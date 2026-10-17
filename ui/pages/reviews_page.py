from typing import Any, Dict, List
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from core.enums import SignalState
from ui.components.dialogs import ConfirmationDialog


class ReviewsPage(QWidget):
    """
    Trang Chờ xác nhận (Needs Review / Needs Policy):
    - Quản lý các tín hiệu bị chặn an toàn chờ quyết định của người dùng
    - Hỗ trợ duyệt chính sách thủ công hoặc từ chối bỏ qua
    """

    resolve_signal_requested = Signal(str, SignalState, str) # signal_id, new_state, reason
    refresh_reviews_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Top Row
        top_row = QHBoxLayout()
        title = QLabel("TÍN HIỆU CHỜ XÁC NHẬN VÀ BỔ SUNG CHÍNH SÁCH")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        top_row.addWidget(title)
        top_row.addStretch()

        self.refresh_btn = QPushButton("Làm mới")
        self.refresh_btn.clicked.connect(self.refresh_reviews_requested.emit)
        top_row.addWidget(self.refresh_btn)

        layout.addLayout(top_row)

        info_lbl = QLabel(
            "Các tín hiệu dưới đây đang được tạm dừng để bảo vệ an toàn vốn theo quy tắc: "
            "không tự ý đoán giá range, không tự ý nới đòn bẩy quá trần, không vào lệnh khi ngữ nghĩa mâu thuẫn."
        )
        info_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(info_lbl)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Signal ID", "Thời gian", "Symbol", "Hướng", "Trạng thái", "Lý do chặn", "Thao tác"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        self.signals_data: List[Dict[str, Any]] = []

    def update_reviews_table(self, signals: List[Dict[str, Any]]):
        self.signals_data = signals
        self.table.setRowCount(len(signals))

        for row, s in enumerate(signals):
            sig_id = s.get("signal_id", "")
            self.table.setItem(row, 0, QTableWidgetItem(sig_id))
            self.table.setItem(row, 1, QTableWidgetItem(s.get("created_at", "")[:19]))
            self.table.setItem(row, 2, QTableWidgetItem(s.get("symbol", "N/A")))
            self.table.setItem(row, 3, QTableWidgetItem(s.get("side", "N/A")))

            state_item = QTableWidgetItem(s.get("state", ""))
            state_item.setForeground(Qt.yellow)
            self.table.setItem(row, 4, state_item)

            self.table.setItem(row, 5, QTableWidgetItem(s.get("blocking_reason", "")))

            # Action Buttons container
            btn_box = QWidget()
            btn_layout = QHBoxLayout(btn_box)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(6)

            approve_btn = QPushButton("Duyệt")
            approve_btn.setProperty("class", "success-btn")
            approve_btn.setFixedHeight(24)
            approve_btn.clicked.connect(lambda _, sid=sig_id: self._on_approve(sid))
            btn_layout.addWidget(approve_btn)

            reject_btn = QPushButton("Hủy bỏ")
            reject_btn.setProperty("class", "danger-btn")
            reject_btn.setFixedHeight(24)
            reject_btn.clicked.connect(lambda _, sid=sig_id: self._on_reject(sid))
            btn_layout.addWidget(reject_btn)

            self.table.setCellWidget(row, 6, btn_box)

    def _on_approve(self, signal_id: str):
        confirmed = ConfirmationDialog.confirm(
            title="DUYỆT TÍN HIỆU THỦ CÔNG",
            message=f"Bạn có chắc chắn muốn duyệt và chuyển tín hiệu <b>{signal_id}</b> sang trạng thái VALIDATED?",
            confirm_btn_text="Duyệt tín hiệu",
            parent=self,
        )
        if confirmed:
            self.resolve_signal_requested.emit(signal_id, SignalState.VALIDATED, "Người dùng xác nhận thủ công")

    def _on_reject(self, signal_id: str):
        confirmed = ConfirmationDialog.confirm(
            title="TỪ CHỐI TÍN HIỆU",
            message=f"Xác nhận loại bỏ tín hiệu <b>{signal_id}</b> và đánh dấu REJECTED?",
            confirm_btn_text="Từ chối tín hiệu",
            is_dangerous=True,
            parent=self,
        )
        if confirmed:
            self.resolve_signal_requested.emit(signal_id, SignalState.REJECTED, "Người dùng từ chối bỏ qua")

