# SFR Butterfly Mean-Reversion Lab — Design

**Date:** 2026-07-29
**Status:** In progress
**Branch:** `feat/sfr-fly-meanrev`
**Predecessors (ground truth, not background reading):**
`docs/superpowers/specs/2026-07-29-sfr-rv-lab-findings.md` (honesty rules, verdict
taxonomy, bug log), `docs/superpowers/specs/2026-07-29-sfr-rv-lab-design.md` (engine
design), `notebooks/backtests/SFR_screeners/kink_fade_backtest.py` +
`FINDINGS_kink_fade.md` (prior verdicts on fading the kink),
`docs/superpowers/specs/2026-06-24-rv-toolkit-v2-bsic-additions.md` (v2 toolkit, merged).

## Problem

Stress-test **mean reversion on SR3 (3M SOFR futures) butterflies** across every 3m and
6m fly formable from the front 16 quarterly contracts, over the longest daily history the
feed supports, and produce two deliverables a desk can act on:

1. an honest league table of mean-reversion formulations, and
2. **rules of thumb per constant-maturity fly slot** — where a fly usually trades, how far
   it has to go before fading it has paid net of costs, and how that changes by regime.

## What is already known (do not re-derive)

* **The naive fly-level fade is the real effect, and options add nothing to it.**
  `FINDINGS_kink_fade.md` (250 dates, 2025-05→2026-05, 44 flies): within-gap
  cross-sectional IC of fly level vs Δfly is −0.27 (t = −8.3) at h=21, and the naive
  long/short fade prints IR ≈ +1.35 with non-overlapping Sharpe ≈ +1.97. The
  options-implied variance signal fails Fama-MacBeth against the level control at every
  horizon (|t| ≤ 0.2) and dies at 0.75bp/side.
* That result is **one regime, one year, one panel, gross of any realistic cost model**
  (the `QueryDrivenBacktest` path charges `fee=0.0`). It is the hypothesis this lab tests,
  not a finding this lab can assume.
* h=63 numbers in the prior work are overlap artifacts (naive IR +15.44 on ~4 independent
  windows). Discount anything at that horizon that is not reported non-overlapping.

## Sign conventions (one place, checked against the code AND reconciled on real trades)

The desk writes a butterfly `1/-2/1` with **negative = paid** (makes money when that leg's
rate rises). The engine stores rate-exposure weights with **positive = paid**. Same trade,
opposite notation:

| desk notation | internal `w` | futures action | position | profits when |
|---|---:|---|---|---|
| front `+1` | `−1` | **BUY** 1 front | received | front rate falls |
| belly `−2` | `+2` | **SELL** 2 belly | **paid** | belly rate rises |
| back `+1` | `−1` | **BUY** 1 back | received | back rate falls |

`LONG` the spread in the engine (`d = +1`) means **paid the belly against the wings**, and
profits when the belly *cheapens* relative to them. Reconciled against raw settles on a real
holding period (`U26-Z26-H27`, 2026-06-02 → 2026-07-29: belly rate +30.5bp vs front +24.0 and
back +30.0, spread +2.0bp → +9.0bp): P&L from the spread arithmetic and P&L computed
leg-by-leg from settle changes both give **+$175.00 per package**, agreeing to 1e-10
(`notebooks/rv/_audit_sign_conventions.py`).



| Object | Definition | Units |
|---|---|---|
| contract rate | `100 − settle` | percent |
| calendar spread | `back − front` | bp (positive = steepening) |
| **fly** | **`2·belly − front − back`** | **bp** |

The fly convention matches the Query layer's `FLY RATE`
(`Query/IRSwaps/IRSwapValue.py:49-68` forces `[−1, +2, −1]` on the leg rates and scales by
1e4) and `RVUtils/FlyVsVol/_types.py::FLY_WEIGHTS`. It is verified numerically against a
live `FLY RATE` fetch in the panel builder's audit cell.

`BT/signals/sfr_cal_spread_rv.py::compute_fly_curve` uses the **opposite** sign
(`+1/−2/+1`, "wings positive"). Nothing in this lab imports it.

## Marks: raw settles, not a fitted curve

The tradeable object is a package of SR3 futures, so the P&L mark is the **futures
settlement price**. Measured reason, not preference: on 2026-07-27 the
`USD-SOFR-1D-Q16STIRT` curve returned bit-identical rates (`4.038996478235703`) for strip
slots 8–14, i.e. flat interpolation, where every fly is identically zero. Backtesting a
fitted curve lets the strategy trade its own interpolation error. This is the same rule as
the SR3 RV lab's "listed marks only".

The curve is kept as a **cross-check panel** (`curve_strip.parquet`) so the fitted-curve
residual framework has something to fit, and so the settle-vs-curve gap is measurable.

Field scales verified before use (rule 9 from the prior lab, which cost a session):
`fixed_rate` off the Q16 curve is **percent** (3.766 on 2026-07-27), not decimal — the
existing `notebooks/backtests/SFR_screeners/_curve_panel.py:93` multiplies it as if it were
decimal and so reports `bf_bps` 100× too large. This lab does not use that file.

## Data

`notebooks/rv/build_sfr_fly_panel.py` — one Barchart EOD history request per contract
symbol (`SR3<MonYY>` → Barchart `SQ<MonYY>`), so the whole sample is ~56 requests rather
than 56 × 2,000. Checkpointed to `parts/<SYM>.parquet` and skipped on re-run.

* **Coverage.** SR3 EOD history starts **2018-05-04** (contract launch). Each contract is
  listed ~5 years ahead of expiry, so a 16-deep strip is formable from the start. The
  *usable* sample is set by liquidity, not by the feed: per-slot volume and open interest
  are carried through the panel and the effective start is chosen from them and stated.
* **Columns.** `as_of, code, settle, rate_pct, volume, open_interest, imm_start, imm_end`.
* **Absolute contracts only.** Series are keyed on the contract code (`U26`), never on a
  constant-maturity slot, so no roll ever enters a series. Constant-maturity slots are
  attached as a **reporting tag** per (date, fly).

### Strip, birth and death

On each date the strip is the quarterly contracts ordered by `imm_start`, restricted to
those whose reference quarter has **not yet started** (`imm_start > as_of`). Slot 1 is
therefore the front SR3 contract that is not yet accruing — which is what a desk means by
"SFR1", and what the Q16 curve's `IMM_1xIMM_2` resolves to (verified: on 2026-07-27,
`IMM_1xIMM_2` has `effective = 2026-09-16` = U26).

* **Birth** of an absolute fly = the first date all three legs have a settle and are inside
  the first 16 slots.
* **Death** = the date its **front leg** leaves slot 1, i.e. that leg's reference quarter
  starts accruing. No contract is ever marked while partially fixed, so there is no
  accrual-decay contamination and no explicit expiry blackout is needed. A configurable
  `min_days_to_front_start` gate (default 0, swept) tests whether the last days of a fly's
  life are tradeable.

### Fly enumeration

Belly-named, on the strip slots `(i, i+k, i+2k)` as of each date:

* **3m flies** — `k = 1`, slots `(i, i+1, i+2)` for `i = 1..14` → **14 flies/day**.
  The `(U26, Z26, H27)` fly is the "Z26 3m fly" and gets CM slot `SFR123` when its belly
  sits in slot 2.
* **6m flies** — `k = 2`, slots `(i, i+2, i+4)` for `i = 1..12` → **12 flies/day**.
  Wings equidistant from the belly: `(Z26, M27, Z27)` is the "M27 6m fly".

The brief's alternative first 6m fly `(U26, H27, M27)` is **asymmetric** (2 quarters on the
front wing, 1 on the back) and is not a butterfly in the `2·belly − front − back` sense —
its DV01-neutral weights are not `1/−2/1`. The symmetric definition is used, matches the
Query layer's own fly grammar (each leg is an independent `IMM_axIMM_b` token, so any
spacing is expressible but only equal spacing gives the 1/−2/1 package), and matches
`compute_fly_curve(gap=2)`, which is the repo's BF_6M. The asymmetric variant is run as an
**ablation** in the enumeration notebook so the choice is a measurement, not an assertion.

### Constant-maturity tags (reporting only)

Each (date, fly) carries `cm_slot` = the belly's strip index and `cm_label`:

* 3m: `SFR123`, `SFR234`, … `SFR141516` — repo-consistent long form `SFR1/SFR2/SFR3`
  (`BT/signals/sfr_cal_spread_rv.py::cm_label`) is also emitted.
* 6m: `SFR135`, `SFR246`, … — long form `SFR1/SFR3/SFR5`.
* Pack colour of the belly (`whites` 1–4, `reds` 5–8, `greens` 9–12, `blues` 13–16),
  matching `RVUtils/ImpliedDistribution/_strip_utils.py::STRIP_PRESETS`.

Backtests run on absolute flies. Summaries and the rules of thumb are stated per CM slot.

## Package sizing and P&L

A `2·belly − front − back` fly is `1` front + `2` belly + `1` back = **4 contracts**, and
delivers exactly **$25 per bp of fly move per package** (each SR3 contract is $25/bp and
the belly carries 2). P&L in bp is `direction × Δfly`; dollars are
`bp × 25 × n_packages`. The league table states `n_packages = 100` → **$2,500 per bp**, and
prints the contract count (400) in every header.

Note the Query layer's *swap* fly is DV01-weighted (`−20078 / +40543 / −20470` notional on
2026-07-27, i.e. 1 : 2.019 : 1.019) because act/360 quarters differ in length. The
**futures** package is exactly 1/2/1 in contracts, which is what a desk trades and what
this lab uses. The difference is ≤ 2% of one wing and is reported, not swept under.

## Costs

Per the prior lab: **0.25bp one-way per futures leg**, so a 3-leg fly round trip is
`3 × 2 × 0.25 = 1.5bp` on the package. Headline scenarios are the existing
`COST_SCENARIOS = {maker: 0.0, tight: 1.5, taker: 2.5}`. Every table shows gross and net at
all three.

Back contracts are materially less liquid. The panel carries per-leg volume and OI; the
league table is reported both for the full strip and for a **liquidity-gated** universe
(all three legs above an OI floor), and per-slot results are never pooled without the
per-slot breakdown alongside.

## Honesty rules (inherited verbatim, each one earned)

1. **Lag-1 execution.** Signal at close `t` fills at `t+1`. Lag-0 is an ablation only.
   A *deterministic* exit date (fixed horizon, max hold, end of sample) is known at entry
   and is **not** lagged a second time.
2. **Costs charged once per completed trade**, on the exit bar, in the daily series too.
3. **Grid discipline.** Every sweep reports the distribution (median config, % net
   positive), the deflated Sharpe of the selected config with `n_trials` = configs actually
   run and the cross-trial Sharpe variance taken from the sweep, and one-parameter-at-a-time
   neighbourhood stability. The top row is never the verdict.
4. **Sign-test both directions.** Mean reversion *and* momentum, every method.
5. **Verdict taxonomy** — `RVUtils/SFRRVLab/stats.py::verdict`: ALIVE / SELECTION-ARTIFACT /
   MARGINAL-maker-only / DEAD (+ `DEAD (too few trades)` under 10).
6. **Beat your own linear shadow.** Every fly strategy is re-run with the identical signal
   on (a) the outright belly and (b) each of the two constituent calendar spreads. If the
   fly does not beat its shadows, the "fly mean reversion" is a directional or curve trade.
7. **Full panel, then regime split.** Nothing is believed on a maturity subset. Regimes:
   `ZIRP` (→2022-03-16), `HIKING` (2022-03-17→2023-07-26), `PLATEAU`
   (2023-07-27→2024-09-17), `CUTTING` (2024-09-18→) — cut on FOMC decision dates, stated in
   the notebook.
8. **Overlapping trades share moves.** Report non-overlapping Sharpe and Newey-West t on
   daily P&L alongside the naive per-trade t.
9. **Verify field scales before trusting them.** Units are printed in the panel audit cell.
10. **No look-ahead.** Forward-fill only, never `bfill`. Rolling statistics that feed a
    signal traded on bar `t` are computed on a window ending at `t`; an `exclude_current`
    ablation quantifies the self-inclusion.
11. **Half-life honesty.** AR(1)/OU half-lives are fitted per fly and holding periods are
    set from them where possible. A sub-1-day measured half-life is fit noise, not a
    signal.

## Method catalog

Each family gets one executed notebook, a grid, a sign test, a regime split, a linear-shadow
decomposition, and league rows for `best-config` **and** `median-config`.

| # | Notebook | Formulation |
|---|---|---|
| 1 | `sfr_fly_meanrev_zscore` | rolling z-score fade: lookback × MA × entry z × exit rule; Bollinger band-crossing; threshold vs continuous sizing |
| 2 | `sfr_fly_meanrev_ou` | OU: OLS-AR(1) and exact MLE fits, half-life, `ou_sscore`, Zeng-Lee and Bertram cost-aware optimal bands, holding periods set from the fitted half-life |
| 3 | `sfr_fly_meanrev_coint` | Engle-Granger and Johansen on the three legs: is `1/−2/1` the cointegrating vector, or is a fitted vector better? Both traded |
| 4 | `sfr_fly_meanrev_pca` | PCA residual of the fly vs the fitted strip (rolling `rolling_residual`, eigenvector continuity), plus PC1/PC2-neutral fly weights |
| 5 | `sfr_fly_meanrev_kalman` | Kalman local-level fair value and Kalman dynamic hedge ratios on the wings |
| 6 | `sfr_fly_meanrev_curvefit` | Nelson-Siegel / Svensson / spline fit across the 16-contract strip; trade the fly's deviation from the fitted curve |
| 7 | `sfr_fly_meanrev_xsection` | cross-sectional rank: long cheapest / short richest, within-bucket standardised then pooled (the `ls_fade` pattern) |
| 8 | `sfr_fly_meanrev_regime` | state filters: Hurst, variance ratio, ADF/half-life gating, realised vol, FOMC proximity, curve level and slope |
| 9 | `sfr_fly_meanrev_summary` | the league table |
| 10 | `sfr_fly_rules_of_thumb` | the per-CM-slot desk card |

Momentum is not a separate notebook: it is the mandatory `direction` axis inside every grid.

## Engine

`RVUtils/SFRRVLab/engine.py` marks **option structures** through a `MarkBook` and cannot
mark a futures fly without a fake book. This lab therefore adds a sibling engine for the
case where the traded object is a **level series in bp**, and reuses
`RVUtils/SFRRVLab/stats.py` unchanged for grid distribution, DSR, Newey-West t,
non-overlapping Sharpe, cost curve and verdict — so both labs are graded by identical code.

`RVUtils/MeanRev/` (new, data-agnostic, synthetic-testable):

* `panel.py` — wide-panel helpers: rolling z with an `exclude_current` switch,
  cross-sectional rank/standardisation, regime tagging, birth/death masking.
* `engine.py` — one vectorised backtest over `levels: DataFrame[date × key]` and
  `signal: DataFrame[date × key]`, with the same structural rules as the SR3 lab engine
  (lag, deterministic exits unlagged, cost on the exit bar, gates at entry only) and the
  same `LabResult` shape so `SFRRVLab.stats` consumes it directly.
* `signals.py` — the method families as pure functions from a level panel to a signal panel.
* `shadow.py` — the linear-shadow decomposition (belly outright, both calendar spreads).

## Toolkit refactor

The audit found **11 independent OU/half-life implementations**, 7 mutually incompatible
ADF call conventions, 27 z-score sites, and both Hurst and variance ratio trapped as
closures inside a plotting builder. Two are outright bugs:

* `RVUtils/plt_timeseries.py:323 _hurst_exponent` returns `2 × slope` of
  `log std(Δ_l x)` vs `log l`, which is **2× too large** — measured H = 1.035 on a pure
  random walk (should be 0.5).
* `RVUtils/mean_reversion.py:184 optimal_ou_thresholds` accepts `kappa` and `sigma` and
  **never uses them**, and its zero-cost branch fails `brentq` and silently returns the
  fallback constant `1.0`, producing a discontinuity (a* = 1.000 at cost 0, 0.017 at cost
  0.01) that breaks monotonicity in cost.

Scope of the refactor (bounded — it must not destabilise the screeners):

1. `RVUtils/mean_reversion.py` gains the canonical core: `half_life`, `rolling_half_life`,
   `hurst_exponent` (correct scaling, `std` and `rs` estimators), `rolling_hurst`,
   `variance_ratio` (+ Lo-MacKinlay heteroskedasticity-robust z), `ou_mle` (the exact
   closed form currently buried inside `simulate_mean_reversion_ou`),
   `bertram_thresholds`, `kalman_local_level`, `kalman_hedge_ratio`, `rolling_zscore`.
2. `optimal_ou_thresholds` fixed: solve the zero-cost FOC, honour `kappa`/`sigma` by
   returning bands in level units alongside σ_eq units.
3. Delegation, preserving each caller's existing sentinel semantics under test:
   `plt_timeseries._hurst_exponent` / `_variance_ratio` / `_ou_calibrate`,
   `FlyVsVol.screener.series_half_life`, `BT/signals/sfr_kink_fade.fit_ou_halflife`.
4. Hot paths profiled before optimising, with the measured speedup stated.

Everything new is covered by synthetic, no-network, hand-computable tests in
`tests/test_rv_*.py` and `tests/test_meanrev_*.py`, run under
`conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.

## Deliverables

1. This design + `docs/superpowers/plans/2026-07-29-sfr-fly-meanrev.md` +
   a findings doc written at the end.
2. `RVUtils/MeanRev/` + the `RVUtils/mean_reversion.py` consolidation, with tests.
3. `notebooks/rv/build_sfr_fly_panel.py` (checkpointed, resumable) and
   `notebooks/rv/build_sfr_fly_structures.py` (panel → flies → CM tags → regimes).
4. Executed notebooks under `notebooks/backtests/`, built by `_py2nb.py`, executed with
   `jupyter nbconvert --to notebook --execute --inplace`, verified by `_verify_nb.py`, all
   driven by `run_sfr_fly_meanrev.py`.
5. `notebooks/data/sfr_fly_meanrev/league_table.csv` (+ `_sorted`) and
   `rules_of_thumb.csv`.
