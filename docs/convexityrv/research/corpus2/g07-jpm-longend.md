# G07 — JPM long-end convexity corpus (curve-as-gamma framework, convexity-hedger flows, ultra-long RV)

Reading group: 11 markdown conversions from `C:/Users/chris/Downloads/convexityrv_markdown`.
Theme of this group: J.P. Morgan's "yield curve as a cheap option" framework (Younger/Salem/Sarkar/Salford et al.), the convexity-hedger flow landscape (MBS, banks, VA, Formosa callables) that drives rate/spread/fly directionality, and ultra-long-end swap fly RV. Nothing in this group is directly about SR3 packs/bundles or CME-LCH basis, but the fair-value-regression machinery (fly = f(curve, flow proxies), breakeven-vol vs swaption-implied-vol) is directly reusable for the CA-vs-fly program, and several fitted regressions with coefficients/R² are quoted verbatim below for tie-outs.

---

## 1. An option by any other name — Sourcing cheap convexity in the long end of the curve
**J.P. Morgan, North America Fixed Income Strategy, 03 Feb 2017** (completed 03 Feb 2017 4:39 PM EST). Authors: Joshua Younger (AC), Devdeep Sarkar, Munier Salem.

**Core framework** (foundational piece cited by every later report in this group):
- PVBP-weighted curve flatteners have an options-like (straddle-like) payoff under large parallel moves due to convexity differentials between tenors: in a selloff the longer receive-fixed leg loses dollar duration faster than the shorter pay-fixed leg gains it → positive P/L; vice versa in a rally.
- 30s/50s is the canonical structure; "the vast majority of P/L variance for 30s/50s flatteners over the past ten years is attributable to convexity effects" (Exhibit 2 attribution over 1-yr horizons, trades initiated daily, held forward-to-spot; carry = ex-ante spot-forward difference, curve = change in spot curve, convexity = remainder).
- **1-year breakeven parallel shifts** (Exhibit 1, minimum parallel shift on a 1-yr forward flattener held to spot to offset carry, as of 30-Sep-14 and 2-Feb-17): chart runs 0–600bp across pairs 2s/5s, 5s/10s, 5s/30s, 10s/30s, 30s/50s — breakevens fall monotonically with maturity; 30s/50s smallest.

**Signal definitions (verbatim mechanics):**
1. *Expected payoff*: extract implied distribution from ATMF+OTM 1Yx30Y swaption pricing; multiply against payoff profile of an aged flattener at fixed coupon (incorporates carry); assume parallel shifts; 1-yr horizon. Positive expected payoff ⇒ curve is the cheaper source of long gamma.
2. *Curve-implied vol*: assume normal terminal distribution of parallel shifts; solve the std-dev giving zero expected payoff over the horizon ("level of normal daily volatility sufficient to offset carry"). Curve-implied vol < 1Yx30Y ATMF swaption vol ⇒ curve cheap. Both measures in bp/day in Exhibit 4 (axis 0–10 bp/day; expected payoff axis −100…+500 bp of notional).
- Around 2008, curve-implied vol stayed roughly constant while swaption vols spiked ⇒ curve gamma outperforms in risk-off.

**Backtest (trades initiated daily after Jan-2009, Exhibit 5) — key known-answer table:**
Trading rule: when ex-ante expected payoff > 0, initiate flattener and *sell* 1Yx30Y ATMF swaption straddles sized so premium intake = 1-yr carry cost of the flattener; when < 0, reverse both legs. (When carry is positive, buy the straddles.)

| Statistic | 30s/50s | 25Y/20Yx5Y |
|---|---|---|
| % of time curve gamma cheap | 70% | 100% |
| Hit rate | 56% | 86% |
| Avg P/L (bp of notional) | 10.4 | 11.4 |
| Carry (bp of notional) | −100.6 | +1.1 |
| 25th/75th pct P/L | −43 / 75 | 4 / 19 |
| 5th/95th pct P/L | −140 / 128 | −10 / 33 |

- Conclusion: **forward curve flatteners (25Yx5Y vs 20Yx5Y) are a cheaper, more reliable long-gamma source than spot 30s/50s** — lower (often positive) carry, more consistent cheapness.
- SDR flow confirmation (Exhibit 6): rolling 1-yr ADV in >30Y-maturity swaps and >20Y-fwd-term/≤10Y-maturity swaps, in $mn of 10-yr equivalents (axis 500–3500), rising through 2014-2017, favoring forward-space flatteners.

**Relevance to CA-vs-fly:** the expected-payoff / breakeven-vol machinery is exactly the fair-value engine one can apply to SR3 CA (which is also a convexity-carry trade priced vs options): compare CA carry to option-implied variance. Also a template for "curve trade vs vol" RV backtests with a carry-funded option leg.

---

## 2. Interest Rate Derivatives: A comprehensive look at convexity hedging in interest rates
**J.P. Morgan, US Fixed Income Strategy / FIMW Interest Rate Derivatives section, 29 Mar 2019** (cover dated Sat Mar 30 2019). Authors: Younger (AC), Salem, St John.

**Landscape census of convexity hedgers** (drives rate/spread directionality — background for dealer-positioning-conditioned CA models):
- Since rates peaked Nov 2018: **>$200mn/bp of duration demand** delivered via convexity channel; callable-bond offset **>$100mn/bp in the past month alone**. Comparable to taper tantrum, well below summer-2003.
- Episode date windows used throughout (Exhibit 1 note): 2003 rally 6/3/03–8/1/03; taper tantrum 5/2/13–7/5/13; early 2016 12/29/15–2/11/16; Trump election 11/4/16–12/16/16; early 2018 1/3/18–2/21/18.
- **Rate/spread directionality**: higher rates/wider spreads, lower rates/narrower spreads; kicks in only in later stages of a repricing; much more muted post-crisis (Exhibit 3, avg 10Y MM spread move vs 10Y swap yield move buckets, split 2000-09 / 2010-16 / 2017-present, y-axis ±8bp).
- **GSEs**: retained portfolios ~$850bn pre-crisis → **<$200bn** (−80%); diminished swaption/vol footprint.
- **Banks**: ~30% of agency MBS market (~$2tn notional); assume **~20% actively hedged**.
- **mREITs**: ~$280bn agency MBS+TBA; duration gap and dollar convexity tracked via **quadratic fit to reported rate sensitivities of NLY, AGNC, CMO, CYS** (Exhibit 6); ~¼ of actively-hedged MBS duration contraction since Nov.
- **MSRs**: top-4 banks >50% pre-crisis → ~25% share; modeled as a **30bp IO strip off the index**; largest single component of current convexity hedging but near/past peak negative convexity.
- **MBS universe peak negative convexity is 70–100bp lower in rates**; convexity exposure could rise ~30% if rates fall 70bp+; 2018 vintage the exception (near peak already).
- **Programmatic gamma sellers**: modeled as **daily sales of $500mn 1Mx10Y ATMF straddles** held to expiry; overall size at most $10mn/bp; returns net of costs maximized with a modest **~25% delta rebalancing threshold**; with thresholds, **$3–4mn/bp of rebalancing occurs on 10–20% of days** (Exhibit 9).
- **Callable/Formosa channel (positive-convexity offset)**: >15-20yr maturity, 1-10yr lockouts, Taiwanese regs favor 30nc5. Dealers long convexity via cancelable swaps; aggregate position at times **~$200mn/bp** (Exhibit 10); ~**40% (vega-weighted)** placed with end-users via **Bermudan-vs-first-call-European "B/E switches"**; delivered **~$56mn/bp pay-fixed flow since late-2018 ($34mn/bp past month)**; ~25bp below peak convexity, sensitivity stays 80-90% of current in a further rally, only decays meaningfully in a 50bp+ rally (Exhibit 11).
- **Variable annuities**: rate sensitivity of VA liability duration has fallen (rolling 1-yr partial betas, per 25bp of 30Y and per 5% S&P; Exhibit 12); long-end 30Y MM spreads now driven far more by **5s/30s Treasury slope** than VA flows (Exhibit 13, rolling 1-yr correlations).

**Trades (as of 3/29/19, exact tickets):**
- Sell $100mn 3Yx27Y Bermudan receiver (first notif 3/28/22, annual, mat 3/30/49, strike 4.5%, **premium 3585bp of notional**) vs buy $100mn 3Yx27Y European receiver (same dates, 4.5%, **premium 3523bp**); buy $100mn 5Yx25Y Bermudan receiver (first notif 3/28/24, mat 4/2/49, strike 3.0%, **premium 1385bp**) vs sell $100mn 5Yx25Y European (**premium 1161bp**). (B/E switch RV; i.e., Berm-minus-Euro premium 62bp at 4.5% strike vs 224bp at 3.0%.)
- Take profits: 3Mx2Y vs 3Mx30Y ATMF straddles, P/L +6.9abp (entry 3/1/19: long $1.5bn 3Mx2Y ATMF straddles @35c vs sell $141mn 3Mx30Y ATMF straddles @415c).
- Trade-log tallies: 55 closed trades/12mo, 41 winners, 79% hit rate. Notable rows: "Sell EDZ1 versus EDZ0 Eurodollars 09/28/18–01/04/19 +7.0bp"; "Reds/Blues conditional bear steepeners 09/07/18–12/11/18 0.0".

**Relevance**: this is the flow-driver map for a dealer-positioning-conditioned CA model (whose receiving pressure moves the swap leg of CA), and the source of the "spread directionality" regressors.

---

## 3. Interest Rate Derivatives: For cheap gamma, look to the long end
**J.P. Morgan, US FIMW – Interest Rate Derivatives, 23 Aug 2019.** Authors: Younger (AC), Salem, St John. (File "(1)" copy read; the non-(1) duplicate in the directory is the same publication.)

**Key fitted regression (tie-out):** 10s/20s/30s swap butterfly fair value = **5Y regression of the 10s/20s/30s fly on (i) the 10s/30s curve and (ii) VA liability durations; R² = 98%, std error = 0.5bp** (Exhibit 4 footnote). Fly level axis 0–20bp; residual axis ±1.5bp. Used to call 20s "stretched" after convexity-receiving (VA + servicers) richened 20s: **>$60mn/bp of long-end duration demand since late-July**, much of it in Libor swaps.
- 20s/40s flattener implied-vol vs 1Yx30Y swaption vol (both abp, axis 40–90) and expected payoff (bp yield, −1.0…+4.0) per the 2017 framework (footnote restates the method verbatim: swap-implied vol solves for the level of vol making expected convexity P/L exactly offset 1-yr slide under parallel shocks; expected payoff uses swaption-implied vol).
- Exhibit 6 scatter: 1Y expected payoff vs ex-ante 1Y slide for flattener right legs 35Y/5Y (payoff ~6-8bp, slide ~−2bp), 30Y/10Y, 25Y/15Y, 20Y/20Y, 15Y/25Y, 10Y/30Y, 5Y/35Y and left legs 5YFwd15Y, 10YFwd10Y, 15YFwd5Y; **carry-optimized pick: pay 15Y/5Y vs receive 35Y/5Y**.

**Trades (exact):**
- **Conditional 10s/20s/30s widener in a selloff**: Buy $100mn 25-delta 6Mx20Y payers (notif 2/24/20, mat 2/27/40, ATMF 1.61%, 25d strike 1.94%, prem 135c) vs sell $93mn 25d 6Mx10Y payers (ATMF 1.44%, 25d 1.77%, prem 71.5c) and $35.6mn 25d 6Mx30Y payers (ATMF 1.65%, 25d 1.95%, prem 196c). Premium-neutral, 50% risk weight per wing vs belly.
- **Ultra-long flattener**: Pay $250mn 15Yx5Y (start 8/29/34, mat 8/30/39, coupon 1.83%) vs receive $357mn 35Yx5Y (start 8/28/54, mat 8/28/59, coupon 1.49%) @ spread **−35.7bp**; 1-yr slide −2bp. (Closed 1/10/20 at **+7.9bp** per the Feb-2020 weekly's log.)
- mREIT 2Q19: duration gap contracted to **0.7 $mn/bp** (record low; prior record 5.7 $mn/bp in 2Q12); convexity −6.7 → **−5.7 $bn/10bp**; P/B <100% ⇒ hedging via swaps ⇒ bearish intermediate spreads.
- U9/Z9 futures roll table (data as of 2/20/19... as printed): WN 194-01, cal spread −0-31/32nds, HR 974, CTD 3 Nov44/3 May45; US 165-00, +0-26, HR 995, 4-1/2 Feb36 both; UXY 143-11+, −0-19+, HR 960; TY 130-23+, −0-20+, HR 950; FV 119-12+, −0-14, HR 932; TU 107-27, −0-08+, HR 854. Bearish all six.
- Vol cyclical: Sep seasonal ~−5abp in 3Mx10Y, observed 7 of past 9 years.
- Trade-log tallies: 62 closed/12mo, 46 winners, 77% hit rate.

**Relevance**: the fly-fair-value-from-(curve, flow) regression with quoted R²/SE is the closest published analogue to the planned "Blues CA = a + b·fly" style models, and the 10s/20s/30s fly is exactly the matched-swap-space belly instrument for Greens/Blues-area CA comparisons.

---

## 4. Interest Rate Derivatives: Is bank convexity hedging lying in wait?
**J.P. Morgan, US FIMW – Interest Rate Derivatives, 31 May 2019.** Authors: Younger (AC), Salem, St John, Jimmy (Guanjie) Huang.

- Rates −17 to −23bp on the week (Mexico tariffs); JPM economists pencil two 2H19 cuts; OIS+swaption-implied probability of cuts within a year **>80%**.
- Rolling 3M beta of weekly MM-spread changes on yield changes near post-crisis positive highs (Exhibit 3, by contract 2Y…30Y, betas ±0.2 range, 10-yr lookback percentiles).
- **Duration delivery to GSEs/REITs/servicers since Nov-2018 peak in yields ~$200mn/bp — rivals taper tantrum; nearly a quarter of it in the past two weeks.**
- **Bank balance-sheet convexity model (Exhibit 5 assumptions, verbatim parameters)**: assets from FRB H.8 (4/3/19); liabilities from 1Q19 LCR disclosure; MBS modeled off JPM Agency MBS Index cohorts; MSR = 30bp IO strip; **retail deposit beta 0.45, wholesale 0.65, both +0.15 per 100bp**; banks >$250bn assets (sample: JPM, C, BAC, WFC, MS, GS, BK, USB, COF, TD, PNC, SCHW, HSBC NA); book equity assumed 9.5% of assets.
- Results: banks' equity duration ~**5 years short** currently (~3 years as of 1Q-end); another 6-7 years shed if −100bp. **In a 50bp rally, portfolio durations shorten another $300-400mn/bp; aggregate delivery would exceed $300bn 10-yr equivalents** (headline). Even 25% hedged ⇒ >$100mn/bp receive-fixed flow. Hedging channel: receive fixed vs C&I/CRE floaters (Libor-linked) ⇒ swap-spread and tenor-basis narrower; cited as why intermediate FF/Libor traded below fallback levels.
- Threshold nature ⇒ **asymmetric spread directionality: narrowing in a rally > widening in a selloff**.
- **Trades**: Sell current 5s vs OIS — sell $200mn 2.00% May-2024 vs receive $200mn 5/31/24 OIS @ **matched-maturity Tsy/OIS 23.3bp** (3M carry ≈ −1bp, slide flat). Sell 1,000 TYQ 128.5 calls (prem 27c, exp 7/26/19, ATM 127) vs buy $130mn matched-expiry receiver swaptions (prem 21.7c, swap 9/3/19–4/30/26, strike 1.67% vs ATMF 1.96%), premium-neutral. Take profits short 3Mx30Y 1x2 receiver spreads +10.2bp.
- ML bond-trading update: passive long 10Y Sharpe 2.5 over 8 months; original model 1.1 (selling ~35% of days, ~+0.5 Sharpe vs randomized benchmark); retrained-through-3Q18 model Sharpe 1.27, selling ~half of days, >95% confidence vs benchmark. Episode table (Exhibit 12) quotes sell-fraction/avg-return/conviction for year-end-2018, Mar-2019, Apr/May-2019 rallies and Mar/Apr selloff.
- Trade-log tallies: 58 closed/12mo, 40 winners, 73% hit rate.

**Relevance**: bank/positioning-conditioned spread (and hence CA) directionality with explicit thresholds and magnitudes; the deposit-beta parameters are usable to rebuild the bank-convexity regressor.

---

## 5. Interest Rate Derivatives: Renewed Formosa supply continues to flatten the long end
**J.P. Morgan, US FIMW – Interest Rate Derivatives, 21 Feb 2020.** Authors: Younger (AC), Salem, St John.

- Ultra-long USD swap curve **>1bp flatter since January, 3bp since year-end**; driver = record Formosa redemptions/reissuance: **~$20bn notional called/announced for Q1 2020 (~$14bn cash returned), ~$14.5bn new deals; +$7bn more expected in March**.
- Newer **40nc5** structures (vs earlier 30nc5) ⇒ more 20-50Y partial duration; **Q1 duration supply ≈ $9bn 10-yr equivalents, headed for record $14bn+**; majority swapped via cancelable swaps.
- Fair-value gate (Exhibit 3): expected payoff and **swap-vs-swaption implied vol ratio** for 20Y/40Y, 40Y/50Y, 30Y/50Y flatteners — all "notably steep to fair" (ratio axis 0-100%; payoff axis 0-2.5bp); method footnote again restates the 2017 An-option-by-any-other-name definition verbatim.
- Vega: Q1 new vega supply at levels last seen early 2018, unprecedented 20Y+-expiry supply; dealer dVega/dRate near saturation, biased to be **delivered long vega in a selloff** — incrementally bearish long-dated implieds.
- **Trades**: Stay in **30Yx10Y vs 10Yx10Y flattener**: receive $185mn 30Yx10Y (start 1/28/50, mat 1/26/60, coupon 1.70%) vs pay $125mn 10Yx10Y (start 1/28/30, mat 1/30/40, coupon 2.09%) @ **−39bp**, 1-yr slide −4bp; P/L +3.0bp. Receive 2Yx1Y EUR/USD xccy basis $25k/bp @ −12.8bp. 10Y/20Yx10Y vega-neutral vol flattener: short $50mn 20Yx10Y ATMF straddles (ATMF 1.967%, prem 1230c) vs long $58.4mn 10Yx10Y (ATMF 2.067%, prem 1185c).
- FX/OIS regression table (Exhibit 8, daily Jun-2012–present; per currency betas/t-stats on FRA/OIS, leveraged-fund positioning, AM positioning, NFA; R² 36–76%; e.g., EUR: FRA/OIS β −0.84 (t −22.3), NFA β −0.06 (t −17.7), R² 55%, residual 15.6bp).
- Trade-log tallies: 44 closed/12mo, 33 winners, 75% hit rate. Log includes **"1Y5Y/5Y vs 35Y/5Y swap yield curve flatteners 08/23/19–01/10/20 +7.9"** (the Aug-2019 recommendation) and "15Y/25Yx15Y swap yield curve flatteners 04/26/19–07/26/19 +4.1".

**Relevance**: supply-flow conditioning of long-end fly/flattener fair value; the swap-vs-swaption vol *ratio* as a normalized cheapness score is a clean, portable signal format.

---

## 6. Interest Rate Derivatives: The long and short of it
**J.P. Morgan, US FIMW – Interest Rate Derivatives, 03 Aug 2018.** Authors: Younger (AC), Salem.

- **30Y spread fair-value regression (verbatim spec)**: "We regress 30-year swap spreads against the 5s/30s Treasury yield curve (X1), 1-year ahead budget deficit expectations (X2), estimated variable annuity hedging flows (X3) and the WAM of marketable Treasury debt (X4)." Findings: ~30bp of 30Y spread widening over the past year mostly attributable to the ~75bp 5s/30s flattening; curve partial beta **more than doubled** while deficit and VA betas stable; model says current level "a bit rich" (Exhibit 5 actual-vs-fair, range −70…+10bp since 2013).
- **Trade**: Sell 30Y MM spreads vs 50% duration risk in 10s/30s flattener — sell $25mn 3.125% May-2048, receive $47.6mn 5/15/48 swap @ **spread 4.54bp**, sell $57.8mn 2.875% May-2028; 1-mo carry+roll −0.5bp. (Closed 9/14/18 +1.0bp per later logs.)
- Front end: Sell 4000 EDZ9 @ **96.96** vs sell matched-notional Z8xReds ATM midcurve puts (OTM strike 96.875, exp 12/14/18, prem 10bp) — covered-put structure motivated by rich midcurve vol and mean-reversion ratio diagnostics (Exhibit 1: 3M realized vol daily/monthly ratio ÷ √21 across Whites…Golds).
- CME/LCH section (qualitative but useful background): clearing mandate 2013 covered ~73% of market rising to 85% by 2017; volumes +35% while gross notionals −10%; **CME-LCH basis arose from segmentation of clearing activity — dealers net received at CME priced IM costs into lower LCH par rates; as basis widened, asset managers' IM-optimization advantage at CME eroded → reallocation to LCH** (LCH share of IRS clearing and dealer IM share tracked in Exhibit 8; USD dealer LCH gross-notional share up Q1-2015→Q2-2018, JPY migrating to JSCC instead on a double-digit basis). Uncleared-margin phases: Phase 1 Sep-2016 >$3tn covered >half of uncleared exposure; Phase 3 ($1.5tn, 2018) marginal.
- Trade-log tallies: 52 closed/12mo, 39 winners, 81% hit rate. Log includes "Add cheap convexity with 40Y/20Yx10Y flatteners 02/10/17–08/04/17 +10.5".

**Relevance**: the four-factor spread fair-value spec is the pattern for a CA fair-value regression with flow covariates; the CME-LCH mechanism paragraph is the best concise causal statement of the clearing-basis driver in this group.

---

## 7. Interest Rate Derivatives: The return of convexity hedging
**J.P. Morgan, US FIMW – Interest Rate Derivatives, 31 Jan 2020.** Authors: Younger (AC), Salem, St John.

- Primary mortgage rates −30bp since Nov ⇒ agency MBS back at **maximum negative convexity** (JPM Agency MBS Index OA convexity chart vs 30Y primary rate, −0.5…−2.0 yrs/100bp over 3.25–5.00%).
- Banks: gross unhedged short-duration exposure ≈ **$1tn 10-yr equivalents**; even if flat at year-end, **~$275mn/bp more to hedge** at current levels.
- REITs entered 4Q19 with a **negative duration gap** — little tolerance for further rally.
- **Intermediate spread fair value**: simple regression of 10Y MM spread on bank-convexity exposure + 3M GC/OIS ⇒ spreads **3-5bp too wide** (Exhibit 3; axis −15…+10bp) → **receive TYH0 invoice spreads**: sell 1,000 TYH0, receive $133mn matched swap (start 3/31/20, end 11/15/26) @ **−5.95bp**.
- 2s/10s conditional bear steepener: sell $500mn 3Mx2Y ATMF payers (strike 1.33%) @23.2c vs buy $86.54mn 3Mx10Y ATMF payers (strike 1.47%) @134c; rationale includes rolling 3M selloff-only beta of 10Y vs 2Y weekly changes >1 for most of 2 years (Exhibit 5, 0.4–1.8 range).
- 1Y 2s/10s/30s OTM conditional receiver fly (ACM term-premium replication): sell $100mn 1Yx10Y 20d receivers (strike 0.92%) @88c vs sell $258mn 1Yx2Y 25d (0.80%) @22.7c and $11.2mn 1Yx30Y 25d.
- Week-on-week 3M-expiry implieds +7.1/+7.4/+6.5/+6.3abp in 2/5/10/30Y tails.
- Trade-log tallies: 43 closed/12mo, 32 winners, 74% hit rate.

**Relevance**: template for a two-regressor spread/CA fair-value with a funding-conditions control (GC/OIS) — directly analogous to conditioning CA on SOFR-funding/clearing variables.

---

## 8. Interest Rate Derivatives: Zen and the art of gamma maintenance
**J.P. Morgan, US FIMW – Interest Rate Derivatives, 09 Mar 2018** (completed 3/9/18 7:21 PM EST). Authors: Younger (AC), Salem, Zhan Zhao.

- Programmatic gamma-seller stock model: **daily sales of $500mn 1Mx10Y ATMF straddles held to expiry; Jan-Feb 2018 assumed at 25% of that flow, March at 50%** (Exhibit 3, net gamma exposure axis 0–40 $bn 1Mx10Y straddle equivalents).
- **Expiry-curve fair value regression (verbatim)**: 3Mx10Y/2Yx10Y ATMF vol ratio modeled by "a 2-year regression … against the average of the two implied volatilities, an estimate of gamma supply from programmatic sales and the level of the VIX" — 3M should trade "well below 90%" of 2Yx10Y; further supply recovery worth another ~5% of ratio.
- **Kurtosis-conditioned gamma signal**: significance of trailing 1-month excess kurtosis in daily 1Mx10Y swap-yield moves (−log10 p-value; 1.3 = 95% threshold). Short 3Mx10Y daily-delta-hedged ATMF held 1M performs substantially **better after high-kurtosis** periods; short 1Mx10Y held to expiry performs substantially **worse when initiated on significant-kurtosis days**; low kurtosis + rising vol ⇒ long-vega/short-gamma calendars win. Robustness: 1000 half-sample bootstraps; performance metric = average of nonparametric Sharpe (median/IQR), Sterling (median return/median loss), drawdown ratio (return/5th pct).
- **Trade**: Sell $50mn 3Mx10Y ATMF straddles (notif 6/11/18, mat 6/13/28, strike 2.946%, prem 231c) vs buy $50mn 2Yx10Y ATMF straddles (notif 3/9/20, mat 3/11/30, strike 3.048%, prem 688c), delta-hedged. Unwind 1Yx30Y 25d strangle vs 3Mx30Y ATMF straddle +1.1bp.
- Taiwan lifers extending FX hedges 3M→1Y (term structure of USD/TWD onshore & NDF basis inverted, Exhibit 7); ~75% of JPM's four-hikes-in-a-year forecast priced.
- ARRC paced-transition table (Exhibit 9): SOFR publication 4/3/18; futures/OIS infrastructure 2H18; cleared EFFR-PAI OIS Q1-19; SOFR PAI/discounting choice Q1-2020; EFFR PAI closed to new trades Q2-2021; term rate end-2021. PAI switch ⇒ **$1,000-1,500mn/bp term FF/SOFR basis risk** (taking avg swap-market duration ~7yr; CCP-facing MTM up to $2.25tn(sic, printed "$2.25bn")).
- Trade-log tallies: 48 closed/12mo (options table 51), 35 (37) winners, 78% (77%).

**Relevance**: the kurtosis-conditioned entry rule and the vol-ratio fair-value regression are portable conditioning ideas for CA-vs-fly mean-reversion (regime gates on realized-tail behavior).

---

## 9. Valuing convexity in the long end of the yield curve — A global perspective
**J.P. Morgan, Global Fixed Income Strategy, 09 Feb 2018** (completed 4:17 PM GMT). Authors: Gianluca Salford (AC), Younger (AC), Salem, Khagendra Gupta, Jay Barry, Francis Diamond, Aditya Chordia, Zhan Zhao.

**The formal fair-value framework (verbatim math, OCR-garbled in the file but reconstructable):**
- ΔP = −PVBP·ΔY + 0.5·Γ·(ΔY)², and expected return over horizon T for maturity M, yield Y, funding F, expected vol σ: E(R) = carry + slide + **0.5·σ²·Γ/PVBP** ("value of convexity"). Convexity value scales with instrument convexity and σ².
- Convexity share of total return under instantaneous parallel shocks (Exhibit 1): at ±100bp, **>20% of P/L for 50Y swaps vs <2% for 2Y**.
- Duration-neutral ultra-long flatteners have straddle-like payoff; hence **30s/50s typically trades inverted across currencies** (Exhibit 4: 10-yr ranges for USD/EUR/GBP/JPY, axis −60…+20bp).

**Known-answer tables:**
- French OATs (Exhibit 2; carry/slide/convexity/expected return, 3M realized vol 3.0bp for all, RAC): May-48: 10.6/2.0/3.3 → 15.9, RAC 0.33; Apr-55: 10.7/1.0/3.6 → 15.4, 0.32; Apr-60: 9.9/0.2/4.1 → 14.2, 0.30; May-66: 7.9/−1.0/4.9 → 11.8, 0.25. (All bp of yield, 3M horizon.)
- 30Y+ EGB universe (Exhibit 9): 11 bonds ex-private-placements, total **€68.1bn** (e.g., FR Apr-55 €14.9bn, Apr-60 €13.1bn, May-66 €9.1bn; IT Mar-67 €6.6bn; ES Jul-66 €7.6bn; AT Nov-86 €2.5bn "century" etc.). Only 2.5% of EGB conventional stock. 30Y EGBs beat ultras at current vol; **doubling vol flips it** (expected-return curves become upward-sloping ex-Italy); 70Y/100Y RAGBs already out-yield some core 50Ys in expected-return terms. Ultra headwinds: ECB QE caps at 31Y (segmentation), poorer liquidity.
- **EUR swap 1Y value of convexity (Exhibit 15, bp of yield, since euro inception)**: Current 1.2/2.3/3.3/3.9/4.5 for 10/20/30/40/50Y; High 7.6/17.9/31.4/39.2/45.9 (Lehman); Low 1.1/1.8/2.3/2.8/3.1; Avg 2.5/4.4/6.1/7.4/8.6; SD 1.0/2.2/3.8/4.8/5.7; Z −1.3/−0.9/−0.7/−0.8/−0.7; %ile 1/3/15/13/16%.
- Breakeven-vol ratios vs 50Y (Exhibit 16): 30Y current 107% vs breakeven 89% ⇒ **~20% decline in 30Y vol needed** to equalize 30Y and 50Y expected returns; 35Y 106%/100%, 40Y 106%/100%, 45Y 102%/101% (approx readings). **Doubling vol quadruples convexity value** (σ² scaling).
- **GBP swap 1Y convexity value (Exhibit 22, since Jan-99)**: Current 2.0/3.5/4.9/6.1/7.3 (10/20/30/40/50Y); High 6.6/10.9/14.6/18.1/20.9; Low 1.3/2.0/2.4/2.9/3.4; Avg 3.1/4.9/6.2/7.6/8.8; SD 1.1/1.8/2.5/3.1/3.7; Z −1.0/−0.8/−0.5/−0.5/−0.4; %ile 21/29/39/40/40%.
- Gilt convexity-vol fit (Exhibit 20): 1Y convexity value of 3H68 vs daily yield vol x: **y = 0.49x² − 0.6x + 1.05, R² = 99%** (quadratic in vol, as theory demands).
- Gilt/swap 50Y convexity cross-fit (Exhibit 23, since Jan-16): **y = 1.05x − 2.49, R² = 46%**.
- 30s/50s gilt-curve fair value (Exhibit 25 footnote, verbatim): **30s/50s par gilt = 0.6·(1Y value of convexity) + 5.3·(50Y par gilt yield) − 31; R² 56%, std error 4bp** ⇒ curve ~**5bp too flat**. Gilt/GBP-swap 30s/50s stats (Exhibit 24): past-10Y par-gilt max +10/min −62/avg −11; swap max +16/min −36/avg −6; past-5Y −26…+6 avg −11 (gilt), −17…+10 avg −7 (swap).
- Gilt market structure (Exhibit 18): <15Y 25 bonds £681bn 65% (dur 4.5y); 15-30Y 11 bonds £244bn 23% (16.7y); 30Y+ 7 bonds **£131bn, 12%, wt mod duration 25.3y**, driven by pension/LDI demand.
- US backtest recap: hit rates **56% (30s/50s), 86% (25Y/20Yx5Y)** vs 1Yx30Y ATMF straddles; best current structure **20Y/40Yx10Y** (high expected payoff AND positive ex-ante roll; Exhibit 8 scatter of 1Y expected payoff vs carry+roll: 20/40x10 ~+15bp payoff, spot pairs 10/20, 20/30, 10/30 negative-carry/low-payoff cluster).
- Cross-market verdict (Exhibits 26-27): 30s/50s convexity **cheap in USD & GBP (curve-implied vol < swaption vol, expected payoff positive), expensive in EUR & JPY**; forward-dated flatteners best everywhere; **20Y/40Yx10Y clear winner in USD & GBP, neck-and-neck with 15Y/35Yx15Y in EUR**.
- US Treasury ultra-long: TBAC/Treasury found no durable 50Y demand; 20Y more likely; FY18 deficit projection $765bn, FY19 $1,022bn, FY18 net issuance $1.424tn ($900bn coupons, $524bn bills).

**Relevance**: this is the master methodology document — the E(R) = carry + slide + 0.5σ²Γ/PVBP decomposition and the breakeven-vol-vs-implied-vol comparison are exactly the "CA fair value from vol" leg of the planned framework (SR3 CA ≈ 0.5σ²·t-type Ho-Lee expressions live in the same algebra), and the published tables above are precise tie-outs for reimplementations.

---

## 10. Euro Swaps Relative value: RV on the ultra-long end of the swap curve
**J.P. Morgan, European Rates Strategy, 11 Feb 2019** (completed 09:24 AM GMT). Authors: Fabio Bassi (AC), Khagendra Gupta, Sampath Vijay.

**Directly relevant fly-construction/mean-reversion methodology (EUR, but the recipe is the point):**
- **RV opportunity index** = 10-day MA of the sum of squared 6M rolling Z-scores across curve- and level-neutral swap butterflies (2s/5s/10s, 2s/10s/30s, 5s/7s/10s, 3s/7s/15s, 10s/20s/30s); axis 0–40; spiked in Feb-2019.
- 5Yx5Y/15Yx5Y/30Yx5Y **50:50 fly** near multi-year cheap (5Y range ~10-60bp); flow story: issuance receiving in 10Y + pension receiving 30Y+ cheapened 20-25Y. These flies **richen during hiking cycles** (20Y history vs ECB depo rate).
- Regression vs 10s/30s (past 1Y): **fly = 0.91·(10s/30s) − 4.85, R² 78%** ⇒ receiving the 50:50 body ≈ a 10s/30s flattener with better RV.
- **PCA-weighted version (preferred)**: 1Y PCA on forwards, neutral to factors 1 (level) and 2 (curve); weighted fly defined **15Yx5Y − 0.133·5Yx5Y − 0.778·30Yx5Y**, i.e., risk weights −13.3%/+100%/−77.8%; ~4bp from 1Y average (extreme of past year); **3M carry ≈ −1bp**. By construction no macro betas (Exhibit 6: PCA fly beta to 10Y −1% R² 0%, to fronts/golds −1%/0%, to 10s/30s 17%/10%, residual 3.2bp; vs 50:50 fly betas −26%/63%, −18%/67%, +90%/76%, residuals 1.5/1.5/6.7bp).
- Cross-fly RV: 5Y-fwd fly vs 10Y-fwd fly (10Y/10Yx10Y/20Yx10Y): **y = 1.40x − 53.59, R² 72%**; receive 5Y-fwd body vs pay 10Y-fwd body **100%:140%**, RV ≈ 4bp (i.e., 15s/20s too steep vs 5s/10s and 25s/30s).
- Exhibit 8 menu (weights, 3M carry, current/1Y-avg/SD/dislocation/Z, betas to 10Y): e.g., weighted steepener 15Yx5Y vs 30Yx5Y 100%/−95%, carry −0.7, current −62 vs avg −58, SD 2, dislocation −3.6, Z −1.9; fly 5Yx5Y/20Yx10Y/40Yx10Y −41%/100%/−87%, carry −2.9, current 4.4 vs avg 13.5, SD 3.3, **dislocation −9.0, Z −2.7**.

**Relevance**: the cleanest published recipe in this corpus for level/curve-neutral fly weighting (PCA vs 50:50), Z-score dislocation screens, and carry bookkeeping — the intended construction for the swap-fly leg against SR3 CA.

---

## 11. Why does the ultra long-end of a yield curve invert? — Quantitative Finance Stack Exchange
**Stack Exchange thread, asked Aug 8 2019** (quanty; answers by demully, dm63, Attack68, Edward Watson; ~3k views).

One-paragraph value: community answers on why 30s/50s inverts. dm63: long 40Y/short 30Y same-DV01 at equal yields is a pure long-gamma trade ("every time the market moves you make money") so the market charges via lower 40Y yield; ZCB math: P = e^{−yT}, dv01 = −T·e^{−yT}, convexity = T²·e^{−yT} ⇒ **convexity per unit dv01 ∝ T**. Attack68's forward-space convexity ladder for a $1000 PV01 swap: **10Y $1.1, 10Y10Y $3.1, 20Y10Y $5.1, 30Y10Y $7.1, 40Y10Y $9.1**; at 50bp/yr vol, 1-yr expected gamma value = 0.5·50²·γ = **[1.4, 3.9, 6.4, 8.9, 11.4]bp**. demully: LDI/pension regulatory demand is the structural receiver, pro-cyclical (falling yields ⇒ more hedging); 10s30s doesn't show the same effect because 10s move more than 30s while 30s/40s move in parallel (dm63 comment). References Darbyshire ch.8 and Litterman-Scheinkman-Weiss. Useful as a sanity-check tie-out for convexity-per-PV01 scaling; no trade specs.

---

## Cross-document synthesis for the CA-vs-fly program

1. **Fair-value engine**: E(R) = carry + slide + 0.5σ²Γ/PVBP (doc 9) plus the twin signals *expected payoff under the swaption-implied distribution* and *breakeven (curve-implied) vol vs ATMF swaption vol* (docs 1, 3, 5, 9). The identical algebra prices SR3 CA: CA carry (futures-vs-forward drift) vs the option-implied variance over the contract's life. The swap-vs-swaption **vol ratio** (doc 5) is the most portable normalized score.
2. **Regression templates with published coefficients** (tie-outs for harness validation): 10s/20s/30s fly = f(10s/30s, VA durations), R² 98%, SE 0.5bp (doc 3); 30Y spread = f(5s/30s, deficit, VA, WAM) (doc 6); 30s/50s par gilt = 0.6·cvx + 5.3·y50 − 31, R² 56%, SE 4bp (doc 9); EUR 50:50 fly = 0.91·(10s/30s) − 4.85, R² 78%, and 5Yfwd-vs-10Yfwd fly y = 1.40x − 53.59, R² 72% (doc 10); gilt convexity y = 0.49x² − 0.6x + 1.05, R² 99% (doc 9).
3. **Fly construction**: 50:50 (2·belly − wings) vs PCA level/curve-neutral weights (−13.3/100/−77.8 example), Z-score dislocation entry, 3M carry as a hurdle, and beta-to-10s/30s as the interpretability bridge (doc 10). RV opportunity index (sum of squared fly Z-scores) as a regime/entry gate.
4. **Positioning/flow conditioning**: hedger-flow magnitudes in $mn/bp with dated episodes (docs 2, 4, 7), deposit-beta bank model parameters (doc 4), Formosa supply calendar (doc 5) — the covariates for the "dealer-positioning-conditioned" variant (with CFTC TFF replacing JPM's proprietary flow estimates).
5. **Backtest discipline**: daily-initiated 1-yr horizon trades, carry-funded option hedge sizing, hit-rate + percentile-P/L reporting (doc 1's Exhibit 5 format) — a reasonable reporting standard for the CA-vs-fly backtests.
6. **CME-LCH**: only doc 6 touches it (mechanism + LCH-share history, no basis level tables). No pack/bundle or SR3-specific conventions appear anywhere in this group.
