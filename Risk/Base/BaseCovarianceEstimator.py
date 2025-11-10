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
import pandas as pd


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
    def fit(self, returns: pd.DataFrame) -> np.ndarray:
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

        Returns:
            Condition number
        """
        cov = self.get_covariance()
        return np.linalg.cond(cov)

    def _handle_missing_data(self, returns: pd.DataFrame) -> pd.DataFrame:
        """
        Handle missing data according to strategy.

        Args:
            returns: DataFrame with possible NaN values

        Returns:
            DataFrame with NaN handled
        """
        if self.handle_missing == 'drop':
            # Drop rows with any NaN
            return returns.dropna()
        elif self.handle_missing == 'pairwise':
            # Keep all data, use pairwise complete observations
            # (pandas .cov() does this by default)
            return returns
        else:
            raise ValueError(f"Unknown handle_missing: {self.handle_missing}")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(handle_missing='{self.handle_missing}')"
