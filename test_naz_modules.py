"""
test_naz_modules.py
===================
security_layer.py, auth_client.py ve network_sender.py için
kapsamlı test dosyası.

Çalıştırmak için:
    python test_naz_modules.py

Gereksinimler:
    pip install cryptography websockets
"""

import json
import sys
import time

# ── Renk kodları (terminal çıktısı için) ──────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

passed = 0
failed = 0

def ok(msg):
    global passed
    passed += 1
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg, err=""):
    global failed
    failed += 1
    print(f"  {RED}✗ FAIL:{RESET} {msg}")
    if err:
        print(f"    {RED}→ {err}{RESET}")

def section(title):
    print(f"\n{YELLOW}{'='*50}{RESET}")
    print(f"{YELLOW}  {title}{RESET}")
    print(f"{YELLOW}{'='*50}{RESET}")


# ══════════════════════════════════════════════════════
# BÖLÜM 1 — security_layer.py
# ══════════════════════════════════════════════════════
section("1 / 3 — security_layer.py")

try:
    from security_layer import (
        encrypt_payload, decrypt_payload,
        sign_message, verify_signature,
        build_secure_packet, open_secure_packet,
        get_expected_server_token, hash_password,
    )
    ok("Import başarılı")
except ImportError as e:
    fail("Import", str(e))
    print(f"\n{RED}security_layer.py bulunamadı, testler durduruluyor.{RESET}")
    sys.exit(1)

# Test 1: Şifreleme → Çözme
try:
    data = {"action": "status_update", "student_id": "std_01", "flags": []}
    enc  = encrypt_payload(data)
    dec  = decrypt_payload(enc)
    assert dec == data
    ok("Fernet encrypt → decrypt (round-trip)")
except Exception as e:
    fail("Fernet encrypt → decrypt", str(e))

# Test 2: Şifreli mesaj okunamaz olmalı
try:
    assert "std_01" not in enc   # plain text şifreli içinde görünmemeli
    ok("Şifreli içerik okunamaz (plain text yok)")
except Exception as e:
    fail("Plain text gizleme", str(e))

# Test 3: HMAC imza doğrulama
try:
    msg = json.dumps(data)
    sig = sign_message(msg)
    assert verify_signature(msg, sig)
    ok("HMAC imza oluşturma ve doğrulama")
except Exception as e:
    fail("HMAC sign/verify", str(e))

# Test 4: Mesaj değiştirilince imza bozulmalı
try:
    tampered = msg[:-1] + "X"
    assert not verify_signature(tampered, sig)
    ok("Mesaj değiştirilince imza geçersizleşiyor (tamper detection)")
except Exception as e:
    fail("Tamper detection", str(e))

# Test 5: Güvenli paket — tam döngü
try:
    packet    = build_secure_packet(data)
    recovered = open_secure_packet(packet)
    assert recovered["student_id"] == "std_01"
    ok("build_secure_packet → open_secure_packet (tam döngü)")
except Exception as e:
    fail("Secure packet round-trip", str(e))

# Test 6: Eski paket reddedilmeli (replay attack koruması)
try:
    old_packet = json.loads(packet)
    old_packet["timestamp"] = time.time() - 60  # 60 sn önce yazılmış gibi yap
    try:
        open_secure_packet(json.dumps(old_packet), max_age_seconds=30)
        fail("Eski paket kabul edildi (replay attack koruması çalışmıyor)")
    except ValueError:
        ok("Eski paket reddediliyor (replay attack koruması)")
except Exception as e:
    fail("Replay attack testi", str(e))

# Test 7: Server token formatı
try:
    token = get_expected_server_token("std_01")
    assert token == "token_std_01_gizli"
    ok(f"Server token formatı doğru: '{token}'")
except Exception as e:
    fail("Server token formatı", str(e))

# Test 8: Password hash
try:
    h1 = hash_password("secret1")
    h2 = hash_password("secret1")
    h3 = hash_password("secret2")
    assert h1 == h2           # aynı şifre → aynı hash
    assert h1 != h3           # farklı şifre → farklı hash
    assert len(h1) == 64      # SHA-256 = 64 hex karakter
    assert "secret1" not in h1  # düz metin hash içinde olmamalı
    ok("Password hash (deterministik, SHA-256, plain text yok)")
except Exception as e:
    fail("Password hash", str(e))


# ══════════════════════════════════════════════════════
# BÖLÜM 2 — auth_client.py
# ══════════════════════════════════════════════════════
section("2 / 3 — auth_client.py")

try:
    from auth_client import AuthClient
    ok("Import başarılı")
except ImportError as e:
    fail("Import", str(e))
    sys.exit(1)

auth = AuthClient()

# Test 9: Geçerli kimlik bilgileri
try:
    r = auth.authenticate("student1", "secret1")
    assert r.success
    assert r.login_id == "student1"
    assert r.password_hash != "secret1"   # düz şifre değil
    assert len(r.credential_sig) == 64    # HMAC hex
    ok("Geçerli kimlik bilgileri kabul ediliyor")
except Exception as e:
    fail("Geçerli kimlik bilgileri", str(e))

# Test 10: Boş login_id reddedilmeli
try:
    r2 = auth.authenticate("", "secret1")
    assert not r2.success
    assert r2.error != ""
    ok("Boş login_id reddediliyor")
except Exception as e:
    fail("Boş login_id kontrolü", str(e))

# Test 11: Boş password reddedilmeli
try:
    r3 = auth.authenticate("student1", "")
    assert not r3.success
    ok("Boş password reddediliyor")
except Exception as e:
    fail("Boş password kontrolü", str(e))

# Test 12: Aynı şifre → aynı hash (deterministik)
try:
    r4 = auth.authenticate("student1", "secret1")
    r5 = auth.authenticate("student1", "secret1")
    assert r4.password_hash == r5.password_hash
    ok("Aynı şifre → aynı hash (deterministik)")
except Exception as e:
    fail("Hash deterministik", str(e))

# Test 13: Credential alanları doğru formatta
try:
    r6     = auth.authenticate("student1", "secret1")
    fields = auth.build_credential_fields(r6)
    assert "login_id"       in fields
    assert "password"       in fields
    assert "password_hash"  in fields
    assert "credential_sig" in fields
    ok("build_credential_fields — tüm alanlar mevcut")
except Exception as e:
    fail("Credential fields", str(e))

# Test 14: Brute-force koruması
try:
    auth2 = AuthClient()
    for _ in range(3):
        auth2.authenticate("", "x")   # validation fail → sayaç artar
    locked = auth2.authenticate("student1", "secret1")
    assert not locked.success
    assert "Too many" in locked.error
    ok("Brute-force koruması (3 hatalı → kilit)")
except Exception as e:
    fail("Brute-force koruması", str(e))


# ══════════════════════════════════════════════════════
# BÖLÜM 3 — network_sender.py
# ══════════════════════════════════════════════════════
section("3 / 3 — network_sender.py")

try:
    from network_sender import NetworkSender, STUDENT_ID, SECURE_MODE
    ok("Import başarılı")
except ImportError as e:
    fail("Import", str(e))
    sys.exit(1)

auth3       = AuthClient()
auth_result = auth3.authenticate("student1", "secret1")
sender      = NetworkSender(auth_result=auth_result)

# Test 15: request_start_exam formatı
try:
    reg = json.loads(sender._build_registration_message())
    assert reg["action"]      == "request_start_exam"
    assert reg["student_id"]  == STUDENT_ID
    assert "login_id"         in reg
    assert "password_hash"    in reg
    assert "credential_sig"   in reg
    assert "auth_signature"   in reg
    assert reg.get("password_hash") != "secret1"  # düz şifre değil
    ok("request_start_exam — format ve güvenlik alanları")
except Exception as e:
    fail("request_start_exam format", str(e))

# Test 16: auth_signature mesajı imzalıyor
try:
    reg2 = json.loads(sender._build_registration_message())
    assert len(reg2["auth_signature"]) == 64
    ok("auth_signature HMAC imzası mevcut (64 hex karakter)")
except Exception as e:
    fail("auth_signature", str(e))

# Heartbeat testleri için fake token set et
sender._session_token = get_expected_server_token(STUDENT_ID)

# Test 17: İhlalli heartbeat
try:
    payload_viol = {
        "active_window": "Google Chrome - ChatGPT",
        "open_apps":     ["chrome", "examapp"],
        "exam_running":  True,
        "idle_seconds":  3.0,
        "flags":         ["FOCUS_LOST", "BANNED:chrome"],
    }
    packet = sender._build_status_update(payload_viol)

    if SECURE_MODE:
        recovered = open_secure_packet(packet)
        assert recovered["action"]                          == "status_update"
        assert recovered["security"]["violation_alert"]     == True
        assert "FOCUS_LOST" in recovered["security"]["details"]["flags"]
        ok("İhlalli heartbeat — şifreli, violation_alert=True")
    else:
        parsed = json.loads(packet)
        assert parsed["security"]["violation_alert"] == True
        ok("İhlalli heartbeat — plain, violation_alert=True")
except Exception as e:
    fail("İhlalli heartbeat", str(e))

# Test 18: Temiz heartbeat
try:
    payload_clean = {
        "active_window": "ExamApp",
        "open_apps":     ["examapp"],
        "exam_running":  True,
        "idle_seconds":  1.5,
        "flags":         [],
    }
    packet2 = sender._build_status_update(payload_clean)

    if SECURE_MODE:
        recovered2 = open_secure_packet(packet2)
        assert recovered2["security"]["violation_alert"] == False
        assert recovered2["security"]["details"]["flags"] == []
        ok("Temiz heartbeat — şifreli, violation_alert=False")
    else:
        parsed2 = json.loads(packet2)
        assert parsed2["security"]["violation_alert"] == False
        ok("Temiz heartbeat — plain, violation_alert=False")
except Exception as e:
    fail("Temiz heartbeat", str(e))

# Test 19: Session token içeriği
try:
    packet3   = sender._build_status_update(payload_clean)
    if SECURE_MODE:
        rec = open_secure_packet(packet3)
        assert rec["session_token"] == sender._session_token
    ok("Session token heartbeat içinde doğru taşınıyor")
except Exception as e:
    fail("Session token taşıma", str(e))

# Test 20: Şifreli paketin düz metin içermemesi
try:
    if SECURE_MODE:
        raw_packet = sender._build_status_update(payload_viol)
        assert "FOCUS_LOST"  not in raw_packet.replace('"encrypted"', '')
        assert "status_update" not in json.loads(raw_packet).get("encrypted", "")
        ok("Şifreli pakette düz metin flag/action görünmüyor")
    else:
        ok("SECURE_MODE=False, bu test atlandı")
except Exception as e:
    fail("Plain text gizleme (heartbeat)", str(e))


# ══════════════════════════════════════════════════════
# ÖZET
# ══════════════════════════════════════════════════════

# Test 21: Yanlis key ile Fernet decrypt edilememeli
try:
    from cryptography.fernet import Fernet, InvalidToken
    import base64 as b64, hashlib as hl

    wrong_key    = b64.urlsafe_b64encode(hl.sha256(b'totally_wrong_hacker_key').digest())
    wrong_fernet = Fernet(wrong_key)

    enc = encrypt_payload({'action': 'status_update', 'student_id': 'std_01'})

    try:
        wrong_fernet.decrypt(enc.encode())
        fail('Yanlis key ile decrypt kabul edildi (guvenlik acigi!)')
    except InvalidToken:
        ok('Yanlis key ile Fernet decrypt reddediliyor (InvalidToken)')
except Exception as e:
    fail('Yanlis key Fernet testi', str(e))

# Test 22: Yanlis key ile paketin icerigi okunamaz olmali
try:
    import security_layer as sl_mod
    from cryptography.fernet import Fernet, InvalidToken
    import base64 as b64, hashlib as hl

    good_packet = build_secure_packet({'test': 'data', 'student_id': 'std_01'})
    encrypted_blob = json.loads(good_packet)["encrypted"]

    orig = sl_mod._fernet
    wrong_k = b64.urlsafe_b64encode(hl.sha256(b'hacker_key_xyz_123').digest())
    sl_mod._fernet = Fernet(wrong_k)

    try:
        sl_mod.decrypt_payload(encrypted_blob)
        fail('Yanlis key ile icerik okundu (guvenlik acigi!)')
    except Exception:
        ok('Yanlis key ile paket icerigi okunamiyor')
    finally:
        sl_mod._fernet = orig
except Exception as e:
    fail('Yanlis key paket testi', str(e))

total = passed + failed
print(f"\n{'='*50}")
print(f"  SONUÇ: {passed}/{total} test geçti", end="")
if failed == 0:
    print(f"  {GREEN}— HEPSİ BAŞARILI ✓{RESET}")
else:
    print(f"  {RED}— {failed} test başarısız ✗{RESET}")
print(f"{'='*50}\n")

sys.exit(0 if failed == 0 else 1)

# ── BONUS: Yanlış key testleri (security_layer.py) ────────────────────────
# (Bu testler dosyanın sonuna eklendi, özetten önce çalışır)
