"""
monitor_loop.py
===============
YOUR MODULE — Monitoring Loop (WebSocket version)
Integrates with network_sender.py which now uses WebSocket.

No changes to the loop logic — only the sender changed.
"""

import threading
import time

from payload_builder import PayloadBuilder
from network_sender  import NetworkSender

# ── CONFIG ────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 5
STUDENT_ID         = "std_01"
STUDENT_NAME       = "Alice K."
# ──────────────────────────────────────────────────────────────────────────


class MonitorLoop:
    """
    Runs the periodic monitoring cycle in a background thread.
    Calls NetworkSender.send_heartbeat() every HEARTBEAT_INTERVAL seconds.
    The server handles violation detection on its side based on the flags.
    """

    def __init__(self, exam_state, sender: NetworkSender = None):
        self._exam_state = exam_state
        self._sender     = sender or NetworkSender()
        self._builder    = PayloadBuilder(STUDENT_ID, STUDENT_NAME)
        self._running    = False
        self._thread     = None

    def start(self):
        """Register with server then start the monitoring loop."""
        if self._running:
            return

        # ── SERVER TEAMMATE INTEGRATION POINT ────────────────────────────
        # register() connects via WebSocket and sends "request_start_exam"
        # Server must be running before this is called.
        # ─────────────────────────────────────────────────────────────────
        registered = self._sender.register()
        if not registered:
            print("[MONITOR] Warning: Could not register with server. Running in offline mode.")

        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[MONITOR] Monitoring loop started.")

    def stop(self):
        """Stop the loop and close connection."""
        self._running = False
        self._sender.disconnect()
        print("[MONITOR] Monitoring loop stopped.")

    # ── Internal loop ─────────────────────────────────────────────────────

    def _loop(self):
        while self._running:

            # Wait until exam is active
            if not self._exam_state.is_active():
                time.sleep(1)
                continue

            # Build payload from your existing modules
            try:
                payload = self._builder.build()
            except Exception as exc:
                print(f"[MONITOR] Build error: {exc}")
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            # Log locally
            self._log(payload)

            # Send to server — server handles violation_paused state
            self._sender.send_heartbeat(payload)

            time.sleep(HEARTBEAT_INTERVAL)

    def _log(self, payload: dict):
        flags    = payload["flags"]
        flag_str = ", ".join(flags) if flags else "clean"
        print(
            f"[HB] {payload['student_name']} | "
            f"window='{payload['active_window'][:40]}' | "
            f"idle={payload['idle_seconds']:.0f}s | "
            f"flags=[{flag_str}]"
        )


# ── Stubs for testing ─────────────────────────────────────────────────────

class _StubSender:
    """Fake sender — prints instead of sending. Use when server is not ready."""
    def register(self):
        print("[STUB] register() called → returning fake session_token")
        return True
    def send_heartbeat(self, payload):
        import json
        print(f"[STUB] send_heartbeat:\n{json.dumps(payload, indent=2)}\n")
    def disconnect(self):
        print("[STUB] disconnect() called")

class _StubExamState:
    """Fake exam state — exam always active."""
    def is_active(self) -> bool:
        return True


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  MONITOR LOOP — test mode (stubs)")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    # ── Switch to real modules when teammates are ready ───────────────────
    #
    #   from exam_state import ExamState     # exam control teammate
    #   exam_state = ExamState()
    #   loop = MonitorLoop(exam_state=exam_state)  # uses real NetworkSender
    #
    # To test with real server but stub exam state:
    #   loop = MonitorLoop(exam_state=_StubExamState())
    #
    # ─────────────────────────────────────────────────────────────────────

    loop = MonitorLoop(exam_state=_StubExamState(), sender=_StubSender())
    loop.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        loop.stop()
        print("Exited.")
