# SFR Convex Screener Backtest Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Backtest the SFR Convex Linear Structure Screener (`RVUtils/SFRConvexScreener`) on historical data using the event-driven `QueryDrivenBacktest` framework. Generate per-trade P&L, Sharpe, max drawdown, and a tearsheet from a `pd.bdate_range` of as_of dates.

**Architecture:** Mirror `BT/signals/sfr_fly_triggers.py` + `notebooks/backtests/sfr_fly_rv_backtest.ipynb`. Pre-compute a cached signal table (one entry per as_of date with the screener's `Snapshot.to_dataframe()` output) so the heavyweight BL/joint calibration runs once per date and persists to disk. Two `FlowSignalTriggerRequirements`-backed triggers wire the table to entries (`AddQueryAction`) and exits (`UnwindPositionsAction`). Tag every position with the `structure_id` so exits can target by tag.

**Tech Stack:**
- Existing screener: `RVUtils/SFRConvexScreener.build_snapshot`
- BT framework: `BT.data_handler.TimeGrid`, `BT.query_engine.QueryDrivenBacktest`, `BT.query_strategy.QueryStrategy`, `BT.triggers.{Trigger, FlowSignalTriggerRequirements}`, `BT.event.TriggerInfo`, `BT.query_actions.{AddQueryAction, UnwindPositionsAction}`
- Query layer: `Query.IRSwaps.IRSwapQuery.IRSwapQuery`, `Query.IRSwaps.IRSwapStructure.IRSwapStructure` (`OUTRIGHT`, `SPREAD`, `FLY`)
- MDP: `MDP.IRSwaps.IRSwapsMDP` (curve), `MDP.STIRFutures.STIRFutureOptionMDP` (smiles)
- Cache: pickle/JSON on disk under `data/screener_results/sfr_convex_screener_backtest_cache/`
- Tests: pytest, conda env `stir`

**Key reuse (no re-implementation):**
- `build_snapshot(config, as_of=date)` — runs the full pipeline; returns `SFRConvexScreenerSnapshot`
- `Snapshot.to_dataframe()` — flat ranked table with `direction`, `asymmetry_ratio`, `composite_score`, etc.
- `StructureResult.direction()` — already produces "PAY X / RECEIVE Y" strings
- `_format_direction` logic is leg-aware → use leg sign + structure_type to build IRSwapQuery
- `BT.signals.sfr_fly_triggers._make_fly_query` shows the exact `IRSwapQuery(structure=FLY, structure_kwargs={...})` shape — copy

**Conventions (must follow):**
- `@dataclass` (mutable) configs; `@dataclass(frozen=True)` results
- `logger = logging.getLogger(__name__)`; per-trade `logger.warning(...)` on failures
- `datetime.date` for cache keys; `pytz.timezone('America/New_York').localize(...)` for tz-aware backtest grids
- Type hints via `typing`
- Tests in flat `tests/` directory, no MDP mocking — synthetic `Snapshot` fixtures
- All Python via `conda run -n stir`
- Frequent commits, one per task

**Out of scope (Phase 2+):**
- Intraday entries (daily EOD only)
- Cross-strategy portfolio overlay
- Live paper trading
- Walk-forward parameter optimization
- IV/RV / historical asymmetry filters as separate triggers (pull through screener directly)

---

## Phase 0: Snapshot caching layer

The screener takes 5–20 minutes per as_of date (BL extraction × 12 contracts × 60d bulk fetch × 12 SABR smiles). For a 1-year backtest at weekly cadence (~52 dates) this is several hours. We must cache.

### Task 0.1: Disk-backed snapshot cache

**Files:**
- Create: `RVUtils/SFRConvexScreener/_backtest_cache.py`
- Test: `tests/test_sfr_convex_screener_backtest_cache.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_backtest_cache.py
import datetime
from pathlib import Path

from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._backtest_cache import (
    SnapshotCache,
    snapshot_cache_key,
)
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics


def _trivial_snapshot(d: datetime.date) -> SFRConvexScreenerSnapshot:
    sd = StructureDef(
        structure_id="A_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("A", 1.0, 96.5, 25.0),),
    )
    metrics = PayoffMetrics(
        mean_bp=1.0, std_bp=5.0, skew=0.5, excess_kurtosis=1.0,
        p_profit=0.55, ev_given_profit_bp=4.0, ev_given_loss_bp=-3.0,
        asymmetry_ratio=1.5,
        percentiles_bp={"p5": -8, "p25": -2, "p50": 1, "p75": 5, "p95": 11},
        tail_ratio=1.4,
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=0.0, rolldown_bp=0.0,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.7, rank=1,
    )
    return SFRConvexScreenerSnapshot(
        as_of=d, results=(r,), config_summary={"universe_size": 4},
    )


def test_snapshot_cache_key_is_stable():
    k1 = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 12})
    k2 = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 12})
    assert k1 == k2


def test_snapshot_cache_key_depends_on_config():
    k_small = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 4})
    k_big = snapshot_cache_key(datetime.date(2026, 4, 28), {"universe_size": 12})
    assert k_small != k_big


def test_cache_roundtrip(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    snap = _trivial_snapshot(datetime.date(2026, 4, 28))
    cfg = {"universe_size": 4}
    assert cache.get(datetime.date(2026, 4, 28), cfg) is None
    cache.put(snap, cfg)
    loaded = cache.get(datetime.date(2026, 4, 28), cfg)
    assert loaded is not None
    assert loaded.as_of == snap.as_of
    assert loaded.results[0].structure_def.structure_id == "A_OUTRIGHT"


def test_cache_miss_on_different_config(tmp_path: Path):
    cache = SnapshotCache(root=tmp_path)
    snap = _trivial_snapshot(datetime.date(2026, 4, 28))
    cache.put(snap, {"universe_size": 4})
    assert cache.get(datetime.date(2026, 4, 28), {"universe_size": 12}) is None
```

**Step 2: Run test to verify it fails**

```
conda run -n stir pytest tests/test_sfr_convex_screener_backtest_cache.py -v
```

Expected: FAIL — module doesn't exist.

**Step 3: Implement minimal cache**

```python
# RVUtils/SFRConvexScreener/_backtest_cache.py
"""On-disk snapshot cache for the SFR Convex Screener backtest.

Stores one pickled `SFRConvexScreenerSnapshot` per (as_of, config-hash) pair so
the heavyweight `build_snapshot` runs once per backtest date and reloads
instantly on subsequent runs.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

from RVUtils.SFRConvexScreener._types import SFRConvexScreenerSnapshot

logger = logging.getLogger(__name__)


def snapshot_cache_key(as_of: datetime.date, config_summary: Dict[str, Any]) -> str:
    """Stable hash of (as_of, config) — JSON-encoded config sorted by key."""
    payload = json.dumps(config_summary, sort_keys=True, default=str)
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{as_of.isoformat()}_{h}"


@dataclass
class SnapshotCache:
    root: Union[str, Path]

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, as_of: datetime.date, config_summary: Dict[str, Any]) -> Path:
        key = snapshot_cache_key(as_of, config_summary)
        return Path(self.root) / f"{key}.pkl"

    def get(
        self, as_of: datetime.date, config_summary: Dict[str, Any]
    ) -> Optional[SFRConvexScreenerSnapshot]:
        p = self._path(as_of, config_summary)
        if not p.exists():
            return None
        try:
            with p.open("rb") as fh:
                return pickle.load(fh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache read failed for %s: %s", p, exc)
            return None

    def put(
        self,
        snapshot: SFRConvexScreenerSnapshot,
        config_summary: Dict[str, Any],
    ) -> Path:
        p = self._path(snapshot.as_of, config_summary)
        with p.open("wb") as fh:
            pickle.dump(snapshot, fh)
        return p
```

**Step 4: Run test to verify it passes**

```
conda run -n stir pytest tests/test_sfr_convex_screener_backtest_cache.py -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_backtest_cache.py tests/test_sfr_convex_screener_backtest_cache.py
git commit -m "feat(sfr-screener): on-disk snapshot cache for backtest"
```

---

### Task 0.2: Bulk snapshot loader with cache integration

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_backtest_cache.py`
- Test: extend `tests/test_sfr_convex_screener_backtest_cache.py`

**Step 1: Write the failing test**

```python
def test_load_or_build_uses_cache(tmp_path: Path, monkeypatch):
    """If cache is hit, build_fn is NOT called."""
    from RVUtils.SFRConvexScreener._backtest_cache import (
        SnapshotCache,
        load_or_build_many,
    )

    snap = _trivial_snapshot(datetime.date(2026, 4, 28))
    cache = SnapshotCache(root=tmp_path)
    cache.put(snap, {"universe_size": 4})

    call_count = {"n": 0}

    def fake_build(d):
        call_count["n"] += 1
        return _trivial_snapshot(d)

    out = load_or_build_many(
        dates=[datetime.date(2026, 4, 28)],
        cache=cache,
        build_fn=fake_build,
        config_summary={"universe_size": 4},
    )
    assert datetime.date(2026, 4, 28) in out
    assert call_count["n"] == 0  # cache hit — no build


def test_load_or_build_falls_through_to_build(tmp_path: Path):
    from RVUtils.SFRConvexScreener._backtest_cache import (
        SnapshotCache,
        load_or_build_many,
    )

    cache = SnapshotCache(root=tmp_path)
    call_count = {"n": 0}

    def fake_build(d):
        call_count["n"] += 1
        return _trivial_snapshot(d)

    out = load_or_build_many(
        dates=[datetime.date(2026, 4, 28), datetime.date(2026, 4, 29)],
        cache=cache,
        build_fn=fake_build,
        config_summary={"universe_size": 4},
    )
    assert call_count["n"] == 2  # both built and cached
    # second pass — both cached
    out2 = load_or_build_many(
        dates=[datetime.date(2026, 4, 28), datetime.date(2026, 4, 29)],
        cache=cache,
        build_fn=fake_build,
        config_summary={"universe_size": 4},
    )
    assert call_count["n"] == 2  # no new builds
```

**Step 2: Run test (FAIL — function not implemented)**

**Step 3: Implement**

```python
# Append to RVUtils/SFRConvexScreener/_backtest_cache.py
from typing import Callable, Dict, Iterable, OrderedDict as _OD
from collections import OrderedDict


def load_or_build_many(
    dates: Iterable[datetime.date],
    *,
    cache: SnapshotCache,
    build_fn: Callable[[datetime.date], SFRConvexScreenerSnapshot],
    config_summary: Dict[str, Any],
    show_progress: bool = False,
) -> _OD[datetime.date, SFRConvexScreenerSnapshot]:
    """For each as_of date, return the cached snapshot if present, else
    invoke ``build_fn(date)`` and persist the result before returning it."""
    out: "OrderedDict[datetime.date, SFRConvexScreenerSnapshot]" = OrderedDict()
    iterator = list(dates)
    if show_progress:
        try:
            from tqdm.auto import tqdm

            iterator = tqdm(iterator, desc="snapshots")
        except ImportError:
            pass
    for d in iterator:
        snap = cache.get(d, config_summary)
        if snap is None:
            try:
                snap = build_fn(d)
            except Exception as exc:  # noqa: BLE001
                logger.warning("build failed for %s: %s", d, exc)
                continue
            try:
                cache.put(snap, config_summary)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache write failed for %s: %s", d, exc)
        out[d] = snap
    return out
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_backtest_cache.py tests/test_sfr_convex_screener_backtest_cache.py
git commit -m "feat(sfr-screener): bulk snapshot loader with cache fall-through"
```

---

## Phase 1: Signal table builder

The screener emits one `Snapshot` per as_of. We flatten it into a date-keyed table of `BacktestSignal` records that the triggers can look up cheaply.

### Task 1.1: BacktestSignal dataclass

**Files:**
- Create: `RVUtils/SFRConvexScreener/_backtest_signals.py`
- Test: `tests/test_sfr_convex_screener_backtest_signals.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_backtest_signals.py
import datetime

from RVUtils.SFRConvexScreener import Leg, StructureDef, StructureType
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal


def test_backtest_signal_holds_screener_fields():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    sig = BacktestSignal(
        as_of=datetime.date(2026, 4, 28),
        structure_def=sd,
        direction="PAY SFRZ26",
        flip=False,
        asymmetry_ratio=2.92,
        composite_score=0.64,
        mean_bp=45.6,
        std_bp=155.3,
        rolldown_bp=0.51,
        carry_3m_bp=365.0,
        is_stale=False,
    )
    assert sig.structure_def.structure_id == "SFRZ26_OUTRIGHT"
    assert sig.flip is False
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_backtest_signals.py
"""Backtest-friendly per-(date, structure) signal records derived from
SFRConvexScreenerSnapshots."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from RVUtils.SFRConvexScreener._types import StructureDef


@dataclass(frozen=True)
class BacktestSignal:
    as_of: datetime.date
    structure_def: StructureDef
    direction: str  # human-readable PAY/RECEIVE string
    flip: bool      # True iff asymmetry_ratio < 1 (long-price / receiver convention)
    asymmetry_ratio: float
    composite_score: float
    mean_bp: float
    std_bp: float
    rolldown_bp: float
    carry_3m_bp: float
    is_stale: bool
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_backtest_signals.py tests/test_sfr_convex_screener_backtest_signals.py
git commit -m "feat(sfr-screener): BacktestSignal dataclass"
```

---

### Task 1.2: `build_signal_table_from_snapshots`

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_backtest_signals.py`
- Test: extend `tests/test_sfr_convex_screener_backtest_signals.py`

**Step 1: Write the failing test**

```python
def test_build_signal_table_from_snapshots():
    from RVUtils.SFRConvexScreener._backtest_signals import (
        build_signal_table_from_snapshots,
    )
    from RVUtils.SFRConvexScreener import (
        SFRConvexScreenerSnapshot, StructureResult,
    )
    from RVUtils.SFRConvexScreener._metrics import PayoffMetrics

    metrics = PayoffMetrics(
        mean_bp=45.6, std_bp=155.0, skew=1.47, excess_kurtosis=2.0,
        p_profit=0.518, ev_given_profit_bp=70.0, ev_given_loss_bp=-30.0,
        asymmetry_ratio=2.92,
        percentiles_bp={"p5": -200, "p25": -50, "p50": 5, "p75": 80, "p95": 250},
        tail_ratio=5.88,
    )
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"marginal": metrics},
        primary_method="marginal", carry_3m_bp=365.0, rolldown_bp=0.51,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.64, rank=1,
    )
    snap = SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(r,),
        config_summary={"universe_size": 4},
    )
    table = build_signal_table_from_snapshots([snap])
    assert datetime.date(2026, 4, 28) in table
    sigs = table[datetime.date(2026, 4, 28)]
    assert len(sigs) == 1
    assert sigs[0].direction == "PAY SFRZ26"
    assert sigs[0].asymmetry_ratio == 2.92
    assert sigs[0].flip is False
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# Append to RVUtils/SFRConvexScreener/_backtest_signals.py
from typing import Dict, Iterable, List

from RVUtils.SFRConvexScreener._types import SFRConvexScreenerSnapshot


def build_signal_table_from_snapshots(
    snapshots: Iterable[SFRConvexScreenerSnapshot],
) -> Dict[datetime.date, List[BacktestSignal]]:
    """Flatten a sequence of screener snapshots into a date-keyed signal table."""
    out: Dict[datetime.date, List[BacktestSignal]] = {}
    for snap in snapshots:
        rows: List[BacktestSignal] = []
        for r in snap.results:
            primary = r.metrics_by_method.get(r.primary_method)
            if primary is None:
                continue
            asym = float(primary.asymmetry_ratio)
            flip = asym < 1.0
            stale = any("stale_smile_asof" in w for w in r.warnings)
            rows.append(
                BacktestSignal(
                    as_of=snap.as_of,
                    structure_def=r.structure_def,
                    direction=r.direction(),
                    flip=flip,
                    asymmetry_ratio=asym,
                    composite_score=float(r.composite_score),
                    mean_bp=float(primary.mean_bp),
                    std_bp=float(primary.std_bp),
                    rolldown_bp=float(r.rolldown_bp),
                    carry_3m_bp=float(r.carry_3m_bp),
                    is_stale=stale,
                )
            )
        out[snap.as_of] = rows
    return out
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_backtest_signals.py tests/test_sfr_convex_screener_backtest_signals.py
git commit -m "feat(sfr-screener): flatten snapshots into BacktestSignal table"
```

---

## Phase 2: Query construction

### Task 2.1: `structure_to_query` helper

Each `BacktestSignal` must produce an `IRSwapQuery` understood by the backtest engine. Map:
- `OUTRIGHT` → `IRSwapStructure.OUTRIGHT` with single tenor (e.g., `IMM_M2027xIMM_U2027`)
- `CALENDAR` → `IRSwapStructure.SPREAD` with `front_tenor`, `back_tenor`
- `BUTTERFLY` → `IRSwapStructure.FLY` with `front_tenor`, `belly_tenor`, `back_tenor`

bpv sign comes from `flip` (True → flip the direction, RECEIVE side).

**Files:**
- Create: `RVUtils/SFRConvexScreener/_backtest_query.py`
- Test: `tests/test_sfr_convex_screener_backtest_query.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_backtest_query.py
import datetime
from RVUtils.SFRConvexScreener import Leg, StructureDef, StructureType
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal
from RVUtils.SFRConvexScreener._backtest_query import (
    structure_to_query,
    structure_position_tag,
)


def _signal(structure_def, *, flip=False):
    return BacktestSignal(
        as_of=datetime.date(2026, 4, 28),
        structure_def=structure_def,
        direction="X",
        flip=flip,
        asymmetry_ratio=1.5 if not flip else 0.5,
        composite_score=0.5,
        mean_bp=1.0,
        std_bp=10.0,
        rolldown_bp=0.5,
        carry_3m_bp=100.0,
        is_stale=False,
    )


def test_structure_to_query_outright_pay():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    q = structure_to_query(_signal(sd), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    # PAY = +bpv (long-rate convention)
    assert q.structure_kwargs["tenor"] == "IMM_Z2026xIMM_H2027"
    assert q.structure_kwargs["bpv"] == 100_000


def test_structure_to_query_outright_receive_flips_sign():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    q = structure_to_query(_signal(sd, flip=True), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    assert q.structure_kwargs["bpv"] == -100_000


def test_structure_to_query_calendar():
    sd = StructureDef(
        structure_id="SFRM27_SFRU27_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("SFRM27", 1.0, 96.5, 25), Leg("SFRU27", -1.0, 96.6, 25)),
    )
    q = structure_to_query(_signal(sd), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    kw = q.structure_kwargs
    assert kw["front_tenor"] == "IMM_M2027xIMM_U2027"
    assert kw["back_tenor"] == "IMM_U2027xIMM_Z2027"


def test_structure_to_query_fly_long_rate():
    sd = StructureDef(
        structure_id="SFRM27_SFRU27_SFRZ27_FLY_1_-2_1",
        structure_type=StructureType.BUTTERFLY,
        legs=(
            Leg("SFRM27", 1.0, 96.5, 25),
            Leg("SFRU27", -2.0, 96.6, 25),
            Leg("SFRZ27", 1.0, 96.7, 25),
        ),
    )
    q = structure_to_query(_signal(sd), curve="USD-SOFR-1D-Q12STIRT", bpv=100_000)
    kw = q.structure_kwargs
    assert kw["front_tenor"] == "IMM_M2027xIMM_U2027"
    assert kw["belly_tenor"] == "IMM_U2027xIMM_Z2027"
    assert kw["back_tenor"] == "IMM_Z2027xIMM_H2028"


def test_structure_position_tag_uses_structure_id():
    sd = StructureDef(
        structure_id="SFRZ26_OUTRIGHT",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    sig = _signal(sd)
    assert structure_position_tag(sig) == "sfr_screener_SFRZ26_OUTRIGHT"
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_backtest_query.py
"""Map BacktestSignal → IRSwapQuery for the backtest engine."""

from __future__ import annotations

import logging
from typing import Any, Dict

from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure

from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal
from RVUtils.SFRConvexScreener._carry_roll import sfr_to_imm_tenor
from RVUtils.SFRConvexScreener._types import StructureType

logger = logging.getLogger(__name__)


def structure_position_tag(sig: BacktestSignal) -> str:
    """Deterministic position tag — used by the exit trigger to find positions."""
    return f"sfr_screener_{sig.structure_def.structure_id}"


def structure_to_query(
    sig: BacktestSignal,
    *,
    curve: str,
    bpv: float,
) -> IRSwapQuery:
    """Build an `IRSwapQuery` for a single BacktestSignal.

    bpv carries the *long-rate* convention; ``flip=True`` (i.e. asymmetry < 1)
    inverts the bpv to express the receiver / long-price direction.
    """
    sd = sig.structure_def
    legs = sd.legs
    sign = -1.0 if sig.flip else 1.0
    tags = [structure_position_tag(sig)]

    if sd.structure_type is StructureType.OUTRIGHT:
        leg = legs[0]
        return IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            curve=curve,
            structure_kwargs={
                "tenor": sfr_to_imm_tenor(leg.contract),
                "bpv": sign * float(leg.weight) * float(bpv),
            },
            tags=tags,
        )

    if sd.structure_type is StructureType.CALENDAR:
        front = next(l for l in legs if l.weight > 0)
        back = next(l for l in legs if l.weight < 0)
        return IRSwapQuery(
            structure=IRSwapStructure.SPREAD,
            curve=curve,
            structure_kwargs={
                "front_tenor": sfr_to_imm_tenor(front.contract),
                "back_tenor": sfr_to_imm_tenor(back.contract),
                "bpv": sign * float(bpv),
            },
            tags=tags,
        )

    if sd.structure_type is StructureType.BUTTERFLY:
        wings = [l for l in legs if l.weight > 0]
        belly = next(l for l in legs if l.weight < 0)
        if len(wings) != 2:
            raise ValueError(f"Butterfly needs exactly two +1 wings: {sd.structure_id}")
        front, back = sorted(wings, key=lambda l: l.contract)
        return IRSwapQuery(
            structure=IRSwapStructure.FLY,
            curve=curve,
            structure_kwargs={
                "front_tenor": sfr_to_imm_tenor(front.contract),
                "belly_tenor": sfr_to_imm_tenor(belly.contract),
                "back_tenor": sfr_to_imm_tenor(back.contract),
                "bpv": sign * float(bpv),
            },
            tags=tags,
        )

    raise ValueError(f"unsupported structure_type: {sd.structure_type}")
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_backtest_query.py tests/test_sfr_convex_screener_backtest_query.py
git commit -m "feat(sfr-screener): structure → IRSwapQuery helper for backtest"
```

---

## Phase 3: Entry trigger

### Task 3.1: `SFRScreenerEntryTrigger` via `FlowSignalTriggerRequirements`

**Files:**
- Create: `RVUtils/SFRConvexScreener/_backtest_triggers.py`
- Test: `tests/test_sfr_convex_screener_backtest_triggers.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_backtest_triggers.py
import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from RVUtils.SFRConvexScreener import Leg, StructureDef, StructureType
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal
from RVUtils.SFRConvexScreener._backtest_triggers import (
    SFRScreenerBacktestConfig,
    build_entry_trigger,
)


def _signal(sid: str, *, asym: float = 2.0, score: float = 0.6, flip: bool = False) -> BacktestSignal:
    sd = StructureDef(
        structure_id=sid,
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    return BacktestSignal(
        as_of=datetime.date(2026, 4, 28),
        structure_def=sd, direction="PAY SFRZ26", flip=flip,
        asymmetry_ratio=asym, composite_score=score,
        mean_bp=10.0, std_bp=20.0, rolldown_bp=0.5, carry_3m_bp=350.0,
        is_stale=False,
    )


def test_entry_trigger_fires_when_top_signal_passes_filters():
    table = {datetime.date(2026, 4, 28): [_signal("X", asym=3.0, score=1.0)]}
    cfg = SFRScreenerBacktestConfig(
        entry_min_asymmetry=1.5,
        entry_min_composite_score=0.0,
        max_concurrent=10,
    )
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is True


def test_entry_trigger_filters_below_asymmetry_threshold():
    table = {datetime.date(2026, 4, 28): [_signal("X", asym=1.05)]}
    cfg = SFRScreenerBacktestConfig(entry_min_asymmetry=1.5)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is False


def test_entry_trigger_caps_at_max_concurrent():
    sigs = [_signal(f"X{i}", asym=2.0, score=1.0 - i * 0.01) for i in range(10)]
    table = {datetime.date(2026, 4, 28): sigs}
    cfg = SFRScreenerBacktestConfig(max_concurrent=2)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []  # nothing open
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is True
    # exactly 2 entry orders
    actions = info.info
    assert any(len(orders) == 2 for orders in actions.values())


def test_entry_trigger_skips_stale_when_configured():
    s_fresh = _signal("Fresh", asym=2.0)
    s_stale = _signal("Stale", asym=2.0)
    s_stale = BacktestSignal(**{**s_stale.__dict__, "is_stale": True})
    table = {datetime.date(2026, 4, 28): [s_fresh, s_stale]}
    cfg = SFRScreenerBacktestConfig(skip_stale=True, max_concurrent=10)
    trig = build_entry_trigger(table, cfg)
    bt = MagicMock()
    bt.portfolio.positions = []
    info = trig.has_triggered(datetime.datetime(2026, 4, 28, 17, 0), backtest=bt)
    assert bool(info) is True
    orders = next(iter(info.info.values()))
    ids = [(o.query.tags or [None])[0] for o in orders]
    assert "sfr_screener_Fresh" in ids
    assert "sfr_screener_Stale" not in ids
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_backtest_triggers.py
"""Entry/exit triggers for the SFR Convex Screener backtest.

Both triggers wrap `FlowSignalTriggerRequirements` with a `signal_fn` that
looks up the date-keyed signal table and emits orders/unwinds. Entry uses
`AddQueryAction`; exit uses `UnwindPositionsAction`.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from BT.event import TriggerInfo
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_order import QueryOrder, UnwindOrder
from BT.triggers import FlowSignalTriggerRequirements, Trigger

from RVUtils.SFRConvexScreener._backtest_query import (
    structure_position_tag,
    structure_to_query,
)
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal

logger = logging.getLogger(__name__)


@dataclass
class SFRScreenerBacktestConfig:
    # --- Curve / sizing ---
    curve: str = "USD-SOFR-1D-Q12STIRT"
    bpv_per_trade: float = 100_000.0

    # --- Entry filters ---
    entry_min_asymmetry: float = 1.5  # uses max(A, 1/A) so direction-agnostic
    entry_min_composite_score: float = 0.0
    skip_stale: bool = True
    structure_types: Tuple[str, ...] = ("outright", "calendar", "butterfly")
    max_concurrent: int = 5
    rebalance_dow: Optional[int] = None  # 0=Mon … 4=Fri; None = every day

    # --- Exit conditions (first match wins) ---
    exit_asymmetry_threshold: float = 1.10  # asymmetry decays below → exit
    exit_take_profit_bp: Optional[float] = None  # exit if MTM ≥ +X bp
    exit_stop_loss_bp: Optional[float] = None    # exit if MTM ≤ -X bp
    exit_max_holding_days: int = 22

    # --- Costs (passed through to UnwindPositionsAction) ---
    round_trip_cost_bp: float = 0.5  # half taken at unwind via UnwindPositionsAction.fee


def _asym_magnitude(a: float) -> float:
    if a <= 0 or not (a == a):  # NaN-safe
        return 0.0
    return max(a, 1.0 / a)


def _entry_signal_fn(table, config):
    def fn(state: datetime.datetime, backtest=None):
        if config.rebalance_dow is not None and state.weekday() != config.rebalance_dow:
            return TriggerInfo(False)
        target_date = state.date()
        sigs = table.get(target_date) or []
        if not sigs:
            return TriggerInfo(False)

        # Filter
        passing: List[BacktestSignal] = []
        for s in sigs:
            if s.structure_def.structure_type.value not in config.structure_types:
                continue
            if config.skip_stale and s.is_stale:
                continue
            if _asym_magnitude(s.asymmetry_ratio) < config.entry_min_asymmetry:
                continue
            if s.composite_score < config.entry_min_composite_score:
                continue
            passing.append(s)
        if not passing:
            return TriggerInfo(False)

        # Sort by composite_score desc
        passing.sort(key=lambda s: s.composite_score, reverse=True)

        # Skip duplicates of currently-open structures
        open_tags: set = set()
        if backtest is not None:
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))
        passing = [s for s in passing if structure_position_tag(s) not in open_tags]
        if not passing:
            return TriggerInfo(False)

        # Cap by max_concurrent
        n_open = len(backtest.portfolio.positions) if backtest is not None else 0
        slots = max(0, config.max_concurrent - n_open)
        if slots == 0:
            return TriggerInfo(False)
        passing = passing[:slots]

        # Build orders
        orders: List[QueryOrder] = []
        for s in passing:
            try:
                q = structure_to_query(
                    s, curve=config.curve, bpv=config.bpv_per_trade,
                )
                orders.append(
                    QueryOrder(
                        timestamp=state,
                        query=q,
                        meta={
                            "action": "sfr_screener_entry",
                            "tags": [structure_position_tag(s)],
                            "structure_id": s.structure_def.structure_id,
                            "direction": s.direction,
                            "flip": s.flip,
                            "entry_asymmetry": s.asymmetry_ratio,
                            "entry_composite": s.composite_score,
                            "entry_mean_bp": s.mean_bp,
                            "entry_carry_3m_bp": s.carry_3m_bp,
                            "entry_rolldown_bp": s.rolldown_bp,
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "failed to build entry query for %s: %s",
                    s.structure_def.structure_id, exc,
                )
        if not orders:
            return TriggerInfo(False)
        return TriggerInfo(True, {AddQueryAction: orders})

    return fn


def build_entry_trigger(
    signal_table: Dict[datetime.date, List[BacktestSignal]],
    config: SFRScreenerBacktestConfig,
) -> Trigger:
    """Wire a FlowSignalTriggerRequirements that emits AddQueryAction orders."""
    reqs = FlowSignalTriggerRequirements(signal_fn=_entry_signal_fn(signal_table, config))
    # The action class itself is a passthrough — orders are pre-built and
    # placed under `AddQueryAction` in the TriggerInfo.info dict so the
    # framework picks them up by class key.
    action = _PassThroughEntryAction()
    return Trigger(trigger_requirements=reqs, actions=[action])


class _PassThroughEntryAction:
    """Returns the entry orders that were pre-staged by the signal_fn."""

    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return list(info.get(AddQueryAction, []))
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_backtest_triggers.py tests/test_sfr_convex_screener_backtest_triggers.py
git commit -m "feat(sfr-screener): entry trigger via FlowSignalTriggerRequirements"
```

---

## Phase 4: Exit trigger

### Task 4.1: `build_exit_trigger`

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_backtest_triggers.py`
- Test: extend `tests/test_sfr_convex_screener_backtest_triggers.py`

**Step 1: Write the failing test**

```python
def test_exit_trigger_fires_on_asymmetry_decay():
    """A position open with entry asymmetry 3.0 exits when current asymmetry drops below 1.10."""
    from RVUtils.SFRConvexScreener._backtest_triggers import build_exit_trigger

    sd = StructureDef(
        structure_id="X",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    table = {
        datetime.date(2026, 5, 5): [BacktestSignal(
            as_of=datetime.date(2026, 5, 5), structure_def=sd, direction="PAY",
            flip=False, asymmetry_ratio=1.05, composite_score=0.0,
            mean_bp=0.0, std_bp=10.0, rolldown_bp=0.0, carry_3m_bp=350.0,
            is_stale=False,
        )]
    }
    cfg = SFRScreenerBacktestConfig(exit_asymmetry_threshold=1.10)
    trig = build_exit_trigger(table, cfg)

    bt = MagicMock()
    fake_pos = MagicMock()
    fake_pos.meta = {
        "tags": ["sfr_screener_X"],
        "structure_id": "X",
        "entry_asymmetry": 3.0,
        "flip": False,
    }
    fake_pos.opened = pd.Timestamp("2026-04-28")
    bt.portfolio.positions = [fake_pos]

    info = trig.has_triggered(datetime.datetime(2026, 5, 5, 17, 0), backtest=bt)
    assert bool(info) is True


def test_exit_trigger_max_holding_days():
    from RVUtils.SFRConvexScreener._backtest_triggers import build_exit_trigger

    sd = StructureDef(
        structure_id="X",
        structure_type=StructureType.OUTRIGHT,
        legs=(Leg("SFRZ26", 1.0, 96.5, 25),),
    )
    table = {
        datetime.date(2026, 5, 30): [BacktestSignal(
            as_of=datetime.date(2026, 5, 30), structure_def=sd, direction="PAY",
            flip=False, asymmetry_ratio=3.0, composite_score=0.0,
            mean_bp=0.0, std_bp=10.0, rolldown_bp=0.0, carry_3m_bp=350.0,
            is_stale=False,
        )]
    }
    cfg = SFRScreenerBacktestConfig(exit_max_holding_days=22)
    trig = build_exit_trigger(table, cfg)
    bt = MagicMock()
    pos = MagicMock()
    pos.meta = {"tags": ["sfr_screener_X"], "structure_id": "X",
                "entry_asymmetry": 3.0, "flip": False}
    pos.opened = pd.Timestamp("2026-04-28")
    bt.portfolio.positions = [pos]
    info = trig.has_triggered(datetime.datetime(2026, 5, 30, 17, 0), backtest=bt)
    assert bool(info) is True
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# Append to RVUtils/SFRConvexScreener/_backtest_triggers.py

def _exit_signal_fn(table, config):
    def fn(state: datetime.datetime, backtest=None):
        if backtest is None or not backtest.portfolio.positions:
            return TriggerInfo(False)

        target_date = state.date()
        signals_today = {
            structure_position_tag(_to_signal_tag_proxy(s)): s
            for s in (table.get(target_date) or [])
        }

        unwinds: List[UnwindOrder] = []
        for pos in backtest.portfolio.positions:
            tags = set((pos.meta or {}).get("tags", []))
            screener_tags = [t for t in tags if t.startswith("sfr_screener_")]
            if not screener_tags:
                continue
            tag = screener_tags[0]
            structure_id = (pos.meta or {}).get("structure_id", tag.replace("sfr_screener_", ""))
            entry_meta = pos.meta or {}
            exit_reason = None

            sig_today = signals_today.get(tag)

            # 1. Asymmetry decay
            if sig_today is not None and config.exit_asymmetry_threshold is not None:
                # Use the "edge" magnitude in the position's direction:
                # if entered with flip=False (long-rate), edge erodes when
                # asymmetry_ratio falls; if entered with flip=True
                # (long-price), edge erodes when 1/asymmetry_ratio falls.
                a = float(sig_today.asymmetry_ratio)
                edge = (1.0 / a) if entry_meta.get("flip") else a
                if edge < config.exit_asymmetry_threshold:
                    exit_reason = "asymmetry_decay"

            # 2. Take profit / stop loss via mtm_history (best-effort; falls back to no-op)
            if exit_reason is None and (config.exit_take_profit_bp or config.exit_stop_loss_bp):
                pnl_bp = _position_pnl_bp(pos, backtest, config.bpv_per_trade)
                if pnl_bp is not None:
                    if config.exit_take_profit_bp is not None and pnl_bp >= config.exit_take_profit_bp:
                        exit_reason = "tp_bp"
                    elif config.exit_stop_loss_bp is not None and pnl_bp <= config.exit_stop_loss_bp:
                        exit_reason = "stop_bp"

            # 3. Max holding
            if exit_reason is None and config.exit_max_holding_days is not None:
                opened = getattr(pos, "opened", None)
                if opened is not None:
                    held = (state.date() - opened.date() if hasattr(opened, "date") else state.date() - opened).days
                    if held >= config.exit_max_holding_days:
                        exit_reason = "max_holding"

            if exit_reason is None:
                continue

            _t = tag
            unwinds.append(
                UnwindOrder(
                    timestamp=state,
                    selector=lambda p, _t=_t: _t in set((p.meta or {}).get("tags", [])),
                    meta={
                        "action": "sfr_screener_exit",
                        "reason": exit_reason,
                        "structure_id": structure_id,
                        "fee": float(config.round_trip_cost_bp),
                    },
                )
            )

        if not unwinds:
            return TriggerInfo(False)
        return TriggerInfo(True, {UnwindPositionsAction: unwinds})

    return fn


def _to_signal_tag_proxy(sig: BacktestSignal):
    """Identity helper so we can index a per-date signal list by tag without
    re-constructing each BacktestSignal."""
    return sig


def _position_pnl_bp(pos: Any, backtest: Any, bpv: float) -> Optional[float]:
    """Approximate position MTM in bp using the engine's mtm_history.

    Returns None on any data shape mismatch — the caller treats that as
    "TP/SL not evaluable" and skips those exit conditions.
    """
    try:
        mtm_history = getattr(backtest, "mtm_history", {}) or {}
        if not mtm_history:
            return None
        latest_dt = max(mtm_history.keys())
        # Per-position MTM lookup is engine-specific; fall back to portfolio-level.
        portfolio_pnl_dollar = float(mtm_history[latest_dt])
        # Approximate per-position bp (only meaningful with single open position;
        # otherwise the orchestrator should run TP/SL via per-position MTM hooks).
        if bpv <= 0:
            return None
        return portfolio_pnl_dollar / float(bpv)
    except Exception:
        return None


def build_exit_trigger(
    signal_table: Dict[datetime.date, List[BacktestSignal]],
    config: SFRScreenerBacktestConfig,
) -> Trigger:
    reqs = FlowSignalTriggerRequirements(signal_fn=_exit_signal_fn(signal_table, config))
    return Trigger(trigger_requirements=reqs, actions=[_PassThroughExitAction()])


class _PassThroughExitAction:
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        return list(info.get(UnwindPositionsAction, []))
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_backtest_triggers.py tests/test_sfr_convex_screener_backtest_triggers.py
git commit -m "feat(sfr-screener): exit trigger (asymmetry decay + TP/SL + max hold)"
```

---

## Phase 5: Top-level wiring

### Task 5.1: `run_backtest` orchestrator

**Files:**
- Create: `RVUtils/SFRConvexScreener/backtest.py`
- Modify: `RVUtils/SFRConvexScreener/__init__.py` (re-export `SFRScreenerBacktestConfig`, `run_backtest`)
- Test: `tests/test_sfr_convex_screener_backtest_orchestrator.py` (integration-marked smoke)

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_backtest_orchestrator.py
import datetime

import pandas as pd
import pytest
import pytz

from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig
from RVUtils.SFRConvexScreener.backtest import (
    SFRScreenerBacktestConfig,
    run_backtest,
)


@pytest.mark.integration
def test_run_backtest_smoke(tmp_path):
    NYC = pytz.timezone("America/New_York")
    bt_dates = pd.bdate_range(
        NYC.localize(datetime.datetime(2026, 4, 21, 17, 0)),
        NYC.localize(datetime.datetime(2026, 4, 28, 17, 0)),
        tz=NYC,
    )
    screener_cfg = SFRConvexScreenerConfig(
        universe_size=4, calendar_gaps=(1,), fly_gaps=(1,),
        correlation_window=10, n_simulations=10_000,
    )
    bt_cfg = SFRScreenerBacktestConfig(max_concurrent=2)
    bt = run_backtest(
        bt_datetimes=[d.to_pydatetime() for d in bt_dates],
        screener_config=screener_cfg,
        backtest_config=bt_cfg,
        cache_root=tmp_path,
    )
    assert bt is not None
    assert hasattr(bt, "portfolio")
```

**Step 2: Run test (FAIL — module doesn't exist)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/backtest.py
"""Top-level entry point for the SFR Convex Screener backtest."""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import pandas as pd

from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig, build_snapshot
from RVUtils.SFRConvexScreener._backtest_cache import (
    SnapshotCache,
    load_or_build_many,
)
from RVUtils.SFRConvexScreener._backtest_signals import (
    build_signal_table_from_snapshots,
)
from RVUtils.SFRConvexScreener._backtest_triggers import (
    SFRScreenerBacktestConfig,
    build_entry_trigger,
    build_exit_trigger,
)

logger = logging.getLogger(__name__)


def run_backtest(
    *,
    bt_datetimes: Sequence[datetime.datetime],
    screener_config: SFRConvexScreenerConfig,
    backtest_config: SFRScreenerBacktestConfig,
    cache_root: Optional[Path] = None,
    snapshot_dates: Optional[Iterable[datetime.date]] = None,
    show_progress: bool = True,
) -> QueryDrivenBacktest:
    """Run the SFR Convex Screener backtest.

    Parameters
    ----------
    bt_datetimes : sequence of datetime
        TZ-aware datetimes that form the simulation TimeGrid.
    screener_config : SFRConvexScreenerConfig
        Passed to `build_snapshot` per as_of date.
    backtest_config : SFRScreenerBacktestConfig
        Filter thresholds, sizing, and exit conditions.
    cache_root : Path, optional
        Directory for the on-disk snapshot cache. Defaults to
        ``data/screener_results/sfr_convex_screener_backtest_cache``.
    snapshot_dates : iterable of date, optional
        Defaults to the unique dates in ``bt_datetimes``.
    """
    if cache_root is None:
        cache_root = Path("data/screener_results/sfr_convex_screener_backtest_cache")
    cache = SnapshotCache(root=cache_root)

    if snapshot_dates is None:
        snapshot_dates = sorted({d.date() for d in bt_datetimes})

    config_summary = _config_summary_for_cache(screener_config)

    def _build_one(d: datetime.date):
        return build_snapshot(screener_config, as_of=d)

    snapshots = load_or_build_many(
        dates=snapshot_dates,
        cache=cache,
        build_fn=_build_one,
        config_summary=config_summary,
        show_progress=show_progress,
    )
    signal_table = build_signal_table_from_snapshots(snapshots.values())

    entry = build_entry_trigger(signal_table, backtest_config)
    exit_ = build_exit_trigger(signal_table, backtest_config)

    curve_mdp = IRSwapsMDP(source=screener_config.curve_source)
    strategy = QueryStrategy(
        name="sfr_convex_screener",
        triggers=[entry, exit_],
        default_mdp=curve_mdp,
    )
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(list(bt_datetimes)),
        strategy=strategy,
        mdp=curve_mdp,
        show_progress=show_progress,
    )
    bt.run()
    return bt


def _config_summary_for_cache(cfg: SFRConvexScreenerConfig) -> dict:
    return {
        "universe_size": cfg.universe_size,
        "include_outrights": cfg.include_outrights,
        "jpm_method": cfg.jpm_method,
        "calendar_gaps": list(cfg.calendar_gaps),
        "fly_gaps": list(cfg.fly_gaps),
        "correlation_window": cfg.correlation_window,
        "n_simulations": cfg.n_simulations,
        "ghost_extension_bps": cfg.ghost_extension_bps,
    }
```

**Step 4: Verify import-only**

```
conda run -n stir python -c "from RVUtils.SFRConvexScreener.backtest import run_backtest; print('ok')"
```

Expected: `ok`. Skip the integration test in CI.

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/backtest.py RVUtils/SFRConvexScreener/__init__.py tests/test_sfr_convex_screener_backtest_orchestrator.py
git commit -m "feat(sfr-screener): top-level run_backtest orchestrator"
```

---

## Phase 6: Notebook frontend + tearsheet

### Task 6.1: `notebooks/backtests/sfr_convex_screener_backtest.ipynb`

**Files:**
- Create: `notebooks/backtests/sfr_convex_screener_backtest.ipynb`

**Step 1: Author the notebook**

Mirror `notebooks/backtests/sfr_fly_rv_backtest.ipynb`. Cells:

1. **Setup**: imports, `nest_asyncio.apply()`, NYC tz, `sys.path.append("../../")`.
2. **Config**:
   ```python
   from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig, JointMethod
   from RVUtils.SFRConvexScreener.backtest import (
       SFRScreenerBacktestConfig, run_backtest,
   )

   screener_cfg = SFRConvexScreenerConfig(
       universe_size=12,
       include_outrights=True,
       jpm_method=True,
       primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
       correlation_window=60,
       n_simulations=50_000,
   )
   bt_cfg = SFRScreenerBacktestConfig(
       bpv_per_trade=100_000,
       entry_min_asymmetry=1.5,
       entry_min_composite_score=0.0,
       skip_stale=True,
       structure_types=("outright", "calendar", "butterfly"),
       max_concurrent=5,
       rebalance_dow=4,                 # Friday rebalance
       exit_asymmetry_threshold=1.10,
       exit_take_profit_bp=10.0,
       exit_stop_loss_bp=-15.0,
       exit_max_holding_days=22,
       round_trip_cost_bp=0.5,
   )
   ```
3. **Build TimeGrid**: `pd.bdate_range(start, end, tz=NYC)` and convert to list of datetimes.
4. **Run**:
   ```python
   bt = run_backtest(
       bt_datetimes=bt_datetimes,
       screener_config=screener_cfg,
       backtest_config=bt_cfg,
       show_progress=True,
   )
   ```
5. **Tearsheet** — copy the MTM/drawdown/Sharpe/hit-rate cell from `sfr_fly_rv_backtest.ipynb`. Add:
   - Trade log per `bt.portfolio.trades_log` with `structure_id`, `direction`, `entry_asymmetry`, `entry_composite`.
   - Unwind log grouped by `reason` (`asymmetry_decay`, `tp_bp`, `stop_bp`, `max_holding`).
   - Histogram of P&L per closed structure_type (outright vs calendar vs fly).
6. **Sensitivity sweeps** — small grid over `entry_min_asymmetry ∈ {1.5, 2.0, 3.0}` and `max_concurrent ∈ {3, 5, 10}`; plot Sharpe vs threshold.
7. **Caveats** markdown:
   - Snapshots are pickled; cache invalidates only when `_config_summary_for_cache` changes — bump the hash key when methodology changes.
   - The historical Gaussian-copula path uses 60d daily-change correlation; in sparse-history regimes (e.g., post-launch contracts) the copula falls back to identity.
   - Round-trip costs are crude (flat 0.5 bp); tighten with venue-specific bid-ask before sizing.

**Step 2: Execute notebook end-to-end** (best-effort — may fail if cache priming hits Barchart rate limits):

```bash
conda run -n stir jupyter nbconvert --to notebook --execute notebooks/backtests/sfr_convex_screener_backtest.ipynb --output sfr_convex_screener_backtest.ipynb
```

**Step 3: Commit**

```bash
git add notebooks/backtests/sfr_convex_screener_backtest.ipynb
git commit -m "feat(sfr-screener): backtest notebook frontend"
```

---

## Phase 7: Verification

### Task 7.1: Full unit suite

```bash
conda run -n stir pytest tests/test_sfr_convex_screener_*.py -v -m "not integration"
```

Expected: all unit tests pass.

### Task 7.2: One-week paper backtest

Run the notebook with a one-week date range (5 BDays) and a 4-contract universe to confirm the full pipeline executes end-to-end in under 10 minutes with cache priming. Inspect:

- `bt.portfolio.trades_log` — should contain 1+ entries
- `bt.portfolio.unwind_log` — entries match exit reasons
- MTM history — daily values present, finite

### Task 7.3: Final commit + push

```bash
git add -A
git status
git commit -m "chore(sfr-screener): final backtest verification"
git push
```

---

## File map (final state)

```
RVUtils/SFRConvexScreener/
├── _backtest_cache.py         (new — SnapshotCache, load_or_build_many)
├── _backtest_signals.py       (new — BacktestSignal, build_signal_table_from_snapshots)
├── _backtest_query.py         (new — structure_to_query, structure_position_tag)
├── _backtest_triggers.py      (new — entry/exit triggers via FlowSignalTriggerRequirements)
├── backtest.py                (new — run_backtest top-level)
└── __init__.py                (modified — re-exports backtest API)

notebooks/backtests/
└── sfr_convex_screener_backtest.ipynb   (new)

tests/
├── test_sfr_convex_screener_backtest_cache.py
├── test_sfr_convex_screener_backtest_signals.py
├── test_sfr_convex_screener_backtest_query.py
├── test_sfr_convex_screener_backtest_triggers.py
└── test_sfr_convex_screener_backtest_orchestrator.py

docs/plans/
└── 2026-04-28-sfr-convex-screener-backtest.md   (this file)
```

---

## Notes for the executing engineer

- **Cache primes are slow.** Each new as_of date is a full screener run (12 contracts × 60d bulk fetch + 12 SABR smiles + BL extraction × 12 + joint calibration). Plan ~5–20 minutes per uncached date, depending on Barchart rate-limit state. Pre-prime the cache with `RVUtils.SFRConvexScreener._backtest_cache.load_or_build_many` before kicking off the QueryDrivenBacktest run.
- **Don't bypass `FlowSignalTriggerRequirements`.** The user explicitly mandated this trigger interface — entry and exit logic stays inside the `signal_fn` callback. Don't write custom subclasses of `Trigger` or `TriggerRequirements` for this backtest.
- **Tag positions deterministically.** `structure_position_tag(sig)` returns `sfr_screener_<structure_id>` — use this verbatim in both the entry meta `tags` and the exit `UnwindPositionsAction.match_tag` selector. Mismatched tags = exits never fire.
- **rateslib limitations carry over.** The underlying screener's known issues (jpm_method tail dependence, 1m rolldown horizon for SR3 IMM-IMM) are inherited by the backtest. Document caveats prominently in the notebook.
- **Run all Python via `conda run -n stir`.**
