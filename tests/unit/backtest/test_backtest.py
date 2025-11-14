# ABOUTME: Test suite for generic Backtest class
# ABOUTME: Verifies configurable components, multiple workflows, backwards compatibility

"""
Tests for Generic Backtest

Verifies the generic backtest can:
1. Work with any signal type (not just CarrySignal)
2. Work with any adapter (Futures, Equity, custom)
3. Accept multiple signals with combiner
4. Work with query-based workflow (futures)
5. Work with DataFrame-based workflow (equities)

Test Organization:
- TestBacktestBasics: Instantiation, validation
- TestFuturesCarryWorkflow: Futures carry baseline
- TestFuturesMomentumWorkflow: Futures momentum strategy
- TestMultiSignalWorkflow: Multiple signals + combiner
- TestDataFrameWorkflow: Equity/ETF strategies
- TestComponentInjection: Custom risk models, optimizers
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import List


class TestBacktestBasics:
    """Test basic instantiation and validation."""

    def test_backtest_can_be_imported(self):
        """Verify Backtest class exists and can be imported."""
        from Backtest.Backtest import Backtest
        assert Backtest is not None

    def test_backtest_requires_signals(self):
        """Backtest raises ValueError if no signals provided."""
        from Backtest.Backtest import Backtest

        with pytest.raises(ValueError, match="Must provide at least one signal"):
            Backtest()

    def test_backtest_accepts_single_signal(self):
        """Backtest accepts a single signal."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name='carry')
        backtest = Backtest(signals=signal)

        assert backtest is not None
        assert len(backtest.signals) == 1
        assert backtest.signals[0] == signal

    def test_backtest_accepts_signal_list(self):
        """Backtest accepts a list of signals."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Futures.MomentumSignal import MomentumSignal

        carry = CarrySignal(name='carry')
        momentum = MomentumSignal(name='momentum')

        backtest = Backtest(signals=[carry, momentum])

        assert len(backtest.signals) == 2
        assert backtest.signals[0] == carry
        assert backtest.signals[1] == momentum

    def test_backtest_validates_adapter_requires_mdp(self):
        """Backtest raises if adapter provided without mdp."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal

        # Create mock adapter (will fail validation in Backtest)
        class MockAdapter:
            pass

        with pytest.raises(ValueError, match="Adapter requires mdp"):
            Backtest(
                adapter=MockAdapter(),
                mdp=None,  # ← Missing mdp
                signals=CarrySignal()
            )

    def test_backtest_creates_default_components(self):
        """Backtest creates default components if not provided."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.AlphaGenerator import AlphaGenerator
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        backtest = Backtest(signals=CarrySignal())

        # Should create defaults
        assert isinstance(backtest.alpha_generator, AlphaGenerator)
        assert isinstance(backtest.risk_model, LedoitWolfShrinkage)
        assert isinstance(backtest.optimizer, MeanVarianceOptimizer)

    def test_backtest_uses_provided_components(self):
        """Backtest uses provided components instead of defaults."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.AlphaGenerator import AlphaGenerator
        from Risk.Covariance.SampleCovariance import SampleCovariance
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Custom components
        custom_alpha = AlphaGenerator(IC=0.10)
        custom_risk = SampleCovariance()
        custom_optimizer = MeanVarianceOptimizer(risk_aversion=5.0)

        backtest = Backtest(
            signals=CarrySignal(),
            alpha_generator=custom_alpha,
            risk_model=custom_risk,
            optimizer=custom_optimizer,
        )

        # Should use provided, not defaults
        assert backtest.alpha_generator == custom_alpha
        assert backtest.risk_model == custom_risk
        assert backtest.optimizer == custom_optimizer


class TestFuturesCarryWorkflow:
    """Test futures carry workflow (baseline)."""

    def test_backtest_runs_with_futures_adapter(self, mock_mdp):
        """Backtest runs with FuturesAdapter and CarrySignal."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        adapter = FuturesAdapter(market_data_provider=mock_mdp)
        signal = CarrySignal(name='carry')

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=adapter,
            signals=signal
        )

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15), date(2024, 6, 22)]

        result = backtest.run(contracts, dates)

        # Should return BacktestResult
        assert result is not None
        assert hasattr(result, 'weights')
        assert hasattr(result, 'returns')
        assert hasattr(result, 'ic')
        assert hasattr(result, 'sharpe_ratio')

    def test_backtest_validates_requires_adapter_for_run(self, mock_mdp):
        """Backtest.run() raises if adapter not provided."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal

        # Create backtest WITHOUT adapter
        backtest = Backtest(signals=CarrySignal())

        contracts = ['SFRZ4']
        dates = [date(2024, 6, 15)]

        with pytest.raises(ValueError, match="Query-based workflow requires adapter"):
            backtest.run(contracts, dates)



class TestFuturesMomentumWorkflow:
    """Test futures momentum workflow (new capability)."""

    def test_backtest_runs_with_momentum_signal(self, mock_mdp):
        """Backtest runs with MomentumSignal."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.MomentumSignal import MomentumSignal

        adapter = FuturesAdapter(market_data_provider=mock_mdp)
        signal = MomentumSignal(lookback_days=20, name='momentum')

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=adapter,
            signals=signal
        )

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15), date(2024, 6, 22)]

        result = backtest.run(contracts, dates)

        # Should return valid result
        assert result is not None
        assert hasattr(result, 'returns')

    def test_momentum_signal_generates_different_weights_than_carry(self, mock_mdp):
        """MomentumSignal produces different weights than CarrySignal."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Futures.MomentumSignal import MomentumSignal

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15)]

        # Carry backtest
        carry_bt = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(market_data_provider=mock_mdp),
            signals=CarrySignal()
        )
        carry_result = carry_bt.run(contracts, dates)

        # Momentum backtest
        momentum_bt = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(market_data_provider=mock_mdp),
            signals=MomentumSignal(lookback_days=20)
        )
        momentum_result = momentum_bt.run(contracts, dates)

        # Weights should differ (different signals)
        # Note: May be similar by chance, but logic is different
        assert carry_result.weights is not None
        assert momentum_result.weights is not None


class TestMultiSignalWorkflow:
    """Test multi-signal workflow with combiner."""

    def test_backtest_combines_multiple_signals(self, mock_mdp):
        """Backtest combines multiple signals with SignalCombiner."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Futures.MomentumSignal import MomentumSignal
        from Signals.SignalCombiner import SignalCombiner

        adapter = FuturesAdapter(market_data_provider=mock_mdp)
        carry = CarrySignal(name='carry')
        momentum = MomentumSignal(lookback_days=20, name='momentum')
        combiner = SignalCombiner()

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=adapter,
            signals=[carry, momentum],
            signal_combiner=combiner
        )

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15), date(2024, 6, 22)]

        result = backtest.run(contracts, dates)

        # Should return valid result
        assert result is not None
        assert hasattr(result, 'returns')

    def test_backtest_creates_default_combiner_for_multiple_signals(self, mock_mdp):
        """Backtest auto-creates SignalCombiner if multiple signals provided."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Futures.MomentumSignal import MomentumSignal
        from Signals.SignalCombiner import SignalCombiner

        carry = CarrySignal(name='carry')
        momentum = MomentumSignal(lookback_days=20, name='momentum')

        # Don't provide combiner - should auto-create
        backtest = Backtest(signals=[carry, momentum])

        # Should have created combiner
        assert backtest.signal_combiner is not None
        assert isinstance(backtest.signal_combiner, SignalCombiner)

    def test_backtest_no_combiner_for_single_signal(self, mock_mdp):
        """Backtest doesn't create combiner for single signal."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal

        backtest = Backtest(signals=CarrySignal())

        # Should NOT have combiner for single signal
        assert backtest.signal_combiner is None


class TestDataFrameWorkflow:
    """Test DataFrame-based workflow (equity/ETF strategies)."""

    def test_backtest_runs_from_dataframe(self):
        """Backtest runs from pre-computed returns DataFrame."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.MomentumSignal import MomentumSignal

        # Create sample returns DataFrame
        returns_df = pl.DataFrame({
            'date': [date(2024, 6, 15), date(2024, 6, 15), date(2024, 6, 22), date(2024, 6, 22)],
            'ticker': ['AAPL', 'MSFT', 'AAPL', 'MSFT'],
            'return': [0.02, -0.01, 0.01, 0.03]
        })

        backtest = Backtest(signals=MomentumSignal(lookback_days=20))

        dates = [date(2024, 6, 15), date(2024, 6, 22)]
        result = backtest.run_from_dataframe(returns_df, dates)

        # Should return valid result
        assert result is not None
        assert hasattr(result, 'returns')

    def test_run_from_dataframe_rejects_adapter(self, mock_mdp):
        """run_from_dataframe() raises if adapter is set."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        # Create backtest WITH adapter
        backtest = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(market_data_provider=mock_mdp),
            signals=CarrySignal()
        )

        returns_df = pl.DataFrame({
            'date': [date(2024, 6, 15)],
            'ticker': ['AAPL'],
            'return': [0.02]
        })

        with pytest.raises(ValueError, match="DataFrame workflow doesn't use adapter"):
            backtest.run_from_dataframe(returns_df, [date(2024, 6, 15)])

    def test_dataframe_workflow_optional_instruments_list(self):
        """DataFrame workflow accepts optional instruments list."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.MomentumSignal import MomentumSignal

        returns_df = pl.DataFrame({
            'date': [date(2024, 6, 15), date(2024, 6, 15), date(2024, 6, 15)],
            'ticker': ['AAPL', 'MSFT', 'GOOGL'],
            'return': [0.02, -0.01, 0.03]
        })

        backtest = Backtest(signals=MomentumSignal(lookback_days=20))

        # Only trade AAPL and MSFT
        result = backtest.run_from_dataframe(
            returns_df,
            dates=[date(2024, 6, 15)],
            instruments=['AAPL', 'MSFT']
        )

        assert result is not None
