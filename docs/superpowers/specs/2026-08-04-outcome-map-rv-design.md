# Outcome-Map RV — Design

**Date:** 2026-08-04
**Branch:** `feat/outcome-map-rv` (worktree `ARBS-xm`, off `origin/main`)
**Handover:** `2026-08-04-outcome-map-rv-handover.md`
**Predecessors:** `2026-07-30-zq-sr3-meeting-prob-*`, `2026-08-02-impdist-linear-vs-vol-*`,
`2026-08-03-linvol-backtest-grid-*`, `2026-08-04-family-b-dispersion-*`

## The question

Every framework in this line has used the linear market (ZQ / FOMC swaps) as a
*measuring stick* and traded options against it one boundary at a time. The two
verdicts that matter:

* channel-1 (fade a listed boundary digital vs the ZQ tree, full digital hedged
  with a ZQ basket) — mechanism certified by placebos, **5 trades in 2 years**,
  the hedge's traffic ate the edge;
* the dispersion premium (modal deficit ≡ wing surplus) — **one** premium, fairly
  priced in both directions, not many edges.

This study asks whether the *whole outcome map* — every count cell of a
quarterly's resolved-meeting space, priced twice — contains a **shape**
disagreement that survives when the standing dispersion premium is projected
out, and whether an options-vs-options expression of it makes the linear leg
small enough to earn its costs.

## What the outcome map is (and what exchangeability leaves of it)

For a quarterly SR3 option every resolved-by-expiry meeting carries day-weight
1, so orderings collapse to the **total move count**: the identified object is
the count distribution, i.e. a set of atoms on a 25bp grid around the forward.
Two-point supports per meeting (the FedWatch convention) put those atoms at
`base + n * 25bp`. The outcome map is therefore a vector of **cells**, one per
distinct atom, each priced twice:

* `p_lin` — the ZQ FedWatch lattice (second read: the FOMC-swap lattice), smeared
  by the unresolved meetings;
* `p_opt` — the listed option surface.

### The cell instrument: the 25bp butterfly

The exact cell indicator is a difference of two digitals — four legs of 6.25bp
verticals at **16 lots per probability unit**, i.e. 1.0bp of round-trip cost for
6.25bp of payoff scale: 16pp of probability just to break even. That is the
arithmetic that killed channel-1.

The 25bp butterfly centred on an atom (`C(k-0.25), -2 C(k), C(k+0.25)`) is a
triangular kernel that vanishes at the neighbouring atoms: on a pure lattice its
price **is** `25bp * P(cell)`. Four contracts, 1.0bp round trip, 25bp of payoff
scale — **4pp of probability to break even**, four times cheaper per unit of
probability than the digital-difference. Every expression below is built from
these flies, marked from LISTED premiums on the parity-completed surface.

Two consequences to keep honest:

1. The kernels sum to a partition of unity only in the interior, so
   `sum_i price_i / 25` is *below* 1 by the mass the lattice cannot carry. That
   deficit **is** the off-lattice premium — measured, not assumed.
2. The strike grid is 6.25bp / 12.5bp, so the fly centre is rounded onto the
   listed grid (offset recorded per cell). The tree-fair price is computed on the
   **same rounded legs**, so richness is market-vs-tree on an identical package.

### Cell richness and its even/odd decomposition

Per contract-day, per cell `i`:

```
r_i   = market_fly_i - tree_fair_fly_i          (bp of premium)
d_i   = (atom_rate_i - forward) / 0.25          (signed distance in 25bp cells)
r_i  ~= a + b*d_i + c*d_i^2 + e_i               (OLS over the day's cells)
```

* `a`, `c` — **even** in `d`: the standing dispersion / off-lattice premium.
  Probability conservation says the modal deficit *is* the wing surplus; family B
  and the linvol grid both measured it as fairly-priced insurance. One price.
* `b*d_i` — **odd**: the map is TILTED, i.e. the surface puts more on-lattice
  mass on one side of the forward than the lattice does. Both the mean and the
  total mass are pinned (parity + mean-pinning), so an on-lattice tilt is
  compensated off-lattice: it is a genuine statement about *where* the priced
  path sits, and it is the one component a linear market also prices.
* `e_i` — local, per-cell residual.

**The thesis of this study**: the odd component is the part of the map that a
linear hedge is *for*. A tilt package (long the cheap-end fly, short the rich-end
fly) is directional in count space; the ZQ meeting basket or the FOMC-swap
package is the instrument that neutralises exactly that direction. If the linear
leg cannot earn its costs *here*, it cannot earn them anywhere in this line.

## Expressions (pre-declared)

All packages: fixed legs from the entry day, one open package per symbol, lag-1
entry on the global session calendar, listed marks only.

| id | package | contracts | signal |
|---|---|---:|---|
| `pair_raw` | long min-`r` cell fly, short max-`r` cell fly | 8 (6 if the two flies share a cancelling strike) | `max r - min r` |
| `pair_odd` | long the cheap-end fly, short the rich-end fly, ends chosen by the fitted tilt `b` | 8 (6) | `|b| * (d_max - d_min)` |
| `map_full` | every cell, weight ∝ `-(r_i - mean r)`, normalised to `sum|w| = 2`, telescoped over strikes | `sum|w_net|` after telescoping | `sum_i |r_i - mean r| / n` |
| `reswin` | `pair_odd`, entered only 1–5 sessions before a decision, exit the session after it | 8 (6) | as `pair_odd` |

`pair_raw` is the control: with the standing premium left in, the "cheapest
cell" is the modal one and the "richest" a wing, so it should collapse onto the
already-dead dispersion trade. If `pair_odd` does not separate from it, the
even/odd split bought nothing and the answer is written accordingly.

### The linear leg

`h_m = d(package tree-fair value in bp) / d(jump_m in bp)`, computed in the
**frame-frozen** representation (`AtomEngine.rates_probs(..., q_ref=)`) so atom
locations are held at absolute rates and the package is multilinear in the
per-meeting probabilities. Hedge P&L over the hold is `-side * sum_m h_m *
d(jump_m)`, re-ratioed (and re-charged) when a meeting resolves.

* `none` — unhedged; the drift beta to the forward is reported, not neutralised.
* `zq` — jumps marked off the daily ZQ FedWatch ladder.
* `swap` — jumps marked off the daily `USD-SOFR-1D-Q12xM12STIRT` meeting-dated
  swap ladder (`RVUtils/MeetingProb/swap_ladder.py`); no bootstrap, no expiry
  seam. **Never used as a hedge leg before in this program.**

Contract counts and costs follow the house convention already in
`RVUtils/MeetingProb/backtest.package_cost_bp` (ZQ basket = 3 legs per meeting,
DV01-converted), charged per rebalance; `tcost_vol_bp` and `tcost_linear_bp` are
separate dials so the linear leg's bill is always separable from the option
leg's.

## Sample and data

* **Quotes** — `famb_common.load_quotes()`: lab panel + the 2021-02→2026-07
  backfill parts, 376k rows, 26 quarterlies; parity-completed
  (`premium_surface`, `C = P + DF(F-K)`) because the panel is OTM-only.
* **Forwards** — serff SR3 settles (`sr3_forwards`, option root `SFR*` ↔ futures
  cache `SR3*`).
* **Lattice** — `meeting_ladder` off cached ZQ settles + the FOMC registry;
  `split_meetings` / `AtomEngine` for the atoms; smear
  `sqrt(unresolved_var + 3^2)` (the strict ZQ-null convention used by every
  previous panel in this line).
* **Second linear read** — daily swap ladder, with a per-meeting tie-out gate
  against ZQ. (Measured: 0.1–1.1s per build date, available 2021→2026; the FIRST
  upcoming meeting's swap jump is known to be contaminated by the fixing base —
  gated, not silently used.)
* Ranks 1–3 (front three quarterlies), cells requiring all three fly legs to have
  marks, `n_cells >= 3`.

The sample spans 2021-02 → 2026-07: ZIRP, the 2022 hiking cycle, SVB, the
2024 cutting cycle and the 2025-26 pause. Costs in the 2021–22 era were thinner
than the half-tick model assumes — flagged, never adjusted away.

## The grid (pre-declared, 288 configs)

```
expression  {pair_raw, pair_odd, map_full, reswin}      4
dte band    {<30, 30-60, <60}                           3
threshold   {4pp, 8pp}  (= 1.0bp, 2.0bp of fly premium) 2
exit        {converge-half, hold-15}                    2
linear leg  {none, zq, swap}                            3
direction   {fade, momentum}                            2
                                                    = 288
```

`reswin` overrides `exit` with "the session after the decision" but still runs
both exit cells (they differ only through the max-hold cap) so the trial count is
honest. 1bp of fly premium = 4pp of cell probability (25bp payoff scale) — the
thresholds are stated in pp to match the rest of the program.

## Statistics and discipline (house law)

* Both directions always; the sign test is `fade` vs `momentum` on gross.
* n ≥ 10 floor before any row is named a winner (`pick_winner`).
* DSR (`BT.signals.deflated_sharpe`) at the FULL trial count of 288, on per-trade
  nets, plus NW t on the daily position series.
* Chronological halves; neighbourhood count around the winner.
* Costs per contract per side (option half-tick 0.125bp, futures 0.25bp), reported
  at 0× / 1× / 2×.
* Probability conservation reported per contract-day (`sum_i p_opt - sum_i p_lin`
  = the off-lattice premium) — we are trading ONE premium redistributed.
* Notebooks compute their own conclusions; no asserted numbers in markdown.
* Verdicts via `RVUtils/SFRRVLab/stats.verdict`.

### Placebos (both re-derived INSIDE the placebo world)

* **P1 Gaussian tree** — tree-fair fly priced under a Gaussian with the same mean
  (forward) and the same total std (`event_std_zq` ⊕ smear), and cell centres
  placed on a 25bp grid anchored at the strike nearest the forward, so **no
  lattice information enters cell placement either**. Everything downstream
  (richness, the even/odd fit, cell selection) recomputed.
* **P2 wrong calendar** — `shifted_ladders`: every meeting wears the next
  meeting's jump/support/q. New atoms, new cell centres, new legs, new richness,
  new fit. If the edge survives, it was never lattice information.

## Kill criteria (pre-declared)

1. If the linear leg's costs exceed **half** the gross of the paired expression
   across the grid median → *"linear still doesn't earn its leg"*; write it up as
   a closed question rather than torturing the grid.
2. If the cell-pair expressions collapse to the same 1–5 trades / 2y as
   channel-1 → DEAD (too few trades), the EOD ceiling is confirmed, and the
   recommendation is the intraday escalation, not more EOD configs.
3. If the placebos retain the edge → it was never lattice information.
4. If `pair_odd` does not separate from `pair_raw` → the even/odd split bought
   nothing; report the map as one premium and stop.
5. **ALIVE** requires all of: n ≥ 10, positive at 2× costs, DSR > 0.5,
   non-negative median config in its family, mirrored sign test, and survival of
   both placebos.

## Deliverables

* `RVUtils/OutcomeMap/` — `cells.py` (map construction + even/odd decomposition),
  `structures.py` (fly legs, telescoping, contract counts), `hedge.py` (package
  hedge ratios, ZQ/swap legs, costs), `engine.py` (the trade loop). Synthetic,
  no-network tests in `tests/test_outcome_map.py`.
* `notebooks/backtests/outcome_map_common.py` (panels + placebos) and
  `run_outcome_map_grid.py`.
* `notebooks/rv/build_outcome_map_history.py` — the daily panels.
* Executed notebooks `outcome_map_atlas.ipynb` (the map, its decomposition, the
  conservation ledger), `outcome_map_league.ipynb` (the grid), and
  `outcome_map_autopsy.ipynb` (winner, halves, neighbourhood, placebos, the
  linear-leg bill).
* Findings doc, memory update, green fast gate, PR to main.
