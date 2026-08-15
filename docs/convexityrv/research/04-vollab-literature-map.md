# Convexity / Vol RV in Rates — Consolidated Literature Map

Sources (all Citi Research, *Rates Vol Lab* / *US Rates Vol Lab*, Bikbov & Williams):
- **[D1]** "Liquidity, vega, and convexity", 30 Mar 2020 (data close 3/27/20)
- **[D2]** "Gamma and Vega RV", 14 Jan 2019 (data close 1/11/19)
- **[D3]** "In search of cheap vol", 17 Jan 2020 (data close 1/16/20)

Cross-referenced but not in the set: *US Rates Vol Lab: Trading long-dated convexity*, *US Rates Vol Lab – Buying vol for less*, *Rates Vol Lab: From GFC to ZLB*, *US Rates Vol Lab: Tactically short gamma*, *US Rates Vol Lab: CCAR and bear steepeners*, *Initiating 6m 2s10s30s payer fly*.

Note on reading this: the **methodology footnotes are verbatim-stable across the three dates**; the **rich/cheap verdicts are not** and several invert between dates. Everything below separates the stable spec from the dated reading, and every verdict carries its date.

---

## PART 1 — TRADE STRUCTURES

### 1. Outright delta-hedged straddle (gamma)

**Definition.** Sell/buy ATMF straddle in a single expiry/tail, delta-hedged on a rule.

**Signal.** Rich/cheap vs the *macro-vol model* (ATM vol regressed on 3 PCs of the swap curve) plus implied/realized ratios; z-scores on both.

**Dated instances**
- [D2] Sold **$100mn 3m10y straddles**, delta-hedged **at 9am EST with a 15% delta threshold**. 3m10y fell **66 → ~59 normals**. Scaled down 50%, keeping **$50mn at 59nv** (3pm 1/11/2019). Rationale: rich valuations, expected liquidity improvement after a tight year-end, government shutdown. Gamma still **~3 normals above macro-vol fair value**.
- [D1] **Sold 2y2y USD straddles at 55 normals** (2pm 3/27/2020) as the *preferred* way to position for ZLB / forward guidance / YCC — explicitly chosen **instead of selling gamma**, "with a minimal gamma exposure". Main risk: V-shaped H2 recovery. 2y2y still looked somewhat rich on the surface.
- [D1] 1m10y at **103 normals**; 10y gamma **~3 sigmas rich** on macro-vol; **3m30y 4 sigmas rich** on macro-vol and **2.7 sigmas rich** on surface PCA.

### 2. Cross-currency vega switch (straddle vs straddle)

**Definition.** Buy straddle in one currency vs sell the matched expiry/tail in another; vega-matched.

**Signal.** Historical level of the cross-currency vol spread + fundamental divergence (policy space, inflation pricing), against a technical driver (callable supply, position liquidation).

**Dated instance** [D1]: **Bought 10y10y USD straddles vs EUR straddles** — USD **59nv** vs EUR **57.4nv** (9:30am 3/27/20), i.e. near flat. Justification: Fed has more ammunition than ECB, larger US fiscal response, **5y5y inflation swaps ~2.0% US vs 0.92% EUR** → Japanification less likely in US. Cheapening attributed to technicals: (1) pent-up callable supply, (2) liquidations of existing long-vega positions. Main risk: further stop-outs/liquidations.

### 3. Vol tenor fly (1x2x1 across tails, vega-neutral)

**Definition.** 1x2x1 vol fly at fixed expiry across three tails; wings 2y and 30y, belly 5y or 10y. Screened as `2y/5y/10y`, `2y/5y/30y`, `2y/10y/30y`, `5y/10y/30y` across 1m→10y expiries.

**Signals (three, stacked)**
1. **Surface PCA rich/cheap** calibrated to the previous hiking/on-hold cycle: 3 PCs on **Jan-2004→Jan-2008 spliced with Jan-2017→present**.
2. **Long-run z-score** of the fly level, **window back to 1999**.
3. **Forward-curve fair-value regression**: fly regressed on **level and slope of the forward curve**, sample **2003→present, excluding the ZLB era 6/1/2008–1/1/2016** ("vol-rates models tend to struggle" there).
4. **Carry** of being long the belly.

**Dated instance** [D2] — the **3y2y/3y10y/3y30y vol fly** (note prints this once as "3y2y/3y10y/3y10y"; a typo, the rest of the note confirms 3y30y):
- On prev-cycle PCA: **3y2y rich by 5.7 normals (3.6σ)**; **3y10y cheap by 1.9 normals (2.2σ)**. Neighbours: 2y2y +6.7 (2.5σ), 2y10y −2.5 (−2.6σ), 1y10y −3.0 (−2.0σ), 2y1y +7.6 (1.9σ), 3y1y +6.3 (2.4σ).
- Fly level **−4.0 normals, z = −1.9** (3y expiry, 2y/10y/30y column) — "roughly 2 sigmas cheap on a window back to 1999", at historical lows.
- **Curve-model fair value = +5 normals.**
- **Carry: +0.75 normals (~$43K) over 1y; ~6 normals (~$341K) over 2y.**
- **Executable structure (vega-neutral):** *Sell $230mn 3y2y ATMF straddles / Buy $100mn 3y10y ATMF straddles / Sell $21mn 3y30y ATMF straddles*, **take-in $240K spot premium** (pricing 9am 1/11/19).
- Risks: flattening of the forward curve, or a significant richening of 3y2y vol.
- "Why cheap": 3y10y cheapness plausibly reflects **less demand for vega from mortgage convexity hedgers than pre-crisis**; 3y2y richness is directional with Fed-policy uncertainty; 3y30y bid by **less Formosa issuance**. Full fly grid (level, long-run z) at 1m…10y expiries in D2 Fig 5.

### 4. Expiry switches and tail switches (ATM vol ratios)

**Definition.** Ratio of shorter-expiry vol to longer-expiry vol (same tail), and shorter-tail to longer-tail vol (same expiry).

**Signal.** **3m z-score of the ratio**; deep red/deep blue mark extreme z-scores.

**Dated readings**
- [D1] 3y2y/5y2y ratio **2.5σ low**; 1m5y/1m10y ratio **2σ low** (5y tail cheap to longer tails).
- [D2] 6m5y/1y5y ratio **0.8σ high**; 1y **1y10y/1y30y = 1.09 (z 2.2)**; 5y/10y expiry ratio in the 10y tail **1.08 (z −3.1)**.
- [D3] 3y10y/5y10y ratio **2.6σ low**, 5y10y/10y10y **0.4σ high** (5y expiries rich vs neighbours); 2y2y/2y5y **1.4σ low**.
- [D3, EUR] 6m2y/1y2y **1.8σ low**; 3m5y/3m10y **2.2σ high**; 3m5y/3m30y **2.1σ high**.
- [D1, EUR] 3y10y/5y10y ~**2σ high**; 3m5y/3m10y **2.4σ low**.

### 5. Forward vol trades — gamma-neutral calendar spreads and triangles

**Definition.** "All executable forward vol trades, expressed using **gamma-neutral calendar spreads and triangles**". Calendar spreads use **underlying forwards with matching mid-points**; triangles combine three points. Reported as e.g. `short 3m20y / long 6m20y → fwd 3m3m20y`, with **gamma-neutral weights** printed as `82.1 / 100`.

**Signal (efficient frontier, 20 best trades).** Two axes:
- **Ex-ante Sharpe = vol-adjusted roll on the surface** (3m roll in nv, divided by vol).
- **Value = 1y z-score** (3m z-score also shown).

**Forward vol construction (used by both the screen and the standalone forward-vol tables).** Forward 1y2y / 1y5y / 1y10y / 1y30y vols implied from the spot surface using the **standard triangular approximation from spot vols, using 6m realized correlations as a proxy for implied correlations**. Reported per forward-start year 0→9: level, 1w chg, 1m chg, **difference from 1y average (with z-score)**, and **difference from the 10y average of the corresponding 1y-expiry spot vol (with z-score)**. Also plotted: fwd 1y2y/1y5y, 1y5y/1y10y, 1y10y/1y30y **ratio term structures** (current vs 1m ago vs 3m ago).

**Dated instances**
- [D2] **15y15y/20y5y calendar switch → 15y5y5y**, gamma-neutral weights **30.9/100**, vols 56.2 / 55.4 / **53.3 fwd**, **3m roll 0.38nv ("about 0.4 normals")**, Sharpe 0.30, 1y ZS −0.9, 3m ZS −1.3. Top of the D2 frontier: `15y5y/15y30y vs 20y25y → 15y5y25y`, 95.9/100, 51.2/49.7/**44.7**, roll 0.46, Sharpe 0.44.
- [D3] **10y20y/5y30y straddle switch = long 5y fwd 5y20y vol** — 10y20y **54.6nv**, 5y30y **56.6nv** (1pm 1/17/2020). Chart: USD vs EUR 5y-fwd 5y20y. D3 frontier tops: `1y3y2y/18m7y → 1y6m7y`, 316.5/100, 69.5/62.9/**51.1**, roll 2.28, Sharpe 0.26, ZS −1.8/−0.9; `1y2y2y/18m5y → 1y6m5y`, 224.4/100, 68.6/62.6/**49.8**, roll 2.23, Sharpe 0.24 — flagged as newly attractive on the cheapening of upper-left vols.
- [D1] Top of frontier by Sharpe: `3m20y/6m20y → 3m3m20y`, **82.1/100**, 103.9/90.2/**74.1**, roll **29.75nv**, **Sharpe 4.17**, 1y ZS 2.1; `3m30y/6m30y → 3m3m30y`, 81.9/100, 106.1/92.7/76.9, roll 29.25, Sharpe 4.08, ZS 2.3. Best by *value*: `1y3y1y/3y3y → 1y2y3y`, 280.9/100, 96.4/59.7/**31.4**, roll 6.70, Sharpe 0.96, **1y ZS −4.8**. Explicit linkage: *because 3y1y midcurves look rich to swaptions, calendar switches such as 1y3y1y/3y3y look quite cheap and roll attractively.*
- [D1] Forward vol levels (spot row): 1y2y **46.1**, 1y5y **63.8**, 1y10y **76.7**, 1y30y **80.6**; 1-4y forwards cheapened sharply on prolonged-ZLB expectations, long-dated 2y-tail forwards richened. [D3] spot: 57.0 / 61.5 / 62.4 / 58.7; the 1y2y term structure very steep in long expiries → **"7y2y spot vol may be cheap to 10y2y."** [D2] spot: 67.7 / 69.0 / 64.7 / 59.5.
- [D1, EUR] Term structure of forward vols in the **30y tail especially flat → attractive carry**.

### 6. Delta-hedged long-dated swap curve flatteners (physical convexity — the "free convexity buy")

**This is the core "cheap gamma vs swaptions" structure in the set.**

**Definition.** DV01-neutral long-dated forward-starting curve flattener (e.g. **15y10y/25y10y**, **15y5y/20y10y**), held as a **long-convexity position** and delta-hedged discretely. Screened universe = 15 long-dated pairs:
`10y10y/15y15y, 10y10y/20y5y, 10y10y/20y10y, 10y10y/20y15y, 10y10y/25y5y, 10y10y/25y10y, 15y5y/20y5y, 15y5y/20y10y, 15y5y/20y15y, 15y5y/25y5y, 15y5y/25y10y, 15y10y/25y5y, 15y10y/25y10y, 20y5y/25y5y, 20y5y/25y10y` — across **USD, EUR, GBP, CAD, JPY** [D3]; USD/EUR/GBP [D1].

**Why it is long convexity / cheap gamma.** For a DV01-neutral pair, the longer-dated leg carries more convexity per unit DV01, so the DV01-neutral spread is net long convexity. When the flattener also **carries positively**, the convexity is acquired at **zero or negative cost** — versus paying premium for the same gamma in swaptions. Quoted: *"the flatteners offer an effectively free convexity buy"* [D3]; *"the trade is effectively a free convexity buy"* [D1]. (The receive/pay leg decomposition is inferred, not stated in the notes; the notes only specify DV01-neutrality and which leg is adjusted.)

**Valuation metrics (exact, as printed).** For each curve:
- **curve, bp** — the level as printed (sign convention not stated in the source; quote as printed).
- **1y ZS**, **3y ZS**, **ZS since 2000** — z-scores over 1y, 3y and full sample from 2000.
- **1y carry, bp**.
- **daily BE, bp** — *"the daily breakeven (the move in rates that yields a convexity gain offsetting the negative daily roll)"*; **set to zero when carry is positive** ("zero of carry is positive").
- **1y realized vol, bp** — daily realized vol of the underlying rates.
- **BE / realized vol** — *"a smaller ratio indicates the cheapness of the embedded convexity and therefore a more attractive trade."* Zero = free convexity.
- Three most attractive curves by each metric marked in red.

**Hedging / weighting convention (quoted).**
- **Sizing: DV01-neutral.** [D3] initiated **50K DV01**.
- **Rebalance rule:** *"We will be delta-hedging the trade by adjusting the **longer leg** of the trade for **DV01 neutral at each 25bp move in the 25y10y rate**."*
- **Justification for the band:** *"We have previously found that hedging at **20-25bp** offers an attractive balance between the **accuracy of hedging and transaction costs**"* (ref: *US Rates Vol Lab: Trading long-dated convexity*).
- [D1] cross-check on hedging cost in gamma: **mid-to-bid/offer still about 0.6bp in 10y swaps**, "which makes it costly to delta-hedge frequently."

**Dated instances**
- [D3] **Initiated GBP 15y10y/25y10y flatteners, 50K DV01, at −11.2bp** (12pm 1/17/2020). Screen row (close 1/16/20): curve **−10.37bp**, 1y ZS **−0.01**, 3y ZS **1.15**, **ZS since 2000 = 1.84** (steepest in the GBP row), **1y carry +0.52bp**, **daily BE 0.00**, 1y realized vol **4.19bp**, **BE/RV = 0.00**. Drivers: post-election fading of budget-expansion risk; **20y sector rich on the GBP curve because of ALM receiving flows** (10s20s30s fly chart). Risk: continued richening of the 20y on ALM receiving.
- [D1] **Took profits on the GBP 15y10y/25y10y flatteners** (curve had flattened on aggressive BoE QE; risk of re-steepening on supply).
- [D1] **USD 15y5y/20y10y flatteners at −5.21bp** (3pm 3/26/2020) — added to *watch list*, not initiated, "given the lack of liquidity and wide bid/offer spreads." Screen row: 1y ZS **4.21**, 3y ZS **3.58**, ZS since 2000 **1.02**, **1y carry +0.11bp**, **daily BE 0.00**, 1y realized vol **6.40bp**, **BE/RV 0.00**. Driver: *"the 15y5y/20y10y USD curve has steepened to the upper bound of the historical range, most likely due to **receiving pressures from variable annuity portfolios** in the stock market selloff… **VA hedging is typically concentrated in the 20y sector of the curve**."* Risk: further risk-off and associated VA hedging flows.
- [D1] Full USD row (curve levels, bp, in screen order): −5.07, −6.70, −6.86, −11.74, −7.03, −14.38, −5.04, **−5.21**, −10.09, −5.38, −12.73, −2.90, −10.24, −0.34, −7.68. USD 1y realized vols ~6.2–6.5bp; EUR ~4.9–5.4bp; GBP ~5.1–5.4bp. USD BE/RV mostly **0.15–0.30** (very cheap convexity); EUR BE/RV **0.00–1.17**; GBP **0.00–0.54**.
- [D3] Cross-currency BE/RV comparison (close 1/16/20): **GBP cheapest** (0.00–0.89), USD 0.00–1.08, EUR 0.60–1.48, **CAD 0.00–1.82**, **JPY 0.76–1.50 (most expensive convexity, no zeros)**. GBP 1y realized ~4.19–4.33bp, JPY ~2.40–3.08bp.

### 7. Conditional curve trades (bull/bear steepeners and flatteners)

**Definition.** Two-leg swaption curve trade: **the leg with the smaller vol is struck ATM, the other leg is struck OTM for zero cost.** Bear trades use payers, bull trades use receivers. Notionals printed DV01-weighted as `100 / xx.x` ($mn). Grid: expiries 3m/6m/1y/2y/3y × curves 1y2y, 1y3y, 1y5y, 2y5y, 2y10y, 2y30y, 3y5y, 3y10y, 3y30y, 5y10y, 5y30y, 10y30y.

**Valuation metrics (exact, quoted footnote).**
- **spot curve, fwd curve, 3m ZS of fwd curve, costless strike curve**, 1m and 3m change, hist ZS.
- **hist %** — *"historical % of the strike curve using data starting in 1990."*
- **Implied beta** — *"the beta between the curve and the average of end points implied by vols."*
- **Realized beta** — *"empirical beta between the curve and the average of end points computed over the last 3m."* Plus **rlzd − imp**.
- **Curve pick-up** — *"the spread between spot and forward curves for steepeners, and the spread between forward and spot curve for flatteners."*
- **Vol pick-up** — *"the spread between forward and strike curves for steepeners, and the spread between strike and forward curves for flatteners."*
- **Total pick-up** = curve + vol pick-up.
- **3m roll** — *"computed assuming unchanged curve and vol cube and is expressed in bp of running yield."*
- Three best bear steepeners marked red, three best bear flatteners green (and equivalently for bull).

**Representative row semantics** [D1, bear]: `3m 2y10y, 100/20.3, spot crv 17.3, fwd crv 29.5, 3m ZS 0.7, strk crv 54.7, 1m chg 37.6, 3m ZS 1.2, hist 30%, imp β 0.73, rlzd β 0.56, rlzd−imp −0.16, bear-steepener crv pick-up −12.3, vol pick-up −25.1, total −37.4, 3m roll −13.9`.

**Dated instances**
- [D1] **3y 10s30s conditional bear steepeners** maintained (ref: *Initiate 3y 10s30s bear steepeners*). Risk: V-shaped recovery causing bear flattening.
- [D3] **3y 5s30s conditional bear steepeners** maintained (ref: *CCAR and bear steepeners*); **zero-cost strike spread ≈ 14bp** (3pm 1/16/2020).
- [D2] *"At current valuations, we do not find conditional curve trades very attractive."*

### 8. Conditional flies (payer flies and receiver flies, 50/50 DV01-weighted)

**Definition.** *"Conditional flies are structured by buying (selling) payers [receivers] in the belly vs selling (buying) payers [receivers] on the wings with **50/50 DV01 weights**. The **wings are struck ATM, while the strike on the belly is solved for zero cost**."* Notionals printed e.g. `149.8 / 100 / 30.1`.

**Valuation metrics (exact, quoted).**
- **Spot, forward and costless-strike rates flies reported using −0.5 / 1 / −0.5 weights.**
- **Correlations of the forward fly with the belly** — *"using a 3m window in changes and 1y window in levels."*
- **Rich/cheap of the forward fly to the belly** — *"based on 1y regression in levels"* (reported as RC in bp and a z-score).
- **belly strike OTM, bp**; **strike fly, bp**; 1m/3m change; ZS.
- **hist %** of the strike fly, **data starting in 1990**.
- **Crv pick-up / vol pick-up / total pick-up / 3m roll** (roll again "assuming unchanged curve and vol cube, in bp of running yield").
- Three best long-belly trades red, three best short-belly green.

**Dated instances**
- [D3] **Sell 6m10y payers vs 6m2y and 6m30y payers** — the **6m 2s10s30s payer fly**, "to monetize the relative richness of the 10y vol". Risk: technical selling pressure on 10s.
- [D2] **Sell 6m5y receivers on the 6m 2s5s10s receiver fly**, "to fade the richness of 5y in a rally… we expect the rates fly to cheapen in a large rally as the market should price near-term cuts." Risk: hawkish Fed despite weakening data.

### 9. Midcurve swaptions vs plain-vanilla swaptions

**Definition.** Midcurve (option on a forward-starting swap) vs the two plain-vanilla swaptions that span it — a **correlation/convexity trade** between two forward rates.

**Valuation metrics (three, all printed).**
1. **ATM implied vol level + 3m z-score.**
2. **Implied correlation, % + 3y z-score.** Low implied correlation ⇒ midcurve cheap to swaptions.
3. **Implied/realized correlation ratio** — *"the ratios of implied to **3m realized correlations (in daily changes)**"*, with **1y z-scores**.
4. **Rich/cheap to plain vanilla**: [D1, D3] *"We regress midcurve vols on **two corresponding plain vanilla vols using last 3y** of data. For example, **1y2y1y is regressed against 1y3y and 1y2y** vols."* [D2 variant] *"We regress midcurve vols on **three principal components of the plain vanilla surface using 3y of data.**"*
Grid: expiries 1m/3m/6m/1y/2y × tails 1y1y, 2y1y, 3y1y, 1y2y, 2y2y, 3y2y, 5y5y, 10y10y.

**Dated readings (these invert — note the dates)**
- [D2, Jan-19] **1y1y, 2y1y, 1y2y midcurves RICH** to swaptions; **5y5y midcurves CHEAP** (1y5y5y RC −2.5, z −1.9).
- [D3, Jan-20] **5y5y midcurves CHEAP** — *"the 1y5y5y vol looks cheap to swaptions by about 3 sigmas"* (RC −2.3, **z −2.8**; 6m5y5y −2.5, z −2.5).
- [D1, Mar-20] **1y1y and 1y2y midcurves CHEAP** (1m1y1y RC −10.8, z −2.4; 3m1y2y −10.2, **z −3.8**; implied corr 1m1y2y **111.1**, 3m1y2y **125.3, z 3.2**); **3y1y midcurves RICH** (1m3y1y RC **+23.3, z 4.4**; implied corr 1m3y1y **94.4, z −5.2**; 1m3y2y RC **+31.6, z 5.6**, implied corr **77.1, z −6.9**). This richness is the stated reason the **1y3y1y/3y3y calendar** screened cheap on the forward-vol frontier.
- [D1, EUR] **6m3y2y midcurve ~3 sigmas cheap** to swaptions (RC −1.1, z −3.0); EUR midcurves broadly cheap in 3m/6m expiries.
- [D3, EUR] 5y5y and 10y10y midcurves cheapened notably; **1y2y may look rich** on the implied/realized correlation ratio.

### 10. Curve (spread) CMS options — 2s5s, 2s10s, 2s30s, 5s10s, 5s30s, 10s30s

**Definition.** Options on a CMS curve spread; the RV question is spread vol vs the two underlying swaption vols (i.e. implied correlation).

**Valuation metrics.**
1. **ATM implied vol (normals) + 3m z-score**, expiries 1m/3m/6m/1y/2y/3y/5y.
2. **Rich/cheap to PCA** — *"PCA on curve vols using **two principal components and 3y of data**. By design, this framework only yields relative value."*
3. **Implied correlation** (2s10s time series, by expiry) — a fall in implied correlation = spread vol richening to swaptions.
4. **Implied/realized ratios** vs **1m and 3m realized**, with **1y z-scores**. [D1, D3] close-to-close realized used; [D2] **hourly (intraday) realized vol between 8am and 3pm** used.

**Dated readings (these invert)**
- [D2, Jan-19] **10s30s vol CHEAP** on PCA and vs recent realized (implied/1m RV 0.73 at 1m, **z −2.2**; PCA 5y −1.0, 3y −1.4 z −1.9). **5s10s and 5s30s RICH** on PCA.
- [D3, Jan-20] **2s10s richened, implied correlations off the highs; 2s10s now rich on PCA** (3m +3.8, **z 2.4**; 6m +3.2, z 2.2). **10s30s VERY RICH to recent realized** (implied/1m RV **1.90 at 3m, z 2.1; 1.97 at 6m, z 2.3; 2.03 at 1y, z 2.2**).
- [D1, Mar-20] *"Spread vol has richened to swaptions, which is evident from the decline in implied correlations. **The 2s10s vol looks especially rich on the surface** — the 6m 2s10s vol is roughly **2.7 sigma rich on PCA** (+4.2 normals). **Yet, curve gamma looks cheap to recent realized vols**"* (implied/1m RV all ~0.32–0.59, **z −2.4 to −3.0**). **EUR 10s30s especially rich on PCA** (2y +3.1 z 2.8; 3y +2.7 z 2.9).
- Headline [D1]: *"Curve vol remains rich to swaptions when evaluated by implied correlations. USD 2s10s vols and EUR 10s30s vols appear especially rich."*

### 11. Board (Treasury futures) options vs swaptions

**Definition.** Compare exchange-traded FV / TY / US option vol to the **CTD-matched swaption vol**.

**Valuation metrics.**
- **Board vol** (ATM, interpolated) and 1w change; **CTD-matched swaption vol** and 1w change.
- **Board/1m RV, Board/3m RV, swpn/1m RV, swpn/3m RV**.
- **Board/swpn ratio** (and 1w-ago value); chart uses **the second available expiry, rolled on the expiration of front options**.
- **ftrs 1m RV / swap 1m RV** and **ftrs 3m RV / swap 3m RV** — the basis-adjustment cross-check.
- **Skew comparison convention:** *"Swaption strike = Board strike yield + invoice spread."*

**Dated readings (invert)**
- [D2, Jan-19] **FV may be RICH to swaptions if compared to recent realized vol.** FVH9 Board 61.9 vs swaption 61.5 (ratio 1.01) but **Board/1m RV 0.77 vs swpn/1m RV 0.67**. Put skew rich to payer skew.
- [D3, Jan-20] Board vols trade **largely on par** with swaptions; **FVH0 may be slightly rich**. Put skew rich to payer skew.
- [D1, Mar-20] **FV and US vols look CHEAP to swaptions if compared to recent realized vols.** FVK0 Board **67.1** vs CTD swpn **77.8** → **Board/swpn 0.86**; USK0 **106.9** vs **120.5** → **0.89**; TYK0 96.7 vs 95.1 → 1.02. Board/1m RV 0.38–0.44 vs swpn/1m RV 0.46–0.52. **ftrs/swap RV ratio 1.17–1.18 (1m), 1.12–1.14 (3m).** **Board smile looks rich to swaption smile.**

### 12. Conditional spread trades (swaption vs Board option, DV01-neutral)

**Definition & convention (quoted).** *"Swaption notional is for **1000 Board contracts**. The **costless swaption strike makes the DV01-neutral trade costless**. The **BP pick-up is the spread between the costless strike spread and the invoice spread**."* Reported per futures option (FV/TY/US, two expiries), for six strikes each on both the puts/payers and calls/receivers side, with **put vol, payer vol, vol ratio**.

**Representative row** [D1]: `FVK0, 04/24/20, fut price 125-5.75, fut DV01 5.07, swap DV01 4.14, swpn ntl $122.5mn, invoice spread 5.0bp, put strike 125.00 (0.43% yield), costless payer strike 0.50%, strike spread 7.0bp, pick-up −2.0bp, put vol 68.4, payer vol 77.2, ratio 0.89`.

### 13. Eurodollar / futures convexity adjustment (short-convexity trade)

**Definition & formula (quoted).** *"Convexity adjustments for **1y ED packs** are computed as **the spread between the pack's rate (the average of 4 ED rates in the pack) and the matched-maturity forward 1y CME swap rate**. The model for convexity adjustment is the **Ho-Lee model calibrated to cap/floor vols**. **Implied vol is calculated by matching the model to the observed convexity adjustment.** **Realized vol is 3m realized vol of the corresponding pack.**"*

**Valuation metrics (columns).** Cvx Adj (bp); 1-week chg; **3m Z-Score**; **1Y Z-Score**; **Vs Model (bp)**; **3m and 1Y Z-Score of the model spread**; **3m Roll (short cvx, bp)**; **Implied Vol**; **Realized Vol**; **Implied/Realized**; **Cap vol Impl/Rlzd**. *"For each valuation metric, we mark **three best short convexity trades** in bold."* Also plotted: Greens / Blues / Golds rolling packs vs the Ho-Lee model.

**Dated readings**
- [D2, Jan-19] Adjustments **roughly fair to model**, compressed notably (short covering of ED futures). H9-Z9 0.06bp; M0-H1 1.09bp (z-scores −2.8 to −3.0); H3-Z3 7.44bp. Implied/realized ~0.9–1.3.
- [D3, Jan-20] Tightened closer to fair in Blues and Golds. H0-Z0 −0.02bp; H2-Z2 1.93bp (vs model +0.49, 3m z 2.05); H4-Z4 5.58bp. Implied vols 37–78 vs realized 56–82; **implied/realized 0.7–1.0**.
- [D1, Mar-20] **Richened in Blues and Golds** (profit-taking on long ED futures positions). M0-H1 0.03bp (3m z 1.64); H1-Z1 0.38bp, vs model +0.18, 3m z 2.40, implied 63.6 vs realized 84.2; M4-H5 7.25bp. Implied/realized **0.6–0.8** across the strip; cap-vol implied/realized 0.4–0.5.

### 14. Swaption skew / risk reversals (implied and implied-vs-realized)

**Definitions & conventions (quoted).**
- **Risk reversal, payer skew, receiver skew, all in normal vol terms.**
- **OTM strike conventions: 25bp out for 3m expiries, 50bp out for 6m–2y expiries, 100bp out for 3y+ expiries.**
- Grid: expiries 3m/6m/1y/2y/3y/5y/10y × tails 1y/2y/5y/7y/10y/30y, level + **1y z-score**.

**"Realized skew" model (the implied-vs-realized skew engine, verbatim).** *"We calibrate an **empirical SABR model** to the recent observed dynamics of ATM vols and rates. We use a **2y rolling window to estimate a backbone parameter**, and a **3m window to estimate correlation and vol-of-vol parameters**. The empirical model **matches ATM implied vols exactly**, so it's different from the market only in skew parameters. We calculate 'realized skew' as the theoretical values of OTM payers, receivers and risk reversals from this empirical model. The table shows **market − 'realized' spreads for risk reversals**, and **market / 'realized' ratios of OTM payers and receivers**, together with **1y z-scores**."*

**Dated readings (invert)**
- [D2, Jan-19] Implied smile richened. Short-dated RRs **inverted**, receivers at a high premium to payers (3m2y RR **−8.7**, 3m 25bp receiver skew +8.0). **RRs generally RICH to realized skew, especially longer tails**: 3m30y **+2.5 (z 1.0, ~1σ rich)**; **5y30y +1.2 (z 2.0, ~2σ rich)**; 5y10y +2.4 (z 2.0).
- [D3, Jan-20] Short-dated RRs little changed, slightly inverted (3m2y −10.1, 6m1y −17.0). Longer-dated payer skews **very cheap historically**. **RRs in shorter expiries CHEAP to realized skew** — *"the 6m10y risk reversals trade about **two sigmas cheap**"* (−6.4, **z −2.0**); 3m10y −3.7 (z −1.8).
- [D1, Mar-20] Short-dated RRs **richened sharply as rates approached ZLB**; 3m2y RR −5.2 (z 1.4), 1y10y +1.5 (z 4.0), 2y10y +2.5 (z 4.1), 3y10y +2.6 (z 4.3). **RRs in shorter expiries RICH to realized skew** — *"3m10y risk reversals trade about **three sigma rich**"* (**+11.6, z 3.2**); 3m30y +16.0 (z 3.6); 6m30y +10.9 (z 2.9). OTM receivers 2y1y **1.18 (z 6.7)**.
- [D1, EUR] 3m30y RR **−10.6 (z −2.3)**; long-dated payer skews cheapened, receiver skews richened.

### 15. Rates vol vs FX vol (cross-asset vol RV)

**Definition** [D3]. Buy FX option structure vs sell swaption, sized by premium/notional, exploiting the relative level of rates vol to FX vol.

**Signal.** **6m10y / USDJPY vol ratio** time series (rates vol very rich to FX vol by historical standards) + a **spot-vs-rate-differential regression**: `USDJPY = 0.0266 × (USD-JPY 10y differential, bp) + 103.48, R² = 0.32, sample 2018–2019` → yen too weak. Plus **USDJPY 25D put/ATM vol ratio** (put skew optically rich) and 6m10y rich on the macro-vol model.

**Dated instance** [D3]: **Bought $30mn USDJPY 108/105 put spreads vs selling $50mn 6m10y ATMF+45bp (2.2%) payers, net cost $35K** (USDJPY 110.17, 12pm 1/17/20). *"Structured similarly to a 'quiet bull' familiar to rates investors, but we prefer buying USDJPY put spreads to rates receiver spreads given the relative cheapness of FX vol."* Predecessor trade: bought 3m USDJPY calls vs 3m10y payers (Oct 2019), closed the payer leg, kept $15mn USDJPY 110 calls, closed at 110. Risk: return of inflation / improved global growth pushing 10y above 2.2%.

### 16. Callable / Formosa supply as the vega-supply driver (flow overlay, not a trade)

**Definition & metrics.** Gross callable supply (**Formosa vs non-Formosa**, **financial vs non-financial**), redemptions, **net notional supply**, and **vega supply in normal parallel vega ($mn)**. Convention (quoted): *"We assume (simplistically) that **all financial and government bonds are swapped, while all non-financial bonds are not swapped**"*; universe = *"all callable Formosa (zero-coupon and fixed-rate) and zero-coupon non-Formosa bonds."*

**Dated readings**
- [D3, Jan-20] **$5.3bn issued MTD** vs a $5bn projection, possibly **$6bn** by month end; issuance shifted to **40NC5**, so **~$16mn normal vega swapped — highest monthly supply since Jan 2018**. February supply expected with more non-financials (less likely to swap vol) → smaller vega supply; Q1 Formosa supply typically front-loaded, **≥50% in January**. This is the stated technical reason **bottom-right vega stayed cheap** and the setup for the 10y20y/5y30y switch.
- [D2, Jan-19] $1.2bn in first two weeks; $2-3bn expected in Q1. Jan-19 MTD vega **$2.9mn**; 2018 full-year vega **$53.3mn**.
- [D1, Mar-20] **$5.08bn MTD, all bank issuance**, highest monthly since January; **vega $14.6mn**; 2020 YTD gross **$20.62bn**, vega **$46.8mn**; 2019 full year vega $37.8mn.

### 17. Liquidity / hedging-cost diagnostics (inputs to every gamma decision)

- **On-the-run / off-the-run rich-cheap:** *"the residual from the regression of the **10y OFR yield on three principal components of the ONR curve**."* [D1]
- **Intraday vs close-to-close realized vol ratio:** [D1] "Realized vol is calculated using a **10-day window**. Intraday vol is calculated using **30m snapshots from 7am to 5pm EST**." A high intraday/close-to-close ratio = whipsawing, low-liquidity market. Grid version: **1m and 3m intraday/close-to-close ratio of realized vols with 1y z-scores**, 30m sampling **7am–4pm NY** (or London for EUR); [D2] hourly **8am–3pm**.
- **Transaction cost:** mid-to-bid/offer **~0.6bp in 10y swaps** [D1, Mar-20].

---

## PART 2 — VALUATION METRICS, EXACT DEFINITIONS

The notes give **verbal** definitions; these are transcribed as printed (no invented algebra).

| Metric | Exact definition as printed |
|---|---|
| **Macro-vol model (rich/cheap to rates)** | *"We regress each ATM point on **3 principal components of the swap curve**. We report rich/cheap for each vol as **a residual from this regression** together with z-scores in parentheses."* **USD sample: 1996–2008 spliced with 2017–2019** (2017-2018 in D2), *"to exclude the near-zero rate policy regime."* **EUR sample: 2016+, i.e. the negative rates regime.** |
| **Rich/cheap to PCA of the vol surface** | *"We calculate rich/cheap and z-scores from **PCA on the vol surface based on 3 principal components using 2y of data**. **By design, this framework only yields relative value.**"* [D2 cycle-calibrated variant: 3 PCs on **Jan-2004→Jan-2008 spliced Jan-2017→present**.] |
| **ATM vol table** | ATM implied vols in **normals**, with **3m z-scores** in parentheses; deep red = largest z, deep blue = smallest. Companion table: **1w or 2w change in implied vols, normals**. |
| **Implied/realized ratio** | Implied vs **1m and 3m realized**, computed **two ways**: (a) **intraday** — 30m sampling 7am–4pm NY / London [D1, D3]; hourly 8am–3pm [D2]; (b) **close-to-close**. Reported as a ratio with a **1y z-score**. |
| **Intraday/close-to-close realized ratio** | 1m and 3m windows, **1y z-score**; a diagnostic for liquidity/whipsaw. |
| **Day-to-day realized vol by time-of-day** | *"day-to-day realized volatilities measured at a given hour within a day for the last **3m, 6m and 1y**"*, plotted 8am→5pm plus a **"hedged hourly"** and a **"hedged once a day"** bar. Used to *pick the delta-hedge snapshot*. |
| **Expiry switch ratio** | shorter-expiry vol / longer-expiry vol, **3m z-score**. |
| **Tail switch ratio** | shorter-tail vol / longer-tail vol, **3m z-score**. |
| **Vol tenor fly** | **1x2x1** across tails; long-run **z-score from 1999 to present**. Fair value = regression of the fly on **level and slope of the forward curve**, 2003→present, **excluding 6/1/2008–1/1/2016**. |
| **Forward vol** | *"standard **triangular approximation** from spot vols and using **6m realized correlations as a proxy for implied correlations**."* Reported: level, 1w chg, 1m chg, **vs 1y avg (+z)**, **vs the 10y average of the corresponding 1y-expiry spot vol (+z)**. |
| **Forward vol trade Sharpe** | *"The ex-ante Sharpe is calculated as **vol-adjusted roll on the surface**"* (3m roll in nv). **Value axis = 1y z-score** (3m z also shown). Weights = **gamma-neutral**. |
| **Skew** | Risk reversal / payer skew / receiver skew **in normal vol terms**, OTM **25bp (3m) / 50bp (6m–2y) / 100bp (3y+)**, with **1y z-scores**. |
| **Realized skew** | Empirical **SABR**: **2y rolling window → backbone**; **3m window → correlation and vol-of-vol**; ATM matched exactly. Output: **market − model spread for RRs**; **market/model ratio for OTM payers and receivers**; **1y z-scores**. |
| **Midcurve implied correlation** | Implied correlation in %, **3y z-score**. |
| **Midcurve implied/realized correlation** | *"ratios of implied to **3m realized correlations (in daily changes)**"*, **1y z-scores**. |
| **Midcurve rich/cheap** | Regression of midcurve vol on **the two corresponding plain-vanilla vols, 3y of data** (1y2y1y on 1y3y and 1y2y) [D1, D3]; or on **3 PCs of the plain-vanilla surface, 3y of data** [D2]. |
| **Curve (CMS) option PCA** | *"PCA on curve vols using **two principal components and 3y of data**. By design, this framework only yields relative value."* |
| **Curve option implied/realized** | implied / 1m RV and implied / 3m RV, **1y z-scores**; close-to-close [D1, D3] or hourly 8am–3pm [D2]. |
| **ED convexity adjustment** | **pack rate (average of 4 ED rates) − matched-maturity forward 1y CME swap rate**. Model = **Ho-Lee calibrated to cap/floor vols**. **Implied vol = value that matches the model to the observed adjustment.** Realized = **3m realized vol of the pack**. Columns include **3m Roll (short cvx, bp)** and **Cap vol Impl/Rlzd**. |
| **Daily breakeven (curve convexity)** | *"the move in rates that yields **a convexity gain offsetting the negative daily roll**"*; **set to 0 when carry is positive**. |
| **BE / realized vol** | daily BE ÷ 1y daily realized vol of the underlying rates. *"A **smaller ratio indicates the cheapness of the embedded convexity** and therefore a more attractive trade."* |
| **Curve z-scores** | **1y, 3y and full-sample (since 2000)** z-scores of the curve level; three most attractive per metric marked red. |
| **Conditional-curve implied beta** | *"the beta between the curve and the **average of end points implied by vols**."* |
| **Conditional-curve realized beta** | *"empirical beta between the curve and the average of end points computed over the **last 3m**."* |
| **Curve/vol/total pick-up** | steepeners: curve = spot − forward; vol = forward − strike. flatteners: curve = forward − spot; vol = strike − forward. total = sum. |
| **3m roll / carry** | *"computed assuming **unchanged curve and vol cube** and expressed in **bp of running yield**."* |
| **hist %** | percentile of the strike curve / strike fly, **data starting in 1990**. |
| **Fly-vs-belly correlation** | **3m window in changes**, **1y window in levels**; rich/cheap of the forward fly to the belly from a **1y regression in levels**. |
| **Board/swaption** | ATM interpolated Board vol vs **CTD-matched swaption vol**; ratios to 1m and 3m RV; **ftrs RV / swap RV**; skew mapped by **swaption strike = Board strike yield + invoice spread**. |
| **Costless swaption strike (vs futures)** | *"makes the **DV01-neutral trade costless**"*; **BP pick-up = costless strike spread − invoice spread**. |
| **Vega supply** | **normal parallel vega**; financials + governments assumed swapped, non-financials not. |
| **OFR rich/cheap** | residual of the **10y OFR yield on 3 PCs of the ONR curve**. |

---

## PART 3 — DELTA-HEDGING AND GAMMA-MAINTENANCE RULES (quoted)

**Swaption gamma (straddles)**
- *"We sold $100mn 3m10y straddles **delta-hedged at 9am EST with a 15% delta threshold**."* [D2]
- *"We will continue delta-hedging **daily at 9am EST but only if delta moves by more than 15% from the previous hedge**."* [D2]
- *"We chose to hedge at 9am given that **this time snapshot has delivered one of the lowest realized volatilities over the last 3m, 6m and 1y**."* [D2] — i.e. the hedge *time* is chosen from the time-of-day realized vol table, not by convention.
- *"Our delta-hedging strategy has also proved to be useful with **rates whipsawing between 9am snapshots** on most days."* [D2]

**Physical curve convexity (long-dated flatteners)**
- *"We will be delta-hedging the trade by **adjusting the longer leg of the trade for DV01 neutral at each 25bp move in the 25y10y rate**."* [D3]
- *"We have previously found that **hedging at 20-25bp offers an attractive balance between the accuracy of hedging and transaction costs**."* [D3]

**Time-of-day hedging evidence (each dated; these move)**
- [D2, Jan-19] USD: **hedging around 9am** delivers one of the lowest realized vols over 6m and 1y; **3–5pm the highest**.
- [D3, Jan-20] USD: **9am lowest** over 3m and 12m; **12pm the highest**. EUR: **2pm London lowest** over 3m and 6m ("consistent with the USD vol low at 9am NY"); **8am highest**.
- [D1, Mar-20] USD: **10–12pm** delivered relatively low realized vol of the 10y over 3–12 months; **intraday hedging delivered the highest** realized vol. EUR: **8am London lowest**; intraday highest.
- Every chart also prints a **"hedged hourly"** and **"hedged once a day"** comparison bar — the explicit cost of hedge frequency.

**Cost constraint on frequent hedging**
- *"the bid/offer remains wide (**mid-to-bid and offer is still about 0.6bp in 10y swaps**), which makes it costly to delta-hedge frequently. From that point of view, **we would rather sell longer expiries, such as 2y2y**… to position for the ZLB."* [D1]

---

## PART 4 — WHERE GAMMA/CONVEXITY IS CHEAP OR RICH VS SWAPTIONS, AND WHY

**Cheap sources of convexity relative to swaptions**

1. **Delta-hedged long-dated curve flatteners — the flagship.** Positive carry + net long convexity ⇒ *"effectively free convexity buy"* / *"a cheap convexity buy"* [D1, D3]. Mechanism: DV01-neutral, longer leg carries more convexity per DV01, and the daily breakeven is zero when carry is positive, so **BE/realized-vol = 0** — the convexity is acquired for free rather than paid for in premium. Screened cross-currency; GBP and USD screened cheapest in the two dates covered; JPY consistently most expensive (no zero-BE entries).
2. **The dislocation that creates the entry** is always a *flow* story, and the notes name it:
 - **USD 15y5y/20y10y steepness** ⇐ *"receiving pressures from **variable annuity portfolios** in the stock market selloff… **VA hedging is typically concentrated in the 20y sector of the curve**"* [D1].
 - **GBP 15y10y/25y10y steepness** ⇐ *"the richness of the 20y on the curve, likely because of **receiving flows from ALM investors**"* [D3].
3. **Bottom-right USD vega** cheap on **technical** grounds — *"pent-up callable supply"* and *"liquidations of existing long vega positions"* — while cheap on **fundamentals** vs EUR [D1]. Same channel in reverse [D3]: the **shift to 40NC5 Formosa structures surged vega supply to ~$16mn/month**, keeping 5y-fwd 5y20y cheap → buy via 10y20y/5y30y switch.
4. **3y10y vega structurally cheaper than pre-crisis** — *"there is **less demand for vega from mortgage convexity hedgers today**, compared to pre-crisis"* [D2].
5. **Midcurves vs swaptions** — cheap when implied correlation is high relative to its 3y history *and* the direct regression on the two spanning vanillas shows a negative residual. 5y5y midcurves cheap in both Jan-19 and Jan-20; 1y1y/1y2y cheap in Mar-20.
6. **Board (futures) options vs swaptions** — **FV and US cheap to swaptions (Mar-20, ratios 0.86/0.89)**; but **FV rich (Jan-19)** when judged against recent realized. The verdict is date-dependent and must be checked with **ftrs RV / swap RV** (1.17 in Mar-20) before treating the ratio as an edge.
7. **Curve gamma via CMS options** — [D1] *"curve gamma looks **cheap to recent realized vols**"* even while *"spread vol has **richened to swaptions**"* on implied correlation. The two metrics disagree by construction: implied-correlation says rich vs swaptions, implied/realized says cheap vs the curve's own delivered vol.
8. **Forward vol via gamma-neutral calendars** — buying a cheap forward vol point without paying for near-dated gamma; the whole point of the *gamma-neutral* weighting.
9. **FX vol vs rates vol** — *"rates vol continues to trade **very rich to FX vol** by historical standards"*; hence buy USDJPY put spreads rather than rates receiver spreads [D3].

**Rich / to-avoid sources**

- **Selling gamma into a ZLB transition.** *"We don't think **selling gamma is the best way to position for zero rates**… **selling delta-hedged gamma did not deliver consistent positive returns until a few months after the Fed brought rates to zero and initiated QE in the previous cycle.** As the fundamental uncertainty remains high, and incoming economic data is likely to surprise, we expect to continue to see outsized daily moves."* Plus the 0.6bp hedging cost. Preferred alternative: **sell 2y2y vega** [D1].
- **Long-tail gamma in the 30y** [D1]: 3m30y **4σ rich to rates**, **2.7σ rich on surface PCA**.
- **Short-dated risk reversals** — 3m10y **~3σ rich to realized skew** (Mar-20); but **6m10y ~2σ cheap** (Jan-20). Direction flips.
- **Curve spread vol** — 6m 2s10s **2.7σ rich on PCA** (Mar-20); EUR 10s30s rich on PCA; 10s30s implied/1m RV ~1.9–2.0 with z ~2.2 (Jan-20).
- **3y1y midcurves rich** (Mar-20), the mirror image of the cheap 1y3y1y/3y3y calendar.
- **Illiquidity as a veto.** [D1] declined to initiate the USD 15y5y/20y10y flattener despite the best z-score on the screen: *"we are adding this trade to our watch list but **don't initiate yet given the lack of liquidity and wide bid/offer spreads**."*
- **Regime caveat on YCC.** JPY 1y2y and 1y10y vols **collapsed** when the BoJ announced targeting the curve to 10y in 2016; a similar USD policy targeting Treasuries to 5y *"should be especially negative for upper-left USD volatilities"* [D1].

---

## PART 5 — RISK-WEIGHTING CONVENTIONS (quoted)

| Structure | Weighting rule |
|---|---|
| Long-dated curve flattener | **DV01-neutral**, sized in DV01 (**50K DV01** [D3]); rebalanced to DV01-neutral **on the longer leg** at each **25bp** move in the longer forward rate |
| Conditional curve (2-leg swaption) | **DV01-weighted notionals**, printed `100 / xx.x` ($mn); **smaller-vol leg struck ATM, other leg struck OTM for zero cost** |
| Conditional fly (payer/receiver) | **50/50 DV01 weights**, printed `xxx / 100 / xx.x`; **wings ATM, belly strike solved for zero cost** |
| Rates fly (for the rate levels quoted) | **−0.5 / 1 / −0.5 weights** on spot, forward and costless-strike flies |
| Vol tenor fly | **1x2x1** in vol terms; the traded structure is sized **vega-neutral** (e.g. **$230mn / $100mn / $21mn** for 3y2y/3y10y/3y30y) |
| Forward vol calendar / triangle | **gamma-neutral weights**, printed as `82.1 / 100`, `280.9 / 100`, `316.5 / 100`, etc. |
| Swaption vs Board option spread | **DV01-neutral**; **swaption notional is for 1000 Board contracts**; swaption strike solved so the DV01-neutral trade is **costless** |
| Board-vs-swaption skew mapping | **swaption strike = Board strike yield + invoice spread** |
| Cross-currency vega switch | matched expiry/tail straddles (10y10y vs 10y10y), vega-comparable |
| Rates-vs-FX | premium-driven, not risk-neutral: **$30mn USDJPY 108/105 put spreads vs $50mn 6m10y ATMF+45bp payers, net $35K** |
| Callable vega measure | **normal parallel vega** |

---

## PART 6 — KEY NUMERIC EXHIBITS

**D1, 30 Mar 2020 (close 3/27/20 unless noted)**
- 1m10y **103nv**; 2y2y **55nv** (2pm 3/27); 10y10y USD **59nv** vs EUR **57.4nv** (9:30am 3/27).
- 10y gamma **~3σ rich** on macro-vol; 3m30y **4σ rich** on macro-vol, **2.7σ rich** on PCA; 5y gamma relatively cheap.
- USD 15y5y/20y10y curve **−5.21bp** (3pm 3/26); **1y ZS 4.21**, 3y ZS 3.58, ZS-2000 1.02, **1y carry +0.11bp**, **daily BE 0.00**, 1y realized vol **6.40bp**, **BE/RV 0.00**.
- Fed buying **$75bn** Treasuries/day; **$2tn** fiscal stimulus; mid-to-bid/offer **~0.6bp** in 10y swaps.
- 5y5y inflation swaps: **US ~2.0%** vs **EUR 0.92%**.
- Callable: **$5.08bn** MTD (all financial), **vega $14.6mn**; 2020 YTD gross $20.62bn, vega $46.8mn; 2019 FY vega $37.8mn.
- Forward vol spot row: 1y2y **46.1**, 1y5y **63.8**, 1y10y **76.7**, 1y30y **80.6**.
- Frontier best-Sharpe: 3m20y/6m20y → 3m3m20y, **82.1/100**, 103.9/90.2/**74.1**, roll **29.75**, **Sharpe 4.17**. Best-value: 1y3y1y/3y3y → 1y2y3y, 280.9/100, 96.4/59.7/**31.4**, **1y ZS −4.8**.
- Skew: 3m10y RR **+11.6 vs model (z 3.2)**; 3m30y **+16.0 (z 3.6)**; 1y10y RR z **4.0**; 2y1y OTM receiver ratio **1.18 (z 6.7)**.
- Board: FVK0 **67.1** vs CTD swpn **77.8** → **0.86**; USK0 **106.9** vs **120.5** → **0.89**; TYK0 96.7/95.1 → 1.02; ftrs/swap RV **1.17 (1m)**, 1.12–1.14 (3m).
- Midcurve: 1m3y1y implied corr **94.4 (z −5.2)**; 1m3y2y **77.1 (z −6.9)**, RC **+31.6 (z 5.6)**; 3m1y2y RC **−10.2 (z −3.8)**, implied corr **125.3 (z 3.2)**.
- CMS: 6m 2s10s RC **+4.2 (z 2.7)**; implied/1m RV 6m 2s10s **0.42 (z −2.5)**, 1m 2s5s **0.36 (z −2.7)**.
- ED: M0-H1 **0.03bp**; H1-Z1 **0.38bp** (vs model +0.18, 3m z 2.40; implied 63.6 vs realized 84.2); M4-H5 **7.25bp**; implied/realized **0.6–0.8**.
- EUR: 1y10y **~5σ rich** on PCA; 10s30s CMS PCA 2y **+3.1 (z 2.8)**, 3y **+2.7 (z 2.9)**; 6m3y2y midcurve RC **−1.1 (z −3.0)**.
- Conditional-curve reference row: `3m 2y10y, 100/20.3, spot 17.3, fwd 29.5, strike 54.7, imp β 0.73, rlzd β 0.56, bear-steep total pick-up −37.4bp, 3m roll −13.9bp`.

**D2, 14 Jan 2019 (close 1/11/19)**
- 3m10y **66 → 59nv**; position **$100mn → $50mn**; ~**3 normals** above macro fair value; 3m10y ATM printed **58.7**.
- Prev-cycle surface PCA: **3y2y +5.7nv (3.6σ)**; **3y10y −1.9nv (2.2σ)**; 2y2y +6.7 (2.5σ); 2y10y −2.5 (−2.6σ); 3y1y +6.3 (2.4σ); 1y10y −3.0 (−2.0σ).
- **3y2y/3y10y/3y30y fly: −4.0nv, z −1.9; curve-model FV +5nv; carry +0.75nv/$43K over 1y and ~6nv/$341K over 2y; structure sell $230mn 3y2y / buy $100mn 3y10y / sell $21mn 3y30y for a $240K take-in.**
- Rich/cheap to rates: **2y1y +12.1nv (1.6σ)**; 30y tail cheap (1m30y −4.7); PCA: **3m5y +2.5 (2.5σ)**, 3m3m −8.0 (−2.7σ).
- Ratios: 1y **1y10y/1y30y 1.09 (z 2.2)**; 5y/10y expiry, 10y tail **1.08 (z −3.1)**; 3m/6m 1y tail 0.79 (z −2.3).
- Implieds cheap to realized across the board: 1m1y implied/1m RV (intraday) **0.70 (z −1.8)**; close-to-close 1m2y **0.59 (z −2.4)**.
- Skew: 3m2y RR **−8.7**, 6m2y **−14.6**; **3m30y +2.5 (z 1.0)**, **5y30y +1.2 (z 2.0)** rich to realized skew.
- Board: FVH9 **61.9** vs swpn **61.5** (ratio 1.01), **Board/1m RV 0.77 vs swpn/1m RV 0.67**; ftrs/swap 1m RV 0.88.
- Midcurve: 2y3y1y RC **−3.4 (z −1.7)**, 1y5y5y RC **−2.5 (z −1.9)**; 1m1y2y implied corr **71.4**.
- CMS: 10s30s implied/1m RV **0.73 (z −2.2)** at 1m; PCA 3y 10s30s **−1.4 (z −1.9)**.
- ED: H9-Z9 **0.06bp** (3m z −1.21), M0-H1 **1.09bp** (3m z −3.01), H3-Z3 **7.44bp**; roughly fair to model.
- Frontier: 15y15y/20y5y → 15y5y5y, **30.9/100**, 56.2/55.4/**53.3**, roll **0.38nv**, Sharpe 0.30.
- Callable: **$1.21bn** MTD, vega **$2.9mn**; 2018 FY gross $23.89bn, vega **$53.3mn**.

**D3, 17 Jan 2020 (close 1/16/20 unless noted)**
- **GBP 15y10y/25y10y flatteners initiated, 50K DV01, at −11.2bp** (12pm 1/17/20). Screen: **−10.37bp**, 1y ZS −0.01, 3y ZS 1.15, **ZS-2000 1.84**, **1y carry +0.52bp**, **daily BE 0.00**, 1y realized **4.19bp**, **BE/RV 0.00**.
- Cross-currency BE/RV ranges: GBP **0.00–0.89**, USD **0.00–1.08**, EUR **0.60–1.48**, CAD **0.00–1.82**, JPY **0.76–1.50**.
- Formosa: **$5.3bn** MTD (vs $5bn projection), possibly **$6bn**; **~$16mn normal vega**, highest since Jan-2018; shift to **40NC5**.
- **10y20y 54.6nv / 5y30y 56.6nv** (1pm 1/17) = long 5y-fwd 5y20y.
- **$30mn USDJPY 108/105 put spreads vs $50mn 6m10y ATMF+45bp (2.2%) payers, net $35K**; USDJPY **110.17**; regression **USDJPY = 0.0266x + 103.48, R² 0.32** (2018-19 sample).
- 6m10y **~0.4σ rich** on macro-vol, **~1.1σ rich** on PCA.
- 6m10y RR **−6.4 vs model (z −2.0)** = ~2σ cheap to realized skew; 3m2y RR −10.9; 6m1y RR −17.0.
- Midcurve **1y5y5y RC −2.3 (z −2.8)**, 6m5y5y −2.5 (z −2.5).
- CMS: 2s10s PCA 3m **+3.8 (z 2.4)**, 6m +3.2 (z 2.2); **10s30s implied/1m RV 1.90 (3m, z 2.1), 1.97 (6m, z 2.3), 2.03 (1y, z 2.2)**.
- **3y 5s30s conditional bear steepener zero-cost strike spread ≈ 14bp** (3pm 1/16).
- ED: H0-Z0 **−0.02bp**, H2-Z2 **1.93bp** (vs model +0.49, 3m z 2.05), H4-Z4 **5.58bp**; implied/realized **0.7–1.0**.
- Frontier: 1y3y2y/18m7y → 1y6m7y, 316.5/100, 69.5/62.9/**51.1**, roll **2.28**, Sharpe 0.26; 1y2y2y/18m5y → 1y6m5y, 224.4/100, 68.6/62.6/**49.8**, roll 2.23.
- EUR: **1y5y ~2.8σ rich on PCA**; 30y tail cheap on PCA; 1m 10s30s CMS PCA **−3.6 (z −1.6)**.

---

## PART 7 — IMPLICATIONS FOR A 3-STRATEGY IMPLEMENTATION

- **The convexity-cheapness screen is a two-number test**, not a z-score: `1y carry` plus `daily BE / realized vol`. Positive carry forces BE to zero, which is precisely the "free convexity" condition. Rank by BE/RV ascending; break ties with `ZS since 2000` (long-run steepness) rather than 1y ZS, which is noisy (GBP's 1y ZS was −0.01 while ZS-2000 was 1.84 on the day the trade was initiated).
- **Every entry is a flow dislocation with a named counterparty** (VA hedgers in USD 20y, ALM receivers in GBP 20y, Formosa/callable issuers in the bottom-right). A screen without the flow story produces the D1 outcome — best z-score on the sheet, not initiated, because liquidity vetoed it.
- **Rich/cheap verdicts do not persist across dates**; only the methodology does. Do not hard-code any of the directional calls above.
- **Two independent cheapness metrics routinely disagree** (implied-correlation vs implied/realized on CMS curve options; Board/swaption ratio vs Board-to-realized-vol). Decide in advance which is the arbiter, or require agreement.
- **Hedge-time selection is an empirical input, not a convention** — the time-of-day realized-vol table (3m/6m/1y) determines the snapshot; the delta threshold (15%) and the curve rebalance band (20–25bp) are the two quoted maintenance parameters, both explicitly justified as accuracy-vs-transaction-cost trade-offs.