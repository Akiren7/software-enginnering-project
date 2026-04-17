import asyncio
import json
import os
import platform

from common import protocol

from .macos import enrich_snapshot_for_macos
from .psutil_snapshot import collect_hardware_snapshot
from .windows import enrich_snapshot_for_windows


CHECK_INTERVAL_SECONDS = 10


class HardwareMonitor:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "hardware_changes.jsonl")
        self.active = False
        self._task = None
        self._previous_snapshot = None

    def start(self):
        if self._task is not None:
            return

        self.active = True
        self._ensure_log_file()
        initial_snapshot = self._current_snapshot()
        self._previous_snapshot = initial_snapshot
        self._task = asyncio.create_task(self._loop())
        print(f"[HARDWARE] Monitor started. Logging to {self.log_file}")

    def stop(self):
        self.active = False
        if not self._task:
            return

        self._task.cancel()
        self._task = None
        print("[HARDWARE] Monitor stopped.")

    def export_current_snapshot(self) -> str | None:
        snapshot = self._current_snapshot()
        report_path = self._snapshot_report_path()
        if not self._write_snapshot_report(report_path, snapshot):
            return None

        print(f"[HARDWARE] Wrote current hardware snapshot to {report_path}")
        self._previous_snapshot = snapshot
        return report_path

    def _current_snapshot(self) -> dict:
        snapshot = collect_hardware_snapshot()
        system_name = platform.system()
        if system_name == "Windows":
            return enrich_snapshot_for_windows(snapshot)
        if system_name == "Darwin":
            return enrich_snapshot_for_macos(snapshot)
        return snapshot

    def _full_snapshot_entry(self, snapshot: dict, *, entry_type: str) -> dict:
        return {
            "timestamp": protocol.now_iso(),
            "type": entry_type,
            "snapshot": snapshot,
        }

    def _change_entry(self, previous_snapshot: dict, current_snapshot: dict) -> dict:
        return {
            "timestamp": protocol.now_iso(),
            "type": "hardware_change",
            "changes": _hardware_changes(previous_snapshot, current_snapshot),
        }

    def _write_log(self, payload: dict):
        try:
            with open(self.log_file, "a", encoding="utf-8") as log_handle:
                log_handle.write(json.dumps(payload) + "\n")
        except Exception as exc:
            print(f"[HARDWARE] Failed to write log: {exc}")

    def _ensure_log_file(self):
        try:
            with open(self.log_file, "a", encoding="utf-8"):
                pass
        except Exception as exc:
            print(f"[HARDWARE] Failed to initialize log file: {exc}")

    def _write_snapshot_report(self, report_path: str, snapshot: dict) -> bool:
        payload = self._full_snapshot_entry(snapshot, entry_type="snapshot_report")
        try:
            with open(report_path, "w", encoding="utf-8") as report_file:
                json.dump(payload, report_file, indent=2)
            return True
        except Exception as exc:
            print(f"[HARDWARE] Failed to write snapshot report: {exc}")
            return False

    def _snapshot_report_path(self) -> str:
        timestamp = protocol.now_iso().replace(":", "-")
        return os.path.join(self.output_dir, f"hardware_snapshot_{timestamp}.json")

    async def _loop(self):
        try:
            while self.active:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                current_snapshot = self._current_snapshot()
                if current_snapshot == self._previous_snapshot:
                    continue

                self._write_log(self._change_entry(self._previous_snapshot, current_snapshot))
                self._previous_snapshot = current_snapshot
        except asyncio.CancelledError:
            pass


def _hardware_changes(previous_snapshot: dict, current_snapshot: dict) -> dict:
    return {
        "disks": _collection_changes(
            previous_snapshot.get("disks", []),
            current_snapshot.get("disks", []),
            key_fields=("device", "mountpoint"),
        ),
        "usb_devices": _collection_changes(
            previous_snapshot.get("usb_devices", []),
            current_snapshot.get("usb_devices", []),
            key_fields=("name", "location_id", "serial_number"),
        ),
        "network_interfaces": _collection_changes(
            previous_snapshot.get("network_interfaces", []),
            current_snapshot.get("network_interfaces", []),
            key_fields=("name",),
        ),
        "battery": _value_change(previous_snapshot.get("battery"), current_snapshot.get("battery")),
        "system": _value_change(previous_snapshot.get("system"), current_snapshot.get("system")),
    }


def _collection_changes(previous_items: list[dict], current_items: list[dict], *, key_fields: tuple[str, ...]) -> dict:
    previous_map = {_item_key(item, key_fields): item for item in previous_items}
    current_map = {_item_key(item, key_fields): item for item in current_items}

    added = [current_map[key] for key in sorted(current_map.keys() - previous_map.keys())]
    removed = [previous_map[key] for key in sorted(previous_map.keys() - current_map.keys())]
    changed = []

    for key in sorted(previous_map.keys() & current_map.keys()):
        if previous_map[key] == current_map[key]:
            continue
        changed.append(
            {
                "key": list(key),
                "before": previous_map[key],
                "after": current_map[key],
            }
        )

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _item_key(item: dict, key_fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(item.get(field, "")) for field in key_fields)


def _value_change(previous_value, current_value) -> dict | None:
    if previous_value == current_value:
        return None
    return {
        "before": previous_value,
        "after": current_value,
    }
