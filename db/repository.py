"""
KAP Classifier — PostgreSQL CRUD operasyonları.

Tüm metodlar async'tir; DB işlemleri asyncio thread pool üzerinden
çalıştırılır (psycopg2 sync API'sini sarmalar).
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any

import psycopg2.extensions

from db.connection import get_connection
from models.disclosure import DisclosureClassified
from utils.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
    text = text.translate(tr_map).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


# ---------------------------------------------------------------------------
# Bildirim (Disclosure) işlemleri
# ---------------------------------------------------------------------------

async def upsert_disclosure(disclosure: DisclosureClassified) -> None:
    """
    Bildirimi DB'ye ekler; aynı disclosure_index zaten varsa günceller.
    PostgreSQL: INSERT ... ON CONFLICT DO UPDATE
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _upsert_disclosure_sync, conn, disclosure)


def _upsert_disclosure_sync(
    conn: psycopg2.extensions.connection, d: DisclosureClassified
) -> None:
    classified_at = d.classified_at if isinstance(d.classified_at, datetime) else datetime.utcnow()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kap_disclosures (
                disclosure_index, disclosure_type, disclosure_class, title,
                company_id, company_name, stock_codes, publish_date, subject,
                year_info, kap_link, news_category, company_slug, classified_at,
                fund_id, fund_code, sub_report_ids, accepted_file_types
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s::jsonb
            )
            ON CONFLICT (disclosure_index) DO UPDATE SET
                disclosure_type      = EXCLUDED.disclosure_type,
                disclosure_class     = EXCLUDED.disclosure_class,
                title                = EXCLUDED.title,
                company_name         = EXCLUDED.company_name,
                stock_codes          = EXCLUDED.stock_codes,
                publish_date         = EXCLUDED.publish_date,
                subject              = EXCLUDED.subject,
                year_info            = EXCLUDED.year_info,
                kap_link             = EXCLUDED.kap_link,
                news_category        = EXCLUDED.news_category,
                company_slug         = EXCLUDED.company_slug,
                classified_at        = EXCLUDED.classified_at
            """,
            (
                d.disclosure_index,
                (d.disclosure_type or "")[:10],
                (d.disclosure_class or "")[:10],
                (d.title or "")[:500],
                (d.company_id or "")[:50],
                (d.company_name or "")[:500],
                (d.stock_codes or "")[:100],
                (d.publish_date or "")[:50],
                (d.subject or "")[:2000],
                (d.year or "")[:10],
                (d.kap_link or "")[:1000],
                (d.news_category or "")[:100],
                (d.company_slug or "")[:500],
                classified_at,
                (d.fund_id or "")[:50],
                (d.fund_code or "")[:50],
                json.dumps(d.sub_report_ids or [], ensure_ascii=False),
                json.dumps(d.accepted_data_file_types or [], ensure_ascii=False),
            ),
        )


async def disclosure_exists(index: int) -> bool:
    """Belirtilen disclosure_index veritabanında mevcut mu?"""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _disclosure_exists_sync, conn, index)


def _disclosure_exists_sync(
    conn: psycopg2.extensions.connection, index: int
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM kap_disclosures WHERE disclosure_index = %s LIMIT 1",
            (index,),
        )
        return cur.fetchone() is not None


async def get_disclosures(
    limit: int = 50,
    stock_code: str = "",
    category: str = "",
    offset: int = 0,
) -> list[DisclosureClassified]:
    """
    DB'den sıralı bildirim listesi döndürür.
    - stock_code filtresi: stock_codes ILIKE (kısmi eşleşme, çoklu kodları destekler)
    - category filtresi: news_category exact match
    - Sıralama: disclosure_index DESC (en yeni önce)
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_disclosures_sync, conn, limit, stock_code, category, offset
        )


def _get_disclosures_sync(
    conn: psycopg2.extensions.connection,
    limit: int,
    stock_code: str,
    category: str,
    offset: int,
) -> list[DisclosureClassified]:
    where_clauses: list[str] = []
    params: list[Any] = []

    if stock_code:
        # stock_codes virgülle ayrılmış çoklu kod içerebilir (örn: "THYAO,THYAO2")
        # Exact match yerine ILIKE ile kısmi eşleşme yapılır
        where_clauses.append("stock_codes ILIKE %s")
        params.append(f"%{stock_code.upper()}%")

    if category:
        where_clauses.append("news_category = %s")
        params.append(category)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                disclosure_index, disclosure_type, disclosure_class, title,
                company_id, company_name, stock_codes, publish_date, subject,
                year_info, kap_link, news_category, company_slug, classified_at,
                fund_id, fund_code, sub_report_ids, accepted_file_types
            FROM kap_disclosures
            {where_sql}
            ORDER BY disclosure_index DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()

    results: list[DisclosureClassified] = []
    for row in rows:
        try:
            # sub_report_ids ve accepted_file_types JSONB olarak gelir (zaten list)
            sub_ids = row[16] if isinstance(row[16], list) else []
            acc_types = row[17] if isinstance(row[17], list) else []
            classified_at = row[13] if isinstance(row[13], datetime) else datetime.utcnow()

            disc = DisclosureClassified(
                disclosureIndex=int(row[0]),
                disclosureType=row[1] or "",
                disclosureClass=row[2] or "",
                title=row[3] or "",
                companyId=row[4] or "",
                companyName=row[5] or "",
                stockCodes=row[6] or "",
                publishDate=row[7] or "",
                subject=row[8] or "",
                year=row[9] or "",
                kapLink=row[10] or "",
                newsCategory=row[11] or "",
                companySlug=row[12] or "",
                classified_at=classified_at,
                fundId=row[14] or "",
                fundCode=row[15] or "",
                subReportIds=sub_ids,
                acceptedDataFileTypes=acc_types,
            )
            results.append(disc)
        except Exception as exc:
            log.warning(
                "DB satırı DisclosureClassified'a dönüştürülemedi (index={}): {}",
                row[0], exc,
            )

    return results


async def get_last_seen_index() -> int:
    """
    kap_sync_state tablosundaki son bildirim indeksini döndürür.
    DB'de hiç kayıt yoksa 0 döner.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_last_seen_index_sync, conn)


def _get_last_seen_index_sync(conn: psycopg2.extensions.connection) -> int:
    with conn.cursor() as cur:
        # Sync state tablosunu dene
        cur.execute(
            "SELECT state_value FROM kap_sync_state WHERE state_key = 'last_disclosure_index'"
        )
        row = cur.fetchone()
        if row and row[0]:
            val = int(row[0])
            if val > 0:
                return val

        # Fallback: disclosures tablosundaki max index
        cur.execute("SELECT MAX(disclosure_index) FROM kap_disclosures")
        row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])

    return 0


async def update_last_seen_index(index: int) -> None:
    """kap_sync_state tablosunu son görülen indeksle günceller."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _update_last_seen_index_sync, conn, index)


def _update_last_seen_index_sync(
    conn: psycopg2.extensions.connection, index: int
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kap_sync_state (state_key, state_value, updated_at)
            VALUES ('last_disclosure_index', %s, NOW())
            ON CONFLICT (state_key) DO UPDATE
                SET state_value = EXCLUDED.state_value,
                    updated_at  = NOW()
            """,
            (str(index),),
        )


# ---------------------------------------------------------------------------
# Şirket (Company) işlemleri
# ---------------------------------------------------------------------------

async def upsert_company(member: dict) -> None:
    """
    /members endpoint'inden gelen şirket kaydını DB'ye ekler/günceller.
    member dict beklenen alanlar: id, title, stockCode, memberType, kfifUrl
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _upsert_company_sync, conn, member)


def _upsert_company_sync(
    conn: psycopg2.extensions.connection, member: dict
) -> None:
    member_id = str(member.get("id", "")).strip()
    if not member_id:
        return

    title = str(member.get("title", "") or "")
    stock_code = str(member.get("stockCode", "") or "")
    member_type = str(member.get("memberType", "") or "")
    kfif_url = str(member.get("kfifUrl", "") or "")
    slug = _slugify(title) if title else ""

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kap_companies (member_id, title, stock_code, member_type, kfif_url, company_slug)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (member_id) DO UPDATE SET
                title        = EXCLUDED.title,
                stock_code   = EXCLUDED.stock_code,
                member_type  = EXCLUDED.member_type,
                kfif_url     = EXCLUDED.kfif_url,
                company_slug = EXCLUDED.company_slug,
                fetched_at   = NOW()
            """,
            (
                member_id[:50],
                title[:500],
                stock_code[:20],
                member_type[:50],
                kfif_url[:1000],
                slug[:500],
            ),
        )


async def upsert_company_detail(member_id: str, detail: dict) -> None:
    """
    /memberDetail/{id} yanıtını DB'ye kaydeder.
    Tüm detay JSONB sütununa yazılır.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _upsert_company_detail_sync, conn, member_id, detail)


def _upsert_company_detail_sync(
    conn: psycopg2.extensions.connection, member_id: str, detail: dict
) -> None:
    name_tr = str(detail.get("nameTr", "") or "")
    name_en = str(detail.get("nameEn", "") or "")
    detail_json = json.dumps(detail, ensure_ascii=False)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kap_company_details (member_id, name_tr, name_en, detail_json)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (member_id) DO UPDATE SET
                name_tr     = EXCLUDED.name_tr,
                name_en     = EXCLUDED.name_en,
                detail_json = EXCLUDED.detail_json,
                updated_at  = NOW()
            """,
            (
                member_id[:50],
                name_tr[:500],
                name_en[:500],
                detail_json,
            ),
        )


async def get_companies(stock_code: str = "") -> list[dict]:
    """
    kap_companies tablosundan şirketleri döndürür.
    stock_code verilirse exact match filtresi uygulanır.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_companies_sync, conn, stock_code)


def _get_companies_sync(
    conn: psycopg2.extensions.connection, stock_code: str
) -> list[dict]:
    with conn.cursor() as cur:
        if stock_code:
            cur.execute(
                """
                SELECT member_id, title, stock_code, member_type, kfif_url, company_slug, fetched_at
                FROM kap_companies WHERE stock_code = %s
                """,
                (stock_code.upper(),),
            )
        else:
            cur.execute(
                """
                SELECT member_id, title, stock_code, member_type, kfif_url, company_slug, fetched_at
                FROM kap_companies ORDER BY title
                """
            )
        rows = cur.fetchall()

    return [
        {
            "member_id": row[0],
            "title": row[1] or "",
            "stock_code": row[2] or "",
            "member_type": row[3] or "",
            "kfif_url": row[4] or "",
            "company_slug": row[5] or "",
            "fetched_at": row[6].isoformat() if row[6] else "",
        }
        for row in rows
    ]


async def companies_stale(ttl_hours: int = 24) -> bool:
    """
    kap_companies tablosunun son güncelleme zamanına göre yenilenip
    yenilenmeyeceğine karar verir.
    Tabloda hiç kayıt yoksa veya TTL dolmuşsa True döner.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _companies_stale_sync, conn, ttl_hours)


def _companies_stale_sync(
    conn: psycopg2.extensions.connection, ttl_hours: int
) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM kap_companies")
        row = cur.fetchone()
        count = row[0] if row else 0

        if count == 0:
            return True

        cur.execute("SELECT MAX(fetched_at) FROM kap_companies")
        row = cur.fetchone()

    if not row or not row[0]:
        return True

    last_fetch: datetime = row[0].replace(tzinfo=None) if row[0].tzinfo else row[0]
    age_hours = (datetime.utcnow() - last_fetch).total_seconds() / 3600
    return age_hours >= ttl_hours
