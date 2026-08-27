"""Tests for RVUtils.CvxSuite.frontiers (daily_xfit / off_frontier).

Pure-logic tests on synthetic panels -- nothing touches a store or panel file,
so no integration/slow marks.

Known-answer anchors: an exact planted per-day line is recovered to machine
precision (slope/intercept/r2 = 1), and the textbook OLS identities (residual
mean 0, residual orthogonal to x, per day) hold for a fitted frontier.  Every
planted answer has a negative control that must fail; degenerate days must be
NaN, never a silent zero.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import pytest

from RVUtils.CvxSuite.frontiers import daily_xfit, off_frontier

IDX = pd.to_datetime(["2026-08-20", "2026-08-21", "2026-08-24"])
COLS = [f"p{i}" for i in range(10)]

#: Per-day planted lines.  Day-0 slope -1.27 is the ING 2020-01-15 published
#: value-carry frontier slope (the number the fit must be able to read back).
A_TRUE = np.array([1.0, -2.0, 0.5])
B_TRUE = np.array([-1.27, 0.8, 2.5])


def _panels(noise: float = 0.0, seed: int = 3):
    rng = np.random.default_rng(seed)
    x = pd.DataFrame(rng.normal(2.0, 5.0, (3, 10)), index=IDX, columns=COLS)
    y = x.mul(B_TRUE, axis=0).add(A_TRUE, axis=0)
    if noise:
        y = y + rng.normal(0.0, noise, (3, 10))
    return y, x


def test_daily_xfit_recovers_planted_line_exactly():
    """Noise-free planted lines are recovered per day to machine precision.

    MUTATION 1: pool the panel into one OLS (drop the per-day axis) -- three
    different planted slopes cannot all match and the allclose fails.
    MUTATION 2: swap y and x in the regression -- slope reads 1/b (r2 stays 1),
    the slope pin fails.
    """
    y, x = _panels(noise=0.0)
    fit = daily_xfit(y, x, min_n=3)
    assert list(fit.columns) == ["slope", "intercept", "r2", "n"]
    assert np.allclose(fit["slope"].to_numpy(), B_TRUE, atol=1e-10)
    assert np.allclose(fit["intercept"].to_numpy(), A_TRUE, atol=1e-9)
    assert np.allclose(fit["r2"].to_numpy(), 1.0, atol=1e-12)
    assert (fit["n"] == 10).all()
    # negative controls -- each must fail
    assert not np.allclose(fit["slope"].to_numpy(), B_TRUE[::-1], atol=1e-3)
    assert not np.allclose(fit["slope"].to_numpy(), 1.0 / B_TRUE, atol=1e-3)


def test_daily_xfit_with_noise_stays_close_and_r2_in_unit_interval():
    y, x = _panels(noise=0.8)
    fit = daily_xfit(y, x, min_n=3)
    assert np.allclose(fit["slope"].to_numpy(), B_TRUE, atol=0.25)
    assert ((fit["r2"] > 0.5) & (fit["r2"] < 1.0)).all()


def test_daily_xfit_refuses_degenerate_days_with_nan():
    """Thin or degenerate days -> NaN fit (never a fabricated 0.0 slope).

    Day 0: only 2 valid points (< min_n=3).  Day 1: constant x (sxx = 0).
    Day 2: constant y (syy = 0) -- a flat cross-section COULD be read as
    slope 0, but a printed 0.0 would be indistinguishable from a measured
    flat frontier, so it is refused (the silent-zero rule).

    MUTATION: replace the `bad` masking with `slope[bad] = 0.0` -- every
    isnan assert here fails.
    """
    y, x = _panels()
    y = y.copy()
    x = x.copy()
    y.iloc[0, 2:] = np.nan            # 2 valid points on day 0
    x.iloc[1] = 7.0                   # constant x on day 1
    y.iloc[2] = 3.0                   # constant y on day 2
    fit = daily_xfit(y, x, min_n=3)
    assert fit.loc[IDX[0], ["slope", "intercept", "r2"]].isna().all()
    assert fit.loc[IDX[0], "n"] == 2  # the count is still reported
    assert fit.loc[IDX[1], ["slope", "intercept", "r2"]].isna().all()
    assert fit.loc[IDX[2], ["slope", "intercept", "r2"]].isna().all()


def test_daily_xfit_min_n_and_alignment_guards():
    y, x = _panels()
    with pytest.raises(ValueError, match="min_n"):
        daily_xfit(y, x, min_n=2)
    with pytest.raises(ValueError, match="missing columns"):
        daily_xfit(y, x[COLS[:-1]])
    # extra x columns are ignored; a date absent from x fits as an empty day
    x_extra = x.copy()
    x_extra["zz"] = 1.0
    fit = daily_xfit(y, x_extra, min_n=3)
    assert np.allclose(fit["slope"].to_numpy(), B_TRUE, atol=1e-10)
    fit2 = daily_xfit(y, x.iloc[:2], min_n=3)
    assert fit2.loc[IDX[2], ["slope", "intercept", "r2"]].isna().all()
    assert fit2.loc[IDX[2], "n"] == 0


def test_off_frontier_planted_bump():
    """off_frontier is y - (a + b x): a +5 bp bump off a known line reads 5.0.

    The fit is computed on the CLEAN panel and applied to the bumped one, so
    the planted residual is exact.

    MUTATION 1: compute y + (a + b x) -- the zero cells read ~2(a + b x), the
    zero assert fails.
    MUTATION 2: forget the intercept in the subtraction -- clean cells read
    `a`, not 0.
    """
    y, x = _panels(noise=0.0)
    fit = daily_xfit(y, x, min_n=3)
    off_clean = off_frontier(y, x, fit)
    assert np.allclose(off_clean.to_numpy(), 0.0, atol=1e-9)

    y_bump = y.copy()
    y_bump.iloc[1, 3] += 5.0
    off = off_frontier(y_bump, x, fit)
    assert off.iloc[1, 3] == pytest.approx(5.0, abs=1e-9)
    mask = np.ones(off.shape, dtype=bool)
    mask[1, 3] = False
    assert np.allclose(off.to_numpy()[mask], 0.0, atol=1e-9)
    # negative control -- must fail: the bumped cell is NOT on the frontier
    assert not np.isclose(off.iloc[1, 3], 0.0, atol=1e-3)


def test_off_frontier_ols_identities():
    """Textbook OLS anchors, per day: residual mean 0 and cov(residual, x) 0.

    MUTATION: fit without an intercept in daily_xfit -- the per-day residual
    mean stops being 0.
    """
    y, x = _panels(noise=0.8)
    fit = daily_xfit(y, x, min_n=3)
    off = off_frontier(y, x, fit)
    for d in IDX:
        r = off.loc[d].to_numpy()
        xv = x.loc[d].to_numpy()
        assert abs(r.mean()) < 1e-9
        assert abs(np.sum(r * (xv - xv.mean()))) < 1e-7
    # and the residual is genuinely nonzero (noise is there)
    assert np.abs(off.to_numpy()).max() > 0.1


def test_off_frontier_nan_propagation_and_guards():
    """NaN fit day -> all-NaN residual row; NaN cells stay NaN; loud guards.

    MUTATION: fillna(0) on the fit inside off_frontier -- the all-NaN row
    assert fails (residuals would print as y - 0).
    """
    y, x = _panels()
    y = y.copy()
    y.iloc[0, 2:] = np.nan  # day 0 fit will be NaN (2 points)
    fit = daily_xfit(y, x, min_n=3)
    off = off_frontier(y, x, fit)
    assert off.iloc[0].isna().all()          # NaN fit -> NaN row, never y-0
    assert off.iloc[1].notna().all()
    with pytest.raises(ValueError, match="missing columns"):
        off_frontier(y, x[COLS[:-1]], fit)
    with pytest.raises(ValueError, match="daily_xfit"):
        off_frontier(y, x, fit[["r2", "n"]])
    # a date absent from the fit frame is NaN too
    off2 = off_frontier(y, x, fit.iloc[1:])
    assert off2.iloc[0].isna().all()
