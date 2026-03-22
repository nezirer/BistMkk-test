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
- [x] Sayfalama (pagination) desteği web arayüzünde
- [ ] Şirket detayları (`/memberDetail/{id}`) DB'ye önbellekleme

## ✅ Tamamlananlar (v4 — Web Ürün Haline Getirme)
- [x] `db/repository.py`: `count_disclosures()`, `get_disclosure_by_index()`, `get_stats()`, `count_companies()` fonksiyonları eklendi; `get_disclosures()` ve `get_companies()`'e `search_query` + sayfalama parametreleri eklendi
- [x] `main.py`: `PAGE_SIZE=50` sabiti; tüm HTML endpoint'lerine `page` query param + sayfalama; `/disclosure/{index}` (bildirim detay), `/companies` (şirket listesi), `/api/stats` yeni endpoint'leri; `/api/disclosures`'a `q` search param eklendi
- [x] `web/templates/base.html`: Marka "KAP Sinyal" olarak güncellendi; navbar'a arama çubuğu + /companies linki eklendi; "MVP" yazısı footer'dan kaldırıldı; sticky navbar; tıklanabilir satır JS desteği
- [x] `web/templates/index.html`: 4 istatistik kartı (toplam bildirim, son 24 saat, olumlu/olumsuz oran); arama + sayfalama; renkli kategori badge'leri; tıklanabilir satırlar; fiyat değişimleri yüzde olarak gösteriliyor
- [x] `web/templates/disclosure.html` (YENİ): Bildirim detay sayfası — başlık kartı, sentiment açıklaması, fiyat hareketi şeridi (Yayın→5dk→1sa→1g→1h), full_text HTML render, ek dosyalar, meta bilgiler, ilgili bildirimler
- [x] `web/templates/companies.html` (YENİ): BIST şirket listesi — arama + sayfalama (50/sayfa)
- [x] `web/templates/company.html`: Sayfalama + tıklanabilir satırlar + renkli badge'ler + modern tasarım
- [x] `web/templates/category.html`: Sayfalama + tıklanabilir satırlar + renkli badge'ler + modern tasarım

---
## ⚠️ Kritik Değişiklik
- [x] Eski kap.org.tr scraping yaklaşımı KALDIRILDI
- [x] Yeni provider mimarisi kuruldu (bkz. ADIM 2)

## ✅ Tamamlananlar (v3.4 — publish_datetime_utc + Tam Sistem Testi)
- [x] `publish_date` parse formatına `%d.%m.%Y %H:%M:%S` (saniyeli) eklendi — DB'deki tüm tarihlerin UTC'ye çevrilmesini engelleyen bug düzeltildi
- [x] `publish_datetime_utc` backfill: 100 kayıt başarıyla güncellendi
- [x] `price_at_news` backfill: 18 yeni kayıt daha güncellendi (toplam 39)
- [x] Tüm yeni DB sütunları migration ile otomatik oluşturuldu: `attachment_urls`, `related_disclosure_index`, `period`, `related_stocks`, `publish_datetime_utc`
- [x] `pdf_link` veritabanı sütunu eklendi. KAP bildirimlerinde ek dosya (özellikle PDF) varsa, ilk dosyanın URL'si doğrudan `pdf_link` alanına kaydediliyor ve arayüzde "PDF İndir" butonu olarak gösteriliyor.
- [x] Tam sistem testi başarılı: PostgreSQL bağlantı, MKK API polling, sentiment analizi, fiyat backfill, web UI, JSON API

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
_22.03.2026 — KAP verilerinin formatını incelemek amacıyla `sandbox_fetch.py` betiği oluşturuldu ve MKK API üzerinden 5 adet örnek bildirim çekilerek `ornek.json` dosyasına kaydedildi._
_22.03.2026 — MKK API'den gelen 4 yeni alan veritabanına ve modele eklendi: `attachment_urls` (bildirim ek dosyaları, JSONB), `related_disclosure_index` (ilişkili bildirim index'i, VARCHAR(50)), `period` (dönem bilgisi, VARCHAR(200)), `related_stocks` (ilişkili hisse kodları, JSONB). Değişiklikler: `models/disclosure.py` (Pydantic model + `enrich_from_detail` parse), `db/schema.sql` (CREATE TABLE + ALTER TABLE migration), `db/models.py` (DDL + migration), `db/repository.py` (INSERT/UPDATE sorguları + tüm SELECT sorguları güncellendi, tekrar eden row→object dönüşüm kodu `_row_to_disclosure()` yardımcı fonksiyonuyla merkezileştirildi). Ayrıca `repository.py`'deki kırık `update_last_seen_index()` fonksiyon imzası düzeltildi.
_22.03.2026 — **Fiyat hesaplama mimarisi yeniden yazıldı: yayınlanma tarihine dayalı (publish_datetime_utc) sistem.**
  - **Problem:** `price_at_news` bildirimin çekildiği an'ın fiyatını alıyordu (`get_current_price()`), bildirimin yayınlanma tarihi ile çekilme tarihi farklı olabildiğinden yanlış fiyatlar kaydediliyordu. `_update_prices` fonksiyonu da yanlışlıkla `_backfill_full_text()` içinde sahipsiz kod bloğu olarak kalmıştı (NameError).
  - **Çözüm:**
    1. DB'ye `publish_datetime_utc TIMESTAMPTZ` sütunu eklendi (migration: v3.4). KAP bildirimi yayınlanma zamanı Türkiye saatinden (UTC+3) UTC'ye çevrilerek saklanıyor.
    2. `models/disclosure.py`: `publish_datetime_utc` alanı + `_parse_publish_datetime_utc()` metodu eklendi. `enrich_from_detail()` sonunda otomatik doldurma.
    3. `fetcher/finance.py`: `get_price_at_publish()` fonksiyonu eklendi — yayınlanma gününün kapanış fiyatını veya son 7 gün içindeyse 5dk intraday en yakın fiyatı döndürür.
    4. `main.py / _fetch_and_classify()`: `get_current_price()` → `get_price_at_publish(publish_datetime_utc)` ile değiştirildi.
    5. `main.py / _update_prices()`: Sahipsiz kod bloğu düzgün `async def` fonksiyonuna çevrildi; `publish_datetime` property yerine `publish_datetime_utc` DB sütunu kullanılıyor.
    6. `main.py / _backfill_publish_datetime()`: Mevcut kayıtların (a) `publish_datetime_utc` parse + (b) `price_at_news` yayınlanma tarihine göre backfill mekanizması. Başlangıçta bir kez + her 10 dakikada bir çalışır.
    7. `db/repository.py`: `update_publish_datetime_utc()`, `get_disclosures_missing_publish_datetime()`, `get_disclosures_needing_price_at_news()`, `update_price_at_news()` fonksiyonları eklendi. `upsert_disclosure` ve `_row_to_disclosure` güncellendi._
_22.03.2026 — **Web ürün haline getirildi (v4).** MVP arayüzü tamamen yeniden yazıldı: (1) Marka "KAP Sinyal" olarak güncellendi. (2) Ana sayfaya 4 istatistik kartı (toplam bildirim, son 24 saat, olumlu/olumsuz oran) eklendi. (3) Tüm sayfalara sayfalama (50/sayfa) ve arama desteği eklendi. (4) Yeni `/disclosure/{index}` bildirim detay sayfası: fiyat hareketi şeridi, full_text HTML render, AI sentiment açıklaması, ek dosyalar, ilgili bildirimler. (5) Yeni `/companies` şirket listesi sayfası: 1014 şirketi arama+sayfalama ile listeler. (6) Renkli kategori badge'leri (mavi=finansal, mor=özel durum, yeşil=temettü vb.). (7) Tüm tablo satırları tıklanabilir (detay sayfasına yönlendirir). (8) `/api/stats` ve `/api/disclosures?q=` yeni endpoint'leri eklendi. DB fonksiyonları: `count_disclosures()`, `get_disclosure_by_index()`, `get_stats()`, `count_companies()`, `search_query` parametreli sorgular._
