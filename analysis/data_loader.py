"""
analysis/data_loader.py

PostgreSQL'den analiz için veri yükler ve temizler.
Pandas DataFrame olarak döndürür.
"""
from __future__ import annotations

import asyncio
from datetime import timezone
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

import db.repository as repo
from db.connection import close_pool, init_pool

load_dotenv()


def _run_repo(coro):
    """Analiz modülündeki sync API'yi repository'nin async sorgularına bağlar."""
    init_pool()
    try:
        return asyncio.run(coro)
    finally:
        close_pool()


# ─────────────────────────────────────────────
# Temel veri yükleme
# ─────────────────────────────────────────────

def load_disclosures(
    min_price: bool = True,
    require_sentiment: bool = False,
    require_1d: bool = True,
    category: Optional[str] = None,
    stock_code: Optional[str] = None,
) -> pd.DataFrame:
    """
    Analiz için gerekli sütunları çeker ve temizlenmiş DataFrame döndürür.

    Parametreler:
        min_price:        price_at_news NOT NULL zorunlu (default: True)
        require_sentiment: sentiment NOT NULL zorunlu
        require_1d:       price_1d NOT NULL zorunlu
        category:         Belirli bir kategoriyi filtrele (örn: 'Finansal Rapor')
        stock_code:       Belirli bir hisseyi filtrele (örn: 'THYAO')

    Döner:
        pd.DataFrame — temizlenmiş ve return sütunları eklenmiş.
    """
    rows = _run_repo(
        repo.get_analysis_disclosures(
            min_price=min_price,
            require_sentiment=require_sentiment,
            require_1d=require_1d,
            category=category,
            stock_code=stock_code,
        )
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["publish_datetime_utc"] = pd.to_datetime(df["publish_datetime_utc"], utc=True)

    # ── Temizleme ──────────────────────────────────────────────
    df = df.copy()

    # Zaman dilimi: UTC'ye normalize et
    if df["publish_datetime_utc"].dt.tz is None:
        df["publish_datetime_utc"] = df["publish_datetime_utc"].dt.tz_localize("UTC")
    else:
        df["publish_datetime_utc"] = df["publish_datetime_utc"].dt.tz_convert("UTC")

    # Türkiye saatine çevir (analiz için)
    df["publish_datetime_tr"] = df["publish_datetime_utc"].dt.tz_convert("Europe/Istanbul")

    # Borsa saati mi? (BIST: 10:00–18:10 yerel saat, Pazartesi–Cuma)
    df["is_market_hours"] = (
        df["publish_datetime_tr"].dt.weekday.between(0, 4)  # Pzt–Cum
        & df["publish_datetime_tr"].dt.hour.between(10, 18)
    )

    # Haber saati (0–23)
    df["publish_hour"] = df["publish_datetime_tr"].dt.hour
    df["publish_weekday"] = df["publish_datetime_tr"].dt.day_name()

    # Sentiment sayısallaştır
    sentiment_map = {"Olumlu": 1, "Nötr": 0, "Olumsuz": -1}
    df["sentiment_score"] = df["sentiment"].map(sentiment_map)

    # İlk hisse kodunu al (virgüllü olanlar için)
    df["primary_stock"] = df["stock_codes"].str.split(",").str[0].str.strip()

    return df


def get_data_quality_report() -> dict:
    """
    Veritabanındaki analiz veri kalitesini özetler.
    Kaç kayıt analiz için hazır?
    """
    row = _run_repo(repo.get_analysis_data_quality_report())
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}


def load_category_breakdown() -> pd.DataFrame:
    """
    Her kategori için veri sayısını döndürür (dashboard için).
    """
    return pd.DataFrame(_run_repo(repo.get_analysis_category_breakdown()))


def load_top_companies(n: int = 20) -> pd.DataFrame:
    """
    En çok bildirimi olan şirketleri döndürür.
    """
    return pd.DataFrame(_run_repo(repo.get_analysis_top_companies(n)))
