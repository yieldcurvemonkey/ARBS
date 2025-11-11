# ABOUTME: Tests for TearSheet analysis generating performance metrics and plots
# ABOUTME: Validates summary statistics, drawdowns, and visualization outputs
"""
Tests for TearSheet

Validates:
- Summary statistics (total return, Sharpe, max drawdown)
- Drawdown calculation
- Cumulative returns
- Monthly/annual aggregation
- Edge cases (empty returns, single period)
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta

from Analysis.TearSheet import TearSheet, TearSheetMetrics


class TestTearSheetMetrics:
    """Test tear sheet metrics calculation."""

    def test_can_import_tear_sheet(self):
        """Can import TearSheet and TearSheetMetrics."""
        assert TearSheet is not None
        assert TearSheetMetrics is not None

    def test_total_return_calculation(self):
        """Calculate total return from series."""
        returns = pl.Series([0.01, 0.02, -0.01, 0.03])

        tear_sheet = TearSheet(returns)
        metrics = tear_sheet.calculate_metrics()

        # Total return = (1.01 × 1.02 × 0.99 × 1.03) - 1
        expected_total = (1.01 * 1.02 * 0.99 * 1.03) - 1
        assert metrics.total_return == pytest.approx(expected_total, rel=1e-6)

    def test_sharpe_ratio_calculation(self):
        """Calculate Sharpe ratio."""
        # Use fixed seed for reproducibility
        np.random.seed(42)
        # Weekly returns with positive mean
        returns = pl.Series(np.random.randn(52) * 0.02 + 0.001)

        tear_sheet = TearSheet(returns, periods_per_year=52)
        metrics = tear_sheet.calculate_metrics()

        # Sharpe = (mean / std) × √52
        expected_sharpe = (returns.mean() / returns.std()) * np.sqrt(52)
        assert metrics.sharpe_ratio == pytest.approx(expected_sharpe, rel=1e-3)

    def test_max_drawdown_calculation(self):
        """Calculate maximum drawdown."""
        # Returns that create a drawdown
        returns = pl.Series([0.10, 0.05, -0.15, -0.10, 0.05, 0.08])

        tear_sheet = TearSheet(returns)
        metrics = tear_sheet.calculate_metrics()

        # Cumulative: 1.10, 1.155, 0.98175, 0.88358, 0.92776, 1.00198
        # Peak: 1.155, Trough: 0.88358
        # Drawdown: (0.88358 - 1.155) / 1.155 = -0.235
        assert metrics.max_drawdown < -0.20  # At least 20% drawdown
        assert metrics.max_drawdown > -0.30  # Not more than 30%

    def test_annualized_return(self):
        """Calculate annualized return."""
        # Use fixed seed for reproducibility
        np.random.seed(42)
        # 252 daily returns averaging 0.1% per day
        returns = pl.Series(np.random.randn(252) * 0.01 + 0.001)

        tear_sheet = TearSheet(returns, periods_per_year=252)
        metrics = tear_sheet.calculate_metrics()

        # With random returns, should be positive on average
        assert metrics.annual_return > 0

    def test_volatility_calculation(self):
        """Calculate annualized volatility."""
        returns = pl.Series(np.random.randn(252) * 0.02)

        tear_sheet = TearSheet(returns, periods_per_year=252)
        metrics = tear_sheet.calculate_metrics()

        # Vol = std × √252
        expected_vol = returns.std() * np.sqrt(252)
        assert metrics.annual_volatility == pytest.approx(expected_vol, rel=1e-4)

    def test_calmar_ratio(self):
        """Calculate Calmar ratio (return / max drawdown)."""
        returns = pl.Series([0.10, 0.05, -0.15, 0.20, 0.10])

        tear_sheet = TearSheet(returns, periods_per_year=52)
        metrics = tear_sheet.calculate_metrics()

        # Calmar = annual_return / abs(max_drawdown)
        expected_calmar = metrics.annual_return / abs(metrics.max_drawdown)
        assert metrics.calmar_ratio == pytest.approx(expected_calmar, rel=1e-6)


class TestDrawdownCalculation:
    """Test drawdown calculation."""

    def test_no_drawdown_for_positive_returns(self):
        """No drawdown if returns are always positive."""
        returns = pl.Series([0.01, 0.02, 0.01, 0.03])

        tear_sheet = TearSheet(returns)
        drawdowns = tear_sheet.calculate_drawdowns()

        # Last drawdown should be 0 (at new peak)
        assert drawdowns[-1] == pytest.approx(0.0)

    def test_drawdown_series(self):
        """Drawdown series tracks distance from peak."""
        returns = pl.Series([0.10, -0.05, -0.05, 0.05])

        tear_sheet = TearSheet(returns)
        drawdowns = tear_sheet.calculate_drawdowns()

        # After 0.10: at peak, drawdown = 0
        # After -0.05: (1.045 - 1.10) / 1.10 = -0.05
        # After -0.05: (0.9928 - 1.10) / 1.10 = -0.0975
        # After 0.05: (1.0424 - 1.10) / 1.10 = -0.0523
        assert drawdowns[0] == pytest.approx(0.0)
        assert drawdowns[1] < 0
        assert drawdowns[2] < drawdowns[1]  # Deeper drawdown

    def test_recovery_from_drawdown(self):
        """Drawdown returns to 0 after recovery to new peak."""
        returns = pl.Series([0.10, -0.10, 0.11])

        tear_sheet = TearSheet(returns)
        drawdowns = tear_sheet.calculate_drawdowns()

        # After 0.11 return, should be back at peak
        # (Exact recovery depends on compounding)
        assert drawdowns[-1] > -0.01  # Nearly recovered


class TestCumulativeReturns:
    """Test cumulative returns calculation."""

    def test_cumulative_returns_from_zero(self):
        """Cumulative returns - first value is first return."""
        returns = pl.Series([0.01, 0.02, 0.01])

        tear_sheet = TearSheet(returns)
        cum_returns = tear_sheet.calculate_cumulative_returns()

        # First cumulative return equals first return
        assert cum_returns[0] == pytest.approx(0.01)

    def test_cumulative_returns_compounding(self):
        """Cumulative returns compound correctly."""
        returns = pl.Series([0.10, 0.10])

        tear_sheet = TearSheet(returns)
        cum_returns = tear_sheet.calculate_cumulative_returns()

        # After first return: 0.10 (10%)
        # After second: 1.10 × 1.10 - 1 = 0.21 (21%)
        assert cum_returns[0] == pytest.approx(0.10)
        assert cum_returns[1] == pytest.approx(0.21)

    def test_negative_cumulative_returns(self):
        """Cumulative returns can be negative."""
        returns = pl.Series([-0.10, -0.10])

        tear_sheet = TearSheet(returns)
        cum_returns = tear_sheet.calculate_cumulative_returns()

        # After two -10% returns: 0.9 × 0.9 - 1 = -0.19
        assert cum_returns[-1] < 0
        assert cum_returns[-1] == pytest.approx(-0.19)


class TestMonthlyAnnualAggregation:
    """Test monthly and annual return aggregation."""

    def test_monthly_returns_aggregation(self):
        """Aggregate daily returns to monthly."""
        # Create daily returns for 2 months
        dates = pl.date_range(date(2024, 1, 1), date(2024, 2, 29), interval='1d', eager=True)
        returns = pl.Series(np.random.randn(len(dates)) * 0.01)

        tear_sheet = TearSheet(returns, dates=dates)
        monthly = tear_sheet.aggregate_monthly_returns()

        # Should have 2 months
        assert len(monthly) == 2

    def test_annual_returns_aggregation(self):
        """Aggregate daily returns to annual."""
        # Create daily returns for 2 years
        dates = pl.date_range(date(2023, 1, 1), date(2024, 12, 31), interval='1d', eager=True)
        returns = pl.Series(np.random.randn(len(dates)) * 0.01)

        tear_sheet = TearSheet(returns, dates=dates)
        annual = tear_sheet.aggregate_annual_returns()

        # Should have 2 years
        assert len(annual) == 2


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_empty_returns_series(self):
        """Handle empty returns series."""
        returns = pl.Series(values=[], dtype=pl.Float64)

        tear_sheet = TearSheet(returns)
        metrics = tear_sheet.calculate_metrics()

        # Should return NaN for all metrics
        assert np.isnan(metrics.total_return)
        assert np.isnan(metrics.sharpe_ratio)

    def test_single_return(self):
        """Handle single return."""
        returns = pl.Series([0.05])

        tear_sheet = TearSheet(returns)
        metrics = tear_sheet.calculate_metrics()

        # Total return should be the single return
        assert metrics.total_return == pytest.approx(0.05)
        # Sharpe should be NaN or 0 (can't calculate std from 1 point)
        assert np.isnan(metrics.sharpe_ratio) or metrics.sharpe_ratio == 0

    def test_all_zero_returns(self):
        """Handle all zero returns."""
        returns = pl.Series([0.0, 0.0, 0.0, 0.0])

        tear_sheet = TearSheet(returns)
        metrics = tear_sheet.calculate_metrics()

        assert metrics.total_return == pytest.approx(0.0)
        assert metrics.max_drawdown == pytest.approx(0.0)
        # Sharpe is undefined (0 / 0)
        assert np.isnan(metrics.sharpe_ratio) or metrics.sharpe_ratio == 0

    def test_constant_positive_returns(self):
        """Handle constant positive returns."""
        returns = pl.Series([0.01, 0.01, 0.01, 0.01])

        tear_sheet = TearSheet(returns)
        metrics = tear_sheet.calculate_metrics()

        # Total return = (1.01^4) - 1
        expected_total = (1.01 ** 4) - 1
        assert metrics.total_return == pytest.approx(expected_total)
        # Max drawdown should be 0 (always at peak)
        assert metrics.max_drawdown == pytest.approx(0.0)
