import sqlite3

db_app = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db'
conn = sqlite3.connect(db_app)
conn.row_factory = sqlite3.Row

print("=== Sample orders ===")
for r in conn.execute("SELECT client_order_id, symbol, side, order_type, status, created_at FROM orders ORDER BY created_at DESC LIMIT 5"):
    print(dict(r))

print("=== App alerts ===")
for r in conn.execute("SELECT * FROM app_alerts"):
    print(dict(r))

conn.close()

