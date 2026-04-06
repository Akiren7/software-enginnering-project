# 📝 PROJE DURUM RAPORU (Claude Code İçin Güncel Mimari Notları)

Tarih: 2026-04-07

---

## Proje
Network-Based Laboratory Exam System — Ağ Tabanlı Laboratuvar Sınav Sistemi

GitHub Repo: https://github.com/Akiren7/software-enginnering-project (public, main branch)

Çalışma Dizini: `C:\Users\BARIŞ\Desktop\SOFTWARE ENGİNEERİNG PROJECT - NETWORK-BASED LABORATORY EXAM SYSTEM`

---

## 📌 1. Mevcut Durum ve Son Yapılanlar

Merkezi sunucu (`server_core.py` ve `server.ipynb`) üzerinde takım arkadaşlarının (Naz, Engin, Ahmet, Mert) geliştirdiği alt modüllerin birleştirilmesi (Merge) başarıyla tamamlandı. Sistem şu an **3 Katmanlı Mesaj İşleme** mimarisiyle çalışmaktadır.

---

## Ekip ve Görev Dağılımı

| Kişi  | Görev                                     | Durum      |
|-------|-------------------------------------------|------------|
| Baris | Merkezi WebSocket sunucu + DB uyumu       | Devam      |
| Ahmed | Client-side güvenlik (aktif pencere)      | ✅ Entegre |
| Engin | Client→Server gerçek zamanlı veri iletimi | ✅ Entegre |
| Naz   | Kimlik doğrulama + şifreli iletişim       | ✅ Entegre |
| Mert  | Veritabanı yapısı + backend mantığı       | Placeholder ekli |
| Irem  | Dashboard (ana arayüz)                    | Bekleniyor |
| Rana  | UI bileşenleri (tablo, alert, status)     | Bekleniyor |

---

## 🏗️ 2. Gerçekleşen Mimari Değişiklikler

### Ahmet'in Modülleri (Protokol & Loglama)

- `server.ipynb` içerisine `runtime_logging` (stdout capture kapalı şekilde) ve `discovery` (Port 5354 üzerinden UDP Beacon) entegre edildi.
- `server_core.py` içerisinde mesajlar işlenirken Ahmet'in `protocol.decode` ve checksum mantığı araya (Katman 2 olarak) eklendi.
- `events.py` import fix: `from . import protocol` → `import protocol` (relative import kaldırıldı).
- Server→client mesajları artık `protocol.encode()` ile checksum'lı gönderiliyor (`sync_time`, `exam_end`).
- `_map_ahmet_to_internal()` fonksiyonu hem `matches` (Ahmet) hem `flags` (Engin) formatını destekliyor.

### Mert'in Modülü (Veritabanı & Crash Recovery)

- `db_manager.py` placeholder olarak eklendi.
- `save_server_state()` — Her 5 saniyede RAM'deki veriyi (ws objeleri hariç) `server_recovery_db.json` olarak kaydediyor.
- `load_server_state()` — Sunucu başlarken çökme kurtarma yapıyor.
- `save_violation_to_db()` — Placeholder, Mert'in gerçek SQL entegrasyonunu bekliyor.
- `server.ipynb` içine **HARD_RESET** mantığı eklendi (Testlerde DB sıfırlamak veya çökme sonrası veriyi RAM'e geri yüklemek için).

### Naz'ın Modülü (Güvenlik & Eğitmen Yetkisi)

- Mesajların en dışında AES-128 / HMAC şifre çözme katmanı (Katman 1) çalışmaya devam ediyor.
- `instructor_auth.py` entegre edildi.
- `register_exam` (Admin) ve `resume_student` (Teacher) komutları artık sahte istekleri reddeden güvenli token doğrulamasından geçiyor (`verify_instructor_role`).
- `verify_instructor_role(data, required_action)` doğru imza ile çağrılıyor (önceki `verify_instructor_role(token, role)` hatası düzeltildi).

### Engin'in Modülü (Heartbeat & Reconnect)

- Rate limiting (0.5s) aktif.
- Reconnect Kural 3 (bağlantısı kopan → kurtarılır) ve Kural 4 (ihlal yapan → reddedilir) çalışıyor.
- **Crash Recovery**: Sunucu çökmesi sonrası `ws is None` kontrolü ile otomatik kurtarma eklendi.
- `global_timer` içinde `sync_time` (her 60s) ve `exam_end` (süre bitince) client'a gönderiliyor.

---

## Dosya Yapısı

### Ana Sunucu
| Dosya            | Açıklama |
|---|---|
| `server.ipynb`   | Launcher — import'lar + runtime_logging + discovery + db_manager + `run_server()` + `%autoreload 2` |
| `server_core.py` | Tüm iş mantığı: 3 katmanlı parse, auth, şifreleme, reconnect, risk scoring, dashboard, crash recovery |

### Naz'ın Modülleri (Kimlik + Şifreleme)
| Dosya               | Açıklama |
|---|---|
| `security_layer.py` | Fernet (AES-128-CBC) şifreleme + HMAC-SHA256 imzalama |
| `auth_client.py`    | Öğrenci login_id/password doğrulama + credential paketleme + brute-force koruması |
| `instructor_auth.py` | ✅ YENİ — Eğitmen RBAC yetkilendirme + token üretimi/doğrulama + paket builder'ları |

### Ahmet'in Modülleri (Aktivite Tespiti + Protokol)
| Dosya                | Açıklama |
|---|---|
| `activity_monitor.py`| Aktif pencere, çalışan süreçler, idle süresi (Win/Linux/macOS) |
| `payload_builder.py` | Violation flag üretimi: EXAM_CLOSED, FOCUS_LOST, BANNED, IDLE_WARN, IDLE_CRITICAL |
| `protocol.py`        | JSON mesaj encode/decode + SHA-256 checksum |
| `events.py`          | Event sabitleri ve constructor'ları (welcome, start_exam, sync_time, exam_end, PROCESS_CATCH...) |
| `discovery.py`       | UDP broadcast/multicast server keşif (ServerAnnouncer, discover_server) |
| `runtime_logging.py` | stdout/stderr → JSONL log, tag bazlı level/component mapping, TeeStream |

### Engin'in Modülleri
| Dosya                | Açıklama |
|---|---|
| `network_sender.py`  | WebSocket gönderici: credential'lı register + şifreli heartbeat |
| `monitor_loop.py`    | Arka plan izleme: PayloadBuilder → NetworkSender |

### Mert'in Modülleri
| Dosya                | Açıklama |
|---|---|
| `db_manager.py`      | Crash Recovery (save/load server state), violation placeholder |

---

## 3 Katmanlı Mesaj İşleme Mimarisi

```
Katman 1 (En Dış):  Naz'ın Şifre Çözme
                     "encrypted" + "signature" varsa → open_secure_packet()

Katman 2 (İç):      Ahmet'in Protokolü
                     "event" + "checksum" varsa → protocol.decode()
                     → event→action mapping (START_EXAM→request_start_exam,
                       PROCESS_CATCH→status_update)

Katman 3 (En İç):   geriye uyumluluk
                     Doğrudan action field'ı okunur
                     (Engin'in eski client'ları burada çalışır)
```

---

## Sunucu Hafızası
- `active_students = {}` — aktif öğrenci (ws, state, session_token, exam_id, time_left, login_id, password_hash, credential_sig, total_risk_score, risk_level, last_violation, last_msg_time)
- `exam_registry = {}` — sınav kayıt defteri
- `dashboard_counter = 0` — eğitmen paneli güncelleme sayısı

## Öğrenci State Machine
- `in_progress` — sınav devam ediyor
- `disconnected_paused` — bağlantı koptu, donduruldu
- `violation_paused` — ihlal tespit edildi, donduruldu
- `completed` — süre doldu, sınav bitti

## Protokoller

### Şifreli Status Update (SECURE_MODE=True)
```json
{"encrypted": "<fernet>", "signature": "<hmac_hex>", "timestamp": <unix_ts>}
```

### request_start_exam (Tam Güvenlikli)
```json
{
  "action": "request_start_exam", "student_id": "...", "exam_id": "...",
  "login_id": "...", "password": "...", "password_hash": "<sha256_hex>",
  "credential_sig": "<hmac_hex>", "auth_signature": "<hmap_hex>"
}
```

### Protocol Encode (Server→Client)
```json
{"event": "sync_time", "data": {"time_left_seconds": 1200}, "checksum": "sha256_hex"}
```

---

## ⚠️ 3. BİR SONRAKİ GÖREVDEN ÖNCE YAPILACAKLAR (CRITICAL TODO)

### Mantıksal Kırılma 1 — "Zamanı Dondurma Hilesi"

**Sorun:** `global_timer` içinde sınav süresi sadece öğrenci `in_progress` durumundayken azalıyor. Bağlantısı kopan veya ihlalden dondurulan öğrencinin süresi duruyor. Öğrenci bağlantıyı kasıtlı koparıp süreyi dondurabilir.

**Çözüm:** İlgili `if` bloğu `if info["state"] != "completed":` şeklinde değiştirilmeli, böylece sınav süresi her koşulda (öğrenci düşse bile) akmaya devam etmeli.

### Mantıksal Kırılma 2 — "Sessiz Af (Kilitli Ekran)"

**Sorun:** Eğitmen `resume_student` gönderdiğinde sunucu öğrencinin durumunu kendi içinde `in_progress` yapıyor ama öğrenciye (client) kilitli ekranı açması için sinyal yollamıyor. Öğrenci yeniden bağlanana kadar kilitli kalır (client-side exam state güncellenmez).

**Çözüm:** `resume_student` bloğunun içine, durumu güncelledikten hemen sonra öğrencinin `ws` kanalına `{"action": "exam_resumed", "status": "success"}` mesajını gönderecek kod eklenmeli.

---

## ⚠️ 4. DİĞER BİLİNEN SORUNLAR

| # | Sorun | Kritiklik | Etki |
|---|---|---|---|
| 3 | `exam_registry` kontrolü devre dışı (request_start_exam) | Orta | Sınav açılmadan öğrenci giriş yapabilir (comment'te) |
| 4 | `resume_student` hedef bulunamazsa sessiz geçiyor | Orta | Eğitmen yanlış bilgilendirilir, else bloğu eksik |
| 5 | Rate limiting ilk mesajda yok (request_start_exam) | Düşük | Brute-force credential denemesi için zayıf nokta |
| 6 | `matches` dict formatı vs `flags` list çakışması | Düşük | Ahmet'in PROCESS_CATCH payload'ı bozuk görünebilir |
| 7 | `db_manager.save_violation_to_db` placeholder | Bekleniyor | Mert'in SQL entegrasyonunu bekliyor |
| 8 | İki ayrı log sistemi (`log_event` + `runtime_logging`) | Kod kalitesi | Tutarlılık sorunu, bozuk değil |

---

## Git Durumu
- Branch: main
- Remote: https://github.com/Akiren7/software-enginnering-project (public)
- Son commit: `12a1b3e` — Server core + server.ipynb (3 katmanlı parse, instructor auth, crash recovery, protocol encode, sync_time/exam_end)
