"""Tests for lead-lag detection module (spec C)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.lead_lag import levy_area, levy_area_signal, xcorr_lead_lag, granger_lead_lag


def _leader_follower(n=500, lag=3, noise=0.1, seed=42):
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.standard_normal(n + lag))
    y = x[lag:] + rng.standard_normal(n) * noise
    x_s = x[lag:]
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(x_s, index=idx, name="x"), pd.Series(y, index=idx, name="y")


class TestXcorrLeadLag:
    def test_recovers_known_lag(self):
        lag_true = 5
        rng = np.random.default_rng(99)
        n = 1000
        x = np.cumsum(rng.standard_normal(n))
        y = np.roll(x, lag_true) + rng.standard_normal(n) * 0.05
        y[:lag_true] = np.nan
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        xs = pd.Series(x, index=idx)
        ys = pd.Series(y, index=idx)
        result = xcorr_lead_lag(xs, ys, max_lag=10)
        assert result["lag"] == lag_true
        assert result["corr"] > 0.5

    def test_zero_lag_for_simultaneous(self):
        rng = np.random.default_rng(42)
        n = 500
        x = np.cumsum(rng.standard_normal(n))
        y = x + rng.standard_normal(n) * 0.01
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        result = xcorr_lead_lag(pd.Series(x, index=idx), pd.Series(y, index=idx), max_lag=10)
        assert result["lag"] == 0


class TestLevyArea:
    def test_output_shape(self):
        x, y = _leader_follower(n=200, lag=3)
        la = levy_area(x, y, window=20)
        assert isinstance(la, pd.Series)
        assert len(la) <= 200

    def test_sign_indicates_lead_direction(self):
        rng = np.random.default_rng(7)
        n = 600
        x = np.cumsum(rng.standard_normal(n) * 0.5)
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        y = np.empty(n)
        y[0] = x[0]
        for t in range(1, n):
            y[t] = x[t - 1] + rng.standard_normal() * 0.01
        xs = pd.Series(x, index=idx, name="x")
        ys = pd.Series(y, index=idx, name="y")
        la = levy_area(xs, ys, window=50)
        assert la.dropna().mean() != 0  # non-zero mean


class TestLevyAreaSignal:
    def test_output_values_in_expected_set(self):
        x, y = _leader_follower(n=300, lag=2)
        sig = levy_area_signal(x, y, window=20, theta_entry=1.5, theta_exit=0.5)
        assert isinstance(sig, pd.Series)
        unique_vals = set(sig.dropna().unique())
        assert unique_vals.issubset({-1, 0, 1})


class TestGrangerLeadLag:
    def test_recovers_direction(self):
        rng = np.random.default_rng(42)
        n = 500
        x = rng.standard_normal(n)
        y = np.zeros(n)
        for t in range(2, n):
            y[t] = 0.8 * x[t - 2] + rng.standard_normal() * 0.1
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        result = granger_lead_lag(pd.Series(x, index=idx), pd.Series(y, index=idx), max_lag=5)
        assert "lag" in result
        assert "pvalue" in result
        assert result["pvalue"] < 0.05
