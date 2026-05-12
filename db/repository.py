"""
KAP Classifier — PostgreSQL CRUD operasyonları.

Tüm metodlar async'tir; DB işlemleri asyncio thread pool üzerinden
çalıştırılır (psycopg2 sync API'sini sarmalar).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import psycopg2.extensions
import psycopg2.extras

from db.connection import get_connection
from models.disclosure import DisclosureClassified
from utils.logger import get_logger
from utils.text import slugify

log = get_logger(__name__)


_DISCLOSURE_COLUMNS = """
    disclosure_index, disclosure_type, disclosure_class, title,
    company_id, company_name, stock_codes, publish_date, subject,
    year_info, kap_link, news_category, company_slug, classified_at,
    fund_id, fund_code, sub_report_ids, accepted_file_types,
    sentiment, sentiment_reason, price_at_news, price_5m, price_1h, price_1d, price_1w,
    full_text,
    attachment_urls, related_disclosure_index, period, related_stocks,
    publish_datetime_utc, pdf_link
"""


def _row_to_disclosure(row: tuple) -> DisclosureClassified:
    sub_ids = row[16] if isinstance(row[16], list) else []
    acc_types = row[17] if isinstance(row[17], list) else []
    classified_at = row[13] if isinstance(row[13], datetime) else datetime.utcnow()
    att_urls = row[26] if isinstance(row[26], list) else []
    rel_stocks = row[29] if isinstance(row[29], list) else []

    return DisclosureClassified(
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
        attachmentUrls=att_urls,
        relatedDisclosureIndex=row[27] or "",
        period=row[28] or "",
        relatedStocks=rel_stocks,
        publishDatetimeUtc=row[30] if len(row) > 30 else None,
        pdfLink=(row[31] or "") if len(row) > 31 else "",
    )


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
                full_text,
                attachment_urls, related_disclosure_index, period, related_stocks,
                publish_datetime_utc, pdf_link
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, %s::jsonb,
                %s, %s, %s, %s, %s, %s, %s,
                %s,
                %s::jsonb, %s, %s, %s::jsonb,
                %s, %s
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
                price_1w             = COALESCE(EXCLUDED.price_1w, kap_disclosures.price_1w),
                attachment_urls      = COALESCE(EXCLUDED.attachment_urls, kap_disclosures.attachment_urls),
                related_disclosure_index = COALESCE(EXCLUDED.related_disclosure_index, kap_disclosures.related_disclosure_index),
                period               = COALESCE(EXCLUDED.period, kap_disclosures.period),
                related_stocks       = COALESCE(EXCLUDED.related_stocks, kap_disclosures.related_stocks),
                publish_datetime_utc = COALESCE(EXCLUDED.publish_datetime_utc, kap_disclosures.publish_datetime_utc),
                pdf_link             = COALESCE(EXCLUDED.pdf_link, kap_disclosures.pdf_link)
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
                json.dumps(d.attachment_urls or [], ensure_ascii=False),
                (d.related_disclosure_index or "")[:50] or None,
                (d.period or "")[:200] or None,
                json.dumps(d.related_stocks or [], ensure_ascii=False),
                getattr(d, "publish_datetime_utc", None),
                (d.pdf_link or "")[:2000] or None,
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
    search_query: str = "",
) -> list[DisclosureClassified]:
    """
    DB'den sıralı bildirim listesi döndürür.
    - stock_code filtresi: stock_codes ILIKE (kısmi eşleşme, çoklu kodları destekler)
    - category filtresi: news_category exact match
    - search_query filtresi: title veya subject ILIKE
    - Sıralama: disclosure_index DESC (en yeni önce)
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_disclosures_sync, conn, limit, stock_code, category, offset, search_query
        )


def _get_disclosures_sync(
    conn: psycopg2.extensions.connection,
    limit: int,
    stock_code: str,
    category: str,
    offset: int,
    search_query: str = "",
) -> list[DisclosureClassified]:
    where_clauses: list[str] = []
    params: list[Any] = []

    if stock_code:
        where_clauses.append("stock_codes ILIKE %s")
        params.append(f"%{stock_code.upper()}%")

    if category:
        where_clauses.append("news_category = %s")
        params.append(category)

    if search_query:
        where_clauses.append("(title ILIKE %s OR subject ILIKE %s OR stock_codes ILIKE %s)")
        q = f"%{search_query}%"
        params.extend([q, q, q.upper()])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_DISCLOSURE_COLUMNS}
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
            results.append(_row_to_disclosure(row))
        except Exception as exc:
            log.warning(
                "DB satırı DisclosureClassified'a dönüştürülemedi (index={}): {}",
                row[0], exc,
            )

    return results


async def count_disclosures(
    stock_code: str = "",
    category: str = "",
    search_query: str = "",
) -> int:
    """Filtreli bildirim sayısını döndürür (sayfalama için)."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _count_disclosures_sync, conn, stock_code, category, search_query
        )


def _count_disclosures_sync(
    conn: psycopg2.extensions.connection,
    stock_code: str,
    category: str,
    search_query: str,
) -> int:
    where_clauses: list[str] = []
    params: list[Any] = []

    if stock_code:
        where_clauses.append("stock_codes ILIKE %s")
        params.append(f"%{stock_code.upper()}%")

    if category:
        where_clauses.append("news_category = %s")
        params.append(category)

    if search_query:
        where_clauses.append("(title ILIKE %s OR subject ILIKE %s OR stock_codes ILIKE %s)")
        q = f"%{search_query}%"
        params.extend([q, q, q.upper()])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM kap_disclosures {where_sql}",
            params,
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


async def get_disclosure_by_index(index: int) -> DisclosureClassified | None:
    """Tekil bildirim kaydını döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_disclosure_by_index_sync, conn, index)


def _get_disclosure_by_index_sync(
    conn: psycopg2.extensions.connection, index: int
) -> DisclosureClassified | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_DISCLOSURE_COLUMNS}
            FROM kap_disclosures
            WHERE disclosure_index = %s
            LIMIT 1
            """,
            (index,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    try:
        return _row_to_disclosure(row)
    except Exception as exc:
        log.warning("DB satırı dönüştürülemedi (index={}): {}", index, exc)
        return None


async def get_stats() -> dict:
    """
    Dashboard kartları için özet istatistikler döndürür:
    toplam bildirim, bugün, bu hafta, sentiment dağılımı, en aktif şirketler.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_stats_sync, conn)


def _get_stats_sync(conn: psycopg2.extensions.connection) -> dict:
    stats: dict[str, Any] = {}

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM kap_disclosures")
        row = cur.fetchone()
        stats["total"] = int(row[0]) if row else 0

        cur.execute(
            """
            SELECT COUNT(*) FROM kap_disclosures
            WHERE publish_datetime_utc >= NOW() - INTERVAL '1 day'
            """
        )
        row = cur.fetchone()
        stats["today"] = int(row[0]) if row else 0

        cur.execute(
            """
            SELECT COUNT(*) FROM kap_disclosures
            WHERE publish_datetime_utc >= NOW() - INTERVAL '7 days'
            """
        )
        row = cur.fetchone()
        stats["this_week"] = int(row[0]) if row else 0

        cur.execute(
            """
            SELECT sentiment, COUNT(*) as cnt
            FROM kap_disclosures
            WHERE sentiment IS NOT NULL
            GROUP BY sentiment
            """
        )
        rows = cur.fetchall()
        sentiment_counts: dict[str, int] = {}
        for r in rows:
            sentiment_counts[r[0]] = int(r[1])
        stats["sentiment"] = sentiment_counts

        total_with_sentiment = sum(sentiment_counts.values())
        if total_with_sentiment > 0:
            stats["positive_pct"] = round(
                sentiment_counts.get("Olumlu", 0) / total_with_sentiment * 100, 1
            )
            stats["negative_pct"] = round(
                sentiment_counts.get("Olumsuz", 0) / total_with_sentiment * 100, 1
            )
        else:
            stats["positive_pct"] = 0.0
            stats["negative_pct"] = 0.0

        cur.execute(
            """
            SELECT stock_codes, company_name, COUNT(*) as cnt
            FROM kap_disclosures
            WHERE stock_codes IS NOT NULL AND stock_codes != ''
            GROUP BY stock_codes, company_name
            ORDER BY cnt DESC
            LIMIT 5
            """
        )
        rows = cur.fetchall()
        stats["top_companies"] = [
            {"stock_codes": r[0], "company_name": r[1] or "", "count": int(r[2])}
            for r in rows
        ]

    return stats


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
    Bu sayede sentiment analizi hatası alan kayıtlar sonsuz döngüye girmez.
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
            f"""
            SELECT {_DISCLOSURE_COLUMNS}
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
            results.append(_row_to_disclosure(row))
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
            f"""
            SELECT {_DISCLOSURE_COLUMNS}
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
            results.append(_row_to_disclosure(row))
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
            f"""
            SELECT {_DISCLOSURE_COLUMNS}
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
            results.append(_row_to_disclosure(row))
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



async def update_publish_datetime_utc(
    disclosure_index: int, publish_datetime_utc: datetime
) -> None:
    """publish_datetime_utc sütununu günceller."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _update_publish_datetime_utc_sync, conn,
            disclosure_index, publish_datetime_utc,
        )


def _update_publish_datetime_utc_sync(
    conn: psycopg2.extensions.connection,
    disclosure_index: int,
    publish_datetime_utc: datetime,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET publish_datetime_utc = %s
             WHERE disclosure_index = %s
            """,
            (publish_datetime_utc, disclosure_index),
        )


async def get_disclosures_missing_publish_datetime(limit: int = 200) -> list[DisclosureClassified]:
    """
    publish_datetime_utc NULL olan bildirimleri döndürür.
    Backfill için kullanılır: publish_date string'inden parse edilip güncellenir.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_disclosures_missing_publish_datetime_sync, conn, limit,
        )


def _get_disclosures_missing_publish_datetime_sync(
    conn: psycopg2.extensions.connection, limit: int,
) -> list[DisclosureClassified]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_DISCLOSURE_COLUMNS}
            FROM kap_disclosures
            WHERE publish_datetime_utc IS NULL
              AND publish_date IS NOT NULL
              AND publish_date != ''
            ORDER BY disclosure_index DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    results: list[DisclosureClassified] = []
    for row in rows:
        try:
            results.append(_row_to_disclosure(row))
        except Exception as exc:
            log.warning("DB satırı dönüştürülemedi (index={}): {}", row[0], exc)
    return results


async def get_disclosures_needing_price_at_news(limit: int = 100) -> list[DisclosureClassified]:
    """
    price_at_news NULL olan ama publish_datetime_utc dolu olan bildirimleri döndürür.
    Yayınlanma tarihine göre Yahoo Finance'den fiyat çekilecek.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_disclosures_needing_price_at_news_sync, conn, limit,
        )


def _get_disclosures_needing_price_at_news_sync(
    conn: psycopg2.extensions.connection, limit: int,
) -> list[DisclosureClassified]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_DISCLOSURE_COLUMNS}
            FROM kap_disclosures
            WHERE price_at_news IS NULL
              AND publish_datetime_utc IS NOT NULL
              AND stock_codes IS NOT NULL
              AND stock_codes != ''
            ORDER BY disclosure_index DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    results: list[DisclosureClassified] = []
    for row in rows:
        try:
            results.append(_row_to_disclosure(row))
        except Exception as exc:
            log.warning("DB satırı dönüştürülemedi (index={}): {}", row[0], exc)
    return results


async def update_price_at_news(
    disclosure_index: int, price_at_news: float
) -> None:
    """Sadece price_at_news sütununu günceller."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _update_price_at_news_sync, conn, disclosure_index, price_at_news,
        )


def _update_price_at_news_sync(
    conn: psycopg2.extensions.connection,
    disclosure_index: int,
    price_at_news: float,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET price_at_news = %s
             WHERE disclosure_index = %s
            """,
            (price_at_news, disclosure_index),
        )


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
    slug = slugify(title) if title else ""

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


async def get_companies(
    stock_code: str = "",
    limit: int = 0,
    offset: int = 0,
    search_query: str = "",
) -> list[dict]:
    """
    kap_companies tablosundan şirketleri döndürür.
    - stock_code: exact match filtresi
    - search_query: title veya stock_code ILIKE
    - limit/offset: sayfalama (limit=0 → tümünü getir)
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_companies_sync, conn, stock_code, limit, offset, search_query
        )


def _get_companies_sync(
    conn: psycopg2.extensions.connection,
    stock_code: str,
    limit: int,
    offset: int,
    search_query: str,
) -> list[dict]:
    where_clauses: list[str] = []
    params: list[Any] = []

    if stock_code:
        where_clauses.append("stock_code = %s")
        params.append(stock_code.upper())

    if search_query:
        where_clauses.append("(title ILIKE %s OR stock_code ILIKE %s)")
        q = f"%{search_query}%"
        params.extend([q, q.upper()])

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = f"""
        SELECT member_id, title, stock_code, member_type, kfif_url, company_slug, fetched_at
        FROM kap_companies
        {where_sql}
        ORDER BY title
    """

    if limit > 0:
        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(query, params)
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


async def count_companies(search_query: str = "") -> int:
    """Şirket sayısını döndürür (sayfalama için)."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _count_companies_sync, conn, search_query)


def _count_companies_sync(
    conn: psycopg2.extensions.connection, search_query: str
) -> int:
    params: list[Any] = []
    where_sql = ""

    if search_query:
        where_sql = "WHERE (title ILIKE %s OR stock_code ILIKE %s)"
        q = f"%{search_query}%"
        params.extend([q, q.upper()])

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM kap_companies {where_sql}", params)
        row = cur.fetchone()
        return int(row[0]) if row else 0


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


# ---------------------------------------------------------------------------
# PDF Metin İşlemleri
# ---------------------------------------------------------------------------

async def get_disclosures_with_unparsed_pdfs(limit: int = 10) -> list[DisclosureClassified]:
    """
    pdf_link dolu olan (veya attachment_urls'de pdf geçen) ama kap_pdf_texts
    tablosunda henüz ayrıştırılmış metni bulunmayan bildirimleri döndürür.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_disclosures_with_unparsed_pdfs_sync, conn, limit
        )


def _get_disclosures_with_unparsed_pdfs_sync(
    conn: psycopg2.extensions.connection, limit: int
) -> list[DisclosureClassified]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT d.{_DISCLOSURE_COLUMNS.replace(',', ', d.')}
            FROM kap_disclosures d
            LEFT JOIN kap_pdf_texts p ON d.disclosure_index = p.disclosure_index
            WHERE (d.pdf_link IS NOT NULL OR d.attachment_urls::text LIKE '%%pdf%%')
              AND p.disclosure_index IS NULL
            ORDER BY d.disclosure_index DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    results: list[DisclosureClassified] = []
    for row in rows:
        try:
            results.append(_row_to_disclosure(row))
        except Exception as exc:
            log.warning("DB satırı dönüştürülemedi (index={}): {}", row[0], exc)

    return results


async def upsert_pdf_text(disclosure_index: int, extracted_text: str) -> None:
    """PDF'ten çıkarılan metni kap_pdf_texts tablosuna kaydeder."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _upsert_pdf_text_sync, conn, disclosure_index, extracted_text)


def _upsert_pdf_text_sync(
    conn: psycopg2.extensions.connection, disclosure_index: int, extracted_text: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kap_pdf_texts (disclosure_index, extracted_text)
            VALUES (%s, %s)
            ON CONFLICT (disclosure_index) DO UPDATE
                SET extracted_text = EXCLUDED.extracted_text,
                    parsed_at      = NOW()
            """,
            (disclosure_index, extracted_text),
        )


# ---------------------------------------------------------------------------
# PDF LLM Extraction İşlemleri
# ---------------------------------------------------------------------------

async def get_pdfs_needing_extraction(limit: int = 10) -> list[dict]:
    """
    kap_pdf_texts tablosunda metni olan ancak kap_pdf_parsed_data'da 
    henüz ayrıştırılmamış kayıtları döndürür.
    """
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_pdfs_needing_extraction_sync, conn, limit
        )

def _get_pdfs_needing_extraction_sync(
    conn: psycopg2.extensions.connection, limit: int
) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.disclosure_index, p.extracted_text, d.news_category, d.disclosure_type
            FROM kap_pdf_texts p
            JOIN kap_disclosures d ON p.disclosure_index = d.disclosure_index
            LEFT JOIN kap_pdf_parsed_data e ON p.disclosure_index = e.disclosure_index
            WHERE e.disclosure_index IS NULL
            ORDER BY p.disclosure_index DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    results = []
    for row in rows:
        results.append({
            "disclosure_index": row[0],
            "extracted_text": row[1] or "",
            "news_category": row[2] or "Genel",
            "disclosure_type": row[3] or "Bilinmiyor"
        })
    return results

async def upsert_pdf_parsed_data(disclosure_index: int, category_type: str, parsed_json: dict) -> None:
    """LLM'den dönen yapılandırılmış veriyi kaydeder."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _upsert_pdf_parsed_data_sync, conn, disclosure_index, category_type, parsed_json)

def _upsert_pdf_parsed_data_sync(
    conn: psycopg2.extensions.connection, disclosure_index: int, category_type: str, parsed_json: dict
) -> None:
    json_str = json.dumps(parsed_json, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kap_pdf_parsed_data (disclosure_index, category_type, parsed_json)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (disclosure_index) DO UPDATE
                SET category_type = EXCLUDED.category_type,
                    parsed_json   = EXCLUDED.parsed_json,
                    extracted_at  = NOW()
            """,
            (disclosure_index, category_type, json_str),
        )


# ---------------------------------------------------------------------------
# Gemma özet / analiz işlemleri
# ---------------------------------------------------------------------------

async def get_pending_gemma_summaries(
    limit: int,
    full_text_threshold: int = 1000,
) -> list[dict[str, Any]]:
    """Gemma ile özetlenmeye uygun ve henüz özetlenmemiş kayıtları döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_pending_gemma_summaries_sync, conn, limit, full_text_threshold
        )


def _get_pending_gemma_summaries_sync(
    conn: psycopg2.extensions.connection,
    limit: int,
    full_text_threshold: int,
) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                disclosure_index,
                stock_codes,
                company_name,
                news_category,
                disclosure_type,
                title,
                subject,
                full_text,
                pdf_link,
                LENGTH(full_text) AS ft_len
            FROM kap_disclosures
            WHERE
                (llm_summary IS NULL OR llm_summary = '')
                AND llm_summary_at IS NULL
                AND (
                    LENGTH(full_text) > %s
                    OR (
                        (full_text IS NULL OR LENGTH(full_text) <= %s)
                        AND pdf_link IS NOT NULL
                        AND pdf_link != ''
                    )
                )
            ORDER BY
                CASE news_category
                    WHEN 'Finansal Rapor' THEN 1
                    WHEN 'Özel Durum'     THEN 2
                    WHEN 'Sermaye'        THEN 3
                    WHEN 'Temettü'        THEN 4
                    ELSE 5
                END,
                disclosure_index DESC
            LIMIT %s
            """,
            (full_text_threshold, full_text_threshold, limit),
        )
        return [dict(row) for row in cur.fetchall()]


async def save_gemma_summary(
    disclosure_index: int,
    summary: str,
    source: str,
    category: str,
) -> None:
    """Gemma özetini kap_disclosures ve kap_pdf_parsed_data tablolarına yazar."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            _save_gemma_summary_sync,
            conn,
            disclosure_index,
            summary,
            source,
            category,
        )


def _save_gemma_summary_sync(
    conn: psycopg2.extensions.connection,
    disclosure_index: int,
    summary: str,
    source: str,
    category: str,
) -> None:
    parsed_json = json.dumps({"summary": summary, "source": source}, ensure_ascii=False)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET llm_summary        = %s,
                   llm_summary_at     = NOW(),
                   llm_summary_source = %s
             WHERE disclosure_index = %s
            """,
            (summary, source, disclosure_index),
        )
        cur.execute(
            """
            INSERT INTO kap_pdf_parsed_data
                (disclosure_index, category_type, parsed_json, summary, summarized_at)
            VALUES (%s, %s, %s::jsonb, %s, NOW())
            ON CONFLICT (disclosure_index) DO UPDATE
                SET category_type = EXCLUDED.category_type,
                    summary       = EXCLUDED.summary,
                    parsed_json   = EXCLUDED.parsed_json,
                    summarized_at = NOW()
            """,
            (disclosure_index, (category or "Genel")[:100], parsed_json, summary),
        )


async def mark_gemma_summary_failed(disclosure_index: int) -> None:
    """Özetlenemeyen kaydı yeniden denenmemesi için işaretler."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _mark_gemma_summary_failed_sync, conn, disclosure_index)


def _mark_gemma_summary_failed_sync(
    conn: psycopg2.extensions.connection,
    disclosure_index: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE kap_disclosures
               SET llm_summary    = '__FAILED__',
                   llm_summary_at = NOW()
             WHERE disclosure_index = %s
            """,
            (disclosure_index,),
        )


async def get_gemma_summary_stats(
    full_text_threshold: int = 1000,
    min_text_length: int = 100,
) -> dict[str, Any]:
    """Gemma özetleme kapsam istatistiklerini döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _get_gemma_summary_stats_sync,
            conn,
            full_text_threshold,
            min_text_length,
        )


def _get_gemma_summary_stats_sync(
    conn: psycopg2.extensions.connection,
    full_text_threshold: int,
    min_text_length: int,
) -> dict[str, Any]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS toplam,
                COUNT(CASE WHEN LENGTH(full_text) > %s THEN 1 END) AS fulltext_uzun,
                COUNT(CASE WHEN LENGTH(full_text) <= %s
                           AND pdf_link IS NOT NULL AND pdf_link != '' THEN 1 END) AS kisa_ama_pdf,
                COUNT(CASE WHEN (full_text IS NULL OR LENGTH(full_text) < %s)
                           AND (pdf_link IS NULL OR pdf_link = '') THEN 1 END) AS atlanacak,
                COUNT(CASE WHEN llm_summary IS NOT NULL
                           AND llm_summary != '__FAILED__' THEN 1 END) AS ozetlenmis,
                COUNT(CASE WHEN llm_summary = '__FAILED__' THEN 1 END) AS basarisiz,
                COUNT(CASE WHEN llm_summary_source = 'full_text' THEN 1 END) AS fulltext_kaynakli,
                COUNT(CASE WHEN llm_summary_source = 'pdf' THEN 1 END) AS pdf_kaynakli
            FROM kap_disclosures
            """,
            (full_text_threshold, full_text_threshold, min_text_length),
        )
        row = dict(cur.fetchone() or {})
        fulltext_uzun = row.get("fulltext_uzun") or 0
        kisa_ama_pdf = row.get("kisa_ama_pdf") or 0
        ozetlenmis = row.get("ozetlenmis") or 0
        basarisiz = row.get("basarisiz") or 0
        row["bekleyen"] = fulltext_uzun + kisa_ama_pdf - ozetlenmis - basarisiz
        return row


async def get_gemma_summary_category_stats(full_text_threshold: int = 1000) -> list[dict[str, Any]]:
    """Gemma özet kapsamını kategori bazında döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, _get_gemma_summary_category_stats_sync, conn, full_text_threshold
        )


def _get_gemma_summary_category_stats_sync(
    conn: psycopg2.extensions.connection,
    full_text_threshold: int,
) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT news_category,
                   COUNT(*) AS n,
                   COUNT(CASE WHEN LENGTH(full_text) > %s THEN 1 END) AS ft_uzun,
                   COUNT(CASE WHEN LENGTH(full_text) <= %s
                              AND pdf_link IS NOT NULL AND pdf_link != '' THEN 1 END) AS kisa_pdf,
                   COUNT(CASE WHEN llm_summary IS NOT NULL
                              AND llm_summary != '__FAILED__' THEN 1 END) AS ozetlenmis
            FROM kap_disclosures
            GROUP BY news_category
            ORDER BY n DESC
            """,
            (full_text_threshold, full_text_threshold),
        )
        return [dict(row) for row in cur.fetchall()]


async def get_pending_gemma_pdf_analyses(limit: int) -> list[dict[str, Any]]:
    """PDF linki olan ve henüz Gemma yatırımcı değerlendirmesi yapılmamış kayıtları döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_pending_gemma_pdf_analyses_sync, conn, limit)


def _get_pending_gemma_pdf_analyses_sync(
    conn: psycopg2.extensions.connection,
    limit: int,
) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                d.disclosure_index,
                d.company_name,
                d.news_category,
                d.title,
                d.pdf_link,
                SPLIT_PART(d.stock_codes, ',', 1) AS hisse
            FROM kap_disclosures d
            JOIN kap_companies c ON c.stock_code = SPLIT_PART(d.stock_codes, ',', 1)
            WHERE
                (c.member_type LIKE 'IGS%%' OR c.member_type = 'IGMS')
                AND d.pdf_link IS NOT NULL AND d.pdf_link != ''
                AND d.stock_codes IS NOT NULL AND d.stock_codes != ''
                AND NOT EXISTS (
                    SELECT 1 FROM kap_disclosure_analiz a
                    WHERE a.disclosure_index = d.disclosure_index
                )
            ORDER BY
                CASE d.news_category
                    WHEN 'Finansal Rapor' THEN 1
                    WHEN 'Özel Durum'     THEN 2
                    WHEN 'Sermaye'        THEN 3
                    ELSE 4
                END,
                RANDOM()
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


async def save_gemma_pdf_analysis(
    disclosure_index: int,
    reason: str,
    sentiment: str,
    confidence_score: float = 1.0,
) -> None:
    """Gemma yatırımcı değerlendirmesini kap_disclosure_analiz tablosuna yazar."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            _save_gemma_pdf_analysis_sync,
            conn,
            disclosure_index,
            reason,
            sentiment,
            confidence_score,
        )


def _save_gemma_pdf_analysis_sync(
    conn: psycopg2.extensions.connection,
    disclosure_index: int,
    reason: str,
    sentiment: str,
    confidence_score: float,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO kap_disclosure_analiz
                (disclosure_index, analyzed_text, sentiment_label, confidence_score)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (disclosure_index) DO UPDATE
                SET analyzed_text    = EXCLUDED.analyzed_text,
                    sentiment_label  = EXCLUDED.sentiment_label,
                    confidence_score = EXCLUDED.confidence_score,
                    analyzed_at      = CURRENT_TIMESTAMP
            """,
            (disclosure_index, reason, sentiment, confidence_score),
        )


# ---------------------------------------------------------------------------
# Analiz raporlama sorguları
# ---------------------------------------------------------------------------

async def get_analysis_disclosures(
    min_price: bool = True,
    require_sentiment: bool = False,
    require_1d: bool = True,
    category: str | None = None,
    stock_code: str | None = None,
) -> list[dict[str, Any]]:
    """Event study/raporlama için temizlenmeye hazır bildirim satırlarını döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            _get_analysis_disclosures_sync,
            conn,
            min_price,
            require_sentiment,
            require_1d,
            category,
            stock_code,
        )


def _get_analysis_disclosures_sync(
    conn: psycopg2.extensions.connection,
    min_price: bool,
    require_sentiment: bool,
    require_1d: bool,
    category: str | None,
    stock_code: str | None,
) -> list[dict[str, Any]]:
    where_clauses = [
        "stock_codes IS NOT NULL",
        "stock_codes != ''",
        "publish_datetime_utc IS NOT NULL",
    ]
    params: list[Any] = []
    if min_price:
        where_clauses.append("price_at_news IS NOT NULL")
    if require_1d:
        where_clauses.append("price_1d IS NOT NULL")
    if require_sentiment:
        where_clauses.append("sentiment IS NOT NULL")
    if category:
        where_clauses.append("news_category = %s")
        params.append(category)
    if stock_code:
        where_clauses.append("stock_codes ILIKE %s")
        params.append(f"%{stock_code.upper()}%")

    where_sql = "WHERE " + " AND ".join(where_clauses)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                disclosure_index,
                stock_codes,
                company_name,
                news_category,
                sentiment,
                publish_datetime_utc,
                price_at_news,
                price_5m,
                price_1h,
                price_1d,
                price_1w,
                subject,
                kap_link
            FROM kap_disclosures
            {where_sql}
            ORDER BY publish_datetime_utc DESC
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


async def get_analysis_data_quality_report() -> dict[str, Any]:
    """Analiz veri kalitesi özetini döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_analysis_data_quality_report_sync, conn)


def _get_analysis_data_quality_report_sync(conn: psycopg2.extensions.connection) -> dict[str, Any]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS toplam,
                COUNT(price_at_news) AS fiyat_var,
                COUNT(price_5m) AS price_5m_var,
                COUNT(price_1h) AS price_1h_var,
                COUNT(price_1d) AS price_1d_var,
                COUNT(price_1w) AS price_1w_var,
                COUNT(sentiment) AS sentiment_var,
                COUNT(CASE WHEN price_at_news IS NOT NULL
                           AND price_1d IS NOT NULL
                           AND sentiment IS NOT NULL THEN 1 END) AS tam_kayit,
                COUNT(CASE WHEN price_at_news IS NOT NULL
                           AND price_1d IS NOT NULL THEN 1 END) AS fiyat_tam,
                COUNT(DISTINCT stock_codes) AS benzersiz_hisse,
                COUNT(DISTINCT news_category) AS benzersiz_kategori,
                MIN(publish_datetime_utc) AS en_eski,
                MAX(publish_datetime_utc) AS en_yeni
            FROM kap_disclosures
            WHERE stock_codes IS NOT NULL AND stock_codes != ''
            """
        )
        return dict(cur.fetchone() or {})


async def get_analysis_category_breakdown() -> list[dict[str, Any]]:
    """Kategori bazlı analiz kapsamını döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_analysis_category_breakdown_sync, conn)


def _get_analysis_category_breakdown_sync(conn: psycopg2.extensions.connection) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                news_category,
                COUNT(*) AS total,
                COUNT(price_1d) AS has_price_1d,
                COUNT(sentiment) AS has_sentiment,
                COUNT(CASE WHEN price_1d IS NOT NULL AND sentiment IS NOT NULL THEN 1 END) AS complete,
                AVG(CASE WHEN price_at_news > 0 THEN
                    (price_1d - price_at_news) / price_at_news * 100 END) AS avg_return_1d_pct
            FROM kap_disclosures
            WHERE stock_codes IS NOT NULL AND stock_codes != ''
            GROUP BY news_category
            ORDER BY total DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


async def get_analysis_top_companies(limit: int = 20) -> list[dict[str, Any]]:
    """En çok bildirimi olan şirketleri döndürür."""
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_analysis_top_companies_sync, conn, limit)


def _get_analysis_top_companies_sync(
    conn: psycopg2.extensions.connection,
    limit: int,
) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                primary_stock,
                company_name,
                COUNT(*) AS disclosure_count,
                COUNT(price_1d) AS has_price_count,
                AVG(CASE WHEN price_at_news > 0 THEN
                    (price_1d - price_at_news) / price_at_news * 100 END) AS avg_return_1d
            FROM (
                SELECT
                    SPLIT_PART(stock_codes, ',', 1) AS primary_stock,
                    company_name,
                    price_at_news,
                    price_1d
                FROM kap_disclosures
                WHERE stock_codes IS NOT NULL AND stock_codes != ''
            ) sub
            GROUP BY primary_stock, company_name
            ORDER BY disclosure_count DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


