"""
Outright/unexplained swaption detection and ATMF enrichment.

Identifies swaption trades that remain "unpackaged" after all other
detectors have run and enriches them with ATMF-relative strike offset
information for customer flow analysis.

Key use cases:
- Understanding customer directional flows (e.g., buying OTM payers vs ATM receivers)
- Flagging unexplained residual trades
- Providing moneyness context for single-leg trades

ATMF offset bucketing uses standard benchmark offsets:
    [..., -100, -75, -50, -25, 0, +25, +50, +75, +100, ...]

This is analogous to how customer_rr_strangle.py matches strike widths
to benchmark widths, but applied to absolute strike offsets from ATMF.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, List, Optional

import numpy as np
import pandas as pd

import QuantLib as ql

from SDRUtils.packages.swaption.utils import (
    safe_float,
    ensure_package_columns,
)

if TYPE_CHECKING:
    from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve


logger = logging.getLogger(__name__)


# Standard benchmark offsets from ATMF in basis points
# These are the same as BENCHMARK_OFFSETS in pricer/constants.py
BENCHMARK_STRIKE_OFFSETS_BPS: List[int] = [
    -300,
    -250,
    -200,
    -175,
    -150,
    -125,
    -100,
    -75,
    -50,
    -25,
    -20,
    -15,
    -10,
    0,
    10,
    15,
    20,
    25,
    50,
    75,
    100,
    125,
    150,
    175,
    200,
    250,
    300,
]

# Default tolerance for rounding to benchmark offsets (in bps)
DEFAULT_OFFSET_TOLERANCE_BPS: float = 7.5


def _round_to_benchmark_offset(
    actual_offset_bps: float,
    benchmarks: List[int],
    tolerance_bps: float,
) -> Optional[int]:
    """
    Round actual strike offset to nearest benchmark offset.

    Similar to _match_benchmark_width in customer_rr_strangle.py,
    but for absolute offsets from ATMF rather than strike widths.

    Args:
        actual_offset_bps: Actual strike offset from ATMF in basis points
                          (positive = above ATMF, negative = below)
        benchmarks: List of benchmark offsets to round to
        tolerance_bps: Maximum deviation from benchmark to accept

    Returns:
        Nearest benchmark offset if within tolerance, else None

    Examples:
        actual_offset_bps=48.5, benchmarks=[...,-25,0,25,50,...], tolerance_bps=7.5
        -> returns 50 (because |48.5 - 50| = 1.5 <= 7.5)

        actual_offset_bps=-103.2, benchmarks=[...,-100,-75,...], tolerance_bps=7.5
        -> returns -100 (because |-103.2 - (-100)| = 3.2 <= 7.5)

        actual_offset_bps=37.0, benchmarks=[...25,50,...], tolerance_bps=7.5
        -> returns None (|37-25|=12 > 7.5 and |37-50|=13 > 7.5)
    """
    if pd.isna(actual_offset_bps):
        return None

    best_match = None
    best_diff = float("inf")

    for bm in benchmarks:
        diff = abs(actual_offset_bps - bm)
        if diff <= tolerance_bps and diff < best_diff:
            best_diff = diff
            best_match = bm

    return best_match


def _compute_atmf_for_trade(
    row: pd.Series,
    pricer: "QLIRSwapCurve",
    expiration_col: str = "expiration_date",
    underlying_expiration_col: str = "underlying_expiration_date",
    notional_col: str = "notional",
) -> Optional[float]:
    """
    Compute the At-The-Money Forward rate for a swaption trade.

    Uses the same ATMF calculation as in _compute_swaption_leg_greeks
    from the pricer module.

    Args:
        row: Trade row as pandas Series
        pricer: QLIRSwapCurve instance for curve data
        expiration_col: Column name for option expiration date
        underlying_expiration_col: Column name for underlying swap maturity
        notional_col: Column name for notional amount

    Returns:
        ATMF rate as a decimal (e.g., 0.0425 for 4.25%), or None if calculation fails
    """
    try:
        # Lazy imports to avoid circular dependencies
        import Query.IRSwaps.adapter  # noqa: F401
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

        expiration_date = row.get(expiration_col)
        underlying_expiration_date = row.get(underlying_expiration_col)
        notional = safe_float(row.get(notional_col, 1_000_000))

        if pd.isna(expiration_date) or pd.isna(underlying_expiration_date):
            return None

        # Use absolute notional for ATMF calculation (sign doesn't affect rate)
        notional = abs(notional) if pd.notna(notional) and notional != 0 else 1_000_000

        atm_query = IRSwapQuery(
            curve="USD-SOFR-1D",
            effective_date=expiration_date,
            maturity_date=underlying_expiration_date,
            structure_kwargs={"notional": notional},
        )

        ql_atm_underlying_pkg, atm_rws = atm_query.resolve_package(pricer_or_curve=pricer)
        atm_vmap = atm_query.build_value_map(
            pricer_or_curve=pricer,
            package=ql_atm_underlying_pkg,
            risk_weights=atm_rws,
        )
        atmf = abs(atm_vmap.apply(value=IRSwapValue.RATE))

        return atmf

    except Exception as exc:
        logger.debug("Failed to compute ATMF for trade: %s", exc)
        return None


def detect_outright_swaptions(
    df: pd.DataFrame,
    *,
    # Pricer for ATMF calculation
    pricer: Optional["QLIRSwapCurve"] = None,
    curve_provider: Optional[Callable] = None,
    # Benchmark offset parameters
    benchmark_offsets_bps: Optional[List[int]] = None,
    offset_tolerance_bps: float = DEFAULT_OFFSET_TOLERANCE_BPS,
    # Column names
    product_col: str = "product_type",
    package_col: str = "package_type",
    trade_id_col: str = "trade_id",
    strike_col: str = "strike",
    expiration_col: str = "expiration_date",
    underlying_expiration_col: str = "underlying_expiration_date",
    notional_col: str = "notional",
    trade_label_col: str = "trade_label",
    # Platform filtering
    platforms_filter: Optional[List[str]] = None,
    platform_col: str = "platform_identifier",
) -> pd.DataFrame:
    """
    Detect and enrich outright/unexplained swaption trades with ATMF data.

    This function processes swaption trades that have not been assigned to
    a package by previous detectors. For each such trade, it:
    1. Calculates the ATMF rate using the provided pricer
    2. Computes the strike offset from ATMF in basis points
    3. Rounds the offset to the nearest benchmark offset
    4. Enriches the trade with moneyness classification

    Args:
        df: Classifications dataframe with swaption trades
        pricer: Optional QLIRSwapCurve instance for ATMF calculation
        curve_provider: Optional callable that returns a pricer for a given timestamp
                       (signature: curve_provider(timestamp) -> QLIRSwapCurve)
        benchmark_offsets_bps: List of benchmark offsets to round to
        offset_tolerance_bps: Tolerance for benchmark matching (default 7.5 bps)
        product_col: Column name for product type
        package_col: Column name for package type
        trade_id_col: Column name for trade ID
        strike_col: Column name for strike
        expiration_col: Column name for expiration date
        underlying_expiration_col: Column name for underlying swap maturity
        notional_col: Column name for notional
        trade_label_col: Column name for trade label
        platforms_filter: If set, only process trades from these platforms
        platform_col: Column name for platform identifier

    Returns:
        DataFrame with outright enrichment columns:
        - package_type: "OUTRIGHT" for detected unexplained trades
        - outright_atmf: ATMF rate for the trade (decimal)
        - outright_strike_offset_bps: Raw strike offset from ATMF in bps
        - outright_strike_offset_rounded_bps: Offset rounded to benchmark
        - outright_moneyness: "ATM", "OTM_PAYER", "OTM_RECEIVER", "ITM_PAYER", "ITM_RECEIVER"
    """
    if df.empty:
        return df

    if benchmark_offsets_bps is None:
        benchmark_offsets_bps = BENCHMARK_STRIKE_OFFSETS_BPS

    out = ensure_package_columns(df, package_col=package_col)

    # Initialize outright-specific columns
    outright_cols = [
        "outright_atmf",
        "outright_strike_offset_bps",
        "outright_strike_offset_rounded_bps",
        "outright_moneyness",
    ]
    for col in outright_cols:
        if col not in out.columns:
            out[col] = np.nan if col != "outright_moneyness" else None

    # Filter to candidate trades: swaptions without a package
    is_swaption = out[product_col].astype(str).str.contains("SWAPTION", case=False, na=False)
    not_packaged = out["package_id"].isna() | (out["package_id"] == "")

    # Apply platform filter if provided
    if platforms_filter is not None:
        is_platform = out[platform_col].isin(platforms_filter)
        candidate_mask = is_swaption & not_packaged & is_platform
    else:
        candidate_mask = is_swaption & not_packaged

    if not candidate_mask.any():
        return out

    # Check if we can compute ATMF
    can_compute_atmf = pricer is not None or curve_provider is not None

    # Process each candidate trade
    candidate_indices = out.index[candidate_mask].tolist()

    for idx in candidate_indices:
        row = out.loc[idx]

        # Mark as OUTRIGHT
        out.loc[idx, package_col] = "OUTRIGHT"

        # Skip ATMF calculation if no pricer available
        if not can_compute_atmf:
            continue

        # Get the appropriate pricer
        current_pricer = pricer
        if current_pricer is None and curve_provider is not None:
            exec_ts = row.get("execution_timestamp")
            if pd.notna(exec_ts):
                try:
                    current_pricer = curve_provider(exec_ts)
                except Exception as exc:
                    logger.debug("curve_provider failed for timestamp %s: %s", exec_ts, exc)
                    continue

        if current_pricer is None:
            continue

        # Compute ATMF
        atmf = _compute_atmf_for_trade(
            row,
            current_pricer,
            expiration_col=expiration_col,
            underlying_expiration_col=underlying_expiration_col,
            notional_col=notional_col,
        )
        if atmf is None:
            continue

        atmf = atmf / 100

        out.loc[idx, "outright_atmf"] = atmf

        # Get strike and compute offset
        strike = safe_float(row.get(strike_col))
        if pd.isna(strike):
            continue

        # Calculate offset in basis points: (Strike - ATMF) * 10000
        offset_bps = (strike - atmf) * 10_000
        out.loc[idx, "outright_strike_offset_bps"] = offset_bps

        # Round to benchmark offset
        rounded_offset = _round_to_benchmark_offset(
            offset_bps,
            benchmark_offsets_bps,
            offset_tolerance_bps,
        )

        if rounded_offset is not None:
            out.loc[idx, "outright_strike_offset_rounded_bps"] = rounded_offset
        else:
            # If no benchmark match, still store the raw offset as rounded
            # (rounded to nearest integer)
            out.loc[idx, "outright_strike_offset_rounded_bps"] = round(offset_bps)

        # Determine moneyness based on option type and offset
        trade_label = str(row.get(trade_label_col, "")).upper()
        product_type = str(row.get(product_col, "")).upper()

        is_payer = "PAYER" in product_type or "PAYER" in trade_label or "CALL" in product_type
        is_receiver = "RECEIVER" in product_type or "RECEIVER" in trade_label or "PUT" in product_type

        # ATM is within a small tolerance of 0
        atm_threshold_bps = 10.0
        if abs(offset_bps) <= atm_threshold_bps:
            moneyness = "ATM"
        elif is_payer:
            # Payer swaption: profits if rates rise
            # Strike > ATMF: OTM (needs rates to rise past strike)
            # Strike < ATMF: ITM (already profitable on rates)
            if offset_bps > 0:
                moneyness = "OTM_PAYER"
            else:
                moneyness = "ITM_PAYER"
        elif is_receiver:
            # Receiver swaption: profits if rates fall
            # Strike < ATMF: OTM (needs rates to fall past strike)
            # Strike > ATMF: ITM (already profitable on rates)
            if offset_bps < 0:
                moneyness = "OTM_RECEIVER"
            else:
                moneyness = "ITM_RECEIVER"
        else:
            # Unknown option type
            moneyness = "UNKNOWN"

        out.loc[idx, "outright_moneyness"] = moneyness

    return out
