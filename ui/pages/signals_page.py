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
    QSplitter,
    QTextEdit,
    QComboBox,
    QLineEdit,
    QGroupBox,
)
from PySide6.QtCore import Qt, Signal


class SignalsPage(QWidget):
    """
    Trang Tín hiệu và Timeline chi tiết:
    - Bảng danh sách toàn bộ tín hiệu đã phân tích
    - Bộ lọc trạng thái (ALL, VALIDATED, NEEDS_REVIEW, NEEDS_POLICY, REJECTED)
    - Inspector xem chi tiết tin gốc, các phiên bản đã quan sát, và timeline sự kiện
    """

    refresh_signals_requested = Signal()
    signal_selected = Signal(str) # signal_id

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Top Filter Row
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title = QLabel("TÍN HIỆU VÀ TIMELINE SỰ KIỆN")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        top_row.addWidget(title)

        top_row.addStretch()

        self.state_filter = QComboBox()
        self.state_filter.addItems([
            "ALL", "VALIDATED", "NEEDS_REVIEW", "NEEDS_POLICY",
            "REJECTED", "ENTRY_PENDING", "OPEN_PROTECTED", "CLOSED"
        ])
        self.state_filter.currentTextChanged.connect(self._on_filter_changed)
        top_row.addWidget(QLabel("Trạng thái:"))
        top_row.addWidget(self.state_filter)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm theo Symbol (vd: BTC)...")
        self.search_input.setFixedWidth(180)
        self.search_input.textChanged.connect(self._on_filter_changed)
        top_row.addWidget(self.search_input)

        self.refresh_btn = QPushButton("Làm mới")
        self.refresh_btn.clicked.connect(self.refresh_signals_requested.emit)
        top_row.addWidget(self.refresh_btn)

        layout.addLayout(top_row)

        # Splitter: Table on left, Inspector on right
        splitter = QSplitter(Qt.Horizontal)

        # Left: Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Signal ID", "Thời gian", "Symbol", "Hướng", "SL", "Trạng thái", "Lý do / Cảnh báo"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        # Right: Detail Inspector
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        # 1. Raw Message Box
        msg_box = QGroupBox("Nội dung tin nhắn gốc")
        msg_layout = QVBoxLayout(msg_box)
        self.raw_text_view = QTextEdit()
        self.raw_text_view.setReadOnly(True)
        msg_layout.addWidget(self.raw_text_view)
        right_layout.addWidget(msg_box)

        # 2. Timeline Events Box
        timeline_box = QGroupBox("Timeline sự kiện Admin & Bot")
        tl_layout = QVBoxLayout(timeline_box)
        self.timeline_view = QTextEdit()
        self.timeline_view.setReadOnly(True)
        tl_layout.addWidget(self.timeline_view)
        right_layout.addWidget(timeline_box)

        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])
        layout.addWidget(splitter)

        self.signals_data: List[Dict[str, Any]] = []

    def update_signals_table(self, signals: List[Dict[str, Any]]):
        self.signals_data = signals
        self.table.setRowCount(len(signals))

        for row, s in enumerate(signals):
            self.table.setItem(row, 0, QTableWidgetItem(s.get("signal_id", "")))
            self.table.setItem(row, 1, QTableWidgetItem(s.get("created_at", "")[:19]))
            self.table.setItem(row, 2, QTableWidgetItem(s.get("symbol", "N/A")))
            
            side = s.get("side", "N/A")
            item_side = QTableWidgetItem(side)
            if side == "LONG":
                item_side.setForeground(Qt.green)
            elif side == "SHORT":
                item_side.setForeground(Qt.red)
            self.table.setItem(row, 3, item_side)

            self.table.setItem(row, 4, QTableWidgetItem(str(s.get("stop_loss", "None"))))

            state = s.get("state", "")
            item_state = QTableWidgetItem(state)
            if state == "VALIDATED":
                item_state.setForeground(Qt.green)
            elif state in ["NEEDS_REVIEW", "NEEDS_POLICY"]:
                item_state.setForeground(Qt.yellow)
            elif state == "REJECTED":
                item_state.setForeground(Qt.red)
            self.table.setItem(row, 5, item_state)

            self.table.setItem(row, 6, QTableWidgetItem(s.get("blocking_reason", "OK")))

    def display_signal_detail(self, detail: Dict[str, Any]):
        sig = detail.get("signal", {})
        raw_msg = detail.get("raw_message", {})
        versions = detail.get("versions", [])
        timeline = detail.get("timeline", [])

        # Display raw message & observed versions
        text_lines = [
            f"=== THÔNG TIN TÍN HIỆU: {sig.get('symbol', 'UNKNOWN')} ({sig.get('side', '')}) ===",
            f"Signal ID: {sig.get('signal_id', '')}",
            f"Chat ID: {sig.get('chat_id', '')} | Message ID: {sig.get('message_id', '')}",
            f"Trạng thái: {sig.get('state', '')}",
            f"Entries: {sig.get('entries_json', '[]')} | SL: {sig.get('stop_loss', '')}",
            f"Lý do chặn: {sig.get('blocking_reason', 'None')}",
            "",
            "--- NỘI DUNG NGUYÊN VĂN (RAW TEXT) ---",
            raw_msg.get("raw_text", "(Không có nội dung lưu trữ)"),
            "",
            f"--- CÁC PHIÊN BẢN QUAN SÁT ĐƯỢC (TỔNG: {len(versions)}) ---",
        ]
        for v in versions:
            tag = "CHỈNH SỬA (EDIT)" if v.get("is_edit") else "TIN GỐC (NEW)"
            text_lines.append(f"v{v.get('version')} [{tag}] lúc {v.get('event_date')}:")
            text_lines.append(f"  {v.get('normalized_text', '')}")

        self.raw_text_view.setPlainText("\n".join(text_lines))

        # Display timeline
        tl_lines = []
        if not timeline:
            tl_lines.append("Chưa có sự kiện timeline nào được ghi nhận.")
        else:
            for ev in timeline:
                tl_lines.append(f"[{ev.get('timestamp')[:19]}] {ev.get('event_type')}:")
                tl_lines.append(f"  -> {ev.get('description')}")
                if ev.get("payload_json"):
                    tl_lines.append(f"  Dữ liệu: {ev.get('payload_json')}")
                tl_lines.append("")

        self.timeline_view.setPlainText("\n".join(tl_lines))

    def _on_row_selected(self):
        rows = self.table.selectedItems()
        if rows:
            row_idx = self.table.currentRow()
            sig_id = self.table.item(row_idx, 0).text()
            self.signal_selected.emit(sig_id)

    def _on_filter_changed(self):
        self.refresh_signals_requested.emit()

