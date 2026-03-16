# Market Simulation Infrastructure — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a scenario grid evaluator that analytically re-prices option packages across underlying price shifts, time decay, and vol shifts.

**Architecture:** Purely additive `Simulation/` module. No existing files modified. Immutable `ScenarioAxis` dataclasses define market mutations, a `ScenarioGrid` generates the cartesian product, product-specific `MarketStateExtractor`s bridge pricers to a generic `MarketState`, and a stateless `SimulationEngine` evaluates the grid. See `docs/plans/2026-03-16-market-simulation-design.md` for full design.

**Tech Stack:** Python 3.13, dataclasses, numpy, pandas, QuantLib (via existing `bachelier.py`), pytest.

---

### Task 1: Scenarios — MarketState and ScenarioAxis

**Files:**
- Create: `Simulation/__init__.py`
- Create: `Simulation/scenarios.py`
- Test: `tests/test_simulation_scenarios.py`

**Step 1: Write the failing tests**

```python
# tests/test_simulation_scenarios.py
import datetime
import pytest
from Simulation.scenarios import (
    MarketState,
    ScenarioAxis,
    UnderlyingShift,
    VolShift,
    TimeDecay,
    CompositeScenario,
)


def _base_state() -> MarketState:
    return MarketState(
        forward=95.75,
        vol_normal=0.0050,       # 50 bps normal vol
        discount=0.998,
        tte=0.25,                # 3 months
        eval_date=datetime.date(2026, 3, 16),
    )


class TestUnderlyingShift:
    def test_positive_shift(self):
        s = _base_state()
        result = UnderlyingShift(shift=1.0).mutate(s)
        assert result.forward == pytest.approx(96.75)
        # Other fields unchanged
        assert result.vol_normal == s.vol_normal
        assert result.discount == s.discount
        assert result.tte == s.tte
        assert result.eval_date == s.eval_date

    def test_negative_shift(self):
        s = _base_state()
        result = UnderlyingShift(shift=-2.5).mutate(s)
        assert result.forward == pytest.approx(93.25)

    def test_zero_shift_is_identity(self):
        s = _base_state()
        result = UnderlyingShift(shift=0.0).mutate(s)
        assert result == s


class TestVolShift:
    def test_positive_vol_shift(self):
        s = _base_state()
        result = VolShift(shift_bps=10.0).mutate(s)
        # 10 bps = 0.001 in normal vol terms (bps * 0.0001)
        assert result.vol_normal == pytest.approx(0.0050 + 10.0 * 0.0001)

    def test_negative_vol_shift(self):
        s = _base_state()
        result = VolShift(shift_bps=-5.0).mutate(s)
        assert result.vol_normal == pytest.approx(0.0050 - 5.0 * 0.0001)


class TestTimeDecay:
    def test_time_decay_reduces_tte(self):
        s = _base_state()
        result = TimeDecay(days=30).mutate(s)
        assert result.tte == pytest.approx(0.25 - 30.0 / 365.0)
        assert result.eval_date == datetime.date(2026, 4, 15)

    def test_time_decay_floors_at_zero(self):
        s = _base_state()
        result = TimeDecay(days=365).mutate(s)
        assert result.tte == 0.0

    def test_zero_days_is_identity(self):
        s = _base_state()
        result = TimeDecay(days=0).mutate(s)
        assert result == s


class TestCompositeScenario:
    def test_applies_axes_sequentially(self):
        s = _base_state()
        composite = CompositeScenario(axes=(
            UnderlyingShift(shift=1.0),
            TimeDecay(days=7),
        ))
        result = composite.mutate(s)
        assert result.forward == pytest.approx(96.75)
        assert result.tte == pytest.approx(0.25 - 7.0 / 365.0)
        assert result.eval_date == datetime.date(2026, 3, 23)

    def test_empty_composite_is_identity(self):
        s = _base_state()
        result = CompositeScenario(axes=()).mutate(s)
        assert result == s

    def test_nested_composites(self):
        s = _base_state()
        inner = CompositeScenario(axes=(UnderlyingShift(shift=1.0),))
        outer = CompositeScenario(axes=(inner, VolShift(shift_bps=5.0)))
        result = outer.mutate(s)
        assert result.forward == pytest.approx(96.75)
        assert result.vol_normal == pytest.approx(0.0050 + 5.0 * 0.0001)


class TestImmutability:
    def test_market_state_is_frozen(self):
        s = _base_state()
        with pytest.raises(AttributeError):
            s.forward = 100.0

    def test_scenario_axis_is_frozen(self):
        axis = UnderlyingShift(shift=1.0)
        with pytest.raises(AttributeError):
            axis.shift = 2.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation_scenarios.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Simulation'`

**Step 3: Write the implementation**

```python
# Simulation/__init__.py
# (leave empty for now — populated in Task 5)
```

```python
# Simulation/scenarios.py
from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Optional, Tuple


@dataclass(frozen=True)
class MarketState:
    """Snapshot of inputs for analytical re-pricing. Product-agnostic."""

    forward: Optional[float] = None
    vol_normal: Optional[float] = None
    discount: Optional[float] = None
    tte: Optional[float] = None
    eval_date: Optional[datetime.date] = None


@dataclass(frozen=True)
class ScenarioAxis(ABC):
    """Single dimension of market mutation. Pure function: state in, state out."""

    @abstractmethod
    def mutate(self, market_state: MarketState) -> MarketState: ...


@dataclass(frozen=True)
class UnderlyingShift(ScenarioAxis):
    """Shift the underlying forward price (absolute, in price points)."""

    shift: float = 0.0

    def mutate(self, s: MarketState) -> MarketState:
        return replace(s, forward=s.forward + self.shift)


@dataclass(frozen=True)
class VolShift(ScenarioAxis):
    """Shift normal volatility (absolute, in basis points)."""

    shift_bps: float = 0.0

    def mutate(self, s: MarketState) -> MarketState:
        return replace(s, vol_normal=s.vol_normal + self.shift_bps * 0.0001)


@dataclass(frozen=True)
class TimeDecay(ScenarioAxis):
    """Roll forward in time (theta decay)."""

    days: int = 0

    def mutate(self, s: MarketState) -> MarketState:
        new_tte = max(s.tte - self.days / 365.0, 0.0)
        new_date = (
            s.eval_date + datetime.timedelta(days=self.days)
            if s.eval_date is not None
            else None
        )
        return replace(s, tte=new_tte, eval_date=new_date)


@dataclass(frozen=True)
class CompositeScenario(ScenarioAxis):
    """Apply multiple axes sequentially."""

    axes: Tuple[ScenarioAxis, ...] = ()

    def mutate(self, s: MarketState) -> MarketState:
        for axis in self.axes:
            s = axis.mutate(s)
        return s
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_scenarios.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add Simulation/__init__.py Simulation/scenarios.py tests/test_simulation_scenarios.py
git commit -m "feat(simulation): add MarketState and ScenarioAxis abstractions"
```

---

### Task 2: ScenarioGrid

**Files:**
- Create: `Simulation/grid.py`
- Test: `tests/test_simulation_grid.py`

**Step 1: Write the failing tests**

```python
# tests/test_simulation_grid.py
import pytest
from Simulation.grid import ScenarioGrid
from Simulation.scenarios import (
    CompositeScenario,
    MarketState,
    TimeDecay,
    UnderlyingShift,
)


class TestScenarioGrid:
    def test_shape(self):
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1, 0, 1]),
            (TimeDecay, "days", [0, 7, 14]),
        ])
        assert grid.shape == (3, 3)

    def test_axis_names(self):
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1, 0, 1]),
            (TimeDecay, "days", [0, 7]),
        ])
        assert grid.axis_names == ["UnderlyingShift.shift", "TimeDecay.days"]

    def test_scenarios_count(self):
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1, 0, 1]),
            (TimeDecay, "days", [0, 7]),
        ])
        scenarios = list(grid.scenarios())
        assert len(scenarios) == 6  # 3 * 2

    def test_scenarios_coordinates(self):
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1, 0]),
            (TimeDecay, "days", [0, 7]),
        ])
        scenarios = list(grid.scenarios())
        coords = [c for c, _ in scenarios]
        assert coords == [(-1, 0), (-1, 7), (0, 0), (0, 7)]

    def test_scenarios_mutate_correctly(self):
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [1.0]),
            (TimeDecay, "days", [7]),
        ])
        scenarios = list(grid.scenarios())
        assert len(scenarios) == 1
        coords, composite = scenarios[0]
        assert coords == (1.0, 7)

        base = MarketState(forward=95.0, tte=0.25, eval_date=None,
                           vol_normal=0.005, discount=0.998)
        result = composite.mutate(base)
        assert result.forward == pytest.approx(96.0)
        assert result.tte == pytest.approx(0.25 - 7.0 / 365.0)

    def test_1d_grid(self):
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-2, -1, 0, 1, 2]),
        ])
        assert grid.shape == (5,)
        assert len(list(grid.scenarios())) == 5

    def test_coordinates_property(self):
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1, 0, 1]),
            (TimeDecay, "days", [0, 30]),
        ])
        assert grid.coordinates == {
            "UnderlyingShift.shift": [-1, 0, 1],
            "TimeDecay.days": [0, 30],
        }
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation_grid.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Simulation.grid'`

**Step 3: Write the implementation**

```python
# Simulation/grid.py
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Tuple, Type

from Simulation.scenarios import CompositeScenario, ScenarioAxis


@dataclass(frozen=True)
class ScenarioGrid:
    """N-dimensional grid of scenario axes. Generates cartesian product."""

    axes: List[Tuple[Type[ScenarioAxis], str, List[Any]]]

    def scenarios(self) -> Iterator[Tuple[Tuple[Any, ...], CompositeScenario]]:
        param_lists = [values for _, _, values in self.axes]
        for combo in itertools.product(*param_lists):
            scenario_axes = []
            for (cls, param_name, _), val in zip(self.axes, combo):
                scenario_axes.append(cls(**{param_name: val}))
            yield combo, CompositeScenario(axes=tuple(scenario_axes))

    @property
    def axis_names(self) -> List[str]:
        return [f"{cls.__name__}.{param}" for cls, param, _ in self.axes]

    @property
    def shape(self) -> Tuple[int, ...]:
        return tuple(len(vals) for _, _, vals in self.axes)

    @property
    def coordinates(self) -> Dict[str, List[Any]]:
        return {
            f"{cls.__name__}.{param}": values
            for cls, param, values in self.axes
        }
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_grid.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add Simulation/grid.py tests/test_simulation_grid.py
git commit -m "feat(simulation): add ScenarioGrid with cartesian product generation"
```

---

### Task 3: Extractors — MarketStateExtractor and BachelierExtractor

**Files:**
- Create: `Simulation/extractors.py`
- Test: `tests/test_simulation_extractors.py`

**Step 1: Write the failing tests**

These tests use a mock pricer constructed from `QLSTIRFutureOptionPricer` and `QLSTIRFutureOptionPricable` — the real concrete classes, populated with fake data. No MDP or network calls.

```python
# tests/test_simulation_extractors.py
import datetime
import math

import pytest

from Query.Base.bachelier import bachelier_price
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (
    QLSTIRFutureOptionPricable,
    QLSTIRFutureOptionPricer,
)
from Simulation.extractors import (
    BachelierExtractor,
    MarketStateExtractor,
    get_extractor,
    register_extractor,
)
from Simulation.scenarios import MarketState


def _make_pricer(
    *,
    forward: float = 95.75,
    strike: float = 95.75,
    iv_normal: float = 0.0050,
    right: str = "C",
    tte_days: int = 90,
) -> QLSTIRFutureOptionPricer:
    ts = datetime.datetime(2026, 3, 16, 17, 0)
    expiry = (ts + datetime.timedelta(days=tte_days)).date()
    discount = 0.998
    tte = tte_days / 365.0
    price = bachelier_price(right, strike, forward, iv_normal, tte, discount)
    return QLSTIRFutureOptionPricer(
        symbol=f"SFR{right}{int(strike * 100)}",
        right=right,
        underlying_symbol="SFRM6",
        strike=strike,
        quote_timestamp=ts,
        expiry_date=expiry,
        market_price=price,
        model_price=price,
        iv_normal=iv_normal,
        delta=0.5,
        gamma=100.0,
        vega=0.01,
        theta=-0.001,
        forward=forward,
        discount=discount,
    )


def _make_leg(pricer: QLSTIRFutureOptionPricer) -> QLSTIRFutureOptionPricable:
    return pricer.build_pricable(quantity=1.0)


class TestBachelierExtractor:
    def test_extract_produces_valid_market_state(self):
        pricer = _make_pricer()
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        assert state.forward == pytest.approx(95.75)
        assert state.vol_normal == pytest.approx(0.0050)
        assert state.discount == pytest.approx(0.998)
        assert state.tte == pytest.approx(90.0 / 365.0)
        assert state.eval_date == datetime.date(2026, 3, 16)

    def test_reprice_matches_bachelier_price(self):
        pricer = _make_pricer(forward=95.75, strike=95.75, iv_normal=0.005)
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        repriced = extractor.reprice(state, leg)
        expected = bachelier_price("C", 95.75, 95.75, 0.005, 90.0 / 365.0, 0.998)
        assert repriced == pytest.approx(expected, rel=1e-10)

    def test_reprice_with_shifted_state(self):
        pricer = _make_pricer(forward=95.75, strike=95.75, iv_normal=0.005)
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        from dataclasses import replace
        shifted = replace(state, forward=96.75)
        repriced = extractor.reprice(shifted, leg)
        expected = bachelier_price("C", 95.75, 96.75, 0.005, 90.0 / 365.0, 0.998)
        assert repriced == pytest.approx(expected, rel=1e-10)

    def test_reprice_put(self):
        pricer = _make_pricer(right="P", strike=96.0)
        leg = _make_leg(pricer)
        extractor = BachelierExtractor()
        state = extractor.extract(pricer, leg)

        repriced = extractor.reprice(state, leg)
        expected = bachelier_price("P", 96.0, 95.75, 0.005, 90.0 / 365.0, 0.998)
        assert repriced == pytest.approx(expected, rel=1e-10)


class TestExtractorRegistry:
    def test_register_and_get(self):
        register_extractor("STIRFUTUREOPTION", BachelierExtractor)
        extractor = get_extractor("STIRFUTUREOPTION")
        assert isinstance(extractor, BachelierExtractor)

    def test_get_unknown_product_raises(self):
        with pytest.raises(KeyError):
            get_extractor("NONEXISTENT_PRODUCT_XYZ_12345")
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation_extractors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Simulation.extractors'`

**Step 3: Write the implementation**

```python
# Simulation/extractors.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Type

from Query.Base.bachelier import bachelier_price
from Simulation.scenarios import MarketState


class MarketStateExtractor(ABC):
    """Bridge between product-specific pricers and generic MarketState."""

    @abstractmethod
    def extract(self, pricer: Any, leg: Any) -> MarketState: ...

    @abstractmethod
    def reprice(self, state: MarketState, leg: Any) -> float: ...


class BachelierExtractor(MarketStateExtractor):
    """For STIR future options and UST future options (Bachelier normal model)."""

    def extract(self, pricer: Any, leg: Any) -> MarketState:
        tte = max(
            (leg.expiry_date() - pricer.quote_timestamp().date()).days / 365.0,
            1e-12,
        )
        return MarketState(
            forward=float(pricer.forward()),
            vol_normal=float(pricer.iv_normal()),
            discount=float(pricer.discount()),
            tte=tte,
            eval_date=pricer.quote_timestamp().date(),
        )

    def reprice(self, state: MarketState, leg: Any) -> float:
        return bachelier_price(
            right=leg.right(),
            strike=float(leg.strike()),
            forward=state.forward,
            vol_normal=state.vol_normal,
            tte=state.tte,
            discount=state.discount,
        )


# --------------- Registry ---------------

_EXTRACTORS: Dict[str, Type[MarketStateExtractor]] = {}


def register_extractor(product: str, extractor_cls: Type[MarketStateExtractor]) -> None:
    _EXTRACTORS[product] = extractor_cls


def get_extractor(product: str) -> MarketStateExtractor:
    try:
        return _EXTRACTORS[product]()
    except KeyError as e:
        raise KeyError(
            f"No MarketStateExtractor registered for product '{product}'. "
            f"Registered: {sorted(_EXTRACTORS)}"
        ) from e


# Default registrations
register_extractor("STIRFUTUREOPTION", BachelierExtractor)
register_extractor("USTFUTUREOPTION", BachelierExtractor)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_extractors.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add Simulation/extractors.py tests/test_simulation_extractors.py
git commit -m "feat(simulation): add MarketStateExtractor and BachelierExtractor with registry"
```

---

### Task 4: SimulationEngine and SimulationResult

**Files:**
- Create: `Simulation/engine.py`
- Test: `tests/test_simulation_engine.py`

**Step 1: Write the failing tests**

```python
# tests/test_simulation_engine.py
import datetime
import math

import numpy as np
import pytest

from Query.Base.bachelier import bachelier_price
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (
    QLSTIRFutureOptionPricable,
    QLSTIRFutureOptionPricer,
)
from Simulation.engine import SimulationEngine, SimulationResult
from Simulation.extractors import BachelierExtractor
from Simulation.grid import ScenarioGrid
from Simulation.scenarios import TimeDecay, UnderlyingShift, VolShift


# --- Helpers (same factory as Task 3) ---

def _make_pricer(
    *,
    forward: float = 95.75,
    strike: float = 95.75,
    iv_normal: float = 0.0050,
    right: str = "C",
    tte_days: int = 90,
) -> QLSTIRFutureOptionPricer:
    ts = datetime.datetime(2026, 3, 16, 17, 0)
    expiry = (ts + datetime.timedelta(days=tte_days)).date()
    discount = 0.998
    tte = tte_days / 365.0
    price = bachelier_price(right, strike, forward, iv_normal, tte, discount)
    return QLSTIRFutureOptionPricer(
        symbol=f"SFR{right}{int(strike * 100)}",
        right=right,
        underlying_symbol="SFRM6",
        strike=strike,
        quote_timestamp=ts,
        expiry_date=expiry,
        market_price=price,
        model_price=price,
        iv_normal=iv_normal,
        delta=0.5,
        gamma=100.0,
        vega=0.01,
        theta=-0.001,
        forward=forward,
        discount=discount,
    )


def _make_leg(pricer: QLSTIRFutureOptionPricer) -> QLSTIRFutureOptionPricable:
    return pricer.build_pricable(quantity=1.0)


def _straddle_pricer_dict():
    """ATM straddle: call + put at 95.75 strike, 90 DTE."""
    call_pr = _make_pricer(right="C", strike=95.75)
    put_pr = _make_pricer(right="P", strike=95.75)
    return {call_pr.symbol(): call_pr, put_pr.symbol(): put_pr}


def _straddle_package(pricer_dict):
    call_pr = list(pricer_dict.values())[0]
    put_pr = list(pricer_dict.values())[1]
    return [call_pr.build_pricable(quantity=1.0), put_pr.build_pricable(quantity=1.0)]


class TestSimulationEngine1D:
    def test_underlying_shift_grid(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1.0, 0.0, 1.0]),
        ])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )
        assert result.data.shape == (3, 1)  # 3 shifts, 1 metric
        # At shift=0, should match market price * quantity
        base_price = bachelier_price("C", 95.75, 95.75, 0.005, 90 / 365, 0.998)
        assert result.data[1, 0] == pytest.approx(base_price, rel=1e-6)
        # Higher underlying -> higher call price
        assert result.data[2, 0] > result.data[1, 0]
        assert result.data[0, 0] < result.data[1, 0]

    def test_pnl_with_entry_cost(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        base_price = bachelier_price("C", 95.75, 95.75, 0.005, 90 / 365, 0.998)
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [0.0]),
        ])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["pnl"],
            entry_cost=base_price,
        )
        # At shift=0, PnL = 0
        assert result.data[0, 0] == pytest.approx(0.0, abs=1e-10)


class TestSimulationEngine2D:
    def test_shift_x_time_grid(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1.0, 0.0, 1.0]),
            (TimeDecay, "days", [0, 30]),
        ])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )
        assert result.data.shape == (3, 2, 1)
        # Time decay reduces ATM option value
        atm_t0 = result.data[1, 0, 0]  # shift=0, days=0
        atm_t30 = result.data[1, 1, 0]  # shift=0, days=30
        assert atm_t30 < atm_t0


class TestSimulationEngineStraddle:
    def test_straddle_symmetry_at_t0(self):
        """ATM straddle PnL should be approximately symmetric around forward."""
        pricers = _straddle_pricer_dict()
        package = _straddle_package(pricers)
        risk_weights = [1.0, 1.0]

        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1.0, 0.0, 1.0]),
        ])
        result = SimulationEngine.evaluate(
            pricer=pricers,
            package=package,
            risk_weights=risk_weights,
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )
        # Symmetry: NPV at -1 shift ~= NPV at +1 shift
        assert result.data[0, 0] == pytest.approx(result.data[2, 0], rel=1e-4)

    def test_straddle_time_decay(self):
        """Straddle loses value as time passes (ATM, all else equal)."""
        pricers = _straddle_pricer_dict()
        package = _straddle_package(pricers)

        grid = ScenarioGrid(axes=[
            (TimeDecay, "days", [0, 30, 60]),
        ])
        result = SimulationEngine.evaluate(
            pricer=pricers,
            package=package,
            risk_weights=[1.0, 1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )
        # Monotonically decreasing
        assert result.data[0, 0] > result.data[1, 0] > result.data[2, 0]


class TestSimulationEngineGreeks:
    def test_delta_positive_for_call(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [0.0]),
        ])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["delta"],
        )
        assert result.data[0, 0] > 0

    def test_gamma_positive(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [0.0])])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["gamma"],
        )
        assert result.data[0, 0] > 0


class TestSimulationResult:
    def test_to_dataframe_2d(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1.0, 0.0, 1.0]),
            (TimeDecay, "days", [0, 30]),
        ])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )
        df = result.to_dataframe("npv")
        assert df.shape == (3, 2)
        assert list(df.index) == [-1.0, 0.0, 1.0]
        assert list(df.columns) == [0, 30]

    def test_to_dataframe_1d(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1.0, 0.0, 1.0]),
        ])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
            metrics=["npv"],
        )
        df = result.to_dataframe("npv")
        assert df.shape == (3, 1)

    def test_to_dataframe_default_metric(self):
        pricer = _make_pricer(right="C")
        leg = _make_leg(pricer)
        grid = ScenarioGrid(axes=[(UnderlyingShift, "shift", [0.0])])
        result = SimulationEngine.evaluate(
            pricer={pricer.symbol(): pricer},
            package=[leg],
            risk_weights=[1.0],
            grid=grid,
            extractor=BachelierExtractor(),
        )
        df = result.to_dataframe()  # no metric specified — uses first
        assert df is not None
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Simulation.engine'`

**Step 3: Write the implementation**

```python
# Simulation/engine.py
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from Query.Base._GenericPricable import _GenericPricable
from Simulation.extractors import MarketStateExtractor, get_extractor
from Simulation.grid import ScenarioGrid
from Simulation.scenarios import MarketState


@dataclass
class SimulationResult:
    """Result of a grid evaluation."""

    data: np.ndarray
    coordinates: Dict[str, List[Any]]
    metrics: List[str]

    def to_dataframe(self, metric: Optional[str] = None) -> pd.DataFrame:
        if metric is None:
            metric = self.metrics[0]
        metric_idx = self.metrics.index(metric)

        axis_names = list(self.coordinates.keys())

        if len(axis_names) == 1:
            return pd.DataFrame(
                {metric: self.data[:, metric_idx]},
                index=pd.Index(
                    self.coordinates[axis_names[0]], name=axis_names[0]
                ),
            )

        if len(axis_names) == 2:
            return pd.DataFrame(
                self.data[:, :, metric_idx],
                index=pd.Index(
                    self.coordinates[axis_names[0]], name=axis_names[0]
                ),
                columns=pd.Index(
                    self.coordinates[axis_names[1]], name=axis_names[1]
                ),
            )

        records: list[dict] = []
        for idx in itertools.product(
            *(range(len(v)) for v in self.coordinates.values())
        ):
            record = {
                name: self.coordinates[name][i]
                for name, i in zip(axis_names, idx)
            }
            record[metric] = self.data[idx][metric_idx]
            records.append(record)
        return pd.DataFrame(records)


class SimulationEngine:
    """Evaluate a resolved option package across a ScenarioGrid."""

    @staticmethod
    def evaluate(
        *,
        pricer: Any,
        package: List[Any],
        risk_weights: List[float],
        grid: ScenarioGrid,
        extractor: MarketStateExtractor,
        metrics: Optional[List[str]] = None,
        entry_cost: Optional[float] = None,
    ) -> SimulationResult:
        if metrics is None:
            metrics = ["pnl"] if entry_cost is not None else ["npv"]

        greek_metrics = {"delta", "gamma", "vega", "theta"}
        need_greeks = bool(greek_metrics & set(metrics))

        # Extract base market state for each leg
        base_states: List[MarketState] = []
        for idx, leg in enumerate(package):
            pr = _resolve_pricer(pricer, leg, idx)
            base_states.append(extractor.extract(pr, leg))

        output = np.empty(grid.shape + (len(metrics),))

        for flat_idx, (coords, scenario) in enumerate(grid.scenarios()):
            multi_idx = np.unravel_index(flat_idx, grid.shape)

            package_npv = 0.0
            package_price = 0.0
            package_greeks: Dict[str, float] = {
                "delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0,
            }

            for leg_idx, (leg, rw, base_state) in enumerate(
                zip(package, risk_weights, base_states)
            ):
                shocked_state = scenario.mutate(base_state)
                leg_price = extractor.reprice(shocked_state, leg)
                qty = _leg_quantity(leg)

                package_npv += rw * qty * leg_price
                package_price += rw * leg_price

                if need_greeks:
                    greeks = _fd_greeks(extractor, shocked_state, leg)
                    for g, val in greeks.items():
                        package_greeks[g] += rw * qty * val

            for m_idx, m in enumerate(metrics):
                if m == "npv":
                    output[multi_idx + (m_idx,)] = package_npv
                elif m == "pnl":
                    base_npv = entry_cost if entry_cost is not None else 0.0
                    output[multi_idx + (m_idx,)] = package_npv - base_npv
                elif m == "price":
                    output[multi_idx + (m_idx,)] = package_price
                elif m in package_greeks:
                    output[multi_idx + (m_idx,)] = package_greeks[m]

        return SimulationResult(
            data=output, coordinates=grid.coordinates, metrics=metrics,
        )


def simulate_package(
    *,
    query: Any,
    pricer: Any,
    grid: ScenarioGrid,
    metrics: Optional[List[str]] = None,
    include_pnl: bool = True,
) -> SimulationResult:
    """End-to-end simulation from a query + pricer."""
    pkg, rws = query.resolve_package(pricer_or_curve=pricer)
    vmap = query.build_value_map(
        pricer_or_curve=pricer, package=pkg, risk_weights=rws,
    )

    extractor = get_extractor(query.product)

    entry_cost = None
    if include_pnl:
        value_id = query.default_mtm_value_id()
        entry_cost = vmap.apply(value=value_id)
        if metrics is None:
            metrics = ["pnl"]

    return SimulationEngine.evaluate(
        pricer=pricer,
        package=pkg,
        risk_weights=rws,
        grid=grid,
        extractor=extractor,
        metrics=metrics,
        entry_cost=entry_cost,
    )


# --------------- Internal helpers ---------------


def _resolve_pricer(pricer: Any, leg: Any, index: int) -> Any:
    if isinstance(pricer, dict):
        from Query.STIRFutureOptions._risk import resolve_pricer_for_leg
        return resolve_pricer_for_leg(pricer, leg, index=index)
    return pricer


def _leg_quantity(leg: Any) -> float:
    if hasattr(leg, "quantity"):
        q = leg.quantity
        return float(q() if callable(q) else q)
    return 1.0


def _fd_greeks(
    extractor: MarketStateExtractor,
    state: MarketState,
    leg: Any,
) -> Dict[str, float]:
    p0 = extractor.reprice(state, leg)
    h_f = 0.01
    h_v = max(1e-4, abs(state.vol_normal) * 0.01) if state.vol_normal else 1e-4
    dt = 1.0 / 365.0

    p_up = extractor.reprice(replace(state, forward=state.forward + h_f), leg)
    p_dn = extractor.reprice(replace(state, forward=state.forward - h_f), leg)
    delta = (p_up - p_dn) / (2 * h_f)
    gamma = (p_up - 2 * p0 + p_dn) / (h_f ** 2)

    vol = state.vol_normal or 1e-8
    pv_up = extractor.reprice(replace(state, vol_normal=vol + h_v), leg)
    pv_dn = extractor.reprice(replace(state, vol_normal=max(vol - h_v, 1e-8)), leg)
    vega = (pv_up - pv_dn) / (2 * h_v)

    tte = state.tte or 1e-6
    pt_up = extractor.reprice(replace(state, tte=tte + dt), leg)
    pt_dn = extractor.reprice(replace(state, tte=max(tte - dt, 1e-6)), leg)
    theta = (pt_up - pt_dn) / (2 * dt)

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_engine.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add Simulation/engine.py tests/test_simulation_engine.py
git commit -m "feat(simulation): add SimulationEngine, SimulationResult, and simulate_package"
```

---

### Task 5: Public API and Module Init

**Files:**
- Modify: `Simulation/__init__.py`

**Step 1: Write the init with all public exports**

```python
# Simulation/__init__.py
from Simulation.scenarios import (
    ScenarioAxis,
    MarketState,
    UnderlyingShift,
    VolShift,
    TimeDecay,
    CompositeScenario,
)
from Simulation.grid import ScenarioGrid
from Simulation.engine import SimulationEngine, SimulationResult, simulate_package
from Simulation.extractors import (
    MarketStateExtractor,
    BachelierExtractor,
    register_extractor,
    get_extractor,
)
```

**Step 2: Verify all tests pass**

Run: `python -m pytest tests/test_simulation_scenarios.py tests/test_simulation_grid.py tests/test_simulation_extractors.py tests/test_simulation_engine.py -v`
Expected: All PASS

**Step 3: Verify import works**

Run: `python -c "from Simulation import SimulationEngine, ScenarioGrid, UnderlyingShift, TimeDecay, BachelierExtractor, simulate_package; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add Simulation/__init__.py
git commit -m "feat(simulation): wire up public API in __init__.py"
```

---

### Task 6: Full Integration Smoke Test

**Files:**
- Test: `tests/test_simulation_integration.py`

**Purpose:** Verify the `simulate_package()` convenience helper works end-to-end with a `STIRFutureOptionQuery`, using mock pricer data (no network/MDP calls).

**Step 1: Write the integration test**

```python
# tests/test_simulation_integration.py
"""Integration test: simulate_package with STIRFutureOptionQuery."""
import datetime

import numpy as np
import pytest

from Query.Base.bachelier import bachelier_price
from Query.STIRFutureOptions.backends.quantlib.QLSTIRFutureOptionPricer import (
    QLSTIRFutureOptionPricer,
)
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import STIRFutureOptionStructure
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Simulation import ScenarioGrid, UnderlyingShift, TimeDecay, simulate_package


def _mock_straddle_pricer():
    ts = datetime.datetime(2026, 3, 16, 17, 0)
    expiry = datetime.date(2026, 6, 15)
    fwd = 95.75
    strike = 95.75
    iv = 0.005
    discount = 0.998
    tte = (expiry - ts.date()).days / 365.0

    def _make(right):
        price = bachelier_price(right, strike, fwd, iv, tte, discount)
        sym = f"SFRC9575{right}"
        return QLSTIRFutureOptionPricer(
            symbol=sym, right=right, underlying_symbol="SFRM6",
            strike=strike, quote_timestamp=ts, expiry_date=expiry,
            market_price=price, model_price=price, iv_normal=iv,
            delta=0.5 if right == "C" else -0.5,
            gamma=100.0, vega=0.01, theta=-0.001,
            forward=fwd, discount=discount,
        )

    call_pr = _make("C")
    put_pr = _make("P")
    return {call_pr.symbol(): call_pr, put_pr.symbol(): put_pr}


class TestSimulatePackageIntegration:
    def test_straddle_expected_return_grid(self):
        pricer = _mock_straddle_pricer()
        query = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.STRADDLE,
            symbol="SFRC9575C",
            structure_kwargs={
                "call_symbol": "SFRC9575C",
                "put_symbol": "SFRC9575P",
            },
            contracts=1,
        )

        grid = ScenarioGrid(axes=[
            (UnderlyingShift, "shift", [-1.0, -0.5, 0.0, 0.5, 1.0]),
            (TimeDecay, "days", [0, 30, 60]),
        ])

        result = simulate_package(
            query=query, pricer=pricer, grid=grid, include_pnl=True,
        )

        # Shape: 5 shifts x 3 time points x 1 metric (pnl)
        assert result.data.shape == (5, 3, 1)
        assert result.metrics == ["pnl"]

        df = result.to_dataframe("pnl")
        assert df.shape == (5, 3)

        # PnL at shift=0, days=0 should be ~0
        assert df.loc[0.0, 0] == pytest.approx(0.0, abs=1e-6)

        # Time decay: PnL at shift=0 gets worse over time
        assert df.loc[0.0, 30] < df.loc[0.0, 0]
        assert df.loc[0.0, 60] < df.loc[0.0, 30]

        # Symmetry at t=0
        assert df.loc[-1.0, 0] == pytest.approx(df.loc[1.0, 0], rel=1e-3)
```

**Step 2: Run to verify it passes**

Run: `python -m pytest tests/test_simulation_integration.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_simulation_integration.py
git commit -m "test(simulation): add end-to-end integration test with STIRFutureOptionQuery"
```

---

### Task 7: Run Full Test Suite and Final Commit

**Step 1: Run all simulation tests**

Run: `python -m pytest tests/test_simulation_scenarios.py tests/test_simulation_grid.py tests/test_simulation_extractors.py tests/test_simulation_engine.py tests/test_simulation_integration.py -v`
Expected: All PASS

**Step 2: Verify no regressions in existing tests**

Run: `python -m pytest tests/ -x --timeout=60 -q`
Expected: No failures in existing tests

**Step 3: Final commit**

```bash
git add -A Simulation/ tests/test_simulation_*.py docs/plans/2026-03-16-market-simulation-*.md
git commit -m "feat(simulation): market simulation infrastructure — Phase 1 complete

Adds Simulation/ module with:
- ScenarioAxis abstractions (UnderlyingShift, VolShift, TimeDecay, CompositeScenario)
- ScenarioGrid for N-dimensional cartesian product evaluation
- MarketStateExtractor registry with BachelierExtractor
- SimulationEngine for analytical re-pricing across scenario grids
- simulate_package() convenience helper
- Full test coverage including integration test with STIRFutureOptionQuery

Design doc: docs/plans/2026-03-16-market-simulation-design.md"
```
