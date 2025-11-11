# ABOUTME: Risk estimation module for portfolio optimization
# ABOUTME: Implements covariance estimators (Ledoit-Wolf shrinkage, sample covariance) for mean-variance optimization
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
    # Direct imports (backward compatible)
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

    # Factory pattern (new)
    from Risk import risk_model_factory

    # Create models by name
    model = risk_model_factory.create('ledoit_wolf')
    model = risk_model_factory.create('sample')
    model = risk_model_factory.create('constant_correlation')
    model = risk_model_factory.create('diagonal')
    model = risk_model_factory.create('identity')

    # List available models
    models = risk_model_factory.list_models()
"""

# Import all covariance estimators
from Risk.Covariance import (
    SampleCovariance,
    LedoitWolfShrinkage,
    ConstantCorrelationCovariance,
    DiagonalCovariance,
    IdentityCovariance,
    compare_estimators,
)

# Import factory
from Risk.risk_model_factory import RiskModelFactory

# Create default factory instance and pre-register all models
risk_model_factory = RiskModelFactory()
risk_model_factory.register("sample", SampleCovariance)
risk_model_factory.register("ledoit_wolf", LedoitWolfShrinkage)
risk_model_factory.register("constant_correlation", ConstantCorrelationCovariance)
risk_model_factory.register("diagonal", DiagonalCovariance)
risk_model_factory.register("identity", IdentityCovariance)

__version__ = "0.1.0"

__all__ = [
    # Covariance estimators (backward compatible)
    "SampleCovariance",
    "LedoitWolfShrinkage",
    "ConstantCorrelationCovariance",
    "DiagonalCovariance",
    "IdentityCovariance",
    "compare_estimators",
    # Factory
    "RiskModelFactory",
    "risk_model_factory",
]
