import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from datetime import datetime
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from core.models import SourceMetadata

with open(os.path.join(PROJECT_ROOT, "data", "extracted_channel_messages.json"), "r", encoding="utf-8") as f:
    msgs = json.load(f)

parser = SignalParser()
update_parser = ChannelUpdateParser()

missed = []
for m in msgs:
    text = m["raw_text"]
    u_type, _, _ = update_parser.parse_update(text)
    if u_type.value != "UNKNOWN":
        continue
    parsed = parser.parse(
        text,
        SourceMetadata(chat_id=m["chat_id"], message_id=m["message_id"], telegram_timestamp=datetime.utcnow()),
    )
    if not (parsed.symbol_candidate and parsed.side):
        # Look for potential signal patterns
        if re.search(r"\b(LONG|SHORT|BUY|SELL)\b", text, re.IGNORECASE) and re.search(r"\b(SL|STOP|ENTRY|TARGET|TP)\b", text, re.IGNORECASE):
            missed.append({
                "channel": m["channel_title"],
                "id": m["message_id"],
                "reason": parsed.blocking_reason,
                "warnings": parsed.warnings,
                "text": text,
            })

print(f"Total potential missed signals: {len(missed)}")
for idx, item in enumerate(missed[:10], 1):
    print("=" * 60)
    print(f"[{idx}] Channel: {item['channel']} | Msg ID: {item['id']}")
    print(f"Reason: {item['reason']} | Warnings: {item['warnings']}")
    print("-" * 60)
    print(item["text"][:500])

