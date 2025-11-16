# ABOUTME: Identity covariance matrix estimator (extends BaseCovarianceEstimator, diagonal risk model with uniform variance)
# ABOUTME: Assumes zero correlation between assets with all variances equal to mean variance: Σ = σ² × I where σ² = mean(var(returns))
"""
Identity Covariance Estimator

The simplest possible covariance estimator:
    Σ = σ² × I
    where σ² = mean(var(returns)) and I is identity matrix

Properties:
- Diagonal matrix (all correlations = 0)
- Uniform variance (all assets have same variance = mean variance)
- Perfect conditioning (condition number = 1.0)
- Extremely fast to compute

Use cases:
- Baseline for comparison with more sophisticated estimators
- When you want to ignore correlation structure entirely
- When you want perfectly stable matrix inversion
- Initial guess for optimization algorithms

Limitations:
- Ignores all correlation information (likely suboptimal)
- Ignores individual asset variance differences
- Will underperform sample/shrinkage estimators in most cases
- Only use when simplicity/stability is paramount

Mathematics:
    For N assets with returns r_i, i=1..N:
    Individual variances: σ²_i = var(r_i)
    Mean variance: σ² = (1/N) Σ σ²_i
    Covariance matrix: Σ_ij = σ² if i=j, 0 if i≠j
"""

import numpy as np
import polars as pl

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


class IdentityCovariance(BaseCovarianceEstimator):
    """
    Identity covariance matrix estimator.

    This is the simplest possible covariance estimator:
    - All correlations set to zero (diagonal matrix)
    - All variances set to mean variance across assets
    - Results in identity matrix scaled by a constant

    Perfect stability (condition number = 1.0) but ignores all
    correlation information and individual variance differences.
    """

    def __init__(self, handle_missing: str = "drop"):
        """
        Initialize identity covariance estimator.

        Args:
            handle_missing: How to handle missing data
                - 'drop': Drop rows with any NaN
                - 'pairwise': Use pairwise complete observations
        """
        super().__init__(handle_missing=handle_missing)

    def _fit_impl(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate identity covariance matrix.

        Formula: Σ = σ² × I
        where σ² = mean(var(returns_i)) for all assets i

        Args:
            returns: Clean DataFrame of returns (T×N), missing data already handled

        Returns:
            Identity covariance matrix (N×N)
        """
        # Calculate individual variances for each asset
        # polars.var() returns 1-row DataFrame with variance for each column
        individual_variances = returns.var()

        # Calculate mean variance across all assets
        mean_variance = individual_variances.to_numpy().mean()

        # Number of assets
        n_assets = len(returns.columns)

        # Create identity matrix scaled by mean variance
        return np.eye(n_assets) * mean_variance

    def __repr__(self) -> str:
        return "IdentityCovariance()"
