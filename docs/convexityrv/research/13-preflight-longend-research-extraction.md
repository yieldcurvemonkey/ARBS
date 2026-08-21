<!-- Verbatim return of a preflight investigation agent, 2026-08-20/21.
     Measured on this machine; see the report's own probe list. Kept as
     research evidence, not as a design document. -->

# Preflight scout: ultra-long-end research extraction

# EXTRACTION REPORT — Ultra-long-end / long-dated convexity RV research corpus

**Sources:** `C:/Users/chris/Downloads/convexityrv/*.pdf` (PDFs), `C:/Users/chris/Downloads/convexityrv_markdown/*.md` (Aug-14 conversions). Un-converted PDFs re-extracted with PyMuPDF 1.26.4 to `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/txt/` via `.../scratchpad/extract.py`. Page refs below are the `===== PAGE n =====` markers in those .txt files; line refs are into the .md files (after `tr -d '\r'`).

**Coverage statements about ARBS data are quoted from `C:/Users/chris/Downloads/convexityrv/HANDOVER_PREFLIGHT.md`, NOT re-measured in this session.** No network calls, no notebooks, no cache warms were run.

---

## 0. DOCUMENT IDENTITY CORRECTIONS (do before anything else)

| file | actual identity | note |
|---|---|---|
| `convexityrv_markdown/20y10y_flatteners.pdf.md` | Citi, **05-Dec-2019**, "Alert: Taking profits on delta-hedged 15y5y/20y10y flatteners" | the EXIT note |
| `convexityrv_markdown/20y10y_flatteners (1).pdf.md` | Citi, **16-Oct-2019**, "Alert: **Reweighting** delta-hedged 15y5y/20y10y flatteners" | **not a duplicate** — different note, different date, contains the beta-reweight rule |
| `Rates_Vol_Lab_Forward_steepener_and_vol_divergence (1).pdf` | byte-identical size to non-`(1)` | skipped |
| `Interest Rate Derivatives_ For cheap gamma... (1).pdf` | byte-identical size | skipped |

Date-hygiene conflicts to carry forward: the 05-Dec-2019 note says the trade was initiated **5/9/2019**; the 16-Oct-2019 note says **5/10/2019**. The 16-Oct note contains a typo — "current nationals are $149.5mn and $81.97 for 15y5y and **25y10y**" — the second leg is the **20y10y** and the figure is **$81.97mn**.

---

## 1. Citi — Alert: Taking profits on delta-hedged 15y5y/20y10y flatteners (05-Dec-2019)
`convexityrv_markdown/20y10y_flatteners.pdf.md:1-53`

**STRUCTURE.** USD **15y5y / 20y10y** forward swap curve flattener. Entered $50K DV01 at **−11.8bp**. Legs are forward-starting par swaps (15y forward, 5y tail; 20y forward, 10y tail).

**RISK WEIGHTING (verbatim + from the 16-Oct alert).** DV01-neutral at entry; re-weighted 16-Oct-2019 by **empirical beta 1.025** between 15y5y and 20y10y rates — *"scaling the DV01-neutral notional up by 1.025"*, i.e. 20y10y notional $81.97mn → **$84.0mn** (ratio 1.0248).

**DELTA-HEDGE RULE.** *"delta-hedged at each 20bp move in the 20y10y rate"* — resize the **longer** leg back to (beta-scaled) DV01-neutral each 20bp move **in the back forward rate**. The 17-Jan-2020 note adds: *"We have previously found that hedging at 20-25bp offers an attractive balance between the accuracy of hedging and transaction costs."*

**SIGNAL (risk-adjusted carry).** Figure 1 screen, **as of close 12/4/2019**, 15 curve pairs × 2 currencies. Rows: `curve, bp` / `1y ZS` / `3y ZS` / `ZS since 2000` / `1y carry, bp` / `daily BE, bp` / `1y realized vol, bp` / `BE/realized vol`. Verbatim definitions:
> *"1y carry, daily breakeven (**zero if carry is positive**), and the ratio of the daily breakeven to realized vol"*
> *"the ratio of the daily breakeven (**the daily move in rates that yields a convexity gain offsetting a negative daily carry**) to realized daily volatility"*
> *"Three most attractive curves by each metric are marked in red."*

**Column mapping (recovered, cross-verified — see §12).** 15 columns = 10y10y/{15y15y,20y5y,20y10y,20y15y,25y5y,25y10y}, 15y5y/{20y5y,20y10y,20y15y,25y5y,25y10y}, 15y10y/{25y5y,25y10y}, 20y5y/{25y5y,25y10y}.

**USD row values (close 12/4/2019), in that column order:**
- `curve,bp`: −6.77, −7.97, −11.33, −14.90, −14.99, −18.83, −9.18, −12.54, −16.11, −16.20, −20.04, −11.82, −15.65, −7.02, −10.85
- `1y ZS`: 0.55, 0.68, 0.43, 0.46, 0.13, 0.37, 0.12, −0.91, −0.37, −1.65, −0.42, −2.08, −0.54, −2.22, −0.89
- `3y ZS`: 1.38, 1.48, 1.28, 1.28, 1.07, 1.20, 0.98, 0.70, 0.76, 0.52, 0.70, 0.38, 0.58, 0.02, 0.13
- `ZS since 2000`: 1.08, 1.03, 0.97, 0.95, 0.80, 0.80, 0.71, 0.64, 0.62, 0.49, 0.50, 0.27, 0.25, −0.33, −0.29
- `1y carry,bp`: −3.19, −4.16, −3.95, −3.95, −3.73, −3.82, −2.30, −2.09, −2.09, −1.87, −1.96, −0.77, −0.86, **+0.43, +0.34**
- `daily BE,bp`: 4.14, 4.62, 3.93, 3.54, 3.40, 3.16, 4.23, 3.33, 2.90, 2.70, 2.49, 1.98, 1.84, 0.00, 0.00
- `1y realized vol,bp`: 4.22, 4.23, 4.16, 4.17, 4.08, 4.13, 4.23, 4.16, 4.17, 4.08, 4.13, 4.08, 4.13, 4.08, 4.13
- `BE/realized vol`: 0.98, 1.09, 0.95, 0.85, 0.83, 0.77, 1.00, 0.80, 0.70, 0.66, 0.60, 0.49, 0.45, 0.00, 0.00

**GBP row values (same columns, close 12/4/2019):** curve −7.25, −8.86, −10.12, −11.60, −11.43, −13.05, −7.01, −8.27, −9.74, −9.57, −11.19, −6.14, −7.76, −2.56, −4.18; ZS2000 1.27, 1.20, 1.36, 1.53, 1.51, 1.69, 1.34, 1.61, 1.85, 1.78, 2.00, 1.86, 2.05, 1.53, 1.54; carry −1.93, −2.45, −2.02, −1.92, −1.56, −1.64, −0.68, −0.24, −0.14, +0.21, +0.14, **+0.54**, +0.47, +0.89, +0.82; BE 3.21, 3.57, 2.82, 2.47, 2.22, 2.07, 2.31, 1.13, 0.76, 0, 0, 0, 0, 0, 0; realized vol 4.29, 4.26, 4.30, 4.21, 4.34, 4.18, 4.26, 4.30, 4.21, 4.34, 4.18, 4.34, 4.18, 4.34, 4.18; BE/vol 0.75, 0.84, 0.66, 0.59, 0.51, 0.50, 0.54, 0.26, 0.18, 0, 0, 0, 0, 0, 0.

**EXIT RULE (as executed).** Carry deteriorated to **−2bp/yr** and **BE/realized vol rose to 0.8** ⇒ close. *"we prefer closing this trade at this time."*

**P&L.** Curve little changed (−12.5bp mid, 2pm 12/5/2019 vs −11.8 entry); MTM **+$187K at mid**; booked **+$155K net transaction costs** ⇒ implied round-trip cost ≈ **$32K on $50K DV01** (all resizes included).

**COSTS.** Only implicitly: $187K gross → $155K net.

**DRIVER / PROXY.** *"insurance flows"* cause the curve's directionality with rates (steepens in rallies, flattens in sell-offs). No observable series named here.

---

## 2. Citi — Alert: Reweighting delta-hedged 15y5y/20y10y flatteners (16-Oct-2019)
`convexityrv_markdown/20y10y_flatteners (1).pdf.md:1-33`

**STRUCTURE / SIZING.** Notionals at reweight: **$149.5mn 15y5y** vs **$81.97mn 20y10y** (DV01-neutral) → 20y10y raised to **$84.0mn**.
**RISK WEIGHTING (verbatim).** *"we prefer to reweight it using the empirical beta of 1.025 between 15y5y and 20y10y rates … and will continue delta-hedging this leg at each 20bp with the same beta (i.e. scaling the DV01-neutral notional up by 1.025)."*
**MTM at reweight:** **+$105K** (from 5/10/2019 entry), *"even though the 15y5y/20y10y curve has steepened by about 2bp since initiation"* — i.e. all P&L from realized vol via the resizes.
**DRIVER.** *"notable directionality with rates over the last few months (steepening in rallies and flattening in selloffs), which likely reflects insurance flows."*
**Implementation note:** notional ratio 149.5/81.97 = **1.824** for the DV01-neutral 15y5y:20y10y pair on 16-Oct-2019 — usable as a DV01-ratio sanity check on a rebuilt USD SOFR curve for that date.

---

## 3. Citi — Alert: Taking profits on GBP 15y10y/25y10y flatteners (26-Mar-2020)
`convexityrv_markdown/25y10y_flatteners.pdf.md:1-20`

**STRUCTURE.** GBP **15y10y / 25y10y** flattener, **50K DV01**, entered January 2020 at −11.2bp.
**HEDGE.** *"delta-hedged at each 25bp move in the 25y10y rate"* (back leg again).
**EXIT.** Closed 3/26/2020 on view (*"risk of re-steepening on supply"* after aggressive QE flattening), not on the metric.
**P&L DECOMPOSITION (the single most valuable tie-out in this note).** *"a profit of GBP 445K, net transaction costs (about **115K from the curve move** and **330K from convexity**; pricing as of 2pm on 3/26/2020)."* ⇒ **74% of P&L from convexity, 26% from the curve** on a 2.3-month hold spanning COVID.
**MOTIVATION (verbatim).** *"We were motivated by the **steepness of the curve, positive convexity, and attractive carry**."* — three-part entry condition.

---

## 4. JPM — Valuing convexity in the long end of the yield curve: A global perspective (09-Feb-2018)
`convexityrv_markdown/Valuing convexity in the long end of the yield curve A global perspective.pdf.md`

**FRAMEWORK (verbatim, l.~150-175).**
`ΔP = −PVBP·ΔY + 0.5·Cvx·(ΔY)²`
`E[return] = (Y−F)·T/PVBP  +  slide  +  0.5·σ²·Cvx/PVBP`  ⇒ **Expected return = carry + slide + value of convexity**.

**RISK-ADJUSTED CARRY (RAC) — the user's singled-out metric.** Exhibit 2, 30Y+ French OATs (columns: `Carry | Slide | Convexity | Expected return | 3M realised vol | RAC`):

| OAT | Carry | Slide | Convexity | Exp. return | 3M realised vol | RAC |
|---|---:|---:|---:|---:|---:|---:|
| 25-May-48 | 10.6 | 2.0 | 3.3 | 15.9 | 3.0 | 0.33 |
| 25-Apr-55 | 10.7 | 1.0 | 3.6 | 15.4 | 3.0 | 0.32 |
| 25-Apr-60 | 9.9 | 0.2 | 4.1 | 14.2 | 3.0 | 0.30 |
| 25-May-66 | 7.9 | −1.0 | 4.9 | 11.8 | 3.0 | 0.25 |

**Recovered exact formula (arithmetic-verified 4/4, see §12): `RAC = E[return over 3M, bp of yield] / (3M-realised DAILY bp vol × √252)`.** Units: bp of yield in numerator, annualised bp vol in denominator ⇒ unitless. Exhibit 12's caption reads *"Annualised 3M expected return divided by annualised expected volatility"* — **the caption is misleading; the verified arithmetic uses the raw (un-annualised) 3M return.** Building it from the caption gives a number 4× too large.

**SECOND SIGNAL — the option-comparison framework.** *"we extract an implied distribution from ATMF and OTM pricing for each expiry. This is then multiplied with the payoff profile of an **aged flattener at fixed coupon** … we use **1Yx30Y swaptions for a 1-year horizon** and assume parallel shifts."* Alternative: solve for **breakeven vol** — *"a normal distribution of terminal rate shifts centered on zero with standard deviation fit to produce a probability-weighted payoff of zero"*. Reading: **expected payoff > 0 ⇒ curve is the cheaper gamma; swap-implied vol < 1Yx30Y ATMF ⇒ same conclusion.**

**PUBLISHED HIT RATES (tie-out).** *"a favorable hit rate, especially for long-dated forward curve structures (**56% for 30s/50s, and 86% for 25Y/20Yx5Y**)"* vs 1Yx30Y ATMF straddles.

**STRUCTURE RANKING (Exhibit 8, data 2/5/18, 1Y expected payoff vs 1Y carry+roll, bp yield).** Best → worst: **20/40x10** (highest payoff ~15bp, positive roll), 20/30x10, 15/35x15, 2/25x5, 30/50, 5/15x5, 10/30, 20/30, 10/20. *"We continue to see the most value in forward curve pairs, in particular **20Y/40Yx10Y**, which often come with not only high expected convexity value, but also **positive ex-ante roll**."* Cross-market (Exhibit 27): *"for USD and GBP, **20Y/40Yx10Y** was the clear winner, and in EUR this structure was neck-and-neck with **15Y/35Yx15Y**."*

**EUR 1Y value of convexity, bp of yield (Exhibit 15, since Euro inception):**

| | 10Y | 20Y | 30Y | 40Y | 50Y |
|---|---:|---:|---:|---:|---:|
| Current | 1.2 | 2.3 | 3.3 | 3.9 | 4.5 |
| High | 7.6 | 17.9 | 31.4 | 39.2 | 45.9 |
| Low | 1.1 | 1.8 | 2.3 | 2.8 | 3.1 |
| Average | 2.5 | 4.4 | 6.1 | 7.4 | 8.6 |
| SD | 1.0 | 2.2 | 3.8 | 4.8 | 5.7 |
| Z-score | −1.3 | −0.9 | −0.7 | −0.8 | −0.7 |
| %ile | 1% | 3% | 15% | 13% | 16% |

**GBP 1Y value of convexity (Exhibit 22, since Jan-99):** Current 2.0/3.5/4.9/6.1/7.3; High 6.6/10.9/14.6/18.1/20.9; Low 1.3/2.0/2.4/2.9/3.4; Average 3.1/4.9/6.2/7.6/8.8; SD 1.1/1.8/2.5/3.1/3.7; Z −1.0/−0.8/−0.5/−0.5/−0.4; %ile 21/29/39/40/40 (10Y…50Y).

**Other calibrated relations (tie-outs).**
- Gilt 3H68 1Y value of convexity vs expected daily yield vol: **y = 0.49x² − 0.6x + 1.05, R² = 99%** (past 2Y) — confirms the σ² scaling.
- Gilt-vs-swap 50Y convexity: **y = 1.05x − 2.49, R² = 46%** (since Jan-16).
- 30s/50s par gilt fair value: **`30s/50s = 0.6·(1Y value of convexity) + 5.3·(50Y par gilt yield) − 31`, R² 56%, std err 4bp** ⇒ curve *"5bp too flat"*.
- 30s/50s inversion stats (bp): Par Gilt past-10Y max 10 / min −62 / avg −11; Swap max 16 / min −36 / avg −6. Past-5Y: gilt 6/−26/−11; swap 10/−17/−7.
- *"a doubling of volatility **quadruples** the value of convexity"* (Exhibit 17).
- *"an almost **20% decline in 30Y vol**"* required to equate 30Y and 50Y EUR expected returns; breakeven vol ratios vs 50Y: 30Y 89% (vs current 107%), 35Y 101/106%, 40Y 100/106%, 45Y 100/105%.

**DRIVER / PROXY.** UK: pension/LDI/insurance hedging demand; £131bn of 30Y+ gilts = 12% of market, 7 bonds, wtd mod duration 25.3y. EUR: ECB QE purchases capped at 31Y maturity (segmentation) + 30Y+ EGB universe only €68.1bn (2.5% of conventional outstanding), itemised issuer-by-issuer in Exhibit 9 — **directly observable proxies**.

---

## 5. JPM — Euro Swaps Relative Value: RV on the ultra-long end of the swap curve (11-Feb-2019)
`scratchpad/txt/Euro_Swaps_Relative_value_RV_on_the_ultra_long_end_of_the_swap_curve_Mon_Feb_11_.txt` PAGES 1-4

**STRUCTURE 1 (headline).** Receive body of a **level- and curve-neutral 5Yx5Y / 15Yx5Y / 30Yx5Y** fly.
**RISK WEIGHTING (verbatim).** *"**−13.3% / +100% / −77.8% risk weights**"*; footnote definition *"**15Yx5Y − 0.133·5Yx5Y − 0.778·30Yx5Y**"*. Method: *"1Y PCA of various forward points and structuring the trade such that it is **neutral to the first (level) and second (curve) PCA factors**"*; *"These weights are very similar to that obtained by constructing a **regression based curve- and level-neutral fly**."*
**CARRY.** *"The overall **3M carry** on this trade is around **−1bp**"* (Exhibit 8 table says **−1.4**).
**SIGNAL.** Dislocation = current − 1Y avg; Z = dislocation / SD (all on the PCA-weighted fly). *"currently 4bp away from its 1Y average … close to the extremes seen over the past year and the weighted fly has typically mean-reverted from these levels."*
**Orthogonality check (Exhibit 6, past 1Y):** PCA-weighted fly vs 10Y β −1%/R² 0%; vs Fronts/golds β −1%/R² 0%; vs 10s/30s β 17%/R² 10%. Same for the raw 50:50 fly: −26%/63%, −18%/67%, **90%/76%**.
**STRUCTURE 2.** *"receiving the body of the 5Y forward fly versus a **beta-weighted amount of paying the body in the 10Y forward fly (100%/140%)**"* (5Yx5Y/15Yx5Y/30Yx5Y vs 10Y/10Yx10Y/20Yx10Y). *"The current RV is around 4bp."* Regression: **y = 1.40x − 53.59, R² = 72%** (since 1-Jan-2018).
**Related regressions.** 50:50 fly vs 10s/30s EUR swap curve, past 1Y: **y = 0.91x − 4.85, R² = 78%**. *"an outright receiving the body of this fly is akin to having a 10s/30s flattener but with better relative value."*

**Exhibit 8 — full screen (all arithmetic self-consistent, §12):**

*Weighted steepeners (neutral to PC1 only):*

| Receive | Pay | Weights | 3M carry | Current | 1Y avg | SD | Disloc. | Z | β to 10Y | R² |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 15Yx5Y | 30Yx5Y | 100/−95% | −0.7 | −62 | −58 | 2 | −3.6 | −1.9 | −4% | 3% |
| 15Yx5Y | 30Yx10Y | 98/−100% | −0.7 | −54 | −49 | 2 | −4.8 | −2.2 | −6% | 7% |
| 20Yx5Y | 30Yx10Y | 92/−100% | −0.9 | −19 | −14 | 2 | −5.9 | −3.3 | −2% | 1% |
| 10Yx10Y | 30Yx10Y | 97/−100% | +0.4 | −55 | −51 | 3 | −3.7 | −1.4 | −11% | 15% |

*Weighted flies (neutral to PC1 and PC2):*

| Wing | Body | Wing | Weights | 3M carry | Current | 1Y avg | SD | Disloc. | Z | β | R² |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5Yx5Y | 15Yx5Y | 30Yx5Y | −13/100/−78% | −1.4 | −65.9 | −62.4 | 1.7 | −3.5 | −2.1 | 1% | 0% |
| 5Yx5Y | 15Yx5Y | 30Yx10Y | −19/100/−76% | −1.8 | −63.2 | −58.9 | 1.8 | −4.4 | −2.5 | 1% | 0% |
| 5Yx5Y | 20Yx5Y | 30Yx10Y | −11/100/−93% | −1.6 | −25.6 | −19.5 | 1.7 | −6.0 | −3.5 | 2% | 1% |
| 5Yx5Y | 10Yx10Y | 30Yx10Y | −32/100/−59% | −1.3 | −69.8 | −66.8 | 1.5 | −3.0 | −1.9 | 1% | 0% |
| 5Yx5Y | 20Yx10Y | 40Yx10Y | −41/100/−87% | −2.9 | +4.4 | +13.5 | 3.3 | −9.0 | −2.7 | 4% | 1% |

**"RV opportunity index" (reusable).** *"the sum of squared 6M rolling Z-score of various curve- and level-neutral swap butterflies"*, 10D MA. Constituents named: **2s/5s/10s, 2s/10s/30s, 5s/7s/10s, 3s/7s/15s, 10s/20s/30s**.
**DRIVER / PROXY.** *"issuance based receiving is mostly active in the 10Y sector whereas **pension fund receiving** … focused at the ultra-long end (for example 30Y+). This has cheapened 20Y rates."* Also: *"these ultra-long end flies tend to **richen during hiking cycles**"* (charted vs ECB depo rate, 20Y history) — the depo/policy path is the observable proxy.

---

## 6. Citi — Rates Vol Lab: Forward steepener and vol divergence (12-Jun-2023)
`convexityrv_markdown/Rates_Vol_Lab_Forward_steepener_and_vol_divergence.pdf.md`

**HEADLINE STRUCTURE — the sign-flipped twin of the flattener screen.** Long-dated forward **steepener** as a **positive-carry / short-vol** trade. *"Because long-dated forward steepeners have net negative convexity, we can back out implied yield breakevens from the carry and compare them to the recent realized yield moves. **Having a breakeven/realized vol ratio allows us to compare the positive carry of various long-dated forward steepeners in a standardized fashion**"* (l.156-160).

**Figure 5 screen, close of 06/08/23, 10 columns** — 10y10y/{15y15y,20y5y,20y10y,20y15y,25y5y,25y10y}, 15y5y/{20y5y,20y10y,20y15y,25y10y} (l.168-180):

| row | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| curve, bp | −51.5 | −62.4 | −76.1 | −89.4 | −91.5 | −105.6 | −50.9 | −64.5 | −77.9 | −94.1 |
| 3y ZS | −0.91 | −0.91 | −0.96 | −1.00 | −1.01 | −1.04 | −0.98 | −1.03 | −1.06 | −1.11 |
| ZS since 2000 | −2.07 | −1.47 | −1.96 | −2.34 | −2.28 | −2.56 | −1.30 | −1.87 | −2.31 | −2.58 |
| 1y carry, bp | 6.89 | 10.31 | 8.31 | 7.71 | 5.95 | 6.04 | 5.93 | 3.93 | 3.33 | 1.66 |
| daily BE, bp | 6.18 | 7.22 | 5.71 | 4.99 | 4.29 | 3.97 | 6.77 | 4.59 | 3.71 | 2.29 |
| 1y realized vol, bp | 5.30 | 5.24 | 5.11 | 4.85 | 4.98 | 4.66 | 5.24 | 5.11 | 4.85 | 4.66 |
| **BE/realized vol** | **1.17** | **1.38** | **1.12** | **1.03** | 0.86 | 0.85 | **1.29** | 0.90 | 0.77 | 0.49 |

**ENTRY RULE (steepener, verbatim).** *"the **10y10y/15y15y and 20y5y-10y10y** steepeners lie on the **efficient frontier** of this carry vs entry trade-off and have **breakeven vs realized vol ratios that are meaningfully above 1**. Between the two, 20y5y-10y10y looks slightly more attractive due to a more favorable carry vs entry trade-off **when using a more recent 3y Z-score**. 25y10y-10y10y and 20y15y-10y10y steepeners also lie on the efficient frontier but their **breakeven vs realized vol ratios are not high enough**."* Efficient frontier axes: **BE/Realized Vol (y) vs Curve Level Z-score since 2000 (x)** (Figure 6).

**SECOND STRUCTURE.** *"shorting Blues convexity adjustment via **long SOFR futures against pay in swaps** as a short vol proxy"*; *"the Blues convexity adjustment could continue to compress towards our model fair value, which is currently about **5bps lower**"* (12-Jun-2023).

**Figure 58 — SOFR pack CA screen, close 6/9/23, 13 rows (M4-H5 … M7-H8).** Definition (verbatim): *"Convexity adjustments for 1y SOFR packs are computed as the spread between the pack's rate (**the average of 4 SOFR rates in the pack**) and **matched-maturity forward 1y CME swap rate**. The model … is the **Ho-Lee model calibrated to cap/floor vols**. Implied vol is calculated by matching the model to the observed convexity adjustment. Realized vol is **3m realized vol of the corresponding pack**."* (This is the 13-row screen already used as a tie-out in `docs/convexityrv/`.) Columns: Cvx Adj / 1W chg / 3m ZS / 1Y ZS / Model / Vs Model / 3m ZS / 1Y ZS / 3m Roll (short cvx) / Implied Vol / Realized Vol / Implied-Realized / Cap-vol Impl/Rlzd.

**THIRD STRUCTURE — forward-vol efficient frontier (Figure 22, close 6/9/23).** *"all executable forward vol trades, expressed using **gamma-neutral calendar spreads and triangles**, and report 20 trades on the efficient frontier based on **ex-ante Sharpe (measured by the vol-adjusted roll)** and **value (measured by 1y-zscore)** … We analyze both calendar spreads (**underlying forwards with matching mid-points**) and triangles … Forward vols are computed using the **standard triangular approximation** from spot vols and using **6m realized correlations as a proxy for implied correlations**."*
Top-of-frontier rows (short expiry | long expiry | fwd vol | γ-neutral wghts | σ_short | σ_long | σ_fwd | 3m roll nv | 1y Sharpe | 1y ZS | 3m ZS):
- `3m3y2y | 9m7y | 3m6m7y | 254.2/100 | 142.3 | 114.5 | 103.9 | 14.08 | 0.69 | −0.7 | −2.0`
- `1y2y1y | 3y1y | 1y2y1y | 69.8/100 | 145.5 | 120.7 | 106.1 | 7.02 | 0.54 | −1.0 | −0.5`
- `6m3y2y | 3y3y | 6m30m3y | 76.9/100 | 139.3 | 111.6 | 105.9 | 5.16 | 0.51 | −1.0 | −1.9`
- `6m25y | 1y25y | 6m6m25y | 72.0/100 | 88.1 | 85.5 | 83.4 | 2.34 | 0.29 | −1.2 | −1.7`
- `6m30y | 1y30y | 6m6m30y | 71.7/100 | 85.3 | 83.2 | 81.5 | 1.90 | 0.24 | −1.2 | −1.7`
(20 rows total in the file.)

**FOURTH — CMS curve options (Figures 54-57, close 6/9/23).** ATM curve vols (normals) 1m/3m/6m/1y/2y/3y/5y × 2s5s/2s10s/2s30s/5s10s/5s30s/10s30s; rich/cheap from a **PCA on curve vols using two PCs and 3y of data**; implied/1m and implied/3m realized ratios. E.g. 1m 5s30s vol 92.6 (z −1.1), implied/1m RV 1.23 (z 0.5), implied/3m RV 0.91 (z −0.8). *"Implied curve correlations remain at their multi-year lows for 5s30s. This reflects the persistent demand for intermediate **curve caps**."*

**FIFTH — conditional curves (Figure 61, "bear trades"), full grid 3m/6m/1y/2y/3y expiries × 12 curve pairs.** Columns: notionals, spot crv, fwd crv, 3m ZS, **costless strike curve**, 1m/3m chg, hist ZS, **imp beta / rlzd beta / rlzd−imp**, then bear-steepener and bear-flattener **crv pick-up / vol pick-up / total pick-up / 3m roll**. Verbatim: *"The vol pick-up is the spread between forward and strike curves for steepeners, and the spread between strike and forward curves for flatteners. Total pick-up is the sum of curve and vol pick-ups. 3m carry is computed assuming unchanged curve and vol cube."*

**DRIVER / PROXY.** Callable/Formosa vega supply, quantified monthly (Figures 31-35). Figure 35 recent supply table, $bn initial notional and $mn normal vega: Jun-23 MTD gross 0.04 (vega 0.1); May-23 0.46 (0.6); Jun-22 0.28 (0.3); 2023 YTD 2.44 (2.6); 2022 YTD 14.30 (36.0); 2022 full-year 16.73 (39.3). Also Figure 4: *"2y30y Vol"* vs *"20y5y−10y10y Rate Spread"* — the inverse vol/forward-curve relationship, an **observable, buildable pair**.

---

## 7. Citi — Rates Vol Lab: Liquidity, vega, and convexity (30-Mar-2020)
`convexityrv_markdown/Rates_Vol_Lab_Liquidity_vega_and_convexity.pdf.md`

**STRUCTURE.** *"the **15y5y/20y10y USD curve** has steepened to the upper bound of the historical range … The 15y5y/20y10y flatteners (**−5.21 bp as of 3pm on 3/26/2020**) have a **slightly positive carry and positive convexity** … In other words, the trade is effectively a **free convexity buy**. We are adding this trade to our **watch list but don't initiate yet given the lack of liquidity and wide bid/offer spreads."* (l.231-252) — an explicit **liquidity veto** on an otherwise-triggering signal.

**COSTS (measured, verbatim).** *"the bid/offer remains wide (**mid-to-bid an offer is still about 0.6bp in 10y swaps**), which makes it costly to delta-hedge frequently"* (l.93).

**Figure 9 screen, as of 3pm 3/26/2020, same 15-column layout, USD / EUR / GBP.** USD: curve −5.07, −6.70, −6.86, −11.74, −7.03, −14.38, −5.04, **−5.21**, −10.09, −5.38, −12.73, −2.90, −10.24, −0.34, −7.68; 1y ZS 1.07…4.60; 3y ZS 1.76…3.59; ZS2000 1.20…−0.09; **1y carry** −0.28, −0.71, −0.24, −1.03, **+0.24**, −1.20, −0.36, **+0.11**, −0.68, **+0.58**, −0.85, **+0.76**, −0.68, **+0.94**, −0.49; daily BE 1.21, 1.92, 0.98, 1.81, 0.00, 1.77, 1.68, **0.00**, 1.65, 0.00, 1.64, 0.00, 1.63, 0.00, 1.61; **1y realized vol 6.47, 6.46, 6.40, 6.30, 6.33, 6.21, …** (COVID: vs 4.2 in January); BE/vol 0.19, 0.30, 0.15, 0.29, 0.00, 0.29, 0.26, **0.00**, 0.26, 0.00, 0.26, 0.00, 0.26, 0.00, 0.26.
EUR and GBP blocks present in full at l.267-287.

**DRIVER / PROXY.** *"most likely due to **receiving pressures from variable annuity portfolios** in the stock market selloff … **variable annuity hedging is typically concentrated in the 20y sector of the curve**."* Proxy: equity drawdown → 20y sector richness. Also March-2020 Formosa/bank callable supply **≈$5bn** (Figure 7).

---

## 8. Citi — Rates Vol Lab: In search of cheap vol (17-Jan-2020)
`convexityrv_markdown/Rates_Vol_Lab_In_search_of_cheap_vol.pdf.md`

**STRUCTURE (initiation).** *"We initiate **50K DV01 of GBP 15y10y/25y10y flatteners at −11.2bp** (as of 12pm on 1/17/2020). We will be delta-hedging the trade by **adjusting the longer leg of the trade for DV01 neutral at each 25bp move in the 25y10y rate**. We have previously found that **hedging at 20-25bp offers an attractive balance between the accuracy of hedging and transaction costs**."* (l.179-186)
**ENTRY CONDITION.** *"the 15y10y/25y10y flatteners also **carry positively by about 0.5bp over 1y**. As a result, the flatteners offer an **effectively free convexity buy**."*
**SIGNAL (verbatim, l.206-214).** *"We evaluate steepeners by simple z-scores as well as **the ratio of the daily breakeven (the move in rates that yields a convexity gain offsetting the negative daily roll) to realized daily vol of the underlying rates (a smaller ratio indicates the cheapness of the embedded convexity and therefore a more attractive trade)**."*
**Figure 11 — the full 5-currency screen, close of 1/16/2020, 15 columns × {USD, EUR, GBP, CAD, JPY}** (l.222-276). Key column 13 = 15y10y/25y10y: GBP curve −10.37, 1y ZS −0.01, 3y ZS 1.15, **ZS2000 1.84**, **carry +0.52**, BE 0.00, realized vol 4.24, **BE/vol 0.00**. USD col 8 (15y5y/20y10y): −13.65 / carry −2.20 / BE 3.41 / vol 4.27 / **0.80**. Full USD/EUR/GBP/CAD/JPY numbers are transcribed in the file at those lines.
**RELATED VOL STRUCTURE.** *"We continue to like our **10y20y/5y30y straddle switch** as way to buy the **5y fwd 5y20y** volatility (10y20y and 5y30y are at **54.6 and 56.6 nv** as of 1pm on 1/17/2020)"* (l.72-76).
**DRIVER / PROXY.** *"20s remain rich on the curve … likely because of **receiving flows from ALM investors**"* — charted as the **10s20s30s fly** (Figure 10), an observable curve proxy for the ALM bid. Formosa: *"$5.3bn already issued [Jan-2020] … about **$16mn normal vega already has been swapped this month, the highest monthly supply since January 2018**"*; *"issuance shifting toward **40NC5** structures"*.

---

## 9. Citi — US Rates Vol Lab: Gamma and Vega RV (14-Jan-2019)
`convexityrv_markdown/US_Rates_Vol_Lab_Gamma_and_Vega_RV.pdf.md`

**STRUCTURE — 1x2x1 vol tenor fly, fully specified (l.190-200):**
- **Sell $230mn 3y2y ATMF straddles**
- **Buy $100mn 3y10y ATMF straddles**
- **Sell $21mn 3y30y ATMF straddles**
- *"constructed **vega-neutral**"*; **take-in $240K spot premium** (pricing 9am 1/11/19)
- **Carry: +0.75 normals (+$43K) over 1 year; +6 normals (+$341K) over 2 years**

**SIGNAL.** (i) Z-score of the 1×2×1 vol fly **from 1999 to present** — Figure 5 grid (expiry × fly), 3y row: 2y/5y/10y 0.3 (−0.6); 2y/5y/30y 7.2 (−1.2); **2y/10y/30y −4.0 (−1.9)**; 5y/10y/30y 1.3 (−1.4). (ii) Fair value = *"regression of the fly to the **level and slope of the curve**"*, sample 2003-present **excluding the ZLB era 6/1/2008–1/1/2016**; fair value **+5 normals**. (iii) Surface PCA rich/cheap: 3 PCs of the vol surface calibrated **Jan-2004→Jan-2008 spliced with Jan-2017→present**; 3y2y **+5.7 normals (3.6σ) rich**, 3y10y **−1.9 normals (2.2σ) cheap**.

**DELTA-HEDGE RULE (gamma leg).** *"sold $100mn 3m10y straddles **delta-hedged at 9am EST with a 15% delta threshold**"*, later halved to $50mn at 59 normals (3pm 1/11/2019). *"We chose to hedge at 9am given that this time snapshot has delivered one of the **lowest realized volatilities** over the last 3m, 6m and 1y."* Scale-down rule: **50% off on diminished valuation** (fair value gap fell to ~3 normals).

**Figure 57 — ED pack CA screen, close 1/11/19, 17 rows H9-Z9 … H3-Z3** (l.831-848); same column definitions as the 2023 SOFR screen. Selected: H9-Z9 CA 0.06 / model 0.00 / vs model 0.06 / 3m roll 0.06 / implied 53.3 / realized 61.0; H3-Z3 CA 7.44 / model 0.20*(see caveat) / vs model 1.28 / implied 84.4 / realized 65.5. *"For each valuation metric, we mark **three best short convexity trades** in bold."*

**DRIVER / PROXY.** *"3y30y remains somewhat bid by **less Formosa issuance**"*; *"less demand for vega from **mortgage convexity hedgers** today, compared to pre-crisis"* — both named, neither given a series here.

---

## 10. Citi — Rates Vol Lab: Left-side vols' outperformance (22-Jun-2021)
`scratchpad/txt/Rates_Vol_Lab_Left_side_vols_outperformance.txt`

**STRUCTURE — the most completely specified CA trade in the corpus (PAGE 8, l.514-533):**
> *"we recommended selling the convexity adjustments by **buying 1000 of the EDM4-H5 Blue pack** and **paying $1.01bn CME cleared forward starting (6/17/2024-6/16/2025) swap at 7.9bp in rate spread** (priced as of **noon 6/11/2021, $100K DV01**). The rate spread has **tightened to 5.9bp** since then … The trade has **1.2bps running of positive carry over three months**, and we are **targeting 4bps of tightening** in the convexity adjustment and would **stop out on 3bps of widening**."*

**CLEARING CHOICE (verbatim).** *"The analysis is based on the **CME FRA/swap curve, which we favor over LCH-cleared swaps because clearing on CME is more capital-efficient due to netting of futures and swap positions for margin calculations**."*

**SELECTION RULE between Blues and Golds.** *"While the **Golds look slightly more favorable in terms of the dislocation relative to the model levels**, the **Blues have a higher 3m roll and a higher vol computed from its market-observed convexity adjustment**. The computed **market observed/realized vol ratio for Blues is currently at the upper end of its multi-year range**."*

**DRIVER / OBSERVABLE PROXY (the one the handover asked for).** Figure 12 plots **"Asset Managers + Leveraged Funds, Net % of OI (inverted)"** against **"Blues Convexity Adj − Model"** (Jan-19 → Jun-21) — i.e. **CFTC positioning as % of open interest** is the named proxy for CA richness. Risk statement: *"The primary risk to the trade is a **further build-up of short-duration positions that are more concentrated in EDs than in OTC derivatives**."*

**Forward-vol frontier (Figure 38, close 6/21/21).** Same construction as §6. Named tie-out: *"the **6m30y versus 1y30y swaption switch that is a proxy of the 6m6m30y forward vol** currently has a **1.07 Sharpe ratio and −1.4 3m z-score**."*

**Vol carry (Figure 6).** *"the **six-month vol carry for fixed-strike straddles** … short tails have negative vol carry and **30y tails have positive vol carry** … **1y5y has positive vol carry that nearly offsets the carry on the 1y30y**."* — the basis for tail-switch sizing.

**EXTRACTION CAVEAT.** Figure 13 (17-row ED CA table, levels as of 6/21/2021 close) extracted **column-scrambled** (one value per line, headers detached). Rows partially recovered (U1-M2 … H4-Z4) but **not reliable as a tie-out**; do not use. Use the Jan-2019 and Jun-2023 screens instead.

---

## 11. Citi — US Rates Vol Lab: Fair value vs seasonality (01-May-2017)
`scratchpad/txt/US_Rates_Vol_Lab_Fair_value_vs_seasonality.txt` PAGES 1-3

**No ultra-long structure.** Extractable content:
- **Vol fair value model.** *"We regress each ATM point on **3 principal components of the swap curve** … calibrated to the **pre-2008 regime** (**1996-2008 spliced with 2017 data** to exclude the near-zero rate policy regime)."* **Current fair value for 3m10y ≈ 72bp vs 3m10y at 70 normals** (close 4/28/17) ⇒ about fair. Full rich/cheap grid (expiry 1m…10y × tail 1y…30y) with z-scores at PAGE 2.
- **Seasonality signal.** *"Gamma outperformed in **four out of the last five May months (and in seven out of the last ten)**."* Named negative modifier: government shutdown (gamma cheapened in the Sep-Oct 2013 shutdown).
- **Conditional fly/curve carry definition** (l.5255): *"3m carry is computed **assuming unchanged curve and vol cube** and is expressed in **bp of running yield**."*
- **DRIVER.** April callable supply **$910mn** long-dated; expects May pick-up but below May-2016.

---

## 12. Citi — US Rates Trade Recommendation: Receive Belly of 1-Year Forward 5s10s30s Fly (20-Dec-2010)
`convexityrv_markdown/US_Rates_Trade_Recommendation_Receive_Belly_of_1_Year_Forward_5s10s30s_Fly.pdf.md`

**STRUCTURE (Figure 6, complete trade ticket):**

| Side | Notional $mm | Start | Tenor | Strike | Delta | Gamma |
|---|---:|---|---|---|---:|---:|
| Pay | −180.0 | 1y | 5y | 2.971% (ATMF) | 84,827 | −64 |
| Receive | 200.0 | 1y | 10y | 3.908% (ATMF) | −171,139 | 206 |
| Pay | −50.0 | 1y | 30y | 4.344% (ATMF) | 86,510 | −230 |
| **Total** | | | | | **198** | **−88** |

**RISK WEIGHTING.** DV01-neutral overall (net delta 198 vs ~171k per leg = 0.12%); wings essentially **50:50 by DV01** (84,827 vs 86,510 = 49.5%/50.5%).
**TARGET / STOP (verbatim).** *"We target **20bp** (computed as **the 28bp difference between the current 1-year forward and predicted values minus 8bp of convexity costs**) with a **10bp stop-loss**."*
**CARRY & CONVEXITY COST.** Fly: *"negative carry of **5bp/a** … incurs only **8bp/a of convexity costs**"*. Comparison 1y-fwd 10s30s steepener: *"**27bp/a of positive carry** … incurs **convexity costs of 11bp/a assuming realized volatility of 120bp/a**"*, rejected as *"the margin on the trade too thin"*.
**SIGNAL (fair-value model).** Predicted 1y-fwd curve/curvature = probability-weighted average of historical regime means. Regime means (bp): On Hold after Cut / Start of Hiking / 6M into Hiking = 2s-5s 129/106/69; 5s-10s 93/74/55; 10s-30s 69/63/49; 2s-5s-10s 36/32/14; **5s-10s-30s 24/10/6**. Market-implied hike-start probabilities: 30% 2011, 42% 2012, 28% 2013. Worked: *"**9%·6 + 21%·10 + 70%·24 = 19bp**"*. Current 1y-fwd 5s10s30s = **48bp** (spot 53), predicted **19bp**.
**Extra valuation anchor.** *"Current levels of the 1-year forward fly at 48bp **exceed the 98th percentile of historical fly values even for when the Fed is on hold after cut**."*

---

## 13. JPM — RV Trade Note: Pay belly of the 1Yx1Y/5Yx5Y/10Yx10Y EUR swap fly (23-Jan-2020)
`scratchpad/txt/RV_Trade_Note_Pay_belly_of_the_1Yx1Y_5Yx5Y_10Yx10Y_EUR_swap_fly_on_valuations_an.txt` PAGES 1-3

**STRUCTURE (verbatim, PAGE 3):**
> *"**Pay €100mn 5Yx5Y swaps (100% risk, start 27 Jan 2025, end 27 Jan 2030)** versus receiving **€251.8mn 1Yx1Y swaps (50% risk, start 27 Jan 2021, end 27 Jan 2022)** and **€26.2mn 10Yx10Y swaps (50% risk, start 27 Jan 2030, end 27 Jan 2040)** to enter into a **50:50 swap fly at 11.6bp (defined as 2·5Yx5Y − 1Yx1Y − 10Yx10Y)**"*

**RISK WEIGHTING.** 50:50 **DV01** weighting (each wing carries 50% of the belly's risk) — the notional ratios 251.8 : 100 : 26.2 are the DV01-inverse of the 1y/5y/10y tails.
**CARRY.** **−2bp over 3M**. Alternative *"paying 10Y in 2s/10s/30s fly … marginally lower carry (**−1.5bp over 3M**)"*.
**SIGNALS (three, all published with coefficients):**
1. **Convex valuation.** Fly regressed on 5Yx5Y swap yield since 1-Jan-2018: **y = 33.23x² + 10.56x + 15.44, R² = 99%** ⇒ *"trading **10bp too rich**"*. Linear 6M version: residual **≈11bp**.
2. **Fly-vs-fly.** Fly vs EUR 2s/10s/30s 50:50 fly, past 6M: **y = 0.87x + 23.95, R² = 55%** ⇒ *"**7bp too rich** versus 2s/10s/30s fly"*.
3. **Level-and-curve-neutral residual**, past 6M:
   (a) `Y = 11.49·(5Yx5Y) + 31.93·(1Yx1Y/10Yx10Y) − 19.3; R² 78%; SE 2.9bp`
   (b) `Y = 41.1·(10Y) − 12·(2s/10s) − 7.4; R² 91%; SE 1.6bp`
   *(caption for (b) says the regressors are 10Y yield and the **2s/30s** curve while the printed equation says **2s/10s** — unresolved discrepancy in the source.)*
**DRIVER / PROXY.** *"large scale **issuance based receiving** in this [10Y] sector, some **real money receiving**, and anecdotal evidence of **fast money unwinding paid positions** in the 10Y sector which were expressed via 2s/5s/10s fly."* Only the 2s/5s/10s fly is an observable proxy.

---

## 14. JPM — RV on the EUR swap yield curve: a historical perspective / beta-stability framework (07-Apr-2021)
`scratchpad/txt/RV_on_the_EUR_swap_yield_curve_a_historical_perspective_Improve_monetisation_of_.txt`

**This is the only document in the corpus containing a complete, reproducible systematic-strategy spec with a published performance grid.**

**UNIVERSE (footnotes 1-3, PAGE 3).**
- *Cat 1 — standard flies* (spot, 1Y-fwd, 2Y-fwd, 5Y-fwd): 1s/2s/3s, 1s/2s/5s, 1s/3s/5s, 2s/3s/5s, 2s/5s/7s, 2s/5s/10s, 2s/7s/12s, **2s/10s/30s**, 3s/5s/10s, 3s/7s/15s, 5s/7s/10s, 5s/10s/15s, **5s/10s/30s**, 7s/10s/15s, 7s/15s/20s, 10s/12s/15s, **10s/15s/20s**, **10s/20s/30s**, 12s/15s/20s, 12s/20s/30s, **15s/20s/30s** (21 flies × 4 starts).
- *Cat 2 — 5Y-tail non-overlapping, 5Y-gap forwards*: 5s/10s/15s, 10s/15s/20s, 15s/20s/25s, **20s/25s/30s, 25s/30s/35s, 30s/35s/40s, 35s/40s/45s** ⇒ e.g. **5Yx5Y/10Yx5Y/15Yx5Y** … **35Yx5Y/40Yx5Y/45Yx5Y**. **This is the ultra-long-end block.**
- *Cat 3 — 1Y/2Y gap flies*: 1Yx(1M/1Y/2Y), 1Yx(1Y/2Y/3Y), 1Yx(2Y/3Y/4Y), 1Yx(1M/2Y/4Y), 2Yx(1M/2Y/4Y), 2Yx(2Y/4Y/6Y), 2Yx(4Y/6Y/8Y), 2Yx(6Y/8Y/10Y).

**RISK WEIGHTING.** 50:50 fly, made **level- and curve-neutral** by a **rolling 6M two-factor regression** of the fly on (body yield, curve).

**ENTRY (3 simultaneous thresholds, 12 combinations tested):** R² ∈ {60%, 80%}; |residual| ∈ {2, 3, 4} bp; |z-score of residual| ∈ {1.5, 2}. **Recommended: R² ≥ 60%, |residual| ≥ 4bp, |z| ≥ 1.5.**

**EXIT (verbatim, PAGE 4-5):** *"(i) **The residual has fully reverted to zero** … when the **out-of-sample residual (calculated using ex-ante regression betas)** has crossed zero for the first time based on COB levels. (ii) **The residual has worsened by another two SD** … stop out at **3.5 or 4 z-score**. (iii) **1M (or the trade horizon) has passed**"* — justified by a **Fourier transform of the rolling residual** showing *"dominant mean reverting frequencies are less than 1M with some peaks around the 2M and 3M horizon."*
**Portfolio rules:** multiple simultaneous trades allowed; *"we do not re-enter into the same trade on consecutive days"*; a stopped-out fly **may** be re-entered the next day.

**PERFORMANCE (Exhibit 7, bp of yield, per trade, Jan-2001→Apr-2021) — the full 12-column grid:**

| criterion | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R² | 60 | 80 | 60 | 80 | 60 | 80 | 60 | 80 | 60 | 80 | 60 | 80 |
| resid | 2 | 2 | 3 | 3 | 4 | 4 | 2 | 2 | 3 | 3 | 4 | 4 |
| z | 1.5 | 1.5 | 1.5 | 1.5 | 1.5 | 1.5 | 2 | 2 | 2 | 2 | 2 | 2 |
| **Overall avg** | 0.7 | 0.4 | 1.0 | 0.6 | **1.3** | 0.8 | 0.7 | 0.4 | 1.0 | 0.7 | **1.3** | 0.9 |
| Success | 50% | 47% | 52% | 48% | 52% | 48% | 54% | 51% | 55% | 52% | 55% | 53% |
| Max | 39 | 39 | 39 | 39 | 39 | 39 | 42 | 26 | 42 | 26 | 42 | 26 |
| Min | −19 | −16 | −19 | −16 | −19 | −16 | −14 | −13 | −14 | −13 | −14 | −13 |
| Trades | 3587 | 1964 | 1929 | 976 | 1188 | 564 | 2642 | 1527 | 1479 | 785 | 923 | 457 |
| **Good-period avg** | 0.9 | 0.7 | 1.3 | 1.0 | 1.6 | 1.2 | 0.9 | 0.7 | 1.3 | 1.0 | 1.5 | 1.3 |
| Good success | 54% | 52% | 55% | 52% | 55% | 51% | 58% | 56% | 58% | 56% | 58% | 57% |
| Good trades | 2456 | 1266 | 1383 | 639 | 905 | 402 | 1799 | 997 | 1046 | 518 | 698 | 328 |
| **Critical-period avg** | 0.1 | 0.0 | 0.3 | 0.0 | 0.5 | −0.1 | 0.1 | −0.1 | 0.3 | 0.0 | 0.4 | −0.1 |
| Critical success | 42% | 38% | 43% | 40% | 43% | 39% | 46% | 42% | 48% | 44% | 48% | 43% |
| Critical trades | 1131 | 698 | 546 | 337 | 283 | 162 | 843 | 530 | 433 | 267 | 225 | 129 |

**"Critical periods" (defined ex-post, PAGE 5):** 3Q04–2Q05, 3Q07–4Q07, 2Q11–4Q12, 2015, 4Q16–1Q18, 2Q19. Worst by trigger, 2Q07–4Q07: avg **−2.9bp**, success **10%** (R²80/resid4/z2).

**THE TRAFFIC-LIGHT INDICATOR (verbatim, PAGE 12):**
> *"First, we find the **6M Z-scores of the 3M volatility of each of the regression beta**. Second, we calculate the **quadratic average of the two Z-scores**. … **"Traffic light Indicator" = √(Zb² + Zw²)** where Zb (Zw) is defined as the 6M Z-score of 3M volatility of the regression beta of the 50:50 fly versus **body** (**wing**), after adjusting for the wing (body)."*
> Threshold: *"If we use **3** as an arbitrary cut off threshold…"* / *"a threshold of **3** is optimum in terms of not reducing aggressively the total number of trades while still delivering decent improvement."*

**INDICATOR VALIDATION — carry this caveat.** Quarterly total P&L vs TL: **y = −6.87x + 238.69, R² = 0%**. Quarterly P&L *conditioned on being negative* vs TL: **y = −44.78x − 45.10, R² = 17%**. ⇒ **the indicator predicts the loss tail only, not returns.** Effect of the filter: *"the overall P&L during the **'critical period' increases by around 25%**, on average."* Portability: *"**Ideally, users should build this indicator based on the exact fly they wish to trade**"*; an indicator built on 2s/10s/30s betas *"also improves performance"* (Exhibit 18).

**CATEGORY RESULT (ultra-long relevance).** *"Money market flies (Category 3) tend to perform **better overall and during 'good' periods**. However, the **5Y forward gap flies (Category 2) have outperformed during 'critical' periods** … during ECB regime shifts, the front-end exhibits larger volatility and RVs are likely to be **optical** in nature as opposed to those observed at the **long-end**."* — **directly argues the ultra-long block is the regime-robust one.**

**DRIVER.** Regime shifts in central-bank expectations. Observable proxy = the beta-volatility indicator itself (built entirely from the curve, no external data).

---

## 15. JPM — A comprehensive look at convexity hedging in interest rates (29-Mar-2019)
`scratchpad/txt/Interest_Rate_Derivatives_A_comprehensive_look_at_convexity_hedging_in_interest_.txt`

**Not a trade note — the source of the driver taxonomy and its observable proxies.** Five convexity-hedger cohorts with explicit modelling recipes (Exhibit 4 note, PAGE 4):
- **Banks** — modelled on J.P. Morgan Agency MBS Index composition, **assuming 20% of dynamic duration is actively hedged with swaps**; ~30% of a ~$2tn agency MBS market.
- **GSE retained portfolios** — 2009 index composition with passive paydowns; peaked ~$850bn pre-crisis, **down ~80% to below $200bn**.
- **mREITs** — coupon/tenor/spec-pool mix from **AGNC investor presentations**, grossed up to total REIT agency holdings; largest 12 held **~$280bn**; quadratic fit to reported rate sensitivities of NLY/AGNC/CMO/CYS quarterly disclosure.
- **MSR** — modelled as a **30bp IO strip** off the index, weighted by the top-4 banks' servicing share (>50% pre-crisis → **~25%**).
- **Programmatic gamma sellers** — *"$500mn notional **daily** sales of 1Mx10Y ATMF straddles, held to expiry"*; *"returns … net of transaction costs, are maximized when using a **modest (but not too tight) delta rebalancing threshold (e.g., 25%)**"*; total program size *"at most **$10mn per bp**"*; *"**$3-4mn per bp of rebalancing can occur on 10-20% of days**"*.
- **Formosa-style callables (positive-convexity offset)** — *"all long-dated callable bonds (**>15-year original maturity**) issued after 2011 likely purchased by Taiwanese … and Korean life insurers. We model each as a **callable swap struck at the prevailing par rate as of the announcement date**, using the **Bloomberg reported structure**."* Aggregate dealer position *"at times been as large as **$200mn per bp**"*; *"~**40% on a vega risk-weighted basis**"* placed with end users as **B/E switches**; *"$56mn per bp in pay-fixed flow from the Street since late-2018 ($34mn per bp in the past month)"*; dealer sensitivity stays within **80-90%** of current until a **50bp+ rally**.
- **Variable annuities** — rolling 1y partial beta of weekly VA liability duration ($mn/bp) to weekly 30Y Treasury moves (per 25bp) and weekly S&P returns (per 5%). Conclusion: *"long end spreads are driven **much more by the slope of the yield curve than VA**"* (Exhibit 13).

**Aggregate magnitude.** *"Since rates peaked late last year, we estimate **more than $200mn per bp** of duration demand was delivered … with a notable **offset from callable bonds (more than $100mn per bp in the past month alone)**."* Peak negative MBS convexity *"still a ways lower in rate, reached only in a roughly **70-100bp rally**"*; convexity exposure could rise **~30%** on a 70bp+ rally.

**TRADE (fully specified, PAGE 9).** *"Sell the **3Yx27Y B/E switch @ 4.5%** to buy the **5Yx25Y B/E switch @ 3%**"*: sell $100mn 3Yx27Y Bermudan receiver (first notification 3/28/22, annual, maturity 3/30/49, strike 4.5%, **premium 3585bp**) vs buy $100mn 3Yx27Y European receiver (same dates, **3523bp**); buy $100mn 5Yx25Y Bermudan receiver (first notification 3/28/24, annual, maturity 4/2/49, strike 3.0%, **1385bp**) vs sell $100mn 5Yx25Y European (**1161bp**). ⇒ B/E switch values **62bp** and **224bp** respectively.

## 15b. JPM — Is bank convexity hedging lying in wait? (31-May-2019)
`scratchpad/txt/Interest_Rate_Derivatives_Is_bank_convexity_hedging_lying_in_wait_Fri_May_31_201.txt`

**THESIS.** *"large commercial banks **do not actively hedge** their convexity exposure, [but] a sufficient rally will eventually incentivize these players to cover"*; *"the aggregate dollar duration delivered would **exceed $300bn in a 50bp rally**"*; *"even if only a quarter of this delivery is hedged, it could be in excess of **$100mn per bp** … Were rates to decline another 50 bp, we estimate bank portfolio durations would shorten by another **$300-400mn per bp**."*
**ASYMMETRY (tradeable).** *"The **threshold-based** nature of this behavior suggests strong asymmetry, with spreads preferentially narrowing **in a rally**."*
**TRADES.** (i) *"Sell **$200mn notional of 2.00% May 2024s** and receive fixed in **$200mn of a 5/31/24 OIS** @ a matched maturity Treasury/OIS spread of **23.3bp**. Carry ≈ **−1bp over 3 months**, slide roughly flat."* (ii) *"Sell **1,000 128.5 TYQ calls** (premium 27c, 7/26/19 expiry, ATM @ 127) versus buying **$130mn matched-expiry receiver swaptions** (premium 21.7c, 7/26/19 expiry, 9/3/19 swap start, 4/30/26 maturity, **strike 1.67% vs ATMF 1.96%**), **premium neutral at initiation**."* — a conditional bet on rally-side spread narrowing, financed by rich board call skew.

## 15c. JPM — The return of convexity hedging (31-Jan-2020)
`scratchpad/txt/Interest_Rate_Derivatives_The_return_of_convexity_hedging_Fri_Jan_31_2020.txt`

**FAIR-VALUE MODEL (Exhibit 3) — the single most implementable regression in the convexity-hedging trio.** *"Incorporating both into a simple regression, we find that swap spreads are **3-5 bp too wide** at current levels."* Regressors: **(1) bank convexity duration** (Exhibit 2: *"Net duration of large commercial bank portfolios, assuming no additional hedges and flat exposure as of Q1-end 2019; $bn of 10-year equivalents"*, close to **−$1tn 10-year equivalents**) and **(2) 3-month GC/OIS spread**. Bank catch-up estimate: *"**roughly $275mn per bp more to hedge at current levels**."*
**TRADE.** *"we therefore recommend **receiving TYH0 invoice spreads**."*
**Liquidity diagnostics (reusable).** 2-year z-score of rolling 5-day **market depth** (notional at the best few prices, both sides, trade-volume weighted) and **price impact** (*"average price move per $100mn of traded volume … sign corrected for flow imbalance"*) in 10-year hot-run Treasuries, BrokerTec interdealer.
**Vol move tie-out.** Week-on-week 3-month expiries rose **7.1 / 7.4 / 6.5 / 6.3 abp** in 2-, 5-, 10- and 30-year tails.

---

## 16. Citi — US Rates Vol Lab: Long Live Formosa (09-Jan-2017)
`scratchpad/txt/US_Rates_Vol_Lab_Long_Live_Formosa.txt` PAGES 2-4

**THE VEGA-SUPPLY MODEL (the corpus's most quantitative Formosa proxy).**
- Regulatory driver: FSC proposal requiring a **minimum 6y non-call** for exemption from the **45% cap** on foreign investments. Foreign non-exempt holdings **~37% of total assets (2013) → ~42% (end-2016)**; total assets growing **~9%/yr**, foreign holdings **~25%/yr**.
- Supply: net Formosa 2016 **≈$30bn**; forecast net **≈$35bn/yr**; gross **≈$38bn** for Q2-2017→Q2-2018.
- **Per-bond vega (tie-out): 30NC1 and 30NC6 zero-coupon callables carry bp vega of ≈$145K and ≈$270K per $100mn of initial notional.**
- Aggregate impact of the rule: **+$31mn of normal vega (≈$20bn of 10y10y straddle equivalents)** in year one; **+$46mn normal vega (≈$25bn 10y10y straddle equivalents)** concentrated in **10y expiries**.
- Bucketed-vega mechanism: *"30NC1 is most likely to be hedged with some combination 1y30y and 10y20y (or even 10y10y for liquidity) … 30NC6 largely hedged with 10y expiries (10y20y or 10y10y). The net result … **less supply in 1y-2y expiries in 30y tails** and **more supply in 10y expiries and in 10y-20y tails**."*

**TRADE (beta-weighted vol switch).** *"buying **2y30y straddles vs 2y10y straddles on a beta-adjusted basis (1 unit of vega on 2y30y vs 0.8 units of vega on 2y10y**, or **$53mn notional 2y30y vs $100mn 2y10y**)"*. Companion valuation: *"the **10y30y looks about 5 normals (about 1.6 sigmas) cheap to 2y30y vol**."*
**CA note (same issue).** *"Convexity adjustments in **Blues** are especially rich to the model (**by about 3 sigmas**)"*, attributed to *"short positions in ED futures established post FOMC."*

## 16b. JPM — Renewed Formosa supply continues to flatten the long end (21-Feb-2020)
`scratchpad/txt/Interest_Rate_Derivatives_Renewed_Formosa_supply_continues_to_flatten_the_long_e.txt` PAGES 2-4

**THE CLEANEST PUBLISHED DEFINITION OF THE STRAT-1 SIGNAL (Exhibit 3 note, verbatim):**
> *"**Implied volatility on a 20s/40s flattener comes from solving for the level of prevailing volatility that would make the flattener's expected convexity P/L precisely offset 1-year slide under parallel rate shocks. Expected payoff comes from using swaption-implied vol to solve for the flattener's expected convexity P/L.**"*
Plotted for **20Y/40Y, 40Y/50Y, 30Y/50Y**: LHS = *"Expected payoff from holding a long-end swap yield curve flattener for a year (bp yld)"*; RHS = *"the **ratio of swap curve-implied vol** (a measure of how cheap such a curve is; %)"*. **The RATIO (swap-implied / swaption-implied) is the published normalisation** — the codebase's `frac_always_cheap` / cheap-share are not.

**FLOW MODEL.** Q1-2020 Formosa duration supply **≈$9bn of 10-year equivalents**, *"a majority hedged via cancellable swaps"*; March run-rate would give a *"record **$14bn+ in 10-year equivalents**"*. Redemptions **≈$20bn** called/announced Q1-2020, **$14bn cash returned**, **$14.5bn** reissued; forecast **+$7bn** March. Structural shift **30nc5 → 40nc5** ⇒ *"inherently more exposed to **20-50Y partial duration risk**, and this coupled with a far flatter yield curve (longer dated calls more ITM, therefore higher delta) means issuance has generated far more receiving activity at the long end."*
**Vega-supply model assumptions (Exhibit 4 note):** *"par accreter callable struck as of the announcement date … assuming the returned principal is reinvested in callables and that this comes from a **50/50 mix of 30nc5 and 40nc5** structures."* Dealer dVega/dRate *"moved closer to saturation and now looks incrementally biased towards **net vega delivered in a large selloff**."*
**TRADES (named in body; sizes NOT extracted — the Trade Recommendations page did not surface in the text extraction):** *"we maintain exposure via **30Yx10Y vs 10Yx10Y swap yield curve flatteners**"* and *"vol surface flattening via **10Yx10Y vs 20Yx10Y vega-neutral ATMF swaptions**"*.
**Structural claim.** *"Thus all signs continue to point to a flatter ultra-long end yield curve. And **with no natural payer this far out the curve, we see little reason for a floor to be enforced**."*

---

## 17. Citi — North America Rates Focus: Corporate supply to bring spreads tighter (03-Jan-2017)
`scratchpad/txt/North_America_Rates_Focus_Corporate_supply_to_bring_spreads_tighter.txt` PAGES 2-3

**STRUCTURE.** Tactical **10y swap spread tightener**, held ~2 weeks over the January supply surge.
**SIGNAL (seasonal, Figure 3) — change in swap spreads to/from year-end, bp:**

| horizon | block | 2y | 3y | 5y | 10y | 30y |
|---|---|---:|---:|---:|---:|---:|
| 10d before | 5y median (2011-15) | 1.7 | 4.1 | −1.3 | −0.6 | −0.1 |
| 5d before | 5y median | −0.7 | 0.8 | 0.0 | −0.4 | 0.2 |
| **5d after** | **5y median** | −0.8 | −0.4 | −1.1 | **−3.0** | **−1.8** |
| 10d after | 5y median | −0.7 | −1.4 | 0.4 | −2.0 | −2.7 |
| 20d after | 5y median | −0.3 | −0.6 | 2.9 | −0.2 | −2.3 |
| 10d before | 10y median (2006-15) | −0.1 | 0.6 | −2.7 | −0.4 | 2.3 |
| 5d before | 10y median | −0.8 | 0.3 | −1.4 | −1.1 | 0.4 |
| **5d after** | **10y median** | −0.5 | −1.0 | −0.6 | **−2.1** | **−2.5** |
| 10d after | 10y median | −1.2 | −4.0 | 0.9 | −2.6 | −2.8 |
| 20d after | 10y median | −0.6 | −2.2 | 2.8 | −0.8 | −2.6 |
| 10d before | 2016 | −0.5 | 6.4 | 0.8 | −1.5 | −4.8 |
| 5d before | 2016 | −4.4 | 3.4 | 0.8 | −0.6 | −4.4 |

**RELATIVE-VALUE OVERLAY.** 10y vs 30y spread regression, sample 1/1/2016–1/2/2017: **y = 0.41x + 6.71, R² = 0.65**; *"10y spreads look about **2bp wide** to 30y spreads"* ⇒ pick 10y over 30y despite 30y's larger seasonal beta, because 30y *"already came off from the highs by about 4bp in the last week of December."*
**DRIVER / OBSERVABLE PROXIES (all named series).** (1) **January share of annual financial issuance = 13%** (median 2012-16, Dealogic). (2) **Financial redemption schedule**: $11bn Dec-2016 vs est. **$36bn Jan-2017** (5y Jan average ≈$32bn). (3) **Average maturity of fixed-rate financial January issuance ≈8.4 years**. (4) **Long-dated callable redemptions**: est. **$450mn Jan-2017** vs **≈$1bn Jan-2016**; expected callable issuance **≈$5bn** vs $1.5bn in December. (5) **TLAC shortfall**: Fed-estimated **$49bn eligible long-term debt / $70bn total** for US G-SIBs.
**MECHANISM AT 30Y.** *"January months normally see a surge of long-dated callables, including Formosa. **Dealers normally hedge associated swaps by receiving in 30y, which has a direct negative impact on 30y spreads.**"*

---

## 18. CONSOLIDATED — "RISK-ADJUSTED CARRY": five distinct definitions, side by side

The user singled this out. The corpus contains **five different constructions** and they are not interchangeable.

### RAC-1 — Citi `BE / realized vol` (the dominant one; 4 independent vintages)
```
daily_BE_bp      = the daily move in the underlying rate whose CONVEXITY gain exactly
                   offsets one day of the package's carry;  == 0 whenever 1y carry >= 0
realized_vol_bp  = 1-YEAR TRAILING DAILY REALIZED VOL, in bp/day, OF THE BACK
                   (longer, delta-hedged) FORWARD RATE — not of the curve, not of the front leg
signal           = daily_BE_bp / realized_vol_bp          (unitless)
```
- **Back-leg keying is VERIFIED TWICE, independently.** 12-Jun-2023 Fig 5: the vol row takes exactly 6 distinct values keyed to the back leg — 15y15y 5.30, 20y5y 5.24, 20y10y 5.11, 20y15y 4.85, 25y5y 4.98, 25y10y 4.66 — repeating identically across all pairs sharing that back leg. Same pattern in the 12/4/2019 table (20y5y 4.23, 20y10y 4.16, 20y15y 4.17, 25y5y 4.08, 25y10y 4.13, 15y15y 4.22) and the 1/16/2020 5-currency table. **This is implementation-critical**: keying it to the curve or to the front leg reproduces neither table.
- **Sign convention.** *Flattener (long convexity, negative carry):* **LOW is attractive**; observed exit at **0.8**. *Steepener (short convexity, positive carry):* **HIGH is attractive**, *"meaningfully above 1"*; observed entries at **1.17 / 1.38**.
- **The BE=0 truncation** makes the metric one-sided: for a positively carrying flattener the ratio is 0 and the trade is *"an effectively free convexity buy"* (GBP 15y10y/25y10y, carry +0.52bp, 17-Jan-2020; USD 15y5y/20y10y, carry +0.11bp, 26-Mar-2020).
- **Implied functional form (INFERRED from column ratios, not printed):** `BE = sqrt(2 · carry_daily / Γ)` with Γ the package's convexity. Check: 10y10y/20y10y (carry 3.95, BE 3.93) vs 15y5y/20y10y (carry 2.09, BE 3.33) on 12/4/2019 implies Γ ratio 1.357 — consistent with the wider (10y→30y vs 15y→30y) forward gap carrying more convexity. **Not measured beyond this ratio arithmetic.**

### RAC-2 — JPM `RAC` (expected-return over annualised vol)
```
E[return]_3M_bp = carry_3M + slide_3M + value_of_convexity_3M      [bp of yield]
value_of_convexity = 0.5 * sigma^2 * Convexity / PVBP
RAC = E[return]_3M_bp / ( realised_daily_bp_vol_3M * sqrt(252) )   [unitless]
```
- **VERIFIED 4/4 rows exactly** (§19). **√252 is the unique annualiser** among {250, 252, 260} that reproduces all four printed values to 2dp.
- **CAPTION TRAP:** Exhibit 12 is captioned *"Annualised 3M expected return divided by annualised expected volatility"* — the numerator in the verified arithmetic is the **raw 3M** figure. Implementing from the caption gives a value **4× too large**.
- Related two-sided use: Exhibit 16 solves for the **breakeven vol ratio** that equates two maturities' expected returns (30Y needs a ~20% vol decline vs 50Y).

### RAC-3 — Citi forward-vol `ex-ante Sharpe = vol-adjusted roll`
```
sigma_fwd = sqrt( ( sigma_long^2 * T_long - sigma_short^2 * T_short ) / (T_long - T_short) )
ex-ante Sharpe = 3m_roll_on_the_surface / <vol-adjustment>
value          = 1y z-score of sigma_fwd
```
- Forward-vol formula **verified exactly** on `1y2y1y / 3y1y`: (120.7²·3 − 145.5²·1)/2 = 11267.6, √ = **106.15** vs printed **106.1**.
- **The denominator is NOT PRINTED.** Back-solved from roll/Sharpe across 20 rows it lies in **6.3–20.4 normal-vol units**, varying by structure — consistent with a realised **vol-of-forward-vol** normalisation. **NOT MEASURED** beyond that ratio arithmetic; do not assert the construction.
- Legs are **gamma-neutral weighted** (e.g. 254.2/100, 69.8/100); triangles use *"6m realized correlations as a proxy for implied correlations"*.

### RAC-4 — CA screen `3m Roll (short cvx)` + `Implied/Realized`
Per-pack columns on the ED/SOFR screens: **3m Roll (short cvx, bp)**, **Implied Vol** (the vol that reprices the *observed* CA through Ho-Lee), **Realized Vol** (3m realized vol of that pack), **Implied/Realized**, and **Cap-vol Impl/Rlzd**. Selection rule between packs (Jun-2021): pick the one with **higher 3m roll AND higher implied-from-CA vol**, even if a different pack is more dislocated versus model.

### RAC-5 — target = dislocation minus convexity cost (2010 fly)
`target = (current − model-predicted) − convexity_cost_per_annum` = 28 − 8 = **20bp**, with stop at **10bp** (2:1). The **convexity cost is priced explicitly, from an assumed realised vol** (*"11bp/a assuming realized volatility of 120bp/a"* for the 10s30s steepener). This is the only note in the corpus that converts convexity into a **cost that shrinks the profit target** rather than a signal.

---

## 19. CONSOLIDATED TIE-OUT TABLE

| # | date | quantity | value + units | source | verification status |
|---|---|---|---|---|---|
| T1 | 09-Feb-2018 | JPM RAC, OAT 25-May-48 | carry 10.6 + slide 2.0 + cvx 3.3 = **15.9bp**; 3M rlzd vol **3.0 bp/day**; **RAC 0.33** | `Valuing convexity….pdf.md` Ex.2 | **ARITHMETIC-VERIFIED**: 15.9/(3.0·√252)=0.3339→0.33 |
| T2 | 09-Feb-2018 | RAC, OATs 55/60/66 | 0.32 / 0.30 / 0.25 | same | **ARITHMETIC-VERIFIED 3/3**; √250 and √260 both fail ≥1 row |
| T3 | 09-Feb-2018 | flattener-vs-1Yx30Y-straddle hit rates | **56% (30s/50s), 86% (25Y/20Yx5Y)** | same | transcribed-clean |
| T4 | 09-Feb-2018 | EUR 1Y value of convexity 10Y/20Y/30Y/40Y/50Y | **1.2 / 2.3 / 3.3 / 3.9 / 4.5 bp**; avg 2.5/4.4/6.1/7.4/8.6; SD 1.0/2.2/3.8/4.8/5.7 | Ex.15 | transcribed-clean; z-scores self-consistent |
| T5 | 09-Feb-2018 | GBP 1Y value of convexity 10Y…50Y | **2.0 / 3.5 / 4.9 / 6.1 / 7.3 bp** | Ex.22 | transcribed-clean |
| T6 | 09-Feb-2018 | 30s/50s par gilt fair value | `0.6·cvx + 5.3·y50 − 31`, R² 56%, SE 4bp; curve **5bp too flat** | Ex.25 | transcribed-clean |
| T7 | 04-Dec-2019 (close) | Citi flattener screen, USD 15y5y/20y10y | curve **−12.54bp**, carry **−2.09 bp/yr**, BE **3.33 bp/day**, vol **4.16 bp/day**, **BE/vol 0.80** | `20y10y_flatteners.pdf.md` Fig 1 | **COLUMN-MAPPING VERIFIED** by body text ("−12.5bp", "−2bp/year", "0.8"); BE/vol **15/15 rows reproduce** |
| T8 | 04-Dec-2019 | GBP 15y10y/25y5y | ZS2000 **1.86**, carry **+0.54**, BE **0.00**, BE/vol **0.00** | same | cross-verified by body text ("upper bound … carries positively") |
| T9 | 05-Dec-2019 | USD 15y5y/20y10y trade P&L | entry **−11.8bp** (5/9 or 5/10-2019), exit **−12.5bp**, MTM **+$187K**, booked **+$155K net**, $50K DV01 | same | transcribed-clean; **initiation date conflicts across the two alerts** |
| T10 | 16-Oct-2019 | reweight | notionals **$149.5mn 15y5y / $81.97mn → $84.0mn 20y10y**; beta **1.025**; MTM **+$105K** | `20y10y_flatteners (1).pdf.md` | ratio-verified (84.0/81.97 = 1.0248) |
| T11 | 26-Mar-2020 | GBP 15y10y/25y10y close-out | **GBP 445K net** = **115K curve + 330K convexity**, 50K DV01, entry −11.2bp Jan-2020 | `25y10y_flatteners.pdf.md` | transcribed-clean; 115+330=445 ✓ |
| T12 | 16-Jan-2020 (close) | 5-currency flattener screen | GBP 15y10y/25y10y: **−10.37bp, carry +0.52, BE 0.00**; USD 15y5y/20y10y: **−13.65, −2.20, 3.41, 4.27, 0.80** | `In_search_of_cheap_vol.pdf.md` Fig 11 | **COLUMN-MAPPING VERIFIED** ("carry positively by about 0.5bp"); BE/vol arithmetic reproduces |
| T13 | 26-Mar-2020 3pm | USD screen | 15y5y/20y10y **−5.21bp, carry +0.11, BE 0.00, 1y rlzd vol 6.40 bp/day** | `Liquidity_vega_and_convexity.pdf.md` Fig 9 | **COLUMN-MAPPING VERIFIED** ("−5.21 bp as of 3pm on 3/26/2020", "slightly positive carry") |
| T14 | 30-Mar-2020 | bid/offer, 10y swaps | **mid-to-bid ≈0.6bp** | same, l.93 | transcribed-clean |
| T15 | 08-Jun-2023 (close) | Citi steepener screen, 10 cols | see §6 table; **BE/vol 10/10 rows reproduce to 2dp** | `Forward_steepener….pdf.md` Fig 5 | **ARITHMETIC-VERIFIED 10/10**; back-leg vol keying verified |
| T16 | 12-Jun-2023 | Blues CA vs model | *"about **5bps lower**"* than market | same, l.118 | transcribed-clean |
| T17 | 09-Jun-2023 (close) | SOFR pack CA screen, 13 rows M4-H5…M7-H8 | M4-H5 CA 4.03 / model 2.94 / implied 199.5 / realized 229.7; M7-H8 CA 22.29 / model 14.50 / implied 151.9 / realized 113.8 | same, Fig 58 | transcribed-clean; **already the codebase's known-answer anchor** |
| T18 | 09-Jun-2023 | forward-vol triangle | `1y2y1y`: σ_s 145.5 (T=1), σ_l 120.7 (T=3) → σ_f **106.1** | same, Fig 22 | **ARITHMETIC-VERIFIED**: computed 106.15 |
| T19 | 11-Jan-2019 (close) | ED pack CA screen, 17 rows H9-Z9…H3-Z3 | H9-Z9 0.06 / M0-H1 1.09 / H3-Z3 7.44 bp; implied vols 53.3→84.4 nv, realized 61.0→65.5 | `Gamma_and_Vega_RV.pdf.md` Fig 57 | transcribed-clean (second CA vintage, ED not SOFR) |
| T20 | 11-Jan-2019 9am | vol tenor fly ticket | **−$230mn 3y2y / +$100mn 3y10y / −$21mn 3y30y**, vega-neutral, **take-in $240K**; carry **+0.75nv/+$43K (1y)**, **+6nv/+$341K (2y)**; fly at **−4.0 nv (−1.9σ)**, FV **+5nv** | same, l.190-200 | transcribed-clean |
| T21 | 11-Jun-2021 noon | Blues CA trade | **1000 EDM4-H5** vs **$1.01bn** CME swap 6/17/24-6/16/25 @ **7.9bp**, $100K DV01; **→5.9bp by 6/21**; carry **+1.2bp/3M**; **target 4bp, stop 3bp** | `Left_side_vols….txt` PAGE 8 | transcribed-clean — **the only entry/target/stop in the CA family** |
| T22 | 21-Jun-2021 (close) | fwd-vol frontier example | 6m30y vs 1y30y (≈6m6m30y): **Sharpe 1.07, 3m ZS −1.4** | same, l.1455 | transcribed-clean |
| T23 | 11-Feb-2019 | EUR PCA fly weights | **−13.3% / +100% / −77.8%** (5Yx5Y/15Yx5Y/30Yx5Y); 3M carry **−1bp** (text) vs **−1.4** (table) | `Euro_Swaps….txt` PAGE 3-4 | **discrepancy between text and table — carry both** |
| T24 | 11-Feb-2019 | EUR Exhibit 8 grid, 9 structures | see §5 tables | same | **SELF-CONSISTENT**: Dislocation = Current − 1Y avg (5/5), Z = Disloc/SD (5/5) within integer-SD rounding |
| T25 | 23-Jan-2020 | EUR fly ticket | **Pay €100mn 5Yx5Y / Rec €251.8mn 1Yx1Y / Rec €26.2mn 10Yx10Y**, fly **11.6bp** = 2·5Yx5Y−1Yx1Y−10Yx10Y; carry **−2bp/3M** | `RV_Trade_Note….txt` PAGE 3 | notional ratios consistent with 50:50 DV01 |
| T26 | 23-Jan-2020 | EUR fly valuation regressions | quadratic **33.23x²+10.56x+15.44, R² 99%** (→10bp rich); fly-vs-fly **0.87x+23.95, R² 55%** (→7bp rich); L&C-neutral (a) R² 78% SE 2.9bp, (b) R² 91% SE 1.6bp | same PAGES 1-2 | transcribed-clean; **(b)'s regressor labelled 2s/10s in the equation and 2s/30s in the caption** |
| T27 | 07-Apr-2021 | beta-stability performance grid | 12 triggers × 3 regimes × 5 stats (see §14) | `RV_on_the_EUR_swap_yield_curve….txt` Ex.7 | transcribed-clean; trade counts monotone in strictness ✓ |
| T28 | 07-Apr-2021 | traffic light | **√(Zb²+Zw²)**, threshold **3**; neg-P&L regression **−44.78x−45.10, R² 17%**; all-P&L **R² 0%**; critical-period P&L **+25%** | same PAGES 12-14 | transcribed-clean |
| T29 | 20-Dec-2010 | 1y-fwd 5s10s30s ticket | −$180mn 1y5y @2.971 (Δ 84,827, Γ −64) / +$200mn 1y10y @3.908 (Δ −171,139, Γ 206) / −$50mn 1y30y @4.344 (Δ 86,510, Γ −230); total Δ 198, Γ −88; **target 20bp, stop 10bp** | `…5s10s30s_Fly.pdf.md` Fig 6 | **ARITHMETIC-VERIFIED**: Σ Δ = 198 ✓; predicted fly 9%·6+21%·10+70%·24 = 19.4 → 19 ✓ |
| T30 | 20-Dec-2010 | convexity costs | fly **8bp/a**; 1y-fwd 10s30s steepener **11bp/a at 120bp/a realised vol**; fly carry −5bp/a, steepener +27bp/a | same | transcribed-clean |
| T31 | 09-Jan-2017 | Formosa per-bond vega | **30NC1 ≈ $145K, 30NC6 ≈ $270K bp-vega per $100mn initial notional** | `Long_Live_Formosa.txt` PAGE 3 | transcribed-clean |
| T32 | 09-Jan-2017 | Formosa aggregate vega | **+$31mn normal vega (≈$20bn 10y10y straddle equiv)**; 10y expiries **+$46mn (≈$25bn)** on $38bn/yr gross | same PAGE 4 | transcribed-clean |
| T33 | 09-Jan-2017 | Formosa vol switch | **$53mn 2y30y straddles vs $100mn 2y10y** (1 : 0.8 vega); 10y30y **5nv / 1.6σ cheap** to 2y30y | same | transcribed-clean |
| T34 | 21-Feb-2020 | Formosa duration supply | Q1-2020 **≈$9bn** 10y-equiv; record run-rate **$14bn+**; redemptions $20bn called, $14bn cash, $14.5bn reissued, +$7bn March | `Renewed_Formosa….txt` PAGE 3 | transcribed-clean |
| T35 | 29-Mar-2019 | convexity-hedger aggregate | **>$200mn/bp** duration demand since Nov-2018; callable offset **>$100mn/bp in one month**; dealer callable book peak **$200mn/bp**; program gamma **≤$10mn/bp**, **$3-4mn/bp on 10-20% of days** | `A_comprehensive_look….txt` PAGES 2-8 | transcribed-clean |
| T36 | 29-Mar-2019 | B/E switch trade | 3Yx27Y Berm 3585bp vs Euro 3523bp (switch **62bp**, strike 4.5%); 5Yx25Y Berm 1385 vs Euro 1161 (switch **224bp**, strike 3.0%) | same PAGE 9 | **ARITHMETIC-VERIFIED**: 3585−3523=62; 1385−1161=224 |
| T37 | 31-May-2019 | bank hedging scale | **>$300bn** dollar duration in a 50bp rally; **>$100mn/bp** if a quarter hedged; further 50bp ⇒ **$300-400mn/bp** | `Is_bank_convexity….txt` PAGE 5 | transcribed-clean |
| T38 | 31-Jan-2020 | spread fair value | spreads **3-5bp too wide** vs a regression on (bank convexity duration, 3m GC/OIS); bank catch-up **$275mn/bp**; 3m vols +7.1/7.4/6.5/6.3 abp in 2/5/10/30y tails | `The_return_of_convexity….txt` PAGES 2-4 | transcribed-clean |
| T39 | 03-Jan-2017 | January spread seasonality | 5d-after: 10y **−3.0bp** (5y median) / **−2.1bp** (10y median); 30y −1.8 / −2.5 | `Corporate_supply….txt` PAGE 3 | transcribed-clean; full 12-row grid in §17 |
| T40 | 03-Jan-2017 | 10y-vs-30y spread | **y = 0.41x + 6.71, R² 0.65**; 10y **~2bp wide** | same | transcribed-clean |

**Rows deliberately NOT offered as tie-outs:** the 17-row ED CA table in `Left_side_vols` Figure 13 (extraction column-scrambled); the Renewed-Formosa trade-recommendation sizes (page never surfaced in extraction — structures named only); all bar/scatter exhibits whose values exist only as chart geometry (JPM Ex.7/8, Citi Fig 6/7).

---

## 20. SHORTLIST — 5 most implementable on USD SOFR, 2021-2026

Coverage claims below are **quoted from HANDOVER_PREFLIGHT.md, not re-measured in this session**: `USD-SOFR-1D` 2019-01-02→2026-08-12 (node-starved before 2019-07-08); swaption cube ATMF 97.8%, smile only from 2020-03-25; SR3 settles 2018-05→2026-08 but the deep strip is thin after 2022 (≥16 contracts: 246/246/53/19/2/1 days by year 2021→2026); JPM package panels 2019-08-26→2026-08-12.

### #1 — Citi `BE / realized vol` as a TWO-SIDED timing rule on long-dated forward curve pairs
**Structure:** the 15-pair grid — 10y10y/{15y15y,20y5y,20y10y,20y15y,25y5y,25y10y}, 15y5y/{20y5y,20y10y,20y15y,25y5y,25y10y}, 15y10y/{25y5y,25y10y}, 20y5y/{25y5y,25y10y}. DV01-neutral, optional beta scale 1.025-style, delta-hedge the **back leg** at 20-25bp.
**Signal:** `daily_BE / 1y-trailing daily realized vol of the BACK forward rate`; **enter flattener when low and carry ≥ 0 (ratio 0 ⇒ free convexity buy), exit flattener at ≈0.8; enter steepener when > 1.0 (observed 1.17-1.38), with a curve z-score-since-2000 screen on the other axis.**
**Why #1:** it is the **direct answer to the measured defect in strat 1 and strat 3** ("the signal is degenerate on the long end … a permanently-on flattener, not a timing rule"; `frac_always_cheap` 86.0/40.7/34.2%). This rule flips sign at a printed threshold and Citi documents four dated entries and exits across it (17-Jan-2020 enter, 26-Mar-2020 watch-list-not-enter, 05-Dec-2019 exit at 0.8, 12-Jun-2023 steepener at 1.17/1.38). It needs **only the swap curve** — no cube, no futures, no vendor vol — so it runs on the full 2019-2026 window at full density. Four published screens give **50 verifiable cells** for a known-answer test.
**Gotcha to encode:** back-leg vol keying (verified twice); BE truncation to 0 on positive carry; and the fact that the same metric has **opposite polarity** for the two sides.

### #2 — JPM RAC ranking + swap-implied/swaption-implied vol RATIO on ultra-long forward pairs
**Structure:** 20Y/40Yx10Y (JPM's cross-market winner in both USD and GBP), plus 30Y/50Y, 40Y/50Y, 20Y/40Y, 15Y/35Yx15Y, 25Y/20Yx5Y.
**Signals:** (a) `RAC = (3M carry+slide+convexity)/(3M daily bp vol·√252)`; (b) **swap-implied vol / 1Yx30Y ATMF swaption vol ratio** — the *ratio*, per the Feb-2020 Exhibit 3 definition, which is a **different and less saturated statistic than the cheap-share the codebase measured**.
**Why:** `RVUtils/ConvexityRV/{payoff,holee,swaption_cube}.py` already computes breakeven vol and expected payoff; this adds a ranking metric with a 4-row exact tie-out and two published hit rates (56%/86%). Cube ATMF at 97.8% covers 1Yx30Y for the whole window.
**Caveat to state up front:** the caption-vs-arithmetic conflict in the RAC definition (§18, RAC-2).

### #3 — Short SOFR pack convexity adjustment with Citi's explicit entry / carry / target / stop
**Structure:** long the pack (Blues or Golds) vs pay matched-maturity forward 1y **CME-cleared** swap, DV01-matched ($100K DV01 per the published ticket).
**Rules (all published):** entry on rich-vs-Ho-Lee **and** market-implied/realized vol ratio at the top of its multi-year range **and** higher 3m roll; **target 4bp of tightening, stop 3bp of widening**, carry +1.2bp/3M.
**Why:** this is strat 2 with the **missing exit discipline** supplied — the existing strat 2 book had no target/stop. Two dated CA screens (Jan-2019 ED 17 rows, Jun-2023 SOFR 13 rows) plus one full ticket.
**Hard constraint (measured, from handover):** SR3 settle depth ≥16 contracts exists on only **19 days in 2024, 2 in 2025, 1 in 2026**. **Blues/Golds are effectively unavailable after 2023 without a new settle warm.** Front packs (ranks 1-8) are intact ~250 days/year throughout — so the tradeable window for the *deep* version is 2021-2023, and the front version is available throughout but has 30.1% noise/CA-level vs 6.7% deep.
**Positioning proxy (Citi's own):** *"Asset Managers + Leveraged Funds, Net % of OI (inverted)"* vs `Blues CA − model`. **CFTC TFF availability in ARBS is NOT MEASURED** — the handover lists it as a wish-list item, not as an existing source.

### #4 — Beta-stability / traffic-light systematic fly RV, translated to USD SOFR
**Structure:** 50:50 DV01 flies made level-and-curve-neutral by rolling 6M regression; **Category 2 (5Y-tail, 5Y-gap forwards: 5Yx5Y/10Yx5Y/15Yx5Y … 35Yx5Y/40Yx5Y/45Yx5Y)** is the ultra-long block and the one JPM measures as **regime-robust**.
**Rules:** enter on R² ≥ 60% ∧ |resid| ≥ 4bp ∧ |z| ≥ 1.5; exit on **residual zero-cross (out-of-sample, ex-ante betas)** ∨ **+2SD worsening (3.5-4 z stop)** ∨ **1M elapsed**; stand down when **√(Zb²+Zw²) > 3**.
**Why:** the **only fully-specified systematic strategy in the corpus with a published performance grid to reproduce** (Exhibit 7: 12 triggers × 3 regimes × avg/success/max/min/n). It is curve-only, so it runs on the whole USD SOFR window. It also imports the codebase's own discipline (`lag it`, ex-ante betas, walk-forward-vs-full-sample) as a *requirement of the method*, not an afterthought.
**Explicit translation warning:** every published number is **EUR, 2001-2021**. A USD SOFR 2019-2026 run is a **translation of the method, not a reproduction of the result**; the EUR grid is a code tie-out for the *mechanics* only.
**Free bonus:** the traffic-light indicator directly addresses the handover's `pc1_neutral 5Y/30Y` finding (+1408bp walk-forward vs −66bp full-sample = *"that is the PCA moving, not a trade"*) — √(Zb²+Zw²) **is** a beta-instability detector, and it should be tested against exactly that case.

### #5 — 1×2×1 vol tenor fly + gamma-neutral forward-vol frontier on the swaption cube
**Structure A:** vega-neutral 1×2×1 vol fly, wings 2y and 30y tails, belly 5y or 10y, over expiries 1m…10y (published ticket: −$230mn 3y2y / +$100mn 3y10y / −$21mn 3y30y).
**Structure B:** gamma-neutral calendar spreads and triangles with **matching underlying mid-points**; `σ_fwd` from the exactly-verified triangular formula; rank on **1y z-score** (value) × **3m roll** (carry).
**Why:** needs **only ATMF from the swaption cube** (97.8% coverage; no smile ⇒ no strike dimension needed for either). It plugs straight into `RVUtils/ConvexityRV/swaption_cube.py::{load_vol_panel, atmf_vol_series}`. Two independent frontier snapshots (Jun-2021, Jun-2023) with 20 rows each provide a rank-order tie-out even where the Sharpe denominator is unknown; the **σ_fwd formula tie-out (106.1) is exact and mechanical**.
**Caveat:** the **ex-ante Sharpe denominator is not printed** (§18, RAC-3). Reproduce the *level* and the *ordering*, not the Sharpe. Cheap fair-value overlays available: curve-PCA regression (3 PCs, ZLB era 6/1/2008–1/1/2016 excluded per the 2019 note) and the level/slope regression of the fly.

### Explicitly NOT shortlisted, with the reason
- **EUR/GBP-specific books** (Euro Swaps ultra-long PCA fly, EUR 1Yx1Y/5Yx5Y/10Yx10Y fly, GBP 15y10y/25y10y): structures translate to USD but every published number is another currency and the ARBS USD-SOFR curve is the only measured coverage.
- **MBS / bank / VA / mREIT convexity-hedger flow models** (§15, 15b, 15c): the recipes are precise (20% bank-hedged share, 30bp IO strip for MSR, AGNC disclosure for REITs, $500mn/day 1Mx10Y program) but every input is a **new external source** (FNMA/FHLMC/GNMA pools, LCR disclosures, company filings, BrokerTec depth). **No ARBS coverage measured for any of them.** Highest-value single item if one source is added: the Jan-2020 fair-value regression `10y swap spread ~ f(bank convexity duration, 3m GC/OIS)`.
- **Corporate/Formosa supply seasonality** (§16, 17): the January seasonality table is directly testable against USD swap spreads, but the driver series (Dealogic issuance, redemption calendars, Bloomberg callable structures, TLAC shortfalls) are unmeasured in ARBS. The one *derived* proxy that is curve-only and buildable today is the **10s20s30s fly** as a stand-in for the ALM/20y bid (§8) and Citi's **2y30y vol vs 20y5y−10y10y spread** pair (§6, Fig 4).

---

## 21. FILES

- Documents: `C:/Users/chris/Downloads/convexityrv/` (PDFs), `C:/Users/chris/Downloads/convexityrv_markdown/` (.md conversions)
- Extracted text for the 11 un-converted priority PDFs: `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/txt/`
- Extractor: `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/extract.py`
- Prior context read (not modified): `C:/Users/chris/Downloads/convexityrv/HANDOVER_PREFLIGHT.md`; `C:/Users/chris/clee/ARBS-cvx2/docs/convexityrv/research/04-vollab-literature-map.md`; `C:/Users/chris/clee/ARBS-cvx2/RVUtils/ConvexityRV/` (18 modules)
- No repo files were created or modified.
