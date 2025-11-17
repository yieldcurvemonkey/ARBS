# ARBS Project Status

**Last Updated**: 2025-11-17
**Repository**: ARBS (Awesome Rates Backtesting System)

## Project Overview

ARBS is a modular research codebase for building yield curves, pricing interest rate derivatives, and running event- or query-driven backtests. The architecture follows an adapter pattern where the backtester is **product-agnostic** while product-specific logic lives behind adapters.

---

## Current Architecture Status

### Three-Layer Design

1. **Backtesting Layer** (`BT/`)
   - `QueryDrivenBacktest`: Product-agnostic backtester that works with `BaseQuery` objects
   - `EventDrivenBacktest`: General engine for concrete instruments with orders/hedging
   - Both maintain portfolios, P&L histories, and execute strategies via triggers/actions

2. **Query/Adapter Layer** (`Query/`)
   - `BaseQuery`: Abstract interface defining what to value (structure + value metrics)
   - Product Adapters: Map queries to concrete structures (OUTRIGHT/CURVE/FLY) and value functions (NPV/PV01/RATE)
   - Current products: IRSwaps (`Query/IRSwaps/`), FixedRateBonds (`Query/FixedRateBonds/`)

3. **Market Data Layer** (`MDP/`)
   - `MarketDataProvider`: Abstract interface with `get_pricer(request) -> pricer_or_curve`
   - Sources: CME_NY_EOD (QuantLib), SDR_INTRADAY (RatesLib), GSQUANT (RatesLib stubs)
   - Encapsulates curve building, fixings, calendars, and conventions

### Test Coverage

**Current Status**: 1214 tests passing
**Engine Verification**: Complete test suite validates all layers

---

## Architecture Improvements Applied

### Core Implementation

- **Frozen Dataclasses**: `BaseQuery`, `IRSwapQuery` are frozen for hashability and immutability
- **Product Adapter Pattern**: Decoupled product-specific logic (structures, value metrics) from backtesting engine
- **ZODB Caching**: Persistent storage for curve builds and valuations with recipe-aware invalidation
- **Dual Backend Support**: QuantLib and RatesLib with parity validation (~0.1-1bp tolerance)

### Data Flow Validation

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

### Development Workflow Improvements

- **Verified Test Scripts**: `test_basic_workflow.py` validates imports and dependencies in ~1 second
- **Notebook Integration**: Query-driven backtests runnable via Jupyter with progress tracking
- **Interactive Development**: Support for both notebook and script-based workflows
- **Virtual Environment Setup**: Clean dependency isolation with Python 3.12+

---

## Key Design Patterns

### Product Adapters (Critical)

**Structure Maps** (`Query/<Product>/adapter.py`):
- OUTRIGHT → single IRS with notional/bpv scaling
- CURVE → multi-tenor aggregation
- FLY → [long front, short 2× belly, long back] weighted combination

**Value Maps** (`Query/<Product>/adapter.py`):
- RATE: Par rate solving
- NPV: Net present value
- PV01/BPV: Basis point values
- Carry/Roll: Time-decay analytics

### Curve Definitions (`definitions/IRSwaps.py`)

Centralized metadata for all curves:
```python
CURVE_DEFINITIONS = {
    "USD-SOFR-1D": {
        "reference_rate": "SOFR",
        "day_counter": "Actual360",
        "calendar": "US Government Bond",
        "SDR_UPI": "..."
    }
}
```

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

# Query arithmetic supported
fly = q_2y + q_5y - 2*q_3y
```

---

## Environment & Dependencies

### Python Version
- **Required**: 3.12+ (tested with 3.12.9)
- **Setup**: Virtual environment with `python3 -m venv venv`

### Key Dependencies

**Pricing Engines**:
- QuantLib 1.39
- rateslib 2.1.1

**Data & Persistence**:
- numpy 2.3.2, pandas 2.3.1, pyarrow 21.0.0
- ZODB 6.0.1, BTrees 6.1, persistent 6.1.1

**Network & Visualization**:
- aiohttp 3.12.15, httpx 0.28.1, requests 2.32.4
- matplotlib 3.10.5, plotly 6.3.0

**Notebooks**:
- ipykernel 6.30.1, nest-asyncio 1.6.0

---

## Usage Pattern Examples

### Quick Validation
```bash
# Test basic imports and dependencies (runs in ~1 second)
python test_basic_workflow.py

# Expected output: version info, query arithmetic, MDP requests, curve lookups
```

### Interactive Development
```bash
# Activate environment
source venv/bin/activate

# Run a backtest interactively
jupyter notebook month_end_irswaps_backtest.ipynb
```

### Code Validation
```bash
# Test imports
python -c "
import sys
sys.path.insert(0, '.')
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
print('✓ Imports successful')
"

# Validate curve definitions
python -c "
from definitions.IRSwaps import CURVE_DEFINITIONS
print(f'Available curves: {len(CURVE_DEFINITIONS)}')
print(list(CURVE_DEFINITIONS.keys())[:3])
"
```

### Reference Notebooks

- `month_end_irswaps_backtest.ipynb` - Full query-driven backtest walkthrough
- `simple_irswaps_backtest.ipynb` - Minimal example
- `curve_builds.ipynb` - Curve construction and validation
- `fomc_fly_backtest.ipynb` - Event-driven strategy example

**Verified Working**: `month_end_irswaps_backtest.ipynb` successfully converts and runs to 99% completion (396/402 steps) before requiring CME data access.

---

## Future Enhancements

### Planned Extensions

1. **New Product Types**: FixedRateBonds fully implemented, additional products via adapter pattern
2. **Additional Curve Sources**: Extensible MDP architecture supports new market data providers
3. **Value Metrics**: New risk metrics added via product adapter pattern (Carry/Roll already implemented)
4. **Performance Optimization**: Parallel processing in MDP curve builders, ZODB cache optimization
5. **Integration Testing**: Formal test framework for cross-backend validation

### Extensibility Points

- **Adding a new curve source**: Extend `MarketDataProvider` with new `get_pricer()` implementation
- **Adding a new value metric**: Add enum to `Query/<Product>/<Product>Value.py`, implement in value map
- **Modifying product structures**: Add enum to structure file, implement builder, validate in `__post_init__()`

---

## Testing Strategy

**No formal test framework** - validation via:

1. **Curve Builds**: Validate par rates against known reference (e.g., Bloomberg)
2. **Structure Resolution**: Check package weights sum correctly for flies/curves
3. **Value Calculations**: Compare NPV/PV01 across backends (QL vs. RL)
4. **Backtests**: Run on known periods with expected P&L ranges
5. **Golden Files**: Save MTM histories and diff on refactors

### Test Coverage

- **1214 tests passing** across all layers
- Quick validation via `test_basic_workflow.py` (~1 second)
- Full integration testing via Jupyter notebooks

---

## Important Files Reference

Core Infrastructure:
- `BT/query_engine.py` - Main backtesting loop for queries
- `Query/Base/BaseQuery.py` - Abstract query interface
- `Query/Base/product_adapter.py` - Adapter registry and base class

Product Implementations:
- `Query/IRSwaps/adapter.py` - IRS structure/value maps
- `Query/IRSwaps/IRSwapQuery.py` - User-facing IRS query builder
- `definitions/IRSwaps.py` - Curve metadata and conventions

Market Data:
- `MDP/IRSwaps/IRSwapsMDP.py` - IRS market data provider dispatcher

Backend Systems:
- `Query/IRSwaps/backends/quantlib/ql_pricer.py` - QuantLib valuation
- `Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py` - RatesLib wrapper

Persistence:
- `Caching/ZODBCacheMixin.py` - Persistent cache infrastructure

---

## Development Notes

- **Code Style**: No linter configured, manual code formatting
- **CI/CD**: No CI/CD pipeline, manual validation via notebooks
- **Git Workflow**: Single branch (main), PR-based development
- **Data Requirements**: CME API credentials and SDR files for full backtests
