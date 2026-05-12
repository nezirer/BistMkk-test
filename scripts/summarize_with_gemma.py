"""
scripts/summarize_with_gemma.py

Akıllı kaynak seçimi ile KAP bildirimlerini Gemma-3 GGUF ile özetler.

Kural:
  1. full_text > 1000 karakter  → full_text ile özetle
  2. full_text ≤ 1000 + pdf_link varsa → PDF indir, metni çıkar, özetle
  3. full_text < 100 + pdf_link yoksa  → ATLA (işleme alma)

Kullanım:
    cd kap-classifier
    python -m scripts.summarize_with_gemma             # 10 kayıt (varsayılan)
    python -m scripts.summarize_with_gemma --batch 50  # 50 kayıt
    python -m scripts.summarize_with_gemma --stats     # Sadece istatistik göster
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import db.repository as repo
from db.connection import init_pool, close_pool, get_connection
from db.models import create_tables
from utils.logger import get_logger
from utils.pdf_parser import extract_text_from_pdf_url
from classifier.local_llm import generate_summary

log = get_logger("summarize_with_gemma")

# ─── Ayarlar ────────────────────────────────────────────────────────────────
BATCH_SIZE          = int(os.getenv("BATCH_SIZE", "10"))
SLEEP_BETWEEN       = float(os.getenv("SLEEP_BETWEEN", "2"))
FULL_TEXT_THRESHOLD = 1000   # Bu uzunluktan büyükse full_text kullan
MIN_TEXT_LENGTH     = 100    # Bu uzunluktan kısa + pdf yoksa atla


async def _init_db() -> None:
    init_pool()
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, create_tables, conn)


async def _mark_failed(disclosure_index: int, reason: str = "") -> None:
    await repo.mark_gemma_summary_failed(disclosure_index)
    if reason:
        log.warning("  Başarısız işaretlendi ({}): {}", disclosure_index, reason)


# ─── Ana İşlem ──────────────────────────────────────────────────────────────

async def run_summarization():
    await _init_db()
    log.info("DB bağlantısı kuruldu.")

    pending = await repo.get_pending_gemma_summaries(BATCH_SIZE, FULL_TEXT_THRESHOLD)
    if not pending:
        log.info("Özetlenecek uygun kayıt bulunamadı.")
        close_pool()
        return

    log.info("Bu batch'te {} kayıt işlenecek...", len(pending))

    success  = 0
    failed   = 0
    skipped  = 0

    for i, row in enumerate(pending, 1):
        idx      = row["disclosure_index"]
        ft       = (row.get("full_text") or "").strip()
        ft_len   = len(ft)
        pdf_link = (row.get("pdf_link") or "").strip()
        company  = (row.get("company_name") or row.get("stock_codes") or "?")[:40]
        category = row.get("news_category") or row.get("disclosure_type") or "Genel"

        # ── Kaynak kararı ──────────────────────────────────────
        if ft_len > FULL_TEXT_THRESHOLD:
            source     = "full_text"
            text_input = ft
            log.info("[{}/{}] #{} | {} | {} | full_text ({} kar)",
                     i, len(pending), idx, company, category, ft_len)

        elif pdf_link:
            source = "pdf"
            log.info("[{}/{}] #{} | {} | {} | PDF indiriliyor...",
                     i, len(pending), idx, company, category)
            try:
                pdf_text = await extract_text_from_pdf_url(pdf_link)
            except Exception as exc:
                log.error("  PDF indirme hatası: {}", exc)
                await _mark_failed(idx, str(exc))
                failed += 1
                continue

            if not pdf_text or pdf_text.strip() == "No text extracted (Possible Image PDF)":
                log.warning("  PDF'ten metin çıkarılamadı (görüntü PDF olabilir). Atlanıyor.")
                await _mark_failed(idx, "PDF metin çıkarılamadı")
                failed += 1
                continue

            text_input = pdf_text
            log.info("  PDF metni çıkarıldı: {} karakter", len(pdf_text))

        else:
            # full_text kısa, PDF de yok → atla (kural 3)
            log.debug("  Atlandı: full_text={} kar, PDF yok.", ft_len)
            skipped += 1
            continue

        # ── Gemma ile özetle ────────────────────────────────────
        try:
            t0      = time.time()
            summary = await generate_summary(text_input)
            elapsed = time.time() - t0

            if not summary or summary == "Özetleme işlemi başarısız.":
                await _mark_failed(idx, "Gemma boş yanıt")
                failed += 1
                continue

            log.info("  ✓ Özet ({}, {:.1f}sn): {}",
                     source, elapsed, summary[:120].replace("\n", " "))
            await repo.save_gemma_summary(idx, summary, source, category)
            success += 1

        except Exception as exc:
            log.error("  ✗ Özetleme hatası: {}", exc)
            await _mark_failed(idx, str(exc))
            failed += 1

        if i < len(pending):
            await asyncio.sleep(SLEEP_BETWEEN)

    close_pool()
    log.info("Tamamlandı — Başarılı: {} | Başarısız: {} | Atlandı: {}",
             success, failed, skipped)


# ─── İstatistik ─────────────────────────────────────────────────────────────

async def print_stats():
    await _init_db()
    stats = await repo.get_gemma_summary_stats(FULL_TEXT_THRESHOLD, MIN_TEXT_LENGTH)
    cats = await repo.get_gemma_summary_category_stats(FULL_TEXT_THRESHOLD)

    print(f"\n{'='*55}")
    print(f"  Toplam bildirim          : {stats['toplam']:>7}")
    print(f"  {'-'*43}")
    print(f"  full_text > {FULL_TEXT_THRESHOLD} kar (Kural 1)  : {stats['fulltext_uzun']:>7}")
    print(f"  full_text kısa + PDF var (Kural 2) : {stats['kisa_ama_pdf']:>7}")
    print(f"  Atlanacak (Kural 3)      : {stats['atlanacak']:>7}")
    print(f"  {'-'*43}")
    print(f"  Özetlenmiş               : {stats['ozetlenmis']:>7}")
    print(f"    -> full_text kaynağı   : {stats['fulltext_kaynakli']:>7}")
    print(f"    -> PDF kaynağı         : {stats['pdf_kaynakli']:>7}")
    print(f"  Başarısız                : {stats['basarisiz']:>7}")
    print(f"  Bekleyen                 : {stats['bekleyen']:>7}")
    print(f"{'='*55}\n")

    if cats:
        print(f"  {'Kategori':<22} {'Toplam':>7} {'FT>1k':>6} {'PDF':>6} {'Özet':>6}")
        print(f"  {'-'*22} {'-'*7} {'-'*6} {'-'*6} {'-'*6}")
        for c in cats:
            print(
                f"  {(c['news_category'] or 'Diğer'):<22} {c['n']:>7} "
                f"{c['ft_uzun']:>6} {c['kisa_pdf']:>6} {c['ozetlenmis']:>6}"
            )
        print()

    close_pool()


# ─── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gemma-3 ile KAP bildirimleri özetleme")
    parser.add_argument("--stats",  action="store_true", help="Sadece istatistik göster")
    parser.add_argument("--batch",  type=int, default=BATCH_SIZE, help=f"Batch büyüklüğü (varsayılan: {BATCH_SIZE})")
    args = parser.parse_args()

    if args.stats:
        asyncio.run(print_stats())
        sys.exit(0)

    BATCH_SIZE = args.batch

    try:
        asyncio.run(run_summarization())
    except KeyboardInterrupt:
        log.warning("Kullanıcı tarafından durduruldu.")
