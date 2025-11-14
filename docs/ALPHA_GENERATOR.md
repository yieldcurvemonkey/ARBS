# AlphaGenerator - Signal to Expected Return Conversion

**Purpose**: Convert dimensionless signal Z-scores to expected returns (alphas) using the Grinold-Kahn framework

**Date**: 2025-11-11

**Component**: `/home/user/ARBS/Signals/AlphaGenerator.py`

**Tests**: `/home/user/ARBS/tests/unit/signals/test_alpha_generator.py`

---

## Overview

AlphaGenerator solves a critical problem in quantitative portfolio management: **converting signals to expected returns**. Without this conversion, raw signals (Z-scores) would be treated as expected returns, leading to absurd portfolio recommendations.

### The Problem

**Signals are dimensionless Z-scores**:
```
Carry signal = 2.0
```
This means "2 standard deviations above mean carry"

**Without conversion**:
```
Optimizer sees: Expected return = 2.0 = 200% (absurd!)
Result: Massive over-allocation
```

**With AlphaGenerator**:
```
Signal Z = 2.0
IC = 0.05 (5% forecast skill)
Vol = 0.10 (10% volatility)
→ Alpha = 0.05 × 0.10 × 2.0 = 0.01 = 1% (sensible!)
```

### Key Insight

The Grinold-Kahn formula scales signals by:
1. **IC (Information Coefficient)**: How good is the forecast?
2. **Volatility**: How much does the asset move?

This produces **expected returns in the same units as realized returns**, enabling proper portfolio optimization.

---

## Mathematical Foundation

### Grinold-Kahn Formula

**Alpha Generation**:
```
α_i = IC × σ_i × z_i
```

Where:
- **α_i** = Expected excess return for asset i (alpha)
- **IC** = Information Coefficient (forecast skill)
- **σ_i** = Volatility of asset i (annualized)
- **z_i** = Signal Z-score for asset i (standardized)

### Information Coefficient (IC)

**Definition**: Correlation between forecasted returns and realized returns
```
IC = Corr(α_forecast, r_realized)
```

**Typical Values**:
- IC = 0.00 → No skill (random forecast)
- IC = 0.03-0.05 → Typical quant strategy
- IC = 0.10 → Very good strategy
- IC = 0.15 → Exceptional (rare)
- IC = 1.00 → Perfect foresight (impossible)

**Fundamental Law of Active Management**:
```
IR = IC × √BR

where:
  IR = Information Ratio (risk-adjusted active return)
  BR = Breadth (number of independent bets)
```

### Example Calculation

**Scenario**:
```
Signal:         Z = 1.5 (strong positive)
IC:             0.05 (5% forecast skill)
Volatility:     15% annualized
```

**Without Scaling** (wrong):
```
Alpha = Z = 1.5 → 150% expected return (absurd!)
```

**With Grinold-Kahn** (correct):
```
Alpha = IC × Vol × Z
      = 0.05 × 0.15 × 1.5
      = 0.01125
      = 1.125% expected return (sensible!)
```

---

## API Reference

### Constructor

```python
AlphaGenerator(
    IC: float = 0.05,
    vol_estimator: VolatilityEstimator = None
)
```

**Parameters**:
- `IC` (float): Information Coefficient (default: 0.05)
  - Measures forecasting skill
  - Typical range: 0.02 - 0.10
- `vol_estimator` (VolatilityEstimator): Volatility estimator
  - Default: `RealizedVolatility(lookback=60)`
  - Can use any VolatilityEstimator implementation

**Example**:
```python
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Volatility.RealizedVolatility import RealizedVolatility
from Risk.Volatility.EWMAVolatility import EWMAVolatility

# Conservative (low IC)
alpha_gen = AlphaGenerator(IC=0.03)

# Aggressive (high IC, confident in signals)
alpha_gen = AlphaGenerator(IC=0.10)

# Custom volatility estimator
alpha_gen = AlphaGenerator(
    IC=0.05,
    vol_estimator=EWMAVolatility(halflife=20)
)
```

### signals_to_alphas()

```python
signals_to_alphas(
    signals: Dict[str, float],
    returns_history: pd.DataFrame,
    as_of: date
) -> Dict[str, float]
```

**Parameters**:
- `signals` (Dict[str, float]): Map from asset → Z-score
  - Z-scores are standardized signals (mean=0, std=1)
  - Positive = bullish, Negative = bearish, Zero = neutral
- `returns_history` (pd.DataFrame): Historical returns for volatility estimation
  - Rows = time periods, Columns = assets
  - Values = decimal returns (0.01 = 1%)
- `as_of` (date): Current date (for potential time-varying IC)

**Returns**:
- Dict mapping asset → expected return (alpha)
- Returns are in decimal (0.01 = 1% expected return)

**Edge Cases**:
- Missing volatility (no history) → alpha = 0
- Zero volatility (constant returns) → alpha = 0
- Zero signal → alpha = 0
- Zero IC → alpha = 0 (no forecasting skill)

**Example**:
```python
from Signals.AlphaGenerator import AlphaGenerator
import pandas as pd
from datetime import date

alpha_gen = AlphaGenerator(IC=0.05)

# Signals from carry strategy
signals = {
    'SFRZ4': 1.5,    # Strong positive carry
    'SFRH5': -1.0,   # Negative carry
    'SFRM5': 0.5     # Weak positive carry
}

# Historical returns (for volatility estimation)
returns_history = pd.DataFrame({
    'SFRZ4': [...],  # 60+ periods of returns
    'SFRH5': [...],
    'SFRM5': [...]
})

# Convert signals → alphas
alphas = alpha_gen.signals_to_alphas(
    signals,
    returns_history,
    as_of=date(2024, 11, 1)
)

# Result: alphas = {
#     'SFRZ4': 0.0112,   # 1.12% expected return
#     'SFRH5': -0.0075,  # -0.75% expected return
#     'SFRM5': 0.0037    # 0.37% expected return
# }
```

---

## Integration with Other Components

### Data Flow

```
BaseSignal (e.g., CarrySignal)
    ↓
Signals (Z-scores: dimensionless)
    ↓
AlphaGenerator
    ├─ uses → VolatilityEstimator (σ_i from returns)
    └─ applies → IC × Vol × Z formula
    ↓
Alphas (expected returns: %)
    ↓
MeanVarianceOptimizer → Portfolio weights
```

### Usage in Backtest Pipeline

```python
from Signals.CarrySignal import CarrySignal
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Volatility.RealizedVolatility import RealizedVolatility
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

# 1. Generate signals (Z-scores)
carry_signal = CarrySignal()
signals = carry_signal.calculate(market_data, as_of)
# signals = {'SFRZ4': 2.0, 'SFRH5': -1.5, ...}

# 2. Convert signals → alphas (expected returns)
alpha_gen = AlphaGenerator(
    IC=0.05,
    vol_estimator=RealizedVolatility(lookback=60)
)
alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)
# alphas = {'SFRZ4': 0.010, 'SFRH5': -0.0075, ...}

# 3. Optimize portfolio (alphas are now in correct units!)
optimizer = MeanVarianceOptimizer(risk_aversion=2.0)
weights = optimizer.optimize(alphas, covariance_matrix)
# weights = {'SFRZ4': 0.15, 'SFRH5': -0.10, ...}
```

### Combining Multiple Signals

```python
from Signals.CarrySignal import CarrySignal
from Signals.MomentumSignal import MomentumSignal
from Signals.AlphaGenerator import AlphaGenerator

# Generate multiple signals
carry_sig = CarrySignal().calculate(data, as_of)
momentum_sig = MomentumSignal().calculate(data, as_of)

# Combine signals (equal weight)
combined_signals = {}
for asset in carry_sig:
    combined_signals[asset] = (
        0.5 * carry_sig[asset] +
        0.5 * momentum_sig.get(asset, 0)
    )

# Convert combined signals → alphas
alpha_gen = AlphaGenerator(IC=0.05)
alphas = alpha_gen.signals_to_alphas(
    combined_signals,
    returns_history,
    as_of
)
```

---

## Test Coverage

**Location**: `/home/user/ARBS/tests/unit/signals/test_alpha_generator.py`

**Test Classes**:

1. **TestAlphaGeneratorBasics** (4 tests)
   - Import and creation
   - Default IC = 0.05
   - Default vol estimator = RealizedVolatility

2. **TestSignalsToAlphas** (6 tests)
   - Simple alpha conversion
   - Negative signals → negative alphas
   - Zero signal → zero alpha
   - Multiple assets

3. **TestICScaling** (2 tests)
   - Higher IC → proportionally higher alphas
   - Zero IC → zero alphas

4. **TestVolatilityScaling** (2 tests)
   - Higher vol → proportionally higher alphas
   - Zero vol → zero alphas

5. **TestEdgeCases** (3 tests)
   - Missing returns history
   - Empty signals
   - Empty returns history

6. **TestRealWorldExample** (1 test)
   - Carry signal → alpha conversion
   - Demonstrates proper scaling vs absurd 150% return

**Total**: 18 tests, all passing

---

## Usage Examples

### Example 1: Simple Signal Conversion

```python
from Signals.AlphaGenerator import AlphaGenerator
import pandas as pd
import numpy as np
from datetime import date

# Create alpha generator
alpha_gen = AlphaGenerator(IC=0.05)

# Single strong signal
signals = {'SFRZ4': 2.0}  # 2 std devs above mean

# Historical returns (10% annual volatility)
returns_history = pd.DataFrame({
    'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252)
})

# Convert to alpha
alphas = alpha_gen.signals_to_alphas(
    signals,
    returns_history,
    as_of=date(2024, 11, 1)
)

print(f"Signal Z-score: {signals['SFRZ4']}")
print(f"Expected return: {alphas['SFRZ4']:.2%}")
# Output:
# Signal Z-score: 2.0
# Expected return: 1.00%  (much better than 200%!)
```

### Example 2: Multiple Assets

```python
from Signals.AlphaGenerator import AlphaGenerator
import pandas as pd
import numpy as np
from datetime import date

alpha_gen = AlphaGenerator(IC=0.05)

# Portfolio of 3 futures with different signals
signals = {
    'SFRZ4': 2.0,    # Strong buy
    'SFRH5': -1.0,   # Moderate sell
    'SFRM5': 0.0     # Neutral
}

# Different volatilities
np.random.seed(42)
returns_history = pd.DataFrame({
    'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),  # 10% vol
    'SFRH5': np.random.randn(60) * 0.15 / np.sqrt(252),  # 15% vol
    'SFRM5': np.random.randn(60) * 0.08 / np.sqrt(252),  # 8% vol
})

alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

print("Alphas:")
for asset in sorted(alphas.keys()):
    print(f"  {asset}: {alphas[asset]:>7.2%}")
# Output:
# Alphas:
#   SFRM5:    0.00%  (zero signal)
#   SFRH5:   -0.75%  (negative signal, high vol)
#   SFRZ4:    1.00%  (positive signal, moderate vol)
```

### Example 3: IC Sensitivity

```python
from Signals.AlphaGenerator import AlphaGenerator
import pandas as pd
import numpy as np
from datetime import date

# Same signal, different IC assumptions
signals = {'SFRZ4': 1.5}

returns_history = pd.DataFrame({
    'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252)
})

# Conservative IC (low confidence)
alpha_low = AlphaGenerator(IC=0.03).signals_to_alphas(
    signals, returns_history, date(2024, 11, 1)
)

# Standard IC
alpha_mid = AlphaGenerator(IC=0.05).signals_to_alphas(
    signals, returns_history, date(2024, 11, 1)
)

# Aggressive IC (high confidence)
alpha_high = AlphaGenerator(IC=0.10).signals_to_alphas(
    signals, returns_history, date(2024, 11, 1)
)

print(f"Signal: {signals['SFRZ4']:.1f}")
print(f"Alpha (IC=0.03): {alpha_low['SFRZ4']:.2%}")
print(f"Alpha (IC=0.05): {alpha_mid['SFRZ4']:.2%}")
print(f"Alpha (IC=0.10): {alpha_high['SFRZ4']:.2%}")
# Output shows alphas scale linearly with IC
```

### Example 4: Using EWMA Volatility

```python
from Signals.AlphaGenerator import AlphaGenerator
from Risk.Volatility.EWMAVolatility import EWMAVolatility
import pandas as pd
import numpy as np
from datetime import date

# Use EWMA for more responsive volatility
alpha_gen = AlphaGenerator(
    IC=0.05,
    vol_estimator=EWMAVolatility(halflife=20)
)

# Returns with recent volatility spike
returns_history = pd.DataFrame({
    'SFRZ4': np.concatenate([
        np.random.randn(80) * 0.01,  # Low vol period
        np.random.randn(20) * 0.05,  # High vol spike
    ])
})

signals = {'SFRZ4': 1.0}

alphas = alpha_gen.signals_to_alphas(signals, returns_history, date(2024, 11, 1))

print(f"Alpha: {alphas['SFRZ4']:.2%}")
# EWMA captures recent high volatility → higher alpha
```

### Example 5: Carry Strategy (Real World)

```python
from Signals.CarrySignal import CarrySignal
from Signals.AlphaGenerator import AlphaGenerator
from Adapters.FuturesAdapter import FuturesAdapter
import pandas as pd
from datetime import date

# Real carry strategy workflow
adapter = FuturesAdapter(['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5'])
carry_signal = CarrySignal()
alpha_gen = AlphaGenerator(IC=0.05)

as_of = date(2024, 11, 1)

# 1. Get market data
data = adapter.get_data(start=date(2024, 1, 1), end=as_of)

# 2. Calculate carry signals (Z-scores)
signals = carry_signal.calculate(data, as_of)
print("Carry Signals (Z-scores):")
for asset, z in signals.items():
    print(f"  {asset}: {z:>6.2f}")

# 3. Convert to alphas (expected returns)
returns_history = adapter.get_returns_history(as_of, lookback=60)
alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)

print("\nExpected Returns (alphas):")
for asset, alpha in alphas.items():
    print(f"  {asset}: {alpha:>6.2%}")

# Now alphas can be fed to optimizer
# They're in correct units (expected returns, not Z-scores)
```

---

## Design Decisions

### Why Use Volatility Scaling?

**Decision**: Scale signals by volatility: `α = IC × Vol × Z`

**Rationale**:
- High vol assets need larger alphas to justify positions
- Example: If volatility doubles, expected return should double (same Sharpe)
- Without scaling, optimizer over-allocates to low-vol assets

**Example**:
```python
# Without vol scaling:
Signal A: Z=1.0, Vol=10% → Alpha=1.0 → Massive position!
Signal B: Z=1.0, Vol=30% → Alpha=1.0 → Same position (wrong!)

# With vol scaling:
Signal A: Z=1.0, Vol=10% → Alpha=0.5% → Moderate position
Signal B: Z=1.0, Vol=30% → Alpha=1.5% → Proportionally larger
```

### Why Default IC=0.05?

**Decision**: Default IC = 0.05 (5%)

**Rationale**:
- Typical for quantitative strategies
- Conservative (prevents over-confidence)
- Empirically validated in literature
- Grinold & Kahn cite 3-7% as typical

**When to Adjust**:
- Lower (0.02-0.03): New/unvalidated signals
- Higher (0.07-0.10): Proven signals with long track record
- Calibrate from backtest: IC = Corr(α_forecast, r_realized)

### Why Accept Returns History?

**Decision**: Require returns_history parameter (not just volatility dict)

**Rationale**:
- Flexibility: Can use any VolatilityEstimator
- Recency: Volatility estimated fresh each period
- Consistency: Same returns used throughout pipeline
- Testability: Easy to test with synthetic returns

**Alternative Rejected**: Accept pre-computed volatilities
- Less flexible
- Risk of stale volatilities
- Harder to change vol estimation method

---

## Advanced Topics

### Calibrating IC from Backtest

**Method**: Measure correlation between forecasts and realized returns

```python
import numpy as np
from scipy.stats import pearsonr

def calibrate_ic(alphas_forecast, returns_realized):
    """
    Calibrate IC from backtest results.

    Args:
        alphas_forecast: Dict[date, Dict[asset, alpha]]
        returns_realized: Dict[date, Dict[asset, return]]

    Returns:
        IC (Information Coefficient)
    """
    forecasts = []
    realizations = []

    for date in alphas_forecast:
        for asset in alphas_forecast[date]:
            forecasts.append(alphas_forecast[date][asset])
            realizations.append(returns_realized[date][asset])

    ic, p_value = pearsonr(forecasts, realizations)
    print(f"IC: {ic:.3f} (p-value: {p_value:.4f})")
    return ic

# Usage:
# ic = calibrate_ic(backtest_alphas, backtest_returns)
# alpha_gen = AlphaGenerator(IC=ic)  # Use calibrated IC
```

### Time-Varying IC

**Concept**: IC may change over time (regime-dependent)

```python
class AdaptiveAlphaGenerator:
    """Alpha generator with time-varying IC."""

    def __init__(self, ic_history: pd.Series):
        self.ic_history = ic_history

    def signals_to_alphas(self, signals, returns_history, as_of):
        # Use IC for current date
        ic = self.ic_history.loc[as_of]

        # Rest of logic same as AlphaGenerator
        vol_est = RealizedVolatility()
        vols = vol_est.estimate(returns_history)

        alphas = {}
        for asset, z in signals.items():
            vol = vols.get(asset, 0.0)
            alphas[asset] = ic * vol * z

        return alphas
```

### Combining Signals with Different ICs

**Problem**: Different signals have different forecasting skill

**Solution**: Weight by IC

```python
def combine_signals_by_ic(signal_dict, ic_dict):
    """
    Combine multiple signals weighted by IC.

    Args:
        signal_dict: {'carry': {...}, 'momentum': {...}}
        ic_dict: {'carry': 0.05, 'momentum': 0.03}

    Returns:
        Combined signals (IC-weighted)
    """
    # Normalize ICs to sum to 1
    total_ic = sum(ic_dict.values())
    weights = {name: ic / total_ic for name, ic in ic_dict.items()}

    # Combine signals
    combined = {}
    all_assets = set()
    for signals in signal_dict.values():
        all_assets.update(signals.keys())

    for asset in all_assets:
        combined[asset] = sum(
            weights[name] * signal_dict[name].get(asset, 0)
            for name in signal_dict
        )

    return combined

# Usage:
carry_signals = carry_sig.calculate(data, as_of)
momentum_signals = momentum_sig.calculate(data, as_of)

combined_signals = combine_signals_by_ic(
    {'carry': carry_signals, 'momentum': momentum_signals},
    {'carry': 0.05, 'momentum': 0.03}
)

# Use overall IC for alpha generation
avg_ic = np.mean([0.05, 0.03])
alpha_gen = AlphaGenerator(IC=avg_ic)
alphas = alpha_gen.signals_to_alphas(combined_signals, returns_history, as_of)
```

---

## Common Pitfalls

### Pitfall 1: Using Raw Signals as Alphas

**Wrong**:
```python
# Treating Z-scores as expected returns
signals = carry_signal.calculate(data, as_of)
optimizer.optimize(signals, cov_matrix)  # WRONG! Z=2.0 ≠ 200% return
```

**Right**:
```python
# Convert to alphas first
signals = carry_signal.calculate(data, as_of)
alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)
optimizer.optimize(alphas, cov_matrix)  # Correct! Alpha ~1%
```

### Pitfall 2: Overconfident IC

**Wrong**:
```python
# Assuming perfect foresight
alpha_gen = AlphaGenerator(IC=0.50)  # Way too high!
```

**Right**:
```python
# Use realistic IC from empirical evidence
alpha_gen = AlphaGenerator(IC=0.05)  # Typical for quant strategies

# Or calibrate from backtest
ic = calibrate_ic(forecast_history, realized_history)
alpha_gen = AlphaGenerator(IC=ic)
```

### Pitfall 3: Ignoring Volatility Changes

**Wrong**:
```python
# Using static volatility estimates
vols = {'SFRZ4': 0.15, 'SFRH5': 0.12}  # Fixed
# Problem: Vol changes over time!
```

**Right**:
```python
# Re-estimate volatility each period
alpha_gen = AlphaGenerator(
    IC=0.05,
    vol_estimator=EWMAVolatility(halflife=30)  # Adapts to regime changes
)
# Volatility estimated fresh from returns_history each time
```

### Pitfall 4: Mixing Signal Scales

**Wrong**:
```python
# Signals not standardized
signals = {
    'SFRZ4': 0.5,    # Some arbitrary scale
    'SFRH5': 10.0    # Different arbitrary scale
}
alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)
# Problem: Signals not comparable!
```

**Right**:
```python
# Standardize signals to Z-scores first
from Signals.BaseSignal import standardize_signals

raw_signals = carry_signal.calculate_raw(data, as_of)
signals = standardize_signals(raw_signals)  # Mean=0, Std=1
alphas = alpha_gen.signals_to_alphas(signals, returns_history, as_of)
```

---

## Related Components

- **BaseSignal**: Generates signals (Z-scores) that AlphaGenerator converts
- **VolatilityEstimator**: Estimates volatilities used in alpha scaling
- **MeanVarianceOptimizer**: Receives alphas to optimize portfolio weights
- **Backtest**: Orchestrates signal → alpha → weights flow

---

## References

- Grinold, R.C., and Kahn, R.N. (1999). *Active Portfolio Management* (2nd ed.)
  - Chapter 4: Exceptional Return, Benchmarks, and Value Added
  - Alpha formula: `α = IC × Vol × Z`
  - Fundamental Law: `IR = IC × √BR`

- Qian, E., Hua, R., and Sorensen, E. (2007). *Quantitative Equity Portfolio Management*
  - Chapter 5: Signal Generation and Processing
  - Discusses signal standardization and scaling

- Clarke, R., de Silva, H., and Thorley, S. (2002). "Portfolio Constraints and the Fundamental Law of Active Management"
  - *Financial Analysts Journal*, 58(5), 48-66
  - Extends Grinold-Kahn framework with constraints
