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
import db.repository as repo
from db.connection import init_pool, close_pool, get_connection
from db.models import create_tables
from fetcher.base_provider import BaseKAPProvider
from fetcher.provider_factory import get_provider
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
        raw_items: list[DisclosureRaw] = await _provider.fetch_latest(limit=100)
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
    async with get_connection() as conn:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, create_tables, conn)

    # Provider ve ilk polling
    _provider = get_provider()
    await _fetch_and_classify()

    _scheduler.add_job(_fetch_and_classify, "interval", minutes=3, id="kap_poll")
    _scheduler.start()
    log.info("APScheduler başlatıldı — her 3 dakikada bir polling.")

    yield

    _scheduler.shutdown(wait=False)
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
