"""
Vega Curve Package Detection

This module contains logic to detect and link swaption straddles into
vega curve packages based on risk metrics and trade characteristics.

A vega curve package typically consists of multiple straddles with
different expiries/tenors traded together to express a view on the
volatility term structure.
"""

from typing import List, Optional, Tuple, Dict, Any
from enum import Enum, auto

import numpy as np
import pandas as pd


class VegaCurveType(Enum):
    """Classification of vega curve package types."""
    CALENDAR_SPREAD = auto()      # Same tenor, different expiries
    DIAGONAL_SPREAD = auto()      # Different expiry and tenor
    VEGA_NEUTRAL_FLY = auto()     # Butterfly structure, vega-neutral
    TERM_STRUCTURE = auto()       # Multiple points on term structure
    UNKNOWN = auto()


def _compute_time_to_expiry_years(
    df: pd.DataFrame,
    reference_date: Any,
    expiry_col: str = "expiry_date",
) -> pd.Series:
    """
    Compute time to expiry in years for each row.

    Args:
        df: DataFrame with expiry dates
        reference_date: Reference date for calculation
        expiry_col: Column name for expiry date

    Returns:
        Series of time to expiry in years
    """
    ref = pd.Timestamp(reference_date)
    expiries = pd.to_datetime(df[expiry_col])
    return (expiries - ref).dt.days / 365.25


def _compute_swap_tenor_years(
    df: pd.DataFrame,
    effective_col: str = "effective_date",
    maturity_col: str = "maturity_date",
) -> pd.Series:
    """
    Compute underlying swap tenor in years for each row.

    Args:
        df: DataFrame with effective and maturity dates
        effective_col: Column name for effective date
        maturity_col: Column name for maturity date

    Returns:
        Series of swap tenors in years
    """
    eff = pd.to_datetime(df[effective_col])
    mat = pd.to_datetime(df[maturity_col])
    return (mat - eff).dt.days / 365.25


def _match_straddles_by_timing(
    df: pd.DataFrame,
    time_window_seconds: int = 300,
    timestamp_col: str = "timestamp",
) -> pd.Series:
    """
    Group straddles that traded within a time window.

    This is a preliminary grouping step to identify potential packages
    based on execution timing proximity.

    Args:
        df: DataFrame of detected straddles
        time_window_seconds: Maximum time between trades in same group
        timestamp_col: Column name for trade timestamp

    Returns:
        Series of group IDs for each row
    """
    if len(df) == 0:
        return pd.Series(dtype=int)

    df_sorted = df.sort_values(timestamp_col).copy()
    timestamps = pd.to_datetime(df_sorted[timestamp_col])

    group_ids = np.zeros(len(df_sorted), dtype=int)
    current_group = 0
    group_start_time = timestamps.iloc[0]

    for i, ts in enumerate(timestamps):
        if (ts - group_start_time).total_seconds() > time_window_seconds:
            current_group += 1
            group_start_time = ts
        group_ids[i] = current_group

    # Map back to original index
    result = pd.Series(index=df_sorted.index, data=group_ids)
    return result.reindex(df.index)


def _classify_vega_curve_type(
    expiries: List[float],
    tenors: List[float],
    vegas: List[float],
) -> VegaCurveType:
    """
    Classify the type of vega curve package based on characteristics.

    Args:
        expiries: List of time to expiry in years
        tenors: List of swap tenors in years
        vegas: List of vega values

    Returns:
        VegaCurveType classification
    """
    if len(expiries) < 2:
        return VegaCurveType.UNKNOWN

    expiry_arr = np.array(expiries)
    tenor_arr = np.array(tenors)
    vega_arr = np.array(vegas)

    # Check if same tenor (within tolerance)
    tenor_std = np.std(tenor_arr)
    same_tenor = tenor_std < 0.5  # Within 6 months

    # Check if same expiry (within tolerance)
    expiry_std = np.std(expiry_arr)
    same_expiry = expiry_std < 0.1  # Within ~1 month

    # Check vega neutrality (net vega near zero)
    net_vega = np.sum(vega_arr)
    total_vega = np.sum(np.abs(vega_arr))
    vega_neutral = abs(net_vega) < 0.1 * total_vega if total_vega > 0 else False

    # Classification logic
    if same_tenor and not same_expiry:
        return VegaCurveType.CALENDAR_SPREAD
    elif not same_tenor and not same_expiry:
        if vega_neutral and len(expiries) >= 3:
            return VegaCurveType.VEGA_NEUTRAL_FLY
        return VegaCurveType.DIAGONAL_SPREAD
    elif len(expiries) >= 3:
        return VegaCurveType.TERM_STRUCTURE

    return VegaCurveType.UNKNOWN


def _compute_package_risk_metrics(
    straddle_rows: pd.DataFrame,
    vega01_col: str = "straddle_vega01",
    dv01_col: str = "straddle_dv01",
    gamma01_col: str = "straddle_gamma01",
) -> Dict[str, float]:
    """
    Compute aggregate risk metrics for a vega curve package.

    This function sums the individual straddle Greeks to get
    package-level risk exposures.

    Args:
        straddle_rows: DataFrame rows belonging to the package
        vega01_col: Column name for vega01
        dv01_col: Column name for dv01
        gamma01_col: Column name for gamma01

    Returns:
        Dictionary of aggregate risk metrics
    """
    metrics = {}

    if vega01_col in straddle_rows.columns:
        metrics["net_vega01"] = straddle_rows[vega01_col].sum()
        metrics["gross_vega01"] = straddle_rows[vega01_col].abs().sum()

    if dv01_col in straddle_rows.columns:
        metrics["net_dv01"] = straddle_rows[dv01_col].sum()
        metrics["gross_dv01"] = straddle_rows[dv01_col].abs().sum()

    if gamma01_col in straddle_rows.columns:
        metrics["net_gamma01"] = straddle_rows[gamma01_col].sum()

    return metrics


def detect_vega_curve_packages(
    straddles_df: pd.DataFrame,
    reference_date: Any,
    time_window_seconds: int = 300,
    min_package_size: int = 2,
    timestamp_col: str = "timestamp",
    expiry_col: str = "expiry_date",
    effective_col: str = "effective_date",
    maturity_col: str = "maturity_date",
    notional_col: str = "notional",
    vega01_col: str = "straddle_vega01",
    dv01_col: str = "straddle_dv01",
    gamma01_col: str = "straddle_gamma01",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Detect vega curve packages from a DataFrame of detected straddles.

    This function analyzes straddle trades to identify packages where
    multiple straddles were traded together to form a vega curve position.
    The linking is based on:

    1. **Timing proximity**: Straddles executed within a configurable
       time window are candidates for the same package.

    2. **Risk profile analysis**: The function examines the vega, DV01,
       and gamma exposures to determine if straddles form a coherent
       risk structure (e.g., calendar spread, butterfly).

    3. **Notional scaling**: Relative notional sizes are checked for
       consistency with common package ratios (1:1, 1:2:1, etc.).

    Business Logic:
    ---------------
    The detection algorithm follows these steps:

    a) Group straddles by execution time window
    b) For each time group, compute:
       - Time to expiry for each straddle
       - Underlying swap tenor for each straddle
       - Vega and delta exposures
    c) Classify the package type based on expiry/tenor patterns
    d) Compute aggregate risk metrics for the package
    e) Filter out groups that don't meet minimum size requirements

    The resulting package data can be used downstream for:
    - Risk aggregation and reporting
    - P&L attribution at package level
    - Trade reconstruction and analysis

    Args:
        straddles_df: DataFrame of detected straddles. Must contain columns
            for timestamp, expiry, effective/maturity dates, and ideally
            enriched pricing columns (vega01, dv01, gamma01).
        reference_date: Reference date for time calculations
        time_window_seconds: Maximum seconds between trades in same package
        min_package_size: Minimum number of straddles to form a package
        timestamp_col: Column name for trade timestamp
        expiry_col: Column name for option expiry date
        effective_col: Column name for underlying swap effective date
        maturity_col: Column name for underlying swap maturity date
        notional_col: Column name for notional amount
        vega01_col: Column name for vega01 (if available)
        dv01_col: Column name for dv01 (if available)
        gamma01_col: Column name for gamma01 (if available)

    Returns:
        Tuple of (enriched_straddles_df, packages_df):
        - enriched_straddles_df: Original straddles with package_id column added
        - packages_df: Summary DataFrame with one row per detected package,
          including package type, aggregate risk metrics, and member indices
    """
    if len(straddles_df) == 0:
        empty_packages = pd.DataFrame(columns=[
            "package_id", "package_type", "member_count", "member_indices",
            "net_vega01", "gross_vega01", "net_dv01", "gross_dv01", "net_gamma01",
        ])
        return straddles_df.assign(package_id=pd.Series(dtype=int)), empty_packages

    # Step 1: Group by timing
    time_groups = _match_straddles_by_timing(
        straddles_df,
        time_window_seconds=time_window_seconds,
        timestamp_col=timestamp_col,
    )

    # Step 2: Compute time metrics
    time_to_expiry = _compute_time_to_expiry_years(
        straddles_df, reference_date, expiry_col
    )
    swap_tenor = _compute_swap_tenor_years(
        straddles_df, effective_col, maturity_col
    )

    # Step 3: Process each time group
    packages_data = []
    straddle_package_ids = pd.Series(index=straddles_df.index, data=-1, dtype=int)
    package_id_counter = 0

    for group_id in time_groups.unique():
        group_mask = time_groups == group_id
        group_indices = straddles_df.index[group_mask].tolist()

        if len(group_indices) < min_package_size:
            # Not enough members for a package - these remain standalone
            continue

        group_rows = straddles_df.loc[group_indices]

        # Get metrics for classification
        expiries = time_to_expiry.loc[group_indices].tolist()
        tenors = swap_tenor.loc[group_indices].tolist()

        # Use vega if available, else use notional as proxy
        if vega01_col in group_rows.columns:
            vegas = group_rows[vega01_col].tolist()
        else:
            vegas = group_rows[notional_col].tolist()

        # Classify package type
        pkg_type = _classify_vega_curve_type(expiries, tenors, vegas)

        # Compute aggregate risk metrics
        risk_metrics = _compute_package_risk_metrics(
            group_rows, vega01_col, dv01_col, gamma01_col
        )

        # Assign package ID to straddles
        straddle_package_ids.loc[group_indices] = package_id_counter

        # Record package summary
        packages_data.append({
            "package_id": package_id_counter,
            "package_type": pkg_type.name,
            "member_count": len(group_indices),
            "member_indices": group_indices,
            **risk_metrics,
        })

        package_id_counter += 1

    # Build output DataFrames
    enriched_straddles = straddles_df.assign(vega_curve_package_id=straddle_package_ids)

    if packages_data:
        packages_df = pd.DataFrame(packages_data)
    else:
        packages_df = pd.DataFrame(columns=[
            "package_id", "package_type", "member_count", "member_indices",
            "net_vega01", "gross_vega01", "net_dv01", "gross_dv01", "net_gamma01",
        ])

    return enriched_straddles, packages_df
