# Adding Custom Components to the Strategy Factory

This guide shows how to extend the strategy factory system with custom signals, alpha methods, and covariance estimators without modifying framework code.

## Table of Contents
- [Quick Start](#quick-start)
- [Custom Signals](#custom-signals)
- [Custom Alpha Methods](#custom-alpha-methods)
- [Custom Covariance Estimators](#custom-covariance-estimators)
- [Complete Example](#complete-example)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

The strategy factory system uses **registry patterns** to allow runtime extension. Register your custom components, then use them in YAML configurations or Python code.

```python
from Strategies.Factory import SignalFactory, AlphaFactory, CovarianceFactory

# Register custom signal
SignalFactory.register_signal('my_signal', MySignalClass)

# Now works in YAML:
# signals:
#   - type: my_signal
#     config: {param1: value1}
```

---

## Custom Signals

### Step 1: Implement BaseSignal Interface

All signals must inherit from `BaseSignal` and implement `calculate()`.

```python
from Signals.Base.BaseSignal import BaseSignal
import pandas as pd
import numpy as np

class BasisSignal(BaseSignal):
    """
    Futures-swap basis signal.

    Identifies mispricing between futures and swap markets.
    """

    def __init__(self, swap_tenor: str = '3M', standardize: bool = True):
        """
        Args:
            swap_tenor: Swap tenor to compare ('3M', '6M', etc.)
            standardize: Whether to z-score the signal
        """
        super().__init__(name='basis_signal')
        self.swap_tenor = swap_tenor
        self.standardize = standardize

    def calculate(self, prices: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
        """
        Calculate basis signal.

        Args:
            prices: DataFrame of asset prices
            dates: DatetimeIndex for signal dates

        Returns:
            DataFrame of signal values (same shape as prices)
        """
        # Your signal logic here
        # Example: Calculate basis spread
        basis = prices.diff(1)  # Simple example

        if self.standardize:
            basis = (basis - basis.mean()) / basis.std()

        return basis.reindex(dates).fillna(0)
```

### Step 2: Register the Signal

```python
from Strategies.Factory import SignalFactory

SignalFactory.register_signal('basis', BasisSignal)
```

### Step 3: Use in YAML or Python

**YAML Configuration:**
```yaml
signals:
  - type: basis
    config:
      swap_tenor: '3M'
      standardize: true
    weight: 1.0
```

**Python:**
```python
from Strategies.Registry import quick_strategy

strategy = quick_strategy(
    'multi_signal',
    instruments=['SFRZ4', 'SFRH5'],
    **{'signals': [{'type': 'basis', 'config': {'swap_tenor': '3M'}}]}
)
```

### Signal Requirements

- ✅ Must inherit from `BaseSignal`
- ✅ Must call `super().__init__(name='your_name')`
- ✅ Must implement `calculate(prices, dates)` returning DataFrame
- ✅ Return shape must match `(len(dates), len(prices.columns))`
- ✅ Should handle missing data gracefully (fillna/ffill)

---

## Custom Alpha Methods

### Step 1: Create Alpha Generator Function

Alpha methods are **factory functions** that create `AlphaGenerator` instances.

```python
from Signals.AlphaGenerator import AlphaGenerator

def create_adaptive_ic_alpha(config):
    """
    Create alpha generator with adaptive IC based on recent performance.

    Args:
        config: StrategyConfig instance

    Returns:
        AlphaGenerator instance
    """
    # Access config values
    base_ic = config.alpha.IC

    # Custom logic: start with conservative IC
    conservative_ic = base_ic * 0.5

    return AlphaGenerator(
        IC=conservative_ic,
        dynamic_ic=True,
        ic_method='rolling',
        ic_lookback=90  # Longer lookback for stability
    )
```

### Step 2: Register the Method

```python
from Strategies.Factory import AlphaFactory

AlphaFactory.register_method('adaptive_ic', create_adaptive_ic_alpha)
```

### Step 3: Use in YAML or Python

**YAML:**
```yaml
alpha:
  IC: 0.05  # Base IC
  method: adaptive_ic
```

**Python:**
```python
config_dict = {
    'alpha': {'IC': 0.05, 'method': 'adaptive_ic'},
    # ... other config
}
strategy = StrategyFactory().create_from_dict(config_dict)
```

### Alpha Method Requirements

- ✅ Must be a callable taking `config` parameter
- ✅ Must return `AlphaGenerator` instance
- ✅ Can access all config fields via `config.alpha`, `config.risk`, etc.
- ✅ Should validate parameters and raise `ValueError` if invalid

---

## Custom Covariance Estimators

### Step 1: Implement Covariance Estimator Class

Covariance estimators should have a consistent interface (no strict base class required).

```python
import numpy as np
import pandas as pd

class RobustCovariance:
    """
    Robust covariance estimator using Minimum Covariance Determinant (MCD).

    Reduces impact of outliers on covariance estimation.
    """

    def __init__(self, support_fraction: float = 0.8):
        """
        Args:
            support_fraction: Fraction of observations to use (0.5 to 1.0)
        """
        self.support_fraction = support_fraction

    def estimate(self, returns: pd.DataFrame) -> pd.DataFrame:
        """
        Estimate covariance matrix.

        Args:
            returns: DataFrame of asset returns

        Returns:
            DataFrame covariance matrix
        """
        from sklearn.covariance import MinCovDet

        # Fit robust covariance
        mcd = MinCovDet(support_fraction=self.support_fraction)
        mcd.fit(returns.values)

        # Return as DataFrame
        cov_matrix = pd.DataFrame(
            mcd.covariance_,
            index=returns.columns,
            columns=returns.columns
        )

        return cov_matrix
```

### Step 2: Register the Estimator

```python
from Strategies.Factory import CovarianceFactory

CovarianceFactory.register_covariance('robust', RobustCovariance)
```

### Step 3: Use in YAML or Python

**YAML:**
```yaml
risk:
  covariance: robust
  lookback: 60
```

**Python:**
```python
config_dict = {
    'risk': {'covariance': 'robust'},
    # ... other config
}
strategy = StrategyFactory().create_from_dict(config_dict)
```

### Covariance Estimator Requirements

- ✅ Constructor should accept configuration parameters
- ✅ Should have `estimate(returns)` method returning DataFrame
- ✅ Return matrix must be symmetric positive semi-definite
- ✅ Should handle edge cases (insufficient data, singular matrices)

---

## Complete Example

Here's a full working example combining custom signal, alpha method, and usage.

```python
# custom_strategies.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Signals.Base.BaseSignal import BaseSignal
from Signals.AlphaGenerator import AlphaGenerator
from Strategies.Factory import SignalFactory, AlphaFactory
from Strategies.Registry import quick_strategy
import pandas as pd
import numpy as np


# 1. Define custom signal
class VolatilityBreakoutSignal(BaseSignal):
    """Enters positions when volatility breaks out of recent range."""

    def __init__(self, vol_window: int = 20, breakout_threshold: float = 2.0):
        super().__init__(name='volatility_breakout')
        self.vol_window = vol_window
        self.breakout_threshold = breakout_threshold

    def calculate(self, prices: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
        # Calculate rolling volatility
        returns = prices.pct_change()
        vol = returns.rolling(self.vol_window).std()

        # Z-score of current vol vs historical
        vol_zscore = (vol - vol.rolling(60).mean()) / vol.rolling(60).std()

        # Signal: 1 when vol breaks above threshold, -1 when below
        signal = np.sign(vol_zscore - self.breakout_threshold)

        return signal.reindex(dates).fillna(0)


# 2. Define custom alpha method
def create_high_conviction_alpha(config):
    """
    High conviction alpha: higher IC, lower diversification.

    Use when signals are very reliable.
    """
    # Boost IC by 50%
    boosted_ic = config.alpha.IC * 1.5

    return AlphaGenerator(
        IC=boosted_ic,
        dynamic_ic=False  # Static, no adaptation
    )


# 3. Register custom components
def register_custom_components():
    """Register all custom components with factories."""
    SignalFactory.register_signal('vol_breakout', VolatilityBreakoutSignal)
    AlphaFactory.register_method('high_conviction', create_high_conviction_alpha)


# 4. Use in strategy
def create_custom_strategy():
    """Create strategy using custom components."""
    # Register first
    register_custom_components()

    # Create strategy
    strategy = quick_strategy(
        'multi_signal',
        instruments=['SFRZ4', 'SFRH5', 'SFRM5'],
        **{
            'signals': [
                {'type': 'vol_breakout', 'config': {'vol_window': 20}},
                {'type': 'carry', 'config': {'standardize': True}}
            ],
            'alpha.IC': 0.06,
            'alpha.method': 'high_conviction'
        }
    )

    return strategy


if __name__ == '__main__':
    strategy = create_custom_strategy()
    print(f"Created strategy: {strategy.identifier}")
    print(f"Number of signals: {len(strategy.signals)}")
```

---

## Troubleshooting

### "Invalid signal type" Error

**Problem**: `ValueError: Invalid signal type 'my_signal'`

**Solution**: Register the signal before creating config:
```python
SignalFactory.register_signal('my_signal', MySignalClass)  # Do this FIRST
config = StrategyConfig.from_dict(config_dict)  # Then create config
```

### Signal Not Producing Expected Output

**Checklist**:
- ✅ Does `calculate()` return DataFrame with correct shape?
- ✅ Are dates aligned correctly? Use `.reindex(dates)`
- ✅ Are NaN values handled? Use `.fillna(0)` or `.ffill()`
- ✅ Is standardization applied if needed?

### Covariance Matrix Not Positive Definite

**Solution**: Add regularization:
```python
def estimate(self, returns):
    cov = returns.cov()
    # Add small diagonal term
    cov += np.eye(len(cov)) * 1e-8
    return cov
```

### Alpha Method Not Being Called

**Problem**: Factory not calling your method

**Solution**: Ensure method signature is correct:
```python
# ✅ Correct
def my_alpha_method(config):  # Takes config parameter
    return AlphaGenerator(...)

# ❌ Incorrect
def my_alpha_method():  # Missing config parameter
    return AlphaGenerator(...)
```

### "Unknown IC method" After Registration

**Problem**: Method registered but still raises error

**Cause**: StrategyConfig created before registration

**Solution**: Register BEFORE creating StrategyConfig:
```python
# ✅ Correct order
AlphaFactory.register_method('my_method', my_function)
config = StrategyConfig.from_dict(config_dict)

# ❌ Wrong order
config = StrategyConfig.from_dict(config_dict)  # Validates FIRST
AlphaFactory.register_method('my_method', my_function)  # Too late
```

---

## Best Practices

### Signal Design

1. **Keep it simple**: Start with basic logic, add complexity only if needed
2. **Standardize signals**: Use z-scores for comparable magnitudes across assets
3. **Handle missing data**: Always fillna/ffill to avoid NaN propagation
4. **Test in isolation**: Verify signal produces expected output before integration

### Alpha Methods

1. **Start conservative**: Lower IC initially, increase based on observed performance
2. **Document assumptions**: Explain why your IC/method choices are appropriate
3. **Validate inputs**: Check config values are sensible before creating AlphaGenerator

### Covariance Estimators

1. **Regularize**: Add small diagonal term to prevent singular matrices
2. **Use lookback**: Don't estimate on too few observations
3. **Check properties**: Verify symmetry and positive definiteness

### Testing

Always write tests for custom components:

```python
def test_my_custom_signal():
    signal = MyCustomSignal(param=value)

    # Test output shape
    prices = pd.DataFrame(...)  # Mock prices
    dates = pd.date_range(...)
    result = signal.calculate(prices, dates)

    assert result.shape == (len(dates), len(prices.columns))
    assert not result.isna().any().any()  # No NaN
```

---

## Next Steps

- Review existing signals in `Signals/Futures/` for patterns
- Check `examples/yaml_strategy_example.py` for usage examples
- Read `docs/MODULARITY_REVIEW_AND_STRATEGY_TYPES.md` for strategy ideas
- See `tests/unit/strategies/test_dynamic_validation.py` for extension tests

---

**Questions?** Check the main README or raise an issue.
