"""
MKK API Portal üzerinden KAP verilerine erişim sağlar.
Resmi API: https://apiportal.mkk.com.tr

Test ortamı : https://apigwdev.mkk.com.tr   (alternatif: https://apitestint.mkk.com.tr)
Prod ortamı : https://apiint.mkk.com.tr

Erişim için gerekli:
- MKK API Portal'den API KEY alınması (https://apiportal.mkk.com.tr)
- IP yetkilendirmesi (MKK tarafından yapılır)
- Borsa İstanbul veri dağıtım sözleşmesi (kurumsal kullanım için)

Kullanıcı aşağıdaki değişkenleri .env'e koymalı:
MKK_API_KEY=...
MKK_API_BASE_URL=https://apigwdev.mkk.com.tr   # test için
MKK_ENV=test  # "test" veya "prod"
"""
from __future__ import annotations

import httpx
from pydantic_settings import BaseSettings

from fetcher.base_provider import BaseKAPProvider
from models.disclosure import DisclosureRaw
from utils.logger import get_logger

log = get_logger(__name__)


class MKKSettings(BaseSettings):
    mkk_api_key: str = ""
    mkk_api_base_url: str = "https://apigwdev.mkk.com.tr"
    mkk_env: str = "test"

    model_config = {"env_file": ".env", "extra": "ignore"}


class MKKProvider(BaseKAPProvider):
    """
    MKK API Gateway üzerinden KAP verilerine erişim sağlar.
    API Key ve endpoint bilgilerini .env dosyasından okur.
    """

    def __init__(self) -> None:
        self.settings = MKKSettings()
        self.base_url = self.settings.mkk_api_base_url
        self.headers = {
            "Authorization": f"Bearer {self.settings.mkk_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=20.0,
            follow_redirects=True,
        )

    async def fetch_latest(self, limit: int = 50) -> list[DisclosureRaw]:
        """
        MKK KAP Veri Yayın Servisi üzerinden son bildirimleri çeker.
        ⚠️ Endpoint path'i kullanıcının MKK API Portal'den aldığı
           dokümana göre güncellenmelidir.
        """
        # TODO: Kullanıcı MKK API Portal'den aldığı endpoint path'i buraya yazacak
        # Örnek: /kap/v1/disclosures veya /bildirim/liste gibi
        log.warning("MKK endpoint path henüz yapılandırılmadı, boş liste dönüyor.")
        return []

    async def fetch_by_stock_code(self, code: str) -> list[DisclosureRaw]:
        # TODO: Kullanıcı endpoint path'ini girdikten sonra implemente et
        return []

    async def fetch_companies(self) -> list[dict]:
        # TODO: Kullanıcı endpoint path'ini girdikten sonra implemente et
        return []

    async def health_check(self) -> bool:
        try:
            resp = await self.client.get(f"{self.base_url}")
            return resp.status_code < 500
        except Exception as exc:
            log.error("MKK health check başarısız: {}", exc)
            return False

    async def close(self) -> None:
        await self.client.aclose()
