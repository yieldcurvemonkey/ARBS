"""
Customer risk reversal / strangle detection for swaption packages.

Detects customer RR/strangle structures from SDR data based on:
- PAYER + RECEIVER pair
- Same tenor (expiry and swap)
- Same timestamp window (within seconds)
- Same notional, platform, event_action
- Strike difference is a benchmark offset (10bp, 20bp, 25bp, 50bp, 100bp, etc.)

Key differences from inter-dealer risk reversals (4-leg):
- Customer RR/strangles are 2-leg structures (no delta hedge legs)
- Strikes are at benchmark widths (not arbitrary)
- Typically on customer platforms (BILT, TPSE, XXXX)

RR vs Strangle distinction (requires ATMF):
- Risk Reversal: Strikes bracket the ATMF (one ITM, one OTM)
- Strangle: Both strikes on same side of ATMF (both OTM)
- Without ATMF, we cannot definitively classify; default to "CUSTY_RR_STRANGLE"
"""

from __future__ import annotations

from typing import List, Optional, Set

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.swaption.utils import (
    safe_float,
    compute_package_id,
    build_package_reason,
    ensure_package_columns,
)


# Benchmark strike widths in basis points
BENCHMARK_WIDTHS_BPS: List[int] = [10, 15, 20, 25, 30, 40, 50, 75, 100, 125, 150, 200]

# Default detection parameters
DEFAULT_WIDTH_TOLERANCE_BPS: float = 3.0
DEFAULT_TIMESTAMP_WINDOW_SECONDS: int = 5
DEFAULT_NOTIONAL_TOLERANCE_PCT: float = 0.01


def _match_benchmark_width(
    actual_bps: float,
    benchmarks: List[int],
    tolerance_bps: float,
) -> Optional[int]:
    """
    Match actual strike width to a benchmark width.

    Args:
        actual_bps: Actual strike difference in basis points
        benchmarks: List of benchmark widths to match against
        tolerance_bps: Tolerance for matching (in bps)

    Returns:
        Matched benchmark width, or None if no match
    """
    for bw in benchmarks:
        if abs(actual_bps - bw) <= tolerance_bps:
            return bw
    return None


def _notionals_match(n1: float, n2: float, tolerance_pct: float) -> bool:
    """Check if two notionals match within tolerance."""
    if n1 == 0 and n2 == 0:
        return True
    if n1 == 0 or n2 == 0:
        return False

    avg = (n1 + n2) / 2
    return abs(n1 - n2) / avg <= tolerance_pct


def detect_customer_rr_strangles_packages(
    df: pd.DataFrame,
    *,
    # Time window parameters
    timestamp_window_seconds: int = DEFAULT_TIMESTAMP_WINDOW_SECONDS,
    # Matching tolerances
    notional_tolerance_pct: float = DEFAULT_NOTIONAL_TOLERANCE_PCT,
    width_tolerance_bps: float = DEFAULT_WIDTH_TOLERANCE_BPS,
    benchmark_widths_bps: Optional[List[int]] = None,
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
    forward_col: str = "forward_start_years",
    notional_col: str = "notional",
    event_action_col: str = "event_action",
    option_premium_amount_col: str = "option_premium_amount",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    require_same_underlier: bool = True,
    require_same_index: bool = True,
    require_same_event_action: bool = True,
    # Platform filters
    platforms_filter: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Detect customer swaption risk reversals and strangles.

    A customer RR/strangle consists of:
    - One PAYER swaption and one RECEIVER swaption
    - Same option expiration date
    - Same underlying tenor
    - Same notional (within tolerance)
    - Different strikes with a benchmark offset (10, 20, 25, 50, 100, 200bp, etc.)
    - Execution timestamps within the specified window
    - Same platform, event_action

    This is distinct from inter-dealer risk reversals which are 4-leg structures
    with delta hedge at the middle strike.

    Args:
        df: Classifications dataframe with swaption trades
        timestamp_window_seconds: Maximum time difference between payer and
            receiver legs for them to be considered a package
        notional_tolerance_pct: Percentage tolerance for notional matching (0.01 = 1%)
        width_tolerance_bps: Tolerance for matching benchmark widths (in bps)
        benchmark_widths_bps: List of benchmark strike widths to detect
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
        forward_col: Column name for forward start years
        notional_col: Column name for notional
        event_action_col: Column name for event action
        option_premium_amount_col: Column name for option premium amount
        require_same_platform: Require same platform for matching
        require_same_currency: Require same currency for matching
        require_same_underlier: Require same underlier for matching
        require_same_index: Require the same swaption index for matching
        require_same_event_action: Require same event_action for matching
        platforms_filter: If set, only these platforms are considered

    Returns:
        DataFrame with customer RR/strangle annotations:
        - package_type: "CUSTY_RR_STRANGLE" for detected structures
        - package_id: Deterministic package identifier
        - package_legs: List of trade IDs in the package
        - package_confidence: Confidence score 0-1
        - package_reason: Structured explanation string
        - package_legs_count: Always 2 for customer RR/strangles
        - custy_rr_width_bps: Benchmark strike width in basis points
    """
    if df.empty:
        return df

    if benchmark_widths_bps is None:
        benchmark_widths_bps = BENCHMARK_WIDTHS_BPS

    out = ensure_package_columns(df, package_col=package_col)

    # Ensure custy_rr_width_bps column exists
    if "custy_rr_width_bps" not in out.columns:
        out["custy_rr_width_bps"] = np.nan

    # Filter to candidate trades
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")

    is_payer = out[product_col].astype(str).str.contains("PAYER|CALL", case=False, na=False)
    is_receiver = out[product_col].astype(str).str.contains("RECEIVER|PUT", case=False, na=False)

    # Apply platform filter if provided
    if platforms_filter is not None:
        is_platform = out[platform_col].isin(platforms_filter)
        candidate_mask = is_swaption & not_packaged & is_platform
    else:
        candidate_mask = is_swaption & not_packaged

    payer_mask = candidate_mask & is_payer
    receiver_mask = candidate_mask & is_receiver

    payers = out.loc[payer_mask].copy()
    receivers = out.loc[receiver_mask].copy()

    if payers.empty or receivers.empty:
        return out

    # Convert timestamps to epoch seconds
    payers["_t"] = _ensure_int64_epoch_seconds(payers[exec_col])
    receivers["_t"] = _ensure_int64_epoch_seconds(receivers[exec_col])

    payer_idx = payers.index.tolist()
    receiver_idx = receivers.index.tolist()

    matched_payers: Set[int] = set()
    matched_receivers: Set[int] = set()

    def _extract_index_name(value) -> str:
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

    def _same_event_action_ok(payer_row: pd.Series, receiver_row: pd.Series) -> bool:
        if not require_same_event_action:
            return True
        if event_action_col not in out.columns:
            return True  # Skip check if column not present
        p_action = str(payer_row.get(event_action_col, ""))
        r_action = str(receiver_row.get(event_action_col, ""))
        if not p_action or p_action in ("", "nan", "<NA>", "None"):
            return False
        if not r_action or r_action in ("", "nan", "<NA>", "None"):
            return False
        return p_action == r_action

    # Iterate through payers to find matching receivers
    for p_idx in payer_idx:
        if p_idx in matched_payers:
            continue

        p_row = payers.loc[p_idx]
        p_t = p_row["_t"]
        p_strike = safe_float(p_row.get(strike_col))
        p_expiry = p_row.get(expiration_col)
        p_tenor = safe_float(p_row.get(tenor_col))
        p_forward = safe_float(p_row.get(forward_col))
        p_notional = safe_float(p_row.get(notional_col))
        p_platform = p_row.get(platform_col, "")
        p_currency = p_row.get(currency_col, "")
        p_underlier = p_row.get(underlier_col, "")
        p_trade_id = str(p_row.get(trade_id_col, ""))
        p_prem = safe_float(p_row.get(option_premium_amount_col, 0))

        # Skip if missing critical fields
        if pd.isna(p_strike) or pd.isna(p_tenor) or pd.isna(p_notional):
            continue

        best_match = None
        best_time_diff = float("inf")
        best_width_bps = None

        for r_idx in receiver_idx:
            if r_idx in matched_receivers:
                continue

            r_row = receivers.loc[r_idx]
            r_t = r_row["_t"]

            # Check timestamp tolerance
            time_diff = abs(p_t - r_t)
            if time_diff > timestamp_window_seconds:
                continue

            r_strike = safe_float(r_row.get(strike_col))
            r_expiry = r_row.get(expiration_col)
            r_tenor = safe_float(r_row.get(tenor_col))
            r_forward = safe_float(r_row.get(forward_col))
            r_notional = safe_float(r_row.get(notional_col))
            r_platform = r_row.get(platform_col, "")
            r_currency = r_row.get(currency_col, "")
            r_underlier = r_row.get(underlier_col, "")
            r_prem = safe_float(r_row.get(option_premium_amount_col, 0))

            # Skip if missing critical fields
            if pd.isna(r_strike) or pd.isna(r_tenor) or pd.isna(r_notional):
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

            # Check forward match (option expiry tenor)
            if pd.notna(p_forward) and pd.notna(r_forward):
                if abs(p_forward - r_forward) > 0.01:  # 0.01 year tolerance
                    continue

            # Check notional match
            if not _notionals_match(abs(p_notional), abs(r_notional), notional_tolerance_pct):
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
            if not _same_event_action_ok(p_row, r_row):
                continue

            # Calculate strike width in basis points
            strike_diff_bps = abs(p_strike - r_strike) * 10000

            # Check if strike difference matches a benchmark width
            matched_width = _match_benchmark_width(
                strike_diff_bps, benchmark_widths_bps, width_tolerance_bps
            )

            if matched_width is None:
                continue

            # This is a valid match - track the best one (closest in time)
            if time_diff < best_time_diff:
                best_time_diff = time_diff
                best_match = r_idx
                best_width_bps = matched_width

        # If we found a match, create the package
        if best_match is not None:
            r_idx = best_match
            r_row = receivers.loc[r_idx]
            r_trade_id = str(r_row.get(trade_id_col, ""))
            r_prem = safe_float(r_row.get(option_premium_amount_col, 0))

            matched_payers.add(p_idx)
            matched_receivers.add(r_idx)

            # Generate package ID
            pid = compute_package_id(
                [p_trade_id, r_trade_id],
                p_platform,
                int(p_t // 30),  # Time bucket
                "CUSTY_RR_STRANGLE",
            )

            # Compute confidence
            confidence = 0.8  # High base confidence
            if best_time_diff < 2:  # Within 2 seconds
                confidence += 0.1
            if best_width_bps in [25, 50, 100]:  # Very common widths
                confidence += 0.05
            confidence = min(confidence, 1.0)

            # Calculate net premium
            net_prem = None
            if not pd.isna(p_prem) and not pd.isna(r_prem):
                net_prem = p_prem - r_prem

            # Build reason
            r_strike_val = safe_float(r_row.get(strike_col))
            reason = build_package_reason(
                platform=p_platform,
                time_delta_max_seconds=best_time_diff,
                vega_cluster_spread_pct=None,  # N/A
                premium_mode="CUSTY_RR_STRANGLE",
                num_legs=2,
                identical_timestamps=(best_time_diff < 1),
                extra_info=f"width={best_width_bps}bp; payer_K={p_strike:.4f}; recv_K={r_strike_val:.4f}",
            )

            legs_list = [p_trade_id, r_trade_id]

            # Update both legs
            for idx in [p_idx, r_idx]:
                idx_mask = out.index == idx
                out.loc[idx_mask, package_col] = "CUSTY_RR_STRANGLE"
                out.loc[idx_mask, "package_id"] = pid
                legs_count = int(idx_mask.sum())
                out.loc[idx_mask, "package_legs"] = pd.Series(
                    [legs_list] * legs_count,
                    index=out.index[idx_mask],
                )
                out.loc[idx_mask, "package_confidence"] = confidence
                out.loc[idx_mask, "package_reason"] = reason
                out.loc[idx_mask, "package_legs_count"] = 2
                out.loc[idx_mask, "custy_rr_width_bps"] = best_width_bps

    return out
