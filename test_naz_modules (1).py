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



# ======================================================
# BOLUM 4 -- instructor_auth.py
# ======================================================
section("4 / 4 --- instructor_auth.py")

try:
    from instructor_auth import (
        InstructorAuth,
        generate_instructor_token,
        verify_instructor_token,
        verify_instructor_role,
        ROLE_PERMISSIONS,
    )
    from security_layer import verify_instructor_token as sl_verify_instructor_token
    from security_layer import verify_instructor_role  as sl_verify_instructor_role
    ok("Import basarili (instructor_auth + security_layer instructor fonksiyonlari)")
except ImportError as e:
    fail("Import", str(e))
    import sys; sys.exit(1)

inst_auth = InstructorAuth()

# Test 26: Gecerli egitmen kimlik bilgileri
try:
    r = inst_auth.authenticate("instructor1", "inst_pass")
    assert r.success
    assert r.role == "instructor"
    assert "resume_student" in r.permissions
    assert len(r.instructor_token) == 64
    ok("Gecerli egitmen kimlik bilgileri kabul ediliyor")
except Exception as e:
    fail("Gecerli egitmen kimlik bilgileri", str(e))

# Test 27: verify_instructor_token -- gecerli
try:
    assert verify_instructor_token(r.instructor_token, "instructor1", "instructor")
    ok("verify_instructor_token -- gecerli token kabul ediliyor")
except Exception as e:
    fail("verify_instructor_token gecerli", str(e))

# Test 28: verify_instructor_token -- yanlis token reddediliyor
try:
    assert not verify_instructor_token("yanlis_token_xyzxyz", "instructor1", "instructor")
    ok("verify_instructor_token -- yanlis token reddediliyor")
except Exception as e:
    fail("verify_instructor_token yanlis token", str(e))

# Test 29: verify_instructor_token -- yanlis kullanici reddediliyor
try:
    assert not verify_instructor_token(r.instructor_token, "baska_egitmen", "instructor")
    ok("verify_instructor_token -- yanlis kullanici reddediliyor")
except Exception as e:
    fail("verify_instructor_token yanlis kullanici", str(e))

# Test 30: Ogr token egitmen tokeninden ayri
try:
    from security_layer import get_expected_server_token
    ogrenci_token  = get_expected_server_token("instructor1")   # ogrenci formatinda
    egitmen_token  = generate_instructor_token("instructor1", "instructor")
    assert ogrenci_token != egitmen_token
    ok("Ogrenci ve egitmen tokenlari birbirinden farkli (cross-role guvenlik)")
except Exception as e:
    fail("Token ayirimi", str(e))

# Test 31: can_perform -- rol bazli yetki
try:
    assert inst_auth.can_perform(r, "resume_student")
    assert inst_auth.can_perform(r, "register_exam")
    assert not inst_auth.can_perform(r, "force_stop_exam")   # sadece admin
    ok("can_perform -- instructor rolu dogru yetkiye sahip")
except Exception as e:
    fail("can_perform rol kontrolu", str(e))

# Test 32: Admin rolu daha fazla yetki
try:
    r_admin = inst_auth.authenticate("admin1", "admin_pass", role="admin")
    assert inst_auth.can_perform(r_admin, "force_stop_exam")
    assert inst_auth.can_perform(r_admin, "ban_student")
    ok("Admin rolu genisletilmis yetkiye sahip")
except Exception as e:
    fail("Admin rol yetkisi", str(e))

# Test 33: resume_student paketi -- dogru format ve sifreleme
try:
    packet = inst_auth.build_resume_student_packet(r, "std_01")
    from security_layer import open_secure_packet
    dec = open_secure_packet(packet)
    assert dec["action"]        == "resume_student"
    assert dec["student_id"]    == "std_01"
    assert dec["instructor_id"] == "instructor1"
    assert "instructor_token"   in dec
    ok("resume_student paketi -- sifrelenmis, tum alanlar mevcut")
except Exception as e:
    fail("resume_student paketi", str(e))

# Test 34: register_exam paketi -- dogru format
try:
    exam_payload = {"exam_id": "exam_001", "duration_minutes": 40}
    packet2 = inst_auth.build_register_exam_packet(r, exam_payload)
    dec2 = open_secure_packet(packet2)
    assert dec2["action"] == "register_exam"
    assert dec2["payload"]["exam_id"] == "exam_001"
    ok("register_exam paketi -- format dogru")
except Exception as e:
    fail("register_exam paketi", str(e))

# Test 35: verify_instructor_role -- sunucu tarafli tek adim dogrulama
try:
    fake_data = {
        "action":           "resume_student",
        "student_id":       "std_01",
        "instructor_id":    "instructor1",
        "instructor_token": r.instructor_token,
        "role":             "instructor",
    }
    ok_flag, err = sl_verify_instructor_role(fake_data, "resume_student")
    assert ok_flag and err == ""
    ok("verify_instructor_role (security_layer) -- gecerli data kabul ediliyor")
except Exception as e:
    fail("verify_instructor_role gecerli", str(e))

# Test 36: verify_instructor_role -- yanlis token reddediliyor
try:
    bad_data = {**fake_data, "instructor_token": "tamamen_yanlis_token_xyz"}
    ok_flag2, err2 = sl_verify_instructor_role(bad_data, "resume_student")
    assert not ok_flag2 and err2 != ""
    ok(f"verify_instructor_role -- yanlis token reddediliyor")
except Exception as e:
    fail("verify_instructor_role yanlis token", str(e))

# Test 37: verify_instructor_role -- yetkisiz aksiyon reddediliyor
try:
    ok_flag3, err3 = sl_verify_instructor_role(fake_data, "force_stop_exam")
    assert not ok_flag3
    ok("verify_instructor_role -- yetkisiz aksiyon reddediliyor")
except Exception as e:
    fail("verify_instructor_role yetki kontrolu", str(e))

# Test 38: PermissionError yetkisiz build
try:
    try:
        inst_auth.build_action_packet(r, "force_stop_exam")
        fail("PermissionError bekleniyor ama firlatilmadi")
    except PermissionError:
        ok("Yetkisiz aksiyon PermissionError firlatiliyor")
except Exception as e:
    fail("PermissionError testi", str(e))

# Test 39: Bos instructor_id reddediliyor
try:
    r_bad = inst_auth.authenticate("", "pass")
    assert not r_bad.success
    ok("Bos instructor_id reddediliyor")
except Exception as e:
    fail("Bos instructor_id", str(e))

# Test 40: Gecersiz rol reddediliyor
try:
    r_bad2 = inst_auth.authenticate("inst1", "pass", role="hacker")
    assert not r_bad2.success and "Unknown role" in r_bad2.error
    ok("Gecersiz rol reddediliyor")
except Exception as e:
    fail("Gecersiz rol", str(e))

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
