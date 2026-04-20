"""
network_sender.py — v4 FINAL
============================
(Engin's Fixes + Naz's Security + Reliable Transfer + CATS Auth + Waiting Room)

Quick config guide
------------------
  SERVER_IP          : instructor machine IP
  STUDENT_ID         : student number (matches CATS)
  EXAM_ID            : exam identifier
  SECURE_MODE        : True = Fernet encrypted, False = plain JSON
  SKIP_WAITING_ROOM  : True  = skip waiting room, start sending immediately
                               USE THIS for testing without instructor panel
                       False = wait for instructor's exam_started_ack (production)
"""

import asyncio
import collections
import datetime
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

import websockets

from security_layer import (
    build_secure_packet,
    get_expected_server_token,
    sign_message,
)
from auth_client import AuthClient, AuthResult

# ── CONFIG ────────────────────────────────────────────────────────────────
SERVER_IP          = "127.0.0.1"
WS_PORT            = 8765
STUDENT_ID         = "2300007951"
EXAM_ID            = "exam_001"
SECURE_MODE        = True
SKIP_WAITING_ROOM  = True    # ← set False in production (requires instructor panel)

BUFFER_MAX_SIZE    = 200
RECONNECT_DELAY    = 3.0
SEND_TIMEOUT       = 8.0

# ──────────────────────────────────────────────────────────────────────────

WS_URL = f"ws://{SERVER_IP}:{WS_PORT}"


# ── Delivery Status ───────────────────────────────────────────────────────

class DeliveryStatus(Enum):
    SENT     = "SENT"       # sent to server right now
    BUFFERED = "BUFFERED"   # offline, queued for later
    DROPPED  = "DROPPED"    # buffer full, oldest evicted
    WAITING  = "WAITING"    # exam not started yet


# ── Buffer internals ──────────────────────────────────────────────────────

@dataclass
class _BufferedEntry:
    seq       : int
    payload   : dict
    queued_at : float = field(default_factory=time.time)
    attempts  : int   = 0


class OutboundBuffer:
    """Thread-safe FIFO queue for payloads held during disconnection."""

    def __init__(self, maxsize: int = BUFFER_MAX_SIZE):
        self._q       = collections.deque(maxlen=maxsize)
        self._lock    = threading.Lock()
        self._maxsize = maxsize
        self.student_real_name = "Bilinmeyen Öğrenci"

    def push(self, entry: _BufferedEntry) -> DeliveryStatus:
        with self._lock:
            before = len(self._q)
            self._q.append(entry)
            if before == self._maxsize and len(self._q) == self._maxsize:
                return DeliveryStatus.DROPPED
            return DeliveryStatus.BUFFERED

    def pop_all(self) -> list:
        with self._lock:
            items = list(self._q)
            self._q.clear()
            return items

    def push_back(self, entries: list):
        with self._lock:
            self._q.extendleft(reversed(entries))

    def size(self) -> int:
        with self._lock:
            return len(self._q)


# ── NetworkSender ─────────────────────────────────────────────────────────

class NetworkSender:

    def __init__(self, auth_result: AuthResult = None):
        self._auth_result   = auth_result
        self._auth_client   = AuthClient()
        self._session_token = None
        self._ws            = None
        self._loop          = None
        self._loop_thread   = None
        self._connected     = False
        self._offline_count = 0

        # Reliable delivery
        self._session_id = str(uuid.uuid4())
        self._seq        = 0
        self._seq_lock   = threading.Lock()
        self._buffer     = OutboundBuffer(BUFFER_MAX_SIZE)

        # Waiting room
        # SKIP_WAITING_ROOM=True  → start True, skip waiting
        # SKIP_WAITING_ROOM=False → start False, wait for instructor
        self._exam_active       = SKIP_WAITING_ROOM
        self._exam_active_event = threading.Event()
        if SKIP_WAITING_ROOM:
            self._exam_active_event.set()

        self._start_background_loop()
        print(f"[NET] Session ID : {self._session_id}")
        print(f"[NET] Waiting room: {'DISABLED (test mode)' if SKIP_WAITING_ROOM else 'ENABLED'}")

    # ── Sequence ──────────────────────────────────────────────────────────

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    # ── Background asyncio loop ───────────────────────────────────────────

    def _start_background_loop(self):
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="NetworkSenderLoop"
        )
        self._loop_thread.start()

    def _stop_background_loop(self):
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=3)
            if self._loop_thread.is_alive():
                print("[NET] Warning: loop thread did not stop cleanly")
            else:
                print("[NET] Background loop stopped.")

    def _run(self, coro, timeout: float = 12.0):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── Public API ────────────────────────────────────────────────────────

    def register(self) -> bool:
        return self._run(self._async_register())

    def is_exam_active(self) -> bool:
        return self._exam_active

    def wait_for_exam_start(self, timeout: float = None) -> bool:
        return self._exam_active_event.wait(timeout=timeout)

    def send_heartbeat(self, payload: dict) -> DeliveryStatus:
        if not self._exam_active:
            return DeliveryStatus.WAITING

        seq   = self._next_seq()
        entry = _BufferedEntry(seq=seq, payload=payload)

        if not self._connected or self._ws is None:
            self._offline_count += 1
            status = self._buffer.push(entry)
            label  = "DROPPED" if status == DeliveryStatus.DROPPED else "buffered"
            print(
                f"[OFFLINE] Not connected — seq={seq} {label}. "
                f"Buffer: {self._buffer.size()}. Reconnecting..."
            )
            asyncio.run_coroutine_threadsafe(
                self._async_reconnect_and_flush(), self._loop
            )
            return status

        self._run(self._async_send_entry(entry))
        return DeliveryStatus.SENT

    def disconnect(self):
        if self._connected and self._buffer.size() > 0:
            print(f"[NET] Flushing {self._buffer.size()} buffered packets...")
            self._run(self._async_flush_buffer())
        if self._ws:
            self._run(self._async_disconnect())
        self._stop_background_loop()

    def buffer_size(self) -> int:
        return self._buffer.size()

    # ── Message builders ──────────────────────────────────────────────────

    def _build_registration_message(self) -> str:
        message = {
            "action":     "request_start_exam",
            "student_id": STUDENT_ID,
            "exam_id":    EXAM_ID,
            "session_id": self._session_id,
        }

        if self._auth_result and self._auth_result.success:
            creds = self._auth_client.build_credential_fields(self._auth_result)
            message.update(creds)
            # Ensure plain password is present for CATS verification
            if "password" not in message:
                message["password"] = self._auth_result.password
        else:
            print("[NET] Warning: no auth_result — sending without credentials")

        msg_str = json.dumps(message, sort_keys=True)
        message["auth_signature"] = sign_message(msg_str)
        return json.dumps(message)

    def _build_status_update(self, entry: _BufferedEntry) -> str:
        payload        = entry.payload
        flags          = payload.get("flags", [])
        has_violation  = len(flags) > 0
        violation_type = flags[0] if flags else None
        was_buffered   = entry.attempts > 0 or (time.time() - entry.queued_at) > 6.0

        data = {
            "action":        "status_update",
            "student_id":    STUDENT_ID,
            "session_token": self._session_token,
            "seq":           entry.seq,
            "session_id":    self._session_id,
            "buffered":      was_buffered,
            "queued_at":     _iso_timestamp_from(entry.queued_at),
            "security": {
                "violation_alert": has_violation,
                "violation_type":  violation_type,
                "timestamp":       _iso_timestamp(),
                "details": {
                    "active_window": payload.get("active_window", ""),
                    "open_apps":     payload.get("open_apps", []),
                    "idle_seconds":  payload.get("idle_seconds", -1),
                    "exam_running":  payload.get("exam_running", False),
                    "flags":         flags,
                }
            }
        }

        if SECURE_MODE:
            return build_secure_packet(data)
        return json.dumps(data)

    # ── Async internals ───────────────────────────────────────────────────

    async def _async_register(self) -> bool:
        try:
            self._ws = await websockets.connect(WS_URL)
            self._connected = True
            print(f"[NET] Connected to {WS_URL}")

            await self._ws.send(self._build_registration_message())
            raw  = await asyncio.wait_for(self._ws.recv(), timeout=8)
            resp = json.loads(raw)

            action = resp.get("action", "")
            status = resp.get("status", "")

            # ── auth_success: CATS OK, waiting for instructor ─────────────
            if action == "auth_success" and status == "success":
                self._session_token = resp.get("session_token")
                self.student_real_name = resp.get("login_name", "Bilinmeyen Öğrenci") # İsmi kaydet
                name = resp.get("message", "")
                print(f"[NET] ✓ Authenticated: {name}")

                if SKIP_WAITING_ROOM:
                    # Test mode: don't wait for instructor panel
                    self._exam_active = True
                    self._exam_active_event.set()
                    print("[NET] ▶ Waiting room skipped (SKIP_WAITING_ROOM=True).")
                else:
                    print("[NET] ⏳ Waiting for instructor to start exam...")

                asyncio.create_task(self._async_listen_for_server_push())
                return True

            # ── exam_started_ack: crash recovery ─────────────────────────
            if action == "exam_started_ack" and status == "success":
                self._session_token = resp.get("session_token")
                reconnected = resp.get("reconnected", False)

                if reconnected:
                    left = resp.get("time_left_seconds", "?")
                    print(f"[NET] 🔄 Reconnected. Time left: {left}s")
                else:
                    mins = resp.get("total_duration_minutes", 40)
                    print(f"[NET] ▶ Exam started. Duration: {mins} min")

                self._exam_active = True
                self._exam_active_event.set()
                self._offline_count = 0
                await self._async_flush_buffer()
                asyncio.create_task(self._async_listen_for_server_push())
                return True

            # ── Rejected ──────────────────────────────────────────────────
            reason = resp.get("message", "unknown")
            print(f"[OFFLINE] Registration rejected: {reason}")
            self._connected = False
            return False

        except ConnectionRefusedError:
            print(f"[OFFLINE] Server not reachable at {WS_URL}")
        except asyncio.TimeoutError:
            print("[OFFLINE] Server did not respond within 8 seconds")
        except Exception as e:
            print(f"[OFFLINE] Register error: {type(e).__name__}: {e}")

        self._connected = False
        return False

    async def _async_listen_for_server_push(self):
        """
        Keeps WebSocket open and reacts to server-pushed events:
          exam_started_ack → instructor started exam → begin sending
          exam_resumed     → violation cleared by instructor
          exam_end         → time up → stop sending
          sync_time        → remaining time log
        """
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                action = msg.get("action", "")

                if action == "exam_started_ack" and msg.get("status") == "success":
                    self._session_token = msg.get("session_token", self._session_token)
                    reconnected = msg.get("reconnected", False)
                    if reconnected:
                        left = msg.get("time_left_seconds", "?")
                        print(f"[NET] 🔄 Exam resumed. Time left: {left}s")
                    else:
                        mins = msg.get("total_duration_minutes", 40)
                        print(f"[NET] ▶ Instructor started exam! Duration: {mins} min")
                    self._exam_active = True
                    self._exam_active_event.set()
                    await self._async_flush_buffer()

                elif action == "exam_resumed":
                    print("[NET] ✅ Exam resumed by instructor.")
                    self._exam_active = True
                    self._exam_active_event.set()

                elif action == "exam_end" or msg.get("event") == "exam_end":
                    print("[NET] ⏹ Exam ended.")
                    self._exam_active = False
                    self._exam_active_event.clear()

                elif "sync_time" in (action, msg.get("event", "")):
                    left = (msg.get("data", {}).get("remaining_seconds")
                            or msg.get("remaining_seconds", "?"))
                    print(f"[NET] 🕐 Time sync: {left}s remaining")

                elif msg.get("status") == "error":
                    print(f"[NET] ⚠ Server: {msg.get('message', '')}")

        except websockets.ConnectionClosed:
            print("[OFFLINE] Server closed connection.")
            self._connected = False
            self._ws        = None
        except Exception as e:
            print(f"[OFFLINE] Listener error: {type(e).__name__}: {e}")
            self._connected = False
            self._ws        = None

    async def _async_reconnect_and_flush(self):
        if self._connected:
            return
        await asyncio.sleep(RECONNECT_DELAY)
        if not self._connected:
            await self._async_register()

    async def _async_flush_buffer(self):
        entries = self._buffer.pop_all()
        if not entries:
            return
        print(f"[NET] Flushing {len(entries)} buffered packet(s)...")
        failed_from = None
        for i, entry in enumerate(entries):
            if not self._connected or self._ws is None:
                failed_from = i
                break
            try:
                entry.attempts += 1
                msg = self._build_status_update(entry)
                await asyncio.wait_for(self._ws.send(msg), timeout=SEND_TIMEOUT)
                print(f"[NET] ✓ Flushed seq={entry.seq}")
            except Exception as e:
                print(f"[OFFLINE] Flush failed at seq={entry.seq}: {e}")
                failed_from = i
                self._connected = False
                self._ws        = None
                break
        if failed_from is not None:
            self._buffer.push_back(entries[failed_from:])
            print(f"[OFFLINE] {len(entries) - failed_from} packet(s) returned to buffer.")

    async def _async_send_entry(self, entry: _BufferedEntry):
        try:
            msg = self._build_status_update(entry)
            await asyncio.wait_for(self._ws.send(msg), timeout=SEND_TIMEOUT)
            flags    = entry.payload.get("flags", [])
            flag_str = ", ".join(flags) if flags else "clean"
            mode_str = "encrypted" if SECURE_MODE else "plain"
            print(
                f"[NET] ✓ Sent [{mode_str}] seq={entry.seq} | "
                f"violation={len(flags)>0} | flags=[{flag_str}]"
            )
        except websockets.ConnectionClosed:
            print(f"[OFFLINE] Connection closed — seq={entry.seq} re-buffered.")
            self._connected = False; self._ws = None
            entry.attempts += 1; self._buffer.push(entry)
        except asyncio.TimeoutError:
            print(f"[OFFLINE] Timeout — seq={entry.seq} re-buffered.")
            entry.attempts += 1; self._buffer.push(entry)
        except Exception as e:
            print(f"[OFFLINE] Error — seq={entry.seq} re-buffered. ({e})")
            entry.attempts += 1; self._buffer.push(entry)

    async def _async_disconnect(self):
        try:
            await self._ws.close()
            print("[NET] WebSocket closed.")
        except Exception:
            pass
        finally:
            self._connected = False
            self._ws        = None


# ── Helpers ───────────────────────────────────────────────────────────────

def _iso_timestamp() -> str:
    return datetime.datetime.now().isoformat(timespec="milliseconds")

def _iso_timestamp_from(unix_ts: float) -> str:
    return datetime.datetime.fromtimestamp(unix_ts).isoformat(timespec="milliseconds")