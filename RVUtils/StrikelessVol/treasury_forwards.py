"""Forward par rates built off the Treasury curve.

H2's discriminator. If the ultra-long forward slope inverts because a rising
term funding premium drags long SWAP rates down relative to bonds, then the
same slope built from TREASURY forwards should not show the effect: there is no
swap leg to drag. If instead a single balance-sheet regime cheapens bonds versus
swaps AND removes the receiving bid, both curves move together.

The Treasury curve arrives as a fitted PAR curve (``CashSpline.yield_at``), so
it is bootstrapped to discount factors before any forward is taken.

**RMSE guard** (found on real 2021-2026 data, not a defensive measure added
speculatively): a small number of dates produce a ``CashSpline`` whose own
fit RMSE is one to four orders of magnitude above normal -- normal fits on
this window sit at 1.8-3.6bp RMSE (median 2.03bp, 99th percentile 3.62bp,
n=1396), while 13 dates land at 22.5bp to >80,000bp, with a clean, unbroken
gap between the two groups (nothing between ~3.6bp and ~22.5bp). A curve
whose own fit error is tens to tens-of-thousands of bp does not represent the
input bonds at all -- typically because the B-spline's linearised tail (the
config's ``tail_linearize=True`` region beyond its last knot) swings wildly
when a specific long-end CUSIP is thin or briefly mispriced that day,
producing a nonsensical yield near 25-30y (e.g. 0.85% or -8.7% against
neighbouring days' ~3.7-4.7%) that corrupts any forward computed off it,
including the ultra-long legs this module exists to price. 7 of the 13 dates
found are exactly the 7 dates ``panels.umep_panel`` already excludes for an
independently-diagnosed corrupted per-tenor duration read (2026-07-09/10/
13/17/20/24/27, see that function's docstring) -- the same underlying
reference-data corruption breaking two unrelated downstream fits, not a
coincidence. The other 6 (2023-02-10, 02-13, 06-15, 08-01, 11-20, 12-04)
are a previously undiscovered failure mode specific to the spline fit.
``treasury_forward_panel`` skips any spline whose ``rmse`` exceeds
``rmse_guard_bp`` (default 10.0 -- comfortably above the normal group's
99th percentile of 3.62bp and comfortably below the corrupted group's
minimum of 22.5bp) and exposes the excluded count on
``panel.attrs["treasury_excluded_bad_fit_days"]``, mirroring
``umep_panel``'s ``umep_excluded_degenerate_days`` pattern.
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


def treasury_forward_panel(
    spline_by_date: Dict, legs: Iterable, *, rmse_guard_bp: float = 10.0
) -> pd.DataFrame:
    """Same shape as ``panels.forward_rate_panel`` so regressions are unchanged.

    Skips any spline whose ``rmse`` exceeds ``rmse_guard_bp`` -- see the
    module docstring's "RMSE guard" section for why this is a diagnosed
    defect, not a speculative filter, and for the exact dates it excludes.
    The excluded count is exposed on
    ``panel.attrs["treasury_excluded_bad_fit_days"]`` on every return path,
    including the empty-input path, so the exclusion is visible rather than
    silent.
    """
    legs = list(legs)
    grid = np.arange(0.5, 40.5, 0.5)
    rows = []
    n_excluded_bad_fit = 0
    for ts in sorted(spline_by_date):
        spline = spline_by_date[ts]
        if spline is None:
            continue
        rmse = getattr(spline, "rmse", None)
        if rmse is not None and np.isfinite(rmse) and rmse > rmse_guard_bp:
            n_excluded_bad_fit += 1
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
        empty = pd.DataFrame(columns=[l.label for l in legs])
        empty.attrs["treasury_excluded_bad_fit_days"] = n_excluded_bad_fit
        return empty
    panel = pd.DataFrame(rows).set_index("date").sort_index()
    panel.attrs["treasury_excluded_bad_fit_days"] = n_excluded_bad_fit
    return panel
