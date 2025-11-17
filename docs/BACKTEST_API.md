# Backtest API Documentation

## Overview

The `Backtest` class provides a single, flexible interface for running backtests across all asset classes and data sources. It supports three workflows:

1. **Signal-Based Query Workflow**: Uses MDP + Adapter + Signals for signal-driven strategies (futures, swaps)
2. **DataFrame-Based Workflow**: Uses pre-computed returns + Signals (equities, ETFs)
3. **Query-Driven Workflow**: Uses MDP + Queries directly without signals (custom query-based strategies)

### Key Design Principles

- **Single Class**: One `Backtest` class for all use cases
- **Component Injection**: All components are configurable via dependency injection
- **Signal Agnostic**: Works with any signal type (carry, momentum, mean reversion, custom)
- **Workflow Flexibility**: Choose query or DataFrame workflow based on data availability

### Architecture

```
Signal-Based Query:      DataFrame Workflow:      Query-Driven:
MDP → Adapter            Pre-computed Returns     MDP → Queries
  ↓                         ↓                         ↓
Signals                   Signals                   MTM Tracking
  ↓                         ↓                         ↓
Alpha Generator          Alpha Generator           Returns Calculation
  ↓                         ↓                         ↓
Risk Model               Risk Model                Performance Metrics
  ↓                         ↓
Optimizer                Optimizer
  ↓                         ↓
Portfolio                Portfolio
```

---

## Installation & Setup

```python
from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal
from Signals.SignalCombiner import SignalCombiner
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
```

---

## API Reference

### Backtest Class

```python
class Backtest(BaseBacktest):
    """
    Generic backtest with configurable components.

    Supports three workflows:
    1. Signal-based query: mdp + adapter + signals + contracts → run()
    2. DataFrame-based: signals + returns_df → run_from_dataframe()
    3. Query-driven: mdp + queries + time_grid → run_from_queries()
    """
```

#### Constructor

```python
def __init__(
    self,
    # Data source (signal-based query workflow)
    mdp: Optional[Any] = None,
    adapter: Optional[Any] = None,

    # Signals (signal-based workflows)
    signals: Optional[Union[BaseSignal, List[BaseSignal]]] = None,
    signal_combiner: Optional[Any] = None,

    # Queries (query-driven workflow)
    queries: Optional[List[BaseQuery]] = None,
    triggers: Optional[List[Any]] = None,

    # Pipeline components (optional)
    alpha_generator: Optional[AlphaGenerator] = None,
    risk_model: Optional[Any] = None,
    optimizer: Optional[Any] = None,
    returns_calculator: Optional[ReturnsCalculator] = None,

    # Convenience parameters
    IC: float = 0.05,
    risk_aversion: float = 1.0,
    long_only: bool = True,
    min_history: int = 20,
)
```

**Parameters:**

- `mdp` (Optional): Market data provider (for query-based workflows)
- `adapter` (Optional): Converts queries → DataFrame (FuturesAdapter, EquityAdapter)
- `signals` (Optional): Single signal or list of signals to combine (required for signal-based workflows)
- `signal_combiner` (Optional): How to combine multiple signals
- `queries` (Optional): List of queries to execute (required for query-driven workflow)
- `triggers` (Optional): Event triggers (for query-driven workflow)
- `alpha_generator` (Optional): Converts signals → expected returns (default: IC × Vol × Z)
- `risk_model` (Optional): Covariance estimator (default: LedoitWolfShrinkage)
- `optimizer` (Optional): Portfolio weight optimizer (default: MeanVarianceOptimizer)
- `returns_calculator` (Optional): Price → return conversion (default: percent returns)
- `IC` (float): Information coefficient (default: 0.05)
- `risk_aversion` (float): Risk aversion parameter (default: 1.0)
- `long_only` (bool): Only long positions (default: True)
- `min_history` (int): Minimum periods for covariance estimation (default: 20)

**Raises:**

- `ValueError`: If neither signals nor queries provided
- `ValueError`: If using adapter without mdp
- `ValueError`: If using queries without mdp

---

#### Query-Based Workflow: run()

```python
def run(
    self,
    contracts: List[str],
    dates: List[date],
) -> BacktestResult
```

Run backtest using query-based workflow.

**Requires:** `self.mdp` and `self.adapter`

**Parameters:**

- `contracts` (List[str]): List of contract codes (e.g., ['SFRZ4', 'SFRH5'])
- `dates` (List[date]): List of rebalance dates

**Returns:**

- `BacktestResult`: Performance metrics and results

**Raises:**

- `ValueError`: If adapter or mdp not provided

**Example:**

```python
from Adapter.FuturesAdapter import FuturesAdapter

backtest = Backtest(
    mdp=market_data_provider,
    adapter=FuturesAdapter(mdp),
    signals=CarrySignal(),
    risk_aversion=1.0,
    long_only=True,
)

result = backtest.run(
    contracts=['SFRZ4', 'SFRH5', 'SFRM5'],
    dates=[date(2024, 6, 15), date(2024, 6, 22), ...]
)
```

---

#### DataFrame-Based Workflow: run_from_dataframe()

```python
def run_from_dataframe(
    self,
    returns_df: pl.DataFrame,
    dates: List[date],
    instruments: Optional[List[str]] = None,
) -> BacktestResult
```

Run backtest from pre-computed returns DataFrame.

**No adapter needed** - returns already provided.

**Parameters:**

- `returns_df` (pl.DataFrame): DataFrame with columns ['date', 'ticker', 'return']
- `dates` (List[date]): List of rebalance dates
- `instruments` (Optional[List[str]]): Tickers to trade (optional filter)

**Returns:**

- `BacktestResult`: Performance metrics and results

**Raises:**

- `ValueError`: If adapter is set (shouldn't use adapter with DataFrame workflow)

**Example:**

```python
returns_df = pl.DataFrame({
    'date': [date(2024, 1, d) for d in range(1, 31)],
    'ticker': ['AAPL', 'MSFT', ...],
    'return': [0.01, -0.02, ...],
})

backtest = Backtest(
    signals=MomentumSignal(lookback=20),
    risk_aversion=3.0,
)

result = backtest.run_from_dataframe(
    returns_df=returns_df,
    dates=returns_df['date'].unique().to_list()
)
```

---

#### Query-Based Workflow: run_from_queries()

```python
def run_from_queries(
    self,
    time_grid: List[date],
    **kwargs
) -> BacktestResult
```

Run backtest using query-driven workflow.

**Requires:** `self.mdp` and `self.queries`

**Parameters:**

- `time_grid` (List[date]): List of dates for query execution
- `**kwargs`: Additional arguments

**Returns:**

- `BacktestResult`: Performance metrics and results

**Raises:**

- `ValueError`: If mdp or queries not provided

**How it differs from other workflows:**

| Feature | `run()` | `run_from_dataframe()` | `run_from_queries()` |
|---------|---------|------------------------|---------------------|
| Data Source | MDP + Adapter | Pre-computed returns | MDP + Queries |
| Requires Signals | Yes | Yes | No (optional) |
| Requires Adapter | Yes | No | No |
| Use Case | Futures/swaps with signals | Equities/ETFs | Custom query-based strategies |
| Tracking | Weights + returns | Weights + returns | MTM + returns |

**Example:**

```python
from Backtest.Backtest import Backtest
from Query.Futures.FuturesQuery import FuturesQuery
from Query.Futures.FuturesStructure import FuturesStructure

# Create queries
queries = [
    FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRZ4'),
    FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRH5'),
]

# Setup backtest with query workflow
backtest = Backtest(
    mdp=market_data_provider,
    queries=queries,
)

# Run using query workflow
result = backtest.run_from_queries(
    time_grid=[date(2024, 6, 15), date(2024, 6, 22), ...]
)

# Analyze results
print(f"Sharpe: {result.sharpe_ratio:.3f}")
print(f"Return: {result.total_return:.2%}")
```

**Note:** This workflow is designed for strategies that execute queries directly without signal generation. It tracks MTM (mark-to-market) values over time and calculates returns from MTM changes.

---

### BacktestResult

```python
@dataclass
class BacktestResult:
    """Results from backtest execution."""

    weights: pl.DataFrame          # Portfolio weights over time
    returns: pl.Series             # Portfolio returns
    signals: pl.DataFrame          # Signal values over time
    prices: pl.DataFrame           # Price history (query workflow only)
    ic: float                      # Information Coefficient
    sharpe_ratio: float            # Annualized Sharpe ratio
    total_return: float            # Cumulative return
```

---

## Workflow Examples

### 1. Query-Based Workflow

Best for: Futures, swaps, real-time pricing

```python
from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter
from Signals.Futures.CarrySignal import CarrySignal

# Setup
backtest = Backtest(
    mdp=market_data_provider,
    adapter=FuturesAdapter(mdp),
    signals=CarrySignal(),
    risk_aversion=1.0,
    long_only=True,
)

# Run
result = backtest.run(
    contracts=['SFRZ4', 'SFRH5', 'SFRM5'],
    dates=[date(2024, 6, 15), date(2024, 6, 22), ...]
)

# Analyze
print(f"Sharpe: {result.sharpe_ratio:.3f}")
print(f"IC: {result.ic:.3f}")
print(f"Return: {result.total_return:.2%}")
```

### 2. DataFrame-Based Workflow

Best for: Equities, ETFs, pre-computed returns

```python
from Backtest.Backtest import Backtest
from Signals.Futures.MomentumSignal import MomentumSignal

# Setup
backtest = Backtest(
    signals=MomentumSignal(lookback=20),
    risk_aversion=2.0,
    long_only=True,
)

# Prepare returns DataFrame
returns_df = pl.DataFrame({
    'date': [...],
    'ticker': [...],
    'return': [...],
})

# Run
result = backtest.run_from_dataframe(
    returns_df=returns_df,
    dates=returns_df['date'].unique().to_list()
)

# Analyze
print(f"Sharpe: {result.sharpe_ratio:.3f}")
```

### 3. Query-Driven Workflow

Best for: Custom query-based strategies, direct MDP execution

```python
from Backtest.Backtest import Backtest
from Query.Futures.FuturesQuery import FuturesQuery
from Query.Futures.FuturesStructure import FuturesStructure

# Create queries
queries = [
    FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRZ4'),
    FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRH5'),
]

# Setup
backtest = Backtest(
    mdp=market_data_provider,
    queries=queries,
)

# Run
result = backtest.run_from_queries(
    time_grid=[date(2024, 6, 15), date(2024, 6, 22), ...]
)

# Analyze
print(f"Sharpe: {result.sharpe_ratio:.3f}")
print(f"Return: {result.total_return:.2%}")
```

### 4. Multi-Signal Strategy

Combine multiple signals with automatic combiner

```python
from Signals.SignalCombiner import SignalCombiner

backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=[
        CarrySignal(name='carry'),
        MomentumSignal(lookback=20, name='momentum')
    ],
    signal_combiner=SignalCombiner(method='equal'),  # Optional
    risk_aversion=1.5,
)

result = backtest.run(contracts=[...], dates=[...])
```

**Note**: If `signal_combiner` not provided, Backtest auto-creates `SignalCombiner()` with equal weights.

### 5. Custom Components

Inject custom risk models, optimizers, etc.

```python
from Risk.Covariance.SampleCovariance import SampleCovariance
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=CarrySignal(),
    risk_model=SampleCovariance(),           # Custom risk model
    optimizer=MeanVarianceOptimizer(         # Custom optimizer
        risk_aversion=5.0,
        long_only=False,                     # Allow short positions
    ),
    IC=0.10,                                 # Higher expected IC
)
```

---

## Migration Guide

### From Legacy Backtest to Unified Backtest

**Before (Legacy):**

```python
from Backtest.FuturesBacktest import FuturesBacktest

backtest = FuturesBacktest(
    mdp=mdp,
    signal=CarrySignal(),
)
result = backtest.run_backtest(contracts, dates)
```

**After:**

```python
from Backtest.Backtest import Backtest
from Adapter.FuturesAdapter import FuturesAdapter

backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),  # Add adapter
    signals=CarrySignal(),         # signals (plural)
)
result = backtest.run(contracts, dates)  # run() not run_backtest()
```

**Key Changes:**

1. Import from `Backtest.Backtest`
2. Add `adapter` parameter (e.g., `FuturesAdapter(mdp)`)
3. Use `signals` parameter (plural, supports list)
4. Call `run()` method (not `run_backtest()`)

### From Equity Strategies

**Before (Separate Class):**

```python
from Backtest.EquityBacktest import EquityBacktest

backtest = EquityBacktest(
    returns_df=returns_df,
    signal=MomentumSignal(lookback=20),
)
result = backtest.run()
```

**After:**

```python
from Backtest.Backtest import Backtest

backtest = Backtest(
    signals=MomentumSignal(lookback=20),
)
result = backtest.run_from_dataframe(returns_df, dates)
```

**Key Changes:**

1. Import from `Backtest.Backtest`
2. Use `signals` parameter
3. Call `run_from_dataframe(returns_df, dates)`
4. Pass `dates` explicitly

---

## Advanced Usage

### Hybrid Workflow: Query → DataFrame

Convert query data to DataFrame workflow:

```python
class QueryReturnsConverter:
    """Convert query-based prices to returns DataFrame."""

    def __init__(self, mdp, adapter):
        self.mdp = mdp
        self.adapter = adapter
        self.prev_prices = {}

    def get_returns(self, queries, as_of):
        # Get prices
        df = self.adapter.convert(queries, as_of)

        # Calculate returns
        returns = []
        for row in df.iter_rows(named=True):
            contract = row['contract']
            price = row['price']

            if contract in self.prev_prices:
                ret = (price - self.prev_prices[contract]) / self.prev_prices[contract]
            else:
                ret = 0.0

            self.prev_prices[contract] = price
            returns.append({'date': as_of, 'ticker': contract, 'return': ret})

        return pl.DataFrame(returns)

# Use converter
converter = QueryReturnsConverter(mdp, FuturesAdapter(mdp))

# Collect returns over time
all_returns = []
for d in dates:
    returns_df = converter.get_returns(queries, d)
    all_returns.append(returns_df)

combined = pl.concat(all_returns)

# Run DataFrame workflow
backtest = Backtest(signals=MomentumSignal(lookback=20))
result = backtest.run_from_dataframe(combined, dates)
```

### Custom Signal Implementation

Signals must implement `BaseSignal` interface:

```python
from Signals.Base.BaseSignal import BaseSignal

class CustomSignal(BaseSignal):
    """Custom signal implementation."""

    def __init__(self, param1: float, name: str = 'custom'):
        super().__init__(name=name)
        self.param1 = param1

    def generate(self, df: pl.DataFrame, mdp: Any, as_of: date) -> float:
        """
        Generate signal value for instrument.

        Args:
            df: DataFrame for single instrument
            mdp: Market data provider (may be None for DataFrame workflow)
            as_of: Evaluation date

        Returns:
            float: Signal value (typically z-score)
        """
        # Implement signal logic
        # Return scalar signal value
        return signal_value

# Use custom signal
backtest = Backtest(
    mdp=mdp,
    adapter=FuturesAdapter(mdp),
    signals=CustomSignal(param1=1.5),
)
```

---

## Performance Considerations

### Optimization Tips

1. **Min History**: Set `min_history` appropriately
   - Higher values → more stable covariance, slower warmup
   - Lower values → faster warmup, less stable estimates
   - Recommended: 20-40 periods

2. **Risk Model Choice**:
   - `LedoitWolfShrinkage`: Best for most cases (default)
   - `SampleCovariance`: Fast but noisy
   - Custom models: Profile carefully

3. **Rebalancing Frequency**:
   - Weekly: Good balance for most strategies
   - Daily: Higher turnover, more computation
   - Monthly: Lower turnover, less responsive

4. **Universe Size**:
   - Query workflow: <100 contracts typical
   - DataFrame workflow: Can handle 1000+ tickers
   - Performance scales roughly O(N²) for covariance

### Performance Targets

- Query workflow: <5s for 100 periods × 10 contracts
- DataFrame workflow: <5s for 100 periods × 50 tickers
- Multi-signal: +20-30% overhead per additional signal

---

## Testing

### Unit Testing

```python
import pytest
from Backtest.Backtest import Backtest
from Signals.Futures.CarrySignal import CarrySignal

def test_backtest_requires_signals():
    """Backtest requires at least one signal."""
    with pytest.raises(ValueError, match="Must provide at least one signal"):
        Backtest()

def test_backtest_accepts_signal_list():
    """Backtest accepts list of signals."""
    backtest = Backtest(
        signals=[CarrySignal(), MomentumSignal()]
    )
    assert len(backtest.signals) == 2
```

### Integration Testing

```python
def test_end_to_end_query_workflow():
    """Test complete query workflow."""
    backtest = Backtest(
        mdp=mock_mdp,
        adapter=FuturesAdapter(mock_mdp),
        signals=CarrySignal(),
    )

    result = backtest.run(
        contracts=['SFRZ4', 'SFRH5'],
        dates=[date(2024, 6, 15), date(2024, 6, 22)]
    )

    assert result is not None
    assert len(result.returns) > 0
```

---

## Troubleshooting

### Common Issues

**Issue**: `ValueError: Query-based workflow requires adapter and mdp`

**Solution**: Provide both `mdp` and `adapter` when using `run()`:

```python
backtest = Backtest(
    mdp=market_data_provider,           # Must provide mdp
    adapter=FuturesAdapter(mdp),        # Must provide adapter
    signals=CarrySignal(),
)
```

**Issue**: `ValueError: DataFrame workflow doesn't use adapter`

**Solution**: Don't provide `adapter` when using `run_from_dataframe()`:

```python
# Wrong
backtest = Backtest(
    adapter=FuturesAdapter(mdp),  # Don't provide adapter
    signals=MomentumSignal(),
)
result = backtest.run_from_dataframe(returns_df, dates)

# Correct
backtest = Backtest(
    signals=MomentumSignal(),  # No adapter
)
result = backtest.run_from_dataframe(returns_df, dates)
```

**Issue**: `ValueError: Adapter requires mdp to be provided`

**Solution**: Always provide `mdp` when using `adapter`:

```python
# Wrong
backtest = Backtest(
    adapter=FuturesAdapter(mdp),  # Adapter provided
    mdp=None,                     # But mdp is None
    signals=CarrySignal(),
)

# Correct
backtest = Backtest(
    mdp=market_data_provider,     # Provide mdp
    adapter=FuturesAdapter(mdp),  # Then adapter
    signals=CarrySignal(),
)
```

**Issue**: Empty results (no returns)

**Causes**:
- Not enough history (increase `min_history`)
- Empty input data (check contracts/dates)
- Data quality issues (check adapter output)

**Debug**:

```python
# Check intermediate outputs
result = backtest.run(contracts, dates)

print(f"Signals: {len(result.signals)}")
print(f"Weights: {len(result.weights)}")
print(f"Returns: {len(result.returns)}")

# Inspect signal values
print(result.signals.head())
```

---

## Best Practices

### 1. Workflow Selection

**Use Query Workflow When:**
- Real-time pricing needed
- Working with futures/swaps
- MDP infrastructure available
- Need complex data transformations

**Use DataFrame Workflow When:**
- Pre-computed returns available
- Working with equities/ETFs
- Batch processing
- Simpler data pipeline

### 2. Signal Design

- Keep signals stateless where possible
- Return z-scores (standardized values)
- Handle missing data gracefully
- Document expected input format

### 3. Component Configuration

- Start with defaults (they're sensible!)
- Customize only when needed
- Test with simple mock data first
- Profile before optimizing

### 4. Testing Strategy

- Unit test signals independently
- Integration test full workflows
- Use golden files for determinism
- Test with realistic data volumes

---

## Examples

Complete examples available in `examples/`:

- `examples/run_backtest.py` - Basic futures carry strategy
- `examples/backtest_query_workflow.py` - Query workflow examples
- `examples/backtest_hybrid_workflow.py` - Hybrid workflow patterns
- `examples/custom_components_example.py` - Custom component injection

---

## API Stability

The `Backtest` API is stable. Future enhancements will maintain backward compatibility:

- **Stable**: Constructor signature, `run()`, `run_from_dataframe()`
- **May Extend**: New optional parameters, new workflows
- **Will Not Break**: Existing code will continue to work

---

## Further Reading

- [GRINOLD_KAHN_FRAMEWORK.md](./GRINOLD_KAHN_FRAMEWORK.md) - Theoretical foundation
- [ALPHA_GENERATOR.md](./ALPHA_GENERATOR.md) - Alpha generation details
- [SIGNAL_COMBINATION_METHODS.md](./SIGNAL_COMBINATION_METHODS.md) - Multi-signal strategies
- [USER_GUIDE_STRATEGY_CREATION.md](./USER_GUIDE_STRATEGY_CREATION.md) - Strategy development guide
