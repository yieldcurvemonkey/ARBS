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

__all__ = ["distribution_stats", "vol_beta"]


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
        return {k: float("nan") for k in
                ("sharpe_annualised", "skew", "kurtosis", "max_drawdown", "daily_pnl_vol")}
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
        return {"corr": float("nan"), "beta": float("nan"), "n": len(df)}
    beta = float(np.polyfit(df["v"], df["p"], 1)[0])
    return {"corr": float(df["p"].corr(df["v"])), "beta": beta, "n": int(len(df))}
