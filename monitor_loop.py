"""
monitor_loop.py — FINAL
=======================
Monitoring loop compatible with network_sender.py v4.

How it works
------------
1. start() → register() with server (CATS auth)
2. Loop waits in "waiting room" until sender.is_exam_active() becomes True
   (server pushes exam_started_ack when instructor starts the exam)
3. Once active: build payload every 5s, send via sender.send_heartbeat()
4. stop() → flush buffer, disconnect

Key fix from previous version
------------------------------
- Removed exam_state parameter entirely. Exam active/passive state is now
  driven by sender.is_exam_active() which the NetworkSender sets when it
  receives exam_started_ack from the server. No more _StubExamState needed.
- Main block now uses real NetworkSender + AuthClient, not stubs.
  This is what actually sends data to the server.
"""

import threading
import time

from payload_builder import PayloadBuilder
from network_sender  import NetworkSender, DeliveryStatus
from auth_client     import AuthClient

# ── CONFIG ────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 5
STUDENT_ID         = "std_01"
STUDENT_NAME       = "Alice K."
# ──────────────────────────────────────────────────────────────────────────


class MonitorLoop:
    """
    Monitoring loop. No exam_state parameter — state comes from sender.

    Usage:
        auth        = AuthClient()
        auth_result = auth.authenticate("student_number", "cats_password")
        sender      = NetworkSender(auth_result=auth_result)
        loop        = MonitorLoop(sender=sender)
        loop.start()
    """

    def __init__(self, sender: NetworkSender = None):
        self._sender  = sender or NetworkSender()
        self._builder = PayloadBuilder(STUDENT_ID, STUDENT_NAME)
        self._running = False
        self._thread  = None

    def start(self):
        if self._running:
            return

        registered = self._sender.register()
        if registered:
        # YENİ: PayloadBuilder içindeki ismi sunucudan gelenle güncelle
            self._builder.student_name = self._sender.student_real_name
        
        if not registered:
            print("[MONITOR] Could not register. Will retry when loop runs.")

        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[MONITOR] Loop started.")

    def stop(self):
        self._running = False
        self._sender.disconnect()
        print("[MONITOR] Loop stopped.")

    # ── Internal loop ─────────────────────────────────────────────────────

    def _loop(self):
        waiting_logged = False

        while self._running:

            # ── Waiting room: exam not started yet ────────────────────────
            if not self._sender.is_exam_active():
                if not waiting_logged:
                    print("[MONITOR] ⏳ Waiting room — monitoring paused until instructor starts exam.")
                    waiting_logged = True
                time.sleep(1)
                continue

            # Exam just became active
            if waiting_logged:
                print("[MONITOR] ▶ Exam active. Sending heartbeats.")
                waiting_logged = False

            # ── Build and send payload ────────────────────────────────────
            try:
                payload = self._builder.build()
            except Exception as exc:
                print(f"[MONITOR] Build error: {exc}")
                time.sleep(HEARTBEAT_INTERVAL)
                continue

            self._log(payload)

            status = self._sender.send_heartbeat(payload)

            if status == DeliveryStatus.BUFFERED:
                print(f"[MONITOR] Offline — buffered. Queue: {self._sender.buffer_size()}")
            elif status == DeliveryStatus.DROPPED:
                print("[MONITOR] ⚠ Buffer full — packet dropped.")
            elif status == DeliveryStatus.WAITING:
                # Exam paused mid-session (violation freeze or exam ended)
                print("[MONITOR] ⏸ Exam paused or ended.")
                waiting_logged = False   # will log again when it resumes

            time.sleep(HEARTBEAT_INTERVAL)

    def _log(self, payload: dict):
        flags    = payload.get("flags", [])
        flag_str = ", ".join(flags) if flags else "clean"
        print(
            f"[HB] {payload.get('student_name','?')} | "
            f"window='{payload.get('active_window','')[:40]}' | "
            f"idle={payload.get('idle_seconds', 0):.0f}s | "
            f"flags=[{flag_str}]"
        )


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  MONITOR LOOP — live mode")
    print("  Ctrl+C to stop")
    print("=" * 55)

    # ── Credentials ───────────────────────────────────────────────────────
    # Change these to your real CATS student number and password
    CATS_ID       = "2300007951"       # ← your student number
    CATS_PASSWORD = "1476BaEnder-"      # ← your CATS password
    # ─────────────────────────────────────────────────────────────────────

    auth        = AuthClient()
    auth_result = auth.authenticate(CATS_ID, CATS_PASSWORD)

    if not auth_result.success:
        print(f"[AUTH] Failed: {auth_result.error}")
        exit(1)

    sender = NetworkSender(auth_result=auth_result)
    loop   = MonitorLoop(sender=sender)
    loop.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        loop.stop()
        print("Exited.")