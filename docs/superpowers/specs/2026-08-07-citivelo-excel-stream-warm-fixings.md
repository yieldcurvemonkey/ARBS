# Citi Velocity Excel — the CVSTREAM daemon, the CurveStore warm, and fixings

**Branch** `feat/citivelo-irswaps-source` · **written** 2026-08-07 · builds on
[the source design note](2026-08-07-citivelo-excel-irswaps-source.md) and
[its verification](2026-08-07-citivelo-excel-verification.md).

Three things the first pass explicitly did not do, now done.

---

## 0. A wire fact found along the way, and it was already costing data

The add-in's own log gave up something the package did not know:

```
ERROR | Citi.Excel.Registration.ExcelFunctionStub | Error in params. CVTSHIST -
Parameter 'Period' must be one of "30I", "1H", "2H", "4H", "8H", "12H", "1D",
"2D", "4D", "1W", "2W", "1M", "2M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y",
"MAX".
```

`Period` is a **closed vocabulary**, not the `<n><D|W|M|Y>` grammar
`frequencies.normalise_period` was validating with. Three consequences, all of
which had already bitten:

* **`DEFAULT_FULL_PERIOD` was `"50Y"`** — not in the list. So
  `fetch_timeseries` with neither `period` nor `start`, i.e. "give me all the
  history", **returned an empty frame for every tag**. Now `"MAX"`.
* My earlier `period="5D"` failure, written up in the first verification note as
  "`HOURLY` does not take a relative period", was **wrong**: `5D` is simply not in
  the vocabulary (`1D`, `2D`, `4D` are). `HOURLY` takes a period fine — an
  intraday one. **That finding is corrected below.**
* `period="15Y"` likewise. The deep-history harvest now uses explicit bounds,
  which are honoured, and got **21 years** (2005-01-03 onward) in one call.

The rejection is what makes this expensive: the add-in writes **no block at all**,
instantly, which is indistinguishable from a tag that has no data. So
`normalise_period` now validates against the real set and, for a value of the
right shape but the wrong size, names the nearest accepted period.

---

## 1. Fixings

### Where they come from

`RATES.MONEY_MARKETS.<ccy>.<index>.ON`. Probed live for all eleven currencies the
catalog lists, plus five speculative USD spellings:

| curve | serves | history | last fixing (2026-08-07) |
|---|---|---|---|
| USD-SOFR-1D | ✓ | 2005-01-03 → | **2026-06-25** (6 weeks stale) |
| EUR-ESTR-1D | ✓ | 2005-01-03 → | 2026-08-06 |
| GBP-SONIA-1D | ✓ | 2005-01-04 → | 2026-08-06 |
| JPY-TONAR-1D ×3 | ✓ | 2005-01-03 → | 2026-08-06 |
| CHF-SARON-1D | ✓ | 2005-01-03 → | 2026-08-06 |
| AUD-AONIA-1D | ✓ | 2005-01-04 → | 2026-08-06 |
| NZD-NZIONA-1D | ✓ | 2005-01-04 → | 2026-08-07 |
| CAD-CORRA-1D | ✓ | 2005-01-04 → | **2026-04-29** (3 months stale) |
| SEK-STINA-1D | ✓ | 2005-01-03 → | **2026-06-26** (6 weeks stale) |
| NOK-NOWA-1D, DKK-TNDKK-1D | ✗ | — | tag well-formed, serves no rows |
| USD-FEDFUNDS-1D | ✗ | — | `FFT`, `BGCR`, `TGCR`, `FEDFUND`, `EFFR` all probed; none serves |
| ILS, MXN, SGD, THB, ZAR | ✗ | — | absent from `RATES.MONEY_MARKETS` |

### Why Citi's fixings are trusted

The one currency with an independent source here decides it:

> **Citi `RATES.MONEY_MARKETS.USD.SOFR.ON` vs the New York Fed's own SOFR:
> 2,056 overlapping business days, 2018-04-02 … 2026-06-25,
> max |difference| = 0.000000 bp, 0 of 2,056 dates differ at all.**

So Citi's money-market ON series *is* the official published fixing, in percent.
That licenses using it for the eight currencies where nothing else exists here.
USD still prefers the Fed's — not because the values differ but because Citi's
tail was six weeks stale — and the two are unioned, giving 2005→present.

### The two failure modes, and they are not symmetric

Both were measured on a seasoned 5Y (started 2024-08-06, matures 2029-08-06):

**A hole in the middle raises.** rateslib needs a rate for every business day of
an elapsed period, and the leg calendar and the publisher disagree: `syd` calls
**8** days business days that Citi's AONIA series does not publish over two years;
`tyo` one for TONAR. One missing day made JPY and AUD raise.
*Fix:* carry the previous fixing forward onto the leg calendar's business days —
an index does not move on a day it is not published, and this repo already relies
on that reasoning in `_asof_fixings`, which measured the substitution at **~0.0012
bp on a seasoned 5Y**. Filling happens only inside `[first, last]`.

**A tail that stops early does NOT raise — it produces a plausible number.**
rateslib forecasts the missing days off a curve that does not extend back that
far, whose discount factors are zero. Measured: **CAD-CORRA, whose fixings stop 99
days before the curve date, priced that seasoned 5Y at −27.26%**. SEK gave −23.68%.
*Fix:* if the fixings do not reach within 5 days of the curve's reference date the
series is **withheld entirely**, so rateslib raises instead. A refusal is strictly
better than −27%.

### Result

| | before | after |
|---|---|---|
| curves carrying real fixings | 1 (USD) | **12** |
| history | 2018→ | **2005→** |
| seasoned 5Y prices correctly | 1 | **10** |
| seasoned 5Y silently wrong | — | **0** (was 2: CAD −27.26, SEK −23.68) |

The ten: USD 4.046, EUR 2.478, GBP 4.117, JPY 1.493, JPY-JSCC 1.493, JPY-LCH
1.504, CHF 0.166, AUD 4.332, NZD 3.255. JSCC and LCH correctly differ — the CCP
basis is real and the two curves are not interchangeable.

The other ten raise, which is correct: eight have no published fixing anywhere in
`RATES.MONEY_MARKETS`, CAD and SEK have one that is too stale to use.

---

## 2. The `CVSTREAM` daemon

### What `CVSTREAM` actually is

| property | measured 2026-08-07 |
|---|---|
| tags per cell | **one** — `CVSTREAM("a,b,c")` returned a single scalar, the first tag's, silently dropping the rest |
| live? | **yes** — the same cell 25 s apart gave `4.05612604557329` then `4.05596231843847` |
| precision | full double, against `CVLATEST`'s 5 dp (`4.23919`) |
| timestamp | **none** |
| where the value lands | the **anchor cell** itself — a scalar does not spill |

### The shape that follows

A 44-tenor curve is 44 RTD cells. Writing is the dangerous operation, so it
happens **once**, at `open()`; every poll afterwards is `read_stream()`, which
performs **no writes at all** — pinned by
`test_polling_a_stream_performs_no_writes`. The workbook is **never closed**:
`CitiVelocityExcelClient.close()` declines when a stream is open, because an RTD
cell always has queued add-in actions against it and tearing one down is the
documented `AccessViolation` trigger.

**Excel pushes back on a burst of subscriptions.** Measured: 44 cells opened
cleanly, then the 45th raised
`com_error(-2147352567, 'Exception occurred.', (…, -2146777998))` — which
`com_retry` does not cover, because it is not one of the two busy HRESULTs. Fixed
with a 0.15 s inter-write pause plus a bounded backoff retry that names the tag if
it persists.

### The timestamp is ours, and that is the limitation

`CVSTREAM` publishes no timestamp, so a snapshot is stamped with **when the daemon
read the cell**. To stop that manufacturing ticks that did not happen, a poll only
persists when at least one tenor has **moved**, and a run of unchanged polls is
counted and warned about. This is why `MI01` remains the primitive for the
request/response source, which needs to know *when*.

### Running live

```bash
conda run -n stir python scripts/citivelo_excel_stream_service.py run \
    --curves USD-SOFR-1D,EUR-ESTR-1D,GBP-SONIA-1D --poll-seconds 60 --stop-at 17:00
conda run -n stir python scripts/citivelo_excel_stream_service.py status
```

Observed on 2026-08-07, 132 live cells across three curves:

```
12:44:09 USD-SOFR-1D   wrote 44 tenors, 44 moved  ok   10Y=4.24055
12:44:09 EUR-ESTR-1D   wrote 44 tenors, 44 moved  ok   10Y=2.92148
12:44:09 GBP-SONIA-1D  wrote 44 tenors, 44 moved  ok   10Y=4.52392
12:45:09 USD-SOFR-1D   skip  44 tenors,  0 moved  unchanged   10Y=4.24055
12:45:09 EUR-ESTR-1D   wrote 44 tenors, 44 moved  ok   10Y=2.92153
12:45:09 GBP-SONIA-1D  wrote 44 tenors, 39 moved  ok   10Y=4.52425
```

Per-curve independence is visible in that second poll: USD had not moved and was
correctly not written, while EUR and GBP had.

A single-instance file lock enforces one daemon per machine — two processes
writing into one Excel is how `CvFunction` regions overlap.

Asset: **`<curve_name>-CITIVELOSTREAM`**.

---

## 3. The CurveStore warm

```bash
conda run -n stir python scripts/citivelo_excel_warm.py warm --start 2024-01-01
conda run -n stir python scripts/citivelo_excel_warm.py status
```

Runs **entirely offline** against the banked tag cache — no Excel, no network —
because one `CVTSHIST` per currency already fetched 21 years of daily history.
Resumable: existing days are skipped, each day is written atomically.

Asset: **`<curve_name>-CITIVELOEXCEL`**, deliberately distinct from the older
workbook source's `-CITIVELO` (930 warmed partitions and the dealer-ladder study
depend on that one) and from the daemon's `-CITIVELOSTREAM`. The repo has a
recorded incident where two curve variants shared a key and *which answer you got
depended on cache state*.

| curve | days | span | worst reprice |
|---|---|---|---|
| USD-SOFR-1D | 680 | 2024-01-01 → 2026-08-07 | 5.52e-04 bp |
| EUR-ESTR-1D | 680 | 2024-01-01 → 2026-08-07 | 1.71e-03 bp |
| JPY-TONAR-1D | 633 (46 sparse, 1 failed) | 2024-01-04 → 2026-08-07 | 1.95e-03 bp |
| CAD-CORRA-1D | 680 | 2024-01-01 → 2026-08-07 | 2.41e-03 bp |
| GBP-SONIA-1D | 680 | 2024-01-01 → 2026-08-07 | 2.95e-04 bp |

**3,353 curve-days.** GBP needed a second pass: its first warm covered only a year
because the deep-history fetch had been the one that used the rejected
`period="15Y"` (§0). Re-fetched with explicit bounds it gave 5,566 daily rows and
the warm resumed, skipping the 261 days already present - which is the resumability
the atomic per-day write exists for.

"Sparse" days are ones with fewer than 20 tenors quoted; they are counted, not
hidden. Requiring all 44 would have thrown away two thirds of the available
history (USD has 5,540 daily rows but only 1,835 where every tenor prints).

**The stored curve equals the rebuilt one to 0.0000 bp** on all five currencies —
that is the check that matters, and it is what makes the store safe to read from.
An EOD request now serves from it, measured **1.87× faster** (597 ms vs 1115 ms
median; much of what remains in both is the fixings read). A cold or damaged store
degrades silently to the normal build path — the one place a silent fallback is
right, because the fallback recomputes the same curve from the same quotes.

---

## 3b. The workbook leak, and consolidating by currency

**Every `connect()` called `Workbooks.Add()`.** Any process that did not reach
`close()` — a streaming daemon by design, a killed or abandoned run by accident —
left its workbook behind. Measured 2026-08-07: **62 open workbooks**, 54 of them
carrying nothing but the readiness probe's `$A$1:$C$71` footprint.

**The fix is reuse, not tidier teardown.** A scratch workbook is never saved, so
Excel names it `Book47` and there is nothing stable to look it up by. So the
client stamps `A1` with `ARBS_CITIVELO_<TAG>` and, on the next `connect()`, finds
that workbook and writes below whatever is already on it (via `UsedRange`, not a
presumed blank sheet — a reused workbook carries every previous run's live
regions, and writing on top of one is the `AccessViolation` trigger).

| caller | tag | workbooks |
|---|---|---|
| every request/response client | `SCRATCH` | **one, shared, forever** |
| the streaming daemon | `STREAM_<ccy>` | **one per currency streamed** |

Verified live: three consecutive `connect()`s took the count 8 → 9 → 9 → 9. The
first created the shared workbook; the rest reused it.

The daemon groups by **currency** rather than by curve because its workbooks can
never be closed — so one per curve per restart grows without bound, while one per
currency is stable across restarts and covers the three JPY CCP variants with a
single book.

### Cleaning up what the old behaviour left

```bash
conda run -n stir python scripts/citivelo_excel_workbooks.py list
conda run -n stir python scripts/citivelo_excel_workbooks.py cleanup --apply
```

Dry-run by default. It closes only unsaved single-sheet workbooks that carry this
package's marker or the readiness-probe footprint, one at a time with a drain
pause, and stops at the first refusal. It **never** touches a saved workbook, the
active workbook, or one holding a live `CVSTREAM` cell — tearing down an RTD
region is the documented way to kill Excel.

Run on 2026-08-07: **62 → 8 workbooks** (54 closed). The four holding live RTD
cells were correctly protected, `bridge.xlsx` was left alone as the user's, and
the streaming daemon kept polling throughout.

---

## 4. Correction to the first verification note

**F6 was wrong.** It recorded that "`CVTSHIST` at `HOURLY` with a relative
`period=` returns no block at all". The real cause was the `Period` vocabulary
(§0): `5D` is not an accepted value. `HOURLY` accepts a period perfectly well —
an intraday one (`30I`, `1H` … `12H`). The observation was right; the explanation
was not, and it is corrected in the verification note.

---

## 5. What is still not done

* **`USD-FEDFUNDS-1D`, NOK, DKK, ILS, MXN, SGD, THB, ZAR have no fixings.** Citi
  publishes none and this repo has no other source for them. A par or
  forward-starting swap is unaffected; a seasoned one raises. Adding official
  sources (Norges Bank, Nationalbanken, Banxico, MAS, BOT, SARB, and the Fed for
  EFFR) is a per-publisher scraping job with no shared shape and was not started.
* **No Supabase push by default** from either the daemon or the warm. A
  per-minute daemon pushing a whole-day blob to a remote database is a lot of
  traffic for something the local parquet answers; `--push-l2` opts in.
* **The warm covers the five requested currencies from 2024-01-01.** The banked
  history reaches 2005 and `--start` will take it there; it was bounded here to
  keep the run inside this session.
* **No scheduled-task registration** for the daemon. The ERIS precedent ships a
  `register_*_task.ps1`; this one is started by hand.
