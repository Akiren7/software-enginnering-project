from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView


class ReportScreen(QWidget):
    def __init__(self, students):
        super().__init__()

        self.setStyleSheet("""
            QWidget {
                background-color: #0f172a;
                color: white;
                font-family: Segoe UI;
            }

            QTableWidget {
                background-color: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 16px;
                color: white;
                font-size: 13px;
            }

            QHeaderView::section {
                background-color: rgba(255,255,255,0.08);
                color: white;
                padding: 8px;
                font-weight: 700;
                border: none;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Post-Exam Report Screen")
        title.setStyleSheet("font-size: 22px; font-weight: 800;")

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Name", "Duration", "Violations", "Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setRowCount(len(students))

        for row, student in enumerate(students):
            self.table.setItem(row, 0, QTableWidgetItem(student["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(str(student["duration"])))
            self.table.setItem(row, 2, QTableWidgetItem(str(student["alerts"])))
            self.table.setItem(row, 3, QTableWidgetItem(student["status"]))

        layout.addWidget(title)
        layout.addWidget(self.table)