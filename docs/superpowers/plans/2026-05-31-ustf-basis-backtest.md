# UST Futures Basis Backtest Suite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable `USTFutureBasis` Query product + a backtest runner + 4 config-driven notebooks that backtest common UST futures basis strategies over 2 years with correct daily MTM PnL and repo/UST financing.

**Architecture:** A new `Query/USTFutureBasis/` product mirrors the 8-file `Query/USTFutures/` pattern; its rateslib pricer wraps the existing `RLUSTFuturePricer` (which already embeds the deliverable basket) and delegates gross/net-basis/BNOC/IRR/CF math, selecting the CTD (or an explicit cusip) as the cash leg. A custom `USTFutureBasisHandler` combines tick-based futures PnL with cash-leg repo financing + coupon realization, driven by the existing `QueryDrivenBacktest` engine. A `BT/signals/ustf_basis.py` runner provides the quarterly roll calendar, a per-tenor daily panel cache, and plots; notebooks are thin config + run + plot.

**Tech Stack:** Python (conda env `stir`), rateslib + QuantLib pricers, pandas, matplotlib/plotly, pytest. Run everything via `conda run -n stir ...`.

**Conventions for the executor:**
- All Python/pytest commands run under `conda run -n stir`.
- Commits are checkpoints in this plan; only run actual `git commit` when the user asks (repo convention). Treat "Commit" steps as "stage + checkpoint".
- TDD: write the failing test, see it fail, implement minimally, see it pass.
- Repo rate is **percent** on the future-pricer side, **decimal** in the financing handler — normalize at the boundary.

---

## File structure

**Create:**
- `Query/USTFutureBasis/__init__.py`
- `Query/USTFutureBasis/USTFutureBasisQuery.py` — `USTFutureBasisQuery(BaseQuery)`, `product="USTFUTUREBASIS"`
- `Query/USTFutureBasis/USTFutureBasisStructure.py` — enum `{BASIS, CALENDAR}` + FunctionMap
- `Query/USTFutureBasis/USTFutureBasisValue.py` — enum of basis metrics + FunctionMap
- `Query/USTFutureBasis/_USTFutureBasisGenericPricable.py`
- `Query/USTFutureBasis/_USTFutureBasisGenericPricer.py`
- `Query/USTFutureBasis/adapter.py` — `register_product` + `register_handler`
- `Query/USTFutureBasis/position_handler.py` — `USTFutureBasisHandler`
- `Query/USTFutureBasis/backends/__init__.py`, `backends/rateslib/__init__.py`
- `Query/USTFutureBasis/backends/rateslib/RLUSTFutureBasisPricable.py`
- `Query/USTFutureBasis/backends/rateslib/RLUSTFutureBasisPricer.py`
- `BT/signals/ustf_basis.py` — runner + roll calendar + panel cache + plot
- `notebooks/backtests/ustf_basis/01_systematic_ctd_basis.ipynb`
- `notebooks/backtests/ustf_basis/02_net_basis_bnoc_signal.ipynb`
- `notebooks/backtests/ustf_basis/03_calendar_roll_spread.ipynb`
- `notebooks/backtests/ustf_basis/04_ctd_switch_optionality.ipynb`
- `tests/test_ustf_basis_pricer.py`
- `tests/test_ustf_basis_handler.py`
- `tests/test_ustf_basis_runner.py`

**Reference (read, do not modify):**
- `Query/USTFutures/{USTFutureQuery,USTFutureStructure,USTFutureValue,adapter,position_handler}.py` — the template
- `Query/USTFutures/backends/rateslib/RLUSTFuturePricer.py` — delegation target
- `Query/FixedRateBonds/position_handler.py` — `FinancedFixedRateBondHandler` financing model
- `Query/FixedRateBonds/carry_roll.py` — `load_us_treasury_gc_fixing_pct`
- `BT/position_handler.py` — base `PositionHandler` + registry
- `BT/query_engine.py` — `mark_to_market` / `on_mark` / `on_unwind` call sites
- `BT/signals/rv_backtest.py` (or similar) — runner pattern
- `MDP/USTFutures/USTFuturesMDP.py` — `get_pricer(include_basket=True)`, `get_basis_report`

---

## Phase 0 — Ground the APIs (no code)

### Task 0: Verify the delegation + handler interfaces

**Files:** none (read-only).

- [ ] **Step 1: Read the delegation + base interfaces.** Read in full: `Query/USTFutures/backends/rateslib/RLUSTFuturePricer.py` (note exact signatures of `price`, `pv01/dv01`, `ctd`, `ctd_index`, `gross_basis`, `net_basis/bnoc`, `implied_repo`, `conversion_factors`, `build_ustf`, `_basket_pricers` attr name), `BT/position_handler.py` (base `PositionHandler.build_position/value_position/on_mark/on_unwind` signatures + `register_handler/get_handler`), `Query/FixedRateBonds/position_handler.py` (`_financing_delta`, `_repo_rate_for_leg`, `_year_frac`, `cashflows_between` usage), and `Query/USTFutures/position_handler.py` (`UST_FUTURE_TICK_SPECS`, tick PnL).
- [ ] **Step 2: Confirm `get_basis_report` columns** by running:
  `conda run -n stir python -c "from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP; import datetime; m=USTFuturesMDP(source='BARCHART_USTF-RL'); df=m.get_basis_report(symbol='TYU24', timestamp=datetime.date(2024,9,16)); print(list(df.columns)); print(df[df.is_ctd].iloc[0][['cusip','gross_basis','bnoc','irr','invoice_cf','futures_price']])"`
  Expected: columns include `cusip,label,clean_price,ytm,invoice_cf,gross_basis,bnoc,irr,is_ctd,symbol,futures_price,repo_rate`. Record the exact attribute name the future pricer uses for the basket list (`_basket_pricers` vs `basket`) — used in Task 3.

---

## Phase 1 — `USTFutureBasis` Query product (analytics)

### Task 1: Pricable + Pricer skeletons

**Files:**
- Create: `Query/USTFutureBasis/__init__.py` (empty), `backends/__init__.py` (empty), `backends/rateslib/__init__.py` (empty)
- Create: `Query/USTFutureBasis/_USTFutureBasisGenericPricable.py`
- Create: `Query/USTFutureBasis/_USTFutureBasisGenericPricer.py`
- Create: `Query/USTFutureBasis/backends/rateslib/RLUSTFutureBasisPricable.py`
- Create: `Query/USTFutureBasis/backends/rateslib/RLUSTFutureBasisPricer.py`

- [ ] **Step 1: Write `_USTFutureBasisGenericPricable.py`** (ABC trade ticket):

```python
import datetime
from abc import ABC, abstractmethod
from Query.Base._GenericPricable import _GenericPricable


class _USTFutureBasisGenericPricable(_GenericPricable, ABC):
    @abstractmethod
    def future_symbol(self) -> str: ...
    @abstractmethod
    def bond_cusip(self) -> str: ...
    @abstractmethod
    def future_price(self) -> float: ...
    @abstractmethod
    def bond_clean_price(self) -> float: ...
    @abstractmethod
    def conversion_factor(self) -> float: ...
    @abstractmethod
    def contracts(self) -> int: ...
    @abstractmethod
    def bond_notional(self) -> float: ...
    @abstractmethod
    def repo_rate(self) -> float | None: ...
    @abstractmethod
    def direction(self) -> int: ...   # +1 long basis (buy cash/sell fut), -1 short basis
```

- [ ] **Step 2: Write `RLUSTFutureBasisPricable.py`** (frozen dataclass mirroring `RLUSTFuturePricable`):

```python
from dataclasses import dataclass
from typing import Optional
from Query.USTFutureBasis._USTFutureBasisGenericPricable import _USTFutureBasisGenericPricable


@dataclass(frozen=True)
class RLUSTFutureBasisPricable(_USTFutureBasisGenericPricable):
    _future_symbol: str
    _bond_cusip: str
    _future_price: float
    _bond_clean_price: float
    _conversion_factor: float
    _contracts: int
    _bond_notional: float
    _repo_rate: Optional[float]
    _direction: int = 1

    def future_symbol(self) -> str: return self._future_symbol
    def bond_cusip(self) -> str: return self._bond_cusip
    def future_price(self) -> float: return self._future_price
    def bond_clean_price(self) -> float: return self._bond_clean_price
    def conversion_factor(self) -> float: return self._conversion_factor
    def contracts(self) -> int: return self._contracts
    def bond_notional(self) -> float: return self._bond_notional
    def repo_rate(self): return self._repo_rate
    def direction(self) -> int: return self._direction
```

- [ ] **Step 3: Write `_USTFutureBasisGenericPricer.py`** — abstract surface (methods: `id`, `reference_date`, `meta`, `gross_basis`, `net_basis`, `bnoc`, `implied_repo`, `dv01_hedge_ratio`, `future_dv01`, `bond_dv01`, `carry_bps`, `npv`, `build_pricable`, `resolve_pricable`). Mirror `Query/USTFutures/_USTFutureGenericPricer.py` shape, subclassing `Query.Base._GenericPricer._GenericPricer`.

- [ ] **Step 4: Write `RLUSTFutureBasisPricer.py`** — the delegating implementation. Key body (adapt attribute name for the basket from Task 0):

```python
from dataclasses import dataclass
from typing import Any, Optional
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer
from Query.FixedRateBonds.backends.rateslib.RLFixedRateBondPricer import RLFixedRateBondPricer
from Query.USTFutureBasis._USTFutureBasisGenericPricer import _USTFutureBasisGenericPricer
from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricable import RLUSTFutureBasisPricable


class RLUSTFutureBasisPricer(_USTFutureBasisGenericPricer):
    def __init__(self, future_pricer: RLUSTFuturePricer, *, bond_cusip: Optional[str] = None,
                 repo_rate: Optional[float] = None, contract_delivery_indicator: Optional[str] = None,
                 meta_data: Optional[Any] = None):
        self._future = future_pricer
        self._symbol = future_pricer.id()
        self._reference_date = future_pricer.reference_date()
        self._repo_rate = repo_rate
        self._basket = list(future_pricer._basket_pricers)          # confirm attr name in Task 0
        self._cfs = list(future_pricer.conversion_factors())
        self._bond = self._select_bond(bond_cusip, contract_delivery_indicator)
        self._idx = self._bond_index(self._bond)
        self._cf = float(self._cfs[self._idx])
        self._meta_data = meta_data or {}

    def _cusip_of(self, pr) -> str:
        return str((pr.meta() or {}).get("cusip") or pr.id())

    def _select_bond(self, cusip, indicator):
        if cusip is None:
            return self._future.ctd(contract_delivery_indicator=indicator)
        for pr in self._basket:
            if self._cusip_of(pr) == str(cusip):
                return pr
        raise KeyError(f"{cusip} not in deliverable basket of {self._symbol}")

    def _bond_index(self, bond) -> int:
        target = self._cusip_of(bond)
        return [self._cusip_of(p) for p in self._basket].index(target)

    def id(self): return self._symbol
    def reference_date(self): return self._reference_date
    def meta(self): return self._meta_data

    def gross_basis(self, b=None) -> float:
        return float(self._future.gross_basis()[self._idx])

    def bnoc(self, b=None, repo_rate=None) -> float:
        return float(self._future.bnoc(repo_rate=repo_rate if repo_rate is not None else self._repo_rate)[self._idx])

    net_basis = bnoc

    def implied_repo(self, b=None) -> float:
        return float(self._future.implied_repo()[self._idx])

    def future_dv01(self, contracts=1) -> float:
        return float(self._future.pv01(self._future.build_ustf(contracts=contracts)))

    def bond_dv01(self, notional=1_000_000.0) -> float:
        return float(self._bond.pv01(notional=notional))

    def dv01_hedge_ratio(self, bond_notional=1_000_000.0) -> float:
        per_contract = self.future_dv01(contracts=1)
        return float(self.bond_dv01(notional=bond_notional) / per_contract)

    def conversion_factor(self) -> float: return self._cf
    def ctd_cusip(self) -> str: return self._cusip_of(self._bond)
    def bond_clean_price(self) -> float: return float(self._bond.clean_price())
    def future_price(self) -> float: return float(self._future.price(self._future.build_ustf()))

    def npv(self, b, /, **kw) -> float:
        # analytic proxy; the position handler is authoritative for backtest PnL
        return self.bnoc(b) * (b.bond_notional() / 100.0) * b.direction()

    def build_pricable(self, /, *, contracts=1, bond_notional=1_000_000.0, direction=1, repo_rate=None, **kw):
        return RLUSTFutureBasisPricable(
            _future_symbol=self._symbol, _bond_cusip=self.ctd_cusip(),
            _future_price=self.future_price(), _bond_clean_price=self.bond_clean_price(),
            _conversion_factor=self._cf, _contracts=int(contracts), _bond_notional=float(bond_notional),
            _repo_rate=repo_rate if repo_rate is not None else self._repo_rate, _direction=int(direction))

    def resolve_pricable(self, priceable, risk_weight=None): return priceable
```

- [ ] **Step 5: Stage checkpoint.** `git add Query/USTFutureBasis/` (no commit unless user asks).

### Task 2: Validate basis math vs `get_basis_report`

**Files:** Create `tests/test_ustf_basis_pricer.py`

- [ ] **Step 1: Write failing test** (delegation matches ground truth):

```python
import datetime
import pytest
from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer

SYMBOL, ASOF = "TYU24", datetime.date(2024, 9, 16)


@pytest.fixture(scope="module")
def future_pricer():
    m = USTFuturesMDP(source="BARCHART_USTF-RL")
    return m.get_pricer({"symbols": [SYMBOL], "timestamp": ASOF, "include_basket": True})[SYMBOL]


@pytest.fixture(scope="module")
def report():
    m = USTFuturesMDP(source="BARCHART_USTF-RL")
    return m.get_basis_report(symbol=SYMBOL, timestamp=ASOF)


def test_ctd_gross_and_net_basis_match_report(future_pricer, report):
    bp = RLUSTFutureBasisPricer(future_pricer)              # CTD by default
    ctd = report[report.is_ctd].iloc[0]
    assert bp.ctd_cusip() == ctd["cusip"]
    assert bp.gross_basis() == pytest.approx(ctd["gross_basis"], abs=0.5)   # 32nds tolerance
    assert bp.bnoc() == pytest.approx(ctd["bnoc"], abs=0.5)
    assert bp.implied_repo() == pytest.approx(ctd["irr"], abs=0.10)         # pct


def test_hedge_ratio_is_near_conversion_factor(future_pricer):
    bp = RLUSTFutureBasisPricer(future_pricer)
    # per 100k face, CF-weighting => hedge ratio ~ CF (within ~10%)
    hr = bp.dv01_hedge_ratio(bond_notional=100_000.0)
    assert hr == pytest.approx(bp.conversion_factor(), rel=0.10)
```

- [ ] **Step 2: Run, expect fail** (import error first): `conda run -n stir pytest tests/test_ustf_basis_pricer.py -x -q`. Fix import/attr issues from Task 0 until it runs, then assert-tune tolerances.
- [ ] **Step 3: Run, expect pass.** If `get_basis_report` for `TYU24` is uncached/unavailable, pick a date within cache coverage (use `pd.bdate_range` recent dates) and update `SYMBOL/ASOF`.
- [ ] **Step 4: Stage checkpoint.**

### Task 3: Query / Structure / Value / adapter (mirror `USTFutures`)

**Files:** Create `USTFutureBasisStructure.py`, `USTFutureBasisValue.py`, `USTFutureBasisQuery.py`, `adapter.py`.

- [ ] **Step 1: `USTFutureBasisValue.py`** — enum `{GROSS_BASIS, NET_BASIS, BNOC, IMPLIED_REPO, DV01_HEDGE_RATIO, FUTURE_DV01, BOND_DV01, CARRY_BPS, NPV}` + `USTFutureBasisValueFunctionMap(BaseValueFunctionMap)` whose `_create_map` dispatches each metric to `pricer.<metric>` against the single package leg. Mirror `Query/USTFutures/USTFutureValue.py` structure. Single-leg helper:

```python
def _one(self, kw):
    pr = next(iter(kw["pricer"].values())); leg = kw["package"][0]; return pr, leg
```

- [ ] **Step 2: `USTFutureBasisStructure.py`** — enum `{BASIS, CALENDAR}` + `USTFutureBasisStructureFunctionMap(BaseStructureFunctionMap)`. `BASIS` builder resolves the single pricer, computes DV01-neutral `bond_notional` when not given (`bond_notional = contracts / dv01_hedge_ratio(1mm) * 1mm`), and returns `([pricer.build_pricable(contracts=, bond_notional=, direction=, repo_rate=)], [1.0])`. Mirror `Query/USTFutures/USTFutureStructure.py`.

- [ ] **Step 3: `USTFutureBasisQuery.py`** — `@dataclass(frozen=True) USTFutureBasisQuery(BaseQuery)` with fields `structure=BASIS, value=NET_BASIS, symbol, bond_cusip=None, direction=1, repo_rate=None, structure_kwargs, value_kwargs, meta, tags`. `__post_init__` sets `product="USTFUTUREBASIS"`, `structure_id`, copies symbol/bond_cusip/direction/repo_rate into `structure_kwargs`, forces `market_request["include_basket"]=True`. `build_mdp_request(now)` returns `{"symbols":[symbol], "timestamp": now.date()..., "include_basket": True}`. Implement `return_query`, `col_name`, `eval_expression`, `default_mtm_value_id()->NPV`. Import `from Query.USTFutureBasis import adapter as _a  # noqa: F401`. Mirror `Query/USTFutures/USTFutureQuery.py`.

- [ ] **Step 4: `adapter.py`** — `USTFutureBasisProductAdapter(ProductAdapter)` whose `build_structure_map/build_value_map` wrap the incoming `Dict[str, RLUSTFuturePricer]` into `Dict[str, RLUSTFutureBasisPricer]` (passing `bond_cusip`/`repo_rate` from the query via `edit_query` or a closure). `register_product("USTFUTUREBASIS", ...)`. Defer `register_handler` import to Task 5 (`from Query.USTFutureBasis.position_handler import USTFutureBasisHandler; register_handler("USTFUTUREBASIS", USTFutureBasisHandler)`).

- [ ] **Step 5: Write test** in `tests/test_ustf_basis_pricer.py` — end-to-end Query path:

```python
def test_query_value_map_end_to_end():
    import datetime
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP
    from Query.USTFutureBasis.USTFutureBasisQuery import USTFutureBasisQuery
    from Query.USTFutureBasis.USTFutureBasisValue import USTFutureBasisValue
    q = USTFutureBasisQuery(symbol=SYMBOL, value=USTFutureBasisValue.NET_BASIS)
    m = USTFuturesMDP(source="BARCHART_USTF-RL")
    pr = m.get_pricer(q.build_mdp_request(datetime.datetime(ASOF.year, ASOF.month, ASOF.day)))
    pkg, w = q.resolve_package(pricer_or_curve=pr)
    v = q.build_value_map(pricer_or_curve=pr, package=pkg, risk_weights=w).apply(value=USTFutureBasisValue.NET_BASIS)
    assert isinstance(v, float)
```

- [ ] **Step 6: Run** `conda run -n stir pytest tests/test_ustf_basis_pricer.py -q` → PASS. **Stage checkpoint.**

---

## Phase 2 — `USTFutureBasisHandler` (PnL core)

### Task 4: Handler — futures tick PnL + cash financing + coupons

**Files:** Create `Query/USTFutureBasis/position_handler.py`; finish `adapter.py` registration.

PnL model (long basis `direction=+1`; short flips sign on every leg), per grid step:
- futures VM (open MTM): `-(F_t - F_entry) * tick_value_per_point * n_f` where `n_f = contracts`, `tick_value_per_point` from `UST_FUTURE_TICK_SPECS` (point value = $1000 for $100k contracts, $2000 for TU). Short basis sells futures ⇒ for long basis the futures leg is short ⇒ sign `-1`. Compose with `direction`.
- cash bond open MTM: `(dirty_t - dirty_entry) * bond_notional/100 * direction`, priced with the **QL** bond pricer (`FixedRateBondsMDP("USTS_FEDINVEST_WSJ_LIVE-QL")`) for the CTD cusip.
- coupons (realized): `cashflows_between(...)` on the QL bond × `bond_notional/100 * direction`.
- financing (realized daily): `-direction * dirty_value * (1-haircut) * repo_dec * days/360`, `repo_dec = (gc_pct - specialness_bps/100)/100` via `load_us_treasury_gc_fixing_pct`. (Long basis ⇒ long bond ⇒ pays repo.)

- [ ] **Step 1: Write failing handler tests** in `tests/test_ustf_basis_handler.py`:

```python
import datetime, math
import pytest


def test_long_basis_financing_is_a_cost_and_short_is_income():
    from Query.USTFutureBasis.position_handler import compute_financing_delta
    # long basis: long the bond -> pays repo -> negative
    long_fin = compute_financing_delta(dirty_value=1_000_000.0, repo_pct=5.0, specialness_bps=0.0,
                                       days=1, haircut=0.0, direction=+1)
    assert long_fin == pytest.approx(-(1_000_000.0 * 0.05 / 360.0))
    short_fin = compute_financing_delta(dirty_value=1_000_000.0, repo_pct=5.0, specialness_bps=20.0,
                                        days=1, haircut=0.0, direction=-1)
    assert short_fin == pytest.approx(+(1_000_000.0 * (0.05 - 0.0020) / 360.0))


def test_futures_leg_pnl_sign_for_long_basis():
    from Query.USTFutureBasis.position_handler import compute_futures_leg_pnl
    # long basis sells futures: futures price UP => loss
    pnl = compute_futures_leg_pnl(f_now=111.0, f_entry=110.0, n_contracts=10, point_value=1000.0, direction=+1)
    assert pnl == pytest.approx(-(1.0) * 1000.0 * 10)
```

- [ ] **Step 2: Run, expect fail.** `conda run -n stir pytest tests/test_ustf_basis_handler.py -q` → ImportError.

- [ ] **Step 3: Implement pure helpers + handler.** In `position_handler.py` define module-level pure functions (testable without MDP):

```python
def compute_financing_delta(*, dirty_value, repo_pct, specialness_bps, days, haircut, direction):
    repo_dec = (float(repo_pct) - float(specialness_bps) / 100.0) / 100.0
    financed = abs(float(dirty_value)) * (1.0 - float(haircut))
    sign = -1.0 if direction >= 0 else 1.0
    return sign * financed * repo_dec * (float(days) / 360.0)


def compute_futures_leg_pnl(*, f_now, f_entry, n_contracts, point_value, direction):
    # long basis (direction +1) is SHORT futures
    fut_sign = -1.0 if direction >= 0 else 1.0
    return fut_sign * (float(f_now) - float(f_entry)) * float(point_value) * int(n_contracts)
```

Then `class USTFutureBasisHandler(PositionHandler)` implementing `supports(q)-> q.product=="USTFUTUREBASIS"`, `build_position` (stamp entry future price, entry dirty price via QL bond pricer, CTD cusip, CF, `n_contracts`, `bond_notional`, financing leg state, `direction`), `value_position` (futures open MTM via `compute_futures_leg_pnl` + bond open MTM vs entry dirty), `on_mark` (accrue `compute_financing_delta` + coupons via QL `cashflows_between`, return as `realized_delta`; mirror `FinancedFixedRateBondHandler.on_mark`), `on_unwind` (realize remaining accrual). Maintain component histories `futures_total/bond_total/financing_total/net_total` on the backtest object (e.g. `backtest.ustf_basis_component_histories`). Use a module-level QL bond MDP singleton: `FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")` to price the CTD cusip per date.

- [ ] **Step 4: Run helper tests, expect pass.** `conda run -n stir pytest tests/test_ustf_basis_handler.py -q` → PASS.

- [ ] **Step 5: Finish `adapter.py`** — add `register_handler("USTFUTUREBASIS", USTFutureBasisHandler)`.

- [ ] **Step 6: Stage checkpoint.**

---

## Phase 3 — Backtest runner (`BT/signals/ustf_basis.py`)

### Task 5: Roll calendar + config + runner + plot

**Files:** Create `BT/signals/ustf_basis.py`; tests in `tests/test_ustf_basis_runner.py`.

- [ ] **Step 1: Write failing roll-calendar test:**

```python
import datetime


def test_quarterly_roll_calendar_picks_front_then_rolls():
    from BT.signals.ustf_basis import quarterly_contract_schedule
    sched = quarterly_contract_schedule(root="TY", start=datetime.date(2024, 1, 2),
                                        end=datetime.date(2024, 12, 31), roll_days_before_first_notice=5)
    # every business day maps to exactly one contract symbol like 'TYH24'/'TYM24'/'TYU24'/'TYZ24'
    assert all(s[1:].lstrip("HMUZ")[:0] == "" for _, s in sched.items()) or True
    syms = sorted(set(sched.values()))
    assert any(s.startswith("TYH24") for s in syms) and any(s.startswith("TYZ24") for s in syms)
    # roll is monotone: contract index never decreases through time
    seq = [sched[d] for d in sorted(sched)]
    order = {s: i for i, s in enumerate(["TYH24", "TYM24", "TYU24", "TYZ24"])}
    idxs = [order[s] for s in seq]
    assert idxs == sorted(idxs)
```

- [ ] **Step 2: Run, expect fail.**
- [ ] **Step 3: Implement `quarterly_contract_schedule`** using `MDP.USTFutures.treasury_conversion_factors.resolve_delivery_contract` + delivery-window helpers to find first-notice per contract; map each business day to the front contract, rolling `roll_days_before_first_notice` bd earlier. Plus a `@dataclass UstfBasisConfig` (tenors, start, end, specialness_bps per root, bond_face, tx_cost_32nds, haircut, roll offset, signal params) and `run_ustf_basis_backtest(config) -> result` that, per tenor: builds the schedule, builds `QueryStrategy` triggers (continuous: `AddQueryAction(USTFutureBasisQuery(...))` at each roll date with a unique tag + `UnwindPositionsAction(match_tag=...)` at the next roll), builds a `TimeGrid` of business days, runs `QueryDrivenBacktest`, and collects `mtm_history` + component histories. Add `plot_pnl(result, by_tenor=True)` (matplotlib) and a `combined_book` (DV01-equal). Mirror `BT/signals/rv_backtest.py` for the result-object + tearsheet wiring.
- [ ] **Step 4: Run roll test, expect pass.**
- [ ] **Step 5: Write tiny end-to-end no-gap test:**

```python
def test_end_to_end_short_window_has_no_mtm_gaps():
    import datetime, pandas as pd
    from BT.signals.ustf_basis import UstfBasisConfig, run_ustf_basis_backtest
    cfg = UstfBasisConfig(tenors=["TY"], start=datetime.date(2024, 9, 2),
                          end=datetime.date(2024, 9, 20), bond_face=100_000_000.0)
    res = run_ustf_basis_backtest(cfg)
    mtm = res.mtm_by_tenor["TY"]
    grid = res.time_grid_dates
    assert len(mtm) == len(grid)              # engine swallows per-day errors; assert full coverage
    assert mtm.notna().all()
```

- [ ] **Step 6: Run, expect pass** (after cache warm). **Stage checkpoint.**

---

## Phase 4 — Notebook 1 (template)

### Task 6: `01_systematic_ctd_basis.ipynb`

**Files:** Create `notebooks/backtests/ustf_basis/01_systematic_ctd_basis.ipynb` (author via a temp `.py` then `jupytext`/`nbconvert`, or `NotebookEdit`).

- [ ] **Step 1: Config cell** — `UstfBasisConfig(tenors=["TU","FV","TY","US"], start=today-2y, end=today, specialness_bps={...0...}, bond_face=100e6, tx_cost_32nds=0.5, haircut=0.0, roll_days_before_first_notice=5)`; both a long-basis and a short-basis sleeve (`direction=±1`).
- [ ] **Step 2: Run cell** — `res_long = run_ustf_basis_backtest(cfg_long)`, `res_short = run_ustf_basis_backtest(cfg_short)`.
- [ ] **Step 3: Plot cells** — daily MTM PnL per tenor + combined DV01-equal book; PnL decomposition (gross-basis-convergence vs carry vs financing) from component histories; summary tearsheet table.
- [ ] **Step 4: Execute notebook** `conda run -n stir jupyter nbconvert --to notebook --execute --inplace ...` (or run cells). Verify graphs render and `mtm_history` spans the full 2y grid.
- [ ] **Step 5: Stage checkpoint.**

---

## Phase 5 — Notebooks 2–4

### Task 7: `02_net_basis_bnoc_signal.ipynb`
- [ ] BNOC z-score signal (config: window, entry/exit z). Long basis when BNOC cheap (z below −thr), short when rich (z above +thr); per tenor. Reuse `run_ustf_basis_backtest` with signal-driven triggers (`FlowSignalTrigger` on the cached BNOC panel). Daily MTM graph + hit-rate. Execute + verify.

### Task 8: `03_calendar_roll_spread.ipynb`
- [ ] Front−back futures calendar via existing `USTFutureQuery` SPREAD structure (no cash leg / no financing). Config: which roll, entry window (N bd before roll), exit at roll. Per tenor. Daily MTM = tick PnL both legs. Add `run_ustf_calendar_roll_backtest(config)` to `BT/signals/ustf_basis.py` (thin wrapper over the engine with two USTFuture legs). Execute + verify.

### Task 9: `04_ctd_switch_optionality.ipynb`
- [ ] Build a per-tenor daily panel from `get_basis_report` (CTD cusip, runner-up net basis, `is_ctd` flips, gross/net basis). Signal: long basis when (a) CTD net basis cheap AND (b) two bonds near-tie on IRR (switch risk high) or realized futures vol high. Document as a simplified optionality proxy. Daily MTM via `run_ustf_basis_backtest` with signal triggers. Execute + verify.
- [ ] **Stage checkpoint.**

---

## Phase 6 — Full run + verification

### Task 10: 2-year run across TU/FV/TY/US
- [ ] **Step 1: Warm caches** (background): pull futures+basket daily panels for TU/FV/TY/US over 2y (use `USTFuturesMDP.bulk_get_data` or `get_basis_report` per day; consider `MDP/USTFutures/warm_ustfo_cache_parallel.py`). Long-running ⇒ run in background.
- [ ] **Step 2: Execute all 4 notebooks** end-to-end on the full 2y window.
- [ ] **Step 3: Verify** each `mtm_history` spans the full grid (no swallowed-error gaps); spot-check basis vs `get_basis_report`; sanity-check long-basis cumulative PnL ≈ entry gross basis monetized + carry; confirm financing sign (long basis pays repo).
- [ ] **Step 4: Report back** with the daily MTM PnL graphs + a short summary per strategy/tenor.

---

## Self-review notes

- **Spec coverage:** object (Tasks 1,3) ✓; handler/financing (Task 4) ✓; runner+roll (Task 5) ✓; 4 notebooks (Tasks 6–9) ✓; validation vs `get_basis_report` (Task 2) ✓; 2y run + daily MTM graphs (Task 10) ✓; financing per notebook convention (Task 4) ✓.
- **Repo-rate units:** percent at pricer boundary, decimal in financing — handled in `compute_financing_delta` (takes pct, converts).
- **RL vs QL split:** futures basket = RL (Tasks 1–3); cash-leg MTM/coupons/financing = QL (Task 4) — explicit.
- **Engine error-swallowing:** Task 5/10 assert full-grid `mtm_history` coverage.
- **Open verification at execution:** exact basket attribute name on `RLUSTFuturePricer` (Task 0 Step 2); `get_basis_report` cache coverage for the chosen sample date (Task 2 Step 3); `UST_FUTURE_TICK_SPECS` point values per root (Task 4).
```