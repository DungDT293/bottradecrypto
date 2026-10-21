import asyncio
import sys
import os
from decimal import Decimal
sys.path.insert(0, ".")

from config.config import load_config
from core.enums import OrderSide, OrderType
from exchange.binance_client import BinanceFuturesClient

async def update_ena_sl():
    client = BinanceFuturesClient(load_config())
    
    # 1. Check existing algo orders
    algo_orders = await client.get_open_algo_orders("ENAUSDT")
    print(f"Found {len(algo_orders)} existing algo orders for ENAUSDT")
    
    old_algo_id = None
    for ao in algo_orders:
        if ao.get("orderType") == "STOP_MARKET":
            old_algo_id = ao.get("algoId")
            print(f"Cancelling old SL algo order {old_algo_id} (trigger: {ao.get('triggerPrice')})...")
            await client.cancel_algo_order(symbol="ENAUSDT", algo_id=str(old_algo_id))
            print("Cancelled successfully.")
            
    # 2. Place new Breakeven Stop Loss at 0.18850 (Entry was 0.18819)
    new_sl_price = Decimal("0.18850")
    print(f"Placing new Breakeven Stop Loss at {new_sl_price} (Quantity: 101, ReduceOnly: True)...")
    res = await client.create_algo_order(
        symbol="ENAUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        trigger_price=new_sl_price,
        quantity=Decimal("101"),
        reduce_only=True,
    )
    print("New Breakeven SL placed successfully!")
    print("New Algo Order details:", res)
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(update_ena_sl())
