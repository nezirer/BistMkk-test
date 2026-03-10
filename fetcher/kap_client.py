"""
KAP istemcisi — Bu modül artık kullanılmıyor.

kap.org.tr/tr/api/disclosures endpoint'i public erişime kapalı olduğu için
bu istemci kaldırıldı. Yeni mimari için bkz: fetcher/base_provider.py
"""
from __future__ import annotations


class KAPAPIError(Exception):
    """Geriye dönük uyumluluk için bırakıldı. Artık kullanılmamalı."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class KAPClient:
    """
    Kullanımdan kalkmış KAP istemcisi.

    Bu class artık kullanılmıyor. Lütfen fetcher/provider_factory.py
    üzerinden get_provider() kullanın.
    """
