# ARBS Architecture Documentation

**Source**: `/home/peter/ARBS/CLAUDE.md`
**Last Updated**: From repository local version
**Purpose**: Complete technical architecture reference for ARBS backtesting system

---

## Repository Overview

ARBS (Awesome Rates Backtesting System) is a modular research codebase for building yield curves, pricing interest rate derivatives, and running event- or query-driven backtests. The architecture follows an **adapter pattern** where the backtester is **product-agnostic** while product-specific logic lives behind adapters.

### Key Characteristics

- **Modular Design**: Three-layer separation enabling component reuse
- **Product-Agnostic Core**: Backtesting engine works with any instrument via adapters
- **Dual Backtesting Modes**: Query-driven (product-neutral) and event-driven (instrument-specific)
- **Multi-Backend Support**: QuantLib and RatesLib for curve building and valuation
- **Persistent Caching**: ZODB-based infrastructure for large-scale historical runs

---

## Core Architecture

### Three-Layer Design

#### 1. Backtesting Layer (`BT/`)

The core execution engine for both query-driven and event-driven workflows:

- **`QueryDrivenBacktest`**: Product-agnostic backtester that works with `BaseQuery` objects
  - Primary usage pattern for research and analysis
  - Operates on abstract query definitions independent of instrument type
  - Supports query arithmetic (e.g., fly spreads: `q_2y + q_5y - 2*q_3y`)

- **`EventDrivenBacktest`**: General engine for concrete instruments with orders/hedging
  - Used when explicit order flow and hedging decisions are needed
  - Manages order lifecycle and hedging execution
  - Operates at instrument level (IRS, bonds, futures, etc.)

- **Common Responsibilities**:
  - Portfolio management and position tracking
  - P&L history accumulation and reporting
  - Strategy execution via triggers and actions
  - Timeline stepping and event processing

#### 2. Query/Adapter Layer (`Query/`)

The abstraction layer bridging high-level query definitions to concrete valuations:

- **`BaseQuery`**: Abstract interface defining what to value
  - Structure: Definition of instrument composition (OUTRIGHT, CURVE, FLY)
  - Value Metrics: What to compute (NPV, PV01/BPV, RATE)
  - Frozen dataclass for hashability and use in portfolios

- **Product Adapters**: Map queries to concrete structures and value functions
  - Structure Map: Converts abstract structures to instrument packages
  - Value Map: Implements metric calculations
  - Current products:
    - `Query/IRSwaps/` - Interest Rate Swaps
    - `Query/FixedRateBonds/` - Fixed rate bonds
  - Extensible for new products

- **Adapter Registry** (`Query/Base/product_adapter.py`):
  - Central registration of product-specific adapters
  - Runtime dispatch based on query type

#### 3. Market Data Layer (`MDP/`)

Encapsulates all market data sourcing and curve construction:

- **`MarketDataProvider`**: Abstract interface
  - Primary method: `get_pricer(request) -> pricer_or_curve`
  - Returns consistent interface regardless of source

- **Data Sources**:
  - `CME_NY_EOD`: End-of-day CME data via QuantLib
  - `SDR_INTRADAY`: SwapData Repository intraday data via RatesLib
  - `GSQUANT`: Goldman Sachs Quant stubs via RatesLib
  - Extensible for new sources

- **Responsibilities**:
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

**Available Metrics**:
- `RATE`: Par rate (swap coupon for par value)
- `NPV`: Net present value in basis points
- `PV01`/`BPV`: Basis point value (DV01)
- `Carry`: Day-to-day accrual
- `Roll`: Carry plus first-order curve slide

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

**Infrastructure**: ZODB-based persistent storage for curve builds and valuations

**Use Cases**:
- Large time grids (months/years of daily data)
- Repeated curve construction (expensive operation)
- Valuation history archival

**Cache Keys Include**:
- Source (CME_NY_EOD, SDR_INTRADAY, etc.)
- Curve name (USD-SOFR-1D, etc.)
- Timestamp (daily close, specific time)
- Recipe hash (curve construction recipe version)

**Invalidation Strategy**:
- Bump namespace after recipe changes
- Add recipe hash to cache keys for version tracking
- Manual cache clearing when needed

---

## Backend Systems

### QuantLib Backend (`Query/IRSwaps/backends/quantlib/`)

**Components**:
- `ql_curve_definitions_map.py`: Maps repository curve names to QuantLib bootstrap configurations
- `ql_pricer.py`: IRS valuation functions
  - NPV calculation
  - PV01 sensitivity computation
  - Par rate solving (finding swap coupon for par value)

**Data Source**: CME_NY_EOD_LIVE
**Language**: C++ (via SWIG bindings)
**Strengths**: Robust, production-tested, wide instrument support

**Key Conventions**:
- Calendar string: `"US Government Bond"` for USD
- Day counter: From CURVE_DEFINITIONS

### RatesLib Backend (`Query/IRSwaps/backends/rateslib/`)

**Components**:
- `rl_curve_definitions_map.py`: Maps repository curve names to RatesLib curve recipes
- `RLIRSwapCurve.py`: Wrapper providing consistent interface to QuantLib
- `rl_curve_utils/`: Parallel processing utilities for bulk curve builds

**Data Sources**: SDR_INTRADAY, GSQUANT
**Language**: Python (pure Python implementation)
**Strengths**: Fast iteration, detailed curve inspection, Python ecosystem

**Key Conventions**:
- Calendar string: `"nyc"` for USD
- Curve recipes: YAML-based specifications for flexible bootstrapping
- Dual number support: Automatic differentiation for Greeks

### Backend Parity

**Tolerance**: Par rates should agree within 0.1-1 basis point

**Verification Process**:
1. Build same curve with both backends on same date
2. Compare par rates across tenors
3. If drift > 1bp, check:
   - Day count convention alignment
   - Calendar holiday handling
   - Fixing date conventions
   - Settlement day calculations

**Common Misalignments**:
- QuantLib: `"US Government Bond"` calendar
- RatesLib: `"nyc"` calendar
- Different compounding convention defaults
- Fixing lag handling (trade time vs. close time)

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

**Risk Weight** (query-level):
- Scalar multiplier for query arithmetic
- Affects all metrics proportionally
- Used for portfolio weighting

**BPV** (structure-level):
- Basis point value target for position sizing
- Defines how much price movement = 1bp P&L
- Specific to structure specification

**Notional** (structure-level):
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

## Essential Files Reference

### Core Backtesting

- `BT/query_engine.py` - Main backtesting loop for queries
- `BT/event_engine.py` - Event-driven backtesting engine

### Query and Adapter Infrastructure

- `Query/Base/BaseQuery.py` - Abstract query interface
- `Query/Base/product_adapter.py` - Adapter registry and base class
- `Query/IRSwaps/adapter.py` - IRS structure/value maps
- `Query/IRSwaps/IRSwapQuery.py` - User-facing IRS query builder
- `Query/IRSwaps/IRSwapStructure.py` - Structure enum (OUTRIGHT, CURVE, FLY)
- `Query/IRSwaps/IRSwapValue.py` - Value metric enum (RATE, NPV, PV01, etc.)

### Market Data

- `MDP/IRSwaps/IRSwapsMDP.py` - IRS market data provider dispatcher
- `MDP/IRSwaps/backends/cme_ny_eod/CME_NY_EOD_MDP.py` - CME data via QuantLib
- `MDP/IRSwaps/backends/sdr_intraday/SDR_INTRADAY_MDP.py` - SDR data via RatesLib

### Metadata and Configuration

- `definitions/IRSwaps.py` - Curve metadata and conventions
- `Caching/ZODBCacheMixin.py` - Persistent cache infrastructure

---

## Extension Points

### Adding a New Product

1. Create `Query/<Product>/` directory with:
   - `<Product>Query.py` - User-facing query class (extend BaseQuery)
   - `<Product>Structure.py` - Structure enum
   - `<Product>Value.py` - Value metric enum
   - `adapter.py` - Structure and value maps

2. Register adapter in `Query/Base/product_adapter.py`

3. Implement MDP for product:
   - Create `MDP/<Product>/<Product>MDP.py`
   - Extend MarketDataProvider interface

### Adding a New Curve Source

1. Extend `MarketDataProvider` in `MDP/<Domain>/<Domain>MDP.py`
2. Add source string recognition
3. Implement `get_pricer(request)`:
   - Build calendars, indices, fixings
   - Bootstrap pillar instruments
   - Return pricer/curve with consistent interface
4. Add metadata to `definitions/IRSwaps.py`
5. Validate par rates vs. known reference

### Adding a New Value Metric

1. Add enum value to `Query/<Product>/<Product>Value.py`
2. Implement calculation in `Query/<Product>/adapter.py` ValueMap
3. Function signature: `(pricer_or_curve, package, risk_weights, **context) -> float`
4. Update `default_mtm_value_id()` if should be default MTM

---

## Architecture Benefits

### Modularity
- **Separation of Concerns**: Each layer has single responsibility
- **Easy Testing**: Components can be tested in isolation
- **Reusability**: Backtesting engine works with any product

### Extensibility
- **New Products**: Add via adapters without changing core
- **New Data Sources**: Plug new MDPs without modifying backtester
- **New Metrics**: Extend value maps incrementally

### Consistency
- **Single Source of Truth**: Curve definitions prevent drift
- **Backend Parity**: Adapter pattern ensures consistent behavior
- **Hashable Queries**: Portfolio keys and caching work reliably

### Performance
- **Persistent Caching**: Large backtests leverage disk storage
- **Query Arithmetic**: Composite structures computed on-demand
- **Parallel Curve Building**: RatesLib utilities support concurrent execution

---

## Key References

See `/home/peter/ARBS/CLAUDE.md` for:
- Detailed environment setup and testing instructions
- Common development tasks and troubleshooting guides
- Code conventions and design patterns
- Important files reference
- Jupyter notebook examples and conversion utilities

