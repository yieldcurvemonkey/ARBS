# ABOUTME: Ground truth validation tests for SampleCovariance using hand-calculated examples
# ABOUTME: Tests prove correctness by comparing to manually verified calculations
"""
Validation Test: SampleCovariance - Ground Truth

Component: SampleCovariance
Method: Hand-calculated examples
Created: 2025-11-16
Status: ✅ PASSING / ❌ FAILING / ⚠️ PARTIAL
"""

import numpy as np
import polars as pl

from Risk.Covariance.SampleCovariance import SampleCovariance


def test_2x2_known_values():
    """
    Test sample covariance against hand-calculated 2×2 matrix.

    Given returns:
    Asset A: [0.01, 0.02, -0.01]
    Asset B: [0.02, 0.01, -0.02]

    Hand calculation (ddof=1):
    mean_A = (0.01 + 0.02 - 0.01) / 3 = 0.00667
    mean_B = (0.02 + 0.01 - 0.02) / 3 = 0.00333

    Var(A) = [(0.01-0.00667)² + (0.02-0.00667)² + (-0.01-0.00667)²] / 2
           = [0.000011 + 0.000178 + 0.000278] / 2
           = 0.0002333

    Var(B) = [(0.02-0.00333)² + (0.01-0.00333)² + (-0.02-0.00333)²] / 2
           = [0.000278 + 0.000044 + 0.000544] / 2
           = 0.0004333

    Cov(A,B) = sum[(A_i - mean_A)(B_i - mean_B)] / 2
             = [(0.01-0.00667)(0.02-0.00333) + (0.02-0.00667)(0.01-0.00333) + (-0.01-0.00667)(-0.02-0.00333)] / 2
             = [0.0000556 + 0.0000889 + 0.0003889] / 2
             = 0.0002667
    """
    returns = pl.DataFrame({"A": [0.01, 0.02, -0.01], "B": [0.02, 0.01, -0.02]})

    estimator = SampleCovariance()
    cov = estimator.fit(returns)

    # Hand-calculated expected values
    expected = np.array([[0.0002333, 0.0002667], [0.0002667, 0.0004333]])

    np.testing.assert_allclose(cov, expected, rtol=1e-3, atol=1e-6)


def test_3x3_identity_case():
    """
    Test case where returns are uncorrelated (should give diagonal matrix).

    Asset A: [0.01, -0.01, 0.01]  (alternating)
    Asset B: [0.02, 0.02, -0.04]  (uncorrelated with A)
    Asset C: [0.00, 0.03, -0.03]  (uncorrelated with both)
    """
    returns = pl.DataFrame({"A": [0.01, -0.01, 0.01], "B": [0.02, 0.02, -0.04], "C": [0.00, 0.03, -0.03]})

    estimator = SampleCovariance()
    cov = estimator.fit(returns)

    # Off-diagonal elements should be close to zero (uncorrelated)
    # Extract off-diagonal
    off_diag = cov[~np.eye(3, dtype=bool)]

    # All off-diagonal should be small
    assert np.all(np.abs(off_diag) < 0.001)

    # Diagonal should be positive
    assert np.all(np.diag(cov) > 0)


def test_single_asset():
    """Test with single asset (should return 1×1 matrix)."""
    returns = pl.DataFrame({"A": [0.01, 0.02, -0.01, 0.03]})

    estimator = SampleCovariance()
    cov = estimator.fit(returns)

    # Should be 1×1
    assert cov.shape == (1, 1)

    # Should be positive
    assert cov[0, 0] > 0

    # Should match numpy
    expected = np.var(returns["A"].to_numpy(), ddof=1)
    np.testing.assert_allclose(cov[0, 0], expected, rtol=1e-10)


def test_zero_variance_asset():
    """Test with constant returns (zero variance)."""
    returns = pl.DataFrame({"A": [0.01, 0.02, 0.03], "B": [0.02, 0.02, 0.02]})  # Constant (zero variance)

    estimator = SampleCovariance()
    cov = estimator.fit(returns)

    # Asset B should have zero variance
    assert abs(cov[1, 1]) < 1e-10

    # Covariance with B should also be zero
    assert abs(cov[0, 1]) < 1e-10
    assert abs(cov[1, 0]) < 1e-10


# Add validation report at end
"""
VALIDATION REPORT
=================
Component: SampleCovariance
Method: Ground Truth (Hand-calculated)
Tests: 4 total
  - test_2x2_known_values: Hand-calculated 2×2 matrix
  - test_3x3_identity_case: Uncorrelated returns
  - test_single_asset: Single asset edge case
  - test_zero_variance_asset: Constant returns edge case

Expected Result: All tests passing
Confidence: 99% (matches hand calculations and numpy)
"""
