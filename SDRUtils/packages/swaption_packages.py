"""
SDRUtils.packages.swaption_packages
===================================

Main orchestrator for swaption package detection and pricing.

This module provides the primary entry point for the swaption package detection
pipeline, integrating:
1. Straddle detection from SDR trade data
2. QuantLib-based precise pricing for detected straddles
3. Vega curve package detection for linked straddles across tenors
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve
from SDRUtils.packages.swaption.vega_curve import detect_vega_curve_packages
from SDRUtils.products._swaptions.pricer import (
    USDSwaptionStraddlePricerResult,
    usd_swaption_straddle_pricer_from_row,
)


logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Straddle Detection Logic
# -----------------------------------------------------------------------------


def _detect_straddles_packages(
    df: pd.DataFrame,
    timestamp_col: str = "Execution Timestamp",
    product_col: str = "Underlier ID-Leg 1",
    strike_col: str = "Strike Price",
    expiry_col: str = "Option Expiration Date",
    tenor_col: str = "Underlier ID-Leg 2",
    notional_col: str = "Notional amount-Leg 1",
    option_type_col: str = "Option Type",
    premium_col: str = "Option Premium Amount",
    time_window_seconds: int = 30,
) -> pd.DataFrame:
    """
    Detect swaption straddle packages from raw SDR trade data.

    A straddle is identified when:
    1. A payer and receiver swaption with the same strike
    2. Same underlying swap (tenor, expiry)
    3. Traded within a short time window
    4. Similar notional amounts

    Parameters
    ----------
    df : pd.DataFrame
        Raw SDR swaption trade data.
    timestamp_col : str
        Column containing execution timestamps.
    product_col : str
        Column identifying the product type.
    strike_col : str
        Column containing strike prices.
    expiry_col : str
        Column containing option expiration dates.
    tenor_col : str
        Column containing underlying swap tenor information.
    notional_col : str
        Column containing notional amounts.
    option_type_col : str
        Column identifying option type (CALL/PUT, PAYER/RECEIVER).
    premium_col : str
        Column containing option premium amounts.
    time_window_seconds : int
        Maximum time between trades to be considered a straddle.

    Returns
    -------
    pd.DataFrame
        DataFrame with additional columns:
        - `package_type`: 'STRADDLE' for detected straddles, NaN otherwise
        - `straddle_package_id`: Unique ID linking straddle legs
        - `straddle_leg_type`: 'PAYER' or 'RECEIVER'
    """
    if df.empty:
        return df.assign(
            package_type=pd.Series(dtype="object"),
            straddle_package_id=pd.Series(dtype="object"),
            straddle_leg_type=pd.Series(dtype="object"),
        )

    df = df.copy()
    df["package_type"] = np.nan
    df["straddle_package_id"] = np.nan
    df["straddle_leg_type"] = np.nan

    # Normalize option type to PAYER/RECEIVER or CALL/PUT
    if option_type_col in df.columns:
        df["_normalized_option_type"] = df[option_type_col].astype(str).str.upper().str.strip()
        df["_is_payer"] = df["_normalized_option_type"].isin(["PAYER", "CALL", "C", "P"])
        df["_is_receiver"] = df["_normalized_option_type"].isin(["RECEIVER", "PUT", "R"])
    else:
        # If no option type column, we cannot detect straddles
        return df

    # Parse timestamps
    if timestamp_col in df.columns:
        df["_parsed_ts"] = pd.to_datetime(df[timestamp_col], errors="coerce", utc=True)
    else:
        return df

    # Parse expiry dates
    if expiry_col in df.columns:
        df["_parsed_expiry"] = pd.to_datetime(df[expiry_col], errors="coerce")
    else:
        df["_parsed_expiry"] = pd.NaT

    # Group by characteristics that should match for a straddle
    # We'll use a simple pairwise matching approach
    straddle_counter = 0
    assigned = set()

    indices = df.index.tolist()

    for i, idx in enumerate(indices):
        if idx in assigned:
            continue

        row = df.loc[idx]

        # Must be a payer or receiver
        if not (row.get("_is_payer", False) or row.get("_is_receiver", False)):
            continue

        # Get characteristics
        ts = row.get("_parsed_ts")
        strike = row.get(strike_col) if strike_col in df.columns else None
        expiry = row.get("_parsed_expiry")
        tenor = row.get(tenor_col) if tenor_col in df.columns else None
        notional = row.get(notional_col) if notional_col in df.columns else None
        is_payer = row.get("_is_payer", False)

        # Look for matching opposite leg
        for other_idx in indices[i + 1:]:
            if other_idx in assigned:
                continue

            other_row = df.loc[other_idx]

            # Must be opposite type
            other_is_payer = other_row.get("_is_payer", False)
            other_is_receiver = other_row.get("_is_receiver", False)

            if is_payer and not other_is_receiver:
                continue
            if not is_payer and not other_is_payer:
                continue

            # Check strike match
            other_strike = other_row.get(strike_col) if strike_col in df.columns else None
            if strike is not None and other_strike is not None:
                if not np.isclose(float(strike), float(other_strike), rtol=0.001):
                    continue

            # Check expiry match
            other_expiry = other_row.get("_parsed_expiry")
            if pd.notna(expiry) and pd.notna(other_expiry):
                if expiry != other_expiry:
                    continue

            # Check tenor match
            other_tenor = other_row.get(tenor_col) if tenor_col in df.columns else None
            if tenor is not None and other_tenor is not None:
                if str(tenor).strip().upper() != str(other_tenor).strip().upper():
                    continue

            # Check time window
            other_ts = other_row.get("_parsed_ts")
            if pd.notna(ts) and pd.notna(other_ts):
                time_diff = abs((ts - other_ts).total_seconds())
                if time_diff > time_window_seconds:
                    continue

            # Check notional similarity (within 10%)
            other_notional = other_row.get(notional_col) if notional_col in df.columns else None
            if notional is not None and other_notional is not None:
                try:
                    if not np.isclose(abs(float(notional)), abs(float(other_notional)), rtol=0.10):
                        continue
                except (ValueError, TypeError):
                    pass

            # Found a match - mark as straddle
            straddle_counter += 1
            straddle_id = f"STRADDLE_{straddle_counter:06d}"

            df.loc[idx, "package_type"] = "STRADDLE"
            df.loc[idx, "straddle_package_id"] = straddle_id
            df.loc[idx, "straddle_leg_type"] = "PAYER" if is_payer else "RECEIVER"

            df.loc[other_idx, "package_type"] = "STRADDLE"
            df.loc[other_idx, "straddle_package_id"] = straddle_id
            df.loc[other_idx, "straddle_leg_type"] = "PAYER" if other_is_payer else "RECEIVER"

            assigned.add(idx)
            assigned.add(other_idx)
            break

    # Clean up temporary columns
    df = df.drop(columns=["_normalized_option_type", "_is_payer", "_is_receiver", "_parsed_ts", "_parsed_expiry"], errors="ignore")

    return df


def _consolidate_straddle_rows(
    df: pd.DataFrame,
    straddle_id_col: str = "straddle_package_id",
    notional_col: str = "Notional amount-Leg 1",
    premium_col: str = "Option Premium Amount",
    strike_col: str = "Strike Price",
    expiry_col: str = "Option Expiration Date",
    tenor_col: str = "Underlier ID-Leg 2",
) -> pd.DataFrame:
    """
    Consolidate paired straddle rows into single straddle entries.

    For each straddle package, creates a single row with combined information
    suitable for pricing.

    Returns a DataFrame where each row represents one straddle package.
    """
    if df.empty or straddle_id_col not in df.columns:
        return df

    straddle_mask = df["package_type"] == "STRADDLE"
    non_straddles = df[~straddle_mask].copy()
    straddles = df[straddle_mask].copy()

    if straddles.empty:
        return df

    # Group by straddle ID and consolidate
    consolidated = []

    for straddle_id, group in straddles.groupby(straddle_id_col):
        if len(group) < 2:
            # Single leg - keep as is
            consolidated.append(group.iloc[0].to_dict())
            continue

        # Take the first row as base and update with combined info
        base_row = group.iloc[0].to_dict()

        # Sum premiums for the straddle
        if premium_col in group.columns:
            total_premium = group[premium_col].apply(lambda x: float(x) if pd.notna(x) else 0).sum()
            base_row["option_premium"] = total_premium
        else:
            base_row["option_premium"] = np.nan

        # Keep max notional
        if notional_col in group.columns:
            max_notional = group[notional_col].apply(lambda x: abs(float(x)) if pd.notna(x) else 0).max()
            base_row["notional_amount"] = max_notional
        else:
            base_row["notional_amount"] = np.nan

        # Parse and store expiry date
        if expiry_col in group.columns:
            expiry = group[expiry_col].iloc[0]
            if pd.notna(expiry):
                try:
                    base_row["option_expiry_date"] = pd.to_datetime(expiry).date()
                except Exception:
                    base_row["option_expiry_date"] = None
            else:
                base_row["option_expiry_date"] = None
        else:
            base_row["option_expiry_date"] = None

        # Store tenor
        if tenor_col in group.columns:
            base_row["underlying_tenor"] = group[tenor_col].iloc[0]
        else:
            base_row["underlying_tenor"] = None

        # Store strike
        if strike_col in group.columns:
            base_row["strike_price"] = group[strike_col].iloc[0]
        else:
            base_row["strike_price"] = None

        consolidated.append(base_row)

    consolidated_df = pd.DataFrame(consolidated)

    # Combine with non-straddles
    result = pd.concat([non_straddles, consolidated_df], ignore_index=True)

    return result


# -----------------------------------------------------------------------------
# Pricing Integration
# -----------------------------------------------------------------------------


def _apply_straddle_pricing(
    df: pd.DataFrame,
    pricer: _IRSwapGenericCurve,
    package_type_col: str = "package_type",
    expiry_col: str = "option_expiry_date",
    tenor_col: str = "underlying_tenor",
    strike_col: str = "strike_price",
    notional_col: str = "notional_amount",
    premium_col: str = "option_premium",
) -> pd.DataFrame:
    """
    Apply QuantLib-based pricing to detected straddle rows.

    For every row where `package_type == 'STRADDLE'`, calls the
    `usd_swaption_straddle_pricer_from_row` function to compute
    precise Greeks and volatility metrics.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with detected straddles.
    pricer : _IRSwapGenericCurve
        The curve/pricer object for pricing calculations.
    package_type_col : str
        Column indicating package type.
    expiry_col : str
        Column name for option expiry date.
    tenor_col : str
        Column name for underlying swap tenor.
    strike_col : str
        Column name for strike price.
    notional_col : str
        Column name for notional amount.
    premium_col : str
        Column name for option premium.

    Returns
    -------
    pd.DataFrame
        DataFrame with additional pricing columns:
        - straddle_bpvol_yr
        - straddle_fwd_premium
        - straddle_dv01
        - straddle_vega01
        - straddle_gamma01
        - straddle_theta1d
    """
    # Initialize output columns with NaN
    pricing_cols = [
        "straddle_bpvol_yr",
        "straddle_fwd_premium",
        "straddle_dv01",
        "straddle_vega01",
        "straddle_gamma01",
        "straddle_theta1d",
    ]

    for col in pricing_cols:
        df[col] = np.nan

    if df.empty:
        return df

    # Find straddle rows
    if package_type_col not in df.columns:
        return df

    straddle_mask = df[package_type_col].astype(str).str.upper() == "STRADDLE"
    straddle_indices = df[straddle_mask].index.tolist()

    if not straddle_indices:
        return df

    # Price each straddle
    for idx in straddle_indices:
        row = df.loc[idx]

        try:
            # Call the pricer function
            result: USDSwaptionStraddlePricerResult = usd_swaption_straddle_pricer_from_row(
                row=row,
                pricer=pricer,
                expiry_col=expiry_col,
                tenor_col=tenor_col,
                strike_col=strike_col,
                notional_col=notional_col,
                premium_col=premium_col,
            )

            # Populate the pricing columns
            if result.pricing_error is None:
                df.loc[idx, "straddle_bpvol_yr"] = result.bpvol_yr
                df.loc[idx, "straddle_fwd_premium"] = result.fwd_premium
                df.loc[idx, "straddle_dv01"] = result.dv01
                df.loc[idx, "straddle_vega01"] = result.vega01
                df.loc[idx, "straddle_gamma01"] = result.gamma01
                df.loc[idx, "straddle_theta1d"] = result.theta1d
            else:
                logger.debug(f"Pricing error for straddle at index {idx}: {result.pricing_error}")

        except Exception as e:
            logger.warning(f"Exception pricing straddle at index {idx}: {e}")
            # Leave columns as NaN on error
            continue

    return df


# -----------------------------------------------------------------------------
# Main Orchestrator
# -----------------------------------------------------------------------------


def detect_and_link_swaption_packages_df(
    df: pd.DataFrame,
    pricer: Optional[_IRSwapGenericCurve] = None,
    timestamp_col: str = "Execution Timestamp",
    product_col: str = "Underlier ID-Leg 1",
    strike_col: str = "Strike Price",
    expiry_col: str = "Option Expiration Date",
    tenor_col: str = "Underlier ID-Leg 2",
    notional_col: str = "Notional amount-Leg 1",
    option_type_col: str = "Option Type",
    premium_col: str = "Option Premium Amount",
    time_window_seconds: int = 30,
    consolidate_straddles: bool = True,
    detect_vega_curves: bool = True,
    vega_curve_time_window_minutes: int = 5,
    **kwargs: Any,
) -> pd.DataFrame:
    """
    Main orchestrator for swaption package detection and pricing.

    This function performs the complete pipeline:
    1. Detects straddle packages from raw SDR trade data
    2. Optionally consolidates paired straddle legs into single rows
    3. Computes precise QuantLib-based pricing metrics for each straddle
    4. Optionally detects vega curve packages (linked straddles across tenors)

    Parameters
    ----------
    df : pd.DataFrame
        Raw SDR swaption trade data.
    pricer : _IRSwapGenericCurve, optional
        The curve/pricer object for pricing calculations. If not provided,
        pricing columns will be populated with NaN. Can also be passed via
        kwargs as 'pricer' or 'curve'.
    timestamp_col : str
        Column containing execution timestamps.
    product_col : str
        Column identifying the product type.
    strike_col : str
        Column containing strike prices.
    expiry_col : str
        Column containing option expiration dates.
    tenor_col : str
        Column containing underlying swap tenor information.
    notional_col : str
        Column containing notional amounts.
    option_type_col : str
        Column identifying option type (CALL/PUT, PAYER/RECEIVER).
    premium_col : str
        Column containing option premium amounts.
    time_window_seconds : int
        Maximum time between trades to be considered a straddle.
    consolidate_straddles : bool
        If True, consolidate paired straddle legs into single rows.
    detect_vega_curves : bool
        If True, run vega curve package detection after straddle detection.
    vega_curve_time_window_minutes : int
        Time window for vega curve package detection.
    **kwargs : Any
        Additional arguments. Supports passing 'pricer' or 'curve' here.

    Returns
    -------
    pd.DataFrame
        Enhanced DataFrame with the following additional columns:

        **Straddle Detection Columns:**
        - `package_type`: 'STRADDLE' for detected straddles
        - `straddle_package_id`: Unique ID linking straddle legs
        - `straddle_leg_type`: 'PAYER' or 'RECEIVER'

        **Straddle Pricing Columns** (derived from USDSwaptionStraddlePricerResult):
        - `straddle_bpvol_yr`: Implied normal volatility in bps/year
        - `straddle_fwd_premium`: Forward premium of the straddle
        - `straddle_dv01`: Dollar value of 1bp rate move
        - `straddle_vega01`: Dollar value of 1bp vol move
        - `straddle_gamma01`: Second derivative w.r.t. rate
        - `straddle_theta1d`: One-day time decay

        **Vega Curve Package Columns** (if detect_vega_curves=True):
        - `vega_curve_package_id`: ID for linked vega curve packages
        - `vega_curve_leg_num`: Leg number within the package
        - `estimated_vega`: Vega value (estimated or from pricer)

    Examples
    --------
    >>> from SDRUtils import detect_and_link_swaption_packages_df
    >>> from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
    >>>
    >>> # Load SDR data
    >>> sdr_df = load_sdr_swaption_data()
    >>>
    >>> # Build a pricer/curve object
    >>> pricer = build_sofr_curve(reference_date)
    >>>
    >>> # Run the detection and pricing pipeline
    >>> enriched_df = detect_and_link_swaption_packages_df(
    ...     df=sdr_df,
    ...     pricer=pricer,
    ...     detect_vega_curves=True,
    ... )
    >>>
    >>> # Access pricing metrics for straddles
    >>> straddles = enriched_df[enriched_df['package_type'] == 'STRADDLE']
    >>> print(straddles[['straddle_bpvol_yr', 'straddle_vega01', 'straddle_dv01']])
    """
    if df.empty:
        return df

    # Handle pricer from kwargs
    if pricer is None:
        pricer = kwargs.get("pricer") or kwargs.get("curve")

    # Step 1: Detect straddle packages
    logger.info("Step 1: Detecting straddle packages...")
    df = _detect_straddles_packages(
        df=df,
        timestamp_col=timestamp_col,
        product_col=product_col,
        strike_col=strike_col,
        expiry_col=expiry_col,
        tenor_col=tenor_col,
        notional_col=notional_col,
        option_type_col=option_type_col,
        premium_col=premium_col,
        time_window_seconds=time_window_seconds,
    )

    straddle_count = (df["package_type"] == "STRADDLE").sum() if "package_type" in df.columns else 0
    logger.info(f"Detected {straddle_count // 2} straddle packages ({straddle_count} legs)")

    # Step 2: Optionally consolidate straddle rows
    if consolidate_straddles and straddle_count > 0:
        logger.info("Step 2: Consolidating straddle legs...")
        df = _consolidate_straddle_rows(
            df=df,
            notional_col=notional_col,
            premium_col=premium_col,
            strike_col=strike_col,
            expiry_col=expiry_col,
            tenor_col=tenor_col,
        )

    # Step 3: Apply pricing to straddles
    if pricer is not None and straddle_count > 0:
        logger.info("Step 3: Applying QuantLib pricing to straddles...")
        df = _apply_straddle_pricing(
            df=df,
            pricer=pricer,
            package_type_col="package_type",
            expiry_col="option_expiry_date",
            tenor_col="underlying_tenor",
            strike_col="strike_price",
            notional_col="notional_amount",
            premium_col="option_premium",
        )

        priced_count = df["straddle_bpvol_yr"].notna().sum()
        logger.info(f"Successfully priced {priced_count} straddles")
    else:
        if pricer is None:
            logger.warning("No pricer provided - straddle pricing columns will be NaN")
        # Initialize pricing columns with NaN
        pricing_cols = [
            "straddle_bpvol_yr",
            "straddle_fwd_premium",
            "straddle_dv01",
            "straddle_vega01",
            "straddle_gamma01",
            "straddle_theta1d",
        ]
        for col in pricing_cols:
            if col not in df.columns:
                df[col] = np.nan

    # Step 4: Optionally detect vega curve packages
    if detect_vega_curves and straddle_count > 0:
        logger.info("Step 4: Detecting vega curve packages...")

        # Use pre-calculated vega if available from the pricer
        use_precalc = pricer is not None and "straddle_vega01" in df.columns

        df = detect_vega_curve_packages(
            df=df,
            package_type_col="package_type",
            expiry_col="option_expiry_date",
            tenor_col="underlying_tenor",
            notional_col="notional_amount",
            timestamp_col=timestamp_col,
            time_window_minutes=vega_curve_time_window_minutes,
            use_precalculated_vega=use_precalc,
            vega_col="straddle_vega01",
        )

        vega_curve_count = df["vega_curve_package_id"].notna().sum() if "vega_curve_package_id" in df.columns else 0
        logger.info(f"Detected {vega_curve_count} legs in vega curve packages")

    logger.info("Swaption package detection pipeline complete")
    return df


# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------


def get_straddle_summary(
    df: pd.DataFrame,
    package_type_col: str = "package_type",
) -> pd.DataFrame:
    """
    Generate a summary of detected and priced straddles.

    Returns a DataFrame with aggregated statistics for straddles.
    """
    if df.empty or package_type_col not in df.columns:
        return pd.DataFrame()

    straddles = df[df[package_type_col] == "STRADDLE"]

    if straddles.empty:
        return pd.DataFrame()

    summary = {
        "total_straddles": len(straddles),
        "priced_straddles": straddles["straddle_bpvol_yr"].notna().sum() if "straddle_bpvol_yr" in straddles.columns else 0,
        "avg_bpvol": straddles["straddle_bpvol_yr"].mean() if "straddle_bpvol_yr" in straddles.columns else np.nan,
        "avg_vega01": straddles["straddle_vega01"].mean() if "straddle_vega01" in straddles.columns else np.nan,
        "total_vega01": straddles["straddle_vega01"].sum() if "straddle_vega01" in straddles.columns else np.nan,
        "avg_dv01": straddles["straddle_dv01"].mean() if "straddle_dv01" in straddles.columns else np.nan,
        "total_notional": straddles["notional_amount"].sum() if "notional_amount" in straddles.columns else np.nan,
    }

    return pd.DataFrame([summary])
