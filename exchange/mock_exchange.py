import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional
from core.enums import MarginMode, OrderSide, OrderType, PositionSide
from core.exceptions import AccountStateBlockedError, ExchangeAdapterError
from exchange.exchange_info import SymbolFilterInfo


class MockBinanceFuturesClient:
    """
    High-fidelity in-memory mock client replicating Binance USD-M Futures:
    - Verifies endpoints (raises -4120 if conditional order is sent to standard endpoint)
    - Emulates order matching, partial fills, and balance updates
    - Emulates fail-safe conditions (e.g. SL placement rejection)
    """

    def __init__(self, initial_equity: Decimal = Decimal("10000.0"), is_dual_side: bool = False):
        self.equity = initial_equity
        self.is_dual_side = is_dual_side
        self.symbols_info: Dict[str, SymbolFilterInfo] = {
            "GRASSUSDT": SymbolFilterInfo("GRASSUSDT", Decimal("0.0001"), Decimal("0.1"), Decimal("1.0"), Decimal("100000"), Decimal("5.0"), True),
            "ZEREBROUSDT": SymbolFilterInfo("ZEREBROUSDT", Decimal("0.00001"), Decimal("1.0"), Decimal("10.0"), Decimal("100000"), Decimal("5.0"), True),
            "RSRUSDT": SymbolFilterInfo("RSRUSDT", Decimal("0.000001"), Decimal("10.0"), Decimal("100.0"), Decimal("10000000"), Decimal("5.0"), True),
            "AKEUSDT": SymbolFilterInfo("AKEUSDT", Decimal("0.00001"), Decimal("1.0"), Decimal("10.0"), Decimal("1000000"), Decimal("5.0"), True),
            "QTUMUSDT": SymbolFilterInfo("QTUMUSDT", Decimal("0.001"), Decimal("0.1"), Decimal("0.1"), Decimal("100000"), Decimal("5.0"), True),
            "ETHUSDT": SymbolFilterInfo("ETHUSDT", Decimal("0.01"), Decimal("0.001"), Decimal("0.001"), Decimal("1000"), Decimal("5.0"), True),
            "BTCUSDT": SymbolFilterInfo("BTCUSDT", Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal("500"), Decimal("5.0"), True),
        }
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.open_orders: Dict[str, Dict[str, Any]] = {}
        self.open_algo_orders: Dict[str, Dict[str, Any]] = {}
        self.margin_modes: Dict[str, str] = {}
        self.leverages: Dict[str, int] = {}
        self.fail_next_algo_order: bool = False
        self.always_fail_algo_order: bool = False

    async def get_symbol_filter(self, symbol: str) -> SymbolFilterInfo:
        if symbol not in self.symbols_info:
            raise ExchangeAdapterError(f"Symbol '{symbol}' khong ton tai tren Binance USD-M Futures")
        return self.symbols_info[symbol]

    async def check_position_mode_one_way(self) -> bool:
        if self.is_dual_side:
            raise AccountStateBlockedError("BLOCKED: Tai khoan dang o Hedge Mode")
        return True

    async def set_margin_type(self, symbol: str, margin_mode: str = "CROSSED") -> None:
        pos = self.positions.get(symbol)
        if pos and Decimal(str(pos.get("positionAmt", "0"))) != Decimal("0"):
            raise ExchangeAdapterError("Khong the doi margin type khi dang co vi the mo")
        self.margin_modes[symbol] = "CROSSED" if str(margin_mode).upper() in ("CROSS", "CROSSED") else "ISOLATED"

    async def set_margin_type_cross(self, symbol: str) -> None:
        await self.set_margin_type(symbol, "CROSSED")

    async def set_margin_type_isolated(self, symbol: str) -> None:
        await self.set_margin_type(symbol, "ISOLATED")

    async def get_max_leverage(self, symbol: str) -> int:
        return 20

    async def set_leverage(self, symbol: str, leverage: int) -> int:
        self.leverages[symbol] = leverage
        return leverage

    async def get_account_equity(self) -> Decimal:
        return self.equity

    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self.positions.get(symbol, {
            "symbol": symbol,
            "positionAmt": "0",
            "entryPrice": "0",
            "unrealizedProfit": "0",
            "marginType": self.margin_modes.get(symbol, "isolated"),
            "leverage": str(self.leverages.get(symbol, 1)),
        })

    async def get_open_positions(self) -> List[Dict[str, Any]]:
        return list(self.positions.values())

    async def get_market_trend_context(self, symbol: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "change_24h": 1.5,
            "volume_24h": 50000000.0,
            "funding_rate": 0.0001,
            "last_close": 150.0,
            "ema20_1h": 148.0,
            "trend_1h": "BULLISH",
            "trend_diff_pct": 1.35,
            "btc_change_24h": 1.2,
            "atr_1h": 2.5,
            "market_status": "NORMAL",
        }

    async def create_standard_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
        reduce_only: bool = False,
    ) -> Dict[str, Any]:
        # Enforce error -4120 if conditional orders are sent to standard endpoint
        if order_type in [OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET]:
            raise ExchangeAdapterError("Loi Binance -4120: STOP_ORDER_SWITCH_ALGO - Lenh conditional bat buoc gui qua /fapi/v1/algoOrder")

        order_id = str(uuid.uuid4().int)[:10]
        cid = client_order_id or f"mock_{order_id}"
        order = {
            "orderId": order_id,
            "clientOrderId": cid,
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "price": str(price) if price else "0",
            "origQty": str(quantity),
            "executedQty": "0",
            "status": "NEW",
            "reduceOnly": reduce_only,
        }
        if order_type == OrderType.MARKET:
            order["status"] = "FILLED"
            order["executedQty"] = str(quantity)
            side_mult = Decimal("-1") if side == OrderSide.SELL else Decimal("1")
            existing_amt = Decimal(str(self.positions.get(symbol, {}).get("positionAmt", "0")))
            new_amt = existing_amt + (quantity * side_mult)
            self.positions[symbol] = {
                "symbol": symbol,
                "positionAmt": str(new_amt),
                "entryPrice": str(price or "0"),
                "unrealizedProfit": "0",
                "marginType": self.margin_modes.get(symbol, "isolated"),
                "leverage": str(self.leverages.get(symbol, 1)),
            }
        else:
            self.open_orders[cid] = order
        return order

    async def create_algo_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        trigger_price: Decimal,
        quantity: Optional[Decimal] = None,
        client_algo_id: Optional[str] = None,
        close_position: bool = False,
        working_type: str = "MARK_PRICE",
        reduce_only: bool = True,
    ) -> Dict[str, Any]:
        if self.always_fail_algo_order:
            raise ExchangeAdapterError("Binance Algo Order Placement Failed (Persistent Failure)")
        if self.fail_next_algo_order:
            self.fail_next_algo_order = False
            raise ExchangeAdapterError("Binance Algo Order Placement Failed (Simulated Failure)")

        algo_id = str(uuid.uuid4().int)[:10]
        cid = client_algo_id or f"algo_{algo_id}"
        order = {
            "algoId": algo_id,
            "clientAlgoId": cid,
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "triggerPrice": str(trigger_price),
            "quantity": str(quantity) if quantity else None,
            "closePosition": close_position,
            "reduceOnly": reduce_only,
            "status": "NEW",
            "workingType": working_type,
        }
        self.open_algo_orders[cid] = order
        return order

    async def cancel_standard_order(self, symbol: str, client_order_id: str) -> Dict[str, Any]:
        if client_order_id in self.open_orders:
            order = self.open_orders.pop(client_order_id)
            order["status"] = "CANCELED"
            return order
        return {"status": "NOT_FOUND"}

    async def cancel_algo_order(self, symbol: str, algo_id: Optional[str] = None, client_algo_id: Optional[str] = None) -> Dict[str, Any]:
        target = client_algo_id or algo_id
        if target and target in self.open_algo_orders:
            order = self.open_algo_orders.pop(target)
            order["status"] = "CANCELED"
            return order
        return {"status": "NOT_FOUND"}

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        orders = list(self.open_orders.values())
        if symbol:
            orders = [o for o in orders if o.get("symbol") == symbol]
        return orders

    async def get_open_algo_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        orders = list(self.open_algo_orders.values())
        if symbol:
            orders = [o for o in orders if o.get("symbol") == symbol]
        return orders

    async def cancel_all_symbol_orders(self, symbol: str) -> Dict[str, Any]:
        stds = [k for k, o in self.open_orders.items() if o.get("symbol") == symbol]
        for k in stds:
            self.open_orders.pop(k, None)
        algos = [k for k, o in self.open_algo_orders.items() if o.get("symbol") == symbol]
        for k in algos:
            self.open_algo_orders.pop(k, None)
        return {"status": "SUCCESS", "standard_canceled": len(stds), "algo_canceled": len(algos)}

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Dict[str, Any]:
        if endpoint == "/fapi/v1/ticker/price":
            sym = params.get("symbol", "") if params else ""
            pos = self.positions.get(sym)
            p = pos.get("entryPrice", "2500") if pos else "2500"
            return {"symbol": sym, "price": p}
        return {}

    def set_mark_price(self, symbol: str, mark_price: Decimal) -> None:
        if symbol in self.positions:
            self.positions[symbol]["markPrice"] = str(mark_price)
            # Calculate unrealized pnl
            amt = Decimal(str(self.positions[symbol].get("positionAmt", "0")))
            entry_p = Decimal(str(self.positions[symbol].get("entryPrice", "0")))
            if amt != Decimal("0") and entry_p != Decimal("0"):
                diff = mark_price - entry_p
                unpnl = diff * amt
                self.positions[symbol]["unrealizedProfit"] = str(unpnl)

    # Helper method to simulate a fill in tests
    def simulate_entry_fill(self, client_order_id: str, fill_qty: Decimal, fill_price: Decimal) -> None:
        if client_order_id in self.open_orders:
            order = self.open_orders[client_order_id]
            order["executedQty"] = str(fill_qty)
            order["status"] = "FILLED" if fill_qty == Decimal(order["origQty"]) else "PARTIALLY_FILLED"
            sym = order["symbol"]
            side_mult = Decimal("1") if order["side"] == "BUY" else Decimal("-1")
            existing_amt = Decimal(str(self.positions.get(sym, {}).get("positionAmt", "0")))
            new_amt = existing_amt + (fill_qty * side_mult)
            self.positions[sym] = {
                "symbol": sym,
                "positionAmt": str(new_amt),
                "entryPrice": str(fill_price),
                "unrealizedProfit": "0",
                "marginType": self.margin_modes.get(sym, "isolated"),
                "leverage": str(self.leverages.get(sym, 1)),
            }

    def simulate_partial_close(self, symbol: str, close_qty: Decimal, exit_price: Decimal) -> None:
        if symbol in self.positions:
            pos = self.positions[symbol]
            current_amt = Decimal(str(pos.get("positionAmt", "0")))
            if current_amt > Decimal("0"):
                new_amt = max(Decimal("0"), current_amt - close_qty)
            else:
                new_amt = min(Decimal("0"), current_amt + close_qty)
            pos["positionAmt"] = str(new_amt)
            if new_amt == Decimal("0"):
                pos["entryPrice"] = "0"
                pos["unrealizedProfit"] = "0"

