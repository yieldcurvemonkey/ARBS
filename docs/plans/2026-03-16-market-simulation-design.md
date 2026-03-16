# Market Simulation Infrastructure — Design Document

**Date:** 2026-03-16
**Status:** Approved
**Driving use case:** Option package expected return (e.g., TYM6 straddle PnL grid across underlying price shifts and days forward)

---

## 1. Objective

Design a generalized market simulation infrastructure for the ARBS codebase that:

1. Computes expected return / PnL grids for arbitrary option packages (STIR future options, UST future options, swaptions) across multiple scenario dimensions (underlying price, time decay, vol shifts).
2. Supports partial delta hedges and multi-leg structures (straddles, verticals, flies, etc.).
3. Integrates cleanly with the existing 5-step ARBS pricing pipeline (MDP → Query → Structure → ValueMap → Evaluate) without modifying any existing abstractions.
4. Is designed for future extension to a gs_quant-style context-manager API.

## 2. Architectural Decision

### Approach A: Scenario Grid Evaluator (Implemented Now)

The simulation layer sits **after** the standard 5-step pipeline. You build your package normally (Steps 1-4), then hand it to a `SimulationEngine` that analytically re-prices across a grid of hypothetical market states.

**Why this approach:**
- Minimal changes to existing pipeline — purely additive module.
- Analytical re-pricing is fast and sufficient for listed options (Bachelier model).
- Self-contained and easy to test.
- Each scenario axis is an immutable dataclass — trivially composable.

### Approach C: Context Manager Integration (Future)

The `ScenarioAxis` dataclasses are designed so they can later extend `ContextBase` (mirroring gs_quant's `Scenario` pattern) to support:

```python
with UnderlyingShift(shift=+1.0):
    with TimeDecay(days=7):
        shocked_npv = vmap.apply(value=STIRFutureOptionValue.NPV)
```

This is deferred because:
- Requires thread-local state management and interception of `ValueFunctionMap.apply()`.
- Doesn't vectorize well across grids (would loop over each point).
- Premature for the current analytical re-pricing use case.

**Migration path is documented in Section 8.**

### Approaches Considered but Rejected

**Approach B: Pricer Proxy.** Wrap the pricer with a proxy that intercepts method calls (`forward()`, `iv_normal()`, etc.) and returns shocked values. Rejected because each product's pricer has a different interface, making proxies product-specific without clear benefit over the extractor pattern. Also hard to vectorize across a full grid.

## 3. Core Abstractions

### 3.1 MarketState

A flat, product-agnostic snapshot of the inputs needed for analytical re-pricing.

```python
@dataclass(frozen=True)
class MarketState:
    forward: Optional[float] = None      # underlying forward price
    vol_normal: Optional[float] = None   # normal (Bachelier) volatility
    discount: Optional[float] = None     # discount factor to expiry
    tte: Optional[float] = None          # time to expiry in years
    eval_date: Optional[date] = None     # evaluation date (for calendar effects)
```

Each field is `Optional` so scenario axes only override what they touch. Product-specific extractors populate it from pricers.

### 3.2 ScenarioAxis

Base class for a single dimension of market mutation. Pure function: state in, state out.

```python
@dataclass(frozen=True)
class ScenarioAxis(ABC):
    @abstractmethod
    def mutate(self, market_state: MarketState) -> MarketState: ...
```

**Concrete axes:**

| Axis | Parameter | Effect |
|------|-----------|--------|
| `UnderlyingShift` | `shift: float` | Adds `shift` to `forward` (absolute, in price points) |
| `VolShift` | `shift_bps: float` | Adds `shift_bps * 0.01` to `vol_normal` |
| `TimeDecay` | `days: int` | Subtracts `days/365` from `tte`, advances `eval_date` |
| `CompositeScenario` | `axes: Tuple[ScenarioAxis, ...]` | Applies axes sequentially |

### 3.3 ScenarioGrid

Defines the N-dimensional cartesian product of scenario axes to evaluate.

```python
@dataclass(frozen=True)
class ScenarioGrid:
    axes: List[Tuple[Type[ScenarioAxis], str, List[Any]]]
    #           e.g. [(UnderlyingShift, "shift", [-2, -1, 0, 1, 2]),
    #                  (TimeDecay,       "days",  [0, 7, 14, 30])]

    def scenarios(self) -> Iterator[Tuple[Tuple[Any, ...], CompositeScenario]]:
        """Yield (coordinate_tuple, composite_scenario) for each grid point."""
        ...

    @property
    def shape(self) -> Tuple[int, ...]: ...

    @property
    def axis_names(self) -> List[str]: ...
```

### 3.4 MarketStateExtractor

Bridges product-specific pricers to the generic `MarketState`. The **only** product-specific code in the simulation module.

```python
class MarketStateExtractor(ABC):
    @abstractmethod
    def extract(self, pricer: Any, leg: Any) -> MarketState: ...

    @abstractmethod
    def reprice(self, state: MarketState, leg: Any) -> float: ...
```

**Concrete extractors:**

| Extractor | Products | Model |
|-----------|----------|-------|
| `BachelierExtractor` | STIRFUTUREOPTION, USTFUTUREOPTION | Bachelier normal vol |
| `SwaptionExtractor` | IRSWAPTION | Bachelier normal vol (different pricer interface) |

Extractors are registered via a registry that mirrors the existing `product_adapter.py` pattern:

```python
register_extractor("STIRFUTUREOPTION", BachelierExtractor)
register_extractor("USTFUTUREOPTION", BachelierExtractor)
register_extractor("IRSWAPTION", SwaptionExtractor)
```

### 3.5 SimulationResult

```python
@dataclass
class SimulationResult:
    data: np.ndarray                      # shape: (*grid.shape, len(metrics))
    coordinates: Dict[str, List[Any]]     # axis_name -> axis values
    metrics: List[str]                    # e.g. ["pnl", "delta"]

    def to_dataframe(self, metric: str = None) -> pd.DataFrame:
        """For 2D grids: rows = axis_0, cols = axis_1.
           For 1D grids: single-column DataFrame.
           For 3D+: long-form DataFrame."""
        ...
```

## 4. SimulationEngine

Stateless evaluator. Takes a resolved package and evaluates it across a scenario grid.

```python
class SimulationEngine:
    @staticmethod
    def evaluate(
        *,
        pricer: Any,
        package: List[_GenericPricable],
        risk_weights: List[float],
        grid: ScenarioGrid,
        extractor: MarketStateExtractor,
        metrics: Optional[List[str]] = None,
        entry_cost: Optional[float] = None,
    ) -> SimulationResult:
        ...
```

**Algorithm:**

1. Extract `MarketState` from pricer for each leg in the package.
2. For each grid point (cartesian product of axes):
   a. Create `CompositeScenario` from the grid coordinates.
   b. For each leg: `mutate(base_state)` → `reprice(shocked_state, leg)`.
   c. Aggregate: `package_value = sum(rw * qty * leg_price)`.
   d. If Greeks requested: finite-difference on the shocked state.
   e. If PnL requested: `pnl = scenario_npv - entry_cost`.
3. Return `SimulationResult` with shape `(*grid.shape, len(metrics))`.

**Supported metrics:** `npv`, `pnl`, `price`, `delta`, `gamma`, `vega`, `theta`.

**Greeks** are computed via central finite differences on the shocked state (not the base state), so you get Greeks at each scenario point. The FD bumps mirror the conventions in `Query/Base/bachelier.py:bachelier_greeks_fd()`.

## 5. Convenience Helper

`simulate_package()` auto-selects the extractor and runs Steps 3-5 internally:

```python
def simulate_package(
    *,
    query: BaseQuery,
    pricer: Any,
    grid: ScenarioGrid,
    metrics: Optional[List[str]] = None,
    include_pnl: bool = True,
) -> SimulationResult:
    """End-to-end simulation from a query + pricer."""
    pkg, rws = query.resolve_package(pricer_or_curve=pricer)
    vmap = query.build_value_map(pricer_or_curve=pricer, package=pkg, risk_weights=rws)

    extractor = get_extractor(query.product)

    entry_cost = None
    if include_pnl:
        entry_cost = vmap.apply(value=query.default_mtm_value_id())
        if metrics is None:
            metrics = ["pnl"]

    return SimulationEngine.evaluate(
        pricer=pricer, package=pkg, risk_weights=rws,
        grid=grid, extractor=extractor, metrics=metrics,
        entry_cost=entry_cost,
    )
```

## 6. End-to-End Usage Example

### TYM6 Straddle Expected Return

```python
from Simulation import (
    ScenarioGrid, UnderlyingShift, TimeDecay,
    SimulationEngine, BachelierExtractor, simulate_package,
)

# --- Standard ARBS pipeline (Steps 1-2) ---
mdp = STIRFutureOptionMDP(source="BARCHART")
pricer = mdp.get_pricer(request={"symbols": ["SFRM6C 9575S"], "timestamp": eod})

# --- Query (Step 2) + Simulation ---
query = STIRFutureOptionQuery(
    structure=STIRFutureOptionStructure.STRADDLE,
    symbol="SFRM6C 9575S",
    contracts=1,
)

grid = ScenarioGrid(axes=[
    (UnderlyingShift, "shift", np.arange(-2.0, 2.05, 0.1).tolist()),
    (TimeDecay,       "days",  [0, 7, 14, 30, 60]),
])

result = simulate_package(query=query, pricer=pricer, grid=grid)

# --- Output ---
pnl_heatmap = result.to_dataframe("pnl")
# DataFrame with rows=underlying shift, cols=days forward
```

### Swaption with Delta Hedge

```python
# Build swaption package
swaption_query = IRSwaptionQuery(
    structure=IRSwaptionStructure.STRADDLE,
    tenor="2Y", length="5Y", vega_01=10_000,
)
pkg, rws = swaption_query.resolve_package(pricer_or_curve=swaption_pricer)

# Add delta hedge (swap leg)
swap_query = IRSwapQuery(tenor="5Y", bpv=-delta_of_straddle)
swap_pkg, swap_rws = swap_query.resolve_package(pricer_or_curve=curve_handle)

# Combine into single package for simulation
combined_pkg = pkg + swap_pkg
combined_rws = rws + swap_rws

# Simulate with appropriate extractor
result = SimulationEngine.evaluate(
    pricer=combined_pricer_dict,
    package=combined_pkg,
    risk_weights=combined_rws,
    grid=grid,
    extractor=SwaptionExtractor(),  # handles both swaption + swap legs
    entry_cost=entry_cost,
)
```

## 7. Integration with Existing ARBS Code

### No Existing Files Modified

The simulation module is purely additive. All dependencies are read-only:

| Existing Module | What We Import | Direction |
|---|---|---|
| `Query/Base/bachelier.py` | `bachelier_price()` | Read-only |
| `Query/STIRFutureOptions/_risk.py` | `resolve_pricer_for_leg()`, `option_quantity()` | Read-only |
| `Query/Base/BaseQuery.py` | `BaseQuery` (type hint only in `simulate_package`) | Read-only |
| `Query/Base/_GenericPricable.py` | `_GenericPricable` (type hint) | Read-only |
| `MDP/*` | None — engine receives pricer from caller | No dependency |

### Registry Convention

The extractor registry mirrors the existing `product_adapter.py` pattern so it feels native:

```python
# product_adapter.py pattern:
register_product("IRS", IRSProductAdapter)
get_adapter("IRS")

# extractor pattern (same convention):
register_extractor("STIRFUTUREOPTION", BachelierExtractor)
get_extractor("STIRFUTUREOPTION")
```

## 8. Future Work: Approach C Context Manager Integration

### Phase 2: ScenarioAxis as Context Manager

`ScenarioAxis` gains `__enter__`/`__exit__` via a thread-local stack, mirroring gs_quant's `Scenario(ContextBase)` pattern:

```python
# Future API:
with UnderlyingShift(shift=+1.0):
    with TimeDecay(days=7):
        shocked_npv = vmap.apply(value=STIRFutureOptionValue.NPV)

# Or equivalently:
with CompositeScenario(axes=(UnderlyingShift(+1.0), TimeDecay(days=7))):
    shocked_npv = vmap.apply(value=STIRFutureOptionValue.NPV)
```

**Implementation notes:**
1. `ScenarioAxis` extends a local port of gs_quant's `ContextBase` (thread-local stack via metaclass).
2. A `SimulationContext` singleton manages the active axis stack.
3. `BaseValueFunctionMap.apply()` gains a hook that checks the stack:
   - If axes are active: extract `MarketState` from pricer, apply axes, reprice analytically.
   - If no axes: existing behavior unchanged.
4. The `ScenarioAxis` dataclasses from Phase 1 are the **same objects** used in Phase 2 — no API break.

### Phase 3: SimulationMDP for Curve-Level Scenarios

For instruments where analytical re-pricing is insufficient (e.g., swaptions under a parallel-shifted SOFR curve), a `SimulationMDP` wrapper intercepts `get_pricer()` and returns a pricer built from shocked market data:

```python
# Future API:
class CurveShiftScenario(ScenarioAxis):
    """Parallel shift of the yield curve."""
    shift_bps: float = 0.0

    def mutate_mdp_request(self, request: dict) -> dict:
        """Override get_pricer behavior at the MDP level."""
        return {**request, "curve_shifts": {"parallel": self.shift_bps}}
```

This enables full curve re-bootstrapping for scenarios that require it, while maintaining the same `ScenarioAxis` interface.

## 9. Module Layout

```
Simulation/
    __init__.py              # Public API exports
    scenarios.py             # ScenarioAxis, MarketState, UnderlyingShift,
                             #   VolShift, TimeDecay, CompositeScenario
    grid.py                  # ScenarioGrid
    engine.py                # SimulationEngine, SimulationResult, simulate_package()
    extractors.py            # MarketStateExtractor base, registry,
                             #   BachelierExtractor, SwaptionExtractor
    context.py               # FUTURE (Phase 2): context-manager integration
```

## 10. Testing Strategy

| Test | What it validates |
|------|-------------------|
| `test_scenario_axes` | Each axis mutates MarketState correctly; CompositeScenario chains |
| `test_scenario_grid` | Grid generates correct cartesian product; shape/names correct |
| `test_bachelier_extractor` | Extract → reprice round-trips match `bachelier_price()` directly |
| `test_engine_1d` | 1D grid (underlying shift only) produces correct PnL curve |
| `test_engine_2d` | 2D grid (shift x time) produces correct shape and known values |
| `test_engine_greeks` | FD Greeks at each grid point match `bachelier_greeks_fd()` |
| `test_simulate_package` | End-to-end with mock pricer; auto-extractor selection works |
| `test_straddle_symmetry` | ATM straddle PnL is symmetric around forward at t=0 |
| `test_time_decay` | Option value decreases monotonically as days_forward increases (ATM) |
