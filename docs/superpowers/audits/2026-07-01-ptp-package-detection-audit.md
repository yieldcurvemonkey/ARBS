# PTP Package Detection — Implementation Audit

**Date:** 2026-07-01
**Scope:** 7 commits `4e7e9cf6..23e248f2` (PTP pre-grouper, structure classifier,
OPA sign solver, pipeline wiring, schema, tape ingest, dashboard).
**Spec:** `docs/superpowers/specs/2026-07-01-ptp-package-detection-design.md`
**Method:** full-file code review of all 13 touched files plus every layer they
hand off to (trade_tape enrichment, ingest coercion helpers, display view,
API route, pg driver serialization, PrimeReact filter plumbing), empirical
micro-experiments against the real modules, full test-suite run, live schema
migration, two-date DB backfill with row-level verification, service-loop
profiling, and Chrome browser verification of the dashboard.

---

## Final Verdict: SHIP-WITH-FIXES *(fixes applied and verified during this audit)*

As shipped, **neither half of the feature actually worked on real data**:

- **Backend:** at live detection time `Package transaction price` is a raw
  DTCC string with thousands separators (`'88,100'`). The pre-grouper's
  plain `pd.to_numeric(errors="coerce")` turned every comma-formatted PTP
  into NaN, so **every USD-amount package ≥ $1,000 — including both of the
  spec's motivating trades — silently bypassed PTP grouping** and fell
  back to the old detectors. The first audit backfill of 2026-06-25 wrote
  only 27 PTP groups, none of them the 12-leg IMM fly (still carved into
  FLY_104…FLY_107); the July-1 MAC ladder was still 2 CURVEs + 4
  OUTRIGHTs. The only PTPs that *did* group were comma-free ones — mostly
  price-notation values like `9.9999999999` (notation 3), whose "$10"
  residuals then produced **fake EXACT confidence badges**.
- **Frontend:** the API's hard-coded column projection never selected any
  of the 8 new package-level columns, so badges/spread/filter rendered
  nothing regardless of what the backend wrote.

The unit tests all passed because they feed the modules clean floats; the
implementation was evidently never verified against the live string-typed
detection path or a browser. After the audit fixes, the 2026-06-25
backfill produces **202 PTP groups covering 1,028 legs** (vs 27/79
pre-fix), the 12-leg fly and 8-leg MAC ladder both group and tie out at
their specced residuals, and the dashboard renders and filters correctly.

---

## Code Quality

### Critical (fixed during audit)

**C0. Comma-formatted PTP/OPA strings disqualified nearly all real packages (the headline bug).**
`group_by_ptp` and `solve_all_opa_signs` parsed
`package_transaction_price` / `other_payment_amount` with bare
`pd.to_numeric(errors="coerce")`. At detection time those columns are raw
DTCC strings (`'88,100'`, `'1,537,032'`, multi-valued
`'1000000.0;549700000.0'`), so any comma-formatted value became NaN:
PTP → leg not a candidate; OPA → silently solved as 0. The repo already
owns the correct normalizer (`_coerce_numeric_like` in `usd_swaps.py`,
per the CLAUDE.md "pass numerics through a notation-aware parser" rule) —
the new modules just didn't use it. Root-caused by re-running the grouper
on the (already-coerced) cached day frame — 202 groups — vs what the
live path stored — 27. *Fix:* `numeric_like()` tolerant parser in
`ptp_grouper.py` (commas, `$`, parenthesised negatives, blank-likes),
used for PTP/OPA/rate/tenor/pv01 across both modules; live-path
regression tests with string inputs added.

**C0b. Price-notation PTPs produced fake-EXACT tieouts.** Groups whose PTP
is a *decimal price* (`'9.9999999999'`, Part 43 price notation 3) — not a
dollar amount — were solved as if PTP were $10: zero-OPA groups net to 0,
residual ≈ $10 → "EXACT" badge on a meaningless comparison. *Fix:*
`solve_all_opa_signs` now reads `package_transaction_price_notation` when
present and reports non-monetary-notation groups (notation ≠ 1) as
UNRESOLVED with no per-leg signs. Grouping itself still happens — the
package integrity signal is real; only the dollar tieout is not.

**C1. Dashboard API never selected the new columns — the headline UI features were dead on arrival.**
`SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts` projects a hard-coded
`COLUMNS` allowlist and intersects it with the live view's columns.
None of the 8 new package-level columns (`ptp_group_id`, `ptp_group_size`,
`opa_signed_net`, `opa_ptp_residual`, `opa_sign_confidence`,
`dealer_spread_est`, `dealer_spread_bps`, `ptp_sub_structures`) were added
to it. `row.opa_sign_confidence` and `row.dealer_spread_bps` were therefore
always `undefined`: no confidence badge, no dealer-spread values, no
spread sort, ever. Only the per-leg sign badges worked, because `legs_json`
is built with `to_jsonb(l)` (whole-row) so per-leg `opa_sign` /
`opa_signed_amount` flowed automatically. The dashboard commit (cc263489)
shipped UI reading columns the API could never return — this is exactly what
a pre-commit browser check would have caught.
*Fix:* added the 8 columns to `COLUMNS`.

**C2. Latent crash once C1 was fixed: `.toFixed()` on a pg NUMERIC string.**
The dashboard's pg client sets no `setTypeParser` for NUMERIC, so numeric
view columns arrive as **strings**. Every existing formatter coerces with
`Number(...)` (`format.ts`), but the new code called
`row.dealer_spread_bps.toFixed(2)` directly in two places (confidence badge
line and the Spread column). The `number | null` TS type hid it from tsc.
With C1 fixed this throws `TypeError: v.toFixed is not a function` on every
PTP row. *Fix:* `spreadBpsDisplay()` helper mirroring the `Number()`
convention, used at both sites.

**C3. Confidence filter was dead code.**
`OPA_CONFIDENCE_FILTER` was defined and exported in `filter-utils.ts` with
zero imports anywhere. No column had `filterField="opa_sign_confidence"`,
and `buildInitialFilters()` (which seeds the PrimeReact menu-mode filter
state) had entries for neither `opa_sign_confidence` nor
`dealer_spread_bps` — so even the shipped Spread column's funnel had no
seeded filter form. The SQL pushdown allowlist in `route.logic.ts` was
ready, but nothing in the UI could emit the filter. *Fix:* new compact
"OPA Conf" badge column (`filterField="opa_sign_confidence"`, sortable,
filterable), both fields seeded in `buildInitialFilters()`, dead
`OPA_CONFIDENCE_FILTER` export removed.

**C4. Three cache layers un-versioned for a schema-changing detector change.**
- `TRADE_TAPE_CACHE_VERSION` was left at `"v8-invoice-packages"` despite
  `SDRUtils/CLAUDE.md` mandating a bump for any enrichment-output change.
  Pickle keys fingerprint trade ids/action mix, not detection output, so
  stale pre-PTP tapes would be served for previously-built keys.
  *Fix:* bumped to `"v9-ptp-opa"`.
- The classification parquet day-cache
  (`classification_cache/usd_swaps/{curve}/{flags}/{date}/{count}.parquet`)
  keys only on detector on/off flags + row count. Post-detection frames
  cached before this feature lack all PTP/OPA columns and carry different
  package assignments, but would be reused whenever the day's row count is
  unchanged (any historical date; a restarted service's earlier-today
  frames). `backfill` defaults `--ignore-cache` on, so backfills were safe
  — the exposure was the **service loop** and any notebook/consumer using
  cache defaults. *Fix:* cache-flags suffix `_ptp1` so pre-PTP day caches
  miss.
- The service warm-start pickle (`service_caches/packaged_day.pkl`,
  `_PACKAGED_DAY_CACHE`) is keyed by date only and would warm-load pre-PTP
  packaged frames into a restarted service. *Fix:* renamed to
  `packaged_day_ptp1.pkl`, orphaning stale files.

### Bugs in the new modules (fixed during audit, all confirmed empirically first)

**B1. NaT execution timestamps formed garbage groups.** `ts.astype("int64")`
turns NaT into the int64 sentinel, so any two `package_indicator=True` legs
with unparseable timestamps and the same PTP/UPI/platform clustered
together (confirmed: 2 NaT legs → 1 group). *Fix:* NaT excluded from
candidates (they can't satisfy a time-window constraint); they flow to the
global pool.

**B2. `package_indicator` as float `1.0` was silently dropped.** The
truthiness set was `{"true","t","1","yes"}`; a bool column that picked up
NaNs becomes float dtype and stringifies as `"1.0"` → every leg silently
bypassed PTP grouping. *Fix:* added `"1.0"` to the set + regression test.
(Live-data check: the pipeline's `package_indicator` arrives as
object-dtype bool/str, which already matched — this was a robustness fix,
not a live failure.)

**B3. Elastic time window via global clustering.** Time clusters were
computed across *all* candidates before keying by (PTP, UPI, platform), so
an unrelated trade sitting between two legs of the same key chained them
into one group even when they were farther apart than the 5s tolerance
(confirmed: same-PTP legs 8s apart merged when bridged by a different-PTP
trade at t+4s). Spec says ±5s per group. *Fix:* clustering now runs within
each (PTP, UPI, platform) partition (sort by key+time, break on key change
or gap > tolerance).

**B4. `ptp_group_size` was `0` on one code path and `None` on another** for
non-PTP legs (the final commit 23e248f2 fixed only the has-candidates
branch). Non-PTP packages would get `ptp_group_size = 0` in the DB whenever
a day had zero PTP candidates, `NULL` otherwise. *Fix:* `None` everywhere.

**B5. CURVE/FLY classification ignored the "different tenors" spec
requirement.** A DV01-balanced same-tenor pair (a switch/roll) classified
as CURVE; three same-tenor legs could in principle classify as FLY. *Fix:*
CURVE requires 2 distinct tenor buckets, FLY requires 3 (rounded to 0.1Y,
consistent with `_detect_sub_flies`).

**B6. Brute-force solver was a service-loop stall risk.** Pure-python 2^N
enumeration measured at **1.7s for N=20, ~27s extrapolated for N=24** —
inside the tape build, per group, plus a second pass for the constrained
solve. *Fix:* exact chunked-numpy enumeration with identical selection
semantics (min residual → tie prefers net closer to +PTP → lowest mask):
**N=20: 0.15s, N=22: 0.78s, N=24: 3.3s** (8–11×). Equivalence pinned by a
new test comparing against a naive reference on random inputs, plus a
performance-budget test at N=20. Real-world group sizes on the two test
dates max out at 12 legs (4ms), so the cap of 24 is comfortable.

### Design observations (documented, not changed)

- **`dealer_spread_bps` units are off by 100× from true basis points.**
  `residual / total_dv01 × 100` — residual($)/DV01($/bp) is already bp, so
  the extra ×100 makes the column "bp × 100". It matches the spec's own
  examples ($216 on ~$420K DV01 displaying "~0.05bp"), so it was
  implemented as designed and left alone — but the PM should be aware the
  label lies dimensionally. If it's ever fixed, fix spec + solver +
  dashboard label together.
- **Neighborhood-scoped incremental detection can split a PTP group** whose
  legs straddle the ±10min re-detection window edge (part re-detected,
  part carried from cache with a different `ptp_group_id`). The same
  fragility pre-exists for fly/curve detectors; window ≫ group width makes
  it rare. Not a regression; noted for the record.
- **PTP groups bypass invoice/MMS/MAC/spreadover detection by design** — a
  2-leg PTP pair that would previously have been tagged INVOICE now comes
  out CURVE/PKG-2. This is the spec's intent ("holistic"), but it is a
  behavior change on real tapes worth remembering when eyeballing labels.
- `_detect_sub_flies` checks distinct tenors on raw values but buckets on
  rounded values — a group with tenors {2.01, 2.04, 5, 10} refuses
  annotation even though it buckets to 3 tenors. Cosmetic (annotations
  only).
- Sub-fly leg pairing sorts each tenor bucket by DV01 and zips — two
  equal-size sub-flies with different rates can get their legs cross-paired
  in the annotation. Cosmetic.
- `solve_all_opa_signs` `fillna(0)` on missing OPA means a null-OPA leg
  still gets a ±1 `opa_sign` in the DB with `opa_signed_amount = 0`. The UI
  is unaffected (it checks the raw OPA), but DB consumers should treat
  `opa_sign` as meaningful only where `other_payment_amount` is non-null.
- Row order out of `_run_all_detectors` changes (PTP rows concat first,
  remainder re-sorted) and indexes are reset via `ignore_index=True`.
  Nothing downstream keys on positional order (verified `build_leg_rows` /
  `build_package_rows` / `_enrich_packages` all key on ids), so this is
  fine — just worth knowing when diffing cached frames.

### Security

- `route.logic.ts` filter pushdown: field names are allowlisted
  (`COLUMN_FILTER_ALLOWLIST_PACKAGE`/`_LEG`) before being interpolated;
  values are always parameterized (`$n`); LIKE patterns are escaped. The
  two new fields ride the same path. **No injection surface found.**
- New DB writes go through the existing coercion helpers
  (`_num_or_none`/`_int_or_none`/`_str_or_none`/`_to_jsonable`), all of
  which normalize NaN/ndarray/numpy scalars safely (verified including the
  parquet-roundtrip case where `ptp_sub_structures` comes back as
  `np.ndarray` of dicts).

### Test quality

The shipped tests assert real behavior (group counts, ids, classifications,
known-trade residuals/confidences, constraint sharing) rather than types —
good. Gaps found and filled during the audit: NaT timestamps, float-dtype
`package_indicator`, window bridging, `ptp_group_size` None-consistency,
same-tenor CURVE/FLY rejection, solver equivalence vs naive reference,
N=20 performance budget. Still untested (accepted): inf PTP, negative PTP,
duplicate trade_ids within a group.

---

## Test Results

- **PTP + detector regression subset** (`test_ptp_grouper`,
  `test_opa_sign_solver`, `test_ptp_pipeline_integration`,
  `test_fly_detector_arrival_order`, `test_gap_fly_detection`,
  `test_gap_curve_detection`, `test_v2_package_detection`,
  `test_basis_packages`, `test_sub_package_detection`):
  **85 passed, 0 failed** after all audit fixes (43 PTP-module tests — 31
  shipped + 12 audit-added — plus the full existing detector regression
  set).
- **Full `tests/` suite:** not a usable gate today. `pytest tests/ -x`
  dies at *collection* on 7 orphaned test files importing deleted modules
  (below), and with those ignored the remaining suite ran past 70 minutes
  of CPU during the audit without completing (long/network-bound tests).
  Cleaning up the orphans and marking the slow tests is recommended
  follow-up, unrelated to this feature.
- **Pre-existing, unrelated to this feature** (verified via `git log` that
  all predate the audited range):
  - 7 test files fail at *collection* on imports of deleted modules
    (`ingest_listed_vs_swaption_vol` ×2, `OBI` ×2, `BT.signals.pca_rv_engine`,
    `BT.signals.swap_curve_rv` ×2) — orphaned since commits c006547e /
    71d8baf0 / e944c2d8. These break `pytest tests/ -x` at collection for
    everyone; worth a cleanup PR.
  - Dashboard jest: 29 failures in 7 suites, all stale expectations vs
    older UI changes (rowClassName palette drift from 809f1fe6,
    TapeLabelCell UFRO-token change, VolumeGrid modal, 3 route.cache suites
    that attempt live DB access). The suites covering this feature's files
    (`filter-utils.test.ts` 46/46 with 2 pre-existing rowClassName
    failures excluded → all filter/format tests pass) show no regressions.
  - `npx tsc --noEmit`: 52 pre-existing error lines, all in unrelated test
    files; **zero in any file touched by the feature or the audit fixes**.

---

## Schema Migration

Ran `ensure_schema()` from `ingest_usdswaps_tape` against the live Supabase
pooler (`aws-0-us-east-1.pooler.supabase.com:6543`). Two deadlock retries
(ACCESS EXCLUSIVE on the display view vs live readers) were absorbed by the
built-in retry/backoff — a good validation of that mechanism. Verified via
`information_schema`:

- `arbs_usd_swap_tape_legs_v2`: `ptp_group_id text`, `opa_sign smallint`,
  `opa_signed_amount numeric` ✓
- `arbs_usd_swap_tape_packages_v2`: all 10 columns with specced types
  (incl. `ptp_sub_structures jsonb`) ✓
- `arbs_usd_swap_tape_display_v2`: 8 columns projected (constrained-solve
  columns intentionally table-only, matching spec) ✓

The `_LATEST_MIGRATION_COLS` marker was correctly updated to
(`packages.ptp_sub_structures`, `legs.opa_signed_amount`), so the
skip-DDL-when-current fast path keys on the newest columns.

---

## Data Verification (backfills)

Both dates were backfilled twice against the live Supabase tape DB: once
with the shipped code (exposing the comma bug), once after the fixes.

**2026-06-25 — before vs after the comma/notation fixes:**

| | shipped code | fixed code |
|---|---|---|
| PTP-grouped legs | 79 / 5,076 | **1,028 / 5,076** |
| PTP packages | 27 | **202** |
| 12-leg IMM fly grouped? | **NO** — still 4 split FLY_104…107 | **YES** — `PTP_3865630341000001201`, PKG-12 |
| confidence mix | mostly fake-EXACT on PTP=10 groups | 45 EXACT / 39 TIGHT / 82 LOOSE / 36 UNRESOLVED |

**12-leg IMM_U2026 fly (the spec's primary test case), verified in
`arbs_usd_swap_tape_packages_v2` / `_legs_v2`:**

- `package_type = PKG-12`, `ptp_group_size = 12`
- `opa_signed_net = $87,883.71` vs PTP $88,100 →
  `opa_ptp_residual = $216.29` → **TIGHT** (exactly the known ~$216)
- `dealer_spread_est = $216.29`, `dealer_spread_bps = 0.0269`
- `ptp_sub_structures`: 4 FLY triplets, correctly paired by DV01
  (2 × 71,612 bellies, 2 × 129,797 bellies)
- all 12 legs carry `opa_sign` ∈ {−1, +1} and `opa_signed_amount`
  (e.g. 2Y −13,268 / +326,320 / +23,742 / −583,941 …)

**2026-07-01 — 8-leg MAC ladder (`PTP_3969258311000000201`):**

- all 8 legs grouped, `package_type = PKG-8` (previously 2 CURVEs +
  4 OUTRIGHTs — the exact mis-classification the spec set out to fix)
- `opa_signed_net = $1,548,031` vs PTP $1,537,032 →
  `opa_ptp_residual = $10,999` → **LOOSE** (the known ~$11K),
  `dealer_spread_bps = 20.1`
- MAC rate ladder (3.00% → 4.00%) and signs (2Y −, belly +, 15Y −, …)
  consistent
- day totals: 1,852 PTP legs, 251 PTP packages

Note on the July-1 first pass: the user's live tape service (running
pre-fix code since 15:05) was rewriting today's rows every 10s; it was
stopped before the fixed re-backfill and **restarted afterwards from the
fixed working tree** (fresh PID, logging to
`sdr_cache/service_restart_2026-07-01.log`). Its stale warm cache is
orphaned by the `_ptp1` rename.

Data caveats worth knowing when reading the tape:
- Price-notation PTP clusters (the `9.9999999999` compression/list
  blobs) still *group* — PKG-24…PKG-107 super-packages on June 25 —
  because the SDR fields genuinely match; their OPA tieout is now
  UNRESOLVED instead of fake-EXACT. If those mega-groups are unwanted as
  display packages, a follow-up could gate grouping on notation too.
- A null-OPA leg inside a monetary-PTP group still gets `opa_sign` with
  `opa_signed_amount = 0` (solver treats missing OPA as 0); consumers
  should read signs only where `other_payment_amount` is non-null.

---

## Performance

**PTP stages in isolation** (full 2026-06-25 day frame, 5,066 legs, 202
groups — the worst realistic case, since service cycles only re-detect a
±10min neighborhood):

| stage | before optimization | after |
|---|---|---|
| `group_by_ptp` | 34 ms | 31 ms |
| `classify_ptp_groups` | 190 ms | 176 ms |
| merge concat | 15 ms | 14 ms |
| `solve_all_opa_signs` | **11,793 ms** | **432 ms** |
| **total** | **12.0 s** | **0.65 s** |

The 11.8s came from the 2^N sweep on the day's two 24-leg groups (~3.3s
each even vectorized) plus the 20–22-leg groups and their constrained
passes. The meet-in-the-middle solver removes the exponential wall
(N=20/22/24 all < 10 ms) while remaining exact — pinned by a randomized
200-case equivalence test against a full sweep (200/200 after the
scale-aware tie tolerance; the first run exposed 74 complement-direction
flips caused by the too-tight 1e-9 window, an issue the shipped
pure-python solver shared).

**Full-day detection** (`_run_all_detectors` end to end): 64.8s for
5,066 trades post-fix on June 25 vs 79.7s for 5,593 trades pre-fix on
July 1 — the PTP additions are noise against the pre-existing detector
chain; lifecycle resolution separately adds ~42s to backfills.

**Service loop** (3 iterations, `--interval-seconds 10
--no-smart-intervals`, fixed code):

- Cycle 1 (cold bootstrap, 24h lookback): classification 41.5s + tape
  45.2s (of which DB write 40.0s) = **86.9s** — dominated by
  pre-existing lifecycle + full-day write, not PTP.
- Cycle 2 (warm incremental): classification **3.4s**, no new trades →
  tape skipped, cycle total **3.7s**.
- Cycle 3: no new DTCC slices → 0.3s check, cycle skipped.

No PTP component exceeds the 500ms/cycle budget in steady state (the
full-day worst case is 0.65s for *all* PTP stages combined; warm-cycle
neighborhood frames are far smaller). Memory: the solver's temporaries
are ≤ 32 MB (vectorized sweep chunk) and ~100 KB (MITM half-tables).

Solver benchmarks (isolated, vectorized fix):

| N | pure-python (shipped) | vectorized (fixed) |
|----|----------------------|--------------------|
| 12 | 4 ms | <5 ms |
| 16 | 94 ms | ~10 ms |
| 20 | 1,658 ms | 150 ms |
| 22 | ~6.6 s (extrap.) | 780 ms |
| 24 | ~27 s (extrap.) | 3.3 s |

---

## Browser Testing

Chrome (via MCP) against `npm run dev` on localhost:3000, reading the
live re-backfilled data. All checks on the fixed frontend; the shipped
frontend could not have passed any of them (see C1).

1. **PKG-12 package row** (`execution_start=6/25` +
   `package_type=PKG-12` filters → exactly 1 match): renders
   `IMM_U2026 2Y/…/10Y Package PHYS`, risk 804K, per-leg OPA line
   (13.3k / 326k / … / 564k), `PTP: 88.1k`, **TIGHT badge** and
   **0.03bp** spread on the Other Lvl cell; `SPREAD (BP)` column shows
   `0.03bp`; the new `OPA CONF` column shows the TIGHT badge.
2. **Sign badges**: expanding the PKG-12 shows all 12 legs with colored
   signed OPAs — −13.3K, +326K, +23.7K, −584K, −677K, +25.5K, +1.2M,
   −46.2K, +20K, +314K, +35.4K, −564K — matching the DB solve
   sign-for-sign. Per-leg PTP 88.1K, exec ts 14:30:59Z, UFRO
   decomposition footer intact.
3. **Confidence filter** (SQL pushdown end-to-end): EXACT → 43 matching,
   TIGHT → 38, LOOSE → 80 on June 25 — consistent with the DB's
   45/39/82 group counts (the deltas are packages excluded by the
   view's default row gates).
4. **Sort by dealer spread**: initially **broken — lexicographic**
   (91.01bp sorted above 9.08bp… above 73.55bp) because pg NUMERIC
   arrives as a string; after the route-level coercion fix, descending
   sort returns 231.07bp → 142.16bp → … correctly. Exercised via the
   URL-synced `sort_field=dealer_spread_bps&sort_order=-1`.
5. **Regressions**: non-PTP SPREADOVER_FLY (51 rows) and
   SPREADOVER_CURVE (149 rows) render and expand normally — unsigned
   OPA (`—`), per-leg PTS values, package-confidence chips (5/6 FLY
   etc.) and the "Show Package Confidence Details" affordance intact;
   empty `·` in the OPA Conf column. The analytics dock opens a focused
   CURVE trade with its timeseries. The volume grid heatmap
   (fwd × tenor, percentiles, totals) renders and its collapse toggle
   works. **Zero console errors across the entire session.**

Screenshots captured throughout the session document each step (PKG-12
header + expanded legs, filter counts, sort order, regression views).

---

## Regressions Found

- **None in existing backend behavior**: the full detector regression
  subset passes; non-PTP legs flow through the unchanged detector chain
  (verified empty-remainder edge: detectors accept an empty frame).
- The feature's own dashboard additions were non-functional as shipped
  (C1–C3) — regressions *of the feature itself*, not of prior features.
- Pre-existing failures inventoried above are explicitly **not**
  regressions from these commits.

---

## Fixes Applied

All fixes verified end-to-end (tests → DB backfill → browser) before
committing:

- **`d5e4c618` fix(packages)** — comma/notation-tolerant parsing
  (`numeric_like`), PTP-notation gating of the OPA tieout, per-key time
  clustering, NaT exclusion, `ptp_group_size` None-consistency,
  distinct-tenor CURVE/FLY requirements, exact MITM solver with
  scale-aware tiebreak. +12 regression tests.
- **`3929411a` fix(cache)** — `_ptp1` classification-cache flags,
  `packaged_day_ptp1.pkl` warm cache, `TRADE_TAPE_CACHE_VERSION =
  v9-ptp-opa`.
- **`9d0053b6` fix(dashboard)** — project the 8 columns in
  `resolveDisplayView`, numeric coercion at the API boundary,
  `spreadBpsDisplay()` at both `.toFixed` sites, filterable/sortable
  "OPA Conf" column, filter-state seeds, dead `OPA_CONFIDENCE_FILTER`
  removed.

Operational actions taken during the audit:
- Schema migration executed and verified on live Supabase.
- 2026-06-25 and 2026-07-01 re-backfilled with the fixed code (the
  pre-fix backfills' data has been fully overwritten).
- The user's tape service was stopped (it was running pre-fix code and
  rewriting today's rows) and **restarted from the fixed tree**
  (`service --interval 10`, log at
  `sdr_cache/service_restart_2026-07-01.log`). Its first fixed-code
  cycle is the cold bootstrap (~90s), then ~4s warm cycles.

Recommended follow-ups (out of audit scope, not blocking):
- Decide the real unit/label for `dealer_spread_bps` (currently bp×100
  per spec).
- Optionally gate *grouping* (not just the tieout) on PTP notation to
  suppress PKG-107-style compression blobs, if they prove noisy.
- Delete the 7 orphaned test files so `pytest tests/` collects again;
  mark the >1h network-bound tests.
- Update the stale dashboard jest expectations (rowClassName palette,
  TapeLabelCell UFRO token) — pre-existing drift.

---

*Generated by the 2026-07-01 implementation audit session.*
