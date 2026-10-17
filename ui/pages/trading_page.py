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
    QGroupBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from ui.components.dialogs import ConfirmationDialog


class TradingPage(QWidget):
    """
    Trang Đang giao dịch:
    - Bảng Vị thế đang mở (Positions) với Protection Status (CONFIRMED/MISSING/UNKNOWN)
    - Phân tách rõ vị thế thuộc bot vs vị thế ngoài bot (chỉ quan sát)
    - Bảng Lệnh chờ (Pending Orders)
    - Các nút thao tác an toàn (Hủy pending entry, Đóng vị thế) được bảo vệ bằng ConfirmationDialog
    """

    refresh_trading_requested = Signal()
    cancel_pending_orders_requested = Signal(str) # symbol
    close_position_requested = Signal(str)        # symbol
    close_all_bot_positions_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. BẢNG VỊ THẾ ĐANG MỞ
        # -------------------------------------------------------------
        pos_box = QGroupBox("VỊ THẾ ĐANG MỞ (BOT VÀ QUAN SÁT SÀN)")
        pos_layout = QVBoxLayout(pos_box)

        self.pos_table = QTableWidget(0, 9)
        self.pos_table.setHorizontalHeaderLabels([
            "Symbol", "Hướng", "Khối lượng", "Giá vào", "Đòn bẩy / Margin", "SL Thực tế", "uPNL (USDT)", "Bảo vệ (Protection)", "Nguồn"
        ])
        self.pos_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        pos_layout.addWidget(self.pos_table)

        # Positions action buttons
        pos_btn_row = QHBoxLayout()
        self.close_selected_btn = QPushButton("Đóng vị thế đã chọn")
        self.close_selected_btn.setProperty("class", "danger-btn")
        self.close_selected_btn.setEnabled(False)
        self.close_selected_btn.clicked.connect(self._on_close_selected_pos)
        pos_btn_row.addWidget(self.close_selected_btn)

        self.close_all_btn = QPushButton("Đóng TẤT CẢ vị thế của Bot")
        self.close_all_btn.setProperty("class", "danger-btn")
        self.close_all_btn.setEnabled(False)
        self.close_all_btn.clicked.connect(self._on_close_all_bot_pos)
        pos_btn_row.addWidget(self.close_all_btn)

        pos_btn_row.addStretch()
        pos_layout.addLayout(pos_btn_row)
        layout.addWidget(pos_box)

        # -------------------------------------------------------------
        # 2. BẢNG LỆNH ĐANG CHỜ (PENDING ORDERS)
        # -------------------------------------------------------------
        orders_box = QGroupBox("CÁC LỆNH ĐANG CHỜ KHỚP VÀ LỆNH ĐIỀU KIỆN (PENDING & ALGO ORDERS)")
        orders_layout = QVBoxLayout(orders_box)

        self.orders_table = QTableWidget(0, 8)
        self.orders_table.setHorizontalHeaderLabels([
            "Client Order ID", "Symbol", "Loại lệnh", "Hướng", "Khối lượng", "Giá đặt", "Trigger Price (SL/TP)", "Trạng thái"
        ])
        self.orders_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        orders_layout.addWidget(self.orders_table)

        # Orders action buttons
        orders_btn_row = QHBoxLayout()
        self.cancel_pending_btn = QPushButton("Hủy các Limit Entry đang chờ")
        self.cancel_pending_btn.setProperty("class", "danger-btn")
        self.cancel_pending_btn.setEnabled(False)
        self.cancel_pending_btn.clicked.connect(self._on_cancel_pending_orders)
        orders_btn_row.addWidget(self.cancel_pending_btn)

        self.refresh_btn = QPushButton("Đồng bộ dữ liệu")
        self.refresh_btn.clicked.connect(self.refresh_trading_requested.emit)
        orders_btn_row.addWidget(self.refresh_btn)

        orders_btn_row.addStretch()
        orders_layout.addLayout(orders_btn_row)
        layout.addWidget(orders_box)

        # Selection trigger
        self.pos_table.itemSelectionChanged.connect(self._on_pos_selection_changed)

    def update_positions_table(self, positions: List[Dict[str, Any]], is_live: bool = False):
        self.pos_table.setRowCount(len(positions))
        for row, p in enumerate(positions):
            self.pos_table.setItem(row, 0, QTableWidgetItem(str(p.get("symbol", ""))))
            self.pos_table.setItem(row, 1, QTableWidgetItem(str(p.get("side", ""))))
            self.pos_table.setItem(row, 2, QTableWidgetItem(str(p.get("quantity", ""))))
            self.pos_table.setItem(row, 3, QTableWidgetItem(str(p.get("entry_price", ""))))
            
            lev_margin = f"{p.get('leverage', 1)}x ({p.get('margin_mode', 'ISOLATED')})"
            self.pos_table.setItem(row, 4, QTableWidgetItem(lev_margin))

            self.pos_table.setItem(row, 5, QTableWidgetItem(str(p.get("sl_price", "N/A"))))
            self.pos_table.setItem(row, 6, QTableWidgetItem(str(p.get("unrealized_pnl", "0.0"))))

            prot = p.get("protection_status", "UNKNOWN")
            item_prot = QTableWidgetItem(prot)
            if prot == "CONFIRMED":
                item_prot.setForeground(Qt.green)
            elif prot == "MISSING":
                item_prot.setForeground(Qt.red)
            else:
                item_prot.setForeground(Qt.yellow)
            self.pos_table.setItem(row, 7, item_prot)

            is_bot = "BOT" if p.get("active_signal_id") else "NGOÀI BOT"
            self.pos_table.setItem(row, 8, QTableWidgetItem(is_bot))

        # Enable danger buttons only in Live/Testnet mode if positions exist
        has_pos = len(positions) > 0
        self.close_all_btn.setEnabled(is_live and has_pos)
        self.cancel_pending_btn.setEnabled(is_live)

    def update_orders_table(self, orders: List[Dict[str, Any]]):
        self.orders_table.setRowCount(len(orders))
        for row, o in enumerate(orders):
            self.orders_table.setItem(row, 0, QTableWidgetItem(str(o.get("client_order_id", ""))))
            self.orders_table.setItem(row, 1, QTableWidgetItem(str(o.get("symbol", ""))))
            self.orders_table.setItem(row, 2, QTableWidgetItem(str(o.get("order_type", ""))))
            self.orders_table.setItem(row, 3, QTableWidgetItem(str(o.get("side", ""))))
            self.orders_table.setItem(row, 4, QTableWidgetItem(str(o.get("quantity", ""))))
            self.orders_table.setItem(row, 5, QTableWidgetItem(str(o.get("price", "MARKET"))))
            self.orders_table.setItem(row, 6, QTableWidgetItem(str(o.get("trigger_price", "N/A"))))
            self.orders_table.setItem(row, 7, QTableWidgetItem(str(o.get("status", ""))))

    def _on_pos_selection_changed(self):
        selected = self.pos_table.selectedItems()
        self.close_selected_btn.setEnabled(len(selected) > 0)

    def _on_close_selected_pos(self):
        row = self.pos_table.currentRow()
        if row < 0:
            return
        sym = self.pos_table.item(row, 0).text()
        confirmed = ConfirmationDialog.confirm(
            title=f"XÁC NHẬN ĐÓNG VỊ THẾ {sym}",
            message=f"Bạn có chắc chắn muốn đóng khẩn cấp vị thế <b>{sym}</b> trên sàn?",
            confirm_btn_text="Đóng vị thế",
            is_dangerous=True,
            required_phrase=sym,
            parent=self,
        )
        if confirmed:
            self.close_position_requested.emit(sym)

    def _on_close_all_bot_pos(self):
        confirmed = ConfirmationDialog.confirm(
            title="XÁC NHẬN ĐÓNG TẤT CẢ VỊ THẾ BOT",
            message="<b>CẢNH BÁO NGUY HIỂM:</b> Bạn đang yêu cầu đóng khẩn cấp toàn bộ các vị thế đang mở thuộc bot trên sàn Binance!",
            confirm_btn_text="Đóng tất cả vị thế",
            is_dangerous=True,
            required_phrase="DONG TAT CA",
            parent=self,
        )
        if confirmed:
            self.close_all_bot_positions_requested.emit()

    def _on_cancel_pending_orders(self):
        confirmed = ConfirmationDialog.confirm(
            title="XÁC NHẬN HỦY CÁC LIMIT ENTRY CHỜ KHỚP",
            message="Hành động này sẽ hủy tất cả các lệnh Limit Entry chưa khớp của bot. Các vị thế đang mở và lệnh bảo vệ SL/TP vẫn được giữ nguyên.",
            confirm_btn_text="Hủy lệnh Limit",
            parent=self,
        )
        if confirmed:
            self.cancel_pending_orders_requested.emit("ALL")

