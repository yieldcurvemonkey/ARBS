# Minute-resolution Citi Velocity IRS structures, off disk

`scripts/citivelo_intraday_ts_warm.py` fills the computed-timeseries cache with
minute-resolution USD-SOFR structures priced off the warmed minute CurveStore, so
a notebook reads them instead of repricing them.

Measured on 2026-07-29 (1,139 published minutes):

| | before | after |
|---|---|---|
| 3 queries incl. a fly and a forward | ~5 min | **0.40 s** |
| 8 queries incl. 4 swap spreads | ~6 min | **0.59 s** |

## Reading it

```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.Unified.UnifiedQuery import UnifiedQuery
from Query.Unified.registry import UnifiedValue
from TB.IRSwapsTB import IRSwapsTB
from TB.TimeseriesBuilder import TimeseriesBuilder

curve_mdp = IRSwapsMDP(source="citivelo_excel_rl")
irs_tb = IRSwapsTB(curve_mdp, show_tqdm=False, use_ts_cache=True)   # <-- True
ts = TimeseriesBuilder()

intraday = ts.get_timeseries(
    start=NYC_tz.localize(datetime.datetime(2026, 7, 29, 4, 0)),
    end=NYC_tz.localize(datetime.datetime(2026, 7, 29, 17, 0)),
    queries=[
        UnifiedQuery(curve="USD-SOFR-1D", tenor="5y/10y/30y", value=UnifiedValue.IRS_RATE),
        UnifiedQuery(curve="USD-SOFR-1D", tenor="5yx5y", value=UnifiedValue.IRS_RATE),
        UnifiedQuery(curve="USD-SOFR-1D", tenor="10Y", value=UnifiedValue.IRS_CITIVELO_SWAP_SPREAD),
    ],
    freq="1min",
    routers={"IRS": irs_tb},
    ignore_cache_miss=True,
)
```

**`use_ts_cache=True` is the whole thing.** `use_ts_cache=False` bypasses the
cache and reprices every minute — it is the difference between 0.4 s and 6
minutes, and nothing in the output says which one you got.

## What is in it

| | count | spelling |
|---|---|---|
| outright spot tenors | 28 | `1m` … `50y` |
| outright forwards | 39 | `3mx1y` … `25yx5y` |
| curves (2-leg) | 66 | `5y/10y`, `5yx5y/10yx10y` |
| flies (3-leg) | 42 | `5y/10y/30y`, `1yx1y/2yx1y/3yx1y` |
| Citi published swap spreads | 11 | `1M` … `30Y`, uppercase |

Every RATE structure is stored under both its lowercase spelling and `.upper()`,
so `5y/10y/30y` and `5Y/10Y/30Y` both hit. Mixed spellings (`5Yx5Y`) are not
pre-warmed and will reprice.

**One uncached query reprices the whole batch.** `IRSwapsTB.get_timeseries`
prices every query in the request at any reference point where any one of them is
missing, so adding a single unwarmed column to a cell of nine warmed ones takes it
from 0.4 s to 374 s. If a read is unexpectedly slow, the cause is usually one
column, not the cache.

The grid is the store's own published minutes. Sundays and US bond-market
holidays hold no priced rows by design — `IRSwapsTB` filters USD-SOFR-1D
reference points to US government-bond business days.

### Ask for the resolution the CurveStore actually has

The minute CurveStore is **not one-minute everywhere**, and the warm inherits
whatever it holds rather than inventing minutes that were never published:

| era | days | minutes/day (median) | ask for |
|---|---|---|---|
| 2024-01 → 2026-08 | 632 | **1,209–1,310** | `freq="1min"` |
| 2022-08 → 2023-12 | 366 | **132** — ten-minute data | `freq="10min"` |

Measured read times for 9 queries over a 04:00–17:00 session:

| | | |
|---|---|---|
| 2025-03-12 `freq="1min"` | 781 points | **1.7 s** |
| 2023-06-14 `freq="10min"` | 79 points | **2.1 s** |
| 2023-06-14 `freq="1min"` | 781 points | **670 s** ← 90% of the grid has no snapshot |

That last row is not a cache failure — there is no 2023 one-minute data to cache.
A `freq="1min"` request there asks for 702 instants the store has never held; the
nearest-snapshot loader serves the same curve to each run of ten, and every one of
them has to be priced. It is a **one-time** cost per day (the result is then
cached), but the values it produces are ten-minute data wearing a one-minute
index, which is worse than useless in a mean-reversion study.

The real fix is upstream: `CVTSHIST` **does** serve true 1-minute history that far
back — measured at T-1460d while warming the swap-spread axis — so
`scripts/citivelo_excel_intraday_warm.py fetch` could refill 2022-2023 at MI01 and
this warm would then cover it on a re-run. That is Excel-bound work and is not
done here.

### Swap spreads: minutes that can never be cached

Citi publishes `SWAP_SPREAD` only during its own session, but the minute
CurveStore holds the Sunday-evening open. A Monday 01:44 curve therefore meets a
Friday 17:59 print — 55.8 hours against a 12-hour limit — and the value map
refuses it, correctly, one `StaleCurveError` per (tenor, minute).

**Those minutes can never be cached**, because there is no value to cache. The
warm skips them; a *read* that asks for them pays every time, because
`IRSwapsTB` has no negative caching — the missing pairs drag the whole batch back
through the pricer (see above) and each spread query re-raises with a full
traceback.

Measured over 128,046 minutes across the first 120 store days of 2024+:

| | minutes with no serveable spread |
|---|---|
| Tue / Wed / Thu / Fri | **0** |
| ordinary Monday | ~6 (the session's first minutes, e.g. 01:00–01:44) |
| US bond holiday that still has curves (Columbus Day, Veterans Day) | ~1,050 — the whole day |

So the practical rule is narrow: **a swap-spread read covering a US bond holiday
gets NaN columns and pays full repricing for them.** Ordinary days are unaffected.
The holidays are the ones to bound or exclude — and note `IRSwapsTB` filters
USD-SOFR-1D to US government-bond business days anyway, so those days have no
RATE rows either.

### Not warmed: IMM structures

The universe is calendar tenors only — spot (`10y`) and `<forward>x<tenor>`
(`5yx5y`). Relative IMM pairs (`IMM_1xIMM_2`, which `scripts/stirf_curve_service.py`
warms for STIRT curves) and explicit IMM codes (`IMM_M27xIMM_U27`) reprice on
demand.

Relative IMM pairs are a reasonable follow-up config: adding them changes the
config fingerprint, so every day re-runs — but a re-run reads its outrights and
spreads from cache, so it costs the IMM pricing only, not another full pass.
Explicit IMM codes are an unbounded vocabulary that shifts with the reference
date and are deliberately left on demand.

## Running it

```bash
# what would run, and roughly how long
conda run -n stir python scripts/citivelo_intraday_ts_warm.py plan --workers 10

# Citi's published swap spread needs its MI01 tags out of Excel, once
conda run -n stir python scripts/citivelo_intraday_ts_warm.py fetch-spreads --auto-restart

# prove the three claims the warm rests on, on one real day
conda run -n stir python scripts/citivelo_intraday_ts_warm.py verify --date 2026-07-29

# the run itself; resumable, stops cleanly at the disk floor
conda run -n stir python scripts/citivelo_intraday_ts_warm.py warm --workers 10 --min-free-gb 10

conda run -n stir python scripts/citivelo_intraday_ts_warm.py status
```

`warm` is ledger-first: a day recorded at the current config fingerprint is
skipped, so an interrupted run resumes and a config change re-runs rather than
leaving half a universe that reads as complete. Sundays and holidays are recorded
as `non_business`, which is terminal — they are not failures and are not retried.

### Why 10 workers and not 30

Threads do not help (the pricing loop is GIL-bound: 1 worker 531 pricings/s, 8
workers 323), so parallelism is one process per day. Each worker holds ~700 MB and
runs its own Parquet write pool, and this machine routinely has other backfills
running; 16 workers alongside them is antisocial rather than fast.

### When the system disk has no room: `--spill-dir`

```bash
conda run -n stir python scripts/citivelo_intraday_ts_warm.py warm \
    --spill-dir D:\ARBS\ts --min-free-gb 6
```

This moves **this run's** symbol directories to another volume and leaves an NTFS
junction behind, so there is still one logical root: readers keep opening
`data/ts/asset=<sha1>/date=.../*.parquet` and never learn that some of those
directories live elsewhere. Nothing outside this run's symbols is touched.
Measured, a read through the junction takes 0.41 s against 0.40 s direct — the
query touches a handful of small files, so the volume's latency does not show.

The cost, stated plainly: **those symbols are unreadable while the spill volume is
detached.** That degrades to a cache miss and reprices rather than erroring, and
this cache is derived data that `warm` rebuilds. To undo it, move the directories
back and delete the junctions:

```powershell
Get-ChildItem "$repo\data\ts" -Directory |
  Where-Object { $_.LinkType -eq 'Junction' } |
  ForEach-Object { $t = $_.Target; Remove-Item $_.FullName; Move-Item $t $_.FullName }
```

Free space on this machine moved between 6 GB and 44 GB inside a minute while
other backfills ran, so `warm` **pauses** at `--min-free-gb` rather than stopping,
and only gives up after `--disk-wait-minutes`.

### `verify` is not optional

It checks the three things that fail silently:

1. the symbol a warm writes is the symbol a user query reads (the fingerprint
   does not normalise tenor case, so this is a real constraint);
2. a derived curve/fly equals the directly-priced one (max 5.6e-13 bp);
3. an uppercase alias equals the lowercase number it was copied from (exactly 0).

## Excel

`fetch-spreads` is the only part that needs Excel. `--auto-restart` handles the
add-in's unbounded memory growth: at the abort ceiling it **saves every unsaved
workbook first** (in place if it has a path, into
`~/Documents/ARBS-excel-recovery` if it does not), restarts Excel, and waits up to
25 minutes for the add-in to sign back in from saved credentials. A rescue that
fails aborts the restart rather than proceeding — see
`MDP/CitiVelocityExcel/supervisor.py`.

Pricing never touches Excel: `ARBS_CITIVELO_QUOTES_OFFLINE=1` and
`swap_spreads.set_force_offline(True)` are set in every worker, so a cold tag
cache degrades to a missing column rather than N processes racing COM into one
shared Excel.
