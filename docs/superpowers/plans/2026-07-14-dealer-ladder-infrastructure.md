# Dealer Positioning Ladder Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Layers 1–3 of the dealer positioning delta ladder — per-print projection onto meeting/futures/SERFF-basis buckets, synthetic dealer book MTM with arbitrary intraday snapshots, and the pure-query ladder-state layer — plus the 6-month backfill.

**Spec:** `docs/superpowers/specs/2026-07-14-dealer-positioning-delta-ladder-design.md` (approved — authority on rules). Classifier spec/plan for upstream conventions: `docs/superpowers/specs/2026-07-12-stir-dealer-direction-classifier-design.md`.

**Scope:** This plan = the durable observable (spec Sections 2–8, 11–12). The `BT/dealer_ladder` Phase-4 research harness is a separate follow-up plan written once ladder data exists; Phase 5 is gated on Phase 4's verdict (spec Sections 9–10).

**Architecture:** New modules in the existing `SDRUtils/stir_flow/` package. Pricing happens once per print (projection + entry mark) and once per open position per reval; everything else (decay, weighting, netting, rank views) is read-time pandas over persisted vectors.

**Tech Stack:** Python (conda env `stir`), pandas, psycopg2, rateslib via `build_delta_risk_ladder`/`build_basis_risk_ladder` (`MDP/IRSwaps/BARCHART_STIRF/risk.py`), existing `SDRUtils/stir_flow/` classifier modules, pytest.

## Global Constraints

- All Python/pytest via `conda run -n stir ...`. `conda run` cannot take multiline `-c` — write scripts to files.
- Fast gate must stay green after every task: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.
- Pricer tests marked `@pytest.mark.network` + `@pytest.mark.slow`; prod-DB tests `@pytest.mark.db`.
- DB is REMOTE SUPABASE PROD. WRITE ONLY to `arbs_stir_ladder_prints_v1` and `arbs_stir_book_marks_v1`. READ from `arbs_stir_direction_v1`, `arbs_stir_tick_size_v1`, `arbs_usd_swap_tape_legs_v2`, `arbs_usd_swap_tape_packages_v2`. Never modify tape or classifier tables.
- Tape `fixed_rate` is ALREADY decimal (0.03713 = 3.713%) — pass to pricer as-is.
- **Projection snapshot** = classifier convention: `floor(original_execution_timestamp → ET, 1min) − 1min` (`SDRUtils/stir_flow/pricing.snap_timestamp`). **MTM snapshot** = `floor(ts → ET, 1min)` with NO minus-1 (MTM wants the mark at ts, not the dealer's decision curve).
- Curves: SOFR → `USD-SOFR-1D-Q12xM12STIRT`, FED_FUNDS → `USD-OIS-Q12xM12STIRT-SERFFX-MIX23`, source `BARCHART_STIRF-RL` (reuse `stir_flow/config.CURVE_FOR`).
- **Persisted sign convention:** `delta_dv01 > 0` ⟺ dealer long futures-equivalent ⟺ dealer RECEIVED fixed. Anticipated dealer hedge flow = −ladder.
- **Absolute bucket keys only** (meeting date ISO / contract symbol / contract month) — never CM ranks; rank views are read-time.
- Visibility rule v1: `execution_ts + 15min` if `is_block` else `execution_ts + 1min`. (Dissemination-timestamp column investigation is Task 5 Step 1; if found, wiring it is a follow-up, not this plan.)
- Provisional EWMA half-lives until Phase 4 calibrates: default 90min, block 240min.
- Branch `feat/stir-dealer-ladder`; create a worktree via superpowers:using-git-worktrees at a SHORT sibling path (`../ARBS-ladder`).

## File Structure

```
SDRUtils/stir_flow/ladder_conventions.py     signs, visibility, bucket-key helpers (pure)
SDRUtils/_swappulse_scripts/_stir_ladder_schema_v1.py   DDL for the 2 new tables
SDRUtils/stir_flow/ladder.py                 risk models, delta extraction, project_unit (pricer-touching)
SDRUtils/stir_flow/unwinds.py                lifecycle-linked unwind extraction (degrades gracefully)
SDRUtils/stir_flow/ladder_state.py           Layer 3: pure-query ladder (EWMA/weighting/netting/views)
SDRUtils/stir_flow/book.py                   Layer 2: open positions, reval, EOD marks, book_snapshot
SDRUtils/_swappulse_scripts/backfill_stir_ladder.py     CLI: project | marks | snapshot phases
tests/test_stir_ladder_conventions.py
tests/test_stir_ladder_projection.py
tests/test_stir_ladder_unwinds.py
tests/test_stir_ladder_state.py
tests/test_stir_ladder_book.py
tests/test_stir_ladder_backfill.py
```

---

### Task 1: Conventions module (signs, visibility, bucket keys)

**Files:**
- Create: `SDRUtils/stir_flow/ladder_conventions.py`
- Test: `tests/test_stir_ladder_conventions.py`

**Interfaces:**
- Produces (every later task imports these):
  - `VISIBILITY_BLOCK_DELAY_MIN = 15`, `VISIBILITY_DEFAULT_DELAY_MIN = 1`
  - `PROVISIONAL_HALF_LIVES_MIN = {"default": 90.0, "block": 240.0}`
  - `EPS_HALF_LIVES = 3.0`
  - `visibility_timestamp(execution_ts, is_block) -> pd.Timestamp` (tz-aware, exec + delay)
  - `dealer_leg_signs(kind: str, method: str, direction: str, n_legs: int) -> list[int]` (+1 = dealer received fixed on that leg)
  - `meeting_bucket_key(effective_date) -> str` (ISO date string)
  - `contract_month_key(effective_date) -> str` (`"2026-10"`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stir_ladder_conventions.py
import datetime
import pandas as pd
import pytest
from SDRUtils.stir_flow import ladder_conventions as lc


def test_visibility_rule():
    ts = pd.Timestamp("2026-07-10 19:41:45+00:00")
    assert lc.visibility_timestamp(ts, is_block=False) == ts + pd.Timedelta(minutes=1)
    assert lc.visibility_timestamp(ts, is_block=True) == ts + pd.Timedelta(minutes=15)


def test_dealer_leg_signs_outright():
    assert lc.dealer_leg_signs("OUTRIGHT", "RATE_VS_MID", "RECEIVED", 1) == [1]
    assert lc.dealer_leg_signs("OUTRIGHT", "RATE_VS_MID", "PAID", 1) == [-1]
    assert lc.dealer_leg_signs("OUTRIGHT", "TICK_RULE", "RECEIVED", 1) == [1]
    assert lc.dealer_leg_signs("OUTRIGHT", "NPV_VS_UPFRONT", "PAID", 1) == [-1]


def test_dealer_leg_signs_on_market_structures():
    # RECEIVED the spread = received back / paid front (legs sorted by maturity)
    assert lc.dealer_leg_signs("CURVE", "SPREAD_VS_MID", "RECEIVED", 2) == [-1, 1]
    assert lc.dealer_leg_signs("CURVE", "SPREAD_VS_MID", "PAID", 2) == [1, -1]
    # RECEIVED the fly = received belly / paid wings
    assert lc.dealer_leg_signs("FLY", "FLY_VS_MID", "RECEIVED", 3) == [-1, 1, -1]
    assert lc.dealer_leg_signs("FLY", "FLY_VS_MID", "PAID", 3) == [1, -1, 1]


def test_dealer_leg_signs_off_market_packages_same_frame():
    # NPV_VS_UPFRONT direction is the net-fixed frame: ALL legs share the sign
    assert lc.dealer_leg_signs("CURVE", "NPV_VS_UPFRONT", "RECEIVED", 2) == [1, 1]
    assert lc.dealer_leg_signs("FLY", "NPV_VS_UPFRONT", "PAID", 3) == [-1, -1, -1]
    assert lc.dealer_leg_signs("PKG", "NPV_VS_UPFRONT", "RECEIVED", 5) == [1] * 5


def test_dealer_leg_signs_rejects_unknown():
    with pytest.raises(ValueError):
        lc.dealer_leg_signs("CURVE", "SPREAD_VS_MID", "UNKNOWN", 2)


def test_bucket_keys():
    assert lc.meeting_bucket_key(datetime.date(2026, 10, 28)) == "2026-10-28"
    assert lc.meeting_bucket_key(pd.Timestamp("2026-10-28")) == "2026-10-28"
    assert lc.contract_month_key(datetime.date(2026, 10, 1)) == "2026-10"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_conventions.py -v`
Expected: FAIL with `ModuleNotFoundError` / attribute errors

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/ladder_conventions.py
"""Ladder sign/visibility/bucket conventions (ladder spec sections 4, 6, 8).

Persisted convention: delta_dv01 > 0  <=>  dealer long futures-equivalent
<=> dealer RECEIVED fixed. Off-market (NPV_VS_UPFRONT) directions are the
net-fixed frame from the classifier, so ALL legs carry the same sign; the
on-market spread/fly methods are true opposite-leg structures.
"""
from __future__ import annotations

import pandas as pd

VISIBILITY_BLOCK_DELAY_MIN = 15
VISIBILITY_DEFAULT_DELAY_MIN = 1
PROVISIONAL_HALF_LIVES_MIN = {"default": 90.0, "block": 240.0}  # Phase 4 recalibrates
EPS_HALF_LIVES = 3.0


def visibility_timestamp(execution_ts, is_block: bool) -> pd.Timestamp:
    delay = VISIBILITY_BLOCK_DELAY_MIN if is_block else VISIBILITY_DEFAULT_DELAY_MIN
    return pd.Timestamp(execution_ts) + pd.Timedelta(minutes=delay)


def dealer_leg_signs(kind: str, method: str, direction: str, n_legs: int) -> list:
    if direction not in ("PAID", "RECEIVED"):
        raise ValueError(f"cannot sign direction {direction!r}")
    recv = 1 if direction == "RECEIVED" else -1
    if method == "NPV_VS_UPFRONT":
        return [recv] * n_legs                       # net-fixed frame: same sign
    if kind == "OUTRIGHT":
        return [recv]
    if kind == "CURVE" and n_legs == 2:
        return [-recv, recv]                         # RECEIVED spread = recv back, pay front
    if kind == "FLY" and n_legs == 3:
        return [-recv, recv, -recv]                  # RECEIVED fly = recv belly, pay wings
    raise ValueError(f"unsupported structure {kind}/{method} with {n_legs} legs")


def meeting_bucket_key(effective_date) -> str:
    return pd.Timestamp(effective_date).date().isoformat()


def contract_month_key(effective_date) -> str:
    d = pd.Timestamp(effective_date)
    return f"{d.year:04d}-{d.month:02d}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_conventions.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/ladder_conventions.py tests/test_stir_ladder_conventions.py
git commit -m "feat(ladder): sign, visibility, and bucket-key conventions"
```

---

### Task 2: Schema module

**Files:**
- Create: `SDRUtils/_swappulse_scripts/_stir_ladder_schema_v1.py`
- Test: `tests/test_stir_ladder_backfill.py` (schema section)

**Interfaces:**
- Produces: `LADDER_PRINTS_TABLE = "arbs_stir_ladder_prints_v1"`, `BOOK_MARKS_TABLE = "arbs_stir_book_marks_v1"`, `DDL_STATEMENTS: list[str]`, `ensure_schema(conn) -> None` (all statements idempotent).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stir_ladder_backfill.py
from SDRUtils._swappulse_scripts import _stir_ladder_schema_v1 as schema


def test_ladder_schema_ddl_columns():
    ddl = "\n".join(schema.DDL_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_ladder_prints_v1" in ddl
    assert "CREATE TABLE IF NOT EXISTS arbs_stir_book_marks_v1" in ddl
    for col in (
        "unit_key", "bucket_space", "bucket_key", "delta_dv01",
        "visibility_timestamp", "p_flip", "direction_confidence",
        "curve_suspect_trade", "is_block", "dv01", "projected_at",
    ):
        assert col in ddl, col
    for col in ("mark_ts", "mark_kind", "npv_usd", "pnl_since_entry_usd", "curve_name"):
        assert col in ddl, col


def test_ladder_ensure_schema_executes_all():
    executed = []

    class FakeCursor:
        def execute(self, sql):
            executed.append(sql)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            executed.append("COMMIT")

    schema.ensure_schema(FakeConn())
    assert executed[-1] == "COMMIT"
    assert len(executed) == len(schema.DDL_STATEMENTS) + 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_backfill.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/_swappulse_scripts/_stir_ladder_schema_v1.py
"""DDL for the dealer positioning ladder tables (ladder spec sections 4-5)."""

LADDER_PRINTS_TABLE = "arbs_stir_ladder_prints_v1"
BOOK_MARKS_TABLE = "arbs_stir_book_marks_v1"

DDL_STATEMENTS = [
    f"""
CREATE TABLE IF NOT EXISTS {LADDER_PRINTS_TABLE} (
    unit_key              TEXT NOT NULL,
    bucket_space          TEXT NOT NULL,
    bucket_key            TEXT NOT NULL,
    delta_dv01            NUMERIC NOT NULL,
    as_of_date            DATE NOT NULL,
    execution_timestamp   TIMESTAMPTZ NOT NULL,
    visibility_timestamp  TIMESTAMPTZ NOT NULL,
    p_flip                NUMERIC,
    direction_confidence  TEXT,
    curve_suspect_trade   BOOLEAN DEFAULT FALSE,
    is_block              BOOLEAN DEFAULT FALSE,
    dv01                  NUMERIC,
    projected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unit_key, bucket_space, bucket_key)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_ladder_prints_vis ON {LADDER_PRINTS_TABLE} (bucket_space, bucket_key, visibility_timestamp)",
    f"CREATE INDEX IF NOT EXISTS idx_ladder_prints_asof ON {LADDER_PRINTS_TABLE} (as_of_date)",
    f"""
CREATE TABLE IF NOT EXISTS {BOOK_MARKS_TABLE} (
    unit_key              TEXT NOT NULL,
    mark_ts               TIMESTAMPTZ NOT NULL,
    mark_kind             TEXT NOT NULL,
    npv_usd               NUMERIC,
    pnl_since_entry_usd   NUMERIC,
    curve_name            TEXT,
    marked_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (unit_key, mark_ts)
)""",
    f"CREATE INDEX IF NOT EXISTS idx_book_marks_ts ON {BOOK_MARKS_TABLE} (mark_ts)",
    f"CREATE INDEX IF NOT EXISTS idx_book_marks_kind ON {BOOK_MARKS_TABLE} (mark_kind, mark_ts)",
]


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for stmt in DDL_STATEMENTS:
            cur.execute(stmt)
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_backfill.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/_stir_ladder_schema_v1.py tests/test_stir_ladder_backfill.py
git commit -m "feat(ladder): schema DDL for ladder prints + book marks"
```

---

### Task 3: Risk models and delta extraction

**Files:**
- Create: `SDRUtils/stir_flow/ladder.py` (part 1 of 2)
- Test: `tests/test_stir_ladder_projection.py`

**Interfaces:**
- Consumes: `build_delta_risk_ladder`, `build_basis_risk_ladder` from `MDP.IRSwaps.BARCHART_STIRF.risk`; `resolve_central_bank_tenor` from `Query.IRSwaps._CENTRAL_BANK_DATES`; `ladder_conventions` helpers; `stir_flow.config.CURVE_FOR`.
- Produces:
  - `RiskModel` dataclass: `space: str` (`MEETING`/`FUTURES`/`SERFF_BASIS`), `curve_handle`, `solver`, `label_to_bucket: dict[str, str]`.
  - `build_risk_models(curve_name, curve_handle, ts, stirf_mdp, include_basis: bool) -> list[RiskModel]`
  - `extract_bucket_deltas(delta_df, label_to_bucket, *, basis_prefix=None) -> dict[str, float]` — pure parser; sums the first numeric column of rows whose LAST index level matches a label; `basis_prefix="cvx_"` restricts to (or strips) prefixed labels.

- [ ] **Step 1: Write the failing pure test for the parser**

```python
# tests/test_stir_ladder_projection.py
import pandas as pd
import pytest
from SDRUtils.stir_flow.ladder import extract_bucket_deltas


def _fake_delta_df(rows):
    """Mimic rl.Portfolio.delta(solver) shape: MultiIndex (type, solver_id, label)."""
    idx = pd.MultiIndex.from_tuples(
        [("instruments", "RISK", label) for label, _ in rows],
        names=["type", "solver", "label"],
    )
    return pd.DataFrame({("usd", "usd"): [v for _, v in rows]}, index=idx)


def test_extract_bucket_deltas_maps_and_sums():
    df = _fake_delta_df([("SR3U26", 100.0), ("SR3Z26", -40.0), ("SR3H27", 0.5)])
    label_map = {"SR3U26": "SR3U26", "SR3Z26": "SR3Z26", "SR3H27": "SR3H27"}
    out = extract_bucket_deltas(df, label_map)
    assert out == {"SR3U26": 100.0, "SR3Z26": -40.0, "SR3H27": 0.5}


def test_extract_bucket_deltas_meeting_labels():
    df = _fake_delta_df([("fomc_1", 80.0), ("fomc_2", -20.0), ("ignored", 5.0)])
    label_map = {"fomc_1": "2026-07-29", "fomc_2": "2026-09-16"}
    out = extract_bucket_deltas(df, label_map)
    assert out == {"2026-07-29": 80.0, "2026-09-16": -20.0}


def test_extract_bucket_deltas_basis_prefix():
    df = _fake_delta_df([("SR1V26", 30.0), ("cvx_SR1V26", -7.0)])
    pure = extract_bucket_deltas(df, {"SR1V26": "2026-10"})
    basis = extract_bucket_deltas(df, {"SR1V26": "2026-10"}, basis_prefix="cvx_")
    assert pure == {"2026-10": 30.0}
    assert basis == {"2026-10": -7.0}


def test_extract_bucket_deltas_collapses_duplicate_buckets():
    df = _fake_delta_df([("a", 10.0), ("b", 15.0)])
    out = extract_bucket_deltas(df, {"a": "2026-10-28", "b": "2026-10-28"})
    assert out == {"2026-10-28": 25.0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_projection.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write the implementation (ladder.py part 1)**

```python
# SDRUtils/stir_flow/ladder.py
"""Layer 1: project classified prints onto delta risk ladders (ladder spec section 4)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow import ladder_conventions as conv

N_MEETINGS = 12
N_SFR = 12
N_BASIS_MONTHS = 12
MEETING_TENORS = [f"fomc_{i}" for i in range(1, N_MEETINGS + 1)]
# Sign flip: rateslib delta is dNPV per +1bp instrument-rate bump; a received-fixed
# (long futures-equivalent) book LOSES on higher rates, so persisted convention
# (+ = dealer long futures-equiv) requires one flip. Golden test is the arbiter.
RL_DELTA_TO_FUTURES_EQ = -1.0


@dataclasses.dataclass
class RiskModel:
    space: str                     # MEETING | FUTURES | SERFF_BASIS
    curve_handle: object
    solver: object
    label_to_bucket: dict


def extract_bucket_deltas(delta_df, label_to_bucket, *, basis_prefix=None) -> dict:
    out: dict = {}
    for idx, row in delta_df.iterrows():
        label = idx[-1] if isinstance(idx, tuple) else idx
        if basis_prefix is not None:
            if not str(label).startswith(basis_prefix):
                continue
            label = str(label)[len(basis_prefix):]
        elif str(label).startswith("cvx_"):
            continue
        if label not in label_to_bucket:
            continue
        bucket = label_to_bucket[label]
        out[bucket] = out.get(bucket, 0.0) + float(row.iloc[0])
    return out


def build_risk_models(curve_name, curve_handle, ts, stirf_mdp, include_basis: bool) -> list:
    from MDP.IRSwaps.BARCHART_STIRF.risk import (
        build_basis_risk_ladder, build_delta_risk_ladder,
    )
    from Query.IRSwaps._CENTRAL_BANK_DATES import resolve_central_bank_tenor
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery

    models = []

    # MEETING space: fomc_1..12 tenor strings; bucket = absolute meeting eff date
    as_of = pd.Timestamp(ts).date()
    meeting_map = {}
    for tok in MEETING_TENORS:
        dates = resolve_central_bank_tenor(curve_handle.id(), tok, as_of=as_of)
        if dates is None:
            continue
        meeting_map[tok] = conv.meeting_bucket_key(dates[0])
    m_curve, m_solver = build_delta_risk_ladder(list(meeting_map.keys()), curve_handle)
    models.append(RiskModel("MEETING", m_curve, m_solver, meeting_map))

    # FUTURES space: SFRCM1..12; bucket = absolute contract id (solver labels ARE ids)
    sfr_queries = [STIRFutureQuery(symbol=f"SFRCM{i}") for i in range(1, N_SFR + 1)]
    f_curve, f_solver = build_delta_risk_ladder(
        sfr_queries, curve_handle, stirf_mdp_handle=stirf_mdp, timestamp=ts
    )
    fut_labels = list(f_solver.instrument_labels) if hasattr(f_solver, "instrument_labels") else []
    if not fut_labels:
        fut_labels = [lbl for lbl in getattr(f_solver, "s", [])]  # defensive; golden verifies
    fut_map = {lbl: lbl for lbl in fut_labels if isinstance(lbl, str)}
    models.append(RiskModel("FUTURES", f_curve, f_solver, fut_map))

    # SERFF basis split (FED_FUNDS prints only)
    if include_basis:
        b_curve, b_solver, _stir_solver = build_basis_risk_ladder(
            [str(i) for i in range(1, N_BASIS_MONTHS + 1)],
            curve_handle, stirf_mdp_handle=stirf_mdp, timestamp=ts,
        )
        # labels: SER contract ids (pure) and cvx_<id> (basis); bucket = contract month
        basis_map = {}
        for lbl in getattr(b_solver, "instrument_labels", []):
            raw = str(lbl)
            base = raw[4:] if raw.startswith("cvx_") else raw
            basis_map[base] = base  # month key resolved at extraction time via pricer dates
        models.append(RiskModel("SERFF_BASIS", b_curve, b_solver, basis_map))

    return models
```

Note: `instrument_labels` availability/shape on `rl.Solver` differs across rateslib versions — the network golden in Step 5 is the arbiter; adjust the label-harvest lines to whatever the installed rateslib exposes (e.g. `solver.instrument_labels` tuple) so the golden passes. `label_to_bucket` for SERFF months may equivalently be built from the SER pricers' effective dates via `conv.contract_month_key` — do that if solver labels turn out not to carry month info.

- [ ] **Step 4: Run pure tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_projection.py -v`
Expected: 4 PASS

- [ ] **Step 5: Add the network golden for risk-model construction**

Append to `tests/test_stir_ladder_projection.py`:

```python
@pytest.mark.network
@pytest.mark.slow
def test_build_risk_models_golden():
    import datetime
    import pytz
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from SDRUtils.stir_flow.ladder import build_risk_models

    NY = pytz.timezone("America/New_York")
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    stirf = STIRFutureMDP(source="BARCHART_STIRF-RL")
    h = mdp._get_curve(curve_name="USD-OIS-Q12xM12STIRT-SERFFX-MIX23", timestamp=ts)
    models = build_risk_models("USD-OIS-Q12xM12STIRT-SERFFX-MIX23", h, ts, stirf, include_basis=True)
    spaces = {m.space for m in models}
    assert spaces == {"MEETING", "FUTURES", "SERFF_BASIS"}
    meeting = next(m for m in models if m.space == "MEETING")
    assert len(meeting.label_to_bucket) >= 10          # ~12 upcoming meetings resolved
    assert meeting.label_to_bucket["fomc_1"] == "2026-07-29"
    futures = next(m for m in models if m.space == "FUTURES")
    assert len(futures.label_to_bucket) == 12
```

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_projection.py -m network -v`
Expected: 1 PASS (fix label harvesting per the installed rateslib if the futures map is empty)

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/stir_flow/ladder.py tests/test_stir_ladder_projection.py
git commit -m "feat(ladder): risk-model construction and delta extraction"
```

---

### Task 4: project_unit and ladder-row writer

**Files:**
- Modify: `SDRUtils/stir_flow/ladder.py` (append part 2)
- Modify: `tests/test_stir_ladder_projection.py` (append)

**Interfaces:**
- Consumes: `RiskModel`, `extract_bucket_deltas`, `conv.dealer_leg_signs`, `conv.visibility_timestamp`, `stir_flow.pricing.CurvePricer` (`price_leg(curve_name, ts, eff, mat, notional, fixed_rate) -> LegPricing`), `stir_flow.trade_selection.Unit`.
- Produces:
  - `project_unit(unit, direction_row: dict, risk_models: list[RiskModel], pricer, curve_name, snap_ts) -> tuple[list[dict], dict]` — (ladder rows for `arbs_stir_ladder_prints_v1`, one ENTRY mark row for `arbs_stir_book_marks_v1`).
  - `dealer_signed_packages(unit, direction_row, curve_handle, snap_ts) -> list` — rl instrument list, one per leg, notional signed so the portfolio IS the dealer's position (payer legs positive rl notional).
  - `LADDER_COLUMNS: list[str]` — insert column order for the prints table.

- [ ] **Step 1: Write the failing tests (fakes; golden numbers from classifier POC)**

```python
# append to tests/test_stir_ladder_projection.py
import datetime

import pandas as pd

from SDRUtils.stir_flow.ladder import LADDER_COLUMNS, project_unit, RiskModel
from SDRUtils.stir_flow.trade_selection import Unit


def _direction_row(**kw):
    base = dict(
        unit_key="4137861837000000101", trade_type="OUTRIGHT",
        classification_method="NPV_VS_UPFRONT", dealer_direction="PAID",
        rate_index_clean="FED_FUNDS", p_flip=0.2, direction_confidence="LOW",
        curve_suspect_trade=False, structure_dv01=50001.0,
    )
    base.update(kw)
    return base


def _unit():
    legs = pd.DataFrame([dict(
        trade_id="4137861837000000101", package_id=None,
        as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        original_execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        effective_date=datetime.date(2026, 7, 29),
        expiration_date=datetime.date(2026, 9, 16),
        notional=3.7e9, fixed_rate=0.03713, is_block=False, risk=50001.0,
    )])
    return Unit("4137861837000000101", "OUTRIGHT", legs, None, True)


class FakeVmapModel:
    """RiskModel whose solver/curve are ignored by the fake projector below."""


def test_project_unit_rows_and_entry_mark(monkeypatch):
    import SDRUtils.stir_flow.ladder as ladder_mod

    # fake the two pricer-touching internals; test the orchestration + conventions
    monkeypatch.setattr(
        ladder_mod, "_project_onto_model",
        lambda pkgs, model: {"2026-07-29": -50001.0} if model.space == "MEETING"
        else {"SR3U26": -30000.0, "SR3Z26": -20001.0},
    )

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            from SDRUtils.stir_flow.pricing import LegPricing
            return LegPricing(3.717511, 22554.95, 50001.0)

    models = [
        RiskModel("MEETING", None, None, {"fomc_1": "2026-07-29"}),
        RiskModel("FUTURES", None, None, {"SR3U26": "SR3U26", "SR3Z26": "SR3Z26"}),
    ]
    rows, entry = project_unit(
        _unit(), _direction_row(), models, FakePricer(),
        "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
        pd.Timestamp("2026-07-10 15:40:00-04:00"),
    )
    by_space = {(r["bucket_space"], r["bucket_key"]): r for r in rows}
    # dealer PAID -> short futures-equivalent -> negative delta
    assert by_space[("MEETING", "2026-07-29")]["delta_dv01"] == -50001.0
    assert set(r["bucket_space"] for r in rows) == {"MEETING", "FUTURES"}
    r0 = rows[0]
    assert r0["visibility_timestamp"] == pd.Timestamp("2026-07-10 19:42:45+00:00")
    assert r0["p_flip"] == 0.2 and r0["is_block"] is False
    assert set(LADDER_COLUMNS) <= set(r0.keys())
    # ENTRY mark: dealer PAID -> dealer npv = +npv_pay = +22,554.95
    assert entry["mark_kind"] == "ENTRY"
    assert abs(entry["npv_usd"] - 22554.95) < 0.01
    assert entry["pnl_since_entry_usd"] == 0.0


def test_project_unit_block_visibility(monkeypatch):
    import SDRUtils.stir_flow.ladder as ladder_mod
    monkeypatch.setattr(ladder_mod, "_project_onto_model", lambda p, m: {"2026-07-29": 1.0})

    class FakePricer:
        def price_leg(self, *a, **k):
            from SDRUtils.stir_flow.pricing import LegPricing
            return LegPricing(3.7, 0.0, 1.0)

    u = _unit()
    u.legs.loc[0, "is_block"] = True
    rows, _ = project_unit(
        u, _direction_row(), [RiskModel("MEETING", None, None, {"fomc_1": "2026-07-29"})],
        FakePricer(), "USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
        pd.Timestamp("2026-07-10 15:40:00-04:00"),
    )
    assert rows[0]["visibility_timestamp"] == pd.Timestamp("2026-07-10 19:56:45+00:00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_projection.py -v -k project_unit`
Expected: FAIL (names not defined)

- [ ] **Step 3: Write the implementation (append to ladder.py)**

```python
LADDER_COLUMNS = [
    "unit_key", "bucket_space", "bucket_key", "delta_dv01", "as_of_date",
    "execution_timestamp", "visibility_timestamp", "p_flip",
    "direction_confidence", "curve_suspect_trade", "is_block", "dv01",
]


def dealer_signed_packages(unit, direction_row, curve_handle, snap_ts):
    """Build the dealer's position as rl instruments on the given curve handle.

    Rateslib positive notional = pay fixed. Dealer sign +1 (received) -> rl
    notional negative. Returns list of rl instruments (one per leg).
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery

    from SDRUtils.stir_flow.ladder_conventions import dealer_leg_signs

    signs = dealer_leg_signs(
        unit.kind, direction_row["classification_method"],
        direction_row["dealer_direction"], len(unit.legs),
    )
    pkgs = []
    for (_, leg), sign in zip(unit.legs.iterrows(), signs):
        rl_notional = -sign * float(leg["notional"])   # +1 received -> negative (receiver)
        q = IRSwapQuery(
            curve=curve_handle._meta_data.get("requested_curve_name"),
            effective_date=pd.Timestamp(leg["effective_date"]).date(),
            maturity_date=pd.Timestamp(leg["expiration_date"]).date(),
            structure_kwargs={"notional": rl_notional, "fixed_rate": float(leg["fixed_rate"])},
        ).resolve_query(snap_ts, pricer_or_curve=curve_handle)
        pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
        pkgs.extend(pkg)
    return pkgs


def _project_onto_model(pkgs, model: RiskModel) -> dict:
    import rateslib as rl
    delta_df = rl.Portfolio(pkgs).delta(solver=model.solver)
    if model.space == "SERFF_BASIS":
        pure = extract_bucket_deltas(delta_df, model.label_to_bucket)
        basis = extract_bucket_deltas(delta_df, model.label_to_bucket, basis_prefix="cvx_")
        out = {("SERFF_BASIS_SOFR", k): v for k, v in pure.items()}
        out.update({("SERFF_BASIS_SPREAD", k): v for k, v in basis.items()})
        return out
    return extract_bucket_deltas(delta_df, model.label_to_bucket)


def project_unit(unit, direction_row, risk_models, pricer, curve_name, snap_ts):
    from SDRUtils.stir_flow import ladder_conventions as _conv

    first = unit.legs.iloc[0]
    vis = _conv.visibility_timestamp(first["execution_timestamp"], bool(first.get("is_block")))
    meta = dict(
        unit_key=direction_row["unit_key"],
        as_of_date=first["as_of_date"],
        execution_timestamp=first["execution_timestamp"],
        visibility_timestamp=vis,
        p_flip=direction_row.get("p_flip"),
        direction_confidence=direction_row.get("direction_confidence"),
        curve_suspect_trade=bool(direction_row.get("curve_suspect_trade")),
        is_block=bool(first.get("is_block")),
        dv01=direction_row.get("structure_dv01"),
    )

    rows = []
    for model in risk_models:
        pkgs = None
        if model.curve_handle is not None:
            pkgs = dealer_signed_packages(unit, direction_row, model.curve_handle, snap_ts)
        deltas = _project_onto_model(pkgs, model)
        for key, val in deltas.items():
            space, bucket = key if isinstance(key, tuple) else (model.space, key)
            rows.append(dict(meta, bucket_space=space, bucket_key=bucket,
                             delta_dv01=RL_DELTA_TO_FUTURES_EQ * float(val)
                             if model.curve_handle is not None else float(val)))

    # ENTRY mark: dealer-signed NPV at the projection snapshot
    signs = _conv.dealer_leg_signs(
        unit.kind, direction_row["classification_method"],
        direction_row["dealer_direction"], len(unit.legs),
    )
    npv = 0.0
    for (_, leg), sign in zip(unit.legs.iterrows(), signs):
        lp = pricer.price_leg(curve_name, snap_ts, leg["effective_date"],
                              leg["expiration_date"], notional=float(leg["notional"]),
                              fixed_rate=float(leg["fixed_rate"]))
        npv += -sign * lp.npv_pay          # received (+1) -> value = -npv_pay
    entry = dict(unit_key=direction_row["unit_key"], mark_ts=snap_ts,
                 mark_kind="ENTRY", npv_usd=npv, pnl_since_entry_usd=0.0,
                 curve_name=curve_name)
    return rows, entry
```

Note the fake in Step 1 bypasses `dealer_signed_packages` (curve_handle=None ⇒ `_project_onto_model` is monkeypatched), so the sign flip inside `_project_onto_model` paths is exercised only by the golden below — the fake supplies already-signed deltas. Keep the `RL_DELTA_TO_FUTURES_EQ` application inside `project_unit` for the real path exactly as written; the golden is the arbiter.

- [ ] **Step 4: Run tests, then the golden**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_projection.py -v -k "project_unit"`
Expected: 2 PASS

Append and run the sign-arbiter golden:

```python
@pytest.mark.network
@pytest.mark.slow
def test_project_unit_golden_sign_and_magnitude():
    """FF FOMC JUL26 outright, dealer PAID, DV01 ~50K (classifier golden print).
    Persisted convention: PAID -> delta_dv01 NEGATIVE, |sum| ~ structure DV01."""
    import datetime
    import pytz
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
    from SDRUtils.stir_flow.ladder import build_risk_models, project_unit
    from SDRUtils.stir_flow.pricing import CurvePricer

    NY = pytz.timezone("America/New_York")
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    curve_name = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    stirf = STIRFutureMDP(source="BARCHART_STIRF-RL")
    h = mdp._get_curve(curve_name=curve_name, timestamp=ts)
    models = [m for m in build_risk_models(curve_name, h, ts, stirf, include_basis=False)]
    rows, entry = project_unit(_unit(), _direction_row(), models, CurvePricer(mdp=mdp),
                               curve_name, ts)
    meeting = {r["bucket_key"]: r["delta_dv01"] for r in rows if r["bucket_space"] == "MEETING"}
    total = sum(meeting.values())
    assert total < 0, f"PAID must be negative futures-equivalent, got {total}"
    assert abs(abs(total) - 50001) < 2500          # ~ structure DV01
    assert abs(meeting.get("2026-07-29", 0.0)) > 0.9 * abs(total)  # concentrated in JUL26
    assert abs(entry["npv_usd"] - 22554.95) < 250
```

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_projection.py -m network -v`
Expected: 2 PASS. **If the sign assertion fails, flip `RL_DELTA_TO_FUTURES_EQ` to `+1.0` — this constant is the single designated arbiter point; do not touch `dealer_leg_signs`.**

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/ladder.py tests/test_stir_ladder_projection.py
git commit -m "feat(ladder): per-print projection with dealer signing and entry marks"
```

---

### Task 5: Unwind linkage extraction

**Files:**
- Create: `SDRUtils/stir_flow/unwinds.py`
- Test: `tests/test_stir_ladder_unwinds.py`

**Interfaces:**
- Consumes: tape tables (read-only), `conv.visibility_timestamp`.
- Produces: `extract_unwind_events(conn, start_date, end_date, classified_unit_keys: set[str]) -> pd.DataFrame` with columns `[unit_key, unwind_visibility_ts]` — one row per classified print that was lifecycle-terminated in the window. Returns an EMPTY df (correct columns) when no lineage column exists; ladder netting is then a no-op. Also `LINEAGE_CANDIDATES: tuple[str, ...]`.

- [ ] **Step 1: Inspection script (run once, record findings in the module docstring)**

Write and run `C:\Users\chris\AppData\Local\Temp\claude\ladder_lineage_probe.py` (scratch, not committed):

```python
import sys
sys.path.insert(0, r"C:\Users\chris\clee\ARBS")
import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

conn = psycopg2.connect(resolve_pg_url())
cols = pd.read_sql(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name = 'arbs_usd_swap_tape_legs_v2'", conn)
print([c for c in cols["column_name"]
       if any(k in c for k in ("dissem", "prior", "original", "uti", "usi", "lineage"))])
sample = pd.read_sql(
    "SELECT * FROM arbs_usd_swap_tape_legs_v2 "
    "WHERE economic_class = 'ECONOMIC_UNWIND' AND as_of_date = '2026-07-10' LIMIT 3", conn)
print(sample.columns.tolist())
conn.close()
```

Run: `conda run -n stir python C:\Users\chris\AppData\Local\Temp\claude\ladder_lineage_probe.py`
Record which lineage columns exist (expected candidates: `original_dissemination_identifier`, `prior_uti`, or none beyond `original_execution_timestamp`).

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_stir_ladder_unwinds.py
import pandas as pd
from SDRUtils.stir_flow.unwinds import _match_unwinds_frame


def test_match_unwinds_direct_lineage():
    unwind_rows = pd.DataFrame([
        dict(trade_id="U1", lineage_ref="T1", execution_timestamp=pd.Timestamp("2026-07-11 14:00:00+00:00"), is_block=False),
        dict(trade_id="U2", lineage_ref="NOT_CLASSIFIED", execution_timestamp=pd.Timestamp("2026-07-11 15:00:00+00:00"), is_block=False),
    ])
    out = _match_unwinds_frame(unwind_rows, {"T1", "T9"}, lineage_col="lineage_ref")
    assert list(out["unit_key"]) == ["T1"]
    assert out.iloc[0]["unwind_visibility_ts"] == pd.Timestamp("2026-07-11 14:01:00+00:00")


def test_match_unwinds_block_delay_and_empty():
    unwind_rows = pd.DataFrame([
        dict(trade_id="U1", lineage_ref="T1", execution_timestamp=pd.Timestamp("2026-07-11 14:00:00+00:00"), is_block=True),
    ])
    out = _match_unwinds_frame(unwind_rows, {"T1"}, lineage_col="lineage_ref")
    assert out.iloc[0]["unwind_visibility_ts"] == pd.Timestamp("2026-07-11 14:15:00+00:00")
    empty = _match_unwinds_frame(unwind_rows.head(0), {"T1"}, lineage_col="lineage_ref")
    assert list(empty.columns) == ["unit_key", "unwind_visibility_ts"] and empty.empty
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_unwinds.py -v`
Expected: FAIL with import error

- [ ] **Step 4: Write the implementation**

```python
# SDRUtils/stir_flow/unwinds.py
"""Lifecycle-linked unwind extraction for ladder netting (ladder spec section 3b/6).

Netting applies ONLY to unwind events whose lineage resolves to an
already-classified print. Generic opposite-direction prints are new flow.
Findings from the lineage probe (Task 5 Step 1): <record columns found here>.
If no lineage column exists in the tape, extract_unwind_events returns an
empty frame and netting is a documented no-op pending a tape lineage column.
"""
from __future__ import annotations

import pandas as pd

from SDRUtils.stir_flow import ladder_conventions as conv

LINEAGE_CANDIDATES = ("original_dissemination_identifier", "prior_uti", "prior_usi")
_EMPTY = pd.DataFrame(columns=["unit_key", "unwind_visibility_ts"])


def _match_unwinds_frame(unwind_rows: pd.DataFrame, classified: set, *, lineage_col: str) -> pd.DataFrame:
    if unwind_rows.empty:
        return _EMPTY.copy()
    hits = unwind_rows[unwind_rows[lineage_col].isin(classified)]
    if hits.empty:
        return _EMPTY.copy()
    return pd.DataFrame({
        "unit_key": hits[lineage_col].values,
        "unwind_visibility_ts": [
            conv.visibility_timestamp(ts, bool(b))
            for ts, b in zip(hits["execution_timestamp"], hits["is_block"].fillna(False))
        ],
    })


def extract_unwind_events(conn, start_date, end_date, classified_unit_keys: set) -> pd.DataFrame:
    cols = pd.read_sql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'arbs_usd_swap_tape_legs_v2'", conn,
    )["column_name"].tolist()
    lineage_col = next((c for c in LINEAGE_CANDIDATES if c in cols), None)
    if lineage_col is None:
        return _EMPTY.copy()
    rows = pd.read_sql(
        f"SELECT trade_id, {lineage_col}, execution_timestamp, is_block "
        "FROM arbs_usd_swap_tape_legs_v2 "
        "WHERE economic_class = 'ECONOMIC_UNWIND' AND as_of_date BETWEEN %(s)s AND %(e)s",
        conn, params={"s": start_date, "e": end_date},
    )
    return _match_unwinds_frame(rows, classified_unit_keys, lineage_col=lineage_col)
```

- [ ] **Step 5: Run tests, fill the docstring findings from Step 1, commit**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_unwinds.py -v`
Expected: 2 PASS. Replace `<record columns found here>` with the probe's actual output before committing.

```bash
git add SDRUtils/stir_flow/unwinds.py tests/test_stir_ladder_unwinds.py
git commit -m "feat(ladder): lifecycle-linked unwind extraction with graceful degradation"
```

---

### Task 6: Layer 3 — ladder state (pure query)

**Files:**
- Create: `SDRUtils/stir_flow/ladder_state.py`
- Test: `tests/test_stir_ladder_state.py`

**Interfaces:**
- Consumes: prints DataFrame with `LADDER_COLUMNS`; unwinds DataFrame from Task 5; `conv.PROVISIONAL_HALF_LIVES_MIN`.
- Produces:
  - `ladder_at(prints, ts, *, space="MEETING", half_lives=None, weighting="expected", include_suspect=False, unwinds=None) -> pd.Series` (index bucket_key, values decayed dealer DV01).
  - `ladder_grid(prints, timestamps, **kw) -> pd.DataFrame` (index ts, columns bucket_key).
  - `print_weights(prints, ts, half_lives) -> pd.Series` — exposed for book.py (open-position weights).
  - `weighting`: `"expected"` = `(1 − 2·p_flip)` (NaN p_flip → 1.0), `"unweighted"` = 1.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stir_ladder_state.py
import numpy as np
import pandas as pd
import pytest
from SDRUtils.stir_flow.ladder_state import ladder_at, ladder_grid, print_weights

TS0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
HL = {"default": 90.0, "block": 240.0}


def _print(unit="T1", bucket="2026-07-29", dv=100.0, vis=TS0, p_flip=0.0,
           suspect=False, block=False, space="MEETING"):
    return dict(unit_key=unit, bucket_space=space, bucket_key=bucket, delta_dv01=dv,
                visibility_timestamp=vis, p_flip=p_flip,
                curve_suspect_trade=suspect, is_block=block)


def test_no_lookahead_print_invisible_before_visibility():
    df = pd.DataFrame([_print(vis=TS0)])
    before = ladder_at(df, TS0 - pd.Timedelta(seconds=1), half_lives=HL)
    at = ladder_at(df, TS0, half_lives=HL)
    assert before.empty or before.get("2026-07-29", 0.0) == 0.0
    assert at["2026-07-29"] == pytest.approx(100.0)


def test_ewma_halves_at_half_life_and_block_hl():
    df = pd.DataFrame([_print(), _print(unit="B1", bucket="2026-09-16", block=True)])
    at_90 = ladder_at(df, TS0 + pd.Timedelta(minutes=90), half_lives=HL)
    assert at_90["2026-07-29"] == pytest.approx(50.0, rel=1e-6)
    assert at_90["2026-09-16"] == pytest.approx(100.0 * 0.5 ** (90.0 / 240.0), rel=1e-6)


def test_expected_weighting_and_suspect_exclusion():
    df = pd.DataFrame([
        _print(unit="A", dv=100.0, p_flip=0.25),           # weight 0.5
        _print(unit="S", dv=999.0, suspect=True),           # excluded by default
    ])
    lad = ladder_at(df, TS0, half_lives=HL)
    assert lad["2026-07-29"] == pytest.approx(50.0)
    lad_inc = ladder_at(df, TS0, half_lives=HL, include_suspect=True)
    assert lad_inc["2026-07-29"] == pytest.approx(50.0 + 999.0)
    lad_unw = ladder_at(df, TS0, half_lives=HL, weighting="unweighted")
    assert lad_unw["2026-07-29"] == pytest.approx(100.0)


def test_unwind_netting_zeroes_from_unwind_visibility():
    df = pd.DataFrame([_print(unit="T1", dv=100.0)])
    unw = pd.DataFrame([dict(unit_key="T1",
                             unwind_visibility_ts=TS0 + pd.Timedelta(minutes=30))])
    before = ladder_at(df, TS0 + pd.Timedelta(minutes=29), half_lives=HL, unwinds=unw)
    after = ladder_at(df, TS0 + pd.Timedelta(minutes=31), half_lives=HL, unwinds=unw)
    assert before["2026-07-29"] > 0
    assert after.get("2026-07-29", 0.0) == 0.0


def test_space_filter_and_grid():
    df = pd.DataFrame([
        _print(),
        _print(unit="F1", bucket="SR3U26", space="FUTURES"),
    ])
    fut = ladder_at(df, TS0, space="FUTURES", half_lives=HL)
    assert list(fut.index) == ["SR3U26"]
    grid = ladder_grid(df, [TS0, TS0 + pd.Timedelta(minutes=90)], half_lives=HL)
    assert grid.loc[TS0, "2026-07-29"] == pytest.approx(100.0)
    assert grid.iloc[1]["2026-07-29"] == pytest.approx(50.0)


def test_print_weights_for_book():
    df = pd.DataFrame([_print()])
    w = print_weights(df, TS0 + pd.Timedelta(minutes=90), HL)
    assert w["T1"] == pytest.approx(0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_state.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/ladder_state.py
"""Layer 3: the ladder as a pure read-time transform (ladder spec section 6).

No pricing here — decay, weighting, netting, and views over persisted
per-print projection vectors. Every parameter is an argument.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from SDRUtils.stir_flow import ladder_conventions as conv


def _decay(prints: pd.DataFrame, ts, half_lives) -> pd.Series:
    hl = pd.Series(
        np.where(prints["is_block"].fillna(False), half_lives["block"], half_lives["default"]),
        index=prints.index, dtype=float,
    )
    age_min = (pd.Timestamp(ts) - pd.to_datetime(prints["visibility_timestamp"])).dt.total_seconds() / 60.0
    w = np.power(0.5, age_min / hl)
    w[age_min < 0] = 0.0                      # no-lookahead: invisible prints weigh 0
    return pd.Series(w, index=prints.index)


def _weight(prints: pd.DataFrame, weighting: str) -> pd.Series:
    if weighting == "unweighted":
        return pd.Series(1.0, index=prints.index)
    if weighting == "expected":
        return (1.0 - 2.0 * prints["p_flip"].astype(float)).fillna(1.0)
    raise ValueError(f"unknown weighting {weighting!r}")


def _apply_filters(prints, space, include_suspect, unwinds, ts):
    df = prints[prints["bucket_space"] == space]
    if not include_suspect:
        df = df[~df["curve_suspect_trade"].fillna(False).astype(bool)]
    if unwinds is not None and len(unwinds):
        dead = unwinds[pd.to_datetime(unwinds["unwind_visibility_ts"]) <= pd.Timestamp(ts)]
        df = df[~df["unit_key"].isin(set(dead["unit_key"]))]
    return df


def ladder_at(prints, ts, *, space="MEETING", half_lives=None, weighting="expected",
              include_suspect=False, unwinds=None) -> pd.Series:
    half_lives = half_lives or conv.PROVISIONAL_HALF_LIVES_MIN
    df = _apply_filters(prints, space, include_suspect, unwinds, ts)
    if df.empty:
        return pd.Series(dtype=float)
    contrib = df["delta_dv01"].astype(float) * _decay(df, ts, half_lives) * _weight(df, weighting)
    out = contrib.groupby(df["bucket_key"]).sum()
    return out[out != 0.0].sort_index()


def ladder_grid(prints, timestamps, **kw) -> pd.DataFrame:
    rows = {pd.Timestamp(t): ladder_at(prints, t, **kw) for t in timestamps}
    return pd.DataFrame(rows).T.fillna(0.0)


def print_weights(prints, ts, half_lives) -> pd.Series:
    per_unit = prints.drop_duplicates("unit_key").set_index("unit_key")
    return _decay(per_unit, ts, half_lives)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_state.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/ladder_state.py tests/test_stir_ladder_state.py
git commit -m "feat(ladder): pure-query ladder state with EWMA, netting, no-lookahead"
```

---

### Task 7: Layer 2 — book MTM and intraday snapshots

**Files:**
- Create: `SDRUtils/stir_flow/book.py`
- Test: `tests/test_stir_ladder_book.py`

**Interfaces:**
- Consumes: `CurvePricer.price_leg`, `conv.dealer_leg_signs`, `conv.EPS_HALF_LIVES`, `ladder_state.print_weights`, `ladder_state.ladder_at`, `stir_flow.config.CURVE_FOR`.
- Produces:
  - `snap_mtm(ts) -> tz-aware datetime` — floor to minute, NO minus-1.
  - `reval_unit(legs_df, signs, pricer, curve_name, ts) -> float` — dealer-signed NPV = Σ −sign·npv_pay.
  - `open_positions(prints_meta, unwinds, ts, half_lives, eps_half_lives=3.0) -> pd.DataFrame`.
  - `book_snapshot(units_by_key, direction_rows, prints, unwinds, pricer, ts, *, half_lives=None, weighting="expected", include_suspect=False) -> BookSnapshot` where `BookSnapshot` has `ts`, `ladders: dict[str, pd.Series]`, `per_unit: pd.DataFrame` (unit_key, npv_usd, entry_npv_usd, pnl_usd, weight), `gross_pnl_usd: float`, `residual_pnl_usd: float`.
  - `eod_mark_rows(units_by_key, direction_rows, entry_marks, pricer, mark_date) -> list[dict]` — rows for `arbs_stir_book_marks_v1` with `mark_kind='EOD'`, `mark_ts` = 17:00 ET.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stir_ladder_book.py
import datetime
import pandas as pd
import pytest
import pytz
from SDRUtils.stir_flow import book
from SDRUtils.stir_flow.pricing import LegPricing

NY = pytz.timezone("America/New_York")


def test_snap_mtm_floors_without_minus_one():
    ts = NY.localize(datetime.datetime(2026, 7, 14, 8, 29, 45))
    assert book.snap_mtm(ts) == NY.localize(datetime.datetime(2026, 7, 14, 8, 29))


def test_reval_unit_dealer_signed():
    legs = pd.DataFrame([
        dict(effective_date=datetime.date(2026, 7, 29),
             expiration_date=datetime.date(2026, 9, 16),
             notional=3.7e9, fixed_rate=0.03713),
    ])

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            return LegPricing(3.7175, 22554.95, 50001.0)

    # dealer PAID (sign -1): dealer npv = +npv_pay
    v = book.reval_unit(legs, [-1], FakePricer(), "C", None)
    assert v == pytest.approx(22554.95)
    # dealer RECEIVED (+1): dealer npv = -npv_pay
    assert book.reval_unit(legs, [1], FakePricer(), "C", None) == pytest.approx(-22554.95)


def test_open_positions_eps_cutoff_and_unwinds():
    ts0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
    prints = pd.DataFrame([
        dict(unit_key="FRESH", bucket_space="MEETING", bucket_key="x", delta_dv01=1.0,
             visibility_timestamp=ts0, p_flip=0.0, curve_suspect_trade=False, is_block=False),
        dict(unit_key="STALE", bucket_space="MEETING", bucket_key="x", delta_dv01=1.0,
             visibility_timestamp=ts0 - pd.Timedelta(minutes=90 * 4), p_flip=0.0,
             curve_suspect_trade=False, is_block=False),
        dict(unit_key="DEAD", bucket_space="MEETING", bucket_key="x", delta_dv01=1.0,
             visibility_timestamp=ts0, p_flip=0.0, curve_suspect_trade=False, is_block=False),
    ])
    unw = pd.DataFrame([dict(unit_key="DEAD", unwind_visibility_ts=ts0 + pd.Timedelta(minutes=1))])
    hl = {"default": 90.0, "block": 240.0}
    open_df = book.open_positions(prints, unw, ts0 + pd.Timedelta(minutes=10), hl)
    assert set(open_df["unit_key"]) == {"FRESH"}     # STALE beyond 3 half-lives, DEAD unwound


def test_book_snapshot_gross_and_residual():
    ts0 = pd.Timestamp("2026-07-10 14:00:00+00:00")
    legs = pd.DataFrame([
        dict(effective_date=datetime.date(2026, 7, 29),
             expiration_date=datetime.date(2026, 9, 16),
             notional=1e9, fixed_rate=0.037),
    ])

    class FakeUnit:
        kind = "OUTRIGHT"
        def __init__(self):
            self.legs = legs

    units = {"T1": FakeUnit()}
    directions = {"T1": dict(unit_key="T1", classification_method="RATE_VS_MID",
                             dealer_direction="PAID", rate_index_clean="FED_FUNDS")}
    prints = pd.DataFrame([
        dict(unit_key="T1", bucket_space="MEETING", bucket_key="2026-07-29",
             delta_dv01=-50000.0, visibility_timestamp=ts0, p_flip=0.0,
             curve_suspect_trade=False, is_block=False),
    ])
    entry_marks = {"T1": 10_000.0}

    class FakePricer:
        def price_leg(self, curve_name, ts, eff, mat, notional, fixed_rate=None):
            return LegPricing(3.71, 25_000.0, 50_000.0)   # npv_pay now 25K

    snap = book.book_snapshot(units, directions, prints, None, FakePricer(),
                              ts0 + pd.Timedelta(minutes=90),
                              half_lives={"default": 90.0, "block": 240.0},
                              entry_marks=entry_marks)
    # dealer PAID: npv = +25,000; pnl = 25,000 - 10,000 = 15,000 gross
    assert snap.gross_pnl_usd == pytest.approx(15_000.0)
    assert snap.residual_pnl_usd == pytest.approx(7_500.0)   # weight 0.5 at one half-life
    assert snap.ladders["MEETING"]["2026-07-29"] == pytest.approx(-25_000.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_book.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/stir_flow/book.py
"""Layer 2: synthetic single-dealer book MTM (ladder spec section 5)."""
from __future__ import annotations

import dataclasses
import datetime

import pandas as pd
import pytz

from SDRUtils.stir_flow import config
from SDRUtils.stir_flow import ladder_conventions as conv
from SDRUtils.stir_flow import ladder_state

NY = pytz.timezone("America/New_York")


def snap_mtm(ts):
    et = pd.Timestamp(ts)
    et = et.tz_convert(NY) if et.tzinfo else NY.localize(et.to_pydatetime())
    et = et.replace(second=0, microsecond=0)
    return NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))


def reval_unit(legs, signs, pricer, curve_name, ts) -> float:
    npv = 0.0
    for (_, leg), sign in zip(legs.iterrows(), signs):
        lp = pricer.price_leg(curve_name, ts, leg["effective_date"], leg["expiration_date"],
                              notional=float(leg["notional"]),
                              fixed_rate=float(leg["fixed_rate"]))
        npv += -sign * lp.npv_pay
    return npv


def open_positions(prints_meta, unwinds, ts, half_lives,
                   eps_half_lives: float = conv.EPS_HALF_LIVES) -> pd.DataFrame:
    per_unit = prints_meta.drop_duplicates("unit_key").copy()
    if unwinds is not None and len(unwinds):
        dead = unwinds[pd.to_datetime(unwinds["unwind_visibility_ts"]) <= pd.Timestamp(ts)]
        per_unit = per_unit[~per_unit["unit_key"].isin(set(dead["unit_key"]))]
    w = ladder_state.print_weights(per_unit, ts, half_lives)
    eps = 0.5 ** eps_half_lives
    keep = w[w > eps]
    out = per_unit[per_unit["unit_key"].isin(keep.index)].copy()
    out["weight"] = out["unit_key"].map(keep)
    return out


@dataclasses.dataclass
class BookSnapshot:
    ts: object
    ladders: dict
    per_unit: pd.DataFrame
    gross_pnl_usd: float
    residual_pnl_usd: float


def book_snapshot(units_by_key, direction_rows, prints, unwinds, pricer, ts, *,
                  half_lives=None, weighting="expected", include_suspect=False,
                  entry_marks=None) -> BookSnapshot:
    half_lives = half_lives or conv.PROVISIONAL_HALF_LIVES_MIN
    mts = snap_mtm(ts) if not isinstance(ts, pd.Timestamp) or ts.tzinfo else ts
    ladders = {
        space: ladder_state.ladder_at(prints, ts, space=space, half_lives=half_lives,
                                      weighting=weighting, include_suspect=include_suspect,
                                      unwinds=unwinds)
        for space in sorted(prints["bucket_space"].unique())
    }
    open_df = open_positions(prints, unwinds, ts, half_lives)
    recs = []
    for _, row in open_df.iterrows():
        key = row["unit_key"]
        unit = units_by_key.get(key)
        drow = direction_rows.get(key)
        if unit is None or drow is None:
            continue
        curve_name = config.CURVE_FOR[drow["rate_index_clean"]]
        signs = conv.dealer_leg_signs(unit.kind, drow["classification_method"],
                                      drow["dealer_direction"], len(unit.legs))
        npv = reval_unit(unit.legs, signs, pricer, curve_name, mts)
        entry = (entry_marks or {}).get(key, 0.0)
        recs.append(dict(unit_key=key, npv_usd=npv, entry_npv_usd=entry,
                         pnl_usd=npv - entry, weight=row["weight"]))
    per_unit = pd.DataFrame(recs)
    gross = float(per_unit["pnl_usd"].sum()) if len(per_unit) else 0.0
    residual = float((per_unit["pnl_usd"] * per_unit["weight"]).sum()) if len(per_unit) else 0.0
    return BookSnapshot(ts=ts, ladders=ladders, per_unit=per_unit,
                        gross_pnl_usd=gross, residual_pnl_usd=residual)


def eod_mark_rows(units_by_key, direction_rows, entry_marks, pricer, mark_date,
                  open_unit_keys) -> list:
    mark_ts = NY.localize(datetime.datetime(mark_date.year, mark_date.month, mark_date.day, 17, 0))
    rows = []
    for key in open_unit_keys:
        unit, drow = units_by_key.get(key), direction_rows.get(key)
        if unit is None or drow is None:
            continue
        curve_name = config.CURVE_FOR[drow["rate_index_clean"]]
        signs = conv.dealer_leg_signs(unit.kind, drow["classification_method"],
                                      drow["dealer_direction"], len(unit.legs))
        npv = reval_unit(unit.legs, signs, pricer, curve_name, mark_ts)
        entry = (entry_marks or {}).get(key, 0.0)
        rows.append(dict(unit_key=key, mark_ts=mark_ts, mark_kind="EOD", npv_usd=npv,
                         pnl_since_entry_usd=npv - entry, curve_name=curve_name))
    return rows
```

- [ ] **Step 4: Run tests, then golden**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_book.py -v`
Expected: 4 PASS

Append the golden (deterministic: reval at the SAME snapshot as entry must equal entry):

```python
@pytest.mark.network
@pytest.mark.slow
def test_reval_golden_ff_jul26_at_entry_snapshot():
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from SDRUtils.stir_flow.pricing import CurvePricer
    legs = pd.DataFrame([
        dict(effective_date=datetime.date(2026, 7, 29),
             expiration_date=datetime.date(2026, 9, 16),
             notional=3.7e9, fixed_rate=0.03713),
    ])
    ts = NY.localize(datetime.datetime(2026, 7, 10, 15, 40))
    pricer = CurvePricer(mdp=IRSwapsMDP(source="BARCHART_STIRF-RL"))
    v = book.reval_unit(legs, [-1], pricer, "USD-OIS-Q12xM12STIRT-SERFFX-MIX23", ts)
    assert abs(v - 22554.95) < 200
```

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_book.py -m network -v`
Expected: 1 PASS

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/stir_flow/book.py tests/test_stir_ladder_book.py
git commit -m "feat(ladder): book MTM, open positions, intraday snapshot API"
```

---

### Task 8: Backfill CLI

**Files:**
- Create: `SDRUtils/_swappulse_scripts/backfill_stir_ladder.py`
- Modify: `tests/test_stir_ladder_backfill.py` (append)

**Interfaces:**
- Consumes: everything above; `resolve_pg_url`, `build_units`, `is_excluded_unit`, `ELIGIBLE_LEGS_SQL`, `ALL_PKG_LEGS_SQL` from `trade_selection`; `snap_timestamp`, `CurvePricer` from `pricing`; direction rows from `arbs_stir_direction_v1`.
- Produces CLI:
  ```
  conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
      --phase project|marks|snapshot --start 2026-07-10 --end 2026-07-10 \
      [--snapshot-ts "2026-07-14 08:29"] [--limit N] [--dry-run] [--pg-url URL]
  ```
  and library functions: `load_directions(conn, start, end) -> pd.DataFrame`, `run_project_phase(conn, start, end, limit, dry_run) -> int` (units projected; skips unit_keys already in the prints table — resumable), `run_marks_phase(conn, start, end, dry_run) -> int`, `run_snapshot_phase(conn, snapshot_ts) -> None` (prints ladders + gross/residual P&L), `write_ladder_rows(conn, rows)`, `write_mark_rows(conn, rows)` (execute_values upserts, `ON CONFLICT ... DO UPDATE`).

- [ ] **Step 1: Write the failing tests (append to tests/test_stir_ladder_backfill.py)**

```python
import datetime
import pandas as pd


def test_write_ladder_rows_upsert_sql():
    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            captured["committed"] = True

    bf._execute_values = lambda cur, sql, vals: captured.update(sql=sql, n=len(vals))
    bf.write_ladder_rows(FakeConn(), [dict(
        unit_key="T1", bucket_space="MEETING", bucket_key="2026-07-29",
        delta_dv01=-50001.0, as_of_date=datetime.date(2026, 7, 10),
        execution_timestamp=pd.Timestamp("2026-07-10 19:41:45+00:00"),
        visibility_timestamp=pd.Timestamp("2026-07-10 19:42:45+00:00"),
        p_flip=0.2, direction_confidence="LOW", curve_suspect_trade=False,
        is_block=False, dv01=50001.0,
    )])
    assert "ON CONFLICT (unit_key, bucket_space, bucket_key) DO UPDATE" in captured["sql"]
    assert captured["n"] == 1 and captured["committed"]


def test_write_mark_rows_upsert_sql():
    from SDRUtils._swappulse_scripts import backfill_stir_ladder as bf
    captured = {}

    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            captured["committed"] = True

    bf._execute_values = lambda cur, sql, vals: captured.update(sql=sql, n=len(vals))
    bf.write_mark_rows(FakeConn(), [dict(
        unit_key="T1", mark_ts=pd.Timestamp("2026-07-10 21:00:00+00:00"),
        mark_kind="EOD", npv_usd=1.0, pnl_since_entry_usd=0.5, curve_name="C",
    )])
    assert "ON CONFLICT (unit_key, mark_ts) DO UPDATE" in captured["sql"]
    assert captured["n"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_backfill.py -v`
Expected: new tests FAIL

- [ ] **Step 3: Write the implementation**

```python
# SDRUtils/_swappulse_scripts/backfill_stir_ladder.py
"""Backfill the dealer positioning ladder: projection, EOD marks, snapshots.

Phases:
  project  — project classified prints onto ladders + write ENTRY marks (resumable)
  marks    — EOD reval of open positions per date in [start, end]
  snapshot — print ladder + book P&L at an arbitrary intraday timestamp
Writes ONLY arbs_stir_ladder_prints_v1 / arbs_stir_book_marks_v1.
"""
from __future__ import annotations

import argparse
import datetime
import sys

import pandas as pd
import psycopg2
import pytz
from psycopg2.extras import execute_values as _execute_values

from SDRUtils._swappulse_scripts._stir_ladder_schema_v1 import (
    BOOK_MARKS_TABLE, LADDER_PRINTS_TABLE, ensure_schema,
)
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow import book, config, ladder_state, unwinds
from SDRUtils.stir_flow.ladder import LADDER_COLUMNS, build_risk_models, project_unit
from SDRUtils.stir_flow.pricing import CurvePricer, snap_timestamp
from SDRUtils.stir_flow.trade_selection import (
    ALL_PKG_LEGS_SQL, ELIGIBLE_LEGS_SQL, build_units, is_excluded_unit,
)

NY = pytz.timezone("America/New_York")
MARK_COLUMNS = ["unit_key", "mark_ts", "mark_kind", "npv_usd", "pnl_since_entry_usd", "curve_name"]


def load_directions(conn, start, end) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT unit_key, trade_id, package_id, trade_type, rate_index_clean, "
        "classification_method, dealer_direction, p_flip, direction_confidence, "
        "curve_suspect_trade, structure_dv01, as_of_date "
        "FROM arbs_stir_direction_v1 "
        "WHERE as_of_date BETWEEN %(s)s AND %(e)s "
        "AND dealer_direction IN ('PAID', 'RECEIVED')",
        conn, params={"s": start, "e": end},
    )


def _load_units(conn, start, end):
    eligible = pd.read_sql(ELIGIBLE_LEGS_SQL, conn, params={"start": start, "end": end})
    pkg_ids = sorted(set(eligible.loc[eligible["n_package_legs"].fillna(1) > 1,
                                      "package_id"].dropna()))
    all_legs = eligible.head(0)
    if pkg_ids:
        all_legs = pd.read_sql(ALL_PKG_LEGS_SQL, conn, params={"package_ids": pkg_ids})
    units = [u for u in build_units(eligible, all_legs) if is_excluded_unit(u.legs) is None]
    return {u.unit_key: u for u in units}


def _already_projected(conn, start, end) -> set:
    df = pd.read_sql(
        f"SELECT DISTINCT unit_key FROM {LADDER_PRINTS_TABLE} "
        "WHERE as_of_date BETWEEN %(s)s AND %(e)s",
        conn, params={"s": start, "e": end},
    )
    return set(df["unit_key"])


def write_ladder_rows(conn, rows):
    if not rows:
        return
    sql = (
        f"INSERT INTO {LADDER_PRINTS_TABLE} ({', '.join(LADDER_COLUMNS)}) VALUES %s "
        f"ON CONFLICT (unit_key, bucket_space, bucket_key) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in LADDER_COLUMNS
                    if c not in ("unit_key", "bucket_space", "bucket_key"))
    )
    with conn.cursor() as cur:
        _execute_values(cur, sql, [tuple(r.get(c) for c in LADDER_COLUMNS) for r in rows])
    conn.commit()


def write_mark_rows(conn, rows):
    if not rows:
        return
    sql = (
        f"INSERT INTO {BOOK_MARKS_TABLE} ({', '.join(MARK_COLUMNS)}) VALUES %s "
        f"ON CONFLICT (unit_key, mark_ts) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in MARK_COLUMNS
                    if c not in ("unit_key", "mark_ts"))
    )
    with conn.cursor() as cur:
        _execute_values(cur, sql, [tuple(r.get(c) for c in MARK_COLUMNS) for r in rows])
    conn.commit()


def run_project_phase(conn, start, end, limit=0, dry_run=False) -> int:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    directions = load_directions(conn, start, end)
    units = _load_units(conn, start, end)
    done = _already_projected(conn, start, end)
    todo = directions[~directions["unit_key"].isin(done)]
    todo = todo[todo["unit_key"].isin(units.keys())]
    if limit:
        todo = todo.head(limit)

    mdp = IRSwapsMDP(source=config.CURVE_SOURCE)
    stirf = STIRFutureMDP(source=config.CURVE_SOURCE)
    pricer = CurvePricer(mdp=mdp)
    n = 0
    # group by (curve, snapshot minute) so risk models build once per group
    metas = []
    for _, drow in todo.iterrows():
        u = units[drow["unit_key"]]
        first = u.legs.iloc[0]
        snap = snap_timestamp(first.get("original_execution_timestamp"),
                              first["execution_timestamp"])
        metas.append((config.CURVE_FOR[drow["rate_index_clean"]], snap, drow, u))
    metas.sort(key=lambda m: (m[0], m[1]))
    cache = {}
    ladder_rows, mark_rows = [], []
    for curve_name, snap, drow, u in metas:
        try:
            key = (curve_name, snap)
            if key not in cache:
                h = pricer.handle(curve_name, snap)
                cache[key] = build_risk_models(
                    curve_name, h, snap, stirf,
                    include_basis=(drow["rate_index_clean"] == "FED_FUNDS"))
            rows, entry = project_unit(u, drow.to_dict(), cache[key], pricer, curve_name, snap)
            ladder_rows.extend(rows)
            mark_rows.append(entry)
            n += 1
            if len(ladder_rows) >= 2000 and not dry_run:
                write_ladder_rows(conn, ladder_rows)
                write_mark_rows(conn, mark_rows)
                ladder_rows, mark_rows = [], []
        except Exception as exc:  # noqa: BLE001 per-unit isolation
            print(f"PROJECT_ERROR {drow['unit_key']}: {exc}")
    if not dry_run:
        write_ladder_rows(conn, ladder_rows)
        write_mark_rows(conn, mark_rows)
    print(f"projected {n} units ({start}..{end})")
    return n


def run_marks_phase(conn, start, end, dry_run=False) -> int:
    prints = pd.read_sql(f"SELECT * FROM {LADDER_PRINTS_TABLE}", conn)
    if prints.empty:
        print("no projections; run project phase first")
        return 0
    directions = load_directions(conn, prints["as_of_date"].min(), end)
    dmap = {r["unit_key"]: r for r in directions.to_dict(orient="records")}
    units = _load_units(conn, prints["as_of_date"].min(), end)
    entries = pd.read_sql(
        f"SELECT unit_key, npv_usd FROM {BOOK_MARKS_TABLE} WHERE mark_kind = 'ENTRY'", conn)
    entry_marks = dict(zip(entries["unit_key"], entries["npv_usd"]))
    unw = unwinds.extract_unwind_events(conn, prints["as_of_date"].min(), end,
                                        set(prints["unit_key"]))
    pricer = CurvePricer()
    total = 0
    for d in pd.date_range(start, end, freq="B"):
        mark_date = d.date()
        eod_ts = NY.localize(datetime.datetime(mark_date.year, mark_date.month, mark_date.day, 17, 0))
        from SDRUtils.stir_flow.ladder_conventions import PROVISIONAL_HALF_LIVES_MIN
        open_df = book.open_positions(prints, unw, eod_ts, PROVISIONAL_HALF_LIVES_MIN)
        rows = book.eod_mark_rows(units, dmap, entry_marks, pricer, mark_date,
                                  list(open_df["unit_key"]))
        if not dry_run:
            write_mark_rows(conn, rows)
        total += len(rows)
        print(f"{mark_date}: {len(rows)} EOD marks")
    return total


def run_snapshot_phase(conn, snapshot_ts) -> None:
    ts = NY.localize(pd.Timestamp(snapshot_ts).to_pydatetime()) \
        if pd.Timestamp(snapshot_ts).tzinfo is None else pd.Timestamp(snapshot_ts)
    prints = pd.read_sql(f"SELECT * FROM {LADDER_PRINTS_TABLE}", conn)
    directions = load_directions(conn, prints["as_of_date"].min(), ts.date())
    dmap = {r["unit_key"]: r for r in directions.to_dict(orient="records")}
    units = _load_units(conn, prints["as_of_date"].min(), ts.date())
    entries = pd.read_sql(
        f"SELECT unit_key, npv_usd FROM {BOOK_MARKS_TABLE} WHERE mark_kind = 'ENTRY'", conn)
    unw = unwinds.extract_unwind_events(conn, prints["as_of_date"].min(), ts.date(),
                                        set(prints["unit_key"]))
    snap = book.book_snapshot(units, dmap, prints, unw, CurvePricer(), ts,
                              entry_marks=dict(zip(entries["unit_key"], entries["npv_usd"])))
    for space, series in snap.ladders.items():
        print(f"\n== {space} ladder @ {ts} (dealer dv01, + = long fut-equiv) ==")
        print(series.round(0).to_string())
    print(f"\ngross book P&L:    {snap.gross_pnl_usd:,.0f}")
    print(f"residual book P&L: {snap.residual_pnl_usd:,.0f}")
    print(f"open positions:    {len(snap.per_unit)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["project", "marks", "snapshot"], required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--snapshot-ts")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pg-url", default=None)
    args = ap.parse_args()

    conn = psycopg2.connect(resolve_pg_url(args.pg_url))
    ensure_schema(conn)
    if args.phase == "project":
        run_project_phase(conn, args.start, args.end, args.limit, args.dry_run)
    elif args.phase == "marks":
        run_marks_phase(conn, args.start, args.end, args.dry_run)
    else:
        run_snapshot_phase(conn, args.snapshot_ts)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests + full fast gate**

Run: `conda run -n stir python -m pytest tests/test_stir_ladder_backfill.py -v`
Expected: 4 PASS
Run: `conda run -n stir python -m pytest tests -m "not slow and not network and not db" -q`
Expected: all pass, no regressions

- [ ] **Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/backfill_stir_ladder.py tests/test_stir_ladder_backfill.py
git commit -m "feat(ladder): backfill CLI - project, marks, snapshot phases"
```

---

### Task 9: Operational backfill + verification (network + prod DB; user-gated)

**CONFIRM WITH THE USER before each prod-writing step.** Long-running steps: use `run_in_background`, chunked, resumable.

- [ ] **Step 1: Classifier backfill extension (6 months, chunked weekly)**

The ladder needs `arbs_stir_direction_v1` coverage 2026-01-12 → present (currently only 2026-07-10). Run per-week chunks, oldest first:

```bash
conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_direction \
  --classify-date <DATE> --calib-start 2026-06-10 --calib-end 2026-07-10
```

looped over business days (write a small runner script iterating dates, logging per-day summaries). Verify per chunk: direction counts by day, UNKNOWN rate < 2%, no empty days. This is the longest step (each day ≈ the 07/10 POC run; curve-cache-bound).

- [ ] **Step 2: Projection backfill smoke, then full**

```bash
conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
  --phase project --start 2026-07-10 --end 2026-07-10 --limit 25 --dry-run
# then, after user confirmation, full range without --limit/--dry-run:
conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
  --phase project --start 2026-01-12 --end <TODAY>
```

Expected: PROJECT_ERROR lines only for known seasoned-leg/fixings units; resumable on rerun (already-projected unit_keys skipped).

- [ ] **Step 3: EOD marks backfill**

```bash
conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
  --phase marks --start 2026-01-12 --end <TODAY>
```

- [ ] **Step 4: Verification queries**

```sql
-- bucket-sum vs structure DV01 consistency (MEETING space, outrights):
SELECT p.unit_key, sum(p.delta_dv01) AS ladder_sum, max(p.dv01) AS dv01,
       max(d.dealer_direction) AS dir
FROM arbs_stir_ladder_prints_v1 p JOIN arbs_stir_direction_v1 d USING (unit_key)
WHERE p.bucket_space = 'MEETING' AND d.trade_type = 'OUTRIGHT'
GROUP BY p.unit_key
HAVING abs(abs(sum(p.delta_dv01)) - max(p.dv01)) > 0.1 * max(p.dv01)
LIMIT 20;   -- expect ~empty; investigate any rows
-- sign convention: PAID -> negative sums, RECEIVED -> positive
SELECT dir, sgn, count(*) FROM (
  SELECT d.dealer_direction AS dir, sign(sum(p.delta_dv01)) AS sgn
  FROM arbs_stir_ladder_prints_v1 p JOIN arbs_stir_direction_v1 d USING (unit_key)
  WHERE p.bucket_space = 'MEETING' AND d.trade_type = 'OUTRIGHT'
  GROUP BY p.unit_key, d.dealer_direction
) x GROUP BY dir, sgn ORDER BY dir;
-- expect: PAID rows overwhelmingly sgn = -1, RECEIVED overwhelmingly +1
-- visibility sanity (no-lookahead):
SELECT count(*) FROM arbs_stir_ladder_prints_v1
WHERE visibility_timestamp < execution_timestamp + interval '1 minute';  -- expect 0
SELECT count(*) FROM arbs_stir_ladder_prints_v1
WHERE is_block AND visibility_timestamp < execution_timestamp + interval '15 minutes';  -- expect 0
```

- [ ] **Step 5: The intraday snapshot demo**

```bash
conda run -n stir python -m SDRUtils._swappulse_scripts.backfill_stir_ladder \
  --phase snapshot --snapshot-ts "2026-07-14 08:29"
```

Expected: MEETING + FUTURES (+SERFF) ladders printed with dealer-signed DV01 per bucket, gross and residual book P&L, open-position count — the spec's "positioning and P&L at 07/14 8:29am" question answered from persisted data + on-demand reval.

- [ ] **Step 6: Results note + commit**

Write `docs/superpowers/plans/2026-07-14-dealer-ladder-backfill-results.md`: coverage by day, projection error counts, verification query outcomes, the 8:29am snapshot output, unwind-lineage probe findings, runtime notes.

```bash
git add docs/superpowers/plans/2026-07-14-dealer-ladder-backfill-results.md
git commit -m "docs(ladder): 6-month backfill + snapshot verification results"
```

---

## Deferred (per spec gating — NOT in this plan)

- `BT/dealer_ladder/` Phase-4 research harness (decay calibration, kinks + structural grid, go/no-go event study) — separate plan once ladder data exists.
- Phase 5 trigger/sizing/stops — gated on Phase 4's verdict.
- Dissemination-timestamp wiring if the Task 5 probe finds the column in raw-but-not-tape (follow-up tape change).
- Dashboard / live 15-min ladder service.

## Self-Review Notes

- Spec coverage: §3 inputs (Tasks 5, 8 load), §4 projection + table (Tasks 1-4), §5 book + intraday snapshot (Task 7, CLI snapshot phase), §6 ladder state (Task 6), §7 curve-suspect handling (suspect flag persisted Task 4, excluded-by-default Task 6), §8 no-lookahead (visibility Task 1, tests Task 6, verification Task 9), §11 backfill (Task 9), §12 testing (per task). §§9-10 deferred by scope decision, stated up front.
- Sign-convention arbiter: single constant `RL_DELTA_TO_FUTURES_EQ` with a network golden asserting PAID → negative — documented flip procedure, `dealer_leg_signs` immutable.
- Type consistency: `RiskModel`, `LADDER_COLUMNS`, `MARK_COLUMNS`, `BookSnapshot`, `print_weights` signatures consistent across Tasks 3-8.
