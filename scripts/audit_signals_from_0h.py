import sqlite3
import os
import sys
import json
import datetime
import urllib.request
import hmac
import hashlib
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

db_path = os.path.expandvars(r"%APPDATA%\telegram_binance_signal_executor\data\trading_state.db")
print(f"Auditing DB: {db_path}\n")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"Tables in DB: {tables}\n")

# Start time: 00:00:00 2026-10-21 Vietnam time = 2026-10-20 17:00:00 UTC
# Let's search from 2026-10-20T17:00:00 to now
start_iso = "2026-10-20T17:00:00"

print("================================================================================")
print("1. TELEGRAM MESSAGES SINCE 00:00 (21/10 VN TIME)")
print("================================================================================")
if "telegram_messages" in tables:
    c.execute("""
        SELECT * FROM telegram_messages 
        WHERE timestamp >= ? OR created_at >= ?
        ORDER BY timestamp ASC
    """, (start_iso, start_iso))
    messages = c.fetchall()
    print(f"Total Telegram messages received: {len(messages)}")
    for m in messages:
        d = dict(m)
        raw_text_snip = (d.get("raw_text") or "").replace("\n", " ")[:120]
        print(f"[{d.get('timestamp') or d.get('created_at')}] ID: {d.get('message_id')} | Chat: {d.get('chat_id')} ({d.get('channel_title') or 'N/A'}) | Parsed: {bool(d.get('is_signal'))} | Text: {raw_text_snip}")
else:
    print("No telegram_messages table found.")

print("\n================================================================================")
print("2. SIGNALS RECORDED SINCE 00:00 (21/10 VN TIME)")
print("================================================================================")
c.execute("""
    SELECT * FROM signals 
    WHERE created_at >= ? OR updated_at >= ?
    ORDER BY created_at ASC
""", (start_iso, start_iso))
signals = c.fetchall()
print(f"Total Signals: {len(signals)}")
for s in signals:
    d = dict(s)
    print(f"\n--- Signal ID: {d.get('signal_id')} ---")
    print(f"  Time: {d.get('created_at')} | Chat: {d.get('chat_id')} | Msg #{d.get('message_id')}")
    print(f"  Symbol: {d.get('symbol')} | Direction: {d.get('direction')} | Leverage: {d.get('leverage')}x")
    print(f"  State: {d.get('state')} | Reason: {d.get('blocking_reason')}")
    print(f"  Entries: {d.get('entries_json')} | SL: {d.get('stop_loss')} | TPs: {d.get('take_profits_json')}")

print("\n================================================================================")
print("3. ORDERS GENERATED SINCE 00:00 (21/10 VN TIME)")
print("================================================================================")
c.execute("""
    SELECT * FROM orders 
    WHERE created_at >= ? OR updated_at >= ?
    ORDER BY created_at ASC
""", (start_iso, start_iso))
orders = c.fetchall()
print(f"Total Orders: {len(orders)}")
for o in orders:
    d = dict(o)
    print(f"  [{d.get('created_at')}] CID: {d.get('client_order_id')} | Sig: {d.get('signal_id')} | Sym: {d.get('symbol')} | Side: {d.get('side')} | Type: {d.get('order_type')} | Px: {d.get('price')} | StopPx: {d.get('trigger_price')} | Qty: {d.get('quantity')} | Status: {d.get('status')} | FilledQty: {d.get('filled_quantity')} | AvgPx: {d.get('avg_fill_price')}")

print("\n================================================================================")
print("4. TIMELINE EVENTS SINCE 00:00 (21/10 VN TIME)")
print("================================================================================")
c.execute("""
    SELECT * FROM signal_timeline 
    WHERE timestamp >= ?
    ORDER BY id ASC
""", (start_iso,))
events = c.fetchall()
print(f"Total Events: {len(events)}")
for e in events:
    d = dict(e)
    print(f"  [{d.get('timestamp')}] Sig: {d.get('signal_id')} | Event: {d.get('event_type')} | Desc: {d.get('description')}")

