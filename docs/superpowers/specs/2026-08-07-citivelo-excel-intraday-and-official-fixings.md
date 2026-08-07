# Citi Velocity Excel: minute-resolution intraday history, and publisher-direct fixings

Measured 2026-08-07 unless stated. Everything here is a number that was taken off
the live add-in or a live endpoint, not a documented claim.

---

## 1. The add-in downsamples by requested SPAN, not by age

This is the finding the rest of the work rests on, and it corrects the framing it
started from ("the add-in silently downsamples long windows" — true, but the
operative variable was not obvious).

`CVTSHIST` does not serve the frequency you ask for. It serves the frequency it
thinks the requested **span** deserves, and it does so **silently**: the block
comes back looking exactly like a healthy minute request, just with fewer rows.
Ask for a year of `MI01` and you get 261 rows stamped at midnight — daily data,
no error, no warning.

Measured on `RATES.OIS.USD_SOFR.PAR.10Y`, end fixed at 13:00 ET:

| requested | span | spacing actually served |
|---|---|---|
| `MI01` | 2d, 5d, 6d | 1 minute |
| `MI01` | **7d** | **10 minutes** |
| `MI01` | 8d – 60d | 10 minutes |
| `MI01` | 120d | 60 minutes |
| `MI01` | 365d | 1440 minutes (daily, midnight-stamped) |
| `HOURLY` | ≤ 120d | 60 minutes |
| `HOURLY` | 365d | 1440 minutes |

The cliff is at **exactly 7 days**, pinned to the hour: 6.5d served 1-minute,
7.0d served 10-minute.

### It is span, not retention

Holding the span at four days and walking the window backwards:

| age of window | rows | spacing |
|---|---|---|
| 3d ago | 2,697 | 1 min |
| 10d | 2,700 | 1 min |
| 25d | 2,306 | 1 min |
| 60d | 2,701 | 1 min |
| 90d | 4,235 | 1 min |
| 180d | 2,875 | 1 min |
| **365d** | **4,961** | **1 min** |

Minute history is retained for **at least two years** — the deep backfill has
since pulled USD-SOFR back to **2024-07-31 at true 1-minute spacing**, 563 day
files. It is only ever hidden by asking for too much of it at once. So a
full-resolution backfill was never a retention problem — it is a chunking
problem.

### The boundary is a property of the add-in, not of USD

Re-measured at 6d and 7d on four more curves, at both "now" and "a year ago":

| index | 6d (now / 1y ago) | 7d (now / 1y ago) |
|---|---|---|
| `EUR_EUROSTR` | 1 min / 1 min | 10 min / 10 min |
| `JPY_TONAR_LCH` | 1 min / 1 min | 10 min / 10 min |
| `GBP_SONIA` | 1 min / 1 min | 10 min / 10 min |
| `CAD_CORRA` | 1 min / 1 min | 10 min / 10 min |

Identical everywhere.

### The trap: it is NOT monotone in the argument form

Do not "simplify" the chunker into a single wide request. Two measured
counter-examples:

* `period="1W"` at `MI01` served **7,676 rows at 1-minute**, while explicit
  bounds spanning 7.0 days served 10-minute.
* `period="1Y"` at `HOURLY` served **6,252 hourly rows**, while explicit bounds
  over the same year served **261 daily** ones.

The relative-period form and the explicit-bounds form take different paths
through the add-in. `MDP/CitiVelocityExcel/windowed.py` therefore holds windows
strictly **under** the cliff rather than at it, and verifies the spacing of every
window it returns.

### Correction to an earlier note

An earlier measurement in this session recorded "MI01 over 1 week → 667 rows
(~14-min)". That was wrong — re-running it gave 7,676 rows at true 1-minute
spacing. The 667-row readings all came from **7.0-day explicit-bounds** requests,
which is the 10-minute rung of the ladder above.

### Argument shape

All three of these are equivalent — the reference workbook's omitted-argument
form has no special power:

```
=CVTSHIST(tags,"MI01","","202607200001","202607242359","CLOSE")   6,049 rows
=CVTSHIST(tags,"MI01",,202607200001,202607242359,"CLOSE")         6,049 rows
=CVTSHIST(tags,"MI01",,"202607200001","202607242359","CLOSE")     6,049 rows
```

6,049 rows matches `db_v2.xlsx` exactly, so the fetch path reproduces the
hand-built workbook bar for bar.

---

## 2. One worksheet per window

A minute window of a full curve is ~5,300 rows × 45 columns. A few hundred of
them in one sheet is millions of live `CvFunction_*` cells and an Excel that runs
out of memory.

Each window therefore gets its own worksheet, named for its bounds
(`202607200001-202607242359`), dropped once the window has been read — the same
shape as the hand-built `citi_usd_sofr_intraday_curve` workbooks, which are one
file per Mon–Fri week.

Verified live: two windows × 44 tenors, both sheets created and deleted, **1
sheet remaining** (the marker sheet), 10,613 minute rows with no duplicates, 1.4 s
per window.

The delete drains first (`CalculateUntilAsyncQueriesDone` + pause) and suppresses
`DisplayAlerts`. A refusal is logged and survived, never raised: the window's data
is already read, and fighting Excel there costs the process.

### Dropping sheets is necessary but NOT sufficient — this wedged Excel

Sheet-dropping bounds the number of live **cells**. It does **not** return Excel's
**process memory**, and at scale that is the binding constraint.

**What happened (2026-08-07).** A 528-window deep fetch ran cleanly for eight
minutes — zero refused deletes, zero failed windows, WARM workbook steady at 1
sheet — and then stopped writing at 14:50:02. The Python process was still alive.
Excel was at **5,249 MB** and did not answer a 15-second `SendMessageTimeout`
window ping. `IsWindowEnabled` was **True** and there was no `#32770` child, so
this was *not* the cell-edit-mode hang seen twice earlier in this work — those
answered the ping. Killing the fetch process to release COM did not recover it;
memory did not even move.

**The lesson.** Small-scale success was misleading. The 8-window top-up proved the
sheet lifecycle, and that was taken as proof the memory problem was solved. It was
not — it only proved the *cell* problem was solved. 528 windows is 66× the
validated scale.

**The fix.** `CitiVelocityExcelClient.recycle_workbook()` closes the scratch
workbook and opens a fresh tagged one, which is the only mechanism that actually
gives the memory back. `fetch` now checks `excel_memory_mb()` every
`--recycle-every` windows (default 25) and recycles above `--memory-ceiling-mb`
(default 3000, comfortably under the 5,250 that wedged). It refuses outright while
a `CVSTREAM` cell is live — tearing down live RTD is the documented
`AccessViolation` trigger — and a refused recycle stops that curve rather than
driving Excel further up. Everything fetched is already on disk, so a re-run
resumes.

**Nothing was lost**: 563 USD day files (to 2024-07-31) survived, because day
parquets are written atomically and the two-phase split means Excel work is
banked per day.

### The memory is in the add-in's cache, not the workbooks — measured twice

Recycling helps but cannot keep up, and closing workbooks barely moves it:

| action | Excel before | after | recovered |
|---|---|---|---|
| recycle the scratch workbook | 2,621 MB | 2,409 MB | **212 MB** |
| …while the preceding 20 windows had *added* | | | **~340 MB** |
| close 3 workbooks (one holding a 3,537×45 window sheet) | 3,974 MB | 3,832 MB | **142 MB** |

After the second, Excel was down to **one** workbook and still at 3,832 MB. So
the growth is the add-in's own series cache, and **only an Excel restart clears
it**. Recycling is still worth doing — it buys windows — but it is a brake, not a
fix.

**The restart has to be the user's.** A programmatically spawned Excel never
registers the `CV*` UDFs, so quitting and relaunching from code would destroy the
only working transport with no way to restore it.

**Therefore the run is designed to stop, not to push.** `fetch` raises
`MemoryCeilingReached` above `--memory-abort-mb` (3,800), reports what it banked,
and ends. A watchdog run confirmed the design live: it stopped the fetch at
**4,001 MB** and Excel stayed healthy and responsive at 3,796 MB — no wedge, no
lost data, ~750 day files banked across EUR and GBP in that pass.

---

## 3. Minute-resolution CurveStore warm

`scripts/citivelo_excel_intraday_warm.py`, two phases:

* **fetch** — single-threaded through the one Excel session, writing one
  `{date}.parquet` per calendar day.
* **build** — pure CPU in a process pool, one rateslib solver per NaN-tenor
  signature per day, re-solved per minute.

Splitting them is what makes the run **resumable**: a day file on disk is a
completed unit of Excel work, so losing Excel costs time, never data.

Asset: `<curve_name>-CITIVELOEXCELMIN`. A **fourth** distinct key, deliberately —
`write_day` replaces a whole day partition, so sharing the EOD warm's
`-CITIVELOEXCEL` asset would let an EOD re-warm silently delete that day's ~1,100
minute curves.

### Timezone: the bug this caught

The add-in stamps **every** curve in New York wall-clock, whatever the currency.
Bucketing those stamps by their raw date would have filed JPY's 19:00 ET bars —
already 08:00 the *next* morning in Tokyo — under the previous Tokyo business
date, and Phase 2 would have solved them off the wrong reference and spot date.

Phase 1 therefore converts ET → the curve's own zone before grouping. The check
that it worked: after the fix every curve's session reads **08:00–19:59 in its own
local zone**, a clean contiguous 12-hour session with no interior gaps. Before it,
EUR read 02:00–13:59.

#### And it survives the asymmetric DST windows

The US and EU do not change clocks on the same day — US DST ran 2026-03-08 to
11-01, EU DST 2026-03-29 to 10-25 — so for about three weeks each spring and one
each autumn the ET↔Berlin offset is **5 hours, not 6**. A fixed-offset conversion
would be silently an hour out on exactly those days. Checked against the fetched
EUR history:

| date | regime | session (Berlin local) |
|---|---|---|
| 2026-03-04 | both on winter time (6h) | 08:00 → 19:59 |
| **2026-03-16** | **US on DST, EU not (5h)** | **08:00 → 19:59** |
| 2026-04-07 | both on summer time (6h) | 08:00 → 19:59 |
| **2025-10-28** | **EU back, US not (5h)** | **08:00 → 19:59** |
| 2025-11-05 | both on winter time (6h) | 08:01 → 19:59 |

Identical in every regime, so the `zoneinfo` conversion is genuinely tracking both
zones' transitions rather than applying a constant.

### Results

| curve | days | minutes | curves built | errors | max reprice |
|---|---|---|---|---|---|
| USD-SOFR-1D | 35 | 35,874 | 35,874 | 0 | 0.0018 bp |
| EUR/GBP/JPY/CAD | 121 | ~77,000 | in progress | 0 | 0.0024 bp |

Throughput ~50–60 curves/s on 6 workers; Excel fetch is ~1.4 s per 5-day window
of 44 tenors and is not the bottleneck.

`solver.result["status"] == "SUCCESS"` stopped being proof of a good solve in
rateslib 2.7, so every 250th minute is **repriced against its own inputs** and the
worst error is carried into the run log. Nodes are seeded with the discount factor
each par rate implies rather than a flat 1.0, which is what stops steep, high-rate
curves diverging outright.

### Serving it

`IRSwapsMDP._load_citivelo_excel_minute_store_point` serves intraday requests from
this asset, falling back to live Excel on a miss. Verified end-to-end:

```
mode                  intraday
from_curve_store      True
asset                 USD-SOFR-1D-CITIVELOEXCELMIN
snapshot_lag_seconds  0.0
```

Note the `isinstance` order in the dispatch: `pd.Timestamp` subclasses
`datetime.datetime` subclasses `datetime.date`, so testing for `date` first would
route every intraday request down the EOD branch.

### Tie-out through the Query path

`curve.fair_rate()` against Citi's own quoted par rates at the same minute:

| curve | when | tenors | max error |
|---|---|---|---|
| USD-SOFR-1D | 2026-08-05 10:30 | 44 | **0.0013 bp** |
| USD-SOFR-1D | 2026-07-22 14:15 | 44 | **0.0002 bp** |
| EUR-ESTR-1D | 2026-08-05 11:00 | 44 | **0.0006 bp** |
| GBP-SONIA-1D | 2026-08-05 11:00 | 44 | **0.0004 bp** |
| JPY-TONAR-1D-LCH | 2026-08-05 11:00 | 44 | **0.0002 bp** |
| CAD-CORRA-1D | 2026-08-05 11:00 | 44 | **0.0015 bp** |

All five currencies, every tenor, three orders of magnitude inside the ±1 bp bar.

### The deep history reconstructs too

The table above is all 2026 dates — the top-up window. The two-year backfill is a
different question (older quotes, different rate regimes, curves solved months
apart), so it was checked separately, mid-session, at a random minute of each day:

| date | minute | tenors | max error |
|---|---|---|---|
| 2024-08-01 | 12:01 | 44 | **0.0003 bp** |
| 2024-11-15 | 09:00 | 44 | **0.0014 bp** |
| 2025-03-14 | 09:10 | 44 | **0.0017 bp** |

Every one served `from_curve_store`, so the whole path — windowed fetch, ET→local
conversion, day partitioning, solve, store round-trip — holds across two years of
history and not just the recent weeks.

### Two units/date traps the tie-out walked into first

Both produced large, confident-looking errors on curves that were exact. Worth
knowing because a reader reproducing this will hit them too:

* `fair_rate()` returns a **decimal** (it divides rateslib's percent by 100) while
  Citi quotes percent. Comparing them unscaled reads as a **442 bp** error — the
  same units trap as `IRSwapValue.RATE` earlier in this work.
* Spot must come from **`SettlementDays`**, not `payment_lag`. They coincide for
  USD (both 2) and diverge for EUR (1 vs 2). Using `payment_lag` reported
  **0.4358 bp** at EUR 3M; `SettlementDays` gives **0.0006 bp**. A tie-out that
  builds its own instruments has to build them the way the warm did.

---

## 4. Publisher-direct overnight fixings

`MDP/IRSwaps/CITIVELO_EXCEL/official_sources.py`, modelled on
`MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/FixingsFetcher.py` — a per-source method
behind a dispatch map keyed by curve.

Citi's `RATES.MONEY_MARKETS` tags cover twelve of the twenty curves. Of the eight
they do not, **three now serve** and five are recorded unavailable with the
measured reason:

| curve | source | status |
|---|---|---|
| `USD_FEDFUND` | NY Fed `effr/search.json` | **serves** — 549 rows |
| `NOK_NOWA` | Norges Bank `SHORT_RATES/B.NOWA.ON.R` | **serves** — 552 rows, history to 2011 |
| `ZAR_ZARONIA` | SARB timeseries `MMRD855A` | **serves** — 546 rows |
| `MXN_T_FONDEO` | Banxico SIE `SF331451` | needs a free `BANXICO_TOKEN` (HTTP 400 `Token inválido` without) |
| `DKK_TNDKK` | — | no public API found; every `/api/v1` shape 404s, not in ECB `FM` |
| `ILS_SHIR` | — | BOI SDMX serves 39 dataflows but none is SHIR/TELBOR; the public endpoint returns the **policy** rate |
| `SGD_SORA` | — | MAS eservices returns its maintenance page — looks like an outage, worth re-probing |
| `THB_THOR` | — | BOT requires a registered client key |

### Three traps these endpoints set

* **Norges Bank**: NOWA is **not** in the `IR` dataflow (which carries only the
  key policy rate). It is in `SHORT_RATES`, and the final `R` selects
  UNIT_MEASURE=Rate — `T` there returns the daily **transaction count**, small
  integers like 9, 15, 13 that pass every sanity check a rate would.
* **SARB**: the undated endpoint silently truncates to the last ~25 observations.
  The dated form `.../MMRD855A/{start}/{end}` serves history (648 rows to 2024).
* **Bank of Israel**: the public `GetInterest` endpoint returns the policy rate
  (3.5%) where a caller reaching for SHIR would expect the overnight fixing.

Everything returns **percent**, indexed by fixing date, ascending — unlike
`FixingsFetcher`, whose methods return decimals. The conversion happens once, at
the boundary.

A source that does not answer raises or returns empty. It never falls back to a
policy rate, a neighbouring currency, or a carried-forward constant.

### Through `fixings_for`, with provenance

Verified live 2026-08-07 against reference date 2026-08-06 — the number of rows,
the freshness of the tail, and **which source answered**:

| curve | rows | last fixing | gap | source |
|---|---|---|---|---|
| USD-FEDFUNDS-1D | 548 | 2026-08-05 | 1d | `official` |
| NOK-NOWA-1D | 551 | 2026-08-05 | 1d | `official` |
| ZAR-ZARONIA-1D | 548 | 2026-08-05 | 1d | `official` |
| USD-SOFR-1D | 5,456 | 2026-08-05 | 1d | `official+citi` |
| THB-THOR-1D | 0 | — | — | `none` |
| DKK-TNDKK-1D | 0 | — | — | `none` |

Three curves that previously had **no fixings at all** now carry a real
two-year history one day behind. The two that still have none report `none`
rather than an empty series that would read as "the rate is zero", and the live
tests (`-m network`) assert both the plausibility of the rate and that the tail is
no more than ten days stale.

---

## 5. Tests

* `tests/test_citivelo_windowed.py` — 15 tests. The fake models the span cliff,
  so the spacing guard has something real to catch. **Mutation-verified**:
  replacing the guard's condition with `if False` fails 2 tests; restoring it
  passes 15.
* `tests/test_citivelo_official_sources.py` — 11 hermetic + 3 network-marked.
  Guards the parsing traps above (rate-vs-transaction-count, dated-vs-undated,
  percent-vs-decimal).
