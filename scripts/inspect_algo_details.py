import asyncio
import sys
import os
import yaml

sys.path.append('.')
from exchange.binance_client import BinanceFuturesClient
from config.config import AppConfig

async def check_algo_details():
    sys.stdout.reconfigure(encoding='utf-8')
    cfg = AppConfig.model_validate(yaml.safe_load(open(os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml'))))
    c = BinanceFuturesClient(cfg)
    try:
        await c.sync_time()
        algos = await c.get_open_algo_orders()
        for a in algos:
            print(a)
    finally:
        await c.close()

asyncio.run(check_algo_details())
