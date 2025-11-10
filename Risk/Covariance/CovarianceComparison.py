# ABOUTME: Covariance estimator comparison and benchmarking utilities
# ABOUTME: Compares estimators on condition number, portfolio variance, out-of-sample performance, and computation time
"""
Covariance Estimator Comparison Utilities

Provides tools to compare multiple covariance estimators:
- Condition number (stability)
- Frobenius norm (magnitude)
- Portfolio variance (practical impact)
- Computation time (efficiency)

Use to benchmark Ledoit-Wolf vs Sample vs other methods.
"""

import time
from typing import Dict
import numpy as np
import pandas as pd

from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator


def compare_estimators(
    estimators: Dict[str, BaseCovarianceEstimator],
    returns: pd.DataFrame,
    portfolio_weights: np.ndarray = None,
) -> Dict[str, Dict[str, float]]:
    """
    Compare multiple covariance estimators.

    Args:
        estimators: Dictionary mapping name → estimator instance
        returns: DataFrame of returns (T×N)
        portfolio_weights: Optional portfolio weights for variance calculation
            If None, uses equal weights

    Returns:
        Dictionary mapping estimator name → metrics:
            - condition_number: Matrix stability
            - frobenius_norm: Overall magnitude
            - portfolio_variance: w'Σw (if weights provided)
            - fit_time: Computation time (seconds)

    Example:
        >>> estimators = {
        ...     'Sample': SampleCovariance(),
        ...     'Ledoit-Wolf': LedoitWolfShrinkage(),
        ... }
        >>> results = compare_estimators(estimators, returns)
        >>> print(f"Sample condition: {results['Sample']['condition_number']:.1f}")
        >>> print(f"LW condition: {results['Ledoit-Wolf']['condition_number']:.1f}")
    """
    N = returns.shape[1]

    # Default: equal weights
    if portfolio_weights is None:
        portfolio_weights = np.ones(N) / N

    results = {}

    for name, estimator in estimators.items():
        # Time the fit
        start = time.time()
        cov_matrix = estimator.fit(returns)
        fit_time = time.time() - start

        # Calculate metrics
        metrics = {}

        # Condition number (stability)
        metrics['condition_number'] = float(np.linalg.cond(cov_matrix))

        # Frobenius norm (magnitude)
        metrics['frobenius_norm'] = float(np.linalg.norm(cov_matrix, 'fro'))

        # Portfolio variance
        port_var = portfolio_weights @ cov_matrix @ portfolio_weights
        metrics['portfolio_variance'] = float(port_var)

        # Computation time
        metrics['fit_time'] = fit_time

        # Smallest eigenvalue (positive definiteness)
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        metrics['min_eigenvalue'] = float(np.min(eigenvalues))

        # Largest eigenvalue
        metrics['max_eigenvalue'] = float(np.max(eigenvalues))

        # Determinant (singularity check)
        metrics['determinant'] = float(np.linalg.det(cov_matrix))

        # Store shrinkage intensity if available
        if hasattr(estimator, 'shrinkage_intensity'):
            if estimator.shrinkage_intensity is not None:
                metrics['shrinkage_intensity'] = float(estimator.shrinkage_intensity)

        results[name] = metrics

    return results


def print_comparison(results: Dict[str, Dict[str, float]]) -> None:
    """
    Print comparison results in a readable table format.

    Args:
        results: Output from compare_estimators()
    """
    print("\nCovariance Estimator Comparison")
    print("=" * 80)

    # Header
    print(f"{'Estimator':<20} {'CondNum':>10} {'MinEig':>10} {'PortVar':>10} {'Time(s)':>10}")
    print("-" * 80)

    # Each estimator
    for name, metrics in results.items():
        print(
            f"{name:<20} "
            f"{metrics['condition_number']:>10.1f} "
            f"{metrics['min_eigenvalue']:>10.4f} "
            f"{metrics['portfolio_variance']:>10.4f} "
            f"{metrics['fit_time']:>10.4f}"
        )

        # Show shrinkage intensity if available
        if 'shrinkage_intensity' in metrics:
            print(f"  → Shrinkage intensity: δ = {metrics['shrinkage_intensity']:.3f}")

    print("=" * 80)


def out_of_sample_comparison(
    estimators: Dict[str, BaseCovarianceEstimator],
    returns_in: pd.DataFrame,
    returns_out: pd.DataFrame,
    portfolio_weights: np.ndarray = None,
) -> Dict[str, Dict[str, float]]:
    """
    Compare estimators on out-of-sample performance.

    This is the gold standard for evaluating covariance estimators:
    - Fit on in-sample data
    - Predict portfolio variance
    - Measure actual variance on out-of-sample data
    - Lower prediction error = better estimator

    Args:
        estimators: Dictionary mapping name → estimator instance
        returns_in: In-sample returns for fitting
        returns_out: Out-of-sample returns for validation
        portfolio_weights: Portfolio weights (default: equal)

    Returns:
        Dictionary with metrics:
            - predicted_variance: In-sample prediction
            - actual_variance: Out-of-sample realization
            - prediction_error: |predicted - actual|
            - relative_error: error / actual
    """
    N = returns_in.shape[1]

    # Default: equal weights
    if portfolio_weights is None:
        portfolio_weights = np.ones(N) / N

    results = {}

    # Actual out-of-sample variance
    portfolio_returns_out = returns_out @ portfolio_weights
    actual_variance = np.var(portfolio_returns_out, ddof=1)

    for name, estimator in estimators.items():
        # Fit on in-sample data
        cov_matrix = estimator.fit(returns_in)

        # Predicted variance
        predicted_variance = portfolio_weights @ cov_matrix @ portfolio_weights

        # Prediction error
        error = abs(predicted_variance - actual_variance)
        relative_error = error / actual_variance if actual_variance > 0 else np.inf

        results[name] = {
            'predicted_variance': float(predicted_variance),
            'actual_variance': float(actual_variance),
            'prediction_error': float(error),
            'relative_error': float(relative_error),
        }

    return results
