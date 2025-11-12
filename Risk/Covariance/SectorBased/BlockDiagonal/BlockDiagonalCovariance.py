# ABOUTME: Block-diagonal covariance estimator with sector structure
# ABOUTME: Integrates factor extraction and per-block Ledoit-Wolf shrinkage
"""
BlockDiagonalCovariance

Estimates covariance with sector-based block-diagonal structure from Žignić et al. (2024):
    Σ = B·Cov(F)·B^T + block_diag(Ψ₁, ..., Ψₘ)

Where:
- B: Factor loading matrix (p×K)
- Cov(F): Factor covariance (K×K)
- Ψᵢ: Residual covariance for sector i (block-diagonal structure)

Components:
- Factor extraction via PCA
- Per-block Ledoit-Wolf shrinkage
- Eigenvalue bias correction when p > T
- Support for predefined or hierarchical clustering
"""

import numpy as np
import polars as pl
from typing import Optional, Literal
from sklearn.decomposition import PCA

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator
from Risk.Covariance.SectorBased.BlockDiagonal.HierarchicalSectorClustering import (
    HierarchicalSectorClustering,
)
from Risk.Covariance.SectorBased.sector_utils import (
    validate_sector_data,
    long_to_wide,
    extract_sector_mapping,
    group_tickers_by_sector,
    create_block_diagonal_matrix,
)


class BlockDiagonalCovariance(BaseCovarianceEstimator):
    """
    Estimates covariance with sector-based block-diagonal structure.

    Based on Žignić et al. (2024):
        Σ = B·Cov(F)·B^T + Ψ

    Where Ψ has block structure:
        Ψ = block_diag(Ψ₁, Ψ₂, ..., Ψₘ)

    Each block corresponds to a sector/cluster.
    """

    def __init__(
        self,
        n_factors: Optional[int] = None,
        clustering_method: Literal["predefined", "hierarchical"] = "predefined",
        shrinkage_method: Literal["ledoit_wolf", "none"] = "ledoit_wolf",
        bias_correction: bool = True,
        handle_missing: str = "drop",
    ):
        """
        Initialize block-diagonal covariance estimator.

        Args:
            n_factors: Number of common factors (if None, auto-select via variance threshold)
            clustering_method: "predefined" (use sector column) or "hierarchical"
            shrinkage_method: Shrinkage applied to each block
            bias_correction: Apply eigenvalue bias correction when p > T
            handle_missing: How to handle missing data
        """
        super().__init__(handle_missing=handle_missing)
        self.n_factors = n_factors
        self.clustering_method = clustering_method
        self.shrinkage_method = shrinkage_method
        self.bias_correction = bias_correction

        self.clusterer = (
            HierarchicalSectorClustering() if clustering_method == "hierarchical" else None
        )

    def fit(
        self,
        returns: pl.DataFrame,
        sector_col: Optional[str] = "sector",
    ) -> np.ndarray:
        """
        Estimate block-diagonal covariance matrix.

        Args:
            returns: DataFrame with columns [ticker, date, return, sector]
                     If clustering_method="hierarchical", sector_col is optional
            sector_col: Name of sector column (for predefined clustering)

        Returns:
            Covariance matrix as numpy array (N×N)

        Raises:
            ValueError: If required columns missing or data insufficient
        """
        # Validate data
        if self.clustering_method == "predefined":
            if sector_col is None:
                raise ValueError("sector_col must be provided for predefined clustering")
            validate_sector_data(returns, sector_col)

        # Convert to wide format for computation
        wide_returns, tickers = long_to_wide(returns, pivot_col="ticker", value_col="return")
        self.asset_names_ = tickers

        # Convert to numpy for computation
        returns_matrix = wide_returns.to_numpy()  # T×p
        T, p = returns_matrix.shape

        # Step 1: Extract common factors and compute residuals
        factor_loadings, factor_cov, residuals = self._extract_factors(returns_matrix)

        # Step 2: Determine sector/cluster assignments
        if self.clustering_method == "predefined":
            ticker_sector_map = extract_sector_mapping(returns, sector_col)
        else:
            # Use hierarchical clustering on residuals
            clustering_result = self.clusterer.fit(residuals, tickers)
            ticker_sector_map = clustering_result.cluster_assignments

        # Step 3: Estimate per-block residual covariances
        sector_groups = group_tickers_by_sector(ticker_sector_map)
        block_covariances = self._estimate_block_covariances(
            residuals, tickers, sector_groups
        )

        # Step 4: Reconstruct full covariance matrix
        self.cov_matrix_ = self._reconstruct_covariance(
            factor_loadings, factor_cov, block_covariances, tickers, ticker_sector_map
        )

        return self.cov_matrix_

    def _extract_factors(
        self, returns: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Extract common factors using PCA and compute residuals.

        Args:
            returns: T×p returns matrix

        Returns:
            Tuple of (loadings, factor_cov, residuals)
            - loadings: p×K factor loading matrix
            - factor_cov: K×K factor covariance matrix
            - residuals: T×p residual matrix
        """
        T, p = returns.shape

        # Demean returns
        returns_centered = returns - np.mean(returns, axis=0)

        # Determine number of factors
        if self.n_factors is None:
            # Auto-select via variance threshold (95%)
            n_components = min(T, p)
            pca_full = PCA(n_components=n_components)
            pca_full.fit(returns_centered)

            # Select factors explaining 95% variance
            cumsum_var = np.cumsum(pca_full.explained_variance_ratio_)
            n_factors = int(np.searchsorted(cumsum_var, 0.95) + 1)
            n_factors = max(1, min(n_factors, min(T, p) // 2))
        else:
            n_factors = min(self.n_factors, min(T, p) // 2)

        # Extract factors
        pca = PCA(n_components=n_factors)
        factors = pca.fit_transform(returns_centered)  # T×K
        loadings = pca.components_.T  # p×K

        # Compute residuals: ε = Y - Y_hat = Y - F·B^T
        reconstructed = factors @ loadings.T
        residuals = returns_centered - reconstructed  # T×p

        # Factor covariance
        if n_factors == 1:
            # Special case: single factor
            factor_cov = np.array([[np.var(factors[:, 0], ddof=1)]])
        else:
            factor_cov = np.cov(factors.T)  # K×K

        return loadings, factor_cov, residuals

    def _estimate_block_covariances(
        self,
        residuals: np.ndarray,
        tickers: list[str],
        sector_groups: dict[str, list[str]],
    ) -> dict[str, np.ndarray]:
        """
        Estimate covariance for each sector block with optional shrinkage.

        Args:
            residuals: T×p residual matrix
            tickers: List of ticker names
            sector_groups: Dictionary mapping sector → list of tickers

        Returns:
            Dictionary mapping sector → block covariance matrix
        """
        T, p = residuals.shape
        ticker_to_idx = {ticker: i for i, ticker in enumerate(tickers)}

        block_covariances = {}

        for sector, sector_tickers in sector_groups.items():
            # Extract residuals for this sector
            indices = [ticker_to_idx[t] for t in sector_tickers]
            sector_residuals = residuals[:, indices]  # T×n_i

            n_i = len(sector_tickers)

            # Compute sample covariance
            if n_i == 1:
                # Special case: single asset in sector
                sample_cov = np.array([[np.var(sector_residuals[:, 0], ddof=1)]])
            else:
                sample_cov = np.cov(sector_residuals.T)  # n_i×n_i

            # Apply shrinkage if requested
            if self.shrinkage_method == "ledoit_wolf":
                shrunk_cov = self._ledoit_wolf_shrinkage(sector_residuals, sample_cov)
            else:
                shrunk_cov = sample_cov

            # Apply bias correction if requested and p > T
            if self.bias_correction and n_i > T:
                corrected_cov = self._apply_bias_correction(shrunk_cov, T, n_i)
            else:
                corrected_cov = shrunk_cov

            block_covariances[sector] = corrected_cov

        return block_covariances

    def _ledoit_wolf_shrinkage(
        self, residuals: np.ndarray, sample_cov: np.ndarray
    ) -> np.ndarray:
        """
        Apply Ledoit-Wolf shrinkage to block covariance.

        Args:
            residuals: T×n residual matrix for this block
            sample_cov: n×n sample covariance

        Returns:
            Shrunk covariance matrix
        """
        T, n = residuals.shape

        # Shrinkage target: constant correlation model
        std = np.sqrt(np.diag(sample_cov))
        corr = sample_cov / np.outer(std, std)

        # Average correlation
        mask = ~np.eye(n, dtype=bool)
        avg_corr = np.mean(corr[mask]) if n > 1 else 0.0

        # Target matrix
        target_corr = np.full((n, n), avg_corr)
        np.fill_diagonal(target_corr, 1.0)
        target = target_corr * np.outer(std, std)

        # Compute shrinkage intensity
        delta = self._compute_shrinkage_intensity(residuals, sample_cov, target)

        # Apply shrinkage
        shrunk_cov = delta * target + (1 - delta) * sample_cov

        return shrunk_cov

    def _compute_shrinkage_intensity(
        self, residuals: np.ndarray, sample_cov: np.ndarray, target: np.ndarray
    ) -> float:
        """
        Compute optimal shrinkage intensity (Ledoit-Wolf formula).

        Args:
            residuals: T×n residual matrix
            sample_cov: n×n sample covariance
            target: n×n target matrix

        Returns:
            Shrinkage intensity δ ∈ [0, 1]
        """
        T, n = residuals.shape

        # Demean
        residuals_centered = residuals - np.mean(residuals, axis=0)

        # π̂: sum of asymptotic variances
        pi_hat = 0.0
        for t in range(T):
            r_t = residuals_centered[t:t+1, :].T
            outer_t = r_t @ r_t.T
            diff = outer_t - sample_cov
            pi_hat += np.sum(diff ** 2)
        pi_hat /= T ** 2

        # ρ̂: squared Frobenius norm of (S - F)
        rho_hat = np.sum((sample_cov - target) ** 2)

        # Shrinkage intensity
        if rho_hat < 1e-10:
            delta = 0.0
        else:
            kappa = pi_hat / rho_hat
            delta = max(0.0, min(1.0, kappa / T))

        return delta

    def _apply_bias_correction(
        self, cov: np.ndarray, T: int, p: int
    ) -> np.ndarray:
        """
        Apply eigenvalue bias correction when p > T.

        Formula: λ_i^c = max{λ̂_i - c·p/T, 0}

        Args:
            cov: p×p covariance matrix
            T: Number of observations
            p: Number of assets

        Returns:
            Bias-corrected covariance matrix
        """
        # Eigen decomposition
        eigenvalues, eigenvectors = np.linalg.eigh(cov)

        # Bias correction: shrink eigenvalues
        # c is a constant (use 1.0 as default)
        c = 1.0
        correction = c * p / T
        corrected_eigenvalues = np.maximum(eigenvalues - correction, 1e-8)

        # Reconstruct matrix
        corrected_cov = eigenvectors @ np.diag(corrected_eigenvalues) @ eigenvectors.T

        return corrected_cov

    def _reconstruct_covariance(
        self,
        factor_loadings: np.ndarray,
        factor_cov: np.ndarray,
        block_covariances: dict[str, np.ndarray],
        tickers: list[str],
        ticker_sector_map: dict[str, str],
    ) -> np.ndarray:
        """
        Reconstruct full covariance: Σ = B·Cov(F)·B^T + Ψ.

        Args:
            factor_loadings: p×K loading matrix
            factor_cov: K×K factor covariance
            block_covariances: Dictionary of sector → block covariance
            tickers: List of ticker names
            ticker_sector_map: Mapping of ticker → sector

        Returns:
            Full covariance matrix (p×p)
        """
        p = len(tickers)

        # Factor component: B·Cov(F)·B^T
        factor_component = factor_loadings @ factor_cov @ factor_loadings.T

        # Block-diagonal residual component
        residual_component = create_block_diagonal_matrix(
            block_covariances, tickers, ticker_sector_map
        )

        # Full covariance
        full_cov = factor_component + residual_component

        # Ensure positive definite
        min_eigenvalue = np.min(np.linalg.eigvalsh(full_cov))
        if min_eigenvalue <= 0:
            # Add small diagonal regularization
            full_cov += np.eye(p) * (abs(min_eigenvalue) + 1e-8)

        return full_cov

    def __repr__(self) -> str:
        return (
            f"BlockDiagonalCovariance("
            f"n_factors={self.n_factors}, "
            f"clustering_method='{self.clustering_method}', "
            f"shrinkage_method='{self.shrinkage_method}', "
            f"bias_correction={self.bias_correction})"
        )
