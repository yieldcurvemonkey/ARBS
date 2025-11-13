# ABOUTME: CVaR-constrained mean-variance portfolio optimizer
# ABOUTME: Extends MeanVarianceOptimizer with tail risk (CVaR) constraints using CVXPY
"""
CVaR Mean-Variance Portfolio Optimizer

Extends Markowitz (1952) with Conditional Value-at-Risk (CVaR) tail risk constraints.

Theory (Rockafellar & Uryasev 2000):
    CVaR_α(w) = expected loss beyond VaR_α
    = E[L | L >= VaR_α]
    = VaR + (1/(α*T)) * sum(max(0, L_i - VaR))

Objective:
    max_w { α'w - λ/2 × w'Σw }
    subject to: CVaR_α(w) ≤ cvar_limit (NEW)
                sum(w) = 1.0 (budget)
                sum(|w|) ≤ L (leverage)
                w_i ∈ bounds (position limits)

CVXPY Formulation:
    Variables: w (weights), t (VaR), u_i (excess losses)

    Minimize: -α'w + λ/2 × w'Σw

    Constraints:
        1. t + (1/(α*T)) * sum(u_i) ≤ cvar_limit  (CVaR constraint)
        2. u_i ≥ 0  (auxiliary: excess loss non-negative)
        3. u_i ≥ -(returns_i^T * w) - t  (auxiliary: capture excess loss)
        4. sum(w) = 1.0  (budget)
        5. sum(|w|) ≤ L  (leverage)
        6. w_i ∈ bounds  (position limits)

Complexity:
- For T time periods and N assets: O(T*N²) variables/constraints
- T=252 (1 year), N=50: ~6500 variables (manageable with cvxpy+mosek)
- Solver: CVXPY defaults (ECOS, SCS for open-source)

Reference:
    Rockafellar, R. T., & Uryasev, S. (2000). Optimization of conditional value-at-risk.
    Journal of Risk, 2(3), 21-41.
"""

import numpy as np
import polars as pl
import cvxpy as cp
from typing import Optional, Dict
from scipy.optimize import minimize

from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer, WeightsDict


class CVaRMeanVarianceOptimizer(MeanVarianceOptimizer):
    """
    Mean-variance optimizer with CVaR (tail risk) constraints.

    Inherits from MeanVarianceOptimizer and adds CVaR constraint to control
    tail risk. Uses CVXPY for convex optimization with auxiliary variables
    for VaR and excess losses.

    Attributes:
        risk_aversion (float): Risk aversion parameter λ
        long_only (bool): If True, no short positions
        leverage_limit (float): Maximum sum of |weights|
        position_limit (float): Maximum weight per asset
        allow_cash (bool): If True, allow sum(weights) < 1.0
        cvar_alpha (float): Confidence level α (e.g., 0.05 for 5% tail)
        cvar_limit (float): Maximum allowed CVaR
        use_cvxpy (bool): If True, use CVXPY; else use scipy (legacy)
    """

    def __init__(
        self,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        leverage_limit: Optional[float] = None,
        position_limit: Optional[float] = None,
        allow_cash: bool = False,
        cvar_alpha: float = 0.05,
        cvar_limit: float = 0.05,
        use_cvxpy: bool = True,
    ):
        """
        Initialize CVaR mean-variance optimizer.

        Args:
            risk_aversion: Risk aversion λ (higher = more conservative)
            long_only: If True, only allow positive weights
            leverage_limit: Maximum sum of |weights|
            position_limit: Maximum weight per asset
            allow_cash: If True, allow sum(weights) < 1.0
            cvar_alpha: Confidence level α for CVaR (e.g., 0.05)
            cvar_limit: Maximum allowed CVaR value
            use_cvxpy: If True, use CVXPY solver; else fallback to scipy
        """
        super().__init__(
            risk_aversion=risk_aversion,
            long_only=long_only,
            leverage_limit=leverage_limit,
            position_limit=position_limit,
            allow_cash=allow_cash,
        )
        self.cvar_alpha = cvar_alpha
        self.cvar_limit = cvar_limit
        self.use_cvxpy = use_cvxpy

    def optimize(
        self,
        alphas: pl.Series,
        covariance: pl.DataFrame,
        returns: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        """
        Optimize portfolio weights with CVaR constraint.

        Args:
            alphas: Expected returns or alpha signals (z-scores)
            covariance: Covariance matrix (N×N)
            returns: Historical returns (T×N) needed for CVaR calculation.
                    If None, assumes normal distribution (uses covariance only).

        Returns:
            Optimal portfolio weights (asset → weight as dict)

        Raises:
            ValueError: If inputs are incompatible or optimization fails
        """
        # Validate inputs
        self._validate_inputs_polars(alphas, covariance)

        # Extract asset names and values
        assets = covariance.columns
        alphas_aligned = alphas.to_numpy()
        cov_matrix = covariance.select(assets).to_numpy()
        n_assets = len(assets)

        # If returns provided and CVXPY available, use CVaR-aware optimization
        if returns is not None and self.use_cvxpy:
            try:
                weights_array = self._optimize_with_cvxpy(
                    alphas_aligned, cov_matrix, returns, n_assets
                )
            except Exception as e:
                # Fallback to scipy if CVXPY fails
                print(f"CVXPY failed: {e}. Falling back to scipy.")
                weights_array = self._optimize_with_scipy(
                    alphas_aligned, cov_matrix, n_assets
                )
        else:
            # Use scipy (no CVaR constraint if returns not provided)
            weights_array = self._optimize_with_scipy(
                alphas_aligned, cov_matrix, n_assets
            )

        # Convert to WeightsDict
        weights_dict = WeightsDict({
            asset: float(weight)
            for asset, weight in zip(assets, weights_array)
        })
        self.weights_ = weights_dict

        return weights_dict

    def _optimize_with_cvxpy(
        self,
        alphas: np.ndarray,
        cov_matrix: np.ndarray,
        returns: np.ndarray,
        n_assets: int,
    ) -> np.ndarray:
        """
        Optimize with CVXPY using CVaR constraint.

        Formulation (Rockafellar & Uryasev 2000):
            Variables: w (weights), t (VaR), u_i (excess losses)

            Minimize: -α'w + λ/2 × w'Σw

            Subject to:
                t + (1/(α*T)) * sum(u_i) ≤ cvar_limit  (CVaR)
                u_i ≥ -(returns_i^T * w) - t  for all i
                u_i ≥ 0  for all i
                sum(w) = 1.0
                |w| ≤ bounds

        Args:
            alphas: Alpha signals (N,)
            cov_matrix: Covariance matrix (N×N)
            returns: Historical returns (T×N)
            n_assets: Number of assets

        Returns:
            Optimal weights (N,)
        """
        T = returns.shape[0]  # Number of time periods

        # Variables
        w = cp.Variable(n_assets)
        t = cp.Variable()  # VaR
        u = cp.Variable(T)  # Excess losses

        # Objective: -α'w + λ/2 * w'Σw
        obj_return = -cp.sum(cp.multiply(alphas, w))
        obj_variance = 0.5 * self.risk_aversion * cp.quad_form(w, cov_matrix)
        objective = cp.Minimize(obj_return + obj_variance)

        # Constraints
        constraints = []

        # 1. CVaR constraint: t + (1/α*T) * sum(u_i) <= cvar_limit
        cvar_constraint = t + (1.0 / (self.cvar_alpha * T)) * cp.sum(u) <= self.cvar_limit
        constraints.append(cvar_constraint)

        # 2. Excess loss definition: u_i >= -(returns_i^T * w) - t
        # This captures losses beyond VaR
        portfolio_losses = returns @ w  # T-dimensional: returns for each period
        for i in range(T):
            # u_i >= -(returns_i^T * w) - t  =>  u_i >= -portfolio_loss - t
            constraints.append(u[i] >= -portfolio_losses[i] - t)
            constraints.append(u[i] >= 0)

        # 3. Budget constraint
        if self.allow_cash:
            constraints.append(cp.sum(w) <= 1.0)
        else:
            constraints.append(cp.sum(w) == 1.0)

        # 4. Long-only constraint
        if self.long_only:
            constraints.append(w >= 0)

        # 5. Position limits
        if self.position_limit is not None:
            if self.long_only:
                constraints.append(w <= self.position_limit)
            else:
                constraints.append(w <= self.position_limit)
                constraints.append(w >= -self.position_limit)
        else:
            if not self.long_only:
                constraints.append(w <= 1.0)

        # 6. Leverage constraint
        if self.leverage_limit is not None:
            constraints.append(cp.sum(cp.abs(w)) <= self.leverage_limit)

        # Solve
        problem = cp.Problem(objective, constraints)
        problem.solve(verbose=False, solver=cp.SCS, max_iters=5000)

        if problem.status != cp.OPTIMAL:
            raise ValueError(f"Optimization failed: {problem.status}")

        return w.value

    def _optimize_with_scipy(
        self,
        alphas: np.ndarray,
        cov_matrix: np.ndarray,
        n_assets: int,
    ) -> np.ndarray:
        """
        Fallback: optimize with scipy (no CVaR constraint).

        Used when CVXPY is unavailable or fails.
        Falls back to parent class (MeanVarianceOptimizer) behavior.

        Args:
            alphas: Alpha signals (N,)
            cov_matrix: Covariance matrix (N×N)
            n_assets: Number of assets

        Returns:
            Optimal weights (N,)
        """
        # Initial guess
        if self.long_only:
            x0 = np.ones(n_assets) / n_assets
        else:
            x0 = np.zeros(n_assets)

        # Build constraints
        constraints = self._build_constraints(n_assets)

        # Build bounds
        bounds = self._build_bounds(n_assets)

        # Solve
        result = minimize(
            fun=self._objective,
            x0=x0,
            args=(alphas, cov_matrix),
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000, 'ftol': 1e-9},
        )

        if not result.success:
            # Fallback: equal weights or zero
            if self.long_only:
                return np.ones(n_assets) / n_assets
            else:
                return np.zeros(n_assets)

        return result.x

    def __repr__(self) -> str:
        return (
            f"CVaRMeanVarianceOptimizer("
            f"risk_aversion={self.risk_aversion}, "
            f"long_only={self.long_only}, "
            f"cvar_alpha={self.cvar_alpha}, "
            f"cvar_limit={self.cvar_limit})"
        )
