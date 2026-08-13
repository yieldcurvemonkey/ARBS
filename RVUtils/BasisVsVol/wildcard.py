"""The wildcard option: the delivery option this framework originally left out.

The design document ranked the **switch** option as dominant for ZB/UB and called the wildcard
"small in the electronic era". The dealer literature says the opposite for the modern regime:

    "Pre-crisis, when yields were closer to the 6% level from which CTD conversion factors are
     derived, the switch option was the most important of these delivery options... While the CTD
     bond still switches on occasion in multiple contracts, the switch is essentially valueless...
     Delivery optionality -- in today's yield curve environment, most notably the wildcard option --
     can comprise the majority of the net basis in these contracts."
        -- J.P. Morgan, *Special delivery*, 4 Dec 2019

    "We like buying nets on dips below 0 in both TY and UXY. TY and UXY offer different option
     focus, with TY more exposed to switches in the basket but also having a wild card (after
     futures close) delivery option, while UXY has only wild card option."
        -- BofA, *US Rates Alpha: Buy futures basis = cheap options*, 10 Apr 2025

**Mechanism.** The invoice price is frozen at the futures settle (3pm ET) but notice of intent to
deliver is not due until the evening, and the cash bond keeps trading. A short who is long the
basis holds a *duration-hedged* bond position -- ``1/CF`` face per contract -- but only has to
deliver 1 face. If the bond rallies after the close, the short can declare delivery at the stale
invoice and sell the excess ``1/CF - 1`` "tail" at the higher price. If it sells off, the short
simply does nothing and waits for the next morning. That asymmetry is the option, and its size is
governed by ``1/CF - 1`` -- which is why it is worth most in the low-conversion-factor Ultra
contracts and nearly nothing where CF is close to 1.

**Pricing** follows the backward induction in J.P. Morgan, *Good things come to those who wait*,
18 May 2018. On each delivery day the short exercises only if the tail payoff beats what waiting is
worth -- the remaining option value plus one more day of carry:

    k       = 1/CF - 1                        the tail, per contract
    W_i     = V_{i+1} + g                     value of waiting one more day (g = one day's carry)
    a_i     = W_i / k                         exercise threshold, in price points
    V_i     = k * sigma * phi(a_i/sigma) + Phi(a_i/sigma) * W_i

with post-close price moves normal, ``sigma = sigma_yield_bp * DV01``. The house assumption is
**1bp per 2-hour post-close window, doubled on FOMC days**.

The wildcard's *option* value is ``V_1`` measured against the same recursion run with ``k = 0``
(i.e. pure carry accrual, no tail), so that carry is not double-counted as optionality.

**Why this matters here.** Positive carry raises the exercise threshold and suppresses the option;
negative carry drags it down and makes early delivery attractive. In August 2026 term repo is
3.69% against a CTD coupon of 5%, so carry is strongly positive -- and the vendor sheet marks
almost every deliverable ``LD`` (last delivery). That is the regime in which a switch-only model is
least wrong, and it is measurable rather than assumed: see :func:`wildcard_value`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

__all__ = ["WildcardResult", "wildcard_value", "tail_multiplier", "post_close_sigma_points"]

TICKS_PER_POINT = 32.0


def tail_multiplier(cf: float) -> float:
    """``k = 1/CF - 1`` -- the excess bond face held per contract under a duration hedge."""
    if not np.isfinite(cf) or cf <= 0:
        return float("nan")
    return 1.0 / cf - 1.0


def post_close_sigma_points(sigma_yield_bp: float, dv01_points_per_bp: float) -> float:
    """Post-close price-move sigma in price points, from a yield sigma in bp."""
    return float(sigma_yield_bp) * float(dv01_points_per_bp)


@dataclass(frozen=True)
class WildcardResult:
    value_points: float
    value_ticks: float
    total_with_carry_points: float
    carry_only_points: float
    exercise_thresholds_bp: tuple
    n_days: int
    k: float

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (f"WildcardResult(value={self.value_ticks:.2f} ticks, k={self.k:.4f}, "
                f"n_days={self.n_days})")


def wildcard_value(cf: float, dv01_points_per_bp: float, daily_carry_points: float,
                   n_delivery_days: int, sigma_yield_bp: float = 1.0,
                   fomc_days: tuple = (), fomc_multiplier: float = 2.0) -> WildcardResult:
    """Value the wildcard by backward induction over the delivery days.

    Parameters
    ----------
    cf
        Conversion factor of the CTD. The whole option scales with ``1/cf - 1``.
    dv01_points_per_bp
        CTD DV01 in price points per bp (a ``BPV`` quoted per $1mm divides by 10,000).
    daily_carry_points
        One day of carry to the short who waits, in price points. **Positive carry suppresses the
        option** by raising the exercise threshold; negative carry inflates it.
    n_delivery_days
        Business days on which the wildcard is live (first delivery through last trading day).
    sigma_yield_bp
        Post-close yield move standard deviation over the 2-hour window. House assumption 1.0;
        1.5-2.0 in stressed markets.
    fomc_days
        1-indexed positions within the delivery window that carry an FOMC meeting; their sigma is
        multiplied by ``fomc_multiplier``. Meetings late in the window are worth most, because the
        option still has days to run.
    """
    k = tail_multiplier(cf)
    n = int(n_delivery_days)
    if not np.isfinite(k) or k <= 0 or n <= 0:
        return WildcardResult(float("nan"), float("nan"), float("nan"), float("nan"), (), n, k)

    sig_base = post_close_sigma_points(sigma_yield_bp, dv01_points_per_bp)
    sigmas = [sig_base * (fomc_multiplier if (i + 1) in set(fomc_days) else 1.0) for i in range(n)]

    def _roll(kk: float) -> tuple[float, list]:
        v, thresholds = 0.0, []
        for i in range(n - 1, -1, -1):  # last delivery day backwards
            w = v + daily_carry_points
            s = sigmas[i]
            if kk <= 0 or s <= 0:
                v, a = w, float("inf")
            else:
                a = w / kk
                z = a / s
                v = kk * s * float(norm.pdf(z)) + float(norm.cdf(z)) * w
            thresholds.append(a)
        return v, list(reversed(thresholds))

    v_opt, thr = _roll(k)
    v_carry, _ = _roll(0.0)
    opt = v_opt - v_carry
    thr_bp = tuple(
        (t / dv01_points_per_bp if np.isfinite(t) and dv01_points_per_bp > 0 else float("inf"))
        for t in thr
    )
    return WildcardResult(
        value_points=opt,
        value_ticks=opt * TICKS_PER_POINT,
        total_with_carry_points=v_opt,
        carry_only_points=v_carry,
        exercise_thresholds_bp=thr_bp,
        n_days=n,
        k=k,
    )
