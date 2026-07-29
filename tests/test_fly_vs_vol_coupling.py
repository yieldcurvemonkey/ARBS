"""Tests for RVUtils.FlyVsVol.coupling against Normal closed forms."""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from RVUtils.FlyVsVol import ContractMarginal
from RVUtils.FlyVsVol.coupling import (
    comonotone_grid,
    gaussian_copula_sample,
    historical_corr,
)

MUS = (3.99, 4.145, 4.225)
SIGMAS = (0.30, 0.45, 0.82)


def normal_marginal(sym, mu, sigma, n=6001, span=6.0):
    grid = np.linspace(mu - span * sigma, mu + span * sigma, n)
    return ContractMarginal(
        symbol=sym, grid_rate=grid, cdf=norm.cdf(grid, mu, sigma), forward_rate=mu
    )


@pytest.fixture()
def marginals():
    return [
        normal_marginal(s, m, sg)
        for s, m, sg in zip(("F", "B", "K"), MUS, SIGMAS)
    ]


def phi_bp(rates):
    return (2 * rates[:, 1] - rates[:, 0] - rates[:, 2]) * 100


def test_comonotone_shape_and_monotonicity(marginals):
    rates = comonotone_grid(marginals, n=5001)
    assert rates.shape == (5001, 3)
    assert np.all(np.diff(rates, axis=0) >= -1e-12)  # each column non-decreasing in U


def test_comonotone_normals_closed_form(marginals):
    rates = comonotone_grid(marginals, n=20001)
    phi = phi_bp(rates)
    fly_bp = (2 * MUS[1] - MUS[0] - MUS[2]) * 100
    s_eff = 2 * SIGMAS[1] - SIGMAS[0] - SIGMAS[2]  # phi = fly + s_eff*z (percent)
    assert phi.mean() == pytest.approx(fly_bp, abs=0.05)
    p_gt0 = (phi > 0).mean()
    assert p_gt0 == pytest.approx(norm.cdf(fly_bp / (abs(s_eff) * 100)), abs=0.005)
    # quantiles linear in z
    z90 = norm.ppf(0.90)
    expected_q = fly_bp + abs(s_eff) * 100 * z90
    assert np.percentile(phi, 90) == pytest.approx(expected_q, rel=0.02)


def test_copula_rho1_matches_comonotone(marginals):
    como = phi_bp(comonotone_grid(marginals, n=20001))
    corr = np.full((3, 3), 1.0)
    cop = phi_bp(
        gaussian_copula_sample(marginals, corr, n_sim=200_000,
                               rng=np.random.default_rng(11))
    )
    for p in (5, 25, 50, 75, 95):
        assert np.percentile(cop, p) == pytest.approx(np.percentile(como, p), abs=0.5)


def test_copula_rho0_wider(marginals):
    como = phi_bp(comonotone_grid(marginals, n=20001))
    cop = phi_bp(
        gaussian_copula_sample(marginals, np.eye(3), n_sim=100_000,
                               rng=np.random.default_rng(11))
    )
    assert cop.std() > como.std()


def test_historical_corr_min_overlap():
    idx = pd.bdate_range("2026-01-01", periods=100)
    rng = np.random.default_rng(3)
    panel = pd.DataFrame(
        {"A": np.cumsum(rng.normal(size=100)), "B": np.cumsum(rng.normal(size=100))},
        index=idx,
    )
    panel["C"] = np.nan
    panel.loc[idx[:10], "C"] = np.cumsum(rng.normal(size=10))  # only 9 overlapping diffs
    corr = historical_corr(panel, min_overlap=60)
    assert not np.isnan(corr.loc["A", "B"])
    assert np.isnan(corr.loc["A", "C"]) and np.isnan(corr.loc["C", "B"])
    assert corr.loc["A", "A"] == pytest.approx(1.0)
