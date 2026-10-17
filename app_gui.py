"""
Desktop Application Entrypoint for telegram_binance_signal_executor.
Built with PySide6.
"""
import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from config.config import load_config
from ui.main_window import MainWindow
from ui.theme import DARK_STYLESHEET


def main():
    # Set high DPI policy
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Telegram Binance Signal Executor")
    app.setOrganizationName("TradingAutomation")

    # Apply global Dark Theme
    app.setStyleSheet(DARK_STYLESHEET)

    # Load configuration
    config = load_config()

    # Launch MainWindow
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

