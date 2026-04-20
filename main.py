import sys
import random
import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
)

from components.alerts_panel import AlertsPanel
from components.student_table import StudentTableWidget
from components.summary_card import SummaryCard
from components.control_panel import ControlPanel
from components.timeline import Timeline
from components.report_screen import ReportScreen
from data.backend_loader import load_dashboard_data


class CleanNightUI(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Instructor Dashboard")
        self.resize(1200, 750)

        # ⭐ daha az ama kaliteli yıldız
        self.stars = [
            {
                "x": random.randint(0, 1200),
                "y": random.randint(0, 750),
                "size": random.uniform(1, 2.2),
                "phase": random.uniform(0, math.pi * 2)
            }
            for _ in range(25)
        ]

        # 🌠 kayan yıldızlar
        self.shooting_stars = []

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_scene)
        self.timer.start(30)

        # 🎨 UI styling (premium)
        self.setStyleSheet("""
            QWidget {
                background: transparent;
                font-family: Segoe UI;
                color: #f8fafc;
            }

            QFrame#Card {
                background-color: rgba(255,255,255,0.05);
                border-radius: 18px;
                padding: 12px;
                border: 1px solid rgba(255,255,255,0.08);
            }

            QLabel {
                color: #e5e7eb;
            }

            QPushButton {
                background-color: rgba(255,255,255,0.08);
                border-radius: 10px;
                padding: 8px;
                color: white;
            }

            QPushButton:hover {
                background-color: rgba(255,255,255,0.15);
            }
        """)

        self.build_ui()

    # 🌠 spawn
    def spawn_shooting_star(self):
        self.shooting_stars.append({
            "x": random.randint(200, 1200),
            "y": random.randint(0, 200),
            "dx": random.uniform(-8, -5),
            "dy": random.uniform(3, 5),
            "length": random.randint(70, 120),
            "life": 0
        })

    def update_scene(self):
        for star in self.stars:
            star["phase"] += 0.03

        if random.random() < 0.05:
            self.spawn_shooting_star()

        new_list = []
        for s in self.shooting_stars:
            s["x"] += s["dx"]
            s["y"] += s["dy"]
            s["life"] += 1
            if s["life"] < 30:
                new_list.append(s)

        self.shooting_stars = new_list

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)

        # 🌌 temiz gece
        painter.fillRect(self.rect(), QColor("#020617"))

        # ⭐ yıldızlar (soft glow)
        for star in self.stars:
            glow = (math.sin(star["phase"]) + 1) / 2
            alpha = int(100 + glow * 120)

            # glow layer
            painter.setBrush(QColor(255, 255, 255, int(alpha * 0.15)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(
                int(star["x"] - 2),
                int(star["y"] - 2),
                6,
                6
            )

            # core
            painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawEllipse(
                int(star["x"]),
                int(star["y"]),
                int(star["size"]),
                int(star["size"])
            )

        # 🌠 kayan yıldız
        for s in self.shooting_stars:
            x = s["x"]
            y = s["y"]
            length = s["length"]

            for i in range(length):
                alpha = int(255 * (1 - i / length))
                painter.setPen(QColor(255, 255, 255, alpha))
                painter.drawPoint(int(x + i), int(y - i * 0.5))

        super().paintEvent(event)

    def build_ui(self):
        data = load_dashboard_data()
        students = data["students"]
        alerts = data["alerts"]
        summary = data["summary"]

        layout = QVBoxLayout(self)

        title = QLabel("Instructor Monitoring Dashboard")
        title.setStyleSheet("font-size:24px; font-weight:bold; color:white;")
        layout.addWidget(title)

        # summary
        row = QHBoxLayout()
        row.addWidget(SummaryCard("Total", summary["total_students"]))
        row.addWidget(SummaryCard("Active", summary["active_students"]))
        row.addWidget(SummaryCard("Alerts", summary["alerts"]))
        row.addWidget(SummaryCard("Time", summary["remaining_time"]))
        layout.addLayout(row)

        middle = QHBoxLayout()

        # LEFT
        left = QFrame()
        left.setObjectName("Card")
        left_layout = QVBoxLayout(left)

        table = StudentTableWidget()
        table.set_students(students)

        left_layout.addWidget(QLabel("Students"))
        left_layout.addWidget(table)

        # RIGHT
        right = QFrame()
        right.setObjectName("Card")
        right_layout = QVBoxLayout(right)

        alerts_panel = AlertsPanel()
        for a in alerts:
            alerts_panel.add_alert(a["message"], a["severity"], a["time"])

        control = ControlPanel()

        timeline = Timeline()
        for a in alerts:
            timeline.add_event(a["time"], a["message"])

        right_layout.addWidget(alerts_panel)
        right_layout.addWidget(control)
        right_layout.addWidget(timeline)

        middle.addWidget(left, 3)
        middle.addWidget(right, 2)

        layout.addLayout(middle)

        self.report = ReportScreen(students)
        self.report.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CleanNightUI()
    window.show()
    sys.exit(app.exec())