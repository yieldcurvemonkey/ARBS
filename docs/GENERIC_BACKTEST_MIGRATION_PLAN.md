# Generic Backtest Migration Plan

**Date**: 2025-11-13
**Objective**: Replace MinimalBacktest with generic, configurable Backtest class
**Root Cause**: MinimalBacktest hardcodes FuturesAdapter + CarrySignal, blocking all other strategies

---

## Executive Summary

**Current Problem:**
- MinimalBacktest is **not minimal** - it's futures carry ONLY
- Hardcodes adapter, signal, preventing use with:
  - Other signals (momentum, mean reversion)
  - Other asset classes (equities, ETFs)
  - Multi-signal strategies

**Solution:**
- Create `Backtest` class with **component injection**
- Keep MinimalBacktest temporarily for backwards compatibility
- Migrate 13 files over 3 phases

**Impact:**
- ✅ Enables equity backtesting (currently impossible)
- ✅ Enables multi-signal strategies (currently workarounds)
- ✅ Enables custom risk models / optimizers
- ✅ Showcases library's modular architecture

---

## Phase 1: Create Generic Backtest Class

### 1.1 Design Requirements

Based on usage analysis, the generic Backtest must support:

| Requirement | Current Limitation | New Capability |
|-------------|-------------------|----------------|
| **Multiple signals** | Single CarrySignal only | List[BaseSignal] + combiner |
| **Any adapter** | FuturesAdapter only | FuturesAdapter OR EquityAdapter OR None |
| **DataFrame input** | Must use mdp + queries | Accept pre-computed returns |
| **Configurable components** | All hardcoded | Inject alpha_gen, risk_model, optimizer |

### 1.2 New Class Structure

**File**: `Backtest/Backtest.py` (new)

```python
class Backtest(BaseBacktest):
    """
    Generic backtest supporting all asset classes and signal types.

    Two usage patterns:

    1. Query-based (futures, swaps):
       backtest = Backtest(
           mdp=market_data_provider,
           adapter=FuturesAdapter(mdp),
           signals=CarrySignal()
       )
       result = backtest.run(contracts=['SFRZ4'], dates=[...])

    2. DataFrame-based (equities, pre-computed):
       backtest = Backtest(
           signals=MomentumSignal(),
           alpha_generator=AlphaGenerator(IC=0.05),
           ...
       )
       result = backtest.run_from_dataframe(returns_df, dates=[...])

    Component Injection:
    - adapter: FuturesAdapter, EquityAdapter, or None
    - signals: Single signal or List[BaseSignal]
    - signal_combiner: How to combine multiple signals (default: equal weight)
    - alpha_generator: Converts signals → alphas (default: IC × Vol × Z)
    - risk_model: Covariance estimator (default: LedoitWolf)
    - optimizer: Portfolio optimizer (default: MeanVariance)
    - returns_calculator: Price → return conversion (default: percent)
    """

    def __init__(
        self,
        # Data source (query-based workflow)
        mdp: Optional[Any] = None,
        adapter: Optional[BaseAdapter] = None,

        # Signals (required)
        signals: Optional[Union[BaseSignal, List[BaseSignal]]] = None,
        signal_combiner: Optional[SignalCombiner] = None,

        # Pipeline components (optional - use defaults if not provided)
        alpha_generator: Optional[AlphaGenerator] = None,
        risk_model: Optional[Any] = None,  # BaseCovariance
        optimizer: Optional[Any] = None,   # BaseOptimizer
        returns_calculator: Optional[ReturnsCalculator] = None,

        # Convenience parameters (create default components)
        IC: float = 0.05,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        min_history: int = 20,
    ):
        """
        Initialize generic backtest.

        Args:
            mdp: Market data provider (for query-based workflow)
            adapter: Converts queries → DataFrame (FuturesAdapter, EquityAdapter)
            signals: Single signal or list of signals to combine
            signal_combiner: How to combine multiple signals
            alpha_generator: Converts signals → expected returns
            risk_model: Covariance estimator
            optimizer: Portfolio weight optimizer
            returns_calculator: Price → return conversion
            IC: Information coefficient (if using default alpha_generator)
            risk_aversion: Risk aversion parameter (if using default optimizer)
            long_only: Only long positions (if using default optimizer)
            min_history: Minimum periods for covariance estimation

        Raises:
            ValueError: If signals not provided
            ValueError: If using query workflow but no adapter/mdp
        """
        super().__init__(mdp)

        # Validate inputs
        if signals is None:
            raise ValueError("Must provide at least one signal")

        if adapter is not None and mdp is None:
            raise ValueError("Adapter requires mdp to be provided")

        # Store configuration
        self.adapter = adapter
        self.signals = [signals] if isinstance(signals, BaseSignal) else (signals or [])
        self.min_history = min_history

        # Create or use provided components
        self.signal_combiner = signal_combiner or (
            SignalCombiner(method='equal') if len(self.signals) > 1 else None
        )
        self.alpha_generator = alpha_generator or AlphaGenerator(IC=IC)
        self.risk_model = risk_model or LedoitWolfShrinkage()
        self.optimizer = optimizer or MeanVarianceOptimizer(
            risk_aversion=risk_aversion,
            long_only=long_only,
        )
        self.returns_calc = returns_calculator or ReturnsCalculator(method="percent")

    def run(
        self,
        contracts: List[str],
        dates: List[date],
    ) -> BacktestResult:
        """
        Run backtest using query-based workflow (futures, swaps).

        Requires:
        - self.mdp must be set
        - self.adapter must be set

        Algorithm:
        1. For each date:
           a. Use adapter to convert queries → DataFrame
           b. Calculate signals from DataFrame
           c. Combine signals if multiple
           d. Convert signals → alphas
           e. Estimate covariance
           f. Optimize portfolio weights
           g. Track positions and calculate returns
        2. Return performance metrics

        Args:
            contracts: List of contract codes (e.g., ['SFRZ4', 'SFRH5'])
            dates: List of backtest dates (sorted)

        Returns:
            BacktestResult with weights, returns, IC, Sharpe, etc.
        """
        if self.adapter is None or self.mdp is None:
            raise ValueError(
                "Query-based workflow requires adapter and mdp. "
                "Use run_from_dataframe() for DataFrame-based workflow."
            )

        # Implementation similar to MinimalBacktest.run()
        # but using self.signals instead of hardcoded CarrySignal
        # and using self.adapter instead of hardcoded FuturesAdapter
        ...

    def run_from_dataframe(
        self,
        returns_df: pl.DataFrame,
        dates: List[date],
        instruments: Optional[List[str]] = None,
    ) -> BacktestResult:
        """
        Run backtest from pre-computed returns DataFrame (equities, ETFs).

        No adapter or mdp needed - returns already provided.

        Args:
            returns_df: DataFrame with columns ['date', 'ticker', 'return']
            dates: List of rebalance dates
            instruments: List of tickers to trade (optional, use all if None)

        Returns:
            BacktestResult with weights, returns, IC, Sharpe, etc.
        """
        if self.adapter is not None:
            raise ValueError(
                "DataFrame workflow doesn't use adapter. "
                "Use run() for query-based workflow."
            )

        # Implementation for DataFrame-based workflow
        # Used by equity strategies
        ...
```

### 1.3 Implementation Steps

**Step 1: Create Backtest/Backtest.py** (TDD)
- [ ] Write tests for futures carry (same as MinimalBacktest)
- [ ] Write tests for futures momentum (new capability)
- [ ] Write tests for multi-signal (new capability)
- [ ] Write tests for DataFrame input (new capability)
- [ ] Implement run() method
- [ ] Implement run_from_dataframe() method

**Step 2: Update Backtest/__init__.py**
```python
from Backtest.Base.BaseBacktest import BaseBacktest, BacktestResult
from Backtest.MinimalBacktest import MinimalBacktest  # Deprecated
from Backtest.Backtest import Backtest  # New generic class

__all__ = [
    'BaseBacktest',
    'BacktestResult',
    'Backtest',  # Prefer this
    'MinimalBacktest',  # Backwards compatibility only
]
```

**Step 3: Add deprecation warning to MinimalBacktest**
```python
class MinimalBacktest(BaseBacktest):
    """
    DEPRECATED: Use Backtest instead.

    MinimalBacktest is hardcoded to futures carry strategies.
    For other signals or asset classes, use the generic Backtest class.

    This class remains for backwards compatibility only.
    """

    def __init__(self, *args, **kwargs):
        import warnings
        warnings.warn(
            "MinimalBacktest is deprecated. Use Backtest with injected components instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(*args, **kwargs)
```

---

## Phase 2: Migrate Existing Files

### 2.1 EASY Migrations (No Changes Needed)

Keep these working with MinimalBacktest during transition:

- ✅ `examples/run_minimal_backtest.py` - Example of futures carry
- ✅ `notebooks/01_getting_started.ipynb` - Tutorial
- ✅ `tests/unit/backtest/test_minimal_backtest.py` - Keep for backwards compat

**Action**: Add comments noting MinimalBacktest is deprecated, but don't break them.

### 2.2 MEDIUM Migrations (Add Signal Parameter)

**Files:**
- `notebooks/06_carry_strategy_complete.ipynb`
- `notebooks/07_momentum_strategy_complete.ipynb`

**Change Pattern:**
```python
# Before (MinimalBacktest - hardcoded CarrySignal):
backtest = MinimalBacktest(
    mdp=mdp,
    risk_aversion=1.0,
    long_only=True,
)

# After (Generic Backtest - inject MomentumSignal):
from Signals.Futures.MomentumSignal import MomentumSignal

momentum = MomentumSignal(lookback_days=20, standardize=True)

backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=momentum,  # ← Now configurable!
    risk_aversion=1.0,
    long_only=True,
)
```

**Benefits:**
- Notebook 07 can actually use MomentumSignal (currently can't)
- Notebook 06 can experiment with different signals
- Demonstrates library's modularity

### 2.3 HARD Migrations (Need New Components)

**Files:**
- `notebooks/05_cross_asset_integration.ipynb`
- `notebooks/10_vol_arbitrage_strategy.ipynb`
- `notebooks/12_risk_parity_strategy.ipynb`

**Blockers:**
1. Need `EquityAdapter` (doesn't exist yet)
2. Need to handle DataFrame input (new method)

**Two-Phase Approach:**

**Phase 2a: Create EquityAdapter**
```python
# File: Adapter/EquityAdapter.py (already exists but not used with Backtest)

class EquityAdapter(BaseAdapter):
    """Convert EquityQuery/ETFQuery to DataFrame."""

    def convert(
        self,
        queries: List[Union[EquityQuery, ETFQuery]],
        as_of_date: date,
    ) -> pl.DataFrame:
        """
        Returns DataFrame with columns:
        - ticker: Stock symbol
        - date: Trading date
        - close: Price
        - return: Calculated return
        - sector: GICS sector
        - weight: Portfolio weight
        """
        # Implementation exists
        ...
```

**Phase 2b: Use Backtest.run_from_dataframe()**
```python
# Notebooks 10, 12 pattern:
# They already have returns_df from calculations
# Just pass it to Backtest

from Backtest.Backtest import Backtest
from Signals.CorrelationVolatilitySignal import CorrelationVolatilitySignal

vol_signal = CorrelationVolatilitySignal(
    min_correlation=0.85,
    lookback=60,
)

backtest = Backtest(
    signals=vol_signal,
    risk_aversion=3.0,
    long_only=False,
)

# Use DataFrame workflow (no adapter needed)
result = backtest.run_from_dataframe(
    returns_df=returns_df,
    dates=dates,
)

print(f"Sharpe: {result.sharpe_ratio:.2f}")
print(f"IC: {result.ic:.3f}")
```

---

## Phase 3: Testing and Validation

### 3.1 Test Coverage Requirements

**Unit Tests** (`tests/unit/backtest/test_backtest.py`):
- [ ] Can instantiate with futures components
- [ ] Can instantiate with equity components
- [ ] Can instantiate with multiple signals
- [ ] run() works with FuturesAdapter
- [ ] run_from_dataframe() works with returns DataFrame
- [ ] Validates inputs (raises on missing signals)
- [ ] Backwards compatible with MinimalBacktest API

**Integration Tests**:
- [ ] Futures carry strategy (same results as MinimalBacktest)
- [ ] Futures momentum strategy (new capability)
- [ ] Multi-signal strategy (carry + momentum + mean reversion)
- [ ] Equity strategy with DataFrame input
- [ ] Custom risk model (SampleCovariance instead of LedoitWolf)
- [ ] Custom optimizer (RiskParity instead of MeanVariance)

### 3.2 Validation Checklist

**Functional Validation:**
- [ ] All 4 EASY files still work (backwards compat)
- [ ] Notebook 07 can use MomentumSignal
- [ ] Notebooks 10, 12 can use DataFrame workflow
- [ ] Multi-signal test works
- [ ] Performance metrics match MinimalBacktest (for carry strategy)

**Documentation Validation:**
- [ ] CLAUDE.md updated (remove "Minimal" terminology)
- [ ] Docstrings explain when to use run() vs run_from_dataframe()
- [ ] Examples show both workflows
- [ ] Migration guide for existing users

---

## File-by-File Migration Checklist

### Core Implementation
- [ ] `Backtest/Backtest.py` - Create new generic class
- [ ] `Backtest/__init__.py` - Export Backtest, deprecate MinimalBacktest
- [ ] `Backtest/MinimalBacktest.py` - Add deprecation warning

### Tests
- [ ] `tests/unit/backtest/test_backtest.py` - New test file
- [ ] `tests/unit/backtest/test_minimal_backtest.py` - Keep for backwards compat
- [ ] `tests/integration/test_multi_signal_strategy.py` - Migrate to use Backtest

### Examples
- [ ] `examples/run_minimal_backtest.py` - Add note about Backtest
- [ ] `examples/run_generic_backtest.py` - NEW: Show different configurations

### Notebooks
- [ ] `notebooks/01_getting_started.ipynb` - Add section on Backtest vs MinimalBacktest
- [ ] `notebooks/06_carry_strategy_complete.ipynb` - Optional: Show Backtest usage
- [ ] `notebooks/07_momentum_strategy_complete.ipynb` - MIGRATE: Use Backtest
- [ ] `notebooks/05_cross_asset_integration.ipynb` - MIGRATE: Use run_from_dataframe()
- [ ] `notebooks/10_vol_arbitrage_strategy.ipynb` - MIGRATE: Use run_from_dataframe()
- [ ] `notebooks/12_risk_parity_strategy.ipynb` - MIGRATE: Use run_from_dataframe()

### Documentation
- [ ] `CLAUDE.md` - Remove "Minimal" terminology
- [ ] `docs/GENERIC_BACKTEST_MIGRATION_PLAN.md` - This document
- [ ] `docs/USER_GUIDE_BACKTEST.md` - NEW: How to use Backtest class

---

## Success Criteria

### Must Have (MVP):
1. ✅ Backtest class created and tested
2. ✅ Backwards compatible with MinimalBacktest use cases
3. ✅ Can use any signal type (not just CarrySignal)
4. ✅ Can use multiple signals + combiner
5. ✅ At least 1 notebook migrated successfully

### Should Have:
6. ✅ run_from_dataframe() supports equity strategies
7. ✅ All MEDIUM migrations complete (notebooks 06, 07)
8. ✅ Documentation updated
9. ✅ Examples showing different configurations

### Nice to Have:
10. ✅ All HARD migrations complete (notebooks 05, 10, 12)
11. ✅ MinimalBacktest fully deprecated and removed
12. ✅ User migration guide published

---

## Risks and Mitigation

### Risk 1: Breaking Existing Code
**Mitigation:**
- Keep MinimalBacktest with deprecation warning
- All existing code continues to work
- Gradual migration, not big bang

### Risk 2: API Too Complex
**Mitigation:**
- Provide good defaults (most params optional)
- Create convenience functions:
  ```python
  def futures_carry_backtest(mdp, **kwargs):
      return Backtest(
          mdp=mdp,
          adapter=FuturesAdapter(mdp),
          signals=CarrySignal(),
          **kwargs
      )
  ```

### Risk 3: DataFrame Workflow Different from Query Workflow
**Mitigation:**
- Two separate methods: run() vs run_from_dataframe()
- Clear documentation on when to use each
- Examples for both patterns

---

## Timeline Estimate

### Week 1: Core Implementation
- Day 1-2: Write tests for Backtest class
- Day 3-5: Implement Backtest.run()
- Day 6-7: Implement Backtest.run_from_dataframe()

### Week 2: MEDIUM Migrations
- Day 1-2: Migrate notebook 07 (momentum)
- Day 3-4: Update examples
- Day 5-7: Testing and bug fixes

### Week 3: HARD Migrations
- Day 1-3: Enhance EquityAdapter if needed
- Day 4-5: Migrate notebooks 10, 12
- Day 6-7: Documentation and user guide

---

## Open Questions

1. **Should MinimalBacktest be removed entirely?**
   - Option A: Remove after 1-2 releases (force migration)
   - Option B: Keep indefinitely as convenience wrapper
   - **Recommendation**: Option B - it's a valid use case

2. **Should we create convenience subclasses?**
   ```python
   class FuturesCarryBacktest(Backtest):
       def __init__(self, mdp, **kwargs):
           super().__init__(
               mdp=mdp,
               adapter=FuturesAdapter(mdp),
               signals=CarrySignal(),
               **kwargs
           )
   ```
   - **Recommendation**: No - use factory functions instead

3. **How to handle GrinoldKahnPortfolio?**
   - It already exists and works well
   - Could Backtest use it internally?
   - **Recommendation**: Keep separate, document relationship

---

## Next Actions

**Immediate (This Sprint):**
1. Create `Backtest/Backtest.py` with TDD
2. Write comprehensive tests
3. Migrate notebook 07 as proof of concept
4. Update documentation

**Short Term (Next Sprint):**
5. Complete all MEDIUM migrations
6. Create examples showing different configurations
7. Add deprecation warnings to MinimalBacktest

**Long Term (Future):**
8. Complete HARD migrations (equity strategies)
9. Publish user migration guide
10. Consider removing MinimalBacktest entirely

---

## Conclusion

The generic Backtest class unlocks the library's full potential:
- ✅ **Showcase modularity**: Any signal, any adapter, any optimizer
- ✅ **Enable equity strategies**: Currently impossible with MinimalBacktest
- ✅ **Enable multi-signal**: Combine carry + momentum + mean reversion
- ✅ **Honest naming**: Not "minimal" - it's the complete backtest engine

**The name "MinimalBacktest" was wrong from the start.** It's not minimal - it's futures-specific. The generic Backtest is what the library always needed.
