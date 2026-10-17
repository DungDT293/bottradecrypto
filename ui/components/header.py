from datetime import datetime
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from core.enums import ExecutionMode


class HeaderBar(QFrame):
    """
    Top application header bar.
    Displays:
    - App Name
    - Prominent Mode Badge (READ_ONLY / PAPER / TESTNET / LIVE with text label)
    - Telegram & Binance connection status badges
    - Engine status badge
    - Last sync timestamp & stale data warning indicator
    - Manual refresh button
    """

    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(54)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(14)

        # 1. App Title
        title_box = QHBoxLayout()
        title_box.setSpacing(8)
        app_title = QLabel("TELEGRAM BINANCE SIGNAL EXECUTOR")
        app_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc; letter-spacing: 0.5px;")
        title_box.addWidget(app_title)
        layout.addLayout(title_box)

        # 2. Mode Badge (Prominently displayed)
        self.mode_badge = QLabel("CHẾ ĐỘ: READ_ONLY")
        self.mode_badge.setStyleSheet(
            "background-color: #334155; color: #94a3b8; font-weight: 700; "
            "padding: 4px 10px; border-radius: 4px; font-size: 11px; border: 1px solid #475569;"
        )
        layout.addWidget(self.mode_badge)

        layout.addStretch()

        # 3. Telegram Status Badge
        self.tg_badge = QLabel("TELEGRAM: CHƯA KẾT NỐI")
        self.tg_badge.setStyleSheet(
            "background-color: #1e293b; color: #94a3b8; font-weight: 600; "
            "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;"
        )
        layout.addWidget(self.tg_badge)

        # 4. Binance Status Badge
        self.binance_badge = QLabel("BINANCE: CHƯA KẾT NỐI")
        self.binance_badge.setStyleSheet(
            "background-color: #1e293b; color: #94a3b8; font-weight: 600; "
            "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;"
        )
        layout.addWidget(self.binance_badge)

        # 5. Engine Status Badge
        self.engine_badge = QLabel("ENGINE: ĐÃ DỪNG")
        self.engine_badge.setStyleSheet(
            "background-color: #1e293b; color: #94a3b8; font-weight: 600; "
            "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;"
        )
        layout.addWidget(self.engine_badge)

        # 6. Last Sync & Stale Warning
        self.sync_label = QLabel("Đồng bộ: --:--:--")
        self.sync_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.sync_label)

        # 7. Refresh Button
        self.refresh_btn = QPushButton("Làm mới")
        self.refresh_btn.setFixedHeight(28)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self.refresh_btn)

    def update_mode(self, mode: ExecutionMode, live_enabled: bool = False):
        if mode == ExecutionMode.LIVE and live_enabled:
            self.mode_badge.setText("CHẾ ĐỘ: LIVE TRADING (TIỀN THẬT)")
            self.mode_badge.setStyleSheet(
                "background-color: #7f1d1d; color: #fca5a5; font-weight: 700; "
                "padding: 4px 10px; border-radius: 4px; font-size: 11px; border: 1px solid #ef4444;"
            )
        elif mode == ExecutionMode.TESTNET:
            self.mode_badge.setText("CHẾ ĐỘ: TESTNET")
            self.mode_badge.setStyleSheet(
                "background-color: #78350f; color: #fcd34d; font-weight: 700; "
                "padding: 4px 10px; border-radius: 4px; font-size: 11px; border: 1px solid #f59e0b;"
            )
        elif mode == ExecutionMode.PAPER:
            self.mode_badge.setText("CHẾ ĐỘ: PAPER (GIẢ LẬP)")
            self.mode_badge.setStyleSheet(
                "background-color: #1e3a8a; color: #93c5fd; font-weight: 700; "
                "padding: 4px 10px; border-radius: 4px; font-size: 11px; border: 1px solid #3b82f6;"
            )
        else:
            self.mode_badge.setText("CHẾ ĐỘ: READ_ONLY (CHỈ ĐỌC)")
            self.mode_badge.setStyleSheet(
                "background-color: #064e3b; color: #6ee7b7; font-weight: 700; "
                "padding: 4px 10px; border-radius: 4px; font-size: 11px; border: 1px solid #10b981;"
            )

    def update_telegram_status(self, is_connected: bool, details: str = ""):
        if is_connected:
            self.tg_badge.setText(f"TELEGRAM: ĐÃ KẾT NỐI {details}".strip())
            self.tg_badge.setStyleSheet(
                "background-color: #064e3b; color: #6ee7b7; font-weight: 600; "
                "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #10b981;"
            )
        else:
            self.tg_badge.setText(f"TELEGRAM: CHƯA ĐĂNG NHẬP")
            self.tg_badge.setStyleSheet(
                "background-color: #1e293b; color: #94a3b8; font-weight: 600; "
                "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;"
            )

    def update_binance_status(self, is_connected: bool, position_mode: str = "UNKNOWN"):
        if is_connected:
            self.binance_badge.setText(f"BINANCE: ONE-WAY [OK]" if position_mode == "ONE_WAY" else f"BINANCE: {position_mode}")
            self.binance_badge.setStyleSheet(
                "background-color: #064e3b; color: #6ee7b7; font-weight: 600; "
                "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #10b981;"
            )
        else:
            self.binance_badge.setText("BINANCE: CHƯA KẾT NỐI")
            self.binance_badge.setStyleSheet(
                "background-color: #1e293b; color: #94a3b8; font-weight: 600; "
                "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;"
            )

    def update_engine_status(self, status: str):
        self.engine_badge.setText(f"ENGINE: {status}")
        if "RUNNING" in status:
            self.engine_badge.setStyleSheet(
                "background-color: #1e3a8a; color: #93c5fd; font-weight: 600; "
                "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #3b82f6;"
            )
        else:
            self.engine_badge.setStyleSheet(
                "background-color: #1e293b; color: #94a3b8; font-weight: 600; "
                "padding: 3px 8px; border-radius: 4px; font-size: 11px; border: 1px solid #334155;"
            )

    def set_sync_time(self, timestamp_str: str, is_stale: bool = False):
        if is_stale:
            self.sync_label.setText(f"Đồng bộ: {timestamp_str} (CẢNH BÁO: DỮ LIỆU CŨ)")
            self.sync_label.setStyleSheet("color: #f59e0b; font-size: 11px; font-weight: 600;")
        else:
            self.sync_label.setText(f"Đồng bộ: {timestamp_str}")
            self.sync_label.setStyleSheet("color: #64748b; font-size: 11px;")

