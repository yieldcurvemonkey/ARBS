"""Tests for regression sub-period segmentation (spec I)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.regression import ols_segment


class TestOlsSegment:
    def test_returns_per_period_betas(self):
        rng = np.random.default_rng(42)
        n = 500
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        x1 = rng.standard_normal(n)
        x2 = rng.standard_normal(n)
        y = np.where(np.arange(n) < 250,
                     1.0 * x1 + 0.5 * x2,
                     0.2 * x1 + 2.0 * x2) + rng.standard_normal(n) * 0.1

        ys = pd.Series(y, index=idx, name="y")
        X = pd.DataFrame({"x1": x1, "x2": x2}, index=idx)

        periods = [(idx[0], idx[249]), (idx[250], idx[-1])]
        results = ols_segment(ys, X, periods)

        assert len(results) == 2
        assert abs(results[0]["betas"]["x1"] - 1.0) < 0.3
        assert abs(results[1]["betas"]["x2"] - 2.0) < 0.3

    def test_adj_r2_present(self):
        rng = np.random.default_rng(0)
        n = 200
        idx = pd.date_range("2020", periods=n, freq="B")
        x = rng.standard_normal(n)
        y = 2.0 * x + rng.standard_normal(n) * 0.1
        ys = pd.Series(y, index=idx)
        X = pd.DataFrame({"x": x}, index=idx)
        results = ols_segment(ys, X, [(idx[0], idx[-1])])
        assert "adj_r2" in results[0]
        assert results[0]["adj_r2"] > 0.9
