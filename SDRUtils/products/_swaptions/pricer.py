from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

import pandas as pd
import QuantLib as ql

import Query.IRSwaps.adapter  # noqa: F401
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve
from Query.IRSwaps.IRSwapQuery import IRSwapQuery


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
    dStrike: float = 1.0,  # 1bp strike bump
) -> USDSwaptionLegPricerResult:
    """
    Prices a single swaption leg (payer or receiver) off the row definition.

    Notes:
    - Preserves your existing conventions:
      * notional sign encodes payer vs receiver (payer negative, receiver positive)
      * strike is in % (row strike in decimal, multiplied by 100)
      * premium passed in is FORWARD premium (priceType=Swaption.Forward)
      * Normal (Bachelier) vol
    - Greeks follow your existing helper conventions:
      dv01 = delta / 1e4
      vega01 = vega / 1e4
      gamma01 = central diff on delta vs strike, then scaled by /100
      theta1d computed by rolling evaluationDate +1 and repricing
    """
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    if leg is None:
        leg = "receiver" if "rec" in str(final_classification_row["trade_label"]).lower() else "payer"
    if fwd_prem is None:
        fwd_prem = final_classification_row["premium"]

    ql_underlying_pricing_engine = ql.DiscountingSwapEngine(pricer.handle())

    # Build underlying swap (strike in %, notional sign per leg)
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

    # Create leg swaption and imply vol from FORWARD premium
    ql_swaption = ql.Swaption(ql_underlying, ql.EuropeanExercise(ql_underlying.startDate()))
    print(ql_swaption.exercise().dates(), ql_underlying.maturityDate())
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

    # Relink swaption to implied vol engine
    implied_engine = ql.BachelierSwaptionEngine(
        pricer.handle(),
        ql.QuoteHandle(ql.SimpleQuote(iv_bpvol_yr / 10_000.0)),
        pricer.daycounter(),
    )
    ql_swaption.setPricingEngine(implied_engine)

    # DV01 / Vega01 in your units
    dv01 = ql_swaption.delta() / 10_000.0
    vega01 = ql_swaption.vega() / 10_000.0

    # Gamma01 via central diff on strike (rebuild bumped underlyings, reprice deltas)
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

    # Keep your sign convention (down - up), then absolute at the straddle level later
    gamma01 = ((ql_swaption_down.delta() / 10_000.0) - (ql_swaption_up.delta() / 10_000.0)) / (2.0 * dStrike) / 100.0

    # Theta 1d (roll eval date)
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


def usd_swaption_straddle_pricer_from_row(final_classification_row: pd.Series, pricer: QLIRSwapCurve):
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    # NOTE: Your existing implementation splits the straddle forward premium equally across legs.
    # This preserves that behavior exactly.
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

    dv01 = payer_res.dv01 + receiver_res.dv01
    gamma01 = abs(payer_res.gamma01 + receiver_res.gamma01)
    vega01 = payer_res.vega01 + receiver_res.vega01

    # Straddle theta: roll each leg consistently (your prior straddle code did this at the combined level;
    # summing leg thetas is equivalent here because each theta is computed as price_today - price_t+1).
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
