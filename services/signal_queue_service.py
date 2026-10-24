"""
services/signal_queue_service.py
Trụ Cột 6: Smart Queue Priority (Hàng Đợi Tín Hiệu Thông Minh).
Khi hệ thống đã mở đủ số vị thế tối đa (kịch trần rủi ro danh mục),
các tín hiệu chất lượng cao từ các kênh Tier 1 không bị bỏ lỡ mà được đưa vào
hàng đợi ưu tiên (TTL 15-20 phút) và tự động kích hoạt ngay khi có lệnh cũ đạt Breakeven/TP1.
"""

import time
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from core.models import ValidatedSignal

logger = logging.getLogger("signal_queue_service")


@dataclass
class QueuedItem:
    signal: ValidatedSignal
    chat_id: int
    channel_name: str
    enqueued_at: float = field(default_factory=time.time)
    ttl_seconds: int = 1200  # 20 minutes default TTL
    priority: int = 1        # 1 = Highest (Tier 1 Elite), 2 = Tier 2

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.enqueued_at) > self.ttl_seconds

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self.ttl_seconds - (time.time() - self.enqueued_at)))


class SignalQueueService:
    """
    Priority Queue manager for signals waiting for risk/slot clearance.
    """

    def __init__(self, default_ttl_seconds: int = 1200, max_queue_size: int = 20):
        self.default_ttl_seconds = default_ttl_seconds
        self.max_queue_size = max_queue_size
        self._queue: List[QueuedItem] = []

    def enqueue(
        self,
        signal: ValidatedSignal,
        chat_id: int,
        channel_name: str,
        priority: int = 1,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Adds a signal to the priority queue.
        Returns True if queued, False if queue is full or duplicate symbol.
        """
        self.purge_expired()

        # Reject if symbol already waiting in queue
        if any(item.signal.symbol == signal.symbol for item in self._queue):
            logger.info(f"[SMART QUEUE] Symbol {signal.symbol} đã có trong hàng đợi. Bỏ qua.")
            return False

        if len(self._queue) >= self.max_queue_size:
            logger.warning(f"[SMART QUEUE] Hàng đợi đã đầy ({len(self._queue)}/{self.max_queue_size}).")
            return False

        item = QueuedItem(
            signal=signal,
            chat_id=chat_id,
            channel_name=channel_name,
            enqueued_at=time.time(),
            ttl_seconds=ttl_seconds or self.default_ttl_seconds,
            priority=priority,
        )
        self._queue.append(item)
        # Sort by priority asc (1 before 2), then by timestamp asc (earliest first)
        self._queue.sort(key=lambda x: (x.priority, x.enqueued_at))
        logger.info(
            f"[SMART QUEUE] Đã đưa tín hiệu {signal.symbol} từ '{channel_name}' vào hàng đợi "
            f"(Priority {priority}, TTL {item.remaining_seconds}s). Tổng chờ: {len(self._queue)}"
        )
        return True

    def dequeue_next(self) -> Optional[QueuedItem]:
        """
        Pops the highest priority, earliest non-expired signal from the queue.
        """
        self.purge_expired()
        if not self._queue:
            return None
        return self._queue.pop(0)

    def purge_expired(self) -> int:
        """
        Removes all expired items from queue. Returns count of purged items.
        """
        now = time.time()
        initial_count = len(self._queue)
        self._queue = [item for item in self._queue if not item.is_expired]
        purged = initial_count - len(self._queue)
        if purged > 0:
            logger.info(f"[SMART QUEUE] Đã thanh lý {purged} tín hiệu hết thời hạn sống (TTL).")
        return purged

    def remove_by_symbol(self, symbol: str) -> bool:
        sym = symbol.upper()
        initial = len(self._queue)
        self._queue = [i for i in self._queue if i.signal.symbol != sym]
        return len(self._queue) < initial

    def clear(self) -> None:
        self._queue.clear()

    def get_queue_summary(self) -> List[Dict[str, Any]]:
        self.purge_expired()
        return [
            {
                "signal_id": item.signal.signal_id,
                "symbol": item.signal.symbol,
                "side": item.signal.side.value if hasattr(item.signal.side, "value") else str(item.signal.side),
                "chat_id": item.chat_id,
                "channel_name": item.channel_name,
                "priority": item.priority,
                "enqueued_at": item.enqueued_at,
                "remaining_seconds": item.remaining_seconds,
            }
            for item in self._queue
        ]

    def size(self) -> int:
        self.purge_expired()
        return len(self._queue)


global_signal_queue_service = SignalQueueService()
