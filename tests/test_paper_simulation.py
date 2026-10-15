from decimal import Decimal
import pytest

from core.enums import OrderSide, OrderType
from exchange.paper_exchange import PaperTradingClient


def test_paper_trading_market_order_with_slippage_and_fee():
    paper = PaperTradingClient(
        initial_equity=Decimal("10000.0"),
        taker_fee_pct=Decimal("0.05"),
        slippage_pct=Decimal("0.05"),
    )

    # Buy 0.1 BTC at market price 60,000
    # Expected slippage (0.05% higher): 60,000 * 1.0005 = 60,030
    # Notional: 0.1 * 60,030 = 6,003 USDT
    # Taker fee (0.05%): 6,003 * 0.0005 = 3.0015 USDT
    res = paper.execute_market_order_simulation(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("0.1"),
        market_price=Decimal("60000"),
    )

    assert res["status"] == "FILLED"
    assert Decimal(res["executedPrice"]) == Decimal("60030.00")
    assert Decimal(res["executedQty"]) == Decimal("0.1")
    assert Decimal(res["fee"]) == Decimal("3.0015")
    # Equity decreased by fee
    assert paper.equity == Decimal("10000.0") - Decimal("3.0015")

    # Verify position is recorded
    pos = paper.positions["BTCUSDT"]
    assert pos["positionAmt"] == "0.1"
    assert Decimal(pos["entryPrice"]) == Decimal("60030.00")
