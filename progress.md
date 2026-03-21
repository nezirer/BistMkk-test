# KAP Classifier — İlerleme Takibi

## Durum: 🟢 v2 — PostgreSQL Entegrasyonu Tamamlandı ve Test Edildi

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

## ✅ Tamamlananlar (v2 — PostgreSQL Entegrasyonu)
- [x] `psycopg2-binary>=2.9.9` requirements.txt'e eklendi (oracledb kaldırıldı)
- [x] `db/connection.py` — psycopg2 ThreadedConnectionPool, async context manager, bağlantı havuzu (min=1, max=5)
- [x] `db/schema.sql` — PostgreSQL DDL: kap_disclosures, kap_companies, kap_company_details, kap_sync_state (JSONB, INSERT ON CONFLICT)
- [x] `db/models.py` — Python'dan otomatik tablo oluşturma (CREATE TABLE IF NOT EXISTS — idempotent)
- [x] `db/repository.py` — CRUD: upsert_disclosure, get_disclosures, disclosure_exists, get_last_seen_index, update_last_seen_index, upsert_company, upsert_company_detail, get_companies, companies_stale
- [x] `main.py` — in-memory deque/set kaldırıldı, PostgreSQL repository ile değiştirildi
- [x] `.env` — PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD değişkenleri eklendi
- [x] API limit koruması: İlk açılışta son 500 bildirimden başlar (limit=500). MKK API'nin 50'lik limiti nedeniyle her 3 dakikada bir 50'şer 50'şer çekerek geçmişi doldurur ve güncele yetişir. Mevcut bildirimler tekrar çekilmez, şirket listesi 24 saatte bir yenilenir.
- [x] PostgreSQL DB kuruldu: OCI sunucusundaki `invoice-db` container'ına `kap_db` ve `kap_user` eklendi
- [x] `.env` PG bağlantı bilgileriyle güncellendi — local geliştirme için `PG_HOST=132.226.192.163` ile uzaktan bağlanılıyor
- [x] Uçtan uca test tamamlandı: 50 bildirim çekildi, sınıflandırıldı, `kap_disclosures` tablosuna yazıldı (`SELECT COUNT(*) → 50`)

## ⏳ Bekliyor (Kullanıcı Aksiyonu)
- [ ] Uygulamayı OCI sunucusuna taşı (`scp` veya `git clone`)
- [ ] Sunucuda `PG_HOST=localhost` olarak güncelle
- [ ] Sunucuda `pip install -r requirements.txt && uvicorn main:app` ile başlat
- [ ] OCI Security List'te 5432 portunu yalnızca kendi IP'nize kısıtlayın (güvenlik)

## 📋 Backlog (v3)
- [x] LLM entegrasyon katmanı (otomatik özet + sentiment analizi) - OpenAI ile
- [x] Sentiment prompt'u yeniden yazıldı: BIST domain'ine özel karar kuralları, kategori/bildirim tipi bağlam eklendi, temperature 0.0, tekrar kaldırıldı
- [x] yfinance ile haber sonrası hisse fiyatı değişimlerinin takibi (anlık, 5dk, 1sa, 1g, 1h)
- [x] Sentiment backfill mekanizması: DB'deki sentiment=NULL kayıtlar yeniden analiz edilir; zaten analiz edilmiş haberlere dokunulmaz. Başlangıçta bir kez + her 10 dakikada bir çalışır.
- [ ] Şirket bazlı alert / bildirim sistemi
- [ ] REST API dokümantasyonu (OpenAPI genişletme)
- [ ] Sayfalama (pagination) desteği web arayüzünde
- [ ] Şirket detayları (`/memberDetail/{id}`) DB'ye önbellekleme

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
_12.03.2026 — Oracle Always Free veritabanı entegrasyonu tamamlandı. in-memory deque/set → Oracle DB (oracledb thin mode, Wallet bağlantısı). 4 tablo: KAP_DISCLOSURES, KAP_COMPANIES, KAP_COMPANY_DETAILS, KAP_SYNC_STATE. API limit koruması: polling her seferinde son kaydedilen index'ten başlar. Şirket listesi 24 saatlik TTL ile önbelleklenir._
_12.03.2026 — DB katmanı Oracle XE'den PostgreSQL'e geçirildi. OCI Compute Instance ARM64 (aarch64) mimarisi Oracle XE imajıyla uyumsuz olduğu için psycopg2-binary + PostgreSQL Docker kullanımına geçildi. Tüm Oracle SQL sözdizimi (MERGE INTO, DUAL, VARCHAR2, CLOB, SYSTIMESTAMP) PostgreSQL karşılıklarına (INSERT ON CONFLICT, VARCHAR, JSONB, NOW()) dönüştürüldü._
_12.03.2026 — Uçtan uca test başarılı. PostgreSQL kap_db'ye bağlantı kuruldu, tablolar otomatik oluşturuldu, 50 KAP bildirimi çekilip sınıflandırılarak kap_disclosures tablosuna yazıldı. SELECT COUNT(*) → 50 doğrulandı._
_21.03.2026 — Sentiment backfill mekanizması eklendi: `_backfill_sentiment()` fonksiyonu DB'de `sentiment IS NULL` olan bildirimleri bulup OpenAI API ile analiz eder. Zaten analiz edilmiş (sentiment dolu) haberlere hiç dokunmaz. Uygulama başlangıcında bir kez + her 10 dakikada bir scheduler ile çalışır. `db/repository.py`'e `get_disclosures_missing_sentiment()`, `classifier/news_type.py`'e `get_category_key()` eklendi._
_21.03.2026 — 5 kritik hata düzeltildi: (1) OpenAI model adı `gpt-5.4-nano` → `gpt-4.1-nano-2025-04-14` düzeltildi (geçersiz model adı sentiment özelliğini tamamen devre dışı bırakıyordu). (2) `kap_disclosures` tablosuna `sentiment_failed_at TIMESTAMPTZ` sütunu eklendi; başarısız olan sentiment işlemleri bu alanla işaretleniyor, `get_disclosures_missing_sentiment()` artık `sentiment_failed_at IS NULL` koşulunu da kontrol ederek sonsuz retry döngüsü önleniyor. (3) `_backfill_sentiment` ve `_update_prices` fonksiyonları `upsert_disclosure` yerine hedefli `update_sentiment()` / `update_prices()` sorgularını kullanıyor — gereksiz tam kayıt yazımı kaldırıldı. (4) `get_disclosures_needing_price_update()` sorgusuna `classified_at >= NOW() - INTERVAL '8 days'` filtresi eklendi; hiçbir zaman fiyat alınamayacak eski kayıtların sonsuz döngüye girmesi engellendi. (5) PostgreSQL bağlantı havuzu boyutu `maxconn=5` → `maxconn=10` olarak artırıldı._
_12.03.2026 — Kritik bug düzeltmeleri (7 adet): (1) fetch_latest() artık DB'deki last_seen_index parametresini alarak sadece yeni bildirimleri çekiyor — her polling döngüsündeki 100 gereksiz HTTP isteği engellendi. (2) stock_codes filtresi exact match → ILIKE ile çoklu kodlu bildirimlerde şirket sayfası boş görünme hatası giderildi. (3) MockProvider.fetch_companies() yanlış dict anahtarları ("code"/"name") → doğru anahtarlar ("id"/"title"/"stockCode") — mock modunda şirketlerin DB'ye kaydedilmemesi hatası giderildi. (4) company.py update_registry() / get_company_slug() boş stock_codes için geçersiz "" anahtarla kayıt oluşturma hatası giderildi. (5) asyncio.get_event_loop() → get_running_loop() (Python 3.10+ DeprecationWarning/RuntimeError riski). (6) httpx.AsyncClient lifespan sonunda kapatılmıyor (kaynak sızıntısı) — provider.close() lifespan shutdown'a eklendi. (7) fetch_by_stock_code() disclosureIndex=last_index yanlış — start_index=last_index-99 ile son 100 bildirimi kapsıyor._
