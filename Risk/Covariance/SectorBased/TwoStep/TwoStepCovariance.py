# ABOUTME: Two-step covariance (extends SectorBasedCovarianceEstimator) with RMT filtering
# ABOUTME: Hierarchical clustering (Step 1) + random matrix filtering per cluster (Step 2)
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

from typing import Literal, Optional

import numpy as np
import polars as pl

from Risk.Covariance.SectorBased.BaseSectorCovarianceEstimator import SectorBasedCovarianceEstimator
from Risk.Covariance.SectorBased.BlockDiagonal.HierarchicalSectorClustering import (
    ClusteringResult,
    HierarchicalSectorClustering,
)
from Risk.Covariance.SectorBased.TwoStep.RandomMatrixFilter import RandomMatrixFilter


class TwoStepCovariance(SectorBasedCovarianceEstimator):
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
        # TwoStep always uses hierarchical clustering
        super().__init__(clustering_method="hierarchical", handle_missing=handle_missing)

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

    def _fit_impl(self, returns: pl.DataFrame, sector_col: Optional[str] = None) -> np.ndarray:
        """
        Estimate covariance using two-step procedure.

        Args:
            returns: Clean DataFrame with columns [ticker, date, return]
                     Missing data already handled
            sector_col: Ignored (TwoStep always uses hierarchical clustering)

        Returns:
            Covariance matrix (N×N numpy array)

        Raises:
            ValueError: If insufficient data
        """
        # Convert to wide format
        returns_np, tickers = self._convert_to_wide_format(returns)
        # Sort tickers for consistency with original implementation
        self.asset_names_ = sorted(tickers)

        # Get dimensions
        T, N = returns_np.shape

        # Validate sufficient observations
        if T < 10:
            raise ValueError(f"Insufficient observations: T={T}. Need at least 10 observations.")

        # Step 1: Hierarchical clustering
        self.clustering_result_ = self.clusterer.fit(returns_np, tickers)

        # Get cluster assignments and store in sector_mapping_
        self.sector_mapping_ = self.clustering_result_.cluster_assignments

        # Step 2: Estimate covariance per cluster with RMT filtering
        return self._estimate_clustered_covariance(returns_np, tickers, self.sector_mapping_, T)

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
            cleaned_sub_cov = self.rmt_filter_obj.clean_covariance(sub_cov, n_observations)

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
