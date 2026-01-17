from __future__ import annotations

import pandas as pd
import QuantLib as ql

from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve

from SDRUtils.products._swaptions.pricer.greeks import _compute_swaption_leg_greeks
from SDRUtils.products._swaptions.pricer.parsing import _identify_risk_reversal_structure, _parse_risk_reversal_legs
from SDRUtils.products._swaptions.pricer.results import USDSwaptionDealerRiskReversalSkewResult


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
