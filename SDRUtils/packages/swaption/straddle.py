"""
Straddle detection for swaption packages.

Detects straddles: Payer + Receiver swaptions with same strike/expiry/tenor.
"""

from __future__ import annotations

import datetime
from typing import Optional, Set

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
    timestamp_tolerance: datetime.timedelta = datetime.timedelta(seconds=60),
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
    require_same_underlier: bool = False,
    # Additional options
    must_be_reported_as_package: bool = False,
    custy_leg_option_premium_amount_tolerance: Optional[float] = None,
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

    For customer trades (platform_identifier=BILT), straddles may be reported as
    separate legs without the package_indicator flag. When custy_leg_option_premium_amount_tolerance
    is provided, an additional matching rule is applied for customer trades that
    matches based on option_premium_amount being the same within the tolerance.

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
        must_be_reported_as_package: If True, only match trades with package_indicator=True
        custy_leg_option_premium_amount_tolerance: Percentage tolerance for matching
            customer (BILT) trades based on option_premium_amount.

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
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")
    candidate_mask = is_swaption & not_packaged

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

    # =========================================================================
    # Customer (BILT) straddle detection based on option_premium_amount matching
    # =========================================================================
    if custy_leg_option_premium_amount_tolerance is not None:
        out = _detect_customer_straddles(
            out,
            tolerance_seconds=tolerance_seconds,
            strike_tolerance=strike_tolerance,
            notional_tolerance_pct=notional_tolerance_pct,
            custy_leg_option_premium_amount_tolerance=custy_leg_option_premium_amount_tolerance,
            product_col=product_col,
            package_col=package_col,
            exec_col=exec_col,
            platform_col=platform_col,
            currency_col=currency_col,
            underlier_col=underlier_col,
            trade_id_col=trade_id_col,
            strike_col=strike_col,
            expiration_col=expiration_col,
            tenor_col=tenor_col,
            notional_col=notional_col,
            option_premium_amount_col=option_premium_amount_col,
            require_same_platform=require_same_platform,
            require_same_currency=require_same_currency,
            require_same_underlier=require_same_underlier,
        )

    return out


def _detect_customer_straddles(
    out: pd.DataFrame,
    *,
    tolerance_seconds: float,
    strike_tolerance: float,
    notional_tolerance_pct: float,
    custy_leg_option_premium_amount_tolerance: float,
    product_col: str,
    package_col: str,
    exec_col: str,
    platform_col: str,
    currency_col: str,
    underlier_col: str,
    trade_id_col: str,
    strike_col: str,
    expiration_col: str,
    tenor_col: str,
    notional_col: str,
    option_premium_amount_col: str,
    require_same_platform: bool,
    require_same_currency: bool,
    require_same_underlier: bool,
) -> pd.DataFrame:
    """
    Detect customer straddles based on option_premium_amount matching.

    For customer trades reported via BILT, straddles are reported as separate
    legs so must_be_reported_as_package=True may miss them. This additional
    rule matches based on option_premium_amount being the same within tolerance.
    """
    # Re-filter for unmatched swaptions on BILT platform only
    is_swaption_custy = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged_custy = out["package_id"].isna() | (out["package_id"] == "")
    is_bilt = out[platform_col] == "BILT"
    custy_candidate_mask = is_swaption_custy & not_packaged_custy & is_bilt

    is_payer_custy = out[product_col].astype(str).str.contains("PAYER|CALL", case=False, na=False)
    is_receiver_custy = out[product_col].astype(str).str.contains("RECEIVER|PUT", case=False, na=False)

    # For customer trades, ignore must_be_reported_as_package filter
    custy_payer_mask = custy_candidate_mask & is_payer_custy
    custy_receiver_mask = custy_candidate_mask & is_receiver_custy

    custy_payers = out.loc[custy_payer_mask].copy()
    custy_receivers = out.loc[custy_receiver_mask].copy()

    if custy_payers.empty or custy_receivers.empty:
        return out

    # Parse option_premium_amount for matching
    if option_premium_amount_col in custy_payers.columns:
        custy_payers["_opt_prem"] = custy_payers[option_premium_amount_col].apply(safe_float)
    else:
        custy_payers["_opt_prem"] = np.nan

    if option_premium_amount_col in custy_receivers.columns:
        custy_receivers["_opt_prem"] = custy_receivers[option_premium_amount_col].apply(safe_float)
    else:
        custy_receivers["_opt_prem"] = np.nan

    custy_payers["_t"] = _ensure_int64_epoch_seconds(custy_payers[exec_col])
    custy_receivers["_t"] = _ensure_int64_epoch_seconds(custy_receivers[exec_col])

    custy_payer_idx = custy_payers.index.tolist()
    custy_receiver_idx = custy_receivers.index.tolist()

    custy_matched_payers: Set[int] = set()
    custy_matched_receivers: Set[int] = set()

    for cp_idx in custy_payer_idx:
        if cp_idx in custy_matched_payers:
            continue

        cp_row = custy_payers.loc[cp_idx]
        cp_t = cp_row["_t"]
        cp_strike = safe_float(cp_row.get(strike_col))
        cp_expiry = cp_row.get(expiration_col)
        cp_tenor = safe_float(cp_row.get(tenor_col))
        cp_notional = safe_float(cp_row.get(notional_col))
        cp_platform = cp_row.get(platform_col, "")
        cp_currency = cp_row.get(currency_col, "")
        cp_underlier = cp_row.get(underlier_col, "")
        cp_trade_id = str(cp_row.get(trade_id_col, ""))
        cp_opt_prem = cp_row["_opt_prem"]

        # Skip if missing critical fields
        if pd.isna(cp_strike) or pd.isna(cp_tenor) or pd.isna(cp_notional):
            continue

        # For customer matching, require valid option_premium_amount
        if pd.isna(cp_opt_prem):
            continue

        best_custy_match = None
        best_custy_time_diff = float("inf")

        for cr_idx in custy_receiver_idx:
            if cr_idx in custy_matched_receivers:
                continue

            cr_row = custy_receivers.loc[cr_idx]
            cr_t = cr_row["_t"]

            # Check timestamp tolerance
            time_diff = abs(cp_t - cr_t)
            if time_diff > tolerance_seconds:
                continue

            cr_strike = safe_float(cr_row.get(strike_col))
            cr_expiry = cr_row.get(expiration_col)
            cr_tenor = safe_float(cr_row.get(tenor_col))
            cr_notional = safe_float(cr_row.get(notional_col))
            cr_platform = cr_row.get(platform_col, "")
            cr_currency = cr_row.get(currency_col, "")
            cr_underlier = cr_row.get(underlier_col, "")
            cr_opt_prem = cr_row["_opt_prem"]

            # Skip if missing critical fields
            if pd.isna(cr_strike) or pd.isna(cr_tenor) or pd.isna(cr_notional):
                continue

            # For customer matching, require valid option_premium_amount
            if pd.isna(cr_opt_prem):
                continue

            # Check strike match
            if abs(cp_strike - cr_strike) > strike_tolerance:
                continue

            # Check expiry match (if both are valid)
            if pd.notna(cp_expiry) and pd.notna(cr_expiry):
                cp_exp_date = pd.to_datetime(cp_expiry)
                cr_exp_date = pd.to_datetime(cr_expiry)
                if cp_exp_date != cr_exp_date:
                    continue

            # Check tenor match
            if abs(cp_tenor - cr_tenor) > 0.01:  # 0.01 year tolerance
                continue

            # Check notional match
            avg_notional = 0.5 * (cp_notional + cr_notional)
            if avg_notional > 0:
                notional_diff = abs(cp_notional - cr_notional) / avg_notional
                if notional_diff > notional_tolerance_pct:
                    continue

            # Check economic filters
            if require_same_platform and cp_platform != cr_platform:
                continue
            if require_same_currency and cp_currency != cr_currency:
                continue
            if require_same_underlier and cp_underlier != cr_underlier:
                continue

            # CUSTOMER-SPECIFIC: Check option_premium_amount match within tolerance
            avg_opt_prem = 0.5 * (cp_opt_prem + cr_opt_prem)
            if avg_opt_prem > 0:
                opt_prem_diff = abs(cp_opt_prem - cr_opt_prem) / avg_opt_prem
                if opt_prem_diff > custy_leg_option_premium_amount_tolerance:
                    continue

            # This is a valid customer straddle match
            if time_diff < best_custy_time_diff:
                best_custy_time_diff = time_diff
                best_custy_match = cr_idx

        # If we found a customer straddle match, create the straddle
        if best_custy_match is not None:
            cr_idx = best_custy_match
            cr_row = custy_receivers.loc[cr_idx]
            cr_trade_id = str(cr_row.get(trade_id_col, ""))
            cr_opt_prem = cr_row["_opt_prem"]

            custy_matched_payers.add(cp_idx)
            custy_matched_receivers.add(cr_idx)

            # Generate package ID
            custy_pid = compute_package_id(
                [cp_trade_id, cr_trade_id],
                cp_platform,
                int(cp_t // 30),  # Time bucket
                "STRADDLE",
            )

            # Compute confidence (slightly lower for customer matching)
            custy_confidence = 0.75  # Base confidence for customer straddles
            if best_custy_time_diff < 5:  # Within 5 seconds
                custy_confidence += 0.1
            if abs(safe_float(cp_row.get(strike_col)) - safe_float(cr_row.get(strike_col))) < 0.00001:
                custy_confidence += 0.1
            # Bonus for exact premium match
            if abs(cp_opt_prem - cr_opt_prem) < 0.01:
                custy_confidence += 0.05
            custy_confidence = min(custy_confidence, 1.0)

            # Build reason with customer-specific info
            custy_reason = build_package_reason(
                platform=cp_platform,
                time_delta_max_seconds=best_custy_time_diff,
                vega_cluster_spread_pct=None,
                premium_mode="STRADDLE",
                num_legs=2,
                identical_timestamps=(best_custy_time_diff < 1),
                extra_info=f"strike={cp_strike:.4f}; tenor={cp_tenor:.1f}Y; custy_prem_match",
            )

            custy_legs_list = [cp_trade_id, cr_trade_id]

            # Sum option_premium_amount for the straddle
            summed_opt_prem = cp_opt_prem + cr_opt_prem

            # Update both legs
            for cidx in [cp_idx, cr_idx]:
                cidx_mask = out.index == cidx
                out.loc[cidx_mask, package_col] = "STRADDLE"
                out.loc[cidx_mask, "premium"] = summed_opt_prem
                out.loc[cidx_mask, "package_id"] = custy_pid
                cleg_count = int(cidx_mask.sum())
                out.loc[cidx_mask, "package_legs"] = pd.Series(
                    [custy_legs_list] * cleg_count,
                    index=out.index[cidx_mask],
                )
                out.loc[cidx_mask, "package_confidence"] = custy_confidence
                out.loc[cidx_mask, "package_reason"] = custy_reason
                out.loc[cidx_mask, "package_legs_count"] = 2
                # Set the summed option_premium_amount for both legs
                out.loc[cidx_mask, option_premium_amount_col] = f"{summed_opt_prem:,.5f}".rstrip("0").rstrip(".").rstrip(",")

    return out
