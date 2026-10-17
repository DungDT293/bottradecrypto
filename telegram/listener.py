import asyncio
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from telethon import TelegramClient, events

from config.config import AppConfig
from core.enums import ExecutionMode, PositionSide, SignalState, UpdateType
from core.models import SourceMetadata, ValidatedSignal
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from services.channel_analytics_service import KNOWN_CHANNELS
from storage.database import DatabaseManager, SignalRepository

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
        self.is_shadow = is_shadow

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

        # 2. Normalize text first
        normalized = normalize_text(raw_text)
        if not normalized:
            # Empty / deleted message content
            print(f"[THONG TIN] Tin nhan trong hoac da bi xoa. Msg ID: {msg_id}")
            return

        fingerprint = self.compute_fingerprint(normalized)
        event_time = (edit_date or orig_date or now_utc).replace(tzinfo=None)

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
        else:
            # EDIT: Check if edit itself is stale
            effective_edit_date = edit_date or now_utc
            edit_age_seconds = (now_utc - effective_edit_date).total_seconds()
            if edit_age_seconds > self.config.telegram.reconnect_max_backlog_seconds:
                print(f"[BI CHAN: EDIT QUA HAN] Thoi diem sua cach day ({int(edit_age_seconds)}s > {self.config.telegram.reconnect_max_backlog_seconds}s).")
                return

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
                        if self.order_manager and self.config.mode in (ExecutionMode.TESTNET, ExecutionMode.LIVE):
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
                                    orders = await self.order_manager.submit_entries(validated, entry_sizes)
                                    print(f"[DA CAP NHAT ENTRY MOI TREN SAN] Đã đặt lại {len(orders)} lệnh Limit mới theo giá admin đã sửa ({new_entries}).")
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
                        # Update SL on exchange if active
                        if self.order_manager:
                            try:
                                pos = await self.order_manager.client.get_position(parsed.symbol_candidate)
                                amt = Decimal(str(pos.get("positionAmt", 0))) if pos else Decimal("0")
                                if amt != Decimal("0"):
                                    import uuid
                                    from core.enums import OrderSide, OrderType
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
                                    for oa in (old_algos or []):
                                        cid = oa.get("clientAlgoId")
                                        if cid and cid != new_sl_cid:
                                            await self.order_manager.client.cancel_algo_order(parsed.symbol_candidate, client_algo_id=cid)
                                    print(f"[DA CAP NHAT SL TREN SAN] Da cap nhat SL moi ({new_sl}) thanh cong tren Binance.")
                            except Exception as ex_sl:
                                print(f"[CANH BAO] Khong the cap nhat SL tren san: {ex_sl}")
                return

        # 7. Validate & Resolve Policies
        if not parsed.symbol_candidate or parsed.symbol_candidate == "UNKNOWN":
            return  # Silently skip non-signal messages (greetings, reactions, links without pair)

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

            if self.order_manager and self.config.mode in (ExecutionMode.TESTNET, ExecutionMode.LIVE):
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

                    open_risk = Decimal("0.0")

                    ticker = await client._request("GET", "/fapi/v1/ticker/price", params={"symbol": validated.symbol})
                    current_price = Decimal(ticker.get("price", "0"))

                    # Guard: Check if market price has already run past TP1 or breached Stop Loss
                    if current_price > Decimal("0"):
                        if validated.side == PositionSide.LONG:
                            if validated.stop_loss and current_price <= validated.stop_loss:
                                print(f"[CHAN LENH: GIA DA THUNG SL] Keo {validated.symbol} gia thi truong ({current_price}) da cham/thung SL ({validated.stop_loss}). Khong vao lenh.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã chạm/thủng Stop Loss ({validated.stop_loss}). Chặn vào lệnh bảo vệ tài khoản.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm hoặc thủng Stop Loss trước khi đặt lệnh")
                                return
                            if validated.take_profits and current_price >= validated.take_profits[0][0]:
                                print(f"[CHAN LENH: GIA DA DAT TP1] Keo {validated.symbol} gia thi truong ({current_price}) da dat TP1 ({validated.take_profits[0][0]}). Khong mua duoi.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã đạt hoặc vượt TP1 ({validated.take_profits[0][0]}). Chặn mua đuổi đỉnh.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm TP1 trước khi đặt lệnh, không mua đuổi")
                                return
                        elif validated.side == PositionSide.SHORT:
                            if validated.stop_loss and current_price >= validated.stop_loss:
                                print(f"[CHAN LENH: GIA DA VUOT SL] Keo {validated.symbol} gia thi truong ({current_price}) da cham/vuot SL ({validated.stop_loss}). Khong vao lenh.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã chạm/vượt Stop Loss ({validated.stop_loss}). Chặn vào lệnh bảo vệ tài khoản.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm hoặc vượt Stop Loss trước khi đặt lệnh")
                                return
                            if validated.take_profits and current_price <= validated.take_profits[0][0]:
                                print(f"[CHAN LENH: GIA DA DAT TP1] Keo {validated.symbol} gia thi truong ({current_price}) da dat TP1 ({validated.take_profits[0][0]}). Khong ban duoi.")
                                self.signal_repo.record_timeline_event(
                                    validated.signal_id,
                                    "PRICE_OUT_OF_BOUNDS",
                                    f"Giá thị trường ({current_price}) đã đạt hoặc thấp hơn TP1 ({validated.take_profits[0][0]}). Chặn bán đuổi đáy.",
                                )
                                self.signal_repo.update_signal_state(validated.signal_id, SignalState.REJECTED, "Giá thị trường đã chạm TP1 trước khi đặt lệnh, không bán đuổi")
                                return

                    entry_prices = [e[0] for e in validated.entries]
                    min_entry = min(entry_prices)
                    max_entry = max(entry_prices)

                    # Dynamic Immediate Entry:
                    # User requirement: "với lệnh mà bị lỡ nếu giá thấp hơn giá entry admin cho thì vào luôn"
                    if current_price > Decimal("0"):
                        tick = filters.tick_size if filters and filters.tick_size else Decimal("0.0001")
                        if validated.side == PositionSide.LONG and current_price <= max_entry and current_price > validated.stop_loss:
                            rounded_entry = (current_price // tick) * tick
                            validated.entries = [(rounded_entry, Decimal("1.0"))]
                            print(f"[VÀO LỆNH NGAY] Giá thị trường {validated.symbol} ({current_price}) <= Entry admin ({max_entry}). Kích hoạt khớp ngay lập tức tại {rounded_entry}!")
                            self.signal_repo.record_timeline_event(
                                validated.signal_id,
                                "IMMEDIATE_MARKET_ENTRY",
                                f"Giá thị trường ({current_price}) <= Entry admin ({max_entry}). Kích hoạt khớp ngay lập tức tại {rounded_entry}.",
                            )
                        elif validated.side == PositionSide.SHORT and current_price >= min_entry and current_price < validated.stop_loss:
                            rounded_entry = (current_price // tick) * tick
                            validated.entries = [(rounded_entry, Decimal("1.0"))]
                            print(f"[VÀO LỆNH NGAY] Giá thị trường {validated.symbol} ({current_price}) >= Entry admin ({min_entry}). Kích hoạt khớp SHORT ngay lập tức tại {rounded_entry}!")
                            self.signal_repo.record_timeline_event(
                                validated.signal_id,
                                "IMMEDIATE_MARKET_ENTRY",
                                f"Giá thị trường ({current_price}) >= Entry admin ({min_entry}). Kích hoạt khớp SHORT ngay lập tức tại {rounded_entry}.",
                            )

                    try:
                        await client.set_margin_type_isolated(validated.symbol)
                    except Exception:
                        pass
                    try:
                        await client.set_leverage(validated.symbol, validated.leverage)
                    except Exception:
                        pass

                    entry_sizes = self.order_manager.risk_engine.calculate_position_sizes(
                        signal=validated,
                        current_equity=equity,
                        open_risk_amount=open_risk,
                        step_size=filters.step_size,
                        min_qty=filters.min_qty,
                        min_notional=filters.min_notional,
                        current_market_price=current_price,
                    )

                    orders = await self.order_manager.submit_entries(validated, entry_sizes)
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

        while True:
            try:
                await self.tg_client.run_until_disconnected()
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
            min_entry = min(entry_prices)
            max_entry = max(entry_prices)
            sl = validated.stop_loss
            tp1 = validated.take_profits[0][0] if validated.take_profits else None

            if side == PositionSide.LONG:
                # If price already breached Stop Loss
                if sl and curr_p <= sl:
                    return False, f"Giá thị trường ({curr_p}) đã thủng Stop Loss ({sl}). Kèo đã thất bại."
                # If price already hit TP1
                if tp1 and curr_p >= tp1:
                    return False, f"Giá thị trường ({curr_p}) đã đạt/vượt TP1 ({tp1}). Không mua đuổi đỉnh."
                # If price is within entry or within 0.8% above max entry
                if curr_p > max_entry * Decimal("1.008"):
                    return False, f"Giá thị trường ({curr_p}) đã tăng cao hơn vùng Entry ({max_entry}) > 0.8%. Bỏ qua."

                return True, (
                    f"Kèo {symbol} gửi trễ {int(age_seconds)}s nhưng thị giá ({curr_p}) vẫn nằm trong vùng Entry hợp lệ "
                    f"[{min_entry} - {max_entry}], chưa chạm TP1 ({tp1}) và trên SL ({sl}). Đủ điều kiện khớp bổ sung."
                )

            elif side == PositionSide.SHORT:
                # If price already breached Stop Loss
                if sl and curr_p >= sl:
                    return False, f"Giá thị trường ({curr_p}) đã vượt Stop Loss ({sl}). Kèo đã thất bại."
                # If price already hit TP1
                if tp1 and curr_p <= tp1:
                    return False, f"Giá thị trường ({curr_p}) đã đạt/thấp hơn TP1 ({tp1}). Không bán đuổi đáy."
                # If price is within entry or within 0.8% below min entry
                if curr_p < min_entry * Decimal("0.992"):
                    return False, f"Giá thị trường ({curr_p}) đã giảm thấp hơn vùng Entry ({min_entry}) > 0.8%. Bỏ qua."

                return True, (
                    f"Kèo {symbol} gửi trễ {int(age_seconds)}s nhưng thị giá ({curr_p}) vẫn nằm trong vùng Entry hợp lệ "
                    f"[{min_entry} - {max_entry}], chưa chạm TP1 ({tp1}) và dưới SL ({sl}). Đủ điều kiện khớp bổ sung."
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
                        if not m or not getattr(m, "raw_text", None) or not m.raw_text.strip():
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
