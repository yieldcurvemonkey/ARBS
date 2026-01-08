"""
Swaption package detection module.

Detects multi-leg swaption packages including:
- VEGA_BUCKETED_PACKAGE: Trades with similar vega within time proximity
- IMPLIED_PACKAGE_SAME_TIMESTAMP: Trades with identical timestamps (BILT pattern)
- LINKED_PACKAGES_TIME_PROXIMITY: Separate packages linked by time and vega overlap

Detection uses configurable business logic following the same patterns as
curve.py and fly.py for linear trades.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.base import PackageDetector


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class SwaptionPackageDetectionConfig:
    """
    Configuration for swaption package detection algorithms.

    All detection logic thresholds are configurable via this dataclass.
    """

    # Time windows
    time_window_seconds: int = 300  # 5 minutes for grouping trades
    time_window_link_seconds: int = 600  # 10 minutes for linking separate packages

    # Vega tolerance for matching legs
    vega_tolerance_pct: float = 0.05  # 5% tolerance

    # Minimum legs for a package
    min_legs: int = 2

    # Platform filtering
    platform_allowlist: Optional[List[str]] = None  # If set, only these platforms
    platform_blocklist: Optional[List[str]] = None  # If set, exclude these platforms

    # Economic filters
    require_same_platform: bool = True
    require_same_currency: bool = True
    require_same_underlier: bool = True

    # Timestamp matching mode
    timestamp_mode: Literal["exact", "fuzzy"] = "fuzzy"
    exact_timestamp_tolerance_seconds: int = 1  # For "exact" mode

    # Price field handling mode
    # "prefer_premium": Use premium if available, else package_price
    # "prefer_package_price": Use package_price if available, else premium
    # "both": Check both fields and flag anomalies
    price_field_mode: Literal["prefer_premium", "prefer_package_price", "both"] = "both"

    # Notional sanity checks
    notional_sanity_checks: bool = True
    notional_max_multiplier: float = 1000.0  # Flag if notional > max_mult * median

    # Column names (SDR raw columns)
    exec_col: str = "execution_timestamp"
    platform_col: str = "Platform identifier"
    currency_col: str = "notional_currency"
    underlier_col: str = "UPI Underlier Name"
    trade_id_col: str = "trade_id"
    premium_col: str = "premium"
    package_price_col: str = "Package transaction price"
    package_indicator_col: str = "Package indicator"
    vega_col: str = "estimated_vega"
    notional_col: str = "notional"
    strike_col: str = "strike"
    expiration_col: str = "expiration_date"
    tenor_col: str = "tenor_years"
    forward_col: str = "forward_start_years"

    # Confidence scoring weights
    confidence_weights: Dict[str, float] = field(default_factory=lambda: {
        "identical_timestamp": 0.3,
        "vega_similarity": 0.25,
        "package_indicator": 0.15,
        "premium_anomaly": 0.15,  # Premium zero but package_price non-zero
        "platform_match": 0.15,
    })


# Default config instance
DEFAULT_SWAPTION_PACKAGE_CONFIG = SwaptionPackageDetectionConfig()


# =============================================================================
# Helper Functions
# =============================================================================


def _vega_bucket(vega: np.ndarray, tol: float) -> np.ndarray:
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


def _time_bucket(timestamps: np.ndarray, bucket_seconds: int = 30) -> np.ndarray:
    """
    Bucket timestamps for fast grouping.

    Args:
        timestamps: Array of epoch seconds (int64)
        bucket_seconds: Size of each bucket in seconds

    Returns:
        Array of bucket indices
    """
    return (timestamps // bucket_seconds).astype(np.int64)


def _extract_effective_premium(
    row: pd.Series,
    config: SwaptionPackageDetectionConfig,
) -> Tuple[float, str]:
    """
    Extract effective premium from a trade row.

    Handles the BILT pattern where Premium may be empty/zero but
    Package Price is populated.

    Args:
        row: Trade row as pandas Series
        config: Detection configuration

    Returns:
        Tuple of (effective_premium, source_field)
        source_field is one of: "PREMIUM", "PKG_PRICE", "NONE"
    """
    premium = _safe_float(row.get(config.premium_col))
    pkg_price = _safe_float(row.get(config.package_price_col))

    has_premium = pd.notna(premium) and premium != 0.0
    has_pkg_price = pd.notna(pkg_price) and pkg_price != 0.0

    if config.price_field_mode == "prefer_premium":
        if has_premium:
            return premium, "PREMIUM"
        elif has_pkg_price:
            return pkg_price, "PKG_PRICE"
        return np.nan, "NONE"

    elif config.price_field_mode == "prefer_package_price":
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


def _safe_float(x) -> float:
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


def _compute_package_id(
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


def _build_package_reason(
    *,
    platform: str,
    time_delta_max_seconds: float,
    vega_cluster_spread_pct: float,
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
        f"vega_cluster_spread={vega_cluster_spread_pct:.1f}%",
        f"premium_mode={premium_mode}",
        f"legs={num_legs}",
    ]

    if identical_timestamps:
        parts.append("identical_ts=Y")

    if extra_info:
        parts.append(extra_info)

    return "; ".join(parts)


def _estimate_swaption_vega(
    row: pd.Series,
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
        vega ≈ notional * sqrt(expiry) * 0.01

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
        vega = _safe_float(row.get(vega_col))
        if pd.notna(vega) and vega > 0:
            return vega

    # Fall back to approximation
    notional = _safe_float(row.get(notional_col, 0))
    expiry = _safe_float(row.get(forward_col, 1.0))  # Option expiry

    if pd.isna(notional) or notional <= 0:
        return np.nan

    if pd.isna(expiry) or expiry <= 0:
        expiry = 1.0

    # Rough vega approximation: notional * sqrt(T) * 0.01
    # This gives vega in notional terms per 1% vol move
    return abs(notional) * np.sqrt(expiry) * 0.01


# =============================================================================
# Main Detection Functions
# =============================================================================


def detect_swaption_packages_df(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    vega_estimator: Optional[Callable[[pd.Series], float]] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Detect swaption packages using vega bucketing and time proximity.

    This is the main entry point for swaption package detection.
    Mirrors the pattern of detect_fly_trades_df and detect_curve_trades_df.

    Detection Strategy:
    1. Filter to swaption candidates (not already in a package)
    2. Sort by execution time
    3. Maintain sliding time window
    4. Use vega bucketing to find similar-risk trades
    5. Apply economic filters (platform, currency, underlier)
    6. Detect implied packages from identical timestamps
    7. Score confidence based on multiple factors

    Args:
        df: Classifications dataframe with swaption trades
        config: Detection configuration (uses default if None)
        vega_estimator: Optional custom vega estimation function
        product_col: Column name for product type
        package_col: Column name for package type

    Returns:
        DataFrame with package annotations:
        - package_type: Type of package (VEGA_BUCKETED_PACKAGE, etc.)
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the package
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation string
        - package_legs_count: Number of legs in package
        - effective_premium: Extracted premium value
        - effective_premium_source: Source of premium (PREMIUM/PKG_PRICE/NONE)
    """
    if df.empty:
        return df

    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    # Initialize output columns if not present
    if package_col not in out.columns:
        out[package_col] = "SWAPTION"
    if "package_id" not in out.columns:
        out["package_id"] = None
    if "package_legs" not in out.columns:
        out["package_legs"] = None
    if "package_confidence" not in out.columns:
        out["package_confidence"] = None
    if "package_reason" not in out.columns:
        out["package_reason"] = None
    if "package_legs_count" not in out.columns:
        out["package_legs_count"] = None

    # Determine vega estimator
    if vega_estimator is None:
        def _default_vega_estimator(row: pd.Series) -> float:
            return _estimate_swaption_vega(
                row,
                vega_col=config.vega_col,
                notional_col=config.notional_col,
                tenor_col=config.tenor_col,
                forward_col=config.forward_col,
            )
        vega_estimator = _default_vega_estimator

    # Filter to swaption candidates not already in a package
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")

    candidate_mask = is_swaption & not_packaged

    # Apply platform filters
    if config.platform_allowlist:
        platform_ok = out[config.platform_col].isin(config.platform_allowlist)
        candidate_mask &= platform_ok
    if config.platform_blocklist:
        platform_blocked = out[config.platform_col].isin(config.platform_blocklist)
        candidate_mask &= ~platform_blocked

    # Extract candidate indices
    cand_idx = out.index[candidate_mask].tolist()
    if len(cand_idx) < config.min_legs:
        return out

    # Build candidate arrays for fast processing
    cand = out.loc[cand_idx].copy()

    # Compute vega for all candidates
    cand["_vega"] = cand.apply(vega_estimator, axis=1)

    # Extract effective premium
    premium_results = cand.apply(
        lambda row: _extract_effective_premium(row, config), axis=1
    )
    cand["_eff_premium"] = premium_results.apply(lambda x: x[0])
    cand["_eff_premium_src"] = premium_results.apply(lambda x: x[1])

    # Ensure execution timestamp is epoch seconds
    cand["_t"] = _ensure_int64_epoch_seconds(cand[config.exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    # Convert to numpy arrays for fast processing
    n = len(cand)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    vega = cand["_vega"].to_numpy(dtype=np.float64)
    trade_ids = cand[config.trade_id_col].astype(str).to_numpy()

    # Precompute economic key arrays
    plat = (
        cand[config.platform_col].astype("string").to_numpy()
        if (config.require_same_platform and config.platform_col in cand.columns)
        else None
    )
    ccy = (
        cand[config.currency_col].astype("string").to_numpy()
        if (config.require_same_currency and config.currency_col in cand.columns)
        else None
    )
    und = (
        cand[config.underlier_col].astype("string").to_numpy()
        if (config.require_same_underlier and config.underlier_col in cand.columns)
        else None
    )

    # Package indicator and premium arrays for confidence scoring
    pkg_ind = cand[config.package_indicator_col].to_numpy() if config.package_indicator_col in cand.columns else None
    eff_prem = cand["_eff_premium"].to_numpy(dtype=np.float64)
    eff_prem_src = cand["_eff_premium_src"].to_numpy()

    # Bucket arrays
    vega_bucket = _vega_bucket(vega, config.vega_tolerance_pct)
    time_bucket = _time_bucket(tsec, bucket_seconds=30)

    # Sliding window approach
    store: Dict[Tuple[int, int, str], List[int]] = {}  # (time_bucket, vega_bucket, platform) -> indices
    head: Dict[Tuple[int, int, str], int] = {}

    matched = np.zeros(n, dtype=bool)
    pkg_ids = np.full(n, "", dtype=object)
    pkg_type = np.full(n, "", dtype=object)
    pkg_legs = np.full(n, None, dtype=object)
    pkg_conf = np.full(n, 0.0, dtype=np.float64)
    pkg_reason = np.full(n, "", dtype=object)
    pkg_legs_count = np.full(n, 0, dtype=np.int32)

    left = 0

    def _evict_old(curr_t: int):
        nonlocal left
        while left < n and (curr_t - tsec[left] > config.time_window_seconds):
            left += 1

    def _active_list(key: Tuple[int, int, str]) -> List[int]:
        lst = store.get(key)
        if not lst:
            return []
        h = head.get(key, 0)
        while h < len(lst) and lst[h] < left:
            h += 1
        head[key] = h
        return lst[h:]

    def _econ_ok(i: int, j: int) -> bool:
        """Check economic filters between two trades."""
        if ccy is not None and ccy[i] != ccy[j]:
            return False
        if und is not None and und[i] != und[j]:
            return False
        if plat is not None and plat[i] != plat[j]:
            return False
        return True

    def _compute_confidence(indices: List[int]) -> float:
        """Compute confidence score for a package."""
        conf = 0.0
        weights = config.confidence_weights

        # Identical timestamp bonus
        if len(set(tsec[indices])) == 1:
            conf += weights.get("identical_timestamp", 0.3)

        # Vega similarity bonus
        vegas = vega[indices]
        if len(vegas) > 1 and np.nanmean(vegas) > 0:
            vega_spread = (np.nanmax(vegas) - np.nanmin(vegas)) / np.nanmean(vegas)
            if vega_spread < config.vega_tolerance_pct:
                conf += weights.get("vega_similarity", 0.25)
            elif vega_spread < config.vega_tolerance_pct * 2:
                conf += weights.get("vega_similarity", 0.25) * 0.5

        # Package indicator bonus (if any leg has it)
        if pkg_ind is not None:
            if any(pkg_ind[idx] == True or pkg_ind[idx] == "Y" for idx in indices):
                conf += weights.get("package_indicator", 0.15)

        # Premium anomaly bonus (zeros with non-zero package price)
        prem_srcs = [eff_prem_src[idx] for idx in indices]
        if any(src == "PKG_PRICE" for src in prem_srcs):
            conf += weights.get("premium_anomaly", 0.15)

        # Platform match bonus (all same platform)
        if plat is not None and len(set(plat[indices])) == 1:
            conf += weights.get("platform_match", 0.15)

        return min(conf, 1.0)

    # Phase 1: Detect packages via vega bucketing and time proximity
    for i in range(n):
        if matched[i]:
            continue

        _evict_old(tsec[i])

        # Skip if vega is invalid
        if pd.isna(vega[i]) or vega[i] <= 0:
            continue

        plat_i = plat[i] if plat is not None else "UNKNOWN"
        tb_i = int(time_bucket[i])
        vb_i = int(vega_bucket[i])

        # Find candidate matches
        candidates: List[int] = []

        # Look in neighboring vega buckets
        for dvb in (-1, 0, 1):
            # Look in neighboring time buckets (within window)
            for dtb in range(-int(config.time_window_seconds / 30) - 1, int(config.time_window_seconds / 30) + 2):
                key = (tb_i + dtb, vb_i + dvb, plat_i)
                candidates.extend(_active_list(key))

        # Filter candidates by economic constraints and time window
        valid_candidates = [i]  # Include current trade
        for j in candidates:
            if j == i or matched[j]:
                continue
            if abs(tsec[i] - tsec[j]) > config.time_window_seconds:
                continue
            if not _econ_ok(i, j):
                continue

            # Check vega similarity
            if pd.isna(vega[j]) or vega[j] <= 0:
                continue
            avg_vega = 0.5 * (vega[i] + vega[j])
            vega_rel = abs(vega[i] - vega[j]) / max(avg_vega, 1e-12)
            if vega_rel > config.vega_tolerance_pct:
                continue

            valid_candidates.append(j)

        # Check for package
        if len(valid_candidates) >= config.min_legs:
            # Determine package type
            timestamps_set = set(tsec[valid_candidates])
            if len(timestamps_set) == 1:
                ptype = "IMPLIED_PACKAGE_SAME_TIMESTAMP"
                identical_ts = True
            else:
                ptype = "VEGA_BUCKETED_PACKAGE"
                identical_ts = False

            # Compute time delta
            time_delta_max = float(np.max(tsec[valid_candidates]) - np.min(tsec[valid_candidates]))

            # Compute vega spread
            package_vegas = vega[valid_candidates]
            vega_mean = np.nanmean(package_vegas)
            vega_spread_pct = (
                100.0 * (np.nanmax(package_vegas) - np.nanmin(package_vegas)) / max(vega_mean, 1e-12)
                if vega_mean > 0 else 0.0
            )

            # Determine premium mode
            prem_modes = [eff_prem_src[idx] for idx in valid_candidates]
            if "PKG_PRICE" in prem_modes and "PREMIUM" not in prem_modes:
                prem_mode = "PKG_PRICE_ONLY"
            elif "PREMIUM" in prem_modes:
                prem_mode = "PREMIUM"
            else:
                prem_mode = "NONE"

            # Compute confidence
            confidence = _compute_confidence(valid_candidates)

            # Generate package ID
            pid = _compute_package_id(
                [trade_ids[idx] for idx in valid_candidates],
                plat_i,
                tb_i,
                ptype,
            )

            # Generate reason
            reason = _build_package_reason(
                platform=plat_i,
                time_delta_max_seconds=time_delta_max,
                vega_cluster_spread_pct=vega_spread_pct,
                premium_mode=prem_mode,
                num_legs=len(valid_candidates),
                identical_timestamps=identical_ts,
            )

            # Mark all legs
            legs_list = [str(trade_ids[idx]) for idx in valid_candidates]
            for idx in valid_candidates:
                matched[idx] = True
                pkg_ids[idx] = pid
                pkg_type[idx] = ptype
                pkg_legs[idx] = legs_list
                pkg_conf[idx] = confidence
                pkg_reason[idx] = reason
                pkg_legs_count[idx] = len(valid_candidates)

        # Add current trade to store for future matching
        key_i = (tb_i, vb_i, plat_i)
        store.setdefault(key_i, []).append(i)

    # Build result dataframe and merge back
    res = pd.DataFrame({
        config.trade_id_col: trade_ids,
        "_pkg_type": pkg_type,
        "_pkg_id": pkg_ids,
        "_pkg_legs": pkg_legs,
        "_pkg_conf": pkg_conf,
        "_pkg_reason": pkg_reason,
        "_pkg_legs_count": pkg_legs_count,
    })

    # Also include effective premium columns from cand
    cand_result = cand[[config.trade_id_col, "_eff_premium", "_eff_premium_src"]].copy()
    res = res.merge(cand_result, on=config.trade_id_col, how="left")

    # Merge back to output
    out = out.merge(
        res[[config.trade_id_col, "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count", "_eff_premium", "_eff_premium_src"]],
        on=config.trade_id_col,
        how="left",
    )

    # Apply detected packages
    detected_mask = out["_pkg_id"].notna() & (out["_pkg_id"] != "")
    out.loc[detected_mask, package_col] = out.loc[detected_mask, "_pkg_type"]
    out.loc[detected_mask, "package_id"] = out.loc[detected_mask, "_pkg_id"]
    out.loc[detected_mask, "package_legs"] = out.loc[detected_mask, "_pkg_legs"]
    out.loc[detected_mask, "package_confidence"] = out.loc[detected_mask, "_pkg_conf"]
    out.loc[detected_mask, "package_reason"] = out.loc[detected_mask, "_pkg_reason"]
    out.loc[detected_mask, "package_legs_count"] = out.loc[detected_mask, "_pkg_legs_count"]

    # Add effective premium columns
    out["effective_premium"] = out["_eff_premium"]
    out["effective_premium_source"] = out["_eff_premium_src"]

    # Clean up temp columns
    temp_cols = ["_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count", "_eff_premium", "_eff_premium_src"]
    out.drop(columns=[c for c in temp_cols if c in out.columns], inplace=True, errors="ignore")

    return out


def link_swaption_packages(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Second-pass linking of separate swaption packages.

    Links packages that:
    - Are on the same platform
    - Have time gap <= time_window_link_seconds
    - Have vega overlap / similarity within tolerance

    This handles the 9m1y vs 1y1y example where two separate packages
    are economically linked.

    Args:
        df: DataFrame with package annotations from detect_swaption_packages_df
        config: Detection configuration
        package_col: Column name for package type

    Returns:
        DataFrame with additional columns:
        - linked_package_id: ID linking related packages
        - linked_package_relation: Relation type (e.g., LINKED_BY_TIME_VEGA)
    """
    if df.empty:
        return df

    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    # Initialize output columns
    if "linked_package_id" not in out.columns:
        out["linked_package_id"] = None
    if "linked_package_relation" not in out.columns:
        out["linked_package_relation"] = None

    # Find detected packages (non-null package_id with SWAPTION-related types)
    swaption_package_types = ["VEGA_BUCKETED_PACKAGE", "IMPLIED_PACKAGE_SAME_TIMESTAMP"]
    has_package = (
        out["package_id"].notna() &
        out[package_col].isin(swaption_package_types)
    )

    if not has_package.any():
        return out

    # Get unique packages with their characteristics
    packaged_df = out.loc[has_package].copy()

    # Aggregate package info
    package_info = packaged_df.groupby("package_id").agg({
        config.exec_col: ["min", "max"],
        config.platform_col: "first",
        config.currency_col: "first",
        "package_confidence": "first",
    })
    package_info.columns = ["time_min", "time_max", "platform", "currency", "confidence"]
    package_info["time_mid"] = (
        pd.to_datetime(package_info["time_min"]).astype(np.int64) // 10**9 +
        pd.to_datetime(package_info["time_max"]).astype(np.int64) // 10**9
    ) // 2

    # Compute package-level vega (sum of leg vegas)
    if "effective_premium" in packaged_df.columns:
        package_vega = packaged_df.groupby("package_id")["effective_premium"].sum()
    else:
        package_vega = pd.Series(dtype=float)

    package_info["total_vega"] = package_vega
    package_info = package_info.reset_index()

    if len(package_info) < 2:
        return out

    # Find linkable packages
    link_groups: Dict[str, List[str]] = {}
    linked: Set[str] = set()
    link_counter = 0

    pkg_ids = package_info["package_id"].tolist()
    n_pkgs = len(pkg_ids)

    for i in range(n_pkgs):
        if pkg_ids[i] in linked:
            continue

        pid_i = pkg_ids[i]
        time_i = package_info.iloc[i]["time_mid"]
        plat_i = package_info.iloc[i]["platform"]
        ccy_i = package_info.iloc[i]["currency"]
        vega_i = package_info.iloc[i].get("total_vega", np.nan)

        group = [pid_i]

        for j in range(i + 1, n_pkgs):
            if pkg_ids[j] in linked:
                continue

            pid_j = pkg_ids[j]
            time_j = package_info.iloc[j]["time_mid"]
            plat_j = package_info.iloc[j]["platform"]
            ccy_j = package_info.iloc[j]["currency"]
            vega_j = package_info.iloc[j].get("total_vega", np.nan)

            # Check time proximity
            if abs(time_i - time_j) > config.time_window_link_seconds:
                continue

            # Check same platform and currency
            if config.require_same_platform and plat_i != plat_j:
                continue
            if config.require_same_currency and ccy_i != ccy_j:
                continue

            # Check vega similarity
            if pd.notna(vega_i) and pd.notna(vega_j) and vega_i > 0 and vega_j > 0:
                avg_vega = 0.5 * (vega_i + vega_j)
                vega_rel = abs(vega_i - vega_j) / max(avg_vega, 1e-12)
                if vega_rel <= config.vega_tolerance_pct * 2:  # Slightly relaxed for linking
                    group.append(pid_j)

        if len(group) > 1:
            link_counter += 1
            link_id = f"LINKED_{link_counter}"
            for pid in group:
                linked.add(pid)
                link_groups[pid] = link_id

    # Apply link annotations
    if link_groups:
        for pid, link_id in link_groups.items():
            mask = out["package_id"] == pid
            out.loc[mask, "linked_package_id"] = link_id
            out.loc[mask, "linked_package_relation"] = "LINKED_BY_TIME_VEGA"

    return out


def detect_and_link_swaption_packages_df(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    vega_estimator: Optional[Callable[[pd.Series], float]] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Combined detection and linking of swaption packages.

    Convenience function that runs both detection and linking passes.

    Args:
        df: Classifications dataframe with swaption trades
        config: Detection configuration
        vega_estimator: Optional custom vega estimation function
        product_col: Column name for product type
        package_col: Column name for package type

    Returns:
        DataFrame with full package annotations including links
    """
    out = detect_swaption_packages_df(
        df,
        config=config,
        vega_estimator=vega_estimator,
        product_col=product_col,
        package_col=package_col,
    )

    out = link_swaption_packages(
        out,
        config=config,
        package_col=package_col,
    )

    return out


# =============================================================================
# Package Detector Class
# =============================================================================


class SwaptionPackageDetector(PackageDetector):
    """
    Swaption package detector implementing the PackageDetector interface.

    This class wraps the functional detection API for integration with
    the SDRUtils registry system.
    """

    package_type = "SWAPTION_PACKAGE"

    def __init__(self, config: Optional[SwaptionPackageDetectionConfig] = None):
        self.config = config or DEFAULT_SWAPTION_PACKAGE_CONFIG

    def detect(self, df: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        """
        Detect swaption packages in the given dataframe.

        Args:
            df: Classifications dataframe
            **kwargs: Additional arguments passed to detection function

        Returns:
            DataFrame with package annotations
        """
        return detect_and_link_swaption_packages_df(
            df,
            config=self.config,
            **kwargs,
        )

    def metadata(self) -> Dict[str, str]:
        return {
            "package_type": self.package_type,
            "time_window_seconds": str(self.config.time_window_seconds),
            "vega_tolerance_pct": str(self.config.vega_tolerance_pct),
        }
