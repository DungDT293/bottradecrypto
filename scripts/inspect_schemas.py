import sqlite3

db_app = r'C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db'
conn = sqlite3.connect(db_app)
conn.row_factory = sqlite3.Row

for table in ['orders', 'app_alerts', 'signals']:
    cols = [r['name'] for r in conn.execute(f"PRAGMA table_info({table})")]
    print(f"Schema for {table}: {cols}")

conn.close()

