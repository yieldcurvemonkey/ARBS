from __future__ import annotations

from typing import Literal

import pandas as pd
import QuantLib as ql

import Query.IRSwaps.adapter  # noqa: F401
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

from SDRUtils.products._swaptions.pricer.results import USDSwaptionLegPricerResult


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
