# SR3 MBO Explorer — Findings

**Date:** 2026-08-07
**Branch:** `feat/sr3-mbo-explorer`
**Input:** `glbx-mdp3-20260715.mbo.dbn.zst` — GLBX.MDP3 MBO, parent `SR3.FUT`, 2026-07-15
**Notebook:** `notebooks/exploratory/sr3_mbo_explorer.ipynb`
**Engine:** `RVUtils/MBO`

One trading day. Everything below is measured on it and nothing has been checked on a second day.

## 1. The listed butterfly is quoted one tick wide

The headline, in the units the backtests use:

| | round trip | $ per lot |
| --- | ---: | ---: |
| Listed butterfly, own book (median of 10) | **0.506 bp** | **$12.65** |
| Two listed calendars | 1.0 bp | $25.00 |
| Three outright books | 2.0 bp | $50.00 |
| The repo's standing assumption | 2.0 bp | $50.00 |

Three ways to trade `SR3:BF Z6-H7-M7`, RTH medians. The listed instrument is not only the
tightest but also the deepest, and the ordering is monotone in both:

| route | width | $ per lot | size at touch |
| --- | ---: | ---: | ---: |
| listed butterfly | 0.5 bp | $12.50 | 2,261 |
| two listed calendars | 1.0 bp | $25.00 | 753 |
| three outrights | 2.0 bp | $50.00 | 286 |

`reference_sfr_fly_conventions` charges a fly 2.0 bp round trip, derived as four contracts at
half a basis point each. That number is **exactly right for the route it describes** — the
measured leg-implied width is 2.000 bp, to three decimals, for all ten butterflies. It is the
cost of building the fly out of three outright books.

The exchange lists the butterfly as its own instrument, and that instrument is quoted at one
tick — the same one tick as an outright — for **99.8% of RTH** on the most active names. The
cost of the structure is the tick, not four times the tick.

Per butterfly, RTH of 2026-07-15:

| symbol | tenor | quoted bp | effective bp | share of RTH at 1 tick | bid size at touch | lots |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `SR3:BF Z7-H8-M8` | 3m | 0.500 | 0.50 | 100.0% | 2,173 | 1,427 |
| `SR3:BF H7-M7-U7` | 3m | 0.500 | 0.50 | 100.0% | 2,532 | 1,878 |
| `SR3:BF Z6-H7-M7` | 3m | 0.501 | 0.50 | 99.8% | 3,619 | 6,384 |
| `SR3:BF M7-U7-Z7` | 3m | 0.501 | 0.50 | 99.8% | 2,803 | 2,876 |
| `SR3:BF U7-Z7-H8` | 3m | 0.503 | 0.50 | 99.4% | 3,129 | 2,150 |
| `SR3:BF U6-Z6-H7` | 3m | 0.509 | 0.50 | 98.1% | 636 | 4,997 |
| `SR3:BF M7-Z7-M8` | 6m | 0.571 | 0.50 | 85.7% | 362 | 2,480 |
| `SR3:BF M7-M8-M9` | **12m** | 0.600 | 0.50 | 80.0% | 145 | 2,977 |
| `SR3:BF Z6-M7-Z7` | 6m | 0.605 | 0.50 | 79.1% | 117 | 3,913 |
| `SR3:BF U6-H7-U7` | 6m | 0.993 | 0.50 | 22.1% | 201 | 2,005 |

Calendars behave the same way: 0.50 bp listed against 1.0 bp implied, i.e. half.

**What this does not say.** One day. Quoted size is not firm size, and 8,008 lots traded in
`Z6-H7-M7` against 3,619 lots showing at the bid — the book is far bigger than the flow that
takes it. Nothing here has been carried through a backtest; the claim is about the cost line,
not about any strategy.

## 2. The listed book is not implied liquidity

The obvious objection is that CME's implied-in quotes make the listed spread look tight while
really being the legs. Measured over 32,399 one-second observations of RTH:

- listed width **0.5 bp** against leg-implied **2.0 bp**; the listed book is tighter at
  **100.0%** of observations
- listed size at the touch **2,261 lots** against leg-implied **286** — eight times deeper
- the two mids agree to **0.25 bp**, half a tick, i.e. to the tick grid
- listed bid never reaches the implied ask, and vice versa: `frac_listed_crossable = 0.0`

A book that is four times tighter and eight times deeper than what its legs can produce is
carrying its own resting orders. (Stated as an observation: no implied-flagged records appear in
this file, but that has not been checked against Databento's GLBX documentation.)

## 3. Price units differ by instrument, and the difference is 100×

Outrights and bundles quote in **index points** (96.040, tick 0.005). Every differential
instrument — calendar, butterfly, condor, double fly, bundle spread — quotes **directly in
basis points** (6.500, tick 0.5).

Confirmed by arithmetic on the file's own closes, exactly:

```
SR3:BF M7-M8-M9   95.960 − 2(96.080) + 96.080 = −0.120 index points = −12.0 bp
listed close                                                          −12.0
SR3:BF Z6-H7-M7   96.040 − 2(95.970) + 95.960 =  0.060 index points =   6.0 bp
listed close                                                            6.5
```

Treating a butterfly price as index points reports a one-tick market as **50 bp wide**. This is
how the first pass over the data read, and it is silent — the numbers stay plausible.

A second, smaller trap: **$25 per bp per lot** holds for an outright and for every differential
instrument, because the leg ratios are already inside the quoted price. It does **not** hold for
a bundle, whose price is the average of N legs: a 1 bp move there is 1 bp on each of N contracts,
so a 1-year bundle is $100 per bp and a 3-year is $300.

`RVUtils/MBO` derives the scale from the parsed symbol *and* from the tick the instrument
actually printed, and raises if they disagree rather than guessing.

## 4. Two microstructure notes

**Price impact at 60 s is around zero on the listed butterflies.** Median effective spread is
0.50 bp and median realised spread at 60 s is the same, so the mid does not move against the
taker after the print. With 37–404 trades per instrument on one day this is suggestive, not
established, but it is the opposite of what an adversely-selected book looks like.

**Order-flow imbalance needs a five-minute bar in this book; signed trade flow does not.**
Against the mid change over the same bar, on SR3Z6 / SR3H7 / SR3Z7:

| horizon | signed trade flow | order-flow imbalance |
| --- | --- | --- |
| 1 min | r = +0.32 / +0.25 / +0.21 | r = −0.13 / −0.05 / +0.14 |
| 5 min | r = +0.38 / +0.20 / +0.24 | r = +0.19 / +0.28 / +0.42 |

The touch holds thousands of lots and the mid only moves when a whole level clears, so one
minute of queue churn is mostly noise around a price that did not move. That signed *trade* flow
is positive at every horizon is also the check that the aggressor convention and the mid are
consistent — a flipped direction would make effective spread negative, and it is +0.50 bp
everywhere.

## 5. What is on the file

72,900,288 records; 443 of 1,188 mapped instruments active. Action mix `M` 56.6 M, `A` 8.0 M,
`C` 7.9 M, `F` 246 k, `T` 126 k, `R` 443.

| Kind | Active | Messages | Trades | Lots | msgs/trade |
| --- | ---: | ---: | ---: | ---: | ---: |
| `OUTRIGHT` | 31 | 61,904,608 | 78,502 | 2,251,596 | 789 |
| `CALENDAR` | 209 | 5,474,537 | 18,857 | 555,463 | 290 |
| `BUNDLE` | 41 | 3,427,106 | 23,759 | 128,303 | 144 |
| `BUTTERFLY` | 89 | 1,331,044 | 3,871 | 55,051 | 344 |
| `BUNDLE_SPREAD` | 13 | 540,696 | 396 | 1,056 | 1,365 |
| `DOUBLE_FLY` | 40 | 221,144 | 164 | 1,583 | 1,348 |
| `INTERCOMMODITY` | 4 | 824 | 25 | 329 | 33 |
| `CONDOR` | 15 | 302 | 17 | 126 | 18 |
| `BUNDLE_FLY` | 1 | 27 | 6 | 14 | 4 |

Message rate peaks 12:00–13:00 UTC (18.4 M) around a scheduled release at 12:30; the settlement
break is visible as 13,000 messages in the 21:00 UTC hour.

## 6. Verification

**Tie-out — exact.** Four-hour bars rebuilt from MBO trade prints against the Barchart panel
already in the repo (`notebooks/data/stir_intraday/contracts.parquet`), 12 outrights:

| bar convention | bars | exact close | median abs diff | median volume ratio |
| --- | ---: | ---: | ---: | ---: |
| **labelled by start** | 48 | **100%** | **0.0 bp** | **1.000** |
| labelled by end | 60 | 23% | 1.0 bp | 0.599 |

Every close reproduced to the last decimal. Bars are stamped in Chicago time and labelled by
their start. Both conventions were tested and both reported, so the alignment is a finding.
Volume ties exactly except in the 13:00 UTC bar, where the MBO is 0.3–6.0% *higher* — consistent
with spread-leg executions printing into the outright books.

**Replay invariants.**

- crossed at a packet boundary: **12 of 59,563,338** top-of-book states, all on `SR3M6`, all
  between 21:46 and 21:53 UTC — the pre-open of the following session, where CME accepts orders
  without matching them and a locked book is the expected state. None inside RTH.
- trades outside the prevailing book: **33 of 79,700 (0.041%)**, only on outrights and bundles,
  never on a listed spread — the signature of implied matching, where a spread order executes
  against the outright book at a price that book never displayed.
- leg-implied mid against listed mid: **0.25 bp for all 15 structures**, i.e. half a tick, four
  independently replayed books agreeing on an arithmetic identity none of them knows about.

**Unit tests.** 35 hand-built sequences with known resulting books. Five mutations of the kernel
were applied and all five were caught by the test named for them.

## 7. What this changes, and what it does not

The 2.0 bp charge is not wrong as a description of legging a fly out of outrights — that number
is now measured rather than assumed. What it does not describe is the cost of trading the listed
instrument, which is a quarter of it.

Whether re-costing revives anything in `project_sfr_rv_lab`, `project_sfr_kink_fade_v2` or
`project_outcome_map_rv` is a separate question, and it needs the listed butterflies' *history*,
not one day. The obvious next step is a second and third MBO day — ideally one quiet and one
around an FOMC — to see whether one tick is the normal state or a feature of 2026-07-15.

Deferred as specced: queue-position analytics, which needs the MDP3 priority rules (a price
change or a size *increase* loses priority, a decrease keeps it).
