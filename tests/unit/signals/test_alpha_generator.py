# ABOUTME: Tests for AlphaGenerator converting signals to expected returns
# ABOUTME: Validates IC × Vol × Z formula and proper scaling
"""
Tests for AlphaGenerator

Validates:
- Signal → Alpha conversion: α = IC × Vol × Z
- IC (Information Coefficient) scaling
- Volatility scaling
- Multi-asset alpha generation
- Edge cases: zero signals, zero IC, zero volatility

Critical Insight:
    Signals are dimensionless Z-scores (e.g., Z=2.0 means 2 std devs above mean)
    Alphas are EXPECTED RETURNS (e.g., α=0.01 means expect 1% return)

    Without conversion, Z=2.0 would be treated as 200% expected return (wrong!)
    With conversion: Z=2.0, Vol=10%, IC=0.05 → α=1% (sensible!)
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date
from typing import Dict

from Signals.AlphaGenerator import AlphaGenerator
from Risk.Volatility.RealizedVolatility import RealizedVolatility


class TestAlphaGeneratorBasics:
    """Basic functionality and interface."""

    def test_can_import_alpha_generator(self):
        """Can import AlphaGenerator."""
        assert AlphaGenerator is not None

    def test_can_create_alpha_generator(self):
        """Can create AlphaGenerator with IC and vol estimator."""
        vol_est = RealizedVolatility(lookback=60)
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=vol_est)

        assert alpha_gen is not None
        assert alpha_gen.IC == 0.05

    def test_default_ic_is_0_05(self):
        """Default IC is 0.05 (5% correlation)."""
        alpha_gen = AlphaGenerator()
        assert alpha_gen.IC == pytest.approx(0.05)

    def test_default_vol_estimator_is_realized(self):
        """Default volatility estimator is RealizedVolatility."""
        alpha_gen = AlphaGenerator()
        assert isinstance(alpha_gen.vol_estimator, RealizedVolatility)


class TestSignalsToAlphas:
    """Test signals → alphas conversion."""

    def test_simple_alpha_conversion(self):
        """Convert single signal to alpha using IC × Vol × Z."""
        # IC = 0.05, Vol = 0.10 (10%), Z = 2.0
        # Expected: α = 0.05 × 0.10 × 2.0 = 0.01 (1%)

        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {'SFRZ4': 2.0}  # Z-score = 2.0

        # Historical returns with 10% vol
        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),  # Daily returns → 10% annual vol
        })

        alphas = alpha_gen.signals_to_alphas(
            signals,
            returns_history,
            as_of=date(2024, 11, 1)
        )

        # Should be approximately 0.01 (1%)
        # (Exact value depends on random returns, but should be close)
        assert abs(alphas['SFRZ4'] - 0.01) < 0.005  # Within 0.5%

    def test_negative_signal_negative_alpha(self):
        """Negative signal produces negative alpha."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {'SFRZ4': -1.5}  # Negative Z-score

        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(
            signals,
            returns_history,
            as_of=date(2024, 11, 1)
        )

        # Negative signal → negative alpha
        assert alphas['SFRZ4'] < 0

    def test_zero_signal_zero_alpha(self):
        """Zero signal produces zero alpha."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {'SFRZ4': 0.0}  # No signal

        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(
            signals,
            returns_history,
            as_of=date(2024, 11, 1)
        )

        assert alphas['SFRZ4'] == pytest.approx(0.0)

    def test_multiple_assets(self):
        """Convert signals for multiple assets."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {
            'SFRZ4': 2.0,
            'SFRH5': -1.0,
            'SFRM5': 0.5
        }

        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
            'SFRH5': np.random.randn(60) * 0.15 / np.sqrt(252),  # Higher vol
            'SFRM5': np.random.randn(60) * 0.08 / np.sqrt(252),  # Lower vol
        })

        alphas = alpha_gen.signals_to_alphas(
            signals,
            returns_history,
            as_of=date(2024, 11, 1)
        )

        # All assets should have alphas
        assert 'SFRZ4' in alphas
        assert 'SFRH5' in alphas
        assert 'SFRM5' in alphas

        # Positive signal → positive alpha
        assert alphas['SFRZ4'] > 0
        # Negative signal → negative alpha
        assert alphas['SFRH5'] < 0
        # Small positive signal → small positive alpha
        assert 0 < alphas['SFRM5'] < alphas['SFRZ4']


class TestICScaling:
    """Test IC (Information Coefficient) scaling."""

    def test_higher_ic_higher_alpha(self):
        """Higher IC produces proportionally higher alphas."""
        # IC = 0.10 should produce 2x alphas compared to IC = 0.05

        alpha_gen_low = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())
        alpha_gen_high = AlphaGenerator(IC=0.10, vol_estimator=RealizedVolatility())

        signals = {'SFRZ4': 2.0}

        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        alphas_low = alpha_gen_low.signals_to_alphas(signals, returns_history, date(2024, 11, 1))
        alphas_high = alpha_gen_high.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Higher IC → proportionally higher alpha
        ratio = alphas_high['SFRZ4'] / alphas_low['SFRZ4']
        assert ratio == pytest.approx(2.0, rel=0.01)

    def test_zero_ic_zero_alpha(self):
        """Zero IC produces zero alphas (no forecasting skill)."""
        alpha_gen = AlphaGenerator(IC=0.0, vol_estimator=RealizedVolatility())

        signals = {'SFRZ4': 2.0}

        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # IC = 0 → no forecasting skill → alpha = 0
        assert alphas['SFRZ4'] == pytest.approx(0.0)


class TestVolatilityScaling:
    """Test volatility scaling."""

    def test_higher_vol_higher_alpha(self):
        """Higher volatility produces proportionally higher alphas."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {
            'LOW_VOL': 1.0,
            'HIGH_VOL': 1.0,  # Same signal
        }

        # LOW_VOL has 10% vol, HIGH_VOL has 20% vol
        returns_history = pd.DataFrame({
            'LOW_VOL': np.random.randn(60) * 0.10 / np.sqrt(252),
            'HIGH_VOL': np.random.randn(60) * 0.20 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Same signal, higher vol → higher alpha
        # HIGH_VOL should have ~2x alpha of LOW_VOL
        ratio = alphas['HIGH_VOL'] / alphas['LOW_VOL']
        assert 1.8 < ratio < 2.2  # Approximately 2.0 (allow for sampling noise)

    def test_zero_vol_zero_alpha(self):
        """Zero volatility produces zero alpha."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {'CONSTANT': 1.0}

        # Constant returns → zero volatility
        returns_history = pd.DataFrame({
            'CONSTANT': [0.01] * 60,
        })

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Zero vol → zero alpha
        assert alphas['CONSTANT'] == pytest.approx(0.0)


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_missing_returns_history(self):
        """Handle asset in signals but not in returns history."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {'SFRZ4': 1.0, 'NEW_ASSET': 1.0}

        # NEW_ASSET not in returns history
        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # SFRZ4 should have alpha
        assert 'SFRZ4' in alphas
        assert alphas['SFRZ4'] != 0

        # NEW_ASSET should have alpha = 0 (no history → no vol estimate)
        assert 'NEW_ASSET' in alphas
        assert alphas['NEW_ASSET'] == pytest.approx(0.0)

    def test_empty_signals(self):
        """Handle empty signals dict."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {}

        returns_history = pd.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Empty signals → empty alphas
        assert len(alphas) == 0

    def test_empty_returns_history(self):
        """Handle empty returns history."""
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {'SFRZ4': 1.0}

        returns_history = pd.DataFrame()

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # No history → alpha = 0
        assert alphas['SFRZ4'] == pytest.approx(0.0)


class TestRealWorldExample:
    """Real-world example demonstrating proper scaling."""

    def test_carry_signal_to_alpha(self):
        """
        Real-world example: carry signal → alpha.

        Scenario:
            Signal (carry Z-score): 1.5 (strong carry)
            Volatility: 12% annualized
            IC: 0.05 (5% correlation between forecast and realized)

            Without scaling: α = 1.5 → 150% expected return (absurd!)
            With scaling: α = 0.05 × 0.12 × 1.5 = 0.009 → 0.9% (sensible!)
        """
        alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())

        signals = {'CARRY_TRADE': 1.5}

        # Create returns with 12% volatility
        returns_history = pd.DataFrame({
            'CARRY_TRADE': np.random.randn(60) * 0.12 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Should be approximately 0.9% (0.009)
        # Much more sensible than 150%!
        assert 0.005 < alphas['CARRY_TRADE'] < 0.015  # Between 0.5% and 1.5%
