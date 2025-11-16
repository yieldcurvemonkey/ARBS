# ABOUTME: Sample covariance matrix estimator (extends BaseCovarianceEstimator, baseline/benchmark method)
# ABOUTME: Standard unbiased estimator Σ̂ = (1/(T-1)) Σ(r_t - r̄)(r_t - r̄)' for comparison with shrinkage methods
"""
Sample Covariance Estimator

The standard unbiased covariance estimator:
    Σ̂ = (1/(T-1)) Σ(r_t - r̄)(r_t - r̄)'

Properties:
- Unbiased estimator of true covariance
- Maximum likelihood estimator under normality
- Works well when T >> N (many observations per asset)

Limitations:
- Noisy when T ≈ N (portfolio context)
- Singular when T < N
- Can have large estimation error
- Condition number can be high (unstable inversion)

Use as baseline for comparison with shrinkage methods.
"""

import numpy as np
import polars as pl

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


class SampleCovariance(BaseCovarianceEstimator):
    """
    Sample covariance matrix estimator (baseline).

    This is the standard textbook estimator, used as a baseline
    for comparing against shrinkage methods like Ledoit-Wolf.
    """

    def __init__(self, handle_missing: str = "drop"):
        """
        Initialize sample covariance estimator.

        Args:
            handle_missing: How to handle missing data
                - 'drop': Drop rows with any NaN
                - 'pairwise': Use pairwise complete observations
        """
        super().__init__(handle_missing=handle_missing)

    def _fit_impl(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate sample covariance matrix.

        Formula: Σ̂ = (1/(T-1)) Σ(r_t - r̄)(r_t - r̄)'

        Args:
            returns: Clean DataFrame of returns (T×N), missing data already handled

        Returns:
            Sample covariance matrix (N×N)
        """
        # Calculate covariance matrix using numpy
        # np.cov with ddof=1 (unbiased estimator, same as pandas default)
        returns_array = returns.to_numpy()
        cov = np.cov(returns_array, rowvar=False, ddof=1)

        # Ensure covariance is always 2D (np.cov returns scalar for single column)
        return np.atleast_2d(cov)

    def __repr__(self) -> str:
        return "SampleCovariance()"
