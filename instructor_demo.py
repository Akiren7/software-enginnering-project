import tkinter as tk
from tkinter import ttk, messagebox
import asyncio, websockets, json, threading, time

from instructor_auth import InstructorAuth

SERVER_URI = "ws://127.0.0.1:8765"
auth = InstructorAuth()
auth_result = None
ws_conn = None
network_loop = None  # YENİ: Ağ döngüsünü hafızada tutacağız

STATUS_MAP = {
    "waiting_for_start": "Beklemede",
    "in_progress": "Sınavda",
    "disconnected_paused": "Koptu (Süre Durdu)",
    "İhlal Yaptı - Donduruldu": "İHLAL: DURDURULDU",
    "completed": "Tamamladı"
}

async def instructor_network_loop():
    global ws_conn, network_loop
    network_loop = asyncio.get_running_loop() # YENİ: Çalışan asenkron döngüyü kaydet
    
    try:
        async with websockets.connect(SERVER_URI) as ws:
            ws_conn = ws
            log_ekle("✅ Sunucuya bağlantı sağlandı.")
            while True:
                if auth_result and auth_result.success:
                    try:
                        req_packet = auth.build_action_packet(auth_result, "get_dashboard_data")
                        await ws.send(req_packet)
                    except Exception:
                        pass
                
                try:
                    resp = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(resp)
                    if data.get("action") == "dashboard_update":
                        root.after(0, update_dashboard_table, data.get("students", {}))
                except asyncio.TimeoutError:
                    continue
    except Exception as e: 
        log_ekle(f"❌ Bağlantı koptu: {e}")

def login_instructor():
    global auth_result
    auth_result = auth.authenticate("admin1", "admin_pass", role="admin")
    if auth_result.success:
        log_ekle("🔓 Eğitmen girişi başarılı. Sistem hazır.")
        # Ağ dinleyicisini başlat
        threading.Thread(target=lambda: asyncio.run(instructor_network_loop()), daemon=True).start()
    else:
        messagebox.showerror("Yetki Hatası", "Eğitmen girişi başarısız!")

def register_and_start_exam():
    # EKRANDAN SINAV ADINI AL (Örn: LAB_1_VIZE)
    exam_id = entry_exam_name.get().strip()
    if not exam_id: 
        return messagebox.showwarning("Hata", "Sınav adı boş olamaz!")
    
    # PAYLOAD'U OLUŞTUR
    payload = {
        "exam_id": exam_id,
        "name": exam_id,
        "duration_minutes": 40,
        "allowed_apps": ["pythonw", "python"]
    }
    
    async def send_cmds():
        try:
            # Sınavı Kaydet
            reg_pkt = auth.build_register_exam_packet(auth_result, payload)
            await ws_conn.send(reg_pkt)
            root.after(0, log_ekle, f"📝 {exam_id} sunucuya kaydedildi.")
            
            await asyncio.sleep(1)
            
            # Sınavı Başlat
            start_pkt = auth.build_action_packet(auth_result, "start_exam", {"payload": {"exam_id": exam_id}})
            await ws_conn.send(start_pkt)
            root.after(0, log_ekle, f"🚀 {exam_id} BAŞLATILDI! Öğrenciler oturuma alınıyor.")
        except Exception as e:
            root.after(0, log_ekle, f"❌ Gönderim hatası: {e}")
        
    # Ağ döngüsüne komutu gönder
    asyncio.run_coroutine_threadsafe(send_cmds(), network_loop)

def update_dashboard_table(students_data):
    current_ids = {tree.set(k, "No"): k for k in tree.get_children()}
    incoming_ids = set(students_data.keys())
    
    for k in list(tree.get_children()):
        if tree.set(k, "No") not in incoming_ids:
            tree.delete(k)

    for sid, info in students_data.items():
        status_text = STATUS_MAP.get(info.get("state"), info.get("state"))
        skor = info.get('risk_score', 0)
        seviye = info.get("risk_level", "TEMİZ")
        
        values = (sid, info.get("exam_id", "-"), status_text, 
                  info.get("time_left_formatted", "00:00"), f"%{skor}", 
                  seviye, info.get("last_window", "Bilinmiyor"))
        
        tag = "high_risk" if skor > 50 else "clean"
        
        if sid in current_ids:
            tree.item(current_ids[sid], values=values, tags=(tag,))
        else:
            tree.insert("", "end", values=values, tags=(tag,))

# --- ÖĞRENCİ DETAY PENCERESİ ---
def on_item_double_click(event):
    if not tree.selection(): return
    item = tree.selection()[0]
    student_info = tree.item(item, "values")
    
    detail_win = tk.Toplevel(root)
    detail_win.title(f"Detay: {student_info[0]}")
    detail_win.geometry("400x300")
    detail_win.configure(bg="#f4f4f4")
    
    tk.Label(detail_win, text=f"Öğrenci: {student_info[0]}", font=("Arial", 14, "bold"), bg="#f4f4f4").pack(pady=15)
    tk.Label(detail_win, text=f"Durum: {student_info[2]}", font=("Arial", 11), bg="#f4f4f4").pack(pady=5)
    tk.Label(detail_win, text=f"Son Tespit Edilen Pencere:\n{student_info[6]}", fg="red", font=("Arial", 10, "bold"), bg="#f4f4f4").pack(pady=10)
    tk.Label(detail_win, text=f"Risk Seviyesi: {student_info[5]} ({student_info[4]})", font=("Arial", 11), bg="#f4f4f4").pack(pady=5)
    
    tk.Button(detail_win, text="Sınava Devam Ettir (Affet)", font=("Arial", 11, "bold"), bg="#27ae60", fg="white",
              command=lambda: send_resume(student_info[0], detail_win)).pack(pady=20)

def send_resume(sid, win):
    if not ws_conn or not auth_result or not network_loop: return
    
    async def send_res():
        try:
            pkt = auth.build_action_packet(auth_result, "resume_student", {"student_id": sid})
            await ws_conn.send(pkt)
            root.after(0, log_ekle, f"🟢 {sid} affedildi ve devam ettirildi.")
        except Exception as e:
            root.after(0, log_ekle, f"❌ Hata: {e}")
            
    # Aynı şekilde affetme komutunu da ağ döngüsüne gönderiyoruz
    asyncio.run_coroutine_threadsafe(send_res(), network_loop)
    win.destroy()

def log_ekle(mesaj):
    listbox_log.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {mesaj}")
    listbox_log.yview(tk.END)


# GUI Kurulumu
root = tk.Tk()
root.title("İKÜ Eğitici Dashboard")
root.geometry("1000x650")
root.configure(bg="#2c3e50")

style = ttk.Style()
style.theme_use('default')
style.configure("TNotebook", background="#2c3e50")

notebook = ttk.Notebook(root)
notebook.pack(expand=True, fill="both", padx=10, pady=10)

# --- 1. SEKME: SINAV YÖNETİMİ ---
# --- 1. SEKME: SINAV YÖNETİMİ (Lokal Lab Modeli) ---
tab_manage = tk.Frame(notebook, bg="#ecf0f1")
notebook.add(tab_manage, text="📚 Lab Sınav Yönetimi")

tk.Label(tab_manage, text="Bu laboratuvardaki sınavın adını belirleyin.", font=("Arial", 11), bg="#ecf0f1").pack(pady=10)

tk.Label(tab_manage, text="Sınav Adı (Örn: LAB_1_VIZE):", font=("Arial", 12, "bold"), bg="#ecf0f1").pack(pady=(10,5))
entry_exam_name = tk.Entry(tab_manage, font=("Arial", 14), justify="center")
entry_exam_name.insert(0, "LAB_1_VIZE")
entry_exam_name.pack(pady=5)

btn_start = tk.Button(tab_manage, text="Sınavı Kaydet ve Başlat", bg="#27ae60", fg="white", font=("Arial", 12, "bold"), padx=20, pady=10, command=register_and_start_exam)
btn_start.pack(pady=30)

listbox_log = tk.Listbox(tab_manage, width=90, height=12, bg="#1e272e", fg="#00d8d6", font=("Consolas", 11))
listbox_log.pack(pady=10)

# --- 2. SEKME: CANLI İZLEME ---
tab_monitor = tk.Frame(notebook, bg="#ecf0f1")
notebook.add(tab_monitor, text="👁️ Canlı Öğrenci Takibi")

cols = ("No", "Sınav", "Durum", "Süre", "Risk", "Seviye", "Pencere")
tree = ttk.Treeview(tab_monitor, columns=cols, show="headings", height=20)
for c in cols: 
    tree.heading(c, text=c)
    if c == "Pencere":
        tree.column(c, width=250, anchor="w")
    else:
        tree.column(c, width=100, anchor="center")

tree.tag_configure("high_risk", background="#ffcccc", foreground="red")
tree.tag_configure("clean", background="white")

tree.bind("<Double-1>", on_item_double_click)
tree.pack(expand=True, fill="both", padx=20, pady=20)

root.after(500, login_instructor)
root.mainloop()