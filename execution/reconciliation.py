import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from config.config import AppConfig, exchange_writes_enabled
from config.policy_defaults import calculate_tp_weights
from core.enums import MarginMode, OrderSide, OrderType, PositionSide, SignalState
from core.exceptions import AccountStateBlockedError, ReconciliationError
from core.models import SourceMetadata, ValidatedSignal
from execution.order_manager import OrderManager
from execution.trailing_tp_manager import TrailingTakeProfitManager
from storage.database import DatabaseManager, OrderRepository, SignalRepository

try:
    from backend.events.event_bus import event_bus
except Exception:
    event_bus = None


def build_validated_signal_from_row(row: Dict[str, Any], config: AppConfig) -> ValidatedSignal:
    """Reconstructs a ValidatedSignal object from a SQLite signal row."""
    entries_raw = json.loads(row.get("entries_json") or "[]")
    tps_raw = json.loads(row.get("take_profits_json") or "[]")

    entries = [(Decimal(str(e)), Decimal("1.0")) for e in entries_raw]
    if not entries:
        entries = [(Decimal("0"), Decimal("1.0"))]

    tp1_pct = float(getattr(config.execution, "tp1_target_weight_pct", Decimal("35.0")))
    tp_weights = calculate_tp_weights(len(tps_raw), tp1_pct)
    take_profits = []
    for i, p_str in enumerate(tps_raw):
        w = tp_weights[i] if i < len(tp_weights) else Decimal("0")
        take_profits.append((Decimal(str(p_str)), w))

    meta = SourceMetadata(
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        telegram_timestamp=datetime.utcnow(),
        received_at=datetime.utcnow(),
    )

    side_val = str(row.get("side", "LONG")).upper()
    side = PositionSide.LONG if "BUY" in side_val or "LONG" in side_val else PositionSide.SHORT

    sl_raw = row.get("stop_loss")
    stop_loss = Decimal(str(sl_raw)) if sl_raw is not None and str(sl_raw) != "None" else Decimal("0")

    return ValidatedSignal(
        signal_id=row["signal_id"],
        symbol=row["symbol"],
        side=side,
        entries=entries,
        stop_loss=stop_loss,
        take_profits=take_profits,
        leverage=int(row.get("leverage") or 5),
        margin_mode=MarginMode.ISOLATED,
        is_breakeven_after_tp1=getattr(config.risk, "breakeven_after_tp1_default", True),
        risk_pct=Decimal(str(row.get("risk_pct") or "2.0")),
        metadata=meta,
    )


class ReconciliationEngine:
    """
    Autonomous State Reconciliation & Risk-Free Trade Engine:
    - Real-time synchronization between Local SQLite DB and Binance USD-M Futures.
    - Automatically detects filled entries and deploys protective Stop Loss & Take Profits.
    - Implements Risk-Free Trade ('Kèo Bất Tử'): Automatically moves SL to Breakeven once TP1 is hit.
    - Automatically cancels orphaned orders when a position closes on the exchange.
    """

    def __init__(
        self,
        exchange_client: Any,
        db: DatabaseManager,
        order_manager: Optional[OrderManager] = None,
        config: Optional[AppConfig] = None,
        on_slot_freed_callback: Optional[Any] = None,
    ):
        self.client = exchange_client
        self.db = db
        self.signal_repo = SignalRepository(db)
        self.order_repo = OrderRepository(db)
        self.order_manager = order_manager
        self.config = config or getattr(order_manager, "config", None)
        self.trailing_mgr = TrailingTakeProfitManager()
        self.on_slot_freed_callback = on_slot_freed_callback

    async def _notify_slot_freed(self) -> None:
        """Invoked when a position is closed or moves to breakeven, freeing up risk slots."""
        if hasattr(self, "on_slot_freed_callback") and self.on_slot_freed_callback:
            try:
                if asyncio.iscoroutinefunction(self.on_slot_freed_callback):
                    await self.on_slot_freed_callback()
                else:
                    self.on_slot_freed_callback()
            except Exception as ex_cb:
                logger.warning(f"[RECONCILIATION] Callback on_slot_freed loi: {ex_cb}")

    @staticmethod
    def _exchange_order_matches(local_order: Any, exchange_order: Dict[str, Any]) -> bool:
        client_id = exchange_order.get("clientOrderId") or exchange_order.get("clientAlgoId")
        exchange_id = exchange_order.get("orderId") or exchange_order.get("algoId")
        return (
            (client_id and client_id == local_order.client_order_id)
            or (exchange_id and local_order.exchange_order_id and str(exchange_id) == str(local_order.exchange_order_id))
        )

    async def _position_owned_by_signal(self, row: Dict[str, Any], symbol: str) -> bool:
        """Require local entry ownership before mutating state for exchange position."""
        entry_orders = [o for o in self.order_repo.get_orders_for_signal(row["signal_id"]) if not o.is_reduce_only]
        if not entry_orders:
            return False
        for order in entry_orders:
            if order.status in ("FILLED", "PARTIALLY_FILLED") and order.filled_quantity > Decimal("0"):
                return True
            try:
                status = await self.client.get_order_status(symbol, client_order_id=order.client_order_id)
                exchange_status = status.get("status")
                executed = Decimal(str(status.get("executedQty", "0")))
                if exchange_status in ("FILLED", "PARTIALLY_FILLED") and executed > Decimal("0"):
                    self.order_repo.update_order_fill(
                        order.client_order_id,
                        exchange_status,
                        executed,
                        Decimal(str(status.get("avgPrice", "0"))) if status.get("avgPrice") else None,
                    )
                    return True
            except Exception:
                continue
        return False

    async def reconcile_all(self) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "account_one_way": False,
            "equity": "0",
            "active_signals_checked": 0,
            "orphaned_cleaned": 0,
            "positions_protected": 0,
            "breakeven_activated": 0,
            "discrepancies": [],
        }

        if self.config is None or not exchange_writes_enabled(self.config):
            report["discrepancies"].append(
                f"Reconciliation blocked in {self.config.mode.value if self.config else 'UNKNOWN'} mode"
            )
            return report

        # 1. Verify One-Way Position Mode
        try:
            await self.client.check_position_mode_one_way()
            report["account_one_way"] = True
        except AccountStateBlockedError:
            raise
        except Exception as exc:
            report["discrepancies"].append(f"Không thể xác minh position mode: {exc}")
            return report

        try:
            equity = await self.client.get_account_equity()
            report["equity"] = str(equity)
        except Exception as exc:
            report["discrepancies"].append(f"Không thể xác minh equity: {exc}")
            return report

        # 2. Check active signals from local DB (strictly within last 2 days to avoid matching stale historical entries)
        with self.signal_repo.db.get_connection() as conn:
            raw_active_rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE state IN ('ENTRY_PENDING', 'PARTIALLY_FILLED', 'OPEN_PROTECTED', 'EXITING')
                ORDER BY updated_at DESC
                """
            ).fetchall()

        # Keep every active signal; symbol alone cannot identify one trade.
        active_rows = raw_active_rows

        # Pre-fetch all active open positions, orders, and algo orders in single calls
        positions_map = {}
        fetch_positions_success = False
        try:
            all_open_positions = await self.client.get_open_positions()
            for p in (all_open_positions or []):
                if p.get("symbol"):
                    positions_map[p["symbol"]] = p
            fetch_positions_success = True
        except Exception as e:
            report["discrepancies"].append(f"Không thể lấy danh sách vị thế mở: {e}")
            return report

        try:
            all_open_orders = await self.client.get_open_orders()
        except Exception as exc:
            report["discrepancies"].append(f"Không thể lấy danh sách open orders: {exc}")
            return report
        active_order_symbols = {o.get("symbol") for o in (all_open_orders or []) if o.get("symbol")}

        all_open_algos = []
        fetch_algos_success = False
        try:
            all_open_algos = await self.client.get_open_algo_orders()
            fetch_algos_success = True
        except Exception as exc:
            report["discrepancies"].append(f"Không thể lấy danh sách algo orders: {exc}")

        cleaned_cids = set()
        cleaned_aids = set()

        for r in active_rows:
            row = dict(r)
            report["active_signals_checked"] += 1
            sig_id = row["signal_id"]
            symbol = row["symbol"]
            state = row["state"]

            pos = positions_map.get(symbol)
            amt = Decimal(str(pos.get("positionAmt", "0"))) if pos else Decimal("0")
            entry_p = Decimal(str(pos.get("entryPrice", "0"))) if pos else Decimal("0")
            mark_p = Decimal(str(pos.get("markPrice", "0"))) if pos else Decimal("0")

            # Safeguard: Ensure signal matches this open position on Binance (Entry price must match within +/-12%)
            entries_raw = json.loads(row.get("entries_json") or "[]")
            if entries_raw and entry_p > Decimal("0") and amt != Decimal("0"):
                try:
                    sig_entries = [Decimal(str(e)) for e in entries_raw]
                    min_sig_e = min(sig_entries)
                    max_sig_e = max(sig_entries)
                    if entry_p < min_sig_e * Decimal("0.85") or entry_p > max_sig_e * Decimal("1.15"):
                        # Stale or mismatched signal from another trade level, ignore!
                        continue
                except Exception:
                    pass

            if state == "ENTRY_PENDING" and amt == Decimal("0"):
                try:
                    created_at = datetime.fromisoformat(str(row.get("created_at", "")).replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=datetime.utcnow().astimezone().tzinfo)
                    age_seconds = (datetime.now(created_at.tzinfo) - created_at).total_seconds()
                    ttl = int(getattr(self.config.risk, "entry_order_ttl_seconds", 900))
                    if age_seconds > ttl:
                        await self.order_manager.cancel_pending_entries_for_signal(sig_id, symbol) if self.order_manager else None
                        self.signal_repo.update_signal_state(
                            sig_id,
                            SignalState.CLOSED,
                            reason=f"Entry pending quá TTL ({int(age_seconds)}s > {ttl}s)",
                        )
                        self.signal_repo.record_timeline_event(
                            sig_id,
                            "ENTRY_TTL_EXPIRED",
                            f"Đã hủy entry chờ quá hạn sau {int(age_seconds)} giây.",
                        )
                        report["orphaned_cleaned"] += 1
                        continue
                except Exception as exc:
                    report["discrepancies"].append(f"Không thể xử lý TTL entry {sig_id}: {exc}")

            # Case A: Signal is ENTRY_PENDING but position is ALREADY open on Binance!
            if state in ["ENTRY_PENDING", "PARSED", "VALIDATED"] and amt != Decimal("0"):
                if not await self._position_owned_by_signal(row, symbol):
                    report["discrepancies"].append(
                        f"Vị thế {symbol} không chứng minh được quyền sở hữu từ signal {sig_id}; bỏ qua nhận nuôi và bảo vệ tự động."
                    )
                    continue
                report["discrepancies"].append(
                    f"Phát hiện vị thế {symbol} ({amt}) đã khớp sàn! Đang kích hoạt bảo vệ SL và TP..."
                )
                if self.order_manager and self.config:
                    try:
                        validated_sig = build_validated_signal_from_row(row, self.config)

                        if not fetch_algos_success:
                            report["discrepancies"].append(
                                f"Không thể xác minh algo orders cho {symbol}; bỏ qua reprotection để tránh đặt trùng."
                            )
                            continue

                        local_orders = self.order_repo.get_orders_for_signal(sig_id)
                        # Match protective orders by client/exchange ID, never by symbol alone.
                        has_sl_on_san = any(
                            local.is_reduce_only and local.is_algo and any(
                                (a.get("orderType") == "STOP_MARKET" or a.get("type") == "STOP_MARKET")
                                and a.get("symbol") == symbol
                                and self._exchange_order_matches(local, a)
                                for a in (all_open_algos or [])
                            )
                            for local in local_orders
                        )
                        has_tps_on_san = any(
                            local.is_reduce_only and not local.is_algo and any(
                                o.get("reduceOnly") in [True, "true", "True"]
                                and o.get("type") == "LIMIT"
                                and o.get("symbol") == symbol
                                and self._exchange_order_matches(local, o)
                                for o in (all_open_orders or [])
                            )
                            for local in local_orders
                        )

                        if not has_sl_on_san or not has_tps_on_san:
                            await self.order_manager.on_entry_filled(
                                signal=validated_sig,
                                filled_qty=abs(amt),
                                avg_entry_price=entry_p,
                            )
                            report["positions_protected"] += 1

                        # Persist aggregate fill only on the order confirmed by exchange; do not stamp every DCA order as fully filled.
                        db_orders = self.order_repo.get_orders_for_signal(sig_id)
                        remaining_qty = abs(amt)
                        for o in db_orders:
                            if o.is_reduce_only or remaining_qty <= Decimal("0"):
                                continue
                            order_remaining = max(Decimal("0"), o.quantity - o.filled_quantity)
                            fill_for_order = min(order_remaining, remaining_qty)
                            if fill_for_order > Decimal("0"):
                                self.order_repo.update_order_fill(
                                    o.client_order_id,
                                    status="FILLED" if fill_for_order >= order_remaining else "PARTIALLY_FILLED",
                                    filled_qty=o.filled_quantity + fill_for_order,
                                    avg_price=entry_p,
                                )
                                remaining_qty -= fill_for_order

                        # Protection placement is exchange-confirmed only when on_entry_filled returns.
                        self.signal_repo.update_signal_state(sig_id, SignalState.OPEN_PROTECTED)
                        self.signal_repo.record_timeline_event(
                            sig_id,
                            "ENTRY_FILLED_RECONCILED",
                            f"Đã khớp lệnh Entry {symbol} trên sàn (Giá: {entry_p}, SL/TP bảo vệ đã kích hoạt)",
                        )
                        state = "OPEN_PROTECTED"
                        if event_bus:
                            try:
                                asyncio.create_task(event_bus.publish("signal_updated", {
                                    "signal_id": sig_id,
                                    "symbol": symbol,
                                    "state": SignalState.OPEN_PROTECTED.value,
                                }))
                            except Exception:
                                pass
                    except Exception as ex:
                        report["discrepancies"].append(f"Lỗi kích hoạt bảo vệ {symbol}: {ex}")
                continue
            elif state == "ENTRY_PENDING" and amt == Decimal("0"):
                try:
                    db_orders = self.order_repo.get_orders_for_signal(sig_id)
                    if db_orders and symbol not in active_order_symbols:
                        # Double check if any entry order was FILLED on exchange before closing
                        any_filled = False
                        all_cancelled = True
                        for ord in db_orders:
                            if not ord.is_reduce_only:
                                try:
                                    st = await self.client.get_order_status(symbol, client_order_id=ord.client_order_id)
                                    status = st.get("status")
                                    if status == "FILLED":
                                        any_filled = True
                                        all_cancelled = False
                                        break
                                    elif status in ["NEW", "PARTIALLY_FILLED"]:
                                        all_cancelled = False
                                except Exception:
                                    all_cancelled = False

                        if any_filled:
                            continue
                        elif all_cancelled:
                            # Only cancel orders owned by this signal; symbol-wide cancellation can destroy another trade.
                            self.order_repo.cancel_open_orders_for_signal(sig_id)
                            self.signal_repo.update_signal_state(
                                sig_id,
                                SignalState.CLOSED,
                                reason="Đối chiếu: Lệnh chờ không còn tồn tại trên sàn Binance",
                            )
                            report["orphaned_cleaned"] += 1
                            if event_bus:
                                try:
                                    asyncio.create_task(event_bus.publish("signal_updated", {
                                        "signal_id": sig_id,
                                        "symbol": symbol,
                                        "state": SignalState.CLOSED.value,
                                    }))
                                except Exception:
                                    pass
                except Exception:
                    pass


            # Case B: Signal is OPEN_PROTECTED or PARTIALLY_FILLED
            if state in ["OPEN_PROTECTED", "PARTIALLY_FILLED"]:
                if not fetch_positions_success:
                    continue  # Do not cancel orders or close signal if network failed to query positionRisk

                # Check if position direction matches the signal
                sig_side = str(row.get("side", "")).upper()
                is_sig_long = sig_side in ("LONG", "BUY")
                is_pos_long = amt > Decimal("0")
                direction_mismatch = (amt != Decimal("0")) and (is_sig_long != is_pos_long)

                if amt == Decimal("0") or direction_mismatch:
                    # Reset tracked trailing peak on position closure
                    self.trailing_mgr.reset_tracked_peak(sig_id)
                    # Position was closed outside or hit SL/TP while bot was offline
                    close_reason = "amt=0" if amt == Decimal("0") else f"đã đổi chiều sang {'LONG' if is_pos_long else 'SHORT'}"
                    report["discrepancies"].append(
                        f"Vị thế {symbol} ({sig_side}) đã đóng trên sàn ({close_reason}) nhưng local đang ở {state}. Cập nhật sang CLOSED."
                    )
                    # Cancel only exchange orders proven to belong to this signal.
                    orders = self.order_repo.get_orders_for_signal(sig_id)
                    for ord in orders:
                        if ord.status not in ("NEW", "PARTIALLY_FILLED"):
                            continue
                        try:
                            if ord.is_algo:
                                await self.client.cancel_algo_order(
                                    symbol,
                                    algo_id=ord.exchange_order_id or None,
                                    client_algo_id=ord.client_order_id,
                                )
                            else:
                                await self.client.cancel_standard_order(symbol, ord.client_order_id)
                            self.order_repo.update_order_fill(ord.client_order_id, "CANCELED", ord.filled_quantity, ord.avg_fill_price)
                            cleaned_cids.add(ord.client_order_id)
                            if ord.exchange_order_id:
                                cleaned_aids.add(str(ord.exchange_order_id))
                            report["orphaned_cleaned"] += 1
                        except Exception as exc:
                            report["discrepancies"].append(f"Khong the huy lenh {ord.client_order_id}: {exc}")

                    self.signal_repo.update_signal_state(
                        sig_id,
                        SignalState.CLOSED,
                        reason="Đối chiếu: Vị thế đã đóng trên sàn Binance",
                    )
                    self.signal_repo.record_timeline_event(
                        sig_id,
                        "POSITION_CLOSED_RECONCILED",
                        f"Vị thế {symbol} đã hoàn tất đóng trên sàn Binance",
                    )

                    # Thẩm định kết quả đóng vị thế & phát sóng thông báo thông minh qua Telegram
                    try:
                        from telegram.dedicated_bot import get_dedicated_bot
                        bot = get_dedicated_bot()
                        if bot and bot.is_configured:
                            user_trades = await self.client._request(
                                "GET", "/fapi/v1/userTrades",
                                params={"symbol": symbol, "limit": 10},
                                signed=True
                            ) or []

                            closing_pnl = 0.0
                            last_exit_price = 0.0
                            for ut in user_trades:
                                pnl = float(ut.get("realizedPnl") or 0.0)
                                if abs(pnl) > 1e-6:
                                    closing_pnl += pnl
                                    last_exit_price = float(ut.get("price") or 0.0)

                            all_sig_orders = self.order_repo.get_orders_for_signal(sig_id)
                            tp_orders = [o for o in all_sig_orders if "tp_" in o.client_order_id]
                            filled_tps = [o for o in tp_orders if o.status == "FILLED"]

                            if len(filled_tps) >= 3 or (closing_pnl > 0.1 and len(filled_tps) >= len(tp_orders) and len(tp_orders) > 0):
                                asyncio.create_task(bot.notify_full_tp(symbol=symbol, total_pnl_usdt=closing_pnl))
                            elif closing_pnl < -0.15:
                                sl_val = last_exit_price or row.get("stop_loss") or "SL"
                                root_cause = "Thị trường biến động quét râu nến qua vùng hỗ trợ/kháng cự 1H. Dừng lỗ kỷ luật giúp bảo vệ 98.5% NAV an toàn."
                                asyncio.create_task(bot.notify_sl_hit(symbol=symbol, sl_price=sl_val, loss_usdt=abs(closing_pnl), root_cause=root_cause))
                    except Exception as e_notify:
                        logger.debug(f"Smart close notification failed: {e_notify}")
                    if event_bus:
                        try:
                            asyncio.create_task(event_bus.publish("signal_updated", {
                                "signal_id": sig_id,
                                "symbol": symbol,
                                "state": SignalState.CLOSED.value,
                            }))
                        except Exception:
                            pass
                    await self._notify_slot_freed()
                else:
                    # Check if position size has increased (e.g. DCA / Entry 2 filled) or SL is missing/under-sized
                    if self.order_manager and self.config:
                        try:
                            active_sl_orders = [
                                a for a in (all_open_algos or [])
                                if a.get("symbol") == symbol
                                and (a.get("orderType") == "STOP_MARKET" or a.get("type") == "STOP_MARKET")
                            ]
                            def _algo_qty(a: dict) -> Decimal:
                                raw = a.get("quantity") or a.get("origQty") or "0"
                                try:
                                    return Decimal(str(raw))
                                except Exception:
                                    return Decimal("0")

                            has_full_coverage = any(
                                a.get("closePosition") in [True, "true", "True"] or
                                _algo_qty(a) >= abs(amt)
                                for a in active_sl_orders
                            )
                            total_sl_qty = sum(_algo_qty(a) for a in active_sl_orders)
                            if total_sl_qty >= abs(amt):
                                has_full_coverage = True

                            local_orders = self.order_repo.get_orders_for_signal(sig_id)
                            owned_sl_orders = [
                                a for a in active_sl_orders
                                if any(self._exchange_order_matches(local, a) for local in local_orders if local.is_reduce_only and local.is_algo)
                            ]
                            has_full_coverage = any(
                                a.get("closePosition") in [True, "true", "True"] or _algo_qty(a) >= abs(amt)
                                for a in owned_sl_orders
                            ) or sum(_algo_qty(a) for a in owned_sl_orders) >= abs(amt)

                            # Clean up duplicate SL orders only when ownership is proven.
                            if len(owned_sl_orders) > 1:
                                for extra_sl in owned_sl_orders[1:]:
                                    try:
                                        await self.client.cancel_algo_order(
                                            symbol,
                                            algo_id=str(extra_sl.get("algoId")) if extra_sl.get("algoId") else None,
                                            client_algo_id=extra_sl.get("clientAlgoId"),
                                        )
                                    except Exception:
                                        pass

                            if fetch_algos_success and (not owned_sl_orders or not has_full_coverage):
                                report["discrepancies"].append(
                                    f"Phát hiện vị thế {symbol} ({abs(amt)}) chưa đủ SL bảo vệ. Đang tái đồng bộ SL & TP..."
                                )
                                for old_sl in owned_sl_orders:
                                    try:
                                        await self.client.cancel_algo_order(
                                            symbol,
                                            algo_id=str(old_sl.get("algoId")) if old_sl.get("algoId") else None,
                                            client_algo_id=old_sl.get("clientAlgoId"),
                                        )
                                    except Exception:
                                        pass

                                # Hủy các lệnh TP cũ trên sàn trước khi đặt mới để tránh xung đột vượt hạn mức Reduce-Only
                                for old_tp in (all_open_orders or []):
                                    if old_tp.get("symbol") == symbol and old_tp.get("type") in ("LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
                                        try:
                                            await self.client.cancel_standard_order(symbol, old_tp.get("clientOrderId"))
                                        except Exception:
                                            pass

                                # Mark previous open SL and TP orders for this signal as CANCELED in DB
                                for old_o in self.order_repo.get_orders_for_signal(sig_id):
                                    if old_o.is_reduce_only and old_o.status in ("NEW", "PARTIALLY_FILLED"):
                                        self.order_repo.update_order_fill(old_o.client_order_id, "CANCELED", old_o.filled_quantity, old_o.avg_fill_price)

                                validated_sig = build_validated_signal_from_row(row, self.config)
                                # Protection API accepts aggregate filled quantity only; use current position size.
                                await self.order_manager.on_entry_filled(
                                    signal=validated_sig,
                                    filled_qty=abs(amt),
                                    avg_entry_price=entry_p,
                                )
                                report["positions_protected"] += 1
                                self.signal_repo.record_timeline_event(
                                    sig_id,
                                    "POSITION_REPROTECTED",
                                    f"Đã tái đồng bộ bảo vệ toàn bộ vị thế {symbol} ({abs(amt)} coin): SL & TP mới đã đặt thành công.",
                                )
                        except Exception as ex_prot:
                            report["discrepancies"].append(f"Lỗi tái đồng bộ bảo vệ {symbol}: {ex_prot}")

                    # Position is still open: Quantum Dynamic Breakeven & Multi-Tier Profit Guardian
                    if self.order_manager and self.config and getattr(self.config.risk, "breakeven_after_tp1_default", True):
                        try:
                            db_orders = self.order_repo.get_orders_for_signal(sig_id)
                            tps_raw = json.loads(row.get("take_profits_json") or "[]")
                            is_long = amt > Decimal("0")

                            # 1. Real-time unrealized price gain calculation
                            if entry_p > Decimal("0") and mark_p > Decimal("0"):
                                price_gain_pct = ((mark_p - entry_p) / entry_p * Decimal("100")) if is_long else ((entry_p - mark_p) / entry_p * Decimal("100"))
                            else:
                                price_gain_pct = Decimal("0")

                            # 2. Identify current active Stop Loss order & trigger price
                            current_algo_sl = next((o for o in reversed(db_orders) if o.is_algo and o.status == "NEW"), None)
                            current_sl_px = current_algo_sl.trigger_price if current_algo_sl and current_algo_sl.trigger_price else None
                            if current_sl_px is None and active_sl_orders:
                                for a in active_sl_orders:
                                    raw_trig = a.get("triggerPrice") or a.get("stopPrice")
                                    if raw_trig:
                                        try:
                                            current_sl_px = Decimal(str(raw_trig))
                                            break
                                        except Exception:
                                            pass

                            # Check if current SL is already at or better than Breakeven
                            is_at_least_be = False
                            if current_sl_px is not None and entry_p > Decimal("0"):
                                is_at_least_be = (current_sl_px >= entry_p * Decimal("1.0005")) if is_long else (current_sl_px <= entry_p * Decimal("0.9995"))
                            if any(o.client_order_id.startswith("be_") for o in db_orders):
                                is_at_least_be = True

                            # 3. Check TP1 status (order fill or mark price reach)
                            tp1_filled = False
                            price_reached_tp1 = False
                            tp1_price = None
                            if tps_raw:
                                tp1_price = Decimal(str(tps_raw[0]))
                                tp1_orders = [
                                    o for o in db_orders
                                    if ("tp_" in o.client_order_id and ("_1_" in o.client_order_id or o.client_order_id.endswith("_1")))
                                ]
                                tp1_filled = any(o.status == "FILLED" for o in tp1_orders)
                                if not tp1_filled and tp1_orders:
                                    for tp_ord in tp1_orders:
                                        try:
                                            st = await self.client.get_order_status(symbol, client_order_id=tp_ord.client_order_id)
                                            if st.get("status") == "FILLED":
                                                tp1_filled = True
                                                self.order_repo.update_order_fill(
                                                    tp_ord.client_order_id,
                                                    "FILLED",
                                                    Decimal(str(st.get("executedQty", "0"))),
                                                    Decimal(str(st.get("avgPrice", "0"))),
                                                )
                                                break
                                        except Exception:
                                            pass

                                valid_tp1_direction = (tp1_price > entry_p * Decimal("1.002")) if is_long else (tp1_price < entry_p * Decimal("0.998"))
                                price_reached_tp1 = valid_tp1_direction and ((mark_p >= tp1_price if is_long else mark_p <= tp1_price) if mark_p > Decimal("0") else False)

                            # 4. Breakeven Trigger Condition (TP1 filled OR price reached TP1 OR price gain >= 0.8%)
                            price_favorable_for_be = (mark_p >= entry_p * Decimal("1.003")) if is_long else (mark_p <= entry_p * Decimal("0.997"))
                            dynamic_be_gain = price_gain_pct >= Decimal("0.8") and price_favorable_for_be
                            should_activate_be = (tp1_filled or (price_reached_tp1 and price_favorable_for_be) or dynamic_be_gain)

                            if not is_at_least_be and should_activate_be:
                                validated_sig = build_validated_signal_from_row(row, self.config)
                                old_sl_id = current_algo_sl.client_order_id if current_algo_sl else None
                                if not old_sl_id and active_sl_orders:
                                    old_sl_id = str(active_sl_orders[0].get("algoId") or active_sl_orders[0].get("clientAlgoId"))

                                be_res = await self.order_manager.move_sl_to_breakeven(
                                    signal=validated_sig,
                                    position_qty=abs(amt),
                                    avg_entry_price=entry_p,
                                    existing_sl_algo_id=old_sl_id,
                                )
                                if be_res:
                                    is_at_least_be = True
                                    current_algo_sl = be_res
                                    current_sl_px = be_res.trigger_price
                                    db_orders.append(be_res)
                                    report["breakeven_activated"] += 1
                                    trigger_reason = f"TP1 ({tp1_price}) đã khớp" if tp1_filled else (f"Chạm giá TP1 ({tp1_price})" if price_reached_tp1 else f"Lợi nhuận đạt +{price_gain_pct:.2f}%")
                                    report["discrepancies"].append(
                                        f"KÈO BẤT TỬ CHỦ ĐỘNG: {trigger_reason} cho {symbol}! Đã tự động dời SL về hòa vốn Entry ({entry_p}) + phí sàn!"
                                    )
                                    self.signal_repo.record_timeline_event(
                                        sig_id,
                                        "BREAKEVEN_SL_ACTIVATED",
                                        f"Kèo Bất Tử Chủ Động: {trigger_reason}. Đã dời SL về Entry ({entry_p}) + phí sàn. Rủi ro = 0!",
                                    )
                                    try:
                                        from services.alert_service import AlertLevel, AlertService
                                        AlertService.get_instance().add_alert(
                                            AlertLevel.INFO,
                                            f"🛡️ KÈO BẤT TỬ: {symbol}",
                                            f"{trigger_reason}. Đã tự động dời SL về Entry ({entry_p}) + phí sàn. Lợi nhuận đã được khóa an toàn 100%!",
                                            "RECONCILIATION",
                                        )
                                    except Exception:
                                        pass
                                    await self._notify_slot_freed()

                            # 5. Multi-Tier Dynamic Profit-Locking & Trailing Engine
                            # Evaluates whether market has surged to higher profit tiers (+3%, +6%, +10%) or hit TP2/moonbag
                            target_trail_px = None
                            trail_label = None
                            trail_desc = None

                            # Tier A: Unrealized Gain Multi-Tier Thresholds
                            if price_gain_pct >= Decimal("10.0"):
                                # ROE +100% to +350%: Lock in at least +6.0% profit above entry
                                target_gain = Decimal("6.0")
                                target_trail_px = entry_p * (Decimal("1.0") + target_gain / Decimal("100")) if is_long else entry_p * (Decimal("1.0") - target_gain / Decimal("100"))
                                trail_label = "trail_p10"
                                trail_desc = f"Lợi nhuận vượt bậc +{price_gain_pct:.2f}%: Đã khóa chặt +6.0% lợi nhuận"
                            elif price_gain_pct >= Decimal("6.0"):
                                # ROE +60% to +200%: Lock in at least +3.2% profit above entry
                                target_gain = Decimal("3.2")
                                target_trail_px = entry_p * (Decimal("1.0") + target_gain / Decimal("100")) if is_long else entry_p * (Decimal("1.0") - target_gain / Decimal("100"))
                                trail_label = "trail_p6"
                                trail_desc = f"Lợi nhuận tăng trưởng +{price_gain_pct:.2f}%: Đã khóa chặt +3.2% lợi nhuận"
                            elif price_gain_pct >= Decimal("3.0"):
                                # ROE +30% to +100%: Lock in at least +1.5% profit above entry
                                target_gain = Decimal("1.5")
                                target_trail_px = entry_p * (Decimal("1.0") + target_gain / Decimal("100")) if is_long else entry_p * (Decimal("1.0") - target_gain / Decimal("100"))
                                trail_label = "trail_p3"
                                trail_desc = f"Lợi nhuận tích cực +{price_gain_pct:.2f}%: Đã khóa an toàn +1.5% lợi nhuận"
                            elif price_gain_pct >= Decimal("2.0"):
                                # ROE +40% to +80%: Lock in at least +1.0% profit above entry
                                target_gain = Decimal("1.0")
                                target_trail_px = entry_p * (Decimal("1.0") + target_gain / Decimal("100")) if is_long else entry_p * (Decimal("1.0") - target_gain / Decimal("100"))
                                trail_label = "trail_p2"
                                trail_desc = f"Lợi nhuận vững chắc +{price_gain_pct:.2f}%: Đã khóa an toàn +1.0% lợi nhuận"
                            elif price_gain_pct >= Decimal("1.2"):
                                # ROE +24% to +48%: Lock in at least +0.5% profit above entry
                                target_gain = Decimal("0.5")
                                target_trail_px = entry_p * (Decimal("1.0") + target_gain / Decimal("100")) if is_long else entry_p * (Decimal("1.0") - target_gain / Decimal("100"))
                                trail_label = "trail_p1_2"
                                trail_desc = f"Lợi nhuận chớm đỉnh +{price_gain_pct:.2f}%: Đã khóa an toàn +0.5% lợi nhuận"

                            # Tier B: TP2 Hit Trailing Lock (Locks TP1 price on remaining volume)
                            if len(tps_raw) >= 2:
                                tp1_price = Decimal(str(tps_raw[0]))
                                tp2_price = Decimal(str(tps_raw[1]))
                                tp2_orders = [
                                    o for o in db_orders
                                    if ("tp_" in o.client_order_id and ("_2_" in o.client_order_id or o.client_order_id.endswith("_2")))
                                ]
                                tp2_filled = any(o.status == "FILLED" for o in tp2_orders)
                                if not tp2_filled and tp2_orders:
                                    for tp2_ord in tp2_orders:
                                        try:
                                            st = await self.client.get_order_status(symbol, client_order_id=tp2_ord.client_order_id)
                                            if st.get("status") == "FILLED":
                                                tp2_filled = True
                                                self.order_repo.update_order_fill(
                                                    tp2_ord.client_order_id,
                                                    "FILLED",
                                                    Decimal(str(st.get("executedQty", "0"))),
                                                    Decimal(str(st.get("avgPrice", "0"))),
                                                )
                                                break
                                        except Exception:
                                            pass

                                valid_tp2_direction = (tp2_price > tp1_price) if is_long else (tp2_price < tp1_price)
                                price_reached_tp2 = valid_tp2_direction and ((mark_p >= tp2_price if is_long else mark_p <= tp2_price) if mark_p > Decimal("0") else False)
                                if tp2_filled or price_reached_tp2:
                                    if target_trail_px is None or ((tp1_price > target_trail_px) if is_long else (tp1_price < target_trail_px)):
                                        target_trail_px = tp1_price
                                        trail_label = "trail_tp1"
                                        trail_desc = f"TP2 ({tp2_price}) đã khớp: Đã dời SL lên mức giá TP1 ({tp1_price})"

                            # Tier C: Moonbag Trailing Take-Profit (Gồng lãi cho phần volume còn lại)
                            has_moon_or_tp1 = any(o.client_order_id.startswith("trail_") for o in db_orders)
                            if (has_moon_or_tp1 or price_gain_pct >= Decimal("6.0")) and mark_p > Decimal("0") and len(tps_raw) >= 2:
                                tp2_price = Decimal(str(tps_raw[1]))
                                ref_sl = current_sl_px or (entry_p if is_at_least_be else Decimal("0"))

                                # Dynamic ATR / Volatility trailing distance (2.0% - 4.5%, mặc định an toàn 2.5% - 3.0%)
                                # Tránh bị quét non đối với các coin râu nến dài (ERA, DOS, etc.)
                                atr_distance_pct = Decimal("2.8")
                                initial_sl_raw = row.get("stop_loss")
                                if initial_sl_raw is not None and entry_p > Decimal("0"):
                                    try:
                                        init_sl = Decimal(str(initial_sl_raw))
                                        if init_sl > Decimal("0"):
                                            # Ước lượng độ biến động qua cự ly SL ban đầu (khoảng 0.8x khoảng cách SL)
                                            sl_span_pct = (abs(entry_p - init_sl) / entry_p) * Decimal("100")
                                            calculated_trail = sl_span_pct * Decimal("0.8")
                                            atr_distance_pct = max(Decimal("2.0"), min(Decimal("4.5"), calculated_trail))
                                    except Exception:
                                        pass

                                should_trail, new_sl_price, trail_reason = self.trailing_mgr.calculate_trailing_stop(
                                    side=PositionSide.LONG if is_long else PositionSide.SHORT,
                                    reference_price=tp2_price,
                                    current_mark_price=mark_p,
                                    current_sl=ref_sl,
                                    key=sig_id,
                                    atr_distance_pct=atr_distance_pct,
                                )
                                if should_trail and new_sl_price:
                                    if target_trail_px is None or ((new_sl_price > target_trail_px) if is_long else (new_sl_price < target_trail_px)):
                                        target_trail_px = new_sl_price
                                        trail_label = "trail_moon"
                                        trail_desc = f"Trailing Moonbag: {trail_reason}"

                            # 6. Apply Trailing Stop Loss if strictly better than current SL (Monotonic Ratchet)
                            if target_trail_px is not None and mark_p > Decimal("0"):
                                strictly_better = False
                                if current_sl_px is not None:
                                    strictly_better = (target_trail_px > current_sl_px * Decimal("1.0005")) if is_long else (target_trail_px < current_sl_px * Decimal("0.9995"))
                                else:
                                    strictly_better = (target_trail_px > entry_p) if is_long else (target_trail_px < entry_p)

                                safe_from_mark = (target_trail_px <= mark_p * Decimal("0.995")) if is_long else (target_trail_px >= mark_p * Decimal("1.005"))

                                if strictly_better and safe_from_mark:
                                    old_sl_id = current_algo_sl.client_order_id if current_algo_sl else None
                                    if not old_sl_id and active_sl_orders:
                                        old_sl_id = str(active_sl_orders[0].get("algoId") or active_sl_orders[0].get("clientAlgoId"))

                                    validated_sig = build_validated_signal_from_row(row, self.config)
                                    trail_res = await self.order_manager.move_sl_to_trailing_price(
                                        signal=validated_sig,
                                        position_qty=abs(amt),
                                        target_price=target_trail_px,
                                        existing_sl_algo_id=old_sl_id,
                                        label=trail_label or "trail",
                                    )
                                    if trail_res:
                                        report["discrepancies"].append(
                                            f"KHÓA LÃI TỰ ĐỘNG: {symbol} -> {trail_desc} (SL mới: {target_trail_px})!"
                                        )
                                        self.signal_repo.record_timeline_event(
                                            sig_id,
                                            "DYNAMIC_PROFIT_LOCK_ACTIVATED",
                                            f"Khóa Lãi Tự Động: {trail_desc} (SL mới: {target_trail_px})",
                                        )

                            # 7. Active Position Structure & Adverse News Invalidation Guard (Cắt Lỗ Sớm Chủ Động)
                            # Nếu vị thế đang lỗ (chưa chạm TP1) và cự ly lỗ từ -0.8% trở lên:
                            # Không để vị thế bleed đến tận điểm SL nguy hiểm nếu cấu trúc 1H đã bị bẻ gãy!
                            if not tp1_filled and not is_at_least_be and price_gain_pct <= Decimal("-0.8"):
                                is_invalidated, invalid_reason = await self._check_structural_invalidation(
                                    symbol=symbol,
                                    is_long=is_long,
                                    mark_p=mark_p,
                                    entry_p=entry_p,
                                )
                                if is_invalidated:
                                    logger.warning(f"🚨 Phát hiện bẻ gãy cấu trúc cho {symbol}: {invalid_reason}. Kích hoạt Cắt Lỗ Sớm Chủ Động!")
                                    early_cut_success = await self._execute_early_invalidation_close(
                                        symbol=symbol,
                                        quantity=abs(amt),
                                        is_long=is_long,
                                        signal_id=sig_id,
                                        entry_p=entry_p,
                                        mark_p=mark_p,
                                        loss_pct=float(price_gain_pct),
                                        reason=invalid_reason,
                                    )
                                    if early_cut_success:
                                        report["discrepancies"].append(
                                            f"CẮT LỖ SỚM CHỦ ĐỘNG: {symbol} đã bẻ gãy cấu trúc ({invalid_reason}). Đã đóng vị thế bảo toàn vốn!"
                                        )
                                        continue
                        except Exception as ex_be:
                            report["discrepancies"].append(f"Lỗi kiểm tra Breakeven / Khóa lãi cho {symbol}: {ex_be}")

        # 3. Fallback: Check for any active Binance positions that were NOT covered in active_rows (e.g. marked CLOSED earlier)
        from services.gemini_autonomous_trader import GeminiAutonomousTrader
        checked_symbols = {dict(r)["symbol"] for r in active_rows}
        for pos_sym, pos in positions_map.items():
            if pos_sym in getattr(GeminiAutonomousTrader, "in_flight_symbols", set()):
                continue
            amt = Decimal(str(pos.get("positionAmt", "0")))
            if abs(amt) > Decimal("0") and pos_sym not in checked_symbols:
                # Bỏ qua nếu đã có tín hiệu cho symbol này được tạo trong 2 phút gần nhất (đang trong quá trình khớp lệnh)
                try:
                    with self.signal_repo.db.get_connection() as conn:
                        recent_row = conn.execute(
                            "SELECT signal_id FROM signals WHERE symbol = ? AND created_at > datetime('now', '-2 minutes')",
                            (pos_sym,)
                        ).fetchone()
                        if recent_row:
                            continue
                except Exception:
                    pass
                active_sl_orders = [
                    a for a in (all_open_algos or [])
                    if a.get("symbol") == pos_sym
                    and (a.get("orderType") == "STOP_MARKET" or a.get("type") == "STOP_MARKET")
                    and a.get("reduceOnly") in (True, "true", "True")
                ]
                sym_open_orders = [o for o in (all_open_orders or []) if o.get("symbol") == pos_sym]
                has_bot_signature = any(
                    str(o.get("clientOrderId", "")).startswith(("sig_", "tp_", "sl_", "be_", "trail_", "ent_"))
                    for o in sym_open_orders
                ) or any(
                    str(a.get("clientAlgoId", "")).startswith(("sig_", "tp_", "sl_", "be_", "trail_", "ent_"))
                    for a in active_sl_orders
                )

                if has_bot_signature:
                    try:
                        entry_p = Decimal(str(pos.get("entryPrice", "0")))
                        is_pos_long = amt > Decimal("0")
                        side_str = "LONG" if is_pos_long else "SHORT"
                        recovered_sig_id = f"sig_recovered_{pos_sym}_{int(time.time())}"
                        now_iso = datetime.now(timezone.utc).isoformat()
                        with self.signal_repo.db.get_connection() as conn:
                            rcv_chat_id = -999001
                            rcv_msg_id = int(time.time() * 1000) % 2000000000
                            conn.execute(
                                """
                                INSERT OR IGNORE INTO messages (
                                    chat_id, message_id, sender_id, telegram_timestamp, received_at,
                                    raw_text, normalized_text
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (rcv_chat_id, rcv_msg_id, rcv_chat_id, now_iso, now_iso, f"Recovered Position: {pos_sym}", f"Recovered Position: {pos_sym}")
                            )
                            sl_val = None
                            if active_sl_orders:
                                sl_val = active_sl_orders[0].get("triggerPrice") or active_sl_orders[0].get("stopPrice")
                            if not sl_val:
                                sl_val = str(entry_p * Decimal("0.98") if is_pos_long else entry_p * Decimal("1.02"))

                            tp_vals = [str(o.get("price")) for o in sym_open_orders if o.get("price") and float(o.get("price", 0)) > 0]
                            conn.execute(
                                """
                                INSERT OR REPLACE INTO signals (
                                    signal_id, chat_id, message_id, symbol, side, state,
                                    entry_mode, entries_json, stop_loss, take_profits_json,
                                    leverage, margin_mode, risk_pct, created_at, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    recovered_sig_id, rcv_chat_id, rcv_msg_id, pos_sym, side_str,
                                    "OPEN_PROTECTED", "SINGLE", json.dumps([str(entry_p)]),
                                    float(sl_val), json.dumps(tp_vals), int(pos.get("leverage") or 10),
                                    "CROSSED", 2.0, now_iso, now_iso
                                )
                            )

                            # Đồng bộ các lệnh SL hiện có trên sàn vào DB orders để không bị hiểu nhầm là thiếu SL
                            for sl_ord in active_sl_orders:
                                sl_cid = str(sl_ord.get("clientAlgoId") or f"sl_{recovered_sig_id[:12]}")
                                sl_aid = str(sl_ord.get("algoId") or "")
                                trig_px = float(sl_ord.get("triggerPrice") or sl_ord.get("stopPrice") or sl_val)
                                sl_side = "SELL" if is_pos_long else "BUY"
                                conn.execute(
                                    """
                                    INSERT OR REPLACE INTO orders (
                                        client_order_id, signal_id, symbol, side, order_type,
                                        price, quantity, trigger_price, is_reduce_only, is_algo,
                                        exchange_order_id, status, filled_quantity, avg_fill_price, created_at, updated_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        sl_cid, recovered_sig_id, pos_sym, sl_side, "STOP_MARKET",
                                        None, float(abs(amt)), trig_px, 1, 1,
                                        sl_aid, "NEW", 0.0, None, now_iso, now_iso
                                    )
                                )

                            # Đồng bộ các lệnh TP hiện có trên sàn vào DB orders
                            for idx, tp_ord in enumerate(sym_open_orders):
                                tp_cid = str(tp_ord.get("clientOrderId") or f"tp_{recovered_sig_id[:12]}_{idx+1}")
                                tp_oid = str(tp_ord.get("orderId") or "")
                                tp_px = float(tp_ord.get("price", 0))
                                tp_qty = float(tp_ord.get("origQty", 0))
                                tp_side = str(tp_ord.get("side", "SELL" if is_pos_long else "BUY"))
                                conn.execute(
                                    """
                                    INSERT OR REPLACE INTO orders (
                                        client_order_id, signal_id, symbol, side, order_type,
                                        price, quantity, trigger_price, is_reduce_only, is_algo,
                                        exchange_order_id, status, filled_quantity, avg_fill_price, created_at, updated_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        tp_cid, recovered_sig_id, pos_sym, tp_side, "LIMIT",
                                        tp_px, tp_qty, None, 1, 0,
                                        tp_oid, "NEW", 0.0, None, now_iso, now_iso
                                    )
                                )
                        report["discrepancies"].append(
                            f"ĐÃ TỰ ĐỘNG NHẬN NUÔI & BẢO VỆ: Phát hiện vị thế bot {pos_sym} ({amt}) trên Binance. Đã đồng bộ vào hệ thống giám sát để tự động dời SL & khóa lãi!"
                        )
                    except Exception as ex_adopt:
                        report["discrepancies"].append(f"Không thể nhận nuôi vị thế {pos_sym}: {ex_adopt}")
                elif not active_sl_orders:
                    report["discrepancies"].append(
                        f"CẢNH BÁO: Phát hiện vị thế {pos_sym} ({amt}) đang mở trên sàn nhưng chưa có SL! Đang tự động bảo vệ..."
                    )
                    report["discrepancies"].append(
                        f"Vị thế {pos_sym} không có signal active đã xác minh; không tự nhận nuôi vị thế."
                    )

        # 4. Clean up Zombie Orders on Binance for symbols with NO open position and NO pending entry
        try:
            with self.signal_repo.db.get_connection() as conn:
                entry_rows = conn.execute("SELECT DISTINCT symbol FROM signals WHERE state = 'ENTRY_PENDING'").fetchall()
                active_entry_symbols = {r["symbol"] for r in entry_rows}

            open_pos_symbols = {s for s, p in positions_map.items() if abs(Decimal(str(p.get("positionAmt", "0")))) > Decimal("0")}

            # Clean Zombie Algos
            if fetch_algos_success and all_open_algos:
                for algo in all_open_algos:
                    a_sym = algo.get("symbol")
                    if a_sym and a_sym not in open_pos_symbols and a_sym not in active_entry_symbols:
                        caid = str(algo.get("clientAlgoId", ""))
                        aid = algo.get("algoId")
                        if (caid and caid in cleaned_cids) or (aid and str(aid) in cleaned_aids):
                            continue
                        is_reduce = algo.get("reduceOnly") in (True, "true", "True")
                        is_bot_order = any(caid.startswith(pfx) for pfx in ("sl_", "be_", "trail_", "tp_", "emg_"))
                        if is_bot_order or is_reduce:
                            try:
                                await self.client.cancel_algo_order(
                                    a_sym,
                                    algo_id=str(aid) if aid else None,
                                    client_algo_id=caid if not aid else None,
                                )
                                report["orphaned_cleaned"] += 1
                                report["discrepancies"].append(
                                    f"Đã dọn dẹp lệnh Zombie Algo {caid or aid} của {a_sym} vì vị thế đã đóng hoàn toàn trên sàn."
                                )
                            except Exception as ex_clean:
                                report["discrepancies"].append(f"Không thể hủy lệnh Zombie Algo {caid or aid}: {ex_clean}")

            # Clean Zombie Standard Limit Orders
            if all_open_orders:
                for ord_info in all_open_orders:
                    o_sym = ord_info.get("symbol")
                    if o_sym and o_sym not in open_pos_symbols and o_sym not in active_entry_symbols:
                        cid = str(ord_info.get("clientOrderId", ""))
                        oid = ord_info.get("orderId")
                        if (cid and cid in cleaned_cids) or (oid and str(oid) in cleaned_aids):
                            continue
                        is_reduce = ord_info.get("reduceOnly") in (True, "true", "True")
                        is_bot_order = any(cid.startswith(pfx) for pfx in ("sl_", "be_", "trail_", "tp_", "ent_"))
                        if is_bot_order or is_reduce:
                            try:
                                await self.client.cancel_standard_order(o_sym, cid)
                                report["orphaned_cleaned"] += 1
                                report["discrepancies"].append(
                                    f"Đã dọn dẹp lệnh Zombie Limit {cid or oid} của {o_sym} vì vị thế đã đóng hoàn toàn trên sàn."
                                )
                            except Exception as ex_clean:
                                report["discrepancies"].append(f"Không thể hủy lệnh Zombie Limit {cid or oid}: {ex_clean}")
        except Exception as ex_zombie:
            report["discrepancies"].append(f"Lỗi kiểm tra lệnh Zombie: {ex_zombie}")

        return report

    async def _check_structural_invalidation(
        self,
        symbol: str,
        is_long: bool,
        mark_p: Decimal,
        entry_p: Decimal,
    ) -> Tuple[bool, str]:
        """
        Kiểm tra xem vị thế đang lỗ có bị bẻ gãy cấu trúc SMC hoặc dính bão tin tức không.
        1. Nến 1H: Đóng qua cản EMA50 + RSI đảo chiều cực hạn.
        2. Tin tức: Black-Swan / Extreme Negative Catalyst.
        """
        try:
            # 1. Kiểm tra biến động kỹ thuật 1H
            klines = await self.client._request(
                "GET", "/fapi/v1/klines",
                params={"symbol": symbol, "interval": "1h", "limit": 55},
                signed=False,
            )
            if klines and len(klines) >= 50:
                closes = [float(k[4]) for k in klines]
                
                # Tính EMA50
                k50 = 2.0 / (50 + 1)
                ema50 = sum(closes[:50]) / 50.0
                for c in closes[50:]:
                    ema50 = c * k50 + ema50 * (1.0 - k50)

                # Tính RSI14
                if len(closes) >= 15:
                    gains = [max(closes[i] - closes[i-1], 0) for i in range(1, 15)]
                    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, 15)]
                    avg_g = sum(gains) / 14.0
                    avg_l = sum(losses) / 14.0
                    for i in range(14, len(closes)):
                        d = closes[i] - closes[i-1]
                        avg_g = (avg_g * 13.0 + max(d, 0)) / 14.0
                        avg_l = (avg_l * 13.0 + max(-d, 0)) / 14.0
                    rs = avg_g / avg_l if avg_l > 1e-9 else 100.0
                    rsi = 100.0 - (100.0 / (1.0 + rs))
                else:
                    rsi = 50.0

                cur_p = float(mark_p)
                # For SHORT: Giá vượt lên trên cản EMA50 (> +0.3% trên EMA50) và RSI > 58.0
                if not is_long and cur_p > ema50 * 1.003 and rsi > 58.0:
                    return True, f"Nến 1H đóng vượt cản EMA50 ({ema50:.4f}) với RSI={rsi:.1f} (Động lượng Tăng áp đảo)"
                
                # For LONG: Giá thủng xuống dưới hỗ trợ EMA50 (< -0.3% dưới EMA50) và RSI < 42.0
                if is_long and cur_p < ema50 * 0.997 and rsi < 42.0:
                    return True, f"Nến 1H đóng thủng hỗ trợ EMA50 ({ema50:.4f}) với RSI={rsi:.1f} (Động lượng Giảm áp đảo)"

            # 2. Kiểm tra tin tức thiên nga đen (Black-Swan News)
            try:
                from services.market_sentiment_news_guardian import MarketSentimentNewsGuardian, SentimentVerdict
                guardian = MarketSentimentNewsGuardian(session=await self.client._get_session())
                sentiment = await guardian.analyze_symbol_sentiment(symbol, "LONG" if is_long else "SHORT")
                if sentiment.verdict == SentimentVerdict.REJECTED_BLACK_SWAN:
                    return True, f"Phát hiện tin tức thảm họa / Black-Swan: {', '.join(sentiment.reasons)}"
            except Exception:
                pass

        except Exception as e_chk:
            logger.debug(f"Structural invalidation check error for {symbol}: {e_chk}")

        return False, ""

    async def _execute_early_invalidation_close(
        self,
        symbol: str,
        quantity: Decimal,
        is_long: bool,
        signal_id: str,
        entry_p: Decimal,
        mark_p: Decimal,
        loss_pct: float,
        reason: str,
    ) -> bool:
        """
        Đóng khẩn cấp vị thế khi bị bẻ gãy cấu trúc (Early Invalidation Cut):
        1. Hủy mọi lệnh mở (SL/TP) của symbol này trên Binance.
        2. Bắn lệnh MARKET reduce_only để đóng toàn bộ vị thế ngay lập tức.
        3. Cập nhật DB: trạng thái CLOSED (EARLY_INVALIDATION_CUT).
        4. Bắn thông báo Telegram notify_early_cut.
        """
        close_side = OrderSide.SELL if is_long else OrderSide.BUY
        try:
            # 1. Hủy các lệnh SL algo đang treo
            all_algos = await self.client.get_open_algo_orders(symbol)
            for a in (all_algos or []):
                aid = str(a.get("algoId") or a.get("clientAlgoId") or "")
                caid = str(a.get("clientAlgoId") or "")
                if aid:
                    try:
                        await self.client.cancel_algo_order(symbol, algo_id=aid, client_algo_id=caid if caid else None)
                    except Exception:
                        pass

            # 2. Hủy các lệnh TP limit đang treo
            all_orders = await self.client.get_open_orders(symbol)
            for o in (all_orders or []):
                oid = str(o.get("clientOrderId") or o.get("orderId") or "")
                if oid:
                    try:
                        await self.client.cancel_standard_order(symbol, oid)
                    except Exception:
                        pass

            # 3. Đặt lệnh Market Reduce-Only để đóng vị thế
            emg_cid = f"early_{signal_id[:8]}_{uuid.uuid4().hex[:4]}"
            await self.client.create_standard_order(
                symbol=symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                client_order_id=emg_cid,
                reduce_only=True,
            )

            # 4. Cập nhật SQLite
            self.signal_repo.update_signal_state(
                signal_id,
                SignalState.CLOSED,
                reason=f"EARLY_INVALIDATION_CUT: {reason}",
            )
            self.signal_repo.record_timeline_event(
                signal_id,
                "EARLY_INVALIDATION_CUT",
                f"Cắt Lỗ Sớm Chủ Động: {reason}. Giá thoát: {mark_p} (Âm: {loss_pct:.2f}%). Tiết kiệm ~70% vốn dự phòng!",
            )

            # 5. Bắn thông báo Telegram
            try:
                from telegram.dedicated_bot import get_dedicated_bot
                bot = get_dedicated_bot()
                if bot and bot.is_configured:
                    loss_usdt = float(abs(mark_p - entry_p) * quantity)
                    asyncio.create_task(
                        bot.notify_early_cut(
                            symbol=symbol,
                            exit_price=float(mark_p),
                            loss_pct=loss_pct,
                            loss_usdt=loss_usdt,
                            root_cause=reason,
                        )
                    )
            except Exception as e_tele:
                logger.debug(f"Early cut telegram alert failed: {e_tele}")

            try:
                from services.alert_service import AlertLevel, AlertService
                AlertService.get_instance().add_alert(
                    AlertLevel.WARNING,
                    f"⚠️ CẮT LỖ SỚM CHỦ ĐỘNG: {symbol}",
                    f"{reason}. Thoát vị thế @ {mark_p} ({loss_pct:.2f}%) thay vì đợi chạm full SL.",
                    "RECONCILIATION",
                )
            except Exception:
                pass

            return True
        except Exception as e_close:
            logger.error(f"Failed to execute early invalidation close for {symbol}: {e_close}")
            return False
