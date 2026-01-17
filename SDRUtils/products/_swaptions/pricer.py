from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, NamedTuple, Tuple

import numpy as np
import pandas as pd
import QuantLib as ql

import Query.IRSwaps.adapter  # noqa: F401
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery


class _SwaptionLegGreeks(NamedTuple):
    """Internal container for single leg Greeks."""

    bpvol_yr: float
    dv01: float
    gamma01: float
    vega01: float
    theta1d: float


@dataclass
class USDSwaptionDealerRiskReversalSkewResult:
    """Result of backing out skew from a risk reversal package."""

    trade_label: str
    atm_strike: float
    otm_payer_strike: float
    otm_receiver_strike: float
    wing_strike_width: float
    atm_bpvol_yr: float
    otm_payer_bpvol_yr: float
    otm_receiver_bpvol_yr: float
    payer_skew_bpvol_yr: float
    receiver_skew_bpvol_yr: float
    skew_bpvol_yr: float  # otm_payer_bpvol - otm_receiver_bpvol
    atm_notional: float
    wing_notional: float
    # Wing-level Greeks
    otm_payer_vega01: float
    otm_receiver_vega01: float
    # Aggregate Greeks (all 4 legs)
    dv01: float
    gamma01: float
    vega01: float
    theta1d: float
    wing_dv01: float


@dataclass
class USDSwaptionStraddlePricerResult:
    trade_label: str
    ql_payer_swaption: ql.Swaption
    ql_receiver_swaption: ql.Swaption
    notional: float
    fwd_prem: float
    bpvol_yr: float
    dv01: float
    gamma01: float
    vega01: float
    theta1d: float


@dataclass
class USDSwaptionLegPricerResult:
    trade_label: str
    ql_swaption: ql.Swaption
    fwd_prem: float
    notional: float
    bpvol_yr: float
    dv01: float
    vega01: float
    gamma01: float
    theta1d: float


def usd_swaption_leg_pricer_from_row(
    final_classification_row: pd.Series,
    pricer: QLIRSwapCurve,
    *,
    leg: Literal["payer", "receiver"] = None,
    fwd_prem: float = None,
    dStrike: float = 1.0,
) -> USDSwaptionLegPricerResult:
    """
    Prices a single swaption leg (payer or receiver) off the row definition.
    """
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    if leg is None:
        leg = "receiver" if "rec" in str(final_classification_row["trade_label"]).lower() else "payer"
    if fwd_prem is None:
        fwd_prem = final_classification_row["premium"]

    ql_underlying_pricing_engine = ql.DiscountingSwapEngine(pricer.handle())

    notional = abs(final_classification_row["notional"])
    signed_notional = (-1.0 if leg == "payer" else 1.0) * notional
    strike_percent = final_classification_row["strike"] * 100.0

    base_query = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=final_classification_row["expiration_date"],
        maturity_date=final_classification_row["underlying_expiration_date"],
        structure_kwargs={"notional": signed_notional, "fixed_rate": strike_percent},
    )
    ql_underlying_pkg, _ = base_query.resolve_package(pricer_or_curve=pricer)
    ql_underlying: ql.OvernightIndexedSwap = ql_underlying_pkg[0]
    ql_underlying.setPricingEngine(ql_underlying_pricing_engine)

    ql_swaption = ql.Swaption(ql_underlying, ql.EuropeanExercise(ql_underlying.startDate()))
    initial_engine = ql.BachelierSwaptionEngine(
        pricer.handle(),
        ql.QuoteHandle(ql.SimpleQuote(0.0)),
        pricer.daycounter(),
    )
    ql_swaption.setPricingEngine(initial_engine)

    iv_bpvol_yr = (
        ql_swaption.impliedVolatility(
            price=fwd_prem,
            discountCurve=pricer.handle(),
            guess=0.01,
            accuracy=1e-8,
            maxEvaluations=1000,
            minVol=0.0,
            maxVol=1,
            type=ql.Normal,
            displacement=0.0,
            priceType=ql.Swaption.Forward,
        )
        * 10_000.0
    )

    implied_engine = ql.BachelierSwaptionEngine(
        pricer.handle(),
        ql.QuoteHandle(ql.SimpleQuote(iv_bpvol_yr / 10_000.0)),
        pricer.daycounter(),
    )
    ql_swaption.setPricingEngine(implied_engine)

    dv01 = ql_swaption.delta() / 10_000.0
    vega01 = ql_swaption.vega() / 10_000.0

    query_up = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=final_classification_row["expiration_date"],
        maturity_date=final_classification_row["underlying_expiration_date"],
        structure_kwargs={"notional": signed_notional, "fixed_rate": strike_percent + dStrike},
    )
    ql_underlying_up_pkg, _ = query_up.resolve_package(pricer_or_curve=pricer)
    ql_underlying_up: ql.OvernightIndexedSwap = ql_underlying_up_pkg[0]
    ql_underlying_up.setPricingEngine(ql_underlying_pricing_engine)

    query_down = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=final_classification_row["expiration_date"],
        maturity_date=final_classification_row["underlying_expiration_date"],
        structure_kwargs={"notional": signed_notional, "fixed_rate": strike_percent - dStrike},
    )
    ql_underlying_down_pkg, _ = query_down.resolve_package(pricer_or_curve=pricer)
    ql_underlying_down: ql.OvernightIndexedSwap = ql_underlying_down_pkg[0]
    ql_underlying_down.setPricingEngine(ql_underlying_pricing_engine)

    ql_swaption_up = ql.Swaption(ql_underlying_up, ql.EuropeanExercise(ql_underlying_up.startDate()))
    ql_swaption_down = ql.Swaption(ql_underlying_down, ql.EuropeanExercise(ql_underlying_down.startDate()))
    ql_swaption_up.setPricingEngine(implied_engine)
    ql_swaption_down.setPricingEngine(implied_engine)

    gamma01 = ((ql_swaption_down.delta() / 10_000.0) - (ql_swaption_up.delta() / 10_000.0)) / (2.0 * dStrike) / 100.0

    price_today = ql_swaption.NPV()
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate() + 1
    theta1d = price_today - ql_swaption.NPV()
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    return USDSwaptionLegPricerResult(
        trade_label=final_classification_row["trade_label"],
        ql_swaption=ql_swaption,
        bpvol_yr=iv_bpvol_yr,
        fwd_prem=fwd_prem,
        notional=notional,
        dv01=dv01,
        vega01=vega01,
        gamma01=gamma01,
        theta1d=theta1d,
    )


class SingleStraddleLegException(Exception):
    pass


def usd_swaption_straddle_pricer_from_row(final_classification_row: pd.Series, pricer: QLIRSwapCurve):
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    half_fwd_prem = final_classification_row["premium"] / 2.0

    payer_res = usd_swaption_leg_pricer_from_row(
        final_classification_row,
        pricer,
        leg="payer",
        fwd_prem=half_fwd_prem,
        dStrike=1.0,
    )
    receiver_res = usd_swaption_leg_pricer_from_row(
        final_classification_row,
        pricer,
        leg="receiver",
        fwd_prem=half_fwd_prem,
        dStrike=1.0,
    )

    bpvol_yr = (payer_res.bpvol_yr + receiver_res.bpvol_yr) / 2.0

    if bpvol_yr <= 35:
        raise SingleStraddleLegException("tooo low vol")

    dv01 = payer_res.dv01 + receiver_res.dv01
    gamma01 = abs(payer_res.gamma01 + receiver_res.gamma01)
    vega01 = payer_res.vega01 + receiver_res.vega01
    theta1d = -abs(payer_res.theta1d + receiver_res.theta1d)

    return USDSwaptionStraddlePricerResult(
        trade_label=final_classification_row.get("trade_label", None),
        ql_payer_swaption=payer_res.ql_swaption,
        ql_receiver_swaption=receiver_res.ql_swaption,
        notional=abs(final_classification_row["notional"]),
        fwd_prem=final_classification_row["premium"],
        bpvol_yr=bpvol_yr,
        dv01=dv01,
        gamma01=gamma01,
        vega01=vega01,
        theta1d=theta1d,
    )


def _parse_delimited_field(value, dtype=float, delim: str = " / ") -> List:
    """Parse a delimited string field into a list of values."""
    if pd.isna(value):
        return []
    if isinstance(value, str):
        parts = value.split(delim)
        result = []
        for p in parts:
            p = p.strip().replace(",", "")
            if dtype == float:
                try:
                    result.append(float(p))
                except ValueError:
                    result.append(np.nan)
            else:
                result.append(p)
        return result
    return [value]


def _parse_risk_reversal_legs(
    row: pd.Series,
    delim: str = " / ",
) -> Tuple[List[float], List[float], List[float], List[str]]:
    """Parse a collapsed risk reversal row into individual leg components."""
    strikes = _parse_delimited_field(row.get("strike"), dtype=float, delim=delim)
    premiums = _parse_delimited_field(row.get("premium"), dtype=float, delim=delim)
    notionals = _parse_delimited_field(row.get("notional"), dtype=float, delim=delim)
    product_types = _parse_delimited_field(row.get("product_type"), dtype=str, delim=delim)

    return strikes, premiums, notionals, product_types


def _identify_risk_reversal_structure(
    strikes: List[float],
    premiums: List[float],
    notionals: List[float],
    product_types: List[str],
    strike_tolerance: float = 0.0001,
) -> Tuple[
    Tuple[float, float, float],  # atm_strike, atm_payer_premium, atm_receiver_premium
    Tuple[float, float, float],  # otm_payer_strike, otm_payer_premium, otm_payer_notional
    Tuple[float, float, float],  # otm_receiver_strike, otm_receiver_premium, otm_receiver_notional
    float,  # atm_notional
]:
    """
    Identify the structure of a risk reversal from parsed legs.

    Risk reversal structure:
    - 4 legs total
    - 3 distinct strikes (low, middle/ATM, high)
    - Middle strike has payer + receiver (ATM straddle, smaller notional)
    - Low strike is OTM receiver (put wing) - forced regardless of SDR label
    - High strike is OTM payer (call wing) - forced regardless of SDR label
    """
    if len(strikes) != 4:
        raise ValueError(f"Risk reversal must have 4 legs, got {len(strikes)}")

    strike_groups = {}
    for i, strike in enumerate(strikes):
        bucket = round(strike / strike_tolerance) if strike_tolerance > 0 else strike
        if bucket not in strike_groups:
            strike_groups[bucket] = []
        strike_groups[bucket].append(i)

    if len(strike_groups) != 3:
        raise ValueError(f"Risk reversal must have 3 distinct strikes, got {len(strike_groups)}")

    sorted_groups = sorted(
        strike_groups.items(),
        key=lambda x: np.mean([strikes[i] for i in x[1]]),
    )

    low_group = sorted_groups[0][1]
    mid_group = sorted_groups[1][1]
    high_group = sorted_groups[2][1]

    if len(mid_group) != 2:
        raise ValueError(f"ATM strike should have 2 legs (payer+receiver), got {len(mid_group)}")

    atm_strike = np.mean([strikes[i] for i in mid_group])
    low_strike = np.mean([strikes[i] for i in low_group])
    high_strike = np.mean([strikes[i] for i in high_group])

    # Find ATM payer and receiver premiums by product_type
    atm_payer_premium = None
    atm_receiver_premium = None
    atm_notional = None
    for i in mid_group:
        pt = product_types[i].upper()
        if "PAYER" in pt:
            atm_payer_premium = premiums[i]
            atm_notional = abs(notionals[i])
        elif "RECEIVER" in pt:
            atm_receiver_premium = premiums[i]
            if atm_notional is None:
                atm_notional = abs(notionals[i])

    if atm_payer_premium is None or atm_receiver_premium is None:
        raise ValueError("ATM straddle must have both payer and receiver legs")

    # OTM wings: force low strike = receiver, high strike = payer
    # Always use the leg at that strike level, regardless of SDR product_type label
    low_idx = low_group[0]
    high_idx = high_group[0]

    # Extract premiums/notionals by strike level (not by product_type)
    otm_receiver_strike = low_strike
    otm_receiver_premium = premiums[low_idx]
    otm_receiver_notional = abs(notionals[low_idx])

    otm_payer_strike = high_strike
    otm_payer_premium = premiums[high_idx]
    otm_payer_notional = abs(notionals[high_idx])

    return (
        (atm_strike, atm_payer_premium, atm_receiver_premium),
        (otm_payer_strike, otm_payer_premium, otm_payer_notional),
        (otm_receiver_strike, otm_receiver_premium, otm_receiver_notional),
        atm_notional,
    )


def _compute_swaption_leg_greeks(
    pricer: QLIRSwapCurve,
    expiration_date,
    underlying_expiration_date,
    strike: float,
    notional: float,
    fwd_prem: float,
    leg: Literal["payer", "receiver"],
    dStrike: float = 1.0,
) -> _SwaptionLegGreeks:
    """
    Compute full Greeks for a single swaption leg.

    Returns:
        _SwaptionLegGreeks with bpvol_yr, dv01, gamma01, vega01, theta1d
    """
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    ql_underlying_pricing_engine = ql.DiscountingSwapEngine(pricer.handle())

    signed_notional = (-1.0 if leg == "payer" else 1.0) * notional
    strike_percent = strike * 100.0

    base_query = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=expiration_date,
        maturity_date=underlying_expiration_date,
        structure_kwargs={"notional": signed_notional, "fixed_rate": strike_percent},
    )
    ql_underlying_pkg, _ = base_query.resolve_package(pricer_or_curve=pricer)
    ql_underlying: ql.OvernightIndexedSwap = ql_underlying_pkg[0]
    ql_underlying.setPricingEngine(ql_underlying_pricing_engine)

    ql_swaption = ql.Swaption(ql_underlying, ql.EuropeanExercise(ql_underlying.startDate()))
    initial_engine = ql.BachelierSwaptionEngine(
        pricer.handle(),
        ql.QuoteHandle(ql.SimpleQuote(0.0)),
        pricer.daycounter(),
    )
    ql_swaption.setPricingEngine(initial_engine)

    iv_bpvol_yr = (
        ql_swaption.impliedVolatility(
            price=fwd_prem,
            discountCurve=pricer.handle(),
            guess=0.01,
            accuracy=1e-8,
            maxEvaluations=1000,
            minVol=0.0,
            maxVol=1,
            type=ql.Normal,
            displacement=0.0,
            priceType=ql.Swaption.Forward,
        )
        * 10_000.0
    )

    implied_engine = ql.BachelierSwaptionEngine(
        pricer.handle(),
        ql.QuoteHandle(ql.SimpleQuote(iv_bpvol_yr / 10_000.0)),
        pricer.daycounter(),
    )
    ql_swaption.setPricingEngine(implied_engine)

    dv01 = ql_swaption.delta() / 10_000.0
    vega01 = ql_swaption.vega() / 10_000.0

    # Gamma via central difference on strike
    query_up = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=expiration_date,
        maturity_date=underlying_expiration_date,
        structure_kwargs={"notional": signed_notional, "fixed_rate": strike_percent + dStrike},
    )
    ql_underlying_up_pkg, _ = query_up.resolve_package(pricer_or_curve=pricer)
    ql_underlying_up: ql.OvernightIndexedSwap = ql_underlying_up_pkg[0]
    ql_underlying_up.setPricingEngine(ql_underlying_pricing_engine)

    query_down = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=expiration_date,
        maturity_date=underlying_expiration_date,
        structure_kwargs={"notional": signed_notional, "fixed_rate": strike_percent - dStrike},
    )
    ql_underlying_down_pkg, _ = query_down.resolve_package(pricer_or_curve=pricer)
    ql_underlying_down: ql.OvernightIndexedSwap = ql_underlying_down_pkg[0]
    ql_underlying_down.setPricingEngine(ql_underlying_pricing_engine)

    ql_swaption_up = ql.Swaption(ql_underlying_up, ql.EuropeanExercise(ql_underlying_up.startDate()))
    ql_swaption_down = ql.Swaption(ql_underlying_down, ql.EuropeanExercise(ql_underlying_down.startDate()))
    ql_swaption_up.setPricingEngine(implied_engine)
    ql_swaption_down.setPricingEngine(implied_engine)

    gamma01 = ((ql_swaption_down.delta() / 10_000.0) - (ql_swaption_up.delta() / 10_000.0)) / (2.0 * dStrike) / 100.0

    # Theta via 1-day roll
    price_today = ql_swaption.NPV()
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate() + 1
    theta1d = price_today - ql_swaption.NPV()
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    return _SwaptionLegGreeks(
        bpvol_yr=iv_bpvol_yr,
        dv01=dv01,
        gamma01=gamma01,
        vega01=vega01,
        theta1d=theta1d,
    )


def usd_swaption_dealer_risk_reversal_skew_from_row(
    risk_reversal_row: pd.Series,
    pricer: QLIRSwapCurve,
    *,
    delim: str = " / ",
    strike_tolerance: float = 0.0001,
) -> USDSwaptionDealerRiskReversalSkewResult:
    """
    Back out the skew in bpvol from a risk reversal package row.

    A risk reversal consists of:
    - ATM straddle (payer + receiver at middle strike, smaller notional)
    - OTM payer (high strike, larger notional) - the "call wing"
    - OTM receiver (low strike, larger notional) - the "put wing"

    The skew is the difference in implied volatilities between the OTM wings:
        skew = otm_payer_bpvol - otm_receiver_bpvol

    Positive skew means higher vol for high strikes (payer skew).
    Negative skew means higher vol for low strikes (receiver skew).
    """
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    pkg_type = risk_reversal_row.get("package_type", "")
    if pkg_type != "RISK_REVERSAL":
        raise ValueError(f"Expected RISK_REVERSAL package, got {pkg_type}")

    strikes, premiums, notionals, product_types = _parse_risk_reversal_legs(risk_reversal_row, delim=delim)

    (
        (atm_strike, atm_payer_premium, atm_receiver_premium),
        (otm_payer_strike, otm_payer_premium, otm_payer_notional),
        (otm_receiver_strike, otm_receiver_premium, otm_receiver_notional),
        atm_notional,
    ) = _identify_risk_reversal_structure(strikes, premiums, notionals, product_types, strike_tolerance=strike_tolerance)

    expiration_date = risk_reversal_row["expiration_date"]
    underlying_expiration_date = risk_reversal_row["underlying_expiration_date"]

    # Compute full Greeks for all 4 legs
    atm_payer_greeks = _compute_swaption_leg_greeks(
        pricer,
        expiration_date,
        underlying_expiration_date,
        atm_strike,
        atm_notional,
        atm_payer_premium,
        "payer",
    )
    atm_receiver_greeks = _compute_swaption_leg_greeks(
        pricer,
        expiration_date,
        underlying_expiration_date,
        atm_strike,
        atm_notional,
        atm_receiver_premium,
        "receiver",
    )
    otm_payer_greeks = _compute_swaption_leg_greeks(
        pricer,
        expiration_date,
        underlying_expiration_date,
        otm_payer_strike,
        otm_payer_notional,
        otm_payer_premium,
        "payer",
    )
    otm_receiver_greeks = _compute_swaption_leg_greeks(
        pricer,
        expiration_date,
        underlying_expiration_date,
        otm_receiver_strike,
        otm_receiver_notional,
        otm_receiver_premium,
        "receiver",
    )

    atm_bpvol_yr = (atm_payer_greeks.bpvol_yr + atm_receiver_greeks.bpvol_yr) / 2.0
    skew_bpvol_yr = otm_payer_greeks.bpvol_yr - otm_receiver_greeks.bpvol_yr

    # Aggregate Greeks across all 4 legs
    # double check here please 
    dv01 = atm_payer_greeks.dv01 + atm_receiver_greeks.dv01 + otm_payer_greeks.dv01 + otm_receiver_greeks.dv01
    gamma01 = (
        (abs(atm_payer_greeks.gamma01) + (atm_receiver_greeks.gamma01)) + abs(otm_payer_greeks.gamma01) - abs(otm_receiver_greeks.gamma01)
    )  # assume long payer skew
    vega01 = (
        (abs(atm_payer_greeks.vega01) + abs(atm_receiver_greeks.vega01)) + abs(otm_payer_greeks.vega01) - abs(otm_receiver_greeks.vega01)
    )  # assume long payer skew
    theta1d = -abs(atm_payer_greeks.theta1d + atm_receiver_greeks.theta1d + otm_payer_greeks.theta1d) + abs(otm_receiver_greeks.theta1d)

    return USDSwaptionDealerRiskReversalSkewResult(
        trade_label=risk_reversal_row.get("trade_label", ""),
        atm_strike=atm_strike,
        otm_payer_strike=otm_payer_strike,
        otm_receiver_strike=otm_receiver_strike,
        wing_strike_width=(otm_payer_strike - otm_receiver_strike) * 10_000,
        atm_bpvol_yr=atm_bpvol_yr,
        otm_payer_bpvol_yr=otm_payer_greeks.bpvol_yr,
        otm_receiver_bpvol_yr=otm_receiver_greeks.bpvol_yr,
        payer_skew_bpvol_yr=otm_payer_greeks.bpvol_yr - atm_bpvol_yr,
        receiver_skew_bpvol_yr=otm_receiver_greeks.bpvol_yr - atm_bpvol_yr,
        skew_bpvol_yr=skew_bpvol_yr,
        atm_notional=atm_notional,
        wing_notional=otm_payer_notional,
        otm_payer_vega01=otm_payer_greeks.vega01,
        otm_receiver_vega01=otm_receiver_greeks.vega01,
        dv01=dv01,
        gamma01=gamma01,
        vega01=vega01,
        theta1d=theta1d,
        wing_dv01=abs(otm_payer_greeks.dv01) + abs(otm_receiver_greeks.dv01),
    )
