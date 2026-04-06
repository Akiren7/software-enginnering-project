"""
network_sender.py
=================
FINAL MERGED VERSION (Engin's Fixes + Naz's Security)

Takes monitoring data, secures it (Naz's module), and sends it to the server
with resilience against connection drops (Engin's module).
"""

import asyncio
import json
import time
import datetime
import threading
import websockets

# NAZ'S SECURITY MODULES (Restored)
from security_layer import (
    build_secure_packet,
    open_secure_packet,
    get_expected_server_token,
    sign_message,
)
from auth_client import AuthClient, AuthResult

# ── CONFIG ────────────────────────────────────────────────────────────────
SERVER_IP  = "127.0.0.1"     # ← instructor machine IP
WS_PORT    = 8765            # ← server port
STUDENT_ID = "std_01"        
EXAM_ID    = "exam_001"      

# NAZ'S SECURE MODE (Restored)
SECURE_MODE = True
# ──────────────────────────────────────────────────────────────────────────

WS_URL = f"ws://{SERVER_IP}:{WS_PORT}"

def _iso_timestamp() -> str:
    """ENGIN'S FIX: Timestamp format (ISO 8601)"""
    return datetime.datetime.now().isoformat(timespec="milliseconds")

class NetworkSender:
    def __init__(self, auth_result: AuthResult = None):
        self._auth_result   = auth_result
        self._auth_client   = AuthClient()
        self._session_token = None
        self._ws            = None
        self._loop          = None
        self._loop_thread   = None       # ENGIN'S FIX: Thread reference
        self._connected     = False
        self._offline_count = 0          # ENGIN'S FIX: Offline counter
        self._start_background_loop()

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
        """ENGIN'S FIX: Async thread cleanup"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=3)
            if self._loop_thread.is_alive():
                print("[NET] Warning: background loop thread did not stop cleanly")
            else:
                print("[NET] Background loop stopped cleanly.")

    def _run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=10)

    # ── Public API ────────────────────────────────────────────────────────

    def register(self) -> bool:
        return self._run(self._async_register())

    def send_heartbeat(self, payload: dict):
        """ENGIN'S FIX: Log silent failure and add reconnect attempt"""
        if not self._connected or self._ws is None:
            self._offline_count += 1
            print(f"[OFFLINE] Not connected to server (missed heartbeats: {self._offline_count}). Attempting reconnect...")
            success = self.register()
            if not success:
                print("[OFFLINE] Reconnect failed. Payload will NOT be sent this cycle.")
                return
            self._offline_count = 0   
        self._run(self._async_send_heartbeat(payload))

    def disconnect(self):
        if self._ws:
            self._run(self._async_disconnect())
        self._stop_background_loop()   

    # ── Message builders ──────────────────────────────────────────────────

    def _build_registration_message(self) -> str:
        """NAZ'S SECURITY: Adding credential fields and auth_signature"""
        message = {
            "action":     "request_start_exam",
            "student_id": STUDENT_ID,
            "exam_id":    EXAM_ID,
        }
        
        # Injecting AuthClient credentials
        if self._auth_result and self._auth_result.success:
            creds = self._auth_client.build_credential_fields(self._auth_result)
            message.update(creds)
        else:
            print("[NET] Warning: No auth_result — sending without credentials")

        # Sign the entire message for integrity
        msg_str = json.dumps(message, sort_keys=True)
        message["auth_signature"] = sign_message(msg_str)
        return json.dumps(message)

    def _build_status_update(self, payload: dict) -> str:
        """MERGE: Engin's ISO timestamp + Naz's Secure Packet"""
        flags          = payload.get("flags", [])
        has_violation  = len(flags) > 0
        violation_type = flags[0] if flags else None

        data = {
            "action":        "status_update",
            "student_id":    STUDENT_ID,
            "session_token": self._session_token,
            "security": {
                "violation_alert": has_violation,
                "violation_type":  violation_type,
                "timestamp":       _iso_timestamp(),  # ENGIN'S ISO TIMESTAMP
                "details": {
                    "active_window": payload.get("active_window", ""),
                    "open_apps":     payload.get("open_apps", []),
                    "idle_seconds":  payload.get("idle_seconds", -1),
                    "exam_running":  payload.get("exam_running", False),
                    "flags":         flags,
                }
            }
        }
        
        # NAZ'S ENCRYPTION
        if SECURE_MODE:
            return build_secure_packet(data)
        return json.dumps(data)

    # ── Async internals ───────────────────────────────────────────────────

    async def _async_register(self) -> bool:
        try:
            self._ws = await websockets.connect(WS_URL)
            self._connected = True
            print(f"[NET] Connected to server at {WS_URL}")

            await self._ws.send(self._build_registration_message())
            raw  = await asyncio.wait_for(self._ws.recv(), timeout=5)
            resp = json.loads(raw)

            if resp.get("status") == "success":
                server_token = resp.get("session_token")
                expected = get_expected_server_token(STUDENT_ID)
                if server_token != expected:
                    print(f"[NET] ⚠ Token mismatch! Got: {server_token}, expected: {expected}")
                else:
                    print(f"[NET] ✓ Token verified")

                self._session_token = server_token
                reconnected = resp.get("reconnected", False)

                if reconnected:
                    print(f"[NET] Reconnected! Time left: {resp.get('time_left_seconds')}s")
                else:
                    mins = resp.get("total_duration_minutes", 40)
                    print(f"[NET] Exam started. Duration: {mins} min")
                return True
            else:
                print(f"[OFFLINE] Registration rejected: {resp.get('message')}")
                self._connected = False
                return False

        except ConnectionRefusedError:
            print(f"[OFFLINE] Server not reachable at {WS_URL}. Is it running?")
        except asyncio.TimeoutError:
            print(f"[OFFLINE] Server at {WS_URL} did not respond within 5 seconds.")
        except Exception as e:
            print(f"[OFFLINE] Unexpected register error: {e}")

        self._connected = False
        return False

    async def _async_send_heartbeat(self, payload: dict):
        try:
            message  = self._build_status_update(payload)
            await self._ws.send(message)

            flags    = payload.get("flags", [])
            flag_str = ", ".join(flags) if flags else "clean"
            mode_str = "encrypted" if SECURE_MODE else "plain"
            print(f"[NET] ✓ Sent [{mode_str}] | violation={len(flags)>0} | flags=[{flag_str}]")

        except websockets.ConnectionClosed:
            print("[OFFLINE] Connection closed by server. Will retry on next heartbeat.")
            self._connected = False
            self._ws        = None
        except Exception as e:
            print(f"[OFFLINE] Failed to send heartbeat: {e}")

    async def _async_disconnect(self):
        try:
            await self._ws.close()
            print("[NET] WebSocket closed.")
        except Exception:
            pass
        finally:
            self._connected = False
            self._ws        = None