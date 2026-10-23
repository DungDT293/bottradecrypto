import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

print('=== TODAY SIGNALS ===')
c.execute("SELECT signal_id, symbol, side, state, entries_json, stop_loss, take_profits_json, leverage, created_at FROM signals WHERE created_at LIKE '2026-10-22%' ORDER BY created_at DESC")
for r in c.fetchall():
    print(r)

print('\n=== TODAY ORDERS FOR DASH ===')
c.execute("SELECT client_order_id, symbol, side, order_type, price, trigger_price, quantity, status, filled_quantity, avg_fill_price, created_at FROM orders WHERE symbol LIKE '%DASH%' AND created_at LIKE '2026-10-22%' ORDER BY created_at ASC")
for r in c.fetchall():
    print(r)

print('\n=== ALL ORDERS WITH DASH ===')
c.execute("SELECT client_order_id, signal_id, symbol, side, order_type, price, trigger_price, quantity, status, filled_quantity, avg_fill_price, created_at FROM orders WHERE symbol LIKE '%DASH%' ORDER BY created_at DESC LIMIT 20")
for r in c.fetchall():
    print(r)

