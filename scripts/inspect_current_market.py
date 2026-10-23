import asyncio
import sys
import json
sys.path.insert(0, '.')
from config.config import load_config
from exchange.binance_client import BinanceFuturesClient

async def check():
    cfg = load_config('config.yaml')
    client = BinanceFuturesClient(cfg)
    try:
        # Check BTWUSDT
        try:
            btw_ticker = await client._request('GET', '/fapi/v1/ticker/price', params={'symbol': 'BTWUSDT'})
            print('BTWUSDT Ticker:', btw_ticker)
            btw_klines = await client._request('GET', '/fapi/v1/klines', params={'symbol': 'BTWUSDT', 'interval': '15m', 'limit': 5})
            print('BTWUSDT Last 15m candle [Open, High, Low, Close]:', [btw_klines[-1][1], btw_klines[-1][2], btw_klines[-1][3], btw_klines[-1][4]])
        except Exception as e:
            print('BTWUSDT error:', e)
            
        # Check SKYAIUSDT
        try:
            sky_ticker = await client._request('GET', '/fapi/v1/ticker/price', params={'symbol': 'SKYAIUSDT'})
            print('SKYAIUSDT Ticker:', sky_ticker)
            sky_klines = await client._request('GET', '/fapi/v1/klines', params={'symbol': 'SKYAIUSDT', 'interval': '15m', 'limit': 5})
            print('SKYAIUSDT Last 15m candle [Open, High, Low, Close]:', [sky_klines[-1][1], sky_klines[-1][2], sky_klines[-1][3], sky_klines[-1][4]])
        except Exception as e:
            print('SKYAIUSDT error:', e)
            
        # Check open orders
        orders = await client._request('GET', '/fapi/v1/openOrders', signed=True)
        print(f'Open Orders ({len(orders)}):')
        for o in orders:
            print(f"  {o.get('symbol')}: {o.get('type')}, side={o.get('side')}, origQty={o.get('origQty')}, price={o.get('price')}, status={o.get('status')}")

        # Check open positions
        positions = await client.get_open_positions()
        print(f'Open Positions ({len(positions)}):')
        for p in positions:
            print(f"  {p.get('symbol')}: amt={p.get('positionAmt')}, entry={p.get('entryPrice')}, pnl={p.get('unRealizedProfit')}")

    finally:
        await client.close()

if __name__ == '__main__':
    asyncio.run(check())

