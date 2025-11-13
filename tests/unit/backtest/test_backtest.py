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
6. Maintain backwards compatibility with MinimalBacktest usage

Test Organization:
- TestBacktestBasics: Instantiation, validation
- TestFuturesCarryWorkflow: Baseline (same as MinimalBacktest)
- TestFuturesMomentumWorkflow: New capability
- TestMultiSignalWorkflow: Multiple signals + combiner
- TestDataFrameWorkflow: Equity/ETF strategies
- TestComponentInjection: Custom risk models, optimizers
- TestBackwardsCompatibility: MinimalBacktest use cases still work
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
