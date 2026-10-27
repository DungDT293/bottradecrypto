import asyncio
import re
import time
from decimal import Decimal
import hashlib
import json
import math
import os
import urllib.request
import signal
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from backend.api.auth_middleware import make_error_response
from backend.events.event_bus import event_bus
from config.config import AppConfig, exchange_writes_enabled, save_config
from config.policy_defaults import ExecutionPolicyConfig
from core.enums import EntryRangePolicy, ExecutionMode, MarginMode, MultiTPWeightMode, OrderSide, OrderType, SignalState, UpdateType
from core.models import SourceMetadata
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from services.alert_service import AlertLevel, AlertService
from services.binance_service import BinanceService
from services.channel_analytics_service import ChannelAnalyticsService
from services.license_service import LicenseService
from services.stats_service import StatsService, VN_TZ
from services.telegram_service import TelegramService
from services.trading_service import EngineStatus, TradingService
from services.gemini_autonomous_trader import GeminiAutonomousTrader
from storage.database import DatabaseManager, OrderRepository, SignalRepository
from exchange.binance_client import BinanceFuturesClient
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.reconciliation import ReconciliationEngine
from risk.risk_engine import RiskEngine
from risk.market_regime_shield import global_market_regime_shield
from services.signal_queue_service import global_signal_queue_service
from telegram.listener import TelegramSignalListener


def create_api_router(
    config: AppConfig,
    db: DatabaseManager,
    session_token: str,
) -> APIRouter:
    router = APIRouter()

    # Instantiate services
    telegram_svc = TelegramService(config)
    binance_svc = BinanceService(config)
    trading_svc = TradingService(db, config)
    stats_svc = StatsService(db, config)
    channel_analytics_svc = ChannelAnalyticsService(db.db_path)
    license_svc = LicenseService()
    alert_svc = AlertService.get_instance(db=db)
    from notifications.notifier import SystemNotifier
    system_notifier = SystemNotifier(
        config=getattr(config, "notifications", None),
        telegram_client_getter=telegram_svc.get_client,
    )
    alert_svc.set_notifier(system_notifier)
    if not alert_svc._alerts:
        alert_svc.add_alert(
            AlertLevel.INFO,
            "Hệ thống khởi động",
            f"Backend đã sẵn sàng hoạt động ở chế độ {config.mode.value}. Cơ sở dữ liệu và bảo mật rủi ro đã nạp thành công.",
            "SYSTEM",
        )
    signal_repo = SignalRepository(db)
    order_repo = OrderRepository(db)
    parser = SignalParser()
    last_income_sync: Dict[str, float] = {"time": 0.0}
    validator = SignalValidator(config)
    update_parser = ChannelUpdateParser()

    binance_client = BinanceFuturesClient(config)
    pos_manager = PositionManager(binance_client, signal_repo)
    risk_engine = RiskEngine(config)
    order_manager = OrderManager(
        client=binance_client,
        order_repo=order_repo,
        signal_repo=signal_repo,
        position_manager=pos_manager,
        risk_engine=risk_engine,
        config=config,
    )
    reconciler = ReconciliationEngine(
        exchange_client=binance_client,
        db=db,
        order_manager=order_manager,
        config=config,
    )
    trading_svc._reconciler = reconciler

    # Instantiate Gemini Autonomous AI Trader
    ai_trader = GeminiAutonomousTrader(
        config=config,
        binance_client=binance_client,
        order_manager=order_manager,
        risk_engine=risk_engine,
        signal_repo=signal_repo,
        db=db,
        entry_enabled_provider=trading_svc.is_entry_enabled,
        engine_status_provider=trading_svc.get_engine_status,
    )
    trading_svc._ai_trader = ai_trader

    # Autonomous AI Market Scanner Background Worker
    async def run_ai_trader_worker():
        if getattr(trading_svc, "_ai_worker_started", False):
            return
        trading_svc._ai_worker_started = True
        if ai_trader.enabled and exchange_writes_enabled(config):
            trading_svc.set_engine_status(EngineStatus.RUNNING_LISTEN)
        await asyncio.sleep(12.0)  # Initial wait for server readiness
        while True:
            try:
                if ai_trader.enabled and exchange_writes_enabled(config) and binance_svc.has_credentials():
                    trading_svc.set_engine_status(EngineStatus.RUNNING_LISTEN)
                    res = await ai_trader.scan_and_auto_trade()
                    if res.get("executed") and res["executed"].get("status") == "SUCCESS":
                        t_info = res["executed"]
                        alert_svc.add_alert(
                            AlertLevel.INFO,
                            "AI Quant Tự Động Khớp Lệnh",
                            f"🤖 AI Quant vừa khớp lệnh {t_info.get('side')} {t_info.get('quantity')} {t_info.get('symbol')} @ {t_info.get('entry_price')}. Lý do: {t_info.get('rationale')}",
                            "AI_TRADER",
                        )
            except Exception:
                pass
            interval = max(3, getattr(ai_trader, "scan_interval_minutes", 15))
            await asyncio.sleep(interval * 60)

    router.ai_trader_task_starter = run_ai_trader_worker

    # Active Reconciliation Background Worker (Guarded against duplicate execution)
    async def run_reconciliation_worker():
        if getattr(trading_svc, "_reconciliation_started", False):
            return
        trading_svc._reconciliation_started = True
        while True:
            try:
                if exchange_writes_enabled(config) and binance_svc.has_credentials():
                    from exchange.binance_client import BinanceFuturesClient
                    if BinanceFuturesClient.is_rate_limited():
                        await asyncio.sleep(5.0)
                        continue
                    await reconciler.reconcile_all()
            except Exception:
                pass
            await asyncio.sleep(12.0)

    router.reconciliation_task_starter = run_reconciliation_worker


    # Auto-start Telegram listener in background if session authorized
    async def run_listener_loop():
        if getattr(trading_svc, "_listener_started", False):
            return
        if not getattr(config, "channel_signals_enabled", False):
            print("[TELEGRAM] Quét tín hiệu kênh Telegram đang tắt (Ưu tiên AI Quant Autonomous Trader).")
            trading_svc.set_engine_status(EngineStatus.RUNNING_LISTEN)
            return
        trading_svc._listener_started = True
        await asyncio.sleep(1.0)
        try:
            tg_client = telegram_svc.get_client()
            if not tg_client.is_connected():
                await tg_client.connect()
            if not await tg_client.is_user_authorized():
                print("[TELEGRAM] Session chua authorized.")
                return

            listener = TelegramSignalListener(
                config=config,
                tg_client=tg_client,
                db_manager=db,
                order_manager=order_manager,
                position_manager=pos_manager,
                is_shadow=config.mode in (ExecutionMode.READ_ONLY, ExecutionMode.SHADOW, ExecutionMode.PAPER),
                entry_enabled_provider=trading_svc.is_entry_enabled,
            )
            trading_svc._listener = listener
            reconciler.on_slot_freed_callback = listener.process_next_queued_signal
            trading_svc.set_engine_status(EngineStatus.RUNNING_LISTEN)

            mode_title = "TIỀN THẬT (LIVE)" if config.mode.value == "LIVE" else "DEMO / TESTNET"
            print("\n" + "=" * 60)
            print(f"[TELEGRAM BOT EXECUTOR] DA KHOI DONG THANH CONG ({mode_title})!")
            print(f"- Mode: {config.mode.value}")
            print(f"- So luong kenh tinh hoa theo doi: {len(config.telegram.allowed_chat_ids)} nhom")
            print("=" * 60 + "\n")

            alert_svc.add_alert(
                AlertLevel.INFO,
                f"Bot Giao Dịch Đã Sẵn Sàng ({mode_title})",
                f"Đang giám sát {len(config.telegram.allowed_chat_ids)} nhóm Tinh hoa đã duyệt và sẵn sàng vào lệnh trên Binance ({config.mode.value}).",
                "BOT_ENGINE",
            )
            await event_bus.publish("backend_status_changed", {"mode": config.mode.value, "engine": "RUNNING_LISTEN"})

            await listener.start()
        except Exception as e:
            print(f"[TELEGRAM LISTENER ERROR] {e}")
            trading_svc.set_engine_status(EngineStatus.ERROR)

    router.listener_task_starter = run_listener_loop

    # Dedicated Telegram Bot Runner (Interactive AI Council & Telemetry)
    async def run_dedicated_bot_loop():
        while True:
            try:
                token = getattr(getattr(config, "notifications", None), "notification_bot_token", None) or os.environ.get("TELEGRAM_BOT_TOKEN")
                if token:
                    from telegram.dedicated_bot import DedicatedTelegramBot
                    bot = DedicatedTelegramBot(bot_token=token, config=config)
                    if bot.is_configured:
                        await bot.run()
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Dedicated bot runner crashed: {e}, restarting in 5s...")
                await asyncio.sleep(5)

    router.dedicated_bot_task_starter = run_dedicated_bot_loop

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(run_listener_loop())
        loop.create_task(run_dedicated_bot_loop())
    except RuntimeError:
        pass

    # Token Dependency for HTTP requests
    def verify_token(x_session_token: Optional[str] = Header(None)):
        if not x_session_token or x_session_token != session_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=make_error_response("UNAUTHORIZED", "Phiên làm việc không hợp lệ hoặc thiếu Token xác thực."),
            )

    # -------------------------------------------------------------
    # 1. Health & Snapshot
    # -------------------------------------------------------------
    @router.get("/health")
    async def get_health():
        # Clean health check: NEVER exposes session token
        return {
            "status": "HEALTHY",
            "version": "2.8.1",
            "mode": config.mode.value,
            "live_trading_enabled": config.live_trading_enabled,
            "engine_status": trading_svc.get_engine_status().value,
            "entry_enabled": trading_svc.is_entry_enabled(),
        }

    @router.get("/handshake")
    async def get_handshake():
        if os.environ.get("TBCE_ALLOW_BROWSER_HANDSHAKE") != "1":
            raise HTTPException(status_code=404, detail="Handshake unavailable")
        return {
            "status": "READY",
            "host": "127.0.0.1",
            "port": int(os.environ.get("TBCE_BACKEND_PORT", "0") or 0),
            "session_token": session_token,
        }

    @router.get("/snapshot", dependencies=[Depends(verify_token)])
    async def get_snapshot():
        telemetry = stats_svc.get_telegram_telemetry()
        account = binance_svc.get_cached_snapshot()
        if binance_svc.has_credentials():
            try:
                account = await asyncio.wait_for(binance_svc.sync_account(force=False), timeout=8.0)
            except Exception:
                account = binance_svc.get_cached_snapshot()

            # Periodic background sync of realized PnL from Binance income
            if time.time() - last_income_sync["time"] > 60.0:
                try:
                    c = BinanceFuturesClient(config)
                    await stats_svc.sync_binance_income(c, days_back=30)
                    last_income_sync["time"] = time.time()
                    await c.close()
                except Exception:
                    pass

        pnl_today = stats_svc.get_pnl_summary(0)
        pnl_7d = stats_svc.get_pnl_summary(6)
        recent_alerts = alert_svc.get_alerts(limit=20)


        positions = trading_svc.get_open_positions(
            binance_positions=account.open_positions,
            binance_orders=account.active_orders,
        )
        orders = trading_svc.get_active_orders(binance_orders=account.active_orders)

        return {
            "mode": config.mode.value,
            "live_trading_enabled": config.live_trading_enabled,
            "ferrari_mode_enabled": bool(getattr(config, "ferrari_mode_enabled", False)),
            "max_active_signals": int(getattr(config.risk, "max_active_signals", 20 if getattr(config, "ferrari_mode_enabled", False) else 3)),
            "engine_status": trading_svc.get_engine_status().value,
            "entry_enabled": trading_svc.is_entry_enabled(),
            "account": account.model_dump(),
            "telemetry": telemetry,
            "pnl_today": pnl_today,
            "pnl_7d": pnl_7d,
            "positions": positions,
            "orders": orders,
            "alerts": recent_alerts,
            "unread_alerts_count": alert_svc.get_unread_count(),
            "basket_guard": getattr(reconciler, "basket_guard_state", None),
        }

    # -------------------------------------------------------------
    # 2. Telegram Endpoints
    # -------------------------------------------------------------
    @router.get("/telegram/credentials-status", dependencies=[Depends(verify_token)])
    async def get_telegram_credentials_status():
        return telegram_svc.get_credentials_status()

    class TelegramCredentialsModel(BaseModel):
        api_id: int
        api_hash: str

    @router.post("/telegram/credentials", dependencies=[Depends(verify_token)])
    async def update_telegram_credentials(body: TelegramCredentialsModel):
        return await telegram_svc.update_credentials(body.api_id, body.api_hash)

    @router.get("/telegram/profile", dependencies=[Depends(verify_token)])
    async def get_telegram_profile():
        return await telegram_svc.get_account_profile()

    class LoginRequestModel(BaseModel):
        phone: str

    @router.post("/telegram/login/request-code", dependencies=[Depends(verify_token)])
    async def telegram_request_code(body: LoginRequestModel):
        res = await telegram_svc.send_login_code(body.phone)
        if not res.get("success"):
            error_code = res.get("error_code", "TG_LOGIN_CODE_FAILED")
            error_msg = res.get("error", "Lỗi gửi mã OTP.")
            raise HTTPException(
                status_code=400,
                detail=make_error_response(error_code, error_msg),
            )
        return res

    class LoginSubmitModel(BaseModel):
        code: str
        auth_attempt_id: Optional[str] = None
        password_2fa: Optional[str] = None

    @router.post("/telegram/login/submit-code", dependencies=[Depends(verify_token)])
    async def telegram_submit_code(body: LoginSubmitModel):
        res = await telegram_svc.submit_login_code(
            code=body.code,
            password_2fa=body.password_2fa,
            auth_attempt_id=body.auth_attempt_id,
        )
        if not res.get("success"):
            error_code = res.get("error_code", "TG_LOGIN_AUTH_FAILED")
            error_msg = res.get("error", "Lỗi xác thực Telegram.")
            if res.get("needs_2fa"):
                return {
                    "success": False,
                    "needs_2fa": True,
                    "auth_attempt_id": res.get("auth_attempt_id"),
                    "error": error_msg,
                }
            raise HTTPException(
                status_code=400,
                detail=make_error_response(error_code, error_msg),
            )
        await event_bus.publish("telegram_status_changed", {"status": "CONNECTED", "user": res.get("first_name")})
        return res

    @router.get("/telegram/dialogs", dependencies=[Depends(verify_token)])
    async def get_telegram_dialogs(refresh: bool = Query(False)):
        try:
            res = await telegram_svc.list_accessible_dialogs(force_refresh=refresh)
            if isinstance(res, dict):
                return {
                    "dialogs": res.get("dialogs", []),
                    "folders": res.get("folders", []),
                    "allowed_chat_ids": config.telegram.allowed_chat_ids,
                }
            return {
                "dialogs": res,
                "folders": [],
                "allowed_chat_ids": config.telegram.allowed_chat_ids,
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=make_error_response("TG_DIALOGS_FAILED", str(e)),
            )

    class AllowlistUpdateModel(BaseModel):
        allowed_chat_ids: List[int]

    @router.post("/telegram/allowlist", dependencies=[Depends(verify_token)])
    async def update_allowlist(body: AllowlistUpdateModel):
        config.telegram.allowed_chat_ids = body.allowed_chat_ids
        save_config(config)
        alert_svc.add_alert(
            AlertLevel.INFO,
            "Cập nhật danh sách theo dõi",
            f"Đã cập nhật: {len(body.allowed_chat_ids)} kênh được theo dõi.",
            "USER",
        )
        return {"success": True, "allowed_chat_ids": config.telegram.allowed_chat_ids}

    class DedicatedBotTokenModel(BaseModel):
        bot_token: str
        chat_id: Optional[int] = None

    @router.post("/telegram/bot-token", dependencies=[Depends(verify_token)])
    async def set_dedicated_bot_token(body: DedicatedBotTokenModel):
        if not getattr(config, "notifications", None):
            from config.config import NotificationsConfig
            config.notifications = NotificationsConfig()
        token = body.bot_token.strip()
        config.notifications.notification_bot_token = token
        config.notifications.telegram_notification_enabled = True
        if body.chat_id:
            config.notifications.notification_chat_id = body.chat_id
        save_config(config)
        from telegram.dedicated_bot import DedicatedTelegramBot
        bot = DedicatedTelegramBot(bot_token=token, config=config)
        if bot.is_configured:
            asyncio.create_task(bot.run())
        return {"success": True, "bot_configured": True}

    @router.post("/telegram/auto-join-elite", dependencies=[Depends(verify_token)])
    async def auto_join_elite():
        try:
            res = await telegram_svc.auto_join_elite_channels()
            alert_svc.add_alert(
                AlertLevel.INFO,
                "Tự động tham gia nhóm tinh hoa",
                res.get("message", "Đã quét và tham gia các nhóm tinh hoa."),
                "TELEGRAM",
            )
            return res
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=make_error_response("AUTO_JOIN_FAILED", str(e)),
            )

    @router.get("/system/public-ip", dependencies=[Depends(verify_token)])
    async def get_public_ip():
        """Returns the public IP address of this machine for Binance API IP whitelisting."""
        import urllib.request
        try:
            loop = asyncio.get_event_loop()
            def fetch_ip():
                req = urllib.request.Request(
                    "https://api.ipify.org?format=json",
                    headers={"User-Agent": "TradeBot/1.3.1"},
                )
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    return json.loads(resp.read().decode("utf-8")).get("ip", "")
            ip = await loop.run_in_executor(None, fetch_ip)
            return {"ip": ip, "success": True}
        except Exception as e:
            return {"ip": "", "success": False, "error": str(e)}

    # === COMMERCIAL LICENSE ENDPOINTS ===
    @router.get("/license/status", dependencies=[Depends(verify_token)])
    async def get_license_status():
        return license_svc.get_license_info()

    class LicenseKeyModel(BaseModel):
        key: str

    @router.post("/license/activate", dependencies=[Depends(verify_token)])
    async def activate_license(body: LicenseKeyModel):
        res = license_svc.activate_key(body.key)
        if not res.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=make_error_response("LICENSE_INVALID", res.get("message", "Key không hợp lệ")),
            )
        alert_svc.add_alert(
            AlertLevel.INFO,
            "Bản quyền kích hoạt thành công",
            res.get("message", ""),
            "LICENSE",
        )
        return res

    @router.post("/license/trial", dependencies=[Depends(verify_token)])
    async def activate_license_trial():
        res = license_svc.activate_trial()
        if not res.get("success", False):
            raise HTTPException(
                status_code=400,
                detail=make_error_response("TRIAL_FAILED", res.get("message", "Không thể kích hoạt dùng thử")),
            )
        alert_svc.add_alert(
            AlertLevel.INFO,
            "Kích hoạt Dùng Thử 3 Ngày",
            res.get("message", ""),
            "LICENSE",
        )
        return res

    class CollectHistoryModel(BaseModel):
        chat_id: int
        days: int = 7
        limit: int = 1000

    @router.post("/telegram/collect-history", dependencies=[Depends(verify_token)])
    async def collect_history(body: CollectHistoryModel):
        async def _progress(last_id, count):
            await event_bus.publish("task_progress", {
                "task": "COLLECT_HISTORY",
                "chat_id": body.chat_id,
                "current": count,
                "total": body.limit,
            })

        try:
            msgs = await telegram_svc.collect_history(
                chat_id=body.chat_id,
                limit=body.limit,
                max_days=body.days,
                progress_callback=_progress,
            )

            # Sort ascending by message_id so versions are stored chronologically
            sorted_msgs = sorted(msgs, key=lambda m: m["message_id"])

            signals_detected = 0
            signals_validated = 0
            updates_recorded = 0

            for m in sorted_msgs:
                raw_text = m.get("raw_text") or ""
                has_media = bool(m.get("media_kind") or m.get("has_media") or m.get("photo"))
                if has_media:
                    from services.admin_evidence import classify_media_claim, is_brag_media_claim
                    evidence = classify_media_claim(raw_text, str(m.get("media_kind") or "photo"))
                    signal_repo.save_admin_evidence(
                        m["chat_id"], m["message_id"],
                        datetime.fromisoformat(m["date"]).replace(tzinfo=None) if m.get("date") else datetime.now(timezone.utc).replace(tzinfo=None),
                        evidence,
                        sender_id=m.get("sender_id"),
                    )
                    if is_brag_media_claim(raw_text):
                        continue
                if not raw_text.strip():
                    continue

                msg_chat_id = m["chat_id"]
                msg_id = m["message_id"]
                sender_id = m.get("sender_id")
                reply_to_msg_id = m.get("reply_to_msg_id")

                # Parse dates
                if m.get("date"):
                    try:
                        orig_date = datetime.fromisoformat(m["date"]).replace(tzinfo=None)
                    except Exception:
                        orig_date = datetime.utcnow()
                else:
                    orig_date = datetime.utcnow()

                if m.get("edit_date"):
                    try:
                        edit_date = datetime.fromisoformat(m["edit_date"]).replace(tzinfo=None)
                    except Exception:
                        edit_date = None
                else:
                    edit_date = None

                normalized = normalize_text(raw_text)
                fingerprint = hashlib.sha256("".join(normalized.split()).lower().encode("utf-8")).hexdigest() if normalized else ""
                now_utc = datetime.utcnow()

                # 1. Save message & message version
                signal_repo.save_message(
                    chat_id=msg_chat_id,
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
                    chat_id=msg_chat_id,
                    message_id=msg_id,
                    event_date=edit_date or orig_date,
                    received_at=now_utc,
                    raw_text=raw_text,
                    normalized_text=normalized,
                    fingerprint=fingerprint,
                    is_edit=bool(edit_date),
                    reply_to_msg_id=reply_to_msg_id,
                )

                # 2. Check channel update (TP hit, admin cancel, correction)
                update_type, update_val, detail_text = update_parser.parse_update(normalized)
                if update_type != UpdateType.UNKNOWN:
                    updates_recorded += 1
                    parent_sig_id = None
                    if reply_to_msg_id:
                        parent_sig_id = signal_repo.resolve_reply_parent(msg_chat_id, reply_to_msg_id)
                    if parent_sig_id:
                        signal_repo.record_timeline_event(
                            parent_sig_id,
                            update_type.value,
                            detail_text,
                            {"message_id": msg_id, "chat_id": msg_chat_id},
                        )
                    if update_type in [
                        UpdateType.RESULT_TP_REPORTED,
                        UpdateType.RESULT_SL_REPORTED,
                        UpdateType.CANCEL_PENDING_ENTRY,
                        UpdateType.CORRECT_SIGNAL,
                    ]:
                        continue

                # 3. Parse signal
                meta = SourceMetadata(
                    chat_id=msg_chat_id,
                    message_id=msg_id,
                    sender_id=sender_id,
                    telegram_timestamp=orig_date,
                    received_at=now_utc,
                    is_edit=bool(edit_date),
                    edit_timestamp=edit_date,
                )
                parsed = parser.parse(raw_text, meta)

                if parsed.symbol_candidate:
                    signals_detected += 1
                    signal_repo.save_signal(parsed)

                    source_override = config.sources.get(msg_chat_id)
                    parsed, validated = validator.validate_and_resolve(parsed, source_override)
                    signal_repo.save_signal(parsed)

                    if validated:
                        signals_validated += 1
                        signal_repo.record_timeline_event(
                            validated.signal_id,
                            "SIGNAL_VALIDATED",
                            f"Tin hieu lich su da xac thuc: {validated.symbol} {validated.side.value}",
                            {
                                "leverage": validated.leverage,
                                "entries": [str(e) for e in validated.entries],
                                "stop_loss": str(validated.stop_loss),
                                "take_profits": [str(tp) for tp in validated.take_profits],
                            },
                        )
                    elif parsed.validation_status == SignalState.NEEDS_REVIEW:
                        signal_repo.record_timeline_event(
                            parsed.signal_id,
                            "NEEDS_REVIEW",
                            parsed.blocking_reason or "Can danh gia",
                        )
                    elif parsed.validation_status == SignalState.NEEDS_POLICY:
                        signal_repo.record_timeline_event(
                            parsed.signal_id,
                            "NEEDS_POLICY",
                            parsed.blocking_reason or "Cho cau hinh policy",
                        )

            await event_bus.publish("stats_updated", stats_svc.get_telegram_telemetry())
            return {
                "success": True,
                "count": len(msgs),
                "signals_detected": signals_detected,
                "signals_validated": signals_validated,
                "updates_recorded": updates_recorded,
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=make_error_response("TG_COLLECT_FAILED", str(e)),
            )

    @router.post("/telegram/cancel-collection", dependencies=[Depends(verify_token)])
    async def cancel_collection():
        telegram_svc.cancel_collection()
        return {"success": True}

    @router.post("/telegram/logout", dependencies=[Depends(verify_token)])
    async def telegram_logout():
        success = telegram_svc.logout()
        await event_bus.publish("telegram_status_changed", {"status": "NOT_LOGGED_IN"})
        return {"success": success}

    @router.get("/telegram/channels/{chat_id}/messages", dependencies=[Depends(verify_token)])
    async def get_channel_messages(
        chat_id: int,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        only_signals: bool = Query(False),
    ):
        try:
            with db.get_connection() as conn:
                where_clauses = ["m.chat_id = ?"]
                params: List[Any] = [chat_id]
                if only_signals:
                    where_clauses.append("s.signal_id IS NOT NULL")

                where_sql = " AND ".join(where_clauses)

                query = f"""
                    SELECT m.chat_id, m.message_id, m.sender_id, m.telegram_timestamp,
                           m.received_at, m.edit_timestamp, m.raw_text,
                           s.signal_id, s.symbol, s.side, s.state, s.entry_mode,
                           s.entries_json, s.stop_loss, s.take_profits_json,
                           s.leverage, s.blocking_reason, s.created_at as signal_created_at
                    FROM messages m
                    LEFT JOIN signals s ON m.chat_id = s.chat_id AND m.message_id = s.message_id
                    WHERE {where_sql}
                    ORDER BY m.message_id DESC
                    LIMIT ? OFFSET ?
                """
                params.extend([limit, offset])

                rows = conn.execute(query, tuple(params)).fetchall()

                # Total count
                count_query = f"""
                    SELECT COUNT(*)
                    FROM messages m
                    LEFT JOIN signals s ON m.chat_id = s.chat_id AND m.message_id = s.message_id
                    WHERE {where_sql}
                """
                total_count = conn.execute(count_query, (chat_id,)).fetchone()[0]

                # Channel signal stats
                sig_stats = conn.execute("""
                    SELECT 
                        COUNT(s.signal_id) as total_signals,
                        SUM(CASE WHEN s.state = 'VALIDATED' THEN 1 ELSE 0 END) as validated_signals,
                        SUM(CASE WHEN s.state = 'REJECTED' THEN 1 ELSE 0 END) as rejected_signals
                    FROM signals s
                    WHERE s.chat_id = ?
                """, (chat_id,)).fetchone()

                msg_list = []
                for r in rows:
                    r_dict = dict(r)
                    msg_id = r_dict["message_id"]

                    # Fetch edit versions for this message
                    v_rows = conn.execute("""
                        SELECT version, event_date, received_at, raw_text, is_edit, reply_to_msg_id
                        FROM message_versions
                        WHERE chat_id = ? AND message_id = ?
                        ORDER BY version ASC
                    """, (chat_id, msg_id)).fetchall()

                    r_dict["versions"] = [dict(v) for v in v_rows]
                    r_dict["has_edits"] = len(v_rows) > 1 or bool(r_dict.get("edit_timestamp"))

                    if r_dict.get("entries_json"):
                        try:
                            r_dict["entries"] = json.loads(r_dict["entries_json"])
                        except Exception:
                            r_dict["entries"] = []
                    else:
                        r_dict["entries"] = []

                    if r_dict.get("take_profits_json"):
                        try:
                            r_dict["take_profits"] = json.loads(r_dict["take_profits_json"])
                        except Exception:
                            r_dict["take_profits"] = []
                    else:
                        r_dict["take_profits"] = []

                    msg_list.append(r_dict)

            return {
                "success": True,
                "chat_id": chat_id,
                "total": total_count,
                "total_signals": sig_stats[0] if sig_stats and sig_stats[0] else 0,
                "validated_signals": sig_stats[1] if sig_stats and sig_stats[1] else 0,
                "rejected_signals": sig_stats[2] if sig_stats and sig_stats[2] else 0,
                "messages": msg_list,
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=make_error_response("TG_CHANNEL_MESSAGES_FAILED", str(e)),
            )

    # -------------------------------------------------------------
    # 3. Binance Endpoints
    # -------------------------------------------------------------
    @router.get("/binance/credentials-status", dependencies=[Depends(verify_token)])
    async def get_binance_credentials_status():
        return binance_svc.get_credentials_status()

    class BinanceCredentialsModel(BaseModel):
        testnet_api_key: Optional[str] = None
        testnet_api_secret: Optional[str] = None
        live_api_key: Optional[str] = None
        live_api_secret: Optional[str] = None

    @router.post("/binance/credentials", dependencies=[Depends(verify_token)])
    async def update_binance_credentials(body: BinanceCredentialsModel):
        res = binance_svc.update_credentials(
            testnet_api_key=body.testnet_api_key,
            testnet_api_secret=body.testnet_api_secret,
            live_api_key=body.live_api_key,
            live_api_secret=body.live_api_secret,
        )
        save_config(config)
        alert_svc.add_alert(
            AlertLevel.INFO,
            "Cập nhật Binance API",
            "Đã cập nhật thông tin khóa API sàn Binance.",
            "USER",
        )
        return res

    @router.post("/binance/credentials/remove", dependencies=[Depends(verify_token)])
    async def remove_binance_credentials(target: str = Query("all", pattern="^(testnet|live|all)$")):
        res = binance_svc.remove_credentials(target=target)
        save_config(config)
        await event_bus.publish("binance_status_changed", {"disconnected": True, "target": target})
        alert_svc.add_alert(
            AlertLevel.WARNING,
            "Gỡ bỏ Binance API Key",
            f"Đã gỡ bỏ khóa API Binance ({target.upper()}) thành công.",
            "USER",
        )
        return res

    @router.get("/binance/status", dependencies=[Depends(verify_token)])
    async def get_binance_status():
        snapshot = binance_svc.get_cached_snapshot()
        return snapshot.model_dump()

    @router.post("/binance/test-connection", dependencies=[Depends(verify_token)])
    async def test_binance_connection(target_mode: Optional[str] = Query(None)):
        res = await binance_svc.test_connection(target_mode=target_mode)
        if res.get("success") and (not target_mode or target_mode.upper() == config.mode.value):
            await event_bus.publish("binance_status_changed", res)
        return res


    @router.post("/binance/sync", dependencies=[Depends(verify_token)])
    async def sync_binance_account():
        snapshot = await binance_svc.sync_account()
        await event_bus.publish("binance_status_changed", snapshot.model_dump())
        return snapshot.model_dump()

    # -------------------------------------------------------------
    # 4. Signals & Timeline
    # -------------------------------------------------------------
    @router.get("/signals", dependencies=[Depends(verify_token)])
    async def get_signals(
        state: Optional[str] = Query(None),
        symbol: Optional[str] = Query(None),
        limit: int = Query(200, ge=1, le=500),
    ):
        return trading_svc.get_signals(state_filter=state, symbol_search=symbol, limit=limit)

    @router.get("/signals/{signal_id}", dependencies=[Depends(verify_token)])
    async def get_signal_detail(signal_id: str):
        detail = trading_svc.get_signal_detail(signal_id)
        if not detail:
            raise HTTPException(
                status_code=404,
                detail=make_error_response("SIGNAL_NOT_FOUND", f"Không tìm thấy tín hiệu {signal_id}"),
            )

        # Bổ sung thông tin kết quả Lãi/Lỗ thực tế (Trade Outcome) từ Binance cho vị thế
        sig = detail.get("signal", {})
        sym = sig.get("symbol")
        if sym and binance_svc.has_credentials():
            try:
                client = BinanceFuturesClient(config)
                raw_trades = await client._request("GET", "/fapi/v1/userTrades", params={"symbol": sym, "limit": 30}, signed=True)
                await client.close()
                if raw_trades:
                    sig_created_str = sig.get("created_at") or "2000-01-01"
                    try:
                        sig_created_ts = int(datetime.fromisoformat(sig_created_str.replace("Z", "+00:00")).timestamp() * 1000) - 60000
                    except Exception:
                        sig_created_ts = 0

                    sig_order_ids = {str(o.get("exchange_order_id")) for o in detail.get("orders", []) if o.get("exchange_order_id")}
                    matching_trades = [
                        t for t in raw_trades
                        if str(t.get("orderId")) in sig_order_ids or t.get("time", 0) >= sig_created_ts
                    ]
                    if matching_trades:
                        realized_pnl_total = sum(float(t.get("realizedPnl", 0)) for t in matching_trades)
                        comm_total = sum(float(t.get("commission", 0)) for t in matching_trades)
                        close_fills = [t for t in matching_trades if float(t.get("realizedPnl", 0)) != 0]
                        exit_price = float(close_fills[-1].get("price")) if close_fills else None
                        close_time_ms = close_fills[-1].get("time") if close_fills else None

                        detail["trade_outcome"] = {
                            "realized_pnl": round(realized_pnl_total, 4),
                            "commission": round(comm_total, 4),
                            "net_pnl": round(realized_pnl_total - comm_total, 4),
                            "exit_price": exit_price,
                            "close_time": (
                                datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc)
                                .astimezone(VN_TZ)
                                .strftime("%d/%m/%Y %H:%M:%S")
                                if close_time_ms else None
                            ),
                            "fills_count": len(matching_trades),
                        }
            except Exception as e:
                logger.debug(f"Không thể truy vấn kết quả khớp lệnh Binance cho {sym}: {e}")

        return detail

    class ResolveSignalModel(BaseModel):
        new_state: str
        reason: str

    @router.post("/signals/{signal_id}/resolve", dependencies=[Depends(verify_token)])
    async def resolve_signal(signal_id: str, body: ResolveSignalModel):
        reason = body.reason.strip()
        if not reason:
            raise HTTPException(
                status_code=422,
                detail=make_error_response("RESOLVE_REASON_REQUIRED", "Lý do xử lý không được để trống."),
            )
        try:
            target_state = SignalState(body.new_state.strip().upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=make_error_response("INVALID_STATE", "Trạng thái không hợp lệ."))
        if target_state not in (SignalState.VALIDATED, SignalState.REJECTED):
            raise HTTPException(
                status_code=400,
                detail=make_error_response("INVALID_RESOLUTION_STATE", "Chỉ được chuyển sang VALIDATED hoặc REJECTED."),
            )
        current = trading_svc.signal_repo.get_signal(signal_id)
        if not current:
            raise HTTPException(status_code=404, detail=make_error_response("SIGNAL_NOT_FOUND", "Không tìm thấy tín hiệu."))
        if current.get("state") not in (SignalState.NEEDS_REVIEW.value, SignalState.NEEDS_POLICY.value):
            raise HTTPException(
                status_code=409,
                detail=make_error_response("RESOLVE_STATE_CONFLICT", "Tín hiệu không còn ở trạng thái chờ xử lý."),
            )

        success = trading_svc.resolve_signal_policy(signal_id, target_state, reason)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=make_error_response(
                    "RESOLVE_REJECTED",
                    "Không thể kích hoạt tín hiệu này: Vi phạm quy tắc an toàn hoặc tín hiệu đã quá hạn vào lệnh (stale).",
                ),
            )

        await event_bus.publish("signal_updated", {"signal_id": signal_id, "state": target_state.value})
        return {"success": True, "signal_id": signal_id, "new_state": target_state.value}

    # -------------------------------------------------------------
    # 4b. Channel Performance & Commercial Leaderboard
    # -------------------------------------------------------------
    @router.get("/channels/leaderboard", dependencies=[Depends(verify_token)])
    async def get_channel_leaderboard(
        timeframe: str = Query("all", pattern="^(all|month|week|day)$"),
        bankroll: Optional[float] = Query(None, ge=1.0),
        margin_pct: Optional[float] = Query(None, ge=0.1, le=50.0),
    ):
        target_bankroll = bankroll
        if target_bankroll is None:
            # Fallback to real Binance equity if connected
            cached_acc = binance_svc.get_cached_snapshot()
            eq = getattr(cached_acc, "equity", None) or getattr(cached_acc, "total_margin_balance", None)
            try:
                if eq and float(eq) > 0:
                    target_bankroll = float(eq)
            except Exception:
                pass
        if target_bankroll is None:
            target_bankroll = 86.18

        target_margin_pct = margin_pct
        if target_margin_pct is None:
            try:
                target_margin_pct = float(getattr(config.risk, "target_margin_pct", 1.5))
            except Exception:
                target_margin_pct = 1.5

        return channel_analytics_svc.get_channel_leaderboard(
            timeframe=timeframe,
            bankroll_usd=target_bankroll,
            margin_per_trade_pct=target_margin_pct,
        )

    @router.get("/channels/{chat_id}/detail", dependencies=[Depends(verify_token)])
    async def get_channel_detail(chat_id: int):
        return channel_analytics_svc.get_channel_detail(chat_id)

    # -------------------------------------------------------------
    # 5. Trading & Position Management
    # -------------------------------------------------------------
    @router.get("/trading/positions", dependencies=[Depends(verify_token)])
    async def get_trading_positions():
        account = binance_svc.get_cached_snapshot()
        if binance_svc.has_credentials():
            try:
                account = await asyncio.wait_for(binance_svc.sync_account(), timeout=8.0)
            except Exception:
                account = binance_svc.get_cached_snapshot()
        return trading_svc.get_open_positions(
            binance_positions=account.open_positions,
            binance_orders=account.active_orders,
        )


    @router.get("/trading/orders", dependencies=[Depends(verify_token)])
    async def get_trading_orders():
        account = binance_svc.get_cached_snapshot()
        if binance_svc.has_credentials():
            try:
                account = await binance_svc.sync_account()
            except Exception:
                pass
        return trading_svc.get_active_orders(binance_orders=account.active_orders)

    @router.get("/trading/trades", dependencies=[Depends(verify_token)])
    async def get_trading_trades(
        limit: int = Query(50, ge=1, le=200),
        days_back: int = Query(0, ge=0, le=3650),
    ):
        trades_list = []
        start_utc, end_utc = stats_svc.get_local_day_boundaries(days_back)
        start_ms = int(start_utc.timestamp() * 1000)
        end_ms = int(end_utc.timestamp() * 1000)
        if binance_svc.has_credentials():
            client = None
            try:
                client = BinanceFuturesClient(config)
                raw_trades = await client._request(
                    "GET",
                    "/fapi/v1/userTrades",
                    params={"limit": 1000, "startTime": start_ms, "endTime": end_ms},
                    signed=True,
                )
                # Binance returns trades in chronological ascending order; reverse so newest trades come first
                if raw_trades:
                    raw_trades = list(reversed(raw_trades))
                
                # Pre-fetch order -> signal -> chat_id mapping
                order_channel_map = {}
                symbol_channel_map = {}
                try:
                    with db.get_connection() as conn:
                        c = conn.cursor()
                        c.execute("""
                            SELECT o.exchange_order_id, s.chat_id
                            FROM orders o
                            JOIN signals s ON o.signal_id = s.signal_id
                            WHERE o.exchange_order_id IS NOT NULL
                        """)
                        for r in c.fetchall():
                            if r[0]:
                                order_channel_map[str(r[0])] = r[1]
                        c.execute("""
                            SELECT symbol, chat_id
                            FROM signals
                            ORDER BY updated_at ASC
                        """)
                        for r in c.fetchall():
                            if r[0] and r[1]:
                                symbol_channel_map[r[0]] = r[1]
                except Exception:
                    pass

                from services.channel_analytics_service import KNOWN_CHANNELS

                for tr in (raw_trades or [])[:limit]:
                    time_ms = tr.get("time") or 0
                    t_str = (
                        datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
                        .astimezone(VN_TZ)
                        .strftime("%d/%m/%Y %H:%M:%S")
                        if time_ms else "—"
                    )
                    pnl_val = float(tr.get("realizedPnl", 0))
                    ord_id = str(tr.get("orderId", ""))
                    sym = str(tr.get("symbol", ""))
                    chat_id = order_channel_map.get(ord_id) or symbol_channel_map.get(sym)
                    channel_name = KNOWN_CHANNELS.get(chat_id, "Thủ công / Khác") if chat_id else "Thủ công / Khác"

                    trades_list.append({
                        "id": str(tr.get("id")),
                        "order_id": ord_id,
                        "symbol": sym,
                        "side": "MUA (BUY)" if str(tr.get("side")).upper() == "BUY" else "BÁN (SELL)",
                        "price": str(tr.get("price")),
                        "qty": str(tr.get("qty")),
                        "commission": f"{float(tr.get('commission', 0)):.4f} {tr.get('commissionAsset', 'USDT')}",
                        "realized_pnl": pnl_val,
                        "is_closing": (pnl_val != 0),
                        "trade_type": "CHỐT LÃI / LỖ" if pnl_val != 0 else "MỞ VỊ THẾ",
                        "time": t_str,
                        "channel_name": channel_name,
                        "chat_id": chat_id,
                    })
            except Exception:
                pass
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass

        # Fallback to local SQLite database if Binance API call failed or returned empty
        if not trades_list:
            from services.channel_analytics_service import KNOWN_CHANNELS
            try:
                with db.get_connection() as conn:
                    c = conn.cursor()
                    c.execute("""
                        SELECT o.exchange_order_id, o.client_order_id, o.symbol, o.side, o.price, o.avg_fill_price,
                               o.quantity, o.filled_quantity, o.created_at, o.updated_at, s.chat_id, o.is_reduce_only
                        FROM orders o
                        LEFT JOIN signals s ON o.signal_id = s.signal_id
                        WHERE (o.status = 'FILLED' OR (o.filled_quantity IS NOT NULL AND CAST(o.filled_quantity AS REAL) > 0))
                          AND o.updated_at >= ? AND o.updated_at <= ?
                        ORDER BY o.created_at DESC
                        LIMIT ?
                    """, (start_utc.isoformat(), end_utc.isoformat(), limit))
                    for r in c.fetchall():
                        exch_id = str(r[0] or r[1])
                        sym = str(r[2])
                        side_str = "MUA (BUY)" if str(r[3]).upper() == "BUY" else "BÁN (SELL)"
                        fill_p = str(r[5] or r[4] or "0")
                        fill_q = str(r[7] or r[6] or "0")
                        t_raw = r[9] or r[8] or ""
                        try:
                            dt_obj = datetime.fromisoformat(str(t_raw).replace("Z", "+00:00"))
                            if dt_obj.tzinfo is None:
                                dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                            t_str = dt_obj.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M:%S")
                        except Exception:
                            t_str = str(t_raw)[:19]
                        chat_id = r[10]
                        channel_name = KNOWN_CHANNELS.get(chat_id, "Thủ công / Khác") if chat_id else "Thủ công / Khác"
                        trades_list.append({
                            "id": exch_id,
                            "order_id": exch_id,
                            "symbol": sym,
                            "side": side_str,
                            "price": fill_p,
                            "qty": fill_q,
                            "commission": "0.0000 USDT",
                            "realized_pnl": 0.0,
                            "time": t_str,
                            "channel_name": channel_name,
                            "chat_id": chat_id,
                        })
            except Exception:
                pass

        return trades_list

    class ToggleEntryModel(BaseModel):
        entry_enabled: bool

    @router.post("/trading/toggle-entry", dependencies=[Depends(verify_token)])
    async def toggle_entry(body: ToggleEntryModel):
        trading_svc.set_entry_enabled(body.entry_enabled)
        alert_svc.add_alert(
            AlertLevel.INFO if body.entry_enabled else AlertLevel.WARNING,
            "Thay đổi trạng thái nhận lệnh mới",
            f"Đã {'cho phép' if body.entry_enabled else 'tạm dừng'} nhận thêm vị thế mới.",
            "USER",
        )
        await event_bus.publish("trading_status_changed", {"entry_enabled": body.entry_enabled})
        return {"success": True, "entry_enabled": body.entry_enabled}

    class ClosePositionModel(BaseModel):
        symbol: str

    def require_live_close_confirmation(x_confirm_live: Optional[str]) -> None:
        if config.mode == ExecutionMode.LIVE and x_confirm_live != "CONFIRM_CLOSE_POSITION":
            raise HTTPException(
                status_code=403,
                detail=make_error_response("LIVE_CONFIRMATION_REQUIRED", "Thao tác đóng vị thế LIVE yêu cầu X-Confirm-Live: CONFIRM_CLOSE_POSITION."),
            )

    @router.post("/trading/close-position", dependencies=[Depends(verify_token)])
    async def close_position(body: ClosePositionModel, x_confirm_live: Optional[str] = Header(None)):
        # Strict validation: Backend rejects write operations when in READ_ONLY or LIVE without confirmation
        if not exchange_writes_enabled(config):
            raise HTTPException(
                status_code=403,
                detail=make_error_response(
                    "READ_ONLY_BLOCKED",
                    "Hệ thống đang ở chế độ READ_ONLY. Thao tác đóng lệnh sàn thật bị chặn hoàn toàn.",
                ),
            )
        require_live_close_confirmation(x_confirm_live)
        try:
            client = BinanceFuturesClient(config)
            # 1. Cancel all limit orders and algo orders for this symbol on Binance FIRST
            await client.cancel_all_symbol_orders(body.symbol)

            # 2. Find position side and amt to close via Market order
            pos = await client.get_position(body.symbol)
            if pos and float(pos.get("positionAmt", 0)) != 0:
                amt = abs(Decimal(str(pos.get("positionAmt"))))
                side = OrderSide.SELL if float(pos.get("positionAmt", 0)) > 0 else OrderSide.BUY
                await client.create_standard_order(
                    symbol=body.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=amt,
                    reduce_only=True,
                )
            remaining_pos = await client.get_position(body.symbol)
            remaining_amt = abs(Decimal(str(remaining_pos.get("positionAmt", "0")))) if remaining_pos else Decimal("0")
            if remaining_amt != Decimal("0"):
                raise RuntimeError(f"Vị thế {body.symbol} vẫn còn {remaining_amt} sau lệnh đóng")
            await client.close()

            # Update local orders and signal state
            order_repo.cancel_open_orders_for_symbol(body.symbol)
            active_sig = signal_repo.get_active_signal_for_symbol(body.symbol)
            if active_sig:
                signal_repo.update_signal_state(active_sig["signal_id"], SignalState.CLOSED, "Thủ công đóng vị thế từ người dùng")
                signal_repo.record_timeline_event(
                    active_sig["signal_id"],
                    "POSITION_CLOSED_MANUALLY",
                    f"Người dùng đã bấm đóng vị thế và hủy toàn bộ lệnh {body.symbol}",
                )

            alert_svc.add_alert(
                AlertLevel.WARNING,
                f"Đã đóng vị thế {body.symbol}",
                "Lệnh đóng thị trường (MARKET CLOSE) và hủy toàn bộ lệnh chờ đã hoàn tất trên Binance.",
                "USER",
            )
            return {"success": True, "symbol": body.symbol, "message": f"Đã đóng thành công vị thế và hủy toàn bộ lệnh {body.symbol}."}
        except Exception as e:
            alert_svc.add_alert(
                AlertLevel.CRITICAL,
                f"Lỗi đóng vị thế {body.symbol}",
                str(e),
                "USER",
            )
            raise HTTPException(status_code=500, detail=make_error_response("CLOSE_FAILED", str(e)))

    @router.post("/trading/close-all-bot", dependencies=[Depends(verify_token)])
    async def close_all_bot_positions(x_confirm_live: Optional[str] = Header(None)):
        if not exchange_writes_enabled(config):
            raise HTTPException(
                status_code=403,
                detail=make_error_response(
                    "READ_ONLY_BLOCKED",
                    "Hệ thống đang ở chế độ READ_ONLY. Thao tác đóng tất cả vị thế bị chặn hoàn toàn.",
                ),
            )
        require_live_close_confirmation(x_confirm_live)
        try:
            client = BinanceFuturesClient(config)
            owned_symbols = {
                row["symbol"]
                for row in db.get_connection().execute(
                    "SELECT DISTINCT symbol FROM signals WHERE state IN ('ENTRY_PENDING','PARTIALLY_FILLED','OPEN_PROTECTED','EXITING')"
                ).fetchall()
            }
            positions = [p for p in await client.get_open_positions() if p.get("symbol") in owned_symbols]
            closed_symbols = []
            for pos in positions:
                sym = pos.get("symbol")
                amt = abs(Decimal(str(pos.get("positionAmt"))))
                side = OrderSide.SELL if float(pos.get("positionAmt", 0)) > 0 else OrderSide.BUY
                await client.cancel_all_symbol_orders(sym)
                try:
                    await client.create_standard_order(
                        symbol=sym,
                        side=side,
                        order_type=OrderType.MARKET,
                        quantity=amt,
                        reduce_only=True,
                    )
                except Exception as ce:
                    raise RuntimeError(f"Không thể gửi lệnh đóng {sym}: {ce}") from ce
                try:
                    current = await client.get_position(sym)
                    remaining = abs(Decimal(str(current.get("positionAmt", "0")))) if current else Decimal("0")
                except Exception as ce:
                    raise RuntimeError(f"Không thể xác minh vị thế {sym} sau khi đóng: {ce}") from ce
                if remaining != Decimal("0"):
                    raise RuntimeError(f"Vị thế {sym} vẫn còn {remaining} sau lệnh đóng")
                order_repo.cancel_open_orders_for_symbol(sym)
                active_sig = signal_repo.get_active_signal_for_symbol(sym)
                if active_sig:
                    signal_repo.update_signal_state(active_sig["signal_id"], SignalState.CLOSED, "Đóng khẩn cấp tất cả vị thế")
                    signal_repo.record_timeline_event(
                        active_sig["signal_id"],
                        "POSITION_CLOSED_ALL",
                        f"Thao tác đóng khẩn cấp toàn bộ: Đã đóng {sym} và hủy các lệnh chờ",
                    )
                closed_symbols.append(sym)
            await client.close()
            alert_svc.add_alert(
                AlertLevel.CRITICAL,
                "Đã đóng TẤT CẢ vị thế",
                f"Đã đóng các cặp: {', '.join(closed_symbols)} và hủy toàn bộ lệnh",
                "USER",
            )
            return {"success": True, "message": f"Đã gửi lệnh đóng toàn bộ {len(closed_symbols)} vị thế và hủy toàn bộ lệnh chờ."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=make_error_response("CLOSE_ALL_FAILED", str(e)))

    @router.get("/trading/basket-guard-status", dependencies=[Depends(verify_token)])
    async def get_basket_guard_status():
        guard_state = getattr(reconciler, "basket_guard_state", {
            "basket_unrealized_pnl": 0.0,
            "basket_peak_unrealized": 0.0,
            "daily_profit_target_usdt": float(getattr(config.risk, "daily_profit_target_usdt", 8.0)),
            "daily_profit_target_enabled": bool(getattr(config.risk, "daily_profit_target_enabled", True)),
            "basket_trailing_enabled": bool(getattr(config.risk, "basket_trailing_enabled", True)),
            "basket_trailing_trigger_usdt": float(getattr(config.risk, "basket_trailing_trigger_usdt", 8.0)),
            "basket_trailing_pullback_pct": float(getattr(config.risk, "basket_trailing_pullback_pct", 25.0)),
            "today_realized_pnl": 0.0,
            "today_total_pnl": 0.0,
            "trailing_active": False,
            "pullback_threshold": 0.0,
            "daily_target_locked": False,
            "positions_count": 0,
        })
        return {"success": True, "data": guard_state}

    @router.post("/trading/start-bot", dependencies=[Depends(verify_token)])
    async def start_bot_engine():
        if trading_svc.get_engine_status() == EngineStatus.RUNNING_LISTEN:
            return {"success": True, "message": "Bot đang hoạt động giám sát.", "engine_status": "RUNNING_LISTEN"}
        trading_svc._listener_started = False
        asyncio.create_task(run_listener_loop())
        return {"success": True, "message": "Đang khởi động bot giám sát Telegram...", "engine_status": "STARTING"}

    @router.post("/trading/stop-bot", dependencies=[Depends(verify_token)])
    async def stop_bot_engine():
        trading_svc._listener_started = False
        if getattr(trading_svc, "_listener", None):
            try:
                await trading_svc._listener.stop()
            except Exception:
                pass
        trading_svc.set_engine_status(EngineStatus.STOPPED)
        await event_bus.publish("backend_status_changed", {"mode": config.mode.value, "engine": "STOPPED"})
        return {"success": True, "message": "Đã dừng giám sát bot.", "engine_status": "STOPPED"}

    # -------------------------------------------------------------
    # 6. Statistics & Performance
    # -------------------------------------------------------------
    @router.get("/stats/pnl", dependencies=[Depends(verify_token)])
    async def get_stats_pnl(days_back: int = Query(0, ge=0, le=3650)):
        if binance_svc.has_credentials():
            # Sync if last sync was > 30s ago
            if time.time() - last_income_sync["time"] > 30.0:
                client = None
                try:
                    client = BinanceFuturesClient(config)
                    await stats_svc.sync_binance_income(client, days_back=max(days_back, 30))
                    last_income_sync["time"] = time.time()
                except Exception:
                    pass
                finally:
                    if client is not None:
                        try:
                            await client.close()
                        except Exception:
                            pass

        summary = stats_svc.get_pnl_summary(days_back=days_back)
        return summary

    @router.get("/stats/pnl-chart", dependencies=[Depends(verify_token)])
    async def get_stats_pnl_chart():
        if binance_svc.has_credentials():
            if time.time() - last_income_sync["time"] > 30.0:
                client = None
                try:
                    client = BinanceFuturesClient(config)
                    await stats_svc.sync_binance_income(client, days_back=60)
                    last_income_sync["time"] = time.time()
                except Exception:
                    pass
                finally:
                    if client is not None:
                        try:
                            await client.close()
                        except Exception:
                            pass

        return stats_svc.get_pnl_chart_data()

    @router.post("/stats/sync", dependencies=[Depends(verify_token)])
    async def post_sync_stats():
        if not binance_svc.has_credentials():
            return {"success": False, "message": "Chưa kết nối Binance API."}
        client = None
        try:
            client = BinanceFuturesClient(config)
            res = await stats_svc.sync_binance_income(client, days_back=30)
            last_income_sync["time"] = time.time()
            return {"success": True, "details": res, "message": "Đã đồng bộ thành công dữ liệu PnL từ Binance."}
        except Exception as e:
            return {"success": False, "message": f"Đồng bộ thất bại: {e}"}
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass

    @router.get("/stats/telemetry", dependencies=[Depends(verify_token)])
    async def get_stats_telemetry():
        return stats_svc.get_telegram_telemetry()

    @router.get("/stats/coins", dependencies=[Depends(verify_token)])
    async def get_stats_coins(days_back: int = Query(0, ge=0, le=3650)):
        if binance_svc.has_credentials():
            client = None
            try:
                client = BinanceFuturesClient(config)
                coins = await stats_svc.get_coin_pnl_breakdown(client, days_back=days_back)
                return {"success": True, "coins": coins}
            except Exception as e:
                return {"success": False, "coins": [], "error": str(e)}
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass
        return {"success": True, "coins": []}

    # -------------------------------------------------------------
    # 7. Alerts & Logs
    # -------------------------------------------------------------
    @router.get("/alerts", dependencies=[Depends(verify_token)])
    async def get_alerts(limit: int = Query(50)):
        return alert_svc.get_alerts(limit=limit)

    @router.post("/alerts/mark-all-read", dependencies=[Depends(verify_token)])
    async def mark_all_alerts_read():
        count = alert_svc.mark_all_as_read()
        return {"success": True, "marked_count": count}

    # -------------------------------------------------------------
    # 8. Settings & Mode Safety
    # -------------------------------------------------------------
    @router.get("/settings", dependencies=[Depends(verify_token)])
    async def get_settings():
        return {
            "mode": config.mode.value,
            "live_trading_enabled": config.live_trading_enabled,
            "ferrari_mode_enabled": bool(getattr(config, "ferrari_mode_enabled", False)),
            "risk_per_signal_pct": float(config.risk.risk_per_signal_pct),
            "max_daily_loss_pct": float(config.risk.max_daily_loss_pct),
            "max_leverage": int(config.risk.max_leverage),
            "margin_mode": config.risk.margin_mode.value,
            "entry_range_policy": config.execution.entry_range_policy.value,
            "multi_tp_default_weight_mode": config.execution.multi_tp_default_weight_mode.value,
            "tp1_target_weight_pct": float(getattr(config.execution, "tp1_target_weight_pct", Decimal("35.0"))),
            "breakeven_after_tp1": bool(config.risk.breakeven_after_tp1_default),
            "sl_buffer_pct": float(getattr(config.risk, "sl_buffer_pct", Decimal("1.0"))),
            "max_active_signals": int(getattr(config.risk, "max_active_signals", 5)),
            "max_total_open_risk_pct": float(getattr(config.risk, "max_total_open_risk_pct", Decimal("150.0"))),
            "daily_profit_target_enabled": bool(getattr(config.risk, "daily_profit_target_enabled", True)),
            "daily_profit_target_usdt": float(getattr(config.risk, "daily_profit_target_usdt", Decimal("8.0"))),
            "basket_trailing_enabled": bool(getattr(config.risk, "basket_trailing_enabled", True)),
            "basket_trailing_trigger_usdt": float(getattr(config.risk, "basket_trailing_trigger_usdt", Decimal("8.0"))),
            "basket_trailing_pullback_pct": float(getattr(config.risk, "basket_trailing_pullback_pct", Decimal("25.0"))),
        }

    class UpdateSettingsModel(BaseModel):
        mode: str
        live_trading_enabled: bool
        risk_per_signal_pct: float
        max_daily_loss_pct: float
        max_leverage: int
        entry_range_policy: str
        multi_tp_default_weight_mode: str
        margin_mode: Optional[str] = "CROSSED"
        tp1_target_weight_pct: Optional[float] = 35.0
        breakeven_after_tp1: Optional[bool] = True
        sl_buffer_pct: Optional[float] = 1.0
        max_active_signals: Optional[int] = 5
        ferrari_mode_enabled: Optional[bool] = False
        max_total_open_risk_pct: Optional[float] = None
        daily_profit_target_enabled: Optional[bool] = None
        daily_profit_target_usdt: Optional[float] = None
        basket_trailing_enabled: Optional[bool] = None
        basket_trailing_trigger_usdt: Optional[float] = None
        basket_trailing_pullback_pct: Optional[float] = None

    @router.post("/settings", dependencies=[Depends(verify_token)])
    async def update_settings(
        body: UpdateSettingsModel,
        x_confirm_live: Optional[str] = Header(None),
    ):
        target_mode = body.mode.strip().upper()
        if not math.isfinite(body.risk_per_signal_pct) or not math.isfinite(body.max_daily_loss_pct):
            raise HTTPException(status_code=422, detail=make_error_response("INVALID_RISK_SETTINGS", "Risk phải là số hữu hạn."))
        if body.tp1_target_weight_pct is not None and not math.isfinite(body.tp1_target_weight_pct):
            raise HTTPException(status_code=422, detail=make_error_response("INVALID_TP_WEIGHT", "TP1 weight phải là số hữu hạn."))
        if body.sl_buffer_pct is not None and not math.isfinite(body.sl_buffer_pct):
            raise HTTPException(status_code=422, detail=make_error_response("INVALID_SL_BUFFER", "SL buffer phải là số hữu hạn."))

        # Strict LIVE gating: Cannot enable LIVE without valid Binance credentials and explicit confirmation
        if target_mode == "LIVE" or body.live_trading_enabled:
            if not config.binance.live_api_key or not config.binance.live_api_secret:
                raise HTTPException(
                    status_code=400,
                    detail=make_error_response(
                        "LIVE_GATES_FAILED",
                        "Không thể kích hoạt LIVE: Thiếu cấu hình Binance Live API Key/Secret.",
                    ),
                )
            if x_confirm_live != "ENABLE_LIVE_TRADING":
                raise HTTPException(
                    status_code=400,
                    detail=make_error_response(
                        "LIVE_CONFIRMATION_REQUIRED",
                        "Kích hoạt LIVE yêu cầu gửi Header xác nhận an toàn: X-Confirm-Live: ENABLE_LIVE_TRADING",
                    ),
                )

        try:
            target_mode_enum = ExecutionMode(target_mode)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=make_error_response("INVALID_MODE", f"Chế độ thực thi không hợp lệ: {target_mode}"),
            )

        if target_mode == "LIVE" and not body.live_trading_enabled:
            raise HTTPException(
                status_code=400,
                detail=make_error_response("INVALID_MODE_COMBINATION", "LIVE yêu cầu live_trading_enabled=true."),
            )
        if target_mode != "LIVE" and body.live_trading_enabled:
            raise HTTPException(
                status_code=400,
                detail=make_error_response("INVALID_MODE_COMBINATION", "live_trading_enabled chỉ hợp lệ với LIVE."),
            )
        if body.risk_per_signal_pct <= 0 or body.risk_per_signal_pct > 10 or body.max_daily_loss_pct <= 0 or body.max_daily_loss_pct > 20 or body.max_leverage <= 0 or body.max_leverage > 125:
            raise HTTPException(
                status_code=400,
                detail=make_error_response("INVALID_RISK_SETTINGS", "Risk và leverage phải lớn hơn 0."),
            )

        config.mode = target_mode_enum
        config.live_trading_enabled = body.live_trading_enabled
        config.risk.risk_per_signal_pct = Decimal(str(min(body.risk_per_signal_pct, 10.0)))
        config.risk.max_daily_loss_pct = Decimal(str(min(body.max_daily_loss_pct, 20.0)))
        config.risk.max_leverage = body.max_leverage
        margin_mode = str(body.margin_mode or "CROSSED").strip().upper()
        if margin_mode in ("CROSS", "CROSSED"):
            config.risk.margin_mode = MarginMode.CROSSED
        elif margin_mode == "ISOLATED":
            config.risk.margin_mode = MarginMode.ISOLATED
        else:
            raise HTTPException(status_code=400, detail=make_error_response("INVALID_MARGIN_MODE", "Margin mode phải là ISOLATED hoặc CROSSED."))
        entry_policy = ExecutionPolicyConfig.normalize_entry_range(body.entry_range_policy)
        if not isinstance(entry_policy, EntryRangePolicy) or entry_policy == EntryRangePolicy.NEEDS_POLICY:
            raise HTTPException(status_code=400, detail=make_error_response("INVALID_ENTRY_RANGE_POLICY", "Entry range policy không hợp lệ."))
        tp_policy = ExecutionPolicyConfig.normalize_multi_tp(body.multi_tp_default_weight_mode)
        if not isinstance(tp_policy, MultiTPWeightMode) or tp_policy == MultiTPWeightMode.NEEDS_POLICY:
            raise HTTPException(status_code=400, detail=make_error_response("INVALID_TP_POLICY", "Multi-TP policy không hợp lệ."))
        config.execution.entry_range_policy = entry_policy
        config.execution.multi_tp_default_weight_mode = tp_policy
        if body.tp1_target_weight_pct is not None:
            config.execution.tp1_target_weight_pct = Decimal(str(body.tp1_target_weight_pct))
        if body.breakeven_after_tp1 is not None:
            config.risk.breakeven_after_tp1_default = bool(body.breakeven_after_tp1)
        if body.sl_buffer_pct is not None:
            config.risk.sl_buffer_pct = Decimal(str(body.sl_buffer_pct))
        if body.max_active_signals is not None:
            if body.max_active_signals < 1 or body.max_active_signals > 50:
                raise HTTPException(status_code=400, detail=make_error_response("INVALID_ACTIVE_SIGNALS", "max_active_signals phải trong khoảng 1-50."))
            config.risk.max_active_signals = body.max_active_signals

        if body.ferrari_mode_enabled is not None:
            config.ferrari_mode_enabled = bool(body.ferrari_mode_enabled)
            if config.ferrari_mode_enabled:
                config.risk.max_leverage = 40
                config.risk.default_leverage = 35
                config.risk.max_total_open_risk_pct = Decimal("150.0")
                config.risk.max_margin_per_trade_pct = Decimal("15.0")
                config.risk.risk_per_signal_pct = Decimal("5.0")
                config.risk.max_active_signals = 20
                config.risk.breakeven_after_tp1_default = True
                config.execution.multi_tp_default_weight_mode = MultiTPWeightMode.FIXED_35_35_30
                config.execution.tp1_target_weight_pct = Decimal("35.0")
                config.execution.breakeven_trigger_tp_index = 1
            else:
                config.risk.max_leverage = 20
                config.risk.default_leverage = 15
                config.risk.max_total_open_risk_pct = Decimal("20.0")
                config.risk.max_margin_per_trade_pct = Decimal("5.0")
                config.risk.risk_per_signal_pct = Decimal("1.5")
                config.risk.max_active_signals = 3
                config.risk.breakeven_after_tp1_default = True
                config.execution.multi_tp_default_weight_mode = MultiTPWeightMode.FIXED_35_35_30
                config.execution.tp1_target_weight_pct = Decimal("35.0")
                config.execution.breakeven_trigger_tp_index = 1

        if body.max_total_open_risk_pct is not None:
            config.risk.max_total_open_risk_pct = Decimal(str(body.max_total_open_risk_pct))

        if body.daily_profit_target_enabled is not None:
            config.risk.daily_profit_target_enabled = bool(body.daily_profit_target_enabled)
        if body.daily_profit_target_usdt is not None:
            if body.daily_profit_target_usdt <= 0 or not math.isfinite(body.daily_profit_target_usdt):
                raise HTTPException(status_code=400, detail=make_error_response("INVALID_SETTINGS", "Chỉ tiêu lãi ngày phải lớn hơn 0."))
            config.risk.daily_profit_target_usdt = Decimal(str(body.daily_profit_target_usdt))
        if body.basket_trailing_enabled is not None:
            config.risk.basket_trailing_enabled = bool(body.basket_trailing_enabled)
        if body.basket_trailing_trigger_usdt is not None:
            if body.basket_trailing_trigger_usdt <= 0 or not math.isfinite(body.basket_trailing_trigger_usdt):
                raise HTTPException(status_code=400, detail=make_error_response("INVALID_SETTINGS", "Ngưỡng trailing rổ phải lớn hơn 0."))
            config.risk.basket_trailing_trigger_usdt = Decimal(str(body.basket_trailing_trigger_usdt))
        if body.basket_trailing_pullback_pct is not None:
            if body.basket_trailing_pullback_pct <= 0 or body.basket_trailing_pullback_pct >= 100 or not math.isfinite(body.basket_trailing_pullback_pct):
                raise HTTPException(status_code=400, detail=make_error_response("INVALID_SETTINGS", "% hồi lui phải nằm trong khoảng (0, 100)."))
            config.risk.basket_trailing_pullback_pct = Decimal(str(body.basket_trailing_pullback_pct))

        save_config(config)

        await event_bus.publish("backend_status_changed", {"mode": config.mode.value, "live": config.live_trading_enabled, "ferrari": getattr(config, "ferrari_mode_enabled", False)})
        return {
            "success": True,
            "settings": {
                "mode": config.mode.value,
                "live_trading_enabled": config.live_trading_enabled,
                "ferrari_mode_enabled": bool(getattr(config, "ferrari_mode_enabled", False)),
                "risk_per_signal_pct": float(config.risk.risk_per_signal_pct),
                "max_daily_loss_pct": float(config.risk.max_daily_loss_pct),
                "max_leverage": int(config.risk.max_leverage),
                "margin_mode": config.risk.margin_mode.value,
                "entry_range_policy": config.execution.entry_range_policy.value,
                "multi_tp_default_weight_mode": config.execution.multi_tp_default_weight_mode.value,
                "tp1_target_weight_pct": float(config.execution.tp1_target_weight_pct),
                "breakeven_after_tp1": bool(config.risk.breakeven_after_tp1_default),
                "sl_buffer_pct": float(config.risk.sl_buffer_pct),
                "max_active_signals": int(config.risk.max_active_signals),
                "max_total_open_risk_pct": float(getattr(config.risk, "max_total_open_risk_pct", Decimal("150.0"))),
                "daily_profit_target_enabled": bool(getattr(config.risk, "daily_profit_target_enabled", True)),
                "daily_profit_target_usdt": float(getattr(config.risk, "daily_profit_target_usdt", Decimal("8.0"))),
                "basket_trailing_enabled": bool(getattr(config.risk, "basket_trailing_enabled", True)),
                "basket_trailing_trigger_usdt": float(getattr(config.risk, "basket_trailing_trigger_usdt", Decimal("8.0"))),
                "basket_trailing_pullback_pct": float(getattr(config.risk, "basket_trailing_pullback_pct", Decimal("25.0"))),
            },
        }

    class ToggleFerrariModel(BaseModel):
        ferrari_mode_enabled: bool

    @router.post("/trading/toggle-ferrari-mode", dependencies=[Depends(verify_token)])
    async def toggle_ferrari_mode(body: ToggleFerrariModel):
        config.ferrari_mode_enabled = bool(body.ferrari_mode_enabled)
        if config.ferrari_mode_enabled:
            config.risk.max_leverage = 40
            config.risk.default_leverage = 35
            config.risk.max_total_open_risk_pct = Decimal("150.0")
            config.risk.max_margin_per_trade_pct = Decimal("15.0")
            config.risk.risk_per_signal_pct = Decimal("5.0")
            config.risk.max_active_signals = 20
            config.risk.breakeven_after_tp1_default = True
            config.execution.multi_tp_default_weight_mode = MultiTPWeightMode.FIXED_35_35_30
            config.execution.tp1_target_weight_pct = Decimal("35.0")
            config.execution.breakeven_trigger_tp_index = 1
            msg = "Đã BẬT FERRARI MODE (Xác nhận chấp nhận rủi ro lớn để săn lợi nhuận lớn: Đòn bẩy 35x-40x, Khối lượng 5.0%, Bỏ van chờ 15 phút, Khớp mọi kèo đạt chuẩn)!"
        else:
            config.risk.max_leverage = 20
            config.risk.default_leverage = 15
            config.risk.max_total_open_risk_pct = Decimal("20.0")
            config.risk.max_margin_per_trade_pct = Decimal("5.0")
            config.risk.risk_per_signal_pct = Decimal("1.5")
            config.risk.max_active_signals = 3
            config.execution.multi_tp_default_weight_mode = MultiTPWeightMode.FIXED_35_35_30
            config.execution.tp1_target_weight_pct = Decimal("35.0")
            config.execution.breakeven_trigger_tp_index = 1
            msg = "Đã TẮT Ferrari Mode ➔ TỰ ĐỘNG KÍCH HOẠT CHẾ ĐỘ AN TOÀN (Đòn bẩy 15x-20x, Giãn cách 15p, Rủi ro 1.5%, Bảo toàn vốn Zero-Liquidation)!"

        save_config(config)
        await event_bus.publish("backend_status_changed", {"ferrari_mode_enabled": config.ferrari_mode_enabled})
        return {
            "success": True,
            "ferrari_mode_enabled": config.ferrari_mode_enabled,
            "message": msg,
        }

    # -------------------------------------------------------------
    # 8b. Gemini Autonomous AI & Quant Trader Endpoints
    # -------------------------------------------------------------
    class AIConfigModel(BaseModel):
        enabled: Optional[bool] = None
        gemini_api_key: Optional[str] = None
        preferred_model: Optional[str] = None
        scan_interval_minutes: Optional[int] = None
        min_confidence: Optional[int] = None
        watchlist: Optional[List[str]] = None

    class AIExecuteModel(BaseModel):
        setup: Dict[str, Any]

    @router.get("/ai/status", dependencies=[Depends(verify_token)])
    async def get_ai_status():
        from services.gemini_key_rotator import GeminiKeyRotator
        rotator = GeminiKeyRotator.get_instance()
        key_pool_status = rotator.get_pool_status()

        key = ai_trader.gemini_api_key
        key_masked = None
        if key and len(key) >= 8:
            key_masked = f"{key[:4]}...{key[-4:]}"
        return {
            "enabled": ai_trader.enabled,
            "has_gemini_key": bool(key) or key_pool_status.get("has_healthy", False),
            "gemini_key_masked": key_masked,
            "preferred_model": getattr(ai_trader, "preferred_model", "gemini-3.5-flash"),
            "scan_interval_minutes": ai_trader.scan_interval_minutes,
            "min_confidence": ai_trader.min_confidence,
            "watchlist": ai_trader.watchlist,
            "last_scan_time": ai_trader.last_scan_time,
            "last_scan_results": ai_trader.last_scan_results,
            "last_scan_skipped_symbols": getattr(ai_trader, "last_scan_skipped_symbols", []),
            "last_scan_symbol_validation_error": getattr(ai_trader, "last_scan_symbol_validation_error", None),
            "is_scanning": getattr(ai_trader, "_is_scanning", False),
            "quota_status": getattr(ai_trader, "_quota_status", "NORMAL"),
            "cooldown_remaining_seconds": ai_trader.get_cooldown_remaining(),
            "daily_api_calls": getattr(ai_trader, "_daily_api_calls", 0),
            "key_pool": key_pool_status,
        }

    @router.post("/ai/config", dependencies=[Depends(verify_token)])
    async def update_ai_config(body: AIConfigModel):
        if body.enabled is not None:
            ai_trader.enabled = body.enabled
            config.ai.enabled = body.enabled
        if body.gemini_api_key is not None:
            clean_key = body.gemini_api_key.strip()
            ai_trader.gemini_api_key = clean_key if clean_key else None
            ai_trader._gemini_key_invalid = False
            config.ai.api_key = clean_key if clean_key else None
            os.environ["GEMINI_API_KEY"] = clean_key

            from services.gemini_key_rotator import GeminiKeyRotator
            rotator = GeminiKeyRotator.get_instance()
            raw_keys = [k.strip() for k in re.split(r"[,;\n\r\t]+", clean_key) if k.strip()]
            if raw_keys:
                rotator.set_keys(raw_keys)
            elif not clean_key:
                rotator.set_keys([])
        if body.preferred_model is not None:
            clean_m = body.preferred_model.strip()
            ai_trader.preferred_model = clean_m
            config.ai.preferred_model = clean_m
        if body.scan_interval_minutes is not None:
            val = max(1, body.scan_interval_minutes)
            ai_trader.scan_interval_minutes = val
            config.ai.scan_interval_minutes = val
        if body.min_confidence is not None:
            c_val = int(body.min_confidence)
            if c_val <= 82:
                val = 80
            elif c_val <= 87:
                val = 85
            else:
                val = 90
            ai_trader.min_confidence = val
            config.ai.min_confidence = val
        if body.watchlist is not None:
            clean_list = [s.upper().strip() for s in body.watchlist if s.strip()]
            ai_trader.watchlist = clean_list
            config.ai.watchlist = clean_list

        save_config(config)
        key = ai_trader.gemini_api_key
        key_masked = f"{key[:4]}...{key[-4:]}" if key and len(key) >= 8 else None
        return {
            "success": True,
            "enabled": ai_trader.enabled,
            "has_gemini_key": bool(key),
            "gemini_key_masked": key_masked,
            "scan_interval_minutes": ai_trader.scan_interval_minutes,
            "min_confidence": ai_trader.min_confidence,
            "watchlist": ai_trader.watchlist,
        }

    @router.post("/ai/scan-now", dependencies=[Depends(verify_token)])
    async def trigger_ai_scan():
        if not ai_trader.gemini_api_key and not ai_trader.enabled:
            return {"success": False, "count": 0, "setups": [], "message": "AI trader đang tắt"}
        if getattr(ai_trader, "_is_scanning", False):
            return {
                "success": False,
                "message": "Quá trình quét thị trường đang diễn ra...",
                "setups": ai_trader.last_scan_results,
            }
        setups = await ai_trader.scan_market()
        return {
            "success": True,
            "count": len(setups),
            "setups": setups,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @router.post("/ai/execute-setup", dependencies=[Depends(verify_token)])
    async def execute_ai_setup(body: AIExecuteModel):
        if not exchange_writes_enabled(config):
            raise HTTPException(
                status_code=403,
                detail=make_error_response("EXCHANGE_WRITE_BLOCKED", "AI execution bị chặn trong mode hiện tại."),
            )
        res = await ai_trader.execute_setup(body.setup, bypass_cooldown=True)
        if res.get("status") == "SUCCESS":
            alert_svc.add_alert(
                AlertLevel.INFO,
                "Khớp Lệnh Theo AI Thành Công",
                f"Vào lệnh {res.get('side')} {res.get('symbol')} khối lượng {res.get('quantity')} @ {res.get('entry_price')}.",
                "AI_TRADER",
            )
            return {"success": True, "result": res}
        else:
            return {"success": False, "reason": res.get("reason", "Lỗi không xác định")}

    class AICouncilDebateRequest(BaseModel):
        symbol: str
        direction: Optional[str] = None
        entry_price: Optional[float] = None
        stop_loss: Optional[float] = None
        take_profit_1: Optional[float] = None
        broadcast: bool = True

    @router.post("/ai/council-debate", dependencies=[Depends(verify_token)])
    async def run_ai_council_debate(body: AICouncilDebateRequest):
        """
        Triệu tập Hội Đồng Lượng Tử AI thẩm định và tranh biện cho cặp giao dịch.
        Tự động phát sóng cuộc đối chất của 5 tác tử AI lên Telegram nếu broadcast=True.
        """
        sym = body.symbol.upper().replace("/", "").replace(":", "")
        params = {}
        if body.direction:
            params["direction"] = body.direction.upper()
        if body.entry_price:
            params["entry_price"] = body.entry_price
        if body.stop_loss:
            params["stop_loss"] = body.stop_loss
        if body.take_profit_1:
            params["take_profit_1"] = body.take_profit_1

        if hasattr(ai_trader, "evaluate_and_broadcast_debate"):
            delib = await ai_trader.evaluate_and_broadcast_debate(sym, custom_params=params, broadcast=body.broadcast)
        else:
            from services.quantum_council_harness import QuantumCouncilArbiter
            arbiter = QuantumCouncilArbiter(config=config, binance_client=binance_svc.client if binance_svc else None)
            delib = await arbiter.deliberate(sym, params)
            if body.broadcast and getattr(delib, "debate_html", None):
                alert_svc.add_alert(
                    AlertLevel.INFO,
                    f"Quantum Council: {sym}",
                    delib.debate_html,
                    "AI_COUNCIL",
                )

        return {
            "success": True,
            "symbol": sym,
            "deliberation": delib.to_dict() if hasattr(delib, "to_dict") else delib,
            "debate_html": getattr(delib, "debate_html", ""),
        }

    # -------------------------------------------------------------
    # 9. Graceful Shutdown Endpoint
    # -------------------------------------------------------------
    @router.post("/shutdown", dependencies=[Depends(verify_token)])
    async def graceful_shutdown():
        """
        Gracefully terminates backend server after delivering HTTP 200 response.
        """
        alert_svc.add_alert(
            AlertLevel.INFO,
            "Tắt hệ thống Backend",
            "Đã nhận yêu cầu tắt an toàn từ tiến trình giám sát.",
            "SUPERVISOR",
        )
        def _terminate():
            try:
                import sys
                sys.exit(0)
            finally:
                os._exit(0)

        loop = asyncio.get_running_loop()
        loop.call_later(0.4, _terminate)
        return {"success": True, "message": "Backend đang tắt an toàn..."}

    # -------------------------------------------------------------
    # 10. Realtime WebSocket with First-Message Auth Protocol
    # -------------------------------------------------------------
    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        # 1. Verify Origin Header
        origin = websocket.headers.get("origin")
        allowed_prefixes = (
            "http://localhost",
            "http://127.0.0.1",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        )
        if origin and not any(origin.startswith(p) for p in allowed_prefixes):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.accept()

        # 2. First-message Ticket Authentication
        # Client MUST send {"type": "AUTH", "token": "..."} within 5.0 seconds.
        # No business data or snapshot is sent before valid authentication.
        try:
            raw_text = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            auth_msg = json.loads(raw_text)
            if auth_msg.get("type") != "AUTH" or auth_msg.get("token") != session_token:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="AUTH_FAILED")
                return
        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            try:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="AUTH_TIMEOUT")
            except Exception:
                pass
            return

        # 3. Authenticated: Register to EventBus & Send Confirmation
        await event_bus.subscribe(websocket)
        try:
            await websocket.send_json({
                "event_type": "AUTH_SUCCESS",
                "timestamp": stats_svc.get_local_day_boundaries(0)[1].isoformat(),
                "payload": {
                    "status": "AUTHENTICATED",
                    "mode": config.mode.value,
                    "engine": trading_svc.get_engine_status().value,
                    "entry_enabled": trading_svc.is_entry_enabled(),
                },
            })

            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            await event_bus.unsubscribe(websocket)
        except Exception:
            await event_bus.unsubscribe(websocket)

    # -------------------------------------------------------------
    # SUSTAINABLE PROFIT PILLARS: Market Regime & Smart Queue
    # -------------------------------------------------------------
    @router.get("/market-regime", dependencies=[Depends(verify_token)])
    async def get_market_regime():
        if not global_market_regime_shield.is_cache_valid() and binance_svc.has_credentials():
            client = None
            try:
                client = BinanceFuturesClient(config)
                await global_market_regime_shield.update_regime(client)
            except Exception:
                pass
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass
        return global_market_regime_shield.current_regime

    @router.get("/trading/smart-queue", dependencies=[Depends(verify_token)])
    async def get_smart_queue():
        return {
            "items": global_signal_queue_service.get_queue_summary(),
            "count": global_signal_queue_service.size(),
        }

    @router.get("/capital-stage", dependencies=[Depends(verify_token)])
    async def get_capital_stage():
        cached = binance_svc.get_cached_snapshot()
        raw_equity = getattr(cached, "total_margin_balance", None) or getattr(cached, "equity", None)
        if raw_equity and Decimal(str(raw_equity)) > Decimal("0"):
            equity = Decimal(str(raw_equity))
        elif binance_svc.has_credentials():
            try:
                equity = await binance_client.get_account_equity()
            except Exception:
                equity = Decimal("92.21")
        else:
            equity = Decimal("92.21")
        is_ferrari = bool(getattr(config, "ferrari_mode_enabled", False))
        max_pos = int(getattr(config.risk, "max_active_signals", 20 if is_ferrari else 4))
        return RiskEngine.get_compounding_stage(equity, max_positions_override=max_pos, ferrari_mode=is_ferrari)

    return router
