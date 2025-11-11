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
        # Use fixed seed for reproducibility
        np.random.seed(42)
        returns_history = pd.DataFrame({
            'LOW_VOL': np.random.randn(60) * 0.10 / np.sqrt(252),
            'HIGH_VOL': np.random.randn(60) * 0.20 / np.sqrt(252),
        })

        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Same signal, higher vol → higher alpha
        # HIGH_VOL should have ~2x alpha of LOW_VOL
        ratio = alphas['HIGH_VOL'] / alphas['LOW_VOL']
        assert 1.5 < ratio < 2.5  # Approximately 2.0 (allow for sampling noise)

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


class TestDynamicICBasics:
    """Basic dynamic IC functionality."""

    def test_can_create_alpha_generator_with_dynamic_ic(self):
        """Can create AlphaGenerator with dynamic IC enabled."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60
        )

        assert alpha_gen.dynamic_ic is True
        assert alpha_gen.ic_method == "rolling"
        assert alpha_gen.ic_lookback == 60

    def test_default_dynamic_ic_is_false(self):
        """Dynamic IC is disabled by default (backward compatible)."""
        alpha_gen = AlphaGenerator(IC=0.05)
        assert alpha_gen.dynamic_ic is False

    def test_invalid_ic_method_raises_error(self):
        """Invalid ic_method raises ValueError."""
        alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="invalid", ic_min_periods=10)

        # Need sufficient data to pass initial checks
        dates = pd.date_range('2024-01-01', periods=30)
        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(30)}, index=dates)
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(30)}, index=dates)

        with pytest.raises(ValueError, match="Unknown ic_method"):
            alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)


class TestRollingICEstimation:
    """Test rolling IC estimation method."""

    def test_rolling_ic_with_perfect_correlation(self):
        """Rolling IC detects perfect correlation (IC = 1.0)."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60
        )

        # Perfect correlation: signals = returns
        np.random.seed(42)
        values = np.random.randn(60)
        dates = pd.date_range('2024-01-01', periods=60)

        signals_hist = pd.DataFrame({'SFRZ4': values}, index=dates)
        returns_hist = pd.DataFrame({'SFRZ4': values}, index=dates)  # Perfect correlation

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # IC should be close to 1.0 (perfect correlation)
        assert ic == pytest.approx(1.0, abs=0.01)

    def test_rolling_ic_with_no_correlation(self):
        """Rolling IC detects no correlation (IC ≈ 0)."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60
        )

        # No correlation: independent random variables
        np.random.seed(42)
        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # IC should be close to 0 (no correlation)
        assert abs(ic) < 0.3  # Allow some sampling noise

    def test_rolling_ic_with_negative_correlation(self):
        """Rolling IC detects negative correlation (IC < 0)."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60
        )

        # Negative correlation: signals = -returns
        np.random.seed(42)
        values = np.random.randn(60)
        dates = pd.date_range('2024-01-01', periods=60)

        signals_hist = pd.DataFrame({'SFRZ4': values}, index=dates)
        returns_hist = pd.DataFrame({'SFRZ4': -values}, index=dates)  # Negative correlation

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # IC should be close to -1.0 (perfect negative correlation)
        assert ic == pytest.approx(-1.0, abs=0.01)

    def test_rolling_ic_with_partial_correlation(self):
        """Rolling IC detects partial correlation (0 < IC < 1)."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60
        )

        # Partial correlation: returns = signals + noise
        np.random.seed(42)
        signals = np.random.randn(60)
        noise = np.random.randn(60) * 0.5  # Add noise
        dates = pd.date_range('2024-01-01', periods=60)

        signals_hist = pd.DataFrame({'SFRZ4': signals}, index=dates)
        returns_hist = pd.DataFrame({'SFRZ4': signals + noise}, index=dates)

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # IC should be positive but < 1.0
        assert 0.5 < ic < 0.95  # Partial correlation

    def test_rolling_ic_with_insufficient_history(self):
        """Rolling IC falls back to static IC with insufficient history."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60,
            ic_min_periods=20
        )

        # Only 10 periods (< ic_min_periods)
        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(10)})
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(10)})

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # Should fallback to static IC
        assert ic == pytest.approx(0.05)


class TestEWMAICEstimation:
    """Test exponentially weighted IC estimation method."""

    def test_ewma_ic_with_perfect_correlation(self):
        """EWMA IC detects perfect correlation."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="ewma",
            ic_halflife=30
        )

        # Perfect correlation across multiple assets
        np.random.seed(42)
        n_periods = 60
        n_assets = 5
        dates = pd.date_range('2024-01-01', periods=n_periods)

        signals_data = {}
        returns_data = {}
        for i in range(n_assets):
            values = np.random.randn(n_periods)
            signals_data[f'ASSET_{i}'] = values
            returns_data[f'ASSET_{i}'] = values  # Perfect correlation

        signals_hist = pd.DataFrame(signals_data, index=dates)
        returns_hist = pd.DataFrame(returns_data, index=dates)

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # IC should be close to 1.0
        assert ic == pytest.approx(1.0, abs=0.05)

    def test_ewma_ic_adapts_to_changing_correlation(self):
        """EWMA IC adapts to changing correlation over time."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="ewma",
            ic_halflife=10  # Short halflife for quick adaptation
        )

        # First half: high correlation, Second half: low correlation
        np.random.seed(42)
        n_periods = 60
        n_assets = 3

        signals_data = {}
        returns_data = {}
        for i in range(n_assets):
            signals = np.random.randn(n_periods)
            # First 30: high correlation
            returns_early = signals[:30] + np.random.randn(30) * 0.1
            # Last 30: low correlation (more noise)
            returns_late = signals[30:] + np.random.randn(30) * 5.0

            signals_data[f'ASSET_{i}'] = signals
            returns_data[f'ASSET_{i}'] = np.concatenate([returns_early, returns_late])

        signals_hist = pd.DataFrame(signals_data)
        returns_hist = pd.DataFrame(returns_data)

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # EWMA should weight recent (low correlation) periods more
        # IC should be lower than if we used rolling average
        assert ic < 0.5  # Lower due to recent low correlation


class TestRegimeAwareICEstimation:
    """Test regime-aware IC estimation method."""

    def test_regime_ic_detects_high_vol_regime(self):
        """Regime IC detects high volatility regime."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="regime"
        )

        # Create data with varying volatility
        np.random.seed(42)
        n_periods = 60

        # Early periods: low vol
        returns_early = np.random.randn(30, 3) * 0.01

        # Recent periods: high vol
        returns_late = np.random.randn(30, 3) * 0.05

        returns_hist = pd.DataFrame(
            np.vstack([returns_early, returns_late]),
            columns=['A', 'B', 'C']
        )

        # Signals correlated with returns
        signals_hist = pd.DataFrame(
            returns_hist.values + np.random.randn(60, 3) * 0.01,
            columns=['A', 'B', 'C']
        )

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # Should calculate IC based on high vol regime (recent periods)
        assert ic is not None
        assert not np.isnan(ic)

    def test_regime_ic_with_insufficient_regime_data(self):
        """Regime IC falls back to static IC with insufficient regime data."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="regime",
            ic_min_periods=20
        )

        # Only 15 periods in current regime
        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(15)})
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(15)})

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # Should fallback to static IC
        assert ic == pytest.approx(0.05)


class TestDynamicICEdgeCases:
    """Edge cases for dynamic IC estimation."""

    def test_empty_signals_history(self):
        """Empty signals history falls back to static IC."""
        alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="rolling")

        signals_hist = pd.DataFrame()
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # Should fallback to static IC
        assert ic == pytest.approx(0.05)

    def test_empty_returns_history(self):
        """Empty returns history falls back to static IC."""
        alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="rolling")

        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})
        returns_hist = pd.DataFrame()

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # Should fallback to static IC
        assert ic == pytest.approx(0.05)

    def test_no_common_assets(self):
        """No common assets falls back to static IC."""
        alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="rolling")

        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})
        returns_hist = pd.DataFrame({'SFRH5': np.random.randn(60)})

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # Should fallback to static IC
        assert ic == pytest.approx(0.05)

    def test_extreme_ic_capped(self):
        """IC values are clipped to valid range [-1, 1]."""
        alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=True, ic_method="rolling")

        # Random data - IC should be valid correlation coefficient
        dates = pd.date_range('2024-01-01', periods=60)
        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)}, index=dates)
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)}, index=dates)

        ic = alpha_gen.estimate_dynamic_ic(signals_hist, returns_hist)

        # IC must be a valid correlation coefficient
        assert -1.0 <= ic <= 1.0


class TestDynamicICIntegration:
    """Test integration of dynamic IC with signals_to_alphas."""

    def test_signals_to_alphas_with_dynamic_ic_method(self):
        """signals_to_alphas_with_dynamic_ic uses dynamic IC."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60
        )

        # Create correlated signals and returns
        np.random.seed(42)
        values = np.random.randn(60)

        signals_hist = pd.DataFrame({'SFRZ4': values})
        returns_hist = pd.DataFrame({'SFRZ4': values * 0.01})  # High correlation

        current_signals = {'SFRZ4': 2.0}

        alphas = alpha_gen.signals_to_alphas_with_dynamic_ic(
            current_signals,
            returns_hist,
            signals_hist,
            date(2024, 11, 1)
        )

        # Should produce alphas using dynamic IC
        assert 'SFRZ4' in alphas
        assert alphas['SFRZ4'] != 0

    def test_dynamic_ic_does_not_modify_static_ic_attribute(self):
        """Using dynamic IC does not permanently modify IC attribute."""
        alpha_gen = AlphaGenerator(
            IC=0.05,
            dynamic_ic=True,
            ic_method="rolling",
            ic_lookback=60
        )

        np.random.seed(42)
        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})
        current_signals = {'SFRZ4': 2.0}

        # Original IC
        original_ic = alpha_gen.IC

        # Use dynamic IC
        alpha_gen.signals_to_alphas_with_dynamic_ic(
            current_signals,
            returns_hist,
            signals_hist,
            date(2024, 11, 1)
        )

        # IC should be restored to original
        assert alpha_gen.IC == pytest.approx(original_ic)

    def test_static_ic_mode_ignores_dynamic_ic(self):
        """When dynamic_ic=False, signals_to_alphas_with_dynamic_ic uses static IC."""
        alpha_gen = AlphaGenerator(IC=0.05, dynamic_ic=False)

        np.random.seed(42)
        signals_hist = pd.DataFrame({'SFRZ4': np.random.randn(60)})
        returns_hist = pd.DataFrame({'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252)})
        current_signals = {'SFRZ4': 2.0}

        # Should use static IC
        alphas_static = alpha_gen.signals_to_alphas(
            current_signals,
            returns_hist,
            date(2024, 11, 1)
        )

        alphas_dynamic_disabled = alpha_gen.signals_to_alphas_with_dynamic_ic(
            current_signals,
            returns_hist,
            signals_hist,
            date(2024, 11, 1)
        )

        # Should be identical
        assert alphas_static == alphas_dynamic_disabled
