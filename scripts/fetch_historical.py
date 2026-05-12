"""
Tarihsel KAP bildirimlerini (son 1000 adet) yavaşça çeken araç.
Bu script, MKK API limitlerine (rate limit) takılmadan geriye dönük verileri
yaklaşık 1 saatlik bir süre zarfında veritabanına aktarmak için tasarlanmıştır.

Kullanım:
    cd kap-classifier
    python -m scripts.fetch_historical
"""
from __future__ import annotations

import os
import sys
import asyncio
from dotenv import load_dotenv

# Ana dizini system_path'e ekle (module importlarını doğru çözebilmek için)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from utils.logger import get_logger
from db.connection import init_pool, close_pool, get_connection
from db.models import create_tables
import db.repository as repo
from fetcher.provider_factory import get_provider
from fetcher.mkk_provider import MKKProvider
import classifier.news_type as news_svc
import classifier.company as company_svc
from fetcher.finance import get_price_at_publish
from models.disclosure import DisclosureClassified

log = get_logger("fetch_historical")

START_INDEX = 1  # 1 yaparsanız KAP'ın kuruluşundan (ilk veri) günümüze çeker, gaps(boşluklar) otomatik atlanır
BATCH_SIZE = 50
WAIT_SECONDS_BETWEEN_BATCHES = 180  # 3 dakika

async def run_historical_pull():
    log.info("Historical fetch (Sınırsız) başlatılıyor. Batch: {}, Bekleme: {}sn", 
             BATCH_SIZE, WAIT_SECONDS_BETWEEN_BATCHES)
             
    # PostgreSQL Başlat
    init_pool()
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, create_tables, conn)
        
    provider = get_provider()
    
    if not isinstance(provider, MKKProvider):
        log.error("Bu script sadece MKKProvider ile çalışır! .env dosyasında KAP_PROVIDER=mkk yapın.")
        close_pool()
        return

    # 1. MKK üzerinden son yayınlanan index'i bul
    try:
        idx_payload = await provider._get("/lastDisclosureIndex")
        last_index = int(idx_payload.get("lastDisclosureIndex", 0))
    except Exception as exc:
        log.error("Son index alınamadı: {}", exc)
        await provider.close()
        close_pool()
        return
        
    if last_index == 0:
        log.error("Geçersiz last_index: 0")
        await provider.close()
        close_pool()
        return
        
    log.info("API'deki güncel son index: {}", last_index)
    
    batch_idx = 0

    # User already pulled 1000 items in the first run.
    # Start checking from where we left off (last_index - 1000) or just last_index
    current_upper_bound = last_index - 1000
    
    log.info("Zaten çekilmiş olan ilk 1000 kaydın öncesine iniliyor...")

    # Geriye doğru giden döngü
    while current_upper_bound > 0:
        batch_idx += 1
        # Geriye doğru 50'şer aralıklarla çekiyoruz
        fetch_start_idx = max(1, current_upper_bound - BATCH_SIZE)
        
        log.info("--- Batch {} başlıyor. (Aranan index aralığı: {} -> {}) ---", batch_idx, fetch_start_idx, current_upper_bound)
        
        try:
            # API liste çağrısı
            items = await provider._get(
                "/disclosures",
                params={"disclosureIndex": fetch_start_idx},
            )
            
            if not items or not isinstance(items, list):
                log.info("Yeni liste dönmedi (veya boş). Kayıtlar bitmiş olabilir.")
                break
                
            # Gelen diziyi 50 item ile sınırla
            batch_items = items[:BATCH_SIZE]
            
            inserted_count = 0
            
            for raw_item in batch_items:
                raw_idx = raw_item.get("disclosureIndex")
                if not raw_idx:
                    continue
                    
                val_idx = int(raw_idx)
                
                if await repo.disclosure_exists(val_idx):
                    log.debug("Index {} DB'de mevcut. Atlanıyor.", val_idx)
                    continue

                # Zenginleştirme
                from models.disclosure import DisclosureRaw
                try:
                    disclosure = DisclosureRaw.from_list_item(raw_item)
                except Exception as exc:
                    log.warning("Disclosure parse atlandı (index={}): {}", val_idx, exc)
                    continue
                    
                # MKK Detay İstediği
                try:
                    detail = await provider._get(
                        f"/disclosureDetail/{disclosure.disclosure_index}",
                        params={"fileType": "html"},
                    )
                    if isinstance(detail, dict):
                        disclosure.enrich_from_detail(detail)
                except Exception as exc:
                    log.warning("Detay okunamadı (index={})", disclosure.disclosure_index)

                # Sınıflandırma
                try:
                    category = news_svc.classify(disclosure)
                    slug = company_svc.get_company_slug(disclosure.stock_codes, disclosure.company_name)
                    classified = DisclosureClassified.from_raw(
                        disclosure,
                        news_category=news_svc.get_category_label(category),
                        company_slug=slug,
                    )
                    
                    if not classified.publish_datetime_utc:
                        classified.publish_datetime_utc = classified._parse_publish_datetime_utc()

                    # Finans / Fiyat ekle
                    if classified.stock_codes and classified.publish_datetime_utc:
                        first_code = classified.stock_codes.split(",")[0].strip()
                        if first_code:
                            price = await get_price_at_publish(first_code, classified.publish_datetime_utc)
                            if price is not None:
                                classified.price_at_news = price
                                
                    await repo.upsert_disclosure(classified)
                    inserted_count += 1
                except Exception as exc:
                    log.error("DB kayıt/algoritma hatası (index={}): {}", disclosure.disclosure_index, exc)

            log.info("Batch {} tamamlandı. Gelen haber: {}, Kaydedilen yeni haber: {}", batch_idx, len(batch_items), inserted_count)
            
            # Geriye doğru ilerle
            current_upper_bound = fetch_start_idx

        except Exception as exc:
            # 400 Bad Request geldiyse, test ortamındaki API'nin sınırına (en eski kayda) ulaştık demektir.
            error_str = str(exc)
            if "400" in error_str or "Bad Request" in error_str:
                log.warning("API 400 Bad Request döndürdü. Bu durum MKK test ortamındaki ulaşılabilir en eski habere (sınıra) geldiğimizi gösterir.")
                log.info("Veri çekimi kalıcı olarak durduruldu, sona ulaşıldı.")
                break
            else:
                log.error("Batch {} sırasında kritik hata: {}", batch_idx, exc)
            
        if current_upper_bound > 0:
            log.info("{} saniye bekleniyor...", WAIT_SECONDS_BETWEEN_BATCHES)
            await asyncio.sleep(WAIT_SECONDS_BETWEEN_BATCHES)

    log.info("!!! Tüm geçmiş haber işlemi (geriye dönük) tamamlandı !!!")
    
    await provider.close()
    close_pool()

if __name__ == "__main__":
    try:
        asyncio.run(run_historical_pull())
    except KeyboardInterrupt:
        log.warning("Kullanıcı tarafından yarıda kesildi.")
