"""
Pydantic v2 veri modelleri — schema-first tasarım.

Gelecekteki DB migration'ını kolaylaştırmak amacıyla tüm alanlar
açıklayıcı Field(description=...) ile belgelenmiştir.

Modeller:
    DisclosureRaw         — MKK VYK API /disclosures + /disclosureDetail birleşimi
    DisclosureClassified  — Sınıflandırılmış bildirim (ek alanlar dahil)
    ClassificationResult  — Şirket ve tür bazında gruplandırılmış sonuç yapısı
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator, model_validator

from utils.text import slugify


class DisclosureRaw(BaseModel):
    """
    MKK VYK API'den gelen birleşik bildirim verisi.

    /disclosures (özet liste) + /disclosureDetail (detay) endpoint'lerinin
    birleşiminden oluşturulur. Sadece /disclosures'dan gelen hafif nesneler
    için detay alanları opsiyoneldir.

    Alanlar MKK OpenAPI spec v0.0.1 (apispec.json) ile uyumludur.
    """

    # --- /disclosures endpoint'inden gelen zorunlu alanlar ---
    disclosure_index: int = Field(
        ...,
        alias="disclosureIndex",
        description="KAP sistemindeki tekil bildirim sırası / kimliği",
    )
    disclosure_type: str = Field(
        default="",
        alias="disclosureType",
        description="Bildirim tipi (FR, ODA, DG, DUY, FON, CA)",
    )
    disclosure_class: str = Field(
        default="",
        alias="disclosureClass",
        description="Bildirim sınıfı (FR, ODA, DG, DUY)",
    )
    title: str = Field(
        default="",
        alias="title",
        description="Bildirim gönderen şirket ünvanı (/disclosures'dan gelir)",
    )
    company_id: str = Field(
        default="",
        alias="companyId",
        description="Bildirim gönderen şirket id",
    )
    sub_report_ids: list[str] = Field(
        default_factory=list,
        alias="subReportIds",
        description="Bildirimin alt rapor id listesi",
    )
    accepted_data_file_types: list[str] = Field(
        default_factory=list,
        alias="acceptedDataFileTypes",
        description="Alınabilecek dosya tipleri (html, presentation)",
    )
    fund_id: str = Field(
        default="",
        alias="fundId",
        description="Fon id (fon bildirimi ise dolu gelir)",
    )
    fund_code: str = Field(
        default="",
        alias="fundCode",
        description="Fon kodu (fon bildirimi ise dolu gelir)",
    )

    # --- /disclosureDetail endpoint'inden gelen opsiyonel alanlar ---
    company_name: str = Field(
        default="",
        alias="companyName",
        description="Şirketin tam ticari unvanı (senderTitle'dan türetilir)",
    )
    stock_codes: str = Field(
        default="",
        alias="stockCodes",
        description="İlgili hisse senedi kodu/ları (senderExchCodes'dan türetilir)",
    )
    publish_date: str = Field(
        default="",
        alias="publishDate",
        description="Yayınlanma tarihi ve saati (time alanından türetilir)",
    )
    subject: str = Field(
        default="",
        alias="subject",
        description="Bildirimin konusu / özeti (subject.tr alanından türetilir)",
    )
    year: str = Field(
        default="",
        alias="year",
        description="Bildirimin ait olduğu mali yıl",
    )
    kap_link: str = Field(
        default="",
        alias="kapLink",
        description="KAP sayfasındaki bildirim bağlantısı (link alanından gelir)",
    )
    full_text: str = Field(
        default="",
        alias="fullText",
        description=(
            "Bildirimin tam metni: summary.tr + htmlMessages Base64 decode "
            "edilip HTML striplenerek elde edilir. Sentiment analizi için kullanılır."
        ),
    )
    attachment_urls: list[dict] = Field(
        default_factory=list,
        alias="attachmentUrls",
        description="Bildirim ek dosyaları [{url, fileName}]",
    )
    related_disclosure_index: str = Field(
        default="",
        alias="relatedDisclosureIndex",
        description="İlişkili bildirimin index'i (varsa)",
    )
    period: str = Field(
        default="",
        alias="period",
        description="Bildirimin ait olduğu dönem (period.tr alanından türetilir)",
    )
    related_stocks: list[str] = Field(
        default_factory=list,
        alias="relatedStocks",
        description="İlişkili hisse kodları listesi (relatedStocks[].code)",
    )
    publish_datetime_utc: datetime | None = Field(
        default=None,
        alias="publishDatetimeUtc",
        description=(
            "Yayınlanma tarihinin UTC TIMESTAMPTZ karşılığı. "
            "publish_date string'inden parse edilip Türkiye saatinden (UTC+3) "
            "UTC'ye çevrilir. Fiyat hesaplamalarında bu alan kullanılır."
        ),
    )
    pdf_link: str = Field(
        default="",
        alias="pdfLink",
        description="İlk ek dosyanın (tercihen PDF) doğrudan bağlantısı",
    )

    model_config = {
        "populate_by_name": True,
        "str_strip_whitespace": True,
    }

    @field_validator("disclosure_index", mode="before")
    @classmethod
    def coerce_index_to_int(cls, v: Any) -> int:
        """API string olarak dönebilir, int'e zorluyoruz."""
        return int(v)

    @field_validator("stock_codes", mode="before")
    @classmethod
    def normalize_stock_codes(cls, v: Any) -> str:
        """Hisse kodunu büyük harfe ve boşluksuz formata getirir."""
        return str(v).strip().upper() if v else ""

    @property
    def publish_datetime(self) -> datetime | None:
        """
        publish_date alanını datetime nesnesine dönüştürür.

        MKK API 'time' alanı ISO-8601 veya DD.MM.YYYY HH:MM formatında
        gelebilir; her ikisini de dener.
        """
        for fmt in (
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(self.publish_date, fmt)
            except ValueError:
                continue
        return None

    def _parse_publish_datetime_utc(self) -> datetime | None:
        """
        publish_date string'ini parse edip UTC'ye çevirir.
        KAP/MKK zaman damgaları Türkiye saatindedir (UTC+3).
        """
        _TURKEY_TZ = timezone(timedelta(hours=3))
        dt = self.publish_datetime
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_TURKEY_TZ)
        return dt.astimezone(timezone.utc)

    @classmethod
    def from_list_item(cls, item: dict) -> "DisclosureRaw":
        """
        /disclosures endpoint'inden gelen özet item'dan nesne oluşturur.
        Detay alanları (companyName, stockCodes, publishDate) boş kalır;
        enrich_from_detail() ile sonradan doldurulur.
        """
        return cls(**item)

    def enrich_from_detail(self, detail: dict) -> None:
        """
        /disclosureDetail endpoint yanıtından detay alanlarını doldurur.

        MKK detail response alanları:
          senderTitle      → company_name
          senderExchCodes  → stock_codes (virgülle birleştirilir)
          time             → publish_date
          subject.tr       → subject
          year             → year
          link             → kap_link
          summary.tr       → full_text'e eklenir
          htmlMessages[].tr → Base64 decode + HTML strip → full_text'e eklenir
        """
        self.company_name = detail.get("senderTitle", "") or ""

        exch_codes: list = detail.get("senderExchCodes", []) or []
        self.stock_codes = ",".join(str(c).strip().upper() for c in exch_codes if c)

        self.publish_date = detail.get("time", "") or ""

        subject_obj = detail.get("subject")
        if isinstance(subject_obj, dict):
            self.subject = subject_obj.get("tr", "") or ""
        elif isinstance(subject_obj, str):
            self.subject = subject_obj

        self.year = str(detail.get("year", "")) or ""
        self.kap_link = detail.get("link", "") or ""

        # --- full_text: summary + htmlMessages içeriği ---
        text_parts: list[str] = []

        summary_obj = detail.get("summary")
        if isinstance(summary_obj, dict):
            summary_tr = (summary_obj.get("tr") or "").strip()
            if summary_tr:
                text_parts.append(summary_tr)
        elif isinstance(summary_obj, str) and summary_obj.strip():
            text_parts.append(summary_obj.strip())

        for msg in detail.get("htmlMessages", []) or []:
            b64 = (msg.get("tr") or "").strip() if isinstance(msg, dict) else ""
            if not b64:
                continue
            try:
                raw_bytes = base64.b64decode(b64)
                try:
                    html = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    html = raw_bytes.decode("iso-8859-9", errors="replace")
                soup = BeautifulSoup(html, "html.parser")
                plain = soup.get_text(separator=" ", strip=True)
                plain = re.sub(r"\s{2,}", " ", plain).strip()
                if plain:
                    text_parts.append(plain)
            except Exception:
                pass

        self.full_text = "\n\n".join(text_parts)[:8000]

        # --- attachmentUrls ---
        raw_attachments = detail.get("attachmentUrls") or []
        self.attachment_urls = [
            {"url": att.get("url", ""), "fileName": att.get("fileName", "")}
            for att in raw_attachments
            if isinstance(att, dict) and att.get("url")
        ]

        # --- relatedDisclosureIndex ---
        rdi = detail.get("relatedDisclosureIndex")
        if isinstance(rdi, dict):
            self.related_disclosure_index = str(rdi.get("relatedDisclosureIndex", "")) or ""
        else:
            self.related_disclosure_index = str(rdi) if rdi else ""

        # --- period ---
        period_obj = detail.get("period")
        if isinstance(period_obj, dict):
            self.period = period_obj.get("tr", "") or ""
        elif isinstance(period_obj, str):
            self.period = period_obj
        else:
            self.period = ""

        # --- relatedStocks ---
        raw_rs = detail.get("relatedStocks") or []
        self.related_stocks = [
            str(s.get("code", "")).strip().upper()
            for s in raw_rs
            if isinstance(s, dict) and s.get("code")
        ]

        # --- publish_datetime_utc ---
        self.publish_datetime_utc = self._parse_publish_datetime_utc()

        # --- pdf_link ---
        self.pdf_link = ""
        if self.attachment_urls:
            # Önce içinde "pdf" geçen ilk dosyayı bulmaya çalış
            for att in self.attachment_urls:
                if "pdf" in att.get("fileName", "").lower() or "pdf" in att.get("url", "").lower():
                    self.pdf_link = att.get("url", "")
                    break
            # Bulamazsa direkt ilk ek dosyanın URL'sini al
            if not self.pdf_link:
                self.pdf_link = self.attachment_urls[0].get("url", "")


class DisclosureClassified(DisclosureRaw):
    """
    Sınıflandırılmış bildirim verisi.

    DisclosureRaw'ı miras alır; ek olarak sınıflandırıcı katmanının
    ürettiği companySlug ve newsCategory alanlarını içerir.
    """

    company_slug: str = Field(
        default="",
        alias="companySlug",
        description=(
            "Şirket adından türetilmiş URL-dostu slug "
            "(örn: 'turk-hava-yollari')"
        ),
    )
    news_category: str = Field(
        default="Diğer",
        alias="newsCategory",
        description=(
            "İnsan okunabilir bildirim kategorisi "
            "(örn: 'Finansal Raporlar', 'Temettü Açıklamaları')"
        ),
    )
    classified_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Sınıflandırmanın gerçekleştirildiği UTC zaman damgası",
    )
    sentiment: str | None = Field(
        default=None,
        description="LLM tarafından belirlenen duygu (Olumlu, Olumsuz, Nötr)",
    )
    sentiment_reason: str | None = Field(
        default=None,
        description="LLM'in duygu analizi için kısa açıklaması",
    )
    price_at_news: float | None = Field(
        default=None,
        description="Haber anındaki hisse fiyatı",
    )
    price_5m: float | None = Field(
        default=None,
        description="Haberden 5 dakika sonraki hisse fiyatı",
    )
    price_1h: float | None = Field(
        default=None,
        description="Haberden 1 saat sonraki hisse fiyatı",
    )
    price_1d: float | None = Field(
        default=None,
        description="Haberden 1 gün sonraki hisse fiyatı",
    )
    price_1w: float | None = Field(
        default=None,
        description="Haberden 1 hafta sonraki hisse fiyatı",
    )

    @model_validator(mode="after")
    def auto_fill_slug(self) -> "DisclosureClassified":
        """company_slug boşsa company_name veya title'dan otomatik türetir."""
        if not self.company_slug:
            source = self.company_name or self.title
            if source:
                self.company_slug = slugify(source)
        return self

    @classmethod
    def from_raw(
        cls,
        raw: DisclosureRaw,
        news_category: str = "Diğer",
        company_slug: str = "",
    ) -> "DisclosureClassified":
        """Ham bildirimden sınıflandırılmış nesne oluşturur."""
        data = raw.model_dump(by_alias=True)
        data["newsCategory"] = news_category
        data["companySlug"] = company_slug
        return cls(**data)


class ClassificationResult(BaseModel):
    """
    Şirket ve tür bazında gruplandırılmış sınıflandırma sonucu.
    """

    total: int = Field(..., description="İşlenen toplam bildirim sayısı")
    by_company: dict[str, list[DisclosureClassified]] = Field(
        default_factory=dict,
        description="Hisse senedi koduna göre gruplandırılmış bildirimler",
    )
    by_category: dict[str, list[DisclosureClassified]] = Field(
        default_factory=dict,
        description="Haber kategorisine göre gruplandırılmış bildirimler",
    )
    fetched_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Verilerin KAP'tan çekildiği UTC zaman damgası",
    )

    @property
    def company_count(self) -> int:
        return len(self.by_company)

    @property
    def category_count(self) -> int:
        return len(self.by_category)
