# ABOUTME: Diagonal covariance matrix estimator (extends BaseCovarianceEstimator, zero correlation assumption)
# ABOUTME: Assumes zero correlation between assets: Σ_ij = σ_i² if i=j, else 0
"""
Diagonal Covariance Estimator

The diagonal covariance estimator assumes zero correlation between assets:
    Σ_ij = σ_i² if i=j, else 0

Properties:
- Simplest covariance estimator (variance-only)
- Always invertible (no singularity issues)
- Optimal condition number among covariance estimators
- No correlation estimation (assumes ρ_ij = 0 for i≠j)

Use Cases:
- Baseline comparison (extreme shrinkage limit)
- When correlations are unreliable or unknown
- Fast risk calculations (O(N) instead of O(N²))
- Diversification studies under independence assumption

Limitations:
- Ignores all correlations (underestimates concentrated risk)
- Portfolio variance typically underestimated
- Not suitable for highly correlated assets (e.g., STIR futures)
"""

import numpy as np
import polars as pl

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


class DiagonalCovariance(BaseCovarianceEstimator):
    """
    Diagonal covariance matrix estimator.

    Assumes zero correlation between all assets, using only
    individual asset variances.
    """

    def __init__(self, handle_missing: str = 'drop'):
        """
        Initialize diagonal covariance estimator.

        Args:
            handle_missing: How to handle missing data
                - 'drop': Drop rows with any NaN
                - 'pairwise': Use pairwise complete observations
        """
        super().__init__(handle_missing=handle_missing)

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate diagonal covariance matrix.

        Formula: Σ_ij = σ_i² if i=j, else 0

        Where σ_i² is the sample variance of asset i.

        Args:
            returns: DataFrame of returns (T×N)

        Returns:
            Diagonal covariance matrix (N×N)
        """
        # Handle missing data
        returns_clean = self._handle_missing_data(returns)

        # Store asset names
        self.asset_names_ = list(returns_clean.columns)

        # Calculate variances (diagonal elements)
        # .var() returns a single-row DataFrame with variance of each column
        variances = returns_clean.var().to_numpy()[0]

        # Create diagonal matrix
        self.cov_matrix_ = np.diag(variances)

        return self.cov_matrix_

    def __repr__(self) -> str:
        return "DiagonalCovariance()"
