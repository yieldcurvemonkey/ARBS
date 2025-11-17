# Critical Bug Fixes Plan

**Date**: 2025-11-15
**Based On**: Code review findings from parallel reviewers

---

## TimeSeriesSignalMixin Fixes (5 Critical Bugs)

### Fix #1: Remove Architectural Violation

**Problem**: Created duplicate `calculate()` method instead of using existing `BaseSignal.generate_batch()`

**Solution**: Make `calculate()` delegate to `generate_batch()` to reuse existing infrastructure

**File**: `Signals/Base/TimeSeriesSignalMixin.py`

**Changes**:
```python
def calculate(
    self,
    instruments: List[str],
    market_data: Any,
    as_of: date,
) -> Dict[str, float]:
    """
    Calculate signals for multiple instruments.

    Delegates to BaseSignal.generate_batch() to reuse existing infrastructure.
    """
    # Fetch price history for all instruments
    inst_data_list = []
    failed_instruments = []

    lookback_days = getattr(self, 'lookback_days', 60)

    for instrument in instruments:
        try:
            lookback_date = as_of - timedelta(days=lookback_days + 10)
            price_history = market_data.get_price_history(
                instrument,
                start_date=lookback_date,
                end_date=as_of
            )
            inst_data_list.append(price_history)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "Excluding instrument from universe",
                extra={'instrument': instrument, 'error': str(e)}
            )
            failed_instruments.append(instrument)

    # Only process instruments that succeeded
    successful_instruments = [i for i in instruments if i not in failed_instruments]

    if not successful_instruments:
        return {}

    # Delegate to BaseSignal.generate_batch()
    signals_array = self.generate_batch(inst_data_list, market_data, as_of)

    # Convert array to dict
    return {inst: float(sig) for inst, sig in zip(successful_instruments, signals_array)}
```

---

### Fix #2: Error Handling - Exclude Failed Instruments

**Problem**: Failed instruments assigned 0.0, which becomes negative z-score (bearish bias)

**Solution**: Exclude failed instruments from universe entirely (done in Fix #1)

---

### Fix #3: Security - Use Logging Instead of Print

**Problem**: `print()` may leak sensitive information in logs

**Solution**: Replace with proper logging (done in Fix #1)

---

### Fix #4: Contract Enforcement

**Problem**: Mixin accesses attributes without checking they exist

**Solution**: Add explicit checks with helpful error messages

**File**: `Signals/Base/TimeSeriesSignalMixin.py`

**Add to beginning of `calculate()`**:
```python
def calculate(self, instruments, market_data, as_of):
    # Enforce contract - mixin requires these attributes
    required_attrs = ['lookback_days', 'standardize', 'track_history', '_calculate_raw_signal']
    missing = [attr for attr in required_attrs if not hasattr(self, attr)]

    if missing:
        raise TypeError(
            f"{self.__class__.__name__} must define {missing} to use TimeSeriesSignalMixin. "
            f"Ensure your class extends BaseSignal and defines lookback_days in __init__."
        )

    # Rest of method...
```

---

### Fix #5: Fix Test Failure

**Problem**: `test_calculate_with_error` expects 0.0 but gets -0.707

**Solution**: Update test to expect failed instrument to be excluded

**File**: `tests/unit/signals/test_time_series_signal_mixin.py`

**Change**:
```python
def test_calculate_with_error(self):
    # INST2 is missing from price data (will error and be excluded)
    results = signal.calculate(['INST1', 'INST2'], mdp, base_date)

    # INST2 should be excluded, not included with 0.0
    assert len(results) == 1  # Only INST1
    assert 'INST1' in results
    assert 'INST2' not in results  # Excluded!
```

---

## Covariance Validation Fixes (3 Critical Bugs)

### Fix #6: Division by Zero in _calculate_condition_number()

**Problem**: Divides by min eigenvalue without checking for zero

**File**: `Risk/Base/BaseCovarianceEstimator.py`

**Change line 217**:
```python
def _calculate_condition_number(self, cov_matrix: np.ndarray) -> float:
    """Calculate condition number of covariance matrix."""
    eigenvalues = np.linalg.eigvalsh(cov_matrix)
    max_eig = eigenvalues.max()
    min_eig = eigenvalues.min()

    # Handle singular matrix
    if min_eig <= 0:
        return np.inf

    return max_eig / min_eig
```

---

### Fix #7: Remove Method Duplication

**Problem**: `condition_number()` (line 102) and `_calculate_condition_number()` (line 199) duplicate functionality

**Solution**: Remove `_calculate_condition_number()` entirely, use `condition_number()` everywhere

**File**: `Risk/Base/BaseCovarianceEstimator.py`

**DELETE lines 199-217** (the entire `_calculate_condition_number()` method)

**UPDATE `condition_number()` to handle singular matrices**:
```python
def condition_number(self) -> float:
    """
    Calculate condition number of covariance matrix.

    Returns:
        Condition number (κ = λ_max / λ_min)
        Returns np.inf for singular matrices
    """
    cov = self.get_covariance()
    cond = np.linalg.cond(cov)

    # np.linalg.cond can return inf for singular matrices
    # This is correct behavior - document it
    return cond
```

---

### Fix #8: Add Validation to BaseCovarianceEstimator.fit()

**Problem**: Only OAShrinkage validates; other estimators don't

**Solution**: Add template method pattern to enforce validation

**File**: `Risk/Base/BaseCovarianceEstimator.py`

**Rename existing `fit()` to `_fit_impl()`**:
```python
@abstractmethod
def _fit_impl(self, returns: pl.DataFrame) -> np.ndarray:
    """
    Estimate covariance matrix from returns (implementation).

    Subclasses implement this instead of fit().
    """
    pass

def fit(self, returns: pl.DataFrame) -> np.ndarray:
    """
    Estimate covariance matrix with automatic validation.

    Template method that:
    1. Calls subclass _fit_impl()
    2. Validates result
    3. Stores in self.cov_matrix_
    4. Returns covariance matrix
    """
    # Call subclass implementation
    cov_matrix = self._fit_impl(returns)

    # Always validate
    self._validate_covariance_matrix(cov_matrix)

    # Store result
    self.cov_matrix_ = cov_matrix
    self.asset_names_ = returns.columns

    return cov_matrix
```

**Update all subclasses**: Rename `fit()` → `_fit_impl()`
- `SampleCovariance.py`
- `LedoitWolfShrinkage.py`
- `OAShrinkage.py`
- `ConstantCorrelationCovariance.py`
- `DiagonalCovariance.py`
- `IdentityCovariance.py`
- All sector-based estimators

---

## Execution Order

**Agent 1**: Fix TimeSeriesSignalMixin (Fixes #1-5)
**Agent 2**: Fix Covariance Validation (Fixes #6-8)

Both can run in parallel (different files).

---

## Success Criteria

1. All 597 tests pass (582 original + 15 new)
2. No architectural violations (use existing systems)
3. No security issues (use logging, not print)
4. No silent failures (failed instruments excluded)
5. No division by zero errors
6. Consistent validation across all estimators
