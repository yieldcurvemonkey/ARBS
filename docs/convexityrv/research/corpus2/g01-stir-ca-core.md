# Group 01 — STIR Convexity-Adjustment Core Corpus

Extraction report for the convexity-RV backtest project (CA = futures-implied rate minus matched-maturity forward swap rate, bp).
Source directory: `C:/Users/chris/Downloads/convexityrv_markdown`. All numbers below are quoted from the documents with their
as-of dates; anything reconstructed or garbled by OCR is flagged.

**Doc index**

| # | Doc | Publisher | Date | Core content |
|---|-----|-----------|------|--------------|
| 1 | A better way to sell vol: CME-based convexity adjustments are rich | J.P. Morgan | 2017-05-03 | Dealer-positioning beta of CA richness, implied funding spreads, CME/LCH front-end basis, sell H9/M9 CA rec |
| 2 | US Rates Vol Lab: Value in Greens convexity | Citi | 2017-05-15 | Ho-Lee cap/floor CA model, ED5/ED9 steepener hedge, 17-row CA table (5/12/17), Greens trade ticket |
| 3 | North America Rates Trade Idea: Turning Green from Blue on short convexity | Citi | 2017-06-06 | Blues trade close (+$500K net costs), Greens trade ticket, both fitted hedge equations verbatim |
| 4 | Alert: Take off the hedge on short Greens convexity trade | Citi | 2017-07-13 | Hedge unwind at +$70.5K, Greens CA mark 3.35bp |
| 5 | US Rates Vol Lab: Sell Eurodollar convexity in Blues | Citi | 2018-01-08 | ED6/ED16 hedge (0.74/-1.0), 17-row CA table (1/5/18), Blues trade ticket, positioning thesis |
| 6 | The disappearing convexity bias (stirfutures blog) | Stephen Aikin | 2013-12-16 | Payoff formulas, margining monetisation, post-2011 disappearance, negative Euribor bias episode |
| 7 | QSE: STIR Futures convexity adjustment | Stack Exchange (Chris Taylor Q / Attack68 A) | 2025-06-13/14 | 4 estimation approaches; market-implied calibration; positioning can engulf theory; rateslib CompositeCurve recipe |
| 8 | QSE: Why are FRA/futures convexity adjustments necessary? | Stack Exchange (Attack68 A) | 2019-05-26, upd. 2023-07-27 | Correct risk-based mechanism; full rateslib SOFR worked example (9.6bp naive → ~6bp decay-adjusted) |
| 9 | pm_bbgchat.txt | Bloomberg chat transcript | 2026-01-21 | Long-end 10y10y/20y10y "strikeless vol" — NOT STIR CA; one-line summary only |

---

## 1. J.P. Morgan — "A better way to sell vol: CME-based convexity adjustments are rich" (2017-05-03)

- **Title/publisher/date:** "A better way to sell vol — CME-based convexity adjustments are rich", J.P. Morgan Securities LLC,
  US Fixed Income Strategy, 03 May 2017 (completed 11:10 AM EDT, disseminated 12:01 PM EDT). Authors: Joshua Younger (AC),
  Devdeep Sarkar, Munier Salem. Follow-up to "More than meets the eye" (Younger et al., 2/28/17).

### Fair-value model (theoretical CA)
- Financing bias estimated with a **Ho-Lee model**. The report states "this reduces to" a closed form that the OCR garbled
  (fragments: `= … 1 2/2 … 2` — i.e. the standard Ho-Lee reduction, **[OCR-garbled; standard form is CA ≈ ½σ²·t₁·t₂]**, given
  as a clearly-labeled gloss, not verbatim).
- Vol inputs: **ATM Eurodollar option vols where available (out to the early Greens or so), OTC Libor cap vols otherwise.**
- Note on VM/PAI: cleared OTC FRAs now carry VM too, but price alignment interest (receiver of margin pays interest, usually Fed
  funds, to poster) "aligns the economics of cleared and bilateral FRAs. As a consequence, classical financing bias estimates are
  still appropriate when pricing the convexity adjustment."

### Dealer-positioning ↔ CA relationship (Exhibit 1)
- Metric: **3-year beta (bp per ’000 contracts) and correlation (%) between [observed CA − theoretical estimate] and dealer net
  positioning in Eurodollars (CFTC data)**, plotted against forward term 0.5–4.0y.
- Finding: beta and correlation "consistently positive", with a **term structure that peaks roughly 2 to 3 years forward**
  (i.e. Greens) — attributed to dealers accumulating a net long in EDs vs OTC swaps (LCH-cleared) from issuance-related
  receiving, primarily by SSAs and GSEs. (Chart axes shown 0–1 bp/'000 for beta, 0–100% for correlation; specific point values
  not printed in text.)
- Framing: CA richness = additional slide priced in as compensation for IM funding costs on otherwise risk-less offsetting
  positions, exacerbated when the offsetting exposures face different CCPs (no margin netting).

### Implied funding spread construction (Exhibit 2)
- Based on **observed CA net of theoretical financing bias for the rolling 8th Eurodollar contract vs OTC FRAs cleared through
  LCH**. Static margin assumed on both legs based on CCP estimates for a pvbp-neutral package — **approximately 1.3% total
  margin**. Converted to a spread vs Libor assuming Fed funds interest on IM and 3-month basis swap spreads.
- **Tie-out numbers:** 2y implied funding spread rose from **L+50–100bp last year (2016) to nearly L+300bp recently**
  (as of early May 2017), alongside dealer net ED positioning rising toward ~4,500–5,000 ('000s of contracts axis; chart runs
  Nov-15 → May-17).

### CME vs LCH margin netting (Exhibit 3, as of 5/1/17)
- IM estimates for long ED vs pvbp-weighted (at trade initiation) paid OTC FRA, per contract Z7→Z9, $k per $1bn notional (chart
  axis $0–$1,600k): CME netting (ED and CME-cleared FRA net for margin) gives **roughly 70–80% margin savings** vs the ED/LCH
  two-separate-postings package.
- Despite that, **CME-based CAs (net of theoretical financing bias) trade at roughly 80% of LCH-based** across much of the ED
  complex — i.e. the netting benefit is NOT priced.
- CME did not provide margin estimates beyond Z9 OTC FRAs at the time.

### CME/LCH basis, front end (Exhibit 4, since May 2016, as of 5/1/17)
- Front-end CME/LCH basis "has remained exceptionally tight since it first emerged in mid-2016, remaining **well under 1 bp**
  for the entirety of that period and spending most of its time **around 0.25 bp**", while longer tenors (2Y/5Y/10Y/30Y shown,
  chart axis 0–6 bp running) widened.

### Implied funding spreads by contract (Exhibit 5)
- Implied funding spread (bp/year) by contract Z7…Z9 from CAs using CME- vs LCH-cleared FRAs; chart axis 0–1200 bp/yr with a
  "typical funding spread" reference line. CME-based implied funding spreads trade **at a multiple of** LCH-based, "again
  peaking around the early Greens".

### Trade recommendation
- **Sell the H9 and M9 (EDH9, EDM9) convexity adjustments: buy H9 and M9 Eurodollars versus paying fixed in CME-facing OTC
  FRAs** — positions for a wider front-end CME/LCH basis and monetizes rich CAs. Rationale for the front end over 10y/30y
  CME/LCH: contract expiry is ~2 years away, so the actual-vs-implied funding spread can be monetized "on a more realistic
  timescale" (a pull-to-expiry argument). No explicit target/stop/costs given.

---

## 2. Citi — "US Rates Vol Lab: Value in Greens convexity" (2017-05-15)

- **Title/publisher/date:** "US Rates Vol Lab — Value in Greens convexity", Citi Research, Rates, Developed Markets North
  America, 15 May 2017 11:34:00 ET, 24 pages. Authors: Ruslan Bikbov (AC), Jason Williams (AC).

### CA definition and model (verbatim conventions)
- "Convexity adjustments for 1y ED packs are computed as **the spread between the pack's rate (the average of 4 ED rates in the
  pack) and matched-maturity forward 1y swap rate**."
- "The model for convexity adjustment is **the Ho-Lee model calibrated to cap/floor vols**. Implied vol is calculated by
  matching the model to the observed convexity adjustment. Realized vol is 3m realized vol of the corresponding pack."
- Analysis is on 1y packs "because individual ED/FRA spreads are noisy and hard to trade" (stated in the Jan-2018 sibling doc,
  same table machinery).

### Positioning thesis
- Widening of CAs from fair value driven by "massive short positioning" in ED futures (hawkish-Fed expression). YTD 2017:
  asset managers and leveraged funds reduced net ED shorts (CFTC DV01 measure incl. futures and options); dealers' longs
  declined from highs. Blues and Golds CAs moved back toward fair value; **Greens remained dislocated near historical highs**
  because short covering was concentrated in Blues+; open interest in Reds and Greens kept trending up.
- FRA/OIS angle: some ED shorts believed to be vs OIS; further FRA/OIS tightening could trigger capitulation → risks to Greens
  CA "skewed tighter".

### Fitted hedge relationship (the fair-value regression)
- "The fair value of Greens convexity (based on our implementation of the standard Ho-Lee model calibrated to cap/floor
  volatility) is highly correlated with the **ED5/ED9 curve with −1/1.18 DV01 weights**" (Figure 5 caption: ED5 and ED9
  expressed as rates in % terms; the 6/6/17 doc prints the fitted line verbatim as **`-3.53*ED5+4.17*ED9`** — see doc 3).
- Rationale: steeper curve ⇒ greater Fed-path uncertainty ⇒ higher vol; hedge is slightly short the market (front-end vols
  directional with rates via zero-bound effect); the weighted steepener has "about flat carry".

### Trade ticket (pricing as of 9:30am 5/15/2017)
- **Sell $100k DV01 of Greens CA**: buy **1000 of M9–H0 packs** (1000 of each of the four contracts EDM9/EDU9/EDZ9/EDH0) and
  **pay $1bn on a matched-maturity CME swap (M19–M20 IMM quarterly money swap) at about 4.5bp** in ED/swap-spread terms.
  "Consistent with the standard market practice, **both fixed and floating legs of this swap have a quarterly payment
  frequency**."
- Hedge: **sell 167 contracts of EDM9 at 98.065; buy 141 contracts of EDM8 at 98.41** (9:30am 5/15/2017).
- Carry: "**rolls positively by about 0.88bp over the first three months**." Risk: further build-up of Greens shorts.
  No explicit target/stop in this doc (the 6/6/17 re-initiation carries them).

### KNOWN-ANSWER TIE-OUT — Figure 53: Convexity adjustments for 1y Eurodollar packs, close of 5/12/17
Columns: CA (bp) | 1wk chg (bp) | 3m Z | 1y Z | VsModel (bp) | model-dislocation 3m Z | 1y Z | 3m roll (short cvx, bp) |
Implied vol | Realized vol | Impl/Rlzd | Cap-vol Impl/Rlzd.

| Pack | CA bp | 1w chg | 3m Z | 1y Z | VsModel bp | 3m Z | 1y Z | 3m roll | ImplVol | RlzdVol | I/R | CapV I/R |
|------|-------|--------|------|------|-----------|------|------|---------|---------|---------|-----|----------|
| M7-H8 | 0.23 | -0.01 | -0.77 | 0.00 | 0.20 | -0.73 | 0.18 | 0.12 | 120.6 | 48.2 | 2.5 | 0.7 |
| U7-M8 | 0.48 | -0.03 | -0.84 | 0.05 | 0.42 | -0.76 | 0.29 | 0.25 | 124.6 | 53.2 | 2.3 | 0.7 |
| Z7-U8 | 0.84 | -0.04 | -0.94 | 0.14 | 0.72 | -0.80 | 0.48 | 0.36 | 126.9 | 57.7 | 2.2 | 0.7 |
| H8-Z8 | 1.32 | -0.06 | -0.99 | 0.35 | 1.12 | -0.74 | 0.81 | 0.48 | 128.7 | 62.0 | 2.1 | 0.7 |
| M8-H9 | 1.92 | -0.06 | -0.95 | 0.59 | 1.59 | -0.51 | 1.12 | 0.60 | 130.1 | 64.9 | 2.0 | 0.8 |
| U8-M9 | 2.60 | -0.03 | -0.87 | 0.77 | 2.09 | -0.02 | 1.36 | 0.68 | 130.2 | 67.6 | 1.9 | 0.8 |
| Z8-U9 | 3.33 | -0.03 | -0.92 | 0.79 | 2.57 | 0.39 | 1.46 | 0.72 | 129.0 | 70.0 | 1.8 | 0.8 |
| H9-Z9 | 4.09 | -0.06 | -1.01 | 0.73 | 3.02 | 0.64 | 1.48 | 0.77 | 127.4 | 72.2 | 1.8 | 0.9 |
| M9-H0 | 4.91 | -0.10 | -1.14 | 0.65 | 3.43 | 0.82 | 1.48 | 0.81 | 125.6 | 73.7 | 1.7 | 0.9 |
| U9-M0 | 5.53 | -0.14 | -1.40 | 0.46 | 3.57 | 0.54 | 1.43 | 0.62 | 121.3 | 74.8 | 1.6 | 0.9 |
| Z9-U0 | 5.95 | -0.16 | -1.78 | 0.14 | 3.46 | -0.04 | 1.07 | 0.43 | 115.4 | 75.3 | 1.5 | 1.0 |
| H0-Z0 | 6.62 | -0.17 | -1.92 | 0.09 | 3.53 | -0.37 | 0.93 | 0.66 | 112.3 | 75.5 | 1.5 | 1.0 |
| M0-H1 | 7.01 | -0.23 | -1.87 | -0.18 | 3.30 | -1.16 | 0.49 | 0.40 | 107.4 | 75.3 | 1.4 | 1.0 |
| U0-M1 | 7.65 | -0.35 | -1.84 | -0.33 | 3.27 | -1.31 | 0.30 | 0.64 | 104.7 | 75.1 | 1.4 | 1.0 |
| Z0-U1 | 8.64 | -0.44 | -1.94 | -0.33 | 3.53 | -1.42 | 0.35 | 0.99 | 104.3 | 74.8 | 1.4 | 1.0 |
| H1-Z1 | 9.55 | -0.54 | -2.09 | -0.37 | 3.67 | -1.59 | 0.36 | 0.91 | 103.3 | 74.2 | 1.4 | 1.1 |
| M1-H2 | 10.55 | -0.62 | -2.35 | -0.27 | 3.86 | -1.74 | 0.50 | 1.00 | 102.5 | 73.9 | 1.4 | 1.1 |

### The original Blues trade (restated, "Further details on trade ideas")
- From "Sell Blues convexity adjustments, hedged", **09 Feb 2017 09:12 ET**, pricing as of **8am 2/9/2017**:
  **sell $200k DV01 of Blues CAs** = buy **2000 of H0–Z0 Eurodollar packs** and **pay $2bn on a matched-maturity
  (3/18/20–3/17/21) CME-cleared swap at 8.8bp** of spread. Hedge: **pay the belly of the 2s5s10s swap fly with notional
  weights $147mm/−$85.6mm/$20.89mm (0.705/−1/0.465 DV01 weights) at −18.2bp** in DV01-weighted-fly-level terms.

### Ancillary tie-outs in the same doc (close of 5/12/17)
- ATM swaption normal-vol grid: e.g. 1y1y 48.3, 1y10y 72.9, 5y10y 77.8, 10y10y 70.2 (Figures 6–7); rich/cheap-to-rates
  residual grid regressed on 3 curve PCs using 1996–2008 spliced with 2017 data "to exclude the near-zero rate policy regime".
- Board vs swaption (Figure 46): FVN7 board 67.6 vs CTD-matched swaption 62.9 (ratio 1.07); USN7 57.7 vs 61.7 (0.93);
  swaption strike convention = board strike yield + invoice spread; FVN7 futures DV01 4.70 / swap DV01 3.99, TYN7 7.62/6.21,
  USN7 19.82/15.16 (Figure 52).
- Chart scale points: Greens CA chart 0–6bp, Blues 2–12bp, Golds 5–15bp over May-16→May-17 (Figures 54–56).

---

## 3. Citi — "North America Rates Trade Idea: Turning Green from Blue on short convexity" (2017-06-06)

- **Title/publisher/date:** "North America Rates Trade Idea — Turning Green from Blue on short convexity", Citi Research,
  06 Jun 2017 14:30:16 ET, 7 pages. Bikbov/Williams.

### Blues trade CLOSE (P&L tie-out incl. transaction costs)
- Entry recap (2/9/17): bought 2000 H0–Z0 Blues packs, paid $2bn matched-maturity CME-cleared swap **at 8.8bp** the spread,
  paid belly of 2s5s10s swap fly $147mm/−$85.6mm/$20.89mm at **−18.2bp**.
- Close (pricing as of **1:30pm 6/6/17**): **H0–Z0 CA at 6.6bp; 2s5s10s fly at −16.5bp**. Target of +$600K P&L not reached.
- **"Our net P&L, net transaction costs, is +$500K."** ⇒ on the stated marks the gross convexity leg made ~2.2bp × $200k/bp
  = ~$440K and the fly leg ~1.7bp on its DV01; the printed net-of-costs figure +$500K is the only all-in cost-inclusive P&L
  datapoint in this corpus.

### Fitted equations — VERBATIM (Figure 1 and Figure 2 legends)
- Blues CA proxy hedge (chart legend, Jan-10→Jan-17 history, bp axis 0–20):
  **`scaled 2s5s10s fly: 10.2+21.4*(-0.70*2y+5y-0.46*10y)`**
  (i.e. Blues CA fair-ish level ≈ 10.2 + 21.4 × weighted fly, weights −0.70/+1/−0.46 on 2y/5y/10y swap rates in %).
- Greens CA fair-value hedge (chart legend, history Jan-00→Jan-15+, bp axis 0–14): model plotted against
  **`-3.53*ED5+4.17*ED9`**, "ED5 and ED9 are expressed as rates in % terms". Note 4.17/3.53 ≈ 1.18 ⇒ the −1/1.18 DV01-weight
  statement in doc 2. No R² printed for either fit ("highly correlated" only).

### Greens trade ticket (pricing as of 1:30pm 6/6/17)
- **Sell $300k DV01 of Greens CA**: buy **3000 of M9–H0 packs** (3000 of each of the four contracts) and **pay $3bn on a
  matched-maturity CME swap (M19–M20 IMM quarterly money swap) at 4.3bp** in ED/swap-spread terms; both swap legs quarterly.
- Hedge = **EDM8/EDM9 steepener with 1/−1.18 DV01 weights**: **sell 500 contracts of EDM9 at 98.215; buy 424 contracts of
  EDM8 at 98.46**.
- Carry: "**rolls positively by about 0.7bp over the first three months**."
- **Target: profit of $450K. Stop: loss of $225K.** Main risk: further build-up of ED shorts.

---

## 4. Citi — "Alert: Take off the hedge on short Greens convexity trade" (2017-07-13)

- **Title/publisher/date:** "North America Rates Trade Idea — Alert: Take off the hedge on short Greens convexity trade",
  Citi Research, 13 Jul 2017 09:18:59 ET, 6 pages. Bikbov/Williams.
- **Tie-outs (as of 8:30am 7/13/17):** Greens CA mid for the M9–H0 pack **3.35bp** (entered 4.3bp on 6/6/17) ⇒ mark-to-market
  gain on the convexity leg **$285K** at current mid ($300k DV01 × 0.95bp).
- Hedge taken off at **+$70.5K** dollar P&L: "we **sell 500 contracts of EDM8 at 98.385 and buy 424 contracts of EDM9 at
  98.095**". **Discrepancy note (data, not noise):** the entry leg was sell 500 EDM9 / buy 424 EDM8, so a clean unwind would be
  buy 500 EDM9 / sell 424 EDM8 — the alert's contract counts are swapped across the two contracts (likely a typo in the
  original). Using entry prices (EDM8 98.46→98.385 on 424 lots, EDM9 98.215→98.095 short 500 lots) the short-M9/long-M8
  steepener P&L = (12.0bp×500 − 7.5bp×424)×$25 = $70,500 only if the 500-lot is EDM9 — consistent with the alert's counts
  being transposed.
- Rationale: hedge outperformed model fair value on recent curve steepening; keeps **short Greens CA outright** (comfortable
  outright short Greens vol; implieds expected unsupported as rates grind lower over summer). Risk: further ED short build-up.
- Rest of doc is disclosures.

---

## 5. Citi — "US Rates Vol Lab: Sell Eurodollar convexity in Blues" (2018-01-08)

- **Title/publisher/date:** "US Rates Vol Lab — Sell Eurodollar convexity in Blues", Citi Research, 08 Jan 2018 11:07:38 ET,
  25 pages. Bikbov/Williams.

### Thesis and positioning mechanics
- Blues CAs widened to Ho-Lee fair value since early-September yield lows even as implieds collapsed — driven by stretched
  shorts (CFTC: asset managers + leveraged funds) positioning for a hawkish Fed. Margin asymmetry stated explicitly:
  **CME/LCH IM models for swaps/FRAs use a 5-day close-out period; CME uses only 1- or 2-day close-out for ED futures** ⇒
  futures enjoy considerably smaller IM, making them the instrument of choice (also cited: higher transparency).
- Dealers on the other side hold significant ED longs; "**Convexity adjustments have therefore widened to compensate dealers
  for this concentration risk.**"
- Steepener crowding: Greens/Blues slopes such as **EDH0/EDH1 within only a few bp of the flattest levels in fifteen years**;
  hence widening concentrated in Blues (Greens only marginally wider).
- Historical regularity (Figure 4): monthly changes 1/1/13–12/26/17 show short capitulation richens CAs relative to fair value.
- Clearing venue: analysis based on the **CME FRA/swap curve**; CAs are **wider for LCH-cleared swaps**, but Citi recommends
  clearing on CME — CME-LCH basis had retraced from December highs, and CME "allows netting futures and swap positions for
  margin calculations".

### Fitted hedge (the Blues fair-value regression)
- "The model value of Blues CA can be reasonably accurately hedged with an **ED6/ED16 steepener with 0.74/−1.0 DV01
  weights**." Weights **calibrated on the pre-2008 sample** because "vol-curve relationship exhibited a structural break in the
  ZLB regime"; with effective Fed funds at 1.4% the relationship "should be back to normal", and the same curve "did a fine job
  explain[ing] CA fair value in 2017" (Figure 6). Hedge is slightly short the market (positive vol-rate directionality in
  short tails). The **ED6/ED16 steepener with these weights carries positively by ~2bp in 3m** — more carry-efficient than
  buying 3y1y swaptions or 3x4 cap/floor vol.

### Trade ticket (as of 10am on "1/5/2017" — sic; context is clearly **1/5/2018**; discrepancy noted)
- **Sell $100K DV01 of Blues CA**: buy **1000 of H1–Z1 packs** (1000 of each of the four contracts) and **pay $1bn on a
  matched-maturity (3/17/21–3/16/22) CME-cleared swap at 6.5bp** in spread terms; both legs quarterly.
- Hedge: **buy 130 EDM9 (ED6) contracts at 97.53; sell 176 EDZ1 (ED16) contracts at 97.495**.
- Carry: "**The package carries positively by about +$140K over the next three months (+$130K from the short CA trade and
  +$10K from the hedge).**" Risk: further positioning imbalance widening Blues CAs beyond fair value. No target/stop printed.

### KNOWN-ANSWER TIE-OUT — Figure 54: Convexity adjustments for 1y Eurodollar packs, close of 1/5/18
Same column layout/conventions as the 5/12/17 table (Ho-Lee calibrated to cap/floor vols; three most attractive short-CA
trades bolded per metric in the original).

| Pack | CA bp | 1w chg | 3m Z | 1y Z | VsModel bp | 3m Z | 1y Z | 3m roll | ImplVol | RlzdVol | I/R | CapV I/R |
|------|-------|--------|------|------|-----------|------|------|---------|---------|---------|-----|----------|
| H8-Z8 | 0.17 | 0.00 | 0.46 | -0.54 | 0.14 | 0.44 | -0.61 | 0.08 | 92.0 | 34.4 | 2.7 | 1.0 |
| M8-H9 | 0.35 | -0.03 | 0.68 | -0.62 | 0.28 | 0.71 | -0.70 | 0.17 | 95.2 | 35.3 | 2.7 | 1.0 |
| U8-M9 | 0.58 | -0.08 | 0.75 | -0.70 | 0.46 | 0.77 | -0.77 | 0.23 | 96.5 | 37.1 | 2.6 | 1.1 |
| Z8-U9 | 0.86 | -0.12 | 0.74 | -0.78 | 0.65 | 0.71 | -0.85 | 0.28 | 96.5 | 39.1 | 2.5 | 1.1 |
| H9-Z9 | 1.18 | -0.15 | 0.77 | -0.87 | 0.86 | 0.67 | -0.93 | 0.32 | 95.9 | 41.4 | 2.3 | 1.1 |
| M9-H0 | 1.58 | -0.18 | 1.07 | -0.87 | 1.10 | 1.00 | -0.90 | 0.40 | 96.1 | 43.0 | 2.2 | 1.2 |
| U9-M0 | 2.03 | -0.21 | 1.36 | -0.84 | 1.35 | 1.36 | -0.83 | 0.45 | 96.2 | 44.2 | 2.2 | 1.2 |
| Z9-U0 | 2.54 | -0.23 | 1.61 | -0.76 | 1.62 | 1.64 | -0.71 | 0.52 | 96.3 | 45.2 | 2.1 | 1.2 |
| H0-Z0 | 3.15 | -0.24 | 1.81 | -0.66 | 1.92 | 1.82 | -0.53 | 0.60 | 96.9 | 46.2 | 2.1 | 1.3 |
| M0-H1 | 3.86 | -0.19 | 1.88 | -0.56 | 2.28 | 2.13 | -0.29 | 0.71 | 98.0 | 47.3 | 2.1 | 1.3 |
| U0-M1 | 4.75 | -0.12 | 2.27 | -0.36 | 2.77 | 2.35 | 0.20 | 0.88 | 99.9 | 48.5 | 2.1 | 1.3 |
| Z0-U1 | 5.81 | -0.06 | 2.51 | -0.07 | 3.41 | 2.30 | 0.81 | 1.07 | 102.3 | 49.6 | 2.1 | 1.3 |
| H1-Z1 | 7.13 | -0.10 | 2.44 | 0.28 | 4.26 | 2.21 | 1.37 | 1.32 | 105.4 | 50.4 | 2.1 | 1.3 |
| M1-H2 | 8.24 | -0.23 | 2.30 | 0.41 | 4.87 | 2.03 | 1.54 | 1.11 | 106.0 | 51.0 | 2.1 | 1.3 |
| U1-M2 | 9.09 | -0.36 | 2.18 | 0.36 | 5.18 | 1.95 | 1.52 | 0.85 | 104.5 | 51.7 | 2.0 | 1.3 |
| Z1-U2 | 9.60 | -0.42 | 2.04 | 0.16 | 5.11 | 1.86 | 1.36 | 0.51 | 101.1 | 52.5 | 1.9 | 1.3 |
| H2-Z2 | 9.78 | -0.30 | 1.75 | -0.20 | 4.69 | 1.73 | 1.02 | 0.18 | 96.4 | 53.4 | 1.8 | 1.3 |

Note the recommended H1–Z1 pack: CA 7.13bp / VsModel +4.26bp / 3m roll 1.32bp — highest roll on the curve (trade text quotes
6.5bp spread on the specific matched swap vs the table's 7.13bp mid, different construction/time).

### Ancillary tie-outs (close of 1/5/18)
- ATM normal vols: 1y1y 44.7, 1y10y 59.8, 3m10y 52.8, 10y10y 62.2, 10y30y 54.0 (Figures 7–8); 1y2y implied/1m realized ≈ 1.27.
- Board vs swaption (Figure 47): USH8 board 54.8 vs CTD-matched swaption 53.3 (board/swpn 1.03) vs futures/swap realized-vol
  ratios 1.14 (1m) and 1.11 (3m) — board vol cheap on RV. FV/TY/US futures DV01s: FVG8 4.61 (swap 3.95), TYG8 7.56 (6.14),
  USG8 19.72 (14.67).
- Callable supply: ~$1.14bn long-dated callables issued first week of Jan-18; Jan-17 comparison $12.1bn gross / vega $23.9mn;
  FY2017 $44.2bn gross, $37.0bn net, vega $81.3mn (Figure 38).
- Standard conditional curve/fly tables (Figures 58–61) — same machinery as May-17 doc; not CA-specific.

---

## 6. Stephen Aikin — "The disappearing convexity bias" (stirfutures blog, 2013-12-16)

- **Title/publisher/date:** "The disappearing convexity bias", Welcome to STIR futures (supporting site for Aikin's *STIR
  Futures* book), December 16, 2013.
- **Payoff formulas (verbatim):**
  - Short STIR future: **`(L% − F%) * 10000 * $25`**
  - Short FRA: **`((F% − L%) * Notional * 0.25) / (1 + L% * 0.25)`**
  - F% = FRA forward rate / rate implied by STIR; L% = FRA-maturity LIBOR / futures EDSP; 0.25 = 3m accrual (ACT/360 in
    reality for USD/EUR); $25 = Eurodollar tick value per bp.
- **Worked example (tie-out):** short 1000 ED futures vs offsetting short **$1005m** 3m FRA (slightly over $1000m to
  compensate for discounting), both at 2%. Rates 2%→2.10%: **+$250,000** credit to the ED variation margin account and a debit
  of slightly less than that on the FRA collateral (zero threshold). Rates 2%→1.90%: **−$250,000** ED debit, FRA credit
  slightly more than that.
- Mechanism: FRA's discounted payoff is convex vs futures' linear payoff ⇒ futures should trade at a **higher rate** than the
  equivalent FRA; the difference (convexity bias) is "dependent on and driven by term and short rate volatility". Monetised
  via margining — beneficial VM flows re-lent higher / financed lower, "effectively a long gamma payoff".
- **Disappearance:** post-crisis CCP clearing of FRAs/swaps (traction from ~2011) margined both sides futures-style, so the ED
  bias "largely disappeared" (chart shows pre-2011 ED convexity bias vs ~zero after) — the CME cross-margining of ED vs
  CME-cleared USD swaps being the capital-efficient case.
- **Negative bias episode:** Euribor bias "went slightly negative this summer" (2013) because LIFFE Euribor futures margin
  could not be netted against Euro FRAs cleared at SwapClear — double margin + funding cost above interest received on margin
  exceeded the bias value; "there was nothing to prevent the bias going negative!" (Direct precedent for the JPM/Citi
  positioning-and-margin-driven CA framework, and for empirically observed positive CA prices in doc 7.)

## 7. Quant SE — "STIR Futures convexity adjustment" (asked 2025-06-13, answered 2025-06-14)

- **Title/publisher/date:** Quantitative Finance Stack Exchange question by Chris Taylor (Jun 13, 2025), answer by Attack68
  (rateslib author, Jun 14, 2025).
- **Four estimation approaches enumerated in the question:** (1) short-rate model (Ho-Lee, Hull-White) calibrated to futures/
  IRS and/or swaptions; (2) heuristics from convexity PnL of a hedged IMM-IRS-vs-STIR-futures portfolio with swaption-implied
  covariances; (3) same heuristics with historical covariances (realized vol/correlation from futures rates); (4) imply the
  market convexity directly from STIR futures vs IRS rates (IRS-only curve → read futures off it; difference = market CA).
- **Answer (Attack68):** 1–3 are theoretical; "they don't include supply and demand dynamics… It depends upon positioning,
  clearing house margin, where the futures tend to trade (EUREX, ICE-liffe, CME) and what are the respective swaps clearing
  house basis markets. These effects can **engulf** the theoretical prices. **I've also seen real market positive convexity
  prices, which are impossible theoretically.**" He has "always adopted approach 4", calibrating convexity inputs to major
  traded short swaps with "some simple parameter model for smoothing the convexity over the contracts".
- **Implementation recipe (rateslib 2.0):** `stir_curve` (monthly nodes) + spline-interpolated `convexity` curve;
  `swaps_curve = CompositeCurve([stir_curve, convexity])`; Solver takes 12 monthly 1m "STIR proxy" IRS on `stir_curve` plus 6m
  and 12m IRS on `swaps_curve`; the convexity curve then yields per-contract adjustments. **[OCR-garbled code block: node
  dates/rates interleaved; quoted structure is reconstructed from the fragments, the outputs below are verbatim.]** Example
  market inputs (s=): 1.93, 1.94, 1.98, 2.02, 2.05, 2.070, 2.09, 2.146, 2.15, 2.2, 2.25, 2.3, 2.32, 2.37 [order partially
  garbled]; **12 printed convexity node outputs (tie-out for the smoothing model, in %):** 0.003867533154249832,
  0.004124170133401605, 0.004637442503942974, 0.0054173163792192724, 0.00646096935165833, 0.007765535595627427,
  0.009244030058451792, 0.010567096097501677, 0.011607910720368153, 0.012387808800557796, 0.012909634790236879,
  0.013170544225162768 — i.e. ~0.39bp at 1m rising smoothly to ~1.32bp at 12m.
- **Liquidity color (river_rat comment):** "very little pricing information passed the reds… **The greens only trade at 40%
  the ADV of the reds**, blues even worse"; 1m futures needed for month-end weirdness, futures needed for FOMC jumps; "after
  the reds switch to IRS's". Bloomberg's <EDS GO> does something similar to the market-implied approach.

## 8. Quant SE — "Why are FRA/futures convexity adjustments necessary?" (2019-05-25; SOFR example added 2023-07-27)

- **Title/publisher/date:** Quantitative Finance Stack Exchange, question by "quanty" (May 25, 2019); principal answer by
  Attack68 (May 26, 2019; practical SOFR example added 27 July 2023). Viewed 19k times.
- **Core correction:** the convexity adjustment "has nothing to do with profits/losses being immediately recognised on the
  future through margin settlement, and potential reinvestment" (a "very common belief… possibly due to bad wording in
  Hull"). Three arguments: (i) collateralised FRA and margined future have equivalent reinvestment patterns ($10000 gain →
  $1 OIS either way); (ii) a collateralised CFD settling on the FRA date has the same convexity with no daily margin; (iii)
  intraday vol with continuous delta hedging matters even if the future closes unchanged every day.
- **Risk-based mechanism:** FRA settlement `P = vNd(r−R)/(1+dr)` — the `(1+dr)⁻¹` self-discounting term makes FRA delta
  state-dependent (`∂P_fra/∂r = vNd/(1+dr) · (1 − d(r−R)/(1+dr))`) while futures delta is constant (`∂P_fut/∂r = Ñd`).
  Rehedging the FRA-vs-future package systematically buys high/sells low (paid FRA) or locks in gains (received FRA) ⇒ value
  proportional to volatility; "futures are always oversold relative to FRAs… The rates on FRAs are naturally lower than those
  for futures and the difference is called the convexity bias." Comment thread: with OIS discounting and parallel moves,
  `∂v/∂r_i` (discounting to FRA settlement) dominates ⇒ longer maturity = bigger adjustment.
- **KNOWN-ANSWER worked example — SOFR, as of 2023-07-27 (rateslib):**
  - Flat SOFR curve: `Curve({2023-07-27: 1.0, 2025-07-27: 0.9})` solved to a 2Y IRS at **4.75%**.
  - Received **Red Jun-25 IMM SOFR swap (2025-06-18 → 2025-09-17)**, notional **N = 1,133,694,000**, fixed rate
    **4.666320863240951** ⇒ NPV precisely zero; delta exactly **25k USD** ⇒ hedged by selling exactly **1000 lots** of Jun-25
    CME 3M SOFR futures.
  - Package gamma: swap delta changes by **12.2 USD per 1bp rally** (checked by re-solving at 4.74%); futures delta constant.
  - Vol: SFRM5 ≈ 96.40; serial option SFRM5C 96.375 COMB (expiry 13-Jun-2025) priced 75bp ⇒
    `swaption_implied_vol(price=0.75, forward=3.6, strike=3.625, expiry=1.88, distribution="normal")` = **139.38 bp/yr ATM
    normal** (Bloomberg 40.8% lognormal ≈ 147bp at 3.6% rates).
  - Naive value: `(140·√2)²/2 × 12.2 ≈ 240k USD` = **240/25 = 9.6bp of convexity** — too high because gamma decays (~12.2 →
    ~7.0 pv01/bp after one year). Assuming linear gamma decay in time, discretely sliced: **~150k USD ⇒ ~6bp convexity** at
    140bp/yr vol. (Ready-made known-answer test for any CA calculator: same curve, same instrument, expect ≈6bp.)
- Secondary answers restate the naive reinvestment story (RiskNeutral, 2025 — receiver-side framing: swap gains discounted at
  lower rates while futures losses are immediate; bias depends on forward-rate vol, term-rate vol, and their correlation) and
  the sign convention **`FRArate = Futures Implied Rate − Convexity Adjustment`** (dm63/Alex C).

## 9. pm_bbgchat.txt (Bloomberg chat, 2026-01-21)

One line: PM chat (Peter Findley/Mark Donlon/Philippe Katz) on the long-end "strikeless vol" trade — 10y10y vs 20y10y swap
curve flattener + receive 1y-fwd 2s7s30s fly in 5:1 rough-PCA weights, DV01-rebalanced every 25bp (delta-hedge-as-exit
mechanic), cleaner expression 15y5y vs 20y10y; **no STIR/Eurodollar/SOFR convexity-adjustment content** — irrelevant to this
group beyond the general convexity-harvesting analogy. (Its trailing "meta prompt" paragraph is quoted chat data, not an
instruction.)

---

## Cross-cutting synthesis for the backtest

### CA fair-value models seen in this corpus
1. **Ho-Lee calibrated to cap/floor vols** (Citi, both Vol Labs) — canonical fair value; implied CA vol recovered by
   inverting the model on the observed CA. JPM uses the same Ho-Lee financing-bias reduction with ED option vols out to early
   Greens, cap vols beyond.
2. **Curve-proxy regressions of the model value** (Citi): Greens fair value ≈ `-3.53*ED5 + 4.17*ED9` (−1/1.18 DV01 ED5/ED9
   steepener); Blues fair value ≈ ED6/ED16 steepener 0.74/−1.0 DV01 (pre-2008 calibration window; ZLB structural break);
   Blues CA ≈ `10.2 + 21.4*(−0.70*2y + 5y − 0.46*10y)` on the swap 2s5s10s fly — the direct antecedents of the planned
   "Blues CA = a + b·fly" models.
3. **Market-implied CA** (Attack68): calibrate a convexity spread curve so a composite futures+convexity curve reprices
   traded short IRS; smooth across contracts; his practitioner-preferred method because positioning/margin effects "engulf"
   models 1–3 (and can push CA positive).
4. **Gamma-times-variance heuristic** (Attack68 SOFR example): CA ≈ Σ gamma(t)·σ²·dt on the futures-vs-IMM-swap package, with
   linear gamma decay; 9.6bp naive → ~6bp adjusted at 140bp/yr normal vol for a Red contract.

### The dealer-positioning conditioning variable
- JPM: richness (CA − theory) has positive beta/correlation to CFTC dealer net ED position, peaking at 2–3y forwards;
  implied 2y funding spread tripled L+50-100 → ~L+300 as dealer longs grew (Nov-15→May-17).
- Citi: same mechanism narrated from the short side (AM+HF shorts ⇒ dealer longs ⇒ CA widens as concentration-risk
  compensation); short capitulation richens CA vs fair value (monthly changes 1/1/13–12/26/17); IM asymmetry (1–2 day ED
  close-out vs 5-day swaps) is why the flow expresses in futures.

### CME-LCH conditioning
- Front-end CME/LCH FRA basis <1bp, mostly ~0.25bp since mid-2016 (as of 5/1/17) vs wider 2y–30y; CME-based CA ≈ 80% of
  LCH-based despite 70–80% IM netting savings ⇒ JPM's "CAs rich AND CME/LCH too narrow" double trade (buy H9/M9 EDs vs
  CME-cleared FRAs). Citi (Jan-18): CAs wider on LCH-cleared swaps; prefer CME clearing for netting; CME-LCH retracement from
  Dec-17 highs cited as a timing input.

### Conventions to replicate
- **Pack CA:** average of the 4 contract rates in the pack minus the matched-maturity forward 1y swap rate (Citi). Matched
  swap = IMM-dated quarterly-quarterly money swap, CME-cleared (e.g. M19–M20; 3/17/21–3/16/22), quoted as ED/swap spread bp.
- **Hedge sizing:** DV01 weights on ED contract steepeners (1/−1.18; 0.74/−1.0) executed in round contract counts
  (167/141, 500/424, 130/176 per $100k CA DV01 unit).
- **Trade unit economics:** $100k CA DV01 ≙ 1000 packs + $1bn matched swap. Carry/roll quoted per 3m (0.7–1.32bp on the CA
  leg; +$140K package). Targets/stops where given: +$450K/−$225K (Greens, $300k DV01); +$600K target on the $200k-DV01 Blues
  trade closed early at +$500K net of transaction costs.
- **Sign convention:** FRA rate = futures-implied rate − convexity adjustment; futures rate > forward/FRA rate in theory;
  empirically CA can print positive-price (futures rich) under positioning/margin distortions.

### Discrepancies / cautions logged
1. 7/13/17 alert's unwind leg contract counts are transposed vs the 6/6/17 entry (500 on EDM8 vs entry's 500 on EDM9).
2. Jan-2018 report prints pricing timestamps "as of 10am on 1/5/2017" — context (close-of-1/5/18 tables throughout) makes
   clear it is 1/5/2018.
3. OCR damage: JPM's Ho-Lee formula and the rateslib code block in doc 7 are garbled in the markdown; verbatim outputs were
   preserved, formulas glossed and flagged above.
4. Citi quotes "highly correlated"/"reasonably accurately" for the fitted hedges but prints **no R² or standard errors**
   anywhere in this corpus — the regression quality must be re-established in-house before use as a fair-value model.
