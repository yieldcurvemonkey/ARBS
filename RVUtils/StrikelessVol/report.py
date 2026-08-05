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
that. They are not evidence of convexity.

**Nor is anything else in this module.** :func:`residual_stats` was built as
the replacement and then failed its own calibration (1-for-2 on the cases where
the truth was independently known), and :func:`mirror_split` was built to
rescue it and turned out to be an arithmetic x2 rescaling. Both are kept as a
committed record of that, with their limits in their docstrings, and both are
report-only.

**To ask whether a package is convex, call** :func:`greeks.package_gamma` --
it answers directly, from a bump-and-reprice, and it settled the case these
statistics could not in a single call. **To ask whether that convexity was
realised, read the ledger's ``harvest`` bucket.**
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

# Reporting thresholds on the linear fit. **These are NOT a validated gate.**
#
# They were drawn after the fact, inside the gap between the only two R^2
# regimes observed: 0.882, where the sign came out wrong, and 0.956, where it
# came out right. That is a 1-vs-1 in-sample separator fitted to the very rows
# that failed, never tested on a case it was not drawn from -- and in this
# sample Gamma is perfectly confounded with R^2 (the high-R^2 rows are also the
# 10x-Gamma rows), so the cut cannot even be attributed to fit quality rather
# than signal strength. Treat them as a reminder to look at min_r2, not as a
# criterion anything may be decided on.
RESID_R2_SIGN_USABLE: float = 0.93   # below this the sign is certainly not readable
RESID_R2_FLOOR: float = 0.90         # below this do not report the number at all


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
    convexity, negative for short. Measured on the study pair that is what
    happens (+2.4767 long, -2.6558 mirror), and the zero-gamma twin correctly
    returns NaN.

    **It does not follow that the number tracks gamma in general.** Two placebo
    pairs with identical measured gamma (+20.31 and +20.34 $/bp^2, a tenth of
    the study pair's) printed +0.7835 and -0.4451 -- opposite signs for the
    same convexity. Whatever this statistic reads at low signal, it is not
    gamma. See :func:`mirror_split` for the domain where it can be trusted.

    ``spread_changes`` must be the change in the pair's OWN slope (a placebo
    pair is regressed on the placebo's slope, not on the study pair's).

    **REPORT IT; DO NOT ACT ON IT.** After calibration this statistic may be
    computed and shown alongside ``min_r2`` and the package's measured gamma.
    It may **not** serve as a gate, a ranking key, evidence for or against
    convexity, or a tiebreaker. The reasons are cumulative, and each is
    measured rather than argued:

    1. It is **1-for-2** on the only configurations where the truth is known
       independently: two placebo pairs with the same gamma, one right sign and
       one wrong.
    2. :func:`mirror_split` **adds nothing** -- ``simulate`` is exactly
       antisymmetric in ``sign``, so pairing is a x2 rescaling that cannot
       change a sign. The study pair and its mirror are one observation.
    3. The R^2 cuts are a **1-vs-1 in-sample separator** drawn because those
       rows failed, never tested out of sample, with gamma confounded with
       R^2 across the whole sample.
    4. It is **dominated** by :func:`greeks.package_gamma`, which answers the
       convexity question directly and settled the placebo case in one call,
       and by the ledger's ``harvest`` bucket, which answers whether that
       convexity was realised. Both are cheaper and neither can be fooled by
       the residual's shape.

    Its value is as a committed record of a measured defect in the original
    distributional criteria (see this module's docstring), not as a tool.

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
    """``resid_skew(book) - resid_skew(its mirror)``. **A x2 rescaling. Adds nothing.**

    Kept only as committed documentation of a measured dead end. It was
    introduced on the theory that a book and its sign-flipped mirror share
    their model misfit, so differencing would cancel the contamination that
    made the unpaired ``resid_skew`` print a wrong sign. **That theory is
    false, and the reason is structural rather than empirical.**

    ``simulate`` is EXACTLY ANTISYMMETRIC in ``sign``. Per-unit ``dv01`` is
    sign-invariant (numerator and denominator both flip); the notionals flip;
    ``pv`` and ``theta`` are linear in the notionals; the trigger reads the
    sign-independent constant-maturity rate, so the two runs hedge on the same
    dates; and ``cost`` is a magnitude fee. Every P&L bucket therefore negates
    exactly and only the cost ledger is shared:

        resid_short = -resid_long - resid_cost
        split       = resid_long - resid_short  ~=  2 * resid_long

    So the "mirror" is not a second book carrying a common contaminant -- it
    is the arithmetic negation of the first, and there is nothing to cancel.
    Measured: on a synthetic engine-mirror with no costs the ratio
    ``split / resid_long`` is **2.000000** exactly; with costs 2.12; on the
    three real 2017-2026 runs 2.072 / 2.140 / 1.864. Pinned by
    ``test_the_mirror_is_the_negation_so_pairing_only_rescales``.

    A monotone positive rescaling cannot change a sign, so pairing **cannot
    rescue a wrong one** -- and indeed did not: the placebo that printed
    -0.4451 unpaired printed -0.8296 paired. The study pair and its mirror are
    ONE observation, not two.

    Use :func:`greeks.package_gamma` to ask whether a package is convex -- it
    answers directly, and it settled the placebo case in a single call. Use
    the ledger's ``harvest`` bucket to ask whether that convexity was actually
    realised. Neither goes through this function.
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
