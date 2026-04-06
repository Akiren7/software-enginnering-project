# db_manager.py
import json
import os

# Mert gerçek veritabanını bağlayana kadar kullanılacak geçici (sanal) veritabanı dosyası
DB_FILE = "server_recovery_db.json"

def save_server_state(active_students, exam_registry):
    """
    Sunucunun anlık hafızasını veritabanına kaydeder (Snapshot).
    WebSocket (ws) gibi canlı ağ objeleri veritabanına yazılamayacağı için filtrelenir.
    """
    safe_students = {}
    for sid, info in active_students.items():
        safe_info = info.copy()
        safe_info.pop("ws", None) # Canlı ağ bağlantısını RAM'den ayırıp DB'ye yazıyoruz
        safe_students[sid] = safe_info
    
    state = {
        "active_students": safe_students,
        "exam_registry": exam_registry
    }
    
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def load_server_state():
    """
    Sunucu başlatıldığında veya çöktüğünde veritabanındaki son durumu RAM'e yükler.
    """
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ [DB HATASI] Veritabanı okunamadı: {e}")
    return None

def save_violation_to_db(student_id, violation_type, window_name, new_score):
    """
    MERT İÇİN PLACEHOLDER: 
    Öğrenci kopya çektiğinde bu fonksiyon tetiklenir. 
    Mert buraya 'INSERT INTO violations...' SQL sorgularını yazacak.
    """
    # Şimdilik sadece Mert'in sisteminin çalıştığını simüle ediyoruz
    pass