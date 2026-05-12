"""
analysis/charts.py

Görselleştirme modülü.

İki çıktı modu:
  1. Matplotlib → PNG dosyaları (tez/rapor için)
  2. Chart.js uyumlu JSON → web dashboard için
"""
from __future__ import annotations

import io
import os
import base64
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Headless (GUI gerektirmez)
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

# Türkçe karakter desteği için font
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False
sns.set_theme(style="whitegrid", palette="muted")

OUTPUT_DIR = Path("analysis/output")


def _ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _fig_to_base64(fig) -> str:
    """Matplotlib figure'ü base64 PNG string'e çevirir (web embed için)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return encoded


# ─────────────────────────────────────────────
# 1. Sentiment Bazlı Getiri (Bar Chart)
# ─────────────────────────────────────────────

def chart_sentiment_returns(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    save: bool = True,
) -> str:
    """
    Olumlu / Nötr / Olumsuz grupların ortalama ve medyan getirisini gösterir.
    Döner: base64 PNG string
    """
    if "sentiment" not in df.columns or return_col not in df.columns:
        return ""

    order = ["Olumlu", "Nötr", "Olumsuz"]
    colors = {"Olumlu": "#22c55e", "Nötr": "#94a3b8", "Olumsuz": "#ef4444"}

    grouped = df.groupby("sentiment")[return_col].agg(["mean", "median", "count"]).reindex(order)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Sentiment Bazlı Hisse Getirisi (%)", fontsize=14, fontweight="bold")

    for ax, stat, title in [
        (axes[0], "mean", "Ortalama Getiri (%)"),
        (axes[1], "median", "Medyan Getiri (%)"),
    ]:
        vals = grouped[stat]
        bar_colors = [colors.get(cat, "#94a3b8") for cat in order]
        bars = ax.bar(order, vals, color=bar_colors, edgecolor="white", linewidth=1.5)
        ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.set_title(title, fontsize=12)
        ax.set_ylabel("Getiri (%)")
        ax.set_xlabel("")

        # N değerleri
        for bar, cat in zip(bars, order):
            n = int(grouped.loc[cat, "count"]) if cat in grouped.index else 0
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01 * max(abs(vals.max()), abs(vals.min()), 0.1),
                f"n={n}", ha="center", va="bottom", fontsize=9, color="#374151"
            )

    plt.tight_layout()

    if save:
        _ensure_output_dir()
        fig.savefig(OUTPUT_DIR / "sentiment_returns.png", dpi=150, bbox_inches="tight")

    return _fig_to_base64(fig)


# ─────────────────────────────────────────────
# 2. Kategori Bazlı Getiri (Box Plot)
# ─────────────────────────────────────────────

def chart_category_boxplot(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    max_pct: float = 15.0,
    save: bool = True,
) -> str:
    """
    Her bildirim kategorisi için return dağılımını box plot ile gösterir.
    """
    if "news_category" not in df.columns or return_col not in df.columns:
        return ""

    plot_df = df[df[return_col].abs() <= max_pct].copy()

    # Kategori sıralaması (medyana göre)
    order = (
        plot_df.groupby("news_category")[return_col]
        .median()
        .sort_values(ascending=False)
        .index.tolist()
    )

    fig, ax = plt.subplots(figsize=(13, 6))

    palette = sns.color_palette("Set2", len(order))
    sns.boxplot(
        data=plot_df,
        x="news_category",
        y=return_col,
        order=order,
        palette=palette,
        width=0.6,
        fliersize=3,
        linewidth=1.2,
        ax=ax,
    )

    ax.axhline(0, color="black", linewidth=1, linestyle="--", alpha=0.6)
    ax.set_title("Kategori Bazlı Hisse Getirisi Dağılımı (%)", fontsize=14, fontweight="bold")
    ax.set_xlabel("")
    ax.set_ylabel("Getiri (%)")
    ax.tick_params(axis="x", rotation=30)

    # N değerleri
    for i, cat in enumerate(order):
        n = plot_df[plot_df["news_category"] == cat][return_col].notna().sum()
        ax.text(i, ax.get_ylim()[0] * 0.92, f"n={n}", ha="center", fontsize=8, color="#6b7280")

    plt.tight_layout()

    if save:
        _ensure_output_dir()
        fig.savefig(OUTPUT_DIR / "category_boxplot.png", dpi=150, bbox_inches="tight")

    return _fig_to_base64(fig)


# ─────────────────────────────────────────────
# 3. Zaman Penceresi Karşılaştırması
# ─────────────────────────────────────────────

def chart_time_windows(
    df: pd.DataFrame,
    by_sentiment: bool = True,
    save: bool = True,
) -> str:
    """
    5dk / 1sa / 1gün / 1hafta zaman pencerelerinde ortalama getirileri gösterir.
    by_sentiment=True: sentiment grubuna göre renklendirme.
    """
    windows = {
        "5 Dakika": "return_5m",
        "1 Saat": "return_1h",
        "1 Gün": "return_1d",
        "1 Hafta": "return_1w",
    }
    available = {k: v for k, v in windows.items() if v in df.columns}
    if not available:
        return ""

    fig, ax = plt.subplots(figsize=(11, 5))

    if by_sentiment and "sentiment" in df.columns:
        colors_map = {"Olumlu": "#22c55e", "Nötr": "#94a3b8", "Olumsuz": "#ef4444"}
        sentiments = ["Olumlu", "Nötr", "Olumsuz"]
        x = np.arange(len(available))
        width = 0.25

        for i, sent in enumerate(sentiments):
            sub = df[df["sentiment"] == sent]
            means = [sub[col].mean() for col in available.values()]
            bars = ax.bar(
                x + (i - 1) * width, means,
                width=width, label=sent,
                color=colors_map[sent], alpha=0.85, edgecolor="white"
            )

        ax.set_xticks(x)
        ax.set_xticklabels(available.keys())
        ax.legend(title="Sentiment")
    else:
        means = [df[col].mean() for col in available.values()]
        ax.bar(available.keys(), means, color="#6366f1", alpha=0.85, edgecolor="white")

    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_title("Zaman Penceresi Bazlı Ortalama Hisse Getirisi (%)", fontsize=14, fontweight="bold")
    ax.set_ylabel("Ortalama Getiri (%)")
    plt.tight_layout()

    if save:
        _ensure_output_dir()
        fig.savefig(OUTPUT_DIR / "time_windows.png", dpi=150, bbox_inches="tight")

    return _fig_to_base64(fig)


# ─────────────────────────────────────────────
# 4. Korelasyon Heatmap
# ─────────────────────────────────────────────

def chart_correlation_heatmap(df: pd.DataFrame, save: bool = True) -> str:
    """
    sentiment_score ve return sütunları arasındaki Spearman korelasyon matrisi.
    """
    cols = [c for c in ["sentiment_score", "return_5m", "return_1h", "return_1d", "return_1w"]
            if c in df.columns]
    if len(cols) < 2:
        return ""

    corr = df[cols].corr(method="spearman")
    labels = {
        "sentiment_score": "Sentiment\nSkoru",
        "return_5m": "5 Dakika\nGetiri",
        "return_1h": "1 Saat\nGetiri",
        "return_1d": "1 Gün\nGetiri",
        "return_1w": "1 Hafta\nGetiri",
    }
    corr.index = [labels.get(c, c) for c in corr.index]
    corr.columns = [labels.get(c, c) for c in corr.columns]

    fig, ax = plt.subplots(figsize=(8, 6))
    mask = np.triu(np.ones_like(corr, dtype=bool))
    sns.heatmap(
        corr, mask=mask, annot=True, fmt=".3f",
        cmap="RdYlGn", center=0, vmin=-1, vmax=1,
        linewidths=0.5, ax=ax, square=True,
        cbar_kws={"label": "Spearman r"},
    )
    ax.set_title("Spearman Korelasyon Matrisi", fontsize=13, fontweight="bold")
    plt.tight_layout()

    if save:
        _ensure_output_dir()
        fig.savefig(OUTPUT_DIR / "correlation_heatmap.png", dpi=150, bbox_inches="tight")

    return _fig_to_base64(fig)


# ─────────────────────────────────────────────
# 5. Violin Plot: Sentiment Dağılımı
# ─────────────────────────────────────────────

def chart_violin_sentiment(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    max_pct: float = 15.0,
    save: bool = True,
) -> str:
    """Sentiment gruplarının return dağılımını violin plot ile gösterir."""
    if "sentiment" not in df.columns or return_col not in df.columns:
        return ""

    plot_df = df[df[return_col].abs() <= max_pct].copy()
    order = ["Olumlu", "Nötr", "Olumsuz"]

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#22c55e", "#94a3b8", "#ef4444"]
    sns.violinplot(
        data=plot_df, x="sentiment", y=return_col,
        order=order, palette=colors, inner="quartile",
        linewidth=1.2, ax=ax,
    )
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.6)
    ax.set_title("Sentiment Bazlı Getiri Dağılımı (Violin Plot)", fontsize=13, fontweight="bold")
    ax.set_xlabel("")
    ax.set_ylabel(f"{return_col.replace('_', ' ').title()} (%)")
    plt.tight_layout()

    if save:
        _ensure_output_dir()
        fig.savefig(OUTPUT_DIR / "violin_sentiment.png", dpi=150, bbox_inches="tight")

    return _fig_to_base64(fig)


# ─────────────────────────────────────────────
# 6. Şirket Bazlı En Büyük Getiri (Top N)
# ─────────────────────────────────────────────

def chart_top_companies(
    df: pd.DataFrame,
    return_col: str = "return_1d",
    top_n: int = 15,
    save: bool = True,
) -> str:
    """Ortalama getirisi en yüksek/düşük şirketleri yatay bar chart ile gösterir."""
    if "primary_stock" not in df.columns or return_col not in df.columns:
        return ""

    company_returns = (
        df.groupby("primary_stock")[return_col]
        .agg(["mean", "count"])
        .query("count >= 3")
        .sort_values("mean", ascending=False)
    )

    top = pd.concat([company_returns.head(top_n // 2), company_returns.tail(top_n // 2)])
    colors = ["#22c55e" if v >= 0 else "#ef4444" for v in top["mean"]]

    fig, ax = plt.subplots(figsize=(10, max(5, len(top) * 0.4)))
    bars = ax.barh(top.index, top["mean"], color=colors, edgecolor="white", linewidth=1)
    ax.axvline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.set_title(f"Şirket Bazlı Ortalama {return_col.replace('_',' ').title()} (%)", fontsize=13, fontweight="bold")
    ax.set_xlabel("Ortalama Getiri (%)")
    plt.tight_layout()

    if save:
        _ensure_output_dir()
        fig.savefig(OUTPUT_DIR / "top_companies.png", dpi=150, bbox_inches="tight")

    return _fig_to_base64(fig)


# ─────────────────────────────────────────────
# Chart.js JSON Çıktıları (Web Dashboard)
# ─────────────────────────────────────────────

def chartjs_sentiment_bar(df: pd.DataFrame, return_col: str = "return_1d") -> dict:
    """Chart.js bar chart için sentiment bazlı getiri JSON'u."""
    if "sentiment" not in df.columns or return_col not in df.columns:
        return {}

    order = ["Olumlu", "Nötr", "Olumsuz"]
    grouped = df.groupby("sentiment")[return_col].agg(["mean", "median", "count"])

    return {
        "labels": order,
        "datasets": [
            {
                "label": "Ortalama Getiri (%)",
                "data": [round(grouped.loc[s, "mean"], 4) if s in grouped.index else 0 for s in order],
                "backgroundColor": ["rgba(34,197,94,0.7)", "rgba(148,163,184,0.7)", "rgba(239,68,68,0.7)"],
                "borderColor": ["#16a34a", "#64748b", "#dc2626"],
                "borderWidth": 2,
            },
            {
                "label": "Medyan Getiri (%)",
                "data": [round(grouped.loc[s, "median"], 4) if s in grouped.index else 0 for s in order],
                "backgroundColor": ["rgba(34,197,94,0.3)", "rgba(148,163,184,0.3)", "rgba(239,68,68,0.3)"],
                "borderColor": ["#16a34a", "#64748b", "#dc2626"],
                "borderWidth": 2,
            },
        ],
    }


def chartjs_category_bar(df: pd.DataFrame, return_col: str = "return_1d") -> dict:
    """Chart.js bar chart için kategori bazlı ortalama getiri JSON'u."""
    if "news_category" not in df.columns or return_col not in df.columns:
        return {}

    grouped = df.groupby("news_category")[return_col].agg(["mean", "count"]).sort_values("mean", ascending=False)
    labels = grouped.index.tolist()
    means = [round(v, 4) for v in grouped["mean"]]
    colors = ["rgba(34,197,94,0.7)" if v >= 0 else "rgba(239,68,68,0.7)" for v in means]

    return {
        "labels": labels,
        "datasets": [{
            "label": "Ortalama 1G Getiri (%)",
            "data": means,
            "backgroundColor": colors,
            "borderWidth": 1,
        }],
    }


def chartjs_time_windows(df: pd.DataFrame) -> dict:
    """Chart.js için zaman penceresi bazlı ortalama getiriler."""
    windows = {
        "5 Dakika": "return_5m",
        "1 Saat": "return_1h",
        "1 Gün": "return_1d",
        "1 Hafta": "return_1w",
    }
    labels = []
    all_means = []
    pos_means = []
    neg_means = []

    for label, col in windows.items():
        if col not in df.columns:
            continue
        labels.append(label)
        all_means.append(round(df[col].mean(), 4))
        if "sentiment" in df.columns:
            pos_means.append(round(df[df["sentiment"] == "Olumlu"][col].mean(), 4))
            neg_means.append(round(df[df["sentiment"] == "Olumsuz"][col].mean(), 4))

    datasets = [{
        "label": "Tümü",
        "data": all_means,
        "backgroundColor": "rgba(99,102,241,0.7)",
        "borderColor": "#4f46e5",
        "borderWidth": 2,
    }]

    if pos_means:
        datasets.append({
            "label": "Olumlu",
            "data": pos_means,
            "backgroundColor": "rgba(34,197,94,0.5)",
            "borderColor": "#16a34a",
            "borderWidth": 2,
        })
        datasets.append({
            "label": "Olumsuz",
            "data": neg_means,
            "backgroundColor": "rgba(239,68,68,0.5)",
            "borderColor": "#dc2626",
            "borderWidth": 2,
        })

    return {"labels": labels, "datasets": datasets}
