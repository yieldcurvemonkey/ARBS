# ARBS storage migration — C: → D:

**2026-08-15 · branch `chore/storage-d-drive` → merged as PR #463 (`d1253fd5`)**

## Result

| | before | after |
|---|---|---|
| `C:` free | **11.9 GB** of 951 GB (hit **0.48 GB** mid-session) | **155.1 GB** |
| `D:` free | 268.5 GB of 466 GB | 67.8 GB |

**~143 GB returned to the system drive.** Every store was verified after moving — see
*Verification* below. Two items remain outstanding and are described honestly at the end.

---

## What was found

The largest ARBS consumer on `C:` was **`C:\Users\chris\AppData\Local\ARBS` — 162 GB across
173,314 files**. (An early scan reported 151 GB; that was a lower bound — a
`Directory.EnumerateFiles` walk that aborts on its first unreadable entry.) Roughly 23 GB more
sat inside the repo.

Two things were running that had to be handled first:

- An **orphaned, hung `pytest`** (PID 21788, parent already dead, 0 CPU across an 8-second
  sample, 698 MB resident). Killed — this is the known `test_not_signed_in_means_keep_waiting`
  hang.
- The **ERIS live-curve daemon** (running since 2026-08-11) and three scheduled tasks.

---

## Mechanism 1 — NTFS junctions (out-of-repo stores)

| source | → destination | size | status |
|---|---|---|---|
| `…\AppData\Local\ARBS\Cache\curve_store` | `D:\ARBS_DATA\appdata\Cache\curve_store` | 74,900 files | ✅ |
| `…\Cache\ust_future_store` | mirrored | 19,024 files | ✅ |
| `…\Cache\swaption_cube_store` | mirrored | 2,702 files | ✅ |
| `…\Cache\{duckdb_ts, central_bank_dates, citivelo_par_extract, forex_factory_calendar, forex_factory_calendar_store, MDP, Query, zodb}` | mirrored | 4,264 files | ✅ |
| `…\ARBS` (citivelo_excel) | mirrored | 32,087 files | ✅ |
| `…\{BT, MDP, excel-scratch}` | mirrored | 472 files | ✅ |
| `C:\sdr_cache` | `D:\ARBS_DATA\sdr_cache_root` | 0.27 GB / 377 files | ✅ |
| `C:\Users\chris\clee\mbo_cache` | `D:\ARBS_DATA\mbo_cache` | 0.85 GB / 33 files | ✅ |

### Why a junction and not `ARBS_CACHE_DIR`

This is the decision worth reading. The cache-root ladder is `ARBS_CACHE_DIR` →
`platformdirs.user_cache_dir` → `LOCALAPPDATA`, and **for four stores the first rung does not
point where the second rung points**:

| store | `$ARBS_CACHE_DIR` branch | where the data actually is |
|---|---|---|
| `MDP/IRSwaps/fixings_cache/fixings_cache.py:153` | `$E\fixings_cache\<curve>_fixings` | `…\ARBS\MDP\IRSwaps\ARBS\MDP\IRSwaps\Cache\fixings_cache\…` |
| `MDP/USMoneyMarkets/dbnomics_fetcher.py:32` | `$E\dbnomics_cache\<slug>` | `…\ARBS\MDP\USMoneyMarkets\…\Cache\dbnomics_cache\…` |
| `BT/serff/futures_data.py:42` | `$E\eod_settles` | `…\ARBS\BT\serff\ARBS\BT\serff\Cache\eod_settles` |
| `MDP/IRSwaps/BARCHART_STIRF/rl.py:1630` | `$E\IRSwaps\BARCHART_STIRF\curve_cache` | `…\ARBS\Cache\diskcache\dump\BARCHART_STIRF-RL_CURVE_CACHE` |

The doubled segments are real: those call sites use `user_cache_dir(appname="ARBS/MDP/IRSwaps")`
without `appauthor=False`, so platformdirs inserts the appname twice.

Setting `ARBS_CACHE_DIR` — the obvious one-line fix — would have aimed those four caches at
directories that have never held a byte. **Nothing would error.** Each would refetch over the
network, for hours, while every log line reported a successful migration. A junction cannot do
that: it is byte-identical by construction.

**`ARBS_CACHE_DIR` is deliberately left unset.**

### Why the junctions are one level down

The original plan was a single junction at `…\AppData\Local\ARBS`. That rename was refused. A
lock probe walked the tree and localised the blocker to exactly one child — `Cache\diskcache`,
a SQLite `FanoutCache` held open for the lifetime of whichever process opened it. On Windows an
open *file* does not block renaming its parent; only a handle on the *directory* does, which is
why the probe was conclusive rather than a guess.

So the junctions sit on each child instead. This is exactly as transparent to callers —
`platformdirs` still returns `…\ARBS\Cache\curve_store`, and that path still resolves to `D:`.

---

## Mechanism 2 — environment variable (repo-relative stores)

A junction **must not** go inside a git worktree: `git clean -xfd` and `git worktree remove`
delete straight through a reparse point on Windows and would take the real data with them.
These resolve through the new `utils/storage_paths.py`.

Precedence: the store's own variable → `$ARBS_DATA_ROOT/<same relative path>` →
`<repo>/<same relative path>`. **With nothing set the answer is the historical repo-relative
path**, so the ~60 sibling worktrees running older code are unaffected.

| store | size | status |
|---|---|---|
| `notebooks/sdr/_cache/trade_tape` | 10.26 GB / 4,553 files | ✅ verified (count + bytes exact) |
| `sdr_cache` | 2.49 GB / 12,325 files | ✅ verified (hash-sampled, 41 files incl. the largest) |
| `BT/signals/_ustf_basis_cache` | 4 files | ✅ verified |
| `data/ts` | 8.98 GB / 1,921,159 files | ⏳ **running** (see below) |

Set at **User** scope:

```
ARBS_DATA_ROOT        = D:\ARBS_DATA\repo
ARBS_COMPUTED_TS_DIR  = C:\Users\chris\clee\ARBS\data\ts     # temporary pin — remove when data\ts lands
ARBS_CACHE_DIR        = (deliberately unset)
```

The `ARBS_COMPUTED_TS_DIR` pin matters: without it `ARBS_DATA_ROOT` would point the
computed-timeseries store at an empty `D:` directory, which reads as a cold cache rather than
an error. **Delete that variable once `data/ts` finishes moving.**

---

## Verification

A baseline was captured **before** anything moved and re-run afterwards, comparing *contents*
rather than paths (a junction resolves to `D:`, so paths are expected to change):

- **all 31 curves** present, each with its date count and first/last date unchanged
  (e.g. `USD-SOFR-1D-CITIVELOEXCEL` 5,510 dates, 2005-01-03 → 2026-08-13)
- `swaption_cube_store` — 2,702 dates, 2015-10-08 → 2026-08-12
- `ust_future_store` — 12,327 snapshot files + 6,697 basis reports
- DuckDB — 5,654 rows / 19 symbols
- frozen trees (`C:\sdr_cache`, `mbo_cache`) — MD5 over the sorted `(relpath, size)` manifest
  **identical** before and after, read *through* the junction

The comparator raised exactly one item — `repo_sdr_cache: VANISHED` — which is the intended
move of `<repo>/sdr_cache` to `D:` with no junction left behind. Everything else matched.

Both the comparator and the robocopy residual checker were themselves tested against inputs
whose answers were known, which caught a real defect: **the residual check was reading the
`Total` column of robocopy's summary instead of `Copied`**, and so declared a byte-perfect
12,325-file copy a total failure. Independent hashing proved the copy good; the checker was
wrong. It now reads `Copied`/`Failed` and is verified against a known-good copy, a
deleted-file case, and a truncated-file case.

---

## Code (PR #463)

`utils/storage_paths.py` (new) plus 10 call sites. `tests/test_storage_paths.py` — 7 tests,
**verified by mutation**: injecting the "guess `D:` if the drive exists" branch the module
deliberately refuses to have turns 4 of them red.

Two defects fixed that had nothing to do with the drive:

- **`dd_lineage_store` defaulted to `"./dd_lineage_store"`** — CWD-relative, so launching from
  anywhere but the repo root silently started a *fresh, empty* lineage sidecar.
- **`ingest_usdswaps` / `ingest_usdswaptions` defaulted to `"./sdr_cache"`** — same failure
  mode, on the SDR tape. (`.env` also carries `SDR_CACHE_PATH=NONE`; nothing calls
  `load_dotenv` today, but if a shell ever exported it the old code would have created a
  directory named `NONE`. Now treated as unset.)
- `tape_v3_backfill.py` / `_dtcc_probe.py` hardcoded one worktree's absolute path.

### Test gate

`8,311 passed, 1 failed`. The failure —
`test_citivelo_read_path_perf.py::test_fixings_kwargs_resolve_once_per_wrapper` — is
**pre-existing**: a clean `origin/main` worktree with none of these changes fails the identical
test (`8,394 passed, 1 failed`). It passes in isolation and with its own file, so it is a
full-suite ordering effect that predates this work.

---

## Outstanding

**1. `Cache\diskcache` — 27.31 GB, still on `C:`. Recommendation: leave it there.**

It was blocked by a directory handle held by one of the two VS Code Jupyter kernels open since
19:44, and killing that would have discarded the user's notebook state. But the arithmetic has
since changed the answer from "finish it later" to "don't":

**`D:` is now the tighter drive.** `C:` has ~155 GB free; `D:` has ~50 GB. And `D:` costs more
per byte than the logical size suggests — 1.92 M tiny files in `data/ts` consumed ~14 GB for
8.98 GB of data, about **1.6×**, because each file rounds up to a whole cluster. Moving another
27 GB across would leave `D:` near 20 GB while `C:` sat above 180 GB. That is the original
problem with the drives swapped.

So this is only worth doing if `C:` gets tight again. If it does, restart the kernels, add
`'Cache\diskcache'` to the `$children` list in `<scratchpad>\appdata_swap_children.ps1` (it was
omitted precisely because it was locked), and re-run — the script skips whatever is already
junctioned.

Note for whoever restarts those kernels: they also captured the old repo-relative `data/ts`
constant at import time, so a notebook cell writing computed-timeseries *after* the move would
write into a fresh empty `C:` tree. Restart them before touching that store from those
notebooks.

**2. `data/ts` — 8.98 GB / 1.92 M files, migration launched and running.** It was blocked
earlier by the same kernels and freed up later. The script copies, verifies a zero residual, and
only then deletes the staging tree; if it reports `MISMATCH`, the staging copy is intact and the
rollback is a single `Rename-Item` printed in its output. **Check
`<scratchpad>\data_ts_move.log`, then delete the `ARBS_COMPUTED_TS_DIR` variable.**

---

## Deliberately not changed

- **`MDP/FixedRateBonds/reference_data_cache/`** — named "cache" but **tracked in git**.
- **`Caching/DiskCacheMixin.py`** — the only store ignoring `ARBS_CACHE_DIR`. Its bytes move
  with the junction, so adding the env branch would cold-start a notebook's cache fork for zero
  storage benefit. Two latent inconsistencies in that resolver are logged in
  `docs/storage_layout.md` instead, along with `ARBS_DUCKDB_PATH` being dead for its main
  consumer.
- **`project-oasis\private\sdranalytics\.cache`** — another project's cache; ARBS only reads it.
- **Sibling worktree caches** under `clee\ARBS-*` and `ARBS\.claude\worktrees\*` — ~60 of them,
  each owning its own copy. Real duplication, worth a separate pass, untouched here.

## Still reclaimable (measured, not acted on)

| path | size | note |
|---|---|---|
| `ARBS\Caching\dump` | 0.83 GB | legacy ZODB `.fs` files; current code uses the AppData `diskcache` root |
| `ARBS\.cache` | 0.52 GB | cache-root fork created by one notebook that repoints `ARBS_CACHE_DIR` |
| `notebooks\backtests\irswaps_pca_regression_rv\.cache` | 145 MB | duplicate `curve_store` fork |
| `notebooks\logs` | 132 MB | gitignored |
| Recycle Bin | 5.18 GB | not emptied — the user's call |

## Environment changes made and restored

`ARBS-CacheWarmer-Daily` and `ARBS-CacheWarmer-WeekendBackfill` were disabled during the
migration and are **re-enabled** (next runs 2026-08-17 18:15 and 2026-08-22 10:00).
`ARBS-ErisLiveCurve-Intraday` could not be disabled at all ("Access is denied" via both
`Disable-ScheduledTask` and `schtasks` — it is registered with privileges this session did not
hold); its process was stopped for the cutover and it has since **restarted on its own** and is
running, writing through the junctions to `D:`.

One untracked file of the user's —
`MDP/FixedRateBonds/reference_data_cache/…/2026-08-14/2026-08-14.parquet` — blocked the
fast-forward pull into the primary checkout. It was **byte-identical (SHA-256) to the version
already committed on `main`**, so it was backed up to
`<scratchpad>\user_untracked_backup\` and removed. Nothing was lost.

## Rollback

`Remove-Item` on a junction deletes the link, not the target:

```powershell
Remove-Item 'C:\Users\chris\AppData\Local\ARBS\Cache\curve_store' -Force
robocopy 'D:\ARBS_DATA\appdata\Cache\curve_store' 'C:\Users\chris\AppData\Local\ARBS\Cache\curve_store' /E /MOVE /MT:16
```

But `git clean -xfd` and `git worktree remove` make no such distinction — which is why no
junction was placed inside a worktree. For the code: revert `d1253fd5` and unset
`ARBS_DATA_ROOT`; with the variable gone the resolver returns the historical paths on its own.
