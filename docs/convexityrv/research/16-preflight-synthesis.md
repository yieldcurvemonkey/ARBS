<!-- Consolidated synthesis of the six preflight scouts, 2026-08-21. -->

# Preflight synthesis

# CONVEXITY-RV PREFLIGHT — CONSOLIDATED, DECISION-GRADE

**Measured at `C:/Users/chris/clee/ARBS-cvx2` HEAD = `50e5fb29`, branch `feat/convexity-rv2`, 2026-08-21 00:05 EDT.**

⚠️ **The worktree moved twice during this synthesis.** Scouts measured at `61fa6d1a`. During my own tool calls it advanced `61fa6d1a → 59bc9b2e` (preflight doc) `→ 50e5fb29` (shared-CA-path fix, committed 00:04:11 between two of my calls). **A concurrent writer is active in this tree.** Every scout fact below is stamped with the HEAD it was measured at; four scout "live defects" are now FIXED and are marked as such.

---

## 0. ADJUDICATIONS — where scouts (and committed docs) disagree

| # | dispute | winner | evidence |
|---|---|---|---|
| **A1** | **SR3 deep-strip coverage 2024-2026.** `HANDOVER_PREFLIGHT.md` (quoted by scout *newdocs-longend*): ≥16 contracts = 246/246/53/**19/2/1** days 2021→2026. Committed `docs/convexityrv/preflight-2026-08-20.md` §3 (`ca_coverage_by_rank.csv`): rank-17 = 251/187/52/51/**19/2/103**. Scout *coverage* + **my rerun**: rank-17 = 253/187/52/51/**248/247/156**. | **Fresh scan wins, decisively.** | I re-ran the *shipped gate function* `strip_depth_by_date(Q20Config(max_instruments=20, min_strip_depth=4))` — 2,097 dates, 24.9 s, `scratchpad/syn_depth.py`. Coverage scout independently validated the same map elementwise (`n_diff=0`). **The preflight doc contradicts itself:** its own §3 dry-run says only **4/4/3** dates are short of depth 20 in 2024/25/26 — arithmetically impossible against its CSV table. The CSV is a pre-warm artifact; `scripts/warm_sr3_deferred.py` ran manually to completion on 2026-08-19 16:19 (ledger: 635 dates, 9,448/9,476 cells resolved, 0 errors, 5.48 h). |
| **A2** | *newdocs-longend* shortlist #3: *"Blues/Golds are effectively unavailable after 2023"*, tradeable deep window = 2021-2023. | **INVERTED — do not merge verbatim.** | The hole is **2021-2023**. Blues short 58 (2022) + 207 (2023); Golds short 65 (2021) + 201 (2022) + 207 (2023). 2024-2026 are 98-99% complete. Merging that shortlist unedited would contradict §2 of this report. |
| **A3** | OTM smile start date: `DESIGN.md` says **2020-03-25**; scout *engine* measured **2020-04-22**. | **2020-04-22.** | Threshold-insensitive store scan (identical answer at ≥2,3,5,7,9,11,13 offsets) over 2,706 partitions of `USD-SWAPTIONVOL-CITIVELOEXCEL`. |
| **A4** | Cube ATMF coverage: `DESIGN.md` 97.8% vs engine 95.6% vs 99.43%. | **Not a conflict — three denominators.** | 97.8% = ÷ store-days; 95.6% = ÷ `pd.bdate_range`; 99.43% = ÷ business-days-minus-US-holidays. Same numerator. Quote the denominator or the number is meaningless. |
| **A5** | Annual-vs-Q/Q swap-leg gap: strat2 docstring "~3.8 bp"; scout *plumbing* measured **6.05-6.07 bp**; `50e5fb29` measured **+4.585 / +5.816 / +5.884 bp**. | **One defect, one date-dependent range 4.6-6.1 bp.** | All three are the same compounding term on different curves/windows. **Now FIXED** (Q/Q is the default in `IRSwapValue._convexity_adjustment`). |
| **A6** | Warm wall-time: `plan()` `est_seconds` 4,039 s (1.1 h); preflight §3 realised 39.9 s/date (5.4 h); ledger median 6.6 s/date (1.6 h), mean 31.1 s/date (7.5 h). | **Budget 1.5-7.5 h, plan the upper end.** | Seconds/date is bimodal (q10/q50/q90 = 2.4/6.6/66.4) and **`corr(seconds, cells) = 0.144`** — the linear-in-cells model is structurally wrong, ~11× optimistic on slope. Preflight's 39.9 s/date is an early-slice mean of the same distribution. |
| **A7** | Module census: scouts saw "18 `RVUtils/ConvexityRV` modules". | **There are 30**, plus 16 results docs. | `ls`: incl. `strat1_longend_listed.py`, `strat1_threeway.py`, `strat2_fly_universe.py`, `strat2_grid.py`, `strat3_strikeless_vol.py`, `listed_vol.py`, `listed_contracts.py`, `factor_neutral_sizing.py` (118 KB), `factor_attribution.py`. **W3 and W4 must build on this scaffolding, not propose from scratch.** |
| **A8** | Scout *plumbing* landmines #1 (annual swap leg), #4 (`_as_percent`), #25 (`except: pass`). | **All three FIXED by `50e5fb29`**, plus a fourth no scout found. | See §1. Do not carry them into the risk register. |

---

## 1. GREEN / RED BOARD

| # | thing | verdict | measurement |
|---|---|---|---|
| G1 | **Backtest engine** (`QueryDrivenBacktest` + `DateTrigger`/`AddQueryAction`/`UnwindPositionsAction`) | 🟢 **LIVE** | `scratchpad/step1_probe.py`, 8.1 s, 0 network. `IRSwapQuery` OUTRIGHT ±bpv on 5Y, 2022-09-12..15 → ±$2,303,346, **mirror residual exactly 0.000000e+00**. Ties the pinned value in `docs/convexityrv/results/strat1-jpm-curve-as-gamma.md:21`. |
| G2 | **Sign conventions**, all four | 🟢 **LIVE, probed** | `OUTRIGHT bpv>0 = PAYER`; `CURVE bpv<0 = FLATTENER` (front pv01 `+100000.000`, back `−100000.000`, `sum = 1.455e-11`, mirror `0.000e+00`); `FLY bpv>0 = PAY THE BELLY`; `STIRFuture contracts>0 = LONG future = SHORT rate` ($25/bp). |
| G3 | **Convexity kernel** (`structure_profile` / `payoff_profile`) | 🟢 **LIVE, reproduces DESIGN.md §0** | 4/4 structures, max disagreement **0.0493 bp** (20Yx5Y/25Yx5Y), 0.0441 (30Y/50Y), 0.0432 (10Yx10Y/20Yx10Y), 0.0500 (5Y/30Y) — all inside DESIGN.md's own 1-dp rounding. `carry_bp` reproduces `CARRY_2022_09_13` to 4 dp. Fitted `a` (bp per bp²): 6.16e-04, 1.22e-03, 1.17e-03, 1.20e-03; `is_convex` True for all 4 flatteners, False for all 4 steepeners. |
| G4 | **Convexity test suite** | 🟢 **789 passed / 73 skipped / 0 failed**, 184.6 s | `pytest tests -k convexity_rv -q` (preflight §1, **commit-claimed at `59bc9b2e`, not independently re-run by me**). All 73 skips are *"panel not built"* — the fresh-worktree signature, not failures. |
| G5 | **Shared-CA-path tie-out** (new) | 🟢 **14 passed, 3.81 s — I RAN IT** | `ARBS_SUPABASE_ENABLED=0 <stir python> -m pytest tests/test_convexity_rv_shared_ca_path.py -q -p no:cacheprovider`. Grades `IRSwapValue.CVX_ADJ` against Citi Fig 58 (13 rows, close 6/9/2023) **and keeps the annual-swap variant as a negative control that must fail**. Mutation-checked 4/4 per commit message. |
| G6 | **`USD-SOFR-1D` EOD curve store** | 🟢 **1,466 / 1,470 bdays** in 2021-01-01..2026-08-20 (99.73%) | Exhaustive partition enumeration, `asset=USD-SOFR-1D-CITIVELOEXCEL`: **5,511 partitions, 0 empty, 2005-01-03 .. 2026-08-14**. Only in-window holes: 2026-08-17/18/19/20 (unwarmed tail). 9/9 sampled dates build in 0.02-0.06 s warm; `meta` confirms `from_curve_store=True, mode=eod`, no COM. |
| G7 | **Ultra-long forwards price** | 🟢 **7/7 tenors × 9/9 dates, 0 failures** | 20Yx10Y, 25Yx10Y, 30Yx20Y, 20Yx30Y, 30Y, 40Y, 50Y — all in the 0.1-10% band across 2005-2026. **The curve carries the whole ultra-long space including 40Y/50Y outrights.** This is W3/W4's foundation. |
| G8 | **Swaption cube** | 🟢 **99.43% ATMF and 99.36% full-13-offset smile** (holiday-adjusted) 2021-2026 | 2,706 partitions, 2015-10-08..2026-08-17. Identical for 1Yx30Y / 1Yx20Y / 3Mx30Y / 6Mx30Y / 1Yx10Y — the cube writes them together or not at all. `atmf_vol_series(...)[2022-09-13] = 98.3785 bp` = the pinned test value. **Smile starts 2020-04-22**; ATMF-only signals run from 2015-10-08. |
| G9 | **Intraday CA is achievable with 0 network** | 🟢 **MEASURED END-TO-END** | `scratchpad/probe_cvx.py`: 2026-08-19 15:00 ET, curve 0.470 s, `mode=intraday from_curve_store=True asset=USD-SOFR-1D-CITIVELOEXCELMIN`, `SnapshotPolicy.strict(minutes=5, on_miss="raise")`, all HTTP monkeypatched to raise → **0 network attempts**. WHITES pack `CVX_ADJ = −5.813509 bp` (pre-fix annual leg) / **+0.190513 bp with the Q/Q leg that is now the default**. |
| G10 | **Shared CA path correctness** | 🟢 **FIXED at `50e5fb29`** (was 🔴 at `61fa6d1a`) | Three defects, all pinned to Citi Fig 58: (1) matched swap was annual/annual, **CA too low by 4.6-5.9 bp** — larger than the Whites/Reds adjustment itself; (2) `_as_percent` multiplied any SR3 above 99.00 by 100 — **up to 9,405 bp of error across the whole ZIRP window 2020-03..2022-06**; (3) **`get_barchart_timeseries` did an unconditional `.bfill().ffill()` — look-ahead inside the price panel** (no scout found this). Failures now land in `sfr_cvx_adj_failures` with a reason instead of `except: pass`. |
| R1 | **SR3 deep strip, 2021-2023** | 🔴 **473 Golds-dates + 265 Blues-dates short** | See §2. This is the entire remaining W1 data gap. |
| R2 | **The only rebuilt CA panel on this machine is pre-`db95871d`** | 🔴 | It lives in a *different worktree* (`C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat2_q20_panel.parquet`, 32,540 rows, built 02:50 at `a9bc31a7` where `rl.py` still carried `max_tenor=60`). `ARBS-cvx2/notebooks/data/convexity_rv/` holds **only `_baseline_prewarm/`** (121 MB, 291 files, deliberately non-canonical). **No live panel exists in this worktree.** |
| R3 | **Golds gate in the only extant panel** | 🔴 **41 / 20 / 0** pass-days in 2024/25/26 | Median `max_settle_diff_bp` 2.63/4.01/3.72 against a 2.0 bp gate. Independent 15-date sample: median **2.86 → 1.05 bp**, pass **6/15 → 15/15** when rebuilt at `max_tenor=66`. Corroborated by `db95871d`'s own 963-date population table (2024 5→100%, 2025 0→93.7%, 2026 0→100%). |
| R4 | **`Q12STIRT` / `Q16STIRT` still violate `max_tenor ≥ 3n+6`** | 🔴 **LIVE IN PRODUCTION** | My grep of `rl.py`: line 1066 = **39** (needs 45), line 1093 = **51** (needs 57), line 1139 = **66** ✓. Both drop their terminal calibration instrument and price it by extrapolation. **These are the two curves `daily_cache_warmer` actually builds nightly** — the defect is in the production curve store, not latent. |
| R5 | **The scheduled SR3 settle warm has never run** | 🔴 | `grep -l -i "SR3 EOD settles" logs/cache_warmer/*.log` → **exit 1, 0 matches across all 12 logs** (2026-08-10..20). Tonight's 18:15 run enumerated 16 jobs, none of them it; main reached the primary checkout at 23:15:36, **5 h 00 m after that process started**, so it holds the pre-merge module. First run that *can* include it is the next invocation. |
| R6 | **Per-contract SR3 open interest before ~2025** | 🔴 **SURVIVORSHIP-DEAD** | See §2. |
| R7 | **CFTC positioning cache is 14 weeks stale and cannot self-refresh** | 🔴 | `BT/signals/cftc_positioning.py:51-52` — unconditional `if cache_path.exists(): return read_parquet(...)` before any date check. Last report date **2026-05-12**. |
| R8 | **Hardcoded live gs_quant credentials committed to the repo** | 🔴 **SECURITY** | `MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py:7-8` — `client_id` (len 32) + `secret` (len 64) as literals, resolved at `:63-64`. All five `GS_*` env vars are unset; **auth succeeded on the committed literals**. This must reach the user regardless of which workflow proceeds. |

---

## 2. DATA AVAILABILITY

### 2.1 The three the user asked for

| series | verdict | measured coverage | accessor | the catch |
|---|---|---|---|---|
| **SOFR/ED futures OPEN INTEREST** | 🟠 **PARTIAL — survivorship-shaped, not liquidity-shaped** | SR3 EOD dates with ≥1 positive OI: **2018 0.0% · 2019 0.4% · 2020 0.4% · 2021 4.0% · 2022 34.0% · 2023 79.8% · 2024 99.6% · 2025 99.6% · 2026 98.7%** | `Query/STIRFutures/STIRFutureValue.py:85,112` → `pricer.meta()["openinterest"]`; fetch at `STIRFutureMDP.py:904` | Per-symbol OI fraction splits into **two disjoint groups with no middle**: `SR3H20…SR3M26` (all **expired**) = 0.004-0.028; `SR3U26…SR3M31` (all **live today**) = 0.976-0.996. The boundary is exactly the live/expired line. **The pre-2025 hole is a fixed code-set drifting through the calendar, not vendor absence.** Whether Barchart `queryeod` serves OI for expired contracts is **NOT MEASURED** (fetch prohibited). Gate at `STIRFutureMDP.py:1145` (`want_eod and src=="BARCHART_STIRF-RL"`): intraday and TOS-live **never** fetch OI — 0/17,910,002 TOS rows carry it. Independent tie-out vs CFTC `Open_Interest_All`, 40 common dates: ratio median **0.609** (below 1 exactly as predicted — cache holds 18-20 deferred, CFTC counts the whole strip). |
| **CME-LCH BASIS (gs_quant)** | 🟢 **AVAILABLE — entitled, live-verified** | **2 network calls.** `Dataset("IR_SWAP_RATES_V1_STANDARD").get_data(2026-08-10..14, assetId=[MA4X9S4FR3MNW2JQ (LCH), MASHESG4P65M6ST5 (CME)])` → shape (8,8), 1.2 s. **USD SOFR 10y LCH−CME: −2.00 / −2.05 / −2.05 / −2.05 bp** (Aug 10/11/13/14). | `MDP/IRClearingHouseBasisSwaps/IRClearingHouseBasisSwapsMDP.py.get_pricer()` | Offline catalogue: 33,057 CCP-tagged assets; **exactly 3 (ccy,index) pairs carry both LCH and CME** — USD SOFR, USD OIS, USD LIBOR — spot ladder 1y…30y at both. `historyStartDate` 2018-04-27 is **catalogue-claimed, NOT measured**. **No caching layer exists** (no `GSQUANT_CH_BASIS` diskcache dir) — every call refetches. Default `coverage_path` at `:34` hardcodes the **primary checkout**, not this worktree. 2026-08-12 absent from a 5-bday window, unexplained. A second dataset `IR_BASIS_SWAP_RATES_V1_STANDARD` (40,221 assets, USD SOFR/OIS LCH+CME 801 each) exists but the repo's `_NAME_PATTERN` matches **0** of it. |
| **DEALER POSITIONING** | 🟠 **PARTIAL (CFTC TFF, 14 wks stale)** / 🔴 **UNAVAILABLE (NY Fed PD)** | **2020-01-07 → 2026-05-12**, 332 report dates, 154 markets, modal gap 7.0 d (325/331), fully offline | `BT/signals/cftc_positioning.py:83 build_positioning_panel()` over `BT/results/tfp_screener/cftc_raw.parquet` | Raw carries the **full TFF column set** incl. `Dealer_Positions_Long_All`/`Short_All`, `Pct_of_OI_Dealer_*`, `Change_in_Dealer_*` — but `build_positioning_panel` extracts **only lev/am; there is no `dealer_net`**, and `_CONTRACT_MAP` (`:22-43`) lists only 2Y/5Y/10Y/30Y treasuries. Measured directly from raw: 2Y dealer_net −557,177…+40,213; 10Y −793,974…+176,777. **STIR is in the same file**: `SOFR-3M` n=223 from 2022-02-08 (dealer_net last **+1,719,008**), `3-MONTH SOFR` n=109 2020-01-07→2022-02-01, `SOFR-1M` n=223, `FED FUNDS` n=223. **NY Fed primary-dealer stats: no fetcher, no cache, no schema anywhere in the repo.** |

**The convergence that makes W2b's enrichment work:** Citi's own published positioning signal — Fig 12 of *Left-side vols' outperformance* (22-Jun-2021) — is **"Asset Managers + Leveraged Funds, Net % of OI (inverted)"** plotted against `Blues CA − model`. That is *exactly* a CFTC TFF quantity, at weekly frequency, and it is already on disk. **The signal Citi published is buildable today**; the per-contract exchange OI series that is missing is not the one Citi used.

### 2.2 SR3 settle depth — the W1 gap, re-measured by me

`strip_depth_by_date(Q20Config(max_instruments=20, min_strip_depth=4))`, 2,097 dates, 24.9 s, 0 network (`scratchpad/syn_depth.py`). Rank *r* needs depth *r+3*.

| yr | dates w/ EOD | Whites r1 (≥4) | Reds r5 (≥8) | Greens r9 (≥12) | Blues r13 (≥16) | Golds r17 (≥20) |
|---|---:|---:|---:|---:|---:|---:|
| 2018 | 167 | 167 | 167 | 167 | 167 | 41 |
| 2019 | 253 | 253 | 253 | 252 | 252 | 77 |
| 2020 | 253 | 253 | 253 | 253 | 253 | 253 |
| **2021** | 252 | 252 | 252 | 252 | 252 | **187** |
| **2022** | 252 | 252 | 252 | 252 | **195** | **52** |
| **2023** | 258 | 258 | 258 | **231** | **51** | **51** |
| 2024 | 252 | 252 | 251 | 249 | 248 | 248 |
| 2025 | 251 | 251 | 250 | 249 | 248 | 247 |
| 2026 | 159 | 159 | 159 | 159 | 157 | 156 |
| **ALL** | **2097** | **2097** | **2095** | **2064** | **1823** | **1312** |

**Over the workflows' window 2021-01-01 .. 2026-08-21 (1,424 EOD dates):**

| band | rank | depth | covered | % | warm needed? |
|---|---|---|---:|---:|---|
| **Whites** | 1 | ≥4 | 1424 | **100.0%** | **NO** |
| **Reds** | 5 | ≥8 | 1422 | **99.9%** | **NO** |
| **Greens** | 9 | ≥12 | 1392 | **97.8%** | marginal (27 of 32 are 2023) |
| **Blues** | 13 | ≥16 | 1151 | **80.8%** | **YES** — 58 (2022) + 207 (2023), ~794 cells |
| **Golds** | 17 | ≥20 | 941 | **66.1%** | **YES** — 65 (2021) + 201 (2022) + 207 (2023), ~2,698 cells |

**The warm bill** (`warm_sr3_deferred.plan(2018-01-01, 2026-08-20, depth=20, protect_min_depth=99)`, 52.8 s, no socket — reproduced verbatim in preflight §3): `dates_short 872`, `cells_to_fetch 4,398`, 54 distinct contract codes.
**1,700 of those 4,398 cells are unservable and would be burned**: 85 dates are **2018-01-02 .. 2018-05-03, before the first SR3 key exists (2018-05-04)** — `plan()` unions business days with no launch-date floor (`warm_sr3_deferred.py:170-174`); plus 2021-04-02 (Good Friday) and today. **Servable remainder: 787 dates / 2,698 cells.**

**Decisive measurement — the vendor STILL serves pre-2024 deferred settles.** Every fetch on record was 2024+; the only pre-2024 datapoint was a 2018-12-06 failure. Two deliberate probes at ladder position **depth+2** (so no contiguous prefix could extend and no published `ca_bp_q20` could move): `2023-06-26 SR3Z26 resolved=True (2.0 s)`, `2022-08-09 SR3Z26 resolved=True (0.7 s)` — **both wrote the NY-stamped 17:00 alias the panel reads.** The 2021-2023 plan is viable.

### 2.3 Everything else the four workflows need

| series | verdict | measured coverage | accessor |
|---|---|---|---|
| `USD-SOFR-1D` EOD curve | 🟢 | 5,511 partitions **2005-01-03..2026-08-14**, 0 empty; 1,466/1,470 bdays in window | `IRSwapsMDP(source="CITIVELO_EXCEL")`, asset `-CITIVELOEXCEL` |
| **`USD-SOFR-1D` MINUTE curve** | 🟢 | **1,543 days, 2021-09-14 .. 2026-08-19**; 2026-08-19 = 1,077 rows, 05:00Z→23:16Z | asset `-CITIVELOEXCELMIN`, `IRSwapsMDP.py:3163+` | **⚠️ W2a's intraday history floor is 2021-09-14, not 2021-01.** |
| SR3 minute futures tape | 🟢 | every minute; `SR3H27` on 2026-08-19 = **1,386 keys 00:00→23:59 CT**; newest key `2026-08-20T21:00:00+00:00` | `STIRFutureMDP(source="BARCHART_TOS_LIVE_STIRF-RL")` | **⚠️ invisible to `BARCHART_STIRF-RL` lookups** — `src` is part of the cache key (`:1018,1072`). |
| Swaption cube (ATMF) | 🟢 | 2,706 days 2015-10-08..2026-08-17; 99.43% of trading days 2021-2026 | `RVUtils/ConvexityRV/swaption_cube.py::load_vol_panel` | **always pass `cache_path=`** — it scans all 2,706 dirs regardless of `start`/`end` (~50 s cold). |
| Swaption cube (13-pt smile) | 🟢 from 2020-04-22 | 99.36% 2021-2026; 1,579 smile days vs 1,127 ATM-only overall | same | one degraded day in-window: 2026-08-17 is ATM-only. |
| `USD-SOFR-1D-Q16STIRT` curve store | 🟠 | **201 days only, 2024-01-02..2026-08-20, NO 2026-03 partitions** | CurveStore | the `sfr_convexity_pricer.ipynb` anchor `6.28942097885013` (2026-03-10) **cannot be re-derived offline**; that cell needs a live Q16 build. |
| `USD-SOFR-1D-Q12STIRT` | 🟢 | 2,065 days 2018-06-01..2026-08-20 | CurveStore | but see R4 — built with a short node grid. |
| `USD-SOFR-1D-ERISLIVE` | 🔴 | **2 days** | — | unusable as history. |
| JPM vol package panels (8 parquets) | 🟠 | 2019-08-26..2026-08-12 | `RVUtils/ConvexityRV/jpm_package.py` | **live in `ARBS-cvx`, not this worktree.** Schema-scanned for `open_int\|oi\|volume\|position\|dealer\|flow`: **NONE in any of the 8 files.** It is a pure vol product. |
| `hw1f_model.py` | 🔴 dead | — | `MDP/STIRConvexityAdjustment/hw1f_model.py` | referenced **only** by tests. `IRSwapsTB_v2_STIRCVX_EMPIRICAL` diskcache is `len=0` — nothing has ever been computed on that path. |
| `data/ts` computed-TS store | 🔴 cold | `./data/ts` does not exist in this worktree | `ComputedTimeseriesStore(base_dir="./data/ts")`, `IRSwapsTB.py:494` | **cwd-relative** — CurveStore and diskcache are absolute and shared; this one is not. |

---

## 3. NEW RESEARCH

### 3.1 The STIR / convexity-adjustment family

**Citi, *Sell Eurodollar convexity in Blues* (08-Jan-2018).** Sell $100K DV01 of Blues CA: buy 1000 H1-Z1 packs vs pay $1bn matched-maturity CME swap at 6.5 bp; hedge with an ED6/ED16 steepener at published **0.74/−1.0 DV01 weights** (130/176 = 0.7386 ✓). Seven ranking metrics per pack; selection is "stands out on a number of these". Carry +$140K/3M. Names the CCP rule explicitly: *clear at CME, because the basis has retraced and futures/swap netting is capital-efficient*. **FEASIBLE** — the 17-row table is a direct grading screen for the CA kernel, and the ED6/ED16 hedge translates 1:1 to SR3 ranks 6/16 which are inside the depth-20 strip.

**Citi, *Value in Greens convexity* (15-May-2017) + *Turning Green from Blue* (06-Jun-2017) + *Take off the hedge* (13-Jul-2017).** The only complete open→hedge→de-hedge→close arc in the corpus, and **the only printed target/stop pair: +$450K / −$225K on $300K DV01 = +1.50 bp / −0.75 bp, 2:1.** Two exact tie-outs: CA leg `(4.3−3.35)×$300,000 = $285,000` matches the printed figure to the dollar, and the hedge unwind `+$70,500` matches **only with the initiation leg quantities** — the alert's closing sentence transposes them (literal quantities give +$33,450). **FEASIBLE and high-value: this is the exit discipline strat 2 currently lacks.**

**Citi, *Left-side vols' outperformance* (22-Jun-2021) — the single most implementable CA ticket.** Buy 1000 EDM4-H5 Blue packs vs pay $1.01bn CME 6/17/24-6/16/25 swap at **7.9 bp**, $100K DV01; carry **+1.2 bp/3M**; **target 4 bp tightening, stop 3 bp widening**. Selection rule between Blues and Golds is stated: Golds were more dislocated-vs-model, but **Blues won on higher 3m roll and higher CA-implied vol relative to its multi-year range**. Its Fig 12 is the CFTC-positioning-as-%-of-OI proxy (§2.1). **FEASIBLE** — dated inside the 2021-2026 window, and every input is either on disk or in the CFTC parquet.

**J.P. Morgan, *A better way to sell vol* (03-May-2017).** The only closed-form CA in the corpus: **`A_cvx = σ²T₁T₂/2`** (Ho-Lee reduction). Converts observed-minus-theoretical excess into an **implied collateral funding spread vs 3M Libor** using ~1.3% total margin on a pvbp-neutral package, and trades when implied exceeds actual funding. Makes a falsifiable linear prediction: *halve the IM and the CA net of vol-driven financing bias falls proportionally*. States the front-end CME/LCH basis is **"well under 1 bp… mostly around 0.25 bp"** while CME CAs trade at ~80% of LCH's. **PARTIALLY FEASIBLE**: the σ²T₁T₂/2 model is trivially implementable and reproduces Citi's implied-vol column to ~3-6% (§3.3 caveat); the IM/funding leg needs CME/LCH margin schedules that are **not in ARBS**.

**Clarus (4 notes, 2015-2017) + FIA.** Five full published CME-LCH term structures (18-May-2015, 26-May-2015, 17-Jun-2015, 26-Jun-2017, plus a Tradition multi-currency USD/EUR/GBP grid) reconstruct a 30Y basis path: **<0.1 bp (Jun-2014) → 1.90 → 2.50 → 2.40 → 3.40 bp (Jun-2017)**. *Pricing and Arbitraging* is the corpus's **headline negative result**: a 1.25 bp 5Y basis nets **$62,480 → "just over $45,000"** after deliberately generous fees, and *"this just isn't going to work… I am not beating treasuries."* *For Dummies* gives a complete MVA build ($282,867 CME + $443,678 LCH = $726,545) — **but its printed bp column (1.30/2.10/3.40) does not equal MVA/DV01 (1.257/1.972/3.229); do not build that tie-out as an identity.** **FEASIBLE as historical validation only** — these are levels, not a time series; the live series is gs_quant. `CME vs. LCH: Take Two (FIA)` is **off-topic** — entirely NDF/FX clearing, zero IRS basis content.

**CME Group, *Pricing and Hedging USD SOFR IRS with SOFR Futures* (04-Jun-2025).** **By far the richest known-answer test available.** A fully numeric worked example, every relation of which I have verified: 8-contract strip → par coupon **3.3304%**; bundle price = arithmetic mean = **96.675625**; hedge vector `100,99,99,98,97,96,95,95 = 779` against swap DV01 **$19,480.69** (779×$25 = $19,475); **all 8 convexity P&L scenarios** (−100bp → +$22,292 … +100bp → +$21,226); gamma identity `18×0.5×100×$25 = $22,500` vs $22,292; margin `$569,910 + $1,568,352 = $2,138,262` vs portfolio-margined `$46,161` = **97.84% reduction**; MM edge **0.29 bp gross − 0.1875 bp bundle slippage = ~0.1 bp net**. **FEASIBLE — build this as the tie-out cell for W1/W2b immediately.** ⚠️ Sign hazard: CME's example is the *long-convexity* direction (receive fixed vs short futures); Citi's "sell the CA" is the opposite. Flip before comparing.

**Aikin, *The disappearing convexity bias* (16-Dec-2013).** Primitive payoff definitions and the note's thesis: convexity bias *"has largely disappeared due to the cross margining benefit of both products being cleared and margined by CME Group."* Carries a hard falsifier: **the Euribor bias went slightly negative in summer 2013** because LIFFE futures could not be netted against SwapClear FRAs. **Any model that floors CA at zero is refuted by a published observation.** His companion note on open interest carries the corpus's one explicit **negative** OI claim: *"There does not seem to be an obvious link between increasing open interest and price action."*

**Bonus — Quantitative Finance Stack Exchange, answered by Attack68 (the rateslib author), 14-Jun-2025.** A fully specified `rateslib` `CompositeCurve` implementation of "imply CA from swaps", with 12 printed output values (0.387 → 1.317 bp) and all inputs given. **Directly reproducible in this repo** — but written for `rateslib 2.0` vs this repo's 2.7.1, so version drift is the first suspect on a mismatch. His methodological warning is the sharpest in the corpus and directly contradicts the Citi/JPM model approach: *"STIR convexity is just not based on those models. It depends upon positioning, clearing house margin… I've also seen real market positive convexity prices, which are impossible theoretically."*

### 3.2 The ultra-long-end family

**Citi flattener/steepener screens (4 dated vintages: 04-Dec-2019, 16-Jan-2020, 26-Mar-2020, 08-Jun-2023).** A 15-pair grid of long-dated forward curve pairs with `curve / 1y-Z / 3y-Z / Z-since-2000 / 1y carry / daily BE / 1y realized vol / **BE÷realized vol**`. Delta-hedge the **back** leg at 20-25 bp. **This is the direct answer to the measured defect in strat 1 and strat 3** (`frac_always_cheap` 86.0/40.7/34.2% — *"a permanently-on flattener, not a timing rule"*): BE/vol flips sign at a printed threshold, with four dated decisions across it — enter GBP flattener 17-Jan-2020 at ratio 0.00; **watch-list-but-do-not-enter 26-Mar-2020 on a liquidity veto** despite the signal triggering; exit 05-Dec-2019 at 0.8; enter steepeners 12-Jun-2023 at 1.17/1.38. **FULLY FEASIBLE — needs only the swap curve, so it runs the entire 2019-2026 window at full density, and 50 published cells grade it.**

**J.P. Morgan, *Valuing convexity in the long end: a global perspective* (09-Feb-2018).** `E[return] = carry + slide + ½σ²·Cvx/PVBP`, ranked by **`RAC = E[return over 3M, bp] ÷ (3M realised daily bp vol × √252)`** — which I note is **verified 4/4 against the printed OAT rows, and √252 is the unique annualiser among {250,252,260} that reproduces all four to 2 dp**. Second signal: multiply a swaption-implied distribution by the aged flattener's payoff, or solve for breakeven vol; published hit rates **56% (30s/50s) and 86% (25Y/20Yx5Y)** vs 1Yx30Y ATMF straddles. Names **20Y/40Yx10Y as the cross-market winner in both USD and GBP**. **FEASIBLE — this is W4's primary metric, and the cube's 99.4% ATMF coverage supports the 1Yx30Y comparison for the whole window.**

**J.P. Morgan, *RV on the EUR swap yield curve* (07-Apr-2021) — the only fully-specified systematic strategy in the corpus with a published performance grid.** 50:50 DV01 flies made level- and curve-neutral by a rolling 6M two-factor regression; enter on `R² ≥ 60% ∧ |resid| ≥ 4bp ∧ |z| ≥ 1.5`; exit on **out-of-sample residual zero-cross (ex-ante betas)** ∨ +2SD worsening ∨ 1M elapsed; stand down when the **traffic-light `√(Zb² + Zw²) > 3`**. Exhibit 7 is a 12-trigger × 3-regime grid. **Its Category 2 — 5Y-tail, 5Y-gap forwards (5Yx5Y/10Yx5Y/15Yx5Y … 35Yx5Y/40Yx5Y/45Yx5Y) — is the ultra-long block and the one JPM measures as regime-robust.** **FEASIBLE as a method translation, NOT as a result reproduction** (every published number is EUR 2001-2021). Bonus: the traffic-light *is* a beta-instability detector and should be tested directly against the codebase's own `pc1_neutral 5Y/30Y` finding (+1408 bp walk-forward vs −66 bp full-sample = *"that is the PCA moving, not a trade"*).

**Citi, *Forward steepener and vol divergence* (12-Jun-2023).** The sign-flipped twin of the flattener screen — long-dated forward **steepener** as positive-carry/short-vol, entered on the **efficient frontier of BE/realized-vol (y) against curve Z-score-since-2000 (x)**. It also carries **Fig 58, the 13-row SOFR pack CA screen already used as this codebase's tie-out anchor**, and states the Blues CA *"could continue to compress towards our model fair value, which is currently about 5 bps lower."* **This single note spans W2b and W3 and is the natural bridge between them.**

**J.P. Morgan, *Renewed Formosa supply* (21-Feb-2020) — the cleanest published definition of the strat-1 signal.** *"Implied volatility on a 20s/40s flattener comes from solving for the level of prevailing volatility that would make the flattener's expected convexity P/L precisely offset 1-year slide under parallel rate shocks,"* plotted as **the ratio of swap-curve-implied vol to swaption-implied vol**. **The RATIO is the published normalisation — the codebase's `frac_always_cheap` / cheap-share is not.** Swapping to the ratio is a small change with a published precedent and directly attacks the saturation defect.

**Convexity-hedger flow models (JPM ×3, Citi Formosa ×2, Citi corporate supply).** Precise recipes — 20% bank-hedged share, MSR as a 30 bp IO strip, AGNC disclosure for mREITs, $500mn/day 1Mx10Y programmatic gamma, 30NC1/30NC6 per-bond vega of $145K/$270K per $100mn. **NOT FEASIBLE on this data**: every input is a new external source (agency pools, LCR disclosures, Dealogic, Bloomberg callable structures, BrokerTec depth); **no ARBS coverage measured for any of them.** Highest-value single addition if one source is ever added: the Jan-2020 fair-value regression `10y swap spread ~ f(bank convexity duration, 3m GC/OIS)`. The only curve-only proxies available today are the **10s20s30s fly** (the ALM/20y bid) and Citi's **2y30y vol vs 20y5y−10y10y** pair.

### 3.3 "RISK-ADJUSTED CARRY" — five distinct definitions, not interchangeable

W4 names this as the dominant driver. **Pick one and say which.**

| id | definition | verification |
|---|---|---|
| **RAC-1** (Citi, 4 vintages) | `daily_BE_bp ÷ 1y-trailing daily realized bp vol of the **BACK** forward rate`; `BE ≡ 0` whenever carry ≥ 0 | **Reproduces 10/10 rows (06/2023) and 15/15 rows (12/2019).** The back-leg keying is **verified twice independently**: the vol row takes exactly 6 distinct values keyed to the back leg, repeating across every pair sharing it. Keying it to the curve or the front leg reproduces neither table. **Polarity is opposite for the two sides**: LOW is attractive for a flattener (exit at 0.8), HIGH for a steepener ("meaningfully above 1", entries at 1.17/1.38). |
| **RAC-2** (JPM) | `(3M carry + slide + convexity, bp) ÷ (3M realised daily bp vol × √252)` | **Verified 4/4 exactly.** ⚠️ **CAPTION TRAP**: Exhibit 12 is captioned *"Annualised 3M expected return divided by annualised expected volatility"*, but the verified arithmetic uses the **raw 3M** numerator. Implementing from the caption gives a value **4× too large.** |
| **RAC-3** (Citi fwd-vol) | ex-ante Sharpe = 3m roll ÷ ⟨vol-adjustment⟩; value = 1y z-score of σ_fwd | σ_fwd formula **verified exactly** (106.15 vs printed 106.1). **The Sharpe denominator is NOT PRINTED** — back-solves to 6.3-20.4 across 20 rows. Reproduce the *level and ordering*, never the Sharpe. |
| **RAC-4** (CA screens) | per-pack `3m Roll (short cvx, bp)` + `Implied/Realized` vol ratio | The published per-pack risk-adjusted metric. **Needs only the CA panel — this is W2b's risk-adjusted signal.** |
| **RAC-5** (2010 fly) | `target = (current − model) − convexity_cost` = 28 − 8 = 20 bp, stop 10 bp | The only note that treats convexity as a **cost that shrinks the target** rather than a signal. |

### 3.4 CONSOLIDATED TIE-OUT TABLE (decision-grade subset)

Status: **VERIFIED** = re-derived arithmetically and matches · **PRINTED** = published, no independent check · **DIFF** = re-derivation disagrees · **CHART** = read off a chart. The full 143-row inventory is in the two `newdocs-*` scout reports; this is the subset that grades W1-W4.

| # | source | date | quantity | value | status | grades |
|---|---|---|---|---|---|---|
| 1 | Citi Fig 58 | close 6/9/23 | **13-row SOFR pack CA screen** M4-H5…M7-H8 (CA/model/vs-model/roll/impl/rlzd) | M4-H5 4.03 → M7-H8 22.29 bp | PRINTED | **W1, W2b — already the repo anchor; now also grades `IRSwapValue.CVX_ADJ`** |
| 2 | Citi Fig 57 | close 1/11/19 | 17-row **ED** pack CA screen H9-Z9…H3-Z3 | 0.06 → 7.44 bp | PRINTED | W1 (second vintage) |
| 3 | Citi Fig 5/54 | close 1/5/18 | 17-row ED pack CA screen, 12 columns | H1-Z1 CA 7.13, vsMdl 4.26, IV 105.4, RV 50.4 | PRINTED | W1, W2b |
| 4 | Citi Fig 53 | close 5/12/17 | 17-row ED pack CA screen | M9-H0 CA 4.91, vsMdl 3.43, 1Y-Z 1.48 | PRINTED | W1, W2b |
| 5 | Citi Blues | 1/5/18 | ED6/ED16 DV01 weights vs 130/176 | 0.74 vs **0.7386** | **VERIFIED** | W2b hedge |
| 6 | Citi Greens | 5/15/17 | ED5/ED9 weights vs 167/141 | −1/1.18 vs **1.1844** | **VERIFIED** | W2b hedge |
| 7 | Citi Greens | 5/15/17 | CA model regression | `−3.53·ED5 + 4.17·ED9` (ED in **%**, printed) | PRINTED | W2b |
| 8 | Citi Blues | Jan-99→17 | CA model regression | `−0.65 + 0.044·(ED16 − 0.74·ED6)` (ED units **inferred bp**) | PRINTED | W2b |
| 9 | Citi Blues Fig 4 | 1/13→12/17 | **Δ CA-vs-model on Δ dealer positioning** | **y = 2E-06x − 0.1053, R² = 0.2724** | PRINTED | **W2b positioning enrichment** |
| 10 | Citi TurnGreen | 6/6/17 | Greens **target / stop** on $300K DV01 | **+$450,000 / −$225,000 = +1.50 / −0.75 bp** | PRINTED | **W2b exit rule** |
| 11 | Citi TakeOffHedge | 7/13/17 | CA leg MTM `(4.3−3.35)×$300,000` | **$285,000** | **VERIFIED (exact)** | W2b |
| 12 | Citi TakeOffHedge | 7/13/17 | Hedge unwind P&L | **+$70,500** | **VERIFIED — only with INITIATION quantities; the alert's printed legs are transposed (+$33,450)** | W2b |
| 13 | Citi LeftSide | 6/11/21 | Blues ticket: 1000 EDM4-H5 vs $1.01bn CME @ **7.9 bp**, $100K DV01; carry **+1.2 bp/3M**; **target 4 bp, stop 3 bp** | — | PRINTED | **W2b — the only in-window CA ticket** |
| 14 | Citi TurnGreen | 6/6/17 | Blues package **net P&L, net transaction costs** | **+$500,000** (gross CA leg $440,000 ✓) | PRINTED / VERIFIED | W2b costs |
| 15 | JPM | 5/3/17 | Ho-Lee financing bias closed form | **`A_cvx = σ²T₁T₂/2`** | PRINTED | W1 model |
| 16 | *my check* | 1/5/18 | JPM form vs Citi implied-vol column | Blues σ back-out 102.1 vs printed 105.4 (~3%); Greens 90.6 vs 96.1 (~6%) | **±5% SANITY BAND ONLY — do not assert equality** | W1 |
| 17 | CME | Jun-25 | 2y IMM OIS par coupon from the 8-contract strip | **3.3304%** | PRINTED | **W1 tie-out cell** |
| 18 | CME | Jun-25 | bundle price = arithmetic mean of 8 prices | **96.675625** | **VERIFIED** | W1 |
| 19 | CME | Jun-25 | hedge vector / total vs swap DV01 | `100,99,99,98,97,96,95,95 = 779`; $19,480.69 vs $19,475 | **VERIFIED** | W1 |
| 20 | CME | Jun-25 | convexity P&L, 8 scenarios | −100→$22,292 · −50→$5,638 · +50→$5,241 · +100→$21,226 | **VERIFIED 8/8** | **W1 kernel** |
| 21 | CME | Jun-25 | gamma identity `18×0.5×100×$25` | $22,500 vs $22,292 (diff $208) | **VERIFIED** | W1 |
| 22 | CME | Jun-25 | margin: futures / swap / portfolio-margined / reduction | $569,910 / $1,568,352 / **$46,161** / **97.84%** | **VERIFIED** | W2b cost & IM story |
| 23 | CME | Jun-25 | MM edge / bundle slippage / net | **0.29 / 0.1875 / ~0.1 bp** | **VERIFIED** | **W2b cost benchmark** |
| 24 | Clarus/ICAP | 18-May-15 | CME-LCH term structure 1Y-30Y | 30Y **+1.90 bp** | PRINTED | W2b basis validation |
| 25 | Clarus/Tradition | 26-Jun-17 | CME-LCH term structure 1Y-50Y | 30Y **+3.40 bp** | PRINTED | W2b |
| 26 | Clarus Arb | 17-Jun-15 | 5Y basis gross edge / after fees | $62,500 → **"just over $45,000"**; verdict *"isn't going to work"* | VERIFIED / PRINTED | **W2b cost realism** |
| 27 | Clarus Dummies | Jun-17 | MVA bp column vs MVA/DV01 | printed 1.30/2.10/**3.40** vs computed 1.257/1.972/**3.229** | **DIFF — do not use MVA/DV01 as the identity** | W2b |
| 28 | JPM | 5/1/17 | front-end CME/LCH basis | **"well under 1 bp, mostly ~0.25 bp"** | PRINTED | **W2b — bounds the basis's explanatory power for SR3 CA** |
| 29 | QSE / Attack68 | 6/14/25 | rateslib `CompositeCurve` implied convexity, 12 monthly contracts | **0.387 → 1.317 bp**, all inputs printed | PRINTED — **directly reproducible; rateslib 2.0 vs repo 2.7.1** | W1 |
| 30 | Citi Fig 5 | close 6/8/23 | **10-column steepener screen, BE/realized-vol row** | 1.17 / 1.38 / 1.12 / 1.03 / 0.86 / 0.85 / 1.29 / 0.90 / 0.77 / 0.49 | **ARITHMETIC-VERIFIED 10/10; back-leg vol keying verified** | **W3, W4** |
| 31 | Citi Fig 1 | close 12/4/19 | 15-column flattener screen | 15y5y/20y10y: curve −12.54, carry −2.09, BE 3.33, vol 4.16, **BE/vol 0.80** | **VERIFIED 15/15**; column mapping confirmed by body text | **W4** |
| 32 | Citi Fig 11 | close 1/16/20 | 5-currency screen | GBP 15y10y/25y10y: −10.37, carry **+0.52**, BE **0.00** | **VERIFIED** | W4 |
| 33 | Citi Fig 9 | 3pm 3/26/20 | USD screen at COVID vol | 15y5y/20y10y −5.21, carry +0.11, BE 0.00, **1y rlzd vol 6.40 bp/day** (vs 4.2 in Jan) | **VERIFIED** | W4 |
| 34 | JPM Ex.2 | 2/9/18 | **RAC, 4 OATs** | 0.33 / 0.32 / 0.30 / 0.25 | **VERIFIED 4/4; √252 unique among {250,252,260}** | **W4 primary metric** |
| 35 | JPM | 2/9/18 | flattener-vs-1Yx30Y-straddle hit rates | **56% (30s/50s), 86% (25Y/20Yx5Y)** | PRINTED | W3 |
| 36 | Citi | 12/5/19 | flattener P&L: gross vs net | **+$187K → +$155K** on $50K DV01 ⇒ **round-trip ≈ $32K incl. all resizes** | PRINTED | **W3/W4 cost calibration** |
| 37 | Citi | 3/26/20 | GBP flattener close-out **P&L decomposition** | **445K = 115K curve + 330K convexity (74% convexity)** | PRINTED (115+330=445 ✓) | **W3 — the attribution to reproduce** |
| 38 | Citi | 3/30/20 | bid/offer, 10y swaps | **mid-to-bid ≈ 0.6 bp** | PRINTED | W3/W4 costs |
| 39 | Citi Fig 22 | 6/9/23 | forward-vol triangle `1y2y1y` | σ_f = **106.1** (computed 106.15) | **VERIFIED** | W3 |
| 40 | JPM Ex.7 | 4/7/21 | beta-stability grid, 12 triggers × 3 regimes | best avg **1.3 bp/trade**, success 52-55%, critical-period avg 0.5 → −0.1 | PRINTED — **EUR, method-only translation** | W4 |
| 41 | JPM | 4/7/21 | traffic light `√(Zb²+Zw²)`, threshold **3** | all-P&L R² **0%**; conditioned-on-negative R² **17%** | PRINTED | **W4 — predicts the loss tail only, not returns. State this.** |
| 42 | Citi | 12/20/10 | 1y-fwd 5s10s30s ticket, Σdelta / predicted fly | 198 ✓ ; `9%·6+21%·10+70%·24 = 19.4 → 19` ✓ | **VERIFIED** | W4 |
| 43 | Aikin | summer-13 | **Euribor convexity bias went NEGATIVE** | — | PRINTED | **W1 — falsifies any model that floors CA at 0** |

---

## 4. FEASIBILITY VERDICT PER WORKFLOW

### W1 — Fix SFR convexity-adjustment DATA for Whites/Reds/Greens/Blues/Golds
**🟢 FEASIBLE. Roughly half the code is already landed; the rest is one bounded warm, one panel rebuild, and one re-baseline.**

| deciding measurement | consequence |
|---|---|
| Whites 100.0% / Reds 99.9% / Greens 97.8% over 2021-2026 | **Three of five bands need no fetch at all.** |
| Blues 80.8%, Golds 66.1%; hole is **2021-2023** | 787 servable dates / 2,698 cells at depth 20. |
| **Vendor serves pre-2024 deferred settles** (2 probes, both `resolved=True`, both wrote the NY 17:00 alias) | The 2021-2023 plan is viable — this was the open question. |
| Golds gate 41/20/0 in the only extant panel, built without `db95871d` | **The panel rebuild is the largest single coverage win and costs zero network.** Sample median 2.86→1.05 bp, pass 6/15→15/15. |
| `50e5fb29` landed 3 CA-path defects + a look-ahead `bfill` | **W1's correctness half is done and graded (14/14 tests, 3.81 s).** |
| The commit changes the `value_kwargs` → `_query_fingerprint` → cache-symbol chain | **Every previously cached `sfr_cvx_adj` row is orphaned by design. A fresh CA-timeseries backfill is a W1 deliverable line item, not an optional extra.** |

**Two decisions the builder must make explicitly, not discover:**
1. **`--protect-min-depth 21`.** The default is 12 precisely so a repair moves no published `ca_bp_q20`. The brief says *fully fix*, so it must be raised — 2022 sits at depths 14-18 and 2023 at 10-14, so re-solving those curves **will** move published values.
2. **The `published_values_moved: 0` invariant is impossible and must be retired.** Both remaining streams move values by design: the warm deepens existing dates, and `db95871d` moves ranks 15-17 (c16 ≤0.307, c17 ≤0.832, c18 ≤1.701, c19 ≤2.833, c20 ≤4.411 bp; ranks 1-14 pooled delta exactly 0.0000). The deliverable is a **quantified before/after diff against `_baseline_prewarm/`**, not a no-change assertion.

**Do not use `ca_coverage_repair.ipynb` as-is.** Its `end` is pinned at 2026-08-18 (`ca_coverage_repair.py:86`), its remaining-work block filters `d.year >= 2024` (`:770-775`), and its `resume_command` is `--start 2024-01-01`. **It is structurally incapable of seeing the 2018-2023 gap, which is now the entire gap.** Reuse its machinery (ledger-based code-vs-fetch attribution, `trim_to_contiguous_run`, `assert_settle_source`, the Citi Fig-58 tie-out at `:777-800`); repoint its window.

### W2a — Intraday CA pricer objects, timeseries, and `IRSwapQuery` support
**🟢 FEASIBLE. The hard question is already answered by measurement.**

The decisive fact: a full intraday `CVX_ADJ` was computed at 2026-08-19 15:00 ET in **0.47 s with 0 network attempts**, through the identical inner loop as `sfr_cvx_adj` (`resolve_package(is_for_timeseries=True)` → `build_value_map` → `apply(CVX_ADJ, sfr=[...])`), with the swap leg from `CITIVELO_EXCEL` minute store under `SnapshotPolicy.strict(minutes=5, on_miss="raise")` and the futures leg from the `BARCHART_TOS_LIVE` minute tape. **Both sources are warm and the plumbing works.** `50e5fb29` already fixed the *value*; W2a is now purely a **time-axis** problem.

**Remaining work, all small and all still live at HEAD:**
- `IRSwapQuery.build_mdp_request` (`:268-279`) **date-truncates for every value except `CVX_ADJ_EMPIRICAL`.** Generalise `_uses_empirical_convexity_adjustment` to a membership test over a value *set* including `CVX_ADJ` — which also repairs the list-valued-`value` case (`==` fails today).
- `return_query()` (`:305-320`) **drops `value_kwargs`** — and `value_kwargs` is now load-bearing (it carries `matched_frequency`).
- **`sfr` must stay a runtime object.** Transport a declarative `sfr_spec` (JSON-canonicalisable, fingerprint-safe) and resolve it to `rl.STIRFuture` at the call site. Do not serialise the object.
- New `TB/IRSwapsTB.sfr_cvx_adj_intraday(...)` **beside** `sfr_cvx_adj`, not a modification of it (179 cached rows of key/column semantics to preserve). Per-instant curve cache via `bulk_get_data(timestamps=[...])`; `STIRFutureMDP` prices instead of `get_barchart_timeseries`; **drop the `_is_today` write gate** (`:1564,1617`) — it skips exactly the data an intraday run produces.
- Contract picking must use the **instant's Chicago trading date** (17:00 roll), not `ts.date()` — the current code is off by one contract for the evening session on roll days.
- Return **two lag columns** (`curve_lag_s`, `futures_lag_s`) alongside the value, or the CA is unfalsifiable.

**⚠️ Hard scope limit: the minute curve store starts 2021-09-14.** Intraday cannot reach 2021-01. Say so in the deliverable.

### W2b — CA vs swap fly, QueryDrivenBacktest, 2021-2026, enriched signal
**🟠 FEASIBLE for the backtest structure; PARTIAL for the enrichment.**

| leg | verdict | deciding measurement |
|---|---|---|
| **Backtest skeleton** | 🟢 | `RVUtils/ConvexityRV/strat2_sofr_convexity.py` (1,812 lines) already wires plan→run→assert end-to-end, with 3 live sign probes, `assert_ran` (mandatory — `bt.run()` swallows exceptions), and a results doc `strat2-sofr-convexity-vs-fly.md`. `strat2_fly_universe.py` and `strat2_grid.py` exist. **Do not rebuild this.** |
| **CA panel 2021-2026** | 🟠 → 🟢 after W1 | Golds 66.1%, Blues 80.8%, hole 2021-2023. **A Golds-selecting screen cannot select Golds on days it is not priced** → selection bias toward shallower packs in 2022-2023. Real hazard; name it or fix it with W1. |
| **Open interest** | 🔴 per-contract / 🟠 via proxy | Survivorship-dead pre-~2024. **Substitute: CFTC TFF `Open_Interest_All` for SOFR-3M (weekly, 2020-01-07→2026-05-12, contiguous across the Feb-2022 rename).** Whole-strip, no contract dimension. |
| **CME-LCH basis** | 🟢 available, 🟠 **weak explanatory power expected** | Live-verified at −2.00/−2.05 bp on USD SOFR 10y. **But JPM measured the front-end basis at "well under 1 bp, mostly ~0.25 bp"** — and SR3 pack CA lives ≤5y. The mechanism JPM names is **IM non-nettability**, not the basis level. Include it, but pre-register the expectation that it explains little, and do not let a null result be read as a data failure. History depth **NOT MEASURED**. |
| **Dealer positioning** | 🟠 | CFTC TFF dealer columns are on disk and fully populated; `build_positioning_panel` needs one added metric (`dealer_net`) and `_CONTRACT_MAP` needs `SOFR-3M` / `3-MONTH SOFR` added. **14 weeks stale; refresh requires deleting the parquet** (unconditional short-circuit). |
| **Risk-adjusted signal** | 🟢 | **RAC-4** (`3m Roll (short cvx)` + `Implied/Realized`) is the published per-pack risk-adjusted metric and needs only the panel. Citi's Jun-2021 selection rule is explicit: Blues beat the more-dislocated Golds on **higher roll and higher CA-implied vol vs its own range**. |

### W3 — CA vs ultra-long curves as a vol RV trade
**🟠 FEASIBLE, but it depends on W1 for the CA leg.**

Both legs are long/short-vol expressions and both are already scaffolded: the ultra-long side has `strat1_curve_gamma.py`, `strat1_longend_listed.py`, `strat1_threeway.py`, `strat3_strikeless_vol.py` plus 5 results docs; the CA side has strat2. The ultra-long data is 🟢 **unconditionally** (7/7 tenors × 9/9 dates, 1,466/1,470 bdays, cube 99.4%). **The CA leg is the constraint** — the vol content lives in Blues/Golds, which are 80.8%/66.1% covered with a 2021-2023 hole. Whites/Reds carry almost no CA and will not express the trade.

Citi's *Forward steepener and vol divergence* (12-Jun-2023) is the natural spine: **it carries both the ultra-long BE/realized-vol frontier and the 13-row SOFR CA screen in one note**, and explicitly proposes shorting Blues CA *"as a short vol proxy"* against the forward steepener. The P&L attribution to reproduce is Citi's own: **74% convexity / 26% curve** on the GBP close-out.

### W4 — Ultra-long curve trades vs swap fly, risk-adjusted carry dominant
**🟢 FULLY FEASIBLE NOW, AND COMPLETELY INDEPENDENT OF W1/W2a. This is the one to start immediately.**

Every input is the swap curve plus the ATMF cube, both 🟢 for the whole window and both in diskcache directories (`IRSwapsTB_v2_CITIVELO_EXCEL`, `citivelo_par_extract`) that are **separate from `STIRFuturePricer_Cache`** — verified in preflight §5 trap 7 — so **W4 can run concurrently with the W1 warm without shard contention.**

It also has the strongest published grading battery: **RAC-1 reproduces 10/10 and 15/15 on two independent screens** with the back-leg vol keying verified twice, and **RAC-2 reproduces 4/4 exactly**. And it directly attacks the codebase's own measured defect — `frac_always_cheap` 86.0/40.7/34.2% is *"a permanently-on flattener, not a timing rule"*, and BE/realized-vol is a two-sided rule that flips at a printed threshold with four dated Citi decisions across it, including one **liquidity veto on a triggering signal** (26-Mar-2020).

---

## 5. PROPOSED IMPLEMENTATION ORDER

```
                         ┌──────────────────────────────────────┐
  W1.a  shared CA path ──┤ DONE — 50e5fb29, 14/14 tests, 3.81 s │
                         └──────────────────────────────────────┘
  ─────────────────────────────── wall-clock critical path ───────────────────────────────
  W1.b  SR3 warm  ──────────────────────────► W1.c  panel rebuild ──► W1.d  re-baseline
   (1.5-7.5 h, blocks SR3 panel builds)         (zero network)          vs _baseline_prewarm
        │                                              │
        │  (runs concurrently — separate caches)       ├──────────────► W2b (CA leg)
        ▼                                              └──────────────► W3  (CA leg)
  W4  ultra-long vs fly  ──────────────────────────────────────────► (independent, ships first)
                                                  W2a intraday ──────► live screeners (W2b, W3)
```

| step | why here | blocks / blocked by |
|---|---|---|
| **0. Fix `Q12STIRT` / `Q16STIRT` `max_tenor` (39→45, 51→57)** | 30 seconds of work; these are the curves the **nightly warmer builds into the production store**, so every night of delay bakes more bad curve into a shared cache. Independent of everything. | nothing |
| **1. Kick off the SR3 warm FIRST** | It is the only wall-clock-bound item (1.5-7.5 h) and it is the **only step that blocks other work** — it writes `STIRFuturePricer_Cache`, and a panel build reading the same shards inside `cache_only()` turns contention into an exception. Start it, then do something else. Set `--protect-min-depth 21`, `--start 2020-01-01` (skip the 85 pre-listing 2018 dates that would burn ~1,700 cells against a vendor that has nothing). Resumable ledger. | blocks W1.c, W2b/W3 panel builds |
| **2. W4 — ultra-long vs swap fly, RAC-1/RAC-2** | **Runs concurrently with step 1** on verified-separate caches. Zero dependency on W1 or W2a. Strongest tie-out battery (10/10, 15/15, 4/4). Attacks a *known* measured defect rather than opening a new front. Ships a complete deliverable while the warm burns. | ⊥ everything |
| **3. W1.c panel rebuild + W1.d re-baseline** | After the warm. **One** rebuild captures both `db95871d` (code) and the new depth (fetch) — and `ca_coverage_repair.py` already attributes recovered (date,rank) pairs to code-vs-fetch from the warm's own ledger, so a single rebuild still separates the two effects. Deliver the quantified before/after diff, not a no-change assertion. Backfill the orphaned `sfr_cvx_adj` cache. | blocked by 1; blocks 5, 6 |
| **4. W2a intraday** | Small, well-scoped, and now purely a time-axis problem. Can start any time after step 1 begins (it touches `Query`/`TB`, not the SR3 shards). Needed only by the **live screeners**, not by the backtests. | ⊥ 1,3; blocks screeners |
| **5. W2b — CA vs swap fly backtest + live screener** | Needs the rebuilt panel (3) for its CA leg and W2a (4) only for its *screener*. **The backtest itself can be EOD.** Build on `strat2_sofr_convexity.py` + `strat2_fly_universe.py`; add Citi's target/stop (+4 bp / −3 bp) and RAC-4; enrich with CFTC weekly. | blocked by 3 (backtest), 4 (screener) |
| **6. W3 — CA vs ultra-long as vol RV** | Last: it is the only workflow needing **both** a repaired CA panel *and* the ultra-long machinery, so it profits from W4's and W2b's plumbing being settled. Spine is Citi 12-Jun-2023, which carries both sides. | blocked by 3, and by W4's signal code |

---

## 6. RISK REGISTER

### 6.1 Carried forward from the committed preflight (all still live)
| # | landmine | mitigation |
|---|---|---|
| 1 | **A cached artifact fakes a successful re-run.** Several notebooks do `if _F.exists(): X = pd.read_parquet(_F)`. | Every new notebook gets `FORCE_REBUILD` that unlinks its own outputs first. The Aug-19 baseline is parked at `_baseline_prewarm/` so it can never be picked up by that pattern. |
| 2 | **`QueryDrivenBacktest.run()` swallows exceptions and prints them** — a failing backtest is indistinguishable from a flat equity curve. | Copy `strat2_sofr_convexity.assert_ran` (`:1772`): `len(specs)>0` (an empty plan is a *planning* failure), `mtm_history` non-empty, `len(eq)==expect_days`, `eq.abs().max()>0`, `len(closed_positions_log) >= legs_per_epoch × n_epochs`. |
| 3 | **`rateslib.Curve.translate()` cannot age a struck swap** (`HorizonAgeingUnsupported`). | Convexity is the *shape*, carry is the *level*. Pass `carry_ccy = package_carry_roll_bp(...) × package_dv01` into `payoff_profile`. |
| 4 | **`GAMMA_01` / `DV01` raise `NotImplementedError`** on the rateslib backend. | Reprice on a shifted curve (`pricer._rl_curve_handle.shift(bp)`), never differentiate. |
| 5 | **Parallel `conda run` collide on a temp file → empty output, exit 0 (a fake pass).** | Call `C:/Users/chris/anaconda3/envs/stir/python.exe` directly, always. |
| 6 | **`IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name":"USD-SOFR-1D-Q20STIRT"})` = 52-57 HTTP requests per date**, and `offline=True` is accepted then ignored. | Never call it. Gate with `ignore_cache_miss=True` (returns `None`, `IRSwapsMDP.py:2693-2694`) or a direct `store.read_raw_nodes` probe. |
| 7 | **The warm writes `STIRFuturePricer_Cache`; a concurrent panel build inside `cache_only()` turns shard contention into an exception.** | Sequence per §5. Verified safe to run pure-swap-curve work concurrently (`IRSwapsTB_v2_CITIVELO_EXCEL`, `citivelo_par_extract` are separate dirs). |

### 6.2 New, from this synthesis
| # | landmine | evidence | mitigation |
|---|---|---|---|
| 8 | **THE WORKTREE IS UNDER CONCURRENT MODIFICATION.** HEAD moved twice during synthesis; `50e5fb29` landed *between two of my tool calls*, and a `git diff TB/IRSwapsTB.py` that returned 84 changed lines returned empty ~90 s later. | measured | **Re-check `git -C ... log --oneline -1` and `status --porcelain` immediately before any edit.** Never assume a diff you read is still the diff on disk. |
| 9 | **The committed preflight's §3 coverage CSV is stale ~10× for 2024-2026** and will send a builder to warm dates that are already at depth 20. | CSV r17 = 19/2/103 vs shipped gate 248/247/156; **the doc's own dry-run (4/4/3 dates short) contradicts it.** | Use §2.2 of this report. Delete or re-stamp `ca_coverage_by_rank.csv`. |
| 10 | **A shortlist in circulation states the deep-pack hole backwards** ("Blues/Golds unavailable after 2023"). | §0/A2 | The hole is **2021-2023**. |
| 11 | **`50e5fb29` orphans every cached `sfr_cvx_adj` row by design** (convention travels in `value_kwargs` → `_query_fingerprint` → cache symbol). | commit message | Budget a fresh CA-timeseries backfill as a W1 deliverable. This is correct behaviour — orphaning beats silently serving old-convention rows — but it is not free. |
| 12 | **`IRSwapQuery.build_mdp_request` silently date-truncates `CVX_ADJ`.** An "intraday" request returns an EOD number with no error and no metadata saying so. | `IRSwapQuery.py:268-279`, `BaseQuery.py:12-21` | W2a item 1. Until fixed, do not route intraday CA through the query layer. |
| 13 | **`STIRConvexityAdjustmentMDP`'s default `source_b` (`ERIS_EOD_LIVE-RL_BASIC-NOJUMPS`) silently `.date()`-truncates a datetime** (`IRSwapsMDP.py:2142-2143`) → intraday leg A vs EOD leg B, no warning. | measured (code) | Raise instead of truncate, or change the default. |
| 14 | **The SR3 minute tape is keyed under `BARCHART_TOS_LIVE_STIRF-RL` and is invisible to `BARCHART_STIRF-RL` lookups** — `src` is part of the cache key. A "cached" intraday request under the wrong source silently fetches. | `STIRFutureMDP.py:1018,1072`; probe had to fall through namespaces | Pin the futures source explicitly in the intraday pricer config; assert the served stamp. |
| 15 | **Exact midnight resolves to END OF DAY, not to the instant** (`IRSwapsMDP.py:3101-3105, 3224-3238`). | measured (code) | Ask for `00:00:01`. |
| 16 | **`SnapshotPolicy.legacy()` — the DEFAULT — is nearest-in-either-direction with unbounded lag, so it can serve a curve stamped AFTER the request.** Look-ahead by default. | `snapshot_policy.py:93-106,120-122` | Research callers must pass `.strict(minutes=N, allow_future=False, on_miss="raise")`. |
| 17 | **A cold `CITIVELO_EXCEL` EOD day falls through to a LIVE EXCEL COM BUILD** (`IRSwapsMDP.py:2899-2912`), and `snapshot_policy` does **not** protect an EOD request (`_assert_policy_mode` refuses a minute policy on a non-intraday request). | measured (code) | **Enumerate on-disk partitions first and request only dates that exist.** Confirm with `pricer.meta()["from_curve_store"] is True`. Never pass `force_refresh`/`ignore_cache`/`no_curve_store`. |
| 18 | **`_is_today` write gate means an intraday series for today computes and persists nothing** (`IRSwapsTB.py:1564,1617`). | measured (code) | Replace with "write if the served instant is more than N minutes old". |
| 19 | **`warm_sr3_settles._depth_by_date` is blind to exactly the dates the job exists to fill.** It never passes `min_depth`, so `before[d] = 0` for any date under depth 4 and a genuine 2→3 gain fails the `depth_gained` acceptance test. The ledger recorded **213 dates at depth 0-3 before the warm** — this is the common case. | synthetic-shard probe: depth-2 date **not visible** | Use `warm_sr3_deferred` (which passes `min_depth=1` explicitly, `:165`) for the repair. Fix `warm_sr3_settles` before relying on the scheduled job. |
| 20 | **The test guarding #19 never calls the function it names.** `test_depth_by_date_sees_dates_a_floored_config_hides` asserts on `strip_depth_by_date` directly (`:84-86`), never on `W._depth_by_date`. It passes while the function is blind. | measured | Rewrite the test behaviourally. (Precedent: `50e5fb29` hit the same class of failure twice under mutation testing — *"the swallow mutation survived a source-text assertion."*) |
| 21 | **`warm_sr3_settles` has no `d >= today` guard** and runs at ~18:17 ET, while `warm_sr3_deferred` and the diagnosis doc state the opposite doctrine (warming a date during its own session *"stamps an intraday print with a settlement key"*). The two jobs disagree. | measured (code); **impact NOT measured — the job has never run** | Add the guard before the job's first scheduled run. |
| 22 | **CFTC TFF is stamped by REPORT date (Tuesday) but released Friday 15:30 ET; `build_positioning_panel` daily-ffills.** Using report date as the signal date is ~3 days of look-ahead. | **NOT MEASURED in this repo — flagged from the release convention.** | **Verify and lag before any positioning-enriched backtest result is believed.** Precedent: `50e5fb29` just removed a `bfill` look-ahead from the price panel for the same reason. |
| 23 | **Weekly signal, daily panel, monthly rebalance.** CFTC is weekly; the CA panel is daily; strat2 rebalances `BMS`. | — | The monthly rebalance absorbs this cleanly — but state the alignment rule rather than letting ffill decide it. |
| 24 | **CFTC cache cannot self-refresh** and is 14 weeks stale. | `cftc_positioning.py:51-52` | Delete the parquet to refresh, or add a max-age check. A 2021-2026 backtest ending 2026-05-12 on the positioning leg must say so. |
| 25 | **`IRSwapClearingHouseBasisSwapsMDP` has no cache and hardcodes the primary checkout's path.** | no `GSQUANT_CH_BASIS` dir; `:34` | Add a diskcache layer before any multi-year pull; repoint `coverage_path`. |
| 26 | **Hardcoded live gs_quant credentials in the repo.** | `gs_quant_fetcher.py:7-8`, auth succeeded on them | Rotate and move to env. Report to the user regardless of workflow. |
| 27 | **`_query_fingerprint` includes `value_kwargs` only when non-empty**, and `return_query()` drops `value_kwargs` entirely. Adding or losing a kwarg silently changes or corrupts the cache symbol. | `IRSwapsTB.py:68-71`; `IRSwapQuery.py:305-320` | Fix `return_query`; treat any `value_kwargs` change as a cache-version event. |
| 28 | **`structure_kwargs["risk_weights"]` is MUTATED IN PLACE** by `_build_fly`. | strat2 sign probe asserts this explicitly | Construct a fresh list per query. |
| 29 | **`plan()`'s `est_seconds` is ~11× optimistic on the slope and is printed to the operator as the headline budget.** | `corr(seconds, cells) = 0.144` | Budget on the ledger's distribution, not the model. |
| 30 | **`plan()` schedules 85 dates before SR3 existed** (2018-01-02..2018-05-03, first key 2018-05-04) — ~1,700 cells burned against a vendor with nothing. | measured | `--start 2020-01-01`, or add a launch-date floor. |
| 31 | **`docs/convexityrv/ca_coverage_diagnosis.md:1256-1265` still carries the explanation `db95871d` refuted** (Golds as an "edge-of-calibration effect" needing a curve past rank 17). It is a node-grid defect fixed by one number. | measured | Correct the doc, or a future reader re-derives the wrong fix. |
| 32 | **`db95871d`'s SCOPE paragraph contradicts its own diff** (claims the override is in `build_q20_pricer`; the diff edits `_STIRF_CURVE_CONFIGS`). Blast radius is nil today, but the statement on record is false. | measured | Note it; do not rely on the paragraph. |
| 33 | **`plotly` figures do not survive `nbconvert --execute`** without `pio.renderers.default = "plotly_mimetype+notebook_connected"`, and `_verify_nb.py` counts only `image/png` — a plotly-only notebook correctly verifies as "0 figures". | measured | Set the renderer; do not read "0 figures" as a failure. |
| 34 | **`_verify_nb.py` globs relative to CWD** — must be invoked with `cwd` = the notebook's directory. The FOMC template also hardcodes `REPO = r"C:\Users\chris\clee\ARBS-gcb"` — a *different* worktree. | measured | Repoint before copying the template. |
| 35 | **`trade_dashboard`: `span_years` is the ONLY annualisation input** and its absence silently drops annualised Sharpe; `bar_width` is in **milliseconds** and a dense book draws 1-pixel bars without it. | measured | Always pass both explicitly. |
| 36 | **`build_rl_stirf`'s SFR branch has `**rate_fixings_kwargs(fixings)` commented out** (`stir_curve_building_utils.py:521`) — harmless while only `fixed_rate` is read, fatal if anyone prices that STIRFuture mid-accrual. | measured | Leave the CA path reading `fixed_rate` only, or restore the fixings. |
| 37 | **A boundary/threshold signal at the edge of a fitted curve is confounded with the fit.** RAC-1's `BE ≡ 0` truncation on positive carry is exactly such a boundary, and it is the condition Citi calls *"a free convexity buy"* — i.e. the entry trigger sits **on** the boundary. | repo memory: matched-rarity placebos gave \|t\| up to 2.4 from nothing | Run matched-rarity placebos on the BE=0 trigger before believing any W4 result. |
| 38 | **Research bugs flatter the hypothesis.** 12/12 post-hoc defects in this repo's history favoured the thesis. | repo memory | Every W2b/W3/W4 result gets a negative control that must fail, mutation testing on the signal code, and the deflated-Sharpe / trial-count section of the FOMC template. `50e5fb29`'s mutation harness caught two survivors on the first draft — reuse it. |

---

## 7. EXPLICITLY NOT MEASURED

1. Whether Barchart `queryeod` serves OI for **expired** contracts — decides whether the pre-2025 per-contract OI hole is backfillable. Path: `BarchartFetcher.barchart_timeseries_api(merge_val_col="Open Interest")`, ~1 request/contract.
2. **gs_quant actual served history depth.** 2018-04-27 is a catalogue claim from a Dec-2025 xlsx; only a 4-business-day live window was read.
3. Why **2026-08-12** is absent from that 5-business-day gs_quant window.
4. `SDRUtils/dealer_direction` coverage window — remote-only source, not queried under `ARBS_SUPABASE_ENABLED=0`.
5. **Whether tonight's 18:15 cache-warmer run (still executing at 23:32) picked up the SR3 settle job.** Evidence says no — main reached the primary checkout 5 h after that process started — but the log was not re-read after completion.
6. The **CA impact** of the `max_tenor` over-shoot on shallow dates (D2). The rule violation is measured — 785/2,097 dates (37.4%) run 9-13 nodes past their last calibration instrument — but the resulting bp error is not; the 2.0 bp settle-agreement gate bounds it per row.
7. The **full 2,097-date** effect of `db95871d`. The 15-date sample and `db95871d`'s own 963-date table both point one way; do not extrapolate to "all 1,312 Golds dates" without the rebuild.
8. `IRSwapsTB_v2_STIRCVX_EMPIRICAL` is `len=0` — the empirical-CA path has **never been exercised end-to-end** outside tests.
9. Citi's exact Ho-Lee convention. `σ²T₁T₂/2` recovers Citi's implied-vol column to ~3% (Blues) / ~6% (Greens) but not exactly. **Use it as a ±5% sanity band, never as an equality tie-out.**
10. Citi's RAC-1 `daily_BE` functional form. Column-ratio arithmetic is consistent with `BE = √(2·carry_daily/Γ)`, but this is **inferred, not printed**.
11. Citi's RAC-3 ex-ante-Sharpe denominator (back-solves to 6.3-20.4 across 20 rows). Reproduce level and ordering only.
