# VolatilityEstimator - Asset Volatility Estimation

**Purpose**: Estimate asset volatilities from historical returns for use in alpha generation and risk modeling

**Date**: 2025-11-11

**Component**: `/home/user/ARBS/Risk/Volatility/VolatilityEstimator.py`

**Implementations**:
- `/home/user/ARBS/Risk/Volatility/RealizedVolatility.py`
- `/home/user/ARBS/Risk/Volatility/EWMAVolatility.py`

**Tests**: `/home/user/ARBS/tests/unit/risk/test_volatility_estimator.py`

---

## Overview

VolatilityEstimator provides a unified interface for estimating asset volatilities from historical returns. Volatility is a critical input to:

1. **Alpha Generation**: `α = IC × Vol × Z` (Grinold-Kahn)
2. **Covariance Matrix**: `Cov[i,j] = Corr[i,j] × Vol[i] × Vol[j]`
3. **Risk Decomposition**: Understanding portfolio risk sources

### Key Insight

**Volatility is estimated from RETURNS, not prices**:
- Returns are stationary (constant statistical properties)
- Prices are non-stationary (variance grows with time)
- Standard deviation of returns is meaningful
- Standard deviation of prices is not

---

## Mathematical Foundation

### Basic Formula

**Annualized Volatility**:
```
Vol = StdDev(returns) × √T
```

Where:
- `StdDev(returns)` = Standard deviation of period returns
- `T` = Annualization factor (252 for daily, 52 for weekly, 12 for monthly)

**Example** (daily returns):
```
Daily StdDev = 0.01 (1%)
Annual Vol = 0.01 × √252 = 0.159 (15.9%)
```

### Why Annualize?

Volatility scales with square root of time:
```
Vol[T periods] = Vol[1 period] × √T
```

This allows comparison across different frequencies:
- Daily vol → Annual vol: multiply by √252
- Weekly vol → Annual vol: multiply by √52
- Monthly vol → Annual vol: multiply by √12

---

## Implementations

### 1. RealizedVolatility

**Method**: Historical standard deviation over lookback window

**Formula**:
```
Vol[i] = StdDev(returns[i, -lookback:]) × √T
```

**Properties**:
- Simple and robust
- Equal weight to all observations in window
- Works well for stable volatility regimes
- Standard choice for long-only portfolios

**When to Use**:
- Stable markets
- Long lookback periods (60+ days)
- When responsiveness not critical

**Example**:
```python
from Risk.Volatility.RealizedVolatility import RealizedVolatility

vol_est = RealizedVolatility(
    lookback=60,              # Use last 60 periods
    annualization_factor=252  # Daily data
)

returns = pl.DataFrame({
    'SFRZ4': [0.01, -0.01, 0.02, ...],  # 60+ daily returns
    'SFRH5': [0.005, -0.005, 0.01, ...]
})

vols = vol_est.estimate(returns)
# Returns: {'SFRZ4': 0.158, 'SFRH5': 0.102}  (annualized)
```

### 2. EWMAVolatility

**Method**: Exponentially weighted moving average

**Formula**:
```
EWMA[t] = λ × EWMA[t-1] + (1-λ) × r[t]²
Vol[t] = √EWMA[t] × √T

where: λ = exp(-ln(2) / halflife)
```

**Properties**:
- More weight to recent observations
- Responds quickly to volatility changes
- Detects regime shifts
- Standard in risk management (RiskMetrics)

**When to Use**:
- Volatile markets (regime changes)
- Risk management (need quick response)
- Options pricing (implied vol estimation)
- Shorter horizons

**Example**:
```python
from Risk.Volatility.EWMAVolatility import EWMAVolatility

vol_est = EWMAVolatility(
    halflife=30,              # Weight halves every 30 periods
    annualization_factor=252  # Daily data
)

# Same returns DataFrame as above
vols = vol_est.estimate(returns)
# Returns: {'SFRZ4': 0.165, 'SFRH5': 0.098}  (more responsive)
```

### Comparison

| Feature | RealizedVolatility | EWMAVolatility |
|---------|-------------------|----------------|
| **Weighting** | Equal | Exponential decay |
| **Responsiveness** | Slow | Fast |
| **Smoothness** | High | Low |
| **Regime Detection** | Poor | Good |
| **Computation** | Simple | Moderate |
| **Use Case** | Stable markets | Volatile markets |

---

## API Reference

### Abstract Base Class: VolatilityEstimator

```python
class VolatilityEstimator(ABC):
    @abstractmethod
    def estimate(self, returns: pl.DataFrame) -> Dict[str, float]:
        """
        Estimate annualized volatility for each asset.

        Args:
            returns: Historical returns DataFrame
                     Rows = time periods, Columns = assets
                     Values = decimal returns (0.01 = 1%)

        Returns:
            Dict mapping asset → annualized volatility
        """
        pass
```

### RealizedVolatility

**Constructor**:
```python
RealizedVolatility(
    lookback: int = 60,
    annualization_factor: float = 252
)
```

**Parameters**:
- `lookback` (int): Number of periods to use (default: 60)
- `annualization_factor` (float): Scaling factor (default: 252 for daily)

**Method**:
```python
estimate(returns: pl.DataFrame) -> Dict[str, float]
```

**Example**:
```python
vol_est = RealizedVolatility(lookback=60, annualization_factor=252)
returns_df = pl.DataFrame(...)  # 100 days × N assets
vols = vol_est.estimate(returns_df)  # Uses last 60 days
```

### EWMAVolatility

**Constructor**:
```python
EWMAVolatility(
    halflife: int = 30,
    annualization_factor: float = 252
)
```

**Parameters**:
- `halflife` (int): Half-life in periods (default: 30)
  - After `halflife` periods, weight decays to 50%
- `annualization_factor` (float): Scaling factor (default: 252)

**Method**:
```python
estimate(returns: pl.DataFrame) -> Dict[str, float]
```

**Example**:
```python
vol_est = EWMAVolatility(halflife=30, annualization_factor=252)
returns_df = pl.DataFrame(...)
vols = vol_est.estimate(returns_df)  # Uses EWMA
```

---

## Integration with Other Components

### Data Flow

```
ReturnsCalculator
    ↓
Returns (stationary)
    ↓
VolatilityEstimator → Volatilities (σ_i)
    ↓
    ├──→ AlphaGenerator (α = IC × Vol × Z)
    └──→ CovarianceEstimator (Cov = Corr × Vol_i × Vol_j)
```

### Usage in AlphaGenerator

```python
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Volatility.RealizedVolatility import RealizedVolatility

# Create volatility estimator
vol_est = RealizedVolatility(lookback=60)

# AlphaGenerator uses it internally
alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=vol_est)

# Convert signals → alphas (uses Vol internally)
signals = {'SFRZ4': 2.0, 'SFRH5': -1.0}  # Z-scores
returns_history = pl.DataFrame(...)
alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)

# Inside: α_i = IC × Vol_i × Z_i
# Vol_i comes from vol_estimator.estimate(returns_history)
```

### Usage in Covariance Estimation

```python
from Risk.Volatility.RealizedVolatility import RealizedVolatility
import numpy as np

# Estimate volatilities
vol_est = RealizedVolatility(lookback=60)
returns = pl.DataFrame(...)  # Historical returns
vols = vol_est.estimate(returns)

# Calculate correlation matrix
corr_matrix = returns.corr().values

# Build covariance from correlation and volatilities
vol_vec = np.array([vols[asset] for asset in returns.columns])
cov_matrix = corr_matrix * np.outer(vol_vec, vol_vec)
# Cov[i,j] = Corr[i,j] × Vol[i] × Vol[j]
```

---

## Test Coverage

**Location**: `/home/user/ARBS/tests/unit/risk/test_volatility_estimator.py`

**Test Classes**:

1. **TestRealizedVolatility** (9 tests)
   - Simple volatility calculation
   - Multiple assets
   - Lookback period handling
   - Annualization factor scaling
   - Zero volatility (constant returns)
   - Insufficient data handling

2. **TestEWMAVolatility** (5 tests)
   - EWMA calculation
   - Responsiveness comparison
   - Halflife parameter effects

3. **TestEdgeCases** (4 tests)
   - Single period returns
   - Empty returns DataFrame
   - NaN handling

4. **TestDefaultParameters** (2 tests)
   - Default lookback = 60
   - Default annualization = 252

**Total**: 15 tests, all passing

---

## Usage Examples

### Example 1: Simple Volatility Estimation

```python
from Risk.Volatility.RealizedVolatility import RealizedVolatility
import polars as pl
import numpy as np

# Create realized volatility estimator
vol_est = RealizedVolatility(lookback=60, annualization_factor=252)

# Generate sample returns (100 days of daily returns)
np.random.seed(42)
returns = pl.DataFrame({
    'SFRZ4': np.random.randn(100) * 0.01,  # 1% daily vol
    'SFRH5': np.random.randn(100) * 0.015, # 1.5% daily vol
})

# Estimate annualized volatilities
vols = vol_est.estimate(returns)

print(f"SFRZ4 volatility: {vols['SFRZ4']:.2%}")  # ~15.9% annual
print(f"SFRH5 volatility: {vols['SFRH5']:.2%}")  # ~23.8% annual
```

### Example 2: Comparing Realized vs EWMA

```python
from Risk.Volatility.RealizedVolatility import RealizedVolatility
from Risk.Volatility.EWMAVolatility import EWMAVolatility
import polars as pl
import numpy as np

# Low vol regime → high vol regime
returns = pl.DataFrame({
    'ASSET': [0.001] * 50 + list(np.random.randn(50) * 0.05)
})

# Realized volatility (equal weights)
vol_realized = RealizedVolatility(lookback=100)
vols_realized = vol_realized.estimate(returns)

# EWMA volatility (more weight to recent)
vol_ewma = EWMAVolatility(halflife=20)
vols_ewma = vol_ewma.estimate(returns)

print(f"Realized vol: {vols_realized['ASSET']:.2%}")  # Lower (averages both regimes)
print(f"EWMA vol:     {vols_ewma['ASSET']:.2%}")      # Higher (weights recent high vol)
```

### Example 3: Weekly Returns

```python
from Risk.Volatility.RealizedVolatility import RealizedVolatility
import polars as pl
import numpy as np

# Weekly returns (52 weeks)
weekly_returns = pl.DataFrame({
    'SFRZ4': np.random.randn(52) * 0.02,  # 2% weekly vol
})

# Use weekly annualization factor
vol_est = RealizedVolatility(
    lookback=52,               # 1 year of weekly data
    annualization_factor=52    # √52 to annualize
)

vols = vol_est.estimate(weekly_returns)
print(f"Annual volatility: {vols['SFRZ4']:.2%}")  # ~14.4% annual
```

### Example 4: Custom Halflife for EWMA

```python
from Risk.Volatility.EWMAVolatility import EWMAVolatility
import polars as pl
import numpy as np

# Create returns with regime change
returns = pl.DataFrame({
    'ASSET': np.concatenate([
        np.random.randn(80) * 0.01,   # Low vol
        np.random.randn(20) * 0.03,   # High vol spike
    ])
})

# Fast adaptation (short halflife)
vol_fast = EWMAVolatility(halflife=10)
vols_fast = vol_fast.estimate(returns)

# Slow adaptation (long halflife)
vol_slow = EWMAVolatility(halflife=60)
vols_slow = vol_slow.estimate(returns)

print(f"Fast EWMA: {vols_fast['ASSET']:.2%}")  # Captures recent spike
print(f"Slow EWMA: {vols_slow['ASSET']:.2%}")  # Still influenced by past
```

### Example 5: Multi-Asset Portfolio

```python
from Risk.Volatility.RealizedVolatility import RealizedVolatility
import polars as pl
import numpy as np

# Portfolio of 5 futures contracts
np.random.seed(42)
returns = pl.DataFrame({
    f'SFR{contract}': np.random.randn(100) * vol
    for contract, vol in zip(['Z4', 'H5', 'M5', 'U5', 'Z5'],
                             [0.01, 0.012, 0.011, 0.013, 0.014])
})

# Estimate all volatilities
vol_est = RealizedVolatility(lookback=60, annualization_factor=252)
vols = vol_est.estimate(returns)

# Display results
print("Asset Volatilities (Annualized):")
for asset, vol in sorted(vols.items()):
    print(f"  {asset}: {vol:.2%}")
```

---

## Design Decisions

### Why Abstract Base Class?

**Decision**: Define VolatilityEstimator as ABC with `estimate()` method

**Rationale**:
- Allows multiple implementations (Realized, EWMA, GARCH, etc.)
- Components can use any estimator via polymorphism
- Easy to add new estimators without changing dependent code
- Clear interface contract

**Example**:
```python
# AlphaGenerator works with any VolatilityEstimator
def __init__(self, IC, vol_estimator: VolatilityEstimator):
    self.vol_estimator = vol_estimator  # Any implementation works

# Can swap implementations easily:
alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=RealizedVolatility())
# or
alpha_gen = AlphaGenerator(IC=0.05, vol_estimator=EWMAVolatility())
```

### Why Default lookback=60?

**Decision**: Default lookback of 60 periods for RealizedVolatility

**Rationale**:
- 60 days ≈ 3 months of trading data
- Sufficient for stable vol estimates
- Not too long (captures recent regime)
- Industry standard (RiskMetrics uses 60-day)
- Balances bias vs variance

**When to Adjust**:
- More stable assets → longer lookback (120, 252)
- More volatile assets → shorter lookback (20, 30)
- Frequent regime changes → use EWMA instead

### Why Default annualization_factor=252?

**Decision**: Default to 252 (daily trading days per year)

**Rationale**:
- Standard for equity/futures markets
- Excludes weekends and holidays
- Industry convention
- Matches daily return data

**Common Values**:
- Daily: 252 (trading days)
- Weekly: 52 (weeks per year)
- Monthly: 12 (months per year)
- Hourly: 252 × 6.5 = 1638 (trading hours)

---

## Advanced Topics

### Volatility Forecasting

**Problem**: Historical vol ≠ Future vol

**Solutions**:
1. **EWMA**: Adapts quickly to regime changes
2. **GARCH**: Models volatility clustering
3. **Regime Switching**: Separate models for different regimes

**Example** (EWMA responds to spikes):
```python
# Volatility spike in recent data
returns = pl.DataFrame({
    'ASSET': [0.001] * 90 + [0.05, -0.05, 0.04, -0.04, 0.03]
})

# EWMA captures the spike
vol_ewma = EWMAVolatility(halflife=10)
vols = vol_ewma.estimate(returns)
print(f"Vol after spike: {vols['ASSET']:.2%}")  # High

# Realized averages it out
vol_real = RealizedVolatility(lookback=100)
vols_real = vol_real.estimate(returns)
print(f"Vol averaged: {vols_real['ASSET']:.2%}")  # Lower
```

### Volatility Term Structure

Different horizons have different volatilities:
```python
# Short-term volatility (more reactive)
vol_short = RealizedVolatility(lookback=20, annualization_factor=252)

# Long-term volatility (smoother)
vol_long = RealizedVolatility(lookback=252, annualization_factor=252)

vols_short = vol_short.estimate(returns)
vols_long = vol_long.estimate(returns)

# Compare term structure
print(f"20-day vol:  {vols_short['ASSET']:.2%}")
print(f"252-day vol: {vols_long['ASSET']:.2%}")
```

### Correlation Between Volatility and Returns

**Leverage Effect**: Negative correlation between returns and volatility
- Down markets → volatility increases
- Up markets → volatility decreases

**Implication**: Simple historical vol may underestimate downside risk

---

## Common Pitfalls

### Pitfall 1: Using Price Volatility

**Wrong**:
```python
# Taking std dev of PRICES (meaningless!)
price_vol = prices.std() * np.sqrt(252)  # WRONG
```

**Right**:
```python
# Calculate returns first, then vol
returns = calc.calculate_returns(curr_prices, prev_prices)
vol_est = RealizedVolatility()
vols = vol_est.estimate(returns_df)  # Correct
```

### Pitfall 2: Forgetting to Annualize

**Wrong**:
```python
# Using raw std dev (not annualized)
vol = returns.std()  # Period vol, not annual
```

**Right**:
```python
# Multiply by √T to annualize
vol = returns.std() * np.sqrt(252)  # Annual vol
# Or use VolatilityEstimator (handles this automatically)
vol_est = RealizedVolatility(annualization_factor=252)
vols = vol_est.estimate(returns)
```

### Pitfall 3: Wrong Annualization Factor

**Wrong**:
```python
# Using wrong factor for data frequency
weekly_returns = ...
vol_est = RealizedVolatility(
    lookback=52,
    annualization_factor=252  # WRONG! Data is weekly, not daily
)
```

**Right**:
```python
# Match factor to data frequency
weekly_returns = ...
vol_est = RealizedVolatility(
    lookback=52,
    annualization_factor=52  # Correct for weekly data
)
```

### Pitfall 4: Lookback Too Short

**Wrong**:
```python
# Too few observations for stable estimate
vol_est = RealizedVolatility(lookback=5)  # Too short!
vols = vol_est.estimate(returns)  # Very noisy
```

**Right**:
```python
# Use sufficient lookback (at least 20-30 periods)
vol_est = RealizedVolatility(lookback=60)  # Better
vols = vol_est.estimate(returns)
```

---

## Related Components

- **ReturnsCalculator**: Converts prices → returns (input to VolatilityEstimator)
- **AlphaGenerator**: Uses volatilities to scale signals: `α = IC × Vol × Z`
- **CovarianceEstimator**: Uses volatilities to build covariance: `Cov = Corr × Vol_i × Vol_j`
- **TearSheet**: Uses volatility for Sharpe ratio calculation

---

## References

- **RiskMetrics Technical Document** (1996)
  - J.P. Morgan/Reuters
  - Introduced EWMA with λ = 0.94 (halflife ≈ 11 days)
  - Industry standard for volatility estimation

- Grinold, R.C., and Kahn, R.N. (1999). *Active Portfolio Management*
  - Chapter 4: Exceptional Return, Benchmarks, and Value Added
  - Uses volatility in alpha scaling: `α = IC × Vol × Z`

- Engle, R.F. (1982). "Autoregressive Conditional Heteroscedasticity with Estimates of the Variance of United Kingdom Inflation"
  - Original ARCH paper (Nobel Prize 2003)
  - Foundation for time-varying volatility models
