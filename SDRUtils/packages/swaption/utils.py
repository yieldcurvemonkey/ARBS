"""
Shared utilities for swaption package detection.

This module contains helper functions used across multiple detection modules:
- Vega/time bucketing for fast grouping
- Package ID generation
- Reason string building
- Vega estimation
- Premium extraction
- Common type checks
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


# =============================================================================
# Bucketing Functions
# =============================================================================


def vega_bucket(vega: np.ndarray, tol: float) -> np.ndarray:
    """
    Bucket vega values by log scale for grouping similar-risk trades.

    Uses log scale so that "within % tolerance" becomes "nearby buckets".
    Similar to _pv01_bucket but for vega.

    Args:
        vega: Array of vega values (absolute)
        tol: Tolerance as fraction (e.g., 0.05 for 5%)

    Returns:
        Array of bucket indices
    """
    vega_pos = np.maximum(np.abs(vega), 1e-12)
    return np.floor(np.log(vega_pos) / np.log(1.0 + tol)).astype(np.int32)


def time_bucket(timestamps: np.ndarray, bucket_seconds: int = 30) -> np.ndarray:
    """
    Bucket timestamps for fast grouping.

    Args:
        timestamps: Array of epoch seconds (int64)
        bucket_seconds: Size of each bucket in seconds

    Returns:
        Array of bucket indices
    """
    return (timestamps // bucket_seconds).astype(np.int64)


# =============================================================================
# Data Extraction/Conversion
# =============================================================================


def safe_float(x) -> float:
    """Convert value to float, returning NaN for invalid values."""
    if pd.isna(x) or x == "":
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan


def extract_effective_premium(
    row: pd.Series,
    *,
    premium_col: str = "premium",
    package_price_col: str = "package_transaction_price",
    price_field_mode: str = "both",
) -> Tuple[float, str]:
    """
    Extract effective premium from a trade row.

    Handles the BILT pattern where Premium may be empty/zero but
    Package Price is populated.

    Args:
        row: Trade row as pandas Series
        premium_col: Column name for premium field
        package_price_col: Column name for package price field
        price_field_mode: One of "prefer_premium", "prefer_package_price", "both"

    Returns:
        Tuple of (effective_premium, source_field)
        source_field is one of: "PREMIUM", "PKG_PRICE", "NONE"
    """
    premium = safe_float(row.get(premium_col))
    pkg_price = safe_float(row.get(package_price_col))

    has_premium = pd.notna(premium) and premium != 0.0
    has_pkg_price = pd.notna(pkg_price) and pkg_price != 0.0

    if price_field_mode == "prefer_premium":
        if has_premium:
            return premium, "PREMIUM"
        elif has_pkg_price:
            return pkg_price, "PKG_PRICE"
        return np.nan, "NONE"

    elif price_field_mode == "prefer_package_price":
        if has_pkg_price:
            return pkg_price, "PKG_PRICE"
        elif has_premium:
            return premium, "PREMIUM"
        return np.nan, "NONE"

    else:  # "both" mode
        if has_premium:
            return premium, "PREMIUM"
        elif has_pkg_price:
            return pkg_price, "PKG_PRICE"
        return np.nan, "NONE"


# =============================================================================
# Vega Estimation
# =============================================================================


def estimate_swaption_vega(
    row: pd.Series,
    *,
    vega_col: str = "estimated_vega",
    notional_col: str = "notional",
    tenor_col: str = "tenor_years",
    forward_col: str = "forward_start_years",
) -> float:
    """
    Estimate or retrieve vega for a swaption trade.

    If estimated_vega column exists and has value, use it.
    Otherwise, use a rough approximation based on notional and tenor.

    The rough approximation is:
        vega = notional * sqrt(expiry) * 0.01

    This is a placeholder - should be replaced with proper Greek calculation.

    Args:
        row: Trade row
        vega_col: Column name for pre-computed vega
        notional_col: Column name for notional
        tenor_col: Column name for underlying tenor in years
        forward_col: Column name for option expiry (forward start years)

    Returns:
        Estimated vega value
    """
    # First try to use pre-computed vega
    if vega_col in row.index:
        vega = safe_float(row.get(vega_col))
        if pd.notna(vega) and vega > 0:
            return vega

    # Fall back to approximation
    notional = safe_float(row.get(notional_col, 0))
    expiry = safe_float(row.get(forward_col, 1.0))  # Option expiry

    if pd.isna(notional) or notional <= 0:
        return np.nan

    if pd.isna(expiry) or expiry <= 0:
        expiry = 1.0

    # Rough vega approximation: notional * sqrt(T) * 0.01
    # This gives vega in notional terms per 1% vol move
    return abs(notional) * np.sqrt(expiry) * 0.01


# =============================================================================
# Package ID and Reason Building
# =============================================================================


def compute_package_id(
    trade_ids: List[str],
    platform: str,
    timestamp_bucket: int,
    package_type: str,
) -> str:
    """
    Generate a deterministic package ID.

    Args:
        trade_ids: List of trade IDs in the package (will be sorted)
        platform: Platform identifier
        timestamp_bucket: Timestamp bucket for the package
        package_type: Type of package detected

    Returns:
        Deterministic hash-based package ID
    """
    sorted_ids = sorted(str(tid) for tid in trade_ids)
    key = f"{package_type}:{platform}:{timestamp_bucket}:{','.join(sorted_ids)}"
    return f"{package_type}_{hashlib.md5(key.encode()).hexdigest()[:12]}"


def build_package_reason(
    *,
    platform: str,
    time_delta_max_seconds: float,
    vega_cluster_spread_pct: Optional[float],
    premium_mode: str,
    num_legs: int,
    identical_timestamps: bool = False,
    extra_info: Optional[str] = None,
) -> str:
    """
    Build a structured, explainable package reason string.

    Format: key=value; pairs for easy parsing.
    """
    parts = [
        f"platform={platform}",
        f"time_delta_max={time_delta_max_seconds:.1f}s",
        f"premium_mode={premium_mode}",
        f"legs={num_legs}",
    ]

    if identical_timestamps:
        parts.append("identical_ts=Y")

    if extra_info:
        parts.append(extra_info)

    return "; ".join(parts)


# =============================================================================
# Option Type Helpers
# =============================================================================


def is_payer(label: str) -> bool:
    """Check if the product label indicates a payer swaption."""
    upper = label.upper()
    return "PAYER" in upper or "CALL" in upper


def is_receiver(label: str) -> bool:
    """Check if the product label indicates a receiver swaption."""
    upper = label.upper()
    return "RECEIVER" in upper or "PUT" in upper


# =============================================================================
# DataFrame Column Initialization
# =============================================================================


def ensure_package_columns(
    df: pd.DataFrame,
    package_col: str = "package_type",
    default_package_type: str = "SWAPTION",
) -> pd.DataFrame:
    """
    Ensure the DataFrame has all required package columns initialized.

    Args:
        df: DataFrame to update
        package_col: Column name for package type
        default_package_type: Default value for package_type column

    Returns:
        DataFrame with initialized columns
    """
    out = df.copy()

    for col, default in [
        (package_col, default_package_type),
        ("package_id", None),
        ("package_legs", None),
        ("package_confidence", None),
        ("package_reason", None),
        ("package_legs_count", None),
    ]:
        if col not in out.columns:
            out[col] = default

    return out


# =============================================================================
# Economic Filter Helpers
# =============================================================================


def check_economic_filters(
    i: int,
    j: int,
    *,
    platforms: Optional[np.ndarray] = None,
    currencies: Optional[np.ndarray] = None,
    underliers: Optional[np.ndarray] = None,
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    require_same_underlier: bool = False,
) -> bool:
    """
    Check economic filters between two trade indices.

    Args:
        i: First trade index
        j: Second trade index
        platforms: Array of platform values (or None if not required)
        currencies: Array of currency values (or None if not required)
        underliers: Array of underlier values (or None if not required)
        require_same_platform: Whether platform must match
        require_same_currency: Whether currency must match
        require_same_underlier: Whether underlier must match

    Returns:
        True if economic filters pass, False otherwise
    """
    try:
        if require_same_platform and platforms is not None:
            if platforms[i] != platforms[j]:
                return False
        if require_same_currency and currencies is not None:
            if currencies[i] != currencies[j]:
                return False
        if require_same_underlier and underliers is not None:
            if underliers[i] != underliers[j]:
                return False
        return True
    except Exception:
        return False
