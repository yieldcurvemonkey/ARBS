# RVUtils/StrikelessVol/report.py
"""Distribution diagnostics. The distribution is the result, not the Sharpe.

A long-convexity position and a short-convexity one can print the same Sharpe
over a decade; what separates them is the SHAPE of the daily P&L -- skew near
zero (many small bleeds, occasional large gains) against the short-vol
signature of skew around -3 -- and the sign of the position's response to
changes in implied vol. Those are the numbers this module exists to produce,
and they are what the Task 13 gate is decided on.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from RVUtils.StrikelessVol.conventions import TRADING_DAYS

__all__ = ["distribution_stats", "residual_stats", "vol_beta"]


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
