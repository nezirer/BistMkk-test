-- =============================================================================
-- KAP Classifier — PostgreSQL DDL
-- Versiyon: 2.0 (PostgreSQL, ARM64 uyumlu)
-- Açıklama : Bu dosyayı psql ile el ile de çalıştırabilirsiniz.
--             Python uygulama başlangıcında db/models.py üzerinden otomatik
--             olarak da çalıştırılır (CREATE TABLE IF NOT EXISTS — idempotent).
--
-- Kullanım:
--   psql -U kap_user -d kap_db -f schema.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- kap_disclosures
-- MKK VYK API /disclosures + /disclosureDetail birleşiminden gelen bildirimler
-- ---------------------------------------------------------------------------
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
    sentiment              VARCHAR(20),
    sentiment_reason       VARCHAR(1000),
    sentiment_failed_at    TIMESTAMPTZ,
    price_at_news          NUMERIC(10, 4),
    price_5m            NUMERIC(10, 4),
    price_1h            NUMERIC(10, 4),
    price_1d            NUMERIC(10, 4),
    price_1w            NUMERIC(10, 4)
);

CREATE INDEX IF NOT EXISTS idx_disc_stock    ON kap_disclosures (stock_codes);
CREATE INDEX IF NOT EXISTS idx_disc_category ON kap_disclosures (news_category);
CREATE INDEX IF NOT EXISTS idx_disc_company  ON kap_disclosures (company_id);

-- ---------------------------------------------------------------------------
-- kap_companies
-- MKK VYK API /members endpoint'inden gelen şirket listesi
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kap_companies (
    member_id    VARCHAR(50)  PRIMARY KEY,
    title        VARCHAR(500),
    stock_code   VARCHAR(20),
    member_type  VARCHAR(50),
    kfif_url     VARCHAR(1000),
    company_slug VARCHAR(500),
    fetched_at   TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comp_stock ON kap_companies (stock_code);

-- ---------------------------------------------------------------------------
-- kap_company_details
-- MKK VYK API /memberDetail/{id} endpoint'inden gelen şirket detayları
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kap_company_details (
    member_id    VARCHAR(50)  PRIMARY KEY,
    name_tr      VARCHAR(500),
    name_en      VARCHAR(500),
    detail_json  JSONB,
    updated_at   TIMESTAMPTZ  DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- kap_sync_state
-- Polling durumunu takip eder: son görülen disclosure_index
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kap_sync_state (
    state_key    VARCHAR(50)   PRIMARY KEY,
    state_value  VARCHAR(500)  NOT NULL,
    updated_at   TIMESTAMPTZ   DEFAULT NOW()
);

INSERT INTO kap_sync_state (state_key, state_value)
VALUES ('last_disclosure_index', '0')
ON CONFLICT (state_key) DO NOTHING;

-- Migration: mevcut DB'lerde sentiment_failed_at sütunu yoksa ekle
ALTER TABLE kap_disclosures
    ADD COLUMN IF NOT EXISTS sentiment_failed_at TIMESTAMPTZ;
