import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from config.config import AppConfig
from config.policy_defaults import calculate_tp_weights
from core.enums import MarginMode, PositionSide, SignalState
from core.exceptions import AccountStateBlockedError, ReconciliationError
from core.models import SourceMetadata, ValidatedSignal
from execution.order_manager import OrderManager
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

    tp1_pct = float(getattr(config.execution, "tp1_target_weight_pct", Decimal("60.0")))
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

    return ValidatedSignal(
        signal_id=row["signal_id"],
        symbol=row["symbol"],
        side=side,
        entries=entries,
        stop_loss=Decimal(str(row["stop_loss"])),
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
    ):
        self.client = exchange_client
        self.db = db
        self.signal_repo = SignalRepository(db)
        self.order_repo = OrderRepository(db)
        self.order_manager = order_manager
        self.config = config or getattr(order_manager, "config", None)

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

        # 1. Verify One-Way Position Mode
        try:
            await self.client.check_position_mode_one_way()
            report["account_one_way"] = True
        except AccountStateBlockedError:
            raise
        except Exception:
            pass

        try:
            equity = await self.client.get_account_equity()
            report["equity"] = str(equity)
        except Exception:
            pass

        # 2. Check active signals from local DB
        with self.signal_repo.db.get_connection() as conn:
            active_rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE state IN ('VALIDATED', 'ENTRY_PENDING', 'PARTIALLY_FILLED', 'OPEN_PROTECTED', 'EXITING')
                """
            ).fetchall()

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

        all_open_orders = []
        try:
            all_open_orders = await self.client.get_open_orders()
        except Exception:
            pass
        active_order_symbols = {o.get("symbol") for o in (all_open_orders or []) if o.get("symbol")}

        all_open_algos = []
        try:
            all_open_algos = await self.client.get_open_algo_orders()
        except Exception:
            pass

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

            # Case A: Signal is ENTRY_PENDING but position is ALREADY open on Binance!
            if state in ["ENTRY_PENDING", "PARSED", "VALIDATED"] and amt != Decimal("0"):
                report["discrepancies"].append(
                    f"Phát hiện vị thế {symbol} ({amt}) đã khớp sàn! Đang kích hoạt bảo vệ SL và TP..."
                )
                if self.order_manager and self.config:
                    try:
                        validated_sig = build_validated_signal_from_row(row, self.config)

                        # Check existing open algos on Binance
                        has_sl_on_san = any(
                            (a.get("orderType") == "STOP_MARKET" or a.get("type") == "STOP_MARKET")
                            and a.get("symbol") == symbol
                            for a in (all_open_algos or [])
                        )

                        # Check existing TP limit orders on Binance
                        has_tps_on_san = any(
                            o.get("reduceOnly") in [True, "true", "True"]
                            and o.get("type") == "LIMIT"
                            and o.get("symbol") == symbol
                            for o in (all_open_orders or [])
                        )

                        if not has_sl_on_san or not has_tps_on_san:
                            await self.order_manager.on_entry_filled(
                                signal=validated_sig,
                                filled_qty=abs(amt),
                                avg_entry_price=entry_p,
                            )
                            report["positions_protected"] += 1

                        # Update DB entry orders to FILLED
                        db_orders = self.order_repo.get_orders_for_signal(sig_id)
                        for o in db_orders:
                            if not o.is_reduce_only and o.status != "FILLED":
                                self.order_repo.update_order_fill(
                                    o.client_order_id,
                                    status="FILLED",
                                    filled_qty=abs(amt),
                                    avg_price=entry_p,
                                )

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
                            self.order_repo.cancel_open_orders_for_symbol(symbol)
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
                if amt == Decimal("0"):
                    # Position was closed outside or hit SL/TP while bot was offline
                    report["discrepancies"].append(
                        f"Vị thế {symbol} đã đóng trên sàn (amt=0) nhưng local đang ở {state}. Cập nhật sang CLOSED."
                    )
                    try:
                        await self.client.cancel_all_symbol_orders(symbol)
                    except Exception:
                        pass

                    orders = self.order_repo.get_orders_for_signal(sig_id)
                    for ord in orders:
                        if ord.status in ["NEW", "PARTIALLY_FILLED"]:
                            self.order_repo.update_order_fill(ord.client_order_id, "CANCELED", ord.filled_quantity, ord.avg_fill_price)
                            report["orphaned_cleaned"] += 1

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
                    if event_bus:
                        try:
                            asyncio.create_task(event_bus.publish("signal_updated", {
                                "signal_id": sig_id,
                                "symbol": symbol,
                                "state": SignalState.CLOSED.value,
                            }))
                        except Exception:
                            pass
                else:
                    # Check if position size has increased (e.g. DCA / Entry 2 filled) or SL is missing/under-sized
                    if self.order_manager and self.config:
                        try:
                            active_sl_orders = [
                                a for a in (all_open_algos or [])
                                if a.get("symbol") == symbol
                                and (a.get("orderType") == "STOP_MARKET" or a.get("type") == "STOP_MARKET")
                            ]
                            # A STOP_MARKET with closePosition=True or qty=None/0 covers 100% of the position!
                            has_full_coverage = any(
                                a.get("closePosition") in [True, "true", "True"] or
                                not a.get("origQty") or str(a.get("origQty")) == "0" or
                                Decimal(str(a.get("origQty", "0"))) >= abs(amt)
                                for a in active_sl_orders
                            )
                            total_sl_qty = sum(Decimal(str(a.get("origQty") or a.get("quantity") or "0")) for a in active_sl_orders)
                            if total_sl_qty >= abs(amt):
                                has_full_coverage = True

                            # Clean up duplicate SL orders if more than 1
                            if len(active_sl_orders) > 1:
                                for extra_sl in active_sl_orders[1:]:
                                    try:
                                        await self.client.cancel_algo_order(
                                            symbol,
                                            algo_id=str(extra_sl.get("algoId")) if extra_sl.get("algoId") else None,
                                            client_algo_id=extra_sl.get("clientAlgoId"),
                                        )
                                    except Exception:
                                        pass

                            if not active_sl_orders or not has_full_coverage:
                                report["discrepancies"].append(
                                    f"Phát hiện vị thế {symbol} ({abs(amt)}) chưa đủ SL bảo vệ. Đang tái đồng bộ SL & TP..."
                                )
                                for old_sl in active_sl_orders:
                                    try:
                                        await self.client.cancel_algo_order(
                                            symbol,
                                            algo_id=str(old_sl.get("algoId")) if old_sl.get("algoId") else None,
                                            client_algo_id=old_sl.get("clientAlgoId"),
                                        )
                                    except Exception:
                                        pass
                                try:
                                    await self.client.cancel_all_orders(symbol)
                                except Exception:
                                    pass

                                validated_sig = build_validated_signal_from_row(row, self.config)
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

                    # Position is still open: Check Break-even trigger (Kèo Bất Tử)
                    if self.order_manager and self.config and getattr(self.config.risk, "breakeven_after_tp1_default", True):
                        try:
                            db_orders = self.order_repo.get_orders_for_signal(sig_id)
                            has_be = any(o.client_order_id.startswith("be_") for o in db_orders)
                            if not has_be:
                                tps_raw = json.loads(row.get("take_profits_json") or "[]")
                                if tps_raw:
                                    tp1_price = Decimal(str(tps_raw[0]))
                                    is_long = amt > Decimal("0")
                                    tp1_reached = (mark_p >= tp1_price) if is_long else (mark_p <= tp1_price)
                                    if tp1_reached:
                                        validated_sig = build_validated_signal_from_row(row, self.config)
                                        old_sl_id = None
                                        for o in db_orders:
                                            if o.is_algo and o.status == "NEW" and not o.client_order_id.startswith("be_"):
                                                old_sl_id = o.client_order_id
                                                break
                                        await self.order_manager.move_sl_to_breakeven(
                                            signal=validated_sig,
                                            position_qty=abs(amt),
                                            avg_entry_price=entry_p,
                                            existing_sl_algo_id=old_sl_id,
                                        )
                                        report["breakeven_activated"] += 1
                                        report["discrepancies"].append(
                                            f"KÈO BẤT TỬ: Giá Mark {symbol} ({mark_p}) đã vượt TP1 ({tp1_price}). Đã dời SL về hòa vốn!"
                                        )
                                        self.signal_repo.record_timeline_event(
                                            sig_id,
                                            "BREAKEVEN_SL_ACTIVATED",
                                            f"Kèo Bất Tử: Giá ({mark_p}) đã chạm/vượt TP1 ({tp1_price}). Đã dời SL về Entry ({entry_p}) + phí!",
                                        )
                        except Exception as ex_be:
                            report["discrepancies"].append(f"Lỗi kiểm tra Breakeven cho {symbol}: {ex_be}")

        # 3. Fallback: Check for any active Binance positions that were NOT covered in active_rows (e.g. marked CLOSED earlier)
        checked_symbols = {dict(r)["symbol"] for r in active_rows}
        for pos_sym, pos in positions_map.items():
            amt = Decimal(str(pos.get("positionAmt", "0")))
            if abs(amt) > Decimal("0") and pos_sym not in checked_symbols:
                active_sl_orders = [
                    a for a in (all_open_algos or [])
                    if a.get("symbol") == pos_sym
                    and (a.get("orderType") == "STOP_MARKET" or a.get("type") == "STOP_MARKET")
                ]
                if not active_sl_orders:
                    report["discrepancies"].append(
                        f"CẢNH BÁO: Phát hiện vị thế {pos_sym} ({amt}) đang mở trên sàn nhưng chưa có SL! Đang tự động bảo vệ..."
                    )
                    with self.signal_repo.db.get_connection() as conn:
                        sig_row = conn.execute(
                            "SELECT * FROM signals WHERE symbol = ? AND state != 'REJECTED' ORDER BY created_at DESC LIMIT 1",
                            (pos_sym,),
                        ).fetchone()
                    if sig_row and self.order_manager and self.config:
                        try:
                            val_sig = build_validated_signal_from_row(dict(sig_row), self.config)
                            entry_p = Decimal(str(pos.get("entryPrice", "0")))
                            await self.order_manager.on_entry_filled(
                                signal=val_sig,
                                filled_qty=abs(amt),
                                avg_entry_price=entry_p,
                            )
                            self.signal_repo.update_signal_state(val_sig.signal_id, SignalState.OPEN_PROTECTED)
                            report["positions_protected"] += 1
                        except Exception as ex_prot:
                            report["discrepancies"].append(f"Lỗi tự động bảo vệ vị thế mở {pos_sym}: {ex_prot}")

        return report
