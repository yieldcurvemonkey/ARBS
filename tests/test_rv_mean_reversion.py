"""Tests for RVUtils.mean_reversion OU extensions (Task 1)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.mean_reversion import (
    calibrate_ou,
    ou_conditional,
    ou_ex_ante_sharpe,
    first_passage_time,
)


def _make_ou_path(kappa, mu, sigma, n, x0=None, seed=0, dt=1.0):
    """Exact discrete OU simulation: x_t = mu + phi(x_{t-1}-mu) + N(0, s_step)."""
    rng = np.random.default_rng(seed)
    phi = np.exp(-kappa * dt)
    s_step = sigma * np.sqrt((1.0 - np.exp(-2 * kappa * dt)) / (2 * kappa))
    x = np.empty(n)
    x[0] = mu if x0 is None else x0
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + s_step * rng.standard_normal()
    idx = pd.date_range("2000-01-03", periods=n, freq="B")
    return pd.Series(x, index=idx, name="ou")


def test_calibrate_ou_recovers_halflife():
    kappa, mu, sigma = 0.05, 1.5, 0.30
    true_hl = np.log(2.0) / kappa  # ~13.86
    s = _make_ou_path(kappa, mu, sigma, n=8000, seed=42)
    params = calibrate_ou(s)
    assert set(params) >= {"mu", "kappa", "sigma", "phi", "intercept", "half_life"}
    assert 0.0 < params["phi"] < 1.0
    assert true_hl * 0.7 < params["half_life"] < true_hl * 1.3
    assert abs(params["mu"] - mu) < 0.15


def test_calibrate_ou_handles_short_series():
    s = pd.Series([1.0, 2.0], index=pd.date_range("2020", periods=2))
    params = calibrate_ou(s)
    assert np.isnan(params["half_life"])


def test_ou_conditional_mean_decays_to_mu():
    params = {"mu": 0.0, "kappa": 0.1, "sigma": 0.2, "phi": np.exp(-0.1), "half_life": np.log(2) / 0.1}
    near = ou_conditional(2.0, params, horizon=1)
    far = ou_conditional(2.0, params, horizon=200)
    assert 0.0 < far["mean"] < near["mean"] < 2.0  # decays toward mu=0
    # variance rises toward stationary sigma^2/(2 kappa)
    stat_var = params["sigma"] ** 2 / (2 * params["kappa"])
    assert near["var"] < far["var"] <= stat_var * 1.0001
    assert far["var"] == pytest.approx(stat_var, rel=1e-3)


def test_ou_ex_ante_sharpe_sign():
    params = {"mu": 0.0, "kappa": 0.1, "sigma": 0.2, "phi": np.exp(-0.1), "half_life": np.log(2) / 0.1}
    sr_cheap = ou_ex_ante_sharpe(-1.0, params, horizon=10)  # below mean -> expect rise -> +
    sr_rich = ou_ex_ante_sharpe(1.0, params, horizon=10)    # above mean -> expect fall -> -
    assert sr_cheap > 0 > sr_rich
    assert np.isfinite(sr_cheap)


def test_first_passage_time_monotone_in_distance():
    params = calibrate_ou(_make_ou_path(0.08, 0.0, 0.25, n=4000, seed=7))
    np.random.seed(123)
    fpt_near = first_passage_time(0.3, 0.0, params, sims=3000, steps=252)
    fpt_far = first_passage_time(1.2, 0.0, params, sims=3000, steps=252)
    assert 0.0 < fpt_near < fpt_far <= 252
