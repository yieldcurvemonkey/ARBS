# Corpus 2 / G09 — Citi US Rates Weeklies + NA Rates Focus + EUR RV notes

Extraction pass for the SOFR-futures convexity-adjustment (CA) vs swap-butterfly backtest program.
Source directory: `C:/Users/chris/Downloads/convexityrv_markdown`. Each section below covers one file
in full. All levels in bp unless noted. OCR caveat: these are PDF→markdown conversions with mirrored
gutter text ("eeL rehpotsirhC…" = "Prepared for Christopher Lee" reversed) and some scrambled
multi-column tables; numbers are quoted only where the row is unambiguous, and garbled tables are
flagged rather than reconstructed.

---

## 1. US Rates Weekly — "All it takes is a little push"

**File:** `US_Rates_Weekly_All_it_takes_is_a_little_push.pdf.md`
**Publisher/date:** Citi Research, US Rates Weekly, 04 Oct 2019 19:44:29 ET, 36 pages. Authors: Jabaz Mathai, Ruslan Bikbov, Steve Kang, Jason Williams, Shuo Li.

### Views summary (Fig 1)
Duration Neutral; Curve Steeper (2y-fwd 2s10s steepener); Swap spreads Tighter (30y tightener); Gamma Neutral (buy 1y 2s10s vs 6m 5s10s delta-hedged straddles); Vega Neutral; Inflation Wider (long 5y BEs); Front end Wider (fade YE Fed funds).

### Trades initiated this issue
1. **2y-forward 2s10s swap steepener** — initiated **50k DV01 at 26bp** (pricing 3:00pm Fri 10/4/19); rolldown **−4.7bp/yr**. Rationale: regime shift from "mid-cycle adjustment" to full easing cycle; works in both "grind to zero" and "fast break" scenarios. Risk: trade-war truce → bear flattener.
2. **30y swap spread tightener** — initiated at **−38.9bp** (4pm 10/4/19). Drivers: QE consensus already priced (30y spreads already ~3.5bp off lows; est. marginal QE widening impact only 2–5bp), equity-selloff/VA-hedging beta (**1% S&P drop ≈ 0.77bp of 30y spread tightening**, so a 5% drop ≈ 4bp tighter), recession model at 74% probability in 12m, seasonal bank supply (~2bp average tightening by mid-October). Risk: more aggressive QE.

### Butterfly/curve analysis (belly-in-easing-cycle study)
- Spot 2s5s30s swap fly **richened 6bp** in the week as October cut odds solidified. Spot 2s10s30s is **1bp richer** (in swaps) since July FOMC.
- Study: 6m risk-adjusted returns of spot and forward swap flies following the first cut of full easing cycles ('01, '07) vs a ZLB-scenario return (5y5y OIS assumed 1.0–1.2%). Conclusion: 10s underperform, 5s stay rich; 1y/2y/3y-fwd 2s5s30s flies "price in too much cheapening" of 5s. Scatter used: spot 2s5s30s fly vs 5s level, sample 2010–present.

### CA / convexity tie-outs (closed-trade table, Fig 41 — directly relevant known answers)
- **"Sell Blues convexity adjustments, hedged"** — opened **Feb 9, 2017 at 8.8bp**, closed **Jun 6, 2017 at 6.6bp**; P&L **+$552k**, target $600k, stop $350k, return-on-risk 55.20%, portfolio ret 0.18%. (Blues CA quoted in bp; ticket confirms Citi runs sold-CA hedged with matched swaps.)
- **"Sell Greens convexity adjustment, hedged"** — opened **Jun 6, 2017 at 4.3bp**, closed **Aug 8, 2017 at 2.65bp**; P&L **+$476k**, target $450k, stop $225k, RoR 47.55%.
- Also relevant closed flies: "Buy the belly in 5s7s12s swap butterfly" Nov 30 2016 → Apr 7 2017, −7.2bp → −9.3bp, +$310k; "UST Butterfly Buy 10s vs 7s and 30s" Jan 30 2018 → May 31 2019, −19 → −10, +$70k; "1y forward 2s10s flattener" Mar 22 2019 → May 31 2019, 26.0 → 35.9bp, −$495k.

### Model-portfolio marks (Fig 40, pricing 4:00pm Oct 3, 2019)
Portfolio +1.30% YTD 2019. Selected open-trade marks: 3y 5s30s conditional bear steepener open 18bp → 29bp (+$153k); 6m LIBOR/OIS 5s10s spread-curve flattener 1.3bp → −0.2bp (+$76k); 15y5y/20y10y delta-hedged flattener −11.8bp → −9.69bp (+$34k); 2s5s10s fly noted "richest since 2013"; buy 2EZ9 vs 0EZ9 puts 4.5 → 2 ticks (+$63k); pay 1y1y 3s1s vs receive FFvLIBOR 2:1, −3.5bp → −2.6bp (+$66k); buy 3m 2s10s 1x2 floor spreads −7bp → +3bp (+$80k); sell delta-hedged 1m10y straddles 185.5 → 294.7 cents (−$9k); FF turn trade (sell FFX9/buy FFZ9/sell FFF0/buy FFG0) fading −4.5bp priced YE FF drop, 4.5 → 4 cents (+$50k); buy SERV9 vs FFV9 −4.4 → −3.8 cents (+$23k, target $75k stop $45k). Note: "Calculations do not include transaction costs and other fees"; portfolio return based on $300mn model sizing.

### Swap fly RV appendix (Fig 43/44, as of 10/3/2019 vs 7/3/2019) — tie-out tables
Conventions: **equal-weighted flies are −0.5:1:−0.5** (receive belly; positive = belly cheap); PCA flies use weights of the **3rd PC of the three legs over a 5y rolling window**; Z-scores at 1m/3m/6m; 3m carry+roll; 3m correlation vs 10s, 2s10s, 5s30s.
Selected equal-weight rows (Level bp / 3m C+R / 1m Z): 2s3s5s −2.6 / 0.0 / −1.94; 2s5s10s −11.1 / 1.6 / −0.33; 5s7s10s −2.4 / 0.2 / −1.44; 5s10s30s −4.1 / 0.5 / 0.08; 7s10s30s −5.8 / 0.0 / −1.54; 5s20s30s +12.3 / 1.0 / 2.03; 10s20s30s +6.6 / 0.2 / 1.76; 15s20s30s +1.4 / 0.0 / −2.25.
Selected PCA rows (weights / level): 2s5s10s −0.36:1:−0.72 / −22.6bp; 5s10s30s −0.44:1:−0.63 / −17.5bp; 7s10s30s −0.63:1:−0.40 / −7.8bp; 10s20s30s −0.26:1:−0.75 / 0.0bp.

### Eurodollar curve/pack/fly monitor (Fig 48/49, as of 10/3/2019) — futures-space fly conventions
- Pack naming W/R/G/B/Go/P (White/Red/Green/Blue/Gold/Purple). Curves: Z9/Z0 −56.1bp; Z0/Z1 −5.2; Z1/Z2 +6.8; Z2/Z3 +8.8; Z3/Z4 +11.7. Packs: White/Red −27.6; Red/Green +2.4; Green/Blue +8.1; Blue/Gold +10.4; Gold/Purple +11.4. CM ED curves: 1y/2y −7.6; 2y/3y +6.8; 3y/4y +8.7; 4y/5y +11.9.
- ED flies quoted both 1:2:1 and PCA-weighted, e.g. Z9/Z0/Z1 −50.9bp (PCA weights 1.3:2:1.1); pack flies W/R/G −30.0 (PCA 1.1:2:1), R/G/B −5.7, G/B/Go −2.3, B/Go/P −1.0; CM-ED 1y/2y/3y −14.3. Method note: fly regressed against its belly (correlation/beta/residual); −ve residual = fly rich; PCA flies built to have **no correlation/beta to the belly**.

### CME/LCH basis
- 30y CME/LCH swap basis chart (Nov-15 to Nov-18+ history, range roughly −1 to +6 "normals"/bp). Thesis: prudential regulators' Sept 2019 proposal offers IM exemption only for *specific* IBOR-remediation amendments, not a blank exemption for bilateral SOFR derivatives ⇒ **the ARRC blank-exemption-driven CME/LCH compression since May 2019 has limited room to run** (a blank exemption would let dealers move duration from CCPs to bilateral, compressing the basis). Inter-affiliate IM repeal frees ≥$39bn collateral (ISDA survey of 20 largest banks, YE2018); 88.4% of required IM collateral is govt securities.

### Other tie-outs
- Front-end: Oct-19 implied SOFR ~185bp / EFFR ~183bp called fair; Fed to buy $50bn/mo USTs Nov-19→Q4-20; steady-state private UST supply ~$500bn ⇒ OIS/2yUST fair ~−15bp vs current −24bp; regression R²: OIS-2yUST vs 12m coupon-only supply 0.6886 (coup+bill 0.6442); 2y swap spread version 0.6053 (0.2127). 2y USTs moved ~15bp→~27bp cheap to OIS since May trade-war escalation; SOFR spiked to 5.25% on 9/17/19 (text has "9/17/18" typo).
- TIPS ASW table (10/3/19 levels/z-scores): TII Jan20s 22.1bp, Apr20s 15.7, Jul20s 17.6, Jan21s 27.2, Apr21s 25.6, Jul21s 22.1, Jan22s 24.5, Apr22s 22.8, Jul22s 22.4, Jan23s 23.2, Apr23s 23.9, Jul23s 23.3, Jan24s 20.3.
- 2020 forecasts: 2y 0.75%, 5y 0.80%, 10y 1.25%, 30y 1.75% (ZLB by 2021 base case).
- Appendix II Treasury RV table (fitted-curve spread + ASW percentiles) present, as of 10/3/2019; garbled in places but rows quoted above are clean. Trailing ~350 lines are standard Citi risk/regulatory boilerplate (no content).

**Relevance:** High — direct printed CA trade tickets (Blues/Greens sold-CA hedged, with entry/exit dates and bp levels), ED pack/fly conventions incl. PCA-vs-1:2:1 weighting, swap-fly RV table conventions (−0.5:1:−0.5, PCA 3rd-PC 5y window), CME/LCH basis driver narrative, and forward-fly-vs-easing-cycle framework.

---

## 2. US Rates Weekly — "Deal or no deal: Rates implications"

**File:** `US_Rates_Weekly_Deal_or_no_deal_Rates_implications.pdf.md`
**Publisher/date:** Citi Research, US Rates Weekly, 10 May 2019 16:48:48 ET, 34 pages. Authors: Mathai, Bikbov, Kang, Williams, Li (with Mark Chen).

### Views (Fig 1)
Duration Long TIPS (long 30y TIPS); Curve Flattener (1y-fwd 2s10s flattener); Spreads Wider (TU/OIS widener); Gamma Long (6m30y delta-hedged straddles); Inflation Wider; Front end: 18m1y 3s1s widener vs FFvLIBOR tightener 2:1 DV01. 2019 forecasts: 2y 2.75, 5y 2.70, 10y 2.85, 30y 3.05; 2y/10y/30y swap spread +20/0/−20bp; 10y BE 200bp.

### Swaps section: "Trading long-dated convexity" (Bikbov) — CONVEXITY METHODOLOGY PAYLOAD
Thesis: convexity embedded in long-dated forward flatteners is cheap to realized vol; systematically delta-hedged flatteners are profitable with long-vol bias.
- Structure: e.g. 10y10y/20y10y flattener = **receive 20y10y fwd swap vs pay 10y10y fwd swap, DV01-neutral**. At long horizons curve ≈ convexity adjustments + term premium + technicals; 20y10y has more convexity per unit DV01 ⇒ flattener is positively convex, rolls negatively (long-fwd term structure normally inverted). Analogy: 10y10y/20y10y spread ≈ implied vol (vega). Empirical fit: **10y10y/20y10y curve vs 2y10y normal vol: y = −0.5x + 19.0, R² = 0.5** (sample 1/4/2010–5/3/2019).
- Metric: **implied daily rates breakeven** = parallel shift whose convexity gain offsets negative daily roll; historically below realized vol of the forwards (i.e. embedded convexity cheap).
- Backtest: enter **$100K DV01** DV01-neutral flattener, roll annually, **delta-hedge by adjusting notional of the longer leg at each 25bp move** in the longer rate (at close; receive more if rates +25bp, pay if −25bp). 25bp threshold chosen as accuracy/cost trade-off; Sharpe insensitive within 15–30bp threshold. Sample 12/31/2013–5/7/2019 (curves from 2004 for levels).
- Results table (avg daily return $K / daily P&L vol $K / Sharpe): 10y5y/15y15y 0.67/195.3/0.05; 10y10y/15y15y 1.15/142.4/0.13; 10y10y/20y10y 2.28/222.1/0.16; 10y10y/20y15y 3.20/208.5/0.24; **10y10y/25y10y 5.40/247.6/0.35**; 15y5y/20y10y 2.92/251.5/0.18; 15y5y/20y15y 3.79/241.7/0.25; 20y5y/25y10y 4.09/219.3/0.30. Corr(monthly P&L, Δ1y10y vol) ≈ +26%; daily-P&L skew ≈ 0 (vs short 1m10y gamma: Sharpe ~0.84 but skew ~−3).
- Trade initiated: **$50K DV01 15y5y/20y10y flattener at −11.8bp** ($148.8mn 15y5y vs $90.3mn 20y10y), pricing 12pm 5/9/2019; **delta-hedge every 20bp move**; carry −0.44bp/yr vs 1.3bp daily curve vol (20y10y rate daily vol realized 3bp 1y / 2.8bp 3m). Entry-screen table (close 5/8/2019) per curve (level bp / 1y ZS / 3y ZS / 1y carry bp / daily BE bp / 1y realized vol bp / BE/realized): 10y5y-15y15y −10.1/2.50/0.19/−2.91/3.5/3.2/1.07; 10y10y-15y15y −8.8/2.15/0.39/−1.64/3.0/3.2/0.94; 10y10y-20y10y −13.2/1.87/0.53/−1.75/2.6/3.1/0.84; 10y10y-20y15y −16.7/2.41/0.50/−1.88/2.5/3.1/0.79; 10y10y-25y10y −20.1/2.38/0.55/−1.83/2.2/3.0/0.72; **15y5y-20y10y −11.3/1.16/1.01/−0.31/1.3/3.0/0.42**; 15y5y-20y15y −15.2/1.62/0.99/−0.44/1.3/3.0/0.45; 20y5y-25y10y −9.1/1.95/0.87/+0.13/0.0/3.0/0.00. Risk: VA hedging (annuity duration concentrated in 15–25y bucket; corr(stocks, 15y5y/20y10y curve) ≈ −23%; but corr(trade P&L, S&P) ≈ 0).
- **Transaction costs (Fig 21, one-way mid-to-bid/offer, bp): initiation 0.75bp (1bp for 10y10y/20y15y, 10y10y/25y10y, 15y5y/20y15y, 20y5y/25y10y); delta-hedging & roll 0.3bp (0.4bp for those same wider curves).**

### Treasury futures roll (Jun19→Sep19) — dealer/AM-positioning-vs-valuation regressions (CFTC TFF style)
Views: TU bearish, FV slightly bearish, TY slightly bearish, UXY neutral, US neutral, WN bearish. Levels close 5/8/19: TU −5.875 ticks (CTDs 1.25% Mar21 / 1.125% Jun21); FV −3.25 (2.75% Aug23 / 2.875% Nov23); TY −7.5 (2.625% Dec26 [text also says Dec25s] / 2.375% Apr26); UXY −19 (3.125% Nov28 / 2.625% Feb29); US +21.0 (4.5% Feb36 both); WN −20.0 (3.125% Aug44 / 3.0% Nov44).
- TU: 10.7% rolled vs 3.2% average at same point; spread ~2 ticks cheap to carry, ~3 ticks cheap incl. CTD slope; U9 net basis ~2 ticks rich, CTD Jun21s ~1.3bp rich to fitted curve; M9 CTD ~0.3bp rich. AM position near multi-year highs.
- FV: AM net long 31% of OI (prev 34%; late-2018 high 43%). **Regression of roll rich/cheap (at FND) on normalized AM positioning: y = −17.517x + 2.5885, R² = 0.6405** ⇒ spread >1 tick too cheap.
- TY: AM 16% of OI (prev 21%, peak 25% at start of 2019).
- UXY: AM collapsed to 1% of OI (prev cycle start ~9%).
- US: AM ~9% of OI (prev ~10%, late-2018 high ~17%); same CTD both months ⇒ stable spread.
- WN: AM 58% of OI (prev 55%); spread −3 ticks cheap to carry but "rich" ~1 tick per regression **y = −14.666x + 3.039, R² = 0.825** (past ten rolls ex Nov-16). Rule of thumb: with AM >40% of OI, spread cheapens into FND ⇒ roll early.

### Model portfolio (pricing 4:00pm May 9, 2019; portfolio +0.33% YTD)
1y-fwd 2s10s flattener open 26bp → 26.5bp (−$25k; carry +~20bp/annum quoted); 3y 5s30s conditional bear steepener 18 → 26bp (+$147k); 6m30y straddles 47.6 → 49.1 nv (+$73k); UST 7s10s flattener −18.6 → −10.6bp (+$9k; note 10y cheapened ~7bp on the fly that month, ~27bp since Sep 2017 vs ~30bp taper-tantrum move May–Sep 2013); sell 2y 2.648 → 2.31% (−$1,404k); buy 30y TIPS 1.347 → 0.97% (+$1,728k); SERN9 short 2.415 → 2.385% (+$63k); TUM9 OIS invoice widener −16.4 → −15.97 (+$21k); 18m1y 3s1s vs FFvLIBOR 2:1 −6.5 → −4.22bp (+$114k; 18m1y carry 4.3bp/yr); 1y1y-2y2y FRA/OIS steepener 0.5 → −1.11bp (−$161k); 1x2 0EM9 call spreads 9 → 27bp (−$450k); pay 1y1y JPYUSD −38 → −30.17bp (+$391k). Overview betas: 3m beta 10y-vs-S&P: y = 257.09x − 0.5103, R² 0.1799 (1y: 161.18x − 0.2417, R² 0.1808); ~2.5bp per 1% SPX. 5y BE fair value 1.91% vs actual 1.76% (model: Michigan 1y-ahead, CL1-vs-CL12 %chg, USDCAD, Citi Growth Index; rolling 2y weekly window).

### Swap fly RV appendix (Fig 47/48, as of 5/9/2019 vs 2/11/2019) — tie-outs
Equal-weight (−0.5:1:−0.5) selected (Level / 3m C+R / 1m ZS): 2s3s5s −3.0/−0.1/0.27; 2s5s10s −11.1/0.8/0.14; 5s7s10s −2.2/0.0/0.01; 5s10s30s −1.9/0.3/0.40; 7s10s30s −4.4/0.1/0.70; 5s20s30s +14.5/0.3/−0.50; 10s20s30s +7.3/0.0/−0.81; 15s20s30s +1.6/0.0/0.94.
PCA selected (weights / level): 2s5s10s −0.39:1:−0.68 / −27.9; 5s10s30s −0.45:1:−0.62 / −20.2; 7s10s30s −0.64:1:−0.40 / −9.6; 10s20s30s −0.24:1:−0.77 / −2.3. Same conventions as doc 1.

### ED monitor (5/9/2019)
Curves: Z9/Z0 −27.4; Z0/Z1 −0.1; Z1/Z2 +9.4; Z2/Z3 +13.5; Z3/Z4 +13.8. Packs: White/Red −26.1; Red/Green −2.3; Green/Blue +8.8; Blue/Gold +12.8; Gold/Purple +13.9. Flies: Z9/Z0/Z1 −27.3 (PCA 0.8:2:1.4); W/R/G −23.8 (0.9:2:1.4); R/G/B −11.1; G/B/Go −4.0; B/Go/P −1.1; CM 1y/2y/3y −19.6.
Closed-trades table is the same cumulative table as doc 1 (through Apr 2019), incl. the **Blues CA (8.8→6.6bp) and Greens CA (4.3→2.65bp) sold-hedged tickets**. Treasury RV appendix as of 5/9/2019 (rows quoted in file). Trailing section is options-risk + standard disclosures.

**Relevance:** High — the long-dated-convexity (forward flattener as cheap convexity) framework with full backtest spec, transaction-cost table, delta-hedge rule, and daily-breakeven-vs-realized-vol metric; plus the CFTC-positioning-vs-futures-roll-valuation regressions (template for dealer-positioning-conditioned CA work) and a second vintage of the swap-fly RV and ED-fly tables.

---

## 3. US Rates Weekly — "Learning on the job"

**File:** `US_Rates_Weekly_Learning_on_the_job.pdf.md`
**Publisher/date:** Citi Research, US Rates Weekly, 02 Aug 2019 18:20:21 ET, 41 pages. Authors: Mathai, Bikbov, Kang, Williams, Li (with Mark Chen).

### Views (Fig 1)
Duration Neutral; Curve Neutral; Spreads Flatter curve; Gamma Short (sell 3m-into-2y OTM strangle); Vega Neutral; Inflation Wider; Front end: flatter FRA/OIS.

### CME/LCH basis + POSITIONING-vs-CA section (Bikbov, "TU OIS and CME/LCH") — KEY for the program
- **30y CME/LCH spread reached 0.8bp, tightest since 2015** (from ~5-6bp Q1 2019; chart Jul-15 onward). Drivers claimed: (1) anticipated blank IM exemption for bilateral SOFR derivatives (structural: incentive to move duration CCP→bilateral); (2) **positioning unwinds — domestic real money structurally pays on CME; unwinding steepeners = receiving pressure on the back end of the CME curve**, concentrated in the 30y sector.
- **Fig 27 pairs CFTC asset-manager net ED positions (% of OI, LHS) against the Blues ED convexity adjustment (bp, RHS), Jan-18→Jul-19**: significant decline in AM net ED longs "is also reflected in the recent **widening of ED convexity adjustments**" — real money exiting steepeners by receiving long-dated swaps vs selling ED futures. This is the doc's explicit dealer/AM-positioning ⇒ CA relationship (AM ED longs ↓ ⇒ Blues CA ↑). Chart axis range ~0 to −25% of OI vs 0–10bp CA.
- Forecast: rebound possible in CME/LCH to the extent it was positioning, but no return to Q1 levels (structural SOFR-IM story intact).
- TU OIS tightener: initiated **$50K DV01 at −23.6bp** (8/1/19), level −26.5bp (1pm 8/2/19), **close target −28bp**, stop per portfolio table $130k/target $220k. Fair-value model: 2y OIS/Tsy ~3bp wide (model on term 3m OIS/GC spread + primary-dealer <3y UST inventories). Supporting numbers: Fed reinvestment demand +$70bn Aug-Sep ($40bn MBS-runoff secondary + $30bn auction add-ons); bill supply +$180bn Aug; 1% lower deficit/GDP ≈ 3bp wider spreads; potential $94bn sterilized FX intervention (ESF size); budget deal +$154bn deficits over 5y.

### Overview trades
- Long stub FF OIS (spot to 9/18/2019 FOMC maturity, no Sep-FOMC exposure) entered **215.7bp, 50K DV01** (3pm 8/2/19; EFFR 214bp). Payoff table: mid-Aug 25bp intermeeting cut ⇒ −18bp on the stub (19:1 payoff); end-Aug cut ⇒ −10bp (10:1). FF/IOER vs reserves regression: **y = −0.0157x + 27.043, R² = 0.9576** (drift +0.75–3bp on $50–150bn reserve drain).
- Sell 50mm Sep-18-expiry IG CDX 55 receiver at 12.4 cents (3pm).
- Closed tactical long 10y swaps (from exercised 1.91%/1.71% receiver spread) by paying 50mm at 1.774% (3pm Fri). Bull-case 10y UST 1.75% ≈ 10y swaps 1.67%.
- Noted 2y-fwd 2s10s steepener "looks good on carry-adjusted basis, still somewhat early" (initiated later in doc 1, Oct-19).

### Short-end
New: **pay 1y1y 3s1s + receive FFvLIBOR, 2:1 DV01** — quoted as 2×3s1s − FFvLIBOR = 2×11.0 − 25.5 = **−3.5bp entry, 75K DV01, target 0bp, stop −6bp** (10AM 8/2/19). Level/roll table (FFvLIBOR / 3s1s / 2*3s1s−FFvLIB): 1y 28.5/15.5/2.5; 1y1y 25.5/11.0/−3.5; 2y1y 23.4/9.8/−3.9; 3y1y 23.8/9.8/−4.3; 4y1y 24.7/9.6/−5.4; 5y1y 24.4/9.6/−5.1; 6y1y 24.2/9.1/−5.9; 7y1y 23.8/9.6/−4.6; 8y1y 24.8/9.4/−6.0; 9y1y 22.3/9.1/−4.0. Closed 1.5:1:1 JPYUSD/EURUSD/CHFUSD XCCY at −25bp, flat P&L. FF/SOFR futures strip marks (8/2/19-ish): Q9…F0 showing −5.375, −7.5, −8.75, −9.25, −11.5 bp (partially garbled column alignment).

### 10y refunding auction model (Williams)
Tail/through(WI) vs foreign takedown: y = −11.482x + 2.7495, R² 0.4818 (concurrent); predictive version on 3-auction-avg past takedown: y = −12.19x + 2.6219, R² 0.2203. Logistic model on {3m-MA foreign takedown, 1m ΔUSDJPY, 1m Δglobal CESI}, calibrated 2010–2017, 4/6 correct 2018+, full-sample accuracy 64% (76% tails / 55% throughs). Recent foreign takedown 15.5% (3m avg) vs ~20% avg 2018.

### LIBOR/LCH-discounting special topic
FRA/OIS 5y/5y5y slope fair-value table under mean/median × 5y/10y-window scenarios (data CoB 8/1/19), e.g. current 5y/5y5y curves (bp): 1m/OIS 0.6, 3m/OIS −1.4, 6m/OIS 1.5, 3s1s −1.9, 6s3s 2.8, 6s1s 0.9, 1s3s6s −4.8; median/5y-window fair values −5.0/−7.0/−9.9/−2.0/−2.9/−4.9/0.0 ⇒ 6m/OIS 11.4bp too steep (2.60 vol-adj). Assumes EFFR/SOFR −2.5bp to end-2019 widening to +4bp by 2023; LIBOR discontinued 2024. LCH SOFR-discounting conversion targeted ~Oct 17 2020 (CME proposed Jul 17 2020); LCH compensation = cash + bucketed ATM FF/SOFR basis swaps at 2y/5y/10y/15y/20y/30y with optional cash-only election + centralized auction (liquidity-risk discussion).

### Model portfolio (pricing 4:00pm Aug 1, 2019; portfolio +0.43% YTD)
15y5y/20y10y delta-hedged flattener −11.8 → −11.14bp (+$20k); 3y 5s30s cond. bear steepener 18 → 34bp (+$144k); 5y BE 1.69 → 1.41% (−$934k); sell 3m-into-2y OTM strangle 10.8 → 1.9 cents (+$226k); Q9 1s/OIS tightener 10 → 8 (+$100k); long 10y (from receiver spread) 1.91 → 1.81% (+$252k); TU OIS tightener −23.6 → −25.2bp (+$80k). Closed-trades table = same cumulative table (adds: pay 1y1y FFvLIBOR vs rec 5y5y FFvLIBOR 2:1 May 10 → Jul 22 2019, −19.8 → −26.3, +$323k; Q9-V9 FF/SOFR box steepener/X9 widener Jul 26 → Aug 1 2019, −2.0 → −1.5, +$25k). Blues/Greens CA tickets present again unchanged.

### Swap fly RV appendix (Fig 40/41, as of 8/1/2019 vs 5/1/2019) — third vintage
Equal-weight (Level / 3m C+R / 1m ZS): 2s3s5s −2.7/0.0/1.07; 2s5s10s −13.2/1.0/−1.84; 5s7s10s −3.2/0.1/−3.19; 5s10s30s −5.0/0.5/−2.70; 7s10s30s −7.2/0.1/−3.18; 5s20s30s +16.0/0.7/−1.26; 10s20s30s +8.5/0.1/−0.07; 15s20s30s +1.6/0.0/−2.41.
PCA (weights/level): 2s5s10s −0.36:1:−0.72 / −28.6; 5s10s30s −0.44:1:−0.63 / −21.4; 7s10s30s −0.64:1:−0.40 / −9.4; 10s20s30s −0.26:1:−0.76 / −0.5.

### ED monitor (8/1/2019)
Curves: Z9/Z0 −43.6; Z0/Z1 −1.4; Z1/Z2 +7.9; Z2/Z3 +10.8; Z3/Z4 +12.6. Packs: White/Red −35.2; Red/Green +1.1; Green/Blue +8.3; Blue/Gold +11.3; Gold/Purple +13.1. Flies: Z9/Z0/Z1 −42.2 (PCA 0.8:2:1.5); W/R/G −36.3 (0.9:2:1.4); R/G/B −7.1; G/B/Go −3.0; B/Go/P −1.9; CM 1y/2y/3y −15.7 (PCA 0.2:2:2).
Agency section: OAS to Tsy 8/1/19: 2y 2bp (12%ile), 3y 4 (2%), 5y 7 (28%), 7y 11 (7%), 10y 23 (46%); duration-adj rolldown and vol-adjusted breakeven tables quoted in file. Trailing pages boilerplate.

**Relevance:** Very high — the single most direct printed statement of the AM-ED-positioning ⇒ ED convexity-adjustment relationship and CME/LCH tightening mechanics/level tie-out (30y CME/LCH = 0.8bp, tightest since 2015, as of ~8/1/2019), plus third dated vintage of swap-fly and ED-fly tables.

---

## 4. US Rates Weekly — "The rocky road to a steeper curve"

**File:** `US_Rates_Weekly_The_rocky_road_to_a_steeper_curve.pdf.md`
**Publisher/date:** Citi Research, US Rates Weekly, 18 Jan 2019 17:24:33 ET, 33 pages. Authors: Mathai, Bikbov, Kang, Williams, Li (with Mark Chen).

### Positioning section: "Shorts increasing? An alternate view of positioning" (Williams) — CORE for CA-vs-positioning + CME-LCH
Context: CFTC data unavailable (government shutdown), so Citi uses **market-traded instruments as positioning proxies: the 10y CME-LCH basis (back-end shorts) and ED futures convexity adjustments (front-end positioning)**.
- **CME-LCH basis mechanics:** basis emerged May 2015 (near zero → almost 2bp quickly); identical swaps clear higher on CME than LCH; customers clear USD swaps at CME for futures-swaps netting (CME hosts Treasury+ED futures), dealers at LCH (legacy books). Fair value = positioning + relative clearing costs (client-specific netting).
- **Quantified relationships: 3m changes of 10y CME-LCH basis are 31% correlated to TY spec positioning/OI and 51% correlated to changes in 10y yields.** Basis collapsed Oct→Dec 2018 as 10y rallied 3.25%→~2.7% on short covering; recent 2-week widening = fresh shorts. 10y CME-LCH chart range ~1.0–4.5bp (Nov-15 onward).
- **ED convexity adjustment fair value = one-factor Ho-Lee model, CA a function of volatility** ("Our fair value model is based on the one factor Ho-Lee model, wherein convexity adjustments are a function of volatility"; basis trades rich/cheap to fair value on positioning — ref: US Rates Vol Lab: Convexity Meets Steepeners). Fig 11: **Blues pack CA vs Ho-Lee model level, Jan-17→Sep-18+, CA range ~2–12bp; CA collapsed to model fair value over past few months** as levered funds covered ED shorts (Fig 12: ED levered funds/OI from ~−25/−30% shorts toward flat, Jan-14→Sep-18). Narrative: 2015-hiking-cycle LF shorts drove ED cheap to model 2017–early-2018; Q4-18 covering ⇒ CA converged down to fair value; CA now *through* model fair value ⇒ former short base is now long. Explicit rule used across these weeklies: **CA above model = short base / cheap futures; CA at/below model = long positioning**.
- Combined read (this issue): 10y CME-LCH widening + ED CA tightening ⇒ investors getting short duration and into steepeners.

### Overview: ED1/ED4 inversion → curve steepening event study
Signal: first inversion of ED1/ED4 slope in each tightening cycle; changes measured on **1y-forward-starting swap rates** (to allow for rolldown). Episodes (first inv → first cut): May-95→Jul-95, Dec-97→Sep-98, Sep-00→Jan-01, Mar-06→Sep-07, Sep-08→Oct-08. Full table (inv→cut change, bp): e.g. Sep-00: 2y −142.5, 10y −91.6, 2s10s +50.9, 5s30s +26.5; Mar-06: 2s10s −39.7, 5s30s +52.5. Horizon tables at 1m/3m/6m/1y after inversion (all quoted in file); 1y-after: 2s10s +55.1/+14.4/+189.5/−30.1/+151.4 and 5s30s −1.6/+31.5/+107.8/+15.2/+88.1 across the five episodes. Conclusion: curve bull-steepens by 1y after signal; entry can wait up to ~6m; 4/5 episodes bull-steepened by first cut.

### Short-end: supply-vs-spreads regressions (Kang)
Univariate OLS since 2010, 1m/3m cumulative supply vs spread changes (TU/FV/TY vs OIS and LIBOR): **only T-bill notional supply has consistent significant negative coefficient on TU/OIS** (e.g. 3m chg past 3yrs coeff −0.036, t −3.60). $130bn T-bill paydown Apr/Jul ⇒ TU/OIS +2 to +5bp; +$220bn H2 bills ⇒ −3 to −8bp. SOMA-WAM scenario: private-WAM vs UST/OIS regressions: TU/OIS y = −0.529x + 23.959 (R² 0.0903); FV/OIS y = −1.3553x + 63.705 (R² 0.2885); TY/OIS y = −2.5096x + 126.67 (R² 0.5106); at 25% of historical beta ⇒ TY/FV/TU tighten −5/−2.5/−1bp if Fed reinvests in 1y USTs post-normalization.

### Swaps (Bikbov)
Spread-curve flattener (TU OIS vs TY OIS) paused; TU OIS +3.5bp since initiation; 30y spreads hit −20bp on pension rebalancing after 14% Q4 S&P selloff; 2y OIS/Tsy ≈ fair on model (3m FF/term GC spread + dealer inventories + world FX reserves); China sold ~$18bn reserves in Dec (valuation-adjusted). 2019 forecasts: 2y/10y/30y swap spreads +25/+7/0bp.

### Model portfolio (pricing 3:00pm Jan 17, 2019; +0.04% YTD)
UST 7s10s fly (buy 10s vs 7s/30s) −18.6 → −10bp (+$14k); Dec18 FOMC OIS received 2.312 → 2.400% (−$440k); 5y BE 1.83 → 1.66% (−$493k); 30y TIPS 1.347 → 1.2% (+$662k); 1x2 0EM9 call spreads 19 → 24bp (−$106k); 3m 5s30s curve caps vs 3m5y receivers 6.9 → 27bp (−$21k); pay 1y1y 3s1s vs FRA/OIS 2:1 −11.12 → −5.96bp (+$387k); sell 2y 2.648 → 2.54 (−$492k); short 10y10y straddles 66 → 66.3 (−$21k); pay 1y1y JPYUSD −38 → −37.44 (+$28k). Closed table through Jan 2019 (Blues/Greens CA rows present).

### Swap fly RV appendix (as of 1/17/2019 vs 10/17/2018) — earliest vintage in set
Equal-weight (Level / 3m C+R / 1m ZS): 2s3s5s −2.0/−0.2/0.29; 2s5s10s −9.1/0.5/0.13; 5s7s10s −2.1/0.1/−0.18; 5s10s30s +0.5/0.3/−0.15; 7s10s30s −1.4/0.1/−0.18; 5s20s30s +11.6/0.4/0.17; 10s20s30s +5.8/0.0/0.26; 15s20s30s +1.5/0.0/0.12.
PCA (weights/level): 2s5s10s −0.43:1:−0.62 / −23.1; 5s10s30s −0.44:1:−0.62 / −20.5; 7s10s30s −0.63:1:−0.41 / −10.3; 10s20s30s −0.24:1:−0.79 / −3.7.

### ED monitor (1/17/2019)
Curves: Z9/Z0 −14.2; Z0/Z1 −1.7; Z1/Z2 +8.6; Z2/Z3 +12.5; Z3/Z4 +11.8. Packs: White/Red −10.0; Red/Green −6.1; Green/Blue +6.6; Blue/Gold +11.6; Gold/Purple +12.4. Flies: Z9/Z0/Z1 −12.5 (PCA 0.7:2:1.5); Z0/Z1/Z2 −10.2 (0.6:2:1.5); W/R/G −3.9 (0.9:2:1.4); R/G/B −12.7 (0.6:2:1.6); G/B/Go −5.0; B/Go/P −0.8; CM 1y/2y/3y −13.7 (0.5:2:1.8). Special topic (Fitch downgrade) and Treasury RV appendix (1/17/2019) present; trailing boilerplate.

**Relevance:** Very high — names the **Ho-Lee one-factor model as Citi's ED CA fair-value model** and documents the CA-vs-levered-fund-positioning regime rule and CME-LCH-basis-as-positioning-proxy with correlation numbers (31% vs TY spec/OI, 51% vs 10y yield changes, 3m changes); plus the ED1/ED4-inversion steepening event-study tables and a Jan-2019 vintage of fly/ED tables.

---

## 5. US Rates Weekly — "Trade worries linger"

**File:** `US_Rates_Weekly_Trade_worries_linger.pdf.md`
**Publisher/date:** Citi Research, US Rates Weekly, 17 May 2019 18:35:05 ET, 36 pages. Authors: Mathai, Bikbov, Kang, Williams, Li, Daniel Sorid, Wei Guan (with Mark Chen).

### Swaps section (Bikbov): SOFR IM exemption ⇒ CME-LCH tightening thesis — origin of the story tracked in docs 1 & 3
- ARRC requested blank IM exemption for new bilateral SOFR derivatives. **Mechanism**: IM phase-in schedule table (Sep 2016 >$3tn gross notional; 2017 >$2.25tn; 2018 >$1.5tn; 2019 >$0.75tn; 2020 >$8bn). If granted, dealers/clients transfer delta risk CCP→bilateral via offsetting SOFR OIS: e.g. real money net-paying CME IRS receives a CME-cleared SOFR swap + pays a bilateral SOFR swap. **IM-reduction table (Fig 20): Pay $100K DV01 10y IRS: CME IM $3,237k → $766k hedged with receive 10y SOFR (−76%); LCH $4,539k → $1,596k (−65%). Receive $100K DV01 10y IRS: CME $3,959k → $782k (−80%); LCH $4,165k → $2,180k (−48%).**
- **Why the CME-LCH spread exists (verbatim mechanism):** "the spread exists mainly because domestic real money investors are structurally paying in CME-cleared swaps, while dealers hedge this risk by paying in LCH-cleared swaps and need to post IMs to both CME and LCH. The corresponding financing and balance sheet costs incurred by dealers are passed to clients as the CME-LCH spread." Delta transfer to bilateral ⇒ lower dealer IM ⇒ tighter CME-LCH.
- Collateral figures: ISDA YE2018 — regulatory IM for uncleared derivatives up to $163bn (~88% government securities); cleared IR-derivative IM another $173bn; also short-end section notes SOFR-IM exemption could free "up to $160bn" of collateral.
- Spread tightening in the week: 5y swap spread −2.5bp w/w to +1.5bp; TU invoice spread to −19bp; attributed to (1) China-selling fears (faded), (2) mortgage convexity receiving (rates locally steep on refinanceability S-curve; curve flattens 20–25bp lower in rates), (3) capitulation of long-spread positions. Recommendation: fade the tightening.
- Vol RV trade: buy delta-hedged **1000 TYQ9 126.5 calls at 19/64** vs sell **$124.1mn receivers on 9/30/2019–4/30/2026 swap, expiry 7/26/2019, strike 2.03%, at 26.3 cents** (pricing 12pm 5/17/19); delta-hedged daily 3pm NY. Board/swaption table close 5/16/19: e.g. TY Board vols TYN9/Q9/U9 59.8/60.5/61.3 vs CTD-matched swaption 63.2/62.4/61.6; Board/swpn 0.95/0.97/1.00 (US contract 0.91/0.93/0.95).

### Short-end (Kang)
GC ~245–250bp avg expected 2019, SOFR ~240–245bp; L/OIS printed 15.6bp with 15bp floor thesis (<10bp "too extreme" per 30y history); excess-GC-collateral measure = private GC supply (UST bills+coupons+MBS) minus MMF GC demand (y/y chg in repo+UST+agency holdings), correlated with yearly-avg GC/IOER. Sell SERN9 continuing (bid 2.39% 2pm 5/17).

### Overview
Tariff impact tables (Citi economics): $325bn @25% ⇒ China growth −1.35, US −0.17, global −0.51; core PCE +0.22/+0.24 (60% pass-through headline/core) or +0.37/+0.41 (100%). Foreign flows (TIC, March, valuation-adjusted using ~5y avg maturity and 5y-yield changes): foreign official LT UST −$16bn hdr / official −$1bn table; China −$27bn (z −1.5); Canada −$15bn (z −4.0); UK +$21bn (z +2.6); Singapore +$7bn; Japan −$10bn.

### Model portfolio (pricing 4:00pm May 16, 2019; +0.16% YTD)
15y5y/20y10y delta-hedged flattener −11.8 → −11.4bp (−$20k); 1y-fwd 2s10s flattener 26 → 31.5bp (−$275k); UST 7s10s −18.6 → −12bp (−$39k); sell 2y 2.648 → 2.25 (−$1,717k); 30y TIPS 1.347 → 0.94% (+$1,928k); 1x2 0EM9 call spreads 9 → 38bp (−$725k); TUM9 OIS invoice widener −16.4 → −19.37 (−$149k); SERN9 2.415 → 2.380% (+$74k); 3y 5s30s cond bear steepener 18 → 28bp (+$136k); 18m1y 3s1s vs FFvLIBOR −6.5 → −3.43bp (+$154k). Closed table through Apr-2019 (Blues/Greens CA rows present).

### Swap fly RV appendix (as of 5/16/2019 vs 2/18/2019)
Equal-weight (Level / 3m C+R / 1m ZS): 2s3s5s −3.8/−0.1/−1.78; 2s5s10s −11.7/1.0/−1.47; 5s7s10s −2.4/0.0/−1.78; 5s10s30s −2.0/0.3/−0.78; 7s10s30s −4.9/0.1/−1.32; 5s20s30s +16.0/0.4/1.00; 10s20s30s +7.8/0.0/1.10; 15s20s30s +1.6/0.0/1.05.
PCA (weights/level): 2s5s10s −0.38:1:−0.68 / −28.6; 5s10s30s −0.45:1:−0.62 / −20.2; 7s10s30s −0.64:1:−0.40 / −9.5; 10s20s30s −0.25:1:−0.77 / −2.1.

### ED monitor (5/16/2019)
Curves: Z9/Z0 −31.5; Z0/Z1 +0.9; Z1/Z2 +11.1; Z2/Z3 +15.0; Z3/Z4 +15.1. Packs: White/Red −32.2; Red/Green −1.3; Green/Blue +10.6; Blue/Gold +14.1; Gold/Purple +15.5. Flies: Z9/Z0/Z1 −32.4 (PCA 0.9:2:1.4); W/R/G −30.9 (0.9:2:1.4); R/G/B −12.0 (0.8:2:1.4); G/B/Go −3.5; B/Go/P −1.4; CM 1y/2y/3y −20.7 (0.2:2:2). Agency + TIC-flows sections and Treasury RV appendix (5/16/2019) as quoted in file; trailing boilerplate.

**Relevance:** High — the definitive CME-LCH basis mechanism note (structural payer-flow origin, IM economics with a printed dealer-IM table, SOFR-exemption channel) that the later weeklies reference; plus May-2019 vintages of all monitor tables and the Board-vs-swaption vol RV framework relevant to futures-vs-swap wedges.

---

## 6. US Rates Weekly — "What to expect when you're expecting a turn"

**File:** `US_Rates_Weekly_What_to_expect_when_you_re_expecting_a_turn.pdf.md`
**Publisher/date:** Citi Research, US Rates Weekly, 20 Apr 2018 18:56:57 ET, 31 pages. Authors: Mathai, Bikbov, Kang, Williams (with Utkarsh Saddi).

### Vol section: "Convexity meets Steepeners" (Bikbov) — THE core CA fair-value + trade-construction doc in this set
- **ED convexity adjustments in Blues and Golds widened notably**; Fig 11/12: **Blues Pack CA vs Model level (range ~2–12bp) and Golds Pack CA vs Model (range ~4–16bp), Apr-16→Apr-18. Convexities measured vs CME swaps.** "Convexities have widened to theoretical fair values based on implied volatilities... **Blues and Golds convexities are about two sigmas wide to the model**."
- Driver claim: build-up of (1) duration shorts and (2) steepener positions fading the flattening; "**Because futures are more capital-efficient than swaps, they are the instrument of choice for many investors. As a result, macro positioning tends to be reflected in ED convexity adjustments.**" CFTC Fig 13: both leveraged funds and asset managers "extremely short" ED (% of OI chart, Oct-12→Oct-17, range ~−30% to +50%). Curve beyond Greens flattened most (1y z-scores by pack curve, whites/reds…golds/purples ~−0.2 to −1.1) ⇒ CAs there widened most. Back-end 3m2y/3m30y risk-reversal flip since January = flatteners liquidated → steepeners.
- **Printed CA fair-value regression (Fig 16 caption): "Model value of Blues CA = −0.65 + 0.044·(ED16 − 0.74·ED6)"**, history Jan-99→Jan-17, i.e. Blues-CA fair value as a linear function of the DV01-weighted ED6/ED16 curve — with the caveat "**the hedge is not effective at ZLB**". This is the Citi "CA = a + b×(curve)" template the backtest program is replicating.
- **Trade: sell Blues convexity adjustments (vs CME swaps) outright at 7.2bp mid (3pm 4/18/2018**; text has a "4/18/2019" typo). Preference for Blues over Golds "for liquidity reasons". Alternative construction (recommended earlier in "Ringing in optimism"): **sell Blues CA hedged with an ED6/ED16 curve steepener with 0.74 : −1 DV01 weights** (hedges the vol/level directionality of CA fair value). Main risk: higher volatilities; outright chosen because "a flat curve environment is normally negative for vol".
- 2s10s-percentile conditional-return table (Fig 17; daily data 1971–2017, conditioned on last Fed move = hike): current 30–40% bucket (2s10s 43–62bp): 6m median flattener +13bp, hit 0.66; 1y +54bp, hit 0.74; also full 8-bucket table for long-2y/long-10y/flattener at 6m and 1y (quoted in file).
- Maintains 6m 5s30s / 2y 2s30s curve-cap switch; 6m-fwd-18m 2s30s implied curve vol 42 normals (3pm 4/18/2018); underlying curves correlated with beta ≈ 1.

### Overview: cycle-turn positioning
2s10s decile framework (Apr 1988–Apr 2017 sample; flattening episodes 1988-89, 1999-2000, 2005-06): current 2s10s 50bp = 40th decile; curve kept flattening 10–20 weeks after entering the 0–10 decile; 6m flattener returns positive in the 30–40 percentile bucket. Zero-coupon return tables into first cuts (9/18/07, 1/3/01, 6/16/89) at 6m/1y/1.5y/2y horizons for 2y/5y/10y/30y, raw and duration-adjusted (e.g. 2001 cycle 1y-ahead: 2y +1.1, 5y +6.2, 10y +14.3, 30y +26.4%; duration-adj 0.5/1.2/1.4/0.9). Conclusion: belly (5y–10y) is the sweet spot into cuts (basis of doc 4's "belly is the best place... heading into a rate cut" cite).

### Treasury RV: supply-week seasonality
Friday-to-Friday Δ10y since 2014 by auction-week type: first week +2.7/+2.7bp (46% rally); 3s/10s/30s week −1.9/−1.1 (56%); TIPS week −0.1/+0.4 (50%); empty week −3.9/−3.4 (69%); 2s/5s/7s −0.9/−1.0 (53%); final week −7.4/−6.0 (86%). Six-week-forward DV01-supply percentile vs next-2w Δ10y: 0–33rd −2.3/−1.1bp (61% rally); 33–66th −0.4/+0.8 (52%); 66–100th +1.8/+1.3 (46%).

### Model portfolio (pricing 3:00pm Apr 19, 2018; +1.32% YTD 2018)
Sell 10y inflation swaps vs short MXN calls 2.17 → 2.37% (−$895k); buy 1y4y 3s1s 8 → 10.59bp (+$259k); receive M8-U8 EURUSD XCCY −27.5 → −18.68bp (−$441k); UST 7s10s fly −18.6 → −15bp (−$270k); buy 30y spreads (hedged CDX IG receivers) −11.9 → −13.5bp (−$80k; view: 30y spreads should trade −10 to 0bp); 1x2 3m 2s10s curve floors 48 → 16.8bp (−$150k); sell 1y1y payers 2.931 → 2.93 (+$75k); M8/U8 FRA/OIS steepener −3.4 → −6.7 (−$165k); receive 1s vs OIS+3s 1y-fwd-1y −10 → +5.5bp (+$450k); 10y20y/5y30y swaption switch 51.4 → 51.5 (+$53k). Closed table 2017–Apr 2018 (Blues/Greens CA rows; also an unnamed row Feb 28 2017 → May 1 2017, −38.5 → −44.875bp, +$605k).

### Swap fly RV appendix (as of 4/19/2018 vs 1/19/2018) — 2018 vintage; note belly-cheap regime vs 2019 vintages
Equal-weight (Level / 3m C+R / 1m ZS): 2s3s5s +1.2/−0.1/−0.20; 2s5s10s +4.7/−0.7/1.31; 5s7s10s −0.5/−0.1/2.21; 5s10s30s +1.8/0.0/0.59; 7s10s30s +0.4/0.1/1.63; 5s20s30s +7.9/−0.3/−0.81; 10s20s30s +4.7/−0.1/−0.94; 15s20s30s +2.4/0.0/2.25.
PCA (weights/level): 2s5s10s −0.52:1:−0.57 / −22.2; 5s10s30s −0.47:1:−0.63 / −26.6; 7s10s30s −0.64:1:−0.41 / −13.8; 10s20s30s −0.24:1:−0.79 / −3.7.

### ED monitor (4/19/2018) — front contracts are Z8-rooted
Curves: Z8/Z9 +32.5; Z9/Z0 +6.5; Z0/Z1 +2.0; Z1/Z2 +2.4. Packs: White/Red +35.1; Red/Green +9.2; Green/Blue +2.6; Blue/Gold +2.6; Gold/Purple +3.3. Flies: Z8/Z9/Z0 +26.0 (PCA 1.1:2:1.2); Z9/Z0/Z1 +4.5; W/R/G +25.9 (1.2:2:1.1); R/G/B +6.6; G/B/Go +0.1; B/Go/P −0.7; CM 1y/2y/3y +16.4 (1:2:1.2). Appendix II market-hike-expectations tables; Treasury RV (4/19/2018); TIC section (Feb-2018 data: officials +$45bn val-adj LT UST; China +$16bn; Brazil +$12bn). Trailing boilerplate.

**Relevance:** Highest in set — the printed Blues-CA fair-value regression with coefficients (−0.65 + 0.044·(ED16 − 0.74·ED6)), the two-sigma-wide-to-model entry trigger, the sell-Blues-CA ticket at 7.2bp (3pm 4/18/2018) that becomes the closed 8.8→6.6bp 2017 ticket's sequel, the CA-hedged-with-ED-steepener construction (0.74:−1 DV01), and the packs-CA-vs-CFTC-positioning narrative. Also documents that Citi quotes pack CAs **vs CME swaps** specifically.

---

## 7. North America Rates Focus — "Corporate supply to bring spreads tighter"

**File:** `North_America_Rates_Focus_Corporate_supply_to_bring_spreads_tighter.pdf.md`
**Publisher/date:** Citi Research, North America Rates Focus, 03 Jan 2017 09:06:52 ET, 9 pages. Author: Ruslan Bikbov.

Short swap-spread tactical note; largely peripheral to the CA/fly program but with tie-out numbers:
- Trade: **10y swap spread tighteners** into a seasonal January corporate-supply surge. January = ~13% of annual financial supply (5y median); Jan fixed-rate financial issuance ~$45bn 5y avg vs $18bn Dec-16; Dec-16 financial issuance $24bn vs $42bn 2016 monthly avg; Jan-17 financial redemptions est. $36bn (vs 5y Jan avg $32bn, Dec $11bn); long-dated callable (Formosa) issuance est ~$5bn Jan vs $1.5bn Dec, redemptions ~$450mn (vs ~$1bn Jan-16). Dealers hedge callables by receiving 30y ⇒ pressure on 30y spreads. TLAC: Fed est. US G-SIB shortfall $49bn eligible LTD / $70bn total.
- Year-turn seasonality table (Fig 3, Δspreads in bp at 10d/5d before, 5d/10d/20d after year-end for 2y/3y/5y/10y/30y, 5y and 10y medians + 2016 realized): e.g. 10y median 10d-after: 10y −2.6, 30y −2.8; 30y spreads already −4bp off highs late Dec.
- **Regression: 10y vs 30y swap spread, y = 0.41x + 6.71, R² = 0.65** (sample 1/1/2016–1/2/2017) ⇒ 10y ~2bp wide to 30y ⇒ prefer 10s tighteners.
- Dec-16 widening attribution: post-election paying (mortgage/VA convexity hedging, dealer short-gamma delta-hedging at high strikes, bank swap unwinds) into thin liquidity. Fixed-rate share of financial issuance 75% in Dec (low end). Remainder of file is disclosure boilerplate.

**Relevance:** Low/peripheral — no CA, futures, fly, or positioning content; useful only as swap-spread seasonality/mechanics background and one dated regression tie-out.

---

## 8. North America Rates Focus — "Flatter skew is a warning signal for duration shorts"

**File:** `North_America_Rates_Focus_Flatter_skew_is_a_warning_signal_for_duration_shorts.pdf.md`
**Publisher/date:** Citi Research, North America Rates Focus, 12 Jan 2017 10:51:58 ET, 8 pages. Author: Ruslan Bikbov.

Three content pages; charts not preserved by OCR. Signal definition: **3m changes in the 3m10y 25-out (25bp OTM) risk reversal grouped into historical percentiles; average/median subsequent 1m Δ10y rate computed per percentile (monthly data Jan 2006–Nov 2016). Steeper (flatter) skew predicts higher (lower) rates over ~1 month.** Mechanism: core shorts hedged with low-strike options richen low strikes ⇒ skew reflects positioning; skew flattening = build-up of core duration shorts, consistent with **record short leveraged-money futures positions (CFTC, Fig 3)**. State at publication: 3m-skew-change moved from upper-75% percentile (2016) to the 50–75% bucket ⇒ duration shorts less convincing (not yet an outright long signal). This is the note referenced by doc 3 ("richer risk reversals have been a strong predictor of higher rates"). No numbers in the percentile table survive OCR; remainder is disclosures.

**Relevance:** Moderate — supplies the skew-as-positioning predictor definition used by the weeklies' positioning framework (companion to CA/CME-LCH positioning proxies); no CA/fly content of its own.

---

## 9. US Rates Trade Recommendation — "Receive Belly of 1-Year Forward 5s10s30s Fly"

**File:** `US_Rates_Trade_Recommendation_Receive_Belly_of_1_Year_Forward_5s10s30s_Fly.pdf.md`
**Publisher/date:** Citi (Citi Investment Research & Analysis), US Rates Trade Recommendation, 20 December 2010, 6 pages. Authors: Amitabh Arora, Dan Chen. Title in body: "Flying Too High: Receive Belly of 1-Year Forward 5s10s30s Fly".

### Full printed forward-fly trade ticket (Fig 6) — DV01-style notionals with option-like greeks
Receive belly of **1y-forward 5s10s30s swap fly**: **Pay $180mm 1y→5y at 2.971% (ATMF); Receive $200mm 1y→10y at 3.908% (ATMF); Pay $50mm 1y→30y at 4.344% (ATMF)**. Printed delta/gamma per leg: 5y +84,827 / −64; 10y −171,139 / +206; 30y +86,510 / −230; total gamma +198 (table's "Total" row shows 198 / −88). **Target 20bp, stop-loss 10bp.** (Note the fly here is quoted so belly-received value declines toward target — the target is computed as 28bp mispricing minus 8bp/a convexity cost.)

### Signal / fair-value method (a Fed-regime-probability-weighted fly fair value)
1. Back out market-implied future FF from Eurodollar futures + LIBOR-OIS basis swaps; via constrained minimization fit probabilities of staggered hiking-cycle scenarios (each culminating at FF 3.5% after 2y): P(hike starts 2011) = 30%, 2012 = 42%, 2013 = 28% (half-year buckets charted).
2. Historical regime means (swap space, bp): On-hold-after-cut / Start-of-hiking / 6m-into-hiking: 2s5s 129/106/69; 5s10s 93/74/55; 10s30s 69/63/49; **2s5s10s 36/32/14; 5s10s30s 24/10/6**. Regimes: hiking cycles from 02/1994 and 12/1994; on-hold periods 10/1992–02/1994, 01/2001–06/2004, 01/2009–present.
3. Predicted 1y-fwd value = probability-weighted regime means; worked example in note: predicted 5s10s30s = 9%·6 + 21%·10 + 70%·24 = **19bp**. Current values table (bp): spot / 1y-fwd current / 1y-fwd predicted: 2s5s 132/129/119; 5s10s 126/94/85; 10s30s 73/46/66; 2s5s10s 6/35/33; **5s10s30s 53/48/19**.
4. Trade selection logic: alternative 1y-fwd 10s30s steepener has +27bp/a carry but is rate-directional and costs **11bp/a convexity assuming 120bp/a realized vol** — "margin too thin". The 1y-fwd 5s10s30s fly receive-belly has **−5bp/a carry but only 8bp/a convexity cost and low rate directionality**. Target = (48 − 19 ≈ 28bp) − 8bp convexity ≈ 20bp. Historical context: 1y-fwd 5s10s30s consistently <40bp before Dec 2010; current 48bp exceeds the **98th percentile** of fly values even in the on-hold-after-cut regime.

**Relevance:** High for the fly leg of the program — a complete forward-starting 2-leg-vs-belly fly ticket with notionals, ATMF strikes, target/stop, plus an explicit convexity-cost accounting (bp/a at an assumed realized vol) and a regime-conditional fly fair-value model; the "fly = curvature vs Fed-regime" framework is the swap-side mirror of the CA fair-value work.

---

## 10. Alert: North America Rates Trade Idea — "Taking profits on long end butterfly trade"

**File:** `Alert_North_America_Rates_Trade_Idea_Taking_profits_on_long_end_butterfly_trade.pdf.md`
**Publisher/date:** Citi Research, North America Rates Trade Idea (Alert), 15 Jun 2020 17:21:37 ET, 6 pages. Authors: Jabaz Mathai, Jason Williams.

One page of content (rest disclosures). Trade unwound: **long-end forward swap butterfly — receive 20y10y vs pay 10y10y and 30y10y (1x2x1 fly)**, entered late Feb 2020 (ref US Rates Weekly: Taking a chill pill) to fade cheapness of 30y point vs 40y; **"beta adjustment that made it slightly net long dv01"**. Selection method: **efficient-frontier screen of long-dated/ultra-long swap butterflies on 5y z-score (valuation) vs 1y vol-adjusted carry**. Rationale for fly over outright long-end steepener: smaller convexity risks.
Tie-outs: **entry 16bp; unwind at current offer 10bp (pricing 4pm 6/15/20); P&L +$360k. Historical bid/offer on the structure ~3bp** — explicitly cited as the reason they could NOT take profits at the March-2020 max-P&L dislocation ("large transaction costs meant we couldn't realistically take it off"); unwound only once transaction cost normalized to ~3bp. Fig 1: 10y10y/20y10y/30y10y 1x2x1 fly history Jun-15→Feb-20, range roughly −15 to +30bp.

**Relevance:** High for the fly leg — a dated round-trip ticket on a forward 1x2x1 long-end fly with an explicit transaction-cost quote (~3bp bid/offer on the package) and the 5y-z-score × vol-adjusted-carry efficient-frontier selection recipe; direct evidence on realistic fly costs during stress.

---

## 11. J.P. Morgan RV Trade Note — "Pay belly of the 1Yx1Y/5Yx5Y/10Yx10Y EUR swap fly on valuations and relative value"

**File:** `RV Trade Note_ Pay belly of the 1Yx1Y_5Yx5Y_10Yx10Y EUR swap fly on valuations and relative value. Thu Jan 23 2020.pdf.md`
**Publisher/date:** J.P. Morgan (J.P. Morgan Securities plc), European Rates Strategy RV Trade Note, 23 January 2020 (completed/disseminated 23 Jan 2020 16:21 GMT). Authors: Khagendra Gupta (AC), Fabio Bassi, Sampath Vijay.

### Trade ticket (verbatim numbers) — forward-starting 50:50 fly with full notionals
**Pay the belly of the EUR 1Yx1Y/5Yx5Y/10Yx10Y 50:50 swap fly at 11.6bp** (fly defined as **2×5Yx5Y − 1Yx1Y − 10Yx10Y**):
- Pay **€100mn 5Yx5Y** (100% of risk; start 27 Jan 2025, end 27 Jan 2030)
- Receive **€251.8mn 1Yx1Y** (50% risk; start 27 Jan 2021, end 27 Jan 2022)
- Receive **€26.2mn 10Yx10Y** (50% risk; start 27 Jan 2030, end 27 Jan 2040)
Carry: **−2bp over 3M** (variant paying 10Y in spot 2s/10s/30s carries −1.5bp/3M but forwards preferred since the forward fly is ~7bp rich vs 2s/10s/30s). No explicit target/stop printed in the extract.

### Signal definitions with fitted regressions (all EUR, 50:50 flies)
- Richening: fly richened ~15bp in two weeks to levels last seen around the Sep-2019 ECB cut (10Y Bund −0.70%). Drivers: issuance-based receiving in 10Y, real-money receiving, fast-money unwinding 10Y-paid 2s/5s/10s flies.
- **Convex level relationship (Exh 2): fly vs 5Yx5Y swap yield, since 1 Jan 2018: y = 33.23x² + 10.56x + 15.44, R² = 99%; fly trading ~10bp too rich to this fit.** Linear 6M version residual ~11bp.
- **Cross-fly relationship (Exh 3): fwd fly vs spot 2s/10s/30s 50:50 fly, past 6M: y = 0.87x + 23.95, R² = 55%** ⇒ forward fly ~7bp rich vs the spot fly.
- **Level-and-curve-neutral (C&L) fly residuals (Exh 4), 6M regressions:**
  (a) 1Yx1Y/5Yx5Y/10Yx10Y fly = **11.49·(5Yx5Y level) + 31.93·(1Yx1Y/10Yx10Y curve) − 19.3; R² = 78%, SE = 2.9bp**
  (b) 2s/10s/30s fly = **41.1·(10Y level) − 12·(2s/10s curve) − 7.4; R² = 91%, SE = 1.6bp**
  Both C&L flies rich in the 6M regression, forward fly showing the larger residual; the C&L version is offered as the "pure RV" expression (pay 5Yx5Y in a level-and-curve-neutral fly).

**Relevance:** High for the fly-methodology leg — a complete forward 2-leg-vs-belly (50:50) fly ticket with notionals/dates/entry level and three distinct fair-value regressions (quadratic-in-level, cross-fly, and level+curve-neutral with SEs), i.e. the exact fair-value-regression family planned for CA-vs-fly models. EUR not USD, but the construction/weighting conventions (50:50 = −1:2:−1 in risk, quoted 2·belly − wings) transfer directly.

---

## 12. J.P. Morgan — "RV on the EUR swap yield curve: a historical perspective — Improve monetisation of curve dislocation via a beta-stability framework"

**File:** `RV on the EUR swap yield curve_ a historical perspective_ Improve monetisation of curve dislocation via a beta-stability framework. Wed Apr 07 2021.pdf.md`
**Publisher/date:** J.P. Morgan (J.P. Morgan Securities plc), European Rates Strategy, 07 April 2021 (completed 10:08 BST). Authors: Khagendra Gupta (AC), Fabio Bassi, Sampath Vijay. 19 pages.

### The systematic level-and-curve-neutral fly backtest — full spec
**Universe (3 categories of 50:50 flies, all level-and-curve neutral):**
1. Standard flies (spot, 1Y-fwd, 2Y-fwd, 5Y-fwd): 1s/2s/3s, 1s/2s/5s, 1s/3s/5s, 2s/3s/5s, 2s/5s/7s, 2s/5s/10s, 2s/7s/12s, 2s/10s/30s, 3s/5s/10s, 3s/7s/15s, 5s/7s/10s, 5s/10s/15s, 5s/10s/30s, 7s/10s/15s, 7s/15s/20s, 10s/12s/15s, 10s/15s/20s, 10s/20s/30s, 12s/15s/20s, 12s/20s/30s, 15s/20s/30s.
2. 5Y-tail non-overlapping 5Y-gap forward flies: forwards at 5s/10s/15s, 10s/15s/20s, 15s/20s/25s, 20s/25s/30s, 25s/30s/35s, 30s/35s/40s, 35s/40s/45s (first = 5Yx5Y/10Yx5Y/15Yx5Y).
3. 1Y/2Y gap (money-market) flies: 1Yx(1M/1Y/2Y), 1Yx(1Y/2Y/3Y), 1Yx(2Y/3Y/4Y), 1Yx(1M/2Y/4Y), 2Yx(1M/2Y/4Y), 2Yx(2Y/4Y/6Y), 2Yx(4Y/6Y/8Y), 2Yx(6Y/8Y/10Y).
**Model:** rolling **6M two-factor regressions** of each 50:50 fly on the body yield and the wing curve (e.g. 1Yx1Y/2Yx1Y/3Yx1Y fly vs 30Y yield and 2s/30s curve in Exh 1); residual = signal.
**Entry triggers — 12 combinations:** R² ∈ {60%, 80%}; |residual| ∈ {2, 3, 4bp}; |Z-score of residual| ∈ {1.5, 2}. **Best-performing combination: R² ≥ 60%, |Z| ≥ 1.5, |residual| ≥ 4bp.**
**Exits (first of):** (i) out-of-sample residual (computed with ex-ante betas) crosses zero (COB); (ii) residual worsens by another 2 SD (stop at 3.5 or 4 z); (iii) **1M horizon elapsed** — Fourier analysis of residual shows dominant mean-reversion frequency <1M (secondary peaks 2M/3M).
**Portfolio rules:** multiple simultaneous trades allowed (max = number of flies); never two open trades on the same fly (no re-entry on consecutive days while open); may re-enter the day after a stop-out. P&L computed out-of-sample with ex-ante betas; daily total P&L = sum over open trades (0 on empty days).

### Results (Jan 2001–2021; per-trade stats in bp of yield, Exh 7)
Overall by trigger (avg P&L bp / success ratio / # trades): 60-2-1.5: 0.7/50%/3587; 80-2-1.5: 0.4/47%/1964; 60-3-1.5: 1.0/52%/1929; 80-3-1.5: 0.6/48%/976; **60-4-1.5: 1.3/52%/1188**; 80-4-1.5: 0.8/48%/564; 60-2-2: 0.7/54%/2642; 80-2-2: 0.4/51%/1527; 60-3-2: 1.0/55%/1479; 80-3-2: 0.7/52%/785; 60-4-2: 1.3/55%/923; 80-4-2: 0.9/53%/457. Max/min per trade +39…+42 / −13…−19bp. Cumulative avg P&L since 2001 ≈ 1,000+bp (chart max ~1,400); most profitable in post-Lehman years, pace declining recently.
Good vs critical split: good-period averages 0.7–1.6bp, success 51–58%; critical-period averages −0.1…+0.5bp, success 38–48%. Max drawdowns occurred in "good" 2008-09 (Lehman-era volatility), not in critical periods.
**Critical periods (regime-change losses):** 3Q04–2Q05 (ECB hiking priced), 3Q07–4Q07 (easing priced; worst per-trade avg −2.9bp at 80-4-2, success 8–19% at 60/80-4-1.5), 2Q11–4Q12 (sov crisis + hikes/cuts; actually net positive), 2015 (QE + Bund VaR shock), 4Q16–1Q18 (taper pricing), **2Q19 (worst: success ratios 3–29%, avg −1.0 to −1.4bp)**. Exceptions where high vol was fine: post-Lehman, 2Q13 taper tantrum. Category performance: **MM (1Y/2Y-gap) flies best overall and in good periods; 5Y-fwd-gap flies best in critical periods** (front-end RV more "optical" during ECB regime shifts).

### The beta-stability "traffic light" indicator — definition and effect
Diagnosis: losses come when ex-post betas deviate from ex-ante betas (residual is "optical"); rolling 6M betas of 2s/10s/30s, 1Yx1Y/2Yx1Y/3Yx1Y, 5Yx5Y/10Yx5Y/15Yx5Y vs body yield are themselves volatile and ECB-regime-dependent (Exh 11/13).
**Indicator = √(Zb² + Zw²), where Zb (Zw) = 6M Z-score of the 3M volatility of the regression beta of the 50:50 fly vs body (wing), after adjusting for the wing (body).** Built on the 1Yx1Y/2Yx1Y/3Yx1Y ("reds/greens/blues") fly betas — its P&L is representative of the whole strategy (Exh 12); ideally build per traded fly (2s/10s/30s version also works, Exh 18). **Threshold: 3** (index ranged 0–7 since 2001; spikes above 3 coincide with the critical periods).
Validation: quarterly ex-post P&L vs ex-ante (1m-prior) index — positive-P&L sample: y = −6.87x + 238.69, R² = 0% (no relationship); **negative-P&L sample: y = −44.78x − 45.10, R² = 17%** (high index ⇒ bigger losses). Filter effect: **critical-period average P&L +~25% on average** (by period: 3Q07-4Q07 +0.3bp/+63%/+7% success; 2Q11-4Q12 +0.6bp/+149%/+6%; 2015 −0.3bp/−195%/−4% (worse); 4Q16-1Q18 +82%; 3Q04-2Q05 and 2Q19 unchanged); overall improvements up to ~35-40% in avg P&L at some triggers with success-ratio gains up to ~5-6pp (Exh 16, partially garbled).
Call at publication: indicator "flashing red" (betas unstable — USD-rates sensitivity, pre-PEPP-upsizing) ⇒ avoid systematic RV in EUR flies for now.

**Relevance:** Very high (methodology payload) — the complete recipe the ARBS backtests can port: fly universe construction (incl. forward-gap flies), 6M level+curve two-factor regression, residual/z/R² entry grid with the empirically best trigger (60%/1.5z/4bp), first-crossing / +2SD / 1M-horizon exits, per-trade bp-of-yield accounting, regime-failure taxonomy, and a concrete beta-instability risk filter with formula and threshold.

---

## Cross-document synthesis for the CA-vs-fly backtest program

**CA fair-value models (Citi):**
- Structural model: one-factor **Ho-Lee**, CA = f(volatility) (doc 4, Jan-2019); pack CAs quoted **vs CME swaps** (doc 6).
- Regression model: **Blues CA fair value = −0.65 + 0.044·(ED16 − 0.74·ED6)** with the caveat that the hedge fails at the ZLB (doc 6, Apr-2018) — the direct ancestor of the planned "Blues CA = a + b·(fly/curve)" models.
- Entry trigger observed in practice: CA ~2σ wide to model (doc 6); sell hedged with ED6/ED16 steepener 0.74:−1 DV01, or outright when curve view is flat.

**Printed CA trade tickets (known answers):** Sell Blues CA hedged: 2/9/2017 @ 8.8bp → 6/6/2017 @ 6.6bp (+$552k, tgt $600k, stop $350k). Sell Greens CA hedged: 6/6/2017 @ 4.3bp → 8/8/2017 @ 2.65bp (+$476k, tgt $450k, stop $225k). Blues CA vs CME 7.2bp mid at 3pm 4/18/2018 (doc 6). Blues CA chart ranges: ~2–12bp 2016-18 (vs model), Golds ~4–16bp.

**Positioning ⇒ CA (the dealer-positioning-conditioned leg):** ED CAs reflect macro positioning because futures are the capital-efficient instrument (doc 6); levered-fund/AM CFTC ED net % of OI vs Blues CA charts in docs 3, 4, 6; short base ⇒ CA above model; covering/longs ⇒ CA at/below model. 10y CME-LCH basis as back-end positioning proxy: 3m-change corr 31% vs TY spec/OI, 51% vs Δ10y (doc 4). AM ED selling in mid-2019 ⇒ CA widening + 30y-led CME/LCH tightening (doc 3).

**CME-LCH basis (clearing-basis-conditioned leg):** existence mechanism = real money structurally pays CME, dealers hedge paying LCH, dual IM costs passed through as the basis (doc 5, with IM $-table); level tie-outs: near 0 → ~2bp May-2015 (doc 4); 10y ~1.0–4.5bp 2015-18 (doc 4); 30y range −1 to +6bp 2015-19 (doc 1); **30y = 0.8bp on ~8/1/2019, tightest since 2015** (doc 3); drivers: SOFR IM-exemption expectations (structural) + positioning unwinds (cyclical) (docs 1, 3, 5).

**Fly construction conventions:** Citi swap flies −0.5:1:−0.5 (equal) and PCA (3rd PC of legs, 5y rolling window; built to have zero beta/corr to belly); ED flies 1:2:1 and PCA (quoted like 0.9:2:1.4); ED fly rich/cheap = regression vs own belly, −residual = rich. JPM 50:50 flies quoted 2·belly − wings with 100%/50%/50% risk allocation; level-and-curve-neutral versions via 6M two-factor regressions. Forward flies: Citi 1x2x1 10y10y/20y10y/30y10y (~3bp package bid/offer); JPM forward-gap families.
**Costs quoted anywhere in the set:** long-end fwd fly package ~3bp bid/offer (doc 10); long-dated curve initiation 0.75–1bp, delta-hedge/roll 0.3–0.4bp one-way (doc 2); Citi model-portfolio P&L excludes transaction costs ($300mn sizing basis).

**Fly RV table vintages available as tie-outs** (equal-weight and PCA, ~29 structures each): 4/19/2018, 1/17/2019, 5/9/2019, 5/16/2019, 8/1/2019, 10/3/2019 — plus ED curve/pack/fly monitors on the same dates. These six dated snapshots are the densest known-answer sets in the corpus for a matched-maturity fly reconstruction.

**Systematic frameworks to port:** Citi delta-hedged long-dated flattener program (daily-breakeven vs realized vol; $100K DV01, 25bp rehedge; Sharpes 0.05–0.35) — doc 2; JPM beta-stability framework (6M regressions, 60%/1.5z/4bp trigger, 1M horizon, √(Zb²+Zw²) filter at 3) — doc 12; Citi CFTC-positioning-vs-roll-valuation regressions (FV R² 0.64, WN R² 0.825) — doc 2.

