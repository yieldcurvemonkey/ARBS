# Vol-vs-Vol: the adjacent-expiry fly hedge — Design

**Date:** 2026-08-04
**Branch:** `feat/volvol-calendar-hedge` (worktree `ARBS-xm`, off `feat/outcome-map-rv`)
**Predecessor:** `2026-08-04-outcome-map-rv-{design,findings}.md`

## Where this comes from

The outcome-map study closed the vol-vs-linear question with a mechanism: the
FOMC lattice's frame-frozen hedge ratios are **5.7× too large** for a butterfly
(beta 0.175, R² 0.166 over 10,142 hedged trades), because a digital's lattice
sensitivity is a difference of CDFs while a butterfly's is a **density**, and the
market's density is the lattice's smeared by a 15–29pp off-lattice premium. Its
closing recommendation was to hedge a density with a density — an adjacent-expiry
butterfly rather than a ZQ basket.

## The falsifiable claim, and its fate

Consecutive SR3 quarterlies nest: the near contract's resolved-meeting set is a
**subset** of the far one's (verified 70/70 in sampling; structurally, a meeting
resolved by the near expiry is resolved by the far one and effective inside the
far window). So a butterfly on T2 has the same shared-meeting exposure as one on
T1, plus the extra meetings.

If the market-vs-lattice sensitivity mis-scaling `c` were a **common factor**
across butterflies, it would cancel in a fly-vs-fly ratio: with `d_i = c_i · P_i`
and a tree ratio `λ` fitted so `P_1 = λ P_2`, regressing realised `d_1` on
`λ d_2` returns `beta = c_1 / c_2 = 1`. That was the reason to expect the
vol-vs-vol hedge to be correctly specified where the linear one was not.

**Measured before building anything: it is not.** Pairing each `pair_odd_dev`
package with its mirror at the same absolute strikes on the adjacent expiry, over
~20k daily observations with a `|λ| ≤ 3` gate:

| hedge side | beta vs tree λ | R² | tree-hedged risk | best fitted risk |
|---|---:|---:|---:|---:|
| far (next expiry out) | **0.259** | 0.112 | **1.35×** | 0.91× |
| near (previous expiry) | **0.320** | 0.121 | **1.19×** | 0.91× |

The tree-implied calendar ratio is roughly **4× too large** and, used as
prescribed, *raises* risk — the same failure as the linear leg, milder in degree.

The tempting explanation — that `c` rises with dte, so `c_1/c_2 < 1` — **is not
supported**: measured per fixed-strike series, `c` is 0.19–0.61 with
Spearman(dte, c) = −0.17 on thin per-bin samples. `c` is contract-specific and
noisy; there is no common factor to cancel. The claim is recorded as refuted
rather than rescued.

## What is actually being built, and why it is still worth building

Two things survive the refutation and are worth measuring properly.

**1. The pairing convention is a real result.** Head to head over 67,423 daily
observations, best-case (pooled, in-sample) fitted hedges:

| hedge side | matching | corr | fitted β | variance removed |
|---|---|---:|---:|---:|
| far | **absolute rate** | **0.401** | 0.555 | **16.1%** |
| far | moneyness (same `d`) | 0.129 | 0.190 | 1.7% |
| near | absolute rate | 0.177 | 0.140 | 3.1% |
| near | moneyness | −0.078 | −0.079 | 0.6% |

Absolute-rate matching beats moneyness matching by an order of magnitude, which
is the frame-freezing principle (atoms live at `base + n·25bp`) confirmed from a
third direction. And it bounds the whole enterprise: **the best an
adjacent-expiry fly can do is remove 16% of a cell package's variance**, fitted
with hindsight, for ~11.5 contracts (≈2.9bp/trade round trip) against a package
earning 0.2–0.5bp/trade. The linear leg's correctly-sized ceiling was ~9–11% for
1.93bp. Better hedge, worse price.

**2. The calendar disagreement is an untested SIGNAL.** The same machinery that
fails as a hedge defines a trade nobody in this program has run: the *same count
cell*, at the *same absolute rate*, priced on two adjacent expiries. Its residual
richness `rich_1 − λ·rich_2` cancels the common part of the market-vs-lattice
distortion `c` (both legs are butterflies read against their own trees), leaving
the cross-expiry disagreement about the **extra meetings** — the object the
impdist study measured as options' own implied conditional (0.26/0.49 against
ZQ's 0.17/0.26) but could only call indicative because a one-Bernoulli fit left
an L1 residual of 0.33–0.41. That weak deconvolution fit and this weak hedge
correlation are the same fact seen twice; whether the *disagreement* is tradeable
is a separate question from whether the *hedge* works.

## Construction

New module `RVUtils/OutcomeMap/calendar.py`:

* `adjacent(symbols, as_of, sym)` — the previous/next listed quarterly by expiry.
* `mirror_package(legs, strikes_other, shift=0.0)` — the same package at the same
  absolute strikes on another expiry (`shift = f1 − f2` gives the moneyness
  convention, kept so the losing arm stays reproducible).
* `shared_exposure(cm1, cm2, h1, h2)` — align hedge ratios by meeting effective
  date; returns shared/extra split.
* `tree_ratio(v1, v2)` — least squares over **shared** meetings, `(v1·v2)/(v2·v2)`,
  requiring ≥2 shared meetings so the fit is over-determined and its residual
  means something (with one shared meeting it is exactly solvable and λ is
  arbitrary — measured at λ up to 6.3).
* `empirical_ratio(s1, s2, window)` — causal trailing-window regression of the
  two packages' daily changes, the honest tradeable alternative to the tree
  ratio; never fitted on the holding period itself.
* `residual_exposure(v1, v2, lam)` — what the hedge leaves, reported per trade.

## The grid (pre-declared, 128 configs)

```
signal      {map_odd, calendar}                       2
lambda      {none(0), one(1), tree, empirical}        4
dte band    {<=130, >130}                             2
threshold   {8pp, 16pp}                               2
exit        {converge-half, hold-15}                  2
direction   {fade, momentum}                          2
                                                  = 128
```

`map_odd` is the outcome-map `pair_odd_dev` signal with a calendar hedge bolted
on (λ = 0 reproduces the unhedged row from the prior study, which is the control
that must match). `calendar` trades the cross-expiry residual richness itself, in
which case λ defines the structure rather than hedging it and `none` is dropped
to `one` at run time (recorded, not silently merged).

Hedge side is fixed to **far** (the next expiry out): it is the only side with a
usable population (487 vs 111 sampled pairs, because a near neighbour rarely has
the two shared meetings the ratio needs) and it is the better hedge on every
measured axis. The near side is reported as a diagnostic, not gridded.

## Discipline

Unchanged from the outcome-map study and applied identically: listed marks only
on the parity-completed surface, lag-1 entries on the global calendar, costs per
contract per side (option half-tick 0.125bp) reported at 0×/1×/2× with the two
legs' bills kept separate, both directions always, n ≥ 10 floor before naming a
winner, DSR at the full 128 trials, NW t on dailies, chronological halves,
neighbourhood, and the two placebo worlds (Gaussian tree, wrong calendar)
re-derived from atoms up through the same `Context` subclasses.

## Kill criteria (pre-declared)

1. **Already fired, before the build**: if the tree calendar ratio is not
   right-sized (`beta` far from 1), the "hedge a density with a density" thesis
   is refuted as stated. It measured 0.26/0.32. The build continues only to
   quantify the ceiling and to test the calendar *signal*; the hedge claim is not
   re-litigated.
2. If the fitted-in-sample variance reduction is under 25%, an adjacent-expiry
   fly is not a hedge at any price, and the correct recommendation is to stop
   looking for one. (Measured: 16.1%.)
3. If the calendar signal's gross does not exceed the unhedged `pair_odd_dev`
   row's gross per trade, the extra expiry adds nothing and the cross-expiry
   channel is closed too.
4. ALIVE requires, as always: n ≥ 10, positive at 2× costs, DSR > 0.5,
   non-negative median config, mirrored sign test, survival of both placebos.
