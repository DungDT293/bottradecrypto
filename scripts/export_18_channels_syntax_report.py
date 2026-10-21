import sys
import os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import json
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

parser = SignalParser()
now = datetime.now(timezone.utc)

report_data = []

for cid in allowed_chats:
    s = sources_cfg.get(cid) or sources_cfg.get(str(cid))
    name = s.name if s else f"Channel {cid}"
    
    msgs = conn.execute("""
        SELECT message_id, raw_text, telegram_timestamp
        FROM messages
        WHERE chat_id = ?
        ORDER BY telegram_timestamp DESC
    """, (cid,)).fetchall()
    
    total_msgs = len(msgs)
    trade_candidates = 0
    parsed_valid = 0
    sample_text = ""
    sample_parsed = None
    
    for m in msgs:
        raw = m["raw_text"] or ""
        # Check candidate
        has_dir = any(k in raw.upper() for k in ["LONG", "SHORT", "BUY", "SELL"])
        has_pair = "USDT" in raw.upper()
        if not (has_dir and has_pair):
            continue
        
        trade_candidates += 1
        meta = SourceMetadata(chat_id=cid, message_id=m["message_id"], telegram_timestamp=now, received_at=now)
        p = parser.parse(raw, meta)
        
        if p.validation_status in ["PARSED", "NEEDS_POLICY"]:
            parsed_valid += 1
            if not sample_text:
                sample_text = raw
                sample_parsed = {
                    "symbol": p.symbol_candidate,
                    "side": str(p.side),
                    "entries": [str(x) for x in p.entries],
                    "entry_mode": str(p.entry_mode),
                    "stop_loss": str(p.stop_loss),
                    "take_profits": [str(x) for x in p.take_profits],
                    "leverage": p.leverage_requested
                }

    report_data.append({
        "chat_id": cid,
        "name": name,
        "total_messages": total_msgs,
        "candidates": trade_candidates,
        "parsed_valid": parsed_valid,
        "success_rate_pct": round(parsed_valid / trade_candidates * 100, 1) if trade_candidates else 0.0,
        "sample_parsed": sample_parsed,
        "sample_text": sample_text[:500] if sample_text else "No active signal sample found"
    })

output_path = "data/18_channels_syntax_and_coverage_report.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(report_data, f, ensure_ascii=False, indent=2)

print(f"Report exported successfully to {output_path}")
conn.close()

