"""
risk/market_regime_shield.py
Trụ Cột 1: Correlation Shield & BTC Market Regime Filter.
Bảo vệ tài khoản trước các đợt sập giá diện rộng của Bitcoin (Panic Dump),
chặn tuyệt đối việc mua altcoin (LONG) khi dòng tiền cá mập rút lui.
"""

import time
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("market_regime_shield")


def calculate_ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0.0
    if len(prices) < period:
        return prices[-1]
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1.0 - k)
    return ema


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss <= 1e-9:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class MarketRegimeShield:
    """
    Correlation Shield & BTC 4H / 1H Market Regime Engine.
    
    Quy tắc kỷ luật Zero-Liquidation:
    1. Định kỳ tối đa 3 phút kiểm tra BTCUSDT.
    2. Nếu nến 4H nằm dưới cả EMA20 và EMA50, HOẶC RSI 1H < 40:
       Chuyển trạng thái sang BEARISH_PANIC.
    3. Ở trạng thái BEARISH_PANIC:
       - TỰ ĐỘNG CHẶN (BLOCK) 100% lệnh LONG của Altcoins.
       - Chỉ cho phép lệnh SHORT của Altcoins.
       - Lệnh trực tiếp trên BTCUSDT vẫn được xử lý theo phân tích kỹ thuật riêng.
    """

    def __init__(self, cache_ttl_seconds: int = 180, enabled: bool = True):
        self.cache_ttl_seconds = cache_ttl_seconds
        self.enabled = enabled
        self._last_update_ts: float = 0.0
        self._cached_regime: Dict[str, Any] = {
            "status": "NEUTRAL",
            "btc_price": 0.0,
            "btc_4h_ema20": 0.0,
            "btc_4h_ema50": 0.0,
            "btc_1h_rsi": 50.0,
            "reason": "Khởi tạo hệ thống",
            "timestamp": 0.0,
        }

    @property
    def current_regime(self) -> Dict[str, Any]:
        return dict(self._cached_regime)

    def is_cache_valid(self) -> bool:
        return (time.time() - self._last_update_ts) < self.cache_ttl_seconds

    def evaluate_regime_from_data(
        self,
        btc_4h_closes: List[float],
        btc_1h_closes: List[float],
    ) -> Dict[str, Any]:
        """
        Pure calculation method without network I/O, easy to test and verify.
        """
        if not btc_4h_closes or not btc_1h_closes:
            return {
                "status": "NEUTRAL",
                "btc_price": 0.0,
                "btc_4h_ema20": 0.0,
                "btc_4h_ema50": 0.0,
                "btc_1h_rsi": 50.0,
                "reason": "Thiếu dữ liệu nến BTC",
                "timestamp": time.time(),
            }

        btc_price = btc_4h_closes[-1]
        ema20_4h = calculate_ema(btc_4h_closes, 20)
        ema50_4h = calculate_ema(btc_4h_closes, 50)
        rsi_1h = calculate_rsi(btc_1h_closes, 14)

        is_below_emas = (btc_price < ema20_4h) and (btc_price < ema50_4h)
        is_rsi_dump = rsi_1h < 40.0

        if is_rsi_dump or (is_below_emas and rsi_1h < 42.0):
            status = "BEARISH_PANIC"
            reasons = []
            if is_below_emas:
                reasons.append(f"BTC 4H ({btc_price:.1f}) < EMA20 ({ema20_4h:.1f}) & EMA50 ({ema50_4h:.1f})")
            if is_rsi_dump or rsi_1h < 42.0:
                reasons.append(f"RSI 1H ({rsi_1h:.1f}) < 42 (Lực bán áp đảo)")
            reason = " | ".join(reasons)
        elif is_below_emas:
            status = "BEARISH_CORRECTION"
            reason = f"BTC 4H dưới EMA20/50 nhưng RSI 1H ({rsi_1h:.1f}) đang hồi phục tích lũy (Cho phép Long thận trọng)"
        elif (btc_price > ema20_4h) and (ema20_4h > ema50_4h) and (rsi_1h >= 50.0):
            status = "BULLISH_TREND"
            reason = f"BTC 4H ({btc_price:.1f}) > EMA20 ({ema20_4h:.1f}) > EMA50 ({ema50_4h:.1f}) và RSI 1H ({rsi_1h:.1f}) >= 50"
        else:
            status = "NEUTRAL"
            reason = f"BTC dao động tích lũy (Giá: {btc_price:.1f}, RSI 1H: {rsi_1h:.1f})"

        regime = {
            "status": status,
            "btc_price": btc_price,
            "btc_4h_ema20": round(ema20_4h, 2),
            "btc_4h_ema50": round(ema50_4h, 2),
            "btc_1h_rsi": round(rsi_1h, 2),
            "reason": reason,
            "timestamp": time.time(),
        }
        self._cached_regime = regime
        self._last_update_ts = time.time()
        return regime

    async def update_regime(self, client: Any, force: bool = False) -> Dict[str, Any]:
        """
        Queries Binance API for BTC 4H and 1H klines and updates regime.
        """
        if not self.enabled:
            return self._cached_regime

        if not force and self.is_cache_valid():
            return self._cached_regime

        try:
            # Query 4h klines (need at least 55 for EMA50)
            klines_4h = await client._request("GET", "/fapi/v1/klines", params={"symbol": "BTCUSDT", "interval": "4h", "limit": 60})
            # Query 1h klines (need at least 20 for RSI14)
            klines_1h = await client._request("GET", "/fapi/v1/klines", params={"symbol": "BTCUSDT", "interval": "1h", "limit": 30})

            if klines_4h and klines_1h:
                closes_4h = [float(k[4]) for k in klines_4h]
                closes_1h = [float(k[4]) for k in klines_1h]
                regime = self.evaluate_regime_from_data(closes_4h, closes_1h)
                logger.info(f"[BTC MARKET REGIME] Cập nhật: {regime['status']} | {regime['reason']}")
                return regime
        except Exception as e:
            logger.warning(f"[BTC MARKET REGIME] Không thể cập nhật từ sàn: {e}. Sử dụng cache cũ.")

        return self._cached_regime

    def check_signal_allowed(self, symbol: str, side: Any) -> Tuple[bool, str]:
        """
        Validates if an incoming signal is allowed under the current market regime.
        Returns (is_allowed, reason).
        """
        if not self.enabled:
            return True, "Market Regime Shield đang tắt."

        clean_symbol = symbol.upper().replace("/", "").replace(":", "")
        side_str = (side.value if hasattr(side, "value") else str(side)).upper()

        # BTC itself is handled by its own direct technical setup
        if clean_symbol in ("BTCUSDT", "BTCUSDC", "BTC"):
            return True, "Lệnh trực tiếp trên BTC được phép thực thi."

        status = self._cached_regime.get("status", "NEUTRAL")
        if status == "BEARISH_PANIC":
            if side_str in ("LONG", "BUY"):
                reason = (
                    f"Trụ cột 1 chặn lệnh: Thị trường chung BEARISH_PANIC "
                    f"({self._cached_regime.get('reason')}). Chặn mở Altcoin LONG để bảo toàn vốn!"
                )
                return False, reason
            elif side_str in ("SHORT", "SELL"):
                return True, "Thị trường BEARISH_PANIC: Cho phép mở lệnh SHORT Altcoin thuận xu hướng."

        return True, f"Market Regime ({status}) cho phép thực thi."


    def get_safe_leverage_ceiling(self, symbol: str, side: Any) -> Optional[int]:
        """
        Khống chế trần đòn bẩy an toàn theo bối cảnh thị trường (Macro Regime Clamp):
        Khi BTC ở trạng thái BEARISH_PANIC:
        - Mọi lệnh LONG của Altcoins tự động bị ghìm trần đòn bẩy tối đa 18x (dải 15x - 20x).
        - Ngăn ngừa biên độ rung lắc nhỏ của giá gây áp lực âm ROE quá lớn cho tài khoản.
        """
        if not self.enabled:
            return None

        clean_symbol = symbol.upper().replace("/", "").replace(":", "")
        side_str = (side.value if hasattr(side, "value") else str(side)).upper()

        if clean_symbol in ("BTCUSDT", "BTCUSDC", "BTC"):
            return None

        status = self._cached_regime.get("status", "NEUTRAL")
        if status in ("BEARISH_PANIC", "BEARISH_CORRECTION") and side_str in ("LONG", "BUY"):
            return 18

        return None


# Global singleton instance for system-wide access
global_market_regime_shield = MarketRegimeShield()
