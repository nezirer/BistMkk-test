"""
PostgreSQL DDL yönetimi — tabloları uygulama başlangıcında oluşturur.

Kullanım (lifespan içinden):
    from db.models import create_tables
    create_tables(conn)
"""
from __future__ import annotations

import psycopg2.extensions

from utils.logger import get_logger

log = get_logger(__name__)

_DDL_STATEMENTS: list[str] = [
    # kap_disclosures
    """
    CREATE TABLE IF NOT EXISTS kap_disclosures (
        disclosure_index    BIGINT          PRIMARY KEY,
        disclosure_type     VARCHAR(10),
        disclosure_class    VARCHAR(10),
        title               VARCHAR(500),
        company_id          VARCHAR(50),
        company_name        VARCHAR(500),
        stock_codes         VARCHAR(100),
        publish_date        VARCHAR(50),
        subject             VARCHAR(2000),
        year_info           VARCHAR(10),
        kap_link            VARCHAR(1000),
        news_category       VARCHAR(100),
        company_slug        VARCHAR(500),
        classified_at       TIMESTAMPTZ     DEFAULT NOW(),
        fund_id             VARCHAR(50),
        fund_code           VARCHAR(50),
        sub_report_ids      JSONB           DEFAULT '[]',
        accepted_file_types JSONB           DEFAULT '[]',
        full_text           TEXT,
        sentiment              VARCHAR(20),
        sentiment_reason       VARCHAR(1000),
        sentiment_failed_at    TIMESTAMPTZ,
        price_at_news          NUMERIC(10, 4),
        price_5m               NUMERIC(10, 4),
        price_1h               NUMERIC(10, 4),
        price_1d               NUMERIC(10, 4),
        price_1w               NUMERIC(10, 4),
        attachment_urls         JSONB           DEFAULT '[]',
        related_disclosure_index VARCHAR(50),
        period                 VARCHAR(200),
        related_stocks         JSONB           DEFAULT '[]',
        publish_datetime_utc   TIMESTAMPTZ,
        llm_summary            TEXT,
        llm_summary_at         TIMESTAMPTZ,
        llm_summary_source     VARCHAR(20),
        pdf_link               TEXT
    )
    """,
    # kap_companies
    """
    CREATE TABLE IF NOT EXISTS kap_companies (
        member_id    VARCHAR(50)  PRIMARY KEY,
        title        VARCHAR(500),
        stock_code   VARCHAR(20),
        member_type  VARCHAR(50),
        kfif_url     VARCHAR(1000),
        company_slug VARCHAR(500),
        fetched_at   TIMESTAMPTZ  DEFAULT NOW()
    )
    """,
    # kap_company_details
    """
    CREATE TABLE IF NOT EXISTS kap_company_details (
        member_id    VARCHAR(50)  PRIMARY KEY,
        name_tr      VARCHAR(500),
        name_en      VARCHAR(500),
        detail_json  JSONB,
        updated_at   TIMESTAMPTZ  DEFAULT NOW()
    )
    """,
    # kap_sync_state
    """
    CREATE TABLE IF NOT EXISTS kap_sync_state (
        state_key    VARCHAR(50)   PRIMARY KEY,
        state_value  VARCHAR(500)  NOT NULL,
        updated_at   TIMESTAMPTZ   DEFAULT NOW()
    )
    """,
    # kap_pdf_texts
    """
    CREATE TABLE IF NOT EXISTS kap_pdf_texts (
        disclosure_index BIGINT PRIMARY KEY,
        extracted_text   TEXT,
        parsed_at        TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    # kap_pdf_parsed_data
    """
    CREATE TABLE IF NOT EXISTS kap_pdf_parsed_data (
        disclosure_index BIGINT PRIMARY KEY,
        category_type    VARCHAR(100),
        parsed_json      JSONB,
        summary          TEXT,
        summarized_at    TIMESTAMPTZ DEFAULT NOW(),
        extracted_at     TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    # kap_disclosure_analiz
    """
    CREATE TABLE IF NOT EXISTS kap_disclosure_analiz (
        disclosure_index BIGINT PRIMARY KEY,
        analyzed_text    TEXT,
        sentiment_label  VARCHAR(20),
        confidence_score NUMERIC(6, 4),
        analyzed_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """,
]

_INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_disc_stock    ON kap_disclosures (stock_codes)",
    "CREATE INDEX IF NOT EXISTS idx_disc_category ON kap_disclosures (news_category)",
    "CREATE INDEX IF NOT EXISTS idx_disc_company  ON kap_disclosures (company_id)",
    "CREATE INDEX IF NOT EXISTS idx_comp_stock    ON kap_companies   (stock_code)",
]

_MIGRATION_STATEMENTS: list[str] = [
    # v3.1 — sentiment + fiyat sütunları: mevcut DB'lerde eksikse ekle
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS sentiment_reason VARCHAR(1000)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS sentiment_failed_at TIMESTAMPTZ",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS price_at_news NUMERIC(10,4)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS price_5m NUMERIC(10,4)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS price_1h NUMERIC(10,4)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS price_1d NUMERIC(10,4)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS price_1w NUMERIC(10,4)",
    # v3.2 — tam bildirim metni (Base64 decode edilmiş htmlMessages)
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS full_text TEXT",
    # v3.3 — API'den gelen ek bilgi alanları
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS attachment_urls JSONB DEFAULT '[]'",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS related_disclosure_index VARCHAR(50)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS period VARCHAR(200)",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS related_stocks JSONB DEFAULT '[]'",
    # v3.4 — publish_datetime_utc: yayınlanma tarihini TIMESTAMPTZ olarak tutma
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS publish_datetime_utc TIMESTAMPTZ",
    # v3.5 — pdf_link: İlk ek dosyanın (tercihen PDF) doğrudan bağlantısı
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS pdf_link TEXT",
    # v4.2 — lokal Gemma özet alanları
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS llm_summary TEXT",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS llm_summary_at TIMESTAMPTZ",
    "ALTER TABLE kap_disclosures ADD COLUMN IF NOT EXISTS llm_summary_source VARCHAR(20)",
    "ALTER TABLE kap_pdf_parsed_data ADD COLUMN IF NOT EXISTS summary TEXT",
    "ALTER TABLE kap_pdf_parsed_data ADD COLUMN IF NOT EXISTS summarized_at TIMESTAMPTZ DEFAULT NOW()",
]

_SEED_STATEMENTS: list[str] = [
    """
    INSERT INTO kap_sync_state (state_key, state_value)
    VALUES ('last_disclosure_index', '0')
    ON CONFLICT (state_key) DO NOTHING
    """,
]


def create_tables(conn: psycopg2.extensions.connection) -> None:
    """
    Eksik tabloları ve indeksleri oluşturur (idempotent — IF NOT EXISTS).
    """
    with conn.cursor() as cur:
        for ddl in _DDL_STATEMENTS:
            cur.execute(ddl.strip())

        for ddl in _INDEX_STATEMENTS:
            cur.execute(ddl.strip())

        for ddl in _MIGRATION_STATEMENTS:
            cur.execute(ddl.strip())

        for ddl in _SEED_STATEMENTS:
            cur.execute(ddl.strip())

    conn.commit()
    log.info("PostgreSQL şema doğrulaması tamamlandı.")
