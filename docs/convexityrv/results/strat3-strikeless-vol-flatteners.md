All deliverables are built, executed and verified. Final report:

---

# STRATEGY 3 — delta-hedged long-dated forward flatteners ("strikeless vol")

## FILES WRITTEN (all absolute)

| file | what |
|---|---|
| `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat3_strikeless_vol.py` | `Strat3Config`, the 15-pair universe, Fig-9 cost tiers, the Fig-7 screen (both breakevens), `simulate_strat3` (beta + resize_mode), roll segmentation/stitching, `book_stats`, `entry_state`, `grid_cells`/`run_grid`, `hedge_schedule` (the QDB trade tape) |
| `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/__init__.py` | re-exports strat3 (31 names) |
| `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_strat3.py` | **57 tests, all pass** (36.7s) |
| `C:/Users/chris/clee/ARBS-cvx/scripts/strat3_build_panels.py` | panel builder (multiprocess); screen 323s, ledgers 1093s |
| `.../notebooks/backtests/convexity_rv/strat3_strikeless_vol_backtest.py` + `.ipynb` | **executed, `_verify_nb` OK: 15 cells, 34 outputs, 0 unrun, 0 errors** |
| `.../notebooks/backtests/convexity_rv/strat3_strikeless_vol_gridsearch.py` + `.ipynb` | **executed, `_verify_nb` OK: 19 cells, 47 outputs, 0 unrun, 0 errors** |
| `.../notebooks/data/convexity_rv/strat3_leg_panel.parquet` | 30,573 rows, 9 legs × 3,397 days (2013-01-02 … 2026-08-07) |
| `.../notebooks/data/convexity_rv/strat3_screen.parquet` | 50,955 rows = 15 pairs × 3,397 days |
| `.../notebooks/data/convexity_rv/strat3_ledgers.parquet` | 1,366,560 rows = 15 pairs × 48 hedging variants × 1,898 days |
| `.../notebooks/data/convexity_rv/strat3_grid_results.csv` | 15,120 scored cells (5,040 × 3 cost multipliers) |

**All 15 pairs priced. None skipped.** Reuses `RVUtils/StrikelessVol` (`CurvePricer`, `build_package`, `CostSchedule`) unchanged — `simulate_strat3` is a `PricingContext` client, asserted bit-identical to `replication.simulate` at `beta=1.0, resize_mode="neutral"`.

## TIE-OUTS — measured deltas, not "passed"

**(a) Citi Figure 7, close of 2019-05-08** (external known answer, 8 published pairs):

| metric | max abs Δ | detail |
|---|---|---|
| curve level | **1.305 bp** (spec allowed ~1.5) | all 8 uniformly ~0.8bp more negative than Citi |
| 1y carry | **0.484 bp** (allowed ~1.0) | corr **+0.991**, Spearman **0.976** |
| 1y realized vol | **0.228 bp** | 3.20–3.26 vs published 3.0–3.2 |
| daily breakeven | **1.076 bp** | driven entirely by 15y5y/20y10y (ours −0.009bp carry vs Citi −0.31 → sqrt amplifies) |

**The brief named the wrong carry field, and Fig 7 proves it.** `IRSwapValue.CARRY_AND_ROLL_BPS_RUNNING` @1Y: corr **−0.136**, MAE 1.28bp. Repriced 1-year `rl.Curve.roll` of the aged package / package DV01: corr **+0.991**, MAE 0.354bp, and the rank order is right where the query field's is wrong. The repriced roll is primary; the query value is still reported as `carry_query_bp`.

**(b) DV01 neutrality at initiation:** package PV01 = **0.0** (max |1.5e-11|) on every pair.

**(c) Convexity:** gamma > 0 on **all 50,955 pair-days** (min $101.4/bp²). Repriced gamma vs the spec's `Γ = ΔM/10⁴` reconstruction: **0.947 – 1.058** over 13 years (0.975–1.018 on 2019-05-08) — an independent confirmation of a reconstruction Citi never published. The committed `payoff_profile` regression table reproduces **exactly** (`20Yx5Y/25Yx5Y`, `30Y/50Y`, `10Yx10Y/20Yx10Y`, all 13 shifts, atol 0.05).

**BE analytic vs BE repriced: 0.991 – 1.013** on 2019-05-08, **0.972 – 1.027** across all 13 years.

**(d) Sign probe:** re-run live in both notebooks. +bpv = +$2,303,346 / −bpv = −$2,303,346, exact mirror; `bpv<0` CURVE confirmed convex.

**(e) Resize mechanics, real 2020 curves:** a −115bp rally left the un-resized package at **−$22,486/bp** (22% of gross DV01), sign negative as a growing received leg requires; the 25bp trigger removed it to −$0. Over full-year 2020 (20y10y: 180→31→136bp), 15Yx5Y/20Yx10Y hedged **+$863,939** vs never-hedged **+$92,503**, harvest **+$760,328**.

**A blocked path, recorded:** the brief asks for the exact breakeven from `curve_ops.payoff_profile` at a 1-day horizon. That function ages with `rl.Curve.translate`, which returns **exactly zero** carry for a par-struck forward package (measured: +1d translate −0.00 vs roll −350.68; +1y translate +0.00 vs roll −129,434.37). The exact BE is therefore built from `rl.Curve.roll` + a second-difference reprice, and it agrees with the analytic formula to 1–3%. Pinned by a test.

## BACKTEST — 15Yx5Y/20Yx10Y @25bp, $100k DV01, annual roll, always-on, net Citi Fig-9 costs, 2019-01-02 … 2026-08-07 (1,898 days)

Run through `QueryDrivenBacktest` in **202s**; 1,898/1,898 marks, 65 closed positions, terminal MTM **+$6,340,995**. Ledger engine: **+$6,018,558**; **daily-change correlation 0.9997**, terminal gap +5.36% (the two are deliberately different trades — off-market notional resize vs at-market increment swaps on the aged leg's dates, Citi's own stated practical convention).

| | |
|---|---|
| total net | **+$6,018,558** = **60.19 bp** of DV01 |
| ├ carry (theta) | −$102,842 |
| ├ gamma harvest | **+$1,171,836** |
| ├ curve mtm (direction) | **+$5,290,502** |
| └ costs | −$340,938 |
| **net ex-direction** (carry+harvest−costs) | **+$728,055 = +7.28 bp** |
| annualised Sharpe | **0.404** (Citi Fig-4 for this pair, 2013-19: 0.18) |
| Sharpe ex-direction | **0.108** |
| hit rate / skew | 52.0% / −0.385 |
| max drawdown | −$3,527,731 |
| hedges / rolls | 49 / 7 |
| never-hedged counterfactual | +$4,989,551, Sharpe 0.305 → **the hedge added +$1,029,007** |

By year (net): 2019 +560k, 2020 +777k, 2021 +1,580k, 2022 +4,289k, 2023 −657k, 2024 +1,013k, **2025 −1,537k**, 2026 −6k. 2025 is the trend year where harvest went **negative** (−$357k) — long gamma pays for round trips, not trends, and that is pinned by a test rather than hidden.

## GRID SEARCH — 5,040 cells × 3 cost multipliers, scored in 68s

Axes: 15 pairs × {10,15,20,25,30,40}bp × {neutral, always_decrease} × beta{1.0, 1.025} × roll{12,24}m × 7 entry rules.

### Like-for-like vs Citi Figure 4 (25bp, always-on, DV01-neutral, annual roll)

| pair | our Sharpe | Sharpe ex-direction | carry_bp | harvest_bp | mtm_bp | net_ex_mtm_bp | Citi Fig-4 |
|---|---|---|---|---|---|---|---|
| 15Yx10Y/25Yx10Y | 0.578 | 0.005 | −6.18 | 11.32 | 78.21 | +0.49 | — |
| 15Yx5Y/25Yx10Y | 0.546 | 0.024 | −6.24 | 13.75 | 95.23 | +2.66 | — |
| 20Yx5Y/25Yx10Y | 0.536 | −0.027 | −6.26 | 8.79 | 60.17 | −1.89 | 0.30 |
| 15Yx5Y/20Yx15Y | 0.505 | 0.053 | −3.63 | 13.11 | 73.05 | +4.75 | 0.25 |
| 15Yx10Y/25Yx5Y | 0.470 | 0.052 | −2.59 | 10.81 | 55.66 | +3.72 | — |
| 20Yx5Y/25Yx5Y | 0.464 | 0.007 | −2.66 | 7.22 | 37.62 | +0.31 | — |
| 15Yx5Y/25Yx5Y | 0.447 | 0.073 | −2.66 | 14.15 | 72.69 | +6.76 | — |
| 15Yx5Y/20Yx10Y | 0.404 | **0.108** | −1.03 | 11.72 | 52.91 | **+7.28** | 0.18 |
| 10Yx10Y/25Yx10Y | 0.404 | −0.159 | −32.12 | 15.86 | 90.26 | −21.34 | 0.35 |
| 10Yx10Y/20Yx15Y | 0.347 | −0.162 | −29.45 | 16.49 | 68.07 | −18.00 | 0.24 |
| 10Yx10Y/25Yx5Y | 0.297 | −0.135 | −28.54 | 17.94 | 67.71 | −15.60 | — |
| **15Yx5Y/20Yx5Y** | 0.290 | 0.061 | **+0.16** | 6.95 | 35.06 | **+2.79** | — |
| 10Yx10Y/20Yx10Y | 0.234 | −0.157 | −26.86 | 16.16 | 47.93 | −14.34 | 0.16 |
| 10Yx10Y/15Yx15Y | 0.112 | −0.257 | −26.63 | 12.74 | 28.91 | −17.35 | 0.13 |
| 10Yx10Y/20Yx5Y | 0.087 | −0.278 | −25.64 | 10.81 | 30.08 | −19.45 | — |

Ours mean **+0.363** (range 0.087–0.578) vs Citi mean +0.230 (range 0.13–0.35) on the 7 overlapping pairs; **cross-sectional Spearman +0.714** across two disjoint samples (theirs 12/2013–5/2019, ours 1/2019–8/2026).

### The finding that matters most — direction dominates

**The mean `mtm` share of net across the 15 pairs is 1.29**, and it is ≥0.88 for every single pair. Over the sample the ultra-long forward curve inverted by ~40bp (10y10y/20y10y level −14bp → −56bp), so a DV01-neutral flattener was long the biggest move in the window. `net_ex_mtm_bp` (= carry + harvest − costs) removes it: **only 8 of 15 pairs are profitable ex-direction**, and the entire `10Yx10Y/*` family is deeply negative — its gamma harvest covers only **0.48–0.63×** its carry bill. The `15Yx5Y/*` family covers it 2.2–43.7×.

### The flag the brief demanded

**Sharpe-optimal cell = `10Yx10Y/25Yx10Y` @40bp, neutral, beta 1.025, roll 12m, BE/rv-gated: Sharpe 0.765, net $10,386,864.** It is **FLAGGED, not crowned**: mean ex-ante 1y carry **−4.17 bp/yr**, positive-carry on **2.0%** of days, and its `sharpe_ex_mtm` at the always-on 25bp base is **−0.159**. It is long gamma (every cell is) but it pays heavily to be. The notebook prints this flag automatically.

**Deflated Sharpe on that winner: p(true SR>0) = 0.011.** Expected max Sharpe under the null across 5,040 tries = **1.599** annualised vs 0.765 found — the winner does **not** clear the multiple-testing bar. Median cell Sharpe −0.012; 49.1% of cells positive.

### The structure the objective actually asks for — long vol AND paid theta

**Only 336 of 5,040 cells (6.7%) have non-negative mean ex-ante carry, and every one of them is `15Yx5Y/20Yx5Y`** — the sole pair in the Citi 15-grid with positive mean carry over 2019-2026 (**+0.087 bp/yr**, positive-carry on **46.2%** of days). Only **24 cells** clear carry ≥ 0 *and* profit ex-direction. Best of them:

> **`15Yx5Y/20Yx5Y`, 15bp threshold, DV01-neutral, beta 1.0, annual roll, always-on** — Sharpe **0.335**, **Sharpe ex-direction 0.186**, net **+$4,362,913**, net ex-direction **+8.57 bp**, realised carry **+0.15 bp**, harvest **+13.28 bp**, 148 hedges. Its `always_decrease` twin at 10–15bp does nearly as well on **24–34 hedges** instead of 148.

Runner-up families on ex-direction Sharpe with near-zero carry: `15Yx5Y/20Yx10Y` (the PM's "pure vega expression", ex-direction Sharpe 0.108, carry −0.064 bp/yr, 40.5% positive-carry days) and `15Yx5Y/25Yx5Y` (0.073, −0.263 bp/yr).

### Stability, not a single cell — and Citi's own threshold claim, tested

Sharpe by pair × threshold (always-on, neutral, beta 1, annual roll):

|  | 10bp | 15bp | 20bp | 25bp | 30bp | 40bp |
|---|---|---|---|---|---|---|
| 15Yx10Y/25Yx10Y | 0.611 | 0.623 | 0.597 | 0.578 | 0.627 | 0.633 |
| 15Yx5Y/25Yx10Y | 0.579 | 0.590 | 0.564 | 0.546 | 0.595 | 0.602 |
| 15Yx5Y/20Yx10Y | 0.430 | 0.440 | 0.411 | 0.404 | 0.434 | 0.395 |
| 15Yx5Y/20Yx5Y | 0.315 | 0.335 | 0.304 | 0.290 | 0.300 | 0.294 |
| 10Yx10Y/20Yx10Y | 0.262 | 0.278 | 0.236 | 0.234 | 0.273 | 0.220 |
| 10Yx10Y/15Yx15Y | 0.144 | 0.144 | 0.128 | 0.112 | 0.129 | 0.109 |

**Citi's prediction is half-confirmed.** "The Sharpe doesn't change significantly in 15-30bp" — confirmed: median spread inside the band is **0.044** on a ~0.4 mean. "…but declines with a smaller or larger threshold" — **not confirmed**: mean Sharpe inside 15-30bp is **0.404** vs **0.408** at 10 & 40bp, and the claim holds on only **9/15** pairs. On our sample 10-15bp are usually the *best* and 25bp is often a local minimum.

### Other knobs (mean over the grid, 1× costs)

| knob | result |
|---|---|
| `resize_mode` | noise: always_decrease −0.047 vs neutral −0.055 mean Sharpe (but always_decrease uses ~1/5 the hedges) |
| `beta` | noise: 1.0 → −0.043, 1.025 → −0.060 |
| `roll_months` | 12m better on net ($995k vs $535k mean); 24m better ex-direction |
| `entry_rule` | **always-on 0.378 ≫ be_ratio 0.181 ≫ z_and_be −0.252 ≈ carry −0.259 ≈ z −0.293.** The screen gates as implemented destroy value: occupancy 13–24% and an initiation charged on every flip |
| `cost_multiplier` | **first-order**: mean Sharpe 0.620 (0×) → −0.051 (1×) → −0.585 (2×) |

## THINGS THAT DID NOT WORK / CAVEATS, stated plainly

1. **`CARRY_AND_ROLL_BPS_RUNNING` is not Citi's carry field** (corr −0.136). Replaced by repriced roll; both reported.
2. **`payoff_profile(horizon_date=…)` cannot produce the exact breakeven** — `translate` gives exactly zero carry on par-struck forwards. Used `roll` instead; documented and tested.
3. **Two bugs found and fixed during the build**, both caught by comparing implementations: `book_stats` double-billed the initiation on an always-on book; the notebook's QDB fee charged initiate/roll per leg rather than per package (Citi Fig-9 quotes the package).
4. **Gated cells scale an always-on aged ledger** by a lag-1 {0,1} state rather than striking a fresh package at entry (the `sv_citivelo_h13` approximation). Their Sharpes are an upper bound; the always-on rows carry no such caveat.
5. **Unpublished pairs default to the wide cost tier (1.0/0.40)** — an assumption, recorded, not a measurement.
6. `zs_full` is "since 2013", not Citi's "since 2000" — the leg panel starts 2013-01-02.
7. Mutation test: flipping the resize-target sign in `simulate_strat3` fails **4** tests (`engine_matches_strikeless_vol_simulate`, `book_stats_sharpe_and_carry_split`, `engine_residual_delta_sign_across_the_2020_rally`, `delta_hedging_harvests_a_real_round_trip`) — the suite bites. Restored and re-verified: 57 passed.