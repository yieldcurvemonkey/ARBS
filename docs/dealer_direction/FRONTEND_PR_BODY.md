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

## Defects this found

**`if nan:` is `True`, and it excluded every package unit.** The first
`publish` run stopped on its own coverage guard. `pkg_exclusion` is only
assigned on a `PKG` unit; on a day where no package is refused, no row assigns
it, `reindex` creates it as an all-NaN **float64** column, parquet round-trips
that as float64, and `bool(nan)` is `True` — so a presence test on a string
field fired on every package unit and handed the reason `nan` downstream.

It had **no symptom of its own**: the units would have shipped as abstentions
with a blank tooltip and the ladder would have been quietly short. It surfaced
only because the coverage accounting is required to be a partition and refuses
a unit with no reason. Fixed by one reader (`_s`) for every string field
leaving the stage cache, plus two assertions that state the invariant instead
of relying on the next guard downstream.

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

**Pre-existing failures, unrelated:** `LegsSubTable.test.ts` and
`MmsTab.test.tsx` — 4 tests. Confirmed by stashing this branch's changes and
re-running: identical failures on the clean tree.

---

## Unfinished, stated plainly

*(this section is filled in at hand-off — see FRONTEND_LEDGER.md for the live
state)*
