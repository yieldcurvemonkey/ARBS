# Backtest Unification - Clean VM Setup & Parallel Task Execution

## Part 1: Clean VM Environment Setup

### Prerequisites
- Fresh VM with Python 3.11+
- Git installed
- Internet connection for package downloads

### Step 1: Initial Environment Setup

```bash
# 1.1 Verify Python version
python --version
# Expected: Python 3.11.x or 3.12.x

# 1.2 Verify pip is available
pip --version
python -m pip --version

# 1.3 Install virtualenv if not present (optional but recommended)
pip install virtualenv
```

### Step 2: Clone Repository and Create Branch

```bash
# 2.1 Clone the repository
cd ~
git clone https://github.com/pfin/ARBS.git
cd ARBS

# 2.2 Verify you're on the correct starting branch
git status
# Should show: On branch main (or master)

# 2.3 Create new working branch for backtest unification
# Branch name format: claude/backtest-unification-<session-id>
SESSION_ID=$(date +%s)
BRANCH_NAME="claude/backtest-unification-${SESSION_ID}"
git checkout -b "$BRANCH_NAME"

# 2.4 Verify branch creation
git branch
# Should show your new branch with asterisk: * claude/backtest-unification-...

# 2.5 Set up tracking (will use later after first commit)
echo "Branch name: $BRANCH_NAME" > .branch-name
```

### Step 3: Install Dependencies

```bash
# 3.1 Create virtual environment (recommended)
python -m venv venv

# 3.2 Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# 3.3 Upgrade pip to latest
pip install --upgrade pip

# 3.4 Install all dependencies
# Note: This may take 5-10 minutes
pip install -r requirements.txt

# 3.5 Handle known issues
# If yfinance fails (multitasking build error), that's OK - continue
# Core functionality doesn't require yfinance

# 3.6 Verify core dependencies installed
python -c "import numpy, scipy, polars, QuantLib, rateslib; print('✓ Core dependencies OK')"
python -c "import pytest; print('✓ Testing framework OK')"
```

### Step 4: Verify Test Suite

```bash
# 4.1 Run full test suite to establish baseline
python -m pytest tests/unit/ -v --tb=short 2>&1 | tee test-baseline.log

# 4.2 Check test count
# Expected: 1038+ passing tests (99.2% pass rate)
grep -E "passed|failed" test-baseline.log | tail -1

# 4.3 If tests fail, check for missing dependencies
python -m pytest tests/unit/ -v --tb=short -x
# -x stops at first failure for easier debugging

# 4.4 Save baseline for comparison later
cp test-baseline.log test-baseline-before-changes.log
```

### Step 5: Understand Current Architecture

```bash
# 5.1 Read key documentation
cat CLAUDE.md | head -50
# Pay attention to Rule #2: NEVER create new systems, ALWAYS extend

# 5.2 Review backtest systems
ls -la BT/
ls -la Backtest/

# 5.3 Review existing integration plan
cat docs/design/BACKTEST_UNIFICATION_PLAN.md | less

# 5.4 Review codebase analysis
cat CODEBASE_ANALYSIS.md | less
```

### Step 6: Set Up Development Environment

```bash
# 6.1 Configure git (if not already done)
git config user.name "Your Name"
git config user.email "your.email@example.com"

# 6.2 Verify pre-commit hooks work (if any)
git status

# 6.3 Create working directory for notes
mkdir -p work-notes
```

---

## Part 2: Backtest Unification - Orthogonal Task Breakdown

### Critical Context

**Goal**: Enable Backtest class to support BOTH signal-driven (existing) AND query-driven workflows

**Rule #2 Compliance**:
- ❌ DO NOT create UnifiedBacktest class
- ✅ EXTEND existing Backtest/Backtest.py
- ❌ DO NOT create UnifiedPortfolio class
- ✅ EXTEND existing Asset/GrinoldKahnPortfolio.py
- ✅ Create ONLY thin bridge adapters

**Architecture**:
- `BT/` = Query/event-driven for derivatives (swaps, futures, bonds)
- `Backtest/` = Signal-driven for equities/portfolios (Grinold-Kahn)
- Goal: Let Backtest/ support query workflows too

---

### Task 1: QuerySignal Bridge Adapter (ORTHOGONAL)

**What**: Create adapter that converts BaseQuery to BaseSignal interface

**Why**: Enables derivative queries to work as signals in portfolio optimization

**Files to Create**:
- `Signals/Bridges/QuerySignal.py`
- `Signals/Bridges/__init__.py`
- `tests/unit/signals/bridges/test_query_signal.py`
- `tests/unit/signals/bridges/__init__.py`

**Files to Read** (for context, DO NOT MODIFY):
- `Signals/Base/BaseSignal.py` - Understand signal interface
- `Query/Base/BaseQuery.py` - Understand query interface
- `BT/query_engine.py` - How queries are executed
- `MDP/MarketDataProvider.py` - MDP interface

**Implementation Spec**:

```python
# Signals/Bridges/QuerySignal.py
# ABOUTME: Adapter converting BaseQuery to BaseSignal interface
# ABOUTME: Enables derivative queries to generate signals for portfolio optimization

"""
QuerySignal - Query to Signal Bridge

Adapts BaseQuery (derivative pricing) to BaseSignal (alpha generation) interface.
Enables using derivative queries as signals in Grinold-Kahn portfolio optimization.

Example:
    >>> from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    >>> from Query.IRSwaps.IRSwapValue import IRSwapValue
    >>> from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    >>>
    >>> # Create query that computes swap carry
    >>> carry_query = IRSwapQuery(
    ...     value=IRSwapValue.CARRY,
    ...     tenor="5Y",
    ...     curve="USD-SOFR-1D"
    ... )
    >>>
    >>> # Wrap as signal
    >>> carry_signal = QuerySignal(
    ...     query=carry_query,
    ...     mdp=IRSwapsMDP(),
    ...     value_field='carry'  # Extract this field from query result
    ... )
    >>>
    >>> # Use in backtest like any other signal
    >>> backtest = Backtest(signals=carry_signal)
"""

from typing import Dict, Any, Callable, Optional, List
import polars as pl
import numpy as np
from datetime import date

from Signals.Base.BaseSignal import BaseSignal
from Query.Base.BaseQuery import BaseQuery
from MDP.MarketDataProvider import MarketDataProvider


class QuerySignal(BaseSignal):
    """
    Adapter that executes queries via MDP and extracts signal values.

    Workflow:
    1. Execute query via MDP at as_of date
    2. Extract value from query result using value_field
    3. Standardize to z-scores (if requested)
    4. Return as signal compatible with AlphaGenerator
    """

    def __init__(
        self,
        query: BaseQuery,
        mdp: MarketDataProvider,
        value_field: str = 'value',
        standardize: bool = True,
        cache_results: bool = True
    ):
        """
        Initialize QuerySignal adapter.

        Args:
            query: BaseQuery instance to execute
            mdp: MarketDataProvider for market data
            value_field: Field to extract from query result (e.g., 'carry', 'rate', 'spread')
            standardize: Whether to z-score the values
            cache_results: Whether to cache MDP calls
        """
        self.query = query
        self.mdp = mdp
        self.value_field = value_field
        self.standardize = standardize
        self.cache_results = cache_results
        self._cache: Dict[date, Dict[str, float]] = {}

    def generate(
        self,
        tickers: List[str],
        returns: pl.DataFrame,
        as_of: date
    ) -> pl.DataFrame:
        """
        Generate signals by executing queries via MDP.

        Args:
            tickers: List of asset identifiers
            returns: Returns DataFrame (may not be used for query-based signals)
            as_of: Date for signal generation

        Returns:
            DataFrame with columns: ['ticker', 'signal']
            Signals are z-scores if standardize=True, raw values otherwise
        """
        # TODO: Implement query execution via MDP
        # TODO: Extract value_field from results
        # TODO: Standardize if requested
        # TODO: Return as DataFrame
        raise NotImplementedError("QuerySignal.generate() - Implement in Task 1")


# Signals/Bridges/__init__.py
"""Bridge adapters between different system abstractions."""

from Signals.Bridges.QuerySignal import QuerySignal

__all__ = ['QuerySignal']
```

**Test Spec**:

```python
# tests/unit/signals/bridges/test_query_signal.py

"""
Tests for QuerySignal bridge adapter.

Test coverage:
1. Construction and validation
2. Query execution via MDP
3. Value extraction
4. Standardization
5. Caching behavior
6. Integration with AlphaGenerator
"""

import pytest
import polars as pl
import numpy as np
from datetime import date

from Signals.Bridges.QuerySignal import QuerySignal
# ... additional imports


class TestQuerySignalConstruction:
    """Test QuerySignal initialization and validation."""

    def test_construction_with_minimal_args(self):
        """QuerySignal constructs with query and MDP."""
        # TODO: Create mock query and MDP
        # TODO: Construct QuerySignal
        # TODO: Verify attributes set correctly
        pass

    def test_construction_with_all_args(self):
        """QuerySignal accepts all optional parameters."""
        pass

    def test_invalid_value_field_raises_error(self):
        """Invalid value_field raises descriptive error."""
        pass


class TestQueryExecution:
    """Test query execution via MDP."""

    def test_executes_query_via_mdp(self):
        """QuerySignal executes query through MDP.get_pricer()."""
        pass

    def test_extracts_correct_value_field(self):
        """Extracts specified field from query result."""
        pass

    def test_handles_multiple_tickers(self):
        """Generates signals for multiple assets."""
        pass


class TestStandardization:
    """Test signal standardization."""

    def test_standardize_true_returns_z_scores(self):
        """When standardize=True, returns z-scores."""
        pass

    def test_standardize_false_returns_raw_values(self):
        """When standardize=False, returns raw query values."""
        pass


class TestCaching:
    """Test MDP result caching."""

    def test_caching_enabled_avoids_duplicate_calls(self):
        """With cache_results=True, doesn't repeat MDP calls."""
        pass

    def test_caching_disabled_calls_every_time(self):
        """With cache_results=False, calls MDP each time."""
        pass


class TestIntegration:
    """Test integration with broader system."""

    def test_compatible_with_alpha_generator(self):
        """QuerySignal output works with AlphaGenerator."""
        pass

    def test_compatible_with_signal_combiner(self):
        """Can combine QuerySignal with other signals."""
        pass
```

**Success Criteria**:
- ✅ QuerySignal class compiles and imports
- ✅ All unit tests pass (target: 15+ tests)
- ✅ Can execute query via MDP
- ✅ Extracts value correctly
- ✅ Standardization works
- ✅ Integration test with AlphaGenerator passes
- ✅ No modifications to existing files (only new files created)

**Estimated Time**: 45-60 minutes

---

### Task 2: SignalQuery Bridge Adapter (ORTHOGONAL)

**What**: Create adapter that converts BaseSignal to BaseQuery interface

**Why**: Enables signals to drive query-based execution in BT/

**Files to Create**:
- `Query/Bridges/SignalQuery.py`
- `Query/Bridges/__init__.py`
- `tests/unit/query/bridges/test_signal_query.py`
- `tests/unit/query/bridges/__init__.py`

**Files to Read** (for context, DO NOT MODIFY):
- `Query/Base/BaseQuery.py` - Understand query interface
- `Signals/Base/BaseSignal.py` - Understand signal interface
- `BT/query_portfolio.py` - How query positions work

**Implementation Spec**:

```python
# Query/Bridges/SignalQuery.py
# ABOUTME: Adapter converting BaseSignal to BaseQuery interface
# ABOUTME: Enables signals to drive query-based position execution

"""
SignalQuery - Signal to Query Bridge

Adapts BaseSignal (alpha generation) to BaseQuery (position execution) interface.
Enables using signals to drive query-based execution in BT/.

Example:
    >>> from Signals.Futures.CarrySignal import CarrySignal
    >>> from Query.Bridges.SignalQuery import SignalQuery
    >>>
    >>> # Create signal
    >>> carry_signal = CarrySignal()
    >>>
    >>> # Wrap as query for BT/ execution
    >>> signal_query = SignalQuery(
    ...     signal=carry_signal,
    ...     tickers=['SFRZ4', 'SFRH5'],
    ...     position_builder=lambda signal_values: build_positions(signal_values)
    ... )
    >>>
    >>> # Use in QueryDrivenBacktest
    >>> from BT.query_engine import QueryDrivenBacktest
    >>> backtest = QueryDrivenBacktest(
    ...     mdp=mdp,
    ...     queries=[signal_query]  # Signal driving query execution
    ... )
"""

from typing import Dict, Any, Callable, List, Tuple
import numpy as np
from datetime import date

from Query.Base.BaseQuery import BaseQuery
from Signals.Base.BaseSignal import BaseSignal


class SignalQuery(BaseQuery):
    """
    Adapter that generates signals and converts to query positions.

    Workflow:
    1. Generate signal values using BaseSignal
    2. Convert signal values to position sizes
    3. Package as query result for BT/ execution
    """

    def __init__(
        self,
        signal: BaseSignal,
        tickers: List[str],
        position_builder: Callable[[Dict[str, float]], List[Tuple[str, float]]],
        label: str = None
    ):
        """
        Initialize SignalQuery adapter.

        Args:
            signal: BaseSignal instance
            tickers: Assets to generate signals for
            position_builder: Function converting signal values to positions
            label: Human-readable label for query
        """
        self.signal = signal
        self.tickers = tickers
        self.position_builder = position_builder
        self.label = label or f"SignalQuery({signal.__class__.__name__})"

    def resolve_package(self, pricer_or_curve):
        """
        Resolve to package of positions.

        This is called by QueryDrivenBacktest to build positions.
        """
        # TODO: Generate signals for tickers
        # TODO: Convert to positions using position_builder
        # TODO: Return package compatible with BT/
        raise NotImplementedError("SignalQuery.resolve_package() - Implement in Task 2")

    def build_mdp_request(self, now: date):
        """Build MDP request (may not be needed for pure signal queries)."""
        # TODO: Decide if signal queries need MDP access
        # TODO: May return None if signals don't need market data
        raise NotImplementedError("SignalQuery.build_mdp_request() - Implement in Task 2")


# Query/Bridges/__init__.py
"""Bridge adapters between different system abstractions."""

from Query.Bridges.SignalQuery import SignalQuery

__all__ = ['SignalQuery']
```

**Test Spec**:

```python
# tests/unit/query/bridges/test_signal_query.py

"""
Tests for SignalQuery bridge adapter.

Test coverage:
1. Construction
2. Signal generation
3. Position building
4. Package resolution
5. Integration with BT/
"""

import pytest
import numpy as np
from datetime import date

from Query.Bridges.SignalQuery import SignalQuery
# ... additional imports


class TestSignalQueryConstruction:
    """Test SignalQuery initialization."""

    def test_construction_with_minimal_args(self):
        """SignalQuery constructs with signal and tickers."""
        pass

    def test_custom_position_builder(self):
        """Accepts custom position builder function."""
        pass


class TestSignalGeneration:
    """Test signal generation."""

    def test_generates_signals_for_tickers(self):
        """Generates signals for specified tickers."""
        pass

    def test_uses_provided_signal_instance(self):
        """Uses the provided BaseSignal instance."""
        pass


class TestPositionBuilding:
    """Test position building."""

    def test_converts_signals_to_positions(self):
        """position_builder converts signal values to positions."""
        pass

    def test_handles_long_only_constraints(self):
        """Respects long-only constraint if specified."""
        pass


class TestPackageResolution:
    """Test package resolution for BT/."""

    def test_resolve_package_returns_valid_package(self):
        """resolve_package returns package compatible with BT/."""
        pass

    def test_package_has_correct_structure(self):
        """Package has instruments and weights."""
        pass


class TestIntegration:
    """Test integration with BT/."""

    def test_compatible_with_query_driven_backtest(self):
        """SignalQuery works with QueryDrivenBacktest."""
        pass
```

**Success Criteria**:
- ✅ SignalQuery class compiles and imports
- ✅ All unit tests pass (target: 12+ tests)
- ✅ Generates signals correctly
- ✅ Converts signals to positions
- ✅ Compatible with BT/QueryDrivenBacktest
- ✅ No modifications to existing files

**Estimated Time**: 45-60 minutes

---

### Task 3: Extend Backtest Class - Query Workflow Support (ORTHOGONAL)

**What**: EXTEND existing Backtest/Backtest.py to support query-driven workflow

**Why**: Unify both workflows in single class (Rule #2 compliance)

**Files to Modify**:
- `Backtest/Backtest.py` (EXTEND, don't rewrite)

**Files to Create**:
- `tests/unit/backtest/test_backtest_query_workflow.py`

**Files to Read** (for context):
- `BT/query_engine.py` - Query workflow implementation
- `Backtest/Backtest.py` - Current signal workflow
- `MDP/MarketDataProvider.py` - MDP interface

**Implementation Spec**:

```python
# Modifications to Backtest/Backtest.py

# ADD these imports at the top (after existing imports)
from typing import Optional, Union, List
from Query.Base.BaseQuery import BaseQuery
from MDP.MarketDataProvider import MarketDataProvider
from BT.triggers import Trigger

# EXTEND the __init__ method to accept query parameters
def __init__(
    self,
    # Existing signal-based parameters (keep all of these)
    signals: Union[BaseSignal, List[BaseSignal]] = None,
    signal_combiner: SignalCombiner = None,
    alpha_generator: AlphaGenerator = None,
    risk_model: BaseCovarianceEstimator = None,
    optimizer: BaseOptimizer = None,
    rebalance_frequency: str = 'weekly',

    # ADD: New query-based parameters
    mdp: Optional[MarketDataProvider] = None,
    queries: Optional[List[BaseQuery]] = None,
    triggers: Optional[List[Trigger]] = None,
    adapter: Optional[BaseAdapter] = None,
):
    """
    Initialize generic backtest.

    Supports THREE workflows:
    1. Signal-driven (existing): Provide signals
    2. Query-driven (NEW): Provide mdp + queries
    3. Hybrid (NEW): Provide both signals and queries

    Args:
        signals: Signal(s) for alpha generation (signal workflow)
        mdp: Market data provider (query workflow)
        queries: List of queries to execute (query workflow)
        triggers: Event triggers (query workflow)
        adapter: Data adapter (query workflow)
        ... (keep all existing parameters)
    """
    # ADD: Validate workflow configuration
    self._workflow = self._detect_workflow(signals, mdp, queries)

    # Existing initialization (keep all)
    # ...

    # ADD: Query workflow initialization
    if self._workflow in ('query', 'hybrid'):
        self.mdp = mdp
        self.queries = queries or []
        self.triggers = triggers or []
        self.adapter = adapter
        # TODO: Initialize query-specific components

# ADD: New method to detect workflow
def _detect_workflow(self, signals, mdp, queries) -> str:
    """
    Detect which workflow to use based on parameters.

    Returns:
        'signal': Signal-driven workflow
        'query': Query-driven workflow
        'hybrid': Both workflows
    """
    has_signals = signals is not None
    has_queries = mdp is not None and queries is not None

    if has_signals and has_queries:
        return 'hybrid'
    elif has_queries:
        return 'query'
    elif has_signals:
        return 'signal'
    else:
        raise ValueError("Must provide either signals or (mdp + queries)")

# ADD: New run method for query workflow
def run_from_queries(
    self,
    time_grid: List[date],
    **kwargs
) -> 'BacktestResult':
    """
    Run backtest using query-driven workflow.

    Executes queries via MDP at each time step.
    """
    # TODO: Implement query execution loop
    # TODO: Use BT/query_engine.py as reference
    # TODO: Generate BacktestResult
    raise NotImplementedError("Backtest.run_from_queries() - Implement in Task 3")

# MODIFY: Extend existing run() method to route to correct workflow
def run(self, *args, **kwargs):
    """
    Run backtest using detected workflow.

    Routes to:
    - run_from_dataframe() for signal workflow (existing)
    - run_from_queries() for query workflow (NEW)
    - hybrid execution for both (NEW)
    """
    if self._workflow == 'signal':
        return self.run_from_dataframe(*args, **kwargs)  # Existing
    elif self._workflow == 'query':
        return self.run_from_queries(*args, **kwargs)  # NEW
    elif self._workflow == 'hybrid':
        return self._run_hybrid(*args, **kwargs)  # NEW
    else:
        raise ValueError(f"Unknown workflow: {self._workflow}")
```

**Test Spec**:

```python
# tests/unit/backtest/test_backtest_query_workflow.py

"""
Tests for Backtest query workflow support.

Tests ONLY the new query workflow functionality.
Existing signal workflow tests remain in test_backtest.py.
"""

class TestWorkflowDetection:
    """Test workflow detection logic."""

    def test_signal_only_detects_signal_workflow(self):
        """When only signals provided, detects signal workflow."""
        pass

    def test_query_only_detects_query_workflow(self):
        """When mdp + queries provided, detects query workflow."""
        pass

    def test_both_detects_hybrid_workflow(self):
        """When both provided, detects hybrid workflow."""
        pass

    def test_neither_raises_error(self):
        """When neither provided, raises ValueError."""
        pass


class TestQueryWorkflow:
    """Test query-driven workflow execution."""

    def test_executes_queries_via_mdp(self):
        """Query workflow executes queries through MDP."""
        pass

    def test_generates_positions_from_queries(self):
        """Converts query results to positions."""
        pass

    def test_tracks_mtm_correctly(self):
        """MTM calculation matches BT/query_engine."""
        pass


class TestHybridWorkflow:
    """Test hybrid workflow (signals + queries)."""

    def test_combines_signal_and_query_positions(self):
        """Hybrid workflow combines both position types."""
        pass

    def test_unified_tear_sheet(self):
        """TearSheet shows unified metrics."""
        pass
```

**Success Criteria**:
- ✅ Backtest class accepts query parameters
- ✅ Workflow detection works correctly
- ✅ Query workflow executes via MDP
- ✅ Results match BT/QueryDrivenBacktest
- ✅ All existing signal workflow tests still pass
- ✅ New query workflow tests pass (target: 10+ tests)
- ✅ No breaking changes to existing API

**Estimated Time**: 60-90 minutes

---

### Task 4: Extend GrinoldKahnPortfolio - Query Position Support (ORTHOGONAL)

**What**: EXTEND Asset/GrinoldKahnPortfolio.py to track query-based positions

**Why**: Support both signal positions and query positions in single portfolio

**Files to Modify**:
- `Asset/GrinoldKahnPortfolio.py` (EXTEND, don't rewrite)

**Files to Create**:
- `tests/unit/asset/test_grinold_kahn_portfolio_queries.py`

**Files to Read**:
- `BT/query_portfolio.py` - How query positions work
- `Asset/GrinoldKahnPortfolio.py` - Current implementation

**Implementation Spec**:

```python
# Modifications to Asset/GrinoldKahnPortfolio.py

# ADD: Import for query positions
from typing import List, Optional, Union
from BT.query_portfolio import ResolvedQueryPosition

# EXTEND __init__ to support query positions
def __init__(
    self,
    identifier: str,
    # Existing signal parameters
    signals: List[BaseSignal] = None,
    alpha_generator: AlphaGenerator = None,
    risk_model: BaseCovarianceEstimator = None,
    optimizer: BaseOptimizer = None,
    rebalance_frequency: str = 'weekly',

    # ADD: Query position support
    track_query_positions: bool = False,
):
    """
    Initialize Grinold-Kahn portfolio.

    Now supports TWO position types:
    1. Signal-based positions (existing)
    2. Query-based positions (NEW)
    """
    # Existing initialization
    # ...

    # ADD: Query position tracking
    self.track_query_positions = track_query_positions
    if track_query_positions:
        self._query_positions: List[ResolvedQueryPosition] = []

# ADD: Method to add query position
def add_query_position(
    self,
    position: ResolvedQueryPosition,
    as_of: date
) -> None:
    """
    Add a query-based position to portfolio.

    Args:
        position: Resolved query position from BT/
        as_of: Date position was opened
    """
    if not self.track_query_positions:
        raise ValueError("Portfolio not configured for query positions")

    # TODO: Add position to tracking
    # TODO: Update internal state
    raise NotImplementedError("GrinoldKahnPortfolio.add_query_position() - Task 4")

# EXTEND: calculate_return to handle both position types
def calculate_return(
    self,
    prev_state: Dict[str, Any],
    curr_state: Dict[str, Any],
    as_of: date
) -> float:
    """
    Calculate portfolio return.

    Now handles:
    1. Signal-based positions (existing calculation)
    2. Query-based positions (NEW - MTM via MDP)
    3. Combined (both types)
    """
    # Existing signal-based calculation
    signal_return = self._calculate_signal_return(prev_state, curr_state)

    # ADD: Query-based calculation
    if self.track_query_positions and len(self._query_positions) > 0:
        query_return = self._calculate_query_return(prev_state, curr_state, as_of)
        # Combine returns (weighted by position sizes)
        return self._combine_returns(signal_return, query_return)

    return signal_return

# ADD: Helper for query return calculation
def _calculate_query_return(
    self,
    prev_state: Dict[str, Any],
    curr_state: Dict[str, Any],
    as_of: date
) -> float:
    """Calculate return from query positions via MTM."""
    # TODO: Implement MTM calculation for query positions
    # TODO: Use MDP to get current valuations
    # TODO: Return percentage change
    raise NotImplementedError("GrinoldKahnPortfolio._calculate_query_return() - Task 4")
```

**Test Spec**:

```python
# tests/unit/asset/test_grinold_kahn_portfolio_queries.py

"""
Tests for GrinoldKahnPortfolio query position support.

Tests ONLY the new query position functionality.
Existing signal position tests remain in test_grinold_kahn_portfolio.py.
"""

class TestQueryPositionTracking:
    """Test query position tracking."""

    def test_add_query_position_stores_correctly(self):
        """add_query_position stores position."""
        pass

    def test_query_positions_listed_separately(self):
        """Query positions tracked separately from signal positions."""
        pass

    def test_disabled_tracking_raises_error(self):
        """Adding query position when tracking disabled raises error."""
        pass


class TestReturnCalculation:
    """Test return calculation with query positions."""

    def test_query_only_returns_correct_mtm(self):
        """Return calculation for query-only portfolio."""
        pass

    def test_signal_only_unchanged(self):
        """Signal-only behavior unchanged."""
        pass

    def test_combined_weights_correctly(self):
        """Combined signal + query positions weighted correctly."""
        pass


class TestPositionReporting:
    """Test position reporting."""

    def test_get_positions_includes_both_types(self):
        """get_positions includes both signal and query positions."""
        pass

    def test_position_attribution_separated(self):
        """Can attribute returns to signal vs query positions."""
        pass
```

**Success Criteria**:
- ✅ GrinoldKahnPortfolio accepts query positions
- ✅ Query positions tracked separately
- ✅ Return calculation handles both types
- ✅ All existing signal tests still pass
- ✅ New query position tests pass (target: 8+ tests)
- ✅ No breaking changes to existing API

**Estimated Time**: 45-60 minutes

---

### Task 5: Integration Tests & Documentation (ORTHOGONAL)

**What**: Create end-to-end integration tests and update documentation

**Why**: Verify all components work together, document unified interface

**Files to Create**:
- `tests/integration/test_backtest_unification.py`
- `examples/backtest_query_workflow.py`
- `examples/backtest_hybrid_workflow.py`
- `docs/BACKTEST_UNIFIED_API.md`

**Files to Update**:
- `README.md` (add unified workflow examples)
- `Backtest/__init__.py` (update docstring)

**Implementation Spec**:

```python
# tests/integration/test_backtest_unification.py

"""
Integration tests for unified backtest system.

Tests that all components work together:
- QuerySignal bridge
- SignalQuery bridge
- Extended Backtest class
- Extended GrinoldKahnPortfolio
"""

class TestEndToEnd:
    """End-to-end workflow tests."""

    def test_query_workflow_produces_results(self):
        """Query workflow executes end-to-end and produces results."""
        # Use mock MDP
        # Execute simple query
        # Verify results structure
        pass

    def test_signal_workflow_still_works(self):
        """Existing signal workflow unchanged."""
        # Run signal-based backtest
        # Verify matches baseline
        pass

    def test_hybrid_workflow_combines_both(self):
        """Hybrid workflow combines signal and query positions."""
        # Mix signals and queries
        # Verify both execute
        # Verify results combined correctly
        pass


class TestBridgeAdapters:
    """Test bridge adapters in integrated context."""

    def test_query_signal_in_backtest(self):
        """QuerySignal works in Backtest."""
        pass

    def test_signal_query_in_bt(self):
        """SignalQuery works in BT/QueryDrivenBacktest."""
        pass

    def test_roundtrip_signal_query_signal(self):
        """Can convert signal → query → signal."""
        pass


class TestPerformance:
    """Performance and regression tests."""

    def test_query_workflow_performance_acceptable(self):
        """Query workflow completes in reasonable time."""
        # Target: <5s for 100 steps
        pass

    def test_no_memory_leaks(self):
        """Extended portfolio doesn't leak memory."""
        pass

    def test_results_deterministic(self):
        """Repeated runs produce identical results."""
        pass
```

```python
# examples/backtest_query_workflow.py

"""
Example: Using query workflow in unified Backtest.

Demonstrates:
- Executing derivative queries via MDP
- Position tracking
- Performance analysis
"""

from datetime import date
from Backtest.Backtest import Backtest
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue
from BT.data_handler import TimeGrid


def main():
    # Create time grid (monthly steps)
    dates = [date(2024, m, 1) for m in range(1, 13)]
    grid = TimeGrid(dates)

    # Create MDP
    mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

    # Create queries
    queries = [
        IRSwapQuery(
            value=IRSwapValue.CARRY,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000}
        )
    ]

    # Create unified backtest with query workflow
    backtest = Backtest(
        mdp=mdp,
        queries=queries
    )

    # Run
    result = backtest.run(time_grid=grid)

    # Analyze
    print(f"Total Return: {result.total_return:.2%}")
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"Max Drawdown: {result.max_drawdown:.2%}")


if __name__ == "__main__":
    main()
```

```markdown
# docs/BACKTEST_UNIFIED_API.md

# Unified Backtest API

## Overview

The `Backtest` class now supports THREE workflows in a single interface:

1. **Signal-driven** (existing): Portfolio optimization with signals
2. **Query-driven** (NEW): Derivative execution via MDP
3. **Hybrid** (NEW): Combination of both

## Signal-Driven Workflow

Use when: Optimizing equity/portfolio strategies with signals

... (document existing API)

## Query-Driven Workflow

Use when: Executing derivative strategies via MDP

... (document new query API)

## Hybrid Workflow

Use when: Combining signals and queries

... (document hybrid usage)
```

**Success Criteria**:
- ✅ Integration tests pass (target: 8+ tests)
- ✅ Examples run successfully
- ✅ Documentation complete and accurate
- ✅ README updated
- ✅ API clear and consistent

**Estimated Time**: 45-60 minutes

---

## Part 3: Parallel Execution Guide

### How to Run Tasks in Parallel

Tasks 1, 2, 4, and 5 are ORTHOGONAL and can run in parallel:

**Parallel Group A** (No dependencies):
- Task 1: QuerySignal bridge
- Task 2: SignalQuery bridge
- Task 5: Integration tests (can stub bridges initially)

**Sequential After Group A**:
- Task 3: Extend Backtest (needs bridges from Tasks 1+2)
- Task 4: Extend GrinoldKahnPortfolio (needs bridges from Tasks 1+2)

### Verification After Each Task

```bash
# After completing a task, verify:

# 1. Run new tests
python -m pytest tests/unit/<task-path>/ -v

# 2. Run ALL tests to ensure no breakage
python -m pytest tests/unit/ -v --tb=short

# 3. Check test count increased
# Should be: 1038 + <new tests from task>

# 4. Commit changes
git add <modified-files>
git commit -m "feat: <task-description>"

# 5. Push to remote
BRANCH_NAME=$(cat .branch-name)
git push -u origin "$BRANCH_NAME"
```

### Final Integration

```bash
# After ALL tasks complete:

# 1. Run full test suite
python -m pytest tests/ -v --cov=. --cov-report=term-missing

# 2. Run integration tests specifically
python -m pytest tests/integration/test_backtest_unification.py -v

# 3. Run examples
python examples/backtest_query_workflow.py
python examples/backtest_hybrid_workflow.py

# 4. Verify backward compatibility
python -m pytest tests/unit/backtest/ -v  # All existing tests pass
python -m pytest tests/unit/asset/ -v      # All existing tests pass

# 5. Final commit
git add -A
git commit -m "feat: Complete backtest unification

- Extended Backtest to support query workflow
- Extended GrinoldKahnPortfolio for query positions
- Created QuerySignal and SignalQuery bridge adapters
- Added integration tests and examples
- Updated documentation

Tests: X passing (was 1038)
Backward compatible: Yes
Rule #2 compliant: Yes (extended existing, no new systems)"

# 6. Push
BRANCH_NAME=$(cat .branch-name)
git push -u origin "$BRANCH_NAME"
```

---

## Success Metrics

### Code Quality
- ✅ All tests pass (target: 1100+ total)
- ✅ No regressions in existing tests
- ✅ Code coverage >95% for new code
- ✅ All new files have ABOUTME headers
- ✅ No "TODO" comments in production code

### Architecture
- ✅ Rule #2 compliant (extended, not created new)
- ✅ Backward compatible
- ✅ Clean separation of concerns
- ✅ Orthogonal task execution verified

### Documentation
- ✅ API docs complete
- ✅ Examples work
- ✅ README updated
- ✅ Migration guide clear

### Performance
- ✅ Query workflow <5s for 100 steps
- ✅ No memory leaks
- ✅ Results deterministic

---

## Troubleshooting

### If Task Fails

1. **Read error carefully** - error messages contain solutions
2. **Check dependencies** - did previous task complete?
3. **Verify files exist** - did you create all required files?
4. **Run single test** - isolate the failure
5. **Check CLAUDE.md** - are you following Rule #2?

### If Tests Won't Run

```bash
# Check imports work
python -c "from Signals.Bridges.QuerySignal import QuerySignal; print('OK')"

# Check pytest finds tests
python -m pytest --collect-only tests/unit/signals/bridges/

# Run with verbose output
python -m pytest tests/unit/signals/bridges/ -vvv
```

### If Installation Fails

```bash
# Check Python version
python --version  # Must be 3.11+

# Try installing one package at a time
pip install numpy
pip install scipy
pip install polars
# ... etc

# Skip yfinance if it fails (non-critical)
```

---

## Questions Before Starting?

1. Is the VM environment clean and ready?
2. Have you read CLAUDE.md Rule #2?
3. Do you understand the orthogonal task structure?
4. Are you clear on which files to EXTEND vs CREATE?
5. Ready to execute in parallel?

**If yes to all → BEGIN!**

---

*Created: 2025-11-14*
*For: Backtest Unification Phase 1*
*Estimated Total Time: 4-5 hours (with parallel execution: 2-3 hours)*
