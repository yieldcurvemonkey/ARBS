"""Tests for BT.signals.regime_filter — traffic light indicator."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.regime_filter import (
    RegimeFilterConfig,
    traffic_light,
)


def _make_stable_betas(n: int = 500, seed: int = 42):
    """Betas with low volatility — should produce green regime."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
    betas_body = pd.Series(0.5 + rng.normal(0, 0.01, n), index=dates)
    betas_curve = pd.Series(0.3 + rng.normal(0, 0.01, n), index=dates)
    return betas_body, betas_curve


def _make_regime_shift_betas(n: int = 500, seed: int = 42):
    """Betas with a regime shift in the middle — should produce red zone."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
    betas_body = np.concatenate([
        0.5 + rng.normal(0, 0.01, n // 2),
        0.5 + rng.normal(0, 0.10, n // 2),  # 10x volatility spike
    ])
    betas_curve = np.concatenate([
        0.3 + rng.normal(0, 0.01, n // 2),
        0.3 + rng.normal(0, 0.10, n // 2),
    ])
    return pd.Series(betas_body, index=dates), pd.Series(betas_curve, index=dates)


class TestTrafficLight:
    def test_output_columns(self):
        bb, bc = _make_stable_betas()
        config = RegimeFilterConfig()
        result = traffic_light(bb, bc, config)

        assert "indicator" in result.columns
        assert "regime" in result.columns
        assert len(result) == len(bb)

    def test_stable_betas_produce_green(self):
        bb, bc = _make_stable_betas()
        config = RegimeFilterConfig(
            beta_vol_window_days=65,
            beta_vol_zscore_window_days=130,
            threshold=3.0,
        )
        result = traffic_light(bb, bc, config)
        valid = result.dropna()
        green_pct = (valid["regime"] == "green").mean()
        assert green_pct > 0.80  # mostly green

    def test_regime_shift_triggers_red(self):
        bb, bc = _make_regime_shift_betas()
        config = RegimeFilterConfig(
            beta_vol_window_days=65,
            beta_vol_zscore_window_days=130,
            threshold=3.0,
        )
        result = traffic_light(bb, bc, config)
        valid = result.dropna()
        # Should have some red periods after the regime shift
        red_count = (valid["regime"] == "red").sum()
        assert red_count > 10

    def test_custom_threshold(self):
        bb, bc = _make_regime_shift_betas()
        low_config = RegimeFilterConfig(threshold=1.0)
        high_config = RegimeFilterConfig(threshold=5.0)
        low_result = traffic_light(bb, bc, low_config)
        high_result = traffic_light(bb, bc, high_config)

        low_red = (low_result["regime"].dropna() == "red").sum()
        high_red = (high_result["regime"].dropna() == "red").sum()
        assert low_red >= high_red  # lower threshold → more red
