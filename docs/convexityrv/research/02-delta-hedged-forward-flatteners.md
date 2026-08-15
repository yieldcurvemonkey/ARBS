# DELTA-HEDGED LONG-DATED FORWARD FLATTENERS — COMPLETE TECHNICAL SPEC

**Sources (all four read in full; line refs are to the .md files):**

| # | File | Doc | Date | Substantive lines |
|---|---|---|---|---|
| A | `C:\Users\chris\Downloads\convexityrv_markdown\US Rates Vol Lab_ Trading long-dated convexity.pdf.md` | Citi *US Rates Vol Lab: Trading long-dated convexity* (Bikbov/Williams) | 09 May 2019 | 1–260 (strategy), 261–1210 (standing weekly monitors), 1211+ boilerplate |
| B | `...\20y10y_flatteners (1).pdf.md` | *Alert: Reweighting delta-hedged 15y5y/20y10y flatteners* | 16 Oct 2019 11:51:21 ET | 1–34; rest boilerplate |
| C | `...\20y10y_flatteners.pdf.md` | *Alert: Taking profits on delta-hedged 15y5y/20y10y flatteners* | 05 Dec 2019 14:52:26 ET | 1–53; rest boilerplate |
| D | `...\25y10y_flatteners.pdf.md` | *Alert: Taking profits on GBP 15y10y/25y10y flatteners* | 26 Mar 2020 10:38:21 ET | 1–20; rest boilerplate |

Cross-reference files (same series, explicitly cited by A–D; flagged as such throughout): `Rates_Vol_Lab_In_search_of_cheap_vol.pdf.md` (17 Jan 2020, GBP initiation), `Rates_Vol_Lab_Liquidity_vega_and_convexity.pdf.md` (30 Mar 2020), `Rates_Vol_Lab_Forward_steepener_and_vol_divergence.pdf.md` (12 Jun 2023, the short-vol mirror).

---

## 1. TRADE STRUCTURE AND NOTATION

### 1.1 Notation decode — quoted definition
Doc A, lines 40–41 (the only place the structure is defined explicitly):

> "consider 10y10y/20y10y curve flatteners, **structured by receiving 20y10y forward swaps vs paying 10y10y forward swaps, DV01-neutral**."

Therefore `AyBy` = **A-year forward start, B-year swap tail**. `20y10y` = 10y swap starting in 20y (spans 20y→30y). `15y5y` = 5y swap starting in 15y (15y→20y). The pair `X/Y` is written **shorter-dated leg / longer-dated leg**, and the quoted "curve, bp" is **rate(longer) − rate(shorter)**, which is normally negative (inverted long-end forward curve).

### 1.2 Leg direction for a FLATTENER
- **RECEIVE fixed on the longer leg** (20y10y / 25y10y) — the leg with more convexity.
- **PAY fixed on the shorter leg** (10y10y / 15y5y / 15y10y).
- Doc A line 46: "As a result, the 10y10y/20y10 flattener must be positively convex."
- Sign convention check (Doc A line 47): "The flattener **also rolls negatively** given that the term structure of long-dated forwards is normally inverted (Figure 1)."

### 1.3 The three live trades in these documents

| | USD trade | GBP trade |
|---|---|---|
| Structure | 15y5y/20y10y flattener (pay 15y5y, receive 20y10y) | 15y10y/25y10y flattener (pay 15y10y, receive 25y10y) |
| Size | **$50K DV01** (Doc C l.9) | **50K DV01** GBP (Doc D l.13) |
| Entry level | **−11.8bp** (Doc C l.9) | **−11.2bp** (cross-ref: *In search of cheap vol* l.181) |
| Entry date | 5/9/2019 (Doc C l.7) — Doc B l.13 says 5/10/2019 (see errata) | 1/17/2020, 12pm (cross-ref l.181) |
| Hedge trigger | **20bp** move in the 20y10y rate (Doc B l.15) | **25bp** move in the 25y10y rate (Doc D l.14) |
| Exit | 12/5/2019 2pm, curve −12.5bp | 3/26/2020 2pm |
| Result | **+$187K at mid; booked +$155K net transaction costs** (Doc C l.18, l.22) | **GBP 445K net transaction costs** (Doc D l.18) |

### 1.4 Full universe of pairs analysed
Doc A Figure 4/Figure 7/Figure 9 use 8 pairs: `10y5y/15y15y, 10y10y/15y15y, 10y10y/20y10y, 10y10y/20y15y, 10y10y/25y10y, 15y5y/20y10y, 15y5y/20y15y, 20y5y/25y10y`.
Docs B/C (and the Jan/Mar cross-refs) use a 15-pair grid: `10y10y/{15y15y, 20y5y, 20y10y, 20y15y, 25y5y, 25y10y}, 15y5y/{20y5y, 20y10y, 20y15y, 25y5y, 25y10y}, 15y10y/{25y5y, 25y10y}, 20y5y/{25y5y, 25y10y}`.

---

## 2. RISK WEIGHTING

### 2.1 Base rule: DV01-neutral
- Doc A l.41: "**DV01-neutral**".
- Doc A l.123: "We analyze a strategy where we **enter a DV01-neutral flattener rolled once a year**."
- Doc A l.126: "Although we initiate a DV01-neu[t]ral flattener, **DV01 risks change as the market moves**."
- Cross-ref (*In search of cheap vol* l.182): "adjusting the longer leg of the trade **for DV01 neutral** at each 25bp move".

### 2.2 Actual notionals observed (tie-out for DV01 ratio)
Doc B l.16: "The current nationals are **$149.5mn and $81.97 [mn]** for 15y5y and 25y10y [*sic* — read 20y10y], respectively".

Derived from those numbers at $50K DV01:
- DV01 per $1mn of 15y5y = 50,000 / 149.5 = **$334.4 /mn**
- DV01 per $1mn of 20y10y = 50,000 / 81.97 = **$610.0 /mn**
- Notional ratio 15y5y : 20y10y = **1.824 : 1**

### 2.3 Beta re-weighting (the one deviation from pure DV01-neutral)
Doc B, lines 26–32 (verbatim):

> "However, the curve has developed a notable directionality with rates over the last few months (steepening in rallies and flattening in selloffs), which likely reflects insurance flows and introduces undesirable volatility to our P&L. We still like the trade but we prefer to reweight it using the **empirical beta of 1.025 between 15y5y and 20y10y rates**. We increase the notional of the 20y10y from **$81.97mn to $84mn** and will continue delta-hedging this leg at each 20bp **with the same beta (i.e. scaling the DV01-neutral notional up by 1.025)**."

Tie-out: 81.97 × 1.025 = **84.02** ✓. Post-reweight rule: `N_long = 1.025 × N_long^{DV01-neutral}`.

---

## 3. WHY FLATTENER = LONG VOL / LONG CONVEXITY

### 3.1 The mechanism — verbatim (Doc A, lines 39–52)

> "At that long horizons, expectations of monetary policy should flatten out, so the curve should be mostly determined by convexity adjustments, term premiums and technical factors. **Because convexity is higher at longer maturities, the 20y10y forward should have a greater convexity per a unit of DV01 than 10y10y. As a result, the 10y10y/20y10 flattener must be positively convex.**
> The flattener also rolls negatively given that the term structure of long-dated forwards is normally inverted (Figure 1). From that point of view, **the risk profile of this trade is similar to that of long swaption straddles. In that analogy, the spread between 10y10y and 20y10y rates is akin to implied volatility, i.e. the vega exposure of the trade.** Indeed, the 10y10y/20y10y curve is highly correlated empirically with implied rates vol (the higher the vol, the more inverted the curve is; Figure 2)."

**Figure 2 regression (the vega/implied-vol linkage), Doc A lines 55–70:**
`y = -0.5x + 19.0`, `R² = 0.5`, where y = 10y10y/20y10y curve (bp), x = 2y10y vol (normals). Sample **1/4/2010–5/3/2019**. Axes: vol 40→160 normals, curve 0→−60bp.

Interpretation: **d(curve)/d(vol) = −0.5 bp per normal**. A $50K DV01 flattener therefore carries roughly **$25K of P&L per 1 normal** of 2y10y vol as its vega-equivalent exposure (derived from the quoted slope, not stated by Citi).

### 3.2 Why the embedded convexity is cheap vs options (Doc A lines 79–100, verbatim)

> "This may be counterintuitive given the options analogy, since implied option vols typically exceed realized vols. Still, we think there are good reasons why this may be the case. **Most importantly, curve flatteners do not offer positive convexity in the same clean way as options and therefore can be less attractive for convexity buyers. Indeed, unlike options, a curve flattener trade doesn't have a well-defined downside. Also, the flattener is difficult to use as a terminal trade. Convexity exposure declines while the volatility of the curve increases as the trade ages. As a result, the trade needs to be closed a few years after initiation, at which point an investor would realize any curve P&L (i.e. effectively the vega risk). In contrast, the vega risk is not relevant for the terminal P&L of options. Finally, we believe that life insurance flows may keep very long-dated curves structurally steep. This is because the duration of variable annuity portfolios is known to be concentrated in the 15-25y buckets.** Structural receiving from insurance may therefore steepen the curve beyond 20y above the fair value."

### 3.3 Gamma / convexity profile in bp per bp² — **NOT QUOTED ANYWHERE IN THESE FOUR DOCUMENTS**
Citi never publishes a Γ in bp/bp². It publishes only `1y carry` and `daily BE`. However Γ is **exactly invertible** from those two published rows (see §11 for the derivation and its verification). The result:

**Γ (net convexity, in bp-of-curve P&L per bp² of parallel shift, per unit of trade DV01) ≈ ΔM / 10,000, where ΔM = M_long − M_short and M = (forward start) + (tail/2) = mid-point maturity of the forward swap.**

| Pair | ΔM theory (y) | ΔM implied from Dec-19 USD carry & BE | Γ (bp/bp²) | $ convexity @ $50K DV01 |
|---|---|---|---|---|
| 10y10y/15y15y | 7.5 | 7.39 | 7.5e-4 | $37.5/bp² |
| 10y10y/20y5y | 7.5 | 7.74 | 7.5e-4 | $37.5/bp² |
| 10y10y/20y10y | 10.0 | 10.15 | 1.00e-3 | $50/bp² |
| 10y10y/20y15y | 12.5 | 12.51 | 1.25e-3 | $62.5/bp² |
| 10y10y/25y5y | 12.5 | 12.81 | 1.25e-3 | $62.5/bp² |
| 10y10y/25y10y | 15.0 | 15.18 | 1.50e-3 | $75/bp² |
| 15y5y/20y5y | 5.0 | 5.10 | 5.0e-4 | $25/bp² |
| **15y5y/20y10y** | **7.5** | **7.48** | **7.5e-4** | **$37.5/bp²** |
| 15y5y/20y15y | 10.0 | 9.86 | 1.00e-3 | $50/bp² |
| 15y5y/25y5y | 10.0 | 10.18 | 1.00e-3 | $50/bp² |
| 15y5y/25y10y | 12.5 | 12.55 | 1.25e-3 | $62.5/bp² |
| 15y10y/25y5y | 7.5 | 7.80 | 7.5e-4 | $37.5/bp² |
| **15y10y/25y10y** | **10.0** | **10.08** | **1.00e-3** | **$50/bp²** |

Mean |error| ≈ 2%. The implied ΔM is stable across **four separate publication dates and five currencies** (see §11.3), which is what validates the reconstruction.

### 3.4 Long-vol evidence quoted (Doc A lines 142–161)
> "Although the Sharpe does not look very high, it is important to note that **this strategy is structurally long volatility** unlike some popular systematic carry trades, such as short gamma, monetizing term premium etc. Figure 5 shows that **the trade tended to outperform during large spikes in volatility. The correlation of monthly P&L with the monthly changes in the 1y10y vol is about 26%.** For the same reason, the distribution of daily P&L does not exhibit a significant negative tail (Figure 6). In fact, **the skewness of daily P&L is about 0.** In comparison, the popular strategy of systematically selling delta-hedged 1m10y straddles has a higher **Sharpe of about 0.84, but also an extreme skewness of the P&L of about -3**".

Doc A lines 189–193:
> "Despite the long vol bias, the strategy has outperformed even though implied vols have declined over our historical sample (Figure 5). The performance of the strategy has been largely flat since 2013 even though **the 1y10y vol has declined by about 50 normals** over the same time period (Figure 5). This reflects the cheapness of the embedded convexity relative to typical realized volatility."

---

## 4. DELTA HEDGING — the "delta hedge the forward curve" methodology

### 4.1 What the delta is
The trade is initiated DV01-neutral, but **DV01 drifts as rates move because the long leg has more convexity**: "Although we initiate a DV01-neu[t]ral flattener, **DV01 risks change as the market moves. We therefore delta-hedge the trade by adjusting the notional on the longer leg at each 25bp move in rates.**" (Doc A lines 126–128). The residual delta is outright duration; a receive-long-leg flattener gets **longer duration in a rally / shorter in a selloff**? — no: the long (received) leg's DV01 grows faster as rates fall, so the net position becomes **net-received (long duration) in rallies and net-paid (short duration) in selloffs** → the classic positive-gamma profile monetised by re-flattening the notional back to DV01-neutral.

### 4.2 The three hedging variants (they differ — a reimplementer must pick one)

| | Backtest (Doc A) | USD live pre-reweight (Doc C) | USD live post-reweight (Doc B) | GBP live (Doc D + cross-ref) |
|---|---|---|---|---|
| Trigger | **25bp move in the longer rate** | **20bp move in rates** | **20bp** | **25bp move in the 25y10y rate** |
| Observation | **at market close** | (not stated) | (not stated) | (not stated) |
| Instrument adjusted | **notional of the initial off-market swap** on the longer leg | longer leg | longer leg | longer leg |
| Target | DV01-neutral | DV01-neutral | **DV01-neutral × 1.025** | DV01-neutral |
| Roll | **rolled every year** | n/a (closed) | n/a | n/a |

Verbatim, Doc A lines 115–117 (Figure 4 note):
> "For each pair of forward rates, **we enter $100K DV01 of flatteners, rolled every year. We delta-hedge by adjusting the notional on the longer end of the trade at each 25bp move in the longer rate (at market close).**"

Verbatim, Doc A lines 129–139 (threshold choice):
> "**The 25bp threshold for delta-hedging was chosen as a trade-off between the accuracy of hedging and transaction costs. Delta hedging too frequently increases transaction costs, while hedging too infrequently increases the volatility of the P&L resulting in a smaller Sharpe** (a similar trade-off exists in systematic gamma selling strategies; see for US Rates Vol Lab: The art of gamma hedging details). With our transaction costs assumptions, detailed in the Appendix, **we have found that the Sharpe ratio of the strategy doesn't change significantly if the threshold is chosen in the 15-30bp range, but declines with a smaller or larger threshold. To simplify our historical analysis, we adjust the notional of the initial off-market swap, although delta-hedging with ATM swaps may be easier for the practical implementation of this strategy.**"

Doc A line 232: "As discussed above, **the trade needs to be hedged at every 15-30bp move in rates.**"
Cross-ref (*In search of cheap vol* l.183–185): "**We have previously found that hedging at 20-25bp offers an attractive balance between the accuracy of hedging and transaction costs** (US Rates Vol Lab: Trading long-dated convexity)."

**No time-based rehedge, no delta band in %, no intraday rule** — the trigger is purely a **level band on the longer forward rate**, evaluated at close.

### 4.3 Transaction costs — Doc A Figure 9 (one way, mid-to-offer / mid-to-bid, bp)

| curve | 10y5y/15y15y | 10y10y/15y15y | 10y10y/20y10y | 10y10y/20y15y | 10y10y/25y10y | 15y5y/20y10y | 15y5y/20y15y | 20y5y/25y10y |
|---|---|---|---|---|---|---|---|---|
| initiation | 0.75 | 0.75 | 0.75 | 1 | 1 | 0.75 | 1 | 1 |
| delta-hedging and roll | 0.3 | 0.3 | 0.3 | 0.4 | 0.4 | 0.3 | 0.4 | 0.4 |

Doc A lines 246–252 (rationale):
> "In Figure 9 we show our bid/offer assumptions for 1) **initiating $100K DV01-neutral flatteners** and 2) **delta-hedging by adjusting the longer leg of the trade**. While the market is quite wide for initiating flatteners of this size, **delta hedging at each 25bp normally requires adjusting only a small size and therefore can be done at much tighter levels.** Similarly, rolling the trade entails less risk for a dealer and can normally be executed at tighter levels. **We assume the same bid/offer for the roll as for delta-hedging.**"

Realised cost check: USD trade $187K gross at mid → $155K booked net ⇒ **~$32K all-in costs** on $50K DV01 over ~7 months incl. the reweight.

---

## 5. CARRY / ROLLDOWN

### 5.1 Definition
- Qualitative, Doc A l.47: "The flattener also **rolls negatively given that the term structure of long-dated forwards is normally inverted** (Figure 1)."
- Reported metric label (Docs B/C/A tables): **"1y carry, bp"** — carry+rolldown of the curve spread over a 1-year horizon, in bp of the curve.
- **The computational formula is never stated in these four documents.** Standard-and-consistent inference (mark as inferred): `carry_1y = curve(t+1y, same forward tenors slid 1y) − curve(t)` under an unchanged spot curve, i.e. the 1y rolldown of the spread; the sign convention is that a negative number costs the flattener money.
- Sibling notes describe the same field as "**negative daily roll**" in the BE definition, confirming carry ≡ roll here.

### 5.2 Quoted carry numbers (USD 15y5y/20y10y through the trade's life)

| Date / source | 1y carry (bp) | daily BE (bp) | 1y realized vol (bp) | BE/rv |
|---|---|---|---|---|
| 5/8/2019 close — Doc A Fig 7 | **−0.31** (text says −0.44, see errata) | 1.3 | 3.0 | 0.42 |
| 12/4/2019 close — Doc C Fig 1 | **−2.09** | 3.33 | 4.16 | **0.80** |
| 1/16/2020 close — *In search of cheap vol* Fig 11 | −2.20 | 3.41 | 4.27 | 0.80 |
| 3/26/2020 3pm — *Liquidity, vega and convexity* Fig 9 | **+0.11** | 0.00 | 6.40 | 0.00 |

Doc C lines 18–22 (exit rationale, verbatim):
> "However, **the carry on the trade has worsened recently to as low as -2bp/year.** The ratio of the daily breakeven (the daily move in rates that yields a convexity gain offsetting a negative daily carry) to realized daily volatility has increased to **just 0.8** (Figure 1). As a result, we prefer closing this trade at this time."

Doc A lines 228–231 (entry rationale, verbatim):
> "The 15y5y/20y10y curve is trading at the upper bound of its historical range (Figure 8). **While the trade carries negatively by about -0.44bp per year, this negative carry is offset by just 1.3bp of daily volatility. In comparison, the daily volatility of the 20y10y rate has realized at 3bp and 2.8bp in the last year and the last three months, respectively.**"

GBP carry (cross-ref, *In search of cheap vol* l.179–181): "**the 15y10y/25y10y flatteners also carry positively by about 0.5bp over 1y. As a result, the flatteners offer an effectively free convexity buy.**" (Fig 11 GBP col: **+0.52**.)

---

## 6. BREAKEVEN ANALYSIS

### 6.1 Definition — verbatim (Doc A lines 71–78 and Figure 3 note l.115–116)

> "Long-dated curve flatteners can therefore be used to buy convexity, but how cheap is the embedded vol? One way to answer this question is to **calculate implied daily rates breakeven, i.e. a parallel shift in rates that yields a convexity gain offsetting the negative daily roll.** It turns out the daily breakeven calculated this way is typically small relative to realized vol. For example, the daily breakeven for the 10y10y/20y10y flattener has been consistently above the realized vol of corresponding forward rates (Figure 3; **zero breakeven in the Figure 3 corresponds to episodes where the roll was positive**)."

Figure 3 note: "**The daily rates breakeven is a parallel shift in rates that yields a convexity gain offsetting the negative daily roll. When the roll is positive, the breakeven is zero.**"

Table footnote convention (Doc C l.51–53, identical in Jan/Mar notes): "We also report 1y carry, **daily breakeven (zero if carry is positive)**, and the ratio of the daily breakeven to realized vol."

### 6.2 The formula (reconstructed; verified in §11)
```
BE_daily(bp) = 0                                   if carry_1y >= 0
BE_daily(bp) = sqrt( |carry_1y| / (N * Γ) )        otherwise
Γ  = ΔM / 10000        [bp of curve-P&L per bp², per unit trade DV01]
ΔM = M_long - M_short,  M = fwd_start + tail/2
N  ≈ 252 business days
```
Equivalently, `Γ · BE² = |carry_1y| / N` (daily roll). Reproduces every published BE across four dates and five currencies to ~1–2%.

### 6.3 The decision statistic
`BE / (1y realized vol)` where **the realized vol is that of the LONGER forward rate**, not of the curve. Verified two ways:
- Doc A Figure 3 chart legend: "daily breakeven of the 10y10y/20y10y flattener" vs "**1y realized vol of 20y10y**".
- Every table: the "1y realized vol" row is identical for all pairs sharing a longer leg (e.g. Dec-19 USD: 20y10y → 4.16 for both 10y10y/20y10y and 15y5y/20y10y; 25y10y → 4.13 for all four pairs ending in 25y10y).

**Rule (quoted, cross-ref *In search of cheap vol* l.208–211):** "the ratio of the daily breakeven ... to realized daily vol of the underlying rates (**a smaller ratio indicates the cheapness of the embedded convexity and therefore a more attractive trade**)."

---

## 7. IMPLIED VOL FROM THE CURVE vs SWAPTION VOL

**There is no direct "imply a vol number from the curve and compare to the swaption grid" calculation in these four documents.** State this as a gap. The three nearest artifacts:

1. **BE/realized-vol ratio** (§6) — the note's own substitute for an implied-vs-realized comparison. Doc A l.74–77: "the daily breakeven calculated this way is typically small relative to realized vol ... has been **consistently above** the realized vol of corresponding forward rates" (note: the Figure 3 title reads "Realized vol has typically exceed[ed] the implied daily breakeven", i.e. BE < realized vol — the body text sentence is inverted; see errata).
2. **Curve↔vol regression** (Doc A Fig 2): `curve = −0.5 × (2y10y vol, normals) + 19.0`, R²=0.5, sample 1/4/2010–5/3/2019. Inverting gives an "implied 2y10y vol from the curve": `vol_implied = (19.0 − curve_bp)/0.5`. At curve = −11.3bp → 60.6 normals; the actual 5/8/2019 2y10y ATM vol from Doc A Figure 10 is **66.8 normals** → the curve was "cheap" (too steep) by ~6 normals on this regression. *(Inversion and the 66.8 lookup are derived, not quoted.)*
3. **Eurodollar convexity adjustment** (Doc A Fig 60, l.907–909) uses a genuine implied-vol-from-convexity method, but for a **different instrument**: "The model for convexity adjustment is the **Ho-Lee model calibrated to cap/floor vols. Implied vol is calculated by matching the model to the observed convexity adjustment.** Realized vol is 3m realized vol of the corresponding pack."

---

## 8. ENTRY / EXIT SIGNALS, VALUATION METRICS, Z-SCORES

### 8.1 The screen (identical in Docs A/C and the Jan/Mar cross-refs)
Per curve pair: **level (bp)**, **1y z-score**, **3y z-score**, **z-score since 2000** (full sample), **1y carry (bp)**, **daily BE (bp)**, **1y realized vol (bp)**, **BE/realized vol**. "**Three most attractive curves by each metric are marked in red.**" (Doc C l.52–53).
- Doc A Fig 7 reports only 1y ZS and 3y ZS (no since-2000 column); Docs B/C-era tables add the since-2000 column.
- z-scores are of the **curve level**, computed on 1y / 3y / since-2000 windows. A **high positive z-score = steep = attractive flattener entry**.

### 8.2 Entry signal, quoted (Doc A lines 194–203, 228–229)
> "We believe the current environment is especially favorable for initiating delta-hedged curve flatteners. As discussed in US Rates Vol Lab: Vol cycle, steepeners, and SOFR, **we believe rates vol is likely to see a cyclical turn higher in the next 6m-1y. At the same time, long-dated forward curves have steepened as a result of the recent decline in rates volatilities.** In Figure 7 we evaluate a number of different flatteners **by simple z-scores, carry, and implied daily breakeven. The last three trades look especially attractive on these metrics. We like the 15y5y/20y10y flattener in particular because it has a somewhat tighter market than the other two trades (15y5y/20y15y and 20y5y/25y10y).**"
> "**The 15y5y/20y10y curve is trading at the upper bound of its historical range** (Figure 8)."

Figure 8 axis (Doc A l.212–221): 15y5y/20y10y curve, **+20 to −100bp, Jan-02 → Jan-17+**.

### 8.3 Exit signal, quoted (Doc C lines 16–25)
> "Our views have been largely realized. While the curve has been little changed (at **-12.5bp at mid as of 2pm on 12/5/2019**), increased realized volatility has generated the P&L of about **$187K at mid**. However, the carry on the trade has worsened recently to as low as **-2bp/year**. The ratio of the daily breakeven ... to realized daily volatility has increased to **just 0.8** (Figure 1). As a result, we prefer closing this trade at this time. We book **+$155K profits net transaction costs**. More attractive delta-hedged flatteners can now be found in GBP swaps. For example, the **15y10[y]/25y5y GBP curve is trading at the upper bound of the historical range and carries positively** (Figure 1). We add this trade to our watch list but don't initiate it yet."

GBP exit (Doc D lines 13–20):
> "We were motivated by the **steepness of the curve, positive convexity, and attractive carry. The curve has flattened recently, driven by an aggressive QE, but we see a risk of re-steepening on supply.** We therefore prefer to close the trade at this time for a profit of GBP 445K, net transaction costs."

**Operational thresholds implied by the two exits:** exit when (a) carry deteriorates to ≈ −2bp/yr, AND (b) **BE/realized vol rises to ≈ 0.8**, or (c) the thesis (curve steepness / vol view) is spent. Entry was taken at BE/rv ≈ 0.42–0.45 with a top-of-range z-score.

### 8.4 Risk flags, quoted (Doc A lines 234–244)
> "One risk to this trade is **variable annuity hedging flows in a risk-off scenario** ... the duration of variable annuities extends when stocks underperform, so that insurance firms would typically need to receive in the ~20y sector in that scenario. Indeed, there exists a **small negative correlation between stock returns and the 15y5y/20y10y curve of about -23%** in the data (lower stocks leading to a steeper curve). However, we would also expect rates volatility to increase in that scenario, which should be positive for the gamma part of the trade P&L. In fact, there is little empirical correlation between the P&L of the trade and stock market performance (**the correlation between monthly P&L of delta-hedged 15y5y/20y10y flatteners and monthly S&P returns has been close to 0** in our historical sample)."

---

## 9. P&L ATTRIBUTION FRAMEWORK

**Only a two-bucket attribution is given, and only for the GBP trade** (Doc D lines 18–20):

> "we prefer to close the trade at this time for a profit of **GBP 445K, net transaction costs (about 115K from the curve move and 330K from convexity**; pricing as of 2pm on 3/26/2020)."

⇒ **P&L = curve-move (vega-like) P&L + convexity (gamma) P&L − transaction costs.**
- Curve component ≈ `DV01 × Δcurve`: 115,000 / 50,000 = **2.3bp of flattening** from −11.2bp entry.
- Convexity component GBP **330K** — i.e. **74% of gross P&L from delta-hedging gamma**, on a trade held ~2.3 months across the Covid vol shock.

USD trade (Docs B/C) gives only running totals, not a decomposition:
- 10/16/2019: "the current MTM on the trade is **+$105K**. **Elevated realized volatility has helped the performance of the trade even though the 15y5y/20y10y curve has steepened by about 2bp since initiation**" (Doc B l.17–19) ⇒ curve component ≈ −$100K (2bp steepening × 50K DV01), so convexity ≈ +$205K by mid-October — **the P&L was convexity-dominated with a negative curve leg**.
- 12/5/2019: curve −12.5 vs entry −11.8 ⇒ curve component ≈ **+$35K**; residual ≈ **+$152K convexity** (derived, not quoted). Booked **$155K** net.

**Carry** is not broken out separately; it is embedded in the curve/roll term (the "1y carry" screen metric is ex-ante, not a realised P&L bucket).

---

## 10. NUMERIC EXHIBITS — VERBATIM TIE-OUT TABLES

*Scope note: item 10 is scoped to the flattener-relevant exhibits. Doc A additionally contains ~55 standing weekly-monitor exhibits (Figs 10–67: ATM vol grid & z-scores, macro-vol/PCA rich-cheap, implied-vs-realized, intraday hedging-hour vols, expiry/tail switches, forward vols and the forward-vol efficient frontier, callable/Formosa supply, swaption skew and SABR "realized skew", Board/swaption RV and conditional spread trades, midcurves, CMS curve options, ED convexity adjustments, conditional curves and conditional flies). Ask if any of those are needed.*

### Figure 4 (Doc A) — Systematically delta-hedged flatteners, historical performance
Note: "For each pair of forward rates, we enter **$100K DV01** of flatteners, rolled every year. We delta-hedge by adjusting the notional on the longer end of the trade at each 25bp move in the longer rate (at market close). Transaction costs assumptions can be found in the Appendix. **Sample: 12/31/2013-5/7/2019.**"

| metric | 10y5y/15y15y | 10y10y/15y15y | 10y10y/20y10y | 10y10y/20y15y | 10y10y/25y10y | 15y5y/20y10y | 15y5y/20y15y | 20y5y/25y10y |
|---|---|---|---|---|---|---|---|---|
| avg daily return, $K | 0.67 | 1.15 | 2.28 | 3.20 | **5.40** | 2.92 | 3.79 | 4.09 |
| daily vol of the P&L, $K | 195.3 | 142.4 | 222.1 | 208.5 | 247.6 | 251.5 | 241.7 | 219.3 |
| Sharpe | 0.05 | 0.13 | 0.16 | 0.24 | **0.35** | 0.18 | 0.25 | 0.30 |

**Verified tie-out (derived):** Sharpe = avg daily / daily vol × √252, exact to 2dp for all 8 columns (e.g. 5.40/247.6×15.875 = 0.346 → 0.35). So the reported Sharpe is **annualised, 252-day, gross of financing, net of the stated transaction costs**.

### Figure 7 (Doc A) — Entry screen, close of 5/8/2019 (USD)

| pair | curve (bp) | 1y ZS | 3y ZS | 1y carry (bp) | daily BE (bp) | 1y rlzd vol (bp) | BE/rv |
|---|---|---|---|---|---|---|---|
| 10y5y/15y15y | −10.1 | 2.50 | 0.19 | −2.91 | 3.5 | 3.2 | 1.07 |
| 10y10y/15y15y | −8.8 | 2.15 | 0.39 | −1.64 | 3.0 | 3.2 | 0.94 |
| 10y10y/20y10y | −13.2 | 1.87 | 0.53 | −1.75 | 2.6 | 3.1 | 0.84 |
| 10y10y/20y15y | −16.7 | 2.41 | 0.50 | −1.88 | 2.5 | 3.1 | 0.79 |
| 10y10y/25y10y | −20.1 | 2.38 | 0.55 | −1.83 | 2.2 | 3.0 | 0.72 |
| **15y5y/20y10y** | **−11.3** | 1.16 | 1.01 | **−0.31** | **1.3** | 3.0 | **0.42** |
| 15y5y/20y15y | −15.2 | 1.62 | 0.99 | −0.44 | 1.3 | 3.0 | 0.45 |
| 20y5y/25y10y | −9.1 | 1.95 | 0.87 | +0.13 | 0.0 | 3.0 | 0.00 |

### Figure 1 (Doc C) — Close of 12/4/2019, USD

| pair | curve (bp) | 1y ZS | 3y ZS | ZS since 2000 | 1y carry (bp) | daily BE (bp) | 1y rlzd vol (bp) | BE/rv |
|---|---|---|---|---|---|---|---|---|
| 10y10y/15y15y | −6.77 | 0.55 | 1.38 | 1.08 | −3.19 | 4.14 | 4.22 | 0.98 |
| 10y10y/20y5y | −7.97 | 0.68 | 1.48 | 1.03 | −4.16 | 4.62 | 4.23 | 1.09 |
| 10y10y/20y10y | −11.33 | 0.43 | 1.28 | 0.97 | −3.95 | 3.93 | 4.16 | 0.95 |
| 10y10y/20y15y | −14.90 | 0.46 | 1.28 | 0.95 | −3.95 | 3.54 | 4.17 | 0.85 |
| 10y10y/25y5y | −14.99 | 0.13 | 1.07 | 0.80 | −3.73 | 3.40 | 4.08 | 0.83 |
| 10y10y/25y10y | −18.83 | 0.37 | 1.20 | 0.80 | −3.82 | 3.16 | 4.13 | 0.77 |
| 15y5y/20y5y | −9.18 | 0.12 | 0.98 | 0.71 | −2.30 | 4.23 | 4.23 | 1.00 |
| **15y5y/20y10y** | **−12.54** | −0.91 | 0.70 | 0.64 | **−2.09** | **3.33** | 4.16 | **0.80** |
| 15y5y/20y15y | −16.11 | −0.37 | 0.76 | 0.62 | −2.09 | 2.90 | 4.17 | 0.70 |
| 15y5y/25y5y | −16.20 | −1.65 | 0.52 | 0.49 | −1.87 | 2.70 | 4.08 | 0.66 |
| 15y5y/25y10y | −20.04 | −0.42 | 0.70 | 0.50 | −1.96 | 2.49 | 4.13 | 0.60 |
| 15y10y/25y5y | −11.82 | −2.08 | 0.38 | 0.27 | −0.77 | 1.98 | 4.08 | 0.49 |
| 15y10y/25y10y | −15.65 | −0.54 | 0.58 | 0.25 | −0.86 | 1.84 | 4.13 | 0.45 |
| 20y5y/25y5y | −7.02 | −2.22 | 0.02 | −0.33 | +0.43 | 0.00 | 4.08 | 0.00 |
| 20y5y/25y10y | −10.85 | −0.89 | 0.13 | −0.29 | +0.34 | 0.00 | 4.13 | 0.00 |

### Figure 1 (Doc C) — Close of 12/4/2019, GBP

| pair | curve (bp) | 1y ZS | 3y ZS | ZS since 2000 | 1y carry (bp) | daily BE (bp) | 1y rlzd vol (bp) | BE/rv |
|---|---|---|---|---|---|---|---|---|
| 10y10y/15y15y | −7.25 | 0.40 | 1.28 | 1.27 | −1.93 | 3.21 | 4.29 | 0.75 |
| 10y10y/20y5y | −8.86 | 0.35 | 1.22 | 1.20 | −2.45 | 3.57 | 4.26 | 0.84 |
| 10y10y/20y10y | −10.12 | 0.50 | 1.33 | 1.36 | −2.02 | 2.82 | 4.30 | 0.66 |
| 10y10y/20y15y | −11.60 | 0.50 | 1.36 | 1.53 | −1.92 | 2.47 | 4.21 | 0.59 |
| 10y10y/25y5y | −11.43 | 0.59 | 1.41 | 1.51 | −1.56 | 2.22 | 4.34 | 0.51 |
| 10y10y/25y10y | −13.05 | 0.53 | 1.40 | 1.69 | −1.64 | 2.07 | 4.18 | 0.50 |
| 15y5y/20y5y | −7.01 | 0.60 | 1.32 | 1.34 | −0.68 | 2.31 | 4.26 | 0.54 |
| 15y5y/20y10y | −8.27 | 0.70 | 1.44 | 1.61 | −0.24 | 1.13 | 4.30 | 0.26 |
| 15y5y/20y15y | −9.74 | 0.64 | 1.44 | 1.85 | −0.14 | 0.76 | 4.21 | 0.18 |
| 15y5y/25y5y | −9.57 | 0.75 | 1.52 | 1.78 | +0.21 | 0.00 | 4.34 | 0.00 |
| 15y5y/25y10y | −11.19 | 0.64 | 1.47 | 2.00 | +0.14 | 0.00 | 4.18 | 0.00 |
| **15y10y/25y5y** (the flagged trade) | **−6.14** | 0.78 | 1.61 | **1.86** | **+0.54** | 0.00 | 4.34 | 0.00 |
| 15y10y/25y10y | −7.76 | 0.65 | 1.51 | **2.05** | +0.47 | 0.00 | 4.18 | 0.00 |
| 20y5y/25y5y | −2.56 | 0.82 | 1.77 | 1.53 | +0.89 | 0.00 | 4.34 | 0.00 |
| 20y5y/25y10y | −4.18 | 0.64 | 1.56 | 1.54 | +0.82 | 0.00 | 4.18 | 0.00 |

### Chart-axis facts (Doc A)
- **Fig 1** "Very long-dated forward curve is normally inverted due to convexity": 10y10y/20y10y swap curve, axis +10 → −90bp, **Dec-03 → Dec-18**.
- **Fig 2**: scatter, x = 2y10y vol 40→160 normals, y = curve 0→−60bp; `y = −0.5x + 19.0`, `R² = 0.5`; **sample 1/4/2010–5/3/2019**.
- **Fig 3**: "daily breakeven of the 10y10y/20y10y flattener" vs "1y realized vol of 20y10y", 0→12bp, **Dec-03 → Dec-18**.
- **Fig 5**: cumulative P&L of delta-hedged 10y10y/25y10y flatteners (LHS, −5 → $25mn) vs 1y10y vol (RHS, 40 → 200 normals), Dec-03 → Dec-18.
- **Fig 6**: histogram of daily P&L of delta-hedged 10y10y/25y10y flatteners, −1.0 → +1.0 $mn, frequency 0 → 0.35. Sample 12/31/2013–5/7/2019.
- **Fig 8**: 15y5y/20y10y curve, +20 → −100bp, Jan-02 → Jan-17+.

---

## 11. DERIVED (NOT QUOTED) — reconstruction of the pricing engine

Everything in this section is **my derivation**, verified against Citi's published numbers; Citi states none of it.

### 11.1 P&L decomposition assumed
```
dPnL/DV01_$  =  Δcurve_bp                       (curve / "vega" term)
              + Γ · (Δy_parallel_bp)²           (convexity / gamma term)
              − carry_1y_bp · dt/252            (roll)
Γ  =  ΔM / 10000     [bp per bp²],   ΔM = M_long − M_short,   M = start + tail/2
```

### 11.2 Breakeven inversion
`Γ · BE² = carry_1y / 252` ⇒ `BE = sqrt(10000 · carry_1y / (252 · ΔM))`, floored at 0 when carry ≥ 0.

### 11.3 Verification (this is what makes the reconstruction trustworthy)
Implied `ΔM = 10000·carry_1y/(252·BE²)` computed from four independent publication dates and five currencies:

| pair | ΔM theory | Dec-19 USD | Mar-20 USD | Jan-20 USD | Dec-19 GBP |
|---|---|---|---|---|---|
| 10y10y/15y15y | 7.5 | 7.39 | 7.59 | 7.39 | 7.43 |
| 10y10y/20y10y | 10.0 | 10.15 | 9.92 | — | 10.06 |
| 10y10y/25y10y | 15.0 | 15.18 | 15.20 | — | 15.05 |
| 15y5y/20y5y | 5.0 | 5.10 | 5.06 | — | 5.06 |
| 15y5y/20y10y | 7.5 | 7.48 | n/a (carry>0) | 7.51 | 7.45 |
| 15y5y/25y10y | 12.5 | 12.55 | 12.54 | — | n/a |
| 15y10y/25y10y | 10.0 | 10.08 | 10.16 | — | n/a |

Also verified: **BE = 0 exactly and only where carry ≥ 0**, column-by-column, in every table (e.g. Mar-20 USD: carry >0 in cols 5, 8, 10, 12, 14 → BE 0.00 in precisely those five).

### 11.4 Sanity-check on the $ gamma
$50K DV01 15y5y/20y10y ⇒ **net dollar convexity ≈ $37.5 per bp²**, i.e. the net DV01 drifts ≈ **$37.5 per 1bp parallel move** (0.075% of gross DV01/bp). At the 20bp hedge trigger, the accumulated delta at rehedge is ≈ **$750 DV01**, i.e. ≈ **$1.2mn notional of 20y10y** to re-square — consistent with Citi's "delta hedging at each 25bp normally requires adjusting only a small size and therefore can be done at much tighter levels."

### 11.5 Expected gamma P&L per rehedge (for backtest calibration)
Per completed ±h bp round trip: `PnL ≈ DV01 × Γ × h²`. For $50K DV01, 15y5y/20y10y, h = 20bp: `50,000 × 0.00075 × 400` → **≈ $15K per 20bp round trip** (order of magnitude; exact figure depends on the ½Γ convention chosen — see §11.6).

### 11.6 Convention caveat
The published BE is consistent with `Γ·Δy²` (no ½) using ΔM/10000 and N=252 — equivalently with `½Γ'·Δy²` where `Γ' = 2ΔM/10000`. Pick one and stay consistent; the *ratio* structure across pairs (which drives all relative-value conclusions) is invariant.

---

## 12. ERRATA / OCR AND SOURCE INCONSISTENCIES (must be handled when tying out)

1. **Doc B l.16 — leg mislabelled:** "The current nationals are $149.5mn and **$81.97** for 15y5y and **25y10y**, respectively" — the trade is 15y5y/**20y10y** throughout; "25y10y" is a typo, and "$81.97" is missing "mn". Also "nationals" for "notionals".
2. **Entry date conflict:** Doc C l.7 "We initiated this trade on **5/9/2019**"; Doc B l.13 "We initiated this trade on **5/10/2019**". The publishing note (Doc A) is dated 9 May 2019 11:52 ET, priced off **close of 5/8/2019**.
3. **Backtest sample conflict (Doc A):** body l.124–125 says "**We start our analysis in 2004** because the quality of our swap curve for prior years is not satisfactory", and Figs 1/3/5 axes start **Dec-03** — but the Fig 4 and Fig 6 notes both say "**Sample: 12/31/2013-5/7/2019**". Reproduced verbatim; unresolvable from the document. (Both readings are defensible: 2004+ for the charts, 2014+ for the Sharpe table.)
4. **Carry number conflict (Doc A):** body l.229 "carries negatively by about **-0.44bp per year**" for 15y5y/20y10y, but Fig 7's 15y5y/20y10y column is **−0.31** (−0.44 is the 15y5y/20y15y column). Column mapping independently confirmed by the curve level (−11.3 → entry −11.8 → Dec −12.54) and by Fig 4's 8-curve list.
5. **Fig 3 title vs body (Doc A):** title "Realized vol has typically exceed[ed] the implied daily breakeven" (BE < rv) vs body l.75–77 "the daily breakeven ... has been **consistently above** the realized vol". The tables (BE/rv < 1 for the recommended trades) support the **title**; the body sentence appears inverted.
6. **Doc C l.23 typo:** "the **15y10/25y5y** GBP curve" → 15y10y/25y5y.
7. **PDF watermark artifact:** the reversed string `eeL rehpotsirhC rof deraperP` ("Prepared for Christopher Lee") is interleaved into table rows in several places (e.g. Doc C l.44 splits the GBP "3y ZS" row) — strip it before parsing.
8. **Column-block OCR:** every screening table is emitted as irregular pipe-groups; the reliable reconstruction key is **15 values per row in fixed pair order** (Docs B/C-era) or **8 values** (Doc A Fig 7/9). Cross-check with the invariant "1y realized vol depends only on the longer leg".

---

## 13. NOT PRESENT IN THESE FOUR DOCUMENTS (do not invent)

- Any Γ/gamma stated in bp per bp², or any dollar-gamma figure.
- The explicit formula for "1y carry" (rolldown convention, day count, discounting).
- The explicit formula for the daily breakeven (only the verbal definition).
- The curve-construction method for the very long forward grid (Doc A only says pre-2004 curve quality "is not satisfactory").
- Any comparison of a curve-implied vol number to the swaption grid (see §7).
- Any drawdown, VaR, turnover, or hedge-count statistic; only mean/vol/Sharpe/skew.
- Any stop-loss, target, or time-based exit rule.
- Financing/collateral assumptions for the backtest.
- Bid/offer for the 15y10y/25y10y GBP pair (Doc A Fig 9 covers only the 8 USD pairs).

---

## 14. CROSS-REFERENCE MATERIAL FROM SIBLING NOTES (same folder, cited by A–D)

### 14.1 GBP initiation — `Rates_Vol_Lab_In_search_of_cheap_vol.pdf.md`, 17 Jan 2020, lines 171–186 (verbatim)
> "In US Rates Vol Lab - Buying vol for less* we highlighted long-dated delta-hedged GBP flatteners as a long convexity trade, but did not initiate them at that time given the risks of a Labour win. ... **long-dated forward curves, such as 15y10y/25y10y, remain quite steep from a historical standpoint given the richness of the 20y on the curve, likely because of receiving flows from ALM investors** (Figure 9 and Figure 10). In addition, **the 15y10y/25y10y flatteners also carry positively by about 0.5bp over 1y. As a result, the flatteners offer an effectively free convexity buy. We initiate 50K DV01 of GBP 15y10y/25y10y flatteners at -11.2bp (as of 12pm on 1/17/2020). We will be delta-hedging the trade by adjusting the longer leg of the trade for DV01 neutral at each 25bp move in the 25y10y rate. We have previously found that hedging at 20-25bp offers an attractive balance between the accuracy of hedging and transaction costs** (US Rates Vol Lab: Trading long-dated convexity). The risk to the trade is a continued richening of the 20y sector on ALM receiving."

Figure 11 (close 1/16/2020) selected rows — **GBP 15y10y/25y10y**: curve −10.37, 1y ZS −0.01, 3y ZS 1.15, ZS-since-2000 **1.84**, 1y carry **+0.52**, daily BE 0.00, 1y rlzd vol 4.19, BE/rv 0.00. **USD 15y5y/20y10y**: curve −13.65, 1y ZS −2.23, 3y ZS 0.18, ZS2000 0.58, carry −2.20, BE 3.41, rv 4.27, BE/rv 0.80. Figure 11 covers **USD, EUR, GBP, CAD, JPY** on the same 15-pair grid (EUR/CAD/JPY rows available on request).

Figure 9/10 charts: 15y10y/25y10y GBP curve 0 → −80bp, Jan-09 → Jan-19; GBP 10s20s30s fly 0 → 70bp, same window (the "20s rich on the curve" ALM evidence).

### 14.2 USD re-entry screen — `Rates_Vol_Lab_Liquidity_vega_and_convexity.pdf.md`, 30 Mar 2020, lines 231–252, Figure 9 (as of 3pm 3/26/2020)
> "**The 15y5y/20y10y USD curve has steepened to the upper bound of the historical range, most likely due to receiving pressures from variable annuity portfolios in the stock market selloff** (Figure 8). As we wrote previously, variable annuity hedging is typically concentrated in the 20y sector of the curve. **The 15y5y/20y10y flatteners (-5.21 bp as [o]f 3pm on 3/26/2020) have a slightly positive carry and positive convexity (Figure 9). In other words, the trade is effectively a free convexity buy. We are adding this trade to our watch list but don't initiate yet given the lack of liquidity and wide bid/offer spreads.**"

USD row, 15y5y/20y10y: curve **−5.21**, 1y ZS **4.21**, 3y ZS **3.58**, ZS2000 1.02, 1y carry **+0.11**, daily BE **0.00**, 1y rlzd vol **6.40**, BE/rv **0.00**.

### 14.3 The mirror trade (steepener = short vol) — `Rates_Vol_Lab_Forward_steepener_and_vol_divergence.pdf.md`, 12 Jun 2023, lines 144–198 (verbatim)
> "We have previously highlighted the **inverse relationship between long-dated forward curves and implied vol due to the net short/(long) convexity exposure that is embedded in long-dated forward curve steepeners/(flatteners)**. ... we prefer to wait until after the FOMC meeting to consider possibly **establishing a long-dated steepener as a positive carry / short vol trade. Because long-dated forward steepeners have net negative convexity, we can back out implied yield breakevens from the carry and compare them to the recent realized yield moves. Having a breakeven/realized vol ratio allows us to compare the positive carry of various long-dated forward steepeners in a standardized fashion (Figure 5).**"
> "**there is generally a trade-off between carry and entry level, where the steepeners with the most attractive carry usually have the worst entry point** (Figure 6). Currently, the 10y10y/15y15y and 20y5y-10y10y steepeners lie on the efficient frontier of this carry vs entry trade-off and have **breakeven vs realized vol ratios that are meaningfully above 1**."

Figure 5, close 06/08/23, USD (steepener sign convention: carry positive):

| pair | curve (bp) | 3y ZS | ZS since 2000 | 1y carry (bp) | daily BE (bp) | 1y rlzd vol (bp) | BE/rv |
|---|---|---|---|---|---|---|---|
| 10y10y/15y15y | −51.5 | −0.91 | −2.07 | 6.89 | 6.18 | 5.30 | 1.17 |
| 10y10y/20y5y | −62.4 | −0.91 | −1.47 | 10.31 | 7.22 | 5.24 | 1.38 |
| 10y10y/20y10y | −76.1 | −0.96 | −1.96 | 8.31 | 5.71 | 5.11 | 1.12 |
| 10y10y/20y15y | −89.4 | −1.00 | −2.34 | 7.71 | 4.99 | 4.85 | 1.03 |
| 10y10y/25y5y | −91.5 | −1.01 | −2.28 | 5.95 | 4.29 | 4.98 | 0.86 |
| 10y10y/25y10y | −105.6 | −1.04 | −2.56 | 6.04 | 3.97 | 4.66 | 0.85 |
| 15y5y/20y5y | −50.9 | −0.98 | −1.30 | 5.93 | 6.77 | 5.24 | 1.29 |
| 15y5y/20y10y | −64.5 | −1.03 | −1.87 | 3.93 | 4.59 | 5.11 | 0.90 |
| 15y5y/20y15y | −77.9 | −1.06 | −2.31 | 3.33 | 3.71 | 4.85 | 0.77 |
| 15y5y/25y10y | −94.1 | −1.11 | −2.58 | 1.66 | 2.29 | 4.66 | 0.49 |

**Signal polarity (important for the strategy engine):** for a **flattener** (long vol) you want **BE/rv LOW** and a **high positive z-score**; for a **steepener** (short vol) you want **BE/rv HIGH (>1)** and a **low/negative z-score**. Implied-ΔM check on this 2023 table: 10y10y/20y10y → 10000×8.31/(252×5.71²) = **10.1** (theory 10) ✓, 15y5y/25y10y → 10000×1.66/(252×2.29²) = **12.6** (theory 12.5) ✓ — the same engine, four years later.