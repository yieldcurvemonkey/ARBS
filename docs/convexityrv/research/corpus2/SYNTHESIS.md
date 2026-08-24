# SYNTHESIS — Corpus 2: SOFR-futures convexity adjustment (CA) vs USD SOFR butterflies

**Synthesized 2026-08-24** from the 12 markdown reports in this directory (g01, g02, g03, g05, g06, g07,
g08, g09, g10, g11, repo-research-digest, repo-results-audit; **g04 is absent from the directory** — 12 of
~13 read; nothing else was found to read). Purpose: feed the build of (1) a configurable
`QueryDrivenBacktest` notebook backtesting 3M SOFR futures CA (outrights, packs, bundles) vs USD SOFR
butterflies (spot and forward-starting), and (2) a live-data screener notebook. All numbers below are
quoted as published, with dates; nothing is re-measured here.

---

## 0. The one reconciliation the corpus requires

g08 (Vol Lab corpus) states as a NEGATIVE FINDING that "no document in this corpus contains a regression
of CA on a swap butterfly — Citi's published CA fair-value model here is Ho-Lee on cap/floor vols."
g09/g10 (Weeklies + Trade Ideas + print files) print exactly such regressions with coefficients. **Both
are right.** The Ho-Lee model is the *standing* fair value in every Vol Lab CA table (the "Model"/"VsModel"
columns); the fitted CA-on-curve/fly equations live in the *US Rates Weeklies and NA Rates Trade Ideas*
(13-Jan-2017 "Swearing in huge expectations", 9-Feb-2017 "Sell Blues convexity adjustments, hedged",
19/20-Apr-2018 "Convexity Meets Steepeners"), where they size the *hedge* of a short-CA trade, not the
screen's fair value. A build that treats "Citi Blues CA = a + b·fly" as the screening model and Ho-Lee as
decoration has the franchise backwards: Citi screens on Ho-Lee dislocation and z-scores, then *hedges*
the model value with the fitted curve/fly proxy.

---

## 1. Canonical conventions (every variation inherits these)

- **CA definition (verbatim, stable 2017→2023):** CA for a 1y pack = pack rate (average of the 4 futures
  rates, rate = 100 − price) minus the **matched-maturity forward 1y CME swap rate**, in bp. Positive =
  futures rate above forward swap rate. SOFR era substitutes "SOFR" for "ED" and "CME swap" is explicit
  from 14-Jan-2019 onward.
- **Matched swap:** IMM-dated forward-starting, `swap_start = IMM(first contract)`, `swap_end = IMM+12m`;
  **both legs quarterly** ("Consistent with the standard market practice, both fixed and floating legs of
  this swap have a quarterly payment frequency"). SR3 reference quarters tile the window exactly
  (Henrard: SR3 runs IMM→next IMM and concatenates; ED did not). The Q/Q convention is load-bearing:
  the annual-frequency variant is off by `0.375·r²` (−5.46bp in 2023), and this exact gap was once
  misattributed to the CME-LCH clearing basis (repo-results-audit §2.16) — the annual variant is now the
  repo's mandatory negative control.
- **Venue:** swap leg **CME-cleared, mandatory** — "convexity adjustments will appear wider if clearing
  the swap leg on LCH"; CME preferred because futures+swap margin net (22-Jun-2021 rationale). The fly
  hedge leg is venue-indifferent.
- **Sizing unit:** $100k CA DV01 = 1000 packs (1000 of each of the 4 contracts; futures DV01 =
  n·4·$25) vs ~$1bn notional matched swap, DV01-matched. In ARBS: 4 separate OUTRIGHT `STIRFutureQuery`
  legs (never the pack alias — the handler quadruples pack P&L) + one payer `IRSwapQuery`; flies need a
  **fresh** `risk_weights` list (`_build_fly` mutates in place); `assert_ran` mandatory (QDB swallows
  exceptions).
- **Fly weights:** Citi quotes swap flies at **−0.5/+1/−0.5** (half of ARBS's 2·belly−front−back); ED/SFR
  futures flies at 1:2:1 or PCA (e.g. 0.9:2:1.4); JPM 50:50 flies = 2·belly − wings with 100/50/50 risk.
  Any Citi-published fly level tie-out must divide the ARBS fly by 2.
- **Ho-Lee model (reverse-engineered, 8-table validated):** `CA_model(bp) = 0.5·σ²·mean(T1_i²)·1e4`,
  T1 = ACT/365 as-of→IMM of each contract, σ from cap/floor vols; implied CA vol
  `σ_impl = sqrt(2·CA/1e4/M)·1e4`, `M = mean(T1²)`. The Hull `½σ²T1T2` form is **wrong** for Citi's
  tables (monotone bias 0.933→0.975); JPM's `σ²T₁T₂/2` reproduces implied vol only to ~3–6% — a ±5%
  sanity band, never an equality tie-out.
- **Model CA magnitudes (fair-value scale):** at HW/Vasicek(a=3%, σ=65bp): ≈0–0.5bp Whites, ~1–2bp Reds,
  ~4–4.5bp at 5y (Rosen Fig 1c), ~7bp at 7y (Henrard GBP). SR1/FF CA ≤0.07bp — effectively zero.
  **CA-based RV is only meaningful from Reds outwards.**
- **Front-contract decay:** once a contract enters its reference quarter the fixed portion has no
  convexity (Henrard Thm 2; Rosen) — CA decays deterministically through the quarter. A Whites CA-vs-fly
  spread has a mechanical, non-mean-reverting drift; **a mean-reversion signal must not harvest it.**
- **CA can print negative/positive-price:** Euribor bias went negative summer 2013 (Aikin — double margin
  across un-nettable pools); Attack68: "I've also seen real market positive convexity prices, which are
  impossible theoretically… positioning, clearing house margin… can engulf the theoretical prices."
  No model that floors CA at zero survives the record.
- **Seasonality:** December IMM contracts always straddle the year-turn (Ametrano; historically +64bp
  2007, +22bp 2008 ON jumps, damped ~1/20 at 1M, ~1/3 of that at 3M); Feb-2017 fitted-ED-curve table
  shows Decembers systematically cheap (Z8 +1.50bp, 1y z 3.22). Quarter-end repo can push SOFR prints
  +15bp (Sep 30, 2024). Flag/exclude December-belly and turn-straddling structures or model the turn.
- **Tie-out discipline:** grade in **bp on levels** (median/max abs error, slope, intercept) with
  negative controls that must fail — corr 0.966 against a rank-linear CA table survived ×2, ×100,
  +10bp and ÷√252 mutations (w2b). Null bars at effective sample size, both per-hold and annualised.

### Cost anchors (the only quantified numbers in the corpus)

| item | cost | source/date |
|---|---|---|
| 2y IMM swap market-maker bid/ask | 0.5bp two-way | CME Rogerson, Jun-2025 |
| SOFR pack/bundle min increment | 0.25bp; bundle execution give-up 0.1875bp in the worked example | CME Jun-2025 |
| USD swap one-way b/o 2017+ | 0.3bp (2y/5y/10y), 0.4bp (30y); 2013–16 0.4/0.5; crisis 1.2–2.0 | Citi 12-Mar-2018 Fig 8 |
| Realized round-trip on hedged CA trades | ≈$20k on $300k DV01 (~0.07bp, Aug-2017); Citi model portfolio otherwise EXCLUDES costs | print(11); g10 |
| Long-end fwd fly package b/o | ~3bp (and untradeable in Mar-2020 stress) | Citi 15-Jun-2020 alert |
| Long-dated flattener | 0.75–1bp initiation, 0.3–0.4bp per delta-hedge/roll, one-way; realized ≈$32k per $50k-DV01 round trip over 7 months | Citi 9-May-2019 Fig 9; Dec-2019 close |
| Listed SR3 fly | ~one tick (0.5bp); repo-measured 1.5–2.0bp round trip dominates small edges | MEMORY refs; Aikin fee warnings |
| CCP-basis trade breakeven | 5Y ≈3.932bp (Clarus); ≥4bp anecdotal (SUERF) — below that the basis is structural, not a trade | Jun-2015; Jul-2024 |

### Structural breaks any 2014→2026 backtest must mark

13-May-2015 (CME curves re-marked to CME observations — "CME curve" changes meaning); 16/19-Oct-2020
(EFFR→SOFR discounting at both CCPs + mandatory basis-swap bookings); Sept-2024 (FMX SOFR futures
clearing at LCH — first SOFR-futures-vs-LCH-swap margin pool, 78% offsets at 2–5y); Jun-2026 repo
clearing mandate (potential ~+1bp "expanded SOFR" fixing shift). ZLB regime break: every fitted
curve/CA regression is annotated "not effective at ZLB" (Citi calibrates pre-2008 + 2017+, excluding
6/2008–1/2016).

---

## 2. Candidate-variation matrix

Ten variations. Each: name, thesis, structure, signal, entry/exit, data, tie-outs, risks.
Repo verdicts from repo-results-audit are attached where they kill or qualify a candidate — the matrix
is deliberately not sanitized into optimism.

### V1 — MR-Z: pure technical mean-reversion of pack CA (z-score)

- **Thesis:** CA dislocations from their own history are positioning-driven and revert when shorts
  capitulate/cover (Citi's recurring narrative 2017–2023; short capitulation richens/normalizes CA;
  monthly-change regularity 1/1/13–12/26/17). The published franchise entered at ~2σ dislocations and
  banked 1.5–2.2bp of tightening per trade.
- **Structure:** short CA = buy 1000×4 SR3 contracts of the selected 1y pack + pay fixed $≈1bn on the
  matched-maturity Q/Q CME forward 1y swap, $100k CA DV01. (Long CA = mirror; the record is short-only.)
- **Signal:** 3m and 1y z-scores of the pack CA level (the screen's own columns); optionally the CA
  1-week change for momentum guard.
- **Entry/exit (published thresholds):** entry when CA ≥ ~2σ rich (2σ observed at every 2017/2018 entry;
  3σ at the Jan-2017 extreme). Exits from the tickets: **2021: target 4bp tightening / stop 3bp
  widening**; **2023: target 4bp / stop 2.5bp**; **2017 Greens: +$450K/−$225K on $300k DV01 = +1.5bp /
  −0.75bp (2:1)**; 2017 Blues $600k/$350k on $200k DV01 (3.0/−1.75bp). Hold ≤3m with quarterly roll
  (repo `plan_epochs` convention).
- **Data:** SR3 settles (strip depth rank+3), SOFR CME swap curve (Q20/CITIVELOEXCEL stores), CA panel.
- **Tie-outs:** the 11 dated CA tables (12/9/16, 1/6/17, 1/12/17, 1/13/17, 4/28/17, 5/12/17, 1/5/18,
  3/9/18, 4/18/18, 1/11/19, 3/22/19, 5/8/19, 9/24/19, 1/16/20, 3/27/20, 6/21/21, 2/16/23, 6/9/23); the
  repo's anchor is Citi Fig 58 close 6/9/2023 (13 rows; Blues M6-H7 CA 15.40 / model 9.98 / VsModel
  +5.42; repo reproduces median |err| 0.99bp, Blues 15.72). Ticket sequence: Blues 8.8→6.6bp (+$552k),
  Greens 4.3→2.65bp (+$476k), 2021 Blues 7.9→5.9bp within 10 days.
- **Risks:** z on the raw CA level harvests the deterministic front-quarter decay and the term-structure
  roll (use VsModel or roll-adjusted CA for the signal, CA level only for marks); row-based rolling
  windows silently span >1,000 calendar days on sparse data (use calendar windows); the repo's closest
  test — w2b CA vs fly on repaired 2021–2026 data — is **DEAD** (gross Sharpe 0.130 < E[max|null] 0.177;
  the 0.470 pre-repair Sharpe was an accidental-sample artifact), so the burden of proof is on any new
  variation to beat that bar; further short build-up is the standing stop-loss scenario.

### V2 — MR-PAIRS: CA-vs-fly spread as a pairs trade (JPM beta-stability recipe)

- **Thesis:** CA and the matched swap-curve butterfly are cointegrated expressions of the same belly
  curvature + vol; their spread residual mean-reverts with a <1M dominant frequency (JPM Apr-2021
  Fourier analysis). Trade the residual, not either leg.
- **Structure:** short(long) CA package (V1 structure) vs receive(pay) belly of a matched USD SOFR fly —
  spot 2s5s10s for Blues-area packs (Citi's published pairing) or the pack-adjacent forward-starting
  fly; fly sized `belly_DV01 = CA_DV01·β/100` with wings at the regression weights (verified 1.004/1.003
  vs Citi's printed notionals).
- **Signal (JPM Apr-2021 verbatim):** rolling **6M two-factor regression** of the 50:50 fly (or of the
  CA-vs-fly spread) on body level and wing curve; residual = signal; z of residual.
- **Entry/exit (published):** enter at **R² ≥ 60% AND |z| ≥ 1.5 AND |residual| ≥ 4bp** (the empirically
  best of 12 trigger combos: 1.3bp/trade, 52–55% hit, 923–1,188 trades 2001–21). Exit at first of:
  residual crosses zero (ex-ante betas, COB); residual worsens another 2 SD (stop ≈3.5–4z); **1M horizon
  elapsed**. Risk filter: skip entries when the beta-stability index `√(Zb²+Zw²) > 3` (Zb/Zw = 6M z of
  the 3M vol of the body/wing betas) — improved critical-period P&L ~+25%.
- **Data:** CA panel + daily SOFR swap fly panel (spot and forward), 6M rolling windows.
- **Tie-outs:** JPM Apr-2021 trigger-grid table (12 cells quoted in g09 §12); Fourier <1M reversion;
  Citi fly RV table vintages (4/19/18, 1/17/19, 5/9/19, 5/16/19, 8/1/19, 10/3/19) for matched fly
  reconstruction; ED fly monitors on the same dates.
- **Risks:** regime-change losses concentrate where the Fed cycle turns (JPM's critical periods:
  2Q19 worst — success 3–29%); the repo's w2b already ran the closest USD variant and it is DEAD
  post-costs (costs remove 90% of gross; hedge worse than no hedge, 0.125 vs 0.130); grid-notebook §5:
  **forward-starting flies do NOT track the CA better** (slope −0.018 vs predicted +1.0) and beyond
  rank 5 the swap leg is the larger beta — the "hedge" becomes a curve-shape bet; beta instability is
  the named failure mode and must gate entries, not be a post-hoc excuse.

### V3 — FV-FLY: fair-value regression, CA = a + b·(weighted 2s5s10s fly)

- **Thesis:** the Ho-Lee model value of Blues CA is spanned by the swap curve because front-end vol is
  curve-directional (steeper ⇒ more Fed-path uncertainty ⇒ higher vol; 3y1y vol vs the fitted fly 90%
  correlated in levels). The fitted fly is therefore both a fair-value line and a carry-positive hedge.
- **Structure:** V1 short-CA package + pay the belly of the 2s5s10s swap fly at fitted weights (Citi
  9-Feb-2017: notionals $147mm/−$85.6mm/$20.89mm = 0.705/−1/0.465 DV01 on $200k CA DV01, fly at
  −18.2bp).
- **Signal (published coefficients — re-fit, don't freeze):**
  `Blues CA ≈ 10.2 + 21.4·(−0.73·2y + 5y − 0.47·10y)` (13-Jan-2017); re-fit three weeks later to
  `9.7 + 20.6·(−0.705, 1, −0.465)` (9-Feb-2017) — **the drift between vintages is the instruction:
  implement the regression (roll ~252d), not the frozen numbers.** Vol-proxy companion:
  `scaled fly = 59.7 + 60.5·(−0.71·2y + 5y − 0.18·10y)`. Signal = CA − fitted fly value, z-scored.
- **Entry/exit:** entry when CA ≥ ~2σ (≈3–4bp, 2017 levels) wide to the fitted fly AND wide to Ho-Lee;
  package carry positive (+$206k/3m on $100k DV01 at the Jan-2017 print, $130k CA + $76k fly). Exits =
  V1 ticket targets/stops (the Feb-2017 trade IS this variation: 8.8→6.6bp, net +$500K incl. costs).
- **Data:** CA panel + USD SOFR 2y/5y/10y swap rates; 252d trailing regression (repo `hedge_regression`
  skips n<30, |β|<1, same-sign wings).
- **Tie-outs:** both printed coefficient sets; `belly_DV01 = CA_DV01·β/100` vs published notionals
  (ratios 1.004/1.003); the −18.2→−16.5bp fly move inside the closed Blues ticket; no R² was ever
  printed for these fits ("highly correlated" only) — the regression quality must be re-established
  in-house before use as fair value.
- **Risks:** the repo already graded this cell: **Citi's own 2s5s10s hedge on the rebuilt Q/Q panel has
  hedge R² 0.000–0.010, β sign flips, and carry −0.67bp vs their +4bp claim** (grid-notebook); hedged
  dollars are engine-certified at only 32–49% of panel dollars (aged-swap fly-leg drift) — certify any
  winner through QDB with `assert_ran` before quoting dollars; ZLB caveat on every curve fit.

### V4 — FV-HOLEE: model-dislocation screen (VsModel)

- **Thesis:** Citi's actual standing fair value. CA above Ho-Lee = compensation for dealer concentration
  risk from futures-expressed shorts; reversion to model is the trade. Selling CA ≡ selling delta-hedged
  straddles: `E[P&L] = E∫(T−t)[σ²_impl − σ²_rlzd]dt` — implied/realized is the ex-ante profitability
  gauge.
- **Structure:** V1 package, pack chosen by the screen (see §3 ranking).
- **Signal:** VsModel = CA − `0.5·σ²_capfloor·mean(T1²)·1e4`; its 3m/1y z; CA-implied vol / 3m realized
  pack vol; cap-vol implied/realized.
- **Entry/exit:** entry at VsModel ≥ 2σ (every published entry); prefer packs where I/R ≥ ~1.5 and
  3m roll highest; exits = V1 ticket rules. The Jun-2021 Blues-vs-Golds refinement: Golds more
  dislocated, **Blues won on higher 3m roll + higher CA-implied vol vs own multi-year range** — rank on
  most-of-8-metrics, not raw VsModel.
- **Data:** CA panel + USD cap/floor (or listed SR3 option) normal vols; `holee.py` inversion.
- **Tie-outs:** σ_fit/σ_reported median 0.9998 (1/12/17), 0.9973 (6/9/23); CA−Model=VsModel identity
  13/13; 2/16/23 table (Blues H6-Z6 13.09/9.44/+3.65; Golds H7-Z7 21.24/13.87/+7.37).
- **Risks:** the model is vol-input-sensitive and the CA-implied vol premium partly reflects genuine
  margin/positioning costs, not mispricing (Attack68's "engulf" warning; Aikin's negative-bias
  episode); w3 verdict: CA-implied vol vs long-end vol RV is DEAD at the diagnostic (max |corr of daily
  changes| 0.112) — don't extend this signal off the strip; cap/floor vol sourcing for SOFR era needs
  the swaption/listed-vol stores (strike-convention traps in MEMORY).

### V5 — FV-STRIP: futures-curve-only fair value (ED6/ED16-style steepener)

- **Thesis:** the model CA is also spanned by the futures strip itself — a DV01-weighted long-dated
  minus mid-curve steepener — usable when swap data is unavailable or as a same-complex hedge with
  positive carry (+2bp/3m on the Jan-2018 hedge; more carry-efficient than 3y1y swaptions or 3x4
  cap/floor).
- **Structure:** V1 package hedged with an SR3 steepener at fitted DV01 weights: Blues ↔ contract-6 vs
  contract-16 at 0.74/−1.0 (Jan-2018: buy 130 EDM9 / sell 176 EDZ1 per $100k DV01); Greens ↔ 5 vs 9 at
  −1/1.18 (May/Jun-2017: sell 500 EDM9 / buy 424 EDM8 per $300k, i.e. `−3.53·ED5 + 4.17·ED9` in %).
- **Signal (published):** `model Blues CA = −0.65 + 0.044·(ED16 − 0.74·ED6)` (Apr-2018 chart label,
  fit to 1999, weights calibrated **pre-2008** — "the hedge is not effective at ZLB"). SR3 equivalent:
  re-fit contract-rank rates on the post-2021 sample.
- **Entry/exit:** as V4 (the signal is a proxy for the model value); hedge lifted independently when it
  outperforms its own fair value (13-Jul-2017 alert: hedge off at +$70.5K, CA short kept).
- **Data:** SR3 settles only (plus the CA panel for the target leg) — the least data-hungry variation.
- **Tie-outs:** the printed equation; the 7/13/17 unwind P&L +$70,500 (NB the alert's contract counts
  are TRANSPOSED vs entry — only the initiation quantities reproduce the P&L; literal counts give
  +$33,450); the −3.53/4.17 Greens fit.
- **Risks:** sample-dependence is documented in-corpus (Aikin flags regression hedge ratios as
  sample-dependent and curve-shape-blind; recommends PCA); the ZLB break annotation is Citi's own;
  a strip-only signal cannot see the swap-leg venue effects (CCP basis, discounting breaks) that move
  measured CA.

### V6 — POS-TFF: dealer/spec-positioning-conditioned (CFTC TFF)

- **Thesis:** CA−model is a positioning gauge — AM+LF net shorts expressed in futures (capital-efficient:
  1–2 day close-out IM vs 5-day swaps) leave dealers long futures/paying swaps, structurally short CA;
  CA widens to compensate. JPM: richness beta to dealer net positioning consistently positive, **peaking
  2–3y forward (Greens)**. Citi used CA itself as the positioning proxy when CFTC went dark (Jan-2019).
- **Structure:** V1/V4 package; positioning is a **gate/tilt**, not a standalone signal.
- **Signal:** CFTC TFF **Asset Managers + Leveraged Funds net position as % of open interest
  (inverted)** vs Blues CA−model (Citi 22-Jun-2021 Fig 12; 21-Feb-2023 Fig 3); alternatively dealer
  net. Published fit: monthly ΔCA-vs-model on Δ dealer positioning R² = 0.32 (2014–17); 2018 vintage
  R² = 0.2724.
- **Entry/exit:** short CA only when VsModel ≥ 2σ AND net %OI short is stretched vs its own history
  (capitulation setup); stand aside when positioning already long (CA below model = long base,
  Jan-2019 rule: "CA above model = short base/cheap futures; CA at/below model = long positioning").
- **Data:** CFTC TFF weekly (`cftc_raw.parquet`, 2020-01→2026-05, incl. SOFR-3M from 2022-02, the
  pre-rename `3-MONTH SOFR` back to 2020, ED); **lag 3 business days** (stamped Tuesday, released
  Friday 15:30 ET — report-date joins are look-ahead); `build_positioning_panel` currently extracts
  only lev/AM — dealer_net needs one line; `_CONTRACT_MAP` lacks the SOFR rows; the cache never
  refreshes (unconditional short-circuit — delete the parquet).
- **Tie-outs:** w2b §5 reproduces Citi's mechanism **on Blues specifically**: slope +5.28e-07, t 2.59,
  R² 0.124 (HAC) — "the mechanism is real, the trade is not". Chart-spec tie-outs: net%OI axis −8%…+4%
  vs CA−model −3…+4bp (2021); −0.08…+0.04 vs −6…+6bp (2023).
- **Risks:** w2b's verdict stands — conditioning did not rescue the trade on 2021–26 data (dealers
  max-long, lev money min-short at the 2026 edge); raw exchange OI is NOT the series (Aikin: no
  OI→price link; per-contract OI history is survivorship-shaped and unusable pre-2025); weekly
  frequency vs daily signal mismatches.

### V7 — CCP-BASIS: CME-LCH basis-conditioned

- **Thesis:** the swap leg has a venue; measured CA embeds the CME-LCH basis at the pack maturity.
  The basis is itself a positioning proxy (10y basis 3m-changes: 31% corr to TY spec/OI, 51% to Δ10y —
  Citi Jan-2019), and its regime (2015 blow-out → 2017 ~3.4bp 30y → 0.8bp Aug-2019 → ~0.85bp and a 2024
  sign flip) shifts the CA level term. Conditioning, hedging-venue choice, and a CA-vs-CA-difference
  diagnostic — **not** a standalone trade below the ~4bp breakeven.
- **Structure:** (a) condition V1/V4 entries on basis regime/direction; (b) build CA vs BOTH CCP curves
  and difference them to recover the clearing-basis term structure at pack maturities; (c) the JPM
  May-2017 double trade (buy front EDs vs pay CME-facing FRAs — long CA richness AND long basis
  widening) as the historical template.
- **Signal:** CME-LCH basis level/changes at 2y–5y (front end historically <1bp, mostly ~0.25bp —
  expect weak power, per the pre-registered expectation: the mechanism is IM non-nettability, not the
  basis level; do not read a null as data failure).
- **Entry/exit:** no published thresholds for a CA-conditioned rule; the only published basis-trade
  economics are the breakevens (5Y 3.932bp Clarus; ≥4bp SUERF) — below them the basis is carry, not a
  trade. JPM's basis trade had no target/stop (pull-to-expiry rationale: ~2y to contract expiry).
- **Data:** gs_quant `IR_SWAP_RATES_V1_STANDARD` (USD SOFR/OIS/LIBOR, both CCPs, spot 1y–30y ladder,
  history claimed from 2018-04-27; live-verified −2.00/−2.05bp 10y LCH−CME Aug-2026); no caching layer;
  `coverage_path` hardcodes the primary checkout; **hardcoded live credentials committed at
  `MDP/IRClearingHouseBasisSwaps/gs_quant_fetcher.py:7-8`** (security finding — rotate/remove).
- **Tie-outs:** printed 30Y basis path (<0.1bp Jun-2014 → 1.90 May-2015 ICAP ladder → 3.4bp Jun-2017
  MVA decomposition ($726,545 lifetime IM funding / $225k DV01 = 1.3+2.1bp; **note the printed bp
  column ≠ MVA/DV01 exactly — not an identity**) → 0.8bp Aug-2019 → 0.85bp May-2025); JPM Exhibit 4:
  front-end basis <1bp, ~0.25bp since mid-2016; CME-based CA ≈80% of LCH-based (5/1/17).
- **Risks:** the corpus's own cautionary tale lives here — the −3.89/−4.31bp "CME-vs-LCH clearing
  basis" found in the first strat2 build was actually the annual/quarterly swap-frequency gap
  (repo-results-audit §2.16). Any basis attribution must first rule out convention error. Post-2024
  regime (basis ~flat through vol episodes, sign flip) argues the conditioning variable is now nearly
  degenerate; FMX/LCH from Sept-2024 is a live structural break in the opposite direction.

### V8 — CARRY-RAC: carry/roll-aware selection and timing

- **Thesis:** the short-CA trade is a positive-carry short-vol position; the screen's own `3m Roll` and
  `Impl/Rlzd` columns are the risk-adjusted-carry pair Citi actually used to pick packs (Jun-2021
  Blues-vs-Golds). Enter only when paid to wait; exit when carry decays.
- **Structure:** V1/V4 package, pack selection by roll and I/R; optional flattener-side mirror (the
  delta-hedged long-convexity franchise) for two-sided expression.
- **Signal (five named RAC constructions — not interchangeable):** RAC-4 (primary here): `3m Roll
  (short cvx) = CA(pack) − CA(pack one contract nearer)` + implied/realized ratio. RAC-1 (flattener
  side): daily breakeven / 1y realized vol of the BACK leg, `BE = sqrt(2·carry_daily/Γ)` inferred,
  BE ≡ 0 when 1y carry ≥ 0. RAC-2 (JPM): `E[3M return]/(3M realized daily bp vol × √252)`. Carry
  conventions: forward-minus-spot per unit DV01 ≡ funding-spread per unit notional (dm63 identity);
  horizon carry needs the accrual factor τ (the Nordea note omits it — literal transcription is 2×
  off); **forward-starting structures have zero carry at inception** — a forward fly's "carry" is pure
  static-curve roll-down; forwards-realized is the zero-edge null.
- **Entry/exit (published):** short-CA side: highest 3m roll among ≥2σ packs (2021: Blues roll 0.98 vs
  Golds; carry +1.2bp/3m; 2023: +1.5bp/3m). Flattener side: enter BE/RV ≤ ~0.42–0.8, **exit at 0.8**
  (5-Dec-2019 observed); steepener side enters at BE/RV **1.17/1.38** (12-Jun-2023 frontier). One
  published liquidity veto on a triggering signal (26-Mar-2020: watch-list only, b/o too wide).
- **Data:** CA panel only (RAC-4); swap curve for RAC-1/roll-downs (static-curve convention off
  forward-rate differences; not linear in horizon).
- **Tie-outs:** roll identity verified 12/12 on both the 1/12/17 and 6/9/23 tables (reversed-column
  negative control 11/12 mismatch); w4's RAC screen vs Citi 2019-12-04 table Spearman 0.988 (120
  cells); RAC-2 verified 4/4 on OAT rows (⚠️ caption says "annualised" — the arithmetic is raw 3M).
- **Risks:** BE≡0 truncation is a boundary trigger — run matched-rarity placebos (boundary-signal
  placebo hazard is a standing repo finding); the repo's carry-gated long-end variants are all DEAD
  (w4: 0.397 < null 0.446; strat3 deflated-Sharpe fail; strat1 signal degenerate/always-on); carry
  measured on the wrong field is a known trap (strat3: `CARRY_AND_ROLL_BPS_RUNNING` gave corr −0.136
  vs repriced roll +0.991).

### V9 — GRAN-CONTRACT: per-contract CA and micro-RV (December effect)

- **Thesis:** CA should be monotone in expiry; per-contract deviations (December contracts cheap on OI
  concentration; "similar to using asset swap spreads when looking at Treasuries") are a
  futures-microstructure conditioning layer and a finer entry grid than 1y packs.
- **Structure:** single-contract CA legs (1 contract + matched 3M IMM swap) or micro-flies inside the
  strip; alternatively adjust pack-entry timing to avoid/exploit December-rich rows.
- **Signal:** contract CA vs a monotone/fitted interpolation of neighbors (Citi Feb-2017: monotonic
  cubic spline, 9 nodes, through 24 contracts; spread-to-fit z-scored); OI-shift regression
  (ΔZ9-fly-spread-to-fit vs ΔOI-in-Z9: R² 0.3676).
- **Entry/exit:** none published (screen-level only). Citi's stated reason for packs: "individual
  ED/FRA spreads are noisy and hard to trade."
- **Data:** full SR3 strip settles + fitted curve; per-contract CA table 2/2/2017 as format template
  (H8 1.12/0.92 … Z0 11.05/4.64, Decembers non-monotone rich).
- **Tie-outs:** Feb-2017 per-contract table; Z-contract cheapness rows (Z8 +1.50bp 1y z 3.22 vs fit).
- **Risks:** noise dominance is Citi's own verdict; December cheapness is a funding/turn technical, not
  convexity (Ametrano) — a "signal" here is partly the year-turn jump; per-contract OI history doesn't
  exist pre-2025 in-repo (survivorship-shaped).

### V10 — GRAN-BUNDLE: bundle/strip CA vs forward swaps (and the packs-vs-bundle micro-arb)

- **Thesis:** the 2y bundle vs 2y IMM swap is the cleanest tradeable CA at scale (CME's own 2025 worked
  example is a complete pricing chain); bundles historically price tighter than the sum of packs
  (Aikin), giving an intra-futures micro-RV; a 2y-bundle CA extends the pack framework to the exact
  structure market-makers hedge with.
- **Structure:** buy/sell the N-year bundle (8/12/16/20 contracts, arithmetic-average price, 0.25bp
  tick) vs the matched IMM-dated Q/Q act/360 swap, DV01-laddered (the ladder is NOT flat: 100/99/99/98/
  97/96/95/95 = 779 per $100mn 2y swap); or bundle vs sum-of-packs at single-fee strategy pricing.
- **Signal:** bundle-implied swap coupon minus market swap rate (net of the model CA); pack/bundle
  price-vs-fair (average) deviations.
- **Entry/exit:** none published; MM economics anchor the edge scale: 0.5bp swap quote − 0.1875bp
  bundle give-up ≈ **0.1bp net** — this is a microstructure/execution overlay, not a standalone alpha.
- **Data:** SR3 strip; bundle quotes if available (else construct from legs at 0.25bp increments,
  respecting CME's integer-net-change allocation to deferred legs first).
- **Tie-outs (the known-answer suite):** CME Jun-2025: 8 prices → DF ladder (6 d.p.) → coupon
  **3.3304%** → hedge ladder 779 → convexity P&L table ±10/25/50/100bp (−100bp: +$22,292; +100bp:
  +$21,226; linear-approx (797−779)×½×100×$25 = $22,500) — verified 8/8 in-repo; portfolio-margin
  chain $569,910 + $1,568,352 → **$46,161** (~98% reduction).
- **Risks:** fee-intensity (multi-leg costs are the documented killer of matrix/fly trading — "many
  matrix traders live off the exchange rebates"); bundle forward-start vs t+2 spot-swap stub/maturity
  mismatch if the swap leg is not IMM-dated; the 0.1bp edge is below every non-MM cost stack in §1.

---

## 3. screener_spec — the live CA-vs-fly screen

Modeled verbatim on Citi's Vol Lab table (12 columns 2016–2020, 13/14 columns 2021–2023) plus the
fair-value lines and conditioning overlays the corpus supports.

**Universe / rows:** 1y SR3 packs rolled quarterly, labeled first–last contract (e.g. `M4-H5`),
ranks ~2–17 (Whites CA is noise; Golds rank-17 sits at the edge of a 20-instrument calibration and
gate-fails — display but flag). Pack labels roll to the dominant H-Z run (Citi Feb-2023 convention:
"Blues" = SFRH6-Z6 even when Z5 is technically the 13th quarterly). Optional expansion rows:
per-contract CA (V9) and 2y bundle CA (V10).

**Columns (in order, with identity checks):**

| # | column | definition / check |
|---|---|---|
| 1 | Pack | first–last contract codes |
| 2 | CA (bp) | pack rate − matched Q/Q CME fwd 1y swap; identity `(pack−swap)×100 − ca_bp = 0` |
| 3 | 1wk chg (bp) | |
| 4 | CA 3m Z | calendar-window z, not row-window |
| 5 | CA 1y Z | |
| 6 | Model (bp) | Ho-Lee `0.5·σ²·mean(T1²)·1e4` on cap/floor (or listed SR3) vols |
| 7 | VsModel (bp) | **identity: CA − Model = VsModel row-by-row (±0.01)** |
| 8 | VsModel 3m Z | |
| 9 | VsModel 1y Z | |
| 10 | 3m Roll, short cvx (bp) | **identity: Roll(p) = CA(p) − CA(p one contract nearer)** (verified 12/12) |
| 11 | Implied vol (nv) | Ho-Lee inverted on observed CA; `n/a` below ~0.1bp CA (floor guard, not sign) |
| 12 | Realized vol (nv) | 3m realized of the pack rate, close-to-close, ×√252; exclude IMM-roll-date returns |
| 13 | Impl/Rlzd | rounded 1dp (Citi rounds) |
| 14 | Cap-vol Impl/Rlzd | truncated 1dp |

**Fair-value lines (plotted under the table, per the two-model split of §0):**
1. Ho-Lee model level per pack (the standing Vol Lab line: rolling Greens/Blues/Golds CA vs model).
2. Fitted-fly fair value: rolling-252d regression `CA ~ r2y + r5y + r10y` rendered as
   `a + b·(w2·2y + 5y + w10·10y)` with the current coefficient printout (Citi printed
   `10.2 + 21.4·(−0.73,1,−0.47)` and `9.7 + 20.6·(−0.705,1,−0.465)` in 2017 — display ours the same
   way, dated), plus hedge-notional preview `belly_DV01 = CA_DV01·β/100`.
3. Strip-proxy line: re-fit `model CA ≈ a + b·(rank16 − 0.74·rank6)` (SR3 ranks), flagged
   "invalid at ZLB".

**Ranking / selection:** bold the top-3 packs per metric (Citi convention); rank by
**most-of-8-metrics** (repo `RANK_METRICS`: the 8 z/dislocation/roll/vol-ratio columns); tie-break by
higher 3m roll then higher CA-implied vol vs its own multi-year range (the Jun-2021 Blues-over-Golds
rule). Display the current published-ticket thresholds next to the top pick: entry ≥2σ VsModel; target
4bp / stop 2.5–3bp (2021/2023 vintages).

**Conditioning overlays (side panels):**
- CFTC TFF: AM+LF net % of OI (inverted) vs Blues VsModel, lagged 3bd to release (axes per the
  published charts: −8%…+4% / −3…+4bp); dealer net as secondary.
- CME-LCH basis: 2y–5y ladder (gs_quant both-CCP series), with the 4bp trade-economics floor marked.
- Carry panel: 3m roll ladder + BE/RV for the mirror flattener side, entry/exit bands 0.8 / 1.17–1.38.
- Diagnostics strip: front-pack in-quarter CA-decay indicator (deterministic drift warning), December/
  turn flag on affected packs, data-coverage flags (strip depth, gate pass, settle-vs-Q20 diff ≤2.0bp),
  ADF p-value + half-life beside every z-score (w3 discipline).

**Footnotes (mandatory, per the source):** "vs CME swaps" venue note; Q/Q both legs; fly quotes at
−0.5/1/−0.5 are half of ARBS 2·belly−front−back; "Calculations do not include transaction costs" if
mid-marked, else state the cost model (§1 anchors).

**Tie-out mode:** a `--tieout` switch rendering the screen for close 6/9/2023 and 2/16/2023 and
grading vs the printed tables **in bp on levels** (median |err|, worst, slope, intercept; the repo
anchor: median 0.99bp, worst 3.06, Blues 15.72 vs 15.40), with the annual-frequency negative control
that must fail by ~−4bp.

---

## 4. What the fresh build must NOT inherit (from repo-results-audit)

1. Any number from the annual-panel era (`strat2_panel.parquet`): the −3.9bp "clearing basis", the
   rank-5 fly spike, Sharpes 0.191/0.070, the +$5.05m/0.470 near-pack reference. All superseded.
2. Trim-artifact windows (2020-08..2024-05 near; 743/301-day Q20) — use `keep="latest"` +
   `window_span_tolerance`.
3. Correlation-only tie-outs against rank-linear tables.
4. Coverage numbers as findings on a demand-driven cache; poisoned `no_data` markers.
5. Unit seams: bp/yr vs bp/day (silent √252, three prior instances), SFR price = 100 − rate,
   `_as_percent` heuristics.
6. Golds rank-17 bought back by loosening the 2.0bp gate.
7. Panel hedged dollars without QDB certification (`assert_ran`).
8. Verdicts without null bars at n_eff on both clocks. And the standing meta-finding: research bugs
   flatter the hypothesis (12/12 precedent) — every result needs a negative control that must fail.

## 5. Published-ticket ledger (the backtest's known-answer battery)

| date | trade | entry | exit / result |
|---|---|---|---|
| 9-Feb-2017 8am | Sell $200k DV01 Blues CA (2000 H0-Z0 vs $2bn CME 3/18/20–3/17/21) + pay belly 2s5s10s $147/−$85.6/$20.89mm @ −18.2bp | 8.8bp | 6-Jun-2017 @ 6.6bp, fly −16.5bp; net **+$500K** (Citi table +$552k); target $600k stop $350k |
| 6-Jun-2017 | Sell $300k DV01 Greens CA (3000 M9-H0 vs $3bn M19–M20) + hedge sell 500 EDM9 @98.215 / buy 424 EDM8 @98.46 | 4.3bp | hedge off 13-Jul @ +$70.5K (counts transposed in alert); closed 8-Aug-2017 @ 2.65bp, **+$475.5k net**; target $450k stop $225k |
| 5-Jan-2018 10am | Sell $100k DV01 Blues CA (1000 H1-Z1 vs $1bn 3/17/21–3/16/22) + 130 EDM9 / 176 EDZ1 (0.74/−1) | 6.5bp | no target/stop printed; carry +$140K/3m; note misprints "1/5/2017" |
| 18-Apr-2018 3pm | Sell Blues CA outright (vs CME) | 7.2bp mid | no printed exit (year misprinted 2019) |
| 11-Jun-2021 noon | Sell $100k DV01 Blues CA (1000 EDM4-H5 vs $1.01bn CME 6/17/24–6/16/25) | 7.9bp | target 4bp tightening / stop 3bp widening; 5.9bp by 6/21; carry +1.2bp/3m |
| 17-Feb-2023 2pm | Sell $100k DV01 Blues CA (1000 SFRH6-Z6 vs $1.17bn CME 3/18/26–3/16/27) | 12.7bp | target 4bp / stop 2.5bp; carry +1.5bp/3m running |

Plus the CME Jun-2025 2y-bundle chain (§V10), the Henrard/Rosen/Ametrano model tables (HW(3%,0.3526%)
EUR CA 0→1.36bp; Vasicek(3%,65bp) SR3 ≈4–4.5bp at 5y), and the eleven dated full-curve CA tables listed
in V1 — the densest known-answer set in the corpus.
