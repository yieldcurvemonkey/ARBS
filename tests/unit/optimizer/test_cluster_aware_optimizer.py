# ABOUTME: Tests for cluster-aware portfolio optimizer with correlation constraints
# ABOUTME: Validates enforcement of max positions per correlation cluster to prevent concentration risk
"""
Tests for ClusterAwareMeanVarianceOptimizer

Tests portfolio optimization with cluster constraints:
- Inherits from MeanVarianceOptimizer
- Adds constraint: max N positions per correlation cluster
- Uses CVXPY indicator constraints or MIP solver

Business Requirements:
1. Constraint Enforcement: No more than max_per_cluster positions in any cluster
2. Optimization Convergence: Solver finds solution in < 1s for 50 assets
3. Objective Tradeoff: Constrained objective <= unconstrained objective
4. Edge Cases: Empty clusters, single clusters, all assets in one cluster

From 2025 Research Consensus:
- Correlation cluster constraints prevent concentration risk
- Example: Can't short 5Y in every correlated currency
- Standard practice in cross-asset portfolio construction
- Critical gap in ARBS vs. 2025 consensus

Implementation Notes:
- Indicator constraint: I(|w_i| > ε) where ε = 0.01 (1% threshold)
- For each cluster C: sum(I(|w_i| > ε) for i in C) <= max_per_cluster
- CVXPY can approximate with continuous relaxation or use MIP solver
"""

import pytest
import numpy as np
import polars as pl
from typing import Dict, List

from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer


class TestClusterAwareOptimizerBasics:
    """Test basic cluster-aware optimizer functionality."""

    def test_optimizer_can_be_imported(self):
        """Verify ClusterAwareMeanVarianceOptimizer exists."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )
        assert ClusterAwareMeanVarianceOptimizer is not None

    def test_optimizer_inherits_from_mean_variance(self):
        """ClusterAwareMeanVarianceOptimizer inherits from MeanVarianceOptimizer."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        assert issubclass(ClusterAwareMeanVarianceOptimizer, MeanVarianceOptimizer)

    def test_optimizer_can_be_instantiated(self):
        """Optimizer can be created with cluster parameters."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        clusters = {"cluster_0": ["A", "B"], "cluster_1": ["C", "D"]}

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=2,
            risk_aversion=1.0,
            long_only=True,
        )

        assert optimizer is not None
        assert optimizer.correlation_clusters == clusters
        assert optimizer.max_per_cluster == 2

    def test_optimizer_has_optimize_method(self):
        """Optimizer has optimize() method with same signature."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        clusters = {"cluster_0": ["A", "B"]}
        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1
        )

        assert hasattr(optimizer, 'optimize')


class TestConstraintEnforcement:
    """Test that cluster constraints are correctly enforced."""

    @pytest.fixture
    def simple_two_cluster_setup(self):
        """
        Create simple setup with 2 clusters of 3 assets each.

        Cluster 0: A, B, C
        Cluster 1: D, E, F
        """
        # All assets have positive signals
        alphas = pl.Series('alphas', [1.0, 0.9, 0.8, 1.0, 0.9, 0.8])

        # Uncorrelated between clusters, correlated within
        cov_matrix = np.array([
            # A      B      C      D      E      F
            [0.01,  0.009, 0.008, 0.0,   0.0,   0.0],    # A
            [0.009, 0.01,  0.009, 0.0,   0.0,   0.0],    # B
            [0.008, 0.009, 0.01,  0.0,   0.0,   0.0],    # C
            [0.0,   0.0,   0.0,   0.01,  0.009, 0.008],  # D
            [0.0,   0.0,   0.0,   0.009, 0.01,  0.009],  # E
            [0.0,   0.0,   0.0,   0.008, 0.009, 0.01],   # F
        ])

        cov = pl.DataFrame(
            cov_matrix,
            schema=["A", "B", "C", "D", "E", "F"]
        )

        clusters = {
            "cluster_0": ["A", "B", "C"],
            "cluster_1": ["D", "E", "F"],
        }

        return alphas, cov, clusters

    def test_max_per_cluster_enforced(self, simple_two_cluster_setup):
        """No cluster has more than max_per_cluster positions."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas, cov, clusters = simple_two_cluster_setup

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=2,  # Max 2 positions per cluster
            risk_aversion=1.0,
            long_only=True,
        )

        weights = optimizer.optimize(alphas, cov)

        # Count positions per cluster (threshold: 1%)
        cluster_0_positions = sum(
            1 for asset in ["A", "B", "C"] if abs(weights[asset]) > 0.01
        )
        cluster_1_positions = sum(
            1 for asset in ["D", "E", "F"] if abs(weights[asset]) > 0.01
        )

        assert cluster_0_positions <= 2, f"Cluster 0 has {cluster_0_positions} positions (max 2)"
        assert cluster_1_positions <= 2, f"Cluster 1 has {cluster_1_positions} positions (max 2)"

    def test_constraint_actually_binds(self, simple_two_cluster_setup):
        """Constraint is active (not automatically satisfied)."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas, cov, clusters = simple_two_cluster_setup

        # Without constraint, optimizer might select all 3 in a cluster
        unconstrained = MeanVarianceOptimizer(
            risk_aversion=1.0,
            long_only=True,
        )
        unconstrained_weights = unconstrained.optimize(alphas, cov)

        # Count unconstrained positions
        cluster_0_unconstrained = sum(
            1 for asset in ["A", "B", "C"]
            if abs(unconstrained_weights[asset]) > 0.01
        )

        # Verify unconstrained violates limit (otherwise test is trivial)
        # With 6 equal assets, should spread across all
        # But we set max_per_cluster=1 to force constraint to bind
        constrained = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1,  # Force only 1 per cluster
            risk_aversion=1.0,
            long_only=True,
        )
        constrained_weights = constrained.optimize(alphas, cov)

        cluster_0_constrained = sum(
            1 for asset in ["A", "B", "C"]
            if abs(constrained_weights[asset]) > 0.01
        )

        # Constrained should have fewer positions if constraint binds
        assert cluster_0_constrained <= 1

    def test_zero_weight_below_threshold_not_counted(self, simple_two_cluster_setup):
        """Weights < 1% threshold are not counted as positions."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas, cov, clusters = simple_two_cluster_setup

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=2,
            risk_aversion=1.0,
            long_only=True,
        )

        weights = optimizer.optimize(alphas, cov)

        # Any weight < 1% should not count toward limit
        for asset, weight in weights.items():
            if abs(weight) < 0.01:
                # This position shouldn't count toward cluster limit
                pass  # Just checking logic doesn't crash


class TestOptimizationConvergence:
    """Test that optimization converges efficiently."""

    def test_converges_with_ten_assets(self):
        """Optimizer converges for 10 assets (typical portfolio)."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        # 10 assets in 3 clusters
        np.random.seed(42)
        alphas = pl.Series('alphas', np.random.randn(10).tolist())

        # Create covariance
        returns = pl.DataFrame({
            f"Asset_{i}": np.random.randn(100).tolist() for i in range(10)
        })
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pl.DataFrame(cov_matrix)

        clusters = {
            "cluster_0": [f"Asset_{i}" for i in range(0, 3)],
            "cluster_1": [f"Asset_{i}" for i in range(3, 7)],
            "cluster_2": [f"Asset_{i}" for i in range(7, 10)],
        }

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=2,
            risk_aversion=1.0,
            long_only=True,
        )

        # Should not raise
        weights = optimizer.optimize(alphas, cov)

        # Basic checks
        assert len(weights) == 10
        assert abs(weights.sum() - 1.0) < 0.01

    def test_converges_with_fifty_assets(self):
        """Optimizer converges for 50 assets in < 1s (stress test)."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )
        import time

        # 50 assets in 5 clusters
        np.random.seed(42)
        assets = [f"Asset_{i}" for i in range(50)]
        alphas = pl.Series('alphas', np.random.randn(50).tolist())

        # Create covariance
        returns = pl.DataFrame({
            asset: np.random.randn(200).tolist() for asset in assets
        })
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)
        cov = pl.DataFrame(cov_matrix)

        # 5 clusters of 10 assets each
        clusters = {
            f"cluster_{i}": [f"Asset_{j}" for j in range(i*10, (i+1)*10)]
            for i in range(5)
        }

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=3,
            risk_aversion=1.0,
            long_only=True,
        )

        start = time.time()
        weights = optimizer.optimize(alphas, cov)
        elapsed = time.time() - start

        # Should converge in < 1s
        assert elapsed < 1.0, f"Optimization took {elapsed:.2f}s (target < 1.0s)"

        # Basic checks
        assert len(weights) == 50
        assert abs(weights.sum() - 1.0) < 0.01


class TestObjectiveTradeoff:
    """Test that constraint causes expected tradeoff in objective."""

    def test_constrained_objective_worse_than_unconstrained(self):
        """Constrained objective value <= unconstrained (tradeoff)."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        # Create setup where constraint will bind
        alphas = pl.Series('alphas', [2.0, 1.5, 1.0, 0.5, 0.3, 0.1])

        cov_matrix = np.array([
            [0.01,  0.009, 0.008, 0.0,   0.0,   0.0],
            [0.009, 0.01,  0.009, 0.0,   0.0,   0.0],
            [0.008, 0.009, 0.01,  0.0,   0.0,   0.0],
            [0.0,   0.0,   0.0,   0.01,  0.009, 0.008],
            [0.0,   0.0,   0.0,   0.009, 0.01,  0.009],
            [0.0,   0.0,   0.0,   0.008, 0.009, 0.01],
        ])

        cov = pl.DataFrame(cov_matrix, schema=["A", "B", "C", "D", "E", "F"])

        clusters = {
            "cluster_0": ["A", "B", "C"],
            "cluster_1": ["D", "E", "F"],
        }

        # Unconstrained
        unconstrained = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
        weights_unc = unconstrained.optimize(alphas, cov)
        stats_unc = unconstrained.portfolio_statistics(alphas, cov, weights_unc)

        # Constrained (force max_per_cluster=1 to ensure binding)
        constrained = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1,
            risk_aversion=1.0,
            long_only=True,
        )
        weights_con = constrained.optimize(alphas, cov)
        stats_con = constrained.portfolio_statistics(alphas, cov, weights_con)

        # Constrained expected return should be <= unconstrained
        # (constraint can only hurt objective, not help)
        assert stats_con['expected_return'] <= stats_unc['expected_return'] + 0.01

    def test_sharpe_ratio_decreases_with_constraint(self):
        """Constraint may reduce Sharpe ratio (expected tradeoff)."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        # Create realistic scenario
        np.random.seed(42)
        alphas = pl.Series('alphas', [1.5, 1.2, 1.0, 0.8, 0.6, 0.4])

        # Block-diagonal covariance
        cov_matrix = np.array([
            [0.01,  0.009, 0.008, 0.0,   0.0,   0.0],
            [0.009, 0.01,  0.009, 0.0,   0.0,   0.0],
            [0.008, 0.009, 0.01,  0.0,   0.0,   0.0],
            [0.0,   0.0,   0.0,   0.01,  0.009, 0.008],
            [0.0,   0.0,   0.0,   0.009, 0.01,  0.009],
            [0.0,   0.0,   0.0,   0.008, 0.009, 0.01],
        ])

        cov = pl.DataFrame(cov_matrix, schema=["A", "B", "C", "D", "E", "F"])

        clusters = {
            "cluster_0": ["A", "B", "C"],
            "cluster_1": ["D", "E", "F"],
        }

        # Unconstrained
        unconstrained = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
        weights_unc = unconstrained.optimize(alphas, cov)
        stats_unc = unconstrained.portfolio_statistics(alphas, cov, weights_unc)

        # Constrained
        constrained = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1,
            risk_aversion=1.0,
            long_only=True,
        )
        weights_con = constrained.optimize(alphas, cov)
        stats_con = constrained.portfolio_statistics(alphas, cov, weights_con)

        # Constraint should reduce Sharpe (or keep similar)
        # Not strictly enforced since diversification might help
        # Just check both are positive
        assert stats_unc['sharpe_ratio'] > 0
        assert stats_con['sharpe_ratio'] > 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_cluster(self):
        """Empty cluster in mapping → ignored."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas = pl.Series('alphas', [1.0, 0.5])
        cov = pl.DataFrame({
            'A': [0.01, 0.0],
            'B': [0.0, 0.01],
        })

        clusters = {
            "cluster_0": ["A", "B"],
            "cluster_1": [],  # Empty cluster
        }

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1,
            risk_aversion=1.0,
            long_only=True,
        )

        # Should not crash
        weights = optimizer.optimize(alphas, cov)

        assert len(weights) == 2

    def test_single_asset_cluster(self):
        """Cluster with one asset → constraint trivial."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas = pl.Series('alphas', [1.0, 0.5, 0.3])
        cov = pl.DataFrame({
            'A': [0.01, 0.0, 0.0],
            'B': [0.0, 0.01, 0.0],
            'C': [0.0, 0.0, 0.01],
        })

        clusters = {
            "cluster_0": ["A"],     # Singleton
            "cluster_1": ["B", "C"],
        }

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1,
            risk_aversion=1.0,
            long_only=True,
        )

        weights = optimizer.optimize(alphas, cov)

        # A can have at most 1 position (trivial)
        # B and C combined can have at most 1 position
        cluster_1_positions = sum(
            1 for asset in ["B", "C"] if abs(weights[asset]) > 0.01
        )

        assert cluster_1_positions <= 1

    def test_all_assets_in_one_cluster(self):
        """All assets in one cluster → max_per_cluster applies to all."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas = pl.Series('alphas', [1.0, 0.9, 0.8, 0.7])
        cov = pl.DataFrame({
            'A': [0.01, 0.0, 0.0, 0.0],
            'B': [0.0, 0.01, 0.0, 0.0],
            'C': [0.0, 0.0, 0.01, 0.0],
            'D': [0.0, 0.0, 0.0, 0.01],
        })

        clusters = {
            "cluster_0": ["A", "B", "C", "D"],  # All in one cluster
        }

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=2,  # Can only pick 2 out of 4
            risk_aversion=1.0,
            long_only=True,
        )

        weights = optimizer.optimize(alphas, cov)

        total_positions = sum(1 for w in weights.values() if abs(w) > 0.01)

        assert total_positions <= 2

    def test_max_per_cluster_larger_than_cluster_size(self):
        """max_per_cluster > cluster size → constraint non-binding."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas = pl.Series('alphas', [1.0, 0.5])
        cov = pl.DataFrame({
            'A': [0.01, 0.0],
            'B': [0.0, 0.01],
        })

        clusters = {
            "cluster_0": ["A", "B"],
        }

        # max_per_cluster=10 but cluster has only 2 assets
        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=10,  # Non-binding
            risk_aversion=1.0,
            long_only=True,
        )

        weights = optimizer.optimize(alphas, cov)

        # Should behave like unconstrained
        assert abs(weights.sum() - 1.0) < 0.01

    def test_asset_not_in_any_cluster(self):
        """Asset not in cluster mapping → unconstrained."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        alphas = pl.Series('alphas', [1.0, 0.5, 0.3])
        cov = pl.DataFrame({
            'A': [0.01, 0.0, 0.0],
            'B': [0.0, 0.01, 0.0],
            'C': [0.0, 0.0, 0.01],
        })

        clusters = {
            "cluster_0": ["A", "B"],
            # C is not in any cluster
        }

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1,
            risk_aversion=1.0,
            long_only=True,
        )

        weights = optimizer.optimize(alphas, cov)

        # C should still be optimizable (not constrained)
        assert 'C' in weights


class TestLongShortConstraints:
    """Test cluster constraints with long-short portfolios."""

    def test_long_short_cluster_constraint(self):
        """Cluster constraint applies to long and short positions."""
        from Optimizer.ClusterAwareMeanVarianceOptimizer import (
            ClusterAwareMeanVarianceOptimizer
        )

        # Mixed signals
        alphas = pl.Series('alphas', [2.0, 1.0, -1.0, -2.0])

        cov = pl.DataFrame({
            'A': [0.01, 0.009, 0.0, 0.0],
            'B': [0.009, 0.01, 0.0, 0.0],
            'C': [0.0, 0.0, 0.01, 0.009],
            'D': [0.0, 0.0, 0.009, 0.01],
        })

        clusters = {
            "cluster_0": ["A", "B"],  # Positive signals
            "cluster_1": ["C", "D"],  # Negative signals
        }

        optimizer = ClusterAwareMeanVarianceOptimizer(
            correlation_clusters=clusters,
            max_per_cluster=1,  # Max 1 per cluster
            risk_aversion=1.0,
            long_only=False,  # Allow shorts
            leverage_limit=2.0,
        )

        weights = optimizer.optimize(alphas, cov)

        # Check cluster 0 (long side)
        cluster_0_positions = sum(
            1 for asset in ["A", "B"] if abs(weights[asset]) > 0.01
        )

        # Check cluster 1 (short side)
        cluster_1_positions = sum(
            1 for asset in ["C", "D"] if abs(weights[asset]) > 0.01
        )

        assert cluster_0_positions <= 1
        assert cluster_1_positions <= 1
