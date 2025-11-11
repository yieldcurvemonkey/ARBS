# ABOUTME: Test suite for diagonal covariance matrix estimator
# ABOUTME: Verifies diagonal structure (zeros off-diagonal), variance matching, and positive definiteness
"""
Tests for Diagonal Covariance Estimator

The diagonal covariance estimator assumes zero correlation between assets:
    Σ_ij = σ_i² if i=j, else 0

Business Requirements:
1. Diagonal structure: All off-diagonal elements = 0
2. Variance matching: diag(Σ) = var(returns)
3. Positive definite: Always invertible (diagonal with positive variances)
4. Simplicity: Fastest covariance estimator (no correlation estimation)

Use Cases:
- Baseline comparison (extreme shrinkage)
- When correlations are unknown/unreliable
- Quick risk calculations
- Diversification studies (correlation = 0 assumption)
"""

import pytest
import numpy as np
import pandas as pd


class TestDiagonalCovarianceBasics:
    """Test basic diagonal covariance functionality."""

    def test_diagonal_covariance_can_be_imported(self):
        """Verify DiagonalCovariance exists."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance
        assert DiagonalCovariance is not None

    def test_diagonal_covariance_can_be_instantiated(self):
        """DiagonalCovariance should be instantiable."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        estimator = DiagonalCovariance()
        assert estimator is not None


class TestDiagonalCovarianceEstimation:
    """Test diagonal covariance estimation."""

    def test_basic_estimation(self):
        """Basic returns should produce diagonal covariance matrix."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        # Create simple returns data
        np.random.seed(42)
        returns = pd.DataFrame(
            np.random.randn(100, 5),
            columns=['A', 'B', 'C', 'D', 'E']
        )

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Should return N×N matrix
        assert cov_matrix.shape == (5, 5)

        # Should be numpy array
        assert isinstance(cov_matrix, np.ndarray)

    def test_off_diagonals_are_zero(self):
        """All off-diagonal elements should be exactly zero."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Extract off-diagonal elements
        n = cov_matrix.shape[0]
        for i in range(n):
            for j in range(n):
                if i != j:
                    assert cov_matrix[i, j] == 0.0, f"Off-diagonal [{i},{j}] should be zero"

    def test_diagonal_matches_sample_variance(self):
        """Diagonal elements should match sample variance of each asset."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(
            np.random.randn(100, 5),
            columns=['A', 'B', 'C', 'D', 'E']
        )

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Compare diagonal to returns.var()
        expected_variances = returns.var().values
        actual_variances = np.diag(cov_matrix)

        np.testing.assert_array_almost_equal(
            actual_variances,
            expected_variances,
            decimal=10
        )

    def test_single_asset(self):
        """Edge case: single asset should work."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 1), columns=['A'])

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be 1×1 matrix
        assert cov_matrix.shape == (1, 1)

        # Should match variance
        expected_var = returns['A'].var()
        assert abs(cov_matrix[0, 0] - expected_var) < 1e-10

    def test_multiple_assets(self):
        """Should handle 5+ assets correctly."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        n_assets = 10
        returns = pd.DataFrame(np.random.randn(100, n_assets))

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Correct shape
        assert cov_matrix.shape == (n_assets, n_assets)

        # All off-diagonals zero
        off_diag_sum = np.sum(np.abs(cov_matrix)) - np.sum(np.abs(np.diag(cov_matrix)))
        assert off_diag_sum == 0.0


class TestDiagonalCovarianceProperties:
    """Test mathematical properties of diagonal covariance."""

    def test_comparison_with_numpy_diag(self):
        """Should match np.diag(returns.var())."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Expected: diagonal matrix with variances
        expected = np.diag(returns.var().values)

        np.testing.assert_array_almost_equal(cov_matrix, expected, decimal=10)

    def test_output_is_symmetric(self):
        """Covariance matrix should be symmetric (trivially true for diagonal)."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(50, 5))

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be symmetric
        np.testing.assert_array_almost_equal(cov_matrix, cov_matrix.T)

    def test_output_is_positive_definite(self):
        """Diagonal matrix with positive variances should be positive definite."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Check eigenvalues (should all be positive)
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 1e-10), "All eigenvalues should be strictly positive"

        # Diagonal matrix eigenvalues = diagonal elements
        expected_eigenvalues = np.sort(np.diag(cov_matrix))
        actual_eigenvalues = np.sort(eigenvalues)
        np.testing.assert_array_almost_equal(actual_eigenvalues, expected_eigenvalues)


class TestDiagonalCovarianceIntegration:
    """Test integration with portfolio optimization."""

    def test_can_invert_for_gmv(self):
        """Diagonal covariance should be trivially invertible."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 10))

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be invertible
        inv_cov = np.linalg.inv(cov_matrix)

        # Inverse of diagonal is diagonal of inverses
        expected_inv = np.diag(1.0 / np.diag(cov_matrix))
        np.testing.assert_array_almost_equal(inv_cov, expected_inv)

    def test_condition_number_is_optimal(self):
        """Diagonal matrix has optimal condition number (ratio of max/min variance)."""
        from Risk.Covariance.DiagonalCovariance import DiagonalCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 10))

        estimator = DiagonalCovariance()
        cov_matrix = estimator.fit(returns)

        # Condition number of diagonal matrix
        cond = np.linalg.cond(cov_matrix)

        # Should equal max(variance) / min(variance)
        variances = np.diag(cov_matrix)
        expected_cond = np.max(variances) / np.min(variances)

        assert abs(cond - expected_cond) < 1e-6
