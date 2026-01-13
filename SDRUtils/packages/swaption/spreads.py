"""
Vertical spread detection for swaption packages.

Detects vertical spreads: Same tenor, different strikes, same option type (1x1, 1x2, etc.).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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


# Default spread ratios: (ratio, name, tolerance)
DEFAULT_SPREAD_RATIOS: List[Tuple[float, str, float]] = [
    (1.0, "1x1", 0.05),   # 1x1 spread (same notional)
    (1.5, "1x1.5", 0.05), # 1x1.5 spread
    (2.0, "1x2", 0.10),   # 1x2 spread
    (2.5, "1x2.5", 0.10), # 1x2.5 spread
    (3.0, "1x3", 0.10),   # 1x3 spread
]


def detect_vertical_spreads(
    df: pd.DataFrame,
    *,
    # Time window parameters
    time_window_seconds: int = 120,
    # Spread parameters
    spread_ratios: Optional[List[Tuple[float, str, float]]] = None,
    min_strike_width: float = 0.001,  # 10bps minimum
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    underlier_col: str = "upi_underlier_name",
    trade_id_col: str = "trade_id",
    strike_col: str = "strike",
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
        spread_ratios: List of (ratio, name, tolerance) tuples for notional matching
        min_strike_width: Minimum strike difference in absolute terms
        product_col: Column name for product type
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        underlier_col: Column name for underlier
        trade_id_col: Column name for trade ID
        strike_col: Column name for strike
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

    if spread_ratios is None:
        spread_ratios = DEFAULT_SPREAD_RATIOS

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
    strike_vals = pd.to_numeric(cand[strike_col], errors="coerce").to_numpy(dtype=np.float64)
    notional_vals = pd.to_numeric(cand[notional_col], errors="coerce").to_numpy(dtype=np.float64)
    tenor_vals = pd.to_numeric(cand[tenor_col], errors="coerce").to_numpy(dtype=np.float64)
    forward_vals = pd.to_numeric(cand[forward_col], errors="coerce").to_numpy(dtype=np.float64)
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
        """Check if both trades are same type (both payer or both receiver)."""
        i_payer = is_payer(product_labels[i])
        j_payer = is_payer(product_labels[j])
        i_receiver = is_receiver(product_labels[i])
        j_receiver = is_receiver(product_labels[j])
        return (i_payer and j_payer) or (i_receiver and j_receiver)

    def _econ_ok(i: int, j: int) -> bool:
        """Check economic filters."""
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
        except:
            return False

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
        is_payer_spread = is_payer(product_labels[long_idx])

        if is_payer_spread:
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

        for target_ratio, ratio_name, tolerance in spread_ratios:
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
            if strike_diff < min_strike_width:
                continue

            # Check notional ratio
            ratio_match = _match_spread_ratio(abs(notional_vals[idx]), abs(notional_vals[other_idx]))
            if ratio_match is None:
                continue

            ratio_name, actual_ratio = ratio_match

            # Found a vertical spread
            direction = _determine_direction(idx, other_idx)
            opt_type = "PAYER" if is_payer(product_labels[idx]) else "RECEIVER"

            combo = [idx, other_idx]
            time_delta = abs(tsec[idx] - tsec[other_idx])
            strikes = sorted([strike_vals[idx], strike_vals[other_idx]])

            platform = platforms[idx] if platforms is not None else "UNKNOWN"
            pid = compute_package_id(
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

            reason = build_package_reason(
                platform=str(platform),
                time_delta_max_seconds=float(time_delta),
                vega_cluster_spread_pct=None,
                premium_mode=f"VERTICAL_{ratio_name}",
                num_legs=2,
                identical_timestamps=(time_delta < 1),
                extra_info=f"strikes={strikes[0]:.4f}/{strikes[1]:.4f}; "
                          f"ratio={actual_ratio:.2f}; "
                          f"type={opt_type}; "
                          f"direction={direction}",
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
