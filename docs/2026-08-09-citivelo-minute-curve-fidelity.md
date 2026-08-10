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

### `USD-FEDFUNDS-1D` — **fit from 2026-02-09, and not before**

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
- **Whether the 01:00 ET session start is a Citi property or a fetch-window
  property.** The measurement shows the first row of the day is ~01:00 ET
  consistently; whether earlier data exists upstream and is simply not being
  requested was not tested.
