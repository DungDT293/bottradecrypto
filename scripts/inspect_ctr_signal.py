import sqlite3
import os

db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("SELECT created_at, updated_at FROM signals WHERE symbol='CTRUSDT' ORDER BY created_at DESC LIMIT 1")
print("CTR time:", c.fetchone())
conn.close()
