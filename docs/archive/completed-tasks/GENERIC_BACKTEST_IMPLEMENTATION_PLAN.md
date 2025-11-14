# Generic Backtest Implementation Plan - Detailed Execution Steps

**Session**: claude/verify-integration-notebook-011CV66ZrAdcoGXccRY1Up3E
**Date**: 2025-11-13
**Objective**: Implement generic Backtest class to replace futures-only MinimalBacktest

---

## 🎯 Session Resume Information

If this session gets interrupted, resume with:

**What We're Building:**
- Generic `Backtest` class that accepts injected components
- Supports futures (query-based) AND equities (DataFrame-based)
- Replaces hardcoded MinimalBacktest with flexible architecture

**Current Branch:** `claude/verify-integration-notebook-011CV66ZrAdcoGXccRY1Up3E`

**Key Files:**
- Implementation: `Backtest/Backtest.py` (new)
- Tests: `tests/unit/backtest/test_backtest.py` (new)
- Exports: `Backtest/__init__.py` (modify)
- Deprecation: `Backtest/MinimalBacktest.py` (add warning)

**Progress Tracking:**
Check `docs/GENERIC_BACKTEST_PROGRESS.md` for latest checkpoint

---

## Phase 1: Setup and Test Design (TDD)

### Step 1.1: Create Progress Tracker

**File**: `docs/GENERIC_BACKTEST_PROGRESS.md`

```markdown
# Generic Backtest Implementation Progress

## Status: [IN_PROGRESS/COMPLETE]
Last Updated: [timestamp]

## Completed Steps:
- [ ] 1.1: Create progress tracker
- [ ] 1.2: Create test file structure
- [ ] 1.3: Write test for basic instantiation
- [ ] 1.4: Write test for futures carry (baseline)
- [ ] 1.5: Write test for futures momentum (new)
- [ ] 1.6: Write test for multi-signal
- [ ] 1.7: Write test for DataFrame input
- [ ] 2.1: Create Backtest class skeleton
- [ ] 2.2: Implement __init__ with validation
- [ ] 2.3: Implement run() method
- [ ] 2.4: Implement run_from_dataframe() method
- [ ] 2.5: Run all tests - confirm passing
- [ ] 3.1: Update __init__.py exports
- [ ] 3.2: Add deprecation warning to MinimalBacktest
- [ ] 3.3: Run all existing tests - confirm no breaks
- [ ] 4.1: Migrate notebook 07 as proof of concept
- [ ] 4.2: Create example file
- [ ] 5.1: Update CLAUDE.md
- [ ] 5.2: Final commit and push

## Current Checkpoint:
Step: [current step number]
File: [current file being worked on]
Status: [what's done, what's next]

## Failed Tests:
[List any tests that failed and need fixing]

## Notes:
[Any important observations or decisions]
```

**Action**: Create this file and mark step 1.1 complete

---

### Step 1.2: Create Test File Structure

**File**: `tests/unit/backtest/test_backtest.py`

**Initial Content:**
```python
# ABOUTME: Test suite for generic Backtest class
# ABOUTME: Verifies configurable components, multiple workflows, backwards compatibility

"""
Tests for Generic Backtest

Verifies the generic backtest can:
1. Work with any signal type (not just CarrySignal)
2. Work with any adapter (Futures, Equity, custom)
3. Accept multiple signals with combiner
4. Work with query-based workflow (futures)
5. Work with DataFrame-based workflow (equities)
6. Maintain backwards compatibility with MinimalBacktest usage

Test Organization:
- TestBacktestBasics: Instantiation, validation
- TestFuturesCarryWorkflow: Baseline (same as MinimalBacktest)
- TestFuturesMomentumWorkflow: New capability
- TestMultiSignalWorkflow: Multiple signals + combiner
- TestDataFrameWorkflow: Equity/ETF strategies
- TestComponentInjection: Custom risk models, optimizers
- TestBackwardsCompatibility: MinimalBacktest use cases still work
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import List


# Will implement test classes below
```

**Action**: Create empty test file with structure

**Checkpoint**: Update progress tracker - step 1.2 complete

---

### Step 1.3: Write Test for Basic Instantiation

**Add to `test_backtest.py`:**

```python
class TestBacktestBasics:
    """Test basic instantiation and validation."""

    def test_backtest_can_be_imported(self):
        """Verify Backtest class exists and can be imported."""
        from Backtest.Backtest import Backtest
        assert Backtest is not None

    def test_backtest_requires_signals(self):
        """Backtest raises ValueError if no signals provided."""
        from Backtest.Backtest import Backtest

        with pytest.raises(ValueError, match="Must provide at least one signal"):
            Backtest()

    def test_backtest_accepts_single_signal(self):
        """Backtest accepts a single signal."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal

        signal = CarrySignal(name='carry')
        backtest = Backtest(signals=signal)

        assert backtest is not None
        assert len(backtest.signals) == 1
        assert backtest.signals[0] == signal

    def test_backtest_accepts_signal_list(self):
        """Backtest accepts a list of signals."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Futures.MomentumSignal import MomentumSignal

        carry = CarrySignal(name='carry')
        momentum = MomentumSignal(name='momentum')

        backtest = Backtest(signals=[carry, momentum])

        assert len(backtest.signals) == 2
        assert backtest.signals[0] == carry
        assert backtest.signals[1] == momentum

    def test_backtest_validates_adapter_requires_mdp(self):
        """Backtest raises if adapter provided without mdp."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        with pytest.raises(ValueError, match="Adapter requires mdp"):
            adapter = FuturesAdapter(None)  # This will fail in adapter
            # Actually, test at Backtest level:
            Backtest(
                adapter=adapter,
                mdp=None,  # ← Missing mdp
                signals=CarrySignal()
            )

    def test_backtest_creates_default_components(self):
        """Backtest creates default components if not provided."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.AlphaGenerator import AlphaGenerator
        from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        backtest = Backtest(signals=CarrySignal())

        # Should create defaults
        assert isinstance(backtest.alpha_generator, AlphaGenerator)
        assert isinstance(backtest.risk_model, LedoitWolfShrinkage)
        assert isinstance(backtest.optimizer, MeanVarianceOptimizer)

    def test_backtest_uses_provided_components(self):
        """Backtest uses provided components instead of defaults."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.AlphaGenerator import AlphaGenerator
        from Risk.Covariance.SampleCovariance import SampleCovariance
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Custom components
        custom_alpha = AlphaGenerator(IC=0.10)
        custom_risk = SampleCovariance()
        custom_optimizer = MeanVarianceOptimizer(risk_aversion=5.0)

        backtest = Backtest(
            signals=CarrySignal(),
            alpha_generator=custom_alpha,
            risk_model=custom_risk,
            optimizer=custom_optimizer,
        )

        # Should use provided, not defaults
        assert backtest.alpha_generator == custom_alpha
        assert backtest.risk_model == custom_risk
        assert backtest.optimizer == custom_optimizer
```

**Action**: Add these tests to test file

**Expected Result**: All tests should fail (Backtest class doesn't exist yet)

**Checkpoint**: Update progress tracker - step 1.3 complete

---

### Step 1.4: Write Test for Futures Carry (Baseline)

**Purpose**: Ensure generic Backtest produces same results as MinimalBacktest for futures carry

**Add to `test_backtest.py`:**

```python
class TestFuturesCarryWorkflow:
    """Test futures carry strategy - baseline compatibility with MinimalBacktest."""

    def test_futures_carry_single_date(self, mock_mdp):
        """Backtest runs futures carry for single date."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        carry = CarrySignal(name='carry', standardize=True)
        adapter = FuturesAdapter(mock_mdp)

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=adapter,
            signals=carry,
            risk_aversion=1.0,
            long_only=True,
        )

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15)]

        result = backtest.run(contracts, dates)

        # Should return valid result
        assert result is not None
        assert hasattr(result, 'weights')
        assert hasattr(result, 'returns')
        assert hasattr(result, 'signals')

    def test_futures_carry_multiple_dates(self, mock_mdp):
        """Backtest runs futures carry for multiple dates."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        carry = CarrySignal(name='carry', standardize=True)
        adapter = FuturesAdapter(mock_mdp)

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=adapter,
            signals=carry,
        )

        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
        dates = [
            date(2024, 6, 1),
            date(2024, 6, 8),
            date(2024, 6, 15),
            date(2024, 6, 22),
        ]

        result = backtest.run(contracts, dates)

        # Should have results for multiple periods
        assert len(result.returns) > 0
        assert result.sharpe_ratio is not None
        assert result.ic is not None

    def test_futures_carry_matches_minimal_backtest(self, mock_mdp):
        """Generic Backtest produces same results as MinimalBacktest for carry."""
        from Backtest.Backtest import Backtest
        from Backtest.MinimalBacktest import MinimalBacktest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
        dates = [
            date(2024, 6, 1),
            date(2024, 6, 8),
            date(2024, 6, 15),
        ]

        # MinimalBacktest (old way)
        minimal = MinimalBacktest(
            mdp=mock_mdp,
            risk_aversion=1.0,
            long_only=True,
            IC=0.05,
        )
        minimal_result = minimal.run(contracts, dates)

        # Generic Backtest (new way)
        generic = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(mock_mdp),
            signals=CarrySignal(name='carry', standardize=True),
            risk_aversion=1.0,
            long_only=True,
            IC=0.05,
        )
        generic_result = generic.run(contracts, dates)

        # Results should match
        assert generic_result.sharpe_ratio == pytest.approx(minimal_result.sharpe_ratio, rel=0.01)
        assert generic_result.ic == pytest.approx(minimal_result.ic, rel=0.01)
        assert generic_result.total_return == pytest.approx(minimal_result.total_return, rel=0.01)
```

**Action**: Add these tests

**Expected Result**: Tests will fail until implementation

**Checkpoint**: Update progress tracker - step 1.4 complete

---

### Step 1.5: Write Test for Futures Momentum (New Capability)

**Purpose**: Test what MinimalBacktest CANNOT do - use MomentumSignal

**Add to `test_backtest.py`:**

```python
class TestFuturesMomentumWorkflow:
    """Test futures momentum strategy - NEW capability."""

    def test_futures_momentum_works(self, mock_mdp):
        """Backtest can use MomentumSignal (impossible with MinimalBacktest)."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.MomentumSignal import MomentumSignal

        momentum = MomentumSignal(lookback_days=20, standardize=True)
        adapter = FuturesAdapter(mock_mdp)

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=adapter,
            signals=momentum,  # ← NOT CarrySignal!
        )

        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
        dates = [
            date(2024, 6, 1),
            date(2024, 6, 8),
            date(2024, 6, 15),
        ]

        result = backtest.run(contracts, dates)

        # Should work with momentum signal
        assert result is not None
        assert len(result.returns) > 0

    def test_futures_mean_reversion_works(self, mock_mdp):
        """Backtest can use MeanReversionSignal."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.MeanReversionSignal import MeanReversionSignal

        mean_rev = MeanReversionSignal(lookback_days=30, standardize=True)

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(mock_mdp),
            signals=mean_rev,
        )

        result = backtest.run(
            contracts=['SFRZ4', 'SFRH5'],
            dates=[date(2024, 6, 15)]
        )

        assert result is not None
```

**Action**: Add these tests

**Checkpoint**: Update progress tracker - step 1.5 complete

---

### Step 1.6: Write Test for Multi-Signal Strategy

**Purpose**: Test combining multiple signals (currently impossible)

**Add to `test_backtest.py`:**

```python
class TestMultiSignalWorkflow:
    """Test multi-signal strategies with SignalCombiner."""

    def test_two_signals_with_combiner(self, mock_mdp):
        """Backtest combines carry + momentum signals."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Futures.MomentumSignal import MomentumSignal
        from Signals.SignalCombiner import SignalCombiner

        carry = CarrySignal(name='carry')
        momentum = MomentumSignal(name='momentum', lookback_days=20)
        combiner = SignalCombiner(method='equal')

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(mock_mdp),
            signals=[carry, momentum],  # ← Multiple signals!
            signal_combiner=combiner,
        )

        result = backtest.run(
            contracts=['SFRZ4', 'SFRH5', 'SFRM5'],
            dates=[date(2024, 6, 1), date(2024, 6, 8)]
        )

        assert result is not None
        assert len(result.signals) > 0  # Should have combined signals

    def test_three_signals_with_ic_weighting(self, mock_mdp):
        """Backtest combines 3 signals with IC-based weighting."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal
        from Signals.Futures.MomentumSignal import MomentumSignal
        from Signals.Futures.MeanReversionSignal import MeanReversionSignal
        from Signals.SignalCombiner import SignalCombiner

        signals = [
            CarrySignal(name='carry'),
            MomentumSignal(name='momentum'),
            MeanReversionSignal(name='mean_rev'),
        ]
        combiner = SignalCombiner(method='ic_weighted')

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(mock_mdp),
            signals=signals,
            signal_combiner=combiner,
        )

        result = backtest.run(
            contracts=['SFRZ4', 'SFRH5'],
            dates=[date(2024, 6, 15)]
        )

        assert result is not None

    def test_single_signal_no_combiner_needed(self, mock_mdp):
        """Single signal doesn't use combiner."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        backtest = Backtest(
            mdp=mock_mdp,
            adapter=FuturesAdapter(mock_mdp),
            signals=CarrySignal(),
            # No combiner needed for single signal
        )

        assert backtest.signal_combiner is None  # Not needed for 1 signal
```

**Action**: Add these tests

**Checkpoint**: Update progress tracker - step 1.6 complete

---

### Step 1.7: Write Test for DataFrame Input (Equity Workflow)

**Purpose**: Test new DataFrame-based workflow for equities

**Add to `test_backtest.py`:**

```python
class TestDataFrameWorkflow:
    """Test DataFrame-based workflow for equity strategies."""

    def test_run_from_dataframe_basic(self):
        """Backtest can run from pre-computed returns DataFrame."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.MomentumSignal import MomentumSignal

        # Create mock returns DataFrame
        returns_df = pl.DataFrame({
            'date': [date(2024, 6, 1)] * 3 + [date(2024, 6, 8)] * 3,
            'ticker': ['AAPL', 'MSFT', 'GOOGL'] * 2,
            'return': [0.01, 0.02, -0.01, 0.015, -0.005, 0.02],
        })

        backtest = Backtest(
            signals=MomentumSignal(),
            # No mdp or adapter needed!
        )

        dates = [date(2024, 6, 1), date(2024, 6, 8)]

        result = backtest.run_from_dataframe(
            returns_df=returns_df,
            dates=dates,
        )

        assert result is not None
        assert len(result.returns) >= 0

    def test_run_from_dataframe_validates_no_adapter(self):
        """run_from_dataframe raises if adapter provided."""
        from Backtest.Backtest import Backtest
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.Futures.CarrySignal import CarrySignal

        # This configuration doesn't make sense:
        # DataFrame workflow + adapter (adapter not used)
        backtest = Backtest(
            mdp=None,  # Mock mdp
            adapter=FuturesAdapter(None),
            signals=CarrySignal(),
        )

        returns_df = pl.DataFrame({
            'date': [date(2024, 6, 1)],
            'ticker': ['AAPL'],
            'return': [0.01],
        })

        with pytest.raises(ValueError, match="DataFrame workflow doesn't use adapter"):
            backtest.run_from_dataframe(returns_df, dates=[date(2024, 6, 1)])

    def test_run_validates_has_adapter(self, mock_mdp):
        """run() raises if no adapter provided."""
        from Backtest.Backtest import Backtest
        from Signals.Futures.CarrySignal import CarrySignal

        backtest = Backtest(
            # No adapter!
            signals=CarrySignal(),
        )

        with pytest.raises(ValueError, match="Query-based workflow requires adapter"):
            backtest.run(
                contracts=['SFRZ4'],
                dates=[date(2024, 6, 1)]
            )
```

**Action**: Add these tests

**Checkpoint**: Update progress tracker - step 1.7 complete

---

## Phase 2: Implement Backtest Class

### Step 2.1: Create Backtest Class Skeleton

**File**: `Backtest/Backtest.py` (NEW)

**Initial Content:**

```python
# ABOUTME: Generic backtest supporting all asset classes and signal types
# ABOUTME: Configurable components via dependency injection, two workflows (query/DataFrame)

"""
Generic Backtest

Flexible backtest engine supporting:
- Any signal type (carry, momentum, mean reversion, custom)
- Any adapter (futures, equities, custom)
- Multiple signals with combiner
- Query-based workflow (futures, swaps)
- DataFrame-based workflow (equities, ETFs)
- Custom risk models and optimizers

Usage Patterns:

1. Futures Carry (same as MinimalBacktest):
   >>> backtest = Backtest(
   ...     mdp=market_data_provider,
   ...     adapter=FuturesAdapter(mdp),
   ...     signals=CarrySignal()
   ... )
   >>> result = backtest.run(contracts=['SFRZ4'], dates=[...])

2. Futures Momentum (new capability):
   >>> backtest = Backtest(
   ...     mdp=mdp,
   ...     adapter=FuturesAdapter(mdp),
   ...     signals=MomentumSignal(lookback=20)
   ... )
   >>> result = backtest.run(contracts=['SFRZ4'], dates=[...])

3. Multi-Signal (new capability):
   >>> backtest = Backtest(
   ...     mdp=mdp,
   ...     adapter=FuturesAdapter(mdp),
   ...     signals=[CarrySignal(), MomentumSignal()],
   ...     signal_combiner=SignalCombiner(method='ic_weighted')
   ... )
   >>> result = backtest.run(contracts=['SFRZ4'], dates=[...])

4. Equity/ETF Strategies (new capability):
   >>> backtest = Backtest(
   ...     signals=VolatilitySignal(),
   ...     risk_aversion=3.0
   ... )
   >>> result = backtest.run_from_dataframe(returns_df, dates=[...])

Component Injection:
- All components are configurable
- Sensible defaults provided
- Easy for simple cases, flexible for advanced
"""

from datetime import date
from typing import Any, List, Optional, Union
import numpy as np
import polars as pl

from Backtest.Base.BaseBacktest import BaseBacktest, BacktestResult
from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Returns.ReturnsCalculator import ReturnsCalculator
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer


class Backtest(BaseBacktest):
    """
    Generic backtest with configurable components.

    Supports two workflows:
    1. Query-based: mdp + adapter + contracts → run()
    2. DataFrame-based: returns_df → run_from_dataframe()
    """

    def __init__(
        self,
        # Data source (query workflow)
        mdp: Optional[Any] = None,
        adapter: Optional[Any] = None,  # BaseAdapter

        # Signals (required)
        signals: Optional[Union[BaseSignal, List[BaseSignal]]] = None,
        signal_combiner: Optional[Any] = None,  # SignalCombiner

        # Pipeline components (optional)
        alpha_generator: Optional[AlphaGenerator] = None,
        risk_model: Optional[Any] = None,
        optimizer: Optional[Any] = None,
        returns_calculator: Optional[ReturnsCalculator] = None,

        # Convenience parameters
        IC: float = 0.05,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        min_history: int = 20,
    ):
        """
        Initialize generic backtest.

        See class docstring for usage examples.
        """
        # Will implement in next step
        pass

    def run(
        self,
        contracts: List[str],
        dates: List[date],
    ) -> BacktestResult:
        """
        Run backtest using query-based workflow.

        Requires: self.mdp and self.adapter

        Args:
            contracts: List of contract codes (e.g., ['SFRZ4', 'SFRH5'])
            dates: List of rebalance dates

        Returns:
            BacktestResult with performance metrics
        """
        # Will implement in step 2.3
        pass

    def run_from_dataframe(
        self,
        returns_df: pl.DataFrame,
        dates: List[date],
        instruments: Optional[List[str]] = None,
    ) -> BacktestResult:
        """
        Run backtest from pre-computed returns DataFrame.

        No adapter needed - returns already provided.

        Args:
            returns_df: DataFrame with ['date', 'ticker', 'return']
            dates: List of rebalance dates
            instruments: Tickers to trade (optional)

        Returns:
            BacktestResult with performance metrics
        """
        # Will implement in step 2.4
        pass
```

**Action**: Create file with skeleton

**Checkpoint**: Update progress tracker - step 2.1 complete

---

### Step 2.2: Implement __init__ with Validation

**Add to `Backtest.__init__`:**

```python
def __init__(
    self,
    mdp: Optional[Any] = None,
    adapter: Optional[Any] = None,
    signals: Optional[Union[BaseSignal, List[BaseSignal]]] = None,
    signal_combiner: Optional[Any] = None,
    alpha_generator: Optional[AlphaGenerator] = None,
    risk_model: Optional[Any] = None,
    optimizer: Optional[Any] = None,
    returns_calculator: Optional[ReturnsCalculator] = None,
    IC: float = 0.05,
    risk_aversion: float = 1.0,
    long_only: bool = True,
    min_history: int = 20,
):
    """Initialize generic backtest with component injection."""

    # Call parent
    super().__init__(mdp)

    # Validate: Must provide signals
    if signals is None:
        raise ValueError("Must provide at least one signal")

    # Validate: Adapter requires mdp
    if adapter is not None and mdp is None:
        raise ValueError("Adapter requires mdp to be provided")

    # Store configuration
    self.adapter = adapter
    self.min_history = min_history

    # Handle signals (convert single to list)
    if isinstance(signals, BaseSignal):
        self.signals = [signals]
    else:
        self.signals = signals if signals else []

    # Create signal combiner if multiple signals
    if len(self.signals) > 1:
        if signal_combiner is None:
            # Import here to avoid circular dependency
            from Signals.SignalCombiner import SignalCombiner
            self.signal_combiner = SignalCombiner(method='equal')
        else:
            self.signal_combiner = signal_combiner
    else:
        self.signal_combiner = signal_combiner  # None for single signal

    # Create or use provided components
    self.alpha_generator = alpha_generator or AlphaGenerator(IC=IC)
    self.risk_model = risk_model or LedoitWolfShrinkage()
    self.optimizer = optimizer or MeanVarianceOptimizer(
        risk_aversion=risk_aversion,
        long_only=long_only,
    )
    self.returns_calc = returns_calculator or ReturnsCalculator(method="percent")
```

**Action**: Implement __init__ with full validation

**Test**: Run tests from step 1.3 - should now pass

**Checkpoint**: Update progress tracker - step 2.2 complete

---

### Step 2.3: Implement run() Method (Query Workflow)

**Strategy**: Copy logic from MinimalBacktest.run() but use self.signals instead of hardcoded CarrySignal

**Implementation Details:**

```python
def run(
    self,
    contracts: List[str],
    dates: List[date],
) -> BacktestResult:
    """Run backtest using query-based workflow."""

    # Validate workflow requirements
    if self.adapter is None or self.mdp is None:
        raise ValueError(
            "Query-based workflow requires adapter and mdp. "
            "Use run_from_dataframe() for DataFrame-based workflow."
        )

    if len(contracts) == 0 or len(dates) == 0:
        return self._empty_result()

    # Storage
    all_weights = []
    all_signals = []
    all_prices = []
    all_returns = []
    return_history = []

    # Create queries (adapter-specific)
    # For FuturesAdapter, this creates FuturesQuery objects
    # For EquityAdapter (future), would create EquityQuery objects
    queries = self._create_queries(contracts)

    previous_weights = None
    previous_prices = None

    for i, as_of in enumerate(dates):
        # Ensure date object
        if hasattr(as_of, 'date'):
            as_of = as_of.date()

        # Step 1: Get data via adapter
        df = self.adapter.convert(queries, as_of)

        if len(df) == 0:
            continue

        # Step 2: Extract prices
        prices = self._extract_prices(df, as_of)
        all_prices.append({'date': as_of, **prices})

        # Step 3: Calculate returns
        if previous_prices is not None and previous_weights is not None:
            returns_dict = self.returns_calc.calculate_returns(prices, previous_prices)
            if len(returns_dict) > 0:
                return_history.append(returns_dict)

                # Portfolio return
                common_contracts = list(set(returns_dict.keys()) & set(previous_weights.keys()))
                if len(common_contracts) > 0:
                    port_ret = sum(
                        previous_weights[c] * returns_dict.get(c, 0.0)
                        for c in common_contracts
                    )
                    all_returns.append({'date': as_of, 'return': port_ret})

        # Step 4: Generate signals
        # THIS IS THE KEY DIFFERENCE FROM MinimalBacktest
        # We use self.signals instead of hardcoded CarrySignal
        if len(self.signals) == 1:
            # Single signal - calculate directly
            signal_values = self._calculate_signal(self.signals[0], df, as_of, return_history)
        else:
            # Multiple signals - calculate each and combine
            individual_signals = []
            for signal in self.signals:
                sig_vals = self._calculate_signal(signal, df, as_of, return_history)
                individual_signals.append(sig_vals)

            # Combine using signal combiner
            signal_values = self.signal_combiner.combine(individual_signals)

        all_signals.append({'date': as_of, **signal_values})

        # Step 5: Estimate covariance
        if len(return_history) >= self.min_history:
            returns_df = pl.DataFrame(return_history).fill_null(0)
            cov_matrix = self.risk_model.fit(returns_df)
        else:
            cov_matrix = np.eye(len(signal_values)) * 0.01

        # Step 6: Convert signals → alphas
        z_scores = self._standardize_signals(signal_values)

        if len(return_history) > 0:
            returns_df = pl.DataFrame(return_history).fill_null(0)
            alphas = self.alpha_generator.signals_to_alphas(
                z_scores,
                returns_df,
                as_of
            )
        else:
            alphas = z_scores

        # Step 7: Optimize weights
        try:
            weights = self.optimizer.optimize(alphas, cov_matrix)
            all_weights.append({'date': as_of, **weights})
            previous_weights = weights
        except Exception:
            equal_weights = {c: 1.0 / len(alphas) for c in alphas.keys()}
            all_weights.append({'date': as_of, **equal_weights})
            previous_weights = equal_weights

        previous_prices = prices

    # Convert to DataFrames
    weights_df = pl.DataFrame(all_weights).fill_null(0) if all_weights else pl.DataFrame()
    signals_df = pl.DataFrame(all_signals).fill_null(0) if all_signals else pl.DataFrame()
    prices_df = pl.DataFrame(all_prices).fill_null(0) if all_prices else pl.DataFrame()

    # Returns series
    if all_returns:
        dates_list = [r['date'] for r in all_returns]
        values = [r['return'] for r in all_returns]
        returns_series = pl.Series(values=values)
    else:
        returns_series = pl.Series(values=[], dtype=pl.Float64)

    # Calculate metrics
    ic = self._calculate_ic(signals_df, returns_series)
    sharpe = self._calculate_sharpe(returns_series)
    total_return = self._calculate_total_return(returns_series)

    return BacktestResult(
        weights=weights_df,
        returns=returns_series,
        signals=signals_df,
        prices=prices_df,
        ic=ic,
        sharpe_ratio=sharpe,
        total_return=total_return,
    )


def _create_queries(self, contracts: List[str]):
    """Create queries for adapter (adapter-specific)."""
    # For FuturesAdapter
    from Query.Futures.FuturesQuery import FuturesQuery
    from Query.Futures.FuturesStructure import FuturesStructure

    return [
        FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract=c)
        for c in contracts
    ]


def _extract_prices(self, df: pl.DataFrame, as_of: date) -> dict:
    """Extract prices from adapter DataFrame."""
    if isinstance(df, pl.DataFrame):
        prices = {row['contract']: row['price'] for row in df.iter_rows(named=True)}
    else:
        prices = {row['contract']: row['price'] for _, row in df.iterrows()}
    return prices


def _calculate_signal(
    self,
    signal: BaseSignal,
    df: pl.DataFrame,
    as_of: date,
    return_history: List[dict]
) -> dict:
    """Calculate signal values for current date."""
    # This depends on signal type
    # For now, use signal's calculate method
    # Different signals have different interfaces - need to handle

    # Simplified: assume signal can calculate from df
    signal_values = {}

    # Iterate through instruments in df
    if isinstance(df, pl.DataFrame):
        for row in df.iter_rows(named=True):
            contract = row['contract']
            # Signal calculation (signal-specific logic)
            # For CarrySignal, calculate carry
            # For MomentumSignal, calculate momentum
            # etc.

            # Call signal's calculate method
            sig_val = signal.calculate(row, return_history, as_of)
            signal_values[contract] = sig_val

    return signal_values


def _standardize_signals(self, signal_values: dict) -> dict:
    """Convert signal values to z-scores."""
    values = list(signal_values.values())
    if len(values) == 0:
        return signal_values

    if np.std(values) > 0:
        mean_sig = np.mean(values)
        std_sig = np.std(values)
        z_scores = {
            k: (signal_values[k] - mean_sig) / std_sig
            for k in signal_values.keys()
        }
    else:
        z_scores = signal_values

    return z_scores


# Copy helper methods from MinimalBacktest:
# - _calculate_ic()
# - _calculate_sharpe()
# - _calculate_total_return()
# - _empty_result()
```

**Action**: Implement run() method with full logic

**Note**: The signal calculation logic needs to be generalized - different signals have different calculation methods. Will need to standardize or use signal's built-in methods.

**Test**: Run tests from steps 1.4, 1.5, 1.6 - should pass

**Checkpoint**: Update progress tracker - step 2.3 complete

---

### Step 2.4: Implement run_from_dataframe() Method

**Purpose**: Enable equity/ETF strategies without adapter/mdp

**Implementation:**

```python
def run_from_dataframe(
    self,
    returns_df: pl.DataFrame,
    dates: List[date],
    instruments: Optional[List[str]] = None,
) -> BacktestResult:
    """Run backtest from pre-computed returns DataFrame."""

    # Validate
    if self.adapter is not None:
        raise ValueError(
            "DataFrame workflow doesn't use adapter. "
            "Use run() for query-based workflow."
        )

    # Validate DataFrame has required columns
    required_cols = ['date', 'ticker', 'return']
    for col in required_cols:
        if col not in returns_df.columns:
            raise ValueError(f"returns_df missing required column: {col}")

    # Filter to specified instruments if provided
    if instruments is not None:
        returns_df = returns_df.filter(pl.col('ticker').is_in(instruments))

    if len(returns_df) == 0:
        return self._empty_result()

    # Get all tickers
    all_tickers = returns_df['ticker'].unique().to_list()

    # Storage
    all_weights = []
    all_signals = []
    all_returns = []
    return_history = []

    previous_weights = None

    for i, as_of in enumerate(dates):
        # Ensure date object
        if hasattr(as_of, 'date'):
            as_of = as_of.date()

        # Step 1: Get returns up to this date
        historical_returns = returns_df.filter(pl.col('date') <= as_of)

        if len(historical_returns) == 0:
            continue

        # Step 2: Calculate signals from returns
        # Signals need returns history, not just current date
        # Pass historical_returns to signal calculation

        if len(self.signals) == 1:
            signal_values = self._calculate_signal_from_returns(
                self.signals[0],
                historical_returns,
                as_of,
                all_tickers
            )
        else:
            individual_signals = []
            for signal in self.signals:
                sig_vals = self._calculate_signal_from_returns(
                    signal,
                    historical_returns,
                    as_of,
                    all_tickers
                )
                individual_signals.append(sig_vals)

            signal_values = self.signal_combiner.combine(individual_signals)

        all_signals.append({'date': as_of, **signal_values})

        # Step 3: Build return history for covariance
        # Pivot returns to wide format
        returns_wide = historical_returns.pivot(
            index='date',
            on='ticker',
            values='return'
        )

        # Step 4: Estimate covariance
        if len(returns_wide) >= self.min_history:
            cov_matrix = self.risk_model.fit(returns_wide)
        else:
            cov_matrix = np.eye(len(signal_values)) * 0.01

        # Step 5: Convert signals → alphas
        z_scores = self._standardize_signals(signal_values)

        if len(returns_wide) > 0:
            alphas = self.alpha_generator.signals_to_alphas(
                z_scores,
                returns_wide,
                as_of
            )
        else:
            alphas = z_scores

        # Step 6: Optimize weights
        try:
            weights = self.optimizer.optimize(alphas, cov_matrix)
            all_weights.append({'date': as_of, **weights})

            # Calculate portfolio return for this period
            if previous_weights is not None:
                # Get returns for this date
                current_returns = returns_df.filter(pl.col('date') == as_of)
                if len(current_returns) > 0:
                    returns_dict = {
                        row['ticker']: row['return']
                        for row in current_returns.iter_rows(named=True)
                    }

                    # Weighted return
                    common = set(returns_dict.keys()) & set(previous_weights.keys())
                    if len(common) > 0:
                        port_ret = sum(
                            previous_weights[t] * returns_dict[t]
                            for t in common
                        )
                        all_returns.append({'date': as_of, 'return': port_ret})

            previous_weights = weights

        except Exception:
            equal_weights = {t: 1.0 / len(alphas) for t in alphas.keys()}
            all_weights.append({'date': as_of, **equal_weights})
            previous_weights = equal_weights

    # Convert to DataFrames
    weights_df = pl.DataFrame(all_weights).fill_null(0) if all_weights else pl.DataFrame()
    signals_df = pl.DataFrame(all_signals).fill_null(0) if all_signals else pl.DataFrame()

    # Returns series
    if all_returns:
        values = [r['return'] for r in all_returns]
        returns_series = pl.Series(values=values)
    else:
        returns_series = pl.Series(values=[], dtype=pl.Float64)

    # Calculate metrics
    ic = self._calculate_ic(signals_df, returns_series)
    sharpe = self._calculate_sharpe(returns_series)
    total_return = self._calculate_total_return(returns_series)

    return BacktestResult(
        weights=weights_df,
        returns=returns_series,
        signals=signals_df,
        prices=pl.DataFrame(),  # No prices in DataFrame workflow
        ic=ic,
        sharpe_ratio=sharpe,
        total_return=total_return,
    )


def _calculate_signal_from_returns(
    self,
    signal: BaseSignal,
    returns_df: pl.DataFrame,
    as_of: date,
    tickers: List[str]
) -> dict:
    """Calculate signal from returns DataFrame."""
    # Signal calculation from returns history
    # Different for each signal type

    # For now, simplified implementation
    # Real implementation would call signal's calculate method

    signal_values = {}
    for ticker in tickers:
        ticker_returns = returns_df.filter(pl.col('ticker') == ticker)

        # Call signal's calculate method (signal-specific)
        sig_val = signal.calculate_from_returns(ticker_returns, as_of)
        signal_values[ticker] = sig_val

    return signal_values
```

**Action**: Implement run_from_dataframe() method

**Test**: Run tests from step 1.7 - should pass

**Checkpoint**: Update progress tracker - step 2.4 complete

---

### Step 2.5: Run All Tests and Fix Issues

**Action**: Run full test suite

```bash
pytest tests/unit/backtest/test_backtest.py -v
```

**Expected Issues:**
1. Signal calculation methods may not match interface
2. Some signals may not have `calculate_from_returns()` method
3. SignalCombiner import may need fixing

**Fix Strategy:**
- Adjust signal calculation to use existing signal interfaces
- Add adapter methods if needed
- Fix imports

**Checkpoint**: Update progress tracker - step 2.5 complete when all tests pass

---

## Phase 3: Integration and Deprecation

### Step 3.1: Update Backtest/__init__.py

**Current Content:**
```python
from Backtest.MinimalBacktest import MinimalBacktest

__all__ = ['MinimalBacktest']
```

**New Content:**
```python
from Backtest.Base.BaseBacktest import BaseBacktest, BacktestResult
from Backtest.Backtest import Backtest  # New generic class
from Backtest.MinimalBacktest import MinimalBacktest  # Deprecated

__all__ = [
    'BaseBacktest',
    'BacktestResult',
    'Backtest',  # ← Use this for new code
    'MinimalBacktest',  # ← Backwards compatibility only
]
```

**Action**: Update __init__.py

**Checkpoint**: Update progress tracker - step 3.1 complete

---

### Step 3.2: Add Deprecation Warning to MinimalBacktest

**File**: `Backtest/MinimalBacktest.py`

**Add at top of __init__:**

```python
def __init__(
    self,
    mdp: Any,
    risk_aversion: float = 1.0,
    long_only: bool = True,
    min_history: int = 20,
    IC: float = 0.05,
):
    """
    Initialize minimal backtest.

    DEPRECATED: This class is hardcoded to futures carry strategies.

    For other signals or asset classes, use the generic Backtest class instead:

    >>> from Backtest.Backtest import Backtest
    >>> from Signals.Futures.MomentumSignal import MomentumSignal
    >>> backtest = Backtest(
    ...     mdp=mdp,
    ...     adapter=FuturesAdapter(mdp),
    ...     signals=MomentumSignal()
    ... )

    Args:
        mdp: Market data provider
        risk_aversion: Risk aversion λ (higher = more conservative)
        long_only: If True, only allow positive weights
        min_history: Minimum periods needed for covariance estimation
        IC: Information Coefficient (forecasting skill, default 0.05)
    """
    import warnings
    warnings.warn(
        "MinimalBacktest is deprecated and limited to futures carry strategies. "
        "Use Backtest class with injected components for other signals/asset classes.",
        DeprecationWarning,
        stacklevel=2
    )

    # Original implementation continues...
    super().__init__(mdp)
    # ... rest of original code
```

**Action**: Add deprecation warning

**Test**: Run MinimalBacktest tests - should still pass but show warning

**Checkpoint**: Update progress tracker - step 3.2 complete

---

### Step 3.3: Run All Existing Tests

**Purpose**: Ensure backwards compatibility

**Action**: Run full test suite

```bash
pytest tests/unit/backtest/ -v
pytest tests/integration/ -k backtest -v
```

**Expected**: All tests pass, deprecation warnings shown for MinimalBacktest

**Fix**: Any broken tests

**Checkpoint**: Update progress tracker - step 3.3 complete

---

## Phase 4: Proof of Concept Migration

### Step 4.1: Migrate Notebook 07 (Momentum Strategy)

**File**: `notebooks/07_momentum_strategy_complete.ipynb`

**Current Problem**: Can't use MomentumSignal with MinimalBacktest

**Find cell with MinimalBacktest usage:**

Look for pattern:
```python
# Currently might be using components directly or workaround
```

**Replace with:**

```python
# NEW: Can now use MomentumSignal with generic Backtest!
from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.MomentumSignal import MomentumSignal

# Create momentum signal
momentum = MomentumSignal(
    lookback_days=20,
    standardize=True,
    name='momentum'
)

# Create backtest with momentum signal
backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=momentum,  # ← NOT CarrySignal!
    risk_aversion=1.0,
    long_only=True,
    IC=0.05,
)

# Run backtest
contracts = ['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5']
dates = pl.date_range(start_date, end_date, "1w", eager=True).to_list()
dates = [d.date() if hasattr(d, 'date') else d for d in dates]

result = backtest.run(contracts=contracts, dates=dates)

# Display results
print(f"Sharpe Ratio: {result.sharpe_ratio:.3f}")
print(f"Information Coefficient: {result.ic:.3f}")
print(f"Total Return: {result.total_return:.2%}")
```

**Add explanation cell:**

```markdown
## 🎉 Using Generic Backtest

This notebook now uses the **generic Backtest class** instead of MinimalBacktest.

**Why this matters:**
- MinimalBacktest is hardcoded to CarrySignal (can't use momentum)
- Generic Backtest accepts **any signal type** via dependency injection
- Showcases the library's modular architecture

**What changed:**
```python
# Old (didn't work):
backtest = MinimalBacktest(mdp=mdp)  # ❌ Hardcoded to CarrySignal

# New (works!):
backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=MomentumSignal()  # ✅ Any signal!
)
```
```

**Action**: Migrate notebook 07

**Test**: Run notebook - should execute successfully

**Checkpoint**: Update progress tracker - step 4.1 complete

---

### Step 4.2: Create Generic Backtest Example

**File**: `examples/run_generic_backtest.py` (NEW)

**Content:**

```python
# ABOUTME: Examples showing different Backtest configurations
# ABOUTME: Demonstrates futures carry, momentum, multi-signal, and equity workflows

"""
Generic Backtest Examples

This script demonstrates the flexible Backtest class with different configurations:

1. Futures Carry (baseline - same as MinimalBacktest)
2. Futures Momentum (new capability)
3. Multi-Signal Strategy (carry + momentum + mean reversion)
4. Equity/ETF Strategy (DataFrame workflow)

Key Point: One backtest engine, many strategies.
"""

from datetime import date
import numpy as np
import polars as pl

from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal
from Signals.Futures.MeanReversionSignal import MeanReversionSignal
from Signals.SignalCombiner import SignalCombiner


def example_1_futures_carry():
    """Example 1: Futures Carry (baseline)."""
    print("\n" + "="*70)
    print("EXAMPLE 1: Futures Carry Strategy")
    print("="*70)

    # Setup (same as run_minimal_backtest.py)
    from examples.run_minimal_backtest import SimpleMockMDP

    mdp = SimpleMockMDP(base_rate=5.0, carry_spread=0.10)

    # Create backtest with CarrySignal
    backtest = Backtest(
        mdp=mdp,
        adapter=FuturesAdapter(mdp),
        signals=CarrySignal(name='carry', standardize=True),
        risk_aversion=1.0,
        long_only=True,
    )

    # Run
    contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
    dates = pl.date_range(date(2024, 9, 1), date(2024, 12, 1), "1w", eager=True).to_list()
    dates = [d.date() if hasattr(d, 'date') else d for d in dates]

    result = backtest.run(contracts, dates)

    print(f"\nResults:")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.3f}")
    print(f"  IC: {result.ic:.3f}")
    print(f"  Total Return: {result.total_return:.2%}")
    print("\n✅ Same as MinimalBacktest")


def example_2_futures_momentum():
    """Example 2: Futures Momentum (NEW CAPABILITY)."""
    print("\n" + "="*70)
    print("EXAMPLE 2: Futures Momentum Strategy")
    print("="*70)
    print("💡 This was IMPOSSIBLE with MinimalBacktest\n")

    from examples.run_minimal_backtest import SimpleMockMDP

    mdp = SimpleMockMDP(base_rate=5.0, carry_spread=0.10)

    # Create backtest with MomentumSignal
    backtest = Backtest(
        mdp=mdp,
        adapter=FuturesAdapter(mdp),
        signals=MomentumSignal(lookback_days=20, standardize=True),  # ← Different signal!
        risk_aversion=1.0,
        long_only=True,
    )

    contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
    dates = pl.date_range(date(2024, 9, 1), date(2024, 12, 1), "1w", eager=True).to_list()
    dates = [d.date() if hasattr(d, 'date') else d for d in dates]

    result = backtest.run(contracts, dates)

    print(f"\nResults:")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.3f}")
    print(f"  IC: {result.ic:.3f}")
    print(f"  Total Return: {result.total_return:.2%}")
    print("\n✅ Generic Backtest enables any signal type")


def example_3_multi_signal():
    """Example 3: Multi-Signal Strategy (NEW CAPABILITY)."""
    print("\n" + "="*70)
    print("EXAMPLE 3: Multi-Signal Strategy (Carry + Momentum + Mean Reversion)")
    print("="*70)
    print("💡 This was IMPOSSIBLE with MinimalBacktest\n")

    from examples.run_minimal_backtest import SimpleMockMDP

    mdp = SimpleMockMDP(base_rate=5.0, carry_spread=0.10)

    # Create three signals
    carry = CarrySignal(name='carry', standardize=True)
    momentum = MomentumSignal(name='momentum', lookback_days=20, standardize=True)
    mean_rev = MeanReversionSignal(name='mean_rev', lookback_days=30, standardize=True)

    # Create backtest with multiple signals
    backtest = Backtest(
        mdp=mdp,
        adapter=FuturesAdapter(mdp),
        signals=[carry, momentum, mean_rev],  # ← Multiple signals!
        signal_combiner=SignalCombiner(method='equal'),
        risk_aversion=1.0,
        long_only=True,
    )

    contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
    dates = pl.date_range(date(2024, 9, 1), date(2024, 12, 1), "1w", eager=True).to_list()
    dates = [d.date() if hasattr(d, 'date') else d for d in dates]

    result = backtest.run(contracts, dates)

    print(f"\nResults:")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.3f}")
    print(f"  IC: {result.ic:.3f}")
    print(f"  Total Return: {result.total_return:.2%}")
    print("\n✅ Generic Backtest enables signal combination")


def example_4_equity_dataframe():
    """Example 4: Equity Strategy with DataFrame (NEW CAPABILITY)."""
    print("\n" + "="*70)
    print("EXAMPLE 4: Equity Strategy (DataFrame Workflow)")
    print("="*70)
    print("💡 This was IMPOSSIBLE with MinimalBacktest\n")

    # Create mock equity returns
    np.random.seed(42)
    tickers = ['AAPL', 'MSFT', 'GOOGL', 'NVDA']
    dates_list = pl.date_range(date(2024, 1, 1), date(2024, 6, 1), "1d", eager=True).to_list()

    returns_data = []
    for ticker in tickers:
        for d in dates_list:
            d_obj = d.date() if hasattr(d, 'date') else d
            ret = np.random.normal(0.001, 0.02)
            returns_data.append({
                'date': d_obj,
                'ticker': ticker,
                'return': ret,
            })

    returns_df = pl.DataFrame(returns_data)

    # Create backtest (no mdp or adapter needed!)
    backtest = Backtest(
        signals=MomentumSignal(lookback_days=20),
        risk_aversion=3.0,
        long_only=False,  # Allow shorts
    )

    # Run from DataFrame
    rebalance_dates = pl.date_range(date(2024, 1, 1), date(2024, 6, 1), "1w", eager=True).to_list()
    rebalance_dates = [d.date() if hasattr(d, 'date') else d for d in rebalance_dates]

    result = backtest.run_from_dataframe(
        returns_df=returns_df,
        dates=rebalance_dates,
    )

    print(f"\nResults:")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:.3f}")
    print(f"  IC: {result.ic:.3f}")
    print(f"  Total Return: {result.total_return:.2%}")
    print("\n✅ Generic Backtest enables equity strategies")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("GENERIC BACKTEST EXAMPLES")
    print("Demonstrating flexible architecture")
    print("="*70)

    example_1_futures_carry()
    example_2_futures_momentum()
    example_3_multi_signal()
    example_4_equity_dataframe()

    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print("\nOne Backtest class, many strategies:")
    print("  ✅ Futures carry (baseline)")
    print("  ✅ Futures momentum (new)")
    print("  ✅ Multi-signal (new)")
    print("  ✅ Equity strategies (new)")
    print("\nMinimalBacktest could only do the first one.")
    print("="*70 + "\n")
```

**Action**: Create example file

**Test**: Run `python examples/run_generic_backtest.py`

**Checkpoint**: Update progress tracker - step 4.2 complete

---

## Phase 5: Documentation Updates

### Step 5.1: Update CLAUDE.md

**Find and replace:**

```markdown
# OLD:
### ✅ Architecture Status (582 tests passing)

**MVP V1 - Core Pipeline (169 tests)**
- **Backtest** (12 tests): MinimalBacktest end-to-end integration

**End-to-end example**: `examples/run_minimal_backtest.py` demonstrates full pipeline

# NEW:
### ✅ Architecture Status (XXX tests passing)

**MVP V1 - Core Pipeline (XXX tests)**
- **Backtest** (XX tests): Generic Backtest with configurable components
- **Backwards Compat** (12 tests): MinimalBacktest (deprecated, futures carry only)

**End-to-end examples**:
- `examples/run_generic_backtest.py` - Multiple strategies with one backtest class
- `examples/run_minimal_backtest.py` - Legacy futures carry example
```

**Remove "Minimal → Maximal" section:**

```markdown
# DELETE:
2. **Minimal → Maximal Approach**
   - Start with simplest working implementation (Minimal)
   - Prove it works end-to-end
   - Then add complexity (Maximal) only when needed
   - Each component independently tested before integration
```

**Add Backtest section:**

```markdown
## Backtest Architecture

The `Backtest` class is the generic backtest engine supporting all strategies:

**Component Injection**:
- Adapter: FuturesAdapter, EquityAdapter, or custom
- Signals: Single or multiple signals with combiner
- Risk Model: LedoitWolf, SampleCovariance, or custom
- Optimizer: MeanVariance, RiskParity, or custom

**Two Workflows**:
1. **Query-based** (futures, swaps): `backtest.run(contracts, dates)`
2. **DataFrame-based** (equities): `backtest.run_from_dataframe(returns_df, dates)`

**MinimalBacktest (Deprecated)**:
- Kept for backwards compatibility
- Hardcoded to futures carry strategies
- Use `Backtest` for new code
```

**Action**: Update CLAUDE.md

**Checkpoint**: Update progress tracker - step 5.1 complete

---

### Step 5.2: Final Commit and Push

**Action**: Commit all changes

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: Implement generic Backtest class to replace futures-only MinimalBacktest

PROBLEM:
- MinimalBacktest hardcoded to FuturesAdapter + CarrySignal
- Impossible to use other signals (momentum, mean reversion)
- Impossible to use other asset classes (equities, ETFs)
- Impossible to combine multiple signals
- Name "Minimal" was misleading - it's futures-specific, not minimal

SOLUTION:
Created generic Backtest class with component injection:
- Accept any adapter (FuturesAdapter, EquityAdapter, custom)
- Accept any signal(s) - single or list with combiner
- Accept any risk model, optimizer
- Two workflows: run() for queries, run_from_dataframe() for DataFrames

IMPLEMENTATION:
- Backtest/Backtest.py: New generic class (350 lines)
- tests/unit/backtest/test_backtest.py: Comprehensive tests (XXX tests)
- Backtest/__init__.py: Export Backtest, deprecate MinimalBacktest
- Backtest/MinimalBacktest.py: Add deprecation warning
- examples/run_generic_backtest.py: Show 4 different configurations
- notebooks/07_momentum_strategy_complete.ipynb: Migrated to Backtest

BACKWARDS COMPATIBILITY:
- MinimalBacktest still works (with deprecation warning)
- All existing tests pass
- Gradual migration path

NEW CAPABILITIES:
✅ Futures momentum strategies (impossible before)
✅ Multi-signal strategies (impossible before)
✅ Equity/ETF backtesting (impossible before)
✅ Custom risk models and optimizers
✅ Demonstrates library's modular architecture

TESTING:
- XXX new tests for Backtest class
- All baseline tests pass (futures carry matches MinimalBacktest)
- New capability tests pass (momentum, multi-signal, DataFrame)
- Integration tests pass
- Notebook 07 migrated and verified

See docs/GENERIC_BACKTEST_MIGRATION_PLAN.md for full details.
EOF
)"

git push -u origin claude/verify-integration-notebook-011CV66ZrAdcoGXccRY1Up3E
```

**Checkpoint**: Update progress tracker - step 5.2 complete

---

## Success Criteria Checklist

**Must Have:**
- [ ] Backtest class created and tested
- [ ] Backwards compatible with MinimalBacktest use cases
- [ ] Can use any signal type (not just CarrySignal)
- [ ] Can use multiple signals + combiner
- [ ] At least 1 notebook migrated successfully
- [ ] All existing tests still pass

**Should Have:**
- [ ] run_from_dataframe() supports equity strategies
- [ ] Documentation updated
- [ ] Examples showing different configurations
- [ ] Deprecation warning on MinimalBacktest

**Nice to Have:**
- [ ] Multiple notebooks migrated
- [ ] User migration guide
- [ ] Performance comparison

---

## Emergency Recovery

If session gets cut off, resume with:

1. Check `docs/GENERIC_BACKTEST_PROGRESS.md` for last checkpoint
2. See which step was incomplete
3. Run tests to verify current state:
   ```bash
   pytest tests/unit/backtest/test_backtest.py -v
   ```
4. Continue from next step in plan

**Key Files to Check:**
- `Backtest/Backtest.py` - Is it created? Complete?
- `tests/unit/backtest/test_backtest.py` - How many tests pass?
- `docs/GENERIC_BACKTEST_PROGRESS.md` - What's the status?

---

## Notes and Observations

[Space for documenting issues, decisions, or important findings during implementation]
