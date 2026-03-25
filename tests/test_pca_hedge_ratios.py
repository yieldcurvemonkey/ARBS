"""Tests for BT.signals.pca_hedge_ratios — PCA-implied hedge ratio matrix."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.pca_hedge_ratios import (
    hedge_ratio_matrix,
    portfolio_factor_exposure,
    portfolio_variance_decomposition,
)


def _make_pca_outputs(n_tenors: int = 6):
    """Create synthetic PCA loadings and eigenvalues for testing."""
    tenors = [f"T{i}" for i in range(n_tenors)]
    # Realistic-ish loadings
    pc1 = np.ones(n_tenors) / np.sqrt(n_tenors)  # level
    pc2 = np.linspace(-1, 1, n_tenors)
    pc2 /= np.linalg.norm(pc2)  # slope
    pc3 = np.array([1, -0.5, -1, -0.5, 0.5, 1])[:n_tenors]
    pc3 -= pc3.mean()
    pc3 /= np.linalg.norm(pc3)  # curvature

    loadings = pd.DataFrame(
        np.column_stack([pc1, pc2, pc3]),
        index=tenors,
        columns=["PC1", "PC2", "PC3"],
    )
    eigenvalues = pd.Series([100.0, 10.0, 2.0], index=["PC1", "PC2", "PC3"])
    return loadings, eigenvalues


class TestHedgeRatioMatrix:
    def test_pc1_only_neutralization(self):
        loadings, eigenvalues = _make_pca_outputs()
        hrm = hedge_ratio_matrix(loadings, eigenvalues, neutralize_factors=[1])

        assert hrm.shape == (6, 6)
        # Diagonal should be 1.0 (hedge yourself = 1:1)
        np.testing.assert_allclose(np.diag(hrm.values), 1.0, atol=1e-10)

        # PC1-only: ratio = u1_x / u1_y
        assert abs(hrm.iloc[0, 1] - loadings.iloc[0, 0] / loadings.iloc[1, 0]) < 1e-10

    def test_pc1_pc2_neutralization(self):
        loadings, eigenvalues = _make_pca_outputs()
        hrm = hedge_ratio_matrix(loadings, eigenvalues, neutralize_factors=[1, 2])

        assert hrm.shape == (6, 6)
        np.testing.assert_allclose(np.diag(hrm.values), 1.0, atol=1e-10)

        # Ratios should differ from PC1-only
        hrm1 = hedge_ratio_matrix(loadings, eigenvalues, neutralize_factors=[1])
        assert not np.allclose(hrm.values, hrm1.values)

    def test_symmetry(self):
        """gamma(x,y) * gamma(y,x) should approx 1 for PC1 neutralization."""
        loadings, eigenvalues = _make_pca_outputs()
        hrm = hedge_ratio_matrix(loadings, eigenvalues, neutralize_factors=[1])

        for i in range(6):
            for j in range(6):
                if i != j:
                    assert abs(hrm.iloc[i, j] * hrm.iloc[j, i] - 1.0) < 1e-8


class TestPortfolioFactorExposure:
    def test_exposure_dimensions(self):
        loadings, eigenvalues = _make_pca_outputs()
        positions = pd.Series([10, -20, 30, -10, 5, -15], index=loadings.index)
        exposure = portfolio_factor_exposure(positions, loadings)

        assert len(exposure) == 3
        assert list(exposure.index) == ["PC1", "PC2", "PC3"]

    def test_zero_portfolio_zero_exposure(self):
        loadings, eigenvalues = _make_pca_outputs()
        positions = pd.Series([0, 0, 0, 0, 0, 0], index=loadings.index)
        exposure = portfolio_factor_exposure(positions, loadings)
        np.testing.assert_allclose(exposure.values, 0.0, atol=1e-10)


class TestPortfolioVarianceDecomposition:
    def test_decomposition_sums_to_total(self):
        loadings, eigenvalues = _make_pca_outputs()
        positions = pd.Series([10, -20, 30, -10, 5, -15], index=loadings.index)
        decomp = portfolio_variance_decomposition(positions, loadings, eigenvalues)

        assert "PC1" in decomp
        assert "total" in decomp
        pc_sum = sum(v for k, v in decomp.items() if k != "total")
        assert abs(pc_sum - decomp["total"]) < 1e-6
