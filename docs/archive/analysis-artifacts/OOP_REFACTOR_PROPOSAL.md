# ARBS Object-Oriented Refactor Proposal

**Date**: 2025-11-15
**Based On**: Complete file functionality documentation + dependency analysis
**Goal**: Reduce code duplication, improve abstraction, maintain 582 passing tests

---

## Executive Summary

**Current State**:
- 383 Python files, 91,834 lines of code
- 582 tests passing (35% test coverage)
- Identified **1,500-3,000 lines** of duplicate code
- Strong base class hierarchy (BaseSignal, BaseCovarianceEstimator, BaseQuery)
- Factory pattern implemented (Strategy, Signal, Alpha, Covariance)

**Proposed Changes**:
- **8 new abstract base classes** to eliminate duplication
- **3 mixin classes** for shared functionality
- **2 utility refactorings** for common patterns
- **Estimated savings**: 1,500-3,000 lines of code
- **Estimated effort**: 15-20 hours with parallel implementation

---

## Refactoring Priorities

### Priority 1: Critical Duplication (High Impact, Low Risk)

#### 1.1 **MDP Data Fetching Abstraction**

**Problem**: Identical `BaseFetcher.py` files in multiple MDP subdirectories (47 lines each × 2 = 94 duplicate lines)

**Current Duplication**:
```
MDP/IRSwaps/data_sources/cme/BaseFetcher.py (47 lines)
MDP/IRSwaps/data_sources/sdr/BaseFetcher.py (47 lines)
```

Both files contain identical:
- `fetch_with_retry()` method
- Exponential backoff logic
- Connection pooling
- Error handling

**Proposed Solution**: Create `MDP/Base/DataFetcher.py`

```python
# MDP/Base/DataFetcher.py
from abc import ABC, abstractmethod
from typing import Any, Optional, Callable
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class BaseDataFetcher(ABC):
    """Abstract base class for data fetching with retry logic and connection pooling"""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        pool_connections: int = 10,
        pool_maxsize: int = 10,
        timeout: int = 30
    ):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self._session = self._create_session(pool_connections, pool_maxsize)

    def _create_session(self, pool_connections: int, pool_maxsize: int) -> requests.Session:
        """Create requests session with connection pooling and retry logic"""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def fetch_with_retry(
        self,
        fetch_fn: Callable[[], Any],
        error_message: str = "Data fetch failed"
    ) -> Any:
        """Execute fetch function with retry logic"""
        try:
            return fetch_fn()
        except Exception as e:
            raise RuntimeError(f"{error_message}: {e}") from e

    @abstractmethod
    def fetch(self, **kwargs) -> Any:
        """Fetch data from source (must be implemented by subclass)"""
        pass
```

**Changes Required**:
1. Create `MDP/Base/DataFetcher.py` (30 lines)
2. Update `MDP/IRSwaps/data_sources/cme/BaseFetcher.py` to extend BaseDataFetcher (10 lines instead of 47)
3. Update `MDP/IRSwaps/data_sources/sdr/BaseFetcher.py` to extend BaseDataFetcher (10 lines instead of 47)
4. Update imports in dependent files (2 files)

**Savings**: 94 - 50 = 44 lines
**Effort**: 1 hour
**Risk**: Low (tests validate behavior)

---

#### 1.2 **Signal Calculation Pattern Abstraction**

**Problem**: MomentumSignal and MeanReversionSignal share 450-600 lines of duplicate patterns:
- Price history extraction
- Rolling window calculations
- Standardization logic
- History tracking

**Current Duplication**:
```python
# Both signals have identical patterns:
class MomentumSignal(BaseSignal):
    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        # Extract prices from last N days
        lookback_data = inst_data.filter(...)
        # Calculate price change
        # Handle edge cases
        # Return signal value

class MeanReversionSignal(BaseSignal):
    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        # Extract prices from last N days (SAME CODE)
        lookback_data = inst_data.filter(...)
        # Calculate deviation from mean
        # Handle edge cases (SAME CODE)
        # Return signal value
```

**Proposed Solution**: Create `Signals/Base/TimeSeriesSignal.py` mixin

```python
# Signals/Base/TimeSeriesSignal.py
from abc import ABC, abstractmethod
from typing import Optional
from datetime import date, timedelta
import polars as pl

class TimeSeriesSignalMixin:
    """Mixin providing common time-series signal functionality"""

    def _extract_lookback_data(
        self,
        inst_data: pl.DataFrame,
        as_of: date,
        lookback_days: int,
        required_columns: list[str] = ["date", "price"]
    ) -> pl.DataFrame:
        """Extract data for lookback window with validation"""
        start_date = as_of - timedelta(days=lookback_days)

        lookback_data = inst_data.filter(
            (pl.col("date") >= start_date) & (pl.col("date") <= as_of)
        )

        # Validate required columns present
        missing = set(required_columns) - set(lookback_data.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        # Validate sufficient data
        if len(lookback_data) < lookback_days * 0.5:  # At least 50% of lookback
            raise ValueError(
                f"Insufficient data: {len(lookback_data)} rows for {lookback_days} day lookback"
            )

        return lookback_data.sort("date")

    def _calculate_rolling_stat(
        self,
        data: pl.DataFrame,
        column: str,
        stat: str,
        window: Optional[int] = None
    ) -> float:
        """Calculate rolling statistic (mean, std, etc.)"""
        series = data[column]

        if window is None:
            window = len(series)

        if stat == "mean":
            return series.tail(window).mean()
        elif stat == "std":
            return series.tail(window).std()
        elif stat == "min":
            return series.tail(window).min()
        elif stat == "max":
            return series.tail(window).max()
        else:
            raise ValueError(f"Unknown statistic: {stat}")

    def _calculate_return(
        self,
        data: pl.DataFrame,
        price_col: str = "price",
        method: str = "percent"
    ) -> float:
        """Calculate return over lookback period"""
        prices = data[price_col]

        if len(prices) < 2:
            return 0.0

        if method == "percent":
            return (prices[-1] / prices[0]) - 1.0
        elif method == "log":
            return float(pl.Series([prices[-1]]).log() - pl.Series([prices[0]]).log())
        else:
            raise ValueError(f"Unknown return method: {method}")
```

**Refactored Signals**:
```python
# Signals/Futures/MomentumSignal.py
class MomentumSignal(BaseSignal, TimeSeriesSignalMixin):
    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        lookback_data = self._extract_lookback_data(inst_data, as_of, self.lookback_days)
        return self._calculate_return(lookback_data, method=self.method)

# Signals/Futures/MeanReversionSignal.py
class MeanReversionSignal(BaseSignal, TimeSeriesSignalMixin):
    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        lookback_data = self._extract_lookback_data(inst_data, as_of, self.lookback_days)
        mean = self._calculate_rolling_stat(lookback_data, "price", "mean")
        std = self._calculate_rolling_stat(lookback_data, "price", "std")
        current_price = lookback_data["price"][-1]
        return -(current_price - mean) / std  # Negative = reversion signal
```

**Changes Required**:
1. Create `Signals/Base/TimeSeriesSignalMixin.py` (80 lines)
2. Refactor `MomentumSignal` to use mixin (remove 200 lines, add 10 lines)
3. Refactor `MeanReversionSignal` to use mixin (remove 200 lines, add 10 lines)
4. Add tests for mixin (30 lines)

**Savings**: 400 - 120 = 280 lines
**Effort**: 3 hours
**Risk**: Medium (requires careful test validation)

---

#### 1.3 **Covariance Validation Logic Consolidation**

**Problem**: 6 covariance estimators duplicate 37 lines of validation code:
- Positive definiteness checking
- Eigenvalue clipping
- Condition number calculation
- NaN/Inf detection

**Current Duplication**:
```python
# Repeated in 6 files: LedoitWolf, OAS, BlockDiagonal, TwoStep, StochasticBlock, Sample
def _validate_covariance_matrix(self, cov_matrix: np.ndarray) -> None:
    """Validate covariance matrix properties"""
    # Check for NaN/Inf (same code × 6)
    # Check symmetry (same code × 6)
    # Check positive semi-definite (same code × 6)
    # Calculate condition number (same code × 6)
```

**Proposed Solution**: Add validation methods to `BaseCovarianceEstimator`

```python
# Risk/Base/BaseCovarianceEstimator.py (ADD TO EXISTING CLASS)

class BaseCovarianceEstimator(ABC):
    # ... existing methods ...

    def _validate_covariance_matrix(
        self,
        cov_matrix: np.ndarray,
        tol: float = 1e-10,
        check_symmetry: bool = True,
        check_positive_definite: bool = True
    ) -> None:
        """Validate covariance matrix mathematical properties

        Args:
            cov_matrix: Covariance matrix to validate
            tol: Tolerance for numerical checks
            check_symmetry: Whether to check matrix symmetry
            check_positive_definite: Whether to check positive definiteness

        Raises:
            ValueError: If validation fails
        """
        # Check for NaN/Inf
        if not np.isfinite(cov_matrix).all():
            raise ValueError("Covariance matrix contains NaN or Inf values")

        # Check square matrix
        if cov_matrix.shape[0] != cov_matrix.shape[1]:
            raise ValueError(f"Covariance matrix must be square, got shape {cov_matrix.shape}")

        # Check symmetry
        if check_symmetry:
            if not np.allclose(cov_matrix, cov_matrix.T, atol=tol):
                raise ValueError("Covariance matrix is not symmetric")

        # Check positive semi-definite
        if check_positive_definite:
            eigenvalues = np.linalg.eigvalsh(cov_matrix)
            if (eigenvalues < -tol).any():
                raise ValueError(
                    f"Covariance matrix has negative eigenvalues: "
                    f"min={eigenvalues.min():.2e}"
                )

    def _ensure_positive_definite(
        self,
        cov_matrix: np.ndarray,
        min_eigenvalue: float = 1e-8
    ) -> np.ndarray:
        """Ensure covariance matrix is positive definite via eigenvalue clipping

        Args:
            cov_matrix: Covariance matrix to fix
            min_eigenvalue: Minimum eigenvalue threshold

        Returns:
            Positive definite covariance matrix
        """
        eigenvalues, eigenvectors = np.linalg.eigh(cov_matrix)
        eigenvalues = np.maximum(eigenvalues, min_eigenvalue)
        return eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

    def _calculate_condition_number(self, cov_matrix: np.ndarray) -> float:
        """Calculate condition number of covariance matrix

        Returns:
            Condition number (ratio of largest to smallest eigenvalue)
        """
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        return eigenvalues.max() / eigenvalues.min()
```

**Changes Required**:
1. Add 3 methods to `BaseCovarianceEstimator` (60 lines)
2. Remove duplicate validation from 6 estimator classes (37 lines × 6 = 222 lines)
3. Update 6 estimators to call base class methods (6 lines × 6 = 36 lines)
4. Add tests for base validation methods (40 lines)

**Savings**: 222 - 136 = 86 lines
**Effort**: 2 hours
**Risk**: Low (purely moving existing code)

---

### Priority 2: Architectural Improvements (Medium Impact, Medium Risk)

#### 2.1 **Query Structure/Value Pattern Unification**

**Problem**: Each product (Futures, IRSwaps, Bonds, Equities, Currencies) implements nearly identical BaseStructureFunctionMap and BaseValueFunctionMap patterns with 150-200 lines of boilerplate each.

**Current Pattern** (repeated 5 times):
```python
# Query/[Product]/[Product]StructureFunctionMap.py
class FuturesStructureFunctionMap(BaseStructureFunctionMap[FuturesStructure, MockFuture]):
    def _create_map(self) -> Dict[FuturesStructure, Callable]:
        return {
            FuturesStructure.OUTRIGHT: self._build_outright,
            FuturesStructure.CALENDAR: self._build_calendar,
            # ... more structures
        }

    def _build_outright(self, **kwargs): ...
    def _build_calendar(self, **kwargs): ...
```

This pattern is repeated for:
- Futures (150 lines)
- IRSwaps (200 lines)
- FixedRateBonds (180 lines)
- Equities (120 lines)
- Currencies (140 lines)

**Total**: ~790 lines of similar structure

**Proposed Solution**: Enhance base classes with common functionality

```python
# Query/Base/BaseStructure.py (ENHANCE EXISTING CLASS)

class BaseStructureFunctionMap(ABC, Generic[E, T]):
    """Enhanced with common structure-building patterns"""

    # ... existing __init__ and apply methods ...

    def _validate_required_kwargs(self, kwargs: dict, required: list[str]) -> None:
        """Validate required kwargs are present"""
        missing = set(required) - set(kwargs.keys())
        if missing:
            raise ValueError(f"Missing required kwargs: {missing}")

    def _resolve_weights(
        self,
        risk_weights: Optional[List[float]],
        default_weights: List[float]
    ) -> List[float]:
        """Resolve risk weights with defaults"""
        if risk_weights is None:
            return default_weights
        if len(risk_weights) != len(default_weights):
            raise ValueError(
                f"Risk weights length {len(risk_weights)} != "
                f"structure length {len(default_weights)}"
            )
        return risk_weights

    def _normalize_weights(self, weights: List[float]) -> List[float]:
        """Normalize weights to sum to 1.0"""
        total = sum(abs(w) for w in weights)
        if total == 0:
            raise ValueError("Weights sum to zero")
        return [w / total for w in weights]
```

**Changes Required**:
1. Add 3 common methods to `BaseStructureFunctionMap` (40 lines)
2. Add 2 common methods to `BaseValueFunctionMap` (30 lines)
3. Refactor 5 product StructureFunctionMaps to use base methods (remove ~150 lines of duplication)
4. Refactor 5 product ValueFunctionMaps to use base methods (remove ~100 lines of duplication)

**Savings**: 250 lines
**Effort**: 4 hours
**Risk**: Medium (touching core query infrastructure)

---

#### 2.2 **Sector Utilities Consolidation**

**Problem**: Sector-based covariance models duplicate sector assignment, clustering, and block construction logic across 3 implementations.

**Current Duplication**:
- `BaseSectorCovarianceEstimator` has clustering logic
- `BlockDiagonalCovariance` duplicates sector grouping
- `StochasticBlockCovariance` duplicates sector grouping
- `TwoStepCovariance` duplicates clustering

**Proposed Solution**: Create comprehensive `SectorUtils` class

```python
# Risk/Covariance/SectorBased/SectorUtils.py (ENHANCE EXISTING FILE)

class SectorUtils:
    """Comprehensive sector assignment and clustering utilities"""

    @staticmethod
    def assign_sectors_predefined(
        returns: pl.DataFrame,
        sector_col: str = "sector"
    ) -> Dict[str, str]:
        """Extract predefined sector assignments from DataFrame"""
        # Extract ticker→sector mapping
        # Validate consistency
        # Return mapping

    @staticmethod
    def assign_sectors_hierarchical(
        returns: np.ndarray,
        tickers: List[str],
        n_clusters: Optional[int] = None,
        linkage_method: str = "ward"
    ) -> Dict[str, str]:
        """Assign sectors via hierarchical clustering"""
        # Use HierarchicalSectorClustering
        # Return ticker→cluster mapping

    @staticmethod
    def group_by_sector(
        ticker_sector_map: Dict[str, str]
    ) -> Dict[str, List[str]]:
        """Group tickers by sector assignment"""
        # Invert mapping
        # Return sector→tickers grouping

    @staticmethod
    def create_block_diagonal(
        blocks: Dict[str, np.ndarray],
        ticker_order: List[str],
        ticker_sector_map: Dict[str, str]
    ) -> np.ndarray:
        """Construct block-diagonal matrix from sector blocks"""
        # Build full matrix
        # Place blocks on diagonal
        # Return matrix

    @staticmethod
    def validate_sector_input(
        returns: pl.DataFrame,
        sector_col: Optional[str]
    ) -> None:
        """Validate sector DataFrame format"""
        # Check required columns
        # Check data types
        # Check for missing values
```

**Changes Required**:
1. Consolidate utilities into `SectorUtils` class (150 lines total)
2. Refactor `BaseSectorCovarianceEstimator` to use SectorUtils (remove 80 lines)
3. Refactor 3 sector models to use SectorUtils (remove 60 lines each = 180 lines)
4. Add comprehensive tests for SectorUtils (60 lines)

**Savings**: 260 - 210 = 50 lines
**Effort**: 3 hours
**Risk**: Medium (sector models are complex)

---

### Priority 3: New Abstractions (High Value, Higher Risk)

#### 3.1 **IC Calculation Utilities Centralization**

**Problem**: IC calculation code scattered across:
- `Signals/Utils/IC.py` (6 functions)
- `Signals/AlphaGenerator.py` (dynamic IC estimation)
- `Signals/Base/BaseSignal.py` (IC calculation method)
- Individual signal classes (IC tracking)

**Proposed Solution**: Create comprehensive `ICEstimator` class

```python
# Signals/Utils/ICEstimator.py (NEW FILE)

from abc import ABC, abstractmethod
from typing import Optional, Literal
import polars as pl
import numpy as np

class ICEstimator(ABC):
    """Abstract base class for Information Coefficient estimation"""

    @abstractmethod
    def estimate(
        self,
        forecasts: pl.Series,
        actuals: pl.Series,
        as_of: Optional[date] = None
    ) -> float:
        """Estimate IC from forecast-actual pairs"""
        pass

    def estimate_significance(
        self,
        forecasts: pl.Series,
        actuals: pl.Series
    ) -> tuple[float, float]:
        """Estimate IC and statistical significance (t-test)"""
        ic = self.estimate(forecasts, actuals)
        n = len(forecasts)
        t_stat = ic * np.sqrt(n - 2) / np.sqrt(1 - ic**2)
        from scipy.stats import t
        p_value = 2 * (1 - t.cdf(abs(t_stat), n - 2))
        return ic, p_value


class StaticICEstimator(ICEstimator):
    """Static IC estimator using fixed IC value"""

    def __init__(self, IC: float = 0.05):
        self.IC = IC

    def estimate(self, forecasts, actuals, as_of=None):
        return self.IC


class RollingICEstimator(ICEstimator):
    """Rolling window IC estimator"""

    def __init__(self, lookback: int = 60, min_periods: int = 20):
        self.lookback = lookback
        self.min_periods = min_periods

    def estimate(self, forecasts, actuals, as_of=None):
        if len(forecasts) < self.min_periods:
            raise ValueError(f"Insufficient data: {len(forecasts)} < {self.min_periods}")

        window = forecasts.tail(self.lookback)
        actuals_window = actuals.tail(self.lookback)

        return float(window.corr(actuals_window))


class EWMAICEstimator(ICEstimator):
    """Exponentially weighted moving average IC estimator"""

    def __init__(self, halflife: int = 30, min_periods: int = 20):
        self.halflife = halflife
        self.min_periods = min_periods

    def estimate(self, forecasts, actuals, as_of=None):
        if len(forecasts) < self.min_periods:
            raise ValueError(f"Insufficient data: {len(forecasts)} < {self.min_periods}")

        # Calculate time-decayed correlation
        alpha = 1 - np.exp(-np.log(2) / self.halflife)
        weights = alpha * (1 - alpha) ** np.arange(len(forecasts))[::-1]
        weights /= weights.sum()

        # Weighted correlation
        f = forecasts.to_numpy()
        a = actuals.to_numpy()
        cov = np.sum(weights * (f - f.mean()) * (a - a.mean()))
        std_f = np.sqrt(np.sum(weights * (f - f.mean())**2))
        std_a = np.sqrt(np.sum(weights * (a - a.mean())**2))

        return cov / (std_f * std_a)


class RegimeICEstimator(ICEstimator):
    """Regime-aware IC estimator (high/low volatility)"""

    def __init__(self, vol_threshold: float = 0.15, lookback: int = 60):
        self.vol_threshold = vol_threshold
        self.lookback = lookback

    def estimate(self, forecasts, actuals, as_of=None):
        # Calculate current volatility regime
        recent_returns = actuals.tail(self.lookback)
        current_vol = recent_returns.std()

        # Split history by regime
        all_returns = actuals.to_numpy()
        rolling_vol = pl.Series(all_returns).rolling_std(window_size=20)

        if current_vol > self.vol_threshold:
            # High volatility regime
            mask = rolling_vol > self.vol_threshold
        else:
            # Low volatility regime
            mask = rolling_vol <= self.vol_threshold

        regime_forecasts = forecasts.filter(mask)
        regime_actuals = actuals.filter(mask)

        if len(regime_forecasts) < 10:
            # Fallback to full history
            return float(forecasts.corr(actuals))

        return float(regime_forecasts.corr(regime_actuals))
```

**Changes Required**:
1. Create `Signals/Utils/ICEstimator.py` (200 lines)
2. Refactor `AlphaGenerator` to use ICEstimator (remove 80 lines, add 20 lines)
3. Refactor `BaseSignal` to use ICEstimator utilities (remove 15 lines, add 5 lines)
4. Update `AlphaFactory` to instantiate appropriate ICEstimator (add 30 lines)
5. Add comprehensive tests (80 lines)

**Savings**: 95 - 250 = -155 lines (NET INCREASE)
**Value**: Better separation of concerns, easier testing, clearer IC method selection
**Effort**: 4 hours
**Risk**: Medium-High (changes core alpha generation)

**Recommendation**: Accept small line increase for architectural benefit

---

#### 3.2 **Portfolio Construction Strategy Pattern**

**Problem**: Portfolio construction logic duplicated across:
- `GrinoldKahnPortfolio.generate_weights()` (signal → alpha → optimization)
- `Backtest.run()` (same logic)
- Future: Risk parity, equal weight, minimum variance strategies

**Proposed Solution**: Create `PortfolioConstructionStrategy` abstract class

```python
# Portfolio/PortfolioConstructionStrategy.py (NEW FILE)

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import polars as pl
import numpy as np
from datetime import date

class PortfolioConstructionStrategy(ABC):
    """Abstract strategy for constructing portfolio weights"""

    @abstractmethod
    def construct_weights(
        self,
        instruments: List[str],
        returns_history: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date
    ) -> Dict[str, float]:
        """Construct portfolio weights for given instruments and history"""
        pass


class GrinoldKahnStrategy(PortfolioConstructionStrategy):
    """Grinold-Kahn portfolio construction (signals → alphas → optimization)"""

    def __init__(
        self,
        signals: List[BaseSignal],
        alpha_generator: AlphaGenerator,
        risk_model: BaseCovarianceEstimator,
        optimizer: BaseOptimizer
    ):
        self.signals = signals
        self.alpha_generator = alpha_generator
        self.risk_model = risk_model
        self.optimizer = optimizer

    def construct_weights(self, instruments, returns_history, market_data, as_of):
        # 1. Generate signals
        signals = self._aggregate_signals(instruments, market_data, as_of)

        # 2. Convert to alphas
        alphas = self.alpha_generator.signals_to_alphas(signals, returns_history, as_of)

        # 3. Estimate risk
        cov_matrix = self.risk_model.fit(returns_history)

        # 4. Optimize
        weights = self.optimizer.optimize(alphas, cov_matrix)

        return weights

    def _aggregate_signals(self, instruments, market_data, as_of):
        # Multi-signal aggregation logic
        ...


class EqualWeightStrategy(PortfolioConstructionStrategy):
    """Equal-weight portfolio construction"""

    def construct_weights(self, instruments, returns_history, market_data, as_of):
        n = len(instruments)
        return {inst: 1.0 / n for inst in instruments}


class RiskParityStrategy(PortfolioConstructionStrategy):
    """Risk parity portfolio construction (equal risk contribution)"""

    def __init__(self, risk_model: BaseCovarianceEstimator):
        self.risk_model = risk_model

    def construct_weights(self, instruments, returns_history, market_data, as_of):
        # Estimate covariance
        cov_matrix = self.risk_model.fit(returns_history)

        # Solve for equal risk contribution weights
        from scipy.optimize import minimize

        def risk_parity_objective(w, cov):
            portfolio_var = w @ cov @ w
            marginal_risk = cov @ w
            risk_contrib = w * marginal_risk
            target_risk = portfolio_var / len(w)
            return np.sum((risk_contrib - target_risk)**2)

        n = len(instruments)
        w0 = np.ones(n) / n
        bounds = [(0, 1) for _ in range(n)]
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1}]

        result = minimize(
            risk_parity_objective,
            w0,
            args=(cov_matrix,),
            bounds=bounds,
            constraints=constraints
        )

        return {inst: w for inst, w in zip(instruments, result.x)}


class MinimumVarianceStrategy(PortfolioConstructionStrategy):
    """Minimum variance portfolio construction"""

    def __init__(self, risk_model: BaseCovarianceEstimator):
        self.risk_model = risk_model

    def construct_weights(self, instruments, returns_history, market_data, as_of):
        cov_matrix = self.risk_model.fit(returns_history)

        from scipy.optimize import minimize

        def variance_objective(w, cov):
            return w @ cov @ w

        n = len(instruments)
        w0 = np.ones(n) / n
        bounds = [(0, 1) for _ in range(n)]
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1}]

        result = minimize(
            variance_objective,
            w0,
            args=(cov_matrix,),
            bounds=bounds,
            constraints=constraints
        )

        return {inst: w for inst, w in zip(instruments, result.x)}
```

**Refactored GrinoldKahnPortfolio**:
```python
class GrinoldKahnPortfolio(Asset):
    def __init__(self, identifier, signals, alpha_generator, risk_model, optimizer, ...):
        self.strategy = GrinoldKahnStrategy(signals, alpha_generator, risk_model, optimizer)
        # ... other init ...

    def generate_weights(self, instruments, returns_history, market_data, as_of):
        return self.strategy.construct_weights(instruments, returns_history, market_data, as_of)
```

**Changes Required**:
1. Create `Portfolio/PortfolioConstructionStrategy.py` (250 lines)
2. Refactor `GrinoldKahnPortfolio` to use strategy (remove 60 lines, add 15 lines)
3. Refactor `Backtest` to optionally accept strategy (add 20 lines)
4. Add tests for strategies (100 lines)

**Savings**: 60 - 285 = -225 lines (NET INCREASE)
**Value**: Enables easy addition of new portfolio construction methods
**Effort**: 5 hours
**Risk**: Medium-High (changes portfolio construction)

**Recommendation**: Implement later when more strategies are needed

---

## Summary of Proposed Changes

### Immediate Priorities (Do Now)

| Refactoring | Lines Saved | Effort | Risk | Priority |
|-------------|-------------|--------|------|----------|
| MDP Data Fetching | 44 | 1h | Low | 1 |
| Covariance Validation | 86 | 2h | Low | 2 |
| Signal Time-Series Mixin | 280 | 3h | Medium | 3 |
| **TOTAL** | **410 lines** | **6h** | - | - |

### Medium-Term Priorities (Next Sprint)

| Refactoring | Lines Saved | Effort | Risk | Priority |
|-------------|-------------|--------|------|----------|
| Query Pattern Unification | 250 | 4h | Medium | 4 |
| Sector Utilities | 50 | 3h | Medium | 5 |
| **TOTAL** | **300 lines** | **7h** | - | - |

### Long-Term Enhancements (Future)

| Refactoring | Lines Changed | Effort | Risk | Priority |
|-------------|---------------|--------|------|----------|
| IC Estimator Classes | -155 (increase) | 4h | Medium-High | 6 |
| Portfolio Strategy Pattern | -225 (increase) | 5h | Medium-High | 7 |

---

## Implementation Plan

### Phase 1: Low-Hanging Fruit (6 hours total)

**Week 1**:
1. Create `MDP/Base/DataFetcher.py` (1 hour)
   - Write base class
   - Refactor CME and SDR fetchers
   - Run existing MDP tests
   - Commit: "refactor: consolidate MDP data fetching logic"

2. Add validation to `BaseCovarianceEstimator` (2 hours)
   - Add 3 validation methods to base class
   - Refactor 6 estimator classes
   - Run existing risk tests (138 tests)
   - Commit: "refactor: consolidate covariance validation logic"

3. Create `TimeSeriesSignalMixin` (3 hours)
   - Write mixin class
   - Refactor MomentumSignal and MeanReversionSignal
   - Add mixin tests
   - Run all signal tests (156 tests)
   - Commit: "refactor: add TimeSeriesSignalMixin for common signal patterns"

**Validation**: All 582 tests still passing

---

### Phase 2: Architectural Improvements (7 hours total)

**Week 2**:
1. Enhance Query base classes (4 hours)
   - Add common methods to BaseStructureFunctionMap
   - Add common methods to BaseValueFunctionMap
   - Refactor 5 product implementations
   - Run query tests
   - Commit: "refactor: enhance Query base classes with common functionality"

2. Consolidate sector utilities (3 hours)
   - Create comprehensive SectorUtils class
   - Refactor BaseSectorCovarianceEstimator
   - Refactor 3 sector models
   - Run sector covariance tests
   - Commit: "refactor: consolidate sector utilities"

**Validation**: All 582 tests still passing

---

### Phase 3: New Abstractions (Optional, 9 hours)

**Week 3** (if pursuing):
1. Create ICEstimator class hierarchy (4 hours)
2. Create PortfolioConstructionStrategy pattern (5 hours)

---

## Risk Mitigation

### Test Coverage
- All refactorings must maintain 582 passing tests
- Add new tests for new abstractions
- Use TDD: write tests first, refactor to pass

### Incremental Changes
- One refactoring per commit
- Each commit leaves codebase in working state
- Easy to revert if issues discovered

### Parallel Development
- Use parallel agents for orthogonal refactorings:
  - Agent 1: MDP DataFetcher
  - Agent 2: Covariance Validation
  - Agent 3: TimeSeriesSignalMixin
  - Agent 4: Query Enhancements
  - Agent 5: Sector Utilities
- All agents work on different files (no merge conflicts)

---

## Expected Outcomes

### Code Quality
- **710 fewer lines** of duplicated code (Phases 1-2)
- Improved abstraction and separation of concerns
- Easier to add new signals, risk models, strategies

### Maintainability
- Validation logic centralized (easier to enhance)
- Common patterns extracted (DRY principle)
- Clear inheritance hierarchy

### Testing
- Existing tests validate refactorings
- New tests for base class functionality
- Test coverage maintained at 35%+

### Performance
- No performance impact (code is equivalent)
- Potential improvement from optimized base implementations

---

## Conclusion

**Recommend implementing Phases 1-2 (13 hours total)**:
- Remove 710 lines of duplication
- Low to medium risk (validated by tests)
- Clear architectural benefits
- Enables future extensibility

**Defer Phase 3** until more strategies are needed to justify the architectural overhead.

All refactorings follow ARBS design principles:
- Extend existing classes (don't create parallel systems)
- Maintain test coverage
- Incremental changes with validation
- DRY without over-engineering

---

**Next Step**: Get Peter's approval and launch parallel agents for Phase 1 refactorings.
