"""The JPM relative-value framework: curve-implied vol and expected payoff.

From "An option by any other name -- Sourcing cheap convexity in the long end of
the curve" (Younger/Sarkar/Salem, J.P. Morgan, 03-Feb-2017). Two signals, both
computed off the same payoff profile:

**Expected payoff.** Integrate the curve package's payoff profile against the
terminal distribution of rate shifts *implied by swaption pricing*::

    "This is then multiplied with the payoff profile of an aged flattener at
    fixed coupon -- primarily to incorporate carry costs -- to estimate an
    expected return."

    "When the expected payoff on a flattener using an implied distribution
    extracted from swaption pricing is positive, the curve trade is the cheaper
    source of long gamma exposure."

**Breakeven ("curve-implied") volatility.** Solve for the normal vol that makes
the expected payoff exactly zero::

    "we are estimating the level of normal daily volatility in rates that is
    sufficient to offset the carry costs on a given curve trade."

    "The same can also be said when the level of volatility priced into the
    curve is less than that implied by ATMF swaptions."

The note quotes both in **bp/day**, so that is this module's default unit.

The breakeven-vol signal only needs an ATMF vol to compare against; the
expected-payoff signal needs the full OTM smile. Coverage decides which is the
primary signal -- see ``ConvexityRVConfig.signal_mode``.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

import numpy as np
from scipy import optimize

__all__ = [
    "normal_pdf_weights",
    "expected_payoff",
    "breakeven_vol_bp_per_year",
    "breakeven_vol_bp_per_day",
    "BUSINESS_DAYS_PER_YEAR",
]

#: The note quotes daily vols; this is the annual<->daily bridge used throughout.
BUSINESS_DAYS_PER_YEAR = 252.0


def normal_pdf_weights(shifts: Sequence[float], sigma_bp: float) -> np.ndarray:
    """Discrete probability weights for a zero-mean normal over *shifts*.

    ``sigma_bp`` is the standard deviation of the TERMINAL shift in bp (i.e.
    already scaled to the horizon). The weights are normalised to sum to 1 so
    that the expectation is a proper weighted average even on a truncated grid
    -- the note's Exhibit 3 grid runs only -250..+250 bp.
    """
    x = np.asarray(shifts, dtype=float)
    if sigma_bp <= 0:
        w = np.zeros_like(x)
        w[np.argmin(np.abs(x))] = 1.0
        return w
    dens = np.exp(-0.5 * (x / sigma_bp) ** 2)
    total = dens.sum()
    if total <= 0:
        w = np.zeros_like(x)
        w[np.argmin(np.abs(x))] = 1.0
        return w
    return dens / total


def expected_payoff(
    shifts: Sequence[float],
    payoff: Sequence[float],
    weights: Sequence[float],
) -> float:
    """Probability-weighted payoff. Positive => curve is the cheap gamma."""
    p = np.asarray(payoff, dtype=float)
    w = np.asarray(weights, dtype=float)
    if p.shape != w.shape:
        raise ValueError(f"payoff {p.shape} and weights {w.shape} must align")
    m = np.isfinite(p) & np.isfinite(w)
    if not m.any():
        return float("nan")
    w = w[m]
    total = w.sum()
    if total <= 0:
        return float("nan")
    return float(np.dot(p[m], w / total))


def breakeven_vol_bp_per_year(
    shifts: Sequence[float],
    payoff: Sequence[float],
    *,
    horizon_years: float = 1.0,
    lo: float = 1.0,
    hi: float = 1000.0,
) -> float:
    """Annualised normal vol (bp/yr) at which the package's expected payoff is 0.

    The expected payoff is monotone increasing in sigma for a convex (long-gamma)
    profile with negative carry -- more vol is worth more to a long-gamma
    position -- so a bracketed root solve is well posed. Returns NaN when no
    root exists in [lo, hi], which happens legitimately: a flattener with
    POSITIVE carry has a positive expected payoff at every vol (it never needs
    volatility to break even), and one with a concave profile never breaks even.
    """
    x = np.asarray(shifts, dtype=float)
    p = np.asarray(payoff, dtype=float)
    if not np.isfinite(p).all():
        return float("nan")

    sqrt_t = float(np.sqrt(max(horizon_years, 1e-12)))

    def f(sigma_annual_bp: float) -> float:
        sigma_terminal = float(sigma_annual_bp) * sqrt_t
        return expected_payoff(x, p, normal_pdf_weights(x, sigma_terminal))

    f_lo, f_hi = f(lo), f(hi)
    if not (np.isfinite(f_lo) and np.isfinite(f_hi)):
        return float("nan")
    if f_lo * f_hi > 0:
        # No sign change: either always cheap (positive carry) or never breaks even.
        return float("nan")
    try:
        return float(optimize.brentq(f, lo, hi, xtol=1e-4, maxiter=200))
    except Exception:
        return float("nan")


def breakeven_vol_bp_per_day(
    shifts: Sequence[float],
    payoff: Sequence[float],
    *,
    horizon_years: float = 1.0,
    business_days_per_year: float = BUSINESS_DAYS_PER_YEAR,
    **kw,
) -> float:
    """Breakeven vol in **bp/day** -- the unit the JPM note quotes (Exhibit 4)."""
    annual = breakeven_vol_bp_per_year(shifts, payoff, horizon_years=horizon_years, **kw)
    if not np.isfinite(annual):
        return float("nan")
    return float(annual / np.sqrt(business_days_per_year))
