# Spread MDPs & EventContractsMDP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement 6 new MDPs (SpreadMDP base, IRSwapSpreadsMDP, IRBasisSwapsMDP, IRClearingHouseBasisSwapsMDP, STIRConvexityAdjustmentMDP, EventContractsMDP) with full query/structure/value/TB support.

**Architecture:** Composable SpreadMDP wraps two child MDPs and returns a SpreadPricer holding both underlying pricers. Each concrete spread MDP configures which child MDPs to use and how to split requests. EventContractsMDP is standalone with its own query layer. All MDPs integrate with the existing backtester via the ProductAdapter registry pattern.

**Tech Stack:** Python, rateslib, QuantLib (HW1F), GS Quant SDK (clearing house basis), Kalshi REST API (RSA-PSS auth), Polymarket REST API (no auth), pytest.

**Design doc:** `docs/plans/2026-03-15-spread-mdps-design.md`

---

## Task 1: SpreadPricer — the two-leg pricer wrapper

**Files:**
- Create: `MDP/Spreads/__init__.py`
- Create: `MDP/Spreads/SpreadPricer.py`
- Test: `tests/test_spread_pricer.py`

**Step 1: Write the failing test**

```python
# tests/test_spread_pricer.py
import pytest
from tests.conftest import MockPricer
import datetime


def _make_pricer(curve_name: str, base_rate: float) -> MockPricer:
    return MockPricer(curve_name=curve_name, as_of_date=datetime.date(2026, 3, 15), base_rate=base_rate)


class TestSpreadPricer:
    def test_holds_both_pricers(self):
        from MDP.Spreads.SpreadPricer import SpreadPricer

        pa = _make_pricer("USD-SOFR-1D", 0.04)
        pb = _make_pricer("USD-FEDFUNDS", 0.05)
        sp = SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={"id": "test"})
        assert sp.pricer_a is pa
        assert sp.pricer_b is pb

    def test_meta_data(self):
        from MDP.Spreads.SpreadPricer import SpreadPricer

        pa = _make_pricer("A", 0.04)
        pb = _make_pricer("B", 0.05)
        sp = SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={"id": "spread-test", "timestamp": "2026-03-15"})
        assert sp.meta_data["id"] == "spread-test"

    def test_spread_rate_delegates_to_legs(self):
        from MDP.Spreads.SpreadPricer import SpreadPricer

        pa = _make_pricer("A", 0.04)
        pb = _make_pricer("B", 0.05)
        sp = SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={})
        inst_a = pa.build_irswap(tenor="5Y")
        inst_b = pb.build_irswap(tenor="5Y")
        rate_a = pa.fair_rate(inst_a)
        rate_b = pb.fair_rate(inst_b)
        # SpreadPricer itself doesn't compute spread — that's the value map's job
        # But it should expose both pricers for the value map to use
        assert sp.pricer_a.fair_rate(inst_a) == rate_a
        assert sp.pricer_b.fair_rate(inst_b) == rate_b
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_spread_pricer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'MDP.Spreads'`

**Step 3: Write minimal implementation**

```python
# MDP/Spreads/__init__.py
# (empty)
```

```python
# MDP/Spreads/SpreadPricer.py
from __future__ import annotations
from typing import Any, Dict


class SpreadPricer:
    """
    Holds two pricers (leg A, leg B) for spread computations.

    The SpreadPricer itself does not compute spreads — it is a container
    that the SpreadValueFunctionMap uses to access both underlying pricers.
    """

    def __init__(self, pricer_a: Any, pricer_b: Any, meta_data: Dict[str, Any]):
        self.pricer_a = pricer_a
        self.pricer_b = pricer_b
        self._meta_data = meta_data

    @property
    def meta_data(self) -> Dict[str, Any]:
        return self._meta_data
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_spread_pricer.py -v`
Expected: PASS (3 passed)

**Step 5: Commit**

```bash
git add MDP/Spreads/__init__.py MDP/Spreads/SpreadPricer.py tests/test_spread_pricer.py
git commit -m "feat: add SpreadPricer two-leg pricer wrapper"
```

---

## Task 2: SpreadMDP — composable base class

**Files:**
- Create: `MDP/Spreads/SpreadMDP.py`
- Test: `tests/test_spread_mdp.py`

**Step 1: Write the failing test**

```python
# tests/test_spread_mdp.py
import pytest
import datetime
from tests.conftest import MockMDP


class TestSpreadMDP:
    def test_get_pricer_returns_spread_pricer(self):
        from MDP.Spreads.SpreadMDP import SpreadMDP
        from MDP.Spreads.SpreadPricer import SpreadPricer

        mdp_a = MockMDP(source="A", base_rate=0.04)
        mdp_b = MockMDP(source="B", base_rate=0.05)

        def splitter(request):
            ts = request["timestamp"]
            return (
                {"curve_name": request["curve_a"], "timestamp": ts},
                {"curve_name": request["curve_b"], "timestamp": ts},
            )

        spread_mdp = SpreadMDP(
            mdp_a=mdp_a,
            mdp_b=mdp_b,
            request_splitter=splitter,
            source="TEST-SPREAD",
        )

        result = spread_mdp.get_pricer({
            "curve_a": "USD-SOFR-1D",
            "curve_b": "USD-FEDFUNDS",
            "timestamp": datetime.date(2026, 3, 15),
        })

        assert isinstance(result, SpreadPricer)
        assert result.pricer_a.curve_name == "USD-SOFR-1D"
        assert result.pricer_b.curve_name == "USD-FEDFUNDS"

    def test_meta_data_includes_source(self):
        from MDP.Spreads.SpreadMDP import SpreadMDP

        mdp_a = MockMDP(source="A")
        mdp_b = MockMDP(source="B")

        def splitter(request):
            return (
                {"curve_name": "C1", "timestamp": request["timestamp"]},
                {"curve_name": "C2", "timestamp": request["timestamp"]},
            )

        spread_mdp = SpreadMDP(mdp_a=mdp_a, mdp_b=mdp_b, request_splitter=splitter, source="SRC")
        result = spread_mdp.get_pricer({"timestamp": datetime.date(2026, 1, 1)})
        assert "source" in result.meta_data
        assert result.meta_data["source"] == "SRC"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_spread_mdp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'MDP.Spreads.SpreadMDP'`

**Step 3: Write minimal implementation**

```python
# MDP/Spreads/SpreadMDP.py
from __future__ import annotations
from typing import Any, Callable, Dict, Tuple

from MDP.MarketDataProvider import MarketDataProvider
from MDP.Spreads.SpreadPricer import SpreadPricer


class SpreadMDP(MarketDataProvider):
    """
    Composable MDP that wraps two child MDPs and returns a SpreadPricer.

    Args:
        mdp_a: First leg market data provider
        mdp_b: Second leg market data provider
        request_splitter: Callable that splits a single request dict into (req_a, req_b)
        source: Source identifier string
    """

    def __init__(
        self,
        mdp_a: MarketDataProvider,
        mdp_b: MarketDataProvider,
        request_splitter: Callable[[Dict[str, Any]], Tuple[Dict[str, Any], Dict[str, Any]]],
        source: str,
        **kwargs: Any,
    ):
        super().__init__(source=source, **kwargs)
        self.mdp_a = mdp_a
        self.mdp_b = mdp_b
        self.request_splitter = request_splitter

    def get_pricer(self, request: Any) -> SpreadPricer:
        req_a, req_b = self.request_splitter(request)
        pricer_a = self.mdp_a.get_pricer(req_a)
        pricer_b = self.mdp_b.get_pricer(req_b)
        return SpreadPricer(
            pricer_a=pricer_a,
            pricer_b=pricer_b,
            meta_data={
                "source": self.source,
                "request": request,
            },
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_spread_mdp.py -v`
Expected: PASS (2 passed)

**Step 5: Commit**

```bash
git add MDP/Spreads/SpreadMDP.py tests/test_spread_mdp.py
git commit -m "feat: add SpreadMDP composable base class"
```

---

## Task 3: SpreadQuery, SpreadStructure, SpreadValue — query layer for spread products

**Files:**
- Create: `Query/Spreads/__init__.py`
- Create: `Query/Spreads/SpreadStructure.py`
- Create: `Query/Spreads/SpreadValue.py`
- Create: `Query/Spreads/SpreadQuery.py`
- Test: `tests/test_spread_query.py`

**Step 1: Write the failing test**

```python
# tests/test_spread_query.py
import pytest
import datetime


class TestSpreadEnums:
    def test_spread_structure_members(self):
        from Query.Spreads.SpreadStructure import SpreadStructure

        assert hasattr(SpreadStructure, "OUTRIGHT")
        assert hasattr(SpreadStructure, "CURVE")
        assert hasattr(SpreadStructure, "FLY")

    def test_spread_value_members(self):
        from Query.Spreads.SpreadValue import SpreadValue

        assert hasattr(SpreadValue, "SPREAD_BPS")
        assert hasattr(SpreadValue, "SPREAD_RATE")
        assert hasattr(SpreadValue, "LEG_A_RATE")
        assert hasattr(SpreadValue, "LEG_B_RATE")
        assert hasattr(SpreadValue, "PV01")
        assert hasattr(SpreadValue, "NPV")
        assert hasattr(SpreadValue, "CVX_ADJ_EMPIRICAL")
        assert hasattr(SpreadValue, "CVX_ADJ_HW1F")


class TestSpreadQuery:
    def test_basic_construction(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        assert q.product == "IRSPREAD"
        assert q.structure == SpreadStructure.OUTRIGHT
        assert q.tenor == "5Y"

    def test_curve_structure_from_tenor(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="2Y/10Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        assert q.structure == SpreadStructure.CURVE

    def test_build_mdp_request(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        assert "curve_a" in req
        assert "curve_b" in req
        assert req["curve_a"] == "USD-SOFR-1D"
        assert req["curve_b"] == "USD-FEDFUNDS"

    def test_col_name(self):
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        col = q.col_name()
        assert "5Y" in col
        assert "SPREAD_BPS" in col
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_spread_query.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# Query/Spreads/__init__.py
# (empty)
```

```python
# Query/Spreads/SpreadStructure.py
from enum import Enum, auto


class SpreadStructure(Enum):
    OUTRIGHT = auto()
    CURVE = auto()
    FLY = auto()
```

```python
# Query/Spreads/SpreadValue.py
from enum import Enum, auto


class SpreadValue(Enum):
    SPREAD_BPS = auto()
    SPREAD_RATE = auto()
    LEG_A_RATE = auto()
    LEG_B_RATE = auto()
    PV01 = auto()
    NPV = auto()
    CVX_ADJ_EMPIRICAL = auto()
    CVX_ADJ_HW1F = auto()
```

```python
# Query/Spreads/SpreadQuery.py
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.Spreads.SpreadStructure import SpreadStructure
from Query.Spreads.SpreadValue import SpreadValue
from Query.Spreads import adapter as _spread_adapter  # noqa: F401  (triggers register_product)


@dataclass(frozen=True)
class SpreadQuery(BaseQuery):
    """
    Query for spread products (IRSwapSpreads, IRBasis, ClearingHouseBasis, STIRCvxAdj).

    User-facing args:
      - structure: OUTRIGHT / CURVE / FLY
      - value: SPREAD_BPS, LEG_A_RATE, LEG_B_RATE, etc.
      - tenor: e.g., "5Y" or "2Y/10Y" for curve or "2Y/5Y/10Y" for fly
      - curve_a, curve_b: curve names for each leg
      - source_a, source_b: optional MDP source overrides per leg
      - product_key: which adapter to use ("IRSPREAD", "IRBASIS", "IRCHBASIS", "STIRCVX")
    """

    structure: SpreadStructure = SpreadStructure.OUTRIGHT
    value: Union[SpreadValue, List[SpreadValue]] = SpreadValue.SPREAD_BPS

    tenor: Optional[str] = None
    curve_a: Optional[str] = None
    curve_b: Optional[str] = None
    source_a: Optional[str] = None
    source_b: Optional[str] = None

    product_key: str = "IRSPREAD"

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="IRSPREAD")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", self.product_key)
        object.__setattr__(self, "structure_id", self.structure)

        # Auto-detect structure from tenor
        tenor_str = self.tenor or ""
        slash_count = tenor_str.count("/")
        if slash_count == 2:
            object.__setattr__(self, "structure", SpreadStructure.FLY)
            object.__setattr__(self, "structure_id", SpreadStructure.FLY)
        elif slash_count == 1:
            object.__setattr__(self, "structure", SpreadStructure.CURVE)
            object.__setattr__(self, "structure_id", SpreadStructure.CURVE)

        # Build structure_kwargs from tenor
        skw = dict(self.structure_kwargs or {})
        if self.tenor and "tenor" not in skw:
            skw["tenor"] = self.tenor
        if self.structure == SpreadStructure.CURVE and "/" in (self.tenor or ""):
            parts = [t.strip() for t in self.tenor.split("/")]
            if len(parts) == 2:
                skw.setdefault("front_tenor", parts[0])
                skw.setdefault("back_tenor", parts[1])
        elif self.structure == SpreadStructure.FLY and "/" in (self.tenor or ""):
            parts = [t.strip() for t in self.tenor.split("/")]
            if len(parts) == 3:
                skw.setdefault("front_tenor", parts[0])
                skw.setdefault("belly_tenor", parts[1])
                skw.setdefault("back_tenor", parts[2])
        object.__setattr__(self, "structure_kwargs", skw)

        # Build market_request
        mr = dict(self.market_request or {})
        if self.curve_a and "curve_a" not in mr:
            mr["curve_a"] = self.curve_a
        if self.curve_b and "curve_b" not in mr:
            mr["curve_b"] = self.curve_b
        if self.source_a:
            mr["source_a"] = self.source_a
        if self.source_b:
            mr["source_b"] = self.source_b
        object.__setattr__(self, "market_request", mr)

        # Sync value_id / value_ids
        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["SpreadQuery"]:
        if isinstance(self.value, list):
            from dataclasses import replace
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        prefix = f"{self.curve_a or ''} vs {self.curve_b or ''} " if self.curve_a else ""
        tenor_str = self.tenor or ""
        val_name = self.value.name if isinstance(self.value, SpreadValue) else "MULTI"
        return re.sub(r"\s\s+", " ", f"{prefix}{tenor_str} {val_name}").strip()

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def default_mtm_value_id(self) -> Any:
        return SpreadValue.SPREAD_BPS
```

**Note:** This references `Query.Spreads.adapter` which is built in Task 4. For this step, create a stub:

```python
# Query/Spreads/adapter.py (stub — full implementation in Task 4)
# (empty for now, will be populated in Task 4)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_spread_query.py -v`
Expected: PASS (5 passed)

**Step 5: Commit**

```bash
git add Query/Spreads/__init__.py Query/Spreads/SpreadStructure.py Query/Spreads/SpreadValue.py Query/Spreads/SpreadQuery.py Query/Spreads/adapter.py tests/test_spread_query.py
git commit -m "feat: add SpreadQuery, SpreadStructure, SpreadValue enums and query class"
```

---

## Task 4: SpreadProductAdapter — structure map + value map + registration

**Files:**
- Modify: `Query/Spreads/adapter.py` (replace stub)
- Test: `tests/test_spread_adapter.py`

**Context needed:** The adapter must:
1. `build_structure_map(pricer_or_curve)` — the pricer_or_curve here is a `SpreadPricer`. The structure map builds IRSwapQuery-style packages for EACH leg, using `pricer_a` and `pricer_b`.
2. `build_value_map(pricer_or_curve, package, risk_weights)` — computes spread metrics.
3. `edit_query(q, pricer_or_curve)` — no-op for now.

The "package" for a spread OUTRIGHT is a list with a single tuple `(swap_a, swap_b)` representing both legs of the spread at a given tenor. For CURVE, it's two such tuples, etc.

**Step 1: Write the failing test**

```python
# tests/test_spread_adapter.py
import pytest
import datetime
from tests.conftest import MockPricer
from MDP.Spreads.SpreadPricer import SpreadPricer


def _make_spread_pricer(rate_a=0.04, rate_b=0.05):
    pa = MockPricer("USD-SOFR-1D", datetime.date(2026, 3, 15), base_rate=rate_a)
    pb = MockPricer("USD-FEDFUNDS", datetime.date(2026, 3, 15), base_rate=rate_b)
    return SpreadPricer(pricer_a=pa, pricer_b=pb, meta_data={"source": "TEST"})


class TestSpreadAdapter:
    def test_adapter_registered(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        adapter_cls = get_adapter("IRSPREAD")
        assert adapter_cls is not None

    def test_build_structure_map_outright(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")
        # Package should contain spread leg pairs
        assert len(package) == 1
        assert len(weights) == 1

    def test_build_value_map_spread_bps(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")

        val_map = adapter.build_value_map(pricer_or_curve=sp, package=package, risk_weights=weights)
        spread_bps = val_map.apply(SpreadValue.SPREAD_BPS)
        # Should be (rate_a - rate_b) * 10000
        assert isinstance(spread_bps, float)

    def test_leg_a_rate(self):
        from Query.Base.product_adapter import get_adapter
        import Query.Spreads.adapter  # noqa: F401
        from Query.Spreads.SpreadStructure import SpreadStructure
        from Query.Spreads.SpreadValue import SpreadValue

        sp = _make_spread_pricer()
        adapter = get_adapter("IRSPREAD")()
        struct_map = adapter.build_structure_map(pricer_or_curve=sp)
        package, weights = struct_map.apply(SpreadStructure.OUTRIGHT, tenor="5Y")
        val_map = adapter.build_value_map(pricer_or_curve=sp, package=package, risk_weights=weights)

        leg_a = val_map.apply(SpreadValue.LEG_A_RATE)
        assert isinstance(leg_a, float)
        assert leg_a > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_spread_adapter.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# Query/Spreads/adapter.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Tuple

from Query.Base.product_adapter import ProductAdapter, register_product
from Query.Base.BaseStructure import BaseStructureFunctionMap
from Query.Base.BaseValue import BaseValueFunctionMap
from Query.Spreads.SpreadStructure import SpreadStructure
from Query.Spreads.SpreadValue import SpreadValue


@dataclass
class SpreadLegPair:
    """A pair of instruments (one from each leg) at a given tenor."""
    inst_a: Any  # instrument built from pricer_a
    inst_b: Any  # instrument built from pricer_b
    tenor: str = ""


class SpreadStructureFunctionMap(BaseStructureFunctionMap[SpreadStructure, SpreadLegPair]):
    def __init__(self, pricer_a: Any, pricer_b: Any, **common_kwargs: Any):
        self._pricer_a = pricer_a
        self._pricer_b = pricer_b
        super().__init__(SpreadStructure, pricer_a=pricer_a, pricer_b=pricer_b, **common_kwargs)

    def _create_map(self) -> Dict[SpreadStructure, Callable[..., Tuple[List[SpreadLegPair], List[float]]]]:
        return {
            SpreadStructure.OUTRIGHT: self._build_outright,
            SpreadStructure.CURVE: self._build_curve,
            SpreadStructure.FLY: self._build_fly,
        }

    def _build_leg_pair(self, tenor: str, **kwargs) -> SpreadLegPair:
        build_kw = {"tenor": tenor}
        if "bpv" in kwargs:
            build_kw["bpv"] = kwargs["bpv"]
        elif "notional" in kwargs:
            build_kw["notional"] = kwargs["notional"]
        inst_a = self._pricer_a.build_irswap(**build_kw)
        inst_b = self._pricer_b.build_irswap(**build_kw)
        return SpreadLegPair(inst_a=inst_a, inst_b=inst_b, tenor=tenor)

    def _build_outright(self, **kwargs) -> Tuple[List[SpreadLegPair], List[float]]:
        tenor = kwargs.get("tenor", "5Y")
        pair = self._build_leg_pair(tenor, **kwargs)
        return [pair], [1.0]

    def _build_curve(self, **kwargs) -> Tuple[List[SpreadLegPair], List[float]]:
        ft = kwargs["front_tenor"]
        bt = kwargs["back_tenor"]
        front_pair = self._build_leg_pair(ft, **kwargs)
        back_pair = self._build_leg_pair(bt, **kwargs)
        return [front_pair, back_pair], [-1.0, 1.0]

    def _build_fly(self, **kwargs) -> Tuple[List[SpreadLegPair], List[float]]:
        ft = kwargs["front_tenor"]
        belly = kwargs["belly_tenor"]
        bt = kwargs["back_tenor"]
        return (
            [self._build_leg_pair(ft, **kwargs), self._build_leg_pair(belly, **kwargs), self._build_leg_pair(bt, **kwargs)],
            [-0.5, 1.0, -0.5],
        )


class SpreadValueFunctionMap(BaseValueFunctionMap[SpreadValue, float]):
    def __init__(
        self,
        pricer_a: Any,
        pricer_b: Any,
        package: List[SpreadLegPair],
        risk_weights: List[float],
    ):
        self._pricer_a = pricer_a
        self._pricer_b = pricer_b
        super().__init__(
            SpreadValue,
            pricer_a=pricer_a,
            pricer_b=pricer_b,
            package=package,
            risk_weights=risk_weights,
        )

    def _create_map(self) -> Dict[SpreadValue, Callable[..., float]]:
        return {
            SpreadValue.SPREAD_RATE: self._spread_rate,
            SpreadValue.SPREAD_BPS: self._spread_bps,
            SpreadValue.LEG_A_RATE: self._leg_a_rate,
            SpreadValue.LEG_B_RATE: self._leg_b_rate,
            SpreadValue.PV01: self._pv01,
            SpreadValue.NPV: self._npv,
            SpreadValue.CVX_ADJ_EMPIRICAL: self._spread_bps,  # alias for spread MDPs
            SpreadValue.CVX_ADJ_HW1F: self._cvx_adj_hw1f,
        }

    def _spread_rate(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        rws: List[float] = kw["risk_weights"]
        pa = kw["pricer_a"]
        pb = kw["pricer_b"]
        return sum(
            rws[i] * (pa.fair_rate(pair.inst_a) - pb.fair_rate(pair.inst_b))
            for i, pair in enumerate(package)
        )

    def _spread_bps(self, **kw) -> float:
        return self._spread_rate(**kw) * 10_000

    def _leg_a_rate(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        rws: List[float] = kw["risk_weights"]
        pa = kw["pricer_a"]
        total = sum(rws[i] * pa.fair_rate(pair.inst_a) for i, pair in enumerate(package))
        n_legs = len(package)
        scale = 1.0 if n_legs == 1 else 10_000
        return total * scale

    def _leg_b_rate(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        rws: List[float] = kw["risk_weights"]
        pb = kw["pricer_b"]
        total = sum(rws[i] * pb.fair_rate(pair.inst_b) for i, pair in enumerate(package))
        n_legs = len(package)
        scale = 1.0 if n_legs == 1 else 10_000
        return total * scale

    def _pv01(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        pa = kw["pricer_a"]
        pb = kw["pricer_b"]
        return sum(pa.pv01(p.inst_a) + pb.pv01(p.inst_b) for p in package)

    def _npv(self, **kw) -> float:
        package: List[SpreadLegPair] = kw["package"]
        pa = kw["pricer_a"]
        pb = kw["pricer_b"]
        return sum(pa.npv(p.inst_a) - pb.npv(p.inst_b) for p in package)

    def _cvx_adj_hw1f(self, **kw) -> float:
        raise NotImplementedError("HW1F convexity adjustment requires hw1f_model — see STIRConvexityAdjustmentMDP")


class SpreadProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> SpreadStructureFunctionMap:
        return SpreadStructureFunctionMap(
            pricer_a=pricer_or_curve.pricer_a,
            pricer_b=pricer_or_curve.pricer_b,
        )

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[Any],
        risk_weights: List[float],
    ) -> SpreadValueFunctionMap:
        return SpreadValueFunctionMap(
            pricer_a=pricer_or_curve.pricer_a,
            pricer_b=pricer_or_curve.pricer_b,
            package=package,
            risk_weights=risk_weights,
        )

    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        return q


register_product("IRSPREAD", SpreadProductAdapter)
register_product("IRBASIS", SpreadProductAdapter)
register_product("IRCHBASIS", SpreadProductAdapter)
register_product("STIRCVX", SpreadProductAdapter)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_spread_adapter.py -v`
Expected: PASS (4 passed)

**Step 5: Commit**

```bash
git add Query/Spreads/adapter.py tests/test_spread_adapter.py
git commit -m "feat: add SpreadProductAdapter with structure map and value map"
```

---

## Task 5: IRSwapSpreadsMDP — generic swap-vs-benchmark spreads

**Files:**
- Modify: `MDP/IRSwapSpreads/IRSwapSpreadsMDP.py` (replace empty stub)
- Test: `tests/test_ir_swap_spreads_mdp.py`

**Step 1: Write the failing test**

```python
# tests/test_ir_swap_spreads_mdp.py
import pytest
import datetime
from tests.conftest import MockMDP
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestIRSwapSpreadsMDP:
    def test_construction(self):
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP

        mdp = IRSwapSpreadsMDP(source_a="MOCK_A", source_b="MOCK_B")
        assert mdp.source == "IRSWAP_SPREAD"

    def test_get_pricer_with_mock(self):
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP

        mdp = IRSwapSpreadsMDP(
            source_a="MOCK_A",
            source_b="MOCK_B",
            _mdp_a=MockMDP(source="A", base_rate=0.04),
            _mdp_b=MockMDP(source="B", base_rate=0.05),
        )
        result = mdp.get_pricer({
            "curve_a": "USD-SOFR-1D",
            "curve_b": "USD-OIS",
            "timestamp": datetime.date(2026, 3, 15),
        })
        assert isinstance(result, SpreadPricer)
        assert result.pricer_a.curve_name == "USD-SOFR-1D"
        assert result.pricer_b.curve_name == "USD-OIS"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ir_swap_spreads_mdp.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# MDP/IRSwapSpreads/IRSwapSpreadsMDP.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple

from MDP.Spreads.SpreadMDP import SpreadMDP


def _default_request_splitter(request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ts = request.get("timestamp")
    req_a = {"curve_name": request["curve_a"], "timestamp": ts}
    req_b = {"curve_name": request["curve_b"], "timestamp": ts}
    # Pass through any extra keys
    for k, v in request.items():
        if k not in ("curve_a", "curve_b", "timestamp", "source_a", "source_b"):
            req_a[k] = v
            req_b[k] = v
    return req_a, req_b


class IRSwapSpreadsMDP(SpreadMDP):
    """
    Generic swap-vs-benchmark spread MDP.

    Wraps two IRSwapsMDP instances with potentially different curves or sources.
    Does NOT break existing IRSwapValue.MMSS (that remains single-curve).

    Request dict:
        curve_a: str       — first curve name (e.g., "USD-SOFR-1D")
        curve_b: str       — second curve name (e.g., "USD-OIS")
        timestamp: date/datetime
    """

    def __init__(
        self,
        source_a: str = "BARCHART_STIRF-RL",
        source_b: str = "BARCHART_STIRF-RL",
        *,
        _mdp_a: Any = None,
        _mdp_b: Any = None,
        **kwargs: Any,
    ):
        if _mdp_a is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_a = IRSwapsMDP(source=source_a)
        if _mdp_b is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_b = IRSwapsMDP(source=source_b)

        super().__init__(
            mdp_a=_mdp_a,
            mdp_b=_mdp_b,
            request_splitter=_default_request_splitter,
            source="IRSWAP_SPREAD",
            **kwargs,
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ir_swap_spreads_mdp.py -v`
Expected: PASS (2 passed)

**Step 5: Commit**

```bash
git add MDP/IRSwapSpreads/IRSwapSpreadsMDP.py tests/test_ir_swap_spreads_mdp.py
git commit -m "feat: add IRSwapSpreadsMDP for generic swap-vs-benchmark spreads"
```

---

## Task 6: IRBasisSwapsMDP — SOFR vs OIS/Fed Funds basis

**Files:**
- Create: `MDP/IRBasisSwaps/__init__.py`
- Create: `MDP/IRBasisSwaps/IRBasisSwapsMDP.py`
- Test: `tests/test_ir_basis_swaps_mdp.py`

**Step 1: Write the failing test**

```python
# tests/test_ir_basis_swaps_mdp.py
import pytest
import datetime
from tests.conftest import MockMDP
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestIRBasisSwapsMDP:
    def test_construction(self):
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP

        mdp = IRBasisSwapsMDP()
        assert mdp.source == "IRBASIS_BARCHART_STIRF-RL"

    def test_get_pricer_with_mock(self):
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP

        mdp = IRBasisSwapsMDP(
            _mdp_a=MockMDP(source="SOFR", base_rate=0.04),
            _mdp_b=MockMDP(source="FF", base_rate=0.038),
        )
        result = mdp.get_pricer({
            "tenor": "5Y",
            "timestamp": datetime.date(2026, 3, 15),
        })
        assert isinstance(result, SpreadPricer)

    def test_default_curves(self):
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP

        mdp = IRBasisSwapsMDP(
            _mdp_a=MockMDP(source="SOFR", base_rate=0.04),
            _mdp_b=MockMDP(source="FF", base_rate=0.038),
        )
        result = mdp.get_pricer({
            "timestamp": datetime.date(2026, 3, 15),
        })
        assert isinstance(result, SpreadPricer)
        # Default curves should be SOFR and FEDFUNDS
        assert result.pricer_a.curve_name == "USD-SOFR-1D-Q12STIRT"
        assert result.pricer_b.curve_name == "USD-FEDFUNDS"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ir_basis_swaps_mdp.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# MDP/IRBasisSwaps/__init__.py
# (empty)
```

```python
# MDP/IRBasisSwaps/IRBasisSwapsMDP.py
from __future__ import annotations
from typing import Any, Dict, Tuple

from MDP.Spreads.SpreadMDP import SpreadMDP


def _basis_request_splitter(request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ts = request.get("timestamp")
    curve_a = request.get("curve_a", "USD-SOFR-1D-Q12STIRT")
    curve_b = request.get("curve_b", "USD-FEDFUNDS")
    req_a = {"curve_name": curve_a, "timestamp": ts}
    req_b = {"curve_name": curve_b, "timestamp": ts}
    return req_a, req_b


class IRBasisSwapsMDP(SpreadMDP):
    """
    SOFR vs OIS/Fed Funds basis spread MDP.

    Default: BARCHART_STIRF-RL source, USD-SOFR-1D-Q12STIRT vs USD-FEDFUNDS curves.

    Request dict:
        timestamp: date/datetime
        curve_a: str (optional, default "USD-SOFR-1D-Q12STIRT")
        curve_b: str (optional, default "USD-FEDFUNDS")
    """

    def __init__(
        self,
        source: str = "BARCHART_STIRF-RL",
        *,
        _mdp_a: Any = None,
        _mdp_b: Any = None,
        **kwargs: Any,
    ):
        if _mdp_a is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_a = IRSwapsMDP(source=source)
        if _mdp_b is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_b = IRSwapsMDP(source=source)

        super().__init__(
            mdp_a=_mdp_a,
            mdp_b=_mdp_b,
            request_splitter=_basis_request_splitter,
            source=f"IRBASIS_{source}",
            **kwargs,
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ir_basis_swaps_mdp.py -v`
Expected: PASS (3 passed)

**Step 5: Commit**

```bash
git add MDP/IRBasisSwaps/__init__.py MDP/IRBasisSwaps/IRBasisSwapsMDP.py tests/test_ir_basis_swaps_mdp.py
git commit -m "feat: add IRBasisSwapsMDP for SOFR vs OIS/Fed Funds basis"
```

---

## Task 7: IRClearingHouseBasisSwapsMDP — LCH vs CME basis from GS Quant

**Files:**
- Create: `MDP/IRClearingHouseBasisSwaps/__init__.py`
- Create: `MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py`
- Create: `MDP/IRClearingHouseBasisSwaps/IRClearingHouseBasisSwapsMDP.py`
- Test: `tests/test_ir_clearing_house_basis_mdp.py`

**Step 1: Write the failing test**

```python
# tests/test_ir_clearing_house_basis_mdp.py
import pytest
import datetime


class TestGSQunatFetcher:
    def test_parse_coverage_name(self):
        from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import parse_coverage_name

        result = parse_coverage_name("USD Swap SOFR 1y ATM 0b to 5y CME Cleared")
        assert result["ccy"] == "USD"
        assert result["index"] == "SOFR"
        assert result["tenor"] == "5y"
        assert result["clearing_house"] == "CME"

    def test_find_asset_pair(self):
        from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import find_asset_pair
        import pandas as pd

        coverage = pd.DataFrame({
            "name": [
                "USD Swap SOFR 1y ATM 0b to 5y CME Cleared",
                "USD Swap SOFR 1y ATM 0b to 5y LCH Cleared",
                "EUR Swap LIBOR 6m ATM 0b to 10y EUREX Cleared",
            ],
            "assetId": ["asset_cme_5y", "asset_lch_5y", "asset_eur_10y"],
        })
        pair = find_asset_pair(
            coverage, ccy="USD", index="SOFR", tenor="5y",
            clearing_house_a="LCH", clearing_house_b="CME",
        )
        assert pair["asset_id_a"] == "asset_lch_5y"
        assert pair["asset_id_b"] == "asset_cme_5y"


class TestIRClearingHouseBasisSwapsMDP:
    def test_construction(self):
        from MDP.IRClearingHouseBasisSwaps.IRClearingHouseBasisSwapsMDP import IRClearingHouseBasisSwapsMDP

        mdp = IRClearingHouseBasisSwapsMDP(
            coverage_path="dummy.xlsx",
            gs_client_id="test",
            gs_secret_key="test",
        )
        assert mdp.source == "GSQUANT_CH_BASIS"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ir_clearing_house_basis_mdp.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# MDP/IRClearingHouseBasisSwaps/__init__.py
# (empty)
```

```python
# MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py
from __future__ import annotations
import re
from typing import Any, Dict, Optional

import pandas as pd


_NAME_PATTERN = re.compile(
    r"^(?P<ccy>\w+)\s+Swap\s+(?P<index>\S+)\s+\S+\s+ATM\s+\S+\s+to\s+(?P<tenor>\S+)\s+(?P<clearing_house>\w+)\s+Cleared$"
)


def parse_coverage_name(name: str) -> Optional[Dict[str, str]]:
    """Parse a GS coverage name like 'USD Swap SOFR 1y ATM 0b to 5y CME Cleared'."""
    m = _NAME_PATTERN.match(name)
    if not m:
        return None
    return m.groupdict()


def find_asset_pair(
    coverage: pd.DataFrame,
    ccy: str,
    index: str,
    tenor: str,
    clearing_house_a: str = "LCH",
    clearing_house_b: str = "CME",
) -> Dict[str, str]:
    """Find the assetId pair for two clearing houses at the same tenor."""
    asset_id_a = None
    asset_id_b = None

    for _, row in coverage.iterrows():
        parsed = parse_coverage_name(row["name"])
        if parsed is None:
            continue
        if parsed["ccy"].upper() != ccy.upper():
            continue
        if parsed["index"].upper() != index.upper():
            continue
        if parsed["tenor"].lower() != tenor.lower():
            continue
        if parsed["clearing_house"].upper() == clearing_house_a.upper():
            asset_id_a = row["assetId"]
        elif parsed["clearing_house"].upper() == clearing_house_b.upper():
            asset_id_b = row["assetId"]

    if asset_id_a is None or asset_id_b is None:
        raise ValueError(
            f"Could not find asset pair for {ccy} {index} {tenor} "
            f"{clearing_house_a}/{clearing_house_b}"
        )
    return {"asset_id_a": asset_id_a, "asset_id_b": asset_id_b}


def fetch_clearing_house_basis(
    asset_id_a: str,
    asset_id_b: str,
    start: Any,
    end: Any,
    gs_client_id: str,
    gs_secret_key: str,
) -> pd.DataFrame:
    """Fetch rate timeseries for both clearing houses from GS Quant and compute basis in bps."""
    from gs_quant.data import Dataset
    from gs_quant.session import GsSession

    GsSession.use(
        client_id=gs_client_id,
        client_secret=gs_secret_key,
        scopes=GsSession.Scopes.get_default(),
    )

    df = Dataset("IR_SWAP_RATES_V1_STANDARD").get_data(start, end, assetId=[asset_id_a, asset_id_b])

    df_a = df[df["assetId"] == asset_id_a][["date", "rate"]].set_index("date").rename(columns={"rate": "rate_a"})
    df_b = df[df["assetId"] == asset_id_b][["date", "rate"]].set_index("date").rename(columns={"rate": "rate_b"})

    merged = df_a.join(df_b, how="inner")
    merged["basis_bps"] = (merged["rate_a"] - merged["rate_b"]) * 10_000
    return merged
```

```python
# MDP/IRClearingHouseBasisSwaps/IRClearingHouseBasisSwapsMDP.py
from __future__ import annotations
from typing import Any, Dict, Optional

import pandas as pd

from MDP.MarketDataProvider import MarketDataProvider


class ClearingHouseBasisPricer:
    """Pricer wrapping pre-fetched clearing house basis data."""

    def __init__(self, basis_data: pd.DataFrame, meta_data: Dict[str, Any]):
        self._basis_data = basis_data
        self._meta_data = meta_data

    @property
    def meta_data(self) -> Dict[str, Any]:
        return self._meta_data

    @property
    def basis_data(self) -> pd.DataFrame:
        return self._basis_data


class IRClearingHouseBasisSwapsMDP(MarketDataProvider):
    """
    LCH vs CME clearing house basis from GS Quant IR_SWAP_RATES_V1_STANDARD.

    Request dict:
        tenor: str              — e.g., "5y"
        ccy: str                — default "USD"
        index: str              — default "SOFR"
        clearing_house_a: str   — default "LCH"
        clearing_house_b: str   — default "CME"
        start: date
        end: date
    """

    def __init__(
        self,
        coverage_path: str,
        gs_client_id: str,
        gs_secret_key: str,
        **kwargs: Any,
    ):
        super().__init__(source="GSQUANT_CH_BASIS", **kwargs)
        self._coverage_path = coverage_path
        self._gs_client_id = gs_client_id
        self._gs_secret_key = gs_secret_key
        self._coverage: Optional[pd.DataFrame] = None

    def _load_coverage(self) -> pd.DataFrame:
        if self._coverage is None:
            self._coverage = pd.read_excel(self._coverage_path)
        return self._coverage

    def get_pricer(self, request: Any) -> ClearingHouseBasisPricer:
        from MDP.IRClearingHouseBasisSwaps.gs_quant_fetcher import find_asset_pair, fetch_clearing_house_basis

        coverage = self._load_coverage()
        tenor = request.get("tenor", "5y")
        ccy = request.get("ccy", "USD")
        index = request.get("index", "SOFR")
        ch_a = request.get("clearing_house_a", "LCH")
        ch_b = request.get("clearing_house_b", "CME")
        start = request.get("start")
        end = request.get("end")

        pair = find_asset_pair(coverage, ccy=ccy, index=index, tenor=tenor,
                               clearing_house_a=ch_a, clearing_house_b=ch_b)

        basis_data = fetch_clearing_house_basis(
            asset_id_a=pair["asset_id_a"],
            asset_id_b=pair["asset_id_b"],
            start=start,
            end=end,
            gs_client_id=self._gs_client_id,
            gs_secret_key=self._gs_secret_key,
        )

        return ClearingHouseBasisPricer(
            basis_data=basis_data,
            meta_data={
                "source": self.source,
                "tenor": tenor,
                "ccy": ccy,
                "index": index,
                "clearing_house_a": ch_a,
                "clearing_house_b": ch_b,
            },
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ir_clearing_house_basis_mdp.py -v`
Expected: PASS (3 passed)

**Step 5: Commit**

```bash
git add MDP/IRClearingHouseBasisSwaps/__init__.py MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py MDP/IRClearingHouseBasisSwaps/IRClearingHouseBasisSwapsMDP.py tests/test_ir_clearing_house_basis_mdp.py
git commit -m "feat: add IRClearingHouseBasisSwapsMDP with GS Quant fetcher"
```

---

## Task 8: STIRConvexityAdjustmentMDP — empirical (SpreadMDP) + analytical (HW1F)

**Files:**
- Create: `MDP/STIRConvexityAdjustment/__init__.py`
- Create: `MDP/STIRConvexityAdjustment/hw1f_model.py`
- Create: `MDP/STIRConvexityAdjustment/STIRConvexityAdjustmentMDP.py`
- Test: `tests/test_stir_convexity_adjustment_mdp.py`

**Step 1: Write the failing test**

```python
# tests/test_stir_convexity_adjustment_mdp.py
import pytest
import datetime
import math
from tests.conftest import MockMDP
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestHW1FModel:
    def test_convexity_adjustment(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment

        # Known formula: (sigma^2 / 2a^2) * (1 - e^(-a*T1)) * (1 - e^(-a*T2))
        a = 0.03       # mean reversion
        sigma = 0.01   # volatility
        T1 = 1.0       # start of accrual
        T2 = 1.25      # end of accrual

        result = hw1f_convexity_adjustment(a=a, sigma=sigma, T1=T1, T2=T2)
        expected = (sigma**2 / (2 * a**2)) * (1 - math.exp(-a * T1)) * (1 - math.exp(-a * T2))
        assert abs(result - expected) < 1e-12

    def test_zero_mean_reversion_raises(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment

        with pytest.raises(ValueError):
            hw1f_convexity_adjustment(a=0.0, sigma=0.01, T1=1.0, T2=1.25)

    def test_convexity_increases_with_maturity(self):
        from MDP.STIRConvexityAdjustment.hw1f_model import hw1f_convexity_adjustment

        adj_short = hw1f_convexity_adjustment(a=0.03, sigma=0.01, T1=0.25, T2=0.5)
        adj_long = hw1f_convexity_adjustment(a=0.03, sigma=0.01, T1=5.0, T2=5.25)
        assert adj_long > adj_short


class TestSTIRConvexityAdjustmentMDP:
    def test_construction(self):
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP

        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )
        assert mdp.source == "STIRCVX_EMPIRICAL"

    def test_get_pricer_returns_spread_pricer(self):
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP

        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )
        result = mdp.get_pricer({
            "curve_name": "USD-SOFR-1D",
            "timestamp": datetime.date(2026, 3, 15),
        })
        assert isinstance(result, SpreadPricer)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_stir_convexity_adjustment_mdp.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# MDP/STIRConvexityAdjustment/__init__.py
# (empty)
```

```python
# MDP/STIRConvexityAdjustment/hw1f_model.py
"""Hull-White 1-Factor convexity adjustment for STIR futures vs swaps."""
from __future__ import annotations
import math


def hw1f_convexity_adjustment(
    a: float,
    sigma: float,
    T1: float,
    T2: float,
) -> float:
    """
    Compute the Hull-White 1-factor convexity adjustment.

    The adjustment is the difference between the futures rate and the forward rate:
        CA = (sigma^2 / 2a^2) * (1 - e^(-a*T1)) * (1 - e^(-a*T2))

    Args:
        a: Mean reversion speed (must be > 0)
        sigma: Short rate volatility
        T1: Start of accrual period (years from now)
        T2: End of accrual period (years from now)

    Returns:
        Convexity adjustment in rate terms (multiply by 10000 for bps)
    """
    if a <= 0:
        raise ValueError(f"Mean reversion 'a' must be positive, got {a}")
    return (sigma**2 / (2 * a**2)) * (1 - math.exp(-a * T1)) * (1 - math.exp(-a * T2))
```

```python
# MDP/STIRConvexityAdjustment/STIRConvexityAdjustmentMDP.py
from __future__ import annotations
from typing import Any, Dict, Tuple

from MDP.Spreads.SpreadMDP import SpreadMDP


def _cvx_request_splitter(request: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Split request for cvx adj: leg A = futures-implied (no cvx), leg B = swap curve (with cvx).
    Both use the same curve_name and timestamp.
    """
    ts = request.get("timestamp")
    curve_name = request.get("curve_name", "USD-SOFR-1D")
    curve_name_a = request.get("curve_name_a", f"{curve_name}-Q12STIRT")
    curve_name_b = request.get("curve_name_b", curve_name)
    req_a = {"curve_name": curve_name_a, "timestamp": ts}
    req_b = {"curve_name": curve_name_b, "timestamp": ts}
    return req_a, req_b


class STIRConvexityAdjustmentMDP(SpreadMDP):
    """
    STIR Convexity Adjustment MDP.

    Empirical mode: computes cvx adj as the difference between
    BARCHART_STIRF-RL (futures-implied, no cvx) and ERIS_EOD_LIVE-RL_BASIC-NOJUMPS (swap curve, with cvx).

    Analytical mode: use hw1f_model.hw1f_convexity_adjustment() directly.

    Request dict:
        curve_name: str         — base curve (default "USD-SOFR-1D")
        curve_name_a: str       — optional override for no-cvx leg
        curve_name_b: str       — optional override for with-cvx leg
        timestamp: datetime
    """

    def __init__(
        self,
        source_a: str = "BARCHART_STIRF-RL",
        source_b: str = "ERIS_EOD_LIVE-RL_BASIC-NOJUMPS",
        *,
        _mdp_a: Any = None,
        _mdp_b: Any = None,
        **kwargs: Any,
    ):
        if _mdp_a is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_a = IRSwapsMDP(source=source_a)
        if _mdp_b is None:
            from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
            _mdp_b = IRSwapsMDP(source=source_b)

        super().__init__(
            mdp_a=_mdp_a,
            mdp_b=_mdp_b,
            request_splitter=_cvx_request_splitter,
            source="STIRCVX_EMPIRICAL",
            **kwargs,
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_stir_convexity_adjustment_mdp.py -v`
Expected: PASS (5 passed)

**Step 5: Commit**

```bash
git add MDP/STIRConvexityAdjustment/__init__.py MDP/STIRConvexityAdjustment/hw1f_model.py MDP/STIRConvexityAdjustment/STIRConvexityAdjustmentMDP.py tests/test_stir_convexity_adjustment_mdp.py
git commit -m "feat: add STIRConvexityAdjustmentMDP with empirical + HW1F analytical"
```

---

## Task 9: EventContractsMDP — Kalshi fetcher

**Files:**
- Create: `MDP/EventContracts/__init__.py`
- Create: `MDP/EventContracts/kalshi_fetcher.py`
- Test: `tests/test_kalshi_fetcher.py`

**Context:** Kalshi API requires RSA-PSS signature auth. Base URL: `https://api.elections.kalshi.com/trade-api/v2`. Historical candlesticks: `GET /historical/markets/{ticker}/candlesticks` (no auth). Live candlesticks: `GET /series/{series_ticker}/markets/{ticker}/candlesticks` (auth required). Response has `candlesticks[].price.close_dollars`, `volume_fp`, `open_interest_fp`, `end_period_ts`.

**Step 1: Write the failing test**

```python
# tests/test_kalshi_fetcher.py
import pytest
import datetime


class TestKalshiFetcher:
    def test_build_auth_headers_structure(self):
        from MDP.EventContracts.kalshi_fetcher import build_kalshi_auth_headers

        # Test that it returns the right header keys (without real key)
        # This should raise if no private key provided
        with pytest.raises(Exception):
            build_kalshi_auth_headers(
                method="GET",
                path="/trade-api/v2/markets",
                api_key_id="test-key",
                private_key_pem=None,
            )

    def test_parse_candlestick_response(self):
        from MDP.EventContracts.kalshi_fetcher import parse_candlestick_response

        raw = {
            "ticker": "TEST-TICKER",
            "candlesticks": [
                {
                    "end_period_ts": 1710532800,
                    "price": {
                        "open_dollars": "0.5500",
                        "low_dollars": "0.5000",
                        "high_dollars": "0.6000",
                        "close_dollars": "0.5800",
                        "mean_dollars": "0.5500",
                        "previous_dollars": "0.5400",
                    },
                    "volume_fp": "150.00",
                    "open_interest_fp": "500.00",
                },
                {
                    "end_period_ts": 1710619200,
                    "price": {
                        "open_dollars": "0.5800",
                        "low_dollars": "0.5600",
                        "high_dollars": "0.6200",
                        "close_dollars": "0.6000",
                        "mean_dollars": "0.5900",
                        "previous_dollars": "0.5800",
                    },
                    "volume_fp": "200.00",
                    "open_interest_fp": "550.00",
                },
            ],
        }

        df = parse_candlestick_response(raw)
        assert len(df) == 2
        assert "close" in df.columns
        assert "volume" in df.columns
        assert "open_interest" in df.columns
        assert df["close"].iloc[0] == pytest.approx(0.58)
        assert df["volume"].iloc[0] == pytest.approx(150.0)

    def test_historical_url_construction(self):
        from MDP.EventContracts.kalshi_fetcher import build_historical_candlestick_url

        url = build_historical_candlestick_url(
            ticker="KXFED-26MAR19",
            start_ts=1710000000,
            end_ts=1710600000,
            period_interval=1440,
        )
        assert "KXFED-26MAR19" in url
        assert "period_interval=1440" in url
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_kalshi_fetcher.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# MDP/EventContracts/__init__.py
# (empty)
```

```python
# MDP/EventContracts/kalshi_fetcher.py
"""Kalshi REST API client for historical and live event contract data."""
from __future__ import annotations

import base64
import datetime
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import pandas as pd
import requests

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


def build_kalshi_auth_headers(
    method: str,
    path: str,
    api_key_id: str,
    private_key_pem: Optional[str],
) -> Dict[str, str]:
    """
    Build RSA-PSS signed auth headers for Kalshi API.

    The signature is: base64(RSA-PSS-SHA256(timestamp_ms + method + path))
    """
    if private_key_pem is None:
        raise ValueError("Kalshi private key PEM is required for authenticated endpoints")

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    timestamp_ms = str(int(time.time() * 1000))
    message = (timestamp_ms + method.upper() + path).encode("utf-8")

    private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )

    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
    }


def build_historical_candlestick_url(
    ticker: str,
    start_ts: int,
    end_ts: int,
    period_interval: int = 1440,
) -> str:
    """Build URL for historical (no-auth) candlestick endpoint."""
    params = urlencode({
        "start_ts": start_ts,
        "end_ts": end_ts,
        "period_interval": period_interval,
    })
    return f"{KALSHI_BASE_URL}/historical/markets/{ticker}/candlesticks?{params}"


def parse_candlestick_response(raw: Dict[str, Any]) -> pd.DataFrame:
    """Parse Kalshi candlestick JSON response into a DataFrame."""
    rows = []
    for candle in raw.get("candlesticks", []):
        ts = candle.get("end_period_ts", 0)
        price = candle.get("price") or {}
        rows.append({
            "timestamp": datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc),
            "open": _parse_fp(price.get("open_dollars")),
            "high": _parse_fp(price.get("high_dollars")),
            "low": _parse_fp(price.get("low_dollars")),
            "close": _parse_fp(price.get("close_dollars")),
            "mean": _parse_fp(price.get("mean_dollars")),
            "volume": _parse_fp(candle.get("volume_fp")),
            "open_interest": _parse_fp(candle.get("open_interest_fp")),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("timestamp")
    return df


def _parse_fp(val: Optional[str]) -> Optional[float]:
    """Parse Kalshi FixedPoint string to float."""
    if val is None:
        return None
    return float(val)


def fetch_historical_candlesticks(
    ticker: str,
    start: datetime.datetime,
    end: datetime.datetime,
    period_interval: int = 1440,
) -> pd.DataFrame:
    """Fetch historical candlestick data from Kalshi (no auth required)."""
    url = build_historical_candlestick_url(
        ticker=ticker,
        start_ts=int(start.timestamp()),
        end_ts=int(end.timestamp()),
        period_interval=period_interval,
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return parse_candlestick_response(resp.json())


def fetch_live_candlesticks(
    series_ticker: str,
    ticker: str,
    start: datetime.datetime,
    end: datetime.datetime,
    period_interval: int = 1440,
    api_key_id: str = "",
    private_key_pem: str = "",
) -> pd.DataFrame:
    """Fetch live candlestick data from Kalshi (auth required)."""
    path = f"/trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks"
    params = urlencode({
        "start_ts": int(start.timestamp()),
        "end_ts": int(end.timestamp()),
        "period_interval": period_interval,
    })
    url = f"{KALSHI_BASE_URL}/series/{series_ticker}/markets/{ticker}/candlesticks?{params}"
    headers = build_kalshi_auth_headers("GET", path, api_key_id, private_key_pem)
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return parse_candlestick_response(resp.json())
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_kalshi_fetcher.py -v`
Expected: PASS (3 passed)

**Step 5: Commit**

```bash
git add MDP/EventContracts/__init__.py MDP/EventContracts/kalshi_fetcher.py tests/test_kalshi_fetcher.py
git commit -m "feat: add Kalshi REST API fetcher with RSA-PSS auth and candlestick parsing"
```

---

## Task 10: EventContractsMDP — Polymarket fetcher

**Files:**
- Create: `MDP/EventContracts/polymarket_fetcher.py`
- Test: `tests/test_polymarket_fetcher.py`

**Context:** Polymarket CLOB API. Base URL: `https://clob.polymarket.com`. Price history: `GET /prices-history?market={asset_id}&startTs={ts}&endTs={ts}&interval={interval}&fidelity={min}`. No auth. Response: `{ "history": [{ "t": unix_ts, "p": 0.0-1.0 }] }`.

**Step 1: Write the failing test**

```python
# tests/test_polymarket_fetcher.py
import pytest
import datetime


class TestPolymarketFetcher:
    def test_parse_price_history(self):
        from MDP.EventContracts.polymarket_fetcher import parse_price_history

        raw = {
            "history": [
                {"t": 1710532800, "p": 0.65},
                {"t": 1710619200, "p": 0.70},
                {"t": 1710705600, "p": 0.68},
            ]
        }
        df = parse_price_history(raw)
        assert len(df) == 3
        assert "price" in df.columns
        assert df["price"].iloc[0] == pytest.approx(0.65)

    def test_build_url(self):
        from MDP.EventContracts.polymarket_fetcher import build_price_history_url

        url = build_price_history_url(
            market_id="0x1234abc",
            start_ts=1710000000,
            end_ts=1710600000,
            interval="1d",
        )
        assert "market=0x1234abc" in url
        assert "interval=1d" in url
        assert "clob.polymarket.com" in url
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_polymarket_fetcher.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# MDP/EventContracts/polymarket_fetcher.py
"""Polymarket CLOB API client for price history data."""
from __future__ import annotations

import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import pandas as pd
import requests

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"


def build_price_history_url(
    market_id: str,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    interval: str = "1d",
    fidelity: int = 1,
) -> str:
    """Build URL for Polymarket price history endpoint."""
    params: Dict[str, Any] = {"market": market_id}
    if start_ts is not None:
        params["startTs"] = start_ts
    if end_ts is not None:
        params["endTs"] = end_ts
    params["interval"] = interval
    params["fidelity"] = fidelity
    return f"{POLYMARKET_CLOB_URL}/prices-history?{urlencode(params)}"


def parse_price_history(raw: Dict[str, Any]) -> pd.DataFrame:
    """Parse Polymarket price history JSON into a DataFrame."""
    rows = []
    for point in raw.get("history", []):
        rows.append({
            "timestamp": datetime.datetime.fromtimestamp(point["t"], tz=datetime.timezone.utc),
            "price": float(point["p"]),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.set_index("timestamp")
    return df


def fetch_price_history(
    market_id: str,
    start: Optional[datetime.datetime] = None,
    end: Optional[datetime.datetime] = None,
    interval: str = "1d",
    fidelity: int = 1,
) -> pd.DataFrame:
    """Fetch price history from Polymarket CLOB API (no auth required)."""
    url = build_price_history_url(
        market_id=market_id,
        start_ts=int(start.timestamp()) if start else None,
        end_ts=int(end.timestamp()) if end else None,
        interval=interval,
        fidelity=fidelity,
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return parse_price_history(resp.json())
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_polymarket_fetcher.py -v`
Expected: PASS (2 passed)

**Step 5: Commit**

```bash
git add MDP/EventContracts/polymarket_fetcher.py tests/test_polymarket_fetcher.py
git commit -m "feat: add Polymarket CLOB API fetcher for price history"
```

---

## Task 11: EventContractsMDP — main MDP + pricer

**Files:**
- Create: `MDP/EventContracts/EventContractsMDP.py`
- Test: `tests/test_event_contracts_mdp.py`

**Step 1: Write the failing test**

```python
# tests/test_event_contracts_mdp.py
import pytest
import datetime
import pandas as pd


class TestEventContractPricer:
    def test_pricer_holds_data(self):
        from MDP.EventContracts.EventContractsMDP import EventContractPricer

        data = pd.DataFrame({"price": [0.5, 0.6]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={"ticker": "TEST"})
        assert len(pricer.data) == 2
        assert pricer.meta_data["ticker"] == "TEST"

    def test_latest_price(self):
        from MDP.EventContracts.EventContractsMDP import EventContractPricer

        data = pd.DataFrame({"price": [0.5, 0.65]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={})
        assert pricer.latest_price() == pytest.approx(0.65)


class TestEventContractsMDP:
    def test_construction_kalshi(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP

        mdp = EventContractsMDP(source="KALSHI")
        assert mdp.source == "KALSHI"

    def test_construction_polymarket(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP

        mdp = EventContractsMDP(source="POLYMARKET")
        assert mdp.source == "POLYMARKET"

    def test_invalid_source(self):
        from MDP.EventContracts.EventContractsMDP import EventContractsMDP

        with pytest.raises(ValueError, match="source must be"):
            EventContractsMDP(source="INVALID")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_contracts_mdp.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# MDP/EventContracts/EventContractsMDP.py
from __future__ import annotations
from typing import Any, Dict, Optional

import pandas as pd

from MDP.MarketDataProvider import MarketDataProvider

_VALID_SOURCES = ("KALSHI", "POLYMARKET")


class EventContractPricer:
    """Pricer wrapping event contract price data."""

    def __init__(self, data: pd.DataFrame, meta_data: Dict[str, Any]):
        self._data = data
        self._meta_data = meta_data

    @property
    def data(self) -> pd.DataFrame:
        return self._data

    @property
    def meta_data(self) -> Dict[str, Any]:
        return self._meta_data

    def latest_price(self) -> Optional[float]:
        if self._data.empty:
            return None
        col = "close" if "close" in self._data.columns else "price"
        return float(self._data[col].iloc[-1])

    def latest_volume(self) -> Optional[float]:
        if self._data.empty or "volume" not in self._data.columns:
            return None
        return float(self._data["volume"].iloc[-1])

    def latest_open_interest(self) -> Optional[float]:
        if self._data.empty or "open_interest" not in self._data.columns:
            return None
        return float(self._data["open_interest"].iloc[-1])


class EventContractsMDP(MarketDataProvider):
    """
    Event contracts MDP for Kalshi and Polymarket.

    Source: "KALSHI" or "POLYMARKET"

    Request dict (KALSHI):
        ticker: str                 — market ticker (e.g., "KXFED-26MAR19")
        series_ticker: str          — series ticker (for live endpoint)
        start: datetime
        end: datetime
        period_interval: int        — 1 (1min), 60 (1hr), 1440 (1day)
        api_key_id: str             — for live endpoint
        private_key_pem: str        — for live endpoint

    Request dict (POLYMARKET):
        market_id: str              — condition token ID
        start: datetime
        end: datetime
        interval: str               — "1h", "6h", "1d", "1w", "1m"
        fidelity: int               — accuracy in minutes
    """

    def __init__(self, source: str, **kwargs: Any):
        if source not in _VALID_SOURCES:
            raise ValueError(f"source must be one of {_VALID_SOURCES}, got '{source}'")
        super().__init__(source=source, **kwargs)

    def get_pricer(self, request: Any) -> EventContractPricer:
        if self.source == "KALSHI":
            return self._fetch_kalshi(request)
        else:
            return self._fetch_polymarket(request)

    def _fetch_kalshi(self, request: Dict[str, Any]) -> EventContractPricer:
        from MDP.EventContracts.kalshi_fetcher import fetch_historical_candlesticks, fetch_live_candlesticks

        ticker = request["ticker"]
        start = request.get("start")
        end = request.get("end")
        period = request.get("period_interval", 1440)

        api_key = request.get("api_key_id")
        private_key = request.get("private_key_pem")

        if api_key and private_key:
            series_ticker = request.get("series_ticker", ticker.rsplit("-", 1)[0])
            data = fetch_live_candlesticks(
                series_ticker=series_ticker,
                ticker=ticker,
                start=start,
                end=end,
                period_interval=period,
                api_key_id=api_key,
                private_key_pem=private_key,
            )
        else:
            data = fetch_historical_candlesticks(
                ticker=ticker,
                start=start,
                end=end,
                period_interval=period,
            )

        return EventContractPricer(
            data=data,
            meta_data={"source": "KALSHI", "ticker": ticker},
        )

    def _fetch_polymarket(self, request: Dict[str, Any]) -> EventContractPricer:
        from MDP.EventContracts.polymarket_fetcher import fetch_price_history

        market_id = request["market_id"]
        start = request.get("start")
        end = request.get("end")
        interval = request.get("interval", "1d")
        fidelity = request.get("fidelity", 1)

        data = fetch_price_history(
            market_id=market_id,
            start=start,
            end=end,
            interval=interval,
            fidelity=fidelity,
        )

        return EventContractPricer(
            data=data,
            meta_data={"source": "POLYMARKET", "market_id": market_id},
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_contracts_mdp.py -v`
Expected: PASS (5 passed)

**Step 5: Commit**

```bash
git add MDP/EventContracts/EventContractsMDP.py tests/test_event_contracts_mdp.py
git commit -m "feat: add EventContractsMDP with Kalshi and Polymarket support"
```

---

## Task 12: EventContractQuery + adapter — query layer for event contracts

**Files:**
- Create: `Query/EventContracts/__init__.py`
- Create: `Query/EventContracts/EventContractStructure.py`
- Create: `Query/EventContracts/EventContractValue.py`
- Create: `Query/EventContracts/EventContractQuery.py`
- Create: `Query/EventContracts/adapter.py`
- Test: `tests/test_event_contract_query.py`

**Step 1: Write the failing test**

```python
# tests/test_event_contract_query.py
import pytest
import datetime
import pandas as pd


class TestEventContractEnums:
    def test_structure_members(self):
        from Query.EventContracts.EventContractStructure import EventContractStructure

        assert hasattr(EventContractStructure, "OUTRIGHT")
        assert hasattr(EventContractStructure, "SPREAD")

    def test_value_members(self):
        from Query.EventContracts.EventContractValue import EventContractValue

        assert hasattr(EventContractValue, "PRICE")
        assert hasattr(EventContractValue, "PROBABILITY")
        assert hasattr(EventContractValue, "VOLUME")
        assert hasattr(EventContractValue, "OPEN_INTEREST")


class TestEventContractQuery:
    def test_basic_construction(self):
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue

        q = EventContractQuery(
            ticker="KXFED-26MAR19",
            value=EventContractValue.PRICE,
        )
        assert q.product == "EVENT"
        assert q.ticker == "KXFED-26MAR19"

    def test_build_mdp_request(self):
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue

        q = EventContractQuery(ticker="KXFED-26MAR19", value=EventContractValue.PRICE)
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        assert req["ticker"] == "KXFED-26MAR19"

    def test_col_name(self):
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue

        q = EventContractQuery(ticker="KXFED-26MAR19", value=EventContractValue.PRICE)
        col = q.col_name()
        assert "KXFED" in col


class TestEventContractAdapter:
    def test_adapter_registered(self):
        from Query.Base.product_adapter import get_adapter
        import Query.EventContracts.adapter  # noqa: F401
        adapter_cls = get_adapter("EVENT")
        assert adapter_cls is not None

    def test_value_map_price(self):
        from Query.Base.product_adapter import get_adapter
        import Query.EventContracts.adapter  # noqa: F401
        from Query.EventContracts.EventContractValue import EventContractValue
        from MDP.EventContracts.EventContractsMDP import EventContractPricer

        data = pd.DataFrame({"price": [0.55, 0.60]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
        pricer = EventContractPricer(data=data, meta_data={"ticker": "TEST"})

        adapter = get_adapter("EVENT")()
        val_map = adapter.build_value_map(pricer_or_curve=pricer, package=[], risk_weights=[])
        price = val_map.apply(EventContractValue.PRICE)
        assert price == pytest.approx(0.60)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_contract_query.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# Query/EventContracts/__init__.py
# (empty)
```

```python
# Query/EventContracts/EventContractStructure.py
from enum import Enum, auto


class EventContractStructure(Enum):
    OUTRIGHT = auto()
    SPREAD = auto()
```

```python
# Query/EventContracts/EventContractValue.py
from enum import Enum, auto


class EventContractValue(Enum):
    PRICE = auto()
    PROBABILITY = auto()
    VOLUME = auto()
    OPEN_INTEREST = auto()
```

```python
# Query/EventContracts/EventContractQuery.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from Query.Base.BaseQuery import BaseQuery
from Query.EventContracts.EventContractStructure import EventContractStructure
from Query.EventContracts.EventContractValue import EventContractValue
from Query.EventContracts import adapter as _ec_adapter  # noqa: F401


@dataclass(frozen=True)
class EventContractQuery(BaseQuery):
    """
    Query for event contracts (Kalshi, Polymarket).

    User-facing args:
      - ticker: Kalshi market ticker (e.g., "KXFED-26MAR19")
      - market_id: Polymarket condition token ID
      - value: PRICE, PROBABILITY, VOLUME, OPEN_INTEREST
      - structure: OUTRIGHT or SPREAD
    """

    structure: EventContractStructure = EventContractStructure.OUTRIGHT
    value: Union[EventContractValue, List[EventContractValue]] = EventContractValue.PRICE

    ticker: Optional[str] = None
    market_id: Optional[str] = None

    structure_kwargs: Dict[str, Any] = field(default_factory=dict)
    risk_weight: Optional[float] = None

    product: str = field(init=False, default="EVENT")
    structure_id: Any = field(init=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, "product", "EVENT")
        object.__setattr__(self, "structure_id", self.structure)

        mr = dict(self.market_request or {})
        if self.ticker and "ticker" not in mr:
            mr["ticker"] = self.ticker
        if self.market_id and "market_id" not in mr:
            mr["market_id"] = self.market_id
        object.__setattr__(self, "market_request", mr)

        if isinstance(self.value, list):
            object.__setattr__(self, "value_id", None)
            object.__setattr__(self, "value_ids", tuple(self.value))
        else:
            object.__setattr__(self, "value_id", self.value)
            object.__setattr__(self, "value_ids", tuple())

    def return_query(self) -> List["EventContractQuery"]:
        if isinstance(self.value, list):
            from dataclasses import replace
            return [replace(self, value=v) for v in self.value]
        return [self]

    def col_name(self, cube_name: Optional[str] = None) -> str:
        label = self.ticker or self.market_id or "EVENT"
        val_name = self.value.name if isinstance(self.value, EventContractValue) else "MULTI"
        return f"{label} {val_name}"

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        col = self.col_name(cube_name=cube_name)
        if self.risk_weight is not None:
            return f"{self.risk_weight} * `{col}`"
        return f"`{col}`"

    def default_mtm_value_id(self) -> Any:
        return EventContractValue.PRICE
```

```python
# Query/EventContracts/adapter.py
from __future__ import annotations
from typing import Any, Callable, Dict, List

from Query.Base.product_adapter import ProductAdapter, register_product
from Query.Base.BaseValue import BaseValueFunctionMap
from Query.EventContracts.EventContractValue import EventContractValue


class EventContractValueFunctionMap(BaseValueFunctionMap[EventContractValue, float]):
    def __init__(self, pricer: Any, **common_kwargs: Any):
        self._pricer = pricer
        super().__init__(EventContractValue, pricer=pricer, **common_kwargs)

    def _create_map(self) -> Dict[EventContractValue, Callable[..., float]]:
        return {
            EventContractValue.PRICE: self._price,
            EventContractValue.PROBABILITY: self._probability,
            EventContractValue.VOLUME: self._volume,
            EventContractValue.OPEN_INTEREST: self._open_interest,
        }

    def _price(self, **kw) -> float:
        return kw["pricer"].latest_price() or 0.0

    def _probability(self, **kw) -> float:
        # For binary contracts, price = probability
        return kw["pricer"].latest_price() or 0.0

    def _volume(self, **kw) -> float:
        return kw["pricer"].latest_volume() or 0.0

    def _open_interest(self, **kw) -> float:
        return kw["pricer"].latest_open_interest() or 0.0


class EventContractProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve: Any) -> Any:
        # Event contracts don't have complex structures — OUTRIGHT returns the pricer itself
        return _EventContractStructureMap(pricer=pricer_or_curve)

    def build_value_map(
        self,
        *,
        pricer_or_curve: Any,
        package: List[Any],
        risk_weights: List[float],
    ) -> EventContractValueFunctionMap:
        return EventContractValueFunctionMap(pricer=pricer_or_curve)

    def edit_query(self, *, q: Any, pricer_or_curve: Any):
        return q


class _EventContractStructureMap:
    """Minimal structure map for event contracts."""

    def __init__(self, pricer: Any):
        self._pricer = pricer

    def apply(self, structure: Any, **kwargs: Any):
        # OUTRIGHT: package is empty (pricer holds all data), weight is 1
        return [], [1.0]


register_product("EVENT", EventContractProductAdapter)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_contract_query.py -v`
Expected: PASS (7 passed)

**Step 5: Commit**

```bash
git add Query/EventContracts/__init__.py Query/EventContracts/EventContractStructure.py Query/EventContracts/EventContractValue.py Query/EventContracts/EventContractQuery.py Query/EventContracts/adapter.py tests/test_event_contract_query.py
git commit -m "feat: add EventContractQuery, adapter, and value map"
```

---

## Task 13: Integration tests — end-to-end spread MDP + backtester TB flow

**Files:**
- Test: `tests/test_spread_mdp_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_spread_mdp_integration.py
"""
Integration test: full spread MDP flow through the backtester query pattern.
Uses MockMDP/MockPricer from conftest to avoid real market data dependencies.
"""
import pytest
import datetime
from tests.conftest import MockMDP, MockPricer
from MDP.Spreads.SpreadPricer import SpreadPricer


class TestSpreadMDPIntegration:
    def test_full_flow_irswap_spread(self):
        """End-to-end: IRSwapSpreadsMDP -> SpreadQuery -> resolve_package -> build_value_map -> apply"""
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        mdp = IRSwapSpreadsMDP(
            _mdp_a=MockMDP(source="A", base_rate=0.04),
            _mdp_b=MockMDP(source="B", base_rate=0.05),
        )

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )

        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        assert isinstance(pricer, SpreadPricer)

        package, weights = q.resolve_package(pricer_or_curve=pricer)
        assert len(package) == 1

        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        spread_bps = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread_bps, float)

        leg_a = val_map.apply(SpreadValue.LEG_A_RATE)
        leg_b = val_map.apply(SpreadValue.LEG_B_RATE)
        assert isinstance(leg_a, float)
        assert isinstance(leg_b, float)

    def test_full_flow_basis(self):
        """End-to-end: IRBasisSwapsMDP -> SpreadQuery -> value"""
        from MDP.IRBasisSwaps.IRBasisSwapsMDP import IRBasisSwapsMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        mdp = IRBasisSwapsMDP(
            _mdp_a=MockMDP(source="SOFR", base_rate=0.04),
            _mdp_b=MockMDP(source="FF", base_rate=0.038),
        )

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.SPREAD_BPS,
            product_key="IRBASIS",
        )
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        spread = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread, float)

    def test_full_flow_cvx_adjustment(self):
        """End-to-end: STIRConvexityAdjustmentMDP -> SpreadQuery -> CVX_ADJ_EMPIRICAL"""
        from MDP.STIRConvexityAdjustment.STIRConvexityAdjustmentMDP import STIRConvexityAdjustmentMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue

        mdp = STIRConvexityAdjustmentMDP(
            _mdp_a=MockMDP(source="STIRT", base_rate=0.04),
            _mdp_b=MockMDP(source="ERIS", base_rate=0.038),
        )

        q = SpreadQuery(
            tenor="5Y",
            value=SpreadValue.CVX_ADJ_EMPIRICAL,
            product_key="STIRCVX",
        )
        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        cvx = val_map.apply(SpreadValue.CVX_ADJ_EMPIRICAL)
        assert isinstance(cvx, float)

    def test_curve_structure_spread(self):
        """Test 2Y/10Y spread-of-spread (CURVE structure)."""
        from MDP.IRSwapSpreads.IRSwapSpreadsMDP import IRSwapSpreadsMDP
        from Query.Spreads.SpreadQuery import SpreadQuery
        from Query.Spreads.SpreadValue import SpreadValue
        from Query.Spreads.SpreadStructure import SpreadStructure

        mdp = IRSwapSpreadsMDP(
            _mdp_a=MockMDP(source="A", base_rate=0.04),
            _mdp_b=MockMDP(source="B", base_rate=0.05),
        )

        q = SpreadQuery(
            tenor="2Y/10Y",
            value=SpreadValue.SPREAD_BPS,
            curve_a="USD-SOFR-1D",
            curve_b="USD-FEDFUNDS",
        )
        assert q.structure == SpreadStructure.CURVE

        now = datetime.datetime(2026, 3, 15, 17, 0)
        req = q.build_mdp_request(now)
        pricer = mdp.get_pricer(req)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        assert len(package) == 2
        assert len(weights) == 2

        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        spread_bps = val_map.apply(SpreadValue.SPREAD_BPS)
        assert isinstance(spread_bps, float)


class TestEventContractIntegration:
    def test_query_to_value_map(self):
        """End-to-end: EventContractQuery -> adapter -> value_map -> PRICE"""
        import pandas as pd
        from MDP.EventContracts.EventContractsMDP import EventContractPricer
        from Query.EventContracts.EventContractQuery import EventContractQuery
        from Query.EventContracts.EventContractValue import EventContractValue

        # Simulate what EventContractsMDP.get_pricer would return
        data = pd.DataFrame({"price": [0.55, 0.60, 0.65]}, index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]))
        pricer = EventContractPricer(data=data, meta_data={"ticker": "TEST"})

        q = EventContractQuery(ticker="TEST", value=EventContractValue.PRICE)
        package, weights = q.resolve_package(pricer_or_curve=pricer)
        val_map = q.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
        price = val_map.apply(EventContractValue.PRICE)
        assert price == pytest.approx(0.65)
```

**Step 2: Run tests**

Run: `pytest tests/test_spread_mdp_integration.py -v`
Expected: PASS (5 passed)

**Step 3: Commit**

```bash
git add tests/test_spread_mdp_integration.py
git commit -m "test: add end-to-end integration tests for spread MDPs and EventContracts"
```

---

## Task 14: Run full test suite and fix any issues

**Step 1: Run all new tests together**

Run: `pytest tests/test_spread_pricer.py tests/test_spread_mdp.py tests/test_spread_query.py tests/test_spread_adapter.py tests/test_ir_swap_spreads_mdp.py tests/test_ir_basis_swaps_mdp.py tests/test_ir_clearing_house_basis_mdp.py tests/test_stir_convexity_adjustment_mdp.py tests/test_kalshi_fetcher.py tests/test_polymarket_fetcher.py tests/test_event_contracts_mdp.py tests/test_event_contract_query.py tests/test_spread_mdp_integration.py -v`

Expected: ALL PASS

**Step 2: Run existing tests to verify no regressions**

Run: `pytest tests/ -v --ignore=tests/test_spread_pricer.py --ignore=tests/test_spread_mdp.py --ignore=tests/test_spread_query.py --ignore=tests/test_spread_adapter.py --ignore=tests/test_ir_swap_spreads_mdp.py --ignore=tests/test_ir_basis_swaps_mdp.py --ignore=tests/test_ir_clearing_house_basis_mdp.py --ignore=tests/test_stir_convexity_adjustment_mdp.py --ignore=tests/test_kalshi_fetcher.py --ignore=tests/test_polymarket_fetcher.py --ignore=tests/test_event_contracts_mdp.py --ignore=tests/test_event_contract_query.py --ignore=tests/test_spread_mdp_integration.py -x`

Expected: no regressions (existing tests should not be affected)

**Step 3: Fix any issues found, commit**

```bash
git add -A
git commit -m "fix: resolve any test failures from new MDP integration"
```
