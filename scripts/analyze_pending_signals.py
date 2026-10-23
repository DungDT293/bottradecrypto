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
        # Check 24hr stats for BTWUSDT
        btw_24h = await client._request('GET', '/fapi/v1/ticker/24hr', params={'symbol': 'BTWUSDT'})
        print('=== BTWUSDT 24hr ===')
        print(f"Price: {btw_24h.get('lastPrice')}, High: {btw_24h.get('highPrice')}, Low: {btw_24h.get('lowPrice')}, Vol: {btw_24h.get('volume')} BTW, QuoteVol: {float(btw_24h.get('quoteVolume', 0))/1e6:.2f}M USDT")
        
        # Check BTW order book top
        btw_depth = await client._request('GET', '/fapi/v1/depth', params={'symbol': 'BTWUSDT', 'limit': 5})
        print(f"Bids: {btw_depth['bids'][:3]}")
        print(f"Asks: {btw_depth['asks'][:3]}")

        # Check 24hr stats for SKYAIUSDT
        sky_24h = await client._request('GET', '/fapi/v1/ticker/24hr', params={'symbol': 'SKYAIUSDT'})
        print('=== SKYAIUSDT 24hr ===')
        print(f"Price: {sky_24h.get('lastPrice')}, High: {sky_24h.get('highPrice')}, Low: {sky_24h.get('lowPrice')}, Vol: {sky_24h.get('volume')} SKYAI, QuoteVol: {float(sky_24h.get('quoteVolume', 0))/1e6:.2f}M USDT")
        
        # Check SKYAI order book top
        sky_depth = await client._request('GET', '/fapi/v1/depth', params={'symbol': 'SKYAIUSDT', 'limit': 5})
        print(f"Bids: {sky_depth['bids'][:3]}")
        print(f"Asks: {sky_depth['asks'][:3]}")

        # Check account equity and available balance
        acc = await client._request('GET', '/fapi/v2/account', signed=True)
        print(f"=== ACCOUNT BALANCE ===")
        print(f"Total Wallet: {acc.get('totalWalletBalance')} USDT")
        print(f"Available Balance: {acc.get('availableBalance')} USDT")

    finally:
        await client.close()

if __name__ == '__main__':
    asyncio.run(check())

