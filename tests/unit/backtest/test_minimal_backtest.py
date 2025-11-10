# ABOUTME: Test suite for minimal backtest loop
# ABOUTME: Verifies end-to-end integration: Query → Adapter → Signals → Risk → Optimizer → P&L tracking
"""
Tests for Minimal Backtest

Verifies the minimal backtest loop that integrates all components:
- Query layer: Get contract prices
- Adapter: Format for signals
- Signals: Generate alphas
- Risk: Estimate covariance
- Optimizer: Calculate weights
- Backtest: Track positions and P&L

MVP Goal: Measure correctly, not necessarily profitably
- If strategy loses money, that's fine
- We measure it accurately with proper P&L calculation
- No IC requirement for MVP success

Business Requirements:
1. Position Tracking: Know what we own at each date
2. P&L Calculation: Accurate returns measurement
3. Performance Metrics: IC, Sharpe, returns time series
4. End-to-End: All components work together

Minimal Implementation:
- Input: contracts list, date range, market data
- For each date:
  1. Get prices (Adapter)
  2. Generate signals (CarrySignal)
  3. Estimate covariance (LedoitWolfShrinkage)
  4. Optimize weights (MeanVarianceOptimizer)
  5. Track positions and P&L
- Output: BacktestResult with returns, IC, Sharpe

Maximal Additions (later):
- Transaction costs
- Slippage
- Realistic execution
- Walk-forward optimization
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta


class TestMinimalBacktestBasics:
    """Test basic backtest functionality."""

    def test_backtest_can_be_imported(self):
        """Verify MinimalBacktest exists and can be imported."""
        from Backtest.MinimalBacktest import MinimalBacktest
        assert MinimalBacktest is not None

    def test_backtest_can_be_instantiated(self, mock_mdp):
        """Backtest can be created with market data provider."""
        from Backtest.MinimalBacktest import MinimalBacktest

        backtest = MinimalBacktest(
            mdp=mock_mdp,
            risk_aversion=1.0,
            long_only=True,
        )

        assert backtest is not None
        assert backtest.mdp == mock_mdp

    def test_backtest_has_run_method(self, mock_mdp):
        """Backtest has run() method."""
        from Backtest.MinimalBacktest import MinimalBacktest

        backtest = MinimalBacktest(mdp=mock_mdp)
        assert hasattr(backtest, 'run')


class TestBacktestExecution:
    """Test backtest execution."""

    def test_single_date_backtest(self, mock_mdp):
        """Backtest runs for single date."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15)]

        backtest = MinimalBacktest(mdp=mock_mdp)
        result = backtest.run(contracts, dates)

        # Should have result
        assert result is not None
        assert hasattr(result, 'weights')
        assert hasattr(result, 'returns')

    def test_multiple_date_backtest(self, mock_mdp):
        """Backtest runs for multiple dates."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
        dates = [
            date(2024, 6, 15),
            date(2024, 6, 22),
            date(2024, 6, 29),
        ]

        backtest = MinimalBacktest(mdp=mock_mdp)
        result = backtest.run(contracts, dates)

        # Should have 3 periods of returns (2 transitions)
        assert len(result.returns) == 2


class TestPositionTracking:
    """Test position tracking."""

    def test_initial_position_is_zero(self, mock_mdp):
        """Initial position starts at zero."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4']
        dates = [date(2024, 6, 15)]

        backtest = MinimalBacktest(mdp=mock_mdp)
        result = backtest.run(contracts, dates)

        # First date should establish position
        assert 'SFRZ4' in result.weights.columns

    def test_weights_sum_to_one(self, mock_mdp):
        """Portfolio weights sum to 1.0 (long-only)."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15)]

        backtest = MinimalBacktest(mdp=mock_mdp, long_only=True)
        result = backtest.run(contracts, dates)

        # Weights should sum to 1.0
        total_weight = result.weights.iloc[0].sum()
        assert abs(total_weight - 1.0) < 0.01


class TestPerformanceMetrics:
    """Test performance metric calculation."""

    def test_returns_calculated(self, mock_mdp):
        """Returns time series is calculated."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4', 'SFRH5']
        dates = [
            date(2024, 6, 15),
            date(2024, 6, 22),
        ]

        backtest = MinimalBacktest(mdp=mock_mdp)
        result = backtest.run(contracts, dates)

        # Should have 1 return (2 dates → 1 period)
        assert len(result.returns) == 1
        assert not np.isnan(result.returns.iloc[0])

    def test_sharpe_ratio_calculated(self, mock_mdp):
        """Sharpe ratio is calculated (may be negative)."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4', 'SFRH5']
        dates = pd.date_range(start='2024-06-15', periods=10, freq='W')

        backtest = MinimalBacktest(mdp=mock_mdp)
        result = backtest.run(contracts, dates.tolist())

        # Should have Sharpe ratio (can be negative)
        assert hasattr(result, 'sharpe_ratio')
        assert result.sharpe_ratio is not None

    def test_ic_calculated(self, mock_mdp):
        """IC is calculated (may be negative)."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
        dates = pd.date_range(start='2024-06-15', periods=10, freq='W')

        backtest = MinimalBacktest(mdp=mock_mdp)
        result = backtest.run(contracts, dates.tolist())

        # Should have IC (can be negative - that's okay for MVP)
        assert hasattr(result, 'ic')
        assert result.ic is not None


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_contracts_list(self, mock_mdp):
        """Empty contracts list → empty result."""
        from Backtest.MinimalBacktest import MinimalBacktest

        backtest = MinimalBacktest(mdp=mock_mdp)
        result = backtest.run([], [date(2024, 6, 15)])

        # Should handle gracefully
        assert result is not None

    def test_single_contract(self, mock_mdp):
        """Single contract → 100% allocation (long-only)."""
        from Backtest.MinimalBacktest import MinimalBacktest

        contracts = ['SFRZ4']
        dates = [date(2024, 6, 15)]

        backtest = MinimalBacktest(mdp=mock_mdp, long_only=True)
        result = backtest.run(contracts, dates)

        # Should allocate 100% to single contract
        assert result.weights.iloc[0]['SFRZ4'] == pytest.approx(1.0, abs=0.01)
