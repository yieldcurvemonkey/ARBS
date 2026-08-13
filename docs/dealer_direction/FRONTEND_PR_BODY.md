# Dealer direction and the risk-bucket ladder, in front of a tape user

Branch `feat/tape-direction-frontend`, off `origin/main`. **Not for merge as
is** — the full backfill is still running; see *Unfinished* at the bottom for
exactly what is and is not done.

PR #441 built the inference. This puts it on screen, and builds the data seam
that makes that possible. It does not touch the inference.

---

## The architectural fact this is shaped by

Direction cannot be computed at request time. It needs `rateslib`, the local
Citi Velocity minute curve store — a DuckDB/parquet cache the web tier cannot
reach — and, measured on this box, **57 s of CPU per tape day**. So a batch job
materialises it and the front end reads it.

**Four tables, split on the cost line**, so a defect in the cheap half never
costs a re-run of the expensive half:

| table | grain | cost |
|---|---|---|
| `arbs_dd_unit_v1` | one row per unit = one row of the display view | expensive |
| `arbs_dd_unit_bucket_v1` | (unit × tenor bucket), signed | expensive |
| `arbs_dd_coverage_v1` | (date, bucket, venue, series, **reason**) → DV01 | cheap |
| `arbs_dd_ladder_v1` | `indicator.CELL_COLUMNS`, verbatim | cheap |

plus `arbs_dd_runs_v1`, because exit code 0 is not evidence a day produced rows.

`price` is per-day and parallel and writes parquet; `publish` is whole-window
and writes Postgres. The ladder is rebuilt **wholesale** every run, never
appended: `indicator`'s adjusted level divides by `mean(coverage)` over the
full sample and `z` is a trailing-250 statistic, so extending history restates
earlier cells. An appended table would mix cells computed against different
sample lengths with nothing saying so.

---

## The brief's join key was wrong, and it was worth measuring on day one

The brief asserts that the display view's `package_id` *is* the direction
feature's `unit_key`. It is not. Measured on 2026-04-01: the two agree on the
**grain** exactly — 2,752 view rows, 2,752 units, no nulls — and on **27.47%
of the keys**.

`universe.py:614` sets `unit_key = trade_id` for a single-leg unit, while the
view keys that same row by its `package_id`. A single-leg print that
nonetheless carries a package id (`MATCHED_MATURITY_…`, `SPREADOVER_…`) is
most of the tape.

Over five days spanning the whole tape:

| day | view rows | units | `package_id` | view-only | unit-only | `unit_key` |
|---|---:|---:|---:|---:|---:|---:|
| 2024-07-01 | 2,364 | 2,364 | **100.0000%** | 0 | 0 | 29.27% |
| 2025-01-15 | 2,817 | 2,817 | **100.0000%** | 0 | 0 | 28.36% |
| 2025-10-17 | 2,502 | 2,502 | **100.0000%** | 0 | 0 | 21.70% |
| 2026-04-01 | 2,752 | 2,752 | **100.0000%** | 0 | 0 | 27.47% |
| 2026-08-07 | 2,341 | 2,341 | **100.0000%** | 0 | 0 | 25.89% |

Both keys are stored. `unit_key` is the backend's identity and every
`dealer_direction` frame is keyed on it; `package_id` is what the front end
joins. Deriving one from the other at read time would put the `n_legs <= 1`
branch in a SQL `CASE` on the web tier, which is where it would be got wrong.

---

## What is on screen

**The tape grid gains a Dealer column.** `RCVD` / `PAID` with a conviction bar
under it, and an abstention that names its reason rather than leaving a blank —
a blank reads as "no flow" when it means "we declined", and those are different
facts. A day the batch has not reached shows `—` with "not computed", which is
a third state and is not the same as either.

**A full-width risk-bucket panel** at the top of the analytics dashboard, in
two panes that are deliberately not interchangeable:

* **left — cross-bucket `z`**, ten buckets × sixty sessions as a heatmap, with
  each bucket's latest `z` and coverage on its row. Click a row to select it.
* **right — one bucket's own history**, the actual signed DV01 as daily bars.

**Coverage is next to every aggregate**, and it is the click target for the
breakdown by reason and DV01 share.

---

## What it structurally cannot draw

A signed-DV01 bar chart across tenor buckets. It is the first chart anyone
would draw and it is wrong: DV01 retention runs **0.761 at 0-1Y down to 0.495
at 15-20Y**, a 1.54× cross-bucket scaling distortion, because the packages the
classifier cannot orient are not a random sample.

> "The 5y bucket against its own history" is supportable.
> "Dealers are longer 5y than 10y" is not.

The Python module refuses it structurally rather than in a docstring. Three
controls carry that across the seam, **none of them a comment**:

1. `/direction/bucket` takes exactly one `bucket` and **400s** on a list, on a
   repeat, and on no bucket at all — with the retention numbers in the message.
   It does not default to "all buckets", because the friendly default would
   ship the forbidden view by accident.
2. levels leave bucket-suffixed (`delta_dv01__5_7Y`), exactly as Python names
   them, so two responses do not align into a comparison.
3. `/direction/standardised` selects no level, and `assertNoLevelKeys` **500s**
   if one ever reaches the payload. The SELECT list is a list and lists get
   edited; that assertion is what survives the edit. `assertNotCrossBucketLevel`
   does the same on the client, on every frame that reaches a chart.

`z` may cross buckets because `z = (r·L − r·μ)/(r·σ) = (L − μ)/σ` — a constant
retention factor cancels exactly.

**No cumulative view.** Compression and allocation are never publicly reported,
so a running sum accumulates an unbounded, monotone error with no offsetting
print. The level is drawn as daily bars rather than a line so it does not read
as a stock.

**Three venue series, never merged.** D2C, D2D and `VENUE_UNKNOWN` are a
toggle, not a sum, and `venueClass=ALL` is a 400.

---

## The diverging pair is a measurement, not a preference

The house pass/fail pair is emerald/rose. Through the palette validator against
a dark surface:

```
emerald #34d399 vs rose  #fb7185   deuteranopia  ΔE  4.6   FAIL
sky     #38bdf8 vs amber #f59e0b   protan        ΔE 25.5   PASS
                                    tritan        ΔE 27.5   PASS
```

A red-green viewer cannot separate "dealer received" from "dealer paid" in the
emerald/rose pair at all. On a chart whose entire content is a sign, that is
the chart failing to say anything. One pair — sky = received/long, amber =
paid/short, neutral grey at the midpoint — used in the badge and every mark,
and identity is never colour alone: the badge carries the word.

---

## Measured cost

Per-day, on this box (32 cores, 64 GB), against a fully warm curve store:

| stage | measured |
|---|---|
| `price`, one tape day | **57 s** single process (2,752 units, 2,098 priced, 58,520 KRD rows on 2026-04-01) |
| `price`, 8 workers | ~60 s of wall clock per 2.5 days |
| `price`, full tape | **609 days in 114.4 min** at 8 workers (11.3 s/day wall), 0 errors |
| one `Calibration.fit` | 42.1 s over 550 fitted buckets — *measured under contention* |
| rolling calibration, full tape | **121 fits in 41.5 min** on a free box (20.6 s/fit), then cached |
| `publish`, one day | 6.5 s contended, **~4 s** on a free box |
| ladder rebuild + write | seconds; 2,006 cells for a 29-day window |

The backend's own estimates were 115 s repricing + 65 s key-rate = 180 s/day.
Measured together against a warm minute store, with the projector taking the
repricer's own pricer, a day costs a third of the sum.

## Measured read cost

`scratch/ddfe06_read_cost.py`, 5 reps each, against prod over the pooler:

| query | median | p95 |
|---|---:|---:|
| tape grid, 200 rows, **no** direction join | 133.2 ms | 337.4 ms |
| tape grid, 200 rows, **with** the join | **128.0 ms** | 141.7 ms |
| `/direction/bucket` — one bucket, whole history | 13.4 ms | 17.2 ms |
| `/direction/standardised` — ten buckets | 17.2 ms | 18.3 ms |
| `/direction/coverage` — breakdown by bucket | 17.0 ms | 20.6 ms |
| `/direction/summary` | 40.8 ms | 43.7 ms |
| per-trade drill-down by `package_id` | 15.9 ms | 18.5 ms |

**The join is free.** `EXPLAIN (ANALYZE, BUFFERS)` shows `Index Scan using
arbs_dd_unit_v1_pkey`, **0.004 ms per row over 200 loops**.

## Defects this found

Four, and every one of them was caught by a guard rather than by looking.

**1. `if nan:` is `True`, and it excluded every package unit.**
`pkg_exclusion` is only assigned on a `PKG` unit; on a day where no package is
refused, no row assigns it, `reindex` creates it as an all-NaN **float64**
column, parquet round-trips that as float64, and `bool(nan)` is `True` — so a
presence test on a string field fired on every package unit and handed the
reason `nan` downstream. **No symptom of its own**: the units would have
shipped as abstentions with a blank tooltip and the ladder would have been
quietly short. It surfaced only because the coverage accounting is required to
be a partition and refuses a unit with no reason.

**2. The coverage headline was 22 points too flattering.** It summed
`coverage_dv01_kept / coverage_dv01_total` over the *ladder*, and a ladder cell
only exists where at least one unit was oriented — so the average conditions
on the very thing it measures. **67.0% against a true 44.8%**, on the one
number whose entire job is to stop the panel reading as complete. Now read
from `arbs_dd_coverage_v1`, which is a partition by construction.

**3. The two clocks do not share a day boundary.** The tape's `as_of` day
starts 20:00 ET the previous evening; the ladder stamps a New York
*availability* date. Publishing `as_of >= SAMPLE_FLOOR` produced 1,050 rows
stamped **the day before the floor**, and `indicator.build` refused the whole
run over it. Dropped; nothing that belongs to a published day goes with them.

**4. The level and the coverage are on two different grids** — INDICATOR.md §2
says so and this is where it bites. rateslib's delta is non-zero at all 28
pillars (measured: 28.0 rows per unit), so one 10Y trade publishes a level cell
in every bucket while its gross DV01 matures in one. 187 of 1,420 cells had a
level and no denominator. Dropped, at a measured **0.253% of |delta_dv01|**,
rather than mixing two populations inside one fraction. Nothing had exercised
this before: the backend built the coverage frame alone, and INDICATOR §6
records that no composed pipeline existed to put a KRD-derived level beside it.

## A finding for the backend owners: FOMC-dated swaps

Not a defect in this branch, and not something this branch changes — improving
the inference is out of scope. But it is the kind of thing that has to be said
out loud rather than left in the data.

**The rate-index routing is provably correct.** `curve_for` raises
`UnsupportedIndex` rather than defaulting; `krd` keys its solver on
`(rate_index, curve_name, block)`; on the published rows SOFR →
`USD-SOFR-1D` (45,551) and FED_FUNDS → `USD-FEDFUNDS-1D` (2,087), with **zero
mismatches**, and Fed Funds deviations sit at a median +0.068 bp — centred,
not offset by a basis.

**The FOMC-dated population is a different matter.** Median |deviation|, same
days, same rules:

| | FOMC-dated | everything else | |
|---|---:|---:|---:|
| FED_FUNDS | **1.994 bp** | 0.295 bp | **6.8×** |
| SOFR | **0.697 bp** | 0.174 bp | **4.0×** |

and the per-meeting median flips sign by 1–2 bp — JUL24 **+1.600** (83.7%
above mid), SEP24 **−1.230** (33.5%). That is the F-20 signature, the exact
statistic that condemned the Barchart curve.

**SOFR and Fed Funds flip together**, same direction, similar magnitude. A
routing fault would make them disagree. Both moving together says the fault is
in what the curve *is*: the Citi minute curve is a smooth par curve with no
discrete FOMC steps, so a meeting-to-meeting swap is repriced against a model
that averages across the very step it trades.

Controls run first: `fomc_meeting_label` is on 2,111 of 3,116 FOMC legs and on
**zero** legs of every other structure type, so it is a structure tag rather
than a proximity tag; de-duplicating the leg join moved the numbers by under
0.1 bp.

**Size** — 1,918 units, 3.33% of the ladder's gross DV01, but **28.17% of the
0–1Y bucket**, the meeting-dated front end.

What this branch does instead of touching the inference: `special_tenor_type`
is persisted per unit and joined onto the tape row, an FOMC-dated row says so
in its tooltip and calls its own direction unreliable, and 0–1Y carries a
pinned caveat with the measurement — the same spirit as the module's own
`PINNED_DRIFT_BUCKETS`.

**Suggested follow-up**, not taken here: FOMC-dated units are a candidate for
their own exclusion reason, or for a meeting-step curve.
`WHAT_THE_LADDER_SUPPORTS` §3 lists Fed Funds as a low-confidence condition;
on this evidence the sharper statement is that *meeting-dated structures on
either index* are the low-confidence population, and Fed Funds looks worse
mainly because it is 66% of them.

---

And one assumption checked rather than trusted: `RepricedUnit.legs[i]` is
paired positionally with `unit.legs.iloc[i]`, so a misalignment would match the
wrong per-leg fee to the wrong NPV and hand `package_price.classify` a
scrambled input — a confident, wrong orientation with no symptom. Measured on a
real day: **0 mismatches over 621 multi-leg units**, and the probe refuses to
pass if the sample contains no multi-leg unit. Asserted in the code as well.

---

## The chart's mid line is now the real 1-minute grid

The intraday prints chart was specced before `arbs_dd_curve_mid_v1` existed, so
it drew its line by joining the prints to each other — `mid = traded −
deviation/100` at each mark, a polyline through wherever somebody happened to
trade. The grid now exists (22.7M rows, 639 days, both indices), so the line is
a curve.

**Two different objects share that axis and they no longer render alike:**

| | what it is | drawn as |
|---|---|---|
| the LINE | `arbs_dd_curve_mid_v1` — a modelled par rate every minute, from the same `SessionBranchPricer` against the same Citi minute curve that repriced every mark | solid, no dots |
| each MARK's mid | `traded − deviation/100`, exact for that print, and what `deviation_bps` — hence the direction call — is measured against | kept, and diffed against the line |

**They agree where they are the same instrument.** Measured over 3,206 OUTRIGHT
prints on 7 days spanning the window, joined at the minute of each print's *own*
curve snapshot:

| | n | median resid | p95 abs | max abs |
|---|---|---|---|---|
| SOFR STANDARD | 2,850 | **0.000000 bp** | 0.132 bp | 15.62 bp |
| SOFR IMM | 334 | 0.000000 bp | 0.010 bp | 1.49 bp |
| FED_FUNDS STANDARD | 19 | 4.4e-14 bp | 0.276 bp | 0.276 bp |

The median is *exactly* zero because a spot STANDARD swap and the grid point are
the same instrument priced by the same code. **The tail is the instrument
differing, not the mid**: of the 9 prints beyond 0.5 bp the median maturity gap
to the grid's canonical swap is 6 days and the median effective-date gap 4 days,
and **not one is an exact instrument match** — against 62.5% exact in the
sub-0.5bp population. So the residual is a **chip on screen** (`mark vs line:
med / p95 / max / n`) rather than a hidden assertion: a reader who sees a mark
off the line gets the number instead of guessing whether the chart is broken.

Verified end to end through the running API, not just in the unit tests —
median residual **+0.000000 bp** at 2Y, 5Y, 10Y and 30Y.

**The line breaks rather than bridging, at a measured threshold.** On SOFR 10Y
across those 7 days the consecutive intra-day gap is 1 min 8,293×, 2 min 170×,
3 min 17×, 4 min once and 5 min once — and **no intra-day gap exceeds 5 minutes
on any of the seven days**, while the narrowest genuine hole (23:00–00:59 ET,
Citi's publication gap) is ~2 hours. 10 minutes sits two orders of magnitude
clear of both sides.

**I dropped the LOCF plan I had written down.** Carrying the last point across a
two-hour hole draws a flat line asserting the mid did not move, when the truth
is that no curve exists there. The panel's governing rule is that a blank
carries its reason, so the line breaks and the gap is disclosed. Prints inside
the hole (measured 102 of 5,401, 1.9%) were repriced off a stale snapshot under
the out-of-session policy, which their own tooltip shows.

**Where there is no grid, the panel says so in amber.** SOFR carries all eight
chart tenors; **Fed Funds carries 12 tenors and has no 7Y, 20Y or 30Y**. Those
fall back to the reconstruction, labelled, with the dashed swatch and a
different caption — a legend that described a chart other than the one on screen
would be believed. Worth stating precisely: **no Fed Funds day anywhere in the
tape has ≥12 prints at 7Y/20Y/30Y**, so this is a guard that does not fire on
today's data rather than a routine path.

12 mutations of this logic were applied and **all 12 killed** — including
matching the residual on the execution clock instead of the curve clock (which
would manufacture a disagreement the chart then reports), selling the modelled
line as a quote in the disclosures, and looking the grid up by the ±6-month band
column.

---

## Tests

| suite | count |
|---|---|
| `route.logic.test.ts` + `route.test.ts` (the refusals, pure and wired) | 38 |
| `dealerDirection.test.ts` (the sign at the render seam) | 22 |
| `DealerLadderPanel.helpers.test.ts` (the guard, the ramp) | 18 |
| `dealer-direction-tables.test.ts` (generation, join key) | 8 |
| `test_dealer_direction_materialise.py` | 36 |
| `test_dealer_direction_sign_trace.py` + its TS half | see below |

**Mutation: 21 of 21 killed**, with the clean tree verified green first
(`scratch/ddfe03_mutate_frontend.py`). The mutations are specific lies: the
direction words swapped, the tone inverted, conviction reading `p` instead of
`|2p−1|`, the CVD-unsafe pair restored, the bucket-list refusal disabled, the
level-key assertion made a no-op, the suffixing removed, the join key changed
to `unit_key`, the LEFT JOIN made INNER, a hue put at the diverging midpoint,
the ramp poles swapped, a missing cell rendered as `z = 0`.

**Python fast gate** (`-m "not slow and not network and not db"`):
**7,650 passed, 1 failed**, 56 skipped, in 31 min.

**Pre-existing failures, unrelated, all three confirmed on a clean tree:**

- `LegsSubTable.test.ts`, `MmsTab.test.tsx` — 4 tests. Confirmed by stashing
  this branch's changes and re-running: identical failures.
- `test_citivelo_excel_supervisor.py::test_not_signed_in_means_keep_waiting` —
  confirmed by running it on `main` in the primary checkout, where it fails
  identically. It is Excel-supervisor code this branch does not touch, and it
  takes 335 s on its own, so it is waiting on real Excel state.

---

## The backfill is complete

`price` **609 days in 114.4 min** at 8 workers, 0 errors.
`publish` **527 days, 9,571,690 unit-bucket rows, 37,740 ladder cells over
629 sessions, 62.1 min.**

Fourth attempt. The first three were lost to a transient read-only database
and two OOMs; all three are fixed rather than worked around — write retry with
a classifier pinned in both directions, the ladder's input streamed to disk,
and a `ladder` stage so that step never costs the 527-day loop again.

The probability clip fired **16 times over 1.28M units, worst 2.2e-16** — one
machine epsilon, exactly the boundary it exists for.

## Sanity gate on the published rows

`scratch/ddfe10_published_sanity.py`, eight thresholds fixed before running.
The headline is the best evidence in this branch that the wiring is right:

Over the **full** history, 1,283,522 units:

| | this branch | the frozen classifier / the backend's own sample |
|---|---:|---:|
| `RATE_VS_MID` share PAID | **50.67%** over 673,038 calls | 78.3% |
| median (printed − mid) | **−0.0011 bp** | +0.021 bp (F-15, sampled independently) |
| share above mid | 49.7% | 55.5% |
| OUTRIGHT sign agreement | 18 of **695,738** disagree, all 18 explained | — |
| multi-leg control | 67,195 of 256,483 net the other way | — |
| coverage | 50.42% of DV01 oriented | — |
| unit table ↔ display view on `package_id` | **1,283,522 = 1,283,522 = 1,283,522** | — |

A median of −0.0011 bp across 673,038 prints is the strongest available
statement that the mid is unbiased — and it is a number the old classifier's
78.3% one-way label set could not have produced.

Two of the eight failed first time and both were the check, not the data —
written up in `FRONTEND_LEDGER.md` G-6c, including the control that keeps the
sign check from being able to pass vacuously.

## Performance: measured, then fixed

Measured on a production build (`next build && next start`), warm, five repeats.
Full numbers in `FRONTEND_LEDGER.md` G-16/G-17.

**The bug the measurement found.** `<Scatter data={[]}>` does not draw nothing --
recharts falls back to the **chart's** `data` prop, here the 1-minute mid grid,
and emits one empty `<g>` per grid minute. Package-legs and off-market are both
off by default, so the ordinary case paid two of them: **2,332 scatter-symbol
nodes on a day with 72 marks**, and 2,643 on the busiest day (= 2 x 1,164 grid
points + 313 real marks, exactly). Three-line guard; the marks were never the
cost.

| | before | after |
|---|---:|---:|
| scatter symbols, default day | 2,332 | **72** |
| prints panel DOM nodes | 2,707 | **443** |
| chart mutations on a date change | 5,022 | **436** |
| `/standardised` payload | 3,322 KB | **487 KB** |
| `/standardised` warm | 102 ms | **30 ms** |
| click Analytics -> z grid drawn | 817 ms | **166-226 ms** |
| cold Analytics tab, total bytes | 3,938 KB | **1,103 KB** |
| FCP | 996 ms | **552 ms** |

**A dated outage is gone.** `/standardised` returned all 6,290 rows of history
while the heatmap draws 60 sessions. At a measured 5,407 B per session, Vercel's
4.5 MB serverless response cap was **244 trading sessions away -- about 11.6
months -- and past it the panel 500s rather than slows.** It is now windowed over
DISTINCT `visibility_date` (never a row limit, which would slice mid-session and
render as "nothing was oriented in 20-30Y today"), the response carries
`sessions`/`truncated`, and a unit test asserts the default *and* the maximum
stay under the cap with headroom.

**The heatmap no longer waits on `/summary`**, which it does not read. That call
is still ~400 ms and still correct; it just no longer gates a chart.

**Two defects the e2e suite was hiding**, both found by running it against the
production build:

- Puppeteer's default 800x600 viewport renders **zero** tape rows (0 vs 31 at
  1680px), so every spec waiting on a row timed out against a working page. That
  is why the suite was red -- including the pre-existing golden-paths file. Every
  spec now sets a viewport and **8/8 pass**.
- `data-direction` carried the abbreviated *label*, emitting `RCVD` where the
  contract says `RECEIVED`. It survived because **`PAID` is spelled the same both
  ways**, so any consumer agreed on paid prints and silently disagreed on
  received ones. `DirectionView` now carries a canonical `state` and a test
  asserts `state !== label`.

**Not improved, stated plainly:** the busiest-day wall clock is 2.1-3.0 s against
3.2 s before, inside run-to-run noise -- the DOM win is unambiguous, that one is
not. CLS is unchanged at ~0.23, of which mine was 0.018. Long tasks on tab open
remain ~1.0-1.2 s and belong to the four sibling analytics panels, not these two.

---

## Unfinished, stated plainly

- **A nightly incremental `publish` changes the day list, which misses the
  calibration cache and forces a full refit** (~85 min). By design — the key is
  a hash of the deviation values, so a stale fit can never be served — but it
  means "publish yesterday" is not a cheap operation as written. Not solved
  here.
- **The most recent visibility day is provisional.** It is missing the
  20:00–23:59 ET prints that arrive with the next tape day's `as_of`, and it
  tops itself up on the next run. Published rather than dropped, because
  dropping it would throw away the freshest cell in the series.
- **`arbs_dd_unit_bucket_v1` stores numerically-zero buckets.** rateslib's delta
  is non-zero at all 28 pillars, so a 7Y swap carries entries of order 1e-11 in
  20-30Y. No dust floor is applied — the backend measured that a 0.05 USD/bp
  floor removes 53% of rows and that one of them was 95.4% of its own unit's
  risk — so the table is ~10 rows per kept unit regardless of how many are
  material.
- **Fed Funds is included and is the weakest part.** The no-bias curve result
  behind the whole method was measured on SOFR. `rate_index` is on every row so
  a consumer can filter, and the prints chart is one-index-at-a-time by
  construction, but the *ladder* does not currently offer that toggle.
- **FOMC-dated units are surfaced, not fixed.** They deviate 6.8× wider on Fed
  Funds and 4.0× on SOFR because the Citi minute curve is smooth and has no
  discrete meeting steps. They are excluded from the prints chart by default and
  flagged in the ladder; improving the inference is out of scope for this PR.
- **Route handlers are served uncompressed by `next start`** (pages and static
  chunks do get gzip; Next's `compress` default does not reach Route Handlers).
  Moot on Vercel, whose edge compresses -- the live site serves `br` -- so this is
  documented rather than worked around. Unverified on the deployment itself:
  every v2 tape route 404s there, so that build predates this API.
- **Nothing keeps `arbs_dd_curve_mid_v1` current.** The chart now depends on a
  second table whose last day is 2026-08-07. A future `publish` day with no
  matching grid day flips that day's chart to the reconstruction fallback —
  labelled and honest, not silently wrong — but the daily grid extension is
  unowned. `backfill_curve_mids.py --stage backfill` is the command; scheduling
  it is not done here.
- **Three panels rendered an unlabelled blank while a fetch was in flight**, and
  every one was found by LOOKING at a screenshot rather than by a test, because
  all three render perfectly: the z heatmap (ten labelled bucket rows, empty
  strips), the exclusion drawer ("no coverage rows" beside a headline saying
  47.4% of DV01 was oriented), and the prints chart (an empty plot frame). Now
  one `panelState()` rule — `ready` / `loading` / `empty` — because a bare
  `loading` boolean cannot tell an in-flight fetch from a genuinely empty
  window, and those need different sentences. Fixed, but it is a class of defect
  no unit test in this repo would have caught, and there are other panels.
- **The mid grid costs 6.6 GB** of the 10.95 GB these tables occupy (~4.5% of a
  246 GB database). Reversible by date range; cheaper trims are fewer tenors or
  a shorter window; the deeper fix is normalising the repeated text columns to
  codes. Flagged rather than decided unilaterally.
- **Two pre-existing dashboard test failures** (`LegsSubTable`, `MmsTab`, 4
  tests) are untouched by this branch — **verified**, not assumed, by checking
  out `origin/main` into a throwaway worktree and running both suites there:
  the same 4 fail.
- **Screenshots are puppeteer, not Chrome MCP.** `chrome-devtools` disconnected
  mid-session and `claude-in-chrome` requires a human to choose between two
  connected browsers. Puppeteer already drives this package's e2e suite, so
  `scratch/shot_dealer_direction.mjs` captures the eight views headless with
  page-error and console-error assertions. Equivalent evidence, different
  driver.
