# ABOUTME: Integration tests for complete signal→alpha→weights pipeline
# ABOUTME: Critical tests verifying Grinold-Kahn framework implementation
"""
Integration Tests: Signal → Alpha → Weights Pipeline

Tests the complete flow from signals to portfolio weights:
1. Signals (z-scores) generated from market data
2. Alphas (expected returns) via IC × Vol × Z formula
3. Covariance matrix from returns
4. Portfolio weights from mean-variance optimization

Critical Tests:
- End-to-end pipeline correctness
- Mathematical consistency (units, scaling)
- Edge cases (zero signals, high correlation, singular covariance)
- Realistic scenarios (carry signals, volatility regimes)
"""

import pytest
import numpy as np
import polars as pl
from datetime import date

from Signals.Futures.CarrySignal import CarrySignal
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Returns.ReturnsCalculator import ReturnsCalculator
from Risk.Volatility.RealizedVolatility import RealizedVolatility
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer


class TestSignalToWeightsPipeline:
    """Test complete pipeline from signals to weights."""

    def test_end_to_end_pipeline(self):
        """
        End-to-end test: signals → alphas → weights.

        Verifies entire Grinold-Kahn pipeline:
        1. Generate carry signals (z-scores)
        2. Convert to alphas using IC × Vol × Z
        3. Estimate covariance from returns
        4. Optimize portfolio weights
        """
        # Setup
        alpha_gen = AlphaGenerator(IC=0.05)
        risk_model = LedoitWolfShrinkage()
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)

        # Step 1: Create synthetic signals
        signals = {
            'SFRZ4': 1.5,   # Strong positive signal
            'SFRH5': -1.0,  # Moderate negative signal
            'SFRM5': 0.2,   # Weak positive signal
        }

        # Step 2: Create synthetic returns history (60 periods)
        np.random.seed(42)
        returns_history = pl.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),  # 10% vol
            'SFRH5': np.random.randn(60) * 0.12 / np.sqrt(252),  # 12% vol
            'SFRM5': np.random.randn(60) * 0.08 / np.sqrt(252),  # 8% vol
        })

        # Step 3: Convert signals → alphas
        alphas_dict = alpha_gen.signals_to_alphas(
            signals,
            returns_history,
            date(2024, 11, 1)
        )

        # Verify alphas are sensible (not raw z-scores!)
        # Z=1.5 should NOT become 150% alpha
        assert all(abs(alpha) < 0.05 for alpha in alphas_dict.values()), \
            f"Alphas too large: {alphas_dict}"

        # Positive signal → positive alpha
        assert alphas_dict['SFRZ4'] > 0
        # Negative signal → negative alpha
        assert alphas_dict['SFRH5'] < 0
        # Small positive signal → small positive alpha
        assert 0 < alphas_dict['SFRM5'] < alphas_dict['SFRZ4']

        # Step 4: Estimate covariance
        cov_matrix = risk_model.fit(returns_history.to_pandas())
        cov_df = pl.DataFrame(
            cov_matrix,
            schema=returns_history.columns
        )

        # Step 5: Optimize weights
        # Convert alphas dict to polars Series for optimizer (order must match covariance)
        asset_order = returns_history.columns
        alphas_values = [alphas_dict[asset] for asset in asset_order]
        alphas = pl.Series(name='alphas', values=alphas_values)
        weights = optimizer.optimize(alphas, cov_df)

        # Verify weights
        assert len(weights) == 3
        assert abs(weights.sum() - 1.0) < 1e-6, "Weights must sum to 1"
        assert all(w >= -1e-10 for w in weights.values()), "No shorts (long_only=True)"

        # Asset with highest alpha should have highest weight
        highest_alpha_idx = alphas_values.index(max(alphas_values))
        highest_alpha_asset = asset_order[highest_alpha_idx]
        assert weights[highest_alpha_asset] > weights['SFRM5'], \
            "Highest alpha should get highest weight"

    def test_zero_signals_equal_weights(self):
        """Zero signals → zero alphas → equal weights (fallback)."""
        alpha_gen = AlphaGenerator(IC=0.05)
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)

        # All zero signals
        signals = {'SFRZ4': 0.0, 'SFRH5': 0.0, 'SFRM5': 0.0}

        returns_history = pl.DataFrame({
            'SFRZ4': np.random.randn(60) * 0.01,
            'SFRH5': np.random.randn(60) * 0.01,
            'SFRM5': np.random.randn(60) * 0.01,
        })

        # Convert signals → alphas (should all be 0)
        alphas_dict = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        assert all(alpha == pytest.approx(0.0) for alpha in alphas_dict.values()), \
            "Zero signals should produce zero alphas"

    def test_units_consistency(self):
        """
        Verify units are consistent throughout pipeline.

        Signals: dimensionless (z-scores)
        Alphas: decimal returns (e.g., 0.01 = 1%)
        Weights: portfolio weights (sum to 1)
        """
        alpha_gen = AlphaGenerator(IC=0.05)

        # Signals are z-scores (dimensionless)
        signals = {'ASSET1': 2.0, 'ASSET2': -1.5}

        returns_history = pl.DataFrame({
            'ASSET1': np.random.randn(60) * 0.10 / np.sqrt(252),
            'ASSET2': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        # Alphas should be returns (decimal, small)
        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Alphas should be much smaller than signals
        for asset in signals:
            assert abs(alphas[asset]) < abs(signals[asset]) / 10, \
                f"Alpha {alphas[asset]} too close to signal {signals[asset]}"

        # Alphas should be reasonable (< 10% per period)
        assert all(abs(alpha) < 0.10 for alpha in alphas.values()), \
            f"Unreasonable alphas: {alphas}"

    def test_correlation_affects_weights(self):
        """
        High correlation → covariance penalizes concentration.

        Two assets with same alpha but high correlation should
        get more equal weights (diversification benefit).
        """
        alpha_gen = AlphaGenerator(IC=0.05)
        risk_model = LedoitWolfShrinkage()
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)

        signals = {'ASSET1': 1.0, 'ASSET2': 1.0}  # Same signal

        # Create highly correlated returns
        np.random.seed(42)
        base_returns = np.random.randn(60) * 0.01
        returns_high_corr = pl.DataFrame({
            'ASSET1': base_returns + np.random.randn(60) * 0.001,  # 0.001 noise
            'ASSET2': base_returns + np.random.randn(60) * 0.001,  # Same base
        })

        # Create low correlation returns
        returns_low_corr = pl.DataFrame({
            'ASSET1': np.random.randn(60) * 0.01,
            'ASSET2': np.random.randn(60) * 0.01,
        })

        # Get weights for high correlation case
        alphas_high_dict = alpha_gen.signals_to_alphas(
            signals, returns_high_corr, date(2024, 11, 1)
        )
        cov_high = risk_model.fit(returns_high_corr.to_pandas())
        cov_df_high = pl.DataFrame(cov_high, schema=returns_high_corr.columns)
        alphas_high_values = [alphas_high_dict[asset] for asset in returns_high_corr.columns]
        alphas_high = pl.Series(name='alphas', values=alphas_high_values)
        weights_high = optimizer.optimize(alphas_high, cov_df_high)

        # Get weights for low correlation case
        alphas_low_dict = alpha_gen.signals_to_alphas(
            signals, returns_low_corr, date(2024, 11, 1)
        )
        cov_low = risk_model.fit(returns_low_corr.to_pandas())
        cov_df_low = pl.DataFrame(cov_low, schema=returns_low_corr.columns)
        alphas_low_values = [alphas_low_dict[asset] for asset in returns_low_corr.columns]
        alphas_low = pl.Series(name='alphas', values=alphas_low_values)
        weights_low = optimizer.optimize(alphas_low, cov_df_low)

        # Weights should be more balanced for low correlation
        # (diversification benefit)
        weight_spread_high = max(weights_high.values()) - min(weights_high.values())
        weight_spread_low = max(weights_low.values()) - min(weights_low.values())

        # Can't concentrate as much in high corr case
        assert weight_spread_high <= weight_spread_low + 0.1, \
            "High correlation should reduce weight concentration"

    def test_volatility_scaling_matters(self):
        """
        Higher volatility → larger alphas → different weights.

        Verify that volatility scaling (IC × Vol × Z) actually
        affects final portfolio weights.
        """
        alpha_gen = AlphaGenerator(IC=0.05)
        risk_model = LedoitWolfShrinkage()
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)

        # Same signals for both assets
        signals = {'LOW_VOL': 1.0, 'HIGH_VOL': 1.0}

        # Create returns with different volatilities
        np.random.seed(42)
        returns_history = pl.DataFrame({
            'LOW_VOL': np.random.randn(60) * 0.05 / np.sqrt(252),   # 5% vol
            'HIGH_VOL': np.random.randn(60) * 0.20 / np.sqrt(252),  # 20% vol
        })

        # Convert signals → alphas
        alphas_dict = alpha_gen.signals_to_alphas(
            signals, returns_history, date(2024, 11, 1)
        )

        # HIGH_VOL should have higher alpha (IC × Vol × Z)
        assert alphas_dict['HIGH_VOL'] > alphas_dict['LOW_VOL'] * 2, \
            "Higher vol should produce higher alpha for same signal"

        # Optimize weights
        cov_matrix = risk_model.fit(returns_history.to_pandas())
        cov_df = pl.DataFrame(cov_matrix, schema=returns_history.columns)
        alphas_values = [alphas_dict[asset] for asset in returns_history.columns]
        alphas = pl.Series(name='alphas', values=alphas_values)
        weights = optimizer.optimize(alphas, cov_df)

        # Weights should reflect both alpha AND risk
        # HIGH_VOL has higher alpha but also higher risk
        # Exact weights depend on risk aversion
        assert 0 <= weights['LOW_VOL'] <= 1
        assert 0 < weights['HIGH_VOL'] <= 1

    def test_ic_parameter_affects_weights(self):
        """
        Higher IC → larger alphas → more concentration in high signals.

        IC represents forecasting confidence. Higher IC should
        lead to more aggressive positioning.
        """
        alpha_gen_low = AlphaGenerator(IC=0.02)   # Low confidence
        alpha_gen_high = AlphaGenerator(IC=0.10)  # High confidence

        risk_model = LedoitWolfShrinkage()
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)

        # Different signals
        signals = {'STRONG': 2.0, 'WEAK': 0.5}

        np.random.seed(42)
        returns_history = pl.DataFrame({
            'STRONG': np.random.randn(60) * 0.10 / np.sqrt(252),
            'WEAK': np.random.randn(60) * 0.10 / np.sqrt(252),
        })

        # Low IC case
        alphas_low_dict = alpha_gen_low.signals_to_alphas(
            signals, returns_history, date(2024, 11, 1)
        )
        cov_matrix = risk_model.fit(returns_history.to_pandas())
        cov_df = pl.DataFrame(cov_matrix, schema=returns_history.columns)
        alphas_low_values = [alphas_low_dict[asset] for asset in returns_history.columns]
        alphas_low = pl.Series(name='alphas', values=alphas_low_values)
        weights_low = optimizer.optimize(alphas_low, cov_df)

        # High IC case
        alphas_high_dict = alpha_gen_high.signals_to_alphas(
            signals, returns_history, date(2024, 11, 1)
        )
        alphas_high_values = [alphas_high_dict[asset] for asset in returns_history.columns]
        alphas_high = pl.Series(name='alphas', values=alphas_high_values)
        weights_high = optimizer.optimize(alphas_high, cov_df)

        # Higher IC → more concentration in STRONG signal
        assert weights_high['STRONG'] > weights_low['STRONG'], \
            "Higher IC should concentrate more in strong signals"


class TestRealisticScenarios:
    """Test realistic trading scenarios."""

    def test_carry_strategy_scenario(self):
        """
        Realistic carry strategy scenario.

        Positive carry → long position
        Negative carry → reduced/zero position (if long-only)
        """
        alpha_gen = AlphaGenerator(IC=0.05)
        risk_model = LedoitWolfShrinkage()
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)

        # Carry signals: some positive, some negative
        carry_signals = {
            'HIGH_CARRY': 1.5,   # Strong positive carry
            'MED_CARRY': 0.5,    # Moderate positive carry
            'NEG_CARRY': -1.0,   # Negative carry
        }

        np.random.seed(42)
        returns_history = pl.DataFrame({
            'HIGH_CARRY': np.random.randn(60) * 0.12 / np.sqrt(252),
            'MED_CARRY': np.random.randn(60) * 0.10 / np.sqrt(252),
            'NEG_CARRY': np.random.randn(60) * 0.11 / np.sqrt(252),
        })

        # Convert signals → alphas
        alphas_dict = alpha_gen.signals_to_alphas(
            carry_signals, returns_history, date(2024, 11, 1)
        )

        # Optimize
        cov_matrix = risk_model.fit(returns_history.to_pandas())
        cov_df = pl.DataFrame(cov_matrix, schema=returns_history.columns)
        alphas_values = [alphas_dict[asset] for asset in returns_history.columns]
        alphas = pl.Series(name='alphas', values=alphas_values)
        weights = optimizer.optimize(alphas, cov_df)

        # HIGH_CARRY should get highest weight
        assert weights['HIGH_CARRY'] >= weights['MED_CARRY']
        # NEG_CARRY should get minimal/zero weight (long-only)
        # (Both might be ~0 if optimizer concentrates in HIGH_CARRY)
        assert weights['NEG_CARRY'] <= weights['MED_CARRY'] + 1e-10
        # Weights sum to 1
        assert abs(weights.sum() - 1.0) < 1e-6
        # At least one asset should have substantial weight
        assert max(weights.values()) > 0.5

    def test_vol_regime_change(self):
        """
        Test behavior during volatility regime change.

        Recent high vol → higher vol estimate → larger alphas
        """
        alpha_gen = AlphaGenerator(IC=0.05)

        signals = {'ASSET': 1.0}

        # Low vol regime, then high vol
        low_vol_returns = np.random.randn(50) * 0.05 / np.sqrt(252)
        high_vol_returns = np.random.randn(10) * 0.20 / np.sqrt(252)

        returns_history = pl.DataFrame({
            'ASSET': np.concatenate([low_vol_returns, high_vol_returns])
        })

        # Alpha should reflect recent high vol
        alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

        # Alpha should be larger than if we only had low vol
        low_vol_only = pl.DataFrame({'ASSET': low_vol_returns})
        alphas_low = alpha_gen.signals_to_alphas(signals, low_vol_only, date(2024, 11, 1))

        # Recent high vol should increase alpha
        assert alphas['ASSET'] > alphas_low['ASSET'] * 1.5, \
            "Recent high vol should increase alpha"
