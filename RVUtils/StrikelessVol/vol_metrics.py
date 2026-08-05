"""Realized vol, implied vol and the valuation ratio, all in bp/day.

Which underlying each vol is computed on is load-bearing:

* ``realized_vol_bp_day`` runs on the **longer leg's forward par rate** -- the
  rate the rebalance trigger watches, and the one the breakeven is compared to.
* ``spread_vol_bp_day`` runs on the **package spread** -- the sizing base
  (~1.65bp/day for USD 10y10y/20y10y in the 2026 sample).

They are different numbers. Swapping them silently changes what the system is
sized off, which the spec forbids.
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
    """<1 means the embedded vol is cheap versus what the market actually does."""
    return _ratio(be_bp_day, rv_bp_day)


def be_over_implied(be_bp_day: pd.Series, iv_bp_day: pd.Series) -> pd.Series:
    """<1 means the embedded vol is cheap versus the swaption surface."""
    return _ratio(be_bp_day, iv_bp_day)
