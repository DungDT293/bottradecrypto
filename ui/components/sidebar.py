from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QButtonGroup,
)
from PySide6.QtCore import Signal, Qt


class Sidebar(QFrame):
    """
    Application navigation sidebar with 10 primary views.
    """

    page_selected = Signal(int)

    PAGES = [
        ("📊  Tổng quan", 0),
        ("🔗  Kết nối", 1),
        ("👥  Nhóm Telegram", 2),
        ("🎯  Tín hiệu", 3),
        ("⚡  Đang giao dịch", 4),
        ("📜  Lịch sử", 5),
        ("📈  Thống kê", 6),
        ("⏳  Chờ xác nhận", 7),
        ("📝  Nhật ký", 8),
        ("⚙️  Cài đặt", 9),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 14, 8, 14)
        layout.setSpacing(4)

        # Brand header
        brand = QLabel("QUẢN LÝ BOT")
        brand.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; padding-left: 12px; margin-bottom: 6px;")
        layout.addWidget(brand)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        for index, (title, page_idx) in enumerate(self.PAGES):
            btn = QPushButton(title)
            btn.setCheckable(True)
            btn.setProperty("class", "nav-btn")
            btn.clicked.connect(lambda checked, idx=page_idx: self.page_selected.emit(idx))
            self.button_group.addButton(btn, page_idx)
            layout.addWidget(btn)

            if index == 0:
                btn.setChecked(True)

        layout.addStretch()

        # Version tag
        ver = QLabel("v1.2.0 • One-Way")
        ver.setStyleSheet("color: #475569; font-size: 11px; text-align: center; padding-left: 12px;")
        layout.addWidget(ver)

    def set_active_page(self, page_idx: int):
        btn = self.button_group.button(page_idx)
        if btn:
            btn.setChecked(True)

