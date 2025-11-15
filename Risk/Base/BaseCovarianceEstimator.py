# ABOUTME: Abstract base class for all covariance matrix estimators
# ABOUTME: Defines standard interface for fit(), get_covariance(), condition_number(), and missing data handling
"""
BaseCovarianceEstimator - Abstract base class for covariance estimation

All covariance estimators should inherit from this class and implement
the fit() method to estimate the covariance matrix from returns data.

Output format:
- numpy array (N×N) where N is number of assets
- Symmetric positive semi-definite
- Suitable for portfolio optimization (matrix inversion)
"""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np
import polars as pl


class BaseCovarianceEstimator(ABC):
    """
    Abstract base class for covariance matrix estimation.

    All estimators must implement fit() which takes a DataFrame of returns
    and produces an N×N covariance matrix.
    """

    def __init__(self, handle_missing: str = 'drop'):
        """
        Initialize covariance estimator.

        Args:
            handle_missing: How to handle missing data
                - 'drop': Drop rows with any NaN
                - 'pairwise': Use pairwise complete observations
        """
        self.handle_missing = handle_missing
        self.cov_matrix_: Optional[np.ndarray] = None
        self.asset_names_: Optional[list] = None

    @abstractmethod
    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate covariance matrix from returns.

        Args:
            returns: DataFrame of returns (T×N)
                - Rows: time periods
                - Columns: assets
                - Values: returns (decimal, e.g., 0.01 for 1%)

        Returns:
            Covariance matrix (N×N numpy array)
        """
        pass

    def get_covariance(self) -> np.ndarray:
        """
        Get the fitted covariance matrix.

        Returns:
            Covariance matrix (N×N)

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        if self.cov_matrix_ is None:
            raise ValueError("Must call fit() before get_covariance()")
        return self.cov_matrix_

    def get_correlation(self) -> np.ndarray:
        """
        Get correlation matrix from fitted covariance.

        Returns:
            Correlation matrix (N×N)
        """
        cov = self.get_covariance()

        # Extract standard deviations (diagonal)
        std = np.sqrt(np.diag(cov))

        # Correlation = cov / (std_i * std_j)
        corr = cov / np.outer(std, std)

        return corr

    def get_precision(self) -> np.ndarray:
        """
        Get precision matrix (inverse covariance).

        From 2025 research: Precision matrix (Σ^-1) is preferred
        for portfolio optimization (nodewise regression).

        Returns:
            Precision matrix (N×N)
        """
        cov = self.get_covariance()
        return np.linalg.inv(cov)

    def condition_number(self) -> float:
        """
        Calculate condition number of covariance matrix.

        Condition number measures matrix stability:
        - κ < 100: Well-conditioned (good)
        - κ > 1000: Ill-conditioned (risky for inversion)
        - κ = inf: Singular matrix (not invertible)

        Returns:
            Condition number (κ = σ_max / σ_min)
            Returns np.inf for singular matrices
        """
        cov = self.get_covariance()
        return np.linalg.cond(cov)

    def _validate_covariance_matrix(
        self,
        cov_matrix: np.ndarray,
        tol: float = 1e-10,
        check_symmetry: bool = True,
        check_positive_definite: bool = True
    ) -> None:
        """
        Validate covariance matrix mathematical properties.

        Checks:
        1. Square matrix (N×N)
        2. Symmetric (Σ = Σᵀ)
        3. Positive semi-definite (all eigenvalues ≥ 0)

        Args:
            cov_matrix: Covariance matrix to validate
            tol: Tolerance for numerical checks
            check_symmetry: Whether to check matrix symmetry
            check_positive_definite: Whether to check positive definiteness

        Raises:
            ValueError: If validation fails
        """
        # Check square
        if cov_matrix.ndim != 2 or cov_matrix.shape[0] != cov_matrix.shape[1]:
            raise ValueError(
                f"Covariance matrix must be square, got shape {cov_matrix.shape}"
            )

        # Check symmetric
        if check_symmetry:
            if not np.allclose(cov_matrix, cov_matrix.T, atol=tol):
                max_diff = np.max(np.abs(cov_matrix - cov_matrix.T))
                raise ValueError(
                    f"Covariance matrix must be symmetric. Max asymmetry: {max_diff:.2e}"
                )

        # Check positive semi-definite
        if check_positive_definite:
            eigenvalues = np.linalg.eigvalsh(cov_matrix)
            min_eigenvalue = np.min(eigenvalues)
            if min_eigenvalue < -tol:
                raise ValueError(
                    f"Covariance matrix must be positive semi-definite. "
                    f"Minimum eigenvalue: {min_eigenvalue:.2e}"
                )

    def _ensure_positive_definite(
        self,
        cov_matrix: np.ndarray,
        min_eigenvalue: float = 1e-8
    ) -> np.ndarray:
        """
        Ensure covariance matrix is positive definite via eigenvalue clipping.

        Method: Eigenvalue decomposition + clipping + reconstruction
        Formula: Σ_pd = V @ diag(max(λ, ε)) @ V^T

        Args:
            cov_matrix: Potentially singular covariance matrix
            min_eigenvalue: Minimum eigenvalue threshold (default: 1e-8)

        Returns:
            Positive definite covariance matrix

        Note:
            Also ensures symmetry via (Σ + Σᵀ)/2 for numerical stability
        """
        # Eigenvalue decomposition
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)

        # Clip negative/small eigenvalues
        eigenvalues = np.maximum(eigenvalues, min_eigenvalue)

        # Reconstruct
        cov_pd = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

        # Ensure symmetry (numerical stability)
        cov_pd = (cov_pd + cov_pd.T) / 2

        return cov_pd

    def _handle_missing_data(self, returns: pl.DataFrame) -> pl.DataFrame:
        """
        Handle missing data according to strategy.

        Args:
            returns: DataFrame with possible NaN values (from numpy arrays)

        Returns:
            DataFrame with NaN handled
        """
        # Convert NaN to null (polars doesn't recognize numpy NaN as null)
        # Replace NaN with None in each column
        for col in returns.columns:
            if returns[col].dtype in [pl.Float64, pl.Float32]:
                returns = returns.with_columns(
                    pl.when(pl.col(col).is_nan()).then(None).otherwise(pl.col(col)).alias(col)
                )

        if self.handle_missing == 'drop':
            # Drop rows with any null
            return returns.drop_nulls()
        elif self.handle_missing == 'pairwise':
            # Keep all data, use pairwise complete observations
            return returns
        else:
            raise ValueError(f"Unknown handle_missing: {self.handle_missing}")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(handle_missing='{self.handle_missing}')"
