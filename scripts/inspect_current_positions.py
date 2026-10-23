import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from exchange.binance_client import BinanceFuturesClient
from config.config import load_config

async def main():
    cfg = load_config()
    client = BinanceFuturesClient(cfg)
    
    # 1. Check positions
    positions = await client.get_open_positions()
    print("--- ACTIVE POSITIONS ON BINANCE ---")
    active = [p for p in (positions or []) if float(p.get("positionAmt", 0)) != 0]
    for p in active:
        print(f"Symbol: {p['symbol']} | Side: {'LONG' if float(p['positionAmt']) > 0 else 'SHORT'} | Amt: {p['positionAmt']} | Entry: {p['entryPrice']} | uPnL: {p['unRealizedProfit']}")
    if not active:
        print("None active.")

    # 2. Check AVAX price on Binance Futures
    url = f"{client.base_url}/fapi/v1/ticker/price?symbol=AVAXUSDT"
    async with (await client._get_session()).get(url) as resp:
        if resp.status == 200:
            data = await resp.json()
            print("\n--- AVAXUSDT TICKER ---")
            print("Current AVAX Price on Binance Futures:", data.get("price"))
        else:
            print("Failed to fetch AVAX price:", resp.status)

    # 3. Check 1h klines for AVAXUSDT
    url_k = f"{client.base_url}/fapi/v1/klines?symbol=AVAXUSDT&interval=1h&limit=5"
    async with (await client._get_session()).get(url_k) as resp_k:
        if resp_k.status == 200:
            klines = await resp_k.json()
            print("\nRecent 5 Candles (1h) for AVAXUSDT:")
            for k in klines:
                print(f"Open: {k[1]} | High: {k[2]} | Low: {k[3]} | Close: {k[4]}")

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
