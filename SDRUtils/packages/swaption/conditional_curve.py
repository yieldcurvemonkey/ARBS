"""
Conditional curve trade detection for swaption packages.

Detects conditional curve trades: Same expiry, different tail maturities.
Example: 1Yx10Y vs 1Yx30Y payer swaptions (conditional steepener/flattener).
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.swaption.utils import (
    compute_package_id,
    build_package_reason,
    ensure_package_columns,
    is_payer,
    is_receiver,
)


def detect_conditional_curve(
    df: pd.DataFrame,
    *,
    # Time window parameters
    time_window_seconds: int = 120,
    # Conditional curve parameters
    min_tail_diff_years: float = 5.0,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    underlier_col: str = "upi_underlier_name",
    trade_id_col: str = "trade_id",
    expiration_col: str = "expiration_date",
    tenor_col: str = "tenor_years",
    forward_col: str = "forward_start_years",
    notional_col: str = "notional",
    package_indicator_col: str = "package_indicator",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    require_same_underlier: bool = False,
    # Platform filters
    platform_allowlist: Optional[List[str]] = None,
    platform_blocklist: Optional[List[str]] = None,
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
        min_tail_diff_years: Minimum tail difference in years
        product_col: Column name for product type
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        underlier_col: Column name for underlier
        trade_id_col: Column name for trade ID
        expiration_col: Column name for expiration date
        tenor_col: Column name for tenor years
        forward_col: Column name for forward start years
        notional_col: Column name for notional
        package_indicator_col: Column name for package indicator
        require_same_platform: Require same platform for matching
        require_same_currency: Require same currency for matching
        require_same_underlier: Require same underlier for matching
        platform_allowlist: If set, only these platforms are considered
        platform_blocklist: If set, these platforms are excluded

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

    out = ensure_package_columns(df, package_col=package_col)

    # Filter to swaption candidates not already packaged
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

    if platform_allowlist:
        candidate_mask &= out[platform_col].isin(platform_allowlist)
    if platform_blocklist:
        candidate_mask &= ~out[platform_col].isin(platform_blocklist)

    cand = out.loc[candidate_mask].copy()
    if len(cand) < 2:
        return out

    cand["_t"] = _ensure_int64_epoch_seconds(cand[exec_col])
    cand.sort_values("_t", inplace=True, kind="mergesort")

    # Extract arrays
    n = len(cand)
    tsec = cand["_t"].to_numpy(dtype=np.int64)
    tenor_vals = pd.to_numeric(cand[tenor_col], errors="coerce").to_numpy(dtype=np.float64)
    forward_vals = pd.to_numeric(cand[forward_col], errors="coerce").to_numpy(dtype=np.float64)
    notional_vals = pd.to_numeric(cand[notional_col], errors="coerce").to_numpy(dtype=np.float64)
    trade_ids = cand[trade_id_col].astype(str).to_numpy()
    product_labels = cand[product_col].astype(str).to_numpy()
    platforms = cand[platform_col].astype("string").to_numpy() if platform_col in cand.columns else None
    currencies = cand[currency_col].astype("string").to_numpy() if currency_col in cand.columns else None
    underliers = cand[underlier_col].astype("string").to_numpy() if underlier_col in cand.columns else None
    expirations = cand[expiration_col].astype("string").to_numpy() if expiration_col in cand.columns else None
    pkg_ind = cand[package_indicator_col].to_numpy() if package_indicator_col in cand.columns else None

    # Output arrays
    matched = np.zeros(n, dtype=bool)
    pkg_ids = np.full(n, "", dtype=object)
    pkg_type = np.full(n, "", dtype=object)
    pkg_legs = np.full(n, None, dtype=object)
    pkg_conf = np.full(n, 0.0, dtype=np.float64)
    pkg_reason = np.full(n, "", dtype=object)
    pkg_legs_count = np.full(n, 0, dtype=np.int32)

    def _same_option_type(i: int, j: int) -> bool:
        i_payer = is_payer(product_labels[i])
        j_payer = is_payer(product_labels[j])
        i_receiver = is_receiver(product_labels[i])
        j_receiver = is_receiver(product_labels[j])
        return (i_payer and j_payer) or (i_receiver and j_receiver)

    def _econ_ok(i: int, j: int) -> bool:
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

        is_payer_trade = is_payer(product_labels[i])

        if is_payer_trade:
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
            if tail_diff < min_tail_diff_years:
                continue

            # Economic filters
            if not _econ_ok(idx, other_idx):
                continue

            # Found a conditional curve trade
            direction = _determine_direction(idx, other_idx)
            opt_type = "PAYER" if is_payer(product_labels[idx]) else "RECEIVER"

            combo = [idx, other_idx]
            time_delta = abs(tsec[idx] - tsec[other_idx])

            # Build tenor descriptions
            short_tail = min(tenor_vals[idx], tenor_vals[other_idx])
            long_tail = max(tenor_vals[idx], tenor_vals[other_idx])
            expiry = forward_vals[idx] if pd.notna(forward_vals[idx]) else 0

            platform = platforms[idx] if platforms is not None else "UNKNOWN"
            pid = compute_package_id(
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

            reason = build_package_reason(
                platform=str(platform),
                time_delta_max_seconds=float(time_delta),
                vega_cluster_spread_pct=None,
                premium_mode="CONDITIONAL_CURVE",
                num_legs=2,
                identical_timestamps=(time_delta < 1),
                extra_info=f"expiry={expiry:.2f}Y; "
                          f"tails={short_tail:.0f}Y/{long_tail:.0f}Y; "
                          f"type={opt_type}; "
                          f"direction={direction}",
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
            trade_id_col: trade_ids,
            "_pkg_type": pkg_type,
            "_pkg_id": pkg_ids,
            "_pkg_legs": pkg_legs,
            "_pkg_conf": pkg_conf,
            "_pkg_reason": pkg_reason,
            "_pkg_legs_count": pkg_legs_count,
        }
    )

    out[trade_id_col] = out[trade_id_col].astype(str)
    out = out.merge(
        res[[trade_id_col, "_pkg_type", "_pkg_id", "_pkg_legs", "_pkg_conf", "_pkg_reason", "_pkg_legs_count"]],
        on=trade_id_col,
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
