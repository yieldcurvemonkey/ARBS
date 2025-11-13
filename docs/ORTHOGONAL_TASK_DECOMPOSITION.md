# Orthogonal Task Decomposition: Cross-Asset Implementation

**Date**: 2025-11-13
**Status**: Task Decomposition Complete

---

## Executive Summary

**Goal**: Implement 2025 consensus best practices while maintaining ARBS architectural principles.

**Critical finding**: 5 orthogonal task streams identified that can execute in **parallel** with zero dependencies.

**Estimated timeline**:
- **Sequential**: 10-12 weeks
- **Parallel (5 agents)**: **2-3 weeks** (80% time reduction)

**Key insight**: Correlation cluster constraints (Task 1) is **the only CRITICAL dependency** for portfolio optimization. All other tasks are independent.

---

## Orthogonalization Criteria

### Definition

Two tasks are **orthogonal** if:
1. **No shared code files** (different modules)
2. **No data dependencies** (can mock inputs)
3. **Independent testing** (separate test files)
4. **Parallel execution safe** (no merge conflicts)

### Benefits

- **Parallel execution**: Multiple subagents work simultaneously
- **Risk isolation**: Failure in one task doesn't block others
- **Fast iteration**: Complete 10-12 weeks of work in 2-3 weeks
- **Clean integration**: Minimal merge conflicts

---

## Task Stream Identification

### Stream 1: Correlation Clustering (CRITICAL PATH)

**Dependency**: None (foundational)
**Files touched**:
- `Risk/Covariance/SectorBased/BaseSectorCovarianceEstimator.py`
- `Optimizer/ClusterAwareMeanVarianceOptimizer.py` (NEW)
- `tests/unit/risk/covariance/test_correlation_clustering.py` (NEW)
- `tests/unit/optimizer/test_cluster_aware_optimizer.py` (NEW)

**No conflicts with**: All other streams (foundation layer)

---

### Stream 2: Volatility Dispersion

**Dependency**: None (independent module)
**Files touched**:
- `Risk/Volatility/VolatilityRatioCalculator.py` (NEW)
- `Signals/CorrelationVolatilitySignal.py` (NEW)
- `tests/unit/risk/volatility/test_volatility_ratio.py` (NEW)
- `tests/unit/signals/test_correlation_vol_signal.py` (NEW)

**No conflicts with**: Stream 1, 3, 4, 5 (separate module)

---

### Stream 3: Currency Translation Layer

**Dependency**: None (new domain)
**Files touched**:
- `Query/Currencies/CurrencyQuery.py` (NEW)
- `Signals/CurrencyCarrySignal.py` (NEW)
- `tests/unit/query/currencies/test_currency_query.py` (NEW)
- `tests/unit/signals/test_currency_carry_signal.py` (NEW)

**No conflicts with**: Stream 1, 2, 4, 5 (new directory)

---

### Stream 4: ML-Enhanced Factors

**Dependency**: None (signal layer extension)
**Files touched**:
- `Signals/MLPredictedReturnsSignal.py` (NEW)
- `Signals/Utils/FeatureEngineering.py` (NEW)
- `tests/unit/signals/test_ml_predicted_returns.py` (NEW)

**No conflicts with**: Stream 1, 2, 3, 5 (separate signal file)

---

### Stream 5: CVaR Tail Risk Constraints

**Dependency**: None (optimizer extension)
**Files touched**:
- `Optimizer/CVaRMeanVarianceOptimizer.py` (NEW)
- `tests/unit/optimizer/test_cvar_optimizer.py` (NEW)

**No conflicts with**: Stream 1, 2, 3, 4 (separate optimizer class)

---

## Dependency Graph

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  ALL TASKS ARE ORTHOGONAL (No dependencies!)       │
│                                                     │
└─────────────────────────────────────────────────────┘
          │          │          │          │          │
          ▼          ▼          ▼          ▼          ▼
    ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
    │ Task 1  │ │ Task 2  │ │ Task 3  │ │ Task 4  │ │ Task 5  │
    │Cluster  │ │ Vol     │ │Currency │ │ML       │ │CVaR     │
    │Constrai │ │Dispers  │ │Translat │ │Factors  │ │Constra  │
    │nts      │ │ion      │ │ion      │ │         │ │int      │
    └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
          │          │          │          │          │
          ▼          ▼          ▼          ▼          ▼
    ┌─────────────────────────────────────────────────────┐
    │                                                     │
    │        Integration (Sequential, after all)          │
    │                                                     │
    └─────────────────────────────────────────────────────┘
```

**Critical insight**: **Zero dependencies** between tasks → Full parallelization possible.

---

## Detailed Task Specifications

### Task 1: Correlation Cluster Constraints

**Priority**: **CRITICAL**
**Effort**: 1-1.5 weeks (sequential) → **1-1.5 weeks** (parallel, no speedup as it's critical path)
**Business value**: Closes critical gap vs. 2025 consensus

#### Deliverables

1. **Add `get_correlation_clusters()` method**
   - **File**: `Risk/Covariance/SectorBased/BaseSectorCovarianceEstimator.py`
   - **Input**: Correlation matrix, threshold (e.g., 0.85)
   - **Output**: Dict[str, List[str]] mapping cluster_id → list of tickers
   - **Method**: Hierarchical clustering on distance = 1 - |ρ|

2. **Create `ClusterAwareMeanVarianceOptimizer`**
   - **File**: `Optimizer/ClusterAwareMeanVarianceOptimizer.py` (NEW)
   - **Inherits**: `MeanVarianceOptimizer`
   - **New parameter**: `correlation_clusters: Dict[str, List[str]]`, `max_per_cluster: int`
   - **Constraint**: For each cluster C, sum(I(|w_i| > ε) for i in C) ≤ max_per_cluster
   - **Method**: CVXPY indicator constraints

3. **Write comprehensive tests**
   - **File**: `tests/unit/risk/covariance/test_correlation_clustering.py` (NEW)
   - **Tests**:
     - Perfect block-diagonal (3 clusters, ρ_within=0.95, ρ_across=0.0)
     - Overlapping clusters (ρ > threshold for multiple pairs)
     - Edge cases (single-asset clusters, all assets in one cluster)

   - **File**: `tests/unit/optimizer/test_cluster_aware_optimizer.py` (NEW)
   - **Tests**:
     - Constraint binds correctly (verifies max_per_cluster enforced)
     - Optimization converges (runtime < 1s for 50 assets)
     - Objective value decreases vs. unconstrained (tradeoff exists)

4. **Example script**
   - **File**: `examples/cluster_aware_portfolio.py` (NEW)
   - **Demonstrates**:
     - Load equity sector ETF data (XLK, XLF, XLE, ...)
     - Calculate correlation matrix
     - Detect clusters
     - Optimize with cluster constraints
     - Show constraint enforcement (print positions per cluster)

#### Acceptance Criteria

- ✅ `get_correlation_clusters()` returns valid cluster assignments
- ✅ Clusters match expected structure (high intra-cluster ρ, low inter-cluster ρ)
- ✅ Optimizer enforces constraints (tests verify)
- ✅ Example script runs end-to-end
- ✅ Documentation updated (docstrings, user guide)

#### Agent Instructions

```
Implement correlation cluster constraints in portfolio optimization.

**Context**: 2025 consensus requires limiting positions per correlation cluster
to prevent concentration risk (e.g., can't short 5Y in every correlated currency).

**Tasks**:
1. Add get_correlation_clusters() to BaseSectorCovarianceEstimator
   - Use hierarchical clustering (scipy.cluster.hierarchy)
   - Distance = 1 - |correlation|
   - Return Dict[cluster_id, List[ticker]]

2. Create ClusterAwareMeanVarianceOptimizer
   - Inherit from MeanVarianceOptimizer
   - Add cluster constraints via CVXPY
   - Constraint: sum(indicator(|w_i| > 0.01) for i in cluster) <= max_per_cluster

3. Write tests (TDD approach)
   - Synthetic data: 3 clusters, verify constraints bind
   - Real data: SPDR sector ETFs
   - Edge cases: empty clusters, all in one cluster

4. Create example script
   - Load sector ETF data (2015-2024)
   - Calculate correlation matrix
   - Detect clusters (threshold=0.85)
   - Optimize with constraints (max_per_cluster=3)
   - Print results showing constraint enforcement

**Success criteria**:
- All tests pass (>= 15 new tests)
- Example script runs successfully
- Documentation complete
- Code follows CLAUDE.md guidelines (TDD, ABOUTME comments, type hints)

**Deliverables**:
- Modified: Risk/Covariance/SectorBased/BaseSectorCovarianceEstimator.py
- New: Optimizer/ClusterAwareMeanVarianceOptimizer.py
- New: tests/unit/risk/covariance/test_correlation_clustering.py
- New: tests/unit/optimizer/test_cluster_aware_optimizer.py
- New: examples/cluster_aware_portfolio.py
```

---

### Task 2: Volatility Dispersion Trading

**Priority**: **HIGH**
**Effort**: 2-3 weeks (sequential) → **2-3 weeks** (parallel, no speedup as independent)
**Business value**: New alpha source (23-point spread in Oct 2025)

#### Deliverables

1. **Create `VolatilityRatioCalculator`**
   - **File**: `Risk/Volatility/VolatilityRatioCalculator.py` (NEW)
   - **Input**: Returns (realized), implied_vols (from options)
   - **Output**: DataFrame with [ticker, date, RV, IV, IV_RV_ratio]
   - **Method**: RV = std(returns) × √252, ratio = IV / RV

2. **Create `CorrelationVolatilitySignal`**
   - **File**: `Signals/CorrelationVolatilitySignal.py` (NEW)
   - **Inherits**: `BaseSignal`
   - **Logic**: For pairs with ρ > 0.85, signal = (IV_RV_B - IV_RV_A) × ρ
   - **Output**: DataFrame with [pair, correlation, spread, z_score, signal]

3. **Write comprehensive tests**
   - **File**: `tests/unit/risk/volatility/test_volatility_ratio.py` (NEW)
   - **Tests**:
     - RV calculation matches manual computation
     - IV/RV ratio correct
     - Edge cases (zero vol, missing data)

   - **File**: `tests/unit/signals/test_correlation_vol_signal.py` (NEW)
   - **Tests**:
     - Signal generation for high-correlation pairs
     - Z-score normalization correct
     - Direction (sell_B_vol vs sell_A_vol) correct

4. **Backtest on equity sectors**
   - **File**: `examples/vol_dispersion_backtest.py` (NEW)
   - **Universe**: SPDR sector ETFs (XLK, XLF, XLE, ...)
   - **Data**: 2015-2024 (needs options data source)
   - **Metrics**: Sharpe, IC, turnover
   - **Target**: Sharpe > 0.7 (per academic research)

#### Acceptance Criteria

- ✅ IV/RV ratios calculated correctly (validated against market data)
- ✅ Signal generation works (z-scores valid)
- ✅ Backtest runs end-to-end
- ✅ Results documented (Sharpe, IC, turnover)
- ✅ Code follows TDD (tests written first)

#### Agent Instructions

```
Implement volatility dispersion trading strategy.

**Context**: 2025 market shows 23-point spread between implied constituent vol
and index vol. Academic research shows consistent profitability when trading
IV/RV ratio convergence across correlated assets.

**Tasks**:
1. Create VolatilityRatioCalculator
   - Calculate realized vol: RV = std(returns) * sqrt(252)
   - Calculate IV/RV ratio per asset
   - Return time series DataFrame

2. Create CorrelationVolatilitySignal (inherits BaseSignal)
   - For pairs with correlation > 0.85:
     - Calculate spread: IV_RV_B - IV_RV_A
     - Z-score the spread (lookback=60)
     - Signal = |z_score| * correlation
   - When |z_score| > 2: generate trade signal

3. Write tests (TDD approach)
   - Test RV calculation
   - Test IV/RV ratio computation
   - Test signal generation for synthetic correlated assets
   - Test edge cases (zero vol, missing data)

4. Create backtest example
   - Universe: SPDR sector ETFs (need options data)
   - Calculate correlations, IV/RV ratios
   - Generate signals
   - Simulate P&L
   - Report Sharpe, IC, turnover

**Success criteria**:
- All tests pass (>= 12 new tests)
- Backtest achieves Sharpe > 0.7 (target from research)
- Documentation complete
- Code follows CLAUDE.md guidelines

**Deliverables**:
- New: Risk/Volatility/VolatilityRatioCalculator.py
- New: Signals/CorrelationVolatilitySignal.py
- New: tests/unit/risk/volatility/test_volatility_ratio.py
- New: tests/unit/signals/test_correlation_vol_signal.py
- New: examples/vol_dispersion_backtest.py

**Note**: Options data source needed (IVolatility, CBOE, or mock for testing).
```

---

### Task 3: Currency Translation Layer

**Priority**: **HIGH**
**Effort**: 1.5 weeks (sequential) → **1.5 weeks** (parallel, no speedup)
**Business value**: Validates cross-asset framework

#### Deliverables

1. **Create `CurrencyQuery`**
   - **File**: `Query/Currencies/CurrencyQuery.py` (NEW)
   - **Analogous to**: `EquityQuery`
   - **Fields**: currency (USD, EUR, GBP), tenor (2Y, 5Y, 10Y, 30Y), structure
   - **Method**: Inherits `BaseQuery`, implements abstract methods

2. **Create `CurrencyCarrySignal`**
   - **File**: `Signals/CurrencyCarrySignal.py` (NEW)
   - **Analogous to**: `SectorMomentumSignal`
   - **Logic**: Carry = forward_rate - spot_rate
   - **Output**: Z-scored carry signals per currency-tenor

3. **Write comprehensive tests**
   - **File**: `tests/unit/query/currencies/test_currency_query.py` (NEW)
   - **Tests**:
     - Query creation and validation
     - Abstract method implementations
     - Structure types (OUTRIGHT, BUTTERFLY, etc.)

   - **File**: `tests/unit/signals/test_currency_carry_signal.py` (NEW)
   - **Tests**:
     - Carry calculation correct
     - Z-score normalization
     - Cross-currency neutralization

4. **Example script**
   - **File**: `examples/currency_rotation_backtest.py` (NEW)
   - **Universe**: USD, EUR, GBP, CHF (2Y, 5Y, 10Y)
   - **Signal**: Carry + mean reversion
   - **Portfolio**: Long top 3 butterflies, short bottom 3
   - **Metrics**: Sharpe, IC, DV01-neutral enforcement

#### Acceptance Criteria

- ✅ `CurrencyQuery` creates valid queries
- ✅ `CurrencyCarrySignal` generates z-scores
- ✅ Example backtest runs end-to-end
- ✅ Results validate sector ↔ currency equivalence
- ✅ Code structure mirrors equity implementation

#### Agent Instructions

```
Create currency translation layer to validate cross-asset framework.

**Context**: Sector rotation strategies map directly to currency carry strategies.
This task proves the equivalence by implementing currency versions of equity classes.

**Tasks**:
1. Create CurrencyQuery (analogous to EquityQuery)
   - Dataclass with: currency, tenor, structure
   - Inherits BaseQuery
   - Implement abstract methods: return_query, col_name, eval_expression
   - Structure types: OUTRIGHT, BUTTERFLY, SPREAD

2. Create CurrencyCarrySignal (analogous to SectorMomentumSignal)
   - Inherits BaseSignal
   - Calculate carry: forward_rate - spot_rate
   - Z-score normalization (cross-currency neutral)
   - Output: signals per currency-tenor

3. Write tests (TDD approach)
   - Test query creation
   - Test carry calculation
   - Test z-score normalization
   - Test cross-currency neutralization

4. Create example backtest
   - Universe: USD, EUR, GBP, CHF (2Y, 5Y, 10Y)
   - Signal: Carry + mean reversion
   - Portfolio: Top-3/bottom-3 butterflies
   - Constraints: DV01-neutral
   - Metrics: Sharpe, IC, turnover

**Success criteria**:
- All tests pass (>= 10 new tests)
- Example backtest runs successfully
- Code structure mirrors Signals/SectorRotation/
- Documentation explains sector ↔ currency mapping

**Deliverables**:
- New: Query/Currencies/CurrencyQuery.py
- New: Signals/CurrencyCarrySignal.py
- New: tests/unit/query/currencies/test_currency_query.py
- New: tests/unit/signals/test_currency_carry_signal.py
- New: examples/currency_rotation_backtest.py
```

---

### Task 4: ML-Enhanced Factors

**Priority**: **MEDIUM**
**Effort**: 2-3 weeks (sequential) → **2-3 weeks** (parallel, no speedup)
**Business value**: Aligns with 2025 consensus (Sharpe > 2.0 potential)

#### Deliverables

1. **Create `MLPredictedReturnsSignal`**
   - **File**: `Signals/MLPredictedReturnsSignal.py` (NEW)
   - **Inherits**: `BaseSignal`
   - **Model**: Random Forest or Gradient Boosting (sklearn)
   - **Features**: Momentum, value, quality, technical indicators
   - **Output**: Predicted returns → z-scored signals

2. **Create `FeatureEngineering` utility**
   - **File**: `Signals/Utils/FeatureEngineering.py` (NEW)
   - **Methods**:
     - `calculate_momentum(returns, lookback=[1, 3, 6, 12])`
     - `calculate_value(prices, fundamentals)`
     - `calculate_quality(financials)`
     - `technical_indicators(prices)` (RSI, MACD, etc.)

3. **Write comprehensive tests**
   - **File**: `tests/unit/signals/test_ml_predicted_returns.py` (NEW)
   - **Tests**:
     - Feature engineering correct
     - Model training and prediction work
     - Z-score normalization
     - Edge cases (missing data, insufficient history)

4. **Backtest on equity sectors**
   - **File**: `examples/ml_factor_backtest.py` (NEW)
   - **Universe**: S&P 500 or sector ETFs
   - **Features**: Momentum, value, quality
   - **Model**: Random Forest (n_estimators=100)
   - **Metrics**: Sharpe, IC, turnover
   - **Benchmark**: Compare to classical factors

#### Acceptance Criteria

- ✅ ML model trains successfully
- ✅ Predictions have positive IC (>= 0.05)
- ✅ Backtest achieves Sharpe > 0.7 (target)
- ✅ Feature importance analysis documented
- ✅ Comparison to classical factors shows improvement

#### Agent Instructions

```
Implement ML-enhanced factor signals.

**Context**: 2025 consensus uses neural networks for predicted returns, achieving
Sharpe > 2.0 in research. We'll use Random Forest (simpler, interpretable).

**Tasks**:
1. Create FeatureEngineering utility
   - Momentum: 1m, 3m, 6m, 12m returns
   - Value: P/E, P/B, dividend yield
   - Quality: ROE, profit margin, debt/equity
   - Technical: RSI, MACD, Bollinger bands

2. Create MLPredictedReturnsSignal (inherits BaseSignal)
   - Train Random Forest: features → next_period_returns
   - Cross-validation (time-series split)
   - Predict returns for each asset
   - Z-score predictions

3. Write tests (TDD approach)
   - Test feature engineering
   - Test model training (synthetic data)
   - Test prediction and z-scoring
   - Test cross-validation

4. Create backtest example
   - Universe: S&P 500 or sector ETFs (2015-2024)
   - Features: all engineered features
   - Model: RandomForestRegressor(n_estimators=100)
   - Portfolio: Top-N/bottom-N or mean-variance
   - Metrics: Sharpe, IC, turnover
   - **Compare to classical factors** (momentum, value, quality separately)

**Success criteria**:
- All tests pass (>= 15 new tests)
- IC >= 0.05 (validation set)
- Sharpe > 0.7 (backtest)
- Feature importance analysis shows interpretability
- Documentation explains feature engineering

**Deliverables**:
- New: Signals/MLPredictedReturnsSignal.py
- New: Signals/Utils/FeatureEngineering.py
- New: tests/unit/signals/test_ml_predicted_returns.py
- New: examples/ml_factor_backtest.py

**Libraries**: sklearn (RandomForestRegressor), pandas, numpy
```

---

### Task 5: CVaR Tail Risk Constraints

**Priority**: **MEDIUM**
**Effort**: 1 week (sequential) → **1 week** (parallel, no speedup)
**Business value**: Better tail risk control (2025 best practice)

#### Deliverables

1. **Create `CVaRMeanVarianceOptimizer`**
   - **File**: `Optimizer/CVaRMeanVarianceOptimizer.py` (NEW)
   - **Inherits**: `MeanVarianceOptimizer`
   - **New constraint**: CVaR_α(w) ≤ cvar_limit
   - **Method**: CVXPY formulation (auxiliary variables)

2. **Write comprehensive tests**
   - **File**: `tests/unit/optimizer/test_cvar_optimizer.py` (NEW)
   - **Tests**:
     - CVaR constraint binds correctly
     - Optimization converges
     - Tail risk reduced vs. unconstrained
     - Edge cases (α=0.01, α=0.10)

3. **Example script**
   - **File**: `examples/cvar_portfolio.py` (NEW)
   - **Demonstrates**:
     - Load returns data
     - Optimize with CVaR constraint (α=0.05, limit=0.05)
     - Compare to unconstrained (show tail risk reduction)
     - Backtest performance

#### Acceptance Criteria

- ✅ CVaR constraint implemented correctly
- ✅ Optimization converges (< 1s for 50 assets)
- ✅ Tail risk reduced (CVaR empirically lower)
- ✅ Example script shows benefit

#### Agent Instructions

```
Implement CVaR (Conditional Value-at-Risk) tail risk constraints.

**Context**: 2025 best practice includes CVaR constraints for conservative
risk management. CVaR = expected loss beyond VaR (tail risk measure).

**Tasks**:
1. Create CVaRMeanVarianceOptimizer (inherits MeanVarianceOptimizer)
   - Add CVaR constraint: CVaR_α(w) <= cvar_limit
   - Use CVXPY formulation:
     - Auxiliary variables: t (VaR), u_i (excess losses)
     - Constraint: t + (1/α) * mean(u_i) <= cvar_limit
     - u_i >= -(r_i^T · w) - t
   - Keep existing constraints (risk budget, leverage)

2. Write tests (TDD approach)
   - Test CVaR constraint binding
   - Test optimization convergence
   - Test tail risk reduction (empirical CVaR < limit)
   - Test edge cases (α=0.01, α=0.10)

3. Create example script
   - Load equity returns (2015-2024)
   - Optimize with CVaR constraint (α=0.05, limit=0.05)
   - Compare to unconstrained:
     - CVaR (empirical)
     - Max drawdown
     - Sharpe ratio
   - Show tradeoff (Sharpe vs tail risk)

**Success criteria**:
- All tests pass (>= 8 new tests)
- CVaR constraint enforced (empirical < limit)
- Example shows tail risk reduction
- Documentation explains CVaR formulation

**Deliverables**:
- New: Optimizer/CVaRMeanVarianceOptimizer.py
- New: tests/unit/optimizer/test_cvar_optimizer.py
- New: examples/cvar_portfolio.py

**Reference**: Rockafellar & Uryasev (2000), "Optimization of CVaR"
```

---

## Parallel Execution Strategy

### Agent Assignment

**5 independent agents** (one per task stream):

1. **Agent 1: Cluster Constraints** (CRITICAL PATH)
   - Subagent type: `general-purpose`
   - Model: `sonnet` (complex optimization logic)
   - Estimated time: 1-1.5 weeks

2. **Agent 2: Volatility Dispersion**
   - Subagent type: `general-purpose`
   - Model: `sonnet` (signal logic + backtesting)
   - Estimated time: 2-3 weeks

3. **Agent 3: Currency Translation**
   - Subagent type: `general-purpose`
   - Model: `sonnet` (mirrors existing equity code)
   - Estimated time: 1.5 weeks

4. **Agent 4: ML Factors**
   - Subagent type: `general-purpose`
   - Model: `sonnet` (ML implementation + feature engineering)
   - Estimated time: 2-3 weeks

5. **Agent 5: CVaR Constraints**
   - Subagent type: `general-purpose`
   - Model: `haiku` (straightforward optimization extension)
   - Estimated time: 1 week

### Timeline

**Parallel execution** (5 agents working simultaneously):
```
Week 1:     [Agent 1] [Agent 2] [Agent 3] [Agent 4] [Agent 5]
Week 2:     [Agent 1] [Agent 2] [Agent 3] [Agent 4] [DONE   ]
Week 3:     [DONE   ] [Agent 2] [DONE   ] [Agent 4] [       ]
Week 4:     [       ] [DONE   ] [       ] [DONE   ] [       ]
```

**Critical path**: Agent 2 or Agent 4 (2-3 weeks)
**Total time**: **2-3 weeks** (vs. 10-12 weeks sequential)

**Speedup**: **4-5x** time reduction

### Integration Phase

After all agents complete:
1. **Merge all branches** (minimal conflicts expected)
2. **Integration tests** (end-to-end)
3. **Documentation update** (user guide, API docs)
4. **Performance validation** (backtests)

**Estimated time**: 1 week

**Total project time**: **3-4 weeks** (vs. 11-13 weeks sequential)

---

## Risk Mitigation

### Risk 1: Agent Failure

**Scenario**: One agent fails to complete task.

**Mitigation**:
- All tasks are orthogonal → Other agents continue
- Failed task can be restarted or done manually
- Critical path (Agent 1) gets highest priority

### Risk 2: Merge Conflicts

**Scenario**: Agents modify overlapping files.

**Mitigation**:
- Tasks are designed to avoid file overlap
- Each agent works in separate directories/modules
- Integration phase handles any conflicts

### Risk 3: API Changes

**Scenario**: One agent changes shared API, breaking others.

**Mitigation**:
- Tasks don't modify existing APIs (only extend)
- All new files (no changes to existing modules)
- Integration tests catch any issues

### Risk 4: Data Dependencies

**Scenario**: Task needs output from another task.

**Mitigation**:
- Tasks are designed to be independent
- Use mocked data during development
- Integration phase connects real data

---

## Success Metrics

### Task-Level Metrics

For each task:
- ✅ All tests pass (>= target test count)
- ✅ Code follows CLAUDE.md guidelines
- ✅ Documentation complete
- ✅ Example script runs successfully

### Integration Metrics

After merging all tasks:
- ✅ All 582 existing tests still pass
- ✅ All new tests pass (>= 60 new tests total)
- ✅ No merge conflicts
- ✅ End-to-end example works

### Performance Metrics

After backtesting:
- ✅ Equity sectors: Sharpe > 0.7, IC > 0.10
- ✅ Global macro: Sharpe > 0.6, IC > 0.08
- ✅ Vol dispersion: Sharpe > 0.7
- ✅ Cluster constraints improve diversification (HHI metric)

---

## Conclusion

### Key Insights

1. **Perfect orthogonalization**: 5 tasks with **zero dependencies**
2. **Massive parallelization**: 4-5x speedup (2-3 weeks vs. 10-12 weeks)
3. **Low integration risk**: Separate modules, minimal conflicts
4. **Critical path identified**: Agent 1 (cluster constraints) is foundation

### Recommendations

**Immediate**: Launch all 5 agents in parallel
**Week 1**: Monitor progress, provide guidance as needed
**Week 2-3**: Agents complete tasks
**Week 4**: Integration, testing, validation

**Expected outcome**: ARBS aligned with 2025 consensus in 3-4 weeks total.

---

**Status**: Task decomposition complete. Ready for parallel agent launch.
