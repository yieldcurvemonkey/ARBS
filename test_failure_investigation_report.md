# Integration Test Failures Investigation Report

**Investigation Date:** 2025-11-15
**Total Failures:** 16 test failures across 5 test files
**Root Causes:** 2 missing dependencies, 1 test bug, 1 API usage bug

---

## Executive Summary

| Test File | Total Tests | Failures | Root Cause | Recommendation |
|-----------|-------------|----------|------------|----------------|
| `test_sector_covariance_real_data.py` | 7 | 4 | Missing `yfinance` | **SKIP** (optional external data) |
| `test_sector_rotation_integration.py` | 9 | 1 | Test bug | **FIXABLE** (1-line fix) |
| `test_signal_to_weights_pipeline.py` | 8 | 5 | Missing `pyarrow` | **FIXABLE** (install dependency) |
| `test_multi_risk_backtest.py` | 16 | 5 + 5 errors | Missing `pyarrow` | **FIXABLE** (install dependency) |
| `test_signal_component.py` | 8 | 1 | API usage bug | **FIXABLE** (1-line fix) |

---

## Detailed Analysis

### 1. test_sector_covariance_real_data.py (4 failures)

**Status:** SKIP (missing optional dependency)

**Failures:**
- `TestRealDataLoading::test_load_dow30_data`
- `TestRealDataLoading::test_invalid_universe`
- `TestRealDataLoading::test_sector_mapping`
- `TestDataQuality::test_validate_data_quality`

**Error:**
```
ModuleNotFoundError: No module named 'yfinance'
```

**Analysis:**
- All 4 failures require the `yfinance` package to download real market data
- This is an external data provider (Yahoo Finance API wrapper)
- The 3 passing tests use synthetic data and don't require yfinance
- These are integration tests for real market data acquisition, not core functionality

**Recommendation:** **SKIP**
- These tests require external dependencies (`yfinance`, `tqdm`) for downloading live market data
- They test data acquisition utilities, not core backtesting logic
- The core functionality is covered by other tests using synthetic data
- Installing yfinance would enable these tests, but they depend on external data availability

**Alternative:** Add to optional dependencies and skip if not installed using `pytest.importorskip()`

---

### 2. test_sector_rotation_integration.py (1 failure)

**Status:** FIXABLE (test bug - incorrect expectation)

**Failure:**
- `TestSectorRotationIntegration::test_fundamental_pipeline`

**Error:**
```python
assert all(0 <= p <= 1 for p in probabilities)
AssertionError: False
```

**Actual values:**
```python
probabilities = [1.14649604, -0.69224436, -0.45425167]
```

**Root Cause:**
The test has incorrect expectations about signal output format.

**Analysis:**
1. `FundamentalSignal` inherits from `BaseSignal` with default `standardize=True`
2. `_calculate_raw_signal()` returns probabilities [0, 1]
3. `generate_batch()` from `BaseSignal` then standardizes these to z-scores (mean=0, std=1)
4. **This is correct behavior** for Grinold-Kahn framework (signals are z-scores)
5. The test incorrectly expects raw probabilities instead of z-scores

**File:** `/home/user/ARBS/tests/integration/test_sector_rotation_integration.py`
**Line:** 134

**Fix:**
```python
# BEFORE (line 134):
assert all(0 <= p <= 1 for p in probabilities)

# AFTER:
# Probabilities are standardized to z-scores by BaseSignal (mean=0, std=1)
assert len(probabilities) == 3
assert abs(np.mean(probabilities)) < 1e-6  # Mean = 0
assert abs(np.std(probabilities, ddof=1) - 1.0) < 1e-6  # Std = 1
```

**Alternative Fix:** Disable standardization in the test:
```python
# Line 113:
signal = FundamentalSignal(hidden_layers=(5, 5), standardize=False)  # Add standardize=False

# Then line 134 would work as-is:
assert all(0 <= p <= 1 for p in probabilities)
```

**Recommendation:** **FIXABLE** - Use Alternative Fix (cleaner, tests raw probabilities)

---

### 3. test_signal_to_weights_pipeline.py (5 failures)

**Status:** FIXABLE (install missing dependency)

**Failures:**
- `TestSignalToWeightsPipeline::test_end_to_end_pipeline`
- `TestSignalToWeightsPipeline::test_correlation_affects_weights`
- `TestSignalToWeightsPipeline::test_volatility_scaling_matters`
- `TestSignalToWeightsPipeline::test_ic_parameter_affects_weights`
- `TestRealisticScenarios::test_carry_strategy_scenario`

**Error:**
```python
ModuleNotFoundError: No module named 'pyarrow'
```

**Stack Trace:**
```python
returns_history.to_pandas()  # Line 85, 190, 246, 284, 337
  → polars.DataFrame.to_pandas()
    → ModuleNotFoundError: No module named 'pyarrow'
```

**Analysis:**
- Tests use `polars.DataFrame.to_pandas()` to convert to pandas for risk models
- Polars requires `pyarrow` for efficient pandas conversion
- This is a standard dependency for polars-pandas interop
- 3 tests pass (don't use to_pandas conversion)

**Fix:**
```bash
pip install pyarrow
```

**Recommendation:** **FIXABLE** - Install `pyarrow` (standard polars dependency)

---

### 4. test_multi_risk_backtest.py (5 failures + 5 errors)

**Status:** FIXABLE (install missing dependency)

**Failures:**
- `TestSyntheticBacktest::test_pipeline_with_sample_covariance`
- `TestRiskModelComparison::test_diagonal_model_ignores_correlation`
- `TestRiskModelComparison::test_identity_model_equal_variance`
- `TestEdgeCases::test_all_models_handle_single_asset`
- `TestEdgeCases::test_all_models_handle_zero_signals`

**Errors (fixture failures):**
- `TestRiskModelComparison::test_all_models_produce_valid_weights`
- `TestRiskModelComparison::test_weights_concentration_computed`
- `TestRiskModelPerformance::test_all_models_produce_valid_performance`
- `TestRiskModelPerformance::test_volatility_computed_for_all_models`
- `TestRiskModelPerformance::test_performance_metrics_documented`

**Error:** Same as #3 - Missing `pyarrow`

**Analysis:**
- Same root cause as test_signal_to_weights_pipeline.py
- All failures use `returns.to_pandas()` for risk model estimation
- 6 tests pass (don't require pandas conversion)
- Errors are due to pytest fixture failures (fixtures use to_pandas)

**Fix:**
```bash
pip install pyarrow
```

**Recommendation:** **FIXABLE** - Install `pyarrow`

---

### 5. test_signal_component.py (1 failure)

**Status:** FIXABLE (incorrect API usage)

**Failure:**
- `TestSignalComponent::test_concrete_implementation_calculate`

**Error:**
```python
AttributeError: 'DataFrame' object has no attribute 'frame_equal'
```

**File:** `/home/user/ARBS/tests/Signals/test_signal_component.py`
**Line:** 40

**Root Cause:**
Polars DataFrame API changed. The method `frame_equal()` was renamed to `equals()`.

**Current Code (line 40):**
```python
assert result.frame_equal(expected)
```

**Fix:**
```python
assert result.equals(expected)
```

**Verification:**
```python
>>> import polars as pl
>>> df = pl.DataFrame({'a': [1, 2, 3]})
>>> hasattr(df, 'frame_equal')
False
>>> hasattr(df, 'equals')
True
```

**Recommendation:** **FIXABLE** - Replace `frame_equal()` with `equals()`

---

## Summary of Recommendations

### Install Immediately (Critical Fixes)

**1. Install pyarrow** (fixes 10 test failures)
```bash
pip install pyarrow
```
- Fixes: `test_signal_to_weights_pipeline.py` (5 failures)
- Fixes: `test_multi_risk_backtest.py` (5 failures + 5 errors)
- Standard dependency for polars-pandas interop

### Fix Test Bugs (2 one-line fixes)

**2. Fix test_signal_component.py** (line 40)
```python
# Change:
assert result.frame_equal(expected)
# To:
assert result.equals(expected)
```

**3. Fix test_sector_rotation_integration.py** (line 113)
```python
# Change:
signal = FundamentalSignal(hidden_layers=(5, 5))
# To:
signal = FundamentalSignal(hidden_layers=(5, 5), standardize=False)
```

### Optional (Skip External Data Tests)

**4. Skip test_sector_covariance_real_data.py**
- Option A: Leave as-is (4 failures, 3 passes)
- Option B: Install `yfinance` and `tqdm` (enables real market data tests)
- Option C: Mark tests with `@pytest.mark.skipif` if yfinance not available

---

## Impact Analysis

**Before Fixes:**
- 16 test failures across 5 files
- 582 total tests (566 passing, 16 failing)
- Success rate: 97.3%

**After Fixes:**
- Install pyarrow: +10 tests passing (576/582 = 99.0%)
- Fix 2 test bugs: +2 tests passing (578/582 = 99.3%)
- Skip yfinance tests: 4 tests skipped (578/578 = 100% of testable)

**Final State:**
- 578 passing tests
- 4 skipped tests (require yfinance)
- 0 failures
- 100% pass rate on available dependencies

---

## Files to Modify

### 1. Install Dependencies
```bash
# In requirements.txt or pyproject.toml
pyarrow>=12.0.0  # For polars-pandas conversion
```

### 2. Code Changes

**File:** `/home/user/ARBS/tests/Signals/test_signal_component.py`
```python
# Line 40
- assert result.frame_equal(expected)
+ assert result.equals(expected)
```

**File:** `/home/user/ARBS/tests/integration/test_sector_rotation_integration.py`
```python
# Line 113
- signal = FundamentalSignal(hidden_layers=(5, 5))
+ signal = FundamentalSignal(hidden_layers=(5, 5), standardize=False)
```

### 3. Optional: Mark Skippable Tests

**File:** `/home/user/ARBS/tests/integration/test_sector_covariance_real_data.py`
```python
# Add at top
import pytest

yfinance = pytest.importorskip("yfinance", reason="yfinance required for real data tests")
```

---

## Root Cause Classification

| Category | Count | Action |
|----------|-------|--------|
| Missing Dependencies | 14 | Install pyarrow |
| Test Bugs | 2 | Fix assertions |
| Optional External Data | 4 | Skip or install yfinance |

---

## Next Steps

1. **Immediate:** Install `pyarrow` (fixes 10 failures)
2. **Quick Fix:** Update 2 test assertions (fixes 2 failures)
3. **Optional:** Decide on yfinance tests (skip vs install)
4. **Verify:** Run full test suite to confirm 100% pass rate

All issues are easily fixable with no code changes required to production code.
