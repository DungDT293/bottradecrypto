from typing import Any, Dict, List, Optional
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLineEdit,
    QDialog,
    QSpinBox,
    QProgressBar,
    QFormLayout,
    QCheckBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from ui.components.dialogs import ConfirmationDialog


class CollectHistoryDialog(QDialog):
    """
    Modal dialog for collecting historical messages with limits, FloodWait tracking,
    and safe cancellation.
    """

    start_collection_requested = Signal(int, int, int) # chat_id, days, limit
    cancel_requested = Signal()

    def __init__(self, chat_id: int, chat_title: str, parent=None):
        super().__init__(parent)
        self.chat_id = chat_id
        self.setWindowTitle("THU THẬP LỊCH SỬ TELEGRAM (READ-ONLY)")
        self.setFixedWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        info = QLabel(
            f"Kênh/Nhóm: <b>{chat_title}</b> (Chat ID: <code>{chat_id}</code>)<br>"
            "<span style='color: #94a3b8;'>Hệ thống chỉ đọc văn bản, tuyệt đối không tải media, "
            "không mở URL, và <b>không chuyển lịch sử thành lệnh giao dịch</b>.</span>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 30)
        self.days_spin.setValue(7)
        self.days_spin.setSuffix(" ngày gần nhất")
        form.addRow("Khoảng thời gian:", self.days_spin)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(50, 2000)
        self.limit_spin.setValue(1000)
        self.limit_spin.setSingleStep(100)
        self.limit_spin.setSuffix(" tin nhắn")
        form.addRow("Số lượng tối đa:", self.limit_spin)

        layout.addLayout(form)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Sẵn sàng bắt đầu.")
        self.status_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.status_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Đóng")
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_btn)

        self.start_btn = QPushButton("Bắt đầu thu thập")
        self.start_btn.setProperty("class", "primary-btn")
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn)

        layout.addLayout(btn_row)

    def _on_start(self):
        self.start_btn.setEnabled(False)
        self.cancel_btn.setText("Hủy tác vụ")
        self.status_lbl.setText("Đang kết nối và quét dữ liệu...")
        self.status_lbl.setStyleSheet("color: #3b82f6; font-size: 11px;")
        self.start_collection_requested.emit(
            self.chat_id,
            self.days_spin.value(),
            self.limit_spin.value(),
        )

    def _on_cancel(self):
        if not self.start_btn.isEnabled():
            self.cancel_requested.emit()
            self.status_lbl.setText("Đã gửi yêu cầu hủy tác vụ...")
            self.status_lbl.setStyleSheet("color: #ef4444; font-size: 11px;")
        else:
            self.reject()

    def update_progress(self, current: int, total: int):
        pct = int((current / max(1, total)) * 100)
        self.progress_bar.setValue(min(100, pct))
        self.status_lbl.setText(f"Đã tải {current} tin nhắn...")

    def on_finished(self, success: bool, message: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setText("Đóng")
        if success:
            self.progress_bar.setValue(100)
            self.status_lbl.setText(f"Hoàn thành: {message}")
            self.status_lbl.setStyleSheet("color: #10b981; font-size: 11px; font-weight: 600;")
        else:
            self.status_lbl.setText(f"Thất bại: {message}")
            self.status_lbl.setStyleSheet("color: #ef4444; font-size: 11px;")


class GroupsPage(QWidget):
    """
    Trang Nhóm Telegram:
    - Quản lý danh sách các kênh/nhóm truy cập được
    - Lựa chọn danh sách cho phép (Allowlist)
    - Kích hoạt thu thập lịch sử an toàn
    """

    refresh_dialogs_requested = Signal()
    allowlist_updated = Signal(list) # list of allowed_chat_ids
    collect_history_requested = Signal(int, int, int) # chat_id, days, limit
    cancel_collect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dialogs_data: List[Dict[str, Any]] = []
        self.allowed_chat_ids: List[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Top Control Row
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title = QLabel("DANH SÁCH NHÓM VÀ KÊNH TELEGRAM")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        top_row.addWidget(title)

        top_row.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm kiếm nhóm hoặc Chat ID...")
        self.search_input.setFixedWidth(240)
        self.search_input.textChanged.connect(self._filter_table)
        top_row.addWidget(self.search_input)

        self.refresh_btn = QPushButton("Tải lại danh sách")
        self.refresh_btn.clicked.connect(self.refresh_dialogs_requested.emit)
        top_row.addWidget(self.refresh_btn)

        layout.addLayout(top_row)

        # Dialogs Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Theo dõi", "Tên Kênh / Nhóm", "Chat ID", "Loại", "Chưa đọc", "Thao tác"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        self.active_collect_dialog: Optional[CollectHistoryDialog] = None

    def set_allowed_chat_ids(self, ids: List[int]):
        self.allowed_chat_ids = ids

    def update_dialogs_table(self, dialogs: Any):
        if isinstance(dialogs, dict):
            self.dialogs_data = dialogs.get("dialogs", [])
        else:
            self.dialogs_data = dialogs or []
        self._filter_table()

    def _filter_table(self):
        query = self.search_input.text().strip().lower()
        filtered = [
            d for d in self.dialogs_data
            if not query or query in d["title"].lower() or query in str(d["id"])
        ]

        self.table.setRowCount(len(filtered))
        for row, d in enumerate(filtered):
            chat_id = d["id"]
            is_allowed = chat_id in self.allowed_chat_ids

            # Column 0: Checkbox for allowlist
            chk = QCheckBox()
            chk.setChecked(is_allowed)
            chk.stateChanged.connect(lambda state, cid=chat_id: self._toggle_allowlist(cid, state))
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, chk_widget)

            # Column 1: Title
            self.table.setItem(row, 1, QTableWidgetItem(d.get("title", "N/A")))

            # Column 2: Chat ID
            item_id = QTableWidgetItem(str(chat_id))
            item_id.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, item_id)

            # Column 3: Type
            kind = "Kênh" if d.get("is_channel") else "Nhóm"
            item_kind = QTableWidgetItem(kind)
            item_kind.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, item_kind)

            # Column 4: Unread count
            item_unread = QTableWidgetItem(str(d.get("unread_count", 0)))
            item_unread.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, item_unread)

            # Column 5: Action button
            action_btn = QPushButton("Thu thập lịch sử")
            action_btn.setFixedHeight(26)
            action_btn.clicked.connect(lambda _, cid=chat_id, title=d["title"]: self._open_collect_dialog(cid, title))
            self.table.setCellWidget(row, 5, action_btn)

    def _toggle_allowlist(self, chat_id: int, state: int):
        if state == Qt.Checked.value:
            if chat_id not in self.allowed_chat_ids:
                self.allowed_chat_ids.append(chat_id)
        else:
            if chat_id in self.allowed_chat_ids:
                self.allowed_chat_ids.remove(chat_id)
        self.allowlist_updated.emit(self.allowed_chat_ids)

    def _open_collect_dialog(self, chat_id: int, title: str):
        self.active_collect_dialog = CollectHistoryDialog(chat_id, title, self)
        self.active_collect_dialog.start_collection_requested.connect(self.collect_history_requested.emit)
        self.active_collect_dialog.cancel_requested.connect(self.cancel_collect_requested.emit)
        self.active_collect_dialog.show()

