import asyncio
import json
import os
import platform
from collections.abc import Callable

from common import protocol

from .macos import get_processes_for_macos
from .psutil_collector import get_processes_via_psutil


FULL_SNAPSHOT_INTERVAL_SECONDS = 120
DIFF_INTERVAL_SECONDS = 15


class ProcessMonitor:
    def __init__(
        self,
        output_dir: str,
        *,
        catch_callback: Callable[[list[dict], str], None] | None = None,
    ):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, "processes.jsonl")
        self.previous_procs = set()
        self.active = False
        self._task = None
        self.current_remaining_time = 0
        self.catch_callback = catch_callback
        self.blacklist_entries: list[str] = []
        self.blacklist_names: set[str] = set()
        self.blacklist_version = "0"
        self.reported_matches: set[tuple[int, str]] = set()

    def start(self):
        """Start the background process monitoring."""
        if self._task is not None:
            return

        self.active = True
        self.previous_procs = self._get_current_processes()
        self._task = asyncio.create_task(self._loop())
        print(f"[PROCESS] Monitor started. Logging to {self.log_file}")

    def stop(self):
        """Stop tracking."""
        self.active = False
        if not self._task:
            return

        self._task.cancel()
        self._task = None
        print("[PROCESS] Monitor stopped.")

    def update_time(self, remaining_seconds: int):
        """Hook called by the client when it receives a SYNC_TIME."""
        self.current_remaining_time = remaining_seconds

    def set_blacklist(self, entries: list[str], version: str = "0"):
        self.blacklist_entries = list(entries)
        self.blacklist_names = {entry.strip().lower() for entry in entries if entry.strip()}
        self.blacklist_version = str(version or "0")
        self.reported_matches.clear()
        print(
            f"[PROCESS] Applied blacklist version {self.blacklist_version} "
            f"with {len(self.blacklist_entries)} entrie(s)."
        )

    def trigger_full_report(self):
        """Immediately generate and save a full list of processes."""
        self.export_requested_report()

    def export_requested_report(self) -> str | None:
        current_procs = self._get_current_processes()
        payload = self._build_full_list_payload("requested", current_procs)
        self._write_log(payload)

        report_path = self._requested_report_path()
        if not self._write_report_file(report_path, payload):
            return None

        print(f"[PROCESS] Wrote requested full process report to {report_path}")
        self.previous_procs = current_procs
        return report_path

    def _get_current_processes(self) -> set[tuple[int, str]]:
        if platform.system() == "Darwin":
            return get_processes_for_macos()
        return get_processes_via_psutil()

    def _build_base_payload(self, entry_type: str) -> dict:
        return {
            "timestamp": protocol.now_iso(),
            "remaining_time": self.current_remaining_time,
            "type": entry_type,
            "platform": platform.system().lower(),
        }

    def _build_full_list_payload(
        self,
        entry_type: str,
        processes: set[tuple[int, str]],
    ) -> dict:
        payload = self._build_base_payload(entry_type)
        payload["processes"] = [list(proc) for proc in sorted(processes)]
        return payload

    def _build_diff_payload(
        self,
        added: set[tuple[int, str]],
        removed: set[tuple[int, str]],
    ) -> dict:
        payload = self._build_base_payload("diff")
        payload["added"] = [list(proc) for proc in sorted(added)]
        payload["removed"] = [list(proc) for proc in sorted(removed)]
        return payload

    def _write_log(self, payload: dict):
        try:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            print(f"[PROCESS] Failed to write log: {e}")

    def _write_report_file(self, report_path: str, payload: dict) -> bool:
        try:
            with open(report_path, "w") as report_file:
                json.dump(payload, report_file, indent=2)
            return True
        except Exception as e:
            print(f"[PROCESS] Failed to write requested report: {e}")
            return False

    def _requested_report_path(self) -> str:
        timestamp = protocol.now_iso().replace(":", "-")
        return os.path.join(self.output_dir, f"process_report_requested_{timestamp}.json")

    def _detect_blacklist_matches(self, processes: set[tuple[int, str]]) -> list[dict]:
        if not self.blacklist_names:
            self.reported_matches.clear()
            return []

        current_matches = set()
        for pid, name in processes:
            normalized_name = _normalize_process_name(name)
            if normalized_name not in self.blacklist_names:
                continue
            current_matches.add((pid, name))

        new_matches = current_matches - self.reported_matches
        self.reported_matches = current_matches
        return [
            {
                "pid": pid,
                "name": name,
            }
            for pid, name in sorted(new_matches, key=lambda item: (item[1].lower(), item[0]))
        ]

    def _report_blacklist_matches(self, matches: list[dict]):
        if not matches:
            return
        print(f"[PROCESS] Blacklist catch detected: {', '.join(match['name'] for match in matches)}")
        if self.catch_callback:
            self.catch_callback(matches, self.blacklist_version)

    async def _loop(self):
        ticks_per_full_snapshot = FULL_SNAPSHOT_INTERVAL_SECONDS // DIFF_INTERVAL_SECONDS
        tick_count = 0

        try:
            while self.active:
                await asyncio.sleep(DIFF_INTERVAL_SECONDS)
                tick_count += 1
                current_procs = self._get_current_processes()
                self._report_blacklist_matches(self._detect_blacklist_matches(current_procs))

                if tick_count >= ticks_per_full_snapshot:
                    self._write_log(
                        self._build_full_list_payload("full_list", current_procs)
                    )
                    tick_count = 0
                else:
                    added = current_procs - self.previous_procs
                    removed = self.previous_procs - current_procs
                    if added or removed:
                        self._write_log(self._build_diff_payload(added, removed))

                self.previous_procs = current_procs
        except asyncio.CancelledError:
            pass


def _normalize_process_name(name: str) -> str:
    base_name = os.path.basename(str(name or "").strip())
    return base_name.lower()
