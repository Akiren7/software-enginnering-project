from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class Timeline(QWidget):
    def __init__(self):
        super().__init__()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(8)

        title = QLabel("Activity Timeline")
        title.setStyleSheet("""
            font-size: 15px;
            font-weight: 800;
            color: white;
            background: transparent;
        """)
        self.main_layout.addWidget(title)

    def add_event(self, time, text):
        label = QLabel(f"✦  [{time}]  {text}")
        label.setWordWrap(True)
        label.setStyleSheet("""
            font-size: 12px;
            color: rgba(255,255,255,0.90);
            background-color: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 12px;
            padding: 8px;
        """)
        self.main_layout.addWidget(label)