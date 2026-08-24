# Repo research digest — `docs/convexityrv/research/` corpus (read 2026-08-24)

Scope: everything in `C:/Users/chris/clee/ARBS-cvx3/docs/convexityrv/research/` relevant to (a) the Citi STIR
pack-convexity screen and its fly hedge, (b) dealer positioning vs CA, (c) CME-LCH / CCP basis, (d) the
risk-adjusted-carry timing rule, (e) SR3 data coverage. Files 01, 09, 10–16 read in full; 02–08 skimmed.
All claims below are sourced to the corpus file (numbers are as published there; nothing re-measured here).

---

## (a) Citi STIR pack-convexity screen and its fly hedge

Primary: `01-citi-stir-convexity-vs-butterfly.md` (full reimplementation spec, ED→SFR port);
`14-preflight-stir-and-cme-lch-extraction.md` (four more Citi notes + JPM + Clarus + CME);
`13-preflight-longend-research-extraction.md` §10 (the 2021 ticket); `16-preflight-synthesis.md` §3.1.

### Measurement spec (fully pinned)
- **CA definition** (verbatim, stable across every vintage 2017→2023): CA for a 1y pack = pack rate
  (average of the 4 futures rates, `rate = 100 − price`) minus the **matched-maturity forward 1y CME swap
  rate**, in bp. Swap window: `swap_start = IMM(first contract)`, `swap_end = IMM +12m` (= IMM of the
  contract after the 4th leg); **Q/Q both legs** ("Consistent with the standard market practice, both fixed
  and floating legs of this swap have a quarterly payment frequency"). For SR3 the four reference quarters
  tile the swap window exactly — cleaner than the ED analogue.
- **Ho-Lee model, reverse-engineered and 8-table validated** (file 01 §2):
  `CA_pack_model(bp) = 0.5·σ²·mean(T1_i²)·1e4`, T1 = ACT/365 as-of→IMM(3rd Wed) of each contract.
  σ_fit/σ_reported median 0.9998 (1/12/17 ED, 13 rows), 0.9973 (6/9/23 SOFR, 13 rows). The Hull form
  `½σ²T1T2` is **wrong** for Citi's tables (monotone bias 0.933→0.975); only `T1²` is flat. Closed-form
  implied vol: `σ_impl = sqrt(2·CA/1e4/M)·1e4`, `M = mean(T1²)`. Exclude rows with CA < 0.3bp from
  calibration tests (rounding-dominated). Rows with CA below ~0.1bp print `n/a` implied vol (guard on a
  floor, not sign — the source is itself irregular here, file 01 §7.6).
  - JPM's printed closed form (`14` §5) is `A_cvx = σ²T₁T₂/2` — reproduces Citi's implied-vol column only
    to ~3% (Blues) / ~6% (Greens). **Use as a ±5% sanity band only, never an equality tie-out** (14 §"Model-convention check").
- **Realized vol**: "3m realized vol of the corresponding pack" — inferred close-to-close daily changes of
  the pack rate, sample stdev, ×√252, bp/yr normal. Roll-date caveat: constituents change at IMM roll;
  exclude roll-date returns or use constant-contract windows.
- **13-column SOFR screen layout** (Fig 58, 6/9/23): `CvxAdj | 1WkChg | 3m Z | 1Y Z | Model(bp) | VsModel |
  3m Z | 1Y Z | 3m Roll | ImplVol | RlzdVol | Impl/Rlzd (ROUNDED 1dp) | Cap-vol I/R (TRUNCATED 1dp)`.
  ED tables (2017–2020) are 12 columns (no Model column). `3m Roll(pack) = CA(pack) − CA(pack shifted one
  contract nearer)` — verified 12/12 exact on both the 1/12/17 ED and 6/9/23 SOFR tables, with a
  non-vacuous negative control (11/12 mismatch when shuffled). `CA − Model = VsModel` holds 13/13.
- **Selection rule**: top-3 per metric marked bold; pick the pack flagged by the most metrics (Blues
  1/12/17 topped vs-model bp, vs-model z, roll, implied/realized). The Jun-2021 refinement (13 §10):
  between Blues and Golds, Golds were more dislocated vs model but **Blues won on higher 3m roll and
  higher CA-implied vol vs its own multi-year range**.

### Trade structure and the fly hedge
- **Short convexity = BUY the pack + PAY FIXED on the matched-maturity 1y CME swap, DV01-neutral within
  the CA leg**: `futures_DV01 = n_packs·4·$25`; swap notional s.t. DV01 matches ($100k DV01 = 1000 packs
  vs $1bn; verified on both published tickets). $25/bp/contract for ED and SR3 alike.
- **The 2s5s10s swap-fly hedge is a BETA hedge, not DV01-matched**: regress `CA(bp) ~ r2y + r5y + r10y`;
  fitted weights −0.73/1/−0.47 (13-Jan-2017, β=21.4) re-fit to 0.705/−1/0.465 (β=20.6) three weeks later —
  **implement the regression, not the frozen numbers**. Sizing: `belly_DV01 = CA_DV01·β/100`, wings
  `w2·belly`, `w10·belly` (verified vs both published notional sets, ratios 0.996/0.997). Belly DV01 is
  only ~21% of the CA DV01. Rationale: 3y1y vol is directional with 5s on the curve (corr in levels 90%);
  selling the fly hedges the vol risk *with positive carry* (+4bp/3m at 13-Jan) instead of buying a 3y1y
  swaption (−$65K/3m).
- **Alternative hedges in later notes** (file 14): ED6/ED16 steepener at 0.74/−1.0 DV01 weights (Blues,
  Jan-2018; calibrated on the pre-2008 sample — "the hedge is not effective at ZLB"); ED5/ED9 at −1/1.18
  (Greens, May-2017, regression `−3.53·ED5 + 4.17·ED9`, ED in %).

### Published tickets, targets/stops, outcomes (tie-out battery)
| date | trade | entry | exit / result |
|---|---|---|---|
| 9-Feb-2017 (8am) | Sell $200k DV01 Blues CA (2000 H0-Z0 packs vs $2bn CME 3/18/20–3/17/21) + pay belly 2s5s10s $147mm/−$85.6mm/$20.89mm at −18.2bp | **8.8bp** | closed 6-Jun-2017 at **6.6bp** / fly −16.5bp; **net P&L +$500K** (target $600K, stop $350K; gross CA leg $440K verified); Citi closed-trade table: P&L $552K, RoR 55.20% |
| 6-Jun-2017 | Sell $300k DV01 Greens CA (3000 M9-H0 vs $3bn, M19-M20) at **4.3bp**; hedge sell 500 EDM9/buy 424 EDM8 | roll +0.7bp/3m | **the only printed target/stop pair: +$450K / −$225K = +1.50bp/−0.75bp, 2:1**; hedge lifted 13-Jul-2017 at **+$70,500** — ⚠️ the alert's closing leg quantities are TRANSPOSED; only the initiation quantities reproduce the P&L (literal quantities give +$33,450). CA-leg MTM tie-out `(4.3−3.35)×$300k = $285,000` exact |
| 5-Jan-2018 (10am) | Sell $100k DV01 Blues CA (1000 H1-Z1 vs $1bn 3/17/21–3/16/22) at **6.5bp**; hedge 130 EDM9 / 176 EDZ1 (0.74/−1.0) | carry +$140K/3m | no target/stop printed; note misprints "1/5/2017" [sic] twice |
| 11-Jun-2021 (noon) | Sell $100k DV01 Blues CA (1000 EDM4-H5 vs $1.01bn CME 6/17/24–6/16/25) at **7.9bp** | carry +1.2bp/3m; **target 4bp tightening / stop 3bp widening**; tightened to 5.9bp by 6/21 — the only in-window (2021+) CA ticket |

Known-answer tables in the corpus: full 12/13-column screens for closes 1/12/17, 1/13/17, 5/12/17, 1/5/18,
1/11/19, 5/8/19, 9/24/19, 1/16/20, 3/27/20 (ED) and **6/9/23 (SOFR, 13 rows M4-H5…M7-H8; M6-H7 Blues CA
15.40 / model 9.98 / vs-model 5.42)**. The 6/9/23 table is already the repo's tie-out anchor
(`tests/test_convexity_rv_shared_ca_path.py`, corr > 0.96, |diff| < 4bp, Blues within 1bp).

Cost conventions: Citi explicitly excludes transaction costs ("Calculations do not include transaction
fees and other costs"); RoP is against a $300mn model portfolio. CME's 2025 SOFR paper (14 §8) provides
the cleanest cost benchmark: 2y bundle hedge slippage **0.1875bp** vs 0.5bp two-way swap spread ⇒ ~0.1bp
net MM edge; and the complete portfolio-margin tie-out ($569,910 futures IM + $1,568,352 swap IM →
**$46,161 portfolio-margined, 97.84% reduction**; 8/8 convexity P&L scenarios verified).

Repo implementation: `RVUtils/ConvexityRV/strat2_sofr_convexity.py` (1,812 lines) wires the whole loop
(file 10 §3d): `ca_snapshot`/`build_panel` → `panel_timeseries`/`model_timeseries` → `daily_screen`
(Citi's 13 columns) → `plan_epochs` (BMS rebalance, `select_pack` = most of 8 RANK_METRICS, hold ≤3m,
roll Blues→Greens style) → per-entry `hedge_regression` (252d trailing, β=b5, skip recorded if n<30 or
|β|<1 or same-sign wings) → `run_backtest` → **`assert_ran` mandatory** (the engine swallows exceptions).
Legs are 4 separate OUTRIGHT STIRFutureQuery legs (never the pack alias — the handler quadruples pack P&L)
plus one payer IRSwapQuery, plus optionally a FLY with a **fresh** risk_weights list (mutated in place).

## (b) Dealer positioning vs CA

Primary: `11-preflight-signal-data-oi-ccp-positioning.md`; file 01 §10; file 14 §§1–5; 16 §2.1.

- **Citi's mechanism** (13-Jan-2017, verbatim in 01 §10): asset managers + leveraged funds short ED
  futures → dealers long futures, hedged by paying swaps → dealers structurally short CAs → CAs widen to
  compensate concentration risk. Quantified: Fig 19 regression of monthly ΔCA-vs-model on Δ dealer ED
  positioning ($mn DV01): `y = 0.00x − 0.15, R² = 0.32`, 1/1/14–1/3/17, CFTC. Jan-2018 vintage (14 §1):
  `y = 2E-06x − 0.1053, R² = 0.2724` (x in $mm, monthly, 1/1/13–12/26/17).
- **JPM (3-May-2017)**: "beta and correlation of richness in CAs with dealer positioning is consistently
  positive… peaks roughly 2 to 3 years forward" — issuance-related receiving (SSAs/GSEs) leaves dealers
  net long ED vs LCH-cleared swaps. Sign map: Citi's "client short" ≡ JPM's "dealer long" ⇒ CA wide/rich.
- **The observable proxy Citi itself published** (22-Jun-2021, Fig 12): **"Asset Managers + Leveraged
  Funds, Net % of OI (inverted)" vs `Blues CA − model`** — a CFTC TFF quantity. Margin asymmetry driver:
  futures IM uses 1–2 day close-out vs 5-day for cleared swaps/FRAs.
- **What's on disk** (file 11): CFTC TFF raw parquet `BT/results/tfp_screener/cftc_raw.parquet`, weekly
  2020-01-07→2026-05-12, 332 report dates, 154 markets, incl. `SOFR-3M` (n=223 from 2022-02-08, dealer_net
  last +1,719,008), `3-MONTH SOFR` (n=109 to 2022-02-01, contiguous across the Feb-2022 rename), SOFR-1M,
  FED FUNDS, ED, plus 2/5/10/30Y UST. Full TFF column set incl. `Dealer_Positions_*`,
  `Pct_of_OI_Dealer_*` — **but `build_positioning_panel` extracts only lev/am; `dealer_net` needs one line
  of code, and `_CONTRACT_MAP` lacks the SOFR rows**.
- **Traps**: (1) cache never refreshes — unconditional `if cache_path.exists(): return` short-circuit
  (`cftc_positioning.py:51-52`); 14 weeks stale as of 2026-08-20; delete the parquet to refresh.
  (2) TFF is stamped Tuesday, **released Friday 15:30 ET** — using report date as signal date is ~3 days
  of look-ahead (flagged NOT measured; verify and lag). (3) NY Fed primary-dealer stats: no fetcher, no
  cache, nothing in the repo. (4) Per-contract exchange OI is NOT the series Citi used — the TFF %-of-OI
  signal is buildable today; per-contract OI is not (see (e)).
- One explicit OI-level claim (Greens note, May-2017): "open interest in Reds and Greens has continued an
  upward trend… no signs of short covering" — vs Aikin's negative general claim ("no obvious link between
  increasing open interest and price action").
- Rateslib-author counterpoint (QSE, Jun-2025, file 14 bonus): "STIR convexity is just not based on those
  models. It depends upon positioning, clearing house margin… I've also seen real market positive
  convexity prices, which are impossible theoretically" — a standing warning against pure-model fair value.

## (c) CME-LCH / CCP basis

Primary: `14-preflight-stir-and-cme-lch-extraction.md` §§5–9; `11` §(b); 16 §2.1/§3.1.

- **Clearing-venue rules in the Citi strategy**: CA-leg swap → **CME mandatory** (netting of futures and
  swap margin; "convexity adjustments will appear wider if clearing the swap leg on LCH"); the 2s5s10s fly
  hedge → CME or LCH indifferent. Clarus hard constraint: "It is only possible to trade convexity between
  CME Eurodollars and FRAs if you clear the FRA at CME and have CME Portfolio Margining in place."
- **JPM vs Citi disagreement on the basis leg** (8 months apart): Citi (Jan-2018) — clear at CME, basis has
  retraced; JPM (May-2017) — front-end basis "too narrow" (well under 1bp, mostly ~0.25bp), buy H9/M9 EDs
  vs CME-facing FRAs to be long a widening. JPM's falsifiable prediction: halve the un-nettable IM and the
  CA net of vol-driven financing bias should fall proportionally. CME CAs ≈80% of LCH-facing CAs (5/1/17).
- **Reconstructible 30Y basis path** (all printed): <0.1bp (Jun-2014) → +1.90 (18-May-2015, ICAP 19981
  full 1Y–30Y ladder) → +2.50 (26-May-2015; Tradition multi-ccy USD/EUR/GBP grid same date) → +2.40
  (17-Jun-2015, second full ICAP ladder) → ~3.85 chart (1-May-2017 JPM) → +3.40 (26-Jun-2017 Tradition
  1Y–50Y). Forward-space: 5y5y basis +2.9 vs spot +1.85 (26-May-2015); max 1y-fwd rolldown just 1.1bp/yr.
- **Cost realism (headline negative result)**: Clarus *Pricing and Arbitraging* — a 1.25bp 5Y basis on
  $100m grosses $62,500 over 5y; after generous fees "just over $45,000", before IM funding ($3.9m day-1
  IM); verdict "this just isn't going to work… I am not beating treasuries." MVA build (For Dummies):
  $282,867 CME + $443,678 LCH = $726,545 on $100m 30Y — **but the printed bp column (1.30/2.10/3.40) ≠
  MVA/DV01 (1.257/1.972/3.229); do not build that tie-out as an identity**. JPM May-2015 upper bound from
  futures/swap cross-margin: 1.5bp.
- **Regime breaks for any historical series**: CME Advisory (13-May-2015) — CME-specific observations enter
  CME EOD curves within 30 days, so "CME curve" changes meaning ~mid-Jun-2015. Aikin: the Euribor
  convexity bias **went negative** in summer 2013 (two un-nettable IM pools) — falsifies any model that
  floors CA at zero.
- **Live series in ARBS** (file 11, measured): gs_quant `IR_SWAP_RATES_V1_STANDARD` — entitled and
  live-verified (USD SOFR 10y LCH−CME −2.00/−2.05bp, 2026-08-10..14; 2026-08-12 absent, unexplained).
  Exactly 3 (ccy,index) pairs carry both CCPs: USD SOFR / USD OIS / USD LIBOR, spot ladder 1y–30y,
  catalogue `historyStartDate` 2018-04-27 (**claimed, not measured**). Second dataset
  `IR_BASIS_SWAP_RATES_V1_STANDARD` (USD SOFR/OIS 801 pairs each) exists but the repo's `_NAME_PATTERN`
  matches 0 of it (needs a second regex). Traps: **no caching layer** (every call refetches);
  `coverage_path` hardcodes the primary checkout; **hardcoded live gs_quant credentials committed at
  `MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py:7-8`** (auth succeeded on them — security finding).
- Pre-registered expectation (16 §W2b): the front-end basis is small (~0.25bp) while SR3 pack CA lives
  ≤5y; the mechanism is **IM non-nettability, not the basis level** — expect weak explanatory power and do
  not read a null as a data failure.

## (d) Risk-adjusted-carry timing rule

Primary: `13-preflight-longend-research-extraction.md` §§1–8, 18; `16` §3.3. The corpus contains **five
distinct RAC constructions — not interchangeable; name which one you use**:

- **RAC-1 — Citi `daily BE / realized vol`** (4 dated vintages: 4-Dec-2019, 16-Jan-2020, 26-Mar-2020,
  8-Jun-2023). `daily_BE` = the daily rate move whose convexity gain offsets one day of negative carry;
  **BE ≡ 0 whenever 1y carry ≥ 0** ("effectively free convexity buy"). Denominator = **1y trailing daily
  bp vol of the BACK (longer, delta-hedged) forward rate** — back-leg keying verified twice independently
  (the vol row takes exactly 6 distinct values keyed to the back leg in both the 12/4/2019 and 6/8/2023
  tables). **Polarity flips by side**: flattener (long cvx, neg carry) — LOW attractive, observed exit at
  **0.8** (5-Dec-2019); steepener (short cvx, pos carry) — HIGH attractive, "meaningfully above 1",
  observed entries at **1.17/1.38** (12-Jun-2023, efficient frontier of BE/vol vs Z-since-2000). Four
  dated decisions incl. one **liquidity veto on a triggering signal** (26-Mar-2020: −5.21bp, carry +0.11,
  BE 0.00 — watch-list only, "lack of liquidity and wide bid/offer"; mid-to-bid ≈0.6bp in 10y swaps).
  Reproduces 10/10 (2023) and 15/15 (2019) published cells. Inferred (not printed) functional form
  `BE = sqrt(2·carry_daily/Γ)`. Needs only the swap curve → runs the whole 2019-2026 window. Delta-hedge
  rule: resize the back leg to (beta-scaled) DV01-neutral at each 20–25bp move in the back rate (Citi:
  "20-25bp offers an attractive balance between the accuracy of hedging and transaction costs"); optional
  empirical beta scale (1.025, 16-Oct-2019 reweight).
- **RAC-2 — JPM `RAC`** (9-Feb-2018): `E[return over 3M, bp] / (3M realised DAILY bp vol × √252)`;
  `E[return] = carry + slide + ½σ²·Cvx/PVBP`. **Verified 4/4 on the OAT rows (0.33/0.32/0.30/0.25); √252
  is the unique annualiser.** ⚠️ CAPTION TRAP: Exhibit 12's caption says "annualised 3M expected return" —
  the verified arithmetic uses the RAW 3M numerator; the caption's construction is 4× too large. Published
  hit rates vs 1Yx30Y ATMF straddles: 56% (30s/50s), 86% (25Y/20Yx5Y). Cross-market structure winner:
  20Y/40Yx10Y (USD and GBP).
- **RAC-3 — Citi forward-vol ex-ante Sharpe** (vol-adjusted roll on gamma-neutral calendars/triangles;
  σ_fwd triangular formula verified exactly, 106.15 vs printed 106.1). **The Sharpe denominator is not
  printed** (back-solves to 6.3–20.4) — reproduce level and ordering only.
- **RAC-4 — the CA screen's own risk-adjusted pair**: `3m Roll (short cvx)` + `Implied/Realized`. The
  Jun-2021 Blues-vs-Golds selection used exactly this. Needs only the CA panel — this is the W2b signal.
- **RAC-5 — target = dislocation − convexity cost** (20-Dec-2010 fly): 28bp dislocation − 8bp/a convexity
  cost = 20bp target, 10bp stop; the only note pricing convexity as a cost that shrinks the target.

Why it matters here (16 §3.2/W4): the codebase's strat-1/strat-3 signal was measured degenerate
(`frac_always_cheap` 86.0/40.7/34.2% — "a permanently-on flattener, not a timing rule"); RAC-1 is the
published two-sided rule with printed thresholds, and JPM's Feb-2020 normalisation is the **ratio of
swap-curve-implied vol to swaption-implied vol** (not a cheap-share). Placebo warning (16 risk #37): the
BE≡0 truncation is a boundary trigger — run matched-rarity placebos before believing results.

## (e) SR3 data coverage

Primary: `15-preflight-ca-coverage-state.md` (measured 2026-08-20), `09-infra-stir-futures.md`,
`16-preflight-synthesis.md` §2 (adjudicated). **Use file 15/16 numbers, not older docs.**

- **Adjudication (16 A1/A2)**: HANDOVER_PREFLIGHT's "Blues/Golds effectively unavailable after 2023" is
  **INVERTED** — the manual `warm_sr3_deferred.py` run (2026-08-19, ledger: 635 dates, 9,448/9,476 cells,
  0 errors, 5.48h) closed the 2024-2026 hole. **The remaining strip-depth gap is 2021-2023 (+2018-19).**
- **Coverage by band, 2021-01-01..2026-08-21 (1,424 EOD dates; rank r needs depth r+3)**: Whites 100.0%,
  Reds 99.9%, Greens 97.8% (27 of 32 short dates in 2023), **Blues 80.8%** (short 58 in 2022 + 207 in
  2023, ~794 cells), **Golds 66.1%** (short 65/201/207 in 2021/22/23, ~2,698 cells; plus 302 dates
  2018-19 at ~1 cell each). Servable remainder 787 dates / 2,698 cells at depth 20; the vendor **still
  serves pre-2024 deferred settles** (two deliberate probes 2023-06-26 and 2022-08-09 both resolved and
  wrote the NY 17:00 alias). Warm wall-time is bimodal — budget 1.5–7.5h; `plan()`'s est_seconds is ~11×
  optimistic (`corr(seconds, cells)=0.144`) and schedules 85 pre-listing 2018 dates (first SR3 key
  2018-05-04) — use `--start 2020-01-01` and decide `--protect-min-depth 21` explicitly (re-solving
  2022/23 curves WILL move published values; the `published_values_moved: 0` invariant must be retired in
  favour of a quantified diff vs `_baseline_prewarm/`).
- **Cache mechanics** (file 09): `STIRFuturePricer_Cache` diskcache (8 shards, 22.6M keys), key
  `{ts_iso}-{ticker}-{src}` — **`src` is part of the key**: the minute tape lives under
  `BARCHART_TOS_LIVE_STIRF-RL` and is invisible to `BARCHART_STIRF-RL` lookups. EOD keys are stamped
  **17:00 America/New_York = 16:00 CT nearest-bar marks, NOT the 14:00 CT CME settle**. `price_df.ffill().bfill()`
  before slicing (a contract with no print inherits a neighbour). Demand-driven, not an archive.
  Curve stores: `USD-SOFR-1D-Q12STIRT` 2,065 days 2018-06→2026-08 (⚠️ built with `max_tenor=39` vs rule
  45 — live production defect, ditto Q16 51 vs 57); Q20 rule-compliant at 66 only after `db95871d`;
  `USD-SOFR-1D-CITIVELOEXCEL` EOD 5,511 partitions 2005-01-03..2026-08-14 (99.73% of bdays in-window);
  minute store `-CITIVELOEXCELMIN` starts **2021-09-14** (intraday floor); Q16 store has only 201 days
  and no 2026-03 partitions (the notebook anchor 6.28942… cannot be re-derived offline).
- **Open interest**: survivorship-shaped, not liquidity-shaped — per-symbol OI coverage splits exactly at
  the live/expired line (expired SR3H20…SR3M26 at 0.004–0.028 vs live SR3U26…SR3M31 at 0.976–0.996).
  **Any front-rank study before ~2025 has no per-contract OI.** Last-bar OI=0 trap: the futures path never
  calls `blank_unpublished_open_interest`, so requesting today's date lands fabricated zeros (42 rows on
  3 dates measured). Only EOD `BARCHART_STIRF-RL` requests fetch OI at all. Proxy: CFTC TFF
  `Open_Interest_All` (weekly whole-strip, 2020-01-07→2026-05-12).
- **CA plumbing traps** (file 12, some FIXED at `50e5fb29` per 16 A8): the shipped `IRSwapValue.CVX_ADJ`
  swap leg was annual/annual `usd_irs` — a 4.6–6.1bp compounding artefact larger than the CA itself
  (Q/Q now the default); `_as_percent` magnitude heuristic multiplied ZIRP-era prices ×100; a `bfill`
  look-ahead in the price panel was removed. **Every previously cached `sfr_cvx_adj` row is orphaned by
  the fix** (convention travels in `value_kwargs` → cache symbol) — a fresh backfill is a deliverable.
  Still live: `IRSwapQuery.build_mdp_request` date-truncates every value except `CVX_ADJ_EMPIRICAL`
  (intraday CA cannot pass through the query layer yet); `SnapshotPolicy.legacy()` default can serve a
  FUTURE snapshot (research callers must pass `.strict(...)`); a cold CITIVELO_EXCEL EOD day silently
  falls through to a live Excel COM build (enumerate partitions first, verify
  `meta()["from_curve_store"]`); exact midnight resolves to EOD (ask for 00:00:01); pack-tick rounding
  default differs between `IRSwapValue` (True) and `Strat2Config` (False — unrounded tied out to Citi at
  corr 0.968); `STIRFutureValue.RATE` always raises (use PRICE and convert); the FLY/BASIS query builders
  are broken (`NameError: kwargs`) — route flies through IMM-tenor `IRSwapQuery`; `constrained_bpv` on
  CURVE double-applies signs (PV01=0, NPV nonsense) — size with explicit per-leg contracts.

## Cross-cutting warnings (carry into any fresh backtest)

1. `QueryDrivenBacktest.run()` swallows exceptions — copy `assert_ran`; an empty plan or flat curve is
   otherwise indistinguishable from success.
2. Research bugs flatter the hypothesis (12/12 precedent): every result needs a negative control that must
   fail, mutation testing on signal code, and a deflated-Sharpe/trial-count section.
3. Never `conda run` in parallel (temp-file collision → empty output, exit 0); call
   `C:/Users/chris/anaconda3/envs/stir/python.exe` directly with `ARBS_SUPABASE_ENABLED=0`.
4. `data/ts` ComputedTimeseriesStore is cwd-relative → cold in every worktree; only CurveStore and
   diskcache are shared.
5. Coverage percentages are meaningless without a denominator (store-days vs bdate_range vs
   holiday-adjusted — the 97.8/95.6/99.43% "conflict" was three denominators).
6. The FOMC configurable-notebook template hardcodes `REPO = ARBS-gcb` (repoint); `trade_dashboard`
   needs explicit `span_years` (only annualisation input) and `bar_width` (milliseconds).
7. Skimmed-file pointers: 02 (delta-hedged flattener spec: AyBy = A-fwd/B-tail, receive the longer leg,
   hedge trigger on the BACK rate), 03 (JPM cheap-gamma: curve-implied vol vs 1Yx30Y swaption vol, the
   ratio normalisation; 15Yx5Y vs 35Yx5Y structure selection), 04 (Vol Lab literature map — methodology
   footnotes stable across dates, verdicts invert), 05 (notebook/dashboard pattern: `_make_config_notebook`
   emits JSON directly; `_py2nb.py` is a separate family), 06 (IRSwapsMDP CITIVELO_EXCEL source map),
   07 (swaption cube: `request_defaults={"verify": False}` is load-bearing — 236s first valuation
   otherwise), 08 (pm chat — different strategy, excluded; only take: reweight DV01 each time, daily-vol
   units).
