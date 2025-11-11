# ABOUTME: Tests for GrinoldKahnPortfolio integrating signals, alpha generation, risk, and optimization
# ABOUTME: Validates full Grinold-Kahn workflow from signals to portfolio weights
"""
Tests for GrinoldKahnPortfolio

Validates:
- Signal → Alpha → Weights pipeline
- Integration with AlphaGenerator, Risk models, Optimizer
- Portfolio return calculation from constituent returns
- Proper Asset interface implementation
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date
from typing import Dict

from Asset.GrinoldKahnPortfolio import GrinoldKahnPortfolio
from Asset.Portfolio import Portfolio
from Asset.Position import Position
from Asset.PriceFuture import PriceFuture
from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Volatility.RealizedVolatility import RealizedVolatility
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer


# Mock signal for testing
class MockSignal(BaseSignal):
    """Simple mock signal that returns fixed Z-scores."""

    def __init__(self, scores: Dict[str, float]):
        super().__init__(name="mock_signal", standardize=False)
        self.scores = scores

    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        return 0.0

    def calculate(self, instruments, market_data, as_of):
        """Return pre-defined Z-scores for testing."""
        return {inst: self.scores.get(inst, 0.0) for inst in instruments}


class TestGrinoldKahnPortfolioConstruction:
    """Test GrinoldKahnPortfolio construction and initialization."""

    def test_can_import(self):
        """Can import GrinoldKahnPortfolio."""
        assert GrinoldKahnPortfolio is not None

    def test_can_construct_with_defaults(self):
        """Can construct GrinoldKahnPortfolio with default parameters."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_CARRY',
            signals=[signal]
        )

        assert portfolio.identifier == 'GK_CARRY'
        assert len(portfolio.signals) == 1
        assert portfolio.alpha_generator is not None
        assert portfolio.risk_model is not None
        assert portfolio.optimizer is not None

    def test_can_construct_with_custom_components(self):
        """Can construct GrinoldKahnPortfolio with custom components."""
        signal = MockSignal({'SFRZ4': 1.0})
        alpha_gen = AlphaGenerator(IC=0.10)
        risk_model = LedoitWolfShrinkage()
        optimizer = MeanVarianceOptimizer(risk_aversion=2.0)

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_CUSTOM',
            signals=[signal],
            alpha_generator=alpha_gen,
            risk_model=risk_model,
            optimizer=optimizer
        )

        assert portfolio.alpha_generator.IC == 0.10
        assert portfolio.optimizer.risk_aversion == 2.0


class TestGenerateWeights:
    """Test weight generation from signals."""

    def test_generate_weights_single_signal(self):
        """Generate weights from single signal."""
        # Setup: signal with positive Z-score for SFRZ4
        signal = MockSignal({'SFRZ4': 2.0, 'SFRH5': -1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_TEST',
            signals=[signal]
        )

        # Create synthetic returns history
        returns_history = pd.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02, -0.01, 0.01] * 10,
            'SFRH5': [0.005, -0.005, 0.01, -0.005, 0.005] * 10
        })

        instruments = ['SFRZ4', 'SFRH5']
        as_of = date(2024, 11, 1)

        # Generate weights
        weights = portfolio.generate_weights(
            instruments=instruments,
            returns_history=returns_history,
            market_data=None,
            as_of=as_of
        )

        # Validate
        assert isinstance(weights, dict)
        assert 'SFRZ4' in weights
        assert 'SFRH5' in weights
        assert abs(sum(weights.values()) - 1.0) < 1e-6  # Weights sum to 1

    def test_weights_reflect_signal_direction(self):
        """Weights should align with signal direction."""
        # Strong positive signal for SFRZ4, negative for SFRH5
        signal = MockSignal({'SFRZ4': 2.0, 'SFRH5': -2.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_TEST',
            signals=[signal],
            optimizer=MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
        )

        returns_history = pd.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02, -0.01, 0.01] * 10,
            'SFRH5': [0.005, -0.005, 0.01, -0.005, 0.005] * 10
        })

        weights = portfolio.generate_weights(
            instruments=['SFRZ4', 'SFRH5'],
            returns_history=returns_history,
            market_data=None,
            as_of=date(2024, 11, 1)
        )

        # With long-only, positive signal should get higher weight
        assert weights['SFRZ4'] > weights['SFRH5']

    def test_multiple_signals_combined(self):
        """Multiple signals should be combined."""
        signal1 = MockSignal({'SFRZ4': 1.0, 'SFRH5': 0.0})
        signal2 = MockSignal({'SFRZ4': 1.0, 'SFRH5': 0.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_MULTI',
            signals=[signal1, signal2]
        )

        returns_history = pd.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02, -0.01, 0.01] * 10,
            'SFRH5': [0.005, -0.005, 0.01, -0.005, 0.005] * 10
        })

        weights = portfolio.generate_weights(
            instruments=['SFRZ4', 'SFRH5'],
            returns_history=returns_history,
            market_data=None,
            as_of=date(2024, 11, 1)
        )

        assert isinstance(weights, dict)
        assert len(weights) == 2


class TestCalculateReturn:
    """Test portfolio return calculation."""

    def test_calculate_return_from_constituent_returns(self):
        """Calculate portfolio return from constituent returns."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_TEST',
            signals=[signal]
        )

        # Simple case: 60/40 split
        weights = {'SFRZ4': 0.6, 'SFRH5': 0.4}
        returns = {'SFRZ4': 0.02, 'SFRH5': 0.01}  # 2% and 1%

        port_return = portfolio.calculate_return(returns, weights)

        # Expected: 0.6 * 0.02 + 0.4 * 0.01 = 0.016
        assert abs(port_return - 0.016) < 1e-10

    def test_calculate_return_all_in_one(self):
        """Calculate return with 100% weight in one asset."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_TEST',
            signals=[signal]
        )

        weights = {'SFRZ4': 1.0, 'SFRH5': 0.0}
        returns = {'SFRZ4': 0.05, 'SFRH5': 0.02}

        port_return = portfolio.calculate_return(returns, weights)

        assert abs(port_return - 0.05) < 1e-10

    def test_calculate_return_missing_asset(self):
        """Handle missing asset in returns."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_TEST',
            signals=[signal]
        )

        weights = {'SFRZ4': 0.5, 'SFRH5': 0.5}
        returns = {'SFRZ4': 0.02}  # Missing SFRH5

        port_return = portfolio.calculate_return(returns, weights)

        # Should handle gracefully, treating missing as 0
        assert abs(port_return - 0.01) < 1e-10  # 0.5 * 0.02


class TestAssetInterface:
    """Test that GrinoldKahnPortfolio implements Asset interface."""

    def test_is_asset_subclass(self):
        """GrinoldKahnPortfolio should be an Asset."""
        from Asset.Base import Asset

        signal = MockSignal({'SFRZ4': 1.0})
        portfolio = GrinoldKahnPortfolio(
            identifier='GK_TEST',
            signals=[signal]
        )

        assert isinstance(portfolio, Asset)

    def test_has_identifier_attribute(self):
        """GrinoldKahnPortfolio should have identifier."""
        signal = MockSignal({'SFRZ4': 1.0})
        portfolio = GrinoldKahnPortfolio(
            identifier='GK_CARRY',
            signals=[signal]
        )

        assert hasattr(portfolio, 'identifier')
        assert portfolio.identifier == 'GK_CARRY'


class TestGrinoldKahnIntegration:
    """Integration tests for full Grinold-Kahn workflow."""

    def test_end_to_end_signal_to_return(self):
        """Test full workflow: Signal → Alpha → Weights → Return."""
        # Setup signal
        signal = MockSignal({'SFRZ4': 2.0, 'SFRH5': -1.0, 'SFRM5': 0.5})

        # Create portfolio with realistic parameters
        portfolio = GrinoldKahnPortfolio(
            identifier='GK_E2E',
            signals=[signal],
            alpha_generator=AlphaGenerator(IC=0.05),
            risk_model=LedoitWolfShrinkage(),
            optimizer=MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
        )

        # Create returns history
        np.random.seed(42)
        returns_history = pd.DataFrame({
            'SFRZ4': np.random.normal(0.001, 0.01, 60),
            'SFRH5': np.random.normal(0.001, 0.008, 60),
            'SFRM5': np.random.normal(0.001, 0.009, 60)
        })

        # Generate weights
        weights = portfolio.generate_weights(
            instruments=['SFRZ4', 'SFRH5', 'SFRM5'],
            returns_history=returns_history,
            market_data=None,
            as_of=date(2024, 11, 1)
        )

        # Verify weights
        assert isinstance(weights, dict)
        assert len(weights) == 3
        assert abs(sum(weights.values()) - 1.0) < 1e-6

        # Calculate return
        realized_returns = {'SFRZ4': 0.015, 'SFRH5': 0.008, 'SFRM5': 0.010}
        port_return = portfolio.calculate_return(realized_returns, weights)

        # Verify return is reasonable
        assert -0.1 < port_return < 0.1  # Within +/- 10%
        assert isinstance(port_return, float)

    def test_updates_with_new_data(self):
        """Portfolio should handle updated returns history."""
        # Use more balanced signals so optimizer doesn't go all-in on one asset
        signal = MockSignal({'SFRZ4': 0.5, 'SFRH5': 0.3})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_UPDATE',
            signals=[signal],
            optimizer=MeanVarianceOptimizer(risk_aversion=5.0, long_only=True)  # Higher risk aversion
        )

        # Initial history with normal volatility
        returns1 = pd.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02, -0.01, 0.01] * 10,
            'SFRH5': [0.005, -0.005, 0.01, -0.005, 0.005] * 10
        })

        weights1 = portfolio.generate_weights(
            instruments=['SFRZ4', 'SFRH5'],
            returns_history=returns1,
            market_data=None,
            as_of=date(2024, 11, 1)
        )

        # Updated history with much more volatile data for SFRZ4
        returns2 = pd.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02, -0.01, 0.01] * 10 + [0.10, -0.10, 0.12, -0.08, 0.10] * 2,
            'SFRH5': [0.005, -0.005, 0.01, -0.005, 0.005] * 10 + [0.005, -0.005, 0.01, -0.005, 0.005] * 2
        })

        weights2 = portfolio.generate_weights(
            instruments=['SFRZ4', 'SFRH5'],
            returns_history=returns2,
            market_data=None,
            as_of=date(2024, 11, 15)
        )

        # With higher risk aversion and much higher volatility for SFRZ4,
        # weight should shift toward less volatile SFRH5
        assert weights1 != weights2
        assert weights2['SFRH5'] > weights1['SFRH5']  # More weight to less volatile asset
