import asyncio
import hashlib
import hmac
import json
import time
import urllib.parse
from decimal import Decimal
from typing import Any, Dict, List, Optional
import aiohttp

from config.config import AppConfig, exchange_writes_enabled, is_safe_testnet_url
from core.enums import ExecutionMode, MarginMode, OrderSide, OrderType, PositionSide
from core.exceptions import AccountStateBlockedError, ExchangeAdapterError
from exchange.exchange_info import SymbolFilterInfo, parse_symbol_info



def _format_decimal(val: Any) -> str:
    """Formats decimal or numeric value without scientific notation (e.g. 1e-8 -> 0.00000001)."""
    if val is None:
        return ""
    if isinstance(val, Decimal):
        return f"{val:f}"
    if isinstance(val, (float, int)):
        return f"{Decimal(str(val)):f}"
    return str(val)


class BinanceFuturesClient:
    """
    Async client for Binance USD-M Futures.
    Properly implements:
    - Standard Orders via /fapi/v1/order
    - Conditional / Algo Orders (STOP_MARKET, TAKE_PROFIT_MARKET) via /fapi/v1/algoOrder
    - Account preflight checks (One-Way mode, Isolated margin, Balance query)
    - Reconciles state without leaking secrets
    - Intelligent Circuit Breaker for IP bans and Rate Limits
    """

    _banned_until_ms: int = 0
    _banned_reason: str = ""
    _cached_one_way_mode: Optional[bool] = None
    _symbol_filter_cache: Dict[str, SymbolFilterInfo] = {}
    _weight_history: List[Any] = []
    _MAX_WEIGHT_PER_60S: int = 2000
    _time_offset_ms: int = 0
    _last_time_sync: float = 0.0

    def __init__(self, config: AppConfig, session: Optional[aiohttp.ClientSession] = None):
        self.config = config
        self._session = session
        self._own_session = False
        self._exchange_info_cache: Optional[List[Dict[str, Any]]] = None
        self._exchange_info_cached_at: float = 0.0

    @classmethod
    def is_rate_limited(cls) -> bool:
        return int(time.time() * 1000) < cls._banned_until_ms

    @classmethod
    def remaining_ban_seconds(cls) -> int:
        rem_ms = cls._banned_until_ms - int(time.time() * 1000)
        return max(0, int(rem_ms / 1000))

    @classmethod
    def _estimate_weight(cls, endpoint: str, params: Optional[Dict[str, Any]] = None) -> int:
        ep = endpoint.lower()
        if "exchangeinfo" in ep:
            return 40
        if "positionside/dual" in ep:
            return 30
        if "openorders" in ep:
            return 1 if (params and params.get("symbol")) else 40
        if "account" in ep or "positionrisk" in ep:
            return 5
        return 1

    @property
    def base_url(self) -> str:
        if self.config.mode == ExecutionMode.LIVE:
            return self.config.binance.live_base_url
        return self.config.binance.testnet_base_url

    @property
    def api_key(self) -> str:
        if self.config.mode == ExecutionMode.LIVE:
            return self.config.binance.live_api_key
        return self.config.binance.testnet_api_key

    @property
    def api_secret(self) -> str:
        if self.config.mode == ExecutionMode.LIVE:
            return self.config.binance.live_api_secret
        return self.config.binance.testnet_api_secret

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=100,
                keepalive_timeout=60.0,
                enable_cleanup_closed=True,
                ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(connector=connector)
            self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def sync_time(self) -> int:
        """
        Dong bo gio he thong voi may chu Binance Futures.
        Offset = server_time - local_time_ms.
        Dam bao timestamp gui len luon khop gio may chu va triet tieu loi -1021.
        """
        session = await self._get_session()
        time_url = f"{self.base_url}/fapi/v1/time"
        try:
            start_req = time.monotonic()
            async with session.get(time_url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    server_time = int(data["serverTime"])
                    rtt_ms = int((time.monotonic() - start_req) * 1000)
                    local_now_ms = int(time.time() * 1000)
                    offset = server_time - local_now_ms
                    BinanceFuturesClient._time_offset_ms = offset
                    BinanceFuturesClient._last_time_sync = time.time()
                    print(f"[BINANCE TIME SYNC] Dong bo thanh cong gio Binance: offset = {offset:+d}ms (RTT = {rtt_ms}ms)")
                    return offset
        except Exception as e:
            print(f"[BINANCE TIME SYNC] Khong the dong bo gio Binance: {e}")
        return BinanceFuturesClient._time_offset_ms

    def _sign_payload(self, params: Dict[str, Any]) -> str:
        if not self.api_secret:
            raise ExchangeAdapterError("API Secret chua duoc cau hinh")
        p = dict(params)
        p["timestamp"] = int(time.time() * 1000) + BinanceFuturesClient._time_offset_ms
        p["recvWindow"] = max(10000, self.config.binance.recv_window)
        query_string = urllib.parse.urlencode(p)
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
        _retry_count: int = 0,
    ) -> Dict[str, Any]:
        if method.upper() in {"POST", "PUT", "DELETE"}:
            if not exchange_writes_enabled(self.config):
                raise ExchangeAdapterError(
                    f"Exchange write blocked in {self.config.mode.value} mode"
                )
            if self.config.mode == ExecutionMode.TESTNET and not is_safe_testnet_url(self.config):
                raise ExchangeAdapterError("Unsafe Binance testnet URL; exchange write blocked")

        # Circuit Breaker: Do NOT send requests if currently banned by Binance
        now_ms = int(time.time() * 1000)
        if now_ms < BinanceFuturesClient._banned_until_ms:
            rem_sec = int((BinanceFuturesClient._banned_until_ms - now_ms) / 1000)
            raise ExchangeAdapterError(
                f"Binance IP dang bi tam khoa de bao ve tai khoan (con {rem_sec}s). {BinanceFuturesClient._banned_reason}"
            )

        # Token Bucket / Sliding window rate limiter
        req_weight = self._estimate_weight(endpoint, params)
        now_mono = time.monotonic()
        BinanceFuturesClient._weight_history = [
            (t, w) for t, w in BinanceFuturesClient._weight_history if now_mono - t < 60.0
        ]
        curr_weight = sum(w for _, w in BinanceFuturesClient._weight_history)

        # High priority exemption for order placement/algo endpoints (never stall orders)
        is_order_endpoint = any(kw in endpoint.lower() for kw in ["order", "algoorder"])
        effective_limit = 2300 if is_order_endpoint else BinanceFuturesClient._MAX_WEIGHT_PER_60S

        if curr_weight + req_weight > effective_limit and BinanceFuturesClient._weight_history:
            oldest_t = BinanceFuturesClient._weight_history[0][0]
            wait_sec = max(0.1, min(5.0, 60.0 - (now_mono - oldest_t) + 0.1))
            print(f"[BINANCE RATE LIMITER] Luu luong ({curr_weight}+{req_weight} > {effective_limit}). Cho {wait_sec:.1f}s...")
            await asyncio.sleep(wait_sec)
            now_mono = time.monotonic()
        BinanceFuturesClient._weight_history.append((now_mono, req_weight))

        # Auto sync Binance server time before signed requests if not yet synced or expired (> 1h)
        if signed and (BinanceFuturesClient._last_time_sync == 0 or (time.time() - BinanceFuturesClient._last_time_sync > 3600)):
            await self.sync_time()

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

                    # Timestamp desync auto-recovery (-1021)
                    if code == -1021 and _retry_count < 2:
                        print(f"[BINANCE TIME SYNC] Phat hien lech gio (-1021: {msg}). Dang dong bo lai va thu lai...")
                        await self.sync_time()
                        return await self._request(method, endpoint, params, signed=signed, _retry_count=_retry_count + 1)

                    # Detect IP Ban / Rate limit
                    if code == -1003 or resp.status in (429, 418):
                        import re
                        m = re.search(r"banned until (\d+)", msg)
                        if m:
                            BinanceFuturesClient._banned_until_ms = int(m.group(1))
                        else:
                            BinanceFuturesClient._banned_until_ms = int(time.time() * 1000) + 60000
                        BinanceFuturesClient._banned_reason = msg
                        rem_sec = int((BinanceFuturesClient._banned_until_ms - int(time.time() * 1000)) / 1000)
                        raise ExchangeAdapterError(
                            f"Binance API Error {code}: {msg} (Tự động kích hoạt Circuit Breaker trong {rem_sec}s)"
                        )

                    if code == -4120 or "STOP_ORDER_SWITCH_ALGO" in msg:
                        raise ExchangeAdapterError(
                            f"Loi Binance -4120: Lenh conditional bat buoc phai gui qua endpoint /fapi/v1/algoOrder: {msg}"
                        )
                    raise ExchangeAdapterError(f"Binance API Error {code}: {msg}")
                return data
        except (asyncio.TimeoutError, TimeoutError):
            if _retry_count < 2:
                print(f"[BINANCE RETRY] Mang Binance bi delay timeout. Dang thu lai lan {_retry_count + 1}...")
                await asyncio.sleep(0.5)
                return await self._request(method, endpoint, params, signed=signed, _retry_count=_retry_count + 1)
            raise ExchangeAdapterError(f"Hết thời gian chờ phản hồi từ Binance ({self.config.binance.request_timeout_seconds}s Timeout)")
        except aiohttp.ClientError as e:
            raise ExchangeAdapterError(f"Loi ket noi mang den Binance: {str(e)}")
        except Exception as e:
            if isinstance(e, ExchangeAdapterError):
                raise
            err_text = str(e) or type(e).__name__
            raise ExchangeAdapterError(f"Loi ket noi Binance ({type(e).__name__}): {err_text}")

    # 1. Exchange Info & Filters
    async def get_exchange_symbols(self, *, trading_only: bool = True) -> set[str]:
        """Return symbols currently published by Binance Futures exchangeInfo."""
        now = time.monotonic()
        if self._exchange_info_cache is None or now - self._exchange_info_cached_at >= 3600:
            data = await self._request("GET", "/fapi/v1/exchangeInfo")
            self._exchange_info_cache = list(data.get("symbols", []))
            self._exchange_info_cached_at = now
        return {
            str(item.get("symbol"))
            for item in self._exchange_info_cache
            if item.get("symbol") and (not trading_only or item.get("status") == "TRADING")
        }

    async def get_symbol_filter(self, symbol: str) -> SymbolFilterInfo:
        if symbol in BinanceFuturesClient._symbol_filter_cache:
            return BinanceFuturesClient._symbol_filter_cache[symbol]

        data = await self._request("GET", "/fapi/v1/exchangeInfo")
        self._exchange_info_cache = list(data.get("symbols", []))
        self._exchange_info_cached_at = time.monotonic()
        for sym_data in self._exchange_info_cache:
            s_name = sym_data.get("symbol")
            if s_name:
                try:
                    BinanceFuturesClient._symbol_filter_cache[s_name] = parse_symbol_info(sym_data)
                except Exception:
                    pass

        if symbol in BinanceFuturesClient._symbol_filter_cache:
            return BinanceFuturesClient._symbol_filter_cache[symbol]
        raise ExchangeAdapterError(f"Symbol '{symbol}' khong ton tai tren Binance USD-M Futures")

    # 2. Position Mode Check (One-Way vs Dual/Hedge)
    async def check_position_mode_one_way(self) -> bool:
        """Verifies account is in One-Way Position Mode (cached after first check)."""
        if BinanceFuturesClient._cached_one_way_mode is True:
            return True
        data = await self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        # {"dualSidePosition": false} means One-Way mode
        is_dual = data.get("dualSidePosition", False)
        if is_dual:
            raise AccountStateBlockedError(
                "BLOCKED: Tai khoan dang o che do Hedge Mode (Dual-Side). He thong chi ho tro One-Way Mode. "
                "Khong tu dong thay doi vi tranh rui ro cho cac vi the san co."
            )
        BinanceFuturesClient._cached_one_way_mode = True
        return True

    # 3. Margin Type Setup & Check
    async def set_margin_type(self, symbol: str, margin_mode: str = "CROSSED") -> None:
        """Sets margin mode to ISOLATED or CROSSED."""
        mode_str = "CROSSED" if str(margin_mode).upper() in ("CROSS", "CROSSED") else "ISOLATED"
        try:
            await self._request(
                "POST",
                "/fapi/v1/marginType",
                params={"symbol": symbol, "marginType": mode_str},
                signed=True,
            )
        except ExchangeAdapterError as e:
            # Code -4046 means "No need to change margin type" (already set)
            # Code -4067 means "Position side cannot be changed if open orders exist"
            if "-4046" not in str(e) and "-4067" not in str(e):
                raise

    async def set_margin_type_cross(self, symbol: str) -> None:
        """Sets margin mode to CROSSED (CROSS)."""
        await self.set_margin_type(symbol, "CROSSED")

    async def set_margin_type_isolated(self, symbol: str) -> None:
        """Sets margin mode to ISOLATED."""
        await self.set_margin_type(symbol, "ISOLATED")

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

    async def get_open_positions(self) -> List[Dict[str, Any]]:
        """Returns all active positions with non-zero positionAmt."""
        positions = await self._request("GET", "/fapi/v2/positionRisk", signed=True)
        active = []
        for pos in (positions or []):
            try:
                amt = float(pos.get("positionAmt", 0))
                if amt != 0:
                    active.append(pos)
            except Exception:
                pass
        return active

    async def get_market_trend_context(self, symbol: str) -> Dict[str, Any]:
        """
        Retrieves 24h ticker, funding rate, 1h klines (EMA20 trend), and BTC market context.
        Used for intelligent pre-trade verification and duplicate symbol analysis.
        """
        result = {
            "symbol": symbol,
            "change_24h": 0.0,
            "volume_24h": 0.0,
            "funding_rate": 0.0,
            "last_close": 0.0,
            "ema20_1h": 0.0,
            "trend_1h": "NEUTRAL",
            "trend_diff_pct": 0.0,
            "btc_change_24h": 0.0,
            "market_status": "NORMAL",
        }
        try:
            # 1. 24h Ticker for symbol
            t24 = await self._request("GET", "/fapi/v1/ticker/24hr", params={"symbol": symbol})
            result["change_24h"] = float(t24.get("priceChangePercent", 0.0))
            result["volume_24h"] = float(t24.get("quoteVolume", 0.0))
            result["last_close"] = float(t24.get("lastPrice", 0.0))
        except Exception:
            pass

        try:
            # 2. Premium / Funding rate
            p_idx = await self._request("GET", "/fapi/v1/premiumIndex", params={"symbol": symbol})
            result["funding_rate"] = float(p_idx.get("lastFundingRate", 0.0))
        except Exception:
            pass

        try:
            # 3. 1h Klines (20 candles)
            klines = await self._request("GET", "/fapi/v1/klines", params={"symbol": symbol, "interval": "1h", "limit": 20})
            if klines and len(klines) >= 5:
                closes = [float(k[4]) for k in klines]
                ema20 = sum(closes) / len(closes)
                result["ema20_1h"] = ema20
                last_c = closes[-1]
                result["last_close"] = last_c
                result["trend_1h"] = "BULLISH" if last_c >= ema20 else "BEARISH"
                result["trend_diff_pct"] = ((last_c - ema20) / ema20 * 100) if ema20 > 0 else 0.0

                # Trụ Cột 4: Calculate 14-period ATR from 1h candles
                if len(klines) >= 15:
                    tr_list = []
                    for i in range(1, len(klines)):
                        h = float(klines[i][2])
                        l = float(klines[i][3])
                        prev_c = float(klines[i - 1][4])
                        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
                        tr_list.append(tr)
                    if tr_list:
                        result["atr_1h"] = sum(tr_list[-14:]) / min(14, len(tr_list))
        except Exception:
            pass

        try:
            # 4. BTC 24h market context
            btc_24 = await self._request("GET", "/fapi/v1/ticker/24hr", params={"symbol": "BTCUSDT"})
            btc_change = float(btc_24.get("priceChangePercent", 0.0))
            result["btc_change_24h"] = btc_change
            if btc_change <= -5.0:
                result["market_status"] = "BTC_HIGH_VOLATILITY_DUMP"
            elif btc_change >= 5.0:
                result["market_status"] = "BTC_HIGH_VOLATILITY_PUMP"
        except Exception:
            pass

        return result

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
            "quantity": _format_decimal(quantity),
        }
        if price:
            params["price"] = _format_decimal(price)
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
        reduce_only: bool = True,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "triggerPrice": _format_decimal(trigger_price),
            "workingType": working_type,
        }
        if close_position:
            params["closePosition"] = "true"
        else:
            if reduce_only:
                params["reduceOnly"] = "true"
            else:
                params["reduceOnly"] = "false"
            if quantity:
                params["quantity"] = _format_decimal(quantity)

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

    async def create_user_data_listen_key(self) -> str:
        if not self.api_key:
            raise ExchangeAdapterError("API Key chua duoc cau hinh")
        data = await self._request("POST", "/fapi/v1/listenKey", params={}, signed=False)
        listen_key = str(data.get("listenKey") or "").strip()
        if not listen_key:
            raise ExchangeAdapterError("Binance khong tra ve listenKey")
        return listen_key

    async def keepalive_user_data_listen_key(self, listen_key: str) -> None:
        if not listen_key:
            raise ValueError("listenKey is required")
        await self._request("PUT", "/fapi/v1/listenKey", params={"listenKey": listen_key}, signed=False)

    async def delete_user_data_listen_key(self, listen_key: str) -> None:
        if listen_key:
            await self._request("DELETE", "/fapi/v1/listenKey", params={"listenKey": listen_key}, signed=False)

    async def get_user_trades(
        self,
        symbol: str,
        limit: int = 50,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        from_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not symbol:
            raise ValueError("Binance userTrades requires symbol")
        params: Dict[str, Any] = {"symbol": symbol, "limit": min(max(limit, 1), 1000)}
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        if from_id is not None:
            params["fromId"] = int(from_id)
        return await self._request("GET", "/fapi/v1/userTrades", params=params, signed=True)

    async def get_user_trades_window(
        self,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Fetch bounded symbol trades with deterministic pagination and dedupe."""
        if end_time_ms <= start_time_ms:
            return []
        results: List[Dict[str, Any]] = []
        seen = set()
        from_id: Optional[int] = None
        page_size = min(max(limit, 1), 1000)
        for _ in range(100):
            page = await self.get_user_trades(
                symbol,
                limit=page_size,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                from_id=from_id,
            )
            if not page:
                break
            for trade in page:
                trade_id = trade.get("id") or trade.get("tradeId")
                key = str(trade_id) if trade_id is not None else json.dumps(trade, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    results.append(trade)
            numeric_ids = [int(t.get("id")) for t in page if str(t.get("id", "")).isdigit()]
            if len(page) < page_size or not numeric_ids:
                break
            next_id = max(numeric_ids) + 1
            if from_id is not None and next_id <= from_id:
                break
            from_id = next_id
        return sorted(results, key=lambda item: int(item.get("time", 0)))

    async def get_income_history(
        self,
        income_type: Optional[str] = None,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": min(max(limit, 1), 1000)}
        if income_type:
            params["incomeType"] = income_type
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        return await self._request("GET", "/fapi/v1/income", params=params, signed=True)

    async def cancel_standard_order(self, symbol: str, client_order_id: str) -> Dict[str, Any]:
        return await self._request(
            "DELETE",
            self.config.binance.standard_order_endpoint,
            params={"symbol": symbol, "origClientOrderId": client_order_id},
            signed=True,
        )

    async def cancel_algo_order(self, symbol: str, algo_id: Optional[str] = None, client_algo_id: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": symbol}
        if algo_id:
            params["algoId"] = int(algo_id) if str(algo_id).isdigit() else algo_id
        elif client_algo_id:
            params["clientAlgoId"] = client_algo_id
        return await self._request("DELETE", self.config.binance.algo_order_endpoint, params=params, signed=True)

    async def cancel_all_orders(self, symbol: str) -> Dict[str, Any]:
        """Cancels all open standard limit/market orders on the symbol."""
        try:
            return await self._request("DELETE", "/fapi/v1/allOpenOrders", params={"symbol": symbol}, signed=True)
        except Exception as e:
            return {"error": str(e)}

    async def cancel_all_symbol_orders(self, symbol: str) -> Dict[str, Any]:
        """Cancels both standard limit orders and conditional algo orders (SL/TP) for the symbol."""
        std_res = await self.cancel_all_orders(symbol)
        algo_count = 0
        try:
            open_algos = await self.get_open_algo_orders(symbol)
            for algo in (open_algos or []):
                aid = algo.get("algoId")
                caid = algo.get("clientAlgoId")
                try:
                    await self.cancel_algo_order(symbol, algo_id=str(aid) if aid else None, client_algo_id=caid)
                    algo_count += 1
                except Exception:
                    pass
        except Exception:
            pass
        return {"standard": std_res, "algos_cancelled": algo_count}

