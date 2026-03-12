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
