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

print(f"Loaded {len(allowed_chats)} allowed channels.")

# 1. Check all signals with blocking reasons
rejections_by_reason = defaultdict(lambda: defaultdict(list))
rejections_by_channel = defaultdict(lambda: defaultdict(int))

rows = conn.execute("""
    SELECT s.signal_id, s.chat_id, s.message_id, s.symbol, s.side, s.state, s.blocking_reason, m.raw_text
    FROM signals s
    LEFT JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
    WHERE s.state = 'REJECTED'
""").fetchall()

print(f"Total REJECTED signals in DB: {len(rows)}")

parser = SignalParser()
recovered_signals = []

for r in rows:
    chat_id = r["chat_id"]
    if chat_id not in allowed_chats:
        continue
    reason = r["blocking_reason"] or "Unknown"
    rejections_by_channel[chat_id][reason] += 1
    
    raw = r["raw_text"] or ""
    # Test if current parser parses it
    if raw:
        now = datetime.now(timezone.utc)
        meta = SourceMetadata(chat_id=chat_id, message_id=r["message_id"], telegram_timestamp=now, received_at=now)
        parsed = parser.parse(raw, meta)
        if parsed.take_profits and reason == "Thieu Take Profit":
            recovered_signals.append({
                "chat_id": chat_id,
                "channel": channel_names.get(chat_id, str(chat_id)),
                "message_id": r["message_id"],
                "symbol": parsed.symbol_candidate,
                "old_reason": reason,
                "new_tps": [str(x) for x in parsed.take_profits],
                "new_status": str(parsed.validation_status),
                "raw_preview": raw[:200]
            })

print("\n================ REJECTION BREAKDOWN BY CHANNEL ================")
for cid in allowed_chats:
    name = channel_names.get(cid, str(cid))
    reasons = rejections_by_channel[cid]
    total_rej = sum(reasons.values())
    print(f"\n[{name}] (ID: {cid}) - Total Rejections: {total_rej}")
    for r_reason, cnt in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"   - {r_reason}: {cnt}")

print("\n================ SIGNALS ALREADY RECOVERED BY CURRENT PARSER ================")
print(f"Recovered count: {len(recovered_signals)}")
for item in recovered_signals[:10]:
    print(f"[{item['channel']}] Msg #{item['message_id']} {item['symbol']} -> TPs: {item['new_tps']} Status: {item['new_status']}")

conn.close()
