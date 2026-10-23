import asyncio
import json
import threading
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from config.config import AppConfig
from core.enums import ExecutionMode, SignalState
from storage.database import DatabaseManager, OrderRepository, SignalRepository
from telegram.listener import TelegramSignalListener


class EngineStatus(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING_SHADOW = "RUNNING_SHADOW"
    RUNNING_LISTEN = "RUNNING_LISTEN"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class ProtectionStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class TradingService:
    """
    Application service for trading engine lifecycle and state inspection.
    Strict Invariants:
    - Single-instance engine guard (prevents starting duplicate runners).
    - Read-only querying for UI presentation.
    - Resolves protection status accurately without assuming DB SL == Exchange SL.
    """

    def __init__(self, db: DatabaseManager, config: AppConfig):
        self.db = db
        self.config = config
        self.signal_repo = SignalRepository(db)
        self.order_repo = OrderRepository(db)
        self._engine_status = EngineStatus.STOPPED
        self._entry_enabled = True
        self._engine_lock = threading.Lock()
        self._engine_task: Optional[asyncio.Task] = None
        self._listener: Optional[TelegramSignalListener] = None

    def get_engine_status(self) -> EngineStatus:
        with self._engine_lock:
            return self._engine_status

    def set_engine_status(self, status: EngineStatus) -> None:
        with self._engine_lock:
            self._engine_status = status

    def is_entry_enabled(self) -> bool:
        with self._engine_lock:
            return self._entry_enabled

    def set_entry_enabled(self, enabled: bool) -> None:
        with self._engine_lock:
            self._entry_enabled = enabled

    def get_signals(
        self,
        state_filter: Optional[str] = None,
        symbol_search: Optional[str] = None,
        limit: int = 200,
        only_allowed: bool = True,
    ) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            query = """
                SELECT s.*, m.telegram_timestamp AS telegram_time
                FROM signals s
                LEFT JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
                WHERE s.symbol IS NOT NULL AND s.symbol != '' AND s.symbol != 'UNKNOWN' AND s.symbol != 'None'
            """
            params: List[Any] = []

            allowed_ids = getattr(self.config.telegram, "allowed_chat_ids", [])
            if only_allowed and allowed_ids:
                placeholders = ",".join("?" for _ in allowed_ids)
                query += f" AND (s.chat_id IN ({placeholders}) OR s.chat_id = -999001 OR s.signal_id LIKE 'sig_ai_%')"
                params.extend(allowed_ids)

            if state_filter and state_filter != "ALL":
                query += " AND s.state = ?"
                params.append(state_filter)

            if symbol_search:
                query += " AND s.symbol LIKE ?"
                params.append(f"%{symbol_search.strip().upper()}%")

            query += " ORDER BY COALESCE(m.telegram_timestamp, s.created_at) DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            from services.channel_analytics_service import KNOWN_CHANNELS
            formatted = []
            for r in rows:
                item = self.signal_repo._format_signal_row(r)
                if item:
                    # Sync telegram_timestamp so frontend displays exact post time
                    item["telegram_timestamp"] = item.get("telegram_time") or item.get("telegram_timestamp") or item.get("created_at")
                    chat_id = item.get("chat_id")
                    sig_id = str(item.get("signal_id", ""))
                    if chat_id == -999001 or sig_id.startswith("sig_ai_"):
                        item["channel_name"] = "🤖 AI Quant (Argon 4)"
                        item["source_type"] = "AI"
                    else:
                        item["channel_name"] = KNOWN_CHANNELS.get(chat_id, "Khác")
                        item["source_type"] = "TELEGRAM"
                    formatted.append(item)
            return formatted

    def get_signal_detail(self, signal_id: str) -> Optional[Dict[str, Any]]:
        sig = self.signal_repo.get_signal(signal_id)
        if not sig:
            return None

        # Fetch message raw text
        with self.db.get_connection() as conn:
            msg_row = conn.execute(
                "SELECT * FROM messages WHERE chat_id = ? AND message_id = ?",
                (sig["chat_id"], sig["message_id"]),
            ).fetchone()
            versions = conn.execute(
                "SELECT * FROM message_versions WHERE chat_id = ? AND message_id = ? ORDER BY version ASC",
                (sig["chat_id"], sig["message_id"]),
            ).fetchall()

        timeline = self.signal_repo.get_timeline(signal_id)
        orders = self.order_repo.get_orders_for_signal(signal_id)

        from services.channel_analytics_service import KNOWN_CHANNELS
        sig["channel_name"] = KNOWN_CHANNELS.get(sig.get("chat_id"), "Khác")

        return {
            "signal": sig,
            "raw_message": dict(msg_row) if msg_row else {},
            "versions": [dict(v) for v in versions],
            "timeline": timeline,
            "orders": [o.model_dump() for o in orders],
        }

    def get_open_positions(
        self,
        binance_positions: Optional[List[Dict[str, Any]]] = None,
        binance_orders: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves active positions from Binance (if available) or DB and assesses protection status.
        Cross-checks both local DB orders and live Binance open/algo orders.
        """
        if binance_positions is not None:
            results = []
            for bp in binance_positions:
                try:
                    amt = float(bp.get("positionAmt", 0))
                    if amt == 0:
                        continue
                    sym = bp.get("symbol", "")
                    side = "LONG" if amt > 0 else "SHORT"
                    entry_p = str(bp.get("entryPrice", "0"))
                    mark_p = str(bp.get("markPrice", "0"))
                    unpnl = str(bp.get("unRealizedProfit", "0"))
                    lev = int(bp.get("leverage", 1))
                    mtype = str(bp.get("marginType", "isolated")).upper()

                    sl_id = None
                    sl_price = None
                    tp_ids = []
                    source_type = "MANUAL"
                    source_label = "👤 Thủ công"

                    with self.db.get_connection() as conn:
                        sl_rows = conn.execute(
                            "SELECT client_order_id, trigger_price FROM orders WHERE symbol = ? AND is_algo = 1 AND status IN ('NEW', 'PARTIALLY_FILLED')",
                            (sym,),
                        ).fetchall()
                        if sl_rows:
                            sl_id = sl_rows[0]["client_order_id"]
                            if sl_rows[0]["trigger_price"]:
                                sl_price = str(sl_rows[0]["trigger_price"])

                        tp_rows = conn.execute(
                            "SELECT client_order_id FROM orders WHERE symbol = ? AND is_reduce_only = 1 AND is_algo = 0 AND status IN ('NEW', 'PARTIALLY_FILLED')",
                            (sym,),
                        ).fetchall()
                        tp_ids = [r["client_order_id"] for r in tp_rows]

                        # Detect signal origin (AI vs Telegram vs Manual)
                        from services.channel_analytics_service import KNOWN_CHANNELS
                        sig_row = conn.execute(
                            """
                            SELECT s.signal_id, s.chat_id, o.client_order_id
                            FROM orders o
                            LEFT JOIN signals s ON o.signal_id = s.signal_id
                            WHERE o.symbol = ?
                            ORDER BY o.created_at DESC LIMIT 1
                            """,
                            (sym,),
                        ).fetchone()
                        if not sig_row:
                            sig_row = conn.execute(
                                "SELECT signal_id, chat_id FROM signals WHERE symbol = ? ORDER BY created_at DESC LIMIT 1",
                                (sym,),
                            ).fetchone()

                        if sig_row:
                            cid = str(sig_row["client_order_id"] or "")
                            s_id = str(sig_row["signal_id"] or "")
                            c_id = sig_row["chat_id"]
                            if c_id == -999001 or s_id.startswith("sig_ai_") or "sig_ai_" in cid:
                                source_type = "AI"
                                source_label = "🤖 AI Quant (Argon 4)"
                            elif c_id in KNOWN_CHANNELS:
                                source_type = "TELEGRAM"
                                source_label = f"📢 {KNOWN_CHANNELS[c_id]}"
                            elif c_id:
                                source_type = "TELEGRAM"
                                source_label = "📢 Telegram"

                    # Real-time reconciliation with live Binance orders
                    if binance_orders is not None:
                        live_sl = None
                        live_sl_price = None
                        live_tps = []
                        for bo in binance_orders:
                            if bo.get("symbol") == sym:
                                o_type = str(bo.get("type", "")).upper()
                                cid = str(bo.get("clientOrderId", "") or bo.get("clientAlgoId", ""))
                                oid = str(bo.get("orderId", "") or bo.get("algoId", ""))

                                is_sl = "STOP" in o_type or cid.startswith("sl_") or cid.startswith("be_") or cid.startswith("trail_")
                                is_tp = "TAKE_PROFIT" in o_type or cid.startswith("tp_") or (bo.get("reduceOnly") and not is_sl and ("LIMIT" in o_type or "TAKE_PROFIT" in o_type))

                                if is_sl:
                                    live_sl = cid or oid
                                    trig_px = bo.get("triggerPrice") or bo.get("stopPrice") or bo.get("price") or bo.get("activatePrice")
                                    if trig_px and float(trig_px) > 0:
                                        live_sl_price = str(trig_px)
                                elif is_tp:
                                    live_tps.append(cid or oid)

                                # Check clientOrderId signature directly
                                if "sig_ai_" in cid:
                                    source_type = "AI"
                                    source_label = "🤖 AI Quant (Argon 4)"
                                elif "sig_-100" in cid and source_type == "MANUAL":
                                    source_type = "TELEGRAM"
                                    source_label = "📢 Telegram"

                        if live_sl:
                            sl_id = live_sl
                        if live_sl_price:
                            sl_price = live_sl_price
                        # Always reflect true live orders on exchange
                        if live_tps or binance_orders:
                            tp_ids = live_tps

                    margin_val = float(bp.get("initialMargin") or (abs(amt) * float(entry_p) / max(lev, 1)))
                    notional_val = float(bp.get("notional") or (abs(amt) * float(entry_p)))
                    roe_val = (float(unpnl) / margin_val * 100.0) if margin_val > 0 else 0.0

                    results.append({
                        "symbol": sym,
                        "side": side,
                        "amount": f"{abs(amt):.4f}".rstrip("0").rstrip("."),
                        "initial_margin": f"{margin_val:.2f}",
                        "notional": f"{notional_val:.2f}",
                        "entry_price": entry_p,
                        "mark_price": mark_p,
                        "unrealized_pnl": unpnl,
                        "roe_pct": f"{roe_val:+.2f}%",
                        "leverage": lev,
                        "margin_type": mtype,
                        "sl_order_id": sl_id,
                        "sl_price": sl_price,
                        "tp_order_ids": tp_ids,
                        "source_type": source_type,
                        "source_label": source_label,
                    })
                except Exception:
                    pass
            return results

        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM positions WHERE quantity != '0'").fetchall()
            positions = []
            for r in rows:
                pos = dict(r)
                q_val = float(pos.get("quantity") or 0)
                ep_val = float(pos.get("entry_price") or 0)
                lev_val = int(pos.get("leverage") or 1)
                pos["amount"] = f"{abs(q_val):.4f}".rstrip("0").rstrip(".")
                pos["initial_margin"] = f"{(abs(q_val) * ep_val / max(lev_val, 1)):.2f}"
                pos["notional"] = f"{(abs(q_val) * ep_val):.2f}"
                algo_orders = conn.execute(
                    """
                    SELECT * FROM orders
                    WHERE symbol = ? AND is_algo = 1 AND is_reduce_only = 1 AND status IN ('NEW', 'PARTIALLY_FILLED')
                    """,
                    (pos["symbol"],),
                ).fetchall()

                if algo_orders:
                    pos["protection_status"] = ProtectionStatus.CONFIRMED.value
                    pos["sl_price"] = algo_orders[0]["trigger_price"]
                else:
                    pos["protection_status"] = ProtectionStatus.MISSING.value
                    pos["sl_price"] = "N/A"

                pos_margin = float(pos.get("initial_margin") or 1)
                unpnl_val = float(pos.get("unrealized_pnl") or 0)
                pos["roe_pct"] = f"{(unpnl_val / pos_margin * 100.0):+.2f}%" if pos_margin > 0 else "+0.00%"
                pos["source_type"] = "TELEGRAM"
                pos["source_label"] = "📢 Telegram"

                positions.append(pos)
            return positions

    def get_active_orders(self, binance_orders: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        if binance_orders is not None:
            results = []
            for bo in binance_orders:
                try:
                    time_val = bo.get("time") or bo.get("updateTime")
                    c_time = datetime.fromtimestamp(time_val / 1000).isoformat() if time_val else datetime.utcnow().isoformat()
                    results.append({
                        "order_id": str(bo.get("orderId")),
                        "client_order_id": str(bo.get("clientOrderId", "")),
                        "symbol": str(bo.get("symbol")),
                        "side": str(bo.get("side")),
                        "type": str(bo.get("type")),
                        "price": str(bo.get("price", "0")),
                        "orig_qty": str(bo.get("origQty", "0")),
                        "executed_qty": str(bo.get("executedQty", "0")),
                        "status": str(bo.get("status", "NEW")),
                        "created_at": c_time,
                    })
                except Exception:
                    pass
            return results

        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status IN ('NEW', 'PARTIALLY_FILLED') ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_pending_review_signals(self) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM signals WHERE state IN ('NEEDS_REVIEW', 'NEEDS_POLICY') ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_signal_policy(
        self,
        signal_id: str,
        new_state: SignalState,
        reason: str,
    ) -> bool:
        """
        Resolves a signal in NEEDS_REVIEW or NEEDS_POLICY.
        Enforces age check to ensure stale signals cannot be forced to ACTIVE.
        """
        sig = self.signal_repo.get_signal(signal_id)
        if not sig:
            return False

        if new_state in (SignalState.VALIDATED, SignalState.ENTRY_PENDING):
            try:
                sig_time = datetime.fromisoformat(sig["created_at"])
                age_seconds = (datetime.utcnow() - sig_time.replace(tzinfo=None)).total_seconds()
                max_age = getattr(self.config.risk, "signal_max_age_seconds", 300)
                if age_seconds > max_age:
                    self.signal_repo.update_signal_state(
                        signal_id, SignalState.REJECTED, f"Tín hiệu đã quá hạn thời gian vào lệnh ({int(age_seconds)}s > {max_age}s)"
                    )
                    return False
            except Exception:
                pass

        self.signal_repo.update_signal_state(signal_id, new_state, reason)
        self.signal_repo.record_timeline_event(
            signal_id,
            "POLICY_RESOLVED",
            f"Người dùng thủ công cập nhật trạng thái: {new_state.value}. Lý do: {reason}",
        )
        return True

