from typing import Any, Dict
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QFormLayout,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QLineEdit,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from core.enums import ExecutionMode
from ui.components.dialogs import ConfirmationDialog


class SettingsPage(QWidget):
    """
    Trang Cài đặt hệ thống:
    - Quản lý chế độ van hành (READ_ONLY, PAPER, TESTNET, LIVE)
    - Cấu hình quản trị rủi ro (Risk Limits)
    - Cấu hình chính sách khớp lệnh (Execution Policies)
    - Thao tác chuyển sang LIVE bắt buộc có xác nhận riêng
    """

    save_settings_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. CHẾ ĐỘ VẬN HÀNH
        # -------------------------------------------------------------
        mode_box = QGroupBox("CHẾ ĐỘ VẬN HÀNH VÀ KHÓA AN TOÀN")
        mode_layout = QFormLayout(mode_box)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("READ_ONLY (Chỉ đọc, không can thiệp sàn)", "READ_ONLY")
        self.mode_combo.addItem("PAPER (Mô phỏng khớp lệnh thực tế)", "PAPER")
        self.mode_combo.addItem("TESTNET (Giao dịch trên Binance Testnet)", "TESTNET")
        self.mode_combo.addItem("LIVE (GIAO DỊCH TIỀN THẬT TRÊN BINANCE)", "LIVE")
        mode_layout.addRow("Chế độ:", self.mode_combo)

        layout.addWidget(mode_box)

        # -------------------------------------------------------------
        # 2. CHÍNH SÁCH QUẢN TRỊ RỦI RO (RISK MANAGEMENT)
        # -------------------------------------------------------------
        risk_box = QGroupBox("CHÍNH SÁCH QUẢN TRỊ RỦI RO (RISK MANAGEMENT)")
        risk_layout = QFormLayout(risk_box)

        self.risk_pct_spin = QDoubleSpinBox()
        self.risk_pct_spin.setRange(0.1, 10.0)
        self.risk_pct_spin.setSingleStep(0.1)
        self.risk_pct_spin.setValue(1.5)
        self.risk_pct_spin.setSuffix(" % Equity / Kèo")
        risk_layout.addRow("Rủi ro tối đa mỗi kèo:", self.risk_pct_spin)

        self.daily_loss_spin = QDoubleSpinBox()
        self.daily_loss_spin.setRange(1.0, 20.0)
        self.daily_loss_spin.setSingleStep(0.5)
        self.daily_loss_spin.setValue(5.0)
        self.daily_loss_spin.setSuffix(" % Equity / Ngày")
        risk_layout.addRow("Giới hạn lỗ tối đa trong ngày:", self.daily_loss_spin)

        self.max_lev_spin = QSpinBox()
        self.max_lev_spin.setRange(1, 125)
        self.max_lev_spin.setValue(50)
        self.max_lev_spin.setSuffix(" x (Trần an toàn)")
        risk_layout.addRow("Đòn bẩy tối đa hệ thống cho phép:", self.max_lev_spin)

        self.margin_mode_lbl = QLabel("ISOLATED (Mặc định bắt buộc theo chính sách)")
        self.margin_mode_lbl.setStyleSheet("color: #10b981; font-weight: 600;")
        risk_layout.addRow("Chế độ ký quỹ:", self.margin_mode_lbl)

        layout.addWidget(risk_box)

        # -------------------------------------------------------------
        # 3. CHÍNH SÁCH PHÂN BỔ ENTRY VÀ TP
        # -------------------------------------------------------------
        policy_box = QGroupBox("CHÍNH SÁCH XỬ LÝ VÙNG GIÁ VÀ NHIỀU MỤC TIÊU")
        policy_layout = QFormLayout(policy_box)

        self.range_policy_combo = QComboBox()
        self.range_policy_combo.addItem("NEEDS_POLICY (Chặn lại để hỏi người dùng)", "NEEDS_POLICY")
        self.range_policy_combo.addItem("MID_POINT (Lấy trung điểm vùng entry)", "MID_POINT")
        self.range_policy_combo.addItem("BEST_PRICE (Đặt limit tại giá tốt nhất)", "BEST_PRICE")
        policy_layout.addRow("Xử lý Entry dạng Range:", self.range_policy_combo)

        self.tp_policy_combo = QComboBox()
        self.tp_policy_combo.addItem("NEEDS_POLICY (Chặn lại để hỏi người dùng)", "NEEDS_POLICY")
        self.tp_policy_combo.addItem("FRONT_LOADED_50_30_20 (50% TP1, 30% TP2, 20% TP3)", "FRONT_LOADED_50_30_20")
        self.tp_policy_combo.addItem("EQUAL_SPLIT (Chia đều theo số lượng TP)", "EQUAL_SPLIT")
        policy_layout.addRow("Xử lý chia tỷ lệ Take Profit:", self.tp_policy_combo)

        layout.addWidget(policy_box)

        # Bottom save row
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.save_btn = QPushButton("Lưu cấu hình hệ thống")
        self.save_btn.setProperty("class", "primary-btn")
        self.save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)
        layout.addStretch()

    def load_settings(self, config):
        # Mode
        idx = self.mode_combo.findData(config.mode.value)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

        # Risk
        self.risk_pct_spin.setValue(float(config.risk.risk_per_signal_pct))
        self.daily_loss_spin.setValue(float(config.risk.max_daily_loss_pct))
        self.max_lev_spin.setValue(int(config.risk.max_leverage))

        # Policies
        idx_range = self.range_policy_combo.findData(config.execution.entry_range_policy)
        if idx_range >= 0:
            self.range_policy_combo.setCurrentIndex(idx_range)

        idx_tp = self.tp_policy_combo.findData(config.execution.multi_tp_default_weight_mode)
        if idx_tp >= 0:
            self.tp_policy_combo.setCurrentIndex(idx_tp)

    def _on_save_clicked(self):
        new_mode_str = self.mode_combo.currentData()
        if new_mode_str == "LIVE":
            confirmed = ConfirmationDialog.confirm(
                title="XÁC NHẬN CHUYỂN SANG LIVE TRADING",
                message=(
                    "<b>CẢNH BÁO NGUY HIỂM:</b> Bạn đang yêu cầu kích hoạt chế độ <b>LIVE TRADING</b>.<br>"
                    "- Bot sẽ có quyền đặt lệnh tiền thật trực tiếp trên tài khoản Binance Futures của bạn.<br>"
                    "- Giao dịch đòn bẩy có nguy cơ thua lỗ cao.<br>"
                    "Nếu chắc chắn, hãy nhập cụm từ <b>BAT LIVE</b> bên dưới để xác nhận:"
                ),
                confirm_btn_text="Kích hoạt Live Trading",
                is_dangerous=True,
                required_phrase="BAT LIVE",
                parent=self,
            )
            if not confirmed:
                return

        payload = {
            "mode": new_mode_str,
            "live_trading_enabled": (new_mode_str == "LIVE"),
            "risk_per_signal_pct": self.risk_pct_spin.value(),
            "max_daily_loss_pct": self.daily_loss_spin.value(),
            "max_leverage": self.max_lev_spin.value(),
            "entry_range_policy": self.range_policy_combo.currentData(),
            "multi_tp_default_weight_mode": self.tp_policy_combo.currentData(),
        }
        self.save_settings_requested.emit(payload)

