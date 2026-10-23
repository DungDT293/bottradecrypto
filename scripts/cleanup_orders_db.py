import sqlite3
import os

paths = [
    'data/trading_state.db',
    os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db'),
    os.path.expandvars(r'%LOCALAPPDATA%\telegram-binance-signal-executor\data\trading_state.db')
]

for p in paths:
    if os.path.exists(p):
        conn = sqlite3.connect(p)
        c = conn.cursor()
        
        # 1. Update POLUSDT entry filled_quantity to 1212
        c.execute("UPDATE orders SET filled_quantity = '1212', status = 'FILLED' WHERE client_order_id = 'ent_sig_-10017_0_ceee'")
        
        # 2. Update POLUSDT signal leverage to 20 to match Binance
        c.execute("UPDATE signals SET leverage = 20 WHERE symbol = 'POLUSDT' AND state = 'OPEN_PROTECTED'")
        
        # 3. Clean up the 3 old phantom TP orders that were replaced
        c.execute("UPDATE orders SET status = 'CANCELED' WHERE client_order_id IN ('tp_sig_-100_1_7c16', 'tp_sig_-100_2_a290', 'tp_sig_-100_3_a5c0')")
        
        # 4. Clean up the old SL order (234 qty) that was replaced by 1212 qty
        c.execute("UPDATE orders SET status = 'CANCELED' WHERE client_order_id = 'sl_sig_-10017_efca'")
        
        # 5. Clean up any rejected unplaced TP orders (exchange_order_id is NULL)
        c.execute("UPDATE orders SET status = 'REJECTED' WHERE exchange_order_id IS NULL AND is_reduce_only = 1 AND client_order_id LIKE 'tp_%'")
        
        conn.commit()
        conn.close()
        print('Cleaned up DB:', p)
