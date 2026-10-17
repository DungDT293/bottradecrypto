from typing import Optional
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QCheckBox,
)
from PySide6.QtCore import Qt


class ConfirmationDialog(QDialog):
    """
    Explicit safety confirmation dialog.
    Supports:
    - Clear title and warning text.
    - Checkbox confirmation ('Tôi hiểu rõ rủi ro và xác nhận hành động này').
    - Optional keyword verification (e.g. user must type 'DONG TAT CA' or 'LIVE').
    """

    def __init__(
        self,
        title: str,
        message: str,
        confirm_btn_text: str = "Xác nhận",
        is_dangerous: bool = False,
        required_phrase: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(460)
        self.setModal(True)
        self.required_phrase = required_phrase

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Warning / Info Message
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("font-size: 13px; line-height: 1.4;")
        layout.addWidget(msg_label)

        # Optional phrase confirmation input
        self.phrase_input: Optional[QLineEdit] = None
        if required_phrase:
            prompt = QLabel(f"Nhập chính xác cụm từ <b>'{required_phrase}'</b> để tiếp tục:")
            layout.addWidget(prompt)
            self.phrase_input = QLineEdit()
            self.phrase_input.setPlaceholderText(required_phrase)
            self.phrase_input.textChanged.connect(self._validate_inputs)
            layout.addWidget(self.phrase_input)

        # Checkbox confirmation
        self.check_box = QCheckBox("Tôi hiểu rõ rủi ro và xác nhận hành động này.")
        self.check_box.stateChanged.connect(self._validate_inputs)
        layout.addWidget(self.check_box)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Hủy bỏ")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton(confirm_btn_text)
        if is_dangerous:
            self.confirm_btn.setProperty("class", "danger-btn")
        else:
            self.confirm_btn.setProperty("class", "primary-btn")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.confirm_btn)

        layout.addLayout(btn_row)

    def _validate_inputs(self):
        is_checked = self.check_box.isChecked()
        phrase_ok = True
        if self.required_phrase and self.phrase_input:
            phrase_ok = (self.phrase_input.text().strip() == self.required_phrase)
        self.confirm_btn.setEnabled(is_checked and phrase_ok)

    @classmethod
    def confirm(
        cls,
        title: str,
        message: str,
        confirm_btn_text: str = "Xác nhận",
        is_dangerous: bool = False,
        required_phrase: Optional[str] = None,
        parent=None,
    ) -> bool:
        dlg = cls(
            title=title,
            message=message,
            confirm_btn_text=confirm_btn_text,
            is_dangerous=is_dangerous,
            required_phrase=required_phrase,
            parent=parent,
        )
        return dlg.exec() == QDialog.Accepted

