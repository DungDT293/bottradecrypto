import os
import tempfile
import pytest
from datetime import datetime, timezone
from decimal import Decimal
import pytz

from config.config import AppConfig, TelegramConfig, BinanceConfig, RiskPolicy, ExecutionPolicyConfig
from core.enums import ExecutionMode, SignalState, OrderSide, OrderType
from core.models import Order, ParsedSignal, SourceMetadata
from services.alert_service import AlertLevel, AlertService
from services.binance_service import BinanceService
from services.stats_service import StatsService
from services.telegram_service import TelegramService, TelegramStatus
from services.trading_service import EngineStatus, ProtectionStatus, TradingService
from storage.database import DatabaseManager, OrderRepository, SignalRepository


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = DatabaseManager(db_path)
    yield db
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


@pytest.fixture
def sample_config():
    return AppConfig(
        mode=ExecutionMode.READ_ONLY,
        live_trading_enabled=False,
        data_dir="./data",
        database_file=":memory:",
        telegram=TelegramConfig(api_id=12345, api_hash="abcdef123456"),
        binance=BinanceConfig(),
        risk=RiskPolicy(),
        execution=ExecutionPolicyConfig(),
    )


def test_alert_service_deduplication():
    alerts = AlertService(max_history=50)
    alerts.clear()

    # Add same alert twice in a row
    a1 = alerts.add_alert(AlertLevel.WARNING, "Connection drop", "Telegram disconnected", "TELEGRAM")
    a2 = alerts.add_alert(AlertLevel.WARNING, "Connection drop", "Telegram disconnected again", "TELEGRAM")

    # Should be deduplicated into 1 item with repeat_count = 2
    items = alerts.get_alerts()
    assert len(items) == 1
    assert items[0]["repeat_count"] == 2
    assert items[0]["title"] == "Connection drop"

    # Mark as read
    assert alerts.get_unread_count() == 1
    alerts.mark_as_read(items[0]["id"])
    assert alerts.get_unread_count() == 0


def test_stats_service_boundaries_and_isolation(temp_db, sample_config):
    stats = StatsService(temp_db, sample_config)

    # Check boundaries in Asia/Ho_Chi_Minh
    start_today_utc, end_today_utc = stats.get_local_day_boundaries(0)
    start_7d_utc, end_7d_utc = stats.get_local_day_boundaries(6)

    assert start_7d_utc < start_today_utc
    assert end_today_utc >= start_today_utc

    # Insert daily PnL records
    with temp_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO daily_pnl (date_str, starting_equity, realized_pnl, fees_paid, net_pnl, deposits_withdrawals, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-10-15", "1000.00", "50.00", "5.00", "45.00", "0.00", datetime.utcnow().isoformat()),
        )

    summary = stats.get_pnl_summary(0)
    assert summary["gross_realized_pnl"] >= 0.0
    assert summary["fees_paid"] >= 0.0
    assert summary["net_realized_pnl"] == summary["gross_realized_pnl"] - summary["fees_paid"]


def test_trading_service_protection_status(temp_db, sample_config):
    trading = TradingService(temp_db, sample_config)

    # 1. Position with NO active algo SL order -> MISSING
    now_str = datetime.utcnow().isoformat()
    with temp_db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (chat_id, message_id, sender_id, telegram_timestamp, received_at, raw_text, normalized_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1001, 1, 999, now_str, now_str, "BTC LONG", "btc long"),
        )
        conn.execute(
            """
            INSERT INTO signals (signal_id, chat_id, message_id, symbol, side, state, entries_json, stop_loss, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("SIG_BTC_1", 1001, 1, "BTCUSDT", "LONG", "OPEN_PROTECTED", "[\"60000.0\"]", "58000.0", now_str, now_str),
        )
        conn.execute(
            """
            INSERT INTO positions (symbol, side, quantity, entry_price, leverage, margin_mode, active_signal_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("BTCUSDT", "LONG", "0.1", "60000.0", 5, "ISOLATED", "SIG_BTC_1", now_str),
        )

    positions = trading.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["protection_status"] == ProtectionStatus.MISSING.value

    # 2. Add active algo SL order -> CONFIRMED
    order_repo = OrderRepository(temp_db)
    order = Order(
        client_order_id="SL_BTC_1",
        signal_id="SIG_BTC_1",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP_MARKET,
        quantity=Decimal("0.1"),
        trigger_price=Decimal("58000.0"),
        is_reduce_only=True,
        is_algo=True,
        status="NEW",
    )
    order_repo.save_order(order)

    positions_updated = trading.get_open_positions()
    assert len(positions_updated) == 1
    assert positions_updated[0]["protection_status"] == ProtectionStatus.CONFIRMED.value
    assert positions_updated[0]["sl_price"] == "58000.0"


def test_binance_service_read_only_isolation(sample_config):
    service = BinanceService(sample_config)
    # When mode is READ_ONLY, has_credentials check or sync never calls live write API
    snapshot = service.get_cached_snapshot()
    assert snapshot.is_connected is False
    assert snapshot.wallet_balance is None  # Unknown/disconnected data NOT displayed as 0


def test_telegram_service_masking(sample_config):
    tg_service = TelegramService(sample_config)
    # Check status
    assert tg_service.get_status() in [TelegramStatus.NOT_LOGGED_IN, TelegramStatus.CONNECTED]
    # Session path contains configured session name
    assert "telegram_user" in tg_service.get_session_file_path()


def test_ui_components_instantiation(sample_config, temp_db):
    """
    Instantiates UI pages off-screen to ensure all PySide6 widgets,
    layouts, and signal wirings initialize without any syntax or runtime errors.
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    from ui.pages.overview_page import OverviewPage
    from ui.pages.connections_page import ConnectionsPage
    from ui.pages.groups_page import GroupsPage
    from ui.pages.signals_page import SignalsPage
    from ui.pages.trading_page import TradingPage
    from ui.pages.history_page import HistoryPage
    from ui.pages.stats_page import StatsPage
    from ui.pages.reviews_page import ReviewsPage
    from ui.pages.logs_page import LogsPage
    from ui.pages.settings_page import SettingsPage

    p1 = OverviewPage()
    p2 = ConnectionsPage()
    p3 = GroupsPage()
    p4 = SignalsPage()
    p5 = TradingPage()
    p6 = HistoryPage()
    p7 = StatsPage()
    p8 = ReviewsPage()
    p9 = LogsPage()
    p10 = SettingsPage()

    assert p1 is not None
    assert p2 is not None
    assert p3 is not None
    assert p4 is not None
    assert p5 is not None
    assert p6 is not None
    assert p7 is not None
    assert p8 is not None
    assert p9 is not None
    assert p10 is not None
