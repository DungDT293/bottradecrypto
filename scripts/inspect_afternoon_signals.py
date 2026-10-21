import sqlite3
import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

db_path = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db')
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("PRAGMA table_info(messages)")
msg_cols = [r[1] for r in c.fetchall()]
print("Messages columns:", msg_cols)

# Query signals from 11:00 VN onwards (>= 04:00 UTC)
c.execute("""
    SELECT s.signal_id, s.chat_id, s.message_id, s.symbol, s.side, s.state, s.blocking_reason, s.created_at,
           m.raw_text, s.entries_json, s.stop_loss, s.take_profits_json, s.leverage
    FROM signals s
    LEFT JOIN messages m ON s.message_id = m.message_id AND s.chat_id = m.chat_id
    WHERE s.created_at >= '2026-10-20T04:00:00'
    ORDER BY s.created_at DESC
""")
rows = c.fetchall()
print(f"\nTotal signals since 11:00 AM (04:00 UTC): {len(rows)}\n")

for idx, r in enumerate(rows, 1):
    sig_id, chat_id, msg_id, sym, side, state, reason, created_at, raw_text, entries, sl, tps, lev = r
    print(f"--- [Signal #{idx}] {sym} ({side}) | State: {state} | Chat: {chat_id} | Created: {created_at} ---")
    print(f"  Reason: {reason}")
    print(f"  Entries: {entries} | SL: {sl} | TPs: {tps} | Lev: {lev}")
    print(f"  Raw Text:\n{raw_text}\n")

conn.close()

