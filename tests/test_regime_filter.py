"""Tests for BT.signals.regime_filter — traffic light indicator."""

import numpy as np
import pandas as pd
import pytest

from BT.signals.regime_filter import RegimeFilterConfig, traffic_light


def _make_stable_betas(n: int = 500, seed: int = 42):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
    betas_body = pd.Series(0.5 + rng.normal(0, 0.01, n), index=dates)
    betas_curve = pd.Series(0.3 + rng.normal(0, 0.01, n), index=dates)
    return betas_body, betas_curve


def _make_regime_shift_betas(n: int = 500, seed: int = 42):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n, freq="B")
    betas_body = np.concatenate([
        0.5 + rng.normal(0, 0.01, n // 2),
        0.5 + rng.normal(0, 0.10, n // 2),
    ])
    betas_curve = np.concatenate([
        0.3 + rng.normal(0, 0.01, n // 2),
        0.3 + rng.normal(0, 0.10, n // 2),
    ])
    return pd.Series(betas_body, index=dates), pd.Series(betas_curve, index=dates)


class TestTrafficLight:
    def test_output_columns(self):
        bb, bc = _make_stable_betas()
        result = traffic_light(bb, bc, RegimeFilterConfig())
        assert "indicator" in result.columns
        assert "regime" in result.columns

    def test_stable_betas_produce_green(self):
        bb, bc = _make_stable_betas()
        result = traffic_light(bb, bc, RegimeFilterConfig())
        valid = result.dropna()
        assert (valid["regime"] == "green").mean() > 0.80

    def test_regime_shift_triggers_red(self):
        bb, bc = _make_regime_shift_betas()
        result = traffic_light(bb, bc, RegimeFilterConfig())
        assert (result["regime"].dropna() == "red").sum() > 10

    def test_custom_threshold(self):
        bb, bc = _make_regime_shift_betas()
        low = traffic_light(bb, bc, RegimeFilterConfig(threshold=1.0))
        high = traffic_light(bb, bc, RegimeFilterConfig(threshold=5.0))
        assert (low["regime"].dropna() == "red").sum() >= (high["regime"].dropna() == "red").sum()
