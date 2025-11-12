# ABOUTME: Bai-Ng Information Criterion for optimal K factor selection
# ABOUTME: Implements IC(K) = log(V(K)) + K·g(p,T) minimization

"""
BaiNgIC: Bai-Ng Information Criterion for Factor Selection

Based on:
- Bai & Ng (2002): "Determining the Number of Factors in Approximate Factor Models"
- Žignić et al. (2024), Section 3.1: Number of Factors Estimation

Mathematical Specification (Equation 8):
    IC(K) = log(V(K)) + K·g(p,T)

    where:
    - V(K) = (1/(p·T)) · ||Y - YB(B'B)^(-1)B'||_F^2
    - g(p,T) = ((p+T)/(p·T)) · log((p·T)/(p+T))
    - K* = argmin_{K ∈ [1, K_max]} IC(K)

Properties:
- IC curve is U-shaped: decreases then increases
- Balances reconstruction error vs model complexity
- Penalty term g(p,T) grows with K
"""

import numpy as np
import polars as pl
from typing import Optional
from sklearn.decomposition import PCA

from Risk.Covariance.SectorBased.sector_utils import long_to_wide


class BaiNgIC:
    """
    Bai-Ng Information Criterion for selecting optimal number of factors.

    Selects K* that minimizes:
        IC(K) = log(V(K)) + K·g(p,T)

    where V(K) is reconstruction error and g(p,T) is penalty term.
    """

    def __init__(self, k_max: int = 10):
        """
        Initialize Bai-Ng IC estimator.

        Args:
            k_max: Maximum number of factors to consider
        """
        if k_max < 1:
            raise ValueError(f"k_max must be >= 1, got {k_max}")

        self.k_max = k_max
        self.ic_values_ = None
        self.k_selected_ = None

    def select_num_factors(
        self,
        returns: pl.DataFrame,
    ) -> int:
        """
        Select optimal number of factors via IC minimization.

        Args:
            returns: Long format DataFrame [ticker, date, return]

        Returns:
            Optimal K* ∈ [1, k_max]

        Raises:
            ValueError: If data insufficient (T < 10 or T < p)
        """
        # Convert to wide format
        returns_wide, tickers = long_to_wide(returns, pivot_col="ticker", value_col="return")
        Y = returns_wide.to_numpy()  # T×p
        T, p = Y.shape

        # Validate dimensions
        if T < 10:
            raise ValueError(
                f"Insufficient observations: T={T}. Need at least 10 observations."
            )

        if T < p:
            raise ValueError(
                f"Insufficient observations: T={T} < p={p}. "
                f"Need T >= p for reliable factor estimation."
            )

        # Limit k_max to reasonable value
        k_max_effective = min(self.k_max, min(T, p) // 2, T - 1)

        if k_max_effective < 1:
            # Edge case: return K=1
            self.k_selected_ = 1
            self.ic_values_ = np.array([0.0])
            return 1

        # Demean returns
        Y_centered = Y - np.mean(Y, axis=0, keepdims=True)

        # Compute IC for K = 1, 2, ..., k_max_effective
        ic_values = np.zeros(k_max_effective)

        for K in range(1, k_max_effective + 1):
            V_K = self._compute_reconstruction_error(Y_centered, K, T, p)
            g_pT = self._compute_penalty(p, T)
            ic_values[K - 1] = np.log(V_K + 1e-10) + K * g_pT

        # Select K that minimizes IC
        k_optimal = int(np.argmin(ic_values)) + 1

        # Store results
        self.ic_values_ = ic_values
        self.k_selected_ = k_optimal

        return k_optimal

    def _compute_reconstruction_error(
        self,
        Y_centered: np.ndarray,
        K: int,
        T: int,
        p: int,
    ) -> float:
        """
        Compute V(K): mean squared reconstruction error with K factors.

        V(K) = (1/(p·T)) · ||Y - YB(B'B)^(-1)B'||_F^2

        This is equivalent to the sum of squared residuals after removing
        the first K principal components.

        Args:
            Y_centered: T×p demeaned returns
            K: Number of factors
            T: Number of observations
            p: Number of assets

        Returns:
            Reconstruction error V(K)
        """
        # Extract K factors via PCA
        pca = PCA(n_components=K)
        pca.fit(Y_centered)

        # Reconstruction error is sum of unexplained variance
        # V(K) = sum of eigenvalues not captured by top K components
        explained_variance = pca.explained_variance_

        # Total variance
        total_var = np.var(Y_centered, axis=0, ddof=1).sum()

        # Unexplained variance
        unexplained_var = total_var - explained_variance.sum()

        # Normalize by (T-1) to get MSE
        # V(K) = unexplained variance / (p·T)
        V_K = unexplained_var / (p * T) if p * T > 0 else 1e-10

        return max(V_K, 1e-10)

    def _compute_penalty(self, p: int, T: int) -> float:
        """
        Compute penalty term g(p,T).

        Formula:
            g(p,T) = ((p+T)/(p·T)) · log((p·T)/(p+T))

        Args:
            p: Number of assets
            T: Number of observations

        Returns:
            Penalty g(p,T)
        """
        p_plus_T = p + T
        p_times_T = p * T

        if p_times_T <= 0 or p_plus_T <= 0:
            return 1.0

        g = (p_plus_T / p_times_T) * np.log(p_times_T / p_plus_T)

        return g

    def __repr__(self) -> str:
        return f"BaiNgIC(k_max={self.k_max})"
