# ABOUTME: Portfolio optimization module for backtesting
# ABOUTME: Implements mean-variance optimizer (Markowitz 1952) to convert alpha signals → portfolio weights
"""
Portfolio Optimization Module

Converts alpha signals into optimal portfolio weights using
modern portfolio theory (Markowitz 1952, Grinold-Kahn 1999).

Modules:
- MeanVarianceOptimizer: Markowitz mean-variance optimizer
- CVaRMeanVarianceOptimizer: CVaR-constrained optimizer
- ClusterAwareMeanVarianceOptimizer: Cluster-aware optimizer
- Base: Abstract base classes

Usage:
    from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
    from Signals.Futures.CarrySignal import CarrySignal
    from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage

    # Generate signals
    signal = CarrySignal()
    alphas = signal.generate_batch(contracts, market_data, as_of)

    # Estimate covariance
    lw = LedoitWolfShrinkage()
    cov_matrix = lw.fit(returns)

    # Optimize portfolio
    optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
    weights = optimizer.optimize(alphas, cov_matrix)

Features:
- Mean-variance optimization with quadratic programming
- Budget constraint (sum of weights)
- Leverage constraint (sum of |weights|)
- Position limits

Potential Extensions:
- Transaction costs (proportional + quadratic)
- DV01 constraints (fixed income risk limits)
- Cardinality constraints (L0 penalty)
- Turnover constraints
"""

__version__ = "0.1.0"
