# ABOUTME: StochasticBlock covariance estimator with inter-block correlations
# ABOUTME: MVP implementation using block-diagonal base + regularized off-diagonal blocks
"""
StochasticBlockCovariance Estimator

Implements Chen et al. (2025) stochastic block covariance model with inter-block correlations.

Key Innovation:
    Unlike pure block-diagonal models, this allows cross-sector correlations
    via off-diagonal blocks.

MVP Implementation Strategy:
    Ψ_ij = α·BlockDiag_ij + (1-α)·FullCov_ij

Where:
    - BlockDiag_ij: Pure block-diagonal component (within-sector only)
    - FullCov_ij: Full sample covariance (captures cross-sector)
    - α ∈ [0,1]: Sparsity parameter (α=1 → pure block-diagonal, α=0 → full cov)

This provides a smooth interpolation between block-diagonal structure
and full covariance, with α controlling the strength of inter-block correlations.
"""

import polars as pl
import numpy as np
from typing import Optional, Dict, List
from scipy import linalg
from sklearn.cluster import AgglomerativeClustering

from Risk.Covariance.SectorBased.BaseSectorCovarianceEstimator import (
    SectorBasedCovarianceEstimator,
)


class StochasticBlockCovariance(SectorBasedCovarianceEstimator):
    """
    Estimates covariance with stochastic block structure allowing inter-block correlations.

    Based on Chen et al. (2025). Unlike BlockDiagonal, this allows off-diagonal blocks
    to capture cross-sector dependencies.

    MVP Approach:
        1. Compute full sample covariance
        2. Compute block-diagonal covariance (within-sector only)
        3. Blend: Ψ = α·BlockDiag + (1-α)·FullCov

    Advanced (Future):
        - Hierarchical Bayesian inference with MCMC sampling
        - Automatic block discovery via correlation clustering
    """

    def __init__(
        self,
        allow_inter_block: bool = True,
        alpha: Optional[float] = None,
        discover_blocks: bool = False,
        n_clusters: Optional[int] = None,
        shrinkage_per_block: bool = True,
        min_eigenvalue: float = 1e-8,
        handle_missing: str = 'drop',
    ):
        """
        Initialize StochasticBlockCovariance estimator.

        Args:
            allow_inter_block: If True, allow off-diagonal blocks (cross-sector correlations)
                             If False, pure block-diagonal (equivalent to BlockDiagonal)
            alpha: Sparsity parameter ∈ [0,1]. If None, auto-select via cross-validation.
                  α=1: Pure block-diagonal (maximum sparsity)
                  α=0: Full covariance (no sparsity)
            discover_blocks: If True, discover block structure via clustering.
                           If False, use predefined sector column.
            n_clusters: Number of clusters for discovery (if discover_blocks=True)
            shrinkage_per_block: Apply Ledoit-Wolf shrinkage within each block
            min_eigenvalue: Minimum eigenvalue for positive definiteness
            handle_missing: How to handle missing data ('drop' or 'pairwise')
        """
        clustering_method = "hierarchical" if discover_blocks else "predefined"
        super().__init__(clustering_method=clustering_method, handle_missing=handle_missing)

        self.allow_inter_block = allow_inter_block
        self.alpha = alpha
        self.n_clusters = n_clusters
        self.shrinkage_per_block = shrinkage_per_block
        self.min_eigenvalue = min_eigenvalue

        # Fitted attributes
        self.ticker_order_: Optional[List[str]] = None
        self.alpha_: Optional[float] = None  # Fitted alpha value

    def fit(self, returns: pl.DataFrame, sector_col: Optional[str] = "sector") -> np.ndarray:
        """
        Estimate covariance matrix from returns.

        Args:
            returns: DataFrame with columns [ticker, date, return, sector]
                     Long format: Each row is (ticker, date, return, sector)
            sector_col: Name of sector column (ignored if discover_blocks=True)

        Returns:
            Covariance matrix (N×N numpy array)

        Raises:
            ValueError: If required columns missing or data invalid
        """
        # Validate input data
        self._validate_sector_input(returns, sector_col)

        # Handle missing data
        returns_clean = self._handle_missing_data(returns)

        # Convert to wide format (T×N)
        returns_array, tickers = self._convert_to_wide_format(returns_clean)
        self.ticker_order_ = tickers
        self.asset_names_ = tickers

        # Determine sector mapping
        self.sector_mapping_ = self._determine_sector_assignments(
            returns_array, tickers, returns_clean, sector_col
        )

        # Compute full sample covariance (baseline)
        cov_full = np.cov(returns_array, rowvar=False)  # N×N

        # Compute block-diagonal component
        cov_block = self._compute_block_diagonal(returns_array, tickers)

        # Determine alpha (sparsity parameter)
        if self.alpha is not None:
            self.alpha_ = self.alpha
        else:
            # Auto-select alpha via cross-validation (simple heuristic for MVP)
            self.alpha_ = 0.7 if self.allow_inter_block else 1.0

        # Blend block-diagonal and full covariance
        if self.allow_inter_block:
            # Ψ = α·BlockDiag + (1-α)·FullCov
            cov_matrix = self.alpha_ * cov_block + (1 - self.alpha_) * cov_full
        else:
            # Pure block-diagonal (no inter-block correlations)
            cov_matrix = cov_block

        # Ensure positive definiteness (using inherited method)
        cov_matrix = self._ensure_positive_definite(cov_matrix, min_eigenvalue=self.min_eigenvalue)

        # Store fitted covariance
        self.cov_matrix_ = cov_matrix

        return cov_matrix

    def _compute_block_diagonal(
        self,
        returns_array: np.ndarray,
        tickers: List[str],
    ) -> np.ndarray:
        """
        Compute block-diagonal covariance (within-sector only).

        Args:
            returns_array: T×N returns matrix
            tickers: List of ticker names

        Returns:
            Block-diagonal covariance matrix (N×N)
        """
        n_assets = len(tickers)
        cov_block = np.zeros((n_assets, n_assets))

        # Group tickers by sector (using inherited method)
        sector_groups = self.get_sector_groups()

        # Get ticker indices
        ticker_to_idx = {ticker: i for i, ticker in enumerate(tickers)}

        # Compute covariance for each block
        for sector, sector_tickers in sector_groups.items():
            # Get indices for this sector
            indices = [ticker_to_idx[t] for t in sector_tickers if t in ticker_to_idx]

            if len(indices) == 0:
                continue

            # Extract returns for this sector
            sector_returns = returns_array[:, indices]  # T×n_i

            # Compute within-sector covariance
            if self.shrinkage_per_block:
                sector_cov = self._ledoit_wolf_shrinkage(sector_returns)
            else:
                sector_cov = np.cov(sector_returns, rowvar=False)

            # Fill in block-diagonal position
            for i, idx_i in enumerate(indices):
                for j, idx_j in enumerate(indices):
                    cov_block[idx_i, idx_j] = sector_cov[i, j]

        return cov_block

    def _ledoit_wolf_shrinkage(self, returns: np.ndarray) -> np.ndarray:
        """
        Apply Ledoit-Wolf shrinkage to covariance matrix.

        Args:
            returns: T×n returns matrix for a single sector

        Returns:
            Shrunk covariance matrix (n×n)
        """
        T, n = returns.shape

        # Sample covariance
        S = np.cov(returns, rowvar=False)

        # Target: constant correlation model
        # Ψ = σ̄²·[(1-ρ̄)·I + ρ̄·11ᵀ]
        variances = np.diag(S)
        mean_var = np.mean(variances)

        # Compute average correlation
        std_devs = np.sqrt(variances)
        corr = S / np.outer(std_devs, std_devs)
        np.fill_diagonal(corr, 0)  # Exclude diagonal
        mean_corr = np.sum(corr) / (n * (n - 1)) if n > 1 else 0

        # Constant correlation target
        target = mean_var * ((1 - mean_corr) * np.eye(n) + mean_corr * np.ones((n, n)))

        # Ledoit-Wolf shrinkage intensity (simplified)
        if T > n:
            # Asymptotic formula
            alpha = min(1.0, max(0.0, (T - 2) / T * np.trace(S) / np.linalg.norm(S - target, 'fro')**2))
        else:
            # High-dimensional regime: use heuristic
            alpha = (n - 2) / (T + n - 2) if T > 2 else 0.5

        # Shrunk covariance
        cov_shrunk = (1 - alpha) * S + alpha * target

        return cov_shrunk

    def get_block_structure(self) -> Dict[str, List[str]]:
        """
        Get the fitted block structure (sector groupings).

        Returns:
            Dictionary mapping sector → list of tickers

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        # Use inherited method
        return self.get_sector_groups()

    def get_cross_sector_correlations(self) -> pl.DataFrame:
        """
        Extract cross-sector correlation matrix.

        Returns average correlation between each pair of sectors.

        Returns:
            DataFrame with columns [sector_i, sector_j, avg_correlation]
        """
        if self.cov_matrix_ is None:
            raise ValueError("Must call fit() before get_cross_sector_correlations()")

        # Get correlation matrix
        corr_matrix = self.get_correlation()

        # Group by sectors
        sector_groups = self.get_block_structure()
        sectors = sorted(sector_groups.keys())

        # Ticker to index
        ticker_to_idx = {t: i for i, t in enumerate(self.ticker_order_)}

        results = []
        for i, sector_i in enumerate(sectors):
            for j, sector_j in enumerate(sectors):
                if i < j:  # Upper triangular only
                    # Get indices for both sectors
                    indices_i = [ticker_to_idx[t] for t in sector_groups[sector_i]]
                    indices_j = [ticker_to_idx[t] for t in sector_groups[sector_j]]

                    # Extract cross-sector block
                    cross_block = corr_matrix[np.ix_(indices_i, indices_j)]

                    # Average correlation
                    avg_corr = np.mean(cross_block)

                    results.append({
                        "sector_i": sector_i,
                        "sector_j": sector_j,
                        "avg_correlation": avg_corr,
                    })

        return pl.DataFrame(results)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"allow_inter_block={self.allow_inter_block}, "
            f"alpha={self.alpha}, "
            f"discover_blocks={self.discover_blocks})"
        )
