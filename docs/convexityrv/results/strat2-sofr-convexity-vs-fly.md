**FILES WRITTEN** (all absolute)
- `C:/Users/chris/clee/ARBS-cvx/RVUtils/ConvexityRV/strat2_sofr_convexity.py` — `Strat2Config` (every knob documented inline), `pack_windows`, `ca_snapshot`, `fit_sigma_model`, `local_cached_dates`, `build_panel`, `trim_to_contiguous_run`, `panel_diagnostics`, `panel_timeseries`, `model_timeseries`, `daily_screen` (Citi's 13 columns), `rank_flags`/`select_pack`, `hedge_regression`/`HedgeFit`/`hedge_sizing`, `TradeSpec`/`build_trade_queries`, `plan_epochs`, `run_backtest`, `assert_ran`.
- `C:/Users/chris/clee/ARBS-cvx/tests/test_convexity_rv_strat2.py` — **35 tests, all pass** (5.8s).
- `C:/Users/chris/clee/ARBS-cvx/notebooks/backtests/convexity_rv/strat2_sofr_convexity_backtest.py` + executed `.../strat2_sofr_convexity_backtest.ipynb` — verified `24 code cells, 0 unrun, 0 errors`, 3 plotly figures (`compare_curves` + 2 × `trade_dashboard`).
- Data: `C:/Users/chris/clee/ARBS-cvx/notebooks/data/convexity_rv/strat2_panel.parquet`, `strat2_rates.parquet`, `strat2_equity.parquet`.

**TIE-OUTS — all pass, with numbers**
- **(a)** 2023-06-09 vs Citi Fig 58: 13/13 pack labels match; `M4-H5 → 2024-06-19..2025-06-18` ✓, `M6-H7 → 2026-06-17..2027-06-16` ✓; **CA corr 0.9682** (bar >0.95); level offset mean −3.89bp / median −4.31bp (the CME-vs-LCH clearing basis; `ca_basis_bp` defaults to 0.0, nothing fudged).
- **(b)** Roll identity `CA(p)−CA(p−1)`: Citi's own table max err **0.0100bp on 12/12**; reversed-column negative control **12/12 mismatch**; asserted exactly (<1e-9) on our computed screen, plus a further-pack control.
- **(c)** `1000×4×$25 = $100,000/bp`, `2000 → $200,000/bp`; `belly_DV01 = CA_DV01·β/100` reproduces Citi's published 5y notionals at **ratio 1.004** ($100k, β=21.4) and **1.003** ($200k, β=20.6).
- **(d)** Sign probes run live in the notebook: OUTRIGHT `bpv>0` payer **+$2,303,346 / −$2,303,346** mirror-exact over the 2022-09 selloff; futures `contracts>0` marks **−$11,250** exactly (= −4.50bp × $25 × 100); FLY `bpv>0` resolves `[−0.73, +1.0, −0.47]` with notionals −$82.6mn/+$47.5mn/−$12.0mn (Citi's shape: 79.0/−44.4/10.9).
- Extra: implied vol from **Citi's own** CA column reproduces **Citi's own** implied-vol column at median ratio **0.9973** (13/13, range 0.9941–0.9979); the fitted variance model tracks Citi's cap-vol model at **shape corr 0.9993** with a **+3.63bp level gap** (exactly the documented limitation).

**Test suite is not vacuous** — mutating (i) the variance-fit basis exponent, (ii) the sign of `belly_DV01`, (iii) the roll's reference pack made **4 tests fail**; reverted, 76/76 pass across all three ConvexityRV test files.

**BACKTEST — REAL MEASURED NUMBERS.** Effective window **2020-02-03..2023-09-20, 3.63y, 904 daily marks, 35 epochs**, $100k/bp CA leg, zero costs (Citi's convention). Every leg through `QueryDrivenBacktest`: 4 SR3 futures legs on `STIRFutureHandler` + matched swap + 2s5s10s FLY.

| | unhedged | hedged |
|---|---|---|
| total | **+$3,209,018** (32.09bp of CA DV01) | **+$1,264,288** (12.64bp) |
| annualised Sharpe | **0.191** | **0.070** |
| ann. $ | +$895,540 | +$352,825 |
| max drawdown | **−$6,493,635** | **−$6,799,544** |
| daily hit rate | 51.1% | 49.6% |
| n trades / trade hit rate | 35 / **74.3%** | 35 / **65.7%** |
| median / mean trade | +$79,759 / +$91,686 | +$89,226 / +$36,123 |

By year (unhedged / hedged): 2020 +1,346,100 / +409,394; 2021 +655,509 / **−505,514**; 2022 +450,037 / +800,440; 2023 +757,372 / +559,969.

**The fly hedge made it worse, and that is a finding, not a bug.** Citi fitted Blues (3–4y forward) and reported 90% correlation in levels. On the near-dated packs this data can reach, the trailing regression gives **R² mostly 0.2–0.6 with a frequently sign-flipping β** (values from +226.7 to −111.6), and **8 of 35 epochs could not be expressed as a fly at all** (a wing weight same-signed as the belly, or |β|<1) — those were skipped and recorded rather than clipped.

**Concentration**: the largest epoch is the COVID entry 2020-02-03 (Z1-U2) at **−$3,098,827**, immediately followed by the reversal epoch 2020-03-02 (M1-H2) at **+$2,851,953** — a near-cancelling pair, exactly the short-gamma signature. **Excluding every 2020-entered epoch: +$1,821,863 over 25 epochs, median +$46,763.** Costs: at **0.5bp** round-trip per $100k DV01 the hedged book goes negative (−$485,712); at **1bp** both do (unhedged −$290,982).

**WHAT DID NOT WORK, PLAINLY**
- **The requested 2019-01→2026-08 window is not achievable offline.** I scanned the 8-shard `STIRFuturePricer_Cache` (2,072 EOD dates) directly. Dates carrying *every* contract a pack window needs: windows 1..10 → 2019:252, 2020:253, 2021:252, 2022:252, 2023:183, 2024:1, 2025:2, 2026:1. Windows 4..13 → 252/253/252/185/3/1/2/1. Windows **5..17 (Citi's own rows)** → 77/253/187/40/2/1/1/0. A cold contract costs ~60s over the network and ~700 dates are missing, so a backfill is a multi-hour job.
- **The Q12STIRT substitute was tested and rejected.** Reading IMM×IMM forwards off the complete futures-calibrated `USD-SOFR-1D-Q12STIRT` curve (2,060 dates) disagrees with raw settles at the pack level by median absolute **9.3bp in 2019** and 2.6bp in 2022, correlation of the two CA series **0.33**. That is calibration residual several times the signal.
- **Consequence: Blues and Golds — the packs Citi actually traded — are out of daily reach.** The book trades windows 2..10 (0.5–2.5y out) where the CA is a fraction of a bp to a few bp. `n_contracts`/`rank_start`/`n_packs` are config knobs; the 2023-06-09 tie-out runs at Citi's full rank-5..17 depth because that one date is fully cached.
- **`vs_model` is not Citi's `Vs Model`.** The corpus gives no cap/floor calibration detail, so the default `sigma_model_mode="fit"` fits a smooth variance term structure to the same-day CA cross-section — a residual-centred *shape* dislocation. `"external"` (supply your own σ) and `"constant"` are the alternatives. Stated in the module docstring, the notebook, and pinned by a test.
- **`IRSwapValue.CVX_ADJ` was deliberately not reused**: it asserts a single-element package, needs an `sfr` kwarg, and rounds the pack price to ¼ tick (0.25bp of CA granularity). The unrounded average is what tied out at 0.968.
- Landmine pinned by a test: `IRSwapStructure._build_fly` **mutates `risk_weights` in place**, so `build_trade_queries` builds a fresh list per query.

Panel build ~3 min (1,196 dates), backtest ~170s for both books; 2023-06-09 and the panel dates are now warm in the shared Barchart cache if the orchestrator reuses them.