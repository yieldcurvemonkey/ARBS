"""
SDRUtils.products._swaptions.pricer
===================================

QuantLib-based USD swaption straddle pricing utilities.

This module provides:
- USDSwaptionStraddlePricerResult: A dataclass containing all pricing metrics for a straddle.
- usd_swaption_straddle_pricer_from_row: Function to price a straddle from a DataFrame row.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

try:
    import QuantLib as ql
except ImportError:
    ql = None  # type: ignore[assignment]

from Query.IRSwaps._IRSwapGenericCurve import _IRSwapGenericCurve


@dataclass
class USDSwaptionStraddlePricerResult:
    """
    Result container for USD swaption straddle pricing.

    Attributes:
        bpvol_yr: Implied normal volatility in basis points per year.
        fwd_premium: Forward premium of the straddle (sum of call + put premiums).
        dv01: Dollar value of a 1bp move in the underlying swap rate.
        vega01: Dollar value of a 1bp move in implied volatility.
        gamma01: Dollar value of the second derivative w.r.t. 1bp rate move.
        theta1d: One-day time decay in dollars.
        underlying_fwd_rate: The forward swap rate at option expiry.
        expiry_date: Option expiration date.
        underlying_tenor: Tenor of the underlying swap (e.g., "5Y").
        strike: Strike rate of the swaption.
        notional: Notional amount.
        pricing_error: Optional error message if pricing failed partially.
    """

    bpvol_yr: Optional[float] = None
    fwd_premium: Optional[float] = None
    dv01: Optional[float] = None
    vega01: Optional[float] = None
    gamma01: Optional[float] = None
    theta1d: Optional[float] = None
    underlying_fwd_rate: Optional[float] = None
    expiry_date: Optional[datetime.date] = None
    underlying_tenor: Optional[str] = None
    strike: Optional[float] = None
    notional: Optional[float] = None
    pricing_error: Optional[str] = None


def _parse_tenor_to_ql_period(tenor_str: str) -> "ql.Period":
    """Convert a tenor string like '5Y', '6M', '10Y' to a QuantLib Period."""
    if ql is None:
        raise ImportError("QuantLib is required for swaption pricing")
    tenor_str = str(tenor_str).strip().upper()
    return ql.Period(tenor_str)


def _parse_date(date_val: Any) -> Optional[datetime.date]:
    """Parse a date value from various formats."""
    if date_val is None or (isinstance(date_val, float) and np.isnan(date_val)):
        return None
    if isinstance(date_val, datetime.datetime):
        return date_val.date()
    if isinstance(date_val, datetime.date):
        return date_val
    if isinstance(date_val, pd.Timestamp):
        return date_val.date()
    if isinstance(date_val, str):
        try:
            return pd.to_datetime(date_val).date()
        except Exception:
            return None
    return None


def _datetime_to_ql_date(dt: datetime.date) -> "ql.Date":
    """Convert Python date to QuantLib Date."""
    if ql is None:
        raise ImportError("QuantLib is required for swaption pricing")
    return ql.Date(dt.day, dt.month, dt.year)


def _ql_date_to_pydate(ql_date: "ql.Date") -> datetime.date:
    """Convert QuantLib Date to Python date."""
    return datetime.date(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())


def _build_swaption(
    curve_handle: "ql.YieldTermStructureHandle",
    expiry_date: datetime.date,
    underlying_tenor: str,
    strike: float,
    notional: float,
    option_type: "ql.Option.Type",
    vol_handle: "ql.QuoteHandle",
    settlement_type: "ql.Settlement.Type" = None,
) -> "ql.Swaption":
    """Build a QuantLib swaption instrument."""
    if ql is None:
        raise ImportError("QuantLib is required for swaption pricing")

    if settlement_type is None:
        settlement_type = ql.Settlement.Physical

    calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    day_count = ql.Actual360()

    # Build the underlying swap
    swap_tenor = _parse_tenor_to_ql_period(underlying_tenor)

    # Create SOFR index for USD swaps
    sofr_index = ql.OvernightIndex(
        "SOFR",
        0,
        ql.USDCurrency(),
        calendar,
        day_count,
        curve_handle,
    )

    # Determine swap start date (T+2 from expiry)
    swap_start_date = calendar.advance(_datetime_to_ql_date(expiry_date), ql.Period(2, ql.Days))
    swap_end_date = calendar.advance(swap_start_date, swap_tenor)

    # Build OIS swap
    swap = ql.MakeOIS(
        swapTenor=ql.Period(0, ql.Days),
        overnightIndex=sofr_index,
        fixedRate=strike / 100.0,
        fwdStart=ql.Period(0, ql.Days),
        effectiveDate=swap_start_date,
        terminationDate=swap_end_date,
        nominal=abs(notional),
        paymentFrequency=ql.Annual,
        receiveFixed=(option_type == ql.Option.Put),
    )

    # Build the swaption
    exercise = ql.EuropeanExercise(_datetime_to_ql_date(expiry_date))
    swaption = ql.Swaption(swap, exercise, settlement_type)

    # Set up the pricing engine with normal (Bachelier) volatility
    vol_ts = ql.ConstantSwaptionVolatility(
        0,
        calendar,
        ql.ModifiedFollowing,
        vol_handle,
        day_count,
        ql.Normal,
    )
    swaption.setPricingEngine(
        ql.BachelierSwaptionEngine(curve_handle, ql.SwaptionVolatilityStructureHandle(vol_ts))
    )

    return swaption


def _implied_normal_vol_from_premium(
    curve_handle: "ql.YieldTermStructureHandle",
    expiry_date: datetime.date,
    underlying_tenor: str,
    strike: float,
    notional: float,
    market_premium: float,
    option_type: "ql.Option.Type",
    initial_guess: float = 0.005,
    max_iterations: int = 100,
    tolerance: float = 1e-8,
) -> Optional[float]:
    """
    Solve for implied normal volatility given a market premium.

    Uses Newton-Raphson iteration to find the volatility that matches
    the market premium.
    """
    if ql is None:
        raise ImportError("QuantLib is required for swaption pricing")

    vol_guess = initial_guess

    for _ in range(max_iterations):
        try:
            vol_handle = ql.QuoteHandle(ql.SimpleQuote(vol_guess))
            swaption = _build_swaption(
                curve_handle=curve_handle,
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
                option_type=option_type,
                vol_handle=vol_handle,
            )

            model_premium = swaption.NPV()
            price_diff = model_premium - market_premium

            if abs(price_diff) < tolerance:
                return vol_guess

            # Compute vega for Newton step
            vol_up = vol_guess + 0.0001
            vol_handle_up = ql.QuoteHandle(ql.SimpleQuote(vol_up))
            swaption_up = _build_swaption(
                curve_handle=curve_handle,
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
                option_type=option_type,
                vol_handle=vol_handle_up,
            )
            vega = (swaption_up.NPV() - model_premium) / 0.0001

            if abs(vega) < 1e-12:
                break

            vol_guess = vol_guess - price_diff / vega
            vol_guess = max(0.0001, min(vol_guess, 0.10))  # Bound between 1bp and 1000bp

        except Exception:
            break

    return None


def usd_swaption_straddle_pricer_from_row(
    row: Union[pd.Series, dict],
    pricer: _IRSwapGenericCurve,
    expiry_col: str = "option_expiry_date",
    tenor_col: str = "underlying_tenor",
    strike_col: str = "strike_price",
    notional_col: str = "notional_amount",
    premium_col: str = "option_premium",
    vol_shift_bp: float = 1.0,
    rate_shift_bp: float = 1.0,
) -> USDSwaptionStraddlePricerResult:
    """
    Price a USD swaption straddle from a DataFrame row using QuantLib.

    This function computes precise pricing metrics including:
    - Implied normal volatility (BPVol)
    - Forward premium
    - DV01, Vega01, Gamma01, Theta

    Parameters
    ----------
    row : pd.Series or dict
        A row from a straddle-detected DataFrame containing option details.
    pricer : _IRSwapGenericCurve
        The curve/pricer object (typically QLIRSwapCurve) with a valid
        YieldTermStructureHandle for discounting and forward rate projection.
    expiry_col : str
        Column name for the option expiry date.
    tenor_col : str
        Column name for the underlying swap tenor.
    strike_col : str
        Column name for the strike price (in percent, e.g., 4.25 for 4.25%).
    notional_col : str
        Column name for the notional amount.
    premium_col : str
        Column name for the straddle premium.
    vol_shift_bp : float
        Volatility bump size in basis points for vega calculation.
    rate_shift_bp : float
        Rate bump size in basis points for delta/gamma calculation.

    Returns
    -------
    USDSwaptionStraddlePricerResult
        Dataclass containing all computed pricing metrics.
    """
    if ql is None:
        return USDSwaptionStraddlePricerResult(pricing_error="QuantLib not available")

    result = USDSwaptionStraddlePricerResult()

    try:
        # Extract row data
        expiry_date = _parse_date(row.get(expiry_col) if isinstance(row, dict) else row.get(expiry_col))
        underlying_tenor = row.get(tenor_col) if isinstance(row, dict) else row.get(tenor_col)
        strike = row.get(strike_col) if isinstance(row, dict) else row.get(strike_col)
        notional = row.get(notional_col) if isinstance(row, dict) else row.get(notional_col)
        market_premium = row.get(premium_col) if isinstance(row, dict) else row.get(premium_col)

        # Validate required fields
        if expiry_date is None:
            return USDSwaptionStraddlePricerResult(pricing_error="Missing expiry date")
        if underlying_tenor is None or pd.isna(underlying_tenor):
            return USDSwaptionStraddlePricerResult(pricing_error="Missing underlying tenor")
        if strike is None or pd.isna(strike):
            return USDSwaptionStraddlePricerResult(pricing_error="Missing strike price")
        if notional is None or pd.isna(notional):
            notional = 1_000_000.0  # Default notional

        # Convert types
        strike = float(strike)
        notional = float(notional)
        underlying_tenor = str(underlying_tenor)

        result.expiry_date = expiry_date
        result.underlying_tenor = underlying_tenor
        result.strike = strike
        result.notional = notional

        # Get the curve handle from the pricer
        curve_handle = pricer.handle()
        ref_date = pricer.reference_date()

        # Set evaluation date
        ql.Settings.instance().evaluationDate = _datetime_to_ql_date(ref_date)

        # Validate expiry is in the future
        if expiry_date <= ref_date:
            return USDSwaptionStraddlePricerResult(
                pricing_error=f"Expiry date {expiry_date} is not after reference date {ref_date}",
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
            )

        # Compute the forward swap rate
        calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        swap_start = calendar.advance(_datetime_to_ql_date(expiry_date), ql.Period(2, ql.Days))
        swap_tenor = _parse_tenor_to_ql_period(underlying_tenor)
        swap_end = calendar.advance(swap_start, swap_tenor)

        day_count = ql.Actual360()
        sofr_index = ql.OvernightIndex("SOFR", 0, ql.USDCurrency(), calendar, day_count, curve_handle)

        # Build a par swap to get the forward rate
        fwd_swap = ql.MakeOIS(
            swapTenor=ql.Period(0, ql.Days),
            overnightIndex=sofr_index,
            fixedRate=0.0,
            fwdStart=ql.Period(0, ql.Days),
            effectiveDate=swap_start,
            terminationDate=swap_end,
            nominal=abs(notional),
            paymentFrequency=ql.Annual,
            receiveFixed=True,
        )
        fwd_rate = fwd_swap.fairRate() * 100.0  # Convert to percentage
        result.underlying_fwd_rate = fwd_rate

        # Use a reasonable initial guess for implied vol based on typical market levels
        initial_vol_guess = 0.007  # 70bp annualized normal vol as starting point

        # If we have a market premium, solve for implied vol
        implied_vol = None
        if market_premium is not None and not pd.isna(market_premium) and float(market_premium) > 0:
            market_premium = float(market_premium)

            # For a straddle, the premium is the sum of call and put
            # Solve for implied vol using the straddle premium
            # We'll iterate to find the vol that gives total straddle NPV = market_premium
            implied_vol = _solve_straddle_implied_vol(
                curve_handle=curve_handle,
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
                market_straddle_premium=market_premium,
                initial_guess=initial_vol_guess,
            )

        if implied_vol is None:
            implied_vol = initial_vol_guess  # Use a reasonable default

        result.bpvol_yr = implied_vol * 10000.0  # Convert to basis points

        # Create the straddle instruments at the implied vol
        vol_handle = ql.QuoteHandle(ql.SimpleQuote(implied_vol))

        # Build call (payer) swaption
        call_swaption = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Call,
            vol_handle=vol_handle,
        )

        # Build put (receiver) swaption
        put_swaption = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Put,
            vol_handle=vol_handle,
        )

        # Straddle premium
        call_npv = call_swaption.NPV()
        put_npv = put_swaption.NPV()
        result.fwd_premium = call_npv + put_npv

        # Compute Greeks
        # DV01: sensitivity to 1bp parallel shift in rates
        rate_shift = rate_shift_bp / 10000.0
        bumped_up_curve = ql.ZeroSpreadedTermStructure(curve_handle, ql.QuoteHandle(ql.SimpleQuote(rate_shift)))
        bumped_up_handle = ql.YieldTermStructureHandle(bumped_up_curve)
        bumped_down_curve = ql.ZeroSpreadedTermStructure(curve_handle, ql.QuoteHandle(ql.SimpleQuote(-rate_shift)))
        bumped_down_handle = ql.YieldTermStructureHandle(bumped_down_curve)

        # Rebuild swaptions with bumped curves
        call_up = _build_swaption(
            curve_handle=bumped_up_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Call,
            vol_handle=vol_handle,
        )
        put_up = _build_swaption(
            curve_handle=bumped_up_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Put,
            vol_handle=vol_handle,
        )
        call_down = _build_swaption(
            curve_handle=bumped_down_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Call,
            vol_handle=vol_handle,
        )
        put_down = _build_swaption(
            curve_handle=bumped_down_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Put,
            vol_handle=vol_handle,
        )

        straddle_up = call_up.NPV() + put_up.NPV()
        straddle_down = call_down.NPV() + put_down.NPV()
        straddle_base = call_npv + put_npv

        # DV01 = (P_down - P_up) / 2 for 1bp shift
        result.dv01 = (straddle_down - straddle_up) / 2.0

        # Gamma01 = (P_up - 2*P_base + P_down) / (shift)^2 * notional_scaling
        result.gamma01 = (straddle_up - 2 * straddle_base + straddle_down) / (rate_shift ** 2) * (rate_shift_bp / 10000.0)

        # Vega01: sensitivity to 1bp move in implied vol
        vol_shift = vol_shift_bp / 10000.0
        vol_up_handle = ql.QuoteHandle(ql.SimpleQuote(implied_vol + vol_shift))
        vol_down_handle = ql.QuoteHandle(ql.SimpleQuote(implied_vol - vol_shift))

        call_vol_up = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Call,
            vol_handle=vol_up_handle,
        )
        put_vol_up = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Put,
            vol_handle=vol_up_handle,
        )
        call_vol_down = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Call,
            vol_handle=vol_down_handle,
        )
        put_vol_down = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Put,
            vol_handle=vol_down_handle,
        )

        straddle_vol_up = call_vol_up.NPV() + put_vol_up.NPV()
        straddle_vol_down = call_vol_down.NPV() + put_vol_down.NPV()

        # Vega01 = (P_vol_up - P_vol_down) / 2 for 1bp vol shift
        result.vega01 = (straddle_vol_up - straddle_vol_down) / 2.0

        # Theta: 1-day time decay
        # Move evaluation date forward by 1 day
        original_eval_date = ql.Settings.instance().evaluationDate
        ql.Settings.instance().evaluationDate = original_eval_date + ql.Period(1, ql.Days)

        call_theta = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Call,
            vol_handle=vol_handle,
        )
        put_theta = _build_swaption(
            curve_handle=curve_handle,
            expiry_date=expiry_date,
            underlying_tenor=underlying_tenor,
            strike=strike,
            notional=notional,
            option_type=ql.Option.Put,
            vol_handle=vol_handle,
        )

        straddle_theta = call_theta.NPV() + put_theta.NPV()
        result.theta1d = straddle_theta - straddle_base

        # Restore evaluation date
        ql.Settings.instance().evaluationDate = original_eval_date

    except Exception as e:
        result.pricing_error = str(e)

    return result


def _solve_straddle_implied_vol(
    curve_handle: "ql.YieldTermStructureHandle",
    expiry_date: datetime.date,
    underlying_tenor: str,
    strike: float,
    notional: float,
    market_straddle_premium: float,
    initial_guess: float = 0.007,
    max_iterations: int = 50,
    tolerance: float = 1e-6,
) -> Optional[float]:
    """
    Solve for the implied normal volatility that matches a market straddle premium.

    Uses Newton-Raphson iteration on the straddle (call + put) premium.
    """
    if ql is None:
        return None

    vol_guess = initial_guess

    for _ in range(max_iterations):
        try:
            vol_handle = ql.QuoteHandle(ql.SimpleQuote(vol_guess))

            call_swaption = _build_swaption(
                curve_handle=curve_handle,
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
                option_type=ql.Option.Call,
                vol_handle=vol_handle,
            )
            put_swaption = _build_swaption(
                curve_handle=curve_handle,
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
                option_type=ql.Option.Put,
                vol_handle=vol_handle,
            )

            model_premium = call_swaption.NPV() + put_swaption.NPV()
            price_diff = model_premium - market_straddle_premium

            if abs(price_diff) < tolerance:
                return vol_guess

            # Compute straddle vega for Newton step
            vol_bump = 0.0001
            vol_up_handle = ql.QuoteHandle(ql.SimpleQuote(vol_guess + vol_bump))

            call_up = _build_swaption(
                curve_handle=curve_handle,
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
                option_type=ql.Option.Call,
                vol_handle=vol_up_handle,
            )
            put_up = _build_swaption(
                curve_handle=curve_handle,
                expiry_date=expiry_date,
                underlying_tenor=underlying_tenor,
                strike=strike,
                notional=notional,
                option_type=ql.Option.Put,
                vol_handle=vol_up_handle,
            )

            premium_up = call_up.NPV() + put_up.NPV()
            straddle_vega = (premium_up - model_premium) / vol_bump

            if abs(straddle_vega) < 1e-12:
                break

            vol_guess = vol_guess - price_diff / straddle_vega
            vol_guess = max(0.0001, min(vol_guess, 0.15))  # Bound between 1bp and 1500bp

        except Exception:
            break

    return vol_guess if vol_guess > 0 else None
