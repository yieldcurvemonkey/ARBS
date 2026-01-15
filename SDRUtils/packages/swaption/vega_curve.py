"""
Vega curve detection for swaption packages.

Detects vega curve equivalent trades: vega-matched straddles across different tenors.
Types: VEGA_EXPIRY_SPREAD, VEGA_TAIL_SPREAD, VEGA_DIAGONAL.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Set

import numpy as np
import pandas as pd

from SDRUtils.core.utils import _ensure_int64_epoch_seconds
from SDRUtils.packages.swaption.utils import compute_package_id

if TYPE_CHECKING:
    from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve

logger = logging.getLogger(__name__)


def _compute_straddle_vega_with_pricer(
    straddle_row: pd.Series,
    pricer: "QLIRSwapCurve",
) -> Optional[float]:
    """
    Compute vega01 for a straddle using QuantLib-based pricing.

    Args:
        straddle_row: Consolidated straddle row with required fields
        pricer: QLIRSwapCurve instance for pricing

    Returns:
        vega01 value or None if pricing fails
    """
    try:
        from SDRUtils.products._swaptions.pricer import usd_swaption_straddle_pricer_from_row

        result = usd_swaption_straddle_pricer_from_row(straddle_row, pricer)
        return result.vega01
    except Exception as e:
        logger.debug(f"Failed to price straddle: {e}")
        return None


def detect_vega_curve_packages(
    df: pd.DataFrame,
    *,
    # Time window parameters
    time_window_seconds: int = 300,
    # Vega curve parameters
    vega_tolerance_pct: float = 0.10,
    vega_misweight_multipliers: Optional[Set[float]] = None,
    min_expiry_diff_years: float = 0.25,
    min_tail_diff_years: float = 1.0,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    exec_col: str = "execution_timestamp",
    platform_col: str = "platform_identifier",
    currency_col: str = "notional_currency",
    trade_id_col: str = "trade_id",
    tenor_col: str = "tenor_years",
    forward_col: str = "forward_start_years",
    notional_col: str = "notional",
    premium_col: str = "premium",
    # Economic filters
    require_same_platform: bool = True,
    require_same_currency: bool = True,
    # Pricer
    pricer: Optional["QLIRSwapCurve"] = None,
    curve_provider: Optional[Callable[[datetime.datetime], Optional["QLIRSwapCurve"]]] = None,
    use_quantlib_vega: bool = True,
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
        vega_tolerance_pct: Tolerance for vega matching (default 10%)
        vega_misweight_multipliers: Acceptable vega ratio multipliers for misweighted
            trades (e.g., 1.25, 1.5, 1.75, 2.0). Uses vega_tolerance_pct as the
            tolerance around each multiplier.
        min_expiry_diff_years: Minimum expiry difference for vega spreads
        min_tail_diff_years: Minimum tail difference for vega spreads
        product_col: Column name for product type
        package_col: Column name for package type
        exec_col: Column name for execution timestamp
        platform_col: Column name for platform identifier
        currency_col: Column name for currency
        trade_id_col: Column name for trade ID
        tenor_col: Column name for tenor years
        forward_col: Column name for forward start years
        notional_col: Column name for notional
        premium_col: Column name for premium
        require_same_platform: Require same platform for matching
        require_same_currency: Require same currency for matching
        pricer: Optional QLIRSwapCurve instance for QuantLib-based vega calculation
        curve_provider: Optional callable that takes an execution timestamp and returns
            a QLIRSwapCurve for that date
        use_quantlib_vega: If True and pricer/curve_provider is available, use QuantLib
            pricing for vega calculation

    Returns:
        DataFrame with vega curve annotations on the straddle legs:
        - vega_curve_type: "VEGA_EXPIRY_SPREAD", "VEGA_TAIL_SPREAD", "VEGA_DIAGONAL"
        - vega_curve_id: Links the two straddles
        - vega_curve_legs: List of all trade IDs across both straddles
        - vega_curve_vega01: Calculated vega01 for each straddle (if pricer provided)
        - vega_curve_weight: Target vega ratio matched (1.0 for balanced)
        - vega_curve_vega_ratio: Actual vega ratio between straddles
        - vega_curve_pricing_method: "QUANTLIB"
    """
    if df.empty:
        return df

    out = df.copy()

    # Initialize vega curve columns
    if "vega_curve_type" not in out.columns:
        out["vega_curve_type"] = None
    if "vega_curve_id" not in out.columns:
        out["vega_curve_id"] = None
    if "vega_curve_legs" not in out.columns:
        out["vega_curve_legs"] = None
    if "vega_curve_vega01" not in out.columns:
        out["vega_curve_vega01"] = np.nan
    if "vega_curve_weight" not in out.columns:
        out["vega_curve_weight"] = np.nan
    if "vega_curve_vega_ratio" not in out.columns:
        out["vega_curve_vega_ratio"] = np.nan
    if "vega_curve_pricing_method" not in out.columns:
        out["vega_curve_pricing_method"] = None

    # Only operate on known straddle rows (straddles are detected upstream)
    straddle_mask = out[package_col] == "STRADDLE"
    if not straddle_mask.any():
        return out

    # Keep a view of just straddle rows for expensive computations / grouping
    straddles = out.loc[straddle_mask].copy()

    # Aggregation dict for straddle characteristics
    agg_dict: Dict[str, Any] = {
        exec_col: "first",
        platform_col: "first",
        currency_col: "first",
        tenor_col: "first",  # Tail
        forward_col: "first",  # Expiry
        notional_col: "sum",  # Total notional
        premium_col: "sum",  # Total premium (vega proxy fallback)
        trade_id_col: list,
    }

    # Also aggregate fields needed for QuantLib pricing if available
    quantlib_fields = ["expiration_date", "underlying_expiration_date", "strike"]
    for field in quantlib_fields:
        if field in straddles.columns:
            agg_dict[field] = "first"

    # Group by package_id to get straddle characteristics (ONLY straddles)
    straddle_groups = straddles.groupby("package_id").agg(agg_dict).reset_index()

    if len(straddle_groups) < 2:
        return out

    # Add timestamp for sorting
    straddle_groups["_t"] = _ensure_int64_epoch_seconds(straddle_groups[exec_col])
    straddle_groups.sort_values("_t", inplace=True, kind="mergesort")

    # Compute vega for each straddle group (ONLY straddles; never touch non-straddle rows)
    quantlib_pricing_available = use_quantlib_vega and (pricer is not None or curve_provider is not None)
    if not quantlib_pricing_available:
        return out

    straddle_vegas: Dict[str, float] = {}  # package_id -> vega

    if vega_misweight_multipliers is None:
        vega_misweight_multipliers = {1, 1.5, 2, 2.5, 3}

    for _, row in straddle_groups.iterrows():
        pid = row["package_id"]

        vega01 = _compute_straddle_vega_with_pricer(row, pricer)
        if vega01 is not None:
            straddle_vegas[pid] = vega01

    n_straddles = len(straddle_groups)
    matched_straddles: Set[str] = set()

    for i in range(n_straddles):
        pid_i = straddle_groups.iloc[i]["package_id"]
        if pid_i in matched_straddles:
            continue

        t_i = straddle_groups.iloc[i]["_t"]
        plat_i = straddle_groups.iloc[i][platform_col]
        ccy_i = straddle_groups.iloc[i][currency_col]
        tail_i = straddle_groups.iloc[i][tenor_col]
        expiry_i = straddle_groups.iloc[i][forward_col]
        vega_i = straddle_vegas.get(pid_i)
        trades_i = straddle_groups.iloc[i][trade_id_col]

        if vega_i is None or vega_i <= 0:
            continue

        for j in range(i + 1, n_straddles):
            pid_j = straddle_groups.iloc[j]["package_id"]
            if pid_j in matched_straddles:
                continue

            t_j = straddle_groups.iloc[j]["_t"]

            # Time window check
            if abs(t_i - t_j) > time_window_seconds:
                continue

            plat_j = straddle_groups.iloc[j][platform_col]
            ccy_j = straddle_groups.iloc[j][currency_col]
            tail_j = straddle_groups.iloc[j][tenor_col]
            expiry_j = straddle_groups.iloc[j][forward_col]
            vega_j = straddle_vegas.get(pid_j)
            trades_j = straddle_groups.iloc[j][trade_id_col]

            # Platform and currency match
            if require_same_platform and plat_i != plat_j:
                continue
            if require_same_currency and ccy_i != ccy_j:
                continue

            # Vega similarity check
            if vega_j is None or vega_j <= 0:
                continue
            avg_vega = 0.5 * (vega_i + vega_j)
            vega_diff = abs(vega_i - vega_j) / avg_vega
            vega_ratio = max(vega_i, vega_j) / min(vega_i, vega_j)
            vega_weight = None

            if vega_diff <= vega_tolerance_pct:
                vega_weight = 1.0
            else:
                for multiplier in vega_misweight_multipliers:
                    if abs(vega_ratio - multiplier) / multiplier <= vega_tolerance_pct:
                        vega_weight = multiplier
                        break

            if vega_weight is None:
                continue

            # Determine curve type based on expiry/tail differences
            tail_diff = abs(tail_i - tail_j) if pd.notna(tail_i) and pd.notna(tail_j) else 0
            expiry_diff = abs(expiry_i - expiry_j) if pd.notna(expiry_i) and pd.notna(expiry_j) else 0

            same_tail = tail_diff < 0.1
            same_expiry = expiry_diff < 0.1

            if same_tail and not same_expiry and expiry_diff >= min_expiry_diff_years:
                curve_type = "VEGA_EXPIRY_SPREAD"
            elif same_expiry and not same_tail and tail_diff >= min_tail_diff_years:
                curve_type = "VEGA_TAIL_SPREAD"
            elif not same_tail and not same_expiry:
                if expiry_diff >= min_expiry_diff_years or tail_diff >= min_tail_diff_years:
                    curve_type = "VEGA_DIAGONAL"
                else:
                    continue
            else:
                continue

            matched_straddles.add(pid_i)
            matched_straddles.add(pid_j)

            curve_id = compute_package_id(
                [pid_i, pid_j],
                str(plat_i),
                int(t_i // 30),
                curve_type,
            )

            all_trades = list(trades_i) + list(trades_j)

            for pid, vega_val in [(pid_i, vega_i), (pid_j, vega_j)]:
                # IMPORTANT: only annotate straddle rows (do not touch non-straddles)
                mask = straddle_mask & (out["package_id"] == pid)
                out.loc[mask, "vega_curve_type"] = curve_type
                out.loc[mask, "vega_curve_id"] = curve_id
                out.loc[mask, "vega_curve_legs"] = pd.Series([all_trades] * mask.sum(), index=out.index[mask])
                out.loc[mask, "vega_curve_vega01"] = vega_val / 2
                out.loc[mask, "vega_curve_weight"] = vega_weight
                out.loc[mask, "vega_curve_vega_ratio"] = vega_ratio
                out.loc[mask, "vega_curve_pricing_method"] = "QUANTLIB"

            break

    return out
