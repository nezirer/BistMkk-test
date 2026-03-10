# KAP Classifier — Ajan Rehberi

## Proje Amacı
KAP bildirimlerini otomatik olarak çekip şirket ve tür bazında sınıflandırmak.

## Mimari Kararlar
- **Şu an:** Veritabanı YOK. Veriler bellekte (in-memory) tutulur, JSON dosyasına cache'lenir.
- **Gelecek v2:** SQLite → PostgreSQL geçişi + LLM sınıflandırma katmanı eklenecek.
- **API:** Provider pattern (BaseKAPProvider) — bkz. fetcher/ klasörü
- **Polling:** Her 3 dakikada bir yeni bildirimleri çek (APScheduler)
- **Web:** MVP — Jinja2 + minimal Tailwind CSS. SPA veya React KULLANMA.

## Geliştirme Kuralları
1. Her yeni özellik önce bu dosyada belgelenir, sonra kodlanır.
2. Veritabanı gerektiren hiçbir bağımlılık ekleme (SQLAlchemy, Alembic vb.) — v2'ye bırak.
3. Sınıflandırma mantığı `classifier/` altında izole tutulmalı (LLM entegrasyonuna hazır).
4. Tüm KAP veri erişimi `BaseKAPProvider` arayüzü üzerinden yapılır; provider `get_provider()` factory fonksiyonu ile seçilir.
5. Pydantic modelleri schema-first prensibiyle tasarlanır (DB migration kolaylığı için).

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

## Gelecek Özellikler (v2+)
- [ ] PostgreSQL entegrasyonu
- [ ] LLM ile otomatik özet ve sentiment analizi
- [ ] Şirket bazlı alert sistemi
- [ ] REST API endpoint'leri (dış kullanım için)
