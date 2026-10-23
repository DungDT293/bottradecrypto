import asyncio
import os
import sys
import json
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from backend.runtime.server import create_app
from config.config import load_config
from storage.database import DatabaseManager

def test_ai_router():
    cfg = load_config()
    db = DatabaseManager(":memory:")
    token = "test_ai_secret_token"
    app = create_app(config=cfg, db=db, session_token=token)
    client = TestClient(app)

    headers = {"X-Session-Token": token}

    print("1. Testing GET /api/ai/status...")
    r = client.get("/api/ai/status", headers=headers)
    print("Status Code:", r.status_code)
    data = r.json()
    print("Response:", json.dumps(data, indent=2))
    assert r.status_code == 200
    assert "enabled" in data
    assert "watchlist" in data

    print("\n2. Testing POST /api/ai/config (updating parameters)...")
    cfg_update = {
        "enabled": False,
        "scan_interval_minutes": 15,
        "min_confidence": 75,
        "watchlist": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    }
    r = client.post("/api/ai/config", headers=headers, json=cfg_update)
    print("Status Code:", r.status_code)
    assert r.status_code == 200
    res = r.json()
    print("Response:", json.dumps(res, indent=2))
    assert res["scan_interval_minutes"] == 15
    assert res["min_confidence"] == 75

    print("\n3. Testing POST /api/ai/scan-now...")
    r = client.post("/api/ai/scan-now", headers=headers)
    print("Status Code:", r.status_code)
    scan_res = r.json()
    print("Scan Response:", json.dumps(scan_res, indent=2))
    assert r.status_code == 200
    assert "setups" in scan_res

    print("\nALL AI ENDPOINTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_ai_router()
