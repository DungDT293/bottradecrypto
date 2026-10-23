import json
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
        if db_path == ":memory:":
            raise ValueError("DatabaseManager requires a file-backed SQLite path")
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
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
                updated_at TEXT NOT NULL,
                win_count INTEGER DEFAULT 0,
                loss_count INTEGER DEFAULT 0,
                total_trades INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                payload_json TEXT
            );

            CREATE TABLE IF NOT EXISTS admin_evidence (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                event_timestamp TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                media_kind TEXT NOT NULL,
                exchange_claim TEXT,
                confidence TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                outcome TEXT NOT NULL,
                is_trade_fill INTEGER NOT NULL DEFAULT 0,
                has_referral_promotion INTEGER NOT NULL DEFAULT 0,
                caption_has_result_markers INTEGER NOT NULL DEFAULT 0,
                sender_id INTEGER,
                parent_signal_id TEXT,
                detail TEXT NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            );

            CREATE TABLE IF NOT EXISTS ledger_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                account_scope TEXT NOT NULL,
                execution_mode TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                asset TEXT NOT NULL DEFAULT 'USDT',
                symbol TEXT,
                signal_id TEXT,
                client_order_id TEXT,
                exchange_order_id TEXT,
                exchange_trade_id TEXT,
                income_type TEXT,
                quantity TEXT,
                price TEXT,
                amount TEXT NOT NULL,
                raw_payload_json TEXT NOT NULL,
                FOREIGN KEY (signal_id) REFERENCES signals(signal_id)
            );

            CREATE INDEX IF NOT EXISTS ix_ledger_scope_time
                ON ledger_events(account_scope, execution_mode, occurred_at);
            CREATE INDEX IF NOT EXISTS ix_ledger_signal_time
                ON ledger_events(signal_id, occurred_at);
            """)

            # Existing installs may contain multiple parser rows for one Telegram message.
            # Keep newest lifecycle row, repoint orders, then enforce canonical identity.
            duplicate_groups = conn.execute(
                """
                SELECT chat_id, message_id
                FROM signals
                GROUP BY chat_id, message_id
                HAVING COUNT(*) > 1
                """
            ).fetchall()
            for group in duplicate_groups:
                rows = conn.execute(
                    """
                    SELECT rowid, signal_id
                    FROM signals
                    WHERE chat_id = ? AND message_id = ?
                    ORDER BY CASE state
                        WHEN 'OPEN_PROTECTED' THEN 6
                        WHEN 'PARTIALLY_FILLED' THEN 5
                        WHEN 'ENTRY_PENDING' THEN 4
                        WHEN 'EXITING' THEN 3
                        WHEN 'ERROR' THEN 2
                        WHEN 'CLOSED' THEN 1
                        ELSE 0
                    END DESC, updated_at DESC, rowid DESC
                    """,
                    (group["chat_id"], group["message_id"]),
                ).fetchall()
                keep_signal_id = rows[0]["signal_id"]
                for duplicate in rows[1:]:
                    conn.execute(
                        "UPDATE orders SET signal_id = ? WHERE signal_id = ?",
                        (keep_signal_id, duplicate["signal_id"]),
                    )
                    conn.execute("DELETE FROM signals WHERE rowid = ?", (duplicate["rowid"],))
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_signals_chat_message ON signals(chat_id, message_id)"
            )
            cols = [c[1] for c in conn.execute("PRAGMA table_info(daily_pnl)").fetchall()]
            if "win_count" not in cols:
                conn.execute("ALTER TABLE daily_pnl ADD COLUMN win_count INTEGER DEFAULT 0")
            if "loss_count" not in cols:
                conn.execute("ALTER TABLE daily_pnl ADD COLUMN loss_count INTEGER DEFAULT 0")
            if "total_trades" not in cols:
                conn.execute("ALTER TABLE daily_pnl ADD COLUMN total_trades INTEGER DEFAULT 0")
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, datetime.utcnow().isoformat()),
            )

    def integrity_report(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            migration = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
            return {"integrity": integrity, "foreign_keys": foreign_keys, "user_version": version, "migration_version": migration}

    def backup_to(self, destination: str) -> None:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        source = self.get_connection()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()


class LedgerRepository:
    def __init__(self, db: DatabaseManager):
        self.db = db

    def append_event(self, event: Dict[str, Any]) -> bool:
        """Append immutable exchange/cash event; duplicate keys are idempotent."""
        required = ("event_key", "account_scope", "execution_mode", "event_type", "source", "occurred_at", "amount", "raw_payload_json")
        missing = [key for key in required if not event.get(key)]
        if missing:
            raise ValueError(f"Ledger event missing fields: {', '.join(missing)}")
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ledger_events
                (event_key, account_scope, execution_mode, event_type, source, occurred_at, ingested_at,
                 asset, symbol, signal_id, client_order_id, exchange_order_id, exchange_trade_id,
                 income_type, quantity, price, amount, raw_payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_key) DO NOTHING
                """,
                (
                    event["event_key"], event["account_scope"], event["execution_mode"], event["event_type"],
                    event["source"], event["occurred_at"], event.get("ingested_at", datetime.utcnow().isoformat()),
                    event.get("asset", "USDT"), event.get("symbol"), event.get("signal_id"),
                    event.get("client_order_id"), event.get("exchange_order_id"), event.get("exchange_trade_id"),
                    event.get("income_type"), event.get("quantity"), event.get("price"),
                    str(Decimal(str(event["amount"]))), event["raw_payload_json"],
                ),
            )
            return cursor.rowcount == 1

    def get_events(self, account_scope: str, execution_mode: str, start: Optional[str] = None, end: Optional[str] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM ledger_events WHERE account_scope = ? AND execution_mode = ?"
        params: List[Any] = [account_scope, execution_mode]
        if start is not None:
            query += " AND occurred_at >= ?"
            params.append(start)
        if end is not None:
            query += " AND occurred_at < ?"
            params.append(end)
        query += " ORDER BY occurred_at ASC, event_id ASC"
        with self.db.get_connection() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]


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
                INSERT INTO messages
                (chat_id, message_id, sender_id, telegram_timestamp, received_at, edit_timestamp, raw_text, normalized_text, fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    sender_id = excluded.sender_id,
                    received_at = excluded.received_at,
                    edit_timestamp = COALESCE(excluded.edit_timestamp, messages.edit_timestamp),
                    raw_text = excluded.raw_text,
                    normalized_text = excluded.normalized_text,
                    fingerprint = excluded.fingerprint
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

    def save_admin_evidence(self, chat_id: int, message_id: int, event_timestamp: datetime, evidence: Any, sender_id: Optional[int] = None, parent_signal_id: Optional[str] = None) -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO admin_evidence
                (chat_id, message_id, event_timestamp, evidence_type, media_kind, exchange_claim,
                 confidence, verification_status, outcome, is_trade_fill, has_referral_promotion,
                 caption_has_result_markers, sender_id, parent_signal_id, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    event_timestamp = excluded.event_timestamp,
                    evidence_type = excluded.evidence_type,
                    media_kind = excluded.media_kind,
                    exchange_claim = excluded.exchange_claim,
                    confidence = excluded.confidence,
                    verification_status = excluded.verification_status,
                    outcome = excluded.outcome,
                    is_trade_fill = excluded.is_trade_fill,
                    has_referral_promotion = excluded.has_referral_promotion,
                    caption_has_result_markers = excluded.caption_has_result_markers,
                    sender_id = excluded.sender_id,
                    parent_signal_id = excluded.parent_signal_id,
                    detail = excluded.detail
                """,
                (
                    chat_id, message_id, event_timestamp.isoformat(), evidence.evidence_type,
                    evidence.media_kind, evidence.exchange_claim, evidence.confidence,
                    evidence.verification_status, evidence.outcome, int(evidence.is_trade_fill),
                    int(evidence.has_referral_promotion), int(evidence.caption_has_result_markers),
                    sender_id, parent_signal_id, evidence.detail,
                ),
            )

    def get_admin_evidence(self, chat_id: Optional[int] = None, message_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            if chat_id is not None and message_id is not None:
                rows = conn.execute("SELECT * FROM admin_evidence WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)).fetchall()
            elif chat_id is not None:
                rows = conn.execute("SELECT * FROM admin_evidence WHERE chat_id = ? ORDER BY event_timestamp", (chat_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM admin_evidence ORDER BY event_timestamp").fetchall()
            return [dict(row) for row in rows]

    def save_signal(self, signal: ParsedSignal) -> None:
        import json
        entries_str = json.dumps([str(e) for e in signal.entries])
        tps_str = json.dumps([str(tp) for tp in signal.take_profits])

        now_str = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            existing = conn.execute(
                "SELECT signal_id, state, created_at FROM signals WHERE chat_id = ? AND message_id = ?",
                (signal.metadata.chat_id, signal.metadata.message_id),
            ).fetchone()
            if existing and existing["signal_id"] != signal.signal_id:
                signal.signal_id = existing["signal_id"]

            conn.execute(
                """
                INSERT INTO signals
                (signal_id, chat_id, message_id, symbol, side, state, entry_mode, entries_json, stop_loss, take_profits_json,
                 leverage, margin_mode, risk_pct, blocking_reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    message_id = excluded.message_id,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    state = CASE
                        WHEN CASE signals.state
                            WHEN 'RECEIVED' THEN 0
                            WHEN 'PARSED' THEN 1
                            WHEN 'NEEDS_POLICY' THEN 2
                            WHEN 'NEEDS_REVIEW' THEN 2
                            WHEN 'VALIDATED' THEN 3
                            WHEN 'ENTRY_PENDING' THEN 4
                            WHEN 'PARTIALLY_FILLED' THEN 5
                            WHEN 'OPEN_PROTECTED' THEN 6
                            WHEN 'EXITING' THEN 7
                            WHEN 'REJECTED' THEN 8
                            WHEN 'CLOSED' THEN 8
                            WHEN 'ERROR' THEN 8
                            ELSE -1
                        END >= CASE excluded.state
                            WHEN 'RECEIVED' THEN 0
                            WHEN 'PARSED' THEN 1
                            WHEN 'NEEDS_POLICY' THEN 2
                            WHEN 'NEEDS_REVIEW' THEN 2
                            WHEN 'VALIDATED' THEN 3
                            WHEN 'ENTRY_PENDING' THEN 4
                            WHEN 'PARTIALLY_FILLED' THEN 5
                            WHEN 'OPEN_PROTECTED' THEN 6
                            WHEN 'EXITING' THEN 7
                            WHEN 'REJECTED' THEN 8
                            WHEN 'CLOSED' THEN 8
                            WHEN 'ERROR' THEN 8
                            ELSE -1
                        END THEN signals.state
                        ELSE excluded.state
                    END,
                    entry_mode = excluded.entry_mode,
                    entries_json = excluded.entries_json,
                    stop_loss = excluded.stop_loss,
                    take_profits_json = excluded.take_profits_json,
                    leverage = excluded.leverage,
                    margin_mode = excluded.margin_mode,
                    risk_pct = excluded.risk_pct,
                    blocking_reason = COALESCE(excluded.blocking_reason, signals.blocking_reason),
                    updated_at = excluded.updated_at
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
                    existing["created_at"] if existing else now_str,
                    now_str,
                ),
            )

    def update_signal_state(
        self,
        signal_id: str,
        new_state: SignalState,
        reason: Optional[str] = None,
        expected_current_state: Optional[SignalState] = None,
    ) -> None:
        now_str = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT state FROM signals WHERE signal_id = ?",
                (signal_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Signal not found: {signal_id}")
            current_state = SignalState(row["state"])
            if expected_current_state is not None and current_state != expected_current_state:
                from storage.state_machine import InvalidStateTransitionError
                raise InvalidStateTransitionError(
                    f"Trang thai hien tai cua tin hieu '{signal_id}' da thay doi tu "
                    f"'{expected_current_state.value}' sang '{current_state.value}'."
                )
            if current_state != new_state:
                from storage.state_machine import InvalidStateTransitionError, SignalStateMachine
                allowed = SignalStateMachine.ALLOWED_TRANSITIONS.get(current_state, set())
                if new_state not in allowed:
                    raise InvalidStateTransitionError(
                        f"Khong the chuyen trang thai tin hieu tu '{current_state.value}' sang '{new_state.value}'. "
                        f"Cac trang thai hop le: {[s.value for s in allowed]}"
                    )
            # Always compare-and-swap the state read above; stale writers must fail.
            where = "signal_id = ? AND state = ?"
            params = (new_state.value, reason, now_str, signal_id, current_state.value)
            cursor = conn.execute(
                f"UPDATE signals SET state = ?, blocking_reason = ?, updated_at = ? WHERE {where}",
                params,
            )
            if cursor.rowcount != 1:
                from storage.state_machine import InvalidStateTransitionError
                raise InvalidStateTransitionError(f"Trang thai tin hieu '{signal_id}' da thay doi trong luc cap nhat.")

    def _format_signal_row(self, row: Any) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        d = dict(row)
        if d.get("entries_json"):
            try:
                d["entries"] = json.loads(d["entries_json"])
            except Exception:
                d["entries"] = []
        elif "entries" not in d or d["entries"] is None:
            d["entries"] = []

        if d.get("take_profits_json"):
            try:
                d["take_profits"] = json.loads(d["take_profits_json"])
            except Exception:
                d["take_profits"] = []
        elif "take_profits" not in d or d["take_profits"] is None:
            d["take_profits"] = []
        return d

    def get_signal(self, signal_id: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM signals WHERE signal_id = ?", (signal_id,)).fetchone()
            return self._format_signal_row(row)

    def get_signal_by_message(self, chat_id: int, message_id: int) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            ).fetchone()
            return self._format_signal_row(row)

    def get_active_signal_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM signals
                WHERE symbol = ? AND state IN ('ENTRY_PENDING', 'PARTIALLY_FILLED', 'OPEN_PROTECTED', 'EXITING')
                """,
                (symbol,),
            ).fetchone()
            return self._format_signal_row(row)

    def get_latest_pending_signal_id(self, chat_id: int, symbol: Optional[str] = None) -> Optional[str]:
        with self.db.get_connection() as conn:
            if symbol:
                row = conn.execute(
                    """
                    SELECT signal_id FROM signals
                    WHERE chat_id = ? AND symbol = ? AND state = 'ENTRY_PENDING'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (chat_id, symbol),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT signal_id FROM signals
                    WHERE chat_id = ? AND state = 'ENTRY_PENDING'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (chat_id,),
                ).fetchone()
            return row["signal_id"] if row else None

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
                INSERT INTO orders
                (client_order_id, signal_id, symbol, side, order_type, price, quantity, trigger_price,
                 is_reduce_only, is_algo, exchange_order_id, status, filled_quantity, avg_fill_price, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_order_id) DO UPDATE SET
                    signal_id = excluded.signal_id,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    order_type = excluded.order_type,
                    price = excluded.price,
                    quantity = excluded.quantity,
                    trigger_price = excluded.trigger_price,
                    is_reduce_only = excluded.is_reduce_only,
                    is_algo = excluded.is_algo,
                    exchange_order_id = COALESCE(excluded.exchange_order_id, orders.exchange_order_id),
                    status = CASE
                        WHEN orders.status = 'FILLED' THEN orders.status
                        WHEN orders.status IN ('CANCELED', 'REJECTED', 'EXPIRED')
                            AND excluded.status IN ('NEW', 'PARTIALLY_FILLED') THEN orders.status
                        ELSE excluded.status
                    END,
                    filled_quantity = CASE
                        WHEN CAST(excluded.filled_quantity AS NUMERIC) >= CAST(orders.filled_quantity AS NUMERIC)
                        THEN excluded.filled_quantity ELSE orders.filled_quantity
                    END,
                    avg_fill_price = COALESCE(excluded.avg_fill_price, orders.avg_fill_price),
                    updated_at = excluded.updated_at
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
                SET status = CASE
                    WHEN status = 'FILLED' THEN 'FILLED'
                    WHEN status IN ('CANCELED', 'REJECTED', 'EXPIRED') AND ? NOT IN ('CANCELED', 'REJECTED', 'EXPIRED') THEN status
                    ELSE ?
                END,
                    filled_quantity = CASE
                        WHEN CAST(filled_quantity AS REAL) > CAST(? AS REAL) THEN filled_quantity
                        ELSE ?
                    END,
                    avg_fill_price = COALESCE(?, avg_fill_price),
                    updated_at = ?
                WHERE client_order_id = ?
                """,
                (status, status, str(filled_qty), str(filled_qty), str(avg_price) if avg_price else None, now_str, client_order_id),
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

    def cancel_open_orders_for_signal(self, signal_id: str) -> None:
        now_str = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = 'CANCELED', updated_at = ?
                WHERE signal_id = ? AND status IN ('NEW', 'PARTIALLY_FILLED')
                """,
                (now_str, signal_id),
            )

    def cancel_open_orders_for_symbol(self, symbol: str) -> None:
        """Legacy helper; callers must prefer signal-scoped cancellation."""
        now_str = datetime.utcnow().isoformat()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = 'CANCELED', updated_at = ?
                WHERE symbol = ? AND status IN ('NEW', 'PARTIALLY_FILLED')
                  AND is_reduce_only = 0
                """
                ,
                (now_str, symbol),
            )

