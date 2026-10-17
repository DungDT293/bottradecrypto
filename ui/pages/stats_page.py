from typing import Any, Dict
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)
from PySide6.QtCore import Qt, Signal

from ui.components.cards import MetricCard


class StatsPage(QWidget):
    """
    Trang Thống kê hiệu suất:
    - Timezone: Asia/Ho_Chi_Minh (Mốc 00:00 đầu ngày)
    - Bộ lọc Hôm nay / 7 ngày / 30 ngày
    - Hiển thị Net Realized PNL, Phí giao dịch, Số kèo thắng/thua, Win rate
    """

    timeframe_changed = Signal(int) # days_back (0, 6, 29)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Top Control Row
        top_row = QHBoxLayout()
        title = QLabel("THỐNG KÊ HIỆU SUẤT VÀ TỶ LỆ THẮNG")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        top_row.addWidget(title)
        top_row.addStretch()

        self.timeframe_combo = QComboBox()
        self.timeframe_combo.addItem("Hôm nay (từ 00:00)", 0)
        self.timeframe_combo.addItem("7 ngày gần nhất", 6)
        self.timeframe_combo.addItem("30 ngày gần nhất", 29)
        self.timeframe_combo.currentIndexChanged.connect(self._on_combo_changed)
        top_row.addWidget(QLabel("Khoảng thời gian (Asia/Ho_Chi_Minh):"))
        top_row.addWidget(self.timeframe_combo)

        layout.addLayout(top_row)

        # Metrics Row
        cards_box = QGroupBox("CHỈ SỐ HIỆU SUẤT TRONG KỲ")
        cards_layout = QHBoxLayout(cards_box)
        cards_layout.setSpacing(12)

        self.card_net_pnl = MetricCard("Lợi nhuận ròng (Net PNL)", "$0.00", "USDT")
        self.card_winrate = MetricCard("Tỷ lệ thắng (Win Rate)", "0.0%", "Thắng / Tổng kèo")
        self.card_total_trades = MetricCard("Kèo đã đóng", "0", "Signals")
        self.card_fees = MetricCard("Tổng phí giao dịch", "$0.00", "Taker/Maker")

        cards_layout.addWidget(self.card_net_pnl)
        cards_layout.addWidget(self.card_winrate)
        cards_layout.addWidget(self.card_total_trades)
        cards_layout.addWidget(self.card_fees)
        layout.addWidget(cards_box)

        # Details Table
        details_box = QGroupBox("BẢNG ĐỐI CHIẾU THỐNG KÊ CHI TIẾT")
        details_layout = QVBoxLayout(details_box)

        self.details_table = QTableWidget(5, 2)
        self.details_table.setHorizontalHeaderLabels(["Chỉ số", "Giá trị ghi nhận"])
        self.details_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.details_table.verticalHeader().setVisible(False)
        details_layout.addWidget(self.details_table)

        layout.addWidget(details_box)
        layout.addStretch()

    def update_stats_view(self, summary: Dict[str, Any]):
        net_pnl = summary.get("net_realized_pnl", 0.0)
        color = "#10b981" if net_pnl >= 0 else "#ef4444"
        self.card_net_pnl.set_value(f"${net_pnl:+,.2f}", color=color)

        wr = summary.get("win_rate_pct", 0.0)
        self.card_winrate.set_value(f"{wr:.1f}%")

        self.card_total_trades.set_value(str(summary.get("total_closed_trades", 0)))
        fees = summary.get("fees_paid", 0.0)
        self.card_fees.set_value(f"${fees:,.2f}")

        # Update details table
        rows_data = [
            ("Khoảng thời gian hiệu lực (VN):", f"{summary.get('start_time_vn', '')} - {summary.get('end_time_vn', '')}"),
            ("Lợi nhuận gộp (Gross Realized PNL):", f"${summary.get('gross_realized_pnl', 0.0):+,.2f}"),
            ("Tổng chi phí giao dịch (Fees):", f"${fees:,.2f}"),
            ("Số kèo Thắng / Thua / Hòa:", f"{summary.get('win_count', 0)} / {summary.get('loss_count', 0)} / {summary.get('breakeven_count', 0)}"),
            ("Quy chuẩn ghi nhận:", "Tính theo thời điểm đóng lệnh thực tế; Không tính deposit/withdraw vào PNL"),
        ]

        for i, (k, v) in enumerate(rows_data):
            self.details_table.setItem(i, 0, QTableWidgetItem(k))
            self.details_table.setItem(i, 1, QTableWidgetItem(v))

    def _on_combo_changed(self):
        days_back = self.timeframe_combo.currentData()
        self.timeframe_changed.emit(days_back)

