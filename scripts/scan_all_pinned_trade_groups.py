import asyncio
import hashlib
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Set

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from telethon import TelegramClient, utils
from telethon.tl.functions.messages import GetDialogFiltersRequest

from config.config import load_config
from core.enums import SignalState, UpdateType
from core.models import SourceMetadata
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from storage.database import DatabaseManager, SignalRepository


async def scan_pinned_trade_groups():
    config = load_config()
    db = DatabaseManager(os.path.join(PROJECT_ROOT, "data", "trading_state.db"))
    signal_repo = SignalRepository(db)
    parser = SignalParser()
    validator = SignalValidator(config)
    update_parser = ChannelUpdateParser()

    session_path = os.path.join(PROJECT_ROOT, "data", "telegram_user")
    client = TelegramClient(session_path, config.telegram.api_id, config.telegram.api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        print("[LỖI] Phiên làm việc Telegram chưa được xác thực.")
        return

    print("=" * 60)
    print("🔍 ĐANG TÌM KIẾM CÁC NHÓM ĐƯỢC GHIM (PINNED) TRONG TELEGRAM...")
    print("=" * 60)

    raw_filters = await client(GetDialogFiltersRequest())
    filters = raw_filters.filters if hasattr(raw_filters, "filters") else (raw_filters if isinstance(raw_filters, list) else [])

    trade_folder_pinned_ids: Set[int] = set()
    for f in filters:
        title = getattr(f, "title", "")
        if hasattr(title, "text"):
            title = str(title.text)
        elif not isinstance(title, str):
            title = str(title)

        # Focus on trade folder
        if "kèo" in title.lower() or "trade" in title.lower():
            for p in getattr(f, "pinned_peers", []) or []:
                try:
                    trade_folder_pinned_ids.add(utils.get_peer_id(p))
                except Exception:
                    pass

    dialogs = await client.get_dialogs()
    target_pinned = []

    for d in dialogs:
        # Pinned in Trade folder or globally pinned channels/groups
        is_trade_pinned = d.id in trade_folder_pinned_ids
        is_global_pinned = d.pinned and (d.is_channel or d.is_group)

        if is_trade_pinned or is_global_pinned:
            # Filter out bot stores / non-trade chats
            t_lower = d.title.lower()
            if any(k in t_lower for k in ["bot", "shop", "claim", "ton station", "dropee", "bums", "tapswap", "dogs", "playdeck", "blum"]):
                continue
            target_pinned.append(d)

    print(f"👉 Tìm thấy {len(target_pinned)} nhóm/kênh giao dịch được bạn ghim:")
    for idx, d in enumerate(target_pinned, 1):
        print(f"   {idx}. {d.title} (ID: {d.id})")

    print("\n" + "=" * 60)
    print("🚀 BẮT ĐẦU TỰ ĐỘNG THU THẬP & BÓC TÁCH TÍN HIỆU...")
    print("=" * 60)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=7)
    total_messages_collected = 0
    total_signals_detected = 0
    total_signals_validated = 0
    total_updates_recorded = 0

    results_per_channel = []

    for idx, d in enumerate(target_pinned, 1):
        print(f"\n[{idx}/{len(target_pinned)}] Đang quét: {d.title} (ID: {d.id})...")
        channel_msgs = []
        try:
            async for msg in client.iter_messages(d.entity, limit=80):
                if msg.date and msg.date < cutoff_date:
                    break
                raw_text = msg.raw_text or ""
                if not raw_text.strip():
                    continue

                reply_id = getattr(msg.reply_to, "reply_to_msg_id", None) if msg.reply_to else None
                channel_msgs.append({
                    "chat_id": d.id,
                    "message_id": msg.id,
                    "sender_id": msg.sender_id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "edit_date": msg.edit_date.isoformat() if msg.edit_date else None,
                    "reply_to_msg_id": reply_id,
                    "raw_text": raw_text,
                })
        except Exception as e:
            print(f"   ⚠️ Lỗi khi tải tin nhắn: {e}")
            continue

        # Sort chronological (oldest to newest)
        sorted_msgs = sorted(channel_msgs, key=lambda m: m["message_id"])
        ch_signals = 0
        ch_validated = 0
        ch_updates = 0

        for m in sorted_msgs:
            raw_text = m["raw_text"]
            msg_id = m["message_id"]
            chat_id = m["chat_id"]
            sender_id = m.get("sender_id")
            reply_to_msg_id = m.get("reply_to_msg_id")

            orig_date = datetime.fromisoformat(m["date"]).replace(tzinfo=None) if m.get("date") else datetime.utcnow()
            edit_date = datetime.fromisoformat(m["edit_date"]).replace(tzinfo=None) if m.get("edit_date") else None
            now_utc = datetime.utcnow()

            normalized = normalize_text(raw_text)
            fingerprint = hashlib.sha256("".join(normalized.split()).lower().encode("utf-8")).hexdigest() if normalized else ""

            # 1. Save message & message version
            signal_repo.save_message(
                chat_id=chat_id,
                message_id=msg_id,
                sender_id=sender_id,
                telegram_timestamp=orig_date,
                received_at=now_utc,
                raw_text=raw_text,
                normalized_text=normalized,
                fingerprint=fingerprint,
                edit_timestamp=edit_date,
            )

            signal_repo.save_message_version(
                chat_id=chat_id,
                message_id=msg_id,
                event_date=edit_date or orig_date,
                received_at=now_utc,
                raw_text=raw_text,
                normalized_text=normalized,
                fingerprint=fingerprint,
                is_edit=bool(edit_date),
                reply_to_msg_id=reply_to_msg_id,
            )

            # 2. Check update
            u_type, u_val, detail_text = update_parser.parse_update(normalized)
            if u_type != UpdateType.UNKNOWN:
                ch_updates += 1
                total_updates_recorded += 1
                parent_sig_id = signal_repo.resolve_reply_parent(chat_id, reply_to_msg_id) if reply_to_msg_id else None
                if parent_sig_id:
                    signal_repo.record_timeline_event(
                        parent_sig_id,
                        u_type.value,
                        detail_text,
                        {"message_id": msg_id, "chat_id": chat_id},
                    )
                if u_type in [
                    UpdateType.RESULT_TP_REPORTED,
                    UpdateType.RESULT_SL_REPORTED,
                    UpdateType.CANCEL_PENDING_ENTRY,
                    UpdateType.CORRECT_SIGNAL,
                ]:
                    continue

            # 3. Parse signal
            meta = SourceMetadata(
                chat_id=chat_id,
                message_id=msg_id,
                sender_id=sender_id,
                telegram_timestamp=orig_date,
                received_at=now_utc,
                is_edit=bool(edit_date),
                edit_timestamp=edit_date,
            )
            parsed = parser.parse(raw_text, meta)

            if parsed.symbol_candidate and parsed.side:
                ch_signals += 1
                total_signals_detected += 1
                signal_repo.save_signal(parsed)

                source_override = config.sources.get(chat_id)
                parsed, validated = validator.validate_and_resolve(parsed, source_override)
                signal_repo.save_signal(parsed)

                if validated:
                    ch_validated += 1
                    total_signals_validated += 1
                    signal_repo.record_timeline_event(
                        validated.signal_id,
                        "SIGNAL_VALIDATED",
                        f"Tín hiệu xác thực: {validated.symbol} {validated.side.value}",
                        {
                            "leverage": validated.leverage,
                            "entries": [str(e) for e in validated.entries],
                            "stop_loss": str(validated.stop_loss),
                            "take_profits": [str(tp) for tp in validated.take_profits],
                        },
                    )

        total_messages_collected += len(channel_msgs)
        results_per_channel.append({
            "title": d.title,
            "chat_id": d.id,
            "messages": len(channel_msgs),
            "signals": ch_signals,
            "validated": ch_validated,
            "updates": ch_updates,
        })
        print(f"   ✅ Đã thu thập {len(channel_msgs)} tin | Tín hiệu: {ch_signals} ({ch_validated} hợp lệ) | Cập nhật Admin: {ch_updates}")

    await client.disconnect()

    print("\n" + "=" * 60)
    print("🎉 HOÀN THÀNH QUÉT TẤT CẢ CÁC NHÓM GHIM!")
    print(f"- Tổng số tin thu thập: {total_messages_collected}")
    print(f"- Tổng số tín hiệu nhận diện: {total_signals_detected}")
    print(f"- Số tín hiệu hợp lệ ngay: {total_signals_validated}")
    print(f"- Số cập nhật trạng thái Admin: {total_updates_recorded}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(scan_pinned_trade_groups())

