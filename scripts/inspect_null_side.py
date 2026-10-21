import sqlite3
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

db = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("""
    SELECT signal_id, symbol, blocking_reason, created_at 
    FROM signals 
    WHERE created_at LIKE '2026-10-20%' AND side IS NULL
""")
rows = cur.fetchall()
print(f"Total side IS NULL today: {len(rows)}")
for r in rows[:10]:
    print(f"ID: {r[0]} | Symbol: {r[1]} | Reason: {r[2]} | At: {r[3]}")

conn.close()

