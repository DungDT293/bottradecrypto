import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from telethon import TelegramClient, utils, types
from telethon.tl.functions.messages import GetDialogFiltersRequest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.config import load_config
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from core.models import SourceMetadata
from core.enums import UpdateType, SignalState


async def extract_and_analyze():
    config = load_config()
    session_path = os.path.join(PROJECT_ROOT, "data", "telegram_user")
    client = TelegramClient(session_path, config.telegram.api_id, config.telegram.api_hash)

    await client.connect()
    if not await client.is_user_authorized():
        print("[ERROR] Telegram session not authorized.")
        return

    print("[1] Getting dialogs and folders...")
    raw_filters = await client(GetDialogFiltersRequest())
    filter_list = raw_filters.filters if hasattr(raw_filters, "filters") else (raw_filters if isinstance(raw_filters, list) else [])

    trade_chat_ids = set()
    folder_title = "Kèo trade"
    for f in filter_list:
        title = getattr(f, "title", "")
        if hasattr(title, "text"):
            title = str(title.text)
        elif not isinstance(title, str):
            title = str(title)

        if "kèo" in title.lower() or "trade" in title.lower():
            folder_title = title
            for p in getattr(f, "include_peers", []) or []:
                try:
                    trade_chat_ids.add(utils.get_peer_id(p))
                except Exception:
                    pass
            for p in getattr(f, "pinned_peers", []) or []:
                try:
                    trade_chat_ids.add(utils.get_peer_id(p))
                except Exception:
                    pass

    print(f"[2] Found trade folder '{folder_title}' with {len(trade_chat_ids)} channels.")

    dialogs = await client.get_dialogs()
    target_dialogs = []
    for d in dialogs:
        if d.id in trade_chat_ids or not trade_chat_ids:
            if d.is_channel or d.is_group:
                target_dialogs.append(d)

    # Sort target dialogs by unread count / priority
    print(f"[3] Selected {len(target_dialogs)} channels for historical extraction.")

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=14)
    dataset: List[Dict[str, Any]] = []

    # Limit to top 15 channels to avoid Telegram rate limits
    channels_to_scan = target_dialogs[:15]

    for idx, d in enumerate(channels_to_scan, 1):
        chat_id = d.id
        title = d.title
        print(f"    [{idx}/{len(channels_to_scan)}] Extracting: {title} (ID: {chat_id})...")
        count = 0
        try:
            async for msg in client.iter_messages(d.entity, limit=60):
                if msg.date and msg.date < cutoff_date:
                    break
                raw_text = msg.raw_text or ""
                if not raw_text.strip():
                    continue

                reply_id = None
                if msg.reply_to:
                    reply_id = getattr(msg.reply_to, "reply_to_msg_id", None)

                dataset.append({
                    "channel_title": title,
                    "chat_id": chat_id,
                    "message_id": msg.id,
                    "sender_id": msg.sender_id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "edit_date": msg.edit_date.isoformat() if msg.edit_date else None,
                    "reply_to_msg_id": reply_id,
                    "raw_text": raw_text,
                })
                count += 1
        except Exception as e:
            print(f"        [WARN] Failed to fetch from {title}: {e}")

    await client.disconnect()

    output_file = os.path.join(PROJECT_ROOT, "data", "extracted_channel_messages.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"\n[4] Extraction complete! Saved {len(dataset)} messages to '{output_file}'.")

    # Run Analysis using current SignalParser and ChannelUpdateParser
    print("\n[5] Running syntax analysis on extracted dataset...")
    parser = SignalParser()
    validator = SignalValidator(config)
    update_parser = ChannelUpdateParser()

    signals_found = []
    updates_found = []
    chat_found = []

    for item in dataset:
        raw_text = item["raw_text"]
        normalized = normalize_text(raw_text)
        
        # Check update
        u_type, u_val, u_desc = update_parser.parse_update(normalized)
        if u_type != UpdateType.UNKNOWN:
            updates_found.append({
                "channel": item["channel_title"],
                "type": u_type.value,
                "desc": u_desc,
                "text": raw_text[:120].replace("\n", " "),
            })
            continue

        # Check signal
        meta = SourceMetadata(
            chat_id=item["chat_id"],
            message_id=item["message_id"],
            telegram_timestamp=datetime.utcnow(),
        )
        parsed = parser.parse(raw_text, meta)
        if parsed.symbol_candidate and parsed.side:
            signals_found.append({
                "channel": item["channel_title"],
                "symbol": parsed.symbol_candidate,
                "side": parsed.side.value if parsed.side else None,
                "state": parsed.validation_status.value,
                "entry_mode": parsed.entry_mode.value if parsed.entry_mode else None,
                "entries": [str(e) for e in parsed.entries],
                "stop_loss": str(parsed.stop_loss) if parsed.stop_loss else None,
                "take_profits": [str(tp) for tp in parsed.take_profits],
                "leverage": parsed.leverage_requested,
                "raw_sample": raw_text[:160].replace("\n", " "),
            })
        else:
            chat_found.append({
                "channel": item["channel_title"],
                "text": raw_text[:100].replace("\n", " "),
            })

    print(f"    - Total Signals Identified: {len(signals_found)}")
    print(f"    - Total Admin Updates / TP Hits: {len(updates_found)}")
    print(f"    - Other Market Chat / Commentary: {len(chat_found)}")

    # Save summary report
    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_messages": len(dataset),
        "total_signals": len(signals_found),
        "total_updates": len(updates_found),
        "total_chat": len(chat_found),
        "signals": signals_found,
        "updates": updates_found[:30],
    }
    summary_file = os.path.join(PROJECT_ROOT, "data", "extracted_signals_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[6] Analysis report saved to '{summary_file}'.")


if __name__ == "__main__":
    asyncio.run(extract_and_analyze())
