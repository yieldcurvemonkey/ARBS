# Abstraction Consistency Verification

**Status**: ⚠️ **1 VIOLATION FOUND**
**Date**: 2025-11-13

## Purpose

Verify that all parallel agent implementations follow proper abstraction hierarchy and extend the correct base classes.

## Base Class Hierarchy

### 1. BaseSignal (Signals/Base/BaseSignal.py)

**Contract**:
- Abstract method: `_calculate_raw_signal(inst_data, market_data, as_of) → float`
- Concrete methods: `generate()`, `generate_batch()`, `_standardize()`, `calculate_ic()`
- Constructor: `__init__(name, standardize=True, track_history=True)`
- Return type: `float` (raw signal) or `np.ndarray` (z-scored signals for batch)

**Purpose**: Provides standardized signal generation with z-score normalization and IC tracking

---

### 2. BaseQuery (Query/Base/BaseQuery.py)

**Contract**:
- Dataclass with `@dataclass(frozen=True)`
- Abstract methods: `return_query()`, `col_name()`, `eval_expression()`
- Concrete methods: `build_mdp_request()`, `resolve_package()`, `build_value_map()`
- Fields: `product`, `structure_id`, `structure_kwargs`, `value_id`, etc.

**Purpose**: Product-agnostic query interface for backtester

---

### 3. MeanVarianceOptimizer (Optimizer/MeanVarianceOptimizer.py)

**Contract**:
- Extends: `BaseOptimizer`
- Abstract method: None (concrete class, but designed to be extended)
- Key methods: `optimize(alphas, covariance) → Dict[str, float]`
- Constructor: `__init__(risk_aversion, long_only, leverage_limit, position_limit, allow_cash)`
- Return type: `WeightsDict` (dict-like wrapper)

**Purpose**: Mean-variance portfolio optimization with quadratic programming

---

### 4. BaseCovarianceEstimator (Risk/Base/BaseCovarianceEstimator.py)

**Contract**:
- Abstract method: `fit(returns) → np.ndarray`
- Concrete methods: `get_covariance()`, `get_correlation()`, `condition_number()`
- Constructor: `__init__(handle_missing='drop')`
- Stores: `self.cov_matrix_`, `self.asset_names_`

**Purpose**: Standardized covariance matrix estimation

---

## Implementation Verification

### ✅ Agent 1: Correlation Cluster Constraints

#### ClusterAwareMeanVarianceOptimizer (Optimizer/ClusterAwareMeanVarianceOptimizer.py)

**Status**: ✅ **COMPLIANT**

```python
class ClusterAwareMeanVarianceOptimizer(MeanVarianceOptimizer):  # Line 48
    def __init__(
        self,
        correlation_clusters: Dict[str, List[str]],
        max_per_cluster: int = 3,
        ...
    ):
        super().__init__(  # Lines 85-91
            risk_aversion=risk_aversion,
            long_only=long_only,
            ...
        )

    def optimize(  # Line 97
        self,
        alphas: pl.Series,
        covariance: pl.DataFrame,
    ) -> Dict[str, float]:
        ...
```

**Compliance**:
- ✅ Extends `MeanVarianceOptimizer`
- ✅ Calls `super().__init__()` with all parent parameters
- ✅ Overrides `optimize()` method correctly
- ✅ Returns `WeightsDict` (compatible with parent)
- ✅ Uses CVXPY for convex optimization with cluster constraints

---

#### BaseSectorCovarianceEstimator (Modified)

**Status**: ✅ **COMPLIANT**

- Already extended `BaseCovarianceEstimator`
- Added `get_correlation_clusters()` method (lines 264-356)
- Uses hierarchical clustering to detect correlation groups
- No abstraction violations

---

### ⚠️ Agent 2: Volatility Dispersion Trading

#### VolatilityRatioCalculator (Risk/Volatility/VolatilityRatioCalculator.py)

**Status**: ✅ **ACCEPTABLE** (Utility Class)

```python
class VolatilityRatioCalculator:  # Line 42
    def __init__(self, lookback: int = 30, annualization: int = 252):
        ...
```

**Analysis**:
- Does NOT extend any base class
- This is acceptable: utility class for IV/RV calculations
- Not a signal, query, optimizer, or risk model
- Provides calculation services to signals

---

#### ⚠️ CorrelationVolatilitySignal (Signals/CorrelationVolatilitySignal.py)

**Status**: ⚠️ **VIOLATION - Does NOT extend BaseSignal**

```python
class CorrelationVolatilitySignal:  # Line 43 - NO PARENT CLASS!
    def __init__(
        self,
        min_correlation: float = 0.85,
        lookback: int = 60,
        z_threshold: float = 2.0
    ):
        # No super().__init__() call!
        self.min_correlation = min_correlation
        self.lookback = lookback
        self.z_threshold = z_threshold

    def calculate(  # Line 71 - Not _calculate_raw_signal()!
        self,
        returns: pl.DataFrame,
        vol_ratios: pl.DataFrame,
        pairs: List[Tuple[str, str]]
    ) -> pl.DataFrame:
        ...
```

**Problems**:
1. ❌ Does NOT extend `BaseSignal`
2. ❌ Does NOT implement `_calculate_raw_signal()` abstract method
3. ❌ Does NOT call `super().__init__(name, standardize, track_history)`
4. ❌ Missing z-score standardization from BaseSignal
5. ❌ Missing IC tracking capabilities
6. ❌ Missing signal history tracking
7. ❌ Cannot integrate with `AlphaGenerator` (expects BaseSignal)

**Expected Structure**:
```python
class CorrelationVolatilitySignal(BaseSignal):
    def __init__(
        self,
        min_correlation: float = 0.85,
        lookback: int = 60,
        z_threshold: float = 2.0,
        standardize: bool = True,
        track_history: bool = True,
    ):
        super().__init__(
            name="correlation_volatility",
            standardize=standardize,
            track_history=track_history,
        )
        self.min_correlation = min_correlation
        self.lookback = lookback
        self.z_threshold = z_threshold

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        # Calculate signal for single asset pair
        ...
```

**Impact**:
- Cannot use with existing backtest infrastructure
- Cannot use with AlphaGenerator
- Missing standardization and IC tracking
- Inconsistent with all other signals

---

### ✅ Agent 3: Currency Translation Layer

#### CurrencyQuery (Query/Currencies/CurrencyQuery.py)

**Status**: ✅ **COMPLIANT**

```python
@dataclass(frozen=True)
class CurrencyQuery(BaseQuery):  # Line 18
    currency: str = ""
    tenor: str = ""
    structure: CurrencyStructure = CurrencyStructure.OUTRIGHT
    value: CurrencyValue = CurrencyValue.YIELD
    ...

    def return_query(self) -> List["CurrencyQuery"]:  # Line 112
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:  # Line 121
        return f"{self.currency}_{self.tenor}"

    def eval_expression(self, cube_name: Optional[str] = None) -> str:  # Line 139
        ...
```

**Compliance**:
- ✅ Extends `BaseQuery`
- ✅ Uses `@dataclass(frozen=True)` decorator
- ✅ Implements all abstract methods: `return_query()`, `col_name()`, `eval_expression()`
- ✅ Validates inputs in `__post_init__()`
- ✅ Perfect symmetry with equity queries (sector ↔ currency, stock ↔ tenor)

---

#### CurrencyCarrySignal (Signals/CurrencyCarrySignal.py)

**Status**: ✅ **COMPLIANT**

```python
class CurrencyCarrySignal(BaseSignal):  # Line 50
    def __init__(
        self,
        long_tenor: str = "10Y",
        short_tenor: str = "2Y",
        butterfly: bool = False,
        standardize: bool = True,
        track_history: bool = True,
    ):
        super().__init__(  # Lines 84-88
            name="currency_carry",
            standardize=standardize,
            track_history=track_history,
        )
        ...

    def _calculate_raw_signal(  # Line 95
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[any],
        as_of: date,
    ) -> float:
        # Calculate carry: long_tenor_yield - short_tenor_yield
        ...
```

**Compliance**:
- ✅ Extends `BaseSignal`
- ✅ Calls `super().__init__()` with name, standardize, track_history
- ✅ Implements `_calculate_raw_signal()` abstract method
- ✅ Returns `float` (raw carry value before standardization)
- ✅ Can generate batch signals with automatic z-score standardization
- ✅ Supports IC tracking and signal history

---

### ✅ Agent 4: ML-Enhanced Factors

#### FeatureEngineering (Signals/Utils/FeatureEngineering.py)

**Status**: ✅ **ACCEPTABLE** (Utility Class)

```python
class FeatureEngineering:  # Line 36
    def __init__(self):
        pass

    def calculate_momentum(self, returns, lookbacks) -> pl.DataFrame:
        ...

    def calculate_value(self, prices, fundamentals) -> pl.DataFrame:
        ...
```

**Analysis**:
- Does NOT extend any base class
- This is acceptable: utility class for feature engineering
- Provides data transformation services to ML signals
- Not a signal itself

---

#### MLPredictedReturnsSignal (Signals/MLPredictedReturnsSignal.py)

**Status**: ✅ **COMPLIANT**

```python
class MLPredictedReturnsSignal(BaseSignal):  # Line 65
    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
        random_state: int = 42,
        target_col: str = "next_return",
        standardize: bool = True,
        track_history: bool = True,
    ):
        super().__init__(  # Lines 101-105
            name="ml_predicted_returns",
            standardize=standardize,
            track_history=track_history,
        )
        ...

    def _calculate_raw_signal(  # Line 315
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        # Use trained Random Forest to predict return
        ...
```

**Compliance**:
- ✅ Extends `BaseSignal`
- ✅ Calls `super().__init__()` with name, standardize, track_history
- ✅ Implements `_calculate_raw_signal()` abstract method
- ✅ Returns `float` (predicted return before standardization)
- ✅ Provides additional methods: `train()`, `predict()`, `cross_validate()`, `get_feature_importance()`
- ✅ Uses Random Forest for ML-based return prediction

---

### ✅ Agent 5: CVaR Tail Risk Constraints

#### CVaRMeanVarianceOptimizer (Optimizer/CVaRMeanVarianceOptimizer.py)

**Status**: ✅ **COMPLIANT**

```python
class CVaRMeanVarianceOptimizer(MeanVarianceOptimizer):  # Line 52
    def __init__(
        self,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        ...
        cvar_alpha: float = 0.05,
        cvar_limit: float = 0.05,
        use_cvxpy: bool = True,
    ):
        super().__init__(  # Lines 95-101
            risk_aversion=risk_aversion,
            long_only=long_only,
            leverage_limit=leverage_limit,
            position_limit=position_limit,
            allow_cash=allow_cash,
        )
        self.cvar_alpha = cvar_alpha
        self.cvar_limit = cvar_limit
        self.use_cvxpy = use_cvxpy

    def optimize(  # Line 106
        self,
        alphas: pl.Series,
        covariance: pl.DataFrame,
        returns: Optional[np.ndarray] = None,
    ) -> Dict[str, float]:
        ...
```

**Compliance**:
- ✅ Extends `MeanVarianceOptimizer`
- ✅ Calls `super().__init__()` with all parent parameters
- ✅ Overrides `optimize()` method with additional `returns` parameter for CVaR
- ✅ Returns `WeightsDict` (compatible with parent)
- ✅ Uses CVXPY for convex optimization with CVaR constraints
- ✅ Implements Rockafellar & Uryasev (2000) CVaR formulation

---

## Summary

### Compliant Implementations: 5/6

| Implementation | Base Class | Status |
|---|---|---|
| ClusterAwareMeanVarianceOptimizer | MeanVarianceOptimizer | ✅ COMPLIANT |
| CurrencyQuery | BaseQuery | ✅ COMPLIANT |
| CurrencyCarrySignal | BaseSignal | ✅ COMPLIANT |
| MLPredictedReturnsSignal | BaseSignal | ✅ COMPLIANT |
| CVaRMeanVarianceOptimizer | MeanVarianceOptimizer | ✅ COMPLIANT |
| **CorrelationVolatilitySignal** | **None** | **⚠️ VIOLATION** |

### Utility Classes (Acceptable): 2

| Implementation | Type | Status |
|---|---|---|
| VolatilityRatioCalculator | Utility | ✅ ACCEPTABLE |
| FeatureEngineering | Utility | ✅ ACCEPTABLE |

---

## Critical Issue

### ⚠️ CorrelationVolatilitySignal Abstraction Violation

**File**: `Signals/CorrelationVolatilitySignal.py`

**Problem**: Does NOT extend `BaseSignal`

**User Requirement Violated**:
> "we MUST use the same abstract base classes across all of the implementations"

**Impact**:
1. Cannot integrate with existing backtest infrastructure
2. Cannot use with `AlphaGenerator` (expects BaseSignal interface)
3. Missing z-score standardization from BaseSignal
4. Missing IC tracking capabilities
5. Missing signal history tracking
6. Inconsistent with all other signals (CarrySignal, MomentumSignal, MeanReversionSignal, CurrencyCarrySignal, MLPredictedReturnsSignal)

**Required Fix**:
Refactor `CorrelationVolatilitySignal` to extend `BaseSignal` and implement `_calculate_raw_signal()` method.

---

## Abstraction Hierarchy Diagram

```
BaseCovarianceEstimator
├── SampleCovariance
├── LedoitWolfShrinkage
└── SectorBasedCovarianceEstimator
    ├── BaseSectorCovarianceEstimator (modified by Agent 1) ✅
    ├── BlockDiagonalCovariance
    └── TwoStepCovariance

BaseSignal
├── CarrySignal ✅
├── MomentumSignal ✅
├── MeanReversionSignal ✅
├── CurrencyCarrySignal ✅ (Agent 3)
├── MLPredictedReturnsSignal ✅ (Agent 4)
└── CorrelationVolatilitySignal ⚠️ MISSING (Agent 2)

BaseQuery
├── FuturesQuery ✅
├── EquityQuery ✅
└── CurrencyQuery ✅ (Agent 3)

BaseOptimizer
└── MeanVarianceOptimizer ✅
    ├── ClusterAwareMeanVarianceOptimizer ✅ (Agent 1)
    └── CVaRMeanVarianceOptimizer ✅ (Agent 5)

Utility Classes (No Base Class Required)
├── VolatilityRatioCalculator ✅ (Agent 2)
├── FeatureEngineering ✅ (Agent 4)
├── ReturnsCalculator ✅
└── VolatilityEstimator ✅
```

---

## Recommendations

1. **Immediate**: Fix `CorrelationVolatilitySignal` to extend `BaseSignal`
2. **Verify**: Run all tests to ensure abstraction compliance doesn't break functionality
3. **Document**: Update agent implementation notes with abstraction requirements
4. **Review**: Create integration notebook to demonstrate all signals work with common interface

---

## Testing Compliance

All implementations should pass these abstraction tests:

```python
# Test 1: Signals extend BaseSignal
from Signals.Base.BaseSignal import BaseSignal
assert isinstance(signal, BaseSignal)
assert hasattr(signal, '_calculate_raw_signal')
assert hasattr(signal, 'generate_batch')
assert hasattr(signal, 'calculate_ic')

# Test 2: Queries extend BaseQuery
from Query.Base.BaseQuery import BaseQuery
assert isinstance(query, BaseQuery)
assert hasattr(query, 'return_query')
assert hasattr(query, 'col_name')
assert hasattr(query, 'eval_expression')

# Test 3: Optimizers extend MeanVarianceOptimizer
from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer
assert isinstance(optimizer, MeanVarianceOptimizer)
assert hasattr(optimizer, 'optimize')
```

---

**End of Verification Report**
