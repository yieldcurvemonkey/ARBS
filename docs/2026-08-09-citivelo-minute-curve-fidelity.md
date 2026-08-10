# Which minute does the Citi minute store actually serve?

**Measured 2026-08-09/10.** Scope: `USD-SOFR-1D-CITIVELOEXCELMIN` and
`USD-FEDFUNDS-1D-CITIVELOEXCELMIN`, over the `_v3` SDR tape span
(2024-03-01 → 2026-08-07), against the **local** `CurveStore`
(`C:\Users\chris\AppData\Local\ARBS\Cache\curve_store`).

Reproduce with `scripts/citivelo_minute_lag_audit.py` (stages `demand`, `density`,
`lag`, `verify`, `bp`, `drift`, `report`).

> **This measurement has a shelf life.** A deep intraday backfill is extending and
> re-solving these curves while you read this. `USD-FEDFUNDS-1D-CITIVELOEXCELMIN`
> went from **155 stored days** to **177** during the twenty minutes between the
> first and second probe of this session, and its first stored day moved backwards
> from 2026-02-09 to 2023-08-24. Every coverage number below is stamped with the
> store state it was taken against; re-run `density` before designing around them.
> The *lag* findings are structural and will not move; the *coverage* findings will.

> **UPDATE 2026-08-10 — read Part II first.** Two of this document's conclusions
> have since been superseded by measurement. §11's open question about the
> 01:00 ET boundary is **answered** (it is Citi's, and the fetch fix is worth far
> less than §11 guessed), and §6's Fed Funds coverage cliff is **gone** — an
> overnight backfill took that curve from 155 stored days to 926 and from 22.9 %
> to 97.2 % priced. Part I's *lag* findings and its recommendation are unchanged.

---

## 1. The headline

For SOFR, over **1,961,419** eligible legs:

| | leg-weighted share |
|---|---|
| served the **exact** minute requested | **96.35 %** |
| served within 1 minute | 97.59 % |
| served a snapshot from **after** the request | **1.09 %** |
| served a snapshot from a **different calendar day** | **0.33 %** |
| no warmed window at all | 0.00 % |

So the problem is **smaller than the framing suggested in the median and worse
than it looks in the tail** — and, more usefully, it is almost entirely a
*time-of-day* effect with a sharp boundary, not a diffuse property of the data.

**Every single one of the 12,649 legs printed in the 00:00–00:59 ET hour is
served a curve from the future.** Not a fraction of them — all of them. The Citi
feed's first row of the day is ~01:00 ET, so a 00:30 request has nothing before
it inside the requested day's partition, and nearest-in-either-direction jumps
*forward* to 01:00. The 22:00 and 23:00 ET hours are 12.0 % and 21.5 %
future-served for the same reason at the other end.

Between **01:00 and 16:59 ET** — 94.7 % of all legs — the p99 signed lag is
**60 seconds** and future-serving is 0.03–0.29 % per hour.

| ET hour | legs | share of tape | fraction future-served | p99 backward lag |
|---|---|---|---|---|
| 00 | 12,649 | 0.6 % | **100.0 %** | 21,000 s |
| 01–16 | 1,856,988 | 94.7 % | 0.03–0.29 % | **60 s** |
| 17 | 3,581 | 0.2 % | 0.45 % | 1,041 s |
| 18–21 | 48,489 | 2.5 % | ≤0.11 % | 3,480–10,140 s |
| 22 | 22,615 | 1.2 % | 12.0 % | 13,620 s |
| 23 | 17,173 | 0.9 % | 21.5 % | 16,920 s |

88.8 % of all future-served legs sit in hours 00, 22 and 23.

---

## 2. What the lag is worth, in basis points

A lag figure alone does not tell anyone whether it matters. Repricing 2Y/5Y/10Y/30Y
par swaps on the snapshot the current rule serves against the true
nearest-preceding snapshot, through the same `IRSwapQuery` path a caller uses, on
400 leg-weighted samples of the cases where the two rules disagree:

| tenor | mean \|Δ\| | p50 | p90 | max |
|---|---|---|---|---|
| 2Y | **1.02 bp** | 0.65 | 2.41 | 5.61 |
| 5Y | **1.14 bp** | 0.75 | 2.56 | 5.06 |
| 10Y | **1.10 bp** | 0.84 | 2.48 | 7.84 |
| 30Y | **0.98 bp** | 0.65 | 2.13 | 10.84 |

By stratum (mean |Δ|, 5Y): future-served **0.97 bp**, wrong-calendar-day **1.31 bp**.

For context: the precedent measurement recorded in
`_load_citivelo_curve_store_point`'s own comment — the bug where `nearest` jumped
forward to 01:00 ET on a bare-date request — was 5Y mean 3.55 bp, max 12.05 bp,
and was considered worth fixing. This is the same class of defect at roughly a
third the magnitude but on a path where the consequence is categorically worse:
**direction inference reads which side of mid a print landed, and most prints land
within a basis point or two of mid.** A 1 bp error there does not degrade the
call, it inverts it. And a curve from *after* the trade is not merely wrong, it is
circular — it can already contain the print's own market impact, which biases the
inference toward whatever the trade actually was.

### A structural result worth stating plainly

`fraction of legs where the two rules disagree` equals
`fraction of legs served from the future` **exactly** (0.010936469974034104 for
SOFR — the same number to sixteen digits). That is not a coincidence: if the
nearest snapshot is in the past, it *is* the nearest-preceding one. So the entire
difference between the shipped rule and a backward-only rule is the future-serving,
and the basis-point table above is precisely the cost of failure mode 1.

---

## 3. Wrong calendar day

0.33 % of SOFR legs (≈6,400) are answered out of a **neighbouring** partition. The
`(D, D-1, D+1)` window exists for a real reason — a session running to 19:59 local
straddles the UTC date boundary — but combined with nearest-in-either-direction
and no bound, a thin or absent partition for the requested day resolves silently
into yesterday's or tomorrow's session. Mean rate impact 1.31 bp at 5Y.

## 4. Exact midnight never reaches the minute store at all

`resolve_request` reads exact midnight as **end of day**, and
`SDRUtils/stir_flow/pricing.py::snap_timestamp` — the direction classifier's own
`t − 1 min` rule — produces exactly midnight for every print in the 00:01:00–00:01:59
ET minute. Those requests skip the minute store entirely and are answered by
`_load_citivelo_excel_curve_store_point`, i.e. **that day's close**, up to sixteen
hours *after* the trade being classified.

Measured: **256 SOFR legs and 3 Fed Funds legs** over the tape span. Tiny, and a
completely silent 16-hour lookahead, on the one code path that no amount of
tuning the minute-store search would ever have touched.

## 5. Density

Store state, re-measured at the end of the session (the Fed Funds row moved three
times while this was being written — 155 → 177 → 263 stored days):

| asset | stored days | span | ≥1000/day | ≥800 | <200 | days in tape span | of those, dense¹ |
|---|---|---|---|---|---|---|---|
| `USD-SOFR-1D-CITIVELOEXCELMIN` | 1,233 | 2022-08-31 → 2026-08-07 | 729 | 808 | 292 | 763 | 605 |
| `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` | 263 | 2023-08-24 → 2026-08-07 | 195 | 214 | 12 | 155 | 119 |

¹ ≥800 snapshots **and** no intra-day gap over five minutes. Both conditions:
240 snapshots evenly spread and 240 that stop at 11:58 ET are the same count and
completely different answers, which is why `density.py` reports the gap profile
beside the count.

Density gates the pathology, but does not remove it:

| SOFR day density | legs | share | future-served | backward lag > 60 s |
|---|---|---|---|---|
| < 200 snaps | 2,615 | 0.13 % | **31.3 %** | 95.4 % |
| 200–400 | 8,380 | 0.43 % | 0.12 % | 20.8 % |
| 400–800 | 13,007 | 0.66 % | 4.4 % | 9.2 % |
| 800–1000 | 175,162 | 8.9 % | 1.40 % | 1.9 % |
| ≥ 1000 | 1,761,999 | 89.8 % | 1.00 % | 2.2 % |

Note the last row: a **dense day is not a safe day**. 1.0 % of legs on
1,000-snapshot days are still future-served, because density says nothing about
whether the feed was publishing at 23:40 ET. Density and time-of-day are
independent gates and both are needed.

`USD-FEDFUNDS-1D-CITIVELOEXCELMIN`'s sparse days are much worse — 52 % of legs on
sub-200-snapshot days are future-served — but there are very few of them.

---

## 6. The Fed Funds coverage gap dominates everything else

> **SUPERSEDED 2026-08-10 — see §17.** The gap described below was closed by
> an overnight backfill. Fed Funds now has no uncovered quarter at all. The
> section is kept because the *shape* of the problem and how it was measured
> still matter, and because it is the clearest illustration in this document
> of why a coverage number needs a date stamp.

Of 66,451 eligible Fed Funds legs on the tape, **50,702 (76.3 %) have no warmed
curve anywhere in the ±1-day window.** That is not a lag problem, it is an absence
problem, and it is far larger than every lag effect in this document put together.
The curve exists and is clean where it exists; it simply does not cover the tape.

The backfill is closing this, but not where it helps: over this session the asset
grew from 155 to 263 stored days, and the new days are **2023Q3-Q4** - real, dense,
and entirely before the tape starts. Within the tape span it still holds only the
155 days from 2026-02-09. **Re-measure before planning around either number.**

---

## 7. Choosing the tolerance

Choosing this number is the one genuinely judgement-laden decision here, so it is
made from two measurements rather than from intuition.

**(a) How far the curve actually moves in a given elapsed time.** Priced on
dense sessions — every snapshot in the 07:00–08:00 and 13:00–14:00 ET blocks plus
a ten-minute grid across the day, on 20 sampled days per curve spanning the tape —
so both sides of every pair are the same curve on the same day through the same
pricing path, and convention bias cancels.

`USD-SOFR-1D`, |Δ par rate| in bp:

| elapsed | pairs | 5Y p50 | 5Y p90 | 5Y p99 | 5Y max | 2Y p90 | 10Y p90 | 30Y p90 |
|---|---|---|---|---|---|---|---|---|
| **1 min** | 2,325 | **0.06** | **0.21** | **0.44** | 6.04 | 0.18 | 0.20 | 0.20 |
| 2 min | 2,287 | 0.10 | 0.29 | 0.60 | 5.96 | 0.27 | 0.27 | 0.29 |
| 5 min | 2,172 | 0.17 | 0.43 | 0.86 | 5.83 | 0.40 | 0.42 | 0.43 |
| 10 min | 4,004 | 0.21 | 0.63 | 1.50 | 5.74 | 0.58 | 0.61 | 0.62 |
| 30 min | 3,265 | 0.38 | 1.07 | 3.07 | 8.78 | 1.02 | 1.04 | 1.06 |
| 60 min | 2,209 | 0.53 | 1.77 | 5.32 | 9.61 | 1.64 | 1.63 | 1.57 |
| 240 min | 1,869 | 1.24 | 4.54 | 10.19 | 13.08 | 4.56 | 4.03 | 3.36 |

`USD-FEDFUNDS-1D` is within a hair of it (5Y p90 0.22 bp at one minute, 0.50 at
five, 1.15 at thirty), so this is not a SOFR-specific curve.

**(b) What tightening costs in coverage.** Under backward-only selection:

| tolerance | share of SOFR legs priced | 5Y drift admitted (p90 / p99) |
|---|---|---|
| **60 s** | **97.58 %** | **0.21 / 0.44 bp** |
| 120 s | 97.69 % | 0.29 / 0.60 |
| 300 s | 97.78 % | 0.43 / 0.86 |
| 1800 s | 98.18 % | 1.07 / 3.07 |
| 3600 s | 98.60 % | 1.77 / 5.32 |

**Conclusion: 60 seconds.** Going from 60 s to a full hour recovers **one percent
more legs** and admits **eight times** the drift. The tolerance is simply not what
constrains coverage — inside the 01:00–16:59 ET session, 60 s already prices
**99.84 %** of legs. What constrains coverage is the hours the feed does not
publish, and no tolerance fixes that; it only disguises it.

Set against what it replaces: the shipped rule introduces a **mean 1.0–1.3 bp**
error on the requests where the two rules differ. One minute of drift is
0.06 bp at the median and 0.44 bp at the 99th percentile — an order of magnitude
below the error being removed, and below the one-to-two basis points from mid at
which prints land, which is the quantity the direction call reads.

**The caveat that survives.** At one minute the p99 is 0.44 bp but the **max is
6.0 bp** (2Y max 7.9 bp). Event minutes exist, and on them a single minute of
staleness is worth more than the whole signal. A tolerance cannot see that; only
the served timestamp reaching the caller can. That is why
`snapshot_lag_signed_seconds` and `snapshot_served_utc` are published on every
path rather than only checked — a direction call made against a 40-minute-stale
curve should be *marked*, and so should one made 30 seconds after a CPI print.

---

## 8. Fitness: what is safe to use, and from when

Under `SnapshotPolicy.strict(minutes=1)` — backward-only, 60 s tolerance, loud on
miss — this is what each curve supports, by quarter. `no curve` counts requests
with no warmed window *or* routed to the EOD branch; `priced` is the share
answered by a snapshot at or before the request within 60 s.

### `USD-SOFR-1D` — **fit for the whole tape span**

| quarter | legs | no curve | exact minute | future-served (old rule) | priced (asof ≤60 s) |
|---|---|---|---|---|---|
| 2024Q1 | 42,216 | 0.00 % | 96.5 % | 1.57 % | 97.0 % |
| 2024Q2 | 135,242 | 0.02 % | 96.6 % | 1.12 % | 97.5 % |
| 2024Q3 | 181,313 | 0.01 % | 97.3 % | 1.01 % | 97.5 % |
| 2024Q4 | 180,291 | 0.01 % | 97.7 % | 1.00 % | 97.8 % |
| 2025Q1 | 205,974 | 0.02 % | 97.0 % | 0.89 % | 98.1 % |
| 2025Q2 | 225,110 | 0.02 % | 94.6 % | 1.16 % | 97.3 % |
| 2025Q3 | 219,266 | 0.01 % | 96.5 % | 0.91 % | 97.8 % |
| 2025Q4 | 195,371 | 0.01 % | 96.3 % | 1.09 % | 97.7 % |
| 2026Q1 | 248,812 | 0.01 % | 97.4 % | 1.02 % | 97.7 % |
| 2026Q2 | 229,556 | 0.01 % | 95.3 % | 1.25 % | 97.3 % |
| 2026Q3 | 98,268 | 0.01 % | 93.9 % | 1.69 % | 96.7 % |

Remarkably flat. **There is no unfit period for SOFR** — no quarter drops below
96.7 % priced, and no warmed window is missing for any material share of legs.
The store holds 763 days inside the tape span, of which 605 are dense (≥800
snapshots *and* no gap over five minutes).

### `USD-FEDFUNDS-1D` — ~~fit from 2026-02-09, and not before~~ **now fit throughout**

> **SUPERSEDED 2026-08-10 — see §17.** Every row in the table below is now
> false: no quarter is uncovered, and Fed Funds prices 97.19 % of its legs
> under `asof` ≤60 s against SOFR's 97.58 %.

| quarter | legs | no curve | priced (asof ≤60 s) |
|---|---|---|---|
| 2024Q1 – 2025Q4 | 47,897 | **100 %** | **0 %** |
| 2026Q1 | 6,999 | 40.1 % | 58.0 % |
| 2026Q2 | 6,738 | 0.01 % | 95.5 % |
| 2026Q3 | 4,817 | 0.00 % | 98.2 % |

The asset now holds 263 days (up from 155 at the start of this session): **106
days in 2023Q3–Q4** and **155 days from 2026-02-09**. The 2023 days are real and
dense, and they are entirely before the tape starts, so they are worth nothing to
this work. **The first 23 months of the tape — 2024-03-01 to 2026-02-08 — have no
Fed Funds minute curve at all.** That is 72 % of Fed Funds legs, and it is
2,000 times larger than every lag effect in this document combined.

Tolerance is irrelevant here: loosening from 60 s to an hour moves Fed Funds
coverage from 22.91 % to 23.09 %.

### Recommended gate for the direction work

1. `SnapshotPolicy.strict(minutes=1)` — non-negotiable, it is what removes the
   circularity.
2. **Drop or flag prints outside 01:00–16:59 ET.** 5.3 % of legs, and 88.8 % of
   all future-served cases. Hour 00 alone is 100 % contaminated under the old
   rule; hours 22–23 are 12 % and 21.5 %.
3. **Record `snapshot_lag_signed_seconds` per trade** and gate downstream on it,
   rather than trusting the tolerance to have made every call equally good. The
   one-minute p99 is 0.44 bp but the max is 6 bp.
4. **Do not attempt Fed Funds direction before 2026-02-09.** Re-measure first —
   the backfill moved this asset three times during a single session.
5. A dense day is not a safe day: 1.0 % of legs on ≥1,000-snapshot days are still
   future-served, because density says nothing about 23:40 ET. Density and
   time-of-day are independent gates and both are needed.

---

## 9. How the measurement was validated

The prompt for this task, and this repo's recent history, both record the same
failure: a probe that called production's own functions with *different
parameters* concluded a day of data was unreachable, and two independent agents
confirmed the wrong answer before a production run disproved it. So:

1. **The selection rules were checked against a known-answer fixture first** —
   an unsorted window with duplicate stamps, an exact tie, a request before the
   first stamp and one after the last — with production's own expression
   (`(stamps - wanted).abs().values.argmin()` evaluated by pandas) as the oracle.
   7/7 agreed, including the tie, which resolves positionally-first.
2. **Then against production itself.** The `verify` stage samples 36 requests
   stratified across future-served, wrong-calendar-day, sparse-day, dense-day,
   large-lag and typical cases, calls the *real*
   `IRSwapsMDP._load_citivelo_excel_minute_store_point`, and compares the
   timestamp it hands back with the one the simulation predicted.
   **36/36 matched.**
3. The requested minutes are not a synthetic grid. They are every distinct
   execution minute of every leg passing `trade_selection.ELIGIBLE_LEGS_SQL`'s
   filters on `arbs_usd_swap_tape_legs_v3` (table name imported from
   `_tape_tables`, never spelled), put through production's own `snap_timestamp`.
   503,637 distinct `(index, minute)` pairs covering 2,027,870 legs.

### One thing the probe found by accident

Calling `_load_citivelo_excel_minute_store_point` **directly** — as the
verification stage does, and as downstream research code might — logs
`Stored reference_key 'USD-FEDFUNDS-1D' is not in RATESLIB_CURVE_DEFINITIONS;
falling back to act360/nyc/mf`. `register()` *does* define that curve, but it is
called by `_build_citivelo_excel_curve`, not by the loader. Anything that reaches
the loader without going through the dispatch inherits the silent
wrong-convention fallback that PR-era work already fixed once for EURIBOR. Go
through `get_data`/`_build_citivelo_excel_curve`, or call
`MDP.IRSwaps.CITIVELO_EXCEL.register()` first.

---

## 10. What changed in the code

See `MDP/IRSwaps/CITIVELO_EXCEL/snapshot_policy.py` and the PR body. In short:

- One selection function that both the single-point loader and `bulk_get_data`
  call. They previously agreed only because both spelled the argmin inline.
- `SnapshotPolicy(method, max_lag, allow_future, on_miss)`. The default is
  **bit-identical to the previous behaviour**, pinned by a test that replays the
  old expression on 200 randomised unsorted windows with duplicates.
- What is *not* opt-in: every served snapshot now publishes
  `snapshot_lag_signed_seconds`, `snapshot_served_utc`, `snapshot_requested_utc`,
  `snapshot_served_from_future` and `snapshot_same_local_date`, and the first
  occurrence of each pathology per asset is logged at WARNING.
  `snapshot_lag_seconds` stays **absolute** for the existing readers.
- `SnapshotPolicy.strict()` gives backward-only selection, a tolerance in
  minutes, and a typed `SnapshotMiss` that the loader's own `except Exception`
  handlers re-raise by name — so a strict miss cannot be converted back into the
  silent fallback it exists to prevent. A strict request can no longer reach the
  live Excel build; the midnight/EOD branch raises rather than serving the close.
- **Caller contradictions raise everywhere; data misses raise once.** A policy
  combined with `force_refresh`/`no_curve_store` or with `"live"` is a
  contradiction and raises on both paths. Everything else — no snapshot inside
  the tolerance, and an exact-midnight (end-of-day) timestamp — raises on the
  single-point path (one question, one answer or one exception) and is
  **omitted from the batch's result dict**, which is keyed by the caller's own
  timestamps, with one WARNING carrying the count. A batch that raised on the
  first of those would be unusable: 2.4 % of tape minutes have no snapshot in a
  one-minute tolerance, and 256 legs snap to exact midnight, so a single 00:01
  print would kill a day's backfill. Note there is no *lenient* answer to a
  midnight request under a minute policy — every branch that could serve it
  serves a close — so the refusal itself is not negotiable; only whether it
  takes the batch down with it.

  > This was found by an independent review, not by my own tests. The batch
  > bucketed exact-midnight requests in its *own* first pass and served them
  > from the EOD store with no policy check — reproducing the sixteen-hour
  > lookahead the single-point dispatch refuses. My bulk-vs-single agreement
  > test could not see it because every timestamp in it was intraday. Worse,
  > that test was **vacuous**: `bulk_get_data` reconstructs through
  > `CurveStore.reconstruct_curve` directly rather than the store's batch
  > method, so the fixture's rows raised, the bulk window branch took its
  > `except Exception` fallback, and the test compared the single-point loader
  > with itself. Both are fixed, and the agreement test now asserts the batch
  > did not fall back.
- `_assert_snapshot_fresh` gains `limit` and `allow_future` rather than gaining a
  rival. Its `requested - snapshot > limit` test is structurally blind to a
  *negative* lag, so no tolerance was ever going to catch a future snapshot —
  which is a second and independent reason "just wire the existing guard in"
  would not have worked, on top of its 12-hour default being three orders of
  magnitude too coarse.
- `CITIVELO_EXCEL/density.py`: count from the parquet footer, gap profile beside
  it, `covers(instant)` for the question a caller actually has.

## 11. What I could not determine

- **Whether the tape's own execution timestamps are accurate to the minute.**
  Everything here measures the store against the timestamp the tape reports. If
  `original_execution_timestamp` is itself rounded or delayed, that is a second
  error source this measurement cannot see and does not bound.
- **Whether Citi's published minute is the minute the market traded.** The wire
  zone is established (America/New_York, measured 2026-08-07), but publication
  latency inside a minute is not measured here.
- **Fed Funds coverage after the running backfill completes.** It moved during
  the session; the 76 % figure is a snapshot, not a conclusion.
- ~~**Whether the 01:00 ET session start is a Citi property or a fetch-window
  property.**~~ **ANSWERED 2026-08-10 — see §12–§16.** It is Citi's: the fetch
  already requests from local midnight and gets nothing back, and the same code
  returns clean 08:00–19:59 *local* sessions for every other currency. The guess
  that fixing the fetch would be "worth more than anything in the patch" was
  wrong twice over — hour 00 is irrecoverable, and the fetch-side defect that
  does exist is worth 12.6 % of the future-serving on SOFR.
- **The other eighteen minute curves.** Only `USD-SOFR-1D` and
  `USD-FEDFUNDS-1D` were measured, because they are what the direction work
  needs. `SnapshotPolicy.strict()`'s one-minute default applies to all twenty;
  the EUR/GBP/JPY/AUD minute assets have different session hours and were not
  checked. The lag *mechanism* is shared, but the numbers are not transferable.
- **Whether the tolerance should vary by tenor.** Drift is nearly flat across
  2Y/5Y/10Y/30Y at every elapsed time measured (p90 within ~0.03 bp of each
  other at one minute), so a single tolerance looks right — but that was
  measured on par rates, not on the package structures the direction work will
  actually classify.

---

## Appendix — the tests fail on `main`

The prompt asked for tests that reproduce each failure mode against the *current*
code and then pass. Two of them (`test_the_shipped_argmin_rule_can_pick_the_future`,
`test_the_shipped_window_spans_neighbouring_days`) are written against the
expression that shipped, so they keep demonstrating the defect regardless of what
the loader is changed to. The rest need the new API to express the property, so
they were re-written against `main`'s API and run in a clean `main` worktree.

All six fail there, and the equivalents pass on the branch:

```
$ python -m pytest tests/test_zz_prefix_evidence.py -q          # clean main worktree
FFFFFF                                                                   [100%]
E   KeyError: 'snapshot_served_from_future'                    tests/...:84
E   KeyError: 'snapshot_same_local_date'                       tests/...:95
E   ModuleNotFoundError: No module named 'MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy'
E   ModuleNotFoundError: No module named 'MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy'
E   ModuleNotFoundError: No module named 'MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy'
E   TypeError: CurvePricer.__init__() got an unexpected keyword argument 'curve_kwargs'

FAILED test_1_future_snapshot_is_reported
FAILED test_2_wrong_calendar_day_is_reported
FAILED test_3_a_backward_only_lookup_is_available
FAILED test_4_a_strict_miss_does_not_reach_the_live_excel_build
FAILED test_5_bulk_refuses_a_midnight_request_under_a_strict_policy
FAILED test_6_the_warmer_builds_on_the_pricers_terms
6 failed
```

One name has since drifted: the branch equivalent of
`test_5_bulk_refuses_a_midnight_request_under_a_strict_policy` is now
`test_bulk_drops_a_midnight_request_under_a_strict_policy`, because the batch was
changed after this evidence was captured to drop-and-count rather than raise (a
single 00:01 print would otherwise kill a day's backfill). The property it pins
on `main` is unchanged: `main` serves the close and says nothing.

Tests 1 and 2 matter most: their *fixture* assertions passed on `main` — the
served snapshot really was `10:05` for a `10:04` request, and really did come out
of the previous day's partition — and only the assertion that this is *reported*
failed. So `main` does the wrong thing and says nothing, which is the whole
finding in two lines of pytest output.

## Appendix — pre-existing test failures

The fast gate (`pytest tests -m "not slow and not network and not db"`) was run in
a clean `main` worktree before any change: **6,246 passed, 3 failed**, 32 min.
The three are pre-existing and unrelated:

- `tests/test_citivelo_catalog.py::test_bond_universe_matches_the_harvest`
- `tests/test_eod_vectorized_engine.py::TestPerformance::test_252_dates_200_tenors_under_5s`
- `tests/test_identifiers.py::test_corpus_is_present_and_large`

The same gate on the branch tip: **6,382 passed, 2 failed**, 29 min. The failure
set is a strict **subset** of the baseline —

- `tests/test_citivelo_catalog.py::test_bond_universe_matches_the_harvest`
- `tests/test_identifiers.py::test_corpus_is_present_and_large`

— so no test that passed on `main` fails on the branch. The third baseline
failure, the 5-second performance budget, *passed* here; it is a wall-clock
assertion and the machine was running a curve backfill during the `main` run, so
treat it as load-sensitive rather than as anything this branch changed.

---
---

# Part II — 2026-08-10: the 01:00 ET boundary, and Fed Funds after the backfill

Two things changed after Part I was written. An overnight Citi backfill filled in
`USD-FEDFUNDS-1D`, which invalidates §6 and half of §8. And §11's open question —
whether the ~01:00 ET session start is Citi's or our fetch window's — has been
answered.

Reproduce with `scripts/citivelo_minute_lag_audit.py session`. Store state as
measured 2026-08-10: `USD-SOFR-1D-CITIVELOEXCELMIN` 1,237 days,
`USD-FEDFUNDS-1D-CITIVELOEXCELMIN` 926 days.

The whole measurement was re-run from `density` through `lag` against today's
store, and the `verify` stage re-checked against production on it: **36/36
predictions matched** again. The store is still being written to — the backfill
has ~1,900 day parquets left to build — so treat every count here as a stamp, and
re-run rather than quoting.

## 12. The answer: the boundary is Citi's, and I was wrong about what it was worth

§11 said: *"whether the ~01:00 ET session start is a Citi property or a
fetch-window property … If it is a fetch-window property, fixing it removes most
of the hour-00 contamination outright, which would be worth more than anything in
the patch."*

**It is a Citi property.** Citi does not publish USD curves between 23:00 and
00:59 ET on any night. Every leg printed in the 00:xx ET hour is therefore
*unclassifiable at minute resolution*, permanently, and no change to the fetch
reaches a single one of them.

There *is* a real fetch-side defect — §15 — but it is worth **12.6 %** of the
future-serving on SOFR, not "most" of it. The speculation was wrong in both
directions: wrong about the cause, and wrong about the size.

## 13. How that was established

Five tests, each of which could have gone the other way.

1. **The fetch already asks for the whole day.**
   `scripts/citivelo_excel_intraday_warm.py::_wire_instant` converts *local
   midnight* to the wire zone and uses it as the chunk bound. For USD the local
   zone **is** the wire zone, so every chunk is requested from 00:00 ET. The
   00:00–00:59 ET hour is requested, every day, and comes back empty. Nothing
   between the fetch and `_write_day_parquet` filters rows.
2. **The same code produces clean sessions elsewhere.** From the identical
   full-local-day request, `GBP-SONIA-1D` returns 08:00–19:59 **London** on
   105/105 Monday–Friday days, and EUR/JPY/CAD likewise in their own zones. The
   fetcher is plainly not imposing a window; it is receiving one.
3. **The boundaries are anchored in two different clocks** (§14). A fetch
   artifact is anchored in one clock — whichever the chunking uses.
4. **US holidays publish normally.** Checked on eighteen. 2025-12-25 holds 1,318
   rows running 01:00–22:59 ET, indistinguishable from a control Wednesday.
5. **The interior gaps are single minutes.** Across 50 sampled dense days, 96 %
   of the missing interior minutes are isolated singletons and the longest run is
   4 minutes. A dropped fetch window would be a contiguous block.

## 14. The session, measured

Over 815 stored days of `USD-SOFR-1D` and 794 of `USD-FEDFUNDS-1D` (2024 onward),
split by DST regime so that each boundary's *anchoring* is established rather
than assumed:

| boundary | EDT (Jun–Aug) | EST (Dec–Feb) | anchored in |
|---|---|---|---|
| first row, Mon–Thu | 01:00 ET = 05:00 UTC | 01:00 ET = 06:00 UTC | **New York** |
| last row, Mon–Thu | 22:59 ET = 02:59 UTC | 22:59 ET = 03:59 UTC | **New York** |
| last row, Friday | 17:59 ET = **21:59 UTC** | 16:59 ET = **21:59 UTC** | **UTC** |
| first row, Sunday | 17:00 ET = **21:00 UTC** | 16:00 ET = **21:00 UTC** | **UTC** |

138/144 and 138/140 Mon–Thu days start at exactly 01:00 ET; 33/36 and 34/34
Fridays end at exactly 21:59 UTC; 36/36 and 32/33 Sundays start at exactly
21:00 UTC.

**The week runs on a UTC clock and the day runs on a New York clock.** So:

- opens **Sunday 21:00 UTC**, closes **Friday 22:00 UTC** (last row 21:59);
- **no rows between 23:00 and 00:59 ET**, any night — a two-hour nightly hole;
- nothing at all on Saturday;
- no holiday calendar.

Both US DST transitions fall on a Sunday, and this session is shut all Sunday
morning — so the skipped hour and the repeated hour never touch a published USD
minute. That is luck, but it is worth knowing.

This is now `MDP/IRSwaps/CITIVELO_EXCEL/citi_session.py`. It **raises** for any
curve whose anatomy was not measured: the non-USD assets run 12 hours in their
own zone against USD's 22, so extrapolating would report most of a GBP trading
day as unpublished — wrongly, and confidently.

## 15. What *is* ours: days cut short by a chunk boundary

Roughly 19 % of Mon–Thu days stop at **23:59 UTC** — 19:59 ET on daylight time,
18:59 ET on standard — instead of 22:59 ET.

That is not a market event:

- the count is **27/144 (EDT) and 27/140 (EST)** — identical on a UTC clock;
- on **190 dates** one USD curve stops early while the other, fetched in a
  separate run, runs to 22:59 ET;
- **zero Fridays** are affected, because Friday's real close (21:59 UTC) is
  already earlier than the artifact's boundary.

The mechanism is in `citivelo_excel_intraday_warm.py`: a day's parquet is written
once and never rewritten (`if out.exists() and not force: continue`), and a whole
window is skipped when every weekday in it is already on disk. So when a chunk
boundary falls inside a local day, whichever half is written first freezes the
day, and no later run completes it.

Current backlog, by cause — `session_repair_list.csv`:

| curve | cause | days | missing minutes |
|---|---|---|---|
| `USD-SOFR-1D` | ten-minute era (needs a 1-min refetch) | 255 | 255,241 |
| `USD-SOFR-1D` | **truncated end (chunk boundary)** | **161** | **33,832** |
| `USD-SOFR-1D` | interior gaps | 65 | 12,153 |
| `USD-FEDFUNDS-1D` | **truncated end (chunk boundary)** | **141** | **30,034** |
| `USD-FEDFUNDS-1D` | interior gaps | 96 | 20,705 |

The ten-minute era is already the running backfill's target. The 302
truncated-end days across the two curves are the self-inflicted part.

## 16. Recoverable vs not

Every requested minute on the tape, split by *why* it is or is not answerable:

### `USD-SOFR-1D` — 1,961,419 legs, 21,451 future-served

| class | legs | share | future-served | of all future-serving |
|---|---|---|---|---|
| exact minute present | 1,889,619 | 96.34 % | 0 | — |
| **Citi publishes nothing** | 30,188 | 1.54 % | 16,343 | **76.2 %** |
| in-session interior gap | 27,072 | 1.38 % | 2,415 | 11.3 % |
| in-session, outside stored span | 14,540 | 0.74 % | 2,693 | **12.6 %** |

### `USD-FEDFUNDS-1D` — 66,451 legs, 1,094 future-served

| class | legs | share | future-served | of all future-serving |
|---|---|---|---|---|
| exact minute present | 63,752 | 95.94 % | 0 | — |
| Citi publishes nothing | 604 | 0.91 % | 337 | 30.8 % |
| in-session interior gap | 941 | 1.42 % | 79 | 7.2 % |
| **in-session, outside stored span** | 1,154 | 1.74 % | 678 | **62.0 %** |

**Repairing every truncated day removes 12.6 % of SOFR's future-serving and 62 %
of Fed Funds'.** The interior gaps are Citi's own missing minutes (§13.5), so on
SOFR **87.5 % of the contamination is irrecoverable** and the gate built in Part I
is the only remedy. On Fed Funds the balance is the other way round, and the
repair is worth doing before that curve is used for direction work.

## 17. Fed Funds, re-measured — §6 and §8 are obsolete

The overnight backfill took `USD-FEDFUNDS-1D-CITIVELOEXCELMIN` from 155 stored
days to **926**, and the coverage cliff is gone:

| | Part I (2026-08-09) | now (2026-08-10) |
|---|---|---|
| legs with no warmed window | **50,702 (76.3 %)** | **0** |
| legs served the exact minute | — | 63,752 (95.94 %) |
| priced under `asof` ≤60 s | 22.9 % | **97.19 %** |

By quarter, every quarter is now usable — the 2024Q1–2025Q4 "100 % no curve" rows
in §8 are **false as of today**:

| quarter | legs | no curve | exact minute | priced (asof ≤60 s) |
|---|---|---|---|---|
| 2024Q1 | 1,867 | 0.00 % | 97.86 % | 98.82 % |
| 2024Q2 | 4,061 | 0.02 % | 97.05 % | 98.92 % |
| 2024Q3 | 6,767 | 0.00 % | 97.67 % | 98.58 % |
| 2024Q4 | 6,500 | 0.00 % | 94.82 % | 95.28 % |
| 2025Q1 | 4,918 | 0.02 % | 98.27 % | 98.96 % |
| 2025Q2 | 6,098 | 0.00 % | 94.69 % | 97.87 % |
| 2025Q3 | 9,243 | 0.00 % | 95.73 % | 96.77 % |
| 2025Q4 | 8,443 | 0.00 % | 94.74 % | 96.02 % |
| 2026Q1 | 6,999 | 0.00 % | 97.17 % | 97.33 % |
| 2026Q2 | 6,738 | 0.01 % | 94.02 % | 95.47 % |
| 2026Q3 | 4,817 | 0.00 % | 95.95 % | 98.15 % |

**Fed Funds is now fit across the whole tape span, on the same terms as SOFR**
(97.19 % vs 97.58 % priced at 60 s). The single largest constraint in Part I has
been removed by someone else's work, not by this branch.

The SOFR numbers are unchanged to two decimal places against Part I, which is the
control that says this is a comparable re-measurement rather than a different
measurement.

## 18. Handover note — a collision with `feat/citivelo-snap-history`

`scripts/citivelo_deep_intraday_warm.py::_already_dense` on that branch documents:

> *"a Sunday-evening partial is ~180 published minutes; Fridays end at 17:59 local
> against Monday-Thursday's 19:59"*

For the two USD curves the measured Monday–Thursday close is **22:59 ET**, and
**19:59 ET is precisely the truncation signature** (23:59 UTC). A completeness
gate built on that model marks the 302 truncated days *complete*, so a repair pass
would skip exactly the days that need it.

The Sunday and Friday halves of that comment are right, and non-obvious — Sunday
really is a ~180–420 minute evening, and Friday really does end early. It is only
the Monday–Thursday close that is off, and it is off in the direction that hides
this defect.

I have deliberately **not** edited those files. That branch owns them and is
running; a repair belongs there, driven by `session_repair_list.csv`, and it needs
a merge-on-write rather than `--force` — forcing a day whose re-fetch is itself
partial would replace good data with worse.

## 19. What this changes in Part I

- **§11's open question is answered.** The boundary is Citi's, and the fetch fix
  is worth 12.6 % of the future-serving on SOFR, not "most" of it. Part I's
  recommendation stands unchanged and is, if anything, more important: since most
  of the contamination cannot be fetched away, gating and marking is the remedy.
- **§6 and the Fed Funds half of §8 are obsolete**, superseded by §17.
- **The recommended gate gains one rule.** Drop or flag prints outside Citi's
  published session (`citi_session.publishes`) *before* judging them by lag. A
  Friday 20:00 ET print and a Monday 20:00 ET print look identical from the
  store — the stored day just stops — and one is the weekend while the other is a
  repairable hole.
