"""
auth_client.py
==============

Öğrencinin kimlik bilgilerini (login_id + password) alır,
güvenli hale getirir ve network_sender.py'nin
request_start_exam mesajına gömmek için hazır credential paketi üretir.

Server uyumluluğu (server.ipynb):
  - Server action: "request_start_exam" bekliyor
  - Ayrı bir "login" action'ı YOK — credential'lar request_start_exam içinde gönderilir
  - Server şu an plain password doğrulaması yapmıyor ama
    "Naz'ın auth modülüyle şifreli token doğrulaması buraya gelecek" yorumu var
  - Biz credential'ı hash'leyip HMAC ile imzalayarak gönderiyoruz
    (server-side doğrulama eklenince hazır olacak)

Kullanım:
    from auth_client import AuthClient

    auth   = AuthClient()
    result = auth.authenticate("student1", "secret1")
    if result.success:
        sender = NetworkSender(auth_result=result)
        sender.register()
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Optional

from security_layer import SHARED_SECRET, sign_message, hash_password


# ── Auth Result ───────────────────────────────────────────────────────────

@dataclass
class AuthResult:
    """
    authenticate() fonksiyonunun döndürdüğü sonuç.

    Attributes:
        success        : True → kimlik bilgileri geçerli formatta
        login_id       : öğrencinin kullanıcı adı
        password       : düz metin şifre (sadece request_start_exam'e gömülür)
        password_hash  : SHA-256 ile hash'lenmiş şifre (log/debug için)
        credential_sig : HMAC imzası
        error          : hata varsa açıklama
    """
    success        : bool
    login_id       : str = ""
    password       : str = ""   # server hâlâ plain bekleyebileceği için saklıyoruz
    password_hash  : str = ""   # hash'li versiyon (server upgrade olunca kullanılır)
    credential_sig : str = ""   # HMAC(login_id:password_hash)
    error          : str = ""


# ── AuthClient ────────────────────────────────────────────────────────────

class AuthClient:
    """
    Öğrenci kimlik doğrulama istemcisi.

    Yaptıkları:
      - login_id ve password formatını doğrular
      - Password'ü hash'ler (düz metin asla log'a veya pakete düz yazılmaz)
      - HMAC imzalı credential paketi oluşturur
      - Brute-force koruması (3 hatalı girişte 30 sn kilit)

    NEDEN İKİ ADIM YOK?
      Server.ipynb'ye bakıldığında ayrı bir "login" action'ı olmadığı görüldü.
      Bu yüzden credential'lar doğrudan request_start_exam mesajına gömülür.
      network_sender.py bunu _build_registration_message() içinde yapar.
    """

    MAX_ATTEMPTS    = 3
    LOCKOUT_SECONDS = 30

    def __init__(self):
        self._failed_attempts = 0
        self._lockout_until   = 0.0

    # ── Public API ────────────────────────────────────────────────────────

    def authenticate(self, login_id: str, password: str) -> AuthResult:
        """
        Kimlik bilgilerini doğrular ve AuthResult döndürür.

        Args:
            login_id : öğrenci kullanıcı adı (örn: "student1")
            password : düz metin şifre     (örn: "secret1")

        Returns:
            AuthResult — success=True ise NetworkSender'a ver

        Örnek:
            result = auth.authenticate("student1", "secret1")
            if result.success:
                sender = NetworkSender(auth_result=result)
                sender.register()
        """
        # Brute-force kontrolü
        lockout_msg = self._check_lockout()
        if lockout_msg:
            return AuthResult(success=False, error=lockout_msg)

        # Format validasyonu
        err = self._validate_inputs(login_id, password)
        if err:
            self._record_failed_attempt()
            return AuthResult(success=False, error=err)

        # Password hash'le
        pw_hash = hash_password(password)

        # Credential'ı HMAC ile imzala
        cred_sig = sign_message(f"{login_id}:{pw_hash}")

        self._failed_attempts = 0   # başarılı → sayacı sıfırla
        print(f"[AUTH] Credentials prepared for '{login_id}'")

        return AuthResult(
            success        = True,
            login_id       = login_id,
            password       = password,      # server plain beklediği için saklıyoruz
            password_hash  = pw_hash,
            credential_sig = cred_sig,
        )

    def build_credential_fields(self, result: AuthResult) -> dict:
        """
        AuthResult'tan request_start_exam mesajına eklenecek
        credential alanlarını döndürür.

        network_sender._build_registration_message() bu fonksiyonu çağırır
        ve dönen dict'i kendi mesajına merge eder.

        Server şu an bu alanları okumasa da, server-side auth eklenince
        hiçbir şeyi değiştirmeden çalışacak.

        Dönen format:
            {
                "login_id":       "student1",
                "password":       "secret1",       # server uyumu için (geçiş)
                "password_hash":  "<sha256_hex>",  # gelecekte kullanılacak
                "credential_sig": "<hmac_hex>",    # bütünlük garantisi
            }
        """
        if not result.success:
            raise ValueError("Cannot build credentials from failed auth result")

        return {
            "login_id":       result.login_id,
            "password":       result.password,      # server plain bekliyorsa bu kullanılır
            "password_hash":  result.password_hash, # server upgrade'i için hazır
            "credential_sig": result.credential_sig,
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    def _validate_inputs(self, login_id: str, password: str) -> Optional[str]:
        if not login_id or not login_id.strip():
            return "Login ID cannot be empty"
        if not password:
            return "Password cannot be empty"
        if len(login_id) > 64:
            return "Login ID too long (max 64)"
        if len(password) > 128:
            return "Password too long (max 128)"
        return None

    def _check_lockout(self) -> Optional[str]:
        if self._failed_attempts >= self.MAX_ATTEMPTS:
            remaining = self._lockout_until - time.time()
            if remaining > 0:
                return f"Too many failed attempts. Try again in {remaining:.0f}s"
            else:
                self._failed_attempts = 0
        return None

    def _record_failed_attempt(self):
        self._failed_attempts += 1
        if self._failed_attempts >= self.MAX_ATTEMPTS:
            self._lockout_until = time.time() + self.LOCKOUT_SECONDS


# ── Test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    print("=" * 55)
    print("  AUTH CLIENT — test")
    print("=" * 55)

    auth = AuthClient()

    print("\n[1] Valid credentials...")
    r = auth.authenticate("student1", "secret1")
    assert r.success
    print(f"    login_id       : {r.login_id}")
    print(f"    password_hash  : {r.password_hash[:20]}...")
    print(f"    credential_sig : {r.credential_sig[:20]}...")

    print("\n[2] Empty login_id...")
    r2 = auth.authenticate("", "secret1")
    assert not r2.success
    print(f"    error: {r2.error}")

    print("\n[3] Empty password...")
    r3 = auth.authenticate("student1", "")
    assert not r3.success
    print(f"    error: {r3.error}")

    print("\n[4] Credential fields for request_start_exam...")
    fields = auth.build_credential_fields(r)
    display = {**fields, "password_hash": fields["password_hash"][:20] + "...",
               "credential_sig": fields["credential_sig"][:20] + "..."}
    print(json.dumps(display, indent=2))

    print("\n[5] Brute-force protection...")
    auth2 = AuthClient()
    for _ in range(3):
        auth2.authenticate("", "x")   # validation fail → sayaç artar
    locked = auth2.authenticate("student1", "secret1")
    assert not locked.success and "Too many" in locked.error
    print(f"    Locked after 3 attempts: OK")
    print(f"    error: {locked.error}")

    print("\n✓ All auth tests passed!")
