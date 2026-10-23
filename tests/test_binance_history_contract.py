import pytest

from core.enums import ExecutionMode
from exchange.binance_client import BinanceFuturesClient
from config.config import AppConfig


@pytest.mark.asyncio
async def test_user_trades_contract_requires_symbol_and_bounds_limit(monkeypatch):
    config = AppConfig(mode=ExecutionMode.READ_ONLY)
    client = BinanceFuturesClient(config)
    calls = []

    async def fake_request(method, endpoint, params=None, signed=False, **kwargs):
        calls.append((method, endpoint, params, signed))
        return []

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(ValueError):
        await client.get_user_trades("")
    await client.get_user_trades("BTCUSDT", limit=5000, start_time_ms=1, end_time_ms=2)
    assert calls[0][2] == {"symbol": "BTCUSDT", "limit": 1000, "startTime": 1, "endTime": 2}


@pytest.mark.asyncio
async def test_user_trade_window_deduplicates_pages(monkeypatch):
    config = AppConfig(mode=ExecutionMode.READ_ONLY)
    client = BinanceFuturesClient(config)
    pages = iter([
        [{"id": 1, "time": 2}, {"id": 2, "time": 3}],
        [{"id": 2, "time": 3}, {"id": 3, "time": 4}],
        [],
    ])

    async def fake_trades(*args, **kwargs):
        return next(pages)

    monkeypatch.setattr(client, "get_user_trades", fake_trades)
    result = await client.get_user_trades_window("BTCUSDT", 1, 10, limit=2)
    assert [row["id"] for row in result] == [1, 2, 3]
