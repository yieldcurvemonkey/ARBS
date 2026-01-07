# ARBS Class Diagrams - Complete Index

This index provides navigation to all comprehensive class diagram and architecture documentation created for the ARBS codebase.

## Documents Created

### 1. CLASS_DIAGRAMS_COMPREHENSIVE.md (Main Document)

**Contents**:
- Complete Mermaid class diagrams for all major modules
- 8 major diagram sections covering:
  1. BT Module - Event-driven backtesting with all trigger types and actions
  2. Query Module - Product-agnostic pricing architecture (Base + IRS + FRB)
  3. MDP Module - Market data provider hierarchy
  4. Caching Module - ZODB mixin patterns and timeseries caching
  5. Data Flow Architecture - Complete backtesting flow diagrams
  6. Query Resolution Flow - Step-by-step pricing flow
  7. Trigger and Action Execution Flow - How triggers fire and execute
  8. Adapter Pattern Diagram - Extensibility patterns
  9. Mixin and Composition Patterns - Pattern implementations
  10. Summary Table - Complete relationships matrix

**Best for**: Visual learners, understanding overall architecture, seeing all relationships

### 2. ARCHITECTURE_SUMMARY.md (Quick Reference)

**Contents**:
- Overview of core principles
- Detailed module breakdowns:
  - BT (Backtesting) Module
  - Query Module (IRS + FixedRateBonds)
  - MDP (Market Data Provider) Module
  - Caching Module
- Data flow examples with code snippets
- Design patterns used in codebase
- Extension points for adding new features
- Performance considerations
- Testing strategy
- Troubleshooting guide

**Best for**: Quick lookups, understanding how to use/extend system, pragmatic reference

### 3. CLASS_DIAGRAMS_REFERENCE.md (Detailed Reference)

**Contents**:
- Quick navigation index
- BT Module Classes - detailed tables and hierarchies
- Query Module Classes - base classes, IRS/FRB hierarchies, enumerations
- MDP Module Classes - provider hierarchy, data sources
- Caching Module Classes - mixin, connection management, codec
- Key Relationships Matrix - inheritance, composition, delegation
- Method Signatures - important class methods
- Type Annotations Guide - Generic types and callables
- File Organization - directory structure with file descriptions

**Best for**: Detailed lookups, method signatures, file locations

## Quick Start Guide

### For Understanding the Architecture

1. Start with **ARCHITECTURE_SUMMARY.md** - Read "Module Overview"
2. Then review relevant diagram in **CLASS_DIAGRAMS_COMPREHENSIVE.md**
3. Use **CLASS_DIAGRAMS_REFERENCE.md** for specific class details

### For Implementation

1. Check **ARCHITECTURE_SUMMARY.md** - Read "Extension Points"
2. Look at example code in "Data Flow Examples"
3. Use **CLASS_DIAGRAMS_REFERENCE.md** for method signatures
4. Reference the comprehensive diagrams for relationship details

### For Debugging

1. Check **ARCHITECTURE_SUMMARY.md** - Read "Troubleshooting"
2. Review data flow in **CLASS_DIAGRAMS_COMPREHENSIVE.md**
3. Look up class details in **CLASS_DIAGRAMS_REFERENCE.md**

## Module Navigation

### BT (Backtesting) Module

- **Primary Document**: CLASS_DIAGRAMS_COMPREHENSIVE.md § 1
- **Quick Reference**: ARCHITECTURE_SUMMARY.md § "BT Module"
- **Detailed**: CLASS_DIAGRAMS_REFERENCE.md § "BT Module Classes"

**Key Classes**:
- `EventDrivenBacktest`: Main orchestrator
- `Trigger` + `TriggerRequirements`: Flexible trigger system (10+ types)
- `Action`: Action protocol (3 implementations)
- `Strategy`: Trigger container
- `Portfolio`: Position tracking

### Query Module

- **Primary Document**: CLASS_DIAGRAMS_COMPREHENSIVE.md § 2 & 2.2 & 2.3
- **Quick Reference**: ARCHITECTURE_SUMMARY.md § "Query Module"
- **Detailed**: CLASS_DIAGRAMS_REFERENCE.md § "Query Module Classes"

**Key Classes**:
- `_GenericPricable` / `_GenericPricer`: Core interfaces
- `BaseQuery`: Generic product query
- `ProductAdapter`: Product-specific adapter registry
- `IRSwapQuery`: Interest rate swaps
- `FixedRateBondQuery`: Fixed rate bonds

**IRS Submodule**:
- `IRSwapStructure` (enum): OUTRIGHT, CURVE, FLY, SPREAD
- `IRSwapValue` (enum): 16+ valuation metrics
- `_IRSwapGenericCurve` (ABC)
  - `QLIRSwapCurve`: QuantLib implementation
  - `RLIRSwapCurve`: Rateslib implementation
- `IRSwapStructureFunctionMap`: Structure mapping
- `IRSwapValueFunctionMap`: Value computation
- `IRSProductAdapter`: IRS-specific adapter

**FRB Submodule**:
- `FixedRateBondStructure` (enum)
- `FixedRateBondValue` (enum)
- `FixedRateBondQuery`
- Similar pricer and adapter hierarchy

### MDP Module

- **Primary Document**: CLASS_DIAGRAMS_COMPREHENSIVE.md § 3
- **Quick Reference**: ARCHITECTURE_SUMMARY.md § "MDP Module"
- **Detailed**: CLASS_DIAGRAMS_REFERENCE.md § "MDP Module Classes"

**Key Classes**:
- `MarketDataProvider` (ABC): Base class
- `IRSwapsMDP`: Curve building from market data
- `FixedRateBondsMDP`: Bond pricing data
- `_RLCurveCache`: Rateslib curve caching
- Data fetchers (WSJFetcher, WebullFetcher, etc.)

### Caching Module

- **Primary Document**: CLASS_DIAGRAMS_COMPREHENSIVE.md § 4
- **Quick Reference**: ARCHITECTURE_SUMMARY.md § "Caching Module"
- **Detailed**: CLASS_DIAGRAMS_REFERENCE.md § "Caching Module Classes"

**Key Classes**:
- `ZODBCacheMixin`: Mixin for persistent caching
- `_DBHandle`: Connection pooling management
- `CodecMapping`: Optional encode/decode wrapper
- `TSCatalog` / `SymbolIndex`: Timeseries indexing
- `TimeSeriesCache`: Parquet-based timeseries storage

## Key Relationships

### Inheritance Hierarchies

See **CLASS_DIAGRAMS_REFERENCE.md** § "Key Relationships Matrix" for complete trees.

**Main hierarchies**:
- TriggerRequirements (10 implementations)
- Trigger (11 implementations)
- _GenericPricer (multiple product implementations)
- BaseQuery (product-specific implementations)
- ProductAdapter (product-specific implementations)
- MarketDataProvider (data source implementations)

### Design Patterns

All patterns documented in **ARCHITECTURE_SUMMARY.md** § "Design Patterns Used":
1. Adapter Pattern (ProductAdapter)
2. Strategy Pattern (Trigger + TriggerRequirements)
3. Factory Pattern (ProductAdapter Registry)
4. Mixin Pattern (ZODBCacheMixin)
5. Template Method (BaseQuery)

## Data Flow Examples

### Complete Backtest Flow

```
TimeGrid → EventDrivenBacktest.run()
    ↓ (for each timestamp)
    Strategy.evaluate()
    ↓
    Trigger.has_triggered()
    ↓
    TriggerRequirements (10+ types check)
    ↓
    Action.__call__() (generate Orders)
    ↓
    ExecutionEngine.execute()
    ↓
    Portfolio.add() (track positions)
    ↓
    mark_to_market() & risk_fn()
```

**Visual**: CLASS_DIAGRAMS_COMPREHENSIVE.md § 5.1
**Details**: ARCHITECTURE_SUMMARY.md § "Data Flow Examples" or CLASS_DIAGRAMS_COMPREHENSIVE.md § 5

### Query Resolution Flow

```
IRSwapQuery
    ↓ __post_init__()
    Normalized Query
    ↓ build_mdp_request()
    MDP Request
    ↓ IRSwapsMDP.get_pricer()
    QLIRSwapCurve / RLIRSwapCurve
    ↓ resolve_package()
    IRSwapStructureFunctionMap.apply()
    ↓ builds legs
    Package + weights
    ↓ build_value_map()
    IRSwapValueFunctionMap
    ↓ apply()
    Value result
```

**Visual**: CLASS_DIAGRAMS_COMPREHENSIVE.md § 5.2
**Code Example**: ARCHITECTURE_SUMMARY.md § "Example 1: Simple IRS Trade"

## Trigger Types Reference

All 10+ trigger requirements with use cases:

| Trigger | Requirements | Use Case |
|---------|--------------|----------|
| PeriodicTrigger | PeriodicTriggerRequirements | Fire on specific calendar dates |
| IntradayPeriodicTrigger | IntradayTriggerRequirements | Fire at specific times |
| MktTrigger | MktTriggerRequirements | Market signal comparison |
| StrategyRiskTrigger | RiskTriggerRequirements | Risk threshold exceeded |
| DateTrigger | DateTriggerRequirements | Check specific dates |
| PortfolioTrigger | PortfolioTriggerRequirements | Portfolio predicate |
| MeanReversionTrigger | MeanReversionTriggerRequirements | Z-score based entry |
| TradeCountTrigger | TradeCountTriggerRequirements | Trade count in window |
| EventTrigger | EventTriggerRequirements | Macro calendar events |
| AggregateTrigger | AggregateTriggerRequirements | AND/OR multiple triggers |
| NotTrigger | NotTriggerRequirements | Negate another trigger |
| OrdersGeneratorTrigger | (custom) | Time-grid based order generation |

**Reference**: CLASS_DIAGRAMS_REFERENCE.md § "BT Module Classes" - Trigger Requirements Hierarchy

## Action Types Reference

| Action | Purpose | Input | Output |
|--------|---------|-------|--------|
| AddTradeAction | Generate fixed trade order | build_kwargs dict | List[Order] |
| AddScaledTradeAction | Dynamic notional from trigger info | build_kwargs + trigger info | List[Order] with scaling |
| HedgeAction | Hedge based on risk exposure | risk_name + hedge_builder | List[Order] for hedge |

**Code Examples**: ARCHITECTURE_SUMMARY.md § "Data Flow Examples"

## File Organization

Complete file structure in **CLASS_DIAGRAMS_REFERENCE.md** § "File Organization"

### BT Module
- event.py, order.py, strategy.py
- triggers.py (all 10+ implementations)
- actions.py (3 implementations)
- portfolio.py, data_handler.py
- execution_engine.py, generic_engine.py

### Query Module
- Base/: _GenericPricable.py, _GenericPricer.py, BaseQuery.py, product_adapter.py
- IRSwaps/: IRSwapQuery.py, IRSwapValue.py, IRSwapStructure.py, adapter.py, backends/
- FixedRateBonds/: FixedRateBondQuery.py, adapter.py, backends/

### MDP Module
- MarketDataProvider.py
- IRSwaps/: IRSwapsMDP.py, CME_NY_EOD_LIVE/, SDR_INTRADAY/, GSQUANT/, fixings_cache/
- FixedRateBonds/: FixedRateBondsMDP.py, fetchers/

### Caching Module
- ZODBCacheMixin.py, CodecMapping.py
- timeseries_cache.py, utils.py

## Type System

### Generic Types

```python
_GP = TypeVar("_GP", bound=_GenericPricable)
_GenericPricer(ABC, Generic[_GP])
MarketDataProvider(ABC, Generic[_GP])
```

### Protocol Types

```python
Action (Protocol):
    risk: Optional[str]
    def __call__(...) -> List[Order]: ...
```

**Reference**: CLASS_DIAGRAMS_REFERENCE.md § "Type Annotations Guide"

## Design Patterns

### Adapter Pattern (ProductAdapter)

Used for product extensibility:
- IRSProductAdapter: Interest rate swaps
- FRBProductAdapter: Fixed rate bonds
- Extensible: Add new product via new adapter + registration

### Strategy Pattern (Trigger + TriggerRequirements)

Separates trigger interface (Trigger) from logic (TriggerRequirements)
- 10+ concrete requirements
- Each wrapped in corresponding Trigger

### Mixin Pattern (ZODBCacheMixin)

Adds persistence to any class without explicit dependency
- Used by _RLCurveCache and other caching classes
- Transparent persistent dict-like interface

## Performance Characteristics

### Backtesting Speed

- TimeGrid iteration: O(n) for n timestamps
- Trigger evaluation: O(m) for m triggers per timestamp
- Portfolio tracking: O(p) for p positions

### Caching

- ZODB connection pooling: Configurable pool_size (default 7)
- Curve caching in EventDrivenBacktest: Single pricer per timestamp
- _RLCurveCache: Disk-based caching for expensive curve builds

### Query Resolution

- Adapter lookup: O(1) via registry
- Structure mapping: O(k) for k legs
- Value computation: O(k) for k legs

## Related Documentation

In ARBS root:
- `CACHING_ARCHITECTURE_DIAGRAMS.md` - Detailed caching patterns
- `DOCUMENTATION_INDEX.md` - All documentation
- Various notebook guides and tutorials

## Version History

- **2024-11-10**: Initial comprehensive documentation created
  - CLASS_DIAGRAMS_COMPREHENSIVE.md: 8 major sections, 10+ diagrams
  - ARCHITECTURE_SUMMARY.md: Quick reference and extension guide
  - CLASS_DIAGRAMS_REFERENCE.md: Detailed class reference
  - This index document

## Contact & Questions

For questions about:
- Architecture: See ARCHITECTURE_SUMMARY.md
- Specific classes: See CLASS_DIAGRAMS_REFERENCE.md
- Visual relationships: See CLASS_DIAGRAMS_COMPREHENSIVE.md
- Implementation: See code in /home/user/ARBS/ modules

