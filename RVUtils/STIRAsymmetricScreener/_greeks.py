"""Per-candidate Greeks (entry + aged) for the STIR Options Asymmetric Screener.

Uses the Bachelier (normal-vol) model since STIR options are quoted in
normal-vol space. Greeks are aggregated across legs respecting leg
quantities. ``CandidateGreeks`` holds per-day theta, vega per vol-point,
gamma per bp², and delta as DV01 (signed).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from scipy.stats import norm

from RVUtils.STIRAsymmetricScreener._types import OptionLeg


@dataclass(frozen=True)
class CandidateGreeks:
    delta_dv01: float
    gamma_per_bp_squared: float
    vega_per_volpoint: float
    theta_per_day: float
    vega_aged_1m: float
    theta_aged_1m: float
    theta_aged_3m: float


def _bachelier_d(forward: float, strike: float, vol_normal: float, tte: float) -> float:
    sqrt_t = math.sqrt(max(tte, 1e-12))
    if vol_normal <= 0:
        return 0.0
    return (forward - strike) / (vol_normal * sqrt_t)


def _bachelier_call_delta_price(
    *, forward: float, strike: float, vol_normal: float, tte: float
) -> float:
    """Bachelier call delta in price space (∂C/∂F)."""
    if tte <= 0 or vol_normal <= 0:
        return 1.0 if forward > strike else 0.0
    return float(norm.cdf(_bachelier_d(forward, strike, vol_normal, tte)))


def _bachelier_call_gamma_price(
    *, forward: float, strike: float, vol_normal: float, tte: float
) -> float:
    """Bachelier call gamma in price space."""
    sqrt_t = math.sqrt(max(tte, 1e-12))
    if tte <= 0 or vol_normal <= 0:
        return 0.0
    d = _bachelier_d(forward, strike, vol_normal, tte)
    return float(norm.pdf(d)) / (vol_normal * sqrt_t)


def _bachelier_call_vega_price(
    *, forward: float, strike: float, vol_normal: float, tte: float
) -> float:
    """Bachelier call vega in price space (per unit normal vol)."""
    sqrt_t = math.sqrt(max(tte, 1e-12))
    if tte <= 0 or vol_normal <= 0:
        return 0.0
    d = _bachelier_d(forward, strike, vol_normal, tte)
    return sqrt_t * float(norm.pdf(d))


def _bachelier_call_theta_price_per_day(
    *, forward: float, strike: float, vol_normal: float, tte: float
) -> float:
    """Bachelier call theta in price space (per calendar day, sign convention:
    negative for long calls)."""
    if tte <= 1e-10 or vol_normal <= 0:
        return 0.0
    sqrt_t = math.sqrt(tte)
    d = _bachelier_d(forward, strike, vol_normal, tte)
    # Bachelier theta = -0.5 * sigma * phi(d) / sqrt(t) per unit time (years)
    theta_per_year = -0.5 * vol_normal * float(norm.pdf(d)) / sqrt_t
    return theta_per_year / 365.0


def _leg_greeks_price(
    *, leg: OptionLeg, forward: float, vol_normal: float, tte: float
) -> tuple[float, float, float, float]:
    """Per-leg greeks in *price space* (delta, gamma, vega, theta_per_day)."""
    call_delta = _bachelier_call_delta_price(
        forward=forward, strike=leg.strike, vol_normal=vol_normal, tte=tte
    )
    call_gamma = _bachelier_call_gamma_price(
        forward=forward, strike=leg.strike, vol_normal=vol_normal, tte=tte
    )
    call_vega = _bachelier_call_vega_price(
        forward=forward, strike=leg.strike, vol_normal=vol_normal, tte=tte
    )
    call_theta = _bachelier_call_theta_price_per_day(
        forward=forward, strike=leg.strike, vol_normal=vol_normal, tte=tte
    )

    if leg.right == "C":
        delta = call_delta
        # Put-call parity: gamma, vega, theta same for call/put
        gamma = call_gamma
        vega = call_vega
        theta = call_theta
    else:
        # Put delta = call_delta - 1
        delta = call_delta - 1.0
        gamma = call_gamma
        vega = call_vega
        theta = call_theta

    qty = float(leg.quantity)
    return qty * delta, qty * gamma, qty * vega, qty * theta


def compute_greeks(
    *,
    legs: Sequence[OptionLeg],
    smile,
    as_of_tte: float,
) -> CandidateGreeks:
    """Aggregate entry + aged Greeks for a candidate.

    ``smile`` must expose ``params.forward_price`` and ``normal_vol(strikes)``.
    ``as_of_tte`` is the time-to-expiry of the front leg in years.
    """
    forward = float(smile.params.forward_price)
    vols = np.asarray(
        smile.normal_vol(
            np.array([leg.strike for leg in legs]),
            strike_space="price",
            vol_units="price",
        ),
        dtype=float,
    )
    vols = np.maximum(vols, 1e-8)

    delta_price = 0.0
    gamma_price = 0.0
    vega_price = 0.0
    theta_per_day = 0.0
    for leg, vol in zip(legs, vols):
        d, g, v, t = _leg_greeks_price(
            leg=leg, forward=forward, vol_normal=float(vol), tte=as_of_tte
        )
        delta_price += d
        gamma_price += g
        vega_price += v
        theta_per_day += t

    # Convert price-space Greeks to "DV01"-style:
    # 1bp move in rate = -1bp in price = -0.01 → DV01 = -delta_price * 0.01
    # (in price units; we keep sign convention as DV01 = price-delta * 0.01)
    delta_dv01 = -delta_price * 0.01
    # Gamma in (price)² units → per bp² = gamma_price * 0.0001
    gamma_per_bp_squared = gamma_price * 1e-4
    # Vega per vol-point: 1 vol-pt of normal vol ≈ 0.01 in price units
    vega_per_volpoint = vega_price * 0.01

    # Aged Greeks
    def _at(tte_off):
        tte_aged = max(as_of_tte - tte_off, 1e-6)
        v_aged = 0.0
        t_aged = 0.0
        for leg, vol in zip(legs, vols):
            v_call = _bachelier_call_vega_price(
                forward=forward, strike=leg.strike, vol_normal=float(vol), tte=tte_aged
            )
            t_call = _bachelier_call_theta_price_per_day(
                forward=forward, strike=leg.strike, vol_normal=float(vol), tte=tte_aged
            )
            v_aged += float(leg.quantity) * v_call
            t_aged += float(leg.quantity) * t_call
        return v_aged * 0.01, t_aged

    vega_1m, theta_1m = _at(30.0 / 365.0)
    _, theta_3m = _at(90.0 / 365.0)

    return CandidateGreeks(
        delta_dv01=float(delta_dv01),
        gamma_per_bp_squared=float(gamma_per_bp_squared),
        vega_per_volpoint=float(vega_per_volpoint),
        theta_per_day=float(theta_per_day),
        vega_aged_1m=float(vega_1m),
        theta_aged_1m=float(theta_1m),
        theta_aged_3m=float(theta_3m),
    )
