"""Closed-form pricing of listed SR3 structures over smeared atoms.

The price at option expiry is atoms + a Gaussian smear (the unresolved-meeting
expectation variance plus diffusion), so every European payoff prices as a
probability-weighted sum of Bachelier pieces. Premiums are in **bp of price**
(the quotes-panel unit); strikes are given in RATE percent, with the usual SR3
mapping ``K_rate = 100 - K_price``:

* a **put on price** is a payer: pays ``(R - K_rate)+``
* a **call on price** is a receiver: pays ``(K_rate - R)+``
"""
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np
from scipy.stats import norm

__all__ = ["price_option", "price_options_vector", "digital_prob",
           "price_vertical", "event_std_bp"]


def _bachelier_call_on_rate(mu: np.ndarray, k: float, sigma: float) -> np.ndarray:
    """E[(R - k)+] with R ~ N(mu, sigma^2), elementwise in mu (units: percent)."""
    d = mu - k
    if sigma <= 1e-12:
        return np.maximum(d, 0.0)
    z = d / sigma
    return d * norm.cdf(z) + sigma * norm.pdf(z)


def price_option(
    rates: np.ndarray,
    probs: np.ndarray,
    right: str,
    strike_rate: float,
    *,
    smear_bp: float = 0.0,
) -> float:
    """Premium in bp of price for a listed option under (atoms, smear)."""
    sigma = smear_bp / 100.0
    if right == "P":                      # put on price = call on rate
        vals = _bachelier_call_on_rate(rates, strike_rate, sigma)
    elif right == "C":                    # call on price = put on rate
        vals = _bachelier_call_on_rate(rates, strike_rate, sigma) - (rates - strike_rate)
    else:
        raise ValueError(f"right must be C or P, got {right!r}")
    return float(np.dot(probs, vals)) * 100.0


def price_options_vector(
    rates: np.ndarray,
    probs: np.ndarray,
    rights: np.ndarray,
    strikes_rate: np.ndarray,
    *,
    smear_bp: float = 0.0,
) -> np.ndarray:
    """Vectorised premiums (bp of price) for many quotes at once.

    Broadcasting over (atoms x quotes); identical values to ``price_option``.
    """
    sigma = smear_bp / 100.0
    mu = rates[:, None]                                    # (A, 1)
    k = np.asarray(strikes_rate, dtype=float)[None, :]     # (1, Q)
    d = mu - k
    if sigma <= 1e-12:
        call_on_rate = np.maximum(d, 0.0)
    else:
        z = d / sigma
        call_on_rate = d * norm.cdf(z) + sigma * norm.pdf(z)
    put_side = probs @ call_on_rate                        # (Q,) put-on-price
    call_side = put_side - (probs @ d)                     # parity
    is_put = np.asarray(rights) == "P"
    return np.where(is_put, put_side, call_side) * 100.0


def digital_prob(
    rates: np.ndarray,
    probs: np.ndarray,
    strike_rate: float,
    *,
    smear_bp: float = 0.0,
) -> float:
    """P(rate at expiry >= strike) under (atoms, smear)."""
    sigma = smear_bp / 100.0
    if sigma <= 1e-12:
        return float(probs[rates >= strike_rate].sum())
    return float(np.dot(probs, norm.cdf((rates - strike_rate) / sigma)))


def price_vertical(
    rates: np.ndarray,
    probs: np.ndarray,
    right: str,
    k_lo_rate: float,
    k_hi_rate: float,
    *,
    smear_bp: float = 0.0,
) -> float:
    """Premium of the (k_lo, k_hi) vertical, in bp of price, long the k_lo leg.

    For puts-on-price (payers) the natural digital normalisation is
    ``[P(k_hi_prem) - P(k_lo_prem)] / width`` — handled by the caller; this
    returns the plain premium difference of the two legs.
    """
    a = price_option(rates, probs, right, k_lo_rate, smear_bp=smear_bp)
    b = price_option(rates, probs, right, k_hi_rate, smear_bp=smear_bp)
    return a - b


def event_std_bp(rates: np.ndarray, probs: np.ndarray) -> float:
    """Std of the atom distribution in bp (smear excluded)."""
    mu = float(np.dot(rates, probs))
    var = float(np.dot(probs, (rates - mu) ** 2))
    return float(np.sqrt(max(var, 0.0))) * 100.0
