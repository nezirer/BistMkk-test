"""
analysis/returns.py

KAP bildirimi sonrası hisse senedi getirilerini (return) hesaplar.

Hesaplanan metrikler:
  - return_5m / return_1h / return_1d / return_1w  → % getiri
  - abs_return_1d                                   → |return_1d| (etki büyüklüğü)
  - direction_1d                                    → Up / Down / Flat
  - is_outlier                                      → IQR ile aykırı değer işaretleme
  - excess_return_1d                                → BIST100'e göre fazla getiri (opsiyonel)
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────
# Getiri hesaplama
# ─────────────────────────────────────────────

def compute_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    price_at_news → price_X sütunlarından yüzde getiri hesaplar.
    df'yi değiştirmez; yeni sütunlar eklenmiş kopyasını döndürür.
    """
    df = df.copy()

    base = df["price_at_news"]
    safe_base = base.replace(0, np.nan)  # Sıfıra bölmeyi önle

    for col, label in [
        ("price_5m", "return_5m"),
        ("price_1h", "return_1h"),
        ("price_1d", "return_1d"),
        ("price_1w", "return_1w"),
    ]:
        if col in df.columns:
            df[label] = (df[col] - base) / safe_base * 100.0

    # Mutlak getiri (etki büyüklüğü için)
    if "return_1d" in df.columns:
        df["abs_return_1d"] = df["return_1d"].abs()

        # Yön etiketi
        df["direction_1d"] = np.where(
            df["return_1d"] > 0.5, "Yükseliş",
            np.where(df["return_1d"] < -0.5, "Düşüş", "Yatay")
        )

    return df


def remove_outliers(df: pd.DataFrame, col: str = "return_1d", k: float = 3.0) -> pd.DataFrame:
    """
    IQR yöntemiyle aykırı değerleri filtreler.
    k: IQR çarpanı (default 3.0 — finansal veride daha geniş bant)
    """
    q1 = df[col].quantile(0.25)
    q3 = df[col].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - k * iqr
    upper = q3 + k * iqr

    mask = df[col].between(lower, upper)
    removed = (~mask).sum()
    if removed > 0:
        print(f"[returns] {removed} aykırı değer çıkarıldı ({col}: [{lower:.2f}%, {upper:.2f}%] dışı)")
    return df[mask].copy()


def flag_outliers(df: pd.DataFrame, col: str = "return_1d", k: float = 3.0) -> pd.DataFrame:
    """
    Aykırı değerleri çıkarmak yerine `is_outlier` sütunuyla işaretler.
    """
    df = df.copy()
    q1 = df[col].quantile(0.25)
    q3 = df[col].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - k * iqr
    upper = q3 + k * iqr
    df["is_outlier"] = ~df[col].between(lower, upper)
    return df


# ─────────────────────────────────────────────
# BIST100 Excess Return (opsiyonel)
# ─────────────────────────────────────────────

def compute_excess_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    BIST100 endeksini (XU100=F) Yahoo Finance'den çekerek piyasa etkisini arındırır.
    Yeni sütun: excess_return_1d = return_1d - bist100_return_1d

    Bu işlem yavaş olabilir (her satır için tarih bazlı fiyat çekimi).
    Kullanım: compute_excess_returns(df) → df
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[returns] yfinance yüklü değil, excess return hesaplanamadı.")
        return df

    df = df.copy()

    # Tüm benzersiz tarihleri topla
    dates = df["publish_datetime_utc"].dt.date.unique()
    print(f"[returns] BIST100 için {len(dates)} farklı tarih çekiliyor...")

    # Her tarih için BIST100 kapanış fiyatlarını indir
    bist = yf.Ticker("XU100=F")
    min_date = pd.Timestamp(min(dates)) - pd.Timedelta(days=5)
    max_date = pd.Timestamp(max(dates)) + pd.Timedelta(days=10)

    try:
        hist = bist.history(start=min_date.date(), end=max_date.date())
    except Exception as e:
        print(f"[returns] BIST100 verisi çekilemedi: {e}")
        return df

    if hist.empty:
        print("[returns] BIST100 verisi boş döndü.")
        return df

    hist.index = hist.index.tz_localize(None)

    def _get_excess_return(row) -> Optional[float]:
        if pd.isna(row.get("return_1d")):
            return None
        pub_date = pd.Timestamp(row["publish_datetime_utc"]).tz_localize(None).normalize()
        future = pub_date + pd.Timedelta(days=1)

        try:
            price_now = hist.loc[hist.index >= pub_date, "Close"].iloc[0]
            price_future = hist.loc[hist.index >= future, "Close"].iloc[0]
            bist_return = (price_future - price_now) / price_now * 100
            return row["return_1d"] - bist_return
        except (IndexError, KeyError):
            return None

    df["excess_return_1d"] = df.apply(_get_excess_return, axis=1)
    non_null = df["excess_return_1d"].notna().sum()
    print(f"[returns] {non_null} kayıt için excess_return_1d hesaplandı.")
    return df


# ─────────────────────────────────────────────
# Özet İstatistikler
# ─────────────────────────────────────────────

def return_summary(df: pd.DataFrame, group_col: Optional[str] = None) -> pd.DataFrame:
    """
    Return sütunları için temel özet istatistik tablosu.

    Parametreler:
        df:        compute_returns() çıktısı
        group_col: Gruplama sütunu (örn: 'news_category', 'sentiment')

    Döner:
        DataFrame — mean, median, std, count, min, max
    """
    return_cols = [c for c in ["return_5m", "return_1h", "return_1d", "return_1w"] if c in df.columns]

    if group_col:
        summary = df.groupby(group_col)[return_cols].agg(
            ["mean", "median", "std", "count", "min", "max"]
        ).round(4)
    else:
        summary = df[return_cols].agg(
            ["mean", "median", "std", "count", "min", "max"]
        ).round(4)

    return summary


def market_hours_comparison(df: pd.DataFrame) -> dict:
    """
    Borsa saatinde vs dışında yayınlanan haberlerin ortalama getirilerini karşılaştırır.
    """
    if "is_market_hours" not in df.columns or "return_1d" not in df.columns:
        return {}

    groups = df.groupby("is_market_hours")["return_1d"].agg(["mean", "median", "std", "count"])
    result = {}
    for idx, row in groups.iterrows():
        key = "borsa_saati" if idx else "borsa_disi"
        result[key] = {
            "ortalama_getiri_pct": round(row["mean"], 4),
            "medyan_getiri_pct": round(row["median"], 4),
            "std": round(row["std"], 4),
            "n": int(row["count"]),
        }
    return result
