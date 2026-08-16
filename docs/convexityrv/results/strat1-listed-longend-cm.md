All checks complete. Final verification: 432 passed across the entire `test_convexity_rv_*` region under fast-gate markers, 0 failed.

## STEP 1 — UNITS CHECK: **PASS** (two independent paths)

**1a. vs the swaption cube, matched sectors** (`lv.ust_units_check_vs_swaptions`), listed ABPV bp/yr vs OTC ATMF bp/yr:

| listed | OTC node | n | med listed | med OTC | ratio | r(level) | r(change) |
|---|---|---|---|---|---|---|---|
| US_30 | 1Mx30Y | 1898 | 89.254 | 80.795 | **1.105** | 0.949 | 0.699 |
| US_60 | 2Mx30Y | 1898 | 89.360 | 81.407 | 1.098 | 0.952 | 0.658 |
| US_90 | 3Mx30Y | 1898 | 91.786 | 81.471 | 1.127 | 0.951 | 0.567 |
| US_30 | 1Mx20Y | 1898 | 89.254 | 82.431 | 1.083 | 0.962 | 0.695 |
| UL_30 | 1Mx30Y | 1647 | 84.479 | 81.461 | **1.037** | 0.936 | 0.476 |
| UL_30 | 1Mx20Y | 1647 | 84.479 | 83.698 | 1.009 | 0.931 | 0.483 |
| UL_90 | 3Mx30Y | 1642 | 88.141 | 83.293 | 1.058 | 0.896 | 0.343 |
| TN_30 | 1Mx10Y | 633 | 98.721 | 90.958 | 1.085 | 0.965 | 0.647 |
| TY_30 | 1Mx10Y | 1898 | 90.117 | 83.445 | 1.080 | 0.975 | 0.790 |
| TY_90 | 3Mx10Y | 1897 | 91.599 | 81.782 | 1.120 | 0.978 | 0.782 |

Ratios 1.009–1.127, level r 0.896–0.978, change r 0.343–0.790. A percent/decimal slip would be ~10x, an annual/daily slip ~16x.

**1b. vs the panel's own ATM through the CTD DV01** (`lv.ust_units_check_dv01`). The repo's `USTFuturesMDP` has no DV01, but `USTFutureOptionMDP._compute_fv01` defines `FV01 = ModDur_ctd × Dirty_ctd / (1e4 × CF)`, and every input exists **offline** in `%LOCALAPPDATA%/ARBS/Cache/ust_future_store/basis_reports` (6,696 files, 800+ dates/root). `ModDur` is computed by new `lv.bond_price_and_duration`; **validated, not assumed** — repricing each CTD from its own quoted yield reproduces the store's clean price to a median **0.00155 price points** (~0.05 of a 32nd), p99 0.00736, over 4,235 front-contract rows.

Date-matched implied vs actual ABPV, cm=30: **UL 0.993** (p05–p95 0.975–1.003, n=332), **US 0.988** (0.965–1.015, n=792), TN 0.983, TY 0.974, FV 0.955, TU 0.887. At cm=60/90: UL 0.992/0.992, US 0.985/0.983.

Price-free form (`ModDur = 1e4·ATM/ABPV`, futures price cancels): implied TU 1.65, FV 3.91, TY 5.84, TN 7.68, US 11.65, UL 16.61 vs measured CTD ModDur 1.85 / 4.01 / 5.85 / 8.12 / 11.58 / 17.14 — ratio 0.893–0.997, and invariant to constant maturity (spread ≤0.03 yrs, TY 0.14) as duration must be.

**1c. Verdict PASS.** Residual: listed runs **4–13% above** matched OTC. Correct sign for (a) Treasury-vs-swap yield vol and (b) the delivery/CTD switch option inside the futures option. It makes listed the **harder** benchmark, not the easier one.

## STEP 2 — SECTOR MATCHING (measured CTD, front contract, 2019+)

TU 1.94y/1.85 · FV 4.39/4.01 · TY **6.80**/5.85 · TN 9.61/8.12 · US **15.86**/11.58 · UL **25.59**/17.14.

The contract named "30-year bond" (US) prices a **~16-year** Treasury yield, so `UST_SECTOR_MAP` makes **UL the primary for 30Y/50Y and 20Yx5Y/25Yx5Y** (US = alt), **US primary for 10Yx10Y/20Yx10Y** (TN alt), TY the control everywhere.

TY control result: on the UL structures, primary 5.318 vs control 6.083 bp/day (**−0.765**), daily-change r only **0.425**. On US-primary structures −0.061, r 0.818. `cheap_share_diff = 0.0000` on all three forward structures — that is **saturation, not control failure**, which is why `longend_benchmark_separation` reports levels/gaps/change-correlation as well.

## STEP 3 — TERM STRUCTURE (stated, not assumed)

Listed ABPV 30→90d slope: **US +2.31%** (+0.13 bp/day), **UL +4.39%** (+0.23), TY +1.73%, TN +0.10%, FV +0.66%, TU +0.24%. The OTC 30Y tail runs the **other way** (1Mx30Y 80.80 → 1Yx30Y 78.94, −2.3%).

Max cheap-share spread across 30/60/90 = **0.0167**, and it occurs **only on 5Y/30Y** (US 0.5334→0.5471; UL 0.4909→0.5076; TY 0.5555→0.5653), always toward *more* cheap. On the three forward structures the verdict is saturated and the slope cannot move it.

## STEP 4 — THE RUN (62,333 rows, 2019-01-02..2026-08-14)

Cheap-share vs listed at every root and every CM tenor, next to the swaption number:

| structure | UL | US | TN | TY (control) | **1Yx30Y swaption** |
|---|---|---|---|---|---|
| 30Y/50Y | 1.000 | 1.000 | — | 1.000 | 1.000 |
| 20Yx5Y/25Yx5Y | 1.000 | 1.000 | — | 1.000 | 1.000 |
| 10Yx10Y/20Yx10Y | — | 1.000 | 1.000 | 1.000 | 1.000 |
| 5Y/30Y | 0.4909/0.5003/0.5076 | 0.5334/0.5402/0.5471 | — | 0.5555/0.5644/0.5653 | 0.514 |

(30/60/90d; n = US/TY 1,901 days, UL 1,643–1,648, TN 633 — windows differ and are carried per row.)

Median bp/day: curve breakeven 0.000 / 0.414 / 1.034 / 2.515; listed UL_30 5.318, US_30 5.614, TY_30 5.675, TN_30 6.216; **1Yx30Y swaption 5.020**.

**Vol basis, OTC − listed, median bp/day — negative for all 12 benchmarks**: UL_30 −0.195, UL_60 −0.233, UL_90 −0.244, US_30 −0.546, US_60 −0.626, US_90 −0.706, TN −0.555/−0.568/−0.590, TY −0.802/−0.859/−0.826.

`frac_signals_disagree`: **0.0000** on the three saturated structures, **0.032–0.053** on 5Y/30Y.

## THE ANSWER

**Yes, it survives — and the hypothesis is backwards: swaptions were the *cheap* comparison, not the expensive one.** The long-end flatteners are cheap gamma on 100% of days against every listed UST benchmark at every constant maturity, identical to their 100% against 1Yx30Y swaptions, because listed UST vol prices a median 0.20–0.86 bp/day **more** vol than the swaption, so substituting the exchange benchmark makes the curve look cheaper still.

**Caveat that belongs next to it:** the cheap-share is **saturated** and therefore weak evidence about a benchmark — 30Y/50Y is `always_cheap` (positive carry, cheap against *any* vol) on 86.0% of days, so the comparison never binds. The information is in the gap and the basis, and in 5Y/30Y, the one unsaturated structure.

## TIE-OUTS

- **Sign probe (live):** 30Y rate 291.21 → 289.95 bp (−1.26 bp) over 2022-09-12..15; `bpv>0` leg P&L −128,366 vs expected −126,100 (−1.8%, carry+convexity); buy/sell mirror exact to 1e-6. Package: both legs pv01 ±100,000, notionals mirror, sum(pv01)≈0. Flattener profile convex → `CURVE bpv<0 = FLATTENER = LONG convexity` confirmed. (Note: a 30Y payer *lost* over the 2022-09 CPI shock — the long end rallied — so the probe asserts against the **measured** rate move, not a remembered narrative.)
- **Payoff-profile regression:** 32 (date × structure) profiles rebuilt from the live curve on 8 dates spanning all three breakeven branches. **max payoff diff 0.0, max carry diff 0.0, max breakeven diff 0.0, all statuses match** — reuse of `strat1_signal_panel.parquet` is exact, not approximate.
- **Tests:** 56 in the new file; **9/9 mutations caught** (bp/day bridge inverted, ATM given a bp/day, duration identity inverted, sector map by contract name, control collapsed onto primary, alias folding dropped, positional join, breakeven status dropped, wide shift grid). 432 passed across `tests/test_convexity_rv_*.py` under fast-gate markers.

## DISCREPANCY WITH THE BRIEF (measured, not reconciled)

The brief quoted "30Y/50Y 100% `always_cheap`, 20Yx5Y/25Yx5Y 58.5%, 10Yx10Y/20Yx10Y 61.8%". Measured from `strat1_signal_panel.parquet`: **cheap-share (signal>0) is 100%/100%/100%**; **`frac_always_cheap` is 86.0%/40.7%/34.2%**. The 100%-of-days claim holds; the `always_cheap` percentages in the brief do not match the stored panel.

## FILES

- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/listed_vol.py` — added `load_ust_cm_panel`, `ust_cm_series/_wide`, `ust_listed_atm_series` (returns the `listed_atm_series` shape so `strat1_listed` consumes it unchanged), `ust_cm_term_structure`, `UST_SECTOR_MAP`/`UST_CTD_PROFILE`/`UST_ROOT_ALIAS`/`UST_BASIS_ROOT`, `ust_benchmarks_for`, `ust_coverage_report`, plus the units helpers `bond_price_and_duration`, `parse_treasury_label`, `load_ctd_basis_frame`, `ust_implied_ctd_duration`, `ust_abpv_from_price_vol`, `ust_units_check_dv01`, `ust_units_check_vs_swaptions`. **`load_ust_panel` still raises** (the smile gap is real and its test/notebook pin it); `coverage_report` keeps `available_offline` and adds `atm_cm_available_offline`.
- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat1_listed.py` — added `LONGEND_SHIFTS_BP` (strat1's ±250 grid, **not** `WIDE_SHIFTS_BP`), `build_longend_listed_panel`, `longend_signal_distribution`, `longend_vol_basis`, `longend_term_structure_effect`, `longend_benchmark_separation`, `longend_curve_regression`, and `Strat1ListedConfig.longend_*` fields + `longend_curve_config()`. Every new field defaults so the SFR path is byte-identical — `test_convexity_rv_threeway.py` passes unchanged.
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat1_listed_longend.py` + executed `.ipynb` — 30 code cells, 0 unrun, 0 errors.
- `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_listed_longend.py`
- Artifacts: `notebooks/data/convexity_rv/strat1_listed_longend_{panel.parquet,distribution.csv,basis.parquet,verdict.json}`, `ust_ctd_fv01.parquet` (bit-identical on rebuild), `vol_shortexp_longtail.parquet`.

Note: `tests/test_convexity_rv_listed_contracts.py` failed twice mid-session on `ArrowInvalid: Parquet magic bytes not found` — a partially written file from the concurrent `harvest_listed_contract_vol.py` run, not related to this work; it passes now that the harvest finished.