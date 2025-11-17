# ARBS Production Readiness Task List
**Generated**: 2025-11-17
**Status**: Diagnostic complete, fixes required

## Executive Summary

ARBS is currently **NOT production ready** in the sandbox environment. Basic validation passes, but backtesting is blocked by a critical datetime type mismatch. After fixing 3 priority issues and addressing missing dependencies, the system should be functional.

**Estimated Time to Production**: 4-8 hours (assuming no additional hidden issues)

---

## P0 - Blocking Issues (MUST FIX)

### Task 1: Fix datetime.date vs datetime.datetime Type Mismatch
**Status**: 🔴 BLOCKING
**Files**: `BT/triggers.py`, `BT/misc.py`, `BT/data_handler.py`
**Error**: `AttributeError: 'datetime.date' object has no attribute 'date'`

#### Root Cause Analysis
1. `TimeGrid.__init__()` expects `Iterable[datetime.datetime]` but receives `datetime.date` objects
2. `ql_cal_date_range()` uses `pl.date_range()` which returns dates, not datetimes
3. `DateTriggerRequirements.has_triggered()` calls `state.date()` assuming datetime, but gets date

#### Proposed Fix (Choose One)

**Option A: Convert dates to datetimes in ql_cal_date_range** (RECOMMENDED)
```python
# In BT/misc.py, around line 37:
return [datetime.datetime.combine(d.date(), datetime.time(0, 0))
        if isinstance(d, datetime.datetime) and d.time() == datetime.time(0, 0)
        else d
        for d in date_filtered_range]
```

**Option B: Handle both types in DateTriggerRequirements**
```python
# In BT/triggers.py line 154:
def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
    check_date = state.date() if isinstance(state, dt.datetime) else state
    return TriggerInfo(check_date in set(self.dates))
```

**Recommendation**: Use **Option B** (defensive) - handles both types gracefully and prevents future issues.

#### Test Plan
1. Fix the code
2. Run `python month_end_irswaps_backtest_clean.py`
3. Verify backtest completes without AttributeError
4. Check that all 40 triggers fire correctly

**Estimated Time**: 30 minutes

---

## P1 - High Priority Issues

### Task 2: Fix Syntax Error in test_em_fx_carry.py
**Status**: 🟡 HIGH PRIORITY
**File**: `tests/unit/signals/test_em_fx_carry.py:194`
**Error**: `SyntaxError: invalid syntax`

#### Fix
```python
# Line 194 - Remove space in class name
class TestEMFXCrossSectional:  # was: TestEMFXCrossSecti onal
    """Test cross-sectional EM FX carry ranking."""
```

#### Test Plan
1. Fix syntax error
2. Run `python -m pytest tests/unit/signals/test_em_fx_carry.py -v`
3. Verify tests collect and run

**Estimated Time**: 5 minutes

---

### Task 3: Complete venv Dependency Installation
**Status**: 🟡 PARTIALLY RESOLVED
**Issue**: Missing dependencies prevent imports

#### What Was Missing (and manually installed)
- polars==1.35.2
- pyarrow==21.0.0
- pyyaml
- scipy>=1.10.0
- scikit-learn==1.7.2
- cvxpy==1.6.0
- pytest, pytest-cov

#### Remaining Items to Verify
1. Check if yfinance builds correctly (known multitasking issues on some systems)
2. Verify all requirements.txt packages install cleanly
3. Document any packages that fail to build

#### Action Items
```bash
# 1. Fresh venv install test
source venv/bin/activate
pip install -r requirements.txt 2>&1 | tee install_log.txt

# 2. Check for failures
grep -i error install_log.txt

# 3. Verify imports
python test_basic_workflow.py
```

**Estimated Time**: 15 minutes

---

## P2 - Medium Priority (Production Quality)

### Task 4: Run Full Test Suite and Document Failures
**Status**: 🟡 UNKNOWN COVERAGE
**Current**: 19/19 smoke tests pass, unit test status unknown

#### Action Items
1. Run full unit test suite:
   ```bash
   source venv/bin/activate
   python -m pytest tests/unit/ -v --tb=short --maxfail=10 > test_results.txt 2>&1
   ```

2. Analyze failures:
   - Categorize by type (import, logic, data)
   - Identify patterns
   - Prioritize fixes

3. Document test coverage:
   ```bash
   python -m pytest tests/unit/ --cov=. --cov-report=term-missing
   ```

**Expected Issues**:
- More datetime type mismatches
- Missing test data files
- Hardcoded paths
- Network-dependent tests

**Estimated Time**: 2-3 hours (including fixes)

---

### Task 5: Validate Market Data Providers
**Status**: 🟢 CME WORKING, 🟡 OTHERS UNKNOWN

#### Verified
- ✅ CME_NY_EOD_LIVE-ql_basic (cached data works)

#### Need Testing
- ❓ SDR_INTRADAY sources
- ❓ GSQUANT sources
- ❓ Fixed rate bonds sources
- ❓ Yahoo Finance (may have build issues)
- ❓ AlphaVantage FX

#### Test Plan
```bash
# Test each MDP source with a simple query
python -c "
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
import datetime

sources = [
    'CME_NY_EOD_LIVE-ql_basic',
    'CME_NY_EOD_LIVE-rl_basic',
    # Add others...
]

for source in sources:
    try:
        mdp = IRSwapsMDP(source=source)
        print(f'✓ {source}')
    except Exception as e:
        print(f'✗ {source}: {e}')
"
```

**Estimated Time**: 1 hour

---

### Task 6: Verify Notebook Examples Run End-to-End
**Status**: 🟡 UNKNOWN

#### Notebooks to Test
- `curve_builds.ipynb`
- `fomc_fly_backtest.ipynb`
- `simple_irswaps_backtest.ipynb`
- `intraday_swaps.ipynb`
- Others in root directory

#### Test Process
```bash
# Convert to script and run
jupyter nbconvert --to script notebook.ipynb
python notebook.py
```

**Expected Issues**:
- Same datetime mismatch as backtests
- Missing data files
- Hardcoded paths

**Estimated Time**: 2-3 hours

---

## P3 - Low Priority (Nice to Have)

### Task 7: Documentation Updates
- Update ARBS_ARCHITECTURE.md with any architecture changes discovered
- Document datetime handling conventions
- Add troubleshooting section for common sandbox issues
- Create QUICKSTART.md with verified setup steps

**Estimated Time**: 1-2 hours

---

### Task 8: Performance Validation
- Test curve build caching (ZODB)
- Verify parallel curve building works
- Benchmark backtest performance on longer periods
- Check memory usage on large portfolios

**Estimated Time**: 2-3 hours

---

## Recommended Execution Order

### Phase 1: Get to Minimal Working (60-90 minutes)
1. Fix datetime type mismatch (Task 1) - **30 min**
2. Fix syntax error (Task 2) - **5 min**
3. Verify dependencies (Task 3) - **15 min**
4. Run sample backtest successfully - **10 min**
5. Run unit tests to baseline (Task 4 partial) - **30 min**

**Checkpoint**: Month-end backtest runs to completion

### Phase 2: Production Quality (3-4 hours)
6. Fix all unit test failures (Task 4 continued)
7. Validate all MDP sources (Task 5)
8. Test notebook examples (Task 6)

**Checkpoint**: All tests pass, all examples run

### Phase 3: Documentation & Performance (2-3 hours)
9. Update documentation (Task 7)
10. Performance validation (Task 8)

**Checkpoint**: Production ready

---

## Known Environment Issues

### Sandbox-Specific
1. **pytest** resolves to anaconda3 even after `source venv/bin/activate`
   - **Workaround**: Use `python -m pytest` instead of `pytest`

2. **CME data fetch** requires network access (may be restricted)
   - **Workaround**: Use cached data only (demonstrated in test_cme_fetch.py)

3. **Virtual environment** requires manual dependency installation
   - **Fix**: Run `pip install -r requirements.txt`

### General ARBS Issues
1. **Type inconsistency** between date and datetime objects throughout codebase
2. **Test coverage** unknown - need full test suite run
3. **Documentation** may be outdated (last update references show Oct 2024 commits)

---

## Success Criteria

### Minimal Working (Phase 1)
- [ ] `python test_basic_workflow.py` passes (8/8 checks) ✅ DONE
- [ ] `python month_end_irswaps_backtest_clean.py` completes without errors
- [ ] Core unit tests pass (smoke tests ✅, others TBD)

### Production Quality (Phase 2)
- [ ] All unit tests pass or failures documented as known issues
- [ ] At least 3 MDP sources verified working
- [ ] At least 2 example notebooks run end-to-end

### Production Ready (Phase 3)
- [ ] Documentation updated and accurate
- [ ] Performance benchmarks documented
- [ ] Setup process verified on clean environment

---

## Next Steps

**Immediate Action** (next 30 minutes):
1. Fix datetime type mismatch in `BT/triggers.py:154`
2. Test with month_end_irswaps_backtest_clean.py
3. Report results

**If successful**, proceed to:
4. Fix syntax error in test_em_fx_carry.py
5. Run full unit test suite
6. Document additional failures
