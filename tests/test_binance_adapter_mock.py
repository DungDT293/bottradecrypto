from decimal import Decimal
import pytest

from core.enums import OrderSide, OrderType
from core.exceptions import ExchangeAdapterError
from exchange.mock_exchange import MockBinanceFuturesClient


@pytest.mark.asyncio
async def test_error_4120_when_stop_market_sent_to_standard_endpoint():
    client = MockBinanceFuturesClient()
    # Sending STOP_MARKET to standard order endpoint must raise Error -4120
    with pytest.raises(ExchangeAdapterError) as exc:
        await client.create_standard_order(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            order_type=OrderType.STOP_MARKET,
            quantity=Decimal("0.1"),
        )
    assert "-4120" in str(exc.value)
    assert "STOP_ORDER_SWITCH_ALGO" in str(exc.value)


@pytest.mark.asyncio
async def test_algo_order_endpoint_accepts_stop_market():
    client = MockBinanceFuturesClient()
    resp = await client.create_algo_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        trigger_price=Decimal("58000"),
        quantity=Decimal("0.1"),
    )
    assert resp["type"] == "STOP_MARKET"
    assert resp["triggerPrice"] == "58000"
    assert resp["status"] == "NEW"


@pytest.mark.asyncio
async def test_cannot_change_margin_mode_when_position_open():
    client = MockBinanceFuturesClient()
    # Create an active position
    client.positions["ETHUSDT"] = {
        "symbol": "ETHUSDT",
        "positionAmt": "1.5",
        "entryPrice": "2400",
        "marginType": "crossed",
    }
    with pytest.raises(ExchangeAdapterError):
        await client.set_margin_type_isolated("ETHUSDT")

