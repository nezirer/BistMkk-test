"""
Pydantic v2 veri modelleri — schema-first tasarım.

Gelecekteki DB migration'ını kolaylaştırmak amacıyla tüm alanlar
açıklayıcı Field(description=...) ile belgelenmiştir.

Modeller:
    DisclosureRaw         — KAP API'den gelen ham bildirim verisi
    DisclosureClassified  — Sınıflandırılmış bildirim (ek alanlar dahil)
    ClassificationResult  — Şirket ve tür bazında gruplandırılmış sonuç yapısı
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _slugify(text: str) -> str:
    """Türkçe karakterler dahil metni URL-dostu slug'a dönüştürür."""
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
    text = text.translate(tr_map).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


class DisclosureRaw(BaseModel):
    """
    KAP API'den gelen ham bildirim verisi.

    https://www.kap.org.tr/tr/api/disclosures endpoint'inden dönen
    JSON objesinin doğrudan temsilidir.

    Kullanım:
        >>> raw = DisclosureRaw(**api_response_item)
        >>> print(raw.stock_codes, raw.publish_date)
    """

    disclosure_index: int = Field(
        ...,
        alias="disclosureIndex",
        description="KAP sistemindeki tekil bildirim sırası / kimliği",
    )
    info_type_desc: str = Field(
        ...,
        alias="infoTypeDesc",
        description="Bildirim türünün açıklaması (örn: 'Finansal Rapor')",
    )
    stock_codes: str = Field(
        ...,
        alias="stockCodes",
        description="İlgili hisse senedi kodu (örn: 'THYAO')",
    )
    company_name: str = Field(
        ...,
        alias="companyName",
        description="Şirketin tam ticari unvanı",
    )
    title: str = Field(
        ...,
        alias="title",
        description="Bildirimin başlığı",
    )
    publish_date: str = Field(
        ...,
        alias="publishDate",
        description="Yayınlanma tarihi ve saati (format: DD.MM.YYYY HH:MM)",
    )
    is_old_kap: bool = Field(
        ...,
        alias="isOldKap",
        description="Bildirimin eski KAP sisteminden gelip gelmediği",
    )
    subject: str = Field(
        default="",
        alias="subject",
        description="Bildirimin konusu / özeti",
    )
    year: int | None = Field(
        default=None,
        alias="year",
        description="Bildirimin ait olduğu mali yıl",
    )
    period: str | None = Field(
        default=None,
        alias="period",
        description="Bildirimin ait olduğu dönem (örn: '3', '6', '9', '12')",
    )
    basic_type: str = Field(
        ...,
        alias="basicType",
        description="Bildirimin ana kategorisi (örn: 'FR', 'ODA', 'GK')",
    )
    disclosure_class: str = Field(
        default="",
        alias="disclosureClass",
        description="Bildirimin KAP sınıfı",
    )

    model_config = {
        "populate_by_name": True,
        "str_strip_whitespace": True,
    }

    @field_validator("stock_codes", mode="before")
    @classmethod
    def normalize_stock_codes(cls, v: Any) -> str:
        """Hisse kodunu büyük harfe ve boşluksuz formata getirir."""
        return str(v).strip().upper()

    @property
    def publish_datetime(self) -> datetime | None:
        """
        publish_date alanını datetime nesnesine dönüştürür.

        Kullanım:
            >>> raw.publish_datetime
            datetime(2024, 3, 15, 14, 30)
        """
        try:
            return datetime.strptime(self.publish_date, "%d.%m.%Y %H:%M")
        except ValueError:
            return None


class DisclosureClassified(DisclosureRaw):
    """
    Sınıflandırılmış bildirim verisi.

    DisclosureRaw'ı miras alır; ek olarak sınıflandırıcı katmanının
    ürettiği companySlug ve newsCategory alanlarını içerir.

    Kullanım:
        >>> classified = DisclosureClassified(
        ...     **raw.model_dump(by_alias=True),
        ...     companySlug="turk-hava-yollari",
        ...     newsCategory="Finansal Raporlar",
        ... )
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

    @model_validator(mode="after")
    def auto_fill_slug(self) -> "DisclosureClassified":
        """company_slug boşsa company_name'den otomatik türetir."""
        if not self.company_slug and self.company_name:
            self.company_slug = _slugify(self.company_name)
        return self

    @classmethod
    def from_raw(
        cls,
        raw: DisclosureRaw,
        news_category: str = "Diğer",
        company_slug: str = "",
    ) -> "DisclosureClassified":
        """
        Ham bildirimden sınıflandırılmış nesne oluşturur.

        Args:
            raw: Ham bildirim nesnesi.
            news_category: Atanacak haber kategorisi.
            company_slug: Atanacak şirket slug'ı (boş bırakılırsa otomatik üretilir).

        Kullanım:
            >>> classified = DisclosureClassified.from_raw(
            ...     raw, news_category="Temettü Açıklamaları"
            ... )
        """
        data = raw.model_dump(by_alias=True)
        data["newsCategory"] = news_category
        data["companySlug"] = company_slug
        return cls(**data)


class ClassificationResult(BaseModel):
    """
    Şirket ve tür bazında gruplandırılmış sınıflandırma sonucu.

    Scheduler döngüsü sonunda üretilen ve web katmanına iletilen
    nihai veri yapısıdır.

    Kullanım:
        >>> result = ClassificationResult(
        ...     total=120,
        ...     by_company={"THYAO": [...]},
        ...     by_category={"Finansal Raporlar": [...]},
        ...     fetched_at=datetime.utcnow(),
        ... )
        >>> print(result.total)
        120
    """

    total: int = Field(
        ...,
        description="İşlenen toplam bildirim sayısı",
    )
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
        """Kaç farklı şirkete ait bildirim bulunduğunu döndürür."""
        return len(self.by_company)

    @property
    def category_count(self) -> int:
        """Kaç farklı kategoride bildirim bulunduğunu döndürür."""
        return len(self.by_category)
