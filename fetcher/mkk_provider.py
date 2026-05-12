"""
MKK VYK API üzerinden KAP bildirimlerine erişim sağlar.
Resmi API spec: apispec.json (OpenAPI 3.0.3, version 0.0.1)

Base URL (test) : https://apigwdev.mkk.com.tr/api/vyk
Base URL (prod) : https://apiint.mkk.com.tr/api/vyk   (henüz test edilmedi)

Auth:
  Her iki ortamda da : Authorization: Basic base64(user:pass)
  Spec: basicAuth (HTTP Basic) — kullanıcı adı ve şifre portal'dan alınır.

Kullanıcı .env'e koymalı:
  MKK_API_KEY      = <portal API key>
  MKK_API_BASE_URL = https://apigwdev.mkk.com.tr/api/vyk
  MKK_ENV          = test   # veya prod

Kullanılan endpoint'ler (spec /paths):
  GET /lastDisclosureIndex                  → son yayın id
  GET /disclosures?disclosureIndex={n}      → özet bildirim listesi (max 50)
  GET /disclosureDetail/{index}?fileType=html → şirket adı, hisse kodu, tarih
  GET /members                              → şirket listesi
  GET /memberDetail/{id}                    → şirket detayı
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic_settings import BaseSettings

from fetcher.base_provider import BaseKAPProvider
from models.disclosure import DisclosureRaw
from utils.logger import get_logger

log = get_logger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0  # saniye — 429 exponential backoff başlangıcı


class MKKSettings(BaseSettings):
    mkk_api_user: str = ""
    mkk_api_pass: str = ""
    mkk_api_key: str = ""
    mkk_bearer_token: str = ""
    mkk_api_base_url: str = "https://apigwdev.mkk.com.tr/api/vyk"
    mkk_env: str = "test"

    model_config = {"env_file": ".env", "extra": "ignore"}


class MKKProvider(BaseKAPProvider):
    """
    MKK API Gateway üzerinden KAP bildirimlerine erişim sağlar.
    Test ortamında HTTP Basic Auth, Üretim (Prod) ortamında Bearer Token kullanılır.
    """

    def __init__(self) -> None:
        self.settings = MKKSettings()
        self.base_url = self.settings.mkk_api_base_url.rstrip("/")
        self.is_prod = self.settings.mkk_env.lower() in ("prod", "production")

        # Spec: basicAuth (HTTP Basic) - Her iki ortamda da geçerli.
        self.auth = httpx.BasicAuth(
            username=self.settings.mkk_api_user,
            password=self.settings.mkk_api_pass,
        )
        
        self.headers: dict[str, str] = {"Accept": "application/json"}
        
        self.auth_token: str | None = self.settings.mkk_bearer_token if self.settings.mkk_bearer_token else None
        self.token_expires_at: float = float('inf')  # Manuel token olduğu için süre hesabı yapılmıyor

        self.client = httpx.AsyncClient(
            auth=self.auth,
            headers=self.headers,
            timeout=60.0,
            follow_redirects=True,
        )

    async def _ensure_token(self) -> None:
        """Kullanıcı isteği ile OTO-TOKEN kapatıldı, manuel token kullanılıyor (veya Basic Auth)."""
        if self.is_prod and not self.auth_token:
            log.info("Prod ortamı için MKK_BEARER_TOKEN bulunamadı, Basic Auth ile devam edilecek.")
        return

    # ------------------------------------------------------------------
    # İç yardımcı
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """
        GET isteği gönderir.
        - 401 → API key / yetki hatası log'u
        - 403 → sözleşme hatası log'u
        - 429 → exponential backoff, max 3 deneme
        - Timeout → retry
        Başarıda parse edilmiş JSON döner; hata durumunda exception fırlatır.
        """
        url = f"{self.base_url}{path}"
        
        if self.is_prod:
            await self._ensure_token()
            req_headers = dict(self.headers)
            if self.auth_token:
                req_headers["Authorization"] = f"Bearer {self.auth_token}"
        else:
            req_headers = self.headers
            
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = await self.client.get(url, params=params, headers=req_headers)

                if resp.status_code == 401:
                    log.error(
                        "MKK 401 — API Key geçersiz veya IP yetkisiz. "
                        "Portal: https://apiportal.mkk.com.tr"
                    )
                    resp.raise_for_status()

                if resp.status_code == 403:
                    log.error(
                        "MKK 403 — Borsa İstanbul veri dağıtım sözleşmesi gerekli. "
                        "Portal: https://apiportal.mkk.com.tr"
                    )
                    resp.raise_for_status()

                if resp.status_code == 429:
                    delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    log.warning(
                        "MKK 429 — Rate limit. Deneme {}/{}, {} sn bekleniyor.",
                        attempt, _MAX_RETRIES, delay,
                    )
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()

                resp.raise_for_status()
                return resp.json()

            except httpx.TimeoutException:
                log.error(
                    "MKK zaman aşımı: {} (deneme {}/{})", url, attempt, _MAX_RETRIES
                )
                if attempt == _MAX_RETRIES:
                    raise
                await asyncio.sleep(_RETRY_BASE_DELAY * attempt)

            except httpx.HTTPStatusError:
                raise

            except Exception as exc:
                log.error("MKK beklenmedik hata: {} — {}", url, exc)
                raise

        return None  # ulaşılmaz

    # ------------------------------------------------------------------
    # Public metodlar
    # ------------------------------------------------------------------

    async def fetch_latest(self, limit: int = 50, since_index: int = 0) -> list[DisclosureRaw]:
        """
        1. GET /lastDisclosureIndex           → son yayın id'sini al
        2. GET /disclosures?disclosureIndex=n → özet liste (max 50 kayıt döner)
        3. Her kayıt için GET /disclosureDetail/{index}?fileType=html
           → şirket adı, hisse kodu, yayın tarihi, konu zenginleştirmesi
        4. DisclosureRaw listesi olarak döndür

        since_index > 0 ise sadece o index'ten sonraki bildirimler çekilir.
        Bu, her polling döngüsünde gereksiz API çağrısı yapılmasını engeller.
        """
        # Adım 1: Son index
        try:
            idx_payload = await self._get("/lastDisclosureIndex")
        except Exception as exc:
            log.error("lastDisclosureIndex alınamadı: {}", exc)
            return []

        if not isinstance(idx_payload, dict) or "lastDisclosureIndex" not in idx_payload:
            log.warning("lastDisclosureIndex beklenen formatta değil: {}", idx_payload)
            return []

        last_index = int(idx_payload["lastDisclosureIndex"])
        log.info("KAP son bildirim index: {}", last_index)

        # since_index verilmişse ve güncel index'e eşit/büyükse yeni bildirim yok
        if since_index > 0 and since_index >= last_index:
            log.info("Yeni bildirim yok (since_index={}, last_index={}).", since_index, last_index)
            return []

        # Adım 2: Özet liste
        # since_index > 0 → sadece o index'ten sonrasını çek (API rate limit koruması)
        # since_index = 0 → ilk çalışma; son limit kadar bildirimi geriden başlayarak çek
        if since_index > 0:
            start_index = since_index + 1
        else:
            start_index = max(0, last_index - (limit - 1))
        try:
            items = await self._get(
                "/disclosures",
                params={"disclosureIndex": start_index},
            )
        except Exception as exc:
            log.error("disclosures çekilemedi (index={}): {}", last_index, exc)
            return []

        if not items:
            log.info("KAP: No new disclosures since index {}", last_index)
            return []

        if not isinstance(items, list):
            log.warning("KAP /disclosures liste dönmedi (tip: {})", type(items).__name__)
            return []

        # Adım 3: Her bildirim için detay çek → zenginleştir
        # MKK API tek seferde en fazla 50 bildirim döndürür.
        # Eğer limit 50'den büyükse (örn: 500), API'nin döndürdüğü kadarını (max 50) işleriz.
        # Bir sonraki polling döngüsünde (3 dk sonra) kalanlar çekilmeye devam eder.
        results: list[DisclosureRaw] = []
        batch = items[:limit]
        for raw_item in batch:
            try:
                disclosure = DisclosureRaw.from_list_item(raw_item)
            except Exception as exc:
                log.warning(
                    "DisclosureRaw parse hatası atlandı (index={}): {}",
                    raw_item.get("disclosureIndex"), exc,
                )
                continue

            # Detay çağrısı — hata olursa özet verisiyle devam et
            try:
                detail = await self._get(
                    f"/disclosureDetail/{disclosure.disclosure_index}",
                    params={"fileType": "html"},
                )
                if isinstance(detail, dict):
                    disclosure.enrich_from_detail(detail)
            except Exception as exc:
                log.warning(
                    "disclosureDetail alınamadı (index={}), özet veriyle devam ediliyor: {}",
                    disclosure.disclosure_index, exc,
                )

            results.append(disclosure)

        log.info(
            "KAP fetch_latest tamamlandı: {} bildirim (son index: {}).",
            len(results), last_index,
        )
        return results

    async def fetch_by_stock_code(self, code: str) -> list[DisclosureRaw]:
        """
        Belirli bir hisse koduna ait şirketin son bildirimlerini çeker.
        Önce /members listesinden companyId bulunur, ardından /disclosures
        filtrelenerek getirilir.
        """
        companies = await self.fetch_companies()
        company_id = next(
            (str(c.get("id", "")) for c in companies
             if code.upper() in [str(ec).upper() for ec in (c.get("exchCodes") or [])]),
            None,
        )
        if not company_id:
            log.warning("Hisse kodu için şirket bulunamadı: {}", code)
            return []

        try:
            idx_payload = await self._get("/lastDisclosureIndex")
            last_index = idx_payload.get("lastDisclosureIndex") if isinstance(idx_payload, dict) else None
            if not last_index:
                return []

            # Son 100 bildirimi geriden başlayarak çek (fetch_latest mantığıyla aynı)
            start_index = max(0, int(last_index) - 99)
            items = await self._get(
                "/disclosures",
                params={"disclosureIndex": start_index, "companyId": [company_id]},
            )
        except Exception as exc:
            log.error("fetch_by_stock_code başarısız (code={}): {}", code, exc)
            return []

        if not isinstance(items, list):
            return []

        results: list[DisclosureRaw] = []
        for raw_item in items:
            try:
                results.append(DisclosureRaw.from_list_item(raw_item))
            except Exception as exc:
                log.warning("parse hatası (atlandı): {}", exc)
        return results

    async def fetch_companies(self) -> list[dict]:
        """GET /members → tüm KAP üyesi şirket listesi."""
        try:
            data = await self._get("/members")
            return data if isinstance(data, list) else []
        except Exception as exc:
            log.error("members alınamadı: {}", exc)
            return []

    async def health_check(self) -> bool:
        """GET /lastDisclosureIndex ile gateway bağlantısını doğrular."""
        try:
            payload = await self._get("/lastDisclosureIndex")
            return isinstance(payload, dict) and "lastDisclosureIndex" in payload
        except Exception as exc:
            log.error("MKK health check başarısız: {}", exc)
            return False

    async def close(self) -> None:
        await self.client.aclose()
