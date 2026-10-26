import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from config.config import AppConfig
from core.enums import ExecutionMode
from exchange.binance_client import BinanceFuturesClient


class BinanceAccountSnapshot(BaseModel):
    is_connected: bool = False
    connected: bool = False  # Compatibility alias for desktop frontend
    mode: ExecutionMode = ExecutionMode.READ_ONLY
    server_time: Optional[int] = None
    position_mode: str = "UNKNOWN"  # "ONE_WAY", "HEDGE", "UNKNOWN"
    wallet_balance: Optional[Decimal] = None
    equity: Optional[Decimal] = None
    total_margin_balance: Optional[Decimal] = None  # Compatibility alias
    available_balance: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    total_unrealized_pnl: Optional[Decimal] = None  # Compatibility alias
    total_maint_margin: Optional[Decimal] = None
    margin_ratio_pct: Optional[Decimal] = None
    open_positions: List[Dict[str, Any]] = []
    open_positions_count: int = 0
    active_orders: List[Dict[str, Any]] = []
    last_sync: Optional[str] = None
    last_sync_utc: Optional[str] = None
    can_trade: bool = False
    base_url: str = ""
    error_message: Optional[str] = None


class BinanceService:
    """
    Application service for Binance USD-M Futures account synchronization.
    Strict Invariants:
    - Never masks missing credentials or connection failures with 0 balances.
    - If disconnected: returns balances as None so UI shows "Chưa có dữ liệu".
    - Separates Testnet vs Live environments.
    - Strictly blocks any write calls if mode is READ_ONLY or PAPER.
    - Caches account snapshot for at least 15s to prevent API weight exhaustion.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._sync_attempted: bool = False
        self._last_sync_monotonic: float = 0.0
        self._consecutive_failures: int = 0
        self._cached_position_mode: Optional[str] = None
        self._last_mode_check: float = 0.0
        self._cached_snapshot: BinanceAccountSnapshot = BinanceAccountSnapshot(
            is_connected=False,
            connected=False,
            mode=config.mode,
        )

    def get_cached_snapshot(self) -> BinanceAccountSnapshot:
        return self._cached_snapshot

    def get_credentials_status(self) -> Dict[str, Any]:
        def mask(s: Optional[str]) -> Optional[str]:
            if not s:
                return None
            s = s.strip()
            if len(s) <= 8:
                return "***"
            return f"{s[:4]}...{s[-4:]}"

        return {
            "has_testnet_credentials": bool(self.config.binance.testnet_api_key and self.config.binance.testnet_api_secret),
            "testnet_api_key_masked": mask(self.config.binance.testnet_api_key),
            "has_live_credentials": bool(self.config.binance.live_api_key and self.config.binance.live_api_secret),
            "live_api_key_masked": mask(self.config.binance.live_api_key),
            "mode": self.config.mode.value,
        }

    def update_credentials(
        self,
        testnet_api_key: Optional[str] = None,
        testnet_api_secret: Optional[str] = None,
        live_api_key: Optional[str] = None,
        live_api_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Credentials stay in process/secret-store layer; never persist plaintext .env/YAML.
        if testnet_api_key is not None:
            self.config.binance.testnet_api_key = testnet_api_key.strip()
        if testnet_api_secret is not None:
            self.config.binance.testnet_api_secret = testnet_api_secret.strip()
        if live_api_key is not None:
            self.config.binance.live_api_key = live_api_key.strip()
        if live_api_secret is not None:
            self.config.binance.live_api_secret = live_api_secret.strip()

        return self.get_credentials_status()

    def remove_credentials(self, target: str = "all") -> Dict[str, Any]:

        if target in ("testnet", "all"):
            self.config.binance.testnet_api_key = None
            self.config.binance.testnet_api_secret = None
            # Secret store cleanup is handled by the credential provider; no plaintext env mutation.

        if target in ("live", "all"):
            self.config.binance.live_api_key = None
            self.config.binance.live_api_secret = None
            # Secret store cleanup is handled by the credential provider; no plaintext env mutation.
            if self.config.mode.value == "LIVE":
                self.config.mode = ExecutionMode.TESTNET

        self._cached_snapshot = BinanceAccountSnapshot(
            connected=False,
            is_connected=False,
            mode=self.config.mode.value,
            error_message="Chưa cấu hình API Key.",
        )
        return self.get_credentials_status()

    def has_credentials(self) -> bool:
        if self.config.mode == ExecutionMode.LIVE:
            return bool(self.config.binance.live_api_key and self.config.binance.live_api_secret)
        return bool(self.config.binance.testnet_api_key and self.config.binance.testnet_api_secret)

    async def test_connection(self, target_mode: Optional[str] = None) -> Dict[str, Any]:
        """
        Tests read-only connection against Binance Futures:
        1. Ping server time.
        2. Query Position Mode (One-Way).
        3. Query USDT margin equity.
        Supports testing either LIVE or TESTNET explicitly!
        """
        eff_mode = ExecutionMode(target_mode.upper()) if target_mode else self.config.mode
        if eff_mode == ExecutionMode.LIVE:
            if not self.config.binance.live_api_key or not self.config.binance.live_api_secret:
                return {
                    "success": False,
                    "error": "Thiếu API Key hoặc Secret của Live Binance trong cấu hình.",
                    "details": {},
                }
            candidate_urls = [self.config.binance.live_base_url]
        else:
            if not self.config.binance.testnet_api_key or not self.config.binance.testnet_api_secret:
                return {
                    "success": False,
                    "error": "Thiếu API Key hoặc Secret của Testnet trong cấu hình.",
                    "details": {},
                }
            candidate_urls = [
                "https://demo-fapi.binance.com",
                "https://testnet.binancefuture.com",
            ]

        last_error = None
        for base_url in candidate_urls:
            test_config = self.config.model_copy(deep=True)
            test_config.mode = eff_mode
            if eff_mode != ExecutionMode.LIVE:
                test_config.binance.testnet_base_url = base_url
            client = BinanceFuturesClient(test_config)
            try:
                time_data = await client._request("GET", "/fapi/v1/time")
                server_time = time_data.get("serverTime")

                is_one_way = await client.check_position_mode_one_way()
                equity = await client.get_account_equity()

                res = {
                    "success": True,
                    "server_time": server_time,
                    "position_mode": "ONE_WAY" if is_one_way else "HEDGE",
                    "equity": float(equity),
                    "base_url": base_url,
                    "target_mode": eff_mode.value,
                    "error": None,
                }
                if eff_mode == self.config.mode:
                    await self.sync_account()
                return res
            except Exception as e:
                last_error = e
            finally:
                await client.close()

        return {
            "success": False,
            "error": str(last_error),
            "details": {},
        }


    async def sync_account(self, force: bool = False) -> BinanceAccountSnapshot:
        """
        Synchronizes balances, open positions, and orders.
        Does not perform any trade execution.
        Caches results for 15 seconds unless force=True.
        """
        import time

        # Return cached snapshot if recent
        now_mono = time.monotonic()
        if not force and (now_mono - self._last_sync_monotonic < 15.0) and self._cached_snapshot.is_connected:
            return self._cached_snapshot

        if BinanceFuturesClient.is_rate_limited():
            rem = BinanceFuturesClient.remaining_ban_seconds()
            if self._cached_snapshot:
                self._cached_snapshot.error_message = f"IP tạm thời bị giới hạn tốc độ Binance (còn {rem}s nữa mở khóa). Tự động thử lại."
                return self._cached_snapshot

        if not self.has_credentials():
            self._cached_snapshot = BinanceAccountSnapshot(
                is_connected=False,
                mode=self.config.mode,
                error_message="Chưa cấu hình API Key/Secret",
            )
            return self._cached_snapshot

        candidate_urls = (
            [self.config.binance.live_base_url]
            if self.config.mode == ExecutionMode.LIVE
            else list(dict.fromkeys([
                self.config.binance.testnet_base_url,
                "https://demo-fapi.binance.com",
                "https://testnet.binancefuture.com",
            ]))
        )

        last_error = None
        for base_url in candidate_urls:
            if self.config.mode != ExecutionMode.LIVE:
                self.config.binance.testnet_base_url = base_url
            client = BinanceFuturesClient(self.config)
            try:
                # 1. Server time
                time_res = await client._request("GET", "/fapi/v1/time")
                server_time = time_res.get("serverTime")

                # 2. Position mode (cached 30 mins to avoid redundant signed requests)
                if self._cached_position_mode is None or (time.time() - self._last_mode_check > 1800):
                    try:
                        is_one_way = await client.check_position_mode_one_way()
                        self._cached_position_mode = "ONE_WAY" if is_one_way else "HEDGE"
                        self._last_mode_check = time.time()
                    except Exception:
                        self._cached_position_mode = self._cached_position_mode or "ONE_WAY"
                position_mode_str = self._cached_position_mode

                # 3. Account balance / equity
                acc_data = await client._request("GET", "/fapi/v2/account", signed=True)
                total_wallet = Decimal(acc_data.get("totalWalletBalance", "0"))
                total_equity = Decimal(acc_data.get("totalMarginBalance", "0"))
                available_balance = Decimal(acc_data.get("availableBalance", "0"))
                unrealized_pnl = Decimal(acc_data.get("totalUnrealizedProfit", "0"))

                # 4. Open positions
                pos_risk = await client.get_open_positions()

                # 5. Open orders (Standard Limit/Market)
                open_orders = await client._request("GET", "/fapi/v1/openOrders", signed=True)
                if not isinstance(open_orders, list):
                    open_orders = []

                # 6. Open Algo / Conditional orders (Stop Loss)
                try:
                    open_algos = await client.get_open_algo_orders()
                    if isinstance(open_algos, list):
                        for a in open_algos:
                            open_orders.append({
                                "orderId": a.get("algoId"),
                                "clientOrderId": a.get("clientAlgoId", ""),
                                "symbol": a.get("symbol"),
                                "side": a.get("side"),
                                "type": f"{a.get('orderType', 'STOP_MARKET')} (ALGO)",
                                "price": a.get("triggerPrice") or a.get("price", "0"),
                                "origQty": a.get("quantity", "0"),
                                "executedQty": a.get("actualQty", "0"),
                                "status": a.get("algoStatus", "NEW"),
                                "time": a.get("createTime"),
                                "is_algo": True,
                                "reduceOnly": a.get("reduceOnly", True),
                            })
                except Exception:
                    pass

                self._consecutive_failures = 0
                self._cached_snapshot = BinanceAccountSnapshot(
                    is_connected=True,
                    connected=True,
                    mode=self.config.mode,
                    server_time=server_time,
                    position_mode=position_mode_str,
                    wallet_balance=total_wallet,
                    equity=total_equity,
                    total_margin_balance=total_equity,
                    available_balance=available_balance,
                    unrealized_pnl=unrealized_pnl,
                    total_unrealized_pnl=unrealized_pnl,
                    total_maint_margin=Decimal("0.0"),
                    margin_ratio_pct=Decimal("0.0"),
                    open_positions=pos_risk,
                    open_positions_count=len(pos_risk),
                    active_orders=open_orders,
                    last_sync=datetime.utcnow().isoformat(),
                    last_sync_utc=datetime.utcnow().isoformat(),
                    can_trade=(
                        self.config.mode == ExecutionMode.TESTNET
                        or (self.config.mode == ExecutionMode.LIVE and self.config.live_trading_enabled)
                    ),
                    base_url=base_url,
                    error_message=None,
                )
                self._last_sync_monotonic = time.monotonic()
                return self._cached_snapshot
            except Exception as e:
                last_error = e
            finally:
                await client.close()

        self._consecutive_failures += 1
        # Chế độ chống chập chờn (Anti-Flapping): Nếu trước đó đang kết nối bình thường, không ngắt kết nối ngay khi gặp lỗi mạng tạm thời
        if self._cached_snapshot and self._cached_snapshot.is_connected and self._consecutive_failures < 3:
            return self._cached_snapshot

        self._cached_snapshot = BinanceAccountSnapshot(
            is_connected=False,
            connected=False,
            mode=self.config.mode,
            error_message=f"Lỗi đồng bộ Binance: {str(last_error)}",
        )
        return self._cached_snapshot

