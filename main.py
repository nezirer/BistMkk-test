"""FastAPI giriş noktası — APScheduler + in-memory store."""
from __future__ import annotations

import os
from collections import deque

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
from fetcher.base_provider import BaseKAPProvider
from fetcher.provider_factory import get_provider
from models.disclosure import DisclosureClassified, DisclosureRaw
from utils.logger import get_logger

log = get_logger(__name__)
templates = Jinja2Templates(directory="web/templates")

# ---------------------------------------------------------------------------
# In-memory store — max 1000 kayıt (deque otomatik kırpar)
# ---------------------------------------------------------------------------

_store: deque[DisclosureClassified] = deque(maxlen=1000)
_seen_ids: set[int] = set()
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
    """KAP'tan son bildirimleri çekip sınıflandırarak store'a ekler."""
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
    for raw in raw_items:
        if raw.disclosure_index in _seen_ids:
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

        _store.appendleft(classified)
        _seen_ids.add(raw.disclosure_index)
        new_count += 1

    new_items = [r for r in raw_items if r.disclosure_index not in (_seen_ids - {d.disclosure_index for d in _store})]
    company_svc.update_registry(new_items)

    log.info("Polling tamamlandı: {} yeni bildirim eklendi (toplam store: {}).", new_count, len(_store))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _provider
    log.info("KAP Classifier başlatılıyor (provider: {})...", _provider_label())
    _provider = get_provider()
    await _fetch_and_classify()
    _scheduler.add_job(_fetch_and_classify, "interval", minutes=3, id="kap_poll")
    _scheduler.start()
    log.info("APScheduler başlatıldı — her 3 dakikada bir polling.")
    yield
    _scheduler.shutdown(wait=False)
    log.info("KAP Classifier kapatılıyor...")


# ---------------------------------------------------------------------------
# FastAPI uygulaması
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KAP Classifier",
    description="KAP bildirimlerini çekip sınıflandıran MVP uygulama",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="web/static"), name="static")


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _sorted_store() -> list[DisclosureClassified]:
    """Store'daki bildirimleri publishDate'e göre tersten sıralar."""
    items = list(_store)
    items.sort(
        key=lambda d: d.publish_datetime or __import__("datetime").datetime.min,
        reverse=True,
    )
    return items


# ---------------------------------------------------------------------------
# Endpoint'ler
# ---------------------------------------------------------------------------

def _base_ctx() -> dict:
    """Tüm template'lerin ortak ihtiyaç duyduğu context değişkenleri."""
    return {
        "provider_name": _provider_name(),
        "provider_label": _provider_label(),
        "category_labels": news_svc.CATEGORY_LABELS,
    }


@app.get("/")
async def index(request: Request):
    """Ana sayfa — son 50 bildirimi listeler."""
    disclosures = _sorted_store()[:50]
    companies = company_svc.get_all_companies()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "KAP Classifier",
            "disclosures": disclosures,
            "companies": companies,
            "categories": news_svc.ALL_CATEGORIES,
            "total": len(_store),
            **_base_ctx(),
        },
    )


@app.get("/company/{stock_code}")
async def company_detail(request: Request, stock_code: str):
    """Şirkete ait tüm bildirimleri listeler."""
    code = stock_code.strip().upper()
    company = company_svc.get_company(code)
    if company is None and not any(d.stock_codes == code for d in _store):
        raise HTTPException(status_code=404, detail=f"'{code}' hisse kodu bulunamadı.")

    disclosures = [d for d in _sorted_store() if d.stock_codes == code]
    return templates.TemplateResponse(
        "company.html",
        {
            "request": request,
            "title": f"{code} — Bildirimleri",
            "stock_code": code,
            "company_name": company.company_name if company else code,
            "disclosures": disclosures,
            **_base_ctx(),
        },
    )


@app.get("/category/{category}")
async def category_detail(request: Request, category: str):
    """Kategoriye ait tüm bildirimleri listeler."""
    label = news_svc.get_category_label(category)
    disclosures = [
        d for d in _sorted_store()
        if d.news_category == label
    ]
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
async def api_disclosures(limit: int = 50, stock_code: str = "", category: str = "") -> JSONResponse:
    """JSON API — bildirim listesi (isteğe bağlı filtreler: stock_code, category)."""
    items = _sorted_store()

    if stock_code:
        items = [d for d in items if d.stock_codes == stock_code.strip().upper()]
    if category:
        label = news_svc.get_category_label(category)
        items = [d for d in items if d.news_category == label]

    items = items[:limit]
    return JSONResponse(
        content={
            "total": len(items),
            "disclosures": [d.model_dump(by_alias=True) for d in items],
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok", "store_size": len(_store)}


@app.get("/status")
async def status():
    """Provider durumu ve sistem bilgisi."""
    provider_ok = await _provider.health_check() if _provider else False
    return {
        "status": "ok",
        "provider": _provider_name(),
        "provider_label": _provider_label(),
        "provider_healthy": provider_ok,
        "store_size": len(_store),
        "seen_ids": len(_seen_ids),
    }
