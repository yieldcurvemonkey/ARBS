"""
USD Swaption Straddle Pricer

QuantLib-based pricing for swaption straddles with Greeks calculation.
"""

from dataclasses import dataclass
from typing import Optional, Any

import numpy as np
import pandas as pd
import QuantLib as ql

from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date


@dataclass(frozen=True)
class USDSwaptionStraddlePricerResult:
    """
    Result container for USD swaption straddle pricing.

    All values are expressed per unit notional unless otherwise specified.

    Attributes:
        bpvol_yr: Annualized basis point volatility (bp/year)
        fwd_premium: Forward premium of the straddle (as percentage of notional)
        dv01: Dollar value of 1bp parallel shift in rates
        vega01: Dollar value of 1% (100bp) shift in implied volatility
        gamma01: Second derivative of premium w.r.t. 1bp rate move
        theta1d: 1-day time decay (theta)
    """
    bpvol_yr: float
    fwd_premium: float
    dv01: float
    vega01: float
    gamma01: float
    theta1d: float


def _build_swaption_engine(
    curve_handle: ql.YieldTermStructureHandle,
    vol: float,
) -> ql.PricingEngine:
    """
    Build a Black swaption pricing engine with the given volatility.

    Args:
        curve_handle: Yield curve for discounting
        vol: Normal (basis point) volatility

    Returns:
        QuantLib swaption pricing engine
    """
    vol_handle = ql.QuoteHandle(ql.SimpleQuote(vol))
    vol_structure = ql.ConstantSwaptionVolatility(
        0,
        ql.TARGET(),
        ql.ModifiedFollowing,
        vol_handle,
        ql.Actual365Fixed(),
        ql.Normal,
    )
    vol_ts_handle = ql.SwaptionVolatilityStructureHandle(vol_structure)
    return ql.BachelierSwaptionEngine(curve_handle, vol_ts_handle)


def _build_underlying_swap(
    pricer: QLIRSwapCurve,
    effective_date: Any,
    maturity_date: Any,
    strike: float,
    notional: float,
    is_payer: bool,
) -> ql.VanillaSwap:
    """
    Build the underlying swap for a swaption.

    Args:
        pricer: The IR swap curve/pricer object
        effective_date: Swap effective date
        maturity_date: Swap maturity date
        strike: Fixed rate strike (as decimal, e.g., 0.04 for 4%)
        notional: Notional amount
        is_payer: True for payer swap, False for receiver

    Returns:
        QuantLib VanillaSwap object
    """
    swap_type = ql.VanillaSwap.Payer if is_payer else ql.VanillaSwap.Receiver

    return pricer.build_irswap(
        effective_date=effective_date,
        maturity_date=maturity_date,
        fixed_rate=strike * 100,  # Convert to percentage
        notional=notional if is_payer else -notional,
    )


def usd_swaption_straddle_pricer(
    pricer: QLIRSwapCurve,
    expiry_date: Any,
    effective_date: Any,
    maturity_date: Any,
    strike: float,
    notional: float,
    implied_vol_bp: float,
) -> USDSwaptionStraddlePricerResult:
    """
    Price a USD swaption straddle and compute Greeks.

    A straddle consists of a payer swaption and a receiver swaption
    with the same strike, expiry, and underlying swap parameters.

    Args:
        pricer: QLIRSwapCurve instance for curve/pricing
        expiry_date: Option expiry date
        effective_date: Underlying swap effective date
        maturity_date: Underlying swap maturity date
        strike: Strike rate (as decimal, e.g., 0.04 for 4%)
        notional: Notional amount
        implied_vol_bp: Implied normal volatility in basis points

    Returns:
        USDSwaptionStraddlePricerResult with all computed metrics
    """
    curve_handle = pricer.handle()
    ref_date = curve_handle.referenceDate()
    ql.Settings.instance().evaluationDate = ref_date

    # Convert dates
    ql_expiry = datetime_to_ql_date(expiry_date)
    ql_effective = datetime_to_ql_date(effective_date)
    ql_maturity = datetime_to_ql_date(maturity_date)

    # Volatility in decimal form (bp vol / 10000)
    vol_decimal = implied_vol_bp / 10000.0

    # Build exercise
    exercise = ql.EuropeanExercise(ql_expiry)

    # Build underlying swaps
    payer_swap = _build_underlying_swap(
        pricer, effective_date, maturity_date, strike, notional, is_payer=True
    )
    receiver_swap = _build_underlying_swap(
        pricer, effective_date, maturity_date, strike, notional, is_payer=False
    )

    # Build swaptions
    payer_swaption = ql.Swaption(payer_swap, exercise)
    receiver_swaption = ql.Swaption(receiver_swap, exercise)

    # Set up pricing engine
    engine = _build_swaption_engine(curve_handle, vol_decimal)
    payer_swaption.setPricingEngine(engine)
    receiver_swaption.setPricingEngine(engine)

    # Base NPV (straddle premium)
    payer_npv = payer_swaption.NPV()
    receiver_npv = receiver_swaption.NPV()
    straddle_npv = payer_npv + receiver_npv

    # Forward premium as percentage of notional
    fwd_premium = straddle_npv / notional * 100.0  # As percentage

    # DV01: bump curve by 1bp (0.0001) and reprice
    bump_size = 0.0001
    bumped_up_curve = ql.ZeroSpreadedTermStructure(
        curve_handle, ql.QuoteHandle(ql.SimpleQuote(bump_size))
    )
    bumped_up_handle = ql.YieldTermStructureHandle(bumped_up_curve)

    bumped_down_curve = ql.ZeroSpreadedTermStructure(
        curve_handle, ql.QuoteHandle(ql.SimpleQuote(-bump_size))
    )
    bumped_down_handle = ql.YieldTermStructureHandle(bumped_down_curve)

    # Reprice with bumped curves
    engine_up = _build_swaption_engine(bumped_up_handle, vol_decimal)
    engine_down = _build_swaption_engine(bumped_down_handle, vol_decimal)

    payer_swaption.setPricingEngine(engine_up)
    receiver_swaption.setPricingEngine(engine_up)
    npv_up = payer_swaption.NPV() + receiver_swaption.NPV()

    payer_swaption.setPricingEngine(engine_down)
    receiver_swaption.setPricingEngine(engine_down)
    npv_down = payer_swaption.NPV() + receiver_swaption.NPV()

    # DV01: central difference for 1bp move
    dv01 = (npv_down - npv_up) / 2.0

    # Gamma01: second derivative for 1bp
    gamma01 = (npv_up - 2.0 * straddle_npv + npv_down) / (bump_size ** 2) / 10000.0

    # Vega01: bump vol by 1bp (0.0001) and reprice
    vol_bump = 0.0001
    engine_vol_up = _build_swaption_engine(curve_handle, vol_decimal + vol_bump)
    engine_vol_down = _build_swaption_engine(curve_handle, vol_decimal - vol_bump)

    payer_swaption.setPricingEngine(engine_vol_up)
    receiver_swaption.setPricingEngine(engine_vol_up)
    npv_vol_up = payer_swaption.NPV() + receiver_swaption.NPV()

    payer_swaption.setPricingEngine(engine_vol_down)
    receiver_swaption.setPricingEngine(engine_vol_down)
    npv_vol_down = payer_swaption.NPV() + receiver_swaption.NPV()

    # Vega for 1bp vol change, scaled to 1% (100bp) for vega01
    vega_per_bp = (npv_vol_up - npv_vol_down) / 2.0
    vega01 = vega_per_bp * 100.0  # Scale to 1% (100bp)

    # Theta1d: shift evaluation date forward by 1 day
    engine_base = _build_swaption_engine(curve_handle, vol_decimal)
    payer_swaption.setPricingEngine(engine_base)
    receiver_swaption.setPricingEngine(engine_base)

    ql.Settings.instance().evaluationDate = ref_date + 1
    payer_npv_t1 = payer_swaption.NPV()
    receiver_npv_t1 = receiver_swaption.NPV()
    npv_t1 = payer_npv_t1 + receiver_npv_t1
    theta1d = npv_t1 - straddle_npv

    # Reset evaluation date
    ql.Settings.instance().evaluationDate = ref_date

    # Annualized BP vol
    bpvol_yr = implied_vol_bp

    return USDSwaptionStraddlePricerResult(
        bpvol_yr=bpvol_yr,
        fwd_premium=fwd_premium,
        dv01=dv01,
        vega01=vega01,
        gamma01=gamma01,
        theta1d=theta1d,
    )


def usd_swaption_straddle_pricer_from_row(
    row: pd.Series,
    pricer: QLIRSwapCurve,
    expiry_col: str = "expiry_date",
    effective_col: str = "effective_date",
    maturity_col: str = "maturity_date",
    strike_col: str = "strike",
    notional_col: str = "notional",
    vol_col: str = "implied_vol_bp",
) -> USDSwaptionStraddlePricerResult:
    """
    Price a USD swaption straddle from a DataFrame row.

    This convenience function extracts the necessary fields from a pandas Series
    (typically a row from a detected straddles DataFrame) and calls the main
    pricer function.

    Args:
        row: pandas Series containing swaption parameters
        pricer: QLIRSwapCurve instance for curve/pricing
        expiry_col: Column name for expiry date
        effective_col: Column name for effective date
        maturity_col: Column name for maturity date
        strike_col: Column name for strike rate
        notional_col: Column name for notional
        vol_col: Column name for implied vol in bp

    Returns:
        USDSwaptionStraddlePricerResult with all computed metrics

    Raises:
        KeyError: If required columns are missing from the row
        ValueError: If pricing fails due to invalid data
    """
    return usd_swaption_straddle_pricer(
        pricer=pricer,
        expiry_date=row[expiry_col],
        effective_date=row[effective_col],
        maturity_date=row[maturity_col],
        strike=row[strike_col],
        notional=row[notional_col],
        implied_vol_bp=row[vol_col],
    )
