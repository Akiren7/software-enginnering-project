# school_service.py
import requests
from bs4 import BeautifulSoup

def verify_user(student_id, password):
    """
    CATS Web Scraping ile Canlı Kimlik Doğrulama.
    Okulun resmi giriş sayfasına arka planda istek atar ve HTML'i parçalar.
    """
    login_url = "https://cats.iku.edu.tr/portal/relogin" 
    
    # Senin bulduğun HTML 'name' değerleri (Kullanıcı adı ve Şifre)
    payload = {
        'eid': student_id,      
        'pw': password,         
        'submit': 'Giriş'       
    }
    
    try:
        # Oturum (Session) başlatıyoruz
        session = requests.Session()
        
        # Sunucuya giriş isteği (POST) atıyoruz
        response = session.post(login_url, data=payload, timeout=8)
        
        # HTML'i parçalıyoruz (Mert'in yöntemi)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Senin bulduğun spesifik div class'ını arıyoruz
        name_div = soup.find("div", {"class": "Mrphs-userNav__submenuitem--fullname"})
        id_div = soup.find("div", {"class": "Mrphs-userNav__submenuitem--displayid"})
        
        # Eğer bu div sayfada varsa, öğrenci başarıyla giriş yapmış demektir!
        if name_div:
            # HTML etiketlerinin içindeki metni (Barış Bağbekleyen) alıp boşlukları temizliyoruz
            user_name = name_div.text.strip()
            
            # Ekstra Güvenlik: Giren kişinin ID'si ile bizim student_id uyuşuyor mu?
            scraped_id = id_div.text.strip() if id_div else ""
            if scraped_id and scraped_id != student_id:
                return False, "Güvenlik İhlali: Başka bir kullanıcının hesabı ile giriş yapılamaz!"
                
            return True, user_name
        else:
            # Eğer o div yoksa (örneğin hala login sayfasındaysa) giriş başarısızdır
            return False, "Hatalı şifre veya numara! Lütfen CATS bilgilerinizi kontrol edin."
            
    except requests.exceptions.RequestException:
        # İnternet kopuksa veya okulun sitesi cevap vermiyorsa
        return False, "Okul sunucusuna bağlanılamadı. Lütfen internet bağlantınızı kontrol edin."
    
# Test amaçlı çalıştırma
# --- DOSYANIN EN ALTINA EKLENECEK TEST BLOĞU ---
if __name__ == "__main__":
    # Test için kendi okul bilgilerini gir
    test_id = "2300005352" 
    test_pw = "BURAYA_GERCEK_SIFRENI_YAZ" # Kendi CATS şifren

    print(f"[{test_id}] numarası ile CATS sistemine bağlanılıyor, lütfen bekleyin...")
    basarili_mi, sonuc_mesaji = verify_user(test_id, test_pw)

    if basarili_mi:
        print(f"✅ HARİKA! Giriş Başarılı. Çekilen İsim: {sonuc_mesaji}")
    else:
        print(f"❌ BAŞARISIZ! Sunucu Cevabı: {sonuc_mesaji}")