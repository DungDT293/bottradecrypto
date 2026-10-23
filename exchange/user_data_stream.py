from __future__ import annotations

import asyncio
import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol


@dataclass(frozen=True)
class UserStateSnapshot:
    account: dict[str, Any]
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    open_algo_orders: list[dict[str, Any]]
    fetched_at_ms: int


class UserDataEventSink(Protocol):
    async def on_order_trade_update(self, payload: dict[str, Any]) -> None: ...
    async def on_account_update(self, payload: dict[str, Any]) -> None: ...
    async def on_resync(self, snapshot: UserStateSnapshot) -> None: ...


class UserDataStreamManager:
    """ListenKey lifecycle with injectable websocket/REST dependencies.

    Production integration must provide a configured websocket factory and a sink
    that persists event dedupe before triggering reconciliation.
    """

    def __init__(self, rest_client: Any, event_sink: UserDataEventSink, websocket_factory: Callable[..., Any], config: Any):
        self.rest_client = rest_client
        self.event_sink = event_sink
        self.websocket_factory = websocket_factory
        self.config = config
        self.listen_key: Optional[str] = None
        self._stop = asyncio.Event()
        self._seen: set[str] = set()
        self._socket: Any = None

    @staticmethod
    def event_key(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _snapshot(self) -> UserStateSnapshot:
        account = await self.rest_client._request("GET", "/fapi/v2/account", signed=True)
        positions = await self.rest_client.get_open_positions()
        orders = await self.rest_client.get_open_orders()
        algos = await self.rest_client.get_open_algo_orders()
        return UserStateSnapshot(account, positions, orders, algos, 0)

    async def handle_event(self, payload: dict[str, Any]) -> bool:
        key = self.event_key(payload)
        if key in self._seen:
            return False
        self._seen.add(key)
        event_type = payload.get("e") or payload.get("eventType")
        if event_type == "ORDER_TRADE_UPDATE":
            await self.event_sink.on_order_trade_update(payload)
        elif event_type == "ACCOUNT_UPDATE":
            await self.event_sink.on_account_update(payload)
        elif event_type == "listenKeyExpired":
            self.listen_key = None
        return True

    async def start(self) -> None:
        self._stop.clear()
        self.listen_key = await self.rest_client.create_user_data_listen_key()

    async def run_forever(self) -> None:
        """Reconnect with bounded exponential backoff; REST resync precedes each session."""
        delay = 1.0
        while not self._stop.is_set():
            try:
                if not self.listen_key:
                    self.listen_key = await self.rest_client.create_user_data_listen_key()
                snapshot = await self._snapshot()
                await self.event_sink.on_resync(snapshot)
                url = f"{self.config.binance.live_user_stream_ws_url}?listenKey={self.listen_key}"
                async with self.websocket_factory(url, ping_interval=20, ping_timeout=10, close_timeout=5) as socket:
                    self._socket = socket
                    delay = 1.0
                    async for raw in socket:
                        if self._stop.is_set():
                            break
                        payload = json.loads(raw) if isinstance(raw, str) else raw
                        await self.handle_event(payload)
            except asyncio.CancelledError:
                break
            except Exception:
                if self._stop.is_set():
                    break
                await asyncio.sleep(delay + random.uniform(0, delay * 0.25))
                delay = min(delay * 2, 60.0)
            finally:
                self._socket = None
                if not self._stop.is_set():
                    try:
                        await self.rest_client.delete_user_data_listen_key(self.listen_key or "")
                    except Exception:
                        pass
                    self.listen_key = None

    async def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            close = getattr(self._socket, "close", None)
            if close:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
        if self.listen_key:
            try:
                await self.rest_client.delete_user_data_listen_key(self.listen_key)
            except Exception:
                pass
            self.listen_key = None
