# ABOUTME: Two-step covariance estimator from García-Medina (2024)
# ABOUTME: Combines hierarchical clustering with random matrix filtering
"""
Two-Step Covariance Estimator

Best performer from García-Medina et al. (2024) "Hierarchical Spectral Clustering of S&P 500".

Algorithm:
1. Step 1: Hierarchical clustering (ALCA) to discover asset groups
2. Step 2: Random matrix filtering (RMT) applied per cluster

Achieves superior diversification metrics:
- Best HHI (lowest concentration)
- Best Leverage (lowest short-selling)
- Best RDI (risk diversification index)

Reference:
- García-Medina et al. (2024): "Hierarchical Spectral Clustering of S&P 500"
- Marčenko & Pastur (1967): Random matrix theory
"""

import numpy as np
import polars as pl
from typing import Optional, Literal

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator
from Risk.Covariance.SectorBased.BlockDiagonal.HierarchicalSectorClustering import (
    HierarchicalSectorClustering,
    ClusteringResult,
)
from Risk.Covariance.SectorBased.TwoStep.RandomMatrixFilter import RandomMatrixFilter


class TwoStepCovariance(BaseCovarianceEstimator):
    """
    Two-step covariance estimator (best performer from García-Medina 2024).

    Step 1: Hierarchical clustering (ALCA)
    Step 2: Random matrix filtering (YCM/MP) per cluster

    Achieves best diversification and leverage metrics.
    """

    def __init__(
        self,
        n_clusters: Optional[int] = None,
        linkage_method: Literal["ward", "average", "complete", "weighted"] = "ward",
        rmt_filter: bool = True,
        handle_missing: str = "drop",
    ):
        """
        Initialize two-step estimator.

        Args:
            n_clusters: Number of clusters (if None, use cross-validation)
            linkage_method: Hierarchical clustering linkage method
            rmt_filter: Apply RMT filtering to each cluster (default: True)
            handle_missing: How to handle missing data
        """
        super().__init__(handle_missing=handle_missing)

        self.n_clusters = n_clusters
        self.linkage_method = linkage_method
        self.rmt_filter = rmt_filter

        # Initialize components
        self.clusterer = HierarchicalSectorClustering(
            linkage_method=linkage_method,
            n_clusters=n_clusters,
        )
        self.rmt_filter_obj = RandomMatrixFilter() if rmt_filter else None

        # Store clustering result
        self.clustering_result_: Optional[ClusteringResult] = None

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate covariance using two-step procedure.

        Args:
            returns: DataFrame with columns [ticker, date, return]
                     Long format: each row is (ticker, date, return)

        Returns:
            Covariance matrix (N×N numpy array)

        Raises:
            ValueError: If required columns missing or insufficient data
        """
        # Validate input
        self._validate_input(returns)

        # Handle missing data
        returns_clean = self._handle_missing_data(returns)

        # Convert long format to wide format
        returns_wide, tickers = self._long_to_wide(returns_clean)

        # Store asset names (sorted for consistency)
        self.asset_names_ = sorted(tickers)

        # Get dimensions
        T, N = returns_wide.shape

        # Validate sufficient observations
        if T < 10:
            raise ValueError(
                f"Insufficient observations: T={T}. Need at least 10 observations."
            )

        # Convert to numpy array
        returns_np = returns_wide.to_numpy()

        # Step 1: Hierarchical clustering
        self.clustering_result_ = self.clusterer.fit(returns_np, tickers)

        # Get cluster assignments
        cluster_assignments = self.clustering_result_.cluster_assignments

        # Step 2: Estimate covariance per cluster with RMT filtering
        cov_matrix = self._estimate_clustered_covariance(
            returns_np, tickers, cluster_assignments, T
        )

        # Store result
        self.cov_matrix_ = cov_matrix

        return self.cov_matrix_

    def _validate_input(self, returns: pl.DataFrame) -> None:
        """
        Validate input DataFrame.

        Args:
            returns: DataFrame to validate

        Raises:
            ValueError: If required columns missing
        """
        required_cols = ["ticker", "date", "return"]
        missing = [col for col in required_cols if col not in returns.columns]

        if missing:
            raise ValueError(f"Missing required columns: {missing}")

    def _long_to_wide(self, returns: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
        """
        Convert long format DataFrame to wide format.

        Args:
            returns: Long format DataFrame [ticker, date, return]

        Returns:
            Tuple of (wide_df, tickers)
            - wide_df: T×N DataFrame with dates as rows, tickers as columns
            - tickers: List of ticker names
        """
        # Pivot to wide format
        wide = returns.pivot(
            index="date",
            columns="ticker",
            values="return",
        ).sort("date")

        # Get ticker names (all columns except 'date')
        tickers = [col for col in wide.columns if col != "date"]

        # Drop date column for covariance calculation
        wide_returns = wide.select(tickers)

        return wide_returns, tickers

    def _estimate_clustered_covariance(
        self,
        returns: np.ndarray,  # T×N
        tickers: list[str],
        cluster_assignments: dict[str, int],
        n_observations: int,
    ) -> np.ndarray:
        """
        Estimate covariance matrix with per-cluster RMT filtering.

        Args:
            returns: T×N returns matrix
            tickers: List of N ticker symbols
            cluster_assignments: Dictionary mapping ticker → cluster_id
            n_observations: Number of time observations (T)

        Returns:
            N×N covariance matrix
        """
        N = len(tickers)

        # Calculate full sample covariance
        sample_cov = np.cov(returns.T)

        # If no RMT filtering, return sample covariance
        if not self.rmt_filter:
            return sample_cov

        # Group tickers by cluster
        clusters = {}
        for ticker, cluster_id in cluster_assignments.items():
            if cluster_id not in clusters:
                clusters[cluster_id] = []
            clusters[cluster_id].append(ticker)

        # Create ticker → index mapping
        ticker_to_idx = {ticker: i for i, ticker in enumerate(tickers)}

        # Initialize cleaned covariance
        cleaned_cov = np.zeros_like(sample_cov)

        # Process each cluster separately
        for cluster_id, cluster_tickers in clusters.items():
            # Get indices for this cluster
            cluster_indices = [ticker_to_idx[t] for t in cluster_tickers]
            cluster_size = len(cluster_indices)

            if cluster_size == 1:
                # Single asset cluster: just copy variance
                idx = cluster_indices[0]
                cleaned_cov[idx, idx] = sample_cov[idx, idx]
                continue

            # Extract sub-covariance matrix for this cluster
            sub_cov = sample_cov[np.ix_(cluster_indices, cluster_indices)]

            # Apply RMT filtering to this cluster
            cleaned_sub_cov = self.rmt_filter_obj.clean_covariance(
                sub_cov, n_observations
            )

            # Place cleaned sub-covariance back into full matrix
            for i, idx_i in enumerate(cluster_indices):
                for j, idx_j in enumerate(cluster_indices):
                    cleaned_cov[idx_i, idx_j] = cleaned_sub_cov[i, j]

        # For off-diagonal blocks (between clusters), use sample covariance
        # This preserves cross-cluster correlations while cleaning within-cluster structure
        for i in range(N):
            ticker_i = tickers[i]
            cluster_i = cluster_assignments[ticker_i]

            for j in range(N):
                ticker_j = tickers[j]
                cluster_j = cluster_assignments[ticker_j]

                # If different clusters, use sample covariance
                if cluster_i != cluster_j:
                    cleaned_cov[i, j] = sample_cov[i, j]

        # Ensure symmetry (numerical stability)
        cleaned_cov = (cleaned_cov + cleaned_cov.T) / 2

        return cleaned_cov

    def get_clustering_result(self) -> ClusteringResult:
        """
        Get the clustering result from hierarchical clustering.

        Returns:
            ClusteringResult with cluster assignments and quality metrics

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        if self.clustering_result_ is None:
            raise ValueError("Must call fit() before get_clustering_result()")
        return self.clustering_result_

    def __repr__(self) -> str:
        return (
            f"TwoStepCovariance("
            f"n_clusters={self.n_clusters}, "
            f"linkage_method='{self.linkage_method}', "
            f"rmt_filter={self.rmt_filter})"
        )
