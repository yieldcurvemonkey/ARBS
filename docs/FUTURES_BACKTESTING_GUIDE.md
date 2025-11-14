# Futures Backtesting Guide

This guide covers futures-specific patterns for backtesting in the ARBS framework.

## Quick Start

```python
from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.CarrySignal import CarrySignal

# Create backtest with futures workflow
backtest = Backtest(
    mdp=market_data_provider,
    adapter=FuturesAdapter(mdp),
    signals=CarrySignal()
)

# Run backtest
result = backtest.run(contracts=['SFRZ4', 'SFRH5'], dates=[...])
```

## Futures Query Patterns

### Contract Structures

Futures queries support multiple structure types:

```python
class FuturesStructure(str, Enum):
    OUTRIGHT = "outright"           # Single contract
    CALENDAR = "calendar_spread"    # Front - Back
    PACK = "pack"                   # 4 consecutive contracts
    BUNDLE = "bundle"               # 8 consecutive contracts
    BASIS = "basis"                 # Future vs Swap
```

### Value Calculations

Available value metrics for futures:

```python
class FuturesValue(str, Enum):
    PRICE = "price"                 # Futures price
    NPV = "npv"                     # Mark-to-market
    DV01 = "dv01"                   # Dollar value of 1bp
    MARGIN = "margin"               # Margin requirement
    BASIS = "basis"                 # vs equivalent swap
    CONVEXITY_ADJ = "convexity_adj" # Futures-FRA adjustment
    IMPLIED_RATE = "implied_rate"   # 100 - price
    CARRY = "carry"                 # Roll-down
```

### Contract Specifications

Example contract query structure:

```python
@dataclass(frozen=True)
class FuturesQuery(BaseQuery):
    contract: str                   # e.g., "EDZ4" (Eurodollar Dec 2024)
    product_type: str = "STIR"      # STIR, Bond, Commodity

    # Contract specs
    tick_size: float = 0.0025       # $6.25 per tick for ED
    multiplier: float = 2500        # $2500 per bp for ED
    expiry: Optional[date] = None   # Auto-resolved from contract code

    # For basis trades
    swap_tenor: Optional[str] = None  # "3M" for STIR basis
```

## Structure Map Examples

### Outright Position

```python
def outright(self, query: FuturesQuery) -> List[Priceable]:
    """Single futures contract"""
    return [rl.STIRFuture(...)]
```

### Calendar Spread

```python
def calendar_spread(self, query: FuturesQuery) -> List[Priceable]:
    """Near - Far spread"""
    front = rl.STIRFuture(...)  # query.contract
    back = rl.STIRFuture(...)   # next quarterly
    return [(front, 1.0), (back, -1.0)]
```

### Pack (4 consecutive contracts)

```python
def pack(self, query: FuturesQuery) -> List[Priceable]:
    """4 consecutive quarterly contracts"""
    contracts = [rl.STIRFuture(...) for _ in range(4)]
    return [(c, 0.25) for c in contracts]
```

### Bundle (8 consecutive contracts)

```python
def bundle(self, query: FuturesQuery) -> List[Priceable]:
    """8 consecutive quarterly contracts"""
    contracts = [rl.STIRFuture(...) for _ in range(8)]
    return [(c, 0.125) for c in contracts]
```

### Basis Trade (Future vs Swap)

```python
def basis(self, query: FuturesQuery) -> List[Priceable]:
    """Future vs equivalent swap"""
    future = rl.STIRFuture(...)
    swap = rl.IRS(...)  # Matched-maturity swap
    return [(future, 1.0), (swap, -1.0)]
```

## Settlement and Margin

### Daily Settlement

Futures use daily mark-to-market settlement:

```python
class FuturesSettlement(SettlementConvention):
    """Daily mark-to-market settlement"""

    def calculate_cash_flows(self, position, t0, t1):
        # Daily variation margin
        prev_price = position.get_price(t0)
        curr_price = position.get_price(t1)
        vm = (curr_price - prev_price) * position.multiplier * position.quantity
        return [CashFlow(t1, vm, "variation_margin")]
```

### Margin Calculation

Simplified margin model:

```python
class FuturesMargin(MarginConvention):
    """CME SPAN-style margin"""

    def initial_margin(self, position, pricer):
        # Simplified: X% of notional
        return abs(position.npv) * self.margin_rate

    def variation_margin(self, position, pricer, prev_price):
        # Daily settlement
        curr_price = pricer.price(position.package)
        return (curr_price - prev_price) * position.multiplier * position.quantity
```

## Roll Strategies

### Roll Before Expiry

Automatic rolling of futures contracts:

```python
class FuturesRoll(RollConvention):
    """Roll futures before expiry"""

    def __init__(self, days_before_expiry: int = 5):
        self.days_before_expiry = days_before_expiry

    def should_roll(self, position, current_date):
        expiry = position.package[0].expiry
        return (expiry - current_date).days <= self.days_before_expiry

    def get_roll_target(self, position, current_date):
        # Roll to next quarterly contract
        old_contract = position.query.contract
        new_contract = self._get_next_quarterly(old_contract)
        return position.query.replace(contract=new_contract)
```

### Roll Timing

Common roll strategies:
- **5 days before expiry**: Standard practice to avoid delivery
- **Front-to-front**: Roll when front contract becomes most liquid
- **Constant maturity**: Maintain fixed time-to-expiry

## Example Strategies

### 1. STIR Curve Steepener

Long front pack, short back pack with quarterly rolling:

```python
backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=CurveSteepenerSignal(front_pack="RED", back_pack="GRN"),
    roll_convention=FuturesRoll(days_before_expiry=5)
)

result = backtest.run(
    contracts=['EDZ4', 'EDH5', 'EDM5', 'EDU5'],  # Front pack
    dates=date_range
)
```

### 2. Futures-Swap Basis

Capture basis when it exceeds threshold:

```python
backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=BasisSignal(threshold=5),  # 5bp threshold
    structure="basis"
)

result = backtest.run(
    contracts=['EDZ4'],
    swap_tenor='3M',
    dates=date_range
)
```

### 3. Calendar Spread Around FOMC

Enter spread 2 weeks before FOMC meetings:

```python
backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=FOMCCalendarSignal(days_before=14),
    structure="calendar_spread"
)

result = backtest.run(
    contracts=['EDZ4', 'EDH5'],  # Pre/post FOMC contracts
    dates=fomc_meeting_dates
)
```

## Cross-Product Strategies

### Futures + Swaps Portfolio

Mixed portfolio example:

```python
# Use generic backtest with mixed queries
from Query.IRS.IRSQuery import IRSQuery
from Query.Futures.FuturesQuery import FuturesQuery

backtest = Backtest(
    mdp=mdp,
    signals=[CarrySignal(), BasisSignal()],
    signal_combiner=SignalCombiner(method='ic_weighted')
)

# Mix of futures and swaps
queries = [
    FuturesQuery(contract='EDZ4'),
    IRSQuery(tenor='2Y', currency='USD')
]

result = backtest.run_from_queries(queries, dates)
```

## Data Requirements

### Market Data Provider

Futures backtesting requires:
- Historical settlement prices
- Contract specifications (tick size, multiplier)
- Expiry dates
- Discount curves for valuation

### Recommended Data Sources

1. **CME**: Official settlement prices
2. **Eris**: Integrated futures infrastructure
3. **ZODB Cache**: Local caching for performance

## Performance Considerations

### Caching

Use ZODB caching for:
- Historical prices
- Contract specifications
- Discount curves

### Memory Management

For large backtests:
- Stream results rather than accumulating in memory
- Use date batching for very long periods
- Clear cache periodically

## Testing

### Unit Tests

Test futures-specific functionality:

```python
def test_futures_query_parsing():
    """Test contract code parsing (EDZ4 → Dec 2024)"""
    query = FuturesQuery(contract='EDZ4')
    assert query.expiry.month == 12
    assert query.expiry.year == 2024

def test_calendar_spread_structure():
    """Test calendar spread construction"""
    structure_map = FuturesStructureMap()
    package = structure_map.calendar_spread(query)
    assert len(package) == 2
    assert package[0][1] == 1.0   # Long front
    assert package[1][1] == -1.0  # Short back
```

### Integration Tests

Test end-to-end workflows:

```python
def test_futures_backtest_with_roll():
    """Test backtest with automatic rolling"""
    backtest = Backtest(
        mdp=mdp,
        adapter=FuturesAdapter(mdp),
        signals=CarrySignal(),
        roll_convention=FuturesRoll(days_before_expiry=5)
    )

    result = backtest.run(contracts=['EDZ4'], dates=date_range)

    # Verify roll occurred
    assert len(result.roll_history) > 0
    assert result.total_return is not None
```

## Common Issues

### Contract Code Parsing

Ensure contract codes follow standard conventions:
- Month codes: H(Mar), M(Jun), U(Sep), Z(Dec)
- Year: Last digit (4 = 2024, 5 = 2025)
- Example: EDZ4 = Eurodollar December 2024

### Margin Calls

Monitor margin requirements:
- Initial margin posted at entry
- Variation margin settled daily
- Margin calls if equity falls below maintenance level

### Roll Timing

Avoid delivery by rolling early:
- Standard: 5 days before expiry
- Liquidity considerations: Roll when next contract is more liquid
- Cost: Track roll costs (bid-ask spread)

## Best Practices

1. **Always specify roll conventions**: Avoid unexpected deliveries
2. **Track margin separately**: Don't confuse margin with P&L
3. **Use proper multipliers**: Ensure tick size and multiplier match contract specs
4. **Cache aggressively**: Futures backtests can be data-intensive
5. **Test with real data**: Mock data doesn't capture roll costs and basis dynamics

## Additional Resources

- See `examples/run_backtest.py` for working example
- Review `Adapter/FuturesAdapter.py` for implementation details
- Check `Backtest/__init__.py` for usage patterns
- Consult CLAUDE.md for architecture overview
