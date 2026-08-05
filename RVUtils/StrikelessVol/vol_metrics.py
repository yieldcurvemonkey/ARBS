"""Realized vol, implied vol and the valuation ratio, all in bp/day.

Which underlying each vol is computed on is load-bearing:

* ``realized_vol_bp_day`` runs on the **longer leg's forward par rate** -- the
  rate the rebalance trigger watches, and the one the breakeven is compared to.
* ``spread_vol_bp_day`` runs on the **package spread** -- the sizing base
  (measured **~1.32bp/day** for USD 10y10y/20y10y over the live
  2026-01-02..2026-08-03 reproduction sample, ``scripts/sv_reproduce_2026.py``
  -- see "why lower than the research brief's ~1.65bp/day" below; **use the
  measured 1.32, not the brief's 1.65, for sizing**).

They are different numbers. Swapping them silently changes what the system is
sized off, which the spec forbids.

**Why the measured spread vol is lower than the research brief's ~1.65bp/day
figure** (diagnosed in Task 15's review): this package's forward par rates are
re-derived from a log-cubic spline discount curve (GS Quant GSQUANT-RL, knots
at 2-10, 12, 15, 20, 25, 30y) rather than directly quoted. Between 10y and
30y, the spread is therefore a smooth function of five spline node rates, and
per-day idiosyncratic bid/ask-bounce and other microstructure noise is
projected away by the spline fit before it ever reaches this series. Stripping
that iid noise layer off the regressand lowers its variance and its lag-1
autocorrelation while leaving regression betas essentially untouched (noise in
``y`` does not bias a covariance ratio) -- which is also why the same
reproduction shows the changes/levels regressions in ``factors.py`` running a
correspondingly *higher* R-squared and a Durbin-Watson closer to 2 than the
brief's own quote-based figures. Concretely: the implied ratio of the two
regressand standard deviations backed out of the R-squared identity,
``(0.777/sqrt(0.527)) / (0.78/sqrt(0.34)) ~= 0.800``, matches the directly
measured vol ratio ``1.32/1.65 = 0.800`` to three significant figures, and the
brief's stated DW of 2.54 implies lag-1 autocorrelation of about -0.27 (a
quote/microstructure-noise signature) against this series' observed -0.018
(essentially none) -- one mechanism, not three unrelated discrepancies.

Sizing off the measured, spline-smoothed number here (rather than backing out
a quote-based one) is intentional, not an oversight: ``CostSchedule`` already
prices bid/ask separately, so sizing off a noisier, quote-implied vol *and*
charging the cost schedule would double-count the same microstructure effect.
See ``be_over_realized`` for the resulting bias this leaves in the valuation
ratio.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import VolQuote

__all__ = [
    "realized_vol_bp_day",
    "spread_vol_bp_day",
    "realized_quote",
    "be_over_realized",
    "be_over_implied",
]


def realized_vol_bp_day(rates: pd.Series, window: int = 63) -> pd.Series:
    """Rolling std of daily changes of a DECIMAL rate series, in bp/day."""
    changes_bp = pd.Series(rates).astype(float).diff() * 10_000.0
    return changes_bp.rolling(int(window), min_periods=int(window)).std(ddof=1)


def spread_vol_bp_day(spread_bp: pd.Series, window: int = 63) -> pd.Series:
    """Rolling std of daily changes of a BP spread series, in bp/day."""
    return (
        pd.Series(spread_bp)
        .astype(float)
        .diff()
        .rolling(int(window), min_periods=int(window))
        .std(ddof=1)
    )


def realized_quote(rates: pd.Series, window: int, *, underlying: str) -> VolQuote:
    """The latest realized vol, labelled."""
    series = realized_vol_bp_day(rates, window=window).dropna()
    if series.empty:
        raise ValueError("not enough observations for the requested window")
    return VolQuote(
        value_bp_day=float(series.iloc[-1]),
        measure="realized",
        underlying=underlying,
        window=f"{int(window)}d",
    )


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    n = pd.Series(num).astype(float)
    d = pd.Series(den).astype(float)
    return n / d.where(d > 0.0, np.nan)


def be_over_realized(be_bp_day: pd.Series, rv_bp_day: pd.Series) -> pd.Series:
    """<1 means the embedded vol is cheap versus what the market actually does.

    Caveat (see the module docstring's mechanism note): ``rv_bp_day`` --
    whether from ``realized_vol_bp_day`` or ``spread_vol_bp_day`` -- is
    measured on this package's spline-derived forward par rates, which are
    smoother than any series an executing book actually transacts against
    (per-day bid/ask-bounce and other microstructure noise is projected away
    by the discount-curve spline fit before it reaches these rates). Realized
    vol here is therefore a **lower bound** on what an executing book
    experiences, and this ratio is correspondingly **biased upward** -- the
    valuation switch reads "less cheap" than a quote-based realized series
    would show. Do not treat a ratio near 1.0 here as proof the embedded vol
    is fairly priced against a real tradeable series; it may still be cheap
    once quote noise is added back.
    """
    return _ratio(be_bp_day, rv_bp_day)


def be_over_implied(be_bp_day: pd.Series, iv_bp_day: pd.Series) -> pd.Series:
    """<1 means the embedded vol is cheap versus the swaption surface."""
    return _ratio(be_bp_day, iv_bp_day)
