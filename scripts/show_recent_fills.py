import asyncio
import sys
import os
sys.path.insert(0, '.')
from config.config import load_config
from exchange.binance_client import BinanceFuturesClient
from datetime import datetime

async def show_symbol_trades(symbol):
    cfg = load_config('config.yaml')
    client = BinanceFuturesClient(cfg)
    try:
        trades = await client._request('GET', '/fapi/v1/userTrades', params={'symbol': symbol, 'limit': 10}, signed=True)
        print(f"\n--- Recent Trades for {symbol} ---")
        for t in trades:
            t_str = datetime.fromtimestamp(t['time'] / 1000).strftime('%H:%M:%S %d/%m/%Y')
            print(f"  {t['symbol']} {t['side']} {t['qty']} @ {t['price']} | PnL: {t['realizedPnl']} | Fee: {t['commission']} | Time: {t_str}")
    finally:
        await client.close()

async def main():
    await show_symbol_trades('METISUSDT')
    await show_symbol_trades('WLDUSDT')
    await show_symbol_trades('CTRUSDT')
    await show_symbol_trades('XRPUSDT')

if __name__ == '__main__':
    asyncio.run(main())

