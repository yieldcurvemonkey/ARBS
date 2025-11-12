# ABOUTME: StochasticBlock covariance estimator package
# ABOUTME: Implements Chen et al. (2025) approach with inter-block correlations
"""
StochasticBlock Covariance Estimator

Allows inter-block correlations between sectors, unlike pure block-diagonal models.

Key Innovation (Chen et al. 2025):
    Ψ = [Ψ₁₁   Ψ₁₂  ...  Ψ₁ₘ]
        [Ψ₂₁   Ψ₂₂  ...  Ψ₂ₘ]
        [...   ...   ⋱   ...]
        [Ψₘ₁   Ψₘ₂  ...  Ψₘₘ]

Off-diagonal blocks Ψᵢⱼ capture cross-sector correlations.

MVP Implementation:
    Ψ_ij = α·BlockDiag_ij + (1-α)·FullCov_ij
"""

from Risk.Covariance.SectorBased.StochasticBlock.StochasticBlockCovariance import (
    StochasticBlockCovariance
)

__all__ = ["StochasticBlockCovariance"]
