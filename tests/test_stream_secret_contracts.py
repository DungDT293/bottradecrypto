import asyncio

import pytest

from config.config import AppConfig
from core.enums import ExecutionMode
from exchange.binance_client import BinanceFuturesClient
from exchange.secret_store import BinanceCredentialProvider, EnvironmentSecretStore, MemorySecretStore, SecretStoreUnavailable
from exchange.user_data_stream import UserDataStreamManager


@pytest.mark.asyncio
async def test_listen_key_contract_is_unsigned_but_keyed(monkeypatch):
    config = AppConfig(mode=ExecutionMode.TESTNET)
    config.binance.testnet_api_key = "key"
    client = BinanceFuturesClient(config)
    calls = []

    async def fake_request(method, endpoint, params=None, signed=False, **kwargs):
        calls.append((method, endpoint, params, signed))
        return {"listenKey": "lk-test"}

    monkeypatch.setattr(client, "_request", fake_request)
    assert await client.create_user_data_listen_key() == "lk-test"
    await client.keepalive_user_data_listen_key("lk-test")
    await client.delete_user_data_listen_key("lk-test")
    assert calls == [
        ("POST", "/fapi/v1/listenKey", {}, False),
        ("PUT", "/fapi/v1/listenKey", {"listenKey": "lk-test"}, False),
        ("DELETE", "/fapi/v1/listenKey", {"listenKey": "lk-test"}, False),
    ]


@pytest.mark.asyncio
async def test_user_stream_deduplicates_events_and_cleans_key():
    class Rest:
        def __init__(self):
            self.deleted = []
        async def create_user_data_listen_key(self): return "lk"
        async def delete_user_data_listen_key(self, key): self.deleted.append(key)

    class Sink:
        def __init__(self): self.events = []
        async def on_order_trade_update(self, payload): self.events.append(payload)
        async def on_account_update(self, payload): self.events.append(payload)
        async def on_resync(self, snapshot): pass

    rest, sink = Rest(), Sink()
    manager = UserDataStreamManager(rest, sink, None, AppConfig(mode=ExecutionMode.TESTNET))
    await manager.start()
    payload = {"e": "ORDER_TRADE_UPDATE", "T": 1, "x": "TRADE"}
    assert await manager.handle_event(payload) is True
    assert await manager.handle_event(payload) is False
    assert len(sink.events) == 1
    await manager.stop()
    assert rest.deleted == ["lk"]


@pytest.mark.asyncio
async def test_user_stream_reconnects_after_socket_failure(monkeypatch):
    class Rest:
        def __init__(self): self.created = 0; self.deleted = 0
        async def create_user_data_listen_key(self): self.created += 1; return f"lk-{self.created}"
        async def delete_user_data_listen_key(self, key): self.deleted += 1
        async def _request(self, *args, **kwargs): return {}
        async def get_open_positions(self): return []
        async def get_open_orders(self): return []
        async def get_open_algo_orders(self): return []

    class Sink:
        async def on_order_trade_update(self, payload): pass
        async def on_account_update(self, payload): pass
        async def on_resync(self, snapshot): pass

    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def __aiter__(self): return self
        async def __anext__(self): raise RuntimeError("disconnect")
        async def close(self): pass

    rest = Rest()
    manager = UserDataStreamManager(rest, Sink(), lambda *args, **kwargs: Socket(), AppConfig(mode=ExecutionMode.TESTNET))
    task = asyncio.create_task(manager.run_forever())
    await asyncio.sleep(0.01)
    await manager.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert rest.created >= 1


def test_secret_store_never_writes_environment():
    store = EnvironmentSecretStore()
    assert store.available() is True
    with pytest.raises(SecretStoreUnavailable):
        store.set("binance/live/api-key", "secret")


def test_memory_credentials_are_scoped_by_mode():
    provider = BinanceCredentialProvider(MemorySecretStore())
    provider.set("TESTNET", "test-key", "test-secret")
    provider.set("LIVE", "live-key", "live-secret")
    assert provider.get("TESTNET") == ("test-key", "test-secret")
    assert provider.get("LIVE") == ("live-key", "live-secret")
