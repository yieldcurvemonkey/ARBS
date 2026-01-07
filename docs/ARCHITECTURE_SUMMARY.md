# ARBS Architecture Summary - Quick Reference

## Overview

The ARBS (Arbitrage System) codebase is organized into several key modules implementing a sophisticated event-driven backtesting framework with pluggable pricing engines and market data providers.

### Core Principles

1. **Product-Agnostic**: Uses Adapter Pattern to support multiple product types (IRS, FixedRateBonds)
2. **Generic Pricing**: Abstract _GenericPricer and _GenericPricable interfaces with concrete implementations
3. **Event-Driven**: TimeGrid-based event loop with flexible trigger system
4. **Persistent Caching**: ZODB mixin for efficient caching of market data and computations
5. **Composable**: Action, Trigger, and Strategy composition for complex trading logic

---

## Module Overview

### 1. BT (Backtesting) Module

**Purpose**: Event-driven backtesting engine with trigger-action framework

**Key Classes**:
- `EventDrivenBacktest`: Main orchestrator
- `TimeGrid`: Iterator over simulation timestamps
- `Strategy`: Container for triggers
- `Trigger` + `TriggerRequirements`: Flexible trigger system (10+ concrete types)
- `Action`: Action protocol with 3 implementations
- `Portfolio`: Position tracking
- `ExecutionEngine`: Order execution (naive immediate-fill)

**Architecture**:
```
TimeGrid → EventDrivenBacktest.run()
    ↓ (for each timestamp)
    Strategy.evaluate()
    ↓
    Trigger.has_triggered()
    ↓
    TriggerRequirements (checks market data, risk, dates, etc.)
    ↓
    Action.__call__() (generates Orders)
    ↓
    ExecutionEngine.execute()
    ↓
    Portfolio.add() (adds Positions)
    ↓
    mark_to_market() & risk_fn()
```

**Trigger Types** (10 concrete implementations):
- `PeriodicTrigger`: On specific dates
- `IntradayPeriodicTrigger`: At specific times
- `MktTrigger`: Market signal + operator
- `StrategyRiskTrigger`: Risk threshold
- `DateTrigger`: Check specific dates
- `PortfolioTrigger`: Predicate on portfolio
- `MeanReversionTrigger`: Z-score based
- `TradeCountTrigger`: Count in lookback window
- `EventTrigger`: Macro calendar membership
- `AggregateTrigger`/`NotTrigger`: Boolean logic

**Action Types** (3 implementations):
- `AddTradeAction`: Basic order generation
- `AddScaledTradeAction`: Dynamic notional from trigger info
- `HedgeAction`: Hedge position based on risk

---

### 2. Query Module

**Purpose**: Product-agnostic pricing framework using Adapter Pattern

**Key Abstractions**:
- `_GenericPricable`: Base interface for all priceable instruments
- `_GenericPricer`: Base interface for all pricers
- `BaseQuery`: Generic product query (frozen dataclass)
- `ProductAdapter`: Registry-based adapter for product-specific logic

**Adapter Pattern Flow**:
```
BaseQuery (product-agnostic)
    ↓ get_adapter(product)
    ↓
ProductAdapter
    ├─ build_structure_map() → StructureFunctionMap
    ├─ build_value_map() → ValueFunctionMap
    └─ edit_query() → normalized Query
```

#### 2.1 IRS (Interest Rate Swaps) Submodule

**Query**: `IRSwapQuery(BaseQuery)`
- `structure`: OUTRIGHT, CURVE, FLY, SPREAD
- `value`: RATE, PV01, DV01, NPV, NOTIONAL, etc. (16 types)
- Fields: tenor, effective_date, maturity_date, curve, risk_weight

**Curves** (Generic + Implementations):
- `_IRSwapGenericCurve` (ABC): Protocol for all curves
  - `QLIRSwapCurve`: QuantLib-based
  - `RLIRSwapCurve`: Rateslib-based

**Structure Mapping**:
- `IRSwapStructureFunctionMap`:
  - OUTRIGHT → single swap
  - CURVE → 2-leg trade (e.g., 2Y5Y butterfly front leg)
  - FLY → 3-leg trade (e.g., 2s5s10s butterfly)

**Value Mapping**:
- `IRSwapValueFunctionMap`:
  - RATE: Fair rate
  - PV01: Delta (price value of 1bp move)
  - DV01: Dollar value of 1bp move
  - GAMMA_01: Convexity
  - NPV: Net present value
  - CARRY_BPS_RUNNING: Carry projection
  - CONVEXITY_ADJ: STIR futures convexity

#### 2.2 FixedRateBonds Submodule

**Query**: `FixedRateBondQuery(BaseQuery)`
- `structure`: OUTRIGHT, CURVE, BUTTERFLY
- `value`: PRICE, YIELD, DV01, CONVEXITY, DURATION, ACCRUED, NPV
- Fields: cusip, maturity_date, price

**Pricers**:
- `QLFixedRateBondPricer`: QuantLib-based
- `RLFixedRateBondPricer`: Rateslib-based

---

### 3. MDP (Market Data Provider) Module

**Purpose**: Abstraction layer for market data sources

**Key Classes**:
- `MarketDataProvider(ABC, Generic[_GP])`: Base class
  - `get_pricer(request) → _GenericPricer`
  - `get_data(request) → _GenericPricer` (deprecated alias)

#### 3.1 IRSwapsMDP

**Sources**:
- CME_NY_EOD_LIVE (QuantLib/Rateslib)
- ERIS_EOD_LIVE (Rateslib)
- SDR_INTRADAY (multiple Rateslib curve builders)
- GSQUANT (Rateslib via GS Quant)

**Features**:
- Curve building from market data (CME futures, swaps)
- Fixings management
- Bulk operations for backtesting
- Caching via `_RLCurveCache`

#### 3.2 FixedRateBondsMDP

**Data Sources**:
- `WSJFetcher`: Wall Street Journal
- `PublicDotcomDataFetcher`: Public.com
- `WebullFintechFetcher`: Webull
- `FedInvestFetcher`: Federal Reserve data

#### 3.3 IRSwapSpreadsMDP

**Purpose**: Spread data for basis trades

---

### 4. Caching Module

**Purpose**: Persistent storage and caching using ZODB

#### 4.1 ZODBCacheMixin

**Mixin for Classes Needing Persistence**:

```python
class MyCache(ZODBCacheMixin):
    def __init__(self):
        super().__init__(use_btree=True, force_refresh=False)
        self.zodb_open_cache(
            cache_attr="my_cache",
            path=self.default_cache_path("my_cache_name")
        )

# Usage:
obj = MyCache()
obj.my_cache["key"] = value  # Automatic persistence
obj.zodb_commit()
obj.close_zodb()
```

**Features**:
- Connection pooling
- Reference counting for DB lifecycle
- Optional codec for custom encode/decode
- Thread-safe operations
- Context manager support (batched)

**Storage Backends**:
- FileStorage: Persistent file-based
- DemoStorage: Memory-based (fallback for read-only)

#### 4.2 TimeSeriesCache

**Persistent Time Series Storage**:
- Parquet-based partitioned storage
- ZODB catalog for metadata
- Symbol-date sharding
- Efficient querying by date range

---

## Data Flow Examples

### Example 1: Simple IRS Trade

```python
from BT.generic_engine import EventDrivenBacktest
from BT.strategy import Strategy
from BT.triggers import PeriodicTrigger, PeriodicTriggerRequirements
from BT.actions import AddTradeAction
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# 1. Create query
q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.PV01,
    tenor="5Y",
    curve="USD-SOFR-1D"
)

# 2. Create action (builds trade via query)
action = AddTradeAction(
    build_kwargs=dict(tenor="5Y", notional=1e6)
)

# 3. Create trigger (fires on date)
trig = PeriodicTrigger(
    trigger_requirements=PeriodicTriggerRequirements(
        dates=[datetime.date(2024, 1, 15)]
    ),
    actions=[action]
)

# 4. Create strategy
strat = Strategy(name="test", triggers=[trig])

# 5. Create backtest
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-QL_BASIC")
bt = EventDrivenBacktest(
    time_grid=TimeGrid(dates),
    mdp=mdp,
    mdp_request_builder=lambda dt: {"curve_name": "USD-SOFR-1D", "timestamp": dt.date()},
    strategy=strat
)

# 6. Run
bt.run()

# 7. Access results
print(bt.portfolio.positions)
print(bt.mtm_history)
```

### Example 2: Risk-Based Hedging

```python
# Trigger on risk threshold
risk_trig = StrategyRiskTrigger(
    trigger_requirements=RiskTriggerRequirements(
        risk="pv01",
        op=operator.gt,
        threshold=1000.0  # Hedge if PV01 > 1000
    ),
    actions=[
        HedgeAction(
            risk_name="pv01",
            hedge_builder=lambda pricer, exp: pricer.build_pricable(
                tenor="2Y",
                notional=exp
            )
        )
    ]
)

strat = Strategy(name="hedge", triggers=[risk_trig])
```

### Example 3: Mean Reversion Trade

```python
import statistics as stats

# Data series
returns = pd.Series([...])

# Trigger on z-score
mean_rev_trig = MeanReversionTrigger(
    trigger_requirements=MeanReversionTriggerRequirements(
        fetch=lambda dt: returns.loc[dt],
        lookback=20,
        z_entry=2.0
    ),
    actions=[
        AddScaledTradeAction(
            build_kwargs=dict(tenor="5Y"),
            scale_key="scaling"
            # The "scaling" value comes from TriggerInfo.info
        )
    ]
)
```

---

## Design Patterns Used

### 1. Adapter Pattern (ProductAdapter)

Allows new product types without changing core backtester:

```python
class NewProductAdapter(ProductAdapter):
    def build_structure_map(self, pricer_or_curve):
        return NewStructureMap(...)
    
    def build_value_map(self, pricer_or_curve, package, weights):
        return NewValueMap(...)

register_product("NewProduct", NewProductAdapter)
```

### 2. Strategy Pattern (Trigger + TriggerRequirements)

Encapsulates trigger logic:

```python
class Trigger:
    trigger_requirements: TriggerRequirements
    
    def has_triggered(self, state, backtest):
        return self.trigger_requirements.has_triggered(state, backtest)
```

### 3. Factory Pattern (ProductAdapter Registry)

```python
adapter_cls = get_adapter(query.product)
adapter = adapter_cls()
struct_map = adapter.build_structure_map(pricer)
```

### 4. Mixin Pattern (ZODBCacheMixin)

Classes inherit caching without explicit dependency:

```python
class CachedProvider(MarketDataProvider, ZODBCacheMixin):
    pass
```

### 5. Template Method (BaseQuery)

Abstract methods implemented by concrete queries:

```python
class BaseQuery(ABC):
    @abstractmethod
    def return_query(self) -> Union[BaseQuery, List[BaseQuery]]: ...
    
    @abstractmethod
    def col_name(self, cube_name) -> str: ...
```

---

## Extension Points

### Add a New Product Type

1. Create Query class inheriting from BaseQuery
2. Create ProductAdapter subclass
3. Register with `register_product()`

### Add a New Market Data Source

1. Subclass MarketDataProvider
2. Implement get_pricer() method
3. Return appropriate Pricer implementation

### Add a New Trigger Type

1. Create TriggerRequirements subclass
2. Create Trigger subclass
3. Implement has_triggered() logic

### Add Caching to a Class

1. Inherit from ZODBCacheMixin
2. Call zodb_open_cache() in __init__
3. Use like normal dict

---

## Performance Considerations

### Caching

- Use ZODB for persistent curve/pricing data
- Implement codec wrappers for compression
- Connection pooling minimizes DB overhead
- Bulk operations for backtesting optimization

### Pricing

- Cached pricers in EventDrivenBacktest.cache
- Single pricer per timestamp (unless changed via MDP)
- Package-based pricing (multiple legs at once)

### Trigger Evaluation

- Lightweight trigger checks per timestamp
- TriggerRequirements delegates heavy computation
- TriggerInfo.info passes contextual data to actions

---

## Testing Strategy

### Unit Testing

Test each TriggerRequirements type independently

### Integration Testing

Test full backtest flow with:
- Simple linear strategy
- Multiple triggers
- Multiple products

### Validation

Compare results against:
- Manual calculations
- Reference implementations
- Historical data

---

## Troubleshooting

### Query Not Resolving

- Check ProductAdapter registration
- Verify market_request is complete
- Ensure pricer/curve is correct type

### Trigger Not Firing

- Check TriggerRequirements logic
- Verify fetch functions return data
- Check date/time formats

### Performance Issues

- Profile caching usage
- Check connection pool size
- Validate query complexity

---

## Related Documentation

- `CLASS_DIAGRAMS_COMPREHENSIVE.md` - Full Mermaid diagrams
- `CACHING_ARCHITECTURE_DIAGRAMS.md` - Detailed caching info
- `DOCUMENTATION_INDEX.md` - All documentation index

