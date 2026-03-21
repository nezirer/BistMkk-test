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
