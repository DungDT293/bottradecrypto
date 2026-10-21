import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath('.'))
from decimal import Decimal
from datetime import datetime, timezone

from config.config import load_config
from exchange.binance_client import BinanceFuturesClient
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from risk.risk_engine import RiskEngine
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from storage.database import DatabaseManager, SignalRepository, OrderRepository
from core.models import SourceMetadata

async def protect():
    cfg = load_config('config.yaml')
    db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
    db_mgr = DatabaseManager(db_path)
    sig_repo = SignalRepository(db_mgr)
    ord_repo = OrderRepository(db_mgr)
    client = BinanceFuturesClient(cfg)

    pos_mgr = PositionManager(client, ord_repo)
    risk_eng = RiskEngine(cfg)
    order_mgr = OrderManager(client, ord_repo, sig_repo, pos_mgr, risk_eng, cfg)

    pos = await client.get_position('XRPUSDT')
    amt = Decimal(str(pos.get('positionAmt', '0')))
    entry_p = Decimal(str(pos.get('entryPrice', '0')))
    print(f'Active XRP Position: {amt} @ {entry_p}')

    if amt != Decimal('0'):
        conn = db_mgr.get_connection()
        c = conn.cursor()
        c.execute("SELECT signal_id FROM signals WHERE symbol = 'XRPUSDT' ORDER BY created_at DESC LIMIT 1")
        sig_id = c.fetchone()[0]

        raw_text = """
💥 Futures (Free Signal)

✅ Long

#XRP/USDT

Entry zone : 1.2579 - 1.2969

Take Profits : 

1.3033
1.3420
1.3807
1.4194
1.4581

Stop loss :1.206117

Leverage: 10x
"""
        parser = SignalParser()
        validator = SignalValidator(cfg)
        meta = SourceMetadata(chat_id=-1001781413045, message_id=237193, source_name='Binance 360 VIP', telegram_timestamp=datetime.now(timezone.utc))
        parsed = parser.parse(raw_text, meta)
        parsed.signal_id = sig_id
        _, validated = validator.validate_and_resolve(parsed, cfg.sources.get(-1001781413045))
        validated.signal_id = sig_id

        print(f'Placing SL ({validated.stop_loss}) and TPs for {abs(amt)} XRP on Binance Futures...')
        orders = await order_mgr.on_entry_filled(validated, abs(amt), entry_p)
        print(f'Placed {len(orders)} protection orders on Binance:')
        for o in orders:
            print(f'  * {o.order_type} | Side: {o.side} | Trigger/Price: {o.price or o.trigger_price} | Qty: {o.quantity}')
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(protect())

