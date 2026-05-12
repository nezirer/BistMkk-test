"""
analysis/correlation.py

KAP bildirimleri ile fiyat değişimleri arasındaki korelasyonu
istatistiksel olarak test eder.

Testler:
  1. Tek örnek t-testi       — return ≠ 0 mu?
  2. Mann-Whitney U           — Olumlu vs Olumsuz return farkı
  3. Kruskal-Wallis           — Kategoriler arası return farkı
  4. Spearman korelasyonu     — sentiment_score ↔ return_1d
  5. OLS regresyon            — Çok değişkenli açıklama (tez için)
  6. Şirket bazlı korelasyon  — Her hisse için ayrı test
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd
from scipy import stats


# ─────────────────────────────────────────────
# 1. Tek Örnek t-testi: Return ≠ 0 mu?
# ─────────────────────────────────────────────

def test_return_vs_zero(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    group_col: Optional[str] = None,
) -> pd.DataFrame:
    """
    H0: Ortalama return = 0 (bildirimler fiyatı etkilemiyor)
    Ha: Ortalama return ≠ 0

    Parametreler:
        group_col: Varsa gruplara göre ayrı ayrı test (örn: 'news_category')

    Döner:
        DataFrame — group, n, mean, t_stat, p_value, significant_05, significant_01
    """
    data = df[return_col].dropna()
    results = []

    def _run_test(subset: pd.Series, label: str = "Tümü"):
        subset = subset.dropna()
        if len(subset) < 5:
            return None
        t, p = stats.ttest_1samp(subset, popmean=0)
        # Cohen's d (effect size)
        d = subset.mean() / subset.std() if subset.std() != 0 else 0
        return {
            "grup": label,
            "n": len(subset),
            "ortalama_return": round(subset.mean(), 4),
            "medyan_return": round(subset.median(), 4),
            "std": round(subset.std(), 4),
            "t_istatistigi": round(t, 4),
            "p_degeri": round(p, 6),
            "anlamli_005": p < 0.05,
            "anlamli_001": p < 0.01,
            "cohens_d": round(d, 4),
        }

    if group_col:
        for grp, grp_df in df.groupby(group_col):
            row = _run_test(grp_df[return_col], str(grp))
            if row:
                results.append(row)
    else:
        row = _run_test(data)
        if row:
            results.append(row)

    return pd.DataFrame(results)


# ─────────────────────────────────────────────
# 2. Sentiment Etkisi: Mann-Whitney U
# ─────────────────────────────────────────────

def test_sentiment_effect(
    df: pd.DataFrame,
    return_col: str = "return_1d",
) -> dict:
    """
    Olumlu vs Olumsuz bildirimlerin return dağılımlarını karşılaştırır.
    Non-parametrik Mann-Whitney U testi (finansal veride tercih edilir).

    H0: Olumlu ve Olumsuz grupların return dağılımları aynı.
    """
    required = {"sentiment", return_col}
    if not required.issubset(df.columns):
        return {"hata": "sentiment veya return sütunu eksik"}

    pos = df[df["sentiment"] == "Olumlu"][return_col].dropna()
    neg = df[df["sentiment"] == "Olumsuz"][return_col].dropna()
    neu = df[df["sentiment"] == "Nötr"][return_col].dropna()

    result = {
        "olumlu": {
            "n": len(pos),
            "ortalama": round(pos.mean(), 4) if len(pos) > 0 else None,
            "medyan": round(pos.median(), 4) if len(pos) > 0 else None,
        },
        "olumsuz": {
            "n": len(neg),
            "ortalama": round(neg.mean(), 4) if len(neg) > 0 else None,
            "medyan": round(neg.median(), 4) if len(neg) > 0 else None,
        },
        "notr": {
            "n": len(neu),
            "ortalama": round(neu.mean(), 4) if len(neu) > 0 else None,
            "medyan": round(neu.median(), 4) if len(neu) > 0 else None,
        },
    }

    # Olumlu vs Olumsuz Mann-Whitney
    if len(pos) >= 5 and len(neg) >= 5:
        u, p = stats.mannwhitneyu(pos, neg, alternative="greater")
        # Effect size r = Z / sqrt(N)
        n_total = len(pos) + len(neg)
        z = stats.norm.ppf(1 - p)
        r = z / np.sqrt(n_total)
        result["olumlu_vs_olumsuz"] = {
            "u_istatistigi": round(u, 4),
            "p_degeri": round(p, 6),
            "anlamli_005": p < 0.05,
            "etki_buyuklugu_r": round(r, 4),
            "yorum": (
                "Olumlu haberler istatistiksel olarak anlamlı yüksek getiri sağlıyor."
                if p < 0.05 else
                "Olumlu ve olumsuz haberler arasında anlamlı getiri farkı yok."
            ),
        }
    else:
        result["olumlu_vs_olumsuz"] = {"hata": "Yeterli veri yok (n<5)"}

    # Tüm gruplar: Kruskal-Wallis
    groups_for_kw = [g for g in [pos, neg, neu] if len(g) >= 5]
    if len(groups_for_kw) >= 2:
        h, p_kw = stats.kruskal(*groups_for_kw)
        result["kruskal_wallis"] = {
            "h_istatistigi": round(h, 4),
            "p_degeri": round(p_kw, 6),
            "anlamli_005": p_kw < 0.05,
        }

    return result


# ─────────────────────────────────────────────
# 3. Kategoriler Arası: Kruskal-Wallis
# ─────────────────────────────────────────────

def test_category_effect(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    min_n: int = 10,
) -> dict:
    """
    Farklı bildirim kategorilerinin fiyat etkisini karşılaştırır.
    Kruskal-Wallis + kategori bazlı özet istatistikler.
    """
    if "news_category" not in df.columns:
        return {"hata": "news_category sütunu eksik"}

    cat_stats = []
    groups = []

    for cat, grp in df.groupby("news_category"):
        series = grp[return_col].dropna()
        if len(series) < min_n:
            continue
        groups.append(series)
        t, p = stats.ttest_1samp(series, popmean=0)
        cat_stats.append({
            "kategori": cat,
            "n": len(series),
            "ortalama_return": round(series.mean(), 4),
            "medyan_return": round(series.median(), 4),
            "std": round(series.std(), 4),
            "t_istatistigi": round(t, 4),
            "p_degeri": round(p, 6),
            "anlamli_005": p < 0.05,
        })

    result: dict = {"kategori_bazli": cat_stats}

    if len(groups) >= 2:
        h, p_kw = stats.kruskal(*groups)
        result["kruskal_wallis"] = {
            "h_istatistigi": round(h, 4),
            "p_degeri": round(p_kw, 6),
            "anlamli_005": p_kw < 0.05,
            "yorum": (
                "Kategoriler arasında istatistiksel olarak anlamlı getiri farkı var."
                if p_kw < 0.05 else
                "Kategoriler arasında anlamlı bir getiri farkı bulunamadı."
            ),
        }

    return result


# ─────────────────────────────────────────────
# 4. Spearman Korelasyonu
# ─────────────────────────────────────────────

def spearman_correlation_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """
    sentiment_score ve return sütunları arasındaki Spearman korelasyonunu hesaplar.
    """
    cols = [c for c in [
        "sentiment_score", "return_5m", "return_1h", "return_1d", "return_1w"
    ] if c in df.columns]

    numeric = df[cols].dropna()
    if numeric.empty:
        return pd.DataFrame()

    return numeric.corr(method="spearman").round(4)


def spearman_pvalues(df: pd.DataFrame) -> pd.DataFrame:
    """
    Spearman korelasyon p-değerleri matrisi.
    """
    cols = [c for c in [
        "sentiment_score", "return_5m", "return_1h", "return_1d", "return_1w"
    ] if c in df.columns]

    numeric = df[cols].dropna().values
    n = len(cols)
    p_matrix = np.ones((n, n))

    for i in range(n):
        for j in range(n):
            if i != j:
                _, p = stats.spearmanr(numeric[:, i], numeric[:, j])
                p_matrix[i, j] = p

    return pd.DataFrame(p_matrix, index=cols, columns=cols).round(6)


# ─────────────────────────────────────────────
# 5. OLS Regresyon (Tez için)
# ─────────────────────────────────────────────

def run_ols_regression(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    use_excess: bool = False,
) -> dict:
    """
    OLS regresyon: return_1d ~ sentiment + kategori + borsa_saati + ...

    Bağımlı değişken: return_1d (veya excess_return_1d)
    Bağımsız değişkenler:
        - sentiment (dummy: Olumlu=1, Olumsuz=-1, Nötr=0)
        - news_category (one-hot encoding)
        - is_market_hours (bool)

    Döner:
        dict — summary, coefficients, r_squared, p_values
    """
    try:
        import statsmodels.api as sm
    except ImportError:
        return {"hata": "statsmodels yüklü değil. pip install statsmodels"}

    target_col = "excess_return_1d" if (use_excess and "excess_return_1d" in df.columns) else return_col
    required = [target_col, "sentiment_score"]
    if not all(c in df.columns for c in required):
        return {"hata": f"Gerekli sütunlar eksik: {required}"}

    model_df = df.dropna(subset=[target_col, "sentiment_score"]).copy()

    if len(model_df) < 20:
        return {"hata": f"Yetersiz veri: {len(model_df)} satır (min 20 gerekli)"}

    # Bağımsız değişkenleri oluştur
    X = pd.DataFrame()
    X["sentiment_score"] = model_df["sentiment_score"]

    if "is_market_hours" in model_df.columns:
        X["borsa_saati"] = model_df["is_market_hours"].astype(int)

    if "news_category" in model_df.columns:
        cat_dummies = pd.get_dummies(
            model_df["news_category"], prefix="kat", drop_first=True
        )
        X = pd.concat([X, cat_dummies], axis=1)

    X = sm.add_constant(X)
    y = model_df[target_col]

    try:
        model = sm.OLS(y, X.astype(float)).fit()
    except Exception as e:
        return {"hata": f"Model kurulamadı: {e}"}

    coeffs = []
    for name in model.params.index:
        coeffs.append({
            "degisken": name,
            "katsayi": round(float(model.params[name]), 6),
            "std_hata": round(float(model.bse[name]), 6),
            "t_istatistigi": round(float(model.tvalues[name]), 4),
            "p_degeri": round(float(model.pvalues[name]), 6),
            "anlamli_005": float(model.pvalues[name]) < 0.05,
        })

    return {
        "bagimli_degisken": target_col,
        "n": int(model.nobs),
        "r_kare": round(float(model.rsquared), 6),
        "duzeltilmis_r_kare": round(float(model.rsquared_adj), 6),
        "f_istatistigi": round(float(model.fvalue), 4),
        "f_p_degeri": round(float(model.f_pvalue), 6),
        "model_anlamli": float(model.f_pvalue) < 0.05,
        "katsayilar": coeffs,
        "ozet": str(model.summary()),
    }


# ─────────────────────────────────────────────
# 6. Şirket Bazlı Korelasyon
# ─────────────────────────────────────────────

def per_company_analysis(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    min_n: int = 5,
) -> pd.DataFrame:
    """
    Her şirket için ayrı ayrı: ortalama return, t-testi, Spearman korelasyonu.
    """
    if "primary_stock" not in df.columns:
        return pd.DataFrame()

    rows = []
    for stock, grp in df.groupby("primary_stock"):
        series = grp[return_col].dropna()
        if len(series) < min_n:
            continue

        row: dict = {
            "hisse": stock,
            "sirket_adi": grp["company_name"].iloc[0] if "company_name" in grp.columns else "",
            "bildirim_sayisi": len(series),
            "ortalama_return": round(series.mean(), 4),
            "medyan_return": round(series.median(), 4),
            "std": round(series.std(), 4),
        }

        # t-testi
        if len(series) >= 5:
            t, p = stats.ttest_1samp(series, popmean=0)
            row["t_istatistigi"] = round(t, 4)
            row["p_degeri"] = round(p, 6)
            row["anlamli_005"] = p < 0.05

        # Sentiment korelasyonu (yeterli veri varsa)
        if "sentiment_score" in grp.columns:
            sentiment_series = grp["sentiment_score"].dropna()
            valid = pd.concat([series, sentiment_series], axis=1).dropna()
            if len(valid) >= 5:
                r, p_spear = stats.spearmanr(
                    valid[return_col], valid["sentiment_score"]
                )
                row["spearman_r"] = round(r, 4)
                row["spearman_p"] = round(p_spear, 6)

        rows.append(row)

    result = pd.DataFrame(rows)
    if not result.empty and "ortalama_return" in result.columns:
        result = result.sort_values("ortalama_return", ascending=False)
    return result


# ─────────────────────────────────────────────
# Zaman Dilimi Analizi
# ─────────────────────────────────────────────

def time_window_comparison(df: pd.DataFrame) -> dict:
    """
    Farklı zaman pencerelerindeki (5dk, 1sa, 1gün, 1hafta) ortalama
    getirileri karşılaştırır — 'etki ne zaman en yüksek?' sorusunu cevaplar.
    """
    return_cols = {
        "5 Dakika": "return_5m",
        "1 Saat": "return_1h",
        "1 Gün": "return_1d",
        "1 Hafta": "return_1w",
    }
    result = {}
    for label, col in return_cols.items():
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if len(s) < 3:
            continue
        t, p = stats.ttest_1samp(s, popmean=0)
        result[label] = {
            "n": len(s),
            "ortalama_pct": round(s.mean(), 4),
            "medyan_pct": round(s.median(), 4),
            "std": round(s.std(), 4),
            "t_istatistigi": round(t, 4),
            "p_degeri": round(p, 6),
            "anlamli_005": p < 0.05,
        }
    return result
