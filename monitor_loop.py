"""
monitor_loop.py
===============
YOUR MODULE — Monitoring Loop
Updated to work with the reliable delivery version of NetworkSender.

Changes from previous version:
  - send_heartbeat() now returns DeliveryStatus — loop logs the result
  - buffer_size() is checked every cycle and printed if non-zero
  - disconnect() flushes the buffer before closing (handled inside sender)
"""

import threading
import time

from payload_builder import PayloadBuilder
from network_sender  import NetworkSender, DeliveryStatus

# ── CONFIG ────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 5
STUDENT_ID         = "2300005352"
STUDENT_NAME       = "Alice K."
# ──────────────────────────────────────────────────────────────────────────


class MonitorLoop:
    """
    Runs the periodic monitoring cycle in a background thread.
    Calls NetworkSender.send_heartbeat() every HEARTBEAT_INTERVAL seconds
    and logs the DeliveryStatus returned by the sender.
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

        registered = self._sender.register()
        if not registered:
            print("[MONITOR] Warning: Could not register with server. Running in offline mode.")

        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[MONITOR] Monitoring loop started.")

    def stop(self):
        """
        Stop the loop.
        NetworkSender.disconnect() will flush any buffered packets first.
        """
        self._running = False
        self._sender.disconnect()
        print("[MONITOR] Monitoring loop stopped.")

    # ── Internal loop ─────────────────────────────────────────────────────

    def _loop(self):
        while self._running:

            if not self._exam_state.is_active():
                time.sleep(1)
                continue

            try:
                payload = self._builder.build()
            except Exception as exc:
                print(f"[MONITOR] Build error: {exc}")
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            self._log(payload)

            # send_heartbeat now returns a DeliveryStatus
            status = self._sender.send_heartbeat(payload)

            # Log delivery outcome and buffer status
            if status == DeliveryStatus.BUFFERED:
                print(f"[MONITOR] Packet buffered. "
                      f"Queue size: {self._sender.buffer_size()}")
            elif status == DeliveryStatus.DROPPED:
                print(f"[MONITOR] ⚠ Packet DROPPED — buffer full.")

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
    """Fake sender — prints instead of sending."""
    def register(self):
        print("[STUB] register() → OK")
        return True
    def send_heartbeat(self, payload):
        import json
        print(f"[STUB] send_heartbeat:\n{json.dumps(payload, indent=2)}\n")
        return DeliveryStatus.SENT
    def buffer_size(self): return 0
    def disconnect(self):
        print("[STUB] disconnect()")

class _StubExamState:
    """Exam always active."""
    def is_active(self) -> bool:
        return True


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from network_sender import NetworkSender
    from auth_client import AuthClient

    print("=" * 55)
    print("  MONITOR LOOP — live mode")
    print("  Press Ctrl+C to stop")
    print("=" * 55)

    # ── Switch to real ExamState when teammate's module is ready: ─────────
    #   from exam_state import ExamState
    #   exam_state = ExamState()
    # ─────────────────────────────────────────────────────────────────────

    auth        = AuthClient()
    auth_result = auth.authenticate("student1", "secret1")
    sender      = NetworkSender(auth_result=auth_result)
    exam_state  = _StubExamState()

    loop = MonitorLoop(exam_state=exam_state, sender=sender)
    loop.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        loop.stop()
        print("Exited.")