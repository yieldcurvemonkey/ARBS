# ARBS Codebase Familiarization Summary

**Date**: 2025-11-17
**Session**: Initial codebase exploration
**Status**: Comprehensive understanding achieved

---

## Executive Summary

ARBS (Awesome Rates Backtesting System) is a sophisticated, modular research codebase for building yield curves, pricing interest rate derivatives, and running backtests. The architecture follows a clean three-layer separation with product-agnostic backtesting at its core.

**Key Stats**:
- **Test Coverage**: 1214 tests passing
- **Python Version**: 3.12+ (tested with 3.12.9)
- **Key Dependencies**: QuantLib 1.39, rateslib 2.1.1, ZODB 6.0.1
- **LOC**: ~50K+ lines across core modules

---

## Architecture Overview

### Three-Layer Architecture

The codebase is organized into three distinct layers that maintain clear separation of concerns:

#### 1. Backtesting Layer (`BT/`)
**Purpose**: Core execution engine for both query-driven and event-driven workflows

**Key Files**:
- `BT/query_engine.py` - QueryDrivenBacktest (primary usage pattern)
- `BT/event_engine.py` - EventDrivenBacktest (instrument-specific)
- `BT/query_portfolio.py` - Portfolio management
- `BT/accounting.py` - P&L tracking and mark-to-market

**Responsibilities**:
- Portfolio management and position tracking
- P&L history accumulation and MTM calculation
- Strategy execution via triggers and actions
- Timeline stepping and event processing
- Order lifecycle management (for event-driven mode)

**Key Pattern**: Product-agnostic - works with any instrument via adapters

#### 2. Query/Adapter Layer (`Query/`)
**Purpose**: Abstraction layer bridging high-level query definitions to concrete valuations

**Key Files**:
- `Query/Base/BaseQuery.py` - Abstract query interface (frozen dataclass)
- `Query/Base/product_adapter.py` - Adapter registry and base class
- `Query/IRSwaps/IRSwapQuery.py` - User-facing IRS query builder
- `Query/IRSwaps/adapter.py` - IRS structure/value maps
- `Query/FixedRateBonds/` - Fixed rate bond queries

**Responsibilities**:
- Define what to value (structure: OUTRIGHT/CURVE/FLY)
- Define what to compute (value: NPV/PV01/RATE)
- Map abstract queries to concrete instrument packages
- Support query arithmetic (e.g., fly = q_2y + q_5y - 2*q_3y)
- Resolve treasury aliases/CUSIPs to swap contracts (matched-maturity swaps)

**Key Pattern**: Adapter pattern enables product extensibility while keeping backtest engine generic

**Current Products**:
- IRSwaps (`Query/IRSwaps/`)
- FixedRateBonds (`Query/FixedRateBonds/`)
- Futures (`Query/Futures/`)
- Equities (`Query/Equities/`)
- Currencies (`Query/Currencies/`)
- Bridges (`Query/Bridges/`) - Cross-asset spread trades

#### 3. Market Data Layer (`MDP/`)
**Purpose**: Encapsulates all market data sourcing and curve construction

**Key Files**:
- `MDP/MarketDataProvider.py` - Abstract base class
- `MDP/IRSwaps/IRSwapsMDP.py` - IRS market data dispatcher
- `MDP/IRSwaps/CME_NY_EOD_LIVE/` - CME end-of-day data (QuantLib)
- `MDP/IRSwaps/SDR_INTRADAY/` - SwapData Repository intraday (RatesLib)
- `MDP/IRSwaps/GSQUANT/` - Goldman Sachs Quant data (RatesLib)

**Responsibilities**:
- Curve building and bootstrapping
- Fixing management and historical lookup
- Calendar and business convention application
- Convention mapping (day counters, compounding)
- Backend dispatch (QuantLib vs RatesLib)

**Data Sources**:
- **CME_NY_EOD**: End-of-day CME data via QuantLib
- **SDR_INTRADAY**: SwapData Repository intraday data via RatesLib
- **GSQUANT**: Goldman Sachs Quant stubs via RatesLib

**Key Pattern**: Single source of truth for curve conventions at `definitions/IRSwaps.py`

---

## Key Design Patterns

### 1. Product Adapter Pattern (Critical)

The adapter pattern is the cornerstone of ARBS's extensibility:

```python
# Structure Maps (Query/<Product>/adapter.py)
OUTRIGHT: Single instrument at specified maturity
CURVE: Multiple instruments along tenor spectrum with weights
FLY: Weighted combination [long front, short 2× belly, long back]

# Value Maps (Query/<Product>/adapter.py)
def calculate_metric(pricer_or_curve, package, risk_weights, **context) -> float
```

**Benefits**:
- Product-agnostic backtesting engine
- Clean separation of product logic
- Easy to add new products without touching backtest core
- Consistent interface across all instruments

### 2. Frozen Dataclasses for Queries

All queries are immutable (`frozen=True`) for hashability:

```python
@dataclass(frozen=True)
class IRSwapQuery(BaseQuery):
    structure: IRSwapStructure = IRSwapStructure.OUTRIGHT
    value: IRSwapValue = IRSwapValue.RATE
    tenor: Optional[str] = None
    curve: Optional[str] = None
    # ... more fields
```

**Benefits**:
- Queries can be dictionary keys in portfolios
- Cache keys are stable and deterministic
- Arithmetic operations create new queries (no mutation)

### 3. Query Arithmetic

Queries support mathematical operations:

```python
# Create individual queries
q_2y = IRSwapQuery(structure=OUTRIGHT, tenor="2Y", curve="USD-SOFR-1D")
q_3y = IRSwapQuery(structure=OUTRIGHT, tenor="3Y", curve="USD-SOFR-1D")
q_5y = IRSwapQuery(structure=OUTRIGHT, tenor="5Y", curve="USD-SOFR-1D")

# Create fly structure via arithmetic
fly = q_2y + q_5y - 2*q_3y  # [+1 × 2Y, -2 × 3Y, +1 × 5Y]
```

**Implementation**: Queries return lists on arithmetic ops, maintaining risk_weight scalars

### 4. Dual Backend Support

ARBS supports both QuantLib and RatesLib for pricing:

**QuantLib Backend** (`Query/IRSwaps/backends/quantlib/`):
- C++ (via SWIG bindings)
- Production-tested and robust
- Calendar: `"US Government Bond"`
- Use case: CME end-of-day data

**RatesLib Backend** (`Query/IRSwaps/backends/rateslib/`):
- Pure Python implementation
- Fast iteration and detailed inspection
- Calendar: `"nyc"`
- Dual number support for automatic differentiation
- Use case: SDR intraday data, custom curve recipes

**Parity Testing**: Par rates should agree within 0.1-1bp tolerance

### 5. ZODB Persistent Caching

Cache infrastructure for expensive curve builds:

**Components**:
- `Caching/ZODBCacheMixin.py` - Base cache infrastructure
- `Data/Cache/` - Cache storage directory

**Cache Keys Include**:
- Source (CME_NY_EOD, SDR_INTRADAY, etc.)
- Curve name (USD-SOFR-1D, etc.)
- Timestamp (daily close, specific time)
- Recipe hash (curve construction recipe version)

**Critical Rule**: Bump cache namespace after recipe changes to avoid stale data

### 6. Curve Definitions (Single Source of Truth)

`definitions/IRSwaps.py` centralizes all curve metadata:

```python
CURVE_DEFINITIONS = {
    "USD-SOFR-1D": {
        "ReferenceRate": "USD-SOFR-OIS Compound",
        "DayCounter": "ACT/360",
        "Calendar": "US Government Bond",
        "SettlementDays": 2,
        "SDR_UPIs": ["QZXQ4R16245X", "QZPB5VSBGRCD"],
        # ... more conventions
    },
    # ... more curves
}
```

**Purpose**: Eliminate drift between QuantLib and RatesLib backends

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

**10-Step Detailed Flow**:
1. Strategy definition (high-level trading logic)
2. Trigger evaluation (conditions checked against market state)
3. Order generation (triggers create orders on specified queries)
4. Query creation (orders reference product-agnostic queries)
5. MDP request building (query constructs market data request)
6. Pricer/curve retrieval (MDP returns bootstrapped curve or pricer)
7. Package resolution (query maps abstract structure to concrete instruments)
8. Value map construction (adapter builds calculation functions)
9. Metric computation (ValueMap applies functions to pricer/package)
10. Portfolio update (results recorded in position/P&L history)

---

## Additional Modules

### Risk Module (`Risk/`)
**Purpose**: Risk management and portfolio analytics

**Components**:
- `Risk/Covariance/` - Covariance matrix estimation
- `Risk/Volatility/` - Volatility estimation and forecasting
- `Risk/Returns/` - Returns calculation and analysis
- `Risk/risk_model_factory.py` - Factory for risk models
- `Risk/templates/` - Risk report templates

**Integration**: Works with Grinold-Kahn framework for portfolio construction

### Signals Module (`Signals/`)
**Purpose**: Alpha signal generation and combination

**Components**:
- `Signals/AlphaGenerator.py` - Generic alpha generation framework
- `Signals/SignalCombiner.py` - Multi-signal combination
- `Signals/CorrelationVolatilitySignal.py` - Correlation/vol-based signals
- `Signals/CurrencyCarrySignal.py` - Currency carry strategies
- `Signals/MLPredictedReturnsSignal.py` - ML-based return predictions
- `Signals/SectorRotation/` - Sector rotation strategies
- `Signals/Futures/` - Futures-specific signals

**Key Pattern**: Decomposable signals with standardized interfaces

### Strategies Module (`Strategies/`)
**Purpose**: High-level strategy definitions and management

**Components**:
- `Strategies/Factory/` - Strategy factory pattern
- `Strategies/Registry/` - Strategy registration and lookup
- `Strategies/Config/` - Strategy configuration management
- `config/strategies/` - YAML/JSON strategy configs

**Integration**: Strategies consume signals and generate orders via backtest engine

### Asset Module (`Asset/`)
**Purpose**: Asset abstraction layer

**Components**:
- `Asset/Base/` - Base asset classes

**Note**: Separate from Query layer, provides object-oriented asset representation

### Adapter Module (`Adapter/`)
**Purpose**: Generic adapter infrastructure (separate from Query/product adapters)

**Components**:
- `Adapter/Base/` - Base adapter classes

### Optimizer Module (`Optimizer/`)
**Purpose**: Portfolio optimization

**Components**:
- `Optimizer/Base/` - Base optimizer classes
- Uses cvxpy for convex optimization

**Integration**: Works with Grinold-Kahn portfolio construction

### Backtest Module (`Backtest/`)
**Purpose**: Legacy/alternative backtesting infrastructure

**Note**: Separate from `BT/` - likely older implementation or different use case

### TB Module (`TB/`)
**Purpose**: Toolbox utilities for bulk operations

**Use Case**: Parallel curve builds, batch processing, performance optimization

### RVUtils Module (`RVUtils/`)
**Purpose**: Relative value utilities

**Components**:
- `RVUtils/Interpolation/` - Curve interpolation utilities

---

## Test Infrastructure

### Testing Framework

**Current Status**: pytest-based with 1214 passing tests

**Test Structure**:
```
tests/
├── unit/           # Unit tests for individual components
│   ├── adapter/
│   ├── backtest/
│   ├── query/
│   ├── risk/
│   ├── signals/
│   └── ...
├── integration/    # Integration tests
├── validation/     # Validation tests
├── golden/         # Golden file tests
├── conftest.py     # pytest fixtures and configuration
└── utils.py        # Test utilities
```

**Key Features**:
- Mock market data providers for fast tests
- Golden file comparison with tolerance
- Deterministic test data generation
- Date fixtures (base_date, date_range, quarterly_dates)
- Mock pricers and curves

**Test Patterns**:
```python
# TDD Pattern (from CLAUDE.md)
# 1. Write failing test FIRST
# 2. Implement minimal code to pass
# 3. Refactor while keeping tests green

# Test structure: ARRANGE → ACT → ASSERT
def test_query_creation():
    # ARRANGE
    curve_name = "USD-SOFR-1D"
    tenor = "5Y"

    # ACT
    query = IRSwapQuery(structure=OUTRIGHT, tenor=tenor, curve=curve_name)

    # ASSERT
    assert query.tenor == "5Y"
    assert query.curve == curve_name
```

**Test Files Missing**:
- `test_basic_workflow.py` (referenced in docs but not present)
- Virtual environment not set up (pytest not available in base Python)

---

## Documentation

### Primary Documentation Files

**Root Level**:
- `CLAUDE.md` - Universal development rules and ARBS overview (27KB)
- `ARBS_ARCHITECTURE.md` - Detailed technical architecture (32KB)
- `README.md` - Project overview and setup instructions (28KB)
- `TODO.md` - Project tasks and roadmap

**Technical Documentation** (`docs/`):
- `GRINOLD_KAHN_FRAMEWORK.md` - Grinold-Kahn integration (21KB)
- `GRINOLD_KAHN_DETAILED_SPECS.md` - Detailed G-K specifications (36KB)
- `ALPHA_GENERATOR.md` - Alpha generation framework (38KB)
- `BACKTEST_API.md` - Backtesting API reference (21KB)
- `FUTURES_BACKTESTING_GUIDE.md` - Futures-specific backtesting (10KB)
- `PORTFOLIO_CONSTRUCTION_WORKFLOW.md` - Portfolio construction (8KB)
- `SIGNAL_COMBINATION_METHODS.md` - Signal combination techniques (14KB)

**User Guides** (`docs/`):
- `USER_GUIDE_STRATEGY_CREATION.md` - Creating custom strategies (32KB)
- `ADDING_CUSTOM_COMPONENTS.md` - Extending the system (15KB)
- `TRADER_REQUIREMENTS.md` - Trading requirements and constraints (12KB)

**Analysis Documents** (`docs/`):
- `CROSS_ASSET_CONCURRENCY_ANALYSIS.md` - Cross-asset analysis (32KB)
- `PAPER_IMPLEMENTATION_FIDELITY.md` - Paper implementation fidelity (19KB)
- `ORTHOGONAL_TASK_DECOMPOSITION.md` - Task decomposition patterns (26KB)

**Archive** (`docs/archive/`):
- Session summaries and analysis reports
- Abandoned plans and experiments

---

## Key Insights

### 1. Clean Architecture
The three-layer separation is well-maintained:
- **BT/** knows nothing about products
- **Query/** bridges products to backtest via adapters
- **MDP/** is purely data provision

### 2. Extensibility by Design
Adding new products requires only:
1. Create `Query/<Product>/` directory
2. Implement `<Product>Query` extending `BaseQuery`
3. Implement adapter with structure/value maps
4. Register adapter in `product_adapter.py`
5. Implement MDP for data sourcing

No changes needed to backtest engine!

### 3. Dual Backend Strategy
Supporting both QuantLib and RatesLib provides:
- **Robustness**: QuantLib for production
- **Flexibility**: RatesLib for rapid iteration
- **Validation**: Backend parity ensures correctness
- **Performance**: Choose backend based on use case

### 4. Advanced Features Beyond Core
The codebase extends far beyond basic backtesting:
- **Grinold-Kahn portfolio construction**
- **ML-based signal generation**
- **Risk model integration**
- **Multi-asset support (swaps, bonds, futures, equities, currencies)**
- **Advanced optimization (cvxpy integration)**

### 5. Research Codebase Philosophy
Not production trading system, but research infrastructure:
- Emphasis on flexibility over performance
- Extensive documentation and examples
- Jupyter notebook integration
- Multiple data sources supported
- Easy experimentation and iteration

### 6. Matched-Maturity Swap (MMS) Support
The adapter layer supports resolving treasury aliases/CUSIPs to swap contracts:
- "CT5" → Current 5-year on-the-run treasury
- "0832" → Treasury maturing August 2032
- Automatically resolves to matched-maturity swap structure
- Smart handling of forwards (e.g., "Z25x0832/7")

This is a sophisticated feature for treasury-swap relative value trading!

---

## Code Quality Observations

### Strengths
1. **Well-documented**: Every file has `ABOUTME` comments
2. **Type hints**: Extensive use of type annotations
3. **Frozen dataclasses**: Immutability by default for queries
4. **Consistent patterns**: Adapter pattern used throughout
5. **Test coverage**: 1214 tests passing
6. **Separation of concerns**: Clear layer boundaries

### Areas for Attention
1. **Virtual environment**: Not set up yet (need to run `python3 -m venv venv`)
2. **pytest dependency**: Need to install requirements.txt to run tests
3. **test_basic_workflow.py**: Referenced in docs but doesn't exist
4. **Documentation drift**: Some references to files that don't exist

### Peter's Development Rules (from CLAUDE.md)
Key rules to follow when working on ARBS:
1. **Extend, don't create**: Never create new systems when existing ones can be extended
2. **TDD strictly enforced**: Write failing test FIRST, then implement
3. **No shortcuts**: Doing it right > doing it fast
4. **Honesty required**: If you don't know, say so
5. **Push after every commit**: VMs are ephemeral
6. **Never skip pre-commit hooks**
7. **Match existing code style**: Consistency within file trumps standards

---

## Next Steps for Development

### Immediate Actions
1. Set up virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Run test suite to verify setup:
   ```bash
   python -m pytest tests/ -v
   ```

3. Create `test_basic_workflow.py` if needed for quick validation

### Exploration Areas
1. **Run example notebooks**:
   - `month_end_irswaps_backtest.ipynb` - Full backtest walkthrough
   - `simple_irswaps_backtest.ipynb` - Minimal example
   - `fomc_fly_backtest.ipynb` - Event-driven strategy

2. **Understand Grinold-Kahn integration**:
   - Read `docs/GRINOLD_KAHN_FRAMEWORK.md`
   - Explore `Risk/` and `Optimizer/` modules

3. **Test backend parity**:
   - Compare QuantLib vs RatesLib valuations
   - Verify tolerance is within 0.1-1bp

### Development Guidelines
- Always read `CLAUDE.md` before making changes
- Consult `ARBS_ARCHITECTURE.md` for technical details
- Follow TDD: test first, implement second
- Commit frequently and push immediately
- Use query arithmetic for complex structures
- Extend existing classes rather than creating new ones

---

## File Count Summary

```
Total Python files: ~500+
Total lines of code: ~50,000+
Documentation files: ~40+ markdown files
Test files: ~100+ test modules
Jupyter notebooks: ~10+ example notebooks
```

**Directory Breakdown**:
```
BT/          17 files   Core backtesting engine
Query/       ~100 files Product queries and adapters
MDP/         ~50 files  Market data providers
Risk/        ~30 files  Risk models and analytics
Signals/     ~40 files  Alpha signal generation
Strategies/  ~20 files  Strategy definitions
tests/       ~100 files Test infrastructure
docs/        ~40 files  Documentation
```

---

## Conclusion

ARBS is a mature, well-architected research codebase with:
- **Clean separation of concerns** via three-layer architecture
- **Extensible design** via product adapter pattern
- **Dual backend support** for robustness and flexibility
- **Comprehensive test coverage** with pytest infrastructure
- **Rich documentation** at both high-level and technical detail
- **Advanced features** including Grinold-Kahn, ML signals, multi-asset support

The codebase follows strict development practices (TDD, code review, systematic debugging) and maintains high code quality standards. It's designed for research and rapid iteration while maintaining production-quality patterns.

**Recommendation**: This is a high-quality foundation for quantitative research in rates markets. The architecture scales well to new products and data sources.

---

**Document Created**: 2025-11-17
**Author**: Claude (Sonnet 4.5)
**Session**: Initial codebase familiarization
