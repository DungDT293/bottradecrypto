import pytest

from config.config import AppConfig
from core.enums import ExecutionMode
from services.gemini_autonomous_trader import GeminiAutonomousTrader


class FakeClient:
    async def get_exchange_symbols(self):
        return {"BTCUSDT", "ETHUSDT"}


@pytest.mark.asyncio
async def test_scan_symbol_validation_skips_unavailable_symbols():
    trader = GeminiAutonomousTrader(
        config=AppConfig(mode=ExecutionMode.READ_ONLY),
        binance_client=FakeClient(),
    )

    valid, skipped = await trader._filter_valid_symbols(["BTCUSDT", "PEPEUSDT", "btcusdt"])

    assert valid == ["BTCUSDT"]
    assert skipped == ["PEPEUSDT"]
    assert trader.last_scan_symbol_validation_error is None
