"""Haber türü bazlı sınıflandırma — MKK disclosureType/disclosureClass + keyword matching."""
from __future__ import annotations

from models.disclosure import DisclosureRaw
from utils.logger import get_logger

log = get_logger(__name__)

# MKK disclosureType/Class kodlarından kategori eşlemesi (öncelikli)
_TYPE_MAP: dict[str, str] = {
    "FR":  "finansal_rapor",
    "ODA": "ozel_durum",
    "CA":  "genel_kurul",   # Hak kullanım: genel kurul, sermaye artırımı, temettü
    "FON": "diger",
    "DUY": "diger",
    "DG":  "diger",
}

# title / subject keyword fallback
CATEGORIES: dict[str, list[str]] = {
    "finansal_rapor": ["finansal rapor", "ara dönem", "yıllık rapor", "bilanço", "gelir tablosu"],
    "ozel_durum":     ["özel durum", "içsel bilgi", "önemli gelişme"],
    "genel_kurul":    ["genel kurul", "ogk", "ook", "genel k"],
    "sermaye":        ["sermaye artırımı", "sermaye azaltımı", "bedelsiz", "rüçhan"],
    "yonetim":        ["yönetim kurulu", "atama", "istifa", "genel müdür"],
    "temettü":        ["temettü", "kâr payı", "kar payı", "dividend"],
    "diger":          [],
}

CATEGORY_LABELS: dict[str, str] = {
    "finansal_rapor": "Finansal Rapor",
    "ozel_durum":     "Özel Durum",
    "genel_kurul":    "Genel Kurul",
    "sermaye":        "Sermaye",
    "yonetim":        "Yönetim",
    "temettü":        "Temettü",
    "diger":          "Diğer",
}

ALL_CATEGORIES = list(CATEGORIES.keys())


def classify(disclosure: DisclosureRaw) -> str:
    """
    Bildirimi MKK disclosureType kodu ile önce hızlı eşler;
    eşleşme bulunamazsa title/subject keyword matching'e düşer.

    Returns:
        CATEGORIES anahtarlarından biri (örn: 'finansal_rapor', 'diger').
    """
    # 1. disclosureType kodu ile doğrudan eşleştir (FR, ODA, CA vb.)
    dtype = (disclosure.disclosure_type or "").upper().strip()
    if dtype in _TYPE_MAP:
        # CA altında sermaye/temettü/genel kurul keyword'leri ile ince ayrım yap
        if dtype == "CA":
            haystack = f"{disclosure.title} {disclosure.subject}".lower()
            for cat in ("sermaye", "temettü", "genel_kurul"):
                for kw in CATEGORIES[cat]:
                    if kw in haystack:
                        log.debug(
                            "Bildirim {} → CA alt kategori '{}' (kw: '{}')",
                            disclosure.disclosure_index, cat, kw,
                        )
                        return cat
        mapped = _TYPE_MAP[dtype]
        log.debug(
            "Bildirim {} → '{}' (disclosureType={})",
            disclosure.disclosure_index, mapped, dtype,
        )
        return mapped

    # 2. Keyword fallback — title + subject üzerinde
    haystack = f"{disclosure.title} {disclosure.subject}".lower()
    for category, keywords in CATEGORIES.items():
        if category == "diger":
            continue
        for kw in keywords:
            if kw in haystack:
                log.debug(
                    "Bildirim {} → '{}' (keyword: '{}')",
                    disclosure.disclosure_index, category, kw,
                )
                return category

    log.debug(
        "Bildirim {} → 'diger' (eşleşme yok, type='{}', haystack='{}')",
        disclosure.disclosure_index, dtype, haystack[:80],
    )
    return "diger"


def get_category_label(category_key: str) -> str:
    """Kategori anahtarını insan okunabilir Türkçe etikete çevirir."""
    return CATEGORY_LABELS.get(category_key, "Diğer")
