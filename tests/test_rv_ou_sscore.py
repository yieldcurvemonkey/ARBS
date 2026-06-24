"""Tests for OU S-score (spec D, Avellaneda-Lee)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.mean_reversion import ou_sscore


def _make_ou(kappa=0.05, mu=1.5, sigma=0.30, n=2000, seed=42):
    rng = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    s_step = sigma * np.sqrt((1 - np.exp(-2 * kappa)) / (2 * kappa))
    x = np.empty(n)
    x[0] = mu
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + s_step * rng.standard_normal()
    return pd.Series(x, index=pd.date_range("2020-01-01", periods=n, freq="B"), name="ou")


class TestOuSscore:
    def test_approximately_standardized(self):
        s = _make_ou(n=5000, seed=0)
        score = ou_sscore(s)
        assert abs(score.mean()) < 0.3, "S-score mean should be near zero"
        assert 0.5 < score.std() < 2.0, "S-score std should be approximately unit-ish"

    def test_rolling_mode(self):
        s = _make_ou(n=1000)
        score = ou_sscore(s, window=252)
        assert isinstance(score, pd.Series)
        assert score.notna().sum() > 100

    def test_full_sample_mode(self):
        s = _make_ou(n=500)
        score = ou_sscore(s)
        assert len(score) == len(s)
