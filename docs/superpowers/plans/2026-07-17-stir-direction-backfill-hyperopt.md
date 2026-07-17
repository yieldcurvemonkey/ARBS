# STIR direction backfill hyperoptimization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Cut `run_classification` wall time (~269 s/day) by decoupling curve acquisition from classification — enumerate demand, warm curves in parallel, persist locally, then classify against a warm cache — with byte-for-byte identical output.

**Architecture:** New `SDRUtils/stir_flow/curve_warm.py` holds a pure curve-demand enumerator and a thread-pool warmer that pre-populates a `CurvePricer`'s handle cache (and, in Phase 2, a local CurveStore). `backfill_stir_direction.run_classification` calls the warmer before `classify_units`; the classifier is unchanged. Full-history uses a process pool over days.

**Tech Stack:** Python 3.11 (conda env `stir`), rateslib, `MDP.IRSwaps.IRSwapsMDP`, `Caching.curve_store`, `concurrent.futures`, psycopg2, pandas, pytest.

## Global Constraints

- **Bit-identical:** every stored column in `arbs_stir_direction_v1` must match current output exactly. Only caching/reuse/dedupe/parallelism — no pricing/classification math changes.
- **Solver tolerance pinned** to the current lazy path (`1e-5`); the relaxed `1e-3` bulk path must not be used.
- **Barchart concurrency capped** (default ≤ 8) to avoid a 429 storm on `BARCHART_STIRF-RL`.
- All Python via `conda run -n stir ...`.
- Curve warming uses **threads** (I/O-bound, bit-identical, no Windows spawn); day-level backfill uses **processes**.
- Fast test gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.

---

## Task 0: Golden capture + bit-identical diff harness

**Files:**
- Create: `SDRUtils/_swappulse_scripts/_stir_direction_golden.py` (dev harness: capture + diff)
- Create: `tests/stir_flow/test_curve_demand.py` (later tasks extend it)

**Interfaces:**
- Produces: `capture_golden(conn, date) -> pd.DataFrame` (all `DIRECTION_COLUMNS`, sorted by `unit_key`); `diff_against_golden(golden, rows) -> pd.DataFrame` (empty == identical).

- [ ] **Step 1: Write the harness.** `capture_golden` runs `run_classification(conn, date, pd.DataFrame(), dry_run=True)`, returns `pd.DataFrame(rows)[DIRECTION_COLUMNS].sort_values("unit_key").reset_index(drop=True)`. `diff_against_golden(golden, rows)` builds the same frame from `rows` and returns rows where any column differs (compare with `equals` per-cell; treat NaN==NaN as equal; `quality_flags` compared as list/str).
- [ ] **Step 2: Capture golden for 2026-07-02** to `scratchpad/golden_0702.pkl` and a second day `2026-07-01` to `golden_0701.pkl`. Record row counts + `dealer_direction.value_counts()`.
- [ ] **Step 3: Self-diff sanity** — `diff_against_golden(golden, golden_rows)` returns empty. Commit the harness.

## Task 1: Curve-demand enumerator (pure, DRY with `_unit_meta`)

**Files:**
- Create: `SDRUtils/stir_flow/curve_warm.py`
- Modify: `SDRUtils/_swappulse_scripts/backfill_stir_direction.py` (`_unit_meta` reuses the new helper)
- Test: `tests/stir_flow/test_curve_demand.py`

**Interfaces:**
- Produces:
  - `unit_curve_and_snap(unit) -> tuple[str, pd.Timestamp]` — `(config.CURVE_FOR[first.rate_index_clean], snap_timestamp(first.original_execution_timestamp, first.execution_timestamp))`, exactly as `_unit_meta` computes today.
  - `enumerate_curve_demand(units) -> set[tuple[str, pd.Timestamp]]`.

- [ ] **Step 1: Write failing test.**
```python
# tests/stir_flow/test_curve_demand.py
import pandas as pd
from SDRUtils.stir_flow.curve_warm import unit_curve_and_snap, enumerate_curve_demand

class _U:
    def __init__(self, legs): self.legs = legs

def _leg(idx="FED_FUNDS", ts="2026-07-02T13:05:23+00:00", orig=None):
    return pd.DataFrame([{ "rate_index_clean": idx, "execution_timestamp": pd.Timestamp(ts),
                           "original_execution_timestamp": pd.Timestamp(orig) if orig else None }])

def test_unit_curve_and_snap_ff():
    cn, snap = unit_curve_and_snap(_U(_leg("FED_FUNDS")))
    assert cn == "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"
    assert snap.minute == 4 and snap.second == 0     # 13:05 -> snap to 13:04:00 (minute-1)

def test_enumerate_dedupes():
    u1 = _U(_leg("SOFR", "2026-07-02T13:05:23+00:00"))
    u2 = _U(_leg("SOFR", "2026-07-02T13:05:47+00:00"))   # same snapped minute
    assert len(enumerate_curve_demand([u1, u2])) == 1
```
- [ ] **Step 2: Run — expect ImportError/fail.** `conda run -n stir python -m pytest tests/stir_flow/test_curve_demand.py -v`
- [ ] **Step 3: Implement `curve_warm.py`.**
```python
from __future__ import annotations
from SDRUtils.stir_flow import config
from SDRUtils.stir_flow.pricing import snap_timestamp

def unit_curve_and_snap(unit):
    first = unit.legs.iloc[0]
    curve_name = config.CURVE_FOR[first["rate_index_clean"]]
    snap = snap_timestamp(first.get("original_execution_timestamp"),
                          first["execution_timestamp"])
    return curve_name, snap

def enumerate_curve_demand(units):
    return {unit_curve_and_snap(u) for u in units}
```
- [ ] **Step 4: Refactor `_unit_meta` to reuse it** (keeps one source of truth, bit-identical): replace its curve_name/snap lines with `curve_name, snap = unit_curve_and_snap(unit)`.
- [ ] **Step 5: Run tests — expect PASS**, and confirm `enumerate_curve_demand` on 07-02 units yields 479 (matches profiling). Commit.

## Task 2: Thread-pool curve warmer (Phase 1 core)

**Files:**
- Modify: `SDRUtils/stir_flow/curve_warm.py`
- Test: `tests/stir_flow/test_curve_warm.py`

**Interfaces:**
- Consumes: `CurvePricer` with `._mdp` and `._handles: dict[(str,ts), handle]`.
- Produces: `warm_pricer(pricer, demand, max_workers=8, on_error="skip") -> dict` returning `{"built": int, "reused": int, "failed": int}`; failures leave the key absent so the lazy path still runs (unchanged `PRICING_ERROR` behavior).

- [ ] **Step 1: Write failing test** (fake mdp/pricer, no network):
```python
# tests/stir_flow/test_curve_warm.py
import pandas as pd
from SDRUtils.stir_flow.curve_warm import warm_pricer

class _FakeMDP:
    def __init__(self): self.calls = []
    def _get_curve(self, curve_name, timestamp):
        self.calls.append((curve_name, timestamp)); return f"H:{curve_name}:{timestamp}"

class _FakePricer:
    def __init__(self): self._mdp = _FakeMDP(); self._handles = {}

def test_warm_builds_all_and_is_idempotent():
    p = _FakePricer()
    demand = {("C", pd.Timestamp("2026-07-02T13:04:00Z")), ("C", pd.Timestamp("2026-07-02T13:05:00Z"))}
    r = warm_pricer(p, demand, max_workers=2)
    assert r["built"] == 2 and len(p._handles) == 2
    r2 = warm_pricer(p, demand, max_workers=2)          # already warm
    assert r2["built"] == 0 and r2["reused"] == 2

def test_warm_isolates_failures():
    p = _FakePricer()
    def boom(curve_name, timestamp):
        if "bad" in curve_name: raise RuntimeError("x")
        return "H"
    p._mdp._get_curve = boom
    r = warm_pricer(p, {("ok", pd.Timestamp("2026-07-02T13:04:00Z")),
                        ("bad", pd.Timestamp("2026-07-02T13:04:00Z"))}, max_workers=2)
    assert r["built"] == 1 and r["failed"] == 1 and ("ok", pd.Timestamp("2026-07-02T13:04:00Z")) in p._handles
```
- [ ] **Step 2: Run — expect fail.**
- [ ] **Step 3: Implement `warm_pricer`.**
```python
import concurrent.futures as _cf

def warm_pricer(pricer, demand, max_workers=8, on_error="skip"):
    todo = [k for k in demand if k not in pricer._handles]
    built = failed = 0
    if not todo:
        return {"built": 0, "reused": len(demand), "failed": 0}
    with _cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(pricer._mdp._get_curve, curve_name=cn, timestamp=ts): (cn, ts)
                for cn, ts in todo}
        for fut in _cf.as_completed(futs):
            key = futs[fut]
            try:
                pricer._handles[key] = fut.result()
                built += 1
            except Exception:
                failed += 1
                if on_error != "skip":
                    raise
    return {"built": built, "reused": len(demand) - len(todo), "failed": failed}
```
- [ ] **Step 4: Run tests — PASS. Commit.**

## Task 3: Wire warmer into `run_classification` + CLI knobs

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/backfill_stir_direction.py`

**Interfaces:**
- Consumes: `enumerate_curve_demand`, `warm_pricer`.
- Produces: `run_classification(conn, classify_date, stats, limit=0, dry_run=False, warm_jobs=8, warm=True)`.

- [ ] **Step 1:** In `run_classification`, after building `units` and before `classify_units`, construct the pricer once and warm it:
```python
    pricer = CurvePricer()
    if warm:
        from SDRUtils.stir_flow.curve_warm import enumerate_curve_demand, warm_pricer
        demand = enumerate_curve_demand(units[:limit] if limit else units)
        wr = warm_pricer(pricer, demand, max_workers=warm_jobs)
        print(f"warmed curves: built={wr['built']} reused={wr['reused']} failed={wr['failed']} "
              f"(demand={len(demand)})")
    rows = classify_units(units, pricer, _build_lookups(stats), _build_prev_rate_lookup(prints))
```
(Currently `classify_units(units, CurvePricer(), ...)` builds a throwaway pricer — replace with the warmed `pricer`.)
- [ ] **Step 2:** Add `--warm-jobs` (default 8) and `--no-warm` args in `main()`; thread through to `run_classification`.
- [ ] **Step 3: Bit-identical gate.** Run 07-02 with warm on, diff vs `golden_0702.pkl` → must be empty. Then repeat 07-01. Record wall time (expect ~5–8× faster). Commit only if diff empty.
```bash
conda run -n stir python -c "..."   # capture rows with warm=True, diff_against_golden -> assert empty
```

## Task 4: Pull-day dedupe spike + implementation (Phase 1b)

**Files:**
- Modify: `SDRUtils/stir_flow/curve_warm.py` (optional day-partition prefetch)

- [ ] **Step 1 (spike):** Determine whether `Caching/curve_store.read_raw_day` (or `supabase_curve_sync.pull_day`) re-reads the remote day partition per call. Instrument a 20-minute warm and count `pull_day` invocations per `(curve, date)`. If it caches per-day already, SKIP this task. If it re-pulls, continue.
- [ ] **Step 2:** Add `prefetch_day_partitions(pricer, demand)` that calls the day-partition read once per distinct `(curve, date)` before warming (or wraps the read in a per-run `functools.lru_cache`), so warming threads hit an in-process cache. Keep it bit-identical (same nodes returned).
- [ ] **Step 3:** Re-run 07-02 diff gate; record incremental speedup. Commit if diff empty.

## Task 5: Persist to local CurveStore (Phase 2) — gated on reconstruct spike

**Files:**
- Modify: `SDRUtils/stir_flow/curve_warm.py`, `SDRUtils/_swappulse_scripts/backfill_stir_direction.py`

- [ ] **Step 1 (reconstruct-fidelity spike):** Build one curve via `_get_curve` (solve), persist its nodes to a local CurveStore, reconstruct, and assert `rate`/`analytic_delta`/`fair_rate` for a sample swap match the solved curve **bit-identically**. If not bit-identical, STOP Phase 2 — keep Phase 1 in-run warm only; record findings.
- [ ] **Step 2:** If the spike passes, make the warmer persist solved nodes to the local CurveStore (promote path), so a second run's `_get_curve` takes the ~1.6 ms reconstruct branch.
- [ ] **Step 3:** Warm-rerun gate: run 07-02 twice; second run diff vs golden empty AND ≫ faster (expect ~100×). Commit.

## Task 6: Day-level orchestrator + calibrate-once (Phase 3)

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/backfill_stir_direction.py`
- Create: `SDRUtils/_swappulse_scripts/backfill_stir_direction_range.py` (multi-day driver)

**Interfaces:**
- Produces: module-level `_classify_one_day(args_tuple)` (picklable worker: opens its own conn + `IRSwapsMDP`, runs warm+classify+write for one date, returns summary); `run_range(start, end, day_jobs, warm_jobs, calib_start, calib_end)`.

- [ ] **Step 1:** Compute calibration once for the window; pass the resulting `stats` frame into each day worker (avoid recomputation).
- [ ] **Step 2:** `ProcessPoolExecutor(max_workers=day_jobs)` over the date list; each worker runs `_classify_one_day`. Guard with `if __name__ == "__main__"` for Windows spawn.
- [ ] **Step 3:** Bit-identical gate on a 2–3-day range: process-pool output == per-day sequential output == golden. Record end-to-end speedup. Commit.

## Task 7 (optional, gated): direct pricing path (Phase 4)

- [ ] **Step 1:** Prototype `price_leg` via `RLIRSwapCurve.build_irswap` + `.fair_rate`/`.analytic_delta` (skip `IRSwapQuery`/deepcopy). Diff full-day vs golden. Ship only if bit-identical. Otherwise document and drop.

## Self-Review

- Spec §3 decouple → Tasks 1–3. §4 components A/B/C/D → Tasks 1,2,3,4; E → Task 6. §5 threads/processes → Tasks 2,6. §6 Barchart cap → Task 2 `max_workers`. §7 correctness gate → Task 0 + gates in every task. §9 phasing → Tasks map 1:1 (Phase 0=Task 0, Phase 1=Tasks 1–4, Phase 2=Task 5, Phase 3=Task 6, Phase 4=Task 7). §11 testing → Tasks 0–3,6.
- Type consistency: `warm_pricer(pricer, demand, max_workers, on_error)`, `enumerate_curve_demand(units)->set`, `unit_curve_and_snap(unit)->(str,ts)` used consistently across Tasks 1–3,6.
- No placeholders in executable tasks (0–3); Tasks 4–7 carry explicit spike/gate branch conditions because they legitimately depend on runtime findings (documented as spikes, not hand-waves).
