# ARBS Class Diagrams - Detailed Reference

This document provides a quick reference guide to the most important class relationships and hierarchies in the ARBS codebase.

## Quick Navigation

- [BT Module Classes](#bt-module-classes)
- [Query Module Classes](#query-module-classes)
- [MDP Module Classes](#mdp-module-classes)
- [Caching Module Classes](#caching-module-classes)
- [Key Relationships Matrix](#key-relationships-matrix)
- [Method Signatures](#method-signatures)

---

## BT Module Classes

### Core Data Classes

| Class | File | Purpose | Key Fields |
|-------|------|---------|-----------|
| `TriggerInfo` | `event.py` | Result of trigger evaluation | `triggered: bool`, `info: Dict[Type, Any]` |
| `Order` | `order.py` | Generated trade order | `timestamp: datetime`, `instrument: _GenericPricable`, `meta: Dict` |
| `Position` | `portfolio.py` | Held position | `instrument: _GenericPricable`, `opened: datetime`, `meta: dict` |
| `Portfolio` | `portfolio.py` | Position tracking | `positions: List[Position]`, `orders_log`, `trades_log` |
| `TimeGrid` | `data_handler.py` | Simulation timestamps | `_states: List[datetime]` |

### Strategy & Execution Classes

| Class | File | Purpose | Key Methods |
|-------|------|---------|-----------|
| `Strategy` | `strategy.py` | Trigger container | `evaluate(now, backtest) -> List[Order]` |
| `Trigger` | `triggers.py` | Trigger wrapper | `has_triggered(state, backtest)`, `get_trigger_times()` |
| `ExecutionEngine` | `execution_engine.py` | Order execution | `execute(orders) -> List[Order]` |
| `EventDrivenBacktest` | `generic_engine.py` | Main orchestrator | `run()`, `mark_to_market()`, `get_strategy_risk()` |

### Trigger Requirements Hierarchy

```
TriggerRequirements (ABC)
├── PeriodicTriggerRequirements
├── IntradayTriggerRequirements
├── MktTriggerRequirements
├── RiskTriggerRequirements
├── AggregateTriggerRequirements
├── NotTriggerRequirements
├── DateTriggerRequirements
├── PortfolioTriggerRequirements
├── MeanReversionTriggerRequirements
├── TradeCountTriggerRequirements
└── EventTriggerRequirements
```

**Common Interface**:
```python
class TriggerRequirements:
    calc_type: str
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo: ...
    def get_trigger_times(self) -> List[dt.time]: ...
```

### Concrete Trigger Classes

Each concrete Trigger class corresponds to a TriggerRequirements:

```
Trigger (ABC)
├── PeriodicTrigger → PeriodicTriggerRequirements
├── IntradayPeriodicTrigger → IntradayTriggerRequirements
├── MktTrigger → MktTriggerRequirements
├── StrategyRiskTrigger → RiskTriggerRequirements
├── AggregateTrigger → AggregateTriggerRequirements
├── NotTrigger → NotTriggerRequirements
├── DateTrigger → DateTriggerRequirements
├── PortfolioTrigger → PortfolioTriggerRequirements
├── MeanReversionTrigger → MeanReversionTriggerRequirements
├── TradeCountTrigger → TradeCountTriggerRequirements
├── EventTrigger → EventTriggerRequirements
└── OrdersGeneratorTrigger → abstract base for time-grid generation
```

### Action Protocol & Implementations

```
Action (Protocol)
├── AddTradeAction
├── AddScaledTradeAction
└── HedgeAction
```

**Protocol Definition**:
```python
class Action(Protocol):
    risk: Optional[str]
    def __call__(self, *, pricer: _GenericPricer, now, backtest, info) -> List[Order]: ...
```

---

## Query Module Classes

### Base Classes

| Class | File | Purpose | Type |
|-------|------|---------|------|
| `_GenericPricable` | `_GenericPricable.py` | Instrument interface | ABC |
| `_GenericPricer` | `_GenericPricer.py` | Pricer interface | ABC with Generic[_GP] |
| `BaseQuery` | `BaseQuery.py` | Generic query | Frozen dataclass (ABC) |
| `ProductAdapter` | `product_adapter.py` | Product-specific adapter | ABC |

### IRS Module

#### Query Hierarchy

```
BaseQuery
└── IRSwapQuery
    ├── structure: IRSwapStructure
    ├── value: Union[IRSwapValue, List[IRSwapValue]]
    ├── tenor: Optional[str]
    ├── effective_date: Optional[date]
    ├── maturity_date: Optional[date]
    ├── is_mms: bool
    ├── curve: Optional[str]
    ├── structure_kwargs: Dict[str, Any]
    ├── value_kwargs: Dict[str, Any]
    └── risk_weight: Optional[float]
```

#### Enumerations

```
IRSwapStructure (Enum)
├── OUTRIGHT (single swap)
├── CURVE (2-leg trade)
├── FLY (3-leg trade)
└── SPREAD

IRSwapValue (Enum)
├── RATE
├── PV01
├── DV01
├── GAMMA_01
├── NPV
├── NOTIONAL
├── CARRY_BPS_RUNNING
├── ROLL_BPS_RUNNING
├── CARRY_AND_ROLL_BPS_RUNNING
├── SPREADOVER
├── MMSS
├── PAR_PAR_ASW
├── TRUE_ASW
├── PROCEEDS_ASW
├── MARKET_ASW
└── CVX_ADJ
```

#### Curve Hierarchy

```
_GenericPricer (ABC) → _IRSwapGenericCurve (ABC)
├── QLIRSwapCurve
│   ├── ql_curve_id: str
│   ├── ql_curve_handle: Any
│   ├── ql_curve_index: Any
│   └── meta_data: Dict
└── RLIRSwapCurve
    ├── rl_curve_id: str
    ├── rl_curve_handle: Any
    ├── fixings: pd.Series
    └── meta_data: Dict
```

#### Function Maps

```
IRSwapStructureFunctionMap
├── curve: _IRSwapGenericCurve
├── _build_outright(): List[_IRSwapGenericObject]
├── _build_curve(): List[_IRSwapGenericObject]
├── _build_fly(): List[_IRSwapGenericObject]
└── apply(structure_id, **kwargs): Tuple[List, List]

IRSwapValueFunctionMap
├── curve: _IRSwapGenericCurve
├── package: List[_IRSwapGenericObject]
├── risk_weights: List[float]
├── _rate(): float
├── _pv01(): float
├── _dv01(): float
├── _gamma(): float
├── _npv(): float
├── _notional(): float
├── _carry_bps_running(): float
├── _rolldown_bps_running(): float
├── _carry_and_roll_bps_running(): float
├── _convexity_adjustment(): float
└── apply(value_id, **kwargs): float
```

#### Adapter

```
ProductAdapter (ABC)
└── IRSProductAdapter
    ├── build_structure_map(pricer_or_curve): IRSwapStructureFunctionMap
    ├── build_value_map(pricer_or_curve, package, weights): IRSwapValueFunctionMap
    └── edit_query(q, pricer_or_curve): IRSwapQuery
```

### FixedRateBonds Module

#### Query

```
BaseQuery
└── FixedRateBondQuery
    ├── structure: FixedRateBondStructure
    ├── value: Union[FixedRateBondValue, List[FixedRateBondValue]]
    ├── cusip: Optional[str]
    ├── maturity_date: Optional[date]
    ├── price: Optional[float]
    ├── structure_kwargs: Dict[str, Any]
    ├── value_kwargs: Dict[str, Any]
    └── risk_weight: Optional[float]
```

#### Enumerations

```
FixedRateBondStructure (Enum)
├── OUTRIGHT
├── CURVE
└── BUTTERFLY

FixedRateBondValue (Enum)
├── PRICE
├── YIELD
├── DV01
├── CONVEXITY
├── DURATION
├── ACCRUED
└── NPV
```

---

## MDP Module Classes

### Base Class

```
MarketDataProvider(ABC, Generic[_GP])
├── __init__(source: str, **kwargs)
├── get_pricer(request: Any) -> _GenericPricer
└── get_data(request: Any) -> _GenericPricer  # deprecated
```

### IRS Providers

#### Main Provider

```
IRSwapsMDP(MarketDataProvider[_GenericPricable])
├── source: str
├── force_refresh_fixings: bool
├── _rl_curve_cache: Optional[_RLCurveCache]
├── get_pricer(request) -> _IRSwapGenericCurve
├── get_data(request) -> Optional[_IRSwapGenericCurve]
├── _get_curve(curve_name, timestamp, kwargs) -> Optional[_IRSwapGenericCurve]
└── bulk_get_data(request) -> Dict[date|datetime, _IRSwapGenericCurve]
```

#### Supported Sources

| Source | Backend | Type | Notes |
|--------|---------|------|-------|
| CME_NY_EOD_LIVE-QL_BASIC | QuantLib | EOD | Official QuantLib curves |
| CME_NY_EOD_LIVE-RL_BASIC | Rateslib | EOD | Rateslib implementation |
| ERIS_EOD_LIVE-RL_BASIC | Rateslib | EOD | Eris futures + swaps |
| SDR_INTRADAY-RL_* | Rateslib | Intraday | Various SOFR/OIS curve builders |
| GSQUANT-RL | Rateslib | EOD | GS Quant data |

### FixedRateBonds Providers

```
FixedRateBondsMDP(MarketDataProvider)
├── get_pricer(request) -> FixedRateBondPricer
└── _get_bond_pricer(cusip, date) -> FixedRateBondPricer
```

#### Data Fetchers

```
_FixedRateBondFetcher (ABC)
├── fetch_prices(cusips, date) -> Dict
└── fetch_yields(cusips, date) -> Dict

Concrete implementations:
├── WSJFetcher
├── PublicDotcomDataFetcher
├── WebullFintechFetcher
└── FedInvestFetcher
```

### Helper Classes

```
_RLCurveCache(ZODBCacheMixin)
├── cache_name: str
├── get_eris_eod_live_rl_basic()
├── bulk_get_eris_eod_live_rl_basic()
└── get_gsquant_rl_basic()

_FixingsCache
└── _fetch_fixings(as_of_date, curve_name, force_refresh) -> pd.Series
```

---

## Caching Module Classes

### Main Mixin

```
ZODBCacheMixin
├── _DB_REGISTRY: Dict[str, _DBHandle]  # class variable
├── _REGISTRY_LOCK: threading.Lock  # class variable
├── _use_btree: bool
├── _force_refresh: bool
├── _z_conns: Dict[str, Tuple[Connection, _DBHandle]]
├── _codec_wrappers: Dict[str, CodecMapping]
├── CACHE_ROOT: Path | None  # class variable
│
├── __init__(use_btree, force_refresh, **kwargs)
├── _open_filestorage(path) -> FileStorage
├── _slug(text, repl) -> str
├── _user_cache_root() -> Path
├── default_cache_path(stem, ext) -> str
├── _acquire_db(path) -> _DBHandle
├── _release_db(path)
├── zodb_open_cache(cache_attr, path, encode, decode, force)
├── batched() -> Generator
├── zodb_commit()
├── close_zodb()
└── diagnostics() -> MappingProxyType
```

### Connection Management

```
_DBHandle
├── db: DB
├── storage: FileStorage
├── refcnt: int
├── _conns: List[Connection]
├── _lock: threading.Lock
├── _pool_cap: int
├── get_conn() -> Connection
├── release_conn(conn)
├── incref()
└── decref()
```

### Codec Wrapper

```
CodecMapping
├── mapping: MutableMapping[Any, Any]
├── encode: Optional[Callable]
├── decode: Optional[Callable]
├── __getitem__(key) -> Any
├── __setitem__(key, value)
├── __contains__(key) -> bool
├── __delitem__(key)
├── __iter__() -> Iterator
├── keys() -> List
├── values() -> List
└── items() -> List
```

### Timeseries Cache

```
TSCatalog(Persistent)
├── shards: OOBTree  # shard -> OOBTree[symbol, SymbolIndex]
└── pointers: OOBTree  # optional logical name mapping

SymbolIndex(Persistent)
└── by_date: OOBTree  # date_str -> OOBTree[part_file, metadata]

TimeSeriesCache
├── cache_dir: str
├── catalog: TSCatalog
├── compression_level: int
├── use_parquet: bool
├── write_timeseries(symbol, df)
├── read_timeseries(symbol, start_date, end_date) -> pd.DataFrame
├── list_symbols() -> List[str]
├── get_metadata(symbol) -> Dict
├── clear_symbol(symbol)
└── vacuum()
```

---

## Key Relationships Matrix

### Inheritance (extends/implements)

```
TriggerRequirements
    ├─ PeriodicTriggerRequirements
    ├─ IntradayTriggerRequirements
    ├─ MktTriggerRequirements
    ├─ RiskTriggerRequirements
    ├─ AggregateTriggerRequirements
    ├─ NotTriggerRequirements
    ├─ DateTriggerRequirements
    ├─ PortfolioTriggerRequirements
    ├─ MeanReversionTriggerRequirements
    ├─ TradeCountTriggerRequirements
    └─ EventTriggerRequirements

Trigger
    ├─ PeriodicTrigger
    ├─ IntradayPeriodicTrigger
    ├─ MktTrigger
    ├─ StrategyRiskTrigger
    ├─ AggregateTrigger
    ├─ NotTrigger
    ├─ DateTrigger
    ├─ PortfolioTrigger
    ├─ MeanReversionTrigger
    ├─ TradeCountTrigger
    ├─ EventTrigger
    └─ OrdersGeneratorTrigger

_GenericPricer
    ├─ _IRSwapGenericCurve
    │   ├─ QLIRSwapCurve
    │   └─ RLIRSwapCurve
    └─ (other product pricers)

BaseQuery
    ├─ IRSwapQuery
    └─ FixedRateBondQuery

ProductAdapter
    ├─ IRSProductAdapter
    └─ FRBProductAdapter

MarketDataProvider
    ├─ IRSwapsMDP
    ├─ FixedRateBondsMDP
    └─ IRSwapSpreadsMDP

ZODBCacheMixin
    └─ (mixed into other classes)

Persistent
    ├─ TSCatalog
    └─ SymbolIndex
```

### Composition (contains)

```
EventDrivenBacktest
    ├─ TimeGrid
    ├─ Strategy
    ├─ ExecutionEngine
    ├─ Portfolio
    ├─ MarketDataProvider (optional)
    └─ Dict (cache, mtm_history)

Strategy
    └─ List[Trigger]

Trigger
    ├─ TriggerRequirements
    └─ List[Action]

Portfolio
    ├─ List[Position]
    ├─ List (orders_log)
    └─ List (trades_log)

Position
    └─ Order (via instrument, opened)

_DBHandle
    ├─ DB
    └─ FileStorage

ZODBCacheMixin
    ├─ _DBHandle (via registry)
    └─ CodecMapping

TimeSeriesCache
    ├─ TSCatalog
    └─ FileStorage
```

### Usage/Delegation

```
BaseQuery
    → ProductAdapter (via registry lookup)

ProductAdapter
    → StructureFunctionMap
    → ValueFunctionMap

EventDrivenBacktest
    → Trigger.has_triggered()
    → Action.__call__()
    → ExecutionEngine.execute()

Trigger
    → TriggerRequirements.has_triggered()
```

---

## Method Signatures

### EventDrivenBacktest

```python
class EventDrivenBacktest:
    def run() -> None:
        """Main simulation loop"""
        
    def mark_to_market(now: datetime) -> float:
        """Calculate portfolio MTM"""
        
    def get_strategy_risk(name: str) -> float:
        """Query specific risk measure"""
        
    def _current_pricer() -> _GenericPricer:
        """Get cached pricer"""
        
    def _resolve_pricer_for(now: datetime) -> _GenericPricer:
        """Resolve or fetch pricer for timestamp"""
```

### Strategy

```python
class Strategy:
    def evaluate(now: datetime, backtest) -> List[Order]:
        """Evaluate all triggers, return orders"""
```

### Trigger

```python
class Trigger:
    def has_triggered(state: datetime, backtest=None) -> TriggerInfo:
        """Delegate to TriggerRequirements"""
        
    def get_trigger_times() -> List[time]:
        """Get intraday trigger times"""
```

### BaseQuery

```python
class BaseQuery(ABC):
    def build_mdp_request(now: datetime) -> Dict[str, Any]:
        """Build request for MDP.get_pricer()"""
        
    def resolve_package(pricer_or_curve, **hints) -> Tuple[List, List]:
        """Get pricables and weights via adapter"""
        
    def build_value_map(pricer_or_curve, package, weights) -> Any:
        """Get value function map via adapter"""
        
    @abstractmethod
    def return_query() -> Union[BaseQuery, List[BaseQuery]]:
        """Expand if multi-valued, else return [self]"""
        
    @abstractmethod
    def col_name(cube_name=None) -> str:
        """Human-friendly label"""
        
    @abstractmethod
    def eval_expression(cube_name=None) -> str:
        """Expression for data cube"""
```

### IRSwapQuery

```python
class IRSwapQuery(BaseQuery):
    def __post_init__():
        """Normalize fields, validate structure"""
        
    def resolve_query(ref_dt, pricer_or_curve) -> IRSwapQuery:
        """Resolve tenor/dates via adapter"""
```

### MarketDataProvider

```python
class MarketDataProvider(ABC, Generic[_GP]):
    def get_pricer(request: Any) -> _GenericPricer:
        """Main interface"""
```

### ZODBCacheMixin

```python
class ZODBCacheMixin:
    def zodb_open_cache(cache_attr, path, encode=None, decode=None, force=None):
        """Open ZODB cache as attribute"""
        
    @contextmanager
    def batched():
        """Transactional batching context"""
        
    def zodb_commit():
        """Explicit commit"""
        
    def close_zodb():
        """Close all open caches"""
```

---

## Type Annotations Guide

### Generic Types Used

```python
_GP = TypeVar("_GP", bound=_GenericPricable)
T = TypeVar("T", bound="ZODBCacheMixin")

# Generic Pricer is Generic[_GP]
class _GenericPricer(ABC, Generic[_GP]):
    def npv(self, instrument: _GP, /) -> float: ...

# MarketDataProvider returns Generic[_GP]
class MarketDataProvider(ABC, Generic[_GP]):
    def get_pricer(self, request: Any) -> _GP: ...
```

### Common Callables

```python
RiskFn = Callable[[Portfolio, _GenericPricer], Dict[str, float]]
RequestBuilder = Callable[[datetime], Dict[str, Any]]
EncodeFn = Callable[[Any], Any]
DecodeFn = Callable[[Any], Any]
```

---

## File Organization

```
ARBS/
├── BT/
│   ├── event.py            # TriggerInfo
│   ├── order.py            # Order
│   ├── strategy.py         # Strategy
│   ├── triggers.py         # Trigger, TriggerRequirements, concrete classes
│   ├── actions.py          # Action, AddTradeAction, HedgeAction
│   ├── portfolio.py        # Portfolio, Position
│   ├── data_handler.py     # TimeGrid
│   ├── execution_engine.py # ExecutionEngine
│   └── generic_engine.py   # EventDrivenBacktest
│
├── Query/
│   ├── Base/
│   │   ├── _GenericPricable.py
│   │   ├── _GenericPricer.py
│   │   ├── BaseQuery.py
│   │   └── product_adapter.py
│   │
│   ├── IRSwaps/
│   │   ├── IRSwapQuery.py
│   │   ├── IRSwapValue.py
│   │   ├── IRSwapStructure.py
│   │   ├── _IRSwapGenericCurve.py
│   │   ├── _IRSwapGenericObject.py
│   │   ├── adapter.py       # IRSProductAdapter
│   │   └── backends/
│   │       ├── quantlib/    # QLIRSwapCurve
│   │       └── rateslib/    # RLIRSwapCurve
│   │
│   └── FixedRateBonds/
│       ├── FixedRateBondQuery.py
│       ├── FixedRateBondValue.py
│       ├── FixedRateBondStructure.py
│       ├── adapter.py       # FRBProductAdapter
│       └── backends/
│           ├── quantlib/    # QLFixedRateBondPricer
│           └── rateslib/    # RLFixedRateBondPricer
│
├── MDP/
│   ├── MarketDataProvider.py
│   │
│   ├── IRSwaps/
│   │   ├── IRSwapsMDP.py
│   │   ├── CME_NY_EOD_LIVE/  # Fetchers for different data sources
│   │   ├── SDR_INTRADAY/     # Curve builders
│   │   ├── GSQUANT/
│   │   └── fixings_cache/
│   │
│   └── FixedRateBonds/
│       ├── FixedRateBondsMDP.py
│       └── (various Fetchers)
│
└── Caching/
    ├── ZODBCacheMixin.py
    ├── CodecMapping.py
    ├── timeseries_cache.py
    └── utils.py
```

