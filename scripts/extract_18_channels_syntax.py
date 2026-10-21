import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import json
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
sources_cfg = config.sources or {}

channel_names = {}
for cid in allowed_chats:
    s = sources_cfg.get(cid) or sources_cfg.get(str(cid))
    channel_names[cid] = s.name if s else f"Channel {cid}"

# Fetch all messages in the 18 channels
messages = conn.execute(f"""
    SELECT chat_id, message_id, raw_text
    FROM messages
    WHERE chat_id IN ({','.join('?' for _ in allowed_chats)})
    ORDER BY telegram_timestamp DESC
""", allowed_chats).fetchall()

print(f"Total messages in allowed 18 channels: {len(messages)}")

# For each channel, find representative trading signal formats
# A trade signal usually has keywords like (LONG or SHORT or BUY or SELL) AND (ENTRY or TARGET or TP or STOP or SL)
channel_samples = defaultdict(list)
for m in messages:
    cid = m["chat_id"]
    text = m["raw_text"] or ""
    has_dir = bool(re.search(r"\b(LONG|SHORT|BUY|SELL)\b", text, re.IGNORECASE))
    has_trade_fields = bool(re.search(r"\b(ENTRY|TARGET|TP|STOP|SL|STOPLOSS|LEVERAGE)\b", text, re.IGNORECASE))
    if has_dir and has_trade_fields and len(text) < 1500:
        if len(channel_samples[cid]) < 8:
            channel_samples[cid].append({
                "mid": m["message_id"],
                "text": text
            })

print(f"Channels with detected trade signals: {len(channel_samples)} / {len(allowed_chats)}")

output_data = {}
for cid in allowed_chats:
    name = channel_names.get(cid, str(cid))
    samples = channel_samples[cid]
    output_data[cid] = {
        "channel_name": name,
        "sample_count": len(samples),
        "samples": samples
    }
    print(f"\n================ [{name}] (ID: {cid}) - Samples found: {len(samples)} ================")
    if samples:
        print(f"--- SAMPLE 1 (Msg #{samples[0]['mid']}) ---")
        print(samples[0]['text'][:300])
        if len(samples) > 1:
            print(f"--- SAMPLE 2 (Msg #{samples[1]['mid']}) ---")
            print(samples[1]['text'][:300])

with open("data/18_channels_admin_syntax_samples.json", "w", encoding="utf-8") as f:
    json.dump(output_data, f, ensure_ascii=False, indent=2)

print("\nSaved all samples to data/18_channels_admin_syntax_samples.json")
conn.close()

