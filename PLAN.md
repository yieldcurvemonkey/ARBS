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

`DateTriggerRequirements` needs `.date()`; `QueryDrivenBacktest.run()` swallows per-step exceptions
→ assert non-zero marks, closed count, no equity holes; derive the bp normalisation analytically
(`R = bpv/w_belly` for IRSwap FLY); `_frb_structure_sign_mapper` is **identity** for FRB FLY and
`calc_spread_rate` scales a 3-leg FRB package by **100** (→ bp) and `abs()`es the ytm (benign for
USTs).

Three that were written down WRONG here and cost a whole run — corrected 2026-08-12:

* **"fee lands only at unwind"** is true and was the trap, not the lesson. The unwind is the only
  fee hook, so charging `rt/2` there because "entry pays the other half" charges **half a round
  trip**. Charge the whole thing at the single hook.
* **"`_build_fly` copysigns wings opposite the belly (GSS weights already have that shape, so they
  pass through)"** — false. It re-signs the package from `sign(bpv)`
  (`FixedRateBondStructure.py:228-231`), so an unsigned `+belly_bpv` forces the belly LONG on every
  trade and discards the signal's direction. Weights "pass through" only when the belly weight is
  positive, i.e. half the time. **15 of 35 flies were put on backwards.** `bpv` must carry the sign.
* **The engine marks bonds at DIRTY NPV.** So `closed["realized_pnl"]` contains coupon accrual and
  the matching coupon *cash* is booked separately via `on_mark`. The two are mirror images: netting
  them turns +$7.9m and t=+1.47 into **−$368,673 and t=−0.20**, and five trades spanning all four
  coupon dates were 105% of the headline. Never read a bond trade ledger without netting the cash.

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

5. **A narrow check certified a broken path.** The first equivalence test compared CUSIP membership
   and rank and reported 48/48 — true, and useless: the local frame was missing `ttm` entirely.
   `apply_universe_filter` *skips* a missing column but *applies* a null one, and `NaN >= min_ttm`
   is False, so once the 48 fetched days supplied a `ttm` column the concatenated panel carried it
   as NaN for the other 284 and **the tradeable universe was empty on 284 of 332 dates**. Nothing
   failed: 343 bonds, 1.94bp RMSE, zero equity holes, plausible P&L — from 14% of the sample.
   `scripts/gss_funnel.py` caught it because the count of dates with any eligible bond was
   *exactly* 48. `ttm` is now computed on **ActualActual(ISDA)** (exact against six fetched frames;
   `days/365.25` is off by half a day and `min_ttm` is a hard cutoff at 3.0), the check compares
   every shared column, and `_assert_reference_is_usable` refuses a panel whose gating column is
   present-but-null. **Any GSS result produced before this is void.**

Also measured: the supplied `gc_repo_hist_example.xlsx` GC curve is **flat across all 14 tenors on
100% of days** — Citi serves the identical number for ON through 10Y — so `repo_tenor` cannot
matter for this collateral and leg-level specialness is the only possible differentiator.

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

## Provenance and cost — both now MEASURED, not assumed (2026-08-12)

`FedInvestDataFetcher` returns `bid_price` and `offer_price`, not just `eod_price`. Two questions
that had been flagged as open are closed from that data.

**1. The matrix-pricing concern is refuted.** Off-the-run closes are genuine dealer quotes, not
interpolations — which matters because all five spline fits share the same prices, so the S1–S4
comparison structurally could not have detected it. Five fingerprints on 3,149 note/bond quotes:

| test | result |
|---|---|
| price on the 1/32 quote grid | **100%**, every seasoning bucket |
| spread vs seasoning | 0 ticks OTR → 0.5 rank 1–6 → 1.0 (p95 4.0) deep off-run |
| `eod` equals the mid | only **1.4%** for deep off-runs |
| spread as f(maturity) | not deterministic (within-bucket sd 0.5–1.9 ticks) |
| spread constant per bond | only **5%** never change it |

An interpolated value is a continuous real and would land on a 32nd essentially never.

**1b. Zero is not a price — and the panel used to believe it was.** On **nine days in 2026-07/08**
FedInvest published `eod_price = 0.0` for **all 463 bonds** while `bid_price` and `offer_price`
stayed perfectly sane (94.97 / 94.98 on the same CUSIP the day before and after). Nothing raised:
the pricer solved a yield from a zero price and got **605%–5,408%**, the spline fitted a curve
through that, the day recorded an RMSE of **80,876bp** against 1.9bp on either side, and
`build_curve_panel` **cached it and served it as valid ever after**. The book that consumed those
days reached **$178 trillion** in equity.

| date | fit RMSE | median observed yield |
|---|---|---|
| 2026-07-08 | 1.7bp | 4.31% |
| **2026-07-09** | **80,876.6bp** | **873.4%** |
| 2026-07-10, 07-13, 07-17, 07-20, 07-24, 07-27 | 45,196–77,581bp | 772–842% |
| 2026-08-07, 08-10 | 106,944 / 110,443bp | 1,501 / 1,513% |

**Nothing in this PR is contaminated, and that was checked rather than assumed.** Every cached day
in both panels was scanned: the 332-day window 2024-09-03..2026-01-02 that the sweep, the DSR and
the cost table all rest on has **max RMSE 2.6bp and zero out-of-band days**. Only the RV notebook
ever ran the extended range, and it is now pinned to the validated window — where it reproduces the
cost table's `assumed` row to the cent from a different code path (equity −4,254,352.40, fees
−5,637,475.12, gross +1,383,122.72, m\* 0.245, financing ledger 0.0).

`BT/gss_fly/data.py::_day_is_usable` now refuses a day whose observed yields fall outside
[−5%, 25%] or whose fit RMSE exceeds 25bp — **on fetch and on cache read**. Read-side is the
load-bearing half: nine poisoned days were already on disk and the cache is preferred over a
refetch, so a fetch-only check would have left them serving indefinitely. Refusing rather than
substituting the bid/offer mid is deliberate: a panel silently made of two price series is a worse
object than one with a visible hole. Mutation-verified in `tests/gss_fly/test_panel_cache.py`.

This *strengthens* the finding above rather than weakening it: bid and offer survived intact on the
days `eod` died, which is further evidence they are genuine quotes and that the measured cost table
below was built on the right column. (Unrelated source, same July window: see the Citi bond-tape
corruption of 2026-07-14/15.)

**2. The cost table is measured.** Pricing bid and offer to yield on 1,890 quotes
(`scripts/gss_measure_cost_table.py` → `config.MEASURED_HALF_SPREAD_BP`):

| bucket | measured | assumed | ratio |
|---|---|---|---|
| 0–3y | 0.625 | 0.200 | **3.12×** |
| 3–5y | 0.244 | 0.250 | 0.98× |
| 5–7y | 0.156 | 0.300 | 0.52× |
| 7–10y | 0.111 | 0.400 | 0.28× |
| 10–20y | 0.368 | 0.500 | 0.74× |
| 20y+ | 0.161 | 0.800 | **0.20×** |

The **shape** is the finding: the assumed table rises with maturity, the market's is **U-shaped** —
widest at the front (heavily seasoned issues nobody trades) and tightest in 7–10y (the actively
quoted benchmark sector).

**Re-pricing the book on each basis** — `scripts/gss_cost_basis.py`, one candidate scan shared
across all five rows because the fee is a gate-layer knob that never feeds back into the decision.
**Funding basis: UNFINANCED** (see below). The trade set is identical in every row and the script
asserts it:

| cost basis | fees | end equity | m\* | Sharpe (ann) | max DD |
|---|---|---|---|---|---|
| gross (no costs charged) | 0 | +1,383,123 | — | **+0.73** | −860,625 |
| assumed | −5,637,475 | −4,254,352 | 0.245 | −1.90 | −4,812,053 |
| **measured** | −3,928,142 | **−2,545,020** | **0.352** | **−1.24** | −3,159,686 |
| assumed, belly-only | −2,740,000 | −1,356,877 | 0.505 | −0.68 | −2,054,082 |
| measured, belly-only | −2,084,800 | −701,677 | 0.663 | −0.36 | −1,489,334 |

Same 34 trades throughout; the ledgers are identical too (carry during hold −7,278,913, unwind
proceeds +8,217,382, open mark +444,653, and a financing ledger of **exactly 0.000**, which is what
proves the basis rather than the label claiming it).

Fees fall 30% on the measured table — more than the 21% an aggregate estimate suggested, because
the fly's legs sit in the buckets the assumed table over-charged most. **m\* still only reaches
0.352**, and even the most charitable combination (measured costs *and* the source's belly-only
convention, charging two of three legs at zero) reaches 0.663. **The book needs execution ~2.8×
tighter than the market quotes.** That is no longer a calibration question.

The gross row is the sanity anchor: **+0.73 ann against SE 0.87**, i.e. before any cost at all the
book is indistinguishable from zero. Costs are not the difference between a good strategy and a bad
one here — they are the difference between nothing and a loss.

## Deflated Sharpe 0.188 — FINAL, on the completed sweep. There is no config to pick.

The sweep finished at **3,432 rows** (`notebooks/data/gss_fly/grid/S0_jpm/grid.parquet`); 17 had
equity holes and are excluded, leaving **3,415 clean configs** with **2,854 effective independent
trials (83.6%)**. Re-derived from the consolidated grid, not carried forward:

| | |
|---|---|
| best per-period Sharpe | +0.1800  (**+2.86** annualised) |
| **SR₀ — the bar the search itself sets** | **+0.2227  (+3.53 annualised)** |
| **DSR** | **0.188** (needs > 0.95) |

**The best configuration does not even reach the Sharpe expected from the best of that many
zero-skill strategies.** It is *below* the selection bar, not marginally above it.

Two earlier numbers in this file are superseded, and one earlier *story* is withdrawn:

* the "2 SE spread" note was computed on 36 configs and no longer holds — the observed p05..p95
  spread is now 3.29 annualised against SE 0.87;
* DSR was quoted at 0.177 (1,164 configs) and at points during the sweep as low as 0.04 on partial
  extracts. **It did not decline monotonically**, and any narrative built on "the DSR falls as the
  sweep grows" was reading partial grids. The honest statement is that across every partial and the
  complete grid it stayed in **0.04–0.19, never within a factor of five of 0.95** — the conclusion
  was never sensitive to which slice you looked at, which is the only robustness that matters here.

The **83.6% effective-independence** is itself a finding. A parameter grid normally collapses toward
a few independent bets; this one behaves like ~2,854 distinct experiments, corroborating the
decision-space result from the other side — these are genuinely different books, not one book in
costume. That *raises* the bar the winner must clear, which is why the search fails so cleanly.

**Cost.** With ≥ 8 trades, m\* median **0.377**, max 9.64, and **538 of 3,041 configs (17.7%) reach
m\* ≥ 1** — they do cover their charged spread. So "cost-dead everywhere", said earlier on three
variants, was too absolute. But those same configs are what the DSR rejects as selection artifacts,
so both findings agree: a sixth of the space clears costs and none of it is defensible.

Integrity: worst reconciliation gap across all 3,432 rows **8.2e-08 USD**.

### The sweep and everything after it are UNFINANCED — and the file is not uniform

`gc_repo_hist_example.xlsx` — the only repo curve this port ever had — **no longer exists on disk**,
and every entry point silently degraded to `repo_curve=None` when it went. There is no flat-rate
fallback: `CostConfig.fallback_repo_pct` is declared and read by nothing (it is one of the harness's
planted nulls). So the sweep and every table derived from it charge **no financing at all**, and on
a book whose thesis is convergence financed in repo they are **upper bounds, not estimates**.

**This file therefore mixes two funding bases, and the older one is identifiable.** `GSSEntryAction`
attaches its `financing` meta block only when `gc_rate is not None`, so the financing ledger is
*exactly* zero on an unfinanced run. The "GSS result" table further down reports a financing ledger
of **+355k**, which is proof that it was produced while the workbook still existed — and its fees
are exactly half the current ones, which dates it before the exit-fee correction as well. Read it as
a historical record, not as the current book; the re-priced table above is the current one.

Fixed rather than noted: `BT/gss_fly/costs.py::resolve_repo_curve` now announces the funding basis
on all four branches and returns it as a string, `scripts/gss_grid.py` stamps it into every row, and
the notebooks put it in the figure titles — a chart is what gets screenshotted and it travels
without its log. `tests/gss_fly/test_gss_logic.py::test_resolve_repo_curve_never_degrades_in_silence`
pins it (verified by mutation: restoring the silent branch fails the test). The 3,432 rows already
on disk pre-date the stamp and carry no `basis` column; they are all unfinanced.

## The SELECTION is chaotic; the signal is not — measured 2026-08-12

> **Retraction.** An earlier version of this section concluded "the signal reads the interpolator"
> from the trade-set Jaccard alone. That was wrong, and wrong in an instructive way: trade-set
> Jaccard **cannot distinguish "the signal changed" from "the ranking reshuffled"**, and the
> deciding measurement — the s2c values themselves — says the signal barely moved.

| S0 vs S3 (knots slid 1.25y) | |
|---|---|
| cross-sectional **corr(s2c)** | **0.983** median, p05 0.955 |
| **Spearman rank** corr | **0.944** median, p05 0.895 |
| mean abs difference | 0.264 bp against 1.946 bp dispersion |
| trade-set Jaccard | **0.045** |

The residual is almost perfectly preserved. The two fits agree on which bonds are cheap to 0.98 and
on their ordering to 0.94 — and still share 3 of 66 trades.

**The cascade is the mechanism.** Selection is a hard top-N over ~173 near-tied candidates a day, so
a 0.26 bp perturbation — a seventh of a standard deviation — reorders the top of the list and
rewrites the entire book. The signal is reproducible; the selection built on it is not.

That is a **fixable design fault**, unlike a fake signal: rank-average across fits, require a minimum
richness gap over the next-best candidate, or size by conviction rather than selecting top-N. It
also means the economics below stand on their own — the cost wall never depended on the signal
being real, and remains the binding constraint.

**Jaccard 0.045.** Sliding the spline knots **1.25 years** — same knot count, same bonds, same
prices, nothing about the market changed — produces a book sharing **3 of 66** trades with the
original.

| | S0 baseline | S3 knot-shift |
|---|---|---|
| median RMSE | 1.939 bp | 1.933 bp |
| s2c std | 1.946 bp | 1.947 bp |
| entries | 35 | 34 |
| **Jaccard vs S0** | 1.000 | **0.045** |

The tolerant Jaccard is *also* 0.045, so these are not the same trades a few days apart — they are
different bonds.

The two fits are statistically indistinguishable: RMSE differs by 0.006bp, residual dispersion by
0.001bp, trade count by one. By every aggregate measure they are the same curve. Yet they disagree
about which bonds are cheap on 95% of occasions.

**Superseded — see the retraction above.** The original reasoning ran: the s2c residual is not a
where the spline was allowed to bend: a bond looks cheap because a knot sits near it, and moving the
knot moves the cheapness.

This subsumes the economics below. The cost wall, the 4.5× cost/gross and the parameter fragility
all presumed the signal measured something. Tuning parameters on a signal that is an artifact of its
own estimator cannot produce a strategy. It also compounds the unresolved FedInvest question —
off-the-run closes that may themselves be matrix-priced from a curve, fed into a spline that adds
its own curvature: two interpolators between the market and the "signal".

**Settled across five fits.** The pattern is the decisive one:

| fit | RMSE | corr(s2c) | Spearman | mean abs diff | trade Jaccard |
|---|---|---|---|---|---|
| S4_with_otr | 1.926 | **0.992** | 0.977 | 0.14 bp | — |
| S3_shift | 1.933 | **0.983** | 0.944 | 0.26 bp | **0.045** |
| S2_dense | 1.900 | **0.975** | 0.929 | 0.31 bp | **0.059** |
| S1_coarse | 2.260 | 0.865 | 0.748 | 0.79 bp | **0.071** |

**Jaccard is flat at ~0.06 while corr ranges 0.865 → 0.992.** If the trade set tracked the signal,
Jaccard would rise with correlation. It does not move at all — direct evidence that the selection is
decoupled from the measurement. Even S4, agreeing to corr 0.992 with a mean difference of 0.14bp (a
fourteenth of a standard deviation), rewrites the book.

**One caveat.** `S1_coarse` genuinely degrades the signal: corr 0.865, Spearman 0.748, mean
difference 0.79bp against a 1.95bp dispersion. A 5-knot fit is a different *measurement*, not merely
a different selection. So "the signal is fit-independent" would be too strong — it is fit-**robust**
across reasonable knot choices (S2/S3/S4, corr 0.975–0.992) and degrades under a genuinely coarse
one.

## Conditioning — measured 2026-08-12. The book is severely ill-conditioned.

**The Sharpe version of the question is not answerable on this sample and was not attempted.** At
331 daily marks `SE(annualised Sharpe) = sqrt(252/331) = 0.873` — and only 154 of them carry a
position, so that is a LOWER bound. A *difference* between two configs carries sqrt(2) more, so it
needs ~2.4 to be significant at 95%. The observed p05–p95 spread across configs
is **1.40** — smaller than two standard errors. Ranking configs by Sharpe, decomposing its variance
across knobs, or fitting a response-surface condition number would each convert noise into a
structural-sounding claim. (The Hessian route was measured returning κ = 13,498 on a *perfect* fit
built only from inert knobs.)

**The decision-space version is exact**, because which trades a config takes is deterministic.
Jaccard of the trade set against the incumbent (35 entries), one step per knob:

| knob | median J | trades |
|---|---|---|
| `require_turning_point` | **0.084** | 55 |
| `entry_zsig_bp` | **0.090** | 13 → 1,080 † |
| `signal.ts_weight` | 0.097 | 13–44 |
| `signal.smoothing_halflife` | 0.139 | 30–39 |
| `fly.fly_scoring_com` | 0.167 | 10–51 |
| `signal.scoring_com` | 0.169 | 30–38 |
| `fly.fly_smoothing_halflife` | 0.236 | 32–34 |
| `fly.std_halflife` | 0.243 | 22–60 |
| `fly.wing_range_2` | 0.274 | 23–77 |
| `fly.wing_objective` | 0.429 | 25 |
| `universe.min_ttm` | 0.443 | 22–81 |
| `fly.wing_range_1` | 0.581 | 33–46 |
| `costs.repo_penalty_bp` | 0.750 | 27–34 |
| `max_concurrent`, `reentry_cooldown_days`, `exit_abs_z` | **1.000** | 35 |

**12 of 16 knobs change more than half the trade set in one step; 9 change more than three
quarters.** The worst is a boolean — flipping `require_turning_point` retains 8% of the trades.

† **The entry/exit pair has a degenerate region, and the incumbent sits 0.5bp from it.** Entry and
exit are thresholds on the *same statistic*: entry needs `zsig > E`, exit fires on `zsig <= X`. So
whenever `E < X` a fly is entered and immediately qualifies to exit, paying a full round trip for
nothing. The rays above hold `X = 2.5` (the incumbent), so the low-`E` end crosses that boundary:

    E    X    entries
    1.0  2.5    1080     <- inverted: churn
    1.5  2.5     549
    2.0  2.5     267
    2.5  2.5      91     <- E == X
    3.0  2.5      35     <- INCUMBENT, 0.5bp from the boundary
    3.5  2.5      13

At a properly ordered `E=1.0, X=0.25` the book takes **150** trades, not 1,080 — so the 1,080 is an
interaction artifact, not the entry knob's own sensitivity. The finding is structural rather than a
tuning matter: two gates on one statistic with no enforced ordering, and the shipped configuration
a half-basis-point away from the regime where every extra trade is a round trip for nothing.
Swept properly (`X <= E - 0.5`), `repo_penalty_bp` alone is the best-behaved knob measured —
J = 0.72–0.82, monotone, 27–34 trades.

So "the GSS strategy" is not a strategy: it is one arbitrary point whose neighbours are different
strategies sharing a name. Every performance number in this file is a number for that one point.

**Three gate knobs are exactly inert (J = 1.000)**, which is its own finding — the gate has three
effective degrees of freedom, not six:
* `max_concurrent` never binds (average concurrency ≈ 0.8 against a cap of 10),
* `reentry_cooldown_days` never fires (35 entries drawn from 27,194 distinct flies),
* `exit_abs_z` is dead **at the incumbent** because the repo-decay branch takes every exit and the
  z-rollover branch never fires. Conditionally inert, not dead: at a tighter hurdle rollovers do
  occur.

`timing_gap` (tolerant − exact Jaccard) is ~0.000 almost everywhere, so these knobs change *which*
trades, not *when*. This is not jitter around a stable book.

## GSS result — 2024-09-03..2026-01-02, 332 dates, 343 bonds, median RMSE 1.94bp

> **Historical run — do not read these magnitudes as current.** Three tells, in increasing order of
> how much they change: its financing ledger is +355k, which is only possible with a repo curve
> loaded (an unfinanced run books *exactly* 0); its fees are exactly half the current ones, dating
> it before the exit-fee correction; and its unwind proceeds are +10.7m against +8.2m today, which
> is a different book, not a different fee. Kept because the *decomposition* — carry against
> convergence, and the cost line deciding it — is what this section is about and that is unchanged.
> For current magnitudes see the re-priced table above (`scripts/gss_cost_basis.py`).

**The book pays carry to collect convergence, and the cost line decides the answer.** Every term
below reconciles to the equity curve to the cent (`reconciliation_gap_usd = -0.0`), asserted per
run rather than believed:

| term | default (all legs) | belly-only (GSS source) |
|---|---|---|
| carry during hold | −7,930,582 | −7,930,582 |
| unwind proceeds (convergence) | +10,736,111 | +10,736,111 |
| fees | −2,818,738 | −1,370,000 |
| open mark | +444,653 | +444,653 |
| **gross before fees** | **+3,250,182** | **+3,250,182** |
| **end equity** | **+431,444** | **+1,880,182** |
| cost share of gross | **87%** | 42% |

Same 35 entries and 34 closes in both; the only difference is which legs are charged. So the
result is a statement about execution cost, not about the signal — which is exactly what
`cost_legs` was made configurable to ask.

**Carry is the coupon leg, not repo.** The `financing` ledger is a small *positive* (+355k); the
drag is coupon accrual, because `w_L + w_R = -1` leaves the book short more coupon than it is long.
Reading the repo ledger alone produced a confidently wrong claim that carry was a tailwind.

**The entry gate is mis-scaled for USTs.** `ZSig = |z|·σ_fly` with median σ = **0.55bp**, so the
ported 3.0bp threshold demands **|z| > 5.5σ**. The funnel (`scripts/gss_funnel.py`) measures the
distribution it cuts into: 186.5 eligible bonds and 170.3 candidate flies per date, `zsig_max`
median **2.83bp** and p90 **3.83bp** — the gate sits at the top of the daily-maximum distribution
and admits 130/332 dates, and the turning-point requirement removes a further **56.4%**, leaving
76 candidate days and 35 actual entries after cooldown, the concurrency cap and the no-shared-leg
rule. 3.0 came from GSS's EGB book and does not survive the change of market.

**34 trades cannot support a verdict.** The useful outputs here are the reconciliation and the gate
diagnosis, not a Sharpe.

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
