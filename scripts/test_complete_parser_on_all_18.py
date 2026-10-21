import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import json
import re
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from config.config import load_config
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

# Import current SignalParser
from parser.signal_parser import SignalParser
parser = SignalParser()
now = datetime.now(timezone.utc)

# Track stats per channel
channel_stats = defaultdict(lambda: {
    "total_messages": 0,
    "candidate_signals": 0,
    "parsed_success": 0,
    "rejected": 0,
    "rejection_reasons": defaultdict(int)
})

# Scan every message in the 18 channels
rows = conn.execute(f"""
    SELECT chat_id, message_id, raw_text
    FROM messages
    WHERE chat_id IN ({','.join('?' for _ in allowed_chats)})
    ORDER BY telegram_timestamp DESC
""", allowed_chats).fetchall()

print(f"Testing current parser on all {len(rows)} messages in 18 channels...")

for r in rows:
    cid = r["chat_id"]
    text = r["raw_text"] or ""
    stats = channel_stats[cid]
    stats["total_messages"] += 1
    
    # Filter for trade signal candidates
    has_dir = bool(re.search(r"\b(LONG|SHORT|BUY|SELL)\b", text, re.IGNORECASE))
    has_usdt = bool(re.search(r"(?:[A-Za-z0-9]{2,10}\/USDT|[A-Za-z0-9]{2,10}USDT)", text, re.IGNORECASE))
    if not (has_dir and has_usdt):
        continue
        
    stats["candidate_signals"] += 1
    meta = SourceMetadata(chat_id=cid, message_id=r["message_id"], telegram_timestamp=now, received_at=now)
    parsed = parser.parse(text, meta)
    
    if parsed.validation_status in ["PARSED", "NEEDS_POLICY"]:
        stats["parsed_success"] += 1
    else:
        stats["rejected"] += 1
        stats["rejection_reasons"][parsed.blocking_reason or "Unknown"] += 1

print("\n================ CURRENT PARSER BENCHMARK ================")
total_candidates = sum(s["candidate_signals"] for s in channel_stats.values())
total_success = sum(s["parsed_success"] for s in channel_stats.values())
print(f"Total Trade Signal Candidates across 18 channels: {total_candidates}")
print(f"Successfully Parsed: {total_success} ({(total_success/total_candidates*100) if total_candidates else 0:.1f}%)")

for cid in allowed_chats:
    name = channel_names.get(cid, str(cid))
    s = channel_stats[cid]
    print(f"\n[{name}] (ID: {cid})")
    print(f"   Msgs: {s['total_messages']} | Candidates: {s['candidate_signals']} | Success: {s['parsed_success']} | Rej: {s['rejected']}")
    if s["rejection_reasons"]:
        top_reasons = sorted(s["rejection_reasons"].items(), key=lambda x: x[1], reverse=True)[:3]
        for r_name, cnt in top_reasons:
            print(f"      - {r_name}: {cnt}")

conn.close()

