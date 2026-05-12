"""
analysis/report.py

Tüm istatistiksel analizleri tek bir JSON raporda birleştirir.
Hem web dashboard API'si hem de tez için kullanılır.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from analysis.data_loader import load_disclosures, get_data_quality_report, load_category_breakdown
from analysis.returns import compute_returns, flag_outliers, return_summary, time_window_comparison, market_hours_comparison
from analysis.correlation import (
    test_return_vs_zero,
    test_sentiment_effect,
    test_category_effect,
    spearman_correlation_matrix,
    spearman_pvalues,
    run_ols_regression,
    per_company_analysis,
    time_window_comparison as corr_time_window,
)

OUTPUT_DIR = Path("analysis/output")


def _safe_df_to_list(df: pd.DataFrame) -> list:
    """DataFrame'i JSON serileştirilebilir listeye çevirir."""
    if df is None or df.empty:
        return []
    return [
        {k: (None if pd.isna(v) else (bool(v) if isinstance(v, (bool,)) else v))
         for k, v in row.items()}
        for row in df.to_dict("records")
    ]


def build_full_report(
    remove_outliers: bool = False,
    run_excess_return: bool = False,
    run_regression: bool = True,
    min_n_per_company: int = 5,
) -> dict:
    """
    Kapsamlı analiz raporunu oluşturur.

    Döner:
        dict — tüm istatistiksel bulgular, web API'ye hazır JSON
    """
    # ─── 1. Veri Kalitesi ───────────────────────────────────────
    print("[report] Veri kalitesi raporu alınıyor...")
    quality = get_data_quality_report()

    # ─── 2. Veri Yükleme ────────────────────────────────────────
    print("[report] Veriler yükleniyor...")
    df_raw = load_disclosures(require_sentiment=False, require_1d=True)

    if df_raw.empty:
        return {
            "hata": "Analiz için yeterli veri bulunamadı. price_1d ve price_at_news alanları dolu olmalı.",
            "veri_kalitesi": quality,
        }

    # ─── 3. Return Hesaplama ─────────────────────────────────────
    print(f"[report] {len(df_raw)} kayıt bulundu. Return hesaplanıyor...")
    df = compute_returns(df_raw)
    df = flag_outliers(df, col="return_1d", k=3.0)

    df_clean = df[~df["is_outlier"]].copy() if "is_outlier" in df.columns else df.copy()
    outlier_count = df["is_outlier"].sum() if "is_outlier" in df.columns else 0

    # Yalnızca sentiment'i olanlar (bazı testler için)
    df_with_sent = df_clean[df_clean["sentiment"].notna()].copy()

    # ─── 4. İstatistik Özeti ────────────────────────────────────
    print("[report] İstatistiksel testler çalıştırılıyor...")
    summary_df = return_summary(df_clean)
    summary_with_sent = return_summary(df_with_sent, group_col="sentiment") if not df_with_sent.empty else pd.DataFrame()

    # ─── 5. Testler ─────────────────────────────────────────────
    t_test_all = test_return_vs_zero(df_clean, "return_1d")
    t_test_by_cat = test_return_vs_zero(df_clean, "return_1d", group_col="news_category")

    sentiment_effect = test_sentiment_effect(df_with_sent) if not df_with_sent.empty else {}
    category_effect = test_category_effect(df_clean)

    spearman_corr = spearman_correlation_matrix(df_with_sent) if not df_with_sent.empty else pd.DataFrame()
    spearman_p = spearman_pvalues(df_with_sent) if not df_with_sent.empty else pd.DataFrame()

    time_windows = corr_time_window(df_clean)
    market_hours = market_hours_comparison(df_clean)

    # ─── 6. Şirket Bazlı ────────────────────────────────────────
    company_analysis = per_company_analysis(df_clean, min_n=min_n_per_company)

    # ─── 7. Regresyon (opsiyonel) ────────────────────────────────
    regression_result = {}
    if run_regression and not df_with_sent.empty and len(df_with_sent) >= 20:
        print("[report] OLS regresyon çalıştırılıyor...")
        regression_result = run_ols_regression(df_with_sent, "return_1d")
        regression_result.pop("ozet", None)  # Ham ozet metni çıkar (API için gereksiz)

    # ─── 8. Top Movers ──────────────────────────────────────────
    top_movers = (
        df_clean[["disclosure_index", "primary_stock", "company_name",
                  "news_category", "sentiment", "return_1d", "publish_datetime_utc",
                  "subject", "kap_link"]]
        .dropna(subset=["return_1d"])
        .nlargest(20, "return_1d")
    ) if "return_1d" in df_clean.columns else pd.DataFrame()

    bottom_movers = (
        df_clean[["disclosure_index", "primary_stock", "company_name",
                  "news_category", "sentiment", "return_1d", "publish_datetime_utc",
                  "subject", "kap_link"]]
        .dropna(subset=["return_1d"])
        .nsmallest(20, "return_1d")
    ) if "return_1d" in df_clean.columns else pd.DataFrame()

    # ─── 9. Kategori Özeti ──────────────────────────────────────
    cat_breakdown = load_category_breakdown()

    # ─── Rapor birleştirme ───────────────────────────────────────
    report = {
        "meta": {
            "toplam_kayit": len(df_raw),
            "temiz_kayit": len(df_clean),
            "aykirideger_sayisi": int(outlier_count),
            "sentiment_dahil_kayit": len(df_with_sent),
        },
        "veri_kalitesi": quality,
        "genel_ozet": _safe_df_to_list(summary_df.reset_index()),
        "genel_t_testi": _safe_df_to_list(t_test_all),
        "kategori_t_testi": _safe_df_to_list(t_test_by_cat),
        "sentiment_etkisi": sentiment_effect,
        "kategori_etkisi": category_effect,
        "zaman_pencereleri": time_windows,
        "borsa_saati_karsilastirma": market_hours,
        "spearman_korelasyon": (
            spearman_corr.to_dict() if not spearman_corr.empty else {}
        ),
        "spearman_p_degerleri": (
            spearman_p.to_dict() if not spearman_p.empty else {}
        ),
        "sirket_bazli_analiz": _safe_df_to_list(company_analysis),
        "regresyon": regression_result,
        "en_yuksek_getiri_haberler": _safe_df_to_list(top_movers),
        "en_dusuk_getiri_haberler": _safe_df_to_list(bottom_movers),
        "kategori_ozeti": _safe_df_to_list(cat_breakdown),
    }

    return report


def build_quick_summary(df: Optional[pd.DataFrame] = None) -> dict:
    """
    Dashboard kartları için hızlı özet.
    df verilmezse DB'den yükler.
    """
    if df is None:
        df = load_disclosures(require_1d=True)
        if df.empty:
            return {}
        df = compute_returns(df)

    result: dict = {
        "toplam_analiz_edilen": len(df),
        "benzersiz_hisse": df["primary_stock"].nunique() if "primary_stock" in df.columns else 0,
    }

    if "return_1d" in df.columns:
        r = df["return_1d"].dropna()
        result["return_1d_ortalama"] = round(r.mean(), 4)
        result["return_1d_medyan"] = round(r.median(), 4)
        result["return_1d_std"] = round(r.std(), 4)
        result["yukselenler"] = int((r > 0.5).sum())
        result["dusenler"] = int((r < -0.5).sum())
        result["yatay"] = int(r.between(-0.5, 0.5).sum())

    if "sentiment" in df.columns and "return_1d" in df.columns:
        for s in ["Olumlu", "Olumsuz", "Nötr"]:
            sub = df[df["sentiment"] == s]["return_1d"].dropna()
            key = s.replace("ö", "o").replace("ü", "u").lower()
            result[f"{key}_ortalama_return"] = round(sub.mean(), 4) if len(sub) > 0 else None
            result[f"{key}_n"] = len(sub)

    return result


def save_report_json(report: dict, path: str = "analysis/output/full_report.json") -> None:
    """Raporu JSON dosyasına kaydeder."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"[report] Rapor kaydedildi: {path}")


def save_all_charts(df: pd.DataFrame) -> dict:
    """Tüm matplotlib grafiklerini PNG olarak kaydeder ve base64 dict döndürür."""
    from analysis.charts import (
        chart_sentiment_returns,
        chart_category_boxplot,
        chart_time_windows,
        chart_correlation_heatmap,
        chart_violin_sentiment,
        chart_top_companies,
    )
    return {
        "sentiment_bar": chart_sentiment_returns(df, save=True),
        "category_boxplot": chart_category_boxplot(df, save=True),
        "time_windows": chart_time_windows(df, save=True),
        "correlation_heatmap": chart_correlation_heatmap(df, save=True),
        "violin_sentiment": chart_violin_sentiment(df, save=True),
        "top_companies": chart_top_companies(df, save=True),
    }
