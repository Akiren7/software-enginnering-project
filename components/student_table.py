from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtGui import QColor


class StudentTableWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Name",
            "Status",
            "Duration",
            "Active Window",
            "Alerts"
        ])

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setShowGrid(False)

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 16px;
                color: white;
                gridline-color: transparent;
                font-size: 13px;
                alternate-background-color: rgba(255,255,255,0.03);
            }

            QHeaderView::section {
                background-color: rgba(255,255,255,0.08);
                color: white;
                font-weight: 700;
                padding: 10px;
                border: none;
                border-bottom: 1px solid rgba(255,255,255,0.08);
            }

            QTableWidget::item {
                padding: 10px;
                border: none;
            }

            QTableWidget::item:selected {
                background-color: rgba(99,102,241,0.35);
                color: white;
            }
        """)

        layout.addWidget(self.table)

    def set_students(self, students):
        self.table.setRowCount(len(students))

        for row, student in enumerate(students):
            name_item = QTableWidgetItem(student["name"])
            status_item = QTableWidgetItem(student["status"])
            duration_item = QTableWidgetItem(str(student["duration"]))
            window_item = QTableWidgetItem(student["window"])
            alerts_item = QTableWidgetItem(str(student["alerts"]))

            status = student["status"].lower()

            if status == "active":
                status_item.setBackground(QColor("#14532d"))
            elif status == "idle":
                status_item.setBackground(QColor("#713f12"))
            elif status == "disconnected":
                status_item.setBackground(QColor("#7f1d1d"))

            for item in [name_item, status_item, duration_item, window_item, alerts_item]:
                item.setForeground(QColor("#ffffff"))

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, status_item)
            self.table.setItem(row, 2, duration_item)
            self.table.setItem(row, 3, window_item)
            self.table.setItem(row, 4, alerts_item)