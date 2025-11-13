# Next Steps: Parallel Execution Plan

## Status: READY FOR PARALLEL EXECUTION
Created: 2025-11-13
Branch: Will merge current → create new branches for parallel work

## Executive Summary

Generic Backtest is complete and tested (18/18 tests passing). Next phase focuses on:
1. **Migration**: Move examples/tests to generic Backtest
2. **Showcase**: Create standalone examples demonstrating capabilities
3. **Validation**: Integration tests with realistic workflows
4. **Documentation**: Capture patterns and research next features

All tasks designed to be **orthogonal** - different files, no shared state, parallel execution safe.

---

## Task Decomposition (5 Parallel Streams)

### Stream 1: Example Migration & Creation
**Agent**: `general-purpose`
**Complexity**: Medium (30-45 min)
**Why this agent**: Multiple file operations, needs to understand code patterns

**Tasks**:
1. Create `examples/run_generic_backtest.py` with three patterns:
   - Futures carry (baseline)
   - Equity momentum (new capability)
   - Multi-signal combination (new capability)

2. Update `examples/run_minimal_backtest.py`:
   - Add comment: "Legacy example - see run_generic_backtest.py for new code"
   - Keep functional for backwards compatibility testing

3. Create `examples/README.md`:
   - Document when to use which example
   - Show migration path from MinimalBacktest → Backtest

**Files touched**:
- `examples/run_generic_backtest.py` (new)
- `examples/run_minimal_backtest.py` (comment only)
- `examples/README.md` (new)

**Success criteria**:
- All examples run without errors
- Outputs are valid BacktestResult objects
- README clearly explains usage patterns

**Orthogonality**: Only touches `examples/` directory

---

### Stream 2: Integration Test Migration
**Agent**: `general-purpose`
**Complexity**: Medium (30-45 min)
**Why this agent**: Needs to understand test patterns and refactor safely

**Tasks**:
1. Create `tests/integration/test_generic_backtest_workflows.py`:
   - Test futures carry end-to-end
   - Test equity momentum end-to-end
   - Test multi-signal futures strategy
   - Test DataFrame workflow with real-like data

2. Update `tests/integration/test_multi_signal_strategy.py`:
   - Migrate to use generic Backtest instead of MinimalBacktest
   - Verify same results (backwards compatibility)

3. Create `tests/integration/test_backtest_migration_compatibility.py`:
   - Side-by-side comparison: MinimalBacktest vs Backtest
   - Verify results match for futures carry strategies
   - Document any acceptable differences

**Files touched**:
- `tests/integration/test_generic_backtest_workflows.py` (new)
- `tests/integration/test_multi_signal_strategy.py` (modify)
- `tests/integration/test_backtest_migration_compatibility.py` (new)

**Success criteria**:
- All integration tests pass
- MinimalBacktest and Backtest produce matching results for carry strategy
- Test coverage for all three workflow patterns

**Orthogonality**: Only touches `tests/integration/` directory

---

### Stream 3: Notebook Showcase Updates
**Agent**: `general-purpose`
**Complexity**: High (60-90 min)
**Why this agent**: Needs to understand notebook context and demonstrate features

**Priority Notebooks** (pick 3 for parallel execution):

**3A: Notebook 07 - Momentum Strategy**
- Currently may use MinimalBacktest (check)
- Update to showcase generic Backtest with MomentumSignal
- Demonstrate both futures and equity momentum
- Show DataFrame workflow

**3B: Notebook 08 - Multi-Factor Strategy**
- Update to showcase multi-signal capability
- Combine CarrySignal + MomentumSignal + MeanReversionSignal
- Demonstrate SignalCombiner with different methods (equal, ic_weighted)
- Show how to analyze signal contributions

**3C: Notebook 02 - Strategy Comparison**
- Add section comparing workflow types
- Show same strategy (e.g., momentum) on futures vs equities
- Demonstrate flexibility of generic Backtest
- Performance comparison across workflows

**Files touched**:
- `notebooks/07_momentum_strategy_complete.ipynb` (modify)
- `notebooks/08_multi_factor_strategy.ipynb` (modify)
- `notebooks/02_strategy_comparison.ipynb` (modify)

**Success criteria**:
- All notebooks execute without errors
- Each demonstrates unique generic Backtest capability
- Clear explanations of new features
- Results are interpretable and meaningful

**Orthogonality**: Each notebook is independent, can be updated in parallel

---

### Stream 4: Performance & Validation Testing
**Agent**: `general-purpose`
**Complexity**: Medium (45-60 min)
**Why this agent**: Needs to design tests and analyze performance

**Tasks**:
1. Create `tests/performance/test_backtest_performance.py`:
   - Benchmark generic Backtest vs MinimalBacktest (should be similar)
   - Test with varying numbers of instruments (10, 50, 100)
   - Test with varying date ranges (1 month, 1 year, 5 years)
   - Identify any performance regressions

2. Create `tests/golden/test_backtest_golden.py`:
   - Golden file tests for known scenarios
   - Futures carry strategy with specific contracts/dates
   - Equity momentum with known returns
   - Multi-signal combination
   - Validates exact numerical results don't drift

3. Create `tests/validation/test_signal_generation.py`:
   - Validate per-instrument signal generation is correct
   - Test signal combiner produces expected combinations
   - Verify standardization (z-scores) works correctly
   - Check edge cases (single instrument, zero variance signals)

**Files touched**:
- `tests/performance/test_backtest_performance.py` (new)
- `tests/golden/test_backtest_golden.py` (new)
- `tests/validation/test_signal_generation.py` (new)
- `tests/golden/data/` (new golden files)

**Success criteria**:
- Performance within 10% of MinimalBacktest baseline
- Golden tests establish reproducible results
- All edge cases handled correctly
- No numerical instabilities

**Orthogonality**: Only touches `tests/performance/`, `tests/golden/`, `tests/validation/`

---

### Stream 5: Documentation & Research
**Agent**: `general-purpose`
**Complexity**: Medium (45-60 min)
**Why this agent**: Research and documentation synthesis

**Tasks**:
1. Create `docs/BACKTEST_USAGE_GUIDE.md`:
   - When to use generic Backtest vs MinimalBacktest
   - Complete API reference for Backtest class
   - Common patterns and recipes
   - Troubleshooting guide
   - Migration guide from MinimalBacktest

2. Create `docs/SIGNAL_COMBINER_GUIDE.md`:
   - How to combine multiple signals
   - Equal weight vs IC-weighted vs orthogonalization
   - When to use each method
   - Examples with interpretation

3. Research next features (document findings):
   - Transaction costs modeling: proportional + quadratic impact
   - DV01 constraints: how to implement for fixed income
   - Cardinality constraints: L0 penalty for limiting positions
   - Advanced covariance: 3-factor PCA, nodewise regression
   - Create `docs/FUTURE_ENHANCEMENTS_RESEARCH.md` with findings

**Files touched**:
- `docs/BACKTEST_USAGE_GUIDE.md` (new)
- `docs/SIGNAL_COMBINER_GUIDE.md` (new)
- `docs/FUTURE_ENHANCEMENTS_RESEARCH.md` (new)

**Success criteria**:
- Complete API documentation
- Clear usage patterns with examples
- Research findings are actionable
- Migration guide has step-by-step instructions

**Orthogonality**: Only touches `docs/` directory

---

## Execution Strategy

### Phase 1: Launch Parallel Streams (5 agents simultaneously)
```bash
# Agent 1: Example Migration
task-decomposer → Stream 1 tasks → parallel-executor

# Agent 2: Integration Tests
task-decomposer → Stream 2 tasks → parallel-executor

# Agent 3: Notebooks
task-decomposer → Stream 3 tasks → parallel-executor

# Agent 4: Performance/Validation
task-decomposer → Stream 4 tasks → parallel-executor

# Agent 5: Documentation/Research
task-decomposer → Stream 5 tasks → parallel-executor
```

### Phase 2: Integration & Validation (after parallel completion)
- Run full test suite (unit + integration + performance)
- Verify all notebooks execute
- Check documentation completeness
- Merge to main

### Phase 3: Create PR
- Comprehensive PR description
- Reference all parallel work streams
- Include performance benchmarks
- Link to updated documentation

---

## Branch Strategy

**Current Branch**: `claude/verify-integration-notebook-011CV66ZrAdcoGXccRY1Up3E`
- Contains: Generic Backtest implementation (18 tests passing)
- Action: Merge to main after review

**New Branch**: `claude/backtest-adoption-and-validation-[SESSION_ID]`
- Contains: All 5 parallel streams
- Created after current branch merged

---

## Risk Mitigation

**Risk**: Parallel agents modify same file
- **Mitigation**: Task decomposition ensures orthogonal file access
- **Verification**: No file appears in multiple streams

**Risk**: Integration tests reveal bugs in generic Backtest
- **Mitigation**: Stream 2 & 4 designed to catch issues early
- **Action**: Fix bugs before proceeding to notebooks

**Risk**: Performance regression
- **Mitigation**: Stream 4 benchmarks performance
- **Action**: Optimize if >10% slower than MinimalBacktest

**Risk**: Documentation becomes stale
- **Mitigation**: Stream 5 happens in parallel, uses latest code
- **Action**: Review docs after all code changes complete

---

## Success Metrics

**Code Quality**:
- All tests passing (unit + integration + performance + golden)
- Code coverage >90% for new code
- No performance regression vs MinimalBacktest

**Adoption**:
- 3+ working examples demonstrating capabilities
- 3+ notebooks showcasing generic Backtest
- Clear migration path documented

**Validation**:
- Golden file tests establish numerical baselines
- Integration tests prove real-world workflows
- Performance tests show scalability

**Documentation**:
- Complete API reference
- Usage guide with recipes
- Research findings for next phase

---

## Estimated Timeline

**Parallel Execution**: 60-90 minutes (5 agents working simultaneously)
**Integration & Validation**: 30 minutes (sequential)
**PR Creation & Review**: 30 minutes (sequential)

**Total**: ~2-3 hours with parallel execution
(vs ~6-8 hours sequential)

---

## Next Steps After This Plan

1. **Merge current branch** to main (generic Backtest foundation)
2. **Create new branch** for parallel work
3. **Launch 5 parallel agents** with tasks from streams above
4. **Monitor progress** using phoenix-interrupting pattern
5. **Integrate results** using integration-synthesizer
6. **Create PR** with comprehensive changes

---

## Notes

- All tasks designed to be orthogonal (no file conflicts)
- Each stream has clear success criteria
- Parallel execution maximizes throughput
- Integration phase ensures everything works together
- Documentation captures learnings for future development
