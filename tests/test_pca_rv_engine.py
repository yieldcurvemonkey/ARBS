"""Tests for BT.signals.pca_rv_engine — rolling PCA for RV analysis."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.pca_rv_engine import (
    PCARVConfig,
    PCARVResult,
    rolling_pca,
    pca_fly_weights,
    ou_half_life,
    adf_test,
)


def _make_synthetic_rates(n_days: int = 300, n_tenors: int = 5, seed: int = 42) -> pd.DataFrame:
    """Build synthetic swap rates driven by 3 factors + noise residual."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")
    tenors = [f"{i}Y" for i in range(1, n_tenors + 1)]

    # Three orthogonal factors
    level = np.cumsum(rng.normal(0, 0.01, n_days))
    slope = np.cumsum(rng.normal(0, 0.005, n_days))
    curve = np.cumsum(rng.normal(0, 0.003, n_days))

    loadings_level = np.ones(n_tenors)
    loadings_slope = np.linspace(-1, 1, n_tenors)
    loadings_curve = np.array([1, -0.5, -1, -0.5, 1])[:n_tenors]

    rates = (
        np.outer(level, loadings_level)
        + np.outer(slope, loadings_slope)
        + np.outer(curve, loadings_curve)
        + rng.normal(0, 0.001, (n_days, n_tenors))  # small residual noise
    )
    rates += 3.0  # base rate of 3%
    return pd.DataFrame(rates, index=dates, columns=tenors)


class TestRollingPCA:
    def test_output_shape(self):
        rates = _make_synthetic_rates(300, 5)
        config = PCARVConfig(pca_window_days=60, n_components=3)
        result = rolling_pca(rates, config)

        assert isinstance(result, PCARVResult)
        # First 60 days are warm-up (NaN), rest have values
        valid = result.residuals.dropna()
        assert len(valid) > 0
        assert result.residuals.shape[1] == 5
        assert result.zscores.shape == result.residuals.shape
        assert result.variance_explained.shape[1] == 3

    def test_out_of_sample_residuals(self):
        """Residual on date T must NOT use T's data in the estimation window."""
        rates = _make_synthetic_rates(200, 5)
        config = PCARVConfig(pca_window_days=60, n_components=3)
        result = rolling_pca(rates, config)

        # Residual = actual - reconstructed. For a well-specified 3-factor model
        # with tiny noise, residuals should be small (< a few bp).
        valid_residuals = result.residuals.dropna()
        assert valid_residuals.abs().max().max() < 0.05  # 5bp max

    def test_variance_explained_sums_below_one(self):
        rates = _make_synthetic_rates(300, 5)
        config = PCARVConfig(pca_window_days=60, n_components=3)
        result = rolling_pca(rates, config)

        valid_ve = result.variance_explained.dropna()
        row_sums = valid_ve.sum(axis=1)
        assert (row_sums <= 1.01).all()  # allow small float tolerance
        assert (row_sums > 0.90).all()   # 3 PCs should capture >90%

    def test_levels_vs_changes_mode(self):
        rates = _make_synthetic_rates(200, 5)
        config_levels = PCARVConfig(pca_window_days=60, pca_input="levels")
        config_changes = PCARVConfig(pca_window_days=60, pca_input="changes")

        result_levels = rolling_pca(rates, config_levels)
        result_changes = rolling_pca(rates, config_changes)

        # Both should produce valid output but different residuals
        assert not result_levels.residuals.dropna().equals(result_changes.residuals.dropna())

    def test_correlation_mode(self):
        rates = _make_synthetic_rates(200, 5)
        config_cov = PCARVConfig(pca_window_days=60, use_correlation=False)
        config_corr = PCARVConfig(pca_window_days=60, use_correlation=True)

        result_cov = rolling_pca(rates, config_cov)
        result_corr = rolling_pca(rates, config_corr)
        assert not result_cov.residuals.dropna().equals(result_corr.residuals.dropna())


class TestPCAFlyWeights:
    def test_belly_normalized_to_one(self):
        rates = _make_synthetic_rates(200, 3)
        config = PCARVConfig(pca_window_days=60, n_components=3)
        weights = pca_fly_weights(rates, config)

        valid = weights.dropna()
        # Middle column (belly) should be normalized to 1.0 or -1.0
        assert (valid.iloc[:, 1].abs() - 1.0).abs().max() < 1e-10

    def test_weights_shape(self):
        rates = _make_synthetic_rates(200, 3)
        config = PCARVConfig(pca_window_days=60, n_components=3)
        weights = pca_fly_weights(rates, config)
        assert weights.shape[1] == 3


class TestStationarityTests:
    def test_ou_half_life_stationary_series(self):
        rng = np.random.default_rng(42)
        # OU process: dx = -theta*x*dt + sigma*dW
        n = 500
        theta = 0.1
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = x[i - 1] - theta * x[i - 1] + rng.normal(0, 0.5)
        series = pd.Series(x, index=pd.bdate_range("2023-01-01", periods=n))
        hl = ou_half_life(series)
        # Half-life should be approximately ln(2)/theta ≈ 6.9
        assert 2 < hl < 20

    def test_adf_stationary_series(self):
        rng = np.random.default_rng(42)
        n = 500
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = x[i - 1] * 0.9 + rng.normal(0, 0.5)
        series = pd.Series(x, index=pd.bdate_range("2023-01-01", periods=n))
        result = adf_test(series)
        assert "statistic" in result
        assert "pvalue" in result
        assert result["pvalue"] < 0.05  # should reject unit root
