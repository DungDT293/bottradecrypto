import sqlite3
import os
import sys
import json

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

db_path = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\data\trading_state.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

start_iso = "2026-10-20T17:00:00"

c.execute("""
    SELECT m.*, s.signal_id, s.symbol, s.side, s.state, s.blocking_reason, s.leverage, s.entries_json, s.stop_loss, s.take_profits_json
    FROM messages m
    LEFT JOIN signals s ON m.chat_id = s.chat_id AND m.message_id = s.message_id
    WHERE m.received_at >= ? OR m.telegram_timestamp >= ?
    ORDER BY m.received_at ASC
""", (start_iso, start_iso))

rows = c.fetchall()
print(f"Total Telegram messages received since 00:00 21/10: {len(rows)}\n")

for i, r in enumerate(rows, 1):
    d = dict(r)
    print(f"================================================================================")
    print(f"#{i} | Received: {d['received_at']} (Telegram: {d['telegram_timestamp']})")
    print(f"Chat ID: {d['chat_id']} | Msg ID: #{d['message_id']}")
    print(f"Signal ID: {d['signal_id']} | State: {d['state']}")
    if d['blocking_reason']:
        print(f"Reason: {d['blocking_reason']}")
    if d['symbol']:
        print(f"Parsed: {d['symbol']} {d['side']} {d['leverage']}x | SL: {d['stop_loss']} | Entries: {d['entries_json']} | TPs: {d['take_profits_json']}")
    print(f"--- RAW TEXT ---")
    print(d['raw_text'])
    print()
