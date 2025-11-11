# ABOUTME: Mean-variance portfolio optimizer (Markowitz 1952)
# ABOUTME: Converts alpha signals and covariance matrix into optimal portfolio weights using quadratic programming
"""
Mean-Variance Portfolio Optimizer

Implements the classic Markowitz (1952) mean-variance optimization:
    maximize: expected_return - λ * variance
    subject to: budget, leverage, and position constraints

Formula:
    max_w { α'w - λ/2 × w'Σw }

Where:
- α = expected returns (alpha signals)
- Σ = covariance matrix
- λ = risk aversion parameter
- w = portfolio weights

From Grinold-Kahn (1999):
- Optimal portfolio maximizes Information Ratio: IR = IC × √BR
- Transfer coefficient measures implementation efficiency
- Constraints reduce transfer coefficient (TC < 1.0)

Method:
- Uses scipy.optimize.minimize with SLSQP (Sequential Least Squares)
- Handles linear equality constraints (budget)
- Handles linear inequality constraints (bounds, leverage)
- Handles nonlinear constraints (if needed in maximal version)

Minimal Implementation (Phase 1):
- Mean-variance objective
- Budget constraint: sum(w) = 1.0
- Long-only bounds: w_i >= 0
- Position limits: w_i <= max_weight
- Leverage limit: sum(|w_i|) <= L

Maximal Additions (Phase 2):
- Transaction costs (proportional + quadratic)
- DV01 constraints (fixed income)
- Cardinality constraints (L0 penalty)
- Turnover constraints
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Optional, Tuple

from Optimizer.Base.BaseOptimizer import BaseOptimizer


class MeanVarianceOptimizer(BaseOptimizer):
    """
    Mean-variance optimizer using quadratic programming.

    Converts alpha signals into optimal portfolio weights that
    maximize expected return while controlling variance.

    Attributes:
        risk_aversion (float): Risk aversion parameter λ
        long_only (bool): If True, no short positions
        leverage_limit (float): Maximum sum of |weights|
        position_limit (float): Maximum weight per asset
        allow_cash (bool): If True, allow sum(weights) < 1.0
    """

    def __init__(
        self,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        leverage_limit: Optional[float] = None,
        position_limit: Optional[float] = None,
        allow_cash: bool = False,
    ):
        """
        Initialize mean-variance optimizer.

        Args:
            risk_aversion: Risk aversion λ (higher = more conservative)
            long_only: If True, only allow positive weights
            leverage_limit: Maximum sum of |weights| (e.g., 2.0 for 2x leverage)
            position_limit: Maximum weight per asset (e.g., 0.4 for 40%)
            allow_cash: If True, allow sum(weights) < 1.0 (hold cash when signals poor)
        """
        super().__init__(risk_aversion=risk_aversion, long_only=long_only)
        self.leverage_limit = leverage_limit
        self.position_limit = position_limit
        self.allow_cash = allow_cash

    def optimize(
        self,
        alphas: pd.Series,
        covariance: pd.DataFrame,
    ) -> pd.Series:
        """
        Optimize portfolio weights.

        Args:
            alphas: Expected returns or alpha signals (z-scores)
            covariance: Covariance matrix (N×N)

        Returns:
            Optimal portfolio weights (asset → weight)

        Example:
            >>> alphas = pd.Series([1.0, 0.5, -0.5], index=['A', 'B', 'C'])
            >>> cov = pd.DataFrame(...)
            >>> optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
            >>> weights = optimizer.optimize(alphas, cov)
            >>> print(weights)
            A    0.50
            B    0.30
            C    0.20
        """
        # Validate inputs
        self._validate_inputs(alphas, covariance)

        # Align alphas and covariance
        assets = list(alphas.index)
        alphas_aligned = alphas[assets].values
        cov_matrix = covariance.loc[assets, assets].values

        # Get dimensions
        n_assets = len(assets)

        # Initial guess: equal weights or zero
        if self.long_only:
            x0 = np.ones(n_assets) / n_assets
        else:
            x0 = np.zeros(n_assets)

        # Build constraints
        constraints = self._build_constraints(n_assets)

        # Build bounds
        bounds = self._build_bounds(n_assets)

        # Solve optimization
        result = minimize(
            fun=self._objective,
            x0=x0,
            args=(alphas_aligned, cov_matrix),
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000, 'ftol': 1e-9},
        )

        if not result.success:
            # Fallback: return equal weights or zero weights
            if self.long_only:
                weights_array = np.ones(n_assets) / n_assets
            else:
                weights_array = np.zeros(n_assets)
        else:
            weights_array = result.x

        # Convert to Series
        self.weights_ = pd.Series(weights_array, index=assets)

        return self.weights_

    def _objective(
        self,
        weights: np.ndarray,
        alphas: np.ndarray,
        cov_matrix: np.ndarray,
    ) -> float:
        """
        Mean-variance objective function (to minimize).

        Formula: -α'w + λ/2 × w'Σw

        We minimize this, which is equivalent to maximizing:
            α'w - λ/2 × w'Σw

        Args:
            weights: Portfolio weights (N,)
            alphas: Expected returns (N,)
            cov_matrix: Covariance matrix (N×N)

        Returns:
            Objective value (scalar)
        """
        # Expected return: α'w
        expected_return = np.dot(alphas, weights)

        # Variance: w'Σw
        variance = weights @ cov_matrix @ weights

        # Mean-variance objective (minimize negative)
        obj = -expected_return + 0.5 * self.risk_aversion * variance

        return obj

    def _build_constraints(self, n_assets: int) -> list:
        """
        Build optimization constraints.

        Args:
            n_assets: Number of assets

        Returns:
            List of constraint dictionaries for scipy.optimize
        """
        constraints = []

        # Budget constraint: sum(weights) = 1.0 (or <= 1.0 if allow_cash)
        if self.allow_cash:
            # sum(weights) <= 1.0
            constraints.append({
                'type': 'ineq',
                'fun': lambda w: 1.0 - np.sum(w),  # 1.0 - sum(w) >= 0
            })
        else:
            # sum(weights) = 1.0
            constraints.append({
                'type': 'eq',
                'fun': lambda w: np.sum(w) - 1.0,  # sum(w) - 1.0 = 0
            })

        # Leverage constraint: sum(|weights|) <= L
        if self.leverage_limit is not None:
            constraints.append({
                'type': 'ineq',
                'fun': lambda w: self.leverage_limit - np.sum(np.abs(w)),
            })

        return constraints

    def _build_bounds(self, n_assets: int) -> list:
        """
        Build optimization bounds.

        Args:
            n_assets: Number of assets

        Returns:
            List of (lower, upper) tuples for each asset
        """
        bounds = []

        for i in range(n_assets):
            if self.long_only:
                # Long-only: 0 <= w_i <= position_limit
                lower = 0.0
            else:
                # Long-short: -position_limit <= w_i <= position_limit
                if self.position_limit is not None:
                    lower = -self.position_limit
                else:
                    lower = None  # No lower bound

            # Upper bound
            if self.position_limit is not None:
                upper = self.position_limit
            else:
                upper = 1.0 if self.long_only else None

            bounds.append((lower, upper))

        return bounds

    def portfolio_statistics(
        self,
        alphas: pd.Series,
        covariance: pd.DataFrame,
        weights: Optional[pd.Series] = None,
    ) -> dict:
        """
        Calculate portfolio statistics for given weights.

        Args:
            alphas: Expected returns
            covariance: Covariance matrix
            weights: Portfolio weights (if None, uses self.weights_)

        Returns:
            Dictionary with:
                - expected_return: Portfolio expected return
                - variance: Portfolio variance
                - volatility: Portfolio volatility (std dev)
                - sharpe_ratio: Return / volatility
                - leverage: Sum of |weights|
                - n_positions: Number of non-zero positions
        """
        if weights is None:
            weights = self.get_weights()

        # Align
        assets = list(weights.index)
        w = weights[assets].values
        alpha_vec = alphas[assets].values
        cov = covariance.loc[assets, assets].values

        # Expected return
        expected_return = np.dot(alpha_vec, w)

        # Variance and volatility
        variance = w @ cov @ w
        volatility = np.sqrt(variance)

        # Sharpe ratio (assuming zero risk-free rate)
        sharpe_ratio = expected_return / volatility if volatility > 0 else 0.0

        # Leverage
        leverage = np.sum(np.abs(w))

        # Number of positions (> 1%)
        n_positions = np.sum(np.abs(w) > 0.01)

        return {
            'expected_return': float(expected_return),
            'variance': float(variance),
            'volatility': float(volatility),
            'sharpe_ratio': float(sharpe_ratio),
            'leverage': float(leverage),
            'n_positions': int(n_positions),
        }

    def __repr__(self) -> str:
        return (
            f"MeanVarianceOptimizer("
            f"risk_aversion={self.risk_aversion}, "
            f"long_only={self.long_only}, "
            f"leverage_limit={self.leverage_limit}, "
            f"position_limit={self.position_limit})"
        )
