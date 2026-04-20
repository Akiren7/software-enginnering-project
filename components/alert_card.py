from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class AlertCard(QWidget):
    def __init__(self, message, severity, time):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        title = QLabel(f"{severity.upper()}  •  {message}")
        time_label = QLabel(time)

        title.setWordWrap(True)

        title.setStyleSheet("""
            font-size: 13px;
            font-weight: 700;
            color: white;
            background: transparent;
            border: none;
        """)

        time_label.setStyleSheet("""
            font-size: 11px;
            color: rgba(255,255,255,0.72);
            background: transparent;
            border: none;
        """)

        if severity == "critical":
            self.setStyleSheet("""
                background-color: rgba(239,68,68,0.18);
                border: 1px solid rgba(239,68,68,0.40);
                border-left: 5px solid #ef4444;
                border-radius: 14px;
            """)
        elif severity == "warning":
            self.setStyleSheet("""
                background-color: rgba(245,158,11,0.18);
                border: 1px solid rgba(245,158,11,0.40);
                border-left: 5px solid #f59e0b;
                border-radius: 14px;
            """)
        else:
            self.setStyleSheet("""
                background-color: rgba(59,130,246,0.16);
                border: 1px solid rgba(59,130,246,0.34);
                border-left: 5px solid #3b82f6;
                border-radius: 14px;
            """)

        layout.addWidget(title)
        layout.addWidget(time_label)