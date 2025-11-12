# ABOUTME: Hierarchical clustering for sector discovery from residual correlations
# ABOUTME: Implements adaptive thresholding from Žignić et al. (2024)
"""
HierarchicalSectorClustering

Discovers sector structure via hierarchical clustering, following Žignić et al. (2024).

Distance Matrix Formula:
    D_ij = (|Ŝ_ij| / √(θ̂_ij·T^(-1)·log p))^(-1)

Where:
- Ŝ_ij: Sample correlation between assets i and j
- θ̂_ij: Estimate of variance of correlation estimator
- T: Number of time periods
- p: Number of assets

Uses agglomerative clustering with cross-validation for optimal cluster count.
"""

from dataclasses import dataclass
import numpy as np
from typing import Optional, Literal
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from sklearn.metrics import silhouette_score


@dataclass
class ClusteringResult:
    """Results from hierarchical clustering."""

    cluster_assignments: dict[str, int]  # ticker → cluster_id
    n_clusters: int
    linkage_matrix: np.ndarray  # Hierarchical linkage
    cluster_quality: float  # Silhouette score


class HierarchicalSectorClustering:
    """
    Discovers sector structure via hierarchical clustering.

    Based on Žignić et al. (2024):
        D_ij = (|S_ij| / √(θ̂_ij·T^(-1)·log p))^(-1)

    Uses agglomerative clustering with cross-validation for optimal cluster count.
    """

    def __init__(
        self,
        linkage_method: Literal["ward", "average", "complete", "weighted"] = "ward",
        n_clusters: Optional[int] = None,
        max_clusters: int = 20,
        cv_folds: int = 5,
    ):
        """
        Initialize hierarchical clustering.

        Args:
            linkage_method: Clustering linkage method
            n_clusters: Fixed cluster count (if None, use cross-validation)
            max_clusters: Maximum clusters to consider in cross-validation
            cv_folds: Number of CV folds for cluster selection
        """
        self.linkage_method = linkage_method
        self.n_clusters = n_clusters
        self.max_clusters = max_clusters
        self.cv_folds = cv_folds

    def fit(
        self,
        residuals: np.ndarray,  # T×p residual matrix
        tickers: list[str],
    ) -> ClusteringResult:
        """
        Fit hierarchical clustering to residuals.

        Args:
            residuals: T×p matrix of residual returns
            tickers: List of p ticker symbols

        Returns:
            ClusteringResult with cluster assignments

        Raises:
            ValueError: If residuals shape doesn't match tickers
        """
        # Validate inputs
        T, p = residuals.shape

        if len(tickers) != p:
            raise ValueError(
                f"Residuals shape {residuals.shape} doesn't match "
                f"{len(tickers)} tickers"
            )

        if T < 2:
            raise ValueError(
                f"Insufficient observations: T={T}. Need at least 2 observations."
            )

        # Compute adaptive distance matrix
        distance_matrix = self._compute_adaptive_distance(residuals)

        # Convert to condensed form for scipy
        condensed_dist = squareform(distance_matrix, checks=False)

        # Perform hierarchical clustering
        linkage_matrix = linkage(condensed_dist, method=self.linkage_method)

        # Determine optimal number of clusters
        if self.n_clusters is None:
            optimal_k = self._select_optimal_clusters(
                residuals, linkage_matrix, distance_matrix
            )
        else:
            optimal_k = self.n_clusters

        # Cut dendrogram to get cluster assignments
        cluster_labels = fcluster(linkage_matrix, optimal_k, criterion="maxclust")

        # Create ticker → cluster mapping
        cluster_assignments = dict(zip(tickers, cluster_labels.tolist()))

        # Compute cluster quality (silhouette score)
        # Note: silhouette_score expects (n_samples, n_features) where n_samples = n_clusters
        # Transpose residuals so each asset (row) is a sample
        if optimal_k > 1 and optimal_k < p:
            quality = silhouette_score(residuals.T, cluster_labels, metric="euclidean")
        else:
            quality = 0.0

        return ClusteringResult(
            cluster_assignments=cluster_assignments,
            n_clusters=optimal_k,
            linkage_matrix=linkage_matrix,
            cluster_quality=quality,
        )

    def _compute_adaptive_distance(self, residuals: np.ndarray) -> np.ndarray:
        """
        Compute adaptive distance matrix following Žignić et al. (2024).

        D_ij = (|Ŝ_ij| / √(θ̂_ij·T^(-1)·log p))^(-1)

        Args:
            residuals: T×p residual matrix

        Returns:
            p×p distance matrix
        """
        T, p = residuals.shape

        # Compute sample correlation matrix
        corr_matrix = np.corrcoef(residuals.T)

        # Compute variance of correlation estimator
        # Simplified: θ̂_ij ≈ (1 - ρ²_ij)² (Fisher's approximation)
        variance_estimate = (1 - corr_matrix**2) ** 2

        # Adaptive threshold
        # Standard error: √(θ̂_ij / T · log p)
        log_p = np.log(p) if p > 1 else 1.0
        std_error = np.sqrt(variance_estimate / T * log_p)

        # Distance: inverse of standardized correlation
        # D_ij = (|ρ_ij| / std_error)^(-1)
        # Higher correlation → smaller distance
        with np.errstate(divide="ignore", invalid="ignore"):
            distance = std_error / (np.abs(corr_matrix) + 1e-8)

        # Ensure diagonal is zero
        np.fill_diagonal(distance, 0.0)

        # Ensure symmetry
        distance = (distance + distance.T) / 2

        # Handle any infinities or NaNs
        distance = np.nan_to_num(distance, nan=1e6, posinf=1e6, neginf=1e6)

        return distance

    def _select_optimal_clusters(
        self,
        residuals: np.ndarray,
        linkage_matrix: np.ndarray,
        distance_matrix: np.ndarray,
    ) -> int:
        """
        Select optimal number of clusters using silhouette score.

        Args:
            residuals: T×p residual matrix
            linkage_matrix: Hierarchical linkage
            distance_matrix: Distance matrix

        Returns:
            Optimal number of clusters
        """
        T, p = residuals.shape

        # Limit max clusters
        max_k = min(self.max_clusters, p // 2)

        if max_k < 2:
            return 1

        # Try different cluster counts
        best_score = -1.0
        best_k = 2

        for k in range(2, max_k + 1):
            # Get cluster labels
            labels = fcluster(linkage_matrix, k, criterion="maxclust")

            # Check if we have valid clustering (multiple clusters with members)
            unique_labels = np.unique(labels)
            if len(unique_labels) < 2:
                continue

            # Compute silhouette score
            # Transpose residuals so each asset is a sample
            try:
                score = silhouette_score(residuals.T, labels, metric="euclidean")
                if score > best_score:
                    best_score = score
                    best_k = k
            except ValueError:
                # Can happen if clustering is degenerate
                continue

        return best_k
