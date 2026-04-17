# server_core.py
import asyncio
import websockets
import json
import time
import os     
from datetime import datetime
import school_service # Yeni Mock Servisimiz

from security_layer import open_secure_packet, verify_signature, hash_password, get_expected_server_token
from instructor_auth import verify_instructor_role

# Ahmet'in protokol modülleri
import protocol
import events

# Mert'in Veritabanı Modülü
import db_manager
db_manager.init_db()

# Örnek Oturma Düzeni (ŞUANLIK KULLANILMIYOR)
SEATING_PLAN = {
    "std_01": "127.0.0.1", # Lab bilgisayarı IP'si
    "std_02": "192.168.1.11"
}



# ---------------------------------------------------------
# EKLENDİ (ÖZELLİK 3): JSONL FORMATINDA DOSYAYA LOGLAMA
# ---------------------------------------------------------
def log_event(event_type, details):
    """Ahmet'in fikri: Olayları konsol haricinde kalıcı dosyaya kaydeder."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "details": details
    }
    with open("sinav_raporu_merkezi.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")
    db_manager.log_audit(event_type, "system", "", details, "OK")


async def broadcast_to_exam(exam_id, action, payload):
    """Küresel Komut Koordinasyonu: Belirli bir sınavdaki tüm aktif öğrencilere mesaj gönderir."""
    for sid, info in active_students.items():
        if info.get("exam_id") == exam_id and info.get("ws"):
            try:
                # Ahmet'in checksum'lı protokolüyle sarmalıyoruz
                event_name = getattr(events, action.upper(), action)
                msg = protocol.encode(event_name, payload)
                if isinstance(msg, dict): msg = json.dumps(msg)
                await info["ws"].send(msg)
            except Exception as e:
                print(f"⚠️ [SİSTEM] {sid} kullanıcısına mesaj gönderilemedi: {e}")
# 1) HAFIZA VE DURUM YÖNETİMİ
active_students = {}
exam_registry = {}
dashboard_counter = 0

# 2) ZAMANLAYICI (Global Timer)
async def global_timer():
    timer_tick = 0
    while True:
        await asyncio.sleep(1)
        timer_tick += 1
        
        if timer_tick % 5 == 0:
            db_manager.save_server_state(active_students, exam_registry)

        for sid, info in active_students.items():
            # DÜZELTME: Sınav bitmediği sürece (kopma/ihlal dahil) süre 1'er 1'er azalır
            if info["state"] != "completed":
                info["time_left"] -= 1
                
                # Her 60 saniyede bir BİREYSEL senkronizasyon (Sadece aktif olanlara)
                if info["state"] == "in_progress" and info["time_left"] > 0 and info["time_left"] % 60 == 0:
                    if info.get("ws"):
                        try:
                            event_name = getattr(events, "SYNC_TIME", "sync_time")
                            sync_msg = protocol.encode(event_name, {"time_left_seconds": info["time_left"]})
                            if isinstance(sync_msg, dict): sync_msg = json.dumps(sync_msg)
                            await info["ws"].send(sync_msg)
                        except: pass

                if info["time_left"] <= 0:
                    info["state"] = "completed"
                    print(f"\n✅ [BİTTİ] {sid} numaralı öğrencinin SÜRESİ DOLDU!")
                    log_event("exam_completed", {"student_id": sid})
                    
                    if info.get("ws"):
                        try:
                            event_name = getattr(events, "EXAM_END", "exam_end")
                            end_msg = protocol.encode(event_name, {})
                            if isinstance(end_msg, dict): end_msg = json.dumps(end_msg)
                            await info["ws"].send(end_msg)
                        except: pass

def _map_ahmet_to_internal(payload):
    """Ahmet'in PROCESS_CATCH formatını senin risk skorlama sistemine bağlar."""
    flags = payload.get("matches", payload.get("flags", []))
    return {
        "action": "status_update",
        "student_id": payload.get("student_id", ""),
        "session_token": payload.get("session_token"),
        "security": {
            "violation_alert": len(flags) > 0,
            "violation_type": flags[0] if flags else None,
            "details": {
                "active_window": payload.get("active_window", "Bilinmiyor"),
                "open_apps": payload.get("open_apps", []),
                "idle_seconds": payload.get("idle_seconds", -1)
            }
        }
    }

# 3) ANA İLETİŞİM FONKSİYONU
async def handle_client(websocket):
    global dashboard_counter, active_students, exam_registry
    try:
        async for message in websocket:
            raw_msg = json.loads(message)
            data = {}

            # --- KATMAN 1: NAZ'IN ŞİFRELİ PAKETİ GELDİYSE ÖNCE AÇ! ---
            if "encrypted" in raw_msg and "signature" in raw_msg:
                try:
                    data = open_secure_packet(message) 
                except Exception as e:
                    print(f"🚫 [SİBER GÜVENLİK] Geçersiz paket reddedildi! Sebep: {e}")
                    continue 
            else:
                data = raw_msg

            # --- KATMAN 2: AHMET'İN PROTOKOLÜ ---
            if "event" in data and "checksum" in data:
                event_name, payload = protocol.decode(json.dumps(data))
                
                if event_name == protocol.DECODE_ERROR:
                    print("⚠️ [PROTOKOL] Ahmet'in katmanı checksum hatası verdi!")
                    continue

                if event_name == getattr(events, "START_EXAM", "start_exam"):
                    action = "request_start_exam"
                    data = {**payload, "action": action}
                elif event_name == getattr(events, "PROCESS_CATCH", "process_catch"):
                    action = "status_update"
                    data = _map_ahmet_to_internal(payload)
                else:
                    action = data.get("action")
            else:
                # --- KATMAN 3: GERİYE UYUMLULUK ---
                action = data.get("action")

            student_id = data.get("student_id")

            # RATE LIMITING
            if student_id and student_id in active_students:
                now = time.time()
                if now - active_students[student_id].get("last_msg_time", 0) < 0.5:
                    continue 
                active_students[student_id]["last_msg_time"] = now

            if action == "register_exam": # EĞİTMENİN YENİ SINAV KAYIT KOMUTU
                #  FIX: Eğitmen Token Kontrolü (Doğru Kullanım)
                ok, err = verify_instructor_role(data, "register_exam")
                if not ok: 
                    print(f"🚫 [GÜVENLİK İHLALİ] Yetkisiz sınav oluşturma girişimi REDDEDİLDİ! Sebep: {err}")
                    await websocket.send(json.dumps({"status": "error", "message": f"Yetkisiz işlem! {err}"}))
                    continue

                exam_id = data["payload"]["exam_id"]
                exam_registry[exam_id] = data["payload"]
                db_manager.create_exam_session(exam_id, data["payload"])
                print(f"\n✅ [EĞİTMEN] Yeni Sınav Aktif Edildi: {exam_id}")
                log_event("exam_registered", {"exam_id": exam_id})
                await websocket.send(json.dumps({"status": "exam_registered"}))
            # --- OTURUM YÖNETİMİ AKSİYONLARI ---

            elif action == "start_all_students":
                # EĞİTMEN KOMUT KOORDİNASYONU
                ok, err = verify_instructor_role(data, "start_exam")
                if ok:
                    exam_id = data["payload"]["exam_id"]
                    # Sınava kayıtlı herkesi WAITING'den IN_PROGRESS'e çek
                    for sid, info in active_students.items():
                        if info["exam_id"] == exam_id and info["state"] == "waiting_for_start":
                            info["state"] = "in_progress"
                    
                    await broadcast_to_exam(exam_id, "exam_started_ack", {"status": "success"})
                    print(f"🚀 [SİSTEM] {exam_id} sınavı TÜM ÖĞRENCİLER için başlatıldı!")
            elif action == "resume_student":
                ok, err = verify_instructor_role(data, "resume_student")
                if not ok:
                    await websocket.send(json.dumps({"status": "error", "message": f"Yetkisiz işlem! {err}"}))
                    continue
                    
                hedef_id = data.get("student_id")
                if hedef_id in active_students:
                    active_students[hedef_id]["state"] = "in_progress"
                    
                    # DÜZELTME: Öğrencinin kilitli ekranını açması için sinyal gönder
                    target_ws = active_students[hedef_id].get("ws")
                    if target_ws:
                        try:
                            await target_ws.send(json.dumps({"action": "exam_resumed", "status": "success"}))
                        except: pass
                        
                    print(f"\n🟢 [EĞİTMEN KOMUTU] {hedef_id} affedildi ve kilit açma sinyali gönderildi.")
                    log_event("student_resumed", {"student_id": hedef_id})
                    await websocket.send(json.dumps({"status": "success", "message": f"{hedef_id} affedildi."}))

            elif action == "request_start_exam": # ÖĞRENCİNİN SINAVA GİRİŞ VE DOĞRULAMA TALEBİ
                student_id = data.get("student_id")
                password = data.get("password", "")
                exam_id = data.get("exam_id")

                # 1. ADIM: HOCANIN İSTEDİĞİ CATS/ORION DOĞRULAMASI
                success, name_or_err = school_service.verify_user(student_id, password)
                if not success:
                    await websocket.send(json.dumps({"status": "error", "message": f"CATS Hatası: {name_or_err}"}))
                    continue

                # 2. ADIM: GÜVENLİK VE İMZA KONTROLÜ (Engin & Naz)
                client_sig = data.pop("auth_signature", None)
                eski_surum_mu = False
                if client_sig:
                    msg_str = json.dumps(data, sort_keys=True)
                    if not verify_signature(msg_str, client_sig):
                        await websocket.send(json.dumps({"status": "error", "message": "Güvenlik İhlali: İmzalı Paket Hatası!"}))
                        continue
                else:
                    eski_surum_mu = True

                # 3. ADIM: OTURUM YÖNETİMİ VE CRASH RECOVERY
                session_token = get_expected_server_token(student_id)
                
                if student_id in active_students:
                    # Sunucu çöktüyse veya koptuysa geri bağla (CRASH RECOVERY)
                    if active_students[student_id].get("ws") is None:
                        active_students[student_id]["ws"] = websocket
                        # Eğer zaten in_progress ise direkt devam ettir, değilse bekleme odasına al
                        yeni_state = active_students[student_id]["state"] 
                        print(f"🔄 [RECOVERY] {student_id} oturumu kurtarıldı. Durum: {yeni_state}")
                        await websocket.send(json.dumps({
                            "action": "exam_started_ack", "status": "success", 
                            "session_token": session_token, "reconnected": True,
                            "time_left_seconds": active_students[student_id]["time_left"]
                        }))
                        continue

                # 4. ADIM: YENİ OTURUM OLUŞTURMA (Bekleme Odası)
                active_students[student_id] = {
                    "ws": websocket, "state": "waiting_for_start", "exam_id": exam_id,
                    "time_left": 2400, "session_token": session_token, "last_seq": 0,
                    "total_risk_score": 0, "login_name": name_or_err
                }
                
                print(f"🎓 [OTURUM] {name_or_err} ({student_id}) CATS üzerinden doğrulandı. BEKLEME ODASINA ALINDI.")
                log_event("student_authenticated", {"student_id": student_id, "name": name_or_err})
                
                await websocket.send(json.dumps({
                    "action": "auth_success", "status": "success", 
                    "message": f"Hoş geldin {name_or_err}. Eğitmen sınavı başlatana kadar lütfen bekleyiniz.",
                    "session_token": session_token,
                    "warning": "⚠️ DİKKAT: Eski sürüm istemci!" if eski_surum_mu else None
                }))

            elif action == "change_duration": # EĞİTMENİN SÜREYİ UZATMA KOMUTU
                ok, err = verify_instructor_role(data, "change_duration")
                if ok:
                    extra_mins = data["payload"].get("extra_minutes", 5)
                    target_exam = data["payload"].get("exam_id")
                    for sid, info in active_students.items():
                        if info["exam_id"] == target_exam:
                            info["time_left"] += (extra_mins * 60)
                    print(f"⏰ [EĞİTMEN] {target_exam} sınav süresi {extra_mins} dk uzatıldı.")
                    await broadcast_to_exam(target_exam, "duration_updated", {"added_minutes": extra_mins})

            elif action == "status_update":
                student_id = data.get("student_id")
                token = data.get("session_token")

                if student_id in active_students and active_students[student_id]["session_token"] == token:
                    security_data = data.get("security", {})
                    
                    # --- YENİ (ENGİN ENTEGRASYONU): Integrity Fields ---
                    seq_no = data.get("seq", 0)
                    session_id = data.get("session_id", "unknown")
                    is_buffered = data.get("buffered", False)
                    queued_at = data.get("queued_at", datetime.now().isoformat())
                    
                    # Sıra numarası takibi (opsiyonel: atlanan paket var mı kontrolü eklenebilir)
                    active_students[student_id]["last_seq"] = seq_no
                    active_students[student_id]["client_session_id"] = session_id
                    # ---------------------------------------------------

                    if security_data.get("violation_alert") == True:
                        active_students[student_id]["state"] = "violation_paused"
                        v_type = security_data.get("violation_type", "Bilinmeyen İhlal")
                        details = security_data.get("details", {})
                        aktif_pencere = details.get("active_window", "Bilinmiyor")
                        acik_uygulamalar = details.get("open_apps", [])
                        
                        mevcut_skor = active_students[student_id].get("total_risk_score", 0)
                        ek_skor = 0
                        high_risk_words = ["chatgpt", "discord", "whatsapp", "telegram", "gemini", "claude", "chegg", "stackoverflow"]
                        medium_risk_words = ["google", "bing", "brave", "search", "yandex"]
                        
                        tum_uygulamalar_str = (aktif_pencere + " " + " ".join(acik_uygulamalar)).lower()
                        for word in high_risk_words:
                            if word in tum_uygulamalar_str: ek_skor += 40
                        for word in medium_risk_words:
                            if word in tum_uygulamalar_str: ek_skor += 15
                                
                        yeni_skor = min(mevcut_skor + ek_skor, 100)
                        risk_level = "KRİTİK" if yeni_skor >= 80 else "YÜKSEK" if yeni_skor >= 40 else "ORTA" if yeni_skor > 0 else "DÜŞÜK"
                            
                        active_students[student_id]["total_risk_score"] = yeni_skor
                        active_students[student_id]["risk_level"] = risk_level
                        
                        # Gecikmiş paketler için asıl oluşturulma zamanını (queued_at) kullan
                        zaman = queued_at if is_buffered else datetime.now().isoformat()
                        
                        active_students[student_id]["last_violation"] = {
                            "type": v_type, "window": aktif_pencere, "time": zaman,
                            "risk_score": yeni_skor, "risk_level": risk_level,
                            "buffered": is_buffered # Loglarda gecikmeli paket olduğunu belirt
                        }
                        
                        log_event("violation_alert", {
                            "student_id": student_id, "score": yeni_skor, 
                            "level": risk_level, "type": v_type, "window": aktif_pencere,
                            "seq": seq_no, "buffered": is_buffered, "queued_at": queued_at
                        })
                        
                        # Konsol çıktısını güncelle
                        buffer_str = "[GECİKMELİ/BUFFERED PAKET] " if is_buffered else ""
                        print(f"\n🚨 [ALARM] {buffer_str}{student_id} ihlal yaptı! Sınav donduruldu.")
                        print(f"   ↳ 🧠 [ANALİZ] Güvenlik Skoru: %{yeni_skor} - Seviye: {risk_level}")
                        print(f"   ↳ Sebep: {v_type} | Pencere: {aktif_pencere}")
                        print(f"   ↳ Sıra No: {seq_no} | Oluşturulma: {queued_at}")
                        
                        # Mert'in veritabanı modülüne kopyayı yolla (Eksiksiz)
                        db_manager.save_violation_to_db(student_id, v_type, aktif_pencere, yeni_skor)
                        db_manager.record_monitoring_event(student_id, "VIOLATION", {
                            "type": v_type, "window": aktif_pencere,
                            "apps": acik_uygulamalar, "score": yeni_skor,
                            "seq": seq_no, "buffered": is_buffered, "session_id": session_id
                        }, "CRITICAL")
 
            elif action == "get_dashboard_data":
                dashboard_counter += 1
                formatted_students = {}
                for sid, info in active_students.items():
                    if info["state"] == "completed": continue
                    time_str = f"{info.get('time_left', 0)//60:02d}:{info.get('time_left', 0)%60:02d}"
                    formatted_students[sid] = {
                        "state": info["state"], "exam_id": info.get("exam_id"), 
                        "time_left_formatted": time_str, "risk_score": info.get("total_risk_score", 0),
                        "risk_level": info.get("risk_level", "TEMİZ")
                    }

                await websocket.send(json.dumps({
                    "action": "dashboard_update", "active_students_count": len(active_students), "students": formatted_students
                }))
                print(f"\r📊 [SİSTEM] Dashboard güncellendi. (İstek: {dashboard_counter})", end="", flush=True)

            
                
    except Exception as e:
        # Bağlantı zorla kesildiğinde çıkan gereksiz ağ hatalarını filtrele
        hata_str = str(e).lower()
        if "no close frame" not in hata_str and "connection is closed" not in hata_str:
            print(f"❌ [SİSTEM HATASI] Beklenmedik bir sorun oluştu: {e}")
    finally:
        for sid, info in active_students.items():
            if info["ws"] == websocket:
                info["ws"] = None
                if info["state"] == "in_progress":
                    info["state"] = "completed" if info.get("time_left", 1) <= 0 else "disconnected_paused"
                    log_event("student_disconnected", {"student_id": sid})
                    print(f"\n🔌 [KOPTU] Öğrenci {sid} hattan düştü. Durumu donduruldu.")
                db_manager.record_student_disconnect(sid)
                break