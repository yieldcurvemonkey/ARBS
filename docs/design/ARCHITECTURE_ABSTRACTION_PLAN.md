# Architecture Abstraction Plan

## Executive Summary

**Current State:**
- **Total codebase**: 91,834 lines of Python code (383 files)
- **Production code**: ~59,461 lines
- **Test code**: 32,373 lines (35% test coverage by LOC)
- **Key modules**: Signals (5,929 lines), Risk (5,325 lines), MDP (thousands), Adapters (734 lines)

**Identified Duplication:**
- **Signal classes**: ~450-600 lines of duplicated batch processing logic
- **Risk models**: ~50-100 lines of duplicated validation and helper methods
- **MDP Fetchers**: 100+ lines including IDENTICAL BaseFetcher files in ql_basic and rl_basic
- **Adapters**: ~50-75 lines of duplicated error handling and DataFrame creation
- **Validation logic**: Spread across 20+ files

**Proposed Abstractions:**
- 8 new abstract base classes or mixins
- 4 consolidation opportunities
- 3 new utility modules

**Expected Impact:**
- **Code reduction**: 1,500-3,000 lines (2-4% LOC reduction)
- **Maintainability**: Significant improvement through DRY principles
- **Consistency**: Standardized patterns across all modules
- **Testability**: Easier to test common functionality once
- **Extensibility**: Clearer extension points for new implementations

---

## Abstraction Opportunities

### 1. Signal Abstraction - HIGH IMPACT

#### Current State
**Duplication found in:**
- `Signals/Futures/MomentumSignal.py` (312 lines)
- `Signals/Futures/MeanReversionSignal.py` (331 lines)
- Both have identical `calculate()`, `_standardize_signals()`, `_update_history()` methods

**Pattern analysis:**
```python
# DUPLICATED PATTERN (appears in 2+ files):
def calculate(self, instruments: List[str], market_data: Any, as_of: date) -> Dict[str, float]:
    raw_signals = {}
    for instrument in instruments:
        # Get price history from MDP
        price_history = market_data.get_price_history(...)
        # Calculate raw signal
        raw_signal = self._calculate_raw_signal(...)
        raw_signals[instrument] = raw_signal

    # Standardize
    if self.standardize:
        signals = self._standardize_signals(raw_signals)

    # Update history
    if self.track_history:
        self._update_history(as_of, signals)

    return signals

def _standardize_signals(self, raw_signals: Dict[str, float]) -> Dict[str, float]:
    # ~30 lines of z-score calculation logic
    # IDENTICAL in both files

def _update_history(self, as_of: date, signals: Dict[str, float]):
    # ~10 lines of history tracking
    # IDENTICAL in both files
```

#### Proposed Solution

**Move to BaseSignal:**
```python
# In Signals/Base/BaseSignal.py

class BaseSignal(ABC):
    # Existing code...

    def calculate(
        self,
        instruments: List[str],
        market_data: Any,
        as_of: date,
    ) -> Dict[str, float]:
        """
        Calculate signals for multiple instruments (DEFAULT IMPLEMENTATION).

        Override this method only if you need custom batch processing logic.
        Most signals can just implement _calculate_raw_signal() and
        _get_instrument_data().
        """
        raw_signals = {}

        for instrument in instruments:
            try:
                inst_data = self._get_instrument_data(
                    instrument, market_data, as_of
                )
                raw_signal = self._calculate_raw_signal(
                    inst_data, market_data, as_of
                )
                raw_signals[instrument] = raw_signal
            except Exception as e:
                self._handle_calculation_error(instrument, e)
                raw_signals[instrument] = 0.0

        # Standardize if requested
        if self.standardize:
            signals = self._standardize_dict(raw_signals)
        else:
            signals = raw_signals

        # Track history if enabled
        if self.track_history:
            self._update_history_dict(as_of, signals)

        self.last_generated = as_of
        return signals

    @abstractmethod
    def _get_instrument_data(
        self,
        instrument: str,
        market_data: Any,
        as_of: date,
    ) -> pl.DataFrame:
        """
        Fetch data for a single instrument from market_data provider.

        This method must be implemented by subclasses to define
        what data is needed for signal calculation.

        Examples:
            - MomentumSignal: get_price_history(lookback window)
            - CarrySignal: get_futures_data(front + back contracts)
            - VolatilitySignal: get_price_history(volatility window)
        """
        pass

    def _standardize_dict(self, raw_signals: Dict[str, float]) -> Dict[str, float]:
        """Standardize dict of signals to z-scores."""
        if len(raw_signals) == 0:
            return {}
        if len(raw_signals) == 1:
            return {k: 0.0 for k in raw_signals.keys()}

        signal_array = np.array(list(raw_signals.values()))
        mean_signal = np.mean(signal_array)
        std_signal = np.std(signal_array, ddof=1)

        if std_signal < 1e-10:
            return {k: 0.0 for k in raw_signals.keys()}

        standardized = {}
        for instrument, raw_value in raw_signals.items():
            z_score = (raw_value - mean_signal) / std_signal
            standardized[instrument] = float(z_score)

        return standardized

    def _update_history_dict(self, as_of: date, signals: Dict[str, float]):
        """Update signal history for dict-based signals."""
        if self.history is None:
            self.history = {}

        self.history[as_of] = {
            'signals': signals.copy(),
            'mean': np.mean(list(signals.values())),
            'std': np.std(list(signals.values()), ddof=1) if len(signals) > 1 else 0.0
        }

    def _handle_calculation_error(self, instrument: str, error: Exception):
        """Handle errors during signal calculation."""
        if hasattr(self, '_logger'):
            self._logger.warning(
                f"Error calculating signal for {instrument}: {error}"
            )
        else:
            print(f"Warning: Error calculating signal for {instrument}: {error}")
```

**Updated concrete implementations:**
```python
# In Signals/Futures/MomentumSignal.py

class MomentumSignal(BaseSignal):
    # __init__ stays the same

    # DELETE calculate(), _standardize_signals(), _update_history()
    # They're now in BaseSignal!

    # ONLY implement these two methods:
    def _get_instrument_data(
        self,
        instrument: str,
        market_data: Any,
        as_of: date
    ) -> pl.DataFrame:
        """Fetch price history for momentum calculation."""
        lookback_date = as_of - timedelta(days=self.lookback_days + 10)
        return market_data.get_price_history(
            instrument,
            start_date=lookback_date,
            end_date=as_of
        )

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        # Existing implementation stays the same
        ...
```

#### Benefits
- **Code reduction**: ~80 lines × 2 files = 160 lines removed
- **Consistency**: All signals use same batch processing logic
- **Maintainability**: Fix bugs in one place
- **Extensibility**: New signals only implement 2 methods instead of 5+

#### Implementation Phases
1. **Phase 1.1**: Add new methods to BaseSignal (keep existing working)
2. **Phase 1.2**: Update MomentumSignal to use new methods
3. **Phase 1.3**: Run tests, verify behavior identical
4. **Phase 1.4**: Update MeanReversionSignal
5. **Phase 1.5**: Update other signal classes
6. **Phase 1.6**: Remove old duplicated code

#### Risks & Mitigation
- **Risk**: Breaking existing signal behavior
  - **Mitigation**: TDD - write tests comparing old vs new behavior first
- **Risk**: Some signals need custom batch logic
  - **Mitigation**: Keep `calculate()` overridable, provide sensible default

---

### 2. Risk Model Abstraction - MEDIUM IMPACT

#### Current State
**Duplication found in:**
- `Risk/Covariance/OAShrinkage.py`: Has `_validate_covariance_matrix()` (37 lines)
- `Risk/Covariance/LedoitWolfShrinkage.py`: Missing validation but should have it
- Different names for shrinkage intensity getters

**Pattern analysis:**
```python
# DUPLICATED in OAShrinkage (should be in BaseCovarianceEstimator):
def _validate_covariance_matrix(self, cov_matrix: np.ndarray, tol: float = 1e-10):
    # Check square
    if cov_matrix.ndim != 2 or cov_matrix.shape[0] != cov_matrix.shape[1]:
        raise ValueError(...)

    # Check symmetric
    if not np.allclose(cov_matrix, cov_matrix.T, atol=tol):
        raise ValueError(...)

    # Check positive semi-definite
    eigenvalues = np.linalg.eigvalsh(cov_matrix)
    if np.min(eigenvalues) < -tol:
        raise ValueError(...)
```

#### Proposed Solution

**Move validation to base class:**
```python
# In Risk/Base/BaseCovarianceEstimator.py

class BaseCovarianceEstimator(ABC):
    # Existing code...

    def _validate_covariance_matrix(
        self,
        cov_matrix: np.ndarray,
        tol: float = 1e-10
    ) -> None:
        """
        Validate covariance matrix properties.

        All covariance estimators should call this after estimation
        to ensure mathematical validity.

        Checks:
        1. Square (N×N)
        2. Symmetric (Σ = Σᵀ)
        3. Positive semi-definite (all eigenvalues ≥ 0)

        Args:
            cov_matrix: Covariance matrix to validate
            tol: Tolerance for symmetry and eigenvalue checks

        Raises:
            ValueError: If validation fails
        """
        # Check square
        if cov_matrix.ndim != 2 or cov_matrix.shape[0] != cov_matrix.shape[1]:
            raise ValueError(
                f"Covariance matrix must be square, got shape {cov_matrix.shape}"
            )

        # Check symmetric
        if not np.allclose(cov_matrix, cov_matrix.T, atol=tol):
            max_diff = np.max(np.abs(cov_matrix - cov_matrix.T))
            raise ValueError(
                f"Covariance matrix must be symmetric. "
                f"Max asymmetry: {max_diff:.2e}"
            )

        # Check positive semi-definite
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        min_eigenvalue = np.min(eigenvalues)
        if min_eigenvalue < -tol:
            raise ValueError(
                f"Covariance matrix must be positive semi-definite. "
                f"Minimum eigenvalue: {min_eigenvalue:.2e}"
            )

    def _compute_sample_covariance(
        self,
        returns: np.ndarray,
        handle_missing: str = 'drop'
    ) -> np.ndarray:
        """
        Compute sample covariance (common step for all estimators).

        Args:
            returns: Returns array (T×N)
            handle_missing: 'drop' or 'pairwise'

        Returns:
            Sample covariance matrix (N×N)
        """
        if handle_missing == 'pairwise':
            return self._pairwise_covariance(returns)
        else:
            # Standard covariance (listwise deletion)
            return np.cov(returns.T, ddof=1)

    def _pairwise_covariance(self, returns: np.ndarray) -> np.ndarray:
        """Compute covariance using pairwise complete observations."""
        N = returns.shape[1]
        cov_matrix = np.zeros((N, N))

        for i in range(N):
            for j in range(i, N):
                valid_mask = ~(np.isnan(returns[:, i]) | np.isnan(returns[:, j]))
                valid_i = returns[valid_mask, i]
                valid_j = returns[valid_mask, j]

                if len(valid_i) > 1:
                    cov_ij = np.cov(valid_i, valid_j)[0, 1]
                else:
                    cov_ij = 0.0

                cov_matrix[i, j] = cov_ij
                cov_matrix[j, i] = cov_ij

        return cov_matrix
```

**Create ShrinkageEstimator abstract base:**
```python
# In Risk/Covariance/Base/ShrinkageEstimator.py

from abc import ABC, abstractmethod
from Risk.Base.BaseCovarianceEstimator import BaseCovarianceEstimator

class ShrinkageEstimator(BaseCovarianceEstimator, ABC):
    """
    Abstract base for shrinkage-based covariance estimators.

    Provides common interface for shrinkage methods:
    - Ledoit-Wolf
    - OAS
    - GraphicalLasso
    - Custom shrinkage
    """

    def __init__(self, target: str = 'constant_correlation', **kwargs):
        super().__init__(**kwargs)
        self.target_type = target
        self.shrinkage_intensity_: Optional[float] = None
        self.target_matrix_: Optional[np.ndarray] = None
        self.sample_cov_: Optional[np.ndarray] = None

    @abstractmethod
    def _compute_shrinkage_intensity(
        self,
        returns: np.ndarray,
        sample_cov: np.ndarray,
        target: np.ndarray,
    ) -> float:
        """
        Compute optimal shrinkage intensity.

        Subclasses implement different formulas:
        - Ledoit-Wolf: Analytic formula
        - OAS: Oracle approximation
        - Custom: User-defined

        Returns:
            Shrinkage intensity δ ∈ [0, 1]
        """
        pass

    def get_shrinkage_intensity(self) -> float:
        """Get the optimal shrinkage intensity (STANDARDIZED NAME)."""
        if self.shrinkage_intensity_ is None:
            raise ValueError("Must call fit() before get_shrinkage_intensity()")
        return self.shrinkage_intensity_

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """Standard shrinkage workflow."""
        # Handle missing data
        returns_clean = self._handle_missing_data(returns)
        self.asset_names_ = list(returns_clean.columns)

        # Calculate sample covariance
        returns_np = returns_clean.to_numpy()
        self.sample_cov_ = self._compute_sample_covariance(
            returns_np, self.handle_missing
        )

        # Calculate shrinkage target
        self.target_matrix_ = self._compute_target(returns_clean)

        # Calculate optimal shrinkage intensity (subclass-specific)
        self.shrinkage_intensity_ = self._compute_shrinkage_intensity(
            returns_np, self.sample_cov_, self.target_matrix_
        )

        # Apply shrinkage: Σ̂ = δ * F + (1-δ) * S
        self.cov_matrix_ = (
            self.shrinkage_intensity_ * self.target_matrix_ +
            (1 - self.shrinkage_intensity_) * self.sample_cov_
        )

        # Validate result
        self._validate_covariance_matrix(self.cov_matrix_)

        return self.cov_matrix_
```

**Updated implementations:**
```python
# In Risk/Covariance/LedoitWolfShrinkage.py

class LedoitWolfShrinkage(ShrinkageEstimator):
    # __init__ simplified - parent handles most attributes

    def _compute_shrinkage_intensity(self, returns, sample_cov, target) -> float:
        # Existing implementation stays the same
        # Just the formula calculation
        ...

    # DELETE: fit(), get_shrinkage_intensity(), validation code
    # They're now in ShrinkageEstimator base class!
```

#### Benefits
- **Code reduction**: ~100-150 lines across risk models
- **Consistency**: All shrinkage estimators use same interface
- **Correctness**: Validation always applied, hard to forget
- **Extensibility**: Easy to add new shrinkage methods

#### Implementation Phases
1. **Phase 2.1**: Create ShrinkageEstimator base class
2. **Phase 2.2**: Add validation to BaseCovarianceEstimator
3. **Phase 2.3**: Update LedoitWolfShrinkage
4. **Phase 2.4**: Update OAShrinkage
5. **Phase 2.5**: Run risk model tests
6. **Phase 2.6**: Remove duplicated code

---

### 3. MDP Fetcher Consolidation - HIGH IMPACT

#### Current State
**CRITICAL DUPLICATION:**
- `MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/BaseFetcher.py` (47 lines)
- `MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/BaseFetcher.py` (47 lines)
- **These files are IDENTICAL** (diff shows zero differences)

**Additional patterns:**
- 17 fetcher classes across MDP hierarchy
- All have similar HTTP client setup
- All have similar logging configuration
- All have similar timeout handling

#### Proposed Solution

**Consolidate to single shared base:**
```python
# In MDP/Base/BaseFetcher.py (NEW LOCATION)

import logging
from typing import Dict, Optional
import httpx


class BaseFetcher:
    """
    Base class for all data fetchers.

    Provides common HTTP client setup, logging, and error handling.
    Used by all MDP fetchers (QuantLib-based, RatesLib-based, etc.)
    """

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: bool = False,
        info_verbose: bool = False,
        warning_verbose: bool = False,
        error_verbose: bool = False,
    ):
        """
        Initialize base fetcher.

        Args:
            global_timeout: Default timeout for HTTP requests (seconds)
            proxies: HTTP/HTTPS proxy configuration
            debug_verbose: Enable DEBUG logging
            info_verbose: Enable INFO logging
            warning_verbose: Enable WARNING logging
            error_verbose: Enable ERROR logging
        """
        self._global_timeout = global_timeout
        self._proxies = proxies if proxies else {"http": None, "https": None}
        self._httpx_proxies = {
            "http://": httpx.AsyncHTTPTransport(proxy=self._proxies["http"]),
            "https://": httpx.AsyncHTTPTransport(proxy=self._proxies["https"]),
        }

        self._debug_verbose = debug_verbose
        self._info_verbose = info_verbose
        self._error_verbose = error_verbose
        self._warning_verbose = warning_verbose
        self._setup_logger()

    def _setup_logger(self):
        """Configure logger for this fetcher."""
        self._logger = logging.getLogger(self.__class__.__name__)

        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            )
            self._logger.addHandler(handler)

        # Set level based on verbosity
        if self._debug_verbose:
            self._logger.setLevel(logging.DEBUG)
        elif self._info_verbose:
            self._logger.setLevel(logging.INFO)
        elif self._error_verbose:
            self._logger.setLevel(logging.ERROR)
        elif self._warning_verbose:
            self._logger.setLevel(logging.WARNING)
        else:
            self._logger.disabled = True

    def get_http_client(self) -> httpx.Client:
        """Get configured HTTP client."""
        return httpx.Client(
            timeout=self._global_timeout,
            transport=self._httpx_proxies.get("https://"),
        )

    def get_async_http_client(self) -> httpx.AsyncClient:
        """Get configured async HTTP client."""
        return httpx.AsyncClient(
            timeout=self._global_timeout,
            transport=self._httpx_proxies.get("https://"),
        )
```

**Update all fetchers:**
```python
# In MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/CMEFetcher.py
from MDP.Base.BaseFetcher import BaseFetcher  # NEW import

class CMEFetcher(BaseFetcher):
    # No need to reimplement __init__, _setup_logger(), etc.
    # Just inherit!
    ...

# DELETE: MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/BaseFetcher.py
# DELETE: MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/BaseFetcher.py
```

#### Benefits
- **Code reduction**: 47 lines × 2 = 94 lines immediately, more as other fetchers adopt
- **DRY**: Single source of truth for HTTP/logging setup
- **Consistency**: All fetchers behave the same way
- **Maintainability**: Update logging once, applies everywhere

#### Implementation Phases
1. **Phase 3.1**: Create MDP/Base/BaseFetcher.py
2. **Phase 3.2**: Update ql_basic fetchers to import from new location
3. **Phase 3.3**: Update rl_basic fetchers to import from new location
4. **Phase 3.4**: Run MDP tests
5. **Phase 3.5**: Delete duplicate BaseFetcher files
6. **Phase 3.6**: Update other fetcher hierarchies

---

### 4. Adapter Error Handling - LOW-MEDIUM IMPACT

#### Current State
**Duplication found in:**
- `Adapter/FuturesAdapter.py`: Error handling in `_convert_outright()` and `_convert_calendar()`
- `Adapter/EquityAdapter.py`: Error handling in `_convert_single_query()` and `_fetch_prices()`

**Pattern analysis:**
```python
# REPEATED PATTERN:
try:
    # Fetch data
    # Transform data
    # Return result
except Exception as e:
    # Log warning
    # Return empty/NaN values with same schema
    return {
        'contract': contract,
        'price': np.nan,
        'next_price': np.nan,
        # ... more fields
    }
```

#### Proposed Solution

**Create error handling mixin:**
```python
# In Adapter/Base/ErrorHandlingMixin.py

from typing import Dict, Any, Callable
import numpy as np
import polars as pl


class ErrorHandlingMixin:
    """
    Mixin providing standardized error handling for adapters.
    """

    def safe_convert(
        self,
        func: Callable,
        error_return: Dict[str, Any],
        log_prefix: str = "",
    ) -> Dict[str, Any]:
        """
        Safely execute conversion function with graceful degradation.

        Args:
            func: Function to execute (should return dict)
            error_return: Dict to return on error (with NaN values)
            log_prefix: Prefix for log message

        Returns:
            Result dict or error_return dict
        """
        try:
            return func()
        except Exception as e:
            if hasattr(self, '_logger'):
                self._logger.warning(f"{log_prefix}: {e}")
            else:
                print(f"Warning {log_prefix}: {e}")
            return error_return

    def create_empty_dataframe(self, schema: Dict[str, type]) -> pl.DataFrame:
        """
        Create empty DataFrame with specified schema.

        Args:
            schema: Dict mapping column names to types
                   e.g., {'contract': str, 'price': float, ...}

        Returns:
            Empty polars DataFrame with schema
        """
        return pl.DataFrame({
            col: pl.Series([], dtype=dtype)
            for col, dtype in schema.items()
        })

    @staticmethod
    def nan_dict(keys: list, defaults: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Create dict with NaN values for numeric fields.

        Args:
            keys: List of keys to include
            defaults: Dict of non-NaN default values

        Returns:
            Dict with NaN for numeric fields, defaults for others
        """
        result = {key: np.nan for key in keys}
        if defaults:
            result.update(defaults)
        return result
```

**Updated adapters:**
```python
# In Adapter/Base/BaseAdapter.py

from Adapter.Base.ErrorHandlingMixin import ErrorHandlingMixin

class BaseAdapter(ABC, ErrorHandlingMixin):
    # Now all adapters have error handling methods
    ...

# In Adapter/FuturesAdapter.py

class FuturesAdapter(BaseAdapter):
    def _convert_outright(self, query: FuturesQuery, as_of_date: date) -> dict:
        """Convert outright futures query to signal format."""
        contract = query.contract

        # Define error return schema
        error_return = self.nan_dict(
            keys=['price', 'next_price', 'roll_date', 'expiry'],
            defaults={'contract': contract}
        )

        # Use safe_convert from mixin
        return self.safe_convert(
            func=lambda: self._do_convert_outright(query, as_of_date),
            error_return=error_return,
            log_prefix=f"Error converting {contract}"
        )

    def _do_convert_outright(self, query: FuturesQuery, as_of_date: date) -> dict:
        """Actual conversion logic (can raise exceptions)."""
        # Original implementation without try/except
        contract = query.contract
        price = self._get_price(contract, as_of_date)
        expiry = get_contract_expiry(contract)
        # ... etc
        return {
            'contract': contract,
            'price': price,
            'next_contract': next_contract,
            'next_price': next_price,
            'roll_date': roll_date,
            'expiry': expiry,
        }
```

#### Benefits
- **Code reduction**: ~50-75 lines across adapters
- **Consistency**: All adapters handle errors the same way
- **Clarity**: Separation of conversion logic from error handling
- **Testability**: Can test error handling separately

---

### 5. Sector Signal Wrapper - LOW IMPACT

#### Current State
**Pattern found in:**
- `Signals/SectorRotation/SectorMomentumSignal.py`
- `Signals/SectorRotation/SectorReversionSignal.py`

Both follow identical wrapper pattern:
- Delegate to factor calculator (MomentumFactor, ReversionFactor)
- Provide BaseSignal interface
- Handle z-score standardization

#### Proposed Solution

**Create abstract wrapper:**
```python
# In Signals/SectorRotation/Base/SectorSignalWrapper.py

from abc import ABC, abstractmethod
from Signals.Base.BaseSignal import BaseSignal

class SectorSignalWrapper(BaseSignal, ABC):
    """
    Abstract base for sector signals that wrap factor calculators.

    Provides common interface for signals that delegate to
    specialized factor calculation classes.
    """

    @abstractmethod
    def _create_factor_calculator(self, **kwargs):
        """Create and return the factor calculator instance."""
        pass

    def _calculate_raw_signal(
        self,
        inst_data: pl.DataFrame,
        market_data: Optional[Any],
        as_of: date,
    ) -> float:
        """Delegate to factor calculator."""
        return self.factor_calculator.calculate(inst_data)
```

**Simplified implementations:**
```python
# In Signals/SectorRotation/SectorMomentumSignal.py

class SectorMomentumSignal(SectorSignalWrapper):
    def __init__(self, lookback_months: int = 7, **kwargs):
        super().__init__(name="sector_momentum", **kwargs)
        self.lookback_months = lookback_months
        self.factor_calculator = self._create_factor_calculator()

    def _create_factor_calculator(self):
        return MomentumFactor(
            lookback_months=self.lookback_months,
            exclusion_pct=0.10,
            trading_days_per_month=21
        )

    # That's it! Base class handles the rest
```

#### Benefits
- **Code reduction**: ~30-40 lines per signal
- **Pattern clarity**: Wrapper pattern made explicit
- **Extensibility**: Easy to add new sector signals

---

### 6. Validation Utilities - MEDIUM IMPACT

#### Current State
Validation logic found in 20+ files with common patterns:
- DataFrame schema validation
- Type checking
- Range validation
- Required field checks

#### Proposed Solution

**Create validation utility module:**
```python
# In utils/validation.py

import polars as pl
from typing import List, Dict, Any, Optional


class DataFrameValidator:
    """Validates DataFrame schemas and content."""

    @staticmethod
    def validate_schema(
        df: pl.DataFrame,
        required_columns: List[str],
        optional_columns: List[str] = None,
        strict: bool = False,
    ) -> None:
        """
        Validate DataFrame has required columns.

        Args:
            df: DataFrame to validate
            required_columns: Columns that must be present
            optional_columns: Columns that may be present
            strict: If True, only required+optional columns allowed

        Raises:
            ValueError: If validation fails
        """
        missing = set(required_columns) - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        if strict and optional_columns is not None:
            allowed = set(required_columns) | set(optional_columns)
            extra = set(df.columns) - allowed
            if extra:
                raise ValueError(f"Unexpected columns: {extra}")

    @staticmethod
    def validate_types(
        df: pl.DataFrame,
        type_map: Dict[str, type],
    ) -> None:
        """
        Validate column types.

        Args:
            df: DataFrame to validate
            type_map: Dict mapping column names to expected polars types

        Raises:
            ValueError: If types don't match
        """
        for col, expected_type in type_map.items():
            if col in df.columns:
                actual_type = df[col].dtype
                if actual_type != expected_type:
                    raise ValueError(
                        f"Column '{col}' has type {actual_type}, "
                        f"expected {expected_type}"
                    )

    @staticmethod
    def validate_range(
        series: pl.Series,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        allow_nan: bool = True,
    ) -> None:
        """
        Validate series values are in range.

        Args:
            series: Series to validate
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            allow_nan: If True, NaN values are allowed

        Raises:
            ValueError: If values out of range
        """
        if not allow_nan and series.is_nan().any():
            raise ValueError(f"Series '{series.name}' contains NaN values")

        valid_values = series.drop_nulls()

        if min_val is not None:
            if (valid_values < min_val).any():
                raise ValueError(
                    f"Series '{series.name}' has values below {min_val}"
                )

        if max_val is not None:
            if (valid_values > max_val).any():
                raise ValueError(
                    f"Series '{series.name}' has values above {max_val}"
                )


class MatrixValidator:
    """Validates matrix properties (covariance, correlation, etc.)."""

    @staticmethod
    def validate_square(matrix: np.ndarray) -> None:
        """Validate matrix is square."""
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise ValueError(
                f"Matrix must be square, got shape {matrix.shape}"
            )

    @staticmethod
    def validate_symmetric(matrix: np.ndarray, tol: float = 1e-10) -> None:
        """Validate matrix is symmetric."""
        if not np.allclose(matrix, matrix.T, atol=tol):
            max_diff = np.max(np.abs(matrix - matrix.T))
            raise ValueError(
                f"Matrix must be symmetric. Max asymmetry: {max_diff:.2e}"
            )

    @staticmethod
    def validate_positive_definite(
        matrix: np.ndarray,
        tol: float = 1e-10
    ) -> None:
        """Validate matrix is positive definite."""
        eigenvalues = np.linalg.eigvalsh(matrix)
        min_eigenvalue = np.min(eigenvalues)
        if min_eigenvalue < -tol:
            raise ValueError(
                f"Matrix must be positive definite. "
                f"Minimum eigenvalue: {min_eigenvalue:.2e}"
            )
```

**Usage in risk models:**
```python
# In Risk/Base/BaseCovarianceEstimator.py

from utils.validation import MatrixValidator

class BaseCovarianceEstimator(ABC):
    def _validate_covariance_matrix(self, cov_matrix: np.ndarray) -> None:
        """Validate covariance matrix properties."""
        MatrixValidator.validate_square(cov_matrix)
        MatrixValidator.validate_symmetric(cov_matrix)
        MatrixValidator.validate_positive_definite(cov_matrix)
```

#### Benefits
- **Code reduction**: ~100+ lines across 20+ files
- **Consistency**: All validation uses same utilities
- **Testability**: Validation logic tested once
- **Error messages**: Standardized, helpful error messages

---

### 7. Common HTTP/API Patterns - LOW-MEDIUM IMPACT

#### Current State
Multiple fetchers implement similar patterns:
- Retry logic
- Rate limiting
- Response parsing
- Cache handling

#### Proposed Solution

**Create HTTP utilities:**
```python
# In utils/http.py

import httpx
from typing import Optional, Dict, Any, Callable
import time


class RetryableHTTPClient:
    """HTTP client with retry and rate limiting."""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        rate_limit_delay: float = 0.0,
    ):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.rate_limit_delay = rate_limit_delay
        self._last_request_time = 0.0

    def get_with_retry(
        self,
        url: str,
        client: httpx.Client,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """
        GET request with retry logic.

        Args:
            url: URL to fetch
            client: httpx.Client instance
            headers: Request headers
            params: Query parameters

        Returns:
            Response

        Raises:
            httpx.HTTPError: If all retries fail
        """
        # Rate limiting
        if self.rate_limit_delay > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit_delay:
                time.sleep(self.rate_limit_delay - elapsed)

        # Retry logic
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
                self._last_request_time = time.time()
                return response
            except httpx.HTTPError as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    delay = self.backoff_factor * (2 ** attempt)
                    time.sleep(delay)

        raise last_exception
```

---

## Implementation Strategy

### Overall Approach
Follow **Test-Driven Refactoring**:
1. Write tests for current behavior
2. Implement abstraction
3. Migrate one module at a time
4. Verify tests still pass
5. Remove duplicated code

### Prioritization

**Phase 1: High Impact, Low Risk** (Weeks 1-2)
1. MDP Fetcher consolidation
2. Signal abstraction (calculate, standardize, history)
3. Risk model validation

**Phase 2: Medium Impact** (Weeks 3-4)
4. Adapter error handling
5. Validation utilities
6. Risk model shrinkage base class

**Phase 3: Low Impact, Polish** (Week 5)
7. Sector signal wrapper
8. HTTP utilities
9. Documentation updates

### Success Metrics
- **All 582 tests pass** after each phase
- **Code coverage maintained** or improved
- **LOC reduction**: 1,500-3,000 lines
- **Duplication reduction**: Measured by copy-paste detector tools
- **Developer velocity**: Time to add new signal/risk model reduces

---

## Risks and Mitigation

### Risk 1: Breaking Existing Functionality
**Likelihood**: Medium
**Impact**: High
**Mitigation**:
- TDD approach: tests first, then refactor
- One module at a time
- Keep old code until new code proven
- Extensive integration testing

### Risk 2: Abstraction Too Generic
**Likelihood**: Low-Medium
**Impact**: Medium
**Mitigation**:
- Design from concrete examples (3+ implementations)
- Keep abstractions overridable
- Don't force-fit edge cases
- Allow concrete classes to override

### Risk 3: Performance Regression
**Likelihood**: Low
**Impact**: Low
**Mitigation**:
- Benchmark before/after
- Avoid unnecessary abstraction layers
- Profile hot paths
- Optimize common cases

### Risk 4: Incomplete Migration
**Likelihood**: Medium
**Impact**: Medium
**Mitigation**:
- Clear phase boundaries
- Each phase is independently valuable
- Track migration status
- Deprecation warnings for old patterns

---

## Measurement Plan

### Before Metrics (Baseline)
```bash
# Code metrics
find . -name "*.py" -exec wc -l {} + | tail -1
# Duplication detection
pylint --disable=all --enable=duplicate-code .
# Test coverage
pytest --cov=. --cov-report=term-missing
```

**Current baseline:**
- Total LOC: 91,834
- Production LOC: ~59,461
- Test LOC: 32,373
- Test coverage: ~582 tests (need coverage %)

### After Metrics (Target)
- Total LOC: ~89,000-90,300 (2-3k reduction)
- Production LOC: ~57,000-58,000
- Test LOC: 32,000+ (may reduce slightly, but not goal)
- Duplicate code blocks: <10 (currently many)
- All tests passing: 582+

### Tracking Progress
Create spreadsheet tracking:
- Lines removed per abstraction
- Tests passing/failing
- Coverage before/after
- Developer feedback (subjective)

---

## Conclusion

This abstraction plan addresses systematic code duplication across the ARBS codebase. By creating well-designed base classes, mixins, and utilities, we can:

1. **Reduce code**: 1,500-3,000 lines (2-4%)
2. **Improve maintainability**: Fix bugs once, apply everywhere
3. **Increase consistency**: All modules follow same patterns
4. **Enhance extensibility**: New implementations easier to add
5. **Better testability**: Test common functionality in one place

The plan is **incremental** (phase by phase), **low-risk** (TDD approach), and **high-value** (targets biggest duplications first).

**Next steps:**
1. Get approval from Peter
2. Create tracking spreadsheet
3. Begin Phase 1: MDP Fetcher consolidation
4. Measure and iterate

---

## Appendix: Code Metrics

### Module Breakdown
| Module | Files | Lines | Duplication Found |
|--------|-------|-------|-------------------|
| Signals | 27 | 5,929 | High (450-600 lines) |
| Risk | 30 | 5,325 | Medium (50-100 lines) |
| MDP | 47 | ~15,000+ | High (100+ lines) |
| Adapter | 5 | 734 | Low-Medium (50-75 lines) |
| Backtest | 4 | ~500 | Low |
| Optimizer | ~10 | ~1,500 | Low |
| Query | ~50 | ~10,000 | Unknown |
| Tests | 111 | 32,373 | N/A (tests) |

### Duplication Hotspots
1. **MDP/IRSwaps/CME_NY_EOD_LIVE/*/BaseFetcher.py** - 100% duplicate (2 files)
2. **Signals/Futures/*Signal.py** - calculate(), _standardize_signals(), _update_history()
3. **Risk/Covariance/***Shrinkage.py** - validation, sample covariance
4. **Adapter/*Adapter.py** - error handling, empty DataFrame creation

### Test Coverage Gaps
(To be measured with pytest --cov)
- Current: 582 tests written
- Coverage %: TBD
- Target: >90% for abstracted base classes
