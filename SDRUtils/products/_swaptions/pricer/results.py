from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

import QuantLib as ql


class _SwaptionLegGreeks(NamedTuple):
    """Internal container for single leg Greeks."""

    bpvol_yr: float
    dv01: float
    gamma01: float
    vega01: float
    theta1d: float
    strike_offset: float


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


@dataclass
class USDSwaptionVerticalSpreadPricerResult:
    """Result of pricing a vertical spread (1x1 or 1x2) swaption package."""

    trade_label: str
    spread_type: Literal["PAYER_SPREAD", "RECEIVER_SPREAD"]
    atm_strike: float
    otm_strike: float
    strike_width_bps: float
    # Implied vols
    atm_bpvol_yr: float
    otm_bpvol_yr: float
    vol_spread_bpvol_yr: float  # otm - atm (skew component)
    # Notionals
    atm_notional: float
    otm_notional: float
    notional_ratio: float  # otm_notional / atm_notional
    # Premium
    net_premium: float  # atm_premium - otm_premium (positive = debit)
    atm_premium: float
    otm_premium: float
    # Leg-level Greeks
    atm_dv01: float
    atm_gamma01: float
    atm_vega01: float
    atm_theta1d: float
    otm_dv01: float
    otm_gamma01: float
    otm_vega01: float
    otm_theta1d: float
    # Aggregate Greeks (long ATM, short OTM)
    dv01: float
    gamma01: float
    vega01: float
    theta1d: float
    # Strike offsets from ATMF
    atm_strike_offset: float
    otm_strike_offset: float
