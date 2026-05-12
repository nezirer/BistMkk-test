"""
scripts/production_pipeline.py

Production Pipeline (Sadece Gemma):
PDF İndir → Gemma ile değerlendir (Sentiment ve Gerekçe üret) → Sonuçları kaydet
"""
import asyncio
import sys
import os
import json
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import db.repository as repo
from db.connection import init_pool, close_pool, get_connection
from db.models import create_tables
from utils.logger import get_logger
from utils.pdf_parser import extract_text_from_pdf_url
from classifier.local_llm import get_summarizer

log = get_logger("prod_pipeline")

SYSTEM_PROMPT = """Sen uzman bir BIST (Borsa İstanbul) analistisin. Türkiye borsasında işlem gören şirketlerin KAP bildirimlerini inceleyip, bireysel hisse senedi yatırımcısı açısından kısa vadeli fiyat etkisini değerlendiriyorsun.

Yanıtını SADECE aşağıdaki JSON formatında ver, dışına kesinlikle hiçbir metin yazma:
{
  "sentiment_label": "Olumlu",
  "reason": "Bildirimin yatırımcı açısından neden bu şekilde yorumlandığını 1-2 cümleyle açıkla."
}

sentiment_label için yalnızca şu üç değerden birini kullan: Olumlu, Olumsuz, Nötr"""

USER_PROMPT_TEMPLATE = """Şirket: {company} ({hisse})
Bildirim Kategorisi: {category}

Aşağıdaki KAP bildirimini yatırımcı perspektifinden değerlendir ve JSON olarak yanıtla:

{text}"""


async def _init_db() -> None:
    init_pool()
    async with get_connection() as conn:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, create_tables, conn)

def parse_gemma_json(response_text: str) -> dict:
    try:
        # Markdown kod bloğunu temizle
        clean_text = re.sub(r'```(?:json)?', '', response_text).strip()
        data = json.loads(clean_text)
        
        raw_label = str(data.get("sentiment_label", "Nötr")).strip()
        label_map = {
            "olumlu": "Olumlu", "positive": "Olumlu",
            "olumsuz": "Olumsuz", "negative": "Olumsuz",
            "nötr": "Nötr", "notr": "Nötr", "neutral": "Nötr",
        }
        label = label_map.get(raw_label.lower(), "Nötr")
            
        return {
            "sentiment": label,
            "reason": data.get("reason", response_text)
        }
    except Exception as e:
        log.warning(f"JSON parse hatası: {e}. Ham metin kullanılıyor.")
        # Eğer model inat edip düz metin verdiyse
        label = "Nötr"
        if "olumlu" in response_text.lower(): label = "Olumlu"
        elif "olumsuz" in response_text.lower() or "kötü" in response_text.lower(): label = "Olumsuz"
        
        return {"sentiment": label, "reason": response_text.strip()[:500]}

def gemma_investor_analysis(pdf_text: str, company: str = "", hisse: str = "", category: str = "") -> dict:
    llm = get_summarizer()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": USER_PROMPT_TEMPLATE.format(
            company=company or "Bilinmiyor",
            hisse=hisse or "?",
            category=category or "Genel",
            text=pdf_text[:6000],
        )},
    ]
    response = llm.create_chat_completion(
        messages=messages,
        max_tokens=400,
        temperature=0.0,
    )
    content = response["choices"][0]["message"]["content"]
    return parse_gemma_json(content)

async def run_pipeline(limit: int):
    await _init_db()
    records = await repo.get_pending_gemma_pdf_analyses(limit)
    if not records:
        log.info("İşlenecek kayıt bulunamadı.")
        close_pool()
        return

    log.info(f"{len(records)} adet yeni kayıt işleme alınıyor...")

    success_count = 0
    error_count = 0

    for i, record in enumerate(records, 1):
        idx = record["disclosure_index"]
        company = record["company_name"] or ""
        category = record["news_category"] or "Genel"
        pdf_link = record["pdf_link"]
        hisse = record["hisse"] or "?"
        print(f"\n{'='*55}\n[{i}/{len(records)}] #{idx} | {hisse} - {company[:30]} | {category}")
        
        try:
            # 1. PDF
            pdf_text = await extract_text_from_pdf_url(pdf_link)
            if not pdf_text or "No text extracted" in pdf_text:
                raise ValueError("PDF okunamadı veya resim formatında.")

            # 2. Gemma Doğrudan Sentiment ve Gerekçe Üretir
            result = gemma_investor_analysis(pdf_text, company=company, hisse=hisse, category=category)
            sentiment = result["sentiment"]
            reason = result["reason"]

            print(f"  → Karar : {sentiment}")
            print(f"  → Neden : {reason}")

            # 3. DB kayıt repository üzerinden yapılır.
            await repo.save_gemma_pdf_analysis(idx, reason, sentiment, 1.0)
            success_count += 1

        except Exception as e:
            print(f"  ✗ HATA: {e}")
            error_count += 1

    close_pool()
    log.info(f"\nPipeline Tamamlandı. Başarılı: {success_count}, Hatalı: {error_count}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10, help="İşlenecek kayıt sayısı")
    args = parser.parse_args()
    
    asyncio.run(run_pipeline(args.limit))
