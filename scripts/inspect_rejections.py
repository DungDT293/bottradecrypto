import json
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.config import load_config
from core.models import SourceMetadata
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator

cfg = load_config()
sig_parser = SignalParser()
validator = SignalValidator(cfg)

conn = sqlite3.connect("data/trading_state.db")
c = conn.cursor()

channels_to_check = [
    ("THE WOLF", -1002007658025),
    ("THE MASTER", -1002266035358),
    ("ESTR", -1001656921849),
]

for name, cid in channels_to_check:
    c.execute("SELECT message_id, raw_text, telegram_timestamp FROM messages WHERE chat_id = ? ORDER BY telegram_timestamp ASC", (cid,))
    rows = c.fetchall()
    
    reasons = {}
    examples = {}
    valid_count = 0
    total_sig = 0
    
    from datetime import datetime
    for mid, text, dt in rows:
        meta = SourceMetadata(chat_id=cid, message_id=mid, telegram_timestamp=datetime.utcnow())
        sig = sig_parser.parse(text, meta)
        if sig.symbol_candidate and (sig.entries or sig.stop_loss):
            total_sig += 1
            res, val = validator.validate_and_resolve(sig, cfg.sources.get(cid))
            if val:
                valid_count += 1
            else:
                reason = sig.blocking_reason or "UNKNOWN_REASON"
                reasons[reason] = reasons.get(reason, 0) + 1
                if reason not in examples:
                    examples[reason] = text[:150]
                    
    print(f"\n=======================================================")
    print(f"KÊNH: {name} (ID: {cid})")
    print(f"Tổng kèo phát hiện: {total_sig} | Hợp lệ: {valid_count} | Bị chặn/lỗi: {total_sig - valid_count}")
    print("Các lý do bị chặn/lỗi:")
    for r, cnt in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
        print(f"  - [{cnt} lần] {r}")
        print(f"    Mẫu: {repr(examples[r])[:100]}")

conn.close()
