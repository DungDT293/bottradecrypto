import json
import os
import sys
import hashlib
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config.config import load_config
from core.enums import SignalState, UpdateType
from core.models import SourceMetadata
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from storage.database import DatabaseManager, SignalRepository


def import_and_parse():
    config = load_config()
    db = DatabaseManager(os.path.join(PROJECT_ROOT, "data", "trading_state.db"))
    signal_repo = SignalRepository(db)
    parser = SignalParser()
    validator = SignalValidator(config)
    update_parser = ChannelUpdateParser()

    json_path = os.path.join(PROJECT_ROOT, "data", "extracted_channel_messages.json")
    with open(json_path, "r", encoding="utf-8") as f:
        msgs = json.load(f)

    # Sort chronological (oldest to newest)
    sorted_msgs = sorted(msgs, key=lambda m: m["message_id"])

    total_signals = 0
    total_validated = 0
    total_updates = 0
    per_channel = {}

    for m in sorted_msgs:
        raw_text = m.get("raw_text") or ""
        if not raw_text.strip():
            continue

        chat_id = m["chat_id"]
        msg_id = m["message_id"]
        sender_id = m.get("sender_id")
        reply_to_msg_id = m.get("reply_to_msg_id")
        ch_title = m.get("channel_title", "Unknown")

        if ch_title not in per_channel:
            per_channel[ch_title] = {"messages": 0, "signals": 0, "updates": 0}
        per_channel[ch_title]["messages"] += 1

        orig_date = datetime.fromisoformat(m["date"]).replace(tzinfo=None) if m.get("date") else datetime.utcnow()
        edit_date = datetime.fromisoformat(m["edit_date"]).replace(tzinfo=None) if m.get("edit_date") else None
        now_utc = datetime.utcnow()

        normalized = normalize_text(raw_text)
        fingerprint = hashlib.sha256("".join(normalized.split()).lower().encode("utf-8")).hexdigest() if normalized else ""

        # 1. Save message & version
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
            total_updates += 1
            per_channel[ch_title]["updates"] += 1
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
            total_signals += 1
            per_channel[ch_title]["signals"] += 1
            signal_repo.save_signal(parsed)

            source_override = config.sources.get(chat_id)
            parsed, validated = validator.validate_and_resolve(parsed, source_override)
            signal_repo.save_signal(parsed)

            if validated:
                total_validated += 1
                signal_repo.record_timeline_event(
                    validated.signal_id,
                    "SIGNAL_VALIDATED",
                    f"Tín hiệu hợp lệ: {validated.symbol} {validated.side.value}",
                    {
                        "leverage": validated.leverage,
                        "entries": [str(e) for e in validated.entries],
                        "stop_loss": str(validated.stop_loss),
                        "take_profits": [str(tp) for tp in validated.take_profits],
                    },
                )

    print("=" * 60)
    print(f"✅ ĐÃ NẠP & BÓC TÁCH TOÀN BỘ {len(sorted_msgs)} TIN NHẮN VÀO CƠ SỞ DỮ LIỆU:")
    print(f"   - Tổng tín hiệu nhận diện: {total_signals}")
    print(f"   - Tín hiệu hợp lệ (Validated): {total_validated}")
    print(f"   - Cập nhật Admin / TP Hit: {total_updates}")
    print("=" * 60)
    print("\nChi tiết từng kênh đã quét:")
    for ch, data in per_channel.items():
        print(f"   • {ch}: {data['messages']} tin | {data['signals']} tín hiệu | {data['updates']} cập nhật")


if __name__ == "__main__":
    import_and_parse()

