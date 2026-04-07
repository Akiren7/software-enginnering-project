# server_core.py
import asyncio
import websockets
import json
import time
import os     
from datetime import datetime

from security_layer import open_secure_packet, verify_signature, hash_password, get_expected_server_token
from instructor_auth import verify_instructor_role

# Ahmet'in protokol modülleri
import protocol
import events

# Mert'in Veritabanı Modülü
import db_manager
db_manager.init_db()

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

# 1) HAFIZA VE DURUM YÖNETİMİ
active_students = {}
exam_registry = {}
dashboard_counter = 0

# 2) ZAMANLAYICI (Global Timer)
async def global_timer():
    timer_tick = 0
    while True:
        await asyncio.sleep(1) # Her 1 saniyede bir tetiklenir
        timer_tick += 1
        
        # EKLENDİ (MERT DB): Her 5 saniyede bir tüm sunucu hafızasını veritabanına yedekle (Crash Recovery)
        if timer_tick % 5 == 0:
            db_manager.save_server_state(active_students, exam_registry)

        for sid, info in active_students.items():
            if info["state"] == "in_progress":
                info["time_left"] -= 1 
                
                # EKLENDİ (ÖZELLİK 1a): Her 60 saniyede bir öğrenciye zamanı senkronize et (sync_time)
                if info["time_left"] > 0 and info["time_left"] % 60 == 0:
                    if info.get("ws"):
                        try:
                            # QWEN FIX: Ahmet'in checksum'lı protokolüyle gönderiyoruz
                            event_name = getattr(events, "SYNC_TIME", "sync_time")
                            sync_msg = protocol.encode(event_name, {"time_left_seconds": info["time_left"]})
                            if isinstance(sync_msg, dict): sync_msg = json.dumps(sync_msg)
                            await info["ws"].send(sync_msg)
                        except Exception as e:
                            pass

                if info["time_left"] <= 0:
                    info["state"] = "completed"
                    print(f"\n✅ [BİTTİ] {sid} numaralı öğrencinin SÜRESİ DOLDU!")
                    log_event("exam_completed", {"student_id": sid})
                    
                    # EKLENDİ (ÖZELLİK 1b): Süre bitince öğrencinin ekranını kitlemek için exam_end at
                    if info.get("ws"):
                        try:
                            # QWEN FIX: Ahmet'in checksum'lı protokolüyle gönderiyoruz
                            event_name = getattr(events, "EXAM_END", "exam_end")
                            end_msg = protocol.encode(event_name, {})
                            if isinstance(end_msg, dict): end_msg = json.dumps(end_msg)
                            await info["ws"].send(end_msg)
                        except Exception as e:
                            pass

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

            elif action == "resume_student": # EĞİTMENİN KOPAN ÖĞRENCİYİ AFFETME KOMUTU
                #   FIX: Eğitmen Token Kontrolü (Doğru Kullanım)
                ok, err = verify_instructor_role(data, "resume_student")
                if not ok:
                    print(f"🚫 [GÜVENLİK İHLALİ] Öğrenci affetme yetkisi reddedildi! Sebep: {err}")
                    await websocket.send(json.dumps({"status": "error", "message": f"Sınava devam etmek için gözetmen onayı gereklidir! {err}"}))
                    continue
                    
                hedef_id = data.get("student_id")
                if hedef_id in active_students:
                    active_students[hedef_id]["state"] = "in_progress"
                    print(f"\n🟢 [EĞİTMEN KOMUTU] {hedef_id} numaralı öğrenci affedildi ve DEVAM ETTİRİLDİ.")
                    log_event("student_resumed", {"student_id": hedef_id})

            elif action == "request_start_exam": # ÖĞRENCİNİN SINAVA BAŞLAMA TALEBİ

                # --- GERİ EKLENDİ: ESKİ SÜRÜM KONTROLÜ ---
                eski_surum_mu = False
                client_sig = data.pop("auth_signature", None)
                if client_sig:
                    msg_str = json.dumps(data, sort_keys=True)
                    if not verify_signature(msg_str, client_sig):
                        await websocket.send(json.dumps({"status": "error", "message": "Güvenlik İhlali: Mesaj İmzası Geçersiz!"}))
                        continue
                else:
                    print("\n⚠️ [UYARI] Eski sürüm bir istemci bağlanıyor (İmza Yok). Güvenlik seviyesi: DÜŞÜK")
                    eski_surum_mu = True
                # ----------------------------------------

                client_sig = data.pop("auth_signature", None)
                if client_sig:
                    msg_str = json.dumps(data, sort_keys=True)
                    if not verify_signature(msg_str, client_sig):
                        await websocket.send(json.dumps({"status": "error", "message": "Güvenlik İhlali: Mesaj İmzası Geçersiz!"}))
                        continue
                
                login_id = data.get("login_id", "")
                gelen_sifre = data.get("password", "")
                gelen_hash = data.get("password_hash", "")
                credential_sig = data.get("credential_sig", "")

                if login_id and gelen_hash and credential_sig:
                    beklenen_imza_metni = f"{login_id}:{gelen_hash}"
                    if not verify_signature(beklenen_imza_metni, credential_sig):
                        await websocket.send(json.dumps({"status": "error", "message": "Güvenlik İhlali: Kimlik İmzası Geçersiz!"}))
                        continue
                if gelen_sifre and gelen_hash:
                    if hash_password(gelen_sifre) != gelen_hash:
                        await websocket.send(json.dumps({"status": "error", "message": "Hatalı Şifre!"}))
                        continue

                student_id = data["student_id"]
                exam_id = data["exam_id"]
                
                if student_id in active_students:
                    mevcut_durum = active_students[student_id]["state"]
                    mevcut_sinav = active_students[student_id]["exam_id"]

                    if mevcut_durum == "in_progress":
                        #  CRASH RECOVERY: Sunucu çöktüyse ws None olur, öğrenciyi kurtar!
                        if active_students[student_id].get("ws") is None:
                            active_students[student_id]["ws"] = websocket
                            print(f"\n🔄 [CRASH RECOVERY] Sunucu çökmesi sonrası {student_id} başarıyla kurtarıldı!")
                            log_event("crash_recovery_reconnect", {"student_id": student_id})
                            await websocket.send(json.dumps({
                            "action": "exam_started_ack", "status": "success", 
                            "session_token": active_students[student_id]["session_token"],
                            "reconnected": True, "time_left_seconds": active_students[student_id]["time_left"],
                            # YENİ EKLENEN SATIR
                            "warning": "⚠️ DİKKAT: Eski sürüm (şifresiz) bir istemci kullanıyorsunuz!" if eski_surum_mu else None
                        }))
                            continue
                        else:
                            await websocket.send(json.dumps({"status": "error", "message": f"HATA: Zaten '{mevcut_sinav}' sınavındasınız!"}))
                            continue
                    
                    elif mevcut_durum in ["disconnected_paused", "violation_paused"] and mevcut_sinav != exam_id:
                        await websocket.send(json.dumps({"status": "error", "message": f"HATA: Önce '{mevcut_sinav}' sınavını bitirmelisiniz!"}))
                        continue

                    elif mevcut_durum == "disconnected_paused" and mevcut_sinav == exam_id:
                        active_students[student_id]["ws"] = websocket
                        active_students[student_id]["state"] = "in_progress"
                        print(f"\n🔄 [BİLGİ] {student_id} bağlantısı koptuğu yerden tekrar içeri alındı!")
                        log_event("student_reconnected", {"student_id": student_id})
                        await websocket.send(json.dumps({
                            "action": "exam_started_ack", "status": "success", "session_token": active_students[student_id]["session_token"],
                            "reconnected": True, "time_left_seconds": active_students[student_id]["time_left"]
                        }))
                        continue
                        
                    elif mevcut_durum == "violation_paused" and mevcut_sinav == exam_id:
                        active_students[student_id]["ws"] = websocket 
                        print(f"\n🚫 [GÜVENLİK] {student_id} ihlalden dondurulduğu için yeniden bağlanma isteği REDDEDİLDİ.")
                        await websocket.send(json.dumps({"status": "error", "message": "Sınavınız güvenlik ihlali sebebiyle durdurulmuştur."}))
                        continue
                
                duration_mins = 40
                session_token = get_expected_server_token(student_id)

                active_students[student_id] = {
                    "ws": websocket, "state": "in_progress", "session_token": session_token,
                    "exam_id": exam_id, "time_left": duration_mins * 60,
                    "login_id": login_id, "password_hash": gelen_hash, "credential_sig": credential_sig
                }
                db_manager.record_student_connection(student_id, exam_id, session_token, login_id)

                log_event("exam_started", {"student_id": student_id, "exam_id": exam_id})
                log_event("exam_started", {"student_id": student_id, "exam_id": exam_id})
                await websocket.send(json.dumps({
                    "action": "exam_started_ack", "status": "success", "session_token": session_token,
                    "reconnected": False, "total_duration_minutes": duration_mins,
                    # YENİ EKLENEN SATIR
                    "warning": "⚠️ DİKKAT: Eski sürüm (şifresiz) bir istemci kullanıyorsunuz!" if eski_surum_mu else None
                }))

            elif action == "status_update":
                student_id = data.get("student_id")
                token = data.get("session_token")

                if student_id in active_students and active_students[student_id]["session_token"] == token:
                    security_data = data.get("security", {})
                    
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
                        zaman = datetime.now().isoformat()
                        
                        active_students[student_id]["last_violation"] = {
                            "type": v_type, "window": aktif_pencere, "time": zaman,
                            "risk_score": yeni_skor, "risk_level": risk_level
                        }
                        
                        log_event("violation_alert", {
                            "student_id": student_id, "score": yeni_skor, 
                            "level": risk_level, "type": v_type, "window": aktif_pencere
                        })
                        
                        # ESKİ DETAYLI GÖRÜNÜMÜ GERİ GETİRİYORUZ
                        print(f"\n🚨 [ALARM] {student_id} ihlal yaptı! Sınav donduruldu.")
                        print(f"   ↳ 🧠 [ANALİZ] Güvenlik Skoru: %{yeni_skor} - Seviye: {risk_level}")
                        print(f"   ↳ Sebep: {v_type} | Pencere: {aktif_pencere}")
                        print(f"   ↳ Arka Plan: {', '.join(acik_uygulamalar)}")
                        
                        # Mert'in veritabanı modülüne kopyayı (violation) yolla
                        db_manager.save_violation_to_db(student_id, v_type, aktif_pencere, yeni_skor)
                        db_manager.record_monitoring_event(student_id, "VIOLATION", {
                            "type": v_type, "window": aktif_pencere,
                            "apps": acik_uygulamalar, "score": yeni_skor
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