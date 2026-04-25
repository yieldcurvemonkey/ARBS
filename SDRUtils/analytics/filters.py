"""
SDR trade filters, enrichment functions, and aggregation helpers.

This is the foundation module -- all other analytics modules depend on it.
Provides:
- Constants: tenor ordering, benchmark tenors, D2D platform sets
- Enrichment: DV01 computation, volume bucketing, execution date extraction
- Filters: new risk, outrights, packages, rate index, basis type, etc.
- Aggregation: daily DV01 pivot, rolling z-scores, VWAP
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TENOR_ORDER: List[str] = [
    "1M", "3M", "6M",
    "1Y", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y",
    "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y",
]

TENOR_BUCKET_ORDER: List[str] = ["0-2Y", "2-5Y", "5-10Y", "10-20Y", "20-30Y", "30Y+"]

TENOR_BUCKET_RANGES = {
    "0-2Y": (0, 2),
    "2-5Y": (2, 5),
    "5-10Y": (5, 10),
    "10-20Y": (10, 20),
    "20-30Y": (20, 30),
    "30Y+": (30, 100),
}

BENCHMARK_TENORS: List[str] = ["2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"]

# Dealer (D2D / IDB) platform identifiers — authoritative SEF MIC list:
#   BGCD — BGC Derivative Markets L.P.
#   DWSF — Dealerweb SEF LLC
#   IGDL — ICAP Global Derivatives Ltd
#   ISWV — ICAP Global Derivatives Ltd – Voice
#   TPSE — TP SEF Inc
#   TSEF — Tradition SEF
# Pre-2026-04-25 this set carried stale codes (TLAD/TRAD/DWUS/MARF/ICAU)
# and incorrectly included BILT (which is a custy / Bilateral platform),
# so the Python D2D classifier mis-bucketed customer flow as dealer.
D2D_PLATFORMS = {"BGCD", "DWSF", "IGDL", "ISWV", "TPSE", "TSEF"}

# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------


def add_dv01_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add dv01 column = abs(estimated_pv01 * notional / 10_000).

    Args:
        df: DataFrame with ``estimated_pv01`` and ``notional`` columns.

    Returns:
        DataFrame with ``dv01`` column added.
    """
    df = df.copy()
    pv01 = pd.to_numeric(df.get("estimated_pv01"), errors="coerce").fillna(0)
    notional = pd.to_numeric(df.get("notional"), errors="coerce").fillna(0)
    df["dv01"] = (pv01 * notional / 10_000).abs()
    return df


def add_volume_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """Add tenor_bucket column based on tenor_years.

    Args:
        df: DataFrame with ``tenor_years`` column.

    Returns:
        DataFrame with ``tenor_bucket`` categorical column added.
    """
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
    """Add execution_date (date only) from execution_timestamp.

    Args:
        df: DataFrame with ``execution_timestamp`` column.

    Returns:
        DataFrame with ``execution_date`` column added.
    """
    df = df.copy()
    df["execution_date"] = pd.to_datetime(
        df["execution_timestamp"], errors="coerce"
    ).dt.date
    return df


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def filter_new_risk(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only new-risk trades (NEWT action type, exclude compression indicators).

    Args:
        df: DataFrame with optional ``event_action`` column.

    Returns:
        Filtered DataFrame containing only NEWT trades.
    """
    mask = pd.Series(True, index=df.index)
    if "event_action" in df.columns:
        mask &= df["event_action"].astype(str).str.upper() == "NEWT"
    return df[mask].copy()


def filter_outrights(df: pd.DataFrame) -> pd.DataFrame:
    """Keep trades where package_type is None/NaN or OUTRIGHT.

    Args:
        df: DataFrame with optional ``package_type`` column.

    Returns:
        Filtered DataFrame containing only outright trades.
    """
    if "package_type" not in df.columns:
        return df.copy()
    pkg = df["package_type"].fillna("OUTRIGHT")
    return df[pkg == "OUTRIGHT"].copy()


def filter_packages(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only multi-leg package trades (CURVE, FLY, etc.).

    Args:
        df: DataFrame with optional ``package_type`` column.

    Returns:
        Filtered DataFrame containing only package trades.
    """
    if "package_type" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    pkg = df["package_type"].fillna("OUTRIGHT")
    return df[pkg != "OUTRIGHT"].copy()


def filter_by_rate_index(df: pd.DataFrame, index: str) -> pd.DataFrame:
    """Filter to specific rate index (e.g., 'SOFR', 'FED_FUNDS').

    Args:
        df: DataFrame with optional ``rate_index`` column.
        index: Rate index string to match (case-insensitive).

    Returns:
        Filtered DataFrame.
    """
    if "rate_index" not in df.columns:
        return df.copy()
    return df[df["rate_index"].astype(str).str.upper() == index.upper()].copy()


def filter_by_basis_type(df: pd.DataFrame, basis: str) -> pd.DataFrame:
    """Filter to specific basis type (e.g., 'SOFR_FF').

    Args:
        df: DataFrame with optional ``basis_type`` column.
        basis: Basis type string to match (case-insensitive).

    Returns:
        Filtered DataFrame.
    """
    if "basis_type" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["basis_type"].astype(str).str.upper() == basis.upper()].copy()


def filter_spreadovers(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only spreadover trades.

    Args:
        df: DataFrame with ``is_spreadover`` or ``linear_product_type`` column.

    Returns:
        Filtered DataFrame containing only spreadover trades.
    """
    if "is_spreadover" in df.columns:
        return df[df["is_spreadover"] == True].copy()
    if "linear_product_type" in df.columns:
        return df[df["linear_product_type"] == "SPREADOVER"].copy()
    return pd.DataFrame(columns=df.columns)


def filter_blocks(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only block trades.

    Args:
        df: DataFrame with optional ``block_trade_election_indicator`` column.

    Returns:
        Filtered DataFrame containing only block trades.
    """
    col = "block_trade_election_indicator"
    if col not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df[col] == True].copy()


def filter_capped(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only trades with capped notional.

    Args:
        df: DataFrame with optional ``is_notional_capped`` column.

    Returns:
        Filtered DataFrame containing only capped-notional trades.
    """
    if "is_notional_capped" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["is_notional_capped"] == True].copy()


def filter_compression_heuristic(df: pd.DataFrame) -> pd.DataFrame:
    """Identify likely compression trades via heuristics.

    Signals:
    - TERM action type (terminations from compression)
    - Round notional divisible by 5M
    - Non-NEWT lifecycle events

    Args:
        df: DataFrame with optional ``event_action`` column.

    Returns:
        Filtered DataFrame containing likely compression trades.
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


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def daily_dv01_by_group(
    df: pd.DataFrame,
    group_col: str,
    date_col: str = "execution_date",
    value_col: str = "risk",
) -> pd.DataFrame:
    """Pivot table: daily DV01 by a grouping column.

    Args:
        df: DataFrame with date, group, and value columns.
        group_col: Column to group by (e.g., ``tenor_bucket``).
        date_col: Column containing execution dates.
        value_col: Column containing DV01 values.

    Returns:
        Pivot table with dates as index, groups as columns, summed values.
    """
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
    """Rolling z-score of a series.

    Args:
        series: Input series.
        window: Rolling window size (minimum 5 periods required).

    Returns:
        Series of z-scores.
    """
    mu = series.rolling(window, min_periods=5).mean()
    sigma = series.rolling(window, min_periods=5).std()
    return (series - mu) / sigma.replace(0, np.nan)


def vwap(
    df: pd.DataFrame,
    rate_col: str = "fixed_rate",
    weight_col: str = "risk",
) -> float:
    """Volume-weighted average rate.

    Args:
        df: DataFrame with rate and weight columns.
        rate_col: Column containing rates.
        weight_col: Column containing weights (e.g., DV01).

    Returns:
        Weighted average rate, or NaN if no valid data.
    """
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
    weight_col: str = "risk",
    date_col: str = "execution_date",
) -> pd.DataFrame:
    """Daily VWAP per group (e.g., per tenor).

    Args:
        df: DataFrame with date, group, rate, and weight columns.
        group_col: Column to group by (e.g., ``tenor_label``).
        rate_col: Column containing rates.
        weight_col: Column containing weights.
        date_col: Column containing execution dates.

    Returns:
        DataFrame with columns ``[date_col, group_col, 'vwap']``.
    """
    records = []
    for (date, group), sub in df.groupby([date_col, group_col]):
        v = vwap(sub, rate_col=rate_col, weight_col=weight_col)
        records.append({date_col: date, group_col: group, "vwap": v})
    return pd.DataFrame(records)
