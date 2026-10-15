import hashlib
import hmac
import time
import urllib.parse
from decimal import Decimal
from typing import Any, Dict, List, Optional
import aiohttp

from config.config import AppConfig
from core.enums import ExecutionMode, MarginMode, OrderSide, OrderType, PositionSide
from core.exceptions import AccountStateBlockedError, ExchangeAdapterError
from exchange.exchange_info import SymbolFilterInfo, parse_symbol_info


class BinanceFuturesClient:
    """
    Async client for Binance USD-M Futures.
    Properly implements:
    - Standard Orders via /fapi/v1/order
    - Conditional / Algo Orders (STOP_MARKET, TAKE_PROFIT_MARKET) via /fapi/v1/algoOrder
    - Account preflight checks (One-Way mode, Isolated margin, Balance query)
    - Reconciles state without leaking secrets
    """

    def __init__(self, config: AppConfig, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._own_session = False

        if config.mode == ExecutionMode.LIVE:
            self.base_url = config.binance.live_base_url
            self.api_key = config.binance.live_api_key
            self.api_secret = config.binance.live_api_secret
        else:
            self.base_url = config.binance.testnet_base_url
            self.api_key = config.binance.testnet_api_key
            self.api_secret = config.binance.testnet_api_secret

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    def _sign_payload(self, params: Dict[str, Any]) -> str:
        if not self.api_secret:
            raise ExchangeAdapterError("API Secret chua duoc cau hinh")
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self.config.binance.recv_window
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query_string}&signature={signature}"

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Dict[str, Any]:
        session = await self._get_session()
        headers = {}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key

        url = f"{self.base_url}{endpoint}"
        query_str = ""

        if signed:
            if not self.api_key or not self.api_secret:
                raise ExchangeAdapterError("Thieu API Key hoac Secret de thuc hien lenh co chu ky")
            query_str = self._sign_payload(params or {})
        elif params:
            query_str = urllib.parse.urlencode(params)

        if query_str:
            if method.upper() in ["GET", "DELETE"]:
                url = f"{url}?{query_str}"
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"

        try:
            async with session.request(
                method,
                url,
                data=query_str if method.upper() in ["POST", "PUT"] else None,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.config.binance.request_timeout_seconds),
            ) as resp:
                data = await resp.json()
                if resp.status >= 400:
                    code = data.get("code")
                    msg = data.get("msg", "")
                    if code == -4120 or "STOP_ORDER_SWITCH_ALGO" in msg:
                        raise ExchangeAdapterError(
                            f"Loi Binance -4120: Lenh conditional bat buoc phai gui qua endpoint /fapi/v1/algoOrder: {msg}"
                        )
                    raise ExchangeAdapterError(f"Binance API Error {code}: {msg}")
                return data
        except aiohttp.ClientError as e:
            raise ExchangeAdapterError(f"Loi ket noi mang den Binance: {str(e)}")

    # 1. Exchange Info & Filters
    async def get_symbol_filter(self, symbol: str) -> SymbolFilterInfo:
        data = await self._request("GET", "/fapi/v1/exchangeInfo")
        for sym_data in data.get("symbols", []):
            if sym_data.get("symbol") == symbol:
                return parse_symbol_info(sym_data)
        raise ExchangeAdapterError(f"Symbol '{symbol}' khong ton tai tren Binance USD-M Futures")

    # 2. Position Mode Check (One-Way vs Dual/Hedge)
    async def check_position_mode_one_way(self) -> bool:
        """Verifies account is in One-Way Position Mode."""
        data = await self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        # {"dualSidePosition": false} means One-Way mode
        is_dual = data.get("dualSidePosition", False)
        if is_dual:
            raise AccountStateBlockedError(
                "BLOCKED: Tai khoan dang o che do Hedge Mode (Dual-Side). He thong chi ho tro One-Way Mode. "
                "Khong tu dong thay doi vi tranh rui ro cho cac vi the san co."
            )
        return True

    # 3. Margin Type Setup & Check
    async def set_margin_type_isolated(self, symbol: str) -> None:
        """Sets margin mode to ISOLATED. Rejects if open position exists and cannot change."""
        try:
            await self._request(
                "POST",
                "/fapi/v1/marginType",
                params={"symbol": symbol, "marginType": "ISOLATED"},
                signed=True,
            )
        except ExchangeAdapterError as e:
            # Code -4046 means "No need to change margin type" (already isolated)
            if "-4046" not in str(e):
                raise

    # 4. Set Leverage
    async def set_leverage(self, symbol: str, leverage: int) -> int:
        data = await self._request(
            "POST",
            "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": leverage},
            signed=True,
        )
        return int(data.get("leverage", leverage))

    # 5. Account Balances & Equity
    async def get_account_equity(self) -> Decimal:
        """Returns total USDT margin balance (equity) from Futures account."""
        data = await self._request("GET", "/fapi/v2/account", signed=True)
        for asset in data.get("assets", []):
            if asset.get("asset") == "USDT":
                return Decimal(str(asset.get("marginBalance", "0")))
        return Decimal("0")

    # 6. Position Information
    async def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        positions = await self._request("GET", "/fapi/v2/positionRisk", params={"symbol": symbol}, signed=True)
        for pos in positions:
            if pos.get("symbol") == symbol:
                return pos
        return None

    # 7. Standard Orders (LIMIT Entry & TP)
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
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "quantity": str(quantity),
        }
        if price:
            params["price"] = str(price)
            params["timeInForce"] = "GTC"
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if reduce_only:
            params["reduceOnly"] = "true"

        return await self._request("POST", self.config.binance.standard_order_endpoint, params=params, signed=True)

    # 8. Conditional / Algo Orders (STOP_MARKET & TAKE_PROFIT_MARKET)
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
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "triggerPrice": str(trigger_price),
            "workingType": working_type,
            "reduceOnly": "true",
        }
        if close_position:
            params["closePosition"] = "true"
        elif quantity:
            params["quantity"] = str(quantity)

        if client_algo_id:
            params["clientAlgoId"] = client_algo_id

        return await self._request("POST", self.config.binance.algo_order_endpoint, params=params, signed=True)

    # 9. Query & Cancel Orders
    async def get_order_status(self, symbol: str, client_order_id: Optional[str] = None, order_id: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": symbol}
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        elif order_id:
            params["orderId"] = str(order_id)
        return await self._request("GET", self.config.binance.standard_order_endpoint, params=params, signed=True)

    async def get_algo_order_status(self, symbol: str, client_algo_id: Optional[str] = None, algo_id: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": symbol}
        if client_algo_id:
            params["clientAlgoId"] = client_algo_id
        elif algo_id:
            params["algoId"] = str(algo_id)
        return await self._request("GET", self.config.binance.algo_order_endpoint, params=params, signed=True)

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"symbol": symbol} if symbol else None
        return await self._request("GET", "/fapi/v1/openOrders", params=params, signed=True)

    async def get_open_algo_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"symbol": symbol} if symbol else None
        return await self._request("GET", "/fapi/v1/openAlgoOrders", params=params, signed=True)

    async def get_user_trades(self, symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
        return await self._request("GET", "/fapi/v1/userTrades", params={"symbol": symbol, "limit": limit}, signed=True)

    async def cancel_standard_order(self, symbol: str, client_order_id: str) -> Dict[str, Any]:
        return await self._request(
            "DELETE",
            self.config.binance.standard_order_endpoint,
            params={"symbol": symbol, "origClientOrderId": client_order_id},
            signed=True,
        )

    async def cancel_algo_order(self, symbol: str, algo_id: Optional[str] = None, client_algo_id: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": symbol}
        if client_algo_id:
            params["clientAlgoId"] = client_algo_id
        elif algo_id:
            params["algoId"] = algo_id
        return await self._request("DELETE", self.config.binance.algo_order_endpoint, params=params, signed=True)

