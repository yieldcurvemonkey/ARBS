# Extending Risk Models in the Factory System

This guide explains how to register new covariance estimators (risk models) in the factory system, enabling you to use custom risk estimation methods in your strategies without modifying framework code.

## Table of Contents
- [Overview](#overview)
- [Quick Start](#quick-start)
- [Step-by-Step: Complete Extension Process](#step-by-step-complete-extension-process)
- [Understanding Validation](#understanding-validation)
- [Adding Custom YAML Parameters](#adding-custom-yaml-parameters)
- [Common Errors and Debugging](#common-errors-and-debugging)
- [Complete Working Example](#complete-working-example)
- [Best Practices](#best-practices)

---

## Overview

The risk model factory system uses a **registry pattern** that allows you to:
1. Implement custom covariance estimators
2. Register them with `CovarianceFactory`
3. Use them immediately in YAML configurations or Python code
4. Extend functionality without modifying framework code

**Key Components:**
- `CovarianceFactory`: Factory class with registry for covariance estimators
- `StrategyConfig`: YAML parser that validates covariance method names
- `RiskConfig`: Dataclass holding risk configuration (covariance method, lookback, etc.)

---

## Quick Start

**Three steps to use a custom risk model:**

```python
from Strategies.Factory import CovarianceFactory

# 1. Create your covariance estimator class
class MyRiskModel:
    def __init__(self):
        pass

    def fit(self, returns):
        # Your logic here
        return covariance_matrix

# 2. Register it
CovarianceFactory.register_covariance('my_model', MyRiskModel)

# 3. Use in YAML
# risk:
#   covariance: my_model
#   lookback: 60
```

That's it! The factory system handles instantiation and validation automatically.

---

## Step-by-Step: Complete Extension Process

### Step 1: Understand the Base Interface

All covariance estimators should inherit from `BaseCovarianceEstimator` and implement the `fit()` method:

```python
from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator
import pandas as pd
import numpy as np

class BaseCovarianceEstimator(ABC):
    """
    Base class defining the interface for all covariance estimators.
    """

    def __init__(self, handle_missing: str = 'drop'):
        """
        Args:
            handle_missing: How to handle missing data ('drop' or 'pairwise')
        """
        self.handle_missing = handle_missing
        self.cov_matrix_ = None      # Fitted covariance matrix
        self.asset_names_ = None      # Asset names from fitting

    @abstractmethod
    def fit(self, returns: pd.DataFrame) -> np.ndarray:
        """
        Estimate covariance matrix from returns.

        Args:
            returns: DataFrame of returns (T×N)
                - Rows: time periods
                - Columns: assets
                - Values: returns (decimal, e.g., 0.01 for 1%)

        Returns:
            Covariance matrix (N×N numpy array)
        """
        pass

    def get_covariance(self) -> np.ndarray:
        """Get fitted covariance matrix."""
        if self.cov_matrix_ is None:
            raise ValueError("Must call fit() before get_covariance()")
        return self.cov_matrix_
```

**Key Requirements:**
- ✅ Must implement `fit(returns: pd.DataFrame) -> np.ndarray`
- ✅ Must store result in `self.cov_matrix_` attribute
- ✅ Must store asset names in `self.asset_names_` attribute
- ✅ Return matrix must be N×N numpy array (symmetric, positive semi-definite)

### Step 2: Implement Your Risk Model

Here's a complete example implementing a **diagonal covariance estimator** (assumes zero correlation):

```python
from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator
import pandas as pd
import numpy as np

class DiagonalCovariance(BaseCovarianceEstimator):
    """
    Diagonal covariance estimator.

    Assumes zero correlation between assets. Only estimates variances.
    Useful for testing or when you believe assets are truly uncorrelated.

    Covariance matrix:
        Σ_ij = {
            σ_i²    if i = j (variance)
            0       if i ≠ j (no correlation)
        }
    """

    def __init__(self, handle_missing: str = 'drop', min_periods: int = 20):
        """
        Initialize diagonal covariance estimator.

        Args:
            handle_missing: How to handle missing data
            min_periods: Minimum observations required per asset
        """
        super().__init__(handle_missing=handle_missing)
        self.min_periods = min_periods

    def fit(self, returns: pd.DataFrame) -> np.ndarray:
        """
        Estimate diagonal covariance matrix.

        Args:
            returns: DataFrame of returns (T×N)

        Returns:
            Diagonal covariance matrix (N×N)
        """
        # Handle missing data using base class method
        returns_clean = self._handle_missing_data(returns)

        # Store asset names
        self.asset_names_ = list(returns_clean.columns)

        # Check minimum periods
        T, N = returns_clean.shape
        if T < self.min_periods:
            raise ValueError(
                f"Insufficient data: {T} periods < {self.min_periods} minimum"
            )

        # Calculate variances (diagonal elements)
        variances = returns_clean.var(ddof=1).values

        # Create diagonal matrix
        self.cov_matrix_ = np.diag(variances)

        return self.cov_matrix_

    def __repr__(self) -> str:
        return f"DiagonalCovariance(min_periods={self.min_periods})"
```

**Implementation Checklist:**
- ✅ Inherits from `BaseCovarianceEstimator`
- ✅ Calls `super().__init__()` in constructor
- ✅ Implements `fit(returns)` method
- ✅ Handles missing data via `_handle_missing_data()`
- ✅ Stores `asset_names_` and `cov_matrix_` attributes
- ✅ Returns N×N numpy array
- ✅ Validates input data (e.g., minimum periods check)
- ✅ Implements `__repr__()` for debugging

### Step 3: Register with CovarianceFactory

Register your estimator so the factory knows about it:

```python
from Strategies.Factory.CovarianceFactory import CovarianceFactory

# Register with a descriptive name
CovarianceFactory.register_covariance('diagonal', DiagonalCovariance)

# Verify registration
available = CovarianceFactory.list_available_methods()
print(f"Available methods: {available}")
# Output: ['ledoit_wolf', 'sample', 'constant_correlation', 'diagonal']
```

**Registration Details:**
- `name`: String identifier used in YAML (lowercase, underscores allowed)
- `estimator_class`: Your covariance estimator class (not an instance!)
- Registration is **persistent** within the Python session
- You can register multiple estimators with different names

### Step 4: Use in YAML Configuration

Once registered, use your risk model in any YAML strategy:

```yaml
# my_strategy.yaml

strategy:
  name: "Low Correlation Strategy"
  type: "multi_signal"
  description: "Assumes assets are uncorrelated"

universe:
  asset_class: "futures"
  instruments:
    - "SFRZ4"
    - "SFRH5"
    - "SFRM5"

signals:
  - type: carry
    weight: 1.0

alpha:
  IC: 0.05
  method: static

risk:
  covariance: diagonal      # ← Your custom method!
  lookback: 60              # Passed to returns calculation
  volatility_target: 0.10

optimizer:
  type: mean_variance
  risk_aversion: 1.0

backtest:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
```

### Step 5: Load and Run Strategy

```python
from Strategies.Config.StrategyConfig import StrategyConfig
from Strategies.Factory.CovarianceFactory import CovarianceFactory

# Register BEFORE loading YAML (validation happens during parsing)
CovarianceFactory.register_covariance('diagonal', DiagonalCovariance)

# Load strategy configuration
config = StrategyConfig.from_yaml('my_strategy.yaml')

# Factory automatically creates your covariance estimator
cov_estimator = CovarianceFactory.create_covariance_estimator(config)
print(cov_estimator)
# Output: DiagonalCovariance(min_periods=20)

# Use in backtest
from Strategies.Factory.StrategyFactory import StrategyFactory
strategy = StrategyFactory().create_from_config(config)
```

---

## Understanding Validation

The factory system has **two validation stages**:

### Stage 1: YAML Parse-Time Validation

When you call `StrategyConfig.from_yaml()`, the `RiskConfig.__post_init__()` method validates the covariance method name:

```python
@dataclass
class RiskConfig:
    covariance: str = 'ledoit_wolf'
    volatility_target: Optional[float] = None
    lookback: int = 60

    def __post_init__(self):
        """Validate risk configuration."""
        from Strategies.Factory.CovarianceFactory import CovarianceFactory

        valid_covariance = CovarianceFactory.list_available_methods()
        if self.covariance not in valid_covariance:
            raise ValueError(
                f"Invalid covariance method '{self.covariance}'. "
                f"Available methods: {valid_covariance}. "
                f"Use CovarianceFactory.register_covariance() to add new methods."
            )
```

**Key Point:** You MUST register your covariance method **BEFORE** parsing the YAML, otherwise validation will fail.

```python
# ✅ CORRECT ORDER
CovarianceFactory.register_covariance('my_model', MyModel)
config = StrategyConfig.from_yaml('strategy.yaml')

# ❌ WRONG ORDER - Will raise ValueError
config = StrategyConfig.from_yaml('strategy.yaml')  # Validates first!
CovarianceFactory.register_covariance('my_model', MyModel)  # Too late
```

### Stage 2: Factory Creation-Time Validation

When `CovarianceFactory.create_covariance_estimator(config)` is called, the factory checks if the method exists in the registry:

```python
@classmethod
def create_covariance_estimator(cls, config):
    """Create covariance estimator from configuration."""
    cls._initialize_defaults()

    method = config.risk.covariance
    if method not in cls._COVARIANCE_REGISTRY:
        available = ', '.join(cls.list_available_methods())
        raise ValueError(
            f"Unknown covariance method: '{method}'. "
            f"Available methods: {available}"
        )

    estimator_class = cls._COVARIANCE_REGISTRY[method]
    return estimator_class()  # Instantiate with no arguments
```

**Current Limitation:** The factory instantiates estimators with **no constructor arguments**. All configuration must happen via default parameters or post-instantiation.

---

## Adding Custom YAML Parameters

### Current Limitation: No Parameter Passing

The current factory implementation instantiates covariance estimators with **zero arguments**:

```python
estimator_class = cls._COVARIANCE_REGISTRY[method]
return estimator_class()  # ← No arguments passed!
```

This means your estimator constructor **must work with no arguments**, using defaults:

```python
# ✅ Works with current factory
class MyEstimator(BaseCovarianceEstimator):
    def __init__(self, param1: float = 0.5, param2: str = 'default'):
        super().__init__()
        self.param1 = param1
        self.param2 = param2

# ❌ Won't work - requires arguments
class MyEstimator(BaseCovarianceEstimator):
    def __init__(self, required_param: float):  # No default!
        super().__init__()
        self.required_param = required_param
```

### Workaround: Use RiskConfig Fields

The `RiskConfig` dataclass has these fields available:
- `covariance: str` - Method name
- `volatility_target: Optional[float]` - Volatility target (if specified)
- `lookback: int` - Lookback window (default: 60)

You can access these in your `fit()` method by accepting a config parameter (requires modifying the factory).

### Future Enhancement: Parameter Passing

To support custom parameters, you would need to:

1. **Extend RiskConfig** to accept arbitrary parameters:
```python
@dataclass
class RiskConfig:
    covariance: str = 'ledoit_wolf'
    volatility_target: Optional[float] = None
    lookback: int = 60
    covariance_params: Dict[str, Any] = field(default_factory=dict)  # ← New field
```

2. **Modify Factory** to pass parameters:
```python
@classmethod
def create_covariance_estimator(cls, config):
    estimator_class = cls._COVARIANCE_REGISTRY[method]
    params = config.risk.covariance_params  # Extract parameters
    return estimator_class(**params)  # Pass to constructor
```

3. **Use in YAML**:
```yaml
risk:
  covariance: my_model
  lookback: 60
  covariance_params:
    shrinkage_intensity: 0.5
    target_type: 'identity'
```

**Note:** This enhancement is not currently implemented. For now, use default parameters.

---

## Common Errors and Debugging

### Error 1: "Invalid covariance method" During YAML Parsing

**Full Error:**
```
ValueError: Invalid covariance method 'my_model'.
Available methods: ['ledoit_wolf', 'sample', 'constant_correlation'].
Use CovarianceFactory.register_covariance() to add new methods.
```

**Cause:** You registered your method AFTER parsing the YAML.

**Solution:** Register BEFORE parsing:
```python
# Register first
CovarianceFactory.register_covariance('my_model', MyModel)

# Then parse YAML
config = StrategyConfig.from_yaml('strategy.yaml')
```

### Error 2: "Unknown covariance method" During Factory Creation

**Full Error:**
```
ValueError: Unknown covariance method: 'my_model'.
Available methods: ledoit_wolf, sample, constant_correlation
```

**Cause:** Method not in registry when factory tries to create it.

**Solution:** This usually means you have a typo in the YAML or forgot to register:
```python
# Check available methods
print(CovarianceFactory.list_available_methods())

# Verify your method is registered
CovarianceFactory.register_covariance('my_model', MyModel)
print(CovarianceFactory.list_available_methods())
```

### Error 3: "Must call fit() before get_covariance()"

**Cause:** Trying to get covariance matrix before calling `fit()`.

**Solution:** Always fit first:
```python
estimator = DiagonalCovariance()
# DON'T: cov = estimator.get_covariance()  # Error!
estimator.fit(returns)  # Fit first
cov = estimator.get_covariance()  # Now works
```

### Error 4: Singular Matrix or Non-Positive Definite

**Cause:** Covariance matrix is ill-conditioned (not invertible).

**Solution:** Add regularization:
```python
def fit(self, returns):
    # Calculate covariance
    cov = returns.cov().values

    # Add small diagonal term for numerical stability
    epsilon = 1e-8
    cov += np.eye(len(cov)) * epsilon

    self.cov_matrix_ = cov
    return self.cov_matrix_
```

### Error 5: Shape Mismatch

**Cause:** Return matrix has wrong dimensions.

**Solution:** Ensure matrix is N×N where N = number of assets:
```python
def fit(self, returns):
    T, N = returns.shape  # T periods, N assets

    # Calculate covariance
    cov = returns.cov().values

    # Verify shape
    assert cov.shape == (N, N), f"Expected ({N}, {N}), got {cov.shape}"

    self.cov_matrix_ = cov
    return self.cov_matrix_
```

### Debugging Checklist

When your custom risk model isn't working:

1. ✅ **Registration:** Did you register BEFORE parsing YAML?
   ```python
   CovarianceFactory.register_covariance('my_model', MyModel)
   ```

2. ✅ **Name Match:** Does YAML name exactly match registration name?
   ```yaml
   risk:
     covariance: my_model  # Must match registration
   ```

3. ✅ **Default Constructor:** Can your class be instantiated with no arguments?
   ```python
   estimator = MyModel()  # Should work
   ```

4. ✅ **Base Class:** Do you inherit from `BaseCovarianceEstimator`?
   ```python
   class MyModel(BaseCovarianceEstimator):
   ```

5. ✅ **fit() Implementation:** Does `fit()` return N×N numpy array?
   ```python
   def fit(self, returns):
       # ... logic ...
       return self.cov_matrix_  # Must be numpy array
   ```

6. ✅ **Attributes Set:** Do you set `cov_matrix_` and `asset_names_`?
   ```python
   self.cov_matrix_ = cov
   self.asset_names_ = list(returns.columns)
   ```

---

## Complete Working Example

Here's a full end-to-end example implementing and using a **shrinkage covariance estimator with custom target**:

```python
"""
custom_risk_model.py - Complete example of custom risk model extension
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator
from Strategies.Factory.CovarianceFactory import CovarianceFactory
from Strategies.Config.StrategyConfig import StrategyConfig


# ==================== 1. IMPLEMENT RISK MODEL ====================

class IdentityCovariance(BaseCovarianceEstimator):
    """
    Identity covariance estimator.

    Assumes all assets have unit variance and zero correlation.
    Useful as a naive baseline or for testing.

    Covariance matrix: Σ = I (identity matrix)
    """

    def __init__(self, handle_missing: str = 'drop'):
        """Initialize identity covariance estimator."""
        super().__init__(handle_missing=handle_missing)

    def fit(self, returns: pd.DataFrame) -> np.ndarray:
        """
        Estimate identity covariance matrix.

        Args:
            returns: DataFrame of returns (T×N)

        Returns:
            Identity matrix (N×N)
        """
        # Handle missing data
        returns_clean = self._handle_missing_data(returns)

        # Store asset names
        self.asset_names_ = list(returns_clean.columns)

        # Get number of assets
        N = returns_clean.shape[1]

        # Create identity matrix
        self.cov_matrix_ = np.eye(N)

        return self.cov_matrix_

    def __repr__(self) -> str:
        return "IdentityCovariance()"


# ==================== 2. REGISTER WITH FACTORY ====================

def register_custom_risk_models():
    """Register all custom risk models."""
    CovarianceFactory.register_covariance('identity', IdentityCovariance)

    print("Registered custom risk models:")
    for method in CovarianceFactory.list_available_methods():
        print(f"  - {method}")


# ==================== 3. CREATE YAML CONFIGURATION ====================

YAML_CONFIG = """
strategy:
  name: "Identity Risk Strategy"
  type: "carry"
  description: "Uses identity covariance (no correlation, unit variance)"

universe:
  asset_class: "futures"
  instruments:
    - "SFRZ4"
    - "SFRH5"
    - "SFRM5"

signals:
  - type: carry
    config:
      standardize: true
    weight: 1.0

alpha:
  IC: 0.05
  method: static

risk:
  covariance: identity    # ← Custom risk model!
  lookback: 60

optimizer:
  type: mean_variance
  risk_aversion: 1.0
  constraints:
    long_only: true
    max_position: 0.40

execution:
  rebalance_frequency: weekly

backtest:
  start_date: "2024-01-01"
  end_date: "2024-12-31"
  initial_capital: 1000000.0
"""


# ==================== 4. USE IN STRATEGY ====================

def test_custom_risk_model():
    """Test custom risk model end-to-end."""

    # Step 1: Register custom risk model
    print("Step 1: Registering custom risk models...")
    register_custom_risk_models()
    print()

    # Step 2: Load configuration from YAML
    print("Step 2: Loading YAML configuration...")
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(YAML_CONFIG)
        yaml_path = f.name

    config = StrategyConfig.from_yaml(yaml_path)
    print(f"  Strategy: {config.strategy.name}")
    print(f"  Risk model: {config.risk.covariance}")
    print()

    # Step 3: Create covariance estimator via factory
    print("Step 3: Creating covariance estimator...")
    cov_estimator = CovarianceFactory.create_covariance_estimator(config)
    print(f"  Created: {cov_estimator}")
    print()

    # Step 4: Test with mock data
    print("Step 4: Testing with mock returns data...")
    returns = pd.DataFrame(
        np.random.randn(100, 3) * 0.01,
        columns=['SFRZ4', 'SFRH5', 'SFRM5']
    )

    cov_matrix = cov_estimator.fit(returns)
    print(f"  Covariance matrix shape: {cov_matrix.shape}")
    print(f"  Is identity? {np.allclose(cov_matrix, np.eye(3))}")
    print()

    # Step 5: Verify properties
    print("Step 5: Verifying covariance properties...")
    print(f"  Symmetric? {np.allclose(cov_matrix, cov_matrix.T)}")
    eigenvalues = np.linalg.eigvals(cov_matrix)
    print(f"  Positive definite? {np.all(eigenvalues > 0)}")
    print(f"  Condition number: {np.linalg.cond(cov_matrix):.2f}")
    print()

    print("✅ Custom risk model test passed!")


if __name__ == '__main__':
    test_custom_risk_model()
```

**Output:**
```
Step 1: Registering custom risk models...
Registered custom risk models:
  - ledoit_wolf
  - sample
  - constant_correlation
  - identity

Step 2: Loading YAML configuration...
  Strategy: Identity Risk Strategy
  Risk model: identity

Step 3: Creating covariance estimator...
  Created: IdentityCovariance()

Step 4: Testing with mock returns data...
  Covariance matrix shape: (3, 3)
  Is identity? True

Step 5: Verifying covariance properties...
  Symmetric? True
  Positive definite? True
  Condition number: 1.00

✅ Custom risk model test passed!
```

---

## Best Practices

### Design Principles

1. **Start Simple:** Begin with basic covariance estimation, add complexity only if needed
2. **Inherit from Base:** Always inherit from `BaseCovarianceEstimator` for consistency
3. **Handle Edge Cases:** Check for insufficient data, singular matrices, etc.
4. **Regularize:** Add small diagonal term to prevent numerical instability
5. **Validate Output:** Ensure matrix is symmetric and positive semi-definite

### Constructor Guidelines

```python
# ✅ Good: All parameters have defaults
def __init__(self, param1: float = 1.0, param2: str = 'default'):
    super().__init__()
    self.param1 = param1
    self.param2 = param2

# ❌ Bad: Required parameters (won't work with factory)
def __init__(self, required_param: float):
    super().__init__()
    self.required_param = required_param
```

### fit() Implementation Pattern

```python
def fit(self, returns: pd.DataFrame) -> np.ndarray:
    """Standard pattern for fit() implementation."""

    # 1. Handle missing data
    returns_clean = self._handle_missing_data(returns)

    # 2. Store asset names (required)
    self.asset_names_ = list(returns_clean.columns)

    # 3. Validate data
    T, N = returns_clean.shape
    if T < self.min_periods:
        raise ValueError(f"Insufficient data: {T} < {self.min_periods}")

    # 4. Calculate covariance
    cov = returns_clean.cov().values

    # 5. Regularize if needed
    epsilon = 1e-8
    cov += np.eye(N) * epsilon

    # 6. Store and return (required)
    self.cov_matrix_ = cov
    return self.cov_matrix_
```

### Testing Your Risk Model

Always write tests before integration:

```python
def test_my_risk_model():
    """Test custom risk model in isolation."""

    # Create mock returns
    returns = pd.DataFrame(
        np.random.randn(100, 5) * 0.01,
        columns=[f'asset_{i}' for i in range(5)]
    )

    # Create and fit estimator
    estimator = MyRiskModel()
    cov = estimator.fit(returns)

    # Verify output
    assert cov.shape == (5, 5), "Wrong shape"
    assert np.allclose(cov, cov.T), "Not symmetric"

    eigenvalues = np.linalg.eigvals(cov)
    assert np.all(eigenvalues > 0), "Not positive definite"

    assert np.linalg.cond(cov) < 1000, "Ill-conditioned"

    print("✅ Risk model tests passed")
```

### Registration Best Practices

```python
# ✅ Good: Register at module import time
from Strategies.Factory import CovarianceFactory
CovarianceFactory.register_covariance('my_model', MyModel)

# ✅ Good: Dedicated registration function
def register_all_custom_components():
    CovarianceFactory.register_covariance('model1', Model1)
    CovarianceFactory.register_covariance('model2', Model2)

# ❌ Bad: Register inside function that's called multiple times
def create_strategy():
    CovarianceFactory.register_covariance('my_model', MyModel)  # Called repeatedly
    config = StrategyConfig.from_yaml('strategy.yaml')
```

### Documentation

Include clear docstrings:

```python
class MyRiskModel(BaseCovarianceEstimator):
    """
    One-line description of risk model.

    Detailed explanation of the methodology, assumptions, and use cases.

    Mathematical Formula:
        Σ = ... (if applicable)

    Advantages:
    - Advantage 1
    - Advantage 2

    Limitations:
    - Limitation 1
    - Limitation 2

    References:
    - Paper citation if applicable
    """
```

---

## Next Steps

**Ready to implement your custom risk model?**

1. ✅ Review existing implementations:
   - `Risk/Covariance/LedoitWolfShrinkage.py` - Industry standard shrinkage
   - `Risk/Covariance/SampleCovariance.py` - Simple baseline

2. ✅ Check tests for patterns:
   - `tests/unit/strategies/test_covariance_factory.py` - Factory tests
   - `tests/unit/risk/test_covariance_estimators.py` - Estimator tests

3. ✅ Read related documentation:
   - `docs/ADDING_CUSTOM_COMPONENTS.md` - General extension guide
   - `docs/GRINOLD_KAHN_FRAMEWORK.md` - Risk modeling theory

4. ✅ Test thoroughly:
   - Write unit tests before integration
   - Verify covariance properties (symmetric, positive definite)
   - Test with real market data

5. ✅ Consider contributing:
   - If your risk model is useful, consider adding it to the framework
   - Follow the contribution guidelines in the main README

---

**Questions or issues?** Check the troubleshooting section or open an issue on GitHub.

Happy risk modeling! 📊
