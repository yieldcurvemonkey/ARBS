import math

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from statsmodels.tsa.adfvalues import mackinnonp

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


def test_half_life_is_strictly_infinite_for_a_random_walk_via_adf():
    """This fixture (seed=1) is the reason the guard cannot be a ``phi >= 1.0``
    boundary comparison alone: OLS's finite-sample downward bias recovers
    phi ~= 0.9982 here, strictly below 1.0, so a boundary-only implementation
    computes a large but *finite* half-life (~393 business days) -- and the
    verbatim test above still passes on that, because its own fallback
    (``> 100``) accepts any sufficiently large finite value as good enough.
    A ~1.6-year "half life" on a residual that does not mean-revert at all is
    exactly the failure this function exists to prevent, so accepting it as
    a passing test does not actually verify the fix. This test requires
    literal infinity, which is only produced once an Augmented Dickey-Fuller
    test (not just the phi point estimate) is what decides -- ADF fails to
    reject the unit-root null for this fixture (p ~= 0.41), which is the
    actual, correct basis for calling this a unit root."""
    rng = np.random.default_rng(1)
    rw = pd.Series(np.cumsum(rng.normal(0, 1, 3000)))
    assert math.isinf(ar1_half_life_days(rw))


def test_half_life_is_strictly_infinite_at_and_above_the_unit_root():
    """Mutation evidence: dropping the ``phi >= 1.0`` branch (keeping only
    ``phi <= 0.0``) is NOT caught by ``test_half_life_is_infinite_for_a_random_walk``
    above -- seed=1's random walk recovers phi ~= 0.9982 (below 1.0), so the
    mutated code still returns a large-but-finite half-life (~393 business
    days) that clears that test's ``> 100`` fallback. This test plants a
    mildly explosive, noise-free series (phi ~= 1.01, comfortably above the
    unit-root boundary -- unlike an exact phi==1.0 fixture, this is not
    sensitive to which side of 1.0 a platform's floating-point/LAPACK
    implementation happens to land a "perfect" ramp on) and asserts the
    return is *literally* infinite, not merely a large (or negative) finite
    number -- both of which a guard missing the upper bound can produce."""
    explosive = pd.Series(1.01 ** np.arange(30), index=pd.bdate_range("2020-01-01", periods=30))
    assert ar1_phi(explosive) > 1.0
    assert math.isinf(ar1_half_life_days(explosive))


def test_engle_granger_critical_values_are_stricter_than_standard_adf():
    """Mechanism check for the ``n_cointegrating_vars`` correction (Task 15
    round 4): for the SAME ADF test statistic, Engle-Granger critical values
    (N>1 I(1) series in a cointegrating regression) must report a LARGER
    (more conservative) p-value than the standard single-series (N=1) ADF
    table -- that is the entire point of the correction, since OLS has
    already minimised a regression residual's in-sample variance and made it
    look spuriously more stationary. Deterministic: fixed stat values, no
    simulation, so this cannot be flaky."""
    for stat in (-2.5, -3.0, -3.5, -4.0):
        p_standard = mackinnonp(stat, regression="c", N=1)
        p_two_series = mackinnonp(stat, regression="c", N=2)
        p_three_series = mackinnonp(stat, regression="c", N=3)
        assert p_two_series > p_standard
        assert p_three_series > p_two_series


def test_ar1_half_life_days_eg_correction_closes_a_placebo_regression_gate():
    """The actual failure mode the correction exists to prevent: regress one
    random walk on an UNRELATED random walk (no true relationship at all --
    the placebo the Task 15 round-4 review used) and confirm the standard
    (uncorrected) gate opens -- a finite half-life on a residual with no real
    mean-reversion -- while ``n_cointegrating_vars=2`` closes it. Seed=27 was
    chosen by search for a comfortable, non-borderline margin on both sides
    (standard p=0.0315, well under 0.05; EG p=0.1015, well over it) rather
    than a razor's-edge case that could flip under a different LAPACK/BLAS
    build -- the I3 lesson from this same test module's own history."""
    rng = np.random.default_rng(27)
    n = 300
    x = pd.Series(np.cumsum(rng.normal(0, 1, n)))
    y = pd.Series(np.cumsum(rng.normal(0, 1, n)))
    resid = sm.OLS(y, sm.add_constant(x)).fit().resid

    hl_standard = ar1_half_life_days(resid)
    hl_corrected = ar1_half_life_days(resid, n_cointegrating_vars=2)

    assert np.isfinite(hl_standard)  # the uncorrected gate is fooled ...
    assert math.isinf(hl_corrected)  # ... the EG-corrected gate is not


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
