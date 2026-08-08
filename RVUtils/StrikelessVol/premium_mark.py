"""Premium marks for USD swaption straddles off the cube + a stored curve.

The H16 certified-mark path: model marks (vega x dIV) are for screening only;
anything graded marks on PREMIUMS recomputed from the stored cube and the
same-day stored curve (design doc §Marking policy). Bachelier throughout, via
``RVUtils/ImpliedDistribution/_bachelier`` — the one pricer in this repo that
is NOT QuantLib, so a later QuantLib cross-check is genuinely independent.

Units, pinned by tests: cube vols are ANNUAL normal bp; Bachelier runs in
decimal rate space (sigma = vol_bp / 1e4); premium $ = rate-space price x
annuity($/bp) x 1e4. The annuity is the forward swap's repriced pv01 at the
notional priced.
"""
from __future__ import annotations

import math
from typing import Optional

from RVUtils.ImpliedDistribution._bachelier import (
    bachelier_call_price,
    bachelier_implied_vol,
    bachelier_put_price,
)

__all__ = ["forward_and_annuity", "straddle_premium_usd", "straddle_delta",
           "implied_from_straddle_usd"]


def forward_and_annuity(curve, expiry: str, tenor: str, *, notional: float = 100e6):
    """(forward decimal, annuity $ per bp at ``notional``) for the underlying swap."""
    swap = curve.build_irswap(fwd=expiry, tenor=tenor, notional=notional)
    fwd = float(curve.fair_rate(swap))
    annuity_per_bp = abs(float(curve.pv01(swap)))
    return fwd, annuity_per_bp


def straddle_premium_usd(*, forward: float, strike: float, vol_bp_annual: float,
                         tte_yrs: float, annuity_per_bp: float) -> float:
    """Straddle premium in dollars (discounting carried by the annuity)."""
    sigma = float(vol_bp_annual) / 1e4
    c = bachelier_call_price(strike, forward, sigma, tte_yrs)
    p = bachelier_put_price(strike, forward, sigma, tte_yrs)
    return (c + p) * annuity_per_bp * 1e4


def straddle_delta(*, forward: float, strike: float, vol_bp_annual: float,
                   tte_yrs: float) -> float:
    """d(straddle rate-space price)/dF = 2*Phi(d) - 1, d=(F-K)/(sigma*sqrt(T))."""
    from scipy.stats import norm

    sigma = float(vol_bp_annual) / 1e4
    if tte_yrs < 1e-10 or sigma <= 0:
        return 0.0 if forward == strike else math.copysign(1.0, forward - strike)
    d = (forward - strike) / (sigma * math.sqrt(tte_yrs))
    return 2.0 * float(norm.cdf(d)) - 1.0


def implied_from_straddle_usd(*, premium_usd: float, forward: float, strike: float,
                              tte_yrs: float, annuity_per_bp: float,
                              initial_guess_bp: float = 80.0) -> Optional[float]:
    """Round-trip check: annual normal bp implied back from a straddle premium.

    Straddle = call + put = 2*call - (F-K) by parity, so invert the call leg.
    """
    rate_space = premium_usd / (annuity_per_bp * 1e4)
    # C - P = F - K  =>  C = (straddle + (F - K)) / 2  (exact at ATM too)
    call_price = 0.5 * (rate_space + (forward - strike))
    iv = bachelier_implied_vol(call_price, strike, forward, tte_yrs)
    return None if iv is None or math.isnan(iv) else float(iv) * 1e4
