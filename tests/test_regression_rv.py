"""Tests for BT.signals.regression_rv — OLS regression for RV analysis."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.regression_rv import (
    RegressionRVConfig,
    RegressionRVResult,
    rolling_regression,
)


def _make_synthetic_fly(n_days: int = 300, seed: int = 42):
    """Build synthetic fly, body, and curve series with known relationship."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n_days, freq="B")

    body = np.cumsum(rng.normal(0, 0.01, n_days)) + 3.0
    curve = np.cumsum(rng.normal(0, 0.005, n_days))

    # fly = 0.5 * body + 0.3 * curve + mean-reverting noise
    noise = np.zeros(n_days)
    for i in range(1, n_days):
        noise[i] = 0.8 * noise[i - 1] + rng.normal(0, 0.002)
    fly = 0.5 * body + 0.3 * curve + noise

    return (
        pd.Series(fly, index=dates, name="fly"),
        pd.Series(body, index=dates, name="body"),
        pd.Series(curve, index=dates, name="curve"),
    )


class TestRollingRegression:
    def test_output_structure(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        assert isinstance(result, RegressionRVResult)
        assert len(result.residuals) == len(fly)
        assert len(result.betas_body) == len(fly)
        assert len(result.betas_curve) == len(fly)
        assert len(result.rsq) == len(fly)
        assert len(result.zscores) == len(fly)

    def test_residual_small_for_known_relationship(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        valid = result.residuals.dropna()
        # Residuals should be small — the model should capture the linear relationship
        assert valid.abs().median() < 0.01

    def test_rsq_high_for_known_relationship(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        valid_rsq = result.rsq.dropna()
        assert valid_rsq.median() > 0.80

    def test_betas_recover_true_coefficients(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        # True betas: body=0.5, curve=0.3
        valid_body = result.betas_body.dropna()
        valid_curve = result.betas_curve.dropna()
        assert abs(valid_body.median() - 0.5) < 0.15
        assert abs(valid_curve.median() - 0.3) < 0.15

    def test_hedge_ratios_shape(self):
        fly, body, curve = _make_synthetic_fly(300)
        config = RegressionRVConfig(window_days=60)
        result = rolling_regression(fly, body, curve, config)

        assert result.hedge_ratios.shape[1] == 2
        assert list(result.hedge_ratios.columns) == ["left_weight", "right_weight"]
