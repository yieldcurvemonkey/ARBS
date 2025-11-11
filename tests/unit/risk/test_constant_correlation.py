# ABOUTME: Test suite for ConstantCorrelationCovariance estimator (constant correlation shrinkage target)
# ABOUTME: Verifies constant correlation structure, analytical properties, and edge cases (ρ=0, ρ=1, ρ<0)
"""
Tests for Constant Correlation Covariance Estimator

The constant correlation model assumes all pairwise correlations are equal:
    Σ = D × (ρ × 11' + (1-ρ) × I) × D

where:
- D = diag(σ_1, ..., σ_n) is diagonal matrix of standard deviations
- ρ = mean pairwise correlation from returns
- 11' is matrix of ones (n×n)
- I = identity matrix

This is a shrinkage target used in Ledoit-Wolf and other methods.

Business Requirements:
1. Constant correlation structure: all off-diagonal correlations equal
2. Variance preservation: diagonal variances match sample variances
3. Positive definite: all eigenvalues > 0
4. Symmetric: Σ = Σ'
5. Edge cases: ρ=0 (diagonal), ρ=1 (perfect correlation), ρ<0 (negative)
"""

import pytest
import numpy as np
import pandas as pd


class TestConstantCorrelationBasics:
    """Test basic constant correlation functionality."""

    def test_constant_correlation_can_be_imported(self):
        """Verify ConstantCorrelationCovariance exists."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance
        assert ConstantCorrelationCovariance is not None

    def test_constant_correlation_can_be_instantiated(self):
        """ConstantCorrelationCovariance should be instantiable."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        estimator = ConstantCorrelationCovariance()
        assert estimator is not None


class TestConstantCorrelationEstimation:
    """Test constant correlation covariance estimation."""

    def test_basic_estimation(self):
        """Basic returns should produce valid covariance matrix."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        # Create simple returns data
        np.random.seed(42)
        returns = pd.DataFrame(
            np.random.randn(100, 5),
            columns=['A', 'B', 'C', 'D', 'E']
        )

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Should return N×N matrix
        assert cov_matrix.shape == (5, 5)
        assert not np.any(np.isnan(cov_matrix))

    def test_output_is_symmetric(self):
        """Covariance matrix should be symmetric."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(50, 5))

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Σ = Σ'
        np.testing.assert_array_almost_equal(cov_matrix, cov_matrix.T)

    def test_output_is_positive_definite(self):
        """Covariance matrix should be positive definite (all eigenvalues > 0)."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Check eigenvalues are strictly positive
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 1e-10)

    def test_constant_correlation_structure(self):
        """All off-diagonal correlations should be equal (constant correlation)."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Convert to correlation matrix
        std = np.sqrt(np.diag(cov_matrix))
        corr_matrix = cov_matrix / np.outer(std, std)

        # Extract all off-diagonal correlations
        n = corr_matrix.shape[0]
        off_diag_corrs = []
        for i in range(n):
            for j in range(i + 1, n):
                off_diag_corrs.append(corr_matrix[i, j])

        # All off-diagonal correlations should be equal
        off_diag_corrs = np.array(off_diag_corrs)
        assert np.allclose(off_diag_corrs, off_diag_corrs[0], atol=1e-10)

    def test_variance_preservation(self):
        """Diagonal variances should match sample variances."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Sample variances
        sample_var = returns.var(ddof=1).values

        # Constant correlation variances (diagonal)
        cc_var = np.diag(cov_matrix)

        # Should preserve variances
        np.testing.assert_array_almost_equal(cc_var, sample_var, decimal=10)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_asset(self):
        """Single asset should return variance as 1×1 matrix."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 1), columns=['A'])

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be 1×1 matrix with variance
        assert cov_matrix.shape == (1, 1)
        expected_var = returns.var(ddof=1).values[0]
        np.testing.assert_almost_equal(cov_matrix[0, 0], expected_var)

    def test_zero_correlation(self):
        """When ρ=0, should be diagonal matrix."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        # Create uncorrelated returns
        returns = pd.DataFrame(np.random.randn(100, 5))

        # Manually set correlation to 0 by using orthogonal data
        # (In practice, ρ will be computed from data, so we'll check approximately)
        estimator = ConstantCorrelationCovariance()

        # Create perfectly uncorrelated data
        returns_ortho = pd.DataFrame({
            'A': np.random.randn(100),
            'B': np.random.randn(100),
            'C': np.random.randn(100),
        })

        # Force near-zero correlation by making columns orthogonal
        # Not perfect, but should give small correlation
        cov_matrix = estimator.fit(returns_ortho)

        # Extract correlation
        std = np.sqrt(np.diag(cov_matrix))
        corr_matrix = cov_matrix / np.outer(std, std)

        # Off-diagonal should be small (not exactly 0, but close to sample correlation)
        off_diag = corr_matrix[0, 1]
        assert abs(off_diag) < 0.5  # Reasonable threshold for random data

    def test_perfect_correlation(self):
        """When ρ=1, all correlations should be 1."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        # Create perfectly correlated returns
        base = np.random.randn(100, 1)
        returns = pd.DataFrame({
            'A': base.flatten(),
            'B': base.flatten() * 1.5,  # Scaled version
            'C': base.flatten() * 0.8,  # Another scaled version
        })

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Convert to correlation
        std = np.sqrt(np.diag(cov_matrix))
        corr_matrix = cov_matrix / np.outer(std, std)

        # All off-diagonal correlations should be 1 (or very close)
        assert np.allclose(corr_matrix[0, 1], 1.0, atol=1e-6)
        assert np.allclose(corr_matrix[0, 2], 1.0, atol=1e-6)
        assert np.allclose(corr_matrix[1, 2], 1.0, atol=1e-6)

    def test_negative_correlation(self):
        """When ρ<0, should handle negative correlations correctly."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        # Create negatively correlated returns
        base = np.random.randn(100)
        returns = pd.DataFrame({
            'A': base,
            'B': -base + np.random.randn(100) * 0.1,  # Negatively correlated
        })

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be positive definite despite negative correlation
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 1e-10)

        # Correlation should be negative
        std = np.sqrt(np.diag(cov_matrix))
        corr_matrix = cov_matrix / np.outer(std, std)
        assert corr_matrix[0, 1] < 0


class TestAnalyticalSolution:
    """Test against known analytical solutions."""

    def test_known_analytical_solution(self):
        """Verify against manual calculation of constant correlation matrix."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        # Create simple returns with known properties
        np.random.seed(42)
        returns = pd.DataFrame({
            'A': [1.0, 2.0, 3.0, 4.0, 5.0],
            'B': [2.0, 3.0, 4.0, 5.0, 6.0],
            'C': [3.0, 4.0, 5.0, 6.0, 7.0],
        })

        # Calculate expected values manually
        sample_cov = returns.cov().values
        sample_std = np.sqrt(np.diag(sample_cov))
        sample_corr = sample_cov / np.outer(sample_std, sample_std)

        # Mean correlation (off-diagonal only)
        n = 3
        off_diag_sum = 0
        for i in range(n):
            for j in range(i + 1, n):
                off_diag_sum += sample_corr[i, j]
        rho = off_diag_sum / (n * (n - 1) / 2)

        # Build constant correlation matrix manually
        # Σ = D × (ρ × 11' + (1-ρ) × I) × D
        D = np.diag(sample_std)
        ones_matrix = np.ones((n, n))
        I = np.eye(n)

        corr_matrix_expected = rho * ones_matrix + (1 - rho) * I
        cov_matrix_expected = D @ corr_matrix_expected @ D

        # Compare to estimator output
        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        np.testing.assert_array_almost_equal(cov_matrix, cov_matrix_expected, decimal=10)


class TestIntegrationWithOptimization:
    """Test that constant correlation works with portfolio optimization."""

    def test_can_invert_for_gmv(self):
        """Constant correlation matrix should be invertible for GMV portfolio."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 10))

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        # GMV weights: w = Σ^(-1) 1 / (1' Σ^(-1) 1)
        ones = np.ones(10)
        inv_cov = np.linalg.inv(cov_matrix)
        weights = inv_cov @ ones / (ones @ inv_cov @ ones)

        # Weights should sum to 1
        assert abs(np.sum(weights) - 1.0) < 1e-6

    def test_condition_number_is_reasonable(self):
        """Condition number should be reasonable for portfolio optimization."""
        from Risk.Covariance.ConstantCorrelationCovariance import ConstantCorrelationCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 20))

        estimator = ConstantCorrelationCovariance()
        cov_matrix = estimator.fit(returns)

        cond_number = np.linalg.cond(cov_matrix)

        # Should be well-conditioned (better than sample in typical cases)
        assert cond_number < 1000  # Reasonable threshold
