import asyncio
from decimal import Decimal
import hashlib
import json
import os
import signal
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from backend.api.auth_middleware import make_error_response
from backend.events.event_bus import event_bus
from config.config import AppConfig, save_config
from config.policy_defaults import ExecutionPolicyConfig
from core.enums import ExecutionMode, OrderSide, OrderType, SignalState, UpdateType
from core.models import SourceMetadata
from parser.normalizer import normalize_text
from parser.signal_parser import SignalParser
from parser.update_parser import ChannelUpdateParser
from parser.validator import SignalValidator
from services.alert_service import AlertLevel, AlertService
from services.binance_service import BinanceService
from services.channel_analytics_service import ChannelAnalyticsService
from services.stats_service import StatsService
from services.telegram_service import TelegramService
from services.trading_service import EngineStatus, TradingService
from storage.database import DatabaseManager, OrderRepository, SignalRepository
from exchange.binance_client import BinanceFuturesClient
from execution.order_manager import OrderManager
from execution.position_manager import PositionManager
from execution.reconciliation import ReconciliationEngine
from risk.risk_engine import RiskEngine
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
    alert_svc = AlertService.get_instance()
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

    # Active Reconciliation Background Worker (Guarded against duplicate execution)
    async def run_reconciliation_worker():
        if getattr(trading_svc, "_reconciliation_started", False):
            return
        trading_svc._reconciliation_started = True
        while True:
            try:
                if binance_svc.has_credentials():
                    from exchange.binance_client import BinanceFuturesClient
                    if BinanceFuturesClient.is_rate_limited():
                        await asyncio.sleep(5.0)
                        continue
                    await reconciler.reconcile_all()
            except Exception:
                pass
            await asyncio.sleep(20.0)

    router.reconciliation_task_starter = run_reconciliation_worker


    # Auto-start Telegram listener in background if session authorized
    async def run_listener_loop():
        if getattr(trading_svc, "_listener_started", False):
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
                is_shadow=False,
            )
            trading_svc._listener = listener
            trading_svc.set_engine_status(EngineStatus.RUNNING_LISTEN)

            print("\n" + "=" * 60)
            print("[TELEGRAM BOT TRADE DEMO] DA KHOI DONG THANH CONG!")
            print(f"- Mode: {config.mode.value} (Dat lenh truc tiep tren Binance Demo)")
            print(f"- So luong kenh theo doi: {len(config.telegram.allowed_chat_ids)} nhom")
            print("=" * 60 + "\n")

            alert_svc.add_alert(
                AlertLevel.INFO,
                "Bot Trade Demo Đã Sẵn Sàng",
                f"Đang giám sát {len(config.telegram.allowed_chat_ids)} nhóm ghim đã duyệt và sẵn sàng vào lệnh trên Binance ({config.mode.value}).",
                "BOT_ENGINE",
            )
            await event_bus.publish("backend_status_changed", {"mode": config.mode.value, "engine": "RUNNING_LISTEN"})

            await listener.start()
        except Exception as e:
            print(f"[TELEGRAM LISTENER ERROR] {e}")
            trading_svc.set_engine_status(EngineStatus.ERROR)

    router.listener_task_starter = run_listener_loop

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(run_listener_loop())
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
            "version": "2.0.0",
            "mode": config.mode.value,
            "live_trading_enabled": config.live_trading_enabled,
            "engine_status": trading_svc.get_engine_status().value,
            "entry_enabled": trading_svc.is_entry_enabled(),
        }

    @router.get("/handshake")
    async def get_handshake():
        return {
            "status": "READY",
            "host": "127.0.0.1",
            "session_token": session_token,
        }

    @router.get("/snapshot", dependencies=[Depends(verify_token)])
    async def get_snapshot():
        telemetry = stats_svc.get_telegram_telemetry()
        pnl_today = stats_svc.get_pnl_summary(0)
        pnl_7d = stats_svc.get_pnl_summary(6)
        recent_alerts = alert_svc.get_alerts(limit=20)
        account = binance_svc.get_cached_snapshot()
        if binance_svc.has_credentials():
            try:
                account = await asyncio.wait_for(binance_svc.sync_account(force=False), timeout=2.0)
            except Exception:
                account = binance_svc.get_cached_snapshot()


        positions = trading_svc.get_open_positions(binance_positions=account.open_positions)
        orders = trading_svc.get_active_orders(binance_orders=account.active_orders)

        return {
            "mode": config.mode.value,
            "live_trading_enabled": config.live_trading_enabled,
            "engine_status": trading_svc.get_engine_status().value,
            "entry_enabled": trading_svc.is_entry_enabled(),
            "account": account.model_dump(),
            "telemetry": telemetry,
            "pnl_today": pnl_today,
            "pnl_7d": pnl_7d,
            "positions": positions,
            "orders": orders,
            "alerts": recent_alerts,
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
        alert_svc.add_alert(
            AlertLevel.INFO,
            "Cập nhật danh sách theo dõi",
            f"Đã cập nhật: {len(body.allowed_chat_ids)} kênh được theo dõi.",
            "USER",
        )
        return {"success": True, "allowed_chat_ids": config.telegram.allowed_chat_ids}

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
        limit: int = Query(200),
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
        return detail

    class ResolveSignalModel(BaseModel):
        new_state: str
        reason: str

    @router.post("/signals/{signal_id}/resolve", dependencies=[Depends(verify_token)])
    async def resolve_signal(signal_id: str, body: ResolveSignalModel):
        try:
            target_state = SignalState(body.new_state)
        except ValueError:
            raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ.")

        success = trading_svc.resolve_signal_policy(signal_id, target_state, body.reason)
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
        bankroll: float = Query(5000.0, ge=100.0),
        margin_pct: float = Query(5.0, ge=0.5, le=50.0),
    ):
        return channel_analytics_svc.get_channel_leaderboard(
            timeframe=timeframe,
            bankroll_usd=bankroll,
            margin_per_trade_pct=margin_pct,
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
                account = await asyncio.wait_for(binance_svc.sync_account(), timeout=1.5)
            except Exception:
                account = binance_svc.get_cached_snapshot()
        return trading_svc.get_open_positions(binance_positions=account.open_positions)


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
    async def get_trading_trades(limit: int = Query(50)):
        trades_list = []
        if binance_svc.has_credentials():
            try:
                client = BinanceFuturesClient(config)
                raw_trades = await client._request("GET", "/fapi/v1/userTrades", params={"limit": limit}, signed=True)
                for tr in (raw_trades or []):
                    time_ms = tr.get("time") or 0
                    t_str = datetime.fromtimestamp(time_ms / 1000).strftime("%d/%m/%Y %H:%M:%S") if time_ms else "—"
                    pnl_val = float(tr.get("realizedPnl", 0))
                    trades_list.append({
                        "id": str(tr.get("id")),
                        "symbol": str(tr.get("symbol")),
                        "side": "MUA (BUY)" if str(tr.get("side")).upper() == "BUY" else "BÁN (SELL)",
                        "price": str(tr.get("price")),
                        "qty": str(tr.get("qty")),
                        "commission": f"{float(tr.get('commission', 0)):.4f} {tr.get('commissionAsset', 'USDT')}",
                        "realized_pnl": pnl_val,
                        "time": t_str,
                    })
                await client.close()
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

    @router.post("/trading/close-position", dependencies=[Depends(verify_token)])
    async def close_position(body: ClosePositionModel):
        # Strict validation: Backend rejects write operations when in READ_ONLY or LIVE without confirmation
        if config.mode == ExecutionMode.READ_ONLY or (config.mode == ExecutionMode.LIVE and not config.live_trading_enabled):
            raise HTTPException(
                status_code=403,
                detail=make_error_response(
                    "READ_ONLY_BLOCKED",
                    "Hệ thống đang ở chế độ READ_ONLY. Thao tác đóng lệnh sàn thật bị chặn hoàn toàn.",
                ),
            )
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
    async def close_all_bot_positions():
        if config.mode == ExecutionMode.READ_ONLY or (config.mode == ExecutionMode.LIVE and not config.live_trading_enabled):
            raise HTTPException(
                status_code=403,
                detail=make_error_response(
                    "READ_ONLY_BLOCKED",
                    "Hệ thống đang ở chế độ READ_ONLY. Thao tác đóng tất cả vị thế bị chặn hoàn toàn.",
                ),
            )
        try:
            client = BinanceFuturesClient(config)
            positions = await client.get_open_positions()
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
                    print(f"Error market closing {sym}: {ce}")
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
    async def get_stats_pnl(days_back: int = Query(0)):
        summary = stats_svc.get_pnl_summary(days_back=days_back)
        # If daily_pnl table is empty/unpopulated, aggregate live from Binance userTrades
        raw_pnl = float(summary.get("realized_pnl") or 0)
        if (not summary.get("has_data") or raw_pnl == 0) and binance_svc.has_credentials():
            try:
                client = BinanceFuturesClient(config)
                raw_trades = await client._request("GET", "/fapi/v1/userTrades", params={"limit": 200}, signed=True)
                if raw_trades:
                    realized = sum(float(tr.get("realizedPnl", 0)) for tr in raw_trades)
                    commissions = sum(float(tr.get("commission", 0)) for tr in raw_trades)
                    closed = [tr for tr in raw_trades if float(tr.get("realizedPnl", 0)) != 0]
                    wins = [tr for tr in closed if float(tr.get("realizedPnl", 0)) > 0]
                    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0.0
                    summary["realized_pnl"] = f"{realized:.2f}"
                    summary["commission"] = f"{commissions:.2f}"
                    summary["net_pnl"] = f"{(realized - commissions):.2f}"
                    summary["gross_realized_pnl"] = realized
                    summary["fees_paid"] = commissions
                    summary["net_realized_pnl"] = realized - commissions
                    summary["total_closed_trades"] = len(closed)
                    summary["win_count"] = len(wins)
                    summary["loss_count"] = len(closed) - len(wins)
                    summary["win_rate_pct"] = win_rate
                    summary["has_data"] = True
                    summary["data_completeness"] = "FULL"
                await client.close()
            except Exception:
                pass
        return summary

    @router.get("/stats/telemetry", dependencies=[Depends(verify_token)])
    async def get_stats_telemetry():
        return stats_svc.get_telegram_telemetry()

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
            "risk_per_signal_pct": float(config.risk.risk_per_signal_pct),
            "max_daily_loss_pct": float(config.risk.max_daily_loss_pct),
            "max_leverage": int(config.risk.max_leverage),
            "margin_mode": config.risk.margin_mode,
            "entry_range_policy": config.execution.entry_range_policy,
            "multi_tp_default_weight_mode": config.execution.multi_tp_default_weight_mode,
            "tp1_target_weight_pct": float(getattr(config.execution, "tp1_target_weight_pct", Decimal("60.0"))),
            "breakeven_after_tp1": bool(config.risk.breakeven_after_tp1_default),
            "sl_buffer_pct": float(getattr(config.risk, "sl_buffer_pct", Decimal("1.0"))),
        }

    class UpdateSettingsModel(BaseModel):
        mode: str
        live_trading_enabled: bool
        risk_per_signal_pct: float
        max_daily_loss_pct: float
        max_leverage: int
        entry_range_policy: str
        multi_tp_default_weight_mode: str
        tp1_target_weight_pct: Optional[float] = 60.0
        breakeven_after_tp1: Optional[bool] = True
        sl_buffer_pct: Optional[float] = 1.0

    @router.post("/settings", dependencies=[Depends(verify_token)])
    async def update_settings(
        body: UpdateSettingsModel,
        x_confirm_live: Optional[str] = Header(None),
    ):
        target_mode = body.mode.upper()

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
            config.mode = ExecutionMode(target_mode)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=make_error_response("INVALID_MODE", f"Chế độ thực thi không hợp lệ: {target_mode}"),
            )

        config.live_trading_enabled = body.live_trading_enabled
        config.risk.risk_per_signal_pct = Decimal(str(min(body.risk_per_signal_pct, 10.0)))
        config.risk.max_daily_loss_pct = Decimal(str(min(body.max_daily_loss_pct, 20.0)))
        config.risk.max_leverage = min(body.max_leverage, 125)
        config.execution.entry_range_policy = ExecutionPolicyConfig.normalize_entry_range(body.entry_range_policy)
        config.execution.multi_tp_default_weight_mode = ExecutionPolicyConfig.normalize_multi_tp(body.multi_tp_default_weight_mode)
        if body.tp1_target_weight_pct is not None:
            clamped_tp1 = min(max(float(body.tp1_target_weight_pct), 10.0), 90.0)
            config.execution.tp1_target_weight_pct = Decimal(str(clamped_tp1))
        if body.breakeven_after_tp1 is not None:
            config.risk.breakeven_after_tp1_default = bool(body.breakeven_after_tp1)
        if body.sl_buffer_pct is not None:
            clamped_buffer = min(max(float(body.sl_buffer_pct), 0.0), 5.0)
            config.risk.sl_buffer_pct = Decimal(str(clamped_buffer))

        save_config(config)

        await event_bus.publish("backend_status_changed", {"mode": config.mode.value, "live": config.live_trading_enabled})
        return {"success": True, "settings": body.model_dump()}

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
        loop = asyncio.get_running_loop()
        loop.call_later(
            0.4,
            lambda: os.kill(os.getpid(), signal.SIGTERM if os.name != "nt" else signal.SIGINT),
        )
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

    return router
