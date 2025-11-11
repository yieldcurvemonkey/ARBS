# TearSheet - Strategy Performance Analysis

**Purpose**: Generate comprehensive performance analysis with metrics, drawdowns, and cumulative returns

**Date**: 2025-11-11

**Component**: `/home/user/ARBS/Analysis/TearSheet.py`

**Tests**: `/home/user/ARBS/tests/unit/analysis/test_tear_sheet.py`

---

## Overview

TearSheet provides post-backtest performance analysis inspired by pyfolio but tailored for futures/swaps strategies. It transforms a return series into actionable insights about strategy performance, risk, and drawdowns.

### What is a Tear Sheet?

A "tear sheet" is a one-page summary of investment performance. The term comes from the practice of tearing a page from a bound report. In quantitative finance, it typically includes:

- **Summary Statistics**: Return, volatility, Sharpe ratio
- **Drawdown Analysis**: Maximum drawdown, recovery periods
- **Time Aggregation**: Monthly/annual returns
- **Visualization**: Cumulative returns, drawdown plots

### Key Metrics

**Performance**:
- Total Return: Cumulative return over entire period
- Annual Return: Geometric mean annualized
- Sharpe Ratio: Risk-adjusted return

**Risk**:
- Annual Volatility: Standard deviation annualized
- Max Drawdown: Largest peak-to-trough decline
- Calmar Ratio: Return / |Max Drawdown|

---

## Mathematical Foundation

### Total Return

**Formula** (compounded):
```
Total Return = ∏(1 + r_t) - 1
```

**Example**:
```
Returns: [0.02, 0.01, -0.01, 0.03]
Total = (1.02 × 1.01 × 0.99 × 1.03) - 1 = 0.0517 = 5.17%
```

### Annualized Return

**Formula** (geometric mean):
```
Annual Return = (1 + Total Return)^(T / N) - 1

where:
  T = periods per year (252 for daily, 52 for weekly)
  N = number of periods in series
```

**Example**:
```
Total Return = 10% over 100 days
Annual = (1.10)^(252/100) - 1 = 26.6%
```

### Sharpe Ratio

**Formula** (annualized):
```
Sharpe = (E[r] - r_f) × √T / σ

where:
  E[r] = arithmetic mean return
  r_f = risk-free rate
  σ = standard deviation of returns
  T = annualization factor
```

**Note**: Uses arithmetic mean (not geometric) because Sharpe measures excess return per unit of risk.

**Example**:
```
Daily returns: mean = 0.001, std = 0.015
Sharpe = (0.001 - 0) × √252 / 0.015 = 1.06
```

### Drawdown

**Formula**:
```
Drawdown_t = (Wealth_t - Peak_t) / Peak_t

where:
  Wealth_t = cumulative value at time t
  Peak_t = maximum wealth up to time t
```

**Properties**:
- Always ≤ 0 (at peak, drawdown = 0)
- Measures distance from peak
- Max Drawdown = min(Drawdown_t)

**Example**:
```
Wealth: [100, 110, 105, 95, 100]
Peak:   [100, 110, 110, 110, 110]
DD:     [0%, 0%, -4.5%, -13.6%, -9.1%]
Max DD: -13.6%
```

### Calmar Ratio

**Formula**:
```
Calmar = Annual Return / |Max Drawdown|
```

**Interpretation**:
- Higher is better
- Measures return per unit of downside risk
- Alternative to Sharpe (focuses on worst case)

**Example**:
```
Annual Return = 15%
Max Drawdown = -10%
Calmar = 15% / 10% = 1.5
```

---

## API Reference

### TearSheetMetrics

**Dataclass** holding summary statistics:

```python
@dataclass
class TearSheetMetrics:
    total_return: float       # Cumulative return
    annual_return: float      # Geometric mean annualized
    annual_volatility: float  # StdDev × √T
    sharpe_ratio: float       # (Return - Rf) / Vol
    max_drawdown: float       # Worst peak-to-trough
    calmar_ratio: float       # Return / |Max DD|
```

**String Representation**:
```python
print(metrics)
# Performance Metrics
# ===================
# Total Return:       10.23%
# Annual Return:      12.50%
# Annual Volatility:  15.80%
# Sharpe Ratio:        0.79
# Max Drawdown:      -12.30%
# Calmar Ratio:        1.02
```

### TearSheet

**Constructor**:
```python
TearSheet(
    returns: pd.Series,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0
)
```

**Parameters**:
- `returns` (pd.Series): Return series (decimal, e.g., 0.01 = 1%)
  - Index should be DatetimeIndex for time aggregation
- `periods_per_year` (int): Annualization factor (default: 252)
  - 252 = daily, 52 = weekly, 12 = monthly
- `risk_free_rate` (float): Risk-free rate for Sharpe (annualized, default: 0.0)

**Example**:
```python
from Analysis.TearSheet import TearSheet
import pandas as pd

# Daily returns
returns = pd.Series([0.01, -0.01, 0.02, ...], index=pd.date_range(...))

# Create tear sheet
tear_sheet = TearSheet(
    returns,
    periods_per_year=252,
    risk_free_rate=0.03  # 3% risk-free rate
)
```

### calculate_metrics()

```python
calculate_metrics() -> TearSheetMetrics
```

**Returns**: TearSheetMetrics with all performance statistics

**Example**:
```python
metrics = tear_sheet.calculate_metrics()
print(f"Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
print(f"Max Drawdown: {metrics.max_drawdown:.2%}")
```

### calculate_drawdowns()

```python
calculate_drawdowns() -> pd.Series
```

**Returns**: Series of drawdowns (negative values, 0 at peaks)

**Example**:
```python
drawdowns = tear_sheet.calculate_drawdowns()
max_dd = drawdowns.min()
print(f"Max Drawdown: {max_dd:.2%}")

# Plot drawdowns
drawdowns.plot(title="Drawdown Over Time")
```

### calculate_cumulative_returns()

```python
calculate_cumulative_returns() -> pd.Series
```

**Returns**: Series of cumulative returns (starting from 0)

**Example**:
```python
cum_returns = tear_sheet.calculate_cumulative_returns()
print(f"Final Return: {cum_returns.iloc[-1]:.2%}")

# Plot cumulative returns
cum_returns.plot(title="Cumulative Returns")
```

### aggregate_monthly_returns()

```python
aggregate_monthly_returns() -> pd.Series
```

**Returns**: Monthly return series (Period index)

**Example**:
```python
monthly = tear_sheet.aggregate_monthly_returns()
print(monthly)
# 2024-01    2.5%
# 2024-02   -1.2%
# 2024-03    3.8%
```

### aggregate_annual_returns()

```python
aggregate_annual_returns() -> pd.Series
```

**Returns**: Annual return series (year index)

**Example**:
```python
annual = tear_sheet.aggregate_annual_returns()
print(annual)
# 2022    15.3%
# 2023    -5.2%
# 2024    22.1%
```

---

## Integration with Other Components

### Data Flow

```
MinimalBacktest
    ↓
Portfolio Returns (time series)
    ↓
TearSheet
    ├─ calculate_metrics() → Summary statistics
    ├─ calculate_drawdowns() → Risk analysis
    └─ aggregate_monthly/annual() → Time analysis
    ↓
Performance Report
```

### Usage After Backtest

```python
from Backtest.MinimalBacktest import MinimalBacktest
from Analysis.TearSheet import TearSheet

# Run backtest
backtest = MinimalBacktest(...)
result = backtest.run()

# Analyze with TearSheet
tear_sheet = TearSheet(
    result.returns,  # Time series of portfolio returns
    periods_per_year=52  # Weekly rebalancing
)

# Get metrics
metrics = tear_sheet.calculate_metrics()
print(metrics)

# Analyze drawdowns
drawdowns = tear_sheet.calculate_drawdowns()
print(f"Max Drawdown: {drawdowns.min():.2%}")
print(f"Current Drawdown: {drawdowns.iloc[-1]:.2%}")

# Time aggregation
annual_returns = tear_sheet.aggregate_annual_returns()
print("Annual Returns:")
print(annual_returns)
```

---

## Test Coverage

**Location**: `/home/user/ARBS/tests/unit/analysis/test_tear_sheet.py`

**Test Classes**:

1. **TestTearSheetMetrics** (7 tests)
   - Total return calculation
   - Sharpe ratio calculation
   - Max drawdown calculation
   - Annualized return
   - Volatility calculation
   - Calmar ratio

2. **TestDrawdownCalculation** (3 tests)
   - No drawdown for positive returns
   - Drawdown series tracking
   - Recovery from drawdown

3. **TestCumulativeReturns** (3 tests)
   - Cumulative returns from zero
   - Compounding calculation
   - Negative cumulative returns

4. **TestMonthlyAnnualAggregation** (2 tests)
   - Monthly aggregation
   - Annual aggregation

5. **TestEdgeCases** (4 tests)
   - Empty returns series
   - Single return
   - All zero returns
   - Constant positive returns

**Total**: 19 tests, all passing

---

## Usage Examples

### Example 1: Basic Metrics

```python
from Analysis.TearSheet import TearSheet
import pandas as pd
import numpy as np

# Generate sample returns (252 days)
np.random.seed(42)
dates = pd.date_range('2024-01-01', periods=252, freq='D')
returns = pd.Series(
    np.random.randn(252) * 0.01 + 0.0005,  # Mean 0.05% daily
    index=dates
)

# Create tear sheet
tear_sheet = TearSheet(returns, periods_per_year=252)

# Calculate metrics
metrics = tear_sheet.calculate_metrics()
print(metrics)
# Performance Metrics
# ===================
# Total Return:       13.45%
# Annual Return:      13.45%
# Annual Volatility:  15.87%
# Sharpe Ratio:        0.85
# Max Drawdown:       -8.23%
# Calmar Ratio:        1.63
```

### Example 2: Drawdown Analysis

```python
from Analysis.TearSheet import TearSheet
import pandas as pd
import matplotlib.pyplot as plt

# Returns with significant drawdown
returns = pd.Series([
    0.02, 0.01, 0.03, -0.05, -0.08, -0.03, 0.02, 0.04, 0.05, 0.06
], index=pd.date_range('2024-01-01', periods=10, freq='W'))

tear_sheet = TearSheet(returns, periods_per_year=52)

# Analyze drawdowns
drawdowns = tear_sheet.calculate_drawdowns()

print(f"Maximum Drawdown: {drawdowns.min():.2%}")
print(f"Current Drawdown: {drawdowns.iloc[-1]:.2%}")

# Find drawdown periods
underwater = drawdowns[drawdowns < -0.05]  # Drawdowns > 5%
print(f"Periods with DD > 5%: {len(underwater)}")

# Plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

# Cumulative returns
cum_returns = tear_sheet.calculate_cumulative_returns()
(cum_returns * 100).plot(ax=ax1, title="Cumulative Returns (%)")

# Drawdowns
(drawdowns * 100).plot(ax=ax2, title="Drawdown (%)", color='red')
ax2.fill_between(drawdowns.index, 0, drawdowns * 100, color='red', alpha=0.3)
plt.tight_layout()
plt.show()
```

### Example 3: Monthly and Annual Returns

```python
from Analysis.TearSheet import TearSheet
import pandas as pd
import numpy as np

# 2 years of daily returns
np.random.seed(42)
dates = pd.date_range('2023-01-01', '2024-12-31', freq='D')
returns = pd.Series(
    np.random.randn(len(dates)) * 0.015 + 0.0004,
    index=dates
)

tear_sheet = TearSheet(returns, periods_per_year=252)

# Monthly returns
monthly = tear_sheet.aggregate_monthly_returns()
print("Monthly Returns:")
print(monthly.head(6))
# 2023-01    2.3%
# 2023-02   -1.5%
# 2023-03    4.2%
# ...

# Annual returns
annual = tear_sheet.aggregate_annual_returns()
print("\nAnnual Returns:")
print(annual)
# 2023    12.5%
# 2024    -3.2%

# Best/worst months
print(f"\nBest Month:  {monthly.max():.2%} ({monthly.idxmax()})")
print(f"Worst Month: {monthly.min():.2%} ({monthly.idxmin()})")
```

### Example 4: Comparing Strategies

```python
from Analysis.TearSheet import TearSheet
import pandas as pd
import numpy as np

# Generate returns for two strategies
np.random.seed(42)
dates = pd.date_range('2024-01-01', periods=252, freq='D')

strategy_a = pd.Series(np.random.randn(252) * 0.012 + 0.0006, index=dates)
strategy_b = pd.Series(np.random.randn(252) * 0.008 + 0.0004, index=dates)

# Analyze both
tear_sheet_a = TearSheet(strategy_a, periods_per_year=252)
tear_sheet_b = TearSheet(strategy_b, periods_per_year=252)

metrics_a = tear_sheet_a.calculate_metrics()
metrics_b = tear_sheet_b.calculate_metrics()

# Compare
print("Strategy Comparison:")
print(f"{'Metric':<20} {'Strategy A':>12} {'Strategy B':>12}")
print("-" * 46)
print(f"{'Annual Return':<20} {metrics_a.annual_return:>11.2%} {metrics_b.annual_return:>11.2%}")
print(f"{'Annual Volatility':<20} {metrics_a.annual_volatility:>11.2%} {metrics_b.annual_volatility:>11.2%}")
print(f"{'Sharpe Ratio':<20} {metrics_a.sharpe_ratio:>11.2f} {metrics_b.sharpe_ratio:>11.2f}")
print(f"{'Max Drawdown':<20} {metrics_a.max_drawdown:>11.2%} {metrics_b.max_drawdown:>11.2%}")
print(f"{'Calmar Ratio':<20} {metrics_a.calmar_ratio:>11.2f} {metrics_b.calmar_ratio:>11.2f}")
```

### Example 5: Weekly Rebalancing

```python
from Analysis.TearSheet import TearSheet
import pandas as pd
import numpy as np

# Weekly returns (52 weeks)
np.random.seed(42)
dates = pd.date_range('2024-01-01', periods=52, freq='W')
weekly_returns = pd.Series(
    np.random.randn(52) * 0.02 + 0.002,
    index=dates
)

# Use weekly annualization
tear_sheet = TearSheet(
    weekly_returns,
    periods_per_year=52,  # Weekly data
    risk_free_rate=0.03   # 3% risk-free rate
)

metrics = tear_sheet.calculate_metrics()
print(metrics)

# Note: metrics are annualized correctly for weekly data
print(f"\nWeekly mean: {weekly_returns.mean():.3%}")
print(f"Annual return: {metrics.annual_return:.2%}")
print(f"Ratio: {metrics.annual_return / weekly_returns.mean():.1f}x")
# Should be approximately 52x
```

---

## Design Decisions

### Why Use Geometric Mean for Return?

**Decision**: Annual return uses geometric mean, not arithmetic

**Rationale**:
- Geometric mean compounds correctly
- Arithmetic mean overstates multi-period returns
- Geometric is "time-weighted return"

**Example**:
```python
Returns: [+50%, -50%]

Arithmetic Mean: (0.50 + (-0.50)) / 2 = 0% (misleading!)
True Return: 1.50 × 0.50 = 0.75 = -25% (geometric is correct)
```

### Why Use Arithmetic Mean for Sharpe?

**Decision**: Sharpe ratio uses arithmetic mean return

**Rationale**:
- Sharpe measures excess return per unit of risk
- Arithmetic mean is unbiased estimator of expected return
- Standard in academic literature (Sharpe 1966)
- Geometric mean would understate expected return

**Example**:
```python
# For Sharpe: use arithmetic mean
sharpe = returns.mean() × sqrt(252) / returns.std()

# For total return: use geometric mean
total = (1 + returns).prod() - 1
```

### Why Separate Cumulative Returns Method?

**Decision**: Provide `calculate_cumulative_returns()` separate from metrics

**Rationale**:
- Time series needed for plotting
- Different from scalar total return
- Allows analysis of return path (not just endpoint)

**Usage**:
```python
# Scalar total return
metrics = tear_sheet.calculate_metrics()
total = metrics.total_return  # Single number

# Time series for plotting
cum_returns = tear_sheet.calculate_cumulative_returns()
cum_returns.plot()  # Can visualize entire path
```

### Why Default risk_free_rate=0.0?

**Decision**: Default to 0% risk-free rate

**Rationale**:
- Simplifies analysis (Sharpe = Return / Vol)
- User can adjust if needed
- Appropriate for absolute return strategies
- Futures strategies don't have funding cost (collateralized)

**When to Adjust**:
```python
# For equity long-only (compare to T-bills)
tear_sheet = TearSheet(returns, risk_free_rate=0.03)

# For absolute return strategies (futures, swaps)
tear_sheet = TearSheet(returns, risk_free_rate=0.0)  # Default
```

---

## Advanced Topics

### Underwater Duration

**Concept**: How long does strategy stay in drawdown?

```python
def calculate_underwater_duration(tear_sheet):
    """Calculate duration of underwater periods (in drawdown)."""
    drawdowns = tear_sheet.calculate_drawdowns()

    # Find underwater periods (DD < 0)
    underwater = drawdowns < 0

    # Calculate consecutive underwater days
    underwater_periods = []
    duration = 0

    for is_underwater in underwater:
        if is_underwater:
            duration += 1
        else:
            if duration > 0:
                underwater_periods.append(duration)
            duration = 0

    if duration > 0:
        underwater_periods.append(duration)

    return {
        'max_duration': max(underwater_periods) if underwater_periods else 0,
        'avg_duration': np.mean(underwater_periods) if underwater_periods else 0,
        'current_duration': duration,
    }

# Usage:
duration_stats = calculate_underwater_duration(tear_sheet)
print(f"Max underwater: {duration_stats['max_duration']} periods")
print(f"Currently underwater: {duration_stats['current_duration']} periods")
```

### Rolling Sharpe Ratio

**Concept**: Track Sharpe ratio over time

```python
def rolling_sharpe(returns, window=60, periods_per_year=252):
    """Calculate rolling Sharpe ratio."""
    rolling_mean = returns.rolling(window).mean()
    rolling_std = returns.rolling(window).std()

    rolling_sharpe = (rolling_mean / rolling_std) * np.sqrt(periods_per_year)
    return rolling_sharpe

# Usage:
returns = tear_sheet.returns
rolling_sr = rolling_sharpe(returns, window=60)
rolling_sr.plot(title="60-Day Rolling Sharpe Ratio")

print(f"Current Sharpe (60d): {rolling_sr.iloc[-1]:.2f}")
print(f"Average Sharpe (60d): {rolling_sr.mean():.2f}")
```

### Benchmark Comparison

**Concept**: Compare strategy to benchmark

```python
def compare_to_benchmark(strategy_returns, benchmark_returns):
    """Compare strategy to benchmark using TearSheet."""
    from Analysis.TearSheet import TearSheet

    # Analyze both
    strategy_ts = TearSheet(strategy_returns, periods_per_year=252)
    benchmark_ts = TearSheet(benchmark_returns, periods_per_year=252)

    strat_metrics = strategy_ts.calculate_metrics()
    bench_metrics = benchmark_ts.calculate_metrics()

    # Calculate alpha (excess return)
    alpha = strat_metrics.annual_return - bench_metrics.annual_return

    # Calculate information ratio
    tracking_error = (strategy_returns - benchmark_returns).std() * np.sqrt(252)
    information_ratio = alpha / tracking_error if tracking_error > 0 else np.nan

    return {
        'alpha': alpha,
        'tracking_error': tracking_error,
        'information_ratio': information_ratio,
        'strategy_sharpe': strat_metrics.sharpe_ratio,
        'benchmark_sharpe': bench_metrics.sharpe_ratio,
    }

# Usage:
comparison = compare_to_benchmark(strategy_returns, spy_returns)
print(f"Alpha: {comparison['alpha']:.2%}")
print(f"Information Ratio: {comparison['information_ratio']:.2f}")
```

---

## Common Pitfalls

### Pitfall 1: Wrong Annualization Factor

**Wrong**:
```python
# Weekly returns but using daily factor
weekly_returns = ...
tear_sheet = TearSheet(weekly_returns, periods_per_year=252)  # WRONG
```

**Right**:
```python
# Match factor to data frequency
weekly_returns = ...
tear_sheet = TearSheet(weekly_returns, periods_per_year=52)  # Correct
```

### Pitfall 2: Using Prices Instead of Returns

**Wrong**:
```python
# Analyzing price series instead of returns
prices = pd.Series([100, 105, 103, 108, ...])
tear_sheet = TearSheet(prices)  # WRONG! Needs returns
```

**Right**:
```python
# Calculate returns first
prices = pd.Series([100, 105, 103, 108, ...])
returns = prices.pct_change().dropna()
tear_sheet = TearSheet(returns)  # Correct
```

### Pitfall 3: Confusing Arithmetic vs Geometric Mean

**Wrong**:
```python
# Using arithmetic mean for total return
total_return = returns.mean() * len(returns)  # WRONG! Doesn't compound
```

**Right**:
```python
# Use geometric mean (compounding)
total_return = (1 + returns).prod() - 1  # Correct
# Or let TearSheet handle it:
metrics = tear_sheet.calculate_metrics()
total_return = metrics.total_return
```

### Pitfall 4: Ignoring Drawdown Duration

**Wrong**:
```python
# Only looking at max drawdown magnitude
max_dd = metrics.max_drawdown  # -15%
# But ignoring that it lasted 6 months!
```

**Right**:
```python
# Consider both magnitude and duration
drawdowns = tear_sheet.calculate_drawdowns()
max_dd = drawdowns.min()

# Calculate recovery time
dd_start = drawdowns[drawdowns < max_dd * 0.95].index[0]
dd_end = drawdowns[drawdowns == 0].index[-1] if (drawdowns == 0).any() else None

if dd_end:
    recovery_days = (dd_end - dd_start).days
    print(f"Max DD: {max_dd:.2%}, Recovery: {recovery_days} days")
```

---

## Related Components

- **MinimalBacktest**: Produces return series that TearSheet analyzes
- **VolatilityEstimator**: TearSheet calculates realized volatility similarly
- **AlphaGenerator**: IC can be measured using TearSheet metrics

---

## References

- Sharpe, W.F. (1966). "Mutual Fund Performance"
  - *Journal of Business*, 39(1), 119-138
  - Original Sharpe ratio definition

- Bailey, D.H., and López de Prado, M. (2012). "The Sharpe Ratio Efficient Frontier"
  - *Journal of Risk*, 15(2), 3-44
  - Statistical properties of Sharpe ratio estimation

- pyfolio: https://github.com/quantopian/pyfolio
  - Open-source performance analysis library
  - Inspiration for TearSheet design
