"""Pure dealer-direction rules (spec section 5). Confidence added separately."""
from __future__ import annotations

import dataclasses

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow.trade_selection import Unit, resolve_upfront


@dataclasses.dataclass
class DirectionResult:
    unit_key: str
    trade_id: str | None
    package_id: str | None
    classification_method: str
    dealer_direction: str = "UNKNOWN"
    dealer_bought: bool | None = None
    is_off_market: bool = False
    curve_mid: float | None = None
    curve_mid_spread_bps: float | None = None
    traded_spread_bps: float | None = None
    spread_to_mid_bps: float | None = None
    repriced_npv: float | None = None
    repriced_pv01: float | None = None
    reported_opa: float | None = None
    reported_ptp: float | None = None
    dealer_charge: float | None = None
    dealer_charge_bps: float | None = None
    structure_dv01: float | None = None
    quality_flags: list = dataclasses.field(default_factory=list)


def structure_dv01(kind: str, pv01s: list) -> float:
    a = [abs(float(p)) for p in pv01s]
    if kind == "OUTRIGHT":
        return a[0]
    if kind == "CURVE":
        return max(a)
    if kind == "FLY":
        return a[1]                    # legs sorted by maturity -> middle = belly
    return sum(a) / 2.0                # PKG-N: gross/2


def _rate_pct(decimal_rate) -> float:
    return float(decimal_rate) * 100.0


def classify_unit(unit: Unit, pricings: list) -> DirectionResult:
    legs = unit.legs
    first = legs.iloc[0]
    res = DirectionResult(
        unit_key=unit.unit_key,
        trade_id=first["trade_id"] if unit.kind == "OUTRIGHT" else None,
        package_id=unit.package_id,
        classification_method="",
        is_off_market=unit.is_off_market,
    )
    pv01s = [p.pv01 for p in pricings]
    res.structure_dv01 = structure_dv01(unit.kind, pv01s)
    res.repriced_pv01 = sum(abs(p) for p in pv01s)
    ptp_raw = first.get("pkg_ptp")
    if ptp_raw is not None and ptp_raw == ptp_raw:
        res.reported_ptp = float(ptp_raw)
    ufros = list(legs["other_payment_ufro"].fillna(0.0))
    res.reported_opa = sum(ufros) if any(u > 0 for u in ufros) else None

    if unit.is_off_market:
        res.classification_method = "NPV_VS_UPFRONT"
        upfront, src, disagree = resolve_upfront(ptp_raw, ufros)
        if disagree:
            res.quality_flags.append("PTP_UFRO_DISAGREE")
        if upfront is None:
            res.quality_flags.append("NO_UPFRONT")
            return res
        npv_pay = sum(p.npv_pay for p in pricings)
        res.repriced_npv = npv_pay
        res.dealer_bought = upfront < abs(npv_pay)
        itm_side = "PAID" if npv_pay > 0 else "RECEIVED"
        other = "RECEIVED" if itm_side == "PAID" else "PAID"
        res.dealer_direction = itm_side if res.dealer_bought else other
        res.dealer_charge = abs(abs(npv_pay) - upfront)
        res.dealer_charge_bps = res.dealer_charge / res.structure_dv01
        return res

    # on-market
    traded = [_rate_pct(r) for r in legs["fixed_rate"]]
    mids = [p.mid_pct for p in pricings]
    if unit.kind == "OUTRIGHT":
        res.classification_method = "RATE_VS_MID"
        res.curve_mid = mids[0]
        s2m = (traded[0] - mids[0]) * 100.0
    elif unit.kind == "CURVE":
        res.classification_method = "SPREAD_VS_MID"
        res.traded_spread_bps = (traded[1] - traded[0]) * 100.0
        res.curve_mid_spread_bps = (mids[1] - mids[0]) * 100.0
        s2m = res.traded_spread_bps - res.curve_mid_spread_bps
    elif unit.kind == "FLY":
        res.classification_method = "FLY_VS_MID"
        res.traded_spread_bps = (2 * traded[1] - traded[0] - traded[2]) * 100.0
        res.curve_mid_spread_bps = (2 * mids[1] - mids[0] - mids[2]) * 100.0
        s2m = res.traded_spread_bps - res.curve_mid_spread_bps
    else:
        res.classification_method = "RATE_VS_MID"
        res.quality_flags.append("ON_MARKET_PKG_N_UNSUPPORTED")
        return res
    res.spread_to_mid_bps = s2m
    res.dealer_direction = "RECEIVED" if s2m > 0 else "PAID"
    return res
