---
Mevcut Sorunlar

1. Öğrenci ID elle giriliyor — gereksiz

Her öğrenci numarasını bilip elle yazmak zorunda. Gerçek senaryoda bu otomatik gelmeli.

2. Sınav seçimi var ama sunucu bunu zorunlu kılmıyor artık

demo.py Combobox ile sınav seçtiriyor ama server.ipynb tarafında artık sunucu kendi aktif sınavı yönetiyor olabilir. Eğer
sunucu tek sınav moduna geçtiyse bu alan gereksiz.

3. IP adresi elle giriliyor

192.168.1.X placeholder. Laboratuvarda sunucu IP'si sabit olmalı, hardcode edilebilir veya otomatik bulunabilir.

4. violation_alert hardcoded False (satır 48)

Ahmed'in modülü gelince bu dinamik olacak. Şimdilik sadece placeholder.

5. Tkinter thread-safety ihlali

network_task ayrı bir daemon thread'de çalışıp log_ekle() ile log_text widget'ına doğrudan yazıyor (satır 73). Tkinter'de
widget işlemleri sadece ana thread'den yapılmalı. Bu nadiren crash'e sebep olabilir.

6. Sınav bitince sunucuya bildirim yok

while time_left > 0 döngüsü bittiğinde herhangi bir "exam_completed" mesajı gönderilmiyor. Sunucu sadece bağlantı kopunca
(finally ile) fark ediyor.

7. Hata durumunda buton tekrar aktif oluyor ama kullanıcı bilgilendirilmiyor yeterince

btn_giris.config(state="normal") satır 25 ve 59'da var ama kullanıcı neyin yanlış gittiğini tam anlamayabilir.
---

Öneriler — Nasıl Daha İyi Hale Getirilir

A. Öğrenci ID otomatik olsun

Seçenek 1 — Bilgisayar adı / hostname:
import socket
student_id = socket.gethostname() # Laboratuvar PC'lerinin adları öğrenci ID'si olabilir

Seçenek 2 — Config dosyası:
Her bilgisayarın masaüstünde bir student_config.json olur:
{"student_id": "2300007951"}
Uygulama açılınca bunu okur.

Seçenek 3 — Registry'den okuma:
Okul bilgisayarlarında öğrenci ID'si registry'ye yazılabilir. Demo açılınca direkt okunur.

B. Sınav seçimi kaldırılmalı

Eğer sunucu tek bir aktif sınavı yönetiyorsa, client bunu sunucudan çekebilir:

# Bağlanınca sunucudan aktif sınavları iste

await ws.send(json.dumps({"action": "get_active_exams"}))
Ya da sunucu zaten register_exam ile sınavı açtıysa, client direkt o sınava girer — seçim yok.

C. IP adresi sabitlenmeli

Laboratuvarda sunucu PC'nin IP'si belli. Hardcode edilebilir:
SERVER_IP = "192.168.1.100" # Sabit sunucu IP'si
Ya da demo.py'ye CLI argümanı olarak geçilebilir.

D. Thread-safety düzeltilmeli

log_ekle() çağrısını ana thread'e taşı:
import queue
log_queue = queue.Queue()

# Worker thread'den:

log_queue.put(mesaj)

# Ana thread'de (after_idle ile):

def process_log_queue():
while not log_queue.empty():
log_text.insert(tk.END, log_queue.get() + "\n")
log_text.see(tk.END)
root.after(100, process_log_queue)

E. Sınav bitimi bildirimi

Döngü bittiğinde sunucuya bilgi gönder:
await ws.send(json.dumps({
"action": "exam_completed",
"student_id": student_id,
"session_token": token
}))

---

Özet — Öncelik Sırasıyla

┌─────────┬────────────────────────────────────────────────────────┬──────────┐
│ Öncelik │ Değişiklik │ Zorluk │
├─────────┼────────────────────────────────────────────────────────┼──────────┤
│ 1 │ Sınav seçimi kaldır (sunucu zaten yönetiyor) │ Kolay │
├─────────┼────────────────────────────────────────────────────────┼──────────┤
│ 2 │ IP'yi hardcode / config yap │ Kolay │
├─────────┼────────────────────────────────────────────────────────┼──────────┤
│ 3 │ Öğrenci ID'yi otomatik yap (config dosyası en pratiği) │ Kolay │
├─────────┼────────────────────────────────────────────────────────┼──────────┤
│ 4 │ Sınav bitimi sunucuya bildirim │ Kolay │
├─────────┼────────────────────────────────────────────────────────┼──────────┤
│ 5 │ Thread-safety düzeltmesi │ Orta │
├─────────┼────────────────────────────────────────────────────────┼──────────┤
│ 6 │ Violation_alert entegrasyonu (Ahmed'in modülü gelince) │ Bekliyor │
└─────────┴────────────────────────────────────────────────────────┴──────────┘
