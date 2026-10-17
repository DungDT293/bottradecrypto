DARK_STYLESHEET = """
QMainWindow, QDialog {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 13px;
}

QWidget {
    background-color: transparent;
    color: #f8fafc;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}

/* Sidebar styling */
QFrame#sidebar {
    background-color: #1e293b;
    border-right: 1px solid #334155;
}

QPushButton.nav-btn {
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
    color: #94a3b8;
    font-size: 13px;
    font-weight: 500;
    margin: 2px 8px;
    background-color: transparent;
}

QPushButton.nav-btn:hover {
    background-color: #334155;
    color: #ffffff;
}

QPushButton.nav-btn:checked {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}

/* Header bar */
QFrame#header {
    background-color: #1e293b;
    border-bottom: 1px solid #334155;
    padding: 8px 16px;
}

/* Metric Cards */
QFrame.metric-card {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 12px;
}

QFrame.metric-card:hover {
    border: 1px solid #475569;
}

QLabel.card-title {
    color: #94a3b8;
    font-size: 11px;
    text-transform: uppercase;
    font-weight: 600;
}

QLabel.card-value {
    color: #f8fafc;
    font-size: 20px;
    font-weight: 700;
}

QLabel.card-subtitle {
    color: #64748b;
    font-size: 11px;
}

/* Standard Buttons */
QPushButton {
    background-color: #334155;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
    font-size: 12px;
}

QPushButton:hover {
    background-color: #475569;
}

QPushButton:pressed {
    background-color: #1e293b;
}

QPushButton:disabled {
    background-color: #1e293b;
    color: #475569;
    border-color: #334155;
}

QPushButton.primary-btn {
    background-color: #2563eb;
    border: 1px solid #3b82f6;
    color: #ffffff;
    font-weight: 600;
}

QPushButton.primary-btn:hover {
    background-color: #1d4ed8;
}

QPushButton.danger-btn {
    background-color: #dc2626;
    border: 1px solid #ef4444;
    color: #ffffff;
}

QPushButton.danger-btn:hover {
    background-color: #b91c1c;
}

QPushButton.success-btn {
    background-color: #059669;
    border: 1px solid #10b981;
    color: #ffffff;
}

QPushButton.success-btn:hover {
    background-color: #047857;
}

/* Tables */
QTableWidget {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    gridline-color: #334155;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    color: #f8fafc;
}

QTableWidget::item {
    padding: 6px;
}

QTableWidget::item:selected {
    background-color: #2563eb;
}

QHeaderView::section {
    background-color: #0f172a;
    color: #94a3b8;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #334155;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
}

/* Input Fields */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f8fafc;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #1e293b;
    border: 1px solid #334155;
    selection-background-color: #2563eb;
    color: #f8fafc;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #0f172a;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #475569;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #64748b;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #0f172a;
    height: 8px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #475569;
    min-width: 20px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: #64748b;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* GroupBox */
QGroupBox {
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 12px;
    font-weight: 600;
    color: #cbd5e1;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}
"""

