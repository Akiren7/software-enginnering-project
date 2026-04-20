import json
import os


def load_dashboard_data():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "dashboard_data.json")

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)