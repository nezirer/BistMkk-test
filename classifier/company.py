"""Şirket bazlı sınıflandırma ve normalize etme."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict

from utils.logger import get_logger

log = get_logger(__name__)


def _slugify(text: str) -> str:
    """Türkçe karakterler dahil metni URL-dostu slug'a dönüştürür."""
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
    text = text.translate(tr_map).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


@dataclass
class CompanyInfo:
    """In-memory şirket kaydı."""

    stock_code: str
    company_name: str
    slug: str = field(default="")

    def __post_init__(self) -> None:
        self.stock_code = self.stock_code.strip().upper()
        if not self.slug:
            self.slug = _slugify(self.company_name)


# ---------------------------------------------------------------------------
# In-memory şirket dizini
# ---------------------------------------------------------------------------

_company_registry: Dict[str, CompanyInfo] = {}


def get_company_slug(stock_code: str, company_name: str) -> str:
    """
    Hisse kodu ve şirket adından URL-dostu slug üretir; şirketi
    in-memory dizine kaydeder.

    Args:
        stock_code: Hisse senedi kodu (örn: 'THYAO').
        company_name: Şirketin tam ticari unvanı.

    Returns:
        URL-dostu slug (örn: 'turk-hava-yollari-as').
    """
    normalized = stock_code.strip().upper()

    if not normalized:
        return _slugify(company_name) if company_name else ""

    if normalized in _company_registry:
        return _company_registry[normalized].slug

    info = CompanyInfo(stock_code=normalized, company_name=company_name)
    _company_registry[normalized] = info
    log.debug("Yeni şirket dizine eklendi: {} → {}", normalized, info.slug)
    return info.slug


def update_registry(disclosures: list) -> None:
    """
    Bildirim listesindeki şirketleri in-memory dizine ekler/günceller.
    APScheduler döngüsü her çalışmada bu fonksiyonu çağırır.

    Args:
        disclosures: DisclosureRaw nesnelerinin listesi.
    """
    added = 0
    for d in disclosures:
        code = d.stock_codes.strip().upper()
        if not code:
            continue
        if code not in _company_registry:
            info = CompanyInfo(stock_code=code, company_name=d.company_name)
            _company_registry[code] = info
            added += 1

    if added:
        log.info(
            "Şirket dizini güncellendi: {} yeni şirket eklendi (toplam: {}).",
            added,
            len(_company_registry),
        )


def get_all_companies() -> list[CompanyInfo]:
    """Dizindeki tüm şirketleri hisse kodu sırasına göre döndürür."""
    return sorted(_company_registry.values(), key=lambda c: c.stock_code)


def get_company(stock_code: str) -> CompanyInfo | None:
    """Hisse koduna göre şirket bilgisini döndürür; bulunamazsa None."""
    return _company_registry.get(stock_code.strip().upper())
