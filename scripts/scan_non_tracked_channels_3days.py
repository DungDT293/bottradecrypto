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
from core.models import SourceMetadata
from core.enums import SignalState

session_orig = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\telegram_user.session')
session_copy = os.path.expandvars(r'%APPDATA%\telegram_binance_signal_executor\data\temp_scan_3d.session')
shutil.copy2(session_orig, session_copy)

api_id = 28680296
api_hash = '927e2da6e7d0ec3d97a79d11cc794e46'

client = TelegramClient(session_copy, api_id, api_hash)

async def scan():
    await client.connect()
    with open("data/all_non_tracked_channels.json", "r", encoding="utf-8") as f:
        channels = json.load(f)

    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    parser = SignalParser()
    
    signal_channels = []
    scanned_count = 0
    total_channels = len(channels)
    
    print(f"Starting scan across {total_channels} channels for messages since {cutoff.strftime('%Y-%m-%d %H:%M UTC')}...")

    for c in channels:
        scanned_count += 1
        cid = c['id']
        title = c['title']
        
        try:
            entity = await client.get_entity(cid)
            messages = await client.get_messages(entity, limit=80)
        except Exception as e:
            # Channel might be restricted, deleted, or require special access
            continue

        signals_in_3d = []
        recent_activity_count = 0

        for m in messages:
            if not m.date or m.date < cutoff:
                continue
            recent_activity_count += 1
            txt = m.text or ""
            if not txt or len(txt) < 15:
                continue

            meta = SourceMetadata(
                chat_id=cid,
                message_id=m.id,
                telegram_timestamp=m.date,
                received_at=datetime.now(timezone.utc)
            )
            parsed = parser.parse(txt, meta)
            
            symbol = parsed.symbol_candidate or parsed.symbol_raw
            # Check if this qualifies as a trading signal
            if symbol and parsed.side and parsed.entries and (parsed.take_profits or parsed.stop_loss):
                signals_in_3d.append({
                    "msg_id": m.id,
                    "date": m.date.strftime("%Y-%m-%d %H:%M"),
                    "symbol": symbol,
                    "side": parsed.side.value if parsed.side else None,
                    "entries": [str(e) for e in parsed.entries] if parsed.entries else [],
                    "sl": str(parsed.stop_loss) if parsed.stop_loss else None,
                    "tps": [str(t) for t in parsed.take_profits] if parsed.take_profits else [],
                    "leverage": parsed.leverage_requested or (parsed.leverage_range[0] if parsed.leverage_range else None),
                    "status": parsed.validation_status.value,
                    "snippet": txt[:120].replace('\n', ' ')
                })

        if signals_in_3d:
            print(f"[FOUND SIGNAL CHANNEL] #{scanned_count}/{total_channels}: '{title}' (ID: {cid}) -> {len(signals_in_3d)} signals in 3 days")
            signal_channels.append({
                "id": cid,
                "title": title,
                "is_broadcast": c.get("is_broadcast", True),
                "signals_count_3d": len(signals_in_3d),
                "recent_activity_count": recent_activity_count,
                "signals": signals_in_3d
            })
        elif scanned_count % 25 == 0:
            print(f"Progress: scanned {scanned_count}/{total_channels} channels. Found {len(signal_channels)} signal channels so far...")

        # Small sleep to respect Telegram rate limits
        await asyncio.sleep(0.15)

    print(f"\n==========================================")
    print(f"COMPLETED SCAN: Found {len(signal_channels)} candidate signal channels out of {total_channels}")
    print(f"==========================================")
    
    out_path = "data/detected_signal_channels_3days.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(signal_channels, f, ensure_ascii=False, indent=2)
    print(f"Saved results to {out_path}")

client.loop.run_until_complete(scan())
client.disconnect()
