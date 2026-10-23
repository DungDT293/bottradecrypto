import asyncio
import sys
import os
import yaml

sys.path.append('.')
from exchange.binance_client import BinanceFuturesClient
from config.config import AppConfig

async def check_all_algos():
    sys.stdout.reconfigure(encoding='utf-8')
    cfg = AppConfig.model_validate(yaml.safe_load(open(os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml'))))
    c = BinanceFuturesClient(cfg)
    try:
        await c.sync_time()
        algos = await c.get_open_algo_orders()
        print(f"=== TOTAL OPEN ALGO ORDERS: {len(algos)} ===")
        for a in algos:
            aid = a.get('algoId')
            sym = a.get('symbol')
            side = a.get('side')
            otype = a.get('orderType')
            tp = a.get('triggerPrice')
            cid = a.get('clientAlgoId')
            print(f"AlgoID: {aid} - Symbol: {sym} - Side: {side} - Type: {otype} - Trigger: {tp} - CID: {cid}")
    finally:
        await c.close()

asyncio.run(check_all_algos())
