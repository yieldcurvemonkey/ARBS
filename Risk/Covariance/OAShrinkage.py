# ABOUTME: Oracle Approximating Shrinkage covariance estimator (extends BaseCovarianceEstimator) from sklearn
# ABOUTME: Implements Chen et al. (2010) OAS for small sample sizes with optimal shrinkage intensity
"""
OAS (Oracle Approximating Shrinkage) Covariance Estimator

Implements the OAS estimator from Chen et al. (2010) which provides
better shrinkage intensity estimation than Ledoit-Wolf when sample
size is small relative to the number of assets.

Formula:
    Σ̂_OAS = (1-ρ) * S + ρ * (tr(S)/N) * I

Where:
- S = sample covariance matrix
- ρ = OAS shrinkage coefficient (data-driven)
- tr(S) = trace of sample covariance
- N = number of assets
- I = identity matrix

Optimal Shrinkage Coefficient:
    ρ* is computed using the Oracle Approximating Shrinkage formula
    which better approximates the oracle shrinkage than Ledoit-Wolf
    for small T/N ratios.

Advantages:
1. Better than Ledoit-Wolf when T/N is small (< 5)
2. Data-driven shrinkage intensity (no hyperparameters)
3. Computationally efficient (uses sklearn)
4. Always invertible and well-conditioned

Reference:
    Chen, Y., Wiesel, A., Eldar, Y. C., & Hero, A. O. (2010).
    "Shrinkage algorithms for MMSE covariance estimation."
    IEEE Transactions on Signal Processing, 58(10), 5016-5029.
    DOI: 10.1109/TSP.2010.2053029

From 2025 research: OAS is recommended over Ledoit-Wolf for portfolios
with fewer than 5× observations vs assets (T/N < 5).
"""

from typing import Optional

import numpy as np
import polars as pl

try:
    from sklearn.covariance import OAS

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


class OAShrinkage(BaseCovarianceEstimator):
    """
    Oracle Approximating Shrinkage covariance estimator.

    Wraps sklearn.covariance.OAS which implements Chen et al. (2010).
    Provides better shrinkage than Ledoit-Wolf for small samples.

    Attributes:
        shrinkage_coefficient (float): Optimal ρ ∈ [0, 1]
        sample_cov (np.ndarray): Sample covariance S before shrinkage
    """

    def __init__(
        self,
        store_precision: bool = False,
        handle_missing: str = "drop",
    ):
        """
        Initialize OAS estimator.

        Args:
            store_precision: Whether to compute precision matrix during fit
            handle_missing: How to handle missing data ('drop' or 'pairwise')

        Raises:
            ImportError: If sklearn is not installed
        """
        if not SKLEARN_AVAILABLE:
            raise ImportError("sklearn is required for OAShrinkage. " "Install with: pip install scikit-learn")

        super().__init__(handle_missing=handle_missing)
        self.store_precision = store_precision
        self.shrinkage_coefficient: Optional[float] = None
        self.sample_cov: Optional[np.ndarray] = None
        self._estimator: Optional[OAS] = None

    def _fit_impl(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate OAS covariance matrix.

        Args:
            returns: Clean DataFrame of returns (T×N), missing data already handled

        Returns:
            OAS covariance matrix (N×N)
        """
        # Convert to numpy
        returns_array = returns.to_numpy()

        # Call sklearn OAS
        self._estimator = OAS(store_precision=self.store_precision)
        self._estimator.fit(returns_array)

        # Extract results
        self.shrinkage_coefficient = self._estimator.shrinkage_

        # Calculate sample covariance for reference
        sample_cov = np.cov(returns_array, rowvar=False, ddof=1)
        # Ensure covariance is always 2D (np.cov returns scalar for single column)
        self.sample_cov = np.atleast_2d(sample_cov)

        return self._estimator.covariance_

    def get_shrinkage_coefficient(self) -> float:
        """
        Get the OAS shrinkage coefficient ρ.

        Returns:
            ρ ∈ [0, 1]

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        if self.shrinkage_coefficient is None:
            raise ValueError("Must call fit() before get_shrinkage_coefficient()")
        return self.shrinkage_coefficient

    def get_precision(self) -> np.ndarray:
        """
        Get precision matrix (inverse covariance).

        If store_precision=True was set, returns the stored precision.
        Otherwise computes it from covariance.

        Returns:
            Precision matrix (N×N)
        """
        if self.store_precision and self._estimator is not None:
            return self._estimator.precision_
        else:
            return super().get_precision()

    def __repr__(self) -> str:
        if self.shrinkage_coefficient is not None:
            return f"OAShrinkage(ρ={self.shrinkage_coefficient:.4f})"
        else:
            return "OAShrinkage(not fitted)"
