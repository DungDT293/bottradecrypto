import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import re
from collections import defaultdict
from config.config import load_config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

db_p = r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db"
conn = sqlite3.connect(db_p)
conn.row_factory = sqlite3.Row

config = load_config("config.yaml")
allowed_chats = config.telegram.allowed_chat_ids or []

# Let's inspect other channels
for cid in allowed_chats:
    rows = conn.execute("""
        SELECT m.message_id, m.raw_text, s.symbol, s.side, s.state, s.blocking_reason
        FROM messages m
        LEFT JOIN signals s ON m.chat_id = s.chat_id AND m.message_id = s.message_id
        WHERE m.chat_id = ? AND m.raw_text LIKE '%USDT%'
        ORDER BY m.telegram_timestamp DESC
        LIMIT 30
    """, (cid,)).fetchall()
    
    print(f"\n================ CHAT {cid} (Found {len(rows)} USDT msgs) ================")
    for r in rows[:3]:
        print(f"Msg #{r['message_id']} | Status: {r['state']} | Reason: {r['blocking_reason']}")
        print((r['raw_text'] or '')[:200])

conn.close()

