# BT Module - Quick Reference Guide

## Module Files Overview

| File | Purpose |
|------|---------|
| `BT/data_handler.py` | TimeGrid - schedule of evaluation timestamps |
| `BT/event.py` | TriggerInfo - trigger evaluation results |
| `BT/order.py` | Order - generic order specification |
| `BT/query_order.py` | QueryOrder, UnwindOrder - query-based orders |
| `BT/portfolio.py` | Portfolio, Position - trade ledger |
| `BT/query_portfolio.py` | QueryPortfolio, ResolvedQueryPosition - query positions |
| `BT/strategy.py` | Strategy - trigger composition |
| `BT/query_strategy.py` | QueryStrategy - query-based trigger composition |
| `BT/triggers.py` | All trigger types and requirements |
| `BT/actions.py` | Action types for EventDrivenBacktest |
| `BT/query_actions.py` | Action types for QueryDrivenBacktest |
| `BT/generic_engine.py` | EventDrivenBacktest main backtest engine |
| `BT/query_engine.py` | QueryDrivenBacktest query-based engine |
| `BT/execution_engine.py` | ExecutionEngine - order execution |
| `BT/misc.py` | Calendar/time utilities |

## Quick Start Patterns

### Pattern 1: Simple EventDrivenBacktest
```python
from BT.data_handler import TimeGrid
from BT.generic_engine import EventDrivenBacktest
from BT.strategy import Strategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from BT.actions import AddTradeAction

# Time grid
tg = TimeGrid([...timestamps...])

# Strategy
strategy = Strategy(
    name="Simple",
    triggers=[
        DateTrigger(
            DateTriggerRequirements(dates=[...]),
            actions=[AddTradeAction(build_kwargs={...})]
        )
    ]
)

# Run
backtest = EventDrivenBacktest(
    time_grid=tg,
    pricer=your_pricer,
    strategy=strategy
)
backtest.run()
```

### Pattern 2: QueryDrivenBacktest (Complex Products)
```python
from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# Time grid
tg = TimeGrid([...timestamps...])

# MDP
mdp = IRSwapsMDP(source="...")

# Strategy
strategy = QueryStrategy(
    name="Fly",
    triggers=[
        DateTrigger(
            DateTriggerRequirements(dates=[...]),
            actions=[AddQueryAction(query=...)]
        )
    ]
)

# Run
backtest = QueryDrivenBacktest(
    time_grid=tg,
    mdp=mdp,
    strategy=strategy
)
backtest.run()
```

## Trigger Types Cheat Sheet

| Trigger Type | When to Use | Key Parameters |
|--------------|------------|-----------------|
| **PeriodicTrigger** | Fire on specific dates | `dates: List[date]` |
| **IntradayPeriodicTrigger** | Fire at specific times | `times: List[time]` |
| **MktTrigger** | Fire on market conditions | `fetch, op, threshold` |
| **RiskTrigger** | Fire when risk exceeds limit | `risk, op, threshold` |
| **AggregateTrigger** | Combine triggers with AND/OR | `triggers, mode` |
| **MeanReversionTrigger** | Fire on statistical signal | `fetch, lookback, z_entry` |
| **TradeCountTrigger** | Fire based on trade frequency | `lookback, op, count` |
| **EventTrigger** | Fire on calendar events (FOMC, etc) | `events_on, event_name` |
| **PortfolioTrigger** | Fire on portfolio state | `predicate` |
| **DateTrigger** | Same as PeriodicTrigger | `dates: List[date]` |

## Action Types Cheat Sheet

### EventDrivenBacktest Actions

| Action | Purpose | Key Use |
|--------|---------|---------|
| **AddTradeAction** | Submit fully-specified instrument | Regular trades |
| **AddScaledTradeAction** | Submit with scaled notional | Signal-following |
| **HedgeAction** | Auto-hedge portfolio risk | Risk management |

### QueryDrivenBacktest Actions

| Action | Purpose | Key Use |
|--------|---------|---------|
| **AddQueryAction** | Submit Query to resolve at trade | Complex products |
| **AddScaledQueryAction** | Submit Query with scaled parameter | Sized entry |
| **UnwindPositionsAction** | Close positions by selector | Exits/rebalance |

## Accessing Results

### EventDrivenBacktest
```python
# Mark-to-market history
mtm_dict = backtest.mtm_history  # Dict[datetime, float]

# Portfolio
positions = backtest.portfolio.positions
orders = backtest.portfolio.orders_log
trades = backtest.portfolio.trades_log
```

### QueryDrivenBacktest
```python
# Total P&L (realized + unrealized)
mtm_dict = backtest.mtm_history  # Dict[datetime, float]

# Realized P&L
realized = backtest.realized_pnl  # float
realized_history = backtest.realized_pnl_history  # Dict[datetime, float]

# Portfolio
positions = backtest.portfolio.positions  # ResolvedQueryPosition
```

## Common Tasks

### Calculate Risk
```python
def risk_fn(portfolio, pricer):
    risks = {}
    for instr in portfolio.iter_instruments():
        # Calculate risks
    return risks

backtest = EventDrivenBacktest(..., risk_fn=risk_fn)
```

### Trigger on Portfolio State
```python
trigger = PortfolioTrigger(
    PortfolioTriggerRequirements(
        predicate=lambda bt: len(bt.portfolio.positions) > 10
    )
)
```

### Close All Positions
```python
UnwindPositionsAction(match_all=True, fee=0.0)
```

### Close by Tag
```python
UnwindPositionsAction(match_tag="my-tag", fee=100.0)
```

### Close by Custom Predicate
```python
UnwindPositionsAction(
    selector=lambda pos: pos.opened < some_date
)
```

## Performance Tips

1. **Pricer Caching**: Backtests cache pricers by request signature
2. **TimeGrid**: Materialize once, iterate many times
3. **Window Function**: Use for lookback analysis (mean, std, etc)
4. **Risk Function**: Called once per timestamp - optimize
5. **ExecutionEngine**: Extend for custom execution logic

## Debugging Tips

1. Check trigger.calc_type to understand trigger behavior
2. Inspect TriggerInfo.info to see action context
3. Review portfolio.orders_log and trades_log for execution
4. Verify mtm_history has expected shape
5. Use risk_fn to inspect portfolio state

## Integration Checklist

- [ ] TimeGrid created with correct timestamp range
- [ ] Strategy/QueryStrategy has triggers
- [ ] Each trigger has actions
- [ ] Pricer or MDP configured
- [ ] Risk function provided (if needed)
- [ ] ExecutionEngine customized (if needed)
- [ ] Results accessed from mtm_history

## File Locations

- **Main Documentation**: `/home/user/ARBS/docs/BT_MODULE_DOCUMENTATION.md`
- **Module Code**: `/home/user/ARBS/BT/`
- **Examples**: `/home/user/ARBS/fomc_fly_backtest.py`

---

For detailed information, see the full BT_MODULE_DOCUMENTATION.md file.
