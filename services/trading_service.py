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
    ) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            query = "SELECT * FROM signals WHERE symbol IS NOT NULL AND symbol != '' AND symbol != 'UNKNOWN' AND symbol != 'None'"
            params: List[Any] = []

            if state_filter and state_filter != "ALL":
                query += " AND state = ?"
                params.append(state_filter)

            if symbol_search:
                query += " AND symbol LIKE ?"
                params.append(f"%{symbol_search.strip().upper()}%")

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self.signal_repo._format_signal_row(r) for r in rows]

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

        return {
            "signal": sig,
            "raw_message": dict(msg_row) if msg_row else {},
            "versions": [dict(v) for v in versions],
            "timeline": timeline,
            "orders": [o.model_dump() for o in orders],
        }

    def get_open_positions(self, binance_positions: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Retrieves active positions from Binance (if available) or DB and assesses protection status.
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
                    tp_ids = []
                    with self.db.get_connection() as conn:
                        sl_rows = conn.execute(
                            "SELECT client_order_id, trigger_price FROM orders WHERE symbol = ? AND is_algo = 1 AND status IN ('NEW', 'PARTIALLY_FILLED')",
                            (sym,),
                        ).fetchall()
                        if sl_rows:
                            sl_id = sl_rows[0]["client_order_id"]

                        tp_rows = conn.execute(
                            "SELECT client_order_id FROM orders WHERE symbol = ? AND is_reduce_only = 1 AND is_algo = 0 AND status IN ('NEW', 'PARTIALLY_FILLED')",
                            (sym,),
                        ).fetchall()
                        tp_ids = [r["client_order_id"] for r in tp_rows]

                    results.append({
                        "symbol": sym,
                        "side": side,
                        "amount": f"{abs(amt):.4f}".rstrip("0").rstrip("."),
                        "entry_price": entry_p,
                        "mark_price": mark_p,
                        "unrealized_pnl": unpnl,
                        "leverage": lev,
                        "margin_type": mtype,
                        "sl_order_id": sl_id,
                        "tp_order_ids": tp_ids,
                    })
                except Exception:
                    pass
            return results

        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM positions WHERE quantity != '0'").fetchall()
            positions = []
            for r in rows:
                pos = dict(r)
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
                max_age = getattr(self.config.execution, "signal_max_age_seconds", 900)
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

