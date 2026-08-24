# CA vs fly, comprehensively re-measured — 515 pre-registered cells, and two phantoms

Block 3 of the convexity RV programme (2026-08-24). The brief: backtest the 3M
SOFR futures convexity adjustment — outrights, packs, bundles — against USD
SOFR butterflies in spot and forward-starting space, on the repaired
Query/MDP/TimeseriesBuilder path, trusting none of the previous results, with
technical (mean-reversion/pairs) and fundamental (positioning, CME–LCH basis,
carry) variations.

Everything below was measured on this machine; the search space was frozen in
`docs/convexityrv/cavf-grid-preregistration.md` BEFORE scoring, with three
dated amendments (a declared JPM-threshold variant added after the corpus
synthesis, and two execution-convention amendments described below).

## The data, first

| panel | size | quality |
|---|---|---|
| CA via `IRSwapsTB.sfr_cvx_adj` (Q/Q matched swap) | 1,409 dates × **31 labels** (5 packs, SFR1..20, 2 legacy + **4 CME bundles**), 2021-01-04..2026-08-21 | **zero pricing failures, zero missing cells**; BLUES/GOLDS tie to Citi's printed 6/9/2023 screen at +0.3/−0.6bp; the annual-frequency negative control fails by −3.9bp as it must |
| fly legs (spot + 1/2/3/**4**/5y forward starts) | 1,407 dates × 48 tenors | 100% dense |
| CFTC TFF positioning | refreshed to 2026-08-18 | dealer/lev/am nets, release-lagged 3bd |
| CME–LCH basis (gs_quant) | 2018-04-27..2026-08-24, 11 tenors | offline cache; tail warm cost 4 HTTP calls |

`BUNDLE{N}Y` (front-anchored ranks 1..4N — the CME convention) was added to
the TB vocabulary; the legacy `BUNDLE{b}` 16-quarter windows are a different
object and both are pinned side by side in
`tests/test_convexity_rv_cavf_vocab.py`. On the brief's fourth word,
"packages": every CA structure here IS a futures-plus-matched-swap package
(CME's own sense of the word — packs and bundles are execution strategies
over the same legs), and arbitrary multi-contract windows are the rank spans
the vocabulary already expresses; no separate "package" object exists to add.

The curve MDP convention for the block is `IRSwapsMDP(source="citivelo_excel_rl")`
(user preference, 2026-08-24), measured bit-identical to the `CITIVELO_EXCEL`
spelling on the CA path (max |diff| 0.0bp).

## The two phantoms — the block's most valuable numbers

The first grid pass printed **100% hit rates on 38–72 episodes with 3–5-day
holds and per-episode P&L an order of magnitude above the CA level itself**
($68.7M gross on a structure whose CA runs 1–3bp). Two mechanisms, both now
amendments in the pre-registration, both carried by tests:

1. **Mark-noise harvesting.** The CA mark is a composite of a 17:00-nearest-bar
   futures price and a separately-timed swap curve (documented timing noise
   0.89–2.55bp/pack-day). A z-rule that enters AT the mark it was computed
   from buys the noise and is filled at a price nobody can trade. Fills now
   lag decisions by one mark; the same-day diagnostic measures the harvest at
   **$0.15–0.9M per median cell** (median hit 0.93 same-day vs 0.45 real). A
   known-answer test pins the convention: engineered i.i.d. noise pays
   ~$25M/5.6y at same-day fills and must die at t+1.
2. **IMM-roll label switching.** Every structure label is constant-RANK; at
   each quarterly roll it swaps contracts, and **22 of 33 SR3 rolls are FOMC
   decision dates**, so the jump is systematically signed. The June-2022
   "win" the second pass booked was literally the 2022-06-15 roll/FOMC jump.
   Signals and panel P&L now use roll-spliced series (jump removed, level
   backward-adjusted); the raw CM level remains the screener's display
   quantity.

Any CA mean-reversion result anywhere that does not state its fill convention
and roll handling should be assumed to be harvesting one or both.

## The grid verdict — dead, at its own declared size

With t+1 fills and roll-spliced series, $100k CA DV01, zero cost unless
stated:

| family | median gross | median net @1× | median ann Sharpe |
|---|---:|---:|---:|
| A — pairs (changes-β) | **−$592k** | −$1.74M | −0.27 |
| B — fair-value (levels fit) | **−$701k** | −$2.29M | −0.21 |
| A-control — CA only | −$514k | −$1.78M | −0.40 |
| B-jpm (R²≥0.6 gate, zero-cross exit) | $0 (1 median episode) | −$191k | −0.15 |
| B-pinned (Citi's printed Blues line) | +$69k | −$991k | +0.01 |
| C/D/E overlays (positioning / basis / carry) | +$21k / −$3k / $0 | all negative | ≈0 |
| **A-control — fly only** | **+$640k** | **−$880k** | +0.41 |

* Best single cell of 515: a fly-only control at ann Sharpe **1.23** —
  **below** the annualised E[max SR | null, 515 trials] of **1.29**, before a
  basis point of cost. Per-hold null 0.51 at median n_eff 36.
* Deflated Sharpe of the best of the traded cells (Bailey effective-N over the
  actual cross-cell correlation): **0.22**, far below the 0.95 bar.
* The pre-registration's declared resampling null — SHARED sign flips, which
  keep the grid's cross-cell correlation (a row permutation leaves a Sharpe
  exactly unchanged) — gives the best cell a family-wise **p = 0.42**: the
  observed best per-observation Sharpe (0.587) equals the null max's own mean
  (0.592).
* Placebo: lagging the signal +20bd kills the top cells' gross.
* The only positive-median family is the **fly-only control** — not a
  convexity trade at all, and negative at 1× its own per-leg costs, consistent
  with the house's earlier fly mean-reversion verdict (+0.75bp/trade edge vs
  1.5bp cost).
* Costs per leg (0.25bp futures package / 0.5bp swap / 0.5bp per fly leg on
  leg DV01 ≈ $95k per pairs round trip at 1×) remove $1.1–1.6M from median
  cells; nothing was alive gross, so costs are the second bullet, not the
  cause of death.

## The headline measurement: forward-start-matched flies — mechanism yes, trade no

The hypothesis — a fly whose forward start sits at the structure's expiry
should hedge its CA better, improvement growing with T1 — was previously
rejected only on ranks ≤10 (T1 ≤ 2.5y). With Blues and Golds daily 2021–2026
for the first time and a 4Y start added to the universe, **the reading
changes**: the peak-R² forward start now RISES with the structure's depth —
front structures peak at spot and die by a 2Y start (WHITES 0.386 → 0.003),
while BLUES peaks at the 2Y start (0.332) and GOLDS at 3Y (0.240) — a
regression of peak start on T1 gives slope **+0.69** against the shallow-era
−0.018 and the predicted +1.0. The vol-locality mechanism became visible the
moment the deep data existed. What did not appear is STRENGTH: the deep peaks
top out at R² 0.24–0.33, too weak to size a hedge, and the declared grid cells
built on matched-start flies lose like everything else. Citi's 2s5s10s remains
a fair-value regressor at monthly horizons, not a daily hedge. A mechanism
without a trade — and the one place "do not trust the previous results"
legitimately flipped a conclusion, exactly where the old rejection was
scope-limited rather than wrong.

## Engine certification — decomposed, and it caught two live defects

First pass certified at **corr −0.005**, which was the harness working: two
sign defects were found and fixed the same hour, both now pinned by tests:

* **Negative `contracts` on a `STIRFutureQuery` silently goes LONG** — the
  outright builder flips the risk weight for a negative size AND the rateslib
  leg carries the negative notional, so the two negations cancel. Direction
  must ride the risk weight with contracts kept positive. (Repo-wide trap;
  candidate upstream hardening: refuse negative contracts loudly.)
* **`abs(β)` on the pair hedge** — a negative β flips the fly leg, it does
  not shrink it.

Post-fix, on the panel's own fill dates:

| book | blended daily corr | non-roll per-episode median | engine vs panel terminal |
|---|---:|---:|---|
| BLUES × 2s5s10s (CA package only) | +0.36 | **+0.85** | $3.33M vs $0.83M |
| BLUES × 2s5s10s (with fly) | +0.34 | **+0.90** | $2.87M vs $0.93M |
| GOLDS × 2s5s10s@5Y | +0.39 | +0.38 (2 clean episodes) | $3.09M vs $0.12M |
| SFR20 × 1s2s3s@5Y | +0.31 | +0.47 | −$0.48M vs $2.23M |

The residuals are named and sized: (1) the TB path's ¼-tick pack-price
rounding puts up to 0.125bp of quantisation into the panel's daily change —
a correlation ceiling the engine's unrounded settles don't share; (2) roll
handling (7/13 Blues episodes cross a roll; the engine holds the original
window); (3) **fixed-window carry** — a held window's CA slides down the T1²
curve while a constant-rank panel cannot see slide; (4) **the traded swap is
the annual-spec instrument while the CA is measured Q/Q** — its rate moves
`0.75·r·Δr` more per move (measured +0.58bp on the 20bp rally week of
2024-07-01..09, exactly the compounding term; the same residual w2b recorded
as its 0.90 sign-probe slope). The slide is Citi's own
"3m roll" column, and the engine-level book that DOES earn it was already
measured on this same repaired data by w2b: **gross Sharpe 0.130, below its
own six-trial null**. The carry was already inside the corpse.

The deep single-contract outrights (SFR12–20) deserve their own sentence: their
CA series swing ±10–20bp on curve-vs-futures dislocations around meeting
repricings — Citi's stated reason for trading packs, "individual ED/FRA
spreads are noisy and hard to trade", measured. Their cells are reported but
their marks are the least trustworthy on the board.

## Interpretation

Huggins & Schaller (2022, ch. 6) point out the SR3 payout lands at the END of
its reference period: the contract has **no Jensen convexity of its own**, so
the measured CA is financing/margin bias plus positioning plus microstructure
(Attack68: those effects "can engulf the theoretical prices"). That is
consistent with everything measured here — a level that ties to Citi's screen,
carries a real positioning mechanism (reproduced in Blues only, w2b §5), and
still offers no tradable daily mean reversion against any fly at these costs.

## What survives

The measurement stack, not a trade: the 31-structure CA panel with its
tie-outs and failure ledger, the 48-tenor fly-leg panel, the roll-splice and
t+1 conventions with their known-answer tests, the engine layer with the sign
traps pinned, the certification harness, and the live screener
(`notebooks/rv/sfr_ca_vs_fly_screener.ipynb`) that presents levels, fits,
implied-vs-realised vol, carry, positioning and the CCP-basis wedge with the
verdict attached.

## Reproduction

```
python notebooks/backtests/convexity_rv/_cavf_backfill_ca.py      # ~6 min
python notebooks/backtests/convexity_rv/_cavf_backfill_legs.py    # ~15 min
python notebooks/backtests/convexity_rv/_cavf_run_grid.py         # ~45 s
python notebooks/backtests/convexity_rv/_cavf_certify.py          # ~3 min
# then the notebook gate on cavf_backtest.py and the screener
```

Suites: `tests/test_convexity_rv_cavf_{vocab,signals,grid,engine}.py` —
76 tests; signal mutants 4/4 killed; the noise-harvest and roll-splice
conventions each carry a known-answer test that fails if the convention is
lost.
