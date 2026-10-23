import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath('.'))
import asyncio
from config.config import load_config
from exchange.binance_client import BinanceFuturesClient

async def check():
    cfg = load_config(os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml'))
    client = BinanceFuturesClient(config=cfg)
    symbols = ['ARIAUSDT', 'QUSDT', 'DOODUSDT', 'TRXUSDT', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ENAUSDT', 'ICNTUSDT', 'IOSTUSDT', 'DEXEUSDT', 'DOGEUSDT', 'JCTUSDT', 'APRUSDT']
    
    print('=== SCANNING ORDER HISTORY FOR CANDIDATE SYMBOLS ===')
    now = time.time()
    for sym in symbols:
        try:
            orders = await client._request('GET', '/fapi/v1/allOrders', params={'symbol': sym, 'limit': 10}, signed=True)
            for o in orders:
                t_ms = o.get('time', 0)
                # Check if created in last 6 hours
                if t_ms > (now - 6 * 3600) * 1000:
                    t = datetime.fromtimestamp(t_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                    print(f"MATCH: {sym} | ID: {o.get('orderId')} | Status: {o.get('status')} | Side: {o.get('side')} | Type: {o.get('type')} | Price: {o.get('price')} | Qty: {o.get('origQty')} | Time: {t} | ClientId: {o.get('clientOrderId')}")
        except Exception as e:
            pass
    await client.close()

if __name__ == '__main__':
    asyncio.run(check())

