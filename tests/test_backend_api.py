import pytest
from fastapi.testclient import TestClient

from backend.runtime.server import create_app
from config.config import AppConfig, TelegramConfig, BinanceConfig, NotificationsConfig
from config.policy_defaults import RiskPolicy, ExecutionPolicyConfig
from core.enums import ExecutionMode
from storage.database import DatabaseManager


@pytest.fixture
def mock_app(tmp_path):
    db_file = str(tmp_path / "test_api.db")
    db = DatabaseManager(db_path=db_file)

    config = AppConfig(
        mode=ExecutionMode.READ_ONLY,
        live_trading_enabled=False,
        data_dir=str(tmp_path),
        database_file=db_file,
        telegram=TelegramConfig(),
        binance=BinanceConfig(),
        risk=RiskPolicy(),
        execution=ExecutionPolicyConfig(),
        notifications=NotificationsConfig(),
    )

    token = "secret_session_token_12345"
    app = create_app(config=config, db=db, session_token=token)
    client = TestClient(app)
    return client, token, config


def test_health_check_no_auth_required(mock_app):
    client, _, _ = mock_app
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["mode"] == "READ_ONLY"
    assert data["live_trading_enabled"] is False
    assert data["entry_enabled"] is True
    # Verify session token is NEVER leaked in health response
    assert "token" not in data
    assert "session_token" not in data


def test_auth_rejection_missing_or_invalid_token(mock_app):
    client, token, _ = mock_app

    # Missing token
    resp1 = client.get("/snapshot")
    assert resp1.status_code == 401
    assert resp1.json()["detail"]["code"] == "UNAUTHORIZED"

    # Invalid token
    resp2 = client.get("/snapshot", headers={"X-Session-Token": "invalid_token"})
    assert resp2.status_code == 401
    assert resp2.json()["detail"]["code"] == "UNAUTHORIZED"


def test_snapshot_with_valid_token(mock_app):
    client, token, _ = mock_app
    headers = {"X-Session-Token": token}

    response = client.get("/snapshot", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "account" in data
    assert "telemetry" in data
    assert "pnl_today" in data
    assert "pnl_7d" in data
    assert "positions" in data
    assert "orders" in data
    assert "alerts" in data
    assert data["entry_enabled"] is True
    assert data["mode"] == "READ_ONLY"
    assert data["live_trading_enabled"] is False


def test_read_only_strictly_blocks_write_operations(mock_app):
    client, token, _ = mock_app
    headers = {"X-Session-Token": token}

    # Attempt manual close-position in READ_ONLY mode
    resp = client.post("/trading/close-position", headers=headers, json={"symbol": "BTCUSDT"})
    assert resp.status_code == 403
    data = resp.json()
    assert data["detail"]["code"] == "READ_ONLY_BLOCKED"
    assert "READ_ONLY" in data["detail"]["user_message"]

    # Attempt close-all-bot in READ_ONLY mode
    resp_all = client.post("/trading/close-all-bot", headers=headers)
    assert resp_all.status_code == 403
    assert resp_all.json()["detail"]["code"] == "READ_ONLY_BLOCKED"


def test_toggle_entry_state(mock_app):
    client, token, _ = mock_app
    headers = {"X-Session-Token": token}

    # Pause new entries
    resp = client.post("/trading/toggle-entry", headers=headers, json={"entry_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["entry_enabled"] is False

    # Verify snapshot reflects paused entry
    snap = client.get("/snapshot", headers=headers).json()
    assert snap["entry_enabled"] is False

    # Resume entries
    resp2 = client.post("/trading/toggle-entry", headers=headers, json={"entry_enabled": True})
    assert resp2.status_code == 200
    assert resp2.json()["entry_enabled"] is True


def test_settings_live_gates_reject_unauthorized_live(mock_app):
    client, token, _ = mock_app
    headers = {"X-Session-Token": token}

    # Attempt to enable LIVE without Binance credentials
    live_payload = {
        "mode": "LIVE",
        "live_trading_enabled": True,
        "risk_per_signal_pct": 2.0,
        "max_daily_loss_pct": 5.0,
        "max_leverage": 20,
        "margin_mode": "CROSSED",
        "entry_range_policy": "MID_POINT",
        "multi_tp_default_weight_mode": "EQUAL",
    }
    resp = client.post("/settings", headers=headers, json=live_payload)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "LIVE_GATES_FAILED"

    # Safe update to SHADOW or PAPER without live trading succeeds
    shadow_payload = {
        "mode": "SHADOW",
        "live_trading_enabled": False,
        "risk_per_signal_pct": 2.5,
        "max_daily_loss_pct": 5.0,
        "max_leverage": 20,
        "margin_mode": "CROSSED",
        "entry_range_policy": "MID_POINT",
        "multi_tp_default_weight_mode": "EQUAL",
    }
    resp_safe = client.post("/settings", headers=headers, json=shadow_payload)
    assert resp_safe.status_code == 200
    assert resp_safe.json()["settings"]["mode"] == "SHADOW"


def test_websocket_first_message_auth(mock_app):
    client, token, _ = mock_app

    # Case 1: Connect and send bad token -> disconnected with 1008
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "AUTH", "token": "wrong_token"})
        # Should be closed by server

    # Case 2: Connect and send valid token -> authenticated and receives AUTH_SUCCESS
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "AUTH", "token": token})
        resp = ws.receive_json()
        assert resp["event_type"] == "AUTH_SUCCESS"
        assert resp["payload"]["status"] == "AUTHENTICATED"
        assert "mode" in resp["payload"]
        
        # Keepalive ping-pong
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_cors_preflight_for_tauri_origins(mock_app):
    client, _, _ = mock_app

    # Windows Tauri v2 origin
    resp = client.options(
        "/health",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://tauri.localhost"

    # HTTPS Tauri origin
    resp_https = client.options(
        "/health",
        headers={
            "Origin": "https://tauri.localhost",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp_https.status_code == 200
    assert resp_https.headers.get("access-control-allow-origin") == "https://tauri.localhost"

    # External unauthorized origin must be blocked
    resp_blocked = client.options(
        "/health",
        headers={
            "Origin": "https://malicious-attacker.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp_blocked.status_code == 400
    assert "Disallowed CORS origin" in resp_blocked.text


def test_websocket_origin_verification(mock_app):
    client, token, _ = mock_app

    # Allowed Tauri origin connects successfully
    with client.websocket_connect("/ws", headers={"origin": "http://tauri.localhost"}) as ws:
        ws.send_json({"type": "AUTH", "token": token})
        resp = ws.receive_json()
        assert resp["event_type"] == "AUTH_SUCCESS"


def test_telegram_dialogs_and_folders_api(mock_app, monkeypatch):
    client, token, _ = mock_app
    headers = {"X-Session-Token": token}

    async def mock_list_accessible(*args, **kwargs):
        return {
            "dialogs": [
                {
                    "id": -1001234567,
                    "title": "VIP Trading Signals",
                    "is_channel": True,
                    "is_group": False,
                    "pinned": True,
                    "unread_count": 5,
                    "folder_ids": [1],
                    "folder_pinned_in": [1],
                },
                {
                    "id": -1009876543,
                    "title": "Community Chat",
                    "is_channel": False,
                    "is_group": True,
                    "pinned": False,
                    "unread_count": 0,
                    "folder_ids": [],
                    "folder_pinned_in": [],
                },
            ],
            "folders": [
                {
                    "id": 1,
                    "title": "Kèo trade",
                    "emoticon": "📊",
                    "chat_ids": [-1001234567],
                    "pinned_chat_ids": [-1001234567],
                    "chat_count": 1,
                }
            ],
        }

    from services.telegram_service import TelegramService
    monkeypatch.setattr(TelegramService, "list_accessible_dialogs", mock_list_accessible)

    resp = client.get("/telegram/dialogs", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "dialogs" in data
    assert "folders" in data
    assert "allowed_chat_ids" in data
    assert len(data["dialogs"]) == 2
    assert len(data["folders"]) == 1
    assert data["folders"][0]["title"] == "Kèo trade"
    assert data["dialogs"][0]["pinned"] is True
    assert data["dialogs"][0]["folder_ids"] == [1]


def test_telegram_allowlist_update(mock_app):
    client, token, config = mock_app
    headers = {"X-Session-Token": token}

    update_payload = {"allowed_chat_ids": [-1001234567, -1009876543]}
    resp = client.post("/telegram/allowlist", headers=headers, json=update_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert -1001234567 in data["allowed_chat_ids"]
    assert -1009876543 in data["allowed_chat_ids"]
    assert config.telegram.allowed_chat_ids == [-1001234567, -1009876543]


def test_telegram_collect_history_ingestion_and_parsing(mock_app, monkeypatch):
    client, token, config = mock_app
    headers = {"X-Session-Token": token}

    mock_raw_signal = (
        "Signal: BTC/USDT (LONG)\n"
        "Leverage: 10x (Isolated)\n"
        "Entry: 65000\n"
        "Target 1: 66000\n"
        "Stop Loss: 64000\n"
    )

    sample_msgs = [
        {
            "chat_id": -1002052872813,
            "message_id": 101,
            "sender_id": 999,
            "date": "2026-10-15T12:00:00",
            "edit_date": None,
            "reply_to_msg_id": None,
            "raw_text": "Hello traders! Market looks good today.",
        },
        {
            "chat_id": -1002052872813,
            "message_id": 102,
            "sender_id": 999,
            "date": "2026-10-15T12:05:00",
            "edit_date": None,
            "reply_to_msg_id": None,
            "raw_text": mock_raw_signal,
        },
        {
            "chat_id": -1002052872813,
            "message_id": 103,
            "sender_id": 999,
            "date": "2026-10-15T12:30:00",
            "edit_date": None,
            "reply_to_msg_id": 102,
            "raw_text": "Take-Profit target 1 achieved ✅",
        },
    ]

    from services.telegram_service import TelegramService
    async def mock_collect(*args, **kwargs):
        return sample_msgs

    monkeypatch.setattr(TelegramService, "collect_history", mock_collect)

    # 1. Trigger history collection
    payload = {"chat_id": -1002052872813, "days": 7, "limit": 100}
    resp = client.post("/telegram/collect-history", headers=headers, json=payload)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["count"] == 3
    assert res_data["signals_detected"] == 1
    assert res_data["signals_validated"] == 1
    assert res_data["updates_recorded"] == 1

    # 2. Verify Stats Telemetry has updated
    snap_resp = client.get("/snapshot", headers=headers)
    assert snap_resp.status_code == 200
    telemetry = snap_resp.json()["telemetry"]
    assert telemetry["messages_received"] >= 3
    assert telemetry["signals_detected"] >= 1
    assert telemetry["signals_validated"] >= 1

    # 3. Verify Signals List endpoint returns the parsed signal
    sig_resp = client.get("/signals", headers=headers)
    assert sig_resp.status_code == 200
    signals = sig_resp.json()
    assert len(signals) >= 1
    assert signals[0]["symbol"] == "BTCUSDT"
    assert signals[0]["side"] == "LONG"


def test_channel_leaderboard_endpoint(mock_app):
    client, token, _ = mock_app
    headers = {"X-Session-Token": token}

    resp = client.get("/channels/leaderboard?timeframe=all", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "summary" in data
    assert "channels" in data
    assert isinstance(data["channels"], list)



