import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


class EventMessage(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entity_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class EventBus:
    """
    In-memory realtime event bus for Desktop UI WebSocket streaming.
    Supports:
    - Multiple active WebSocket client connections.
    - Automatic connection pruning on disconnect.
    - Ring buffer for latest events to avoid unbounded memory growth.
    """

    def __init__(self, max_buffer: int = 200):
        self.max_buffer = max_buffer
        self._subscribers: Set[Any] = set()
        self._history: List[EventMessage] = []
        self._lock = asyncio.Lock()

    async def subscribe(self, websocket: Any) -> None:
        async with self._lock:
            self._subscribers.add(websocket)

    async def unsubscribe(self, websocket: Any) -> None:
        async with self._lock:
            self._subscribers.discard(websocket)

    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        entity_id: Optional[str] = None,
    ) -> EventMessage:
        msg = EventMessage(
            event_type=event_type,
            entity_id=entity_id,
            payload=payload,
        )

        async with self._lock:
            self._history.append(msg)
            if len(self._history) > self.max_buffer:
                self._history.pop(0)

            # Broadcast to all active websockets
            dead_sockets = set()
            json_text = msg.model_dump_json()
            for ws in self._subscribers:
                try:
                    await ws.send_text(json_text)
                except Exception:
                    dead_sockets.add(ws)

            for ws in dead_sockets:
                self._subscribers.discard(ws)

        return msg

    async def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with self._lock:
            return [m.model_dump() for m in self._history[-limit:]]


# Global EventBus instance for backend
event_bus = EventBus()

