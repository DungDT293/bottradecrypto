import asyncio
import os
import sys
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.binance_client import BinanceFuturesClient
from config.config import load_config

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

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return highs[-1] - lows[-1] if highs and lows else 0.0
    tr_list = []
    for i in range(1, len(closes)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i-1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)
    return sum(tr_list[-period:]) / period

async def test_scanner():
    cfg = load_config()
    client = BinanceFuturesClient(cfg)
    symbols = ["SOLUSDT", "ETHUSDT", "BTCUSDT"]
    
    print("=== TESTING QUANT SCANNER ===")
    for sym in symbols:
        url = f"{client.base_url}/fapi/v1/klines?symbol={sym}&interval=1h&limit=50"
        async with (await client._get_session()).get(url) as resp:
            data = await resp.json()
            closes = [float(k[4]) for k in data]
            highs = [float(k[2]) for k in data]
            lows = [float(k[3]) for k in data]
            
            cur_p = closes[-1]
            ema20 = calculate_ema(closes, 20)
            ema50 = calculate_ema(closes, 50)
            rsi = calculate_rsi(closes, 14)
            atr = calculate_atr(highs, lows, closes, 14)
            
            trend = "BULLISH" if cur_p > ema20 > ema50 else ("BEARISH" if cur_p < ema20 < ema50 else "SIDEWAY")
            print(f"{sym}: Px={cur_p} | Trend={trend} | EMA20={ema20:.2f} | EMA50={ema50:.2f} | RSI={rsi:.1f} | ATR={atr:.2f}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(test_scanner())
