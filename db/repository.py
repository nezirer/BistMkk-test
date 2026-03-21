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
                fund_id, fund_code, sub_report_ids, accepted_file_types,
                sentiment, sentiment_reason, price_at_news, price_5m, price_1h, price_1d, price_1w,
                full_text
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s::jsonb,
                %s, %s, %s, %s, %s, %s, %s,
                %s
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
                classified_at        = EXCLUDED.classified_at,
                full_text            = COALESCE(EXCLUDED.full_text, kap_disclosures.full_text),
                sentiment            = COALESCE(EXCLUDED.sentiment, kap_disclosures.sentiment),
                sentiment_reason     = COALESCE(EXCLUDED.sentiment_reason, kap_disclosures.sentiment_reason),
                price_at_news        = COALESCE(EXCLUDED.price_at_news, kap_disclosures.price_at_news),
                price_5m             = COALESCE(EXCLUDED.price_5m, kap_disclosures.price_5m),
                price_1h             = COALESCE(EXCLUDED.price_1h, kap_disclosures.price_1h),
                price_1d             = COALESCE(EXCLUDED.price_1d, kap_disclosures.price_1d),
                price_1w             = COALESCE(EXCLUDED.price_1w, kap_disclosures.price_1w)
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
                getattr(d, "sentiment", None),
                getattr(d, "sentiment_reason", None),
                getattr(d, "price_at_news", None),
                getattr(d, "price_5m", None),
                getattr(d, "price_1h", None),
                getattr(d, "price_1d", None),
                getattr(d, "price_1w", None),
                (d.full_text or "") or None,
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
                fund_id, fund_code, sub_report_ids, accepted_file_types,
                sentiment, sentiment_reason, price_at_news, price_5m, price_1h, price_1d, price_1w,
                full_text
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
                sentiment=row[18],
                sentiment_reason=row[19],
                price_at_news=float(row[20]) if row[20] is not None else None,
                price_5m=float(row[21]) if row[21] is not None else None,
                price_1h=float(row[22]) if row[22] is not None else None,
                price_1d=float(row[23]) if row[23] is not None else None,
                price_1w=float(row[24]) if row[24] is not None else None,
                fullText=row[25] or "",
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


async def get_disclosures_missing_sentiment(limit: int = 50) -> list[DisclosureClassified]:
    """
    DB'de sentiment analizi yapılmamış (sentiment IS NULL) ve daha önce
    başarısız olmamış (sentiment_failed_at IS NULL) bildirimleri döndürür.
    Bu sayede OpenAI API hatası alan kayıtlar sonsuz döngüye girmez.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_disclosures_missing_sentiment_sync, conn, limit
        )


def _get_disclosures_missing_sentiment_sync(
    conn: psycopg2.extensions.connection, limit: int
) -> list[DisclosureClassified]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                disclosure_index, disclosure_type, disclosure_class, title,
                company_id, company_name, stock_codes, publish_date, subject,
                year_info, kap_link, news_category, company_slug, classified_at,
                fund_id, fund_code, sub_report_ids, accepted_file_types,
                sentiment, sentiment_reason, price_at_news, price_5m, price_1h, price_1d, price_1w,
                full_text
            FROM kap_disclosures
            WHERE sentiment IS NULL
              AND sentiment_failed_at IS NULL
            ORDER BY disclosure_index DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    results: list[DisclosureClassified] = []
    for row in rows:
        try:
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
                sentiment=row[18],
                sentiment_reason=row[19],
                price_at_news=float(row[20]) if row[20] is not None else None,
                price_5m=float(row[21]) if row[21] is not None else None,
                price_1h=float(row[22]) if row[22] is not None else None,
                price_1d=float(row[23]) if row[23] is not None else None,
                price_1w=float(row[24]) if row[24] is not None else None,
                fullText=row[25] or "",
            )
            results.append(disc)
        except Exception as exc:
            log.warning("DB satırı dönüştürülemedi (index={}): {}", row[0], exc)

    return results


async def update_sentiment(
    disclosure_index: int, sentiment: str, reason: str | None
) -> None:
    """Sadece sentiment ve sentiment_reason sütunlarını günceller."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _update_sentiment_sync, conn, disclosure_index, sentiment, reason
        )


def _update_sentiment_sync(
    conn: psycopg2.extensions.connection,
    disclosure_index: int,
    sentiment: str,
    reason: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET sentiment        = %s,
                   sentiment_reason = %s
             WHERE disclosure_index = %s
            """,
            (sentiment, reason, disclosure_index),
        )


async def mark_sentiment_failed(disclosure_index: int) -> None:
    """
    Sentiment analizi başarısız olan bildirimi işaretler.
    Bir sonraki backfill çevriminde bu kayıt tekrar işlenmez.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _mark_sentiment_failed_sync, conn, disclosure_index
        )


def _mark_sentiment_failed_sync(
    conn: psycopg2.extensions.connection, disclosure_index: int
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET sentiment_failed_at = NOW()
             WHERE disclosure_index = %s
            """,
            (disclosure_index,),
        )


async def update_prices(
    disclosure_index: int,
    price_5m: float | None,
    price_1h: float | None,
    price_1d: float | None,
    price_1w: float | None,
) -> None:
    """Sadece fiyat sütunlarını günceller (NULL olan alanları korur)."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _update_prices_sync, conn, disclosure_index,
            price_5m, price_1h, price_1d, price_1w
        )


def _update_prices_sync(
    conn: psycopg2.extensions.connection,
    disclosure_index: int,
    price_5m: float | None,
    price_1h: float | None,
    price_1d: float | None,
    price_1w: float | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET price_5m = COALESCE(%s, price_5m),
                   price_1h = COALESCE(%s, price_1h),
                   price_1d = COALESCE(%s, price_1d),
                   price_1w = COALESCE(%s, price_1w)
             WHERE disclosure_index = %s
            """,
            (price_5m, price_1h, price_1d, price_1w, disclosure_index),
        )


async def get_disclosures_needing_price_update() -> list[DisclosureClassified]:
    """
    Fiyat güncellemesi gereken bildirimleri getirir.
    (price_1w'si null olan ve publish_date'i parse edilebilenler)
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_disclosures_needing_price_update_sync, conn)

def _get_disclosures_needing_price_update_sync(
    conn: psycopg2.extensions.connection
) -> list[DisclosureClassified]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                disclosure_index, disclosure_type, disclosure_class, title,
                company_id, company_name, stock_codes, publish_date, subject,
                year_info, kap_link, news_category, company_slug, classified_at,
                fund_id, fund_code, sub_report_ids, accepted_file_types,
                sentiment, sentiment_reason, price_at_news, price_5m, price_1h, price_1d, price_1w,
                full_text
            FROM kap_disclosures
            WHERE (price_5m IS NULL OR price_1h IS NULL OR price_1d IS NULL OR price_1w IS NULL)
              AND stock_codes IS NOT NULL
              AND stock_codes != ''
              AND classified_at >= NOW() - INTERVAL '8 days'
            ORDER BY disclosure_index DESC
            LIMIT 100
            """
        )
        rows = cur.fetchall()

    results: list[DisclosureClassified] = []
    for row in rows:
        try:
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
                sentiment=row[18],
                sentiment_reason=row[19],
                price_at_news=float(row[20]) if row[20] is not None else None,
                price_5m=float(row[21]) if row[21] is not None else None,
                price_1h=float(row[22]) if row[22] is not None else None,
                price_1d=float(row[23]) if row[23] is not None else None,
                price_1w=float(row[24]) if row[24] is not None else None,
                fullText=row[25] or "",
            )
            results.append(disc)
        except Exception as exc:
            log.warning("DB satırı dönüştürülemedi (index={}): {}", row[0], exc)

    return results

async def get_disclosures_missing_full_text(limit: int = 50) -> list[DisclosureClassified]:
    """
    DB'de full_text alanı boş olan bildirimleri döndürür.
    Bu kayıtlar MKK API'den htmlMessages yeniden çekilerek zenginleştirilecek.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_disclosures_missing_full_text_sync, conn, limit
        )


def _get_disclosures_missing_full_text_sync(
    conn: psycopg2.extensions.connection, limit: int
) -> list[DisclosureClassified]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                disclosure_index, disclosure_type, disclosure_class, title,
                company_id, company_name, stock_codes, publish_date, subject,
                year_info, kap_link, news_category, company_slug, classified_at,
                fund_id, fund_code, sub_report_ids, accepted_file_types,
                sentiment, sentiment_reason, price_at_news, price_5m, price_1h, price_1d, price_1w,
                full_text
            FROM kap_disclosures
            WHERE (full_text IS NULL OR full_text = '')
            ORDER BY disclosure_index DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    results: list[DisclosureClassified] = []
    for row in rows:
        try:
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
                sentiment=row[18],
                sentiment_reason=row[19],
                price_at_news=float(row[20]) if row[20] is not None else None,
                price_5m=float(row[21]) if row[21] is not None else None,
                price_1h=float(row[22]) if row[22] is not None else None,
                price_1d=float(row[23]) if row[23] is not None else None,
                price_1w=float(row[24]) if row[24] is not None else None,
                fullText=row[25] or "",
            )
            results.append(disc)
        except Exception as exc:
            log.warning("DB satırı dönüştürülemedi (index={}): {}", row[0], exc)

    return results


async def update_full_text_and_reset_sentiment(
    disclosure_index: int, full_text: str
) -> None:
    """
    full_text sütununu günceller; mevcut sentiment'i sıfırlar (yeniden analiz edilsin diye).
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _update_full_text_and_reset_sentiment_sync, conn, disclosure_index, full_text
        )


def _update_full_text_and_reset_sentiment_sync(
    conn: psycopg2.extensions.connection, disclosure_index: int, full_text: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET full_text            = %s,
                   sentiment            = NULL,
                   sentiment_reason     = NULL,
                   sentiment_failed_at  = NULL
             WHERE disclosure_index = %s
            """,
            (full_text or None, disclosure_index),
        )



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
