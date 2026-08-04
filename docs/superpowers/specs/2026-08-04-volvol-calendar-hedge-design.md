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

The tree-implied calendar ratio is too large and, used as prescribed, *raises*
risk — the same failure as the linear leg, milder in degree.

### Correction: those are DAILY numbers, and daily is the wrong horizon

The table above was the first thing measured and it is attenuated. Marks move on
a 0.5bp tick grid, so each leg's daily change carries quantisation noise that is
independent across expiries — classic errors-in-variables, which biases a daily
regression's slope and R² toward zero. The tradeable horizon is the holding
period, and re-measured there the picture changes materially:

| horizon (sessions) | corr | fitted β | R² | β vs tree λ | risk-min λ | variance removed |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.43 | 0.61 | 0.18 | 0.27 | 0.60 | 18.4% |
| 3 | 0.59 | 0.91 | 0.35 | 0.38 | 0.90 | 35.0% |
| 5 | 0.65 | 1.03 | 0.42 | 0.42 | 1.05 | 42.1% |
| 10 | 0.70 | 1.14 | 0.48 | 0.45 | 1.15 | 48.4% |
| **15** | **0.73** | **1.22** | **0.53** | **0.49** | **1.20** | **52.6%** |

So, corrected: an adjacent-expiry fly **is** a real hedge — at a 15-session
holding period it removes **52.6%** of the package's variance, and the naive
**1:1** ratio captures 50.9% of that without estimating anything. The claim that
fails is narrower than "the hedge does not work": it is that the *lattice* can
size it. `beta` against the tree ratio is 0.49 — the tree is still ~2× too large,
just as it was ~5.7× too large for the linear leg. **The market can size this
hedge; the model cannot.**

The 1:1 result is confirmed independently by per-trade P&L dispersion in the
backtest harness (3.22 → 2.30 bp/trade, a 49% variance reduction on a completely
separate computation).

The tempting explanation — that `c` rises with dte, so `c_1/c_2 < 1` — **is not
supported**: measured per fixed-strike series, `c` is 0.19–0.61 with
Spearman(dte, c) = −0.17 on thin per-bin samples. `c` is contract-specific and
noisy; there is no common factor to cancel. The claim is recorded as refuted
rather than rescued.

## What is actually being built, and why it is still worth building

Two things survive the refutation and are worth measuring properly.

**1. The pairing convention is a real result.** Head to head over 67,423 daily
observations, best-case (pooled, in-sample) fitted hedges (daily, so attenuated —
the comparison between conventions is what matters, not the levels):

| hedge side | matching | corr | fitted β | variance removed |
|---|---|---:|---:|---:|
| far | **absolute rate** | **0.401** | 0.555 | **16.1%** |
| far | moneyness (same `d`) | 0.129 | 0.190 | 1.7% |
| near | absolute rate | 0.177 | 0.140 | 3.1% |
| near | moneyness | −0.078 | −0.079 | 0.6% |

Absolute-rate matching beats moneyness matching by an order of magnitude, which
is the frame-freezing principle (atoms live at `base + n·25bp`) confirmed from a
third direction. The near side is the weaker hedge on every axis as well as the
rarer one.

The economics, at the corrected horizon: ~52% of variance removed for roughly a
doubling of the option bill (1.83 → 3.66 bp/trade at 1:1) against a package
earning 0.2–0.7bp/trade. Compare the linear leg — 9–11% for 1.93bp. **The
vol-vs-vol hedge is five times the hedge for twice the price, and the package it
protects still does not earn enough to pay for either.**

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

1. **Fired before the build**: if the tree calendar ratio is not right-sized
   (`beta` far from 1), the "the lattice can size a density hedge" thesis is
   refuted. Measured 0.49 at the trade horizon — the tree is ~2× too large, down
   from ~5.7× for the linear leg but still wrong. Not re-litigated.
2. If the variance reduction at the holding horizon is under 25%, an
   adjacent-expiry fly is not a hedge at any price. **Measured 52.6% at 15
   sessions (50.9% at a flat 1:1) — this does NOT fire**, and the hedge is real.
   The question moves entirely onto price.
3. If the calendar signal's gross does not exceed the unhedged `pair_odd_dev`
   row's gross per trade, the extra expiry adds nothing and the cross-expiry
   channel is closed too.
4. ALIVE requires, as always: n ≥ 10, positive at 2× costs, DSR > 0.5,
   non-negative median config, mirrored sign test, survival of both placebos.
