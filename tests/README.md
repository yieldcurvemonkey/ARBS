# Test Suite Documentation

## Overview

This directory contains the comprehensive test suite for the ARBS (Algorithmic Risk-Based Strategies) backtesting framework. The test suite is organized following best practices and uses utility functions to minimize boilerplate and maximize maintainability.

## Test Organization

```
tests/
├── utils.py                    # Reusable test utilities (NEW - 2025-11-17)
├── README.md                   # This file
├── unit/                       # Unit tests (individual components)
│   ├── adapter/               # Adapter layer tests (Query → Signals)
│   ├── asset/                 # Asset classes (Future, Position, Portfolio)
│   ├── backtest/              # Backtest framework tests
│   ├── optimizer/             # Portfolio optimizer tests
│   ├── query/                 # Market data query tests
│   ├── risk/                  # Risk model tests (covariance, volatility)
│   └── signals/               # Signal generation tests
├── integration/               # Integration tests (cross-component)
└── validation/                # Validation tests (reference implementations)
```

## Test Utilities (`tests/utils.py`)

The `tests/utils.py` module provides reusable helper functions to eliminate test boilerplate. **Created Nov 17, 2025** to consolidate 60+ repetitive tests across the codebase.

### Covariance Matrix Validation

```python
from tests.utils import assert_valid_covariance_matrix

# Validate all covariance matrix properties in one call
cov_matrix = estimator.fit(returns)
assert_valid_covariance_matrix(
    cov_matrix,
    check_symmetric=True,              # Σ = Σᵀ
    check_positive_semidefinite=True,  # all eigenvalues ≥ 0
    check_invertible=True,             # det(Σ) > 0
    max_condition_number=100,          # κ(Σ) < threshold
)
```

**Replaces:**
- 5+ symmetry checks: `np.testing.assert_array_almost_equal(cov, cov.T)`
- 10+ eigenvalue checks: `eigenvalues = np.linalg.eigvalsh(cov); assert all(eigenvalues >= 0)`
- Multiple condition number checks

**Examples:** See `tests/unit/risk/test_covariance_estimators.py`

### Signal Distribution Validation

```python
from tests.utils import assert_valid_signal_distribution

# Validate z-score properties (mean ≈ 0, std ≈ 1)
signals = signal_generator.generate_batch(instruments)
assert_valid_signal_distribution(
    signals,
    mean_tolerance=0.1,   # |E[z]| < 0.1
    std_tolerance=0.2,    # |σ[z] - 1.0| < 0.2
)
```

**Replaces:**
- 14+ mean checks: `assert abs(np.mean(signals)) < 0.1`
- 18+ std checks: `assert abs(np.std(signals, ddof=1) - 1.0) < 0.2`

**Examples:** See `tests/unit/signals/test_carry_signal.py`

### Component Import/Instantiation

```python
from tests.utils import assert_can_import, assert_can_instantiate

# Import validation
cls = assert_can_import("Risk.Covariance.LedoitWolfShrinkage", "LedoitWolfShrinkage")

# Instantiation validation
estimator = assert_can_instantiate(
    "Risk.Covariance.LedoitWolfShrinkage",
    "LedoitWolfShrinkage",
    init_kwargs={"shrinkage_target": "constant_correlation"}
)
```

**Replaces:**
- 19 import tests: `from X import Y; assert Y is not None`
- 13 instantiation tests: `obj = X(); assert obj is not None`

**Examples:** See `tests/unit/adapter/test_futures_adapter.py`

### Parametrized Import Tests

For testing multiple components at once:

```python
import pytest
from tests.utils import assert_can_import

@pytest.mark.parametrize("module_path,class_name", [
    ("Risk.Covariance.SampleCovariance", "SampleCovariance"),
    ("Risk.Covariance.LedoitWolfShrinkage", "LedoitWolfShrinkage"),
])
def test_covariance_estimators_can_be_imported(module_path, class_name):
    cls = assert_can_import(module_path, class_name)
    assert cls is not None
```

**Examples:** See `tests/unit/risk/test_covariance_estimators.py`

### Portfolio & Performance Validation

```python
from tests.utils import assert_valid_portfolio_weights, assert_valid_sharpe_ratio

# Validate portfolio weights
assert_valid_portfolio_weights(
    weights,
    check_sum_to_one=True,
    max_leverage=2.0,
    allow_short=True,
)

# Validate Sharpe ratio
sharpe = assert_valid_sharpe_ratio(
    daily_returns,
    min_sharpe=-3.0,
    max_sharpe=5.0,
)
```

### Mock Data Generation

```python
from tests.utils import generate_mock_returns, generate_mock_covariance

# Generate correlated returns
returns = generate_mock_returns(
    n_assets=10,
    n_periods=252,
    mean_return=0.0001,
    volatility=0.01,
    correlation=0.3,
)

# Generate valid covariance matrix
cov = generate_mock_covariance(
    n_assets=5,
    correlation=0.3,
)
```

## When to Use Test Utilities

### ✅ Use Test Utilities When:

1. **Validating covariance matrices** - Use `assert_valid_covariance_matrix()` instead of individual checks
2. **Validating signal standardization** - Use `assert_valid_signal_distribution()` for z-score validation
3. **Testing imports** - Use `assert_can_import()` and `assert_can_instantiate()`
4. **Generating test data** - Use `generate_mock_returns()` and `generate_mock_covariance()`
5. **The pattern appears 3+ times** - If you're copying the same test code, create a utility

### ❌ Don't Use Test Utilities When:

1. **Testing specific business logic** - Keep domain-specific tests explicit
2. **Edge cases require custom validation** - Write custom assertions with clear error messages
3. **Test setup is unique** - Don't force-fit utilities to unique scenarios
4. **Single-use patterns** - If it only appears once, inline is clearer

## Boilerplate Reduction Summary

### Before Test Utilities (Pre-Nov 17, 2025)

**Identified boilerplate patterns:**
- 19 import tests: `from X import Y; assert Y is not None`
- 13 instantiation tests: `obj = X(); assert obj is not None`
- 5 symmetry checks: `np.testing.assert_array_almost_equal(cov, cov.T)`
- 10+ eigenvalue checks: Manual eigenvalue validation
- 14 signal mean checks: `assert abs(np.mean(signals)) < tolerance`
- 18 signal std checks: `assert abs(np.std(signals, ddof=1) - 1.0) < tolerance`

**Total: ~80+ boilerplate tests**

### After Test Utilities

**Consolidated into parametrized tests and utilities:**
- Import/instantiation: Single parametrized test per module
- Covariance validation: One function call replacing 3-5 checks
- Signal validation: One function call replacing 2 checks

**Estimated reduction: 200-300 lines of test code**

## Test Organization Principles

### 1. Test Naming Convention

```python
class TestFeatureName:
    """Test suite for specific feature."""

    def test_feature_does_expected_behavior(self):
        """Feature should exhibit expected behavior under normal conditions."""
        # Arrange
        setup_code()

        # Act
        result = feature.method()

        # Assert
        assert result == expected
```

### 2. Test Classes by Feature

Group related tests into classes:
- `TestBasics` - Import, instantiation, basic functionality
- `TestFeatureName` - Specific feature behavior
- `TestEdgeCases` - Error handling, boundary conditions
- `TestBusinessRequirements` - Business logic validation
- `TestIntegration` - Cross-component integration

### 3. Parametrized Tests

Use `@pytest.mark.parametrize` for testing multiple scenarios:

```python
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_doubling(input, expected):
    assert double(input) == expected
```

### 4. Fixtures

Use fixtures for shared test setup:

```python
@pytest.fixture
def sample_returns():
    """Generate sample return data for testing."""
    return pl.DataFrame(np.random.randn(100, 10))

def test_covariance_estimation(sample_returns):
    cov = estimator.fit(sample_returns)
    assert_valid_covariance_matrix(cov)
```

## Running Tests

### Run All Tests
```bash
pytest tests/
```

### Run Specific Test Module
```bash
pytest tests/unit/risk/test_covariance_estimators.py
```

### Run Specific Test Class
```bash
pytest tests/unit/risk/test_covariance_estimators.py::TestLedoitWolfShrinkage
```

### Run Specific Test
```bash
pytest tests/unit/risk/test_covariance_estimators.py::TestLedoitWolfShrinkage::test_ledoit_wolf_reduces_condition_number
```

### Run with Coverage
```bash
pytest tests/ --cov=. --cov-report=html
```

### Run with Verbose Output
```bash
pytest tests/ -v
```

### Run Only Failed Tests
```bash
pytest tests/ --lf
```

## Test Requirements

### Business Requirements

All tests must validate against business requirements:

1. **Measurement Accuracy** - Tests measure correctly, not necessarily profitably
2. **Numerical Stability** - Covariance matrices must be well-conditioned (κ < 100)
3. **Statistical Validity** - Signals properly standardized (z-scores)
4. **Performance** - Operations complete within reasonable time bounds

### Test Quality Standards

1. **Independence** - Tests must not depend on execution order
2. **Repeatability** - Same inputs produce same outputs
3. **Clarity** - Test names and assertions clearly state intent
4. **Speed** - Unit tests run in < 1 second each
5. **Coverage** - All public APIs have test coverage

## Adding New Tests

### Step 1: Check for Existing Patterns

Before writing a new test, check if a utility function exists:

```python
# Instead of:
def test_my_covariance_is_symmetric(self):
    np.testing.assert_array_almost_equal(cov, cov.T)

# Use:
def test_my_covariance_properties(self):
    assert_valid_covariance_matrix(cov)
```

### Step 2: Write Clear Test Names

Test names should describe what is being tested:

```python
# Good
def test_ledoit_wolf_reduces_condition_number(self):

# Bad
def test_lw_works(self):
```

### Step 3: Use Arrange-Act-Assert Pattern

```python
def test_feature(self):
    # Arrange - Set up test data
    data = setup_test_data()

    # Act - Execute the feature
    result = feature.process(data)

    # Assert - Validate expectations
    assert result == expected
```

### Step 4: Document Business Context

Include docstrings explaining WHY the test exists:

```python
def test_ledoit_wolf_reduces_condition_number(self):
    """
    Ledoit-Wolf shrinkage should reduce condition number for stability.

    Business requirement: κ(Σ) < 100 for stable portfolio optimization.
    Ledoit-Wolf achieves this even when N ≈ T (typical in practice).
    """
```

## Migrating Old Tests to Utilities

### Migration Checklist

When refactoring existing tests to use utilities:

1. ✅ Identify the boilerplate pattern
2. ✅ Find the appropriate utility function in `tests/utils.py`
3. ✅ Replace the old code with utility call
4. ✅ Comment out old code with `# Replaced by: ...`
5. ✅ Run tests to verify behavior unchanged
6. ✅ After successful migration, remove commented code

### Example Migration

**Before:**
```python
def test_covariance_is_symmetric(self):
    cov = estimator.fit(returns)
    np.testing.assert_array_almost_equal(cov, cov.T)

def test_covariance_is_positive_definite(self):
    cov = estimator.fit(returns)
    eigenvalues = np.linalg.eigvalsh(cov)
    assert np.all(eigenvalues >= -1e-10)
```

**After:**
```python
def test_covariance_properties(self):
    """Covariance matrix should be symmetric and positive definite."""
    cov = estimator.fit(returns)

    # Replaced individual tests with comprehensive validation
    assert_valid_covariance_matrix(
        cov,
        check_symmetric=True,
        check_positive_semidefinite=True,
    )
```

## Test Files Already Refactored

The following files demonstrate utility usage (refactored Nov 17, 2025):

1. **`tests/unit/risk/test_covariance_estimators.py`**
   - Parametrized import/instantiation tests
   - Covariance matrix property validation
   - Lines reduced: ~30 → ~15 (50% reduction)

2. **`tests/unit/signals/test_carry_signal.py`**
   - Import/instantiation with utilities
   - Signal distribution validation
   - Lines reduced: ~15 → ~8 (47% reduction)

3. **`tests/unit/adapter/test_futures_adapter.py`**
   - Import/instantiation with utilities
   - Lines reduced: ~10 → ~6 (40% reduction)

## Next Steps: Full Migration Plan

### Phase 1: Remaining Import/Instantiation Tests (15 files)

Files with boilerplate import/instantiation tests to migrate:
- `tests/unit/test_futures_structure_map.py`
- `tests/unit/test_futures_value_map.py`
- `tests/unit/signals/test_signal_combiner.py`
- `tests/unit/signals/test_base_signal.py`
- `tests/unit/risk/test_identity_covariance.py`
- `tests/unit/risk/test_constant_correlation.py`
- `tests/unit/risk/test_diagonal_covariance.py`
- `tests/unit/optimizer/test_cluster_aware_optimizer.py`
- `tests/unit/optimizer/test_cvar_optimizer.py`
- `tests/unit/optimizer/test_mean_variance_optimizer.py`
- `tests/unit/backtest/test_backtest.py`
- `tests/unit/adapter/test_equity_adapter.py`

**Estimated effort:** 2-3 hours
**Estimated reduction:** 100-150 lines

### Phase 2: Signal Standardization Tests (10 files)

Files with signal z-score validation to migrate:
- `tests/unit/signals/test_currency_carry_signal.py`
- `tests/unit/signals/test_mean_reversion_signal.py`
- `tests/unit/signals/test_momentum_signal.py`
- `tests/unit/signals/test_base_signal.py`
- `tests/unit/signals/sector_rotation/test_*_signal.py` (multiple files)

**Estimated effort:** 1-2 hours
**Estimated reduction:** 50-80 lines

### Phase 3: Covariance Matrix Validation Tests (3 files)

Files with covariance property checks to migrate:
- `tests/unit/risk/test_diagonal_covariance.py`
- `tests/unit/risk/test_constant_correlation.py`
- `tests/unit/risk/test_identity_covariance.py`

**Estimated effort:** 1 hour
**Estimated reduction:** 30-50 lines

## Contributing

When adding new test utilities:

1. **Add to `tests/utils.py`** with comprehensive docstrings
2. **Update this README** with usage examples
3. **Refactor 2-3 existing tests** to demonstrate usage
4. **Ensure all tests pass** before committing

## References

- **TDD Philosophy**: Design tests from business perspective first
- **MVP Principle**: Measure correctly, not necessarily profitably
- **Test Quality**: Pristine output, no warnings, clear failures
- **Grinold-Kahn Architecture**: Tests validate proper IC × Vol × Z scaling

---

**Last Updated:** November 17, 2025
**Test Count:** 582 tests passing
**Utility Functions:** 15+ reusable helpers
**Boilerplate Eliminated:** ~80+ repetitive tests → ~20 parametrized tests
