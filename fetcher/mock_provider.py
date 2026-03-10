"""
Geliştirme ortamında gerçek API olmadan test için kullanılır.
.env içinde KAP_PROVIDER=mock yazılırsa aktif olur.
"""
from __future__ import annotations

import json
from pathlib import Path

from fetcher.base_provider import BaseKAPProvider
from models.disclosure import DisclosureRaw

MOCK_DATA_PATH = Path("fetcher/mock_data.json")


class MockProvider(BaseKAPProvider):
    """
    Gerçek API olmadan geliştirmeye devam etmek için sahte veri sağlar.
    mock_data.json dosyasına gerçek KAP verisi kopyalanarak
    uçtan uca test yapılabilir.
    """

    async def fetch_latest(self, limit: int = 50) -> list[DisclosureRaw]:
        if MOCK_DATA_PATH.exists():
            raw = json.loads(MOCK_DATA_PATH.read_text(encoding="utf-8"))
            return [DisclosureRaw(**item) for item in raw[:limit]]
        return self._sample_data()[:limit]

    async def fetch_by_stock_code(self, code: str) -> list[DisclosureRaw]:
        data = await self.fetch_latest(200)
        return [d for d in data if code.upper() in (d.stock_codes or "").upper()]

    async def fetch_companies(self) -> list[dict]:
        return [
            {"code": "THYAO", "name": "Türk Hava Yolları A.O."},
            {"code": "GARAN", "name": "T. Garanti Bankası A.Ş."},
            {"code": "AKBNK", "name": "Akbank T.A.Ş."},
        ]

    async def health_check(self) -> bool:
        return True

    def _sample_data(self) -> list[DisclosureRaw]:
        return []
