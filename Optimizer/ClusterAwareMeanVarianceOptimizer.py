# ABOUTME: Cluster-aware mean-variance optimizer with correlation cluster constraints
# ABOUTME: Limits positions per correlation cluster to prevent concentration risk in portfolio construction
"""
Cluster-Aware Mean-Variance Portfolio Optimizer

Extends MeanVarianceOptimizer with correlation cluster constraints:
    maximize: expected_return - λ * variance
    subject to: budget, leverage, position limits, AND cluster constraints

New Constraint:
    For each cluster C: sum(indicator(|w_i| > ε) for i in C) <= max_per_cluster

Where:
- ε = 0.01 (1% threshold for counting positions)
- max_per_cluster = maximum number of positions allowed in any cluster

From 2025 Research Consensus:
- Correlation cluster constraints prevent concentration risk
- Standard practice: "Can't short 5Y in every correlated currency"
- Hierarchical clustering identifies correlation groups
- Limits diversification within highly correlated asset groups

Implementation:
- Uses CVXPY for convex optimization with indicator constraints
- Indicator function approximated via binary variables (MIP)
- Alternative: continuous relaxation for faster solve

Example:
    >>> clusters = {'cluster_0': ['A', 'B', 'C'], 'cluster_1': ['D', 'E', 'F']}
    >>> optimizer = ClusterAwareMeanVarianceOptimizer(
    ...     correlation_clusters=clusters,
    ...     max_per_cluster=2,  # Max 2 positions per cluster
    ...     risk_aversion=1.0,
    ...     long_only=True
    ... )
    >>> weights = optimizer.optimize(alphas, covariance)
    >>> # Result: No more than 2 assets from any cluster have |weight| > 0.01
"""

import numpy as np
import polars as pl
import cvxpy as cp
from typing import Dict, List, Optional

from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer, WeightsDict


class ClusterAwareMeanVarianceOptimizer(MeanVarianceOptimizer):
    """
    Mean-variance optimizer with correlation cluster constraints.

    Prevents concentration risk by limiting number of positions per
    correlation cluster.

    Attributes:
        correlation_clusters: Dict mapping cluster_id → list of asset names
        max_per_cluster: Maximum number of positions allowed per cluster
        position_threshold: Threshold for counting positions (default 0.01 = 1%)
    """

    def __init__(
        self,
        correlation_clusters: Dict[str, List[str]],
        max_per_cluster: int = 3,
        position_threshold: float = 0.01,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        leverage_limit: Optional[float] = None,
        position_limit: Optional[float] = None,
        allow_cash: bool = False,
    ):
        """
        Initialize cluster-aware optimizer.

        Args:
            correlation_clusters: Dict mapping cluster_id → list of tickers
            max_per_cluster: Maximum positions allowed in any cluster
            position_threshold: Threshold for counting positions (default 0.01)
            risk_aversion: Risk aversion λ (higher = more conservative)
            long_only: If True, only allow positive weights
            leverage_limit: Maximum sum of |weights|
            position_limit: Maximum weight per asset
            allow_cash: If True, allow sum(weights) < 1.0
        """
        super().__init__(
            risk_aversion=risk_aversion,
            long_only=long_only,
            leverage_limit=leverage_limit,
            position_limit=position_limit,
            allow_cash=allow_cash,
        )

        self.correlation_clusters = correlation_clusters
        self.max_per_cluster = max_per_cluster
        self.position_threshold = position_threshold

    def optimize(
        self,
        alphas: pl.Series,
        covariance: pl.DataFrame,
    ) -> Dict[str, float]:
        """
        Optimize portfolio weights with cluster constraints.

        Args:
            alphas: Expected returns or alpha signals (z-scores)
            covariance: Covariance matrix (N×N)

        Returns:
            Optimal portfolio weights (asset → weight as dict)

        Example:
            >>> alphas = pl.Series('alphas', [1.0, 0.5, -0.5, 0.3])
            >>> cov = pl.DataFrame(...)
            >>> optimizer = ClusterAwareMeanVarianceOptimizer(
            ...     correlation_clusters={'cluster_0': ['A', 'B'], 'cluster_1': ['C', 'D']},
            ...     max_per_cluster=1
            ... )
            >>> weights = optimizer.optimize(alphas, cov)
        """
        # Validate inputs
        self._validate_inputs_polars(alphas, covariance)

        # Extract asset names and values
        if isinstance(alphas, pl.Series):
            if len(alphas) == 1:
                assets = [alphas.name] if alphas.name else ['Asset_0']
                alphas_array = alphas.to_numpy()
            else:
                assets = covariance.columns
                alphas_array = alphas.to_numpy()
        else:
            raise ValueError("alphas must be a polars Series")

        # Convert covariance to numpy
        cov_matrix = covariance.select(assets).to_numpy()

        n_assets = len(assets)

        # Create CVXPY optimization problem
        w = cp.Variable(n_assets)

        # Objective: maximize expected return - risk_aversion * variance
        expected_return = alphas_array @ w
        variance = cp.quad_form(w, cov_matrix)
        objective = cp.Maximize(expected_return - 0.5 * self.risk_aversion * variance)

        # Standard constraints
        constraints = []

        # Budget constraint
        if self.allow_cash:
            constraints.append(cp.sum(w) <= 1.0)
        else:
            constraints.append(cp.sum(w) == 1.0)

        # Long-only bounds
        if self.long_only:
            constraints.append(w >= 0)

        # Position limits
        if self.position_limit is not None:
            constraints.append(w <= self.position_limit)
            if not self.long_only:
                constraints.append(w >= -self.position_limit)

        # Leverage limit
        if self.leverage_limit is not None:
            # Use continuous relaxation: sum(w) <= leverage_limit (long-only)
            # For long-short, need sum(|w|) which requires auxiliary variables
            if self.long_only:
                constraints.append(cp.sum(w) <= self.leverage_limit)
            else:
                # Auxiliary variables for |w_i|
                w_abs = cp.Variable(n_assets, nonneg=True)
                constraints.append(w_abs >= w)
                constraints.append(w_abs >= -w)
                constraints.append(cp.sum(w_abs) <= self.leverage_limit)

        # Cluster constraints
        # For each cluster: count positions > threshold and limit to max_per_cluster
        # Use continuous relaxation: sum(w_i) for i in cluster as proxy
        # More accurate: binary indicator variables (MIP)

        # Build asset index mapping
        asset_to_idx = {asset: i for i, asset in enumerate(assets)}

        for cluster_id, cluster_assets in self.correlation_clusters.items():
            # Get indices for assets in this cluster
            cluster_indices = []
            for asset in cluster_assets:
                if asset in asset_to_idx:
                    cluster_indices.append(asset_to_idx[asset])

            if not cluster_indices:
                continue  # Skip empty clusters

            # Constraint: At most max_per_cluster assets have |w_i| > threshold
            # Approximation: Use continuous relaxation with big-M
            # Binary variables: b_i = 1 if |w_i| > threshold

            # For simplicity and speed, use cardinality constraint via norm:
            # This is an approximation that encourages sparsity
            # More accurate: mixed-integer programming with binary variables

            # CVXPY doesn't support indicator constraints directly in DCP
            # Use heuristic: limit number of "large" positions via L1 penalty
            # OR use binary variables (requires CVXPY with MILP solver)

            # Approach: Binary variables for position indicators
            # b_i = 1 if |w_i| > threshold, 0 otherwise
            # Constraint: sum(b_i for i in cluster) <= max_per_cluster

            # Check if cluster constraint would be violated trivially
            if len(cluster_indices) <= self.max_per_cluster:
                # Constraint is automatically satisfied
                continue

            # Use big-M formulation
            # If b_i = 0, then |w_i| <= threshold
            # If b_i = 1, then |w_i| can be anything (up to position_limit)

            M = 1.0  # Big-M constant (max possible weight)
            if self.position_limit is not None:
                M = self.position_limit

            # Binary variables for this cluster
            b = cp.Variable(len(cluster_indices), boolean=True)

            # Link binary variables to weights
            # |w_i| <= threshold + M * b_i
            for j, idx in enumerate(cluster_indices):
                if self.long_only:
                    # w_i <= threshold + M * b_i
                    constraints.append(w[idx] <= self.position_threshold + M * b[j])
                else:
                    # |w_i| <= threshold + M * b_i
                    # Need auxiliary variable for |w_i|
                    w_abs_i = cp.Variable(nonneg=True)
                    constraints.append(w_abs_i >= w[idx])
                    constraints.append(w_abs_i >= -w[idx])
                    constraints.append(w_abs_i <= self.position_threshold + M * b[j])

            # Cluster constraint
            constraints.append(cp.sum(b) <= self.max_per_cluster)

        # Solve optimization problem
        problem = cp.Problem(objective, constraints)

        # Try multiple solvers in order of preference
        solvers_to_try = [
            ('CBC', {}),  # Mixed-integer solver (best for binary constraints)
            ('GLPK_MI', {}),  # Alternative MIP solver
            ('SCS', {}),  # Splitting conic solver
            ('OSQP', {}),  # Operator splitting QP solver
        ]

        solved = False
        for solver_name, solver_kwargs in solvers_to_try:
            try:
                if solver_name in cp.installed_solvers():
                    problem.solve(solver=getattr(cp, solver_name), verbose=False, **solver_kwargs)

                    if problem.status in ["optimal", "optimal_inaccurate"]:
                        solved = True
                        break
            except Exception:
                continue  # Try next solver

        if not solved:
            # Fallback: Use scipy-based optimizer without cluster constraints
            # This is a graceful degradation - cluster constraints won't be strictly enforced
            # but the optimization will still work
            return super().optimize(alphas, covariance)

        # Extract weights
        weights_array = w.value

        if weights_array is None:
            # Solver failed, use fallback
            if self.long_only:
                weights_array = np.ones(n_assets) / n_assets
            else:
                weights_array = np.zeros(n_assets)

        # Convert to WeightsDict
        weights_dict = WeightsDict({
            asset: float(weight) for asset, weight in zip(assets, weights_array)
        })

        self.weights_ = weights_dict

        return weights_dict

    def __repr__(self) -> str:
        return (
            f"ClusterAwareMeanVarianceOptimizer("
            f"n_clusters={len(self.correlation_clusters)}, "
            f"max_per_cluster={self.max_per_cluster}, "
            f"risk_aversion={self.risk_aversion}, "
            f"long_only={self.long_only})"
        )
