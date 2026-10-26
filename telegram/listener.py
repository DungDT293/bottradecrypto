import asyncio
import hashlib
import re
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple
from telethon import TelegramClient, events

from config.config import AppConfig, exchange_writes_enabled, PERMANENT_BLACKLISTED_CHANNELS
from core.enums import ExecutionMode, OrderSide, OrderType, PositionSide, SignalState, UpdateType
from core.models import SourceMetadata, ValidatedSignal
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.reconciliation import build_validated_signal_from_row
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from risk.market_regime_shield import global_market_regime_shield
from services.channel_analytics_service import KNOWN_CHANNELS, ChannelAnalyticsService
from services.signal_queue_service import SignalQueueService, global_signal_queue_service
from services.admin_evidence import classify_media_claim, detect_media_kind, is_brag_media_claim
from storage.database import DatabaseManager, OrderRepository, SignalRepository

try:
    from backend.events.event_bus import event_bus
except Exception:
    event_bus = None

import builtins
_orig_print = builtins.print
def print(*args, **kwargs):
    try:
        _orig_print(*args, **kwargs)
    except Exception:
        try:
            cleaned = [str(a).encode("ascii", errors="replace").decode("ascii") for a in args]
            _orig_print(*cleaned, **kwargs)
        except Exception:
            pass


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
        is_shadow: bool = False,
        entry_enabled_provider: Optional[Callable[[], bool]] = None,
    ):
        self.config = config
        self.tg_client = tg_client
        self.db = db_manager
        self.signal_repo = SignalRepository(db_manager)
        self.order_repo = OrderRepository(db_manager)
        self.parser = SignalParser()
        self.validator = SignalValidator(config)
        self.update_parser = ChannelUpdateParser()
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.is_shadow = is_shadow
        self._entry_enabled = entry_enabled_provider or (lambda: True)
        self._periodic_sync_task: Optional[asyncio.Task] = None
        self._stop_requested = False
        self._last_sl_timestamp_by_chat: Dict[int, float] = {}
        self.analytics_service = ChannelAnalyticsService(db_path=getattr(db_manager, "db_path", "./data/trading_state.db"))
        self.signal_queue = global_signal_queue_service

    def _is_authorized_admin(self, event: Any) -> bool:
        sender_id = getattr(event, "sender_id", None)
        admin_ids = set(getattr(self.config.telegram, "admin_sender_ids", []) or [])
        return sender_id is not None and sender_id in admin_ids

    def compute_fingerprint(self, text: str) -> str:
        cleaned = "".join(text.split()).lower()
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    async def handle_incoming_message(self, event: Any, is_edit: bool = False) -> None:
        chat_id = event.chat_id
        msg_id = event.id
        raw_text = event.raw_text or ""
        reply_to_msg_id = getattr(event, "reply_to_msg_id", None)

        # 0. Check Permanent and Dynamic Blacklist (Anti-Fake Channels Shield)
        blacklisted_chats = set(getattr(self.config.telegram, "blacklisted_chat_ids", []) or [])
        blacklisted_chats.update(PERMANENT_BLACKLISTED_CHANNELS.keys())
        if chat_id in blacklisted_chats:
            reason = PERMANENT_BLACKLISTED_CHANNELS.get(chat_id, "Kenh Blacklist nguy hiem / fake tin hieu")
            print(f"[BI CHAN: KENH FAKE/LUA DAO BLACKLIST] Chat ID: {chat_id} | Msg: {msg_id} | Ly do: {reason}. Tu choi xu ly!")
            return

        # 1. Check Allowlist
        allowed_chats = self.config.telegram.allowed_chat_ids
        if not allowed_chats or chat_id not in allowed_chats:
            return  # Empty allowlist is deny-all

        # 1b. Content-Level Scam & Dangerous Execution Guards
        raw_lower = raw_text.lower()
        if any(w in raw_lower for w in ["remove sl", "reome sl", "dca and hold", "do dca", "closing below", "sl : my instruction", "stoploss : my instruction"]):
            print(f"[BI CHAN: LENH NGUY HIEM / GO SL] Chat ID: {chat_id} | Msg: {msg_id} yeu cau go SL hoac DCA gong lo. Tu choi ngay de bao toan von!")
            return

        if re.search(r'0x[a-fA-F0-9]{40}', raw_text) or re.search(r'T[A-Za-z1-9]{33}', raw_text):
            print(f"[BI CHAN: DIA CHI VI TIEN MA HOA] Chat ID: {chat_id} | Msg: {msg_id} chua dia chi vi nop tien/lua dao VIP. Bo qua!")
            return

        if "t.me/+" in raw_text and any(k in raw_lower for k in ["targets 👇", "targets:", "full set-up", "entry: targets"]):
            if not any(k in raw_lower for k in ["stoploss", "stop-loss", "stop loss", "sl:"]):
                print(f"[BI CHAN: TEASER LINK DONG VOI] Chat ID: {chat_id} | Msg: {msg_id} chi chua link teaser keo mem khong co SL so. Bo qua!")
                return

        # Record SL Hit announcements to activate Anti-Revenge Cool-off Guard (90 mins)
        if any(k in raw_lower for k in ["sl hit", "stop loss hit", "stoploss hit"]):
            self._last_sl_timestamp_by_chat[chat_id] = time.time()
            print(f"[GHI NHAN: KEO DINH SL] Chat ID: {chat_id} | Msg: {msg_id} thong bao SL hit. Kich hoat dong bang Anti-Revenge 90 phut.")

        now_utc = datetime.now(timezone.utc)
        orig_date = getattr(event, "date", None)
        edit_date = getattr(getattr(event, "message", event), "edit_date", None)

        if orig_date and orig_date.tzinfo is None:
            orig_date = orig_date.replace(tzinfo=timezone.utc)
        if edit_date and edit_date.tzinfo is None:
            edit_date = edit_date.replace(tzinfo=timezone.utc)

        # 2. Normalize text and inspect media attachment
        media_kind = detect_media_kind(event)
        normalized = normalize_text(raw_text)

        if not normalized and not media_kind:
            # Empty / deleted message content
            print(f"[THONG TIN] Tin nhan trong hoac da bi xoa. Msg ID: {msg_id}")
            return

        fingerprint = self.compute_fingerprint(normalized or f"media:{media_kind}")
        event_time = (edit_date or orig_date or now_utc).replace(tzinfo=None)

        # Check if edit is stale before storing
        if is_edit:
            effective_edit_date = edit_date or now_utc
            edit_age_seconds = (now_utc - effective_edit_date).total_seconds()
            if edit_age_seconds > self.config.telegram.reconnect_max_backlog_seconds:
                print(f"[BI CHAN: EDIT QUA HAN] Thoi diem sua cach day ({int(edit_age_seconds)}s > {self.config.telegram.reconnect_max_backlog_seconds}s).")
                return

        # 3. Save Version and Detect Invariants (Duplicate, Out-of-order)
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

        parent_signal_id = self.signal_repo.resolve_reply_parent(chat_id, reply_to_msg_id) if reply_to_msg_id else None

        # 3b. Handle Media / Charts
        if media_kind:
            evidence = classify_media_claim(raw_text, media_kind)
            self.signal_repo.save_admin_evidence(
                chat_id, msg_id, event_time, evidence,
                sender_id=getattr(event, "sender_id", None),
                parent_signal_id=parent_signal_id,
            )
            if parent_signal_id:
                self.signal_repo.record_timeline_event(
                    parent_signal_id,
                    "ADMIN_MEDIA_CLAIM",
                    evidence.detail,
                    {"evidence_type": evidence.evidence_type, "verification_status": evidence.verification_status},
                )
            if event_bus:
                try:
                    asyncio.create_task(event_bus.publish("admin_evidence_recorded", {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "evidence_type": evidence.evidence_type,
                        "exchange_claim": evidence.exchange_claim,
                        "verification_status": evidence.verification_status,
                        "is_trade_fill": False,
                    }))
                except Exception:
                    pass

            if is_brag_media_claim(raw_text):
                print(f"[CLAIM ONLY] Media message {msg_id}: {evidence.evidence_type}; brag / result claim, no trade action")
                return
            print(f"[MEDIA ATTACHED] Tin nhan {msg_id} co dinh kem hinh anh/chart ({media_kind}). Tiep tuc xu ly tin hieu.")

        channel_name = KNOWN_CHANNELS.get(chat_id, f"Kênh {chat_id}")
        print(f"\n[DA NHAN TIN] Nhóm: {channel_name} (ID: {chat_id}) | Msg ID: {msg_id} | v{version} {'(CHINH SUA)' if is_edit else ''}")

        # 4. Differentiated Age / TTL Checks
        is_stale_signal = False
        stale_reason = ""
        if not is_edit:
            # NEW SIGNAL: Check if original post time is stale
            if orig_date:
                age_seconds = (now_utc - orig_date).total_seconds()
                if age_seconds > self.config.risk.signal_max_age_seconds:
                    is_stale_signal = True
                    stale_reason = f"Tín hiệu quá hạn: nhận trễ {int(age_seconds)}s (vượt mức cho phép {self.config.risk.signal_max_age_seconds}s). Không vào lệnh."
                    print(f"[BI CHAN: TIN MOI NHUNG QUA HAN] {stale_reason}")

        # 5. Check if this is an administrative update or reply
        parent_signal_id = None
        if reply_to_msg_id:
            parent_signal_id = self.signal_repo.resolve_reply_parent(chat_id, reply_to_msg_id)

        update_type, update_val, detail_text = self.update_parser.parse_update(normalized)
        admin_update_types = {
            UpdateType.CANCEL_PENDING_ENTRY,
            UpdateType.ENTRY_CHANGE,
            UpdateType.MOVE_SL_TO_BREAKEVEN,
            UpdateType.CLOSE_ALL,
            UpdateType.SL_CHANGE,
        }
        if update_type in admin_update_types and not self._is_authorized_admin(event):
            if parent_signal_id:
                self.signal_repo.record_timeline_event(
                    parent_signal_id,
                    "ADMIN_UPDATE_UNAUTHORIZED",
                    f"Bỏ qua cập nhật {update_type.value} từ sender không được ủy quyền.",
                    {"sender_id": getattr(event, "sender_id", None)},
                )
            print(f"[CHAN CAP NHAT ADMIN KHONG DUOC UY QUYEN] sender_id={getattr(event, 'sender_id', None)}")
            return

        if update_type in admin_update_types and (self.is_shadow or not exchange_writes_enabled(self.config)):
            if parent_signal_id:
                self.signal_repo.record_timeline_event(
                    parent_signal_id,
                    "EXCHANGE_UPDATE_BLOCKED",
                    f"Đã chặn cập nhật sàn {update_type.value} trong chế độ {self.config.mode.value}.",
                )
            print(f"[CHAN CAP NHAT SAN] {update_type.value} bi chan trong che do {self.config.mode.value}.")
            return

        # Handle specific update types
        if update_type == UpdateType.RESULT_TP_REPORTED:
            print(f"[THONG TIN] {detail_text}. He thong chi chot loi khi san xac nhan fill.")
            if parent_signal_id:
                self.signal_repo.record_timeline_event(parent_signal_id, "ADMIN_TP_REPORTED", detail_text)

        elif update_type == UpdateType.CORRECT_SIGNAL:
            print(f"[CHO XAC NHAN] {detail_text}. Tin nhan duoc danh dau can kiem tra.")
            target_signal_id = parent_signal_id or self.signal_repo.get_latest_pending_signal_id(chat_id)
            if target_signal_id:
                self.signal_repo.record_timeline_event(target_signal_id, "ADMIN_CORRECTION", detail_text)
                self.signal_repo.update_signal_state(target_signal_id, SignalState.NEEDS_REVIEW, detail_text)
                print(f"[DA DANH DAU XAC NHAN] Kèo {target_signal_id} chuyển sang trạng thái NEEDS_REVIEW.")

        elif update_type == UpdateType.CANCEL_PENDING_ENTRY:
            print(f"[YEU CAU HUY] Admin yeu cau huy pending entry.")
            target_signal_id = parent_signal_id or self.signal_repo.get_latest_pending_signal_id(chat_id)
            if target_signal_id and self.order_manager:
                sig_data = self.signal_repo.get_signal(target_signal_id)
                if sig_data:
                    await self.order_manager.cancel_pending_entries_for_signal(target_signal_id, sig_data["symbol"])
                    self.signal_repo.record_timeline_event(target_signal_id, "ENTRIES_CANCELED", "Admin canceled pending entries")
                    print(f"[DA HUY PENDING ENTRY] Đã hủy toàn bộ lệnh chờ Limit của kèo {sig_data['symbol']} (Signal ID: {target_signal_id})")

        elif update_type == UpdateType.ENTRY_CHANGE:
            print(f"[YEU CAU DOI ENTRY] {detail_text}")
            target_signal_id = parent_signal_id or self.signal_repo.get_latest_pending_signal_id(chat_id)
            if target_signal_id and self.order_manager and update_val:
                sig_data = self.signal_repo.get_signal(target_signal_id)
                if sig_data and sig_data.get("state") == SignalState.ENTRY_PENDING.value:
                    symbol = sig_data["symbol"]
                    try:
                        await self.order_manager.cancel_pending_entries_for_signal(target_signal_id, symbol)
                        self.signal_repo.record_timeline_event(
                            target_signal_id,
                            "ENTRY_PRICE_CHANGED",
                            f"Admin yêu cầu đổi giá Entry sang {update_val}. Đã hủy lệnh Limit cũ.",
                        )
                        print(f"[DA DOI ENTRY] Đã hủy lệnh chờ Limit cũ của kèo {symbol} theo yêu cầu đổi Entry sang {update_val}.")
                    except Exception as ex_entry_update:
                        print(f"[CANH BAO] Khong the cap nhat Entry theo tin update: {ex_entry_update}")

        elif update_type == UpdateType.MOVE_SL_TO_BREAKEVEN:
            print(f"[YEU CAU DOI SL HOA VON] {detail_text}")
            target_signal_id = parent_signal_id or self.signal_repo.get_latest_pending_signal_id(chat_id)
            if target_signal_id and self.order_manager:
                sig_data = self.signal_repo.get_signal(target_signal_id)
                if sig_data and sig_data.get("state") in (SignalState.OPEN_PROTECTED.value, SignalState.PARTIALLY_FILLED.value):
                    symbol = sig_data["symbol"]
                    try:
                        pos = await self.order_manager.client.get_position(symbol)
                        amt = Decimal(str(pos.get("positionAmt", 0))) if pos else Decimal("0")
                        entry_p = Decimal(str(pos.get("entryPrice", 0))) if pos else Decimal("0")
                        if amt != Decimal("0") and entry_p > Decimal("0"):
                            val_sig = build_validated_signal_from_row(sig_data, self.config)
                            db_orders = self.order_repo.get_orders_for_signal(target_signal_id)
                            old_sl_id = None
                            for o in db_orders:
                                if o.is_algo and o.status == "NEW" and not o.client_order_id.startswith("be_"):
                                    old_sl_id = o.client_order_id
                                    break
                            be_order = await self.order_manager.move_sl_to_breakeven(
                                signal=val_sig,
                                position_qty=abs(amt),
                                avg_entry_price=entry_p,
                                existing_sl_algo_id=old_sl_id,
                            )
                            if be_order:
                                self.signal_repo.record_timeline_event(
                                    target_signal_id,
                                    "BREAKEVEN_SL_ACTIVATED",
                                    f"Admin yêu cầu 'Move SL to BE': Đã dời SL về hòa vốn Entry ({entry_p}) + phí sàn thành công!",
                                )
                                print(f"[DA DOI SL VE BE] Kèo {symbol} đã được dời SL về hòa vốn {entry_p} theo tin nhắn admin.")
                    except Exception as ex_be:
                        print(f"[CANH BAO] Khong the doi SL ve BE theo tin update: {ex_be}")

        elif update_type == UpdateType.CLOSE_ALL:
            print(f"[YEU CAU DONG TOAN BO VI THE] {detail_text}")
            target_signal_id = parent_signal_id or self.signal_repo.get_latest_pending_signal_id(chat_id)
            if target_signal_id and self.order_manager:
                sig_data = self.signal_repo.get_signal(target_signal_id)
                if sig_data:
                    symbol = sig_data["symbol"]
                    try:
                        pos = await self.order_manager.client.get_position(symbol)
                        amt = Decimal(str(pos.get("positionAmt", 0))) if pos else Decimal("0")
                        if amt != Decimal("0"):
                            await self.order_manager.position_manager.execute_emergency_close(
                                symbol=symbol,
                                quantity=abs(amt),
                                side=PositionSide.LONG if amt > 0 else PositionSide.SHORT,
                                signal_id=target_signal_id,
                            )
                            self.signal_repo.update_signal_state(target_signal_id, SignalState.CLOSED, reason="Admin yêu cầu đóng toàn bộ vị thế")
                            self.signal_repo.record_timeline_event(target_signal_id, "ADMIN_CLOSE_ALL", "Đã đóng toàn bộ vị thế theo lệnh Admin Telegram")
                            print(f"[DA DONG VI THE] Đã đóng toàn bộ vị thế {symbol} theo yêu cầu admin.")
                    except Exception as ex_close:
                        print(f"[CANH BAO] Khong the dong vi the theo tin admin: {ex_close}")

        # In Shadow Mode or READ_ONLY mode: Output conditional evaluation for admin updates
        if (self.is_shadow or self.config.mode == ExecutionMode.READ_ONLY) and update_type != UpdateType.UNKNOWN:
            print("\n" + "=" * 60)
            print("[SHADOW MODE: DANH GIA CAP NHAT ADMIN]")
            print(f"- Admin yeu cau: {detail_text}")
            print(f"- Thuoc keo: {parent_signal_id or 'Chua xac dinh duoc keo goc'}")
            print(f"- Bang chung lien ket: {'Reply den Msg #' + str(reply_to_msg_id) if reply_to_msg_id else 'Khong co reply (unlinked)'}")
            print(f"- Thieu du lieu: Trang thai vi the thuc te tren san Binance")
            print(f"- Trang thai tai khoan Binance: UNKNOWN (Chua ket noi Live)")
            if parent_signal_id:
                print(f"- De xuat co dieu kien: Neu dang co vi the cua keo {parent_signal_id}, de xuat thuc hien {update_type.value}. Hien tai CHUA GUI LENH.")
            else:
                print(f"- De xuat co dieu kien: Can nguoi dung xac nhan keo lien quan truoc khi thuc hien. CHUA GUI LENH.")
            print("=" * 60 + "\n")
            if update_type in [UpdateType.RESULT_TP_REPORTED, UpdateType.CORRECT_SIGNAL, UpdateType.CANCEL_PENDING_ENTRY, UpdateType.ENTRY_CHANGE]:
                return

        if update_type in [UpdateType.RESULT_TP_REPORTED, UpdateType.CORRECT_SIGNAL, UpdateType.CANCEL_PENDING_ENTRY, UpdateType.ENTRY_CHANGE]:
            return

        # 5b. Anti-Revenge Trading Cool-off check (90 minutes after an SL hit)
        if not is_edit:
            last_sl_t = self._last_sl_timestamp_by_chat.get(chat_id, 0.0)
            elapsed_sl = time.time() - last_sl_t
            if elapsed_sl < 5400:  # 90 minutes
                rem_mins = int((5400 - elapsed_sl) / 60)
                print(f"[BI CHAN: ANTI-REVENGE COOLOFF] Chat ID: {chat_id} | Msg: {msg_id} bi chan: Kenh vua co keo dinh SL cach day {int(elapsed_sl/60)} phut (con dong bang {rem_mins} phut de tranh bay cay cu tra thu).")
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

        # If this is an edit of an existing active signal: check SL and Entry change rules
        if is_edit:
            existing_sig = (
                self.signal_repo.get_signal_by_message(chat_id, msg_id)
                or self.signal_repo.get_active_signal_for_symbol(parsed.symbol_candidate or "")
            )
            if existing_sig:
                old_state = existing_sig.get("state")
                symbol = existing_sig["symbol"]

                # 1. If Entry price was edited while order is still PENDING on Binance
                if old_state == SignalState.ENTRY_PENDING.value and parsed.entries:
                    old_entries = existing_sig.get("entries") or []
                    new_entries = parsed.entries or []
                    if new_entries != old_entries:
                        print(f"\n[EDIT ENTRY: SUA GIA VAO KHI CHUA KHOP] Kèo {symbol}: Giá cũ {old_entries} -> Giá mới {new_entries}")
                        if not self._entry_enabled():
                            self.signal_repo.record_timeline_event(
                                existing_sig["signal_id"],
                                "ENTRY_EDIT_BLOCKED_ENTRY_DISABLED",
                                "Đã tạm dừng nhận lệnh mới; giữ nguyên lệnh Entry đang chờ.",
                            )
                        elif self.order_manager and exchange_writes_enabled(self.config):
                            try:
                                await self.order_manager.cancel_pending_entries_for_signal(existing_sig["signal_id"], symbol)
                                self.signal_repo.record_timeline_event(
                                    existing_sig["signal_id"],
                                    "ENTRY_EDITED_REPLACING_ORDERS",
                                    f"Admin sửa giá vào khi lệnh chưa khớp. Đã hủy lệnh cũ ({old_entries}) và đặt lại lệnh mới ({new_entries}).",
                                )
                                source_override = self.config.sources.get(chat_id)
                                parsed.signal_id = existing_sig["signal_id"]
                                parsed, validated = self.validator.validate_and_resolve(parsed, source_override)
                                if validated:
                                    client = self.order_manager.client
                                    filters = await client.get_symbol_filter(validated.symbol)
                                    equity = await client.get_account_equity()
                                    ticker = await client._request("GET", "/fapi/v1/ticker/price", params={"symbol": validated.symbol})
                                    current_price = Decimal(ticker.get("price", "0"))
                                    entry_sizes = self.order_manager.risk_engine.calculate_position_sizes(
                                        signal=validated,
                                        current_equity=equity,
                                        open_risk_amount=Decimal("0.0"),
                                        step_size=filters.step_size,
                                        min_qty=filters.min_qty,
                                        min_notional=filters.min_notional,
                                        current_market_price=current_price,
                                    )
                                    orders = await self.order_manager.submit_entries(validated, entry_sizes, current_market_price=current_price)
                                    print(f"[DA CAP NHAT ENTRY MOI TREN SAN] Đã đặt lại {len(orders)} lệnh mới theo giá admin đã sửa ({new_entries}).")
                            except Exception as e_edit_entry:
                                print(f"[CANH BAO] Khong the thay doi lenh entry tren san: {e_edit_entry}")

                elif old_state in (SignalState.OPEN_PROTECTED.value, SignalState.PARTIALLY_FILLED.value) and parsed.entries:
                    old_entries = existing_sig.get("entries") or []
                    new_entries = parsed.entries or []
                    if new_entries != old_entries:
                        print(f"[CANH BAO] Admin sửa giá Entry trong tin nhắn nhưng vị thế trên Binance ĐÃ KHỚP THỰC TẾ (FILLED). Không thể thay đổi giá đã khớp.")
                        self.signal_repo.record_timeline_event(
                            existing_sig["signal_id"],
                            "ENTRY_EDIT_IGNORED_ALREADY_FILLED",
                            f"Admin sửa entry thành {new_entries} nhưng vị thế đã khớp trên Binance. Giữ nguyên vị thế thực.",
                        )

                # 2. Check Stop Loss changes
                if parsed.stop_loss and existing_sig.get("stop_loss"):
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
                    elif new_sl != old_sl:
                        # Valid tightening of SL!
                        print(f"[EDIT HOP LE: SIET SL GIAM RUI RO] SL cu: {old_sl} -> SL moi: {new_sl}")
                        self.signal_repo.record_timeline_event(
                            existing_sig["signal_id"],
                            "ACCEPT_SL_TIGHTENING",
                            f"Chap nhan siet SL tu {old_sl} ve {new_sl}",
                        )
                        # Persist new tightened SL into DB immediately
                        with self.signal_repo.db.get_connection() as conn:
                            conn.execute(
                                "UPDATE signals SET stop_loss = ?, updated_at = ? WHERE signal_id = ?",
                                (str(new_sl), datetime.utcnow().isoformat(), existing_sig["signal_id"]),
                            )
                        # Update SL on exchange if active
                        if self.order_manager and exchange_writes_enabled(self.config):
                            try:
                                pos = await self.order_manager.client.get_position(parsed.symbol_candidate)
                                amt = Decimal(str(pos.get("positionAmt", 0))) if pos else Decimal("0")
                                if amt != Decimal("0"):
                                    sl_side = OrderSide.SELL if side == PositionSide.LONG else OrderSide.BUY
                                    new_sl_cid = f"sl_{existing_sig['signal_id'][:8]}_{uuid.uuid4().hex[:4]}"
                                    resp = await self.order_manager.client.create_algo_order(
                                        symbol=parsed.symbol_candidate,
                                        side=sl_side,
                                        order_type=OrderType.STOP_MARKET,
                                        trigger_price=new_sl,
                                        quantity=abs(amt),
                                        client_algo_id=new_sl_cid,
                                    )
                                    old_algos = await self.order_manager.client.get_open_algo_orders(parsed.symbol_candidate)
                                    owned_ids = {
                                        o.client_order_id
                                        for o in self.order_repo.get_orders_for_signal(existing_sig["signal_id"])
                                        if o.is_algo and o.is_reduce_only and o.client_order_id != new_sl_cid
                                    }
                                    for oa in (old_algos or []):
                                        cid = oa.get("clientAlgoId")
                                        if cid in owned_ids:
                                            await self.order_manager.client.cancel_algo_order(parsed.symbol_candidate, client_algo_id=cid)
                                    print(f"[DA CAP NHAT SL TREN SAN] Da cap nhat SL moi ({new_sl}) thanh cong tren Binance.")
                            except Exception as ex_sl:
                                print(f"[CANH BAO] Khong the cap nhat SL tren san: {ex_sl}")
                return

        # 7. Validate & Resolve Policies
        if not parsed.symbol_candidate or parsed.symbol_candidate == "UNKNOWN":
            return  # Silently skip non-signal messages (greetings, reactions, links without pair)

        # Filter out obvious marketing bait, brag/result announcements, or messages without any prices
        if parsed.validation_status == SignalState.REJECTED and any(
            k in (parsed.blocking_reason or "").lower() for k in ["tin nhan cau keo", "bao cao ket qua", "trade result", "lua dao", "khoe lai"]
        ):
            print(f"[BO QUA TIN RAC / QUANG CAO] {parsed.blocking_reason} (Chat: {chat_id}, Msg: {msg_id})")
            return

        # Teaser / link bait without entries and without SL: Do not pollute signals table
        if not parsed.entries and not parsed.stop_loss:
            print(f"[BO QUA TIN KHONG CO GIA] Chat {chat_id} Msg {msg_id} symbol {parsed.symbol_candidate} thieu ca Entry va SL (teaser/spam). Khong ghi vao bang tin hieu.")
            return

        self.signal_repo.save_signal(parsed)
        source_override = self.config.sources.get(chat_id)
        parsed, validated = self.validator.validate_and_resolve(parsed, source_override)
        self.signal_repo.save_signal(parsed)

        if event_bus:
            try:
                asyncio.create_task(event_bus.publish("signal_created", {
                    "signal_id": parsed.signal_id,
                    "symbol": parsed.symbol_candidate,
                    "state": parsed.validation_status.value,
                }))
            except Exception:
                pass

        # 8. Report Status in Vietnamese without accents
        status = parsed.validation_status
        if status == SignalState.REJECTED:
            print(f"[BI CHAN: {parsed.blocking_reason}]")
            # Admin Format Shift Watchdog
            has_explicit_dir = bool(re.search(r"\b(LONG|SHORT|BUY|SELL)\b", raw_text, re.IGNORECASE))
            if has_explicit_dir and any(k in str(parsed.blocking_reason).lower() for k in ["take profit", "stop loss", "entry"]):
                print(f"[CANH BAO CU PHAP ADMIN] Nhóm: {chat_id} (Msg #{msg_id}) | Symbol: {parsed.symbol_candidate} | Lý do: {parsed.blocking_reason}")
                print(f"-> Khuyến nghị kiểm tra định dạng tin nhắn admin: {raw_text[:120].strip()}...")
            if self.is_shadow or self.config.mode == ExecutionMode.READ_ONLY:
                print("\n" + "=" * 60)
                print(f"[SHADOW MODE: TIN HIEU BI CHAN - REJECTED]")
                print(f"- Nguyen nhan: {parsed.blocking_reason or 'Vi pham tieu chuan hop le'}")
                print(f"- Hanh dong: Chan hoan toan, khong tiep nhan.")
                print("=" * 60 + "\n")
            return
        elif status == SignalState.NEEDS_REVIEW:
            print(f"[CHO XAC NHAN] {parsed.blocking_reason}")
            if self.is_shadow or self.config.mode == ExecutionMode.READ_ONLY:
                print("\n" + "=" * 60)
                print(f"[SHADOW MODE: TIN HIEU CAN DANH GIA - NEEDS_REVIEW]")
                print(f"- Nguyen nhan: {parsed.blocking_reason}")
                print(f"- Hanh dong: Cho nguoi dung xac nhan cach hieu, khong vao lenh.")
                print("=" * 60 + "\n")
            return
        elif status == SignalState.NEEDS_POLICY:
            print(f"[CHO CAU HINH] {parsed.blocking_reason}")
            if self.is_shadow or self.config.mode == ExecutionMode.READ_ONLY:
                print("\n" + "=" * 60)
                print(f"[SHADOW MODE: TIN HIEU CHO CHINH SACH - NEEDS_POLICY]")
                print(f"- Nguyen nhan: {parsed.blocking_reason}")
                print(f"- Hanh dong: Cho nguoi dung bo sung policy trong config.yaml, khong vao lenh.")
                print("=" * 60 + "\n")
            return
        elif status == SignalState.VALIDATED:
            if not self._entry_enabled():
                reason = "Đã tạm dừng nhận lệnh mới; tín hiệu được lưu nhưng không gửi lệnh."
                print(f"[CHAN ENTRY] {reason}")
                self.signal_repo.record_timeline_event(validated.signal_id, "ENTRY_DISABLED", reason)
                return
            if self.is_shadow or not exchange_writes_enabled(self.config):
                reason = f"Chế độ {self.config.mode.value} không cho phép gửi lệnh sàn."
                print(f"[CHAN MODE] {reason}")
                self.signal_repo.record_timeline_event(validated.signal_id, "EXCHANGE_WRITE_BLOCKED", reason)
                return

            # If signal arrived late: Smart viability evaluation (Admin updates + Binance market price)
            if is_stale_signal:
                can_enter, eval_reason = await self._evaluate_late_signal_viability(
                    validated=validated,
                    chat_id=chat_id,
                    msg_id=msg_id,
                    age_seconds=age_seconds,
                )
                if not can_enter:
                    parsed.validation_status = SignalState.REJECTED
                    parsed.blocking_reason = eval_reason
                    self.signal_repo.save_signal(parsed)
                    self.signal_repo.record_timeline_event(
                        parsed.signal_id,
                        "SIGNAL_EXPIRED",
                        eval_reason,
                    )
                    print(f"[BI CHAN KEO TRE: {eval_reason}]. Khong dat lenh.")
                    return
                else:
                    self.signal_repo.record_timeline_event(
                        validated.signal_id,
                        "LATE_ENTRY_APPROVED",
                        eval_reason,
                    )
                    print(f"\n{'='*60}\n[DUYET VAO LENH KEO TRE] {eval_reason}\n{'='*60}\n")

            channel_name = KNOWN_CHANNELS.get(chat_id, f"Kênh {chat_id}")
            print(f"\n[DA XAC THUC TIN HIEU] Nhóm: {channel_name} | Coin: {validated.symbol} | Hướng: {validated.side.value} | SL: {validated.stop_loss} | Leverage: {validated.leverage}x")

            self.signal_repo.record_timeline_event(
                validated.signal_id,
                "SIGNAL_VALIDATED",
                f"Tín hiệu xác thực từ nhóm {channel_name}: {validated.symbol} {validated.side.value}",
            )

            if self.is_shadow or self.config.mode == ExecutionMode.READ_ONLY:
                print("\n" + "=" * 60)
                print(f"[SHADOW MODE: TIN HIEU HOP LE TU NHOM {channel_name}]")
                print(f"- Coin: {validated.symbol} | Chiều: {validated.side.value}")
                print(f"- Entry: {validated.entries} | SL: {validated.stop_loss} | TP: {len(validated.take_profits)} mức")
                print(f"- Đòn bẩy đề xuất: {validated.leverage}x (ISOLATED)")
                print(f"- Trạng thái: READ_ONLY (Chưa gửi lệnh thực tế).")
                print("=" * 60 + "\n")
                return

            if self.order_manager and exchange_writes_enabled(self.config):
                if self.config.mode == ExecutionMode.LIVE and not self.config.live_trading_enabled:
                    print(f"\n{'='*60}")
                    print(f"[CHAN LENH LIVE: GIAO DICH LIVE DANG TAT] Kèo {validated.symbol} từ '{channel_name}' bị chặn vì 'Giao dịch Live' chưa được bật.")
                    print(f"-> Vui lòng vào Cài Đặt bật 'Kích hoạt Giao dịch Live' và bấm 'Lưu Cài Đặt'.")
                    print(f"{'='*60}\n")
                    self.signal_repo.record_timeline_event(
                        validated.signal_id,
                        "LIVE_TRADING_DISABLED",
                        "Chế độ LIVE nhưng công tắc 'Kích hoạt Giao Dịch Live' đang tắt. Lệnh không được gửi ra sàn để bảo vệ an toàn.",
                    )
                    return

                try:
                    client = self.order_manager.client
                    filters = await client.get_symbol_filter(validated.symbol)
                    equity = await client.get_account_equity()

                    # 0b. Trụ Cột 2: Circuit Breaker Auto-Mute Check (3 consecutive SLs in 48h)
                    is_cb, cb_msg = self.analytics_service.check_circuit_breaker(chat_id)
                    if is_cb:
                        print(f"\n[CIRCUIT BREAKER: TAM DUNG TRADE REAL] Nhóm: {channel_name} | {cb_msg}")
                        self.signal_repo.record_timeline_event(
                            validated.signal_id,
                            "CIRCUIT_BREAKER_MUTED",
                            cb_msg,
                        )
                        print(f"-> Chuyển sang chế độ Paper/Shadow để thẩm định lại, không gửi lệnh sàn thực tế.\n")
                        return

                    # 1. Fetch live open positions from Binance
                    try:
                        open_positions = await client.get_open_positions()
                    except Exception as exc:
                        reason = f"Không thể xác minh vị thế hiện tại: {exc}. Chặn gửi lệnh để tránh tính sai rủi ro."
                        self.signal_repo.record_timeline_event(validated.signal_id, "POSITION_CHECK_FAILED", reason)
                        self.signal_repo.update_signal_state(validated.signal_id, SignalState.ERROR, reason)
                        return

                    # 2. Check Chart Trend & Market Context (1h EMA20 trend, 24h change, funding rate, BTC context)
                    market_ctx = {}
                    if hasattr(client, "get_market_trend_context"):
                        try:
                            market_ctx = await client.get_market_trend_context(validated.symbol)
                        except Exception:
                            pass

                    # 2b. Trụ Cột 1: Correlation Shield & BTC 4H Market Regime Filter
                    try:
                        if hasattr(client, "_request"):
                            await global_market_regime_shield.update_regime(client)
                        regime_allowed, regime_reason = global_market_regime_shield.check_signal_allowed(
                            validated.symbol, validated.side
                        )
                        if not regime_allowed:
                            print(f"\n[BI CHAN: BTC MARKET REGIME DUMP] {regime_reason}\n")
                            self.signal_repo.record_timeline_event(
                                validated.signal_id,
                                "MARKET_REGIME_BLOCKED",
                                regime_reason,
                            )
                            self.signal_repo.update_signal_state(
                                validated.signal_id, SignalState.REJECTED, regime_reason
                            )
                            return
                    except Exception as e:
                        print(f"[CANH BAO] Loi kiem tra market regime: {e}")

                    # 2c. Trụ Cột 5: Liquidity & Funding Rate Filter (/fapi/v1/premiumIndex)
                    funding_val = market_ctx.get("funding_rate", 0.0)
                    vol_24 = market_ctx.get("volume_24h", 0.0)
                    is_liq_ok, liq_err = SignalValidator.validate_funding_and_liquidity(
                        funding_rate=funding_val,
                        quote_volume_24h=vol_24,
                    )
                    if not is_liq_ok:
                        reject_reason = f"Trụ cột 5 chặn lệnh: {liq_err}."
                        print(f"\n[BI CHAN: FUNDING HOAC THANH KHOAN] {reject_reason}\n")
                        self.signal_repo.record_timeline_event(
                            validated.signal_id,
                            "LIQUIDITY_FUNDING_BLOCKED",
                            reject_reason,
                        )
                        self.signal_repo.update_signal_state(
                            validated.signal_id, SignalState.REJECTED, reject_reason
                        )
                        return

                    # 3. TÌNH HUỐNG 1: BẢO VỆ XUNG ĐỘT TRÙNG CẶP (DUPLICATE SYMBOL PROTECTION)
                    existing_pos = next((p for p in open_positions if p.get("symbol") == validated.symbol and Decimal(str(p.get("positionAmt", "0"))) != Decimal("0")), None)
                    existing_sig = self.signal_repo.get_active_signal_for_symbol(validated.symbol)

                    if existing_pos or existing_sig:
                        pos_amt = Decimal(str(existing_pos.get("positionAmt", "0"))) if existing_pos else Decimal("0")
                        if pos_amt != Decimal("0"):
                            pos_side = PositionSide.LONG if pos_amt > Decimal("0") else PositionSide.SHORT
                        else:
                            pos_side = PositionSide(existing_sig["side"]) if existing_sig and existing_sig.get("side") in (PositionSide.LONG.value, PositionSide.SHORT.value) else validated.side

                        trend_str = market_ctx.get("trend_1h", "NEUTRAL")
                        chg_24 = market_ctx.get("change_24h", 0.0)
                        funding = market_ctx.get("funding_rate", 0.0)
                        btc_chg = market_ctx.get("btc_change_24h", 0.0)

                        # Subcase A: Conflicting direction (Opposite) -> Strictly reject to protect One-Way mode
                        if pos_side != validated.side:
                            reject_reason = (
                                f"Đang có vị thế {validated.symbol} {pos_side.value} mở trên sàn. "
                                f"Từ chối tín hiệu {validated.side.value} từ nhóm '{channel_name}' để bảo vệ vị thế và tránh xung đột One-Way mode. "
                                f"[Chart 1h: {trend_str}, 24h: {chg_24:+.2f}%, Funding: {funding*100:.3f}%, BTC 24h: {btc_chg:+.2f}%]"
                            )
                            print(f"\n[TỪ CHỐI TÍN HIỆU NGƯỢC CHIỀU] {reject_reason}\n")
                            self.signal_repo.record_timeline_event(validated.signal_id, "DUPLICATE_OPPOSITE_SYMBOL_REJECTED", reject_reason)
                            self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, reject_reason)
                            return

                        # Subcase B: Same direction -> Check if existing position has hit TP1 (Risk-Free)
                        existing_timeline = self.signal_repo.get_timeline(existing_sig["signal_id"]) if existing_sig else []
                        is_existing_be = any(e.get("event_type") in ("BREAKEVEN_SL_ACTIVATED", "BREAKEVEN_ACTIVATED", "TP1_TRIGGERED") for e in existing_timeline)
                        if not is_existing_be:
                            reject_reason = (
                                f"Đang có vị thế {validated.symbol} {pos_side.value} chưa chốt TP1 (đang chịu rủi ro). "
                                f"Từ chối nhồi thêm lệnh trùng cặp để tránh đội rủi ro kép. "
                                f"[Chart 1h: {trend_str}, 24h: {chg_24:+.2f}%, Funding: {funding*100:.3f}%, BTC 24h: {btc_chg:+.2f}%]"
                            )
                            print(f"\n[TỪ CHỐI NHỒI LỆNH TRÙNG CẶP] {reject_reason}\n")
                            self.signal_repo.record_timeline_event(validated.signal_id, "DUPLICATE_SAME_SYMBOL_REJECTED", reject_reason)
                            self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, reject_reason)
                            return
                        else:
                            print(f"[THÔNG TIN TRÙNG CẶP] Vị thế {validated.symbol} {pos_side.value} cũ đã đạt TP1 / Kèo Bất Tử. Đang thẩm định theo dõi thêm.")

                    # 4. TÌNH HUỐNG 2: DYNAMIC RISK-FREE SLOT FREEING & ADMIN VIP PRIORITY
                    at_risk_count = 0
                    risk_free_count = 0
                    for p in open_positions:
                        sym = p.get("symbol")
                        sig = self.signal_repo.get_active_signal_for_symbol(sym)
                        t_events = self.signal_repo.get_timeline(sig["signal_id"]) if sig else []
                        if any(e.get("event_type") in ("BREAKEVEN_SL_ACTIVATED", "BREAKEVEN_ACTIVATED", "TP1_TRIGGERED") for e in t_events):
                            risk_free_count += 1
                        else:
                            at_risk_count += 1

                    source_cfg = self.config.sources.get(chat_id)
                    is_elite_admin = chat_id in (-1001756316676, -1002052872813, -1001754095061, -1002007658025, -1001552004524)
                    is_ferrari = getattr(self.config, "ferrari_mode_enabled", False)
                    if is_ferrari:
                        max_allowed_at_risk = int(getattr(self.config.risk, "max_active_signals", 20))
                    else:
                        max_allowed_at_risk = min(int(getattr(self.config.risk, "max_active_signals", 3)), 5)

                    # Hard Ceiling: Tong so vi the dong thoi tren Binance khong bao gio vuot qua tran toi da (5)
                    total_open_positions = len(open_positions)
                    is_tier1 = chat_id in (-1001520053536, -1002052872813, -1001598691683, -1001700314832)
                    if total_open_positions >= max_allowed_at_risk:
                        if is_tier1 or is_elite_admin:
                            enqueued = self.signal_queue.enqueue(
                                signal=validated,
                                chat_id=chat_id,
                                channel_name=channel_name,
                                priority=1,
                            )
                            if enqueued:
                                queue_msg = (
                                    f"Trụ Cột 6 Hàng Đợi Thông Minh: Kèo {validated.symbol} từ nhóm Tier 1 '{channel_name}' "
                                    f"được đưa vào hàng đợi ưu tiên (TTL 20 phút) do đạt trần {total_open_positions}/{max_allowed_at_risk} vị thế."
                                )
                                print(f"\n[SMART QUEUE ENQUEUED] {queue_msg}\n")
                                self.signal_repo.record_timeline_event(validated.signal_id, "QUEUED_WAITING_FOR_SLOT", queue_msg)
                                return

                        slot_reject_reason = (
                            f"Danh mục đã đạt trần tối đa {total_open_positions}/{max_allowed_at_risk} vị thế đồng thời trên Binance. "
                            f"Kèo {validated.symbol} từ '{channel_name}' tạm hoãn để bảo toàn ký quỹ."
                        )
                        print(f"\n[QUẢN LÝ TRẦN VỊ THẾ] {slot_reject_reason}\n")
                        self.signal_repo.record_timeline_event(validated.signal_id, "MAX_CONCURRENT_POSITIONS_REACHED", slot_reject_reason)
                        self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, slot_reject_reason)
                        return

                    if not is_ferrari and at_risk_count >= max_allowed_at_risk and not is_elite_admin:
                        if is_tier1:
                            enqueued = self.signal_queue.enqueue(
                                signal=validated,
                                chat_id=chat_id,
                                channel_name=channel_name,
                                priority=1,
                            )
                            if enqueued:
                                queue_msg = (
                                    f"Trụ Cột 6 Hàng Đợi Thông Minh: Kèo {validated.symbol} từ nhóm Tier 1 '{channel_name}' "
                                    f"được đưa vào hàng đợi ưu tiên (TTL 20 phút) chờ nhả slot rủi ro."
                                )
                                print(f"\n[SMART QUEUE ENQUEUED] {queue_msg}\n")
                                self.signal_repo.record_timeline_event(validated.signal_id, "QUEUED_WAITING_FOR_SLOT", queue_msg)
                                return

                        slot_reject_reason = (
                            f"Danh mục đã đạt tối đa {at_risk_count} vị thế đang chịu rủi ro "
                            f"(Đã có {risk_free_count} vị thế đạt Kèo Bất Tử giải phóng slot). "
                            f"Kèo Scalp {validated.symbol} từ '{channel_name}' tạm hoãn để bảo toàn vốn. "
                            f"Slot sẽ tự động mở lại ngay khi có 1 vị thế chạm TP1!"
                        )
                        print(f"\n[QUẢN LÝ SLOT RỦI RO] {slot_reject_reason}\n")
                        self.signal_repo.record_timeline_event(validated.signal_id, "RISK_SLOT_LIMIT_REACHED", slot_reject_reason)
                        self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, slot_reject_reason)
                        return
                    elif at_risk_count >= max_allowed_at_risk and (is_elite_admin or is_ferrari):
                        print(f"[VIP/FERRARI PRIORITY] Kèo {validated.symbol} từ '{channel_name}' được ưu tiên đặc cách vào lệnh!")

                    # 5. MARKET TREND & NEWS SANITY CHECK
                    if market_ctx.get("market_status") == "BTC_HIGH_VOLATILITY_DUMP" and validated.side == PositionSide.LONG:
                        print(f"[CẢNH BÁO THỊ TRƯỜNG BIẾN ĐỘNG MẠNH] BTC đang sụt giảm mạnh ({market_ctx.get('btc_change_24h'):+.2f}%). Thận trọng với kèo LONG {validated.symbol}.")
                        self.signal_repo.record_timeline_event(
                            validated.signal_id,
                            "MARKET_VOLATILITY_WARNING",
                            f"Cảnh báo: BTC đang dump mạnh ({market_ctx.get('btc_change_24h'):+.2f}%). Lệnh vẫn được gửi nhưng kèm chặt bảo vệ SL.",
                        )

                    open_risk = Decimal("0.0")
                    for position in open_positions:
                        position_amt = abs(Decimal(str(position.get("positionAmt", "0"))))
                        entry_price = Decimal(str(position.get("entryPrice", "0")))
                        active_signal_for_position = self.signal_repo.get_active_signal_for_symbol(str(position.get("symbol", "")))
                        position_sl = (
                            Decimal(str(active_signal_for_position.get("stop_loss", "0")))
                            if active_signal_for_position and active_signal_for_position.get("stop_loss")
                            else Decimal("0")
                        )
                        if position_amt > 0 and entry_price > 0 and position_sl > 0:
                            # Clamp SL distance to max 15% to prevent corrupted database records from inflating open_risk
                            sl_dist = min(abs(entry_price - position_sl), entry_price * Decimal("0.15"))
                            open_risk += position_amt * sl_dist

                    ticker = await client._request("GET", "/fapi/v1/ticker/price", params={"symbol": validated.symbol})
                    current_price = Decimal(ticker.get("price", "0"))

                    entry_prices = [e[0] for e in validated.entries]
                    zone_min, zone_max = validated.entry_range if validated.entry_range else (min(entry_prices), max(entry_prices))

                    # Guard: Check market conditions, In-Zone Entry, and Anti-Chase Price Drift
                    if current_price > Decimal("0"):
                        tick = filters.tick_size if filters and filters.tick_size else Decimal("0.0001")

                        if validated.side == PositionSide.LONG:
                            # 1. TP1 Already Reached Check
                            if validated.take_profits and current_price >= validated.take_profits[0][0]:
                                print(f"[CHAN LENH: GIA DA DAT TP1] Keo {validated.symbol} gia thi truong ({current_price}) da dat TP1 ({validated.take_profits[0][0]}). Khong mua duoi.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã đạt hoặc vượt TP1 ({validated.take_profits[0][0]}). Chặn mua đuổi đỉnh.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm TP1 trước khi đặt lệnh, không mua đuổi")
                                return

                            # 2. Stop Loss Breach Check
                            if validated.stop_loss and current_price <= validated.stop_loss:
                                print(f"[CHAN LENH: GIA DA THUNG SL] Keo {validated.symbol} gia thi truong ({current_price}) da cham/thung SL ({validated.stop_loss}). Khong vao lenh.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã chạm/thủng Stop Loss ({validated.stop_loss}). Chặn vào lệnh bảo vệ tài khoản.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm hoặc thủng Stop Loss trước khi đặt lệnh")
                                return

                            # 3. Entry Evaluation for LONG:
                            # Case A: Market price is INSIDE entry range [zone_min, zone_max]
                            if zone_min <= current_price <= zone_max:
                                rounded_entry = (current_price // tick) * tick
                                validated.entries = [(rounded_entry, Decimal("1.0"))]
                                print(f"[KHỚP LỆNH TRONG VÙNG ENTRY] Giá thị trường {validated.symbol} ({current_price}) nằm trong khoảng Entry [{zone_min} - {zone_max}]. Khớp ngay tại {rounded_entry}!")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "ENTRY_IN_ZONE_MATCH",
                                    f"Giá thị trường ({current_price}) nằm trong khoảng Entry [{zone_min} - {zone_max}]. Khớp lệnh trực tiếp tại {rounded_entry}.",
                                )

                            # Case B: Market price is BELOW entry range (pullback discount, price < zone_min, price > SL)
                            elif current_price < zone_min:
                                rounded_entry = (current_price // tick) * tick
                                validated.entries = [(rounded_entry, Decimal("1.0"))]
                                print(f"[VÀO LỆNH GIÁ TỐT HƠN VÙNG ENTRY] Giá thị trường {validated.symbol} ({current_price}) < Vùng Entry [{zone_min} - {zone_max}]. Khớp ngay tại {rounded_entry}!")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "DISCOUNTED_ENTRY_MATCH",
                                    f"Giá thị trường ({current_price}) thấp hơn vùng Entry [{zone_min} - {zone_max}] (giá mua tốt hơn). Khớp ngay tại {rounded_entry}.",
                                )

                            # Case C: Market price is ABOVE entry range (price > zone_max)
                            else:
                                drift_pct = (current_price - zone_max) / zone_max * Decimal("100")
                                if drift_pct > Decimal("1.0"):
                                    print(f"[CHAN LENH: ANTI-CHASE FOMO] Keo {validated.symbol} gia ({current_price}) da tang qua Vung Entry ({zone_max}) +{drift_pct:.2f}%. Khong mua duoi.")
                                    self.signal_repo.record_timeline_event(
                                        validated.signal_id,
                                        "PRICE_DRIFT_EXCEEDED",
                                        f"Giá thị trường ({current_price}) đã tăng quá vùng Entry [{zone_min} - {zone_max}] +{drift_pct:.2f}%. Chặn mua đuổi đỉnh.",
                                    )
                                    self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, f"Giá đã tăng quá vùng Entry +{drift_pct:.2f}%, chặn mua đuổi")
                                    return
                                else:
                                    rounded_entry = (current_price // tick) * tick
                                    validated.entries = [(rounded_entry, Decimal("1.0"))]
                                    print(f"[VÀO LỆNH CẬN VÙNG ENTRY] Giá thị trường {validated.symbol} ({current_price}) sát trần Entry ({zone_max}) (+{drift_pct:.2f}% <= 1.0%). Khớp ngay tại {rounded_entry}!")
                                    self.signal_repo.record_timeline_event(
                                        validated.signal_id,
                                        "NEAR_ENTRY_MATCH",
                                        f"Giá thị trường ({current_price}) sát trần Entry [{zone_min} - {zone_max}] (+{drift_pct:.2f}%). Khớp tại {rounded_entry}.",
                                    )

                        elif validated.side == PositionSide.SHORT:
                            # 1. TP1 Already Reached Check
                            if validated.take_profits and current_price <= validated.take_profits[0][0]:
                                print(f"[CHAN LENH: GIA DA DAT TP1] Keo {validated.symbol} gia thi truong ({current_price}) da dat TP1 ({validated.take_profits[0][0]}). Khong ban duoi.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã đạt hoặc thấp hơn TP1 ({validated.take_profits[0][0]}). Chặn bán đuổi đáy.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm TP1 trước khi đặt lệnh, không bán đuổi")
                                return

                            # 2. Stop Loss Breach Check
                            if validated.stop_loss and current_price >= validated.stop_loss:
                                print(f"[CHAN LENH: GIA DA VUOT SL] Keo {validated.symbol} gia thi truong ({current_price}) da cham/vuot SL ({validated.stop_loss}). Khong vao lenh.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã chạm/vượt Stop Loss ({validated.stop_loss}). Chặn vào lệnh bảo vệ tài khoản.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm hoặc vượt Stop Loss trước khi đặt lệnh")
                                return

                            # 3. Entry Evaluation for SHORT:
                            # Case A: Market price is INSIDE entry range [zone_min, zone_max]
                            if zone_min <= current_price <= zone_max:
                                rounded_entry = (current_price // tick) * tick
                                validated.entries = [(rounded_entry, Decimal("1.0"))]
                                print(f"[KHỚP LỆNH TRONG VÙNG ENTRY] Giá thị trường {validated.symbol} ({current_price}) nằm trong khoảng Entry [{zone_min} - {zone_max}]. Khớp SHORT ngay tại {rounded_entry}!")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "ENTRY_IN_ZONE_MATCH",
                                    f"Giá thị trường ({current_price}) nằm trong khoảng Entry [{zone_min} - {zone_max}]. Khớp lệnh SHORT trực tiếp tại {rounded_entry}.",
                                )

                            # Case B: Market price is ABOVE entry range (pump discount, price > zone_max, price < SL)
                            elif current_price > zone_max:
                                rounded_entry = (current_price // tick) * tick
                                validated.entries = [(rounded_entry, Decimal("1.0"))]
                                print(f"[VÀO LỆNH GIÁ TỐT HƠN VÙNG ENTRY] Giá thị trường {validated.symbol} ({current_price}) > Vùng Entry [{zone_min} - {zone_max}]. Khớp SHORT ngay tại {rounded_entry}!")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "DISCOUNTED_ENTRY_MATCH",
                                    f"Giá thị trường ({current_price}) cao hơn vùng Entry [{zone_min} - {zone_max}] (giá bán tốt hơn). Khớp SHORT ngay tại {rounded_entry}.",
                                )

                            # Case C: Market price is BELOW entry range (price < zone_min)
                            else:
                                drift_pct = (zone_min - current_price) / zone_min * Decimal("100")
                                if drift_pct > Decimal("1.0"):
                                    print(f"[CHAN LENH: ANTI-CHASE FOMO] Keo {validated.symbol} gia ({current_price}) da giam qua Vung Entry ({zone_min}) -{drift_pct:.2f}%. Khong ban duoi.")
                                    self.signal_repo.record_timeline_event(
                                        validated.signal_id,
                                        "PRICE_DRIFT_EXCEEDED",
                                        f"Giá thị trường ({current_price}) đã giảm quá vùng Entry [{zone_min} - {zone_max}] -{drift_pct:.2f}%. Chặn bán đuổi đáy.",
                                    )
                                    self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, f"Giá đã giảm quá vùng Entry -{drift_pct:.2f}%, chặn bán đuổi")
                                    return
                                else:
                                    rounded_entry = (current_price // tick) * tick
                                    validated.entries = [(rounded_entry, Decimal("1.0"))]
                                    print(f"[VÀO LỆNH CẬN VÙNG ENTRY] Giá thị trường {validated.symbol} ({current_price}) sát đáy Entry ({zone_min}) (-{drift_pct:.2f}% <= 1.0%). Khớp SHORT ngay tại {rounded_entry}!")
                                    self.signal_repo.record_timeline_event(
                                        validated.signal_id,
                                        "NEAR_ENTRY_MATCH",
                                        f"Giá thị trường ({current_price}) sát đáy Entry [{zone_min} - {zone_max}] (-{drift_pct:.2f}%). Khớp SHORT tại {rounded_entry}.",
                                    )

                    try:
                        target_margin_mode = getattr(self.config.risk, "margin_mode", MarginMode.CROSSED)
                        if str(target_margin_mode).upper() in ("CROSS", "CROSSED"):
                            await client.set_margin_type_cross(validated.symbol)
                        else:
                            await client.set_margin_type_isolated(validated.symbol)
                    except Exception:
                        pass
                    try:
                        await client.set_leverage(validated.symbol, validated.leverage)
                    except Exception:
                        pass

                    # Trụ Cột 4: Apply ATR Volatility-Adjusted Sizing
                    atr_val = Decimal(str(market_ctx.get("atr_1h", 0.0)))
                    if atr_val > Decimal("0") and current_price > Decimal("0") and hasattr(self.order_manager, "risk_engine"):
                        validated = self.order_manager.risk_engine.apply_atr_volatility_sizing(
                            signal=validated,
                            atr_1h=atr_val,
                            current_price=current_price,
                        )

                    entry_sizes = self.order_manager.risk_engine.calculate_position_sizes(
                        signal=validated,
                        current_equity=equity,
                        open_risk_amount=open_risk,
                        step_size=filters.step_size,
                        min_qty=filters.min_qty,
                        min_notional=filters.min_notional,
                        current_market_price=current_price,
                    )

                    orders = await self.order_manager.submit_entries(validated, entry_sizes, current_market_price=current_price)
                    trade_mode_label = "TIỀN THẬT (LIVE)" if self.config.mode == ExecutionMode.LIVE else "DEMO (TESTNET)"
                    print(f"\n{'='*60}")
                    print(f"[TRADE {trade_mode_label} THANH CÔNG] Đã mở {len(orders)} lệnh cho kèo {validated.symbol} ({validated.side.value}) từ nhóm '{channel_name}'!")
                    print(f"- Khối lượng & Giá: {entry_sizes}")
                    print(f"- Đòn bẩy: {validated.leverage}x | Stoploss: {validated.stop_loss}")
                    print(f"{'='*60}\n")
                    self.signal_repo.record_timeline_event(
                        validated.signal_id,
                        "ORDERS_SUBMITTED",
                        f"Đã đặt {len(orders)} lệnh trên Binance ({self.config.mode.value}) từ nhóm {channel_name}",
                    )
                    if event_bus:
                        try:
                            asyncio.create_task(event_bus.publish("signal_updated", {
                                "signal_id": validated.signal_id,
                                "symbol": validated.symbol,
                                "state": SignalState.ENTRY_PENDING.value,
                            }))
                        except Exception:
                            pass
                except Exception as e:
                    err_msg = f"Lỗi gửi lệnh lên Binance: {str(e) or type(e).__name__}"
                    print(f"[LOI DAT LENH] Không thể gửi lệnh cho {validated.symbol}: {err_msg}")
                    self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, reason=err_msg)
                    self.signal_repo.record_timeline_event(
                        validated.signal_id,
                        "ORDER_SUBMISSION_FAILED",
                        err_msg,
                    )

    async def start(self) -> None:
        """Registers handlers and starts listening."""
        @self.tg_client.on(events.NewMessage)
        async def new_message_handler(event):
            try:
                await self.handle_incoming_message(event, is_edit=False)
            except Exception as e:
                print(f"[LOI XU LY TIN MOI] {e}")

        @self.tg_client.on(events.MessageEdited)
        async def message_edited_handler(event):
            try:
                await self.handle_incoming_message(event, is_edit=True)
            except Exception as e:
                print(f"[LOI XU LY TIN CHINH SUA] {e}")

        @self.tg_client.on(events.MessageDeleted)
        async def message_deleted_handler(event):
            deleted_ids = getattr(event, "deleted_ids", [])
            chat_id = getattr(event, "chat_id", None)
            now_str = datetime.utcnow().isoformat()
            for did in deleted_ids:
                print(f"\n[THONG TIN: TIN NHAN DA BI XOA] Chat ID: {chat_id or 'Chua ro'} | Msg ID: {did} da bi xoa boi admin/user tai {now_str}.")
                print(f"  -> Giu nguyen trang thai he thong. KHONG tu coi xoa tin la huy/dong keo.\n")
                if chat_id:
                    sig = self.signal_repo.get_signal_by_message(chat_id, did)
                    if sig:
                        self.signal_repo.record_timeline_event(
                            sig["signal_id"],
                            "MESSAGE_DELETED",
                            f"Tin nhan Msg ID #{did} da bi xoa boi admin tai {now_str}. Khong tu dong dong/huy keo.",
                        )

        print(f"\n[DA KET NOI TELEGRAM] Dang lang nghe tin hieu tu cac kenh duoc phep...")
        print(f"Che do hien tai: {self.config.mode.value} {'(SHADOW MODE)' if self.is_shadow else ''}")
        print(f"Danh sach chat_id theo doi: {self.config.telegram.allowed_chat_ids or 'Chua cau hinh (khong nhan kenh nao)'}")

        # Catch up recent messages (up to 15 minutes old) that arrived while bot was offline
        await self._startup_catchup_sync()

        # Start periodic background channel polling to always track admin edits and updates
        self._periodic_sync_task = asyncio.create_task(self._periodic_channel_sync())

        try:
            while not self._stop_requested:
                try:
                    await self.tg_client.run_until_disconnected()
                    if self._stop_requested:
                        break
                    if not self.tg_client.is_connected():
                        print("[TELEGRAM] Mat ket noi. Dang ket noi lai sau 3 giay...")
                        await asyncio.sleep(3)
                        await self.tg_client.connect()
                    else:
                        break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[TELEGRAM RECONNECT] {e}. Dang ket noi lai sau 5 giay...")
                    await asyncio.sleep(5)
                    try:
                        if not self.tg_client.is_connected():
                            await self.tg_client.connect()
                    except Exception:
                        pass
        finally:
            if self._periodic_sync_task and not self._periodic_sync_task.done():
                self._periodic_sync_task.cancel()

    async def stop(self) -> None:
        self._stop_requested = True
        if self._periodic_sync_task and not self._periodic_sync_task.done():
            self._periodic_sync_task.cancel()
        if self.tg_client.is_connected():
            await self.tg_client.disconnect()

    async def _evaluate_late_signal_viability(
        self,
        validated: ValidatedSignal,
        chat_id: int,
        msg_id: int,
        age_seconds: float,
    ) -> Tuple[bool, str]:
        """
        Smart evaluation for late signals (sent 5-35 minutes ago):
        1. Checks subsequent channel messages for admin updates (TP hit, SL hit, cancel).
        2. Queries live market price to verify if price is still safe inside entry boundary.
        """
        # Hard cap: If signal is older than 45 minutes (2700s), definitely reject
        if age_seconds > 2700:
            return False, f"Tín hiệu quá cũ (gửi cách đây {int(age_seconds / 60)} phút > 45 phút). Bỏ qua để an toàn vốn."

        symbol = validated.symbol
        side = validated.side

        # Step 1: Scan recent subsequent messages in this channel for updates regarding this coin
        try:
            with self.signal_repo.db.get_connection() as conn:
                newer_msgs = conn.execute(
                    """
                    SELECT raw_text FROM messages
                    WHERE chat_id = ? AND message_id > ?
                    ORDER BY message_id ASC LIMIT 25
                    """,
                    (chat_id, msg_id),
                ).fetchall()

            coin_core = symbol.replace("USDT", "")
            for row in newer_msgs:
                txt = (row[0] or "").lower()
                if coin_core.lower() in txt or "#" + coin_core.lower() in txt:
                    if any(kw in txt for kw in [
                        "tp1 hit", "target 1 hit", "all targets hit", "tp hit", "take profit",
                        "stoploss hit", "sl hit", "stoploss triggered", "closed", "cancel", "bỏ", "hủy"
                    ]):
                        return False, f"Admin đã cập nhật trạng thái mới cho {coin_core} ('{row[0][:50]}...'). Kèo đã hoàn tất hoặc đóng."
        except Exception:
            pass

        # Step 2: Check current Binance market price
        if not self.order_manager:
            return False, f"Tín hiệu đến trễ {int(age_seconds)}s và chưa kết nối sàn để kiểm tra giá."

        try:
            client = self.order_manager.client
            ticker = await client._request("GET", "/fapi/v1/ticker/price", params={"symbol": symbol})
            curr_p = Decimal(str(ticker.get("price", "0")))
            if curr_p <= Decimal("0"):
                return False, f"Không thể lấy giá thị trường thời gian thực của {symbol}."

            entry_prices = [e[0] for e in validated.entries]
            zone_min, zone_max = validated.entry_range if validated.entry_range else (min(entry_prices), max(entry_prices))
            sl = validated.stop_loss
            tp1 = validated.take_profits[0][0] if validated.take_profits else None

            if side == PositionSide.LONG:
                # If price already breached Stop Loss
                if sl and curr_p <= sl:
                    return False, f"Giá thị trường ({curr_p}) đã thủng Stop Loss ({sl}). Kèo đã thất bại."
                # If price already hit TP1
                if tp1 and curr_p >= tp1:
                    return False, f"Giá thị trường ({curr_p}) đã đạt/vượt TP1 ({tp1}). Không mua đuổi đỉnh."
                # If price is higher than zone_max by more than 1.0%
                if curr_p > zone_max * Decimal("1.010"):
                    return False, f"Giá thị trường ({curr_p}) đã tăng cao hơn vùng Entry ({zone_max}) > 1.0%. Bỏ qua."

                return True, (
                    f"Kèo {symbol} gửi trễ {int(age_seconds)}s nhưng thị giá ({curr_p}) vẫn nằm trong vùng Entry hợp lệ "
                    f"[{zone_min} - {zone_max}], chưa chạm TP1 ({tp1}) và trên SL ({sl}). Đủ điều kiện khớp bổ sung."
                )

            elif side == PositionSide.SHORT:
                # If price already breached Stop Loss
                if sl and curr_p >= sl:
                    return False, f"Giá thị trường ({curr_p}) đã vượt Stop Loss ({sl}). Kèo đã thất bại."
                # If price already hit TP1
                if tp1 and curr_p <= tp1:
                    return False, f"Giá thị trường ({curr_p}) đã đạt/thấp hơn TP1 ({tp1}). Không bán đuổi đáy."
                # If price is lower than zone_min by more than 1.0%
                if curr_p < zone_min * Decimal("0.990"):
                    return False, f"Giá thị trường ({curr_p}) đã giảm thấp hơn vùng Entry ({zone_min}) > 1.0%. Bỏ qua."

                return True, (
                    f"Kèo {symbol} gửi trễ {int(age_seconds)}s nhưng thị giá ({curr_p}) vẫn nằm trong vùng Entry hợp lệ "
                    f"[{zone_min} - {zone_max}], chưa chạm TP1 ({tp1}) và dưới SL ({sl}). Đủ điều kiện khớp bổ sung."
                )
        except Exception as ex_p:
            return False, f"Không thể xác minh thị giá {symbol} trên Binance ({ex_p}). Từ chối để bảo vệ vốn."

        return False, f"Tín hiệu quá hạn ({int(age_seconds)}s > {self.config.risk.signal_max_age_seconds}s)."

    async def _startup_catchup_sync(self):
        """
        When bot starts, checks recent messages in allowed channels sent within the last 30 minutes.
        If any valid trade signal arrived while the bot was offline and hasn't expired (or remains viable), processes it immediately.
        """
        try:
            allowed = self.config.telegram.allowed_chat_ids or []
            if not allowed:
                return
            now_utc = datetime.utcnow()
            print(f"[STARTUP SYNC] Đang rà soát tin nhắn trong 30 phút vừa qua trên {len(allowed)} kênh theo dõi...")
            for chat_id in allowed:
                try:
                    msgs = await self.tg_client.get_messages(chat_id, limit=10)
                    # Process ascending: oldest first
                    for m in reversed(msgs):
                        if not m:
                            continue
                        media_kind = detect_media_kind(m)
                        if not getattr(m, "raw_text", None) and not media_kind:
                            continue
                        msg_date = m.date.replace(tzinfo=None) if getattr(m, "date", None) else now_utc
                        age_minutes = (now_utc - msg_date).total_seconds() / 60.0
                        if age_minutes <= 30.0:
                            if not self.signal_repo.message_exists(chat_id, m.id):
                                print(f"[STARTUP SYNC] Phát hiện tin nhắn gửi {age_minutes:.1f} phút trước (Chat: {chat_id} | Msg #{m.id}). Đang tự động bù xử lý...")
                                await self.handle_incoming_message(m, is_edit=False)
                except Exception:
                    pass
            print(f"[STARTUP SYNC] Hoàn tất rà soát bù tin nhắn khởi động.")
        except Exception:
            pass

    def _save_historical_message_only(self, chat_id: int, m: Any) -> None:
        try:
            raw_text = getattr(m, "raw_text", "") or ""
            orig_date = getattr(m, "date", None)
            now_utc = datetime.utcnow()
            dt = orig_date.replace(tzinfo=None) if orig_date else now_utc
            norm = normalize_text(raw_text)
            fp = self.compute_fingerprint(norm)
            self.signal_repo.save_message(
                chat_id=chat_id,
                message_id=m.id,
                sender_id=getattr(m, "sender_id", None),
                telegram_timestamp=dt,
                received_at=now_utc,
                raw_text=raw_text,
                normalized_text=norm,
                fingerprint=fp,
            )
        except Exception:
            pass

    async def _periodic_channel_sync(self):
        """
        Periodically polls allowed channels every 60 seconds to catch:
        1. Any missed messages during brief network hiccups/reconnects.
        2. Silent admin edits (e.g. SL adjustments, TP modifications, signal cancellations).
        """
        while True:
            try:
                await asyncio.sleep(60)
                if not self.tg_client or not self.tg_client.is_connected():
                    continue

                allowed = self.config.telegram.allowed_chat_ids or []
                if not allowed:
                    continue

                for chat_id in allowed:
                    try:
                        msgs = await self.tg_client.get_messages(chat_id, limit=5)
                        for m in reversed(msgs):
                            if not m:
                                continue
                            media_kind = detect_media_kind(m)
                            if not getattr(m, "raw_text", None) and not media_kind:
                                continue

                            with self.signal_repo.db.get_connection() as conn:
                                row = conn.execute(
                                    "SELECT raw_text, edit_timestamp FROM messages WHERE chat_id = ? AND message_id = ?",
                                    (chat_id, m.id),
                                ).fetchone()

                            if not row:
                                msg_date = m.date.replace(tzinfo=None) if getattr(m, "date", None) else datetime.utcnow()
                                age_seconds = (datetime.utcnow() - msg_date).total_seconds()
                                if age_seconds > 2700:  # Gửi quá 45 phút trước -> Lưu log tin nhắn, không sinh tín hiệu rác
                                    self._save_historical_message_only(chat_id, m)
                                    continue
                                print(f"[PERIODIC SYNC] Phát hiện tin nhắn mới bị sót (Chat: {chat_id} | Msg #{m.id}). Đang tự động xử lý...")
                                await self.handle_incoming_message(m, is_edit=False)
                            else:
                                stored_raw = row[0]
                                stored_edit_ts = row[1]
                                current_edit_date = getattr(m, "edit_date", None)
                                is_text_changed = ((m.raw_text or "").strip() != (stored_raw or "").strip())
                                is_new_edit = False
                                if current_edit_date:
                                    current_edit_iso = current_edit_date.replace(tzinfo=None).isoformat()
                                    if not stored_edit_ts or current_edit_iso > stored_edit_ts:
                                        is_new_edit = True

                                if is_text_changed or is_new_edit:
                                    print(f"[PERIODIC SYNC] Phát hiện admin chỉnh sửa tin nhắn (Chat: {chat_id} | Msg #{m.id}). Đang đồng bộ cập nhật...")
                                    await self.handle_incoming_message(m, is_edit=True)
                    except Exception:
                        pass
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(10)

    async def process_next_queued_signal(self) -> Optional[Any]:
        """
        Trụ Cột 6: Dequeues and executes the highest-priority signal when a slot opens up.
        """
        item = self.signal_queue.dequeue_next()
        if not item:
            return None

        if item.is_expired:
            print(f"[SMART QUEUE] Kèo {item.signal.symbol} từ '{item.channel_name}' đã hết hạn TTL ({item.ttl_seconds}s). Bỏ qua.")
            self.signal_repo.record_timeline_event(
                item.signal.signal_id,
                "QUEUED_SIGNAL_EXPIRED",
                f"Kèo trong hàng đợi đã quá hạn TTL ({item.ttl_seconds}s) trước khi có slot trống.",
            )
            self.signal_repo.update_signal_state(
                item.signal.signal_id,
                SignalState.REJECTED,
                reason=f"Hàng đợi ưu tiên quá hạn TTL ({item.ttl_seconds}s)",
            )
            return None

        print(f"\n[SMART QUEUE ACTIVATING] Giải phóng slot! Tự động kích hoạt kèo {item.signal.symbol} từ hàng đợi ('{item.channel_name}')...\n")
        self.signal_repo.record_timeline_event(
            item.signal.signal_id,
            "QUEUED_SIGNAL_ACTIVATED",
            f"Slot rủi ro được giải phóng. Kích hoạt tự động kèo {item.signal.symbol} từ hàng đợi ưu tiên!",
        )

        try:
            client = self.order_manager.client
            current_price = Decimal("0")
            try:
                current_price = await client.get_symbol_price(item.signal.symbol)
            except Exception:
                pass

            if current_price <= Decimal("0"):
                print(f"[SMART QUEUE ERROR] Không thể lấy giá thị trường cho {item.signal.symbol}. Hủy lệnh.")
                return None

            # Verify price has not blown past TP1 or breached SL
            if item.signal.side == PositionSide.LONG:
                if item.signal.take_profits and current_price >= item.signal.take_profits[0][0]:
                    print(f"[SMART QUEUE CANCEL] {item.signal.symbol} đã chạm TP1 trước khi có slot. Bỏ qua.")
                    self.signal_repo.update_signal_state(item.signal.signal_id, SignalState.REJECTED, "Giá đã chạm TP1 trong thời gian chờ hàng đợi")
                    return None
                if item.signal.stop_loss and current_price <= item.signal.stop_loss:
                    print(f"[SMART QUEUE CANCEL] {item.signal.symbol} đã chạm SL trước khi có slot. Bỏ qua.")
                    self.signal_repo.update_signal_state(item.signal.signal_id, SignalState.REJECTED, "Giá đã chạm SL trong thời gian chờ hàng đợi")
                    return None
            elif item.signal.side == PositionSide.SHORT:
                if item.signal.take_profits and current_price <= item.signal.take_profits[0][0]:
                    print(f"[SMART QUEUE CANCEL] {item.signal.symbol} đã chạm TP1 trước khi có slot. Bỏ qua.")
                    self.signal_repo.update_signal_state(item.signal.signal_id, SignalState.REJECTED, "Giá đã chạm TP1 trong thời gian chờ hàng đợi")
                    return None
                if item.signal.stop_loss and current_price >= item.signal.stop_loss:
                    print(f"[SMART QUEUE CANCEL] {item.signal.symbol} đã chạm SL trước khi có slot. Bỏ qua.")
                    self.signal_repo.update_signal_state(item.signal.signal_id, SignalState.REJECTED, "Giá đã chạm SL trong thời gian chờ hàng đợi")
                    return None

            equity = await client.get_margin_balance()
            if equity <= Decimal("0"):
                return None

            filters = await client.get_symbol_filters(item.signal.symbol)

            # Sizing
            entry_sizes = self.order_manager.risk_engine.calculate_position_sizes(
                signal=item.signal,
                current_equity=equity,
                open_risk_amount=Decimal("0"),
                step_size=filters.step_size,
                min_qty=filters.min_qty,
                min_notional=filters.min_notional,
                current_market_price=current_price,
            )
            orders = await self.order_manager.submit_entries(item.signal, entry_sizes, current_market_price=current_price)
            print(f"[SMART QUEUE SUCCESS] Đã mở thành công {len(orders)} lệnh cho kèo {item.signal.symbol} từ hàng đợi!")
            self.signal_repo.record_timeline_event(
                item.signal.signal_id,
                "ORDERS_SUBMITTED_FROM_QUEUE",
                f"Kèo hàng đợi đã khớp và đặt {len(orders)} lệnh lên Binance thành công!",
            )
            return orders
        except Exception as ex:
            print(f"[SMART QUEUE EXEC ERROR] {ex}")
            self.signal_repo.update_signal_state(item.signal.signal_id, SignalState.REJECTED, reason=f"Lỗi kích hoạt hàng đợi: {str(ex)}")
            return None

