import asyncio
import os
import yaml
import sys

sys.path.append('.')
from exchange.binance_client import BinanceFuturesClient
from config.config import AppConfig

async def test_classification():
    sys.stdout.reconfigure(encoding='utf-8')
    cfg = AppConfig.model_validate(yaml.safe_load(open(os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml'))))
    c = BinanceFuturesClient(cfg)
    try:
        await c.sync_time()
        algos = await c.get_open_algo_orders('LDOUSDT')
        orders = await c.get_open_orders('LDOUSDT')
        all_orders = []
        for o in orders:
            all_orders.append(o)
        for a in algos:
            all_orders.append({
                'orderId': a.get('algoId'),
                'clientOrderId': a.get('clientAlgoId', ''),
                'symbol': a.get('symbol'),
                'type': f"{a.get('orderType', 'STOP_MARKET')} (ALGO)",
                'reduceOnly': a.get('reduceOnly', True),
                'is_algo': True
            })
        
        live_sl = None
        live_tps = []
        for bo in all_orders:
            o_type = str(bo.get('type', '')).upper()
            cid = str(bo.get('clientOrderId', ''))
            oid = str(bo.get('orderId', ''))
            
            is_sl = 'STOP' in o_type or cid.startswith('sl_') or cid.startswith('be_') or cid.startswith('trail_')
            is_tp = 'TAKE_PROFIT' in o_type or cid.startswith('tp_') or (bo.get('reduceOnly') and not is_sl and ('LIMIT' in o_type or 'TAKE_PROFIT' in o_type))
            
            if is_sl:
                live_sl = cid or oid
            elif is_tp:
                live_tps.append(cid or oid)

        print("Result for LDOUSDT:")
        print("Live SL:", live_sl)
        print("Live TPs:", live_tps)
        print(f"Count: {len(live_tps)} lệnh TP")
    finally:
        await c.close()

asyncio.run(test_classification())

