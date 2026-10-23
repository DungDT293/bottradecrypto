import asyncio
import os
import sys
import yaml
from datetime import datetime

sys.path.append('.')
from exchange.binance_client import BinanceFuturesClient
from config.config import AppConfig

async def main():
    sys.stdout.reconfigure(encoding='utf-8')
    config_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    config = AppConfig.model_validate(data)
    client = BinanceFuturesClient(config)
    try:
        await client.sync_time()
        print("=== LIVE INCOME / REALIZED PNL HISTORY (LAST 25) ===")
        incomes = await client.get_income_history(limit=35)
        for inc in incomes:
            ts = inc.get('time', 0)
            dt = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
            itype = inc.get('incomeType', '')
            if itype in ('REALIZED_PNL', 'COMMISSION', 'FUNDING_FEE'):
                print(f"{dt} | {inc.get('symbol', 'N/A'):<10} | {itype:<13} | Amount: {float(inc.get('income', 0)):+.4f} {inc.get('asset')}")

        print("\n=== LIVE OPEN POSITIONS ===")
        positions = await client.get_open_positions()
        for p in positions:
            amt = float(p.get('positionAmt', 0))
            if amt != 0:
                print(f"{p.get('symbol'):<10} | Amt: {amt:<8} | Entry: {p.get('entryPrice'):<10} | Mark: {p.get('markPrice'):<10} | uPnL: {float(p.get('unRealizedProfit', 0)):+.4f} | Lev: {p.get('leverage')}x | Margin: {float(p.get('initialMargin', 0)):.4f}")
    finally:
        await client.close()

asyncio.run(main())
