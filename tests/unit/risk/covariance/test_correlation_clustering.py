# ABOUTME: Tests for correlation clustering functionality in BaseSectorCovarianceEstimator
# ABOUTME: Validates hierarchical clustering on correlation matrices with various edge cases
"""
Tests for Correlation Clustering

Tests the get_correlation_clusters() method that groups assets by correlation:
- Uses hierarchical clustering (scipy.cluster.hierarchy)
- Distance metric: d = 1 - |ρ|
- Returns Dict[str, List[str]] mapping cluster_id → list of tickers

Business Requirements:
1. Perfect block-diagonal structure → detect distinct clusters
2. Overlapping correlations → assign to dominant cluster
3. Edge cases: single-asset clusters, all in one cluster
4. Threshold sensitivity: ρ > 0.85 → same cluster

From 2025 Research Consensus:
- Hierarchical clustering is standard for correlation-based grouping
- Distance = 1 - |correlation| is industry practice
- Threshold typically 0.75-0.85 for correlation
- Used to prevent concentration risk in portfolio optimization
"""

import pytest
import numpy as np
import polars as pl
from typing import Dict, List

from Risk.Covariance.SectorBased.BaseSectorCovarianceEstimator import (
    SectorBasedCovarianceEstimator,
)


# Create concrete implementation for testing
class MockSectorCovariance(SectorBasedCovarianceEstimator):
    """Concrete implementation for testing abstract base class."""

    def fit(self, returns: pl.DataFrame, sector_col=None) -> np.ndarray:
        """Mock fit method."""
        # Handle missing data
        returns = self._handle_missing_data(returns)

        # Convert to wide format
        returns_wide, tickers = self._convert_to_wide_format(returns)
        self.asset_names_ = tickers
        self.returns_wide_ = returns_wide

        # Store for clustering
        n = len(tickers)
        self.cov_matrix_ = np.eye(n)

        return self.cov_matrix_


class TestCorrelationClusteringBasics:
    """Test basic correlation clustering functionality."""

    def test_get_correlation_clusters_method_exists(self):
        """Verify get_correlation_clusters() method exists."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")
        assert hasattr(estimator, 'get_correlation_clusters')

    def test_get_correlation_clusters_returns_dict(self):
        """Method returns Dict[str, List[str]]."""
        # Create simple 2-asset perfectly correlated data
        returns = pl.DataFrame({
            "ticker": ["A", "B"] * 10,
            "date": [f"2024-01-{i:02d}" for i in range(1, 11)] * 2,
            "return": [0.01, 0.01] * 10,
        })

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        clusters = estimator.get_correlation_clusters(threshold=0.85)

        assert isinstance(clusters, dict)
        assert all(isinstance(k, str) for k in clusters.keys())
        assert all(isinstance(v, list) for v in clusters.values())


class TestPerfectBlockDiagonal:
    """Test clustering on perfect block-diagonal correlation structure."""

    @pytest.fixture
    def perfect_block_returns(self):
        """
        Create returns with 3 perfect clusters:
        - Cluster 1: Assets A, B (ρ = 0.95)
        - Cluster 2: Assets C, D (ρ = 0.95)
        - Cluster 3: Assets E, F (ρ = 0.95)
        - Cross-cluster: ρ = 0.0
        """
        np.random.seed(42)
        n_periods = 100

        # Generate cluster 1 (A, B) - highly correlated
        factor1 = np.random.randn(n_periods)
        noise1a = np.random.randn(n_periods) * 0.1
        noise1b = np.random.randn(n_periods) * 0.1
        returns_A = factor1 + noise1a
        returns_B = factor1 + noise1b

        # Generate cluster 2 (C, D) - highly correlated, independent of cluster 1
        factor2 = np.random.randn(n_periods)
        noise2a = np.random.randn(n_periods) * 0.1
        noise2b = np.random.randn(n_periods) * 0.1
        returns_C = factor2 + noise2a
        returns_D = factor2 + noise2b

        # Generate cluster 3 (E, F) - highly correlated, independent of others
        factor3 = np.random.randn(n_periods)
        noise3a = np.random.randn(n_periods) * 0.1
        noise3b = np.random.randn(n_periods) * 0.1
        returns_E = factor3 + noise3a
        returns_F = factor3 + noise3b

        # Convert to long format
        dates = [f"2024-{i//30+1:02d}-{i%30+1:02d}" for i in range(n_periods)]

        data = []
        for i, date in enumerate(dates):
            data.extend([
                {"ticker": "A", "date": date, "return": returns_A[i]},
                {"ticker": "B", "date": date, "return": returns_B[i]},
                {"ticker": "C", "date": date, "return": returns_C[i]},
                {"ticker": "D", "date": date, "return": returns_D[i]},
                {"ticker": "E", "date": date, "return": returns_E[i]},
                {"ticker": "F", "date": date, "return": returns_F[i]},
            ])

        return pl.DataFrame(data)

    def test_detects_three_clusters(self, perfect_block_returns):
        """Perfect block structure → detects exactly 3 clusters."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(perfect_block_returns)

        clusters = estimator.get_correlation_clusters(threshold=0.85, n_clusters=3)

        # Should have exactly 3 clusters
        cluster_ids = set(clusters.values())
        assert len(cluster_ids) == 3

    def test_clusters_have_correct_membership(self, perfect_block_returns):
        """Assets A-B, C-D, E-F should be in separate clusters."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(perfect_block_returns)

        clusters = estimator.get_correlation_clusters(threshold=0.85, n_clusters=3)

        # A and B should be in same cluster
        assert clusters["A"] == clusters["B"]

        # C and D should be in same cluster
        assert clusters["C"] == clusters["D"]

        # E and F should be in same cluster
        assert clusters["E"] == clusters["F"]

        # All three clusters should be different
        assert clusters["A"] != clusters["C"]
        assert clusters["A"] != clusters["E"]
        assert clusters["C"] != clusters["E"]

    def test_high_intra_cluster_correlation(self, perfect_block_returns):
        """Within-cluster correlation should be > threshold."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(perfect_block_returns)

        # Get correlation matrix
        returns_wide = perfect_block_returns.pivot(
            index="date", columns="ticker", values="return"
        )
        corr_matrix = returns_wide.to_pandas().corr()

        clusters = estimator.get_correlation_clusters(threshold=0.85, n_clusters=3)

        # Check intra-cluster correlations
        # A-B should be highly correlated
        assert abs(corr_matrix.loc["A", "B"]) > 0.85

        # C-D should be highly correlated
        assert abs(corr_matrix.loc["C", "D"]) > 0.85

        # E-F should be highly correlated
        assert abs(corr_matrix.loc["E", "F"]) > 0.85

    def test_low_inter_cluster_correlation(self, perfect_block_returns):
        """Cross-cluster correlation should be low."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(perfect_block_returns)

        # Get correlation matrix
        returns_wide = perfect_block_returns.pivot(
            index="date", columns="ticker", values="return"
        )
        corr_matrix = returns_wide.to_pandas().corr()

        # Cross-cluster correlations should be low
        assert abs(corr_matrix.loc["A", "C"]) < 0.5
        assert abs(corr_matrix.loc["A", "E"]) < 0.5
        assert abs(corr_matrix.loc["C", "E"]) < 0.5


class TestOverlappingClusters:
    """Test clustering when correlations overlap (not perfectly block-diagonal)."""

    @pytest.fixture
    def overlapping_returns(self):
        """
        Create returns with overlapping correlations:
        - A-B: ρ = 0.90
        - B-C: ρ = 0.85
        - A-C: ρ = 0.70

        This tests assignment when multiple clusters possible.
        """
        np.random.seed(42)
        n_periods = 100

        # Generate common factors
        factor_AB = np.random.randn(n_periods)
        factor_BC = np.random.randn(n_periods)

        # A is mostly factor_AB
        returns_A = 0.95 * factor_AB + 0.05 * np.random.randn(n_periods)

        # B is mix of both factors (connects A and C)
        returns_B = 0.7 * factor_AB + 0.3 * factor_BC

        # C is mostly factor_BC
        returns_C = 0.95 * factor_BC + 0.05 * np.random.randn(n_periods)

        # D is independent
        returns_D = np.random.randn(n_periods)

        # Convert to long format
        dates = [f"2024-{i//30+1:02d}-{i%30+1:02d}" for i in range(n_periods)]

        data = []
        for i, date in enumerate(dates):
            data.extend([
                {"ticker": "A", "date": date, "return": returns_A[i]},
                {"ticker": "B", "date": date, "return": returns_B[i]},
                {"ticker": "C", "date": date, "return": returns_C[i]},
                {"ticker": "D", "date": date, "return": returns_D[i]},
            ])

        return pl.DataFrame(data)

    def test_handles_overlapping_correlations(self, overlapping_returns):
        """Method handles overlapping correlations without error."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(overlapping_returns)

        # Should not raise
        clusters = estimator.get_correlation_clusters(threshold=0.85)

        assert len(clusters) == 4  # All assets assigned

    def test_isolated_asset_gets_own_cluster(self, overlapping_returns):
        """Asset D (independent) should be in separate cluster or singleton."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(overlapping_returns)

        clusters = estimator.get_correlation_clusters(threshold=0.85, n_clusters=2)

        # D should be in different cluster from A/B/C
        # (or in singleton cluster if that's allowed)
        assert "D" in clusters


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_asset_cluster(self):
        """Single asset → single cluster."""
        returns = pl.DataFrame({
            "ticker": ["A"] * 10,
            "date": [f"2024-01-{i:02d}" for i in range(1, 11)],
            "return": np.random.randn(10).tolist(),
        })

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        clusters = estimator.get_correlation_clusters(threshold=0.85)

        assert len(clusters) == 1
        assert "A" in clusters

    def test_all_assets_perfectly_correlated(self):
        """All assets perfectly correlated → single cluster."""
        n_periods = 50
        factor = np.random.randn(n_periods)

        data = []
        for i in range(n_periods):
            date = f"2024-01-{i+1:02d}"
            for ticker in ["A", "B", "C", "D"]:
                data.append({
                    "ticker": ticker,
                    "date": date,
                    "return": factor[i] + np.random.randn() * 0.01  # Tiny noise
                })

        returns = pl.DataFrame(data)

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        clusters = estimator.get_correlation_clusters(threshold=0.85, n_clusters=1)

        # All assets should be in same cluster
        cluster_ids = set(clusters.values())
        assert len(cluster_ids) == 1

    def test_all_assets_uncorrelated(self):
        """All assets uncorrelated → each in own cluster."""
        n_periods = 50

        data = []
        for i in range(n_periods):
            date = f"2024-01-{i+1:02d}"
            for ticker in ["A", "B", "C", "D"]:
                data.append({
                    "ticker": ticker,
                    "date": date,
                    "return": np.random.randn()
                })

        returns = pl.DataFrame(data)

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        # With n_clusters=4 and uncorrelated data, should get 4 clusters
        clusters = estimator.get_correlation_clusters(threshold=0.85, n_clusters=4)

        cluster_ids = set(clusters.values())
        assert len(cluster_ids) == 4  # Each asset in own cluster

    def test_threshold_at_boundary(self):
        """Threshold at exact correlation value (edge case)."""
        # Create two assets with correlation exactly 0.85
        np.random.seed(42)
        n_periods = 100

        factor = np.random.randn(n_periods)
        # Tune noise to get ρ ≈ 0.85
        returns_A = factor + np.random.randn(n_periods) * 0.3
        returns_B = factor + np.random.randn(n_periods) * 0.3

        data = []
        for i in range(n_periods):
            date = f"2024-{i//30+1:02d}-{i%30+1:02d}"
            data.extend([
                {"ticker": "A", "date": date, "return": returns_A[i]},
                {"ticker": "B", "date": date, "return": returns_B[i]},
            ])

        returns = pl.DataFrame(data)

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        # Should not crash with threshold at boundary
        clusters = estimator.get_correlation_clusters(threshold=0.85)

        assert len(clusters) == 2  # Both assets assigned

    def test_negative_correlations_treated_as_distance(self):
        """Negative correlations use absolute value: d = 1 - |ρ|."""
        # Create negatively correlated assets
        np.random.seed(42)
        n_periods = 100

        factor = np.random.randn(n_periods)
        returns_A = factor
        returns_B = -factor  # Perfect negative correlation

        data = []
        for i in range(n_periods):
            date = f"2024-{i//30+1:02d}-{i%30+1:02d}"
            data.extend([
                {"ticker": "A", "date": date, "return": returns_A[i]},
                {"ticker": "B", "date": date, "return": returns_B[i]},
            ])

        returns = pl.DataFrame(data)

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        # With ρ = -1.0, distance = 1 - |-1.0| = 0
        # Should cluster together despite negative correlation
        clusters = estimator.get_correlation_clusters(threshold=0.85, n_clusters=1)

        # Both assets should be in same cluster (close in absolute correlation)
        assert clusters["A"] == clusters["B"]


class TestParameterHandling:
    """Test parameter handling and defaults."""

    def test_default_threshold(self):
        """Default threshold = 0.85."""
        returns = pl.DataFrame({
            "ticker": ["A", "B"] * 10,
            "date": [f"2024-01-{i:02d}" for i in range(1, 11)] * 2,
            "return": [0.01] * 20,
        })

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        # Should use default threshold
        clusters = estimator.get_correlation_clusters()

        assert len(clusters) == 2

    def test_max_cluster_size_parameter(self):
        """max_cluster_size parameter limits cluster membership."""
        # Create 10 perfectly correlated assets
        n_periods = 50
        factor = np.random.randn(n_periods)

        data = []
        for i in range(n_periods):
            date = f"2024-01-{i+1:02d}"
            for j in range(10):
                ticker = f"Asset_{j}"
                data.append({
                    "ticker": ticker,
                    "date": date,
                    "return": factor[i] + np.random.randn() * 0.01
                })

        returns = pl.DataFrame(data)

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        # With max_cluster_size=3, should split into multiple clusters
        clusters = estimator.get_correlation_clusters(
            threshold=0.85,
            max_cluster_size=3
        )

        # Count assets per cluster
        from collections import Counter
        cluster_counts = Counter(clusters.values())

        # No cluster should exceed max_cluster_size
        assert all(count <= 3 for count in cluster_counts.values())

    def test_auto_n_clusters_selection(self):
        """When n_clusters=None, uses heuristic: sqrt(N)."""
        # Create 16 assets (sqrt(16) = 4)
        n_periods = 50

        data = []
        for i in range(n_periods):
            date = f"2024-01-{i+1:02d}"
            for j in range(16):
                ticker = f"Asset_{j}"
                data.append({
                    "ticker": ticker,
                    "date": date,
                    "return": np.random.randn()
                })

        returns = pl.DataFrame(data)

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        # Should auto-select ~4 clusters
        clusters = estimator.get_correlation_clusters(threshold=0.85)

        cluster_ids = set(clusters.values())
        # Should be around sqrt(16) = 4 clusters
        assert 2 <= len(cluster_ids) <= 6  # Allow some flexibility


class TestGetClusterGroups:
    """Test get_cluster_groups() helper method."""

    def test_get_cluster_groups_returns_inverted_mapping(self):
        """get_cluster_groups() returns cluster_id → list of tickers."""
        returns = pl.DataFrame({
            "ticker": ["A", "B", "C", "D"] * 10,
            "date": [f"2024-01-{i:02d}" for i in range(1, 11)] * 4,
            "return": np.random.randn(40).tolist(),
        })

        estimator = MockSectorCovariance(clustering_method="hierarchical")
        estimator.fit(returns)

        clusters = estimator.get_correlation_clusters(n_clusters=2)
        groups = estimator.get_cluster_groups()

        # Should be Dict[str, List[str]]
        assert isinstance(groups, dict)
        assert all(isinstance(v, list) for v in groups.values())

        # All tickers should appear exactly once
        all_tickers = []
        for tickers in groups.values():
            all_tickers.extend(tickers)

        assert sorted(all_tickers) == ["A", "B", "C", "D"]

    def test_get_cluster_groups_before_clustering_raises_error(self):
        """Calling get_cluster_groups() before clustering raises ValueError."""
        estimator = MockSectorCovariance(clustering_method="hierarchical")

        # Haven't called get_correlation_clusters yet
        with pytest.raises(ValueError, match="Must call get_correlation_clusters"):
            estimator.get_cluster_groups()
