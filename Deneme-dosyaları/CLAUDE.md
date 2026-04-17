# CLAUDE.md — Network-Based Laboratory Exam System

## Proje Özeti

Software Engineering dersi için 7 arkadaşla geliştirilen, ağ tabanlı laboratuvar sınav sistemi. Öğrenciler laboratuvarda merkezi sunucuya bağlanarak sınav yapar. Sistem, ağ bağlantısı kopma, güvenlik ihlali tespiti ve eğitmen paneli gibi özellikler içerir.

## Ekip

- 7 kişiler
- Kullanıcı **server (sunucu) kısmından sorumlu** — herkesin task'ı server ile bağlantılı
- Hoca her 2 haftada bir task verir, derste rapor sunulur

## Teknoloji

- WebSocket (`websockets` kütüphanesi)
- Tümü Jupyter Notebook (`.ipynb`) tabanlı
- Demo uygulaması: Tkinter GUI (`demo.py`), PyInstaller ile `.exe`'ye paketlenmiş

## Mimari — WebSocket Sunucu (Port 8765)

### Dosyalar:

| Dosya                     | Açıklama                                                                                  |
| ------------------------- | ----------------------------------------------------------------------------------------- |
| `server.ipynb`            | Merkezi WebSocket sunucusu — `handle_client()` fonksiyonu tüm istemci mesajlarını yönetir |
| `egitmen_komut.ipynb`     | Eğitmen komut gönderme (sınav oluştur / öğrenci devam ettir)                              |
| `egitmen_dashboard.ipynb` | Canlı sınıf paneli — 2 sn aralıkla öğrenci durumlarını çeker                              |
| `test_ogrenci.ipynb`      | Öğrenci test istemcisi 1 (`2300007951`)                                                   |
| `test_ogrenci2.ipynb`     | Öğrenci test istemcisi 2 (`2300005352`)                                                   |
| `demo.py`                 | Tkinter tabanlı öğrenci giriş GUI'si — PyInstaller ile build edilmiş (`dist/demo.exe`)    |

### Sunucunun Mevcut Yetenekleri (`server.ipynb`):

1. **`register_exam`** — Eğitmen sınav oluşturur (exam_id, duration vb.)
2. **`request_start_exam`** — Öğrenci sınava girer. Çoklu giriş, reconnect, farklı sınav kontrolü yapar
3. **`status_update`** — Öğrenci 2 sn aralıkla kalan süre + ihlal durumu gönderir
4. **`get_dashboard_data`** — Eğitmen canlı paneli — aktif öğrenci sayısı, durumlar, süreler
5. **`resume_student`** — Eğitmen donmuş öğrenciyi devam ettirir
6. **Bağlantı kopma yönetimi** — `disconnected_paused`, `violation_paused`, `completed` durumları

### Sunucu Hafızası:

- `active_students = {}` — aktif öğrenci sözlüğü (ws, state, session_token, exam_id, time_left)
- `exam_registry = {}` — sınav kayıt defteri (exam_id -> settings)
- `dashboard_counter = 0` — eğitmen paneli güncelleme sayacı

### Öğrenci Durum States:

- `in_progress` — sınav devam ediyor
- `disconnected_paused` — bağlantı koptu, donduruldu
- `violation_paused` — kopya/ihlal tespit edildi, donduruldu
- `completed` — süre doldu, sınav bitti

## Bilinen Sorunlar / Eksiklikler

- Sunucu Jupyter hücresi `CancelledError` ile kesilebiliyor (`await asyncio.Future()`)
- Süre takibi istemci tarafında, sunucuya bildiriliyor — sunucu kendi başına zaman saymıyor
- Güvenlik ihlali sadece `True/False` bayrak, detay yok (hangi ihlal, kaç kez vs.)
- Öğrenci sınav bitiminde otomatik tamamlanma sunucudan değil, istemci loop'undan geliyor
- `demo.py`'de violation_alert hardcoded `False`
- Session token basit string (`token_{student_id}_gizli`), gerçek şifreleme yok
- Dashboard sadece aktif öğrenci sayısını gösteriyor, geçmiş/biten sınav kaydı yok

## İletişim Protokolü

İstemciden sunucuya giden JSON formatı:

```json
{"action": "...", "student_id": "...", "payload": {...}, "session_token": "..."}
```

Sunucudan istemciye dönen JSON:

```json
{"status": "...", "action": "...", "message": "...", "data": {...}}
```

## Çalışma Dizini

`C:\Users\BARIŞ\Desktop\SOFTWARE ENGİNEERİNG PROJECT - NETWORK-BASED LABORATORY EXAM SYSTEM`

## Önümüzdeki Sunum Hakkında Not

- Barış birkaç saat sonra kendi ve arkadaşlarının tasklarını paylaşacak
- Sunum için proje geliştirilecek, task dağılımına göre hareket edilecek
- Bu bilgi önceki bir oturumda kullanıcı tarafından sözlü olarak iletilmiştir

---

Önce mevcut durumu ve ekip dağılımını netleştirelim, sonra senin yapman gereken somut işlere geçelim.

Görev Dağılımı Haritası

┌───────┬────────────────────────────────────────────────────┬─────────────────────────────────┐
│ Kişi │ Görev │ Dosya │
├───────┼────────────────────────────────────────────────────┼─────────────────────────────────┤
│ Sen │ Merkezî WebSocket sunucu + DB uyumu │ server.ipynb │
├───────┼────────────────────────────────────────────────────┼─────────────────────────────────┤
│ Ahmed │ Client-side güvenlik (aktif pencere/işlem tespiti) │ Yeni client modülü │
├───────┼────────────────────────────────────────────────────┼─────────────────────────────────┤
│ Engin │ Client→Server gerçek zamanlı veri iletimi │ Yeni client modülü │
├───────┼────────────────────────────────────────────────────┼─────────────────────────────────┤
│ Naz │ Kimlik doğrulama + şifreli iletişim │ server.ipynb + yeni auth modülü │
├───────┼────────────────────────────────────────────────────┼─────────────────────────────────┤
│ Mert │ Veritabanı yapısı + backend mantığı │ Yeni DB modülü │
├───────┼────────────────────────────────────────────────────┼─────────────────────────────────┤
│ İrem │ Dashboard (ana arayüz) │ egitmen_dashboard.ipynb yeniden │
├───────┼────────────────────────────────────────────────────┼─────────────────────────────────┤
│ Rana │ UI bileşenleri (tablo, alert, status) │ Dashboard'a componentler │
└───────┴────────────────────────────────────────────────────┴─────────────────────────────────┘

Senin Yapman Gerekenler (Öncelik Sırasıyla)

1. Sunucu tarafında DB hook'ları ekle (Mert ile uyum)

- active_students dict'i yerine veya yanına, mert'in DB'sine veri yazan bir katman
- Sınav başlangıç/bitiş/kopma/ihlal olaylarını DB'ye loglayan bir fonksiyon
- Mert'in DB schema'sını bilmen lazım — ona şu contract'ı ilet:

student_sessions: student_id, exam_id, start_time, end_time, status
violations: student_id, exam_id, violation_type, timestamp
connection_logs: student_id, event_type(disconnect/reconnect), timestamp

2. Sunucu tarafında kendi timer'ını oluştur

- Şu an süre istemciden geliyor → senin sunucunun kendi asyncio timer'ı olmalı
- Bu, "saat manipülasyonu" açığını kapatır ve DB'ye doğru süre kaydı sağlar

3. İhlal/telemetri veri endpoint'ini genişlet

- Şu an sadece violation_alert: True/False var
- Ahmed'in tespiti ve Engin'in iletimi sonrası senin status_update handler'ın şu yapıyı kabul etmeli:
  {
  "action": "status_update",
  "student_id": "...",
  "session_token": "...",
  "timing": {"time_remaining_seconds": 900},
  "security": {
  "violation_alert": true,
  "violation_type": "unauthorized_window",
  "details": {"window_title": "Chrome", "process_name": "chrome.exe"},
  "timestamp": "2026-04-03T14:30:00"
  }
  }

4. Auth/şifreli iletişim altyapısı için hazırlık (Naz ile uyum)

- Şu an token\_{student_id}\_gizli basit string
- Naz'ın auth modülü geldiğinde handle_client fonksiyonun session validation'ı Naz'ın modülüne devretmeli
- Şimdilik session_token doğrulama mantığını ayrı bir fonksiyona çıkar

5. Sunucu stabilitesi

- CancelledError sorununu çöz — düzgün shutdown mekanizması
- Connection pooling / rate limiting düşünebilirsin

Dosya Değişiklikleri

Değiştirilecek:

- server.ipynb → ana odak noktan. Yukarıdaki 5 maddeyi buraya işleyeceksin

Oluşturulacak (opsiyonel ama şık sunum için):

- db_integration.ipynb → Mert'in DB'si ile konuşan ara katman (sen yazarsın, Mert schema'yı verir)
- protocol_spec.md → JSON message format spesifikasyonu (tüm ekip için contract)

Arkadaşlara İletmen Gerekenler

┌─────────────┬────────────────────────────────────────────────────────────────────────────────────────┐
│ Kime │ Ne İletmelisin │
├─────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ Mert │ DB schema'sını paylaş, tablo isimlerini + kolonları belirt │
├─────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ Ahmed │ Tespit ettiği ihlal verisinin JSON formatını seninle eşle │
├─────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ Engin │ Client→Server mesaj yapısını seninle aynı formatta tut │
├─────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ Naz │ Token validation fonksiyonunu nasıl entegre edeceğini planla │
├─────────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ İrem + Rana │ Dashboard'a hangi endpoint'ten ne veri gittiğini belirt (şu an get_dashboard_data var) │
└─────────────┴────────────────────────────────────────────────────────────────────────────────────────┘

Özetle: Senin işin server.ipynb'yi production-ready hale getirmek + 5 farklı modülün buluştuğu merkezi hub'ı yönetmek.
Sunucunun iskeleti sağlam ama üstüne koyman gereken 5 katman var. Sunum için en kritik ilk adım → mert'in DB'siyle
handshake yapmak ve kendi sunucu timer'ını yazmak.
