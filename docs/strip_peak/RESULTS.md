# Strip-Peak-Fade — Results

**Date:** 2026-08-24
**Branch:** `feat/strip-peak-fade` (worktree `C:\Users\chris\clee\ARBS-spf`)
**Sources:** `bd619e4a` (strip builder) → `f6f010d1` (peak tracker) → `0d3ae9b6` (linear backtests) →
`f826a55a` (linear grid run) → `1a500b23`/`3c73e6d2` (vol butterfly) → `4ca6caff` (implied
distribution)

**Bottom line: weak pass, not a green light.** Spread fade at hold=21d clears cost
(+3.86bp gross, +1.86bp net of 2bp). Everything else — the butterfly, the short holds, the
long holds — either dies on cost or isn't a real sample. See §7.

---

## 1. Thesis

The SR3 (3-month SOFR futures) strip prices a single "peak" contract — the point on the
8-contract curve carrying the highest implied rate — and that peak migrates over time as
rate-path expectations shift. The thesis: the peak carries embedded premium from a
bimodal or skewed rate-path distribution (a genuine hump in the term structure, not
noise), and that premium should decay as the bimodality resolves, either because the
peak's rate falls relative to its neighbor (fade the calendar spread) or because the
curvature at the peak flattens (fade the butterfly). Four independent expressions of this
idea were tested: two linear (futures-only) structures priced directly off the strip, and
two options-implied structures (a discrete butterfly-grid mode and a continuous
Breeden-Litzenberger density mode) that test whether the options market's modal
expectation sits away from the futures forward and converges toward it.

## 2. What was tested

| Variant | Structure | What it measures | Data source | Status |
|---|---|---|---|---|
| A — Linear spread | Sell peak, buy peak+1; cost = 2 legs | Peak's rate falling relative to its neighbor | SR3 EOD settles (Barchart), fixed 8-contract strip | **Backtested** — full grid, 116 trading days, 5 hold periods × 3 cost levels |
| B — Linear butterfly | Buy peak−1, sell 2× peak, buy peak+1; cost = 4 legs | Curvature (kink) at the peak decaying | Same strip as A | **Backtested** — same grid |
| C — Vol butterfly | argmax of a discrete, listed-strike options butterfly grid vs. futures forward | Whether the options market's modal outcome sits away from the forward, and converges | SFR options listed strikes + put-call parity fill | **Infrastructure + 3-date snapshot** (SFRU27, 08-19→08-21). Full historical backtest deferred — needs rolling contracts. |
| D — Implied distribution | argmax of a continuous Breeden-Litzenberger risk-neutral density vs. forward | Same question as C, continuous spline density instead of a 6.25bp grid | Same options data, JPM raw-premium BL methodology | **Infrastructure + snapshot** (SFRU26 ×2 dates, SFRU27 ×3 dates). Full historical backtest deferred — same reason as C. |

Only A and B are backtested P&L series. C and D are point-in-time diagnostics — they
establish *that* a mode-vs-forward gap exists and roughly how big it is, not what trading
it would have earned. Treat §5 and §6 as findings about measurement, not performance.

## 3. Linear results (the quantitative core)

Full grid — every row from `analysis_outputs/strip_peak/linear_grid.csv`, 116-day strip,
`require_interior=True`.

### Spread (sell peak, buy peak+1; cost = 2 legs)

| hold_days | cost_bp | n_trades | hit_rate | avg_pnl_bp | sharpe | median_pnl_bp | total_pnl_bp | max_dd_bp |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5  | 0.0 | 52 | 55.8% | +0.19 | 0.17 | +0.50 | 10.0 | -29.00 |
| 5  | 1.0 | 52 | 28.8% | -0.81 | -0.72 | -0.50 | -42.0 | -49.50 |
| 5  | 2.0 | 52 | 21.2% | -1.81 | -1.60 | -1.50 | -94.0 | -100.00 |
| 10 | 0.0 | 47 | 59.6% | +0.85 | 0.63 | +0.50 | 40.0 | -28.50 |
| 10 | 1.0 | 47 | 42.6% | -0.15 | -0.11 | -0.50 | -7.0 | -41.50 |
| 10 | 2.0 | 47 | 27.7% | -1.15 | -0.85 | -1.50 | -54.0 | -55.50 |
| **21** | **0.0** | **36** | **80.6%** | **+3.86** | **1.97** | +3.25 | 139.0 | -8.00 |
| **21** | **2.0** | **36** | **63.9%** | **+1.86** | **0.95** | +1.25 | 67.0 | -19.00 |
| 21 | 1.0 | 36 | 77.8% | +2.86 | 1.46 | +2.25 | 103.0 | -13.00 |
| 42 | 0.0 | 18 | 100.0% | +12.65 | 18.77 | +12.88 | 227.75 | 0.00 |
| 42 | 1.0 | 18 | 100.0% | +11.65 | 17.29 | +11.88 | 209.75 | 0.00 |
| 42 | 2.0 | 18 | 100.0% | +10.65 | 15.80 | +10.88 | 191.75 | 0.00 |
| 63 | 0.0 | 1  | 100.0% | +16.50 | 0.00 | +16.50 | 16.50 | 0.00 |
| 63 | 1.0 | 1  | 100.0% | +15.50 | 0.00 | +15.50 | 15.50 | 0.00 |
| 63 | 2.0 | 1  | 100.0% | +14.50 | 0.00 | +14.50 | 14.50 | 0.00 |

### Butterfly (buy peak−1, sell 2× peak, buy peak+1; cost = 4 legs)

| hold_days | cost_bp | n_trades | hit_rate | avg_pnl_bp | sharpe | median_pnl_bp | total_pnl_bp | max_dd_bp |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5  | 0.0 | 52 | 61.5% | +0.51 | 0.60 | +0.50 | 26.75 | -11.75 |
| 5  | 2.0 | 52 | 21.2% | -1.49 | -1.73 | -1.50 | -77.25 | -81.50 |
| 5  | 4.0 | 52 | 1.9%  | -3.49 | -4.06 | -3.50 | -181.25 | -180.50 |
| 10 | 0.0 | 47 | 63.8% | +1.32 | 1.10 | +0.50 | 62.00 | -9.50 |
| 10 | 2.0 | 47 | 31.9% | -0.68 | -0.57 | -1.50 | -32.00 | -54.50 |
| 10 | 4.0 | 47 | 12.8% | -2.68 | -2.24 | -3.50 | -126.00 | -124.75 |
| 21 | 0.0 | 36 | 77.8% | +3.60 | 2.16 | +4.25 | 129.75 | -11.00 |
| 21 | 2.0 | 36 | 61.1% | +1.60 | 0.96 | +2.25 | 57.75 | -35.00 |
| **21** | **4.0** | **36** | **50.0%** | **-0.40** | **-0.24** | +0.25 | -14.25 | -63.50 |
| 42 | 0.0 | 18 | 94.4% | +7.40 | 7.94 | +7.63 | 133.25 | 0.00 |
| 42 | 2.0 | 18 | 88.9% | +5.40 | 5.79 | +5.63 | 97.25 | -3.50 |
| 42 | 4.0 | 18 | 83.3% | +3.40 | 3.65 | +3.63 | 61.25 | -8.75 |
| 63 | 0.0 | 1  | 100.0% | +11.39 | 0.00 | +11.39 | 11.39 | 0.00 |
| 63 | 2.0 | 1  | 100.0% | +9.39 | 0.00 | +9.39 | 9.39 | 0.00 |
| 63 | 4.0 | 1  | 100.0% | +7.39 | 0.00 | +7.39 | 7.39 | 0.00 |

**Sharpe caveat — read before trusting the hold=42 row.** The `summary_stats` Sharpe is
`mean/std * sqrt(252/n_trades)`: it assumes the sample spans exactly one year regardless
of actual dates or `hold_days`, and has no correction for trade overlap or
autocorrelation. Treat it as a within-grid ranking signal only, never as an annualized
risk-adjusted return — and treat it as least trustworthy exactly where it looks best
(hold=42's Sharpe of 18.77, hold=63's single-trade "0.00"). §4 explains why.

**Key cells:**
- **Spread, hold=21, cost=2.0bp: +1.86bp net, n=36, hit rate 63.9%.** The best-supported
  result in the grid — largest sample with genuine episode diversity (see §4). This is
  the number to quote if asked "does it work."
- **Butterfly dies at hold=21 on its own 4bp round-trip cost** (-0.40bp, hit rate drops
  to 50%). It survives 2bp (+1.60bp) but not the full cost tested. The hold=42 butterfly
  cell nominally "survives" 4bp (+3.40bp) — do not read that as a stronger result than
  the hold=21 fail. It is the same episode-contaminated n=18 sample described in §4, not
  independent confirmation.
- **Short holds (5d, 10d) are positive gross in both variants but do not survive any
  nonzero cost tested** — negative already at the smallest cost level in the grid (1bp
  spread, 2bp fly). Not viable at any realistic cost.
- **Long holds (42d, 63d) survive every cost tested but are not a cost story** — n=18 and
  n=1 respectively, both drawn from the same one or two overlapping episodes (§4). Sample
  independence, not cost, is what's wrong with these cells.

## 4. Sample structure warning

**Read this before believing §3.** The grid's best-looking cells are not what they look
like.

**The achieved window is 2026-01-02 → 2026-06-17, not the requested → 2026-08-22 — 116
trading days, not ~166.** `_enumerate_contracts` fixes the 8-contract set
(`SR3H26...SR3Z27`) at the start date with no rolling, and `build_daily_strip`
inner-joins all 8 columns, dropping any date where any one is missing. SR3 futures settle
**in arrears**: SR3H26 references the 3-month period *starting* at its March 2026 IMM
date and keeps trading through mid-June 2026 — it is the earliest of the 8 to expire, and
its last-trade date sets the `dropna()` cutoff for the whole strip. This is a structural
consequence of the fixed-8-column, no-roll design (explicitly out of scope for this
round), not a bug — but it is why the sample ends where it does, mid-episode, rather than
after the episode resolved.

**Peak contract distribution, 116 dates:**

| contract | n_dates |
|---|---:|
| SR3H26 | 59 |
| SR3M27 | 24 |
| SR3H27 | 12 |
| SR3M26 | 11 |
| SR3U26 | 8 |
| SR3Z26 | 2 |
| SR3U27 | 0 |
| SR3Z27 | 0 |

Interior peaks (`is_interior=True`, entry-eligible): **57 of 116 (49%)**. The other 59
(51%) sit at the strip's front edge — no trade generated (§7.7).

**Migration events, all 13:**

| date | from | to | peak_rate | prominence |
|---|---|---|---:|---:|
| 2026-03-19 | SR3H26 | SR3M26 | 3.720 | 0.00625 |
| 2026-03-20 | SR3M26 | SR3U26 | 3.790 | 0.02750 |
| 2026-03-26 | SR3U26 | SR3Z26 | 3.850 | 0.01250 |
| 2026-03-30 | SR3Z26 | SR3U26 | 3.690 | 0.01500 |
| 2026-03-31 | SR3U26 | SR3H26 | 3.675 | 0.01000 |
| 2026-04-03 | SR3H26 | SR3U26 | 3.700 | 0.02000 |
| 2026-04-08 | SR3U26 | SR3M26 | 3.680 | 0.00875 |
| 2026-04-17 | SR3M26 | SR3H26 | 3.660 | 0.01000 |
| 2026-04-20 | SR3H26 | SR3M26 | 3.665 | 0.03500 |
| 2026-04-23 | SR3M26 | SR3H26 | 3.665 | 0.00000 |
| 2026-04-28 | SR3H26 | SR3H27 | 3.665 | 0.01500 |
| 2026-05-12 | SR3H27 | SR3M27 | 3.885 | 0.02750 |
| 2026-06-16 | SR3M27 | SR3H27 | 3.940 | 0.02750 |

No migration before 03-19 — the peak sits at the front edge (non-interior, SR3H26) for
the first 52 trading days, so there is nothing to migrate from. The first six events churn
within the front four contracts (H26/M26/U26/Z26); 04-28 then jumps straight from SR3H26
to SR3H27 — four contracts out in one day — after which the peak stays in H27/M27 for the
rest of the sample. (This last stretch is the "H7→M7→U7" migration referenced in §1: the
peak parks in the H27/M27 cluster through the end of this backtest window and, per the
live snapshot in §5, had reached SR3U27 by 2026-08-20 — after this backtest's data ends.)

**Contiguous-run structure — why hold=42/63 are not 18/1 independent trials:**

| run | is_interior | start | end | n_days |
|---|---|---|---|---:|
| 1 | False | 2026-01-02 | 2026-03-18 | 52 |
| 2 | True  | 2026-03-19 | 2026-03-30 | 8 |
| 3 | False | 2026-03-31 | 2026-04-02 | 3 |
| 4 | True  | 2026-04-03 | 2026-04-16 | 10 |
| 5 | False | 2026-04-17 | 2026-04-17 | 1 |
| 6 | True  | 2026-04-20 | 2026-04-22 | 3 |
| 7 | False | 2026-04-23 | 2026-04-27 | 3 |
| 8 | True  | 2026-04-28 | 2026-06-17 | 36 |

Four interior episodes total (runs 2, 4, 6, 8), tracing exact index arithmetic
(`exit_i = i + hold_days`, entries need `exit_i < 116`) against these boundaries:

- **hold=42 (n=18):** every entry comes from the two short interior runs (8+10=18 days) —
  none from the long tail run (its entries are too close to the data's right edge to have
  42 days of runway). But 42 trading days forward from mid-March/early-April lands the
  *exit* in mid-May to mid-June — squarely inside the same run-8 (Apr28→Jun17) flattening
  move. **The 18 "trades" are 18 different entry points into materially the same
  underlying move, not 18 independent realizations.**
- **hold=63 (n=1):** only the single earliest interior date (2026-03-19) has 63 days of
  forward runway before the data ends. **One trade. Not a statistic.**
- **hold=21 (n=36):** draws from all four interior runs, including 15 entries from inside
  run 8 itself — the broadest coverage in the grid, though still overlapping and
  autocorrelated within each run. This is why hold=21 is the cell to trust most.

Run 8 (Apr28→Jun17, 36 days) does not resolve or revert on its own within the sample — it
runs uninterrupted to the *edge of the truncated data*, cut off by the SR3H26 expiry
artifact above, not by the underlying move ending. Combined with the overlapping-entry
effect (any `n_trades` column overstates independent bets by roughly a factor of
`hold_days`), the honest read of §3's headline numbers is: **one directional episode —
a Q2 2026 flattening — was profitable to fade, priced with optimistic same-bar execution.
That is not the same claim as "a repeatable, cross-regime signal."**

## 5. Vol butterfly findings (variant C)

Current peak confirmed live: a fresh 5-day strip pull (2026-08-17 → 08-21) shows the peak
migrating **SR3M27 → SR3U27 on 2026-08-20**, holding through 08-21 — the contract used for
the mode-vs-forward snapshot below.

**`mode_series` on SFRU27:**

| as_of | mode_yield | forward_yield | gap_bp | mode_imp_prob | n_bodies |
|---|---:|---:|---:|---:|---:|
| 2026-08-19 | 4.125 | 4.065 | +6.0 | 0.10 | 21 |
| 2026-08-20 | 4.125 | 4.070 | +5.5 | 0.12 | 21 |
| 2026-08-21 | 4.125 | 4.125 | 0.0  | 0.10 | 21 |

**The mode did not move — the forward moved onto it.** The options-implied mode was
pinned at a single strike (4.125%) across all three sessions while the forward drifted up
from 4.065% to 4.125%. The gap compressed +6.0 → +5.5 → 0.0bp purely because the forward
converged onto a stationary mode, not because the mode faded down to meet a stationary
forward. That is the opposite of the "peak premium decays" framing in §1 — this 3-day
window shows convergence, not a completed fade, and shows no post-convergence overshoot
(gap lands at exactly 0, not negative). A real read on whether this variant has edge needs
the deferred rolling-contract backtest, across enough convergence episodes to see whether
the forward tends to overshoot past the mode or stop at it.

**SFRU26 validation (liquid, front contract, 2026-08-21):** mode 3.75% vs. forward 3.80%,
gap **-5.0bp** — independently corroborated by a pre-existing gated memory note
(`reference_sofr_butterfly_grid.md`) from unrelated prior work.

**Data-density caveat:** SFRU27 (~13mo to expiry) is measurably sparser than SFRU26
(~3wk to expiry) — 21 usable bodies vs. 36, `sum(imp_prob)` 0.82-0.84 vs. 2.00. Fewer
strikes carry real (non-floor-tick) prices this far out.

**Bimodality caveat, 2026-08-19:** `imp_prob` was exactly tied (0.10 each) between the
strike that became the mode (yield 4.125%) and a second strike (yield 3.875%) — a
genuinely bimodal-looking snapshot that `idxmax` silently collapsed to whichever row
comes first in body-ascending order. This is simultaneously supporting evidence for the
§1 bimodal-expectations thesis (the market really did see two humps that day) and a
concrete instance of the mode-fragility problem in §6/§7.6 — the "mode" is a coin flip on
some dates, not a stable read.

## 6. Implied distribution findings (variant D)

Breeden-Litzenberger continuous-density mode vs. the same discrete butterfly-grid mode
from §5, same dates, same contracts, same sign convention (`gap_bp > 0` ⇒ mode above
forward).

**SFRU26 — the two methods agree closely:**

| as_of | grid mode (§5) | BL mode | forward | grid gap_bp | BL gap_bp | divergence |
|---|---:|---:|---:|---:|---:|---:|
| 2026-08-21 | 3.7500 | 3.7642 | 3.80 | -5.0 | -3.58 | **1.4bp** |

One grid step (6.25bp) apart on the raw strike; 1.4bp apart on the yield mode itself. The
BL density at exactly 3.75% is 98.7% of its value at the true argmax — a sharp,
well-defined peak, not a close call between candidates. `forward_residual_bp` (fitted
mean minus true forward, should be ~0) is -1.5bp: a well-calibrated fit on this liquid,
near-dated (~3wk), 48-strike contract.

**SFRU27 — the two methods do NOT agree, and disagree by more than the signal itself:**

| as_of | grid mode (§5, pinned) | BL mode | forward | grid gap_bp | BL gap_bp | divergence |
|---|---:|---:|---:|---:|---:|---:|
| 2026-08-19 | 4.125 | 3.9923 | 4.0650 | +6.0 | -7.27 | **13.3bp** |
| 2026-08-20 | 4.125 | 4.0583 | 4.0700 | +5.5 | -1.17 | **6.7bp** |
| 2026-08-21 | 4.125 | 4.0143 | 4.1250 | 0.0  | -11.07 | **11.1bp** |

Divergence ranges **6.7-13.3bp across the three dates** — comparable to, and on the worst
date (08-19) larger than, the gap_bp values either method is trying to measure. The two
methods disagree on sign twice (grid says mode above forward on 08-19/08-20; BL says mode
below forward on all three dates).

This is a real, checked finding, not a bug in either implementation:

1. **Both methods already flagged this contract as thin.** 30 strikes for SFRU27 vs. 48
   for SFRU26; `sum(imp_prob)` 0.82-0.84 vs 2.00.
2. **The BL density itself is a broad, nearly-flat plateau on SFRU27, not a sharp peak.**
   The density at the grid-pinned mode (4.125%) is 96-98% of the density at the BL
   argmax, on every date. SFRU26 shows a similarly flat *ratio*, but SFRU27's `std_rate`
   is 74-87bp vs. SFRU26's 26-28bp — an order of magnitude wider distribution, so a
   comparably flat ratio spans a much wider absolute rate range. With ~13 months to
   expiry and only 30 strikes, discretization (6.25bp grid steps vs. a continuous spline)
   is enough to move the argmax by several bp for free.
3. **Independent corroborating diagnostic:** `forward_residual_bp` is -12 to -18bp for
   SFRU27 vs. -1.5bp for SFRU26 — the BL fit itself is on shakier ground for the far
   contract, by a diagnostic unrelated to the mode computation.

**Reading:** trust the mode-vs-forward gap on SFRU26 (liquid, front, ~1.4bp of daylight
between methods). Treat the same number on SFRU27 — which is where the strip's peak
actually sits, per §5 — as a rough, wide-error-bar read, not a precise value. **Mode
identification is fragile exactly on the contract the signal needs it to be precise on.**
A signal built on "gap_bp on the current peak contract" needs either a liquidity floor
(restrict to near-dated / high-`sum(imp_prob)` contracts) or an explicit uncertainty band,
not a bare point estimate, this far out on the curve.

## 7. What kills it

1. **Sample size.** 116 trading days, one regime (a Q2 2026 cutting-cycle flattening),
   effectively 4 interior episodes (§4). Need a rolling-contract strip spanning multiple
   hump/flatten episodes — e.g. the 2023-2024 easing cycle plus the current regime —
   before this is a multi-cycle result rather than one anecdote.

2. **Cost.** Butterfly dies on cost at the one horizon with real episode diversity
   (hold=21: +3.60bp gross → -0.40bp at 4bp round-trip). Spread is marginal (hold=21:
   +3.86bp gross → +1.86bp at 2bp). Short holds (5d/10d) die at the smallest cost tested
   in both variants. This matches the repo's broader pattern: prior SFR relative-value
   sweeps here — the SR3 RV lab (47 configs, zero alive) and the linvol backtest grid
   (272 configs, nothing alive) alone total 380+ configurations — uniformly died on cost.
   A new signal surviving cost on a 36-trade, single-regime sample is not yet evidence it
   breaks that pattern.

3. **Overlapping entries.** Long-hold results are autocorrelated, not independent: the
   hold=42 grid (n=18) is 18 different entry points into one underlying move (§4); hold=63
   is a single trade. hold=21 (n=36) is the least-bad case but still draws 15 of its 36
   entries from inside one 36-day run. `n_trades` overstates independent bets by roughly a
   factor of `hold_days` in every column, and `summary_stats`' Sharpe formula
   (`mean/std * sqrt(252/n_trades)`) has no correction for this — it is a within-grid
   ranking signal only, least trustworthy exactly where the grid looks best.

4. **Same-bar entry.** The peak is identified from date *t*'s close and entered at that
   same close — the linear backtests' inherited optimistic-execution bound. This biases
   every cell in §3 toward looking better than realistic (t+1) execution would. It can
   only make a real "no gross edge" result look like a false pass, never the reverse — so
   it doesn't undermine a real gross-of-cost fail, but it does mean every gross-of-cost
   pass in §3 is an upper bound, not a realistic estimate.

5. **Direction contamination — not yet tested.** Does fading the peak just mean being
   long rates through the same Q2 2026 flattening that §4 already identified as the whole
   sample? Needed: regress trade-level P&L on the concurrent change in a front-contract
   (or near-money) rate over the same hold window. Until that regression is run, the
   linear results in §3 cannot be distinguished from a directional bet that happened to
   be profitable once.

6. **Mode fragility.** BL and the discrete butterfly grid disagree 6.7-13.3bp on SFRU27
   (§6) — the contract the strip's peak is *currently* sitting on (§5) — while agreeing
   within 1.4bp on the liquid front contract. The peak you'd be fading with variants C/D
   may not be where either measurement says it is, precisely where it matters most.

7. **Peak at the edge.** 59 of 116 dates (51%) had the peak at the strip's endpoint
   (`is_interior=False`) — `require_interior=True` means no trade is generated on any of
   those dates. The signal, as built, is live only about half the time.

## 8. What's next

| Item | Addresses |
|---|---|
| Rolling-contract strip builder | §7.1, §7.3 — required for a multi-cycle sample; also lets variants C/D run real historical backtests instead of 3-5 date snapshots |
| Direction contamination test (regress P&L on front-contract rate change) | §7.5 — the single biggest open question before trusting §3 at all |
| Prominence-conditioned entries (only trade when the peak is pronounced) | §7.7, partially §7.6 — raises average signal quality and skips the flattest, most mode-fragile snapshots |
| Intraday / t+1 execution lag (replace same-bar entry) | §7.4 — turns the optimistic upper bound in §3 into a realistic estimate |

---

**Reproduce:** `scripts/_build_strip_peak.py` (grid runner) →
`analysis_outputs/strip_peak/linear_grid.csv` (§3 source data) — both under
`C:\Users\chris\clee\ARBS-spf`. Core modules: `RVUtils/StripPeak/{strip_builder,
peak_tracker, linear_backtest, vol_backtest, distribution_backtest}.py`. Full
task-by-task detail: `.superpowers/sdd/2026-08-24-strip-peak-fade/task-{1..6}-report.md`
and `progress.md` in the primary `ARBS` checkout.
