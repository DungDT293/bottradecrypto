from decimal import Decimal
from typing import Any, Dict, Optional


class SymbolFilterInfo:
    def __init__(
        self,
        symbol: str,
        tick_size: Decimal,
        step_size: Decimal,
        min_qty: Decimal,
        max_qty: Decimal,
        min_notional: Decimal,
        is_trading: bool,
    ):
        self.symbol = symbol
        self.tick_size = tick_size
        self.step_size = step_size
        self.min_qty = min_qty
        self.max_qty = max_qty
        self.min_notional = min_notional
        self.is_trading = is_trading


def parse_symbol_info(symbol_data: Dict[str, Any]) -> SymbolFilterInfo:
    symbol = symbol_data.get("symbol", "")
    status = symbol_data.get("status", "") == "TRADING"

    tick_size = Decimal("0.01")
    step_size = Decimal("0.001")
    min_qty = Decimal("0.001")
    max_qty = Decimal("1000000")
    min_notional = Decimal("5.0")

    for f in symbol_data.get("filters", []):
        f_type = f.get("filterType")
        if f_type == "PRICE_FILTER":
            tick_size = Decimal(f.get("tickSize", "0.01"))
        elif f_type == "LOT_SIZE":
            step_size = Decimal(f.get("stepSize", "0.001"))
            min_qty = Decimal(f.get("minQty", "0.001"))
            max_qty = Decimal(f.get("maxQty", "1000000"))
        elif f_type in ["MIN_NOTIONAL", "NOTIONAL"]:
            val = f.get("notional") or f.get("minNotional") or "20.0"
            min_notional = Decimal(str(val))

    return SymbolFilterInfo(
        symbol=symbol,
        tick_size=tick_size,
        step_size=step_size,
        min_qty=min_qty,
        max_qty=max_qty,
        min_notional=min_notional,
        is_trading=status,
    )

