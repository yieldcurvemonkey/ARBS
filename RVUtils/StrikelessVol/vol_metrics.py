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
    "UNDERLYING_RATE",
    "UNDERLYING_SPREAD",
    "realized_vol_bp_day",
    "spread_vol_bp_day",
    "realized_quote",
    "be_over_realized",
    "be_over_implied",
]

#: What a vol series was computed on. Stamped on every series these builders
#: return, and REQUIRED by :func:`be_over_realized`, because the two series are
#: both in bp/day and are therefore indistinguishable by units, by dtype and by
#: magnitude on any single observation.
UNDERLYING_RATE: str = "rate"
UNDERLYING_SPREAD: str = "spread"

_UNDERLYING_KEY = "underlying"


def _label(series: pd.Series, underlying: str, window: int) -> pd.Series:
    series.attrs.update({"measure": "realized", _UNDERLYING_KEY: underlying,
                         "window": f"{int(window)}d"})
    return series


def realized_vol_bp_day(rates: pd.Series, window: int = 63) -> pd.Series:
    """Rolling std of daily changes of a DECIMAL rate series, in bp/day.

    The series is stamped ``attrs["underlying"] = "rate"``; see
    :func:`be_over_realized` for why that label is load-bearing rather than
    decorative.
    """
    changes_bp = pd.Series(rates).astype(float).diff() * 10_000.0
    out = changes_bp.rolling(int(window), min_periods=int(window)).std(ddof=1)
    return _label(out, UNDERLYING_RATE, window)


def spread_vol_bp_day(spread_bp: pd.Series, window: int = 63) -> pd.Series:
    """Rolling std of daily changes of a BP spread series, in bp/day.

    Stamped ``attrs["underlying"] = "spread"``.
    """
    out = (
        pd.Series(spread_bp)
        .astype(float)
        .diff()
        .rolling(int(window), min_periods=int(window))
        .std(ddof=1)
    )
    return _label(out, UNDERLYING_SPREAD, window)


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


def be_over_realized(be_bp_day: pd.Series, rv_bp_day: pd.Series, *,
                     denominator: str | None = None) -> pd.Series:
    """<1 means the embedded vol is cheap versus what the market actually does.

    **The denominator must be a RATE vol, and this now REFUSES rather than
    merely documents it.** ``be_bp_day`` comes from
    ``greeks.breakeven_bp_day(roll, gamma)`` where ``gamma`` is
    ``greeks.package_gamma`` -- a second difference over ``rl.Curve.shift(±h)``,
    i.e. a **parallel** bump. So ``BE = sqrt(2|roll|/Γ)`` is denominated in a
    **level** move, and the inequality the strategy is buying is

        ½·Γ·σ_level²  >  |roll|     ⟺     σ_level  >  BE

    Measured on a real 2026-08-03 USD curve to settle it rather than argue it:
    the package's ``package_dv01`` is exactly 0.0 and a 1bp PARALLEL move gives
    ΔPV = +101.88 against ``½Γh²`` = +102.01, with an implied first-order term
    of **0.00** -- the parallel P&L is pure convexity. A 1bp SPREAD move gives
    ~$100,000 of FIRST-order P&L against ~$102 of convexity, a ratio of 980x.
    Spread volatility does not appear in the inequality at all; comparing a
    parallel-move breakeven to a slope vol is a category error, and because
    slope vol is several times smaller (measured 4.4x on USD 2025-2026) it
    **systematically overstates richness**.

    **Why a label and not a docstring.** Both series are in bp/day, both are
    ``float64``, and on any single observation they are indistinguishable. The
    module docstring and the Task 10 brief have said "must never be swapped"
    since Task 10, and a call site swapped them anyway -- by hand-rolling
    ``spread_bp.diff().rolling(63).std()`` and never calling either builder, so
    no amount of prose on the builders could have intervened. The builders now
    stamp ``attrs["underlying"]`` and this function requires it:

    * an **unlabelled** denominator raises -- that is the failure mode that
      actually happened, and the only way to satisfy it is to go through
      :func:`realized_vol_bp_day` or :func:`spread_vol_bp_day`;
    * a **spread-labelled** denominator raises unless the caller states
      ``denominator="spread"``, which makes the deliberate diagnostic
      (``be_over_spread_vol``) explicit at the call site and the accident
      impossible;
    * a stated ``denominator`` that disagrees with the label raises.

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
    label = (getattr(rv_bp_day, "attrs", None) or {}).get(_UNDERLYING_KEY)
    if label is None:
        raise ValueError(
            "be_over_realized's denominator carries no `underlying` label, so "
            "it cannot be checked to be a RATE vol. Build it with "
            "vol_metrics.realized_vol_bp_day(long_rate) -- or, for the "
            "deliberate slope diagnostic, vol_metrics.spread_vol_bp_day(spread) "
            "with denominator='spread'. A hand-rolled "
            "`series.diff().rolling(n).std()` is exactly the call that put a "
            "SPREAD vol under this ratio and inverted the valuation state in "
            "all four markets; the label exists because the two series are both "
            "bp/day and are otherwise indistinguishable."
        )
    if denominator is None:
        if label != UNDERLYING_RATE:
            raise ValueError(
                f"be_over_realized's denominator is a {label!r} vol. BE is a "
                "PARALLEL-move breakeven (package_gamma is a second difference "
                "over Curve.shift), so the comparator is the LEVEL vol; a slope "
                "vol is a category error and, being several times smaller, "
                "systematically overstates richness. Pass "
                "realized_vol_bp_day(long_rate), or state "
                f"denominator={label!r} if the slope ratio is what you want."
            )
    elif denominator != label:
        raise ValueError(
            f"be_over_realized was told denominator={denominator!r} but the "
            f"series is labelled {label!r}. One of the two is wrong, and this "
            "function will not guess which."
        )
    return _ratio(be_bp_day, rv_bp_day)


def be_over_implied(be_bp_day: pd.Series, iv_bp_day: pd.Series) -> pd.Series:
    """<1 means the embedded vol is cheap versus the swaption surface."""
    return _ratio(be_bp_day, iv_bp_day)
