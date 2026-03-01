"""
Swaption package detection module.

Detects multi-leg swaption packages including:
- STRADDLE: Payer + Receiver swaptions with same strike/expiry/tenor
- RISK_REVERSAL: 4-leg structures with wings + delta hedge (3 strikes, 2 notionals)
- VERTICAL_SPREAD: Same tenor, different strikes, same option type (1x1, 1x2, 1x1.5, etc.)
- LADDER: Christmas tree structures with 3+ legs, same option type, asymmetric notionals
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

Architecture:
This module follows a pipeline pattern where each detector is a composable
function that can be added to the detection waterfall. New structure types
(e.g., Iron Condors, Iron Butterflies) can be added by:
1. Creating a new module in SDRUtils/packages/swaption/
2. Adding it to the detector list in detect_swaption_packages_df

Detection uses explicit keyword arguments following the patterns of
fly.py and curve.py for linear trades.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from tqdm import tqdm

import numpy as np
import pandas as pd

from SDRUtils.packages.base import PackageDetector

# Import detection functions from submodules
from SDRUtils.packages.swaption.straddle import detect_straddles_packages
from SDRUtils.packages.swaption.risk_reversal import detect_risk_reversals_packages
from SDRUtils.packages.swaption.spreads import detect_vertical_spreads_packages
from SDRUtils.packages.swaption.ladder import detect_ladder_packages
from SDRUtils.packages.swaption.conditional_curve import detect_conditional_curve_packages
from SDRUtils.packages.swaption.vega_curve import detect_vega_curve_packages
from SDRUtils.packages.swaption.vega_buckets import detect_vega_bucketed_packages
from SDRUtils.packages.swaption.linking import link_packages
from SDRUtils.packages.swaption.customer_rr_strangle import detect_customer_rr_strangles_packages
from SDRUtils.packages.swaption.delta_hedge import detect_delta_hedge_packages
from SDRUtils.packages.swaption.outright import detect_outright_swaptions

# Import utility functions - aliased for backward compatibility exports
from SDRUtils.packages.swaption.utils import (
    vega_bucket as _vega_bucket,
    time_bucket as _time_bucket,
    compute_package_id as _compute_package_id,
    estimate_swaption_vega as _estimate_swaption_vega,
    extract_effective_premium,
)
from SDRUtils.packages.utils import merge_package_legs_to_one_row

if TYPE_CHECKING:
    from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
    from SDRUtils.products._swaptions.pricer import (
        USDSwaptionLegPricerResult,
        USDSwaptionStraddlePricerResult,
        USDSwaptionVerticalSpreadPricerResult,
    )


logger = logging.getLogger(__name__)

# =============================================================================
# Backward Compatibility - Config Class
# =============================================================================
# DEPRECATED: SwaptionPackageDetectionConfig is maintained for backward
# compatibility but should not be used in new code. Use explicit keyword
# arguments instead.


class SwaptionPackageDetectionConfig:
    """
    DEPRECATED: Configuration for swaption package detection algorithms.

    This class is maintained for backward compatibility. New code should use
    explicit keyword arguments to the detection functions instead.

    All detection logic thresholds are now passed as explicit kwargs.
    """

    def __init__(
        self,
        # Time windows
        time_window_seconds: int = 300,
        time_window_link_seconds: int = 600,
        # Vega tolerance
        vega_tolerance_pct: float = 0.00,
        # Minimum legs
        min_legs: int = 2,
        # Platform filtering
        platform_allowlist: Optional[List[str]] = None,
        platform_blocklist: Optional[List[str]] = None,
        # Economic filters
        require_same_platform: bool = True,
        require_same_currency: bool = True,
        require_same_underlier: bool = False,
        # Timestamp matching
        timestamp_mode: str = "fuzzy",
        exact_timestamp_tolerance_seconds: int = 1,
        # Price field handling
        price_field_mode: str = "both",
        # Notional sanity checks
        notional_sanity_checks: bool = True,
        notional_max_multiplier: float = 1000.0,
        # Column names
        exec_col: str = "execution_timestamp",
        platform_col: str = "platform_identifier",
        currency_col: str = "notional_currency",
        underlier_col: str = "upi_underlier_name",
        trade_id_col: str = "trade_id",
        trade_label_col: str = "trade_label",
        premium_col: str = "premium",
        package_price_col: str = "package_transaction_price",
        package_indicator_col: str = "package_indicator",
        vega_col: str = "estimated_vega",
        notional_col: str = "notional",
        strike_col: str = "strike",
        expiration_col: str = "expiration_date",
        tenor_col: str = "tenor_years",
        forward_col: str = "forward_start_years",
        tail_maturity_col: str = "underlying_expiration_date",
        # Confidence weights
        confidence_weights: Optional[Dict[str, float]] = None,
        # Spread detection
        spread_ratios: Optional[List[Tuple[float, str, float]]] = None,
        vertical_spread_min_strike_width: float = 0.001,
        # Conditional curve
        conditional_curve_min_tail_diff_years: float = 5.0,
        # Vega curve
        vega_curve_tolerance_pct: float = 0.10,
        vega_curve_min_expiry_diff_years: float = 0.08,
        vega_curve_min_tail_diff_years: float = 0.333,
        # IDB platforms
        idb_platforms: Optional[List[str]] = None,
        customer_platforms: Optional[List[str]] = None,
    ):
        self.time_window_seconds = time_window_seconds
        self.time_window_link_seconds = time_window_link_seconds
        self.vega_tolerance_pct = vega_tolerance_pct
        self.min_legs = min_legs
        self.platform_allowlist = platform_allowlist
        self.platform_blocklist = platform_blocklist
        self.require_same_platform = require_same_platform
        self.require_same_currency = require_same_currency
        self.require_same_underlier = require_same_underlier
        self.timestamp_mode = timestamp_mode
        self.exact_timestamp_tolerance_seconds = exact_timestamp_tolerance_seconds
        self.price_field_mode = price_field_mode
        self.notional_sanity_checks = notional_sanity_checks
        self.notional_max_multiplier = notional_max_multiplier
        self.exec_col = exec_col
        self.platform_col = platform_col
        self.currency_col = currency_col
        self.underlier_col = underlier_col
        self.trade_id_col = trade_id_col
        self.trade_label_col = trade_label_col
        self.premium_col = premium_col
        self.package_price_col = package_price_col
        self.package_indicator_col = package_indicator_col
        self.vega_col = vega_col
        self.notional_col = notional_col
        self.strike_col = strike_col
        self.expiration_col = expiration_col
        self.tenor_col = tenor_col
        self.forward_col = forward_col
        self.tail_maturity_col = tail_maturity_col
        self.confidence_weights = confidence_weights or {
            "identical_timestamp": 0.3,
            "vega_similarity": 0.25,
            "package_indicator": 0.15,
            "premium_anomaly": 0.15,
            "platform_match": 0.15,
        }
        self.spread_ratios = spread_ratios or [
            (1.0, "1x1", 0.05),
            (1.5, "1x1.5", 0.05),
            (2.0, "1x2", 0.10),
            (2.5, "1x2.5", 0.10),
            (3.0, "1x3", 0.10),
        ]
        self.vertical_spread_min_strike_width = vertical_spread_min_strike_width
        self.conditional_curve_min_tail_diff_years = conditional_curve_min_tail_diff_years
        self.vega_curve_tolerance_pct = vega_curve_tolerance_pct
        self.vega_curve_min_expiry_diff_years = vega_curve_min_expiry_diff_years
        self.vega_curve_min_tail_diff_years = vega_curve_min_tail_diff_years
        self.idb_platforms = idb_platforms or ["BGCD", "ISWV", "TPSE"]
        self.customer_platforms = customer_platforms or ["BILT", "XXXX", "TWSF", "BBSF", "XOFF"]


DEFAULT_SWAPTION_PACKAGE_CONFIG = SwaptionPackageDetectionConfig()


def _extract_effective_premium(
    row: pd.Series,
    config: SwaptionPackageDetectionConfig,
) -> Tuple[float, str]:
    """
    Extract effective premium from a trade row.

    DEPRECATED: Use extract_effective_premium from swaption.utils instead.
    This wrapper is maintained for backward compatibility.
    """
    return extract_effective_premium(
        row,
        premium_col=config.premium_col,
        package_price_col=config.package_price_col,
        price_field_mode=config.price_field_mode,
    )


# =============================================================================
# Pipeline Phase Functions
# =============================================================================
# These helper functions encapsulate each detection phase of the pipeline.
# They are called by detect_and_link_swaption_packages_df in priority order.


def _price_risk_reversals(
    df: pd.DataFrame,
    package_col: str,
    pricer: "QLIRSwapCurve",
) -> pd.DataFrame:
    """
    Price risk reversal packages using merge-price-unmerge workflow.

    The pricer requires merged rows (one row per package with delimited
    fields), but downstream Parquet caching needs individual legs.
    We merge temporarily for pricing, then broadcast results back.

    Args:
        df: DataFrame with detected risk reversals
        package_col: Column name for package type
        pricer: QLIRSwapCurve instance for pricing

    Returns:
        DataFrame with pricing columns added to risk reversal legs
    """
    out = df
    rr_mask: pd.Series = out[package_col] == "RISK_REVERSAL"

    if not rr_mask.any():
        return out

    # Initialize pricing columns
    risk_reversal_pricing_cols = [
        "rr_atmf",
        "rr_out_strike",
        "rr_skew_bpvol",
        "rr_atm_bpvol",
        "rr_payer_skew",
        "rr_receiver_skew",
        "rr_dv01",
        "rr_wing_dv01",
        "rr_gamma01",
        "rr_vega01",
        "rr_theta1d",
    ]
    for col in risk_reversal_pricing_cols:
        if col not in out.columns:
            out[col] = np.nan

    # Step 1: Filter Risk Reversal legs (do NOT modify 'out' directly)
    rr_legs_subset = out.loc[rr_mask].copy()
    original_row_count = len(out)

    # Step 2: Merge legs into single rows for the pricer
    # This creates a temporary view where 4 legs become 1 row per package_id
    rr_merged_packages = merge_package_legs_to_one_row(rr_legs_subset)

    from SDRUtils.products._swaptions.pricer import (
        usd_swaption_dealer_risk_reversal_skew_from_row,
    )

    # Step 3: Calculate metrics on the MERGED rows
    metrics = []
    for idx, row in tqdm(
        rr_merged_packages.iterrows(),
        total=len(rr_merged_packages),
        desc="PRICING RISK REVERSALS...",
    ):
        try:
            res = usd_swaption_dealer_risk_reversal_skew_from_row(row, pricer)
            metrics.append(
                {
                    "package_id": row["package_id"],  # Key for joining back
                    "rr_atmf": res.atm_strike,
                    "rr_out_strike": int(res.wing_strike_width / 2),
                    "rr_skew_bpvol": res.skew_bpvol_yr,
                    "rr_atm_bpvol": res.atm_bpvol_yr,
                    "rr_payer_skew": res.payer_skew_bpvol_yr,
                    "rr_receiver_skew": res.receiver_skew_bpvol_yr,
                    "rr_dv01": res.dv01,
                    "rr_wing_dv01": res.wing_dv01,
                    "rr_gamma01": res.gamma01,
                    "rr_vega01": res.vega01,
                    "rr_theta1d": res.theta1d,
                }
            )
        except Exception as exc:
            logger.warning(
                "Failed to price risk reversal package %s: %s",
                row.get("package_id", idx),
                exc,
            )
            continue

    # Step 4: UNMERGE / JOIN back to the original leg-based dataframe
    # This ensures we support downstream Parquet caching which expects
    # the original leg structure.
    if metrics:
        metrics_df = pd.DataFrame(metrics)
        # Merge on package_id, broadcasting metrics to all legs
        out = out.merge(metrics_df, on="package_id", how="left", suffixes=("", "_new"))
        # Handle any column conflicts from merge
        for col in risk_reversal_pricing_cols:
            new_col = f"{col}_new"
            if new_col in out.columns:
                out[col] = out[new_col].combine_first(out[col])
                out.drop(columns=[new_col], inplace=True)

    # Verify row count unchanged (critical for Parquet compatibility)
    assert len(out) == original_row_count, f"Row count changed after RR pricing: {original_row_count} -> {len(out)}"

    return out


def _run_risk_reversal_phase(
    df: pd.DataFrame,
    config: SwaptionPackageDetectionConfig,
    product_col: str,
    package_col: str,
    pricer: Optional["QLIRSwapCurve"],
    # Risk reversal parameters
    risk_reversal_time_window_seconds: int,
    risk_reversal_strike_tolerance: float,
    risk_reversal_notional_tolerance_pct: float,
    risk_reversal_require_same_expiration: bool,
    risk_reversal_require_same_tenor: bool,
    risk_reversal_require_same_forward: bool,
    risk_reversal_require_directional_structure: bool,
    # Customer RR parameters
    detect_customer_rr_strangles: bool,
    customer_rr_timestamp_window_seconds: int,
    customer_rr_notional_tolerance_pct: float,
    customer_rr_width_tolerance_bps: float,
    customer_rr_benchmark_widths_bps: Optional[List[int]],
    customer_rr_platforms_filter: Optional[List[str]],
) -> pd.DataFrame:
    """
    Phase 1: Detect risk reversals (highest priority - IDB structures).

    This includes:
    - Inter-dealer 4-leg risk reversals
    - Pricing of detected risk reversals
    - Customer 2-leg RR/strangles with benchmark strike widths

    Args:
        df: Input DataFrame
        config: Detection configuration
        product_col: Column name for product type
        package_col: Column name for package type
        pricer: Optional pricer for Greeks calculation
        ... (other parameters passed through)

    Returns:
        DataFrame with risk reversal annotations and pricing
    """
    out = df

    # Detect inter-dealer risk reversals
    out = detect_risk_reversals_packages(
        out,
        time_window_seconds=risk_reversal_time_window_seconds,
        strike_tolerance=risk_reversal_strike_tolerance,
        notional_tolerance_pct=risk_reversal_notional_tolerance_pct,
        require_same_expiration=risk_reversal_require_same_expiration,
        require_same_tenor=risk_reversal_require_same_tenor,
        require_same_forward=risk_reversal_require_same_forward,
        require_directional_structure=risk_reversal_require_directional_structure,
        product_col=product_col,
        package_col=package_col,
        exec_col=config.exec_col,
        platform_col=config.platform_col,
        currency_col=config.currency_col,
        underlier_col=config.underlier_col,
        trade_id_col=config.trade_id_col,
        strike_col=config.strike_col,
        expiration_col=config.expiration_col,
        tenor_col=config.tenor_col,
        forward_col=config.forward_col,
        notional_col=config.notional_col,
        package_indicator_col=config.package_indicator_col,
        package_price_col=config.package_price_col,
        require_same_platform=config.require_same_platform,
        require_same_currency=config.require_same_currency,
        require_same_underlier=config.require_same_underlier,
        platform_allowlist=config.platform_allowlist,
        platform_blocklist=["XXXX", "XSEF", "XOFF", "BILT"],
    )

    # Price risk reversals if pricer is available
    if pricer is not None:
        out = _price_risk_reversals(out, package_col, pricer)

    # Customer RR/strangles: 2-leg payer+receiver with benchmark strike widths
    # custy trades will not be priced
    if detect_customer_rr_strangles:
        out = detect_customer_rr_strangles_packages(
            out,
            timestamp_window_seconds=customer_rr_timestamp_window_seconds,
            notional_tolerance_pct=customer_rr_notional_tolerance_pct,
            width_tolerance_bps=customer_rr_width_tolerance_bps,
            benchmark_widths_bps=customer_rr_benchmark_widths_bps,
            product_col=product_col,
            package_col=package_col,
            exec_col=config.exec_col,
            platform_col=config.platform_col,
            currency_col=config.currency_col,
            underlier_col=config.underlier_col,
            trade_id_col=config.trade_id_col,
            strike_col=config.strike_col,
            expiration_col=config.expiration_col,
            tenor_col=config.tenor_col,
            forward_col=config.forward_col,
            notional_col=config.notional_col,
            event_action_col="event_action",
            require_same_platform=config.require_same_platform,
            require_same_currency=config.require_same_currency,
            require_same_underlier=config.require_same_underlier,
            platforms_filter=customer_rr_platforms_filter or ["BILT", "TPSE", "XXXX"],
        )

    return out


def _price_straddles(
    df: pd.DataFrame,
    package_col: str,
    pricer: "QLIRSwapCurve",
) -> pd.DataFrame:
    """
    Price straddle packages.

    Columns are for the entire straddle not separate legs,
    metrics/rows will look duplicated before merged.

    Args:
        df: DataFrame with detected straddles
        package_col: Column name for package type
        pricer: QLIRSwapCurve instance for pricing

    Returns:
        DataFrame with pricing columns added to straddle legs
    """
    out = df

    straddle_pricing_cols: List[str] = [
        "straddle_bpvol_yr",
        "straddle_fwd_premium",
        "straddle_dv01",
        "straddle_vega01",
        "straddle_gamma01",
        "straddle_theta1d",
    ]
    for col in straddle_pricing_cols:
        if col not in out.columns:
            out[col] = np.nan

    straddle_mask: pd.Series = out[package_col] == "STRADDLE"
    if not straddle_mask.any():
        return out

    from SDRUtils.products._swaptions.pricer import (
        SingleStraddleLegException,
        usd_swaption_straddle_pricer_from_row,
    )

    def _price_straddle_row(row: pd.Series) -> Optional[USDSwaptionStraddlePricerResult]:
        if "SOFR" not in str(row["trade_label"]).upper():
            return None
        try:
            return usd_swaption_straddle_pricer_from_row(row, pricer)

        # kind of stupid but works
        except SingleStraddleLegException:
            try:
                row = row.copy()
                row["premium"] = row["premium"] * 2
                return usd_swaption_straddle_pricer_from_row(row, pricer)
            except Exception:
                return None
        except Exception:
            return None

    def _build_pricing_row(row: pd.Series) -> pd.Series:
        result = _price_straddle_row(row)
        if result is None:
            return pd.Series(
                {
                    "straddle_bpvol_yr": np.nan,
                    "straddle_fwd_premium": np.nan,
                    "straddle_dv01": np.nan,
                    "straddle_vega01": np.nan,
                    "straddle_gamma01": np.nan,
                    "straddle_theta1d": np.nan,
                }
            )
        return pd.Series(
            {
                "straddle_bpvol_yr": result.bpvol_yr,
                "straddle_fwd_premium": result.fwd_prem,
                "straddle_dv01": result.dv01,
                "straddle_vega01": result.vega01,
                "straddle_gamma01": result.gamma01,
                "straddle_theta1d": result.theta1d,
            }
        )

    rows = []
    index = []
    subset = out.loc[straddle_mask]
    for idx, row in tqdm(
        subset.iterrows(),
        total=len(subset),
        desc="PRICING STRADDLES...",
    ):
        rows.append(_build_pricing_row(row))
        index.append(idx)

    pricing_results = pd.DataFrame(rows, index=index)
    out.loc[straddle_mask, pricing_results.columns] = pricing_results

    return out


def _run_straddle_phase(
    df: pd.DataFrame,
    config: SwaptionPackageDetectionConfig,
    product_col: str,
    package_col: str,
    pricer: Optional["QLIRSwapCurve"],
    custy_straddle_timestamp_tolerance: datetime.timedelta,
) -> pd.DataFrame:
    """
    Phase 2: Detect straddles (payer + receiver with same strike/expiry/tenor).

    This includes:
    - Dealer + customer package-reported straddles
    - Customer straddle legs reported separately
    - Pricing of detected straddles

    Args:
        df: Input DataFrame
        config: Detection configuration
        product_col: Column name for product type
        package_col: Column name for package type
        pricer: Optional pricer for Greeks calculation
        custy_straddle_timestamp_tolerance: Max time between customer straddle legs

    Returns:
        DataFrame with straddle annotations and pricing
    """
    out = df

    # Dealers + custy package reported straddles
    out = detect_straddles_packages(
        out,
        timestamp_tolerance=datetime.timedelta(seconds=30),
        strike_tolerance=0,
        notional_tolerance_pct=0,
        product_col=product_col,
        package_col=package_col,
        exec_col=config.exec_col,
        platform_col=config.platform_col,
        currency_col=config.currency_col,
        underlier_col=config.underlier_col,
        trade_id_col=config.trade_id_col,
        strike_col=config.strike_col,
        expiration_col=config.expiration_col,
        tenor_col=config.tenor_col,
        notional_col=config.notional_col,
        package_indicator_col=config.package_indicator_col,
        require_same_platform=config.require_same_platform,
        require_same_currency=config.require_same_currency,
        require_same_underlier=config.require_same_underlier,
        must_be_reported_as_package=True,
    )

    # Custy straddle legs reported separately
    out = detect_straddles_packages(
        out,
        timestamp_tolerance=custy_straddle_timestamp_tolerance,
        strike_tolerance=0,
        notional_tolerance_pct=0,
        product_col=product_col,
        package_col=package_col,
        exec_col=config.exec_col,
        platform_col=config.platform_col,
        currency_col=config.currency_col,
        underlier_col=config.underlier_col,
        trade_id_col=config.trade_id_col,
        strike_col=config.strike_col,
        expiration_col=config.expiration_col,
        tenor_col=config.tenor_col,
        notional_col=config.notional_col,
        package_indicator_col=config.package_indicator_col,
        require_same_platform=config.require_same_platform,
        require_same_currency=config.require_same_currency,
        require_same_underlier=config.require_same_underlier,
        must_be_reported_as_package=False,
        add_leg_premiums=True,
        platforms_filter=["XXXX", "XSEF", "XOFF", "BILT"],
    )

    # Price straddles if pricer is available
    if pricer is not None:
        out = _price_straddles(out, package_col, pricer)

    return out


def _run_ladder_phase(
    df: pd.DataFrame,
    config: SwaptionPackageDetectionConfig,
    product_col: str,
    package_col: str,
    ladder_time_window_seconds: Optional[int],
    ladder_min_legs: int,
    ladder_min_strikes: int,
    ladder_min_strike_width_bps: float,
    ladder_notional_ratio_tolerance: float,
) -> pd.DataFrame:
    """
    Phase 3b: Detect ladders (christmas trees) - 3+ leg vertical structures.

    Ladders will not be priced, they are mostly custy trades.

    Args:
        df: Input DataFrame
        config: Detection configuration
        product_col: Column name for product type
        package_col: Column name for package type
        ladder_*: Ladder detection parameters

    Returns:
        DataFrame with ladder annotations
    """
    return detect_ladder_packages(
        df,
        time_window_seconds=ladder_time_window_seconds,
        min_legs=ladder_min_legs,
        min_strikes=ladder_min_strikes,
        min_strike_width_bps=ladder_min_strike_width_bps,
        notional_ratio_tolerance=ladder_notional_ratio_tolerance,
        product_col=product_col,
        package_col=package_col,
        exec_col=config.exec_col,
        platform_col=config.platform_col,
        currency_col=config.currency_col,
        underlier_col=config.underlier_col,
        trade_id_col=config.trade_id_col,
        strike_col=config.strike_col,
        expiration_col=config.expiration_col,
        tenor_col=config.tenor_col,
        forward_col=config.forward_col,
        notional_col=config.notional_col,
        premium_col=config.premium_col,
        package_indicator_col=config.package_indicator_col,
        require_same_platform=config.require_same_platform,
        require_same_currency=config.require_same_currency,
        require_same_underlier=config.require_same_underlier,
        platform_allowlist=config.platform_allowlist,
        platform_blocklist=config.platform_blocklist,
    )


def _price_vertical_spreads(
    df: pd.DataFrame,
    package_col: str,
    pricer: "QLIRSwapCurve",
) -> pd.DataFrame:
    """
    Price vertical spread packages using merge-price-unmerge workflow.

    The pricer requires merged rows (one row per package with delimited
    fields), but downstream Parquet caching needs individual legs.
    We merge temporarily for pricing, then broadcast results back.

    Args:
        df: DataFrame with detected vertical spreads
        package_col: Column name for package type
        pricer: QLIRSwapCurve instance for pricing

    Returns:
        DataFrame with pricing columns added to vertical spread legs
    """
    out = df
    vs_mask: pd.Series = out[package_col].astype(str).str.contains("VERTICAL_SPREAD", na=False)

    if not vs_mask.any():
        return out

    # Initialize pricing columns (prefixed with vs_ for vertical spread)
    vertical_spread_pricing_cols = [
        "vs_spread_type",
        "vs_atm_strike",
        "vs_otm_strike",
        "vs_strike_width_bps",
        "vs_atm_bpvol_yr",
        "vs_otm_bpvol_yr",
        "vs_vol_spread_bpvol_yr",
        "vs_atm_notional",
        "vs_otm_notional",
        "vs_notional_ratio",
        "vs_net_premium",
        "vs_atm_premium",
        "vs_otm_premium",
        "vs_atm_dv01",
        "vs_atm_gamma01",
        "vs_atm_vega01",
        "vs_atm_theta1d",
        "vs_otm_dv01",
        "vs_otm_gamma01",
        "vs_otm_vega01",
        "vs_otm_theta1d",
        "vs_dv01",
        "vs_gamma01",
        "vs_vega01",
        "vs_theta1d",
        "vs_atm_strike_offset",
        "vs_otm_strike_offset",
    ]
    for col in vertical_spread_pricing_cols:
        if col not in out.columns:
            out[col] = np.nan

    # Step 1: Filter Vertical Spread legs (do NOT modify 'out' directly)
    vs_legs_subset = out.loc[vs_mask].copy()
    original_row_count = len(out)

    # Step 2: Merge legs into single rows for the pricer
    # This creates a temporary view where 2 legs become 1 row per package_id
    vs_merged_packages = merge_package_legs_to_one_row(vs_legs_subset)

    from SDRUtils.products._swaptions.pricer import (
        usd_swaption_vertical_spread_pricer_from_row,
    )

    # Step 3: Calculate metrics on the MERGED rows
    metrics = []
    for idx, row in tqdm(
        vs_merged_packages.iterrows(),
        total=len(vs_merged_packages),
        desc="PRICING VERTICAL SPREADS...",
    ):
        try:
            res: USDSwaptionVerticalSpreadPricerResult = usd_swaption_vertical_spread_pricer_from_row(row, pricer)
            metrics.append(
                {
                    "package_id": row["package_id"],  # Key for joining back
                    "vs_spread_type": res.spread_type,
                    "vs_atm_strike": res.atm_strike,
                    "vs_otm_strike": res.otm_strike,
                    "vs_strike_width_bps": res.strike_width_bps,
                    "vs_atm_bpvol_yr": res.atm_bpvol_yr,
                    "vs_otm_bpvol_yr": res.otm_bpvol_yr,
                    "vs_vol_spread_bpvol_yr": res.vol_spread_bpvol_yr,
                    "vs_atm_notional": res.atm_notional,
                    "vs_otm_notional": res.otm_notional,
                    "vs_notional_ratio": res.notional_ratio,
                    "vs_net_premium": res.net_premium,
                    "vs_atm_premium": res.atm_premium,
                    "vs_otm_premium": res.otm_premium,
                    "vs_atm_dv01": res.atm_dv01,
                    "vs_atm_gamma01": res.atm_gamma01,
                    "vs_atm_vega01": res.atm_vega01,
                    "vs_atm_theta1d": res.atm_theta1d,
                    "vs_otm_dv01": res.otm_dv01,
                    "vs_otm_gamma01": res.otm_gamma01,
                    "vs_otm_vega01": res.otm_vega01,
                    "vs_otm_theta1d": res.otm_theta1d,
                    "vs_dv01": res.dv01,
                    "vs_gamma01": res.gamma01,
                    "vs_vega01": res.vega01,
                    "vs_theta1d": res.theta1d,
                    "vs_atm_strike_offset": res.atm_strike_offset,
                    "vs_otm_strike_offset": res.otm_strike_offset,
                }
            )
        except Exception as exc:
            logger.warning(
                "Failed to price vertical spread package %s: %s",
                row.get("package_id", idx),
                exc,
            )
            continue

    # Step 4: UNMERGE / JOIN back to the original leg-based dataframe
    # This ensures we support downstream Parquet caching which expects
    # the original leg structure.
    if metrics:
        metrics_df = pd.DataFrame(metrics)
        # Merge on package_id, broadcasting metrics to all legs
        out = out.merge(metrics_df, on="package_id", how="left", suffixes=("", "_new"))
        # Handle any column conflicts from merge
        for col in vertical_spread_pricing_cols:
            new_col = f"{col}_new"
            if new_col in out.columns:
                out[col] = out[new_col].combine_first(out[col])
                out.drop(columns=[new_col], inplace=True)

    # Verify row count unchanged (critical for Parquet compatibility)
    assert len(out) == original_row_count, f"Row count changed after VS pricing: {original_row_count} -> {len(out)}"

    return out


def _run_vertical_spread_phase(
    df: pd.DataFrame,
    config: SwaptionPackageDetectionConfig,
    product_col: str,
    package_col: str,
    pricer: Optional["QLIRSwapCurve"],
    vertical_spread_time_window_seconds: int,
) -> pd.DataFrame:
    """
    Phase 3a: Detect vertical spreads (1x1, 1x2, etc. - same tenor, different strikes).

    This includes:
    - Detection of vertical spread packages
    - Pricing of detected spreads using merge-price-unmerge workflow

    Args:
        df: Input DataFrame
        config: Detection configuration
        product_col: Column name for product type
        package_col: Column name for package type
        pricer: Optional pricer for Greeks calculation
        vertical_spread_time_window_seconds: Max time gap between spread legs

    Returns:
        DataFrame with vertical spread annotations and pricing
    """
    out = detect_vertical_spreads_packages(
        df,
        time_window_seconds=vertical_spread_time_window_seconds,
        spread_ratios=config.spread_ratios,
        min_strike_width=config.vertical_spread_min_strike_width,
        product_col=product_col,
        package_col=package_col,
        exec_col=config.exec_col,
        platform_col=config.platform_col,
        currency_col=config.currency_col,
        underlier_col=config.underlier_col,
        trade_id_col=config.trade_id_col,
        strike_col=config.strike_col,
        expiration_col=config.expiration_col,
        tenor_col=config.tenor_col,
        forward_col=config.forward_col,
        notional_col=config.notional_col,
        package_indicator_col=config.package_indicator_col,
        require_same_platform=config.require_same_platform,
        require_same_currency=config.require_same_currency,
        require_same_underlier=config.require_same_underlier,
        platform_allowlist=config.platform_allowlist,
        platform_blocklist=config.platform_blocklist,
    )

    # Price vertical spreads if pricer is available
    if pricer is not None:
        out = _price_vertical_spreads(out, package_col, pricer)

    return out


def _run_vega_curve_phase(
    df: pd.DataFrame,
    config: SwaptionPackageDetectionConfig,
    product_col: str,
    package_col: str,
    pricer: Optional["QLIRSwapCurve"],
    vega_curve_time_window_seconds: int,
) -> pd.DataFrame:
    """
    Phase 5: Detect vega curve trades (vega-matched straddles across tenors).

    Requires straddles to be detected first.

    Args:
        df: Input DataFrame
        config: Detection configuration
        product_col: Column name for product type
        package_col: Column name for package type
        pricer: Optional pricer for vega calculation
        vega_curve_time_window_seconds: Max time gap between vega curve straddles

    Returns:
        DataFrame with vega curve annotations
    """
    return detect_vega_curve_packages(
        df,
        time_window_seconds=vega_curve_time_window_seconds,
        vega_tolerance_pct=config.vega_curve_tolerance_pct,
        min_expiry_diff_years=config.vega_curve_min_expiry_diff_years,
        min_tail_diff_years=config.vega_curve_min_tail_diff_years,
        product_col=product_col,
        package_col=package_col,
        exec_col=config.exec_col,
        platform_col=config.platform_col,
        currency_col=config.currency_col,
        trade_id_col=config.trade_id_col,
        trade_label_col=config.trade_label_col,
        tenor_col=config.tenor_col,
        forward_col=config.forward_col,
        notional_col=config.notional_col,
        premium_col=config.premium_col,
        require_same_platform=config.require_same_platform,
        require_same_currency=config.require_same_currency,
        pricer=pricer,
    )


def _run_delta_hedge_phase(
    df: pd.DataFrame,
    config: SwaptionPackageDetectionConfig,
    product_col: str,
    package_col: str,
    pricer: Optional["QLIRSwapCurve"],
    swap_candidates_df: pd.DataFrame,
    timestamp_windows: Sequence[int],
    delta_hedge_tenor_tolerance_years: float,
    delta_hedge_implied_delta_min: float,
    delta_hedge_implied_delta_max: float,
    delta_hedge_strike_proximity_bps: float,
    delta_hedge_dv01_tolerance: float,
    require_swaption_package_indicator_for_delta_hedge: bool,
    require_swap_package_indicator_for_delta_hedge: bool,
    delta_hedge_require_same_platform: bool,
    delta_hedge_check_dv01: bool,
    # --- barbell parameters ---
    enable_barbell: bool = True,
    barbell_risk_models: Optional[Dict] = None,
    barbell_tenor_tolerance: float = 1.0,
    barbell_time_half_life: float = 30.0,
) -> pd.DataFrame:
    """
    Phase 5.5: Detect swaption + USD swap delta-hedge packages.

    Runs after vega-curve and before outright classification. This phase only
    consumes still-unpackaged swaptions. Enhanced with barbell decomposition
    to detect multi-leg spot swap hedges of forward swaption deltas.

    Pricing consistency checks remain SOFR-pricer based where supported.
    """
    if swap_candidates_df is None or swap_candidates_df.empty:
        return df

    return detect_delta_hedge_packages(
        df,
        swap_candidates_df,
        timestamp_windows=timestamp_windows,
        tenor_tolerance_years=delta_hedge_tenor_tolerance_years,
        implied_delta_min=delta_hedge_implied_delta_min,
        implied_delta_max=delta_hedge_implied_delta_max,
        strike_proximity_bps=delta_hedge_strike_proximity_bps,
        dv01_tolerance=delta_hedge_dv01_tolerance,
        require_swaption_package_indicator=require_swaption_package_indicator_for_delta_hedge,
        require_swap_package_indicator=require_swap_package_indicator_for_delta_hedge,
        require_same_platform=delta_hedge_require_same_platform,
        check_dv01=delta_hedge_check_dv01,
        pricer=pricer,
        product_col=product_col,
        package_col=package_col,
        exec_col=config.exec_col,
        trade_id_col=config.trade_id_col,
        platform_col=config.platform_col,
        underlier_col=config.underlier_col,
        package_indicator_col=config.package_indicator_col,
        tenor_col=config.tenor_col,
        notional_col=config.notional_col,
        strike_col=config.strike_col,
        premium_col=config.premium_col,
        trade_label_col=config.trade_label_col,
        expiration_col=config.expiration_col,
        underlying_expiration_col=config.tail_maturity_col,
        enable_barbell=enable_barbell,
        barbell_risk_models=barbell_risk_models,
        barbell_tenor_tolerance=barbell_tenor_tolerance,
        barbell_time_half_life=barbell_time_half_life,
    )


def _price_outrights(
    df: pd.DataFrame,
    package_col: str,
    pricer: "QLIRSwapCurve",
) -> pd.DataFrame:
    """
    Price outright packages.

    Outrights are single-leg trades, so we use the direct row iteration
    pattern (same as straddles) rather than merge-price-unmerge.

    Args:
        df: DataFrame with detected outrights
        package_col: Column name for package type
        pricer: QLIRSwapCurve instance for pricing

    Returns:
        DataFrame with pricing columns added to outright legs
    """
    out = df

    outright_pricing_cols: List[str] = [
        "outright_bpvol_yr",
        "outright_fwd_premium",
        "outright_dv01",
        "outright_vega01",
        "outright_gamma01",
        "outright_theta1d",
    ]
    for col in outright_pricing_cols:
        if col not in out.columns:
            out[col] = np.nan

    outright_mask: pd.Series = out[package_col] == "OUTRIGHT"
    if not outright_mask.any():
        return out

    from SDRUtils.products._swaptions.pricer import usd_swaption_leg_pricer_from_row

    def _price_outright_row(row: pd.Series) -> Optional[USDSwaptionLegPricerResult]:
        if "SOFR" not in str(row["trade_label"]).upper():
            return None
        try:
            return usd_swaption_leg_pricer_from_row(row, pricer)
        except Exception:
            return None

    def _build_outright_pricing_row(row: pd.Series) -> pd.Series:
        result = _price_outright_row(row)
        if result is None:
            return pd.Series(
                {
                    "outright_bpvol_yr": np.nan,
                    "outright_fwd_premium": np.nan,
                    "outright_dv01": np.nan,
                    "outright_vega01": np.nan,
                    "outright_gamma01": np.nan,
                    "outright_theta1d": np.nan,
                }
            )
        return pd.Series(
            {
                "outright_bpvol_yr": result.bpvol_yr,
                "outright_fwd_premium": result.fwd_prem,
                "outright_dv01": result.dv01,
                "outright_vega01": result.vega01,
                "outright_gamma01": result.gamma01,
                "outright_theta1d": result.theta1d,
            }
        )

    rows = []
    index = []
    subset = out.loc[outright_mask]
    for idx, row in tqdm(
        subset.iterrows(),
        total=len(subset),
        desc="PRICING OUTRIGHTS...",
    ):
        rows.append(_build_outright_pricing_row(row))
        index.append(idx)

    if rows:
        pricing_results = pd.DataFrame(rows, index=index)
        out.loc[outright_mask, pricing_results.columns] = pricing_results

    return out


def _run_outright_phase(
    df: pd.DataFrame,
    config: SwaptionPackageDetectionConfig,
    product_col: str,
    package_col: str,
    pricer: Optional["QLIRSwapCurve"],
    outright_offset_tolerance_bps: float,
    outright_platforms_filter: Optional[List[str]],
) -> pd.DataFrame:
    """
    Phase 6: Detect and enrich outright/unexplained trades.

    This runs last to capture all trades not matched by previous detectors.

    Args:
        df: Input DataFrame
        config: Detection configuration
        product_col: Column name for product type
        package_col: Column name for package type
        pricer: Optional pricer for Greeks calculation
        outright_offset_tolerance_bps: Tolerance for ATMF offset benchmark matching
        outright_platforms_filter: Platforms to consider for outright detection

    Returns:
        DataFrame with outright annotations and pricing
    """
    out = detect_outright_swaptions(
        df,
        pricer=pricer,
        benchmark_offsets_bps=None,  # Use default benchmarks
        offset_tolerance_bps=outright_offset_tolerance_bps,
        product_col=product_col,
        package_col=package_col,
        trade_id_col=config.trade_id_col,
        strike_col=config.strike_col,
        expiration_col=config.expiration_col,
        underlying_expiration_col=config.tail_maturity_col,
        notional_col=config.notional_col,
        trade_label_col=config.trade_label_col,
        platforms_filter=outright_platforms_filter,
        platform_col=config.platform_col,
    )

    # Price outrights if pricer is available
    if pricer is not None:
        out = _price_outrights(out, package_col, pricer)

    return out


def detect_and_link_swaption_packages_df(
    df: pd.DataFrame,
    *,
    # Config (DEPRECATED - use explicit kwargs instead)
    config: Optional[SwaptionPackageDetectionConfig] = None,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    # Detection flags
    detect_risk_reversals: bool = True,
    detect_straddles: bool = True,
    detect_vertical_spreads: bool = True,
    detect_conditional_curve: bool = True,
    detect_vega_curve: bool = True,
    # Straddle parameters
    custy_straddle_timestamp_tolerance: datetime.timedelta = datetime.timedelta(seconds=60),
    # Risk reversal parameters (inter-dealer 4-leg)
    risk_reversal_time_window_seconds: int = 60 * 60,
    risk_reversal_strike_tolerance: float = 0.0001,
    risk_reversal_notional_tolerance_pct: float = 0.05,
    risk_reversal_require_same_expiration: bool = True,
    risk_reversal_require_same_tenor: bool = True,
    risk_reversal_require_same_forward: bool = True,
    risk_reversal_require_directional_structure: bool = True,
    # Customer RR/strangle parameters (2-leg)
    detect_customer_rr_strangles: bool = True,
    customer_rr_timestamp_window_seconds: int = 60 * 60,
    customer_rr_notional_tolerance_pct: float = 0.01,
    customer_rr_width_tolerance_bps: float = 3.0,
    customer_rr_benchmark_widths_bps: Optional[List[int]] = None,
    customer_rr_platforms_filter: Optional[List[str]] = None,
    # Vertical spread parameters
    vertical_spread_time_window_seconds: int = 300,
    # Ladder parameters (3+ leg christmas tree structures)
    detect_ladders: bool = True,
    ladder_time_window_seconds: Optional[int] = 300,  # None = use platform-specific defaults
    ladder_min_legs: int = 3,
    ladder_min_strikes: int = 3,
    ladder_min_strike_width_bps: float = 10.0,
    ladder_notional_ratio_tolerance: float = 0.15,
    # Conditional curve parameters
    conditional_curve_time_window_seconds: int = 300,
    # Vega curve parameters
    vega_curve_time_window_seconds: int = 300,
    # Delta-hedge parameters
    detect_delta_hedges: bool = True,
    swap_candidates_df: Optional[pd.DataFrame] = None,
    delta_hedge_timestamp_windows: Sequence[int] = (1, 5, 60),
    delta_hedge_tenor_tolerance_years: float = 0.50,
    delta_hedge_implied_delta_min: float = 0.20,
    delta_hedge_implied_delta_max: float = 0.80,
    delta_hedge_strike_proximity_bps: float = 50.0,
    delta_hedge_dv01_tolerance: float = 0.20,
    require_swaption_package_indicator_for_delta_hedge: bool = True,
    require_swap_package_indicator_for_delta_hedge: bool = True,
    delta_hedge_require_same_platform: bool = False,
    delta_hedge_check_dv01: bool = True,
    pricer: Optional["QLIRSwapCurve"] = None,
    # Barbell decomposition parameters (delta-hedge enhancement)
    enable_barbell: bool = True,
    barbell_risk_models: Optional[Dict] = None,
    barbell_tenor_tolerance: float = 1.0,
    barbell_time_half_life: float = 30.0,
    # Outright/unexplained detection parameters
    detect_outrights: bool = True,
    outright_offset_tolerance_bps: float = 7.5,
    outright_platforms_filter: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Combined detection and linking of swaption packages.

    This is the main entry point for swaption package detection using a
    pipeline pattern. Detectors are run in sequence, with each detector
    only processing trades not already assigned to a package.

    Detection order (priority):
    1. Risk reversals (4 legs / 3 strikes / 2 notionals) - IDB structures
    1b. Customer RR/strangles (2 legs / payer+receiver / benchmark strike widths)
    2. Straddles (payer + receiver with same strike/expiry/tenor)
    3. Vertical spreads (1x1, 1x2, 1x1.5, etc. - same tenor, different strikes)
    3b. Ladders (3+ legs / christmas trees - same tenor, 3+ strikes, asymmetric notionals)
    4. Conditional curve trades (same expiry, different tails)
    5. Vega curve trades (vega-matched straddles across tenors)
    5.5. Delta-hedges (swaption + USD swap pairs)
    6. Outrights (unexplained single-leg trades, enriched with ATMF offset)

    To add a new structure type (e.g., Iron Condors):
    1. Create SDRUtils/packages/swaption/condor.py with detect_iron_condors()
    2. Add to the pipeline list in this function
    3. Import and register in SDRUtils/packages/swaption/__init__.py

    Args:
        df: Classifications dataframe with swaption trades
        config: DEPRECATED - Detection configuration object
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
        risk_reversal_strike_tolerance: Absolute strike tolerance for RR matching
        risk_reversal_notional_tolerance_pct: Relative notional tolerance
        risk_reversal_middle_notional_max_ratio: Max ratio of middle to wing notional
        risk_reversal_require_same_expiration: Require same expiration across legs
        risk_reversal_require_same_tenor: Require same tenor across legs
        risk_reversal_require_same_forward: Require same forward across legs
        risk_reversal_require_directional_structure: Require payer/receiver alignment
        detect_customer_rr_strangles: Whether to detect customer RR/strangles (default True)
        customer_rr_timestamp_window_seconds: Max time gap for customer RR/strangle legs
        customer_rr_notional_tolerance_pct: Notional tolerance for customer RR/strangle
        customer_rr_width_tolerance_bps: Strike width tolerance in basis points
        customer_rr_benchmark_widths_bps: List of benchmark widths (default: standard)
        customer_rr_platforms_filter: Platforms to consider for customer RR/strangles
        vertical_spread_time_window_seconds: Max time gap between spread legs
        detect_ladders: Whether to detect ladder/christmas tree structures (default True)
        ladder_time_window_seconds: Override platform-specific time windows (None = auto)
        ladder_min_legs: Minimum legs to qualify as ladder (default 3)
        ladder_min_strikes: Minimum distinct strikes (default 3)
        ladder_min_strike_width_bps: Minimum strike separation in bps (default 15)
        ladder_notional_ratio_tolerance: Tolerance for notional ratio matching (default 0.15)
        conditional_curve_time_window_seconds: Max time gap between curve legs
        vega_curve_time_window_seconds: Max time gap between vega curve straddles
        detect_delta_hedges: Whether to run swaption/swap delta-hedge detection
        swap_candidates_df: Raw USD swap candidates (same date slice as df)
        delta_hedge_timestamp_windows: Candidate time windows in seconds (searched in order)
        delta_hedge_tenor_tolerance_years: Max swaption/swap tenor mismatch in years
        delta_hedge_implied_delta_min: Minimum allowed implied-delta notional ratio
        delta_hedge_implied_delta_max: Maximum allowed implied-delta notional ratio
        delta_hedge_strike_proximity_bps: Strike/fixed-rate proximity bonus threshold
        delta_hedge_dv01_tolerance: Allowed |dv01_ratio - implied_delta| for PASS
        require_swaption_package_indicator_for_delta_hedge: Require package flag on swaptions
        require_swap_package_indicator_for_delta_hedge: Require package flag on swap hedges
        delta_hedge_require_same_platform: Require swaption/swap platform to match
        delta_hedge_check_dv01: Run soft DV01 validation on matched pairs
        pricer: Optional QLIRSwapCurve instance for vega/skew calculation
        detect_outrights: Whether to detect and enrich outright trades (default True)
        outright_offset_tolerance_bps: Tolerance for ATMF offset benchmark matching
        outright_platforms_filter: Platforms to consider for outright detection

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
        - custy_rr_width_bps: For customer RR/strangles, the benchmark strike width
        - ladder_structure: For ladders, structure label (e.g., "1x1x2", "2x1x1")
        - ladder_direction: For ladders, "BULL" or "BEAR"
        - ladder_strikes: For ladders, list of strikes
        - ladder_notionals: For ladders, list of notionals per strike
        - delta_hedge_implied_delta: Implied hedge ratio from notional
        - delta_hedge_swap_trade_id: Raw SDR trade id for hedge swap
        - delta_hedge_swap_fixed_rate: Hedge swap fixed rate
        - delta_hedge_swap_tenor_years: Hedge swap tenor in years
        - delta_hedge_swap_notional: Hedge swap notional
        - delta_hedge_match_window_seconds: Matching timestamp window used
        - delta_hedge_dv01_ratio: |swap_dv01 / swaption_dv01| when available
        - delta_hedge_dv01_check: PASS/FAIL/SKIP status for DV01 consistency check
        - outright_atmf: For outrights, the ATMF rate
        - outright_strike_offset_bps: For outrights, raw offset from ATMF in bps
        - outright_strike_offset_rounded_bps: For outrights, offset rounded to benchmark
        - outright_moneyness: For outrights, "ATM", "OTM_PAYER", "OTM_RECEIVER", etc.
        - outright_bpvol_yr: For outrights, implied volatility in basis points per year
        - outright_fwd_premium: For outrights, forward premium used for pricing
        - outright_dv01: For outrights, delta per 1bp rate move
        - outright_vega01: For outrights, vega per 1bp vol move
        - outright_gamma01: For outrights, gamma (delta sensitivity to rates)
        - outright_theta1d: For outrights, theta decay per 1 day
    """
    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    # =========================================================================
    # Pipeline: Run detectors in priority order
    # =========================================================================
    # Each detector processes only unpackaged trades, leaving a "pool" of
    # remaining trades for subsequent detectors.

    # Phase 1: Detect risk reversals (highest priority - IDB structures)
    if detect_risk_reversals:
        out = _run_risk_reversal_phase(
            out,
            config=config,
            product_col=product_col,
            package_col=package_col,
            pricer=pricer,
            risk_reversal_time_window_seconds=risk_reversal_time_window_seconds,
            risk_reversal_strike_tolerance=risk_reversal_strike_tolerance,
            risk_reversal_notional_tolerance_pct=risk_reversal_notional_tolerance_pct,
            risk_reversal_require_same_expiration=risk_reversal_require_same_expiration,
            risk_reversal_require_same_tenor=risk_reversal_require_same_tenor,
            risk_reversal_require_same_forward=risk_reversal_require_same_forward,
            risk_reversal_require_directional_structure=risk_reversal_require_directional_structure,
            detect_customer_rr_strangles=detect_customer_rr_strangles,
            customer_rr_timestamp_window_seconds=customer_rr_timestamp_window_seconds,
            customer_rr_notional_tolerance_pct=customer_rr_notional_tolerance_pct,
            customer_rr_width_tolerance_bps=customer_rr_width_tolerance_bps,
            customer_rr_benchmark_widths_bps=customer_rr_benchmark_widths_bps,
            customer_rr_platforms_filter=customer_rr_platforms_filter,
        )

    # Phase 2: Detect straddles
    if detect_straddles:
        out = _run_straddle_phase(
            out,
            config=config,
            product_col=product_col,
            package_col=package_col,
            pricer=pricer,
            custy_straddle_timestamp_tolerance=custy_straddle_timestamp_tolerance,
        )

    # Phase 3b: Detect ladders (christmas trees) - 3+ leg vertical structures
    if detect_ladders:
        out = _run_ladder_phase(
            out,
            config=config,
            product_col=product_col,
            package_col=package_col,
            ladder_time_window_seconds=ladder_time_window_seconds,
            ladder_min_legs=ladder_min_legs,
            ladder_min_strikes=ladder_min_strikes,
            ladder_min_strike_width_bps=ladder_min_strike_width_bps,
            ladder_notional_ratio_tolerance=ladder_notional_ratio_tolerance,
        )

    # Phase 3a: Detect vertical spreads (1x1, 1x2, etc.)
    if detect_vertical_spreads:
        out = _run_vertical_spread_phase(
            out,
            config=config,
            product_col=product_col,
            package_col=package_col,
            pricer=pricer,
            vertical_spread_time_window_seconds=vertical_spread_time_window_seconds,
        )

    # Phase 4: Conditional curve detection (same expiry, different tails)
    # Note: detect_conditional_curve parameter reserved for future implementation

    # Phase 5: Detect vega curve trades (requires straddles to be detected first)
    if detect_vega_curve and detect_straddles:
        out = _run_vega_curve_phase(
            out,
            config=config,
            product_col=product_col,
            package_col=package_col,
            pricer=pricer,
            vega_curve_time_window_seconds=vega_curve_time_window_seconds,
        )

    # Phase 5.5: Detect swaption + swap delta-hedges for still-unpackaged rows
    if detect_delta_hedges and swap_candidates_df is not None and not swap_candidates_df.empty:
        out = _run_delta_hedge_phase(
            out,
            config=config,
            product_col=product_col,
            package_col=package_col,
            pricer=pricer,
            swap_candidates_df=swap_candidates_df,
            timestamp_windows=delta_hedge_timestamp_windows,
            delta_hedge_tenor_tolerance_years=delta_hedge_tenor_tolerance_years,
            delta_hedge_implied_delta_min=delta_hedge_implied_delta_min,
            delta_hedge_implied_delta_max=delta_hedge_implied_delta_max,
            delta_hedge_strike_proximity_bps=delta_hedge_strike_proximity_bps,
            delta_hedge_dv01_tolerance=delta_hedge_dv01_tolerance,
            require_swaption_package_indicator_for_delta_hedge=require_swaption_package_indicator_for_delta_hedge,
            require_swap_package_indicator_for_delta_hedge=require_swap_package_indicator_for_delta_hedge,
            delta_hedge_require_same_platform=delta_hedge_require_same_platform,
            delta_hedge_check_dv01=delta_hedge_check_dv01,
            enable_barbell=enable_barbell,
            barbell_risk_models=barbell_risk_models,
            barbell_tenor_tolerance=barbell_tenor_tolerance,
            barbell_time_half_life=barbell_time_half_life,
        )

    # Phase 6: Detect and enrich outright/unexplained trades
    # This runs last to capture all trades not matched by previous detectors
    if detect_outrights:
        out = _run_outright_phase(
            out,
            config=config,
            product_col=product_col,
            package_col=package_col,
            pricer=pricer,
            outright_offset_tolerance_bps=outright_offset_tolerance_bps,
            outright_platforms_filter=outright_platforms_filter,
        )

    return out


# =============================================================================
# Backward Compatibility Wrappers
# =============================================================================


def detect_swaption_packages_df(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Backward-compatible alias for the main detection pipeline.
    """
    return detect_and_link_swaption_packages_df(df, config=config, **kwargs)


def detect_swaption_straddles_df(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    straddle_timestamp_tolerance: datetime.timedelta = datetime.timedelta(seconds=60),
    product_col: str = "product_type",
    package_col: str = "package_type",
    pricer: Optional["QLIRSwapCurve"] = None,
    **_: Any,
) -> pd.DataFrame:
    """
    Backward-compatible wrapper for straddle-only detection.
    """
    cfg = config or DEFAULT_SWAPTION_PACKAGE_CONFIG
    return _run_straddle_phase(
        df,
        config=cfg,
        product_col=product_col,
        package_col=package_col,
        pricer=pricer,
        custy_straddle_timestamp_tolerance=straddle_timestamp_tolerance,
    )


def detect_swaption_vertical_spreads_df(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
    pricer: Optional["QLIRSwapCurve"] = None,
    vertical_spread_time_window_seconds: int = 300,
    **_: Any,
) -> pd.DataFrame:
    """
    Backward-compatible wrapper for vertical-spread detection.
    """
    cfg = config or DEFAULT_SWAPTION_PACKAGE_CONFIG
    return _run_vertical_spread_phase(
        df,
        config=cfg,
        product_col=product_col,
        package_col=package_col,
        pricer=pricer,
        vertical_spread_time_window_seconds=vertical_spread_time_window_seconds,
    )


def detect_swaption_conditional_curve_df(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
    conditional_curve_time_window_seconds: int = 300,
    **_: Any,
) -> pd.DataFrame:
    """
    Backward-compatible wrapper for conditional-curve detection.
    """
    cfg = config or DEFAULT_SWAPTION_PACKAGE_CONFIG
    return detect_conditional_curve_packages(
        df,
        time_window_seconds=conditional_curve_time_window_seconds,
        min_tail_diff_years=cfg.conditional_curve_min_tail_diff_years,
        product_col=product_col,
        package_col=package_col,
        exec_col=cfg.exec_col,
        platform_col=cfg.platform_col,
        currency_col=cfg.currency_col,
        underlier_col=cfg.underlier_col,
        trade_id_col=cfg.trade_id_col,
        expiration_col=cfg.expiration_col,
        tail_maturity_col=cfg.tail_maturity_col,
        notional_col=cfg.notional_col,
        package_indicator_col=cfg.package_indicator_col,
        require_same_platform=cfg.require_same_platform,
        require_same_currency=cfg.require_same_currency,
        require_same_underlier=cfg.require_same_underlier,
        platform_allowlist=cfg.platform_allowlist,
        platform_blocklist=cfg.platform_blocklist,
    )


def detect_swaption_vega_curve_df(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    product_col: str = "product_type",
    package_col: str = "package_type",
    pricer: Optional["QLIRSwapCurve"] = None,
    vega_curve_time_window_seconds: int = 300,
    **_: Any,
) -> pd.DataFrame:
    """
    Backward-compatible wrapper for vega-curve detection.
    """
    cfg = config or DEFAULT_SWAPTION_PACKAGE_CONFIG
    return _run_vega_curve_phase(
        df,
        config=cfg,
        product_col=product_col,
        package_col=package_col,
        pricer=pricer,
        vega_curve_time_window_seconds=vega_curve_time_window_seconds,
    )


def link_swaption_packages(
    df: pd.DataFrame,
    *,
    config: Optional[SwaptionPackageDetectionConfig] = None,
    package_col: str = "package_type",
    **_: Any,
) -> pd.DataFrame:
    """
    Backward-compatible wrapper for package linking.
    """
    cfg = config or DEFAULT_SWAPTION_PACKAGE_CONFIG
    return link_packages(
        df,
        time_window_link_seconds=cfg.time_window_link_seconds,
        vega_tolerance_pct=cfg.vega_tolerance_pct,
        package_col=package_col,
        exec_col=cfg.exec_col,
        platform_col=cfg.platform_col,
        currency_col=cfg.currency_col,
        require_same_platform=cfg.require_same_platform,
        require_same_currency=cfg.require_same_currency,
    )


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


# =============================================================================
# Module Exports
# =============================================================================
# Public API:
#   - detect_and_link_swaption_packages_df: Main detection pipeline function
#   - SwaptionPackageDetector: Class interface for registry integration
#
# Deprecated (maintained for backward compatibility):
#   - SwaptionPackageDetectionConfig: Use explicit kwargs instead
#   - DEFAULT_SWAPTION_PACKAGE_CONFIG: Use explicit kwargs instead
#   - _vega_bucket, _time_bucket, etc.: Import from swaption.utils instead
#
# For new code, import utilities directly from SDRUtils.packages.swaption.utils

__all__ = [
    # Public API
    "detect_swaption_packages_df",
    "detect_swaption_straddles_df",
    "detect_swaption_vertical_spreads_df",
    "detect_swaption_conditional_curve_df",
    "detect_swaption_vega_curve_df",
    "link_swaption_packages",
    "detect_and_link_swaption_packages_df",
    "SwaptionPackageDetector",
    # Deprecated - config class (prefer explicit kwargs)
    "SwaptionPackageDetectionConfig",
    "DEFAULT_SWAPTION_PACKAGE_CONFIG",
    # Deprecated - utility aliases (prefer SDRUtils.packages.swaption.utils)
    "_vega_bucket",
    "_time_bucket",
    "_extract_effective_premium",
    "_compute_package_id",
    "_estimate_swaption_vega",
]
