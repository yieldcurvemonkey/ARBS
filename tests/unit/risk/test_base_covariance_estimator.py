# ABOUTME: Tests for BaseCovarianceEstimator validation methods
# ABOUTME: Validates _validate_covariance_matrix, _ensure_positive_definite, and condition_number
"""
Tests for BaseCovarianceEstimator validation methods.

Tests cover:
1. _validate_covariance_matrix - valid matrices
2. _validate_covariance_matrix - invalid matrices (not square, not symmetric, negative eigenvalue)
3. _ensure_positive_definite - eigenvalue clipping
4. _ensure_positive_definite - symmetry preservation
5. condition_number - condition number calculation and singular matrix handling
"""

import pytest
import numpy as np
import polars as pl

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


# =============================================================================
# Concrete Implementation for Testing
# =============================================================================

class SimpleCovarianceEstimator(BaseCovarianceEstimator):
    """Simple concrete implementation for testing abstract base class."""

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """Simple sample covariance implementation."""
        returns_clean = self._handle_missing_data(returns)
        self.asset_names_ = list(returns_clean.columns)
        returns_array = returns_clean.to_numpy()
        self.cov_matrix_ = np.cov(returns_array, rowvar=False, ddof=1)
        return self.cov_matrix_


# =============================================================================
# Tests for _validate_covariance_matrix
# =============================================================================

def test_validate_covariance_matrix_valid():
    """Test _validate_covariance_matrix accepts valid covariance matrix."""
    estimator = SimpleCovarianceEstimator()

    # Create valid covariance matrix (3×3, symmetric, PSD)
    cov = np.array([
        [1.0, 0.5, 0.3],
        [0.5, 1.0, 0.4],
        [0.3, 0.4, 1.0]
    ])

    # Should not raise
    estimator._validate_covariance_matrix(cov)


def test_validate_covariance_matrix_not_square():
    """Test _validate_covariance_matrix rejects non-square matrix."""
    estimator = SimpleCovarianceEstimator()

    # Create non-square matrix (3×2)
    cov = np.array([
        [1.0, 0.5],
        [0.5, 1.0],
        [0.3, 0.4]
    ])

    with pytest.raises(ValueError, match="must be square"):
        estimator._validate_covariance_matrix(cov)


def test_validate_covariance_matrix_not_symmetric():
    """Test _validate_covariance_matrix rejects non-symmetric matrix."""
    estimator = SimpleCovarianceEstimator()

    # Create asymmetric matrix
    cov = np.array([
        [1.0, 0.5, 0.3],
        [0.5, 1.0, 0.4],
        [0.9, 0.4, 1.0]  # Note: cov[2,0] != cov[0,2]
    ])

    with pytest.raises(ValueError, match="must be symmetric"):
        estimator._validate_covariance_matrix(cov)


def test_validate_covariance_matrix_negative_eigenvalue():
    """Test _validate_covariance_matrix rejects matrix with negative eigenvalue."""
    estimator = SimpleCovarianceEstimator()

    # Create matrix with negative eigenvalue
    # This is a known indefinite matrix
    cov = np.array([
        [1.0, 2.0],
        [2.0, 1.0]
    ])
    # Eigenvalues are: 3.0, -1.0

    with pytest.raises(ValueError, match="positive semi-definite"):
        estimator._validate_covariance_matrix(cov)


# =============================================================================
# Tests for _ensure_positive_definite
# =============================================================================

def test_ensure_positive_definite():
    """Test _ensure_positive_definite clips negative eigenvalues."""
    estimator = SimpleCovarianceEstimator()

    # Create matrix with negative eigenvalue
    cov = np.array([
        [1.0, 2.0],
        [2.0, 1.0]
    ])
    # Eigenvalues: [3.0, -1.0]

    # Apply positive definite enforcement
    cov_pd = estimator._ensure_positive_definite(cov, min_eigenvalue=1e-8)

    # Check all eigenvalues are positive
    eigenvalues = np.linalg.eigvalsh(cov_pd)
    assert np.all(eigenvalues >= 0), f"Found negative eigenvalue: {eigenvalues.min()}"
    assert np.all(eigenvalues >= 1e-8), f"Found eigenvalue below threshold: {eigenvalues.min()}"


def test_ensure_positive_definite_symmetry():
    """Test _ensure_positive_definite preserves symmetry."""
    estimator = SimpleCovarianceEstimator()

    # Create matrix with small asymmetry
    cov = np.array([
        [1.0, 0.5, 0.3],
        [0.5, 1.0, 0.4],
        [0.3, 0.4, 1.0]
    ])

    # Apply positive definite enforcement
    cov_pd = estimator._ensure_positive_definite(cov)

    # Check symmetry
    assert np.allclose(cov_pd, cov_pd.T, atol=1e-10), "Output matrix is not symmetric"


# =============================================================================
# Tests for condition_number
# =============================================================================

def test_condition_number():
    """Test condition_number computes κ = λ_max / λ_min."""
    estimator = SimpleCovarianceEstimator()

    # Create returns that will produce diagonal covariance with known eigenvalues
    # Use uncorrelated returns with specific variances
    np.random.seed(42)
    n_samples = 1000
    returns_data = {
        'A': np.random.normal(0, np.sqrt(10.0), n_samples),  # var = 10.0
        'B': np.random.normal(0, np.sqrt(5.0), n_samples),   # var = 5.0
        'C': np.random.normal(0, np.sqrt(1.0), n_samples),   # var = 1.0
    }
    returns = pl.DataFrame(returns_data)

    # Fit estimator
    estimator.fit(returns)

    # Calculate condition number
    kappa = estimator.condition_number()

    # Expected: approximately 10.0 / 1.0 = 10.0 (with some variance)
    # Be lenient since we're using random data
    assert 5.0 < kappa < 15.0, \
        f"Expected κ ≈ 10.0 (range 5-15), got κ={kappa}"


def test_condition_number_singular_matrix():
    """Test condition_number returns inf for singular matrix."""
    estimator = SimpleCovarianceEstimator()

    # Create rank-deficient returns (singular covariance matrix)
    # Perfect correlation: B = 2*A
    returns = pl.DataFrame({
        'A': [1.0, 2.0, 3.0, 4.0, 5.0],
        'B': [2.0, 4.0, 6.0, 8.0, 10.0],  # Perfect correlation with A
    })

    # Fit estimator
    estimator.fit(returns)

    # Calculate condition number
    kappa = estimator.condition_number()

    # Should be inf (or very large for nearly singular)
    assert kappa == np.inf or kappa > 1e10, \
        f"Expected κ = inf for singular matrix, got κ={kappa}"
