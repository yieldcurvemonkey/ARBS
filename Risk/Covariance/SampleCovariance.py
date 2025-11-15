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

    def __init__(self, handle_missing: str = 'drop'):
        """
        Initialize sample covariance estimator.

        Args:
            handle_missing: How to handle missing data
                - 'drop': Drop rows with any NaN
                - 'pairwise': Use pairwise complete observations
        """
        super().__init__(handle_missing=handle_missing)

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate sample covariance matrix.

        Formula: Σ̂ = (1/(T-1)) Σ(r_t - r̄)(r_t - r̄)'

        Args:
            returns: DataFrame of returns (T×N)

        Returns:
            Sample covariance matrix (N×N)
        """
        # Handle missing data (returns polars DataFrame)
        returns_clean = self._handle_missing_data(returns)

        # Store asset names
        self.asset_names_ = list(returns_clean.columns)

        # Calculate covariance matrix using numpy
        # np.cov with ddof=1 (unbiased estimator, same as pandas default)
        returns_array = returns_clean.to_numpy()
        self.cov_matrix_ = np.cov(returns_array, rowvar=False, ddof=1)

        return self.cov_matrix_

    def __repr__(self) -> str:
        return "SampleCovariance()"
