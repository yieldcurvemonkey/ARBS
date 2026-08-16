# ARBS storage migration — C: → D:

**Status: IN PROGRESS** (this file is rewritten as each stage completes)
**Started:** 2026-08-15 19:15 · **Branch:** `chore/storage-d-drive` · **Worktree:** `C:\Users\chris\clee\ARBS-stor`

---

## The situation found

| drive | total | free at start |
|---|---|---|
| `C:` | 951 GB | **11.9 GB**, and it fell to **1.98 GB** during the session |
| `D:` | 466 GB | 268.5 GB |

The single largest ARBS consumer on `C:` was **`C:\Users\chris\AppData\Local\ARBS` — 151.1 GB
across 173,346 files**. Everything else ARBS owned on `C:` came to roughly 23 GB more.

Two things were also found running that had to be dealt with before anything moved:

- An **orphaned, hung `pytest` fast gate** (PID 21788, started 19:04, parent already dead,
  0 CPU over an 8-second sample, 698 MB resident, 137 threads). Killed. This is the known
  `test_not_signed_in_means_keep_waiting` hang.
- The **ERIS live curve daemon** (running continuously since 2026-08-11) plus three
  scheduled tasks. See *Environment changes* below.

---

## What moved, and how

### Mechanism 1 — NTFS junction (out-of-repo stores)

| source | destination | size | status |
|---|---|---|---|
| `C:\Users\chris\AppData\Local\ARBS` | `D:\ARBS_DATA\appdata` | 151.1 GB / 173,346 files | ⏳ copying |
| `C:\sdr_cache` | `D:\ARBS_DATA\sdr_cache_root` | 0.274 GB / 377 files | ✅ **verified** |
| `C:\Users\chris\clee\mbo_cache` | `D:\ARBS_DATA\mbo_cache` | 0.852 GB / 33 files | ✅ **verified** |

"Verified" means the tree was re-read *through the junction* after the move and its file
count, byte total, and an MD5 over the sorted `(relpath, size)` manifest all matched the
pre-migration capture exactly.

**Why a junction and not `ARBS_CACHE_DIR`.** This is the one decision worth reading. The
repo's cache-root ladder is `ARBS_CACHE_DIR` → `platformdirs.user_cache_dir` →
`LOCALAPPDATA`, and for four stores **the first rung does not point where the second rung
points**:

| store | `$ARBS_CACHE_DIR` branch | where the data actually is |
|---|---|---|
| `MDP/IRSwaps/fixings_cache/fixings_cache.py:153` | `$E\fixings_cache\<curve>_fixings` | `…\ARBS\MDP\IRSwaps\ARBS\MDP\IRSwaps\Cache\fixings_cache\…` |
| `MDP/USMoneyMarkets/dbnomics_fetcher.py:32` | `$E\dbnomics_cache\<slug>` | `…\ARBS\MDP\USMoneyMarkets\…\Cache\dbnomics_cache\…` |
| `BT/serff/futures_data.py:42` | `$E\eod_settles` | `…\ARBS\BT\serff\ARBS\BT\serff\Cache\eod_settles` |
| `MDP/IRSwaps/BARCHART_STIRF/rl.py:1630` | `$E\IRSwaps\BARCHART_STIRF\curve_cache` | `…\ARBS\Cache\diskcache\dump\BARCHART_STIRF-RL_CURVE_CACHE` |

(The doubled path segments are real — those call sites use `user_cache_dir(appname="ARBS/MDP/IRSwaps")`
without `appauthor=False`, so platformdirs inserts the appname twice.)

Setting `ARBS_CACHE_DIR` — the obvious one-line fix — would have aimed those four caches at
directories that have never held a byte. Nothing errors. Each simply refetches over the
network, for hours, while every log line reports a successful migration.
**`ARBS_CACHE_DIR` is therefore deliberately left unset.**

### Mechanism 2 — environment variable (repo-relative stores)

A junction **must not** be used inside a git worktree: `git clean -xfd` and
`git worktree remove` delete straight through a reparse point on Windows and would take the
real data on `D:` with them. These resolve through the new `utils/storage_paths.py` instead.

| store | size | status |
|---|---|---|
| `notebooks/sdr/_cache/trade_tape` | 10.26 GB / 4,553 files | ⏳ pending |
| `data/ts` | 8.98 GB / 1,921,019 files | ⏳ pending |
| `sdr_cache` | 2.49 GB / 12,325 files | ⏳ pending |
| `BT/signals/_ustf_basis_cache` | small | ⏳ pending |

`notebooks/sdr/_cache/trade_tape` alone is **94% of the entire 10.91 GB `notebooks/` tree**,
and it is written by `SDRUtils/analytics/trade_tape.py` — a library module reaching sideways
out of `SDRUtils/` into the notebook tree.

---

## Code changes

Commit `3f5cb2e1` on `chore/storage-d-drive`, 10 files.

**New — `utils/storage_paths.py`.** Precedence: the store's own variable →
`$ARBS_DATA_ROOT/<same relative path>` → `<repo>/<same relative path>`. **With no variable
set the answer is the historical repo-relative path**, so an unconfigured checkout — including
all ~60 sibling worktrees, which run older code — behaves exactly as before. There is
deliberately no "use `D:` if the drive exists" branch: a store that changes location because
a drive was mounted is a store that silently rebuilds cold.

| file | change |
|---|---|
| `Caching/computed_timeseries_store.py:17` | `data/ts` → `repo_store(…, env_var="ARBS_COMPUTED_TS_DIR")` |
| `SDRUtils/analytics/trade_tape.py:121` | trade-tape pickles → `repo_store(…, env_var="ARBS_TRADE_TAPE_CACHE")` |
| `BT/signals/ustf_basis.py:228` | basis panels → `repo_store(…)` |
| `SDRUtils/dealer_direction/lineage.py:120` | `"./dd_lineage_store"` → `repo_store(…)` |
| `scripts/tape_v3_backfill.py:25` | hardcoded worktree path → `repo_store(…)` |
| `scripts/_dtcc_probe.py:19` | hardcoded worktree path → `repo_store(…)` |
| `notebooks/sdr/_usd_swaps_common.py:113` | `"C:/sdr_cache"` → `D:\ARBS_DATA\sdr_cache_root` |
| `notebooks/exploratory/sr3_mbo_explorer.py:82` | `C:\…\clee\mbo_cache` → `D:\ARBS_DATA\mbo_cache` |
| `docs/storage_layout.md` | new — the full rationale |

Two of these fix defects that had nothing to do with the drive:

- **`dd_lineage_store` defaulted to `"./dd_lineage_store"`** — CWD-relative, so launching from
  any directory but the repo root silently started a *fresh, empty* lineage sidecar.
- **`tape_v3_backfill.py` and `_dtcc_probe.py` hardcoded one worktree's absolute path**, so a
  run from any other worktree wrote into `ARBS` rather than its own tree.

---

## Deliberately NOT changed

- **`MDP/FixedRateBonds/reference_data_cache/`** — named "cache", but **tracked in git**.
  Moving it would delete tracked files.
- **`Caching/DiskCacheMixin.py`** — the only store that ignores `ARBS_CACHE_DIR` entirely. Its
  bytes are already relocated by the junction, so adding the env branch would cold-start one
  notebook's cache fork for **zero** storage benefit. Logged in `docs/storage_layout.md`
  instead, along with a second latent inconsistency in the same resolver: its platformdirs
  branch (line 51) yields `…\ARBS\Cache\diskcache` while its `LOCALAPPDATA` fallback (line 54)
  yields `…\ARBS\diskcache` — no `Cache` segment.
- **`C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache`** (`SDR_CACHE_DIR`) —
  another project's cache; ARBS only reads it. Not mine to migrate.
- **Sibling worktree caches** under `clee\ARBS-*` and `ARBS\.claude\worktrees\*` — each owns
  its own copy and keeps working on old code. Duplication across ~60 worktrees is real and
  worth a separate pass; it is not touched here.
- **`ARBS_DUCKDB_PATH`** is dead for the main consumer (`ComputedTimeseriesStore` always
  passes an explicit `db_path`, short-circuiting it). Recorded, not fixed.

---

## Still reclaimable (measured, not acted on)

| path | size | note |
|---|---|---|
| `ARBS\Caching\dump` | 0.83 GB / 60 files | legacy ZODB `.fs` files; current code uses the AppData `diskcache` root |
| `ARBS\.cache` | 0.52 GB / 5,371 files | a fork of the canonical cache root, created by one notebook that sets `ARBS_CACHE_DIR` to it |
| `notebooks\backtests\irswaps_pca_regression_rv\.cache` | 145 MB | duplicate `curve_store` fork |
| `notebooks\logs` | 132 MB | gitignored |
| `notebooks\timeseries\.cache` | 32 MB | orphaned SDR CFTC fork |
| Recycle Bin | 5.18 GB | not emptied — that is the user's call |

---

## Environment changes (restore these if you undo the migration)

- `ARBS-CacheWarmer-Daily` — **disabled** (was Ready)
- `ARBS-CacheWarmer-WeekendBackfill` — **disabled** (was Ready)
- `ARBS-ErisLiveCurve-Intraday` — process stopped; the task itself **could not be disabled**
  ("Access is denied" via both `Disable-ScheduledTask` and `schtasks` — it is registered with
  privileges this session does not hold). It re-triggers roughly every 10 minutes and has
  restarted on its own. Harmless: it writes through the junction to `D:`.
- Prior state recorded in `scratchpad\scheduled_tasks_before.json`.

---

## Rollback

Each junction is a single reparse point, and the data on `D:` is the only copy after the husk
is removed. To undo one:

```powershell
Remove-Item 'C:\sdr_cache' -Force          # removes the LINK only, never the target
robocopy 'D:\ARBS_DATA\sdr_cache_root' 'C:\sdr_cache' /E /MOVE /MT:16
```

`Remove-Item` on a junction deletes the link, not the target — but **`git clean -xfd` and
`git worktree remove` do not make that distinction**, which is exactly why no junction was
placed inside a worktree.

To undo the code side: revert commit `3f5cb2e1` and unset `ARBS_DATA_ROOT`. With the variable
unset the code resolves to the historical repo-relative paths on its own.
