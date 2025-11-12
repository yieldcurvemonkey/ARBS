# ABOUTME: BlockDiagonal sector-based covariance estimator package
# ABOUTME: Implements Žignić et al. (2024) block-diagonal factor model with hierarchical clustering
"""
BlockDiagonal Sector-Based Covariance

Implements block-diagonal factor model from Žignić et al. (2024):
    Σ = B·Cov(F)·B^T + block_diag(Ψ₁, ..., Ψₘ)

Components:
- HierarchicalSectorClustering: Discover sector structure
- BlockDiagonalCovariance: Main estimator
"""

from Risk.Covariance.SectorBased.BlockDiagonal.HierarchicalSectorClustering import (
    HierarchicalSectorClustering,
    ClusteringResult,
)
from Risk.Covariance.SectorBased.BlockDiagonal.BlockDiagonalCovariance import (
    BlockDiagonalCovariance,
)

__all__ = [
    "HierarchicalSectorClustering",
    "ClusteringResult",
    "BlockDiagonalCovariance",
]
