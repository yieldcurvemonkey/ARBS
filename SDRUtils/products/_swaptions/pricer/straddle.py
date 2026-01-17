from __future__ import annotations

import pandas as pd
import QuantLib as ql

from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve

from SDRUtils.products._swaptions.pricer.leg_pricer import usd_swaption_leg_pricer_from_row
from SDRUtils.products._swaptions.pricer.results import USDSwaptionStraddlePricerResult


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
