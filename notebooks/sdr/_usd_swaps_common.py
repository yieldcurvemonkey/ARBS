"""
Shared SDR analytics utilities for notebook suite.

Wraps SDRUtils classification pipeline with notebook-friendly helpers
for data loading, enrichment, filtering, and visualization defaults.

Most analytics functions now live in ``SDRUtils.analytics.*`` and are
re-exported here so that notebooks can keep using ``sdr.<name>`` unchanged.
"""

from __future__ import annotations

import datetime
import os
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from SDRUtils.products.usd.usd_swaps import USD_SwapProduct
from SDRUtils.products.usd.linear_base import (
    BasisSwapClassification,
    BasisType,
    LinearProductType,
    RateIndex,
    TenorSegment,
    USDLinearClassification,
)
from SDRUtils.analytics.seasonality import (
    add_event_classifications,
    get_fomc_dates,
    get_imm_dates,
    get_month_end_dates,
    get_quarter_end_dates,
)

# ---------------------------------------------------------------------------
# Re-exports from SDRUtils.analytics
# ---------------------------------------------------------------------------

from SDRUtils.analytics.filters import (  # noqa: F401
    TENOR_ORDER, TENOR_BUCKET_ORDER, TENOR_BUCKET_RANGES, BENCHMARK_TENORS,
    D2D_PLATFORMS,
    add_dv01_columns, add_volume_buckets, add_execution_date,
    filter_new_risk, filter_outrights, filter_packages,
    filter_by_rate_index, filter_by_basis_type, filter_spreadovers,
    filter_blocks, filter_capped, filter_compression_heuristic,
    filter_reset_optimization,
    daily_dv01_by_group, rolling_zscore, vwap, daily_vwap,
)
from SDRUtils.analytics.flow import (  # noqa: F401
    assign_trade_type, bucket_forward_start, classify_venue, infer_ccp,
)
from SDRUtils.analytics.volume import (  # noqa: F401
    detect_volume_spikes, classify_spike_context, seasonality_heatmap_data,
)
from SDRUtils.analytics.fomc import (  # noqa: F401
    get_current_fixing, build_fomc_curves, price_fomc_meetings,
    load_fomc_schedule, classify_rate_index, assign_fomc_meeting,
    compute_calendar_spreads, compute_cut_probabilities,
    FOMCAnalyzer,
)
from SDRUtils.analytics.trade_quality import (  # noqa: F401
    TradeQualityFlag, flag_upfront_payments, flag_off_market_trades,
    flag_outliers,
)
from SDRUtils.analytics.compression import (  # noqa: F401
    detect_compression_signals, clean_volume_decomposition,
    monthly_compression_ratio,
)
from SDRUtils.analytics.liquidity import (  # noqa: F401
    LiquidityScorer, price_dispersion, tick_size_stats, venue_analysis,
)
from SDRUtils.analytics.intraday import (  # noqa: F401
    intraday_cumulative_dv01, hourly_distribution, trade_clustering,
    execution_timing_stats,
)

# ---------------------------------------------------------------------------
# Visualization constants (notebook-specific palettes)
# ---------------------------------------------------------------------------

PACKAGE_COLORS = {
    "OUTRIGHT": "#4C78A8",
    "CURVE": "#F58518",
    "FLY": "#E45756",
    "SPREADOVER": "#72B7B2",
    "MAC": "#54A24B",
    "MATCHED_MATURITY": "#EECA3B",
    "INVOICE_SWAP": "#B279A2",
    "COMPRESSION": "#BFBFBF",
}

RATE_INDEX_COLORS = {
    "SOFR": "#4C78A8",
    "SOFR_COMPOUND": "#4C78A8",
    "FED_FUNDS": "#F58518",
    "FED_FUNDS_COMPOUND": "#F58518",
    "CMS": "#E45756",
    "SIFMA": "#72B7B2",
    "OBFR": "#54A24B",
}

SPECIAL_TENOR_COLORS = {
    "STANDARD": "#4C78A8",
    "IMM": "#F58518",
    "FOMC": "#E45756",
    "MAC": "#54A24B",
    "MATCHED_MATURITY": "#EECA3B",
    "INVOICE_SWAP": "#B279A2",
}

DEFAULT_CACHE_PATH = "C:/sdr_cache"


# ---------------------------------------------------------------------------
# Notebook setup
# ---------------------------------------------------------------------------

def notebook_setup():
    """Standard notebook initialization."""
    try:
        from IPython import get_ipython
        ip = get_ipython()
        if ip is not None:
            ip.run_line_magic("load_ext", "autoreload")
            ip.run_line_magic("autoreload", "2")
            ip.run_line_magic("matplotlib", "inline")
    except Exception:
        pass

    plt.rcParams.update({
        "figure.figsize": (14, 6),
        "figure.dpi": 100,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 9,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.grid": True,
        "grid.alpha": 0.3,
    })
    sns.set_palette("muted")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _coerce_object_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Downcast object columns to reduce memory after concat."""
    skip_patterns = ("timestamp", "date", "time", "tags")
    for col in df.columns:
        if df[col].dtype != object:
            continue
        if any(p in col.lower() for p in skip_patterns):
            continue
        try:
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.notna().sum() > 0.5 * len(df):
                df[col] = numeric
                continue
            n_unique = df[col].nunique()
            if n_unique < 200:
                df[col] = df[col].astype("category")
        except TypeError:
            continue
    return df


def _monthly_chunks(start: datetime.datetime, end: datetime.datetime):
    """Yield (chunk_start, chunk_end) monthly windows."""
    current = start
    while current < end:
        next_month = current.replace(day=1) + datetime.timedelta(days=32)
        chunk_end = min(next_month.replace(day=1) - datetime.timedelta(seconds=1), end)
        if start.tzinfo and not chunk_end.tzinfo:
            chunk_end = chunk_end.replace(tzinfo=start.tzinfo)
        yield current, chunk_end
        current = chunk_end + datetime.timedelta(seconds=1)
        if start.tzinfo and not current.tzinfo:
            current = current.replace(tzinfo=start.tzinfo)


_PRECOMPUTED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_precomputed_trades.parquet")


def load_usd_swaps(
    start: datetime.datetime,
    end: datetime.datetime,
    cache_path: str = DEFAULT_CACHE_PATH,
    curve_source: str = "ERIS_EOD_LIVE-RL_BASIC",
    detect_packages: bool = True,
) -> pd.DataFrame:
    """
    Load and classify SDR trades for a date range.

    If a pre-computed parquet file exists covering the requested range,
    reads from disk (fast). Otherwise, wraps
    USD_SwapProduct.build_classification_dataframe() with chunked loading.
    """
    # Check for pre-computed parquet file first (fast path)
    if os.path.exists(_PRECOMPUTED_PATH):
        print(f"  Using precomputed data from {_PRECOMPUTED_PATH}")
        df = pd.read_parquet(_PRECOMPUTED_PATH, engine="pyarrow")
        df["execution_date"] = pd.to_datetime(df["execution_date"]).dt.date
        start_date = start.date() if hasattr(start, "date") else start
        end_date = end.date() if hasattr(end, "date") else end
        df = df[(df["execution_date"] >= start_date) & (df["execution_date"] <= end_date)]
        return df

    product = USD_SwapProduct()

    span_days = (end - start).days
    if span_days <= 60:
        df = product.build_classification_dataframe(
            start=start,
            end=end,
            cache_path=cache_path,
            detect_curve=detect_packages,
            detect_fly=detect_packages,
            detect_mms=detect_packages,
            detect_invoice=detect_packages,
            detect_mac=detect_packages,
            detect_spreadover=detect_packages,
            curve_source=curve_source,
        )
    else:
        chunks = []
        for chunk_start, chunk_end in _monthly_chunks(start, end):
            print(f"  Loading {chunk_start.date()} to {chunk_end.date()}...")
            try:
                chunk = product.build_classification_dataframe(
                    start=chunk_start,
                    end=chunk_end,
                    cache_path=cache_path,
                    detect_curve=detect_packages,
                    detect_fly=detect_packages,
                    detect_mms=detect_packages,
                    detect_invoice=detect_packages,
                    detect_mac=detect_packages,
                    detect_spreadover=detect_packages,
                    curve_source=curve_source,
                )
                if not chunk.empty:
                    if "special_tenor_tags" in chunk.columns:
                        chunk = chunk.drop(columns=["special_tenor_tags"])
                    chunk = _coerce_object_columns(chunk)
                    chunks.append(chunk)
            except Exception as e:
                print(f"  WARNING: Failed to load {chunk_start.date()}-{chunk_end.date()}: {e}")
        if not chunks:
            return pd.DataFrame()
        df = pd.concat(chunks, ignore_index=True)

    if df.empty:
        return df

    if "special_tenor_tags" in df.columns:
        df = df.drop(columns=["special_tenor_tags"])

    df = add_dv01_columns(df)
    df = add_volume_buckets(df)
    df = add_execution_date(df)
    return df


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def plot_stacked_area(
    pivot_df: pd.DataFrame,
    title: str,
    ylabel: str = "DV01 ($)",
    color_map: Optional[dict] = None,
    figsize: tuple = (14, 6),
):
    """Stacked area chart from a pivot table."""
    fig, ax = plt.subplots(figsize=figsize)
    if pivot_df.empty or len(pivot_df) == 0 or pivot_df.select_dtypes(include="number").shape[1] == 0:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title)
        return fig, ax
    cols = pivot_df.columns.tolist()
    colors = [color_map.get(c, None) if color_map else None for c in cols]
    colors = [c for c in colors if c is not None] or None
    pivot_df.plot.area(ax=ax, stacked=True, alpha=0.8, color=colors)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", framealpha=0.9)
    plt.tight_layout()
    return fig, ax


def plot_stacked_bar(
    pivot_df: pd.DataFrame,
    title: str,
    ylabel: str = "DV01 ($)",
    color_map: Optional[dict] = None,
    figsize: tuple = (14, 6),
):
    """Stacked bar chart from a pivot table."""
    fig, ax = plt.subplots(figsize=figsize)
    if pivot_df.empty or len(pivot_df) == 0 or pivot_df.select_dtypes(include="number").shape[1] == 0:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title)
        return fig, ax
    cols = pivot_df.columns.tolist()
    colors = [color_map.get(c, None) if color_map else None for c in cols]
    colors = [c for c in colors if c is not None] or None
    pivot_df.plot.bar(ax=ax, stacked=True, alpha=0.8, color=colors, width=0.8)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.legend(loc="upper left", framealpha=0.9)
    plt.tight_layout()
    return fig, ax


def plot_heatmap(
    pivot_df: pd.DataFrame,
    title: str,
    cmap: str = "RdYlGn_r",
    fmt: str = ".1f",
    figsize: tuple = (14, 8),
):
    """Heatmap from a pivot table."""
    fig, ax = plt.subplots(figsize=figsize)
    if pivot_df.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title)
        return fig, ax
    sns.heatmap(pivot_df, annot=True, fmt=fmt, cmap=cmap, ax=ax, linewidths=0.5)
    ax.set_title(title)
    plt.tight_layout()
    return fig, ax


def format_dv01(val: float) -> str:
    """Format DV01 value for display (e.g., $1.2M, $450K)."""
    if abs(val) >= 1e6:
        return f"${val / 1e6:.1f}M"
    if abs(val) >= 1e3:
        return f"${val / 1e3:.0f}K"
    return f"${val:.0f}"
