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
    QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal


class HistoryPage(QWidget):
    """
    Trang Lịch sử giao dịch:
    - Bảng các tín hiệu và vị thế đã đóng
    - Thống kê chi tiết Entry/Exit average, phí và Net PnL
    - Chức năng xuất dữ liệu ra file JSON
    """

    export_history_requested = Signal(str) # file_path
    refresh_history_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Top Control Row
        top_row = QHBoxLayout()
        title = QLabel("LỊCH SỬ TÍN HIỆU VÀ GIAO DỊCH ĐÃ ĐÓNG")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        top_row.addWidget(title)
        top_row.addStretch()

        self.export_btn = QPushButton("Xuất lịch sử JSON")
        self.export_btn.setProperty("class", "primary-btn")
        self.export_btn.clicked.connect(self._on_export_clicked)
        top_row.addWidget(self.export_btn)

        self.refresh_btn = QPushButton("Làm mới")
        self.refresh_btn.clicked.connect(self.refresh_history_requested.emit)
        top_row.addWidget(self.refresh_btn)

        layout.addLayout(top_row)

        # History Table
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Signal ID", "Thời gian mở", "Thời gian đóng", "Symbol", "Hướng", "Trạng thái kết thúc", "Lý do / Kết quả", "Chi tiết"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

    def update_history_table(self, history: List[Dict[str, Any]]):
        self.table.setRowCount(len(history))
        for row, h in enumerate(history):
            self.table.setItem(row, 0, QTableWidgetItem(str(h.get("signal_id", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(str(h.get("created_at", "")[:19])))
            self.table.setItem(row, 2, QTableWidgetItem(str(h.get("updated_at", "")[:19])))
            self.table.setItem(row, 3, QTableWidgetItem(str(h.get("symbol", ""))))
            
            side = h.get("side", "")
            item_side = QTableWidgetItem(side)
            if side == "LONG":
                item_side.setForeground(Qt.green)
            elif side == "SHORT":
                item_side.setForeground(Qt.red)
            self.table.setItem(row, 4, item_side)

            state = h.get("state", "")
            self.table.setItem(row, 5, QTableWidgetItem(state))
            self.table.setItem(row, 6, QTableWidgetItem(str(h.get("blocking_reason", "Hoàn tất"))))
            self.table.setItem(row, 7, QTableWidgetItem(f"SL: {h.get('stop_loss', 'N/A')}"))

    def _on_export_clicked(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Xuất lịch sử giao dịch ra JSON",
            f"history_export_{int(self.rect().width())}.json",
            "JSON Files (*.json)",
        )
        if file_path:
            self.export_history_requested.emit(file_path)

