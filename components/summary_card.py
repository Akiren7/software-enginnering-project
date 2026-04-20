from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt


class SummaryCard(QWidget):
    def __init__(self, title, value):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 20px;
            }
        """)

        title_label = QLabel(title)
        value_label = QLabel(str(value))

        title_label.setAlignment(Qt.AlignCenter)
        value_label.setAlignment(Qt.AlignCenter)

        title_label.setStyleSheet("""
            font-size: 12px;
            font-weight: 600;
            color: rgba(255,255,255,0.76);
            background: transparent;
            border: none;
        """)

        value_label.setStyleSheet("""
            font-size: 26px;
            font-weight: 800;
            color: #ffffff;
            background: transparent;
            border: none;
        """)

        layout.addWidget(title_label)
        layout.addWidget(value_label)