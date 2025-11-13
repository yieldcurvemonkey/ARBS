# ABOUTME: Comprehensive tests for VolatilityRatioCalculator
# ABOUTME: Tests RV calculation, IV/RV ratios, edge cases, and time-series handling
"""
Tests for VolatilityRatioCalculator

Tests:
- RV calculation matches manual computation
- IV/RV ratio calculation correct
- Edge cases (zero vol, missing data, NaN handling)
- Multiple assets handling
- Time-series with rolling windows
"""

import pytest
import polars as pl
import numpy as np
from datetime import date, timedelta


# TDD: Write tests BEFORE implementation
class TestVolatilityRatioCalculatorBasic:
    """Test basic RV and IV/RV ratio calculations."""

    def test_rv_calculation_manual_verification(self):
        """RV calculation should match manual computation."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        # Create simple returns data
        dates = [date(2024, 1, i) for i in range(1, 21)]
        returns = [0.01, -0.01, 0.02, -0.02, 0.01, -0.01, 0.02, -0.02, 0.01, -0.01,
                   0.01, -0.01, 0.02, -0.02, 0.01, -0.01, 0.02, -0.02, 0.01, -0.01]

        df = pl.DataFrame({
            'date': dates,
            'ticker': ['AAPL'] * 20,
            'return': returns
        })

        # Calculate RV using calculator
        calc = VolatilityRatioCalculator(lookback=20, annualization=252)
        result = calc.calculate_realized_volatility(df)

        # Manual calculation
        manual_std = np.std(returns, ddof=1)
        manual_rv = manual_std * np.sqrt(252)

        # Verify
        assert 'RV' in result.columns
        rv_value = result.filter(pl.col('ticker') == 'AAPL')['RV'][0]
        assert abs(rv_value - manual_rv) < 1e-10

    def test_iv_rv_ratio_correct(self):
        """IV/RV ratio should be IV divided by RV."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        # Create returns data
        df = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 31)],
            'ticker': ['AAPL'] * 30,
            'return': np.random.normal(0, 0.01, 30)
        })

        # Implied vols
        implied_vols = {'AAPL': 0.25}

        # Calculate ratios
        calc = VolatilityRatioCalculator(lookback=30)
        result = calc.calculate_ratios(df, implied_vols)

        # Verify structure
        assert 'ticker' in result.columns
        assert 'date' in result.columns
        assert 'RV' in result.columns
        assert 'IV' in result.columns
        assert 'IV_RV_ratio' in result.columns

        # Verify ratio = IV / RV
        row = result.filter(pl.col('ticker') == 'AAPL').row(0, named=True)
        expected_ratio = row['IV'] / row['RV']
        assert abs(row['IV_RV_ratio'] - expected_ratio) < 1e-10

    def test_multiple_assets(self):
        """Should handle multiple assets correctly."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        # Create data for 3 assets
        dates = [date(2024, 1, i) for i in range(1, 31)]
        df = pl.DataFrame({
            'date': dates * 3,
            'ticker': ['AAPL'] * 30 + ['MSFT'] * 30 + ['GOOGL'] * 30,
            'return': list(np.random.normal(0, 0.01, 30)) +
                      list(np.random.normal(0, 0.02, 30)) +
                      list(np.random.normal(0, 0.015, 30))
        })

        implied_vols = {'AAPL': 0.20, 'MSFT': 0.30, 'GOOGL': 0.25}

        calc = VolatilityRatioCalculator(lookback=30)
        result = calc.calculate_ratios(df, implied_vols)

        # Should have 3 rows (one per asset)
        assert result.height == 3

        # Each asset should have its own IV
        for ticker, iv in implied_vols.items():
            ticker_row = result.filter(pl.col('ticker') == ticker).row(0, named=True)
            assert ticker_row['IV'] == iv


class TestVolatilityRatioCalculatorEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_volatility(self):
        """Handle zero volatility (all returns equal)."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        # All returns are zero
        df = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 31)],
            'ticker': ['AAPL'] * 30,
            'return': [0.0] * 30
        })

        implied_vols = {'AAPL': 0.20}

        calc = VolatilityRatioCalculator(lookback=30)
        result = calc.calculate_ratios(df, implied_vols)

        # RV should be close to zero
        rv = result.filter(pl.col('ticker') == 'AAPL')['RV'][0]
        assert rv < 1e-10

        # IV/RV ratio should be inf or handled gracefully
        ratio = result.filter(pl.col('ticker') == 'AAPL')['IV_RV_ratio'][0]
        assert np.isinf(ratio) or np.isnan(ratio)

    def test_missing_implied_vol(self):
        """Handle missing implied vol for an asset."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        df = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 31)],
            'ticker': ['AAPL'] * 30,
            'return': np.random.normal(0, 0.01, 30)
        })

        # No implied vol for AAPL
        implied_vols = {'MSFT': 0.25}

        calc = VolatilityRatioCalculator(lookback=30)
        result = calc.calculate_ratios(df, implied_vols)

        # Should still calculate RV, but IV and ratio should be None or NaN
        assert result.height == 1
        row = result.row(0, named=True)
        assert row['RV'] > 0
        assert row['IV'] is None or np.isnan(row['IV'])

    def test_nan_in_returns(self):
        """Handle NaN values in returns."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        returns = np.random.normal(0, 0.01, 30)
        returns[5] = np.nan
        returns[15] = np.nan

        df = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 31)],
            'ticker': ['AAPL'] * 30,
            'return': returns
        })

        implied_vols = {'AAPL': 0.25}

        calc = VolatilityRatioCalculator(lookback=30)
        result = calc.calculate_ratios(df, implied_vols)

        # Should handle NaN gracefully (either skip or calculate with valid values)
        assert result.height == 1
        rv = result.filter(pl.col('ticker') == 'AAPL')['RV'][0]
        # RV should be positive (calculated from non-NaN values)
        assert rv > 0

    def test_insufficient_data(self):
        """Handle case with insufficient data for lookback."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        # Only 5 data points with lookback=30
        df = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 6)],
            'ticker': ['AAPL'] * 5,
            'return': [0.01, -0.01, 0.02, -0.02, 0.01]
        })

        implied_vols = {'AAPL': 0.25}

        calc = VolatilityRatioCalculator(lookback=30)
        result = calc.calculate_ratios(df, implied_vols)

        # Should either use all available data or return NaN
        assert result.height <= 1
        if result.height == 1:
            rv = result.filter(pl.col('ticker') == 'AAPL')['RV'][0]
            # Should be either NaN or calculated from available data
            assert rv > 0 or np.isnan(rv)


class TestVolatilityRatioCalculatorTimeSeries:
    """Test time-series calculations with rolling windows."""

    def test_rolling_window_calculation(self):
        """Calculate RV over rolling windows."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        # Create 60 days of data
        np.random.seed(42)
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(60)]
        returns = np.random.normal(0, 0.01, 60)

        df = pl.DataFrame({
            'date': dates,
            'ticker': ['AAPL'] * 60,
            'return': returns
        })

        implied_vols = {'AAPL': 0.25}

        # Calculate with 30-day lookback
        calc = VolatilityRatioCalculator(lookback=30)
        result = calc.calculate_ratios_timeseries(df, implied_vols)

        # Should have multiple rows (one per valid date after lookback)
        assert result.height >= 30

        # RV should vary over time (not constant)
        rv_values = result['RV'].to_list()
        assert len(set(rv_values)) > 1

    def test_timeseries_preserves_dates(self):
        """Time-series calculation should preserve date order."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(40)]
        df = pl.DataFrame({
            'date': dates,
            'ticker': ['AAPL'] * 40,
            'return': np.random.normal(0, 0.01, 40)
        })

        implied_vols = {'AAPL': 0.25}

        calc = VolatilityRatioCalculator(lookback=20)
        result = calc.calculate_ratios_timeseries(df, implied_vols)

        # Dates should be in order
        dates_result = result['date'].to_list()
        assert dates_result == sorted(dates_result)

        # Should start from date where lookback is satisfied
        assert dates_result[0] >= dates[19]


class TestVolatilityRatioCalculatorAnnualization:
    """Test different annualization factors."""

    def test_daily_annualization(self):
        """Test with daily data (252 trading days)."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        df = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 31)],
            'ticker': ['AAPL'] * 30,
            'return': np.random.normal(0, 0.01, 30)
        })

        calc = VolatilityRatioCalculator(lookback=30, annualization=252)
        result = calc.calculate_realized_volatility(df)

        rv = result.filter(pl.col('ticker') == 'AAPL')['RV'][0]

        # RV should be reasonable for daily data (0.05 to 0.50)
        assert 0.01 < rv < 1.0

    def test_weekly_annualization(self):
        """Test with weekly data (52 weeks)."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        df = pl.DataFrame({
            'date': [date(2024, 1, 1) + timedelta(weeks=i) for i in range(30)],
            'ticker': ['AAPL'] * 30,
            'return': np.random.normal(0, 0.02, 30)
        })

        calc = VolatilityRatioCalculator(lookback=30, annualization=52)
        result = calc.calculate_realized_volatility(df)

        rv = result.filter(pl.col('ticker') == 'AAPL')['RV'][0]

        # RV should be reasonable for weekly data
        assert 0.01 < rv < 1.0

    def test_custom_annualization_factor(self):
        """Test with custom annualization factor."""
        from Risk.Volatility.VolatilityRatioCalculator import VolatilityRatioCalculator

        returns = [0.01, -0.01, 0.02, -0.02, 0.01, -0.01, 0.02, -0.02, 0.01, -0.01]
        df = pl.DataFrame({
            'date': [date(2024, 1, i) for i in range(1, 11)],
            'ticker': ['AAPL'] * 10,
            'return': returns
        })

        # Calculate with different annualization factors
        calc_252 = VolatilityRatioCalculator(lookback=10, annualization=252)
        result_252 = calc_252.calculate_realized_volatility(df)
        rv_252 = result_252['RV'][0]

        calc_100 = VolatilityRatioCalculator(lookback=10, annualization=100)
        result_100 = calc_100.calculate_realized_volatility(df)
        rv_100 = result_100['RV'][0]

        # Ratio should equal sqrt(252/100)
        expected_ratio = np.sqrt(252 / 100)
        actual_ratio = rv_252 / rv_100
        assert abs(actual_ratio - expected_ratio) < 1e-6
