# ABOUTME: Portfolio risk metrics for concentration, leverage, and diversification
# ABOUTME: Implements HHI, Leverage, and RDI from Paper 1 (Equations 7-9)
"""
Portfolio Risk Metrics

Implements three key risk metrics from Paper 1 (Equations 7-9, page 4):

1. Herfindahl-Hirschman Index (HHI):
   - Measures portfolio concentration
   - HHI(w) = Σ w_i²
   - Range: [1/p, 1] where p is number of assets
   - Lower is better (more diversified)
   - 1/p = perfectly diversified (equal weight)
   - 1 = fully concentrated (single asset)

2. Leverage:
   - Measures short-selling magnitude
   - L(w) = Σ |w_i|
   - 1.0 = long-only
   - 2.0 = fully hedged long-short (equal long/short)
   - >2.0 = leveraged

3. Risk Diversification Index (RDI):
   - Measures risk diversification
   - RDI(w) = √(w^T·Σ·w) / (w^T·√diag(Σ))
   - Portfolio risk / average individual risk
   - Lower is better (more diversified)
   - For uncorrelated equal-variance assets: RDI = 1/√p

These metrics are used in sector-based risk models to evaluate
portfolio construction and risk allocation.
"""

import numpy as np


def herfindahl_hirschman_index(weights: np.ndarray) -> float:
    """
    Calculate Herfindahl-Hirschman Index (concentration metric).

    HHI measures portfolio concentration by summing squared weights.
    Lower values indicate better diversification.

    Formula (Paper 1, Equation 7):
        HHI(w) = Σ(i=1 to p) w_i²

    Properties:
    - Range: [1/p, 1] where p = number of assets
    - 1/p = perfectly diversified (equal weight)
    - 1 = fully concentrated (single asset)
    - Works with both positive and negative weights

    Args:
        weights: Portfolio weights (can contain negative values for shorts)

    Returns:
        HHI ∈ [1/p, 1]

    Example:
        >>> # Equal weights (most diversified)
        >>> w = np.array([0.25, 0.25, 0.25, 0.25])
        >>> hhi = herfindahl_hirschman_index(w)
        >>> print(f"{hhi:.3f}")  # 0.250 = 1/4
        0.250

        >>> # Single asset (most concentrated)
        >>> w = np.array([1.0, 0.0, 0.0, 0.0])
        >>> hhi = herfindahl_hirschman_index(w)
        >>> print(f"{hhi:.3f}")  # 1.000
        1.000
    """
    return np.sum(weights ** 2)


def leverage(weights: np.ndarray) -> float:
    """
    Calculate portfolio leverage (short-selling magnitude).

    Leverage measures the total absolute exposure, indicating
    the degree of short-selling and leverage.

    Formula (Paper 1, Equation 8):
        L(w) = Σ(i=1 to p) |w_i|

    Interpretation:
    - 1.0 = long-only portfolio
    - 2.0 = fully hedged long-short (50% long, 50% short)
    - >2.0 = leveraged portfolio

    Args:
        weights: Portfolio weights (can contain negative values for shorts)

    Returns:
        L ≥ 1.0

    Example:
        >>> # Long-only
        >>> w = np.array([0.6, 0.4])
        >>> lev = leverage(w)
        >>> print(f"{lev:.1f}")  # 1.0
        1.0

        >>> # Long-short
        >>> w = np.array([0.5, 0.5, -0.3, -0.7])
        >>> lev = leverage(w)
        >>> print(f"{lev:.1f}")  # 2.0
        2.0
    """
    return np.sum(np.abs(weights))


def risk_diversification_index(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
) -> float:
    """
    Calculate Risk Diversification Index.

    RDI measures how much diversification benefit the portfolio
    achieves compared to holding assets individually.

    Formula (Paper 1, Equation 9):
        RDI(w) = √(w^T·Σ·w) / (w^T·√diag(Σ))

    Where:
    - Numerator: Portfolio risk (standard deviation)
    - Denominator: Weighted average of individual asset risks

    Properties:
    - Lower is better (more diversified)
    - For uncorrelated equal-variance assets with equal weights: RDI = 1/√p
    - For perfectly correlated assets: RDI = 1 (no diversification)
    - RDI < 1 indicates diversification benefit

    Args:
        weights: Portfolio weights (can contain negative values)
        cov_matrix: Covariance matrix (N×N)

    Returns:
        RDI > 0

    Example:
        >>> # Uncorrelated assets, equal weights
        >>> w = np.array([0.5, 0.5])
        >>> cov = np.eye(2)
        >>> rdi = risk_diversification_index(w, cov)
        >>> print(f"{rdi:.3f}")  # 0.707 = 1/√2
        0.707

        >>> # Perfectly correlated assets
        >>> cov = np.ones((2, 2))
        >>> rdi = risk_diversification_index(w, cov)
        >>> print(f"{rdi:.3f}")  # 1.000 (no diversification)
        1.000
    """
    # Portfolio variance: w^T Σ w
    portfolio_variance = weights @ cov_matrix @ weights

    # Portfolio standard deviation
    portfolio_std = np.sqrt(portfolio_variance)

    # Individual asset standard deviations
    individual_stds = np.sqrt(np.diag(cov_matrix))

    # Weighted average of individual risks
    avg_individual_risk = weights @ individual_stds

    # RDI = portfolio risk / average individual risk
    rdi = portfolio_std / avg_individual_risk

    return rdi
