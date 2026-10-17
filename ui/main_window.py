import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer, QLockFile
from PySide6.QtGui import QIcon, QAction

from config.config import AppConfig, load_config
from core.enums import ExecutionMode, SignalState
from services.alert_service import AlertLevel, AlertService
from services.binance_service import BinanceService
from services.stats_service import StatsService
from services.telegram_service import TelegramService, TelegramStatus
from services.trading_service import EngineStatus, TradingService
from storage.database import DatabaseManager

from ui.components.dialogs import ConfirmationDialog
from ui.components.header import HeaderBar
from ui.components.sidebar import Sidebar
from ui.pages import (
    ConnectionsPage,
    GroupsPage,
    HistoryPage,
    LogsPage,
    OverviewPage,
    ReviewsPage,
    SettingsPage,
    SignalsPage,
    StatsPage,
    TradingPage,
)
from ui.workers.async_worker import AsyncRunnerWorker


class MainWindow(QMainWindow):
    """
    Main Application Window for Telegram Binance Signal Executor.
    Coordinates UI Presentation, Application Services, and Background Workers.
    """

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Telegram Binance Signal Executor - Desktop Management")
        self.resize(1280, 800)
        self.setMinimumSize(1024, 680)

        # 1. Single-instance lock
        lock_dir = os.path.abspath(self.config.data_dir)
        os.makedirs(lock_dir, exist_ok=True)
        self.lock_file = QLockFile(os.path.join(lock_dir, "app_gui.lock"))
        if not self.lock_file.tryLock(100):
            QMessageBox.critical(
                None,
                "Ứng dụng đang chạy",
                "Một phiên làm việc của bot đang chạy trên máy tính này.\n"
                "Để đảm bảo an toàn cơ sở dữ liệu SQLite và tránh trùng lặp lệnh, "
                "bạn không thể mở hai cửa sổ cùng lúc.",
            )
            sys.exit(0)

        # 2. Services initialization
        self.db = DatabaseManager(self.config.database_file)
        self.telegram_service = TelegramService(self.config)
        self.binance_service = BinanceService(self.config)
        self.trading_service = TradingService(self.db, self.config)
        self.stats_service = StatsService(self.db, self.config)
        self.alert_service = AlertService.get_instance()

        # 3. Background Async Worker Thread
        self.async_worker = AsyncRunnerWorker(self)
        self.async_worker.task_finished.connect(self._on_async_task_finished)
        self.async_worker.task_error.connect(self._on_async_task_error)
        self.async_worker.start()

        # 4. Central UI Layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        self.header = HeaderBar(self)
        self.header.refresh_requested.connect(self.refresh_all_data)
        self.header.update_mode(self.config.mode, self.config.live_trading_enabled)
        main_layout.addWidget(self.header)

        # Body (Sidebar + StackedWidget)
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = Sidebar(self)
        self.sidebar.page_selected.connect(self._switch_page)
        body_layout.addWidget(self.sidebar)

        self.stacked_pages = QStackedWidget(self)

        # Instantiate 10 Pages
        self.page_overview = OverviewPage(self)
        self.page_connections = ConnectionsPage(self)
        self.page_groups = GroupsPage(self)
        self.page_signals = SignalsPage(self)
        self.page_trading = TradingPage(self)
        self.page_history = HistoryPage(self)
        self.page_stats = StatsPage(self)
        self.page_reviews = ReviewsPage(self)
        self.page_logs = LogsPage(self)
        self.page_settings = SettingsPage(self)

        self.stacked_pages.addWidget(self.page_overview)    # 0
        self.stacked_pages.addWidget(self.page_connections) # 1
        self.stacked_pages.addWidget(self.page_groups)      # 2
        self.stacked_pages.addWidget(self.page_signals)     # 3
        self.stacked_pages.addWidget(self.page_trading)     # 4
        self.stacked_pages.addWidget(self.page_history)     # 5
        self.stacked_pages.addWidget(self.page_stats)       # 6
        self.stacked_pages.addWidget(self.page_reviews)     # 7
        self.stacked_pages.addWidget(self.page_logs)        # 8
        self.stacked_pages.addWidget(self.page_settings)    # 9

        body_layout.addWidget(self.stacked_pages)
        main_layout.addLayout(body_layout)

        # 5. Connect Page Signals
        self._wire_signals()

        # 6. Periodic Refresh Timer (Every 5 seconds)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all_data)
        self.timer.start(5000)

        # 7. Initial data load
        self.page_groups.set_allowed_chat_ids(list(self.config.telegram.allowed_chat_ids))
        self.page_settings.load_settings(self.config)
        self.refresh_all_data()

        self.alert_service.add_alert(
            AlertLevel.INFO,
            "Ứng dụng đã khởi động",
            f"Chế độ hiện tại: {self.config.mode.value} (Live Trading: {self.config.live_trading_enabled})",
            "SYSTEM",
        )

    def _switch_page(self, page_idx: int):
        self.stacked_pages.setCurrentIndex(page_idx)

    def _wire_signals(self):
        # Connections Page
        self.page_connections.test_telegram_requested.connect(self._check_telegram_connection)
        self.page_connections.logout_telegram_requested.connect(self._logout_telegram)
        self.page_connections.test_binance_requested.connect(self._test_binance_connection)

        # Groups Page
        self.page_groups.refresh_dialogs_requested.connect(self._fetch_telegram_dialogs)
        self.page_groups.allowlist_updated.connect(self._on_allowlist_updated)
        self.page_groups.collect_history_requested.connect(self._start_collect_history)
        self.page_groups.cancel_collect_requested.connect(self.telegram_service.cancel_collection)

        # Signals Page
        self.page_signals.refresh_signals_requested.connect(self._refresh_signals_view)
        self.page_signals.signal_selected.connect(self._on_signal_selected)

        # Trading Page
        self.page_trading.refresh_trading_requested.connect(self.refresh_all_data)
        self.page_trading.cancel_pending_orders_requested.connect(self._on_cancel_pending_entries)
        self.page_trading.close_position_requested.connect(self._on_close_single_pos)
        self.page_trading.close_all_bot_positions_requested.connect(self._on_close_all_bot_pos)

        # History Page
        self.page_history.refresh_history_requested.connect(self._refresh_history_view)
        self.page_history.export_history_requested.connect(self._export_history_json)

        # Stats Page
        self.page_stats.timeframe_changed.connect(self._refresh_stats_view)

        # Reviews Page
        self.page_reviews.refresh_reviews_requested.connect(self._refresh_reviews_view)
        self.page_reviews.resolve_signal_requested.connect(self._on_resolve_signal)

        # Logs Page
        self.page_logs.refresh_logs_requested.connect(self._refresh_logs_view)
        self.page_logs.mark_all_read_requested.connect(self._on_mark_all_logs_read)

        # Settings Page
        self.page_settings.save_settings_requested.connect(self._save_settings)

    # -------------------------------------------------------------
    # Periodic & Manual Refresh Operations
    # -------------------------------------------------------------
    def refresh_all_data(self):
        now_str = datetime.utcnow().strftime("%H:%M:%S")
        self.header.set_sync_time(now_str)

        # 1. Update Telemetry & Overview
        telemetry = self.stats_service.get_telegram_telemetry()
        self.page_overview.update_telemetry(telemetry)

        # 2. Update Performance PnL
        pnl_today = self.stats_service.get_pnl_summary(0)
        pnl_7d = self.stats_service.get_pnl_summary(6)
        self.page_overview.update_performance_metrics(pnl_today, pnl_7d)

        # 3. Update Positions & Active Orders
        positions = self.trading_service.get_open_positions()
        is_live = (self.config.mode == ExecutionMode.LIVE and self.config.live_trading_enabled)
        self.page_overview.update_positions(positions)
        self.page_trading.update_positions_table(positions, is_live=is_live)

        orders = self.trading_service.get_active_orders()
        self.page_trading.update_orders_table(orders)

        # 4. Update Alerts & Logs
        alerts = self.alert_service.get_alerts(limit=50)
        self.page_overview.update_alerts_feed(alerts)
        self.page_logs.update_logs_table(alerts)

        # 5. Refresh Signals & Reviews Table
        self._refresh_signals_view()
        self._refresh_reviews_view()

        # 6. Check Telegram status in background
        self._check_telegram_connection()

    def _check_telegram_connection(self):
        self.async_worker.dispatch("CHECK_TG", self.telegram_service.get_account_profile)

    def _test_binance_connection(self):
        self.async_worker.dispatch("TEST_BINANCE", self.binance_service.test_connection)

    def _fetch_telegram_dialogs(self):
        self.async_worker.dispatch("FETCH_DIALOGS", self.telegram_service.list_accessible_dialogs)

    def _start_collect_history(self, chat_id: int, days: int, limit: int):
        def _cb(last_id, count):
            if self.page_groups.active_collect_dialog:
                self.page_groups.active_collect_dialog.update_progress(count, limit)

        self.async_worker.dispatch(
            "COLLECT_HISTORY",
            self.telegram_service.collect_history,
            chat_id,
            limit,
            days,
            _cb,
        )

    def _refresh_signals_view(self):
        state_filter = self.page_signals.state_filter.currentText()
        search_query = self.page_signals.search_input.text()
        signals = self.trading_service.get_signals(state_filter=state_filter, symbol_search=search_query)
        self.page_signals.update_signals_table(signals)

    def _on_signal_selected(self, signal_id: str):
        detail = self.trading_service.get_signal_detail(signal_id)
        if detail:
            self.page_signals.display_signal_detail(detail)

    def _refresh_reviews_view(self):
        pending = self.trading_service.get_pending_review_signals()
        self.page_reviews.update_reviews_table(pending)

    def _on_resolve_signal(self, signal_id: str, new_state: SignalState, reason: str):
        success = self.trading_service.resolve_signal_policy(signal_id, new_state, reason)
        if success:
            self.alert_service.add_alert(
                AlertLevel.INFO,
                "Duyệt tín hiệu thành công",
                f"Tín hiệu {signal_id} chuyển trạng thái sang {new_state.value}",
                "USER",
            )
            self.refresh_all_data()

    def _refresh_history_view(self):
        history = self.trading_service.get_signals(state_filter="CLOSED", limit=300)
        self.page_history.update_history_table(history)

    def _export_history_json(self, file_path: str):
        import json
        data = self.trading_service.signal_repo.export_history_data()
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Xuất thành công", f"Đã lưu lịch sử ra file: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi xuất file", str(e))

    def _refresh_stats_view(self, days_back: int):
        summary = self.stats_service.get_pnl_summary(days_back)
        self.page_stats.update_stats_view(summary)

    def _refresh_logs_view(self):
        alerts = self.alert_service.get_alerts(limit=100)
        self.page_logs.update_logs_table(alerts)

    def _on_mark_all_logs_read(self):
        self.alert_service.mark_all_as_read()
        self._refresh_logs_view()

    def _on_allowlist_updated(self, allowed_ids: list):
        self.config.telegram.allowed_chat_ids = allowed_ids
        self.alert_service.add_alert(
            AlertLevel.INFO,
            "Cập nhật danh sách theo dõi",
            f"Số kênh theo dõi hiện tại: {len(allowed_ids)}",
            "USER",
        )

    def _on_cancel_pending_entries(self, symbol: str):
        self.alert_service.add_alert(
            AlertLevel.WARNING,
            "Yêu cầu hủy pending entries",
            f"Đã yêu cầu hủy pending orders cho {symbol}",
            "USER",
        )

    def _on_close_single_pos(self, symbol: str):
        self.alert_service.add_alert(
            AlertLevel.WARNING,
            "Yêu cầu đóng vị thế",
            f"Đã yêu cầu đóng vị thế {symbol}",
            "USER",
        )

    def _on_close_all_bot_pos(self):
        self.alert_service.add_alert(
            AlertLevel.CRITICAL,
            "Yêu cầu đóng TẤT CẢ vị thế bot",
            "Đã gửi yêu cầu đóng toàn bộ vị thế bot",
            "USER",
        )

    def _logout_telegram(self):
        success = self.telegram_service.logout()
        if success:
            self.header.update_telegram_status(False)
            self.page_connections.update_telegram_view({"status": "NOT_LOGGED_IN"})
            QMessageBox.information(self, "Đăng xuất", "Đã xóa phiên đăng nhập Telegram tại local.")

    def _save_settings(self, payload: dict):
        new_mode_str = payload["mode"]
        self.config.mode = ExecutionMode(new_mode_str)
        self.config.live_trading_enabled = payload["live_trading_enabled"]
        self.config.risk.risk_per_signal_pct = payload["risk_per_signal_pct"]
        self.config.risk.max_daily_loss_pct = payload["max_daily_loss_pct"]
        self.config.risk.max_leverage = payload["max_leverage"]
        self.config.execution.entry_range_policy = payload["entry_range_policy"]
        self.config.execution.multi_tp_default_weight_mode = payload["multi_tp_default_weight_mode"]

        self.header.update_mode(self.config.mode, self.config.live_trading_enabled)
        self.alert_service.add_alert(
            AlertLevel.INFO,
            "Cập nhật cài đặt thành công",
            f"Chế độ mới: {self.config.mode.value} (Live: {self.config.live_trading_enabled})",
            "USER",
        )
        QMessageBox.information(self, "Thành công", "Đã lưu cài đặt mới vào cấu hình ứng dụng.")

    # -------------------------------------------------------------
    # Async Task Results Handler
    # -------------------------------------------------------------
    def _on_async_task_finished(self, task_id: str, result: Any):
        if task_id == "CHECK_TG":
            is_connected = (result.get("status") == "CONNECTED")
            self.header.update_telegram_status(is_connected, result.get("username_masked", ""))
            self.page_connections.update_telegram_view(result)

        elif task_id == "TEST_BINANCE":
            self.page_connections.update_binance_view(result)
            if result.get("success"):
                self.header.update_binance_status(True, result.get("position_mode", "UNKNOWN"))

        elif task_id == "FETCH_DIALOGS":
            self.page_groups.update_dialogs_table(result)

        elif task_id == "COLLECT_HISTORY":
            if self.page_groups.active_collect_dialog:
                self.page_groups.active_collect_dialog.on_finished(
                    True, f"Đã thu thập an toàn {len(result)} tin nhắn."
                )
            self.refresh_all_data()

    def _on_async_task_error(self, task_id: str, error_msg: str):
        self.alert_service.add_alert(
            AlertLevel.WARNING,
            f"Lỗi tác vụ {task_id}",
            error_msg,
            "ASYNC_WORKER",
        )
        if task_id == "COLLECT_HISTORY" and self.page_groups.active_collect_dialog:
            self.page_groups.active_collect_dialog.on_finished(False, error_msg)

    # -------------------------------------------------------------
    # Close Event Handling
    # -------------------------------------------------------------
    def closeEvent(self, event):
        engine_status = self.trading_service.get_engine_status()
        if engine_status != EngineStatus.STOPPED:
            reply = QMessageBox.question(
                self,
                "Xác nhận thoát ứng dụng",
                "<b>Cảnh báo thoát ứng dụng:</b><br>"
                "- Khi ứng dụng thoát, tiến trình nhận tín hiệu Telegram sẽ dừng.<br>"
                "- Các lệnh bảo vệ Stop Loss / Take Profit đã được sàn Binance xác nhận vẫn tồn tại độc lập trên sàn.<br>"
                "Bạn có chắc chắn muốn thoát ứng dụng hoàn toàn?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        # Stop worker thread gracefully
        self.async_worker.stop()
        if self.lock_file.isLocked():
            self.lock_file.unlock()
        event.accept()
