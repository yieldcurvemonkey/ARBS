from __future__ import annotations

from typing import Literal

import pandas as pd
import QuantLib as ql

from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve

from SDRUtils.products._swaptions.pricer.greeks import _compute_swaption_leg_greeks
from SDRUtils.products._swaptions.pricer.parsing import _identify_vertical_spread_structure, _parse_delimited_field
from SDRUtils.products._swaptions.pricer.results import USDSwaptionVerticalSpreadPricerResult


def usd_swaption_vertical_spread_pricer_from_row(
    vertical_spread_row: pd.Series,
    pricer: QLIRSwapCurve,
    *,
    delim: str = " / ",
) -> USDSwaptionVerticalSpreadPricerResult:
    """
    Price a vertical spread (1x1 or 1x2) swaption package from a row.

    A vertical spread consists of:
    - Long one swaption at ATM strike
    - Short one swaption at OTM strike (same expiry, same underlying tenor)

    For payer spreads: long lower strike, short higher strike (bull spread on rates)
    For receiver spreads: long higher strike, short lower strike (bear spread on rates)

    Net Greeks reflect the spread position (long ATM leg, short OTM leg).

    Parameters
    ----------
    vertical_spread_row : pd.Series
        Row from classified SDR data with package_type containing "VERTICAL_SPREAD"
    pricer : QLIRSwapCurve
        Curve pricer for Greeks computation
    delim : str
        Delimiter for parsing collapsed fields (default " / ")

    Returns
    -------
    USDSwaptionVerticalSpreadPricerResult
        Spread-level and leg-level Greeks with vol spread metrics
    """
    ql.Settings.instance().evaluationDate = pricer.handle().referenceDate()

    pkg_type = vertical_spread_row.get("package_type", "")
    if "VERTICAL_SPREAD" not in pkg_type:
        raise ValueError(f"Expected VERTICAL_SPREAD package, got {pkg_type}")

    # Reuse existing parsing helper
    strikes = _parse_delimited_field(vertical_spread_row.get("strike"), dtype=float, delim=delim)
    premiums = _parse_delimited_field(vertical_spread_row.get("premium"), dtype=float, delim=delim)
    notionals = _parse_delimited_field(vertical_spread_row.get("notional"), dtype=float, delim=delim)
    product_types = _parse_delimited_field(vertical_spread_row.get("product_type"), dtype=str, delim=delim)

    spread_type, atm, otm = _identify_vertical_spread_structure(strikes, premiums, notionals, product_types)

    atm_strike, atm_premium, atm_notional = atm
    otm_strike, otm_premium, otm_notional = otm

    expiration_date = vertical_spread_row["expiration_date"]
    underlying_expiration_date = vertical_spread_row["underlying_expiration_date"]

    leg_type: Literal["payer", "receiver"] = "payer" if spread_type == "PAYER_SPREAD" else "receiver"

    # Compute Greeks for each leg using existing helper
    atm_greeks = _compute_swaption_leg_greeks(
        pricer,
        expiration_date,
        underlying_expiration_date,
        atm_strike,
        atm_notional,
        atm_premium,
        leg_type,
    )

    otm_greeks = _compute_swaption_leg_greeks(
        pricer,
        expiration_date,
        underlying_expiration_date,
        otm_strike,
        otm_notional,
        otm_premium,
        leg_type,
    )

    # Aggregate Greeks: long ATM, short OTM
    notional_ratio = otm_notional / atm_notional if atm_notional > 0 else 1.0

    dv01 = atm_greeks.dv01 - otm_greeks.dv01
    gamma01 = atm_greeks.gamma01 - otm_greeks.gamma01
    vega01 = atm_greeks.vega01 - otm_greeks.vega01
    theta1d = atm_greeks.theta1d - otm_greeks.theta1d

    net_premium = atm_premium - otm_premium
    strike_width_bps = abs(otm_strike - atm_strike) * 10_000
    vol_spread = otm_greeks.bpvol_yr - atm_greeks.bpvol_yr

    return USDSwaptionVerticalSpreadPricerResult(
        trade_label=vertical_spread_row.get("trade_label", ""),
        spread_type=spread_type,
        atm_strike=atm_strike,
        otm_strike=otm_strike,
        strike_width_bps=strike_width_bps,
        atm_bpvol_yr=atm_greeks.bpvol_yr,
        otm_bpvol_yr=otm_greeks.bpvol_yr,
        vol_spread_bpvol_yr=vol_spread,
        atm_notional=atm_notional,
        otm_notional=otm_notional,
        notional_ratio=notional_ratio,
        net_premium=net_premium,
        atm_premium=atm_premium,
        otm_premium=otm_premium,
        atm_dv01=atm_greeks.dv01,
        atm_gamma01=atm_greeks.gamma01,
        atm_vega01=atm_greeks.vega01,
        atm_theta1d=atm_greeks.theta1d,
        otm_dv01=otm_greeks.dv01,
        otm_gamma01=otm_greeks.gamma01,
        otm_vega01=otm_greeks.vega01,
        otm_theta1d=otm_greeks.theta1d,
        dv01=dv01,
        gamma01=gamma01,
        vega01=vega01,
        theta1d=theta1d,
        atm_strike_offset=atm_greeks.strike_offset,
        otm_strike_offset=otm_greeks.strike_offset,
    )
