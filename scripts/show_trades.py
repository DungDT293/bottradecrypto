import asyncio
import sys
import os
sys.path.insert(0, '.')
from config.config import load_config
from exchange.binance_client import BinanceFuturesClient
from datetime import datetime

async def show_trades():
    cfg = load_config('config.yaml')
    client = BinanceFuturesClient(cfg)
    trades = await client._request('GET', '/fapi/v1/userTrades', params={'limit': 25}, signed=True)
    print("Recent 25 Binance Trades:")
    for t in trades:
        t_str = datetime.fromtimestamp(t['time'] / 1000).strftime('%H:%M:%S %d/%m')
        print(f"  {t['symbol']} {t['side']} {t['qty']} @ {t['price']} | PnL: {t['realizedPnl']} | Fee: {t['commission']} | Time: {t_str}")
    await client.close()

if __name__ == '__main__':
    asyncio.run(show_trades())

