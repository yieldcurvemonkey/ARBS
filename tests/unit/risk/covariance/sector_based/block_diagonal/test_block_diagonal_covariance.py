# ABOUTME: Tests for BlockDiagonalCovariance estimator
# ABOUTME: Validates block-diagonal structure, shrinkage, and positive definiteness
"""
Tests for BlockDiagonalCovariance

Tests the block-diagonal factor model covariance estimator from Žignić et al. (2024):
    Σ = B·Cov(F)·B^T + block_diag(Ψ₁, ..., Ψₘ)
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta
from Risk.Covariance.SectorBased.BlockDiagonal.BlockDiagonalCovariance import (
    BlockDiagonalCovariance,
)


class TestBlockDiagonalCovariance:
    """Tests for BlockDiagonalCovariance."""

    def test_estimate_with_predefined_sectors(self):
        """Test estimation using predefined sector column."""
        # Create synthetic data with 2 sectors, 3 assets each
        np.random.seed(42)
        n_days = 200
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        # Sector 1: Tech stocks
        tech_returns = np.random.randn(n_days, 3) * 0.02
        # Sector 2: Financial stocks
        fin_returns = np.random.randn(n_days, 3) * 0.015

        # Create long format DataFrame
        data = []
        tech_tickers = ["AAPL", "MSFT", "GOOGL"]
        fin_tickers = ["JPM", "BAC", "C"]

        for i, d in enumerate(dates):
            for j, ticker in enumerate(tech_tickers):
                data.append({
                    "ticker": ticker,
                    "date": d,
                    "return": tech_returns[i, j],
                    "sector": "Technology"
                })
            for j, ticker in enumerate(fin_tickers):
                data.append({
                    "ticker": ticker,
                    "date": d,
                    "return": fin_returns[i, j],
                    "sector": "Financials"
                })

        returns_df = pl.DataFrame(data)

        # Execute
        estimator = BlockDiagonalCovariance(
            n_factors=1,
            clustering_method="predefined",
            shrinkage_method="ledoit_wolf"
        )
        cov_matrix = estimator.fit(returns_df, sector_col="sector")

        # Verify
        assert isinstance(cov_matrix, np.ndarray)
        assert cov_matrix.shape == (6, 6)
        assert np.allclose(cov_matrix, cov_matrix.T), "Covariance should be symmetric"

    def test_block_structure_preserved(self):
        """Test that off-block elements are dominated by factor component."""
        # Create data with clear block structure
        np.random.seed(42)
        n_days = 250

        # Create 2 sectors with minimal cross-sector correlation
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        # Sector 1: High intra-sector correlation
        factor1 = np.random.randn(n_days, 1)
        sector1_returns = factor1 @ np.ones((1, 3)) * 0.8 + np.random.randn(n_days, 3) * 0.1

        # Sector 2: High intra-sector correlation, different factor
        factor2 = np.random.randn(n_days, 1)
        sector2_returns = factor2 @ np.ones((1, 3)) * 0.8 + np.random.randn(n_days, 3) * 0.1

        # Create DataFrame
        data = []
        for i, d in enumerate(dates):
            for j in range(3):
                data.append({
                    "ticker": f"S1_{j}",
                    "date": d,
                    "return": sector1_returns[i, j],
                    "sector": "Sector1"
                })
            for j in range(3):
                data.append({
                    "ticker": f"S2_{j}",
                    "date": d,
                    "return": sector2_returns[i, j],
                    "sector": "Sector2"
                })

        returns_df = pl.DataFrame(data)

        # Execute
        estimator = BlockDiagonalCovariance(
            n_factors=1,
            clustering_method="predefined",
            shrinkage_method="none"  # No shrinkage for clearer block structure
        )
        cov_matrix = estimator.fit(returns_df, sector_col="sector")

        # Verify: Within-block correlations should be higher than cross-block
        # Extract blocks
        block1_cov = cov_matrix[:3, :3]
        block2_cov = cov_matrix[3:, 3:]
        cross_cov = cov_matrix[:3, 3:]

        # Convert to correlation
        std = np.sqrt(np.diag(cov_matrix))
        corr_matrix = cov_matrix / np.outer(std, std)

        block1_corr = corr_matrix[:3, :3]
        block2_corr = corr_matrix[3:, 3:]
        cross_corr = corr_matrix[:3, 3:]

        # Average within-block correlation (excluding diagonal)
        within_corr1 = np.mean(block1_corr[~np.eye(3, dtype=bool)])
        within_corr2 = np.mean(block2_corr[~np.eye(3, dtype=bool)])
        avg_within = (within_corr1 + within_corr2) / 2

        # Average cross-block correlation
        avg_cross = np.mean(np.abs(cross_corr))

        # Within-block should be stronger than cross-block
        assert avg_within > avg_cross, \
            f"Within-block correlation ({avg_within:.3f}) should be > cross-block ({avg_cross:.3f})"

    def test_positive_definite_output(self):
        """Test that output covariance is positive definite."""
        # Create random data
        np.random.seed(42)
        n_days = 150
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        data = []
        tickers = ["A", "B", "C", "D", "E"]
        sectors = ["S1", "S1", "S2", "S2", "S3"]

        for i, d in enumerate(dates):
            for j, ticker in enumerate(tickers):
                data.append({
                    "ticker": ticker,
                    "date": d,
                    "return": np.random.randn() * 0.02,
                    "sector": sectors[j]
                })

        returns_df = pl.DataFrame(data)

        # Execute
        estimator = BlockDiagonalCovariance(n_factors=2, clustering_method="predefined")
        cov_matrix = estimator.fit(returns_df, sector_col="sector")

        # Verify: All eigenvalues should be positive
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 0), \
            f"Covariance should be positive definite, but got min eigenvalue: {eigenvalues.min()}"

    def test_ledoit_wolf_shrinkage_per_block(self):
        """Test that shrinkage is applied within each block."""
        # Create data where shrinkage should improve conditioning
        np.random.seed(42)
        n_days = 80  # Less than assets in sector (ill-conditioned)
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        data = []
        # Sector 1: 10 assets (more than n_days)
        for i, d in enumerate(dates):
            for j in range(10):
                data.append({
                    "ticker": f"A{j}",
                    "date": d,
                    "return": np.random.randn() * 0.02,
                    "sector": "S1"
                })

        returns_df = pl.DataFrame(data)

        # Execute with and without shrinkage
        estimator_shrink = BlockDiagonalCovariance(
            n_factors=1,
            clustering_method="predefined",
            shrinkage_method="ledoit_wolf"
        )
        cov_shrink = estimator_shrink.fit(returns_df, sector_col="sector")

        estimator_no_shrink = BlockDiagonalCovariance(
            n_factors=1,
            clustering_method="predefined",
            shrinkage_method="none"
        )
        cov_no_shrink = estimator_no_shrink.fit(returns_df, sector_col="sector")

        # Verify: Shrinkage should improve conditioning
        cond_shrink = np.linalg.cond(cov_shrink)
        cond_no_shrink = np.linalg.cond(cov_no_shrink)

        assert cond_shrink < cond_no_shrink, \
            f"Shrinkage should reduce condition number: {cond_shrink:.1f} vs {cond_no_shrink:.1f}"

    def test_bias_correction_when_p_greater_than_t(self):
        """Test eigenvalue bias correction in high-dimensional regime."""
        # Create data where p > T (high-dimensional)
        np.random.seed(42)
        n_days = 30  # Make T small
        n_assets = 50  # p > T per block (50 > 30)
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        data = []
        for i, d in enumerate(dates):
            for j in range(n_assets):
                data.append({
                    "ticker": f"A{j}",
                    "date": d,
                    "return": np.random.randn() * 0.02,
                    "sector": "S1"
                })

        returns_df = pl.DataFrame(data)

        # Execute with and without bias correction
        estimator_corrected = BlockDiagonalCovariance(
            n_factors=1,
            clustering_method="predefined",
            shrinkage_method="ledoit_wolf",
            bias_correction=True
        )
        cov_corrected = estimator_corrected.fit(returns_df, sector_col="sector")

        estimator_uncorrected = BlockDiagonalCovariance(
            n_factors=1,
            clustering_method="predefined",
            shrinkage_method="ledoit_wolf",
            bias_correction=False
        )
        cov_uncorrected = estimator_uncorrected.fit(returns_df, sector_col="sector")

        # Verify: Matrices should differ
        assert not np.allclose(cov_corrected, cov_uncorrected), \
            "Bias correction should modify the covariance matrix"

        # Verify: Corrected version should have smaller eigenvalues on average
        eig_corrected = np.linalg.eigvalsh(cov_corrected)
        eig_uncorrected = np.linalg.eigvalsh(cov_uncorrected)

        # Bias correction should shrink small eigenvalues
        assert np.min(eig_corrected) <= np.min(eig_uncorrected), \
            "Bias correction should reduce smallest eigenvalues"

    def test_raises_on_missing_sector_column(self):
        """Test error when sector column is missing."""
        returns_df = pl.DataFrame({
            "ticker": ["A", "B"],
            "date": [date(2024, 1, 1)] * 2,
            "return": [0.01, 0.02]
        })

        estimator = BlockDiagonalCovariance(clustering_method="predefined")

        with pytest.raises(ValueError, match="sector"):
            estimator.fit(returns_df, sector_col="sector")

    def test_handles_single_sector(self):
        """Test behavior with only one sector."""
        np.random.seed(42)
        n_days = 100
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        data = []
        for i, d in enumerate(dates):
            for j in range(4):
                data.append({
                    "ticker": f"A{j}",
                    "date": d,
                    "return": np.random.randn() * 0.02,
                    "sector": "OnlySector"
                })

        returns_df = pl.DataFrame(data)

        # Execute
        estimator = BlockDiagonalCovariance(n_factors=1, clustering_method="predefined")
        cov_matrix = estimator.fit(returns_df, sector_col="sector")

        # Verify
        assert cov_matrix.shape == (4, 4)
        assert np.all(np.linalg.eigvalsh(cov_matrix) > 0)

    def test_automatic_factor_selection(self):
        """Test automatic factor count selection."""
        # Create data with clear factor structure
        np.random.seed(42)
        n_days = 200
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        # Single dominant factor
        factor = np.random.randn(n_days, 1)
        returns_matrix = factor @ np.random.randn(1, 6) * 2.0 + np.random.randn(n_days, 6) * 0.1

        data = []
        tickers = [f"A{i}" for i in range(6)]
        for i, d in enumerate(dates):
            for j, ticker in enumerate(tickers):
                data.append({
                    "ticker": ticker,
                    "date": d,
                    "return": returns_matrix[i, j],
                    "sector": "S1"
                })

        returns_df = pl.DataFrame(data)

        # Execute with auto factor selection
        estimator = BlockDiagonalCovariance(
            n_factors=None,  # Auto-select
            clustering_method="predefined"
        )
        cov_matrix = estimator.fit(returns_df, sector_col="sector")

        # Verify
        assert cov_matrix.shape == (6, 6)
        assert np.all(np.linalg.eigvalsh(cov_matrix) > 0)

    def test_hierarchical_clustering_mode(self):
        """Test estimation with hierarchical sector discovery."""
        # Create data with 2 natural clusters
        np.random.seed(42)
        n_days = 200
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        # Cluster 1
        factor1 = np.random.randn(n_days, 1)
        cluster1_returns = factor1 @ np.ones((1, 3)) + np.random.randn(n_days, 3) * 0.1

        # Cluster 2
        factor2 = np.random.randn(n_days, 1)
        cluster2_returns = factor2 @ np.ones((1, 3)) + np.random.randn(n_days, 3) * 0.1

        all_returns = np.hstack([cluster1_returns, cluster2_returns])

        data = []
        tickers = [f"T{i}" for i in range(6)]
        for i, d in enumerate(dates):
            for j, ticker in enumerate(tickers):
                data.append({
                    "ticker": ticker,
                    "date": d,
                    "return": all_returns[i, j],
                    "sector": "Ignored"  # Should be ignored in hierarchical mode
                })

        returns_df = pl.DataFrame(data)

        # Execute with hierarchical clustering
        estimator = BlockDiagonalCovariance(
            n_factors=1,
            clustering_method="hierarchical"
        )
        cov_matrix = estimator.fit(returns_df)

        # Verify
        assert cov_matrix.shape == (6, 6)
        assert np.all(np.linalg.eigvalsh(cov_matrix) > 0)

    def test_output_format_matches_base_estimator(self):
        """Test that output format matches BaseCovarianceEstimator interface."""
        np.random.seed(42)
        n_days = 100
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        data = []
        for i, d in enumerate(dates):
            for j in range(4):
                data.append({
                    "ticker": f"A{j}",
                    "date": d,
                    "return": np.random.randn() * 0.02,
                    "sector": "S1"
                })

        returns_df = pl.DataFrame(data)

        # Execute
        estimator = BlockDiagonalCovariance(n_factors=1, clustering_method="predefined")
        cov_matrix = estimator.fit(returns_df, sector_col="sector")

        # Verify: Should be numpy array (not DataFrame)
        assert isinstance(cov_matrix, np.ndarray)
        assert cov_matrix.ndim == 2
        assert cov_matrix.shape[0] == cov_matrix.shape[1]

        # Should be able to use BaseCovarianceEstimator methods
        stored_cov = estimator.get_covariance()
        assert np.allclose(stored_cov, cov_matrix)

        corr = estimator.get_correlation()
        assert corr.shape == cov_matrix.shape
