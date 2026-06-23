"""Tests for regression.py RV extensions (Task 10): beta-stability TLI,
residual diagnostics, level/curve-neutral fly."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.regression import (
    rolling_beta_stability,
    residual_diagnostics,
    level_curve_neutral_fly,
)


def _rw(n, seed, scale=0.05):
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.standard_normal(n) * scale)


def _ou(n, seed, kappa=0.1, sigma=0.1):
    rng = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    s = np.empty(n)
    s[0] = 0.0
    for t in range(1, n):
        s[t] = phi * s[t - 1] + sigma * rng.standard_normal()
    return s


def _idx(n):
    return pd.date_range("2021-01-04", periods=n, freq="B")


def test_rolling_beta_stability_distinguishes_regime_break():
    n = 700
    idx = _idx(n)
    level = pd.Series(_rw(n, 1), index=idx)
    slope = pd.Series(_rw(n, 2), index=idx)
    drivers = pd.concat([level.rename("level"), slope.rename("slope")], axis=1)
    noise = pd.Series(_ou(n, 3, sigma=0.01), index=idx)

    y_stable = 1.0 * level + 0.5 * slope + noise
    y_break = pd.Series(np.where(np.arange(n) < n // 2, 1.0, 3.0), index=idx) * level + 0.5 * slope + noise

    out_s = rolling_beta_stability(y_stable, drivers, window_beta=60, window_vol=30, window_z=60)
    out_b = rolling_beta_stability(y_break, drivers, window_beta=60, window_vol=30, window_z=60)

    assert "TLI" in out_s.columns
    assert np.nanmedian(out_s["TLI"]) < 3.0
    assert np.nanmax(out_b["TLI"]) > 3.0
    assert np.nanmax(out_b["TLI"]) > np.nanmedian(out_s["TLI"])


def test_residual_diagnostics_stationary_vs_rw():
    idx = _idx(1200)
    ou = pd.Series(_ou(1200, 7, kappa=0.08, sigma=0.1), index=idx)
    rw = pd.Series(_rw(1200, 8), index=idx)

    d_ou = residual_diagnostics(ou)
    d_rw = residual_diagnostics(rw)

    assert d_ou["adf_pvalue"] < 0.05 and np.isfinite(d_ou["half_life"]) and d_ou["half_life"] > 0
    assert d_rw["adf_pvalue"] > 0.10


def test_level_curve_neutral_fly_orthogonalizes():
    n = 800
    idx = _idx(n)
    level = pd.Series(_rw(n, 11), index=idx)
    slope = pd.Series(_rw(n, 12), index=idx)
    resid = pd.Series(_ou(n, 13, sigma=0.05), index=idx)
    fly = 0.3 * level - 0.2 * slope + resid

    out = level_curve_neutral_fly(fly, level, slope, window=None)
    r = out["residual"]
    assert abs(r.corr(level.reindex(r.index))) < 0.12
    assert abs(r.corr(slope.reindex(r.index))) < 0.12
    assert out["betas"]["level"] == pytest.approx(0.3, abs=0.05)
    assert out["betas"]["slope"] == pytest.approx(-0.2, abs=0.05)
