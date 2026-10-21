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

# Let's inspect messages that have a coin pair and a direction, but parser fails or rejects
failed_patterns = defaultdict(list)

for cid in allowed_chats:
    name = channel_names.get(cid, str(cid))
    msgs = conn.execute("""
        SELECT message_id, raw_text
        FROM messages
        WHERE chat_id = ?
        ORDER BY telegram_timestamp DESC
    """, (cid,)).fetchall()
    
    for m in msgs:
        raw = m["raw_text"] or ""
        # Check if it looks like a real signal (not just VIP advertisement or target achieved)
        # Real signal usually has symbol/pair, direction, and some numbers
        if re.search(r"\b(?:Target Achieved|VIP Contact|join vip|HERE\s*🔥🔥)\b", raw, re.IGNORECASE):
            continue
        
        has_symbol = bool(re.search(r"(?:[A-Za-z0-9]{2,10}\/USDT|[A-Za-z0-9]{2,10}USDT)", raw, re.IGNORECASE))
        has_dir = bool(re.search(r"\b(LONG|SHORT|BUY|SELL)\b", raw, re.IGNORECASE))
        
        if not (has_symbol and has_dir):
            continue
            
        meta = SourceMetadata(chat_id=cid, message_id=m["message_id"], telegram_timestamp=now, received_at=now)
        parsed = parser.parse(raw, meta)
        
        # If it failed for specific reason
        if not parsed.take_profits:
            failed_patterns["NO_TP"].append((cid, name, m["message_id"], raw))
        elif not parsed.stop_loss:
            failed_patterns["NO_SL"].append((cid, name, m["message_id"], raw))
        elif not parsed.entries:
            failed_patterns["NO_ENTRY"].append((cid, name, m["message_id"], raw))
        elif parsed.stop_loss and parsed.entries:
            # Check logic anomaly like SL >= entry for long
            if parsed.side and "LONG" in str(parsed.side) and parsed.stop_loss >= min(parsed.entries):
                failed_patterns["LONG_SL_GTE_ENTRY"].append((cid, name, m["message_id"], parsed.stop_loss, parsed.entries, raw))
            elif parsed.side and "SHORT" in str(parsed.side) and parsed.stop_loss <= max(parsed.entries):
                failed_patterns["SHORT_SL_LTE_ENTRY"].append((cid, name, m["message_id"], parsed.stop_loss, parsed.entries, raw))

print("================ FAILED PATTERNS SUMMARY ================")
for k, v in failed_patterns.items():
    print(f"Pattern '{k}': {len(v)} occurrences")

print("\n================ SAMPLES OF NO_TP ================")
for cid, name, mid, raw in failed_patterns["NO_TP"][:8]:
    print(f"\n[{name}] Msg #{mid}:")
    print(raw[:350])

print("\n================ SAMPLES OF LONG_SL_GTE_ENTRY ================")
for cid, name, mid, sl, entries, raw in failed_patterns["LONG_SL_GTE_ENTRY"][:5]:
    print(f"\n[{name}] Msg #{mid}: SL={sl}, Entries={entries}")
    print(raw[:350])

print("\n================ SAMPLES OF NO_ENTRY ================")
for cid, name, mid, raw in failed_patterns["NO_ENTRY"][:5]:
    print(f"\n[{name}] Msg #{mid}:")
    print(raw[:350])

print("\n================ SAMPLES OF NO_SL ================")
for cid, name, mid, raw in failed_patterns["NO_SL"][:5]:
    print(f"\n[{name}] Msg #{mid}:")
    print(raw[:350])

conn.close()

