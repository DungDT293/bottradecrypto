from typing import Optional
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QLineEdit,
    QDialog,
    QFormLayout,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from ui.components.dialogs import ConfirmationDialog


class TelegramLoginDialog(QDialog):
    """
    In-app interactive modal for Telegram MTProto authentication.
    Strictly masks sensitive credentials and clears fields immediately after use.
    """

    code_requested = Signal(str)            # phone
    code_submitted = Signal(str, str)        # code, 2fa_password

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ĐĂNG NHẬP TELEGRAM MTPROTO")
        self.setFixedWidth(440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        info_lbl = QLabel(
            "Đăng nhập tài khoản cá nhân qua giao thức MTProto chính thức của Telegram.<br>"
            "<i>(Mật khẩu và OTP không bao giờ được lưu vào log hay gửi ra ngoài)</i>"
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(info_lbl)

        form_box = QGroupBox("Thông tin xác thực")
        form_layout = QFormLayout(form_box)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+84912345678")
        form_layout.addRow("Số điện thoại:", self.phone_input)

        self.send_code_btn = QPushButton("Gửi mã xác nhận (OTP)")
        self.send_code_btn.setProperty("class", "primary-btn")
        self.send_code_btn.clicked.connect(self._on_send_code)
        form_layout.addRow("", self.send_code_btn)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Nhập mã 5 chữ số từ Telegram")
        self.code_input.setEnabled(False)
        form_layout.addRow("Mã xác nhận:", self.code_input)

        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.pwd_input.setPlaceholderText("Chỉ điền nếu tài khoản bật 2FA")
        self.pwd_input.setEnabled(False)
        form_layout.addRow("Mật khẩu 2FA:", self.pwd_input)

        layout.addWidget(form_box)

        # Status text
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #f59e0b; font-size: 12px;")
        layout.addWidget(self.status_lbl)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Đóng")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.submit_btn = QPushButton("Hoàn tất đăng nhập")
        self.submit_btn.setProperty("class", "success-btn")
        self.submit_btn.setEnabled(False)
        self.submit_btn.clicked.connect(self._on_submit_login)
        btn_row.addWidget(self.submit_btn)

        layout.addLayout(btn_row)

    def _on_send_code(self):
        phone = self.phone_input.text().strip()
        if not phone:
            self.status_lbl.setText("Vui lòng nhập số điện thoại (ví dụ: +84912345678).")
            return
        self.status_lbl.setText("Đang gửi yêu cầu gửi mã xác nhận đến Telegram...")
        self.code_requested.emit(phone)

    def on_code_sent(self, success: bool, msg: str = ""):
        if success:
            self.status_lbl.setText("Đã gửi mã xác thực thành công. Vui lòng nhập mã bên dưới.")
            self.status_lbl.setStyleSheet("color: #10b981; font-size: 12px;")
            self.code_input.setEnabled(True)
            self.pwd_input.setEnabled(True)
            self.submit_btn.setEnabled(True)
            self.send_code_btn.setEnabled(False)
            self.phone_input.setEnabled(False)
            self.code_input.setFocus()
        else:
            self.status_lbl.setText(f"Lỗi: {msg}")
            self.status_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")

    def _on_submit_login(self):
        code = self.code_input.text().strip()
        pwd = self.pwd_input.text()
        if not code:
            self.status_lbl.setText("Vui lòng nhập mã xác nhận nhận được từ Telegram.")
            return
        self.status_lbl.setText("Đang xác thực tài khoản...")
        self.code_submitted.emit(code, pwd)

    def on_login_result(self, success: bool, msg: str = ""):
        if success:
            self.status_lbl.setText("Đăng nhập thành công!")
            self.status_lbl.setStyleSheet("color: #10b981; font-size: 12px;")
            # Clear sensitive fields immediately
            self.code_input.clear()
            self.pwd_input.clear()
            self.accept()
        else:
            self.status_lbl.setText(f"Đăng nhập thất bại: {msg}")
            self.status_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")


class ConnectionsPage(QWidget):
    """
    Trang Kết nối:
    - Quản lý trạng thái và đăng nhập/đăng xuất Telegram MTProto
    - Quản lý cấu hình và kiểm tra kết nối Binance USD-M Futures
    """

    test_telegram_requested = Signal()
    login_telegram_requested = Signal(str, str, str) # phone, code, pwd
    logout_telegram_requested = Signal()
    test_binance_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. TELEGRAM MTPROTO CONNECTION
        # -------------------------------------------------------------
        tg_box = QGroupBox("KẾT NỐI TELEGRAM (MTPROTO READ-ONLY USER ACCOUNT)")
        tg_layout = QVBoxLayout(tg_box)
        tg_layout.setSpacing(12)

        self.tg_status_lbl = QLabel("Trạng thái: Đang kiểm tra...")
        self.tg_status_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #94a3b8;")
        tg_layout.addWidget(self.tg_status_lbl)

        self.tg_profile_lbl = QLabel("Tài khoản: Chưa đăng nhập")
        self.tg_profile_lbl.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        tg_layout.addWidget(self.tg_profile_lbl)

        tg_btn_row = QHBoxLayout()
        self.login_btn = QPushButton("Đăng nhập tài khoản")
        self.login_btn.setProperty("class", "primary-btn")
        self.login_btn.clicked.connect(self._open_login_dialog)
        tg_btn_row.addWidget(self.login_btn)

        self.check_tg_btn = QPushButton("Kiểm tra kết nối")
        self.check_tg_btn.clicked.connect(self.test_telegram_requested.emit)
        tg_btn_row.addWidget(self.check_tg_btn)

        self.logout_btn = QPushButton("Đăng xuất")
        self.logout_btn.setProperty("class", "danger-btn")
        self.logout_btn.clicked.connect(self._on_logout_clicked)
        tg_btn_row.addWidget(self.logout_btn)

        tg_btn_row.addStretch()
        tg_layout.addLayout(tg_btn_row)
        layout.addWidget(tg_box)

        # -------------------------------------------------------------
        # 2. BINANCE USD-M FUTURES CONNECTION
        # -------------------------------------------------------------
        bn_box = QGroupBox("KẾT NỐI BINANCE USD-M FUTURES")
        bn_layout = QVBoxLayout(bn_box)
        bn_layout.setSpacing(12)

        self.bn_env_lbl = QLabel("Môi trường: TESTNET (Mặc định cấu hình an toàn)")
        self.bn_env_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #fcd34d;")
        bn_layout.addWidget(self.bn_env_lbl)

        self.bn_keys_lbl = QLabel("API Key: [ĐÃ CẤU HÌNH VÀ CHE MẬT MÃ] | Secret: [ĐÃ CHE AN TOÀN]")
        self.bn_keys_lbl.setStyleSheet("font-size: 12px; color: #94a3b8;")
        bn_layout.addWidget(self.bn_keys_lbl)

        self.bn_status_lbl = QLabel("Kết nối: Chưa kiểm tra")
        self.bn_status_lbl.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        bn_layout.addWidget(self.bn_status_lbl)

        bn_btn_row = QHBoxLayout()
        self.check_bn_btn = QPushButton("Kiểm tra kết nối Binance (Read-Only)")
        self.check_bn_btn.setProperty("class", "primary-btn")
        self.check_bn_btn.clicked.connect(self.test_binance_requested.emit)
        bn_btn_row.addWidget(self.check_bn_btn)
        bn_btn_row.addStretch()
        bn_layout.addLayout(bn_btn_row)

        layout.addWidget(bn_box)
        layout.addStretch()

        self.login_dialog: Optional[TelegramLoginDialog] = None

    def update_telegram_view(self, profile: dict):
        status = profile.get("status", "NOT_LOGGED_IN")
        if status == "CONNECTED":
            self.tg_status_lbl.setText("Trạng thái: ĐÃ ĐĂNG NHẬP VÀ SẴN SÀNG (READ-ONLY)")
            self.tg_status_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #10b981;")
            fname = profile.get("first_name", "Telegram User")
            uname = profile.get("username_masked", "")
            phone = profile.get("phone_masked", "")
            self.tg_profile_lbl.setText(f"Tài khoản: {fname} | Username: {uname} | SĐT: {phone}")
            self.login_btn.setEnabled(False)
            self.logout_btn.setEnabled(True)
        else:
            self.tg_status_lbl.setText("Trạng thái: CHƯA ĐĂNG NHẬP")
            self.tg_status_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #f59e0b;")
            self.tg_profile_lbl.setText("Tài khoản: Chưa có phiên đăng nhập hợp lệ.")
            self.login_btn.setEnabled(True)
            self.logout_btn.setEnabled(False)

    def update_binance_view(self, res: dict):
        if res.get("success"):
            equity = res.get("equity", 0.0)
            pm = res.get("position_mode", "ONE_WAY")
            self.bn_status_lbl.setText(f"Kết nối thành công! Ký quỹ: {equity:,.2f} USDT | Position Mode: {pm} [OK]")
            self.bn_status_lbl.setStyleSheet("font-size: 12px; color: #10b981; font-weight: 600;")
        else:
            err = res.get("error", "Lỗi không xác định")
            self.bn_status_lbl.setText(f"Lỗi kiểm tra kết nối: {err}")
            self.bn_status_lbl.setStyleSheet("font-size: 12px; color: #ef4444;")

    def _open_login_dialog(self):
        self.login_dialog = TelegramLoginDialog(self)
        self.login_dialog.show()

    def _on_logout_clicked(self):
        confirmed = ConfirmationDialog.confirm(
            title="XÁC NHẬN ĐĂNG XUẤT TELEGRAM",
            message=(
                "<b>Cảnh báo đăng xuất:</b><br>"
                "- Quá trình quét và lắng nghe tin nhắn Telegram mới sẽ dừng ngay lập tức.<br>"
                "- Thao tác này <b>KHÔNG</b> tự động đóng hoặc hủy bất kỳ vị thế nào trên Binance.<br>"
                "Bạn có chắc chắn muốn đăng xuất phiên làm việc hiện tại?"
            ),
            confirm_btn_text="Đăng xuất",
            is_dangerous=True,
            parent=self,
        )
        if confirmed:
            self.logout_telegram_requested.emit()

