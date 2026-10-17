from typing import Optional
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout
from PySide6.QtCore import Qt


class MetricCard(QFrame):
    """
    Standard reusable UI card for key metrics and statistics.
    """

    def __init__(
        self,
        title: str,
        value: str = "--",
        subtitle: str = "",
        tooltip: str = "",
        color: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("class", "metric-card")
        if tooltip:
            self.setToolTip(tooltip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setProperty("class", "card-title")

        self.value_label = QLabel(value)
        self.value_label.setProperty("class", "card-value")
        if color:
            self.value_label.setStyleSheet(f"color: {color};")

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("class", "card-subtitle")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.subtitle_label)

    def set_value(self, value: str, color: Optional[str] = None):
        self.value_label.setText(value)
        if color:
            self.value_label.setStyleSheet(f"color: {color};")

    def set_subtitle(self, subtitle: str):
        self.subtitle_label.setText(subtitle)

