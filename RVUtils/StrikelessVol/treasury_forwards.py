"""Forward par rates built off the Treasury curve.

H2's discriminator. If the ultra-long forward slope inverts because a rising
term funding premium drags long SWAP rates down relative to bonds, then the
same slope built from TREASURY forwards should not show the effect: there is no
swap leg to drag. If instead a single balance-sheet regime cheapens bonds versus
swaps AND removes the receiving bid, both curves move together.

The Treasury curve arrives as a fitted PAR curve (``CashSpline.yield_at``), so
it is bootstrapped to discount factors before any forward is taken.
"""
from __future__ import annotations

from typing import Dict, Iterable

import numpy as np
import pandas as pd

__all__ = ["par_to_discount", "forward_par_rate", "treasury_forward_panel"]


def par_to_discount(ttms, par_yields, *, freq: int = 2) -> np.ndarray:
    """Bootstrap a par curve to discount factors on the same (sorted) grid.

    ``ttms`` must be sorted ascending and evenly spaced at ``1/freq`` years -- a
    par bond's coupon dates have to land on grid points for the bootstrap to be
    exact rather than interpolated.
    """
    t = np.asarray(ttms, dtype=float)
    c = np.asarray(par_yields, dtype=float)
    if t.ndim != 1 or np.any(np.diff(t) <= 0):
        raise ValueError("ttms must be strictly increasing")
    if c.shape != t.shape:
        raise ValueError("par_yields must match ttms")

    dfs = np.empty_like(t)
    annuity = 0.0
    for i, (ti, ci) in enumerate(zip(t, c)):
        coupon = ci / freq
        dfs[i] = (1.0 - coupon * annuity) / (1.0 + coupon)
        annuity += dfs[i]
    return dfs


def forward_par_rate(ttms, dfs, *, fwd_years: float, tail_years: float,
                     freq: int = 2) -> float:
    """Par rate of a swap starting in ``fwd_years`` running ``tail_years``."""
    t = np.asarray(ttms, dtype=float)
    d = np.asarray(dfs, dtype=float)
    start, end = float(fwd_years), float(fwd_years + tail_years)
    grid = np.arange(start + 1.0 / freq, end + 1e-9, 1.0 / freq)
    d_start = float(np.interp(start, t, d))
    d_end = float(np.interp(end, t, d))
    annuity = float(np.sum(np.interp(grid, t, d)) / freq)
    if annuity <= 0.0:
        return float("nan")
    return (d_start - d_end) / annuity


def treasury_forward_panel(spline_by_date: Dict, legs: Iterable) -> pd.DataFrame:
    """Same shape as ``panels.forward_rate_panel`` so regressions are unchanged."""
    legs = list(legs)
    grid = np.arange(0.5, 40.5, 0.5)
    rows = []
    for ts in sorted(spline_by_date):
        spline = spline_by_date[ts]
        if spline is None:
            continue
        try:
            par = np.asarray([float(spline.yield_at(x)) for x in grid], dtype=float)
            if np.nanmax(par) > 1.0:  # spline may quote percent
                par = par / 100.0
            dfs = par_to_discount(grid, par)
            rec = {
                leg.label: forward_par_rate(
                    grid, dfs, fwd_years=leg.fwd_years, tail_years=leg.tail_years
                )
                for leg in legs
            }
        except Exception:
            continue
        rec["date"] = pd.Timestamp(ts)
        rows.append(rec)
    if not rows:
        return pd.DataFrame(columns=[l.label for l in legs])
    return pd.DataFrame(rows).set_index("date").sort_index()
