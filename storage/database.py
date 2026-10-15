import os
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.enums import MarginMode, OrderSide, OrderType, PositionSide, SignalState
from core.models import Order, ParsedSignal, Position, SourceMetadata


class DatabaseManager:
    """
    Thread-safe SQLite manager with WAL mode and robust schema initialization.
    """

    def __init__(self, db_path: str = "./data/trading_state.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sender_id INTEGER,
                telegram_timestamp TEXT NOT NULL,
                received_at TEXT NOT NULL,
                edit_timestamp TEXT,
                raw_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                fingerprint TEXT,
                PRIMARY KEY (chat_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                symbol TEXT,
                side TEXT,
                state TEXT NOT NULL,
                entry_mode TEXT,
                entries_json TEXT,
                stop_loss TEXT,
                take_profits_json TEXT,
                leverage INTEGER,
                margin_mode TEXT,
                risk_pct TEXT,
                blocking_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (chat_id, message_id) REFERENCES messages(chat_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                price TEXT,
                quantity TEXT NOT NULL,
                trigger_price TEXT,
                is_reduce_only INTEGER NOT NULL,
                is_algo INTEGER NOT NULL,
                exchange_order_id TEXT,
                status TEXT NOT NULL,
                filled_quantity TEXT NOT NULL,
                avg_fill_price TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
            );

            CREATE TABLE IF NOT EXISTS positions (
                symbol TEXT PRIMARY KEY,
                side TEXT NOT NULL,
                quantity TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                leverage INTEGER NOT NULL,
                margin_mode TEXT NOT NULL,
                active_signal_id TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_versions (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                event_date TEXT NOT NULL,
                received_at TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                is_edit INTEGER NOT NULL,
                reply_to_msg_id INTEGER,
                PRIMARY KEY (chat_id, message_id, version)
            );

            CREATE TABLE IF NOT EXISTS signal_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                payload_json TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_pnl (
                date_str TEXT PRIMARY KEY, -- YYYY-MM-DD Asia/Ho_Chi_Minh
                starting_equity TEXT NOT NULL,
                realized_pnl TEXT NOT NULL,
                fees_paid TEXT NOT NULL,
                net_pnl TEXT NOT NULL,
                deposits_withdrawals TEXT NOT NULL,
                trading_halted INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT
            );
            """)


class SignalRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def save_message(
        self,
        chat_id: int,
        message_id: int,
        sender_id: Optional[int],
        telegram_timestamp: datetime,
        received_at: datetime,
        raw_text: str,
        normalized_text: str,
        fingerprint: Optional[str] = None,
        edit_timestamp: Optional[datetime] = None,
    ) -> bool:
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO messages
                (chat_id, message_id, sender_id, telegram_timestamp, received_at, edit_timestamp, raw_text, normalized_text, fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    message_id,
                    sender_id,
                    telegram_timestamp.isoformat(),
                    received_at.isoformat(),
                    edit_timestamp.isoformat() if edit_timestamp else None,
                    raw_text,
                    normalized_text,
                    fingerprint,
                ),
            )
            return cursor.rowcount > 0

    def message_exists(self, chat_id: int, message_id: int) -> bool:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT 1 FROM messages WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)).fetchone()
            return row is not None

    def save_signal(self, signal: ParsedSignal) -> None:
        import json
        entries_str = json.dumps([str(e) for e in signal.entries])
        tps_str = json.dumps([str(tp) for tp in signal.take_profits])

        now_str = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO signals
                (signal_id, chat_id, message_id, symbol, side, state, entry_mode, entries_json, stop_loss, take_profits_json,
                 leverage, margin_mode, risk_pct, blocking_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.signal_id,
                    signal.metadata.chat_id,
                    signal.metadata.message_id,
                    signal.symbol_candidate,
                    signal.side.value if signal.side else None,
                    signal.validation_status.value,
                    signal.entry_mode.value,
                    entries_str,
                    str(signal.stop_loss) if signal.stop_loss else None,
                    tps_str,
                    signal.leverage_requested,
                    signal.margin_mode_requested.value if signal.margin_mode_requested else None,
                    None,
                    signal.blocking_reason,
                    now_str,
                    now_str,
                ),
            )

    def update_signal_state(self, signal_id: str, new_state: SignalState, reason: Optional[str] = None) -> None:
        now_str = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE signals SET state = ?, blocking_reason = ?, updated_at = ? WHERE signal_id = ?",
                (new_state.value, reason, now_str, signal_id),
            )

    def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM signals WHERE signal_id = ?", (signal_id,)).fetchone()
            return dict(row) if row else None

    def get_active_signal_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM signals
                WHERE symbol = ? AND state IN ('ENTRY_PENDING', 'PARTIALLY_FILLED', 'OPEN_PROTECTED', 'EXITING')
                """,
                (symbol,),
            ).fetchone()
            return dict(row) if row else None

    def save_message_version(
        self,
        chat_id: int,
        message_id: int,
        event_date: datetime,
        received_at: datetime,
        raw_text: str,
        normalized_text: str,
        fingerprint: str,
        is_edit: bool,
        reply_to_msg_id: Optional[int] = None,
    ) -> Tuple[int, bool, str]:
        """
        Stores incremental message versions.
        Detects duplicate edits, out-of-order edits, and unanchored edits.
        Returns: (version_number, is_valid_save, status_code)
        status_code in ['OK', 'DUPLICATE', 'OUT_OF_ORDER', 'UNANCHORED']
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT version, event_date, fingerprint
                FROM message_versions
                WHERE chat_id = ? AND message_id = ?
                ORDER BY version DESC LIMIT 1
                """,
                (chat_id, message_id),
            ).fetchall()

            if not rows:
                # First version
                version = 1
                status = "UNANCHORED" if is_edit else "OK"
            else:
                last_v, last_date_str, last_fp = rows[0]["version"], rows[0]["event_date"], rows[0]["fingerprint"]
                if last_fp == fingerprint:
                    return last_v, False, "DUPLICATE"

                last_date = datetime.fromisoformat(last_date_str)
                if event_date < last_date:
                    return last_v, False, "OUT_OF_ORDER"

                version = last_v + 1
                status = "OK"

            cursor.execute(
                """
                INSERT INTO message_versions
                (chat_id, message_id, version, event_date, received_at, raw_text, normalized_text, fingerprint, is_edit, reply_to_msg_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    message_id,
                    version,
                    event_date.isoformat(),
                    received_at.isoformat(),
                    raw_text,
                    normalized_text,
                    fingerprint,
                    1 if is_edit else 0,
                    reply_to_msg_id,
                ),
            )
            return version, True, status

    def resolve_reply_parent(self, chat_id: int, reply_to_msg_id: int, max_depth: int = 5) -> Optional[str]:
        """
        Recursively resolves reply-to references to find the original parent signal_id.
        """
        current_msg_id = reply_to_msg_id
        depth = 0

        with self.db.get_connection() as conn:
            while current_msg_id and depth < max_depth:
                depth += 1
                # Check if this msg_id directly has a signal
                row = conn.execute(
                    "SELECT signal_id FROM signals WHERE chat_id = ? AND message_id = ?",
                    (chat_id, current_msg_id),
                ).fetchone()
                if row:
                    return row["signal_id"]

                # If not, check if this message was itself a reply
                ver_row = conn.execute(
                    "SELECT reply_to_msg_id FROM message_versions WHERE chat_id = ? AND message_id = ? ORDER BY version DESC LIMIT 1",
                    (chat_id, current_msg_id),
                ).fetchone()
                if ver_row and ver_row["reply_to_msg_id"]:
                    current_msg_id = ver_row["reply_to_msg_id"]
                else:
                    break

        return None

    def record_timeline_event(
        self,
        signal_id: str,
        event_type: str,
        description: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        import json
        now_str = datetime.utcnow().isoformat()
        payload_str = json.dumps(payload, default=str) if payload else None
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO signal_timeline (signal_id, timestamp, event_type, description, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (signal_id, now_str, event_type, description, payload_str),
            )

    def get_timeline(self, signal_id: str) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM signal_timeline WHERE signal_id = ? ORDER BY id ASC",
                (signal_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def export_history_data(self) -> Dict[str, Any]:
        with self.db.get_connection() as conn:
            messages = [dict(r) for r in conn.execute("SELECT * FROM messages").fetchall()]
            versions = [dict(r) for r in conn.execute("SELECT * FROM message_versions").fetchall()]
            signals = [dict(r) for r in conn.execute("SELECT * FROM signals").fetchall()]
            orders = [dict(r) for r in conn.execute("SELECT * FROM orders").fetchall()]
            timeline = [dict(r) for r in conn.execute("SELECT * FROM signal_timeline").fetchall()]

        return {
            "messages": messages,
            "message_versions": versions,
            "signals": signals,
            "orders": orders,
            "timeline": timeline,
            "exported_at": datetime.utcnow().isoformat(),
        }


class OrderRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def save_order(self, order: Order) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orders
                (client_order_id, signal_id, symbol, side, order_type, price, quantity, trigger_price,
                 is_reduce_only, is_algo, exchange_order_id, status, filled_quantity, avg_fill_price, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.client_order_id,
                    order.signal_id,
                    order.symbol,
                    order.side.value,
                    order.order_type.value,
                    str(order.price) if order.price else None,
                    str(order.quantity),
                    str(order.trigger_price) if order.trigger_price else None,
                    1 if order.is_reduce_only else 0,
                    1 if order.is_algo else 0,
                    order.exchange_order_id,
                    order.status,
                    str(order.filled_quantity),
                    str(order.avg_fill_price) if order.avg_fill_price else None,
                    order.created_at.isoformat(),
                    order.updated_at.isoformat(),
                ),
            )

    def update_order_fill(self, client_order_id: str, status: str, filled_qty: Decimal, avg_price: Optional[Decimal]) -> None:
        now_str = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = ?, filled_quantity = ?, avg_fill_price = ?, updated_at = ?
                WHERE client_order_id = ?
                """,
                (status, str(filled_qty), str(avg_price) if avg_price else None, now_str, client_order_id),
            )

    def get_orders_for_signal(self, signal_id: str) -> List[Order]:
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM orders WHERE signal_id = ?", (signal_id,)).fetchall()
            orders = []
            for r in rows:
                orders.append(
                    Order(
                        client_order_id=r["client_order_id"],
                        signal_id=r["signal_id"],
                        symbol=r["symbol"],
                        side=OrderSide(r["side"]),
                        order_type=OrderType(r["order_type"]),
                        price=Decimal(r["price"]) if r["price"] else None,
                        quantity=Decimal(r["quantity"]),
                        trigger_price=Decimal(r["trigger_price"]) if r["trigger_price"] else None,
                        is_reduce_only=bool(r["is_reduce_only"]),
                        is_algo=bool(r["is_algo"]),
                        exchange_order_id=r["exchange_order_id"],
                        status=r["status"],
                        filled_quantity=Decimal(r["filled_quantity"]),
                        avg_fill_price=Decimal(r["avg_fill_price"]) if r["avg_fill_price"] else None,
                    )
                )
            return orders

