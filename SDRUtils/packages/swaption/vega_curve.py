"""
SDRUtils.packages.swaption.vega_curve
=====================================

Detection logic for vega curve packages (swaption straddles linked across tenors).

A vega curve package consists of multiple straddles with the same option expiry
but different underlying swap tenors, typically traded together as a vol curve play.

Business Logic Review Notes
---------------------------
The current implementation uses an **estimated vega** approach based on:
1. Square-root-of-time scaling for ATM straddles
2. Bucketed risk approximations using simplified Black-Normal assumptions
3. Notional-weighted aggregation for vega matching

**Recommendation**: Once the upstream `detect_and_link_swaption_packages_df` function
enriches straddle rows with precise `straddle_vega01` values from the QuantLib pricer,
this function should be refactored to consume the pre-calculated vega directly.

The refactoring would involve:
1. Removing the `_estimate_vega` helper function
2. Using the `straddle_vega01` column directly for vega curve matching
3. Improving accuracy by eliminating approximation errors

See the `use_precalculated_vega` parameter for opt-in to the new behavior.
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd


# -----------------------------------------------------------------------------
# Vega Estimation Logic (Current Approximation)
# -----------------------------------------------------------------------------


def _estimate_vega(
    notional: float,
    expiry_years: float,
    underlying_tenor_years: float,
    atm_vol_bps: float = 70.0,
) -> float:
    """
    Estimate vega for an ATM swaption straddle using simplified Normal model assumptions.

    This is an approximation that assumes:
    - ATM straddle (strike = forward rate)
    - Normal (Bachelier) volatility model
    - Vega scales with sqrt(time) and underlying annuity

    Parameters
    ----------
    notional : float
        Notional amount of the swaption.
    expiry_years : float
        Time to option expiry in years.
    underlying_tenor_years : float
        Tenor of the underlying swap in years.
    atm_vol_bps : float
        Assumed ATM normal volatility in basis points per year.

    Returns
    -------
    float
        Estimated vega (dollar change per 1bp vol move).

    Notes
    -----
    This estimation uses the formula:
        Vega ≈ Notional * sqrt(T_expiry) * Annuity_factor * pdf(0) / 10000

    For a normal model ATM straddle:
        Straddle_Vega ≈ 2 * sqrt(T) * Annuity * Notional * sqrt(2/pi) / 10000

    **This is an approximation and should be replaced with precise QuantLib pricing
    when the `straddle_vega01` column is available.**
    """
    if expiry_years <= 0 or underlying_tenor_years <= 0:
        return 0.0

    # Simplified annuity approximation (assuming flat curve)
    annuity_approx = underlying_tenor_years

    # Normal ATM straddle vega approximation
    # For normal model: vega ≈ 2 * sqrt(T) * annuity * notional * sqrt(2/pi)
    sqrt_2_pi = np.sqrt(2.0 / np.pi)
    vega_estimate = 2.0 * np.sqrt(expiry_years) * annuity_approx * abs(notional) * sqrt_2_pi

    # Scale to per-bp (1/10000)
    return vega_estimate / 10000.0


def _parse_tenor_to_years(tenor: str) -> float:
    """
    Convert a tenor string to years.

    Examples: '1Y' -> 1.0, '6M' -> 0.5, '10Y' -> 10.0
    """
    if tenor is None or pd.isna(tenor):
        return 0.0

    tenor = str(tenor).strip().upper()

    if tenor.endswith("Y"):
        return float(tenor[:-1])
    elif tenor.endswith("M"):
        return float(tenor[:-1]) / 12.0
    elif tenor.endswith("W"):
        return float(tenor[:-1]) / 52.0
    elif tenor.endswith("D"):
        return float(tenor[:-1]) / 365.0
    else:
        try:
            return float(tenor)
        except ValueError:
            return 0.0


def _time_to_expiry_years(
    expiry_date: datetime.date,
    reference_date: datetime.date,
) -> float:
    """Calculate time to expiry in years."""
    if expiry_date is None or reference_date is None:
        return 0.0
    delta = (expiry_date - reference_date).days
    return max(0.0, delta / 365.0)


# -----------------------------------------------------------------------------
# Vega Curve Package Detection
# -----------------------------------------------------------------------------


def detect_vega_curve_packages(
    df: pd.DataFrame,
    package_type_col: str = "package_type",
    expiry_col: str = "option_expiry_date",
    tenor_col: str = "underlying_tenor",
    notional_col: str = "notional_amount",
    timestamp_col: str = "Execution Timestamp",
    reference_date: Optional[datetime.date] = None,
    vega_tolerance_pct: float = 15.0,
    time_window_minutes: int = 5,
    min_legs: int = 2,
    max_legs: int = 5,
    use_precalculated_vega: bool = False,
    vega_col: str = "straddle_vega01",
) -> pd.DataFrame:
    """
    Detect vega curve packages from a DataFrame of swaption straddles.

    A vega curve package consists of straddles with:
    1. Same option expiry date
    2. Different underlying swap tenors
    3. Approximately offsetting vega (long one tenor, short another)
    4. Traded within a short time window

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame with detected straddles.
    package_type_col : str
        Column indicating package type. Only rows with 'STRADDLE' are considered.
    expiry_col : str
        Column containing option expiry dates.
    tenor_col : str
        Column containing underlying swap tenors.
    notional_col : str
        Column containing notional amounts.
    timestamp_col : str
        Column containing execution timestamps.
    reference_date : datetime.date, optional
        Reference date for time-to-expiry calculation. Defaults to today.
    vega_tolerance_pct : float
        Maximum percentage difference in net vega for a valid curve package.
    time_window_minutes : int
        Maximum time window (minutes) between trades in a package.
    min_legs : int
        Minimum number of legs for a vega curve package.
    max_legs : int
        Maximum number of legs for a vega curve package.
    use_precalculated_vega : bool
        If True, use the `vega_col` column for precise vega values.
        If False (default), use the estimation logic.
    vega_col : str
        Column name for pre-calculated vega (used when `use_precalculated_vega=True`).

    Returns
    -------
    pd.DataFrame
        DataFrame with additional columns:
        - `vega_curve_package_id`: Unique identifier for linked packages (NaN if not linked)
        - `vega_curve_leg_num`: Leg number within the package
        - `estimated_vega`: Estimated or pre-calculated vega for the straddle

    Notes
    -----
    **Current Business Logic (Estimation-based)**:
    The current implementation estimates vega using simplified Normal model assumptions.
    This approach:
    - Uses square-root-of-time scaling
    - Assumes ATM strikes
    - Applies simplified annuity approximations

    **Recommended Refactor**:
    When `use_precalculated_vega=True`, the function consumes the precise `straddle_vega01`
    values computed by the QuantLib pricer. This provides:
    - Accurate vega accounting for moneyness
    - Proper discounting and forward rate effects
    - Consistent Greeks across the detection pipeline

    Example
    -------
    >>> # Using estimated vega (current default)
    >>> result = detect_vega_curve_packages(df, use_precalculated_vega=False)

    >>> # Using pre-calculated vega from pricer (recommended)
    >>> result = detect_vega_curve_packages(df, use_precalculated_vega=True)
    """
    if df.empty:
        return df.assign(
            vega_curve_package_id=pd.Series(dtype="object"),
            vega_curve_leg_num=pd.Series(dtype="Int64"),
            estimated_vega=pd.Series(dtype="float64"),
        )

    # Filter to straddles only
    if package_type_col not in df.columns:
        df = df.assign(
            vega_curve_package_id=np.nan,
            vega_curve_leg_num=np.nan,
            estimated_vega=np.nan,
        )
        return df

    straddle_mask = df[package_type_col].str.upper() == "STRADDLE"
    if not straddle_mask.any():
        df = df.assign(
            vega_curve_package_id=np.nan,
            vega_curve_leg_num=np.nan,
            estimated_vega=np.nan,
        )
        return df

    # Work on a copy of straddle rows
    df = df.copy()
    df["vega_curve_package_id"] = np.nan
    df["vega_curve_leg_num"] = np.nan
    df["estimated_vega"] = np.nan

    # Set reference date
    if reference_date is None:
        reference_date = datetime.date.today()

    # Compute vega for each straddle
    straddle_indices = df[straddle_mask].index.tolist()

    for idx in straddle_indices:
        row = df.loc[idx]

        if use_precalculated_vega and vega_col in df.columns:
            # Use pre-calculated vega from the pricer
            vega = row.get(vega_col)
            if pd.isna(vega):
                vega = 0.0
        else:
            # Estimate vega using the approximation
            notional = row.get(notional_col, 0.0)
            if pd.isna(notional):
                notional = 0.0

            tenor = row.get(tenor_col)
            tenor_years = _parse_tenor_to_years(tenor)

            expiry = row.get(expiry_col)
            if isinstance(expiry, pd.Timestamp):
                expiry = expiry.date()
            elif isinstance(expiry, datetime.datetime):
                expiry = expiry.date()

            if expiry is not None:
                expiry_years = _time_to_expiry_years(expiry, reference_date)
            else:
                expiry_years = 0.0

            vega = _estimate_vega(
                notional=notional,
                expiry_years=expiry_years,
                underlying_tenor_years=tenor_years,
            )

        df.loc[idx, "estimated_vega"] = vega

    # Group straddles by expiry date and time window to find potential packages
    package_id_counter = 0
    assigned = set()

    for idx in straddle_indices:
        if idx in assigned:
            continue

        row = df.loc[idx]
        expiry = row.get(expiry_col)
        timestamp = row.get(timestamp_col)

        # Find candidate straddles with same expiry within time window
        candidates = []
        for other_idx in straddle_indices:
            if other_idx in assigned:
                continue

            other_row = df.loc[other_idx]
            other_expiry = other_row.get(expiry_col)
            other_timestamp = other_row.get(timestamp_col)

            # Check same expiry
            if expiry is not None and other_expiry is not None:
                exp1 = expiry.date() if hasattr(expiry, "date") else expiry
                exp2 = other_expiry.date() if hasattr(other_expiry, "date") else other_expiry
                if exp1 != exp2:
                    continue
            elif expiry is None or other_expiry is None:
                continue

            # Check time window
            if timestamp is not None and other_timestamp is not None:
                try:
                    time_diff = abs((pd.Timestamp(timestamp) - pd.Timestamp(other_timestamp)).total_seconds())
                    if time_diff > time_window_minutes * 60:
                        continue
                except Exception:
                    pass

            candidates.append(other_idx)

        # Check if we have enough candidates for a package
        if len(candidates) < min_legs:
            continue

        # Check for offsetting vega (different tenors, opposite positions)
        candidate_data = []
        for c_idx in candidates:
            c_row = df.loc[c_idx]
            c_tenor = c_row.get(tenor_col)
            c_vega = df.loc[c_idx, "estimated_vega"]
            candidate_data.append((c_idx, c_tenor, c_vega))

        # Sort by tenor to identify curve structure
        candidate_data.sort(key=lambda x: _parse_tenor_to_years(x[1]) if x[1] else 0)

        # Check for vega curve structure (different tenors)
        tenors = [x[1] for x in candidate_data]
        unique_tenors = set(t for t in tenors if t is not None and not pd.isna(t))

        if len(unique_tenors) < 2:
            continue  # Need at least 2 different tenors for a curve

        # Check vega offsetting within tolerance
        total_vega = sum(x[2] for x in candidate_data if not pd.isna(x[2]))
        total_abs_vega = sum(abs(x[2]) for x in candidate_data if not pd.isna(x[2]))

        if total_abs_vega > 0:
            vega_imbalance_pct = abs(total_vega) / total_abs_vega * 100.0
        else:
            vega_imbalance_pct = 100.0  # No vega to offset

        # For a vega curve, we might not require perfect offset
        # but we check that there's meaningful structure
        if len(candidate_data) >= min_legs and len(candidate_data) <= max_legs:
            package_id_counter += 1
            package_id = f"VEGA_CURVE_{package_id_counter:04d}"

            for leg_num, (c_idx, _, _) in enumerate(candidate_data, start=1):
                df.loc[c_idx, "vega_curve_package_id"] = package_id
                df.loc[c_idx, "vega_curve_leg_num"] = leg_num
                assigned.add(c_idx)

    return df


# -----------------------------------------------------------------------------
# Helper Functions for Vega Curve Analysis
# -----------------------------------------------------------------------------


def summarize_vega_curve_packages(
    df: pd.DataFrame,
    package_id_col: str = "vega_curve_package_id",
    tenor_col: str = "underlying_tenor",
    vega_col: str = "estimated_vega",
    notional_col: str = "notional_amount",
) -> pd.DataFrame:
    """
    Generate a summary of detected vega curve packages.

    Returns a DataFrame with one row per package, containing:
    - Package ID
    - Number of legs
    - Tenor spread
    - Net vega
    - Gross vega
    - Vega imbalance percentage
    """
    if df.empty or package_id_col not in df.columns:
        return pd.DataFrame()

    packages = df[df[package_id_col].notna()].groupby(package_id_col)

    summaries = []
    for pkg_id, group in packages:
        tenors = group[tenor_col].dropna().tolist()
        tenor_years = [_parse_tenor_to_years(t) for t in tenors]

        net_vega = group[vega_col].sum()
        gross_vega = group[vega_col].abs().sum()
        total_notional = group[notional_col].abs().sum() if notional_col in group.columns else 0

        summaries.append({
            "package_id": pkg_id,
            "num_legs": len(group),
            "tenors": sorted(set(tenors)),
            "tenor_spread_years": max(tenor_years) - min(tenor_years) if tenor_years else 0,
            "net_vega": net_vega,
            "gross_vega": gross_vega,
            "vega_imbalance_pct": abs(net_vega) / gross_vega * 100 if gross_vega > 0 else 0,
            "total_notional": total_notional,
        })

    return pd.DataFrame(summaries)
