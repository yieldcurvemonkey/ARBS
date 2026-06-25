"""Tests for eigenportfolio returns (spec F)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.pca_rv import eigenportfolio_returns


class TestEigenportfolioReturns:
    def _setup(self, n=300, seed=0):
        rng = np.random.default_rng(seed)
        cols = ["A", "B", "C"]
        loadings = pd.DataFrame(
            [[0.6, -0.5], [0.5, 0.7], [0.6, 0.5]],
            index=cols, columns=["PC1", "PC2"],
        )
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        returns = pd.DataFrame(rng.standard_normal((n, 3)) * 0.01, index=idx, columns=cols)
        vols = pd.Series([0.15, 0.12, 0.18], index=cols)
        return loadings, returns, vols

    def test_shape(self):
        L, R, V = self._setup()
        F = eigenportfolio_returns(L, R, V)
        assert F.shape == (len(R), 2)
        assert list(F.columns) == ["PC1", "PC2"]

    def test_orthogonality_with_pca_loadings(self):
        rng = np.random.default_rng(0)
        n = 2000
        cols = ["A", "B", "C"]
        L_true = np.array([[1.0, -1.0], [1.0, 0.0], [1.0, 1.0]])
        factors = rng.standard_normal((n, 2))
        R = factors @ L_true.T + rng.standard_normal((n, 3)) * 0.01
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        returns = pd.DataFrame(R, index=idx, columns=cols)
        # PCA to get orthogonal loadings
        from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries
        model, _ = fit_curve_pca_from_timeseries(returns, use_changes=False, sort_by_tenor=False)
        loadings = model.loadings[["PC1", "PC2"]]
        vols = returns.std()
        F = eigenportfolio_returns(loadings, returns, vols)
        corr = F.corr().values
        off_diag = abs(corr[0, 1])
        assert off_diag < 0.15, f"Expected near-orthogonal, got corr={off_diag:.3f}"

    def test_manual_computation(self):
        L, R, V = self._setup(n=5)
        F = eigenportfolio_returns(L, R, V)
        for j, pc in enumerate(["PC1", "PC2"]):
            w = L[pc].values / V.values
            expected = R.values @ w
            np.testing.assert_allclose(F[pc].values, expected, atol=1e-10)
