# Storage layout: which drive holds what, and why

`C:` is a 951 GB system drive. On 2026-08-15 it was down to **1.98 GB free**.
`D:` is the data drive. Everything ARBS persists now lives on `D:`.

Two mechanisms move the data. They are different on purpose, and the reason is
the whole point of this document.

---

## 1. Stores under `%LOCALAPPDATA%\ARBS` — moved by an NTFS junction

```
C:\Users\chris\AppData\Local\ARBS   ──junction──▶   D:\ARBS_DATA\appdata
```

**151 GB, 173,346 files.** This one junction relocates every store that resolves
through the repo's cache-root ladder — `curve_store`, `ust_future_store`,
`swaption_cube_store`, `duckdb_ts`, `diskcache/dump` (~25 named caches),
`citivelo_excel`, `fixings_cache`, `dbnomics_cache`, `cash_spline_cache`,
`roll_spline_cache`, `central_bank_dates`, `forex_factory_calendar*`,
`citivelo_par_extract`, `zodb`, and the serff `eod_settles`.

### Why a junction and not `ARBS_CACHE_DIR`

The obvious move is to set `ARBS_CACHE_DIR=D:\...` and be done. **Do not.** The
ladder is `ARBS_CACHE_DIR` → `platformdirs.user_cache_dir` → `LOCALAPPDATA`, and
for four stores the first rung does not point where the second rung points:

| store | file | `$ARBS_CACHE_DIR` branch | platformdirs branch (where the data actually is) |
|---|---|---|---|
| fixings cache | `MDP/IRSwaps/fixings_cache/fixings_cache.py:153` | `$E\fixings_cache\<curve>_fixings` | `…\ARBS\MDP\IRSwaps\ARBS\MDP\IRSwaps\Cache\fixings_cache\…` |
| DBnomics | `MDP/USMoneyMarkets/dbnomics_fetcher.py:32` | `$E\dbnomics_cache\<slug>` | `…\ARBS\MDP\USMoneyMarkets\…\Cache\dbnomics_cache\…` |
| SERFF settles | `BT/serff/futures_data.py:42` | `$E\eod_settles` | `…\ARBS\BT\serff\ARBS\BT\serff\Cache\eod_settles` |
| BARCHART_STIRF curves | `MDP/IRSwaps/BARCHART_STIRF/rl.py:1630` | `$E\IRSwaps\BARCHART_STIRF\curve_cache` | `…\ARBS\Cache\diskcache\dump\BARCHART_STIRF-RL_CURVE_CACHE` |

The doubled path segments are real: those call sites use
`user_cache_dir(appname="ARBS/MDP/IRSwaps")` without `appauthor=False`, so
platformdirs inserts the appname twice.

Setting `ARBS_CACHE_DIR` would therefore point those four caches at directories
that have never held a byte. Nothing would error. Each would simply rebuild —
network refetches measured in hours — while every log line said the migration
succeeded. A junction cannot do that: it is byte-identical by construction, and
all four ladders still resolve through it.

`ARBS_CACHE_DIR` is deliberately **left unset** at machine scope. Note that
`notebooks/backtests/risk_premia_pairs_pca_backtest.ipynb:176` sets it to
`<repo>/.cache` for its own kernel; that is a local fork and stays that way.

### Known inconsistencies, left alone

- `Caching/DiskCacheMixin.py:47` is the **only** store that ignores
  `ARBS_CACHE_DIR` entirely. Its bytes are relocated by the junction, so this
  was not worth changing — adding the env branch would cold-start the notebook
  fork above for zero storage benefit.
- In that same resolver the platformdirs branch (line 51) yields
  `…\ARBS\Cache\diskcache` while the `LOCALAPPDATA` fallback (line 54) yields
  `…\ARBS\diskcache` — no `Cache` segment. They disagree. Only the first is
  reached today.
- `ARBS_DUCKDB_PATH` (`Caching/duckdb_timeseries_cache.py:64`) is dead for the
  main consumer: `ComputedTimeseriesStore` always passes an explicit `db_path`,
  which short-circuits it. The live DuckDB index is the one inside `data/ts`;
  the copy under `…\Cache\duckdb_ts` is stale (last written 2026-03-19).

---

## 2. Repo-relative stores — moved by an environment variable

A junction **must not** be used inside a git worktree. `git clean -xfd` and
`git worktree remove` delete straight through a reparse point on Windows and
would take the real data on the far side with them.

So these resolve through `utils/storage_paths.py`:

```python
from utils.storage_paths import repo_store
CACHE = repo_store("data", "ts", env_var="ARBS_COMPUTED_TS_DIR")
```

Precedence: the store's own variable → `$ARBS_DATA_ROOT/<same relative path>` →
`<repo>/<same relative path>`. **With no variable set the answer is the
historical repo-relative path**, so an unconfigured checkout — including all
~60 sibling worktrees, which run older code — behaves exactly as before.

The layout under `$ARBS_DATA_ROOT` mirrors the layout under the repo. That makes
a migration a plain directory move and leaves the two trees diffable afterwards.

| store | relative path | own variable | size |
|---|---|---|---|
| trade tape pickles | `notebooks/sdr/_cache/trade_tape` | `ARBS_TRADE_TAPE_CACHE` | 10.26 GB / 4,553 files |
| computed timeseries | `data/ts` | `ARBS_COMPUTED_TS_DIR` | 8.98 GB / 1.92 M files |
| SDR tape cache | `sdr_cache` | `ARBS_SDR_CACHE_DIR` | 2.49 GB / 12,325 files |
| UST futures basis panels | `BT/signals/_ustf_basis_cache` | — | small |
| dealer-direction lineage | `dd_lineage_store` | `DD_LINEAGE_STORE` | absent today |

`notebooks/sdr/_cache/trade_tape` is 94% of everything under `notebooks/`, and
it is written by `SDRUtils/analytics/trade_tape.py` — a library module reaching
sideways out of `SDRUtils/` into the notebook tree.

---

## 3. Already on `D:` before this change

`RVUtils/MBO/store/schema.py` (`ARBS_MBO_STORE` → `D:\mbo_store`, 40.7 GB),
`RVUtils/MBO/archive.py` (`D:\sr3_mbo`, `D:\zq_mbo`, `D:\zt_mbo`, `D:\zf_mbo`,
`D:\zn_mbo`, `D:\tn_mbo`, `D:\zb_mbo`, `D:\ub_mbo`), `D:\dd_signals_cache`,
`D:\ddfe_cache`, `D:\midgrid_cache`, `D:\ddnb_cache`.

## 4. Deliberately NOT moved

- **`MDP/FixedRateBonds/reference_data_cache/`** — named "cache" but **tracked in
  git**. Moving it would delete tracked files. It stays in the checkout.
- **`C:\Users\chris\clee\project-oasis\private\sdranalytics\.cache`**
  (`SDR_CACHE_DIR`, `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/…:308`) — another
  project's cache. ARBS only reads it.
- **Sibling worktree caches** under `C:\Users\chris\clee\ARBS-*` and
  `ARBS/.claude/worktrees/*` — each worktree owns its own copy. They are
  untouched and keep working on old code.
