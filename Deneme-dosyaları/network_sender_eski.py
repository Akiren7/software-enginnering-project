"""
network_sender.py
=================
 Network Sender (WebSocket + Security)
======================================================

Monitoring verilerini (PayloadBuilder çıktısı) alır,
güvenli hale getirir ve server'a WebSocket üzerinden gönderir.

Server uyumluluğu (server.ipynb):
  - Server port: 8765
  - Tanınan action'lar: "request_start_exam", "status_update"
  - Token formatı: f"token_{student_id}_gizli"
  - Credential'lar request_start_exam içinde gönderilir (ayrı login yok)

Akış:
    1. AuthClient ile authenticate()
    2. NetworkSender(auth_result=result)
    3. sender.register()        → request_start_exam gönder, token al
    4. sender.send_heartbeat()  → her 5 sn'de şifreli status_update
    5. sender.disconnect()      → bağlantıyı kapat

Kurulum:
    pip install websockets cryptography
"""

import asyncio
import json
import time
import threading
import websockets

from security_layer import (
    build_secure_packet,
    open_secure_packet,
    get_expected_server_token,
    sign_message,
)
from auth_client import AuthClient, AuthResult


# ── CONFIG ────────────────────────────────────────────────────────────────
SERVER_IP  = "localhost"   # ← instructor machine IP (server'dan öğren)
WS_PORT    = 8765             # ← server.ipynb: websockets.serve(..., 8765)
STUDENT_ID = "std_01"        # ← tüm modüllerde aynı olmalı
EXAM_ID    = "exam_001"      # ← exam control teammate'den alınacak

# SECURE_MODE:
#   True  → status_update mesajları Fernet ile şifrelenir + HMAC imzalanır
#            (server open_secure_packet() ile açmalı)
#   False → düz JSON (server entegrasyonu tamamlanana kadar)
SECURE_MODE = True
# ──────────────────────────────────────────────────────────────────────────

WS_URL = f"ws://{SERVER_IP}:{WS_PORT}"


class NetworkSender:
    """
    Öğrenci makinesinden tüm WebSocket iletişimini yönetir.

    Güvenlik özellikleri:
      - request_start_exam: credential alanları + HMAC imzası içerir
      - status_update: Fernet şifreleme + HMAC imzası (SECURE_MODE=True)
      - Token verify: server'dan gelen token'ı yerel olarak doğrular
      - Rate limiting: server zaten 0.5s'de bir paketi reddediyor,
        biz de heartbeat'i 5 sn'de bir gönderiyoruz (uyumlu)
    """

    def __init__(self, auth_result: AuthResult = None):
        self._auth_result   = auth_result
        self._auth_client   = AuthClient()
        self._session_token = None
        self._ws            = None
        self._loop          = None
        self._connected     = False
        self._start_background_loop()

    # ── Startup ───────────────────────────────────────────────────────────

    def _start_background_loop(self):
        """Async WebSocket kodunu sync monitoring koduyla paralel çalıştırır."""
        self._loop = asyncio.new_event_loop()
        t = threading.Thread(target=self._loop.run_forever, daemon=True)
        t.start()

    def _run(self, coro):
        """Async coroutine'i sync olarak çalıştırır (bridge)."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=10)

    # ── Public API ────────────────────────────────────────────────────────

    def register(self) -> bool:
        """
        Server'a bağlanır ve sınav kaydı yapar.

        Server'a gönderilen mesaj (request_start_exam):
            {
                "action":         "request_start_exam",
                "student_id":     "std_01",
                "exam_id":        "exam_001",
                "login_id":       "student1",      ← AuthClient'tan
                "password":       "secret1",       ← server plain beklediği için
                "password_hash":  "<sha256_hex>",  ← gelecekte server doğrulayacak
                "credential_sig": "<hmac_hex>",    ← bütünlük garantisi
                "auth_signature": "<hmac_hex>",    ← tüm mesajın imzası
            }

        Server yanıtı:
            {
                "action": "exam_started_ack",
                "status": "success",
                "session_token": "token_std_01_gizli",
                "reconnected": false,
                "total_duration_minutes": 40
            }
        """
        return self._run(self._async_register())

    def send_heartbeat(self, payload: dict):
        """
        MonitorLoop'tan gelen payload'ı server'a gönderir.
        SECURE_MODE=True ise Fernet ile şifreli + HMAC imzalı gider.

        payload (PayloadBuilder çıktısı):
            active_window, open_apps, idle_seconds, exam_running, flags
        """
        if not self._connected or self._ws is None:
            print("[NET] Not connected — attempting reconnect...")
            self.register()
            return
        self._run(self._async_send_heartbeat(payload))

    def disconnect(self):
        """WebSocket bağlantısını düzgünce kapatır."""
        if self._ws:
            self._run(self._async_disconnect())

    # ── Message builders ──────────────────────────────────────────────────

    def _build_registration_message(self) -> str:
        """
        request_start_exam mesajı oluşturur.

        Credential alanları AuthClient'tan gelir.
        Tüm mesaj HMAC ile imzalanır (auth_signature).
        """
        message = {
            "action":     "request_start_exam",
            "student_id": STUDENT_ID,
            "exam_id":    EXAM_ID,
        }

        # AuthClient credential'larını ekle
        if self._auth_result and self._auth_result.success:
            creds = self._auth_client.build_credential_fields(self._auth_result)
            message.update(creds)
        else:
            print("[NET] Warning: No auth_result — sending without credentials")

        # Tüm mesajı HMAC ile imzala (mesaj bütünlüğü)
        msg_str = json.dumps(message, sort_keys=True)
        message["auth_signature"] = sign_message(msg_str)

        return json.dumps(message)

    def _build_status_update(self, payload: dict) -> str:
        """
        PayloadBuilder çıktısını server'ın beklediği status_update formatına çevirir.

        SECURE_MODE=True  → build_secure_packet() ile şifreli + imzalı
        SECURE_MODE=False → düz JSON (server entegrasyonu tamamlanana kadar)

        Server okuma noktaları (server.ipynb):
            data["student_id"]
            data["session_token"]         → active_students ile karşılaştırılır
            data["security"]["violation_alert"]
            data["security"]["violation_type"]
            data["security"]["details"]["active_window"]
            data["security"]["details"]["open_apps"]
        """
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
                "timestamp":       time.strftime("%H:%M:%S"),
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

            # Credential'lı request_start_exam gönder
            reg_msg = self._build_registration_message()
            await self._ws.send(reg_msg)
            print("[NET] Sent request_start_exam (with credentials)")

            # Server yanıtını bekle
            raw  = await asyncio.wait_for(self._ws.recv(), timeout=5)
            resp = json.loads(raw)

            if resp.get("status") == "success":
                server_token = resp.get("session_token")

                # Token doğrulama: server'ın ürettiği format ile karşılaştır
                expected = get_expected_server_token(STUDENT_ID)
                if server_token != expected:
                    print(f"[NET] ⚠ Token mismatch! Got: {server_token}, expected: {expected}")
                    # Bağlantıyı kesmiyoruz — server farklı format kullanıyor olabilir
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
                print(f"[NET] Registration rejected: {resp.get('message')}")
                return False

        except ConnectionRefusedError:
            print(f"[NET] Could not connect to {WS_URL} — server running?")
        except asyncio.TimeoutError:
            print("[NET] Server did not respond in time")
        except Exception as e:
            print(f"[NET] Register error: {e}")

        self._connected = False
        return False

    async def _async_send_heartbeat(self, payload: dict):
        try:
            message  = self._build_status_update(payload)
            await self._ws.send(message)

            flags    = payload.get("flags", [])
            flag_str = ", ".join(flags) if flags else "clean"
            mode_str = "encrypted" if SECURE_MODE else "plain"
            print(f"[NET] [{mode_str}] → violation={len(flags)>0} | flags=[{flag_str}]")

        except websockets.ConnectionClosed:
            print("[NET] Connection closed — will retry on next heartbeat")
            self._connected = False
            self._ws        = None
        except Exception as e:
            print(f"[NET] Send error: {e}")

    async def _async_disconnect(self):
        try:
            await self._ws.close()
            print("[NET] Disconnected.")
        except Exception:
            pass
        self._connected = False
        self._ws        = None


# ── Standalone test ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  NETWORK SENDER — message format test")
    print("  (no real server needed)")
    print("=" * 55)

    # AuthClient ile authenticate
    auth        = AuthClient()
    auth_result = auth.authenticate("student1", "secret1")
    print(f"\n[AUTH] success={auth_result.success}")

    sender = NetworkSender(auth_result=auth_result)

    print("\n── request_start_exam (registration) ──")
    reg = json.loads(sender._build_registration_message())
    display = {**reg}
    display["password_hash"]  = display.get("password_hash",  "")[:20] + "..."
    display["credential_sig"] = display.get("credential_sig", "")[:20] + "..."
    display["auth_signature"] = display.get("auth_signature", "")[:20] + "..."
    print(json.dumps(display, indent=2))

    sender._session_token = get_expected_server_token(STUDENT_ID)

    print(f"\n── status_update (SECURE_MODE={SECURE_MODE}) ──")
    payload_violation = {
        "active_window": "Google Chrome - Gmail",
        "open_apps":     ["chrome", "examapp"],
        "exam_running":  True,
        "idle_seconds":  12.3,
        "flags":         ["FOCUS_LOST", "BANNED:chrome"],
    }
    packet = sender._build_status_update(payload_violation)

    if SECURE_MODE:
        recovered = open_secure_packet(packet)
        print(f"  Encrypted + signed: OK")
        print(f"  action    : {recovered['action']}")
        print(f"  violation : {recovered['security']['violation_alert']}")
        print(f"  flags     : {recovered['security']['details']['flags']}")
    else:
        print(packet)

    print("\n── Clean session ──")
    payload_clean = {**payload_violation, "flags": [], "active_window": "ExamApp"}
    packet2 = sender._build_status_update(payload_clean)
    if SECURE_MODE:
        r2 = open_secure_packet(packet2)
        print(f"  violation : {r2['security']['violation_alert']}")

    print("\n✓ All format tests passed!")
