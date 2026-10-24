import os
import sys
import shutil
import asyncio
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

sys.path.insert(0, r"e:\TOOL DUNG CODE\bottradecrypto")
sys.stdout.reconfigure(encoding='utf-8')

from telethon import TelegramClient
from parser.signal_parser import SignalParser
from parser.validator import SignalValidator
from config.config import load_config
from core.models import SourceMetadata
from core.enums import SignalState

session_orig = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\telegram_user.session')
session_copy = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\temp_audit_8new.session')
shutil.copy2(session_orig, session_copy)

api_id = 28680296
api_hash = '927e2da6e7d0ec3d97a79d11cc794e46'

TARGETS = [
    (-1002266035358, "THE MASTER (CRYPTO)"),
    (-1001903052876, "AISH CRYPTO"),
    (-1001520053536, "Coin Chief"),
    (-1001598691683, "Crypto Devil® [ Private 🔒 ]"),
    (-1001652601224, "Crypto World Updates"),
    (-1001391574614, "Bitcoin Bulls"),
    (-1001590450482, "THE CRYPTO TRADER"),
    (-1002078531832, "Crypto Mermaids")
]

client = TelegramClient(session_copy, api_id, api_hash)

async def run():
    await client.connect()
    cfg_p = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\config.yaml')
    config = load_config(cfg_p)
    parser = SignalParser()
    validator = SignalValidator(config)
    
    results = {}

    for cid, name in TARGETS:
        print(f"\n{'='*70}\nINVESTIGATING SYNTAX FOR: {name} (ID: {cid})\n{'='*70}")
        try:
            entity = await client.get_entity(cid)
            messages = await client.get_messages(entity, limit=60)
        except Exception as e:
            print(f"Error fetching {name}: {e}")
            continue

        validated_signals = []
        rejected_potential = []
        raw_samples = []

        for m in messages:
            txt = m.text or ""
            if not txt or len(txt) < 15:
                continue

            meta = SourceMetadata(chat_id=cid, message_id=m.id, telegram_timestamp=m.date or datetime.now(timezone.utc), received_at=datetime.now(timezone.utc))
            parsed = parser.parse(txt, meta)
            override = config.sources.get(cid) or config.sources.get(str(cid))
            parsed, validated = validator.validate_and_resolve(parsed, override)

            # Check if this message was a signal or had trading elements
            is_trade_candidate = any(w in txt.upper() for w in ["BUY", "SELL", "LONG", "SHORT", "ENTRY", "TARGET", "STOP", "LEVERAGE", "TP1", "SL"])
            
            if validated:
                validated_signals.append({
                    "msg_id": m.id,
                    "symbol": validated.symbol,
                    "side": validated.side.value,
                    "entries": [str(e[0]) for e in validated.entries],
                    "sl": str(validated.stop_loss),
                    "tps": [str(t[0]) for t in validated.take_profits],
                    "leverage": validated.leverage,
                    "raw_sample": txt[:250].replace('\n', ' ')
                })
                if len(raw_samples) < 2:
                    raw_samples.append(txt)
            elif is_trade_candidate and not ("T.ME/+" in txt.upper() and "TARGET" in txt.upper()) and not ("Trade Result" in str(parsed.blocking_reason)):
                rejected_potential.append({
                    "msg_id": m.id,
                    "status": parsed.validation_status.value,
                    "reason": parsed.blocking_reason,
                    "symbol": parsed.symbol_candidate or parsed.symbol_raw,
                    "side": parsed.side.value if parsed.side else None,
                    "snippet": txt[:200].replace('\n', ' ')
                })

        print(f"-> VALIDATED Signals: {len(validated_signals)}")
        print(f"-> Potential / Edge cases to inspect: {len(rejected_potential)}")
        for r in rejected_potential[:3]:
            print(f"   * Msg #{r['msg_id']}: Status={r['status']} | Reason={r['reason']} | Snippet={r['snippet']}")

        results[str(cid)] = {
            "name": name,
            "validated_count": len(validated_signals),
            "edge_case_count": len(rejected_potential),
            "validated_samples": validated_signals[:3],
            "edge_cases": rejected_potential,
            "raw_samples": raw_samples
        }

    out_file = "data/audit_8_new_channels_syntax.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nWritten syntax audit to {out_file}")

client.loop.run_until_complete(run())
client.disconnect()

