# RVUtils/StrikelessVol/report.py
"""Distribution diagnostics -- and a measured warning about which ones mean anything.

**Read this before ranking anything on ``distribution_stats`` or ``vol_beta``.**

This module was written on the premise that a long-convexity position and its
short-convexity mirror can print the same Sharpe but must differ in the SHAPE
of their daily P&L (skew near zero against the short-vol signature of ~-3) and
in the sign of their response to changes in implied vol. **Both propositions
were tested on real curves in Task 13 and both are false for a forward-slope
package**, which is the instrument this package studies:

* Daily P&L skew does not separate them. Measured on USD 10Y10Y/20Y10Y over
  2017-2026: the long book prints +0.087 and its exact mirror -0.082. Both
  clear ``> -1``. A DV01-matched **zero-convexity** twin
  (``replication.ZeroConvexityPricer``: constant maturity, no gamma, no carry)
  prints +0.288 -- a BETTER skew than the convex book, on zero gamma.
* The vol correlation is not a property of the position at all. It is the
  market's own slope/vol comovement, which anything carrying this DV01
  inherits: ``corr(-d spread, d vol)`` computed straight from the curves with
  no position in the calculation is +0.6129, and the zero-convexity twin's
  ``vol_corr`` is +0.6129 to four decimals.

The reason is that a DV01-neutral forward-slope package is delta-hedged
against the LEVEL of rates but carries a full FIRST-ORDER exposure to the
SLOPE, and that linear term is ~96% of daily P&L variance. Every statistic
computed on the raw P&L is therefore dominated by it and reads the same way
for any book carrying the same DV01, convex or not.

``distribution_stats`` and ``vol_beta`` remain correct and useful as
DESCRIPTIONS of a P&L series -- they are used throughout the study for exactly
that. They are not evidence of convexity. For that use :func:`residual_stats`,
which removes the shared linear term first, and read its docstring for the
conditions under which even it is usable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import TRADING_DAYS

__all__ = ["distribution_stats", "mirror_split", "residual_stats", "vol_beta"]


def distribution_stats(daily_pnl: pd.Series) -> dict:
    """Sharpe, skew, excess kurtosis, max drawdown and daily vol of a P&L series.

    ``daily_pnl`` is a series of DOLLAR P&L per day, not returns: the
    "Sharpe" reported here is therefore mean/sd of dollars, annualised by
    ``sqrt(TRADING_DAYS)``. That is scale-free in the package's DV01 (both
    numerator and denominator are linear in it) and so is directly
    comparable to a published Sharpe for the same strategy, but it is not a
    return on capital and must not be read as one.

    ``max_drawdown`` is measured on the CUMULATIVE dollar path (peak-to-
    trough of ``cumsum``), so it is negative and in dollars.
    """
    r = pd.Series(daily_pnl).astype(float).dropna()
    if r.empty:
        # Same key set as the populated return, so a caller indexing ["n"]
        # does not get a KeyError only on the empty path.
        out = {k: float("nan") for k in
               ("sharpe_annualised", "skew", "kurtosis", "max_drawdown", "daily_pnl_vol")}
        out["n"] = 0
        return out
    sd = float(r.std(ddof=1))
    cum = r.cumsum()
    dd = float((cum - cum.cummax()).min())
    return {
        "sharpe_annualised": float(r.mean() / sd * np.sqrt(TRADING_DAYS)) if sd else float("nan"),
        "skew": float(r.skew()),
        "kurtosis": float(r.kurtosis()),
        "max_drawdown": dd,
        "daily_pnl_vol": sd,
        "n": int(len(r)),
    }


RESIDUAL_DEGENERATE_FRAC: float = 1e-6

# Operational cuts on the linear fit, calibrated in Task 13 rather than chosen.
# The residual is a convexity read only to the extent the linear model actually
# fits, and the calibration found the boundary is NOT where ordinary statistical
# habits put it: R^2 = 0.882 is a high R^2 by most standards and is exactly
# where the sign became a coin flip (a flattener printed resid_skew -0.4451,
# the wrong sign for a long-convexity book). The two study-pair runs sat at
# 0.956/0.958 and behaved perfectly. There is no data between 0.882 and 0.956,
# so these cuts are drawn conservatively inside that gap.
RESID_R2_SIGN_USABLE: float = 0.93   # below this, do not trust the SIGN
RESID_R2_FLOOR: float = 0.90         # below this, do not read the number at all


def residual_stats(daily_pnl: pd.Series, spread_changes: pd.Series) -> dict:
    """Shape of the P&L once its LINEAR exposure to the slope is removed.

    This exists because the raw distributional statistics were measured and
    found **non-discriminating** on this instrument (Task 13). A DV01-neutral
    forward-slope package is delta-hedged against the LEVEL of rates but
    carries a full first-order exposure to the SLOPE, and on real USD curves
    that linear term is ~96% of daily P&L variance. Raw skew is therefore
    essentially the skew of ``d(spread)``, which is a property of the market
    and reads the same way round for a long-convexity book, its
    short-convexity mirror, and a zero-convexity constant-maturity twin
    (:class:`replication.ZeroConvexityPricer`) that has no gamma at all. All
    three clear ``skew > -1``.

    Regressing the P&L on ``d(spread)`` and looking at what is left removes
    exactly the term all three share. What remains for a convex book is
    ``~0.5*Gamma*move**2``, which is strictly signed -- positive for long
    convexity, negative for short -- so ``resid_skew`` is expected to be
    strongly positive for the long package, its mirror image for the
    steepener, and ~0 for anything without gamma.

    ``spread_changes`` must be the change in the pair's OWN slope (a placebo
    pair is regressed on the placebo's slope, not on the study pair's).

    **Use it paired, and only where the fit is good.** Two calibrated
    conditions, both from Task 13:

    * Prefer :func:`mirror_split` -- the difference against the same book run
      with the opposite ``sign`` -- over reading ``resid_skew`` alone. The
      quadratic term is strictly signed but MODEL MISFIT IS NOT REMOVED by the
      regression, and unpaired the two are indistinguishable. Differencing
      against the mirror cancels the misfit, which is common to both.
    * Respect :data:`RESID_R2_SIGN_USABLE` (0.93) and :data:`RESID_R2_FLOOR`
      (0.90). At R^2 0.882 -- a high R^2 by ordinary standards -- the sign was
      measured to be unreliable.

    **``resid_skew``'s magnitude is not a convexity scale.** It is closer to a
    fit-quality scale: the study pair and its mirror print ~2.5-2.7 at R^2
    ~0.956 while the placebos print 0.45-0.78 at R^2 0.86-0.88, and the
    ordering there tracks how well the linear model fits, not how much gamma
    each book holds. Rank on the paired sign, never on ``|resid_skew|``.

    **Scope note.** In this study ``daily_pnl`` is the ledger's ``total``,
    which includes carry and transaction costs, whereas the ``0.5*Gamma*x**2``
    argument concerns the price-move buckets only. Carry is slow-moving and
    largely absorbed into the intercept, and the cost spikes are few (60 in
    2,391 days) and negative -- so they bias ``resid_skew`` DOWNWARD if at all,
    against the long-convexity reading rather than for it. It is a purity point
    rather than a defect, but a caller wanting the cleanest read can pass
    ``ledger["mtm"] + ledger["harvest"]`` instead.

    ``resid_skew``/``resid_kurtosis`` are NaN when the fit is degenerate --
    residual sd below ``RESIDUAL_DEGENERATE_FRAC`` of the P&L's own sd, i.e.
    R^2 indistinguishable from 1. That is not a failure: it is the correct
    answer for a book whose P&L IS the linear term (the zero-convexity twin
    has R^2 = 1 by construction), and returning a skew computed on float noise
    there would invent a number.
    """
    df = pd.concat(
        [pd.Series(daily_pnl).astype(float).rename("p"),
         pd.Series(spread_changes).astype(float).rename("s")],
        axis=1,
    ).dropna()
    nan = float("nan")
    if len(df) < 5 or float(df["s"].std(ddof=1)) == 0.0:
        return {"beta": nan, "r2": nan, "resid_skew": nan, "resid_kurtosis": nan,
                "resid_sd": nan, "pnl_sd": nan, "n": int(len(df))}
    beta, alpha = np.polyfit(df["s"], df["p"], 1)
    resid = df["p"] - (beta * df["s"] + alpha)
    pnl_sd = float(df["p"].std(ddof=1))
    resid_sd = float(resid.std(ddof=1))
    degenerate = pnl_sd == 0.0 or resid_sd < RESIDUAL_DEGENERATE_FRAC * pnl_sd
    return {
        "beta": float(beta),
        "r2": float(df["p"].corr(df["s"]) ** 2),
        "resid_skew": nan if degenerate else float(resid.skew()),
        "resid_kurtosis": nan if degenerate else float(resid.kurtosis()),
        "resid_sd": resid_sd,
        "pnl_sd": pnl_sd,
        "n": int(len(df)),
    }


def mirror_split(
    pnl_long: pd.Series,
    pnl_short: pd.Series,
    spread_changes: pd.Series,
) -> dict:
    """The paired difference ``resid_skew(book) - resid_skew(its mirror)``.

    **This, not ``resid_skew`` on its own, is the test statistic.** A book and
    its sign-flipped mirror share the same underlying, the same path, the same
    linear slope exposure up to sign, and -- critically -- the same model
    misfit. Differencing them cancels everything that is not strictly signed in
    the position, which is exactly what an unpaired read fails to do.

    Task 13's calibration is the argument for it. Unpaired, ``resid_skew``
    printed the WRONG SIGN (-0.4451) on a placebo flattener whose linear fit
    was poorer (R^2 0.882), because the residual there carries model misfit and
    not just gamma. Paired, the misfit is common to both legs of the comparison
    and drops out.

    Expected behaviour: ``split ~ 2 * |resid_skew|`` and strongly signed for a
    genuinely convex book (the study pair gives +2.4767 - (-2.6558) = +5.13);
    ``split ~ 0`` for a book whose apparent asymmetry is misfit rather than
    convexity.

    ``usable`` reports whether BOTH fits clear :data:`RESID_R2_SIGN_USABLE`.
    Treat a False as "this comparison does not support a sign", not as a
    negative result.
    """
    lo = residual_stats(pnl_long, spread_changes)
    sh = residual_stats(pnl_short, spread_changes)
    nan = float("nan")
    split = nan
    if np.isfinite(lo["resid_skew"]) and np.isfinite(sh["resid_skew"]):
        split = float(lo["resid_skew"] - sh["resid_skew"])
    r2s = [lo["r2"], sh["r2"]]
    finite_r2 = [r for r in r2s if np.isfinite(r)]
    return {
        "split": split,
        "resid_skew_long": lo["resid_skew"],
        "resid_skew_short": sh["resid_skew"],
        "r2_long": lo["r2"],
        "r2_short": sh["r2"],
        "min_r2": min(finite_r2) if finite_r2 else nan,
        "usable": bool(finite_r2) and min(finite_r2) >= RESID_R2_SIGN_USABLE,
        "readable": bool(finite_r2) and min(finite_r2) >= RESID_R2_FLOOR,
        "n": min(lo["n"], sh["n"]),
    }


def vol_beta(pnl: pd.Series, vol_changes: pd.Series) -> dict:
    """Regression of P&L on changes in implied vol -- the long-vol fingerprint.

    Aligns the two series on their shared index (so a monthly P&L series and
    a monthly change-in-implied-vol series need only agree on period ends)
    and drops any period either side is missing. A long-convexity position
    must show ``corr > 0``: vol going up is the environment it is paid in.
    """
    df = pd.concat(
        [pd.Series(pnl).astype(float).rename("p"),
         pd.Series(vol_changes).astype(float).rename("v")],
        axis=1,
    ).dropna()
    if len(df) < 5:
        return {"corr": float("nan"), "beta": float("nan"), "n": int(len(df))}
    beta = float(np.polyfit(df["v"], df["p"], 1)[0])
    return {"corr": float(df["p"].corr(df["v"])), "beta": beta, "n": int(len(df))}
