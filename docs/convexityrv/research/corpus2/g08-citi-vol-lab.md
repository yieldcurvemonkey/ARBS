# G08 — Citi US Rates Vol Lab corpus: ED/SOFR convexity adjustments, long-dated convexity flatteners, transaction costs

Corpus: 14 markdown-converted PDFs from `C:/Users/chris/Downloads/convexityrv_markdown`. All are **Citi Research** publications (the weekly "US Rates Vol Lab" / later "Rates Vol Lab" series, plus three North America Rates Trade Idea alerts). Authors: Ruslan Bikbov + Jason Williams (2016–2020 issues); Mike Chang + Jason Williams + Andrea Appeddu (2021–2023 issues).

This corpus is the **primary source for the Citi convexity-adjustment (CA) framework** referenced in the parent project ("Citi: Blues CA = a + b*(fly)"-style fair value). Key finding up front:

> **NEGATIVE FINDING:** No document in this corpus contains a regression of CA on a swap butterfly. Citi's published CA fair-value model here is a **one-factor Ho-Lee model calibrated to LIBOR cap/floor vols** (never a curve-fly regression). If a "Blues CA = a + b·fly" Citi model exists, it is not sourced from these 14 documents. What IS here: the exact CA definition, the Ho-Lee formulas, 11 dated full-curve CA tables (2016–2023) usable as known-answer tie-outs, the CFTC-positioning-vs-CA narrative and chart spec, one fully-specified CA short trade with entry/target/stop, and the delta-hedged long-dated-flattener franchise (a *swap-space* convexity RV that is the mirror image of the futures CA trade).

---

## 0. Cross-cutting reference (applies to every Vol Lab issue)

### 0.1 CA definition — verbatim, and its evolution

Standing footnote, 2016–2020 (Eurodollar era):

> "Convexity adjustments for 1y ED packs are computed as the spread between the pack's rate (the average of 4 ED rates in the pack) and matched-maturity forward 1y swap rate. The model for convexity adjustment is the Ho-Lee model calibrated to cap/floor vols. Implied vol is calculated by matching the model to the observed convexity adjustment. Realized vol is 3m realized vol of the corresponding pack."

2023 (SOFR era) is identical with "SOFR" substituted: *"the spread between the pack's rate (the average of 4 SOFR rates in the pack) and matched-maturity forward 1y CME swap rate."*

**Evolution of the swap leg (CME vs LCH — feeds the clearing-basis variation):**
- 12 Dec 2016, 9 Jan 2017, 1 May 2017, 12 Mar 2018 issues: "matched-maturity forward 1y **swap** rate" (no CCP qualifier; pre-dates a large CME-LCH basis in these notes).
- From 14 Jan 2019 onward the table is titled "**(vs CME swaps)**" and the footnote says "forward 1y **CME** swap rate".
- 22 Jun 2021 gives the explicit rationale: "The analysis is based on the **CME FRA/swap curve, which we favor over LCH-cleared swaps because clearing on CME is more capital-efficient due to netting of futures and swap positions for margin calculations**."

So Citi's CA is measured **futures pack rate minus CME-cleared matched-maturity forward 1y swap**; an LCH-based CA would differ by the CME-LCH basis at that forward point.

### 0.2 Structure conventions

- **Pack** = 4 consecutive quarterly contracts; the CA table is built on **1y packs rolled quarterly**, labeled by first–last contract (e.g. `M4-H5` = Jun-24, Sep-24, Dec-24, Mar-25). Pack rate = simple average of the 4 futures rates. Whites/Reds/Greens/Blues/Golds = ranks 1-4/5-8/9-12/13-16/17-20; the standing charts track **Greens, Blues, Golds packs (rolling) vs the Ho-Lee model**.
- The matched swap is a **forward-starting 1y swap** whose accrual window matches the pack (Jun 2021 trade: pack EDM4-H5 vs forward swap 6/17/2024–6/16/2025).
- Table columns (identical format every issue): CA (bp); 1-week change (bp); 3m and 1y z-scores of the CA; "Vs Model" (bp, CA minus Ho-Lee fair value) with 3m and 1y z-scores; "3m Roll (short cvx, bp)" — the 3-month rolldown earned by the CA seller; Implied Vol (normal vol backed out of the observed CA via Ho-Lee); Realized Vol (3m realized vol of the pack rate); Implied/Realized ratio; Cap-vol Impl/Rlzd ratio. Three best short-convexity trades per metric marked in bold.

### 0.3 Ho-Lee machinery (verbatim from the 22 Jun 2021 technical appendix)

- Mechanism of CA: futures have **zero convexity** (constant DV01, price linear in rate; priced as undiscounted risk-adjusted expectation because of daily VM without PAI), while cleared FRAs/swaps are discounted and hence **positively convex**; CME pays/collects **Price Alignment Interest (PAI)** on FRA variation margin but not on futures. Long futures funds VM when rates rise and reinvests only when rates fall ⇒ ED trades at a rate discount... i.e. futures **rate** above forward rate; CA > 0.
- One-factor normal (Ho-Lee) closed form:
  `CA = (Fwd + 1/Δ) · [exp(σ²·T·Δ·(Δ + T/2)) − 1]`, with T = maturity of FRA/futures, σ = annualized normal vol of the FRA, Fwd = FRA rate, Δ = 0.25 (3m underlying).
- Practical approximation (Δ→0 limit): `CA ≈ σ²T²/2`.
- Used two ways: (1) calibrated to cap/floor vols ⇒ fair value ("Vs Model"); (2) inverted on the observed CA ⇒ CA-implied vol.
- Skew/smile and forward-curve cross-correlations affect CA in principle but "the quantitative impact of these factors is much smaller in practice."
- Expected P&L of the CA seller held to maturity (bp of yield):
  `E[P&L] = E ∫₀ᵀ (T−t)·[σ²_implied(t) − σ²_realized(t)] dt`
  — selling CA ≡ selling delta-hedged straddles: seller earns curve rolldown (≈ option decay) and pays MTM/PAI cash-flow drag (≈ delta-hedging bleed). The implied/realized vol ratio is therefore the ex-ante profitability gauge, exactly as for gamma selling.

### 0.4 Dealer-positioning ↔ CA relationship

Recurring attribution across issues (dated instances):
- **9 Jan 2017**: "ED convexities have richened, especially in longer maturities, likely due to **short positions in ED futures established post FOMC**." Blues ≈ 3σ rich to model.
- **12 Mar 2018**: Blues/Golds widened vs model, "likely driven by **short positioning in futures**."
- **14 Jan 2019**: CAs compressed to fair, "driven by **short covering** of ED futures positions."
- **30 Mar 2020**: Blues/Golds richened "perhaps due to **profit taking on long positions** in ED futures."
- **22 Jun 2021** (the explicit chart): Figure 12 plots **CFTC Asset Managers + Leveraged Funds net position as % of open interest (inverted)** against **Blues CA − model**; build-up of shorts (expressed in ED futures rather than FRAs/swaps for liquidity) widens the observed CA; "shorts may be at risk of capitulation... we expect the convexity bias to tighten." Sample shown Jun-16 to Jun-21; net%OI axis −8% to +4%, CA−model axis −3 to +4bp.

This is Citi's dealer/spec-positioning-conditioned CA story: **CA rich vs Ho-Lee ⇔ speculative duration shorts concentrated in futures; CA normalization catalyzed by short covering.** Direction: shorts in futures push the futures rate up vs the swap ⇒ CA wider.

### 0.5 Fly-weight convention warning

Citi's conditional-fly tables quote rate flies with **−0.5 / +1 / −0.5 weights** ("Spot, forward and costless strike rates flies are reported using -0.5/1/-0.5 weights"). This is **half** the 2·belly − front − back convention used in ARBS (`reference_sfr_fly_conventions`). Any tie-out of a Citi-published fly level must divide the repo's fly by 2 (or double Citi's number).

### 0.6 Transaction-cost assumptions (the only quantified cost tables in the corpus)

**Swap bid/offer history (12 Mar 2018, Figure 8; one-way, used for delta-hedging in backtests):**

| period | 2y/5y/10y (bp) | 30y (bp) | option b/o scale |
|---|---|---|---|
| 1995–H1 1998 | 1.6 | 2.1 | 2.7 |
| H2 1998–H1 1999 | 2.0 | 2.6 | 3.0 |
| H2 1999–2000 | 1.4 | 2.0 | 2.2 |
| 2000–2004 | 1.2 | 1.6 | 2.0 |
| 2005–2007 | 0.6 | 0.8 | 1.5 |
| 2008–2009 | 1.2 | 1.6 | 2.0 |
| 2010–2012 | 0.7 | 0.9 | 1.5 |
| 2013–2016 | 0.4 | 0.5 | 1.25 |
| 2017–2018 | 0.3 | 0.4 | 1.0 |

Swaption bid/offer 2017-18 (normals): 1m straddles 1.5 (1m10y: 1.0); 1m 25%D strangles 2.0 (10y: 1.25); 3m straddles 1.0 (10y: 0.5); 3m strangles 1.5 (10y: 0.75). Mar-2020 stress datapoint: 10y swap mid-to-bid/offer ~0.6bp.

**Long-dated flattener costs (9 May 2019, Figure 9; one-way, mid-to-bid/offer in bp, for $100K DV01):**

| curve | 10y5y/15y15y | 10y10y/15y15y | 10y10y/20y10y | 10y10y/20y15y | 10y10y/25y10y | 15y5y/20y10y | 15y5y/20y15y | 20y5y/25y10y |
|---|---|---|---|---|---|---|---|---|
| initiation | 0.75 | 0.75 | 0.75 | 1.0 | 1.0 | 0.75 | 1.0 | 1.0 |
| delta-hedging & roll | 0.3 | 0.3 | 0.3 | 0.4 | 0.4 | 0.3 | 0.4 | 0.4 |

---

## 1. US Rates Vol Lab: Trading long-dated convexity — Citi Research, 9 May 2019 (25pp; Bikbov & Williams)

File: `US Rates Vol Lab_ Trading long-dated convexity.pdf.md`

**The flagship long-dated-convexity note.** Thesis: convexity embedded in long-dated forward flatteners is cheap to realized vol; systematic delta-hedging of DV01-neutral flatteners is profitable and structurally long vol.

Mechanics: 10y10y/20y10y flattener = receive 20y10y fwd swap vs pay 10y10y fwd swap, DV01-neutral. At those horizons policy expectations flatten out so the curve is "mostly determined by convexity adjustments, term premiums and technical factors"; 20y10y has more convexity per unit DV01 ⇒ the flattener is positively convex and rolls negatively (fwd curve inverted). Trade ≈ long straddle; the 10y10y/20y10y spread ≈ implied vol / vega. **Regression (Fig 2): 10y10y/20y10y curve (bp) on 2y10y normal vol: y = −0.5x + 19.0, R² = 0.5, sample 1/4/2010–5/3/2019.**

**Backtest (Fig 4):** $100K DV01 flatteners, rolled annually, delta-hedged by adjusting the longer-leg notional at each 25bp move in the longer rate (market close); sample 12/31/2013–5/7/2019 (analysis from 2004 for curve history); Sharpe insensitive for 15–30bp thresholds, worse outside:

| flattener | 10y5y/15y15y | 10y10y/15y15y | 10y10y/20y10y | 10y10y/20y15y | 10y10y/25y10y | 15y5y/20y10y | 15y5y/20y15y | 20y5y/25y10y |
|---|---|---|---|---|---|---|---|---|
| avg daily return, $K | 0.67 | 1.15 | 2.28 | 3.20 | 5.40 | 2.92 | 3.79 | 4.09 |
| daily vol of P&L, $K | 195.3 | 142.4 | 222.1 | 208.5 | 247.6 | 251.5 | 241.7 | 219.3 |
| Sharpe | 0.05 | 0.13 | 0.16 | 0.24 | 0.35 | 0.18 | 0.25 | 0.30 |

Corr(monthly P&L, Δ1y10y vol) ≈ +26%; daily-P&L skewness ≈ 0 (vs short 1m10y straddles: Sharpe 0.84, skewness ≈ −3). Corr(monthly P&L of 15y5y/20y10y, S&P monthly returns) ≈ 0; corr(stocks, 15y5y/20y10y curve) ≈ −23% (VA-hedging risk).

**Entry screen (Fig 7, close of 5/8/2019)** — daily BE = parallel shift whose convexity gain offsets daily roll (0 if roll positive):

| metric | 10y5y/15y15y | 10y10y/15y15y | 10y10y/20y10y | 10y10y/20y15y | 10y10y/25y10y | 15y5y/20y10y | 15y5y/20y15y | 20y5y/25y10y |
|---|---|---|---|---|---|---|---|---|
| curve, bp | −10.1 | −8.8 | −13.2 | −16.7 | −20.1 | −11.3 | −15.2 | −9.1 |
| 1y ZS | 2.50 | 2.15 | 1.87 | 2.41 | 2.38 | 1.16 | 1.62 | 1.95 |
| 3y ZS | 0.19 | 0.39 | 0.53 | 0.50 | 0.55 | 1.01 | 0.99 | 0.87 |
| 1y carry, bp | −2.91 | −1.64 | −1.75 | −1.88 | −1.83 | −0.31 | −0.44 | 0.13 |
| daily BE, bp | 3.5 | 3.0 | 2.6 | 2.5 | 2.2 | 1.3 | 1.3 | 0.0 |
| 1y realized vol, bp | 3.2 | 3.2 | 3.1 | 3.1 | 3.0 | 3.0 | 3.0 | 3.0 |
| BE/realized vol | 1.07 | 0.94 | 0.84 | 0.79 | 0.72 | 0.42 | 0.45 | 0.00 |

**Recommendation:** 15y5y/20y10y delta-hedged flattener (carry −0.44bp/y vs 1.3bp daily BE; 20y10y realized 3.0bp/1y, 2.8bp/3m; hedge every 15–30bp). Risk: VA receiving in ~20y on equity selloffs. (Trade lineage continues in docs 12–13.)

**ED CA table (Fig 60, close of 5/8/2019, vs CME swaps):**

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll bp | Impl vol | Rlzd vol | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M9-H0 | 0.01 | 0.00 | −1.01 | −0.86 | −0.03 | −0.99 | −0.92 | 0.03 | 30.6 | 53.8 | 0.6 | 0.8 |
| U9-M0 | 0.08 | 0.00 | −1.07 | −1.58 | −0.02 | −1.25 | −1.76 | 0.06 | 49.4 | 60.1 | 0.8 | 0.8 |
| Z9-U0 | 0.17 | −0.01 | −1.34 | −1.67 | −0.02 | −1.39 | −1.85 | 0.10 | 57.0 | 66.0 | 0.9 | 0.8 |
| H0-Z0 | 0.30 | −0.01 | −1.52 | −1.75 | −0.02 | −1.45 | −1.90 | 0.12 | 60.7 | 69.7 | 0.9 | 0.8 |
| M0-H1 | 0.43 | −0.02 | −1.67 | −1.84 | −0.05 | −1.46 | −1.90 | 0.14 | 61.5 | 71.4 | 0.9 | 0.8 |
| U0-M1 | 0.58 | −0.03 | −1.73 | −1.89 | −0.09 | −1.52 | −1.86 | 0.15 | 61.4 | 71.3 | 0.9 | 0.9 |
| Z0-U1 | 0.75 | −0.05 | −1.72 | −1.95 | −0.14 | −1.60 | −1.82 | 0.17 | 61.2 | 70.1 | 0.9 | 0.9 |
| H1-Z1 | 0.95 | −0.06 | −1.71 | −2.00 | −0.19 | −1.66 | −1.80 | 0.20 | 61.2 | 68.3 | 0.9 | 0.9 |
| M1-H2 | 1.21 | −0.08 | −1.72 | −2.03 | −0.21 | −1.71 | −1.77 | 0.26 | 62.2 | 66.0 | 0.9 | 1.0 |
| U1-M2 | 1.58 | −0.09 | −1.46 | −1.85 | −0.15 | −1.43 | −1.56 | 0.37 | 64.8 | 64.0 | 1.0 | 1.0 |
| Z1-U2 | 1.83 | −0.12 | −0.77 | −1.77 | −0.26 | −0.71 | −1.43 | 0.25 | 63.8 | 62.2 | 1.0 | 1.1 |
| H2-Z2 | 2.12 | −0.19 | −0.48 | −1.65 | −0.35 | −0.41 | −1.19 | 0.29 | 63.3 | 60.6 | 1.0 | 1.1 |
| M2-H3 | 2.24 | −0.32 | −0.69 | −1.76 | −0.64 | −0.63 | −1.26 | 0.11 | 60.4 | 59.6 | 1.0 | 1.1 |
| U2-M3 | 2.67 | −0.39 | −0.98 | −1.79 | −0.66 | −0.91 | −1.16 | 0.43 | 61.6 | 58.8 | 1.0 | 1.1 |
| Z2-U3 | 3.21 | −0.46 | −1.61 | −1.92 | −0.59 | −1.49 | −1.16 | 0.54 | 63.3 | 58.5 | 1.1 | 1.1 |
| H3-Z3 | 3.98 | −0.41 | −1.98 | −1.95 | −0.34 | −1.44 | −1.10 | 0.77 | 66.4 | 58.4 | 1.1 | 1.2 |
| M3-H4 | 4.93 | −0.22 | −1.69 | −1.91 | 0.04 | −1.06 | −0.99 | 0.95 | 69.7 | 58.2 | 1.2 | 1.2 |

Commentary: "Golds... now trade only slightly rich to the model, while Blues convexities look cheap to the model."

Other tie-outs (close 5/8/19): ATM vol grid (e.g. 3m10y 55.1nv, 1y10y 58.3nv, 5y30y 53.7nv, 10y10y 59.2nv); 3y30y ≈2σ cheap to rates, 1.3σ cheap on PCA; 3m2y ~0.8σ rich; curve-vol grid (1m 2s10s 25.3nv, 1m 10s30s 15.6nv); conditional curve/fly tables at −0.5/1/−0.5 weights (spot 3m 2s10y fly 1y3y5y −9.7bp etc.); 3y 5s30s conditional bear steepener zero-cost strike spread ≈8bp (3pm 5/8/19). Callable supply: Apr-19 gross $0.73bn, 2019 YTD $5.44bn (vs 2018 YTD $20.09bn, FY2018 $23.89bn, vega $53.3mn).

---

## 2. US Rates Vol Lab: The art of gamma hedging — Citi Research, 12 Mar 2018 (25pp; Bikbov & Williams)

File: `US_Rates_Vol_Lab_The_art_of_gamma_hedging.pdf.md`

Weekly focus: sell 1m10y straddles delta-hedged daily around noon; buy 1x2 6m1y1y receiver spreads. Relevance to CA project: the **systematic gamma-selling backtest** whose Sharpe/threshold trade-off is the benchmark Citi reuses for the CA-selling and flattener strategies, plus the historical bid/offer table (§0.6).

**Short-gamma backtest (Fig 3; 1997–2017; sell same notional daily, hold to expiry, ~21 (1m) or 63 (3m) option portfolio):**
- Daily delta-hedged straddles avg daily return (bp running): 1m2y −0.45, 1m5y 0.09, **1m10y 0.64 (Sharpe 0.48)**, 1m30y −0.11, 3m10y 1.63 (0.50).
- 25%-delta-threshold hedged straddles: 1m10y 1.41bp, **Sharpe 0.84**, monthly hit 65%, yearly hit 81%, Calmar 0.27; 3m10y Sharpe 0.71.
- Unhedged straddles 1m10y Sharpe 0.43.
- Fig 4: with 0.3bp swap bid/offer, Sharpe maximized at 0% threshold (daily hedging); at 0.5bp b/o optimum is 3–7% delta threshold.
- Optimal hedging time drifted to 12pm–1pm over last 6m (2014–2018 realized-vol-by-timestamp analysis).

Trade: Buy $500mn 6m1y1y ATMF−15bp receivers vs sell $1bn 6m1y1y ATMF−30bp receivers, take-in $200K (10am 3/9/2018); terminal loss only if 1y1y < 2.38% at expiry.

**ED CA table (Fig 57, close of 3/9/2018)** — Blues/Golds ~2σ+ rich to model, "would consider selling":

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H8-Z8 | 0.12 | −0.01 | −0.78 | −1.14 | 0.08 | −0.96 | −1.31 | 0.06 | 97.8 | 44.2 | 2.2 | 0.9 |
| M8-H9 | 0.24 | −0.02 | −1.01 | −1.18 | 0.18 | −1.21 | −1.31 | 0.13 | 97.8 | 46.4 | 2.1 | 0.9 |
| U8-M9 | 0.41 | −0.04 | −1.39 | −1.24 | 0.29 | −1.70 | −1.42 | 0.17 | 95.7 | 49.4 | 1.9 | 0.9 |
| Z8-U9 | 0.63 | −0.06 | −1.66 | −1.26 | 0.41 | −2.03 | −1.49 | 0.21 | 94.1 | 52.4 | 1.8 | 1.0 |
| H9-Z9 | 0.88 | −0.07 | −1.85 | −1.25 | 0.52 | −2.23 | −1.52 | 0.26 | 92.8 | 55.4 | 1.7 | 1.0 |
| M9-H0 | 1.19 | −0.08 | −1.80 | −1.23 | 0.63 | −2.22 | −1.54 | 0.30 | 91.8 | 58.4 | 1.6 | 1.0 |
| U9-M0 | 1.54 | −0.08 | −1.60 | −1.18 | 0.75 | −2.11 | −1.51 | 0.36 | 91.3 | 60.7 | 1.5 | 1.0 |
| Z9-U0 | 1.96 | −0.10 | −1.35 | −1.09 | 0.86 | −1.97 | −1.44 | 0.42 | 91.2 | 62.3 | 1.5 | 1.0 |
| H0-Z0 | 2.42 | −0.13 | −1.17 | −1.00 | 0.97 | −1.84 | −1.36 | 0.46 | 91.1 | 63.1 | 1.4 | 1.1 |
| M0-H1 | 2.99 | −0.17 | −1.02 | −0.98 | 1.10 | −1.73 | −1.43 | 0.57 | 91.8 | 63.5 | 1.4 | 1.1 |
| U0-M1 | 3.80 | −0.12 | −0.54 | −0.81 | 1.43 | −1.31 | −1.31 | 0.81 | 94.7 | 63.7 | 1.5 | 1.1 |
| Z0-U1 | 4.78 | 0.03 | −0.06 | −0.49 | 1.86 | −0.84 | −0.79 | 0.97 | 97.8 | 63.9 | 1.5 | 1.2 |
| H1-Z1 | 6.00 | 0.22 | 0.32 | −0.03 | 2.48 | −0.47 | −0.09 | 1.22 | 101.6 | 64.2 | 1.6 | 1.2 |
| M1-H2 | 7.11 | 0.43 | 0.52 | 0.23 | 2.95 | −0.30 | 0.24 | 1.12 | 103.1 | 64.6 | 1.6 | 1.2 |
| U1-M2 | 7.94 | 0.57 | 0.55 | 0.19 | 3.07 | −0.29 | 0.19 | 0.82 | 102.0 | 64.8 | 1.6 | 1.2 |
| Z1-U2 | 8.53 | 0.58 | 0.56 | 0.02 | 2.90 | −0.34 | −0.05 | 0.59 | 99.2 | 64.9 | 1.5 | 1.2 |
| H2-Z2 | 8.97 | 0.55 | 0.67 | −0.22 | 2.55 | −0.37 | −0.39 | 0.45 | 96.0 | 65.1 | 1.5 | 1.2 |

Other tie-outs (close 3/9/18): 1m10y 61.4nv, 3m10y 65.0nv, 3m30y 62.0nv; 5y5y/5y10y ratio 3.5σ high; TY Board/swaption 1.03; conditional 1y3y/1y3y1y bull steepener zero-cost strike spread −7bp (ATMF−15/−28, 8am 3/12/18); board vs swaption skew tables (FVK8/TYK8/USK8 full strike grids). Conditional fly tables at −0.5/1/−0.5 weights (e.g. spot 1y3y5y fly +12.4bp, 2y10y30y +13.6bp, close 3/9/18).

---

## 3. US Rates Vol Lab: Gamma and Vega RV — Citi Research, 14 Jan 2019 (24pp; Bikbov & Williams)

File: `US_Rates_Vol_Lab_Gamma_and_Vega_RV.pdf.md`

Weekly focus: halve short 3m10y straddle position (sold at 66nv, now ~59nv, hedged 9am EST with 15% delta threshold); **vega tenor fly**: sell $230mn 3y2y ATMF straddles / buy $100mn 3y10y ATMF straddles / sell $21mn 3y30y ATMF straddles, vega-neutral, take-in $240K (9am 1/11/19), carry +0.75nv ($43K) over 1y and ~6nv ($341K) over 2y. Vol-fly fair value = **regression of the 3y2y/3y10y/3y30y vol fly on the level and slope of the forward curve, sample 2003–present excluding ZLB 6/1/2008–1/1/2016**; fair value +5 normals vs market at record cheap. PCA framework spliced Jan04–Jan08 + Jan17–present: 3y2y 5.7nv (3.6σ) rich, 3y10y 1.9nv (2.2σ) cheap.

**ED CA table (Fig 57, close of 1/11/2019, vs CME swaps)** — "now trade roughly fair to the model... driven by short covering":

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H9-Z9 | 0.06 | −0.07 | −1.21 | −1.02 | 0.00 | −1.73 | −1.19 | 0.06 | 53.3 | 61.0 | 0.9 | 0.7 |
| M9-H0 | 0.17 | −0.09 | −1.99 | −2.35 | 0.05 | −2.43 | −3.41 | 0.12 | 68.6 | 65.0 | 1.1 | 0.8 |
| U9-M0 | 0.33 | −0.13 | −2.21 | −2.40 | 0.10 | −2.77 | −3.91 | 0.16 | 74.2 | 71.4 | 1.0 | 0.8 |
| Z9-U0 | 0.53 | −0.15 | −2.46 | −2.55 | 0.13 | −2.96 | −4.32 | 0.20 | 77.3 | 76.2 | 1.0 | 0.8 |
| H0-Z0 | 0.79 | −0.16 | −2.79 | −2.76 | 0.16 | −2.85 | −4.29 | 0.25 | 79.3 | 78.9 | 1.0 | 0.8 |
| M0-H1 | 1.09 | −0.16 | −3.01 | −2.79 | 0.18 | −2.58 | −3.72 | 0.30 | 80.7 | 80.4 | 1.0 | 0.9 |
| U0-M1 | 1.46 | −0.14 | −3.03 | −2.48 | 0.21 | −2.25 | −3.08 | 0.37 | 82.2 | 80.7 | 1.0 | 0.9 |
| Z0-U1 | 1.88 | −0.13 | −2.87 | −2.12 | 0.24 | −2.04 | −2.65 | 0.42 | 83.4 | 79.8 | 1.0 | 0.9 |
| H1-Z1 | 2.35 | −0.12 | −2.60 | −1.79 | 0.27 | −2.00 | −2.35 | 0.48 | 84.4 | 78.4 | 1.1 | 1.0 |
| M1-H2 | 2.81 | −0.29 | −3.19 | −1.84 | 0.23 | −2.01 | −2.43 | 0.46 | 84.1 | 76.9 | 1.1 | 1.0 |
| U1-M2 | 3.29 | −0.50 | −2.69 | −1.71 | 0.17 | −1.83 | −2.14 | 0.48 | 83.7 | 75.1 | 1.1 | 1.0 |
| Z1-U2 | 3.69 | −0.68 | −1.75 | −1.37 | −0.02 | −1.40 | −1.72 | 0.40 | 81.9 | 73.5 | 1.1 | 1.1 |
| H2-Z2 | 4.22 | −0.87 | −1.10 | −1.19 | −0.12 | −0.96 | −1.47 | 0.52 | 81.3 | 72.0 | 1.1 | 1.1 |
| M2-H3 | 4.52 | −0.96 | −1.42 | −1.40 | −0.46 | −1.18 | −1.57 | 0.31 | 78.7 | 70.3 | 1.1 | 1.1 |
| U2-M3 | 5.28 | −0.97 | −1.24 | −1.37 | −0.43 | −1.07 | −1.54 | 0.75 | 79.8 | 68.6 | 1.2 | 1.2 |
| Z2-U3 | 6.16 | −0.83 | −1.53 | −1.41 | −0.29 | −1.19 | −1.61 | 0.89 | 81.3 | 66.9 | 1.2 | 1.2 |
| H3-Z3 | 7.44 | −0.41 | −0.87 | −1.02 | 0.20 | −0.58 | −1.40 | 1.28 | 84.4 | 65.5 | 1.3 | 1.2 |

Other tie-outs (close 1/11/19): 3m10y 58.7nv, 1y30y 59.5nv; tenor-vol-fly table (3y 2y/10y/30y fly −4.0nv, z −1.9 since 1999); 10s30s curve vol 1m 13.7nv cheap on PCA; 15y15y/20y5y fwd-vol calendar on efficient frontier.

---

## 4. US Rates Vol Lab: Fair value vs seasonality — Citi Research, 1 May 2017 (23pp; Bikbov & Williams)

File: `US_Rates_Vol_Lab_Fair_value_vs_seasonality.pdf.md`

Weekly focus: gamma back to fair (macro-vol fair value for 3m10y ≈ 72bp vs market 70nv; framework = regression of vols on rates/curve calibrated to pre-2008 + 2017, "model broken with near-zero FedFunds ≤50bp"); May seasonality bullish gamma (outperformed 4 of last 5 Mays, 7 of 10). **CA section maintains the standing short-Blues trade: "We maintain our short Blues convexity trade hedged for the fair value (North America Rates Trade Idea: Sell Blues convexity adjustments, hedged)"** — evidence the Citi CA franchise ran a live hedged short-Blues-CA trade in 2017.

**ED CA table (Fig 52, close of 4/28/2017)** — CAs "remain very wide to the model":

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M7-H8 | 0.26 | −0.01 | −0.34 | 0.37 | 0.22 | −0.30 | 0.52 | 0.13 | 121.0 | 47.2 | 2.6 | 0.8 |
| U7-M8 | 0.53 | 0.00 | −0.35 | 0.44 | 0.46 | −0.27 | 0.64 | 0.27 | 125.4 | 52.1 | 2.4 | 0.8 |
| Z7-U8 | 0.91 | 0.01 | −0.40 | 0.51 | 0.77 | −0.25 | 0.79 | 0.38 | 127.5 | 56.5 | 2.3 | 0.8 |
| H8-Z8 | 1.40 | 0.01 | −0.45 | 0.69 | 1.16 | −0.20 | 1.06 | 0.49 | 128.6 | 61.0 | 2.1 | 0.8 |
| M8-H9 | 1.99 | 0.01 | −0.47 | 0.84 | 1.60 | −0.12 | 1.25 | 0.59 | 129.2 | 64.1 | 2.0 | 0.8 |
| U8-M9 | 2.62 | 0.00 | −0.61 | 0.85 | 2.02 | −0.13 | 1.29 | 0.63 | 127.9 | 67.0 | 1.9 | 0.9 |
| Z8-U9 | 3.32 | −0.02 | −0.81 | 0.83 | 2.43 | −0.16 | 1.29 | 0.70 | 126.6 | 69.8 | 1.8 | 0.9 |
| H9-Z9 | 4.11 | −0.05 | −0.89 | 0.80 | 2.84 | −0.05 | 1.30 | 0.78 | 125.5 | 72.2 | 1.7 | 0.9 |
| M9-H0 | 4.94 | −0.09 | −1.05 | 0.74 | 3.21 | 0.04 | 1.27 | 0.83 | 124.2 | 74.1 | 1.7 | 0.9 |
| U9-M0 | 5.60 | −0.21 | −1.39 | 0.60 | 3.33 | −0.11 | 1.18 | 0.66 | 120.4 | 75.5 | 1.6 | 1.0 |
| Z9-U0 | 6.08 | −0.29 | −2.33 | 0.30 | 3.21 | −0.94 | 0.80 | 0.47 | 115.1 | 76.2 | 1.5 | 1.0 |
| H0-Z0 | 6.76 | −0.37 | −2.82 | 0.24 | 3.27 | −1.32 | 0.70 | 0.69 | 112.3 | 76.6 | 1.5 | 1.0 |
| M0-H1 | 7.25 | −0.45 | −2.63 | 0.01 | 3.11 | −2.15 | 0.37 | 0.49 | 108.0 | 76.5 | 1.4 | 1.0 |
| U0-M1 | 8.05 | −0.40 | −2.31 | −0.05 | 3.23 | −1.92 | 0.33 | 0.80 | 106.3 | 76.3 | 1.4 | 1.0 |
| Z0-U1 | 9.20 | −0.34 | −2.26 | 0.06 | 3.65 | −1.71 | 0.50 | 1.16 | 106.7 | 76.1 | 1.4 | 1.1 |
| H1-Z1 | 10.36 | −0.36 | −2.23 | 0.18 | 4.00 | −1.42 | 0.67 | 1.15 | 106.6 | 75.8 | 1.4 | 1.1 |
| M1-H2 | 11.59 | −0.56 | −2.32 | 0.42 | 4.37 | −1.00 | 0.95 | 1.24 | 106.5 | 75.5 | 1.4 | 1.1 |

Note: this issue's footnote says "forward 1y swap rate" (no CME qualifier). Other tie-outs (close 4/28/17): 3m10y 69.6nv, 1m10y 63.4nv; Board/swaption FVM7 1.07, TYM7 1.05, USM7 0.93; FV 118.75/119.25 1x2 call spread now 1/1.5 ticks (8:30am 5/1/17); 2y 1s2s bull steepener costless strike spread 1.5bp.

---

## 5. US Rates Vol Lab: Vol cycle, steepeners, and SOFR — Citi Research, 25 Mar 2019 (28pp; Bikbov & Williams)

File: `US_Rates_Vol_Lab_Vol_cycle_steepeners_and_SOFR.pdf.md`

Weekly Focus I: cyclical vol turn near (3m/5y5y Treasury curve +25bp, OIS −6bp; recession model 37–45%/12m); maintain long 3m30y & 6m30y straddles (both 50nv, 2pm 3/22/19); add calendar curve-cap steepener: **buy $1bn 1y 2s10s caps struck 40bp (ATM 27bp) vs sell $1bn 6m 5s30s caps struck 45bp (ATM 37bp), cost 2.7 cents (3pm 3/22/19)**; fwd vol computed as sqrt(2·(1y 2s10s vol)² − (6m 5s30s vol)²).

Weekly Focus II — **SOFR discounting transition hits swaptions**: single-step CCP transition to SOFR discounting (LCH H2-2020) transfers value in the uncleared swaption market. Grid of % premium change from EFFR→SOFR discounting (close ~3/22/19): 3m1y −0.03% ... 10y30y +0.88%, 20y30y +1.39%; FF/SOFR term structure negative short/positive long. Dealer impact: ~$175bn financial long-dated callables outstanding (95% zero-coupon accreters, wtd-avg 4NC30) ⇒ $366mn normal vega supply; 85% on dealer desks, 85% hedged with short European swaptions ⇒ ~$265mn short vega in 5y25y/10y20y/20y10y at 35/35/30 weights; repricing ≈ **−$100mn** at current FF/SOFR (−$260mn at Jan-2019 basis levels). 10y30y straddle impact 0.9% of premium now, 2.3% at Jan basis.

**ED CA table (Fig 64, close of 3/22/2019, vs CME swaps)** — "roughly fair to the model":

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M9-H0 | 0.03 | 0.01 | −0.50 | −0.93 | −0.02 | −1.04 | −1.09 | 0.05 | 36.7 | 64.5 | 0.6 | 0.6 |
| U9-M0 | 0.13 | 0.09 | −0.40 | −1.57 | 0.02 | −0.92 | −2.08 | 0.10 | 55.5 | 70.1 | 0.8 | 0.7 |
| Z9-U0 | 0.26 | 0.11 | −0.37 | −1.57 | 0.05 | −0.88 | −2.12 | 0.14 | 63.1 | 76.6 | 0.8 | 0.7 |
| H0-Z0 | 0.43 | 0.11 | −0.39 | −1.65 | 0.09 | −0.86 | −2.15 | 0.16 | 66.3 | 81.3 | 0.8 | 0.7 |
| M0-H1 | 0.61 | 0.11 | −0.46 | −1.79 | 0.10 | −0.94 | −2.14 | 0.18 | 67.2 | 84.0 | 0.8 | 0.7 |
| U0-M1 | 0.81 | 0.11 | −0.51 | −1.88 | 0.09 | −0.91 | −2.00 | 0.20 | 67.5 | 84.6 | 0.8 | 0.7 |
| Z0-U1 | 1.07 | 0.14 | −0.51 | −1.87 | 0.11 | −0.74 | −1.80 | 0.26 | 68.6 | 84.2 | 0.8 | 0.7 |
| H1-Z1 | 1.40 | 0.20 | −0.46 | −1.79 | 0.17 | −0.39 | −1.58 | 0.33 | 70.4 | 82.9 | 0.8 | 0.8 |
| M1-H2 | 1.79 | 0.24 | −0.47 | −1.73 | 0.24 | −0.18 | −1.41 | 0.39 | 72.0 | 81.3 | 0.9 | 0.8 |
| U1-M2 | 1.92 | 0.08 | −0.82 | −2.04 | 0.02 | −1.05 | −1.71 | 0.14 | 68.2 | 80.0 | 0.9 | 0.8 |
| Z1-U2 | 1.73 | −0.32 | −1.59 | −2.66 | −0.55 | −3.10 | −2.27 | −0.19 | 59.5 | 78.7 | 0.8 | 0.8 |
| H2-Z2 | 1.63 | −0.63 | −2.06 | −2.71 | −1.06 | −3.28 | −2.22 | −0.11 | 53.3 | 77.4 | 0.7 | 0.9 |
| M2-H3 | 1.65 | −1.01 | −2.40 | −2.75 | −1.44 | −3.10 | −2.18 | 0.03 | 50.1 | 76.0 | 0.7 | 0.9 |
| U2-M3 | 2.34 | −0.82 | −2.17 | −2.39 | −1.21 | −2.13 | −1.72 | 0.69 | 55.8 | 74.6 | 0.7 | 0.9 |
| Z2-U3 | 3.48 | −0.62 | −1.73 | −2.04 | −0.56 | −0.96 | −1.24 | 1.14 | 63.9 | 73.1 | 0.9 | 0.9 |
| H3-Z3 | 4.73 | −0.33 | −1.01 | −1.74 | 0.16 | 0.30 | −0.82 | 1.24 | 70.2 | 71.7 | 1.0 | 0.9 |
| M3-H4 | 5.84 | −0.17 | −0.71 | −1.65 | 0.69 | 0.90 | −0.56 | 1.11 | 73.8 | 70.2 | 1.1 | 1.0 |

Other tie-outs (close 3/22/19): 3m10y 54.9nv; 1y1y ~7nv rich macro-vol / 2.3nv PCA; 2s5s10s and 2s10s30s fly extremes discussion; 3m1y1y/9m2y fwd-vol switch (Sharpe 0.71); board/swaption US 0.89-0.92 (cheap).

---

## 6. US Rates Vol Lab: Long Live Formosa — Citi Research, 9 Jan 2017 (23pp; Bikbov & Williams)

File: `US_Rates_Vol_Lab_Long_Live_Formosa.pdf.md`

Weekly focus: Taiwanese FSC proposal for minimum 6y non-call on cap-exempt Formosas. Vega math: 30NC1 vs 30NC6 zero-coupon callable bp-vega ≈ $145K vs $270K per $100mn notional; projected net Formosa supply ~$35bn/yr, gross ~$38bn (Q2-17–Q2-18); new rule ⇒ +$31mn normal vega/yr total, +$46mn in 10y expiries ($25bn 10y10y straddle equivalents). Trade: buy 2y30y vs sell 2y10y straddles beta-weighted (1 vega : 0.8 vega, = $53mn 2y30y vs $100mn 2y10y).

**ED CA table (Fig 46, close of 1/6/2017)** — Blues ~4.3bp / ~3σ rich to model, blamed on post-FOMC ED shorts:

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H7-Z7 | 0.29 | 0.03 | 1.45 | 1.32 | 0.24 | 1.48 | 1.47 | 0.14 | 119.1 | 46.8 | 2.5 | 0.9 |
| M7-H8 | 0.56 | 0.03 | 1.62 | 1.11 | 0.45 | 1.67 | 1.19 | 0.27 | 121.4 | 50.3 | 2.4 | 1.0 |
| U7-M8 | 0.91 | 0.01 | 1.68 | 0.79 | 0.68 | 1.75 | 0.75 | 0.34 | 120.9 | 55.5 | 2.2 | 1.0 |
| Z7-U8 | 1.29 | −0.02 | 1.59 | 0.47 | 0.89 | 1.53 | 0.26 | 0.38 | 118.3 | 60.6 | 2.0 | 1.0 |
| H8-Z8 | 1.73 | −0.08 | 1.44 | 0.20 | 1.09 | 0.98 | −0.21 | 0.45 | 116.3 | 66.5 | 1.7 | 1.0 |
| M8-H9 | 2.28 | −0.16 | 1.35 | 0.14 | 1.31 | 0.53 | −0.44 | 0.55 | 115.7 | 71.5 | 1.6 | 1.0 |
| U8-M9 | 3.02 | −0.21 | 1.43 | 0.38 | 1.62 | 0.55 | −0.25 | 0.73 | 117.3 | 76.4 | 1.5 | 1.0 |
| Z8-U9 | 4.02 | −0.21 | 1.65 | 0.94 | 2.08 | 0.88 | 0.37 | 1.00 | 121.1 | 81.0 | 1.5 | 1.0 |
| H9-Z9 | 5.19 | −0.12 | 1.82 | 1.55 | 2.57 | 1.17 | 1.00 | 1.17 | 124.5 | 85.2 | 1.5 | 1.0 |
| M9-H0 | 6.39 | 0.02 | 2.10 | 2.65 | 3.00 | 1.48 | 2.01 | 1.19 | 126.0 | 88.8 | 1.4 | 1.0 |
| U9-M0 | 7.76 | 0.30 | 2.43 | 3.99 | 3.56 | 2.23 | 2.83 | 1.37 | 127.7 | 91.6 | 1.4 | 1.0 |
| Z9-U0 | 8.94 | 0.67 | 2.57 | 4.20 | 3.89 | 2.73 | 2.83 | 1.18 | 126.8 | 93.4 | 1.4 | 1.0 |
| H0-Z0 | 10.20 | 1.07 | 2.74 | 4.17 | 4.31 | 3.15 | 2.81 | 1.27 | 126.1 | 94.2 | 1.3 | 1.0 |
| M0-H1 | 11.23 | 1.41 | 2.77 | 4.00 | 4.47 | 3.42 | 2.60 | 1.03 | 123.7 | 94.6 | 1.3 | 1.0 |
| U0-M1 | 11.90 | 1.53 | 2.68 | 3.70 | 4.25 | 3.30 | 2.14 | 0.67 | 119.6 | 94.4 | 1.3 | 1.0 |
| Z0-U1 | 12.58 | 1.46 | 2.50 | 3.53 | 4.04 | 3.04 | 1.84 | 0.68 | 115.9 | 94.3 | 1.2 | 1.0 |
| H1-Z1 | 13.29 | 1.20 | 2.28 | 3.45 | 3.87 | 3.08 | 1.84 | 0.71 | 112.6 | 94.0 | 1.2 | 1.0 |

Other tie-outs (close 1/6/17): 3m10y 82.9nv, 1y10y 85.5nv; conditional 3m 1y5y bear-steepener imp beta 0.83 / rlzd 0.99; 3y 10s30s bear steepeners recommended.

---

## 7. US Rates Vol Lab: Year-Ahead: Bumpy road for vol — Citi Research, 12 Dec 2016 (24pp; Bikbov & Williams)

File: `US_Rates_Vol_Lab_Year_Ahead_Bumpy_road_for_vol.pdf.md`

2017 vol outlook: 3m10y projected to average 85–90nv H1-17 / 70–75nv H2-17 (2016 avg ≈76); fair value of 3m10y from rates+2s10s model ≈80bp (market ~6nv rich). Short-gamma predictability: corr(3m/1y3m OIS curve, next-3m short-gamma return) ≈ +35%. Skews to flatten by H2-17; peak MBS convexity ~100bp lower in rates.

**ED CA table (Fig 48, close of 12/9/2016)** — "Golds convexity looks especially rich to the model (3bp or one sigma)":

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Z6-U7 | 0.03 | −0.01 | −1.66 | −2.35 | 0.01 | −1.67 | −2.15 | 0.08 | 51.1 | 31.6 | 1.6 | 1.1 |
| H7-Z7 | 0.20 | −0.02 | −1.45 | −1.87 | 0.14 | −1.42 | −1.63 | 0.17 | 88.9 | 36.7 | 2.4 | 1.1 |
| M7-H8 | 0.49 | −0.03 | −1.12 | −1.45 | 0.37 | −1.04 | −1.16 | 0.29 | 104.9 | 42.0 | 2.5 | 1.1 |
| U7-M8 | 0.87 | −0.04 | −0.85 | −1.36 | 0.62 | −0.79 | −1.10 | 0.38 | 111.0 | 47.4 | 2.3 | 1.2 |
| Z7-U8 | 1.28 | −0.03 | −0.80 | −1.31 | 0.85 | −0.86 | −1.16 | 0.41 | 112.0 | 53.0 | 2.1 | 1.1 |
| H8-Z8 | 1.71 | −0.01 | −0.93 | −1.38 | 1.01 | −1.11 | −1.41 | 0.43 | 110.4 | 58.7 | 1.9 | 1.1 |
| M8-H9 | 2.16 | 0.01 | −1.07 | −1.49 | 1.10 | −1.29 | −1.75 | 0.45 | 108.2 | 64.2 | 1.7 | 1.1 |
| U8-M9 | 2.64 | 0.03 | −1.16 | −1.63 | 1.12 | −1.40 | −2.18 | 0.48 | 106.0 | 69.2 | 1.5 | 1.1 |
| Z8-U9 | 3.17 | 0.05 | −1.19 | −1.76 | 1.06 | −1.46 | −2.62 | 0.53 | 104.2 | 73.9 | 1.4 | 1.1 |
| H9-Z9 | 4.26 | 0.28 | −0.20 | −1.10 | 1.44 | −1.08 | −1.98 | 1.09 | 109.5 | 77.7 | 1.4 | 1.1 |
| M9-H0 | 5.22 | 0.46 | 1.11 | −0.28 | 1.63 | −0.70 | −0.97 | 0.96 | 110.9 | 80.7 | 1.4 | 1.1 |
| U9-M0 | 6.26 | 0.62 | 2.10 | 0.71 | 1.84 | −0.25 | −0.15 | 1.04 | 111.9 | 83.0 | 1.3 | 1.1 |
| Z9-U0 | 7.31 | 0.72 | 2.28 | 1.11 | 2.03 | 0.07 | 0.26 | 1.05 | 112.1 | 84.3 | 1.3 | 1.1 |
| H0-Z0 | 8.35 | 0.64 | 2.19 | 1.24 | 2.19 | 0.08 | 0.40 | 1.03 | 111.7 | 85.2 | 1.3 | 1.1 |
| M0-H1 | 9.60 | 0.59 | 2.25 | 1.57 | 2.53 | 0.12 | 0.61 | 1.25 | 112.1 | 85.6 | 1.3 | 1.1 |
| U0-M1 | 10.79 | 0.56 | 2.29 | 1.91 | 2.80 | 0.17 | 0.78 | 1.19 | 111.8 | 85.9 | 1.3 | 1.1 |
| Z0-U1 | 11.86 | 0.61 | 2.34 | 2.24 | 2.92 | 0.41 | 1.01 | 1.07 | 110.5 | 86.0 | 1.3 | 1.1 |

Other tie-outs (close 12/9/16): 3m10y 86.3nv, 1m10y 82.6nv; 5y10y/10y10y ratio 2σ high; costless 3m 10s20s30s payer flies recommended.

---

## 8. Rates Vol Lab: Forward steepener and vol divergence — Citi Research VIEWPOINT, 12 Jun 2023 (35pp; Chang, Williams, Appeddu)

File: `Rates_Vol_Lab_Forward_steepener_and_vol_divergence (1).pdf.md`

**The SOFR-era CA note.** Prefer selling vol on bounce; express structural short-vol via (1) long-dated forward steepeners and (2) **shorting Blues CA via long SOFR futures vs pay in swaps** ("Rates Vol Lab - Short Blues convexity via futures/swaps" maintained). Blues CA "could continue to compress towards our model fair value, which is currently **about 5bps lower**." Vol-curve link: 2y30y vol vs (20y5y − 10y10y) rate spread moved inversely over past year until a recent divergence (long-dated fwd steepeners = net short convexity, so flat fwd curve ⇔ high vol).

**Forward-steepener carry screen (close 06/08/23, USD):**

| metric | 10y10y/15y15y | 10y10y/20y5y | 10y10y/20y10y | 10y10y/20y15y | 10y10y/25y5y | 10y10y/25y10y | 15y5y/20y5y | 15y5y/20y10y | 15y5y/20y15y | 15y5y/25y10y |
|---|---|---|---|---|---|---|---|---|---|---|
| curve, bp | −51.5 | −62.4 | −76.1 | −89.4 | −91.5 | −105.6 | −50.9 | −64.5 | −77.9 | −94.1 |
| 3y ZS | −0.91 | −0.91 | −0.96 | −1.00 | −1.01 | −1.04 | −0.98 | −1.03 | −1.06 | −1.11 |
| ZS since 2000 | −2.07 | −1.47 | −1.96 | −2.34 | −2.28 | −2.56 | −1.30 | −1.87 | −2.31 | −2.58 |
| 1y carry, bp | 6.89 | 10.31 | 8.31 | 7.71 | 5.95 | 6.04 | 5.93 | 3.93 | 3.33 | 1.66 |
| daily BE, bp | 6.18 | 7.22 | 5.71 | 4.99 | 4.29 | 3.97 | 6.77 | 4.59 | 3.71 | 2.29 |
| 1y realized vol, bp | 5.30 | 5.24 | 5.11 | 4.85 | 4.98 | 4.66 | 5.24 | 5.11 | 4.85 | 4.66 |
| BE/realized vol | 1.17 | 1.38 | 1.12 | 1.03 | 0.86 | 0.85 | 1.29 | 0.90 | 0.77 | 0.49 |

Efficient frontier: 10y10y/15y15y and 10y10y/20y5y (BE/RV meaningfully > 1).

**SOFR CA table (Fig 58, close 6/9/2023, vs CME swaps)** — first table with SR3 pack codes. This table (unlike the 2016-20 issues) prints both the Ho-Lee **model level** and the CA−model spread:

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | Model bp | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M4-H5 | 4.03 | 1.23 | 0.78 | 0.45 | 2.94 | 1.09 | 0.92 | 0.54 | 0.88 | 199.5 | 229.7 | 0.9 | 0.7 |
| U4-M5 | 4.41 | 0.98 | 0.79 | 0.27 | 3.79 | 0.62 | 0.98 | 0.43 | 0.38 | 178.1 | 201.4 | 0.9 | 0.8 |
| Z4-U5 | 5.16 | 0.71 | 0.63 | 0.19 | 4.66 | 0.49 | 0.93 | 0.42 | 0.74 | 167.7 | 180.3 | 0.9 | 0.8 |
| H5-Z5 | 6.10 | 0.29 | 0.40 | 0.24 | 5.53 | 0.58 | 0.83 | 0.55 | 0.95 | 161.6 | 166.3 | 1.0 | 0.9 |
| M5-H6 | 8.24 | −0.40 | −0.52 | 0.21 | 6.36 | 1.88 | 0.05 | 0.51 | 2.14 | 168.5 | 156.4 | 1.1 | 0.9 |
| U5-M6 | 9.77 | −1.22 | −0.73 | 0.36 | 7.16 | 2.60 | 0.06 | 0.82 | 1.52 | 166.3 | 148.8 | 1.1 | 0.9 |
| Z5-U6 | 11.70 | −1.89 | −0.82 | 0.55 | 8.02 | 3.67 | 0.13 | 1.10 | 1.93 | 166.5 | 142.2 | 1.2 | 0.9 |
| H6-Z6 | 13.70 | −2.37 | −0.80 | 0.70 | 8.96 | 4.74 | 0.22 | 1.25 | 2.00 | 166.0 | 136.1 | 1.2 | 0.9 |
| M6-H7 | 15.40 | −3.08 | −0.96 | 0.73 | 9.98 | 5.42 | −0.07 | 1.18 | 1.70 | 163.1 | 130.9 | 1.2 | 1.0 |
| U6-M7 | 16.84 | −2.97 | −1.30 | 0.63 | 11.10 | 5.74 | −0.42 | 1.05 | 1.44 | 159.0 | 126.2 | 1.3 | 1.0 |
| Z6-U7 | 18.27 | −2.72 | −1.55 | 0.47 | 12.23 | 6.04 | −0.77 | 0.90 | 1.43 | 155.1 | 121.9 | 1.3 | 1.0 |
| H7-Z7 | 20.08 | −2.33 | −1.54 | 0.40 | 13.37 | 6.71 | −0.88 | 0.82 | 1.81 | 152.8 | 118.0 | 1.3 | 1.0 |
| M7-H8 | 22.29 | −1.78 | −1.35 | 0.45 | 14.50 | 7.79 | −0.69 | 0.90 | 2.21 | 151.9 | 113.8 | 1.3 | 1.0 |

Column parse of the merged markdown cells verified two ways: the identity CA − Model = VsModel holds row-by-row to ±0.01 (e.g. 4.03−2.94=1.09; 13.70−8.96=4.74; 22.29−14.50=7.79), and the body text's "Blues CA... model fair value... about 5bps lower" matches the Blues rows (H6-Z6 +4.74 / M6-H7 +5.42) under this parse. Same identity holds in the unambiguous 2021 template (5.88−3.82=2.06).

Other tie-outs (close 6/9/23): 3m10y spot vol 143.0nv → 1y fwd 122.6nv (1y2y col: spot 143.0, 1y fwd 122.6); the fwd-vol table spot row: 1y2y 143.0, 1y5y 121.8, 1y10y 103.8, 1y30y 83.2nv; 1y5y/1y30y and vol-slope commentary; conditional-curve tables (3m 2y10y spot curve −102.3bp etc.).

---

## 9. Rates Vol Lab: In search of cheap vol — Citi Research, 17 Jan 2020 (35pp; Bikbov & Williams)

File: `Rates_Vol_Lab_In_search_of_cheap_vol.pdf.md`

Weekly focus: Formosa supply $5.3bn Jan-to-date (~$16mn normal vega swapped, highest since Jan-2018); keep 10y20y/5y30y straddle switch (10y20y 54.6nv / 5y30y 56.6nv, 1pm 1/17/20); buy $30mn USDJPY 108/105 put spreads vs sell $50mn 6m10y ATMF+45bp (2.2%) payers, net cost $35K (USDJPY 110.17, 12pm 1/17/20; regression USDJPY = 0.0266·(US-JP 10y diff) + 103.48, R² 0.32, 2018-19 sample). **Initiate GBP 15y10y/25y10y delta-hedged flatteners: 50K DV01 at −11.2bp (12pm 1/17/2020), hedged at each 25bp move in the 25y10y rate; carry +0.5bp/1y — "an effectively free convexity buy."** (Closed 26 Mar 2020, doc 14.)

Multi-currency flattener screen (Fig 11, close ~1/16/20): USD 15y5y/20y10y curve −13.65bp, 1y carry −2.20bp, BE/RV 0.80; GBP 15y10y/25y10y curve −10.37bp, 1y carry +0.52bp, BE/RV 0.00 (consistent with the body text "carries positively by about 0.5bp over 1y"); full USD/EUR/GBP/CAD grids in source.

**ED CA table (Fig 62, close of 1/16/2020, vs CME swaps)** — CAs tightened toward fair in Blues/Golds:

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H0-Z0 | −0.02 | 0.04 | −0.20 | −0.64 | −0.06 | 0.14 | −0.49 | 0.01 | 37.2 | 55.9 | 0.7 | 0.7 |
| M0-H1 | 0.01 | 0.05 | −0.49 | −1.46 | −0.07 | −0.23 | −0.71 | 0.03 | n/a | 59.5 | n/a | 0.7 |
| U0-M1 | 0.08 | 0.05 | −0.65 | −1.51 | −0.07 | −0.36 | −0.65 | 0.07 | n/a | 64.7 | n/a | 0.7 |
| Z0-U1 | 0.21 | 0.06 | −0.71 | −1.40 | −0.05 | −0.37 | −0.48 | 0.13 | 48.9 | 69.5 | 0.7 | 0.7 |
| H1-Z1 | 0.44 | 0.07 | −0.54 | −0.88 | 0.02 | −0.08 | −0.02 | 0.23 | 59.8 | 73.2 | 0.8 | 0.7 |
| M1-H2 | 0.76 | 0.08 | −0.15 | −0.19 | 0.14 | 0.57 | 0.51 | 0.32 | 68.1 | 76.1 | 0.9 | 0.8 |
| U1-M2 | 1.12 | 0.09 | 0.34 | 0.28 | 0.26 | 1.33 | 0.79 | 0.36 | 72.8 | 78.6 | 0.9 | 0.8 |
| Z1-U2 | 1.53 | 0.09 | 0.87 | 0.58 | 0.40 | 1.88 | 0.95 | 0.41 | 75.7 | 79.8 | 0.9 | 0.8 |
| H2-Z2 | 1.93 | 0.10 | 1.05 | 0.63 | 0.49 | 2.05 | 0.94 | 0.40 | 76.7 | 80.6 | 1.0 | 0.8 |
| M2-H3 | 2.28 | 0.12 | −0.43 | 0.18 | 0.51 | −0.21 | 0.47 | 0.34 | 75.9 | 80.9 | 0.9 | 0.8 |
| U2-M3 | 2.85 | 0.02 | −0.21 | 0.20 | 0.71 | −0.12 | 0.39 | 0.57 | 78.0 | 81.3 | 1.0 | 0.8 |
| Z2-U3 | 3.23 | −0.12 | −0.94 | −0.06 | 0.69 | −0.90 | 0.09 | 0.38 | 76.8 | 81.4 | 0.9 | 0.8 |
| H3-Z3 | 3.79 | −0.18 | −0.85 | −0.07 | 0.82 | −0.84 | 0.04 | 0.56 | 77.3 | 81.4 | 0.9 | 0.8 |
| M3-H4 | 4.25 | −0.26 | −0.78 | −0.11 | 0.80 | −0.81 | −0.02 | 0.46 | 76.5 | 81.4 | 0.9 | 0.8 |
| U3-M4 | 4.54 | −0.29 | −0.89 | −0.34 | 0.59 | −0.91 | −0.22 | 0.29 | 74.1 | 81.3 | 0.9 | 0.8 |
| Z3-U4 | 5.08 | −0.31 | −0.61 | −0.38 | 0.61 | −0.67 | −0.23 | 0.54 | 73.9 | 81.3 | 0.9 | 0.8 |
| H4-Z4 | 5.58 | −0.39 | −0.55 | −0.54 | 0.56 | −0.63 | −0.33 | 0.50 | 73.2 | 81.6 | 0.9 | 0.8 |

Also: 3y 5s30s conditional bear steepener zero-cost strike spread ~14bp (3pm 1/16/20); still like selling 6m10y payers on 6m 2s10s30s payer flies.

---

## 10. Rates Vol Lab: Left-side vols' outperformance — Citi Research VIEWPOINT, 22 Jun 2021 (42pp; Chang, Williams, Appeddu)

File: `Rates_Vol_Lab_Left_side_vols_outperformance.pdf.md`

**The most complete CA-selling document in the corpus** (technical appendix in §0.3, positioning chart in §0.4, CME-vs-LCH rationale in §0.1).

Weekly focus: favor left-side vols vs 30y tails, 2013-taper analog (1y5y/1y30y vol ratio ~1 → target ~1.3). **Regressions verbatim:** 1y5y/1y30y vol ratio on 1m realized beta of 1y-fwd 5s30s curve to the 1y5y rate (since 2006): **y = −0.6146x + 0.9561, R² = 0.6246**. 6m regression of 5y2y vol on 5y2y forward rate: **y = 24.284x + 24.734, R² = 0.9057** ⇒ 5y2y vol 5.7nv too high (vol +2nv post-FOMC vs rate −9.5bp). Took profits on USD-vs-EUR 6m 10s30s floor switch: +1.9bp / $57K (8am 6/22/21).

**The CA trade (entry/target/stop — the only fully-specified CA trade in the corpus):**
- Sell CAs by **buying 1000 EDM4-H5 Blue pack contracts vs paying $1.01bn CME-cleared forward-starting swap (6/17/2024–6/16/2025) at 7.9bp rate spread** (noon 6/11/2021, $100K DV01). Spread since tightened to 5.9bp (this issue). Pack rolled to U4-M5.
- Carry: **+1.2bp running over 3 months**. **Target: 4bp of CA tightening. Stop: 3bp of widening.**
- Rationale: Blues/Golds CAs at multi-year highs while vol fell; CA-implied vols >100nv vs realized ~82-84nv and cap/floor implieds; Blues preferred over Golds for higher 3m roll and higher CA-implied vol; CA-implied/realized ratio for Blues at upper end of multi-year range. Risk: further build-up of duration shorts concentrated in EDs.

**ED CA table (Fig 13 = Fig 66, system-mid, close of 6/21/2021, CME FRA/swap curve):**

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | Model bp | Vs Model bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| U1-M2 | −0.05 | −0.01 | 1.43 | −0.83 | 0.01 | −0.07 | 0.68 | −0.94 | 0.00 | 49.0 | 14.9 | 3.3 | 1.4 |
| Z1-U2 | −0.05 | −0.02 | 1.21 | −0.91 | 0.04 | −0.08 | −0.07 | −1.20 | 0.01 | 33.7 | 19.6 | 1.7 | 1.4 |
| H2-Z2 | −0.01 | −0.04 | 1.28 | −0.79 | 0.09 | −0.10 | −0.32 | −1.37 | 0.04 | 13.2 | 26.9 | 0.5 | 1.2 |
| M2-H3 | −0.04 | −0.07 | −0.24 | −1.17 | 0.17 | −0.21 | −1.90 | −2.04 | −0.02 | 19.1 | 32.8 | 0.6 | 1.2 |
| U2-M3 | −0.12 | −0.11 | −1.11 | −1.58 | 0.33 | −0.45 | −2.18 | −2.62 | −0.08 | 29.9 | 42.1 | 0.7 | 1.1 |
| Z2-U3 | 0.18 | −0.11 | 0.50 | −0.08 | 0.56 | −0.38 | −0.92 | −1.62 | 0.30 | 31.6 | 55.8 | 0.6 | 0.9 |
| H3-Z3 | 0.65 | −0.12 | 1.29 | 1.35 | 0.88 | −0.23 | 0.03 | −0.67 | 0.48 | 53.5 | 62.1 | 0.9 | 0.9 |
| M3-H4 | 1.43 | −0.10 | 1.68 | 2.78 | 1.32 | 0.11 | 0.69 | 0.51 | 0.78 | 70.8 | 68.3 | 1.0 | 0.9 |
| U3-M4 | 2.54 | −0.07 | 1.88 | 3.07 | 1.88 | 0.66 | 1.10 | 1.45 | 1.11 | 85.4 | 73.7 | 1.2 | 1.0 |
| Z3-U4 | 3.62 | 0.10 | 1.69 | 2.88 | 2.50 | 1.12 | 1.07 | 1.75 | 1.08 | 93.2 | 76.5 | 1.2 | 1.0 |
| H4-Z4 | 4.90 | 0.17 | 1.25 | 2.45 | 3.15 | 1.75 | 0.78 | 1.74 | 1.28 | 99.9 | 80.2 | 1.2 | 1.0 |
| M4-H5 | 5.88 | −0.15 | 0.56 | 1.95 | 3.82 | 2.06 | 0.22 | 1.39 | 0.98 | 101.4 | 82.3 | 1.2 | 1.0 |
| U4-M5 | 6.97 | −0.07 | 0.30 | 1.77 | 4.47 | 2.50 | 0.04 | 1.35 | 1.09 | 102.8 | 84.2 | 1.2 | 0.9 |
| Z4-U5 | 7.94 | −0.27 | 0.04 | 1.61 | 5.15 | 2.79 | −0.18 | 1.22 | 0.96 | 102.7 | 85.3 | 1.2 | 0.9 |
| H5-Z5 | 8.90 | −0.29 | 0.12 | 1.66 | 5.85 | 3.05 | −0.06 | 1.37 | 0.96 | 102.2 | 86.2 | 1.2 | 0.9 |
| M5-H6 | 9.57 | −0.58 | 0.05 | 1.64 | 6.57 | 2.99 | −0.10 | 1.36 | 0.67 | 99.9 | 86.6 | 1.2 | 0.9 |
| U5-M6 | 9.94 | −0.99 | 0.01 | 1.64 | 7.30 | 2.63 | −0.08 | 1.27 | 0.37 | 96.4 | 86.5 | 1.1 | 0.9 |

(Column layout in this 2021 table explicitly separates "Model" and "Vs Model" — this is the template used to interpret the merged 2023 table in doc 8. Tie-out: **Blues M4-H5 CA 5.88bp, Ho-Lee model 3.82bp, CA−model +2.06bp, CA-implied vol 101.4nv vs 3m realized 82.3nv, close 6/21/2021**.)

Also: vol-carry heatmap (6m fixed-strike straddle carry: 1y1y −3.1nv ... 1y30y +2.3nv); PnL profile chart of short 1 EDH5 vs long FRA under instantaneous shifts (−60..+70bp, $ range 0–5,000).

---

## 11. Rates Vol Lab: Liquidity, vega, and convexity — Citi Research, 30 Mar 2020 (36pp; Bikbov & Williams)

File: `Rates_Vol_Lab_Liquidity_vega_and_convexity.pdf.md`

COVID-era issue. Sell 2y2y USD straddles (55nv, 2pm 3/27/20) for ZLB/forward-guidance/YCC; bought 10y10y USD vs EUR straddles (USD 59nv vs EUR 57.4nv, 9:30am 3/27/20); 1m10y at 103nv; 10y swap mid-to-bid ~0.6bp. **15y5y/20y10y USD flattener flagged as watch-list "free convexity buy": curve −5.21bp (3pm 3/26/2020), slightly positive carry (+0.11bp/1y), BE/RV 0.00; 1y ZS +4.21, 3y ZS +3.58** — steepened to upper bound of range on VA receiving in 20y. USD flattener screen (3/26/20): 10y10y/15y15y −5.07bp (1y carry −0.28, BE 1.21, RV 6.47, BE/RV 0.19); full USD/EUR/GBP grid in source.

**ED CA table (Fig 60, close of 3/27/2020, vs CME swaps)** — Blues/Golds richened on profit-taking of longs; note 1wk changes of +4-5bp (COVID vol):

| Pack | CA bp | 1wk chg | 3m ZS | 1y ZS | VsModel bp | VsM 3m ZS | VsM 1y ZS | 3m roll | Impl | Rlzd | I/R | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M0-H1 | 0.03 | 0.00 | 1.64 | 0.10 | −0.03 | 1.88 | 0.86 | 0.03 | 34.1 | 93.6 | 0.4 | 0.4 |
| U0-M1 | 0.10 | 0.00 | 2.06 | 0.15 | 0.02 | 2.54 | 1.39 | 0.07 | 50.0 | 78.3 | n/a | 0.5 |
| Z0-U1 | 0.20 | 0.01 | 2.15 | −0.02 | 0.07 | 2.44 | 1.41 | 0.10 | 55.6 | 80.0 | n/a | 0.5 |
| H1-Z1 | 0.38 | 0.04 | 2.41 | 0.22 | 0.18 | 2.40 | 1.76 | 0.18 | 63.6 | 84.2 | 0.8 | 0.5 |
| M1-H2 | 0.64 | 0.08 | 2.48 | 0.55 | 0.31 | 2.29 | 1.97 | 0.25 | 69.7 | 88.3 | 0.8 | 0.5 |
| U1-M2 | 0.97 | 0.12 | 2.38 | 0.94 | 0.48 | 2.17 | 2.06 | 0.33 | 74.5 | 93.2 | 0.8 | 0.5 |
| Z1-U2 | 1.37 | 0.17 | 2.19 | 1.27 | 0.69 | 2.07 | 2.10 | 0.40 | 78.1 | 98.2 | 0.8 | 0.5 |
| H2-Z2 | 1.78 | 0.20 | 1.91 | 1.32 | 0.88 | 1.89 | 2.01 | 0.41 | 79.5 | 103.0 | 0.8 | 0.5 |
| M2-H3 | 2.02 | 0.27 | 1.17 | 0.85 | 0.88 | 1.42 | 1.61 | 0.24 | 76.8 | 106.7 | 0.7 | 0.5 |
| U2-M3 | 2.54 | 1.03 | 2.11 | 0.76 | 1.11 | 2.22 | 1.58 | 0.52 | 78.6 | 110.1 | 0.7 | 0.5 |
| Z2-U3 | 3.07 | 2.39 | 1.08 | 0.53 | 1.34 | 1.55 | 1.17 | 0.54 | 79.5 | 113.0 | 0.7 | 0.5 |
| H3-Z3 | 3.92 | 3.91 | 1.23 | 0.67 | 1.83 | 1.54 | 1.15 | 0.85 | 83.2 | 115.6 | 0.7 | 0.5 |
| M3-H4 | 4.72 | 4.90 | 1.16 | 0.67 | 2.23 | 1.39 | 1.03 | 0.80 | 84.9 | 118.3 | 0.7 | 0.5 |
| U3-M4 | 5.24 | 4.89 | 1.11 | 0.64 | 2.32 | 1.31 | 0.97 | 0.52 | 83.6 | 121.1 | 0.7 | 0.5 |
| Z3-U4 | 5.96 | 4.28 | 1.36 | 0.78 | 2.56 | 1.53 | 1.10 | 0.72 | 83.8 | 124.4 | 0.7 | 0.5 |
| H4-Z4 | 6.53 | 3.72 | 1.49 | 0.86 | 2.63 | 1.61 | 1.19 | 0.58 | 82.8 | 127.8 | 0.6 | 0.5 |
| M4-H5 | 7.25 | 4.04 | 1.75 | 1.13 | 2.79 | 1.78 | 1.46 | 0.72 | 82.5 | 131.3 | 0.6 | 0.5 |

---

## 12. Alert: Reweighting delta-hedged 15y5y/20y10y flatteners — Citi North America Rates Trade Idea, 16 Oct 2019 (6pp; Bikbov)

File: `20y10y_flatteners (1).pdf.md`

Trade-management alert for the doc-1 trade (initiation dated here "5/10/2019"; the Dec alert says "5/9/2019" — record both as printed). $50K DV01 15y5y/20y10y USD flatteners, **delta-hedged at each 20bp move in the 20y10y rate** (vs 25bp in the Vol Lab backtest — note the discrepancy). Current MTM +$105K; curve steepened ~2bp since initiation but elevated realized vol carried the P&L. "Current nationals are $149.5mn and $81.97 for 15y5y and 25y10y" (as printed; '25y10y' is evidently a typo for 20y10y, and $81.97 lacks "mn"). Curve developed rate-directionality (steepening in rallies) from insurance flows ⇒ **reweight using empirical beta 1.025 between 15y5y and 20y10y: increase 20y10y notional $81.97mn → $84mn, keep hedging every 20bp scaling DV01-neutral notional by 1.025.** Pricing 11:30am ET 10/16/2019. Rest of file is disclosures.

---

## 13. Alert: Taking profits on delta-hedged 15y5y/20y10y flatteners — Citi North America Rates Trade Idea, 5 Dec 2019 (6pp; Bikbov)

File: `20y10y_flatteners.pdf.md` — distinct document from #12 (close-out vs reweight), not a duplicate.

Entered 5/9/2019 at **−11.8bp**, $50K DV01, hedged each 20bp. Close: curve −12.5bp mid (2pm 12/5/2019), P&L ≈ +$187K at mid, **booked +$155K net transaction costs** (so ~$32K ≈ round-trip cost on $50K DV01 — an implied all-in cost datapoint). Exit trigger: carry deteriorated to ~−2bp/yr; BE/realized-vol rose to 0.8. Includes the USD/GBP flattener screen close of 12/4/2019: USD 15y5y/20y10y curve −12.54bp, 1y carry −2.09bp, BE 3.33bp, 1y RV 4.16bp, BE/RV 0.80; GBP 15y10y/25y5y flagged (positive carry +0.21bp, BE/RV 0.00) and added to watch list.

**Complete 15y5y/20y10y trade lifecycle for replication:** entry 5/9/2019 @ −11.8bp → reweight 10/16/2019 (beta 1.025) → exit 12/5/2019 @ −12.5bp; gross +$187K, net +$155K on $50K DV01 over ~7 months, with the curve nearly unchanged — P&L ≈ pure realized convexity minus roll minus costs. This is a direct known-answer test for a delta-hedged-flattener backtest engine.

---

## 14. Alert: Taking profits on GBP 15y10y/25y10y flatteners — Citi North America Rates Trade Idea, 26 Mar 2020 (6pp; Bikbov)

File: `25y10y_flatteners.pdf.md`

Close-out of the doc-9 trade: entered Jan 2020 (50K DV01 GBP 15y10y/25y10y at −11.2bp, hedged each 25bp move in 25y10y). Closed for **profit of GBP 445K net transaction costs — decomposed ~115K curve move + ~330K convexity** (pricing 2pm 3/26/2020). Exit rationale: BoE QE flattened the curve; risk of re-steepening on supply. Second full trade lifecycle tie-out (2.5 months; convexity P&L 3× curve P&L in the COVID vol spike).

---

## Synthesis for the ARBS convexity-RV build

1. **CA tie-out ladder (Blues-area pack, CA level / vs-model, all vs matched 1y fwd swap):** 12/9/16: Z9-U0 7.31bp (+2.03); 1/6/17: H0-Z0 10.20bp (+4.31, ~3σ); 4/28/17: H0-Z0 6.76bp (+3.27, short-Blues trade live); 3/9/18: H1-Z1 6.00bp (+2.48); 1/11/19: H2-Z2 4.22bp (−0.12, "fair"); 3/22/19: H2-Z2 1.63bp (−1.06); 5/8/19: H2-Z2 2.12bp (−0.35, "Blues cheap"); 1/16/20: H2-Z2 1.93bp (+0.49); 3/27/20: H3-Z3 3.92bp (+1.83); 6/21/21: M4-H5 5.88bp (+2.06, model 3.82, entry 7.9bp spread on the live trade); 6/9/23 (SOFR): Blues H6-Z6 13.70bp (model 8.96, +4.74). A backtest CA series should reproduce these to within quoting noise **provided the swap leg is CME-cleared** post-2019.
2. **Citi's CA fair value is vol, not fly**: Ho-Lee on cap/floor vols, CA≈σ²T²/2. The fly enters Citi's framework only implicitly — via the "long-dated forward curve ⇄ vol" inverse relationship (10y10y/20y10y vs 2y10y vol regression, doc 1; 2y30y vol vs 20y5y−10y10y spread, doc 8). A CA-vs-fly regression is an ARBS construction to be validated, not a Citi citation from this corpus.
3. **The two symmetric franchises**: short CA (futures vs CME swap; short vol, positive roll, target/stop in bp of CA) and long delta-hedged flattener (swap curve; long vol, negative roll, BE/RV entry gate ≤~0.8, exit ≥~0.8–1.0 as carry decays). Same Ho-Lee/breakeven algebra prices both; Citi flips between them depending on whether CA-implied (or BE) vol is above or below realized.
4. **Positioning conditioning**: CFTC AM+LF net %OI (inverted) vs Blues CA−model is the published conditioning variable (doc 10, Fig 12) — matches the parent's TFF-conditioned variation.
5. **CME-LCH**: no LCH CA is ever published; the CME choice is justified by futures/swap margin netting (portfolio-margining capital efficiency), i.e. the CA and the CME-LCH basis are entangled at the swap leg. Building CA vs both CCP curves and differencing them recovers the clearing-basis term structure at the pack maturities.
6. **Costs for backtests**: swaps 0.3bp (2017+) scaling up to 1.6-2bp in the 1990s (doc 2 table); flattener initiation 0.75-1bp / hedge-roll 0.3-0.4bp one-way (doc 1); realized all-in drag on the 2019 flattener ≈ $32K per $50K-DV01 round trip incl. ~7 months of hedging.
7. **Data-quality flags**: 6/9/23 CA table's merged markdown columns were disambiguated via the CA−Model=VsModel identity (§8); doc-12 notional typo ("$81.97", "25y10y"); initiation-date 5/9 vs 5/10 discrepancy; hedge threshold 20bp (alerts) vs 25bp (backtest/GBP trade); Citi fly quotes are −0.5/1/−0.5 (half of ARBS's 2·belly−front−back).
