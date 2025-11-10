"""
Risk Estimation Module

Implements covariance estimation methods for portfolio optimization.

Based on 2025 research priorities:
1. Ledoit-Wolf shrinkage (industry standard, >5000 citations)
2. Sample covariance (baseline for comparison)
3. Future: Nodewise regression, 3-factor PCA

Modules:
- Covariance: Covariance matrix estimators
- Base: Abstract base classes

Usage:
    from Risk.Covariance import LedoitWolfShrinkage, SampleCovariance
    from Risk.Covariance import compare_estimators

    # Fit estimators
    lw = LedoitWolfShrinkage()
    cov_matrix = lw.fit(returns)

    # Compare methods
    estimators = {
        'Sample': SampleCovariance(),
        'Ledoit-Wolf': LedoitWolfShrinkage(),
    }
    results = compare_estimators(estimators, returns)
"""

__version__ = "0.1.0"
