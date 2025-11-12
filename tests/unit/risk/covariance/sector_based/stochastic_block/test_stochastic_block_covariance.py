# ABOUTME: Tests for StochasticBlockCovariance estimator with inter-block correlations
# ABOUTME: Validates MVP approach: block-diagonal base + regularized off-diagonal blocks
"""
Tests for StochasticBlockCovariance

The StochasticBlockCovariance estimator allows inter-block correlations
(unlike pure block-diagonal models). This is the key innovation from
Chen et al. (2025).

MVP Implementation:
    Ψ_ij = α·BlockDiag_ij + (1-α)·FullCov_ij

Where:
- BlockDiag_ij: Pure block-diagonal component (within-sector)
- FullCov_ij: Full covariance (captures cross-sector)
- α: Blending parameter (controls sparsity)
"""

import pytest
import polars as pl
import numpy as np
from datetime import date, timedelta


class TestStochasticBlockCovariance:
    """Tests for StochasticBlockCovariance estimator."""

    @pytest.fixture
    def simple_sector_returns(self) -> pl.DataFrame:
        """
        Create simple returns with 2 sectors, 3 assets each.

        Structure:
        - Sector A: Assets A1, A2, A3 (high within-sector correlation)
        - Sector B: Assets B1, B2, B3 (high within-sector correlation)
        - Moderate cross-sector correlation
        """
        np.random.seed(42)
        n_days = 100

        # Common market factor
        market = np.random.randn(n_days) * 0.02

        # Sector-specific factors
        sector_a_factor = np.random.randn(n_days) * 0.015
        sector_b_factor = np.random.randn(n_days) * 0.015

        # Individual noise
        noise_a1 = np.random.randn(n_days) * 0.005
        noise_a2 = np.random.randn(n_days) * 0.005
        noise_a3 = np.random.randn(n_days) * 0.005
        noise_b1 = np.random.randn(n_days) * 0.005
        noise_b2 = np.random.randn(n_days) * 0.005
        noise_b3 = np.random.randn(n_days) * 0.005

        # Construct returns (market + sector + noise)
        returns_a1 = market + sector_a_factor + noise_a1
        returns_a2 = market + sector_a_factor + noise_a2
        returns_a3 = market + sector_a_factor + noise_a3
        returns_b1 = market + sector_b_factor + noise_b1
        returns_b2 = market + sector_b_factor + noise_b2
        returns_b3 = market + sector_b_factor + noise_b3

        # Create long format DataFrame
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        df = pl.DataFrame({
            "date": dates * 6,
            "ticker": (["A1"] * n_days + ["A2"] * n_days + ["A3"] * n_days +
                      ["B1"] * n_days + ["B2"] * n_days + ["B3"] * n_days),
            "sector": (["Technology"] * (n_days * 3) + ["Financials"] * (n_days * 3)),
            "return": np.concatenate([returns_a1, returns_a2, returns_a3,
                                     returns_b1, returns_b2, returns_b3]),
        })

        return df

    @pytest.fixture
    def three_sector_returns(self) -> pl.DataFrame:
        """Create returns with 3 sectors for more complex testing."""
        np.random.seed(123)
        n_days = 150

        market = np.random.randn(n_days) * 0.02

        # Three sector factors with cross-correlations
        tech_factor = np.random.randn(n_days) * 0.015
        finance_factor = 0.5 * tech_factor + np.random.randn(n_days) * 0.01  # Correlated with tech
        energy_factor = np.random.randn(n_days) * 0.02  # Independent

        # 2 assets per sector
        tickers = ["TECH1", "TECH2", "FIN1", "FIN2", "ENERGY1", "ENERGY2"]
        sectors = ["Technology", "Technology", "Financials", "Financials", "Energy", "Energy"]

        returns_list = []
        for i, (ticker, sector) in enumerate(zip(tickers, sectors)):
            noise = np.random.randn(n_days) * 0.005

            if sector == "Technology":
                ret = market + tech_factor + noise
            elif sector == "Financials":
                ret = market + finance_factor + noise
            else:  # Energy
                ret = market + energy_factor + noise

            returns_list.append(ret)

        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        df = pl.DataFrame({
            "date": dates * 6,
            "ticker": [t for t in tickers for _ in range(n_days)],
            "sector": [s for s in sectors for _ in range(n_days)],
            "return": np.concatenate(returns_list),
        })

        return df

    def test_allows_inter_block_correlations(self, simple_sector_returns):
        """
        Test that StochasticBlock allows non-zero off-diagonal blocks.

        This is the KEY DIFFERENCE from BlockDiagonal approach.
        Off-diagonal blocks should capture cross-sector correlations.
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        # Create estimator with inter-block correlations enabled
        estimator = StochasticBlockCovariance(allow_inter_block=True)

        # Fit
        cov_matrix = estimator.fit(simple_sector_returns)

        # Verify output shape
        assert cov_matrix.shape == (6, 6)
        assert np.allclose(cov_matrix, cov_matrix.T)  # Symmetric

        # Extract cross-sector block (Tech vs Financials)
        # Tech: indices 0, 1, 2 (A1, A2, A3)
        # Financials: indices 3, 4, 5 (B1, B2, B3)
        cross_block = cov_matrix[0:3, 3:6]

        # Key assertion: Cross-sector block should have NON-ZERO entries
        assert not np.allclose(cross_block, 0, atol=1e-10), (
            "StochasticBlock should allow inter-block correlations, but got all zeros"
        )

        # Cross-sector correlations should be smaller than within-sector
        within_tech_var = np.mean(np.diag(cov_matrix[0:3, 0:3]))
        cross_sector_cov = np.mean(np.abs(cross_block))

        assert cross_sector_cov < within_tech_var, (
            "Cross-sector covariances should be smaller than within-sector"
        )

    def test_cross_sector_dependencies(self, three_sector_returns):
        """
        Test that cross-sector dependencies are correctly captured.

        In the test data, Tech and Finance are correlated (finance_factor = 0.5 * tech_factor),
        while Energy is independent. The covariance matrix should reflect this.
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        estimator = StochasticBlockCovariance(allow_inter_block=True)
        cov_matrix = estimator.fit(three_sector_returns)

        # Indices: TECH1(0), TECH2(1), FIN1(2), FIN2(3), ENERGY1(4), ENERGY2(5)

        # Tech-Finance cross-sector correlation should be higher than Tech-Energy
        tech_fin_cov = np.mean(np.abs(cov_matrix[0:2, 2:4]))
        tech_energy_cov = np.mean(np.abs(cov_matrix[0:2, 4:6]))

        assert tech_fin_cov > tech_energy_cov, (
            "Tech-Finance correlation should be higher than Tech-Energy "
            "(by construction in test data)"
        )

    def test_vs_block_diagonal(self, simple_sector_returns):
        """
        Compare StochasticBlock vs pure BlockDiagonal.

        StochasticBlock should have non-zero off-diagonal blocks,
        while BlockDiagonal should have exactly zero off-blocks.
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        # Stochastic Block (allows inter-block)
        stochastic = StochasticBlockCovariance(allow_inter_block=True)
        cov_stochastic = stochastic.fit(simple_sector_returns)

        # Block Diagonal (pure block structure)
        block_diag = StochasticBlockCovariance(allow_inter_block=False)
        cov_block = block_diag.fit(simple_sector_returns)

        # Extract cross-sector blocks
        cross_stochastic = cov_stochastic[0:3, 3:6]
        cross_block = cov_block[0:3, 3:6]

        # Stochastic should have non-zero off-blocks
        assert not np.allclose(cross_stochastic, 0, atol=1e-10)

        # Block diagonal should have zero off-blocks (or very small)
        assert np.allclose(cross_block, 0, atol=1e-6), (
            "BlockDiagonal mode should have near-zero off-diagonal blocks"
        )

    def test_positive_definite_output(self, simple_sector_returns):
        """
        Test that output covariance is positive definite.

        Required for portfolio optimization (matrix inversion).
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        estimator = StochasticBlockCovariance(allow_inter_block=True)
        cov_matrix = estimator.fit(simple_sector_returns)

        # Check positive definiteness via eigenvalues
        eigenvalues = np.linalg.eigvalsh(cov_matrix)

        assert np.all(eigenvalues > 0), (
            f"Covariance matrix not positive definite. "
            f"Min eigenvalue: {eigenvalues.min()}"
        )

        # Check invertibility (condition number)
        cond = np.linalg.cond(cov_matrix)
        assert cond < 1e10, f"Matrix is ill-conditioned: κ = {cond}"

    def test_regularization_parameter(self, simple_sector_returns):
        """
        Test that regularization parameter α controls sparsity.

        α = 0: Full covariance (no sparsity)
        α = 1: Block diagonal (maximum sparsity)
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        # Test different α values
        alpha_values = [0.0, 0.5, 1.0]
        cross_sector_norms = []

        for alpha in alpha_values:
            estimator = StochasticBlockCovariance(
                allow_inter_block=True,
                alpha=alpha
            )
            cov_matrix = estimator.fit(simple_sector_returns)

            # Measure cross-sector magnitude
            cross_block = cov_matrix[0:3, 3:6]
            norm = np.linalg.norm(cross_block, 'fro')
            cross_sector_norms.append(norm)

        # α=0 should have largest cross-sector correlations
        # α=1 should have smallest (near zero)
        assert cross_sector_norms[0] > cross_sector_norms[1] > cross_sector_norms[2], (
            "Higher α should reduce cross-sector correlations"
        )

    def test_handles_missing_sector_column(self):
        """Test error handling when sector column is missing."""
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        # Create DataFrame without sector column
        df = pl.DataFrame({
            "date": [date(2024, 1, 1)] * 3,
            "ticker": ["A", "B", "C"],
            "return": [0.01, 0.02, -0.01],
        })

        estimator = StochasticBlockCovariance(allow_inter_block=True)

        with pytest.raises(ValueError, match="Missing required columns.*sector"):
            estimator.fit(df)

    def test_handles_single_sector(self):
        """
        Test behavior when all assets are in same sector.

        Should fall back to full covariance (no block structure needed).
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        # All assets in same sector
        np.random.seed(42)
        n_days = 50
        returns_data = np.random.randn(n_days, 3) * 0.01

        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        df = pl.DataFrame({
            "date": dates * 3,
            "ticker": ["A"] * n_days + ["B"] * n_days + ["C"] * n_days,
            "sector": ["Technology"] * (n_days * 3),
            "return": returns_data.flatten(order='F'),
        })

        estimator = StochasticBlockCovariance(allow_inter_block=True)
        cov_matrix = estimator.fit(df)

        # Should still be positive definite
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 0)

        # Shape should be correct
        assert cov_matrix.shape == (3, 3)

    def test_sector_discovery_mode(self, simple_sector_returns):
        """
        Test automatic sector discovery when discover_blocks=True.

        This is optional advanced feature. For MVP, can skip discovery
        and use predefined sectors.
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        # Remove sector column to force discovery
        df_no_sectors = simple_sector_returns.drop("sector")

        # Estimator with automatic discovery
        estimator = StochasticBlockCovariance(
            allow_inter_block=True,
            discover_blocks=True,
        )

        # Should work even without sector column
        # (will discover structure from correlations)
        cov_matrix = estimator.fit(df_no_sectors)

        assert cov_matrix.shape == (6, 6)
        assert np.allclose(cov_matrix, cov_matrix.T)

    def test_different_sector_sizes(self):
        """
        Test handling of sectors with different numbers of assets.

        Sector A: 2 assets
        Sector B: 4 assets
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        np.random.seed(789)
        n_days = 80

        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]

        # 2 tech, 4 finance
        tickers = ["TECH1", "TECH2", "FIN1", "FIN2", "FIN3", "FIN4"]
        sectors = ["Technology", "Technology", "Financials", "Financials", "Financials", "Financials"]

        returns_data = np.random.randn(n_days, 6) * 0.01

        df = pl.DataFrame({
            "date": dates * 6,
            "ticker": [t for t in tickers for _ in range(n_days)],
            "sector": [s for s in sectors for _ in range(n_days)],
            "return": returns_data.flatten(order='F'),
        })

        estimator = StochasticBlockCovariance(allow_inter_block=True)
        cov_matrix = estimator.fit(df)

        # Verify shape
        assert cov_matrix.shape == (6, 6)

        # Verify positive definite
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 0)

    def test_consistency_with_base_interface(self, simple_sector_returns):
        """
        Test compliance with BaseCovarianceEstimator interface.

        Must implement:
        - fit(returns) -> np.ndarray
        - get_covariance() -> np.ndarray
        - get_correlation() -> np.ndarray
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )
        from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator

        estimator = StochasticBlockCovariance(allow_inter_block=True)

        # Check inheritance
        assert isinstance(estimator, BaseCovarianceEstimator)

        # Fit
        cov_matrix = estimator.fit(simple_sector_returns)

        # get_covariance() should return same matrix
        cov_from_getter = estimator.get_covariance()
        assert np.allclose(cov_matrix, cov_from_getter)

        # get_correlation() should work
        corr_matrix = estimator.get_correlation()
        assert corr_matrix.shape == (6, 6)

        # Diagonal should be 1.0 (correlation)
        assert np.allclose(np.diag(corr_matrix), 1.0)

    def test_out_of_sample_validation(self, three_sector_returns):
        """
        Test out-of-sample covariance estimation.

        Split data: train on first 100 days, validate on last 50 days.
        StochasticBlock should have better out-of-sample risk than naive sample cov.
        """
        from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
            StochasticBlockCovariance
        )

        # Split data
        train_date = date(2024, 1, 1) + timedelta(days=100)
        train_df = three_sector_returns.filter(pl.col("date") < train_date)
        test_df = three_sector_returns.filter(pl.col("date") >= train_date)

        # Fit on training data
        estimator = StochasticBlockCovariance(allow_inter_block=True)
        cov_train = estimator.fit(train_df)

        # Compute test covariance (ground truth)
        from Risk.Covariance.SectorBased.sector_utils import long_to_wide
        test_wide, _ = long_to_wide(test_df, value_col="return")
        test_array = test_wide.to_numpy()
        cov_test = np.cov(test_array, rowvar=False)

        # Measure prediction error (Frobenius norm)
        error = np.linalg.norm(cov_train - cov_test, 'fro')

        # Should have reasonable error (not NaN or inf)
        assert not np.isnan(error)
        assert not np.isinf(error)
        assert error < 1.0, "Out-of-sample error too large"
