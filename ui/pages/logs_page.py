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
    QComboBox,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal


class LogsPage(QWidget):
    """
    Trang Nhật ký và Cảnh báo hệ thống:
    - Bảng thông báo và cảnh báo (INFO, WARNING, CRITICAL)
    - Bộ lọc cấp độ và tìm kiếm nội dung
    - Nút Đánh dấu đã đọc
    """

    mark_all_read_requested = Signal()
    refresh_logs_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Top Control Row
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title = QLabel("NHẬT KÝ HỆ THỐNG VÀ CẢNH BÁO AN TOÀN")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        top_row.addWidget(title)

        top_row.addStretch()

        self.level_combo = QComboBox()
        self.level_combo.addItems(["ALL", "INFO", "WARNING", "CRITICAL"])
        self.level_combo.currentTextChanged.connect(self._on_filter_changed)
        top_row.addWidget(QLabel("Cấp độ:"))
        top_row.addWidget(self.level_combo)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm kiếm thông báo...")
        self.search_input.setFixedWidth(200)
        self.search_input.textChanged.connect(self._on_filter_changed)
        top_row.addWidget(self.search_input)

        self.mark_read_btn = QPushButton("Đánh dấu đã đọc")
        self.mark_read_btn.clicked.connect(self.mark_all_read_requested.emit)
        top_row.addWidget(self.mark_read_btn)

        self.refresh_btn = QPushButton("Làm mới")
        self.refresh_btn.clicked.connect(self.refresh_logs_requested.emit)
        top_row.addWidget(self.refresh_btn)

        layout.addLayout(top_row)

        # Logs Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Thời gian (UTC)", "Cấp độ", "Nguồn", "Tiêu đề", "Nội dung chi tiết"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.logs_data: List[Dict[str, Any]] = []

    def update_logs_table(self, logs: List[Dict[str, Any]]):
        self.logs_data = logs
        self._on_filter_changed()

    def _on_filter_changed(self):
        lvl = self.level_combo.currentText()
        query = self.search_input.text().strip().lower()

        filtered = []
        for a in self.logs_data:
            if lvl != "ALL" and a.get("level") != lvl:
                continue
            if query and query not in a.get("title", "").lower() and query not in a.get("message", "").lower():
                continue
            filtered.append(a)

        self.table.setRowCount(len(filtered))
        for row, a in enumerate(filtered):
            self.table.setItem(row, 0, QTableWidgetItem(a.get("timestamp", "")[:19]))

            item_lvl = QTableWidgetItem(a.get("level", "INFO"))
            if a.get("level") == "CRITICAL":
                item_lvl.setForeground(Qt.red)
            elif a.get("level") == "WARNING":
                item_lvl.setForeground(Qt.yellow)
            self.table.setItem(row, 1, item_lvl)

            self.table.setItem(row, 2, QTableWidgetItem(a.get("source", "SYSTEM")))
            self.table.setItem(row, 3, QTableWidgetItem(a.get("title", "")))
            self.table.setItem(row, 4, QTableWidgetItem(a.get("message", "")))

