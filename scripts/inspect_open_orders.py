import asyncio
import sys
import os
import yaml

sys.path.append('.')
from exchange.binance_client import BinanceFuturesClient
from config.config import AppConfig

async def check_all_orders():
    sys.stdout.reconfigure(encoding='utf-8')
    cfg = AppConfig.model_validate(yaml.safe_load(open(os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml'))))
    c = BinanceFuturesClient(cfg)
    try:
        await c.sync_time()
        orders = await c.get_open_orders()
        print(f"=== TOTAL OPEN STANDARD ORDERS: {len(orders)} ===")
        for o in orders:
            oid = o.get('orderId')
            sym = o.get('symbol')
            side = o.get('side')
            otype = o.get('type')
            px = o.get('price')
            qty = o.get('origQty')
            ro = o.get('reduceOnly')
            cid = o.get('clientOrderId')
            print(f"ID: {oid} - Symbol: {sym} - Side: {side} - Type: {otype} - Price: {px} - Qty: {qty} - RO: {ro} - CID: {cid}")
    finally:
        await c.close()

asyncio.run(check_all_orders())
