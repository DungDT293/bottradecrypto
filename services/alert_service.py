import asyncio
import os
import sqlite3
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertItem(BaseModel):
    id: str
    timestamp: str
    level: AlertLevel
    title: str
    message: str
    source: str = "SYSTEM"
    read: bool = False
    repeat_count: int = 1


class AlertService:
    """
    Centralized in-app alert and notification service with SQLite persistence.
    Features:
    - Thread-safe alert logging.
    - Persistent SQLite storage surviving restarts.
    - Anti-spam deduplication (collapses repeated identical errors).
    - Unread tracking without destroying audit records.
    - Never throws exceptions that could crash the trading engine.
    """

    _instance: Optional["AlertService"] = None
    _lock = threading.Lock()

    def __init__(self, max_history: int = 500, db: Optional[Any] = None):
        self.max_history = max_history
        self._alerts: List[AlertItem] = []
        self._counter = 0
        self._mutex = threading.Lock()
        self._notifier: Optional[Any] = None
        self.db = db
        if self.db:
            self._init_db_table()
            self._load_from_db()

    def set_notifier(self, notifier: Any) -> None:
        self._notifier = notifier

    @classmethod
    def get_instance(cls, db: Optional[Any] = None) -> "AlertService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db=db)
            elif db and not cls._instance.db:
                cls._instance.set_db(db)
            return cls._instance

    def set_db(self, db: Any) -> None:
        with self._mutex:
            self.db = db
            self._init_db_table()
            self._load_from_db()

    def _init_db_table(self) -> None:
        if not self.db:
            return
        try:
            with self.db.get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS app_alerts (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        level TEXT NOT NULL,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        source TEXT NOT NULL,
                        is_read INTEGER NOT NULL DEFAULT 0,
                        repeat_count INTEGER NOT NULL DEFAULT 1
                    )
                """)
        except Exception:
            pass

    def _load_from_db(self) -> None:
        if not self.db:
            return
        try:
            with self.db.get_connection() as conn:
                rows = conn.execute("""
                    SELECT id, timestamp, level, title, message, source, is_read, repeat_count
                    FROM app_alerts
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (self.max_history,)).fetchall()

                self._alerts = [
                    AlertItem(
                        id=r["id"],
                        timestamp=r["timestamp"],
                        level=AlertLevel(r["level"]),
                        title=r["title"],
                        message=r["message"],
                        source=r["source"],
                        read=bool(r["is_read"]),
                        repeat_count=r["repeat_count"],
                    )
                    for r in rows
                ]
                # Update counter
                for r in rows:
                    try:
                        num = int(r["id"].replace("ALT-", ""))
                        if num > self._counter:
                            self._counter = num
                    except Exception:
                        pass
        except Exception:
            pass

    def add_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        source: str = "SYSTEM",
    ) -> AlertItem:
        with self._mutex:
            now_iso = datetime.now(timezone.utc).isoformat()

            # Deduplication check: check if last alert has identical level & title
            if self._alerts:
                last_alert = self._alerts[0]
                if (
                    last_alert.level == level
                    and last_alert.title == title
                    and last_alert.source == source
                ):
                    last_alert.repeat_count += 1
                    last_alert.timestamp = now_iso
                    last_alert.message = message
                    last_alert.read = False

                    if self.db:
                        try:
                            with self.db.get_connection() as conn:
                                conn.execute("""
                                    UPDATE app_alerts
                                    SET timestamp = ?, message = ?, is_read = 0, repeat_count = ?
                                    WHERE id = ?
                                """, (now_iso, message, last_alert.repeat_count, last_alert.id))
                        except Exception:
                            pass
                    return last_alert

            self._counter += 1
            alert_id = f"ALT-{self._counter:05d}"
            item = AlertItem(
                id=alert_id,
                timestamp=now_iso,
                level=level,
                title=title,
                message=message,
                source=source,
                read=False,
                repeat_count=1,
            )
            self._alerts.insert(0, item)
            if len(self._alerts) > self.max_history:
                self._alerts.pop()

            if self.db:
                try:
                    with self.db.get_connection() as conn:
                        conn.execute("""
                            INSERT OR REPLACE INTO app_alerts (id, timestamp, level, title, message, source, is_read, repeat_count)
                            VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                        """, (alert_id, now_iso, level.value, title, message, source))
                except Exception:
                    pass

            if self._notifier:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._dispatch_notify(title, message, level))
                except RuntimeError:
                    pass

            return item

    async def _dispatch_notify(self, title: str, message: str, level: AlertLevel) -> None:
        try:
            from telegram.dedicated_bot import get_dedicated_bot
            bot = get_dedicated_bot()
            if bot and bot.is_configured:
                t_upper = title.upper()
                m_upper = message.upper()
                import re
                match = re.search(r"([A-Z0-9]+USDT)", f"{title} {message}")
                sym = match.group(1) if match else "VỊ THẾ"

                # Chống nhầm lẫn: Bỏ qua thông báo vào lệnh mới (có chuỗi TP1 trong tham số khởi tạo)
                is_entry_alert = any(k in t_upper for k in ("VÀO LỆNH", "KHỚP LỆNH", "OPEN_PROTECTED", "MỞ VỊ THẾ", "NEW SIGNAL", "AI QUANT"))
                
                if is_entry_alert:
                    # Đây là sự kiện mở vị thế mới, không kích hoạt thông báo chốt lời TP1
                    pass
                elif any(k in t_upper for k in ("CHỐT LỜI TP1", "CHẠM TP1", "CẮN TP1", "TP1 HIT", "MỤC TIÊU 1 ĐÃ")) or ("TP1" in t_upper and "CHỐT" in t_upper):
                    await bot.notify_tp1_hit(symbol=sym, tp_price="TP1", entry_price="Entry")
                elif "TP3" in t_upper or "FULL TP" in t_upper or "GRAND SLAM" in t_upper:
                    await bot.notify_full_tp(symbol=sym)
                elif "CẮT LỖ" in t_upper or "STOP LOSS" in t_upper or "CHẠM SL" in t_upper or "STOPPED" in t_upper:
                    await bot.notify_sl_hit(symbol=sym, sl_price="SL", root_cause=message)
        except Exception:
            pass

        if not self._notifier:
            return
        emoji = "ℹ️" if level == AlertLevel.INFO else ("⚠️" if level == AlertLevel.WARNING else "🚨")
        text = f"<b>{emoji} [{title}]</b>\n{message}"
        try:
            if hasattr(self._notifier, "notify"):
                await self._notifier.notify(text)
        except Exception:
            pass

    def get_alerts(
        self,
        unread_only: bool = False,
        level: Optional[AlertLevel] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        with self._mutex:
            result = []
            for a in self._alerts:
                if unread_only and a.read:
                    continue
                if level and a.level != level:
                    continue
                result.append(a.model_dump())
                if len(result) >= limit:
                    break
            return result

    def get_unread_count(self) -> int:
        with self._mutex:
            return sum(1 for a in self._alerts if not a.read)

    def mark_as_read(self, alert_id: str) -> bool:
        with self._mutex:
            for a in self._alerts:
                if a.id == alert_id:
                    a.read = True
                    if self.db:
                        try:
                            with self.db.get_connection() as conn:
                                conn.execute("UPDATE app_alerts SET is_read = 1 WHERE id = ?", (alert_id,))
                        except Exception:
                            pass
                    return True
            return False

    def mark_all_as_read(self) -> int:
        with self._mutex:
            count = 0
            for a in self._alerts:
                if not a.read:
                    a.read = True
                    count += 1
            if self.db:
                try:
                    with self.db.get_connection() as conn:
                        conn.execute("UPDATE app_alerts SET is_read = 1")
                except Exception:
                    pass
            return count

    def clear(self) -> None:
        with self._mutex:
            self._alerts.clear()
            if self.db:
                try:
                    with self.db.get_connection() as conn:
                        conn.execute("DELETE FROM app_alerts")
                except Exception:
                    pass
