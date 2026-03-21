"""FastAPI giriş noktası — APScheduler + PostgreSQL store."""
from __future__ import annotations

import os

from dotenv import load_dotenv
load_dotenv()
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import classifier.company as company_svc
import classifier.news_type as news_svc
from classifier.sentiment import analyze_sentiment, client as _openai_client
import db.repository as repo
from db.connection import init_pool, close_pool, get_connection
from db.models import create_tables
from fetcher.base_provider import BaseKAPProvider
from fetcher.provider_factory import get_provider
from fetcher.finance import get_current_price, get_price_at_time
from models.disclosure import DisclosureClassified, DisclosureRaw
from utils.logger import get_logger

log = get_logger(__name__)
templates = Jinja2Templates(directory="web/templates")

_scheduler = AsyncIOScheduler()
_provider: BaseKAPProvider | None = None


def _provider_name() -> str:
    return os.getenv("KAP_PROVIDER", "mock").lower()


def _provider_label() -> str:
    name = _provider_name()
    return "MockProvider (Geliştirme)" if name == "mock" else "MKKProvider (Üretim)"


# ---------------------------------------------------------------------------
# Polling / sınıflandırma
# ---------------------------------------------------------------------------

async def _fetch_and_classify() -> None:
    """
    KAP'tan son bildirimleri çekip sınıflandırarak Oracle DB'ye kaydeder.

    API limit koruması:
      1. DB'deki son disclosure_index alınır.
      2. MKK'dan sadece o index'ten itibaren yeni bildirimler çekilir.
      3. Her bildirim DB'de mevcut değilse kaydedilir.
      4. Şirket listesi 24 saatte bir yenilenir (companies_stale kontrolü).
    """
    global _provider
    log.info("Polling başladı (provider: {}).", _provider_label())

    try:
        if _provider is None:
            _provider = get_provider()
        last_seen = await repo.get_last_seen_index()
        raw_items: list[DisclosureRaw] = await _provider.fetch_latest(
            limit=500, since_index=last_seen
        )
    except Exception as exc:
        log.error("Provider hatası: {}", exc)
        return

    new_count = 0
    max_index = 0

    for raw in raw_items:
        # DB'de zaten varsa API'yi atlayıp devam et
        if await repo.disclosure_exists(raw.disclosure_index):
            continue

        try:
            category = news_svc.classify(raw)
            slug = company_svc.get_company_slug(raw.stock_codes, raw.company_name)
            classified = DisclosureClassified.from_raw(
                raw,
                news_category=news_svc.get_category_label(category),
                company_slug=slug,
            )
            
            # LLM Duygu Analizi
            sentiment_result = await analyze_sentiment(
                classified.title,
                classified.subject,
                news_category=category,
                disclosure_type=classified.disclosure_type,
                full_text=classified.full_text,
            )
            if sentiment_result:
                classified.sentiment = sentiment_result.sentiment
                classified.sentiment_reason = sentiment_result.reason
                
            # Haber anı fiyatı
            if classified.stock_codes:
                # İlk hisse kodunu alalım (örn: "THYAO,THYAO2" -> "THYAO")
                first_code = classified.stock_codes.split(",")[0].strip()
                if first_code:
                    price = await get_current_price(first_code)
                    if price is not None:
                        classified.price_at_news = price

        except Exception as exc:
            log.warning("Bildirim sınıflandırılamadı: {} — {}", raw.disclosure_index, exc)
            continue

        try:
            await repo.upsert_disclosure(classified)
            new_count += 1
            if raw.disclosure_index > max_index:
                max_index = raw.disclosure_index
        except Exception as exc:
            log.error("DB yazma hatası (index={}): {}", raw.disclosure_index, exc)

    # Son index'i kaydet
    if max_index > 0:
        await repo.update_last_seen_index(max_index)

    # Şirket listesini 24 saatte bir güncelle
    try:
        if await repo.companies_stale(ttl_hours=24):
            companies = await _provider.fetch_companies()
            for member in companies:
                await repo.upsert_company(member)
            company_svc.update_registry(raw_items)
            log.info("Şirket listesi güncellendi ({} kayıt).", len(companies))
    except Exception as exc:
        log.warning("Şirket listesi güncellenemedi: {}", exc)

    log.info("Polling tamamlandı: {} yeni bildirim DB'ye eklendi.", new_count)


async def _backfill_sentiment() -> None:
    """
    DB'de sentiment analizi yapılmamış (sentiment IS NULL) bildirimleri bulup
    OpenAI API ile analiz eder. Her çalışmada en fazla 50 bildirimi işler.
    Böylece uygulama yeniden başlatıldığında eski haberler tekrar analiz edilmez,
    sadece eksik olanlar tamamlanır.
    """
    if not _openai_client:
        return

    try:
        pending = await repo.get_disclosures_missing_sentiment(limit=50)
        if not pending:
            return

        log.info("Sentiment backfill başladı: {} eksik kayıt işlenecek.", len(pending))
        updated = 0

        for disc in pending:
            try:
                category = news_svc.get_category_key(disc.news_category)
                sentiment_result = await analyze_sentiment(
                    disc.title,
                    disc.subject,
                    news_category=category,
                    disclosure_type=disc.disclosure_type,
                    full_text=disc.full_text,
                )
                if sentiment_result:
                    await repo.update_sentiment(
                        disc.disclosure_index,
                        sentiment_result.sentiment,
                        sentiment_result.reason,
                    )
                    updated += 1
                else:
                    # API yanıt verdı ama boş döndü — başarısız say
                    await repo.mark_sentiment_failed(disc.disclosure_index)
            except Exception as exc:
                log.warning(
                    "Backfill sentiment hatası (index={}): {}", disc.disclosure_index, exc
                )
                await repo.mark_sentiment_failed(disc.disclosure_index)

        if updated > 0:
            log.info("Sentiment backfill tamamlandı: {} kayıt güncellendi.", updated)

    except Exception as exc:
        log.error("Sentiment backfill genel hata: {}", exc)


async def _backfill_full_text() -> None:
    """
    DB'de full_text alanı boş olan bildirimlerin tam içeriğini MKK API'den
    yeniden çeker (htmlMessages Base64 decode), DB'ye yazar ve
    sentiment'i sıfırlar ki backfill_sentiment tarafından yeniden analiz edilsin.
    Her çalışmada en fazla 20 bildirimi işler.
    """
    global _provider
    if _provider is None:
        return

    try:
        pending = await repo.get_disclosures_missing_full_text(limit=20)
        if not pending:
            return

        log.info("Full-text backfill başladı: {} eksik kayıt işlenecek.", len(pending))
        updated = 0

        for disc in pending:
            try:
                detail = await _provider._get(
                    f"/disclosureDetail/{disc.disclosure_index}",
                    params={"fileType": "html"},
                )
                if not isinstance(detail, dict):
                    continue

                # Geçici DisclosureRaw nesnesi üzerinden full_text hesapla
                from models.disclosure import DisclosureRaw
                tmp = DisclosureRaw(disclosureIndex=disc.disclosure_index)
                tmp.enrich_from_detail(detail)

                if tmp.full_text:
                    await repo.update_full_text_and_reset_sentiment(
                        disc.disclosure_index, tmp.full_text
                    )
                    updated += 1
            except Exception as exc:
                log.warning(
                    "Full-text backfill hatası (index={}): {}", disc.disclosure_index, exc
                )

        if updated > 0:
            log.info("Full-text backfill tamamlandı: {} kayıt güncellendi.", updated)

    except Exception as exc:
        log.error("Full-text backfill genel hata: {}", exc)



    """
    Eski bildirimlerin fiyatlarını (5dk, 1sa, 1g, 1h) günceller.
    """
    try:
        disclosures = await repo.get_disclosures_needing_price_update()
        if not disclosures:
            return

        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        updated_count = 0

        for disc in disclosures:
            if not disc.stock_codes or not disc.publish_datetime:
                continue

            pub_time = disc.publish_datetime
            if pub_time.tzinfo is None:
                pub_time = pub_time.replace(tzinfo=timezone.utc)

            time_diff = now - pub_time
            first_code = disc.stock_codes.split(",")[0].strip()
            if not first_code:
                continue

            new_5m: float | None = None
            new_1h: float | None = None
            new_1d: float | None = None
            new_1w: float | None = None

            # 5 dakika
            if disc.price_5m is None and time_diff >= timedelta(minutes=5):
                new_5m = await get_price_at_time(first_code, pub_time + timedelta(minutes=5))

            # 1 saat
            if disc.price_1h is None and time_diff >= timedelta(hours=1):
                new_1h = await get_price_at_time(first_code, pub_time + timedelta(hours=1))

            # 1 gün
            if disc.price_1d is None and time_diff >= timedelta(days=1):
                new_1d = await get_price_at_time(first_code, pub_time + timedelta(days=1))

            # 1 hafta
            if disc.price_1w is None and time_diff >= timedelta(days=7):
                new_1w = await get_price_at_time(first_code, pub_time + timedelta(days=7))

            if any(p is not None for p in (new_5m, new_1h, new_1d, new_1w)):
                await repo.update_prices(
                    disc.disclosure_index, new_5m, new_1h, new_1d, new_1w
                )
                updated_count += 1

        if updated_count > 0:
            log.info("Fiyat güncellemesi tamamlandı: {} bildirimin fiyatı güncellendi.", updated_count)

    except Exception as exc:
        log.error("Fiyat güncelleme hatası: {}", exc)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _provider
    log.info("KAP Classifier başlatılıyor (provider: {})...", _provider_label())

    # PostgreSQL bağlantı havuzunu başlat
    init_pool()

    # DB şemasını oluştur (eksik tablolar — IF NOT EXISTS, idempotent)
    import asyncio
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, create_tables, conn)

    # Provider ve ilk polling
    _provider = get_provider()
    await _fetch_and_classify()

    # DB'deki sentiment eksik kayıtları tamamla (başlangıçta bir kez)
    await _backfill_sentiment()

    # DB'deki full_text eksik kayıtları tamamla (başlangıçta bir kez)
    await _backfill_full_text()

    _scheduler.add_job(_fetch_and_classify, "interval", minutes=3, id="kap_poll")
    _scheduler.add_job(_update_prices, "interval", minutes=5, id="price_update")
    _scheduler.add_job(_backfill_sentiment, "interval", minutes=10, id="sentiment_backfill")
    _scheduler.add_job(_backfill_full_text, "interval", minutes=15, id="full_text_backfill")
    _scheduler.start()
    log.info(
        "APScheduler başlatıldı — her 3 dakikada bir polling, "
        "her 5 dakikada bir fiyat güncellemesi, "
        "her 10 dakikada bir sentiment backfill, "
        "her 15 dakikada bir full-text backfill."
    )

    yield

    _scheduler.shutdown(wait=False)
    if _provider is not None:
        await _provider.close()
    close_pool()
    log.info("KAP Classifier kapatılıyor...")


# ---------------------------------------------------------------------------
# FastAPI uygulaması
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KAP Classifier",
    description="KAP bildirimlerini çekip sınıflandıran ve PostgreSQL'e kaydeden uygulama",
    version="0.2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="web/static"), name="static")


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _base_ctx() -> dict:
    """Tüm template'lerin ortak ihtiyaç duyduğu context değişkenleri."""
    return {
        "provider_name": _provider_name(),
        "provider_label": _provider_label(),
        "category_labels": news_svc.CATEGORY_LABELS,
    }


# ---------------------------------------------------------------------------
# Endpoint'ler
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    """Ana sayfa — son 50 bildirimi listeler (DB'den)."""
    disclosures = await repo.get_disclosures(limit=50)
    companies = await repo.get_companies()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "KAP Classifier",
            "disclosures": disclosures,
            "companies": companies,
            "categories": news_svc.ALL_CATEGORIES,
            "total": len(disclosures),
            **_base_ctx(),
        },
    )


@app.get("/company/{stock_code}")
async def company_detail(request: Request, stock_code: str):
    """Şirkete ait tüm bildirimleri listeler (DB'den)."""
    code = stock_code.strip().upper()
    disclosures = await repo.get_disclosures(limit=500, stock_code=code)
    companies = await repo.get_companies(stock_code=code)
    company = companies[0] if companies else None

    if not company and not disclosures:
        raise HTTPException(status_code=404, detail=f"'{code}' hisse kodu bulunamadı.")

    company_name = company["title"] if company else code
    return templates.TemplateResponse(
        "company.html",
        {
            "request": request,
            "title": f"{code} — Bildirimleri",
            "stock_code": code,
            "company_name": company_name,
            "disclosures": disclosures,
            **_base_ctx(),
        },
    )


@app.get("/category/{category}")
async def category_detail(request: Request, category: str):
    """Kategoriye ait tüm bildirimleri listeler (DB'den)."""
    label = news_svc.get_category_label(category)
    disclosures = await repo.get_disclosures(limit=500, category=label)
    return templates.TemplateResponse(
        "category.html",
        {
            "request": request,
            "title": f"{label} — Bildirimleri",
            "category_key": category,
            "category_label": label,
            "disclosures": disclosures,
            **_base_ctx(),
        },
    )


@app.get("/api/disclosures")
async def api_disclosures(
    limit: int = 50,
    stock_code: str = "",
    category: str = "",
    offset: int = 0,
) -> JSONResponse:
    """JSON API — bildirim listesi (isteğe bağlı filtreler: stock_code, category, limit, offset)."""
    category_label = ""
    if category:
        category_label = news_svc.get_category_label(category)

    items = await repo.get_disclosures(
        limit=limit,
        stock_code=stock_code.strip().upper() if stock_code else "",
        category=category_label,
        offset=offset,
    )
    return JSONResponse(
        content={
            "total": len(items),
            "offset": offset,
            "disclosures": [d.model_dump(by_alias=True, mode="json") for d in items],
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status")
async def status():
    """Provider ve DB durumu."""
    provider_ok = await _provider.health_check() if _provider else False
    last_index = await repo.get_last_seen_index()
    return {
        "status": "ok",
        "provider": _provider_name(),
        "provider_label": _provider_label(),
        "provider_healthy": provider_ok,
        "last_disclosure_index": last_index,
    }
