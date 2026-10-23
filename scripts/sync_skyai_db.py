import sqlite3
import os
import datetime

db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

sig_id = 'sig_-1002052872813_38113_7144d0'
now_str = datetime.datetime.utcnow().isoformat()

c.execute(
    "UPDATE signals SET state = 'ENTRY_PENDING', blocking_reason = NULL, entries_json = '[\"0.0337600\"]', updated_at = ? WHERE signal_id = ?",
    (now_str, sig_id)
)

c.execute(
    """
    INSERT OR REPLACE INTO orders (
        client_order_id, exchange_order_id, signal_id, symbol, side, order_type,
        price, trigger_price, quantity, filled_quantity, is_reduce_only, is_algo, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, '0', 0, 0, 'NEW', ?, ?)
    """,
    ('ent_sig_-10020_0_a9c4', '2764611259', sig_id, 'SKYAIUSDT', 'BUY', 'LIMIT', '0.0337600', '1071', now_str, now_str)
)

c.execute(
    """
    INSERT INTO signal_timeline (signal_id, timestamp, event_type, description, payload_json)
    VALUES (?, ?, 'ORDERS_SUBMITTED', 'Da dat lenh Limit Buy 1071 SKYAI @ 0.03376 tren Binance Live', '{}')
    """,
    (sig_id, now_str)
)

conn.commit()
print('Successfully synced SKYAIUSDT into trading_state.db!')

