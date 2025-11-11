# ABOUTME: Constant correlation covariance matrix estimator (equal correlation shrinkage target)
# ABOUTME: Assumes all pairwise correlations equal: Σ = D(ρ11' + (1-ρ)I)D where ρ is mean correlation
"""
Constant Correlation Covariance Estimator

The constant correlation model assumes all pairwise correlations are equal:
    Σ = D × (ρ × 11' + (1-ρ) × I) × D

where:
- D = diag(σ_1, ..., σ_n) is diagonal matrix of standard deviations
- ρ = mean pairwise correlation from returns
- 11' is matrix of ones (n×n)
- I = identity matrix

Properties:
- Preserves individual asset variances (diagonal elements)
- All off-diagonal correlations are equal (constant)
- Always positive definite when -1/(n-1) < ρ < 1
- Used as shrinkage target in Ledoit-Wolf methods

Use Cases:
- Shrinkage target for covariance estimation
- Simple model when assuming uniform correlation structure
- Reduces dimensionality from O(n²) to O(n) parameters
- Better conditioned than sample covariance

From Ledoit & Wolf (2003, 2004): "Improved Estimation of the Covariance Matrix"
"""

import numpy as np
import polars as pl

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


class ConstantCorrelationCovariance(BaseCovarianceEstimator):
    """
    Constant correlation covariance matrix estimator.

    This estimator assumes all pairwise correlations are equal and
    is commonly used as a shrinkage target in covariance estimation.
    """

    def __init__(self, handle_missing: str = 'drop'):
        """
        Initialize constant correlation covariance estimator.

        Args:
            handle_missing: How to handle missing data
                - 'drop': Drop rows with any NaN
                - 'pairwise': Use pairwise complete observations
        """
        super().__init__(handle_missing=handle_missing)
        self.mean_correlation_: float = None

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate constant correlation covariance matrix.

        Formula: Σ = D × (ρ × 11' + (1-ρ) × I) × D

        where:
        - D = diag(σ_1, ..., σ_n) from sample standard deviations
        - ρ = mean pairwise correlation from sample correlation matrix
        - 11' = matrix of ones (all elements = 1)
        - I = identity matrix

        Args:
            returns: DataFrame of returns (T×N)

        Returns:
            Constant correlation covariance matrix (N×N)
        """
        # Handle missing data
        returns_clean = self._handle_missing_data(returns)

        # Store asset names
        self.asset_names_ = list(returns_clean.columns)

        # Get sample covariance and correlation
        # Convert to numpy for covariance calculation (polars lacks .cov() method)
        returns_array = returns_clean.to_numpy()
        sample_cov = np.cov(returns_array.T)

        # Ensure 2D array (np.cov returns scalar for single asset)
        if sample_cov.ndim == 0:
            sample_cov = np.array([[sample_cov]])
        elif sample_cov.ndim == 1:
            sample_cov = np.array([sample_cov])

        sample_std = np.sqrt(np.diag(sample_cov))

        # Handle single asset case
        n = len(sample_std)
        if n == 1:
            self.mean_correlation_ = 1.0
            self.cov_matrix_ = sample_cov
            return self.cov_matrix_

        # Calculate correlation matrix
        sample_corr = sample_cov / np.outer(sample_std, sample_std)

        # Calculate mean off-diagonal correlation
        # Extract upper triangle (excluding diagonal)
        off_diag_sum = 0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                off_diag_sum += sample_corr[i, j]
                count += 1

        self.mean_correlation_ = off_diag_sum / count if count > 0 else 0.0

        # Build constant correlation matrix
        # Correlation: ρ × 11' + (1-ρ) × I
        rho = self.mean_correlation_
        ones_matrix = np.ones((n, n))
        I = np.eye(n)

        corr_matrix = rho * ones_matrix + (1 - rho) * I

        # Convert to covariance: Σ = D × Corr × D
        D = np.diag(sample_std)
        self.cov_matrix_ = D @ corr_matrix @ D

        return self.cov_matrix_

    def get_mean_correlation(self) -> float:
        """
        Get the mean correlation used in the constant correlation model.

        Returns:
            Mean pairwise correlation ρ

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        if self.mean_correlation_ is None:
            raise ValueError("Must call fit() before get_mean_correlation()")
        return self.mean_correlation_

    def __repr__(self) -> str:
        if self.mean_correlation_ is not None:
            return f"ConstantCorrelationCovariance(ρ={self.mean_correlation_:.4f})"
        return "ConstantCorrelationCovariance()"
