"""
KAP Classifier — Finansal Veri Modülü (yfinance entegrasyonu).

Bu modül, yfinance kütüphanesini kullanarak BIST hisse senetlerinin
belirli zaman dilimlerindeki (anlık, 5dk, 1sa vb.) fiyatlarını çeker.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf

from utils.logger import get_logger

log = get_logger(__name__)

# BIST işlem saatleri (TSİ)
# Türkiye saati UTC+3'tür.
BIST_TZ = timezone(timedelta(hours=3))

def _get_bist_ticker(stock_code: str) -> str:
    """Hisse kodunu yfinance formatına (örn: THYAO.IS) çevirir."""
    stock_code = stock_code.strip().upper()
    if not stock_code.endswith(".IS"):
        stock_code = f"{stock_code}.IS"
    return stock_code

async def get_current_price(stock_code: str) -> Optional[float]:
    """
    Belirtilen hisse senedinin anlık (veya en son kapanış) fiyatını çeker.
    """
    if not stock_code:
        return None
        
    ticker_symbol = _get_bist_ticker(stock_code)
    
    loop = asyncio.get_running_loop()
    try:
        # yfinance I/O işlemleri yaptığı için thread pool'da çalıştırıyoruz
        ticker = await loop.run_in_executor(None, yf.Ticker, ticker_symbol)
        
        # fast_info genelde daha hızlıdır
        fast_info = await loop.run_in_executor(None, getattr, ticker, "fast_info")
        
        if "lastPrice" in fast_info:
            return float(fast_info["lastPrice"])
            
        # Fallback: history
        history = await loop.run_in_executor(None, ticker.history, "1d")
        if not history.empty:
            return float(history["Close"].iloc[-1])
            
        return None
    except Exception as e:
        log.error(f"Fiyat çekilirken hata ({ticker_symbol}): {e}")
        return None

async def get_price_at_publish(stock_code: str, publish_utc: datetime) -> Optional[float]:
    """
    Bildirimin yayınlanma tarihindeki (publish_datetime_utc) fiyatı çeker.

    Strateji:
    - Yayınlanma gününün kapanış fiyatını döndürür (en güvenilir yöntem).
    - Eğer yayınlanma günü hafta sonu / tatilse, bir önceki işlem gününün
      kapanış fiyatı döner (yfinance bunu otomatik yapar).
    - Son 7 gün içindeki bildirimler için 5dk intraday veriyle
      en yakın zaman noktası bulunabilir.
    """
    if not stock_code or not publish_utc:
        return None

    ticker_symbol = _get_bist_ticker(stock_code)

    if publish_utc.tzinfo is None:
        publish_utc = publish_utc.replace(tzinfo=timezone.utc)

    publish_istanbul = publish_utc.astimezone(BIST_TZ)

    now = datetime.now(timezone.utc)
    days_diff = (now - publish_utc).days

    loop = asyncio.get_running_loop()
    try:
        ticker = await loop.run_in_executor(None, yf.Ticker, ticker_symbol)

        if days_diff <= 6:
            start_date = (publish_istanbul - timedelta(hours=1)).strftime("%Y-%m-%d")
            end_date = (publish_istanbul + timedelta(days=1)).strftime("%Y-%m-%d")
            history = await loop.run_in_executor(
                None,
                lambda: ticker.history(start=start_date, end=end_date, interval="5m"),
            )
            if not history.empty:
                target_local = publish_utc.astimezone(history.index.tz)
                time_diffs = abs(history.index - target_local)
                closest_idx = time_diffs.argmin()
                return float(history["Close"].iloc[closest_idx])

        start_date = (publish_istanbul - timedelta(days=3)).strftime("%Y-%m-%d")
        end_date = (publish_istanbul + timedelta(days=2)).strftime("%Y-%m-%d")
        history = await loop.run_in_executor(
            None,
            lambda: ticker.history(start=start_date, end=end_date),
        )
        if not history.empty:
            pub_date_str = publish_istanbul.strftime("%Y-%m-%d")
            if pub_date_str in history.index.strftime("%Y-%m-%d"):
                mask = history.index.strftime("%Y-%m-%d") == pub_date_str
                return float(history.loc[mask, "Close"].iloc[0])
            before = history[history.index.date <= publish_istanbul.date()]
            if not before.empty:
                return float(before["Close"].iloc[-1])
            return float(history["Close"].iloc[0])

        return None
    except Exception as e:
        log.error(f"Yayın fiyatı çekilirken hata ({ticker_symbol} - {publish_utc}): {e}")
        return None


async def get_price_at_time(stock_code: str, target_time: datetime) -> Optional[float]:
    """
    Belirtilen hisse senedinin belirli bir zamandaki fiyatını çeker.
    Not: yfinance ücretsiz sürümünde geçmiş intraday (dakikalık) veriler 
    sadece son 7 gün için mevcuttur. Daha eski veriler için günlük kapanış döner.
    """
    if not stock_code or not target_time:
        return None
        
    ticker_symbol = _get_bist_ticker(stock_code)
    
    # target_time'ı UTC'ye çevirip timezone aware yapalım (eğer değilse)
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)
        
    now = datetime.now(timezone.utc)
    days_diff = (now - target_time).days
    
    loop = asyncio.get_running_loop()
    try:
        ticker = await loop.run_in_executor(None, yf.Ticker, ticker_symbol)
        
        # Eğer 7 günden eskiyse sadece günlük veri alabiliriz
        if days_diff > 6:
            start_date = target_time.strftime("%Y-%m-%d")
            end_date = (target_time + timedelta(days=1)).strftime("%Y-%m-%d")
            history = await loop.run_in_executor(None, lambda: ticker.history(start=start_date, end=end_date))
            if not history.empty:
                return float(history["Close"].iloc[0])
            return None
            
        # 7 günden yeniyse 5 dakikalık veri çekip en yakın olanı bulalım
        start_date = (target_time - timedelta(minutes=10)).strftime("%Y-%m-%d")
        end_date = (target_time + timedelta(days=1)).strftime("%Y-%m-%d")
        
        history = await loop.run_in_executor(None, lambda: ticker.history(start=start_date, end=end_date, interval="5m"))
        
        if history.empty:
            return None
            
        # İndeksi timezone aware yapalım (yfinance genelde lokal tz veya America/New_York döner)
        # BIST verileri için genelde Europe/Istanbul döner
        
        # En yakın zamanı bul
        # target_time'ı history index'inin timezone'una çevir
        target_time_local = target_time.astimezone(history.index.tz)
        
        # Zaman farklarını hesapla
        time_diffs = abs(history.index - target_time_local)
        closest_idx = time_diffs.argmin()
        
        return float(history["Close"].iloc[closest_idx])
        
    except Exception as e:
        log.error(f"Geçmiş fiyat çekilirken hata ({ticker_symbol} - {target_time}): {e}")
        return None
