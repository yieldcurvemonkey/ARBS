# Covariance Estimator Templates

This directory contains templates for integrating external covariance estimators into the ARBS framework.

## Quick Start: Adding a New Estimator

1. **Copy the template:**
   ```bash
   cp external_risk_model_template.py ../Covariance/YourNewEstimator.py
   ```

2. **Fill in the [PLACEHOLDER] markers:**
   - `[ESTIMATOR_NAME]`: Name of the algorithm
   - `[PLACEHOLDER_CLASSNAME]`: Your class name (PascalCase)
   - `[PLACEHOLDER: ...]`: Various implementation details
   - Import statements for external library
   - Parameters in `__init__`
   - Core logic in `fit()`

3. **Implement the fit() method:**
   - Call your external library in Step 4
   - The template shows 3 common patterns (sklearn-style, function-based, custom)

4. **Test your estimator:**
   ```python
   from Risk.Covariance.YourNewEstimator import YourNewEstimator

   estimator = YourNewEstimator(param1=value1)
   cov_matrix = estimator.fit(returns_df)
   ```

5. **Write tests:**
   - Create `tests/unit/risk/test_your_estimator.py`
   - Test basic functionality, edge cases, validation

## Template Structure

### Required Sections
- **Imports**: Base class + external library
- **Class Definition**: Inherit from `BaseCovarianceEstimator`
- **`__init__`**: Store algorithm parameters
- **`fit()`**: Main estimation logic (see 7 steps in template)
- **`__repr__`**: String representation

### Optional Sections
- **Validation Functions**: `_validate_covariance_matrix`, `_ensure_positive_definite`
- **Helper Methods**: For complex algorithms with multiple steps
- **Getter Methods**: Expose additional results (e.g., `get_shrinkage_intensity()`)
- **Usage Example**: Quick test in `if __name__ == "__main__"` block

## Key Requirements

1. **Inherit from BaseCovarianceEstimator**
   - Provides standard interface: `fit()`, `get_covariance()`, `condition_number()`
   - Handles missing data: `_handle_missing_data()`
   - Stores: `cov_matrix_`, `asset_names_`

2. **Validate Output**
   - Must be square (N×N)
   - Must be symmetric
   - Must be positive semi-definite
   - Use `_validate_covariance_matrix()` helper

3. **Store Result in `self.cov_matrix_`**
   - Required for base class methods to work
   - Must be numpy array, not DataFrame

4. **Follow ARBS Conventions**
   - PascalCase for class names
   - 2-line ABOUTME comment at file start
   - Comprehensive docstrings with paper citations
   - Type hints on all public methods

## Integration Patterns

### Pattern 1: sklearn-style (fit/transform)
```python
from sklearn.covariance import GraphicalLassoCV

def fit(self, returns: pd.DataFrame) -> np.ndarray:
    returns_clean = self._handle_missing_data(returns)
    self.asset_names_ = list(returns_clean.columns)

    # Call external estimator
    estimator = GraphicalLassoCV(alphas=10, cv=5)
    estimator.fit(returns_clean.values)

    # Extract and validate result
    cov_matrix = estimator.covariance_
    _validate_covariance_matrix(cov_matrix)

    self.cov_matrix_ = cov_matrix
    return self.cov_matrix_
```

### Pattern 2: Function-based
```python
from some_package import compute_robust_covariance

def fit(self, returns: pd.DataFrame) -> np.ndarray:
    returns_clean = self._handle_missing_data(returns)
    self.asset_names_ = list(returns_clean.columns)

    # Call external function
    cov_matrix = compute_robust_covariance(
        returns_clean.values,
        method=self.method,
        alpha=self.alpha
    )

    _validate_covariance_matrix(cov_matrix)
    self.cov_matrix_ = cov_matrix
    return self.cov_matrix_
```

### Pattern 3: Custom Implementation
```python
def fit(self, returns: pd.DataFrame) -> np.ndarray:
    returns_clean = self._handle_missing_data(returns)
    self.asset_names_ = list(returns_clean.columns)

    # Implement algorithm from scratch
    cov_matrix = self._custom_algorithm(returns_clean)

    _validate_covariance_matrix(cov_matrix)
    self.cov_matrix_ = cov_matrix
    return self.cov_matrix_

def _custom_algorithm(self, returns: pd.DataFrame) -> np.ndarray:
    # Your implementation here
    pass
```

## Examples of Existing Estimators

Look at these for reference:

- **Simple**: `Risk/Covariance/SampleCovariance.py`
  - Minimal implementation
  - Just inherits and implements `fit()`
  - Good starting point

- **Complex**: `Risk/Covariance/LedoitWolfShrinkage.py`
  - Multiple parameters
  - Helper methods
  - Additional getters
  - Detailed docstrings

- **Structured**: `Risk/Covariance/ConstantCorrelationCovariance.py`
  - Custom algorithm implementation
  - Multiple internal steps

## Testing Checklist

When implementing a new estimator, verify:

- [ ] Inherits from `BaseCovarianceEstimator`
- [ ] Implements `fit()` method
- [ ] Handles missing data correctly
- [ ] Stores `self.cov_matrix_` and `self.asset_names_`
- [ ] Returns valid covariance matrix (symmetric, PSD)
- [ ] Has comprehensive docstring with citation
- [ ] Has ABOUTME comment at file start
- [ ] Implements `__repr__`
- [ ] Has unit tests covering:
  - Basic functionality
  - Edge cases (empty data, single asset, etc.)
  - Output validation
  - Comparison with known results
- [ ] Integrates with `RiskModelFactory` (if applicable)

## Questions?

See:
- Base class: `Risk/Base/BaseCovarianceEstimator.py`
- Factory: `Risk/risk_model_factory.py`
- Tests: `tests/unit/risk/test_covariance_*.py`
