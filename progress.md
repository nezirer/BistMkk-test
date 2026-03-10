# KAP Classifier — İlerleme Takibi

## Durum: 🟢 MVP Tamamlandı

---

## ✅ Tamamlananlar
- [x] Proje iskeletinin oluşturulması (klasör yapısı + tüm alt dizinler)
- [x] agents.md ve progress.md kurulumu
- [x] requirements.txt oluşturulması
- [x] .env.example oluşturulması
- [x] Tüm __init__.py dosyaları oluşturulması
- [x] utils/logger.py — loguru tabanlı merkezi loglama modülü (console + dosya)
- [x] models/disclosure.py — Pydantic v2: DisclosureRaw, DisclosureClassified, ClassificationResult
- [x] classifier/news_type.py — ✅ CATEGORIES keyword matching, `classify(disclosure) → str`, `get_category_label()`, loglama
- [x] classifier/company.py — ✅ CompanyInfo dataclass, `get_company_slug()`, in-memory `_company_registry`, `update_registry()`, `get_all_companies()`
- [x] main.py — ✅ FastAPI + APScheduler (3 dk polling), in-memory store (deque maxlen=1000), 4 endpoint:
  - `GET /` — son 50 bildirim
  - `GET /company/{stock_code}` — şirket bazlı bildirimler
  - `GET /category/{category}` — kategori bazlı bildirimler
  - `GET /api/disclosures` — JSON API (limit, stock_code, category filtreleri)
- [x] web/templates/base.html — ✅ Tailwind CDN, mobil uyumlu navbar, kategori dropdown, footer
- [x] web/templates/index.html — ✅ Bildirim tablosu (tarih, şirket, kategori, başlık, KAP linki), boş durum mesajı
- [x] web/templates/company.html — ✅ Şirket detay sayfası, bildirim tablosu, KAP linki
- [x] web/templates/category.html — ✅ Kategori detay sayfası, aktif kategori vurgusu, bildirim tablosu
- [x] Eski kap.org.tr endpoint kaldırıldı
- [x] Provider soyutlama katmanı (BaseKAPProvider) oluşturuldu
- [x] MKKProvider iskelet olarak yazıldı (endpoint path bekleniyor)
- [x] MockProvider ile geliştirme ortamı çalışıyor
- [x] main.py → KAPClient yerine get_provider() kullanıyor
- [x] Web arayüzü provider mimarisine güncellendi:
  - base.html: provider durum bandı (mock/prod), navbar provider badge, footer güncellendi
  - index.html / company.html / category.html: boş durum mesajları provider'a göre dinamik
  - /status endpoint: provider sağlık durumu, store boyutu JSON olarak sunuluyor

## ⏳ Bekliyor (Kullanıcı Aksiyonu Gerekiyor)
- [x] MKK API Portal'den API key alınması
- [x] KAP_PROVIDER=mkk yapılması (.env güncellendi)
- [x] MKKProvider içindeki TODO endpoint path'lerinin doldurulması
- [x] MKK API entegrasyon testi — HTTP 200, canlı bildirim çekiliyor

## 🔄 Devam Edenler
- [ ] MockProvider ile sınıflandırma motorunu test et

## 📋 Backlog (v2)
- [ ] Veritabanı şeması tasarımı (SQLite → PostgreSQL)
- [ ] SQLAlchemy modelleri ve Alembic migration'ları
- [ ] LLM entegrasyon katmanı (otomatik özet + sentiment analizi)
- [ ] Şirket bazlı alert / bildirim sistemi
- [ ] REST API dokümantasyonu (OpenAPI genişletme)
- [ ] JSON önbellek dosyasına kalıcı yazma (uygulama yeniden başlatmada veri kaybı önleme)
- [ ] Sayfalama (pagination) desteği web arayüzünde

---
## ⚠️ Kritik Değişiklik
- [x] Eski kap.org.tr scraping yaklaşımı KALDIRILDI
- [x] Yeni provider mimarisi kuruldu (bkz. ADIM 2)

## Notlar
_10.03.2026 — MVP tamamlandı. Tüm sınıflandırma, polling ve web UI görevleri çalışır durumda._
_10.03.2026 — Web başlatma sorunları düzeltildi: sanal ortam (.venv) oluşturuldu, bağımlılıklar Python 3.13 uyumlu sürümlere güncellendi, eksik `__init__.py` dosyaları eklendi, `.env` dosyası oluşturuldu._
_10.03.2026 — KAP client yeniden yazıldı: tarayıcı simülasyonu header'ları eklendi, companies_cache.json (24h TTL), fetch_companies() ve fetch_by_company() metodları eklendi._
_11.03.2026 — .env yükleme hatası düzeltildi: main.py'ye `load_dotenv()` eklendi; MKKSettings'e `extra="ignore"` eklendi. Sunucu artık KAP_PROVIDER=mkk ile MKKProvider (Üretim) modunda başlıyor._
_11.03.2026 — MKK API entegrasyon güvenlik analizi yapıldı. Kritik bulgular: .gitignore eksik (API key ifşa riski), .env.example yok, fetch_latest() implement edilmemiş, 401/429/500 hata handler'ları eksik, test dosyaları yok._
_11.03.2026 — MKK gateway URL'leri resmi adreslere güncellendi: TEST=https://apigwdev.mkk.com.tr (alt: apitestint.mkk.com.tr), PROD=https://apiint.mkk.com.tr. .env ve mkk_provider.py güncellendi._
_11.03.2026 — GitHub'a güvenli gönderim için .gitignore ve .env.example dosyaları oluşturuldu. API key ifşa riski giderildi._
_11.03.2026 — Git deposu başlatıldı, ilk commit oluşturuldu ve `origin` olarak `https://github.com/nezirer/BistMkk-test.git` eklendi. Push denemesi yerel GitHub HTTPS kimlik doğrulaması eksik olduğu için tamamlanamadı._
_11.03.2026 — MKKProvider tam implemente edildi: `fetch_latest()` → lastDisclosureIndex + disclosures çift adım akışı, exponential backoff (429, max 3 retry), 401/403/timeout hata logları, `fetch_by_stock_code()` → /kap/memberSecurities, `fetch_companies()` → /kap/members, `health_check()` → /kap/lastDisclosureIndex. BASE_URL apitestint.mkk.com.tr olarak güncellendi._
_11.03.2026 — Resmi apispec.json (OpenAPI 3.0.3) analiz edildi. Kritik düzeltmeler: BASE_URL → https://apigwdev.mkk.com.tr/api/vyk (/api/vyk prefix zorunlu), path'ler → /lastDisclosureIndex, /disclosures, /disclosureDetail/{index}. DisclosureRaw modeli MKK VYK API response alanlarıyla yeniden yazıldı. classify() MKK disclosureType kodlarına uyarlandı._
_11.03.2026 — MKK Basic Auth (MKK_API_USER / MKK_API_PASS) entegrasyonu tamamlandı. /lastDisclosureIndex HTTP 200, /disclosures HTTP 200, /disclosureDetail HTTP 200. datetime JSON serileştirme hatası (model_dump mode=json) düzeltildi. Sistem uçtan uca çalışıyor: canlı KAP bildirimi çekilip sınıflandırılıyor._
_11.03.2026 — apispec.json uyumluluk doğrulaması yapıldı. 2 kritik düzeltme: (1) companyId parametresi spec gereği array olarak gönderiliyor {"companyId": [company_id]}. (2) mkk_provider.py docstring'deki yanlış Bearer token açıklaması → basicAuth (HTTP Basic) olarak düzeltildi._
