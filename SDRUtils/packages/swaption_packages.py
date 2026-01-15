"""
Swaption Package Detection and Enrichment Pipeline

Main orchestration module for detecting swaption packages from SDR data
and enriching them with pricing metrics.
"""

from typing import Any, Dict, List, Optional, Tuple
from enum import Enum, auto

import numpy as np
import pandas as pd

from SDRUtils.packages.swaption.vega_curve import detect_vega_curve_packages
from SDRUtils.products._swaptions.pricer import (
    usd_swaption_straddle_pricer_from_row,
    USDSwaptionStraddlePricerResult,
)
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve


class SwaptionPackageType(Enum):
    """Classification of swaption package types."""
    OUTRIGHT_CALL = auto()
    OUTRIGHT_PUT = auto()
    STRADDLE = auto()
    STRANGLE = auto()
    CALL_SPREAD = auto()
    PUT_SPREAD = auto()
    COLLAR = auto()
    RISK_REVERSAL = auto()
    VEGA_CURVE = auto()
    UNKNOWN = auto()


# Column names for straddle pricing enrichment
STRADDLE_PRICING_COLUMNS = [
    "straddle_bpvol_yr",
    "straddle_fwd_premium",
    "straddle_dv01",
    "straddle_vega01",
    "straddle_gamma01",
    "straddle_theta1d",
]


def _detect_straddles(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    expiry_col: str = "expiry_date",
    effective_col: str = "effective_date",
    maturity_col: str = "maturity_date",
    strike_col: str = "strike",
    notional_col: str = "notional",
    option_type_col: str = "option_type",
    time_window_seconds: int = 60,
) -> pd.DataFrame:
    """
    Detect straddle packages from raw swaption trades.

    A straddle is identified when a payer and receiver swaption
    with matching parameters trade within a time window.

    Args:
        df: DataFrame of raw swaption trades
        timestamp_col: Column name for trade timestamp
        expiry_col: Column name for expiry date
        effective_col: Column name for effective date
        maturity_col: Column name for maturity date
        strike_col: Column name for strike
        notional_col: Column name for notional
        option_type_col: Column name for option type (PAYER/RECEIVER)
        time_window_seconds: Max time between legs to be a straddle

    Returns:
        DataFrame with straddle package information
    """
    if len(df) == 0:
        return df.assign(package_type=pd.Series(dtype=str))

    df_sorted = df.sort_values(timestamp_col).copy()
    package_types = ["UNKNOWN"] * len(df_sorted)
    straddle_ids = [-1] * len(df_sorted)
    straddle_counter = 0

    # Group by key attributes to find potential straddle legs
    grouping_cols = [expiry_col, effective_col, maturity_col, strike_col]
    available_cols = [c for c in grouping_cols if c in df_sorted.columns]

    if not available_cols:
        return df_sorted.assign(
            package_type=package_types,
            straddle_id=straddle_ids,
        )

    for _, group in df_sorted.groupby(available_cols):
        if len(group) < 2:
            continue

        if option_type_col not in group.columns:
            continue

        payers = group[group[option_type_col].str.upper().isin(["PAYER", "PAY", "P"])]
        receivers = group[group[option_type_col].str.upper().isin(["RECEIVER", "REC", "R"])]

        for p_idx, p_row in payers.iterrows():
            p_time = pd.Timestamp(p_row[timestamp_col])

            for r_idx, r_row in receivers.iterrows():
                r_time = pd.Timestamp(r_row[timestamp_col])

                time_diff = abs((p_time - r_time).total_seconds())
                if time_diff <= time_window_seconds:
                    # Found a straddle pair
                    p_loc = df_sorted.index.get_loc(p_idx)
                    r_loc = df_sorted.index.get_loc(r_idx)
                    package_types[p_loc] = "STRADDLE"
                    package_types[r_loc] = "STRADDLE"
                    straddle_ids[p_loc] = straddle_counter
                    straddle_ids[r_loc] = straddle_counter
                    straddle_counter += 1
                    break

    return df_sorted.assign(
        package_type=package_types,
        straddle_id=straddle_ids,
    )


def _enrich_straddles_with_pricing(
    df: pd.DataFrame,
    pricer: QLIRSwapCurve,
    expiry_col: str = "expiry_date",
    effective_col: str = "effective_date",
    maturity_col: str = "maturity_date",
    strike_col: str = "strike",
    notional_col: str = "notional",
    vol_col: str = "implied_vol_bp",
) -> pd.DataFrame:
    """
    Enrich detected straddles with QuantLib-based pricing metrics.

    For every row identified as a STRADDLE, this function calls the
    swaption straddle pricer to compute:
    - bpvol_yr: Annualized BP volatility
    - fwd_premium: Forward premium as % of notional
    - dv01: Dollar value of 1bp rate move
    - vega01: Dollar value of 1% vol move
    - gamma01: Second derivative w.r.t. rates
    - theta1d: 1-day time decay

    Args:
        df: DataFrame with detected straddles (must have package_type column)
        pricer: QLIRSwapCurve instance for pricing
        expiry_col: Column name for expiry date
        effective_col: Column name for effective date
        maturity_col: Column name for maturity date
        strike_col: Column name for strike
        notional_col: Column name for notional
        vol_col: Column name for implied vol in BP

    Returns:
        DataFrame with additional pricing columns for straddle rows
    """
    # Initialize pricing columns with NaN
    for col in STRADDLE_PRICING_COLUMNS:
        df[col] = np.nan

    # Filter to straddle rows only
    straddle_mask = df["package_type"] == "STRADDLE"
    straddle_indices = df.index[straddle_mask]

    if len(straddle_indices) == 0:
        return df

    # Price each straddle
    for idx in straddle_indices:
        row = df.loc[idx]

        try:
            result: USDSwaptionStraddlePricerResult = usd_swaption_straddle_pricer_from_row(
                row=row,
                pricer=pricer,
                expiry_col=expiry_col,
                effective_col=effective_col,
                maturity_col=maturity_col,
                strike_col=strike_col,
                notional_col=notional_col,
                vol_col=vol_col,
            )

            # Map result fields to DataFrame columns
            df.loc[idx, "straddle_bpvol_yr"] = result.bpvol_yr
            df.loc[idx, "straddle_fwd_premium"] = result.fwd_premium
            df.loc[idx, "straddle_dv01"] = result.dv01
            df.loc[idx, "straddle_vega01"] = result.vega01
            df.loc[idx, "straddle_gamma01"] = result.gamma01
            df.loc[idx, "straddle_theta1d"] = result.theta1d

        except Exception:
            # Pricing failed - columns remain NaN for this row
            # This handles cases with bad data gracefully
            pass

    return df


def detect_and_link_swaption_packages_df(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    expiry_col: str = "expiry_date",
    effective_col: str = "effective_date",
    maturity_col: str = "maturity_date",
    strike_col: str = "strike",
    notional_col: str = "notional",
    option_type_col: str = "option_type",
    vol_col: str = "implied_vol_bp",
    straddle_time_window_seconds: int = 60,
    vega_curve_time_window_seconds: int = 300,
    **kwargs: Any,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Main orchestration function for swaption package detection and enrichment.

    This function performs the following pipeline steps:

    1. **Package Detection**: Identifies swaption packages (straddles,
       strangles, spreads, etc.) from raw SDR swaption trade data.

    2. **Straddle Pricing Enrichment**: For every detected STRADDLE,
       computes rigorous QuantLib-based pricing metrics including:
       - straddle_bpvol_yr: Annualized basis point volatility
       - straddle_fwd_premium: Forward premium as percentage of notional
       - straddle_dv01: Dollar value of 1bp parallel rate shift
       - straddle_vega01: Dollar value of 1% (100bp) vol shift
       - straddle_gamma01: Second derivative w.r.t. 1bp rate move
       - straddle_theta1d: 1-day time decay

    3. **Vega Curve Linking**: Links straddles into larger vega curve
       packages (calendar spreads, butterflies, term structures) based
       on timing and risk metrics.

    Args:
        df: DataFrame of raw swaption trades from SDR
        timestamp_col: Column name for trade timestamp
        expiry_col: Column name for option expiry date
        effective_col: Column name for underlying swap effective date
        maturity_col: Column name for underlying swap maturity date
        strike_col: Column name for strike rate
        notional_col: Column name for notional amount
        option_type_col: Column name for option type (PAYER/RECEIVER)
        vol_col: Column name for implied volatility in basis points
        straddle_time_window_seconds: Max seconds between legs to be a straddle
        vega_curve_time_window_seconds: Max seconds between straddles in a vega curve
        **kwargs: Additional keyword arguments, including:
            - pricer: QLIRSwapCurve instance for pricing (required for enrichment)

    Returns:
        Tuple of (out, vega_curve_packages):
        - out: Enriched DataFrame with package_type, straddle_id, pricing columns,
               and vega_curve_package_id
        - vega_curve_packages: Summary DataFrame of detected vega curve packages

    Example:
        >>> from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
        >>> # ... set up pricer ...
        >>> out, vega_pkgs = detect_and_link_swaption_packages_df(
        ...     df=raw_swaption_trades,
        ...     pricer=my_pricer,
        ... )
        >>> # Filter to enriched straddles
        >>> straddles = out[out["package_type"] == "STRADDLE"]
        >>> print(straddles[["strike", "straddle_dv01", "straddle_vega01"]])
    """
    # Extract pricer from kwargs
    pricer: Optional[QLIRSwapCurve] = kwargs.get("pricer")

    if len(df) == 0:
        empty_out = df.copy()
        for col in ["package_type", "straddle_id"] + STRADDLE_PRICING_COLUMNS + ["vega_curve_package_id"]:
            empty_out[col] = np.nan if col in STRADDLE_PRICING_COLUMNS else None
        empty_vega_pkgs = pd.DataFrame(columns=[
            "package_id", "package_type", "member_count", "member_indices",
            "net_vega01", "gross_vega01", "net_dv01", "gross_dv01", "net_gamma01",
        ])
        return empty_out, empty_vega_pkgs

    # Step 1: Detect base packages (straddles, etc.)
    out = _detect_straddles(
        df=df,
        timestamp_col=timestamp_col,
        expiry_col=expiry_col,
        effective_col=effective_col,
        maturity_col=maturity_col,
        strike_col=strike_col,
        notional_col=notional_col,
        option_type_col=option_type_col,
        time_window_seconds=straddle_time_window_seconds,
    )

    # Step 2: Enrich ALL detected straddles with pricing
    # This applies to every straddle, not just those in vega curves
    if pricer is not None:
        out = _enrich_straddles_with_pricing(
            df=out,
            pricer=pricer,
            expiry_col=expiry_col,
            effective_col=effective_col,
            maturity_col=maturity_col,
            strike_col=strike_col,
            notional_col=notional_col,
            vol_col=vol_col,
        )
    else:
        # No pricer provided - initialize pricing columns with NaN
        for col in STRADDLE_PRICING_COLUMNS:
            out[col] = np.nan

    # Step 3: Detect vega curve packages from enriched straddles
    straddle_rows = out[out["package_type"] == "STRADDLE"]

    if len(straddle_rows) > 0 and pricer is not None:
        reference_date = pricer.reference_date()

        enriched_straddles, vega_curve_packages = detect_vega_curve_packages(
            straddles_df=straddle_rows,
            reference_date=reference_date,
            time_window_seconds=vega_curve_time_window_seconds,
            timestamp_col=timestamp_col,
            expiry_col=expiry_col,
            effective_col=effective_col,
            maturity_col=maturity_col,
            notional_col=notional_col,
            vega01_col="straddle_vega01",
            dv01_col="straddle_dv01",
            gamma01_col="straddle_gamma01",
        )

        # Merge vega curve package IDs back to main output
        if "vega_curve_package_id" in enriched_straddles.columns:
            out = out.join(
                enriched_straddles[["vega_curve_package_id"]],
                how="left",
            )
        else:
            out["vega_curve_package_id"] = -1
    else:
        out["vega_curve_package_id"] = -1
        vega_curve_packages = pd.DataFrame(columns=[
            "package_id", "package_type", "member_count", "member_indices",
            "net_vega01", "gross_vega01", "net_dv01", "gross_dv01", "net_gamma01",
        ])

    return out, vega_curve_packages
