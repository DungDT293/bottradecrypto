import asyncio
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from telethon import TelegramClient, events

from config.config import AppConfig
from core.enums import ExecutionMode, PositionSide, SignalState, UpdateType
from core.models import SourceMetadata
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from storage.database import DatabaseManager, SignalRepository


class TelegramSignalListener:
    """
    Listens to allowed Telegram channels/groups.
    Strictly separates:
    - New signal age check (signal_max_age_seconds) vs Edit age check
    - Tracks incremental message versions (detects duplicates and out-of-order edits)
    - Recursively resolves reply-to links to parent signals
    - Classifies channel administrative updates via ChannelUpdateParser
    - Invariants:
        * Never treats admin 'TP hit' as account fill
        * Never treats 'wrong signal' as position reversal
        * Never allows SL edits that increase risk beyond policy
    """

    def __init__(
        self,
        config: AppConfig,
        tg_client: TelegramClient,
        db_manager: DatabaseManager,
        order_manager: Optional[OrderManager] = None,
        position_manager: Optional[PositionManager] = None,
    ):
        self.config = config
        self.tg_client = tg_client
        self.db = db_manager
        self.signal_repo = SignalRepository(db_manager)
        self.parser = SignalParser()
        self.validator = SignalValidator(config)
        self.update_parser = ChannelUpdateParser()
        self.order_manager = order_manager
        self.position_manager = position_manager

    def compute_fingerprint(self, text: str) -> str:
        cleaned = "".join(text.split()).lower()
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    async def handle_incoming_message(self, event: Any, is_edit: bool = False) -> None:
        chat_id = event.chat_id
        msg_id = event.id
        raw_text = event.raw_text or ""
        reply_to_msg_id = getattr(event, "reply_to_msg_id", None)

        # 1. Check Allowlist
        allowed_chats = self.config.telegram.allowed_chat_ids
        if allowed_chats and chat_id not in allowed_chats:
            return  # Silently ignore channels not in allowlist

        now_utc = datetime.now(timezone.utc)
        orig_date = getattr(event, "date", None)
        edit_date = getattr(getattr(event, "message", event), "edit_date", None)

        if orig_date and orig_date.tzinfo is None:
            orig_date = orig_date.replace(tzinfo=timezone.utc)
        if edit_date and edit_date.tzinfo is None:
            edit_date = edit_date.replace(tzinfo=timezone.utc)

        # 2. Differentiated Age / TTL Checks
        if not is_edit:
            # NEW SIGNAL: Check if original post time is stale
            if orig_date:
                age_seconds = (now_utc - orig_date).total_seconds()
                if age_seconds > self.config.risk.signal_max_age_seconds:
                    print(f"[BI CHAN: TIN MOI NHUNG QUA HAN] Tin cu ({int(age_seconds)}s > {self.config.risk.signal_max_age_seconds}s). Bo qua entry.")
                    return
        else:
            # EDIT: Check if edit itself is stale
            effective_edit_date = edit_date or now_utc
            edit_age_seconds = (now_utc - effective_edit_date).total_seconds()
            if edit_age_seconds > self.config.telegram.reconnect_max_backlog_seconds:
                print(f"[BI CHAN: EDIT QUA HAN] Thoi diem sua cach day ({int(edit_age_seconds)}s > {self.config.telegram.reconnect_max_backlog_seconds}s).")
                return

        # 3. Normalize text
        normalized = normalize_text(raw_text)
        if not normalized:
            # Empty / deleted message content
            print(f"[THONG TIN] Tin nhan trong hoac da bi xoa. Msg ID: {msg_id}")
            return

        fingerprint = self.compute_fingerprint(normalized)
        event_time = (edit_date or orig_date or now_utc).replace(tzinfo=None)

        # 4. Save Version and Detect Invariants (Duplicate, Out-of-order)
        version, is_valid_version, status_code = self.signal_repo.save_message_version(
            chat_id=chat_id,
            message_id=msg_id,
            event_date=event_time,
            received_at=datetime.utcnow(),
            raw_text=raw_text,
            normalized_text=normalized,
            fingerprint=fingerprint,
            is_edit=is_edit,
            reply_to_msg_id=reply_to_msg_id,
        )

        if status_code == "DUPLICATE":
            print(f"[BO QUA: EDIT TRUNG LAP] Chat ID: {chat_id} | Msg ID: {msg_id} v{version}")
            return
        elif status_code == "OUT_OF_ORDER":
            print(f"[CANH BAO: EDIT DEN SAI THU TU] Chat ID: {chat_id} | Msg ID: {msg_id} (Timestamp cu hon version hien tai)")
            return

        # Ensure base message record exists
        self.signal_repo.save_message(
            chat_id=chat_id,
            message_id=msg_id,
            sender_id=getattr(event, "sender_id", None),
            telegram_timestamp=(orig_date or now_utc).replace(tzinfo=None),
            received_at=datetime.utcnow(),
            raw_text=raw_text,
            normalized_text=normalized,
            fingerprint=fingerprint,
            edit_timestamp=edit_date.replace(tzinfo=None) if edit_date else None,
        )

        print(f"\n[DA NHAN TIN] Chat ID: {chat_id} | Msg ID: {msg_id} | v{version} {'(CHINH SUA)' if is_edit else ''}")

        # 5. Check if this is an administrative update or reply
        parent_signal_id = None
        if reply_to_msg_id:
            parent_signal_id = self.signal_repo.resolve_reply_parent(chat_id, reply_to_msg_id)

        update_type, update_val, detail_text = self.update_parser.parse_update(normalized)

        # Handle specific update types
        if update_type == UpdateType.RESULT_TP_REPORTED:
            print(f"[THONG TIN] {detail_text}. He thong chi chot loi khi san xac nhan fill.")
            if parent_signal_id:
                self.signal_repo.record_timeline_event(parent_signal_id, "ADMIN_TP_REPORTED", detail_text)
            return

        if update_type == UpdateType.CORRECT_SIGNAL:
            print(f"[CHO XAC NHAN] {detail_text}. Tin nhan duoc danh dau can kiem tra.")
            if parent_signal_id:
                self.signal_repo.record_timeline_event(parent_signal_id, "ADMIN_CORRECTION", detail_text)
                self.signal_repo.update_signal_state(parent_signal_id, SignalState.NEEDS_REVIEW, detail_text)
            return

        if update_type == UpdateType.CANCEL_PENDING_ENTRY:
            print(f"[YEU CAU HUY] Admin yeu cau huy pending entry.")
            if parent_signal_id and self.order_manager:
                sig_data = self.signal_repo.get_signal(parent_signal_id)
                if sig_data:
                    await self.order_manager.cancel_pending_entries_for_signal(parent_signal_id, sig_data["symbol"])
                    self.signal_repo.record_timeline_event(parent_signal_id, "ENTRIES_CANCELED", "Admin canceled pending entries")
            return

        # 6. Parse Signal Content
        meta = SourceMetadata(
            chat_id=chat_id,
            message_id=msg_id,
            sender_id=getattr(event, "sender_id", None),
            telegram_timestamp=(orig_date or now_utc).replace(tzinfo=None),
            received_at=datetime.utcnow(),
            is_edit=is_edit,
            edit_timestamp=edit_date.replace(tzinfo=None) if edit_date else None,
        )

        parsed = self.parser.parse(raw_text, meta)

        # If this is an edit of an existing active signal: check SL change rules
        if is_edit:
            existing_sig = self.signal_repo.get_active_signal_for_symbol(parsed.symbol_candidate or "")
            if existing_sig and parsed.stop_loss:
                old_sl = Decimal(existing_sig["stop_loss"])
                side = PositionSide(existing_sig["side"])
                new_sl = parsed.stop_loss

                # Strict Rule: Cannot widen SL if it increases risk!
                is_widening = (new_sl < old_sl) if side == PositionSide.LONG else (new_sl > old_sl)
                if is_widening:
                    print(f"[BI CHAN: EDIT NOI SL LAM TANG RUI RO] SL cu: {old_sl} -> SL moi: {new_sl} lam tang rui ro. Giu nguyen SL cu.")
                    self.signal_repo.record_timeline_event(
                        existing_sig["signal_id"],
                        "REJECT_SL_WIDENING",
                        f"Tu choi noi SL tu {old_sl} thanh {new_sl} vi lam tang risk",
                    )
                    return

        # 7. Validate & Resolve Policies
        self.signal_repo.save_signal(parsed)
        source_override = self.config.sources.get(chat_id)
        parsed, validated = self.validator.validate_and_resolve(parsed, source_override)
        self.signal_repo.save_signal(parsed)

        # 8. Report Status in Vietnamese without accents
        status = parsed.validation_status
        if status == SignalState.REJECTED:
            print(f"[BI CHAN: {parsed.blocking_reason}]")
            return
        elif status == SignalState.NEEDS_REVIEW:
            print(f"[CHO XAC NHAN] {parsed.blocking_reason}")
            return
        elif status == SignalState.NEEDS_POLICY:
            print(f"[CHO CAU HINH] {parsed.blocking_reason}")
            return
        elif status == SignalState.VALIDATED:
            print(f"[DA XAC THUC] Symbol: {validated.symbol} | Huong: {validated.side.value} | SL: {validated.stop_loss} | Leverage: {validated.leverage}x")

            self.signal_repo.record_timeline_event(
                validated.signal_id,
                "SIGNAL_VALIDATED",
                f"Tin hieu da duoc xac thuc: {validated.symbol} {validated.side.value}",
            )

            if self.config.mode == ExecutionMode.READ_ONLY:
                print(f"[READ_ONLY] Che do chi doc. Khong dat lenh len san.")
                return

    async def start(self) -> None:
        """Registers handlers and starts listening."""
        @self.tg_client.on(events.NewMessage)
        async def new_message_handler(event):
            await self.handle_incoming_message(event, is_edit=False)

        @self.tg_client.on(events.MessageEdited)
        async def message_edited_handler(event):
            await self.handle_incoming_message(event, is_edit=True)

        print(f"\n[DA KET NOI TELEGRAM] Dang lang nghe tin hieu tu cac kenh duoc phep...")
        print(f"Che do hien tai: {self.config.mode.value}")
        print(f"Danh sach chat_id theo doi: {self.config.telegram.allowed_chat_ids or 'Chua cau hinh (khong nhan kenh nao)'}")
        await self.tg_client.run_until_disconnected()
