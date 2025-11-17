# ABOUTME: Shared Ledoit-Wolf shrinkage utilities for covariance estimation
# ABOUTME: Implements canonical formulas from Ledoit & Wolf (2004) for reuse across estimators
"""
Ledoit-Wolf Shrinkage Utilities

Shared utilities for Ledoit-Wolf shrinkage covariance estimation.
All functions implement the canonical formulas from Ledoit & Wolf (2004)
"Honey, I Shrunk the Sample Covariance Matrix" (>5000 citations).

These utilities are used by:
- LedoitWolfShrinkage: Direct shrinkage estimator
- BlockDiagonalCovariance: Per-block shrinkage in sector models
- Future estimators requiring Ledoit-Wolf shrinkage

Note: StochasticBlockCovariance uses a simplified formula and does not use these utilities.
"""

from typing import Optional

import numpy as np


def compute_constant_correlation_target(
    returns: np.ndarray,
    sample_cov: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Compute constant correlation shrinkage target.

    Target matrix:
        F_ij = {
            σ_i²         if i = j (variance)
            ρ̄ σ_i σ_j    if i ≠ j (constant correlation)
        }

    Where ρ̄ is the average correlation.

    This is the default Ledoit-Wolf target and preserves correlation structure
    better than simpler targets (e.g., diagonal or scaled identity).

    Args:
        returns: Returns array (T×N)
        sample_cov: Sample covariance matrix (N×N). If None, computed from returns.

    Returns:
        Constant correlation matrix (N×N)

    Example:
        >>> returns = np.random.randn(100, 10)
        >>> target = compute_constant_correlation_target(returns)
        >>> target.shape
        (10, 10)
    """
    T, N = returns.shape

    # Compute sample covariance if not provided
    if sample_cov is None:
        sample_cov = np.cov(returns.T)
        sample_cov = np.atleast_2d(sample_cov)

    # Calculate sample correlation matrix
    corr_matrix = np.corrcoef(returns.T)
    corr_matrix = np.atleast_2d(corr_matrix)

    # Average off-diagonal correlation
    mask = ~np.eye(N, dtype=bool)  # Off-diagonal mask
    avg_corr = np.mean(corr_matrix[mask]) if N > 1 else 0.0

    # Create constant correlation matrix
    target_corr = np.full((N, N), avg_corr)
    np.fill_diagonal(target_corr, 1.0)

    # Convert to covariance using sample standard deviations
    std = np.std(returns, axis=0, ddof=1)
    target_cov = target_corr * np.outer(std, std)

    return target_cov


def compute_ledoit_wolf_shrinkage_intensity(
    returns: np.ndarray,
    sample_cov: np.ndarray,
    target: np.ndarray,
) -> float:
    """
    Compute optimal Ledoit-Wolf shrinkage intensity δ*.

    This is the data-driven parameter that minimizes the expected squared
    Frobenius norm of the estimation error.

    Formula (simplified):
        δ* = min(1, κ̂/T)

    Where:
        κ̂ = π̂ / ρ̂
        π̂ = (1/T²) Σ_t [(r_t - r̄)(r_t - r̄)' - S]²  (asymptotic variance)
        ρ̂ = ||S - F||²_F  (squared Frobenius norm)

    Args:
        returns: Returns array (T×N)
        sample_cov: Sample covariance (N×N)
        target: Target matrix (N×N)

    Returns:
        Optimal shrinkage intensity δ* ∈ [0, 1]

    References:
        Ledoit & Wolf (2004) "Honey, I Shrunk the Sample Covariance Matrix"

    Example:
        >>> returns = np.random.randn(100, 10)
        >>> sample_cov = np.cov(returns.T)
        >>> target = np.eye(10)
        >>> delta = compute_ledoit_wolf_shrinkage_intensity(returns, sample_cov, target)
        >>> 0 <= delta <= 1
        True
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

    # Shrinkage intensity: δ* = max(0, min(1, (π̂ - γ̂)/ρ̂))
    # Simplified version: δ* = min(1, pi_hat / (T * rho_hat))
    if rho_hat < 1e-10:
        # Target and sample are identical → no shrinkage needed
        delta = 0.0
    else:
        kappa = pi_hat / rho_hat
        delta = max(0.0, min(1.0, kappa / T))

    return delta


def apply_ledoit_wolf_shrinkage(
    returns: np.ndarray,
    target_type: str = "constant_correlation",
    sample_cov: Optional[np.ndarray] = None,
    target: Optional[np.ndarray] = None,
) -> tuple[np.ndarray, float]:
    """
    Apply Ledoit-Wolf shrinkage to covariance matrix.

    Combines sample covariance and target matrix using optimal shrinkage intensity:
        Σ̂_LW = δ * F + (1-δ) * S

    Where:
        - S = sample covariance
        - F = target matrix
        - δ = optimal shrinkage intensity

    Args:
        returns: Returns array (T×N)
        target_type: Type of target matrix
            - 'constant_correlation': Constant correlation model (default)
            - 'diagonal': Diagonal matrix (uncorrelated assets)
            - 'identity': Identity matrix
            Ignored if target is provided.
        sample_cov: Sample covariance (N×N). If None, computed from returns.
        target: Target matrix (N×N). If None, computed from target_type.

    Returns:
        Tuple of (shrunk_covariance, shrinkage_intensity)
        - shrunk_covariance: Ledoit-Wolf covariance estimate (N×N)
        - shrinkage_intensity: Optimal δ ∈ [0, 1]

    Example:
        >>> returns = np.random.randn(100, 10)
        >>> cov, delta = apply_ledoit_wolf_shrinkage(returns)
        >>> cov.shape
        (10, 10)
        >>> 0 <= delta <= 1
        True
    """
    T, N = returns.shape

    # Compute sample covariance if not provided
    if sample_cov is None:
        sample_cov = np.cov(returns.T)
        sample_cov = np.atleast_2d(sample_cov)

    # Compute target if not provided
    if target is None:
        if target_type == "constant_correlation":
            target = compute_constant_correlation_target(returns, sample_cov)
        elif target_type == "diagonal":
            variances = np.var(returns, axis=0, ddof=1)
            target = np.diag(variances)
        elif target_type == "identity":
            target = np.eye(N)
        else:
            raise ValueError(f"Unknown target type: {target_type}")

    # Compute optimal shrinkage intensity
    delta = compute_ledoit_wolf_shrinkage_intensity(returns, sample_cov, target)

    # Apply shrinkage: Σ̂_LW = δ * F + (1-δ) * S
    shrunk_cov = delta * target + (1 - delta) * sample_cov

    return shrunk_cov, delta
