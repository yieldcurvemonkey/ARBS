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
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from tqdm import tqdm

import numpy as np
import pandas as pd

from SDRUtils.packages.base import PackageDetector

# Import detection functions from submodules
from SDRUtils.packages.swaption.straddle import detect_straddles_packages
from SDRUtils.packages.swaption.risk_reversal import detect_risk_reversals_packages
from SDRUtils.packages.swaption.spreads import detect_vertical_spreads_packages
from SDRUtils.packages.swaption.conditional_curve import detect_conditional_curve_packages
from SDRUtils.packages.swaption.vega_curve import detect_vega_curve_packages
from SDRUtils.packages.swaption.vega_buckets import detect_vega_bucketed_packages
from SDRUtils.packages.swaption.linking import link_packages
from SDRUtils.packages.swaption.customer_rr_strangle import detect_customer_rr_strangles_packages

# Import utility functions for backward compatibility
from SDRUtils.packages.swaption.utils import (
    vega_bucket as _vega_bucket,
    time_bucket as _time_bucket,
    safe_float as _safe_float,
    compute_package_id as _compute_package_id,
    build_package_reason as _build_package_reason,
    estimate_swaption_vega as _estimate_swaption_vega,
    extract_effective_premium,
)
from SDRUtils.packages.utils import merge_package_legs_to_one_row
from SDRUtils.products._swaptions.pricer import (
    USDSwaptionDealerRiskReversalSkewResult,
    USDSwaptionStraddlePricerResult,
    SingleStraddleLegException,
    usd_swaption_dealer_risk_reversal_skew_from_row,
    usd_swaption_straddle_pricer_from_row,
)

if TYPE_CHECKING:
    from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve


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
    customer_rr_timestamp_window_seconds: int = 5,
    customer_rr_notional_tolerance_pct: float = 0.01,
    customer_rr_width_tolerance_bps: float = 3.0,
    customer_rr_benchmark_widths_bps: Optional[List[int]] = None,
    customer_rr_platforms_filter: Optional[List[str]] = None,
    # Vertical spread parameters
    vertical_spread_time_window_seconds: int = 120,
    # Conditional curve parameters
    conditional_curve_time_window_seconds: int = 300,
    # Vega curve parameters
    vega_curve_time_window_seconds: int = 300,
    pricer: Optional["QLIRSwapCurve"] = None,
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
    4. Conditional curve trades (same expiry, different tails)
    5. Vega curve trades (vega-matched straddles across tenors)

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
        conditional_curve_time_window_seconds: Max time gap between curve legs
        vega_curve_time_window_seconds: Max time gap between vega curve straddles
        pricer: Optional QLIRSwapCurve instance for vega/skew calculation

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
    """
    if config is None:
        config = DEFAULT_SWAPTION_PACKAGE_CONFIG

    out = df.copy()

    # temp = out.copy()
    # temp = temp.sort_values(by="execution_timestamp")
    # temp["execution_timestamp"] = temp["execution_timestamp"].astype(str)
    # temp.to_excel("_temp_raw_trades.xlsx")

    # =========================================================================
    # Pipeline: Run detectors in priority order
    # =========================================================================
    # Each detector processes only unpackaged trades, leaving a "pool" of
    # remaining trades for subsequent detectors.

    # Phase 1: Detect risk reversals first (highest priority - IDB structures)
    if detect_risk_reversals:
        # interdealer risk reversals
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
            require_same_platform=config.require_same_platform,
            require_same_currency=config.require_same_currency,
            require_same_underlier=config.require_same_underlier,
            platform_allowlist=config.platform_allowlist,
            platform_blocklist=["XXXX", "XSEF", "XOFF", "BILT"], 
        )

        # =================================================================
        # Merge-Price-Unmerge workflow for Risk Reversal skew & Greeks
        # =================================================================
        # The pricer requires merged rows (one row per package with delimited
        # fields), but downstream Parquet caching needs individual legs.
        # We merge temporarily for pricing, then broadcast results back.

        rr_mask: pd.Series = out[package_col] == "RISK_REVERSAL"
        if rr_mask.any() and pricer is not None:
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

            # Step 3: Calculate metrics on the MERGED rows
            metrics = []
            for idx, row in tqdm(
                rr_merged_packages.iterrows(),
                total=len(rr_merged_packages),
                desc="PRICING RISK REVERSALS...",
            ):
                try:
                    res = usd_swaption_dealer_risk_reversal_skew_from_row(row, pricer)
                    metrics.append({
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
                    })
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
            assert len(out) == original_row_count, (
                f"Row count changed after RR pricing: {original_row_count} -> {len(out)}"
            )

        # Customer RR/strangles: 2-leg payer+receiver with benchmark strike widths
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

    # Phase 2: Detect straddles
    if detect_straddles:
        # dealers + custy package reported straddles
        out = detect_straddles_packages(
            out,
            timestamp_tolerance=datetime.timedelta(seconds=0),
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

        # custy straddle legs reported seperately
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

        # price straddles
        # columns are for tne entire straddle not seperate legs, metrics/rows will look duplicated before merged
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
        if straddle_mask.any() and pricer is not None:

            def _price_straddle(row: pd.Series) -> Optional[USDSwaptionStraddlePricerResult]:
                if "SOFR" not in str(row["trade_label"]).upper():
                    return None
                try:
                    return usd_swaption_straddle_pricer_from_row(row, pricer)

                # kind of stupid but works
                except SingleStraddleLegException:
                    row = row.copy()
                    row["premium"] = row["premium"] * 2
                    return usd_swaption_straddle_pricer_from_row(row, pricer)
                except Exception:
                    return None

            def _build_pricing_row(row: pd.Series) -> pd.Series:
                result = _price_straddle(row)
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

            # tqdm.pandas(desc="PRICING STRADDLES...")
            # pricing_results: pd.DataFrame = out.loc[straddle_mask].apply(_build_pricing_row, axis=1)
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

    # Phase 3: Detect vertical spreads (1x1, 1x2, etc.)
    if detect_vertical_spreads:
        out = detect_vertical_spreads_packages(
            out,
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

    # Phase 4: Detect conditional curve trades (same expiry, different tails)
    # Currently disabled in original code, keeping consistent
    # if detect_conditional_curve:
    #     out = detect_conditional_curve(
    #         out,
    #         time_window_seconds=conditional_curve_time_window_seconds,
    #         min_tail_diff_years=config.conditional_curve_min_tail_diff_years,
    #         product_col=product_col,
    #         package_col=package_col,
    #         exec_col=config.exec_col,
    #         platform_col=config.platform_col,
    #         currency_col=config.currency_col,
    #         underlier_col=config.underlier_col,
    #         trade_id_col=config.trade_id_col,
    #         expiration_col=config.expiration_col,
    #         tenor_col=config.tenor_col,
    #         forward_col=config.forward_col,
    #         notional_col=config.notional_col,
    #         package_indicator_col=config.package_indicator_col,
    #         require_same_platform=config.require_same_platform,
    #         require_same_currency=config.require_same_currency,
    #         require_same_underlier=config.require_same_underlier,
    #         platform_allowlist=config.platform_allowlist,
    #         platform_blocklist=config.platform_blocklist,
    #     )

    # Phase 5: Detect vega curve trades (requires straddles to be detected first)
    if detect_vega_curve and detect_straddles:
        out = detect_vega_curve_packages(
            out,
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


# =============================================================================
# Exports for backward compatibility
# =============================================================================

__all__ = [
    # Config class (deprecated but maintained for compatibility)
    "SwaptionPackageDetectionConfig",
    "DEFAULT_SWAPTION_PACKAGE_CONFIG",
    # Main detection functions
    "detect_and_link_swaption_packages_df",
    # Helper functions (for tests)
    "_vega_bucket",
    "_time_bucket",
    "_extract_effective_premium",
    "_compute_package_id",
    "_estimate_swaption_vega",
    # Detector class
    "SwaptionPackageDetector",
]
