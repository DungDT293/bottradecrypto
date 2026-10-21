import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import json
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from config.config import load_config
from core.models import SourceMetadata
from core.enums import SignalState
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

config = load_config("config.yaml")
parser = SignalParser()
validator = SignalValidator(config)

dbs = [
    r"C:\Users\PC Gaming\AppData\Roaming\telegram_binance_signal_executor\data\trading_state.db",
    r"data/trading_state.db"
]

for db_path in dbs:
    if not os.path.exists(db_path):
        continue
    print(f"\n================ RE-EVALUATING DATABASE: {db_path} ================")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Find rejected signals that have raw messages
    rows = conn.execute("""
        SELECT s.signal_id, s.chat_id, s.message_id, s.state, s.blocking_reason, m.raw_text, m.telegram_timestamp
        FROM signals s
        JOIN messages m ON s.chat_id = m.chat_id AND s.message_id = m.message_id
        WHERE s.state = 'REJECTED'
    """).fetchall()

    print(f"Total REJECTED signals with messages: {len(rows)}")
    recovered_count = 0

    for r in rows:
        raw = r["raw_text"] or ""
        chat_id = r["chat_id"]
        msg_id = r["message_id"]
        old_reason = r["blocking_reason"] or ""
        
        # Parse with updated parser
        now = datetime.now(timezone.utc)
        meta = SourceMetadata(chat_id=chat_id, message_id=msg_id, telegram_timestamp=now, received_at=now)
        parsed = parser.parse(raw, meta)
        
        source_override = config.sources.get(chat_id) or config.sources.get(str(chat_id))
        parsed, validated = validator.validate_and_resolve(parsed, source_override)
        
        # If it was recovered
        new_state = SignalState.VALIDATED.value if validated else parsed.validation_status.value
        new_reason = None if validated else parsed.blocking_reason
        
        # Check if recovered from TP/SL/Entry failure
        if ("Take Profit" in old_reason and parsed.take_profits) or ("SL (1)" in old_reason and parsed.stop_loss) or ("entry" in old_reason.lower() and parsed.entries):
            recovered_count += 1
            # Update database record
            tp_json = json.dumps([str(x) for x in parsed.take_profits]) if parsed.take_profits else "[]"
            entries_json = json.dumps([str(x) for x in parsed.entries]) if parsed.entries else "[]"
            sl_str = str(parsed.stop_loss) if parsed.stop_loss else None
            
            c.execute("""
                UPDATE signals
                SET state = ?,
                    blocking_reason = ?,
                    take_profits_json = ?,
                    entries_json = ?,
                    stop_loss = ?,
                    updated_at = ?
                WHERE signal_id = ?
            """, (
                new_state,
                new_reason,
                tp_json,
                entries_json,
                sl_str,
                datetime.utcnow().isoformat(),
                r["signal_id"]
            ))

    conn.commit()
    print(f"Successfully recovered and updated {recovered_count} signals in {db_path}!")

    # Verify CTRUSDT specifically
    ctrusdt = c.execute("SELECT signal_id, symbol, side, state, blocking_reason, take_profits_json, stop_loss, entries_json FROM signals WHERE message_id = 237139").fetchall()
    print("\n--- CTRUSDT VERIFICATION ---")
    for row in ctrusdt:
        print(dict(row))

    conn.close()
