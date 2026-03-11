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
        accepted_file_types JSONB           DEFAULT '[]'
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
]

_INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_disc_stock    ON kap_disclosures (stock_codes)",
    "CREATE INDEX IF NOT EXISTS idx_disc_category ON kap_disclosures (news_category)",
    "CREATE INDEX IF NOT EXISTS idx_disc_company  ON kap_disclosures (company_id)",
    "CREATE INDEX IF NOT EXISTS idx_comp_stock    ON kap_companies   (stock_code)",
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

        for ddl in _SEED_STATEMENTS:
            cur.execute(ddl.strip())

    conn.commit()
    log.info("PostgreSQL şema doğrulaması tamamlandı.")
