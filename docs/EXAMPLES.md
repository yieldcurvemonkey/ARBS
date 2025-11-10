# ARBS Usage Examples

This document provides practical examples of using ARBS for backtesting interest rate strategies.

All examples are extracted from the test suite (`tests/`) and are guaranteed to work with the current codebase.

## Table of Contents

1. [Query Creation](#query-creation)
2. [Simple Backtests](#simple-backtests)
3. [Portfolio Management](#portfolio-management)
4. [Custom Triggers](#custom-triggers)
5. [Advanced Workflows](#advanced-workflows)

---

## Query Creation

### Example 1: Simple Outright Query

Create a query for a single IRS tenor:

```python
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

# Query for 5Y USD SOFR par rate
query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    tenor="5Y",
    curve="USD-SOFR-1D",
)
```

**Use case**: Get the par rate for a specific tenor at each timestep.

### Example 2: Outright with Custom BPV

Control position sizing using basis point value (BPV):

```python
query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.NPV,
    tenor="10Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000},  # $1MM per bp
)
```

**Use case**: Size positions by risk (DV01) rather than notional.

### Example 3: Butterfly (Fly) Query

Create a butterfly structure (long front, short belly 2x, long back):

```python
query = IRSwapQuery(
    structure=IRSwapStructure.FLY,
    value=IRSwapValue.NPV,
    curve="USD-SOFR-1D",
    structure_kwargs={
        "front_tenor": "2Y",
        "belly_tenor": "5Y",
        "back_tenor": "10Y",
        "bpv": 1_000_000,
    },
)
```

**Use case**: Express curve shape views (e.g., 2s/5s/10s flattening/steepening).

### Example 4: Tagged Query for Later Unwinding

Tag queries to identify positions for closing:

```python
query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    tenor="5Y",
    curve="USD-SOFR-1D",
    tags=("fomc-trade", "short-end"),  # Multiple tags supported
    name="Pre-FOMC 5Y Receiver",       # Human-readable name
)
```

**Use case**: Close all positions related to a specific event or strategy.

---

## Simple Backtests

### Example 5: Empty Backtest (Baseline)

Run a backtest with no trades to verify setup:

```python
import datetime
from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# Create time grid
dates = [datetime.datetime(2025, 1, d) for d in range(1, 6)]
grid = TimeGrid(dates)

# Empty strategy
strategy = QueryStrategy(name="Baseline", triggers=[])

# Market data provider
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

# Run backtest
bt = QueryDrivenBacktest(
    time_grid=grid,
    mdp=mdp,
    strategy=strategy,
    show_progress=False,
)
bt.run()

# Check results
print(f"MTM History: {bt.mtm_history}")
print(f"Realized P&L: {bt.realized_pnl}")
```

**Expected**: Zero P&L, empty portfolio.

### Example 6: Single Trade Entry

Enter a position on a specific date and hold:

```python
from BT.triggers import DateTrigger, DateTriggerRequirements
from BT.query_actions import AddQueryAction

query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.NPV,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000},
)

# Trigger that fires on January 15, 2025
trigger = DateTrigger(
    DateTriggerRequirements(dates=[datetime.date(2025, 1, 15)]),
    actions=[AddQueryAction(query=query)],
)

strategy = QueryStrategy(name="Single Trade", triggers=[trigger])

bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()

print(f"Final MTM: {list(bt.mtm_history.values())[-1]}")
print(f"Positions: {len(list(bt.portfolio.iter_positions()))}")
```

**Expected**: One open position, MTM tracks the value over time.

### Example 7: Enter and Exit

Enter a position, then close it later:

```python
from BT.query_actions import UnwindPositionsAction

entry_date = datetime.date(2025, 1, 10)
exit_date = datetime.date(2025, 1, 20)

query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.NPV,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000},
    tags=("trade-1",),  # Tag for unwinding
)

enter_trigger = DateTrigger(
    DateTriggerRequirements(dates=[entry_date]),
    actions=[AddQueryAction(query=query)],
)

exit_trigger = DateTrigger(
    DateTriggerRequirements(dates=[exit_date]),
    actions=[UnwindPositionsAction(match_tag="trade-1")],
)

strategy = QueryStrategy(
    name="Entry-Exit",
    triggers=[enter_trigger, exit_trigger],
)

bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()

print(f"Realized P&L: {bt.realized_pnl}")
print(f"Open Positions: {len(list(bt.portfolio.iter_positions()))}")
```

**Expected**: Zero open positions after exit, realized P&L recorded.

---

## Portfolio Management

### Example 8: Unwind Multiple Positions

Close all positions sharing a tag:

```python
# Enter two positions with same tag
query1 = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    tenor="5Y",
    curve="USD-SOFR-1D",
    tags=("strategy-A",),
)

query2 = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    tenor="10Y",
    curve="USD-SOFR-1D",
    tags=("strategy-A",),
)

# Enter on different dates
enter1 = DateTrigger(
    DateTriggerRequirements(dates=[datetime.date(2025, 1, 5)]),
    actions=[AddQueryAction(query=query1)],
)

enter2 = DateTrigger(
    DateTriggerRequirements(dates=[datetime.date(2025, 1, 10)]),
    actions=[AddQueryAction(query=query2)],
)

# Unwind all "strategy-A" positions at once
exit_all = DateTrigger(
    DateTriggerRequirements(dates=[datetime.date(2025, 1, 25)]),
    actions=[UnwindPositionsAction(match_tag="strategy-A")],
)

strategy = QueryStrategy(
    name="Multi-Unwind",
    triggers=[enter1, enter2, exit_all],
)
```

**Use case**: Close an entire strategy or theme in one action.

### Example 9: Transaction Costs

Apply fees when closing positions:

```python
exit_with_fee = DateTrigger(
    DateTriggerRequirements(dates=[exit_date]),
    actions=[UnwindPositionsAction(
        match_tag="trade-1",
        fee=1000.0,  # $1000 transaction cost
    )],
)
```

**Use case**: Model realistic trading costs in backtest P&L.

### Example 10: Iterate Open Positions

Access all open positions for custom calculations:

```python
# After running backtest
for position in bt.portfolio.iter_positions():
    print(f"Query: {position.source_query.signature()}")
    print(f"Opened: {position.opened}")
    print(f"Tags: {position.source_query.tags}")
    print(f"Package size: {len(position.package)} instruments")
```

**Use case**: Calculate custom risk metrics (e.g., aggregate DV01, key rates).

---

## Custom Triggers

### Example 11: Always-On Trigger

Fire on every timestep:

```python
from BT.triggers import TriggerRequirements
from BT.event import TriggerInfo

class AlwaysOn(TriggerRequirements):
    def has_triggered(self, state, backtest=None):
        return TriggerInfo(True, info={})

trigger = Trigger(
    AlwaysOn(),
    actions=[AddQueryAction(query=some_query)],
)
```

**Use case**: Continuous rebalancing or daily entry.

### Example 12: Day-of-Week Trigger

Fire on specific days (e.g., Mondays):

```python
class MondayTrigger(TriggerRequirements):
    def has_triggered(self, state, backtest=None):
        is_monday = state.weekday() == 0  # Monday = 0
        return TriggerInfo(is_monday, info={})
```

**Use case**: Week-start rebalancing or calendar-based strategies.

### Example 13: Month-End Trigger

Fire on the last day of each month:

```python
import datetime

class MonthEndTrigger(TriggerRequirements):
    def has_triggered(self, state, backtest=None):
        state_date = state.date() if isinstance(state, datetime.datetime) else state
        next_day = state_date + datetime.timedelta(days=1)
        is_month_end = next_day.month != state_date.month
        return TriggerInfo(is_month_end, info={})
```

**Use case**: Month-end rebalancing, coinciding with month-end fixings.

### Example 14: Risk-Based Trigger

Fire when portfolio risk exceeds a threshold:

```python
class RiskThresholdTrigger(TriggerRequirements):
    def __init__(self, risk_name: str, threshold: float):
        self.risk_name = risk_name
        self.threshold = threshold

    def has_triggered(self, state, backtest=None):
        if backtest is None:
            return TriggerInfo(False, info={})

        current_risk = backtest.get_strategy_risk(self.risk_name)
        exceeds = abs(current_risk) > self.threshold

        return TriggerInfo(exceeds, info={
            "risk_name": self.risk_name,
            "current": current_risk,
            "threshold": self.threshold,
        })

# Use with risk function
def dv01_risk_fn(portfolio, pricer_getter):
    # Calculate portfolio DV01
    total_dv01 = 0.0
    for pos in portfolio.iter_positions():
        pricer = pricer_getter(pos.source_query)
        # ... calculate DV01 ...
        total_dv01 += dv01
    return {"dv01": total_dv01}

trigger = Trigger(
    RiskThresholdTrigger("dv01", 10_000_000),  # $10MM DV01 limit
    actions=[...],  # e.g., hedge action
)
```

**Use case**: Automatic hedging when risk limits are breached.

---

## Advanced Workflows

### Example 15: Carry-Based Entry

Enter when carry is positive, exit when it turns negative:

```python
# Pseudo-code - requires implementing custom carry calculation

class PositiveCarryTrigger(TriggerRequirements):
    def __init__(self, query, horizon="1m"):
        self.query = query
        self.horizon = horizon

    def has_triggered(self, state, backtest=None):
        if backtest is None:
            return TriggerInfo(False, info={})

        # Get pricer for current time
        pricer = backtest._pricer_for_query(self.query, state)

        # Resolve package and calculate carry
        pkg, weights = self.query.resolve_package(pricer_or_curve=pricer)
        value_map = self.query.build_value_map(
            pricer_or_curve=pricer,
            package=pkg,
            risk_weights=weights,
        )

        carry = value_map.apply(
            value=IRSwapValue.CARRY_BPS_RUNNING,
            horizon=self.horizon,
        )

        return TriggerInfo(carry > 0, info={"carry": carry})
```

**Use case**: Trades that only make sense when carry-positive.

### Example 16: FOMC-Based Fly

Enter butterfly positions around FOMC meetings:

See `fomc_fly_backtest.py` for a complete working example.

Key concepts:
- Use `_CENTRAL_BANK_DATES` to identify FOMC meeting dates
- Create fly structures using meeting-relative tenors
- Exit 1 business day before first leg expiry or when carry turns negative

---

## Testing Your Strategies

All examples above can be tested using the test suite:

```bash
# Run all tests
pytest tests/

# Run specific example
pytest tests/test_backtest_simple.py::TestBasicBacktest::test_single_trade_backtest -v

# See example code
cat tests/test_backtest_simple.py
```

The tests serve as:
1. **Documentation**: Each test demonstrates a usage pattern
2. **Validation**: Ensures examples work with current codebase
3. **Regression prevention**: Catch breaking changes

---

## Common Patterns

### Pattern: Tag-Based Position Management

```python
# Always tag positions you might want to close
query = IRSwapQuery(..., tags=("strategy-name", "event-date"))

# Close by tag later
UnwindPositionsAction(match_tag="strategy-name")
```

### Pattern: Multiple Triggers per Strategy

```python
strategy = QueryStrategy(
    name="Complex Strategy",
    triggers=[
        entry_trigger_1,
        entry_trigger_2,
        exit_trigger_1,
        rebalance_trigger,
        hedge_trigger,
    ],
)
```

### Pattern: Conditional Actions

```python
class ConditionalTrigger(TriggerRequirements):
    def has_triggered(self, state, backtest=None):
        # Check multiple conditions
        condition_a = ...
        condition_b = ...

        should_fire = condition_a and condition_b
        return TriggerInfo(should_fire, info={...})
```

---

## Next Steps

1. **Start simple**: Begin with Example 5-7 (empty, single trade, entry-exit)
2. **Add complexity**: Move to custom triggers (Example 11-14)
3. **Real strategies**: Implement carry, curve, or event-driven logic (Example 15-16)
4. **Validate**: Write tests for your strategies
5. **Optimize**: Add caching for large time grids (see `Caching/` module)

## Questions?

- Check `tests/README.md` for test documentation
- See `README.md` for architecture overview
- Review `fomc_fly_backtest.py` for a complete real-world example
