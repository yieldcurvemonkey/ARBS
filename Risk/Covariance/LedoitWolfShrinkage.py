# ABOUTME: Ledoit-Wolf shrinkage covariance estimator (wraps sklearn.covariance.LedoitWolf)
# ABOUTME: Industry standard shrinkage with >5000 citations, data-driven optimal intensity
"""
Ledoit-Wolf Shrinkage Covariance Estimator

Wraps sklearn's LedoitWolf implementation of the Ledoit & Wolf (2004)
"Honey, I Shrunk the Sample Covariance Matrix" shrinkage estimator.

Formula:
    Σ̂_LW = δ * F + (1-δ) * S

Where:
- S = sample covariance matrix (MLE: divides by n)
- F = target matrix (constant correlation structure)
- δ = shrinkage intensity (data-driven, optimal)

Optimal Shrinkage Intensity:
    δ* = max(0, min(1, κ̂/T))

Where κ̂ estimates the loss from using sample covariance.

Advantages over Sample Covariance:
1. Reduced estimation error (especially when T ≈ N)
2. Better conditioned (lower condition number)
3. Always invertible (positive definite)
4. Better out-of-sample portfolio variance

From 2025 research: Most widely used shrinkage method in practice.

Reference:
    Ledoit, O., & Wolf, M. (2004). "Honey, I Shrunk the Sample Covariance Matrix"
    Journal of Portfolio Management, 30(4), 110-119.
    >5000 citations
"""

from typing import Optional

import numpy as np
import polars as pl
from sklearn.covariance import LedoitWolf as SklearnLedoitWolf

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


class LedoitWolfShrinkage(BaseCovarianceEstimator):
    """
    Ledoit-Wolf shrinkage estimator (wraps sklearn).

    Shrinks sample covariance toward constant correlation target,
    with data-driven shrinkage intensity.

    Attributes:
        shrinkage_intensity (float): Optimal δ ∈ [0, 1]
        sklearn_estimator: Underlying sklearn LedoitWolf estimator
    """

    def __init__(
        self,
        target: str = "constant_correlation",  # Only supports constant_correlation via sklearn
        handle_missing: str = "drop",
    ):
        """
        Initialize Ledoit-Wolf estimator.

        Args:
            target: Shrinkage target type (only 'constant_correlation' supported)
                Note: sklearn only supports constant correlation target
            handle_missing: How to handle missing data
                - 'drop': Drop rows with any NaN values (default)
                - 'pairwise': Use pairwise complete observations
                  (handled by BaseCovarianceEstimator)
        """
        super().__init__(handle_missing=handle_missing)
        if target != "constant_correlation":
            raise ValueError(
                f"Only 'constant_correlation' target is supported (sklearn limitation). "
                f"Got: {target}"
            )
        self.target_type = target
        self.shrinkage_intensity: Optional[float] = None
        self.sklearn_estimator: Optional[SklearnLedoitWolf] = None
        self.target_matrix: Optional[np.ndarray] = None
        self.sample_cov: Optional[np.ndarray] = None

    def _fit_impl(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Fit Ledoit-Wolf estimator using sklearn.

        Args:
            returns: DataFrame of returns (T×N), already cleaned by base class

        Returns:
            Shrinkage covariance matrix (N×N)
        """
        # Convert to numpy
        returns_np = returns.to_numpy()

        # Calculate sample covariance (MLE: divide by n, not n-1)
        n = returns_np.shape[0]
        returns_centered = returns_np - np.mean(returns_np, axis=0)
        self.sample_cov = (returns_centered.T @ returns_centered) / n

        # Use sklearn's LedoitWolf
        self.sklearn_estimator = SklearnLedoitWolf(
            store_precision=False,  # We don't need precision matrix
            assume_centered=False,  # Returns are not centered
            block_size=1000,  # Default block size for large N
        )

        # Fit and get covariance
        self.sklearn_estimator.fit(returns_np)
        cov_matrix = self.sklearn_estimator.covariance_

        # Store shrinkage intensity
        self.shrinkage_intensity = self.sklearn_estimator.shrinkage_

        # Compute target matrix: Σ̂_LW = δ * F + (1-δ) * S
        # Solve for F: F = (Σ̂_LW - (1-δ)*S) / δ
        if self.shrinkage_intensity > 1e-10:
            self.target_matrix = (cov_matrix - (1 - self.shrinkage_intensity) * self.sample_cov) / self.shrinkage_intensity
        else:
            # No shrinkage case: target doesn't matter
            self.target_matrix = self.sample_cov.copy()

        return cov_matrix

    def get_shrinkage_intensity(self) -> float:
        """
        Get the optimal shrinkage intensity.

        Returns:
            δ* ∈ [0, 1]

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        if self.shrinkage_intensity is None:
            raise ValueError("Must call fit() before get_shrinkage_intensity()")
        return self.shrinkage_intensity

    def __repr__(self) -> str:
        """Return string representation."""
        return f"LedoitWolfShrinkage(handle_missing='{self.handle_missing}')"
