# ReturnsCalculator - Price to Return Conversion

**Purpose**: Convert price changes to returns at the data layer, ensuring all downstream components work with stationary data

**Date**: 2025-11-11

**Component**: `/home/user/ARBS/Risk/Returns/ReturnsCalculator.py`

**Tests**: `/home/user/ARBS/tests/unit/risk/test_returns_calculator.py`

---

## Overview

ReturnsCalculator performs the critical transformation from **prices** (non-stationary levels) to **returns** (stationary differences). This transformation happens ONCE at the data layer, allowing all downstream components to work with proper stationary data.

### Why This Matters

**The Problem**: Prices are non-stationary random walks
- Variance increases with time
- Covariance of prices is meaningless
- Statistical properties change over time

**The Solution**: Returns are stationary differences
- Well-defined statistical moments
- Covariance of returns is meaningful
- Portfolio math requires returns: `r_portfolio = Σ w_i × r_i`

### Key Insight

In the Grinold-Kahn framework, ALL portfolio mathematics operates on **returns**, not prices:
- Covariance matrix Σ is computed from returns
- Alphas are expected RETURNS
- Portfolio variance: `σ²_p = w' Σ w` requires return covariance

---

## Mathematical Foundation

### Percent Returns (Default)

**Formula**:
```
r_t = (P_t - P_{t-1}) / P_{t-1}
```

**Properties**:
- Scale-free (comparable across assets)
- Additive for portfolios: `r_p = Σ w_i × r_i`
- Standard in Grinold-Kahn framework

**Example**:
```python
Price: $95 → $96
Return: (96 - 95) / 95 = 0.0105 = 1.05%
```

### Log Returns (Alternative)

**Formula**:
```
r_t = log(P_t / P_{t-1})
```

**Properties**:
- Time-additive: `r_{0→t} = Σ r_i`
- Symmetric (±10% change has same magnitude)
- Approximately equal to percent for small changes: `log(1 + x) ≈ x`
- Better statistical properties (more normal)

**Example**:
```python
Price: $95 → $96
Return: log(96/95) = 0.0104 = 1.04%
```

### Relationship

For small returns (< 5%), percent and log returns are nearly identical:

```python
Price change: +1%
Percent return: 0.0100
Log return:     0.0099  (difference < 0.01%)
```

---

## API Reference

### Constructor

```python
ReturnsCalculator(method: str = "percent")
```

**Parameters**:
- `method` (str): Calculation method
  - `"percent"` (default): Percent returns `(P_t - P_{t-1}) / P_{t-1}`
  - `"log"`: Log returns `log(P_t / P_{t-1})`

**Raises**:
- `ValueError`: If method not in `{"percent", "log"}`

**Example**:
```python
from Risk.Returns.ReturnsCalculator import ReturnsCalculator

# Percent returns (default, standard for Grinold-Kahn)
calc = ReturnsCalculator(method="percent")

# Log returns (alternative)
calc_log = ReturnsCalculator(method="log")
```

### calculate_returns()

```python
calculate_returns(
    curr_prices: Dict[str, float],
    prev_prices: Dict[str, float]
) -> Dict[str, float]
```

**Parameters**:
- `curr_prices`: Current prices (map: asset → price)
- `prev_prices`: Previous prices (map: asset → price)

**Returns**:
- Dictionary mapping asset → return (decimal)

**Edge Cases**:
- Missing previous price → return = 0
- Zero previous price → return = 0
- Negative previous price → return = 0
- New asset (not in previous) → return = 0

**Example**:
```python
calc = ReturnsCalculator(method="percent")

prev_prices = {
    'SFRZ4': 95.0,
    'SFRH5': 94.0,
    'SFRM5': 94.8
}

curr_prices = {
    'SFRZ4': 96.0,
    'SFRH5': 94.5,
    'SFRM5': 95.0
}

returns = calc.calculate_returns(curr_prices, prev_prices)
# Returns:
# {
#     'SFRZ4': 0.0105,  # (96-95)/95 = 1.05%
#     'SFRH5': 0.0053,  # (94.5-94)/94 = 0.53%
#     'SFRM5': 0.0021   # (95-94.8)/94.8 = 0.21%
# }
```

---

## Integration with Other Components

### Data Flow

```
Raw Prices
    ↓
ReturnsCalculator → Returns (stationary)
    ↓
    ├──→ VolatilityEstimator (estimates σ from returns)
    ├──→ CovarianceEstimator (estimates Σ from returns)
    └──→ AlphaGenerator (uses Vol estimated from returns)
```

### Usage in Backtest Pipeline

```python
from Risk.Returns.ReturnsCalculator import ReturnsCalculator
from Risk.Volatility.RealizedVolatility import RealizedVolatility

# Create calculator
returns_calc = ReturnsCalculator(method="percent")

# Convert prices → returns at data layer
prev_prices = {'SFRZ4': 95.0, 'SFRH5': 94.0}
curr_prices = {'SFRZ4': 96.0, 'SFRH5': 94.5}
returns = returns_calc.calculate_returns(curr_prices, prev_prices)

# Now all downstream components work with returns
# Example: Estimate volatility FROM RETURNS
vol_est = RealizedVolatility(lookback=60)
returns_history = pd.DataFrame(...)  # Historical returns
volatilities = vol_est.estimate(returns_history)
```

### Integration Points

**FuturesAdapter** (before ReturnsCalculator):
```python
class FuturesAdapter:
    def get_prices(self, as_of: date) -> Dict[str, float]:
        """Get current prices for all assets."""
        prices = {}
        for contract in self.contracts:
            future = self.query.get_future(contract)
            prices[contract] = future.get_price(as_of)
        return prices
```

**MinimalBacktest** (uses ReturnsCalculator):
```python
class MinimalBacktest:
    def __init__(self):
        self.returns_calc = ReturnsCalculator(method="percent")

    def run(self):
        for date in self.dates:
            curr_prices = self.adapter.get_prices(date)
            prev_prices = self.adapter.get_prices(prev_date)

            # Convert to returns ONCE
            returns = self.returns_calc.calculate_returns(
                curr_prices, prev_prices
            )

            # Track realized returns for P&L
            # ...
```

---

## Test Coverage

**Location**: `/home/user/ARBS/tests/unit/risk/test_returns_calculator.py`

**Test Classes**:

1. **TestPercentReturns** (6 tests)
   - Simple percent return calculation
   - Negative returns
   - Zero return (no price change)
   - Multiple assets

2. **TestLogReturns** (4 tests)
   - Log return calculation
   - Negative price changes
   - Approximate equivalence to percent for small changes

3. **TestEdgeCases** (5 tests)
   - Zero previous price → return 0
   - Negative previous price → return 0
   - Missing previous price → return 0
   - New assets → return 0
   - Empty inputs → empty output

4. **TestDefaultMethod** (2 tests)
   - Default method is "percent"
   - Invalid method raises ValueError

**Total**: 17 tests, all passing

---

## Usage Examples

### Example 1: Simple Single-Asset Return

```python
from Risk.Returns.ReturnsCalculator import ReturnsCalculator

calc = ReturnsCalculator(method="percent")

prev_prices = {'SFRZ4': 100.0}
curr_prices = {'SFRZ4': 105.0}

returns = calc.calculate_returns(curr_prices, prev_prices)
print(returns['SFRZ4'])  # 0.05 (5%)
```

### Example 2: Multi-Asset Portfolio Returns

```python
calc = ReturnsCalculator(method="percent")

# Portfolio of 3 SOFR futures
prev_prices = {
    'SFRZ4': 95.0,   # Dec 2024
    'SFRH5': 94.0,   # Mar 2025
    'SFRM5': 94.8    # Jun 2025
}

curr_prices = {
    'SFRZ4': 96.0,
    'SFRH5': 94.5,
    'SFRM5': 95.0
}

returns = calc.calculate_returns(curr_prices, prev_prices)

# Calculate portfolio return with equal weights
weights = {'SFRZ4': 1/3, 'SFRH5': 1/3, 'SFRM5': 1/3}
portfolio_return = sum(weights[asset] * returns[asset]
                      for asset in returns)
print(f"Portfolio return: {portfolio_return:.4f}")
# Output: Portfolio return: 0.0060 (0.60%)
```

### Example 3: Comparison of Methods

```python
calc_percent = ReturnsCalculator(method="percent")
calc_log = ReturnsCalculator(method="log")

prev_prices = {'SFRZ4': 100.0}
curr_prices = {'SFRZ4': 105.0}

r_percent = calc_percent.calculate_returns(curr_prices, prev_prices)
r_log = calc_log.calculate_returns(curr_prices, prev_prices)

print(f"Percent return: {r_percent['SFRZ4']:.6f}")  # 0.050000
print(f"Log return:     {r_log['SFRZ4']:.6f}")      # 0.048790
print(f"Difference:     {abs(r_percent['SFRZ4'] - r_log['SFRZ4']):.6f}")
# For 5% change, difference is ~0.001 (0.1%)
```

### Example 4: Time Series of Returns

```python
import pandas as pd
from Risk.Returns.ReturnsCalculator import ReturnsCalculator

calc = ReturnsCalculator(method="percent")

# Historical price series
prices = {
    date(2024, 1, 1): {'SFRZ4': 95.0},
    date(2024, 1, 8): {'SFRZ4': 96.0},
    date(2024, 1, 15): {'SFRZ4': 95.5},
    date(2024, 1, 22): {'SFRZ4': 97.0},
}

# Calculate returns for each period
dates = sorted(prices.keys())
returns_series = []

for i in range(1, len(dates)):
    prev_date = dates[i-1]
    curr_date = dates[i]

    returns = calc.calculate_returns(
        prices[curr_date],
        prices[prev_date]
    )
    returns_series.append(returns['SFRZ4'])

# Create returns DataFrame
returns_df = pd.Series(returns_series, index=dates[1:])
print(returns_df)
# 2024-01-08    0.010526
# 2024-01-15   -0.005208
# 2024-01-22    0.015707
```

### Example 5: Handling Edge Cases

```python
calc = ReturnsCalculator(method="percent")

# New asset appearing mid-backtest
prev_prices = {'SFRZ4': 95.0}
curr_prices = {
    'SFRZ4': 96.0,
    'SFRH5': 94.0  # New asset, not in previous
}

returns = calc.calculate_returns(curr_prices, prev_prices)
print(returns)
# {
#     'SFRZ4': 0.010526,  # Normal calculation
#     'SFRH5': 0.0        # No previous price → 0 return
# }

# This is safe: won't crash, just treats as 0 return for first period
# Subsequent periods will calculate normally
```

---

## Design Decisions

### Why at Data Layer?

**Decision**: Convert prices → returns ONCE at data ingestion

**Rationale**:
- Single source of truth for returns
- Prevents inconsistencies from multiple conversions
- Downstream components always work with stationary data
- Clear separation of concerns

**Alternative Rejected**: Convert as needed in each component
- Risk of inconsistent calculations
- Duplicated code
- Harder to test

### Why Default to Percent Returns?

**Decision**: Default `method="percent"`

**Rationale**:
- Standard in Grinold-Kahn framework
- Additive for portfolios: `r_p = Σ w_i × r_i`
- Intuitive interpretation (5% gain)
- Industry standard for portfolio management

**When to Use Log Returns**:
- Time series analysis (additivity over time)
- Statistical modeling (more normal distribution)
- Long-horizon returns (symmetry property)

### Why Return 0 for Edge Cases?

**Decision**: Missing/invalid previous prices → return = 0

**Rationale**:
- Safe default (no crash)
- Neutral impact on portfolio
- Allows graceful handling of new assets
- Better than NaN (can still compute portfolio return)

**Alternative Rejected**: Raise exception or return NaN
- Breaks backtest flow
- Requires explicit handling everywhere
- NaN propagation causes downstream errors

---

## Common Pitfalls

### Pitfall 1: Confusing Prices with Returns

**Wrong**:
```python
# Treating price as return
covariance = np.cov(price_series_1, price_series_2)  # WRONG!
```

**Right**:
```python
# Calculate returns first
returns_1 = calc.calculate_returns(curr_prices_1, prev_prices_1)
returns_2 = calc.calculate_returns(curr_prices_2, prev_prices_2)
covariance = np.cov(returns_1, returns_2)  # Correct
```

### Pitfall 2: Multiple Conversions

**Wrong**:
```python
# Converting multiple times (inconsistent)
returns_1 = calc.calculate_returns(curr, prev)
returns_2 = (curr['X'] - prev['X']) / prev['X']  # Different calculation!
```

**Right**:
```python
# Convert ONCE at data layer, reuse everywhere
returns = calc.calculate_returns(curr, prev)
# All downstream components use same returns
```

### Pitfall 3: Mixing Methods

**Wrong**:
```python
# Mixing percent and log returns
calc1 = ReturnsCalculator(method="percent")
calc2 = ReturnsCalculator(method="log")

r1 = calc1.calculate_returns(...)
r2 = calc2.calculate_returns(...)
combined = r1 + r2  # WRONG! Different scales
```

**Right**:
```python
# Use consistent method throughout
calc = ReturnsCalculator(method="percent")
r1 = calc.calculate_returns(...)
r2 = calc.calculate_returns(...)
combined = r1 + r2  # OK, same method
```

---

## Related Components

- **VolatilityEstimator**: Estimates volatility FROM returns
- **CovarianceEstimator**: Estimates covariance FROM returns
- **AlphaGenerator**: Uses volatility (estimated from returns) to scale signals
- **MinimalBacktest**: Uses returns to calculate P&L

---

## References

- Campbell, J.Y., Lo, A.W., and MacKinlay, A.C. (1997). *The Econometrics of Financial Markets*
  - Chapter 1: The Predictability of Asset Returns
  - Discussion of return calculation methods and properties

- Grinold, R.C., and Kahn, R.N. (1999). *Active Portfolio Management*
  - Uses percent returns throughout
  - Portfolio return as weighted sum: `r_p = Σ w_i × r_i`
