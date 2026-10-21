import sqlite3
import os

dbs = [
    'data/trading_state.db',
    os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
]

for db in dbs:
    if os.path.exists(db):
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute(
            "UPDATE signals SET state = 'VALIDATED', blocking_reason = 'Da cap nhat quy tac: Khop truc tiep trong khoang Entry [1.2579 - 1.2969]' "
            "WHERE symbol = 'XRPUSDT' AND (blocking_reason LIKE '%Entry%' OR state = 'REJECTED')"
        )
        conn.commit()
        print(f"Updated {cur.rowcount} rows in {db}")
        conn.close()

