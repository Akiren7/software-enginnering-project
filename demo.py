import tkinter as tk
from tkinter import ttk
import asyncio
import threading
import time
import sys
import os

import socket
from tkinter import messagebox

# 1) Proje modüllerinin yolunu ekle (Aynı dizindelerse bile garantidir)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from network_sender import NetworkSender, DeliveryStatus
    from payload_builder import PayloadBuilder
    from auth_client import AuthClient
    import discovery
except ImportError as e:
    print(f"HATA: Modüller yüklenemedi! Lütfen demo.py'nin ana klasörde olduğundan emin ol. Detay: {e}")
    sys.exit(1)

# --- AĞ VE İZLEME MANTIĞI ---
def run_student_session(ip, student_id, password, exam_id, logger_callback):
    try:
        # Kimlik Doğrulama
        auth = AuthClient()
        auth_result = auth.authenticate(student_id, password)
        
        if not auth_result.success:
            logger_callback(f"❌ Kimlik Doğrulama Başarısız: {auth_result.error}")
            root.after(0, lambda: btn_giris.config(state="normal"))
            return

        # Konfigürasyonları ayarla
        import network_sender
        network_sender.SERVER_IP = ip 
        network_sender.STUDENT_ID = student_id
        network_sender.EXAM_ID = exam_id
        
        sender = NetworkSender(auth_result=auth_result)
        builder = PayloadBuilder(student_id, "Bekleniyor...")

        # Sunucuya Kayıt
        if not sender.register():
            logger_callback("❌ Sunucuya kayıt olunamadı. IP veya şifreyi kontrol edin.")
            root.after(0, lambda: btn_giris.config(state="normal"))
            return

        builder.student_name = getattr(sender, 'student_real_name', student_id)
        logger_callback(f"✅ Giriş Başarılı: {builder.student_name}")

        # Bekleme Odası
        if not sender.is_exam_active():
            logger_callback("⏳ Bekleme Odası: Eğitmenin sınavı başlatması bekleniyor...")
            sender.wait_for_exam_start()
            logger_callback("🚀 Sınav Başladı! İzleme aktif.")

        # İzleme Döngüsü
        kalp_atisi_sayaci = 0
        while sender.is_exam_active():
            payload = builder.build()
            status = sender.send_heartbeat(payload)
            
            # ÖĞRENCİDEN GİZLEME: Artık flag_str veya window ismini ekrana basmıyoruz!
            # Sadece her 10 döngüde bir (yaklaşık 50 saniye) sistemin çalıştığını belli eden ufak bir mesaj
            kalp_atisi_sayaci += 1
            if kalp_atisi_sayaci % 10 == 0:
                logger_callback("📡 Sistem aktif, bağlantı stabil...")
            
            if status == DeliveryStatus.BUFFERED:
                logger_callback(f"⚠️ İnternet bağlantınız zayıf, veriler kuyruğa alındı!")

            time.sleep(5)

        logger_callback("🛑 Sınav sona erdi.")
        sender.disconnect()
        root.after(0, lambda: btn_giris.config(state="normal"))

    except Exception as e:
        logger_callback(f"💥 Kritik Hata: {e}")
        root.after(0, lambda: btn_giris.config(state="normal"))

# --- ARAYÜZ (GUI) FONKSİYONLARI ---
def start_exam_thread():
    ip = ip_entry.get().strip()
    student_id = no_entry.get().strip()
    password = pass_entry.get().strip()
    # DÜZELTME BURADA: Artık sinav_combo değil, exam_entry kullanıyoruz
    exam_id = exam_entry.get().strip() 

    if not password:
        log_ekle("⚠️ Uyarı: Lütfen CATS şifrenizi giriniz!")
        return
    if not ip:
        log_ekle("⚠️ Uyarı: Lütfen Sunucu IP adresini giriniz!")
        return

    btn_giris.config(state="disabled")
    log_ekle(f"🌐 {ip} adresine bağlanılıyor...")
    
    threading.Thread(
        target=run_student_session, 
        args=(ip, student_id, password, exam_id, log_ekle), 
        daemon=True
    ).start()

    
def log_ekle(mesaj):
    root.after(0, lambda: _unsafe_log_ekle(mesaj))

def _unsafe_log_ekle(mesaj):
    log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {mesaj}\n")
    log_text.see(tk.END)

# --- OTOMATİK SUNUCU BULMA (AUTO-DISCOVERY) ---
# --- OTOMATİK SUNUCU BULMA (AUTO-DISCOVERY) ---
def start_discovery():
    log_ekle("🔍 Ağdaki sınav sunucuları aranıyor (6 sn)...")
    
    def run_async_discovery():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # DÜZELTME: Timeout 6.0 saniyeye çıkarıldı ki en az 2 sinyal aralığını kapsasın
            found = loop.run_until_complete(discovery.discover_server(timeout=6.0, bind_host="0.0.0.0"))
            if found:
                root.after(0, update_ip_entry, found[0])
                root.after(0, log_ekle, f"✨ Sunucu otomatik bulundu: {found[0]}")
            else:
                root.after(0, log_ekle, "❌ Otomatik bulma başarısız, IP'yi manuel girin.")
        except Exception as e:
            root.after(0, log_ekle, f"Hata: IP Bulucu çalışamadı ({e})")
        finally:
            loop.close()
            
    threading.Thread(target=run_async_discovery, daemon=True).start()

def update_ip_entry(ip_address):
    ip_entry.delete(0, tk.END)
    ip_entry.insert(0, ip_address)



# --- TEKİL OTURUM KİLİDİ (ÇİFT AÇILMAYI ENGELLER) ---
def check_single_instance():
    try:
        # Sadece bu uygulamaya özel rastgele bir port (Örn: 60064)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 60064))
        return s
    except socket.error:
        return None

app_lock = check_single_instance()
if not app_lock:
    # Tkinter ana penceresi açılmadan gizli bir uyarı ver ve çık
    root = tk.Tk()
    root.withdraw() 
    messagebox.showerror("Hata", "Sınav uygulaması şu anda zaten açık! Lütfen açık olan pencereyi bulun.")
    sys.exit(0)

# --- GÖRSEL ARAYÜZ TASARIMI (TKINTER) ---
root = tk.Tk()
root.title("İKÜ Sınav Sistemi - Öğrenci")

# 2. MADDE: Pencereyi Yatay Genişlet (Eskisi 480x600 idi, şimdi 700x600 yaptık)
root.geometry("700x600") 
root.configure(bg="#f0f0f0")

tk.Label(root, text="LABORATUVAR SINAV SİSTEMİ", font=("Arial", 14, "bold"), bg="#f0f0f0").pack(pady=15)

# IP Adresi
tk.Label(root, text="Sunucu IP Adresi:", bg="#f0f0f0").pack()
ip_entry = tk.Entry(root, font=("Arial", 12), justify="center")
ip_entry.pack(pady=5)

# Öğrenci Numarası
tk.Label(root, text="Öğrenci Numarası (CATS ID):", bg="#f0f0f0").pack()
no_entry = tk.Entry(root, font=("Arial", 12), justify="center")
no_entry.insert(0, "2300005352") # Kendi numaran
no_entry.pack(pady=5)

# CATS Şifresi
tk.Label(root, text="CATS Şifresi:", bg="#f0f0f0").pack()
pass_entry = tk.Entry(root, font=("Arial", 12), justify="center", show="*")
pass_entry.pack(pady=5)

# Sınav Seçimi
# Sınav Seçimi (demo.py içindeki eski Combobox kısmını silip bunu yapıştır)
tk.Label(root, text="Sınav Adı (Hocanın Tahtaya Yazdığı):", bg="#f0f0f0").pack()
exam_entry = tk.Entry(root, font=("Arial", 12), justify="center")
exam_entry.insert(0, "LAB_1_VIZE") # Varsayılan isim
exam_entry.pack(pady=5)

# start_exam_thread içindeki exam_id = sinav_combo.get() kısmını da şöyle düzelt:
# exam_id = exam_entry.get().strip()
# Giriş Butonu
btn_giris = tk.Button(root, text="Sınava Giriş Yap", font=("Arial", 12, "bold"), bg="#4CAF50", fg="white", command=start_exam_thread)
btn_giris.pack(pady=15)

# Log Ekranı
log_text = tk.Text(root, height=12, width=55, font=("Consolas", 9))
log_text.pack(pady=10)

# UYGULAMA AÇILDIKTAN 1 SANİYE SONRA OTOMATİK TARAMA BAŞLAT
root.after(1000, start_discovery)

root.mainloop()