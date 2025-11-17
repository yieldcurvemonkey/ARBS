# ABOUTME: Test utility functions for reducing boilerplate across test suite
# ABOUTME: Provides reusable assertions, fixtures, and parametrized test data
"""
Test Utilities

Provides reusable test helpers to eliminate boilerplate:
- Covariance matrix validation (symmetric, positive definite, invertible)
- Signal distribution validation (z-score properties)
- Component import/instantiation testing
- Common test fixtures

Usage:
    from tests.utils import assert_valid_covariance_matrix

    cov = estimator.fit(returns)
    assert_valid_covariance_matrix(cov)  # Validates all properties

Business Requirements:
- Reduce test duplication (currently 30+ boilerplate tests)
- Maintain test coverage while improving maintainability
- Standardize validation criteria across test suite
"""

import numpy as np
import pytest
from typing import Any, Callable, Dict, List, Tuple


# =============================================================================
# Covariance Matrix Validation
# =============================================================================

def assert_valid_covariance_matrix(
    cov_matrix: np.ndarray,
    tolerance: float = 1e-10,
    check_symmetric: bool = True,
    check_positive_semidefinite: bool = True,
    check_invertible: bool = False,
    max_condition_number: float = None,
) -> None:
    """
    Validate covariance matrix properties.

    Checks that a covariance matrix satisfies mathematical requirements:
    - Symmetric: Σ = Σᵀ
    - Positive semi-definite: all eigenvalues ≥ 0
    - Optionally invertible: det(Σ) > 0
    - Optionally well-conditioned: κ(Σ) < threshold

    Args:
        cov_matrix: Covariance matrix to validate (N×N numpy array)
        tolerance: Numerical tolerance for comparisons (default: 1e-10)
        check_symmetric: Validate symmetry (default: True)
        check_positive_semidefinite: Validate PSD property (default: True)
        check_invertible: Validate invertibility (default: False)
        max_condition_number: Maximum acceptable condition number (default: None)

    Raises:
        AssertionError: If any validation fails

    Example:
        >>> from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        >>> estimator = LedoitWolfShrinkage()
        >>> cov = estimator.fit(returns)
        >>> assert_valid_covariance_matrix(cov, check_invertible=True, max_condition_number=100)
    """
    # Check shape
    assert cov_matrix.ndim == 2, f"Covariance matrix must be 2D, got {cov_matrix.ndim}D"
    assert cov_matrix.shape[0] == cov_matrix.shape[1], \
        f"Covariance matrix must be square, got {cov_matrix.shape}"

    # Check for NaN/Inf
    assert not np.any(np.isnan(cov_matrix)), "Covariance matrix contains NaN values"
    assert not np.any(np.isinf(cov_matrix)), "Covariance matrix contains Inf values"

    # Symmetry check: Σ = Σᵀ
    if check_symmetric:
        np.testing.assert_array_almost_equal(
            cov_matrix, cov_matrix.T,
            decimal=int(-np.log10(tolerance)),
            err_msg="Covariance matrix is not symmetric"
        )

    # Positive semi-definite check: all eigenvalues ≥ 0
    if check_positive_semidefinite:
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        min_eigenvalue = np.min(eigenvalues)
        assert min_eigenvalue >= -tolerance, \
            f"Covariance matrix is not positive semi-definite: min eigenvalue = {min_eigenvalue}"

    # Invertibility check: det(Σ) > 0
    if check_invertible:
        det = np.linalg.det(cov_matrix)
        assert abs(det) > tolerance, \
            f"Covariance matrix is not invertible: det = {det}"

    # Condition number check: κ(Σ) < threshold
    if max_condition_number is not None:
        cond = np.linalg.cond(cov_matrix)
        assert cond < max_condition_number, \
            f"Covariance matrix condition number {cond:.1f} exceeds threshold {max_condition_number}"


def assert_matrix_properties(
    matrix: np.ndarray,
    is_symmetric: bool = False,
    is_positive_definite: bool = False,
    is_orthogonal: bool = False,
    tolerance: float = 1e-10,
) -> None:
    """
    Validate general matrix properties.

    Args:
        matrix: Matrix to validate
        is_symmetric: Check if Σ = Σᵀ
        is_positive_definite: Check if all eigenvalues > 0
        is_orthogonal: Check if QᵀQ = I
        tolerance: Numerical tolerance

    Example:
        >>> # Validate rotation matrix
        >>> assert_matrix_properties(rotation_matrix, is_orthogonal=True)
    """
    if is_symmetric:
        np.testing.assert_array_almost_equal(
            matrix, matrix.T,
            decimal=int(-np.log10(tolerance)),
            err_msg="Matrix is not symmetric"
        )

    if is_positive_definite:
        eigenvalues = np.linalg.eigvalsh(matrix)
        min_eigenvalue = np.min(eigenvalues)
        assert min_eigenvalue > tolerance, \
            f"Matrix is not positive definite: min eigenvalue = {min_eigenvalue}"

    if is_orthogonal:
        product = matrix.T @ matrix
        identity = np.eye(matrix.shape[0])
        np.testing.assert_array_almost_equal(
            product, identity,
            decimal=int(-np.log10(tolerance)),
            err_msg="Matrix is not orthogonal (QᵀQ ≠ I)"
        )


# =============================================================================
# Signal Distribution Validation
# =============================================================================

def assert_valid_signal_distribution(
    signals: np.ndarray,
    mean_tolerance: float = 0.1,
    std_tolerance: float = 0.2,
    check_mean: bool = True,
    check_std: bool = True,
    min_samples: int = 3,
) -> None:
    """
    Validate signal standardization (z-score properties).

    Checks that signals are properly standardized:
    - Mean approximately 0
    - Standard deviation approximately 1
    - No NaN or Inf values

    Args:
        signals: Signal values (1D numpy array)
        mean_tolerance: Maximum deviation from 0 mean (default: 0.1)
        std_tolerance: Maximum deviation from 1 std (default: 0.2)
        check_mean: Validate mean ≈ 0 (default: True)
        check_std: Validate std ≈ 1 (default: True)
        min_samples: Minimum number of samples required (default: 3)

    Raises:
        AssertionError: If standardization is invalid

    Example:
        >>> from Signals.Futures.CarrySignal import CarrySignal
        >>> signal = CarrySignal(standardize=True)
        >>> carries = signal.generate_batch(inst_data_list, None, as_of)
        >>> assert_valid_signal_distribution(carries)
    """
    # Check shape
    assert signals.ndim == 1, f"Signals must be 1D array, got {signals.ndim}D"
    assert len(signals) >= min_samples, \
        f"Need at least {min_samples} samples for validation, got {len(signals)}"

    # Check for NaN/Inf
    assert not np.any(np.isnan(signals)), "Signals contain NaN values"
    assert not np.any(np.isinf(signals)), "Signals contain Inf values"

    # Mean check: E[z] ≈ 0
    if check_mean:
        mean = np.mean(signals)
        assert abs(mean) < mean_tolerance, \
            f"Signal mean {mean:.3f} exceeds tolerance {mean_tolerance}"

    # Standard deviation check: σ[z] ≈ 1
    if check_std:
        std = np.std(signals, ddof=1)
        assert abs(std - 1.0) < std_tolerance, \
            f"Signal std {std:.3f} deviates from 1.0 by more than {std_tolerance}"


def assert_valid_returns_distribution(
    returns: np.ndarray,
    max_abs_return: float = 0.5,
    check_finite: bool = True,
) -> None:
    """
    Validate returns distribution.

    Args:
        returns: Return values
        max_abs_return: Maximum acceptable absolute return (default: 0.5 = 50%)
        check_finite: Check for NaN/Inf (default: True)

    Example:
        >>> assert_valid_returns_distribution(daily_returns, max_abs_return=0.2)
    """
    if check_finite:
        assert not np.any(np.isnan(returns)), "Returns contain NaN values"
        assert not np.any(np.isinf(returns)), "Returns contain Inf values"

    max_return = np.max(np.abs(returns))
    assert max_return <= max_abs_return, \
        f"Maximum absolute return {max_return:.3f} exceeds threshold {max_abs_return}"


# =============================================================================
# Component Import/Instantiation Testing
# =============================================================================

def get_importability_test_cases() -> List[Tuple[str, str]]:
    """
    Get list of (module_path, class_name) for importability tests.

    Returns:
        List of tuples: [(module_path, class_name), ...]

    Example:
        >>> test_cases = get_importability_test_cases()
        >>> for module_path, class_name in test_cases:
        ...     exec(f"from {module_path} import {class_name}")
        ...     assert eval(class_name) is not None
    """
    return [
        # Risk models
        ("Risk.Covariance.SampleCovariance", "SampleCovariance"),
        ("Risk.Covariance.LedoitWolfShrinkage", "LedoitWolfShrinkage"),
        ("Risk.Covariance.IdentityCovariance", "IdentityCovariance"),
        ("Risk.Covariance.DiagonalCovariance", "DiagonalCovariance"),
        ("Risk.Covariance.ConstantCorrelation", "ConstantCorrelation"),

        # Optimizers
        ("Optimizer.MeanVarianceOptimizer", "MeanVarianceOptimizer"),
        ("Optimizer.CVaROptimizer", "CVaROptimizer"),
        ("Optimizer.ClusterAwareOptimizer", "ClusterAwareOptimizer"),

        # Signals
        ("Signals.Futures.CarrySignal", "CarrySignal"),
        ("Signals.Futures.MomentumSignal", "MomentumSignal"),
        ("Signals.Futures.MeanReversionSignal", "MeanReversionSignal"),
        ("Signals.SignalCombiner", "SignalCombiner"),

        # Adapters
        ("Adapter.FuturesAdapter", "FuturesAdapter"),
        ("Adapter.EquityAdapter", "EquityAdapter"),

        # Backtest
        ("Backtest.Backtest", "Backtest"),
    ]


def assert_can_import(module_path: str, class_name: str) -> type:
    """
    Assert that a class can be imported from a module.

    Args:
        module_path: Full module path (e.g., "Risk.Covariance.SampleCovariance")
        class_name: Class name to import (e.g., "SampleCovariance")

    Returns:
        Imported class

    Raises:
        AssertionError: If import fails or class is None

    Example:
        >>> cls = assert_can_import("Risk.Covariance.SampleCovariance", "SampleCovariance")
        >>> instance = cls()
    """
    try:
        module = __import__(module_path, fromlist=[class_name])
        cls = getattr(module, class_name)
        assert cls is not None, f"{class_name} is None after import"
        return cls
    except ImportError as e:
        raise AssertionError(f"Failed to import {class_name} from {module_path}: {e}")
    except AttributeError as e:
        raise AssertionError(f"{class_name} not found in {module_path}: {e}")


def assert_can_instantiate(
    module_path: str,
    class_name: str,
    init_args: Tuple = (),
    init_kwargs: Dict = None,
) -> Any:
    """
    Assert that a class can be imported and instantiated.

    Args:
        module_path: Full module path
        class_name: Class name to import
        init_args: Positional arguments for __init__ (default: ())
        init_kwargs: Keyword arguments for __init__ (default: None)

    Returns:
        Instantiated object

    Raises:
        AssertionError: If import or instantiation fails

    Example:
        >>> estimator = assert_can_instantiate(
        ...     "Risk.Covariance.LedoitWolfShrinkage",
        ...     "LedoitWolfShrinkage",
        ...     init_kwargs={"shrinkage_target": "constant_correlation"}
        ... )
    """
    init_kwargs = init_kwargs or {}

    cls = assert_can_import(module_path, class_name)

    try:
        instance = cls(*init_args, **init_kwargs)
        assert instance is not None, f"{class_name} instance is None"
        return instance
    except Exception as e:
        raise AssertionError(
            f"Failed to instantiate {class_name} with args={init_args}, kwargs={init_kwargs}: {e}"
        )


# =============================================================================
# Portfolio and Performance Validation
# =============================================================================

def assert_valid_portfolio_weights(
    weights: np.ndarray,
    tolerance: float = 1e-6,
    check_sum_to_one: bool = True,
    max_leverage: float = None,
    allow_short: bool = True,
) -> None:
    """
    Validate portfolio weights.

    Args:
        weights: Portfolio weights (1D array)
        tolerance: Numerical tolerance for sum check
        check_sum_to_one: Verify weights sum to 1 (default: True)
        max_leverage: Maximum gross leverage |w| (default: None)
        allow_short: Allow negative weights (default: True)

    Example:
        >>> assert_valid_portfolio_weights(weights, max_leverage=2.0)
    """
    # Check shape
    assert weights.ndim == 1, f"Weights must be 1D array, got {weights.ndim}D"

    # Check finite
    assert not np.any(np.isnan(weights)), "Weights contain NaN values"
    assert not np.any(np.isinf(weights)), "Weights contain Inf values"

    # Sum to 1 check
    if check_sum_to_one:
        weight_sum = np.sum(weights)
        assert abs(weight_sum - 1.0) < tolerance, \
            f"Weights sum to {weight_sum:.6f}, not 1.0"

    # Short selling check
    if not allow_short:
        assert np.all(weights >= -tolerance), "Negative weights not allowed"

    # Leverage check
    if max_leverage is not None:
        gross_leverage = np.sum(np.abs(weights))
        assert gross_leverage <= max_leverage + tolerance, \
            f"Gross leverage {gross_leverage:.3f} exceeds limit {max_leverage}"


def assert_valid_sharpe_ratio(
    returns: np.ndarray,
    min_sharpe: float = -3.0,
    max_sharpe: float = 5.0,
    annualization_factor: float = np.sqrt(252),
) -> float:
    """
    Validate and compute annualized Sharpe ratio.

    Args:
        returns: Return series
        min_sharpe: Minimum acceptable Sharpe (default: -3.0)
        max_sharpe: Maximum acceptable Sharpe (default: 5.0)
        annualization_factor: Factor to annualize (default: sqrt(252))

    Returns:
        Annualized Sharpe ratio

    Example:
        >>> sharpe = assert_valid_sharpe_ratio(daily_returns, min_sharpe=0.5)
    """
    mean_return = np.mean(returns)
    std_return = np.std(returns, ddof=1)

    assert std_return > 0, "Return volatility is zero (constant returns)"

    sharpe = (mean_return / std_return) * annualization_factor

    assert min_sharpe <= sharpe <= max_sharpe, \
        f"Sharpe ratio {sharpe:.3f} outside valid range [{min_sharpe}, {max_sharpe}]"

    return sharpe


# =============================================================================
# Parametrized Test Fixtures
# =============================================================================

@pytest.fixture(params=get_importability_test_cases())
def component_import_case(request):
    """
    Parametrized fixture for component import testing.

    Usage in test file:
        def test_component_can_be_imported(component_import_case):
            module_path, class_name = component_import_case
            cls = assert_can_import(module_path, class_name)
            assert cls is not None
    """
    return request.param


# =============================================================================
# Numeric Comparison Helpers
# =============================================================================

def assert_almost_equal_with_tolerance(
    actual: float,
    expected: float,
    relative_tolerance: float = 0.1,
    absolute_tolerance: float = 1e-8,
) -> None:
    """
    Assert values are almost equal with relative and absolute tolerance.

    Args:
        actual: Actual value
        expected: Expected value
        relative_tolerance: Relative error tolerance (default: 0.1 = 10%)
        absolute_tolerance: Absolute error tolerance (default: 1e-8)

    Example:
        >>> assert_almost_equal_with_tolerance(0.099, 0.1, relative_tolerance=0.01)
    """
    if expected == 0:
        # Use absolute tolerance when expected is zero
        assert abs(actual - expected) <= absolute_tolerance, \
            f"Expected {expected}, got {actual} (abs error {abs(actual - expected):.2e})"
    else:
        # Use relative tolerance otherwise
        relative_error = abs((actual - expected) / expected)
        assert relative_error <= relative_tolerance or abs(actual - expected) <= absolute_tolerance, \
            f"Expected {expected}, got {actual} (rel error {relative_error:.2%})"


def assert_arrays_correlation(
    array1: np.ndarray,
    array2: np.ndarray,
    min_correlation: float = 0.0,
    max_correlation: float = 1.0,
) -> float:
    """
    Assert correlation between two arrays is within expected range.

    Args:
        array1: First array
        array2: Second array
        min_correlation: Minimum acceptable correlation
        max_correlation: Maximum acceptable correlation

    Returns:
        Correlation coefficient

    Example:
        >>> corr = assert_arrays_correlation(signals, returns, min_correlation=0.3)
    """
    assert len(array1) == len(array2), "Arrays must have same length"

    corr = np.corrcoef(array1, array2)[0, 1]

    assert not np.isnan(corr), "Correlation is NaN (zero variance?)"
    assert min_correlation <= corr <= max_correlation, \
        f"Correlation {corr:.3f} outside valid range [{min_correlation}, {max_correlation}]"

    return corr


# =============================================================================
# Test Data Generation Helpers
# =============================================================================

def generate_mock_returns(
    n_assets: int,
    n_periods: int,
    mean_return: float = 0.0,
    volatility: float = 0.01,
    correlation: float = 0.3,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate mock return data with specified characteristics.

    Args:
        n_assets: Number of assets
        n_periods: Number of time periods
        mean_return: Mean return per period (default: 0.0)
        volatility: Return volatility (default: 0.01 = 1%)
        correlation: Average pairwise correlation (default: 0.3)
        seed: Random seed for reproducibility (default: 42)

    Returns:
        Returns matrix (n_periods × n_assets)

    Example:
        >>> returns = generate_mock_returns(n_assets=10, n_periods=252)
        >>> assert returns.shape == (252, 10)
    """
    np.random.seed(seed)

    # Generate common factor for correlation
    common_factor = np.random.randn(n_periods, 1) * volatility * np.sqrt(correlation)

    # Generate idiosyncratic returns
    idiosyncratic = np.random.randn(n_periods, n_assets) * volatility * np.sqrt(1 - correlation)

    # Combine and add mean
    returns = mean_return + common_factor + idiosyncratic

    return returns


def generate_mock_covariance(
    n_assets: int,
    min_variance: float = 0.0001,
    max_variance: float = 0.01,
    correlation: float = 0.3,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate mock covariance matrix.

    Args:
        n_assets: Number of assets
        min_variance: Minimum diagonal variance (default: 0.0001)
        max_variance: Maximum diagonal variance (default: 0.01)
        correlation: Average correlation (default: 0.3)
        seed: Random seed (default: 42)

    Returns:
        Valid covariance matrix (n_assets × n_assets)

    Example:
        >>> cov = generate_mock_covariance(n_assets=5)
        >>> assert_valid_covariance_matrix(cov)
    """
    np.random.seed(seed)

    # Generate random variances
    variances = np.random.uniform(min_variance, max_variance, n_assets)

    # Create correlation matrix with average correlation
    corr = np.full((n_assets, n_assets), correlation)
    np.fill_diagonal(corr, 1.0)

    # Ensure positive definite by eigenvalue adjustment
    eigenvalues, eigenvectors = np.linalg.eigh(corr)
    eigenvalues = np.maximum(eigenvalues, 0.01)  # Floor eigenvalues
    corr = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

    # Convert to covariance
    std_dev = np.sqrt(variances)
    cov = np.outer(std_dev, std_dev) * corr

    return cov
