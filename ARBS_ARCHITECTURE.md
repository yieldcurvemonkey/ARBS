# ARBS Architecture & Technical Reference

This document provides detailed ARBS architecture documentation. For universal development rules and project philosophy, see CLAUDE.md.

**When to read this**:
- Setting up ARBS development environment
- Understanding the three-layer architecture
- Adding new features (curves, products, backends)
- Debugging architecture-related issues
- Looking up specific commands or troubleshooting

**Keep this updated when**:
- Architecture patterns change
- New backends added
- New product types added
- Setup process changes

---

## Table of Contents

1. [Repository Overview](#repository-overview)
2. [Three-Layer Architecture](#three-layer-architecture)
3. [Data Flow](#data-flow-per-timestep)
4. [Key Design Patterns](#key-design-patterns)
5. [Backend Systems](#backend-systems)
6. [Code Conventions](#code-conventions)
7. [Environment Setup](#environment-setup)
8. [Running Tests](#running-tests)
9. [Development Workflow](#development-workflow)
10. [Common Development Tasks](#common-development-tasks)
11. [Troubleshooting](#troubleshooting)
12. [Essential Files Reference](#essential-files-reference)
13. [Extension Points](#extension-points)

---

## Repository Overview

ARBS (Awesome Rates Backtesting System) is a modular research codebase for building yield curves, pricing interest rate derivatives, and running event- or query-driven backtests. The architecture follows an **adapter pattern** where the backtester is **product-agnostic** while product-specific logic lives behind adapters.

**Key Characteristics**:
- **Modular Design**: Three-layer separation enabling component reuse
- **Product-Agnostic Core**: Backtesting engine works with any instrument via adapters
- **Dual Backtesting Modes**: Query-driven (product-neutral) and event-driven (instrument-specific)
- **Multi-Backend Support**: QuantLib and RatesLib for curve building and valuation
- **Persistent Caching**: ZODB-based infrastructure for large-scale historical runs

**Current Status**:
- **Test Coverage**: 1214 tests passing
- **Python Version**: 3.12+ (tested with 3.12.9)
- **Key Dependencies**: QuantLib 1.39, rateslib 2.1.1, ZODB 6.0.1

---

## Three-Layer Architecture

### 1. Backtesting Layer (`BT/`)

The core execution engine for both query-driven and event-driven workflows:

#### `QueryDrivenBacktest`
- **Purpose**: Product-agnostic backtester that works with `BaseQuery` objects
- **Primary Usage**: Research and analysis workflows
- **Key Feature**: Operates on abstract query definitions independent of instrument type
- **Supports**: Query arithmetic (e.g., fly spreads: `q_2y + q_5y - 2*q_3y`)

#### `EventDrivenBacktest`
- **Purpose**: General engine for concrete instruments with orders/hedging
- **Use Case**: When explicit order flow and hedging decisions are needed
- **Responsibilities**: Order lifecycle management and hedging execution
- **Level**: Operates at instrument level (IRS, bonds, futures, etc.)

#### Common Responsibilities
Both backtesting engines handle:
- Portfolio management and position tracking
- P&L history accumulation and reporting
- Strategy execution via triggers and actions
- Timeline stepping and event processing

### 2. Query/Adapter Layer (`Query/`)

The abstraction layer bridging high-level query definitions to concrete valuations:

#### `BaseQuery`
Abstract interface defining what to value:
- **Structure**: Definition of instrument composition (OUTRIGHT, CURVE, FLY)
- **Value Metrics**: What to compute (NPV, PV01/BPV, RATE)
- **Implementation**: Frozen dataclass for hashability and use in portfolios

#### Product Adapters
Map queries to concrete structures and value functions:
- **Structure Map**: Converts abstract structures to instrument packages
- **Value Map**: Implements metric calculations
- **Current Products**:
  - `Query/IRSwaps/` - Interest Rate Swaps
  - `Query/FixedRateBonds/` - Fixed rate bonds
- **Extensibility**: Framework supports addition of new products

#### Adapter Registry
Located at `Query/Base/product_adapter.py`:
- Central registration of product-specific adapters
- Runtime dispatch based on query type

### 3. Market Data Layer (`MDP/`)

Encapsulates all market data sourcing and curve construction:

#### `MarketDataProvider`
Abstract interface with core method:
- **Method**: `get_pricer(request) -> pricer_or_curve`
- **Returns**: Consistent interface regardless of source

#### Data Sources
- **CME_NY_EOD**: End-of-day CME data via QuantLib
- **SDR_INTRADAY**: SwapData Repository intraday data via RatesLib
- **GSQUANT**: Goldman Sachs Quant stubs via RatesLib
- **Extensibility**: Framework supports addition of new sources

#### Responsibilities
- Curve building and bootstrapping
- Fixing management and historical lookup
- Calendar and business convention application
- Convention mapping (day counters, compounding, etc.)

---

## Data Flow (Per Timestep)

```
Strategy → Triggers → Orders → Queries
  ↓
Query.build_mdp_request(now) → MDP Request
  ↓
MDP.get_pricer(request) → Pricer/Curve Object
  ↓
Query.resolve_package(pricer) → [Priceables, Weights]
  ↓
Query.build_value_map(pricer, package) → ValueMap
  ↓
ValueMap.apply(value_id) → Computed Metrics (NPV, PV01, RATE)
  ↓
Portfolio Update → MTM History
```

### Detailed Flow Explanation

1. **Strategy Definition**: High-level trading logic defines what to do
2. **Trigger Evaluation**: Conditions checked against market state
3. **Order Generation**: Triggers create orders on specified queries
4. **Query Creation**: Orders reference product-agnostic queries
5. **MDP Request Building**: Query constructs market data request (source, curve, date)
6. **Pricer/Curve Retrieval**: MDP returns bootstrapped curve or pricer
7. **Package Resolution**: Query maps abstract structure to concrete instruments
8. **Value Map Construction**: Adapter builds calculation functions for chosen metrics
9. **Metric Computation**: ValueMap applies functions to pricer/package
10. **Portfolio Update**: Results recorded in position/P&L history

---

## Key Design Patterns

### Product Adapters (Critical to Understand)

The adapter pattern enables product-agnostic backtesting while maintaining clean product-specific logic.

#### Structure Maps (`Query/<Product>/adapter.py`)

Defines how abstract structures map to concrete instruments:

```
OUTRIGHT Structure:
  Abstract: "Price a single point on the curve"
  Concrete: Single IRS with specified notional/BPV

CURVE Structure:
  Abstract: "Create a curve of instruments"
  Concrete: Multiple IRS along tenor spectrum with specified weightings

FLY Structure:
  Abstract: "Create a weighted combination"
  Concrete: [long front, short 2× belly, long back]
  Example: 2Y5Y10Y fly = (2Y × 1) + (5Y × -2) + (10Y × 1)
```

#### Value Maps (`Query/<Product>/adapter.py`)

Implements metric calculations on resolved packages:

```python
# Function signature
def calculate_metric(
    pricer_or_curve,  # QuantLib/RatesLib object
    package,          # Resolved [instruments, weights]
    risk_weights,     # Query-level scalars
    **context         # Additional parameters
) -> float           # Computed value
```

#### Available Metrics
- **RATE**: Par rate (swap coupon for par value)
- **NPV**: Net present value in basis points
- **PV01**/**BPV**: Basis point value (DV01)
- **Carry**: Day-to-day accrual
- **Roll**: Carry plus first-order curve slide

### Curve Definitions (`definitions/IRSwaps.py`)

Centralized metadata for all curves in the system:

```python
CURVE_DEFINITIONS = {
    "USD-SOFR-1D": {
        "reference_rate": "SOFR",
        "day_counter": "Actual360",
        "calendar": "US Government Bond",
        "settlement_days": 0,
        "sdr_upi": "...",  # Trade filtering
        # Additional conventions
    },
    # ... more curves
}
```

**Purpose**: Single source of truth for conventions, eliminating drift between QuantLib and RatesLib backends.

**Always check this file when**:
- Adding new curves
- Debugging convention mismatches
- Validating backend parity

### Query-Driven Pattern (Primary Usage)

```python
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

# Define what to value
q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000}
)

# Query arithmetic is supported
fly = q_2y + q_5y - 2*q_3y  # Creates a fly structure
```

**Key Features**:
- Frozen dataclass for hashability (used as portfolio keys)
- Arithmetic operations create composite queries
- Risk weights can be applied per query
- Supports both OUTRIGHT and composite structures

### Caching Strategy (`Caching/`)

#### Infrastructure
ZODB-based persistent storage for curve builds and valuations

#### Use Cases
- Large time grids (months/years of daily data)
- Repeated curve construction (expensive operation)
- Valuation history archival

#### Cache Keys Include
- Source (CME_NY_EOD, SDR_INTRADAY, etc.)
- Curve name (USD-SOFR-1D, etc.)
- Timestamp (daily close, specific time)
- Recipe hash (curve construction recipe version)

#### Invalidation Strategy
- Bump namespace after recipe changes
- Add recipe hash to cache keys for version tracking
- Manual cache clearing when needed

---

## Backend Systems

### QuantLib Backend (`Query/IRSwaps/backends/quantlib/`)

#### Components
- **`ql_curve_definitions_map.py`**: Maps repository curve names to QuantLib bootstrap configurations
- **`ql_pricer.py`**: IRS valuation functions
  - NPV calculation
  - PV01 sensitivity computation
  - Par rate solving (finding swap coupon for par value)

#### Specifications
- **Data Source**: CME_NY_EOD_LIVE
- **Language**: C++ (via SWIG bindings)
- **Strengths**: Robust, production-tested, wide instrument support

#### Key Conventions
- **Calendar string**: `"US Government Bond"` for USD
- **Day counter**: From CURVE_DEFINITIONS
- **Settlement**: T+2 standard for USD swaps

### RatesLib Backend (`Query/IRSwaps/backends/rateslib/`)

#### Components
- **`rl_curve_definitions_map.py`**: Maps repository curve names to RatesLib curve recipes
- **`RLIRSwapCurve.py`**: Wrapper providing consistent interface to QuantLib
- **`rl_curve_utils/`**: Parallel processing utilities for bulk curve builds

#### Specifications
- **Data Sources**: SDR_INTRADAY, GSQUANT
- **Language**: Python (pure Python implementation)
- **Strengths**: Fast iteration, detailed curve inspection, Python ecosystem

#### Key Conventions
- **Calendar string**: `"nyc"` for USD
- **Curve recipes**: YAML-based specifications for flexible bootstrapping
- **Dual number support**: Automatic differentiation for Greeks

### Backend Parity

#### Tolerance Specification
Par rates should agree within **0.1-1 basis point**

#### Verification Process
1. Build same curve with both backends on same date
2. Compare par rates across tenors
3. If drift > 1bp, check:
   - Day count convention alignment
   - Calendar holiday handling
   - Fixing date conventions
   - Settlement day calculations

#### Common Misalignments
- **QuantLib**: `"US Government Bond"` calendar
- **RatesLib**: `"nyc"` calendar
- Different compounding convention defaults
- Fixing lag handling (trade time vs. close time)

**Resolution Pattern**: Translate calendar names in adapter layer to maintain consistency

---

## Code Conventions

### Frozen Dataclasses

All queries are frozen dataclasses for immutability and hashability:

```python
from dataclasses import replace

# CORRECT: Use replace() to modify
q_modified = replace(q, tenor="10Y")

# WRONG: Direct assignment fails
q.tenor = "10Y"  # AttributeError: frozen instance
```

**Why**: Enables use as dictionary keys in portfolios and caches

### Risk Weights vs. Notional

#### Risk Weight (query-level)
- Scalar multiplier for query arithmetic
- Affects all metrics proportionally
- Used for portfolio weighting

#### BPV (structure-level)
- Basis point value target for position sizing
- Defines how much price movement = 1bp P&L
- Specific to structure specification

#### Notional (structure-level)
- Raw notional amount in currency units
- Used for leverage/scaling calculations
- Independent of risk weight

### Labels and Signatures

```python
# Query.col_name()
# Human-readable label for DataFrames/plots
# Example: "2Y SOFR Swap Rate (USD)"

# Query.signature()
# Stable identifier for portfolio keys/logging
# Format: product=IRS|struct=OUTRIGHT|tenor=5Y|curve=USD-SOFR-1D
```

---

## Environment Setup

### Python Version Requirement
- **Minimum**: Python 3.12+ (tested with 3.12.9)
- README specifies 3.13 but 3.12+ is acceptable

### Initial Virtual Environment Setup

```bash
# Create virtual environment
python3 -m venv venv

# Activate environment (Linux/Mac)
source venv/bin/activate

# Activate environment (Windows)
venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install all dependencies
pip install -r requirements.txt
```

### Verify Installation

```bash
# Test basic imports and verify versions
python test_basic_workflow.py

# Expected output should show:
# ✓ numpy, pandas, QuantLib, rateslib versions
# ✓ Query creation and arithmetic
# ✓ MDP request building
# ✓ Curve definitions lookup
```

### Key Dependencies Installed
- **Pricing Engines**: QuantLib 1.39, rateslib 2.1.1
- **Data**: numpy 2.3.2, pandas 2.3.1, pyarrow 21.0.0
- **Persistence**: ZODB 6.0.1, BTrees 6.1, persistent 6.1.1
- **Network**: aiohttp 3.12.15, httpx 0.28.1, requests 2.32.4
- **Visualization**: matplotlib 3.10.5, plotly 6.3.0
- **Notebooks**: ipykernel 6.30.1, nest-asyncio 1.6.0

### Quick Start (Every Session)

```bash
# 1. Activate virtual environment
source venv/bin/activate

# 2. Verify environment
python test_basic_workflow.py

# 3. Set Python path for clean imports
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 4. Start development
```

---

## Running Tests

### Quick Validation (No Market Data Required)

```bash
# Test query creation and arithmetic (runs in ~1 second)
python test_basic_workflow.py
```

**Expected Output**:
- numpy, pandas, QuantLib, rateslib versions
- Query creation and arithmetic validation
- MDP request building verification
- Curve definitions lookup confirmation

### Curve Build Tests

Validate curve construction against known reference:

```bash
# Quick validation (no market data needed)
python -c "
import sys
sys.path.insert(0, '.')
from definitions.IRSwaps import CURVE_DEFINITIONS
print(f'Available curves: {len(CURVE_DEFINITIONS)}')
print('Sample curves:', list(CURVE_DEFINITIONS.keys())[:3])
"
```

#### What to Check
- Curve name is in CURVE_DEFINITIONS
- Day counter matches backend (ACT/360 vs. 30/360)
- Calendar is correct (NYC holidays)
- Par rates are within 0.1-1bp of reference (Bloomberg/CME)

### Structure Resolution Tests

Verify query packages resolve correctly:

```python
# Test that fly structure weights sum to 1.0
query_2y = IRSwapQuery(..., tenor="2Y")
query_3y = IRSwapQuery(..., tenor="3Y")
query_5y = IRSwapQuery(..., tenor="5Y")

fly = query_2y + query_5y - 2*query_3y
package = fly.resolve_package(pricer)

total_weight = sum(w for _, w in package)
assert abs(total_weight - 1.0) < 1e-10, f"Weights don't sum to 1.0: {total_weight}"
```

### Backend Parity Tests

Compare QuantLib vs. RatesLib valuations:

```python
# Use same curve timestamp and pillar instruments
# Compare NPV and PV01 outputs
# Tolerance: ~0.1bp for par rates, ~$100 for large notionals
```

### Integration Tests (Notebooks)

Run Jupyter notebooks to validate end-to-end workflows:

```bash
# Convert notebook to script (already verified to work)
jupyter nbconvert --to python month_end_irswaps_backtest.ipynb
python month_end_irswaps_backtest.py  # Should run 99%+ completion

# Expected output: portfolio MTM, P&L history, no crashes
```

**Reference Notebooks**:
- `month_end_irswaps_backtest.ipynb` - Full query-driven backtest walkthrough
- `simple_irswaps_backtest.ipynb` - Minimal example
- `curve_builds.ipynb` - Curve construction and validation
- `fomc_fly_backtest.ipynb` - Event-driven strategy example

### Full Integration Testing

Use Jupyter notebooks in repo root:
- `*_backtest.ipynb` - Backtest examples
- `*_pricer.ipynb` - Pricer examples

**Note**: Full backtests require market data sources (CME credentials, SDR files)

---

## Development Workflow

### Interactive Development Setup

```bash
# Activate virtual environment first
source venv/bin/activate

# Run a backtest interactively
jupyter notebook month_end_irswaps_backtest.ipynb

# OR start Jupyter server and navigate to notebooks
jupyter notebook
```

### Quick Code Validation

```bash
# Test imports (useful after making changes)
python -c "
import sys
sys.path.insert(0, '.')
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
print('✓ Imports successful')
"
```

### Validate Curve Definitions

```bash
# Check available curves
python -c "
from definitions.IRSwaps import CURVE_DEFINITIONS
print(f'Available curves: {len(CURVE_DEFINITIONS)}')
print(list(CURVE_DEFINITIONS.keys())[:3])
"
```

### Add ARBS to Python Path

```bash
# Option 1: Set environment variable
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Option 2: Add to top of scripts
# import sys
# sys.path.insert(0, '.')
```

### Converting Notebooks to Scripts

```bash
# Convert notebook to Python script
jupyter nbconvert --to python notebook_name.ipynb

# Clean up for non-interactive execution
# Remove: get_ipython() calls, %magic commands, plt.show()
# Add: sys.path.insert(0, '.') for imports
```

**Verified Working**: `month_end_irswaps_backtest.ipynb` successfully converts and runs to 99% completion (396/402 steps) before requiring CME data access.

---

## Common Development Tasks

### Adding a New Curve Source

#### Steps
1. Extend `MarketDataProvider` in `MDP/<Domain>/<Domain>MDP.py`
2. Add new source string recognition (e.g., `"SDR_INTRADAY-v2"`)
3. Implement `get_pricer(request)`:
   - Build calendars, indices, fixings
   - Bootstrap pillar instruments
   - Return pricer/curve with consistent interface
4. Add curve metadata to `definitions/IRSwaps.py`
5. Test with small time grid and compare par rates vs. reference

#### Example Template

```python
# In MDP/IRSwaps/IRSwapsMDP.py
def get_pricer(self, request):
    if request.source == "MY_NEW_SOURCE":
        # Build calendar
        calendar = self._build_calendar(request)

        # Build indices and fixings
        index = self._build_index(request)

        # Bootstrap curve
        curve = self._bootstrap_curve(request, calendar, index)

        return curve
```

### Adding a New Value Metric

#### Steps
1. Add enum value to `Query/<Product>/<Product>Value.py`
2. Implement calculation in product's `ValueMap` (`Query/<Product>/adapter.py`)
3. Function signature: `(pricer_or_curve, package, risk_weights, **context) -> float`
4. Update `default_mtm_value_id()` in query class if it should be default MTM

#### Example Template

```python
# In Query/IRSwaps/IRSwapValue.py
class IRSwapValue(Enum):
    RATE = "rate"
    NPV = "npv"
    PV01 = "pv01"
    MY_NEW_METRIC = "my_new_metric"  # Add here

# In Query/IRSwaps/adapter.py
def calculate_my_new_metric(pricer, package, risk_weights, **context):
    """Calculate custom metric on IRS package"""
    result = 0.0
    for instrument, weight in package:
        # Compute metric for each instrument
        metric_value = compute_value(instrument, pricer)
        result += metric_value * weight
    return result * risk_weights
```

### Modifying Product Structures

**Example: Adding a new IRS structure type**

#### Steps
1. Add enum to `Query/IRSwaps/IRSwapStructure.py`
2. Implement builder in `Query/IRSwaps/adapter.py` Structure Map
3. Add validation to `IRSwapQuery.__post_init__()` for required kwargs
4. Test package resolution:

```python
# Test the new structure
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
query = IRSwapQuery(
    structure=IRSwapStructure.MY_NEW_STRUCTURE,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"custom_param": 100}
)
package = query.resolve_package(pricer_or_curve=pricer)
print(package)
```

---

## Troubleshooting

### Missing Fixings

**Symptom**: Valuation errors on historical dates

**Root Cause**: Historical fixing data not available for reference rates

**Fix**:
- Backfill fixings in `MDP/IRSwaps/fixings_cache/`
- Attach fixings to pricer during curve construction
- Check timestamp policy: trade time vs. close time

**Verification**:
```python
# Check if fixings are loaded
print(pricer.fixings)
# Should show historical SOFR/EFFR rates
```

### Non-Deterministic MTM

**Symptom**: Re-running backtest yields different P&L

**Root Cause**:
- Package not frozen at trade time
- Cache key missing recipe details
- Different curve bootstrapping on re-run

**Fix**:
- Ensure `QueryDrivenBacktest` freezes package at `opened_at`
- Add recipe hash to cache key
- Verify curve definitions haven't changed

**Verification**:
```bash
# Run backtest twice, compare results
python backtest.py > run1.txt
python backtest.py > run2.txt
diff run1.txt run2.txt  # Should show no differences
```

### Calendar Misalignment

**Symptom**: Settlement date mismatch between backends (1-2 day difference on weekends)

**Root Cause**: Different calendar naming conventions
- QuantLib uses `"US Government Bond"`
- RatesLib uses `"nyc"` for USD

**Fix**:
- Verify calendar string in `definitions/IRSwaps.py` matches backend convention
- Add translation layer in backend adapter

**Example Translation**:
```python
# In RatesLib adapter
def translate_calendar(calendar_string):
    """Translate ARBS calendar names to RatesLib"""
    mapping = {
        "US Government Bond": "nyc",
        "TARGET": "tgt",
        # ... more mappings
    }
    return mapping.get(calendar_string, calendar_string)
```

**Verification**:
```python
# Compare holidays between backends
from QuantLib import UnitedStates
ql_cal = UnitedStates(UnitedStates.Settlement)

from rateslib.calendars import add_currency
rl_cal = add_currency("USD")

# Check specific dates
test_dates = ["2024-07-04", "2024-12-25"]  # Independence Day, Christmas
for date in test_dates:
    ql_is_holiday = not ql_cal.isBusinessDay(date)
    rl_is_holiday = not rl_cal.isBusinessDay(date)
    assert ql_is_holiday == rl_is_holiday, f"Calendar mismatch on {date}"
```

### Performance Issues

**Solutions**:

#### Use Toolbox Utilities
```python
# Use TB/<Product>TB.py for bulk operations
from TB.IRSwapsTB import IRSwapsTB
tb = IRSwapsTB()
results = tb.bulk_curve_build(dates, curves)
```

#### Enable ZODB Caching
```python
# In backtest code
from Caching.ZODBCacheMixin import ZODBCacheMixin

class CachedMDP(ZODBCacheMixin, MarketDataProvider):
    def get_pricer(self, request):
        # Check cache first
        cache_key = self._build_cache_key(request)
        if cached := self.cache.get(cache_key):
            return cached

        # Build and cache
        pricer = super().get_pricer(request)
        self.cache[cache_key] = pricer
        return pricer
```

#### Constrain Time Grids
```python
# Only compute necessary dates
from pandas import date_range
dates = date_range("2024-01-01", "2024-12-31", freq="BM")  # Month-end only
# Instead of daily: freq="B"
```

#### Parallel Processing
```python
# Use rl_curve_utils for parallel builds
from Query.IRSwaps.backends.rateslib.rl_curve_utils import parallel_curve_build
curves = parallel_curve_build(curve_requests, n_workers=8)
```

### Cache Invalidation After Changes

**Symptom**: Stale cache causing mysterious valuation differences after curve recipe changes

**Root Cause**: Cache key doesn't include recipe version

**Fix**:
```python
# Add recipe hash to cache keys
import hashlib
import json

def build_cache_key(curve_name, timestamp, recipe):
    recipe_hash = hashlib.md5(
        json.dumps(recipe, sort_keys=True).encode()
    ).hexdigest()[:8]

    return f"{curve_name}_{timestamp}_{recipe_hash}"
```

**Alternative**: Bump cache namespace
```python
# In ZODBCacheMixin
CACHE_NAMESPACE = "v2"  # Increment after recipe changes
```

---

## Essential Files Reference

### Core Backtesting
- `/home/peter/ARBS/BT/query_engine.py` - Main backtesting loop for queries
- `/home/peter/ARBS/BT/event_engine.py` - Event-driven backtesting engine

### Query and Adapter Infrastructure
- `/home/peter/ARBS/Query/Base/BaseQuery.py` - Abstract query interface
- `/home/peter/ARBS/Query/Base/product_adapter.py` - Adapter registry and base class
- `/home/peter/ARBS/Query/IRSwaps/adapter.py` - IRS structure/value maps
- `/home/peter/ARBS/Query/IRSwaps/IRSwapQuery.py` - User-facing IRS query builder
- `/home/peter/ARBS/Query/IRSwaps/IRSwapStructure.py` - Structure enum (OUTRIGHT, CURVE, FLY)
- `/home/peter/ARBS/Query/IRSwaps/IRSwapValue.py` - Value metric enum (RATE, NPV, PV01, etc.)

### Market Data
- `/home/peter/ARBS/MDP/IRSwaps/IRSwapsMDP.py` - IRS market data provider dispatcher
- `/home/peter/ARBS/MDP/IRSwaps/backends/cme_ny_eod/CME_NY_EOD_MDP.py` - CME data via QuantLib
- `/home/peter/ARBS/MDP/IRSwaps/backends/sdr_intraday/SDR_INTRADAY_MDP.py` - SDR data via RatesLib

### Metadata and Configuration
- `/home/peter/ARBS/definitions/IRSwaps.py` - Curve metadata and conventions (SINGLE SOURCE OF TRUTH)
- `/home/peter/ARBS/Caching/ZODBCacheMixin.py` - Persistent cache infrastructure

### Backend Systems
- `/home/peter/ARBS/Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py` - QuantLib curve configs
- `/home/peter/ARBS/Query/IRSwaps/backends/quantlib/ql_pricer.py` - QuantLib IRS valuation
- `/home/peter/ARBS/Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py` - RatesLib curve recipes
- `/home/peter/ARBS/Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py` - RatesLib wrapper
- `/home/peter/ARBS/Query/IRSwaps/backends/rateslib/rl_curve_utils/` - Parallel processing utilities

### Jupyter Notebooks (Examples)
- `/home/peter/ARBS/month_end_irswaps_backtest.ipynb` - Full query-driven backtest walkthrough
- `/home/peter/ARBS/simple_irswaps_backtest.ipynb` - Minimal example
- `/home/peter/ARBS/curve_builds.ipynb` - Curve construction and validation
- `/home/peter/ARBS/fomc_fly_backtest.ipynb` - Event-driven strategy example

### Test Files
- `/home/peter/ARBS/test_basic_workflow.py` - Quick validation test (no market data needed)
- `/home/peter/ARBS/test_*.py` - Feature-specific tests

---

## Extension Points

### Adding a New Product

#### Full Process
1. **Create product directory**: `Query/<Product>/`

2. **Implement query interface**:
   ```python
   # Query/<Product>/<Product>Query.py
   from Query.Base.BaseQuery import BaseQuery

   @dataclass(frozen=True)
   class MyProductQuery(BaseQuery):
       tenor: str
       curve: str
       # ... product-specific fields
   ```

3. **Define structures**:
   ```python
   # Query/<Product>/<Product>Structure.py
   from enum import Enum

   class MyProductStructure(Enum):
       OUTRIGHT = "outright"
       CURVE = "curve"
       # ... product-specific structures
   ```

4. **Define value metrics**:
   ```python
   # Query/<Product>/<Product>Value.py
   from enum import Enum

   class MyProductValue(Enum):
       RATE = "rate"
       NPV = "npv"
       # ... product-specific metrics
   ```

5. **Implement adapter**:
   ```python
   # Query/<Product>/adapter.py
   from Query.Base.product_adapter import ProductAdapter

   class MyProductAdapter(ProductAdapter):
       def resolve_structure(self, query, pricer):
           # Map abstract structure to instruments
           pass

       def calculate_value(self, query, pricer, package):
           # Compute requested metric
           pass
   ```

6. **Register adapter**:
   ```python
   # In Query/Base/product_adapter.py
   ADAPTER_REGISTRY["MyProduct"] = MyProductAdapter()
   ```

7. **Implement MDP**:
   ```python
   # MDP/<Product>/<Product>MDP.py
   from MDP.Base.MarketDataProvider import MarketDataProvider

   class MyProductMDP(MarketDataProvider):
       def get_pricer(self, request):
           # Build and return pricer
           pass
   ```

### Adding a New Backend

#### Steps
1. Create backend directory: `Query/<Product>/backends/<backend_name>/`

2. Implement curve definition mapping:
   ```python
   # <backend_name>_curve_definitions_map.py
   CURVE_MAP = {
       "USD-SOFR-1D": {
           "index": "SOFR",
           "conventions": {...},
       }
   }
   ```

3. Implement pricer wrapper:
   ```python
   # <backend_name>_pricer.py
   class MyBackendPricer:
       def npv(self, instrument):
           pass

       def pv01(self, instrument):
           pass

       def par_rate(self, instrument):
           pass
   ```

4. Add backend selection in MDP:
   ```python
   # In MDP/<Product>/<Product>MDP.py
   def get_pricer(self, request):
       if request.backend == "my_backend":
           return MyBackendPricer(...)
   ```

### Adding a New Data Source

#### Steps
1. Extend `MarketDataProvider` in `MDP/<Domain>/<Domain>MDP.py`

2. Add source string recognition:
   ```python
   def get_pricer(self, request):
       if request.source == "MY_NEW_SOURCE":
           return self._build_from_my_source(request)
   ```

3. Implement data fetch and curve build:
   ```python
   def _build_from_my_source(self, request):
       # Fetch data
       raw_data = self._fetch_data(request)

       # Build calendar
       calendar = self._build_calendar(request)

       # Build index
       index = self._build_index(request)

       # Bootstrap curve
       curve = self._bootstrap_curve(
           raw_data, calendar, index, request
       )

       return curve
   ```

4. Add metadata to `definitions/IRSwaps.py`:
   ```python
   CURVE_DEFINITIONS["USD-SOFR-MY-SOURCE"] = {
       "source": "MY_NEW_SOURCE",
       "reference_rate": "SOFR",
       # ... conventions
   }
   ```

5. Validate par rates against known reference

### Testing New Extensions

#### Validation Checklist
- [ ] Unit tests for new classes
- [ ] Integration tests with existing infrastructure
- [ ] Backend parity tests (if applicable)
- [ ] Performance benchmarks
- [ ] Documentation updated

#### Example Test Structure
```python
# test_my_extension.py
import sys
sys.path.insert(0, '.')

# ARRANGE
from Query.MyProduct.MyProductQuery import MyProductQuery

# ACT
query = MyProductQuery(...)
result = query.some_method()

# ASSERT
assert result == expected_value, f"Expected {expected_value}, got {result}"
print("✓ Test passed")
```

---

## Quick Command Reference

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Develop
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python test_basic_workflow.py         # Quick validation
python test_my_feature.py             # Feature test

# Validate
python -c "from definitions.IRSwaps import CURVE_DEFINITIONS; print(len(CURVE_DEFINITIONS))"
jupyter nbconvert --to python notebook.ipynb

# Debug
python notebook.py                    # Run converted notebook
python -c "import QuantLib; print(QuantLib.__version__)"

# Clean up
rm -rf __pycache__
rm -f *.pyc
find . -name "*.pyc" -delete
```

---

## Development Notes

### Current Limitations
- **No linter configured**: Manual code formatting required
- **No CI/CD**: Manual validation via notebooks
- **Git workflow**: Single branch (main)
- **Data sources**: Some require credentials (CME API, SDR files)

### Performance Characteristics
- **Curve builds**: ~100-500ms per curve (varies by source)
- **Valuation**: ~1-10ms per instrument
- **Backtest**: ~10-60 seconds for 1 year of daily data (cached)
- **Cache hit**: <1ms retrieval

### Known Issues
- Backend parity: Both QuantLib and RatesLib should produce similar par rates within tolerance (~0.1-1bp)
- Calendar alignment: Check day count/calendar alignment if drift occurs
- Fixing timestamps: Trade time vs. close time can cause 1-day differences

---

**Last Updated**: Check git log for recent changes to this file
