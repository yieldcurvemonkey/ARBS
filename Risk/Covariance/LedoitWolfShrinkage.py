# ABOUTME: Ledoit-Wolf shrinkage covariance estimator (extends BaseCovarianceEstimator, industry standard, >5000 citations)
# ABOUTME: Implements Σ̂_LW = δ*F + (1-δ)*S with data-driven shrinkage intensity for numerical stability
"""
Ledoit-Wolf Shrinkage Covariance Estimator

Implements the Ledoit & Wolf (2004) "Honey, I Shrunk the Sample Covariance Matrix"
shrinkage estimator with >5000 citations (industry standard).

Formula:
    Σ̂_LW = δ * F + (1-δ) * S

Where:
- S = sample covariance matrix
- F = target matrix (structured, typically constant correlation)
- δ = shrinkage intensity (data-driven, optimal)

Optimal Shrinkage Intensity:
    δ* = min(1, κ̂/T)

Where κ̂ estimates the loss from using sample covariance.

Advantages over Sample Covariance:
1. Reduced estimation error (especially when T ≈ N)
2. Better conditioned (lower condition number)
3. Always invertible (positive definite)
4. Better out-of-sample portfolio variance

From 2025 research: Most widely used shrinkage method in practice.
"""

from typing import Optional

import numpy as np
import polars as pl

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


class LedoitWolfShrinkage(BaseCovarianceEstimator):
    """
    Ledoit-Wolf shrinkage estimator (Ledoit & Wolf, 2004).

    Shrinks sample covariance toward a structured target matrix,
    with data-driven shrinkage intensity.

    Attributes:
        shrinkage_intensity (float): Optimal δ ∈ [0, 1]
        target_matrix (np.ndarray): Shrinkage target F
        sample_cov (np.ndarray): Sample covariance S
    """

    def __init__(
        self,
        target: str = "constant_correlation",
        handle_missing: str = "drop",
    ):
        """
        Initialize Ledoit-Wolf estimator.

        Args:
            target: Shrinkage target type
                - 'constant_correlation': Constant correlation model (default)
                - 'diagonal': Diagonal matrix (uncorrelated assets)
                - 'identity': Identity matrix
            handle_missing: How to handle missing data
        """
        super().__init__(handle_missing=handle_missing)
        self.target_type = target
        self.shrinkage_intensity: Optional[float] = None
        self.target_matrix: Optional[np.ndarray] = None
        self.sample_cov: Optional[np.ndarray] = None
        self.block_shrinkage_intensities_: Optional[dict] = None

    def _fit_impl(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate Ledoit-Wolf shrinkage covariance matrix.

        Args:
            returns: Clean DataFrame of returns (T×N), missing data already handled

        Returns:
            Shrinkage covariance matrix (N×N)
        """
        # Calculate sample covariance
        returns_np = returns.to_numpy()

        # Use pairwise computation if requested
        if self.handle_missing == "pairwise":
            self.sample_cov = self._pairwise_covariance(returns_np)
        else:
            # Standard covariance (drops rows with any NaN)
            sample_cov = np.cov(returns_np.T)
            # Ensure covariance is always 2D (np.cov returns scalar for single column)
            self.sample_cov = np.atleast_2d(sample_cov)

        # Calculate shrinkage target
        self.target_matrix = self._compute_target(returns)

        # Calculate optimal shrinkage intensity
        self.shrinkage_intensity = self._compute_shrinkage_intensity(
            returns.to_numpy(), self.sample_cov, self.target_matrix
        )

        # Apply shrinkage: Σ̂_LW = δ * F + (1-δ) * S
        return self.shrinkage_intensity * self.target_matrix + (1 - self.shrinkage_intensity) * self.sample_cov

    def _pairwise_covariance(self, returns_np: np.ndarray) -> np.ndarray:
        """
        Compute covariance using pairwise complete observations.

        For each pair of assets (i, j), compute covariance using only
        observations where both assets have valid (non-NaN) values.

        Args:
            returns_np: Returns matrix (T×N) with possible NaN values

        Returns:
            Covariance matrix (N×N) computed pairwise
        """
        N = returns_np.shape[1]
        cov_matrix = np.zeros((N, N))

        for i in range(N):
            for j in range(i, N):  # Symmetric, only compute upper triangle
                # Get complete observations for this pair
                valid_mask = ~(np.isnan(returns_np[:, i]) | np.isnan(returns_np[:, j]))
                valid_i = returns_np[valid_mask, i]
                valid_j = returns_np[valid_mask, j]

                # Compute covariance for this pair
                if len(valid_i) > 1:
                    cov_ij = np.cov(valid_i, valid_j)[0, 1]
                else:
                    # Not enough observations, use 0
                    cov_ij = 0.0

                cov_matrix[i, j] = cov_ij
                cov_matrix[j, i] = cov_ij  # Symmetric

        return cov_matrix

    def _compute_target(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Compute shrinkage target matrix F.

        Args:
            returns: DataFrame of returns

        Returns:
            Target matrix F (N×N)
        """
        N = returns.shape[1]

        if self.target_type == "diagonal":
            # Diagonal: var(r_i) on diagonal, zeros off-diagonal
            if self.handle_missing == "pairwise":
                # Compute variances ignoring NaN
                returns_np = returns.to_numpy()
                variances = np.nanvar(returns_np, axis=0, ddof=1)
            else:
                variances = returns.var(ddof=1).to_numpy()
            return np.diag(variances)

        elif self.target_type == "identity":
            # Identity matrix (all assets have unit variance, zero correlation)
            return np.eye(N)

        elif self.target_type == "constant_correlation":
            # Constant correlation model (Ledoit-Wolf default)
            return self._constant_correlation_target(returns)

        else:
            raise ValueError(f"Unknown target type: {self.target_type}")

    def _constant_correlation_target(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Compute constant correlation target.

        Target matrix:
            F_ij = {
                σ_i²         if i = j (variance)
                ρ̄ σ_i σ_j    if i ≠ j (constant correlation)
            }

        Where ρ̄ is the average correlation.

        Args:
            returns: DataFrame of returns

        Returns:
            Constant correlation matrix (N×N)
        """
        # Calculate sample correlation matrix
        returns_np = returns.to_numpy()

        # Use pairwise if needed (to avoid NaN)
        if self.handle_missing == "pairwise":
            cov_matrix = self._pairwise_covariance(returns_np)
            # Convert to correlation
            std = np.sqrt(np.diag(cov_matrix))
            std_matrix = np.outer(std, std)
            std_matrix = np.where(std_matrix > 1e-10, std_matrix, 1.0)
            corr_matrix = cov_matrix / std_matrix
            corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
            np.fill_diagonal(corr_matrix, 1.0)
        else:
            corr_matrix = np.corrcoef(returns_np.T)
            # Ensure correlation matrix is always 2D (np.corrcoef returns scalar for single column)
            corr_matrix = np.atleast_2d(corr_matrix)

        # Average off-diagonal correlation
        n = corr_matrix.shape[0]
        mask = ~np.eye(n, dtype=bool)  # Off-diagonal mask
        avg_corr = np.mean(corr_matrix[mask])

        # Create constant correlation matrix
        target_corr = np.full((n, n), avg_corr)
        np.fill_diagonal(target_corr, 1.0)

        # Convert to covariance using sample standard deviations
        if self.handle_missing == "pairwise":
            std = np.sqrt(np.nanvar(returns_np, axis=0, ddof=1))
        else:
            std = returns.std(ddof=1).to_numpy()
        target_cov = target_corr * np.outer(std, std)

        return target_cov

    def _compute_shrinkage_intensity(
        self,
        returns: np.ndarray,
        sample_cov: np.ndarray,
        target: np.ndarray,
    ) -> float:
        """
        Compute optimal shrinkage intensity δ*.

        This is the data-driven parameter that minimizes the
        expected squared Frobenius norm of the estimation error.

        Formula (simplified):
            δ* = min(1, κ̂/T)

        Where κ̂ estimates the misspecification between sample
        and target.

        Args:
            returns: Returns array (T×N)
            sample_cov: Sample covariance (N×N)
            target: Target matrix (N×N)

        Returns:
            Optimal shrinkage intensity δ* ∈ [0, 1]
        """
        T, N = returns.shape

        # Demean returns
        returns_centered = returns - np.mean(returns, axis=0)

        # Calculate π̂: sum of asymptotic variances of sample covariance elements
        # π̂ = (1/T²) Σ_t [(r_t - r̄)(r_t - r̄)' - S]²
        pi_hat = 0.0
        for t in range(T):
            r_t = returns_centered[t : t + 1, :].T  # Column vector
            outer_t = r_t @ r_t.T
            diff = outer_t - sample_cov
            pi_hat += np.sum(diff**2)
        pi_hat /= T**2

        # Calculate ρ̂: squared Frobenius norm of (S - F)
        rho_hat = np.sum((sample_cov - target) ** 2)

        # Calculate γ̂: trace of (S - F)²
        # This is a simplification; full formula is more complex

        # Shrinkage intensity: δ* = max(0, min(1, (π̂ - γ̂)/ρ̂))
        # Simplified version: δ* = min(1, pi_hat / (T * rho_hat))
        if rho_hat < 1e-10:
            # Target and sample are identical → no shrinkage needed
            delta = 0.0
        else:
            kappa = pi_hat / rho_hat
            delta = max(0.0, min(1.0, kappa / T))

        return delta

    def get_shrinkage_intensity(self) -> float:
        """
        Get the optimal shrinkage intensity.

        Returns:
            δ* ∈ [0, 1]

        Raises:
            ValueError: If fit() hasn't been called yet
        """
        if self.shrinkage_intensity is None:
            raise ValueError("Must call fit() before get_shrinkage_intensity()")
        return self.shrinkage_intensity

    def apply_per_block_shrinkage(
        self,
        blocks: dict,
        returns_by_block: dict,
        target: str = "constant_correlation",
    ) -> dict:
        """
        Apply Ledoit-Wolf shrinkage to each block separately.

        This implements per-block shrinkage from the sector risk model paper,
        where each sector gets its own data-driven shrinkage intensity α_m.

        Formula (Paper 2, Equation 3.3):
            Ŝ^c_m = α_m·Ŝ^c_m + (1 - α_m)·S̃^c_m

        where:
        - Ŝ^c_m: Sample covariance of block m
        - S̃^c_m: Shrinkage target (constant correlation)
        - α_m: Ledoit-Wolf intensity for block m (data-driven, different per block)

        Args:
            blocks: Dict mapping sector names to sample covariance matrices (N_m × N_m)
            returns_by_block: Dict mapping sector names to returns arrays (T × N_m)
            target: Shrinkage target type (default: 'constant_correlation')

        Returns:
            Dict mapping sector names to shrunk covariance matrices

        Example:
            >>> blocks = {
            ...     'Technology': tech_cov,  # 5×5
            ...     'Utilities': util_cov,   # 3×3
            ... }
            >>> returns_by_block = {
            ...     'Technology': tech_returns,  # T×5
            ...     'Utilities': util_returns,   # T×3
            ... }
            >>> shrunk = estimator.apply_per_block_shrinkage(blocks, returns_by_block)
        """
        shrunk_blocks = {}
        self.block_shrinkage_intensities_ = {}

        for sector_name, sample_cov in blocks.items():
            # Get returns for this block
            returns = returns_by_block[sector_name]

            # Convert to polars for consistency with existing methods
            returns_pl = pl.DataFrame(returns)

            # Calculate shrinkage target for this block
            target_matrix = self._compute_target_for_block(returns_pl, target)

            # Calculate optimal shrinkage intensity for this block
            alpha = self._compute_shrinkage_intensity(returns, sample_cov, target_matrix)

            # Store shrinkage intensity
            self.block_shrinkage_intensities_[sector_name] = alpha

            # Apply shrinkage: Ŝ = α·Ŝ + (1-α)·S̃
            shrunk_cov = alpha * sample_cov + (1 - alpha) * target_matrix

            shrunk_blocks[sector_name] = shrunk_cov

        return shrunk_blocks

    def _compute_target_for_block(
        self,
        returns: pl.DataFrame,
        target: str,
    ) -> np.ndarray:
        """
        Compute shrinkage target for a single block.

        Args:
            returns: Returns DataFrame for the block
            target: Target type ('constant_correlation', 'diagonal', 'identity')

        Returns:
            Target matrix (N×N)
        """
        # Temporarily set target type
        original_target = self.target_type
        self.target_type = target

        # Compute target using existing method
        target_matrix = self._compute_target(returns)

        # Restore original target type
        self.target_type = original_target

        return target_matrix

    def get_block_shrinkage_intensities(self) -> dict:
        """
        Get the shrinkage intensities for each block.

        Returns:
            Dict mapping sector names to shrinkage intensities α ∈ [0, 1]

        Raises:
            ValueError: If apply_per_block_shrinkage() hasn't been called yet
        """
        if self.block_shrinkage_intensities_ is None:
            raise ValueError("Must call apply_per_block_shrinkage() before " "get_block_shrinkage_intensities()")
        return self.block_shrinkage_intensities_

    def __repr__(self) -> str:
        return f"LedoitWolfShrinkage(target='{self.target_type}')"
