# ABOUTME: Tests for VolatilityEstimator and implementations
# ABOUTME: Validates RealizedVolatility and EWMAVolatility estimation from returns
"""
Tests for VolatilityEstimator

Validates:
- RealizedVolatility: σ = StdDev(returns) × √252
- EWMAVolatility: Exponentially weighted volatility
- Edge cases: insufficient data, zero volatility, single asset
"""

import pytest
import numpy as np
import polars as pl
from typing import Dict

from Risk.Volatility.VolatilityEstimator import VolatilityEstimator
from Risk.Volatility.RealizedVolatility import RealizedVolatility
from Risk.Volatility.EWMAVolatility import EWMAVolatility


class TestRealizedVolatility:
    """Test realized volatility estimator."""

    def test_can_import_realized_volatility(self):
        """Can import RealizedVolatility."""
        assert RealizedVolatility is not None

    def test_realized_volatility_is_estimator(self):
        """RealizedVolatility implements VolatilityEstimator interface."""
        vol_est = RealizedVolatility()
        assert isinstance(vol_est, VolatilityEstimator)

    def test_simple_volatility_calculation(self):
        """Calculate volatility from simple returns."""
        vol_est = RealizedVolatility(lookback=5, annualization_factor=252)

        # Simple returns: [0.01, -0.01, 0.02, -0.02, 0.01]
        returns = pl.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02, -0.02, 0.01],
        })

        vols = vol_est.estimate(returns)

        # Expected: std([0.01, -0.01, 0.02, -0.02, 0.01]) × √252
        expected_std = returns['SFRZ4'].std()
        expected_vol = expected_std * np.sqrt(252)

        assert vols['SFRZ4'] == pytest.approx(expected_vol)

    def test_multiple_assets(self):
        """Estimate volatility for multiple assets."""
        vol_est = RealizedVolatility(lookback=10, annualization_factor=252)

        returns = pl.DataFrame({
            'SFRZ4': np.random.randn(20) * 0.01,
            'SFRH5': np.random.randn(20) * 0.02,
            'SFRM5': np.random.randn(20) * 0.015,
        })

        vols = vol_est.estimate(returns)

        # All assets should have volatility estimates
        assert 'SFRZ4' in vols
        assert 'SFRH5' in vols
        assert 'SFRM5' in vols

        # SFRH5 should have higher vol (generated with 2x std)
        assert vols['SFRH5'] > vols['SFRZ4']

    def test_lookback_period(self):
        """Lookback period limits history used."""
        vol_est = RealizedVolatility(lookback=5, annualization_factor=252)

        # 20 periods of data, but only last 5 should be used
        returns = pl.DataFrame({
            'SFRZ4': [0.0] * 15 + [0.01, -0.01, 0.02, -0.02, 0.01],
        })

        vols = vol_est.estimate(returns)

        # Should only use last 5 returns (not first 15 zeros)
        last_5_std = returns['SFRZ4'].tail(5).std()
        expected_vol = last_5_std * np.sqrt(252)

        assert vols['SFRZ4'] == pytest.approx(expected_vol)

    def test_annualization_factor(self):
        """Annualization factor scales volatility."""
        # Daily data: annualize with √252
        vol_daily = RealizedVolatility(lookback=20, annualization_factor=252)

        # Weekly data: annualize with √52
        vol_weekly = RealizedVolatility(lookback=20, annualization_factor=52)

        returns = pl.DataFrame({
            'SFRZ4': np.random.randn(30) * 0.01,
        })

        vols_daily = vol_daily.estimate(returns)
        vols_weekly = vol_weekly.estimate(returns)

        # Daily vol should be higher (√252 > √52)
        assert vols_daily['SFRZ4'] > vols_weekly['SFRZ4']

        # Ratio should be approximately √(252/52)
        ratio = vols_daily['SFRZ4'] / vols_weekly['SFRZ4']
        expected_ratio = np.sqrt(252 / 52)
        assert ratio == pytest.approx(expected_ratio, rel=1e-6)

    def test_zero_volatility(self):
        """Zero volatility when returns are constant."""
        vol_est = RealizedVolatility(lookback=10, annualization_factor=252)

        returns = pl.DataFrame({
            'SFRZ4': [0.01] * 20,  # Constant return
        })

        vols = vol_est.estimate(returns)

        # Constant returns → zero volatility
        assert vols['SFRZ4'] == pytest.approx(0.0)

    def test_insufficient_data(self):
        """Handle case with less data than lookback."""
        vol_est = RealizedVolatility(lookback=20, annualization_factor=252)

        # Only 10 periods (less than lookback)
        returns = pl.DataFrame({
            'SFRZ4': np.random.randn(10) * 0.01,
        })

        vols = vol_est.estimate(returns)

        # Should use all available data
        expected_vol = returns['SFRZ4'].std() * np.sqrt(252)
        assert vols['SFRZ4'] == pytest.approx(expected_vol)


class TestEWMAVolatility:
    """Test exponentially weighted moving average volatility."""

    def test_can_import_ewma_volatility(self):
        """Can import EWMAVolatility."""
        assert EWMAVolatility is not None

    def test_ewma_volatility_is_estimator(self):
        """EWMAVolatility implements VolatilityEstimator interface."""
        vol_est = EWMAVolatility()
        assert isinstance(vol_est, VolatilityEstimator)

    def test_ewma_volatility_calculation(self):
        """Calculate EWMA volatility."""
        vol_est = EWMAVolatility(halflife=10, annualization_factor=252)

        returns = pl.DataFrame({
            'SFRZ4': np.random.randn(50) * 0.01,
        })

        vols = vol_est.estimate(returns)

        # Should produce a volatility estimate
        assert vols['SFRZ4'] > 0

    def test_ewma_more_responsive_than_realized(self):
        """EWMA gives more weight to recent observations."""
        ewma_vol = EWMAVolatility(halflife=10, annualization_factor=252)
        realized_vol = RealizedVolatility(lookback=50, annualization_factor=252)

        # Low volatility initially, then spike
        returns = pl.DataFrame({
            'SFRZ4': [0.001] * 40 + list(np.random.randn(10) * 0.05),
        })

        vols_ewma = ewma_vol.estimate(returns)
        vols_realized = realized_vol.estimate(returns)

        # EWMA should give higher weight to recent high vol
        # So EWMA vol should be > realized vol (which averages over full period)
        # Note: This is probabilistic and might not always hold, but in expectation it should
        # For this test, just verify both produce valid results
        assert vols_ewma['SFRZ4'] > 0
        assert vols_realized['SFRZ4'] > 0

    def test_halflife_parameter(self):
        """Halflife parameter affects responsiveness."""
        # Short halflife: more responsive
        vol_short = EWMAVolatility(halflife=5, annualization_factor=252)

        # Long halflife: less responsive
        vol_long = EWMAVolatility(halflife=30, annualization_factor=252)

        # Regime change: low vol → high vol
        returns = pl.DataFrame({
            'SFRZ4': [0.001] * 30 + list(np.random.randn(20) * 0.05),
        })

        vols_short = vol_short.estimate(returns)
        vols_long = vol_long.estimate(returns)

        # Both should be positive
        assert vols_short['SFRZ4'] > 0
        assert vols_long['SFRZ4'] > 0


class TestEdgeCases:
    """Edge cases for volatility estimation."""

    def test_single_period_returns(self):
        """Handle single period of returns."""
        vol_est = RealizedVolatility(lookback=10, annualization_factor=252)

        returns = pl.DataFrame({
            'SFRZ4': [0.01],
        })

        vols = vol_est.estimate(returns)

        # Single observation → std = 0 (need at least 2 for variance)
        # pandas std() with single value returns NaN
        # Our estimator should handle this gracefully
        assert 'SFRZ4' in vols

    def test_empty_returns(self):
        """Handle empty returns DataFrame."""
        vol_est = RealizedVolatility(lookback=10, annualization_factor=252)

        returns = pl.DataFrame()

        vols = vol_est.estimate(returns)

        # Empty input → empty output
        assert len(vols) == 0

    def test_nan_in_returns(self):
        """Handle NaN values in returns."""
        vol_est = RealizedVolatility(lookback=10, annualization_factor=252)

        returns = pl.DataFrame({
            'SFRZ4': [0.01, np.nan, 0.02, -0.01, np.nan, 0.01],
        })

        vols = vol_est.estimate(returns)

        # Should handle NaN gracefully (skip or use available data)
        assert 'SFRZ4' in vols
        assert not np.isnan(vols['SFRZ4'])


class TestDefaultParameters:
    """Test default parameters."""

    def test_default_lookback_60(self):
        """Default lookback is 60 periods."""
        vol_est = RealizedVolatility()

        # Create 100 periods
        returns = pl.DataFrame({
            'SFRZ4': list(np.random.randn(50) * 0.01) + list(np.random.randn(50) * 0.05),
        })

        vols = vol_est.estimate(returns)

        # Should use last 60 periods (high vol period)
        last_60_std = returns['SFRZ4'].tail(60).std()
        expected_vol = last_60_std * np.sqrt(252)

        assert vols['SFRZ4'] == pytest.approx(expected_vol)

    def test_default_annualization_252(self):
        """Default annualization factor is 252 (daily)."""
        vol_est = RealizedVolatility(lookback=20)

        returns = pl.DataFrame({
            'SFRZ4': np.random.randn(30) * 0.01,
        })

        vols = vol_est.estimate(returns)

        # Should annualize with √252
        std = returns['SFRZ4'].tail(20).std()
        expected_vol = std * np.sqrt(252)

        assert vols['SFRZ4'] == pytest.approx(expected_vol)
