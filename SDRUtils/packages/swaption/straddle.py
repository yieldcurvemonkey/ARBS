"""
Straddle detection for swaption packages.

Detects straddles: Payer + Receiver swaptions with same strike/expiry/tenor.
"""

from __future__ import annotations

import datetime
from typing import Optional, Set, Any

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.swaption.utils import (
    safe_float,
    compute_package_id,
    build_package_reason,
    ensure_package_columns,
)


def detect_straddles_packages(
    df: pd.DataFrame,
    *,
    # Time window parameters
    timestamp_tolerance: datetime.timedelta = datetime.timedelta(seconds=0),
    # Matching tolerances
    strike_tolerance: float = 0.0000,
    notional_tolerance_pct: float = 0.00,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    underlier_col: str = "upi_underlier_name",
    trade_label_col: str = "trade_label",
    trade_id_col: str = "trade_id",
    strike_col: str = "strike",
    expiration_col: str = "expiration_date",
    tenor_col: str = "tenor_years",
    notional_col: str = "notional",
    package_indicator_col: str = "package_indicator",
    option_premium_amount_col: str = "option_premium_amount",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    require_same_underlier: bool = True,
    require_same_index: bool = True,
    # Additional options
    must_be_reported_as_package: bool = True,
    platforms_filter: list = None,
    add_leg_premiums: bool = False,
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
        timestamp_tolerance: Maximum time difference between payer and
            receiver legs for them to be considered a straddle.
        strike_tolerance: Absolute tolerance for strike price matching
        notional_tolerance_pct: Percentage tolerance for notional matching (0.05 = 5%)
        product_col: Column name for product type
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        underlier_col: Column name for underlier
        trade_label_col: Column name for trade label
        trade_id_col: Column name for trade ID
        strike_col: Column name for strike
        expiration_col: Column name for expiration date
        tenor_col: Column name for tenor years
        notional_col: Column name for notional
        package_indicator_col: Column name for package indicator
        option_premium_amount_col: Column name for option premium amount
        require_same_platform: Require same platform for matching
        require_same_currency: Require same currency for matching
        require_same_underlier: Require same underlier for matching
        require_same_index: Require the same swaption index for matching
        must_be_reported_as_package: If True, only match trades with package_indicator=True

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

    out = ensure_package_columns(df, package_col=package_col)

    tolerance_seconds = timestamp_tolerance.total_seconds()

    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    is_straddle = out[package_col].astype(str).str.contains("STRADDLE", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")

    candidate_mask = is_swaption & ~is_straddle & not_packaged
    if platforms_filter is not None:
        candidate_mask &= out["platform_identifier"].isin(platforms_filter)

    is_payer = out[product_col].astype(str).str.contains("PAYER|CALL", case=False, na=False)
    is_receiver = out[product_col].astype(str).str.contains("RECEIVER|PUT", case=False, na=False)

    if must_be_reported_as_package:
        payer_mask = candidate_mask & is_payer & (out[package_indicator_col] == True)
        receiver_mask = candidate_mask & is_receiver & (out[package_indicator_col] == True)
    else:
        payer_mask = candidate_mask & is_payer
        receiver_mask = candidate_mask & is_receiver

    payers = out.loc[payer_mask].copy()
    receivers = out.loc[receiver_mask].copy()

    if payers.empty or receivers.empty:
        return out

    payers["_t"] = _ensure_int64_epoch_seconds(payers[exec_col])
    receivers["_t"] = _ensure_int64_epoch_seconds(receivers[exec_col])

    payer_idx = payers.index.tolist()
    receiver_idx = receivers.index.tolist()

    matched_payers: Set[int] = set()
    matched_receivers: Set[int] = set()

    straddle_counter = 0

    def _extract_index_name(value: Any) -> str:
        if value is None or pd.isna(value):
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if "CONSTANT" in text:
            text = text.split("CONSTANT", 1)[0].strip()
        return text

    def _same_index_ok(payer_row: pd.Series, receiver_row: pd.Series) -> bool:
        if not require_same_index:
            return True
        if trade_label_col not in out.columns or underlier_col not in out.columns:
            return False
        payer_label = str(payer_row.get(trade_label_col, ""))
        receiver_label = str(receiver_row.get(trade_label_col, ""))
        has_libor = "LIBOR" in payer_label.upper() or "LIBOR" in receiver_label.upper()
        has_sofr = "SOFR" in payer_label.upper() or "SOFR" in receiver_label.upper()
        if has_libor and has_sofr:
            return False
        payer_index = _extract_index_name(payer_row.get(underlier_col, ""))
        receiver_index = _extract_index_name(receiver_row.get(underlier_col, ""))
        if not payer_index or not receiver_index:
            return False
        return payer_index == receiver_index

    for p_idx in payer_idx:
        if p_idx in matched_payers:
            continue

        p_row = payers.loc[p_idx]
        p_t = p_row["_t"]
        p_strike = safe_float(p_row.get(strike_col))
        p_expiry = p_row.get(expiration_col)
        p_tenor = safe_float(p_row.get(tenor_col))
        p_notional = safe_float(p_row.get(notional_col))
        p_platform = p_row.get(platform_col, "")
        p_currency = p_row.get(currency_col, "")
        p_underlier = p_row.get(underlier_col, "")
        p_trade_id = str(p_row.get(trade_id_col, ""))
        p_prem = p_row.get(option_premium_amount_col, 0)

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

            r_strike = safe_float(r_row.get(strike_col))
            r_expiry = r_row.get(expiration_col)
            r_tenor = safe_float(r_row.get(tenor_col))
            r_notional = safe_float(r_row.get(notional_col))
            r_platform = r_row.get(platform_col, "")
            r_currency = r_row.get(currency_col, "")
            r_underlier = r_row.get(underlier_col, "")
            r_prem = r_row.get(option_premium_amount_col, 0)

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
            if require_same_platform and p_platform != r_platform:
                continue
            if require_same_currency and p_currency != r_currency:
                continue
            if require_same_underlier and p_underlier != r_underlier:
                continue
            if not _same_index_ok(p_row, r_row):
                continue

            # This is a valid match - track the best one (closest in time)
            if time_diff < best_time_diff:
                best_time_diff = time_diff
                best_match = r_idx

        # If we found a match, create the straddle
        if best_match is not None:
            r_idx = best_match
            r_row = receivers.loc[r_idx]
            r_trade_id = str(r_row.get(trade_id_col, ""))

            matched_payers.add(p_idx)
            matched_receivers.add(r_idx)
            straddle_counter += 1

            # Generate package ID
            pid = compute_package_id(
                [p_trade_id, r_trade_id],
                p_platform,
                int(p_t // 30),  # Time bucket
                "STRADDLE",
            )

            # Compute confidence
            confidence = 0.8  # High base confidence for straddles
            if best_time_diff < 5:  # Within 5 seconds
                confidence += 0.1
            if abs(safe_float(p_row.get(strike_col)) - safe_float(r_row.get(strike_col))) < 0.00001:
                confidence += 0.1
            confidence = min(confidence, 1.0)

            # Build reason
            reason = build_package_reason(
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

                if add_leg_premiums:
                    out.loc[idx_mask, option_premium_amount_col] = str(safe_float(p_prem) + safe_float(r_prem))
                    out.loc[idx_mask, "premium"] = safe_float(p_prem) + safe_float(r_prem)

    return out
