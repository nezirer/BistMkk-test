# KAP Classifier — Ajan Rehberi

## Proje Amacı
KAP bildirimlerini otomatik olarak çekip şirket ve tür bazında sınıflandırmak.

## Mimari Kararlar
- **Şu an (v2):** PostgreSQL veritabanı aktif. OCI Compute Instance (Ubuntu 24.04 ARM64) üzerinde `invoice-db` adlı mevcut PostgreSQL Docker container'ına `kap_db` veritabanı ve `kap_user` eklendi.
- **DB Katmanı:** `db/` klasörü — `connection.py` (psycopg2 havuzu), `models.py` (otomatik tablo oluşturma), `repository.py` (CRUD), `schema.sql` (el ile DDL)
- **API limit koruması:** İlk açılışta son 500 bildirimden geriye doğru başlar (limit=500). MKK API'nin 50'lik limiti nedeniyle her 3 dakikada bir 50'şer çekerek geçmişi doldurur. Güncele yetiştikten sonra her polling döngüsünde DB'deki son `disclosure_index`'ten itibaren yalnızca yeni bildirimler çekilir. Mevcut kayıtlar tekrar API'den sorgulanmaz.
- **Şirket listesi:** 24 saatlik TTL ile `kap_companies` tablosunda önbelleklenir, `/members` endpoint'i günde bir kez çağrılır.
- **API:** Provider pattern (BaseKAPProvider) — bkz. fetcher/ klasörü
- **Polling:** Her 3 dakikada bir yeni bildirimleri çek (APScheduler)
- **Web:** MVP — Jinja2 + minimal Tailwind CSS. SPA veya React KULLANMA.

## Geliştirme Kuralları
1. Her yeni özellik önce bu dosyada belgelenir, sonra kodlanır.
2. DB işlemleri yalnızca `db/repository.py` üzerinden yapılır; SQL doğrudan başka dosyalara yazılmaz.
3. Sınıflandırma mantığı `classifier/` altında izole tutulmalı (LLM entegrasyonuna hazır).
4. Tüm KAP veri erişimi `BaseKAPProvider` arayüzü üzerinden yapılır; provider `get_provider()` factory fonksiyonu ile seçilir.
5. Pydantic modelleri schema-first prensibiyle tasarlanır.
6. Yeni tablo/sütun eklendiğinde hem `db/models.py` hem `db/schema.sql` güncellenir.

## ⛔ Kaldırılan Yaklaşım (v0 - KULLANILAMAZ)
- `kap.org.tr/tr/api/disclosures` endpoint'i artık public erişime kapalı
- Header simülasyonu (User-Agent, Referer spoof) ile erişim denendi, başarısız
- Bu endpoint hiçbir zaman resmi public API olmadı, front-end iç endpoint'iydi
- Resmi doküman: veri yayın servisi API key + IP yetkilendirmesi zorunlu tutuyor

## ✅ Aktif Mimari (v1)

### Provider Pattern
- Tüm KAP veri erişimi `BaseKAPProvider` arayüzü üzerinden yapılır
- Provider `KAP_PROVIDER` env değişkeni ile seçilir
- Şu an: `MockProvider` aktif (API key bekleniyor)
- Hedef: `MKKProvider` (MKK API Portal API key alındığında)

### MKK API Portal Bilgileri
- Portal: https://apiportal.mkk.com.tr
- Test REST: https://apitest.mkk.com.tr
- Prod REST: https://api.mkk.com.tr
- Resmi Doküman: https://www.mkk.com.tr/saklama-hizmetleri/bilgi-merkezi/formatlar

### MKK API Key Nasıl Alınır?
1. https://apiportal.mkk.com.tr adresine git
2. Hesap oluştur / giriş yap
3. KAP Veri Yayın Servisi'ne abone ol
4. API Key al → MKK_API_KEY olarak .env'e yaz
5. MKKProvider içindeki TODO'ları endpoint path ile doldur
6. KAP_PROVIDER=mkk olarak değiştir

## Bildirim Türleri (KAP basicType)
- Finansal Raporlar
- Özel Durum Açıklamaları
- Genel Kurul Kararları
- Sermaye Artırımı / Azaltımı
- Yönetim Değişiklikleri
- Temettü Açıklamaları
- Diğer

## Veritabanı Bilgileri
- **Sunucu:** OCI Compute Instance — `132.226.192.163` (eu-frankfurt-1, ARM64)
- **Container:** `invoice-db` (postgres:16-alpine, port 5432)
- **Veritabanı:** `kap_db`
- **Kullanıcı:** `kap_user`
- **Tablolar:** `kap_disclosures`, `kap_companies`, `kap_company_details`, `kap_sync_state`
- **Bağlantı (local geliştirme):** `.env` → `PG_HOST=132.226.192.163` ile uzaktan bağlanılır
- **Bağlantı (sunucu):** Uygulama sunucuya taşındığında `PG_HOST=localhost` yapılır

## Gelecek Özellikler (v3+)
- [x] LLM ile otomatik özet ve sentiment analizi (OpenAI)
- [x] yfinance ile haber sonrası hisse fiyatı değişimlerinin takibi (anlık, 5dk, 1sa, 1g, 1h)
- [ ] Şirket bazlı alert sistemi
- [ ] REST API endpoint'leri (dış kullanım için)
- [ ] Şirket detayları (`/memberDetail/{id}`) DB'ye önbellekleme

## LLM ve Finans Entegrasyonu (v3)
- **LLM:** OpenAI API kullanılarak `classifier/sentiment.py` üzerinden haberlerin duygu analizi (Olumlu, Olumsuz, Nötr) yapılır.
- **Finans:** `yfinance` kütüphanesi kullanılarak `fetcher/finance.py` üzerinden haber anı ve sonrasındaki fiyat değişimleri takip edilir.
- **Veritabanı:** `kap_disclosures` tablosuna `sentiment`, `sentiment_reason` ve fiyat takibi için `price_at_news`, `price_5m`, `price_1h`, `price_1d`, `price_1w` sütunları eklenmiştir.
- **Zamanlanmış Görevler:** `main.py` içinde yeni haberler çekildiğinde asenkron LLM analizi tetiklenir ve belirli aralıklarla eski haberler için fiyat güncellemeleri yapılır.
