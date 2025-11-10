# ARBS Query Module: Comprehensive Technical Documentation

## Table of Contents

1. [Overview & Architecture](#overview--architecture)
2. [BaseQuery Abstract Interface](#basequery-abstract-interface)
3. [Product Adapter Pattern & Registration](#product-adapter-pattern--registration)
4. [Structure Maps & Value Maps](#structure-maps--value-maps)
5. [Generic Interfaces: Pricable & Pricer](#generic-interfaces-pricable--pricer)
6. [IRSwaps Implementation](#irswaps-implementation)
7. [FixedRateBonds Implementation](#fixedratebonds-implementation)
8. [Backend Abstraction Layer](#backend-abstraction-layer)
9. [Query Resolution Pipeline](#query-resolution-pipeline)
10. [Extension Guide: Adding New Products](#extension-guide-adding-new-products)
11. [API Reference](#api-reference)

---

## Overview & Architecture

### Philosophy

The Query module implements a **product-agnostic query system** that decouples the specification of financial instruments from their valuation. The architecture enables:

- **Product Independence**: Backtesting engine remains unaware of specific products (IRS, FRB, Swaptions, etc.)
- **Backend Flexibility**: Support multiple pricing libraries (QuantLib vs RatesLib) without changing query logic
- **Composable Queries**: Queries can be combined arithmetically to form spreads and flies
- **Dynamic Structure Building**: Queries resolve into concrete instrument packages at runtime based on market data

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│           Backtesting Engine (Product-Agnostic)             │
├─────────────────────────────────────────────────────────────┤
│  1. At each timestep, calls query.build_mdp_request(now)   │
│  2. Uses ProductAdapter to resolve package & weights        │
│  3. Uses ProductAdapter to build value map                  │
│  4. Applies value map to get metrics (NPV, PV01, etc.)      │
└─────────────────────────────────────────────────────────────┘
         ↓                     ↓                  ↓
    ┌────────┐        ┌──────────────┐    ┌──────────────┐
    │BaseQuery│        │ProductAdapter│    │MarketData    │
    │(IRS,FRB)│        │(IRS, FRB)    │    │Provider      │
    └────────┘        └──────────────┘    └──────────────┘
         ↓                     ↓                  ↓
    Structure Enum      Structure Map      Pricer/Curve
    Value Enum          Value Map          (QL or RL)
```

---

## BaseQuery Abstract Interface

### Purpose

`BaseQuery` is the product-agnostic entry point. It defines the contract that all product-specific queries (IRSwapQuery, FixedRateBondQuery) must implement.

### Class Definition

**File**: `/home/user/ARBS/Query/Base/BaseQuery.py`

```python
@dataclass(frozen=True)
class BaseQuery(ABC):
    """
    Product-agnostic entry point for the backtester.
    
    You hand this object to the engine. At each timestep:
      1) The engine calls build_mdp_request(now) -> dict
      2) Using the product adapter:
         - engine resolves (package, risk_weights) = StructureMap.apply(...)
         - engine values via ValueMap.apply(...)
    """
```

### Core Fields

| Field | Type | Purpose |
|-------|------|---------|
| `product` | `str` | Logical product name ("IRS", "FRB") - selects adapter |
| `structure_id` | `Any` | Product-specific identifier (enum or str) for outright/curve/fly |
| `structure_kwargs` | `Dict[str, Any]` | Product-specific build params (tenor, dates, notional, side, strikes) |
| `value_id` | `Optional[Any]` | Default value metric for quick one-off valuation |
| `value_ids` | `Tuple[Any, ...]` | Additional metrics to compute/record |
| `market_request` | `Dict[str, Any]` | Template for `MDP.get_pricer(request)` |
| `mdp_time_key` | `str` | Key within market_request for per-timestep time (default: "timestamp") |
| `name` | `Optional[str]` | Display label for dataframes/plots |
| `tags` | `Tuple[str, ...]` | Audit/grouping tags |
| `meta` | `Dict[str, Any]` | Arbitrary metadata |

### Key Methods

#### 1. `build_mdp_request(now: datetime.datetime) -> Dict[str, Any]`

Builds the request dictionary for `MDP.get_pricer(request)` at time `now`.

**Policy**:
- If `mdp_time_key` missing from `market_request` → inject `now.date()`
- If `mdp_time_key == "live"` or already set → pass through unchanged
- If `mdp_time_key == "now"` → inject full datetime

**Example**:
```python
query = IRSwapQuery(
    tenor="10Y",
    curve="USD-SOFR-1D",
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    notional=1_000_000,
)
req = query.build_mdp_request(datetime.datetime(2024, 1, 15, 12, 0, 0))
# Result: {"curve_name": "USD-SOFR-1D", "timestamp": datetime.date(2024, 1, 15)}
```

#### 2. `resolve_package(pricer_or_curve, **hints) -> Tuple[List[_GenericPricable], List[float]]`

Resolves this query into a concrete package of priceables + weights using the product adapter.

**Process**:
1. Gets the adapter class via `get_adapter(self.product)`
2. Adapter builds a `StructureMap` bound to the pricer/curve
3. Calls `struct_map.apply(structure_id, **kwargs)` to get (package, weights)

**Example**:
```python
q = IRSwapQuery(tenor="10Y", notional=1_000_000)
pricer = mdp.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": date(2024, 1, 15)})
package, weights = q.resolve_package(pricer_or_curve=pricer)
# package: [IRSwap(...)]  # a list of _IRSwapGenericObject
# weights: [1.0]          # single leg weight
```

#### 3. `build_value_map(pricer_or_curve, package, risk_weights) -> Any`

Gets the value map bound to (pricer/curve, package, weights) via the product adapter.

**Example**:
```python
value_map = q.build_value_map(
    pricer_or_curve=pricer,
    package=package,
    risk_weights=weights,
)
npv = value_map.apply(IRSwapValue.NPV)
pv01 = value_map.apply(IRSwapValue.PV01)
```

### Abstract Methods (Must Implement)

#### 1. `return_query() -> Union[BaseQuery, List[BaseQuery]]`

Expands a query if it has multiple value metrics. Default: returns `[self]`.

Used when `value` is a list of enum values - expands into separate queries, one per metric.

#### 2. `col_name(cube_name: Optional[str] = None) -> str`

Human-friendly label for dataframes/plots. Includes product specifics.

#### 3. `eval_expression(cube_name: Optional[str] = None) -> str`

Expression for use in analysis cubes/spreadsheets. May include risk_weight arithmetic.

### Convenience Methods

#### `signature() -> str`

Stable identifier for logging/portfolio keys.

```python
q = IRSwapQuery(tenor="10Y", notional=1_000_000, tags=("fly_leg",))
print(q.signature())
# Output: product=IRS|struct=OUTRIGHT|tenor=10Y|value=RATE|tags=fly_leg
```

#### `default_mtm_value_id() -> Any`

Returns the primary value metric (from `value_id` or first element of `value_ids`).

### Arithmetic Operations

Queries support intuitive arithmetic for composing spreads and flies:

```python
# Single query with weight
q = IRSwapQuery(tenor="10Y", notional=1_000_000)
weighted_q = q * 2  # doubles the notional
short_q = -q        # flips the side

# Composing structures
curve = IRSwapQuery(tenor="2Y", ...) - IRSwapQuery(tenor="10Y", ...)
# Result: [2Y query with weight 1, 10Y query with weight -1]

fly = (IRSwapQuery(tenor="2Y", ...) * 1 
     - IRSwapQuery(tenor="5Y", ...) * 2
     + IRSwapQuery(tenor="10Y", ...) * 1)
# Result: list of 3 queries with weights [1, -2, 1]
```

---

## Product Adapter Pattern & Registration

### Purpose

Adapters decouple the backtester from product-specific logic. Each product (IRS, FRB) provides an adapter that:
1. Builds structure maps (converts structure IDs into priceables)
2. Builds value maps (calculates metrics on packages)
3. Optionally edits queries before building (e.g., resolve aliases to CUSIPs)

### Abstract Interface

**File**: `/home/user/ARBS/Query/Base/product_adapter.py`

```python
class ProductAdapter(ABC):
    """
    Pluggable adapter for a product (IRS, Swaption, …).
    Lets the backtester remain product-agnostic.
    """

    @abstractmethod
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        """
        Return the product's StructureFunctionMap (or equivalent) bound to a pricer/curve.
        Must expose:  apply(structure_id, **structure_kwargs) 
                      -> (package: List[_GenericPricable], weights: List[float])
        """

    @abstractmethod
    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        """
        Return the product's ValueFunctionMap (or equivalent).
        Must expose:  apply(value_id, **kwargs) -> float
        """

    @abstractmethod
    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        """
        Optionally normalize/expand the query before building structure.
        Default: no-op.
        """
```

### Registry Mechanism

Global registry pattern allows dynamic product registration:

```python
_ADAPTERS: Dict[str, Type[ProductAdapter]] = {}

def register_product(product: str, adapter_cls: Type[ProductAdapter]) -> None:
    """Register a product adapter."""
    if not issubclass(adapter_cls, ProductAdapter):
        raise TypeError("adapter_cls must subclass ProductAdapter")
    _ADAPTERS[product] = adapter_cls

def get_adapter(product: str) -> Type[ProductAdapter]:
    """Retrieve registered adapter for a product."""
    try:
        return _ADAPTERS[product]
    except KeyError:
        raise KeyError(
            f"No ProductAdapter registered for product '{product}'. "
            f"Registered: {sorted(_ADAPTERS)}"
        )
```

### Registration Pattern

Adapters self-register on module import:

```python
# In Query/IRSwaps/adapter.py
class IRSProductAdapter(ProductAdapter):
    # ... implementation ...

register_product("IRS", IRSProductAdapter)

# In Query/FixedRateBonds/adapter.py
class FRBProductAdapter(ProductAdapter):
    # ... implementation ...

register_product("FRB", FRBProductAdapter)
```

### Example: IRSProductAdapter

**File**: `/home/user/ARBS/Query/IRSwaps/adapter.py`

```python
class IRSProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        # pricer_or_curve is an _IRSwapGenericCurve (QL or RL backend)
        return IRSwapStructureFunctionMap(curve=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_IRSwapGenericObject],
        risk_weights: List[float],
    ) -> Any:
        return IRSwapValueFunctionMap(
            curve=pricer_or_curve, 
            package=package, 
            risk_weights=risk_weights
        )

    def edit_query(self, *, q: IRSwapQuery, pricer_or_curve: _IRSwapGenericCurve):
        """
        Special handling for MMS (Matched-Maturity Swap) queries.
        
        If query tenor is a UST alias (CT2, O3, Ox5, MMYY[-OI]):
        - Resolve to actual maturity date
        - Replace tenor with explicit effective/maturity dates
        """
        if q.curve not in ["USD-SOFR-1D", "USD-FEDFUNDS", "USD-OIS"]:
            return q  # Only for OIS curves
        if q.tenor is None:
            return q  # No tenor to edit
        
        # Check if tenor looks like a UST alias
        if _looks_like_alias_or_cusip(q.tenor):
            cusip, maturity = _resolve_cusip_or_alias(q.tenor, as_of_date)
            # Replace tenor with explicit dates
            skw = dict(q.structure_kwargs or {})
            skw["effective_date"] = pricer_or_curve.calendar_advance(as_of_date, "2D")
            skw["maturity_date"] = maturity
            return replace(q, tenor=None, effective_date=None, 
                          maturity_date=None, is_mms=True, 
                          structure_kwargs=skw)
        
        return q
```

---

## Structure Maps & Value Maps

### Structure Maps: Converting Specs to Priceables

#### Purpose

A **StructureMap** converts a high-level structure specification (enum) + parameters into a concrete list of priceable instruments with risk weights.

#### Base Class

**File**: `/home/user/ARBS/Query/Base/BaseStructure.py`

```python
class BaseStructureFunctionMap(ABC, Generic[E, T]):
    """
    Generic structure builder: enum -> List[priceable]
    
    E: Structure enum (IRSwapStructure, FixedRateBondStructure)
    T: Priceable type (IRSwapGenericObject, FixedRateBondGenericPricable)
    """

    def __init__(self, structure_enum: Type[E], **common_kwargs: Any):
        self._structure_enum = structure_enum
        self.common_kwargs = common_kwargs  # pricer/curve
        self._map: Dict[E, Callable[..., List[T]]] = self._create_map()

    @abstractmethod
    def _create_map(self) -> Dict[E, Callable[..., List[T]]]:
        """Build the mapping: structure_id -> builder function."""
        ...

    def apply(self, structure: E, **builder_kwargs: Any) -> Tuple[List[T], List[float]]:
        """
        Apply the builder for the given structure.
        
        Merges common_kwargs (pricer/curve) with builder_kwargs (structure params).
        Returns (package: List[T], risk_weights: List[float])
        """
        if structure not in self._map:
            raise KeyError(f"Structure '{structure}' is not supported.")
        builder = self._map[structure]
        kwargs = {**self.common_kwargs, **builder_kwargs}
        return builder(**kwargs)
```

#### IRSwaps Structure Map

**File**: `/home/user/ARBS/Query/IRSwaps/IRSwapStructure.py`

```python
class IRSwapStructure(Enum):
    OUTRIGHT = auto()  # Single swap
    CURVE = auto()      # 2-leg spread (e.g., 2s10s)
    FLY = auto()        # 3-leg spread (e.g., 2s5s10s)
    SPREAD = auto()     # Alias for OUTRIGHT

class IRSwapStructureFunctionMap(BaseStructureFunctionMap[IRSwapStructure, _IRSwapGenericObject]):
    def __init__(self, curve: _IRSwapGenericCurve):
        super().__init__(IRSwapStructure, curve=curve)
        self._map = self._create_map()

    def _create_map(self) -> Dict[IRSwapStructure, Callable[...]]:
        return {
            IRSwapStructure.OUTRIGHT: partial(self._build_outright),
            IRSwapStructure.CURVE: partial(self._build_curve),
            IRSwapStructure.FLY: partial(self._build_fly),
            IRSwapStructure.SPREAD: partial(self._build_outright),
        }

    def _build_outright(
        self,
        *,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_for_timeseries: Optional[bool] = False,
        **_,
    ) -> Tuple[List[_IRSwapGenericObject], List[float]]:
        """
        Build a single swap.
        
        Args:
            tenor: "10Y", "3M", or "1D" (for spot)
            effective_date, maturity_date: explicit dates (alternative to tenor)
            fixed_rate: fixed leg rate in decimal (0.025 for 2.5%)
            notional: notional amount (must specify notional XOR bpv)
            bpv: basis point value (used to derive notional)
            is_for_timeseries: skip notional/bpv validation if True
        
        Returns:
            ([swap], [weight])  where weight is ±1 based on notional sign
        """
        if not is_for_timeseries:
            assert notional is not None or bpv is not None
        
        rw = 1 if (notional or bpv) > 0 else -1
        swap = self._leg(
            tenor=tenor,
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
            bpv=bpv,
            is_for_timeseries=is_for_timeseries,
        )
        return [swap], [rw]

    def _build_curve(
        self,
        *,
        front_tenor: Optional[str] = None,
        back_tenor: Optional[str] = None,
        front_notional: Optional[float] = None,
        back_notional: Optional[float] = None,
        bpv: Optional[float] = None,
        risk_weights: Optional[List[float]] = [1, 1],
        front_fixed_rate: Optional[float] = -0,
        back_fixed_rate: Optional[float] = -0,
        **_,
    ) -> Tuple[List[_IRSwapGenericObject], List[float]]:
        """
        Build a 2-leg curve spread (e.g., 2s10s flattener).
        
        Constraint: exactly one of front_notional, back_notional, bpv must be provided.
        
        Risk weights determine the sign of each leg. E.g.:
        - risk_weights=[1, 1] and bpv=10k on back leg:
          front receives 10k notional with rw=1 (received)
          back pays with rw=-1 (paid)
        """
        assert sum(x is not None for x in (front_notional, back_notional, bpv)) == 1
        
        # Use _build_spreadable helper to solve for notionals
        leg0 = {"tenor": front_tenor, "fixed_rate": front_fixed_rate}
        leg1 = {"tenor": back_tenor, "fixed_rate": back_fixed_rate}
        
        if front_notional is not None:
            idx, cn, cp = 0, front_notional, None
        elif back_notional is not None:
            idx, cn, cp = 1, back_notional, None
        else:
            idx, cn, cp = 1, None, bpv  # bpv on back leg
        
        return (
            self._build_spreadable([leg0, leg1], risk_weights, idx, cn, cp),
            risk_weights,
        )

    def _build_fly(self, ...) -> Tuple[List[_IRSwapGenericObject], List[float]]:
        """Similar to _build_curve but with 3 legs."""
        ...

    def _build_spreadable(
        self,
        leg_specs: List[Dict[str, Any]],
        risk_weights: np.ndarray,
        constrained_leg_index: int,
        constrained_notional: Optional[float],
        constrained_bpv: Optional[float],
    ) -> List[_IRSwapGenericObject]:
        """
        Build a multi-leg structure with risk-weighted notionals.
        
        Uses linear algebra to solve for notionals given:
        - risk_weights: desired risk weight for each leg
        - constrained leg: one leg's notional or bpv is specified
        - pv01 values: computed for unit notional swaps
        
        The solver ensures: risk_weight[i] = notional[i] / bpv[i]
        """
        # Build unit notional swaps to get their PV01s
        unit_swaps = [self._leg(**spec, notional=1.0) for spec in leg_specs]
        bpvs = np.array([self.common_kwargs["curve"].pv01(s) for s in unit_swaps])
        
        # Solve for notionals
        notionals = linear_solve_for_risk_weighted_notionals(
            risk_weights=rw,
            bpvs=bpvs,
            constrained_leg_index=constrained_leg_index,
            constrained_leg_contribution=constrained_notional or constrained_bpv,
            contribution_is_bpv=(constrained_bpv is not None),
        )
        
        return [self._leg(**spec, notional=float(n)) 
                for spec, n in zip(leg_specs, notionals)]
```

### Value Maps: Computing Metrics

#### Purpose

A **ValueMap** computes metrics (NPV, PV01, RATE, etc.) on a concrete package of instruments.

#### Base Class

**File**: `/home/user/ARBS/Query/Base/BaseValue.py`

```python
class BaseValueFunctionMap(ABC, Generic[E, R]):
    """
    Generic value function builder: enum -> float (or other result type)
    
    E: Value enum (IRSwapValue, FixedRateBondValue)
    R: Return type (typically float)
    """

    def __init__(self, value_enum: Type[E], **common_kwargs: Any):
        self._value_enum = value_enum
        self.common_kwargs = common_kwargs  # curve/pricer, package, risk_weights
        self._map: Dict[E, Callable[..., R]] = self._create_map()

    @abstractmethod
    def _create_map(self) -> Dict[E, Callable[..., R]]:
        """Build the mapping: value_id -> calculation function."""
        ...

    def apply(self, value: E, **extra_kwargs: Any) -> R:
        """Apply the value function for the given metric."""
        if value not in self._map:
            raise KeyError(f"Value '{value}' is not supported.")
        func = self._map[value]
        kwargs = {**self.common_kwargs, **extra_kwargs}
        return func(**kwargs)
```

#### IRSwaps Value Map

**File**: `/home/user/ARBS/Query/IRSwaps/IRSwapValue.py`

```python
class IRSwapValue(Enum):
    RATE = auto()
    PV01 = auto()
    DV01 = auto()
    GAMMA_01 = auto()
    NPV = auto()
    NOTIONAL = auto()
    CARRY_BPS_RUNNING = auto()
    ROLL_BPS_RUNNING = auto()
    CARRY_AND_ROLL_BPS_RUNNING = auto()
    # ... more ...

class IRSwapValueFunctionMap(BaseValueFunctionMap[IRSwapValue, float]):
    def __init__(
        self,
        curve: _IRSwapGenericCurve,
        package: List[_IRSwapGenericObject],
        risk_weights: List[float],
    ):
        super().__init__(
            IRSwapValue,
            package=package,
            risk_weights=risk_weights,
            curve=curve,
        )

    def _create_map(self) -> Dict[IRSwapValue, Callable[..., float]]:
        return {
            IRSwapValue.RATE: self._rate,
            IRSwapValue.NPV: self._npv,
            IRSwapValue.PV01: self._pv01,
            IRSwapValue.DV01: self._dv01,
            IRSwapValue.GAMMA_01: self._gamma,
            IRSwapValue.NOTIONAL: self._notional,
            IRSwapValue.CARRY_BPS_RUNNING: self._carry_bps_running,
            # ... more ...
        }

    def _rate(self, **kwargs) -> float:
        """
        Fair swap rate (or spread rate for multi-leg structures).
        
        For CURVE (2-leg):
            rate = (rw[0] * fair_rate[0] + rw[1] * fair_rate[1]) * 10,000
        scaled to basis points.
        """
        return calc_spread_rate(
            kwargs["curve"], 
            kwargs["package"], 
            kwargs["risk_weights"]
        ) * _swap_structure_legs_mapper[len(kwargs["package"])][1]

    def _npv(self, **kwargs) -> float:
        """Mark-to-market NPV in USD."""
        curve = kwargs["curve"]
        return sum(curve.npv(s) for s in kwargs["package"])

    def _pv01(self, **kwargs) -> float:
        """Price value of 1 basis point (per unit notional)."""
        curve = kwargs["curve"]
        return sum(curve.pv01(s) for s in kwargs["package"])

    def _dv01(self, **kwargs) -> float:
        """Dollar value of 1 basis point (total notional)."""
        curve = kwargs["curve"]
        return sum(curve.dv01(s) for s in kwargs["package"])

    def _gamma(self, **kwargs) -> float:
        """Second-order interest rate sensitivity."""
        curve = kwargs["curve"]
        return sum(curve.gamma(s) for s in kwargs["package"])

    def _notional(self, **kwargs) -> float:
        """Total notional across all legs (with signs)."""
        curve = kwargs["curve"]
        return sum(
            np.copysign(curve.notional(s), curve.pv01(s))
            for s in kwargs["package"]
        )

    def _carry_bps_running(self, **kwargs) -> float:
        """Carry (accrued interest + drift) in basis points over horizon."""
        assert "horizon" in kwargs
        curve = kwargs["curve"]
        return sum(
            kwargs["risk_weights"][i] * curve.carry_bps_running(s, kwargs["horizon"])
            for i, s in enumerate(kwargs["package"])
        )
    
    # ... more value functions ...
```

---

## Generic Interfaces: Pricable & Pricer

### The Pricable Contract

**File**: `/home/user/ARBS/Query/Base/_GenericPricable.py`

```python
class _GenericPricable(ABC):
    """
    Marker interface for any priceable instrument.
    
    Product-specific subclasses:
    - _IRSwapGenericObject (represents QuantLib or RatesLib swap)
    - _FixedRateBondGenericPricable (represents bond)
    """
    pass
```

This is an **intentionally minimal** base class—a marker interface. Specific contracts are defined in product-specific abstract classes.

### The Pricer Contract

**File**: `/home/user/ARBS/Query/Base/_GenericPricer.py`

```python
class _GenericPricer(ABC, Generic[_GP]):
    """
    Abstract contract for any pricer/curve.
    
    Minimal interface:
    - npv(instrument) -> float
    - build_pricable(**kwargs) -> _GP
    - resolve_pricable(priceable, risk_weight) -> _GP
    """

    @abstractmethod
    def npv(self, instrument: _GP, /, **kwargs: Any) -> float:
        """Compute mark-to-market NPV."""
        ...

    @abstractmethod
    def build_pricable(self, /, **kwargs: Any) -> _GP:
        """Build a priceable from specifications."""
        ...

    @abstractmethod
    def resolve_pricable(
        self, 
        priceable: Generic[_GP], 
        risk_weight: Optional[float] = None
    ) -> _GP:
        """
        Optionally adjust the priceable (e.g., apply risk weight).
        """
        ...
```

### Product-Specific Extensions

#### IRSwap Pricable

**File**: `/home/user/ARBS/Query/IRSwaps/_IRSwapGenericObject.py`

```python
class _IRSwapGenericObject(_GenericPricable, ABC):
    """
    Contract for IR Swap instruments (backend-agnostic).
    
    Implemented by:
    - QuantLib: ql.VanillaSwap
    - RatesLib: rl.IRS
    """

    @abstractmethod
    def effective_date(self) -> datetime.date: ...
    
    @abstractmethod
    def maturity_date(self) -> datetime.date: ...
    
    @abstractmethod
    def fixed_rate(self) -> float:
        """Fixed leg rate in decimal (e.g., 0.025 for 2.5%)."""
        ...
    
    @abstractmethod
    def set_fixed_rate(self, rate_decimal: float) -> None: ...
    
    @abstractmethod
    def nominal(self) -> float:
        """Notional amount."""
        ...
    
    @abstractmethod
    def with_notional(self, notional: float) -> "_IRSwapGenericObject":
        """Return a copy with adjusted notional."""
        ...
    
    @abstractmethod
    def fair_rate(self) -> float:
        """Market-implied fair swap rate."""
        ...
    
    @abstractmethod
    def npv(self) -> float:
        """Mark-to-market NPV."""
        ...
    
    @abstractmethod
    def pv01(self) -> float:
        """Price value of 1 basis point."""
        ...
    
    @abstractmethod
    def dv01(self, shift: float = 1e-4) -> float:
        """Dollar value of 1 basis point (full notional)."""
        ...
    
    @abstractmethod
    def gamma(self, shift: float = 1e-4) -> float:
        """Second-order sensitivity."""
        ...
    
    @abstractmethod
    def carry_bps_running(self, horizon: str) -> float: ...
    
    @abstractmethod
    def roll_bps_running(self, horizon: str) -> float: ...
    
    @abstractmethod
    def carry_and_roll_bps_running(self, horizon: str) -> float: ...
```

#### IRSwap Pricer

**File**: `/home/user/ARBS/Query/IRSwaps/_IRSwapGenericCurve.py`

```python
class _IRSwapGenericCurve(_GenericPricer[_GenericPricable], ABC):
    """
    Contract for interest rate curve (backend-agnostic).
    
    Implemented by:
    - QuantLib: QLIRSwapCurve (wraps ql.YieldTermStructureHandle)
    - RatesLib: RLIRSwapCurve (wraps rl.Curve)
    """

    # Identity & context
    @abstractmethod
    def id(self) -> str:
        """Curve identifier (e.g., 'USD-SOFR-1D')."""
        ...
    
    @abstractmethod
    def reference_date(self) -> datetime.date: ...
    
    @abstractmethod
    def calendar(self) -> Any: ...
    
    @abstractmethod
    def calendar_advance(
        self, 
        dt1: datetime.date, 
        dt2: Union[str, Period]
    ) -> datetime.date:
        """Advance date by tenor (respects business conventions)."""
        ...
    
    @abstractmethod
    def handle(self) -> Any:
        """Backend-specific curve handle (ql.YieldTermStructureHandle or rl.Curve)."""
        ...
    
    @abstractmethod
    def index(self) -> Any:
        """Reference index (ql.SwapIndex or pd.Series of fixings)."""
        ...
    
    @abstractmethod
    def meta(self) -> Any:
        """Metadata (curve build info, timestamps, etc.)."""
        ...

    # Accessor methods (delegate to swap object)
    @abstractmethod
    def effective_date(self, irswap: _IRSwapGenericObject) -> datetime.date: ...
    
    @abstractmethod
    def maturity_date(self, irswap: _IRSwapGenericObject) -> datetime.date: ...
    
    @abstractmethod
    def fixed_rate(self, irswap: _IRSwapGenericObject) -> float: ...
    
    @abstractmethod
    def set_fixed_rate(
        self, 
        irswap: _IRSwapGenericObject, 
        rate_decimal: float
    ) -> None: ...
    
    @abstractmethod
    def notional(self, irswap: _IRSwapGenericObject) -> float: ...
    
    @abstractmethod
    def fair_rate(self, irswap: _IRSwapGenericObject) -> float: ...

    # Valuation methods
    @abstractmethod
    def npv(self, irswap: _IRSwapGenericObject) -> float: ...
    
    @abstractmethod
    def pv01(self, irswap: _IRSwapGenericObject) -> float: ...
    
    @abstractmethod
    def dv01(self, irswap: _IRSwapGenericObject, shift: float = 1e-4) -> float: ...
    
    @abstractmethod
    def gamma(self, irswap: _IRSwapGenericObject, shift: float = 1e-4) -> float: ...
    
    @abstractmethod
    def dollar_carry(self, irswap: _IRSwapGenericObject, horizon: str) -> float: ...
    
    @abstractmethod
    def carry_bps_running(self, irswap: _IRSwapGenericObject, horizon: str) -> float: ...
    
    @abstractmethod
    def roll_bps_running(self, irswap: _IRSwapGenericObject, horizon: str) -> float: ...
    
    @abstractmethod
    def carry_and_roll_bps_running(
        self, 
        irswap: _IRSwapGenericObject, 
        horizon: str
    ) -> float: ...

    # Instrument building
    @abstractmethod
    def build_irswap(
        self,
        fwd: Optional[str] = None,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
    ) -> _IRSwapGenericObject: ...
    
    @abstractmethod
    def build_stirf(
        self,
        fwd: Optional[str] = None,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
        is_ser: Optional[bool] = False,
    ) -> Any: ...

    # Query support
    @abstractmethod
    def nodes(self) -> Dict[datetime.date, float]: ...

    @abstractmethod
    def resolve_pricable(
        self, 
        irswap: _IRSwapGenericObject, 
        risk_weight: Optional[float] = None
    ) -> _IRSwapGenericObject: ...
```

#### Bond Pricable

**File**: `/home/user/ARBS/Query/FixedRateBonds/_FixedRateBondGenericPricable.py`

```python
class _FixedRateBondGenericPricable(_GenericPricable, ABC):
    """
    Contract for Fixed-Rate Bond instruments.
    """

    @abstractmethod
    def effective_date(self) -> datetime.date: ...

    @abstractmethod
    def maturity_date(self) -> datetime.date: ...

    @abstractmethod
    def coupon(self) -> float: ...

    @abstractmethod
    def nominal(self) -> float: ...

    @abstractmethod
    def ytm(self) -> float:
        """Yield-to-maturity."""
        ...

    @abstractmethod
    def dirty_price(self) -> float:
        """Price including accrued interest."""
        ...

    @abstractmethod
    def clean_price(self) -> float:
        """Price excluding accrued interest."""
        ...

    @abstractmethod
    def npv(self) -> float:
        """Mark-to-market NPV."""
        ...

    @abstractmethod
    def accured(self) -> float:
        """Accrued interest."""
        ...

    @abstractmethod
    def pv01(self) -> float:
        """Price value of 1 basis point."""
        ...

    @abstractmethod
    def mod_duration(self) -> float:
        """Modified duration."""
        ...

    @abstractmethod
    def convexity(self) -> float:
        """Bond convexity."""
        ...
```

---

## IRSwaps Implementation

### Overview

The IRSwaps product provides:
1. `IRSwapQuery`: User-facing query with tenor/curve/structure specification
2. `IRSwapStructure`: Enum for OUTRIGHT/CURVE/FLY
3. `IRSwapValue`: Enum for RATE/NPV/PV01/etc.
4. `IRSwapStructureFunctionMap`: Maps structure → concrete swaps
5. `IRSwapValueFunctionMap`: Maps value_id → metric calculations
6. `IRSProductAdapter`: Glue for the backtester
7. Backend implementations (QLIRSwapCurve, RLIRSwapCurve)

### IRSwapQuery Class

**File**: `/home/user/ARBS/Query/IRSwaps/IRSwapQuery.py`

```python
@dataclass(frozen=True)
class IRSwapQuery(BaseQuery):
    """
    IRS-specific Query entry point.

    User-facing args:
      - structure:    OUTRIGHT/CURVE/FLY
      - value:        RATE/NPV/PV01 (or list thereof)
      - tenor:        e.g., "10Y", "3M", "1D" for spot
      - effective_date, maturity_date: explicit date pair
      - is_mms:       True for matched-maturity swap (vs 2D spot)
      - curve:        curve name (e.g., "USD-SOFR-1D")
      - structure_kwargs: additional params for spreads/flies
      - risk_weight:  scalar multiplier

    Auto-fills BaseQuery fields:
      product="IRS"
      structure_id = structure
      structure_kwargs = union of tenor/dates/is_mms + user kwargs
      market_request = {'curve_name': curve, ...}
      value_id / value_ids from `value`
    """

    # User-facing fields
    structure: IRSwapStructure = IRSwapStructure.OUTRIGHT
    value: Union[IRSwapValue, List[IRSwapValue]] = IRSwapValue.RATE
    
    tenor: Optional[str] = None
    effective_date: Optional[datetime.date] = None
    maturity_date: Optional[datetime.date] = None
    is_mms: bool = False
    
    curve: Optional[str] = None
    
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    value_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    # Auto-filled by __post_init__
    product: str = field(init=False, default="IRS")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        """Normalize and validate query specification."""
        object.__setattr__(self, "product", "IRS")
        object.__setattr__(self, "structure_id", self.structure)
        
        # Validate by structure type
        if self.structure == IRSwapStructure.OUTRIGHT:
            assert (self.tenor or 
                   (self.effective_date and self.maturity_date) or 
                   self.is_mms), \
                "OUTRIGHT requires tenor OR (effective_date & maturity_date) OR is_mms=True"
        elif self.structure == IRSwapStructure.CURVE:
            assert ("front_tenor" in self.structure_kwargs and 
                   "back_tenor" in self.structure_kwargs), \
                "CURVE requires both leg tenors"
        elif self.structure == IRSwapStructure.FLY:
            assert ("front_tenor" in self.structure_kwargs and
                   "belly_tenor" in self.structure_kwargs and
                   "back_tenor" in self.structure_kwargs), \
                "FLY requires all three leg tenors"
        
        # Build normalized structure kwargs
        skw = dict(self.structure_kwargs or {})
        if self.tenor is not None and "tenor" not in skw:
            skw["tenor"] = self.tenor
        if self.effective_date is not None and "effective_date" not in skw:
            skw["effective_date"] = self.effective_date
        if self.maturity_date is not None and "maturity_date" not in skw:
            skw["maturity_date"] = self.maturity_date
        if self.is_mms and "is_mms" not in skw:
            skw["is_mms"] = True
        
        object.__setattr__(self, "structure_kwargs", skw)
        
        # Build market_request from curve
        mr = dict(self.market_request or {})
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)
        
        # Sync value_id / value_ids
        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())
```

### Usage Examples

#### Single Outright Swap

```python
q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    tenor="10Y",
    value=IRSwapValue.RATE,
    notional=1_000_000,
    curve="USD-SOFR-1D",
)

# Resolves to a single IRSwap with 1M notional
# Returns RATE in basis points (e.g., 4.50)
```

#### Curve Spread (2s10s)

```python
q = IRSwapQuery(
    structure=IRSwapStructure.CURVE,
    value=IRSwapValue.RATE,
    curve="USD-SOFR-1D",
    structure_kwargs={
        "front_tenor": "2Y",
        "back_tenor": "10Y",
        "bpv": 10_000,  # Constrain on back leg
        "risk_weights": [1.0, 1.0],  # Default: rec both
    },
)

# Resolves to 2-leg structure with notionals set
# such that back leg has ~10k BPV
```

#### Fly Spread (2s5s10s)

```python
q = IRSwapQuery(
    structure=IRSwapStructure.FLY,
    value=IRSwapValue.RATE,
    curve="USD-SOFR-1D",
    structure_kwargs={
        "front_tenor": "2Y",
        "belly_tenor": "5Y",
        "back_tenor": "10Y",
        "bpv": 10_000,
        "risk_weights": [1.0, -2.0, 1.0],  # Rec 2Y, Pay 5Y x2, Rec 10Y
    },
)

# Resolves to 3-leg structure
# RATE is weighted combination of fair rates across all legs
```

#### Arithmetic Composition

```python
short_end = IRSwapQuery(tenor="2Y", notional=1_000_000, curve="USD-SOFR-1D")
long_end = IRSwapQuery(tenor="10Y", notional=1_000_000, curve="USD-SOFR-1D")

curve_flattener = short_end - long_end
# Result: [2Y with weight 1.0, 10Y with weight -1.0]

weighted_short = short_end * 1.5
# Result: 2Y with weight 1.5
```

---

## FixedRateBonds Implementation

### Overview

The FixedRateBonds product provides analogous structure to IRSwaps:
1. `FixedRateBondQuery`: User-facing query with CUSIP specification
2. `FixedRateBondStructure`: Enum for OUTRIGHT/CURVE/FLY
3. `FixedRateBondValue`: Enum for YTM/CLEAN_PRICE/NPV/PV01/etc.
4. Backend implementations (QLFixedRateBondPricer, RLFixedRateBondPricer)

### FixedRateBondQuery Class

**File**: `/home/user/ARBS/Query/FixedRateBonds/FixedRateBondQuery.py`

```python
@dataclass(frozen=True)
class FixedRateBondQuery(BaseQuery):
    """
    Fixed-Rate Bond-specific Query entry point.

    User-facing args:
      - structure:  OUTRIGHT/CURVE/FLY
      - value:      YTM/CLEAN_PRICE/NPV/PV01 (or list thereof)
      - cusip:      9-digit CUSIP code
      - curve:      MDP source (e.g., "UST-DATA")
      - structure_kwargs: additional params for spreads/flies

    Auto-fills BaseQuery fields:
      product="FRB"
      structure_id = structure
      structure_kwargs = union of cusip + user kwargs
      market_request = {'curve_name': curve, ...}
      value_id / value_ids from `value`
    """

    structure: FixedRateBondStructure = FixedRateBondStructure.OUTRIGHT
    value: Union[FixedRateBondValue, List[FixedRateBondValue]] = FixedRateBondValue.YTM
    
    cusip: Optional[str] = None
    curve: Optional[str] = None
    
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="FRB")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        """Normalize and populate BaseQuery fields."""
        skw = dict(self.structure_kwargs or {})
        if self.cusip is not None and "cusip" not in skw:
            skw["cusip"] = self.cusip

        object.__setattr__(self, "product", "FRB")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "structure_kwargs", skw)

        mr = dict(self.market_request or {})
        if self.curve is not None and "curve_name" not in mr:
            mr["curve_name"] = self.curve
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())
```

### FixedRateBondValue Enum

```python
class FixedRateBondValue(Enum):
    YTM = auto()              # Yield to maturity
    CLEAN_PRICE = auto()      # Price without accrued interest
    DIRTY_PRICE = auto()      # Price with accrued interest
    NPV = auto()              # Mark-to-market PnL
    PV01 = auto()             # Basis point value (per unit notional)
    DV01 = auto()             # Dollar value of 1bp (full notional)
    MOD_DURATION = auto()     # Modified duration
    CONVEXITY = auto()        # Convexity
```

### Bond Structure Building

**File**: `/home/user/ARBS/Query/FixedRateBonds/FixedRateBondStructure.py`

Similar pattern to IRSwaps but works with a **pricer dict** (one pricer per bond):

```python
class FixedRateBondStructureFunctionMap(
    BaseStructureFunctionMap[FixedRateBondStructure, _FixedRateBondGenericPricable]
):
    def __init__(self, pricer: Dict[str, _FixedRateBondGenericPricer]):
        """
        Args:
            pricer: dict mapping CUSIP -> pricer instance
                    (QLFixedRateBondPricer or RLFixedRateBondPricer)
        """
        super().__init__(FixedRateBondStructure, pricer=pricer)

    def _build_outright(
        self, 
        notional: Optional[float] = None, 
        bpv: Optional[float] = None, 
        **_
    ) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:
        """
        Build a single bond.
        
        Extract the single CUSIP from pricer dict and build bond.
        """
        cusip = next(iter(self.common_kwargs["pricer"]))
        pricer = self.common_kwargs["pricer"][cusip]
        bond = self._leg(
            cusip=cusip,
            issue_date=pricer.issue_date(),
            maturity_date=pricer.maturity_date(),
            cpn=pricer.coupon(),
            notional=notional,
            bpv=bpv,
        )
        weight = 1.0 if pricer.notional(bond) > 0 else -1.0
        return [bond], [weight]

    def _build_curve(
        self,
        front_notional: Optional[float] = None,
        back_notional: Optional[float] = None,
        bpv: Optional[float] = None,
        risk_weights: List[float] = [1.0, 1.0],
        **_,
    ) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:
        """
        Build a 2-bond curve spread (e.g., 5Y vs 10Y).
        
        Similar logic to IRSwap CURVE.
        """
        pricers = self.common_kwargs["pricer"]
        cusips = list(pricers.keys())
        assert len(cusips) == 2
        
        # Extract bond specs from pricers
        leg0 = {
            "cusip": cusips[0],
            "issue_date": pricers[cusips[0]].issue_date(),
            "maturity_date": pricers[cusips[0]].maturity_date(),
            "cpn": pricers[cusips[0]].coupon(),
        }
        leg1 = {...}  # similar
        
        # Solve for notionals using _build_spreadable
        return (
            self._build_spreadable(
                [leg0, leg1],
                risk_weights=risk_weights,
                constrained_leg_index=idx,
                constrained_notional=cn,
                constrained_bpv=cp,
            ),
            risk_weights,
        )

    def _build_fly(...) -> Tuple[List[_FixedRateBondGenericPricable], List[float]]:
        """Similar to CURVE but with 3 bonds."""
        ...
```

---

## Backend Abstraction Layer

### Philosophy

Two independent pricing libraries are wrapped behind generic interfaces:
- **QuantLib**: `QLIRSwapCurve`, `QLFixedRateBondPricer`
- **RatesLib**: `RLIRSwapCurve`, `RLFixedRateBondPricer`

The backtester is completely unaware of the backend choice.

### QuantLib Backend (IRSwaps)

**File**: `/home/user/ARBS/Query/IRSwaps/backends/quantlib/QLIRSwapCurve.py`

```python
@dataclass
class QLIRSwapCurve(_IRSwapGenericCurve):
    """Wraps QuantLib pricing infrastructure."""
    
    _ql_curve_id: str
    _ql_curve_handle: ql.YieldTermStructureHandle
    _ql_curve_index: ql.SwapIndex
    _meta_data: Any

    def __init__(
        self, 
        ql_curve_id: str, 
        ql_curve_handle: ql.YieldTermStructureHandle, 
        ql_curve_index: ql.SwapIndex, 
        meta_data: Any
    ):
        self._ql_curve_id = ql_curve_id
        self._ql_curve_handle = ql_curve_handle
        self._ql_curve_index = ql_curve_index
        self._meta_data = meta_data

    def id(self) -> str:
        return self._ql_curve_id

    def reference_date(self) -> datetime.date:
        return ql_date_to_pydate(self._ql_curve_handle.referenceDate())

    def fair_rate(self, irswap: ql.VanillaSwap) -> float:
        """Delegate to QuantLib's fair rate calculation."""
        return ql_irswaps_pricer.calc_fair_rate(
            swap=irswap, 
            curve_handle=self._ql_curve_handle
        )

    def npv(self, irswap: ql.VanillaSwap) -> float:
        """Delegate to QuantLib."""
        return ql_irswaps_pricer.calc_npv(
            swap=irswap, 
            curve_handle=self._ql_curve_handle
        )

    def pv01(self, irswap: ql.VanillaSwap) -> float:
        """Delegate to QuantLib."""
        return ql_irswaps_pricer.calc_pv01(
            swap=irswap, 
            curve_handle=self._ql_curve_handle
        )

    def build_irswap(
        self,
        fwd: Optional[str] = None,
        tenor: Optional[str] = None,
        effective_date: Optional[datetime.date] = None,
        maturity_date: Optional[datetime.date] = None,
        fixed_rate: Optional[float] = -0.00,
        notional: Optional[float] = None,
        bpv: Optional[float] = None,
    ) -> ql.VanillaSwap:
        """Build a QuantLib VanillaSwap."""
        return ql_irswaps_pricer.build_ql_irswap(
            curve=self._ql_curve_id,
            curve_handle=self._ql_curve_handle,
            swap_index=self._ql_curve_index,
            fwd=fwd,
            tenor=tenor,
            effective_date=effective_date,
            maturity_date=maturity_date,
            fixed_rate=fixed_rate,
            notional=notional,
            bpv=bpv,
        )
```

### RatesLib Backend (IRSwaps)

**File**: `/home/user/ARBS/Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py`

```python
@dataclass
class RLIRSwapCurve(_IRSwapGenericCurve):
    """Wraps RatesLib pricing infrastructure."""
    
    _rl_curve_id: str
    _rl_curve_handle: rl.Curve
    _fixings: pd.Series
    _meta_data: Any

    def __init__(
        self, 
        rl_curve_id: str, 
        rl_curve_handle: rl.Curve, 
        fixings: pd.Series, 
        meta_data: Any
    ):
        self._rl_curve_id = rl_curve_id
        self._rl_curve_handle = rl_curve_handle
        self._fixings = fixings
        self._meta_data = meta_data

    def id(self) -> str:
        return self._rl_curve_id

    def reference_date(self) -> datetime.date:
        return next(iter(self._rl_curve_handle.nodes.nodes.keys()))

    def fair_rate(self, irswap: rl.IRS) -> float:
        """Delegate to RatesLib."""
        return irswap.rate(curves=self._rl_curve_handle).real / 100

    def npv(self, irswap: rl.IRS) -> float:
        """Delegate to RatesLib."""
        fair = self.fair_rate(irswap)
        at_par = rl.IRS(
            effective=self.effective_date(irswap),
            termination=self.maturity_date(irswap),
            fixed_rate=fair * 100,
            curves=self._rl_curve_handle,
            spec=RATESLIB_CURVE_DEFINITIONS[self._rl_curve_id]["ReferenceRate"],
            notional=self.notional(irswap),
        )
        return at_par.npv(curves=self._rl_curve_handle).real

    def pv01(self, irswap: rl.IRS) -> float:
        """Delegate to RatesLib."""
        return irswap.analytic_delta(curve=self._rl_curve_handle).real
```

### QuantLib Bond Pricer

**File**: `/home/user/ARBS/Query/FixedRateBonds/backends/quantlib/QLFixedRateBondPricer.py`

```python
@dataclass
class QLFixedRateBondPricer(_FixedRateBondGenericPricer):
    """Wraps QuantLib bond pricing."""
    
    _ql_frb_id: str
    _reference_date: datetime.date
    _issue_date: datetime.date
    _maturity_date: datetime.date
    _cpn: float
    _notional: Optional[float] = None
    _clean_price: Optional[float] = None
    _ytm: Optional[float] = None
    _meta_data: Any = None

    def __init__(
        self,
        ql_frb_id: str,
        reference_date: Union[datetime.datetime, datetime.date],
        issue_date: Union[datetime.datetime, datetime.date],
        maturity_date: Union[datetime.datetime, datetime.date],
        cpn: float,
        notional: Optional[float] = None,
        clean_price: Optional[float] = None,
        ytm: Optional[float] = None,
        meta_data: Optional[Any] = None,
    ):
        assert clean_price is None or ytm is None
        self._ql_frb_id = ql_frb_id
        self._reference_date = reference_date
        self._issue_date = issue_date
        self._maturity_date = maturity_date
        self._cpn = cpn
        self._notional = notional
        self._clean_price = clean_price
        self._ytm = ytm
        self._meta_data = meta_data

    def build_schedule(self) -> ql.Schedule:
        """Build QuantLib coupon schedule."""
        return ql.Schedule(
            datetime_to_ql_date(self.issue_date()),
            datetime_to_ql_date(self.maturity_date()),
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["FrequencyPeriod"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["Calendar"],
            QUANTLIB_FRB_DEFINITIONS[self._ql_frb_id]["BusinessConvention"],
            # ...
        )
    
    def ytm(self) -> float:
        if self._ytm is not None:
            return self._ytm
        # Compute from clean_price using QuantLib
        # ... complex bond math ...
        
    def npv(self, notional: Optional[float] = None) -> float:
        # Compute price * notional
        ...
```

### RatesLib Bond Pricer

**File**: `/home/user/ARBS/Query/FixedRateBonds/backends/rateslib/RLFixedRateBondPricer.py`

Similar structure but delegates to RatesLib instead:

```python
@dataclass
class RLFixedRateBondPricer(_FixedRateBondGenericPricer):
    """Wraps RatesLib bond pricing."""
    
    # ... similar fields ...
    
    def build_schedule(self) -> rl.Schedule:
        """Build RatesLib coupon schedule."""
        return rl.FixedRateBond(
            self._to_rl_dt(self.issue_date()),
            self._to_rl_dt(self.maturity_date()),
            spec=RATESLIB_FRB_DEFINITIONS[self._rl_frb_id]["spec"],
            fixed_rate=self.coupon(),
        ).kwargs["schedule"]
    
    def ytm(self) -> float:
        """Delegate to RatesLib."""
        if self._ytm is not None:
            return self._ytm
        return rl.FixedRateBond(...).ytm(
            price=self.clean_price(),
            dirty=False,
            settlement=self.calendar_advance(...),
        )
```

### Definitions Maps

Backend-specific configuration is stored in definitions maps:

**QuantLib**:
```python
# Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py
QUANTLIB_CURVE_DEFINITIONS = {
    "USD-SOFR-1D": {
        "Calendar": ql.UnitedStates(ql.UnitedStates.FederalReserve),
        "BusinessConvention": ql.ModifiedFollowing,
        "DayCount": ql.Actual360(),
        # ...
    },
    # ... more curves ...
}

# Query/FixedRateBonds/backends/quantlib/ql_frb_definitions_map.py
QUANTLIB_FRB_DEFINITIONS = {
    "UST": {
        "Calendar": ql.UnitedStates(ql.UnitedStates.Settlement),
        "FrequencyPeriod": ql.Period(6, ql.Months),
        "BusinessConvention": ql.Unadjusted,
        # ...
    },
}
```

**RatesLib**:
```python
# Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py
RATESLIB_CURVE_DEFINITIONS = {
    "USD-SOFR-1D": {
        "Calendar": rl.Cal.NEW_YORK,
        "BusinessConvention": rl.BusDayConvention.ModFollowing,
        # ...
    },
}

# Query/FixedRateBonds/backends/rateslib/rl_frb_definitions_map.py
RATESLIB_FRB_DEFINITIONS = {
    "UST": {
        "spec": "USD_UST",
        # ...
    },
}
```

---

## Query Resolution Pipeline

### Complete Workflow

Here's the end-to-end flow of how a query becomes a valued position:

```
User Code:
  q = IRSwapQuery(tenor="10Y", notional=1M, curve="USD-SOFR-1D", value=IRSwapValue.NPV)
       ↓
Backtester (per timestep):
  1. req = q.build_mdp_request(now)
       → {"curve_name": "USD-SOFR-1D", "timestamp": date(2024, 1, 15)}
  
  2. pricer_or_curve = mdp.get_pricer(req)
       → QLIRSwapCurve (or RLIRSwapCurve)
  
  3. q_edited = q._edited(pricer_or_curve)
       → adapter.edit_query(q, pricer_or_curve)
       → may resolve MMS aliases to explicit dates
  
  4. package, weights = q_edited.resolve_package(pricer_or_curve=pricer_or_curve)
       → adapter.build_structure_map(pricer_or_curve)
       → returns IRSwapStructureFunctionMap
       → struct_map.apply(IRSwapStructure.OUTRIGHT, tenor="10Y", notional=1M)
       → returns ([IRSwap(10Y, 1M notional)], [1.0])
  
  5. value_map = q_edited.build_value_map(
       pricer_or_curve=pricer_or_curve,
       package=package,
       risk_weights=weights
     )
       → adapter.build_value_map(...)
       → returns IRSwapValueFunctionMap(curve, package, weights)
  
  6. result = value_map.apply(IRSwapValue.NPV)
       → value_map._npv(curve=pricer_or_curve, package=[swap], risk_weights=[1.0])
       → return pricer_or_curve.npv(swap)
       → returns float: e.g., 45,234.56 (mark-to-market PnL)

Result: npv = 45,234.56
```

### Key Data Flows

#### Flow 1: Building Structure Maps

```python
def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
    """
    Creates a callable that maps structure_id -> (package, weights).
    
    The structure map "remembers" the pricer/curve, so later calls
    to apply() can use it without re-passing the backend object.
    """
    # IRSProductAdapter.build_structure_map
    return IRSwapStructureFunctionMap(curve=pricer_or_curve)
    # ↓
    # IRSwapStructureFunctionMap.__init__ stores curve in common_kwargs
    # Later: struct_map.apply(structure_id, **params) merges common + params
```

#### Flow 2: Resolving Structures

```python
def apply(self, structure: E, **builder_kwargs: Any) -> Tuple[List[T], List[float]]:
    """
    Maps structure_id + params to concrete priceables + weights.
    """
    if structure not in self._map:
        raise KeyError(...)
    
    builder = self._map[structure]
    # Merge common kwargs (curve/pricer) with user-supplied (tenor, notional, etc.)
    kwargs = {**self.common_kwargs, **builder_kwargs}
    
    # Call the builder function
    return builder(**kwargs)
    # ↓
    # For IRSwaps OUTRIGHT:
    # self._build_outright(
    #   curve=self.common_kwargs["curve"],
    #   tenor="10Y", notional=1M, fixed_rate=-0, is_for_timeseries=False
    # )
    # ↓
    # Create the swap via curve.build_irswap(...)
    # Return ([swap], [1.0])
```

#### Flow 3: Computing Values

```python
def apply(self, value: E, **extra_kwargs: Any) -> R:
    """
    Maps value_id to a computation function.
    """
    if value not in self._map:
        raise KeyError(...)
    
    func = self._map[value]
    kwargs = {**self.common_kwargs, **extra_kwargs}
    # common_kwargs = {curve, package, risk_weights}
    # extra_kwargs = {} (typically)
    
    return func(**kwargs)
    # ↓
    # For IRSwaps NPV:
    # self._npv(curve=pricer, package=[swap], risk_weights=[1.0])
    # ↓
    # return sum(curve.npv(s) for s in package)
```

---

## Extension Guide: Adding New Products

### Step-by-Step: Adding a Swaption Product

Let's walk through adding support for **Swaptions** to the system.

#### 1. Define Structure & Value Enums

Create `/home/user/ARBS/Query/Swaptions/SwaptionStructure.py`:

```python
from enum import Enum, auto

class SwaptionStructure(Enum):
    SINGLE = auto()        # Single swaption
    STRADDLE = auto()      # Long call + short put (or vice versa)
    STRANGLE = auto()      # Call spread
    COLLAR = auto()        # Call spread + put spread
```

Create `/home/user/ARBS/Query/Swaptions/SwaptionValue.py`:

```python
from enum import Enum, auto

class SwaptionValue(Enum):
    PRICE = auto()         # USD price per 1000 notional (convention)
    IMPLIED_VOL = auto()   # Black model implied volatility
    VEGA = auto()          # DV/D(vol)
    THETA = auto()         # Time decay
    DELTA = auto()         # DV/D(swap_rate)
    GAMMA = auto()         # D²V/D(swap_rate)²
```

#### 2. Define Generic Pricable & Pricer Interfaces

Create `/home/user/ARBS/Query/Swaptions/_SwaptionGenericObject.py`:

```python
from abc import ABC, abstractmethod
import datetime
from Query.Base._GenericPricable import _GenericPricable

class _SwaptionGenericObject(_GenericPricable, ABC):
    """
    Contract for Swaption instruments (backend-agnostic).
    
    Implementations:
    - QL: ql.Swaption
    - RL: rl.Swaption
    """
    
    @abstractmethod
    def settlement_date(self) -> datetime.date: ...
    
    @abstractmethod
    def expiry_date(self) -> datetime.date: ...
    
    @abstractmethod
    def swap_tenor(self) -> str: ...
    
    @abstractmethod
    def swap_notional(self) -> float: ...
    
    @abstractmethod
    def strike_rate(self) -> float: ...
    
    @abstractmethod
    def is_payer(self) -> bool: ...
    
    @abstractmethod
    def price(self, implied_vol: float) -> float:
        """Price the swaption at given implied vol."""
        ...
    
    @abstractmethod
    def implied_vol(self, price: float) -> float:
        """Compute implied vol from price."""
        ...
    
    @abstractmethod
    def vega(self, implied_vol: float) -> float: ...
    
    @abstractmethod
    def delta(self, implied_vol: float) -> float: ...
```

Create `/home/user/ARBS/Query/Swaptions/_SwaptionGenericPricer.py`:

```python
from abc import ABC, abstractmethod
import datetime
from Query.Base._GenericPricer import _GenericPricer
from Query.Swaptions._SwaptionGenericObject import _SwaptionGenericObject

class _SwaptionGenericPricer(_GenericPricer[_SwaptionGenericObject], ABC):
    """
    Contract for volatility surface (backend-agnostic).
    """
    
    @abstractmethod
    def id(self) -> str:
        """Surface identifier (e.g., 'USD-SWAPTION-VOL')."""
        ...
    
    @abstractmethod
    def reference_date(self) -> datetime.date: ...
    
    @abstractmethod
    def build_swaption(
        self,
        settlement: datetime.date,
        expiry: datetime.date,
        swap_tenor: str,
        strike_rate: float,
        notional: float,
        payer: bool,
    ) -> _SwaptionGenericObject: ...
    
    @abstractmethod
    def price(self, swaption: _SwaptionGenericObject) -> float: ...
    
    @abstractmethod
    def implied_vol(self, swaption: _SwaptionGenericObject) -> float: ...
    
    @abstractmethod
    def vega(self, swaption: _SwaptionGenericObject) -> float: ...
```

#### 3. Define Query Class

Create `/home/user/ARBS/Query/Swaptions/SwaptionQuery.py`:

```python
from dataclasses import dataclass, field, replace
import datetime
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.Swaptions.SwaptionStructure import SwaptionStructure
from Query.Swaptions.SwaptionValue import SwaptionValue

@dataclass(frozen=True)
class SwaptionQuery(BaseQuery):
    """
    Swaption-specific Query.
    """
    
    structure: SwaptionStructure = SwaptionStructure.SINGLE
    value: Union[SwaptionValue, List[SwaptionValue]] = SwaptionValue.PRICE
    
    settlement_date: Optional[datetime.date] = None
    expiry_date: Optional[datetime.date] = None
    expiry_tenor: Optional[str] = None  # e.g., "3M", "6M", "1Y"
    
    swap_tenor: Optional[str] = None  # e.g., "10Y"
    strike_rate: Optional[float] = None
    payer: bool = True
    
    notional: Optional[float] = None
    implied_vol: Optional[float] = None  # For pricing (if not on surface)
    
    curve: Optional[str] = None
    vol_surface: Optional[str] = None
    
    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None
    
    product: str = field(init=False, default="SWAPTION")
    structure_id: Any = field(init=False, default=None)
    
    def __post_init__(self):
        """Normalize and validate."""
        assert (self.expiry_date or self.expiry_tenor), \
            "Must specify expiry_date OR expiry_tenor"
        assert self.swap_tenor, "Must specify swap_tenor"
        assert self.strike_rate is not None, "Must specify strike_rate"
        assert self.notional, "Must specify notional"
        
        skw = dict(self.structure_kwargs or {})
        # ... normalize fields ...
        
        object.__setattr__(self, "product", "SWAPTION")
        object.__setattr__(self, "structure_id", self.structure)
        object.__setattr__(self, "structure_kwargs", skw)
        
        # ... sync market_request, value_id/value_ids ...
    
    def return_query(self) -> List["SwaptionQuery"]:
        if isinstance(self.value, list):
            return [replace(self, value=v) for v in self.value]
        return [self]
    
    def col_name(self, cube_name: Optional[str] = None) -> str:
        return f"{self.expiry_tenor}x{self.swap_tenor} {self.strike_rate*100:.2f}% Swaption"
    
    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"
```

#### 4. Implement Structure Map

Create `/home/user/ARBS/Query/Swaptions/SwaptionStructure.py` (structure builder):

```python
from functools import partial
from typing import Dict, Callable, List, Tuple, Any

from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.Swaptions._SwaptionGenericObject import _SwaptionGenericObject

class SwaptionStructureFunctionMap(
    BaseStructureFunctionMap[SwaptionStructure, _SwaptionGenericObject]
):
    """Maps SwaptionStructure enum to concrete swaption packages."""
    
    def __init__(self, vol_surface: Any):
        """
        Args:
            vol_surface: A volatility surface (_SwaptionGenericPricer)
        """
        super().__init__(SwaptionStructure, vol_surface=vol_surface)
        self._map = self._create_map()
    
    def _create_map(self) -> Dict[SwaptionStructure, Callable[...]]:
        return {
            SwaptionStructure.SINGLE: partial(self._build_single),
            SwaptionStructure.STRADDLE: partial(self._build_straddle),
            SwaptionStructure.STRANGLE: partial(self._build_strangle),
            SwaptionStructure.COLLAR: partial(self._build_collar),
        }
    
    def _build_single(
        self,
        settlement_date: Optional[datetime.date],
        expiry_date: Optional[datetime.date],
        expiry_tenor: Optional[str],
        swap_tenor: str,
        strike_rate: float,
        payer: bool,
        notional: float,
        **_,
    ) -> Tuple[List[_SwaptionGenericObject], List[float]]:
        """Build a single swaption."""
        vol_surface = self.common_kwargs["vol_surface"]
        
        # Resolve expiry
        if expiry_date is None:
            expiry_date = vol_surface.calendar_advance(
                vol_surface.reference_date(), 
                expiry_tenor
            )
        
        # Build swaption
        swaption = vol_surface.build_swaption(
            settlement=vol_surface.reference_date(),
            expiry=expiry_date,
            swap_tenor=swap_tenor,
            strike_rate=strike_rate,
            notional=notional,
            payer=payer,
        )
        
        return [swaption], [1.0]
    
    def _build_straddle(
        self,
        # ... similar args ...
        **_,
    ) -> Tuple[List[_SwaptionGenericObject], List[float]]:
        """Build a straddle: long call + long put at same strike."""
        receiver = self._build_single(
            # ..., payer=False (receiver swaption)
        )
        payer = self._build_single(
            # ..., payer=True (payer swaption)
        )
        # Combine
        return receiver[0] + payer[0], [1.0, 1.0]
```

#### 5. Implement Value Map

Create `/home/user/ARBS/Query/Swaptions/SwaptionValue.py` (value calculator):

```python
from typing import Dict, Callable, Any

from Query.Base.BaseValue import BaseValueFunctionMap
from Query.Swaptions.SwaptionValue import SwaptionValue

class SwaptionValueFunctionMap(BaseValueFunctionMap[SwaptionValue, float]):
    """Maps SwaptionValue enum to metric calculations."""
    
    def __init__(
        self,
        vol_surface: Any,
        package: List[_SwaptionGenericObject],
        risk_weights: List[float],
    ):
        super().__init__(
            SwaptionValue,
            vol_surface=vol_surface,
            package=package,
            risk_weights=risk_weights,
        )
    
    def _create_map(self) -> Dict[SwaptionValue, Callable[..., float]]:
        return {
            SwaptionValue.PRICE: self._price,
            SwaptionValue.IMPLIED_VOL: self._implied_vol,
            SwaptionValue.VEGA: self._vega,
            SwaptionValue.DELTA: self._delta,
            SwaptionValue.THETA: self._theta,
        }
    
    def _price(self, **kwargs) -> float:
        """Total price of the swaption package."""
        vol_surface = kwargs["vol_surface"]
        return sum(
            kwargs["risk_weights"][i] * vol_surface.price(s)
            for i, s in enumerate(kwargs["package"])
        )
    
    def _implied_vol(self, **kwargs) -> float:
        """Average implied vol."""
        vol_surface = kwargs["vol_surface"]
        vols = [vol_surface.implied_vol(s) for s in kwargs["package"]]
        return sum(v for v in vols) / len(vols)
    
    def _vega(self, **kwargs) -> float:
        """Total vega (DV/D(vol))."""
        vol_surface = kwargs["vol_surface"]
        return sum(
            kwargs["risk_weights"][i] * vol_surface.vega(s)
            for i, s in enumerate(kwargs["package"])
        )
    
    # ... more value functions ...
```

#### 6. Implement Product Adapter

Create `/home/user/ARBS/Query/Swaptions/adapter.py`:

```python
from typing import Any, List

from Query.Base.product_adapter import ProductAdapter, register_product
from Query.Base._GenericPricable import _GenericPricable
from Query.Swaptions.SwaptionStructure import SwaptionStructureFunctionMap
from Query.Swaptions.SwaptionValue import SwaptionValueFunctionMap

class SwaptionProductAdapter(ProductAdapter):
    """Adapter for swaptions."""
    
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        # pricer_or_curve is a vol_surface (_SwaptionGenericPricer)
        return SwaptionStructureFunctionMap(vol_surface=pricer_or_curve)
    
    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
    ) -> Any:
        return SwaptionValueFunctionMap(
            vol_surface=pricer_or_curve,
            package=package,
            risk_weights=risk_weights,
        )
    
    def edit_query(self, *, q, pricer_or_curve):
        # No special editing for swaptions
        return q

# Register on import
register_product("SWAPTION", SwaptionProductAdapter)
```

#### 7. Implement Backend Wrappers

Create `/home/user/ARBS/Query/Swaptions/backends/quantlib/QLSwaptionVolSurface.py`:

```python
import QuantLib as ql
import datetime
from dataclasses import dataclass
from typing import Any, Optional

from Query.Swaptions._SwaptionGenericPricer import _SwaptionGenericPricer

@dataclass
class QLSwaptionVolSurface(_SwaptionGenericPricer):
    """Wraps QuantLib swaption vol surface."""
    
    _ql_surface_id: str
    _ql_surface_handle: ql.SwaptionVolatilityStructureHandle
    _meta_data: Any
    
    def __init__(
        self,
        ql_surface_id: str,
        ql_surface_handle: ql.SwaptionVolatilityStructureHandle,
        meta_data: Any,
    ):
        self._ql_surface_id = ql_surface_id
        self._ql_surface_handle = ql_surface_handle
        self._meta_data = meta_data
    
    def id(self) -> str:
        return self._ql_surface_id
    
    def reference_date(self) -> datetime.date:
        return ql_date_to_pydate(self._ql_surface_handle.referenceDate())
    
    def build_swaption(
        self,
        settlement: datetime.date,
        expiry: datetime.date,
        swap_tenor: str,
        strike_rate: float,
        notional: float,
        payer: bool,
    ) -> ql.Swaption:
        """Build a QuantLib Swaption."""
        # ... create ql.Swaption ...
    
    def price(self, swaption: ql.Swaption) -> float:
        # Delegate to QL
        ...
```

Similar for RatesLib backend.

#### 8. Usage

```python
from Query.Swaptions import SwaptionQuery, SwaptionStructure, SwaptionValue

q = SwaptionQuery(
    structure=SwaptionStructure.SINGLE,
    expiry_tenor="3M",
    swap_tenor="10Y",
    strike_rate=0.045,
    payer=True,
    notional=1_000_000,
    vol_surface="USD-SWAPTION-VOL",
)

# Backtester auto-handles it!
# 1. Adapter lookup: get_adapter("SWAPTION") → SwaptionProductAdapter
# 2. Build structures: swaptionstructureFunctionMap.apply(...)
# 3. Build values: SwaptionValueFunctionMap.apply(SwaptionValue.PRICE)
# 4. Return result
```

---

## API Reference

### BaseQuery

**Location**: `Query/Base/BaseQuery.py`

| Method | Signature | Returns | Purpose |
|--------|-----------|---------|---------|
| `build_mdp_request` | `(now: datetime.datetime) -> Dict[str, Any]` | Dict | Build MDP request for time `now` |
| `resolve_package` | `(pricer_or_curve, **hints) -> Tuple[List[_GenericPricable], List[float]]` | (package, weights) | Resolve query into instruments + weights |
| `build_value_map` | `(pricer_or_curve, package, risk_weights) -> Any` | ValueMap | Build value map for metrics |
| `_edited` | `(pricer_or_curve) -> BaseQuery` | Query | Run adapter's edit pass |
| `signature` | `() -> str` | str | Stable identifier for logging |
| `default_mtm_value_id` | `() -> Any` | Enum | Primary value metric |
| `return_query` | `() -> Union[BaseQuery, List[BaseQuery]]` | Query(ies) | Expand multi-value queries |
| `col_name` | `(cube_name: Optional[str]) -> str` | str | Human-friendly label |
| `eval_expression` | `(cube_name: Optional[str]) -> str` | str | Spreadsheet expression |

### IRSwapQuery

**Location**: `Query/IRSwaps/IRSwapQuery.py`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `structure` | `IRSwapStructure` | OUTRIGHT | Structure type |
| `value` | `Union[IRSwapValue, List]` | RATE | Value metric(s) |
| `tenor` | `Optional[str]` | None | Swap tenor (e.g., "10Y") |
| `effective_date` | `Optional[datetime.date]` | None | Start date |
| `maturity_date` | `Optional[datetime.date]` | None | End date |
| `is_mms` | `bool` | False | Matched-maturity swap flag |
| `curve` | `Optional[str]` | None | Curve name for MDP |
| `structure_kwargs` | `Dict[str, Any]` | `{}` | Additional build params |
| `risk_weight` | `Optional[float]` | None | Position scaling |

**IRSwapStructure Enum**:
- `OUTRIGHT`: Single swap
- `CURVE`: 2-leg spread
- `FLY`: 3-leg spread
- `SPREAD`: Alias for OUTRIGHT

**IRSwapValue Enum**:
- `RATE`: Fair swap rate (bps)
- `NPV`: Mark-to-market PnL (USD)
- `PV01`: Basis point value (USD per bp)
- `DV01`: Dollar value of 1bp (full notional)
- `GAMMA_01`: Second-order sensitivity
- `NOTIONAL`: Total notional (signed)
- `CARRY_BPS_RUNNING`: Carry in bps over horizon
- `ROLL_BPS_RUNNING`: Rolldown in bps
- `CARRY_AND_ROLL_BPS_RUNNING`: Combined
- And more...

### FixedRateBondQuery

**Location**: `Query/FixedRateBonds/FixedRateBondQuery.py`

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `structure` | `FixedRateBondStructure` | OUTRIGHT | Structure type |
| `value` | `Union[FixedRateBondValue, List]` | YTM | Value metric(s) |
| `cusip` | `Optional[str]` | None | 9-digit CUSIP code |
| `curve` | `Optional[str]` | None | MDP source |
| `structure_kwargs` | `Dict[str, Any]` | `{}` | Additional build params |
| `risk_weight` | `Optional[float]` | None | Position scaling |

**FixedRateBondStructure Enum**:
- `OUTRIGHT`: Single bond
- `CURVE`: 2-bond spread
- `FLY`: 3-bond spread

**FixedRateBondValue Enum**:
- `YTM`: Yield to maturity (%)
- `CLEAN_PRICE`: Price ex-accrued
- `DIRTY_PRICE`: Price inc-accrued
- `NPV`: Mark-to-market PnL
- `PV01`: Basis point value
- `DV01`: Dollar value of 1bp
- `MOD_DURATION`: Modified duration
- `CONVEXITY`: Convexity

### ProductAdapter

**Location**: `Query/Base/product_adapter.py`

| Method | Signature | Returns | Purpose |
|--------|-----------|---------|---------|
| `build_structure_map` | `(pricer_or_curve: Any) -> Any` | StructureMap | Create structure builder |
| `build_value_map` | `(pricer_or_curve, package, risk_weights) -> Any` | ValueMap | Create value calculator |
| `edit_query` | `(q: BaseQuery, pricer_or_curve) -> BaseQuery` | Query | Optionally edit query |
| `register_product` | `(product: str, adapter_cls: Type[ProductAdapter])` | None | Register adapter (module-level) |
| `get_adapter` | `(product: str) -> Type[ProductAdapter]` | Adapter | Retrieve adapter (module-level) |

### BaseStructureFunctionMap

**Location**: `Query/Base/BaseStructure.py`

| Method | Signature | Returns | Purpose |
|--------|-----------|---------|---------|
| `_create_map` | `() -> Dict[E, Callable[..., List[T]]]` | Map | Build enum → builder mapping (override) |
| `apply` | `(structure: E, **kwargs) -> Tuple[List[T], List[float]]` | (package, weights) | Apply builder for structure |

### BaseValueFunctionMap

**Location**: `Query/Base/BaseValue.py`

| Method | Signature | Returns | Purpose |
|--------|-----------|---------|---------|
| `_create_map` | `() -> Dict[E, Callable[..., R]]` | Map | Build enum → calc mapping (override) |
| `apply` | `(value: E, **kwargs) -> R` | Result | Apply calculation for value |

### _IRSwapGenericCurve

**Location**: `Query/IRSwaps/_IRSwapGenericCurve.py`

Core methods:

| Method | Signature | Returns | Purpose |
|--------|-----------|---------|---------|
| `id` | `() -> str` | str | Curve identifier |
| `reference_date` | `() -> datetime.date` | date | As-of date |
| `fair_rate` | `(irswap: _IRSwapGenericObject) -> float` | float | Market fair rate (decimal) |
| `npv` | `(irswap) -> float` | float | Mark-to-market NPV |
| `pv01` | `(irswap) -> float` | float | Basis point value |
| `dv01` | `(irswap) -> float` | float | Dollar value of 1bp |
| `build_irswap` | `(fwd, tenor, ..., notional, bpv) -> _IRSwapGenericObject` | Swap | Build swap |
| `build_stirf` | `(fwd, tenor, ...) -> Any` | Future | Build STIR future |

### QLIRSwapCurve

**Location**: `Query/IRSwaps/backends/quantlib/QLIRSwapCurve.py`

Concrete implementation wrapping QuantLib:

```python
QLIRSwapCurve(
    ql_curve_id: str,
    ql_curve_handle: ql.YieldTermStructureHandle,
    ql_curve_index: ql.SwapIndex,
    meta_data: Any,
)
```

### RLIRSwapCurve

**Location**: `Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py`

Concrete implementation wrapping RatesLib:

```python
RLIRSwapCurve(
    rl_curve_id: str,
    rl_curve_handle: rl.Curve,
    fixings: pd.Series,
    meta_data: Any,
)
```

---

## Summary

The ARBS Query module provides:

1. **Product Agnostic Interface**: BaseQuery allows backtester to work with any product
2. **Flexible Adapter Pattern**: Each product registers itself via ProductAdapter
3. **Generic Structure/Value Maps**: Enum-to-function mappings enable declarative specifications
4. **Backend Abstraction**: QuantLib and RatesLib are interchangeable
5. **Composable Queries**: Arithmetic operators enable spreads and flies
6. **Type Safety**: Frozen dataclasses and abstract base classes enforce contracts
7. **Extensibility**: Adding a new product requires ~1000 LOC of boilerplate following the pattern

The key insight is that **structure resolution and value calculation are decoupled**. A query first resolves into a package of concrete instruments, then those instruments are valued. This separation of concerns enables flexible composition and backend swapping.

