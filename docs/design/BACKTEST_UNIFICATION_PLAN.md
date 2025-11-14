# Backtest System Unification Plan

## Executive Summary

**Goal**: Unify BT/ (query-driven for derivatives) and Backtest/ (signal-driven for equities) into a single, cohesive backtesting framework that supports both workflows.

**Status**: Two working systems, not yet integrated
**Priority**: HIGH - Next major architecture phase
**Estimated Effort**: 3-5 implementation sessions

---

## Current State Analysis

### System 1: BT/ - Query-Driven Backtest (Derivatives)

**Purpose**: Backtest derivative strategies using MDP + queries
**Workflow**: Strategy → Triggers → Queries → MDP → Pricing → P&L

```python
# Current BT/ workflow
QueryDrivenBacktest(
    time_grid=grid,
    mdp=IRSwapsMDP(),
    strategy=QueryStrategy(triggers=[...])
)
```

**Key Components**:
- `QueryDrivenBacktest` - Main engine
- `EventDrivenBacktest` - Alternative engine
- `BaseQuery` - Product-agnostic queries
- `MDP` - Market data providers
- `Triggers` - Time/condition-based actions
- `QueryPortfolio` - Position tracking

**Strengths**:
- ✅ Product-agnostic query abstraction
- ✅ MDP integration for real market data
- ✅ Flexible trigger/action system
- ✅ Derivative-specific features (rolls, settlement, margin)

**Limitations**:
- ❌ No signal abstraction
- ❌ No covariance estimation
- ❌ No portfolio optimization
- ❌ No Grinold-Kahn alpha scaling

### System 2: Backtest/ - Signal-Driven Backtest (Equities)

**Purpose**: Backtest equity strategies using signals + optimization
**Workflow**: Returns → Signals → Alpha → Risk → Optimizer → Weights → Portfolio

```python
# Current Backtest/ workflow
Backtest(
    signals=CarrySignal(),
    risk_model=LedoitWolfShrinkage(),
    optimizer=MeanVarianceOptimizer()
)
```

**Key Components**:
- `Backtest` - Main engine
- `BaseSignal` - Alpha signal abstraction
- `AlphaGenerator` - IC × Vol × Z scaling
- `BaseCovarianceEstimator` - Risk models
- `BaseOptimizer` - Portfolio optimization
- `GrinoldKahnPortfolio` - Position tracking

**Strengths**:
- ✅ Signal abstraction (Carry, Momentum, MeanReversion)
- ✅ Grinold-Kahn framework (IC × Vol × Z)
- ✅ Covariance estimation (10+ models)
- ✅ Portfolio optimization (Markowitz, CVaR)
- ✅ TearSheet analysis

**Limitations**:
- ❌ No query abstraction for derivatives
- ❌ No MDP integration
- ❌ No trigger/action system
- ❌ Limited to returns-based assets

---

## Integration Goals

### 1. **Unified Backtest Interface**

Single backtest class supporting both workflows:

```python
# Unified interface (proposed)
Backtest(
    # Data sources (choose one)
    mdp=IRSwapsMDP(),              # Query-driven workflow
    returns_df=equity_returns,      # Signal-driven workflow

    # Strategy definition (choose one or combine)
    queries=[IRSwapQuery(...)],     # Query-based
    signals=[CarrySignal()],        # Signal-based

    # Optional: Advanced features
    risk_model=LedoitWolfShrinkage(),
    optimizer=MeanVarianceOptimizer(),
    triggers=[DateTrigger(...)],

    # Execution
    time_grid=grid,
    rebalance_frequency='weekly'
)
```

### 2. **Query-Signal Bridge**

Enable queries to generate signals:

```python
# Proposed: QuerySignal adapter
class QuerySignal(BaseSignal):
    """Adapts BaseQuery to BaseSignal interface."""

    def __init__(self, query: BaseQuery, mdp: MarketDataProvider):
        self.query = query
        self.mdp = mdp

    def generate(self, tickers, returns, as_of):
        # Execute query via MDP
        # Extract signal from value (e.g., carry, rate differential)
        # Return standardized z-scores
        pass
```

**Use Case**: Use swap carry as a signal in portfolio optimization

```python
backtest = Backtest(
    mdp=IRSwapsMDP(),
    signals=[
        QuerySignal(IRSwapQuery(value=IRSwapValue.CARRY), mdp),
        MomentumSignal()  # Mix derivative and equity signals
    ],
    risk_model=LedoitWolfShrinkage(),
    optimizer=MeanVarianceOptimizer()
)
```

### 3. **Signal-Query Bridge**

Enable signals to work with query engine:

```python
# Proposed: SignalQuery adapter
class SignalQuery(BaseQuery):
    """Adapts BaseSignal to BaseQuery interface."""

    def __init__(self, signal: BaseSignal, tickers: List[str]):
        self.signal = signal
        self.tickers = tickers

    def resolve_package(self, pricer_or_curve):
        # Generate signal values
        # Convert to position weights
        # Return package for query engine
        pass
```

**Use Case**: Use momentum signal to drive query-based execution

```python
query_bt = QueryDrivenBacktest(
    time_grid=grid,
    mdp=IRSwapsMDP(),
    strategy=QueryStrategy(
        triggers=[
            Trigger(
                requirements=SignalBasedTrigger(MomentumSignal()),
                actions=[AddQueryAction(...)]
            )
        ]
    )
)
```

---

## Proposed Architecture

### Unified Component Hierarchy

```
UnifiedBacktest
├── Data Sources
│   ├── MDP (MarketDataProvider) → QueryEngine
│   └── DataFrame → SignalEngine
│
├── Strategy Layer
│   ├── Queries (BaseQuery) → QueryPortfolio
│   ├── Signals (BaseSignal) → AlphaGenerator → Optimizer → GKPortfolio
│   └── Triggers (Trigger) → Actions
│
├── Execution Layer
│   ├── TimeGrid (common)
│   ├── Rebalancing (common)
│   └── Transaction Costs (common)
│
└── Analysis Layer
    ├── TearSheet (common)
    ├── P&L Attribution (common)
    └── Risk Metrics (common)
```

### Bridge Components

```python
# 1. QuerySignal: Query → Signal
class QuerySignal(BaseSignal):
    """Execute query via MDP, extract signal value."""
    query: BaseQuery
    mdp: MarketDataProvider
    value_extractor: Callable  # Extract signal from query result

# 2. SignalQuery: Signal → Query
class SignalQuery(BaseQuery):
    """Generate signal, convert to query positions."""
    signal: BaseSignal
    position_builder: Callable  # Convert signal → positions

# 3. UnifiedPortfolio: Merge QueryPortfolio + GKPortfolio
class UnifiedPortfolio(Asset):
    """Tracks both query-based and signal-based positions."""
    query_positions: List[ResolvedQueryPosition]
    signal_positions: List[Position]

    def calculate_return(...):
        # Combine returns from both position types
        pass
```

---

## Implementation Phases

### Phase 1: Foundation (Session 1)
**Goal**: Create bridge abstractions without breaking existing code

**Tasks**:
1. ✅ Create `Backtest/Bridges/` directory
2. ✅ Implement `QuerySignal(BaseSignal)`:
   - Constructor: `QuerySignal(query, mdp, value_extractor)`
   - Implement `generate()` method
   - Unit tests with IRSwapQuery
3. ✅ Implement `SignalQuery(BaseQuery)`:
   - Constructor: `SignalQuery(signal, position_builder)`
   - Implement query methods
   - Unit tests with CarrySignal
4. ✅ Documentation: `BRIDGE_COMPONENTS.md`

**Success Criteria**:
- QuerySignal generates signals from queries
- SignalQuery creates queries from signals
- All existing tests still pass
- No breaking changes to BT/ or Backtest/

### Phase 2: Unified Engine (Session 2)
**Goal**: Create UnifiedBacktest class

**Tasks**:
1. ✅ Create `Backtest/UnifiedBacktest.py`
2. ✅ Implement constructor supporting both workflows:
   ```python
   UnifiedBacktest(
       mdp=None,           # Query workflow
       returns_df=None,    # Signal workflow
       queries=None,       # Query strategies
       signals=None,       # Signal strategies
       triggers=None,      # Trigger system
       risk_model=None,    # Risk estimation
       optimizer=None      # Portfolio optimization
   )
   ```
3. ✅ Implement `run()` method:
   - Detect workflow (query vs signal vs hybrid)
   - Route to appropriate engine
   - Merge results
4. ✅ Unit tests for all workflows
5. ✅ Integration tests

**Success Criteria**:
- Single interface works for both workflows
- Can mix queries and signals
- Results match separate engines
- TearSheet works for all workflows

### Phase 3: Unified Portfolio (Session 3)
**Goal**: Merge QueryPortfolio and GrinoldKahnPortfolio

**Tasks**:
1. ✅ Create `Asset/UnifiedPortfolio.py`
2. ✅ Implement position tracking:
   - Query positions (derivative packages)
   - Signal positions (optimized weights)
3. ✅ Implement return calculation:
   - Handle query-based returns (MTM via MDP)
   - Handle signal-based returns (weight × return)
4. ✅ Implement `get_positions()` for both types
5. ✅ Unit tests

**Success Criteria**:
- Single portfolio tracks both position types
- Returns calculated correctly
- Position reporting unified
- Can nest UnifiedPortfolio in other portfolios

### Phase 4: Enhanced Features (Session 4)
**Goal**: Add advanced features to unified system

**Tasks**:
1. ✅ Transaction costs (unified):
   - Query-based: bid-ask spreads
   - Signal-based: proportional + impact
2. ✅ Risk attribution:
   - Query positions: DV01, convexity
   - Signal positions: factor exposures
3. ✅ Unified TearSheet:
   - Works for queries, signals, or both
   - Cross-strategy attribution
4. ✅ Performance optimization:
   - Cache MDP calls
   - Vectorize signal calculations

**Success Criteria**:
- Transaction costs applied correctly
- Risk attribution clear and accurate
- TearSheet shows unified metrics
- Performance acceptable (<5s for 1000 steps)

### Phase 5: Migration & Examples (Session 5)
**Goal**: Migrate examples and document migration path

**Tasks**:
1. ✅ Create migration guide: `MIGRATION_TO_UNIFIED.md`
2. ✅ Update examples:
   - `examples/unified_swap_carry.py` (query-based)
   - `examples/unified_equity_momentum.py` (signal-based)
   - `examples/unified_hybrid_strategy.py` (both)
3. ✅ Update README with unified examples
4. ✅ Deprecation plan for old interfaces:
   - BT/: Keep for now, mark as "legacy path"
   - Backtest/: Merge into unified
5. ✅ Update all docs to reference UnifiedBacktest

**Success Criteria**:
- Clear migration path documented
- Working examples for all workflows
- README reflects new architecture
- Old code still works (backward compatible)

---

## API Design

### Minimal Interface (Query-only)

```python
from Backtest.UnifiedBacktest import UnifiedBacktest
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

backtest = UnifiedBacktest(
    mdp=IRSwapsMDP(),
    queries=[IRSwapQuery(tenor="5Y", curve="USD-SOFR-1D")]
)
result = backtest.run(time_grid=grid)
```

### Minimal Interface (Signal-only)

```python
from Backtest.UnifiedBacktest import UnifiedBacktest
from Signals.Futures.CarrySignal import CarrySignal

backtest = UnifiedBacktest(
    signals=[CarrySignal()]
)
result = backtest.run_from_dataframe(returns_df, dates)
```

### Hybrid Interface (Query + Signal)

```python
from Backtest.UnifiedBacktest import UnifiedBacktest
from Signals.Futures.MomentumSignal import MomentumSignal
from Backtest.Bridges.QuerySignal import QuerySignal

# Use swap carry as a signal
swap_carry = QuerySignal(
    query=IRSwapQuery(value=IRSwapValue.CARRY),
    mdp=IRSwapsMDP()
)

backtest = UnifiedBacktest(
    mdp=IRSwapsMDP(),
    signals=[swap_carry, MomentumSignal()],  # Mix derivative and equity signals
    risk_model=LedoitWolfShrinkage(),
    optimizer=MeanVarianceOptimizer()
)
result = backtest.run(time_grid=grid)
```

### Full Interface (All Features)

```python
backtest = UnifiedBacktest(
    # Data sources
    mdp=IRSwapsMDP(),
    returns_df=equity_returns,  # Can use both!

    # Strategies
    queries=[IRSwapQuery(...)],
    signals=[CarrySignal(), MomentumSignal()],
    triggers=[DateTrigger(...)],

    # Risk & Optimization
    risk_model=LedoitWolfShrinkage(),
    optimizer=MeanVarianceOptimizer(risk_aversion=2.0),

    # Execution
    time_grid=grid,
    rebalance_frequency='weekly',
    transaction_costs={'proportional': 0.001, 'impact': 0.0001},

    # Analysis
    tearsheet_config={'include_attribution': True}
)

result = backtest.run()
print(result.sharpe_ratio)
print(result.information_coefficient)
print(result.position_turnover)
```

---

## Testing Strategy

### Unit Tests (Per Phase)
- **Phase 1**: Bridge components (QuerySignal, SignalQuery)
- **Phase 2**: UnifiedBacktest routing logic
- **Phase 3**: UnifiedPortfolio return calculation
- **Phase 4**: Transaction costs, risk attribution
- **Phase 5**: Examples and integration

### Integration Tests
1. **Query-only workflow**: Verify matches BT/QueryDrivenBacktest
2. **Signal-only workflow**: Verify matches Backtest/Backtest
3. **Hybrid workflow**: Verify combines both correctly
4. **Golden files**: Freeze P&L results for regression testing

### Performance Tests
- 1000-step backtest should complete in <5 seconds
- Memory usage should be <1GB for 1000 steps × 100 assets
- Cache hit rate >90% for repeated MDP calls

---

## Backward Compatibility

### Deprecation Strategy

**Year 1 (Next 6 months)**:
- ✅ UnifiedBacktest available
- ✅ Old interfaces (BT/, Backtest/) still work
- ✅ Deprecation warnings added
- ✅ Migration guide published

**Year 2 (6-12 months)**:
- ⚠️ Old interfaces raise loud warnings
- ⚠️ Tests migrated to UnifiedBacktest
- ⚠️ Examples use UnifiedBacktest
- ⚠️ Docs updated

**Year 3 (12-18 months)**:
- ❌ Old interfaces removed
- ❌ BT/ and Backtest/ merged into Backtest/
- ❌ Single unified architecture

### Migration Path

```python
# Old (BT/)
from BT.query_engine import QueryDrivenBacktest
bt = QueryDrivenBacktest(mdp=mdp, strategy=strategy)

# New (Unified)
from Backtest.UnifiedBacktest import UnifiedBacktest
bt = UnifiedBacktest(mdp=mdp, queries=strategy.queries)
# OR use compatibility wrapper:
from Backtest.UnifiedBacktest import from_query_engine
bt = from_query_engine(mdp=mdp, strategy=strategy)
```

---

## Success Metrics

1. **Functionality**: All workflows work (query, signal, hybrid)
2. **Performance**: <5s for 1000-step backtest
3. **Tests**: 100% of existing tests still pass
4. **Coverage**: 95%+ code coverage on new components
5. **Documentation**: Complete migration guide + examples
6. **Adoption**: 3+ working examples demonstrating unification

---

## Questions for Peter

1. **Priority**: Should we start Phase 1 immediately or wait?
2. **Backward Compatibility**: Keep old interfaces for how long?
3. **API Design**: Any changes to proposed UnifiedBacktest interface?
4. **Performance**: Are <5s and <1GB acceptable targets?
5. **Migration**: Should we provide automated migration tool?

---

*Created: 2025-11-14*
*Next Review: Before starting Phase 1*
*Owner: TBD*
