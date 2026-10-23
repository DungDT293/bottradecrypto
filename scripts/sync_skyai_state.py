import sqlite3
import os

db_paths = [
    "data/trading_state.db",
    os.path.expandvars(r"%LOCALAPPDATA%\telegram-binance-signal-executor\data\trading_state.db"),
]

for db in db_paths:
    if os.path.exists(db):
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute("UPDATE signals SET state='OPEN_PROTECTED' WHERE signal_id='sig_-1002052872813_38113_0589fb'")
        conn.commit()
        conn.close()
        print(f"Updated SKYAI to OPEN_PROTECTED in {db}")

