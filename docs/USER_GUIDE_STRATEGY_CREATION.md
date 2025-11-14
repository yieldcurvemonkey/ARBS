# User Guide: Strategy Creation in ARBS

**Complete guide from beginner to advanced**

Version: 1.0
Date: 2025-11-11

---

## Table of Contents

- [Getting Started](#getting-started)
  - [Installation](#installation)
  - [Your First Strategy in 5 Minutes](#your-first-strategy-in-5-minutes)
  - [Understanding the Output](#understanding-the-output)
- [Beginner Tutorial](#beginner-tutorial)
  - [Simple Carry Strategy](#simple-carry-strategy)
  - [Running a Backtest](#running-a-backtest)
  - [Common Pitfalls and Troubleshooting](#common-pitfalls-and-troubleshooting)
- [Intermediate Tutorial](#intermediate-tutorial)
  - [Creating Multi-Signal Strategies](#creating-multi-signal-strategies)
  - [Custom Signals: Extending the Framework](#custom-signals-extending-the-framework)
  - [Risk Management and Position Sizing](#risk-management-and-position-sizing)
- [Advanced Tutorial](#advanced-tutorial)
  - [Event-Driven Strategies with Custom Rebalancing](#event-driven-strategies-with-custom-rebalancing)
  - [Regime-Switching Strategies](#regime-switching-strategies)
  - [Transaction Cost Modeling](#transaction-cost-modeling)
- [Reference](#reference)
  - [Complete YAML Schema](#complete-yaml-schema)
  - [Available Signals](#available-signals)
  - [Risk Models](#risk-models)
  - [Optimizer Options](#optimizer-options)
- [Appendices](#appendices)
  - [FAQ](#faq)
  - [Glossary](#glossary)
  - [Further Reading](#further-reading)

---

## Getting Started

### Installation

Prerequisites:
- Python 3.9+
- ARBS framework installed
- Market data access configured

Install dependencies:
```bash
# Navigate to ARBS directory
cd /home/user/ARBS

# Install required packages
pip install pyyaml jsonschema

# Verify installation
python -c "import yaml, jsonschema; print('OK')"
```

### Your First Strategy in 5 Minutes

Let's create a simple carry strategy step by step.

**Step 1: Copy a template**

```bash
# Copy the simple carry template
cp strategies/examples/carry_strategy.yaml my_first_strategy.yaml
```

**Step 2: Customize the YAML file**

Edit `my_first_strategy.yaml`:

```yaml
strategy:
  name: "My First Carry Strategy"  # Give it your own name
  type: "carry"
  description: "My first ARBS strategy!"
  mode: "signal"

universe:
  asset_class: "futures"
  instruments:
    - "SFRZ4"  # Keep these or add your own
    - "SFRH5"
    - "SFRM5"

signals:
  - name: "futures_carry"
    type: "carry"
    config:
      standardize: true

alpha:
  IC: 0.05  # Start with conservative IC

risk:
  covariance: "ledoit_wolf"
  lookback: 60

optimizer:
  type: "mean_variance"
  risk_aversion: 1.0
  constraints:
    long_only: true

execution:
  rebalance_frequency: "weekly"

backtest:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
  initial_capital: 1000000.0
```

**Step 3: Run your strategy**

```python
from Strategies.Factory.StrategyFactory import StrategyFactory
from Backtest.Backtest import Backtest

# Load strategy from YAML
factory = StrategyFactory()
strategy = factory.create_from_yaml('my_first_strategy.yaml')

# Run backtest
bt = Backtest(
    strategy=strategy,
    start_date='2024-01-01',
    end_date='2024-12-31'
)
results = bt.run()

# View results
print(f"Total Return: {results.total_return:.2%}")
print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
print(f"IC: {results.ic:.3f}")
```

**Congratulations!** You just created and ran your first strategy.

### Understanding the Output

When you run a backtest, you'll get a `BacktestResult` object with:

- **Returns**: Time series of daily/weekly returns
- **Sharpe Ratio**: Risk-adjusted return (higher is better)
- **Information Coefficient (IC)**: Forecast skill (0.05 is good, 0.10 is very good)
- **Total Return**: Cumulative return over backtest period
- **Max Drawdown**: Largest peak-to-trough decline
- **Turnover**: How often positions change

```python
# Access results
print(results.returns)  # pandas Series of returns
print(results.metrics)  # Dict of all metrics

# Plot cumulative returns
import matplotlib.pyplot as plt
results.returns.cumsum().plot()
plt.title('Cumulative Returns')
plt.show()
```

---

## Beginner Tutorial

### Simple Carry Strategy

**What is Carry?**

Carry is the return from holding an asset, assuming prices don't change. For futures:
- **Backwardation**: Front contract > Back contract → Positive carry (profit from roll)
- **Contango**: Front contract < Back contract → Negative carry (loss from roll)

**Strategy Logic:**
1. Calculate carry for each futures contract
2. Rank contracts by carry (high to low)
3. Long high carry contracts, short (or underweight) low carry contracts

**YAML Configuration:**

```yaml
# strategies/my_carry.yaml
strategy:
  name: "Simple Carry"
  type: "carry"
  mode: "signal"

universe:
  asset_class: "futures"
  instruments: ["SFRZ4", "SFRH5", "SFRM5", "SFRU5"]

signals:
  - type: "carry"
    config:
      method: "calendar_spread"  # Front/back price difference
      annualize: true            # Convert to annual rate
      standardize: true          # Z-score normalization

alpha:
  IC: 0.05  # Assume 5% correlation between forecast and returns

risk:
  covariance: "ledoit_wolf"  # Shrinkage estimator (robust)
  lookback: 60               # 60 days of history

optimizer:
  type: "mean_variance"
  risk_aversion: 1.0  # 1.0 = balanced risk/return
  constraints:
    long_only: true   # Only long positions

execution:
  rebalance_frequency: "weekly"

backtest:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
  initial_capital: 1000000.0
```

### Running a Backtest

**Method 1: Python Script**

```python
# run_backtest.py
from Strategies.Factory.StrategyFactory import StrategyFactory
from Backtest.Backtest import Backtest
from MDP.Futures.FuturesMDP import FuturesMDP
import pandas as pd

# Load strategy
factory = StrategyFactory()
strategy = factory.create_from_yaml('strategies/my_carry.yaml')

# Setup market data
mdp = FuturesMDP(source='live')

# Run backtest
bt = Backtest(
    strategy=strategy,
    market_data=mdp,
    start_date='2024-01-01',
    end_date='2024-12-31'
)
results = bt.run()

# Display results
print("\n=== Backtest Results ===")
print(f"Total Return: {results.total_return:.2%}")
print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
print(f"IC: {results.ic:.3f}")
print(f"Max Drawdown: {results.max_drawdown:.2%}")
print(f"Turnover: {results.turnover:.2%}")

# Save results
results.to_csv('backtest_results.csv')
```

Run it:
```bash
python run_backtest.py
```

**Method 2: Jupyter Notebook**

```python
# In Jupyter notebook
%load_ext autoreload
%autoreload 2

from Strategies.Factory.StrategyFactory import StrategyFactory
from Backtest.Backtest import Backtest

# Load and run
strategy = StrategyFactory().create_from_yaml('strategies/my_carry.yaml')
results = Backtest(strategy=strategy).run()

# Visualize
import matplotlib.pyplot as plt

fig, axes = plt.subplots(2, 1, figsize=(12, 8))

# Cumulative returns
results.returns.cumsum().plot(ax=axes[0], title='Cumulative Returns')
axes[0].grid(True)

# Rolling Sharpe
rolling_sharpe = (
    results.returns.rolling(window=20).mean() /
    results.returns.rolling(window=20).std() *
    np.sqrt(252)
)
rolling_sharpe.plot(ax=axes[1], title='Rolling 20-Day Sharpe Ratio')
axes[1].axhline(y=0, color='r', linestyle='--')
axes[1].grid(True)

plt.tight_layout()
plt.show()
```

### Common Pitfalls and Troubleshooting

#### Problem 1: "No market data for instrument X"

**Cause**: Instrument not available in market data source

**Solution**:
```yaml
# Check your instruments are valid
universe:
  instruments:
    - "SFRZ4"  # ✓ Valid SOFR future
    - "INVALIDCODE"  # ✗ Will fail
```

Verify instruments before running:
```python
from MDP.Futures.FuturesMDP import FuturesMDP

mdp = FuturesMDP()
available = mdp.get_available_instruments()
print(available)
```

#### Problem 2: "Covariance matrix is singular"

**Cause**: Not enough price history or too many instruments

**Solution**:
1. Increase `risk.lookback` (more history)
2. Use Ledoit-Wolf shrinkage (more robust)
3. Reduce number of instruments

```yaml
risk:
  covariance: "ledoit_wolf"  # Use shrinkage
  lookback: 120              # Increase history
```

#### Problem 3: "Weights don't sum to 1.0"

**Cause**: Numerical precision or optimizer failure

**Solution**: Check optimizer constraints:
```yaml
optimizer:
  type: "mean_variance"
  constraints:
    long_only: true  # Ensures weights >= 0 and sum to 1
```

#### Problem 4: "Strategy has zero positions"

**Cause**: Signals are too weak or optimizer is too conservative

**Solution**:
1. Increase IC (stronger alphas)
2. Decrease risk_aversion (take more risk)
3. Check signal standardization

```yaml
alpha:
  IC: 0.10  # Increase from 0.05 (more aggressive)

optimizer:
  risk_aversion: 0.5  # Decrease from 1.0 (less conservative)
```

---

## Intermediate Tutorial

### Creating Multi-Signal Strategies

**Why Multiple Signals?**

Fundamental Law of Active Management:
```
IR = IC × √BR
```

Where:
- IR = Information Ratio (risk-adjusted alpha)
- IC = Information Coefficient (forecast skill)
- BR = Breadth (number of independent bets)

**Key insight**: Combining uncorrelated signals increases √BR → higher IR

**Example: Carry + Momentum**

```yaml
# strategies/carry_momentum.yaml
strategy:
  name: "Carry + Momentum"
  type: "multi_signal"
  mode: "signal"

universe:
  asset_class: "futures"
  instruments: ["SFRZ4", "SFRH5", "SFRM5", "SFRU5", "SFRZ5", "SFRH6"]

signals:
  # Signal 1: Carry (value signal)
  - name: "carry"
    type: "carry"
    config:
      standardize: true
    weight: 1.0

  # Signal 2: Momentum (trend signal)
  - name: "momentum"
    type: "momentum"
    config:
      lookback_days: 30
      standardize: true
    weight: 1.0

alpha:
  IC: 0.05  # Average IC across signals

risk:
  covariance: "ledoit_wolf"
  lookback: 60

optimizer:
  type: "mean_variance"
  risk_aversion: 1.0
  constraints:
    long_only: true
    max_position: 0.30  # More diversified

execution:
  rebalance_frequency: "weekly"

backtest:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
  initial_capital: 1000000.0
```

**How Signals are Combined:**

Default: Equal-weight average
```python
z_combined = mean(z_carry, z_momentum)
```

**Analysis: Are signals diversifying?**

```python
import pandas as pd
import numpy as np

# Load strategy
strategy = StrategyFactory().create_from_yaml('strategies/carry_momentum.yaml')

# Calculate signal correlations
carry_signals = strategy.signals[0].history
momentum_signals = strategy.signals[1].history

# Convert to DataFrame
df = pd.DataFrame({
    'carry': carry_signals,
    'momentum': momentum_signals
})

# Calculate correlation
corr = df.corr()
print(f"Signal Correlation:\n{corr}")

# Ideally: correlation < 0.5 (good diversification)
# If correlation > 0.8 (signals are redundant)
```

### Custom Signals: Extending the Framework

**When to use custom signals:**
- Proprietary indicators
- Macroeconomic data
- Alternative data sources
- Specialized calculations

**Step 1: Create signal class**

```python
# strategies/custom/macro_signal.py
from Signals.Base.BaseSignal import BaseSignal
import pandas as pd
from typing import Dict, List, Any, Optional
from datetime import date

class MacroSignal(BaseSignal):
    """
    Custom signal based on macroeconomic indicators.

    Uses Fed policy indicators to generate alphas:
    - Federal Funds Rate changes
    - Inflation (CPI)
    - Unemployment rate
    """

    def __init__(
        self,
        indicators: List[str] = ["FEDRATE", "CPI", "UNEMPLOYMENT"],
        lookback: int = 90,
        standardize: bool = True
    ):
        super().__init__(
            name="macro_signal",
            standardize=standardize
        )
        self.indicators = indicators
        self.lookback = lookback

    def _calculate_raw_signal(
        self,
        inst_data: pd.DataFrame,
        market_data: Optional[Any],
        as_of: date
    ) -> float:
        """
        Calculate macro signal for a single instrument.

        Logic:
        1. Fetch macro indicators
        2. Calculate changes over lookback period
        3. Combine into composite score
        4. Map to instrument-specific signal
        """
        # Fetch macro data
        fed_rate_change = self._get_fed_rate_change(as_of)
        inflation = self._get_inflation(as_of)
        unemployment = self._get_unemployment(as_of)

        # Composite score (example weights)
        score = (
            0.4 * fed_rate_change +  # Fed hiking/cutting
            0.3 * inflation +        # Inflation pressure
            0.3 * unemployment       # Labor market
        )

        # Map to instrument
        # Example: Short-dated futures more sensitive to Fed
        inst_id = inst_data.get('identifier', '')
        if 'Z4' in inst_id or 'H5' in inst_id:  # Near-term
            signal = score * 2.0  # Higher sensitivity
        else:  # Long-term
            signal = score * 1.0  # Lower sensitivity

        return signal

    def _get_fed_rate_change(self, as_of: date) -> float:
        """Fetch Fed rate change over lookback period."""
        # Implementation: fetch from data source
        # Return: rate change (e.g., +0.25 for 25bp hike)
        pass

    def _get_inflation(self, as_of: date) -> float:
        """Fetch inflation indicator."""
        # Implementation: fetch CPI, calculate YoY change
        pass

    def _get_unemployment(self, as_of: date) -> float:
        """Fetch unemployment rate."""
        # Implementation: fetch from data source
        pass

    def calculate(
        self,
        instruments: List[str],
        market_data: Optional[Any],
        as_of: date
    ) -> Dict[str, float]:
        """
        Calculate signals for multiple instruments.

        This is the main entry point called by the framework.
        """
        signals = {}

        for inst in instruments:
            # Get instrument data
            inst_data = pd.DataFrame({'identifier': [inst]})

            # Calculate signal
            signals[inst] = self._calculate_raw_signal(
                inst_data, market_data, as_of
            )

        # Standardize if requested
        if self.standardize and len(signals) > 1:
            values = list(signals.values())
            mean = np.mean(values)
            std = np.std(values)
            if std > 1e-10:
                signals = {k: (v - mean) / std for k, v in signals.items()}

        return signals
```

**Step 2: Use in YAML**

```yaml
# strategies/with_macro.yaml
signals:
  - name: "carry"
    type: "carry"
    config:
      standardize: true
    weight: 1.0

  - name: "custom_macro"
    type: "custom"
    config:
      module: "strategies.custom.macro_signal"  # Python module path
      class: "MacroSignal"                      # Class name
      params:                                   # Constructor parameters
        indicators: ["FEDRATE", "CPI", "UNEMPLOYMENT"]
        lookback: 90
        standardize: true
    weight: 0.5  # Lower weight (experimental)
```

**Step 3: Test custom signal**

```python
# Test in isolation before using in strategy
from strategies.custom.macro_signal import MacroSignal
from datetime import date

signal = MacroSignal(
    indicators=["FEDRATE", "CPI", "UNEMPLOYMENT"],
    lookback=90
)

# Test calculation
instruments = ["SFRZ4", "SFRH5", "SFRM5"]
signals = signal.calculate(instruments, market_data=None, as_of=date(2024, 11, 1))

print(f"Signals: {signals}")
# Expected: {'SFRZ4': 0.5, 'SFRH5': 0.3, 'SFRM5': -0.8}
```

### Risk Management and Position Sizing

**Key Concepts:**

1. **Volatility Targeting**: Scale positions to maintain constant volatility
2. **Max Position**: Limit concentration in any single instrument
3. **Leverage**: Control total exposure
4. **DV01 Limits**: Limit interest rate risk (fixed income)

**Example: Conservative Risk Management**

```yaml
# strategies/conservative_carry.yaml
optimizer:
  type: "mean_variance"
  risk_aversion: 2.0  # Higher = more conservative

  constraints:
    long_only: true
    max_position: 0.15       # Max 15% in any position
    leverage: 0.8            # Max 80% invested (20% cash)

risk:
  covariance: "ledoit_wolf"
  volatility_target: 0.08    # Target 8% annualized volatility
  lookback: 120              # Longer history = more stable

execution:
  rebalance_frequency: "monthly"  # Less frequent = lower turnover
```

**Example: Aggressive Risk Management**

```yaml
# strategies/aggressive_carry.yaml
optimizer:
  type: "mean_variance"
  risk_aversion: 0.5  # Lower = more aggressive

  constraints:
    long_only: false         # Allow shorting
    max_position: 0.40       # Max 40% long
    max_short_position: -0.30  # Max 30% short
    leverage: 2.0            # Up to 200% gross exposure

risk:
  covariance: "sample"       # Simple covariance (less shrinkage)
  volatility_target: 0.15    # Target 15% volatility
  lookback: 60               # Shorter history = more responsive

execution:
  rebalance_frequency: "weekly"  # More frequent rebalancing
```

**Volatility Targeting Logic:**

```python
# How volatility targeting works:

# 1. Calculate portfolio volatility
portfolio_vol = np.sqrt(weights.T @ cov_matrix @ weights)

# 2. If vol > target, scale down positions
if portfolio_vol > vol_target:
    scaling_factor = vol_target / portfolio_vol
    weights = weights * scaling_factor

# 3. This keeps volatility constant over time
```

---

## Advanced Tutorial

### Event-Driven Strategies with Custom Rebalancing

**Event-driven strategies** trade around specific events (FOMC, auctions, month-end).

**Example: FOMC Butterfly**

```yaml
# strategies/fomc_fly.yaml
strategy:
  name: "FOMC Butterfly"
  type: "event_driven"
  mode: "query"  # Note: query mode, not signal mode

universe:
  asset_class: "swaps"
  instruments: "dynamic"  # Resolved from FOMC calendar

queries:
  - name: "fomc_fly"
    type: "fly"
    config:
      curve: "USD-SOFR-1D"
      tenor_resolution: "fomc_meetings"
      fomc_indices: [1, 2, 3]  # Next 3 FOMC meetings
      bpv: 100000
      tags: ["fomc"]

# Entry: When carry signal triggers
entry:
  type: "signal_with_event"
  config:
    signal:
      name: "2s5s10s_carry"
      type: "carry"
      query:
        type: "fly"
        curve: "USD-SOFR-1D"
        front_tenor: "2Y"
        belly_tenor: "5Y"
        back_tenor: "10Y"
      operator: ">"
      threshold: 0.0
      horizon: "3m"

    event_constraint:
      calendar: "USD-FEDFUNDS"
      event_type: "meeting"
      min_days_to_next: 5  # Only enter if >= 5 days to FOMC

# Exit: Signal flip OR leg expiry
exit:
  type: "multi"
  operator: "any"
  conditions:
    - type: "signal"
      config:
        signal: "2s5s10s_carry"
        operator: "<="
        threshold: 0.0

    - type: "structural_expiry"
      config:
        leg: "front"
        offset_days: -1

execution:
  rebalance_frequency: "event_driven"
  calendar: "US_GOVERNMENT_BOND"

backtest:
  start_date: "2025-01-01"
  end_date: "2025-10-21"
  initial_capital: 1000000.0
```

**How it works:**

1. **Check carry signal daily**: Calculate 2s5s10s carry
2. **If carry > 0 AND >= 5 days to FOMC**:
   - Resolve next 3 FOMC meeting dates
   - Create butterfly: FOMC-1 / FOMC-2 / FOMC-3
   - Enter position (receive belly)
3. **Exit when**:
   - Carry flips to <= 0, OR
   - 1 day before front leg expires, OR
   - Maximum holding period reached

### Regime-Switching Strategies

**Problem**: Different signals work in different market regimes
- **Trending markets**: Momentum works, mean reversion fails
- **Ranging markets**: Mean reversion works, momentum fails
- **Carry markets**: Carry signal dominates

**Solution**: Detect regime and adjust signal weights

**Simple Regime Detection:**

```python
# strategies/custom/regime_detector.py
class RegimeDetector:
    """
    Detect market regime based on price behavior.

    Regimes:
    - trending: High directional movement
    - ranging: Oscillating around mean
    - carry: Persistent backwardation/contango
    """

    def detect_regime(self, price_history: pd.DataFrame) -> str:
        """
        Detect current market regime.

        Returns: "trending", "ranging", or "carry"
        """
        # Calculate metrics
        returns = price_history.pct_change()
        autocorr = returns.autocorr(lag=1)  # Serial correlation
        volatility = returns.std()

        # Decision logic
        if abs(autocorr) > 0.3:
            return "trending"  # High autocorrelation = trend
        elif volatility < 0.005:
            return "ranging"   # Low vol = range-bound
        else:
            return "carry"     # Default to carry

# Use in signal weighting
def get_adaptive_weights(regime: str) -> dict:
    """Get signal weights based on regime."""
    if regime == "trending":
        return {"carry": 0.3, "momentum": 1.0, "mean_rev": 0.0}
    elif regime == "ranging":
        return {"carry": 0.5, "momentum": 0.0, "mean_rev": 1.0}
    else:  # carry regime
        return {"carry": 1.0, "momentum": 0.5, "mean_rev": 0.3}
```

**YAML Configuration:**

```yaml
# strategies/regime_switching.yaml
strategy:
  name: "Regime-Switching Multi-Signal"
  type: "regime_switching"
  mode: "signal"

signals:
  - name: "carry"
    type: "carry"
    config:
      standardize: true
    weight: "adaptive"  # Will be adjusted by regime

  - name: "momentum"
    type: "momentum"
    config:
      lookback_days: 30
      standardize: true
    weight: "adaptive"

  - name: "mean_reversion"
    type: "mean_reversion"
    config:
      lookback_days: 20
      standardize: true
    weight: "adaptive"

# Regime detection config
regime:
  enabled: true
  detector:
    module: "strategies.custom.regime_detector"
    class: "RegimeDetector"
  update_frequency: "monthly"  # Re-detect regime monthly
```

### Transaction Cost Modeling

**Why model transaction costs?**
- **Reality check**: Backtests without costs are optimistic
- **Strategy design**: High-turnover strategies may not be profitable after costs
- **Rebalancing frequency**: Trade off signal freshness vs. costs

**Cost Components:**

1. **Proportional**: Fixed percentage of trade size (e.g., 1 bp)
2. **Fixed**: Per-trade fee (e.g., $5)
3. **Market Impact**: Larger trades move prices (quadratic)
4. **Slippage**: Difference between quoted and execution price

**YAML Configuration:**

```yaml
# strategies/with_costs.yaml
execution:
  rebalance_frequency: "weekly"

  transaction_costs:
    enabled: true

    # Proportional cost (bid-ask spread)
    proportional: 0.0001  # 1 bp = 0.01%

    # Fixed cost (commission)
    fixed: 5.0  # $5 per trade

    # Market impact (price moves against you)
    market_impact:
      enabled: true
      model: "quadratic"
      coefficient: 0.001  # Impact = coef × (trade_size / ADV)^2

    # Slippage (execution uncertainty)
    slippage:
      enabled: true
      model: "percent"
      value: 0.0001  # 1 bp average slippage

  # Rebalancing threshold
  rebalancing:
    method: "threshold"  # Only rebalance if needed
    threshold: 0.05      # Rebalance if weight drifts > 5%
    min_frequency: "weekly"  # But check at least weekly
```

**Impact Analysis:**

```python
# Compare with/without costs
from Strategies.Factory.StrategyFactory import StrategyFactory
from Backtest.Backtest import Backtest

# Strategy without costs
config_no_costs = {
    'execution': {'transaction_costs': {'enabled': False}}
}
strategy_no_costs = StrategyFactory().create_from_dict(config_no_costs)
results_no_costs = Backtest(strategy=strategy_no_costs).run()

# Strategy with costs
config_with_costs = {
    'execution': {
        'transaction_costs': {
            'enabled': True,
            'proportional': 0.0001,
            'fixed': 5.0
        }
    }
}
strategy_with_costs = StrategyFactory().create_from_dict(config_with_costs)
results_with_costs = Backtest(strategy=strategy_with_costs).run()

# Compare
print(f"Sharpe (no costs): {results_no_costs.sharpe_ratio:.2f}")
print(f"Sharpe (with costs): {results_with_costs.sharpe_ratio:.2f}")
print(f"Cost drag: {(results_no_costs.sharpe_ratio - results_with_costs.sharpe_ratio):.2f}")
print(f"Turnover: {results_with_costs.turnover:.2%}")
```

**Optimizing for Costs:**

```yaml
# Strategy optimized for low turnover
optimizer:
  constraints:
    max_turnover: 0.20  # Max 20% turnover per rebalance

execution:
  rebalancing:
    method: "threshold"
    threshold: 0.10  # Only rebalance if drift > 10% (higher threshold)

risk:
  lookback: 120  # Longer history = more stable estimates = less rebalancing
```

---

## Reference

### Complete YAML Schema

See `Strategies/Config/schema.json` for full JSON Schema specification.

**Top-Level Keys:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `strategy` | object | Yes | Strategy metadata |
| `universe` | object | Yes | Instrument universe |
| `signals` | list | Conditional | Signals (for signal mode) |
| `queries` | list | Conditional | Queries (for query mode) |
| `alpha` | object | Conditional | Alpha generation (for signal mode) |
| `risk` | object | Yes | Risk model configuration |
| `optimizer` | object | Conditional | Optimizer (for signal mode) |
| `entry` | object | Conditional | Entry rules (for query mode) |
| `exit` | object | Conditional | Exit rules (for query mode) |
| `execution` | object | Yes | Execution parameters |
| `backtest` | object | Yes | Backtest configuration |

### Available Signals

| Signal | Type | Description | Parameters |
|--------|------|-------------|------------|
| **Carry** | `carry` | Calendar spread (front - back) | `method`, `annualize`, `standardize` |
| **Momentum** | `momentum` | Price momentum (trend following) | `lookback_days`, `method`, `standardize` |
| **Mean Reversion** | `mean_reversion` | Deviation from mean | `lookback_days`, `method`, `threshold`, `standardize` |
| **Custom** | `custom` | User-defined signal | `module`, `class`, `params` |

**Carry Signal:**
```yaml
signals:
  - type: "carry"
    config:
      method: "calendar_spread"  # "calendar_spread" | "roll_yield"
      annualize: true            # Convert to annual rate
      standardize: true          # Z-score normalization
```

**Momentum Signal:**
```yaml
signals:
  - type: "momentum"
    config:
      lookback_days: 30          # Lookback window
      method: "returns"          # "returns" | "regression"
      standardize: true
```

**Mean Reversion Signal:**
```yaml
signals:
  - type: "mean_reversion"
    config:
      lookback_days: 20          # Window for mean calculation
      method: "z_score"          # "z_score" | "bollinger"
      threshold: 2.0             # Z-score threshold for signal
      standardize: true
```

### Risk Models

| Model | Name | Description | Best For |
|-------|------|-------------|----------|
| **Ledoit-Wolf** | `ledoit_wolf` | Shrinkage estimator | Small samples, robust |
| **Sample Covariance** | `sample` | Historical covariance | Large samples, responsive |
| **Constant Correlation** | `constant_correlation` | Assume constant corr | Highly correlated assets |

**Ledoit-Wolf (Recommended):**
```yaml
risk:
  covariance: "ledoit_wolf"
  lookback: 60               # Days of history
  volatility_target: 0.10    # Optional vol targeting
```

**Sample Covariance:**
```yaml
risk:
  covariance: "sample"
  lookback: 120              # Need more data for stability
```

### Optimizer Options

| Optimizer | Description | Use Case |
|-----------|-------------|----------|
| **Mean-Variance** | Markowitz (1952) optimization | General purpose, alpha-driven |
| **Risk Parity** | Equal risk contribution | Diversification-focused |
| **Min Variance** | Minimize variance (ignore alphas) | Pure risk minimization |

**Mean-Variance Optimizer:**
```yaml
optimizer:
  type: "mean_variance"
  risk_aversion: 1.0  # Lambda: higher = more risk averse

  constraints:
    long_only: true              # No shorting
    max_position: 0.30           # Max 30% per position
    max_short_position: -0.20    # Max 20% short (if long_only=false)
    leverage: 1.5                # Max gross exposure
    max_turnover: 0.30           # Max turnover per rebalance
    dv01_limit:                  # Interest rate risk limit
      enabled: true
      max_dv01: 500000
    cardinality:                 # Limit number of positions
      enabled: true
      max_positions: 5
```

---

## Appendices

### FAQ

**Q: When should I use query mode vs signal mode?**

A:
- **Query mode**: Event-driven strategies (FOMC, month-end), structural trades (flies, curves), specific entry/exit dates
- **Signal mode**: Systematic alpha strategies, multi-signal combination, continuous optimization

**Q: How do I choose IC?**

A:
- Start conservative: IC = 0.03-0.05
- Estimate from historical data:
  ```python
  ic = np.corrcoef(forecasts, realized_returns)[0, 1]
  ```
- Targets: IC > 0.05 (good), IC > 0.10 (very good), IC > 0.15 (exceptional)

**Q: What's the difference between standardize=true and standardize=false?**

A:
- `standardize=true`: Signals are z-scored (mean=0, std=1) → comparable across signals
- `standardize=false`: Raw signal values → only use if signals already comparable

**Q: How often should I rebalance?**

A:
- **Daily**: High signal decay, low transaction costs
- **Weekly**: Balanced (most common)
- **Monthly**: Low turnover, high transaction costs
- **Event-driven**: Only on specific triggers

**Q: My strategy has high IC but low Sharpe. Why?**

A:
- High IC = good forecasts
- Low Sharpe = high volatility or low returns
- Possible causes:
  - Insufficient risk management (increase risk_aversion)
  - High transaction costs (reduce rebalancing frequency)
  - Low volatility target (increase vol_target)

**Q: Can I mix query and signal modes?**

A: Not in the same strategy YAML. But you can run multiple strategies and combine results.

### Glossary

- **IC (Information Coefficient)**: Correlation between forecast and realized returns. Measures forecast skill.
- **Sharpe Ratio**: (Mean return - Risk-free rate) / Std dev of returns. Measures risk-adjusted performance.
- **Z-Score**: (Value - Mean) / Std dev. Standardized measure.
- **Carry**: Return from holding asset assuming prices don't change.
- **Backwardation**: Front contract trades above back contract (positive carry).
- **Contango**: Front contract trades below back contract (negative carry).
- **DV01**: Dollar value of 1 basis point change in yield.
- **Turnover**: Percentage of portfolio traded per period.
- **Leverage**: Gross exposure / Capital. 1.0 = no leverage, 2.0 = 2x leverage.

### Further Reading

**Academic Papers:**
- Grinold & Kahn (2000): "Active Portfolio Management"
- Ledoit & Wolf (2004): "Honey, I Shrunk the Sample Covariance Matrix"
- Markowitz (1952): "Portfolio Selection"
- Fama & French (1993): "Common Risk Factors"

**ARBS Documentation:**
- `docs/GRINOLD_KAHN_FRAMEWORK.md` - Framework overview
- `docs/BACKTESTING_FUTURES_SWAPS_PLAN.md` - Backtesting guide
- `docs/STRATEGY_MODULARIZATION_DESIGN.md` - Design document

**Examples:**
- `strategies/examples/` - YAML example files
- `examples/` - End-to-end backtest examples
- `tests/integration/test_multi_signal_strategy.py` - Integration tests

---

**END OF USER GUIDE**
