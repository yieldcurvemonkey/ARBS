"""
Vega-bucketed package detection for swaption packages.

Detects packages based on vega bucketing and time proximity.
Types: VEGA_BUCKETED_PACKAGE, IMPLIED_PACKAGE_SAME_TIMESTAMP.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.swaption.utils import (
    vega_bucket,
    time_bucket,
    safe_float,
    compute_package_id,
    build_package_reason,
    estimate_swaption_vega,
    extract_effective_premium,
    ensure_package_columns,
)


# Default confidence weights
DEFAULT_CONFIDENCE_WEIGHTS: Dict[str, float] = {
    "identical_timestamp": 0.3,
    "vega_similarity": 0.25,
    "package_indicator": 0.15,
    "premium_anomaly": 0.15,  # Premium zero but package_price non-zero
    "platform_match": 0.15,
}


def detect_vega_bucketed_packages(
    df: pd.DataFrame,
    *,
    # Time window parameters
    time_window_seconds: int = 300,
    # Vega parameters
    vega_tolerance_pct: float = 0.00,
    min_legs: int = 2,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    underlier_col: str = "upi_underlier_name",
    trade_id_col: str = "trade_id",
    vega_col: str = "estimated_vega",
    notional_col: str = "notional",
    tenor_col: str = "tenor_years",
    forward_col: str = "forward_start_years",
    premium_col: str = "premium",
    package_price_col: str = "package_transaction_price",
    package_indicator_col: str = "package_indicator",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    require_same_underlier: bool = False,
    # Price field handling
    price_field_mode: str = "both",
    # Confidence weights
    confidence_weights: Optional[Dict[str, float]] = None,
    # Platform filters
    platform_allowlist: Optional[List[str]] = None,
    platform_blocklist: Optional[List[str]] = None,
    # Custom vega estimator
    vega_estimator: Optional[Callable[[pd.Series], float]] = None,
) -> pd.DataFrame:
    """
    Detect swaption packages using vega bucketing and time proximity.

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
        time_window_seconds: Time window for grouping trades
        vega_tolerance_pct: Tolerance for vega matching (as fraction)
        min_legs: Minimum legs for a package
        product_col: Column name for product type
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        underlier_col: Column name for underlier
        trade_id_col: Column name for trade ID
        vega_col: Column name for pre-computed vega
        notional_col: Column name for notional
        tenor_col: Column name for tenor years
        forward_col: Column name for forward start years
        premium_col: Column name for premium
        package_price_col: Column name for package price
        package_indicator_col: Column name for package indicator
        require_same_platform: Require same platform for matching
        require_same_currency: Require same currency for matching
        require_same_underlier: Require same underlier for matching
        price_field_mode: One of "prefer_premium", "prefer_package_price", "both"
        confidence_weights: Weights for confidence scoring factors
        platform_allowlist: If set, only these platforms are considered
        platform_blocklist: If set, these platforms are excluded
        vega_estimator: Optional custom vega estimation function

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

    if confidence_weights is None:
        confidence_weights = DEFAULT_CONFIDENCE_WEIGHTS

    out = ensure_package_columns(df, package_col=package_col)

    # Determine vega estimator
    if vega_estimator is None:
        def _default_vega_estimator(row: pd.Series) -> float:
            return estimate_swaption_vega(
                row,
                vega_col=vega_col,
                notional_col=notional_col,
                tenor_col=tenor_col,
                forward_col=forward_col,
            )
        vega_estimator = _default_vega_estimator

    # Filter to swaption candidates not already in a package
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")

    candidate_mask = is_swaption & not_packaged

    # Apply platform filters
    if platform_allowlist:
        platform_ok = out[platform_col].isin(platform_allowlist)
        candidate_mask &= platform_ok
    if platform_blocklist:
        platform_blocked = out[platform_col].isin(platform_blocklist)
        candidate_mask &= ~platform_blocked

    # Extract candidate indices
    cand_idx = out.index[candidate_mask].tolist()
    if len(cand_idx) < min_legs:
        return out

    # Build candidate arrays for fast processing
    cand = out.loc[cand_idx].copy()

    # Compute vega for all candidates
    cand["_vega"] = cand.apply(vega_estimator, axis=1)

    # Extract effective premium
    premium_results = cand.apply(
        lambda row: extract_effective_premium(
            row,
            premium_col=premium_col,
            package_price_col=package_price_col,
            price_field_mode=price_field_mode,
        ),
        axis=1
    )
    cand["_eff_premium"] = premium_results.apply(lambda x: x[0])
    cand["_eff_premium_src"] = premium_results.apply(lambda x: x[1])

    # Ensure execution timestamp is epoch seconds
    cand["_t"] = _ensure_int64_epoch_seconds(cand[exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    # Convert to numpy arrays for fast processing
    n = len(cand)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    vega = cand["_vega"].to_numpy(dtype=np.float64)
    trade_ids = cand[trade_id_col].astype(str).to_numpy()

    # Precompute economic key arrays
    plat = cand[platform_col].astype("string").to_numpy() if (require_same_platform and platform_col in cand.columns) else None
    ccy = cand[currency_col].astype("string").to_numpy() if (require_same_currency and currency_col in cand.columns) else None
    und = cand[underlier_col].astype("string").to_numpy() if (require_same_underlier and underlier_col in cand.columns) else None

    # Package indicator and premium arrays for confidence scoring
    pkg_ind = cand[package_indicator_col].to_numpy() if package_indicator_col in cand.columns else None
    eff_prem = cand["_eff_premium"].to_numpy(dtype=np.float64)
    eff_prem_src = cand["_eff_premium_src"].to_numpy()

    # Bucket arrays
    vega_buckets = vega_bucket(vega, vega_tolerance_pct) if vega_tolerance_pct > 0 else np.zeros(n, dtype=np.int32)
    time_buckets = time_bucket(tsec, bucket_seconds=30)

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
        while left < n and (curr_t - tsec[left] > time_window_seconds):
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
        weights = confidence_weights

        # Identical timestamp bonus
        if len(set(tsec[indices])) == 1:
            conf += weights.get("identical_timestamp", 0.3)

        # Vega similarity bonus
        vegas = vega[indices]
        if len(vegas) > 1 and np.nanmean(vegas) > 0:
            vega_spread = (np.nanmax(vegas) - np.nanmin(vegas)) / np.nanmean(vegas)
            if vega_spread < vega_tolerance_pct:
                conf += weights.get("vega_similarity", 0.25)
            elif vega_spread < vega_tolerance_pct * 2:
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
        tb_i = int(time_buckets[i])
        vb_i = int(vega_buckets[i])

        # Find candidate matches
        candidates: List[int] = []

        # Look in neighboring vega buckets
        for dvb in (-1, 0, 1):
            # Look in neighboring time buckets (within window)
            for dtb in range(-int(time_window_seconds / 30) - 1, int(time_window_seconds / 30) + 2):
                key = (tb_i + dtb, vb_i + dvb, plat_i)
                candidates.extend(_active_list(key))

        # Filter candidates by economic constraints and time window
        valid_candidates = [i]  # Include current trade
        for j in candidates:
            if j == i or matched[j]:
                continue
            if abs(tsec[i] - tsec[j]) > time_window_seconds:
                continue
            if not _econ_ok(i, j):
                continue

            # Check vega similarity
            if pd.isna(vega[j]) or vega[j] <= 0:
                continue
            avg_vega = 0.5 * (vega[i] + vega[j])
            vega_rel = abs(vega[i] - vega[j]) / max(avg_vega, 1e-12)
            if vega_rel > vega_tolerance_pct:
                continue

            valid_candidates.append(j)

        # Check for package
        if len(valid_candidates) >= min_legs:
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
            pid = compute_package_id(
                [trade_ids[idx] for idx in valid_candidates],
                plat_i,
                tb_i,
                ptype,
            )

            # Generate reason
            reason = build_package_reason(
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
            trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
            "_pkg_conf": pkg_conf,
            "_pkg_reason": pkg_reason,
            "_pkg_legs_count": pkg_legs_count,
        }
    )

    # Also include effective premium columns from cand
    cand_result = cand[[trade_id_col, "_eff_premium", "_eff_premium_src"]].copy()
    cand_result[trade_id_col] = cand_result[trade_id_col].astype(str)
    res = res.merge(cand_result, on=trade_id_col, how="left")

    # Merge back to output
    out[trade_id_col] = out[trade_id_col].astype(str)
    out = out.merge(
        res[[trade_id_col, "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count", "_eff_premium", "_eff_premium_src"]],
        on=trade_id_col,
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
