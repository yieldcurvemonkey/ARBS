# Dealer direction in the tape front end — working ledger

Branch `feat/tape-direction-frontend`, worktree `C:\Users\chris\clee\ARBS-fe`.
Started 2026-08-12. Long-running; this file is the durable memory.

**Scope**: materialise the dealer-direction inference and the signed risk-bucket
ladder into Postgres, and surface both in the USD swap tape front end. NOT:
improving the inference, extending coverage, hedge-ratio projection, any signal.

---

## D0. Branch point — branch from `main`, not from PR #441

The brief said PR #441 "is not merged; you will need to branch from it or
cherry-pick". **It was merged** — `c0c866eb Merge pull request #441` is an
ancestor of `origin/main` (`4a71d1bf`), which also carries #442 (`r0-leadlag`)
and #443. `docs/dealer_direction/`, `SDRUtils/dealer_direction/`,
`BT/dd_signals/` and `notebooks/dealer_direction/` are all present on
`origin/main`.

So: **branched from `origin/main`**. No cherry-pick, no rebase onto a feature
branch, and the R0 result (#442) — which is what retargets this to a *daily*
indicator rather than an intraday trigger — comes along for free.

## D1. Worktree is on `C:`, caches on `D:`

`C:` had 1.9 GB free at start, and `SDRUtils/dashboard/node_modules` measures
746 MB. `D:` has 287 GB but is **exFAT** — `git worktree add D:/ARBS-fe` gets
`fatal: detected dubious ownership … file system that does not record
ownership`, and exFAT has no symlinks or file modes. A worktree there is a bad
idea, so it stays at `C:\Users\chris\clee\ARBS-fe` as briefed.

Freed instead: the global npm cache was **4,799 MB on C:**. Moved to
`D:\npm-cache` (`npm config set cache D:\npm-cache --global`). Reversible with
`npm config delete cache`. Python/analysis caches go to `D:\ddfe_cache`.

---

## Phase log

### Phase 0 — orientation (2026-08-12)

Read `WHAT_THE_LADDER_SUPPORTS.md`, `INDICATOR.md`, `DESIGN.md`, `LEDGER.md`.

### G-1. The brief's join key is WRONG. The grain is right; the key is `package_id`.

Probes `scratch/ddfe01_join_probe.py`, `scratch/ddfe02_join_on_package_id.py`.
Prod Supabase, read-only.

The brief says the display view's primary key `package_id` *is* the direction
feature's `unit_key`. Measured on 2026-04-01: the two agree on the **grain**
exactly — 2,752 view rows, 2,752 units, no nulls — and on only **27.47% of the
keys**.

The cause is `universe.py:614`:

```python
u["unit_key"] = np.where(u["n_legs"] <= 1, u["first_trade_id"], u.index)
```

A **single-leg print that still carries a package id** — `MATCHED_MATURITY_…`,
`SPREADOVER_…` and the rest — is keyed by that package id in the view and by
its raw `trade_id` in `unit_key`. Roughly three quarters of the tape's rows are
in that class, which is why the mismatch is so large rather than a rounding
edge.

**The join that works is `package_id`, which `unit_frame` also carries.**
Measured over five days spanning the whole tape:

| day | view rows | units | `package_id` match | view-only | unit-only | `unit_key` match |
|---|---:|---:|---:|---:|---:|---:|
| 2024-07-01 | 2,364 | 2,364 | **100.0000%** | 0 | 0 | 29.27% |
| 2025-01-15 | 2,817 | 2,817 | **100.0000%** | 0 | 0 | 28.36% |
| 2025-10-17 | 2,502 | 2,502 | **100.0000%** | 0 | 0 | 21.70% |
| 2026-04-01 | 2,752 | 2,752 | **100.0000%** | 0 | 0 | 27.47% |
| 2026-08-07 | 2,341 | 2,341 | **100.0000%** | 0 | 0 | 25.89% |

Exactly one-to-one, both directions, on every day tried.

**Decision D2: the per-unit table carries BOTH keys.** `unit_key` is the
backend's identity and every `dealer_direction` frame is keyed on it, so
dropping it would break the audit trail back to the ladder. `package_id` is the
join key the front end actually uses. Storing one and deriving the other at
read time would put the `n_legs <= 1` branch in a SQL `CASE` on the web tier,
which is precisely where it would be got wrong.

This was worth measuring on day one: every table key, API contract and grid
join in the rest of this work would have been built on the wrong column.

### G-2. The curve store is warm for the whole window

`USD-SOFR-1D-CITIVELOEXCELMIN` and `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` each hold
**659 day-partitions over 2024-07-01 .. 2026-08-07 with zero weekday gaps**
(`C:\Users\chris\AppData\Local\ARBS\Cache\curve_store\raw`). Directory
presence is not a content test; the runner reports a priced fraction per day
and the pilot below is the real check.

### G-3. A day costs 57 s, not the 180 s the estimates implied

Pilot on **2026-04-01**, chosen because `LEDGER.md` pins it: 4,329 eligible
flow legs, 100% priced.

| | |
|---|---|
| units | 2,752 (= the display view's row count for that day, exactly) |
| kept by `universe` | 2,098 |
| priced, no failure | **2,098 — all of them** |
| KRD rows | 58,520 = **28.0 per unit**, i.e. every pillar is non-zero |
| wall | **57 s** single process |

The backend's own numbers were 115 s repricing + 65 s key-rate = 180 s. The
difference is that those were measured separately, each paying its own curve
acquisition; run together against a fully warm minute store, with the
projector taking the repricer's own pricer, the day costs a third of the sum.

**610 days therefore cost ~9.7 h single-process, and ~1.2 h at 8 workers**
(32 cores, 64 GB on this box).

### D3. Store the ten-bucket roll-up, not the 28 pillars

28.0 KRD rows per unit is not a sampling artefact — rateslib's delta is
sensitivity to every calibrating instrument, so a single 5y swap has a
non-zero entry at all 28. Across the tape that is ~35 M rows.

`arbs_dd_unit_bucket_v1` stores the **`TENOR10` roll-up** instead (~12 M
rows), because:

* no published number needs more. `ladder.aggregate`, `indicator.daily_levels`
  and every column of `arbs_dd_ladder_v1` are computed from `TENOR10` rows, so
  the roll-up is a **sufficient statistic for the whole published surface** —
  the re-aggregation insurance the pillar frame would buy is already bought;
* the front end reads a ten-bucket profile, never a pillar;
* the pillar frame is written un-lossy to parquet on `D:` by `price` anyway,
  which is where any future pillar question is answered — and it is a local
  file the web tier could not reach in any case.

No dust threshold is applied. The backend measured that an absolute floor of
0.05 USD/bp removes 53% of rows and that one of them was 95.4% of its own
unit's risk; only exact zeros are dropped.

### D4. Two stages, split on the cost line

`price` (per day, parallel, ~57 s/day) writes parquet. `publish` (whole
window, one process, minutes) writes Postgres. A defect in the calibration,
any of the three rules, the ladder or the indicator is repaired by re-running
`publish` — not by re-pricing for a day.

`price` runs from **2024-03-01**, `publish` from `indicator.SAMPLE_FLOOR`
(**2024-07-01**). The tau calibration is a trailing 60-day window that must end
*strictly* before the day it calibrates, so a calibrated first published day
needs a quarter of priced history in front of it. Those ~85 days are priced
and never published.

### D5. The calibration is refitted, not borrowed

`dd_nb`'s default mode unpickles `D:\dd_signals_cache\s2_pos\calibrations.pkl`.
That pickle exists and is usable, but its fits stop at **2025-08-22** — it was
built for s2's design window — so it cannot serve a window ending 2026-08-07.
`publish` refits `probability.rolling_calibrations` over its own priced
deviations with the same parameters the backend used (60-day window, 1-day
minimum gap, 5-day step) and picks, per day, the most recent fit whose window
ends strictly before that day.

`D:\dd_signals_cache\s2_pos` also holds **371 days** of already-priced units,
KRD and coverage from the backend work, 288 of them inside this window. They
are **not** reused: s2's population is SOFR-only, flow-only and has no
package-price branch (`s2_positioning.py:283`), so reusing it would silently
narrow the published product to a different question. It is kept as an
independent cross-check on the overlapping days instead.

### G-4. `if nan:` is `True`, and it excluded every package unit

The first `publish` run stopped on its own guard:

```
RuntimeError: 2024-07-01: 15 coverage leg(s) belong to a unit with no reason;
the coverage accounting would not sum
```

Probes `ddfe04_coverage_orphans.py` and `ddfe05_reason_nan.py`. The first
ruled out the obvious explanation: the two frames agree on **2,364 unit keys
with zero orphans in either direction**, so `.map()` was not missing a key — it
was mapping to a NaN.

The cause: `pkg_exclusion` is only ever assigned on a `PKG` unit. On a day
where no package is refused, no row assigns it, and
`DataFrame.reindex(columns=UNIT_COLS)` creates it as an **all-NaN `float64`**
column. Parquet round-trips that as `float64`, `r.get("pkg_exclusion")` returns
`nan` — and **`bool(nan)` is `True`**. So

```python
if r.get("pkg_exclusion"):        # fires on EVERY package unit
    out["exclusion"] = r["pkg_exclusion"]   # ... with the reason `nan`
```

Every package-price unit was marked excluded, with a reason that is neither a
reason nor a null.

**It had no symptom of its own.** The units would have shipped as abstentions
with a blank tooltip; the ladder would have been quietly short 15 units a day;
the coverage percentage would have been slightly wrong in the direction that
flatters nothing in particular. It surfaced only because the coverage
accounting is required to be a partition and refuses a unit with no reason.

Fixed by `_s()` — one reader for every string field coming back out of the
stage cache — plus two assertions that state the invariant rather than relying
on the next guard downstream: `classify_day` refuses a non-string exclusion,
and `publish_day` refuses a non-string reason. Pinned by
`test_a_string_field_that_came_back_as_nan_reads_as_absent`, which asserts
`bool(nan) is True` alongside it so the premise is in the test rather than in a
comment, and by a test that reproduces the parquet round-trip rather than
asserting it from memory.

### G-5. The calibration is the only slow thing in `publish`, so it is cached

Measured: **22 rolling fits over 112 priced days cost ~14 minutes** (longer
with 8 pricing workers competing for the CPU). The full 610-day window is ~120
fits, i.e. a couple of hours of mixture MLEs.

That would have taken back the whole point of splitting `price` from
`publish`. `build_calibrations` now caches to
`D:\ddfe_cache\calibrations\<key>.pkl`, keyed on the **day list, the fit
parameters and the deviation count** — not the window bounds, so a day
re-priced after a code change keeps its place in the list, changes the count,
and misses the cache. That is the direction this particular error has to fall.
`--refresh-calibration` forces a refit.


