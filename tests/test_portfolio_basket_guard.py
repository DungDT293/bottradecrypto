import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from config.config import AppConfig, ExecutionMode
from config.policy_defaults import RiskPolicy, ExecutionPolicyConfig
from execution.reconciliation import ReconciliationEngine
from storage.database import DatabaseManager


@pytest.fixture
def mock_db(tmp_path):
    db_file = tmp_path / "test_basket_guard.db"
    return DatabaseManager(str(db_file))


@pytest.fixture
def config():
    cfg = AppConfig()
    cfg.mode = ExecutionMode.LIVE
    cfg.live_trading_enabled = True
    cfg.binance.live_api_key = "test_key"
    cfg.binance.live_api_secret = "test_secret"
    cfg.risk.daily_profit_target_enabled = True
    cfg.risk.daily_profit_target_usdt = Decimal("8.0")
    cfg.risk.basket_trailing_enabled = True
    cfg.risk.basket_trailing_trigger_usdt = Decimal("8.0")
    cfg.risk.basket_trailing_pullback_pct = Decimal("25.0")
    return cfg


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.cancel_all_orders = AsyncMock(return_value={"success": True})
    client.cancel_algo_order = AsyncMock(return_value={"success": True})
    client.get_open_algo_orders = AsyncMock(return_value=[])
    client.create_standard_order = AsyncMock(return_value={"orderId": 12345, "status": "FILLED"})
    return client


@pytest.mark.asyncio
async def test_basket_trailing_tracks_peak_and_locks(mock_db, config, mock_client):
    config.risk.daily_profit_target_enabled = False
    reconciler = ReconciliationEngine(
        exchange_client=mock_client,
        db=mock_db,
        config=config,
    )

    positions_map = {
        "ETHUSDT": {
            "symbol": "ETHUSDT",
            "positionAmt": "0.1",
            "entryPrice": "2000.0",
            "markPrice": "2080.0",
            "unRealizedProfit": "8.0",
        },
        "SOLUSDT": {
            "symbol": "SOLUSDT",
            "positionAmt": "1.0",
            "entryPrice": "100.0",
            "markPrice": "102.0",
            "unRealizedProfit": "2.0",
        },
    }

    report = {"discrepancies": []}

    # Step 1: Total unrealized = 10.0 (>= 8.0 trigger) -> Peak should be 10.0
    await reconciler._check_portfolio_profit_guards(positions_map, report)
    assert reconciler._basket_peak_unrealized == Decimal("10.0")
    assert reconciler.basket_guard_state["trailing_active"] is True
    assert reconciler.basket_guard_state["pullback_threshold"] == 7.5  # 10 * 0.75
    mock_client.create_standard_order.assert_not_called()

    # Step 2: Profit pulls back to 7.0 (<= 7.5 pullback threshold) -> Triggers Market Close
    positions_map["ETHUSDT"]["unRealizedProfit"] = "5.0"
    positions_map["SOLUSDT"]["unRealizedProfit"] = "2.0"
    # Total = 7.0 <= 7.5
    await reconciler._check_portfolio_profit_guards(positions_map, report)

    # Both positions must be closed via market orders
    assert mock_client.create_standard_order.call_count == 2
    assert reconciler._basket_peak_unrealized == Decimal("0.0")
    assert any("BASKET_TRAILING_LOCK" in str(d) or "Giáp Khóa Lãi Rổ" in str(d) for d in report["discrepancies"])


@pytest.mark.asyncio
async def test_daily_profit_target_locks(mock_db, config, mock_client):
    reconciler = ReconciliationEngine(
        exchange_client=mock_client,
        db=mock_db,
        config=config,
    )

    positions_map = {
        "BTCUSDT": {
            "symbol": "BTCUSDT",
            "positionAmt": "-0.01",
            "entryPrice": "80000.0",
            "markPrice": "79100.0",
            "unRealizedProfit": "9.0",  # >= 8.0 daily target
        }
    }

    report = {"discrepancies": []}
    await reconciler._check_portfolio_profit_guards(positions_map, report)

    # Market close called for BTCUSDT
    assert mock_client.create_standard_order.call_count == 1
    assert reconciler.basket_guard_state["daily_target_locked"] is True
    assert any("DAILY_TARGET_LOCK" in str(d) or "Chỉ Tiêu Lãi Ngày" in str(d) for d in report["discrepancies"])
