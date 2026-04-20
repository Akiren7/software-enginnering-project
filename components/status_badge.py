from PySide6.QtWidgets import QLabel


class StatusBadge(QLabel):
    def __init__(self, status="unknown", parent=None):
        super().__init__(parent)
        self.setText(status)