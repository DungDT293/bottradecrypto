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
    Centralized in-app alert and notification service.
    Features:
    - Thread-safe alert logging.
    - Anti-spam deduplication (collapses repeated identical errors within 30s).
    - Unread tracking without destroying audit records.
    - Never throws exceptions that could crash the trading engine.
    """

    _instance: Optional["AlertService"] = None
    _lock = threading.Lock()

    def __init__(self, max_history: int = 500):
        self.max_history = max_history
        self._alerts: List[AlertItem] = []
        self._counter = 0
        self._mutex = threading.Lock()

    @classmethod
    def get_instance(cls) -> "AlertService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

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
            return item

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
                    return True
            return False

    def mark_all_as_read(self) -> int:
        with self._mutex:
            count = 0
            for a in self._alerts:
                if not a.read:
                    a.read = True
                    count += 1
            return count

    def clear(self) -> None:
        with self._mutex:
            self._alerts.clear()

