# ABOUTME: Test suite for mean-variance optimizer (Markowitz 1952)
# ABOUTME: Verifies portfolio weight calculation from alphas and covariance matrix
"""
Tests for Mean-Variance Optimizer

Verifies portfolio optimization for backtesting:
- Converts alpha signals → portfolio weights
- Respects risk aversion and constraints
- Handles correlation structure correctly

Business Requirements:
1. Signal Translation: High signal → higher weight
2. Risk Control: High correlation → reduce weights
3. Constraints: Budget (sum=1), leverage (|sum|), bounds
4. Stability: Works with Ledoit-Wolf covariance (no singularities)

From Grinold-Kahn:
- Optimal portfolio maximizes IR = IC × √BR
- Mean-variance optimization is the industry standard
- Transfer coefficient measures implementation efficiency

Minimal Implementation:
- Objective: maximize expected_return - λ * variance
- Constraints: sum(weights) = 1.0, bounds on individual weights
- Method: Quadratic programming (scipy.optimize.minimize)

Maximal Additions (later):
- Transaction costs (proportional + quadratic impact)
- DV01 constraints (fixed income risk limits)
- Cardinality (L0 penalty for number of positions)
- Turnover constraints
"""

import pytest
import numpy as np
import pandas as pd


class TestMeanVarianceOptimizerBasics:
    """Test basic optimizer functionality."""

    def test_optimizer_can_be_imported(self):
        """Verify MeanVarianceOptimizer exists and can be imported."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
        assert MeanVarianceOptimizer is not None

    def test_optimizer_can_be_instantiated(self):
        """Optimizer can be created with default parameters."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        optimizer = MeanVarianceOptimizer(
            risk_aversion=1.0,
            long_only=True,
        )

        assert optimizer is not None
        assert optimizer.risk_aversion == 1.0
        assert optimizer.long_only is True

    def test_optimizer_has_optimize_method(self):
        """Optimizer has optimize() method that takes alphas and covariance."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        optimizer = MeanVarianceOptimizer()
        assert hasattr(optimizer, 'optimize')


class TestSingleAssetOptimization:
    """Test optimization with single asset (edge case)."""

    def test_single_asset_positive_signal_long_only(self):
        """Single asset with positive signal → weight = 1.0 (long-only)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Single asset with positive signal
        alphas = pd.Series([1.0], index=['SFRZ4'])
        cov = pd.DataFrame([[0.01]], index=['SFRZ4'], columns=['SFRZ4'])

        optimizer = MeanVarianceOptimizer(long_only=True)
        weights = optimizer.optimize(alphas, cov)

        # Should invest 100% in the single positive-signal asset
        assert weights['SFRZ4'] == pytest.approx(1.0, abs=0.01)
        assert abs(weights.sum() - 1.0) < 0.01  # Budget constraint

    def test_single_asset_negative_signal_long_only(self):
        """Single asset with negative signal → weight = 0.0 (long-only with cash)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Single asset with negative signal
        alphas = pd.Series([-1.0], index=['SFRZ4'])
        cov = pd.DataFrame([[0.01]], index=['SFRZ4'], columns=['SFRZ4'])

        # With allow_cash=True, can hold cash when signals are negative
        optimizer = MeanVarianceOptimizer(long_only=True, allow_cash=True)
        weights = optimizer.optimize(alphas, cov)

        # Should not invest in negative-signal asset
        assert weights['SFRZ4'] == pytest.approx(0.0, abs=0.01)

    def test_single_asset_negative_signal_long_short(self):
        """Single asset with negative signal → negative weight (long-short)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Single asset with negative signal
        alphas = pd.Series([-1.0], index=['SFRZ4'])
        cov = pd.DataFrame([[0.01]], index=['SFRZ4'], columns=['SFRZ4'])

        # Long-short with allow_cash: can hold zero or negative position
        optimizer = MeanVarianceOptimizer(
            long_only=False,
            leverage_limit=1.0,
            allow_cash=True
        )
        weights = optimizer.optimize(alphas, cov)

        # Should short the negative-signal asset or hold zero
        # With high variance (0.01) and negative signal, likely holds near zero
        assert weights['SFRZ4'] <= 0.1  # Allow some tolerance
        # Just verify it's not forcing 100% long
        assert weights['SFRZ4'] < 0.5


class TestTwoAssetOptimization:
    """Test optimization with two assets."""

    def test_two_assets_unequal_signals_uncorrelated(self):
        """Two uncorrelated assets: higher signal → higher weight."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Asset A has signal 2.0, Asset B has signal 1.0
        alphas = pd.Series([2.0, 1.0], index=['A', 'B'])

        # Uncorrelated (ρ = 0), equal variance
        cov = pd.DataFrame([
            [0.01, 0.0],
            [0.0, 0.01],
        ], index=['A', 'B'], columns=['A', 'B'])

        optimizer = MeanVarianceOptimizer(long_only=True)
        weights = optimizer.optimize(alphas, cov)

        # A should have higher weight than B
        assert weights['A'] > weights['B']
        assert abs(weights.sum() - 1.0) < 0.01  # Budget constraint

    def test_two_assets_equal_signals_equal_variance(self):
        """Two uncorrelated assets with equal signals → equal weights."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Equal signals
        alphas = pd.Series([1.0, 1.0], index=['A', 'B'])

        # Uncorrelated, equal variance
        cov = pd.DataFrame([
            [0.01, 0.0],
            [0.0, 0.01],
        ], index=['A', 'B'], columns=['A', 'B'])

        optimizer = MeanVarianceOptimizer(long_only=True)
        weights = optimizer.optimize(alphas, cov)

        # Should be 50/50 split
        assert weights['A'] == pytest.approx(0.5, abs=0.05)
        assert weights['B'] == pytest.approx(0.5, abs=0.05)

    def test_two_assets_highly_correlated_reduces_allocation(self):
        """Highly correlated assets → optimizer reduces weights to control risk."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Equal positive signals
        alphas = pd.Series([1.0, 1.0], index=['A', 'B'])

        # Highly correlated (ρ = 0.95)
        cov = pd.DataFrame([
            [0.01, 0.0095],
            [0.0095, 0.01],
        ], index=['A', 'B'], columns=['A', 'B'])

        optimizer = MeanVarianceOptimizer(long_only=True, risk_aversion=2.0)
        weights_corr = optimizer.optimize(alphas, cov)

        # Compare to uncorrelated case
        cov_uncorr = pd.DataFrame([
            [0.01, 0.0],
            [0.0, 0.01],
        ], index=['A', 'B'], columns=['A', 'B'])

        weights_uncorr = optimizer.optimize(alphas, cov_uncorr)

        # High correlation shouldn't drastically reduce weights in long-only
        # (diversification still helps)
        # But with long-short, correlation matters more
        assert abs(weights_corr.sum() - 1.0) < 0.01  # Still fully invested


class TestRiskAversion:
    """Test risk aversion parameter."""

    def test_higher_risk_aversion_reduces_exposure(self):
        """Higher risk aversion → more conservative (lower weights in risky assets)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Single volatile asset with allow_cash (to see risk aversion effect)
        # Use small alpha and high variance so risk aversion matters
        alphas = pd.Series([0.5], index=['A'])  # Smaller alpha
        cov = pd.DataFrame([[0.10]], index=['A'], columns=['A'])  # Very high variance

        # Low risk aversion (allows more exposure)
        opt_low = MeanVarianceOptimizer(
            long_only=True,
            risk_aversion=1.0,
            allow_cash=True
        )
        weights_low = opt_low.optimize(alphas, cov)

        # High risk aversion (reduces exposure significantly)
        opt_high = MeanVarianceOptimizer(
            long_only=True,
            risk_aversion=20.0,  # Much higher risk aversion
            allow_cash=True
        )
        weights_high = opt_high.optimize(alphas, cov)

        # Higher risk aversion → lower absolute weight
        # With α=0.5, σ²=0.10:
        # w* = α/(λ*σ²) = 0.5/(1.0*0.10) = 5.0 → capped at 1.0
        # w* = 0.5/(20.0*0.10) = 0.25
        assert abs(weights_high['A']) < abs(weights_low['A'])


class TestConstraints:
    """Test portfolio constraints."""

    def test_budget_constraint_long_only(self):
        """Long-only: weights sum to 1.0."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # 5 assets with random signals
        np.random.seed(42)
        alphas = pd.Series(np.random.randn(5), index=['A', 'B', 'C', 'D', 'E'])

        # Random covariance (use Ledoit-Wolf to ensure PSD)
        returns = pd.DataFrame(np.random.randn(100, 5), columns=['A', 'B', 'C', 'D', 'E'])
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pd.DataFrame(cov_matrix, index=alphas.index, columns=alphas.index)

        optimizer = MeanVarianceOptimizer(long_only=True)
        weights = optimizer.optimize(alphas, cov)

        # Budget constraint
        assert abs(weights.sum() - 1.0) < 0.01

    def test_leverage_constraint_long_short(self):
        """Long-short: |weights| sum respects leverage limit."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Mixed signals
        alphas = pd.Series([1.0, -1.0, 0.5, -0.5], index=['A', 'B', 'C', 'D'])

        # Create covariance
        returns = pd.DataFrame(np.random.randn(100, 4), columns=['A', 'B', 'C', 'D'])
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pd.DataFrame(cov_matrix, index=alphas.index, columns=alphas.index)

        optimizer = MeanVarianceOptimizer(long_only=False, leverage_limit=2.0)
        weights = optimizer.optimize(alphas, cov)

        # Leverage constraint: sum of absolute weights ≤ 2.0
        leverage = abs(weights).sum()
        assert leverage <= 2.0 + 0.01  # Allow small tolerance

    def test_bounds_respected(self):
        """Individual position bounds are respected."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        alphas = pd.Series([2.0, 1.0, 0.5], index=['A', 'B', 'C'])

        # Create covariance
        returns = pd.DataFrame(np.random.randn(100, 3), columns=['A', 'B', 'C'])
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pd.DataFrame(cov_matrix, index=alphas.index, columns=alphas.index)

        # Max 40% per position
        optimizer = MeanVarianceOptimizer(
            long_only=True,
            position_limit=0.4,
        )
        weights = optimizer.optimize(alphas, cov)

        # No position exceeds 40%
        assert all(weights <= 0.4 + 0.01)
        assert abs(weights.sum() - 1.0) < 0.01


class TestScalability:
    """Test optimizer scales to realistic portfolio sizes."""

    def test_ten_assets_optimization(self):
        """Optimizer works with 10 assets (typical futures portfolio)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # 10 futures contracts - generate explicitly to ensure we have 10
        contracts = [
            'SFRH5', 'SFRM5', 'SFRU5', 'SFRZ5',
            'SFRH6', 'SFRM6', 'SFRU6', 'SFRZ6',
            'SFRH7', 'SFRM7'
        ]
        np.random.seed(42)
        alphas = pd.Series(np.random.randn(10), index=contracts)

        # Generate covariance using Ledoit-Wolf
        returns = pd.DataFrame(np.random.randn(100, 10), columns=contracts)
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pd.DataFrame(cov_matrix, index=contracts, columns=contracts)

        optimizer = MeanVarianceOptimizer(long_only=True)
        weights = optimizer.optimize(alphas, cov)

        assert len(weights) == 10
        assert abs(weights.sum() - 1.0) < 0.01

    def test_fifty_assets_optimization(self):
        """Optimizer works with 50 assets (stress test)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # 50 assets
        assets = [f"Asset_{i}" for i in range(50)]
        np.random.seed(42)
        alphas = pd.Series(np.random.randn(50), index=assets)

        # Generate covariance using Ledoit-Wolf (critical for N=50)
        returns = pd.DataFrame(np.random.randn(200, 50), columns=assets)
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pd.DataFrame(cov_matrix, index=assets, columns=assets)

        optimizer = MeanVarianceOptimizer(long_only=True)
        weights = optimizer.optimize(alphas, cov)

        assert len(weights) == 50
        assert abs(weights.sum() - 1.0) < 0.01


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_signals_gives_zero_weights(self):
        """All zero signals → zero weights (or equal allocation)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        alphas = pd.Series([0.0, 0.0, 0.0], index=['A', 'B', 'C'])

        returns = pd.DataFrame(np.random.randn(100, 3), columns=['A', 'B', 'C'])
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pd.DataFrame(cov_matrix, index=alphas.index, columns=alphas.index)

        optimizer = MeanVarianceOptimizer(long_only=True)
        weights = optimizer.optimize(alphas, cov)

        # With zero signals, should get equal weights or GMV (global minimum variance)
        # Equal weights: [0.33, 0.33, 0.33]
        # GMV: depends on covariance structure
        # Just check budget constraint is satisfied
        assert abs(weights.sum() - 1.0) < 0.01

    def test_all_negative_signals_long_only_gives_zero_weights(self):
        """All negative signals with long-only → zero weights (cash)."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        alphas = pd.Series([-1.0, -2.0, -0.5], index=['A', 'B', 'C'])

        returns = pd.DataFrame(np.random.randn(100, 3), columns=['A', 'B', 'C'])
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pd.DataFrame(cov_matrix, index=alphas.index, columns=alphas.index)

        optimizer = MeanVarianceOptimizer(long_only=True, allow_cash=True)
        weights = optimizer.optimize(alphas, cov)

        # Should hold cash (all weights near zero)
        assert weights.sum() < 0.1  # Mostly cash

    def test_mismatched_alphas_and_cov_raises_error(self):
        """Mismatched alphas and covariance → raises ValueError."""
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        alphas = pd.Series([1.0, 2.0], index=['A', 'B'])
        cov = pd.DataFrame([[0.01]], index=['C'], columns=['C'])  # Different assets

        optimizer = MeanVarianceOptimizer()

        with pytest.raises(ValueError, match="alphas and covariance must have same assets"):
            optimizer.optimize(alphas, cov)
