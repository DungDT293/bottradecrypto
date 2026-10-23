import json
import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.runtime.server import create_app
from config.config import AppConfig, TelegramConfig, BinanceConfig, NotificationsConfig
from config.policy_defaults import RiskPolicy, ExecutionPolicyConfig
from core.enums import ExecutionMode
from services.license_service import LicenseService
from services.telegram_service import TelegramService
from storage.database import DatabaseManager


@pytest.fixture
def temp_license_svc(tmp_path):
    lic_file = str(tmp_path / "test_license.json")
    trial_file = str(tmp_path / ".test_trial_claimed")
    svc = LicenseService(license_file=lic_file, trial_file=trial_file)
    return svc, lic_file, trial_file


def test_hwid_generation_format(temp_license_svc):
    svc, _, _ = temp_license_svc
    hwid = svc.get_machine_hwid()
    assert hwid.startswith("HWID-")
    parts = hwid.split("-")
    assert len(parts) == 5
    assert all(len(p) == 4 for p in parts[1:])


def test_license_key_generation_and_activation(temp_license_svc):
    svc, lic_file, _ = temp_license_svc
    hwid = svc.get_machine_hwid()

    # Generate a VIP Monthly key for this HWID
    key = svc.generate_license_key(hwid=hwid, plan_name="VIP_MONTHLY", duration_days=30)
    assert key.startswith("VIP-")

    # Activate
    res = svc.activate_key(key)
    assert res["success"] is True
    assert res["plan"] == "VIP_MONTHLY"

    # Status check
    info = svc.get_license_info()
    assert info["is_active"] is True
    assert info["status"] == "ACTIVE"
    assert info["plan"] == "VIP_MONTHLY"
    assert info["days_remaining"] >= 29
    assert info["is_lifetime"] is False


def test_license_lifetime_plan(temp_license_svc):
    svc, _, _ = temp_license_svc
    hwid = svc.get_machine_hwid()

    # Lifetime key (duration_days = 0)
    key = svc.generate_license_key(hwid=hwid, plan_name="VIP_LIFETIME", duration_days=0)
    res = svc.activate_key(key)
    assert res["success"] is True

    info = svc.get_license_info()
    assert info["is_active"] is True
    assert info["status"] == "ACTIVE"
    assert info["is_lifetime"] is True
    assert info["days_remaining"] is None


def test_license_rejection_hwid_mismatch(temp_license_svc):
    svc, _, _ = temp_license_svc
    foreign_hwid = "HWID-AAAA-BBBB-CCCC-DDDD"

    # Key was generated for another machine
    key = svc.generate_license_key(hwid=foreign_hwid, plan_name="VIP_LIFETIME", duration_days=0)
    res = svc.activate_key(key)

    assert res["success"] is False
    assert "khác" in res["message"] or "mismatch" in res["message"].lower()

    info = svc.get_license_info()
    assert info["is_active"] is False


def test_license_tampering_detection(temp_license_svc):
    svc, _, _ = temp_license_svc
    hwid = svc.get_machine_hwid()

    key = svc.generate_license_key(hwid=hwid, plan_name="VIP_MONTHLY", duration_days=30)

    # Tamper with the base64 string
    tampered_key = key[:-5] + "XXXXX"
    res = svc.activate_key(tampered_key)
    assert res["success"] is False


def test_license_trial_activation_and_prevention(temp_license_svc):
    svc, lic_file, trial_file = temp_license_svc

    # 1st trial activation should succeed
    res1 = svc.activate_trial()
    assert res1["success"] is True
    assert os.path.exists(trial_file)

    info1 = svc.get_license_info()
    assert info1["is_active"] is True
    assert info1["plan"] == "TRIAL_3_DAYS"
    assert info1["days_remaining"] in (2, 3)

    # 2nd trial activation while active must be rejected
    res2 = svc.activate_trial()
    assert res2["success"] is False
    assert "đang có bản quyền" in res2["message"]

    # Even if license file is removed/expired, claimed marker prevents claiming again
    if os.path.exists(lic_file):
        os.remove(lic_file)
    res3 = svc.activate_trial()
    assert res3["success"] is False
    assert "đã từng sử dụng" in res3["message"]


@pytest.fixture
def commercial_api_client(tmp_path):
    db_file = str(tmp_path / "commercial_test.db")
    db = DatabaseManager(db_path=db_file)

    config = AppConfig(
        mode=ExecutionMode.READ_ONLY,
        live_trading_enabled=False,
        data_dir=str(tmp_path),
        database_file=db_file,
        telegram=TelegramConfig(allowed_chat_ids=[-1002007658025]),
        binance=BinanceConfig(),
        risk=RiskPolicy(),
        execution=ExecutionPolicyConfig(),
        notifications=NotificationsConfig(),
    )

    token = "commercial_session_token"
    app = create_app(config=config, db=db, session_token=token)
    client = TestClient(app)
    return client, token, config


def test_api_license_endpoints(commercial_api_client):
    client, token, _ = commercial_api_client
    headers = {"X-Session-Token": token}

    # 1. Check initial license status
    resp = client.get("/license/status", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "hwid" in data
    assert "is_active" in data

    # 2. Activate trial via API
    trial_resp = client.post("/license/trial", headers=headers)
    assert trial_resp.status_code in (200, 400)  # 200 if fresh machine, 400 if claimed
    if trial_resp.status_code == 200:
        assert trial_resp.json()["success"] is True

    # 3. Activate valid key via API
    svc = LicenseService()
    my_hwid = data["hwid"]
    valid_key = svc.generate_license_key(hwid=my_hwid, plan_name="VIP_YEARLY", duration_days=365)

    act_resp = client.post("/license/activate", headers=headers, json={"key": valid_key})
    assert act_resp.status_code == 200
    act_data = act_resp.json()
    assert act_data["success"] is True
    assert act_data["license"]["plan"] == "VIP_YEARLY"


@pytest.mark.asyncio
async def test_telegram_auto_join_elite_mock(commercial_api_client):
    client, token, config = commercial_api_client
    headers = {"X-Session-Token": token}

    with patch.object(TelegramService, "auto_join_elite_channels", new_callable=AsyncMock) as mock_join:
        mock_join.return_value = {
            "success": True,
            "joined_count": 3,
            "already_count": 2,
            "failed_count": 0,
            "total_channels": 5,
            "message": "Đã tham gia thành công 3 kênh mới (2 kênh đã tham gia trước đó).",
            "results": [
                {"name": "THE WOLF (CRYPTO)®", "chat_id": -1002007658025, "status": "ALREADY_JOINED", "message": "Đã là thành viên"},
                {"name": "Boom_Boom_Billionaires", "chat_id": -1001756316676, "status": "ALREADY_JOINED", "message": "Đã là thành viên"},
                {"name": "CRYPTO LEOPARD'S", "chat_id": -1002052872813, "status": "JOINED", "message": "Tham gia thành công"},
                {"name": "CRYPTO MONK", "chat_id": -1001552004524, "status": "JOINED", "message": "Tham gia thành công"},
                {"name": "Crypto Neon", "chat_id": -1001370457350, "status": "JOINED", "message": "Tham gia thành công"},
            ],
        }

        resp = client.post("/telegram/auto-join-elite", headers=headers)
        assert resp.status_code == 200
        res_data = resp.json()
        assert res_data["success"] is True
        assert res_data["joined_count"] == 3
        assert res_data["already_count"] == 2
        assert len(res_data["results"]) == 5


def test_system_public_ip_endpoint(commercial_api_client, monkeypatch):
    client, token, _ = commercial_api_client
    headers = {"X-Session-Token": token}
    import backend.api.router as router_module
    monkeypatch.setattr(router_module.urllib.request, "urlopen", lambda *args, **kwargs: _FakeIpResponse())

    resp = client.get("/system/public-ip", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data
    assert "ip" in data


@pytest.mark.asyncio
async def test_fetch_remote_elite_channels_resolution():
    from services.telegram_service import TelegramService
    from config.config import AppConfig

    cfg = AppConfig()
    svc = TelegramService(cfg)

    # 1. Fallback to local config/elite_channels.json or default
    channels = await svc.fetch_remote_elite_channels()
    assert len(channels) == 5
    assert any(c["name"] == "THE WOLF (CRYPTO)®" for c in channels)
    assert any("Leopard" in c["name"] or "LEOPARD" in c["name"] for c in channels)


@pytest.mark.asyncio
async def test_auto_join_progress_callback_and_delay():
    from services.telegram_service import TelegramService
    from config.config import AppConfig

    cfg = AppConfig()
    svc = TelegramService(cfg)

    mock_client = AsyncMock()
    mock_client.is_connected = MagicMock(return_value=True)
    mock_client.is_user_authorized = AsyncMock(return_value=True)

    # Return empty dialogs so channels need to be joined
    mock_client.get_dialogs.return_value = []

    progress_events = []
    async def fake_progress(step, total, channel_name, delay_seconds, message, status):
        progress_events.append({
            "step": step,
            "total": total,
            "channel_name": channel_name,
            "delay_seconds": delay_seconds,
            "message": message,
            "status": status,
        })

    with patch.object(svc, "get_client", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        res = await svc.auto_join_elite_channels(progress_callback=fake_progress)
        assert res["success"] is True
        assert res["total_channels"] == 5
        assert len(progress_events) > 0

        # Verify progress messages and waiting status
        waiting_events = [e for e in progress_events if e["status"] == "WAITING"]
        assert len(waiting_events) > 0
        for we in waiting_events:
            assert 8.0 <= we["delay_seconds"] <= 15.0
            assert "bảo vệ tài khoản" in we["message"]

        # Verify asyncio.sleep was called with random delays between 8 and 15 seconds
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list if isinstance(call.args[0], float) and call.args[0] >= 8.0]
        assert len(sleep_calls) > 0
        for s_val in sleep_calls:
            assert 8.0 <= s_val <= 15.0

