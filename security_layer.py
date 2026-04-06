"""
security_layer.py

Bu modül iki şey yapar:
  1. HMAC-SHA256 ile mesaj imzalama (integrity + authentication)
  2. Fernet (AES-128-CBC) ile mesaj şifreleme (confidentiality)

Server uyumluluğu:
  - Server token formatı: f"token_{student_id}_gizli"
  - Bu modül o token'ı doğrulayabilir ve heartbeat'leri şifreleyebilir
  - Server'daki "Naz'ın auth modülüyle şifreli token doğrulaması buraya gelecek"
    yorumunun karşılığı: verify_server_token() fonksiyonu

Kurulum:
    pip install cryptography
"""

import base64
import hashlib
import hmac
import json
import time

from cryptography.fernet import Fernet


# ── SHARED SECRET ─────────────────────────────────────────────────────────
# Server ile client arasında paylaşılan gizli anahtar.
# İkisi de aynı secret'ı kullanmalı.
SHARED_SECRET = b"exam_system_secret_key_2024_secure"


def _derive_fernet_key(secret: bytes) -> bytes:
    """SHARED_SECRET'tan 32-byte Fernet key türetir (SHA-256 ile)."""
    digest = hashlib.sha256(secret).digest()
    return base64.urlsafe_b64encode(digest)


FERNET_KEY = _derive_fernet_key(SHARED_SECRET)
_fernet = Fernet(FERNET_KEY)


# ── HMAC İmzalama ─────────────────────────────────────────────────────────

def sign_message(message: str) -> str:
    """
    Mesajı HMAC-SHA256 ile imzalar.

    Returns:
        hex string — imza (64 karakter)
    """
    return hmac.new(
        SHARED_SECRET,
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_signature(message: str, signature: str) -> bool:
    """
    İmzayı doğrular. Timing-safe comparison kullanır.

    Returns:
        True  — mesaj geçerli
        False — mesaj manipüle edilmiş
    """
    expected = sign_message(message)
    return hmac.compare_digest(expected, signature)


# ── Fernet Şifreleme ──────────────────────────────────────────────────────

def encrypt_payload(data: dict) -> str:
    """Dict payload'ı JSON → Fernet ile şifreler, base64 string döndürür."""
    raw = json.dumps(data).encode("utf-8")
    return _fernet.encrypt(raw).decode("utf-8")


def decrypt_payload(encrypted_str: str) -> dict:
    """
    Şifreli string'i çözer ve dict döndürür.
    Server tarafında kullanılır.

    Raises:
        InvalidToken — yanlış key veya bozuk mesaj
    """
    raw = _fernet.decrypt(encrypted_str.encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


# ── Tam Güvenli Mesaj Paketi ──────────────────────────────────────────────

def build_secure_packet(data: dict) -> str:
    """
    Mesajı şifreler + HMAC ile imzalar, tek JSON string olarak paketler.

    Paket formatı:
    {
        "encrypted": "<fernet_ciphertext>",
        "signature": "<hmac_hex>",
        "timestamp": 1234567890.123
    }

    Server bu paketi open_secure_packet() ile açar.
    """
    timestamp    = time.time()
    data_with_ts = {**data, "_ts": timestamp}
    encrypted    = encrypt_payload(data_with_ts)
    signature    = sign_message(encrypted)

    return json.dumps({
        "encrypted": encrypted,
        "signature": signature,
        "timestamp": timestamp,
    })


def open_secure_packet(packet_str: str, max_age_seconds: float = 30.0) -> dict:
    """
    Güvenli paketi açar ve doğrular. Server tarafında kullanılır.

    Sırasıyla kontrol eder:
        1. HMAC imza (mesaj değiştirilmiş mi?)
        2. Timestamp (replay attack?)
        3. Fernet decrypt

    Returns:
        dict — orijinal payload (_ts alanı temizlenmiş)

    Raises:
        ValueError — imza geçersiz veya mesaj çok eski
    """
    packet    = json.loads(packet_str)
    encrypted = packet["encrypted"]
    signature = packet["signature"]
    timestamp = packet["timestamp"]

    if not verify_signature(encrypted, signature):
        raise ValueError("Signature verification failed — message may be tampered!")

    age = time.time() - timestamp
    if age > max_age_seconds:
        raise ValueError(f"Message too old ({age:.1f}s) — possible replay attack!")

    data = decrypt_payload(encrypted)
    data.pop("_ts", None)
    return data


# ── Server Token Uyumluluğu ───────────────────────────────────────────────

def get_expected_server_token(student_id: str) -> str:
    """
    Server'ın ürettiği token'ı hesaplar.

    Server kodu (server.ipynb):
        session_token = f"token_{student_id}_gizli"

    Bu fonksiyon o token'ı local'de hesaplar,
    server'dan gelen token ile karşılaştırmak için kullanılır.

    Kullanım (network_sender.py içinde):
        expected = get_expected_server_token(STUDENT_ID)
        if server_response["session_token"] != expected:
            raise ValueError("Token mismatch!")
    """
    return f"token_{student_id}_gizli"


def hash_password(password: str) -> str:
    """
    Password'ü SHARED_SECRET ile birlikte SHA-256 hash'ler.
    Düz metin şifre asla ağa gitmez.

    Server tarafı da aynı hash fonksiyonunu kullanırsa
    allowed_users.json'daki şifreler hash'li saklanabilir.
    Şimdilik server plain password beklediği için bu sadece
    request_start_exam içinde credential imzalamak için kullanılıyor.
    """
    raw = f"{password}:{SHARED_SECRET.decode('utf-8')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  SECURITY LAYER — test")
    print("=" * 55)

    test_data = {
        "action": "status_update",
        "student_id": "std_01",
        "session_token": "token_std_01_gizli",
        "security": {"violation_alert": False, "flags": []}
    }

    print("\n[1] Encrypt / Decrypt...")
    enc = encrypt_payload(test_data)
    dec = decrypt_payload(enc)
    assert dec == test_data
    print("    OK")

    print("\n[2] HMAC sign / verify...")
    msg = json.dumps(test_data)
    sig = sign_message(msg)
    assert verify_signature(msg, sig)
    assert not verify_signature(msg[:-1] + "X", sig)
    print("    OK — tamper detection works")

    print("\n[3] Secure packet round-trip...")
    packet    = build_secure_packet(test_data)
    recovered = open_secure_packet(packet)
    assert recovered["student_id"] == "std_01"
    print("    OK")

    print("\n[4] Server token format...")
    token = get_expected_server_token("std_01")
    assert token == "token_std_01_gizli"
    print(f"    Token: {token}")

    print("\n[5] Password hash...")
    h = hash_password("secret1")
    print(f"    Hash: {h[:20]}...")
    assert len(h) == 64
    print("    OK")

    print("\n✓ All security tests passed!")
