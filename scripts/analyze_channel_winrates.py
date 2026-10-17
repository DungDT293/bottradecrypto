import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Any

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

cutoff = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
conn = sqlite3.connect("data/trading_state.db")
c = conn.cursor()

CHANNELS = [
    {"name": "Crypto Hunters", "id": -1002191067035},
    {"name": "Crypto Neon", "id": -1001370457350},
    {"name": "Crypto spider 🕷️ scalper", "id": -1001895315984},
    {"name": "THE WOLF (CRYPTO)®", "id": -1002007658025},
    {"name": "CRYPTO LEOPARD'S", "id": -1002052872813},
    {"name": "THE CRYPTO TRADER", "id": -1001590450482},
    {"name": "THE MASTER (CRYPTO)", "id": -1002266035358},
    {"name": "Global Crypto Research", "id": -1001161683441},
    {"name": "Crypto World Updates", "id": -1001652601224},
]

all_signals_by_channel = {}
unique_symbols = set()

for ch in CHANNELS:
    cid = ch["id"]
    cname = ch["name"]
    override = cfg.sources.get(cid)
    
    c.execute("""
        SELECT message_id, raw_text, telegram_timestamp 
        FROM messages 
        WHERE chat_id = ? AND telegram_timestamp >= ?
        ORDER BY telegram_timestamp ASC
    """, (cid, cutoff))
    
    rows = c.fetchall()
    valid_signals = []
    
    for mid, text, dt in rows:
        meta = SourceMetadata(chat_id=cid, message_id=mid, telegram_timestamp=datetime.fromisoformat(dt) if "T" in dt else datetime.utcnow())
        sig = sig_parser.parse(text, meta)
        if sig.symbol_candidate and (sig.entries or sig.stop_loss):
            res, val = validator.validate_and_resolve(sig, override)
            if val:
                entry_p = float(val.entries[0][0])
                sl_p = float(val.stop_loss)
                tp1_p = float(val.take_profits[0][0])
                tp2_p = float(val.take_profits[1][0]) if len(val.take_profits) > 1 else None
                tp3_p = float(val.take_profits[2][0]) if len(val.take_profits) > 2 else None
                
                valid_signals.append({
                    "id": mid,
                    "date": dt,
                    "symbol": val.symbol,
                    "side": val.side.value,
                    "entry": entry_p,
                    "sl": sl_p,
                    "tp1": tp1_p,
                    "tp2": tp2_p,
                    "tp3": tp3_p,
                    "leverage": val.leverage,
                })
                unique_symbols.add(val.symbol)
                
    all_signals_by_channel[cname] = valid_signals
    print(f"{cname:<28} | Valid Signals: {len(valid_signals)}")

print(f"\nTotal Unique Symbols across all 9 channels: {len(unique_symbols)}")
conn.close()

