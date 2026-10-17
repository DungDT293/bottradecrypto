import sqlite3
import sys
from datetime import datetime
from decimal import Decimal
import json

import os
sys.path.insert(0, os.path.abspath("."))
sys.stdout.reconfigure(encoding='utf-8')

from config.config import load_config
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from core.models import SourceMetadata
from core.enums import SignalState
from storage.database import DatabaseManager, SignalRepository

cfg = load_config()
cfg.execution.allow_below_pattern_as_valid = True
validator = SignalValidator(cfg)
parser = SignalParser()

db = DatabaseManager(cfg.database_file)
repo = SignalRepository(db)

conn = sqlite3.connect(cfg.database_file)
c = conn.cursor()
c.execute('''
    SELECT s.signal_id, s.chat_id, s.message_id, m.raw_text, s.blocking_reason
    FROM signals s
    JOIN messages m ON s.message_id = m.message_id AND s.chat_id = m.chat_id
    WHERE s.state = 'NEEDS_REVIEW' AND s.blocking_reason LIKE '%Short BELOW%'
''')
rows = c.fetchall()
conn.close()
print(f"Bắt đầu xử lý {len(rows)} tín hiệu Short BELOW...")

validated_count = 0
rejected_count = 0

for r in rows:
    sig_id, chat_id, msg_id, raw_text, reason = r
    meta = SourceMetadata(chat_id=chat_id, message_id=msg_id, telegram_timestamp=datetime.utcnow())
    parsed = parser.parse(raw_text, meta)
    parsed, validated = validator.validate_and_resolve(parsed)
    
    if validated:
        repo.save_signal(parsed)
        repo.record_timeline_event(
            validated.signal_id,
            "SIGNAL_VALIDATED",
            f"Tín hiệu đã được xác thực chuẩn: {validated.symbol} {validated.side.value}",
            {
                "leverage": validated.leverage,
                "entries": [str(e) for e in validated.entries],
                "stop_loss": str(validated.stop_loss),
                "take_profits": [str(tp) for tp in validated.take_profits],
            }
        )
        validated_count += 1
    else:
        repo.save_signal(parsed)
        repo.record_timeline_event(
            parsed.signal_id,
            "SIGNAL_REJECTED",
            parsed.blocking_reason or "Lỗi an toàn cú pháp lệnh"
        )
        rejected_count += 1

print(f"\nHoàn tất xử lý:")
print(f"  - Đã chuyển sang VALIDATED (Hợp lệ): {validated_count} tín hiệu")
print(f"  - Đã chuyển sang REJECTED (Chặn lỗi gõ SL/TP chết người): {rejected_count} tín hiệu")

# In tổng quan hiện tại
c.execute("SELECT state, count(*) FROM signals GROUP BY state")
print("\nThống kê trạng thái signals hiện tại trong Database:")
for st, cnt in c.fetchall():
    print(f"  - {st:<15}: {cnt}")
