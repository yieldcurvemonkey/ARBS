"""
Swaption package detection module.

Detects multi-leg swaption packages including:
- STRADDLE: Payer + Receiver swaptions with same strike/expiry/tenor
- RISK_REVERSAL: 4-leg structures with wings + delta hedge (3 strikes, 2 notionals)
- VERTICAL_SPREAD: Same tenor, different strikes, same option type (1x1, 1x2, 1x1.5, etc.)
- CONDITIONAL_CURVE: Same expiry, different tail maturities (e.g., 1Yx10Y vs 1Yx30Y)
- VEGA_CURVE: Vega-matched straddles across different tenors (expiry/tail spreads)
- VEGA_BUCKETED_PACKAGE: Trades with similar vega within time proximity
- IMPLIED_PACKAGE_SAME_TIMESTAMP: Trades with identical timestamps (BILT pattern)
- LINKED_PACKAGES_TIME_PROXIMITY: Separate packages linked by time and vega overlap

Key insights from trader context:
- BILT: Premium field may be empty but Package Price filled - check BOTH
- Implied packages: identical timestamps on BILT often indicate linked trades
- Vega bucketing: trades within 5% vega and 5 min timestamp = potential package
- Package indicator unreliable on customer platforms
- IDB platforms (BGCD, ISWV, TPSE) are golden data sources

Detection uses configurable business logic following the same patterns as
curve.py and fly.py for linear trades.
"""

from __future__ import annotations

import datetime
import hashlib
import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple, Union

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
    vega_tolerance_pct: float = 0.00  # 5% tolerance

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
    platform_col: str = "platform_identifier"
    currency_col: str = "notional_currency"
    underlier_col: str = "upi_underlier_name"
    trade_id_col: str = "trade_id"
    premium_col: str = "premium"
    package_price_col: str = "package_transaction_price"
    package_indicator_col: str = "package_indicator"
    vega_col: str = "estimated_vega"
    notional_col: str = "notional"
    strike_col: str = "strike"
    expiration_col: str = "expiration_date"
    tenor_col: str = "tenor_years"
    forward_col: str = "forward_start_years"
    tail_maturity_col: str = "underlying_expiration_date"  # For tail maturity

    # Confidence scoring weights
    confidence_weights: Dict[str, float] = field(
        default_factory=lambda: {
            "identical_timestamp": 0.3,
            "vega_similarity": 0.25,
            "package_indicator": 0.15,
            "premium_anomaly": 0.15,  # Premium zero but package_price non-zero
            "platform_match": 0.15,
        }
    )

    # ==========================================================================
    # Vertical Spread Detection Parameters
    # ==========================================================================

    # Supported spread ratios: (ratio, name, tolerance)
    # e.g., (2.0, "1x2", 0.1) means ratio 2.0 ± 10%
    spread_ratios: List[Tuple[float, str, float]] = field(
        default_factory=lambda: [
            (1.0, "1x1", 0.10),  # 1x1 spread (same notional)
            (1.5, "1x1.5", 0.10),  # 1x1.5 spread
            (2.0, "1x2", 0.10),  # 1x2 spread
            (2.5, "1x2.5", 0.10),  # 1x2.5 spread
            (3.0, "1x3", 0.10),  # 1x3 spread
        ]
    )

    # Minimum strike width for vertical spreads (in absolute terms, e.g., 0.001 = 10bps)
    vertical_spread_min_strike_width: float = 0.001  # 10bps minimum

    # ==========================================================================
    # Conditional Curve Trade Detection Parameters
    # ==========================================================================

    # Minimum tail difference (in years) for conditional curve trades
    # e.g., 5.0 means at least 5Y difference between tails (10Y vs 30Y qualifies)
    conditional_curve_min_tail_diff_years: float = 5.0

    # ==========================================================================
    # Vega Curve Detection Parameters
    # ==========================================================================

    # Vega tolerance for curve trades (typically looser than general vega tolerance)
    vega_curve_tolerance_pct: float = 0.05  # 5% tolerance for vega curve matching

    # Minimum expiry or tail difference for vega curve trades (in years)
    vega_curve_min_expiry_diff_years: float = 0.25  # 3 months minimum
    vega_curve_min_tail_diff_years: float = 1.0  # 1 year minimum

    # ==========================================================================
    # IDB Platform Classification
    # ==========================================================================

    # Inter-dealer broker platforms (golden data sources)
    idb_platforms: List[str] = field(default_factory=lambda: ["BGCD", "ISWV", "TPSE"])

    # Customer-facing platforms (variable reliability)
    customer_platforms: List[str] = field(default_factory=lambda: ["BILT", "XXXX", "TWSF", "BBSF", "XOFF"])


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
        # f"vega_cluster_spread={vega_cluster_spread_pct:.1f}%",
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
# Straddle Detection
# =============================================================================


def detect_swaption_straddles_df(
    df: pd.DataFrame,
    *,
    straddle_timestamp_tolerance: datetime.timedelta,
    strike_tolerance: float,
    notional_tolerance_pct: float,
    config: Optional["SwaptionPackageDetectionConfig"] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Detect swaption straddles (payer + receiver with same strike/expiry/tenor).

    A straddle consists of:
    - One PAYER swaption and one RECEIVER swaption
    - Same strike price (within tolerance)
    - Same option expiration date
    - Same underlying tenor
    - Same notional (within tolerance)
    - Execution timestamps within the specified tolerance

    Args:
        df: Classifications dataframe with swaption trades
        straddle_timestamp_tolerance: Maximum time difference between payer and
            receiver legs for them to be considered a straddle. Pass as
            datetime.timedelta (e.g., timedelta(seconds=60) for 1 minute).
        strike_tolerance: Absolute tolerance for strike price matching
        notional_tolerance_pct: Percentage tolerance for notional matching (0.05 = 5%)
        config: Detection configuration (uses default if None)
        product_col: Column name for product type
        package_col: Column name for package type

    Returns:
        DataFrame with straddle annotations:
        - package_type: "STRADDLE" for detected straddles
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the straddle
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation string
        - package_legs_count: Always 2 for straddles
    """
    if df.empty:
        return df

    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    for col, default in [
        (package_col, "SWAPTION"),
        ("package_id", None),
        ("package_legs", None),
        ("package_confidence", None),
        ("package_reason", None),
        ("package_legs_count", None),
    ]:
        if col not in out.columns:
            out[col] = default

    tolerance_seconds = straddle_timestamp_tolerance.total_seconds()

    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

    is_payer = out[product_col].astype(str).str.contains("PAYER|CALL", case=False, na=False)
    is_receiver = out[product_col].astype(str).str.contains("RECEIVER|PUT", case=False, na=False)

    payer_mask = candidate_mask & is_payer
    receiver_mask = candidate_mask & is_receiver

    payers = out.loc[payer_mask].copy()
    receivers = out.loc[receiver_mask].copy()

    if payers.empty or receivers.empty:
        return out

    payers["_t"] = _ensure_int64_epoch_seconds(payers[config.exec_col])
    receivers["_t"] = _ensure_int64_epoch_seconds(receivers[config.exec_col])

    payer_idx = payers.index.tolist()
    receiver_idx = receivers.index.tolist()

    matched_payers: Set[int] = set()
    matched_receivers: Set[int] = set()

    straddle_counter = 0

    for p_idx in payer_idx:
        if p_idx in matched_payers:
            continue

        p_row = payers.loc[p_idx]
        p_t = p_row["_t"]
        p_strike = _safe_float(p_row.get(config.strike_col))
        p_expiry = p_row.get(config.expiration_col)
        p_tenor = _safe_float(p_row.get(config.tenor_col))
        p_notional = _safe_float(p_row.get(config.notional_col))
        p_platform = p_row.get(config.platform_col, "")
        p_currency = p_row.get(config.currency_col, "")
        p_underlier = p_row.get(config.underlier_col, "")
        p_trade_id = str(p_row.get(config.trade_id_col, ""))

        # Skip if missing critical fields
        if pd.isna(p_strike) or pd.isna(p_tenor) or pd.isna(p_notional):
            continue

        best_match = None
        best_time_diff = float("inf")

        for r_idx in receiver_idx:
            if r_idx in matched_receivers:
                continue

            r_row = receivers.loc[r_idx]
            r_t = r_row["_t"]

            # Check timestamp tolerance
            time_diff = abs(p_t - r_t)
            if time_diff > tolerance_seconds:
                continue

            r_strike = _safe_float(r_row.get(config.strike_col))
            r_expiry = r_row.get(config.expiration_col)
            r_tenor = _safe_float(r_row.get(config.tenor_col))
            r_notional = _safe_float(r_row.get(config.notional_col))
            r_platform = r_row.get(config.platform_col, "")
            r_currency = r_row.get(config.currency_col, "")
            r_underlier = r_row.get(config.underlier_col, "")

            # Skip if missing critical fields
            if pd.isna(r_strike) or pd.isna(r_tenor) or pd.isna(r_notional):
                continue

            # Check strike match
            if abs(p_strike - r_strike) > strike_tolerance:
                continue

            # Check expiry match (if both are valid)
            if pd.notna(p_expiry) and pd.notna(r_expiry):
                p_exp_date = pd.to_datetime(p_expiry)
                r_exp_date = pd.to_datetime(r_expiry)
                if p_exp_date != r_exp_date:
                    continue

            # Check tenor match
            if abs(p_tenor - r_tenor) > 0.01:  # 0.01 year tolerance
                continue

            # Check notional match
            avg_notional = 0.5 * (p_notional + r_notional)
            if avg_notional > 0:
                notional_diff = abs(p_notional - r_notional) / avg_notional
                if notional_diff > notional_tolerance_pct:
                    continue

            # Check economic filters
            if config.require_same_platform and p_platform != r_platform:
                continue
            if config.require_same_currency and p_currency != r_currency:
                continue
            if config.require_same_underlier and p_underlier != r_underlier:
                continue

            # This is a valid match - track the best one (closest in time)
            if time_diff < best_time_diff:
                best_time_diff = time_diff
                best_match = r_idx

        # If we found a match, create the straddle
        if best_match is not None:
            r_idx = best_match
            r_row = receivers.loc[r_idx]
            r_trade_id = str(r_row.get(config.trade_id_col, ""))

            matched_payers.add(p_idx)
            matched_receivers.add(r_idx)
            straddle_counter += 1

            # Generate package ID
            pid = _compute_package_id(
                [p_trade_id, r_trade_id],
                p_platform,
                int(p_t // 30),  # Time bucket
                "STRADDLE",
            )

            # Compute confidence
            confidence = 0.8  # High base confidence for straddles
            if best_time_diff < 5:  # Within 5 seconds
                confidence += 0.1
            if abs(_safe_float(p_row.get(config.strike_col)) - _safe_float(r_row.get(config.strike_col))) < 0.00001:
                confidence += 0.1
            confidence = min(confidence, 1.0)

            # Build reason
            reason = _build_package_reason(
                platform=p_platform,
                time_delta_max_seconds=best_time_diff,
                vega_cluster_spread_pct=None,  # N/A for straddles
                premium_mode="STRADDLE",
                num_legs=2,
                identical_timestamps=(best_time_diff < 1),
                extra_info=f"strike={p_strike:.4f}; tenor={p_tenor:.1f}Y",
            )

            legs_list = [p_trade_id, r_trade_id]

            # Update both legs
            for idx in [p_idx, r_idx]:
                idx_mask = out.index == idx
                out.loc[idx_mask, package_col] = "STRADDLE"
                out.loc[idx_mask, "package_id"] = pid
                legs_count = int(idx_mask.sum())
                out.loc[idx_mask, "package_legs"] = pd.Series(
                    [legs_list] * legs_count,
                    index=out.index[idx_mask],
                )
                out.loc[idx_mask, "package_confidence"] = confidence
                out.loc[idx_mask, "package_reason"] = reason
                out.loc[idx_mask, "package_legs_count"] = 2

    return out


# =============================================================================
# Risk Reversal Detection
# =============================================================================


def detect_swaption_risk_reversals_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 60,
    strike_tolerance: float = 0.0001,
    notional_tolerance_pct: float = 0.05,
    middle_notional_max_ratio: float = 0.5,
    require_same_expiration: bool = True,
    require_same_tenor: bool = True,
    require_same_forward: bool = True,
    require_directional_structure: bool = True,
    config: Optional["SwaptionPackageDetectionConfig"] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Detect swaption risk reversals with delta-hedge legs.

    Pattern (inter-dealer):
      - 4 trades
      - 3 distinct strikes (middle strike appears twice)
      - 2 distinct notionals (middle strike notional is smaller)

    Args:
        df: Classifications dataframe with swaption trades
        time_window_seconds: Max time gap between legs
        strike_tolerance: Absolute strike tolerance for grouping
        notional_tolerance_pct: Relative notional tolerance for grouping
        middle_notional_max_ratio: Max ratio of middle notional to wing notional
        require_same_expiration: Require same expiration_date across legs
        require_same_tenor: Require same tenor_years across legs
        require_same_forward: Require same forward_start_years across legs
        require_directional_structure: Require payer/receiver direction alignment
        config: Detection configuration (uses default if None)
        product_col: Column name for product type
        package_col: Column name for package type

    Returns:
        DataFrame with risk reversal annotations:
        - package_type: "RISK_REVERSAL"
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the package
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation string
        - package_legs_count: Always 4 for risk reversals
    """
    if df.empty:
        return df

    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    for col, default in [
        (package_col, "SWAPTION"),
        ("package_id", None),
        ("package_legs", None),
        ("package_confidence", None),
        ("package_reason", None),
        ("package_legs_count", None),
    ]:
        if col not in out.columns:
            out[col] = default

    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

    if config.platform_allowlist:
        candidate_mask &= out[config.platform_col].isin(config.platform_allowlist)
    if config.platform_blocklist:
        candidate_mask &= ~out[config.platform_col].isin(config.platform_blocklist)

    cand = out.loc[candidate_mask].copy()
    if cand.empty:
        return out

    cand["_t"] = _ensure_int64_epoch_seconds(cand[config.exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    strike_vals = pd.to_numeric(cand[config.strike_col], errors="coerce").to_numpy(dtype=np.float64)
    notional_vals = pd.to_numeric(cand[config.notional_col], errors="coerce").to_numpy(dtype=np.float64)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    trade_ids = cand[config.trade_id_col].astype(str).to_numpy()
    platforms = cand[config.platform_col].astype("string").to_numpy() if config.platform_col in cand.columns else None
    currencies = cand[config.currency_col].astype("string").to_numpy() if config.currency_col in cand.columns else None
    underliers = cand[config.underlier_col].astype("string").to_numpy() if config.underlier_col in cand.columns else None
    expirations = cand[config.expiration_col].astype("string").to_numpy() if config.expiration_col in cand.columns else None
    tenors = pd.to_numeric(cand[config.tenor_col], errors="coerce").to_numpy(dtype=np.float64) if config.tenor_col in cand.columns else None
    forwards = pd.to_numeric(cand[config.forward_col], errors="coerce").to_numpy(dtype=np.float64) if config.forward_col in cand.columns else None
    product_labels = cand[product_col].astype(str).to_numpy()

    matched = np.zeros(len(cand), dtype=bool)
    pkg_ids = np.full(len(cand), "", dtype=object)
    pkg_type = np.full(len(cand), "", dtype=object)
    pkg_legs = np.full(len(cand), None, dtype=object)
    pkg_conf = np.full(len(cand), 0.0, dtype=np.float64)
    pkg_reason = np.full(len(cand), "", dtype=object)
    pkg_legs_count = np.full(len(cand), 0, dtype=np.int32)

    def _cluster_values(values: np.ndarray, tol: float) -> List[List[int]]:
        clusters: List[List[int]] = []
        for idx, val in enumerate(values):
            placed = False
            for cluster in clusters:
                cvals = values[cluster]
                avg = float(np.nanmean(cvals))
                if avg <= 0:
                    continue
                if abs(val - avg) / avg <= tol:
                    cluster.append(idx)
                    placed = True
                    break
            if not placed:
                clusters.append([idx])
        return clusters

    def _strike_groups(strikes: np.ndarray) -> List[List[int]]:
        if strike_tolerance <= 0:
            groups: Dict[float, List[int]] = {}
            for idx, val in enumerate(strikes):
                groups.setdefault(val, []).append(idx)
            return list(groups.values())
        buckets: Dict[int, List[int]] = {}
        for idx, val in enumerate(strikes):
            bucket = int(np.round(val / strike_tolerance))
            buckets.setdefault(bucket, []).append(idx)
        return list(buckets.values())

    def _direction(label: str) -> int:
        upper = label.upper()
        if "PAYER" in upper or "CALL" in upper:
            return 1
        if "RECEIVER" in upper or "PUT" in upper:
            return -1
        return 0

    def _directional_ok(indices: List[int], ordered_groups: List[Tuple[float, List[int]]]) -> bool:
        if not require_directional_structure:
            return True

        # [FIX] Relaxed check: Simply ensure Low and High wings are opposite types.
        # This supports both (Low=Rec, High=Pay) AND (Low=Pay, High=Rec)

        low_group = ordered_groups[0][1]
        high_group = ordered_groups[2][1]

        # Directions of the wings
        low_dir = _direction(product_labels[indices[low_group[0]]])
        high_dir = _direction(product_labels[indices[high_group[0]]])

        # Must have valid directions (not unknown)
        if low_dir == 0 or high_dir == 0:
            return False

        # Wings must be opposite (one Payer, one Receiver)
        if low_dir == high_dir:
            return False

        # [FIX] Removed strict check on middle legs direction.
        # Reference script only requires 2 trades at ATM, not necessarily a perfect Payer/Receiver pair.

        return True

    def _is_risk_reversal(indices: List[int]) -> bool:
        strikes = strike_vals[indices]
        notionals = np.abs(notional_vals[indices])

        if np.any(np.isnan(strikes)) or np.any(np.isnan(notionals)):
            return False

        strike_groups = _strike_groups(strikes)
        # Classic 3-strike only for now (reference logic flow)
        if len(strike_groups) != 3:
            return False

        strike_counts = sorted(len(g) for g in strike_groups)
        if strike_counts != [1, 1, 2]:
            return False

        strike_levels = [float(np.nanmean(strikes[group])) for group in strike_groups]
        ordered = sorted(zip(strike_levels, strike_groups), key=lambda x: x[0])
        middle_group = ordered[1][1]

        # ATM must have 2 legs
        if len(middle_group) != 2:
            return False

        if not _directional_ok(indices, ordered):
            return False

        notional_groups = _cluster_values(notionals, notional_tolerance_pct)
        if len(notional_groups) != 2:
            return False

        group_means = [float(np.nanmean(notionals[group])) for group in notional_groups]
        low_idx = int(np.argmin(group_means))  # Small notional group index
        high_idx = int(np.argmax(group_means))  # Large notional group index
        low_mean = group_means[low_idx]
        high_mean = group_means[high_idx]

        if low_mean <= 0 or high_mean <= 0:
            return False

        # [FIX] Relaxed notional ratio check.
        # Reference script implies ATM < Wing is sufficient.
        # Enforcing <= 0.5 ratio kills valid trades like 80M ATM / 100M Wing.
        # We assume 0.95 to ensure they are distinct and smaller.
        if low_mean > high_mean * 0.95:
            return False

        low_group_indices = set(notional_groups[low_idx])
        middle_indices = {indices[idx] for idx in middle_group}

        # The Middle Strike trades MUST be the ones with the Smaller Notional
        if not middle_indices.issubset({indices[idx] for idx in low_group_indices}):
            return False

        notional_counts = sorted(len(g) for g in notional_groups)
        if notional_counts != [2, 2]:
            return False

        return True

    def _econ_key(i: int) -> Tuple[Any, ...]:
        parts: List[Any] = []
        if config.require_same_platform and platforms is not None:
            parts.append(platforms[i])
        if config.require_same_currency and currencies is not None:
            parts.append(currencies[i])
        if config.require_same_underlier and underliers is not None:
            parts.append(underliers[i])
        if require_same_expiration and expirations is not None:
            parts.append(expirations[i])
        if require_same_tenor and tenors is not None:
            parts.append(tenors[i])
        if require_same_forward and forwards is not None:
            parts.append(forwards[i])
        return tuple(parts)

    group_indices: Dict[Tuple[Any, ...], List[int]] = {}
    for i in range(len(cand)):
        key = _econ_key(i)
        group_indices.setdefault(key, []).append(i)

    for key, indices in group_indices.items():
        window: List[int] = []
        left = 0

        for idx in indices:
            while left < len(window) and (tsec[idx] - tsec[window[left]] > time_window_seconds):
                left += 1
            window = window[left:] + [idx]
            left = 0

            if len(window) < 4:
                continue

            for combo in itertools.combinations(window, 4):
                if any(matched[i] for i in combo):
                    continue
                if not _is_risk_reversal(list(combo)):
                    continue

                combo_list = list(combo)
                time_delta_max = float(np.max(tsec[combo_list]) - np.min(tsec[combo_list]))

                platform = key[0] if key else "UNKNOWN"
                pid = _compute_package_id(
                    [trade_ids[i] for i in combo_list],
                    str(platform),
                    int(tsec[combo_list[0]] // 30),
                    "RISK_REVERSAL",
                )

                confidence = 0.8
                if time_delta_max <= 5:
                    confidence += 0.1
                confidence = min(confidence, 1.0)

                strike_values = sorted({strike_vals[i] for i in combo_list})
                notional_values = sorted({abs(notional_vals[i]) for i in combo_list})
                reason = _build_package_reason(
                    platform=str(platform),
                    time_delta_max_seconds=time_delta_max,
                    vega_cluster_spread_pct=None,
                    premium_mode="RISK_REVERSAL",
                    num_legs=4,
                    identical_timestamps=(time_delta_max < 1),
                    extra_info=f"strikes={strike_values}; notionals={notional_values}",
                )

                legs_list = [str(trade_ids[i]) for i in combo_list]
                for i in combo_list:
                    matched[i] = True
                    pkg_ids[i] = pid
                    pkg_type[i] = "RISK_REVERSAL"
                    pkg_legs[i] = legs_list
                    pkg_conf[i] = confidence
                    pkg_reason[i] = reason
                    pkg_legs_count[i] = 4

                break

    res = pd.DataFrame(
        {
            config.trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
            "_pkg_conf": pkg_conf,
            "_pkg_reason": pkg_reason,
            "_pkg_legs_count": pkg_legs_count,
        }
    )

    out[config.trade_id_col] = out[config.trade_id_col].astype(str)
    out = out.merge(
        res[[config.trade_id_col, "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]],
        on=config.trade_id_col,
        how="left",
    )

    detected_mask = out["_pkg_id"].notna() & (out["_pkg_id"] != "")
    out.loc[detected_mask, package_col] = out.loc[detected_mask, "_pkg_type"]
    out.loc[detected_mask, "package_id"] = out.loc[detected_mask, "_pkg_id"]
    out.loc[detected_mask, "package_legs"] = out.loc[detected_mask, "_pkg_legs"]
    out.loc[detected_mask, "package_confidence"] = out.loc[detected_mask, "_pkg_conf"]
    out.loc[detected_mask, "package_reason"] = out.loc[detected_mask, "_pkg_reason"]
    out.loc[detected_mask, "package_legs_count"] = out.loc[detected_mask, "_pkg_legs_count"]

    temp_cols = ["_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]
    out.drop(columns=[c for c in temp_cols if c in out.columns], inplace=True, errors="ignore")

    return out


# =============================================================================
# Vertical Spread Detection
# =============================================================================


def detect_swaption_vertical_spreads_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 120,
    config: Optional["SwaptionPackageDetectionConfig"] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Detect vertical spreads (1x1, 1x2, 1x1.5, etc.) in swaption trades.

    A vertical spread consists of:
    - Same underlying tenor (same expiry and tail)
    - Different strikes (at least min_strike_width apart)
    - Same option type (both payers OR both receivers)
    - Notional ratio matches configured spread ratios

    Direction determination:
    - For PAYER spreads: long lower strike, short higher = BULL; opposite = BEAR
    - For RECEIVER spreads: long higher strike, short lower = BULL; opposite = BEAR

    Args:
        df: Classifications dataframe with swaption trades
        time_window_seconds: Max time gap between legs (default 120s)
        config: Detection configuration (uses default if None)
        product_col: Column name for product type
        package_col: Column name for package type

    Returns:
        DataFrame with vertical spread annotations:
        - package_type: "VERTICAL_SPREAD_1x1", "VERTICAL_SPREAD_1x2", etc.
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the spread
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation with direction (BULL/BEAR)
        - package_legs_count: Always 2 for vertical spreads
    """
    if df.empty:
        return df

    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    for col, default in [
        (package_col, "SWAPTION"),
        ("package_id", None),
        ("package_legs", None),
        ("package_confidence", None),
        ("package_reason", None),
        ("package_legs_count", None),
    ]:
        if col not in out.columns:
            out[col] = default

    # Filter to swaption candidates not already packaged
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

    if config.platform_allowlist:
        candidate_mask &= out[config.platform_col].isin(config.platform_allowlist)
    if config.platform_blocklist:
        candidate_mask &= ~out[config.platform_col].isin(config.platform_blocklist)

    cand = out.loc[candidate_mask].copy()
    if len(cand) < 2:
        return out

    cand["_t"] = _ensure_int64_epoch_seconds(cand[config.exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    # Extract arrays
    n = len(cand)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    strike_vals = pd.to_numeric(cand[config.strike_col], errors="coerce").to_numpy(dtype=np.float64)
    notional_vals = pd.to_numeric(cand[config.notional_col], errors="coerce").to_numpy(dtype=np.float64)
    tenor_vals = pd.to_numeric(cand[config.tenor_col], errors="coerce").to_numpy(dtype=np.float64)
    forward_vals = pd.to_numeric(cand[config.forward_col], errors="coerce").to_numpy(dtype=np.float64)
    trade_ids = cand[config.trade_id_col].astype(str).to_numpy()
    product_labels = cand[product_col].astype(str).to_numpy()
    platforms = cand[config.platform_col].astype("string").to_numpy() if config.platform_col in cand.columns else None
    currencies = cand[config.currency_col].astype("string").to_numpy() if config.currency_col in cand.columns else None
    underliers = cand[config.underlier_col].astype("string").to_numpy() if config.underlier_col in cand.columns else None
    expirations = cand[config.expiration_col].astype("string").to_numpy() if config.expiration_col in cand.columns else None
    pkg_ind = cand[config.package_indicator_col].to_numpy() if config.package_indicator_col in cand.columns else None

    # Output arrays
    matched = np.zeros(n, dtype=bool)
    pkg_ids = np.full(n, "", dtype=object)
    pkg_type = np.full(n, "", dtype=object)
    pkg_legs = np.full(n, None, dtype=object)
    pkg_conf = np.full(n, 0.0, dtype=np.float64)
    pkg_reason = np.full(n, "", dtype=object)
    pkg_legs_count = np.full(n, 0, dtype=np.int32)

    def _is_payer(label: str) -> bool:
        upper = label.upper()
        return "PAYER" in upper or "CALL" in upper

    def _is_receiver(label: str) -> bool:
        upper = label.upper()
        return "RECEIVER" in upper or "PUT" in upper

    def _same_option_type(i: int, j: int) -> bool:
        """Check if both trades are same type (both payer or both receiver)."""
        i_payer = _is_payer(product_labels[i])
        j_payer = _is_payer(product_labels[j])
        i_receiver = _is_receiver(product_labels[i])
        j_receiver = _is_receiver(product_labels[j])
        return (i_payer and j_payer) or (i_receiver and j_receiver)

    def _econ_ok(i: int, j: int) -> bool:
        """Check economic filters."""
        if config.require_same_platform and platforms is not None:
            if platforms[i] != platforms[j]:
                return False
        if config.require_same_currency and currencies is not None:
            if currencies[i] != currencies[j]:
                return False
        if config.require_same_underlier and underliers is not None:
            if underliers[i] != underliers[j]:
                return False
        return True

    def _same_tenor(i: int, j: int) -> bool:
        """Check if same underlying tenor (same expiry and tail)."""
        # Same expiration date
        if expirations is not None:
            if expirations[i] != expirations[j]:
                return False
        # Same underlying tenor (tail)
        if pd.notna(tenor_vals[i]) and pd.notna(tenor_vals[j]):
            if abs(tenor_vals[i] - tenor_vals[j]) > 0.01:
                return False
        # Same forward start (expiry)
        if pd.notna(forward_vals[i]) and pd.notna(forward_vals[j]):
            if abs(forward_vals[i] - forward_vals[j]) > 0.01:
                return False
        return True

    def _determine_direction(i: int, j: int) -> str:
        """
        Determine spread direction (BULL or BEAR).

        Convention:
        - PAYER: long lower strike = expecting rates to rise = BULL
        - RECEIVER: long higher strike = expecting rates to fall = BULL
        """
        # Determine which leg is long (larger notional) vs short
        if abs(notional_vals[i]) > abs(notional_vals[j]):
            long_idx, short_idx = i, j
        elif abs(notional_vals[j]) > abs(notional_vals[i]):
            long_idx, short_idx = j, i
        else:
            # Same notional - use the first one as "long"
            long_idx, short_idx = i, j

        long_strike = strike_vals[long_idx]
        short_strike = strike_vals[short_idx]
        is_payer = _is_payer(product_labels[long_idx])

        if is_payer:
            # Payer spread: long lower strike = BULL (expecting rates up)
            return "BULL" if long_strike < short_strike else "BEAR"
        else:
            # Receiver spread: long higher strike = BULL (expecting rates down)
            return "BULL" if long_strike > short_strike else "BEAR"

    def _match_spread_ratio(n1: float, n2: float) -> Optional[Tuple[str, float]]:
        """Check if notional ratio matches any configured spread ratio."""
        if n1 <= 0 or n2 <= 0:
            return None

        ratio = max(n1, n2) / min(n1, n2)

        for target_ratio, ratio_name, tolerance in config.spread_ratios:
            if abs(ratio - target_ratio) <= tolerance * target_ratio:
                return ratio_name, ratio

        return None

    # Sliding window search
    window: List[int] = []
    left = 0

    for idx in range(n):
        # Evict old trades
        while left < len(window) and (tsec[idx] - tsec[window[left]] > time_window_seconds):
            left += 1
        window = window[left:] + [idx]
        left = 0

        if matched[idx]:
            continue

        # Check pairs in window
        for other_idx in window[:-1]:  # Exclude current
            if matched[other_idx]:
                continue

            # Time check
            if abs(tsec[idx] - tsec[other_idx]) > time_window_seconds:
                continue

            # Must be same option type
            if not _same_option_type(idx, other_idx):
                continue

            # Must be same underlying tenor
            if not _same_tenor(idx, other_idx):
                continue

            # Economic filters
            if not _econ_ok(idx, other_idx):
                continue

            # Strike must be different (minimum width)
            strike_diff = abs(strike_vals[idx] - strike_vals[other_idx])
            if strike_diff < config.vertical_spread_min_strike_width:
                continue

            # Check notional ratio
            ratio_match = _match_spread_ratio(abs(notional_vals[idx]), abs(notional_vals[other_idx]))
            if ratio_match is None:
                continue

            ratio_name, actual_ratio = ratio_match

            # Found a vertical spread
            direction = _determine_direction(idx, other_idx)
            opt_type = "PAYER" if _is_payer(product_labels[idx]) else "RECEIVER"

            combo = [idx, other_idx]
            time_delta = abs(tsec[idx] - tsec[other_idx])
            strikes = sorted([strike_vals[idx], strike_vals[other_idx]])

            platform = platforms[idx] if platforms is not None else "UNKNOWN"
            pid = _compute_package_id(
                [trade_ids[i] for i in combo],
                str(platform),
                int(tsec[idx] // 30),
                f"VERTICAL_SPREAD_{ratio_name}",
            )

            # Confidence scoring
            confidence = 0.7  # Base confidence for vertical spreads
            if time_delta < 5:
                confidence += 0.1
            if pkg_ind is not None and any(pkg_ind[i] == True or pkg_ind[i] == "Y" for i in combo):
                confidence += 0.1
            confidence = min(confidence, 1.0)

            reason = _build_package_reason(
                platform=str(platform),
                time_delta_max_seconds=float(time_delta),
                vega_cluster_spread_pct=None,
                premium_mode=f"VERTICAL_{ratio_name}",
                num_legs=2,
                identical_timestamps=(time_delta < 1),
                extra_info=f"strikes={strikes[0]:.4f}/{strikes[1]:.4f}; " f"ratio={actual_ratio:.2f}; " f"type={opt_type}; " f"direction={direction}",
            )

            legs_list = [str(trade_ids[i]) for i in combo]
            pkg_type_str = f"VERTICAL_SPREAD_{ratio_name}"

            for i in combo:
                matched[i] = True
                pkg_ids[i] = pid
                pkg_type[i] = pkg_type_str
                pkg_legs[i] = legs_list
                pkg_conf[i] = confidence
                pkg_reason[i] = reason
                pkg_legs_count[i] = 2

            break  # Move to next trade

    # Build result and merge back
    res = pd.DataFrame(
        {
            config.trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
            "_pkg_conf": pkg_conf,
            "_pkg_reason": pkg_reason,
            "_pkg_legs_count": pkg_legs_count,
        }
    )

    out[config.trade_id_col] = out[config.trade_id_col].astype(str)
    out = out.merge(
        res[[config.trade_id_col, "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]],
        on=config.trade_id_col,
        how="left",
    )

    detected_mask = out["_pkg_id"].notna() & (out["_pkg_id"] != "")
    out.loc[detected_mask, package_col] = out.loc[detected_mask, "_pkg_type"]
    out.loc[detected_mask, "package_id"] = out.loc[detected_mask, "_pkg_id"]
    out.loc[detected_mask, "package_legs"] = out.loc[detected_mask, "_pkg_legs"]
    out.loc[detected_mask, "package_confidence"] = out.loc[detected_mask, "_pkg_conf"]
    out.loc[detected_mask, "package_reason"] = out.loc[detected_mask, "_pkg_reason"]
    out.loc[detected_mask, "package_legs_count"] = out.loc[detected_mask, "_pkg_legs_count"]

    temp_cols = ["_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]
    out.drop(columns=[c for c in temp_cols if c in out.columns], inplace=True, errors="ignore")

    return out


# =============================================================================
# Conditional Curve Trade Detection
# =============================================================================


def detect_swaption_conditional_curve_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 120,
    config: Optional["SwaptionPackageDetectionConfig"] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Detect conditional curve trades (same expiry, different tail maturities).

    A conditional curve trade consists of:
    - Same option expiration date
    - Different underlying tail maturities (e.g., 10Y vs 30Y)
    - Same option type (both payers OR both receivers)
    - Tail difference >= min_tail_diff_years

    Example: 1Yx10Y vs 1Yx30Y payer swaptions
    This is a conditional steepener/flattener on the long end.

    Direction determination:
    - CONDITIONAL_STEEPENER: Long short-tail, short long-tail (expecting curve to steepen)
    - CONDITIONAL_FLATTENER: Long long-tail, short short-tail (expecting curve to flatten)

    Args:
        df: Classifications dataframe with swaption trades
        time_window_seconds: Max time gap between legs (default 120s)
        config: Detection configuration (uses default if None)
        product_col: Column name for product type
        package_col: Column name for package type

    Returns:
        DataFrame with conditional curve annotations:
        - package_type: "CONDITIONAL_STEEPENER" or "CONDITIONAL_FLATTENER"
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the trade
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation
        - package_legs_count: Always 2 for conditional curve trades
    """
    if df.empty:
        return df

    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    for col, default in [
        (package_col, "SWAPTION"),
        ("package_id", None),
        ("package_legs", None),
        ("package_confidence", None),
        ("package_reason", None),
        ("package_legs_count", None),
    ]:
        if col not in out.columns:
            out[col] = default

    # Filter to swaption candidates not already packaged
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

    if config.platform_allowlist:
        candidate_mask &= out[config.platform_col].isin(config.platform_allowlist)
    if config.platform_blocklist:
        candidate_mask &= ~out[config.platform_col].isin(config.platform_blocklist)

    cand = out.loc[candidate_mask].copy()
    if len(cand) < 2:
        return out

    cand["_t"] = _ensure_int64_epoch_seconds(cand[config.exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    # Extract arrays
    n = len(cand)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    tenor_vals = pd.to_numeric(cand[config.tenor_col], errors="coerce").to_numpy(dtype=np.float64)
    forward_vals = pd.to_numeric(cand[config.forward_col], errors="coerce").to_numpy(dtype=np.float64)
    notional_vals = pd.to_numeric(cand[config.notional_col], errors="coerce").to_numpy(dtype=np.float64)
    trade_ids = cand[config.trade_id_col].astype(str).to_numpy()
    product_labels = cand[product_col].astype(str).to_numpy()
    platforms = cand[config.platform_col].astype("string").to_numpy() if config.platform_col in cand.columns else None
    currencies = cand[config.currency_col].astype("string").to_numpy() if config.currency_col in cand.columns else None
    underliers = cand[config.underlier_col].astype("string").to_numpy() if config.underlier_col in cand.columns else None
    expirations = cand[config.expiration_col].astype("string").to_numpy() if config.expiration_col in cand.columns else None
    pkg_ind = cand[config.package_indicator_col].to_numpy() if config.package_indicator_col in cand.columns else None

    # Output arrays
    matched = np.zeros(n, dtype=bool)
    pkg_ids = np.full(n, "", dtype=object)
    pkg_type = np.full(n, "", dtype=object)
    pkg_legs = np.full(n, None, dtype=object)
    pkg_conf = np.full(n, 0.0, dtype=np.float64)
    pkg_reason = np.full(n, "", dtype=object)
    pkg_legs_count = np.full(n, 0, dtype=np.int32)

    def _is_payer(label: str) -> bool:
        upper = label.upper()
        return "PAYER" in upper or "CALL" in upper

    def _is_receiver(label: str) -> bool:
        upper = label.upper()
        return "RECEIVER" in upper or "PUT" in upper

    def _same_option_type(i: int, j: int) -> bool:
        i_payer = _is_payer(product_labels[i])
        j_payer = _is_payer(product_labels[j])
        i_receiver = _is_receiver(product_labels[i])
        j_receiver = _is_receiver(product_labels[j])
        return (i_payer and j_payer) or (i_receiver and j_receiver)

    def _econ_ok(i: int, j: int) -> bool:
        if config.require_same_platform and platforms is not None:
            if platforms[i] != platforms[j]:
                return False
        if config.require_same_currency and currencies is not None:
            if currencies[i] != currencies[j]:
                return False
        if config.require_same_underlier and underliers is not None:
            if underliers[i] != underliers[j]:
                return False
        return True

    def _same_expiry(i: int, j: int) -> bool:
        """Check if same option expiration."""
        if expirations is not None:
            if expirations[i] != expirations[j]:
                return False
        # Also check forward_start_years as proxy
        if pd.notna(forward_vals[i]) and pd.notna(forward_vals[j]):
            if abs(forward_vals[i] - forward_vals[j]) > 0.05:  # ~2 weeks tolerance
                return False
        return True

    def _tail_diff_years(i: int, j: int) -> float:
        """Get the tail (tenor) difference in years."""
        if pd.isna(tenor_vals[i]) or pd.isna(tenor_vals[j]):
            return 0.0
        return abs(tenor_vals[i] - tenor_vals[j])

    def _determine_direction(i: int, j: int) -> str:
        """
        Determine trade direction.

        For same option type:
        - PAYER: long short-tail = steepener (expects short end to sell off more)
        - RECEIVER: long long-tail = flattener (expects long end to rally more)

        We determine "long" by larger notional.
        """
        # Which is short-tail vs long-tail
        if tenor_vals[i] < tenor_vals[j]:
            short_tail_idx, long_tail_idx = i, j
        else:
            short_tail_idx, long_tail_idx = j, i

        # Which has larger notional (assumed to be the "long" leg)
        short_tail_notional = abs(notional_vals[short_tail_idx])
        long_tail_notional = abs(notional_vals[long_tail_idx])

        is_payer = _is_payer(product_labels[i])

        if is_payer:
            # Payer: long short-tail = steepener
            if short_tail_notional >= long_tail_notional:
                return "CONDITIONAL_STEEPENER"
            else:
                return "CONDITIONAL_FLATTENER"
        else:
            # Receiver: long long-tail = flattener
            if long_tail_notional >= short_tail_notional:
                return "CONDITIONAL_FLATTENER"
            else:
                return "CONDITIONAL_STEEPENER"

    # Sliding window search
    window: List[int] = []
    left = 0

    for idx in range(n):
        while left < len(window) and (tsec[idx] - tsec[window[left]] > time_window_seconds):
            left += 1
        window = window[left:] + [idx]
        left = 0

        if matched[idx]:
            continue

        for other_idx in window[:-1]:
            if matched[other_idx]:
                continue

            if abs(tsec[idx] - tsec[other_idx]) > time_window_seconds:
                continue

            # Must be same option type
            if not _same_option_type(idx, other_idx):
                continue

            # Must be same expiry
            if not _same_expiry(idx, other_idx):
                continue

            # Must have different tails (at least min_tail_diff)
            tail_diff = _tail_diff_years(idx, other_idx)
            if tail_diff < config.conditional_curve_min_tail_diff_years:
                continue

            # Economic filters
            if not _econ_ok(idx, other_idx):
                continue

            # Found a conditional curve trade
            direction = _determine_direction(idx, other_idx)
            opt_type = "PAYER" if _is_payer(product_labels[idx]) else "RECEIVER"

            combo = [idx, other_idx]
            time_delta = abs(tsec[idx] - tsec[other_idx])

            # Build tenor descriptions
            short_tail = min(tenor_vals[idx], tenor_vals[other_idx])
            long_tail = max(tenor_vals[idx], tenor_vals[other_idx])
            expiry = forward_vals[idx] if pd.notna(forward_vals[idx]) else 0

            platform = platforms[idx] if platforms is not None else "UNKNOWN"
            pid = _compute_package_id(
                [trade_ids[i] for i in combo],
                str(platform),
                int(tsec[idx] // 30),
                direction,
            )

            # Confidence scoring
            confidence = 0.7
            if time_delta < 5:
                confidence += 0.1
            if pkg_ind is not None and any(pkg_ind[i] == True or pkg_ind[i] == "Y" for i in combo):
                confidence += 0.1
            confidence = min(confidence, 1.0)

            reason = _build_package_reason(
                platform=str(platform),
                time_delta_max_seconds=float(time_delta),
                vega_cluster_spread_pct=None,
                premium_mode="CONDITIONAL_CURVE",
                num_legs=2,
                identical_timestamps=(time_delta < 1),
                extra_info=f"expiry={expiry:.2f}Y; " f"tails={short_tail:.0f}Y/{long_tail:.0f}Y; " f"type={opt_type}; " f"direction={direction}",
            )

            legs_list = [str(trade_ids[i]) for i in combo]

            for i in combo:
                matched[i] = True
                pkg_ids[i] = pid
                pkg_type[i] = direction
                pkg_legs[i] = legs_list
                pkg_conf[i] = confidence
                pkg_reason[i] = reason
                pkg_legs_count[i] = 2

            break

    # Merge back
    res = pd.DataFrame(
        {
            config.trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
            "_pkg_conf": pkg_conf,
            "_pkg_reason": pkg_reason,
            "_pkg_legs_count": pkg_legs_count,
        }
    )

    out[config.trade_id_col] = out[config.trade_id_col].astype(str)
    out = out.merge(
        res[[config.trade_id_col, "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]],
        on=config.trade_id_col,
        how="left",
    )

    detected_mask = out["_pkg_id"].notna() & (out["_pkg_id"] != "")
    out.loc[detected_mask, package_col] = out.loc[detected_mask, "_pkg_type"]
    out.loc[detected_mask, "package_id"] = out.loc[detected_mask, "_pkg_id"]
    out.loc[detected_mask, "package_legs"] = out.loc[detected_mask, "_pkg_legs"]
    out.loc[detected_mask, "package_confidence"] = out.loc[detected_mask, "_pkg_conf"]
    out.loc[detected_mask, "package_reason"] = out.loc[detected_mask, "_pkg_reason"]
    out.loc[detected_mask, "package_legs_count"] = out.loc[detected_mask, "_pkg_legs_count"]

    temp_cols = ["_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]
    out.drop(columns=[c for c in temp_cols if c in out.columns], inplace=True, errors="ignore")

    return out


# =============================================================================
# Vega Curve Detection (Straddle-based)
# =============================================================================


def detect_swaption_vega_curve_df(
    df: pd.DataFrame,
    *,
    time_window_seconds: int = 300,
    config: Optional["SwaptionPackageDetectionConfig"] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
) -> pd.DataFrame:
    """
    Detect vega curve equivalent trades (vega-matched straddles across tenors).

    From trader context:
    - 4y5y (230mm k=4.025) vs 2y5y (470mm k=3.981) on BILT
    - Vega of the straddles is *very* similar
    - This is a customer-facing vega RV trade

    Patterns detected:
    - VEGA_EXPIRY_SPREAD: Same tail, different expiry (e.g., 9Mx10Y vs 1Yx10Y)
    - VEGA_TAIL_SPREAD: Same expiry, different tail (e.g., 1Yx5Y vs 1Yx10Y)
    - VEGA_DIAGONAL: Both expiry and tail differ

    Detection requires pre-existing straddles (payer+receiver pairs).

    Args:
        df: Classifications dataframe with swaption trades (should have straddles detected)
        time_window_seconds: Max time gap between straddles (default 300s = 5 min)
        config: Detection configuration (uses default if None)
        product_col: Column name for product type
        package_col: Column name for package type

    Returns:
        DataFrame with vega curve annotations on the straddle legs:
        - vega_curve_type: "VEGA_EXPIRY_SPREAD", "VEGA_TAIL_SPREAD", "VEGA_DIAGONAL"
        - vega_curve_id: Links the two straddles
        - vega_curve_legs: List of all trade IDs across both straddles
    """
    if df.empty:
        return df

    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    # Initialize vega curve columns
    if "vega_curve_type" not in out.columns:
        out["vega_curve_type"] = None
    if "vega_curve_id" not in out.columns:
        out["vega_curve_id"] = None
    if "vega_curve_legs" not in out.columns:
        out["vega_curve_legs"] = None

    # Find existing straddles
    straddle_mask = out[package_col] == "STRADDLE"
    if not straddle_mask.any():
        return out

    straddles = out.loc[straddle_mask].copy()

    # Group by package_id to get straddle characteristics
    straddle_groups = (
        straddles.groupby("package_id")
        .agg(
            {
                config.exec_col: "first",
                config.platform_col: "first",
                config.currency_col: "first",
                config.tenor_col: "first",  # Tail
                config.forward_col: "first",  # Expiry
                config.notional_col: "sum",  # Total notional
                config.premium_col: "sum",  # Total premium (vega proxy)
                config.trade_id_col: list,
            }
        )
        .reset_index()
    )

    if len(straddle_groups) < 2:
        return out

    # Add timestamp for sorting
    straddle_groups["_t"] = _ensure_int64_epoch_seconds(straddle_groups[config.exec_col])
    straddle_groups.sort_values("_t", inplace=True, kind="mergesort")

    n_straddles = len(straddle_groups)
    matched_straddles: Set[str] = set()

    for i in range(n_straddles):
        pid_i = straddle_groups.iloc[i]["package_id"]
        if pid_i in matched_straddles:
            continue

        t_i = straddle_groups.iloc[i]["_t"]
        plat_i = straddle_groups.iloc[i][config.platform_col]
        ccy_i = straddle_groups.iloc[i][config.currency_col]
        tail_i = straddle_groups.iloc[i][config.tenor_col]
        expiry_i = straddle_groups.iloc[i][config.forward_col]
        vega_i = abs(straddle_groups.iloc[i][config.premium_col])  # Premium as vega proxy
        trades_i = straddle_groups.iloc[i][config.trade_id_col]

        if vega_i <= 0:
            continue

        for j in range(i + 1, n_straddles):
            pid_j = straddle_groups.iloc[j]["package_id"]
            if pid_j in matched_straddles:
                continue

            t_j = straddle_groups.iloc[j]["_t"]

            # Time window check
            if abs(t_i - t_j) > time_window_seconds:
                continue

            plat_j = straddle_groups.iloc[j][config.platform_col]
            ccy_j = straddle_groups.iloc[j][config.currency_col]
            tail_j = straddle_groups.iloc[j][config.tenor_col]
            expiry_j = straddle_groups.iloc[j][config.forward_col]
            vega_j = abs(straddle_groups.iloc[j][config.premium_col])
            trades_j = straddle_groups.iloc[j][config.trade_id_col]

            # Platform and currency match
            if config.require_same_platform and plat_i != plat_j:
                continue
            if config.require_same_currency and ccy_i != ccy_j:
                continue

            # Vega similarity check
            if vega_j <= 0:
                continue
            avg_vega = 0.5 * (vega_i + vega_j)
            vega_diff = abs(vega_i - vega_j) / avg_vega
            if vega_diff > config.vega_curve_tolerance_pct:
                continue

            # Determine curve type based on expiry/tail differences
            tail_diff = abs(tail_i - tail_j) if pd.notna(tail_i) and pd.notna(tail_j) else 0
            expiry_diff = abs(expiry_i - expiry_j) if pd.notna(expiry_i) and pd.notna(expiry_j) else 0

            same_tail = tail_diff < 0.1  # Within ~1 month
            same_expiry = expiry_diff < 0.1

            if same_tail and not same_expiry and expiry_diff >= config.vega_curve_min_expiry_diff_years:
                curve_type = "VEGA_EXPIRY_SPREAD"
            elif same_expiry and not same_tail and tail_diff >= config.vega_curve_min_tail_diff_years:
                curve_type = "VEGA_TAIL_SPREAD"
            elif not same_tail and not same_expiry:
                if expiry_diff >= config.vega_curve_min_expiry_diff_years or tail_diff >= config.vega_curve_min_tail_diff_years:
                    curve_type = "VEGA_DIAGONAL"
                else:
                    continue  # Not significant enough difference
            else:
                continue  # Same tenor, not a curve trade

            # Found a vega curve trade
            matched_straddles.add(pid_i)
            matched_straddles.add(pid_j)

            curve_id = _compute_package_id(
                [pid_i, pid_j],
                str(plat_i),
                int(t_i // 30),
                curve_type,
            )

            all_trades = list(trades_i) + list(trades_j)

            # Annotate all legs
            for pid in [pid_i, pid_j]:
                mask = out["package_id"] == pid
                out.loc[mask, "vega_curve_type"] = curve_type
                out.loc[mask, "vega_curve_id"] = curve_id
                out.loc[mask, "vega_curve_legs"] = pd.Series([all_trades] * mask.sum(), index=out.index[mask])

            break  # Move to next straddle

    return out


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
    premium_results = cand.apply(lambda row: _extract_effective_premium(row, config), axis=1)
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
    plat = cand[config.platform_col].astype("string").to_numpy() if (config.require_same_platform and config.platform_col in cand.columns) else None
    ccy = cand[config.currency_col].astype("string").to_numpy() if (config.require_same_currency and config.currency_col in cand.columns) else None
    und = cand[config.underlier_col].astype("string").to_numpy() if (config.require_same_underlier and config.underlier_col in cand.columns) else None

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
            vega_spread_pct = 100.0 * (np.nanmax(package_vegas) - np.nanmin(package_vegas)) / max(vega_mean, 1e-12) if vega_mean > 0 else 0.0

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
    res = pd.DataFrame(
        {
            config.trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
            "_pkg_conf": pkg_conf,
            "_pkg_reason": pkg_reason,
            "_pkg_legs_count": pkg_legs_count,
        }
    )

    # Also include effective premium columns from cand
    cand_result = cand[[config.trade_id_col, "_eff_premium", "_eff_premium_src"]].copy()
    cand_result[config.trade_id_col] = cand_result[config.trade_id_col].astype(str)
    res = res.merge(cand_result, on=config.trade_id_col, how="left")

    # Merge back to output
    out[config.trade_id_col] = out[config.trade_id_col].astype(str)
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
    has_package = out["package_id"].notna() & out[package_col].isin(swaption_package_types)

    if not has_package.any():
        return out

    # Get unique packages with their characteristics
    packaged_df = out.loc[has_package].copy()

    # Aggregate package info
    package_info = packaged_df.groupby("package_id").agg(
        {
            config.exec_col: ["min", "max"],
            config.platform_col: "first",
            config.currency_col: "first",
            "package_confidence": "first",
        }
    )
    package_info.columns = ["time_min", "time_max", "platform", "currency", "confidence"]
    package_info["time_mid"] = (
        pd.to_datetime(package_info["time_min"]).astype(np.int64) // 10**9 + pd.to_datetime(package_info["time_max"]).astype(np.int64) // 10**9
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
    product_col: str = "product_type",
    package_col: str = "package_type",
    # Detection flags
    detect_risk_reversals: bool = True,
    detect_straddles: bool = True,
    detect_vertical_spreads: bool = True,
    detect_conditional_curve: bool = True,
    detect_vega_curve: bool = True,
    # Straddle parameters
    straddle_timestamp_tolerance: datetime.timedelta = datetime.timedelta(seconds=0),
    straddle_strike_tolerance: float = 0.0000,
    straddle_notional_tolerance_pct: float = 0.00,
    # Risk reversal parameters
    risk_reversal_time_window_seconds: int = 60,
    risk_reversal_strike_tolerance: float = 0.0001,
    risk_reversal_notional_tolerance_pct: float = 0.05,
    risk_reversal_middle_notional_max_ratio: float = 0.5,
    risk_reversal_require_same_expiration: bool = True,
    risk_reversal_require_same_tenor: bool = True,
    risk_reversal_require_same_forward: bool = True,
    risk_reversal_require_directional_structure: bool = True,
    # Vertical spread parameters
    vertical_spread_time_window_seconds: int = 120,
    # Conditional curve parameters
    conditional_curve_time_window_seconds: int = 120,
    # Vega curve parameters
    vega_curve_time_window_seconds: int = 300,
) -> pd.DataFrame:
    """
    Combined detection and linking of swaption packages.

    Convenience function that runs all detection algorithms in sequence.
    Each algorithm only processes trades not already assigned to a package.

    Detection order (priority):
    1. Risk reversals (4 legs / 3 strikes / 2 notionals) - IDB structures
    2. Straddles (payer + receiver with same strike/expiry/tenor)
    3. Vertical spreads (1x1, 1x2, 1x1.5, etc. - same tenor, different strikes)
    4. Conditional curve trades (same expiry, different tails)
    5. Vega curve trades (vega-matched straddles across tenors)
    6. Package linking (link related packages by time/vega)

    Args:
        df: Classifications dataframe with swaption trades
        config: Detection configuration
        product_col: Column name for product type
        package_col: Column name for package type
        detect_risk_reversals: Whether to detect risk reversals (default True)
        detect_straddles: Whether to detect straddles (default True)
        detect_vertical_spreads: Whether to detect vertical spreads (default True)
        detect_conditional_curve: Whether to detect conditional curve trades (default True)
        detect_vega_curve: Whether to detect vega curve trades (default True)
        straddle_timestamp_tolerance: Max time between payer and receiver legs
        straddle_strike_tolerance: Absolute tolerance for strike matching
        straddle_notional_tolerance_pct: Percentage tolerance for notional matching
        risk_reversal_time_window_seconds: Max time gap between risk reversal legs
        risk_reversal_strike_tolerance: Absolute strike tolerance for risk reversal matching
        risk_reversal_notional_tolerance_pct: Relative notional tolerance for grouping
        risk_reversal_middle_notional_max_ratio: Max ratio of middle to wing notional
        risk_reversal_require_same_expiration: Require same expiration_date across legs
        risk_reversal_require_same_tenor: Require same tenor_years across legs
        risk_reversal_require_same_forward: Require same forward_start_years across legs
        risk_reversal_require_directional_structure: Require payer/receiver alignment
        vertical_spread_time_window_seconds: Max time gap between vertical spread legs
        conditional_curve_time_window_seconds: Max time gap between conditional curve legs
        vega_curve_time_window_seconds: Max time gap between vega curve straddles

    Returns:
        DataFrame with full package annotations including:
        - package_type: Type of package detected
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the package
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation string
        - package_legs_count: Number of legs in the package
        - vega_curve_type: For vega curve trades, the specific type
        - vega_curve_id: ID linking vega curve straddles
        - vega_curve_legs: All trade IDs in vega curve
    """
    out = df.copy()

    # temp = out.copy()
    # temp["execution_timestamp"] = temp["execution_timestamp"].astype(str)
    # temp.to_excel("temp_out.xlsx")

    # Phase 1: Detect risk reversals first (highest priority - IDB structures)
    if detect_risk_reversals:
        out = detect_swaption_risk_reversals_df(
            out,
            time_window_seconds=risk_reversal_time_window_seconds,
            strike_tolerance=risk_reversal_strike_tolerance,
            notional_tolerance_pct=risk_reversal_notional_tolerance_pct,
            middle_notional_max_ratio=risk_reversal_middle_notional_max_ratio,
            require_same_expiration=risk_reversal_require_same_expiration,
            require_same_tenor=risk_reversal_require_same_tenor,
            require_same_forward=risk_reversal_require_same_forward,
            require_directional_structure=risk_reversal_require_directional_structure,
            config=config,
            product_col=product_col,
            package_col=package_col,
        )

    # Phase 2: Detect straddles
    if detect_straddles:
        out = detect_swaption_straddles_df(
            out,
            straddle_timestamp_tolerance=straddle_timestamp_tolerance,
            strike_tolerance=straddle_strike_tolerance,
            notional_tolerance_pct=straddle_notional_tolerance_pct,
            config=config,
            product_col=product_col,
            package_col=package_col,
        )

    # # Phase 3: Detect vertical spreads (1x1, 1x2, etc.)
    # if detect_vertical_spreads:
    #     out = detect_swaption_vertical_spreads_df(
    #         out,
    #         time_window_seconds=vertical_spread_time_window_seconds,
    #         config=config,
    #         product_col=product_col,
    #         package_col=package_col,
    #     )

    # # Phase 4: Detect conditional curve trades (same expiry, different tails)
    # if detect_conditional_curve:
    #     out = detect_swaption_conditional_curve_df(
    #         out,
    #         time_window_seconds=conditional_curve_time_window_seconds,
    #         config=config,
    #         product_col=product_col,
    #         package_col=package_col,
    #     )

    # # Phase 5: Detect vega curve trades (requires straddles to be detected first)
    # if detect_vega_curve and detect_straddles:
    #     out = detect_swaption_vega_curve_df(
    #         out,
    #         time_window_seconds=vega_curve_time_window_seconds,
    #         config=config,
    #         product_col=product_col,
    #         package_col=package_col,
    #     )

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
