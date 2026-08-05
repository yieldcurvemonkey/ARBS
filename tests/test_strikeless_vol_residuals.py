import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.StrikelessVol.factors import (
    ar1_half_life_days,
    ar1_phi,
    drift,
    positive_residual_clustering,
    residual_z,
)


def _ar1(phi, n=4000, sigma=1.0, seed=0):
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sigma, n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return pd.Series(x, index=pd.bdate_range("2015-01-01", periods=n))


def test_ar1_phi_recovers_a_planted_persistence():
    assert ar1_phi(_ar1(0.87)) == pytest.approx(0.87, abs=0.03)


def test_half_life_of_phi_087_is_about_a_week():
    hl = ar1_half_life_days(_ar1(0.87))
    assert 4.0 < hl < 7.0  # ln(0.5)/ln(0.87) = 4.98 business days


def test_half_life_is_infinite_for_a_random_walk():
    rng = np.random.default_rng(1)
    rw = pd.Series(np.cumsum(rng.normal(0, 1, 3000)))
    assert not np.isfinite(ar1_half_life_days(rw)) or ar1_half_life_days(rw) > 100


def test_half_life_is_strictly_infinite_at_and_above_the_unit_root():
    """Mutation evidence: dropping the ``phi >= 1.0`` branch (keeping only
    ``phi <= 0.0``) is NOT caught by ``test_half_life_is_infinite_for_a_random_walk``
    above -- seed=1's random walk recovers phi ~= 0.9982 (below 1.0), so the
    mutated code still returns a large-but-finite half-life (~393 business
    days) that clears that test's ``> 100`` fallback. This test plants a
    residual series whose OLS AR(1) fit is exactly phi=1.0 (a perfect,
    noise-free linear ramp: resid[i] = resid[i-1] + 1 for every i) so the
    boundary itself is exercised deterministically, and asserts the return is
    *literally* infinite -- not merely a large or negative finite number, both
    of which a guard missing the upper bound can produce (division by
    log(phi)=0 gives -inf for phi==1.0 exactly, but any phi > 1.0, e.g. a
    mildly explosive OLS fit, gives a negative *finite* half-life under a
    broken guard, which is not caught by an `or > 100` fallback either)."""
    ramp = pd.Series(np.arange(1.0, 31.0), index=pd.bdate_range("2020-01-01", periods=30))
    assert ar1_phi(ramp) == pytest.approx(1.0)
    assert math.isinf(ar1_half_life_days(ramp))

    explosive = pd.Series(1.01 ** np.arange(30), index=pd.bdate_range("2020-01-01", periods=30))
    assert ar1_phi(explosive) > 1.0
    assert math.isinf(ar1_half_life_days(explosive))


def test_residual_z_uses_the_residuals_own_dispersion_not_the_ols_se():
    s = _ar1(0.5, n=1000, sigma=2.0)
    z = residual_z(s, window=252, min_periods=126).dropna()
    # a z built on sigma/sqrt(n) would be sqrt(252) times too large
    assert z.abs().max() < 6.0
    assert z.std() == pytest.approx(1.0, abs=0.25)


def test_drift_detects_a_planted_positive_mean():
    rng = np.random.default_rng(2)
    x = pd.Series(0.2 + rng.normal(0, 1.0, 500),
                  index=pd.bdate_range("2024-01-01", periods=500))
    out = drift(x, window=250)
    assert out["mean_bp_per_day"].iloc[-1] == pytest.approx(0.2, abs=0.15)
    assert out["t_stat"].iloc[-1] > 1.5


def test_drift_is_flat_for_zero_mean_noise():
    rng = np.random.default_rng(3)
    x = pd.Series(rng.normal(0, 1.0, 500),
                  index=pd.bdate_range("2024-01-01", periods=500))
    out = drift(x, window=250)
    assert abs(out["t_stat"].iloc[-1]) < 2.0


def test_clustering_is_one_when_every_residual_is_positive():
    x = pd.Series(np.ones(50), index=pd.bdate_range("2026-01-01", periods=50))
    assert positive_residual_clustering(x, window=21).iloc[-1] == pytest.approx(1.0)
