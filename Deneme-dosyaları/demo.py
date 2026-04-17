import tkinter as tk
from tkinter import ttk
import asyncio
import websockets
import json
import threading

# --- ARKA PLAN AĞ İŞLEMLERİ ---
async def network_task(ip, student_id, password, exam_id):
    uri = f"ws://{ip}:8765"
    try:
        async with websockets.connect(uri) as ws:
            # 1. Sınav Başlatma İsteği (Yeni: Şifre eklendi)
            await ws.send(json.dumps({
                "action": "request_start_exam",
                "student_id": student_id,
                "password": password,  # CATS şifresi sunucuya gidiyor
                "exam_id": exam_id
            }))

            # 2. Sunucudan CATS Doğrulama Cevabını Al
            response_text = await ws.recv()
            response = json.loads(response_text)

            # Hata Kontrolü (Yanlış şifre vb.)
            if response.get("status") == "error":
                log_ekle(f"❌ HATA: {response.get('message')}")
                btn_giris.config(state="normal")
                return

            # 3. Başarılı Giriş ve Bekleme Odası (Session Manager Uyumu)
            token = response.get("session_token")
            time_left = 2400 # Varsayılan 40 dakika
            
            if response.get("reconnected") == True:
                time_left = response.get("time_left_seconds", 2400)
                log_ekle(f"🔄 Kaldığınız yerden devam ediliyor: {time_left} sn")
            else:
                # Eğitmenin başlatmasını bekle
                log_ekle(f"✅ Doğrulandı: {response.get('message', 'Bekleme odasındasınız.')}")
                log_ekle("⏳ Eğitmenin sınavı başlatması bekleniyor...")
                
                while True:
                    msg_text = await ws.recv()
                    # Ahmet'in protokolü veya standart JSON gelme ihtimaline karşı kontrol
                    if "exam_started_ack" in msg_text or "start_exam" in msg_text:
                        log_ekle("🚀 Eğitmen sınavı başlattı!")
                        break

            # 4. Süre Sayacı ve Sunucuya Bildirim (Heartbeat)
            while time_left > 0:
                await asyncio.sleep(2)
                time_left -= 2
                
                # Engin'in uyumlu olduğu formatta basit heartbeat
                await ws.send(json.dumps({
                    "action": "status_update",
                    "student_id": student_id,
                    "session_token": token,
                    "seq": 1, # Demo için sabit
                    "buffered": False,
                    "security": {"violation_alert": False}
                }))
                
                # Saniyeyi aynı satırda güncellemek için metin kutusunun son satırını değiştiriyoruz
                log_text.delete("end-2l", "end-1c") 
                log_ekle(f"⏱ Kalan Süre: {time_left} sn")

            log_ekle("🛑 Sınav süresi bitti!")
            
    except Exception as e:
        log_ekle(f"❌ Bağlantı Koptu: {e}")
        btn_giris.config(state="normal")

# Butona basıldığında arayüz donmasın diye ağ işlemini ayrı bir thread'de (iş parçacığı) başlatıyoruz
def start_exam_thread():
    ip = ip_entry.get()
    student_id = no_entry.get()
    password = pass_entry.get()
    exam_id = sinav_combo.get()

    if not password:
        log_ekle("⚠️ Uyarı: Lütfen CATS şifrenizi giriniz!")
        return

    btn_giris.config(state="disabled") # Çift tıklamayı önle
    log_ekle(f"🌐 {ip} adresine bağlanılıyor...")
    
    threading.Thread(target=lambda: asyncio.run(network_task(ip, student_id, password, exam_id)), daemon=True).start()

def log_ekle(mesaj):
    log_text.insert(tk.END, mesaj + "\n")
    log_text.see(tk.END) # Otomatik en aşağı kaydır

# --- GÖRSEL ARAYÜZ (GUI) TASARIMI ---
root = tk.Tk()
root.title("Öğrenci Sınav Giriş Terminali")
root.geometry("400x530") # Şifre kutusu için pencere boyutu biraz büyütüldü
root.configure(bg="#f0f0f0")

tk.Label(root, text="LABORATUVAR SINAV SİSTEMİ", font=("Arial", 14, "bold"), bg="#f0f0f0").pack(pady=15)

# IP Adresi Girişi
tk.Label(root, text="Sunucu IP Adresi:", bg="#f0f0f0").pack()
ip_entry = tk.Entry(root, font=("Arial", 12), justify="center")
ip_entry.insert(0, "127.0.0.1") # Test için localhost yapıldı
ip_entry.pack(pady=5)

# Öğrenci Numarası Girişi
tk.Label(root, text="Öğrenci Numarası (CATS ID):", bg="#f0f0f0").pack()
no_entry = tk.Entry(root, font=("Arial", 12), justify="center")
no_entry.insert(0, "2300005352")
no_entry.pack(pady=5)

# CATS Şifresi Girişi (YENİ EKLENDİ)
tk.Label(root, text="CATS Şifresi:", bg="#f0f0f0").pack()
pass_entry = tk.Entry(root, font=("Arial", 12), justify="center", show="*") # show="*" şifreyi gizler
pass_entry.pack(pady=5)

# Sınav Seçimi (Açılır Menü)
tk.Label(root, text="Sınav Seçimi:", bg="#f0f0f0").pack()
sinav_combo = ttk.Combobox(root, values=["Applied Deep Learning", "Operating Systems", "CS301_Database"], font=("Arial", 11), state="readonly")
sinav_combo.current(0)
sinav_combo.pack(pady=5)

# Giriş Butonu
btn_giris = tk.Button(root, text="SINAVA GİRİŞ YAP", command=start_exam_thread, bg="#4CAF50", fg="white", font=("Arial", 12, "bold"), width=20)
btn_giris.pack(pady=15)

# Log / Bilgi Ekranı
log_text = tk.Text(root, height=10, width=45, font=("Consolas", 10), bg="black", fg="lime")
log_text.pack(pady=5)
log_ekle("Sistem hazır. Bilgileri girip bağlanın.")

root.mainloop()