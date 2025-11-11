# ABOUTME: Test suite for IdentityCovariance risk model
# ABOUTME: Verifies identity matrix structure scaled by mean variance with proper edge cases and positive definiteness
"""
Tests for Identity Covariance Estimator

The identity covariance estimator assumes zero correlation between assets
and uniform variance across all assets equal to the mean variance.

Formula:
    Σ = σ² × I
    where σ² = mean(var(returns)) and I is identity matrix

Use cases:
- Simplest possible risk model (diagonal, uniform)
- Baseline for comparison with more sophisticated estimators
- When you want to ignore correlation structure entirely

Properties:
- Diagonal matrix (off-diagonals = 0)
- Constant diagonal (all variances equal)
- Positive definite (condition number = 1.0)
- Extremely fast to compute
"""

import pytest
import numpy as np
import pandas as pd


class TestIdentityCovarianceBasics:
    """Test basic IdentityCovariance functionality."""

    def test_identity_covariance_can_be_imported(self):
        """Verify IdentityCovariance exists."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance
        assert IdentityCovariance is not None

    def test_identity_covariance_can_be_instantiated(self):
        """IdentityCovariance should be instantiable."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        estimator = IdentityCovariance()
        assert estimator is not None


class TestIdentityCovarianceEstimation:
    """Test identity covariance estimation."""

    def test_basic_estimation(self):
        """Basic returns should produce identity-scaled covariance."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        # Create simple returns data
        np.random.seed(42)
        returns = pd.DataFrame(
            np.random.randn(100, 5),
            columns=['A', 'B', 'C', 'D', 'E']
        )

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Should return a matrix
        assert cov_matrix is not None
        assert isinstance(cov_matrix, np.ndarray)
        assert cov_matrix.shape == (5, 5)

    def test_identity_structure(self):
        """Off-diagonals should be zero, diagonal should be constant."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Check off-diagonals are zero
        n = cov_matrix.shape[0]
        for i in range(n):
            for j in range(n):
                if i != j:
                    assert abs(cov_matrix[i, j]) < 1e-10, f"Off-diagonal [{i},{j}] should be zero"

        # Check diagonal is constant
        diagonal_values = np.diag(cov_matrix)
        assert np.allclose(diagonal_values, diagonal_values[0]), "All diagonal values should be equal"

    def test_diagonal_is_mean_variance(self):
        """All diagonal values should equal mean of individual variances."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        # Calculate expected mean variance
        individual_variances = returns.var()
        expected_mean_variance = individual_variances.mean()

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Check diagonal equals mean variance
        diagonal_values = np.diag(cov_matrix)
        assert np.allclose(diagonal_values, expected_mean_variance), \
            f"Diagonal should be {expected_mean_variance}, got {diagonal_values[0]}"

    def test_single_asset(self):
        """Edge case: single asset should return 1x1 matrix with its variance."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 1), columns=['A'])

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be 1x1 matrix
        assert cov_matrix.shape == (1, 1)

        # Value should equal the asset's variance
        expected_variance = returns['A'].var()
        assert abs(cov_matrix[0, 0] - expected_variance) < 1e-10

    def test_multiple_assets(self):
        """Should work with 5+ assets."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        n_assets = 10
        returns = pd.DataFrame(np.random.randn(100, n_assets))

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be NxN matrix
        assert cov_matrix.shape == (n_assets, n_assets)

        # Verify identity structure (I × σ²)
        mean_var = returns.var().mean()
        expected = np.eye(n_assets) * mean_var

        np.testing.assert_array_almost_equal(cov_matrix, expected, decimal=10)

    def test_uniform_variance_case(self):
        """When all variances equal, result should be var(asset) × I."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)

        # Create returns with uniform variance
        # All assets have same underlying variance
        base_returns = np.random.randn(100)
        returns = pd.DataFrame({
            'A': base_returns + np.random.randn(100) * 0.01,
            'B': base_returns * 1.0 + np.random.randn(100) * 0.01,
            'C': base_returns * 1.0 + np.random.randn(100) * 0.01,
        })

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Should be close to identity scaled by common variance
        mean_var = returns.var().mean()

        # Diagonal should all be mean_var
        diagonal_values = np.diag(cov_matrix)
        assert np.allclose(diagonal_values, mean_var)

    def test_varying_variance(self):
        """When variances differ widely, diagonal should be mean variance."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)

        # Create returns with widely varying variances
        returns = pd.DataFrame({
            'Low_Vol': np.random.randn(100) * 0.1,   # Low variance
            'Med_Vol': np.random.randn(100) * 1.0,   # Medium variance
            'High_Vol': np.random.randn(100) * 10.0, # High variance
        })

        # Calculate individual and mean variance
        individual_vars = returns.var()
        mean_var = individual_vars.mean()

        # Verify variances are actually different
        assert individual_vars.max() / individual_vars.min() > 5.0, "Variances should differ significantly"

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # All diagonal elements should equal mean variance (not individual variances)
        diagonal_values = np.diag(cov_matrix)
        assert np.allclose(diagonal_values, mean_var)

        # Verify it's different from at least some individual variances
        assert not np.allclose(diagonal_values[0], individual_vars.iloc[0])

    def test_output_is_positive_definite(self):
        """Identity scaled by positive number should be positive definite."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Check eigenvalues are all positive
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 0), "All eigenvalues should be strictly positive"

        # For identity matrix scaled by constant, all eigenvalues should be equal
        assert np.allclose(eigenvalues, eigenvalues[0]), "All eigenvalues should be equal"

        # Condition number should be 1.0 (perfectly conditioned)
        cond_number = np.linalg.cond(cov_matrix)
        assert abs(cond_number - 1.0) < 1e-10, f"Condition number should be 1.0, got {cond_number}"


class TestIdentityCovarianceProperties:
    """Test mathematical properties of identity covariance."""

    def test_is_symmetric(self):
        """Covariance matrix should be symmetric."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(50, 5))

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        np.testing.assert_array_almost_equal(cov_matrix, cov_matrix.T)

    def test_perfect_condition_number(self):
        """Identity matrix should have condition number = 1.0."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(50, 10))

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        cond_number = np.linalg.cond(cov_matrix)
        assert abs(cond_number - 1.0) < 1e-10, "Identity matrix should have perfect condition number"

    def test_determinant_is_power_of_mean_variance(self):
        """det(σ² I) = (σ²)^N for N assets."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        n_assets = 5
        returns = pd.DataFrame(np.random.randn(100, n_assets))

        mean_var = returns.var().mean()

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        determinant = np.linalg.det(cov_matrix)
        expected_det = mean_var ** n_assets

        assert abs(determinant - expected_det) / expected_det < 1e-10, \
            f"Determinant should be {expected_det}, got {determinant}"


class TestIntegrationWithBase:
    """Test integration with BaseCovarianceEstimator."""

    def test_inherits_from_base(self):
        """IdentityCovariance should inherit from BaseCovarianceEstimator."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance
        from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator

        estimator = IdentityCovariance()
        assert isinstance(estimator, BaseCovarianceEstimator)

    def test_get_covariance_after_fit(self):
        """Should be able to retrieve covariance after fitting."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = IdentityCovariance()
        cov_from_fit = estimator.fit(returns)
        cov_from_get = estimator.get_covariance()

        np.testing.assert_array_equal(cov_from_fit, cov_from_get)

    def test_condition_number_method(self):
        """Should be able to compute condition number via base class method."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        estimator = IdentityCovariance()
        estimator.fit(returns)

        cond_number = estimator.condition_number()
        assert abs(cond_number - 1.0) < 1e-10


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_missing_data_with_drop(self):
        """Should handle NaN values by dropping rows."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        returns = pd.DataFrame(np.random.randn(100, 5))

        # Introduce NaN values
        returns.iloc[10:20, 2] = np.nan

        estimator = IdentityCovariance(handle_missing='drop')
        cov_matrix = estimator.fit(returns)

        # Should still produce valid covariance
        assert not np.any(np.isnan(cov_matrix))
        assert cov_matrix.shape == (5, 5)

    def test_very_small_variance(self):
        """Should handle very small variances without numerical issues."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        # Very small returns
        returns = pd.DataFrame(np.random.randn(100, 5) * 1e-10)

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Should still be positive definite
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 0)

    def test_very_large_variance(self):
        """Should handle very large variances without numerical issues."""
        from Risk.Covariance.IdentityCovariance import IdentityCovariance

        np.random.seed(42)
        # Very large returns
        returns = pd.DataFrame(np.random.randn(100, 5) * 1e10)

        estimator = IdentityCovariance()
        cov_matrix = estimator.fit(returns)

        # Should still be positive definite
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        assert np.all(eigenvalues > 0)
        assert not np.any(np.isinf(cov_matrix))
