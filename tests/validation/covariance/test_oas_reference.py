"""
Validation Test: OAShrinkage - Reference Comparison

Component: OAShrinkage
Method: Direct comparison with sklearn.covariance.OAS
Created: 2025-11-16

This test suite validates that our OAShrinkage implementation
produces identical results to sklearn's reference implementation.
"""

import numpy as np
import polars as pl
import pytest
from sklearn.covariance import OAS

from Risk.Covariance.OAShrinkage import OAShrinkage


def test_matches_sklearn_basic():
    """Should match sklearn.covariance.OAS on basic random data."""
    np.random.seed(42)
    n_samples, n_features = 100, 20
    returns_array = np.random.randn(n_samples, n_features) * 0.01
    returns = pl.DataFrame(returns_array, schema=[f"A{i}" for i in range(n_features)])

    # Our implementation
    our_oas = OAShrinkage()
    our_cov = our_oas.fit(returns)
    our_shrinkage = our_oas.get_shrinkage_coefficient()

    # Sklearn reference
    sk_oas = OAS()
    sk_oas.fit(returns_array)
    sk_cov = sk_oas.covariance_
    sk_shrinkage = sk_oas.shrinkage_

    # Covariance matrices should match closely
    np.testing.assert_allclose(our_cov, sk_cov, rtol=1e-6, atol=1e-8, err_msg="Covariance matrices don't match")

    # Shrinkage coefficients should match
    np.testing.assert_allclose(
        our_shrinkage, sk_shrinkage, rtol=1e-4, atol=1e-6, err_msg="Shrinkage coefficients don't match"
    )


def test_shrinkage_matches():
    """Verify ρ (rho) shrinkage parameter matches sklearn's exactly."""
    np.random.seed(123)
    n_samples, n_features = 150, 30
    returns_array = np.random.randn(n_samples, n_features) * 0.02
    returns = pl.DataFrame(returns_array, schema=[f"A{i}" for i in range(n_features)])

    # Our implementation
    our_oas = OAShrinkage()
    our_oas.fit(returns)
    our_rho = our_oas.get_shrinkage_coefficient()

    # Sklearn reference
    sk_oas = OAS()
    sk_oas.fit(returns_array)
    sk_rho = sk_oas.shrinkage_

    # Should match exactly
    assert our_rho == pytest.approx(sk_rho, rel=1e-6, abs=1e-8), f"Our ρ={our_rho:.6f}, sklearn ρ={sk_rho:.6f}"


def test_matches_sklearn_various_dimensions():
    """Test various n/p ratios to ensure consistent behavior."""
    test_cases = [
        (50, 10, "n >> p"),  # Many observations vs features
        (100, 20, "n > p (moderate)"),  # Moderate ratio
        (80, 40, "n ≈ 2p"),  # Challenging case
        (200, 50, "n = 4p"),  # Typical case
    ]

    for n_samples, n_features, description in test_cases:
        np.random.seed(42)
        returns_array = np.random.randn(n_samples, n_features) * 0.01
        returns = pl.DataFrame(returns_array, schema=[f"A{i}" for i in range(n_features)])

        # Our implementation
        our_oas = OAShrinkage()
        our_cov = our_oas.fit(returns)
        our_shrinkage = our_oas.get_shrinkage_coefficient()

        # Sklearn reference
        sk_oas = OAS()
        sk_oas.fit(returns_array)
        sk_cov = sk_oas.covariance_
        sk_shrinkage = sk_oas.shrinkage_

        # Validate match
        np.testing.assert_allclose(
            our_cov, sk_cov, rtol=1e-6, atol=1e-8, err_msg=f"Covariance mismatch for case: {description}"
        )

        np.testing.assert_allclose(
            our_shrinkage, sk_shrinkage, rtol=1e-4, atol=1e-6, err_msg=f"Shrinkage mismatch for case: {description}"
        )


def test_matches_sklearn_factor_model():
    """Test with structured data (factor model) - should have low shrinkage."""
    np.random.seed(42)
    n_samples, n_features = 500, 50
    n_factors = 5

    # Generate factor-structured data
    factors = np.random.randn(n_samples, n_factors)
    loadings = np.random.randn(n_features, n_factors)
    idiosyncratic = np.random.randn(n_samples, n_features) * 0.1
    returns_array = (factors @ loadings.T + idiosyncratic) * 0.01

    returns = pl.DataFrame(returns_array, schema=[f"A{i}" for i in range(n_features)])

    # Our implementation
    our_oas = OAShrinkage()
    our_cov = our_oas.fit(returns)
    our_shrinkage = our_oas.get_shrinkage_coefficient()

    # Sklearn reference
    sk_oas = OAS()
    sk_oas.fit(returns_array)
    sk_cov = sk_oas.covariance_
    sk_shrinkage = sk_oas.shrinkage_

    # Validate match
    np.testing.assert_allclose(our_cov, sk_cov, rtol=1e-6, atol=1e-8, err_msg="Covariance mismatch for factor model")

    np.testing.assert_allclose(
        our_shrinkage, sk_shrinkage, rtol=1e-4, atol=1e-6, err_msg="Shrinkage mismatch for factor model"
    )

    # Factor models should have low shrinkage (data has structure)
    assert our_shrinkage < 0.1, f"Expected low shrinkage for factor model, got {our_shrinkage:.4f}"
    assert sk_shrinkage < 0.1, f"sklearn also should have low shrinkage, got {sk_shrinkage:.4f}"


def test_matches_sklearn_random_noise():
    """Test with pure random noise - should have high shrinkage."""
    np.random.seed(42)
    n_samples, n_features = 200, 50

    # Pure random noise (no structure)
    returns_array = np.random.randn(n_samples, n_features) * 0.01
    returns = pl.DataFrame(returns_array, schema=[f"A{i}" for i in range(n_features)])

    # Our implementation
    our_oas = OAShrinkage()
    our_cov = our_oas.fit(returns)
    our_shrinkage = our_oas.get_shrinkage_coefficient()

    # Sklearn reference
    sk_oas = OAS()
    sk_oas.fit(returns_array)
    sk_cov = sk_oas.covariance_
    sk_shrinkage = sk_oas.shrinkage_

    # Validate match
    np.testing.assert_allclose(our_cov, sk_cov, rtol=1e-6, atol=1e-8, err_msg="Covariance mismatch for random noise")

    np.testing.assert_allclose(
        our_shrinkage, sk_shrinkage, rtol=1e-4, atol=1e-6, err_msg="Shrinkage mismatch for random noise"
    )

    # Random noise should have high shrinkage (no trust in sample covariance)
    assert our_shrinkage > 0.3, f"Expected high shrinkage for random noise, got {our_shrinkage:.4f}"
    assert sk_shrinkage > 0.3, f"sklearn also should have high shrinkage, got {sk_shrinkage:.4f}"


def test_matches_sklearn_precision_matrix():
    """Test that precision matrix (inverse) also matches when store_precision=True."""
    np.random.seed(42)
    n_samples, n_features = 100, 20
    returns_array = np.random.randn(n_samples, n_features) * 0.01
    returns = pl.DataFrame(returns_array, schema=[f"A{i}" for i in range(n_features)])

    # Our implementation with precision storage
    our_oas = OAShrinkage(store_precision=True)
    our_cov = our_oas.fit(returns)
    our_precision = our_oas.get_precision()

    # Sklearn reference with precision storage
    sk_oas = OAS(store_precision=True)
    sk_oas.fit(returns_array)
    sk_precision = sk_oas.precision_

    # Precision matrices should match
    np.testing.assert_allclose(
        our_precision, sk_precision, rtol=1e-6, atol=1e-8, err_msg="Precision matrices don't match"
    )

    # Verify precision is indeed the inverse of covariance
    identity = np.eye(n_features)
    np.testing.assert_allclose(our_cov @ our_precision, identity, rtol=1e-6, atol=1e-8)


def test_matches_sklearn_small_sample():
    """Test challenging case where n < p (more features than samples)."""
    np.random.seed(42)
    n_samples, n_features = 30, 50  # n < p

    returns_array = np.random.randn(n_samples, n_features) * 0.01
    returns = pl.DataFrame(returns_array, schema=[f"A{i}" for i in range(n_features)])

    # Our implementation
    our_oas = OAShrinkage()
    our_cov = our_oas.fit(returns)
    our_shrinkage = our_oas.get_shrinkage_coefficient()

    # Sklearn reference
    sk_oas = OAS()
    sk_oas.fit(returns_array)
    sk_cov = sk_oas.covariance_
    sk_shrinkage = sk_oas.shrinkage_

    # Should still match even in this challenging case
    np.testing.assert_allclose(our_cov, sk_cov, rtol=1e-6, atol=1e-8, err_msg="Covariance mismatch for n < p case")

    np.testing.assert_allclose(
        our_shrinkage, sk_shrinkage, rtol=1e-4, atol=1e-6, err_msg="Shrinkage mismatch for n < p case"
    )

    # Both should produce well-conditioned matrices
    our_cond = np.linalg.cond(our_cov)
    sk_cond = np.linalg.cond(sk_cov)
    assert our_cond < 1e6, f"Our covariance poorly conditioned: {our_cond}"
    assert sk_cond < 1e6, f"sklearn covariance poorly conditioned: {sk_cond}"


def test_matches_sklearn_single_asset():
    """Test edge case with single asset (1D returns)."""
    np.random.seed(42)
    n_samples = 100
    returns_array = np.random.randn(n_samples, 1) * 0.01
    returns = pl.DataFrame(returns_array, schema=["A0"])

    # Our implementation
    our_oas = OAShrinkage()
    our_cov = our_oas.fit(returns)
    our_shrinkage = our_oas.get_shrinkage_coefficient()

    # Sklearn reference
    sk_oas = OAS()
    sk_oas.fit(returns_array)
    sk_cov = sk_oas.covariance_
    sk_shrinkage = sk_oas.shrinkage_

    # Single asset case
    assert our_cov.shape == (1, 1)
    assert sk_cov.shape == (1, 1)

    # Should match
    np.testing.assert_allclose(our_cov, sk_cov, rtol=1e-6, atol=1e-8, err_msg="Covariance mismatch for single asset")

    np.testing.assert_allclose(
        our_shrinkage, sk_shrinkage, rtol=1e-4, atol=1e-6, err_msg="Shrinkage mismatch for single asset"
    )


"""
VALIDATION REPORT
=================
Component: OAShrinkage
Method: Reference Comparison (sklearn.covariance.OAS)
Tests: 8 total
  - test_matches_sklearn_basic: Basic random data comparison
  - test_shrinkage_matches: Shrinkage parameter ρ validation
  - test_matches_sklearn_various_dimensions: Multiple n/p ratios
  - test_matches_sklearn_factor_model: Structured data (low shrinkage expected)
  - test_matches_sklearn_random_noise: Random noise (high shrinkage expected)
  - test_matches_sklearn_precision_matrix: Precision (inverse) matrix comparison
  - test_matches_sklearn_small_sample: Challenging n < p case
  - test_matches_sklearn_single_asset: Edge case (1D returns)

Expected Results:
- All covariance matrices match sklearn with rtol=1e-6, atol=1e-8
- All shrinkage coefficients match sklearn with rtol=1e-4, atol=1e-6
- Factor models: ρ < 0.1 (trusts structure)
- Random noise: ρ > 0.3 (distrusts noise)

Confidence: Will be 100% if all tests pass (direct comparison with reference implementation)
"""
