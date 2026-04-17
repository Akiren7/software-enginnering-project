"""
network_sender.py
=================
RELIABLE DELIVERY VERSION
(Engin's Fixes + Naz's Security + Reliable Transfer)

New in this version
--------------------
  - OutboundBuffer   : thread-safe queue that holds payloads when offline.
                       Max 200 entries. On reconnect, all buffered payloads
                       are flushed to the server in the original order.
  - Sequence numbers : every status_update carries a seq field (1, 2, 3…).
                       The server can detect gaps (lost packets).
  - Session ID       : a UUID generated once per exam session. Stays the same
                       across reconnections so the server can correlate all
                       heartbeats for one student / one exam attempt.
  - Delivery status  : every send() returns DeliveryStatus (SENT / BUFFERED /
                       DROPPED). The caller can log or react to it.
  - Retry on failure : if a send fails, the payload goes back into the buffer
                       instead of being discarded.

What did NOT change
-------------------
  - Naz's SECURE_MODE encryption  (build_secure_packet / open_secure_packet)
  - Naz's AuthClient integration  (_build_registration_message)
  - Engin's ISO timestamp         (_iso_timestamp)
  - Engin's thread cleanup        (_stop_background_loop)
  - Engin's offline logging       ([OFFLINE] messages)
  - Server message format         (action, student_id, session_token, security{})

Teammates
---------
  FROM security teammate (Naz) : security_layer.py, auth_client.py  — unchanged
  FROM server teammate         : SERVER_IP, WS_PORT                 — set below
  FROM exam control teammate   : ExamState.is_active()              — used in monitor_loop.py
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
from typing import Optional
import websockets

from security_layer import (
    build_secure_packet,
    get_expected_server_token,
    sign_message,
)
from auth_client import AuthClient, AuthResult

# ── CONFIG ────────────────────────────────────────────────────────────────
SERVER_IP   = "127.0.0.1"   # ← instructor machine IP
WS_PORT     = 8765           # ← server port
STUDENT_ID  = "std_01"
EXAM_ID     = "exam_001"
SECURE_MODE = True

BUFFER_MAX_SIZE   = 200    # max payloads held while offline
RECONNECT_DELAY   = 3.0    # seconds between reconnect attempts
SEND_TIMEOUT      = 8.0    # seconds before a single send gives up
# ──────────────────────────────────────────────────────────────────────────

WS_URL = f"ws://{SERVER_IP}:{WS_PORT}"


# ── Delivery Status ───────────────────────────────────────────────────────

class DeliveryStatus(Enum):
    """
    Returned by send_heartbeat() so the caller knows what happened.

    SENT     — payload was sent to the server successfully right now.
    BUFFERED — connection was down; payload is queued and will be sent
               automatically once reconnected.
    DROPPED  — buffer is full (> BUFFER_MAX_SIZE); payload was discarded.
               This only happens during a very long disconnection.
    """
    SENT     = "SENT"
    BUFFERED = "BUFFERED"
    DROPPED  = "DROPPED"


# ── Buffered Entry ────────────────────────────────────────────────────────

@dataclass
class _BufferedEntry:
    """
    One item sitting in the outbound buffer.

    seq        : the global sequence number assigned when the payload arrived.
    payload    : the original dict from PayloadBuilder.build()
    queued_at  : unix timestamp when it entered the buffer (for age tracking).
    attempts   : how many times we have tried (and failed) to send this.
    """
    seq       : int
    payload   : dict
    queued_at : float = field(default_factory=time.time)
    attempts  : int   = 0


# ── Outbound Buffer ───────────────────────────────────────────────────────

class OutboundBuffer:
    """
    Thread-safe FIFO queue for outbound payloads.

    Used when the WebSocket connection is unavailable. Entries are added to the buffer
    by send_heartbeat() and drained by _flush_buffer() after reconnect in order to prevent the data loss.

    Capacity is capped at BUFFER_MAX_SIZE (200 for now). When full, the oldest entry is
    evicted to make room (the exam session must continue even if some
    heartbeats are lost during a long disconnection).
    """

    def __init__(self, maxsize: int = BUFFER_MAX_SIZE):
        self._q       = collections.deque(maxlen=maxsize)
        self._lock    = threading.Lock()
        self._maxsize = maxsize

    def push(self, entry: _BufferedEntry) -> DeliveryStatus:
        """
        Add an entry. Returns BUFFERED normally, DROPPED if the deque
        had to evict an old entry to make room (maxlen behaviour).
        """
        with self._lock:
            before = len(self._q)
            self._q.append(entry)
            after  = len(self._q)
            # deque with maxlen evicts from the left automatically
            if before == self._maxsize and after == self._maxsize:
                return DeliveryStatus.DROPPED
            return DeliveryStatus.BUFFERED

    def pop_all(self) -> list:
        """Atomically drain the entire queue and return as a list (oldest first)."""
        with self._lock:
            items = list(self._q)
            self._q.clear()
            return items

    def push_back(self, entries: list):
        """Re-insert entries at the front (used when a flush attempt fails)."""
        with self._lock:
            self._q.extendleft(reversed(entries))

    def size(self) -> int:
        with self._lock:
            return len(self._q)


# ── NetworkSender ─────────────────────────────────────────────────────────

class NetworkSender:
    """
    Reliable WebSocket sender with buffer, sequence numbers, and session ID.

    Public API (unchanged from previous version):
        sender = NetworkSender(auth_result=result)
        sender.register()                    → connect + authenticate
        sender.send_heartbeat(payload)       → returns DeliveryStatus
        sender.disconnect()                  → flush buffer, close connection

    New internal machinery:
        _session_id    : UUID for this exam session (fixed across reconnects)
        _seq           : monotonically increasing message counter
        _buffer        : OutboundBuffer holding payloads sent while offline
    """

    def __init__(self, auth_result: AuthResult = None):
        self._auth_result   = auth_result
        self._auth_client   = AuthClient()
        self._session_token = None
        self._ws            = None
        self._loop          = None
        self._loop_thread   = None
        self._connected     = False
        self._offline_count = 0

        # ── NEW: Reliability fields ───────────────────────────────────────
        self._session_id    = str(uuid.uuid4())   # the same uuid will be used for upcoming heartbeats attemps even if the user disconnects so the system can keep track of the student
        self._seq           = 0                   # incremented per message
        self._seq_lock      = threading.Lock()
        self._buffer        = OutboundBuffer(BUFFER_MAX_SIZE)
        # ─────────────────────────────────────────────────────────────────

        self._start_background_loop()
        print(f"[NET] Session ID: {self._session_id}")

    # ── Sequence number ───────────────────────────────────────────────────

    def _next_seq(self) -> int:
        """Returns the next sequence number, thread-safely."""
        with self._seq_lock:
            self._seq += 1 # we increment the sequence number by one in each heartbeat, this will help us to notice the lost packets(if there are any)
            return self._seq

    # ── Background loop ───────────────────────────────────────────────────

    def _start_background_loop(self):
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="NetworkSenderLoop"
        )
        self._loop_thread.start()

    def _stop_background_loop(self):
        """Engin's fix: graceful async thread shutdown."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=3)
            if self._loop_thread.is_alive():
                print("[NET] Warning: background loop thread did not stop cleanly")
            else:
                print("[NET] Background loop stopped cleanly.")

    def _run(self, coro, timeout: float = 12.0):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── Public API ────────────────────────────────────────────────────────

    def register(self) -> bool:
        """
        Connect to the server and authenticate.
        On reconnect, flushes any buffered payloads automatically.
        """
        return self._run(self._async_register())

    def send_heartbeat(self, payload: dict) -> DeliveryStatus:
        """
        Send a monitoring payload to the server.

        If connected  → sends immediately, returns SENT.
        If offline    → adds to buffer, returns BUFFERED.
        If buffer full→ oldest entry evicted, returns DROPPED.

        The payload is enriched with seq and session_id before sending or
        buffering, so the server always sees these fields regardless of
        whether the packet was delayed.
        """
        seq   = self._next_seq()
        entry = _BufferedEntry(seq=seq, payload=payload)

        if not self._connected or self._ws is None:
            self._offline_count += 1
            status = self._buffer.push(entry)

            if status == DeliveryStatus.DROPPED:
                print(
                    f"[OFFLINE] Buffer full ({BUFFER_MAX_SIZE}). "
                    f"seq={seq} DROPPED. Attempting reconnect..."
                )
            else:
                print(
                    f"[OFFLINE] Not connected — seq={seq} buffered. "
                    f"Buffer size: {self._buffer.size()}. "
                    f"Attempting reconnect..."
                )

            # Try to reconnect in the background; flush will follow automatically
            asyncio.run_coroutine_threadsafe(
                self._async_reconnect_and_flush(), self._loop
            )
            return status

        # Connected — send immediately
        self._run(self._async_send_entry(entry))
        return DeliveryStatus.SENT

    def disconnect(self):
        """
        Flush any remaining buffered payloads, then close the connection.
        """
        if self._connected and self._buffer.size() > 0:
            print(f"[NET] Flushing {self._buffer.size()} buffered packets before disconnect...")
            self._run(self._async_flush_buffer())

        if self._ws:
            self._run(self._async_disconnect())

        self._stop_background_loop()

    def buffer_size(self) -> int:
        """Returns the number of payloads currently waiting in the buffer."""
        return self._buffer.size()

    # ── Message builders ──────────────────────────────────────────────────

    def _build_registration_message(self) -> str:
        """Naz's security: credentials + auth_signature."""
        message = {
            "action":     "request_start_exam",
            "student_id": STUDENT_ID,
            "exam_id":    EXAM_ID,
            "session_id": self._session_id,   # NEW: server can track reconnects
        }
        if self._auth_result and self._auth_result.success:
            creds = self._auth_client.build_credential_fields(self._auth_result)
            message.update(creds)
        else:
            print("[NET] Warning: No auth_result — sending without credentials")

        msg_str = json.dumps(message, sort_keys=True)
        message["auth_signature"] = sign_message(msg_str)
        return json.dumps(message)

    def _build_status_update(self, entry: _BufferedEntry) -> str:
        """
        Builds the status_update envelope.

        New integrity fields added to every message:
            seq        : monotonic counter (1, 2, 3…). Server can detect gaps.
            session_id : UUID for this exam session. Links all heartbeats together.
            buffered   : True if this packet was held in the buffer before sending.
                         Server knows this arrived late and can handle accordingly.
            queued_at  : ISO timestamp of when the payload was originally captured.
                         Differs from timestamp when the packet was buffered.
        """
        payload        = entry.payload
        flags          = payload.get("flags", [])
        has_violation  = len(flags) > 0
        violation_type = flags[0] if flags else None
        was_buffered   = entry.attempts > 0 or (time.time() - entry.queued_at) > 6.0

        data = {
            "action":        "status_update",
            "student_id":    STUDENT_ID,
            "session_token": self._session_token,

            # ── NEW: Integrity fields ─────────────────────────────────────
            "seq":           entry.seq,
            "session_id":    self._session_id,
            "buffered":      was_buffered,
            "queued_at":     _iso_timestamp_from(entry.queued_at),
            # ─────────────────────────────────────────────────────────────

            "security": {
                "violation_alert": has_violation,
                "violation_type":  violation_type,
                "timestamp":       _iso_timestamp(),   # Engin's ISO timestamp
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
        """Connect and authenticate. Flushes buffer on success."""
        try:
            self._ws = await websockets.connect(WS_URL)
            self._connected = True
            print(f"[NET] Connected to {WS_URL}")

            await self._ws.send(self._build_registration_message())
            raw  = await asyncio.wait_for(self._ws.recv(), timeout=5)
            resp = json.loads(raw)

            if resp.get("status") == "success":
                server_token = resp.get("session_token")
                expected     = get_expected_server_token(STUDENT_ID)

                if server_token != expected:
                    print(f"[NET] ⚠ Token mismatch — got: {server_token}")
                else:
                    print(f"[NET] ✓ Token verified")

                self._session_token = server_token
                self._offline_count = 0
                reconnected = resp.get("reconnected", False)

                if reconnected:
                    left = resp.get("time_left_seconds", "?")
                    print(f"[NET] Reconnected to existing session. Time left: {left}s")
                else:
                    mins = resp.get("total_duration_minutes", 40)
                    print(f"[NET] Exam started. Duration: {mins} min")

                # Flush any payloads that built up while we were offline
                await self._async_flush_buffer()
                return True

            else:
                reason = resp.get("message", "unknown")
                print(f"[OFFLINE] Registration rejected: {reason}")
                self._connected = False
                return False

        except ConnectionRefusedError:
            print(f"[OFFLINE] Server not reachable at {WS_URL}")
        except asyncio.TimeoutError:
            print(f"[OFFLINE] Server did not respond within 5 seconds")
        except Exception as e:
            print(f"[OFFLINE] Register error: {type(e).__name__}: {e}")

        self._connected = False
        return False

    async def _async_reconnect_and_flush(self):
        """
        Background reconnect attempt triggered when send_heartbeat() finds
        no connection. Waits RECONNECT_DELAY seconds first to avoid hammering
        the server when it is briefly unavailable.
        """
        if self._connected:
            return   # another coroutine already reconnected

        await asyncio.sleep(RECONNECT_DELAY)
        if not self._connected:
            await self._async_register()

    async def _async_flush_buffer(self):
        """
        Drains the outbound buffer and sends all queued entries in order.
        If a send fails mid-flush, the remaining entries are pushed back
        so they are not lost.
        """
        entries = self._buffer.pop_all()
        if not entries:
            return

        print(f"[NET] Flushing {len(entries)} buffered packet(s) in order...")
        failed_from = None

        for i, entry in enumerate(entries):
            if not self._connected or self._ws is None:
                # Connection dropped again during flush — push remainder back
                failed_from = i
                break
            try:
                entry.attempts += 1
                message = self._build_status_update(entry)
                await asyncio.wait_for(self._ws.send(message), timeout=SEND_TIMEOUT)
                print(f"[NET] ✓ Flushed seq={entry.seq} (buffered={entry.attempts}x)")
            except Exception as e:
                print(f"[OFFLINE] Flush failed at seq={entry.seq}: {e}")
                failed_from = i
                self._connected = False
                self._ws        = None
                break

        if failed_from is not None:
            # Put unsent entries back into the buffer
            self._buffer.push_back(entries[failed_from:])
            print(f"[OFFLINE] {len(entries) - failed_from} packet(s) returned to buffer.")

    async def _async_send_entry(self, entry: _BufferedEntry):
        """
        Send a single entry. On failure, push it back into the buffer so it
        is retried on the next reconnect rather than silently dropped.
        """
        try:
            message = self._build_status_update(entry)
            await asyncio.wait_for(self._ws.send(message), timeout=SEND_TIMEOUT)

            flags    = entry.payload.get("flags", [])
            flag_str = ", ".join(flags) if flags else "clean"
            mode_str = "encrypted" if SECURE_MODE else "plain"
            print(
                f"[NET] ✓ Sent [{mode_str}] seq={entry.seq} | "
                f"violation={len(flags)>0} | flags=[{flag_str}]"
            )

        except websockets.ConnectionClosed:
            print(f"[OFFLINE] Connection closed — seq={entry.seq} re-buffered.")
            self._connected = False
            self._ws        = None
            entry.attempts += 1
            self._buffer.push(entry)

        except asyncio.TimeoutError:
            print(f"[OFFLINE] Send timeout — seq={entry.seq} re-buffered.")
            entry.attempts += 1
            self._buffer.push(entry)

        except Exception as e:
            print(f"[OFFLINE] Send error — seq={entry.seq} re-buffered. ({e})")
            entry.attempts += 1
            self._buffer.push(entry)

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
    """Engin's fix: ISO 8601 timestamp for current moment."""
    return datetime.datetime.now().isoformat(timespec="milliseconds")

def _iso_timestamp_from(unix_ts: float) -> str:
    """Convert a stored unix timestamp to ISO 8601."""
    return datetime.datetime.fromtimestamp(unix_ts).isoformat(timespec="milliseconds")


# ── Standalone test ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json

    print("=" * 60)
    print("  NETWORK SENDER — reliable delivery test")
    print("  (No real server needed for format tests)")
    print("=" * 60)

    auth        = AuthClient()
    auth_result = auth.authenticate("student1", "secret1")
    sender      = NetworkSender(auth_result=auth_result)

    # Give a fake session token so we can build messages
    sender._session_token = f"token_{STUDENT_ID}_gizli"

    fake_payload = {
        "active_window": "Google Chrome - Gmail",
        "open_apps":     ["chrome", "examapp"],
        "exam_running":  True,
        "idle_seconds":  8.0,
        "flags":         ["FOCUS_LOST", "BANNED:chrome"],
    }

    print("\n── Test 1: Sequence numbers increment ──")
    s1 = sender._next_seq()
    s2 = sender._next_seq()
    s3 = sender._next_seq()
    assert s1 == 1 and s2 == 2 and s3 == 3
    print(f"  seq: {s1}, {s2}, {s3}  ✓")

    print("\n── Test 2: Session ID is stable ──")
    sid = sender._session_id
    assert len(sid) == 36   # UUID format
    print(f"  session_id: {sid}  ✓")

    print("\n── Test 3: status_update message has new fields ──")
    entry = _BufferedEntry(seq=sender._next_seq(), payload=fake_payload)
    msg   = sender._build_status_update(entry)

    if SECURE_MODE:
        from security_layer import open_secure_packet
        decoded = open_secure_packet(msg)
    else:
        decoded = _json.loads(msg)

    assert "seq"        in decoded, "seq missing"
    assert "session_id" in decoded, "session_id missing"
    assert "buffered"   in decoded, "buffered missing"
    assert "queued_at"  in decoded, "queued_at missing"
    print(f"  seq={decoded['seq']}, session_id={decoded['session_id'][:8]}...")
    print(f"  buffered={decoded['buffered']}, queued_at={decoded['queued_at']}  ✓")

    print("\n── Test 4: Buffer stores and retrieves in order ──")
    buf = OutboundBuffer(maxsize=5)
    for i in range(1, 4):
        e = _BufferedEntry(seq=i, payload={"flags": []})
        buf.push(e)
    items = buf.pop_all()
    assert [x.seq for x in items] == [1, 2, 3]
    print(f"  Order preserved: {[x.seq for x in items]}  ✓")

    print("\n── Test 5: Buffer evicts oldest when full ──")
    buf2 = OutboundBuffer(maxsize=3)
    for i in range(1, 6):
        status = buf2.push(_BufferedEntry(seq=i, payload={}))
    items2 = buf2.pop_all()
    assert len(items2) == 3
    assert items2[0].seq == 3   # 1 and 2 were evicted
    print(f"  After 5 pushes into size-3 buffer: seqs={[x.seq for x in items2]}  ✓")

    print("\n── Test 6: send_heartbeat returns BUFFERED when offline ──")
    status = sender.send_heartbeat(fake_payload)
    assert status == DeliveryStatus.BUFFERED
    assert sender.buffer_size() == 1
    print(f"  Status: {status.value}, buffer_size: {sender.buffer_size()}  ✓")

    print("\n── Test 7: DeliveryStatus values ──")
    print(f"  SENT={DeliveryStatus.SENT.value}")
    print(f"  BUFFERED={DeliveryStatus.BUFFERED.value}")
    print(f"  DROPPED={DeliveryStatus.DROPPED.value}  ✓")

    print("\n── Registration message (has session_id) ──")
    reg = _json.loads(sender._build_registration_message())
    assert "session_id" in reg
    print(f"  session_id in registration: {reg['session_id'][:8]}...  ✓")

    sender.disconnect()
    print("\n✓ All reliability tests passed!")