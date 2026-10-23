import asyncio
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config.config import load_config
from exchange.binance_client import BinanceFuturesClient

async def pre_check():
    cfg = load_config()
    client = BinanceFuturesClient(cfg)
    
    print("Testing connection to Binance...")
    await client.sync_time()
    equity = await client.get_account_equity()
    print(f"Current Account Equity: {equity} USDT")
    
    positions = await client.get_open_positions()
    print(f"Currently Open Positions: {len(positions)}")
    for p in positions:
        print(f"  {p['symbol']}: Amt={p['positionAmt']}, Entry={p['entryPrice']}")
        
    stx_pos = next((p for p in positions if p['symbol'] == 'STXUSDT'), None)
    if stx_pos and float(stx_pos.get('positionAmt', 0)) != 0:
        print("WARNING: STXUSDT already has an open position!")
        await client.close()
        return False
        
    filter_info = await client.get_symbol_filter("STXUSDT")
    print(f"STX Symbol Filter: min_qty={filter_info.min_qty}, step_size={filter_info.step_size}, min_notional={filter_info.min_notional}, tick_size={filter_info.tick_size}")
    
    await client.close()
    return True

if __name__ == "__main__":
    ok = asyncio.run(pre_check())
    print("Pre-check result:", "OK" if ok else "ABORT")

