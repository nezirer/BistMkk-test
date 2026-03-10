"""Haber türü bazlı sınıflandırma — kural tabanlı keyword matching."""
from __future__ import annotations

from models.disclosure import DisclosureRaw
from utils.logger import get_logger

log = get_logger(__name__)

CATEGORIES: dict[str, list[str]] = {
    "finansal_rapor": ["Finansal Rapor", "Ara Dönem", "Yıllık Rapor"],
    "ozel_durum": ["Özel Durum", "İçsel Bilgi"],
    "genel_kurul": ["Genel Kurul", "OGK", "OOK"],
    "sermaye": ["Sermaye Artırımı", "Sermaye Azaltımı", "Bedelsiz"],
    "yonetim": ["Yönetim Kurulu", "Atama", "İstifa"],
    "temettü": ["Temettü", "Kâr Payı"],
    "diger": [],
}

CATEGORY_LABELS: dict[str, str] = {
    "finansal_rapor": "Finansal Rapor",
    "ozel_durum": "Özel Durum",
    "genel_kurul": "Genel Kurul",
    "sermaye": "Sermaye",
    "yonetim": "Yönetim",
    "temettü": "Temettü",
    "diger": "Diğer",
}

ALL_CATEGORIES = list(CATEGORIES.keys())


def classify(disclosure: DisclosureRaw) -> str:
    """
    Bir bildirimi kural tabanlı keyword matching ile kategorize eder.

    basicType ve infoTypeDesc alanları kontrol edilir; eşleşme
    bulunamazsa 'diger' döndürülür.

    Args:
        disclosure: Ham KAP bildirim nesnesi.

    Returns:
        CATEGORIES anahtarlarından biri (örn: 'finansal_rapor', 'diger').
    """
    haystack = f"{disclosure.basic_type} {disclosure.info_type_desc}".lower()

    for category, keywords in CATEGORIES.items():
        if category == "diger":
            continue
        for kw in keywords:
            if kw.lower() in haystack:
                log.debug(
                    "Bildirim {} → kategori '{}' (eşleşen: '{}')",
                    disclosure.disclosure_index,
                    category,
                    kw,
                )
                return category

    log.debug(
        "Bildirim {} → kategori 'diger' (eşleşme yok: '{}')",
        disclosure.disclosure_index,
        haystack,
    )
    return "diger"


def get_category_label(category_key: str) -> str:
    """Kategori anahtarını insan okunabilir Türkçe etikete çevirir."""
    return CATEGORY_LABELS.get(category_key, "Diğer")
