# ABOUTME: Reference comparison tests validating SampleCovariance matches numpy.cov exactly
# ABOUTME: Tests use numpy.cov as ground truth to validate our implementation
"""
Validation Test: SampleCovariance - Reference Comparison

Component: SampleCovariance
Method: Comparison against numpy.cov reference implementation
Created: 2025-11-16
Status: ✅ PASSING / ❌ FAILING / ⚠️ PARTIAL

This test suite validates that our SampleCovariance implementation
matches numpy.cov exactly across a wide range of inputs.
"""

import numpy as np
import polars as pl

from Risk.Covariance.SampleCovariance import SampleCovariance


def test_matches_numpy_basic():
    """
    Should match np.cov exactly for basic random data.

    This is the fundamental test - if we match numpy.cov on random data,
    our implementation is correct.
    """
    np.random.seed(42)
    n_obs = 100
    n_assets = 20

    # Generate random returns
    returns_array = np.random.randn(n_obs, n_assets) * 0.01
    returns = pl.DataFrame(returns_array, schema=[f"asset_{i}" for i in range(n_assets)])

    # Our implementation
    estimator = SampleCovariance()
    our_cov = estimator.fit(returns)

    # NumPy reference
    numpy_cov = np.cov(returns_array, rowvar=False, ddof=1)

    # Should match to machine precision
    np.testing.assert_allclose(
        our_cov, numpy_cov, rtol=1e-12, atol=1e-15, err_msg="SampleCovariance should match numpy.cov exactly"
    )


def test_matches_numpy_various_shapes():
    """
    Should match np.cov for various matrix dimensions.

    Tests different (T, N) combinations to ensure our implementation
    handles all shapes correctly:
    - T >> N (many observations)
    - T ≈ N (balanced)
    - T < N (would be singular, but covariance still computable)
    """
    np.random.seed(123)

    test_cases = [
        (5, 10, "T < N (rank deficient)"),
        (20, 50, "T < N (highly underdetermined)"),
        (50, 20, "T > N (more typical)"),
        (100, 30, "T >> N (well determined)"),
        (200, 5, "T >>> N (very well determined)"),
    ]

    for n_obs, n_assets, description in test_cases:
        # Generate random returns
        returns_array = np.random.randn(n_obs, n_assets) * 0.01
        returns = pl.DataFrame(returns_array, schema=[f"asset_{i}" for i in range(n_assets)])

        # Our implementation
        estimator = SampleCovariance()
        our_cov = estimator.fit(returns)

        # NumPy reference
        numpy_cov = np.cov(returns_array, rowvar=False, ddof=1)

        # Should match exactly
        np.testing.assert_allclose(
            our_cov, numpy_cov, rtol=1e-12, atol=1e-15, err_msg=f"Failed for {description} (T={n_obs}, N={n_assets})"
        )


def test_matches_numpy_edge_cases():
    """
    Should match np.cov for edge cases.

    Tests challenging inputs:
    - Constant columns (zero variance)
    - Nearly constant columns (very low variance)
    - Perfectly correlated assets
    - Negative returns
    - Mixed positive/negative
    """
    # Test 1: Constant column (zero variance)
    returns1 = pl.DataFrame(
        {"A": [0.01, 0.02, 0.03, -0.01], "B": [0.02, 0.02, 0.02, 0.02], "C": [0.01, -0.01, 0.02, -0.02]}  # Constant
    )

    estimator = SampleCovariance()
    our_cov1 = estimator.fit(returns1)
    numpy_cov1 = np.cov(returns1.to_numpy(), rowvar=False, ddof=1)

    np.testing.assert_allclose(our_cov1, numpy_cov1, rtol=1e-12, atol=1e-15)

    # Test 2: Nearly constant column (very low variance)
    np.random.seed(42)
    returns2 = pl.DataFrame(
        {
            "A": np.random.randn(50) * 0.01,
            "B": 0.02 + np.random.randn(50) * 1e-8,  # Nearly constant
            "C": np.random.randn(50) * 0.01,
        }
    )

    our_cov2 = estimator.fit(returns2)
    numpy_cov2 = np.cov(returns2.to_numpy(), rowvar=False, ddof=1)

    np.testing.assert_allclose(our_cov2, numpy_cov2, rtol=1e-12, atol=1e-15)

    # Test 3: Perfectly correlated assets
    np.random.seed(123)
    base = np.random.randn(30) * 0.01
    returns3 = pl.DataFrame(
        {"A": base, "B": base * 2.0, "C": -base * 0.5}  # Perfect correlation  # Perfect negative correlation
    )

    our_cov3 = estimator.fit(returns3)
    numpy_cov3 = np.cov(returns3.to_numpy(), rowvar=False, ddof=1)

    np.testing.assert_allclose(our_cov3, numpy_cov3, rtol=1e-12, atol=1e-15)


def test_matches_numpy_ddof():
    """
    Should use ddof=1 (unbiased estimator).

    Verify that our implementation uses the correct degrees of freedom
    by comparing against both ddof=0 and ddof=1.
    """
    np.random.seed(42)
    n_obs = 50
    n_assets = 10

    returns_array = np.random.randn(n_obs, n_assets) * 0.01
    returns = pl.DataFrame(returns_array, schema=[f"asset_{i}" for i in range(n_assets)])

    # Our implementation
    estimator = SampleCovariance()
    our_cov = estimator.fit(returns)

    # NumPy with ddof=1 (unbiased)
    numpy_cov_unbiased = np.cov(returns_array, rowvar=False, ddof=1)

    # NumPy with ddof=0 (biased)
    numpy_cov_biased = np.cov(returns_array, rowvar=False, ddof=0)

    # Should match unbiased estimator
    np.testing.assert_allclose(
        our_cov, numpy_cov_unbiased, rtol=1e-12, atol=1e-15, err_msg="Should match unbiased estimator (ddof=1)"
    )

    # Should NOT match biased estimator (except by coincidence)
    # The difference should be a factor of (n-1)/n
    scaling_factor = (n_obs - 1) / n_obs
    np.testing.assert_allclose(
        numpy_cov_biased,
        numpy_cov_unbiased * scaling_factor,
        rtol=1e-12,
        atol=1e-15,
        err_msg="Sanity check: biased and unbiased should differ by (n-1)/n",
    )

    # Verify we're NOT using the biased version
    # (this would fail if we accidentally used ddof=0)
    max_diff = np.max(np.abs(our_cov - numpy_cov_biased))
    assert max_diff > 1e-10, "Should NOT match biased estimator (ddof=0)"


def test_matches_numpy_single_asset():
    """
    Should match np.cov for single asset case.

    Edge case: when N=1, covariance matrix is 1×1.
    """
    np.random.seed(42)
    returns_array = np.random.randn(100, 1) * 0.01
    returns = pl.DataFrame(returns_array, schema=["asset_0"])

    # Our implementation
    estimator = SampleCovariance()
    our_cov = estimator.fit(returns)

    # NumPy reference
    numpy_cov = np.cov(returns_array, rowvar=False, ddof=1)

    # Ensure both are 2D
    numpy_cov = np.atleast_2d(numpy_cov)

    # Should match exactly
    np.testing.assert_allclose(
        our_cov, numpy_cov, rtol=1e-12, atol=1e-15, err_msg="Single asset case should match numpy.cov"
    )

    # Should be 1×1
    assert our_cov.shape == (1, 1)


def test_matches_numpy_two_assets():
    """
    Should match np.cov for two asset case.

    Special case: N=2, simplest multi-asset case.
    """
    np.random.seed(123)
    returns_array = np.random.randn(50, 2) * 0.01
    returns = pl.DataFrame(returns_array, schema=["asset_0", "asset_1"])

    # Our implementation
    estimator = SampleCovariance()
    our_cov = estimator.fit(returns)

    # NumPy reference
    numpy_cov = np.cov(returns_array, rowvar=False, ddof=1)

    # Should match exactly
    np.testing.assert_allclose(
        our_cov, numpy_cov, rtol=1e-12, atol=1e-15, err_msg="Two asset case should match numpy.cov"
    )

    # Should be symmetric
    assert abs(our_cov[0, 1] - our_cov[1, 0]) < 1e-15


def test_matches_numpy_large_scale():
    """
    Should match np.cov for large matrices.

    Tests that our implementation scales correctly and maintains
    precision with larger matrices.
    """
    np.random.seed(42)
    n_obs = 500
    n_assets = 100

    returns_array = np.random.randn(n_obs, n_assets) * 0.01
    returns = pl.DataFrame(returns_array, schema=[f"asset_{i}" for i in range(n_assets)])

    # Our implementation
    estimator = SampleCovariance()
    our_cov = estimator.fit(returns)

    # NumPy reference
    numpy_cov = np.cov(returns_array, rowvar=False, ddof=1)

    # Should match to machine precision even for large matrices
    np.testing.assert_allclose(
        our_cov, numpy_cov, rtol=1e-12, atol=1e-15, err_msg="Large scale case should match numpy.cov"
    )

    # Verify matrix properties
    assert our_cov.shape == (n_assets, n_assets)

    # Should be symmetric
    assert np.allclose(our_cov, our_cov.T, rtol=1e-14, atol=1e-15)

    # Diagonal should be positive
    assert np.all(np.diag(our_cov) > 0)


# Add validation report at end
"""
VALIDATION REPORT
=================
Component: SampleCovariance
Method: Reference Comparison (numpy.cov)
Tests: 8 total
  - test_matches_numpy_basic: Random data, basic validation
  - test_matches_numpy_various_shapes: Different (T, N) dimensions
  - test_matches_numpy_edge_cases: Constant/correlated/nearly singular
  - test_matches_numpy_ddof: Verify unbiased estimator (ddof=1)
  - test_matches_numpy_single_asset: N=1 edge case
  - test_matches_numpy_two_assets: N=2 simple case
  - test_matches_numpy_large_scale: Large matrices (T=500, N=100)

Tolerance: rtol=1e-12, atol=1e-15 (machine precision)
Expected Result: All tests passing
Confidence: 100% (direct comparison to numpy.cov reference)

Notes:
- SampleCovariance uses np.cov internally, so exact match expected
- Tests verify correct usage (rowvar=False, ddof=1)
- Edge cases ensure robustness across all inputs
- Large scale test validates no numerical drift
"""
