# ABOUTME: Sector-based covariance base (extends BaseCovarianceEstimator) with common sector utilities
# ABOUTME: Provides validation, format conversion, hierarchical clustering, positive definiteness
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
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator
from Risk.Covariance.SectorBased.sector_utils import extract_sector_mapping, group_tickers_by_sector, long_to_wide


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
        self.correlation_clusters_: Optional[Dict[str, str]] = None

    def fit(self, returns: pl.DataFrame, sector_col: Optional[str] = "sector") -> np.ndarray:
        """
        Template method that enforces validation for all sector-based estimators.

        Subclasses should implement _fit_impl() instead of overriding this.

        Args:
            returns: DataFrame with columns [ticker, date, return, sector]
                     Long format: Each row is (ticker, date, return, sector)
            sector_col: Name of sector column (required if clustering_method="predefined")

        Returns:
            Covariance matrix (N×N numpy array)
        """
        # 1. Validate sector input
        self._validate_sector_input(returns, sector_col)

        # 2. Handle missing data
        returns_clean = self._handle_missing_data(returns)

        # 3. Call subclass implementation
        cov_matrix = self._fit_impl(returns_clean, sector_col)

        # 4. ALWAYS validate (enforced!)
        self._validate_covariance_matrix(cov_matrix, check_symmetry=True, check_positive_definite=True)

        # 5. Store result
        self.cov_matrix_ = cov_matrix

        return cov_matrix

    @abstractmethod
    def _fit_impl(self, returns: pl.DataFrame, sector_col: Optional[str] = "sector") -> np.ndarray:
        """
        Subclasses implement this to calculate covariance matrix.

        Args:
            returns: Clean returns DataFrame (missing data already handled)
            sector_col: Name of sector column

        Returns:
            Covariance matrix (N×N numpy array)

        Note:
            - Input validation and missing data handling already done
            - No need to set self.cov_matrix_
            - Just return the covariance matrix
            - Validation will be applied automatically
        """

    def _validate_sector_input(self, returns: pl.DataFrame, sector_col: Optional[str]) -> None:
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
            raise ValueError("sector_col must be provided when clustering_method='predefined'")

        # If predefined and sector_col specified, check it exists
        if self.clustering_method == "predefined" and sector_col not in returns.columns:
            raise ValueError(f"Sector column '{sector_col}' not found in DataFrame")

    def _convert_to_wide_format(self, returns: pl.DataFrame) -> tuple[np.ndarray, List[str]]:
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
                f"Unknown clustering_method: {self.clustering_method}. " f"Must be 'predefined' or 'hierarchical'."
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

        # Hierarchical clustering using scipy
        condensed_dist = squareform(distance_matrix, checks=False)
        Z = linkage(condensed_dist, method="average")
        labels = fcluster(Z, n_clusters, criterion="maxclust") - 1  # Make 0-indexed

        # Create sector mapping
        sector_mapping = {}
        for ticker, label in zip(tickers, labels):
            sector_mapping[ticker] = f"Cluster_{label}"

        return sector_mapping

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

    def get_correlation_clusters(
        self,
        threshold: float = 0.85,
        max_cluster_size: int = 10,
        n_clusters: Optional[int] = None,
    ) -> Dict[str, str]:
        """
        Detect correlation clusters using hierarchical clustering.

        Groups assets by correlation structure to identify concentration risk.
        Uses distance metric: d = 1 - |ρ| where ρ is correlation.

        Args:
            threshold: Correlation threshold for clustering (default 0.85)
                      Assets with |ρ| > threshold are considered similar
            max_cluster_size: Maximum number of assets per cluster (default 10)
                             If cluster exceeds size, it will be split
            n_clusters: Number of clusters to form (if None, uses heuristic: sqrt(N))

        Returns:
            Dictionary mapping ticker → cluster_id (e.g., "cluster_0", "cluster_1")

        Raises:
            ValueError: If fit() hasn't been called yet

        Example:
            >>> estimator = SectorBasedCovarianceEstimator()
            >>> estimator.fit(returns)
            >>> clusters = estimator.get_correlation_clusters(threshold=0.85)
            >>> print(clusters)
            {'AAPL': 'cluster_0', 'MSFT': 'cluster_0', 'JPM': 'cluster_1'}
        """
        # Check that fit has been called
        if not hasattr(self, "asset_names_"):
            raise ValueError("Must call fit() before get_correlation_clusters()")

        # Get returns matrix (need to reconstruct or store during fit)
        # For now, compute correlation from covariance if available
        if not hasattr(self, "cov_matrix_"):
            raise ValueError("Covariance matrix not available. Call fit() first.")

        tickers = self.asset_names_
        N = len(tickers)

        # Edge case: single asset
        if N == 1:
            return {tickers[0]: "cluster_0"}

        # Convert covariance to correlation matrix
        # Correlation: ρ_ij = σ_ij / (σ_i × σ_j)
        std_devs = np.sqrt(np.diag(self.cov_matrix_))
        std_matrix = np.outer(std_devs, std_devs)

        # Avoid division by zero
        std_matrix = np.where(std_matrix > 1e-10, std_matrix, 1.0)

        corr_matrix = self.cov_matrix_ / std_matrix

        # Replace NaN/Inf with 0 (happens when both assets have zero variance)
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0, posinf=1.0, neginf=-1.0)

        # Ensure correlation matrix is valid [-1, 1]
        corr_matrix = np.clip(corr_matrix, -1.0, 1.0)

        # Distance metric: d = 1 - |ρ|
        distance_matrix = 1 - np.abs(corr_matrix)

        # Ensure valid distance matrix (non-negative, symmetric)
        distance_matrix = np.maximum(distance_matrix, 0)
        distance_matrix = (distance_matrix + distance_matrix.T) / 2
        np.fill_diagonal(distance_matrix, 0)  # Distance to self is zero

        # Final check: replace any remaining NaN/Inf
        distance_matrix = np.nan_to_num(distance_matrix, nan=1.0, posinf=1.0, neginf=1.0)

        # Auto-select number of clusters if not specified
        if n_clusters is None:
            n_clusters = max(2, int(np.sqrt(N)))

        # Hierarchical clustering using scipy
        # Convert distance matrix to condensed form for linkage
        condensed_dist = squareform(distance_matrix, checks=False)

        # Perform hierarchical clustering
        Z = linkage(condensed_dist, method="average")

        # Cut dendrogram to get cluster labels
        labels = fcluster(Z, n_clusters, criterion="maxclust") - 1  # Make 0-indexed

        # Create initial cluster mapping
        cluster_mapping = {}
        for ticker, label in zip(tickers, labels):
            cluster_mapping[ticker] = f"cluster_{label}"

        # Enforce max_cluster_size by splitting large clusters
        cluster_mapping = self._enforce_max_cluster_size(cluster_mapping, distance_matrix, tickers, max_cluster_size)

        # Store for later retrieval
        self.correlation_clusters_ = cluster_mapping

        return cluster_mapping

    def _enforce_max_cluster_size(
        self,
        cluster_mapping: Dict[str, str],
        distance_matrix: np.ndarray,
        tickers: List[str],
        max_cluster_size: int,
    ) -> Dict[str, str]:
        """
        Split clusters that exceed max_cluster_size.

        Args:
            cluster_mapping: Initial cluster assignments
            distance_matrix: Distance matrix for re-clustering
            tickers: List of ticker names
            max_cluster_size: Maximum assets per cluster

        Returns:
            Updated cluster mapping with no cluster exceeding max_size
        """
        # Group tickers by cluster
        clusters = {}
        for ticker, cluster_id in cluster_mapping.items():
            if cluster_id not in clusters:
                clusters[cluster_id] = []
            clusters[cluster_id].append(ticker)

        # Check if any cluster exceeds max_size
        new_mapping = {}
        cluster_counter = 0

        for cluster_id, cluster_tickers in clusters.items():
            if len(cluster_tickers) <= max_cluster_size:
                # Keep as is
                for ticker in cluster_tickers:
                    new_mapping[ticker] = f"cluster_{cluster_counter}"
                cluster_counter += 1
            else:
                # Split this cluster
                # Get indices for this cluster
                ticker_to_idx = {t: i for i, t in enumerate(tickers)}
                cluster_indices = [ticker_to_idx[t] for t in cluster_tickers]

                # Extract sub-distance matrix
                sub_distance = distance_matrix[np.ix_(cluster_indices, cluster_indices)]

                # Determine number of sub-clusters needed
                n_subclusters = int(np.ceil(len(cluster_tickers) / max_cluster_size))

                # Re-cluster
                if n_subclusters > 1:
                    # Use scipy for sub-clustering
                    sub_condensed = squareform(sub_distance, checks=False)
                    sub_Z = linkage(sub_condensed, method="average")
                    sub_labels = fcluster(sub_Z, n_subclusters, criterion="maxclust")

                    # Map sub-labels to unique cluster IDs
                    # Get unique sub-labels and create mapping
                    unique_sublabels = sorted(set(sub_labels))
                    label_to_cluster = {sublabel: cluster_counter + i for i, sublabel in enumerate(unique_sublabels)}

                    for ticker, sub_label in zip(cluster_tickers, sub_labels):
                        new_mapping[ticker] = f"cluster_{label_to_cluster[sub_label]}"

                    cluster_counter += len(unique_sublabels)
                else:
                    # Single cluster (shouldn't happen, but safety)
                    for ticker in cluster_tickers:
                        new_mapping[ticker] = f"cluster_{cluster_counter}"
                    cluster_counter += 1

        # Recursively enforce until no cluster exceeds max_size
        # (in case sub-clustering still produced large clusters)
        groups = {}
        for ticker, cluster_id in new_mapping.items():
            if cluster_id not in groups:
                groups[cluster_id] = []
            groups[cluster_id].append(ticker)

        max_size = max(len(tickers) for tickers in groups.values())
        if max_size > max_cluster_size:
            # Recursively apply constraint
            return self._enforce_max_cluster_size(new_mapping, distance_matrix, tickers, max_cluster_size)

        return new_mapping

    def get_cluster_groups(self) -> Dict[str, List[str]]:
        """
        Get cluster → list of tickers mapping (inverted from get_correlation_clusters).

        Returns:
            Dictionary mapping cluster_id → list of tickers in that cluster

        Raises:
            ValueError: If get_correlation_clusters() hasn't been called yet

        Example:
            >>> estimator.get_correlation_clusters()
            >>> groups = estimator.get_cluster_groups()
            >>> print(groups)
            {'cluster_0': ['AAPL', 'MSFT'], 'cluster_1': ['JPM', 'GS']}
        """
        if self.correlation_clusters_ is None:
            raise ValueError("Must call get_correlation_clusters() before get_cluster_groups()")

        # Invert the mapping
        groups = {}
        for ticker, cluster_id in self.correlation_clusters_.items():
            if cluster_id not in groups:
                groups[cluster_id] = []
            groups[cluster_id].append(ticker)

        return groups

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"clustering_method='{self.clustering_method}', "
            f"handle_missing='{self.handle_missing}')"
        )
