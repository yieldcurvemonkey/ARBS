# BT (Backtesting) Module - Comprehensive Documentation

## Table of Contents
1. [Overview](#overview)
2. [Architecture & Design Patterns](#architecture--design-patterns)
3. [Core Classes & Components](#core-classes--components)
4. [Event Loop & Execution Flow](#event-loop--execution-flow)
5. [Trigger System](#trigger-system)
6. [Action System](#action-system)
7. [Strategy Pattern](#strategy-pattern)
8. [Portfolio Management](#portfolio-management)
9. [P&L Tracking](#pl-tracking)
10. [QueryDrivenBacktest vs EventDrivenBacktest](#querydriven-vs-eventdriven)
11. [Time Grid Management](#time-grid-management)
12. [Order Execution](#order-execution)
13. [Public API Reference](#public-api-reference)
14. [Integration Points](#integration-points)
15. [Usage Examples](#usage-examples)

---

## Overview

The BT module is a sophisticated backtesting engine designed for quantitative trading strategies, with particular emphasis on interest rate swaps and fixed income derivatives. It implements an event-driven architecture that decouples strategy logic (when/what to trade) from execution details (how trades are filled).

### Key Features
- **Event-driven architecture**: Process market data and events at discrete timestamps
- **Dual execution modes**: EventDrivenBacktest for generic instruments, QueryDrivenBacktest for complex products
- **Composable triggers**: Build complex trading conditions from simple building blocks
- **Flexible actions**: Standardized way to generate orders from trading conditions
- **Realistic P&L tracking**: Mark-to-market accounting with realized/unrealized gains
- **Portfolio tracking**: Complete ledger of all trades and orders with metadata

### Design Philosophy
The module follows the **Strategy Pattern** heavily, allowing traders to define:
1. **When to trade** (Triggers)
2. **What to trade** (Actions)
3. **How to execute** (ExecutionEngine)

This separation of concerns enables rapid iteration and composition of complex strategies from simple, reusable components.

---

## Architecture & Design Patterns

### 1. Strategy Pattern
The core design uses a hierarchical structure:
```
Strategy
├── Triggers (when to act)
│   ├── TriggerRequirements (condition evaluation)
│   └── Actions (what to do when triggered)
```

### 2. Plug-in Architecture
All components are designed to be replaceable:
- **Execution Engine**: Customizable order filling logic
- **Risk Function**: User-defined P&L and risk calculations
- **Pricer Source**: Either static or dynamic (MDP) pricing

### 3. Request/Response Pattern
The backtest uses a clean request/response model:
- **TimeGrid** → sequence of evaluation points
- **Strategy.evaluate()** → generates Orders/QueryOrders
- **ExecutionEngine.execute()** → processes orders
- **Portfolio** → stores and aggregates results

---

## Core Classes & Components

### 1. TimeGrid (BT/data_handler.py)
The temporal backbone of the backtest - a simple but crucial abstraction.

```python
class TimeGrid:
    """Simple iterator over a schedule of datetimes."""
    def __init__(self, states: Iterable[datetime.datetime]):
        self._states = list(states)
    
    def __iter__(self) -> Iterator[datetime.datetime]:
        return iter(self._states)
```

**Purpose**: Provides a consistent timeline for strategy evaluation.

**Key Methods**:
- `__iter__()`: Returns iterator over all timestamps in chronological order

**Usage**:
```python
from BT.data_handler import TimeGrid
from BT.misc import ql_cal_date_range
import QuantLib as ql
import datetime

# Create business day time grid
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
time_grid = TimeGrid(ql_cal_date_range(
    ql_cal=cal,
    start=datetime.date(2024, 1, 1),
    end=datetime.date(2024, 12, 31)
))

# Iterate over all backtest timestamps
for timestamp in time_grid:
    print(timestamp)
```

### 2. TriggerInfo (BT/event.py)
Encapsulates trigger evaluation results with contextual information.

```python
@dataclass
class TriggerInfo:
    triggered: bool
    info: Dict[Type, Any] = field(default_factory=dict)
    
    def __bool__(self) -> bool:
        return self.triggered
```

**Purpose**: Carries both the trigger decision and metadata for actions.

**Fields**:
- `triggered`: Boolean indicating if trigger fired
- `info`: Type-keyed dictionary for passing context to actions

**Usage**:
```python
# Triggers return TriggerInfo
trigger_info = some_trigger.has_triggered(now, backtest)

if trigger_info:  # Uses __bool__
    # Trigger fired
    context = trigger_info.info  # Dict[Type, Any]
    for action in trigger.actions:
        orders = action(pricer=..., now=now, backtest=backtest, info=context)
```

### 3. Order (BT/order.py)
Basic order for generic instruments (EventDrivenBacktest).

```python
@dataclass
class Order:
    timestamp: dt.datetime
    instrument: _GenericPricable
    meta: Optional[Dict] = None
```

**Purpose**: Represents an order to execute a trade of a fully-specified instrument.

**Fields**:
- `timestamp`: When the order was generated
- `instrument`: The thing to trade (fully specified with notional, side, etc.)
- `meta`: Tags, action source, trigger ID, etc.

### 4. QueryOrder & UnwindOrder (BT/query_order.py)
More sophisticated orders for QueryDrivenBacktest.

```python
@dataclass
class QueryOrder:
    timestamp: datetime.datetime
    query: BaseQuery  # Parameterized product definition
    meta: Optional[Dict] = None

@dataclass
class UnwindOrder:
    timestamp: datetime.datetime
    selector: Callable[[Any], bool]  # Predicate: ResolvedQueryPosition -> bool
    meta: Optional[Dict] = None  # e.g., {"action":"unwind", "fee": 0.0}
```

**Purpose**: 
- `QueryOrder`: Submit a Query that will be resolved to concrete instruments at trade time
- `UnwindOrder`: Close positions matching a predicate to realize P&L

### 5. Position (BT/portfolio.py)
Track a single trade with metadata.

```python
@dataclass
class Position:
    instrument: _GenericPricable
    opened: dt.datetime
    meta: dict = field(default_factory=dict)
```

**Purpose**: Immutable representation of a single filled trade.

### 6. Portfolio (BT/portfolio.py)
Aggregates all trades and provides access patterns.

```python
@dataclass
class Portfolio:
    positions: List[Position] = field(default_factory=list)
    orders_log: List = field(default_factory=list)
    trades_log: List = field(default_factory=list)
    
    def add(self, instrument: _GenericPricable, opened: dt.datetime, meta: Optional[dict] = None) -> None:
        self.positions.append(Position(instrument=instrument, opened=opened, meta=meta or {}))
    
    def trade_count_between(self, start: dt.datetime, end: dt.datetime) -> int:
        return sum(1 for p in self.positions if start <= p.opened <= end)
    
    @property
    def instruments_by_key(self) -> Dict[str, _GenericPricable]:
        out: Dict[str, _GenericPricable] = {}
        for p in self.positions:
            out[_instrument_key(p.instrument)] = p.instrument
        return out
    
    def iter_instruments(self) -> Iterable[_GenericPricable]:
        for p in self.positions:
            yield p.instrument
```

**Key Methods**:
- `add()`: Add a filled trade to the portfolio
- `trade_count_between()`: Count trades in a time window (for TradeCountTrigger)
- `instruments_by_key`: Dictionary view of all held instruments
- `iter_instruments()`: Iterate over all instruments

### 7. ResolvedQueryPosition (BT/query_portfolio.py)
Position in the QueryDrivenBacktest context.

```python
@dataclass(frozen=True)
class ResolvedQueryPosition:
    package: List[_GenericPricable]      # Resolved components
    weights: List[float]                  # Risk weights for each component
    opened: datetime.datetime
    source_query: BaseQuery               # Original query used
    meta: Dict[str, Any] = field(default_factory=dict)
```

**Purpose**: Captures both the original Query definition and the resolved instrument package, enabling P&L calculation and position matching.

### 8. QueryPortfolio (BT/query_portfolio.py)
Portfolio for QueryDrivenBacktest with position selection capabilities.

```python
class QueryPortfolio:
    def __init__(self) -> None:
        self.positions: List[ResolvedQueryPosition] = []
        self.orders_log: List[Any] = []
        self.trades_log: List[Any] = []
    
    def add(self, pos: ResolvedQueryPosition) -> None:
        self.positions.append(pos)
    
    def pop_matching(self, predicate: Callable[[ResolvedQueryPosition], bool]) -> List[ResolvedQueryPosition]:
        # Remove and return positions matching predicate
        removed, kept = [], []
        for p in self.positions:
            try:
                match = bool(predicate(p))
            except Exception:
                match = False
            (removed if match else kept).append(p)
        self.positions = kept
        return removed
    
    def trade_count_between(self, start: datetime.datetime, end: datetime.datetime) -> int:
        return sum(1 for p in self.positions if start <= p.opened <= end)
    
    def iter_positions(self) -> Iterable[ResolvedQueryPosition]:
        return tuple(self.positions)
```

**Key Methods**:
- `pop_matching()`: Atomic remove and return of positions (critical for unwinds)
- `iter_positions()`: Snapshot iteration for P&L calculation

### 9. ExecutionEngine (BT/execution_engine.py)
Pluggable order execution logic.

```python
class ExecutionEngine:
    """Naive immediate-fill execution."""
    def execute(self, orders: List[Order]) -> List[Order]:
        # In real life: pricing, slippage, partial fills, venue logic
        return orders
```

**Purpose**: Transforms orders to fills. Current implementation assumes immediate, full execution. Can be extended with:
- Realistic pricing models
- Slippage/transaction costs
- Partial fills
- Venue-specific logic
- Liquidity constraints

---

## Event Loop & Execution Flow

### EventDrivenBacktest Main Loop

The core event loop in `EventDrivenBacktest.run()`:

```python
def run(self) -> None:
    for now in self.time_grid:
        # 1. Resolve pricer for current timestamp
        self._resolve_pricer_for(now)
        
        # 2. Evaluate strategy -> generate orders
        new_orders = self.strategy.evaluate(now, self)
        if not new_orders:
            # No trades this period
            self.mark_to_market(now)
            continue
        
        # 3. Execute orders
        fills = self.exec_engine.execute(new_orders)
        
        # 4. Update portfolio ledger
        self.portfolio.orders_log.extend(new_orders)
        self.portfolio.trades_log.extend(fills)
        for o in fills:
            self.portfolio.add(o.instrument, opened=now, meta=o.meta or {})
        
        # 5. Mark to market
        self.mark_to_market(now)
```

**Flow Diagram**:
```
┌─────────────────────────────────────────────────────────────────┐
│ For each timestamp in TimeGrid:                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─ Pricer Resolution ─────────────────────────────────────────┐ │
│  │ if mdp: fetch new pricer based on request                   │ │
│  │ else: use static pricer                                     │ │
│  │ [Cache pricer by request signature for efficiency]          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                           ↓                                       │
│  ┌─ Strategy Evaluation ──────────────────────────────────────┐  │
│  │ for each trigger in strategy.triggers:                     │  │
│  │   1. evaluate trigger.has_triggered(now, self)             │  │
│  │   2. if triggered:                                         │  │
│  │      for each action in trigger.actions:                   │  │
│  │         orders += action(pricer, now, self, info)          │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                           ↓                                       │
│  ┌─ Order Execution ──────────────────────────────────────────┐  │
│  │ fills = exec_engine.execute(orders)                        │  │
│  │ [Default: immediate full fill]                            │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                           ↓                                       │
│  ┌─ Portfolio Update ─────────────────────────────────────────┐  │
│  │ portfolio.orders_log.extend(new_orders)                    │  │
│  │ portfolio.trades_log.extend(fills)                         │  │
│  │ for each fill:                                             │  │
│  │   portfolio.add(fill.instrument, opened=now, meta=...)     │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                           ↓                                       │
│  ┌─ Mark-to-Market ───────────────────────────────────────────┐  │
│  │ mtm_value = sum(pricer.npv(instr) for instr in portfolio)  │  │
│  │ mtm_history[now] = mtm_value                               │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### QueryDrivenBacktest Main Loop

More sophisticated loop in `QueryDrivenBacktest.run()`:

```python
def run(self) -> None:
    states = list(self.time_grid)
    
    for now in tqdm.tqdm(states, disable=not self.show_progress, ...):
        self._now = now
        
        # 1. Strategy evaluation -> QueryOrder + UnwindOrder
        new_orders: list[QueryOrder] = self.strategy.evaluate(now, self)
        
        # 2. Separate add and unwind orders
        add_orders = [o for o in new_orders if isinstance(o, QueryOrder)]
        unwind_orders = [o for o in new_orders if isinstance(o, UnwindOrder)]
        
        # 3. Execute add orders (buy new positions)
        fills = self.exec_engine.execute(add_orders)
        self.portfolio.orders_log.extend(add_orders)
        self.portfolio.trades_log.extend(fills)
        
        for o in fills:
            q = o.query
            # Resolve query to concrete instruments at trade time
            pricer_or_curve = self._pricer_for_query(q, now)
            package, weights = q.resolve_package(pricer_or_curve=pricer_or_curve)
            
            # Store with weights for P&L calculation
            self.portfolio.add(
                ResolvedQueryPosition(
                    package=package,
                    weights=weights,
                    opened=now,
                    source_query=q,
                    meta=o.meta or {},
                )
            )
        
        # 4. Process unwinds (close positions, realize P&L)
        for u in unwind_orders:
            self._handle_unwind(u, now)
        
        # 5. Mark to market
        self.mark_to_market(now)
```

**Key Differences from EventDriven**:
1. Uses `QueryOrder` (parameterized) instead of `Order` (fully specified)
2. Resolves queries to instruments at trade time (captures snapshot)
3. Tracks weights for multi-leg P&L calculation
4. Supports `UnwindOrder` for position closing with fee tracking
5. Handles realized vs unrealized P&L separately

---

## Trigger System

### Architecture

Triggers define "when to trade". The system uses a **Template Method** pattern where a `Trigger` delegates to a `TriggerRequirements` implementation:

```
Trigger (wrapper with actions)
└── TriggerRequirements (condition logic)
    ├── has_triggered(state, backtest) -> TriggerInfo
    └── get_trigger_times() -> List[dt.time]
```

### Base Classes

#### TriggerRequirements (Abstract Base)

```python
class TriggerRequirements:
    calc_type: str = "point_in_time"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        raise NotImplementedError
    
    def get_trigger_times(self) -> List[dt.time]:
        return []  # overridden by intraday/periodic
```

#### Trigger (Concrete Wrapper)

```python
@dataclass
class Trigger:
    trigger_requirements: TriggerRequirements
    actions: Union[Action, Iterable[Action], None] = None
    
    def __post_init__(self):
        if self.actions is None:
            self.actions = []
        if not isinstance(self.actions, list):
            self.actions = [self.actions]
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return self.trigger_requirements.has_triggered(state, backtest)
    
    def get_trigger_times(self) -> List[dt.time]:
        return self.trigger_requirements.get_trigger_times()
    
    @property
    def calc_type(self):
        return self.trigger_requirements.calc_type
    
    @property
    def risks(self):
        # Risk names from actions
        return [x.risk for x in self.actions if getattr(x, "risk", None) is not None]
```

### Concrete Trigger Types

#### 1. PeriodicTrigger / PeriodicTriggerRequirements
Fires on specific dates.

```python
@dataclass
class PeriodicTriggerRequirements(TriggerRequirements):
    dates: Sequence[dt.date]
    calc_type: str = "calendar"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        trig = state.date() in set(self.dates)
        return TriggerInfo(trig)

@dataclass
class PeriodicTrigger(Trigger):
    pass  # requirements: PeriodicTriggerRequirements
```

**Usage**:
```python
from BT.triggers import PeriodicTrigger, PeriodicTriggerRequirements
from BT.actions import AddTradeAction
import datetime

trigger = PeriodicTrigger(
    trigger_requirements=PeriodicTriggerRequirements(
        dates=[datetime.date(2024, 1, 15), datetime.date(2024, 2, 15)]
    ),
    actions=[
        AddTradeAction(build_kwargs={"tenor": "5Y", "side": "payer"})
    ]
)
```

#### 2. IntradayPeriodicTrigger / IntradayTriggerRequirements
Fires at specific times of day.

```python
@dataclass
class IntradayTriggerRequirements(TriggerRequirements):
    times: Sequence[dt.time]
    calc_type: str = "intraday"
    
    def get_trigger_times(self) -> List[dt.time]:
        return list(self.times)
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return TriggerInfo(state.time() in self.times)

@dataclass
class IntradayPeriodicTrigger(Trigger):
    pass
```

**Usage**:
```python
import datetime as dt

trigger = IntradayPeriodicTrigger(
    trigger_requirements=IntradayTriggerRequirements(
        times=[dt.time(9, 30), dt.time(15, 0)]  # 9:30 AM and 3:00 PM
    ),
    actions=[...]
)
```

#### 3. MktTrigger / MktTriggerRequirements
Fires based on market data conditions (signal vs threshold).

```python
@dataclass
class MktTriggerRequirements(TriggerRequirements):
    fetch: Callable[[dt.datetime], Optional[float]]
    op: Callable[[float, float], bool]
    threshold: float
    calc_type: str = "market"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        v = self.fetch(state)
        return TriggerInfo(v is not None and self.op(float(v), float(self.threshold)))

@dataclass
class MktTrigger(Trigger):
    pass
```

**Usage**:
```python
import operator
import pandas as pd

# Assume we have a Series of some indicator
indicator_series = pd.Series({...})

trigger = MktTrigger(
    trigger_requirements=MktTriggerRequirements(
        fetch=lambda t: indicator_series.get(t),
        op=operator.gt,  # Greater than
        threshold=0.5
    ),
    actions=[...]
)
```

#### 4. RiskTrigger / RiskTriggerRequirements
Fires based on portfolio risk exceeding threshold.

```python
@dataclass
class RiskTriggerRequirements(TriggerRequirements):
    risk: str                              # Risk name (e.g., "dv01")
    op: Callable[[float, float], bool]     # Comparison operator
    threshold: float
    calc_type: str = "risk"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        val = backtest.get_strategy_risk(self.risk)
        return TriggerInfo(self.op(val, self.threshold))

@dataclass
class StrategyRiskTrigger(Trigger):
    @property
    def risks(self):
        return super().risks + [self.trigger_requirements.risk]
```

**Usage**:
```python
# Trigger when DV01 exposure exceeds 50bp
trigger = StrategyRiskTrigger(
    trigger_requirements=RiskTriggerRequirements(
        risk="dv01",
        op=operator.gt,
        threshold=50.0
    ),
    actions=[HedgeAction(...)]  # Hedge when triggered
)
```

#### 5. AggregateTrigger / AggregateTriggerRequirements
Combines multiple triggers with AND/OR logic.

```python
@dataclass
class AggregateTriggerRequirements(TriggerRequirements):
    triggers: List[Trigger]
    mode: str = "any"  # "any" == OR, "all" == AND
    calc_type: str = "aggregate"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        infos = [t.has_triggered(state, backtest) for t in self.triggers]
        trig = all(bool(i) for i in infos) if self.mode == "all" else any(bool(i) for i in infos)
        # Merge action info maps
        info_map: Dict[Type, Any] = {}
        for i in infos:
            info_map.update(i.info)
        return TriggerInfo(trig, info_map)

@dataclass
class AggregateTrigger(Trigger):
    pass
```

**Usage**:
```python
# Fire if EITHER market signal > 0.5 OR risk > 50
combined = AggregateTrigger(
    trigger_requirements=AggregateTriggerRequirements(
        triggers=[mkt_trigger, risk_trigger],
        mode="any"  # OR logic
    ),
    actions=[...]
)

# Fire if BOTH conditions met
combined = AggregateTrigger(
    trigger_requirements=AggregateTriggerRequirements(
        triggers=[mkt_trigger, risk_trigger],
        mode="all"  # AND logic
    ),
    actions=[...]
)
```

#### 6. MeanReversionTrigger / MeanReversionTriggerRequirements
Fires based on z-score of a time series (mean reversion entry).

```python
@dataclass
class MeanReversionTriggerRequirements(TriggerRequirements):
    fetch: Callable[[dt.datetime], Optional[float]]
    lookback: int
    z_entry: float
    calc_type: str = "stat"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        window = backtest.window(self.fetch, state, self.lookback)
        if len(window) < self.lookback or any(x is None for x in window):
            return TriggerInfo(False)
        
        mu = stats.mean(window)
        sd = stats.pstdev(window) or 1e-12
        z = (window[-1] - mu) / sd
        
        # Scale size based on how extreme the z-score
        scaling = -z / self.z_entry if abs(z) >= self.z_entry else 0.0
        
        return TriggerInfo(
            abs(z) >= self.z_entry,
            {AddScaledTradeAction: {"scaling": scaling}}
        )
```

**Purpose**: Supports statistical mean reversion strategies with automatic sizing.

**Usage**:
```python
from BT.triggers import MeanReversionTrigger, MeanReversionTriggerRequirements

trigger = MeanReversionTrigger(
    trigger_requirements=MeanReversionTriggerRequirements(
        fetch=lambda t: some_series.loc[t],
        lookback=20,          # 20-period window
        z_entry=2.0           # Entry at 2-sigma
    ),
    actions=[AddScaledTradeAction(build_kwargs={...})]
)
```

#### 7. TradeCountTrigger / TradeCountTriggerRequirements
Fires based on number of trades in a lookback window.

```python
@dataclass
class TradeCountTriggerRequirements(TriggerRequirements):
    lookback: dt.timedelta
    op: Callable[[int, int], bool]
    count: int
    calc_type: str = "trade_count"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        n = backtest.trade_count_since(state - self.lookback, state)
        return TriggerInfo(self.op(n, self.count))

@dataclass
class TradeCountTrigger(Trigger):
    pass
```

**Usage**:
```python
import datetime as dt
import operator

# Fire if more than 5 trades in last 7 days
trigger = TradeCountTrigger(
    trigger_requirements=TradeCountTriggerRequirements(
        lookback=dt.timedelta(days=7),
        op=operator.gt,
        count=5
    ),
    actions=[UnwindPositionsAction(...)]  # Close when over-trading
)
```

#### 8. EventTrigger / EventTriggerRequirements
Fires on macro calendar events (FOMC, NFP, etc.).

```python
@dataclass
class EventTriggerRequirements(TriggerRequirements):
    events_on: Callable[[dt.datetime], List[str]]
    event_name: str
    calc_type: str = "event"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        todays = set(self.events_on(state))
        return TriggerInfo(self.event_name in todays)

@dataclass
class EventTrigger(Trigger):
    pass
```

**Usage**:
```python
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

trigger = EventTrigger(
    trigger_requirements=EventTriggerRequirements(
        events_on=lambda dt: list(_CENTRAL_BANK_DATES.get("USD-FEDFUNDS", {}).keys()),
        event_name="FOMC"
    ),
    actions=[...]
)
```

#### 9. PortfolioTrigger / PortfolioTriggerRequirements
Fires based on portfolio state predicate.

```python
@dataclass
class PortfolioTriggerRequirements(TriggerRequirements):
    predicate: Callable[[Any], bool]
    calc_type: str = "portfolio"
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return TriggerInfo(self.predicate(backtest))

@dataclass
class PortfolioTrigger(Trigger):
    pass
```

**Usage**:
```python
# Fire if portfolio is empty
trigger = PortfolioTrigger(
    trigger_requirements=PortfolioTriggerRequirements(
        predicate=lambda bt: len(bt.portfolio.positions) == 0
    ),
    actions=[...]
)
```

#### 10. OrdersGeneratorTrigger
Base class for time-grid driven order generation (advanced).

```python
@dataclass
class OrdersGeneratorTrigger(Trigger):
    """Base class for time-grid order generation."""
    
    def get_trigger_times(self) -> List[dt.time]:
        return self.trigger_requirements.get_trigger_times()
    
    def generate_orders(self, state: dt.datetime, backtest=None) -> List[Order]:
        raise RuntimeError("generate_orders must be implemented by subclass")
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        if state.time() not in self.get_trigger_times():
            return TriggerInfo(False)
        orders = self.generate_orders(state, backtest)
        info = {type(a): orders for a in (self.actions or [])} if orders else {}
        return TriggerInfo(bool(orders), info)
```

---

## Action System

### Architecture

Actions define "what to trade" - they're callable objects that accept trigger context and return orders.

```python
class Action(Protocol):
    risk: Optional[str]
    
    def __call__(self, *, pricer: _GenericPricer, now, backtest, info: Dict[Type, Any]) -> List[Order]: ...
```

### Concrete Actions for EventDrivenBacktest

#### 1. AddTradeAction
Submit a fully-specified instrument to be traded.

```python
@dataclass
class AddTradeAction:
    build_kwargs: Dict[str, Any]
    risk: Optional[str] = None
    
    def __call__(self, *, pricer: _GenericPricer, now, backtest, info) -> List[Order]:
        instr = pricer.build_pricable(**self.build_kwargs)
        return [Order(timestamp=now, instrument=instr, meta={"action": "add_trade"})]
```

**Usage**:
```python
action = AddTradeAction(
    build_kwargs={
        "tenor": "5Y",
        "side": "payer",
        "notional": 1_000_000
    },
    risk="dv01"
)
```

#### 2. AddScaledTradeAction
Submit a trade with size scaled by trigger context (e.g., mean reversion z-score).

```python
@dataclass
class AddScaledTradeAction:
    build_kwargs: Dict[str, Any]
    scale_key: str = "scaling"
    notional_key: str = "notional"
    default_notional: float = 1.0e6
    risk: Optional[str] = None
    
    def __call__(self, *, pricer: _GenericPricer, now, backtest, info) -> List[Order]:
        scale = float(info.get(AddScaledTradeAction, {}).get(self.scale_key, 1.0))
        kwargs = dict(self.build_kwargs)
        base_notional = float(kwargs.get(self.notional_key, self.default_notional))
        kwargs[self.notional_key] = base_notional * scale
        instr = pricer.build_pricable(**kwargs)
        return [Order(timestamp=now, instrument=instr, meta={"action": "add_scaled", "scale": scale})]
```

**Usage with MeanReversionTrigger**:
```python
# Trigger provides scaling based on z-score
action = AddScaledTradeAction(
    build_kwargs={"tenor": "5Y", "side": "payer"},
    notional_key="notional",
    default_notional=100_000  # Base size
)
# Actual notional = 100_000 * scaling (from trigger)
```

#### 3. HedgeAction
Automatically hedge a portfolio risk.

```python
@dataclass
class HedgeAction:
    risk_name: str
    hedge_builder: Callable[[_GenericPricer, float], _GenericPricable]
    risk: Optional[str] = None
    
    def __call__(self, *, pricer: _GenericPricer, now, backtest, info) -> List[Order]:
        exposure = backtest.get_strategy_risk(self.risk_name)
        instr = self.hedge_builder(pricer, -float(exposure))
        return [Order(timestamp=now, instrument=instr, meta={"action": "hedge", "risk": self.risk_name})]
```

**Usage**:
```python
def build_dv01_hedge(pricer, target_dv01):
    # Create instrument with target DV01 exposure
    return pricer.build_pricable(tenor="10Y", dv01=target_dv01)

action = HedgeAction(
    risk_name="dv01",
    hedge_builder=build_dv01_hedge,
    risk="dv01"
)
```

### Query Actions for QueryDrivenBacktest

#### 1. AddQueryAction
Submit a Query to be resolved at trade time.

```python
@dataclass
class AddQueryAction:
    query: BaseQuery
    risk: Optional[str] = None
    
    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return [QueryOrder(timestamp=now, query=self.query, meta={"action": "add_query"})]
```

**Usage**:
```python
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure

query = IRSwapQuery(
    structure=IRSwapStructure.SINGLE,
    curve="USD-SOFR-1D",
    structure_kwargs={"tenor": "5Y", "side": "payer", "notional": 1_000_000}
)

action = AddQueryAction(query=query)
```

#### 2. AddScaledQueryAction
Submit a Query with scaled structure parameters.

```python
@dataclass
class AddScaledQueryAction:
    query: BaseQuery
    target_key: str = "bpv"
    scale_key: str = "scaling"
    default_value: float = 1.0
    risk: Optional[str] = None
    
    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        scale = float(info.get(AddScaledQueryAction, {}).get(self.scale_key, 1.0))
        kw = dict(self.query.structure_kwargs or {})
        base = float(kw.get(self.target_key, self.default_value))
        kw[self.target_key] = base * scale
        q2 = replace(self.query, structure_kwargs=kw)
        return [QueryOrder(timestamp=now, query=q2, meta={"action": "add_scaled", "scale": scale})]
```

**Usage**:
```python
action = AddScaledQueryAction(
    query=some_query,
    target_key="bpv",        # Scale the BPV parameter
    default_value=100_000    # Base BPV
)
```

#### 3. UnwindPositionsAction
Close positions matching a selector.

```python
@dataclass
class UnwindPositionsAction:
    selector: Optional[Callable[[Any], bool]] = None
    match_all: bool = False
    match_tag: Optional[str] = None
    fee: float = 0.0
    risk: Optional[str] = None
    
    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        if self.match_all:
            pred = lambda p: True
        elif self.match_tag is not None:
            tag = self.match_tag
            def pred(p):
                tags = set()
                tags.update(p.meta.get("tags", []))
                tags.update(getattr(p.source_query, "tags", ()) or ())
                return tag in tags
        elif self.selector is not None:
            pred = self.selector
        else:
            raise ValueError("Provide selector, match_all, or match_tag")
        
        return [UnwindOrder(timestamp=now, selector=pred, meta={"action": "unwind", "fee": float(self.fee)})]
```

**Usage**:
```python
# Unwind all positions
action = UnwindPositionsAction(match_all=True, fee=0.0)

# Unwind positions with specific tag
action = UnwindPositionsAction(match_tag="fomc-fly", fee=100.0)

# Unwind based on custom predicate
action = UnwindPositionsAction(
    selector=lambda pos: pos.opened < some_date,
    fee=50.0
)
```

---

## Strategy Pattern

### Strategy (EventDrivenBacktest)

```python
@dataclass
class Strategy:
    name: str
    triggers: Iterable[Trigger]
    
    def evaluate(self, now: dt.datetime, backtest) -> List[Order]:
        orders: List[Order] = []
        for trig in self.triggers:
            info = trig.has_triggered(now, backtest)
            if info:
                for action in trig.actions:
                    orders.extend(action(pricer=backtest._current_pricer(), now=now, backtest=backtest, info=info.info))
        return orders
```

**Key Method**: `evaluate(now, backtest)`
- Returns list of `Order` objects
- Called once per timestamp
- Aggregates all triggered actions

**Usage**:
```python
from BT.strategy import Strategy

strategy = Strategy(
    name="My Trading Strategy",
    triggers=[
        trigger1,
        trigger2,
        trigger3
    ]
)

# Backtest evaluates automatically
# But can manually call:
orders = strategy.evaluate(datetime.datetime(2024, 1, 15), backtest)
```

### QueryStrategy (QueryDrivenBacktest)

```python
@dataclass
class QueryStrategy:
    name: str
    triggers: Iterable[Trigger]
    
    def evaluate(self, now: datetime.datetime, backtest) -> List[QueryOrder]:
        orders: List[QueryOrder] = []
        for trig in self.triggers:
            info = trig.has_triggered(now, backtest)
            if info:
                for action in trig.actions:
                    if hasattr(action, "__call__"):
                        out = action(now=now, backtest=backtest, info=info.info)
                        if out:
                            orders.extend(out)
        return orders
```

**Key Differences**:
- Returns `QueryOrder` and `UnwindOrder` (not `Order`)
- Actions don't receive `pricer` (resolved later)
- Returns can include both add and unwind orders

**Usage**:
```python
from BT.query_strategy import QueryStrategy

strategy = QueryStrategy(
    name="Query-Based Strategy",
    triggers=[
        # Mix of different triggers
        DateTrigger(...),
        MeanReversionTrigger(...),
        # etc.
    ]
)
```

---

## Portfolio Management

### EventDrivenBacktest Portfolio Structure

```python
portfolio: Portfolio
    ├── positions: List[Position]
    │   ├── instrument: _GenericPricable
    │   ├── opened: datetime
    │   └── meta: dict
    ├── orders_log: List[Order]
    └── trades_log: List[Order]
```

### QueryDrivenBacktest Portfolio Structure

```python
portfolio: QueryPortfolio
    ├── positions: List[ResolvedQueryPosition]
    │   ├── package: List[_GenericPricable]
    │   ├── weights: List[float]
    │   ├── opened: datetime
    │   ├── source_query: BaseQuery
    │   └── meta: dict
    ├── orders_log: List[QueryOrder]
    └── trades_log: List[QueryOrder]
```

### Common Portfolio Operations

```python
# Add a filled trade
portfolio.add(instrument, opened=now, meta={"trigger": "fomc"})

# Count trades in period
n_trades = portfolio.trade_count_between(start, end)

# Get instruments by key (latest wins)
instr_dict = portfolio.instruments_by_key

# Iterate all instruments
for instr in portfolio.iter_instruments():
    print(instr)
```

### QueryPortfolio-Specific Operations

```python
# Remove positions matching predicate (atomic)
closed_positions = portfolio.pop_matching(
    lambda p: p.source_query.structure == IRSwapStructure.FLY
)

# Iterate positions (immutable snapshot)
for pos in portfolio.iter_positions():
    # pos is ResolvedQueryPosition with package, weights, etc.
```

---

## P&L Tracking

### Mark-to-Market (EventDrivenBacktest)

```python
def mark_to_market(self, now: dt.datetime) -> float:
    pricer = self._current_pricer()
    total = 0.0
    for instr in self.portfolio.iter_instruments():
        try:
            total += float(pricer.npv(instr))
        except Exception:
            continue
    self.mtm_history[now] = total
    return total
```

**Mechanics**:
1. Iterate all held instruments
2. Get NPV from pricer for each
3. Sum to total
4. Store in `mtm_history` dictionary

**Result**: `mtm_history[timestamp] = total_mtm_value`

### Mark-to-Market (QueryDrivenBacktest)

```python
def mark_to_market(self, now: datetime.datetime) -> float:
    # total = realized + current open marks
    total = float(self.realized_pnl)
    for p in self.portfolio.iter_positions():
        total += self._position_value(p, now)
    self.mtm_history[now] = total
    return total

def _position_value(self, pos: ResolvedQueryPosition, now: datetime.datetime) -> float:
    pricer_or_curve: _GenericPricer = self._pricer_for_query(pos.source_query, now)
    
    resolved_package = [
        pricer_or_curve.resolve_pricable(p, rw) 
        for p, rw in zip(pos.package, pos.weights)
    ]
    
    vmap = pos.source_query.build_value_map(
        pricer_or_curve=pricer_or_curve,
        package=resolved_package,
        risk_weights=pos.weights,
    )
    
    value_id = pos.source_query.default_mtm_value_id()
    return float(vmap.apply(value=value_id))
```

**Mechanics**:
1. Start with cumulative realized P&L
2. For each open position:
   - Re-resolve package with current pricer
   - Build value map with original weights
   - Apply default MTM value ID (typically NPV)
3. Sum realized + unrealized
4. Store in `mtm_history`

### Realized P&L (QueryDrivenBacktest)

```python
def _handle_unwind(self, order: UnwindOrder, now: datetime.datetime) -> None:
    to_close = self.portfolio.pop_matching(order.selector)
    if not to_close:
        self.realized_pnl_history[now] = self.realized_pnl
        return
    
    pnl = 0.0
    for pos in to_close:
        pnl += self._position_value(pos, now)
    
    fee = float((order.meta or {}).get("fee", 0.0))
    self.realized_pnl += pnl - fee
    self.realized_pnl_history[now] = self.realized_pnl
```

**Mechanics**:
1. Remove matching positions (atomic operation)
2. Calculate mark for each closed position
3. Subtract fees
4. Accumulate in `realized_pnl`
5. Track history

---

## QueryDriven vs EventDriven

### Conceptual Differences

| Aspect | EventDrivenBacktest | QueryDrivenBacktest |
|--------|---------------------|---------------------|
| **Instrument Specification** | Fully specified at order time | Parameterized via Query |
| **Order Type** | `Order` | `QueryOrder` + `UnwindOrder` |
| **Resolution** | N/A | Query → Package at trade time |
| **P&L Calculation** | Direct NPV sum | Weighted multi-leg valuation |
| **Position Closing** | Remove from portfolio | Atomic unwind with selector |
| **Use Case** | Simple instruments | Complex products (IR swaps, spreads) |

### Execution Flow Comparison

**EventDrivenBacktest**:
```
Trigger → Action → Order(instrument) 
          → ExecutionEngine → Portfolio.add(filled)
          → MtM (sum NPVs)
```

**QueryDrivenBacktest**:
```
Trigger → Action → QueryOrder(query)
          → ExecutionEngine → Resolve query to package
          → Portfolio.add(ResolvedQueryPosition)
          → MtM (weighted multi-leg)
          ↓
          UnwindOrder(selector) → Portfolio.pop_matching()
          → Realize P&L
```

### Key Implementation Differences

#### 1. Pricer Resolution

**EventDrivenBacktest**:
```python
def _resolve_pricer_for(self, now: dt.datetime) -> _GenericPricer:
    if self.mdp is not None:
        req = dict(self.mdp_request_builder(now))
        sig = repr(sorted(req.items()))
        if self.cache.get("pricer_sig") != sig:
            self.cache["pricer"] = self.mdp.get_pricer(req)
            self.cache["pricer_sig"] = sig
    elif self.pricer is not None:
        self.cache["pricer"] = self.pricer
    else:
        raise RuntimeError("Provide either `pricer` or `mdp+mdp_request_builder`.")
    return self.cache["pricer"]
```

**QueryDrivenBacktest**:
```python
def _pricer_for_query(self, q: BaseQuery, now: datetime.datetime) -> Any:
    req = q.build_mdp_request(now)  # Query builds its own request
    return self._pricer_for_request(req)

def _pricer_for_request(self, req: Dict[str, Any]) -> Any:
    sig = repr(sorted(req.items()))
    hit = self._cache.get(("pricer", sig))
    if hit is not None:
        return hit
    pricer = self.mdp.get_pricer(req)
    self._cache[("pricer", sig)] = pricer
    return pricer
```

#### 2. Position Resolution

**EventDrivenBacktest**:
```python
# Instruments are already fully specified
for o in fills:
    self.portfolio.add(o.instrument, opened=now, meta=o.meta or {})
```

**QueryDrivenBacktest**:
```python
# Resolve query to package at trade time
for o in fills:
    q = o.query
    pricer_or_curve = self._pricer_for_query(q, now)
    package, weights = q.resolve_package(pricer_or_curve=pricer_or_curve)
    self.portfolio.add(
        ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=q,
            meta=o.meta or {},
        )
    )
```

#### 3. Position Closing

**EventDrivenBacktest**:
- Positions don't close explicitly; just accumulate
- Only use case is portfolio.pop() or manual deletion

**QueryDrivenBacktest**:
- Active unwind mechanism
- Matches positions by selector predicate
- Realizes P&L atomically
- Supports fee tracking

---

## Time Grid Management

### TimeGrid Class

```python
class TimeGrid:
    def __init__(self, states: Iterable[datetime.datetime]):
        self._states = list(states)
    
    def __iter__(self) -> Iterator[datetime.datetime]:
        return iter(self._states)
```

### Time Grid Generation

The `BT/misc.py` module provides helpers for building calendrical grids:

```python
def ql_cal_date_range(
    ql_cal: ql.Calendar,
    start: datetime.datetime,
    end: datetime.datetime,
    freq: Optional[str] = "1b",  # 1 business day
    open_time: Optional[datetime.time] = datetime.time(7, 0),
    close_time: Optional[datetime.time] = datetime.time(15, 0),
):
    """
    Generate trading hours grid respecting calendar.
    
    Args:
        ql_cal: QuantLib calendar (handles holidays)
        start: Start date
        end: End date
        freq: Frequency (e.g., "1b", "1h", "30min")
        open_time: Market open time
        close_time: Market close time
    
    Returns:
        List of datetime objects during trading hours
    """
```

**Usage**:
```python
import QuantLib as ql
import datetime
from BT.data_handler import TimeGrid
from BT.misc import ql_cal_date_range

# Create business day grid
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
dates = ql_cal_date_range(
    ql_cal=cal,
    start=datetime.datetime(2024, 1, 1),
    end=datetime.datetime(2024, 12, 31),
    freq="1b"  # Daily
)
time_grid = TimeGrid(dates)

# Create intraday grid (9:30-15:00 hourly)
intraday = ql_cal_date_range(
    ql_cal=cal,
    start=datetime.datetime(2024, 1, 1),
    end=datetime.datetime(2024, 12, 31),
    freq="1h",
    open_time=datetime.time(9, 30),
    close_time=datetime.time(15, 0)
)
time_grid = TimeGrid(intraday)
```

### Other Helper Functions

```python
def _last_business_day_of_month(cal: ql.Calendar, y: int, m: int) -> datetime.date:
    """Last business day of a month."""

def _nth_business_day_of_month(cal: ql.Calendar, y: int, m: int, n: int) -> datetime.date:
    """Nth business day of a month."""

def _n_business_days_before(cal: ql.Calendar, d: datetime.date, n: int) -> datetime.date:
    """N business days before a date."""

def _month_iter(start: datetime.date, end: datetime.date) -> list[tuple[int, int]]:
    """Iterate (year, month) tuples in range."""
```

---

## Order Execution

### ExecutionEngine

```python
class ExecutionEngine:
    """Naive immediate-fill execution."""
    def execute(self, orders: List[Order]) -> List[Order]:
        # In real life: pricing, slippage, partial fills, venue logic
        return orders
```

**Current Behavior**: Immediate, full fill of all orders at market prices.

### Extension Points

To customize execution, subclass `ExecutionEngine`:

```python
from BT.execution_engine import ExecutionEngine
from BT.order import Order
from typing import List

class SlippageEngine(ExecutionEngine):
    def __init__(self, slippage_bps: float = 1.0):
        self.slippage_bps = slippage_bps
    
    def execute(self, orders: List[Order]) -> List[Order]:
        # Apply slippage to orders
        # Return filled list
        return orders

class PartialFillEngine(ExecutionEngine):
    def __init__(self, fill_pct: float = 0.9):
        self.fill_pct = fill_pct
    
    def execute(self, orders: List[Order]) -> List[Order]:
        # Partially fill orders
        fills = []
        for order in orders:
            # Scale down notional
            filled_qty = order.quantity * self.fill_pct
            # ... create modified order
            fills.append(...)
        return fills
```

Usage:
```python
backtest = EventDrivenBacktest(
    time_grid=tg,
    strategy=strat,
    pricer=pricer,
    exec_engine=SlippageEngine(slippage_bps=2.0)
)
```

---

## Public API Reference

### EventDrivenBacktest

```python
@dataclass
class EventDrivenBacktest:
    # Configuration
    time_grid: TimeGrid
    pricer: Optional[_GenericPricer] = None
    mdp: Optional[MarketDataProvider] = None
    mdp_request_builder: Optional[RequestBuilder] = None
    strategy: Strategy = None
    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, r: {}
    
    # State
    portfolio: Portfolio = field(default_factory=Portfolio)
    cache: Dict[str, Any] = field(default_factory=dict)
    mtm_history: Dict[dt.datetime, float] = field(default_factory=dict)
    
    # Public Methods
    def run(self) -> None:
        """Execute backtest over all timestamps."""
    
    def get_strategy_risk(self, name: str) -> float:
        """Query current portfolio risk."""
    
    def trade_count_since(self, start: dt.datetime, end: dt.datetime) -> int:
        """Count trades in window."""
    
    def window(self, fetch_fn, now: dt.datetime, lookback: int):
        """Get time series window for lookback analysis."""
    
    def mark_to_market(self, now: dt.datetime) -> float:
        """Calculate current portfolio value."""
    
    def _current_pricer(self) -> _GenericPricer:
        """Get cached pricer (internal)."""
    
    def _resolve_pricer_for(self, now: dt.datetime) -> _GenericPricer:
        """Resolve pricer for timestamp (internal)."""
```

### QueryDrivenBacktest

```python
@dataclass
class QueryDrivenBacktest:
    # Configuration
    time_grid: TimeGrid
    mdp: MarketDataProvider
    strategy: QueryStrategy
    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, g: {}
    
    # State
    portfolio: QueryPortfolio = field(default_factory=QueryPortfolio)
    mtm_history: Dict[datetime.datetime, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    realized_pnl_history: Dict[datetime.datetime, float] = field(default_factory=dict)
    
    # UI
    show_progress: bool = True
    progress_desc: str = "BACKTESTING..."
    
    # Public Methods
    def run(self) -> None:
        """Execute backtest with progress bar."""
    
    def get_strategy_risk(self, name: str) -> float:
        """Query current portfolio risk via risk_fn."""
    
    def trade_count_since(self, start: datetime.datetime, end: datetime.datetime) -> int:
        """Count trades in window."""
    
    def window(self, fetch_fn, now: datetime.datetime, lookback: int):
        """Get time series window."""
    
    def mark_to_market(self, now: datetime.datetime) -> float:
        """Calculate total P&L (realized + unrealized)."""
    
    def _pricer_for_query(self, q: BaseQuery, now: datetime.datetime) -> Any:
        """Get pricer for query (cached)."""
    
    def _pricer_for_request(self, req: Dict[str, Any]) -> Any:
        """Get pricer for request (cached)."""
    
    def _position_value(self, pos: ResolvedQueryPosition, now: datetime.datetime) -> float:
        """Calculate value of open position."""
    
    def _handle_unwind(self, order: UnwindOrder, now: datetime.datetime) -> None:
        """Process position closure and realize P&L."""
```

### Strategy

```python
@dataclass
class Strategy:
    name: str
    triggers: Iterable[Trigger]
    
    def evaluate(self, now: dt.datetime, backtest) -> List[Order]:
        """Generate orders from triggers."""
```

### QueryStrategy

```python
@dataclass
class QueryStrategy:
    name: str
    triggers: Iterable[Trigger]
    
    def evaluate(self, now: datetime.datetime, backtest) -> List[QueryOrder]:
        """Generate orders from triggers."""
```

### Portfolio

```python
@dataclass
class Portfolio:
    positions: List[Position]
    orders_log: List
    trades_log: List
    
    def add(self, instrument: _GenericPricable, opened: dt.datetime, meta: Optional[dict] = None) -> None:
        """Add filled trade."""
    
    def trade_count_between(self, start: dt.datetime, end: dt.datetime) -> int:
        """Count trades in window."""
    
    @property
    def instruments_by_key(self) -> Dict[str, _GenericPricable]:
        """Keyed access to instruments (latest wins)."""
    
    def iter_instruments(self) -> Iterable[_GenericPricable]:
        """Iterate all instruments."""
```

### QueryPortfolio

```python
class QueryPortfolio:
    positions: List[ResolvedQueryPosition]
    orders_log: List[Any]
    trades_log: List[Any]
    
    def add(self, pos: ResolvedQueryPosition) -> None:
        """Add resolved position."""
    
    def pop_matching(self, predicate: Callable[[ResolvedQueryPosition], bool]) -> List[ResolvedQueryPosition]:
        """Atomically remove and return matching positions."""
    
    def trade_count_between(self, start: datetime.datetime, end: datetime.datetime) -> int:
        """Count trades in window."""
    
    def iter_positions(self) -> Iterable[ResolvedQueryPosition]:
        """Iterate all positions (immutable snapshot)."""
```

### Trigger

```python
@dataclass
class Trigger:
    trigger_requirements: TriggerRequirements
    actions: Union[Action, Iterable[Action], None] = None
    
    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        """Evaluate trigger condition."""
    
    def get_trigger_times(self) -> List[dt.time]:
        """Get intraday trigger times (if applicable)."""
    
    @property
    def calc_type(self):
        """Trigger calculation type string."""
    
    @property
    def risks(self):
        """Risk names from actions."""
```

---

## Integration Points

### 1. Query Module Integration

**BaseQuery** (Query.Base.BaseQuery.py)
- Provides parameterized product definitions
- `build_mdp_request(now)`: Converts to MDP request
- `resolve_package(pricer)`: Returns list of _GenericPricable
- `build_value_map()`: Creates valuation logic
- `default_mtm_value_id()`: MTM value to use

**Concrete Implementations**:
- `IRSwapQuery`: Single IR swap or fly
- Other product types as needed

### 2. Market Data Provider Integration

**MarketDataProvider** (MDP/MarketDataProvider.py)
- Abstract interface for data sources
- `get_pricer(request)` → returns _GenericPricer

**Implementations**:
- `IRSwapsMDP`: Interest rate swap curves
- `FixedRateBondsMDP`: Bond pricing
- Custom implementations for other products

### 3. Pricer Integration

**_GenericPricer** (Query.Base._GenericPricer.py)
- Abstraction for valuation engine
- `npv(pricable)`: Calculate NPV
- `build_pricable(**kwargs)`: Construct instrument
- `resolve_pricable(pricable, weight)`: Resolve for multi-leg

### 4. Pricable Integration

**_GenericPricable** (Query.Base._GenericPricable.py)
- Abstraction for tradeable instruments
- Required interface for all traded objects

---

## Usage Examples

### Example 1: Simple Daily Rebalance (EventDrivenBacktest)

```python
import datetime as dt
import operator
from BT.data_handler import TimeGrid
from BT.generic_engine import EventDrivenBacktest
from BT.strategy import Strategy
from BT.triggers import PeriodicTrigger, PeriodicTriggerRequirements
from BT.actions import AddTradeAction
from BT.misc import ql_cal_date_range
import QuantLib as ql

# Setup time grid
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
dates = ql_cal_date_range(
    ql_cal=cal,
    start=dt.datetime(2024, 1, 1),
    end=dt.datetime(2024, 12, 31),
    freq="1b"
)
time_grid = TimeGrid(dates)

# Setup strategy
trigger = PeriodicTrigger(
    trigger_requirements=PeriodicTriggerRequirements(
        dates=[dt.date(2024, 1, 15), dt.date(2024, 2, 15)]
    ),
    actions=[
        AddTradeAction(
            build_kwargs={"tenor": "5Y", "side": "payer", "notional": 1_000_000},
            risk="dv01"
        )
    ]
)

strategy = Strategy(name="Monthly Payer", triggers=[trigger])

# Setup and run backtest
backtest = EventDrivenBacktest(
    time_grid=time_grid,
    pricer=your_pricer,  # Your _GenericPricer instance
    strategy=strategy,
    risk_fn=lambda port, pricer: {"dv01": calculate_dv01(port, pricer)}
)

backtest.run()

# Results
print(f"Final MtM: {backtest.mtm_history[list(backtest.mtm_history.keys())[-1]]}")
print(f"Total trades: {len(backtest.portfolio.positions)}")
```

### Example 2: Mean Reversion Trading (EventDrivenBacktest)

```python
import pandas as pd
from BT.triggers import MeanReversionTrigger, MeanReversionTriggerRequirements
from BT.actions import AddScaledTradeAction

# Historical spread data
spread_series = pd.Series({...})

# Setup trigger
trigger = MeanReversionTrigger(
    trigger_requirements=MeanReversionTriggerRequirements(
        fetch=lambda t: spread_series.get(t),
        lookback=20,
        z_entry=2.0
    ),
    actions=[
        AddScaledTradeAction(
            build_kwargs={"tenor": "5Y", "side": "payer"},
            notional_key="notional",
            default_notional=100_000,  # Scales based on z-score
            risk="dv01"
        )
    ]
)

strategy = Strategy(name="Mean Reversion", triggers=[trigger])

# Run backtest
backtest = EventDrivenBacktest(
    time_grid=time_grid,
    pricer=your_pricer,
    strategy=strategy
)

backtest.run()
```

### Example 3: FOMC Fly Strategy (QueryDrivenBacktest)

From `fomc_fly_backtest.py`:

```python
from BT.data_handler import TimeGrid
from BT.misc import ql_cal_date_range
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue
import QuantLib as ql
import datetime

# Setup time grid
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
tg = TimeGrid(ql_cal_date_range(
    ql_cal=cal,
    start=datetime.date(2024, 1, 1),
    end=datetime.date(2025, 10, 2)
))

# Setup MDP
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

# Define fly query
q_fly = IRSwapQuery(
    structure=IRSwapStructure.FLY,
    curve="USD-SOFR-1D",
    structure_kwargs={
        "front_tenor": "2Y",
        "belly_tenor": "5Y",
        "back_tenor": "10Y",
        "bpv": 500_000
    },
    tags=("fomc-fly",)
)

# Setup triggers for entry and exit
entry_trigger = DateTrigger(
    trigger_requirements=DateTriggerRequirements(
        dates=[datetime.date(2024, 1, 15)]
    ),
    actions=[AddQueryAction(query=q_fly)]
)

exit_trigger = DateTrigger(
    trigger_requirements=DateTriggerRequirements(
        dates=[datetime.date(2024, 1, 31)]
    ),
    actions=[UnwindPositionsAction(match_tag="fomc-fly", fee=0.0)]
)

strategy = QueryStrategy(
    name="FOMC Fly",
    triggers=[entry_trigger, exit_trigger]
)

# Run backtest
backtest = QueryDrivenBacktest(
    time_grid=tg,
    mdp=mdp,
    strategy=strategy,
    show_progress=True
)

backtest.run()

# Results
final_mtm = backtest.mtm_history[max(backtest.mtm_history.keys())]
print(f"Final P&L: {final_mtm}")
print(f"Realized P&L: {backtest.realized_pnl}")
```

### Example 4: Risk-Based Hedging (EventDrivenBacktest)

```python
from BT.triggers import StrategyRiskTrigger, RiskTriggerRequirements
from BT.actions import HedgeAction
import operator

def hedge_builder(pricer, target_dv01):
    """Build hedge to achieve target DV01."""
    return pricer.build_pricable(
        tenor="10Y",
        side="receiver",
        notional=abs(target_dv01 / 0.01)  # Rough approximation
    )

# Trigger when DV01 > 50bp
trigger = StrategyRiskTrigger(
    trigger_requirements=RiskTriggerRequirements(
        risk="dv01",
        op=operator.gt,
        threshold=50.0
    ),
    actions=[
        HedgeAction(
            risk_name="dv01",
            hedge_builder=hedge_builder,
            risk="dv01"
        )
    ]
)

strategy = Strategy(name="Risk Hedge", triggers=[trigger])

# Risk function calculates portfolio DV01
def calculate_dv01(portfolio, pricer):
    total_dv01 = 0.0
    for instr in portfolio.iter_instruments():
        # DV01 = change in value for 1bp move
        try:
            dv01 = calculate_dv01_for_instr(instr, pricer)
            total_dv01 += dv01
        except:
            pass
    return {"dv01": total_dv01}

backtest = EventDrivenBacktest(
    time_grid=time_grid,
    pricer=your_pricer,
    strategy=strategy,
    risk_fn=calculate_dv01
)

backtest.run()
```

### Example 5: Complex Aggregate Trigger

```python
from BT.triggers import (
    AggregateTrigger,
    AggregateTriggerRequirements,
    MktTrigger,
    MktTriggerRequirements,
    StrategyRiskTrigger,
    RiskTriggerRequirements,
)
import operator
import pandas as pd

# Market condition: spread > 50bp
mkt_trigger = MktTrigger(
    trigger_requirements=MktTriggerRequirements(
        fetch=lambda t: spread_series.get(t),
        op=operator.gt,
        threshold=50.0
    )
)

# Risk condition: portfolio long vega
vega_trigger = StrategyRiskTrigger(
    trigger_requirements=RiskTriggerRequirements(
        risk="vega",
        op=operator.gt,
        threshold=0.0
    )
)

# Combined: enter only if BOTH conditions true
combined = AggregateTrigger(
    trigger_requirements=AggregateTriggerRequirements(
        triggers=[mkt_trigger, vega_trigger],
        mode="all"  # AND logic
    ),
    actions=[
        AddTradeAction(build_kwargs={"tenor": "5Y", "side": "payer"})
    ]
)

strategy = Strategy(name="Conditional Entry", triggers=[combined])
```

---

## Advanced Topics

### Custom Risk Functions

Risk functions enable portfolio-level analysis:

```python
from BT.query_portfolio import QueryPortfolio
from Query.Base.BaseQuery import BaseQuery

def my_risk_fn(portfolio: QueryPortfolio, pricer_getter: Callable[[BaseQuery], Any]) -> Dict[str, float]:
    """
    Calculate portfolio-level risks.
    
    Args:
        portfolio: Current portfolio of open positions
        pricer_getter: Function to get pricer for a query (handles caching)
    
    Returns:
        Dictionary of risk names to values
    """
    risks = {
        "dv01": 0.0,
        "vega": 0.0,
        "gamma": 0.0,
    }
    
    for pos in portfolio.iter_positions():
        pricer = pricer_getter(pos.source_query)
        # Calculate risks for this position
        # Add to aggregates
    
    return risks

backtest = QueryDrivenBacktest(
    ...,
    risk_fn=my_risk_fn
)
```

### Custom Execution Engines

Implement realistic execution logic:

```python
from BT.execution_engine import ExecutionEngine
from BT.query_order import QueryOrder
from typing import List

class VenueEngine(ExecutionEngine):
    def __init__(self, min_size: float = 100_000, max_slippage: float = 2.0):
        self.min_size = min_size
        self.max_slippage = max_slippage
    
    def execute(self, orders: List[QueryOrder]) -> List[QueryOrder]:
        fills = []
        for order in orders:
            # Check minimum size
            if order.query.structure_kwargs.get("bpv", 0) < self.min_size:
                continue  # Skip too small
            
            # Orders are assumed filled (can add cost tracking)
            fills.append(order)
        
        return fills
```

### Windowing for Technical Analysis

The `window()` method supports lookback analysis:

```python
# In a trigger's has_triggered method:
def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
    # Get last 20 values of spread
    window = backtest.window(
        fetch_fn=lambda t: spread_series.get(t),
        now=state,
        lookback=20
    )
    
    # Calculate moving average
    if len(window) == 20:
        ma = sum(window) / len(window)
        current = window[-1]
        crossover = window[-2] <= ma and current > ma
        return TriggerInfo(crossover)
    
    return TriggerInfo(False)
```

---

## Performance Considerations

### Caching Strategy

Both backtest engines cache pricers by request signature:

```python
# EventDrivenBacktest
self._cache = {"pricer_sig": sig, "pricer": pricer}

# QueryDrivenBacktest
self._cache[("pricer", sig)] = pricer
```

This avoids rebuilding pricers when the request hasn't changed.

### Portfolio Operations

Iterate rather than recreate:

```python
# Good
for instr in portfolio.iter_instruments():
    total += pricer.npv(instr)

# Less efficient (creates intermediate list)
for instr in list(portfolio.iter_instruments()):
    total += pricer.npv(instr)
```

### Time Grid Materialization

QueryDrivenBacktest materializes the time grid to support progress bars:

```python
states = list(self.time_grid)  # Materialize once
for now in tqdm.tqdm(states, ...):
    # Process
```

This is memory-efficient for typical backtests but could be optimized for very long histories.

---

## Common Patterns

### Date-Based Entry/Exit

```python
entry_dates = [dt.date(2024, 1, 15), dt.date(2024, 2, 15)]
exit_dates = [dt.date(2024, 1, 25), dt.date(2024, 2, 25)]

entry = DateTrigger(
    DateTriggerRequirements(dates=entry_dates),
    actions=[AddQueryAction(query=...)]
)

exit = DateTrigger(
    DateTriggerRequirements(dates=exit_dates),
    actions=[UnwindPositionsAction(match_all=True)]
)
```

### Signal-Following with Scaling

```python
# Scale position size by signal strength
trigger = MeanReversionTrigger(
    MeanReversionTriggerRequirements(
        fetch=lambda t: signal_series.get(t),
        lookback=20,
        z_entry=2.0
    ),
    actions=[
        AddScaledTradeAction(
            build_kwargs={"tenor": "5Y"},
            default_notional=100_000
        )
    ]
)
```

### Tag-Based Position Closing

```python
# Close all positions with specific tag
UnwindPositionsAction(match_tag="rebalance-2024-01-15")

# Close positions opened before date
UnwindPositionsAction(
    selector=lambda pos: pos.opened < dt.datetime(2024, 2, 1)
)
```

### Multi-Condition Entry

```python
# Enter only when multiple conditions align
condition = AggregateTrigger(
    AggregateTriggerRequirements(
        triggers=[
            DateTrigger(PeriodicTriggerRequirements(dates=[dt.date(2024, 1, 15)])),
            MktTrigger(MktTriggerRequirements(
                fetch=lambda t: signal.get(t),
                op=operator.gt,
                threshold=0
            ))
        ],
        mode="all"
    ),
    actions=[...]
)
```

---

## Troubleshooting

### Common Issues

**Issue**: "Pricer not set yet"
- **Cause**: Accessing `_current_pricer()` before first timestamp
- **Fix**: Ensure strategy evaluation happens within backtest loop

**Issue**: Orders not executing
- **Cause**: `trigger.has_triggered()` returning False
- **Solution**: Add logging to trigger evaluation

**Issue**: NaN in MTM history
- **Cause**: Instruments not priceable with current pricer
- **Solution**: Implement try/except in mark_to_market (already done in EventDrivenBacktest)

**Issue**: Unwinds not matching positions
- **Cause**: Selector predicate too restrictive
- **Solution**: Verify metadata and source_query match expectations

---

## Summary

The BT module provides a production-quality backtesting framework with:

1. **Clean separation** of concerns (triggers, actions, execution)
2. **Flexible composition** via aggregation and nested triggers
3. **Realistic portfolio tracking** with full ledgers
4. **Dual execution modes** for simple and complex products
5. **P&L accounting** with realized/unrealized tracking
6. **Integration points** for custom pricing, risk, and execution logic

The design encourages rapid prototyping while supporting sophisticated strategies through its composable architecture.

