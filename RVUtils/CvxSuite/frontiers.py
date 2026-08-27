"""Per-day cross-sectional frontiers: fit and off-frontier residual, in bp.

C1 module of the CvxSuite (docs/cvxsuite/DESIGN.md section 3).  numpy/pandas
only -- no other imports, no other CvxSuite module.

:func:`daily_xfit` is the generic form of
``RVUtils.INGCurve.screen.daily_frontier`` (same vectorized per-day OLS and the
same NaN/degeneracy refusals), freed from that function's ING couplings
(integer forward years 2..15, residual-on-rolldown only).  Why the per-day
CROSS-SECTIONAL construction is the one that matters here: ING's published
2020-01-15 worked example ("Rates Strategy: Deconstructing the EUR yield
curve") has a value-vs-carry frontier with slope ~ -1.27 and R^2 ~ 0.93; the
v1 walk-forward time-series PC1 residual read R^2 0.03 against the same figure
(the F-ING-v2 fidelity gap, ledger L-0015/L-0035, quoted from
``RVUtils/INGCurve/xsec.py``).  The frontier is a statement about ONE day's
cross-section, refit every day.

Orientations (DESIGN.md section 3, the ING Fig 3/4 conventions):

*   **value-carry frontier**: ``y = residual`` (bp, cheap > 0), ``x =
    rolldown`` (bp per horizon).  ``off_frontier`` > 0 = cheap FOR ITS CARRY
    -- the tradeable 2-D dislocation.
*   **carry-vol frontier**: ``y = rolldown`` (bp), ``x = ATM vol`` (bp/day at
    the ledger boundary, DESIGN section 1).  ``off_frontier`` > 0 = more carry
    than its vol point on the day's line -- rent rich to vol.

Units: bp in, bp out.  Slopes are bp of y per unit of x -- state x's unit at
the call site; this module never converts.

What this is NOT
----------------
NOT a hedge regression and NOT a vol proxy.  A cross-sectional LEVEL fit ranks
points within one day; it says nothing about co-movement.  The measured trap
(reference_fly_not_a_vol_proxy): fly level vs vol R^2 0.88 but WEEKLY-CHANGE
R^2 0.0003-0.089 and partial R^2 <= 0.044 -- a co-trend, not a hedge pair.
Never size a hedge off ``daily_xfit`` slopes; hedge ratios live at the trade
horizon (reference_hedge_ratio_horizon).

Degenerate days are REFUSED, not reported as zero: fewer than ``min_n`` valid
points, zero x-variance (sxx <= 0) or zero y-variance (syy <= 0) yield NaN
slope/intercept/r2 for that day (the n column still reports the count).  A
constant-y day COULD be read as slope 0, but a printed 0.0 is
indistinguishable from a measured flat frontier -- NaN keeps the silent-zero
rule (DESIGN section 1 / the silent-fallback ledger note).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["daily_xfit", "off_frontier"]

_FIT_COLS = ("slope", "intercept", "r2", "n")


def daily_xfit(
    y_bp: pd.DataFrame, x_bp: pd.DataFrame, *, min_n: int = 6
) -> pd.DataFrame:
    """Per-day cross-sectional OLS of ``y`` on ``x``: slope/intercept/r2/n.

    ``y_bp`` and ``x_bp`` are date x point panels; ``x_bp`` is reindexed onto
    ``y_bp``'s index and columns (every ``y`` column must exist in ``x`` --
    ``ValueError`` otherwise; extra ``x`` columns are ignored; dates absent
    from ``x`` fit as empty days -> NaN).  For each date, OLS is fit across
    the points where BOTH y and x are non-NaN; days with fewer than ``min_n``
    such points, or with degenerate variance (sxx <= 0 or syy <= 0), return
    NaN slope/intercept/r2 (``n`` always reports the valid count).

    ``min_n`` must be >= 3: with an intercept, 2 points fit exactly and every
    r2 prints 1.0 -- a meaningless frontier that must not exist silently.

    Vectorized over days (the ``INGCurve.screen.daily_frontier`` arithmetic,
    generic in y/x).  Returns a DataFrame indexed by ``y_bp.index`` with
    columns ``slope, intercept, r2, n``.
    """
    if int(min_n) < 3:
        raise ValueError(f"min_n must be >= 3 (got {min_n}): 2 points fit exactly")
    missing = [c for c in y_bp.columns if c not in x_bp.columns]
    if missing:
        raise ValueError(f"x_bp is missing columns {missing}")
    x_df = x_bp.reindex(index=y_bp.index, columns=y_bp.columns)

    y = y_bp.to_numpy(dtype=float)
    x = x_df.to_numpy(dtype=float)
    valid = ~(np.isnan(y) | np.isnan(x))
    n_valid = valid.sum(axis=1)

    xm = np.where(valid, x, 0.0)
    ym = np.where(valid, y, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        nx = np.maximum(n_valid, 1)
        mx = xm.sum(axis=1) / nx
        my = ym.sum(axis=1) / nx
        dx = np.where(valid, x - mx[:, None], 0.0)
        dy = np.where(valid, y - my[:, None], 0.0)
        sxx = (dx * dx).sum(axis=1)
        sxy = (dx * dy).sum(axis=1)
        syy = (dy * dy).sum(axis=1)
        slope = sxy / sxx
        intercept = my - slope * mx
        r2 = (sxy * sxy) / (sxx * syy)

    bad = (n_valid < int(min_n)) | (sxx <= 0) | (syy <= 0)
    slope[bad] = np.nan
    intercept[bad] = np.nan
    r2[bad] = np.nan
    return pd.DataFrame(
        {"slope": slope, "intercept": intercept, "r2": r2, "n": n_valid},
        index=y_bp.index,
    )


def off_frontier(
    y_bp: pd.DataFrame, x_bp: pd.DataFrame, fit: pd.DataFrame
) -> pd.DataFrame:
    """Off-frontier residual ``y - (intercept + slope * x)`` per day, in bp.

    ``fit`` is a :func:`daily_xfit` result (needs ``slope`` and ``intercept``
    columns; ``ValueError`` otherwise), reindexed onto ``y_bp``'s dates;
    ``x_bp`` is reindexed onto ``y_bp`` exactly as in :func:`daily_xfit`.
    Days with a NaN fit (too few points / degenerate / date absent from
    ``fit``) yield all-NaN rows, and NaN y or x cells stay NaN -- never zero.

    Sign: with the value-carry orientation (y = residual, x = rolldown),
    off_frontier > 0 = cheap for its carry; with the carry-vol orientation
    (y = rolldown, x = ATM vol), > 0 = carry-rich for its vol.
    """
    need = [c for c in ("slope", "intercept") if c not in fit.columns]
    if need:
        raise ValueError(f"fit frame is missing columns {need} - pass a daily_xfit result")
    missing = [c for c in y_bp.columns if c not in x_bp.columns]
    if missing:
        raise ValueError(f"x_bp is missing columns {missing}")
    x_df = x_bp.reindex(index=y_bp.index, columns=y_bp.columns)
    f = fit.reindex(y_bp.index)
    slope = f["slope"].to_numpy(dtype=float)[:, None]
    intercept = f["intercept"].to_numpy(dtype=float)[:, None]
    resid = y_bp.to_numpy(dtype=float) - (intercept + slope * x_df.to_numpy(dtype=float))
    return pd.DataFrame(resid, index=y_bp.index, columns=y_bp.columns)
