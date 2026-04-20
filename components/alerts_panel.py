from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from components.alert_card import AlertCard


class AlertsPanel(QWidget):
    def __init__(self):
        super().__init__()

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)

        title = QLabel("Alarm Cards")
        title.setStyleSheet("""
            font-size: 16px;
            font-weight: 800;
            color: white;
            background: transparent;
        """)
        self.main_layout.addWidget(title)

    def add_alert(self, message, severity, time):
        card = AlertCard(message, severity, time)
        self.main_layout.addWidget(card)