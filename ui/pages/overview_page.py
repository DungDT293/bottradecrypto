from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFrame,
    QScrollArea,
    QGroupBox,
)
from PySide6.QtCore import Qt

from ui.components.cards import MetricCard


class OverviewPage(QWidget):
    """
    Trang Tổng quan:
    - 4 nhóm cards: Tài khoản, Hiệu quả, Hoạt động, Telegram
    - Bảng Vị thế đang mở
    - Feed Hoạt động & Cảnh báo gần nhất
    - Nguyên tắc: Nếu chưa kết nối sàn, hiển thị 'Chưa có dữ liệu', không hiển thị 0.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. Nhóm Cards: TÀI KHOẢN (Binance USD-M Futures)
        # -------------------------------------------------------------
        acc_box = QGroupBox("TÀI KHOẢN KÝ QUỸ (BINANCE USD-M FUTURES)")
        acc_layout = QHBoxLayout(acc_box)
        acc_layout.setSpacing(12)

        self.card_wallet = MetricCard("Số dư Ví (Wallet)", "Chưa có dữ liệu", "USDT")
        self.card_equity = MetricCard("Ký quỹ ròng (Equity)", "Chưa có dữ liệu", "USDT")
        self.card_available = MetricCard("Khả dụng (Available)", "Chưa có dữ liệu", "USDT")
        self.card_upnl = MetricCard("PNL chưa chốt (uPNL)", "Chưa có dữ liệu", "USDT")

        acc_layout.addWidget(self.card_wallet)
        acc_layout.addWidget(self.card_equity)
        acc_layout.addWidget(self.card_available)
        acc_layout.addWidget(self.card_upnl)
        layout.addWidget(acc_box)

        # -------------------------------------------------------------
        # 2. Nhóm Cards: HIỆU QUẢ GIAO DỊCH
        # -------------------------------------------------------------
        perf_box = QGroupBox("HIỆU QUẢ GIAO DỊCH (ASIA/HO_CHI_MINH 00:00)")
        perf_layout = QHBoxLayout(perf_box)
        perf_layout.setSpacing(12)

        self.card_pnl_today = MetricCard("Net PNL Hôm nay", "$0.00", "00:00 đến nay")
        self.card_pnl_7d = MetricCard("Net PNL 7 ngày", "$0.00", "7 ngày gần nhất")
        self.card_closed_trades = MetricCard("Số kèo đã đóng", "0", "Hôm nay")
        self.card_winrate = MetricCard("Win Rate (Tỷ lệ thắng)", "0.0%", "Kèo đã chốt")

        perf_layout.addWidget(self.card_pnl_today)
        perf_layout.addWidget(self.card_pnl_7d)
        perf_layout.addWidget(self.card_closed_trades)
        perf_layout.addWidget(self.card_winrate)
        layout.addWidget(perf_box)

        # -------------------------------------------------------------
        # 3. Nhóm Cards: HOẠT ĐỘNG & TELEGRAM TELEMETRY
        # -------------------------------------------------------------
        ops_box = QGroupBox("TRẠNG THÁI HOẠT ĐỘNG VÀ THU THẬP TELEGRAM")
        ops_layout = QHBoxLayout(ops_box)
        ops_layout.setSpacing(12)

        self.card_active_signals = MetricCard("Tín hiệu đang mở", "0", "Kèo active")
        self.card_open_pos = MetricCard("Vị thế mở", "0", "Positions")
        self.card_msgs_total = MetricCard("Tổng tin Telegram", "0", "Đã lưu trữ")
        self.card_edits = MetricCard("Sự kiện sửa tin", "0", "Edit events")

        ops_layout.addWidget(self.card_active_signals)
        ops_layout.addWidget(self.card_open_pos)
        ops_layout.addWidget(self.card_msgs_total)
        ops_layout.addWidget(self.card_edits)
        layout.addWidget(ops_box)

        # -------------------------------------------------------------
        # 4. Bảng: VỊ THẾ ĐANG MỞ
        # -------------------------------------------------------------
        pos_header = QLabel("VỊ THẾ ĐANG HOẠT ĐỘNG")
        pos_header.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc; margin-top: 6px;")
        layout.addWidget(pos_header)

        self.pos_table = QTableWidget(0, 7)
        self.pos_table.setHorizontalHeaderLabels([
            "Symbol", "Hướng", "Khối lượng", "Giá vào", "Stop Loss", "uPNL (USDT)", "Bảo vệ (Protection)"
        ])
        self.pos_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pos_table.setFixedHeight(140)
        layout.addWidget(self.pos_table)

        # -------------------------------------------------------------
        # 5. Bảng: CẢNH BÁO VÀ FEED HOẠT ĐỘNG GẦN NHẤT
        # -------------------------------------------------------------
        feed_header = QLabel("CẢNH BÁO VÀ HOẠT ĐỘNG GẦN NHẤT")
        feed_header.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc; margin-top: 6px;")
        layout.addWidget(feed_header)

        self.feed_table = QTableWidget(0, 4)
        self.feed_table.setHorizontalHeaderLabels([
            "Thời gian (UTC)", "Cấp độ", "Nguồn / Sự kiện", "Chi tiết"
        ])
        self.feed_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.feed_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.feed_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.feed_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.feed_table.setFixedHeight(180)
        layout.addWidget(self.feed_table)

        scroll.setWidget(container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def update_account_metrics(self, snapshot):
        if snapshot.is_connected and snapshot.wallet_balance is not None:
            self.card_wallet.set_value(f"{snapshot.wallet_balance:,.2f} USDT")
            self.card_equity.set_value(f"{snapshot.equity:,.2f} USDT")
            self.card_available.set_value(f"{snapshot.available_balance:,.2f} USDT")
            upnl_str = f"{snapshot.unrealized_pnl:+,.2f} USDT"
            upnl_color = "#10b981" if snapshot.unrealized_pnl >= 0 else "#ef4444"
            self.card_upnl.set_value(upnl_str, color=upnl_color)
        else:
            self.card_wallet.set_value("Chưa có dữ liệu")
            self.card_equity.set_value("Chưa có dữ liệu")
            self.card_available.set_value("Chưa có dữ liệu")
            self.card_upnl.set_value("Chưa có dữ liệu")

    def update_performance_metrics(self, pnl_today, pnl_7d):
        pnl_today_val = pnl_today.get("net_realized_pnl", 0.0)
        color_today = "#10b981" if pnl_today_val >= 0 else "#ef4444"
        self.card_pnl_today.set_value(f"${pnl_today_val:+,.2f}", color=color_today)

        pnl_7d_val = pnl_7d.get("net_realized_pnl", 0.0)
        color_7d = "#10b981" if pnl_7d_val >= 0 else "#ef4444"
        self.card_pnl_7d.set_value(f"${pnl_7d_val:+,.2f}", color=color_7d)

        self.card_closed_trades.set_value(str(pnl_today.get("total_closed_trades", 0)))
        winrate = pnl_today.get("win_rate_pct", 0.0)
        self.card_winrate.set_value(f"{winrate:.1f}%")

    def update_telemetry(self, telemetry: Dict[str, Any]):
        self.card_msgs_total.set_value(f"{telemetry.get('total_messages', 0):,}")
        self.card_edits.set_value(f"{telemetry.get('edit_events', 0):,}")
        self.card_active_signals.set_value(str(telemetry.get("active_signals", 0)))

    def update_positions(self, positions: List[Dict[str, Any]]):
        self.pos_table.setRowCount(len(positions))
        self.card_open_pos.set_value(str(len(positions)))

        for row, pos in enumerate(positions):
            self.pos_table.setItem(row, 0, QTableWidgetItem(str(pos.get("symbol", ""))))
            self.pos_table.setItem(row, 1, QTableWidgetItem(str(pos.get("side", ""))))
            self.pos_table.setItem(row, 2, QTableWidgetItem(str(pos.get("quantity", ""))))
            self.pos_table.setItem(row, 3, QTableWidgetItem(str(pos.get("entry_price", ""))))
            self.pos_table.setItem(row, 4, QTableWidgetItem(str(pos.get("sl_price", "N/A"))))
            
            upnl = pos.get("unrealized_pnl", "0.0")
            item_upnl = QTableWidgetItem(str(upnl))
            self.pos_table.setItem(row, 5, item_upnl)

            prot = pos.get("protection_status", "UNKNOWN")
            item_prot = QTableWidgetItem(prot)
            if prot == "CONFIRMED":
                item_prot.setForeground(Qt.green)
            else:
                item_prot.setForeground(Qt.yellow)
            self.pos_table.setItem(row, 6, item_prot)

    def update_alerts_feed(self, alerts: List[Dict[str, Any]]):
        self.feed_table.setRowCount(len(alerts))
        for row, a in enumerate(alerts):
            self.feed_table.setItem(row, 0, QTableWidgetItem(a.get("timestamp", "")[:19]))
            lvl_item = QTableWidgetItem(a.get("level", "INFO"))
            if a.get("level") == "CRITICAL":
                lvl_item.setForeground(Qt.red)
            elif a.get("level") == "WARNING":
                lvl_item.setForeground(Qt.yellow)
            self.feed_table.setItem(row, 1, lvl_item)
            self.feed_table.setItem(row, 2, QTableWidgetItem(f"{a.get('source', '')} - {a.get('title', '')}"))
            self.feed_table.setItem(row, 3, QTableWidgetItem(a.get("message", "")))

