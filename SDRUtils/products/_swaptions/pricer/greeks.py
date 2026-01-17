from __future__ import annotations

from typing import Literal

import QuantLib as ql

import Query.IRSwaps.adapter  # noqa: F401
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

from SDRUtils.products._swaptions.pricer.constants import BENCHMARK_OFFSETS
from SDRUtils.products._swaptions.pricer.results import _SwaptionLegGreeks


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

    # ATMF
    atm_query = IRSwapQuery(
        curve="USD-SOFR-1D",
        effective_date=expiration_date,
        maturity_date=underlying_expiration_date,
        structure_kwargs={"notional": signed_notional},
    )
    ql_atm_underlying_pkg, atm_rws = atm_query.resolve_package(pricer_or_curve=pricer)
    atm_vmap = atm_query.build_value_map(pricer_or_curve=pricer, package=ql_atm_underlying_pkg, risk_weights=atm_rws)
    atmf = abs(atm_vmap.apply(value=IRSwapValue.RATE))

    return _SwaptionLegGreeks(
        bpvol_yr=iv_bpvol_yr,
        dv01=dv01,
        gamma01=gamma01,
        vega01=vega01,
        theta1d=theta1d,
        strike_offset=min(BENCHMARK_OFFSETS, key=lambda x: abs(x - (strike_percent - atmf) * 100)),
    )
