# ARBS tape `_v3` generation — design

**Date:** 2026-08-08
**Branch:** `feat/tape-v3-generation` (worktree `../ARBS-v3`)
**Status:** design, approved for planning

## Problem

The ARBS USD-swaps trade tape (`arbs_usd_swap_tape_*_v2`) is no longer written by ARBS.

Since **2026-07-23 03:30 UTC** the sole writer is a cron job on the host `sky`
(`run_swaptape`, `/home/peter/SwapPulse`, `sdr-monitor/run_swaptape_cron.sh`), stamping
`producer = 'swappulse_port'`. ARBS's own pipeline last wrote the tape on 2026-07-22 18:06 UTC.
That writer serves a different front end and must keep running.

The rows it produces are missing every enrichment ARBS added over the last year. Measured
fill rate on `arbs_usd_swap_tape_legs_v2`, split by writer:

| producer | rows | `ptp_group_id` | `special_tenor_type` | `event_timestamp` | `matched_ust_maturity` |
|---|---|---|---|---|---|
| `NULL` (ARBS, → 2026-07-23) | 2,247,794 | 53.9% | 100% | 100% | 100% |
| `swappulse_port` (2026-07-23 →) | 76,008 | **0%** | **0%** | **0%** | **0%** |

So the ARBS dashboard — which reads `arbs_usd_swap_tape_display_v2` — has been serving
degraded data for as_of 2026-07-21 → 2026-08-07: no PTP package grouping, no MMS /
special-tenor labels, no UST aliases, no execution-vs-event report lag.

Two writers cannot share one table. ARBS needs its own generation.

## Goal

Stand up an ARBS-owned `_v3` tape generation, backfill it over the full history with current
logic, and point the ARBS dashboard at it. Leave `_v2` entirely to `sky`.

Decisions taken (2026-08-08):

- **Backfill depth:** full 611 days, 2024-03-01 → 2026-08-07.
- **v2 writes:** ARBS stops writing `_v2` entirely. No dual-write.
- **Ongoing feed:** out of scope. Backfill only; cadence is a follow-up.

## Measured context

| Fact | Value | Why it matters |
|---|---|---|
| Tape v2 span | 611 days, 2024-03-01 → 2026-08-07 | Backfill range |
| Tape v2 volume | 2,323,802 legs / 1,447,960 packages, 7.6 GB | v3 roughly doubles it |
| DB total | 211 GB | +7.6 GB is ~3.6%, not a constraint |
| Overrides / notes / manual links | **0 / 0 / 1** | No package_id remap problem — the usual blocker for this migration does not exist |
| Raw source | `dtcc_sdr_fetcher.fetch_historical_reports()` — DTCC daily reports over the network, cached to local parquet | The 104 GB `sdr_data` Postgres table is SwapPulse's store and is **not** used by ARBS |
| Warm parquet cache | 643 days, 2023-12-01 → 2026-07-21, 0.48 GB at `sdr_cache/CFTC/RATES/` | Covers the whole range bar ~13 tail days; the run is compute-bound, not download-bound |
| Tape stage throughput | avg 57.3 s/day over 6,306 successful runs | ~9.7 h for 611 days, **tape stage alone** — classification is on top and unmeasured |
| Dashboard coupling | 92 literal table references across 43 files | The migration surface |

## Design

### 1. Generation seam

The v1 → v2 cutover was done by copying `_tape_schema.py` to `_tape_schema_v2.py`. Repeating
that would create a third hand-synced copy of a 30 KB DDL — and that DDL has *already* drifted
(live `_v2` carries a `producer` column that exists nowhere in ARBS's DDL or git history).

Instead, parameterise the generation. `TAPE_SCHEMA_SQL_V2` is already an f-string interpolating
its table-name constants, so repointing the constants emits v3 objects from unchanged DDL text.

New `SDRUtils/_swappulse_scripts/_tape_tables.py`:

```python
TAPE_GENERATION = "v3"          # the ARBS-owned tape generation

def _t(base: str) -> str:
    return f"arbs_usd_swap_{base}_{TAPE_GENERATION}"

PACKAGES_TABLE         = _t("tape_packages")
LEGS_TABLE             = _t("tape_legs")
RUNS_TABLE             = _t("tape_ingestion_runs")
DISPLAY_VIEW           = _t("tape_display")
OVERRIDES_TABLE        = _t("tape_overrides")
OVERRIDE_MEMBERS_TABLE = _t("tape_override_members")
OVERRIDE_HISTORY_TABLE = _t("tape_override_history")
NOTES_TABLE            = _t("tape_notes")
VWAP_TABLE             = _t("vwap_daily")
SIGNAL_TABLE           = _t("tape_signal")
```

`_tape_schema_v2.py` is renamed `_tape_schema_current.py` and sources its constants from
`_tape_tables`. `_tape_schema.py` (v1) is left untouched.

**Writer guard.** Every write path asserts the target generation is not `v2`:

```python
def assert_writable_generation() -> None:
    if TAPE_GENERATION == "v2" and os.getenv("ARBS_ALLOW_V2_WRITES") != "1":
        raise RuntimeError(
            "Refusing to write the _v2 tape: it is owned by the `sky` run_swaptape job. "
            "Set ARBS_ALLOW_V2_WRITES=1 to override."
        )
```

Called from `ingest_usdswaps_tape.ensure_schema()` and before each bulk write. This makes
clobbering `sky` impossible by default rather than a matter of discipline — which is the
property that was missing when the two writers first collided.

**Python literal sweep.** Repointing the constants is necessary but not sufficient — the tree
carries hardcoded `_v2` strings that no constant change reaches. Sweep
`arbs_usd_swap_tape_\w+_v[12]` across the Python tree and route every hit through
`_tape_tables`. Known hits:

| Location | Nature |
|---|---|
| `ingest_usdswaps_tape.py:545-562` — `_LATEST_MIGRATION_COLS` | **Blocker, see below** |
| `_tape_monitoring_v2.py:18,50` — `arbs_usd_swap_tape_quality_daily_v2` view over `tape_legs_v2` | Monitoring view; needs a v3 sibling |
| `stir_flow/trade_selection.py:34-35,47-48` | Reader — STIR dealer-flow joins legs+packages |
| `stir_flow/unwinds.py:42,49` | Reader — lineage probe |

**`_LATEST_MIGRATION_COLS` is a hard blocker, not a cosmetic literal.** That list feeds
`_schema_already_current()`, which short-circuits `ensure_schema()` when the named columns
exist. The columns are checked *by name only*, against whichever tables the tuples name — and
they name `_v2`. Since sky's `_v2` tables carry every one of those columns (they are present but
NULL), `_schema_already_current()` returns `True`, `ensure_schema()` skips all DDL, and the v3
tables are never created. `ensure_schema()` is on the hot path — called at
`ingest_usdswaps_tape.py:2175` on every single run — so this fails on day one of the backfill.
The tuples must derive their table names from `_tape_tables`.

The two `stir_flow` modules are readers, so moving them is a deliberate scope call rather than a
mechanical rename: they should read v3, since v3 is the corrected data and the STIR dealer-flow
work is exactly the kind of analysis the missing `ptp_group_id` distorts.

### 2. Dashboard seam

New `SDRUtils/dashboard/src/lib/tape-tables.ts` exporting the same names from its **own**
`TAPE_GENERATION = 'v3'` constant.

The two constants are deliberately independent, not a shared environment variable. Flipping the
*reader* back to `v2` — to inspect what `sky` is producing — must never resurrect ARBS *writes*
to v2. A single shared switch couples the two failure modes; two constants do not. A constant
rather than an env var also means a missing variable cannot silently point the dashboard at the
wrong generation.

All 92 literals across 43 files become imports, **tests included** — a test pinning `_v2` would
keep passing while production was broken. `TAPE_DISPLAY_VIEW` in
`app/api/usd-swaps-tape-v2/route.logic.ts` becomes a re-export for compatibility.

Two of the 92 are `_v1`, not `_v2`: `features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts:76`
and `app/api/usd-swaps-tape-v2/packages/route.logic.ts:15`, both referencing
`arbs_usd_swap_tape_packages_v1`. A blanket find-and-replace would silently change their
behaviour from "read the frozen v1 rollback table" to "read v3". Decide each on purpose — most
likely they are stale and should move to v3, but that is a judgement, not a rename.

**Flip timing.** Because the backfill runs newest-first, the dashboard can be pointed at v3 once
the recent days have landed — it does not have to wait for the 2024 tail. Flipping early is also
the strongest end-to-end check available.

### 3. Objects in the generation

All ten objects above are created with the `_v3` suffix.

Two deliberate exclusions:

- **`arbs_usd_swap_manual_links_v2`** stays unversioned. It is keyed by its own UUID, holds one
  row, and is referenced by the classification stage, which is not being versioned. Its single
  row points at a v2 `package_id` and will dangle after the backfill — delete it.
- **Classification tables** (`arbs_usd_swap_legs_v2`, `arbs_usd_swap_packages_v2`) stay on v2.
  They are ARBS-only; `sky` does not write them, so there is no conflict to resolve.

### 4. DDL parity check

The live `_v2` tables have drifted from ARBS's DDL string. Creating v3 from that DDL may
therefore omit columns the ingest actually writes — which fails silently, as a column that is
never inserted looks identical to a column that is always NULL.

After creating v3, assert three column sets agree:

1. v3's actual columns, from `information_schema`
2. live v2's columns, minus `producer`
3. the column list the ingest's `INSERT` statements build

Any column in (2) or (3) absent from (1) is a silent data-loss bug and fails the migration.

**The check is itself validated against a known answer:** `producer` must appear in set (2) and
in neither (1) nor (3). A parity check that does not flag `producer` is broken and its "pass" is
meaningless.

### 5. Backfill

Sequence:

1. **Freeze the code.** Commit, record the SHA in the ledger. Editing pipeline code mid-backfill
   silently splits the output into two logic vintages with no marker distinguishing them.
2. **Pilot three days** — 2026-08-06 (recent), 2025-06-02 (mid), 2024-03-04 (earliest). The
   early date is the real test: it exercises whether ERIS EOD curves reach back to 2024-03 at
   all. Risk pricing depends on them, and their absence is the most likely cause of a failed
   2024 tail.
3. **Extrapolate** the true per-day cost from the pilot — the 57.3 s/day figure covers the tape
   stage only — and confirm the total before committing to the full run.
4. **Bulk run**, newest → oldest, so the ARBS front end becomes correct within the first hour
   rather than the last. Day-by-day, resumable, ledger-first, `--continue-on-error`.
5. **Second pass** over ledger rows marked failed.

Backfill invocation per day:

```
python -m SDRUtils._swappulse_scripts.run_usdswaps_pipeline backfill \
    --date YYYY-MM-DD \
    --cache-path C:\Users\chris\clee\ARBS\sdr_cache
```

`backfill` defaults to `--ignore-cache` and `--no-tape-cache`, so bug-fix deploys actually take
effect — which is what makes this a genuine re-derivation rather than a copy.

**`--cache-path` is mandatory, not optional.** `_resolve_cache_path()`
(`ingest_usdswaps.py:1078`) falls back to `./sdr_cache` *relative to the current working
directory*. Run from the `ARBS-v3` worktree with defaults and it resolves to an empty
directory: the 643 warm parquet days are invisible, all 611 days re-download from DTCC, and the
classification cache rebuilds from nothing. The failure is silent — it looks like a slow run,
not a misconfiguration. Pin the path to the primary checkout's cache (or export
`SDR_CACHE_PATH`).

**Ordering is safe.** Newest-first would be wrong if cross-day enrichment read earlier tape days
back out of the database, because those days would not exist yet in v3. It does not: the `xd_*`
columns are resolved from `raw_df` — raw DTCC data, fetched with the window extended one day
*forward* to catch follow-up lifecycle events (`ingest_usdswaps_tape.py:2184`,
`usd_swaps.py:1662`). The only cross-day input is raw and forward-looking, so descending order
introduces no dependency on unwritten days. `prev_enriched` is service-loop in-memory state and
is not passed by `backfill`.

Incidental repair: as_of **2026-07-24** currently holds 799 legs against 3.3–5.5k on every other
trading day, because the `sky` job never ran its 07-26 batch and only ever writes T−2. The
backfill rebuilds that day in full.

### 6. Error handling

- **Writer-generation guard** (§1) — the primary protection for `sky`.
- **`_assert_risk_populated`** (PR #344) is retained. A transient curve failure yields all-NaN
  pv01, and without this guard NULL risk is published as a successful run.
- **Per-day isolation.** A failing day writes a ledger row and does not stop the run.
- **v2 non-interference proof.** Note that v2 is *not* frozen — sky writes it nightly, and the
  backfill runs for many hours, so row counts and `max(created_at)` on v2 will legitimately move
  during the run. Snapshotting them and asserting "unchanged" would fail the first night for the
  right reason and teach nothing.

  The property that actually matters is that every v2 row written during the backfill came from
  sky, not from us. Record `backfill_start` as a UTC timestamp, then assert:

  ```sql
  SELECT count(*) FROM arbs_usd_swap_tape_legs_v2
  WHERE created_at > :backfill_start
    AND (producer IS DISTINCT FROM 'swappulse_port');   -- must be 0
  ```

  Same for `_packages_v2`. This is robust to sky's off-pattern catch-up runs, and it is the
  evidence that sky was never touched — the absence of an error is not that evidence.

### 7. Testing

- New unit tests: the seam resolves every name from `TAPE_GENERATION`; the guard raises on
  `"v2"` and passes on `"v3"`.
- Python fast gate:
  `python -m pytest tests -m "not slow and not network and not db"`, invoked through the env
  interpreter directly. Parallel `conda run` invocations collide on a temp file and return
  empty output with exit 0 — a fake pass.
- Dashboard: `npm test` only. Plain `npx jest` bypasses the ESM mocks and produces false
  Supabase failures.
- Local verification in Chrome MCP before any deploy.

### 8. Acceptance criteria

1. v3's distinct `as_of_date` set equals v2's **restricted to `as_of_date <= 2026-08-07`** —
   611 days. The restriction is load-bearing: sky keeps writing v2 throughout the backfill, so
   an unrestricted comparison starts failing the moment sky publishes as_of 2026-08-10.
2. Enrichment markers, stated as two separate thresholds so the test is decidable:
   - corpus-wide, `ptp_group_id` fill ≥ 50% (ARBS baseline on v2 is 53.9%);
   - on **every individual day**, `ptp_group_id` fill > 0%, and `special_tenor_type`,
     `event_timestamp`, `matched_ust_maturity` each ≥ 99%.

   These are precisely the markers sitting at 0% in v2 today, so the test discriminates the
   thing the migration exists to fix. Per-day PTP fill varies with how much package trading
   occurred, which is why only the corpus-wide figure carries a 50% floor.
3. as_of 2026-07-24 holds a full day's legs, not 799.
4. Zero rows in `arbs_usd_swap_tape_legs_v2` or `_packages_v2` written after `backfill_start`
   carry a `producer` other than `'swappulse_port'` (see §6).
5. Dashboard renders v3 locally; `npm test` and the Python fast gate are green.

## Out of scope

- Ongoing v3 freshness (scheduled task or service loop) — explicitly deferred.
- Fixing or altering the `sky` job. It keeps running, unmodified.
- Versioning the classification tables.
- Dropping the `_v1` tape tables (84 MB, harmless).

## Risks

| Risk | Mitigation |
|---|---|
| ERIS EOD curves do not reach 2024-03 → 2024 tail unpriceable | Pilot 2024-03-04 **before** the bulk run; if it fails, shorten the range and say so rather than publishing NULL risk |
| v3 DDL misses a drifted column → silent data loss | Three-way parity check, validated against `producer` as a known answer |
| `_schema_already_current()` short-circuits on v2's columns → v3 tables never created | Derive `_LATEST_MIGRATION_COLS` table names from `_tape_tables` (§1); pilot proves the tables exist before the bulk run |
| Backfill run from the worktree resolves an empty `./sdr_cache` → 611 days re-download, silently | `--cache-path` pinned to the primary checkout (§5); pilot timing would expose it |
| A code edit lands mid-backfill → two logic vintages, unmarked | Freeze and record SHA; ledger stores the SHA per day |
| Backfill accidentally targets v2 | Writer guard, plus the producer-scoped non-interference proof (§6) |
| Long run dies partway | Day-by-day ledger, resumable, second pass; run in background and verify by process, not by log tail — a log frozen at a traceback usually means the process is alive with a block-buffered stdout |
