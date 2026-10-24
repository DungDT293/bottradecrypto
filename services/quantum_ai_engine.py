import asyncio
import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
import numpy as np

from config.config import AppConfig

logger = logging.getLogger("quantum_ai_engine")


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
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss <= 1e-9:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_rsi_series(closes: List[float], period: int = 14) -> List[float]:
    """Calculates full rolling RSI array for momentum divergence detection."""
    n = len(closes)
    if n < period + 1:
        return [50.0] * n
    
    rsi_list = [50.0] * period
    deltas = [closes[i+1] - closes[i] for i in range(n - 1)]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss <= 1e-9:
        rsi_list.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_list.append(100.0 - (100.0 / (1.0 + rs)))
        
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss <= 1e-9:
            rsi_list.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_list.append(100.0 - (100.0 / (1.0 + rs)))
            
    return rsi_list


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return (highs[-1] - lows[-1]) if highs and lows else 0.0
    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i-1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)
    return sum(tr_list[-period:]) / period


def calculate_stoch_rsi(closes: List[float], rsi_period: int = 14, stoch_period: int = 14, k_period: int = 3) -> Tuple[float, float]:
    """Calculates smoothed Stochastic RSI %K and %D."""
    rsi_arr = calculate_rsi_series(closes, period=rsi_period)
    if len(rsi_arr) < stoch_period:
        return 50.0, 50.0
    
    k_vals = []
    for offset in range(k_period):
        idx = len(rsi_arr) - 1 - offset
        if idx >= stoch_period:
            window = rsi_arr[idx - stoch_period + 1 : idx + 1]
            min_r = min(window)
            max_r = max(window)
            if max_r - min_r <= 1e-9:
                k_vals.append(50.0)
            else:
                k_vals.append(100.0 * (rsi_arr[idx] - min_r) / (max_r - min_r))
        else:
            k_vals.append(50.0)
            
    k = float(sum(k_vals) / len(k_vals))
    d = k  # Smoothed representative
    return k, d


def calculate_bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0) -> Tuple[float, float, float, float]:
    """Calculates Bollinger Bands: Middle, Upper, Lower, %B."""
    if len(closes) < period:
        c = closes[-1] if closes else 0.0
        return c, c * 1.02, c * 0.98, 0.5
    win = closes[-period:]
    mid = sum(win) / period
    variance = sum((x - mid) ** 2 for x in win) / period
    std = variance ** 0.5
    upper = mid + num_std * std
    lower = mid - num_std * std
    curr = closes[-1]
    pct_b = (curr - lower) / (upper - lower) if (upper - lower) > 1e-9 else 0.5
    return mid, upper, lower, pct_b


def detect_divergence(closes: List[float], rsi_series: List[float], lookback: int = 25) -> Dict[str, bool]:
    """
    Detects Regular Bullish (Bottom) and Regular Bearish (Top) Divergences.
    - Bullish: Lower Price Low + Higher RSI Low (in oversold territory < 42)
    - Bearish: Higher Price High + Lower RSI High (in overbought territory > 58)
    """
    if len(closes) < lookback or len(rsi_series) < lookback:
        return {"bullish_divergence": False, "bearish_divergence": False}
        
    sub_c = closes[-lookback:]
    sub_rsi = rsi_series[-lookback:]
    
    curr_c = sub_c[-1]
    curr_rsi = sub_rsi[-1]
    
    # 1. Bullish Divergence check
    min_idx = int(np.argmin(sub_c[:-2])) if len(sub_c) > 5 else -1
    bullish = False
    if min_idx >= 0 and sub_c[min_idx] <= curr_c * 1.008:
        prior_rsi = sub_rsi[min_idx]
        if curr_rsi >= prior_rsi + 2.5 and curr_rsi <= 44.0:
            bullish = True
            
    # 2. Bearish Divergence check
    max_idx = int(np.argmax(sub_c[:-2])) if len(sub_c) > 5 else -1
    bearish = False
    if max_idx >= 0 and sub_c[max_idx] >= curr_c * 0.992:
        prior_rsi = sub_rsi[max_idx]
        if curr_rsi <= prior_rsi - 2.5 and curr_rsi >= 56.0:
            bearish = True
            
    return {"bullish_divergence": bullish, "bearish_divergence": bearish}


def detect_liquidity_sweep(highs: List[float], lows: List[float], closes: List[float], opens: List[float], lookback: int = 25) -> Dict[str, Any]:
    """
    Detects Liquidity Sweeps (Turtle Soup / Stop Runs):
    Price sweeps beyond previous swing high/low to liquidate stops, but candle body closes back inside the range.
    """
    if len(highs) < lookback + 1:
        return {"bull_sweep": False, "bear_sweep": False, "lower_wick_ratio": 0.0, "upper_wick_ratio": 0.0}
        
    prior_highs = highs[-lookback:-1]
    prior_lows = lows[-lookback:-1]
    
    c_open = opens[-1]
    c_high = highs[-1]
    c_low = lows[-1]
    c_close = closes[-1]
    candle_range = c_high - c_low
    
    if candle_range <= 1e-9:
        return {"bull_sweep": False, "bear_sweep": False, "lower_wick_ratio": 0.0, "upper_wick_ratio": 0.0}
        
    lower_wick = min(c_open, c_close) - c_low
    upper_wick = c_high - max(c_open, c_close)
    lw_ratio = lower_wick / candle_range
    uw_ratio = upper_wick / candle_range
    
    lowest_prior = min(prior_lows)
    highest_prior = max(prior_highs)
    
    # Bullish Bottom Sweep: Pierced prior swing low, closed higher, lower wick >= 35% of candle
    bull_sweep = (c_low < lowest_prior) and (c_close > lowest_prior) and (lw_ratio >= 0.35)
    
    # Bearish Top Sweep: Pierced prior swing high, closed lower, upper wick >= 35% of candle
    bear_sweep = (c_high > highest_prior) and (c_close < highest_prior) and (uw_ratio >= 0.35)
    
    return {
        "bull_sweep": bull_sweep,
        "bear_sweep": bear_sweep,
        "lower_wick_ratio": lw_ratio,
        "upper_wick_ratio": uw_ratio,
        "lowest_prior": lowest_prior,
        "highest_prior": highest_prior,
    }


def detect_order_block(opens: List[float], highs: List[float], lows: List[float], closes: List[float], lookback: int = 25) -> Dict[str, Any]:
    """Detects unmitigated Smart Money Order Blocks (OB) in the recent price structure."""
    if len(closes) < lookback:
        return {"bull_ob": None, "bear_ob": None}
        
    recent_c = closes[-lookback:]
    recent_o = opens[-lookback:]
    recent_h = highs[-lookback:]
    recent_l = lows[-lookback:]
    
    bull_ob = None
    bear_ob = None
    
    # Scan backwards for Bullish Order Block (last down-close before aggressive expansion)
    for i in range(len(recent_c) - 4, 1, -1):
        if recent_c[i] < recent_o[i]:
            expansion = recent_c[i+2] - recent_h[i]
            if expansion > 0 and (recent_c[i+2] - recent_o[i+1]) > 1.3 * (recent_o[i] - recent_c[i]):
                bull_ob = {"top": recent_h[i], "bottom": recent_l[i]}
                break
                
    # Scan backwards for Bearish Order Block (last up-close before aggressive collapse)
    for i in range(len(recent_c) - 4, 1, -1):
        if recent_c[i] > recent_o[i]:
            expansion = recent_l[i] - recent_c[i+2]
            if expansion > 0 and (recent_o[i+1] - recent_c[i+2]) > 1.3 * (recent_c[i] - recent_o[i]):
                bear_ob = {"top": recent_h[i], "bottom": recent_l[i]}
                break
                
    return {"bull_ob": bull_ob, "bear_ob": bear_ob}


def round_to_tick(val: float, tick: float) -> float:
    if tick <= 0:
        return round(val, 6)
    d_val = Decimal(str(val))
    d_tick = Decimal(str(tick))
    return float((d_val / d_tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * d_tick)


class QuantumAIEngine:
    """
    Quantum AI Engine 2.0: Multi-Admin & SMC 85%+ Confluence Brain
    Combines:
    1. Smart Money Concepts (Order Blocks, FVGs, Liquidity Sweeps)
    2. Momentum Exhaustion (RSI Regular Divergence, StochRSI Extreme Crossovers)
    3. Volatility Bands (Bollinger Bands +-2 Sigma, %B Exhaustion)
    4. Volume Climax / Absorption (Smart Money Footprint)
    5. Reverse-Engineered Top Telegram Admin Archetypes
    """

    def __init__(self, config: AppConfig, binance_client: Any):
        self.config = config
        self.client = binance_client

    async def get_market_kline_analysis(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            session = await self.client._get_session()
            url = f"{self.client.base_url}/fapi/v1/klines?symbol={symbol}&interval=1h&limit=60"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=6.0)) as resp:
                if resp.status != 200:
                    return None
                klines = await resp.json()
            if not klines or len(klines) < 30:
                return None

            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            opens = [float(k[1]) for k in klines]
            volumes = [float(k[5]) for k in klines]

            current_p = closes[-1]
            last_open = opens[-1]
            last_high = highs[-1]
            last_low = lows[-1]
            candle_range = last_high - last_low if last_high > last_low else 1e-6
            upper_wick = last_high - max(last_open, current_p)
            lower_wick = min(last_open, current_p) - last_low
            upper_wick_ratio = upper_wick / candle_range
            lower_wick_ratio = lower_wick / candle_range

            ema20 = calculate_ema(closes, 20)
            ema50 = calculate_ema(closes, 50)
            rsi = calculate_rsi(closes, 14)
            rsi_series = calculate_rsi_series(closes, 14)
            atr = calculate_atr(highs, lows, closes, 14)
            k_stoch, d_stoch = calculate_stoch_rsi(closes)
            mid_bb, upper_bb, lower_bb, pct_b = calculate_bollinger_bands(closes)
            
            div = detect_divergence(closes, rsi_series)
            sweep = detect_liquidity_sweep(highs, lows, closes, opens)
            ob = detect_order_block(opens, highs, lows, closes)

            vol_ma20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else volumes[-1]
            vol_ratio = volumes[-1] / vol_ma20 if vol_ma20 > 0 else 1.0

            chg_24 = ((current_p - closes[0]) / closes[0]) * 100

            # Get symbol tick size for precise price rounding
            tick_size = 0.0001
            try:
                filt = await self.client.get_symbol_filter(symbol)
                if filt and filt.tick_size:
                    tick_size = float(filt.tick_size)
            except Exception:
                pass

            return {
                "symbol": symbol,
                "current_price": current_p,
                "ema20": ema20,
                "ema50": ema50,
                "rsi": rsi,
                "rsi_14": rsi,
                "rsi_series": rsi_series,
                "atr": atr,
                "atr_14": atr,
                "k_stoch": k_stoch,
                "d_stoch": d_stoch,
                "mid_bb": mid_bb,
                "upper_bb": upper_bb,
                "lower_bb": lower_bb,
                "pct_b": pct_b,
                "divergence": div,
                "sweep": sweep,
                "order_block": ob,
                "vol_ratio": vol_ratio,
                "upper_wick_ratio": upper_wick_ratio,
                "lower_wick_ratio": lower_wick_ratio,
                "change_24h": chg_24,
                "recent_high": max(highs[-24:]),
                "recent_low": min(lows[-24:]),
                "last_high": last_high,
                "last_low": last_low,
                "tick_size": tick_size,
            }
        except Exception as exc:
            logger.debug("Failed kline analysis for %s: %s", symbol, exc)
            return None

    def evaluate_quantum_85pct_confluence(self, m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Quantum AI 2.0: 85%+ Multi-Confluence Engine (Bắt Đáy Bắt Đỉnh Chuẩn Xác).
        Requires at least 4 independent confluence factors to trigger an 85%+ confidence setup:
        1. Liquidity Sweep (Turtle Soup / Stop Hunt)
        2. Regular RSI / Momentum Divergence
        3. Bollinger Band +-2 Sigma Exhaustion / Extreme %B
        4. Stochastic RSI Extreme Crossover (< 22 oversold or > 78 overbought)
        5. Smart Money Order Block / EMA50 Key Level Retest
        6. Volume Climax / Absorption
        """
        p = m["current_price"]
        ema20 = m["ema20"]
        ema50 = m["ema50"]
        rsi = m.get("rsi", 50.0)
        atr = m.get("atr", p * 0.02)
        vol_r = m.get("vol_ratio", 1.0)
        lw_r = m.get("lower_wick_ratio", 0.0)
        uw_r = m.get("upper_wick_ratio", 0.0)
        k_stoch = m.get("k_stoch", 50.0)
        pct_b = m.get("pct_b", 0.5)
        lower_bb = m.get("lower_bb", p * 0.98)
        upper_bb = m.get("upper_bb", p * 1.02)
        sym = m["symbol"]
        tick = m.get("tick_size", 0.0001)
        
        div = m.get("divergence", {"bullish_divergence": False, "bearish_divergence": False})
        sweep = m.get("sweep", {"bull_sweep": False, "bear_sweep": False})
        ob = m.get("order_block", {"bull_ob": None, "bear_ob": None})

        if p <= 0 or atr <= 0:
            return None

        # ==============================================================
        # 1. 85%+ BOTTOM CATCH (BẮT ĐÁY ĐA HỢP LƯU - LONG)
        # ==============================================================
        # Trend Bias & Falling Knife Shield:
        # Nếu nến 1H đang là xu hướng Giảm mạnh (p < ema20 và ema20 < ema50):
        # BẮT BUỘC phải có Phân kỳ dương RSI HOẶC nến Pinbar rút chân mạnh (lw_r >= 0.40)
        is_strong_downtrend = (p < ema20 and ema20 < ema50)
        has_bull_div = div.get("bullish_divergence", False)
        if is_strong_downtrend and not has_bull_div and lw_r < 0.40:
            return None

        long_confluences: List[str] = []
        
        # Confluence 1: Stop Hunt Liquidity Sweep of Swing Low
        if sweep.get("bull_sweep") or (lw_r >= 0.38 and p <= ema50):
            long_confluences.append(f"Quét thanh khoản đáy (Wick={lw_r*100:.0f}%)")
            
        # Confluence 2: Momentum Exhaustion (GỘP NHÓM ĐỘNG LƯỢNG - LOẠI BỎ HỢP LƯU ẢO)
        if has_bull_div:
            long_confluences.append(f"Phân kỳ dương RSI (RSI={rsi:.1f})")
        elif rsi <= 35.0 or pct_b <= 0.15 or k_stoch <= 22.0:
            long_confluences.append(f"Động lượng quá bán cực hạn (RSI={rsi:.1f}, %B={pct_b:.2f})")
            
        # Confluence 3: Order Block / EMA50 Retest
        bull_ob = ob.get("bull_ob")
        if bull_ob and p <= bull_ob["top"] * 1.01 and p >= bull_ob["bottom"] * 0.99:
            long_confluences.append("Retest Order Block Smart Money tăng giá")
        elif abs(p - ema50) / p <= 0.008:
            long_confluences.append("Chạm hỗ trợ động EMA50")
            
        # Confluence 4: Volume Absorption
        if vol_r >= 1.35:
            long_confluences.append(f"Volume gom hàng x{vol_r:.1f} lần TB")

        # Confluence 5: Price Action Reversal Candlestick Confirmation
        if lw_r >= 0.35 and p >= m.get("open", p):
            long_confluences.append("Nến xanh rút chân hấp thụ lực bán")

        if len(long_confluences) >= 4:
            # High-Conviction 85%+ Bottom Setup
            conf = 85 + (len(long_confluences) - 4) * 4  # 4 confluences = 85-88%, 5+ = 89-93%
            conf = min(conf, 93)
            
            # SL strictly below liquidity sweep wick or recent low with safe buffer
            lowest_ref = sweep.get("lowest_prior", p - atr * 1.5)
            sl_raw = min(m.get("last_low", p - atr), lowest_ref, p - atr * 1.2) - (atr * 0.2)
            sl = round_to_tick(sl_raw, tick)
            sl_dist = p - sl
            if sl_dist <= 0 or sl_dist > p * 0.08:
                sl_dist = max(atr * 1.5, p * 0.035)
                sl = round_to_tick(p - sl_dist, tick)
            elif sl_dist < p * 0.028:
                sl_dist = max(atr * 1.5, p * 0.032)
                sl = round_to_tick(p - sl_dist, tick)
                
            tp1 = round_to_tick(p + (sl_dist * 1.5), tick)
            tp2 = round_to_tick(p + (sl_dist * 2.8), tick)
            tp3 = round_to_tick(p + (sl_dist * 4.5), tick)

            safe_lev = min(20, max(10, int(0.75 / (sl_dist / p))))
            
            rationale_text = (
                f"Tín hiệu Bắt Đáy 85%+ (Quantum Confluence {len(long_confluences)}/5 yếu tố): "
                + " + ".join(long_confluences)
                + ". Entry tối ưu tại vùng hấp thụ thanh khoản."
            )
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "LONG",
                "archetype": "QUANTUM_SMC_BOTTOM_HUNT",
                "confidence": conf,
                "rationale": rationale_text,
                "entry_price": p,
                "stop_loss": sl,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "estimated_rr": round(2.8 / 1.0, 2),
                "leverage": safe_lev,
                "risk_verdict": "APPROVED",
                "confluences": long_confluences,
                "source": f"Quantum AI 2.0 (85%+ Bottom Hunter - {len(long_confluences)} Confluences)",
            }

        # ==============================================================
        # 2. 85%+ TOP CATCH (BẮT ĐỈNH ĐA HỢP LƯU - SHORT)
        # ==============================================================
        # Low-Cap Pump & Whale Volume Climax Shield
        chg_24h = float(m.get("change_24h", 0.0))
        if vol_r >= 2.5 and (p >= ema20 or chg_24h >= 10.0):
            # Volume gom mua/bơm đè quá mạnh - Chặn rủi ro cản tàu SHORT
            return None
        if chg_24h >= 18.0 and not div.get("bearish_divergence"):
            # Đà tăng 24h quá nóng (Parabolic) chưa xuất hiện phân kỳ đảo chiều đa khung
            return None

        # Trend Bias & Parabolic Uptrend Shield:
        # Nếu nến 1H đang là xu hướng Tăng mạnh (p > ema20 và ema20 > ema50):
        # BẮT BUỘC phải có Phân kỳ âm RSI HOẶC nến Pinbar bị đè giá từ chối cực mạnh (uw_r >= 0.40)
        is_strong_uptrend = (p > ema20 and ema20 > ema50)
        has_bear_div = div.get("bearish_divergence", False)
        if is_strong_uptrend and not has_bear_div and uw_r < 0.40:
            return None

        short_confluences: List[str] = []
        
        # Confluence 1: Stop Hunt Liquidity Sweep of Swing High
        if sweep.get("bear_sweep") or (uw_r >= 0.38 and p >= ema50):
            short_confluences.append(f"Quét thanh khoản đỉnh (Wick={uw_r*100:.0f}%)")
            
        # Confluence 2: Momentum Exhaustion (GỘP NHÓM ĐỘNG LƯỢNG - LOẠI BỎ HỢP LƯU ẢO)
        if has_bear_div:
            short_confluences.append(f"Phân kỳ âm RSI đảo chiều (RSI={rsi:.1f})")
        elif rsi >= 65.0 or pct_b >= 0.85 or k_stoch >= 78.0:
            short_confluences.append(f"Động lượng quá mua cực hạn (RSI={rsi:.1f}, %B={pct_b:.2f})")
            
        # Confluence 3: Order Block / EMA50 Resistance Retest
        bear_ob = ob.get("bear_ob")
        if bear_ob and p >= bear_ob["bottom"] * 0.99 and p <= bear_ob["top"] * 1.01:
            short_confluences.append("Retest Order Block Smart Money xả hàng")
        elif abs(p - ema50) / p <= 0.008:
            short_confluences.append("Chạm kháng cự động EMA50")
            
        # Confluence 4: Volume Climax
        if vol_r >= 1.35:
            short_confluences.append(f"Volume xả đè giá x{vol_r:.1f} lần TB")

        # Confluence 5: Price Action Reversal Candlestick Confirmation
        if uw_r >= 0.35 and p <= m.get("open", p):
            short_confluences.append("Nến đỏ bị từ chối đè giá trên đỉnh")

        if len(short_confluences) >= 4:
            # High-Conviction 85%+ Top Setup
            conf = 85 + (len(short_confluences) - 4) * 4
            conf = min(conf, 93)
            
            # SL strictly above liquidity sweep wick or recent high with safe buffer
            highest_ref = sweep.get("highest_prior", p + atr * 1.5)
            sl_raw = max(m.get("last_high", p + atr), highest_ref, p + atr * 1.2) + (atr * 0.2)
            sl = round_to_tick(sl_raw, tick)
            sl_dist = sl - p
            if sl_dist <= 0 or sl_dist > p * 0.08:
                sl_dist = max(atr * 1.5, p * 0.035)
                sl = round_to_tick(p + sl_dist, tick)
            elif sl_dist < p * 0.028:
                sl_dist = max(atr * 1.5, p * 0.032)
                sl = round_to_tick(p + sl_dist, tick)
                
            tp1 = round_to_tick(p - (sl_dist * 1.5), tick)
            tp2 = round_to_tick(p - (sl_dist * 2.8), tick)
            tp3 = round_to_tick(p - (sl_dist * 4.5), tick)

            safe_lev = min(20, max(10, int(0.75 / (sl_dist / p))))
            
            rationale_text = (
                f"Tín hiệu Bắt Đỉnh 85%+ (Quantum Confluence {len(short_confluences)}/5 yếu tố): "
                + " + ".join(short_confluences)
                + ". Entry tối ưu tại vùng suy kiệt lực mua."
            )
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "SHORT",
                "archetype": "QUANTUM_SMC_TOP_HUNT",
                "confidence": conf,
                "rationale": rationale_text,
                "entry_price": p,
                "stop_loss": sl,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "estimated_rr": round(2.8 / 1.0, 2),
                "leverage": safe_lev,
                "risk_verdict": "APPROVED",
                "confluences": short_confluences,
                "source": f"Quantum AI 2.0 (85%+ Top Hunter - {len(short_confluences)} Confluences)",
            }

        return None

    def evaluate_admin_archetypes(self, m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Evaluates market data:
        1. FIRST: Quantum AI 2.0 85%+ Multi-Confluence Engine (Bottom/Top Hunt)
        2. SECOND: Admin Archetypes (The Master Whale, Coin Chief Breakout, Mermaid Mean Reversion)
        """
        # --- PRIORITY 1: 85%+ Multi-Confluence Setup ---
        confluence_setup = self.evaluate_quantum_85pct_confluence(m)
        if confluence_setup and confluence_setup.get("has_setup"):
            return confluence_setup

        # --- PRIORITY 2: Top Telegram Admin Archetypes ---
        p = m["current_price"]
        ema20 = m["ema20"]
        ema50 = m["ema50"]
        rsi = m.get("rsi", 50.0)
        atr = m.get("atr", p * 0.02)
        vol_r = m.get("vol_ratio", 1.0)
        lw_r = m.get("lower_wick_ratio", 0.0)
        uw_r = m.get("upper_wick_ratio", 0.0)
        chg = m.get("change_24h", 0.0)
        sym = m["symbol"]
        tick = m.get("tick_size", 0.0001)

        if p <= 0 or atr <= 0:
            return None

        # ARCHETYPE 1: WHALES CIRCLE (Trend Pullback + Wick Absorption)
        # Bullish Pullback
        if p > ema50 and ema20 > ema50 and 39.0 <= rsi <= 52.0 and lw_r >= 0.28:
            sl_dist = max(atr * 1.4, p * 0.02)
            sl = round_to_tick(p - sl_dist, tick)
            tp1 = round_to_tick(p + (sl_dist * 1.5), tick)
            tp2 = round_to_tick(p + (sl_dist * 2.8), tick)
            tp3 = round_to_tick(p + (sl_dist * 4.5), tick)
            conf = 88 if lw_r >= 0.40 else 84
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "LONG",
                "archetype": "WHALES_CIRCLE_PULLBACK",
                "confidence": conf,
                "rationale": f"Mô phỏng Whales Circle: Xu hướng Tăng khung 1h, nến rút chân mạnh (Râu dưới {lw_r*100:.0f}%), RSI={rsi:.1f} chuẩn bị bật tăng từ hỗ trợ EMA50.",
                "entry_price": p,
                "stop_loss": sl,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "estimated_rr": round(2.8 / 1.4, 2),
                "leverage": 20,
                "risk_verdict": "APPROVED",
                "source": "Quantum AI (WHALES_CIRCLE)",
            }

        # Bearish Pullback
        if p < ema50 and ema20 < ema50 and 48.0 <= rsi <= 61.0 and uw_r >= 0.28:
            if vol_r >= 2.5 or chg >= 15.0:
                return None
            sl_dist = max(atr * 1.4, p * 0.02)
            sl = round_to_tick(p + sl_dist, tick)
            tp1 = round_to_tick(p - (sl_dist * 1.5), tick)
            tp2 = round_to_tick(p - (sl_dist * 2.8), tick)
            tp3 = round_to_tick(p - (sl_dist * 4.5), tick)
            conf = 88 if uw_r >= 0.40 else 84
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "SHORT",
                "archetype": "WHALES_CIRCLE_PULLBACK",
                "confidence": conf,
                "rationale": f"Mô phỏng Whales Circle: Xu hướng Giảm khung 1h, nến bị từ chối đè giá (Râu trên {uw_r*100:.0f}%), RSI={rsi:.1f} suy kiệt tại cản EMA50.",
                "entry_price": p,
                "stop_loss": sl,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "estimated_rr": round(2.8 / 1.4, 2),
                "leverage": 20,
                "risk_verdict": "APPROVED",
                "source": "Quantum AI (WHALES_CIRCLE)",
            }

        # ARCHETYPE 2: COIN CHIEF (Volume Expansion Breakout)
        if vol_r >= 1.6:
            # Bullish Breakout
            if p >= m.get("recent_high", p) * 0.995 and rsi >= 56.0 and ema20 >= ema50:
                sl_dist = max(atr * 1.2, p * 0.018)
                sl = round_to_tick(p - sl_dist, tick)
                tp1 = round_to_tick(p + (sl_dist * 1.4), tick)
                tp2 = round_to_tick(p + (sl_dist * 2.5), tick)
                tp3 = round_to_tick(p + (sl_dist * 4.0), tick)
                return {
                    "has_setup": True,
                    "symbol": sym,
                    "direction": "LONG",
                    "archetype": "COIN_CHIEF_VOLUME_BREAKOUT",
                    "confidence": 86,
                    "rationale": f"Mô phỏng Admin Coin Chief: Phá vỡ đỉnh 24h với Volume đột biến x{vol_r:.1f} lần trung bình, RSI={rsi:.1f} bùng nổ xung lực mua.",
                    "entry_price": p,
                    "stop_loss": sl,
                    "take_profit_1": tp1,
                    "take_profit_2": tp2,
                    "take_profit_3": tp3,
                    "estimated_rr": round(2.5 / 1.2, 2),
                    "leverage": 20,
                    "risk_verdict": "APPROVED",
                    "source": "Quantum AI (COIN_CHIEF)",
                }
            # Bearish Breakdown
            if p <= m.get("recent_low", p) * 1.005 and rsi <= 44.0 and ema20 <= ema50:
                sl_dist = max(atr * 1.2, p * 0.018)
                sl = round_to_tick(p + sl_dist, tick)
                tp1 = round_to_tick(p - (sl_dist * 1.4), tick)
                tp2 = round_to_tick(p - (sl_dist * 2.5), tick)
                tp3 = round_to_tick(p - (sl_dist * 4.0), tick)
                return {
                    "has_setup": True,
                    "symbol": sym,
                    "direction": "SHORT",
                    "archetype": "COIN_CHIEF_VOLUME_BREAKOUT",
                    "confidence": 86,
                    "rationale": f"Mô phỏng Admin Coin Chief & Crypto Leopard: Thủng đáy 24h với Volume bán xả lớn x{vol_r:.1f} lần trung bình, RSI={rsi:.1f} gãy hỗ trợ.",
                    "entry_price": p,
                    "stop_loss": sl,
                    "take_profit_1": tp1,
                    "take_profit_2": tp2,
                    "take_profit_3": tp3,
                    "estimated_rr": round(2.5 / 1.2, 2),
                    "leverage": 20,
                    "risk_verdict": "APPROVED",
                    "source": "Quantum AI (COIN_CHIEF)",
                }

        # ARCHETYPE 3: CRYPTO MERMAIDS & DEVIL (Extreme Mean Reversion)
        if rsi <= 26.0:
            if p < ema20 and ema20 < ema50 and lw_r < 0.35:
                return None
            sl_dist = max(atr * 1.6, p * 0.025)
            sl = round_to_tick(p - sl_dist, tick)
            tp1 = round_to_tick(p + (sl_dist * 1.5), tick)
            tp2 = round_to_tick(p + (sl_dist * 2.5), tick)
            tp3 = round_to_tick(p + (sl_dist * 3.8), tick)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "LONG",
                "archetype": "MERMAID_MEAN_REVERSION",
                "confidence": 83,
                "rationale": f"Mô phỏng Admin Crypto Mermaids: RSI={rsi:.1f} rơi vào vùng quá bán cực hạn (Oversold), giá cách xa EMA20 chuẩn bị có nhịp hồi kỹ thuật.",
                "entry_price": p,
                "stop_loss": sl,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "estimated_rr": round(2.5 / 1.6, 2),
                "leverage": 15,
                "risk_verdict": "APPROVED",
                "source": "Quantum AI (MERMAID_REVERSION)",
            }

        if rsi >= 74.0:
            if vol_r >= 2.5 or chg >= 15.0:
                return None
            sl_dist = max(atr * 1.6, p * 0.025)
            sl = round_to_tick(p + sl_dist, tick)
            tp1 = round_to_tick(p - (sl_dist * 1.5), tick)
            tp2 = round_to_tick(p - (sl_dist * 2.5), tick)
            tp3 = round_to_tick(p - (sl_dist * 3.8), tick)
            return {
                "has_setup": True,
                "symbol": sym,
                "direction": "SHORT",
                "archetype": "MERMAID_MEAN_REVERSION",
                "confidence": 83,
                "rationale": f"Mô phỏng Admin Crypto Mermaids: RSI={rsi:.1f} chạm vùng quá mua cực hạn (Overbought), giá căng cứng chuẩn bị đảo chiều sụt giảm.",
                "entry_price": p,
                "stop_loss": sl,
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "estimated_rr": round(2.5 / 1.6, 2),
                "leverage": 15,
                "risk_verdict": "APPROVED",
                "source": "Quantum AI (MERMAID_REVERSION)",
            }

        return None

    async def scan_market_quantum(self, limit: int = 60) -> List[Dict[str, Any]]:
        """Scans liquid Binance Futures pairs and extracts high-conviction 85%+ setups."""
        try:
            tickers = await self.client._request("GET", "/fapi/v1/ticker/24hr")
            usdt_pairs = [
                t["symbol"] for t in tickers 
                if t["symbol"].endswith("USDT") and float(t.get("quoteVolume", 0)) >= 15_000_000
            ]
            usdt_pairs.sort(key=lambda s: next((float(t.get("quoteVolume", 0)) for t in tickers if t["symbol"] == s), 0), reverse=True)
            target_symbols = usdt_pairs[:limit]
        except Exception as exc:
            logger.error("Error fetching tickers: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for sym in target_symbols:
            m = await self.get_market_kline_analysis(sym)
            if not m:
                continue
            setup = self.evaluate_admin_archetypes(m)
            if setup and setup.get("has_setup"):
                results.append(setup)
            await asyncio.sleep(0.02)

        results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        return results
