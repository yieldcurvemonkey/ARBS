# ABOUTME: Random matrix theory filtering for covariance eigenvalues
# ABOUTME: Implements Marčenko-Pastur threshold and eigenvalue cleaning
"""
Random Matrix Theory Filtering

Filters covariance matrix eigenvalues using random matrix theory (RMT)
to remove noise and improve out-of-sample performance.

Based on Marčenko-Pastur distribution:
    λ_± = σ²(1 ± √(p/T))²

Eigenvalues below λ_+ are considered noise and are replaced with the threshold
value to ensure positive definiteness while removing spurious structure.

Reference:
- García-Medina et al. (2024): "Hierarchical Spectral Clustering of S&P 500"
- Marčenko & Pastur (1967): "Distribution of eigenvalues for some sets of random matrices"
"""

import numpy as np
from typing import Tuple


class RandomMatrixFilter:
    """
    Filters covariance eigenvalues using random matrix theory.

    Based on Marčenko-Pastur distribution:
        λ_± = σ²(1 ± √(p/T))²

    Eigenvalues below λ_+ are considered noise and filtered.
    """

    def __init__(
        self,
        filter_method: str = "marcenko_pastur",
        sigma_estimator: str = "median",
    ):
        """
        Initialize random matrix filter.

        Args:
            filter_method: Method for eigenvalue filtering
                - "marcenko_pastur": Use Marčenko-Pastur threshold (default)
            sigma_estimator: How to estimate noise level σ²
                - "median": Use median of smallest eigenvalues (default)
                - "robust": Use robust estimator (MAD)
        """
        if filter_method not in ["marcenko_pastur"]:
            raise ValueError(f"Unknown filter_method: {filter_method}")

        if sigma_estimator not in ["median", "robust"]:
            raise ValueError(f"Unknown sigma_estimator: {sigma_estimator}")

        self.filter_method = filter_method
        self.sigma_estimator = sigma_estimator

    def filter_eigenvalues(
        self,
        eigenvalues: np.ndarray,
        n_observations: int,
        n_assets: int,
    ) -> np.ndarray:
        """
        Filter eigenvalues using Marčenko-Pastur threshold.

        Args:
            eigenvalues: Array of eigenvalues (sorted descending)
            n_observations: Number of time observations (T)
            n_assets: Number of assets (p)

        Returns:
            Filtered eigenvalues (same length as input)

        Raises:
            ValueError: If n_observations < n_assets (ill-conditioned)
        """
        # Validate dimensions
        if n_observations < n_assets:
            raise ValueError(
                f"Insufficient observations: n_observations ({n_observations}) "
                f"< n_assets ({n_assets}). Matrix is ill-conditioned."
            )

        if len(eigenvalues) != n_assets:
            raise ValueError(
                f"Eigenvalues length ({len(eigenvalues)}) doesn't match "
                f"n_assets ({n_assets})"
            )

        # Estimate noise level σ²
        sigma_sq = self._estimate_noise_level(eigenvalues, n_observations, n_assets)

        # Calculate Marčenko-Pastur threshold
        threshold = self._marcenko_pastur_threshold(sigma_sq, n_observations, n_assets)

        # Filter eigenvalues: replace those below threshold
        filtered_eigenvalues = np.copy(eigenvalues)
        noise_mask = eigenvalues < threshold

        # Replace noise eigenvalues with threshold value
        filtered_eigenvalues[noise_mask] = threshold

        return filtered_eigenvalues

    def clean_covariance(
        self,
        cov_matrix: np.ndarray,
        n_observations: int,
    ) -> np.ndarray:
        """
        Clean covariance matrix by filtering eigenvalues.

        Args:
            cov_matrix: p×p covariance matrix
            n_observations: Number of time observations (T)

        Returns:
            Cleaned covariance matrix (positive definite, symmetric)

        Raises:
            ValueError: If matrix is not square or symmetric
        """
        # Validate input
        if cov_matrix.shape[0] != cov_matrix.shape[1]:
            raise ValueError(
                f"Covariance matrix must be square, got shape {cov_matrix.shape}"
            )

        if not np.allclose(cov_matrix, cov_matrix.T, rtol=1e-10):
            raise ValueError("Covariance matrix must be symmetric")

        n_assets = cov_matrix.shape[0]

        # Eigenvalue decomposition
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)

        # Sort descending (eigh returns ascending)
        idx = eigenvalues.argsort()[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        # Filter eigenvalues
        filtered_eigenvalues = self.filter_eigenvalues(
            eigenvalues, n_observations, n_assets
        )

        # Reconstruct covariance matrix
        cleaned_cov = eigenvectors @ np.diag(filtered_eigenvalues) @ eigenvectors.T

        # Ensure symmetry (numerical stability)
        cleaned_cov = (cleaned_cov + cleaned_cov.T) / 2

        return cleaned_cov

    def _estimate_noise_level(
        self,
        eigenvalues: np.ndarray,
        n_observations: int,
        n_assets: int,
    ) -> float:
        """
        Estimate noise variance σ² from eigenvalue spectrum.

        Uses median of smallest eigenvalues as robust estimator of noise level.
        Conservative approach: use smallest 10% of eigenvalues (min 1, max n_assets//2)
        to avoid overestimating noise when most eigenvalues are signal.

        Args:
            eigenvalues: Array of eigenvalues (sorted descending)
            n_observations: Number of observations (T)
            n_assets: Number of assets (p)

        Returns:
            Estimated noise variance σ²
        """
        if self.sigma_estimator == "median":
            # Use median of smallest 10% of eigenvalues as noise estimate
            # More conservative than 50% to handle cases with many signal eigenvalues
            n_noise = max(1, min(n_assets // 10, n_assets // 2))
            noise_eigenvalues = eigenvalues[-n_noise:]
            sigma_sq = np.median(noise_eigenvalues)

        elif self.sigma_estimator == "robust":
            # Robust estimator: MAD (Median Absolute Deviation)
            n_noise = max(1, min(n_assets // 10, n_assets // 2))
            noise_eigenvalues = eigenvalues[-n_noise:]
            median = np.median(noise_eigenvalues)
            mad = np.median(np.abs(noise_eigenvalues - median))
            sigma_sq = median  # Use median as base estimate

        else:
            raise ValueError(f"Unknown sigma_estimator: {self.sigma_estimator}")

        # Ensure positive
        sigma_sq = max(sigma_sq, 1e-10)

        return sigma_sq

    def _marcenko_pastur_threshold(
        self,
        sigma_sq: float,
        n_observations: int,
        n_assets: int,
    ) -> float:
        """
        Compute λ_+ threshold from Marčenko-Pastur distribution.

        Formula:
            λ_+ = σ²(1 + √q)²

        Where:
            q = p/T (ratio of assets to observations)
            σ² = noise variance

        Args:
            sigma_sq: Noise variance estimate
            n_observations: Number of observations (T)
            n_assets: Number of assets (p)

        Returns:
            Upper threshold λ_+ for noise eigenvalues
        """
        q = n_assets / n_observations
        threshold = sigma_sq * (1 + np.sqrt(q)) ** 2
        return threshold

    def __repr__(self) -> str:
        return (
            f"RandomMatrixFilter("
            f"filter_method='{self.filter_method}', "
            f"sigma_estimator='{self.sigma_estimator}')"
        )
