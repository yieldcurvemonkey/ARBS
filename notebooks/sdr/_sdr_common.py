"""
Shared SDR analytics utilities for notebook suite.

Wraps SDRUtils classification pipeline with notebook-friendly helpers
for data loading, enrichment, filtering, and visualization defaults.
"""

from __future__ import annotations

import datetime
import os
from typing import List, Literal, Optional

import matplotlib.pyplot as plt
import numpy as np
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
# Visualization constants
# ---------------------------------------------------------------------------

TENOR_ORDER = [
    "1M", "3M", "6M",
    "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y",
    "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y",
]

TENOR_BUCKET_ORDER = ["0-2Y", "2-5Y", "5-10Y", "10-20Y", "20-30Y", "30Y+"]

TENOR_BUCKET_RANGES = {
    "0-2Y": (0, 2),
    "2-5Y": (2, 5),
    "5-10Y": (5, 10),
    "10-20Y": (10, 20),
    "20-30Y": (20, 30),
    "30Y+": (30, 100),
}

BENCHMARK_TENORS = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

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
    # Skip columns that contain non-scalar types or timestamps
    skip_patterns = ("timestamp", "date", "time", "tags")
    for col in df.columns:
        if df[col].dtype != object:
            continue
        if any(p in col.lower() for p in skip_patterns):
            continue
        try:
            # Try numeric first
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.notna().sum() > 0.5 * len(df):
                df[col] = numeric
                continue
            # Try category for low-cardinality strings
            n_unique = df[col].nunique()
            if n_unique < 200:
                df[col] = df[col].astype("category")
        except TypeError:
            # Column contains unhashable types (lists, dicts) — skip
            continue
    return df


def _monthly_chunks(start: datetime.datetime, end: datetime.datetime):
    """Yield (chunk_start, chunk_end) monthly windows."""
    current = start
    while current < end:
        next_month = current.replace(day=1) + datetime.timedelta(days=32)
        chunk_end = min(next_month.replace(day=1) - datetime.timedelta(seconds=1), end)
        # Ensure timezone matches
        if start.tzinfo and not chunk_end.tzinfo:
            chunk_end = chunk_end.replace(tzinfo=start.tzinfo)
        yield current, chunk_end
        current = chunk_end + datetime.timedelta(seconds=1)
        if start.tzinfo and not current.tzinfo:
            current = current.replace(tzinfo=start.tzinfo)


_PRECOMPUTED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_precomputed_trades.parquet")


def load_classified_trades(
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

    For ranges >60 days, loads in monthly chunks to avoid MemoryError
    from concat of mismatched-schema DataFrames.

    Returns DataFrame with classification columns including:
        trade_id, execution_timestamp, effective_date, expiration_date,
        product_type, trade_label, notional, is_notional_capped, estimated_pv01,
        tenor_years, tenor_label, is_forward, forward_start_years, forward_label,
        fixed_rate, special_tenor_type, special_tenor_confidence,
        rate_index, linear_product_type, tenor_segment,
        package_type, package_id, package_legs,
        platform_identifier, cleared, block_trade_election_indicator,
        is_spreadover, is_asset_swap
    """
    # Check for pre-computed parquet file first (fast path)
    if os.path.exists(_PRECOMPUTED_PATH):
        print(f"  Using precomputed data from {_PRECOMPUTED_PATH}")
        df = pd.read_parquet(_PRECOMPUTED_PATH, engine="pyarrow")
        # Filter to requested date range
        df["execution_date"] = pd.to_datetime(df["execution_date"]).dt.date
        start_date = start.date() if hasattr(start, "date") else start
        end_date = end.date() if hasattr(end, "date") else end
        df = df[(df["execution_date"] >= start_date) & (df["execution_date"] <= end_date)]
        return df

    product = USD_SwapProduct()

    span_days = (end - start).days
    if span_days <= 60:
        # Short range: load directly
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
        # Long range: load monthly chunks to avoid MemoryError
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
                    # Drop heavy list-typed column that causes object-dtype blowup
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

    # Drop special_tenor_tags if it survived (contains Python lists → object dtype)
    if "special_tenor_tags" in df.columns:
        df = df.drop(columns=["special_tenor_tags"])

    df = add_dv01_columns(df)
    df = add_volume_buckets(df)
    df = add_execution_date(df)
    return df


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------

def add_dv01_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add dv01 column = abs(estimated_pv01 * notional / 10_000)."""
    df = df.copy()
    pv01 = pd.to_numeric(df.get("estimated_pv01"), errors="coerce").fillna(0)
    notional = pd.to_numeric(df.get("notional"), errors="coerce").fillna(0)
    df["dv01"] = (pv01 * notional / 10_000).abs()
    return df


def add_volume_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """Add tenor_bucket column based on tenor_years."""
    df = df.copy()
    tenor = pd.to_numeric(df.get("tenor_years"), errors="coerce").fillna(0)
    conditions = [
        tenor <= 2,
        (tenor > 2) & (tenor <= 5),
        (tenor > 5) & (tenor <= 10),
        (tenor > 10) & (tenor <= 20),
        (tenor > 20) & (tenor <= 30),
        tenor > 30,
    ]
    df["tenor_bucket"] = pd.Categorical(
        np.select(conditions, TENOR_BUCKET_ORDER, default="0-2Y"),
        categories=TENOR_BUCKET_ORDER,
        ordered=True,
    )
    return df


def add_execution_date(df: pd.DataFrame) -> pd.DataFrame:
    """Add execution_date (date only) from execution_timestamp."""
    df = df.copy()
    df["execution_date"] = pd.to_datetime(
        df["execution_timestamp"], errors="coerce"
    ).dt.date
    return df


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def filter_new_risk(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only new-risk trades (NEWT action type, exclude compression indicators)."""
    mask = pd.Series(True, index=df.index)
    if "event_action" in df.columns:
        mask &= df["event_action"].astype(str).str.upper() == "NEWT"
    return df[mask].copy()


def filter_outrights(df: pd.DataFrame) -> pd.DataFrame:
    """Keep trades where package_type is None/NaN or OUTRIGHT."""
    if "package_type" not in df.columns:
        return df.copy()
    pkg = df["package_type"].fillna("OUTRIGHT")
    return df[pkg == "OUTRIGHT"].copy()


def filter_packages(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only multi-leg package trades (CURVE, FLY, etc.)."""
    if "package_type" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    pkg = df["package_type"].fillna("OUTRIGHT")
    return df[pkg != "OUTRIGHT"].copy()


def filter_by_rate_index(df: pd.DataFrame, index: str) -> pd.DataFrame:
    """Filter to specific rate index (e.g., 'SOFR', 'FED_FUNDS')."""
    if "rate_index" not in df.columns:
        return df.copy()
    return df[df["rate_index"].astype(str).str.upper() == index.upper()].copy()


def filter_by_basis_type(df: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Filter to specific basis type (e.g., 'SOFR_FF')."""
    if "basis_type" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["basis_type"].astype(str).str.upper() == basis.upper()].copy()


def filter_spreadovers(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only spreadover trades."""
    if "is_spreadover" in df.columns:
        return df[df["is_spreadover"] == True].copy()
    if "linear_product_type" in df.columns:
        return df[df["linear_product_type"] == "SPREADOVER"].copy()
    return pd.DataFrame(columns=df.columns)


def filter_blocks(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only block trades."""
    col = "block_trade_election_indicator"
    if col not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df[col] == True].copy()


def filter_capped(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only trades with capped notional."""
    if "is_notional_capped" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["is_notional_capped"] == True].copy()


def filter_compression_heuristic(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify likely compression trades via heuristics.

    Signals:
    - TERM action type (terminations from compression)
    - Round notional divisible by 5M
    - Non-NEWT lifecycle events
    """
    masks = []

    if "event_action" in df.columns:
        masks.append(df["event_action"].astype(str).str.upper() == "TERM")

    if masks:
        combined = masks[0]
        for m in masks[1:]:
            combined |= m
        return df[combined].copy()

    return pd.DataFrame(columns=df.columns)


def filter_reset_optimization(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify single-period / FRA-like reset optimization activity.

    These are algorithmic trades (not organic demand) that inflate volume stats.
    Signals: tenor_years < 0.5 (roughly 6 months or less).
    """
    tenor = pd.to_numeric(df.get("tenor_years"), errors="coerce").fillna(999)
    return df[tenor < 0.5].copy()


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def daily_dv01_by_group(
    df: pd.DataFrame,
    group_col: str,
    date_col: str = "execution_date",
    value_col: str = "dv01",
) -> pd.DataFrame:
    """Pivot table: daily DV01 by a grouping column."""
    return df.pivot_table(
        index=date_col,
        columns=group_col,
        values=value_col,
        aggfunc="sum",
        fill_value=0,
    )


def rolling_zscore(
    series: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Rolling z-score of a series."""
    mu = series.rolling(window, min_periods=5).mean()
    sigma = series.rolling(window, min_periods=5).std()
    return (series - mu) / sigma.replace(0, np.nan)


def vwap(
    df: pd.DataFrame,
    rate_col: str = "fixed_rate",
    weight_col: str = "dv01",
) -> float:
    """Volume-weighted average rate."""
    rates = pd.to_numeric(df[rate_col], errors="coerce")
    weights = pd.to_numeric(df[weight_col], errors="coerce")
    valid = rates.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return np.nan
    return np.average(rates[valid], weights=weights[valid])


def daily_vwap(
    df: pd.DataFrame,
    group_col: str = "tenor_label",
    rate_col: str = "fixed_rate",
    weight_col: str = "dv01",
    date_col: str = "execution_date",
) -> pd.DataFrame:
    """Daily VWAP per group (e.g., per tenor)."""
    records = []
    for (date, group), sub in df.groupby([date_col, group_col]):
        v = vwap(sub, rate_col=rate_col, weight_col=weight_col)
        records.append({date_col: date, group_col: group, "vwap": v})
    return pd.DataFrame(records)


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
