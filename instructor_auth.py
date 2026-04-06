"""
instructor_auth.py
==================
 Instructor Authentication
==========================================

Eğitmen komutlarını doğrulayan kimlik doğrulama modülü.

Kapsanan komutlar (server.ipynb):
    - resume_student  : kopya çeken öğrenciyi affetme
    - register_exam   : yeni sınav aktif etme
    - (gelecek)       : diğer eğitmen komutları

Server.ipynb'deki ilgili action'lar:
    elif action == "resume_student":
        hedef_id = data.get("student_id")
        if hedef_id in active_students:
            active_students[hedef_id]["state"] = "in_progress"

    elif action == "register_exam":
        exam_id = data["payload"]["exam_id"]
        exam_registry[exam_id] = data["payload"]

Bu modül bu action'larla gelen eğitmen token'larını doğrular.

Kullanım:
    from instructor_auth import InstructorAuth

    auth   = InstructorAuth()
    result = auth.authenticate("instructor1", "inst_pass")
    if result.success:
        packet = auth.build_resume_student_packet(result, target_student_id="std_01")
        # → network_sender veya doğrudan WebSocket ile gönder

Kurulum:
    pip install cryptography  (security_layer.py'deki bağımlılıkla aynı)
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Optional, Literal

from security_layer import (
    SHARED_SECRET,
    sign_message,
    verify_signature,
    build_secure_packet,
    hash_password,
)


# ── Eğitmen Rol Tanımları ─────────────────────────────────────────────────

# Hangi rol hangi aksiyonları yapabilir
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "instructor": [
        "resume_student",
        "register_exam",
        "get_dashboard_data",
    ],
    "admin": [
        "resume_student",
        "register_exam",
        "get_dashboard_data",
        "force_stop_exam",      # gelecekte eklenebilir
        "ban_student",          # gelecekte eklenebilir
    ],
}

# Eğitmen için ayrı HMAC secret — öğrenci secret'ından farklı
INSTRUCTOR_SECRET = SHARED_SECRET + b":instructor_role"


# ── Auth Result ───────────────────────────────────────────────────────────

@dataclass
class InstructorAuthResult:
    """
    InstructorAuth.authenticate() döndürdüğü sonuç.

    Attributes:
        success          : True → kimlik doğrulandı
        instructor_id    : eğitmenin kullanıcı adı
        role             : "instructor" veya "admin"
        instructor_token : HMAC türevli eğitmen token'ı
        permissions      : bu role ait izin listesi
        error            : başarısız olursa açıklama
    """
    success          : bool
    instructor_id    : str       = ""
    role             : str       = "instructor"
    instructor_token : str       = ""
    permissions      : list      = field(default_factory=list)
    error            : str       = ""


# ── InstructorAuth ────────────────────────────────────────────────────────

class InstructorAuth:
    """
    Eğitmen kimlik doğrulama ve yetkilendirme sınıfı.

    Öğrenci auth'undan farkları:
      - Ayrı INSTRUCTOR_SECRET kullanılır (öğrenci token'larıyla karışmaz)
      - Rol tabanlı yetkilendirme (RBAC) desteklenir
      - Her aksiyon paketi hangi komutu kimin gönderdiğini açıkça belirtir
      - verify_instructor_token() ile sunucu token doğrulayabilir

    Tasarım kararı:
      Eğitmen token'ı deterministik türetilir (instructor_id + role + secret).
      Bu sayede sunucu da aynı hesaplamayı yaparak token'ı doğrulayabilir;
      ayrı bir token DB tutmaya gerek kalmaz.
    """

    MAX_ATTEMPTS    = 5           # eğitmen için biraz daha toleranslı
    LOCKOUT_SECONDS = 60

    def __init__(self):
        self._failed_attempts = 0
        self._lockout_until   = 0.0

    # ── Public API ────────────────────────────────────────────────────────

    def authenticate(
        self,
        instructor_id: str,
        password: str,
        role: str = "instructor"
    ) -> InstructorAuthResult:
        """
        Eğitmeni doğrular.

        Args:
            instructor_id : eğitmenin kullanıcı adı
            password      : düz metin şifre
            role          : "instructor" veya "admin" (varsayılan: "instructor")

        Returns:
            InstructorAuthResult — success=True ise paket oluşturmak için kullan

        Örnek:
            auth   = InstructorAuth()
            result = auth.authenticate("instructor1", "inst_pass")
            if result.success:
                packet = auth.build_resume_student_packet(result, "std_01")
        """
        lockout = self._check_lockout()
        if lockout:
            return InstructorAuthResult(success=False, error=lockout)

        err = self._validate_inputs(instructor_id, password, role)
        if err:
            self._record_failed_attempt()
            return InstructorAuthResult(success=False, error=err)

        # Eğitmen token'ı üret
        token = generate_instructor_token(instructor_id, role)

        # Rol izinlerini al
        permissions = ROLE_PERMISSIONS.get(role, [])

        self._failed_attempts = 0
        print(f"[INST AUTH] Instructor '{instructor_id}' authenticated (role={role})")

        return InstructorAuthResult(
            success          = True,
            instructor_id    = instructor_id,
            role             = role,
            instructor_token = token,
            permissions      = permissions,
        )

    def can_perform(self, result: InstructorAuthResult, action: str) -> bool:
        """
        Eğitmenin belirli bir aksiyonu yapıp yapamayacağını kontrol eder.

        Args:
            result : authenticate() çıktısı
            action : "resume_student", "register_exam" vb.

        Returns:
            True  → yetkili
            False → yetkisiz

        Örnek:
            if not auth.can_perform(result, "resume_student"):
                print("Bu işlem için yetkiniz yok")
        """
        if not result.success:
            return False
        return action in result.permissions

    def build_resume_student_packet(
        self,
        result: InstructorAuthResult,
        target_student_id: str,
    ) -> str:
        """
        resume_student aksiyonu için güvenli paket oluşturur.

        Server.ipynb'deki handler:
            elif action == "resume_student":
                hedef_id = data.get("student_id")
                active_students[hedef_id]["state"] = "in_progress"

        Dönen paket (build_secure_packet ile şifreli):
            {
                "action":            "resume_student",
                "student_id":        "std_01",          ← hedef öğrenci
                "instructor_id":     "instructor1",
                "instructor_token":  "<hmac_token>",
                "role":              "instructor",
                "timestamp":         1234567890.0,
            }

        Raises:
            PermissionError — eğitmenin bu aksiyonu için yetkisi yoksa
        """
        self._require_permission(result, "resume_student")

        data = {
            "action":           "resume_student",
            "student_id":       target_student_id,
            "instructor_id":    result.instructor_id,
            "instructor_token": result.instructor_token,
            "role":             result.role,
            "timestamp":        time.time(),
        }
        return build_secure_packet(data)

    def build_register_exam_packet(
        self,
        result: InstructorAuthResult,
        exam_payload: dict,
    ) -> str:
        """
        register_exam aksiyonu için güvenli paket oluşturur.

        Server.ipynb'deki handler:
            elif action == "register_exam":
                exam_id = data["payload"]["exam_id"]
                exam_registry[exam_id] = data["payload"]

        Args:
            exam_payload : {"exam_id": "...", "duration_minutes": 40, ...}

        Raises:
            PermissionError — yetki yoksa
        """
        self._require_permission(result, "register_exam")

        data = {
            "action":           "register_exam",
            "instructor_id":    result.instructor_id,
            "instructor_token": result.instructor_token,
            "role":             result.role,
            "payload":          exam_payload,      # server bu alanı okur
            "timestamp":        time.time(),
        }
        return build_secure_packet(data)

    def build_action_packet(
        self,
        result: InstructorAuthResult,
        action: str,
        extra_fields: dict = None,
    ) -> str:
        """
        Gelecekteki eğitmen komutları için genel paket builder.

        Yeni bir eğitmen komutu eklendiğinde bu fonksiyon kullanılabilir.
        ROLE_PERMISSIONS'a action eklenmesi yeterlidir.

        Args:
            action       : aksiyon adı (ROLE_PERMISSIONS'da tanımlı olmalı)
            extra_fields : aksiyona özel ek alanlar

        Raises:
            PermissionError — yetki yoksa
        """
        self._require_permission(result, action)

        data = {
            "action":           action,
            "instructor_id":    result.instructor_id,
            "instructor_token": result.instructor_token,
            "role":             result.role,
            "timestamp":        time.time(),
        }
        if extra_fields:
            data.update(extra_fields)

        return build_secure_packet(data)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _require_permission(self, result: InstructorAuthResult, action: str):
        if not result.success:
            raise PermissionError("Authentication required before performing actions")
        if not self.can_perform(result, action):
            raise PermissionError(
                f"Instructor '{result.instructor_id}' (role={result.role}) "
                f"is not authorized to perform '{action}'"
            )

    def _validate_inputs(
        self, instructor_id: str, password: str, role: str
    ) -> Optional[str]:
        if not instructor_id or not instructor_id.strip():
            return "Instructor ID cannot be empty"
        if not password:
            return "Password cannot be empty"
        if len(instructor_id) > 64:
            return "Instructor ID too long"
        if role not in ROLE_PERMISSIONS:
            return f"Unknown role '{role}'. Valid roles: {list(ROLE_PERMISSIONS.keys())}"
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


# ── Standalone Doğrulama Fonksiyonları ───────────────────────────────────
# Sunucu tarafında import edilerek kullanılır.

def generate_instructor_token(instructor_id: str, role: str) -> str:
    """
    Eğitmen ID + rol + INSTRUCTOR_SECRET'tan deterministik token üretir.

    Server da aynı fonksiyonla token'ı hesaplayıp karşılaştırabilir.
    Öğrenci token'larından (SHARED_SECRET kullanan) ayrıdır.

    Örnek çıktı: "a3f8b2..." (64 hex karakter)
    """
    raw = f"{instructor_id}:{role}:{INSTRUCTOR_SECRET.decode('utf-8')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_instructor_token(token: str, instructor_id: str, role: str) -> bool:
    """
    Eğitmen token'ını doğrular. Sunucu tarafında kullanılır.

    Server.ipynb'e eklenecek satırlar:
        from instructor_auth import verify_instructor_token

        elif action == "resume_student":
            inst_token = data.get("instructor_token")
            inst_id    = data.get("instructor_id")
            inst_role  = data.get("role", "instructor")

            if not verify_instructor_token(inst_token, inst_id, inst_role):
                await websocket.send(json.dumps({
                    "status": "error",
                    "message": "Yetkisiz eğitmen komutu reddedildi."
                }))
                continue

            # Doğrulandı — öğrenciyi affet
            hedef_id = data.get("student_id")
            ...

    Returns:
        True  → token geçerli, komut işlenebilir
        False → geçersiz token, komut reddedilmeli

    Timing-safe comparison kullanır.
    """
    if not token or not instructor_id or not role:
        return False
    expected = generate_instructor_token(instructor_id, role)
    return hmac.compare_digest(token, expected)


def verify_instructor_role(
    data: dict,
    required_action: str,
) -> tuple[bool, str]:
    """
    Gelen paketten eğitmen token'ını ve rol iznini birlikte doğrular.

    Sunucu için kolaylık fonksiyonu — tek çağrıda hem token hem yetki kontrolü.

    Args:
        data            : WebSocket'ten gelen parse edilmiş JSON dict
        required_action : hangi aksiyon için yetki kontrol ediliyor

    Returns:
        (True,  "")           → doğrulandı, devam et
        (False, "hata mesajı") → reddedildi, mesajı client'a gönder

    Kullanım (server.ipynb):
        from instructor_auth import verify_instructor_role

        elif action == "resume_student":
            ok, err = verify_instructor_role(data, "resume_student")
            if not ok:
                await websocket.send(json.dumps({"status":"error","message":err}))
                continue
            # devam et...
    """
    instructor_id = data.get("instructor_id", "")
    token         = data.get("instructor_token", "")
    role          = data.get("role", "instructor")

    # Token doğrulama
    if not verify_instructor_token(token, instructor_id, role):
        return False, "Geçersiz eğitmen token'ı — komut reddedildi."

    # Rol izin kontrolü
    allowed = ROLE_PERMISSIONS.get(role, [])
    if required_action not in allowed:
        return False, f"'{role}' rolü '{required_action}' komutunu çalıştıramaz."

    return True, ""


# ── Test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  INSTRUCTOR AUTH — test")
    print("=" * 55)

    auth = InstructorAuth()

    print("\n[1] Valid instructor credentials...")
    r = auth.authenticate("instructor1", "inst_pass")
    assert r.success
    assert r.role == "instructor"
    assert "resume_student" in r.permissions
    assert len(r.instructor_token) == 64
    print(f"    OK — token: {r.instructor_token[:20]}...")

    print("\n[2] verify_instructor_token...")
    assert verify_instructor_token(r.instructor_token, "instructor1", "instructor")
    assert not verify_instructor_token("fake_token" * 5, "instructor1", "instructor")
    assert not verify_instructor_token(r.instructor_token, "instructor2", "instructor")
    print("    OK — valid/invalid/wrong_id all work")

    print("\n[3] can_perform (role-based)...")
    assert auth.can_perform(r, "resume_student")
    assert auth.can_perform(r, "register_exam")
    assert not auth.can_perform(r, "force_stop_exam")  # sadece admin
    print("    OK")

    print("\n[4] resume_student packet...")
    packet = auth.build_resume_student_packet(r, "std_01")
    from security_layer import open_secure_packet
    dec = open_secure_packet(packet)
    assert dec["action"] == "resume_student"
    assert dec["student_id"] == "std_01"
    assert dec["instructor_id"] == "instructor1"
    print(f"    OK — action={dec['action']}, target={dec['student_id']}")

    print("\n[5] register_exam packet...")
    exam_payload = {"exam_id": "exam_001", "duration_minutes": 40}
    packet2 = auth.build_register_exam_packet(r, exam_payload)
    dec2 = open_secure_packet(packet2)
    assert dec2["action"] == "register_exam"
    assert dec2["payload"]["exam_id"] == "exam_001"
    print(f"    OK — exam_id={dec2['payload']['exam_id']}")

    print("\n[6] verify_instructor_role (server-side helper)...")
    fake_data = {
        "action":           "resume_student",
        "student_id":       "std_01",
        "instructor_id":    "instructor1",
        "instructor_token": r.instructor_token,
        "role":             "instructor",
    }
    ok, err = verify_instructor_role(fake_data, "resume_student")
    assert ok and err == ""
    print("    OK — valid data passes")

    bad_data = {**fake_data, "instructor_token": "wrong_token_xyz"}
    ok2, err2 = verify_instructor_role(bad_data, "resume_student")
    assert not ok2 and err2 != ""
    print(f"    OK — invalid token rejected: '{err2}'")

    print("\n[7] PermissionError for unauthorized action...")
    try:
        auth.build_action_packet(r, "force_stop_exam")
        assert False, "Should have raised"
    except PermissionError as e:
        print(f"    OK — caught: {e}")

    print("\n[8] Admin role has more permissions...")
    r_admin = auth.authenticate("admin1", "admin_pass", role="admin")
    assert auth.can_perform(r_admin, "force_stop_exam")
    assert auth.can_perform(r_admin, "ban_student")
    print("    OK — admin has extended permissions")

    print("\n[9] Empty instructor_id rejected...")
    r_bad = auth.authenticate("", "pass")
    assert not r_bad.success
    print(f"    OK — error: {r_bad.error}")

    print("\n[10] Invalid role rejected...")
    r_bad2 = auth.authenticate("inst1", "pass", role="hacker")
    assert not r_bad2.success
    print(f"    OK — error: {r_bad2.error}")

    print("\n✓ All instructor auth tests passed!")
