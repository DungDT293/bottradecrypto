import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import yaml
import uuid
import sqlite3
from decimal import Decimal
from exchange.binance_client import BinanceFuturesClient
from config.config import AppConfig
from core.enums import OrderSide, OrderType

async def main():
    p = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml')
    with open(p, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    cfg = AppConfig(**data)
    client = BinanceFuturesClient(cfg)
    
    cid_tp2 = f"tp_sig_-100_2_{uuid.uuid4().hex[:4]}"
    r2 = await client.create_standard_order(
        symbol='POLUSDT',
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal('485'),
        price=Decimal('0.09234'),
        client_order_id=cid_tp2,
        reduce_only=True
    )
    print('TP2 PLACED SUCCESS:', r2.get('orderId'))

    cid_tp3 = f"tp_sig_-100_3_{uuid.uuid4().hex[:4]}"
    r3 = await client.create_standard_order(
        symbol='POLUSDT',
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal('485'),
        price=Decimal('0.09333'),
        client_order_id=cid_tp3,
        reduce_only=True
    )
    print('TP3 PLACED SUCCESS:', r3.get('orderId'))

    # Save to active DB
    db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR REPLACE INTO orders (
            client_order_id, signal_id, symbol, side, order_type, price, quantity,
            is_reduce_only, is_algo, exchange_order_id, status, filled_quantity, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (cid_tp2, 'sig_-1001756316676_79137_ed6404', 'POLUSDT', 'SELL', 'LIMIT', '0.0923400', '485', 1, 0, str(r2.get('orderId')), 'NEW', '0')
    )
    c.execute(
        """
        INSERT OR REPLACE INTO orders (
            client_order_id, signal_id, symbol, side, order_type, price, quantity,
            is_reduce_only, is_algo, exchange_order_id, status, filled_quantity, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (cid_tp3, 'sig_-1001756316676_79137_ed6404', 'POLUSDT', 'SELL', 'LIMIT', '0.0933300', '485', 1, 0, str(r3.get('orderId')), 'NEW', '0')
    )
    conn.commit()
    conn.close()
    print('Saved both TP2 and TP3 to database successfully!')

    await client.close()

if __name__ == '__main__':
    asyncio.run(main())
