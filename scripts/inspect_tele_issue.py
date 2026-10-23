import sqlite3, os, sys
from datetime import datetime

def safe_print(s):
    sys.stdout.buffer.write((str(s) + "\n").encode("utf-8", errors="replace"))

paths = [
    'data/trading_state.db',
    os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\trading_state.db'),
    os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\trading_state.db')
]

for db_path in paths:
    if not os.path.exists(db_path):
        continue
    safe_print(f"=== DB: {db_path} ===")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        msgs = conn.execute("SELECT chat_id, message_id, telegram_timestamp, received_at, raw_text FROM messages ORDER BY telegram_timestamp DESC LIMIT 10").fetchall()
        safe_print("LATEST 10 MESSAGES:")
        for m in msgs:
            text_preview = (m["raw_text"] or "").replace("\n", " ")[:140]
            safe_print(f"  Chat: {m['chat_id']} | MsgID: {m['message_id']} | Time: {m['telegram_timestamp']} | Text: {text_preview}")

        sigs = conn.execute("SELECT signal_id, chat_id, message_id, symbol, side, state, blocking_reason, created_at FROM signals ORDER BY created_at DESC LIMIT 10").fetchall()
        safe_print("LATEST 10 SIGNALS:")
        for s in sigs:
            safe_print(f"  SigID: {s['signal_id']} | Sym: {s['symbol']} | Side: {s['side']} | State: {s['state']} | Reason: {s['blocking_reason']} | Time: {s['created_at']}")

        alerts = conn.execute("SELECT level, title, message, timestamp FROM app_alerts ORDER BY timestamp DESC LIMIT 10").fetchall()
        safe_print("LATEST 10 ALERTS:")
        for a in alerts:
            safe_print(f"  [{a['level']}] {a['title']}: {a['message']} ({a['timestamp']})")
    except Exception as e:
        safe_print(f"Error reading db: {e}")
    finally:
        conn.close()
