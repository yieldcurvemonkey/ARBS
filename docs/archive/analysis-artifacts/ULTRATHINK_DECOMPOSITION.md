# Ultrathink: Orthogonal Task Decomposition

**Timestamp**: 2025-11-16 01:50 UTC
**Goal**: Decompose validation plan into parallel executable tasks
**Principle**: Maximum parallelism, zero dependencies

---

## Decomposition Strategy

### Why Orthogonal?
Traditional approach: Sequential validation (component → integration → real data)
Orthogonal approach: Validate all layers simultaneously

**Key Insight**: Most validation tasks are independent. We can run 20+ tasks in parallel.

---

## Task Taxonomy

### Dimension 1: Component (What to validate)
- Covariance estimators (6 classes)
- Optimizers (3 classes)
- Signals (5 types)
- Portfolio accounting (1 class)
- Backtest orchestration (1 class)

### Dimension 2: Method (How to validate)
- Ground truth (hand-calculated examples)
- Reference comparison (vs sklearn/cvxpy)
- Numerical stability (ill-conditioned inputs)
- Property testing (algebraic properties)
- Real data (market sanity checks)

### Dimension 3: Source (What to compare against)
- Textbooks (Grinold-Kahn, Markowitz)
- Academic papers (Ledoit-Wolf 2004, etc.)
- Reference libraries (sklearn, cvxpy, QuantLib)
- Market data (SOFR futures, Treasury bonds)

---

## Orthogonal Task Matrix

Each cell is an independent task that can run in parallel:

| Component | Ground Truth | Reference | Numerical | Integration | Real Data |
|-----------|--------------|-----------|-----------|-------------|-----------|
| **SampleCovariance** | ✅ Task 1 | ✅ Task 7 | ✅ Task 13 | ✅ Task 19 | ✅ Task 25 |
| **LedoitWolf** | ✅ Task 2 | ✅ Task 8 | ✅ Task 14 | ✅ Task 20 | ✅ Task 26 |
| **OAShrinkage** | ✅ Task 3 | ✅ Task 9 | ✅ Task 15 | ✅ Task 21 | ✅ Task 27 |
| **MeanVarianceOpt** | ✅ Task 4 | ✅ Task 10 | ✅ Task 16 | ✅ Task 22 | ✅ Task 28 |
| **CarrySignal** | ✅ Task 5 | ✅ Task 11 | ✅ Task 17 | ✅ Task 23 | ✅ Task 29 |
| **Portfolio** | ✅ Task 6 | ✅ Task 12 | ✅ Task 18 | ✅ Task 24 | ✅ Task 30 |

**Total: 30 parallel tasks**

Each task is 1-2 hours of work. With parallel agents, complete in <4 hours.

---

## Task Specifications

### Task Group 1: Ground Truth Validation (Tasks 1-6)
**Effort**: 1 hour each
**Dependencies**: None
**Output**: Test file with hand-calculated examples

#### Task 1: SampleCovariance Ground Truth
```python
# tests/validation/covariance/test_sample_ground_truth.py
def test_2x2_known_values():
    """Hand-calculated 2×2 covariance matrix."""
    returns = pl.DataFrame({
        'A': [0.01, 0.02, -0.01],
        'B': [0.02, 0.01, -0.02]
    })

    estimator = SampleCovariance()
    cov = estimator.fit(returns)

    # Manually calculated:
    # Var(A) = 0.00023333
    # Var(B) = 0.00033333
    # Cov(A,B) = 0.00026667
    expected = np.array([
        [0.00023333, 0.00026667],
        [0.00026667, 0.00033333]
    ])

    np.testing.assert_allclose(cov, expected, rtol=1e-4)
```

#### Task 2: LedoitWolf Ground Truth
```python
def test_ledoit_wolf_simple_case():
    """Simple case where shrinkage is exact."""
    # Create returns where optimal shrinkage is known
    returns = create_ledoit_wolf_test_case(
        true_shrinkage=0.5
    )

    estimator = LedoitWolfShrinkage()
    cov = estimator.fit(returns)

    # Shrinkage intensity should be close to 0.5
    assert abs(estimator.shrinkage_ - 0.5) < 0.05
```

#### Task 3-6: Similar for OAS, Optimizer, Signal, Portfolio

---

### Task Group 2: Reference Comparison (Tasks 7-12)
**Effort**: 1-2 hours each
**Dependencies**: None (reference libraries already installed)
**Output**: Test file comparing to sklearn/cvxpy/QuantLib

#### Task 7: SampleCovariance vs NumPy
```python
def test_sample_cov_matches_numpy():
    """Should match np.cov exactly."""
    returns = generate_random_returns(100, 20)

    our_cov = SampleCovariance().fit(returns)

    numpy_cov = np.cov(returns.to_numpy(), rowvar=False, ddof=1)

    np.testing.assert_allclose(our_cov, numpy_cov, rtol=1e-12)
```

#### Task 8: LedoitWolf vs sklearn
```python
def test_ledoit_wolf_matches_sklearn():
    """Should match sklearn.covariance.LedoitWolf."""
    from sklearn.covariance import LedoitWolf

    returns = generate_random_returns(100, 20)

    our_lw = LedoitWolfShrinkage()
    our_cov = our_lw.fit(returns)

    sk_lw = LedoitWolf()
    sk_cov = sk_lw.fit(returns.to_numpy())

    np.testing.assert_allclose(our_cov, sk_cov, rtol=1e-8)
    np.testing.assert_allclose(
        our_lw.shrinkage_,
        sk_lw.shrinkage_,
        rtol=1e-6
    )
```

#### Task 10: MeanVarianceOptimizer vs cvxpy
```python
def test_optimizer_matches_cvxpy():
    """Should match cvxpy QP solver."""
    import cvxpy as cp

    alphas = np.random.randn(30)
    cov = generate_random_psd(30)
    risk_aversion = 2.5

    # Our implementation
    our_opt = MeanVarianceOptimizer(risk_aversion=risk_aversion)
    our_weights = our_opt.optimize(alphas, cov)

    # cvxpy reference
    w = cp.Variable(30)
    obj = cp.Maximize(
        alphas @ w - (risk_aversion/2) * cp.quad_form(w, cov)
    )
    prob = cp.Problem(obj, [cp.sum(w) == 1.0])
    prob.solve()

    np.testing.assert_allclose(our_weights, w.value, rtol=1e-6)
```

---

### Task Group 3: Numerical Stability (Tasks 13-18)
**Effort**: 1 hour each
**Dependencies**: None
**Output**: Test file with edge cases

#### Task 13: SampleCovariance Numerical
```python
def test_sample_cov_singular_returns():
    """Handle perfectly correlated returns."""
    # Two identical columns → singular
    returns = pl.DataFrame({
        'A': [0.01, 0.02, 0.03],
        'B': [0.01, 0.02, 0.03],  # Identical to A
        'C': [0.02, 0.01, 0.00]
    })

    cov = SampleCovariance().fit(returns)

    # Should be singular (det ≈ 0)
    assert abs(np.linalg.det(cov)) < 1e-10

    # But still symmetric and PSD
    assert np.allclose(cov, cov.T)
    assert np.all(np.linalg.eigvals(cov) >= -1e-10)
```

#### Task 14: LedoitWolf Numerical
```python
def test_ledoit_wolf_ill_conditioned():
    """Handle ill-conditioned sample covariance."""
    # Create nearly singular sample covariance
    returns = create_ill_conditioned_returns(condition=1e8)

    estimator = LedoitWolfShrinkage()
    cov = estimator.fit(returns)

    # After shrinkage should be well-conditioned
    assert np.linalg.cond(cov) < 1e4
```

---

### Task Group 4: Integration Tests (Tasks 19-24)
**Effort**: 2 hours each
**Dependencies**: None (use fixtures)
**Output**: End-to-end validation tests

#### Task 19: SampleCovariance in Backtest
```python
def test_sample_cov_end_to_end():
    """Sample covariance in full backtest workflow."""
    mdp = create_test_mdp()
    backtest = Backtest(
        mdp=mdp,
        adapter=FuturesAdapter(mdp),
        signals=CarrySignal(),
        risk_model=SampleCovariance(),
        optimizer=MeanVarianceOptimizer()
    )

    result = backtest.run(
        contracts=['SFRZ4', 'SFRH5', 'SFRM5'],
        dates=[date(2024, 6, 15)]
    )

    # Basic sanity checks
    assert len(result.weights) > 0
    assert abs(sum(result.weights.values()) - 1.0) < 1e-6
```

#### Task 22: MeanVarianceOptimizer Integration
```python
def test_optimizer_with_real_signals():
    """Optimizer with actual signal/covariance inputs."""
    # Use real signal generation
    signal = CarrySignal()
    alphas = signal.calculate(...)

    # Use real covariance estimation
    risk_model = LedoitWolfShrinkage()
    cov = risk_model.fit(returns)

    # Optimize
    optimizer = MeanVarianceOptimizer(risk_aversion=2.0)
    weights = optimizer.optimize(alphas, cov)

    # Validate properties
    assert abs(weights.sum() - 1.0) < 1e-6
    portfolio_risk = np.sqrt(weights @ cov @ weights)
    assert portfolio_risk < returns.std().mean()  # Diversification
```

---

### Task Group 5: Real Data Tests (Tasks 25-30)
**Effort**: 2 hours each
**Dependencies**: Market data access
**Output**: Real-world validation tests

#### Task 25: SampleCovariance Real Data
```python
def test_sample_cov_sofr_futures():
    """Sample covariance on real SOFR futures data."""
    # Load real market data
    returns = load_sofr_futures_returns(
        start='2023-01-01',
        end='2024-01-01'
    )

    cov = SampleCovariance().fit(returns)

    # Sanity checks
    assert cov.shape == (len(returns.columns), len(returns.columns))

    # Correlation should be positive (futures in same sector)
    corr = cov_to_corr(cov)
    assert np.all(corr >= 0)  # No negative correlations
    assert np.median(corr[~np.eye(len(corr), dtype=bool)]) > 0.5
```

#### Task 29: CarrySignal Real Data
```python
def test_carry_signal_sofr_futures():
    """Carry signal on real SOFR data."""
    mdp = YahooFinanceMDP()
    signal = CarrySignal()

    signals_dict = signal.calculate(
        instruments=['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5'],
        market_data=mdp,
        as_of=date(2024, 6, 15)
    )

    # Sanity checks
    signals = np.array(list(signals_dict.values()))
    assert len(signals) <= 4  # Some might fail

    # Should be approximately standardized
    assert abs(signals.mean()) < 0.5
    assert 0.5 < signals.std() < 1.5
```

---

## Parallel Execution Plan

### Wave 1: Ground Truth (6 tasks in parallel)
**Time**: 1-2 hours
**Agents**: 6 parallel agents
**Output**: 6 test files with hand-calculated examples

Tasks: 1-6 (SampleCov, LW, OAS, Optimizer, Signal, Portfolio ground truth)

### Wave 2: Reference Comparison (6 tasks in parallel)
**Time**: 1-2 hours
**Agents**: 6 parallel agents
**Output**: 6 test files comparing to sklearn/cvxpy

Tasks: 7-12 (Same components vs reference implementations)

### Wave 3: Numerical Stability (6 tasks in parallel)
**Time**: 1-2 hours
**Agents**: 6 parallel agents
**Output**: 6 test files with edge cases

Tasks: 13-18 (Edge cases and numerical challenges)

### Wave 4: Integration (6 tasks in parallel)
**Time**: 2-3 hours
**Agents**: 6 parallel agents
**Output**: 6 test files for end-to-end workflows

Tasks: 19-24 (Full backtest integration tests)

### Wave 5: Real Data (6 tasks in parallel)
**Time**: 2-3 hours
**Agents**: 6 parallel agents
**Output**: 6 test files with real market data

Tasks: 25-30 (SOFR futures, Treasury bonds, etc.)

---

## Total Timeline

### Sequential Execution: 50-60 hours
- Ground truth: 6 hours
- Reference: 8 hours
- Numerical: 6 hours
- Integration: 12 hours
- Real data: 12 hours
- Documentation: 6 hours

### Parallel Execution: 10-12 hours
- Wave 1: 2 hours
- Wave 2: 2 hours
- Wave 3: 2 hours
- Wave 4: 3 hours
- Wave 5: 3 hours
- Documentation: 2 hours

**Speedup: 5x faster with parallelization**

---

## Task Template

Each task follows this structure:

```python
# tests/validation/{category}/test_{component}_{method}.py

"""
Validation Test: {Component} - {Method}

Component: {SampleCovariance, LedoitWolf, etc.}
Method: {Ground Truth, Reference, Numerical, Integration, Real Data}
Created: {Date}
Agent: {Agent ID}
Status: {✅ Passing / ❌ Failing / ⚠️ Partial}
"""

import pytest
import numpy as np
import polars as pl
from {module} import {Component}

def test_{specific_case}():
    """
    Test description.

    Expected behavior:
    - Input: {describe input}
    - Output: {describe expected output}
    - Validation: {how we validate}
    """
    # Setup
    ...

    # Execute
    ...

    # Validate
    assert ...

def test_{another_case}():
    ...

# Add validation report at end
"""
VALIDATION REPORT
=================
Component: {Component}
Method: {Method}
Tests: {X/Y passing}
Confidence: {0-100%}
Issues: {None / List issues}
"""
```

---

## Success Criteria

### Per-Task Success
- [ ] Test file created
- [ ] All tests passing
- [ ] Code formatted (black/isort)
- [ ] Type hints correct (mypy)
- [ ] Documented (docstrings)

### Wave Success
- [ ] All 6 tasks in wave complete
- [ ] No blocking issues
- [ ] Validation report generated

### Overall Success
- [ ] 30/30 tasks complete
- [ ] All tests passing
- [ ] Confidence scorecard >90%
- [ ] Documentation complete

---

## Risk Management

### Risk: Tests Fail
**Probability**: High (50%)
**Impact**: High (blocks validation)
**Mitigation**:
- Document failures clearly
- Triage: Bug vs misunderstanding
- Fix and retest
- Escalate if fundamental issue

### Risk: Agent Conflicts
**Probability**: Low (tasks are orthogonal)
**Impact**: Low (easy to resolve)
**Mitigation**:
- Each agent works on separate file
- No shared state
- Git merge should be clean

### Risk: Reference Library Issues
**Probability**: Medium (sklearn versions differ)
**Impact**: Medium (can't compare)
**Mitigation**:
- Pin versions in requirements
- Document version used
- Allow small tolerance (rtol=1e-6)

---

## Output Artifacts

### After Each Wave
1. `tests/validation/{category}/` directory
2. Test files for that wave
3. Validation report for that wave
4. Updated confidence scorecard

### Final Deliverables
1. `tests/validation/` complete directory structure
2. 30+ test files (150+ individual tests)
3. Final validation report
4. Confidence scorecard
5. Recommendations document

---

## Next Action

**Launch Wave 1 in parallel:**

6 agents, each taking one task:
- Agent 1: Task 1 (SampleCovariance ground truth)
- Agent 2: Task 2 (LedoitWolf ground truth)
- Agent 3: Task 3 (OAS ground truth)
- Agent 4: Task 4 (Optimizer ground truth)
- Agent 5: Task 5 (CarrySignal ground truth)
- Agent 6: Task 6 (Portfolio ground truth)

**Estimated completion: 1-2 hours**

Then proceed to Wave 2, then 3, then 4, then 5.

**Total validation complete in: 10-12 hours**

---

## Conclusion

**This decomposition achieves:**
1. **Maximum parallelism** - 30 independent tasks
2. **Fast execution** - 5x speedup via parallel agents
3. **Complete coverage** - Every component × every method
4. **Clear structure** - Easy to track progress
5. **Actionable output** - Confidence scorecard drives decisions

**This is the ultrathink decomposition - let's execute.**
