# ABOUTME: Abstract base class for sector-based covariance estimators
# ABOUTME: Provides common functionality for block-diagonal and clustered covariance models
"""
SectorBasedCovarianceEstimator

Abstract base class for covariance estimators that exploit sector/cluster structure.

All sector-based models share:
- Data validation for long format with sector column
- Conversion from long to wide format
- Sector assignment (predefined or discovered via clustering)
- Positive definiteness enforcement

Implementations:
- BlockDiagonalCovariance (Žignić et al. 2024)
- TwoStepCovariance (García-Medina et al. 2024)
- StochasticBlockCovariance (Chen et al. 2025)
"""

from abc import abstractmethod
from typing import Dict, List, Literal, Optional
import numpy as np
import polars as pl
from sklearn.cluster import AgglomerativeClustering

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator
from Risk.Covariance.SectorBased.sector_utils import (
    long_to_wide,
    extract_sector_mapping,
    group_tickers_by_sector,
)


class SectorBasedCovarianceEstimator(BaseCovarianceEstimator):
    """
    Abstract base class for sector-based covariance estimators.

    Provides common functionality for models that exploit sector/cluster structure:
    - Data validation
    - Format conversion (long → wide)
    - Sector assignment (predefined or hierarchical clustering)
    - Positive definiteness enforcement
    """

    def __init__(
        self,
        clustering_method: Literal["predefined", "hierarchical"] = "predefined",
        handle_missing: str = "drop",
    ):
        """
        Initialize sector-based covariance estimator.

        Args:
            clustering_method: How to determine sectors
                - "predefined": Use sector column from input data
                - "hierarchical": Discover via clustering
            handle_missing: How to handle missing data ('drop' or 'pairwise')
        """
        super().__init__(handle_missing=handle_missing)
        self.clustering_method = clustering_method
        self.sector_mapping_: Optional[Dict[str, str]] = None

    @abstractmethod
    def fit(
        self, returns: pl.DataFrame, sector_col: Optional[str] = "sector"
    ) -> np.ndarray:
        """
        Estimate covariance matrix from returns.

        Args:
            returns: DataFrame with columns [ticker, date, return, sector]
                     Long format: Each row is (ticker, date, return, sector)
            sector_col: Name of sector column (required if clustering_method="predefined")

        Returns:
            Covariance matrix (N×N numpy array)
        """
        pass

    def _validate_sector_input(
        self, returns: pl.DataFrame, sector_col: Optional[str]
    ) -> None:
        """
        Validate input data for sector-based models.

        Args:
            returns: DataFrame to validate
            sector_col: Expected sector column name

        Raises:
            ValueError: If required columns missing or data invalid
        """
        # Check required columns
        required_cols = ["ticker", "date", "return"]
        missing = [col for col in required_cols if col not in returns.columns]

        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # If predefined clustering, sector_col is required
        if self.clustering_method == "predefined" and sector_col is None:
            raise ValueError(
                "sector_col must be provided when clustering_method='predefined'"
            )

        # If predefined and sector_col specified, check it exists
        if self.clustering_method == "predefined" and sector_col not in returns.columns:
            raise ValueError(f"Sector column '{sector_col}' not found in DataFrame")

    def _convert_to_wide_format(
        self, returns: pl.DataFrame
    ) -> tuple[np.ndarray, List[str]]:
        """
        Convert long format DataFrame to wide format matrix.

        Args:
            returns: Long format DataFrame with [ticker, date, return]

        Returns:
            Tuple of (returns_matrix, tickers)
            - returns_matrix: T×N numpy array
            - tickers: List of N ticker names
        """
        returns_wide, tickers = long_to_wide(returns, pivot_col="ticker", value_col="return")

        # Convert to numpy array
        returns_matrix = returns_wide.to_numpy()

        return returns_matrix, tickers

    def _determine_sector_assignments(
        self,
        returns_wide: np.ndarray,
        tickers: List[str],
        returns_long: pl.DataFrame,
        sector_col: Optional[str],
    ) -> Dict[str, str]:
        """
        Determine sector assignments (predefined or discovered).

        Args:
            returns_wide: T×N returns matrix
            tickers: List of ticker names
            returns_long: Original long format DataFrame
            sector_col: Sector column name (if predefined)

        Returns:
            Dictionary mapping ticker → sector/cluster name
        """
        if self.clustering_method == "predefined":
            # Extract from data
            return extract_sector_mapping(returns_long, sector_col=sector_col)

        elif self.clustering_method == "hierarchical":
            # Discover via clustering
            return self._discover_sectors_hierarchical(returns_wide, tickers)

        else:
            raise ValueError(
                f"Unknown clustering_method: {self.clustering_method}. "
                f"Must be 'predefined' or 'hierarchical'."
            )

    def _discover_sectors_hierarchical(
        self, returns: np.ndarray, tickers: List[str], n_clusters: Optional[int] = None
    ) -> Dict[str, str]:
        """
        Discover sector structure via hierarchical clustering.

        Args:
            returns: T×N returns matrix
            tickers: List of ticker names
            n_clusters: Number of clusters (if None, use heuristic)

        Returns:
            Dictionary mapping ticker → cluster name
        """
        N = len(tickers)

        # Compute correlation matrix
        corr_matrix = np.corrcoef(returns, rowvar=False)

        # Convert to distance: d = 1 - |ρ|
        distance_matrix = 1 - np.abs(corr_matrix)

        # Ensure valid distance matrix
        distance_matrix = np.maximum(distance_matrix, 0)
        distance_matrix = (distance_matrix + distance_matrix.T) / 2

        # Auto-select number of clusters if not specified
        if n_clusters is None:
            n_clusters = max(2, int(np.sqrt(N)))

        # Hierarchical clustering
        clustering = AgglomerativeClustering(
            n_clusters=n_clusters, metric="precomputed", linkage="average"
        )

        labels = clustering.fit_predict(distance_matrix)

        # Create sector mapping
        sector_mapping = {}
        for ticker, label in zip(tickers, labels):
            sector_mapping[ticker] = f"Cluster_{label}"

        return sector_mapping

    def _ensure_positive_definite(
        self, cov_matrix: np.ndarray, min_eigenvalue: float = 1e-8
    ) -> np.ndarray:
        """
        Ensure covariance matrix is positive definite.

        Uses eigenvalue clipping: λᵢ → max(λᵢ, ε)

        Args:
            cov_matrix: Potentially singular covariance matrix
            min_eigenvalue: Minimum eigenvalue threshold

        Returns:
            Positive definite covariance matrix
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

    def get_sector_mapping(self) -> Dict[str, str]:
        """
        Get ticker → sector mapping after fitting.

        Returns:
            Dictionary mapping ticker → sector/cluster name

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        if self.sector_mapping_ is None:
            raise ValueError("Must call fit() before get_sector_mapping()")
        return self.sector_mapping_

    def get_sector_groups(self) -> Dict[str, List[str]]:
        """
        Get sector → list of tickers mapping.

        Returns:
            Dictionary mapping sector → list of tickers in that sector

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        sector_mapping = self.get_sector_mapping()
        return group_tickers_by_sector(sector_mapping)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"clustering_method='{self.clustering_method}', "
            f"handle_missing='{self.handle_missing}')"
        )
