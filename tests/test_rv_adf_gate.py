"""Tests for ADF gate (spec E)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.mean_reversion import adf_gate


def _make_ou(kappa=0.1, mu=0.0, sigma=0.3, n=1000, seed=42):
    rng = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    s_step = sigma * np.sqrt((1 - np.exp(-2 * kappa)) / (2 * kappa))
    x = np.empty(n)
    x[0] = mu
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + s_step * rng.standard_normal()
    return pd.Series(x, index=pd.date_range("2020", periods=n, freq="B"))


class TestAdfGate:
    def test_stationary_passes(self):
        s = _make_ou(kappa=0.1, n=1000, seed=0)
        assert adf_gate(s, pval=0.10) is True

    def test_random_walk_fails(self):
        rng = np.random.default_rng(42)
        rw = pd.Series(np.cumsum(rng.standard_normal(2000)),
                       index=pd.date_range("2020", periods=2000, freq="B"))
        assert adf_gate(rw, pval=0.05) is False

    def test_custom_pval(self):
        s = _make_ou(kappa=0.1, n=1000, seed=1)
        result = adf_gate(s, pval=0.01)
        assert isinstance(result, bool)
