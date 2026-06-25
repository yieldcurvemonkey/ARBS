"""Integration test for make_pca_fly_rv_screener (spec J)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.screener_rv import make_pca_fly_rv_screener


def _panel(n=400, seed=0, noise_std=0.002):
    rng = np.random.default_rng(seed)
    cols = ["2", "5", "10", "30"]
    L = np.array([[1.0, -1.5, 1.0],
                  [1.0, -0.5, -1.0],
                  [1.0,  0.5, -0.5],
                  [1.0,  1.5,  1.0]])
    f = np.cumsum(rng.standard_normal((n, 3)) * np.array([0.05, 0.03, 0.02]), axis=0)
    base = np.array([2.0, 2.5, 3.0, 3.5])
    X = base + f @ L.T + rng.standard_normal((n, 4)) * noise_std
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(X, index=idx, columns=cols)


class TestCapstone:
    def test_returns_dataframe_with_expected_columns(self):
        df = _panel(n=400)
        structures = {"2s5s10s": ("2", "5", "10"), "5s10s30s": ("5", "10", "30")}
        weights_map = {
            "2s5s10s": {"2": -0.5, "5": 1.0, "10": -0.5},
            "5s10s30s": {"5": -0.5, "10": 1.0, "30": -0.5},
        }
        result = make_pca_fly_rv_screener(df, structures, weights_map, window=200, k=3)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        for col in ["zscore", "half_life", "composite", "adf_pass"]:
            assert col in result.columns

    def test_pipeline_runs_end_to_end(self):
        df = _panel(n=400)
        structures = {"2s5s10s": ("2", "5", "10")}
        weights_map = {"2s5s10s": {"2": -0.5, "5": 1.0, "10": -0.5}}
        result = make_pca_fly_rv_screener(df, structures, weights_map, window=200, k=3, adf_pval=0.50)
        assert isinstance(result, pd.DataFrame)

    def test_sorted_by_composite_magnitude(self):
        df = _panel(n=400)
        structures = {"2s5s10s": ("2", "5", "10"), "5s10s30s": ("5", "10", "30")}
        weights_map = {
            "2s5s10s": {"2": -0.5, "5": 1.0, "10": -0.5},
            "5s10s30s": {"5": -0.5, "10": 1.0, "30": -0.5},
        }
        result = make_pca_fly_rv_screener(df, structures, weights_map, window=200, k=3)
        if len(result) >= 2:
            composites = result["composite"].abs().values
            assert composites[0] >= composites[1] - 1e-10
