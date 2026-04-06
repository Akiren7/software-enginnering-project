"""
payload_builder.py
==================
Take raw activity data from ActivityMonitor,
apply violation rules, and produce a structured
JSON-ready dict that the network layer can send.

  - Which apps are banned
  - What counts as "focus lost"
  - What counts as "idle"
  - How flags are assigned

"""

import socket # we use this to identify the desktop name (socket.gethostname())
import time

from activity_monitor import ActivityMonitor

# ── Violation rules 

EXAM_APP_KEYWORD = "python"      # the main platform that the exam will be held, can be changed

BANNED_APPS = [
    # Browsers
    "chrome", "firefox", "chromium", "opera", "brave", "edge",
    # Code editors / IDEs
    "code", "vscode", "sublime_text", "pycharm", "intellij",
    "notepad++", "atom", "vim", "nano",
    # Messaging
    "telegram", "discord", "whatsapp", "slack", "teams",
    # Shells / terminals
    #"cmd", "powershell", "bash", "terminal", "konsole", "gnome-terminal",
]

IDLE_ALERT_THRESHOLD  = 80    # 80 seconds of inactivity - Warns the student by popping up a warning.
IDLE_DANGER_THRESHOLD = 150   # 150 seconds of inactivity - Might be a cheating attempt.


class PayloadBuilder:
    """
    Builds a structured monitoring payload every heartbeat cycle.

    Workflow
    --------
    1. Call ActivityMonitor.snapshot() to get raw OS data
    2. Analyze the data against violation rules
    3. Return a dict with fields + flags list

    Usage
    -----
        builder = PayloadBuilder(student_id="std_04", student_name="David L.")
        payload = builder.build()
        # → hand payload to network.send_heartbeat(payload)
    """

    def __init__(self, student_id: str, student_name: str):
        self.student_id   = student_id
        self.student_name = student_name
        self.hostname     = socket.gethostname()
        self._monitor     = ActivityMonitor()

    # Core method

    def build(self) -> dict:
        """
        Returned structure

        {
            "student_id":    str,
            "student_name":  str,
            "hostname":      str,
            "timestamp":     float,          ← unix time
            "active_window": str,
            "open_apps":     list[str],      ← filtered, normalized
            "exam_running":  bool,
            "idle_seconds":  float,
            "flags":         list[str],      ← Vialations
        }

        Flag values
        -----------
        "EXAM_CLOSED"      exam process not found in running processes
        "FOCUS_LOST"       focused window is not the exam application
        "BANNED:<name>"    a banned application is running
        "IDLE_WARN"        idle >= IDLE_ALERT_THRESHOLD
        "IDLE_CRITICAL"    idle >= IDLE_DANGER_THRESHOLD
        """
        snap = self._monitor.snapshot() # get the raw info from ActivityMonitor

        exam_running  = self._is_exam_running(snap["open_processes"])
        open_apps     = self._filter_notable_apps(snap["open_processes"])
        flags         = self._detect_violations(
            active_window = snap["active_window"],
            open_processes = snap["open_processes"],
            exam_running  = exam_running,
            idle_seconds  = snap["idle_seconds"],
        )

        return {
            "student_id":    self.student_id,
            "student_name":  self.student_name,
            "hostname":      self.hostname,
            "timestamp":     snap["captured_at"],
            "active_window": snap["active_window"],
            "open_apps":     open_apps,
            "exam_running":  exam_running,
            "idle_seconds":  snap["idle_seconds"],
            "flags":         flags,
        }

    # Violation detection logic 

    def _detect_violations(
        self,
        active_window: str,
        open_processes: list,
        exam_running: bool,
        idle_seconds: float,
    ) -> list:
        """
        Applies all violation rules and returns a list of flag strings.

        Rules are checked independently — multiple flags can fire at once.
        """
        flags = []

        # Rule 1 — Exam application closed
        if not exam_running:
            flags.append("EXAM_CLOSED")

        # Rule 2 — Student switched focus away from the exam
        # Only flag if exam IS running (otherwise EXAM_CLOSED already covers it)
        if exam_running and not self._window_is_exam(active_window):
            flags.append("FOCUS_LOST")

        # Rule 3 — Banned application is running
        for proc in open_processes:
            for banned in BANNED_APPS:
                if banned in proc:
                    flags.append(f"BANNED:{proc}")
                    break   # one flag per process is enough

        # Rule 4 — Student appears to have left their seat
        if idle_seconds >= IDLE_DANGER_THRESHOLD:
            flags.append("IDLE_CRITICAL")
        elif idle_seconds >= IDLE_ALERT_THRESHOLD:
            flags.append("IDLE_WARN")

        return flags

    # Helper methods 

    def _is_exam_running(self, processes: list) -> bool:
        """Returns True if the exam application process is in the process list."""
        return any(EXAM_APP_KEYWORD in p for p in processes)

    def _window_is_exam(self, title: str) -> bool:
        """Returns True if the active window title belongs to the exam app."""
        return EXAM_APP_KEYWORD in title.lower()

    def _filter_notable_apps(self, processes: list) -> list:
        """
        Removes low-level system processes that have no exam relevance.
        """
        # Keep: banned apps + exam app + a few known user-space apps
        # Remove: pure system/kernel processes with no GUI relevance
        skip_prefixes = [
            "kworker", "kthread", "migration", "rcu_", "ksoftirq",
            "watchdog", "cpuhp", "netns", "khugepaged",
            "svchost",  
        ]

        notable = []
        for proc in processes:
            if any(proc.startswith(s) for s in skip_prefixes):
                continue
            notable.append(proc)

        return notable[:15]


# ── Quick manual test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    builder = PayloadBuilder(student_id="std_TEST", student_name="Test Student")
    payload = builder.build()

    print(json.dumps(payload, indent=2))
    print(f"\nFlags detected: {payload['flags'] or ['none']}")