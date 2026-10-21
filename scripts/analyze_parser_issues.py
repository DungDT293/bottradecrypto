import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import json
import re
from collections import defaultdict
from config.config import load_config
from parser.signal_parser import SignalParser
from core.models import SourceMetadata
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

db_p = r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db"
conn = sqlite3.connect(db_p)
conn.row_factory = sqlite3.Row

config = load_config("config.yaml")
allowed_chats = config.telegram.allowed_chat_ids or []
sources_cfg = config.sources or {}

channel_names = {}
for cid in allowed_chats:
    s = sources_cfg.get(cid) or sources_cfg.get(str(cid))
    channel_names[cid] = s.name if s else f"Channel {cid}"

parser = SignalParser()
now = datetime.now(timezone.utc)

# 1. Investigate remaining "Thieu Take Profit"
unrecovered_tp = []
rows = conn.execute("""
    SELECT s.signal_id, s.chat_id, s.message_id, s.symbol, s.side, s.state, s.blocking_reason, m.raw_text
    FROM signals s
    JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
    WHERE s.blocking_reason = 'Thieu Take Profit'
""").fetchall()

print(f"Total signals with 'Thieu Take Profit': {len(rows)}")
for r in rows:
    chat_id = r["chat_id"]
    if chat_id not in allowed_chats:
        continue
    raw = r["raw_text"] or ""
    meta = SourceMetadata(chat_id=chat_id, message_id=r["message_id"], telegram_timestamp=now, received_at=now)
    parsed = parser.parse(raw, meta)
    if not parsed.take_profits:
        unrecovered_tp.append((channel_names.get(chat_id, str(chat_id)), r["message_id"], raw))

print(f"Still unrecovered TP signals: {len(unrecovered_tp)}")
for ch_name, mid, raw in unrecovered_tp[:15]:
    print(f"\n================ [{ch_name}] Msg #{mid} ================")
    print(raw[:400])

# 2. Investigate ESTR SL (1)
print("\n================ ESTR SL = 1 SAMPLES ================")
estr_rows = conn.execute("""
    SELECT s.signal_id, s.message_id, s.blocking_reason, m.raw_text
    FROM signals s
    JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
    WHERE s.chat_id = -1001656921849 AND s.blocking_reason LIKE '%SL (1)%'
""").fetchall()
for r in estr_rows[:5]:
    print(f"\nMsg #{r['message_id']} Reason: {r['blocking_reason']}")
    print(r["raw_text"][:300])

# 3. Investigate "Khong co muc gia entry"
print("\n================ SAMPLES OF 'Khong co muc gia entry' ================")
entry_rej = conn.execute("""
    SELECT s.chat_id, s.message_id, s.symbol, m.raw_text
    FROM signals s
    JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
    WHERE s.blocking_reason = 'Khong co muc gia entry'
""").fetchall()
for r in entry_rej[:10]:
    ch = channel_names.get(r["chat_id"], str(r["chat_id"]))
    print(f"\n[{ch}] Msg #{r['message_id']} Symbol: {r['symbol']}")
    print(r["raw_text"][:250])

conn.close()

