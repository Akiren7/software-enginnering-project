from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt


class ControlPanel(QWidget):
    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("Exam Control Center")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 16px;
            font-weight: 800;
            color: white;
            background: transparent;
        """)
        layout.addWidget(title)

        buttons = [
            "▶ Start Exam",
            "⏸ Pause Exam",
            "⏹ Stop Exam",
            "⏱ Add 5 Minutes",
            "📂 Open Submissions",
            "📋 View Activity Log"
        ]

        for text in buttons:
            btn = QPushButton(text)
            layout.addWidget(btn)