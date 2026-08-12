# feat/xccy-and-gss-rv — build plan and state

Two **independent** RV strategies ported from `C:/Users/chris/clee/jpm_pfin`, each with its own
signal/util modules, each backtested on `BT.query_engine.QueryDrivenBacktest`.

## Layout

```
BT/gss_fly/            GSS cash-bond butterfly book (UST re-target)   [no imports from xccy_rv]
BT/xccy_rv/            RVPF cross-currency basis book                 [no imports from gss_fly]
RVUtils/PortfolioOpt/  RVPF mean-variance optimizer (generic infra; xccy_rv imports it)
notebooks/rv/gss_fly_rv.ipynb
scripts/warm_citivelo_xccy_repo.py
tests/gss_fly/, tests/xccy_rv/
```

## Data reality (measured 2026-08-12)

| | status |
|---|---|
| GSS (UST) | **fully offline-capable.** `FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")` → 349 bonds ref, `fetch_cash_spline` 274-bond fit, RMSE 1.84bp, `z_scores()` all work with no Excel. |
| xccy | **no history cached** (0 of 14,438 citivelo parquets are XCCY). Excel add-in **NOT running** → cannot warm. Build against a pluggable data layer; ship running on RVPF's banked 2005-2015 CSVs; Citi warm is a runbook script. |
| repo | `RATES.REPO.USD.{USTREASGC,USD5YOTR,USD10YOTR,USD30YOTR}.SPOT.{ON,TN,1W,1M,3M,6M,9M,1Y,2Y,3Y,4Y,5Y,7Y,10Y}` — grammar recovered from `gc_repo_hist_example.xlsx`. Needs the same warm; xlsx is the offline fallback. |

## Faithfulness anchors (they differ, deliberately)

* **xccy** has a numeric tie-out: `rvpf_repro.py` on the banked CSVs gave gross IR **+0.39** / net **+0.25**
  (union panel 2007-09→2015-10, 20 instruments), era split 2007-09 **+1.54**, 2010-12 **+0.03**,
  2013-15 **+0.29**. The ported package must reproduce these.
* **GSS** has **no surviving calibrated outputs** — faithfulness is spec fidelity plus hand-derived
  known-answer tests (weights formula, wing selection, tcost bucket, entry/exit gates).

## GSS spec (from GSS_module.py / GSS_main.py, read directly)

* bond signal `= 0.75·TSscore + 0.25·XSscore`; `TSscore = zscore(ewma(S2C, halflife=3), com=20)`
  (NB the original passes the scoring window **positionally** to `pd.ewma`, so it is `com`, not halflife)
* universe: coupon < 7, TTM >= 3y, seasoning >= 50d
* wings: belly TTM < 10 → ±2y; 10..20 → ±5y; >= 20 → left from 20y, right to +100y
* weights: `w_L = -(M_R-M_B)/(M_R-M_L)`, `w_B = +1`, `w_R = -(M_B-M_L)/(M_R-M_L)`, then **× sign(fly z)**
* fly z: `ts_scoring(fly_s2c, smoothing=2, scoring=30)`; `Std = ewmstd(fly_yield_bp, hl=20)`
* **`ZSig = |z| · Std`** (bp) — entry `ZSig > 3.0` AND `d|z| < 0`; exit `ZSig <= 2.5` (repo_pen) OR (`|z| < 0.5` AND `d|z| > 0`)
* costs: one-way TTM-bucketed, **belly only** (their assumption — re-set, see below); repo accrual `-(r/360)·days`
* P&L: `-Δ(FlyYield + Tcosts) · |Position_{t-1}|`

### Deliberate deviations from the original (each a config knob, each documented)

1. `wing_selection` in the original maximises `|Signal_wing − belly.TimeToMaturity|` — it subtracts a
   maturity in **years** from a **z-score**. Almost certainly a typo for `Signal_belly`. Default is the
   corrected `signal_gap`; `legacy_ttm_bug` reproduces the original.
2. Cost charged on the belly only is theirs; default here charges **all three legs**
   (`cost_legs="all"`), with `"belly_only"` available. Their rule flatters the result.
3. EGB → **UST**: ARBS has no non-US bond reference data.

## Landmines already paid for (do not re-learn)

`DateTriggerRequirements` needs `.date()`; fee lands only at unwind; `QueryDrivenBacktest.run()`
swallows per-step exceptions → assert non-zero marks, closed count, no equity holes; derive the bp
normalisation analytically (`R = bpv/w_belly` for IRSwap FLY); `FixedRateBondStructure._build_fly`
copysigns wings opposite the belly (GSS weights already have that shape, so they pass through);
`_frb_structure_sign_mapper` is **identity** for FRB FLY and `calc_spread_rate` scales a 3-leg FRB
package by **100** (→ bp) and `abs()`es the ytm (benign for USTs).

## Data acquisition — measured 2026-08-12, after three panel builds were lost

The GSS panel is I/O-bound, not compute-bound: a serial build sat at **2% CPU** for 35 minutes
holding one connection to `164.95.95.225:443` (Treasury). Four things were wrong, in the order they
were found:

1. **The cache was written only at the end.** Three builds were killed; none left a cached day
   behind. Days are now written to `cache_path/days` as they complete.
2. **An incomplete panel consolidated anyway** — and the consolidated file wins on read, so every
   later run loaded the short panel and never retried the missing days. A transient stall became a
   permanent hole, silently. Hence `consolidate="complete"|"never"|"always"`; a chunked warm must
   pass `"never"` or chunk one bakes a two-day prefix as the whole range.
3. **Threading was the wrong lever.** Measured **1.14×** on cold days, not the near-linear first
   claimed — the MDP serialises internally. `workers` is retained and *is* verified bit-identical to
   serial against the real source (s2c/ytm/ttm/rmse/reference all equal over 10 days, so the path is
   thread-safe), but it is not the answer.
4. **`get_bond_reference_data` bypasses the reference cache entirely**, calling `_fetch_fiscaldata`
   directly. 350 HTTP round-trips for one static universe file. Per day: **1.62s fetched vs 0.002s
   local (764×)**, and the reference was **92%** of the per-day cost. `fetch_cash_spline` makes the
   same call before it fits, so the provider is bound onto the MDP for the build (scoped, restored
   on exit) rather than only replacing the builder's own call.

**The boundary rule was measured against 48 reference frames built by the fetched path**, which the
day cache preserved. `issue_date <= as_of < maturity_date` reproduces all 48 exactly — membership
and on-the-run rank. Neither boundary is `_filter_and_rank_ref_df`'s: its strict `issue_date <
as_of` drops a bond on its issue day (2024-09-03: the 2Y/5Y/7Y/20Y settling that day, **181 ranks
moved**), and its `maturity_date >= as_of` keeps a bond on the day it matures (3 dates, 7 bonds).
Not cosmetic here — with `exclude_ranks=(0,)`, whether the new issue is present decides whether the
*previous* on-the-run is rank 0 and dropped, or rank 1 and traded. Splines refit under the local
provider match the cached ones to **3e-13 bp**.

## Status

- [x] worktree, orientation, specs read from primary sources
- [x] `RVUtils/PortfolioOpt` — 13 known-answer tests, exact closed form on diagonal and full covariance
- [x] `BT/gss_fly` — 23 known-answer tests
- [x] `BT/xccy_rv` — 20 tests **including the archive tie-out**
- [x] notebook (`notebooks/rv/gss_fly_rv.ipynb`), warm runbook, tests

## Results

**xccy — the tie-out passes.** Panel IR **gross +0.400 / net +0.264** against the reference
+0.39 / +0.25; era split **1.55 / 0.16 / 0.31** against 1.54 / 0.18 / 0.29. The engine run over
the same 2,003 days: 0 equity holes, 2,973 closed positions, +$24.7k net and +$57.8k gross-of-fee
on $1m of notional per unit, daily Sharpe +0.14. It is a crisis trade — 2010-12 net IR is 0.02.

**Three unit bugs, each of which left a book that still ran and still looked plausible:**

1. the fee was charged on the whole position at every resize rather than the traded increment
   ($624m of fees against $47k of gross P&L);
2. `notional_per_unit` was read as $/bp, inflating every fee by 10,000×;
3. the archive banks its basis curves in **decimals**, not bp, so every engine mark and every
   carry accrual was 10,000× too small and the engine reported a flat book.

The GSS fly vol had the mirror of (3): the panel carries yields in percent, and `ZSig` is compared
against bp thresholds, so `yield_scale=100` is now explicit.

**Inherited behaviours pinned rather than fixed:** the optimizer returns NaN for a single-asset
problem; its objective is `P = 0.5·λ·Σ` against cvxopt's own ½, so the optimum carries a factor
two against textbook; the sqrt-market-impact + quadratic-constraint path has the author's own
undiagnosed infeasibility and is untested.

## Live Citi Velocity (2026-08-12, Excel launched and signed in after 4.8 min / 1 login press)

**The sign is SETTLED: `+1`.** Two independent tests agree, and the checker was itself verified
against synthetic inverted and ambiguous wires before being trusted:

| test | result |
|---|---|
| levels | EUR/USD 5Y median **−23.30 bp**, USD/JPY **−67.36**, GBP/USD **−10.42** — all negative, the market convention |
| COVID squeeze | −15.17 → **−32.83**, i.e. widened *negative* |

**Warm complete** — xccy 102,222 values, repo 78,316 (GC + all three OTR specials), money markets
16,272, all 2012-11 → today.

### Three findings that change how the port should be read

1. **Citi's xccy history begins 2012-11-01**, not 2005 (3,551 rows on EUR/USD 5Y). **The 2008
   crisis is not available** — and on the archive's own data that crisis is where essentially all
   of the IR came from.
2. **The "which leg" premise is wrong.** `BASE_LEG` and `SPREAD_LEG` are *both* materially non-zero
   and nearly equal (−22.56 vs −23.30). The module assumes one carries the spread and the other is
   flat. Collateral currency remains untestable from levels.
3. **Live carry is a different object.** Same window, same instruments: the archive's model-implied
   carry is **+1.519 bp/yr** median against Citi's quoted-grid **+0.289** — same sign, ~5× smaller.
   That is model-vs-market in the forward-basis term structure, and it explains the 4.6× lower
   turnover and the different era profile.

### Live run — 2013-07 → 2026-08, 16 instruments, `sign=+1`

Panel IR **gross +0.270 / net +0.229**; breakeven cost **3.26 bp**; mean turnover 0.034/day.
Era split (net): 2013-15 **−0.17**, 2016-19 **+0.46**, 2020-22 **+0.31**, 2023-26 **+0.81**.
Engine: 3,390 marks, **0 equity holes**, 362 closed positions, +$60.3k.

**Treat the improving profile with caution.** It is the opposite of the banked story, it rests on a
carry definition five times smaller, and there is still no measured cost line to put against the
3.26 bp breakeven.

## Still open

* **No measured ARBS cost line for cross-currency basis.** The 1.0bp round trip is the original's
  assumption carried forward. The live breakeven is 3.26bp, so the verdict hinges entirely on a
  number nobody in this estate has measured. This is the single most valuable next measurement.
* **Which leg, and the collateral currency**, remain unsettled — see above.
* GSS's transaction-cost table is a transparent default, not a calibration: the original's
  country-specific table did not survive.
* The 2008 crisis cannot be tested on Citi data, so the archive's own headline era is
  unreproducible in ARBS.
