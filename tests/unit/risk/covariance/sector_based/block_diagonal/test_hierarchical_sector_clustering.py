# ABOUTME: Tests for HierarchicalSectorClustering sector discovery
# ABOUTME: Validates adaptive thresholding, linkage methods, and cluster quality
"""
Tests for HierarchicalSectorClustering

Tests the hierarchical clustering algorithm for discovering sector structure
from residual correlations, following Žignić et al. (2024).
"""

import pytest
import numpy as np
from Risk.Covariance.SectorBased.BlockDiagonal.HierarchicalSectorClustering import (
    HierarchicalSectorClustering,
    ClusteringResult,
)


class TestHierarchicalSectorClustering:
    """Tests for HierarchicalSectorClustering."""

    def test_clusters_correlated_assets_together(self):
        """Test that highly correlated assets are clustered together."""
        np.random.seed(42)

        # Create 3 groups of 3 assets each with high within-group correlation
        n_days = 200

        # Group 1: Tech stocks
        tech_factor = np.random.randn(n_days, 1)
        tech_residuals = tech_factor @ np.ones((1, 3)) + np.random.randn(n_days, 3) * 0.1

        # Group 2: Financial stocks
        fin_factor = np.random.randn(n_days, 1)
        fin_residuals = fin_factor @ np.ones((1, 3)) + np.random.randn(n_days, 3) * 0.1

        # Group 3: Energy stocks
        energy_factor = np.random.randn(n_days, 1)
        energy_residuals = energy_factor @ np.ones((1, 3)) + np.random.randn(n_days, 3) * 0.1

        # Combine all residuals
        residuals = np.hstack([tech_residuals, fin_residuals, energy_residuals])
        tickers = [
            "AAPL", "MSFT", "GOOGL",  # Tech
            "JPM", "BAC", "C",        # Financials
            "XOM", "CVX", "COP"       # Energy
        ]

        # Execute
        clusterer = HierarchicalSectorClustering(n_clusters=3, linkage_method="ward")
        result = clusterer.fit(residuals, tickers)

        # Verify
        assert isinstance(result, ClusteringResult)
        assert result.n_clusters == 3
        assert len(result.cluster_assignments) == 9

        # Check that within-group assets have same cluster
        tech_clusters = [result.cluster_assignments[t] for t in ["AAPL", "MSFT", "GOOGL"]]
        fin_clusters = [result.cluster_assignments[t] for t in ["JPM", "BAC", "C"]]
        energy_clusters = [result.cluster_assignments[t] for t in ["XOM", "CVX", "COP"]]

        assert len(set(tech_clusters)) == 1, "Tech stocks should be in same cluster"
        assert len(set(fin_clusters)) == 1, "Financial stocks should be in same cluster"
        assert len(set(energy_clusters)) == 1, "Energy stocks should be in same cluster"

        # Check that clusters are different across groups
        all_unique_clusters = {tech_clusters[0], fin_clusters[0], energy_clusters[0]}
        assert len(all_unique_clusters) == 3, "Three distinct clusters should exist"

    def test_automatic_cluster_selection(self):
        """Test cross-validation for optimal cluster count."""
        np.random.seed(42)

        # Create data with clear 2-cluster structure
        n_days = 300

        # Cluster 1: 5 assets
        factor1 = np.random.randn(n_days, 1)
        cluster1 = factor1 @ np.ones((1, 5)) + np.random.randn(n_days, 5) * 0.2

        # Cluster 2: 5 assets
        factor2 = np.random.randn(n_days, 1)
        cluster2 = factor2 @ np.ones((1, 5)) + np.random.randn(n_days, 5) * 0.2

        residuals = np.hstack([cluster1, cluster2])
        tickers = [f"T{i}" for i in range(10)]

        # Execute: Auto-select cluster count
        clusterer = HierarchicalSectorClustering(
            n_clusters=None,  # Auto-select
            max_clusters=8,
            cv_folds=3
        )
        result = clusterer.fit(residuals, tickers)

        # Verify: Should select 2 clusters (or close)
        assert result.n_clusters >= 2, "Should find at least 2 clusters"
        assert result.n_clusters <= 4, "Should not over-cluster (max 4 for 2 true clusters)"

    def test_adaptive_thresholding(self):
        """Test adaptive distance threshold from Žignić et al."""
        np.random.seed(42)

        # Create residuals with varying correlation strengths
        n_days = 250
        n_assets = 8

        # Some pairs have strong correlation, others weak
        residuals = np.random.randn(n_days, n_assets)
        # Make first 4 assets correlated
        common_factor = np.random.randn(n_days, 1)
        residuals[:, :4] += common_factor @ np.ones((1, 4)) * 2.0

        tickers = [f"A{i}" for i in range(n_assets)]

        # Execute
        clusterer = HierarchicalSectorClustering(n_clusters=2, linkage_method="ward")
        result = clusterer.fit(residuals, tickers)

        # Verify: First 4 assets should cluster together
        first_four_clusters = [result.cluster_assignments[f"A{i}"] for i in range(4)]
        assert len(set(first_four_clusters)) == 1, "First 4 assets should be in same cluster"

    def test_different_linkage_methods(self):
        """Test ward vs average vs weighted linkage."""
        np.random.seed(42)

        # Create simple 2-cluster data
        n_days = 200
        factor1 = np.random.randn(n_days, 1)
        cluster1 = factor1 @ np.ones((1, 4)) + np.random.randn(n_days, 4) * 0.1

        factor2 = np.random.randn(n_days, 1)
        cluster2 = factor2 @ np.ones((1, 4)) + np.random.randn(n_days, 4) * 0.1

        residuals = np.hstack([cluster1, cluster2])
        tickers = [f"T{i}" for i in range(8)]

        # Test each linkage method
        for linkage in ["ward", "average", "complete"]:
            clusterer = HierarchicalSectorClustering(
                n_clusters=2,
                linkage_method=linkage
            )
            result = clusterer.fit(residuals, tickers)

            # Verify: All methods should produce valid clustering
            assert result.n_clusters == 2
            assert len(result.cluster_assignments) == 8
            assert result.cluster_quality > 0, f"{linkage} should have positive quality score"

    def test_raises_on_shape_mismatch(self):
        """Test error when residuals shape doesn't match tickers."""
        residuals = np.random.randn(100, 5)
        tickers = ["A", "B", "C"]  # Only 3 tickers for 5 columns

        clusterer = HierarchicalSectorClustering(n_clusters=2)

        with pytest.raises(ValueError, match="shape.*match"):
            clusterer.fit(residuals, tickers)

    def test_raises_on_insufficient_data(self):
        """Test error when T < 2 (too few observations)."""
        residuals = np.random.randn(1, 5)  # Only 1 observation
        tickers = [f"T{i}" for i in range(5)]

        clusterer = HierarchicalSectorClustering(n_clusters=2)

        with pytest.raises(ValueError, match="Insufficient.*observations"):
            clusterer.fit(residuals, tickers)

    def test_handles_single_cluster(self):
        """Test behavior when n_clusters=1."""
        np.random.seed(42)
        residuals = np.random.randn(100, 5)
        tickers = [f"T{i}" for i in range(5)]

        clusterer = HierarchicalSectorClustering(n_clusters=1)
        result = clusterer.fit(residuals, tickers)

        # Verify: All assets in same cluster
        assert result.n_clusters == 1
        unique_clusters = set(result.cluster_assignments.values())
        assert len(unique_clusters) == 1

    def test_cluster_quality_metric(self):
        """Test that cluster quality metric is reasonable."""
        np.random.seed(42)

        # Good clustering: distinct groups
        n_days = 200
        factor1 = np.random.randn(n_days, 1)
        cluster1 = factor1 @ np.ones((1, 3)) + np.random.randn(n_days, 3) * 0.1
        factor2 = np.random.randn(n_days, 1)
        cluster2 = factor2 @ np.ones((1, 3)) + np.random.randn(n_days, 3) * 0.1

        good_residuals = np.hstack([cluster1, cluster2])

        # Bad clustering: all uncorrelated
        bad_residuals = np.random.randn(n_days, 6)

        tickers = [f"T{i}" for i in range(6)]

        # Execute
        clusterer = HierarchicalSectorClustering(n_clusters=2)
        good_result = clusterer.fit(good_residuals, tickers)
        bad_result = clusterer.fit(bad_residuals, tickers)

        # Verify: Good clustering should have higher quality
        assert good_result.cluster_quality > bad_result.cluster_quality, \
            "Distinct clusters should have better quality score"

    def test_linkage_matrix_structure(self):
        """Test that linkage matrix has correct structure."""
        np.random.seed(42)
        residuals = np.random.randn(100, 5)
        tickers = [f"T{i}" for i in range(5)]

        clusterer = HierarchicalSectorClustering(n_clusters=2)
        result = clusterer.fit(residuals, tickers)

        # Verify: Linkage matrix should have (n-1) rows and 4 columns
        # Format: [idx1, idx2, distance, sample_count]
        assert result.linkage_matrix.shape == (4, 4), \
            "Linkage matrix should have (n_assets-1) rows and 4 columns"

    def test_deterministic_with_seed(self):
        """Test that results are deterministic with same random seed."""
        residuals = np.random.randn(100, 5)
        tickers = [f"T{i}" for i in range(5)]

        # Run twice with same data
        clusterer1 = HierarchicalSectorClustering(n_clusters=2, linkage_method="ward")
        result1 = clusterer1.fit(residuals.copy(), tickers)

        clusterer2 = HierarchicalSectorClustering(n_clusters=2, linkage_method="ward")
        result2 = clusterer2.fit(residuals.copy(), tickers)

        # Verify: Results should be identical
        assert result1.cluster_assignments == result2.cluster_assignments
        assert result1.n_clusters == result2.n_clusters
