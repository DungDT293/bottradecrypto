from decimal import Decimal

import pytest

from config.config import AppConfig, exchange_writes_enabled, is_safe_testnet_url
from core.enums import ExecutionMode, OrderSide, OrderType
from core.exceptions import ExchangeAdapterError
from exchange.binance_client import BinanceFuturesClient
from services.binance_service import BinanceService


@pytest.mark.parametrize(
    ("mode", "live_enabled", "allowed"),
    [
        (ExecutionMode.READ_ONLY, False, False),
        (ExecutionMode.SHADOW, False, False),
        (ExecutionMode.PAPER, False, False),
        (ExecutionMode.TESTNET, False, True),
        (ExecutionMode.LIVE, False, False),
        (ExecutionMode.LIVE, True, True),
    ],
)
def test_exchange_write_policy(mode, live_enabled, allowed):
    config = AppConfig(mode=mode, live_trading_enabled=live_enabled)
    assert exchange_writes_enabled(config) is allowed


def test_testnet_url_must_not_alias_live_endpoint():
    config = AppConfig(mode=ExecutionMode.TESTNET)
    assert is_safe_testnet_url(config) is True

    config.binance.testnet_base_url = config.binance.live_base_url
    assert is_safe_testnet_url(config) is False


@pytest.mark.asyncio
async def test_binance_write_fails_before_network_in_read_only():
    config = AppConfig(mode=ExecutionMode.READ_ONLY, live_trading_enabled=False)
    client = BinanceFuturesClient(config)

    with pytest.raises(ExchangeAdapterError, match="blocked"):
        await client.create_standard_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.001"),
            price=Decimal("60000"),
        )

    assert client._session is None


def test_app_config_is_safe_by_default():
    config = AppConfig()
    assert config.mode is ExecutionMode.READ_ONLY
    assert config.live_trading_enabled is False
    assert config.telegram.api_id is None
    assert config.telegram.api_hash is None
    assert config.binance.testnet_api_key is None
    assert config.binance.testnet_api_secret is None
    assert config.binance.live_api_key is None
    assert config.binance.live_api_secret is None


@pytest.mark.asyncio
async def test_read_only_snapshot_cannot_report_trade_capability(monkeypatch):
    config = AppConfig(mode=ExecutionMode.READ_ONLY, live_trading_enabled=False)
    config.binance.testnet_api_key = "test-key"
    config.binance.testnet_api_secret = "test-secret"
    service = BinanceService(config)

    async def fake_request(self, method, endpoint, params=None, signed=False, _retry_count=0):
        if endpoint == "/fapi/v1/time":
            return {"serverTime": 1}
        if endpoint == "/fapi/v2/account":
            return {
                "totalWalletBalance": "100",
                "totalMarginBalance": "100",
                "availableBalance": "100",
                "totalUnrealizedProfit": "0",
            }
        return []

    monkeypatch.setattr(BinanceFuturesClient, "_request", fake_request)
    monkeypatch.setattr(BinanceFuturesClient, "check_position_mode_one_way", lambda self: _one_way())
    monkeypatch.setattr(BinanceFuturesClient, "get_open_positions", lambda self: _empty_list())
    monkeypatch.setattr(BinanceFuturesClient, "get_open_algo_orders", lambda self: _empty_list())

    snapshot = await service.sync_account(force=True)
    assert snapshot.is_connected is True
    assert snapshot.can_trade is False


async def _one_way():
    return True


async def _empty_list():
    return []
