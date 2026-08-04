# Outcome-Map RV — Findings

**Date:** 2026-08-04
**Branch:** `feat/outcome-map-rv` (worktree `ARBS-xm`, off `origin/main`)
**Design:** `2026-08-04-outcome-map-rv-design.md`
**Executed notebooks:** `notebooks/rv/outcome_map_atlas.ipynb`,
`notebooks/backtests/outcome_map_{league,autopsy}.ipynb` (0 errors, 0 unrun)
**Module:** `RVUtils/OutcomeMap/` (27 synthetic tests, all five mutations of the
load-bearing logic caught)
**Panels:** `notebooks/data/outcome_map/` (gitignored)

## The question and the answer

The mission was to finally trade vol AGAINST linear: enumerate each SR3
quarterly's FOMC outcome space, price every count cell twice — listed options
and the ZQ/FOMC-swap lattice — and trade the cell-level disagreements with a
real linear leg on. The cost thesis was that an options-vs-options core would
leave only a RESIDUAL linear hedge, unlike channel-1's full-digital hedge.

**Answer: nothing is ALIVE, and the linear leg does not earn its leg — for a
reason sharper than cost.** 0 of 360 configs are positive at 1× costs; the best
n-floored row breaks even at **0.99×**. But the study is not a repeat of
channel-1: the failure has a different shape and a measured mechanism.

## What went right — the trade-count problem is solved

Channel-1 died on **five trades in two years**. The cell instrument fixes that.
The 25bp butterfly centred on an atom prices a cell at `25bp × P(cell)` on a
lattice: four contracts for 25bp of payoff scale, against the exact
digital-difference's sixteen lots for 6.25bp — **4pp of probability to break
even instead of 16pp**, a fourfold improvement pinned by test.

| | channel-1 (PR #375) | outcome map |
|---|---:|---:|
| trades per config | 5 (in 2 years) | **median 47** (2021–2026) |
| sample | 2024-07 → 2026-07 | 2021-11 → 2026-07, 1,572 contract-days |
| break-even cost multiple | ~1.0× on 5 trades | 0.99× on 38 |

Pre-declared kill criterion 2 ("collapses to 1–5 trades") **does not fire**.

## What the atlas establishes (independent of any backtest)

### 1. The map lives on the wrong side of the feasibility frontier

A map needs three cells → two resolved meetings → for a quarterly whose option
expires *before* its reference window starts, roughly 60+ days to expiry. **50
of 1,572 contract-days (3.2%) sit under 60 dte.** The meeting-prob study put the
convergence channel *inside* 60 dte (89.5% channel-1 under 30 days, 0%
saturated). The outcome map, as an object, exists almost entirely outside the
region where convergence was measured to happen. ZIRP produces no map at all —
with every priced jump at zero the supports are degenerate and the lattice
collapses to one atom. **The map is an object of a moving policy rate, measured
where the lattice cannot carry the surface.**

### 2. One premium, redistributed — now measured over five years

| dte | contract-days | off-lattice premium | level `a` | tilt `b` | curvature `c` |
|---|---:|---:|---:|---:|---:|
| ≤ 90 | 168 | +14.6pp | −2.74bp | +1.92 | +1.24 |
| 90–130 | 504 | +21.2pp | −4.02bp | +1.73 | +2.49 |
| 130–160 | 364 | +23.3pp | −4.60bp | +1.69 | +2.45 |
| 160–200 | 536 | +29.3pp | −5.12bp | +0.96 | +2.26 |

The off-lattice premium is positive on **99.9%** of contract-days and grows with
dte exactly as the feasibility frontier said it should. By signed distance from
the forward, modal cells price **−4.57bp** and wing cells **+1.07bp**: the
triangle ledger's modal deficit and wing surplus, previously read on two dates
from a spline, now measured as *prices* on listed butterflies over 1,572
contract-days.

### 3. The tilt has a LEVEL, and that level is the cut tail

Fitted tilt `b`: mean **+1.479bp** per 25bp cell, positive on **78.6%** of
contract-days, yearly means +0.27 to +2.32. Relative to the lattice the surface
persistently holds more on-lattice mass at HIGHER rates. Mean and mass are both
pinned, so it has to be paid for off-lattice on the LOW-rate side: it is the
on-lattice shadow of a one-sided cut tail, which an even basis in `d` cannot
absorb. **Fading the raw tilt is a standing short of that tail in convergence
costume** — which is why the grid carries `pair_odd_dev`, measured against each
contract's own causal 20-session trailing tilt.

The ladder confirms the reasoning, on unhedged per-trade gross (fade, median
across configs): `map_full` +0.192 < `pair_odd` +0.307 < `pair_raw` +0.406 <
`pair_odd_dev` **+0.527** bp/trade. Projecting out the even part *alone* is
worse than doing nothing; removing the tilt's own level is what helps.

### 4. Everything decays in under a week

Pooled AR(1) within (symbol, cell): raw richness half-life **2.9** sessions, even
part 3.2, odd part 2.7, local residual 1.6 — three to six times faster than
family B's package richness (7–18 sessions).

### 5. The two linear markets agree, except where we knew they would not

Swap minus ZQ per-meeting jump over 9,177 (session, meeting) pairs: later
meetings median **+0.21bp** (MAD 1.14, 69.3% inside ±2bp); the first upcoming
meeting median **+1.46bp** (MAD 1.80, 47.3%) — the fixing-base contamination,
isolated and dropped from the hedge leg rather than silently used.

## The grid: 360 configs, nothing alive

Best n-floored row per rung (the `linear` column is the winner's own leg, so
`pair_odd`'s per-trade figure is 84% hedge leg — see below):

| expression | configs | best n | linear | best gross | per-trade | net@1× | net@2× | median cfg | NW t | DSR |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `pair_raw` | 72 | 57 | none | +45.2 | +0.79 | −52.8 | −150.8 | −185.9 | −2.16 | 0.00 |
| `pair_odd` | 72 | 38 | zq | **+143.8** | +3.78 | **−1.1** | −146.1 | −190.4 | −0.02 | 0.00 |
| `pair_odd_dev` | 72 | 43 | none | +39.5 | +0.92 | −37.5 | −114.5 | −166.1 | −1.18 | 0.00 |
| `map_full` | 72 | 12 | none | +10.2 | +0.85 | −3.2 | −16.6 | −67.1 | −0.27 | 0.00 |
| `reswin` | 72 | 25 | none | +34.5 | +1.38 | −9.0 | −52.5 | −91.0 | −0.65 | 0.00 |

Every rung scores MARGINAL-maker-only by the letter of the taxonomy (positive at
0×, negative at 1×) and DEAD in substance — see the verdicts below.

**0% of 360 configs positive at 1× costs**; median −132.5bp; best −1.15bp. DSR
0.000 at the full 360 trials everywhere. The sign test is an exact mirror on
every single cell (fade gross ≡ −momentum gross), so the direction is not in
doubt — only its size against the spread.

The winner's cost curve is the cleanest statement of the result: gross +143.8bp
over 38 trades, round trip 3.81bp, **break-even at 0.99× the house half-tick
model**. It is profitable at any maker fill and unprofitable at any taker fill —
though that headline gross does not survive its own autopsy, since 84% of it is
the mis-sized linear leg (below). The same statement holds, more modestly, for
every unhedged rung: positive at 0×, negative at 1×, per-trade gross of +0.19 to
+0.53bp against an option bill near 1.8bp.

## The linear leg, priced — and why it fails

Every config exists three times (no leg / ZQ basket / FOMC-swap package) over
*identical* trades: the option leg's P&L is bit-identical across the three
(`max |Δ| = 0.000000`), so every hedge number is a matched-pair measurement.

**Pre-declared kill criterion 1 FIRES, by 7×**: median unhedged fade gross
+13.6bp per config against a median ZQ bill of **95.3bp**. Per trade the linear
bill is **1.93bp against an option bill of 1.76bp** — the hedge costs more than
the thing it hedges. At one ZQ leg per meeting instead of the inherited
FedWatch three, the bill is 31.8bp per config — still 2.3× the gross.

Three diagnostics say the leg is not merely expensive but *wrong*:

1. **It raises risk.** Per-trade P&L standard deviation with the hedge on
   versus off: ×2.60 (`pair_odd`/ZQ), ×2.41 (`pair_raw`), ×2.94 (`reswin`),
   ×1.3–1.9 for the swap version. A hedge that nearly triples dispersion is
   adding a position, not removing one.
2. **The two markets disagree about it.** Same `h` vector, same trades, two
   markets that agree about the jumps to 0.2bp: hedge-P&L correlation 0.851 but
   a median swap/ZQ **ratio of 0.48**. Half of the "hedge contribution" is
   mark-source dependent.
3. **It is 5.7× too large.** Regressing the option leg's realised P&L on what
   the lattice predicted (`−hedge_bp`), through the origin, over 10,142 hedged
   trades: **beta 0.175, R² 0.166**; predicted std 6.54bp against realised
   2.81bp.

### The mechanism, and why channel-1 did not see it

Split by holding period the beta is **flat** — 0.134 (≤7d), 0.243 (8–16d),
0.181 (>16d) — so this is *not* stale-ratio drift, which more rebalancing would
fix. Split by realised move it is 0.484 (<2bp), 0.413 (2–8bp), 0.120 (≥8bp):
support migration adds damage on top for large moves, but even the smallest
moves want half the hedge.

**The same number arrives from upstream of everything.** Take a FIXED butterfly
and compare its two daily price series — market and lattice-fair — with no
hedge ratios, no jump marks and no trade selection anywhere in the calculation.
Over 120 (symbol, strike) series: median daily std **0.586bp for the market
against 1.065bp for the lattice**, the lattice moves more in **86.7%** of
series, and the regression of the market's change on the lattice's gives
**beta 0.295** (correlation 0.541), flat across lattice-mass buckets
(0.22–0.38, so not a wing artefact). Two independent routes — a trade-level
hedge regression and a panel-level price-change regression — land on the same
0.2–0.3.

The reason is geometric. **A digital's lattice sensitivity is a difference of
CDFs; a butterfly's is a density.** Channel-1 hedged a digital and its
replication identity held on every outcome branch (tested ×4). The market's
density is the lattice's density smeared by exactly the off-lattice premium the
atlas measures at 15–29pp, so for a density-like payoff the mismatch is
first-order: the tree's flies are far more sensitive to a meeting repricing than
the market's flies are. Rescaled to its own in-sample optimum (k ≈ 0.175–0.25)
the basket cuts per-trade dispersion only from 2.81 to 2.57bp — a 9% risk
reduction for 0.34bp/trade of cost, against an option leg earning 0.2–0.5bp.

### What the winner's headline gross actually was

Rescaling only the basket, on the winner's own 38 trades (in-sample, and the
point is the shape not the level):

| k | | gross | cost | net@1× | per-trade gross | per-trade std |
|---:|---|---:|---:|---:|---:|---:|
| 1.000 | as traded | +143.8 | 144.9 | −1.1 | 3.783 | **8.51** |
| 0.500 | half | +83.1 | 104.7 | −21.6 | 2.187 | 4.38 |
| 0.175 | beta-sized | +43.7 | 78.6 | −34.9 | 1.149 | **2.92** |
| 0.000 | unhedged | +22.5 | 64.5 | −42.0 | 0.591 | 3.27 |

**The gross scales almost linearly with the basket size** — which is the
definition of a directional position mislabelled as a hedge. 84% of the
winner's headline +143.8bp is a leveraged rates bet that paid because 2022–23
happened, and the mirror-image config loses exactly as much.

The fair version of the conclusion, though, is not "the hedge is worthless". At
its *statistically correct* size the leg does behave like a hedge: per-trade
dispersion falls 3.27 → **2.92** (−11%, the only k at which it falls at all),
and it costs 0.37bp/trade for +0.56bp/trade of gross, a net +0.19bp/trade. The
problem is the size of the hole: the option leg earns +0.59bp/trade against
+1.70bp/trade of its own costs, so even a perfectly sized linear leg closes
about a sixth of the gap — and its contribution is the same directional term
scaled down, which does not survive the ZQ-vs-swap consistency test (ratio 0.48).

**This is the closed answer the handover asked for: the linear leg does not earn
its leg, and not because the trade is too small — because the hedge ratio the
lattice supplies is the wrong object for the payoff that made the trade
affordable.** At the prescribed size it triples risk; at the correct size it is
too small to matter. The cheap instrument and the hedgeable instrument are not
the same instrument. That is a real trade-off, not a tuning failure.

## The placebos

| world | best-of-360 gross | at the winner's own coordinates | retention |
|---|---:|---:|---:|
| real | +143.8 | +143.8 (38 trades) | — |
| P1 Gaussian tree | +49.0 | +30.2 (25 trades) | **21%** |
| P2 wrong calendar | +25.9 | +126.6 (37 trades) | **88%** |

Read on best-of-360 against best-of-360 (equal trial counts, the fair
comparison), kill criterion 3 does not fire. Read at the winner's own
coordinates it is damning: the **wrong-calendar world reproduces 88% of the
winner's gross**. P2 keeps the map's geometry — the 25bp cell grid, the number
of meetings — and destroys only which meeting carries which probability; P1
destroys the geometry too and keeps 21%. Together they locate the content
precisely: **what the winner trades is the cell GEOMETRY, not the FOMC lattice's
probability structure.** The lattice supplies the strike grid and nothing else
that pays.

## Two structural results worth keeping

**1. Through a decision, the surface is right and the lattice is wrong.**
`reswin` — enter 1–5 sessions before a decision, exit after it — earns
**−0.580bp/trade unhedged on the fade**, negative in every config. The odd
cell-map disagreement *widens* through the resolution. Momentum through the
decision is the (equally uncollectable) +0.58bp/trade mirror. This is the
opposite sign to channel-1's convergence result, on a different object (count-map
tilt, not digital level) in a different regime (>60 dte, not <60), and it says
the pre-decision map disagreement is information rather than noise.

**2. The signal does not converge over the hold.** For the winner,
`|exit signal| / |entry signal|` has a median of **1.24** and only 42% of trades
finish inside their entry signal; across converge-exit configs only ~30–35% hit
the half-signal target inside 15 sessions. The odd component reverts with a
2.7-session half-life *as a series*, but the tradeable package's own signal does
not shrink over a holding period — the reversion lives at a frequency the EOD
package cannot hold.

## Verdicts (house taxonomy)

- **Cell-pair RV (`pair_odd`, `pair_odd_dev`), any linear leg:**
  MARGINAL-maker-only by the letter of the taxonomy (positive at 0× cost,
  negative at 1×), **DEAD in substance** — DSR 0.000 at 360 trials, median
  config −132bp, neighbourhood 0/17 positive, halves decaying 6.0 → 1.6bp per
  trade, 88% placebo retention at the winner's coordinates.
- **The full-map book (`map_full`):** telescoping works — 5.4 contracts against
  a pair's 7.2 — and it is the cheapest expression in the study, but its gross
  is the smallest too. DEAD.
- **The resolution window (`reswin`):** DEAD on the fade, and its mirror does not
  clear costs either.
- **The linear leg (the mission's question):** **closed.** Not cost-bound in the
  ordinary sense; mis-specified for this payoff. Kill criterion 1 fires at 7×
  and the hedge is measured at 5.7× too large.

## Honest limits

- One rate cycle plus its tail; 2021 contributes 28 contract-days and no map.
- Costs are the house half-tick model per contract per side; the 2021–22 era was
  thinner than that model assumes, which flatters nothing here (every verdict is
  negative at 1×) but would matter to a maker case.
- The hedge is marked through jump panels, not through individually simulated ZQ
  or swap fills; support-migration rebalances are charged only at meeting
  resolutions, which *understates* the linear bill and therefore understates
  kill criterion 1.
- The k-rescaling of the basket is post-hoc and in-sample; it is used only to
  distinguish "wrong size" from "wrong idea", never as a strategy.
- Butterfly centres are snapped to the listed 6.25/12.5bp strike grid (median
  error 1.5bp, max 12.25bp) and the tree-fair price is computed on the same
  snapped legs, so richness is market-vs-tree on an identical package.
- The threshold axis is NOT comparable across expressions: a pair's strength is
  a spread (max − min of the odd component) while `map_full`'s is a mean
  absolute deviation, so the same pp threshold bites harder on the book (12
  trades at 16pp against a pair's 46–56). Each rung is read against itself.
- `reswin` overrides the exit rule with "the session after the decision", so its
  two exit cells are duplicates and 36 of its 72 configs are identical rows.
  They are still counted in the 360 trials, which makes the DSR penalty
  slightly conservative rather than slightly flattering.

## What would change the verdict

- **A hedge instrument whose sensitivity is a density, not a level.** The
  measured beta says the linear leg is the wrong shape for a butterfly. A
  meeting-dated *option* (or a second butterfly on an adjacent expiry) would
  hedge a density with a density. That is the natural successor question, and it
  is a vol-vs-vol hedge, not a vol-vs-linear one.
- **Maker execution.** Every expression is profitable at 0× and the winner
  breaks even at 0.99×; the entire result sits inside one round trip. As with
  family E, the honest statement is that the edge is real, standing, and
  currently un-collectable at taker.
- **Intraday.** Component half-lives of 1.6–3.2 sessions with a package signal
  that does not shrink over a 15-session hold is the signature of a reversion
  living below the EOD sampling frequency. That was the recommendation the
  linvol grid ended on; this study did not weaken it.
