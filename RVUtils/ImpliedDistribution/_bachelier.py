"""Pure-Python Bachelier (normal model) option pricing.

No QuantLib dependency. Reference implementation:
    SDRUtils/products/_capfloors/pricing.py:67-82
"""

import math

import numpy as np
from scipy.stats import norm


def bachelier_call_price(
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float = 1.0,
) -> float:
    """Bachelier call price in price-space units.

    C = DF * [sigma * sqrt(T) * phi(d) + (F - K) * Phi(d)]
    where d = (F - K) / (sigma * sqrt(T))
    """
    if tte < 1e-10 or vol_normal <= 0:
        return discount * max(forward - strike, 0.0)
    sqrt_t = math.sqrt(tte)
    d = (forward - strike) / (vol_normal * sqrt_t)
    return discount * (vol_normal * sqrt_t * float(norm.pdf(d)) + (forward - strike) * float(norm.cdf(d)))


def bachelier_put_price(
    strike: float,
    forward: float,
    vol_normal: float,
    tte: float,
    discount: float = 1.0,
) -> float:
    """Bachelier put price via put-call parity: P = C - DF*(F-K)."""
    call = bachelier_call_price(strike, forward, vol_normal, tte, discount)
    return call - discount * (forward - strike)


def put_to_call_parity(
    put_price: float,
    strike: float,
    forward: float,
    discount: float = 1.0,
) -> float:
    """Convert put premium to equivalent call premium. C = P + DF*(F - K)."""
    return put_price + discount * (forward - strike)


def bachelier_vega(
    strikes: np.ndarray,
    forward: float,
    vols_normal: np.ndarray,
    tte: float,
    discount: float = 1.0,
) -> np.ndarray:
    """dC/dsigma for the Bachelier model: ``DF * sqrt(T) * phi((F-K)/(sigma*sqrt(T)))``.

    Used to turn a premium tolerance into a vol tolerance. Vega collapses in the wings,
    which is exactly why an implied vol inverted from a tick-quantised deep-OTM premium is
    close to meaningless and must not be fitted as if it were precise.
    """
    sqrt_t = math.sqrt(max(tte, 1e-12))
    d = (forward - np.asarray(strikes, dtype=float)) / (
        np.maximum(np.asarray(vols_normal, dtype=float), 1e-12) * sqrt_t
    )
    return discount * sqrt_t * norm.pdf(d)


def bachelier_implied_vol(
    price: float,
    strike: float,
    forward: float,
    tte: float,
    discount: float = 1.0,
    *,
    lo: float = 1e-6,
    hi: float = 50.0,
    tol: float = 1e-12,
    max_iter: int = 200,
) -> float:
    """Invert a call premium to a Bachelier (normal) volatility, in price-space units/yr.

    Returns NaN when the premium is outside the no-arbitrage band, i.e. below intrinsic
    ``DF*max(F-K, 0)`` or at/above the ``sigma -> inf`` limit. Deep-OTM premiums pinned at
    the settlement tick routinely sit just below intrinsic and must not be silently
    coerced into a vol.

    Bisection rather than Newton: the vega of a far-wing option is tiny, so Newton is
    numerically fragile exactly where this is used, and 200 bisection steps on a bracketed
    monotone function is both cheap and unconditionally safe.
    """
    if not (math.isfinite(price) and math.isfinite(strike) and math.isfinite(forward)):
        return float("nan")
    if tte <= 0.0 or discount <= 0.0:
        return float("nan")
    intrinsic = discount * max(forward - strike, 0.0)
    if price <= intrinsic + 1e-15:
        return float("nan")
    if price >= bachelier_call_price(strike, forward, hi, tte, discount):
        return float("nan")

    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        if bachelier_call_price(strike, forward, mid, tte, discount) < price:
            a = mid
        else:
            b = mid
        if b - a < tol:
            break
    return 0.5 * (a + b)


def bachelier_implied_vols_vectorized(
    prices: np.ndarray,
    strikes: np.ndarray,
    forward: float,
    tte: float,
    discount: float = 1.0,
) -> np.ndarray:
    """Elementwise :func:`bachelier_implied_vol`. NaN marks an uninvertible quote."""
    out = np.empty(len(strikes), dtype=float)
    for i, (p, k) in enumerate(zip(np.asarray(prices, dtype=float),
                                   np.asarray(strikes, dtype=float))):
        out[i] = bachelier_implied_vol(float(p), float(k), forward, tte, discount)
    return out


def bachelier_call_prices_vectorized(
    strikes: np.ndarray,
    forward: float,
    vols_normal: np.ndarray,
    tte: float,
    discount: float = 1.0,
) -> np.ndarray:
    """Vectorized Bachelier call pricing for arrays of strikes and vols."""
    sqrt_t = math.sqrt(max(tte, 1e-12))
    d = (forward - strikes) / (vols_normal * sqrt_t)
    return discount * (vols_normal * sqrt_t * norm.pdf(d) + (forward - strikes) * norm.cdf(d))
