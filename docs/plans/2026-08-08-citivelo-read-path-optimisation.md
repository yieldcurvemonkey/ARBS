# Citi Velocity timeseries read path — measured optimisation

**Branch** `perf/citivelo-read-path` · **Date** 2026-08-08

The starting point: one day of 1-minute `USD-SOFR-1D`, one tenor, everything
served from the warmed local `CurveStore` with no Excel and no network —
**841 observations in 39.3 s, 47 ms per observation**. That was the binding
constraint on minute-resolution work.

Everything below is measured on this machine, on that same day
(2026-07-22, 03:00–17:00 ET, 841 minutes), with `scripts/perf/citivelo_read_path_bench.py`.

---

## 1. Where the 47 ms actually went

The previous round of work on this path found that a *date-independent* fixings
lookup was 97% of a warmed read, while everyone had assumed the cost was parquet
I/O or the rateslib solve. So this round started the same way: component timing,
not a flat total.

Splitting the 47 ms at the seam between "get a curve" and "turn it into a
number" gives:

| stage | ms/obs | share |
|---|---:|---:|
| `IRSwapsMDP.get_data` — build the curve | 29.92 | 60% |
| pricing one `IRS_RATE` row | 20.34 | 40% |

**The pricing layer was 40% of the cost and had never been profiled.** It was on
the "almost certainly others" list in the brief, and it turned out to be the
larger of the two remaining problems once the store side was fixed.

### 1a. Inside the curve build (30 ms)

Per observation, timing each stage of `_load_citivelo_excel_minute_store_point`:

| stage | ms/obs | share | what it was doing |
|---|---:|---:|---|
| `read_raw_day` ×2–3 | 17.392 | 57.2% | re-reading one 537 KB partition, 841 times |
| `fixings_for` | 7.908 | 26.0% | re-filtering and re-gap-filling one 5,445-row history |
| `pd.to_datetime` | 1.981 | 6.5% | re-parsing the same stamp column |
| `pd.concat` | 1.080 | 3.6% | re-joining the same two day frames |
| `has_day` ×3 | 0.964 | 3.2% | re-stat-ing the same three directories |
| `reconstruct_curves_batch` | 0.574 | 1.9% | the only stage doing new work |
| `iloc` / `argmin` / rest | 0.480 | 1.6% | |

**93% of the curve build was recomputing a value that had not changed.** The day
frame is the same object for all 841 minutes of a session; so is the fixings
history, because every observation in a session shares a reference date.

### 1b. Inside the pricing (20 ms)

`IRSwapQuery` → `_build_row_for_query` → `RLIRSwapCurve.build_irswap` +
`calc_spread_rate`. `IRS.rate()` was called **twice per reported rate**:

* once inside `build_irswap`, on a throwaway unit-notional swap, purely to
  choose the strike (`fixed_rate` defaults to par);
* once by `calc_spread_rate`, on the swap that was actually returned.

And each of those calls is expensive because the fixings series is attached:

| `IRS.rate()` on a warmed USD 10Y | ms |
|---|---:|
| with a 5,445-row fixings series | 4.341 |
| with no fixings series | 0.188 |

23×. Attaching a fixings series puts rateslib on its RFR path, which
materialises a business-date `Series` over **every** accrual period before
discovering (at `_populate_fixings`, `fixing_rates.index[0] > fixing_series.index[-1]`)
that none of them is in scope. A par swap consumes no fixing and pays for all of
them.

`rl.IRS` construction is 1.398 ms with fixings against 0.921 ms without, of which
0.235 ms is `rate_fixings_kwargs` — which cleans, sorts and SHA-256s the whole
history on every call, because rateslib's identifier is content-addressed.

---

## 2. What changed

### 2.1 `fixings_for` result memo — `MDP/IRSwaps/CITIVELO_EXCEL/fixings.py`

The existing `_MERGED_CACHE` removed the two *source* lookups (232 ms + 237 ms)
but left the per-call work: the `reference_date` filter builds a 5,445-element
object array of `datetime.date`, and `fill_calendar_gaps` walks 21 years of
calendar days asking `is_bus_day`. 7.9 ms, per call, for an answer that is
identical across a whole session.

The whole `FixingsResult` is now memoised on
`(curve_name, citi_index, reference_date, prefer_official, fill_gaps)`, bounded
LRU (512 entries), populated only when `quotes is None`, and cleared by
`reset_fixings_cache()`.

`reference_date` is **in the key**, not applied as a filter to a shared entry.
That is the whole point: an entry cached for a later date contains fixings an
earlier request must not see, and serving them would leak future rates into a
historical curve — invisible in any timing benchmark. The test for it asks for
the **later** date first.

The returned `series` is a copy (~0.2 ms against 7.9 ms saved), because callers
hand it straight to `RLIRSwapCurve` and this repo has call sites that assign into
a fixings series they were given.

### 2.2 Day-window cache — `MDP/IRSwaps/CITIVELO_EXCEL/day_cache.py` (new)

Two levels, both revalidated on every hit against the partitions' file names,
sizes and mtimes:

* `_DAY_FRAMES` — one day's frame, so overlapping windows share it. A backfill
  walking D then D+1 asks for `(D, D−1, D+1)` then `(D+1, D, D+2)`; without this
  the same partition is read three times across a multi-day run.
* `_CACHE` — the assembled **window**: the three days joined and stamp-parsed
  once. Caching the window (not three days) is what also removes the `concat`
  and the `to_datetime`.

The day order `(0, −1, +1)` is preserved deliberately: the nearest-snapshot
search breaks ties positionally, so reordering the window could change which of
two equidistant snapshots is served.

Revalidation is not optional. The intraday warmer appends minutes to a day that
is already cached; a cache that trusted its first read would serve a truncated
session for the rest of the run, silently. Revalidating three partitions costs a
`scandir` (measured below) against 17 ms to re-read them.

A partition with no parquet yields a `None` signature, which is a legitimate
cached value — that is what preserves `has_day`'s contract, so a cold day still
returns nothing and still falls through to the live build.

### 2.3 One par-rate computation instead of two — `RLIRSwapCurve`

`build_irswap` now constructs the instrument it is going to return **unstruck**,
reads the par rate off *that* object, assigns `fixed_rate`, and parks the value
where `fair_rate` can find it (guarded by the identity of both the wrapper and
the curve handle, so a swap re-priced against a different curve recomputes).

This is not "close to" the old number, it is the same one. Measured on the same
curve before making the change:

```
rate(notional=1)            3fa5af3d6fd1bcf7   0.04235260000211299
rate(notional=1_000_000)    3fa5af3d6fd1bcf7   identical
rate(struck at par)         3fa5af3d6fd1bcf7   identical
```

`IRS.rate()` reads neither the notional nor `fixed_rate`, and `fixed_rate` is
assigned afterwards. Saves one full `rl.IRS` construction (1.4 ms) plus one
`IRS.rate()` (4.3 ms) per reported rate.

### 2.4 Fixings identifier resolved once per curve — `RLIRSwapCurve`, `utils/rl_compat.py`

`rate_fixings_kwargs` is content-addressed, so it costs 0.235 ms on a 5,445-row
history *per call*, and a fly builds three legs on top of a leg per query. Two
memos:

* per-`RLIRSwapCurve` (invalidated by the identity of `_fixings`), which is what
  a multi-query, multi-leg timeseries actually hits;
* per-series-object inside `rl_compat`, guarded by a weakref (so a recycled `id`
  cannot alias a dead entry) plus a length-and-endpoints fingerprint. This one
  also serves the STIR/SDR call sites.

### 2.5 `bulk_get_data` gets a CITIVELO branch — `IRSwapsMDP`

Before this, `citivelo_excel` fell through to the generic per-point loop, which
is literally a `for t in timestamps: self.get_data(...)`. Measured on the
intraday path before any of these changes: **30.09 ms/obs batched against 29.92
ms/obs one at a time** — a batch method that did nothing at all. (The brief
reports it as actively *slower* on EOD history, 141 vs 16 ms/curve; that
comparison was not re-run here.)

The branch groups requests by mode, reads each session's window once, runs the
nearest-snapshot search per request against the shared window, reconstructs the
**distinct** rows in one batch, and resolves fixings once per distinct reference
date.

Two things it does deliberately differently from the ERIS batch it is modelled
on:

* it builds **one wrapper per request**, not one shared wrapper per snapshot.
  CITIVELO metadata carries `requested` and `snapshot_lag_seconds`, which are
  properties of the request, not of the snapshot;
* reconstruction is keyed by **row position**, not by `timestamp_utc`. Two rows
  in a three-day window can carry the same stamp after a re-warm, and a
  timestamp-keyed dict silently collapses them.

Every served curve is wrapped by the same `_wrap_citivelo_excel_*` helper the
single-point loaders use — the helpers were extracted for exactly that reason —
and anything the batch cannot resolve (a QL backend, `force_refresh` /
`ignore_cache` / `no_curve_store`, `live`, an unwarmed day) is handed back to
`get_data` one point at a time.

### 2.6 Opt-in: skip fixings nobody consumes — **default OFF**

`ARBS_RL_OMIT_UNUSED_FIXINGS=1` (or `RLIRSwapCurve.set_omit_unused_fixings(True)`)
omits the fixings series for instruments whose first accrual period starts on or
after the curve's reference date — which consume none of it. That is the 23× on
`IRS.rate()` above.

It is **not** bit-identical, which is why it is off by default. The two routes
are the same quantity computed two ways — daily compounding of curve discount
factors versus the endpoint ratio the compounding telescopes to — and they
disagree in the last unit in the last place:

| par tenor | with fixings | omitted |
|---|---|---|
| 10Y, 30Y | — | identical |
| 2Y | 4.154360000019888 | 4.154360000019887 |
| 5Y | 4.120890000061977 | 4.1208900000619755 |
| 40Y | 4.275369857811132 | 4.275369857811131 |
| 5Yx5Y | 4.3758958166657465 | 4.375895816665747 |

≈2e-13 bp. Immaterial to any decision, and still a changed number, so a caller
has to ask for it. Seasoned, IMM- and central-bank-dated legs starting before the
reference date keep the full series either way; an `effective` that cannot be
resolved to a date is treated as "might be seasoned" and keeps them too.

---

## 3. Proof the numbers did not move

`scripts/perf/citivelo_reference_capture.py` captures a reference at two levels
and compares them exactly:

* **curve level** — `meta_data`, node dates, and a SHA-256 of the raw IEEE-754
  bytes of the node discount factors and of the fixings series. A one-ulp change
  is a failure.
* **frame level** — what `TimeseriesBuilder` returns, compared with
  `assert_frame_equal(check_exact=True)`.

Coverage: 5 currencies (USD, EUR, GBP, CAD, JPY-LCH) × EOD (2026-06-01 →
2026-07-31) and intraday (6 sessions, one of them the full 841-minute grid) ×
outright / forward-starting / curve / fly / PV01 / NPV / a **seasoned** swap
that actually consumes published fixings.

The baseline was captured from a **separate pristine worktree at `main`**, not
from this branch with the changes stashed: this repo imports lazily, so a module
first imported after an edit picks up the new code, and the first attempt at a
baseline was contaminated exactly that way.

The TB mapping cache is bypassed with a throwaway `cache_stem` per run. With it
on, the 841-point request returns in 0.13 s from cached rows and compares a
cache against itself — a "benchmark" that measures nothing and a diff that
proves nothing.

### Result

```
OK  curves.json: 173 entries identical
OK  fixings.json: 25 entries identical
    frames: 1,557 rows x 59 columns — 55 columns bit-identical, 4 moved
```

Bit-identical: **every** reported rate (outright, forward-starting, curve, fly,
seasoned), every PV01, and every NPV on an explicitly-struck swap. Also every
curve: node dates, discount factors and the fixings series compared by SHA-256
of their raw bytes, across 5 currencies × EOD and intraday, including
`snapshot_lag_seconds` and `requested` in the metadata — which is where a wrong
nearest-snapshot pick would show.

#### The one deviation, and why it was taken

The four columns that moved are all `NPV` on a swap struck at **its own par
rate** — a number that is zero by construction:

| column | values moved | max abs delta | largest abs value in the column |
|---|---:|---:|---:|
| USD seasoned NPV-par | 451 | 1.164e-10 | 1.164e-10 |
| EUR seasoned NPV-par | 92 | 8.731e-11 | 5.821e-11 |
| GBP seasoned NPV-par | 57 | 1.164e-10 | 8.731e-11 |
| JPY seasoned NPV-par | 48 | 5.821e-11 | 1.164e-10 |

On a $1,000,000 notional. The column *is* zero; the change is the same order as
its own noise, and several entries move to **exactly** 0.0.

The cause is §2.3 and it is deliberate. The swap's strike used to be the par
rate of a *different* object — a unit-notional probe — and is now the par rate
of the swap itself. Those two differ in the last ulp in about half of cases:
measured across 60 (currency × date × tenor) combinations including seasoned
legs, **28 of 60 differed by 1 ulp** (e.g. EUR 5Y `0.025395199980949603` vs
`0.025395199980949613`). Striking a swap at its own par rate rather than a
copy's is the more self-consistent of the two, which is why its NPV is now
exactly zero more often than before.

The stated bar for this work was byte-identical, so this is called out as a
**deviation, not a pass**. Two things about its blast radius, honestly:

* it is program-wide, not citivelo-scoped — `RLIRSwapCurve.build_irswap` serves
  every rateslib-backed source (ERIS, CME-RL, GSQUANT, SDR, BARCHART). The fast
  gate is the evidence that no golden test elsewhere pins a struck rate;
* it is **one hunk to revert**. Restoring the probe solve in `build_irswap`
  gives back full bit-identity at a cost of ~5.7 ms/observation, and nothing
  else in this branch depends on it.

---

## 4. Mutation testing

`scripts/perf/mutation_check.py` breaks each fix in turn and asserts the test
that covers it **fails**. A test that still passes with the code it covers
reverted is a comment, not a test — and this repo has a record of tests that
passed with the fix removed.

---

## 5. What was NOT worth changing

* **A range read for EOD history.** `read_raw_nodes` (one DuckDB Hive scan) vs
  N `read_raw_day` calls — measured, see the results section. The day cache does
  not help a cross-day EOD backfill (one read per day either way); the fixings
  memo does.
* **Sharing one `rl.IRS` instrument across a session.** Within one trading day
  the instrument differs only by the curve it is rated against, so it could be
  built once. It is a mutable object in a hot, shared, thread-pooled layer, and
  the remaining prize after 2.3 is the 1.4 ms constructor, not the 4.3 ms rate.
  Not taken.
* **Shortening the fixings series passed to rateslib.** The per-period cost is
  `O(accrual period)`, not `O(len(fixings))` — `bus_date_range` and the Series
  it fills are built before the "no fixings in scope" short-circuit is reached.
  Trimming the history changes nothing.
* **`_validate_curve_request_timestamp` per point.** `citivelo_excel` is not an
  `EOD` source by `_requires_strict_eod_calendar_validation`'s test, so this is
  already a no-op on this path.
