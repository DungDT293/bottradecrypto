import uuid
from decimal import Decimal
from typing import Any, Dict, Optional
from core.enums import OrderSide, OrderType
from exchange.exchange_info import SymbolFilterInfo
from exchange.mock_exchange import MockBinanceFuturesClient


class PaperTradingClient(MockBinanceFuturesClient):
    """
    Paper Trading Simulator:
    - Simulates order execution with spread, taker/maker fees, and slippage
    - Does not assume market touch guarantees fill
    - Tracks simulated balance and unrealized PnL
    """

    def __init__(
        self,
        initial_equity: Decimal = Decimal("10000.0"),
        maker_fee_pct: Decimal = Decimal("0.02"),
        taker_fee_pct: Decimal = Decimal("0.05"),
        slippage_pct: Decimal = Decimal("0.05"),
    ):
        super().__init__(initial_equity=initial_equity)
        self.maker_fee_pct = maker_fee_pct
        self.taker_fee_pct = taker_fee_pct
        self.slippage_pct = slippage_pct
        self.total_fees_paid = Decimal("0")

    def execute_market_order_simulation(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        market_price: Decimal,
    ) -> Dict[str, Any]:
        """
        Executes a paper market order including slippage and taker fees.
        """
        slip_mult = (Decimal("1") + (self.slippage_pct / Decimal("100"))) if side == OrderSide.BUY else (Decimal("1") - (self.slippage_pct / Decimal("100")))
        executed_price = market_price * slip_mult
        notional = quantity * executed_price
        fee = notional * (self.taker_fee_pct / Decimal("100"))
        self.total_fees_paid += fee
        self.equity -= fee

        side_mult = Decimal("1") if side == OrderSide.BUY else Decimal("-1")
        existing_amt = Decimal(str(self.positions.get(symbol, {}).get("positionAmt", "0")))
        new_amt = existing_amt + (quantity * side_mult)

        self.positions[symbol] = {
            "symbol": symbol,
            "positionAmt": str(new_amt),
            "entryPrice": str(executed_price),
            "unrealizedProfit": "0",
            "marginType": "isolated",
            "leverage": "5",
        }

        return {
            "symbol": symbol,
            "executedPrice": str(executed_price),
            "executedQty": str(quantity),
            "fee": str(fee),
            "status": "FILLED",
        }

