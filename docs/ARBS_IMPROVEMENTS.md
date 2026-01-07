# ARBS Codebase Improvement Notes
## Comprehensive Analysis & Recommendations

**Project**: Awesome Rates Backtesting System (ARBS)  
**Current Scale**: ~7,686 lines of Python | 121 files | 1,216+ functions  
**Analysis Date**: 2025-11-10  

---

## 1. ARCHITECTURE IMPROVEMENTS

### 1.1 Separation of Concerns - Current Strengths & Gaps

**Current State (Excellent)**:
- Clean adapter pattern isolates product-specific logic
- BaseQuery abstraction keeps engines product-agnostic
- MDP abstraction enables multi-source data providers

**Gaps Identified**:

#### 1.1.1 Tight Coupling in Query Execution Path
**Issue**: Query resolution happens across multiple modules with implicit state passing

```python
# Current flow (spread across files):
# BT/query_engine.py → BaseQuery → ProductAdapter → StructureMap → _IRSwapGenericCurve
# Problem: Difficult to trace data flow and inject custom logic
```

**Recommendation**: Introduce a QueryResolutionContext

```python
# Query/Base/resolution_context.py
@dataclass
class QueryResolutionContext:
    """Centralizes query resolution state and dependencies"""
    query: BaseQuery
    timestamp: datetime.datetime
    pricer: _GenericPricer
    adapter: ProductAdapter
    resolved_package: Optional[List[_GenericPricable]] = None
    computed_values: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def resolve_package(self) -> Tuple[List[_GenericPricable], List[float]]:
        if self.resolved_package is None:
            pkg, wts = self.query.resolve_package(pricer_or_curve=self.pricer)
            self.resolved_package = pkg
        return self.resolved_package, self._compute_weights()
    
    def compute_value(self, value_id: str) -> float:
        if value_id not in self.computed_values:
            vmap = self.query.build_value_map(...)
            self.computed_values[value_id] = vmap.apply(value_id)
        return self.computed_values[value_id]
```

**Benefits**:
- Single point for debug logging and introspection
- Enables middleware pattern for preprocessing/validation
- Easier testing and mocking

#### 1.1.2 Portfolio & Position Management Consolidation

**Current**: Separate QueryPortfolio and Portfolio classes with overlapping logic

**Recommendation**: Unified PortfolioBase with product-specific subclasses

```python
# BT/portfolio_base.py
class PortfolioBase(ABC):
    def __init__(self):
        self.positions: List[Position] = []
        self.audit_log: List[AuditEntry] = []
        self.metadata: Dict[str, Any] = {}
    
    @abstractmethod
    def add_position(self, position: Position) -> None: ...
    
    @abstractmethod
    def mark_to_market(self, pricer) -> float: ...
    
    def audit(self, action: str, **kwargs):
        """Centralized audit logging"""
        self.audit_log.append(AuditEntry(
            timestamp=datetime.datetime.now(),
            action=action,
            details=kwargs
        ))

# BT/query_portfolio.py
class QueryPortfolio(PortfolioBase):
    def add_position(self, pos: ResolvedQueryPosition):
        super().add_position(pos)
        self.audit("position_added", query=pos.source_query.signature())
```

#### 1.1.3 Error Handling Abstraction

**Current State**: Error handling scattered across modules, silently caught in generic_engine.py:73

```python
# BT/generic_engine.py line 71-74
try:
    total += float(pricer.npv(instr))
except Exception:
    continue  # SILENT FAILURE!
```

**Recommendation**: Introduce ErrorHandler strategy

```python
# BT/error_handling.py
from enum import Enum
from abc import ABC, abstractmethod

class ErrorStrategy(Enum):
    RAISE = "raise"           # Fail immediately
    LOG_SKIP = "log_skip"     # Log and continue
    RETRY = "retry"           # Retry with backoff
    FALLBACK = "fallback"     # Use fallback value
    CUSTOM = "custom"         # Custom handler

class ErrorHandler(ABC):
    @abstractmethod
    def handle(self, error: Exception, context: Dict[str, Any]) -> Any:
        raise NotImplementedError

class BacktestErrorHandler(ErrorHandler):
    def __init__(self, strategy: ErrorStrategy = ErrorStrategy.LOG_SKIP):
        self.strategy = strategy
        self.errors: List[ErrorRecord] = []
    
    def handle(self, error: Exception, context: Dict[str, Any]) -> Any:
        record = ErrorRecord(
            timestamp=datetime.datetime.now(),
            error=error,
            context=context,
            strategy=self.strategy
        )
        self.errors.append(record)
        
        if self.strategy == ErrorStrategy.RAISE:
            raise error
        elif self.strategy == ErrorStrategy.LOG_SKIP:
            logger.warning(f"Skipping: {error}", extra=context)
            return context.get("fallback_value", 0.0)
        # ... other strategies
    
    def get_error_report(self) -> pd.DataFrame:
        """Post-backtest error analysis"""
        return pd.DataFrame([asdict(e) for e in self.errors])
```

---

### 1.2 Design Patterns & Opportunities

#### 1.2.1 Chain of Responsibility for Query Processing

**Recommendation**: Add QueryPipeline for sequential processing

```python
# BT/query_pipeline.py
from abc import ABC, abstractmethod
from typing import List

class QueryProcessor(ABC):
    """Chain-of-responsibility for query transformation"""
    @abstractmethod
    def process(self, context: QueryResolutionContext) -> QueryResolutionContext:
        pass
    
    def next(self, processor: "QueryProcessor") -> "QueryProcessor":
        self._next = processor
        return processor

class ValidateQueryProcessor(QueryProcessor):
    def process(self, ctx: QueryResolutionContext) -> QueryResolutionContext:
        query = ctx.query
        if not query.market_request or "curve_name" not in query.market_request:
            raise ValueError("market_request must contain 'curve_name'")
        ctx.metadata["validated"] = True
        return ctx

class CacheCheckProcessor(QueryProcessor):
    def process(self, ctx: QueryResolutionContext) -> QueryResolutionContext:
        key = ctx.query.signature()
        if key in self._cache:
            ctx.resolved_package = self._cache[key]["package"]
            ctx.computed_values = self._cache[key]["values"]
            ctx.metadata["cache_hit"] = True
        return ctx

class StructureResolveProcessor(QueryProcessor):
    def process(self, ctx: QueryResolutionContext) -> QueryResolutionContext:
        pkg, wts = ctx.resolve_package()
        ctx.metadata["structure_resolved"] = True
        return ctx

# Usage in backtest
def create_query_pipeline() -> QueryProcessor:
    validate = ValidateQueryProcessor()
    cache_check = CacheCheckProcessor()
    resolve = StructureResolveProcessor()
    
    validate.next(cache_check).next(resolve)
    return validate

pipeline = create_query_pipeline()
context = QueryResolutionContext(query, timestamp, pricer, adapter)
context = pipeline.process(context)
```

#### 1.2.2 Strategy Pattern for Risk Calculation

**Current**: Risk function is a simple callable, hard to extend

```python
# Current: BT/query_engine.py
RiskFn = Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]
self.risk_fn: RiskFn = lambda p, g: {}
```

**Recommendation**: Strategy pattern with composition

```python
# BT/risk_strategies.py
from abc import ABC, abstractmethod

class RiskMetric(ABC):
    name: str
    
    @abstractmethod
    def compute(self, portfolio: QueryPortfolio, pricer_getter) -> float:
        pass

class DV01RiskMetric(RiskMetric):
    name = "dv01"
    def compute(self, portfolio, pricer_getter):
        total_dv01 = 0.0
        for pos in portfolio.iter_positions():
            pricer = pricer_getter(pos.source_query)
            total_dv01 += sum(pricer.dv01(p) for p in pos.package)
        return total_dv01

class NotionalRiskMetric(RiskMetric):
    name = "notional"
    def compute(self, portfolio, pricer_getter):
        total_notional = 0.0
        for pos in portfolio.iter_positions():
            total_notional += sum(pos.weights)
        return total_notional

class CompositeRiskStrategy:
    def __init__(self, metrics: List[RiskMetric]):
        self.metrics = {m.name: m for m in metrics}
    
    def compute_all(self, portfolio, pricer_getter) -> Dict[str, float]:
        return {
            name: metric.compute(portfolio, pricer_getter)
            for name, metric in self.metrics.items()
        }

# In QueryDrivenBacktest
self.risk_strategy = CompositeRiskStrategy([
    DV01RiskMetric(),
    NotionalRiskMetric(),
])

def get_strategy_risk(self, name: str) -> float:
    risks = self.risk_strategy.compute_all(self.portfolio, self._pricer_for_query)
    return float(risks.get(name, 0.0))
```

#### 1.2.3 Builder Pattern for Complex Queries

**Current**: Direct query construction is error-prone

```python
# Current: Lots of boilerplate
q = IRSwapQuery(
    structure=IRSwapStructure.FLY,
    value=IRSwapValue.PV01,
    curve="USD-SOFR-1D",
    structure_kwargs={
        "front_tenor": "2Y",
        "belly_tenor": "5Y",
        "back_tenor": "10Y",
        "bpv": 1_000_000,
        "pay_fixed": [True, False, True]
    }
)
```

**Recommendation**: Builder pattern

```python
# Query/IRSwaps/builder.py
class IRSwapQueryBuilder:
    def __init__(self, curve: str):
        self.curve = curve
        self.structure = IRSwapStructure.OUTRIGHT
        self.value = IRSwapValue.RATE
        self.structure_kwargs: Dict[str, Any] = {}
    
    def fly(self, front: str, belly: str, back: str) -> "IRSwapQueryBuilder":
        self.structure = IRSwapStructure.FLY
        self.structure_kwargs.update({
            "front_tenor": front,
            "belly_tenor": belly,
            "back_tenor": back
        })
        return self
    
    def with_size(self, bpv: float) -> "IRSwapQueryBuilder":
        self.structure_kwargs["bpv"] = bpv
        return self
    
    def value_pv01(self) -> "IRSwapQueryBuilder":
        self.value = IRSwapValue.PV01
        return self
    
    def build(self) -> IRSwapQuery:
        return IRSwapQuery(
            structure=self.structure,
            value=self.value,
            curve=self.curve,
            structure_kwargs=self.structure_kwargs
        )

# Usage
q = (IRSwapQueryBuilder("USD-SOFR-1D")
     .fly("2Y", "5Y", "10Y")
     .with_size(1_000_000)
     .value_pv01()
     .build())
```

### 1.3 Modularity Enhancements

#### 1.3.1 Plugin System for Products

**Current**: Products hardcoded, registration happens at import

```python
# Query/IRSwaps/adapter.py
register_product("IRS", IRSProductAdapter)

# Problem: Must import all product modules upfront
import Query.IRSwaps.adapter  # noqa: F401
```

**Recommendation**: Plugin discovery system

```python
# Query/Base/plugin_registry.py
import importlib
from pathlib import Path
from typing import Dict, Type

class ProductPluginRegistry:
    _registry: Dict[str, Type[ProductAdapter]] = {}
    _discovered = False
    
    @classmethod
    def discover_plugins(cls, plugin_dir: Path = None):
        """Auto-discover and register product adapters"""
        if cls._discovered:
            return
        
        plugin_dir = plugin_dir or Path(__file__).parent.parent
        
        for product_dir in plugin_dir.iterdir():
            if not product_dir.is_dir() or product_dir.name.startswith("_"):
                continue
            
            adapter_file = product_dir / "adapter.py"
            if adapter_file.exists():
                module_name = f"Query.{product_dir.name}.adapter"
                try:
                    importlib.import_module(module_name)
                    logger.info(f"Loaded product plugin: {product_dir.name}")
                except ImportError as e:
                    logger.warning(f"Failed to load {module_name}: {e}")
        
        cls._discovered = True
    
    @classmethod
    def register(cls, name: str, adapter: Type[ProductAdapter]):
        cls._registry[name] = adapter
    
    @classmethod
    def get(cls, name: str) -> Type[ProductAdapter]:
        cls.discover_plugins()
        return cls._registry[name]

# Usage
ProductPluginRegistry.discover_plugins()
adapter = ProductPluginRegistry.get("IRS")
```

#### 1.3.2 Separate Concerns: Data Fetching vs. Curve Building

**Current**: IRSwapsMDP.get_data() mixes fetching, validation, and building

```python
# MDP/IRSwaps/IRSwapsMDP.py:42-55
# Multiple responsibilities in one method
```

**Recommendation**: Decompose into collaborating classes

```python
# MDP/IRSwaps/data_fetcher.py
class RateDataFetcher(ABC):
    @abstractmethod
    def fetch(self, curve_name: str, timestamp) -> Dict[str, float]:
        """Return pillar rates"""
        pass

class CMERatesFetcher(RateDataFetcher):
    def fetch(self, curve_name: str, timestamp) -> Dict[str, float]:
        # CME-specific fetching
        pass

# MDP/IRSwaps/curve_builder.py
class CurveBuilder(ABC):
    @abstractmethod
    def build(self, rates: Dict[str, float], metadata: Dict) -> _IRSwapGenericCurve:
        pass

class QLCurveBuilder(CurveBuilder):
    def build(self, rates: Dict[str, float], metadata: Dict) -> _IRSwapGenericCurve:
        # Build QL curve from rates
        pass

# MDP/IRSwaps/IRSwapsMDP.py (refactored)
class IRSwapsMDP(MarketDataProvider):
    def __init__(self, fetcher: RateDataFetcher, builder: CurveBuilder):
        self.fetcher = fetcher
        self.builder = builder
    
    def get_pricer(self, request: dict) -> _IRSwapGenericCurve:
        curve_name = request.pop("curve_name")
        timestamp = request.pop("timestamp")
        
        # Clean separation of concerns
        rates = self.fetcher.fetch(curve_name, timestamp)
        curve = self.builder.build(rates, {"curve_name": curve_name})
        return curve
```

---

## 2. CODE QUALITY IMPROVEMENTS

### 2.1 Type Hints Coverage

**Current State**:
- 37 type hints in base Query files
- 29 functions with return type annotations
- Heavy use of `Any` (needs reduction)

**Issues Found**:

1. **BaseQuery returns `Union` without specificity**
   ```python
   # BaseQuery.py:141
   def return_query(self) -> Union["BaseQuery", List["BaseQuery"]]: ...
   # Problem: Callers must handle both types
   ```

2. **Protocol usage incomplete**
   ```python
   # BT/query_actions.py:10
   class QAction(Protocol):
       def __call__(self, *, now, backtest, info: Dict[Type, Any]) -> List[QueryOrder]: ...
       # Missing 'risk: Optional[str]' in __call__
   ```

**Recommendations**:

#### 2.1.1 Improve Generic Type Safety

```python
# Query/Base/types.py
from typing import TypeVar, Generic, Callable, List, Tuple
from typing_extensions import Protocol

PricableT = TypeVar("PricableT")
ValueT = TypeVar("ValueT", bound=float)
StructureT = TypeVar("StructureT", bound=Enum)

class GenericQuery(ABC, Generic[StructureT, ValueT]):
    structure_id: StructureT
    
    @abstractmethod
    def resolve_package(self) -> Tuple[List[PricableT], List[float]]:
        pass

# Usage
class IRSwapQuery(GenericQuery[IRSwapStructure, float]):
    structure: IRSwapStructure
    # Better type safety
```

#### 2.1.2 Use TypedDict for Configuration

```python
# BT/types.py
from typing import TypedDict

class BacktestConfig(TypedDict):
    """Type-safe backtest configuration"""
    time_grid: TimeGrid
    mdp: MarketDataProvider
    strategy: QueryStrategy
    show_progress: bool
    progress_desc: str
    error_handler: Optional[ErrorHandler]

class QueryDrivenBacktest:
    def __init__(self, config: BacktestConfig):
        self.time_grid = config["time_grid"]
        self.mdp = config["mdp"]
        # ... (with IDE autocomplete support)
```

#### 2.1.3 Complete Protocol Definitions

```python
# BT/protocols.py
from typing import Protocol, List, Dict, Any, Tuple, Type
import datetime

class BacktestLike(Protocol):
    """Protocol for backtest-like objects (for trigger injection)"""
    def get_strategy_risk(self, name: str) -> float: ...
    def trade_count_since(self, start: datetime.datetime, end: datetime.datetime) -> int: ...
    def window(self, fetch_fn, now: datetime.datetime, lookback: int) -> List[Any]: ...
    def mark_to_market(self, now: datetime.datetime) -> float: ...

class ActionLike(Protocol):
    """Protocol for actions"""
    risk: Optional[str]
    def __call__(self, *, now: datetime.datetime, backtest: BacktestLike, 
                 info: Dict[Type, Any]) -> List[Any]: ...
```

#### 2.1.4 Better Type Annotations for Value Maps

```python
# Query/Base/BaseValue.py (improved)
from typing import Type, TypeVar, Generic, Dict, Callable, Any, overload

E = TypeVar("E", bound=Enum)
R = TypeVar("R")

class BaseValueFunctionMap(Generic[E, R]):
    def __init__(
        self,
        value_enum: Type[E],
        *,
        package: List[Any],
        risk_weights: List[float],
        curve: Any,
        **extra_kwargs: Any
    ):
        self._value_enum = value_enum
        self.common_kwargs: Dict[str, Any] = {
            "package": package,
            "risk_weights": risk_weights,
            "curve": curve,
            **extra_kwargs,
        }
    
    @overload
    def apply(self, value: E) -> R: ...
    
    @overload
    def apply(self, value: E, **kwargs: Any) -> R: ...
    
    def apply(self, value: E, **kwargs: Any) -> R:
        """Apply value function with proper typing"""
        if value not in self._map:
            raise KeyError(f"Value {value} not supported. Available: {list(self._map.keys())}")
        func = self._map[value]
        merged = {**self.common_kwargs, **kwargs}
        return func(**merged)
```

### 2.2 Documentation Completeness

**Current State**:
- Excellent README and architecture documentation
- Missing: Inline code documentation, docstring standards
- Module-level docstrings incomplete

**Issues**:

```python
# BT/query_engine.py:46-53 - NO DOCSTRING
def _pricer_for_request(self, req: Dict[str, Any]) -> Any:
    sig = repr(sorted(req.items()))
    hit = self._cache.get(("pricer", sig))
    if hit is not None:
        return hit
    pricer = self.mdp.get_pricer(req)
    self._cache[("pricer", sig)] = pricer
    return pricer
```

**Recommendations**:

#### 2.2.1 Standardize Docstring Format (Google Style)

```python
# BT/query_engine.py
class QueryDrivenBacktest:
    """Query-driven backtesting engine for product-agnostic instruments.
    
    This engine executes strategies that produce queries (e.g., "5Y IRS on USD-SOFR").
    At each timestep:
      1. Strategy evaluates and produces orders
      2. Queries are resolved to concrete packages using product adapters
      3. Portfolio is marked-to-market using resolved values
      4. Unwinds realize P&L
    
    Attributes:
        time_grid: TimeGrid specifying simulation dates
        mdp: Market Data Provider for curve/pricer resolution
        strategy: QueryStrategy producing orders
        portfolio: Active positions
        mtm_history: Mark-to-market by timestamp
        realized_pnl_history: Realized P&L by timestamp
    
    Example:
        >>> grid = TimeGrid([datetime(2025, 1, d) for d in range(1, 32)])
        >>> mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
        >>> strategy = QueryStrategy(name="Demo", triggers=[...])
        >>> bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
        >>> bt.run()
        >>> print(bt.mtm_history)
    """
    
    def _pricer_for_request(self, req: Dict[str, Any]) -> _GenericPricer:
        """Get or fetch pricer for a market data request.
        
        Uses in-memory cache keyed by request signature (MD5 of sorted items).
        Falls back to MDP if not cached.
        
        Args:
            req: Request dict (e.g., {"curve_name": "USD-SOFR-1D", "timestamp": date(2025,1,1)})
        
        Returns:
            _GenericPricer: Pricer/curve object with valuation methods
        
        Raises:
            RuntimeError: If MDP.get_pricer fails
        
        Note:
            Cache is ephemeral (session-only). For persistence, use ZODB caching.
        """
        sig = repr(sorted(req.items()))
        hit = self._cache.get(("pricer", sig))
        if hit is not None:
            return hit
        
        pricer = self.mdp.get_pricer(req)
        self._cache[("pricer", sig)] = pricer
        return pricer
```

#### 2.2.2 Add Module-Level Documentation

```python
# BT/query_engine.py (top)
"""Query-driven backtesting orchestration.

This module contains the core QueryDrivenBacktest engine, which:
  - Manages simulation time grid
  - Coordinates strategy → orders → position updates → MTM
  - Bridges queries to product adapters
  - Tracks realized and mark-to-market P&L

Key Classes:
  - QueryDrivenBacktest: Main engine
  - QueryResolutionContext: Encapsulates query processing state

Design Notes:
  - Queries are resolved at trade time (deterministic package)
  - MTM uses current pricer (per-timestep)
  - Unwinds trigger P&L realization with optional fees
  - Audit logging via portfolio.orders_log and trades_log

Example:
    See module docstring in Query/Base/BaseQuery.py for end-to-end workflow.
"""
```

#### 2.2.3 Auto-Generated Documentation

Add to requirements-dev.txt and create docs configuration:

```bash
# requirements-dev.txt
sphinx>=7.0
sphinx-rtd-theme>=1.3
sphinx-autodoc-typehints>=2.0  # Better type hint rendering
sphinx-markdown-tables>=0.0.17
myst-parser>=2.0  # Support .md in Sphinx
```

```python
# docs/conf.py
project = "ARBS"
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",  # Auto docstring type hints
    "myst_parser",  # Markdown support
]

# Auto-doc configuration
autodoc_typehints = "description"
autodoc_type_aliases = {
    "RiskFn": "Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]",
}

# Document private functions in API reference
autodoc_member_order = "groupwise"
```

### 2.3 Error Handling Patterns

**Current Issues**:

1. **Silent failures** (generic_engine.py:71-74)
   ```python
   try:
       total += float(pricer.npv(instr))
   except Exception:
       continue  # Silently skipped!
   ```

2. **Loose validation** (IRSwapsMDP.py:52-53)
   ```python
   if not curve_name or not timestamp:
       raise ValueError("Request must contain 'curve_name' and 'timestamp'.")
   # But missing: what are valid curve names? Accepted timestamp formats?
   ```

3. **No structured error context** (adapter.py:58-61)
   ```python
   except KeyError as e:
       raise KeyError(f"No ProductAdapter registered for product '{product}'.") from e
       # Lost: What products ARE registered? Where to add new ones?
   ```

4. **Inconsistent exception types**
   ```python
   # MDP raises RuntimeError, ValueError, KeyError inconsistently
   # IRSwapQuery raises AssertionError for validation
   ```

**Recommendations**:

#### 2.3.1 Custom Exception Hierarchy

```python
# BT/exceptions.py
"""Exception hierarchy for ARBS backtesting engine."""

class ARBSError(Exception):
    """Base exception for all ARBS errors"""
    pass

class BacktestError(ARBSError):
    """Backtest execution errors"""
    pass

class QueryError(ARBSError):
    """Query resolution errors"""
    pass

class MDPError(ARBSError):
    """Market Data Provider errors"""
    pass

class CurveError(MDPError):
    """Curve construction/resolution errors"""
    pass

class CacheError(ARBSError):
    """Caching system errors"""
    pass

class ValidationError(ARBSError):
    """Input validation errors"""
    pass

# Specific subclasses for better catching
class InvalidCurveName(CurveError):
    """Raised when curve name not found in definitions"""
    def __init__(self, curve_name: str, available: List[str]):
        self.curve_name = curve_name
        self.available = available
        msg = f"Unknown curve '{curve_name}'. Available: {available}"
        super().__init__(msg)

class MissingPricerError(MDPError):
    """Raised when pricer cannot be resolved"""
    def __init__(self, request: Dict[str, Any], reason: str):
        self.request = request
        self.reason = reason
        super().__init__(f"Pricer resolution failed: {reason}\nRequest: {request}")
```

#### 2.3.2 Validation with Better Errors

```python
# Query/Base/validation.py
from typing import List, Dict, Any, Callable
import inspect

class QueryValidator:
    """Validates queries before execution"""
    
    @staticmethod
    def validate_market_request(query: BaseQuery) -> List[str]:
        """Validate market_request has required fields.
        
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        req = query.market_request or {}
        
        if "curve_name" not in req:
            errors.append("'curve_name' missing from market_request")
        
        time_key = query.mdp_time_key
        if time_key not in req:
            errors.append(f"'{time_key}' missing from market_request")
        
        return errors
    
    @staticmethod
    def validate_structure_kwargs(
        query: BaseQuery,
        adapter: ProductAdapter
    ) -> List[str]:
        """Validate structure kwargs for product adapter"""
        errors = []
        
        # Get adapter's signature
        struct_map = adapter.build_structure_map(pricer_or_curve=None)
        supported_structures = {s.value for s in adapter._structure_enum}
        
        if query.structure_id not in supported_structures:
            errors.append(
                f"Structure '{query.structure_id}' not in {list(supported_structures)}"
            )
        
        return errors
    
    @staticmethod
    def validate_all(query: BaseQuery, adapter: ProductAdapter) -> None:
        """Validate query; raise ValidationError if issues"""
        all_errors = []
        all_errors.extend(QueryValidator.validate_market_request(query))
        all_errors.extend(QueryValidator.validate_structure_kwargs(query, adapter))
        
        if all_errors:
            raise ValidationError(
                f"Query validation failed:\n" + "\n  ".join(all_errors)
            )

# Usage in backtest
def resolve_query(query: BaseQuery, pricer, adapter) -> Tuple[List[_GenericPricable], List[float]]:
    QueryValidator.validate_all(query, adapter)  # Fail fast
    return query.resolve_package(pricer_or_curve=pricer)
```

#### 2.3.3 Context Manager for Error Recovery

```python
# BT/error_recovery.py
import contextlib
from typing import Optional, Callable, Any

class BacktestRecoveryContext:
    """Manages error recovery during backtest"""
    
    @contextlib.contextmanager
    def handle_valuation_error(
        self,
        position_id: str,
        fallback_value: float = 0.0
    ):
        """Wrap valuation to handle errors gracefully"""
        try:
            yield
        except Exception as e:
            self.record_error(
                position_id=position_id,
                error=e,
                fallback_value=fallback_value
            )
            # Return fallback but don't crash

# Usage
recovery_ctx = BacktestRecoveryContext()

for pos in portfolio.iter_positions():
    with recovery_ctx.handle_valuation_error(pos.id, fallback_value=0.0):
        mtm_value = pricer.npv(pos.package[0])
```

### 2.4 Testing Infrastructure

**Current State**:
- No test files found in repo
- requirements-dev.txt includes pytest, pytest-cov, pytest-asyncio, pytest-mock
- No CI/CD (.github directory)

**Critical Gap**: Zero test infrastructure despite complex backtesting logic

**Recommendations**:

#### 2.4.1 Test Structure

```
tests/
├── conftest.py                 # Fixtures
├── unit/
│   ├── test_base_query.py
│   ├── test_query_engine.py
│   ├── test_product_adapter.py
│   ├── test_triggers.py
│   └── test_error_handling.py
├── integration/
│   ├── test_query_backtest_flow.py
│   ├── test_mdp_integration.py
│   └── test_caching.py
├── fixtures/
│   ├── mock_pricer.py
│   ├── mock_mdp.py
│   └── sample_data.py
└── benchmarks/
    ├── test_backtest_performance.py
    └── test_cache_performance.py
```

#### 2.4.2 Core Unit Tests

```python
# tests/unit/test_query_engine.py
import pytest
import datetime as dt
from unittest.mock import Mock, MagicMock, patch

from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.query_portfolio import ResolvedQueryPosition
from BT.data_handler import TimeGrid
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

@pytest.fixture
def mock_mdp():
    mdp = Mock()
    pricer = Mock()
    pricer.npv = Mock(return_value=1000.0)
    pricer.pv01 = Mock(return_value=100.0)
    mdp.get_pricer = Mock(return_value=pricer)
    return mdp

@pytest.fixture
def sample_query():
    return IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.NPV,
        tenor="5Y",
        curve="USD-SOFR-1D",
    )

def test_query_driven_backtest_initialization(mock_mdp):
    """Test QueryDrivenBacktest initializes without errors"""
    grid = TimeGrid([dt.datetime(2025, 1, d) for d in range(1, 6)])
    strategy = QueryStrategy(name="Test", triggers=[])
    
    bt = QueryDrivenBacktest(
        time_grid=grid,
        mdp=mock_mdp,
        strategy=strategy,
    )
    
    assert bt.portfolio is not None
    assert len(bt.mtm_history) == 0
    assert bt.realized_pnl == 0.0

def test_pricer_caching(mock_mdp):
    """Test that pricers are cached by request signature"""
    grid = TimeGrid([dt.datetime(2025, 1, 1)])
    
    bt = QueryDrivenBacktest(
        time_grid=grid,
        mdp=mock_mdp,
        strategy=QueryStrategy(name="Test", triggers=[]),
    )
    
    req = {"curve_name": "USD-SOFR-1D", "timestamp": dt.date(2025, 1, 1)}
    pricer1 = bt._pricer_for_request(req)
    pricer2 = bt._pricer_for_request(req)
    
    # Should return same object (cached)
    assert pricer1 is pricer2
    
    # Should only call MDP once
    assert mock_mdp.get_pricer.call_count == 1

def test_position_value_calculation(mock_mdp, sample_query):
    """Test position MTM calculation"""
    grid = TimeGrid([dt.datetime(2025, 1, 1)])
    
    bt = QueryDrivenBacktest(
        time_grid=grid,
        mdp=mock_mdp,
        strategy=QueryStrategy(name="Test", triggers=[]),
    )
    
    # Create a position
    pos = ResolvedQueryPosition(
        package=Mock(),
        weights=[1.0],
        opened=dt.datetime(2025, 1, 1),
        source_query=sample_query,
    )
    
    # Mock pricer to return specific value
    pricer = Mock()
    pricer.npv = Mock(return_value=5000.0)
    pricer.resolve_pricable = Mock(side_effect=lambda p, w: p)
    
    # Calculate value
    with patch.object(bt, '_pricer_for_query', return_value=pricer):
        value = bt._position_value(pos, dt.datetime(2025, 1, 1))
    
    assert value == 5000.0

@pytest.mark.parametrize("trigger_fires,expected_trades", [
    (True, 1),
    (False, 0),
])
def test_trigger_execution(trigger_fires, expected_trades):
    """Test that triggers produce expected number of orders"""
    # Implementation...
    pass
```

#### 2.4.3 Integration Tests

```python
# tests/integration/test_query_backtest_flow.py
def test_full_backtest_workflow():
    """End-to-end: Strategy → Orders → Positions → MTM → Unwind"""
    # Build time grid
    dates = [dt.datetime(2025, 1, d) for d in range(1, 31)]
    grid = TimeGrid(dates)
    
    # Create strategy with triggers
    from BT.triggers import DateTrigger, DateTriggerRequirements
    
    trigger = Trigger(
        trigger_requirements=DateTriggerRequirements(dates=[dt.date(2025, 1, 1)]),
        actions=[AddQueryAction(query=sample_query())],
    )
    
    strategy = QueryStrategy(name="Test", triggers=[trigger])
    
    # Create MDP with real fixture data
    mdp = create_fixture_mdp()
    
    # Run backtest
    bt = QueryDrivenBacktest(
        time_grid=grid,
        mdp=mdp,
        strategy=strategy,
    )
    bt.run()
    
    # Assertions
    assert len(bt.mtm_history) == len(dates)
    assert len(bt.portfolio.positions) >= 0
    assert all(isinstance(v, float) for v in bt.mtm_history.values())
```

#### 2.4.4 Golden File Tests (for Determinism)

```python
# tests/integration/test_determinism.py
import json
from pathlib import Path

class GoldenFileTestMixin:
    """Verify backtest results against golden files"""
    
    GOLDEN_DIR = Path(__file__).parent / "golden_files"
    
    def assert_matches_golden(self, name: str, data: Dict[str, Any]):
        """Compare backtest output to golden file"""
        golden_file = self.GOLDEN_DIR / f"{name}.json"
        
        current = json.dumps(data, indent=2, default=str, sort_keys=True)
        
        if not golden_file.exists():
            # First run: create golden file
            golden_file.write_text(current)
            return
        
        golden_content = golden_file.read_text()
        
        if current != golden_content:
            # Write diff for debugging
            diff_file = self.GOLDEN_DIR / f"{name}_diff.json"
            diff_file.write_text(current)
            
            pytest.fail(
                f"Output mismatch for {name}.\n"
                f"Expected: {golden_file}\n"
                f"Got: {diff_file}"
            )

def test_cme_eod_determinism():
    """Verify CME EOD backtest produces consistent results"""
    test = GoldenFileTestMixin()
    
    bt = run_backtest_with_cme_eod()
    
    test.assert_matches_golden(
        "cme_eod_determinism",
        {
            "mtm_history": {str(k): v for k, v in bt.mtm_history.items()},
            "realized_pnl_history": {str(k): v for k, v in bt.realized_pnl_history.items()},
        }
    )
```

#### 2.4.5 CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt -r requirements-dev.txt
      
      - name: Lint with black and flake8
        run: |
          black --check .
          flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
      
      - name: Type check with mypy
        run: |
          mypy BT Query MDP --ignore-missing-imports
      
      - name: Run tests
        run: |
          pytest tests/ -v --cov=. --cov-report=xml
      
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
```

---

## 3. PERFORMANCE OPTIMIZATIONS

### 3.1 Caching Strategies

**Current State**:
- ZODB-backed persistent cache in place
- In-memory cache in QueryDrivenBacktest (line 34)
- Caching module exists but appears underutilized

**Issues**:

1. **Shallow cache key** (query_engine.py:47)
   ```python
   sig = repr(sorted(req.items()))  # String repr of dict
   # Problem: Inefficient, collision-prone
   ```

2. **No cache warming** - Cannot pre-populate with historical data

3. **No cache invalidation strategy** - Stale data possible if curve definitions change

4. **Portfolio MTM recalculated fully each step** (query_engine.py:109-115)
   ```python
   def mark_to_market(self, now: datetime.datetime) -> float:
       total = float(self.realized_pnl)
       for p in self.portfolio.iter_positions():
           total += self._position_value(p, now)  # Full recalc every step
   ```

**Recommendations**:

#### 3.1.1 Better Cache Keying

```python
# BT/caching.py
import hashlib
from typing import Dict, Any

class CacheKey:
    """Structured cache key with hash for efficiency"""
    
    def __init__(self, **kwargs):
        self.data = kwargs
        self._hash = None
    
    def __hash__(self):
        if self._hash is None:
            # Convert to stable format
            items = tuple(sorted(self.data.items()))
            self._hash = hash(items)
        return self._hash
    
    def __eq__(self, other):
        if not isinstance(other, CacheKey):
            return False
        return self.data == other.data
    
    def __repr__(self):
        return f"CacheKey({self.data})"

class MDPRequestCacheKey(CacheKey):
    """Cache key for MDP requests"""
    
    @staticmethod
    def from_request(request: Dict[str, Any]) -> "MDPRequestCacheKey":
        return MDPRequestCacheKey(
            curve_name=request.get("curve_name"),
            timestamp=request.get("timestamp"),
            # Exclude volatile keys
        )

class QueryCacheKey(CacheKey):
    """Cache key for resolved queries"""
    
    @staticmethod
    def from_query(query: BaseQuery, timestamp) -> "QueryCacheKey":
        return QueryCacheKey(
            query_signature=query.signature(),
            timestamp=timestamp,
        )

# Usage
def _pricer_for_request(self, req: Dict[str, Any]) -> Any:
    key = MDPRequestCacheKey.from_request(req)
    
    if key in self._cache:
        return self._cache[key]
    
    pricer = self.mdp.get_pricer(req)
    self._cache[key] = pricer
    return pricer
```

#### 3.1.2 Incremental MTM (Differential Updates)

```python
# BT/query_engine.py (optimized)
from dataclasses import dataclass
from typing import Optional

@dataclass
class MTMSnapshot:
    timestamp: datetime.datetime
    total_value: float
    position_values: Dict[int, float]  # position_id -> value
    realized_pnl: float

class QueryDrivenBacktest:
    def __init__(self, ...):
        # ...existing...
        self._last_mtm_snapshot: Optional[MTMSnapshot] = None
        self._position_mtm_cache: Dict[int, float] = {}
    
    def mark_to_market(self, now: datetime.datetime) -> float:
        """
        Optimized MTM calculation.
        Only re-compute changed positions.
        """
        now_pricer_sig = self._get_pricer_signature(now)
        
        if self._last_mtm_snapshot and self._last_pricer_sig == now_pricer_sig:
            # Pricer hasn't changed, positions are static
            # Most common case: same pricer across multiple timesteps
            return self._last_mtm_snapshot.total_value
        
        total = float(self.realized_pnl)
        position_values = {}
        
        for idx, pos in enumerate(self.portfolio.iter_positions()):
            # Only recalculate if needed
            pos_mtm = self._position_value(pos, now)
            position_values[idx] = pos_mtm
            total += pos_mtm
        
        snapshot = MTMSnapshot(
            timestamp=now,
            total_value=total,
            position_values=position_values,
            realized_pnl=self.realized_pnl,
        )
        
        self._last_mtm_snapshot = snapshot
        self._last_pricer_sig = now_pricer_sig
        self.mtm_history[now] = total
        
        return total
```

#### 3.1.3 Batch Pricer Initialization

```python
# TB/IRSwapsTB.py (enhanced)
from concurrent.futures import ThreadPoolExecutor
import functools

class BatchPricerLoader:
    """Load pricers for entire time grid upfront"""
    
    def __init__(self, mdp: MarketDataProvider, max_workers: int = 4):
        self.mdp = mdp
        self.max_workers = max_workers
        self.cache: Dict[CacheKey, Any] = {}
    
    def warm_cache(self, time_grid: TimeGrid, curve_names: List[str]) -> None:
        """Pre-populate cache for all timestamps and curves"""
        requests = []
        
        for ts in time_grid:
            for curve_name in curve_names:
                requests.append({
                    "curve_name": curve_name,
                    "timestamp": ts.date(),
                })
        
        # Parallel loading
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [
                executor.submit(self._load_pricer, req)
                for req in requests
            ]
            
            for future in tqdm.tqdm(futures, desc="Warming pricer cache"):
                future.result()
    
    def _load_pricer(self, request: Dict[str, Any]) -> Any:
        key = MDPRequestCacheKey.from_request(request)
        if key not in self.cache:
            self.cache[key] = self.mdp.get_pricer(request)
        return self.cache[key]

# Usage in backtest
loader = BatchPricerLoader(mdp, max_workers=4)
loader.warm_cache(time_grid, ["USD-SOFR-1D", "USD-OIS", "USD-FEDFUNDS"])
# Now pricers are pre-loaded
```

#### 3.1.4 Multi-Level Cache Hierarchy

```python
# Caching/multi_level_cache.py
from abc import ABC, abstractmethod
from typing import Any, Optional

class CacheLevel(ABC):
    """Abstract cache level (L1=memory, L2=disk, etc.)"""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]: ...
    
    @abstractmethod
    def set(self, key: str, value: Any) -> None: ...

class MemoryCache(CacheLevel):
    """Fast in-memory cache (L1)"""
    
    def __init__(self, maxsize: int = 1000):
        self.cache: Dict[str, Any] = {}
        self.maxsize = maxsize
    
    def get(self, key: str) -> Optional[Any]:
        return self.cache.get(key)
    
    def set(self, key: str, value: Any) -> None:
        if len(self.cache) >= self.maxsize:
            # Evict LRU
            oldest = min(self.cache, key=self.cache.get)
            del self.cache[oldest]
        self.cache[key] = value

class DiskCache(CacheLevel, ZODBCacheMixin):
    """Persistent disk cache (L2)"""
    
    def __init__(self, db_path: str):
        super().__init__(use_btree=True, force_refresh=False)
        self.db_path = db_path
    
    def get(self, key: str) -> Optional[Any]:
        # Load from ZODB
        pass
    
    def set(self, key: str, value: Any) -> None:
        # Persist to ZODB
        pass

class MultiLevelCache:
    """Manages L1 (memory) → L2 (disk) hierarchy"""
    
    def __init__(self, l1: CacheLevel, l2: Optional[CacheLevel] = None):
        self.l1 = l1
        self.l2 = l2
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        # Try L1
        value = self.l1.get(key)
        if value is not None:
            self.hits += 1
            return value
        
        # Try L2
        if self.l2:
            value = self.l2.get(key)
            if value is not None:
                self.l1.set(key, value)  # Promote to L1
                self.hits += 1
                return value
        
        self.misses += 1
        return None
    
    def set(self, key: str, value: Any) -> None:
        self.l1.set(key, value)
        if self.l2:
            self.l2.set(key, value)
    
    def stats(self) -> Dict[str, float]:
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
        }
```

### 3.2 Parallel Execution

**Current State**: Sequential time-grid processing only

**Opportunities**:

#### 3.2.1 Parallel Backtest Runs

```python
# BT/parallel_backtest.py
from concurrent.futures import ProcessPoolExecutor, as_completed
import pickle
from typing import List, Callable

class ParallelBacktestRunner:
    """Run multiple backtests in parallel"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
    
    def run_scenarios(
        self,
        scenario_builder: Callable[[int], QueryDrivenBacktest],
        num_scenarios: int,
    ) -> List[QueryDrivenBacktest]:
        """
        Run multiple backtest scenarios in parallel.
        
        Args:
            scenario_builder: Function that creates backtest for scenario i
            num_scenarios: Number of scenarios to run
        
        Returns:
            List of completed backtest objects
        """
        results = []
        
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._run_scenario, scenario_builder, i): i
                for i in range(num_scenarios)
            }
            
            for future in as_completed(futures):
                scenario_id = futures[future]
                try:
                    bt = future.result()
                    results.append(bt)
                    print(f"Completed scenario {scenario_id}")
                except Exception as e:
                    print(f"Scenario {scenario_id} failed: {e}")
        
        return results
    
    @staticmethod
    def _run_scenario(
        scenario_builder: Callable,
        scenario_id: int
    ) -> QueryDrivenBacktest:
        """Run single scenario (in worker process)"""
        bt = scenario_builder(scenario_id)
        bt.run()
        return bt

# Usage
def build_scenario(scenario_id: int) -> QueryDrivenBacktest:
    volatility = 0.01 + (scenario_id * 0.005)
    # Create backtest with scenario params
    return QueryDrivenBacktest(...)

runner = ParallelBacktestRunner(max_workers=4)
results = runner.run_scenarios(build_scenario, num_scenarios=10)

# Analyze results
for i, bt in enumerate(results):
    print(f"Scenario {i}: Total MTM = {bt.mtm_history[list(bt.mtm_history.keys())[-1]]}")
```

#### 3.2.2 Parallel Position Valuation

```python
# BT/query_engine.py (optimized)
from multiprocessing.pool import ThreadPool
import threading

class QueryDrivenBacktest:
    def __init__(self, ..., use_multithread: bool = False):
        # ...
        self.use_multithread = use_multithread
    
    def mark_to_market_parallel(self, now: datetime.datetime) -> float:
        """Calculate MTM using thread pool for position valuation"""
        if not self.use_multithread or len(self.portfolio.positions) < 10:
            # Fall back to serial for small portfolios
            return self.mark_to_market(now)
        
        total = float(self.realized_pnl)
        
        def value_position(pos: ResolvedQueryPosition) -> float:
            return self._position_value(pos, now)
        
        with ThreadPool(max_workers=4) as pool:
            values = pool.map(value_position, self.portfolio.iter_positions())
        
        total += sum(values)
        self.mtm_history[now] = total
        return total
```

### 3.3 Memory Management

**Issues**:

1. **Portfolio grows unbounded** - old positions never freed
2. **History dicts never pruned** - mtm_history grows with time grid
3. **Large queries cached without eviction** - pricer objects held in memory

**Recommendations**:

#### 3.3.1 Position Lifecycle Management

```python
# BT/query_portfolio.py (enhanced)
from enum import Enum
from dataclasses import dataclass, field
import datetime

class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    ARCHIVED = "archived"

@dataclass
class ResolvedQueryPosition:
    package: List[_GenericPricable]
    weights: List[float]
    opened: datetime.datetime
    source_query: BaseQuery
    meta: Dict[str, Any] = field(default_factory=dict)
    
    # New fields
    closed: Optional[datetime.datetime] = None
    status: PositionStatus = PositionStatus.OPEN
    realized_pnl: float = 0.0

class QueryPortfolio:
    def __init__(self, archive_after_days: int = 30):
        self.positions: List[ResolvedQueryPosition] = []
        self.archive: List[ResolvedQueryPosition] = []  # Closed positions
        self.archive_after_days = archive_after_days
    
    def close_position(self, pos: ResolvedQueryPosition, closed_at: datetime.datetime, pnl: float):
        """Close a position and archive if old"""
        pos.closed = closed_at
        pos.status = PositionStatus.CLOSED
        pos.realized_pnl = pnl
        
        # Archive old closed positions
        cutoff = closed_at - datetime.timedelta(days=self.archive_after_days)
        self.archive.extend([
            p for p in self.positions
            if p.status == PositionStatus.CLOSED and p.closed < cutoff
        ])
        self.positions = [
            p for p in self.positions
            if not (p.status == PositionStatus.CLOSED and p.closed < cutoff)
        ]
    
    def get_memory_usage(self) -> Dict[str, int]:
        """Estimate memory usage in bytes"""
        import sys
        return {
            "positions": sys.getsizeof(self.positions) + sum(sys.getsizeof(p) for p in self.positions),
            "archive": sys.getsizeof(self.archive) + sum(sys.getsizeof(p) for p in self.archive),
        }
```

#### 3.3.2 Cache Size Limits

```python
# BT/query_engine.py (enhanced)
from functools import lru_cache
from collections import OrderedDict

class LRUCache(dict):
    """Simple LRU cache with size limit"""
    
    def __init__(self, maxsize: int = 1000):
        super().__init__()
        self.maxsize = maxsize
        self.order = []
    
    def __setitem__(self, key, value):
        if key in self:
            self.order.remove(key)
        elif len(self) >= self.maxsize:
            # Evict oldest
            oldest = self.order.pop(0)
            del self[oldest]
        
        super().__setitem__(key, value)
        self.order.append(key)

class QueryDrivenBacktest:
    def __init__(self, ..., cache_maxsize: int = 10000):
        self._cache = LRUCache(maxsize=cache_maxsize)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Monitor cache performance"""
        return {
            "cache_size": len(self._cache),
            "max_size": self._cache.maxsize,
            "utilization": len(self._cache) / self._cache.maxsize,
        }
```

### 3.4 Algorithm Efficiency

#### 3.4.1 Query Signature Computation

**Current**: String repr each time (inefficient)

```python
# Query/Base/BaseQuery.py (optimized)
from functools import cached_property

class BaseQuery(ABC):
    @cached_property
    def _signature_hash(self) -> str:
        """Compute signature once, cache result"""
        import hashlib
        
        parts = [
            f"product={self.product}",
            f"struct={self.structure_id}",
        ]
        
        for k, v in sorted((self.structure_kwargs or {}).items()):
            parts.append(f"{k}={v}")
        
        combined = "|".join(parts)
        return hashlib.md5(combined.encode()).hexdigest()
    
    def signature(self) -> str:
        """Return cached hash signature"""
        return self._signature_hash
```

#### 3.4.2 Package Resolution Caching

```python
# Query/Base/BaseQuery.py
class BaseQuery(ABC):
    _package_cache: Dict[str, Tuple[List[_GenericPricable], List[float]]] = {}
    
    def resolve_package(
        self,
        *,
        pricer_or_curve: Any,
        **hints: Any,
    ) -> Tuple[List[_GenericPricable], List[float]]:
        """Resolve with caching by query signature"""
        cache_key = (self.signature(), id(pricer_or_curve))
        
        if cache_key in self._package_cache:
            return self._package_cache[cache_key]
        
        # Compute
        adapter_cls = get_adapter(self.product)
        adapter = adapter_cls()
        struct_map = adapter.build_structure_map(pricer_or_curve=pricer_or_curve)
        
        kwargs = {k: v for k, v in (self.structure_kwargs or {}).items() if v is not None}
        kwargs.update(hints)
        
        package, weights = struct_map.apply(self.structure_id, **kwargs)
        
        # Cache
        self._package_cache[cache_key] = (package, weights)
        
        return package, weights
```

---

## 4. API IMPROVEMENTS

### 4.1 Consistency Across Modules

**Issues**:

1. **Inconsistent error handling** - ValueErrors, RuntimeErrors, Asserts mixed
2. **Inconsistent return types** - Some return Optional, some raise
3. **Naming conventions** - `get_data` vs `get_pricer`, `apply` vs `compute`

**Recommendations**:

#### 4.1.1 Unified Naming Convention

```python
# Create naming standards document
# BT/naming_conventions.md

## Naming Standards

### Methods
- Getters: `get_X()` for expensive operations, `X()` for cheap property-like access
  - `get_pricer(request)` - Expensive MDP call
  - `pricer()` - Cheap property access
  
- Computation: `compute_X()` for calculations
  - `compute_pv01()`
  
- Resolution: `resolve_X()`
  - `resolve_package()`
  
- Application: `apply(value_id, **kwargs)` for function maps
  - Not `compute()`, always `apply()`

- Validation: `validate_X()` returns List[str] (errors), not bool
  - Returns empty list if valid

### Exceptions
- Always raise specific exception types (ARBSError subclasses)
- Never use bare `assert` in library code
- Always include context: what failed and why

### Query Operations
- `structure_id` - Type identifier (enum)
- `structure_kwargs` - Parameters for structure building
- `value_id` - Type identifier for value
- `market_request` - Dict for MDP

# Apply standards
class MarketDataProvider(ABC):
    def get_pricer(self, request: dict) -> _GenericPricer:
        """Expensive operation: fetch/build pricer from request"""
        pass

class BaseQuery(ABC):
    def resolve_package(self, *, pricer_or_curve) -> Tuple[...]:
        """Resolve query to concrete instruments"""
        pass

class BaseValueFunctionMap:
    def apply(self, value_id, **kwargs) -> float:
        """Apply value function"""
        pass

class QueryValidator:
    @staticmethod
    def validate_query(q: BaseQuery) -> List[str]:
        """Return validation errors (empty = valid)"""
        pass
```

#### 4.1.2 Consistent Return Types

```python
# BT/contracts.py
"""
API contracts for consistent return types and exceptions.
"""

# Rule 1: Getters either return value or raise
# Rule 2: Validation returns List[str] (empty = valid)
# Rule 3: Apply/Compute returns T or raises

# Inconsistency found:
# IRSwapsMDP.get_data() -> Optional[...] 
# But also raises RuntimeError

# Should be:
class IRSwapsMDP(MarketDataProvider):
    def get_pricer(self, request: dict) -> _IRSwapGenericCurve:
        """Get or build pricer for request.
        
        Raises:
            MDPError: If curve cannot be resolved
            ValidationError: If request is invalid
        """
        curve = self._get_curve(...)
        if curve is None:
            raise MDPError(f"Could not build curve for {request}")
        return curve
    
    # Don't have a separate get_data() - use get_pricer()
```

### 4.2 Usability Enhancements

#### 4.2.1 Better Query Construction

Already covered above (Builder pattern).

#### 4.2.2 Enhanced Error Messages

```python
# BT/error_messages.py
class ErrorMessages:
    """User-friendly error message templates"""
    
    UNKNOWN_PRODUCT = (
        "Product '{product}' is not registered.\n"
        "Available products: {available}\n"
        "To register a new product:\n"
        "  1. Create Query/{product}/adapter.py\n"
        "  2. Implement ProductAdapter subclass\n"
        "  3. Call register_product('{product}', YourAdapter)\n"
        "See documentation: docs/extending_arbs.md"
    )
    
    UNKNOWN_CURVE = (
        "Curve '{curve}' not found in definitions.\n"
        "Available curves: {available}\n"
        "Check: definitions/{product}.py"
    )
    
    INVALID_STRUCTURE = (
        "Structure '{structure}' not supported for product '{product}'.\n"
        "Supported: {supported}\n"
        "See: Query/{product}/IRSwapStructure.py"
    )
    
    @staticmethod
    def unknown_product(product: str, available: List[str]) -> str:
        return ErrorMessages.UNKNOWN_PRODUCT.format(
            product=product,
            available=", ".join(available)
        )

# Usage
raise KeyError(ErrorMessages.unknown_product("Swaptions", list(_ADAPTERS.keys())))
```

#### 4.2.3 Interactive Shell Helpers

```python
# BT/repl_helpers.py
"""
Helpers for interactive backtest development (Jupyter, IPython).
"""

def list_products() -> pd.DataFrame:
    """List registered products"""
    from Query.Base.product_adapter import _ADAPTERS
    return pd.DataFrame([
        {
            "product": name,
            "adapter": cls.__name__,
            "module": cls.__module__,
        }
        for name, cls in _ADAPTERS.items()
    ])

def list_curves() -> pd.DataFrame:
    """List available curves"""
    from definitions.IRSwaps import CURVE_DEFINITIONS
    return pd.DataFrame([
        {
            "name": name,
            "calendar": str(defn.get("calendar")),
            "day_count": defn.get("day_count"),
        }
        for name, defn in CURVE_DEFINITIONS.items()
    ])

def describe_query(q: BaseQuery) -> Dict[str, Any]:
    """Pretty-print query structure"""
    return {
        "signature": q.signature(),
        "product": q.product,
        "structure": q.structure_id,
        "market_request": q.market_request,
        "parameters": q.structure_kwargs,
    }

def test_mdp(mdp: MarketDataProvider, curve_name: str, dates: List) -> pd.DataFrame:
    """Quick smoke test of MDP across dates"""
    results = []
    for dt in dates:
        try:
            req = {"curve_name": curve_name, "timestamp": dt}
            pricer = mdp.get_pricer(req)
            results.append({
                "date": dt,
                "status": "OK",
                "pricer_type": type(pricer).__name__,
            })
        except Exception as e:
            results.append({
                "date": dt,
                "status": "ERROR",
                "error": str(e),
            })
    return pd.DataFrame(results)
```

### 4.3 Breaking Changes Worth Considering

**Low-Impact Breaking Changes** (good to do for v2.0):

1. **Remove `get_data()` alias** from MarketDataProvider
   ```python
   # Old (deprecated in favor of get_pricer):
   def get_data(self, request) -> _GenericPricer:
       return self.get_pricer(request)
   
   # Just remove this method in v2.0
   ```

2. **Standardize exception types**
   - Current: Mix of ValueError, RuntimeError, AssertionError, KeyError
   - New: Use ARBSError subclasses consistently
   - Benefit: Better error handling in user code

3. **Make QueryPortfolio.positions immutable**
   ```python
   # Old: Can modify directly
   bt.portfolio.positions.append(pos)
   
   # New: Use methods only
   bt.portfolio.add_position(pos)
   # Better: Can add validation, logging, caching
   ```

4. **Unify market_request schema**
   ```python
   # Current: Inconsistent keys across MDPs
   # New: Standardize to CurveRequest dataclass
   
   @dataclass
   class CurveRequest:
       curve_name: str
       timestamp: Union[datetime.date, Literal["live"]]
       source: Optional[str] = None  # Override MDP.source
       custom_params: Dict[str, Any] = field(default_factory=dict)
   
   class MarketDataProvider(ABC):
       def get_pricer(self, request: CurveRequest) -> _GenericPricer:
           pass
   ```

---

## 5. FEATURE ADDITIONS

### 5.1 New Product Support

**Template for adding Swaptions**:

```python
# Query/Swaptions/SwaptionStructure.py
from enum import Enum
from Query.Base.BaseStructure import BaseStructureFunctionMap

class SwaptionStructure(Enum):
    PAYER_CAP = "payer_cap"
    RECEIVER_CAP = "receiver_cap"
    STRADDLE = "straddle"
    COLLAR = "collar"

class SwaptionStructureFunctionMap(BaseStructureFunctionMap[SwaptionStructure, _SwaptionGenericObject]):
    def _create_map(self):
        return {
            SwaptionStructure.PAYER_CAP: self._build_payer_swaption,
            SwaptionStructure.RECEIVER_CAP: self._build_receiver_swaption,
            SwaptionStructure.STRADDLE: self._build_straddle,
            SwaptionStructure.COLLAR: self._build_collar,
        }
    
    def _build_payer_swaption(self, tenor: str, strike: float, **kwargs):
        # Build payer swaption
        pass

# Query/Swaptions/SwaptionValue.py
class SwaptionValue(Enum):
    PRICE = auto()
    IMPLIED_VOL = auto()
    DELTA = auto()
    VEGA = auto()
    THETA = auto()

# Query/Swaptions/adapter.py
class SwaptionProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve):
        return SwaptionStructureFunctionMap(curve=pricer_or_curve)
    
    def build_value_map(self, *, pricer_or_curve, package, risk_weights):
        return SwaptionValueFunctionMap(curve=pricer_or_curve, package=package)

# Register on import
register_product("Swaptions", SwaptionProductAdapter)

# Query/Swaptions/SwaptionQuery.py
@dataclass(frozen=True)
class SwaptionQuery(BaseQuery):
    structure: SwaptionStructure
    value: SwaptionValue
    
    tenor: str  # "5Y"
    strike: float
    expiry: str  # "2Y"
    curve: str
    
    product: str = field(init=False, default="Swaptions")
    
    def __post_init__(self):
        object.__setattr__(self, "product", "Swaptions")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "value_id", self.value)
```

### 5.2 Additional Data Sources

**SDR Intraday Enhancement**:

```python
# MDP/IRSwaps/SDR_INTRADAY/
# Current: Partial implementation
# Add: Better error handling, incremental refresh, hourly updates

class SDRIntradayMDP(MarketDataProvider):
    """SDR intraday curve builder with caching"""
    
    def __init__(self, source: str = "SDR_INTRADAY-RL", refresh_interval_hours: int = 1):
        super().__init__(source)
        self.refresh_interval = datetime.timedelta(hours=refresh_interval_hours)
        self._last_refresh: Dict[str, datetime.datetime] = {}
    
    def get_pricer(self, request: dict) -> _IRSwapGenericCurve:
        curve_name = request.get("curve_name")
        timestamp = request.get("timestamp")
        
        # Check if refresh needed
        if self._needs_refresh(curve_name, timestamp):
            self._refresh_sdr_data(curve_name, timestamp)
        
        return self._build_curve(curve_name, timestamp)
    
    def _needs_refresh(self, curve_name: str, timestamp) -> bool:
        last = self._last_refresh.get(curve_name)
        if last is None:
            return True
        return datetime.datetime.now() - last > self.refresh_interval
```

### 5.3 Analytics Capabilities

#### 5.3.1 Risk Attribution

```python
# Analytics/risk_attribution.py
class RiskAttributor:
    """Break down portfolio risk by source"""
    
    def attribute_risk(
        self,
        portfolio: QueryPortfolio,
        pricer,
        total_risk: float,
    ) -> pd.DataFrame:
        """Attribute total DV01 to positions"""
        
        results = []
        for pos in portfolio.iter_positions():
            pos_dv01 = sum(pricer.dv01(p) for p in pos.package)
            contribution = pos_dv01 / total_risk if total_risk != 0 else 0.0
            
            results.append({
                "query_sig": pos.source_query.signature(),
                "dv01": pos_dv01,
                "contribution": contribution,
                "percentage": contribution * 100,
            })
        
        return pd.DataFrame(results).sort_values("contribution", ascending=False)
```

#### 5.3.2 Performance Analysis

```python
# Analytics/backtest_analyzer.py
class BacktestAnalyzer:
    """Post-backtest statistics"""
    
    def __init__(self, backtest: QueryDrivenBacktest):
        self.bt = backtest
    
    def summary(self) -> Dict[str, float]:
        """Key metrics"""
        mtm_vals = list(self.bt.mtm_history.values())
        
        return {
            "total_return": mtm_vals[-1],
            "num_trades": len(self.bt.portfolio.trades_log),
            "avg_position_size": np.mean([
                sum(p.weights) for p in self.bt.portfolio.iter_positions()
            ]),
            "max_drawdown": self._max_drawdown(),
            "sharpe_ratio": self._sharpe_ratio(),
        }
    
    def _max_drawdown(self) -> float:
        vals = list(self.bt.mtm_history.values())
        cummax = np.maximum.accumulate(vals)
        drawdown = (vals - cummax) / cummax
        return float(np.min(drawdown))
    
    def _sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
        mtm_vals = np.array(list(self.bt.mtm_history.values()))
        returns = np.diff(mtm_vals) / mtm_vals[:-1]
        excess_return = np.mean(returns) - risk_free_rate
        return excess_return / (np.std(returns) + 1e-10)
```

### 5.4 Monitoring & Observability

#### 5.4.1 Metrics Collection

```python
# Monitoring/backtest_metrics.py
from typing import Dict, List
import datetime

class BacktestMetrics:
    """Collect metrics during backtest execution"""
    
    def __init__(self):
        self.timestamps: List[datetime.datetime] = []
        self.mtm_values: List[float] = []
        self.pnl_realized: List[float] = []
        self.position_counts: List[int] = []
        self.error_counts: List[int] = []
        self.execution_times: List[float] = []
    
    def record_step(
        self,
        timestamp: datetime.datetime,
        mtm: float,
        realized_pnl: float,
        num_positions: int,
        num_errors: int,
        exec_time: float,
    ):
        self.timestamps.append(timestamp)
        self.mtm_values.append(mtm)
        self.pnl_realized.append(realized_pnl)
        self.position_counts.append(num_positions)
        self.error_counts.append(num_errors)
        self.execution_times.append(exec_time)
    
    def to_dataframe(self) -> pd.DataFrame:
        """Export metrics"""
        return pd.DataFrame({
            "timestamp": self.timestamps,
            "mtm": self.mtm_values,
            "realized_pnl": self.pnl_realized,
            "num_positions": self.position_counts,
            "errors": self.error_counts,
            "exec_time_ms": np.array(self.execution_times) * 1000,
        })
    
    def plot(self):
        """Visualize metrics"""
        df = self.to_dataframe()
        fig, axes = plt.subplots(3, 1, figsize=(12, 8))
        
        axes[0].plot(df["timestamp"], df["mtm"], label="MTM")
        axes[0].set_ylabel("MTM ($)")
        
        axes[1].plot(df["timestamp"], df["num_positions"], label="Open Positions")
        axes[1].set_ylabel("Count")
        
        axes[2].plot(df["timestamp"], df["exec_time_ms"], label="Execution Time")
        axes[2].set_ylabel("Time (ms)")
        
        for ax in axes:
            ax.legend()
            ax.grid(True)
        
        plt.tight_layout()
        return fig
```

#### 5.4.2 Logging Configuration

```python
# Monitoring/logging_config.py
import logging
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detailed": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "[%(levelname)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "backtest.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "level": "DEBUG",
            "formatter": "detailed",
        },
    },
    "loggers": {
        "BT": {
            "level": "DEBUG",
            "handlers": ["console", "file"],
        },
        "Query": {
            "level": "DEBUG",
            "handlers": ["console", "file"],
        },
        "MDP": {
            "level": "INFO",
            "handlers": ["console", "file"],
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
```

---

## 6. DEVOPS & INFRASTRUCTURE

### 6.1 CI/CD Pipeline

**Recommendation**: Add comprehensive GitHub Actions pipeline (already detailed in Testing section)

### 6.2 Docker Configuration

```dockerfile
# Dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libboost-all-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# Pre-compile Python files
RUN python -m py_compile \
    BT/*.py \
    Query/**/*.py \
    MDP/**/*.py

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from BT.query_engine import QueryDrivenBacktest; print('OK')"

CMD ["python", "-m", "arbs.server"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  arbs:
    build: .
    environment:
      - PYTHONUNBUFFERED=1
      - LOG_LEVEL=INFO
      - CACHE_DIR=/data/cache
    volumes:
      - ./data:/data
      - ./config:/app/config:ro
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  redis_data:
```

### 6.3 Configuration Management

```yaml
# config/backtester.yaml
application:
  name: ARBS
  version: 1.0.0

backtesting:
  default_time_zone: "America/New_York"
  cache_dir: "./cache"
  cache_maxsize: 10000
  max_workers: 4

data_providers:
  cme:
    source: "CME_NY_EOD_LIVE-ql_basic"
    timeout_seconds: 30
    retry_attempts: 3
  sdr:
    source: "SDR_INTRADAY-RL"
    refresh_interval_hours: 1

logging:
  level: "INFO"
  file: "./logs/arbs.log"
  max_size_mb: 100
  backup_count: 5

performance:
  enable_multiprocessing: true
  worker_processes: 4
  cache_level: "multi"  # memory, disk, multi
  cache_eviction: "lru"  # lru, lfu
```

```python
# config/config_loader.py
import yaml
from pathlib import Path
from dataclasses import dataclass

@dataclass
class BacktesterConfig:
    default_time_zone: str
    cache_dir: str
    cache_maxsize: int
    max_workers: int

class ConfigLoader:
    @staticmethod
    def load(config_file: Path = None) -> dict:
        if config_file is None:
            config_file = Path(__file__).parent / "backtester.yaml"
        
        with open(config_file) as f:
            return yaml.safe_load(f)
    
    @staticmethod
    def get_backtest_config(config_file: Path = None) -> BacktesterConfig:
        cfg = ConfigLoader.load(config_file)
        return BacktesterConfig(**cfg["backtesting"])
```

---

## 7. DOCUMENTATION & EXAMPLES

### 7.1 Tutorial Improvements

**Add structured tutorials to docs/**:

```markdown
# docs/tutorials/01_quickstart.md
# ARBS Quick Start: Your First Backtest

## Objectives
- Run a simple 5Y IRS backtest
- Understand core concepts
- Inspect results

## Step 1: Environment Setup
[...]

## Step 2: Define Time Grid
[Code example]

## Step 3: Create Strategy
[Code example]

## Step 4: Configure MDP
[Code example]

## Step 5: Run & Analyze
[Code example with output]

## What's Next?
[Link to advanced tutorials]
```

### 7.2 Example Gallery

```python
# examples/01_simple_5y_backtest.py
"""
Example 1: Simple 5Y IRS Backtest

Run a monthly backtest on USD-SOFR 5Y rates.
"""

def main():
    # ... complete runnable example ...
    pass

# examples/02_multi_leg_fly_backtest.py
"""
Example 2: Fly Spread Backtest

Build and backtest 2Y-5Y-10Y flies.
"""

# examples/03_event_driven_hedging.py
"""
Example 3: Event-Driven Hedging

Use risk triggers to hedge portfolio exposures.
"""

# examples/04_custom_product.py
"""
Example 4: Add Custom Product (Swaptions)

Extend ARBS with new product adapter.
"""

# examples/05_performance_tuning.py
"""
Example 5: Parallel Backtests & Caching

Run scenario analysis with multiprocessing.
"""
```

### 7.3 API Reference Generation

```python
# docs/generate_api_reference.py
from pathlib import Path
import inspect

def generate_module_reference(module_name: str) -> str:
    """Generate API reference for module"""
    
    module = importlib.import_module(module_name)
    
    # Collect all public classes/functions
    md = f"# {module_name} API Reference\n\n"
    
    for name, obj in inspect.getmembers(module):
        if name.startswith("_"):
            continue
        
        if inspect.isclass(obj):
            md += f"## Class: `{name}`\n"
            md += f"{inspect.getdoc(obj)}\n\n"
            
            # List methods
            for method_name, method in inspect.getmembers(obj):
                if not method_name.startswith("_") and callable(method):
                    sig = inspect.signature(method)
                    md += f"### `{method_name}{sig}`\n"
                    md += f"{inspect.getdoc(method)}\n\n"
        
        elif inspect.isfunction(obj):
            sig = inspect.signature(obj)
            md += f"## Function: `{name}{sig}`\n"
            md += f"{inspect.getdoc(obj)}\n\n"
    
    return md

# Generate for all modules
if __name__ == "__main__":
    modules = ["BT.query_engine", "BT.triggers", "Query.IRSwaps", "MDP.IRSwaps"]
    
    for module in modules:
        md = generate_module_reference(module)
        output_file = Path(f"docs/api/{module.replace('.', '_')}.md")
        output_file.write_text(md)
```

---

## 8. IMPLEMENTATION PRIORITIES

### Phase 1: Quick Wins (1-2 weeks)
1. Improve error handling (custom exceptions)
2. Add docstrings (Google style)
3. Set up CI/CD with GitHub Actions
4. Basic unit tests for core modules

### Phase 2: Architecture (2-4 weeks)
1. Implement QueryResolutionContext
2. Plugin system for products
3. Error handler strategy pattern
4. Unified caching layer

### Phase 3: Features & Polish (4-8 weeks)
1. Add Swaptions product
2. Implement analytics capabilities
3. Enhance monitoring/observability
4. Create tutorial library

### Phase 4: Performance (ongoing)
1. Multiprocessing for scenarios
2. Cache warming strategies
3. Memory management improvements
4. Parallel position valuation

---

## Summary

This analysis identifies **high-value improvements** across all dimensions:

- **Architecture**: Cleaner separation via QueryResolutionContext, plugin system
- **Code Quality**: Better type hints, comprehensive testing, standardized errors
- **Performance**: Multi-level caching, parallel execution, incremental MTM
- **API**: Consistent naming, better error messages, builder patterns
- **Features**: Swaptions product, analytics, monitoring
- **DevOps**: CI/CD, Docker, configuration management
- **Docs**: Tutorials, API generation, examples

**Total Estimated Effort**: ~3-4 months for 1-2 FTE engineers

**ROI**: Significantly improved maintainability, testability, and extensibility.
