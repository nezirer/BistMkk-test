"""
KAP Classifier — LLM Duygu Analizi (Sentiment Analysis) Modülü.

Bu modül, OpenAI API'sini kullanarak KAP bildirimlerinin başlık ve özetinden
olumlu, olumsuz veya nötr olup olmadığını değerlendirir.
"""
from __future__ import annotations

import os
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from utils.logger import get_logger

log = get_logger(__name__)

# Ortam değişkeninden API anahtarını alıyoruz.
# main.py'de load_dotenv() çağrıldığı için burada os.getenv ile erişilebilir.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Asenkron istemciyi global olarak oluşturuyoruz (API key varsa)
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY and OPENAI_API_KEY != "your_openai_api_key_here" else None


class SentimentResult(BaseModel):
    sentiment: Literal["Olumlu", "Olumsuz", "Nötr"] = Field(
        description="Haberin hisse senedi fiyatına olası etkisi."
    )
    reason: str = Field(
        description="Bu duygu durumunun seçilme nedeni (maksimum 2 cümle)."
    )


SYSTEM_PROMPT = """\
Sen BIST (Borsa İstanbul) odaklı bir hisse senedi analiz uzmanısın.
Görevin: KAP (Kamuyu Aydınlatma Platformu) bildirimlerinin ilgili şirketin \
hisse senedi fiyatı üzerindeki olası etkisini sınıflandırmak.

KARAR KURALLARI:
- Olumlu: Kâr artışı, temettü dağıtımı, yeni iş/sözleşme kazanımı, \
sermaye artırımı (bedelsiz), güçlü finansal sonuçlar, kredi notu yükselmesi, \
stratejik ortaklık veya satın alma, geri alım programı.
- Olumsuz: Zarar açıklama, sermaye azaltımı, borç yapılandırma, idari/hukuki \
yaptırım, yönetimde olumsuz değişiklik, üretim/faaliyet durması, kredi notu \
düşürülme, önemli dava kaybı.
- Nötr: Rutin genel kurul çağrısı, yönetmelik değişikliği, bilgilendirme \
niteliğinde açıklama, mevcut durumu teyit eden bildirim, periyodik rutin rapor \
(içeriğinde belirgin olumlu/olumsuz sinyal yoksa).

ÖNEMLİK: Sınıflandırmayı bildirimin fiili içeriğine göre yap, \
spekülatif çıkarımlardan kaçın. Belirsiz durumlarda Nötr tercih et.\
"""


async def analyze_sentiment(
    title: str,
    subject: str,
    news_category: str = "",
    disclosure_type: str = "",
    full_text: str = "",
) -> SentimentResult | None:
    """
    Verilen başlık, konu ve tam metni OpenAI API'ye göndererek duygu analizi yapar.
    
    Args:
        title: Bildirimin başlığı
        subject: Bildirimin konusu / özeti
        news_category: Sınıflandırıcının atadığı haber kategorisi (ör: finansal_rapor)
        disclosure_type: MKK bildirim tipi kodu (ör: FR, ODA, CA)
        full_text: htmlMessages'tan decode edilen tam bildirim metni (varsa öncelikli kullanılır)
        
    Returns:
        SentimentResult nesnesi veya API hatası/eksik key durumunda None.
    """
    if not client:
        log.warning("OpenAI API key bulunamadı veya geçersiz. Duygu analizi atlanıyor.")
        return None

    if not title and not subject and not full_text:
        log.warning("Başlık, konu ve tam metin boş, duygu analizi yapılamaz.")
        return None

    parts = [f"Başlık: {title}"]
    if disclosure_type:
        parts.append(f"Bildirim Tipi: {disclosure_type}")
    if news_category:
        parts.append(f"Kategori: {news_category}")

    if full_text:
        # Tam metin varsa subject'e gerek yok, zaten full_text içinde yer alır
        parts.append(f"Bildirim İçeriği:\n{full_text[:6000]}")
    elif subject:
        parts.append(f"Özet: {subject}")

    user_content = "\n".join(parts)

    try:
        response = await client.beta.chat.completions.parse(
            model="gpt-4.1-nano-2025-04-14",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format=SentimentResult,
            temperature=0.0,
        )
        
        result = response.choices[0].message.parsed
        if result:
            log.info(f"Duygu analizi başarılı: {result.sentiment} - {title[:50]}...")
            return result
        return None
        
    except Exception as e:
        log.error(f"OpenAI API çağrısında hata oluştu: {e}")
        return None
