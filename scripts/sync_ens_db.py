import sqlite3
import os

db = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db)
c = conn.cursor()

sig_id = 'sig_-1001552004524_76497_77b66b'
c.execute("UPDATE signals SET state = 'OPEN_PROTECTED', blocking_reason = NULL WHERE signal_id = ?", (sig_id,))

orders = [
    ('man_ens_ent_5815', sig_id, 'ENSUSDT', 'SELL', 'LIMIT', '5.815', '15.8', None, 0, 0, '12266678712', 'FILLED', '15.8', '5.815', '2026-10-21T13:50:00', '2026-10-21T13:53:20'),
    ('man_ens_sl_5919', sig_id, 'ENSUSDT', 'BUY', 'STOP_MARKET', None, '15.8', '5.919', 1, 1, '1000002634934929', 'NEW', '0', None, '2026-10-21T13:50:00', '2026-10-21T13:50:00'),
    ('man_ens_tp1_5732', sig_id, 'ENSUSDT', 'BUY', 'LIMIT', '5.732', '5.5', None, 1, 0, '12266686251', 'NEW', '0', None, '2026-10-21T13:53:30', '2026-10-21T13:53:30'),
    ('man_ens_tp2_5661', sig_id, 'ENSUSDT', 'BUY', 'LIMIT', '5.661', '5.5', None, 1, 0, '12266686252', 'NEW', '0', None, '2026-10-21T13:53:30', '2026-10-21T13:53:30'),
    ('man_ens_tp3_5580', sig_id, 'ENSUSDT', 'BUY', 'LIMIT', '5.580', '4.8', None, 1, 0, '12266686253', 'NEW', '0', None, '2026-10-21T13:53:30', '2026-10-21T13:53:30')
]

for o in orders:
    c.execute("INSERT OR REPLACE INTO orders (client_order_id, signal_id, symbol, side, order_type, price, quantity, trigger_price, is_reduce_only, is_algo, exchange_order_id, status, filled_quantity, avg_fill_price, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", o)

c.execute("INSERT OR REPLACE INTO positions (symbol, side, quantity, entry_price, leverage, margin_mode, active_signal_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
    ('ENSUSDT', 'SHORT', '15.8', '5.815', 15, 'CROSSED', sig_id, '2026-10-21T13:53:20'))

c.execute("INSERT INTO signal_timeline (signal_id, timestamp, event_type, description) VALUES (?, datetime('now'), 'ORDER_FILLED', 'Khớp lệnh Entry SHORT 15.8 ENS tại 5.815. Đã kích hoạt Algo SL và 3 lệnh TP')", (sig_id,))

conn.commit()
conn.close()
print("Successfully synced ENS trade into App database!")
