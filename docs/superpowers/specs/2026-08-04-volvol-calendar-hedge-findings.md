# Vol-vs-Vol: the adjacent-expiry fly hedge — Findings

**Date:** 2026-08-04
**Branch:** `feat/volvol-calendar-hedge` (off `feat/outcome-map-rv`)
**Design:** `2026-08-04-volvol-calendar-hedge-design.md`
**Executed notebook:** `notebooks/backtests/volvol_calendar.ipynb` (0 errors, 0 unrun)
**Module:** `RVUtils/OutcomeMap/calendar.py` (17 synthetic tests, 6/6 mutations caught)
**Panels:** `notebooks/data/volvol/` (gitignored)

## The question and the answer

The outcome-map study closed vol-vs-linear and left one recommendation: a
butterfly's model sensitivity is a **density**, so hedge it with a density — an
adjacent-expiry butterfly, not a ZQ basket. This study built that hedge.

**The hedge works, the lattice still cannot size it, and it makes the trade worse
anyway — before costs.**

| | ZQ basket (prior study) | adjacent-expiry fly |
|---|---:|---:|
| variance removed, best size | 9–11% | **53%** |
| variance removed, no estimation | — | **51%** (flat 1:1) |
| beta vs the model's own ratio | 0.175 (5.7× too big) | **0.489** (2.0× too big) |
| bill per trade | 1.93bp | **1.85bp** (1:1: 3.69 total vs 1.84 unhedged) |
| gross per unit of risk | — | **0.213 → 0.167** |

That last row is the finding. Everything else is detail.

## 1. The hedge is real — five times the ZQ basket

Consecutive SR3 quarterlies nest: across 1,458 paired contract-days the near
contract's resolved-meeting set is a subset of the far one's every time (median 3
shared meetings, 2 extra). At the horizon a trade is actually held:

| horizon (sessions) | corr | fitted β | R² | β vs tree λ | risk-min λ | var removed | at flat 1:1 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.429 | 0.611 | 0.184 | 0.273 | 0.60 | 18.4% | 11.0% |
| 2 | 0.512 | 0.780 | 0.262 | 0.344 | 0.80 | 26.2% | 24.1% |
| 3 | 0.592 | 0.906 | 0.350 | 0.377 | 0.90 | 35.0% | 34.6% |
| 5 | 0.649 | 1.032 | 0.421 | 0.421 | 1.05 | 42.1% | 42.1% |
| 10 | 0.696 | 1.143 | 0.484 | 0.452 | 1.15 | 48.4% | 47.7% |
| **15** | **0.725** | **1.223** | **0.526** | **0.489** | **1.20** | **52.6%** | **50.9%** |

Confirmed independently by per-trade dispersion in the backtest: 2.74 → 1.98
bp/trade at 1:1, a 48% variance reduction computed a completely different way.

**The horizon matters and nearly cost this study its headline.** The first
measurement regressed the two packages' *daily* changes and returned β 0.26 with
16% variance removed — which was written into the design doc as a ceiling and is
wrong. Marks move on a 0.5bp tick grid, so each leg carries quantisation noise
independent of the other: textbook errors-in-variables, slope and R² biased
toward zero. The bias is visible as the monotone climb in the table above and
the correction is recorded in the design doc rather than quietly applied.

## 2. The lattice still cannot size a density hedge

`beta` against the tree's least-squares ratio over the shared meetings is
**0.489** at the trade horizon — the model asks for twice the hedge the market
wants. Better than the linear leg's 5.7×, and wrong in the same direction for
the same reason: the tree's density is sharper than the market's, so it
overstates every butterfly's sensitivity, and the overstatement does **not**
cancel between two expiries because it is contract-specific rather than a common
factor (measured directly: `c` runs 0.19–0.61 across fixed-strike series with
Spearman(dte, c) = −0.17, i.e. no clean dte pattern to exploit).

The practical consequence is cheerful, though: **the market's answer is 1:1.**
The risk-minimising ratio is 1.20, a flat 1:1 captures 50.9 of the 52.6%, and it
needs no estimation, no lattice and no trailing window. The causal empirical
ratio (40-session trailing regression, median 0.31) is *worse* than 1:1 — it
inherits the daily attenuation it is fitted on.

The tree ratio also fails as engineering: median 1.43 but IQR [0.40, 2.16] and
only 79.6% of contract-days inside `|λ| ≤ 3`, because with few shared meetings
the least squares is near-degenerate. With one shared meeting it is exactly
solvable and λ is arbitrary — measured up to 6.3 in probing, which is why the
module refuses to fit below two.

## 3. Why it cannot be used: the hedge removes the edge

Matched across ratio modes on identical trades (`map_odd`, fade, per trade):

| λ | gross | dispersion | bill | **gross per unit risk** | risk vs unhedged | **edge vs unhedged** |
|---|---:|---:|---:|---:|---:|---:|
| none | 0.584 | 2.741 | 1.844 | **0.213** | 1.000 | 1.000 |
| one | 0.330 | 1.981 | 3.695 | 0.167 | 0.723 | **0.565** |
| tree | 0.340 | 2.386 | 4.720 | 0.143 | 0.870 | 0.582 |
| emp | 0.297 | 2.357 | 2.535 | 0.126 | 0.860 | 0.508 |

The 1:1 hedge takes out **28% of the dispersion and 44% of the edge**. Gross per
unit of risk falls from 0.213 to 0.167 — the hedge makes the trade worse **at
zero cost**, so no execution assumption can rescue it. Then it doubles the bill.

Because every ratio mode runs the *same trades*, the edge reduction is a paired
quantity and is well estimated rather than a difference of noisy medians:

| λ | paired trades | edge removed | SE | t | share of edge | risk ratio | gross/risk before → after |
|---|---:|---:|---:|---:|---:|---:|---|
| one | 442 | 0.237bp | 0.070 | **3.37** | 39.8% | 0.765 | 0.2122 → 0.1669 |
| tree | 337 | 0.340bp | 0.137 | **2.47** | 59.4% | 0.824 | 0.2229 → 0.1099 |
| emp | 423 | 0.196bp | 0.046 | **4.24** | 32.7% | 0.837 | 0.2149 → 0.1728 |

(The trades pool across configs sharing dates, so the t overstates significance;
the magnitudes and the uniform sign are the point.) **Every ratio degrades
gross-per-unit-risk.** There is no size at which the calendar leg improves the
trade.

The reason is structural and, in hindsight, forced. The two expiries share
meetings; the far contract's cell map is rich and cheap in the same places the
near one's is, because it is the near one's map convolved with the extra
meetings. **The mispricing being traded lives in the shared component — which is
exactly the component a shared-meeting hedge is built to cancel.** A hedge that
neutralises the risk you are paid for is not a hedge; it is a smaller position
with extra legs.

This is the general shape of the whole vol-vs-linear/vol-vs-vol question in this
program: the linear leg could not hedge the payoff at all, and the instrument
that *can* hedge it can only do so by also hedging away the reason to hold it.

## 4. The cross-expiry disagreement is not a trade either

The same pairing defines a signal nobody here had run: the same count cell at the
same absolute rate priced on two adjacent expiries, each leg measured against its
own standing premium and its own trailing tilt, then differenced. Its residual is
the disagreement about the meetings only the far expiry resolves — the object the
impdist study could measure (options' implied conditional 0.26/0.49 against ZQ's
0.17/0.26) but only call indicative, because a one-Bernoulli deconvolution left
an L1 residual of 0.33–0.41.

**Kill criterion 3 fires.** The calendar signal grosses 0.246bp/trade against the
unhedged outcome-map row's 0.584 — it is worse than the thing it was meant to
improve, on 25–28 trades per config against 2.8–5.4bp of cost. The weak
deconvolution fit measured then and the weak calendar signal measured now are the
same fact: adjacent SR3 expiries do not disagree about their shared meetings by
enough to trade, and what they do disagree about (the extra meetings, 28% of the
package's own exposure) is too small and too noisy to pay for a second package.

## 5. The grid

128 configs × 3 worlds. 16 are `calendar` × `λ=none`, meaningless by construction
and recorded as skipped rather than merged. Of the 88 that trade:

* **0% positive at 1× costs**; median −132bp; best −37.5bp; DSR 0.000 at 128.
* The best n-floored config in the entire grid is **`map_odd`, λ = none** — the
  row with no calendar leg at all, which is the prior study's control.
* Neighbourhood 0/13 positive; every move away from "no hedge" is worse.
* Sign test an exact mirror on every cell.
* Placebos: best-of-128 gross 60.7 (Gaussian) and 60.9 (wrong calendar) against
  the real world's 49.7 — the placebos again match or beat the real world, as in
  the outcome-map study, confirming there is no lattice-specific content in what
  survives.

**Control check**: `map_odd` / λ=none reproduces `pair_odd_dev` from the prior
league on the paired subsample — 97 trades at 0.919bp/trade gross and 1.851bp of
cost, against 98 at 0.994 and 1.847 — with pairing retaining 98.7% of packages.
The calendar plumbing did not change the underlying trade.

## Verdicts

- **Adjacent-expiry fly as a hedge**: *works and is not worth using*. 51% of
  variance at 1:1 with no estimation is the best hedge measured anywhere in this
  program, and it lowers gross-per-unit-risk because it cancels the shared
  component the edge lives in. **DEAD, for a reason that is not cost.**
- **The lattice as a hedge-ratio source**: **DEAD** for density payoffs, now
  measured twice (5.7× on the linear leg, 2.0× here). Use 1:1.
- **Cross-expiry cell disagreement as a signal**: **DEAD** — worse than the
  single-expiry signal it was meant to improve.
- **Anything ALIVE**: no. 0 of 88 traded configs positive at 1×.

## Honest limits

- One rate cycle plus its tail; the paired sample starts 2021-11 and 2021
  contributes almost nothing (ZIRP produces no map).
- The hedge is charged the same half-tick per contract as the package; a second
  expiry is typically less liquid than the first, so the 3.69bp/trade figure
  **understates** the real bill and understates the verdict's direction.
- The variance-reduction figures are computed on the packages this study
  actually traded (`pair_odd_dev` cell pairs); a different package shape could
  hedge better or worse, though the shared-component argument in §3 is a property
  of the nesting relation rather than of the package.
- The risk-minimising λ is chosen on a grid in-sample; the 1:1 figure alongside
  it is the honest out-of-sample-safe number and is the one quoted in the
  verdicts.

## What would change the verdict

Nothing in this direction. The two hedging instruments available to a cell
package are now both measured: the linear market cannot hedge a density, and the
adjacent expiry can only hedge it by cancelling the trade. If the outcome-map
edge is to be collected it has to be collected **unhedged and at maker** — the
unhedged row is positive at 0× cost (+0.58 to +0.99bp/trade) and negative at 1×,
which is where the prior study also ended. That is now a closed question with two
independent hedging routes eliminated rather than one.
