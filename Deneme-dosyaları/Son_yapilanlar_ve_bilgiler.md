# Son Yapilanlar ve Bilgiler

Tarih: 2026-04-03

---

## Proje Bilgileri

- **Proje:** Network-Based Laboratory Exam System (Ag tabanli sinav sistemi)
- **Sunucu port:** 8765 (WebSocket, `websockets` kutuphanesi)
- **Tumu Jupyter Notebook (`.ipynb`) tabanli, demo haric**
- **Calisma dizini:** `C:\Users\BARIŞ\Desktop\SOFTWARE ENGİNEERİNG PROJECT - NETWORK-BASED LABORATORY EXAM SYSTEM`

## Ekip ve Task Dagilimi

| Kisi        | Task                                                 |
| ----------- | ---------------------------------------------------- |
| Baris (Sen) | Merkezi WebSocket sunucu + DB uyumu (`server.ipynb`) |
| Ahmed       | Client-side guvenlik (aktif pencere/islem tespiti)   |
| Engin       | Client→Server gercek zamanli veri iletimi            |
| Naz         | Kimlik dogrulama + sifreli iletisim                  |
| Mert        | Veritabani yapisi + backend mantigi                  |
| Irem        | Dashboard (ana arayuz)                               |
| Rana        | UI bilesenleri (tablo, alert, status)                |

## Protokole Iliskin Hatirlatmalar

- Istemci → Sunucu JSON: `{"action": "...", "student_id": "...", "payload": {...}, "session_token": "..."}`
- Sunucu → Istemci JSON: `{"status": "...", "action": "...", "message": "...", "data": {...}}`

## Baris'in `server.ipynb` Uzerinde Yaptigi Duzeltmeler (Bu Oturumda)

1. **Sunucu kendi timer'ini artik tutuyor** — `global_timer()` fonksiyonu `asyncio.create_task()` ile `run_server()` icinde baslatiliyor. `time_left`sunucuda geri sayiyor.
2. **Client'tan gelen `time_left` override kaldirildi** — `status_update` handler'inda artik sunucu `time_left`'i client degeriyle ezip gecilmiyor. Client saat manipulasyonu etkisiz.
3. **Stale websocket temizligi** — `finally` blogunda `info["ws"] = None` eklendi. Baglanti kopan ogrencinin invalid socket referansi RAM'den temizleniyor.
4. **Exception logging** — `handle_client` icindeki `except: pass` yerine `print(f"❌ [SISTEM HATASI] {e}")` yazildi. Hatalar artik gorunur.
5. **Violation detay islemesi** — `violation_alert` artik `True/False` degil; `violation_type`, `details.active_window`, `timestamp` ayiklanip `active_students[sid]["last_violation"]` dict'ine kaydediliyor. Dashboard'a hazir.
6. **Dashboard MM:SS format** — `get_dashboard_data` artik `time_left_formatted` (dakika:saniye) alani donduruyor.
7. **Graceful shutdown** — `run_server()` icindeki `await asyncio.Future()` bir `try/except asyncio.CancelledError` ile sarilmis. Hucre durduruldugunda `"🛑 Sunucu manuel olarak durduruldu. Kapatiliyor..."` mesaji gorunuyor, crash yok.

## Henuz Gelememis Modullere Gore Hazir Bekleyen Yerler

- **Mert (DB):** `db.save_violation_to_sql(student_id, v_type, aktif_pencere)` placeholder comment olarak `status_update` handler'inda var. Mert schema'yi paylasinca buraya yazilacak. CLAUDE.md'de sozlesmesi belli tablolar:
  - `student_sessions`: student_id, exam_id, start_time, end_time, status
  - `violations`: student_id, exam_id, violation_type, timestamp
  - `connection_logs`: student_id, event_type(disconnect/reconnect), timestamp
- **Naz (Auth):** `status_update` handler'inda `"Naz'in auth moduluyle sifreli token dogrulamasi buraya gelecek"` comment'i var. Su anki token: `f"token_{student_id}_gizli"` (basit string).
- **Ahmed + Engin (Guvenlik veri iletimi):** Server `security` dict'inde `violation_type`, `details`, `timestamp`, `active_window` alanlarini kabul edecek sekilde genisletildi. Client tarafindan bu veri gelince hazir.

## Server'in Mevcut Yetenekleri (Calisiyor)

- `register_exam` — Egitmen sinav olusturur
- `request_start_exam` — Ogrenci sinava girer. Coklu giris, reconnect, farkli sinav kontrolu yapar
- `status_update` — Ogrenciden gelen security/violation verisi islenir
- `get_dashboard_data` — Egitmen paneli icin anlik ogrenci durumu, sureler, formatli sure
- `resume_student` — Egitmen donmus ogrenciyi devam ettirir
- Baglanti kopma yonetimi — `disconnected_paused`, `violation_paused`, `completed` durumlan dogru yonetiliyor

## Ogrenci States

- `in_progress` — sinav devam ediyor
- `disconnected_paused` — baglanti koptu, donduruldu
- `violation_paused` — kopya/ihlal tespit edildi, donduruldu
- `completed` — sure doldu, sinav bitti

## Sunucu Hafizasi (Global Degiskenler)

- `active_students = {}` — aktif ogrenci sozlugu (ws, state, session_token, exam_id, time_left, last_violation)
- `exam_registry = {}` — sinav kayit defteri (exam_id -> settings)
- `dashboard_counter = 0` — egitmen paneli guncelleme sayaci

## Onemli Notlar

- `resume_student` komutunda rol dogrulama YOK (herhangi bir WebSocket gonderebilir). Bu Baris'in task'i degil, Naz'in auth modulu gelince cozulmesi planlaniyor.
- Rate limiting yok. Baris'in task'i disinda.
- `global_timer` `time_left -= 1` yaklasimiyla calisiyor. `start_time` + `elapsed` yaklasimi daha hassas olurdu ama su anki yontem calisiyor.
- Digier dosyalar (`test_ogrenci*.ipynb`, `egitmen_*.ipynb`, `demo.py`) duzeltilmedi cunku Baris'in task'i disinda. Client tarafindaki sorunlar (suresiz client countdown, hardcoded `violation_alert=False`, Tkinter thread-safety) baskalarinin sorumlulugunda.

### DEVAM ETTİRME:

## Resume this session with:

claude --resume 2124e21d-7318-4e6c-b388-3ecb02e86fb1
