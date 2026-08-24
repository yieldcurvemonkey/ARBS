# Corpus 2 — "print*.pdf.md" files (anonymous Citi Research PDFs)

Source directory: `C:/Users/chris/Downloads/convexityrv_markdown`. All 13 files were identified from
their opening pages; **none is a duplicate of a named document in the directory** (checked against
`US_Rates_Vol_Lab_Sell_Eurodollar_convexity_in_Blues` [08 Jan 2018], `US_Rates_Vol_Lab_Value_in_Greens_convexity`
[15 May 2017], the Turning-Green-from-Blue trade notes, and the named US Rates Weeklies — all
different dates/titles). The set is dominated by the Citi Eurodollar/SOFR convexity-adjustment (CA)
franchise (Bikbov/Williams 2017–2019, Chang/Williams 2023): the exact fair-value model, the
positioning story, the hedged trade constructions, and dollar-P&L outcomes.

Conventions used by every Citi CA doc in this corpus:

- **CA definition**: pack CA = (average of the 4 futures-implied forward rates in the pack) minus the
  matched-maturity 1y forward swap rate (IMM-dated, e.g. Blues = 13th–16th quarterly ⇒ swap from the
  13th IMM date to the 17th), quoted in bp. Positive = futures rate above forward swap rate.
- **Fair-value model**: one-factor **normal Ho-Lee**, calibrated to **cap/floor implied vols**; the only
  free inputs are maturity (fixed per pack) and vol. "Implied vol" of a CA is backed out by matching
  Ho-Lee to the observed CA.
- **Swap leg**: CME-cleared matched-maturity swap preferred over LCH (margin netting against the
  futures at CME ⇒ capital efficiency); fixed leg reset quarterly in the 2017 trades ("IMM quarterly
  money swap").
- **Positioning link**: CA-minus-model spread is inversely related to asset-manager + leveraged-fund
  net position (% of OI) in ED/SFR futures (CFTC TFF); shorts/steepeners in futures widen CA.

---

## 1. `print.pdf.md` — Citi *European Rates Weekly*: "A narrative shift looms"

- **Publisher/date**: Citi Research VIEWPOINT, 18 Mar 2022 00:18:42 ET, 38 pages (data as of 17 Mar 2022
  London close). Authors: Searle, Harju, Appeddu, Bansal, Gaveau, Dutta, Sawant.
- **Relevance**: peripheral to SOFR CA work; the € swaps section is a clean example of a
  **curve-fly-vs-gamma-vol fair-value framework** (the "fly vs vol" leg of our program), EUR not USD.
- **Trade (Appeddu, € swaps section)**: NEW TRADE — **receive € 5s10s30s 3m-forward-starting swap fly
  @ 41bp mid** (17 Mar 2022 close), **target 20bp, stop 50bp**; carry 3m = 0. Rationale: position for
  cheaper convexity driven by a richer front-end as gamma vol corrects lower. Risk: renewed top-left
  vol richening.
- **Signal machinery (verbatim mechanics)**:
  - 3m fwd/spot roll-down normalized by € 3m10y ATMF vol; as of 17Mar22 the market offers
    **0.3bp (receive 10y), 0.4bp (pay 5s30s), 0.1bp (receive 5s10s30s)** annualized per bpv.
    Pay 5s30s roll-down is best-in-3-years; receive-belly 5s10s30s near bottom of post-GFC range.
  - Conditional regressions of overlapping 3m changes (daily data 4 Jan 2010–16 Mar 2022) of
    {€10y, €5s10s30s, €5s30s} on 3m bpv change of € 3m10y ATMF vol:
    - Conditional on **2y sell-off** (2y >0.5σ above 3m mean): 5s10s30s: **y = 0.82x + 1.25, R² = 0.48**
      (only economically meaningful link); 10y: y = 0.45x + 26.76, R² = 0.05; 5s30s: y = −0.35x − 6.87,
      R² = 0.06. Cheapening of the fly on higher vol comes mostly from flatter 10s30s.
    - Conditional on **2y rally**: 10y: y = −0.64x − 32.10, R² = 0.39; 5s30s: y = −0.48x + 5.42, R² = 0.22;
      5s10s30s: y = 0.13x − 2.14, R² = 0.08 (bull-flattening regime).
  - Forward-implied terminal €10s30s: −45bp 3y-forward with 2y repricing 85bp cheaper ⇒ implied
    beta −0.4 of 10s30s to 2s.
- **Other tie-outs (17 Mar 2022 close)**: since 28 Jan 2022: € 2s +46.0bp, 10s30s −17.9bp; 1y1y SONIA
  vs Fed Funds +28.5bp (entry 2-Dec-21 @ 8.7bp, target −75, stop +50); Dec22 ECB €STR −0.11%
  (target −0.55, stop +0.11); 5y5y HICP 2.14%; regression **5y5y = 0.00·SX5E + 0.40·(5y HICP) + 0.012,
  R² = 89%** (1y sample); closed: May22 MPC SONIA received 1.115%→1.000% (+12bp). Prior closed fly
  trades: Rec €5s10s30s 2y-fwd entered 22.3bp stopped at 26bp (−4bp, 11 Nov 2021); Pay € 2s5s10s 6m-fwd
  6→−2 (−8bp, 9 Mar 2022). Rest of the report (gilt remit £124.5bn forecast, covered bond supply €135bn,
  QE tracker, TIPS/linker carry tables, auction DV01 calendar) — one line: not relevant to CA/fly work.

---

## 2. `print (8).pdf.md` — Citi *Rates Vol Lab*: "Short Blues convexity via futures/swaps"

- **Publisher/date**: Citi Research VIEWPOINT, 21 Feb 2023 12:54:46 ET, 33 pages. Authors: Mike Chang,
  Jason Williams, Andrea Appeddu. **Core document** for the SOFR-era CA franchise.
- **Thesis**: Blues/Golds CAs spiked after the strong Jan-2023 payrolls; high outright AND vs Ho-Lee
  model (CA-minus-model at multi-year high). Short-vol-proxy trade: sell the CA rather than sell
  options. CA framed explicitly as an option premium: futures (no convexity) rate > FRA rate is
  compensation for the FRA's positive convexity; held-to-maturity P&L depends on realized moves vs
  the CA "breakeven".
- **Pack naming convention (important)**: Citi refers to **Blues = SFRH6-Z6 and Golds = SFRH7-Z7**
  even though SFRZ5/SFRZ6 are technically the 13th/17th quarterlies — they roll the pack label to the
  H-Z run with dominant trading activity (as of Feb 2023).
- **Trade (verbatim specs)**: buy **1000 SFRH6-Z6 Blues pack** (1000 of each of the 4 contracts) vs
  **pay $1.17bn CME-cleared forward-starting swap 3/18/2026–3/16/2027 at 12.7bp** rate spread
  (pricing 2pm 2/17/2023, ATMF = 3.14%, **$100K DV01**). **Positive carry 1.5bp running over 3m**
  (short-CA rolldown). Risk: further build-up of futures-concentrated duration shorts.
  (The companion Weekly, doc 3 below, adds: **target 4bp tightening, stop 2.5bp widening**.)
- **Drivers/diagnostics**:
  - CFTC TFF: net position of asset managers + leveraged funds (% of OI, SFR+ED) inversely tracks
    Blues CA-minus-model (Fig 3; axes span roughly −0.08→+0.04 net %OI vs −6→+6bp spread).
    Latest CFTC print used: 1/24/2023 (pre-selloff).
  - Regression residual of **3y1y implied vol on rates** (inverted) also tracks CA-minus-model (Fig 4):
    the CA is positioning-driven, the model is vol-driven, so a vol-cheap residual widens the gap.
- **Known-answer table (Figure 5/50, close 2/16/2023, system-mid CA vs CME FRA/swap curve, 1y packs)**
  — columns: CA (bp) / 1wk chg (bp) / model (bp) / CA−model (bp) / 3m roll for short-cvx (bp) /
  implied vol / realized vol (normal bp/yr):

  | Pack | CA | 1wk chg | Model | vs Model | 3m roll (short cvx) | Impl vol | Rlzd vol |
  |------|-----|-----|------|------|------|------|------|
  | H4-Z4 | 2.67 | −3.06 | 2.21 | 0.46 | −0.54 | 155.2 | 168.1 |
  | M4-H5 | 4.09 | −3.53 | 3.01 | 1.08 | 1.42 | 165.0 | 162.7 |
  | U4-M5 | 5.05 | −3.14 | 3.87 | 1.18 | 0.96 | 160.5 | 155.9 |
  | Z4-U5 | 6.21 | −3.04 | 4.73 | 1.48 | 1.16 | 158.2 | 149.9 |
  | H5-Z5 | 8.45 | −3.09 | 5.17 | 3.28 | 2.24 | 166.1 | 144.8 |
  | M5-H6 | 9.28 | −2.97 | 6.38 | 2.89 | 0.82 | 158.2 | 140.8 |
  | U5-M6 | 10.35 | −2.76 | 7.64 | 2.71 | 1.08 | 153.2 | 138.1 |
  | Z5-U6 | 11.56 | −2.52 | 8.94 | 2.63 | 1.21 | 149.4 | 136.3 |
  | **H6-Z6 (Blues)** | **13.09** | −2.29 | **9.44** | **3.65** | 1.53 | 147.6 | 134.9 |
  | M6-H7 | 14.96 | −1.83 | 10.47 | 4.50 | 1.88 | 147.2 | 134.0 |
  | U6-M7 | 17.16 | −1.23 | 11.54 | 5.62 | 2.20 | 147.8 | 133.1 |
  | Z6-U7 | 19.37 | −0.60 | 12.68 | 6.70 | 2.21 | 147.7 | 131.8 |
  | **H7-Z7 (Golds)** | **21.24** | −0.25 | **13.87** | **7.37** | 1.87 | 146.1 | 130.4 |

  (Also carries 3m/1Y z-scores of CA and of CA-vs-model, and implied/realized & cap-vol/realized
  ratios ≈ 1.1 / 0.9 across the belly.) Table note verbatim: "Convexity adjustments for 1y SFR packs
  are computed as the spread between the pack's rate (the average of 4 ED rates in the pack) and
  matched-maturity forward 1y CME swap rate. The model for convexity adjustment is the Ho-Lee model
  calibrated to cap/floor vols."
- Golds most overvalued but "more persistent"; Blues already normalizing ⇒ trade the Blues.
- Rest of the doc is the standard Vol Lab RV survey (2/17/23 close): ATM vol tables, intraday vs
  close-to-close realized, efficient-frontier forward-vol trades (best: 6m1y1y fwd vol), skew tables,
  midcurves, CMS curve options (implied 2s30s correlations rebounding), conditional-curve carry
  tables, callable/Formosa supply run — usable as vol-side context but not CA-specific.

---

## 3. `print (9).pdf.md` — Citi *US Rates Weekly*: "Time for moderation"

- **Publisher/date**: Citi Research VIEWPOINT, 17 Feb 2023 18:06:52 ET, 47 pages. Mathai, Williams,
  Chang, Li, Datla, Vazquez Plata.
- **Vol section duplicates doc 2 verbatim** (same text, same Figure-5 CA table at 2/16/23 close, same
  trade), with one addition: the trade's explicit exit rules — **"targeting 4bps of tightening in the
  convexity adjustment and would stop out on 2.5bps of widening"** and pricing tag "2pm 2/17/2023".
- **Unique content — SOFR futures curve trades around the Fed pause (Short-end, Williams)**:
  - Fig 11: systematic rolling **SOFR futures micro-flatteners** since Jan-2021 by contract-rank pair
    (4th/5th … 8th/9th, H3 counted as 1st, Z2 excluded as stub): best risk-adjusted over past 3m and
    1y = **6th vs 7th** (7th vs 8th close second).
  - Fig 12 (tie-out table): Sharpe ratio (hit rate) of rolling **ED micro-steepeners** entered X months
    **before** the final hike, and held X months **after** it, over five cycles (Feb95, Mar97, May00,
    Jun06, Dec18), pairs 1st/2nd … 10th/11th. Selected values: before-hike 3m row: 1st/2nd +0.92 (80%),
    6th/7th −1.35 (0%), 7th/8th −1.49 (0%); before-hike 1y row: 3rd/4th +0.45 (100%); after-hike 1m:
    1st/2nd −2.73 (20%); after-hike 2m: 9th/10th +1.26 (100%); after-hike 1y: 7th/8th +1.18 (60%),
    6th/7th +0.95 (40%). Interpretation: pre-pause the whites steepen / 6th–8th flatten; post-pause
    flips — front flattens (1st/2nd, 2nd/3rd), 8th–10th steepen. Read: 6th/7th flattener best if pause
    is ~3m away; 8th/9th (Z4/H5) works even if pause is 6m out.
  - SOFR/FF fair value: regression of SOFR/FF on (T-bills outstanding − reserves):
    **y = −0.011x + 5.084, R² = 0.5942** (beta ≈ 1bp per $100bn); Q4-23 market pricing −0.5bp, Citi
    estimate SOFR 1–3bp **above** FF after TGA rebuild/$900bn bill supply.
  - 2y SOFR vs Dec-23 FOMC OIS: **y = 0.7395x + 0.9918, R² = 0.7135** (Dec OIS 5.10%→5.25% maps 2y
    SOFR → ~4.85%).
- **Positioning/tie-outs (COB 2/16/23)**: rates forecasts (2y 4.64% spot / 3.25% base YE23; 10y 3.86% /
  3.25%); OIS/UST matched-maturity spreads: 2y +9.1, 5y −20.1, 10y −28.4, 20y −59.3, 30y −68.5bp with
  PCA residuals (20y +3.0 rich, 30y −2.2 cheap); FRA/OIS H3 10.6bp, M3 14.7bp; 5nc3m Berm agency
  callable 5.73% yield, +165bp vs 5y UST (99th pctile since 2014), OAS −16bp vs SOFR; FHLB debt
  −$31bn Feb MTD from $1.23trn peak. Model-portfolio tradesheet (4pm 2/16/23, OCR-mangled but legible):
  1y-fwd 10s30s steepener opened −23.5bp now −32.9bp (target +15bp, stop −50bp, P&L −$473k);
  5s30s cap calendar P&L −$240k; 3m5y5y strangle sold at 3.11bp of premium, P&L +$261k; 5y TIPS ASW
  51→40.2bp (target 30, stop 70; +$362k); short TU invoice vs long 10y spreads 3.13→6.3bp (−$134k);
  1y20y SOFR receiver spread P&L −$1.01mm. H3-M3 Treasury futures roll views: bullish TU roll, slightly
  bearish FV, neutral TY/UXY, CTD-slope-vs-20s30s correlation noted (Fig 56); AM net long 42% of OI in TY.

---

## 4. `print (12).pdf.md` — Citi *NA Rates Trade Idea*: "Sell Blues convexity adjustments, hedged"

- **Publisher/date**: Citi Research, 09 Feb 2017 09:12:29 ET, 9 pages. Bikbov, Williams. **The
  canonical hedged-short-CA trade construction.**
- **Trade (verbatim specs, pricing 8am 2/9/2017)**: sell **$200k DV01 of Blues CA** = buy **2000 of
  H0-Z0 ED packs** (2000 of each of the 4 contracts) + **pay $2bn on a matched-maturity
  (3/18/2020–3/17/2021) CME-cleared swap at 8.8bp** of ED/swap spread (fixed leg reset quarterly).
  **Hedge**: pay the belly of the **2s5s10s swap fly**, notionals **$147mm / −$85.6mm / $20.89mm**
  (= **0.705/−1/0.465 DV01 weights**) at **−18.2bp** DV01-weighted fly level.
  **Target +$600k, stop −$350k; positive carry ≈ +$380k over 3m.**
- **Signals/valuations at entry**: Blues CA ≈ **4bp (~2σ) wide** to the Ho-Lee/cap-floor model;
  short-CA rolldown **+1.3bp over 3m**; CA ≈ **3bp (~2σ) wide to the fitted 2s5s10s fly**; short-fly
  carry/roll **+3.2bp over 3m**.
- **Fitted regressions (verbatim from chart labels)**:
  - Blues CA on swap rates: **scaled 2s5s10s fly = 9.7 + 20.6·(−0.705·2y + 5y − 0.465·10y)** — the
    fitted value of Blues CA regressed on 2y/5y/10y "effectively is a 2s5s10s fly with 0.705/−1/0.465
    DV01 weights".
  - 3y1y implied vol proxy: **scaled 2s5s10s fly = 59.7 + 60.5·(−0.71·2y + 5y − 0.18·10y)**; 3y1y
    vol vs fly correlation **90% in levels** — rationale for the short fly as a carry-positive vol
    hedge (a 3y1y swaption or 3x4 cap is the direct hedge but costs carry).
- **Positioning mechanism (dealer-positioning-vs-CA)**: AM + leveraged funds added **>$20.5mn DV01**
  of ED shorts post-election (CFTC); dealers long futures / paying swaps ⇒ structurally short CA;
  dealer risk-limit pressure widens CA; CA-model dislocation "highly correlated with dealers'
  positioning" (per *Swearing in huge expectations*). Heavy Jan corporate supply (receiving flows in
  swaps) also widened CA.
- **Skew-as-positioning signal**: subsequent 1m change in 10y rate bucketed by historical percentile
  of 3m change in the 3m10y 25bp-out risk reversal (monthly, Jan-2006–Nov-2016): pctile <25: avg
  −11.5bp / median −5.0 / freq>0 36%; 25–50: −2.1/−1.1/48%; 50–75: +0.2/−4.2/45%; >75:
  +8.8/+11.1/69% — flattening skew precedes rallies ⇒ short capitulation ⇒ CA tightens.
- **Clearing choice**: CA "will appear wider if clearing the swap leg on LCH", but CME preferred:
  CME-LCH basis had retraced from January wides, and CME nets ED + swap margin.
- Risk: further increase in short ED positioning (mitigated: positioning already historically stretched).

---

## 5. `print (11).pdf.md` — Citi *NA Rates Trade Idea Alert*: "Target achieved on short Greens convexity"

- **Publisher/date**: Citi Research, 08 Aug 2017 08:18:36 ET, 6 pages. Bikbov, Williams. Close-out
  alert for the 6/6/2017 Greens trade (the initiation note *Turning Green from Blue on short
  convexity* and the hedge-removal alert exist as separate named files in this directory — this is
  the final leg, not a duplicate).
- **Full trade history with dollar P&L (known-answer sequence)**:
  - 6/6/2017: sold **$300k DV01 of Greens CA** = bought **3000 M9-H0 packs** (3000 of each contract)
    + paid **$3bn matched-maturity CME swap (M19–M20 IMM quarterly money swap) at 4.3bp** ED/swap
    spread. Motivation: extreme dislocation of Greens CA from fair value.
  - Same date, vol hedge: sold **500 EDM9 @ 98.215**, bought **424 EDM8 @ 98.46** (hedges the
    model-implied fair value of Greens CA, which is directional with implied vol).
  - 7/13/2017: hedge taken off for **+$70.5k** on bearish gamma outlook.
  - 8/8/2017 (8:00am ET): M9-H0 pack CA mid **2.65bp** (from 4.3bp); +$450k target passed; closed at
    **+$475.5k net of transaction costs**. (≈1.65bp tightening × $300k/bp ≈ $495k gross ⇒ implied
    round-trip transaction cost of order $20k ≈ 0.07bp on the package.)
  - Residual: Greens CA still rich to fair value but no longer extreme; risk = hawkish Jackson Hole.

---

## 6. `print (10).pdf.md` — Citi *US Rates Vol Lab*: "Convexity Meets Steepeners"

- **Publisher/date**: Citi Research, 19 Apr 2018 13:29:15 ET, 23 pages. Bikbov, Williams.
- **Thesis**: ED CAs widened notably, led by Blues and Golds, both ≈ **2σ wide to the Ho-Lee model**;
  drivers = crowded duration shorts **and steepener positions** fading the flattening (curve beyond
  Greens flattened most — blues/golds, golds/purples pack slopes ≈ −1.0 to −1.2 on 1y z — so CAs
  there widened most). Leveraged money and AM "extremely short" ED (CFTC % of OI back to Oct-2012;
  dealers on the other side). Back-end skews flipped (receiver above payer) since January ⇒
  flatteners liquidated, replaced by steepeners; upper-left vol richening reflects conditional
  bull-steepener demand.
- **Trade**: sell **Blues** CA (buy Blues ED packs vs pay matched-maturity CME swaps) — Blues over
  Golds **for liquidity**; **outright/unhedged** this time because the house view is flattening and
  "a flat curve environment is normally negative for vol". Entry: **Blues CA vs CME = 7.2bp mid, 3pm
  4/18/2018** (doc misprints the year as 2019). Main risk: higher vol.
- **Steepener-hedged variant (fitted equation, verbatim chart label)**: **model Blues CA = −0.65 +
  0.044·(ED16 − 0.74·ED6)** — i.e. an ED6/ED16 steepener with 0.74/−1 DV01 weights tracks the model
  CA (fit to 1999; annotated "the hedge is not effective at ZLB"). This was the Jan-2018 (*Ringing
  in optimism* / *Sell Eurodollar convexity in Blues*) construction.
- **Known-answer table (Figure 56, close 4/18/2018, CA for 1y ED packs, bp)** — CA / model / 3m roll
  (short cvx) / implied vol / realized vol: M8-H9 0.18/0.14/0.07/98.1/52.4 · U8-M9 0.33/0.25 ·
  Z8-U9 0.53/0.37 · H9-Z9 0.78/0.53 · M9-H0 1.12/0.71 · U9-M0 1.53/0.93 · Z9-U0 2.02/1.18 ·
  **H0-Z0 2.60/1.45/0.58** · M0-H1 3.29/1.76 · U0-M1 4.07/2.10 · Z0-U1 4.92/2.47 ·
  **H1-Z1 6.10/3.13/1.18 (vs-model 3m z 2.22, 1Y z 1.30)** · M1-H2 7.22/3.70 · U1-M2 8.22/4.11 ·
  Z1-U2 9.08/4.32 · H2-Z2 9.76/4.31 · M2-H3 10.16/4.01. Implied/realized ≈ 1.4–1.9;
  cap-vol/realized 0.8–1.1.
- Other: 6m 5s30s/2y 2s30s **curve cap switch** (6m-fwd 18m 2s30s vol 42nv, 3pm 4/18/2018, cheap;
  the two curves correlate with beta ≈ 1); 1y3y/1y3y1y conditional bull steepener at zero-cost
  strike spread −7bp (strikes ATMF−15bp/−24bp, 8am 4/19/2018); 3m 3s5s10s receiver flies. ATM
  surface 4/18/18: 3m10y 56.9nv; 10y10y 5.5nv **cheap** to rates; 3m3y ~4nv rich.

---

## 7. `print (3).pdf.md` — Citi *US Rates Vol Lab*: "Buying vol for less"

- **Publisher/date**: Citi Research, 25 Sep 2019 12:57:47 ET, 25 pages. Bikbov, Williams (CORRECTION
  reprint — risks added to suggested trades). Its parent Weekly is doc 9 below.
- **CA content**: "Convexity adjustments in Blues are still trading rich to fair value", attributed
  to a **shift in asset-manager positioning** (ref Vol Lab *Forward vol, skews, and convexity*).
- **Known-answer table (Figure 62, close 9/24/2019, CA for 1y ED packs vs CME swaps, bp)** — CA /
  model / implied vol / realized vol (an easing-cycle tape: whites' CAs near zero and implied vol
  **below** realized, impl/rlzd 0.3–1.0): Z9-U0 0.08/−0.06/30.8/101.0 · H0-Z0 0.21/−0.03 ·
  M0-H1 0.39/0.02 · U0-M1 0.61/0.09 · Z0-U1 0.86/0.15 · H1-Z1 1.14/0.23 · M1-H2 1.46/0.31 ·
  U1-M2 1.81/0.40 · Z1-U2 2.21/0.50 · **H2-Z2 3.00/0.96 (1wk +0.35, vs-model 1Y z 1.06)** ·
  M2-H3 3.61/1.21 · U2-M3 4.47/1.68 · Z2-U3 5.11/1.90 · H3-Z3 5.51/1.85 · M3-H4 6.09/1.94 ·
  U3-M4 6.47/1.80 · Z3-U4 7.03/1.81.
- **Vol RV context**: forward vols beyond 1y-fwd very cheap (5y z-scores −1.3…−2.4; e.g. spot 1y2y
  68.64nv z +0.29 vs 4y-fwd 1y2y 61.25nv z −2.19) but justified by ELB risk (Citi recession model
  ~67% 1y probability) and Formosa-redemption-driven vol supply (~$1.5bn Sep-2019 callable issuance,
  largest month since Jan). So: don't buy forward swaption vol despite cheapness.
- **Curve-vol trade**: **1y 2s10s / 6m 5s10s straddle switch** — buy $1bn 1y 2s10s vs $1.7bn 6m
  5s10s straddles, delta-hedged (vols 34nv / 21.5nv at 3pm 9/24/2019; correlation 99% levels, 85%
  changes; conservative beta 1.7; implied 6m-fwd 6m 2s10s vol ≈ 31nv via
  sqrt[2·vol(1y2s10s)² − (β·vol(6m5s10s))²]) — watch list only. Spread-vol PCA: 2s10s vols cheap
  (3m −3.6z, 6m −4.9z, 1y −4.2z), 5s30s rich. Directionality: **6m 2s10s vol = 0.19·(2s10s bp) +
  34.44, R² = 0.60** ⇒ 2s10s at 75–100bp maps vol 36nv → 49–54nv. 2s10s ended steeper 1y after the
  first 3m/5y5y inversion in the Mar-89/Aug-00/Oct-06 cycles (3m/5y5y inverted Aug-2019).
- **Cheap-convexity trade**: delta-hedged **GBP 15y10y/25y10y swap flatteners** (rehedge each
  20–25bp move) — long-dated flattener convexity structurally cheap; the USD 15y5y/25y10y $50k DV01
  version initiated May-2019 still positive on elevated realized vol. GBP 20y sector rich from ALM
  receiving (10s20s30s GBP fly history shown). 3y 5s30s conditional bear steepener zero-cost strike
  spread ≈ 16bp (3pm 9/24/2019).

---

## 8. `print (15).pdf.md` — Citi *US Rates Weekly*: "Swearing in huge expectations"

- **Publisher/date**: Citi Research, 13 Jan 2017 17:36:04 ET, 36 pages. Mathai, Bikbov, Kang,
  Williams, Li. **Origin of the Jan-2017 Blues CA trade** (Swaps section "Smart convexity sells").
- **Levels**: Blues pack CA ≈ **4.6bp (~3σ) wide to the Ho-Lee model — widest dislocation since
  2015**; short-CA roll ≈ 1.3bp/3m; CA implied vol ≈ 30% rich to 3m realized (a sample that includes
  the high post-election realized).
- **Mechanism (verbatim chain)**: AMs + leveraged funds net short ED (hawkish-Fed positioning; futures
  preferred to FRAs for liquidity/transparency) → dealers long futures, hedged by paying swaps →
  dealers structurally short CA → historically-high dealer longs pressure risk limits → wider CA.
  **Fitted relation: monthly change in (Blues CA − model) vs monthly change in dealer positioning:
  y = 0.00x − 0.15, R² = 0.32** (monthly changes 1/1/2014–1/3/2017 — slope reported as 0.00 at
  displayed precision, in bp per mm contracts). AM+lev shorts **+$12.5mn DV01 since the election**;
  January corporate-issuance receiving flows add widening pressure; year-end illiquidity exacerbated
  it. ED open interest +500k contracts since Jan-3 CFTC report even as swaps rallied.
- **Known-answer table (Figure 20, close 1/12/2017, CA for 1y ED packs, bp)** — CA / vs-model /
  3m roll / implied vol / realized vol: H8-Z8 1.77/1.18/0.47/118.8/67.0 · M8-H9 2.35/1.46 ·
  U8-M9 3.14/1.86 · Z8-U9 4.17/2.40 · H9-Z9 5.32/2.94 · M9-H0 6.45/3.39 · U9-M0 7.64/3.83 ·
  Z9-U0 8.71/4.12 · **H0-Z0 10.02/4.61/1.30/125.5/95.1 (3m z 2.04, vs-model 3m z 2.66)** ·
  M0-H1 11.12/4.87 · U0-M1 11.93/4.80 · Z0-U1 12.76/4.74 · H1-Z1 13.53/4.60. Impl/rlzd 1.2–1.8;
  cap/rlzd 0.9–1.0. (1y packs used "because individual ED/FRA spreads are noisy and hard to trade".)
- **Trade (verbatim)**: sell **$100k DV01 of Blues CA** = buy **1000 H0-Z0 packs** + pay **$1bn
  matched-maturity 3/18/20–3/17/21 CME swap** (both legs quarterly frequency, "standard market
  practice"); hedge by paying belly of **2s5s10s fly, notionals $79mn/−$44.4mn/$10.9mn
  (0.73/−1/0.46 DV01 weights)** — fly clearing venue (CME or LCH) immaterial. **Package carry ≈
  +$206k/3m ($130k short-CA + $76k fly)**; alternative 3y1y swaption-straddle hedge ($96mn notional)
  cuts package carry to ≈ +$65k/3m ($130k − $65k). Risk: further positioning imbalance.
- **Fitted regressions (verbatim chart labels)**: Blues CA on 2y/5y/10y → **scaled 2s5s10s fly =
  10.2 + 21.4·(−0.73·2y + 5y − 0.47·10y)** (CA ≈ 4bp / 2.5σ wide to the fly); 3y1y vol → **scaled
  fly = 59.7 + 60.5·(−0.71·2y + 5y − 0.18·10y)**, 90% level correlation. CME clearing preferred
  (CA "will appear wider if clearing the swap leg on LCH"; CME-LCH basis retraced from Dec wides;
  ED+swap margin netting).
- **Special topic — skew as positioning warning** (orig. 12 Jan 2017 NA Rates Focus): the 10y-rate
  vs 3m10y-risk-reversal percentile table quoted in doc 4 originates here (Jan-2006–Nov-2016 monthly:
  <25 pctile −11.5bp avg; >75 pctile +8.8bp avg, 69% freq>0); leveraged-money net short DV01 at
  record (CFTC by curve sector); rationale: core shorts hedged with low-strike options richen
  receivers ⇒ flatter skew flags crowded shorts.
- Vol section reprints *Long Live Formosa* (9 Jan 2017): FSC minimum non-call proposal → buy 2y30y
  vs 2y10y straddles beta-weighted.

---

## 9. `print (14).pdf.md` — Citi *US Rates Vol Lab*: "Buy long expiries"

- **Publisher/date**: Citi Research, 17 Jan 2017 13:02:13 ET, 24 pages. Bikbov, Williams. The Vol Lab
  four days after doc 8: **"Optimal convexity sells" section restates the same Blues trade** (same
  $100k DV01 / 1000 H0-Z0 packs / $1bn CME swap / $79mn-$44.4mn-$10.9mn fly hedge / +$206k vs +$65k
  carry alternatives; same two fitted-fly equations, same LCH/CME note) — extract only the deltas:
  - Blues CA ≈ **4.5bp (~2.7σ)** wide to model at this print; AM+lev shorts **+$12.5mn DV01**
    post-election; dealer-positioning regression identical (R² = 0.32); OI +500k contracts since the
    **Jan-10** CFTC report.
  - **Known-answer table (Figure 48, close 1/13/2017, bp)** — CA / vs-model / impl vol / rlzd vol:
    H7-Z7 0.25/0.21/113.5/47.1 · M7-H8 0.53/0.43 · U7-M8 0.89/0.70 · Z7-U8 1.30/0.94 ·
    H8-Z8 1.77/1.19 · M8-H9 2.34/1.46 · U8-M9 3.13/1.86 · Z8-U9 4.16/2.39 · H9-Z9 5.32/2.93 ·
    M9-H0 6.46/3.37 · U9-M0 7.64/3.80 · Z9-U0 8.69/4.04 · **H0-Z0 9.96/4.48/125.2/95.2** ·
    M0-H1 10.99/4.66 · U0-M1 11.74/4.53 · Z0-U1 12.55/4.42 · H1-Z1 13.26/4.22 (front impl/rlzd up
    to 2.4× — CA-implied vol vastly above realized in whites).
- **Weekly Focus (non-CA)**: buy delta-hedged **10y10y straddles** (Formosa min-lockout draft relaxed
  6y→5y; long expiries already priced it; ~$3.5bn Jan callable issuance vs $5.5bn expected).
  Vol-adjusted 1y rolldown table (1/13/2017): 10y10y vol 72.7nv, 1y rolldown 2.10nv, vol-adjusted
  0.38, 3y z −2.02 (most attractive); 10y20y 64.4nv/0.36/z −1.7; 10y30y 63.2nv/0.36/z −1.0; vs
  3y10y 84.6nv/0.04. Prefer spot over forward vol (spot outperformed in the 2013 taper tantrum).
  Plus 2y30y vs 2y10y beta-weighted straddle switch; 3y 10s30s bear steepeners at inverted costless
  strike spreads; 3m 2s3s5s conditional receiver flies.

---

## 10. `print (13).pdf.md` — Citi *US Rates Weekly*: "Going nuclear (on the curve)"

- **Publisher/date**: Citi Research, 03 Feb 2017 17:02:31 ET, 31 pages. Mathai, Bikbov, Kang,
  Williams. **Unique content: fitted-ED-curve RV + per-contract CA table** (Futures RV section,
  Williams: "Eurodollar fallout").
- **Fitted-curve method (verbatim)**: piecewise **monotonic cubic spline through the first 24 ED
  contracts** (out to Purples), **nine nodes** with tighter spacing in Whites/Reds, optimized to
  minimize error to ED settles; history back to 2013; robustness checked across node placements.
  Uses: cheap/rich per contract (z-scored), micro-fly selection, optimal contracts for slope trades.
- **Known-answer table (Figure 8, close 2/2/2017)**: futures-implied vs fitted rate spread (bp,
  + = cheap) and z-scores for H7…Z2. December contracts all cheap: Z7 +1.30 (1y z 2.3), **Z8 +1.50
  (1y z 3.22)**, **Z9 +1.51 (1y z 2.88)**, Z0 +0.85 (1y z 2.34); richest: U7 −1.40 (z −2.7),
  U0 −1.33 (z −3.1), U8 −0.75. Fresh longs → Decembers; fresh shorts → Septembers. RMSE of
  Reds–Purples vs fit ≈ elevated (~near late-2014 highs) since the election; RMSE not directional
  with Fed expectations.
- **Known-answer table (Figure 11, per-contract CA vs CME swaps, close 2/2/2017, bp)** — CA /
  vs-model: H8 1.12/0.92 · M8 1.54/1.18 · U8 2.05/1.45 · Z8 2.65/1.74 · H9 3.37/2.06 · M9 4.37/2.55 ·
  U9 5.19/2.74 · **Z9 6.21/2.96** · H0 6.44/2.40 · M0 7.92/3.17 · U0 9.12/3.58 · **Z0 11.05/4.64
  (1y z 1.74)** · H1 10.65/3.37 · M1 11.68/3.57 · U1 12.58/3.61 · Z1 14.86/5.00 (1y z 2.52).
  RV logic: CA should be monotone in expiry; EDZ0's CA above neighbor EDH1 and EDZ9's above the
  H9/H0 interpolation ⇒ Decembers cheap vs swaps too ("similar to using asset swap spreads when
  looking at Treasuries").
- **Positioning driver**: AM + leveraged funds **+$16mm DV01** of shorts since the election
  (CFTC TFF, dealers other side); ED **open interest concentrates in December contracts**; weekly
  changes since 11/7/16: change of U9-Z9-H0 fly's spread-to-fitted-curve vs change in Z9-vs-U9/H0 OI
  has **R² = 0.3676** — OI shifts into Z9 cheapen it on the fly. Alt explanation (December = "live
  meeting") rejected as insufficient. This is a direct blueprint for a **futures-microstructure
  conditioning variable on CA/fly measures at the individual-contract level**.
- Rest: short-end CMB/debt-ceiling; vol section (3y 10s30s conditional bear steepeners); overview
  (post-Trump steepening) — not CA-relevant.

---

## 11. `print (17).pdf.md` — Citi *NA Rates Focus*: "Shorts increasing? An alternative view of positioning"

- **Publisher/date**: Citi Research, 16 Jan 2019 11:53:49 ET, 8 pages. Jason Williams. **The key
  positioning-inference doc**: with CFTC data dark (government shutdown), Citi reads positioning
  from two market-traded instruments — the **CME-LCH basis** (long-end) and the **ED convexity
  adjustment** (front-end).
- **CME-LCH basis as a positioning gauge**:
  - History: basis emerged May-2015, near-zero → almost 2bp "in short order"; identical swaps clear
    at a **higher rate on CME than LCH**. Structural cause: Dodd-Frank mandatory clearing;
    **customers clear USD swaps at CME for futures/swaps margin netting** (CME houses Treasury +
    ED futures) while **dealers clear at LCH** (legacy books). 10y basis chart range ~1.0–4.5bp
    (Nov-2015 – Nov-2018).
  - Quantified: in **3m changes**, 10y CME-LCH basis is **31% correlated with TY spec positioning /
    OI** and **51% correlated with changes in 10y yields**. Widening basis = fresh paying at CME =
    fresh shorts; the Oct-2018→Jan-2019 basis collapse accompanied the 3.25%→~2.7% 10y rally /
    short-covering.
  - Caveat (verbatim): fair value of the basis "should not only be driven by positioning but also by
    the costs of clearing on both exchanges", which differ per client/dealer with netting benefits.
- **ED CA as a positioning gauge**: Blues CA had **traded through (below) the Ho-Lee model fair
  value**, indicating the former short base is now long. Levered-fund net ED position / OI (CFTC,
  chart −30%…+15%, Jan-2014–Sep-2018): shorts built through the 2015+ hiking cycle (ED futures
  cheap vs model in 2017/early-2018), covered in Q4-2018 on dovish repricing → CA converged to
  model. ED futures DV01 fixed at $25/bp, non-convex, hence the traded basis vs swaps.
- **Joint read (Jan-2019)**: long-end basis widening + front-end CA collapse ⇒ "investors are
  getting short and into steepeners". Directly the **positioning-conditioned CA signal** for our
  backtests: CA-minus-model as a real-time futures-positioning proxy, CME-LCH basis as the long-end
  counterpart.

---

## 12. `print (2).pdf.md` — Citi *US Rates Weekly*: "Fixing the plumbing"

- **Publisher/date**: Citi Research, 30 Sep 2019 08:43:41 ET, 38 pages. Mathai, Bikbov, Kang,
  Williams, Li. Parent weekly of doc 7 (25 Sep 2019 Vol Lab) — the vol section ("Buying vol for
  less", GBP 15y10y/25y10y flattener, 1y 2s10s/6m 5s10s switch) repeats it verbatim; the
  repocalypse/Fed-reserves overview, gross-basis (TYH0/TYM0 CTD richening), year-end FF-curve fade
  and quarter-end GC analysis are not CA-relevant.
- **Unique and valuable: model-portfolio closed-trades table (Figure 38, "2017 to present") — the
  realized outcomes of both hedged CA trades** ($000s P&L, marked to mid, "calculations include
  transaction fees and other costs"):
  - **"Sell Blues convexity adjustments, hedged": inception Feb 9 2017, unwind Jun 6 2017, initial
    8.8bp → unwind 6.6bp, P&L +$552k** (target $600k, stop $350k; return-on-risk 55.20%, portfolio
    return 0.18%). [= the doc-4 trade; note it was closed the same day the Greens trade opened —
    Blues rolled into Greens, matching the named note *Turning Green from Blue*.]
  - **"Sell Greens convexity adjustment, hedged": inception Jun 6 2017, unwind Aug 8 2017, 4.3bp →
    2.65bp, P&L +$476k** (target $450k, stop $225k; RoR 47.55%, portfolio 0.16%). [= doc 5.]
  - Adjacent rows give the full 2017–2019 model-portfolio history for cross-checks (e.g. "Switch to
    short duration: Sell eurodollars" Sep 7–20 2017 1.61%→1.88% +$1.69mm; "Buy 10y10y straddles"
    Jan 12 2017→Dec 14 2017 72.7→66.25nv −$640k — the doc-9 trade lost).

---

## 13. `print (1).pdf.md` — Citi *US Rates Weekly*: "Eat, pay, spend"

- **Publisher/date**: Citi Research, 27 Mar 2020 18:46:02 ET, 41 pages. Mathai, Bikbov, Kang,
  Williams, Li. COVID-crisis weekly; no ED CA content — relevant only for the long-dated
  curve-convexity franchise and crisis-liquidity diagnostics.
- **Vol section ("Liquidity, vega and convexity", Bikbov)**:
  - Liquidity normalization: Fed buying $75bn USTs/day; 10y OFR rich/cheap (residual on ONR PCs)
    richening back; intraday(30m, 7am–5pm)/close-to-close realized vol ratio normalizing; 1m10y
    gamma 103nv; 10y swap mid-to-bid/offer still ≈ 0.6bp (why not to sell gamma: delta-hedging
    costly). Sell 2y2y USD straddles for ZLB/forward guidance/YCC (2y2y 55nv, 2pm 3/27/2020); buy
    10y10y USD vs EUR straddles (USD 59nv vs EUR 57.4nv, 9:30am 3/27/2020); Formosa bank supply
    $4.9bn in March.
  - **Cheap-convexity watch-list trade: delta-hedged USD 15y5y/20y10y flatteners** — 15y5y/20y10y
    steepened to the top of its range on variable-annuity receiving (VA hedging concentrated in the
    20y sector); the flattener has **slightly positive carry AND positive convexity — "effectively a
    free convexity buy"**; not initiated (bid/offer too wide). **Known-answer grid (3pm 3/26/2020)**
    across 15 long-dated curve pairs × {USD, EUR, GBP}: e.g. USD 15y5y/20y10y curve −5.21bp, 1y z
    +4.21, 3y z +3.58, 1y carry +0.11bp, daily breakeven 0.00bp, 1y realized vol 6.40bp/day,
    BE/realized 0.00; USD 10y10y/20y10y −6.86bp, 1y z 2.04, BE/realized 0.15; EUR equivalents
    deeply negative z (−1.6…−2.5) with BE/realized up to 1.17. The GBP 15y10y/25y10y flattener
    (opened Jan-2020, *In search of cheap vol*) was taken off at a profit this week ("Taking profits
    on GBP 15y10y/25y10y flatteners" — no P&L figure in this doc). Separately, the closed-trades
    table shows the earlier **USD 15y5y/20y10y delta-hedged flatteners**: opened May 8 2019 at
    −12bp, closed Dec 5 2019 at −13bp, **+$155k**.
- Short-end trade (Kang/Williams): short **EDK0 + M0 3s1s widener + M0 3m FRA/OIS tightener in
  0.75:2:1 ratio** (J0 FRA/OIS 101bp, K0 77bp at entry) — LIBOR/OIS convergence trade, not CA.
  Treasuries: record drop in Fed custody holdings; UXY/US steepener held. Supply: 20y reintroduction
  + SOFR FRN expected.

---

## Cross-corpus synthesis (what these 13 add to the backtest program)

1. **CA fair-value model is fully specified and reproducible**: one-factor normal Ho-Lee on
   cap/floor vols; CA measured as 1y-pack rate minus matched-maturity 1y forward swap (CME curve);
   packs used because single ED/FRA spreads are "noisy and hard to trade". Five dated CA tables
   (1/12/17, 1/13/17, 2/2/17 per-contract, 4/18/18, 9/24/19, 2/16/23) provide known-answer tie-outs
   spanning both hiking and easing regimes.
2. **The CA-vs-fly regression franchise** (our "Citi: Blues CA = a + b·fly" target) appears twice
   with fitted coefficients: 2s5s10s versions **10.2 + 21.4·(−0.73, 1, −0.47)** (Jan-2017) and
   **9.7 + 20.6·(−0.705, 1, −0.465)** (Feb-2017); plus the vol-proxy fly **59.7 + 60.5·(−0.71, 1,
   −0.18)** and the ED-curve-slope model **Blues CA model = −0.65 + 0.044·(ED16 − 0.74·ED6)**
   (0.74/−1 DV01, invalid at ZLB).
3. **Positioning conditioning**: dealer/AM/leveraged-fund CFTC TFF series drive CA-minus-model
   (monthly-change regression R² = 0.32 on dealer positioning, 2014–17; inverse AM+LF %-of-OI
   relation, 2019–23); CA even substitutes for CFTC when data is dark (Jan-2019), symmetric with
   the CME-LCH basis at the long end (3m-change correlations: 31% to TY spec/OI, 51% to Δ10y).
4. **Costs and P&L**: two completed hedged CA trades earn +$552k on $200k DV01 (2.2bp entry-to-exit
   on the package) and +$476k on $300k DV01 (1.65bp), inclusive of transaction costs; the 8/8/17
   alert implies ~$20k round-trip cost on a $300k/bp package (~0.07bp). Positive carry is central to
   every construction (+$206k/3m on $100k DV01 package; 1.5bp/3m running on the 2023 SOFR Blues).
5. **Exit rules across vintages**: 2017 Blues $600k/−$350k on $200k DV01 (3bp/−1.75bp); 2017 Greens
   $450k/−$225k target/stop; 2023 SOFR Blues −4bp target / +2.5bp stop on the CA itself.
6. **Venue convention**: all CA measurement vs **CME-cleared** swaps; LCH makes CA look wider; CME
   preferred for margin netting — CME-LCH basis is itself positioning-driven.
