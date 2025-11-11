# ABOUTME: Oracle Approximating Shrinkage covariance estimator from sklearn
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

import numpy as np
import polars as pl
from typing import Optional

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
        handle_missing: str = 'drop',
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
            raise ImportError(
                "sklearn is required for OAShrinkage. "
                "Install with: pip install scikit-learn"
            )

        super().__init__(handle_missing=handle_missing)
        self.store_precision = store_precision
        self.shrinkage_coefficient: Optional[float] = None
        self.sample_cov: Optional[np.ndarray] = None
        self._estimator: Optional[OAS] = None

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate OAS covariance matrix.

        Args:
            returns: DataFrame of returns (T×N)
                - Rows: time periods
                - Columns: assets
                - Values: returns (decimal, e.g., 0.01 for 1%)

        Returns:
            OAS covariance matrix (N×N)
        """
        # 1. Handle missing data
        returns_clean = self._handle_missing_data(returns)

        # 2. Store metadata
        self.asset_names_ = list(returns_clean.columns)
        T, N = returns_clean.shape

        # 3. Convert to numpy
        returns_array = returns_clean.to_numpy()

        # 4. Call sklearn OAS
        self._estimator = OAS(store_precision=self.store_precision)
        self._estimator.fit(returns_array)

        # 5. Extract results
        self.cov_matrix_ = self._estimator.covariance_
        self.shrinkage_coefficient = self._estimator.shrinkage_

        # 6. Calculate sample covariance for reference
        self.sample_cov = np.cov(returns_array, rowvar=False, ddof=1)

        # 7. Validate output
        self._validate_covariance_matrix(self.cov_matrix_)

        return self.cov_matrix_

    def _validate_covariance_matrix(self, cov_matrix: np.ndarray, tol: float = 1e-10):
        """
        Validate covariance matrix properties.

        Checks that the matrix is:
        1. Square (N×N)
        2. Symmetric (Σ = Σᵀ)
        3. Positive semi-definite (all eigenvalues ≥ 0)

        Args:
            cov_matrix: Covariance matrix to validate
            tol: Tolerance for symmetry and eigenvalue checks

        Raises:
            ValueError: If validation fails
        """
        # Check square
        if cov_matrix.ndim != 2 or cov_matrix.shape[0] != cov_matrix.shape[1]:
            raise ValueError(
                f"Covariance matrix must be square, got shape {cov_matrix.shape}"
            )

        # Check symmetric
        if not np.allclose(cov_matrix, cov_matrix.T, atol=tol):
            max_diff = np.max(np.abs(cov_matrix - cov_matrix.T))
            raise ValueError(
                f"Covariance matrix must be symmetric. Max asymmetry: {max_diff:.2e}"
            )

        # Check positive semi-definite
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        min_eigenvalue = np.min(eigenvalues)
        if min_eigenvalue < -tol:
            raise ValueError(
                f"Covariance matrix must be positive semi-definite. "
                f"Minimum eigenvalue: {min_eigenvalue:.2e}"
            )

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
