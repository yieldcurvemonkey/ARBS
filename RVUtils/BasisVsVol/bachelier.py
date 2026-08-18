"""Bachelier (normal) option primitives, in rate space.

Every function here works in a single consistent unit system:

    F, K      forward and strike, in **bp**
    sigma     normal volatility, in **bp per sqrt(year)** (i.e. annualised bp vol)
    T         time to expiry, in **years**
    price     undiscounted option premium, in **bp of the underlying rate**

To get money, multiply a bp-space quantity by the position's DV01 in $ per bp.

Why this module exists rather than reusing a vendor pricer: the only non-QuantLib normal-vol
inverter in ARBS lives in ``RVUtils/ImpliedDistribution``; everything else shares the pricer it
would be checking. The basis-vs-vol work needs a pricer that is independent of both the
QuantLib swaption stack and the rateslib bond-future stack, so that a disagreement between them
is detectable rather than absorbed.

Sign convention: ``w = +1`` is a call on the rate (payer swaption / put on a bond future's
price), ``w = -1`` is a put on the rate (receiver swaption / call on price).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

__all__ = [
    "SQRT_2PI",
    "normal_price",
    "normal_atm_price",
    "normal_delta",
    "normal_gamma",
    "normal_vega",
    "normal_theta",
    "implied_normal_vol",
    "vega_per_contract_usd",
    "contracts_for_vega",
]

SQRT_2PI = math.sqrt(2.0 * math.pi)

# Below this the option is treated as intrinsic-only; guards div-by-zero at expiry / zero vol.
_TINY = 1e-12


def _d(F, K, sigma, T):
    v = np.maximum(sigma * np.sqrt(np.maximum(T, 0.0)), _TINY)
    return (F - K) / v, v


def normal_price(F, K, sigma, T, w: int = 1):
    """Undiscounted Bachelier premium, in bp.

    ``price = w*(F-K)*Phi(w*d) + v*phi(d)`` with ``v = sigma*sqrt(T)``.
    """
    F, K, sigma, T = np.asarray(F, float), np.asarray(K, float), np.asarray(sigma, float), np.asarray(T, float)
    d, v = _d(F, K, sigma, T)
    return w * (F - K) * norm.cdf(w * d) + v * norm.pdf(d)


def normal_atm_price(sigma, T):
    """ATM Bachelier premium in bp: ``sigma * sqrt(T / (2*pi))``."""
    return np.asarray(sigma, float) * np.sqrt(np.maximum(np.asarray(T, float), 0.0)) / SQRT_2PI


def normal_delta(F, K, sigma, T, w: int = 1):
    """dPrice/dF, dimensionless. ATM is w*0.5."""
    d, _ = _d(np.asarray(F, float), np.asarray(K, float), np.asarray(sigma, float), np.asarray(T, float))
    return w * norm.cdf(w * d)


def normal_gamma(F, K, sigma, T):
    """d2Price/dF2, in 1/bp. ATM: ``1 / (sigma * sqrt(2*pi*T))``."""
    d, v = _d(np.asarray(F, float), np.asarray(K, float), np.asarray(sigma, float), np.asarray(T, float))
    return norm.pdf(d) / v


def normal_vega(F, K, sigma, T):
    """dPrice/dsigma, in bp of premium per bp of vol. ATM: ``sqrt(T / (2*pi))``."""
    F, K, sigma, T = np.asarray(F, float), np.asarray(K, float), np.asarray(sigma, float), np.asarray(T, float)
    d, _ = _d(F, K, sigma, T)
    return np.sqrt(np.maximum(T, 0.0)) * norm.pdf(d)


def normal_theta(F, K, sigma, T):
    """dPrice/dT, in bp per year (positive; the option loses this as T shrinks).

    ATM: ``sigma / (2 * sqrt(2*pi*T))``.
    """
    F, K, sigma, T = np.asarray(F, float), np.asarray(K, float), np.asarray(sigma, float), np.asarray(T, float)
    d, _ = _d(F, K, sigma, T)
    Ts = np.maximum(T, _TINY)
    return sigma * norm.pdf(d) / (2.0 * np.sqrt(Ts))


def implied_normal_vol(price, F, K, T, w: int = 1, tol: float = 1e-10, max_iter: int = 100,
                       min_time_value: float = 1e-10):
    """Invert :func:`normal_price` for sigma (bp). Scalar only.

    Newton from the ATM closed form, with a bracketed bisection fallback.

    Returns ``nan`` — deliberately, not 0.0 — when the vol is **not identified**: when the price is
    below intrinsic, or when the time value is positive but smaller than ``min_time_value``. Deep
    out-of-the-money premiums underflow to zero long before the vol becomes meaningless, and a
    served 0.0 there is a placeholder masquerading as a measurement. Exact-intrinsic input (zero
    time value) does return 0.0, which is the true answer.
    """
    price, F, K, T = float(price), float(F), float(K), float(T)
    if T <= 0.0 or not np.isfinite(price):
        return float("nan")
    intrinsic = max(w * (F - K), 0.0)
    if price < intrinsic - 1e-9:
        return float("nan")
    time_value = price - intrinsic
    if time_value < min_time_value:
        # sigma == 0 is identified only at the money, where price = sigma*sqrt(T/2pi) is strictly
        # increasing from zero. Away from the money a vanishing time value is consistent with a
        # whole range of small vols, so the honest answer is "not identified".
        if abs(F - K) <= _TINY:
            return 0.0
        return float("nan")

    # ATM closed form is exact at F == K and a good seed elsewhere.
    sigma = max((price - intrinsic) * SQRT_2PI / math.sqrt(T), 1e-6)
    for _ in range(max_iter):
        diff = float(normal_price(F, K, sigma, T, w)) - price
        if abs(diff) < tol:
            return sigma
        v = float(normal_vega(F, K, sigma, T))
        if v < 1e-14:
            break
        step = diff / v
        nxt = sigma - step
        if nxt <= 0.0 or not np.isfinite(nxt):
            break
        sigma = nxt
    else:
        return sigma

    lo, hi = 1e-8, 1.0
    while float(normal_price(F, K, hi, T, w)) < price:
        hi *= 2.0
        if hi > 1e9:
            return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if float(normal_price(F, K, mid, T, w)) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def vega_per_contract_usd(fv01_price_points_per_bp: float, T: float, point_value_usd: float = 1000.0):
    """$ vega per futures-option contract, per 1bp of normal (bp) vol.

    ``fv01`` in the ARBS ustf snapshots is price points per bp of futures yield, so the ATM
    premium in price points is ``sigma_bp * fv01 * sqrt(T/2pi)``. One price point on a $100k-face
    CBOT Treasury future is $1,000.
    """
    return float(fv01_price_points_per_bp) * math.sqrt(max(T, 0.0)) / SQRT_2PI * point_value_usd


def contracts_for_vega(target_vega_usd: float, fv01_price_points_per_bp: float, T: float,
                       point_value_usd: float = 1000.0):
    """Contracts needed to carry ``target_vega_usd`` of $ vega."""
    per = vega_per_contract_usd(fv01_price_points_per_bp, T, point_value_usd)
    if per <= 0.0:
        return float("nan")
    return target_vega_usd / per
