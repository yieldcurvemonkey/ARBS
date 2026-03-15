from __future__ import annotations

import math
from typing import Tuple

import QuantLib as ql


def ql_option_type(right: str) -> int:
    token = str(right).upper()
    if token in {"C", "CALL"}:
        return ql.Option.Call
    if token in {"P", "PUT"}:
        return ql.Option.Put
    raise ValueError(f"Unsupported option right for QuantLib Bachelier: {right}")


def bachelier_price(
    right: str,
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float,
) -> float:
    stddev = max(float(vol_normal), 0.0) * math.sqrt(max(float(tte), 1e-12))
    return float(
        ql.bachelierBlackFormula(
            ql_option_type(right),
            float(strike),
            float(forward),
            float(stddev),
            float(discount),
        )
    )


def implied_normal_vol(
    right: str,
    strike: float,
    forward: float,
    tte: float,
    price: float,
    discount: float,
) -> float:
    if float(tte) <= 0.0 or float(price) <= 0.0:
        return float("nan")
    try:
        return float(
            ql.bachelierBlackFormulaImpliedVolChoi(
                ql_option_type(right),
                float(strike),
                float(forward),
                float(tte),
                float(price),
                float(discount),
            )
        )
    except Exception:
        return float("nan")


def bachelier_greeks_fd(
    *,
    right: str,
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float,
    use_ql_calculator: bool = True,
) -> Tuple[float, float, float, float]:
    if tte <= 0.0 or not math.isfinite(vol_normal) or vol_normal <= 0.0:
        return float("nan"), float("nan"), float("nan"), float("nan")

    if use_ql_calculator:
        try:
            payoff = ql.PlainVanillaPayoff(ql_option_type(right), float(strike))
            stddev = max(float(vol_normal), 0.0) * math.sqrt(max(float(tte), 1e-12))
            calc = ql.BachelierCalculator(
                payoff,
                float(forward),
                float(stddev),
                float(discount),
            )
            delta = float(calc.deltaForward())
            gamma = float(calc.gammaForward())
            vega = float(calc.vega(float(tte)))
            theta = float(calc.theta(float(forward), float(tte)))
            return delta, gamma, vega, theta
        except Exception:
            pass

    h_f = 0.01
    h_v = max(1e-4, float(vol_normal) * 0.01)
    dt = 1.0 / 365.0

    p0 = bachelier_price(right, strike, forward, vol_normal, tte, discount)
    p_up = bachelier_price(right, strike, forward + h_f, vol_normal, tte, discount)
    p_dn = bachelier_price(right, strike, forward - h_f, vol_normal, tte, discount)
    delta = (p_up - p_dn) / (2.0 * h_f)
    gamma = (p_up - 2.0 * p0 + p_dn) / (h_f * h_f)

    pv_up = bachelier_price(right, strike, forward, vol_normal + h_v, tte, discount)
    pv_dn = bachelier_price(right, strike, forward, max(vol_normal - h_v, 1e-8), tte, discount)
    vega = (pv_up - pv_dn) / (2.0 * h_v)

    t_up = tte + dt
    t_dn = max(tte - dt, 1e-6)
    pt_up = bachelier_price(right, strike, forward, vol_normal, t_up, discount)
    pt_dn = bachelier_price(right, strike, forward, vol_normal, t_dn, discount)
    theta = (pt_up - pt_dn) / (2.0 * dt)

    return float(delta), float(gamma), float(vega), float(theta)
