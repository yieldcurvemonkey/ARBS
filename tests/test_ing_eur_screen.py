"""Synthetic-only tests for the ING curve-deconstruction screen.

Fast, no data files, no network.  Verifies the checker itself:
(i)  a day exactly on its PC1 fit has ~0 residual;
(ii) a planted +20bp dislocation on 5F1Y is recovered to within 2bp;
(iii) feeding percent as decimal makes the bootstrap fail loudly.
"""

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import pytest

from RVUtils.INGCurve import (
    INTEGER_TENORS,
    annual_forwards,
    bootstrap_discounts,
    daily_frontier,
    integer_par_grid,
    residual_percentiles,
    reversion_gate,
    rolldown_3m,
    rolling_pc1_residuals,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _flat_par(days=3, rate=3.0):
    idx = pd.bdate_range("2024-01-01", periods=days)
    return pd.DataFrame(
        np.full((days, 30), rate), index=idx, columns=INTEGER_TENORS.tolist()
    )


def _rank1_forwards(n_days=400, m=29, seed=7):
    """Forward panel lying EXACTLY on a one-factor structure (levels)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n_days)
    mu = 1.0 + 0.05 * np.arange(m)                # upward-sloping strip, percent
    v = 1.0 + 0.10 * rng.standard_normal(m)       # near-flat loading
    v = np.abs(v)
    v = v / np.linalg.norm(v)                     # v_j^2 ~ 1/29 << 0.1
    scores = np.cumsum(0.03 * rng.standard_normal(n_days))  # level factor walk
    x = mu[None, :] + scores[:, None] * v[None, :]
    return pd.DataFrame(x, index=idx, columns=list(range(1, m + 1))), v


# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------

def test_flat_curve_bootstrap_roundtrip():
    """Flat par 3% => DF_N = 1.03^-N and every 1y forward = 3%."""
    par = _flat_par(rate=3.0)
    dfs = bootstrap_discounts(par)
    expected = (1.03) ** -INTEGER_TENORS.astype(float)
    np.testing.assert_allclose(dfs.iloc[0].to_numpy(), expected, rtol=1e-12)
    fwd = annual_forwards(dfs, include_spot=True)
    np.testing.assert_allclose(fwd.to_numpy(), 3.0, rtol=1e-10)


def test_negative_rates_are_legal():
    """Negative-EUR-era curves (DF > 1) must pass the sanity gate."""
    par = _flat_par(rate=-0.5)
    dfs = bootstrap_discounts(par)
    assert (dfs.to_numpy() > 1.0).all()


def test_percent_as_decimal_fails_loudly():
    """(iii) Mutated bootstrap - percent fed as decimal - must raise."""
    par = _flat_par(rate=3.0)
    with pytest.raises(ValueError, match="percent"):
        bootstrap_discounts(par * 100.0)  # == skipping the /100 conversion


def test_integer_par_grid_interpolates_and_gates():
    idx = pd.bdate_range("2024-01-01", periods=4)
    cols = [f"{n}Y" for n in INTEGER_TENORS] + ["15M"]
    vals = np.tile(np.r_[np.linspace(1.0, 3.9, 30), [1.05]], (4, 1))
    grid = pd.DataFrame(vals, index=idx, columns=cols)
    # knock out 21..24Y everywhere -> must be linearly re-interpolated
    for n in (21, 22, 23, 24):
        grid[f"{n}Y"] = np.nan
    # day 1: too few printed tenors; day 2: missing the 30Y endpoint;
    # day 3: missing 1Y but 2Y/3Y printed -> kept with a FLAGGED linear anchor
    grid.iloc[1, :] = np.nan
    grid.iloc[1, grid.columns.get_loc("1Y")] = 1.0
    grid.iloc[2, grid.columns.get_loc("30Y")] = np.nan
    grid.iloc[3, grid.columns.get_loc("1Y")] = np.nan

    dense, skipped, flag = integer_par_grid(grid, min_printed=15)
    assert list(dense.index) == [idx[0], idx[3]]
    assert list(skipped) == [idx[1], idx[2]]
    assert flag.tolist() == [False, True]
    # linspace grid is linear in tenor => interpolation reproduces it exactly
    np.testing.assert_allclose(
        dense.loc[idx[0]].to_numpy(), np.linspace(1.0, 3.9, 30), rtol=1e-12
    )
    # the anchor 2*s_2 - s_3 is exact on a linear par curve
    np.testing.assert_allclose(
        dense.loc[idx[3]].to_numpy(), np.linspace(1.0, 3.9, 30), rtol=1e-12
    )
    # printed_only drops the anchored day; always_extrapolate flags both
    dense_p, _, flag_p = integer_par_grid(grid, min_printed=15,
                                          anchor_1y="printed_only")
    assert list(dense_p.index) == [idx[0]]
    dense_a, _, flag_a = integer_par_grid(grid, min_printed=15,
                                          anchor_1y="always_extrapolate")
    assert flag_a.tolist() == [True, True]
    np.testing.assert_allclose(
        dense_a.loc[idx[0]].to_numpy(), dense.loc[idx[0]].to_numpy(), rtol=1e-12
    )


def test_anchor_immaterial_beyond_2f1y():
    """The 1Y anchor moves 1F1Y by tens of bp but k>=2 forwards by <0.5bp.

    This is the check that licenses the primary-panel architecture: on a
    curved par curve where the linear anchor 2*s_2 - s_3 is wrong by ~20bp,
    the bootstrap with true vs anchored s_1 must agree on every forward from
    2F1Y out.
    """
    idx = pd.bdate_range("2024-01-01", periods=1)
    n = INTEGER_TENORS.astype(float)
    true_par = 3.0 - 2.5 * np.exp(-n / 2.0)      # steep, concave front
    par_true = pd.DataFrame([true_par], index=idx, columns=INTEGER_TENORS.tolist())
    par_anchor = par_true.copy()
    anchor = 2.0 * true_par[1] - true_par[2]      # linear extrapolation
    par_anchor.iloc[0, 0] = anchor
    assert abs(anchor - true_par[0]) * 100 > 10.0  # anchor is wrong by >10bp

    f_true = annual_forwards(bootstrap_discounts(par_true))
    f_anchor = annual_forwards(bootstrap_discounts(par_anchor))
    diff_bp = (f_anchor - f_true).abs() * 100.0
    assert diff_bp[1].iloc[0] > 10.0              # 1F1Y is construction
    assert diff_bp[[k for k in diff_bp.columns if k >= 2]].to_numpy().max() < 0.5


# ---------------------------------------------------------------------------
# roll-down
# ---------------------------------------------------------------------------

def test_rolldown_linear_strip():
    """f(k) = a + b*k => roll = 0.25*b*100 bp for every k."""
    idx = pd.bdate_range("2024-01-01", periods=2)
    ks = list(range(0, 30))
    f = pd.DataFrame(
        [[2.0 + 0.04 * k for k in ks]] * 2, index=idx, columns=ks
    )
    roll = rolldown_3m(f)
    np.testing.assert_allclose(roll.to_numpy(), 0.25 * 0.04 * 100.0, rtol=1e-12)
    assert list(roll.columns) == list(range(1, 30))


# ---------------------------------------------------------------------------
# PCA residuals: verify the checker
# ---------------------------------------------------------------------------

def test_pc1_exact_fit_gives_zero_residual():
    """(i) Every day sits exactly on the one-factor structure -> residual ~0."""
    fwd, _ = _rank1_forwards()
    resid = rolling_pc1_residuals(fwd, window=250, min_window=200)
    got = resid.to_numpy()
    assert np.isnan(got[:200]).all()          # ramp-in months are NaN
    valid = got[~np.isnan(got)]
    assert valid.size > 0
    assert np.abs(valid).max() < 1e-6         # bp


def test_planted_dislocation_recovered():
    """(ii) +20bp planted on 5F1Y is recovered to within 2bp of 20bp."""
    fwd, v = _rank1_forwards()
    col = 5
    j = list(fwd.columns).index(col)
    assert v[j] ** 2 <= 0.1                   # leakage 20*v_j^2 stays tiny
    shock_day = fwd.index[380]                # strictly after its refit window
    fwd.loc[shock_day, col] += 0.20           # +20bp in percent
    resid = rolling_pc1_residuals(fwd, window=250, min_window=200)
    got = resid.loc[shock_day, col]
    assert abs(got - 20.0) < 2.0
    # other days in that month remain clean fits
    other = resid.loc[resid.index[370], col]
    assert abs(other) < 1e-6


def test_pca_windows_are_strictly_prior():
    """A shock in month M must not alter loadings used within month M."""
    fwd, _ = _rank1_forwards()
    resid_clean = rolling_pc1_residuals(fwd, window=250, min_window=200)
    fwd2 = fwd.copy()
    fwd2.iloc[380, :] += 0.50                 # parallel shock, late day
    resid_shocked = rolling_pc1_residuals(fwd2, window=250, min_window=200)
    same_month = fwd.index[fwd.index.to_period("M") == fwd.index[380].to_period("M")]
    prior = [d for d in same_month if d < fwd.index[380]]
    a = resid_clean.loc[prior].to_numpy()
    b = resid_shocked.loc[prior].to_numpy()
    np.testing.assert_allclose(a, b, atol=1e-12)


# ---------------------------------------------------------------------------
# percentiles / gate / frontier smoke on synthetic residuals
# ---------------------------------------------------------------------------

def test_rank_excludes_current_day():
    idx = pd.bdate_range("2020-01-01", periods=60)
    r = pd.DataFrame({1: np.zeros(60)}, index=idx)
    r.iloc[59, 0] = 10.0                      # record day
    pct = residual_percentiles(r, window=50, min_obs=20)
    assert pct["rank"].iloc[59, 0] == 1.0     # all history strictly below
    assert pct["p50"].iloc[59, 0] == 0.0      # median of history, not of today


def test_reversion_gate_full_reversion():
    """Dislocate, then snap back: gate must report ~full reversion."""
    n = 400
    idx = pd.bdate_range("2019-01-01", periods=n)
    rng = np.random.default_rng(3)
    base = 0.5 * rng.standard_normal(n)
    x = base.copy()
    x[300] = 25.0                             # single extreme day, reverts next day
    r = pd.DataFrame({5: x}, index=idx)
    pct = residual_percentiles(r, window=250, min_obs=100)
    gate = reversion_gate(
        r, pct["rank"], pct["p50"], horizons=(21, 63), revert_horizon=63
    )
    row = gate.loc["5F1Y"]
    assert row["n_fired"] >= 1
    fired_rank = pct["rank"].iloc[300, 0]
    assert fired_rank >= 0.95
    # the 25bp day reverts fully by 21bd
    assert row["med_reversion_21bd"] > 0


def test_daily_frontier_recovers_planted_line():
    idx = pd.bdate_range("2024-01-01", periods=2)
    ks = list(range(1, 30))
    roll = pd.DataFrame(
        np.tile(np.linspace(0.0, 5.0, len(ks)), (2, 1)), index=idx, columns=ks
    )
    resid = -1.27 * roll + 3.0                # exact line => R2 = 1
    fr = daily_frontier(resid, roll, ks=range(2, 16))
    np.testing.assert_allclose(fr["slope"].to_numpy(), -1.27, rtol=1e-10)
    np.testing.assert_allclose(fr["intercept"].to_numpy(), 3.0, rtol=1e-10)
    np.testing.assert_allclose(fr["r2"].to_numpy(), 1.0, rtol=1e-10)
    assert (fr["n"] == 14).all()
