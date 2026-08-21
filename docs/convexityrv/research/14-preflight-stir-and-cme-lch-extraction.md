<!-- Verbatim return of a preflight investigation agent, 2026-08-20/21.
     Measured on this machine; see the report's own probe list. Kept as
     research evidence, not as a design document. -->

# Preflight scout: STIR pack convexity and CME-LCH basis extraction

# STIR / Pack Convexity + CME-LCH Basis — Extracted Strategy Specifications

**Method.** All 9 required items read. Text extracted with `pypdf` (all PDFs are text-layer, not scans); numeric tables that were bitmaps were re-read via `PyMuPDF` high-DPI crops and, where a text duplicate existed later in the same PDF, **the text version was taken as authoritative** (my low-res image read of Citi Fig 5 had ≥6 digit errors that the Fig 54 text duplicate corrected). All arithmetic claims below were re-derived in `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/tieout.py` and `tieout2.py` (pure arithmetic, 0 network calls, <2s). Page numbers are **PDF page numbers**.

**File-system gotcha:** `Pricing and Arbitraging the CME_LCH Basis - Clarus Financial Technology.pdf` contains **two U+00A0 non-breaking spaces** (`Pricing\xa0and Arbitraging\xa0the …`). A literal-ASCII `os.path.join` misses it; glob on `*Arbitrag*` finds it.

---

## 1. `US_Rates_Vol_Lab_Sell_Eurodollar_convexity_in_Blues.pdf` — Citi Research, 08 Jan 2018 11:07:38 ET, 25pp (Bikbov / Williams)

**STRUCTURE** (p.5, verbatim):
> "Sell $100K DV01 of Blues convexity adjustment, i.e. buy 1000 of H1-Z1 packs (1000 of each of the four contracts) and pay $1bn on a matched-maturity (3/17/21-3/16/22) CME cleared swap at 6.5bp in terms of the spread (as of 10am on 1/5/2017). Consistent with the standard market practice, both fixed and floating legs of this swap have a quarterly payment frequency."
> "Buy 130 EDM9 (ED6) contracts at 97.53 and sell 176 EDZ1 (ED16) contracts at 97.495 (as of 10am on 1/5/2017)."

`1/5/2017` **[sic]** — appears twice (p.5, extract lines 212, 215) in a note dated 8 Jan 2018 whose every table footnote reads "Close of 1/5/18". Context indicates 1/5/2018.

**SIGNAL definition** (p.15 Fig 54 footnote, verbatim — the most precise statement in the whole corpus):
> "Convexity adjustments for 1y ED packs are computed as the spread between the pack's rate (the average of 4 ED rates in the pack) and matched-maturity forward 1y swap rate. The model for convexity adjustment is the Ho-Lee model calibrated to cap/floor vols. **Implied vol is calculated by matching the model to the observed convexity adjustment. Realized vol is 3m realized vol of the corresponding pack.** For each valuation metric, we mark three most attractive short convexity trades in bold."

Seven ranking metrics per pack: CvxAdj level, 1-week chg, 3m Z-score, 1Y Z-score, Vs-Model (bp), Vs-Model 3m Z, Vs-Model 1Y Z, 3m Roll (short-cvx bp), Implied Vol, Realized Vol, Implied/Realized, Cap-vol Impl/Rlzd. Selection rule = pack that "stands out on a number of these metrics" (p.4: "z-scores, implied/realized vol ratios, and dislocation to the fair value … Short Blues CAs also have the highest roll on the curve").

**RISK WEIGHTING.** Convexity leg is **DV01-notional-matched** (1000 packs = 4000 contracts × $25 = $100k DV01 vs $1bn swap). Hedge is a **published fixed DV01 ratio**, not re-estimated: p.4 verbatim —
> "the model value of Blues CA can be reasonably accurately hedged with an ED6/ED16 steepener with **0.74/-1.0 DV01 weights**."
Measured: 130/176 = **0.7386** ✓. Calibration window stated: "we calibrated these weights using the pre-2008 date sample since vol-curve relationship exhibited a structural break in the ZLB regime."

**PUBLISHED REGRESSION** (p.5 Fig 6 legend, verbatim): `-0.65+0.044*(ED16-0.74*ED6)` vs "Model value of Blues CA", y-axis in bp, sample Jan-99→2017 with Jan-08→~Jan-17 shaded "the hedge is not effective at ZLB". **Units of ED16/ED6 are NOT printed — inferred as bp** (with rates in %, the formula returns ≈−0.6bp, impossible against an 0–18bp axis).

**ENTRY / EXIT.** No printed level threshold and **no stop or target** in this note. Entry is metric-rank driven. Exit thesis (p.3, verbatim): *"A short capitulation should richen ED CAs relative to fair value as has historically been the case (Figure 4). Hence, we expect CAs to converge closer to fair value. We are less concerned about the timing of such a capitulation given that selling CAs is a positive carry trade."*

**CARRY / COSTS.** p.5: "The package carries positively by about **+$140K over the next three months (+$130K from the short CA trade and +$10K from the hedge)**." p.4: "the ED6/ED16 steepener with the DV01 weights above **carries positively by about 2bp in 3m**. From a carry standpoint, it is therefore a more efficient hedge than buying vol." No bid/offer or commission figure is given anywhere in the note.

**CLEARING-VENUE RULE** (p.4, verbatim — direct CME-LCH link):
> "Our analysis is based on the CME FRA/swap curve. **Although convexity adjustments are wider for LCH-cleared swaps, we recommend clearing on CME given that the CME-LCH basis has well retraced from its recent highs in December.** In addition, clearing on CME is more capital-efficient since it allows netting futures and swap positions for margin calculations."

**CAUSAL CLAIMS on positioning / OI / margin** (p.2, verbatim):
> "We believe this recent widening of Blues CAs has been driven by stretched short positioning in this sector of the ED curve."
> "ED futures are the instrument of choice to express views on the Fed for most accounts because of higher transparency and greater capital efficiency relative to swaps and FRAs. While the CME's and LCH's initial margin models for swaps/FRAs are based on a **5-day close-out period**, the CME uses only **1- or 2-day close-out** to determine a required margin for ED futures. As a result, futures enjoy considerably smaller initial margin requirements."
> "Dealers, who are on the other side of the shorts established by hedge funds and asset managers, have ended up with significant long ED positions (Figure 2). **Convexity adjustments have therefore widened to compensate dealers for this concentration risk.**"
> "We believe short positioning in Blues have become especially stretched due to popular steepener positions. Slopes between Greens and Blues, such as EDH0/EDH1, are within only a few basis points to the flattest levels in the last fifteen years."

Fig 4 (p.3) prints the positioning→CA regression: **y = 2E-06x - 0.1053, R² = 0.2724**, x = "Chg in dealer positioning, mm's", y = "Chg in Blues CA vs model, bp", "Monthly changes 1/1/13 to 12/26/17. Source: Citi Research, CFTC".

**FULL PACK TABLE — close of 1/5/18** (p.3 Fig 5 = p.15 Fig 54; taken from text). Columns: CvxAdj(bp) | 1wk Chg(bp) | 3m Z | 1Y Z | VsModel(bp) | 3m Z | 1Y Z | 3m Roll (short cvx,bp) | ImplVol | RlzdVol | Impl/Rlzd | Capvol I/R

| Pack | CA | Δ1w | 3mZ | 1YZ | vsMdl | 3mZ | 1YZ | Roll | IV | RV | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|H8-Z8|0.17|0.00|0.46|-0.54|0.14|0.44|-0.61|0.08|92.0|34.4|**2.7**|1.0|
|M8-H9|0.35|-0.03|0.68|-0.62|0.28|0.71|-0.70|0.17|95.2|35.3|**2.7**|1.0|
|U8-M9|0.58|-0.08|0.75|-0.70|0.46|0.77|-0.77|0.23|96.5|37.1|**2.6**|1.1|
|Z8-U9|0.86|-0.12|0.74|-0.78|0.65|0.71|-0.85|0.28|96.5|39.1|2.5|1.1|
|H9-Z9|1.18|-0.15|0.77|-0.87|0.86|0.67|-0.93|0.32|95.9|41.4|2.3|1.1|
|M9-H0|1.58|-0.18|1.07|-0.87|1.10|1.00|-0.90|0.40|96.1|43.0|2.2|1.2|
|U9-M0|2.03|-0.21|1.36|-0.84|1.35|1.36|-0.83|0.45|96.2|44.2|2.2|1.2|
|Z9-U0|2.54|-0.23|1.61|-0.76|1.62|1.64|-0.71|0.52|96.3|45.2|2.1|1.2|
|H0-Z0|3.15|-0.24|1.81|-0.66|1.92|1.82|-0.53|0.60|96.9|46.2|2.1|1.3|
|M0-H1|3.86|-0.19|1.88|-0.56|2.28|2.13|-0.29|0.71|98.0|47.3|2.1|1.3|
|U0-M1|4.75|-0.12|2.27|-0.36|2.77|**2.35**|0.20|0.88|99.9|48.5|2.1|1.3|
|Z0-U1|5.81|-0.06|**2.51**|-0.07|3.41|**2.30**|0.81|**1.07**|102.3|49.6|2.1|1.3|
|**H1-Z1**|7.13|-0.10|**2.44**|**0.28**|4.26|**2.21**|**1.37**|**1.32**|105.4|50.4|2.1|1.3|
|M1-H2|8.24|-0.23|**2.30**|**0.41**|**4.87**|2.03|**1.54**|**1.11**|106.0|51.0|2.1|1.3|
|U1-M2|9.09|-0.36|2.18|**0.36**|**5.18**|1.95|**1.52**|0.85|104.5|51.7|2.0|1.3|
|Z1-U2|9.60|-0.42|2.04|0.16|**5.11**|1.86|1.36|0.51|101.1|52.5|1.9|1.3|
|H2-Z2|9.78|-0.30|1.75|-0.20|4.69|1.73|1.02|0.18|96.4|53.4|1.8|1.3|

Bold = Citi's own "three most attractive short convexity trades" per metric. **H1-Z1 is the recommended pack; it is top-3 on 5 of the 7 metrics.** Note the traded entry was **6.5bp** vs the 1/5/18 table's 7.13bp for the same pack (different timestamp: 10am 1/5 vs close 1/5).

---

## 2. `US_Rates_Vol_Lab_Value_in_Greens_convexity.pdf` — Citi Research, 15 May 2017 11:34:00 ET, 24pp

**STRUCTURE** (p.4, verbatim):
> "Sell $100k DV01 of Greens convexity adjustment, i.e. buy 1000 of M9-H0 packs (1000 of each of the four contracts) and pay $1bn on a matched-maturity CME swap (M19-M20 IMM quarterly money swap) at about **4.5bp** in terms of the ED/swap spread (pricing as of 9:30am 5/15/2017). Consistent with the standard market practice, both fixed and floating legs of this swap have a quarterly payment frequency."
> "Sell 167 contracts of EDM9 (at 98.065 as of 9:30am 5/15/2017) and buy 141 contracts of EDM8 (at 98.41 as of 9:30am 5/15/2017)."

**RISK WEIGHTING** (p.3, verbatim): *"we suggest hedging short Greens convexity with a weighted EDM8/EDM9 steepener. The fair value of Greens convexity (based on our implementation of the standard Ho-Lee model calibrated to cap/floor volatility) is highly correlated with the ED5/ED9 curve with **-1/1.18 DV01 weights** (Figure 5)."* Measured: 167/141 = **1.1844** ✓.

**PUBLISHED REGRESSION** (p.3 Fig 5 legend): `-3.53*ED5+4.17*ED9`, plotted against "Model" and "Greens Convexity adjustment", y-axis bp, sample Jan-00→~2017. Footnote states units explicitly: *"Note: ED5 and ED9 are expressed as rates in % terms."* Coefficient ratio 3.53/4.17 = 0.8465 = 1/1.181 ✓ consistent with the −1/1.18 DV01 weights.

**HEDGE CARRY** (p.3, verbatim): *"Note that the hedge is slightly short the market since front-end vols are generally directional with rates over a long history due to the zero-bound effect. Despite being short the market, this weighted steepener has **about flat carry**."*
**PACKAGE ROLL** (p.4): *"The trade rolls positively by about **0.88bp over the first three months**."*

**ENTRY/EXIT.** No target, no stop, no level threshold printed. Entry rationale = *"the dislocation to the model is near historical highs (Figure 3)"* — Fig 53 (p.14) shows M9-H0 vs-model **3.43bp** at a **1Y Z-score of 1.48**, tied for the highest dislocation Z on the strip.

**COSTS.** None quoted.

**Predecessor-trade hedge formula (Blues, still open)** — p.2 Fig 2 legend, verbatim:
`scaled 2s5s10s fly: 9.7 +20.6*(-0.705*2y+5y-0.465*10y)` plotted vs "Blues Cvx Adj", bp, Jan-10→2017. Units of the swap rates not printed — inferred %. The Blues trade referenced (p.2): *"we sold Blues convexity hedged with a 2s5s10s rates fly (as a proxy for long vol) in Sell Blues convexity adjustments, hedged."*

**CAUSAL CLAIMS on positioning / OI** (verbatim):
- p.2: *"the main reason for the relative cheapening of futures relative to swaps has been massive short positioning, likely as a way to express a hawkish view on the Fed."*
- p.2: *"We believe this is because short covering has been largely limited to Blues and longer maturities, while positioning in shorter maturities has been little changed. **Indeed, open interest in Reds and Greens has continued an upward trend observed since last year (Figure 4).**"* — Fig 4 is titled "No signs of short covering in Reds and Greens", plotting **open interest in ED futures, 000s, Reds/Greens/Blues, May-14→2017** (Reds ~3,000→4,000; Greens ~2,000→2,400; Blues ~1,000). This is the corpus's only explicit *OI-level → convexity-adjustment* claim.
- p.2: *"we believe some shorts in Eurodollars are established against OIS given the tightening in FRA/OIS seen earlier this year."*

**FULL PACK TABLE — close of 5/12/17** (p.14 Fig 53, from text; same 12 columns as above):

| Pack | CA | Δ1w | 3mZ | 1YZ | vsMdl | 3mZ | 1YZ | Roll | IV | RV | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
|M7-H8|0.23|-0.01|-0.77|0.00|0.20|-0.73|0.18|0.12|120.6|48.2|2.5|0.7|
|U7-M8|0.48|-0.03|-0.84|0.05|0.42|-0.76|0.29|0.25|124.6|53.2|2.3|0.7|
|Z7-U8|0.84|-0.04|-0.94|0.14|0.72|-0.80|0.48|0.36|126.9|57.7|2.2|0.7|
|H8-Z8|1.32|-0.06|-0.99|0.35|1.12|-0.74|0.81|0.48|128.7|62.0|2.1|0.7|
|M8-H9|1.92|-0.06|-0.95|0.59|1.59|-0.51|1.12|0.60|130.1|64.9|2.0|0.8|
|U8-M9|2.60|-0.03|-0.87|0.77|2.09|-0.02|1.36|0.68|130.2|67.6|1.9|0.8|
|Z8-U9|3.33|-0.03|-0.92|0.79|2.57|0.39|1.46|0.72|129.0|70.0|1.8|0.8|
|H9-Z9|4.09|-0.06|-1.01|0.73|3.02|0.64|1.48|0.77|127.4|72.2|1.8|0.9|
|**M9-H0**|4.91|-0.10|-1.14|0.65|3.43|0.82|**1.48**|0.81|125.6|73.7|1.7|0.9|
|U9-M0|5.53|-0.14|-1.40|0.46|3.57|0.54|1.43|0.62|121.3|74.8|1.6|0.9|
|Z9-U0|5.95|-0.16|-1.78|0.14|3.46|-0.04|1.07|0.43|115.4|75.3|1.5|1.0|
|H0-Z0|6.62|-0.17|-1.92|0.09|3.53|-0.37|0.93|0.66|112.3|75.5|1.5|1.0|
|M0-H1|7.01|-0.23|-1.87|-0.18|3.30|-1.16|0.49|0.40|107.4|75.3|1.4|1.0|
|U0-M1|7.65|-0.35|-1.84|-0.33|3.27|-1.31|0.30|0.64|104.7|75.1|1.4|1.0|
|Z0-U1|8.64|-0.44|-1.94|-0.33|3.53|-1.42|0.35|0.99|104.3|74.8|1.4|1.0|
|H1-Z1|9.55|-0.54|-2.09|-0.37|3.67|-1.59|0.36|0.91|103.3|74.2|1.4|1.1|
|M1-H2|10.55|-0.62|-2.35|-0.27|3.86|-1.74|0.50|1.00|102.5|73.9|1.4|1.1|

Note the level/Z-score **sign asymmetry vs the 2018 table**: in May-2017 every CvxAdj 3m Z-score is negative (CAs tightening) while the vs-model 1Y Z-scores are positive — i.e. the trade is entered on *dislocation-to-model* Z, not on *level* Z.

---

## 3. `North_America_Rates_Trade_Idea_Turning_Green_from_Blue_on_short_convexity.pdf` — Citi Research, 06 Jun 2017 14:30:16 ET, 7pp

**EXIT of the Blues trade** (p.2, verbatim):
> "We sold hedged Blues convexity adjustment (CA) on **2/9/17** by buying **2000 H0-Z0 Blues packs**, paying **$2bn** on a matched-maturity swap CME-cleared swap at **8.8bp** the spread and paying the belly of the 2s5s10s swap fly with **$147mm/-$85.6mm/$20.89mm weights at -18.2bp** … While we have not reached our target of **+$600K P&L** yet, we now see better opportunities in selling hedged Greens CA … and prefer to close this trade at this time. **We close H0-Z0 CA at 6.6bp and close the 2s5s10s fly at -16.5bp** (pricing as of 1:30pm on 6/6/17). **Our net P&L, net transaction costs, is +$500K.**"

This is the only place in the corpus with a **printed P&L target** (+$600K), a **cash fly hedge weighting** ($147mm / −$85.6mm / $20.89mm ⇒ 2s:5s:10s notional, belly paid), and a **"net transaction costs"** P&L. Gross on the CA leg alone: (8.8−6.6)bp × $200k DV01 = **$440,000** (verified); the reported +$500K is the whole package net of costs, so the fly leg contributed ≈+$60K gross-of-costs — the cost drag is not separately disclosed.

**ENTRY of the Greens trade** (p.2, verbatim):
> "we sell **$300k DV01** of Greens convexity adjustment, i.e. buy **3000 of M9-H0 packs** (3000 of each of the four contracts) and pay **$3bn** on a matched-maturity CME swap (M19-M20 IMM quarterly money swap) at **4.3bp** in terms of the ED/swap spread … We also **sell 500 contracts of EDM9 98.215 and buy 424 contracts of EDM8 98.46**. Pricing is as of 1:30pm on 6/6/17. The trade rolls by positively by about **0.7bp over the first three months**. **Our target is a profit of $450K, and our stop is the loss of $225K.**"
> "The hedge can be thought of as the EDM8/EDM9 steepener with **1/-1.18 DV01 weights**."

**This is the only printed target-and-stop pair in the corpus: +$450K target / −$225K stop on $300k DV01 = +1.50bp / −0.75bp, a 2:1 reward:risk.** Measured: 500/424 = 1.1792 ✓.

**Chart legends re-printed as text** (p.2) — note the **re-fitted Blues fly formula**, different from the 15-May version:
- Fig 1: `scaled 2s5s10s fly: 10.2+21.4*(-0.70*2y+5y-0.46*10y)` (Jun-2017 vintage) vs `9.7+20.6*(-0.705*2y+5y-0.465*10y)` (May-2017 vintage). **A documented re-fit within 3 weeks** — the coefficients are not stable constants.
- Fig 2: `-3.53*ED5+4.17*ED9` — **unchanged** from the May note.

**RISK claim** (p.2, verbatim): *"The ED hedge therefore should protect our short Greens CA trade from a scenario of a surge in volatilities, which can be a risk to the trade given historically low levels of volatilities."* … *"the main reason for the dislocation of Greens convexity from fair valuations is extremely short positions in ED futures. A further build-up of ED shorts is the main risk to the trade."*

---

## 4. `Alert_North_America_Rates_Trade_Idea_Take_off_the_hedge_on_short_Greens_convexity_trade.pdf` — Citi Research, 13 Jul 2017 09:18:59 ET, 6pp

**Full text of the alert (p.1, verbatim):**
> "Last month we entered into a short Greens convexity trade, i.e. we bought 3000 M9-H0 ED packs against paying $3bn on a matched-maturity CME cleared swap … We also initiated EDM8/EDM9 steepener (1/-1.18 dv01-weighted) designed to hedge the model fair value of Greens convexity (which is directional with implied volatilities). Since initiation, **Greens convexity adjustments have tightened with the mid-level currently at 3.35bp for the M9-H0 pack (as of 8:30am on 7/13/17, trade initiated at 4.3bp on 6/6/17, implying mark-to-market gain on the convexity leg of the trade of $285K at the current mid).**
> With our hedge having outperformed the model fair value, given the recent curve steepening, **we take it off at a dollar P&L of +$70.5k. Specifically, we sell 500 contracts of EDM8 at 98.385 and buy 424 contracts of EDM9 at 98.095** (as of 8:30am 7/13/17). We maintain short Greens convexity outright and are comfortable being outright short Greens vol, in the near term, given implieds will likely not find support as we expect rates to grind lower over the summer. A further build-up of ED shorts is the main risk to the trade."

**Two measured tie-outs:**
1. **CA leg:** (4.3 − 3.35) bp × $300,000/bp = **$285,000** — exact match to the printed $285K. Confirms the DV01 convention unambiguously.
2. **Hedge leg — the printed leg quantities are transposed [sic].** With the *initiation* quantities (long 424 EDM8, short 500 EDM9): EDM8 (98.46→98.385) = −$79,500; EDM9 (98.215→98.095) = +$150,000; **total = +$70,500 = the printed +$70.5k exactly.** With the alert's literal quantities (long 500 EDM8, short 424 EDM9) the total is **+$33,450 ≠ printed**. Verified in `tieout2.py`. **The P&L number is right; the leg quantities in the closing sentence are swapped.** Any tie-out harness must use the initiation quantities.

**Exit rule stated:** the hedge is removed *when it "outperform[s] the model fair value"* — a discretionary, unquantified de-hedging trigger. The convexity leg is left open with no revised target/stop.

---

## 5. `A better way to sell vol_ CME-based convexity adjustments are rich. Wed May 03 2017.pdf` — **J.P. Morgan** (not Citi), Younger / Sarkar / Salem, completed 03 May 2017 11:10 AM EDT, 5pp. Markdown at `C:/Users/chris/Downloads/convexityrv_markdown/A better way to sell vol_ CME-based convexity adjustments are rich. Wed May 03 2017.pdf.md`

**MODEL (p.2, Exhibit 1 footnote, verbatim — the only closed-form CA formula printed in the corpus):**
> "Financing bias estimated using a Ho-Lee model, this reduces to **A_cvx = σ² T₁ T₂ / 2**, with ATM Eurodollar vols where available (out to the early Greens or so) and OTC Libor cap vols otherwise."

σ is a normal/absolute rate vol; T₁ = time to the contract's fixing, T₂ = T₁ + accrual.

**STRUCTURE / RECOMMENDATION** (p.3, verbatim):
> "we recommend **buying H9 and M9 Eurodollars versus CME-facing OTC FRAs** to position for a **wider front-end CME/LCH basis** and to monetize rich convexity adjustments."
> "convexity adjustments are rich and the CME/LCH basis is too narrow; **selling CME-based convexity adjustments monetizes both effects**."

**SIGNAL definition** — a two-stage residual, then converted to a funding spread:
1. Observed CA − theoretical financing bias (Ho-Lee above) = excess.
2. Excess converted to an **implied collateral funding spread vs 3M Libor**, using: *"static margin on both, based on estimates provided by each clearinghouse for a pvbp-neutral package (approximately **1.3% total margin**). Converted to a spread versus Libor assuming **Fed funds interest on IM** and 3-month basis swap spreads."* (p.2, Exhibit 2 footnote.)
3. Trade when the implied funding spread exceeds the firm's actual funding cost. p.3: *"To the extent that actual collateral funding rates are lower than those implied, investors can monetize this mispricing."*

**RISK WEIGHTING.** "pvbp-weighted (at trade initiation) amount of OTC FRAs" — **static DV01-neutral, set at inception, not re-hedged** (p.3, Exhibit 3 footnote).

**HORIZON as the selection criterion** (p.3, verbatim — this is the note's core RV argument):
> "In principle the dollar mispricing is somewhat larger in CME/LCH basis in longer tenors (e.g., 10- and 3-year). However, the key distinction here is that **the time to contract expiry is a couple of years compared with much longer maturities. This makes it much easier to monetize the actual/implied funding spread over a reasonable horizon.**"

**PUBLISHED NUMBERS (printed in body text):**
- *"while these estimates were consistent with typical funding spreads among swaps dealers, more recently they have more than tripled, **from L+50-100 bp last year to nearly L+300 bp recently**."* (p.2)
- *"Generally speaking, the latter [CME netting] results in roughly **70-80% margin savings** versus the former."* (p.3)
- *"empirically the CME/LCH basis at the front end has remained exceptionally tight since it first emerged in mid-2016, **remaining well under 1 bp for the entirety of that period and spending most of its time around 0.25 bp**."* (p.3)
- *"CME-based convexity adjustments (again, net of theoretical financing bias) across much of the Eurodollar complex trade continue to trade at **roughly 80% of those facing LCH**."* (p.3)
- Exhibit 3 grid runs Z7…Z9; *"Note: CME does not provide margin estimates beyond Z9 OTC FRAs at present."*

**Chart reads (approximate, NOT printed):** Exhibit 4 "CME/LCH spreads by tenor since May 2016, max/min as well as average and current (as of **5/1/17**) levels; bp running": 5Y max ≈2.7, current ≈avg ≈1.25; 10Y max ≈4.1, current ≈2.7, avg ≈2.35; 30Y max ≈5.4, current ≈3.85, avg ≈3.3. Exhibit 5 implied funding spread by contract: LCH ≈50→300bp Z7→Z9; CME rises to a peak ≈1000bp at **M9**, with a "Typical funding spread" reference line ≈50bp. **Label these as chart reads.**

**CAUSAL CHAIN (verbatim, p.2):**
> "**We find that much of this dislocation can be attributed to the fact that both Eurodollars (cleared through CME) and cleared OTC FRAs and swaps require significant margin on both legs of the trade. Similarly to the CME/LCH basis at the long end, in the presence of an imbalance of flows on dealer books this can lead to pricing discrepancy between otherwise economically very similar positions.**"
> "Looking across the Eurodollar strip, we find that the **beta and correlation of richness in convexity adjustments with dealer positioning is consistently positive, and also has a significant term structure that peaks roughly 2 to 3 years forward** (Exhibit 1). This is broadly consistent with our previous assertion that **dealers have accumulated a net long in Eurodollars versus OTC swaps (almost exclusively cleared through LCH) owing to issuance-related receiving—primarily by SSAs and GSEs.**"
> "one can conceptualize the richness of convexity adjustments as pricing in additional slide as compensation for the costs incurred when posting IM against otherwise risk-less positions. **This dynamic is exacerbated when offsetting exposures face different CCPs, and therefore cannot be netted for margin purposes.**"
> "**if the IM associated with a long in Eurodollars hedged with a pvbp-weighted amount of cleared OTC FRAs were suddenly halved, all else equal the convexity adjustment net of vol-driven financing bias should decline by a proportional amount.**" (p.3 — the falsifiable linear-in-IM prediction)

**Footnote 1 (p.2)** — important for any historical backtest: *"whereas in the previous regime VM was only required for Eurodollars, now it is also required for OTC FRAs, which are subject to the Dodd Frank clearing mandate. However, the introduction of price alignment interest (PAI), in which the receiver of margin will pay interest (usually Fed funds) to the poster, aligns the economics of cleared and bilateral FRAs. As a consequence, **classical financing bias estimates are still appropriate when pricing the convexity adjustment**."*

**NOTE — Citi and JPM disagree on the direction of the CME-LCH leg.** Citi (Jan 2018) says clear the swap at **CME** because the basis had retraced. JPM (May 2017) says the front-end basis is **too narrow** and recommends CME-facing FRAs to be long the basis widening. Same instrument, opposite basis view, 8 months apart.

---

## 6. `CME-LCH Basis_ Convexity in Eurodollar Futures _.pdf` (and `… - Clarus Financial Technology.pdf`) — Clarus, Chris Barnes, July 1, 2015

**The two files are the SAME article** (verified by whitespace-normalised diff; 17pp vs 24pp print pagination only). Markdown at `C:/Users/chris/Downloads/convexityrv_markdown/CME-LCH Basis_ Convexity in Eurodollar Futures _.pdf.md`.

**STRUCTURE.** Short 1000 ED futures vs short a pvbp-equivalent cleared 3M FRA (an ED/FRA convexity package). No pack/fly.

**RISK WEIGHTING.** Notional-scaled for discounting, following Aikin: **short 1000 ED vs short $1005m 3M FRA** (see §9).

**COST / FUNDING ASSUMPTIONS (p.5, verbatim):**
> "1. The Variation Margin. This has to be funded overnight. Let's say the funding spread is **25bp** – i.e. I receive OIS minus 12.5bp on ITM positions; and pay OIS plus 12.5bp on OTM positions.
> 2. The Initial Margin. This is a trickier cost of funds to pin down as it should be term funded for the life of the trade. Let's just take the **1 year IRS rate as a guide – currently 0.50%**."

**PUBLISHED MARGIN NUMBERS (pp.4-5, verbatim):**
- *"IM increases from **$1.37m to $1.4m** as rates go lower. It declines to **below $1.355m** at higher rates."* (LCH IM on the FRA leg, scenario-shifted) … *"the relationship is not linear … **IM itself is slightly convex**."*
- *"the SPAN margin requirement of a CME Eurodollar, which checks out at **$425,000 for 1,000 contracts of EDM6**."*

**THE OPERATIVE CONSTRAINT (p.6, verbatim — the hardest rule in the corpus for a convexity backtest):**
> "The 'traditional' convexity style pay-off **is only apparent when CME Portfolio Margining is applied**. The humps that appear on the two lower lines are due to the cost of funding two lots of Variation Margin! Due to the term cost of funds (IM) versus variable cost of funds (VM), **the pay-offs are also dependant upon outright level of rates**."
> "**It is only possible to trade convexity between CME Eurodollars and FRAs if you clear the FRA at CME and have CME Portfolio Margining in place.**"

**LIQUIDITY CROSSOVER (p.2, from ADV/DV01 3-day averages 24-26 June 2015):** *"swaps up to and including the **3y** maturity would be best priced-off a Eurodollar-derived curve than a 'pure' IRS curve."*

**OI / flow evidence (pp.7-8, verbatim):** *"CME had their biggest ever week in USD FRAs last week – and this was no IMM roll … **EDM6 in nearly $40bn traded on one day, and at a variety of strikes** … Could this be a convexity play? On the same day, **there was also a healthy jump in Open Interest for the Jun 16 Eurodollar contract.**"* — SDR-detectable signature: IMM-dated FRAs printed **outside a Reset/tpMatch run** + coincident ED OI jump.

**Open questions the article poses (p.7, unanswered):** *"What does this mean for short-dated CME-LCH basis spreads? Does this explain the **4 year bump** we noticed in the term-structure of the basis curve?"*

---

## 7. The Clarus CME-LCH set

### 7a. `CME-LCH Basis For Dummies - Clarus Financial Technology.pdf` — Tod Skarecky, June 28, 2017, 23pp

**MECHANISM (Steps 1-5, pp.2-10).** Dealer is fixed-rate **payer at LCH**, fixed-rate **receiver at CME**. Client asks to pay fixed → dealer receives at CME and offloads by paying at LCH → IM rises at **both** CCPs → MVA on the incremental IM profile → quoted basis.

**Pro-Tip (p.2, verbatim):** *"The theory goes that the reason Banks are fixed rate receivers at CME is that **most buy-side institutions caught by the clearing mandate are payers** (and hence the dealer is a receiver)."*

**PUBLISHED NUMBERS:**
- Hypothetical books (p.3): *"we have to give CME **$1.2bn**, and LCH nearly **$5bn** of margin collateral."* (CHARM screens on pp.7-8 print base IM: CME 1,237,414,920 / LCH 4,964,143,911.)
- Trade: **$100m 30Yr swaps at CME & LCH**, DV01 **$225,000** (p.9).
- Funding: *"the dealer assigns a funding spread, say **20 basis points above Fed Funds**"* (p.9).
- CME IM profile (p.7): Base Account 1,237,414,920 / New 7,467,293 / **Change 10,496,311** / Margin 1,247,911,231; decaying to 0 at 30Y. *"we have to pony up **$10m more in collateral today**"* (p.8).
- LCH IM profile (p.8): Base Account 4,964,143,911 / New 11,409,440 / **Change 21,109,203** / Margin 4,985,253,114.
- **MVA in USD (p.9): CME/CME/House incremental $282,867; LCH/LCH/House incremental $443,678; Total $726,545.**
- **MVA in bp (p.10): CME +1.30, LCH +2.10 → "And there you have it, 3.4 basis points."**
- **Tradition quote screen, 26-Jun-2017 11am (EDT)** (p.6) — full term structure of CME-LCH mid, bp:

| 1Y | 2Y | 3Y | 4Y | 5Y | 6Y | 7Y | 8Y | 9Y | 10Y | 11Y | 12Y | 15Y | 20Y | 25Y | 30Y | 35Y | 40Y | 50Y |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|0.10|0.25|0.45|0.70|1.05|1.35|1.55|1.95|2.20|2.45|2.55|2.70|2.85|3.05|3.25|**3.40**|3.45|3.50|3.55|

**MEASURED DISCREPANCY (report as an annotated tie-out, not a match):** $726,545 / $225,000 = **3.229 bp**, not the printed 3.40. Per leg: 282,867/225,000 = **1.257** vs printed 1.30; 443,678/225,000 = **1.972** vs printed 2.10. The implied DV01s are inconsistent with each other ($217,590 CME vs $211,275 LCH), so the printed bp column is **not** a simple MVA/DV01 division — Clarus's bp conversion uses something other than the stated $225,000 DV01. Do not build a tie-out that asserts MVA/DV01 = printed bp.

**Caveat the author himself flags (p.10, verbatim):** *"every bank is different and will have wildly different portfolios, and hence wildly different actual costs at CME and LCH. Hence many banks have an 'axe' … But don't forget that **the basis market is a market unto itself, complete with speculation and panic, so it can move regardless of these costs amongst firms.**"*

### 7b. `CME-LCH Basis Spread - Clarus Financial Technology.pdf` — Amir Khwaja, May 20, 2015, 29pp

**GOLD: full published term structure.** p.3, ICAP indicative quotes, Reuters page **19981**, header `05/18 15:21 GMT [ REUTERS CAPITAL MARKETS SOURCE:ICAP ]`, `USD INDICATIVE IRS SEMI BOND LCH / CME BASIS`:

| SB Term | LCH MID | CME (bps) | CME MID |
|---|---|---|---|
|1Y|0.45802|+0.1500|0.45952|
|2Y|0.82319|+0.3500|0.82669|
|3Y|1.16156|+0.6000|1.16756|
|4Y|1.43481|+0.8500|1.44331|
|5Y|1.65642|+1.2000|1.66842|
|6Y|1.83702|+1.2700|1.84972|
|7Y|1.98360|+1.3500|1.99710|
|8Y|2.10103|+1.4300|2.11533|
|9Y|2.19705|+1.5200|2.21225|
|10Y|2.27699|+1.6000|2.29299|
|12Y|2.40414|+1.6500|2.42064|
|15Y|2.53143|+1.7000|2.54843|
|20Y|2.65554|+1.7500|2.67304|
|25Y|2.71531|+1.8200|2.73351|
|30Y|2.74709|+1.9000|2.76609|

Footnote on screen: *"CME Mids reflect the most recent prices from ICAP's voice desk or implied mids from i-Swap"*.

Derived bid/offer table (p.4, assumes **0.25 bps bid-offer, both CCPs, all tenors**): 2Y 0.82194/0.82444 (LCH) 0.82544/0.82794 (CME); 5Y 1.65517/1.65767, 1.66717/1.66967; 10Y 2.27574/2.27824, 2.29174/2.29424; 30Y 2.74584/2.74834, 2.76484/2.76734. **All eight verified as MID ∓ 0.00125.**

**PUBLISHED NUMBERS / CLAIMS (verbatim):**
- *"This basis has been small enough (**0.15bps**) to be inconsequential to most of the market."* (p.2)
- *"**Pay Fix is now up to 2bps lower at LCH** (tenor dependent); **Receive Fix is now up to 2bps higher at CME** (tenor dependent)."* (p.1)
- *"much larger than the typical bid-offer spread of **0.25 bps**."* (p.2)
- *"the standard size on a USD 30Y IRS is **$25 million** and for this the difference in value is **$95,000**."* (p.4) → **implied 30Y DV01 = $50,000/bp per $25m = $2,000/bp per $1m.**
- CCP switch cost (p.6): *"pay fixed on a CME Swap at 2.76734 and receive fixed on an LCH Swap at 2.74584. In effect losing the basis plus the bid-offer (unless transacted at mid), so **2.15 bps over the life of the deal. Or put another away around $100,000 on our $25m of 30Y and $1 million on a $250m 30Y!**"* — measured 2.15 × $50,000 = $107,500 and $1,075,000 (Clarus rounds).
- *"the Risk article puts at up to as much as a **$20 million loss at each dealer**(?)"* (p.5)
- *"which for our 30Y $25m trade would be zero margin or **$5.5 million of margin** … The cost to fund this margin and the capital cost are significant. **Somewhere between 0.50 bps and 1.5bps.** Which is the reason for the CME-LCH Basis."* (p.8) — **the article's own fundamental band.**
- *"(A recent **JP Morgan** US Fixed Income Strategy Note on **May 1 2015**, attempted to put an upper bound on the size of the CME-LCH Basis by looking at the financial benefits to clients from cross margin of Futures vs Swaps and came up with a **1.5 bps maximum**.)"* (p.9)
- Volumes: *"More than **$20 billion** of these trades have traded since 30 April"* (12 business days, 30 Apr–15 May 2015); Tradition >$10bn (*"30 April with $7b, 13 May with $1.8b and 15 May with 1.9b"*); ICAP almost $10bn (*"5 May with $2.7b and 8 May with $2.3b"*); Tullett $1.9bn on 12 May; GFI $150m 7Y on 13-May. Counting convention explicitly stated on p.13: single vs double vs quadruple counting.

**CAUSAL CLAIM (p.7-8, verbatim, the canonical "flow imbalance" chain):**
> "CME cleared volume is mostly driven by clients that are fixed income asset managers … they generally pay fixed on swaps … So on the client-dealer swap trade, the dealer is receiving fixed … he needs to pay fixed on a swap and find another dealer willing to receive fix … **However as all/most dealers are in the same direction at CME, it is not easy to find the hedge trade. Consequently the dealer does the hedge with another dealer at LCH. Which means that there is interest rate risk and margin required at both CME and LCH. Or put another way the difference between zero and two times gross margin.**"

**Negative finding on the margin-model explanation (p.7, verbatim):** *"This does show that CME Pay Fix requires much less margin than LCH Pay Fix … However that would make the cost of holding a 30Y Pay Fixed Swap higher at LCH, even if only by **0.1 bps or so**, which does not serve to explain why the CME Pay Fix rate should be higher. So we must look else where for our explanation."*

**Regime break to note for any historical series (p.3):** *"CME put out an Advisory Note on **13-May** for CME OTC IRS USD Valuation Curves … This states that **within 30-days CME specific swap observations will be incorporated into end-of-day curves.**"* Before ~mid-June 2015, CME EOD marks did **not** reflect CME-specific pricing — a CME-LCH basis series spanning this date has a discontinuity in what "CME curve" means.

### 7c. `CME-LCH Basis - What does the Term Structure tell us_ - Clarus Financial Technology.pdf` — Chris Barnes, May 26, 2015, 24pp

**GOLD: two-date term structure with changes** (p.6, "CME-LCH Basis", bp):

| Tenor | 18May15 | 26May15 | Change (bp) |
|---|---|---|---|
|2y|0.35|0.65|+0.30|
|3y|0.60|1.10|+0.50|
|4y|0.85|1.60|**+0.75**|
|5y|1.20|1.85|+0.65|
|6y|1.27|1.90|+0.63|
|7y|1.35|2.05|+0.70|
|8y|1.43|2.05|+0.62|
|9y|1.52|2.15|+0.63|
|10y|1.60|2.30|+0.70|
|12y|1.65|2.30|+0.65|
|15y|1.70|2.30|+0.60|
|20y|1.75|2.30|+0.55|
|25y|1.82|2.40|+0.58|
|30y|1.90|2.50|+0.60|

(The 18May15 column reconciles exactly with the ICAP 19981 screen in 7b.)

**Tradition TRADTCCP screen, 26MAY15 10:02, "CME LCH Spread Mids"** (p.5) — **the only multi-currency basis print in the corpus:**

| Tenor | USD | EUR | GBP |
|---|---|---|---|
|2Yr|0.650|0.150|0.100|
|3Yr|1.100| | |
|4Yr|1.600| | |
|5Yr|1.850|0.250|0.100|
|6Yr|1.900| | |
|7Yr|2.050| | |
|8Yr|2.050| | |
|9Yr|2.150| | |
|10Yr|2.300|0.350|0.150|
|11Yr|2.300| | |
|12Yr|2.300| | |
|15Yr|2.300| | |
|20Yr|2.300| | |
|25Yr|2.400| | |
|30Yr|2.500|0.350|0.200|

Footer: *"Indicative Levels Only Please Refer"*.

**FORWARD-SPACE SIGNAL (pp.7-9, verbatim):**
> "**5y5y forward is at +2.9bp versus a spot level of 'only' +1.85bp.**"
> "It looks like long-term payers of fixed rates at CME are causing the basis to be widest in the longest tenors of the curve. This results in an upward sloping curve."
> "**Most obviously, the first 'hump' on the curve is 4 years.** This corresponds with the point on the curve that has seen the largest increase in price ('widening of the basis') in the past week (of **+0.75bp**). Maybe this is telling us that **a lot of positions have an average maturity of 4 years**, which is hence creating a concerted paying interest in this maturity."
> "Conversely, the **'belly' of the curve is cheap compared to the wings, suggesting a relative lack of paying interest around 10 years.** This may also help explain why volumes have been highest at this point in the curve."

**CARRY — the explicit rejection (p.9, verbatim):**
> "Unfortunately, unlike Libor-OIS strategies back in 2008/9, **there do not appear to be hugely compelling carry trades out there. The maximum roll-down for the 1 year forwards is just 1.1bp per year. That is unlikely to be enough to attract hedge funds into the market to provide speculative liquidity just yet.**"
> "**Overall, it is telling that market participants do not expect this basis to be trading at zero in five years time – for any maturity.** If I were a bond issuer I'd be telling my swap bank to price off the CME curve right now!"

**Volume-by-tenor facts (p.4):** *"**21% and 15% of total USD Swap volumes on TradX in 7yr and 10yr maturities were CME-LCH basis related.**"* Data window 30 Apr–15 May 2015, ICAP/TradX/Tullett only. Curve-build caveat: *"I would suggest taking only price information for benchmark maturities. We can therefore remove points such as **6yrs, 12yrs and 25yrs**."*

**Modelling questions raised (p.10, verbatim, both directly relevant to this codebase):**
> "There is an intrinsic cost of carrying IM at two or more CCPs. **This cost will probably increase as rates increase** (in the same way that margin income increases for CCPs at higher rates). Is this why we have an upward sloping CCP basis curve (and therefore **are we ready to model the correlation effect of outright rates on CCP basis?!**)."
> "do we believe that long-only bond funds are naturally payers of negative swap spreads? By extension, does that also mean that **our CCP-Basis curve has some kind of convexity versus swap spreads at a zero strike?** Try modelling that…."

### 7d. `Hedging the CME-LCH Basis - Clarus Financial Technology.pdf` — Amir Khwaja, May 26, 2015, 26pp

**STRUCTURE.** A dealer book net receiver at CME / net payer at LCH across 11 tenors (CME) vs 7 tenors (LCH). Hedge = **CCP Switch trade: simultaneously pay fixed at CME and receive fixed at LCH, transacted at mid, no bid-offer.**

**PUBLISHED NUMBERS (verbatim, pp.4-11):**
- *"At CME we are net receivers at 2Y on **$2.6 billion**; At LCH we are net payers at 2Y on **$2.6 billion**."*
- *"For our CME account, IM is **$218 million**; For our LCH account, IM is **$262 million**. An overall gross requirement of **$480 million** … Contrast this with the situation if all these trades were in one account at CME or LCH; probably no more than **$5 to $10 million**."*
- *"for a +1bps rise: Our CME account would lose **$5.8 million**; Our LCH account would gain **$5.8 million**. Overall we would only lose **$20,000 per point**."*
- **The basis-risk P&L attribution (verbatim):** *"The widening of the spread from **0.15 bps** to up to **1.9 bps** depending on tenor, would have caused the CME account to change in value while the hedge did not. **So as our CME 5Y 01 is -$1m and we know the 5Y CME-LCH Basis moved out to +1.2 bps, we would have lost $1m on this move. Repeating this for each tenor in our example portfolio would give us a $7.5 million portfolio loss.**"*
- Switch trade: **$1 billion 5Y**. *"LCH Side of the Switch trade has an 01 at 5Y of **-$450k**. Which reduces the LCH Account 01 at 5Y to **$695k** … instead of CME 5Y of -$1m offset at LCH by $1.1m, We have **CME -$560k offset at LCH by $695k** … we have **almost halved** it."*
- Cost: *"we are **Receiving Fixed at 1.65642 and Paying Fixed at 1.66842**. So **losing 1.2 bps on the trade i.e. $600k**."* (ties to the 7b ICAP 5Y row exactly.)
- Benefit: *"the IM is reduced by **$17 million** to $244 million [LCH]. And then the CME Account. Also a reduction of **$17 million**. So in total we have **reduced our overall margin requirement by $34 million**."*
- **Funding maths, verbatim (p.12):** *"Assuming an overnight funding rate of **50 bps**, this is a saving in funding cost of **0.50% on $34m = 0.50% * 1/360 * 34,000,000 = $472 per day**. Present Valuing for five years, that would be DV01 5 year swap * Notional * 50bp = **(~$460 per million) * 34 * 50 = $782,000**, But IM will not be constant for 5 years, so lets take an average maturity = **460*34*50*0.5 = $391,000**. Meaning that our funding cost saving is around **$400,000**."*
- *"Our default fund contribution could be estimated crudely at **8% of IM**, which presumably would be charged at an **equity capital rate of say 10%**, so a saving of **$270,000**. … even our simple example shows a saving of **$670,000**. That makes the $600k not look too bad at all."*
- **Regime note (p.12, verbatim):** *"even though we are paying +1.2bps more than we are receiving on this CCP Switch trade, assuming the basis remains at 1.2bps, **the mark to market of the trade will become zero and not minus $600k**"* — once CME's EOD curve incorporates CME-specific observations.

**All of the above verified arithmetically** (`tieout.py`): 218+262=480 ✓; 1.66842−1.65642=1.20bp ✓; 0.005×34e6/360=$472.22 ✓; 460×34×50=782,000 ✓; ×0.5=391,000 ✓; 0.08×34e6×0.10=$272,000 ✓.

### 7e. `Pricing\xa0and Arbitraging\xa0the CME_LCH Basis - Clarus Financial Technology.pdf` — Tod Skarecky, June 22, 2015, 26pp

**STRUCTURE.** Spot-start 5YR: **Payer LCH at 1.86111%, Receiver CME at 1.87361%**, $100m (p.3, "CME/LCH Switch Trades" table).

**GOLD: second full published term structure.** p.2, ICAP SEF, `06/17 15:52 GMT`, page 19981, `USD INDICATIVE IRS SEMI BOND LCH / CME BASIS`:

| SB Term | LCH MID | CME (bps) | CME MID |
|---|---|---|---|
|1Y|0.56780|+0.2500|0.57030|
|2Y|0.98745|+0.3500|0.99095|
|3Y|1.34712|+0.6000|1.35312|
|4Y|1.63128|+0.9500|1.64078|
|5Y|1.86111|+1.2500|1.87361|
|6Y|2.04204|+1.4500|2.05654|
|7Y|2.18374|+1.5500|2.19924|
|8Y|2.29618|+1.6500|2.31268|
|9Y|2.38897|+1.7300|2.40627|
|10Y|2.46487|+1.8500|2.48337|
|12Y|2.58388|+1.9000|2.60288|
|15Y|2.70127|+2.0500|2.72177|
|20Y|2.81167|+2.2000|2.83367|
|25Y|2.86407|+2.3000|2.88707|
|30Y|2.89247|+2.4000|2.91647|

**GROSS EDGE (p.2, verbatim):** *"**1.25 basis points on a 5 year swap. On a 100 million USD swap (average 5Yr notional) that would be $12,500 per year, or $62,500.**"* Verified: 1.87361−1.86111 = 1.25bp ✓; 1.25e-4 × $100m = $12,500/yr, ×5 = $62,500 ✓.

**COSTS — the most complete cost stack in the corpus (pp.5-11, verbatim):**
- Execution: *"Bloomberg SEF offers trades at **$10** … at 10 bucks per side, the total cost is **$20**."* Caveat: *"the basis market really only exists on the **IDBs** at the moment. If I wanted to trade a CME/LCH switch I might have to **leg into it on a client SEF and eat the spread on each side**."*
- DCO fees: *"Trade booking fee … these seem to be **~$4 per million 'standard' or $25 'active'**. Maintenance fee … it would seem to be **$2 – $3 per million per annum** on the standard schedule."*
- FCM fees: *"Trade booking fee should be **~$1,000**. Maintenance fees run anywhere from **10 – 100 basis points on IM**, charged periodically … one FCM raising this fee **by 75bp** … There are typically **monthly minimum fees that run into the tens of thousands of dollars**."*
- IM: *"my day 1 Initial margin comes to roughly **$3.9 million** and tapers down over 5 years."*
- Assumed IM funding term structure: *"lock in 5 years of funding, which I will do in **1 year increments**."*
- **Result (p.10, verbatim): "my $62,480 gain is now down to just over $45,000."** (i.e. **~28% of gross edge eaten by fees before IM funding**.)
- **CONCLUSION (p.11, verbatim): "Alas, given all of my very favorable assumptions on overhead, SEF execution, and FCM fee structures, it becomes clear that this just isn't going to work. Even if I am willing and able to fund at overnight rates (maybe 15bp for a while) this starts to become murky. Further, even if I assume my investors are happy using firm capital to fund the margin, I am not beating treasuries. And really, 10bp FCM IM maintenance fees are not happening. Plug in 50bp and the analysis starts to become more credible (and further loss-making)."**

**This is the corpus's headline negative result: a 1.25bp 5Y CME-LCH basis is NOT arbitrageable by a client, under deliberately generous cost assumptions.**

### 7f. `CME vs. LCH_ Take Two _ FIA.pdf` — FIA MarketVoice, Nicola Tavendale, 21 December 2017, 5pp

**NEGATIVE FINDING — this document is off-topic for the IRS CME-LCH basis.** It is entirely about **NDF / OTC FX clearing** (CME's ForexClear challenge, FX Link, OTC FX options clearing). It contains **no IRS CME-LCH basis levels, no convexity content, no strategy, no tie-out numbers for this project.**

The only transferable facts: *"CME estimates that the **margin offsets between NDFs and non-deliverable interest rate swaps** denominated in currencies such as the Brazilian real and the Korean won **could go as high as 51%**."* And a structural claim that echoes the IRS story: *"At LCH, the ForexClear service has its own default fund that is separate from its clearing services for other asset classes such as interest rate swaps. At CME, NDFs are under the same umbrella … That opens the door for **margin offsets that LCH cannot offer**."* Plus the analogy quote: *"In IRS clearing we saw the buyside use CME initially while big dealers used LCH and it will be interesting to see if the same occurs with FX clearing … CME do offer risk offsets between FX futures and OTC FX … but **dealers may prefer the LCH model due to larger netting pool**."*

---

## 8. `Pricing and Hedging USD SOFR Interest Rate Swaps with SOFR Futures - CME Group.pdf` — CME Group, Mark Rogerson, 04 Jun 2025, 27pp

**This is by far the richest known-answer tie-out document in the corpus: a fully specified, fully numeric worked example, all of it printed.** Every arithmetic relation below was independently re-derived and **matched exactly** (`tieout.py`).

**BASE CASE (pp.5-11).** As-of April 2025. $100m 2y IMM-dated OIS, Jun-2025 start, quarterly/quarterly, 91 days each period.

| Contract | Start | End | Code | Price | Yield % | DF (period) | Cum DF |
|---|---|---|---|---|---|---|---|
|Jun-2025|18-Jun-25|17-Sep-25|SFRM5|95.895|4.105|0.989730|0.989730|
|Sep-2025|17-Sep-25|17-Dec-25|SFRU5|96.290|3.710|0.990709|0.980535|
|Dec-2025|17-Dec-25|18-Mar-26|SFRZ5|96.605|3.395|0.991491|0.972191|
|Mar-2026|18-Mar-26|17-Jun-26|SFRH6|96.815|3.185|0.992013|0.964427|
|Jun-2026|17-Jun-26|16-Sep-26|SFRM6|96.940|3.060|0.992324|0.957024|
|Sep-2026|16-Sep-26|16-Dec-26|SFRU6|96.985|3.015|0.992436|0.949786|
|Dec-2026|16-Dec-26|17-Mar-27|SFRZ6|96.965|3.035|0.992387|0.942555|
|Mar-2027|17-Mar-27|16-Jun-27|SFRH7|96.910|3.090|0.992250|0.935249|

Sum discounted floating CFs **0.0647505**; sum discounted daycount **699.926**; ×360 → **23.310**; **Coupon Rate = 3.3304%**.

**SPECIFIC CONVENTION FACTS (all printed):**
- *"the price of an expiring SR3 contract is 100 minus the compounded SOFR rate … if the realized, compounded SOFR rate for the contract reference period is **3.748%**, the contract's final settlement will be **96.252**."* (p.2)
- *"if the price of the aforementioned March 2025 (SFRH5) contract is observed at **95.705**, that would imply an expected 3-month compounded rate of **4.295%**. By using a simplifying assumption that overnight rates remain constant during the reference period, we can decompound the futures-implied 3-month rate to an overnight rate, which would imply day-to-day SOFR overnight benchmark is in the region of **4.2725%**."* (p.2)
- *"Critical dates for each contract run from and including the **third Wednesday** of the contract's named month up to, but not including the third Wednesday of the month 3 months after."* (p.2)
- *"The price of a SOFR pack or bundle is quoted as the **arithmetic average** of the price levels of its constituent contracts."* (p.12) — verified: mean(8 prices) = **96.675625** ✓
- *"packs and bundles of SOFR futures are eligible to trade in minimum price increments of **0.25bp**."* (p.12)

**MARKET-MAKER EDGE / COSTS (pp.11-13, verbatim):**
- *"a bid/ask spread of **half a basis point**, hence **3.3275/3.3325** … the market maker could buy futures at the prices in the table to lock-in a receive fixed hedge at 3.3304, thus making a hypothetical profit of **0.29 basis points**."*
- *"a market maker may elect to buy the bundle at **96.6775** … 96.6775 - 96.675625 = 0.001875 or **0.1875bp**. As a result, **the net profit from hedging the swap with a bundle of futures is ~0.1bp (0.29 less 0.1875)**."*
**This is the corpus's cleanest cost benchmark: a 2-year bundle hedge costs 0.1875bp against a 0.5bp two-way swap spread, leaving ~0.1bp.**

**HEDGE CONSTRUCTION — bump-and-reprice, per contract (pp.13-17):**
Hedge vector (contracts, short, for a $100m receive-fixed): **SFRM5 100, SFRU5 99, SFRZ5 99, SFRH6 98, SFRM6 97, SFRU6 96, SFRZ6 95, SFRH7 95 = total 779.** Swap DV01 **$19,480.69**; 779 × $25 = **$19,475** (residual $5.69). *"the number of futures required for hedging movement in the second contract is 99 rather than 100 … because the effect of discounting on the swap reduces the change in value as we move along the curve, whereas the value of 1 basis point move in futures remains the same at $25 per basis in all contracts near or far-dated. **This characteristic is what leads to the convexity bias**."* (p.16)

**CONVEXITY P&L TABLE (p.18) — position: receive fixed $100m 2y Jun-25 IMM OIS at 3.3304%, short 779 SR3.** All 8 rows verified (swap + futures = total):

| | −10bp | −25bp | −50bp | −100bp |
|---|---|---|---|---|
|Change in value for $100m|$195,003|$488,326|$979,388|$1,969,792|
|Change in value of 779 futures sold|−$194,750|−$486,875|−$973,750|−$1,947,500|
|**Total P&L from "hedged" position**|**$253**|**$1,451**|**$5,638**|**$22,292**|

| | +10bp | +25bp | +50bp | +100bp |
|---|---|---|---|---|
|Change in value for $100m|−$194,568|−$485,606|−$968,509|−$1,926,274|
|Change in value of 779 futures sold|$194,750|$486,875|$973,750|$1,947,500|
|**Total P&L from "hedged" position**|**$182**|**$1,269**|**$5,241**|**$21,226**|

**Re-hedge / gamma identity (pp.19-20, verbatim):** *"the DV01 has risen from **$19,480 to $19,921** and the futures hedge has risen from originally **779 contracts to 797 contracts** … if we model simple linear change of hedge by taking the difference in hedges, **797 - 779 = 18**, half that and then multiply the change of rates and the tick value - **18 x 0.5 x 100 x 25 = 22,500** … almost identical to the total P&L from 'hedged' position at -100bp."* Verified: 22,500 vs printed 22,292 (**diff $208**). *"The reason we half the position is to represent the increasing size of the difference in hedges over the movement in rates."*

**Direction convention (p.20, verbatim):** *"This hypothetical position of **received fixed in IRS versus short STIR futures** … is considered to be a **'long convexity'** position. Conversely, the opposite position of **paid fixed in IRS versus long STIR futures is considered 'short convexity.'**" … "**The difference in the price of a swap and the price implied by futures prices is essentially the cost of the premium for buying the embedded option in the convexity position.**"*

⚠️ **Sign-convention hazard vs the Citi notes.** CME's "short convexity" = pay fixed + long futures. Citi's "sell convexity adjustment" = **buy packs + pay fixed on the matched swap** — the *same* leg directions. Consistent, but note that CME's example runs the *opposite* (long-convexity) direction, so its P&L signs must be flipped before comparing to a Citi short-CA book.

**MARGIN (pp.22-25) — the corpus's only complete, current portfolio-margin tie-out:**

| Code | Hedge | Performance bond per contract $ | Total $ |
|---|---|---|---|
|SFRM5|100|425|42,500|
|SFRU5|99|650|64,350|
|SFRZ5|99|765|75,735|
|SFRH6|98|825|80,850|
|SFRM6|97|825|80,025|
|SFRU6|96|825|79,200|
|SFRZ6|95|800|76,000|
|SFRH7|95|750|71,250|
|**Total**|**779**| |**569,910**|

- *"the total cost of the initial margin in the futures hedges (**$569,910**) is approximately **36%** of the total cost of the IM in the interest rate swap (**$1,568,352**)."* (verified 36.34%)
- *"futures are afforded a **margin period of risk (MPOR) of 1 day** under U.S. regulations … the more complex nature of IRS means that they are designated to have a **5 day margin period of risk**."*
- **"the total initial margin of the portfolio is $46,161 versus the margin that would be required if Portfolio Margining was not available at $2,138,262. The power of Portfolio Margining is evident, as it can result in nearly a 98% reduction."** (verified: 569,910+1,568,352 = 2,138,262 ✓; 1−46,161/2,138,262 = **97.84%** ✓)
- **Three eligibility conditions (p.25, verbatim):** *"1. Both the futures and the IRS need to be cleared at CME Group. 2. The participant needs to use the same FCM (Futures Commission Merchant) for both the futures and the IRS. 3. The legal entities of the counterparties to the transactions need to demonstrate the same beneficial ownership."*
- *"the total savings accruing to clients who benefit from Portfolio Margining in interest rates has risen from **just over $2 billion in 2018 to a peak of over $9 billion in early 2025**."* (p.25)

---

## 9. `The disappearing convexity bias _ Welcome to STIR futures.pdf` — Stephen Aikin, December 16, 2013, 5pp

**PAYOFF DEFINITIONS (p.1, verbatim — the primitive the Clarus article borrows):**
> "The payoff of a short STIR future is given by **(L%-F%)* 10000*$25**
> The payoff of a short FRA is given by **((F%-L%)* Notional*0.25)/(1+L%*0.25)**
> Where F% is the FRA forward rate or rate implied by STIR; L% is the FRA maturity date LIBOR rate or futures EDSP rate. 0.25 is the 3-month accrual (in reality measured by ACT/360 convention for USD and EUR). $25 assumes Eurodollar tick value per basis point."

**WORKED EXAMPLE / RISK WEIGHTING (p.2, verbatim):**
> "The table shows the convexity bias between a position of **short 1000 Eurodollar (ED) futures and an offsetting short $1005m 3-month FRA (slightly more than $1000m to compensate for discounting methodology), both instigated at a rate of 2%.**
> An increase in underlying rates from **2% to 2.10%** would result in a credit to the variation margin account of short 1000 ED STIR position of **$250,000** and a debit of slightly less than that in the discounted equivalent of $1005m 3M FRA collateral account (assuming zero threshold …).
> A decrease in underlying rates of 10 basis points to **1.9%** would result in a debit … of **$250,000** and a credit of slightly more than that …"

**MONETISATION MECHANISM (p.3, verbatim):** *"The convexity bias is monetarised via margining. The short STIR future position would result in beneficial variation margin flows. If rates moved higher, the variation margin account would be credited and this could be lent out at higher overnight rates. If rates moved lower, the variation margin deficit could be financed at lower rates. **Time and rate volatility would give rise to what is effectively a long gamma payoff.**"*

**THE CENTRAL CAUSAL CLAIM (p.3, verbatim — the whole thesis of the note):**
> "However, as a consequence of the financial crisis, many over-the-counter derivatives like FRA's and swaps are migrating to an exchange traded and central counterparty cleared model, **the convexity bias has largely disappeared as both products will be margined in a similar futures like way.**
> Furthermore, today's low interest rate environment means that **margins are subject to higher funding rates that often exceed the amounts that can be earned on margin**. Also, funding margin accounts can be very capital intensive for products that don't benefit from cross margining benefits. For example, a **Euribor STIR future trade against a EUR swap/FRA might attract two sets of independent margins whereas a Eurodollar STIR future trade against a USD swap/FRA would be more capital efficient since both products are cleared by CME Group.**"
> "The chart shows the convexity bias that used to exist on Eurodollar futures **prior to 2011**, when central counterparty clearing for swaps and FRA's gained traction. **Now it has largely disappeared due to the cross margining benefit of both products being cleared and margined by CME Group.**"

**NEGATIVE-CONVEXITY-BIAS CLAIM (p.4, verbatim — a hard falsifier for any model that floors CA at zero):**
> "In Europe, **the bias went slightly negative this summer** mainly since margins for **LIFFE Euribor futures could not be netted against margins for Euro FRA's cleared at SwapClear**. Any trader doing the European convexity bias trade would have to post two sets of margin and as the rate paid on margin is lower than the trader's own funding costs, a substantial funding adjustment results which would be greater than value of the convexity bias. **Consequently, there was nothing to prevent the bias going negative!**"

No entry/exit rules, no thresholds, no costs quoted. The chart ("ED Convexity bias", p.4) is unlabelled on the y-axis in the extracted text — no numeric levels recoverable.

---

## Bonus documents (present in the folder, beyond the required list, materially relevant)

**`interest rates - STIR Futures convexity adjustment - Quantitative Finance Stack Exchange.pdf`** (asked/answered 13-14 Jun 2025; answer by **Attack68**, the rateslib author). **This is a directly reproducible known-answer test for this codebase.** The accepted answer implements approach 4 (imply CA from swaps) as a `rateslib` `CompositeCurve` of a `stir_curve` plus a 3-node spline `convexity` curve, solved against 12 monthly 1m IRS "STIR proxies" plus a 6m and a 12m swap. **Fully specified inputs** (rates, %): `[2.3, 2.2, 2.05, 1.93, 1.94, 1.98, 2.02, 2.09, 2.15, 2.25, 2.32, 2.37]` for the 12 monthly proxies from `dt(2000,1,1)`, then `2.070` (6m) and `2.146` (12m). **Printed outputs** (`future[0].rate(curves=convexity)`, 12 values, %):
`0.003867533154249832, 0.004124170133401605, 0.004637442503942974, 0.0054173163792192724, 0.00646096935165833, 0.007765535595627427, 0.009244030058451792, 0.010567096097501677, 0.011607910720368153, 0.012387808800557796, 0.012909634790236879, 0.013170544225162768`
(= **0.387bp rising monotonically to 1.317bp**). Header comment: `# rateslib 2.0, python 3.12` — **this repo runs rateslib 2.7.1, so re-running may not reproduce bit-for-bit; treat version drift as the first suspect on a mismatch.**

**The answer's methodological warning (verbatim — directly contradicts the Citi/JPM model-based approach):**
> "**1. 2. and 3. are theoretical using vol, covariance and models. The problem with all three of them is that they don't include supply and demand dynamics. I have experienced numerous markets, in GBP and EUR, where STIR convexity is just not based on those models. It depends upon positioning, clearing house margin, where the futures tend to trade (EUREX, ICE-liffe, CME) and what are the respective swaps clearing house basis markets. These effects can engulf the theoretical prices. I've also seen real market positive convexity prices, which are impossible theoretically.**"
> "I have always adopted approach **4**, generally calibrating my convexity inputs to major traded short swaps inputs, with some simple parameter model for smoothing the convexity over the contracts."

Liquidity constraint from the comments (`river_rat`): *"There is very little pricing information passed the reds generally … **The greens only trade at 40% the ADV of the reds** for example, blues even worse."*

**`LCH-CME Switch Trades and Margin Management - Clarus Financial Technology.pdf`** — Amir Khwaja, June 30, 2014, 21pp. The pre-blowup baseline. Published: dealer house IM **$103m CME / $202m LCH**; LCH worst historical scenario date **13 Nov 2008**, loss **$204m**, of which 10Y contributes **$127m** on a 10Y DV01 of **1,700,000** with the 10Y rate dropping **63bps**; CME 10Y contributes $25m on DV01 **−624,000**. A **$285m notional 10Y switch with DV01 250,000** takes CME 10Y DV01 −624,000→−374,000 and LCH 1,700,000→1,450,000, overall 10Y DV01 unchanged at 1,076,000; **LCH IM −$38m, CME IM −$10m, total −$48m on $305m = a 16% drop**. Market microstructure: *"the standard size 10Y Swap is **$50 million**, the block size is **$170 million** and on average **$6-10 billion** gross volume trades in a day."* **Crucially, the June-2014 basis level (verbatim): "(Note: There can be a small basis spread (<0.1 bps) between CME and LCH rates, which would need to be monitored over time)."** — i.e. **<0.1bp in Jun-2014 → 1.9bp by 18-May-2015 → 2.5bp by 26-May-2015 → 2.4bp (30Y) 17-Jun-2015 → 3.40bp 26-Jun-2017.** Volumes: *"$2.5b of 18M and $3b of 5Y traded in the week of 16-20 June [2014]"*.

**`Understanding open interest _ Welcome to STIR futures.pdf`** — Stephen Aikin, January 24, 2014, 4pp. **Contains the corpus's one explicit NEGATIVE OI claim (p.3, verbatim): "There does not seem to be an obvious link between increasing open interest and price action but it might be useful to keep a watch on contract levels to gauge any potential flows."** General framing: *"Technical practitioners generally expect open interest to increase when a trend is establishing and reduce when the trend is coming to an end."* Charts: ED and Euribor market OI vs continuous close, 2002-2013. No numbers extractable.

---

## Cross-document synthesis: the relationship claims

| Link | Direction claimed | Source | Verbatim anchor |
|---|---|---|---|
| Implied vol → CA | Positive, **defines** fair value | Citi 1/2/3; JPM 5 | JPM: `A_cvx = σ²T₁T₂/2` |
| **Dealer net long ED → CA rich (vs model)** | Positive | JPM 5 p.2; Citi 1 p.2 | JPM: *"beta and correlation … consistently positive … peaks roughly 2 to 3 years forward"*; Citi Fig 4: **y=2E-06x−0.1053, R²=0.2724** |
| **Client short ED positioning → CA WIDE (cheap futures)** | Positive | Citi 1 p.2, Citi 2 p.2 | *"widening of Blues CAs has been driven by stretched short positioning"* — **note Citi and JPM use opposite sign conventions for "rich": Citi's short-client = dealer-long = CA wide = CA rich vs model. Consistent once you map "dealer net long" ≡ "client net short".** |
| **Open interest rising in Reds/Greens → no short covering → CA stays dislocated** | Positive (level, not flow) | Citi 2 p.2 Fig 4 | *"open interest in Reds and Greens has continued an upward trend … No signs of short covering"* |
| Open interest → price action generally | **NONE** | Aikin (OI) p.3 | *"There does not seem to be an obvious link"* |
| **IM (un-nettable, two CCPs) → CA rich AND CME-LCH basis wide** — same mechanism | Positive, **linear in IM** | JPM 5 p.3 | *"if the IM … were suddenly halved … the convexity adjustment net of vol-driven financing bias should decline by a proportional amount"* |
| **CCP netting (portfolio margining) → convexity bias disappears** | Negative | Aikin 9 p.3 | *"it has largely disappeared due to the cross margining benefit of both products being cleared and margined by CME Group"* |
| **CME-LCH basis wide → LCH-cleared CAs wider than CME-cleared CAs** | Positive | Citi 1 p.4 | *"convexity adjustments are wider for LCH-cleared swaps"* |
| **CME/LCH basis narrow at front end + CME netting benefit unpriced → CME convexity RICH** | Composite | JPM 5 p.3 | *"convexity adjustments are rich and the CME/LCH basis is too narrow; selling CME-based convexity adjustments monetizes both effects"* |
| Curve slope (ED5/ED9, ED6/ED16) → CA model value | Positive (steeper = higher vol = higher CA) | Citi 1 p.4, Citi 2 p.3 | *"a steeper curve is normally associated with greater uncertainty about the future Fed path and therefore higher vol"* |
| Outright rate level → CCP basis | **Open question, unmodelled** | Clarus 7c p.10 | *"are we ready to model the correlation effect of outright rates on CCP basis?!"* |
| Basis vs cost fundamentals | **Decoupled** | Clarus 7a p.10 | *"the basis market is a market unto itself, complete with speculation and panic, so it can move regardless of these costs"* |

---

## Consolidated tie-out table

Status: **VERIFIED** = re-derived arithmetically and matches; **PRINTED** = published, no independent check possible from the document alone; **DIFF** = published but my re-derivation disagrees; **CHART** = read off a chart, approximate.

| # | Source doc (PDF page) | Date | Quantity | Value | Units | Status |
|---|---|---|---|---|---|---|
|1|Blues (p.3/p.15)|close 1/5/2018|Full 17-row 1y-ED-pack CA table (CA, Δ1w, 3m/1Y Z, vs-model, roll, impl vol, rlzd vol, ratios)|see §1 table|bp / z / vol-bp|PRINTED|
|2|Blues (p.5)|10am 1/5/2018 [sic "1/5/2017"]|H1-Z1 CA entry level (pack vs matched-maturity 3/17/21–3/16/22 CME swap)|**6.5**|bp|PRINTED|
|3|Blues (p.5)|1/5/2018|Trade size / hedge legs|1000 H1-Z1 packs vs $1bn; buy 130 EDM9 @97.53, sell 176 EDZ1 @97.495|contracts / $|PRINTED|
|4|Blues (p.4/5)|1/5/2018|ED6/ED16 DV01 weights vs contract ratio 130/176|0.74 vs **0.7386**|ratio|VERIFIED|
|5|Blues (p.5)|1/5/2018|Package 3m carry (CA +$130K, hedge +$10K)|**+$140,000**|USD/3m|VERIFIED|
|6|Blues (p.4)|1/5/2018|ED6/ED16 steepener carry|**+2**|bp/3m|PRINTED|
|7|Blues (p.5 Fig 6)|Jan-99→2017|Blues-CA model regression|`-0.65+0.044*(ED16-0.74*ED6)`|bp out; **ED in bp (inferred)**|PRINTED (units inferred)|
|8|Blues (p.3 Fig 4)|monthly, 1/1/13–12/26/17|Δ Blues-CA-vs-model on Δ dealer positioning|**y=2E-06x−0.1053, R²=0.2724**|bp per mm|PRINTED|
|9|Greens (p.14)|close 5/12/2017|Full 17-row 1y-ED-pack CA table|see §2 table|bp / z / vol-bp|PRINTED|
|10|Greens (p.4)|9:30am 5/15/2017|M9-H0 CA entry level|**about 4.5**|bp|PRINTED|
|11|Greens (p.4)|9:30am 5/15/2017|Hedge legs|sell 167 EDM9 @98.065, buy 141 EDM8 @98.41|contracts|PRINTED|
|12|Greens (p.3/4)|5/15/2017|ED5/ED9 DV01 weights vs 167/141|−1/1.18 vs **1.1844**|ratio|VERIFIED|
|13|Greens (p.3 Fig 5)|Jan-00→2017|Greens-CA model regression|`-3.53*ED5+4.17*ED9`|bp out; **ED in % (printed)**|PRINTED|
|14|Greens (p.3 Fig 5)|—|Regression coef ratio 3.53/4.17 vs 1/1.18|0.8465 vs 0.8475|ratio|VERIFIED|
|15|Greens (p.4)|5/15/2017|Package 3m roll|**+0.88**|bp/3m|PRINTED|
|16|Greens (p.2 Fig 2)|Jan-10→2017|Blues-CA fly proxy, **May-2017 vintage**|`9.7+20.6*(-0.705*2y+5y-0.465*10y)`|bp out; % in (inferred)|PRINTED|
|17|TurnGreen (p.2 Fig 1)|Jan-10→2017|Same fly proxy, **Jun-2017 vintage (re-fit)**|`10.2+21.4*(-0.70*2y+5y-0.46*10y)`|bp out; % in (inferred)|PRINTED|
|18|TurnGreen (p.2)|2/9/2017|Blues trade entry: 2000 H0-Z0 packs / $2bn CME swap|**8.8**|bp|PRINTED|
|19|TurnGreen (p.2)|2/9/2017|2s5s10s fly hedge weights / entry|$147mm / −$85.6mm / $20.89mm at **−18.2**|$mm / bp|PRINTED|
|20|TurnGreen (p.2)|1:30pm 6/6/2017|Blues exit: H0-Z0 CA / 2s5s10s fly|**6.6** / **−16.5**|bp|PRINTED|
|21|TurnGreen (p.2)|6/6/2017|Blues CA leg gross P&L (8.8−6.6)×$200k|**$440,000**|USD|VERIFIED|
|22|TurnGreen (p.2)|6/6/2017|Blues package **net P&L, net transaction costs**|**+$500,000**|USD|PRINTED|
|23|TurnGreen (p.2)|—|Blues P&L **target** (not reached)|**+$600,000**|USD|PRINTED|
|24|TurnGreen (p.2)|1:30pm 6/6/2017|Greens entry: 3000 M9-H0 packs / $3bn CME M19-M20|**4.3**|bp|PRINTED|
|25|TurnGreen (p.2)|6/6/2017|Greens hedge: sell 500 EDM9 @98.215, buy 424 EDM8 @98.46; ratio vs 1.18|**1.1792**|contracts / ratio|VERIFIED|
|26|TurnGreen (p.2)|6/6/2017|Greens **target / stop** (on $300k DV01 = +1.50bp / −0.75bp)|**+$450,000 / −$225,000**|USD|PRINTED|
|27|TurnGreen (p.2)|6/6/2017|Greens 3m roll|**+0.7**|bp/3m|PRINTED|
|28|TakeOffHedge (p.1)|8:30am 7/13/2017|M9-H0 CA mid|**3.35**|bp|PRINTED|
|29|TakeOffHedge (p.1)|7/13/2017|CA-leg MTM: (4.3−3.35)×$300,000|**$285,000**|USD|**VERIFIED (exact)**|
|30|TakeOffHedge (p.1)|8:30am 7/13/2017|Hedge unwind P&L|**+$70,500**|USD|**VERIFIED (exact) — but only with the INITIATION leg quantities (long 424 EDM8, short 500 EDM9). The alert's printed quantities are transposed and give +$33,450.** |
|31|JPM (p.2)|03 May 2017|Ho-Lee financing bias closed form|**A_cvx = σ²T₁T₂/2**|—|PRINTED|
|32|JPM (p.2)|2016→May 2017|Implied collateral funding spread vs 3M Libor|**L+50-100bp → nearly L+300bp**|bp|PRINTED|
|33|JPM (p.2)|—|pvbp-neutral ED-vs-FRA package total margin|**~1.3%**|% of notional|PRINTED|
|34|JPM (p.3)|—|CME-netted vs LCH-siloed IM saving|**70-80%**|%|PRINTED|
|35|JPM (p.3)|mid-2016→5/1/2017|Front-end CME/LCH spread|**well under 1bp; mostly ~0.25bp**|bp|PRINTED|
|36|JPM (p.3)|5/1/2017|CME CA net of theory as % of LCH CA|**~80%**|%|PRINTED|
|37|JPM (p.3 Ex.4)|5/1/2017|CME/LCH by tenor, current/avg/max|5Y ~1.25/1.25/2.7; 10Y ~2.7/2.35/4.1; 30Y ~3.85/3.3/5.4|bp running|**CHART**|
|38|JPM (p.3 Ex.5)|5/1/2017|Implied funding spread, LCH vs CME by contract|LCH ~50→300; CME peaks ~1000 at M9|bp/yr|**CHART**|
|39|Clarus ED-cvx (p.5)|Jul 1 2015|LCH IM on the FRA leg, rate-shifted|**$1.37m → $1.40m (lower rates); <$1.355m (higher)**|USD|PRINTED|
|40|Clarus ED-cvx (p.5)|Jul 1 2015|CME SPAN margin, 1,000 EDM6|**$425,000**|USD|PRINTED|
|41|Clarus ED-cvx (p.5)|Jul 1 2015|VM funding spread / IM funding rate assumption|**25bp (±12.5bp) / 0.50% (1y IRS)**|bp / %|PRINTED|
|42|Clarus ED-cvx (p.7)|Jun 2015|EDM6 CME FRA volume, single day|**~$40bn**|USD|PRINTED|
|43|**Clarus Spread (p.3)**|**05/18 15:21 GMT, 18-May-2015**|**ICAP 19981 full CME-LCH term structure, 1Y-30Y (LCH mid / CME bp / CME mid)**|**see §7b table; 30Y basis +1.9000**|bp|PRINTED|
|44|Clarus Spread (p.4)|18-May-2015|Bid/offer derivation (MID ∓ 0.125bp), 8 values 2Y/5Y/10Y/30Y|all 8|% rate|**VERIFIED**|
|45|Clarus Spread (p.2)|pre-2015|Historic "inconsequential" basis level|**0.15**|bp|PRINTED|
|46|Clarus Spread (p.2)|2015|Typical USD IRS bid-offer|**0.25**|bp|PRINTED|
|47|Clarus Spread (p.4)|18-May-2015|Value of 1.9bp on standard $25m 30Y|**$95,000** ⇒ implied DV01 **$50,000/bp ($2,000 per $1m)**|USD|**VERIFIED**|
|48|Clarus Spread (p.6)|18-May-2015|Switch cost basis+bid/offer 2.15bp on $25m / $250m 30Y|~$100,000 / ~$1,000,000 (computed $107,500 / $1,075,000)|USD|VERIFIED (Clarus rounds)|
|49|Clarus Spread (p.8)|May 2015|Two-CCP gross margin on $25m 30Y; funding+capital cost band|**$5.5m; 0.50–1.5bp**|USD / bp|PRINTED|
|50|Clarus Spread (p.9)|**May 1 2015**|**JPM upper bound on CME-LCH basis from futures/swaps cross-margin benefit**|**1.5**|bp (max)|PRINTED|
|51|Clarus Spread (pp.11-14)|30 Apr–15 May 2015|CCP-switch volumes|**>$20bn total; Tradition >$10bn; ICAP ~$10bn; 30 Apr $7bn; 5 May $2.7bn; 8 May $2.3bn; 12 May $1.9bn (Tullett); 13 May $1.8bn; 15 May $1.9bn**|USD notional, single-counted|PRINTED|
|52|Clarus Spread (p.5)|May 2015|Reported dealer loss from the basis blowup|**up to ~$20 million each**|USD|PRINTED (attributed to Risk)|
|53|**Clarus TermStruct (p.6)**|**18-May-15 and 26-May-15**|**Full CME-LCH basis, 2y-30y, both dates + change**|**see §7c table; max change +0.75bp at 4y**|bp|PRINTED|
|54|**Clarus TermStruct (p.5)**|**26MAY15 10:02**|**Tradition TRADTCCP CME-LCH spread mids, USD/EUR/GBP**|**see §7c table; 30Y USD 2.500 / EUR 0.350 / GBP 0.200**|bp|PRINTED|
|55|Clarus TermStruct (p.7)|26-May-2015|5y5y forward basis vs spot|**+2.9 vs +1.85**|bp|PRINTED|
|56|Clarus TermStruct (p.9)|26-May-2015|**Max roll-down, 1y forwards**|**1.1**|bp/yr|PRINTED|
|57|Clarus TermStruct (p.4)|30 Apr–15 May 2015|CME-LCH share of TradX USD swap volume, 7y / 10y|**21% / 15%**|%|PRINTED|
|58|Clarus Hedging (p.4)|26-May-2015|Example book IM: CME / LCH / gross; vs single-CCP|**$218m / $262m / $480m; vs $5–10m**|USD|VERIFIED (sum)|
|59|Clarus Hedging (p.5)|26-May-2015|Book 01: CME −$5.8m, LCH +$5.8m, net|**−$20,000 per point**|USD/bp|PRINTED|
|60|Clarus Hedging (p.5)|26-May-2015|5Y basis move and resulting loss; whole-portfolio loss|**+1.2bp ⇒ $1m on −$1m 01; $7.5m total**|bp / USD|PRINTED|
|61|Clarus Hedging (pp.8-9)|26-May-2015|$1bn 5Y switch: 01 changes|LCH leg −$450k; LCH acct 5Y 01 → $695k; CME −$1m → −$560k|USD/bp|PRINTED|
|62|Clarus Hedging (p.9)|26-May-2015|Switch cost: rec 1.65642 / pay 1.66842 = 1.2bp on $1bn|**1.2bp = $600,000**|bp / USD|**VERIFIED**|
|63|Clarus Hedging (pp.10-11)|26-May-2015|IM reduction from switch|**−$17m LCH, −$17m CME = −$34m**|USD|VERIFIED (sum)|
|64|Clarus Hedging (p.12)|26-May-2015|Funding saving arithmetic chain|**$472/day; 460×34×50=$782,000; ×0.5=$391,000 ≈ $400k**|USD|**VERIFIED (all 3)**|
|65|Clarus Hedging (p.12)|26-May-2015|Default-fund saving: 8% of IM × 10% equity rate|**$272,000 (Clarus prints "$270,000")**|USD|**VERIFIED**|
|66|Clarus Hedging (p.12)|26-May-2015|Total benefit vs $600k cost|**$670,000 vs $600,000**|USD|PRINTED|
|67|**Clarus Arb (p.2)**|**06/17 15:52 GMT, 17-Jun-2015**|**ICAP SEF 19981 full CME-LCH term structure, 1Y-30Y**|**see §7e table; 5Y +1.2500, 30Y +2.4000**|bp|PRINTED|
|68|Clarus Arb (p.2)|17-Jun-2015|Gross edge: 1.25bp on $100m 5Y|**$12,500/yr = $62,500 over 5y**|USD|**VERIFIED**|
|69|Clarus Arb (pp.6-8)|Jun 2015|Cost stack: SEF exec; DCO booking; DCO maint; FCM booking; FCM IM maint|**$10/side; ~$4/mm std or $25 active; $2–3/mm/yr; ~$1,000; 10–100bp of IM (one FCM +75bp)**|USD / bp|PRINTED|
|70|Clarus Arb (p.11)|Jun 2015|Day-1 IM on the $100m 5Y switch package|**~$3.9 million**|USD|PRINTED|
|71|Clarus Arb (p.10)|Jun 2015|**Net P&L after fees, before IM funding**|**"just over $45,000"** (from $62,480)|USD|PRINTED|
|72|Clarus Arb (p.11)|Jun 2015|**Verdict**|**"this just isn't going to work … I am not beating treasuries"**|—|PRINTED|
|73|**Clarus Dummies (p.6)**|**26-Jun-2017 11am EDT**|**Tradition CME-LCH mid term structure, 1Y-50Y**|**see §7a table; 30Y 3.40**|bp|PRINTED|
|74|Clarus Dummies (p.3, pp.7-8)|Jun 2017|Hypothetical dealer base IM: CME / LCH|**$1,237,414,920 / $4,964,143,911**|USD|PRINTED|
|75|Clarus Dummies (pp.7-8)|Jun 2017|Incremental IM from one $100m 30Y at each CCP|**CME +$10,496,311; LCH +$21,109,203**|USD|PRINTED|
|76|Clarus Dummies (p.9)|Jun 2017|Funding-spread assumption|**20bp over Fed Funds**|bp|PRINTED|
|77|Clarus Dummies (p.9)|Jun 2017|**MVA in USD: CME / LCH / Total**|**$282,867 / $443,678 / $726,545**|USD|**VERIFIED (sum)**|
|78|Clarus Dummies (p.9)|Jun 2017|Trade DV01 ($100m 30Y)|**$225,000**|USD/bp|PRINTED|
|79|Clarus Dummies (p.10)|Jun 2017|**MVA in bp: CME / LCH / Total**|**1.30 / 2.10 / 3.40**|bp|**DIFF** — MVA/DV01 gives **1.257 / 1.972 / 3.229**. Implied DV01s ($217,590 vs $211,275) are mutually inconsistent. **Do not use MVA/DV01 as the tie-out identity.**|
|80|Aikin cvx (p.1)|Dec 2013|Short-ED payoff / short-FRA payoff|`(L−F)·10000·$25` / `((F−L)·N·0.25)/(1+L·0.25)`|—|PRINTED|
|81|Aikin cvx (p.2)|Dec 2013|Convexity-bias example weighting and VM|**short 1000 ED vs short $1005m 3M FRA at 2%; ±10bp ⇒ ±$250,000**|contracts / USD|PRINTED|
|82|Aikin cvx (p.4)|summer 2013|Euribor convexity bias sign|**"went slightly negative"** (LIFFE futures vs SwapClear FRAs, two IM pools)|—|PRINTED|
|83|CME SOFR (p.5)|Apr 2025 (hyp.)|8-contract SR3 strip prices/yields SFRM5→SFRH7|see §8 table|price / %|PRINTED|
|84|CME SOFR (pp.7-9)|—|DFs, cum DFs, discounted CFs, sum 0.0647505, daycount 699.926, ×360 = 23.310|see §8|—|PRINTED|
|85|CME SOFR (p.11)|—|**2y IMM OIS par coupon from the strip**|**3.3304%**|%|PRINTED|
|86|CME SOFR (p.12)|—|2y bundle price = mean of 8 prices|**96.675625**|price|**VERIFIED**|
|87|CME SOFR (pp.11-13)|—|MM spread / gross edge / bundle slippage / net edge|**0.5bp (3.3275/3.3325) / 0.29bp / 0.1875bp / ~0.1bp**|bp|**VERIFIED**|
|88|CME SOFR (p.17)|—|Futures hedge vector and total|**100,99,99,98,97,96,95,95 = 779**|contracts|**VERIFIED**|
|89|CME SOFR (p.17)|—|Swap DV01 vs 779×$25|**$19,480.69 vs $19,475**|USD/bp|**VERIFIED**|
|90|CME SOFR (p.18)|—|Convexity P&L, 8 rate scenarios (−100…+100bp)|**$253 / $1,451 / $5,638 / $22,292 ; $182 / $1,269 / $5,241 / $21,226**|USD|**VERIFIED (all 8)**|
|91|CME SOFR (p.19)|—|DV01 and hedge at −100bp|**$19,921 / 797 contracts**|USD/bp, contracts|PRINTED|
|92|CME SOFR (p.20)|—|Linear gamma approximation 18×0.5×100×$25|**$22,500 vs printed $22,292 (diff $208)**|USD|**VERIFIED**|
|93|CME SOFR (p.22)|Jun 2025|Per-contract performance bond, 8 contracts; total|**425/650/765/825/825/825/800/750 ⇒ $569,910**|USD|**VERIFIED (sum)**|
|94|CME SOFR (p.23)|Jun 2025|Swap IM; futures as % of swap IM|**$1,568,352; ~36% (computed 36.34%)**|USD / %|**VERIFIED**|
|95|CME SOFR (p.24)|Jun 2025|**Portfolio-margined IM vs un-netted; reduction**|**$46,161 vs $2,138,262; ~98% (computed 97.84%)**|USD / %|**VERIFIED**|
|96|CME SOFR (p.23)|—|MPOR: futures vs IRS|**1 day vs 5 days**|days|PRINTED|
|97|CME SOFR (p.25)|2018→early 2025|Client portfolio-margining savings, rates|**just over $2bn → over $9bn**|USD|PRINTED|
|98|CME SOFR (p.2)|—|SR3 settlement identities|100−3.748=96.252; 100−95.705=4.295; decompounded ON ≈4.2725%|price / %|**VERIFIED (first two)**|
|99|QSE (pp.4-5)|13-Jun-2025|**rateslib CompositeCurve implied convexity, 12 monthly contracts**|**0.003868 → 0.013171 (%) = 0.387 → 1.317 bp**, inputs fully specified in §Bonus|% (rateslib `.rate()`)|PRINTED — **directly reproducible; note `rateslib 2.0` vs this repo's 2.7.1**|
|100|Switch2014 (pp.2-5)|30-Jun-2014|Dealer IM $103m CME / $202m LCH; 13-Nov-2008 worst loss $204m; 10Y $127m on DV01 1,700,000 at −63bp; $285m 10Y switch DV01 250,000 ⇒ IM −$38m LCH / −$10m CME = −$48m on $305m = **16%**|as listed|USD / bp / %|PRINTED|
|101|Switch2014 (p.5)|Jun 2014|**CME-LCH basis level, pre-blowup**|**<0.1**|bp|PRINTED|
|102|Switch2014 (p.4)|Jun 2014|10Y USD swap standard / block size; daily gross volume|**$50m / $170m / $6–10bn**|USD|PRINTED|
|103|FIA (p.3)|21-Dec-2017|CME NDF-vs-non-deliverable-IRS margin offset|**up to 51%**|%|PRINTED — **FX/NDF, not the IRS basis**|

### Cross-document reconstructible CME-LCH 30Y basis series (all printed)

| Date | 30Y CME-LCH | Source |
|---|---|---|
|Jun-2014|<0.1 bp|Switch2014 p.5|
|18-May-2015|+1.90 bp|ICAP 19981 (7b p.3) & 7c p.6|
|26-May-2015|+2.50 bp|Tradition TRADTCCP (7c p.5) & 7c p.6|
|17-Jun-2015|+2.40 bp|ICAP SEF (7e p.2)|
|1-May-2017|~3.85 bp (chart)|JPM Ex.4|
|26-Jun-2017|+3.40 bp|Tradition (7a p.6)|
|Dec-2017|"recent highs in December", level not printed|Citi Blues p.4|

---

## Model-convention check I ran (report as a caveat, not a match)

Applying the JPM Ho-Lee reduction `A_cvx = σ²T₁T₂/2` (ED fixing = 2 London days before the 3rd Wednesday; T₂ = T₁ + 0.25; ACT/365; pack CA = mean of 4 contract CAs) to Citi's own 1/5/2018 table:
- **H1-Z1 (Blues):** Citi prints CA **7.13bp**, Implied Vol **105.4**. Ho-Lee back-out from 7.13bp gives **σ = 102.1bp** (ACT/365) / **100.7bp** (ACT/360). Forward: 105.4bp ⇒ CA **7.60bp** vs printed 7.13.
- **M9-H0 (Greens):** Citi prints CA **1.58bp**, Implied Vol **96.1**. Back-out gives **σ = 90.6bp**; forward at 96.1bp gives CA **1.78bp** vs printed 1.58.

**Conclusion: the JPM closed form reproduces Citi's implied-vol column to ~3% (Blues) / ~6% (Greens), but does not recover Citi's exact convention.** Citi's Ho-Lee is "calibrated to cap/floor vols" and may use full (non-reduced) Ho-Lee, a payment-date T₂, or a different daycount. **Do not build a tie-out that asserts exact equality between `σ²T₁T₂/2` and the Citi table; use it as a ±5% sanity band only.**

---

## Documents referenced but ABSENT from `C:/Users/chris/Downloads/convexityrv`

These are the origins of several published levels above and are **not in the folder**:
- **Citi, "Sell Blues convexity adjustments, hedged"** (trade entered 2/9/2017) — origin of the +$500K P&L chain, the $147mm/−$85.6mm/$20.89mm fly weights and the −18.2bp fly entry.
- **Citi, "Swearing in huge expectations"** — the original CA-widening call.
- **Citi, "US Rates Vol Lab: 2018 Vol Outlook"** — where the 0.74/−1.0 ED6/ED16 weights and the pre-2008 calibration methodology are actually derived.
- **Citi, "US Rates Vol Lab - Fair value vs seasonality"** — present in the folder as `US_Rates_Vol_Lab_Fair_value_vs_seasonality.pdf` (**not read; outside the task list**).
- **JPM, "More than meets the eye"** (J. Younger et al., 2/28/2017) — the ED CA fair-value framework the 5/3/2017 note builds on.
- **JPM US Fixed Income Strategy note, 1 May 2015** — source of the 1.5bp CME-LCH upper bound (item 50).
- **CME Advisory Chadv15-131 (13-May-2015)** — the CME USD OTC IRS valuation-curve change; a regime break for any CME-LCH series.

## Scratchpad artefacts (session-local, not primary sources)
`C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/` — `extract_all.py`, `crop.py`, `tieout.py`, `tieout2.py`, plus `01_blues.txt` … `12_oi.txt` (full text extractions with `===== PAGE N =====` markers mapping 1:1 to PDF pages).
