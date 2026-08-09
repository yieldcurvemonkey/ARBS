# CME MBO Analytics Suite — Findings

**Date:** 2026-08-08
**Branch:** `feat/cme-mbo-analytics-suite` (worktree `C:\Users\chris\clee\ARBS-mbos`)
**Input:** 64 GB of GLBX.MDP3 MBO on `D:\` — SR3 (53 sessions) and ZT/ZF/ZN/TN/ZB/UB (79 each)
**Design:** `2026-08-08-cme-mbo-analytics-suite-design.md`
**Primary sources:** `2026-08-08-cme-mbo-reference-findings.md` (122 findings, 24 adversarial verdicts)

Everything below is measured on the data or read from a primary source. Where a number rests
on one session, it says so.

## 1. The most active Treasury contract could not be replayed at all

`ZNU6` is 6.76 M of one ZN session's 7.08 M records — the single busiest instrument in the whole
archive. `build_price_grid` refused it: the dense ladder would have needed **6,977,921 slots**.

The cause is 57 records out of 6.76 M — a rate of 8.4e-6 — at ten far-from-market prices: one ask
at **109,080.00** and stub bids from **50.00 to 88.1875**, against a live book occupying about nine
hundred ticks and a traded range of fifty-eight.

`ZBU6` prints the same shape (a stub at 0.0625 against a 96–128 handle), so this is a property of
the complex and not of one contract.

**Fix.** The ladder now covers a median-absolute-deviation band, which is immune to any minority of
outliers however extreme. It is deliberately **unpadded**: the whole session's prices are known
before the ladder is built, so there is nothing to leave headroom for — and padding would have
shifted `px_min` and `n_slots` for every well-behaved instrument, which is what let the existing
quarter-tick and negative-price tests stand untouched.

**The numba kernel was not modified.** Re-reading it, an add whose price cannot be indexed never
sets the order's generation, so its later cancel or modify is already a correct no-op, and a modify
that leaves the band clears the generation before failing to re-add. The kernel was already right
about out-of-band orders and merely *silent* about them. So the change is a banded grid plus a
vectorised assertion outside the kernel: an out-of-band order is harmless only on the side that
keeps it away from the touch, and the opposite case raises rather than producing a quietly wrong
touch. Five mutations of the band logic were applied and each was caught by the test named for it.

`ZNU6` now replays in 6.7 s to 3.87 M top-of-book rows.

## 2. The archives straddle a vendor normalization change

Databento changed CME event-boundary normalization in production on **2026-08-08** and applied it
retroactively to the full history. Under the new convention the last book update no longer carries
`F_LAST`; a separate `action='N'` record does, and records are published per packet rather than
buffered until the event completes — so **`ts_recv` does not mean the same thing under the two**.

Measured by sampling each batch:

| batch | sessions | DBN | `action='N'` | normalization |
| --- | --- | ---: | ---: | --- |
| SR3 `GLBX-20260807` | 2026-07-07 → 08-06 | v1 | none | **old** |
| SR3 `GLBX-20260808` | 2026-06-07 → 07-06 | v3 | 10% of records | **new** |
| Treasury `GLBX-20260808` (all six) | 2026-05-07 → 08-06 | v3 | present | **new** |

So SR3's **June** sessions carry the *newer* convention than its **July** ones, because June was
re-downloaded after the retroactive change. Nothing about the file names says so.

The replay kernel survives — an `N` record matches no branch, so it cannot mutate the book, and the
`F_LAST` it carries still drives emission at the right point. Two known-answer tests pin that,
including one asserting both conventions produce an identical top of book.

What does not survive unaided is any cross-day statistic, which would average two measurement
conventions. `dbn_version`, `n_action_none` and a derived `normalization` label are therefore
recorded per instrument-day and surfaced by `verify.invariants`. A session with no `N` records is
labelled `old` only if it had events at all; a silent instrument proves nothing and is `unknown`.

**Recommendation:** re-download the SR3 07-07 → 08-06 range so the whole history is one vintage. Until
then, treat 2026-07-07 as a seam and do not compare across it without checking the label.

## 3. Store economics, measured

Pilot: one session per product, **7 built, 0 failed, 309 s**.

| | records | top-of-book rows | store | wall |
| --- | ---: | ---: | ---: | ---: |
| SR3 | 80,971,250 | 75,517,086 | 1,054 MB | 307 s |
| ZN | 7,075,513 | 4,022,001 | 57 MB | 16.7 s |
| ZF | 5,328,088 | 2,921,184 | 41 MB | 13.7 s |
| ZT | 4,340,686 | 2,440,738 | 36 MB | 10.4 s |
| TN | 3,293,823 | 1,934,080 | 27 MB | 13.8 s |
| ZB | 2,694,668 | 1,591,920 | 23 MB | 9.2 s |
| UB | 2,161,397 | 1,369,977 | 20 MB | 9.3 s |

Bytes of store per source record: **7.8 to 9.1** for the Treasury roots, **13.0** for SR3 — whose
messages are far likelier to move the touch (75.5 M states from 81.0 M records, against ZN's 4.0 M
from 7.1 M). Projected wide tier: **SR3 ≈ 56 GB, Treasuries ≈ 16 GB, about 72 GB total** against
431 GB free.

The pre-flight disk guard was calibrated at 0.9 bytes per record before this ran — **fourteen times
optimistic**, and it would have waved through a build that could not fit. It is now the SR3 figure,
because over-estimating costs a cautious refusal and under-estimating fills the drive nine hours in.

Tick indices cost **12.9 bytes per row** against 13.9 for float64. That 7% would not justify the
indirection; what does is that SR3's 0.005 tick is not representable in binary floating point, so on
floats "is this market one tick wide" needs a tolerance and on indices it is an integer comparison.

## 4. Verification

**Leg-implied against listed — the check that needs no external data.** A listed calendar and its
two outrights are three separately replayed books sharing no state: different order ids, different
price ladders. Their mids must satisfy an identity none of them knows about.

| product | structure | observations | median error |
| --- | --- | ---: | ---: |
| ZN | `ZNU6-ZNZ6` | 17,200 events | **0.5 ticks** |
| ZF | `ZFU6-ZFZ6` | 4,330 events | **0.5 ticks** |
| ZB | `ZBU6-ZBZ6` | 1,480 events | 1.0 ticks |

Half a tick is the lattice floor — two books on the same grid cannot agree more closely.

**The checker had the bug it exists to catch.** `implied_vs_listed` first thresholded on *grid*
points, and `ZNU6-ZNH7` quoted exactly once all session — one top-of-book state from 82 records —
which forward-fills to 84,834 one-second points and sails past any threshold on grid size. Compared
against legs that moved all day it scored a ten-tick error that said nothing about the engine. It
now thresholds on **events** and reports the event counts, so staleness is visible rather than
arriving disguised as disagreement.

**Store round-trip: exact** on nine instrument-days including a 3.87 M-row instrument — rows, prices
and sizes all identical between the in-memory replay and the parquet read-back.

**Invariants.** `ZNU6` shows 21 locked and 2 crossed states out of 3.87 M, **all between 21:45 and
22:00 UTC** — the settlement break, where the exchange accepts orders without matching them. None
inside the trading session.

The kernel's own `crossed_events` counter turned out to measure the wrong thing: it counts *packet
boundaries*, so a book sitting locked through a busy pre-open scores one per packet — 7,874 for what
are actually 23 states. It scales with message rate, not book health. `locked_states` and
`crossed_states` count emitted states instead.

## 5. The queue model predicts realised fill order

CME's `MDOrderPriority` (tag 37707, lower value = higher priority, meaningful only within a
side-and-price bucket) is deliberately omitted from Databento's normalized MBO as venue-specific.
Queue rank therefore has to be reconstructed — and the obvious source for the rules is wrong.

An adversarial check **refuted** the generic CME "Order Functionalities" table on two rows: it is
venue-unqualified, and the futures matching-algorithm page (v5, 2026-06-02) lists exactly three
priority-losing modifications under FIFO — *working-quantity increase, price change, account change*.
Account is not in the feed, so the implemented rule is: **a price change or a size increase goes to
the back of the queue; a size decrease keeps its place.**

**The falsification test, on ZNU6, 2026-07-14:**

| | |
| --- | ---: |
| orders | 2,388,658 |
| ordered pairs tested | 1,423,070,739 |
| rank inversions | 421,747 |
| **inversion rate** | **0.030%** |
| orphan fills (a fill with no resting order) | **0** |

The reconstructed rank predicts realised fill order 99.97% of the time, and every single fill
matched an order the replay had seen resting.

**Fill probability by queue position at join** — monotone in both fill rate and resting time, which
is what a correct model must produce and what the simulator needs:

| size ahead when the order joined | orders | fill rate | median rest |
| --- | ---: | ---: | ---: |
| 0 (front of queue) | 12,752 | **79.3%** | 0.002 s |
| 1 – 10 | 32,819 | 75.4% | 0.011 s |
| 10 – 50 | 87,941 | 56.4% | 0.042 s |
| 50 – 100 | 74,751 | 44.5% | 0.062 s |
| 100 – 500 | 369,404 | 31.2% | 0.149 s |
| 500 – 1,000 | 285,009 | 21.3% | 0.385 s |
| 1,000 – 5,000 | 1,404,355 | 8.2% | 1.356 s |
| over 5,000 | 121,627 | **2.8%** | 5.099 s |

**What this does not say.** One session, one instrument. A 0.03% inversion rate is consistent with
FIFO but does not prove the absence of a lead-market-maker allocation, which is what Databento's own
caveat about `ts_event` warns of. Running the test across all 553 sessions is the next step, and it
is cheap once the store is built.

## 6. Two facts about the market itself

**The listed Treasury calendar spread barely exists outside the belly.** Top-of-book states on
2026-07-14:

| ZN | ZF | ZB | ZT | UB | TN |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 17,200 | 4,330 | 1,480 | 52 | 28 | 13 |

In ZT, UB and TN the listed spread quotes a few dozen times a day. Any execution study that assumes
"trade the listed spread" as a route has no such route in half the complex.

**Cancel-to-trade is an order of magnitude apart between front and deferred.** `ZNU6` posts 2.39 M
orders a day at 4.7 cancels per fill; `ZNZ6` posts 1,431 cancels per fill. Quoting in the deferred
contract is almost entirely non-transactional.

## 7. Icebergs hide about 2% of ZN's traded volume

Detection uses the exact structural rule from Zotikov and Antonov -- no time window
and no threshold -- and the sizing uses Kaplan-Meier, because **a cancelled iceberg
is a censored observation of its own size**: what it traded is only a lower bound,
so averaging observed totals biases the distribution downward, worst in the tail
where a hidden-liquidity estimate lives.

ZNU6, 2026-07-14:

| | |
| --- | ---: |
| orders | 2,388,658 |
| detected icebergs | 668 (0.028%) |
| their share of traded volume | 2.72% |
| hidden volume, lower bound | 55,982 lots (2.26% of the tape) |
| median iceberg fill vs ordinary filled order | **20 lots vs 1** |

So they are rare, roughly twenty times larger than an ordinary order, and conceal
about one lot in forty-four of everything that trades.

**A caveat that matters more than the numbers.** All 668 were found by rule (a) --
a trade exceeding the resting volume. Not one came from rule (b), an order fully
traded and returning under the same id: `n_refresh` is zero everywhere. Databento's
normalization evidently does not re-use order ids across tranches the way the raw
feed the paper worked from does. Everything here therefore rests on rule (a), which
sees an iceberg only *after* it has traded through its displayed size, so an
iceberg cancelled before that is invisible and these counts are lower bounds.

Synthetic iceberg detection is deliberately not implemented: its rule rests on
assumptions the paper's own authors call very strong, and when candidates collide
it produces a tree of possible icebergs rather than an answer.

## 8. The fill simulator is exact, not modelled

Most fill simulators are probabilistic because most data is not order-resolved:
with aggregated depth you cannot tell whether a size decrease happened ahead of
your order or behind it. Market-by-order removes the guess -- every order at a
level is named, so the set ahead at any instant is known and so is how each left.

Two corrections during implementation, both of which would have produced a
plausible and wrong edge:

- An order that never left carries the session's last timestamp as its exit, which
  read as "already gone" for a later placement. It is the opposite: it is ahead
  forever.
- "The first trade after the queue cleared" **double-counts**. The trade clearing
  the last order ahead is the trade that consumed it; only its residual reaches
  you. The exact rule is on cumulative volume: you fill when trade volume at the
  level exceeds the part of the queue ahead that was actually *executed*. An order
  ahead that was **pulled** advances you for free -- precisely the distinction L3
  supports and aggregated depth cannot.

The model-free counterpart to check it against is §5's realised fill curve.

## 9. The normalization seam costs little, and an earlier claim here was wrong

**Correction.** An earlier version of this section reported the seam costing a p90 of
2,156 us against 111 us -- nineteen times -- and recommended paying for a re-pull on
that basis. That measurement used **one instrument (SR3Z6) over three sessions a
side**, and it does not survive a wider look. Recorded rather than quietly amended,
because the recommendation was to spend money.

Paired across the five busiest SR3 **outrights**, eight sessions either side of
2026-07-07:

| difference, old minus new | value |
| --- | ---: |
| p50 of `ts_recv - ts_event` | **-1.0 us** |
| p90 | **+2.1 us** |
| share of records over 1 ms | **+0.4 pp** (1.0% to 1.4%) |
| p99 | about +700 us |

p90 is roughly 125 us on **both** sides for every one of the five. Six SR3 bundles
show the same thing, with the new vintage marginally *worse* on p90. So the buffering
difference is real but small: it shifts about four records in a thousand past a
millisecond and lengthens the far tail, and it does not move the body of the
distribution at all.

**Revised recommendation.** Do not pay to re-pull for timestamp fidelity alone. The
vintage label on every instrument-day is the appropriate defence, and it is already
there. Re-pull only if a study needs the p99 tail of feed latency specifically, or if
uniform DBN v3 tooling is wanted for its own sake. If you do: `GLBX.MDP3`, schema
`mbo`, `stype_in=parent`, symbol `SR3.FUT`, 2026-07-07 to 2026-08-06 -- there is no
`DATABENTO_API_KEY` on this machine, so it is a portal batch job.

**What the seam does still change**, and what the label is for: the old vintage
carries no `action='N'` records at all, and emits 0.87 top-of-book states per record
against 0.81 for the new one. Book states are identical -- a known-answer test pins
that -- but any count of *events* is not comparable across the seam.

## 10. ZT is not broken; its information is deeper in the book

ZT's touch order-flow imbalance correlates **-0.107** with the same-second mid
change where every other root sits near +0.5, and only reaches 0.410 at a minute.

| product | tick | touch depth | corr @1s | @10s | @60s | @300s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **ZT** | 1/256 | **3,086** | **-0.107** | 0.105 | 0.410 | 0.581 |
| ZF | 1/128 | 1,566 | 0.435 | 0.594 | 0.735 | 0.808 |
| ZN | 1/64 | 2,465 | 0.487 | 0.569 | 0.636 | 0.675 |
| ZB | 1/32 | 846 | 0.521 | 0.644 | 0.798 | 0.873 |

ZT has the finest tick of the complex and the deepest touch, so its front queue
turns over enormously without the price moving and the touch is close to
uninformative: an R-squared of **0.004** at one second.

Multi-level OFI resolves it. With ten levels, ZT reaches **R-squared 0.549** at one
second, and out-of-sample RMSE against the touch-only fit improves:

| | ZT | ZN | ZB |
| --- | ---: | ---: | ---: |
| RMSE improvement, 10 levels vs touch, 1 s | **32%** | 29% | 48% |
| Ridge over OLS, out of sample | 4.3% | 3.1% | 2.7% |
| fitted penalty | 1.6e4 | 1.0e3 | 602 |

Below Xu-Gould-Howison's 65-75 per cent for large-tick equities, but the direction
and the mechanism are theirs, and the practical consequence is concrete: **the
default ten-second bar is too short for the deepest book**, and `ofi_bar_scan`
reports correlation against bar length beside the share of bars whose mid never
moved, so the bar is chosen by looking rather than by default.

## 11. What is built, and what is not

Built and tested (232 tests, all passing under `conda run -n stir` equivalent invocation):

- `products` — per-root units, ticks, dollar values and match algorithm. Outright tick lattices are
  **measured** from the archives (gcd of price offsets over tens of thousands of prints) and agree
  with the contract specifications: ZT 1/256, ZF 1/128, ZN and TN 1/64, ZB and UB 1/32. Two things
  measurement caught that arithmetic would not: SR3 bundles quote on a quarter tick (1/400 over
  44,554 prints) rather than the outright's 1/200, and stub prices appear on every root.
- `symbols` — root-dispatched grammar; SR3 unchanged, Treasury added.
- `book` — banded ladder, unchanged kernel, vintage counters.
- `lifecycle` — per-order table with the falsifiable queue model.
- `archive`, `store` (schema, writer, manifest, reader, panel, risk), `build`, `verify`.

**A units decision worth restating.** `bp` is not a native unit for a Treasury future. SR3 is a rate
contract and $25/bp is intrinsic; a Treasury future is a price contract whose basis point needs the
CTD DV01. Asking a Treasury `ParsedSymbol` for `bp_per_price_unit` now **raises and names the DV01
path**, rather than returning the 100.0 that a global kind-set produced — a number that is not so
much wrong as meaningless, and that nothing downstream would have flagged. In panels, `bp` is a
linear rescaling whose *differences* are yield basis points; the level is not a yield.

- `analytics` — `liquidity`, `flow` (CKS order-flow imbalance and true-aggressor trade flow),
  `impact` (effective/realised spread, impact by size, Kyle lambda), `icebergs`, and `leadlag`.
- `sim` — the exact FIFO fill simulator.

**Lead-lag deserves a note, because it is the piece most easily got wrong.** The estimator is
Hayashi-Yoshida, which needs no common grid; `epps_curve` measures on your own data how much a
gridded estimate would have attenuated. Three things it refuses to do, all from Hoffmann, Rosenbaum
and Yoshida: it reports **no t-statistic or standard error for the lag**, because their Proposition
2 proves no central limit theorem exists for this estimator; it flags the degeneracy where
maximising the contrast provably fails to locate anything; and significance comes from a
**permutation test** that shuffles increments rather than prices, so the surrogate keeps the same
clock, mesh and realised variance.

Not yet done: MLOFI and the deep tier (needs M-level depth at every book change), synthetic iceberg
detection, Hasbrouck information share and Gonzalo-Granger, and the full 553-session build, which is
running.

MLOFI is worth the deep pass specifically here: Xu, Gould and Howison measure a 65–75% out-of-sample
RMSE improvement from ten levels for **large-tick** instruments against 15–30% for small-tick ones,
and both tick degeneracies that cap the small-tick case require a spread wider than one tick — which
these contracts almost never have.
