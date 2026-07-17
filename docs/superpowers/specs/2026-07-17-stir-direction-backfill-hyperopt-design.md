# STIR dealer-direction backfill — hyperoptimization design

**Date:** 2026-07-17
**Branch:** `feat/stir-direction-backfill-opt`
**Target script:** `SDRUtils/_swappulse_scripts/backfill_stir_direction.py`
**Status:** approved (user delegated full autonomy 2026-07-17)

## 1. Problem

`run_classification` takes **~269 s for one day** (2026-07-02: 693 units, 886 priced
legs, 479 distinct `(curve, minute)` snapshots). Profiling (cProfile + instrumented
`CurvePricer`) shows the cost is **curve acquisition I/O, not pricing**:

| Cost | Time | % wall | Nature |
|---|---|---|---|
| Curve acquisition (`_get_curve`) | 207 s | **77%** | I/O-bound |
| ├─ Supabase `pull_day` (remote CurveStore read) | ~115 s | ~43% | remote round-trip, re-pulled **per minute** |
| ├─ Barchart HTTP futures fetch (on store miss) | ~77 s | ~29% | network; 349/479 snapshots miss → full LM solve |
| Swap analytics (rate/npv/pv01) | ~16 s | ~6% | the only real compute |
| Load frames + build_units | ~8 s | ~3% | DB reads |

Root causes:
1. Curves are built **lazily per leg**, interleaving remote I/O with pricing.
2. `read_raw_day`/`pull_day` re-reads the same `(curve, date)` partition from remote
   Supabase **once per minute** instead of once per day.
3. The barchart `_get_curve` path **never writes solved curves back to the CurveStore**
   (no `_promote` call at `IRSwapsMDP.py:2061`), so every run re-pays the full cost.

At 269 s/day a 250-day rebuild is ~18.7 h single-threaded.

## 2. Goals / non-goals

**Goals** (user-selected): optimize **both** the single-day hot path **and** multi-day
backfill orchestration; run **on this Windows box**.

**Hard constraint — bit-identical.** Every stored field in `arbs_stir_direction_v1`
must be byte-for-byte identical to the current classifier output. Only caching, reuse,
I/O-dedupe and parallelism are permitted; no changes to pricing/classification math.

**Non-goals:** changing classification logic, confidence model, calibration math, or the
DB schema. Approximate/alternate pricing math (the ~6% analytics) is out of scope except
as an optional, separately-gated Phase 4.

## 3. Architecture — decouple acquisition from compute

Split each day into ordered stages with clean interfaces:

```
enumerate demand  ->  warm curves (parallel, persisted)  ->  classify (warm, sequential)  ->  write
```

The classifier is untouched; we change only **when and how curves are acquired**. Once
every demanded curve is warm in a local store, `classify_units` runs unchanged against
~1.6 ms local reconstructs.

## 4. Components

- **A. Curve-demand enumerator** — pure function `enumerate_curve_demand(units) ->
  set[(curve_name, snapped_minute)]`, reusing `snap_timestamp` + `config.CURVE_FOR`.
  Deterministic, no I/O, unit-testable. (479 for 07-02.)
- **B. Parallel curve warmer** — builds every demanded curve concurrently and persists
  solved nodes to a **local** CurveStore. Uses the **current single-shot build path
  unchanged**, solver tolerance pinned to today's `1e-5`. Side-effect only.
- **C. Pull dedupe** — read each `(curve, date)` CurveStore partition **once**, not per
  minute. Largely subsumed once B has written the local store; also a standalone
  bit-identical win (~43%).
- **D. Warm classification pass** — existing `classify_units`; `CurvePricer._get_curve`
  now resolves to a local reconstruct. Sequential, analytics-only.
- **E. Day-level orchestrator** — full-history: **process pool over days** (independent),
  calibration computed **once per window** and passed in, per-day = warm(B)+classify(D),
  DB upserts batched per day.

## 5. Concurrency decision (autonomous)

The user selected "multiprocess on this box", but profiling shows the bottleneck is
**I/O (network) = 77%**, and the CPU solve+analytics is ~6%. Therefore:

- **Curve warming (Component B): thread pool, not process pool.** The work is dominated
  by network waits (Supabase pull + Barchart fetch) where the GIL is released; threads
  overlap those waits, are provably **bit-identical** (each `_get_curve` is the identical
  call, just concurrent), and avoid Windows `spawn` overhead, MDP re-instantiation per
  worker, and pickling of the lock/diskcache/HTTP-laden builder. Thread-safety is already
  provided (RLock-guarded builder state, thread-local duckdb, atomic parquet writes).
- **Day-level orchestration (Component E): process pool over days.** Days are independent
  and mix CPU+I/O; separate processes give clean isolation and real parallelism for large
  backfills. Each worker builds its own `IRSwapsMDP`; only day + config cross the boundary.

This is a reasoned deviation justified by the measured bottleneck; the outcome (parallel
on this box, bit-identical) matches the user's intent.

## 6. Barchart 429 constraint

Parallelizing cold builds multiplies concurrent Barchart futures fetches; there is prior
history of an unthrottled 429 storm on this exact source (fixed by adding throttling).
**Constraint:** the warmer caps Barchart concurrency independently and modestly (default
≤ 8), routes fetches through the existing throttled fetch path, and relies on the
per-symbol quote cache. Warm-pool width for solves/reconstructs is a separate knob.

## 7. Correctness gate (governs every phase)

- **Golden capture** — snapshot current per-day output (all stored columns) for ≥ 2
  representative days (incl. 2026-07-02) via a dry-run before any change.
- **Bit-identical diff harness** — after each phase, a field-level diff of every column
  vs golden must be **empty**; this is the merge pass/fail.
- **Phase-0 reconstruct spike** — prove `solve → persist → reconstruct` round-trips
  `curve_mid`/`pv01`/`spread_to_mid_bps` bit-identically (parquet float64 nodes +
  interpolation must reproduce exactly). If it cannot, persistence (Phase 2) degrades to
  an **in-run warm cache only** — the parallel-build win (Phase 1) still stands.
- **Solver config pinned** to `1e-5`; the relaxed `1e-3` bulk path is explicitly not used.

## 8. Error handling & idempotency

Per-curve build failure isolates to that minute — units needing it get today's
`PRICING_ERROR` quality flag (unchanged behavior). Per-day failure isolates the day.
CurveStore writes are atomic. The DB upsert (`ON CONFLICT (unit_key) DO UPDATE`) is
idempotent; re-runs warm only missing curves. A `--no-warm` / legacy fallback flag runs
the current lazy path unchanged.

## 9. Phasing (each independently shippable, behind the diff gate)

0. **Phase 0** — golden capture + bit-identical harness + reconstruct-fidelity spike +
   confirm `pull_day` per-minute re-read.
1. **Phase 1** — thread-pool curve warmer (in-run, no persist) + pull dedupe. Bit-identical.
   Target ~5–8× single-day.
2. **Phase 2** — persist to local CurveStore; warm re-runs collapse to reconstruct-only.
   Target ~100× warm re-run.
3. **Phase 3** — day-level process-pool orchestrator + calibrate-once for full-history.
4. **Phase 4 (optional, gated)** — direct `build_irswap`+`fair_rate`/`analytic_delta`
   pricing path to shave the ~6% analytics + per-leg deepcopy; ships only if bit-identical.

## 10. Targets

- Single-day cold: **~10×** (parallel warm overlapping Barchart/Supabase I/O + pull dedupe).
- Warm re-run: **~100×** (local reconstruct only).
- Full-history: bounded by `day-pool width × per-day cold` — 18.7 h → well under an hour.

## 11. Testing

- Unit: `enumerate_curve_demand` returns the exact deterministic set for a fixture day.
- Fidelity: warm→reconstruct reproduces a solved curve's `rate`/`pv01` exactly (spike/test).
- Integration: full-day field diff vs golden == empty (2026-07-02 + one more day).
- Orchestration: 2–3-day range under the day pool == per-day sequential output.
- Regression: `--no-warm` fallback == current output; existing `tests/` stay green
  (`conda run -n stir python -m pytest tests -m "not slow and not network and not db"`).

## 12. Files (anticipated)

- New: `SDRUtils/stir_flow/curve_warm.py` (Components A, B, C).
- Modified: `SDRUtils/_swappulse_scripts/backfill_stir_direction.py` (wire warm stage +
  `--warm-jobs`/`--day-jobs`/`--no-warm` flags + calibrate-once), `SDRUtils/stir_flow/
  pricing.py` (pull dedupe / warm-cache hook).
- New tests under `tests/`.
