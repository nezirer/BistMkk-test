"""FastAPI giriş noktası — APScheduler + PostgreSQL store."""
from __future__ import annotations

import os

from dotenv import load_dotenv
load_dotenv()
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import classifier.company as company_svc
import classifier.news_type as news_svc
import db.repository as repo
from db.connection import init_pool, close_pool, get_connection
from db.models import create_tables
from fetcher.base_provider import BaseKAPProvider
from fetcher.provider_factory import get_provider
from fetcher.finance import get_price_at_time, get_price_at_publish
from models.disclosure import DisclosureClassified, DisclosureRaw
from utils.logger import get_logger
from utils.pdf_parser import extract_text_from_pdf_url
from classifier.local_llm import generate_summary

log = get_logger(__name__)
templates = Jinja2Templates(directory="web/templates")

_scheduler = AsyncIOScheduler()
_provider: BaseKAPProvider | None = None

PAGE_SIZE = 50


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
    KAP'tan son bildirimleri çekip sınıflandırarak PostgreSQL'e kaydeder.

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

        # Tutarlılık kontrolü: DB boş ama sync_state dolu ise → sıfırla
        if last_seen > 0:
            total_in_db = await repo.count_disclosures()
            if total_in_db == 0:
                log.warning(
                    "DB boş ama sync_state dolu (last_seen={}). "
                    "Sync state sıfırlanıyor.",
                    last_seen,
                )
                await repo.update_last_seen_index(0)
                last_seen = 0

        raw_items: list[DisclosureRaw] = await _provider.fetch_latest(
            limit=15, since_index=last_seen
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
            # publish_datetime_utc'yi hesapla (model'de parse edilmişse kullan)
            if not classified.publish_datetime_utc:
                classified.publish_datetime_utc = classified._parse_publish_datetime_utc()

            # Haber anı fiyatı — yayınlanma tarihine göre Yahoo Finance'den
            if classified.stock_codes and classified.publish_datetime_utc:
                first_code = classified.stock_codes.split(",")[0].strip()
                if first_code:
                    price = await get_price_at_publish(first_code, classified.publish_datetime_utc)
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


async def _backfill_full_text() -> None:
    """
    DB'de full_text alanı boş olan bildirimlerin tam içeriğini MKK API'den
    yeniden çeker (htmlMessages Base64 decode), DB'ye yazar ve
    Gemma özetleme/JSON değerlendirme araçlarının kullanacağı metni günceller.
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


async def _update_prices() -> None:
    """
    Eski bildirimlerin fiyatlarını (5dk, 1sa, 1g, 1h) günceller.
    publish_datetime_utc üzerinden hesaplama yapılır.
    """
    try:
        disclosures = await repo.get_disclosures_needing_price_update()
        if not disclosures:
            return

        now = datetime.now(timezone.utc)
        updated_count = 0

        for disc in disclosures:
            pub_time = disc.publish_datetime_utc
            if not disc.stock_codes or not pub_time:
                continue

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

            if disc.price_5m is None and time_diff >= timedelta(minutes=5):
                new_5m = await get_price_at_time(first_code, pub_time + timedelta(minutes=5))

            if disc.price_1h is None and time_diff >= timedelta(hours=1):
                new_1h = await get_price_at_time(first_code, pub_time + timedelta(hours=1))

            if disc.price_1d is None and time_diff >= timedelta(days=1):
                new_1d = await get_price_at_time(first_code, pub_time + timedelta(days=1))

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


async def _backfill_publish_datetime() -> None:
    """
    DB'de publish_datetime_utc NULL olan kayıtların publish_date string'inden
    datetime parse edip günceller. Ayrıca price_at_news NULL olanları
    yayınlanma tarihine göre Yahoo Finance'den çeker.
    """
    try:
        # 1) publish_datetime_utc eksik olanları doldur
        pending_dt = await repo.get_disclosures_missing_publish_datetime(limit=200)
        if pending_dt:
            log.info("publish_datetime_utc backfill: {} kayıt işlenecek.", len(pending_dt))
            dt_updated = 0
            for disc in pending_dt:
                utc_dt = disc._parse_publish_datetime_utc()
                if utc_dt:
                    await repo.update_publish_datetime_utc(disc.disclosure_index, utc_dt)
                    dt_updated += 1
            if dt_updated > 0:
                log.info("publish_datetime_utc backfill: {} kayıt güncellendi.", dt_updated)

        # 2) price_at_news eksik olanları yayınlanma tarihine göre çek
        pending_price = await repo.get_disclosures_needing_price_at_news(limit=50)
        if pending_price:
            log.info("price_at_news backfill: {} kayıt işlenecek.", len(pending_price))
            price_updated = 0
            for disc in pending_price:
                if not disc.publish_datetime_utc or not disc.stock_codes:
                    continue
                first_code = disc.stock_codes.split(",")[0].strip()
                if not first_code:
                    continue
                price = await get_price_at_publish(first_code, disc.publish_datetime_utc)
                if price is not None:
                    await repo.update_price_at_news(disc.disclosure_index, price)
                    price_updated += 1
            if price_updated > 0:
                log.info("price_at_news backfill: {} kayıt güncellendi.", price_updated)

    except Exception as exc:
        log.error("publish_datetime/price_at_news backfill hatası: {}", exc)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

async def _run_deferred_startup_backfills() -> None:
    """Ağır backfill'ler — HTTP'nin açılmasını bloklamasın diye yield sonrası arka planda çalışır."""
    try:
        await _backfill_full_text()
        await _backfill_publish_datetime()
    except Exception as exc:
        log.error("Başlangıç backfill (ertelenmiş) hatası: {}", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _provider
    log.info("KAP Classifier başlatılıyor (provider: {})...", _provider_label())

    # PostgreSQL bağlantı havuzunu başlat
    init_pool()

    # DB şemasını oluştur (eksik tablolar — IF NOT EXISTS, idempotent)
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, create_tables, conn)

    # DB durumu logla
    _total = await repo.count_disclosures()
    _last_idx = await repo.get_last_seen_index()
    log.info("DB durumu: {} bildirim, son index: {}", _total, _last_idx)

    # Provider ve ilk polling
    _provider = get_provider()
    # Sürekli (yenilenen) API modeli kapatıldı.
    # Sadece /scripts/fetch_historical.py (1000 adet) araç kullanılacak.
    # await _fetch_and_classify()

    # Full_text / publish_datetime backfill — uzun sürebilir; arka planda başlat
    asyncio.create_task(_run_deferred_startup_backfills())

    # _scheduler.add_job(_fetch_and_classify, "interval", minutes=3, id="kap_poll")
    _scheduler.add_job(_update_prices, "interval", minutes=5, id="price_update")
    _scheduler.add_job(_backfill_full_text, "interval", minutes=15, id="full_text_backfill")
    _scheduler.add_job(_backfill_publish_datetime, "interval", minutes=10, id="publish_datetime_backfill")
    _scheduler.start()
    log.info(
        "APScheduler başlatıldı — Sürekli KAP Polling KAPATILDI. "
        "her 5 dakikada bir fiyat güncellemesi, "
        "her 10 dakikada bir publish_datetime backfill, "
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
async def index(request: Request, page: int = 1, q: str = ""):
    """Ana sayfa — bildirimleri sayfalı olarak listeler, arama destekler."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    search_query = q.strip()

    disclosures = await repo.get_disclosures(
        limit=PAGE_SIZE, offset=offset, search_query=search_query
    )
    total = await repo.count_disclosures(search_query=search_query)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    stats = await repo.get_stats()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "KAP Classifier",
            "disclosures": disclosures,
            "total": total,
            "stats": stats,
            "page": page,
            "total_pages": total_pages,
            "search_query": search_query,
            **_base_ctx(),
        },
    )


@app.get("/company/{stock_code}")
async def company_detail(request: Request, stock_code: str, page: int = 1):
    """Şirkete ait tüm bildirimleri sayfalı olarak listeler."""
    code = stock_code.strip().upper()
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE

    disclosures = await repo.get_disclosures(limit=PAGE_SIZE, stock_code=code, offset=offset)
    total = await repo.count_disclosures(stock_code=code)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    companies = await repo.get_companies(stock_code=code)
    company = companies[0] if companies else None

    if not company and not disclosures and page == 1:
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
            "total": total,
            "page": page,
            "total_pages": total_pages,
            **_base_ctx(),
        },
    )


@app.get("/category/{category}")
async def category_detail(request: Request, category: str, page: int = 1):
    """Kategoriye ait tüm bildirimleri sayfalı olarak listeler."""
    label = news_svc.get_category_label(category)
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE

    disclosures = await repo.get_disclosures(limit=PAGE_SIZE, category=label, offset=offset)
    total = await repo.count_disclosures(category=label)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse(
        "category.html",
        {
            "request": request,
            "title": f"{label} — Bildirimleri",
            "category_key": category,
            "category_label": label,
            "disclosures": disclosures,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            **_base_ctx(),
        },
    )


@app.get("/api/disclosures")
async def api_disclosures(
    limit: int = 50,
    stock_code: str = "",
    category: str = "",
    offset: int = 0,
    q: str = "",
) -> JSONResponse:
    """JSON API — bildirim listesi (isteğe bağlı filtreler: stock_code, category, limit, offset, q)."""
    category_label = ""
    if category:
        category_label = news_svc.get_category_label(category)

    search_query = q.strip()
    items = await repo.get_disclosures(
        limit=limit,
        stock_code=stock_code.strip().upper() if stock_code else "",
        category=category_label,
        offset=offset,
        search_query=search_query,
    )
    total = await repo.count_disclosures(
        stock_code=stock_code.strip().upper() if stock_code else "",
        category=category_label,
        search_query=search_query,
    )
    return JSONResponse(
        content={
            "total": total,
            "offset": offset,
            "disclosures": [d.model_dump(by_alias=True, mode="json") for d in items],
        }
    )


@app.get("/api/stats")
async def api_stats() -> JSONResponse:
    """JSON API — sistem istatistikleri."""
    stats = await repo.get_stats()
    return JSONResponse(content=stats)


@app.get("/companies")
async def companies_list(request: Request, page: int = 1, q: str = ""):
    """Tüm şirketleri sayfalı olarak listeler, arama destekler."""
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    search_query = q.strip()

    companies = await repo.get_companies(
        limit=PAGE_SIZE, offset=offset, search_query=search_query
    )
    total = await repo.count_companies(search_query=search_query)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    return templates.TemplateResponse(
        "companies.html",
        {
            "request": request,
            "title": "Şirketler",
            "companies": companies,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "search_query": search_query,
            **_base_ctx(),
        },
    )


@app.get("/disclosure/{index}")
async def disclosure_detail(request: Request, index: int):
    """Tekil bildirim detay sayfası — full_text + fiyat hareketleri."""
    disclosure = await repo.get_disclosure_by_index(index)
    if disclosure is None:
        raise HTTPException(status_code=404, detail=f"Bildirim #{index} bulunamadı.")

    related: list = []
    if disclosure.stock_codes:
        code = disclosure.stock_codes.split(",")[0].strip()
        all_related = await repo.get_disclosures(limit=6, stock_code=code)
        related = [d for d in all_related if d.disclosure_index != index][:5]

    return templates.TemplateResponse(
        "disclosure.html",
        {
            "request": request,
            "title": disclosure.title or disclosure.subject or f"Bildirim #{index}",
            "disclosure": disclosure,
            "related": related,
            **_base_ctx(),
        },
    )


@app.get("/api/test-pdf-parser")
async def api_test_pdf_parser(limit: int = 10) -> JSONResponse:
    """Test endpoint for parsing PDFs of disclosures."""
    pending_disclosures = await repo.get_disclosures_with_unparsed_pdfs(limit=limit)
    if not pending_disclosures:
        return JSONResponse(content={"message": "No pending PDFs found."})

    results = []
    success_count = 0

    for disc in pending_disclosures:
        # Determine the PDF link
        pdf_link = disc.pdf_link
        if not pdf_link and disc.attachment_urls:
            for attachment in disc.attachment_urls:
                if 'url' in attachment and str(attachment.get('fileName', '')).lower().endswith('.pdf'):
                    pdf_link = attachment['url']
                    break
        
        if not pdf_link:
            results.append({"index": disc.disclosure_index, "status": "skipped_no_link"})
            continue
            
        log.info(f"Downloading PDF for index {disc.disclosure_index}: {pdf_link}")
        text = await extract_text_from_pdf_url(pdf_link)
        
        if text:
            await repo.upsert_pdf_text(disc.disclosure_index, text)
            success_count += 1
            results.append({
                "index": disc.disclosure_index, 
                "status": "success", 
                "length": len(text)
            })
        else:
            results.append({"index": disc.disclosure_index, "status": "failed"})

    return JSONResponse(content={
        "total_processed": len(pending_disclosures),
        "success_count": success_count,
        "details": results
    })


@app.get("/api/test-pdf-extractor")
async def api_test_pdf_extractor(limit: int = 5) -> JSONResponse:
    """Yerel Gemma ile PDF metinlerinden yatırımcı özeti çıkaran test endpoint'i."""
    pending_pdfs = await repo.get_pdfs_needing_extraction(limit=limit)
    if not pending_pdfs:
        return JSONResponse(content={"message": "No pending PDF texts found for extraction."})

    results = []
    success_count = 0

    for item in pending_pdfs:
        disclosure_index = item["disclosure_index"]
        text = item["extracted_text"]
        category = item["news_category"]
        dtype = item["disclosure_type"]
        
        log.info(f"Local LLM ile özetleniyor: {disclosure_index}")
        summary = await generate_summary(text)
        
        if summary and summary != "Özetleme işlemi başarısız.":
            parsed_json = {
                "summary": summary,
                "source": "gemma_local",
            }
            
            category_type = category if category else dtype
            await repo.upsert_pdf_parsed_data(disclosure_index, category_type, parsed_json)
            success_count += 1
            results.append({
                "index": disclosure_index,
                "status": "success",
                "extracted_keys": list(parsed_json.keys()),
                "data": parsed_json
            })
        else:
            results.append({"index": disclosure_index, "status": "failed"})

    return JSONResponse(content={
        "total_processed": len(pending_pdfs),
        "success_count": success_count,
        "details": results
    })


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
