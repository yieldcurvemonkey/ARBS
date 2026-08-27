# Convexity RV — The Complete Breakdown

**Corpus:** `convexityrv` (154 files), `basisvsvolrv` (44 files), `nordea_rv` (9 files) + markdown conversions.
**Prepared:** 2026-08-25, for formalizing a convexity relative-value framework for a USD swaps (linear) trader.
**Reading key:** two layers are kept editorially separate throughout — **what the banks published** (catalog, attributed by bank/report/date) and **what ARBS measured** (verdicts from our own backtests, used as constraints). Bank numbers are quoted as published; ARBS numbers are marked as ours.

---

# PART I — THE FRAMEWORK: one risk, five wrappers, one ledger

## 1.1 The single idea underneath every report in the corpus

Every document in these three directories is about the same object: **somebody is long a payoff that is convex in rates, somebody else is short it, and the market charges a running rent (theta / carry / rolldown) for holding the convex side.** The RV question is always the same pair:

1. **Price of gamma:** what daily move in rates does the rent imply as breakeven? (the *implied vol of the wrapper*)
2. **Vs. what the market delivers or charges elsewhere:** realized vol, or the implied vol of a different wrapper of the same risk.

The corpus contains **five linear-market wrappers of short-rate/long-rate variance** plus the option market itself:

| # | Wrapper | The convex object | Long-convexity side | Who publishes the franchise |
|---|---|---|---|---|
| 1 | **Ultra-long forward curve** (10y10y/20y10y, 30s/50s, 20Y/40Yx10Y) | DV01-neutral flattener = straddle-like payoff from convexity differential between tenors | Receive the longer leg (flattener) | JPM "An option by any other name" (2017), "Valuing convexity" (2018); Citi "Trading long-dated convexity" (2019) |
| 2 | **SOFR futures convexity adjustment** (packs/bundles/outrights vs matched IMM swap) | Cleared swap is convex + PAI-carrying; the future is linear and margined — CA = the financing-bias rent | Receive fixed vs short futures (long CA) | Citi Vol Lab CA screen 2016–2023; JPM "A better way to sell vol" (2017); Henrard/Rosen/CME for the model |
| 3 | **Curve butterflies** (5s10s30s, 2s5s10s, forward flies) | Belly-vs-wings curvature ≈ discrete second derivative of the curve in maturity space | Pay the belly (long curvature) | Citi fly RV tables; JPM EUR beta-stability (2021); Citi "Flying Too High" (2010) |
| 4 | **UST futures basis** (long CTD vs CF-weighted futures) | Net basis = the short's delivery option (switch + wildcard + timing) — an actual option, floored at 0 | Long basis = long the option | Burghardt-Belton (the book); JPM basis series 2018–2020; Citi "Summer lull" (2015); BofA "Buy futures basis = cheap options" (2025) |
| 5 | **Swap spreads / invoice spreads vs vol** | Spread directionality from convexity-hedger flow (MBS/banks/VA/Formosa) | Conditional; flow-driven | JPM IRD weeklies 2018–2020 |
| 6 | **The option market itself** (swaptions, SOFR options, UST futures options) | Explicit gamma/vega | Long options | Citi Vol Lab surface toolkit; board-vs-swaption RV |

**The framework's central move: put all six on one axis — breakeven daily vol, in bp/day — and trade the cross-sectional dislocations.**

## 1.2 The gamma/theta ledger — the four numbers per position

Everything in the corpus reduces to four measurements per structure. This is the ledger:

### Γ$ — dollar gamma (per 1bp², parallel)
- **Definition:** ∂²V/∂y² per parallel shift of the relevant curve. For linear structures this comes from **repricing on a shifted curve**, never a closed form (ARBS: `GAMMA_01` raises NotImplementedError on the rateslib backend; measure by repricing — `payoff_profile(pricer, package, shifts_bp)`).
- Long-end flattener: convexity differential between legs; Attack68's ladder for a $1000/bp PV01 leg: 10Y $1.1, 10y10y $3.1, 20y10y $5.1, 30y10y $7.1, 40y10y $9.1 per bp² — **convexity per unit DV01 grows ∝ T** (ZCB: dv01 = −T·e^{−yT}, convexity = T²·e^{−yT}).
- SR3 CA package: gamma of the swap leg only (futures DV01 fixed at $25). CME worked example (Jun-2025): received-fixed 2y IMM swap vs 779 short SR3 → net P&L +$253 at ±10bp, +$22,292/+$21,226 at ∓100bp, matching (797−779)×½×100×$25 = $22,500 linear-approx — **gamma = the drift of the hedge ratio**.
- Basis: gamma of the delivery option — Citi Summer lull (Jul-2015): $100mm May37 basis had **$420/bp² of gamma for $130k premium vs $187k for the same gamma in a 1m25y swaption** (1.4×).
- Fly: second difference across maturity space, NOT vol gamma (see §1.5 warning).

### θ$ — theta / the rent (per year, converted to bp/day for comparison)
- **Composition — always decompose, never quote one number:** (a) **carry** = coupon/fixing spread vs funding (funding-spread form ≡ forward-minus-spot form per unit DV01 — dm63 identity); (b) **rolldown** = ageing on a static curve (the practitioner convention; forwards-realized is the zero-edge null); (c) **decay of the convex object itself** (CA theta: dCA/dt = −σ²·mean(T1)/1e4 per year — ARBS measured −0.24/−0.31/−0.37 bp/month on Greens/Blues/Golds, recovered by the quarterly roll jump at ratio 1.02–1.11; basis: the "daily drop in gross basis" = the CTD's daily carry; option: literal theta).
- **Convention traps (all measured in-house):** `CARRY_AND_ROLL_BPS_RUNNING` correlates **−0.136** with Citi's published 1y carry — a repriced `Curve.roll` of the aged package correlates **+0.991**. Horizon carry needs the accrual factor τ (the Nordea note omits it — literal transcription is 2× off). Forward-starting structures have **zero carry** at inception — their "carry" is pure static-curve roll.
- Roll clocks: SR3 rank maps roll ON the IMM date; IMM_k swap legs roll the business day BEFORE — 22 dates each 2021–26, zero coincide. A roll blackout must be the union.

### σ_BE — breakeven vol (bp/day), the universal axis
- **σ_BE = √(2·|θ_daily| / Γ)** — the daily parallel move at which convexity pays for the rent. This is the exact option identity δS_BE = √(2θ/Γ) = S·σ_i·√δt (Γ cancels from the hurdle: **size scales the P&L, not the hurdle**).
- JPM's "curve-implied vol": solve the normal terminal distribution width making a 1y-held flattener's expected payoff zero — same object at a 1y horizon.
- Citi's published version: "daily BE" = parallel shift whose convexity gain offsets daily roll; **defined ≡ 0 when carry ≥ 0** (truncation — 56% of 2023 truncated on the tight pairs; ARBS trades the continuous carry/(vol·√252) instead).
- **Units discipline: EVERYTHING in bp/day.** bp/yr vs bp/day is a silent √252 ≈ 15.9 that correlation checks cannot catch (measured in-house: a "spread" of ~100bp that was pure units). Guard: a SOFR-complex daily vol outside 0.5–40 bp/day is a wrong-unit series. The PM's meta-instruction says the same: "everything needs to be in terms of daily vol."

### σ_impl / σ_rlzd — the two vols to compare it against
- **σ_impl (model-inverted):** invert the wrapper's pricing model on the observed price. CA: Ho-Lee `CA_bp = 0.5·σ²·mean(T1²)·1e4` inverted → CA-implied normal vol (Citi's column). Basis: implied vol of the delivery option that reprices net basis. Curve: the JPM breakeven above.
- **σ_rlzd:** matched-window realized vol **of the same underlying** (3m realized of the pack rate; 1y realized of the longer forward rate; realized curve vol for the CTD switch), close-to-close, excluding IMM-roll-date returns; Citi also uses intraday (30m, 7am–4pm) vs close-to-close as separate columns and realized-by-time-of-day for hedging-time selection.
- **The P&L identity that links them (the whole corpus's algebra):** delta-hedged, hedged at implied,
  `dΠ = ½·Γ(σ_i)·S²·[(dS/S)² − σ_i²·dt]` (ex-post, exact) → `E[dΠ] = ½·Γ·S²·(σ_r² − σ_i²)·dt` (ex-ante, average) → `Σ P&L ≈ ν·(σ_r − σ_i)` only when σ_r ≈ σ_i (the vol-linear collapse; the exact wedge is (σ_r+σ_i)/2σ_i — the 100c/10c/30c phenomenon: at IV 2bp/day, RV 2.1 pays 10c but RV 2.2 pays 30c — **variance, not vol**).
  Citi writes the identical thing for the CA seller: `E[P&L] = E∫(T−t)·[σ²_impl(t) − σ²_rlzd(t)]dt` — **selling CA ≡ selling delta-hedged straddles**.

### The ledger row, per structure
```
structure | Γ$/bp² | θ$/day (carry, roll, decay, financing split) | σ_BE bp/day | σ_impl bp/day | σ_rlzd bp/day | σ_BE/σ_rlzd | vega$ (∂V/∂σ = σ·"T²-loading") | costs (entry, rehedge, per leg)
```
Rank the whole book on `σ_BE/σ_rlzd` (cheap gamma < 1 < rich gamma), then express each side in its cheapest wrapper. **Citi's own trigger levels:** enter delta-hedged flatteners (long gamma) at BE/RV ≤ ~0.42–0.8, exit at 0.8; enter forward steepeners (short gamma) at BE/RV ≥ 1.17–1.38. The two sides are one franchise flipped on this ratio.

## 1.3 The five signal families (how every trade in the corpus is generated)

1. **Risk-adjusted carry harvest (the default):** hold the side with σ_BE/σ_rlzd on your side and positive rent. JPM RAC = E[3M return]/(3M realized daily bp vol·√252); Citi picks packs on "most-of-8-metrics" (z, VsModel z, 3m roll, I/R). **Ours: rank on rac_net (carry net of reversion drag), because corr(carry, level z-score) = +0.61 — raw carry ranking systematically surfaces things that have already run.**
2. **Mean reversion / dislocation:** z-scores of the wrapper's price vs its own history and vs model (CA VsModel ≥ 2σ was every published Citi entry; JPM fly residuals: 6M two-factor regression on body level + wing curve, enter R²≥60% & |z|≥1.5 & |resid|≥4bp, exit at zero-cross / +2SD stop / 1M horizon — 1.3bp/trade, 52–55% hit over 2001–21, with the beta-stability gate √(Zb²+Zw²) ≤ 3).
3. **Cross-wrapper RV (vol vs vol):** same risk, two wrappers, trade the spread — curve breakeven vs 1Yx30Y swaption vol (JPM), basis-implied vs futures-option vs swaption vol (the basis triangle: same CTD underlying), CA-implied vs cap/floor vol (Citi), board vs CTD-matched swaption vol (Citi's standing table), listed vs OTC.
4. **Flow/positioning conditioning:** CFTC TFF (AM+LF net %OI inverted tracks Blues CA−model; dealer beta peaks at Greens per JPM), convexity-hedger flow maps (MBS/bank/VA/Formosa $mn/bp with thresholds), skew-as-positioning (3m10y 25-out RR percentile → next-1m rate direction), CME-LCH basis as long-end positioning proxy (3m corr: 31% TY spec/OI, 51% Δ10y).
5. **Macro punts wearing an RV coat:** ultra-long forward flatteners as standing long-vol (the PM's "strikeless vol"), curve caps for re-steepening views, conditional structures at zero-cost strikes.

## 1.4 The two-sided franchise (the deepest structural point in the corpus)

Citi runs the SAME algebra long and short and flips on the ratio:
- **Short-vol wing:** sell CA (buy futures/pay matched CME swap) when CA-implied ≥ 2σ over Ho-Lee and I/R ≥ ~1.5 — positive rent ~1.2–1.5bp/3m, target 4bp, stop 2.5–3bp.
- **Long-vol wing:** delta-hedged long-dated forward flatteners when BE/RV ≤ ~0.8 — pay ~0–2bp/y of rent for gamma harvested by mechanical DV01 resizes every 15–30bp (the PM's exact mechanic: "recalc the delta every 25bp, resize notionals back to DV01-neutral — every resize is taking profit").
- The forward-steepener screen (12-Jun-2023) is the same book short: sell the flattener when BE/RV ≥ 1.17–1.38 and carry is fat (10y10y/20y5y earned 10.31bp/y carry at −1.47σ since-2000 z).

**A desk formalizing this should run one ledger and two books:** a "harvest" book (short the wrappers whose σ_BE/σ_rlzd is highest, long those lowest, subject to rent ≥ 0 where possible) and a "dislocation" book (fade 2σ+ moves in wrapper-vs-wrapper spreads, beta-stability-gated).

## 1.5 What our own measurements FORBID the framework from assuming (the constraint layer)

These are ARBS results, each of which killed a naive version of the framework. The framework below is designed around them.

1. **A fly is NOT a vol hedge.** Level R² up to 0.88 (10y10y/20y10y on 10Yx10Y nvol, β −1.13 — the desk intuition is correctly signed) but **partial R² after level/slope controls is 0.000–0.044 on all 11 legs, and weekly change R² is 0.0003–0.089 with sign-flipping β**. The fly/curve co-trends with vol; it does not co-move. Flies enter the ledger as **curvature/carry instruments priced off vol**, never as vega hedges; gate any vega-match on the partial R² of the vol term.
2. **CA-vs-fly pairing is dead four ways** (515-cell + 298-cell pre-registered grids, both DEAD; Citi's own 2s5s10s hedge has hedge R² 0.000–0.010 and sign-flipping β on the rebuilt panel; "no hedge beats every hedge" monotonically in hedge size). The one real relationship (1s2s3s spot) is curve shape at the pack's own maturity, not vol.
3. **The CA's quarterly roll jump IS its theta** — a roll blackout leaves a one-sided short-CA carry ≈ +1.2bp/quarter that must be decomposed out of any Sharpe.
4. **Fill and roll conventions are the first suspects:** same-day fills harvest the CA mark's own noise (median hit 0.93 → 0.45 with t+1 fills); constant-rank labels book the IMM-roll switch as P&L (22/33 SR3 rolls are FOMC dates); mark-quality: run the EWMA-deviation diagnostic (SFR12: 4bp wanders for days at AC1 −0.056 "clean").
5. **A par-rate panel is not a P&L model:** Δrate×DV01 overstated hedged CA books 1.5–6× in Sharpe and understated an unhedged one 2–3.8× in dollars (daily-change corr 0.09–0.53 vs engine). Signals on panels; P&L from repricing engines (struck instruments age; carry/accrual is invisible to a level-difference panel).
6. **Estimate hedge ratios at the holding horizon:** tick-quantised marks attenuate daily regressions (β 0.61→1.22, variance removed 18%→53% from 1d→15d horizons); near 1, prefer flat 1:1.
7. **A model-implied hedge ratio must be regression-tested through the origin before use:** the FedWatch-lattice ratios were 5.7× too large for a density payoff (digital's sensitivity is a CDF difference; a fly's is a density). Hedge a density with a density.
8. **Vol-surface support gate:** a position priced outside the quoted grid manufactured the strongest fake result in the program (1M leg Sharpe +1.94 extrapolated → −0.19 on support). Gate any vol comparison on being inside the quoted term structure.
9. **Costs are first-order and per-LEG:** quote P&L at 0×/0.5×/1×/2× and the break-even cost per leg on gross DV01 traded. Measured anchors: swaps 0.3bp one-way (2017+), long-dated flattener 0.75–1bp entry + 0.3–0.4bp per rehedge (realized ≈$32k per $50k-DV01 round trip over 7 months), long-end fwd fly package ~3bp (untradeable in Mar-2020), SR3 fly ~1.5–2bp measured round trip, CCP-basis breakeven ~3.9–4bp.
10. **DV01-neutral is not factor-neutral:** PC1 loadings are humped, so zero net DV01 leaves 3.8–16.7% of an outright's level risk; the slope residual varies **130×** across structures under the same rule (5Y/30Y = $56,249/unit of PC2 — a slope trade wearing a convexity label; the tight forward pairs = 409/unit). Hedge PC1 on the tight pairs; never size 5s30s-type structures as convexity trades. Walk-forward-vs-full-sample PCA gaps mean you are trading the estimator.
11. **Statistical bars:** deflated Sharpe at the effective n (holds overlap; n_eff from holding period and cross-structure correlation), E[max SR|null] on BOTH clocks (per-hold and annualised — the annualised null is 1/√span-years, the larger bar), negative controls that must fail, and the standing meta-finding: **research bugs flatter the hypothesis (12/12 precedent)**.

---

# PART II — THE CATALOG BY VENUE

## II.1 Ultra-long forward-curve convexity (the "curve as an option" franchise)

### The physics
PVBP-weighted flatteners have a straddle payoff under parallel moves: in a selloff the longer receive-fixed leg sheds dollar duration faster than the shorter pay-fixed leg gains it (positive P&L both directions). Convexity per unit DV01 ∝ maturity; the long end moves near-parallel; so the very long end is where curve trades become options. The market charges for it by inverting the curve there (30s/50s inverted across USD/EUR/GBP/JPY, 10-year evidence) — **the inversion is the option premium**; LDI/pension receiving is the structural flow that sets its level.

### JPM "An option by any other name" (03-Feb-2017, Younger/Sarkar/Salem) — the founding document
- **Two signals:** (1) expected payoff of an aged fixed-coupon flattener under the ATMF+OTM **1Yx30Y swaption-implied terminal distribution** (parallel shifts, 1y horizon) — positive ⇒ curve is the cheaper gamma; (2) **curve-implied vol**: the normal daily vol that zeroes expected payoff — compare to 1Yx30Y ATMF vol in bp/day.
- 2008 evidence: curve-implied vol barely moved while swaption vol spiked ⇒ **curve gamma outperforms in risk-off** (the crisis richening of options is a wrapper premium, not a risk premium).
- **Backtest (daily entries post-Jan-2009, flattener + sell 1Yx30Y ATMF straddles sized so premium = 1y carry; reverse when rich):** 30s/50s — 70% cheap-share, 56% hit, +10.4bp avg, carry −100.6bp; **25Y/20Yx5Y — 100% cheap-share, 86% hit, +11.4bp avg, carry +1.1bp** (5/95th pct −10/+33). Forwards dominate spot: same convexity, none of the carry bill.
- SDR flows confirm: >20Y-forward-term activity tripled 2014–17.

### JPM "Valuing convexity in the long end — a global perspective" (09-Feb-2018, Salford/Younger et al.)
- **The formal decomposition: E(R) = carry + slide + ½·σ²·Γ/PVBP** ("value of convexity"); doubling vol quadruples it. At ±100bp, >20% of a 50Y swap's P&L is convexity vs <2% for 2Y.
- Known-answer tables: OAT ladder (May-48 carry 10.6/slide 2.0/cvx 3.3 → E(R) 15.9, RAC 0.33 … May-66 7.9/−1.0/4.9 → 11.8, 0.25 — **convexity value rises with maturity while carry+slide falls; the crossover defines the "convexity-efficient" sector**); EUR 1Y convexity value 10/20/30/40/50Y = 1.2/2.3/3.3/3.9/4.5bp current vs Lehman highs 7.6–45.9 (z −0.7 to −1.3); GBP = 2.0/3.5/4.9/6.1/7.3 (z −0.4 to −1.0); gilt fit **cvx = 0.49·vol² − 0.6·vol + 1.05, R² 99%** (pure σ² as theory demands); 30s/50s gilt fair value = 0.6·cvx + 5.3·y50 − 31 (R² 56%, se 4bp) ⇒ curve ~5bp too flat on LDI flow.
- **Cross-market verdict: convexity cheap in USD & GBP, mixed EUR, expensive JPY. Best structure 20Y/40Yx10Y in USD/GBP (high payoff AND positive roll); 15Y/35Yx15Y competitive in EUR.** Breakeven-vol ratios vs 50Y: 30Y needs a ~20% vol decline to equalize expected returns with 50Y.

### Citi "US Rates Vol Lab: Trading long-dated convexity" (09-May-2019, Bikbov/Williams) — the systematic long-gamma engine
- Structure: DV01-neutral forward flatteners (receive longer fwd, pay shorter), **delta-hedged by resizing the longer leg's notional at each 25bp move in the longer rate** (Sharpe insensitive 15–30bp thresholds). At those horizons the curve is "mostly convexity adjustments, term premium, technicals" — 10y10y/20y10y ≈ implied vol in curve form: **regression 10y10y/20y10y = −0.5·(2y10y nvol) + 19.0, R² 0.5** (2010–2019).
- **Backtest (2013–2019, $100k DV01, annual roll):** Sharpes 0.05–0.35, best 10y10y/25y10y (0.35), 20y5y/25y10y (0.30); corr(monthly P&L, Δ1y10y vol) +26%; **skew ≈ 0 vs −3 for short 1m10y straddles at Sharpe 0.84 — the long-gamma book buys the tail the gamma-selling book sells.**
- **Entry screen (BE/RV):** the 5/8/2019 table — 15y5y/20y10y at BE 1.3bp vs realized 3.0 ⇒ **0.42, the trade**; exit rule realized when BE/RV hit 0.8 (5-Dec-2019).
- **Full lifecycle tie-outs:** USD 15y5y/20y10y entered 5/9/19 @ −11.8bp, $50k DV01, hedge each 20bp, reweighted 10/16/19 (empirical β 1.025), closed 12/5/19 @ −12.5bp: **+$187k gross, +$155k net — with the curve nearly unchanged: pure realized-convexity harvest minus roll minus ~$32k costs.** GBP 15y10y/25y10y entered Jan-2020 @ −11.2bp at **positive carry +0.5bp/y ("effectively free convexity")**, closed 26-Mar-2020 +£445k = £115k curve + **£330k convexity** (COVID: convexity P&L 3× curve P&L in 2.5 months).
- Risk: VA receiving concentrates in ~20y (corr(equities, 15y5y/20y10y curve) −23%), but corr(trade P&L, S&P) ≈ 0 delta-hedged.

### Citi "Rates Vol Lab: Forward steepener and vol divergence" (12-Jun-2023, Chang/Williams/Appeddu) — the same book, short side
- Post-debt-ceiling vol collapse: prefer selling vol via **structures**, not options: (1) short Blues CA (maintained), (2) **long-dated forward steepeners as positive-carry short-vol**.
- Mechanism: long-dated forward steepeners are net short convexity ⇒ back out **implied yield breakevens from carry + negative convexity** and standardize: **BE/realized ratio**. The 06/08/23 screen: 10y10y/20y5y carry 10.31bp/y, daily BE 7.22bp, 1y realized 5.24 ⇒ **1.38**; 10y10y/15y15y 1.17; efficient frontier = carry vs entry z (since-2000 z −1.47 to −2.07 — the fat-carry cells are the ones that have already flattened; the trade-off is explicit).
- The divergence signal: 2y30y vol vs (20y5y−10y10y) moved inversely all year until vol collapsed and the curve bear-flattened — a **wrapper-vs-wrapper dislocation flag** (wait for FOMC, then sell the rich wrapper).
- Same issue: Blues/Golds CA finally declining toward model (~5bp above); full 13-row CA table (M4-H5 4.03 … M7-H8 22.29, Blues H6-Z6 13.70 vs model 8.96).

### The PM's version (Bloomberg chat, 21-Jan-2026) — "strikeless vol"
- 10y10y/20y10y flattener + **receive 1y-fwd 2s7s30s fly in 5:1 rough-PCA weights** = "long vega short gamma without trading a swaption": the flattener is short 20s gross; the fly translates the 20s bucket into a delta hedge that earns carry when nothing happens.
- **Mechanics = the whole framework in chat form:** "recalc the delta every 25bp, resize the notionals back to DV01-neutral, every time you will be 'taking profit' … how you do the resize (always decrease vs keep constant) makes the delta-hedging also your exit." Japan 1010/2010 flagged as the multi-year carry-vega version. **Cleaner expression: 15y5y vs 20y10y** — less factor exposure, no fly leg needed (identical to Citi's chosen pair).
- **Our verdicts on this trade (constraints):** the FORM is right — breakeven daily move 5.81bp vs 1.43bp realized (ratio 4.05) beats a same-carry short swaption (zero vega vs $11,407/bp of vega on the straddle; a 30bp vol spike = 37% of the year's carry) — but the TIMING doesn't survive: level at 90th pctile with AR(1) half-life 3.1 months nets −3.4bp at 4.5m unless the inversion unwind is structural. `10y10y/15y10y` beats `10y10y/20y10y` on risk-adjusted carry (rac 0.64 vs 0.40). And the factor attribution says the tight pairs need a **PC1 hedge**, not a slope hedge.

### Related long-end/flow documents (JPM IRD weeklies — the flow layer)
- **"A comprehensive look at convexity hedging" (Mar-2019):** the hedger census — GSEs shrunk 80%, banks ~$2tn MBS ~20% hedged, mREITs quadratic-fit duration gaps, MSRs = 30bp IO strip, programmatic gamma sellers = $500mn/day 1Mx10Y straddles (25% delta-threshold optimal), **Formosa/callable channel ~$200mn/bp dealer long convexity, ~40% recycled via Bermudan-vs-European "B/E switches"**; VA hedging now slope-driven not level-driven.
- **"Is bank convexity hedging lying in wait?" (May-2019):** bank balance-sheet convexity model (deposit betas 0.45 retail / 0.65 wholesale, +0.15 per 100bp; equity duration ~5y short); a 50bp rally ⇒ $300–400mn/bp more to shed ⇒ **asymmetric spread directionality** (narrowing in rallies > widening in selloffs).
- **"The return of convexity hedging" (Jan-2020):** MBS back at max negative convexity; receive TYH0 invoice spreads @ −5.95bp off a two-regressor fair value (bank convexity + 3M GC/OIS).
- **"Renewed Formosa supply" (Feb-2020):** 40nc5 structures push 20–50Y partial duration; fair-value gate = **swap-implied/swaption-implied vol RATIO** for 20Y/40Y, 30Y/50Y flatteners; 30Yx10Y vs 10Yx10Y flattener @ −39bp.
- **"The long and short of it" (Aug-2018):** 30Y spread fair value = f(5s/30s, deficit expectations, VA flows, WAM); CME-LCH mechanism paragraph (dealers-receive-at-CME priced into LCH par rates).
- **"For cheap gamma, look to the long end" (Aug-2019):** 10s/20s/30s fly fair value = 5y regression on 10s/30s + VA durations, **R² 98%, se 0.5bp**; carry-optimized flattener pick pay 15Y/5Y vs receive 35Y/5Y @ −35.7bp (closed +7.9bp Jan-2020); conditional 10s/20s/30s payer-fly widener in a selloff (premium-neutral 25d 6M payers).
- **"Zen and the art of gamma maintenance" (Mar-2018):** expiry-curve fair value (3Mx10Y/2Yx10Y ratio on avg vol, gamma supply, VIX); **kurtosis-conditioned gamma rule** — short 3Mx10Y delta-hedged performs better after high trailing kurtosis; short 1Mx10Y held-to-expiry performs worse when initiated on significant-kurtosis days; sell 3Mx10Y vs buy 2Yx10Y straddles delta-hedged.

## II.2 The STIR convexity adjustment (SOFR futures vs matched swaps)

### The object, precisely
**CA = pack rate (average of 4 SR3 rates) − matched-maturity forward 1y CME swap rate, in bp** (both legs quarterly, IMM-dated, ACT/360; the swap leg's venue matters — CA "appears wider if clearing the swap leg on LCH"; CME preferred because futures+swap margin nets). Positive CA = futures rate above forward.
- **What it is economically:** the future is linear ($25/bp always) and margined; the cleared swap is convex and carries PAI. The CA is the **financing/margining bias** (CIR 1981): shorts reinvest gains high / finance losses low. For SR3 specifically there is **no ED-style payout nonlinearity** (Huggins & Schaller: settlement at the END of the reference quarter makes the futures rate a true forward "with no convexity") — the entire SR3 CA is margining bias + microstructure + positioning premium. Gaussian-HJM closed forms (Henrard Thm 1/2) price the margining term; Rosen: the SR1/FF (arithmetic-average) CA = daily-weighted sum of one-day ED CAs ≈ the compounded CA (differences <0.01bp SR1, ≤0.33bp SR3).
- **Model magnitudes (fair-value scale):** at HW(a=3%, σ=65bp): ~0–0.5bp Whites, 1–2bp Reds, ~4–4.5bp at 5y, ~7bp at 7y. SR1/FF ≤ 0.07bp. **CA-based RV is only meaningful from Reds outward.** Front contracts decay deterministically through the reference quarter (no convexity on fixed days — Henrard Thm 2).
- **Ho-Lee working forms (Citi's model):** `CA = (Fwd + 1/Δ)·[exp(σ²·T·Δ·(Δ + T/2)) − 1]` → practical `CA ≈ σ²T²/2`; Citi's screen uses `CA_model = 0.5·σ²_capfloor·mean(T1_i²)·1e4` and inverts for CA-implied vol. (Hull's ½σ²T1T2 does NOT reproduce Citi's tables — monotone bias 0.93–0.98; the T1² convention does, verified on 8 tables.)
- Attack68's practitioner correction: positioning/margin effects "**engulf** the theoretical prices — I've seen real market positive convexity prices, which are impossible theoretically"; his production method is approach 4: **imply CA directly from futures vs traded IRS** with a smoothing parameter model (rateslib CompositeCurve recipe). ARBS implements exactly this (identity exact at 0.000bp over 29,643 rows).

### The Citi CA franchise (2016–2023) — the most complete published RV loop in the corpus
- **The screen (weekly, 13 columns):** CA, 1wk chg, 3m/1y z, Model, VsModel + z's, **3m roll (short cvx)** [identity: roll(p) = CA(p) − CA(one contract nearer), verified 12/12], CA-implied vol, 3m realized pack vol, Impl/Rlzd, cap-vol Impl/Rlzd. Three best short-CA trades bolded per metric.
- **Entries:** every published entry at VsModel ≈ 2σ (3σ at the Jan-2017 extreme). Pack picked on most-of-8-metrics; Jun-2021 Blues-over-Golds on higher 3m roll + higher CA-implied vs own range; Blues-over-Golds 2023 on "Golds more dislocated but more persistent."
- **The published ticket ledger (known answers):**
  - 9-Feb-2017: sell $200k DV01 Blues (2000 H0-Z0 packs vs $2bn CME 3/18/20–3/17/21) @ **8.8bp** + pay belly 2s5s10s fly $147/−$85.6/$20.89mm @ −18.2bp → closed 6-Jun-2017 @ 6.6bp, **+$500K net of costs** (+$552k in the model-portfolio table); target $600k/stop $350k; entry package carry +$380k/3m.
  - 6-Jun-2017: sell $300k DV01 Greens (3000 M9-H0 vs $3bn M19–M20) @ **4.3bp**, hedge sell 500 EDM9/buy 424 EDM8 (1/−1.18 DV01) → hedge off 13-Jul +$70.5k; closed 8-Aug-2017 @ 2.65bp, **+$475.5k net** (implied round-trip cost ~$20k ≈ 0.07bp on $300k DV01).
  - 5-Jan-2018: sell $100k DV01 Blues (H1-Z1) @ 6.5bp + 130 EDM9/176 EDZ1 (0.74/−1); carry +$140k/3m.
  - 18-Apr-2018: sell Blues outright @ 7.2bp mid ("flat curve is normally negative for vol" — hedge dropped).
  - 11-Jun-2021: sell $100k DV01 Blues (1000 EDM4-H5 vs $1.01bn CME) @ **7.9bp**; target 4bp tightening/stop 3bp; carry +1.2bp/3m; 5.9bp within 10 days.
  - 17-Feb-2023 (SOFR era): sell $100k DV01 Blues (1000 SFRH6-Z6 vs $1.17bn CME 3/18/26–3/16/27) @ **12.7bp**; target 4bp/stop 2.5bp; carry +1.5bp/3m.
- **The hedge evolution (three fair-value proxies, all printed):** 2s5s10s swap fly `Blues CA ≈ 10.2 + 21.4·(−0.73·2y + 5y − 0.47·10y)` (Jan-2017) refit `9.7 + 20.6·(−0.705, 1, −0.465)` (Feb-2017) — **the drift between vintages is the instruction: roll the regression, never freeze coefficients**; the vol-proxy fly `59.7 + 60.5·(−0.71, 1, −0.18)` (3y1y vol 90% level-correlated); ED-strip proxy `model Blues CA = −0.65 + 0.044·(ED16 − 0.74·ED6)` (fit to 1999, "not effective at ZLB"); Greens: `−3.53·ED5 + 4.17·ED9`.
- **The positioning story (the standing conditioning variable):** futures are the capital-efficient short (1–2 day close-out IM vs 5-day swaps) ⇒ macro shorts express in ED/SFR ⇒ dealers long futures/paying swaps = structurally short CA ⇒ CA widens as concentration-risk compensation; short capitulation richens/normalizes. Fitted: monthly Δ(CA−model) on Δdealer positioning R² = 0.32 (2014–17); Citi's Fig-4 (2023) reproduced in-house **on Blues only**: slope +5.28e-07, t +2.59, R² 0.124. Rule: **CA above model = short base/cheap futures; CA at/below model = longs**. When CFTC went dark (Jan-2019) Citi used the CA itself + the CME-LCH basis as the positioning gauges.
- **Micro-RV variants:** per-contract CA vs monotone spline (Feb-2017: Decembers systematically cheap — Z8 +1.50bp at 1y z 3.22 — an OI/turn technical, "similar to using asset swap spreads for Treasuries"; ΔOI-in-Z9 regression R² 0.37); packs used because single-contract spreads are "noisy and hard to trade."

### JPM "A better way to sell vol: CME-based convexity adjustments are rich" (03-May-2017)
- CA net of theory = **implied funding spread** on the IM of the offsetting package (~1.3% total margin): 2y implied funding spread L+50–100 (2016) → ~L+300 (May-2017) as dealer ED longs grew; dealer-positioning beta on CA richness **peaks 2–3y forward (Greens)**.
- CME netting saves ~70–80% of margin vs ED/LCH pairs, yet CME-based CAs trade at ~80% of LCH-based — the netting benefit is not priced. **Trade: buy H9/M9 EDs vs pay CME-facing FRAs — long CA richness AND long front-end CME/LCH basis widening** (front basis <1bp, mostly ~0.25bp), monetized by pull-to-expiry (~2y).

### The CME worked chain (Jun-2025, Rogerson) — the mechanics tie-out
8 SR3 prices → DF ladder → 2y IMM swap coupon **3.3304%** → DV01 hedge ladder **100/99/99/98/97/96/95/95 = 779 lots** (the declining ladder IS the convexity) → parallel-move P&L table (±10/25/50/100bp: +$253/+$1,451/+$5,638/+$22,292 and +$182/+$1,269/+$5,241/+$21,226) ≈ (797−779)×½×100×$25 — "the swap-vs-futures rate difference is essentially the cost of the premium for buying the embedded option"; margin: futures IM $570k vs swap $1.57mn vs **portfolio-margined $46k (−98%)**. Cost anchors: 0.5bp 2y IMM swap b/o; 0.25bp pack/bundle tick; bundle give-up 0.1875bp in the worked example.

### CCP basis layer (the venue dimension of the CA)
- History: <0.1bp (2014) → 2bp blow-out May-2015 (dealer dual-IM cost passed to clients; CME re-marked its curves 13-May-2015 — the two-curve regime begins) → 30Y ≈ 3.4bp mid-2017, fully explained as two-sided MVA ($726,545 lifetime IM funding / $225k DV01 = 1.3 + 2.1bp) → 0.8bp Aug-2019 (SOFR IM-exemption anticipation + positioning unwinds) → ~0.85bp, vol-insensitive, 2024 sign flip. **Trade economics floor: 5Y breakeven 3.932bp (Clarus cost stack) / ≥4bp (SUERF)** — below that the basis is structural carry, not a trade. Positioning content: 10y basis 3m-changes 31% corr to TY spec/OI, 51% to Δ10y.
- Structural breaks for any backtest: 13-May-2015; 16/19-Oct-2020 (EFFR→SOFR discounting at both CCPs + mandatory basis-swap bookings); **Sept-2024 FMX SOFR futures clearing at LCH** (first SOFR-futures-vs-LCH-swap margin pool; 78% offsets at 2–5y); Jun-2026 repo clearing mandate (~+1bp "expanded SOFR" estimate).

### ARBS verdicts on this venue (constraints)
Short-CA hedged-with-fly is DEAD on the repaired 2021–26 panel (w2b gross Sharpe 0.130 < null 0.177; costs take 90% of gross; the fly hedge is worse than no hedge). CA mean-reversion grids DEAD (cavf 515 cells; gv 298 cells; SFR12's "clean" AC1 hid a 4bp multi-day dislocation). Ultra-long risk-adjusted carry DEAD (w4: gross 0.397 < 0.446 null; it was duration — level t −4.85). W3 (STIR CA-implied vol vs long-end curve-implied vol) dead at the diagnostic: max |change corr| 0.112. **What survives: the measurement layer (identity-exact CA, engine-certified P&L, the roll/theta identity), Citi's mechanism on Blues, and the two-sided BE/RV franchise logic — not the standalone mean-reversion trades at our costs.**

## II.3 Curve butterflies as the linear vol wrapper

### What a fly is (and is not)
- A fly = discrete second difference of the curve in maturity space = **curvature**. Its *level* prices convexity/vol (it co-trends with vol; 10y10y/20y10y on 10Yx10Y nvol level R² 0.81–0.88) — but its *changes* do not hedge vol (partial R² ~0, weekly change R² ~0, β sign-flips). Paying the belly is "like buying a straddle" only in the priced-rent sense: you pay curvature rent (negative carry) for a payoff that needs reshaping to pay. **Ours: forward flies are where you PAY for convexity (mean 1y CR −2.55bp, 30% positive across 502 structures) and same-tenor forward curves are where you EARN it (+6.63bp, 78% positive) — that's the venue split for rent harvesting.**
- Conventions: Citi quotes −0.5/+1/−0.5 (half of 2·belly−front−back); ED/SFR flies 1:2:1 or PCA (e.g. 0.9:2:1.4); JPM 50:50 flies = 2·belly−wings at 100/50/50 risk; PCA flies built from the 3rd PC of the legs (5y window) to have no beta to the belly.

### Citi "Flying Too High: Receive belly of 1y-fwd 5s10s30s" (20-Dec-2010, Arora/Chen) — the template forward-fly ticket
- Pay $180mm 1y→5y @ 2.971%, receive $200mm 1y→10y @ 3.908%, pay $50mm 1y→30y @ 4.344% (printed per-leg gamma: −64/+206/−230). **Target 20bp, stop 10bp.**
- **The fair value is regime-probability-weighted:** back out P(hiking starts 2011/12/13) from ED+LIBOR-OIS (30/42/28%), map to historical regime means of the fly (on-hold 24bp / start-hiking 10 / 6m-in 6), predicted 1y-fwd 5s10s30s = 19bp vs 48 current (98th pctile).
- **The convexity-cost accounting is the framework in miniature:** the alternative 1y-fwd 10s30s steepener carries +27bp/y but costs **11bp/y of convexity at 120bp/y realized vol** — "margin too thin"; the fly carries −5bp/y with only **8bp/y convexity cost** and low directionality. Target = 28bp mispricing − 8bp convexity ≈ 20bp. **Every fly trade should carry this line: expected reversion − convexity rent, at an explicit vol assumption.**

### Citi long-end 1x2x1 (15-Jun-2020 TP alert)
Receive 20y10y vs pay 10y10y & 30y10y, entered Feb-2020 @ 16bp on an **efficient-frontier screen (5y z vs 1y vol-adjusted carry)**, unwound @ 10bp, +$360k — with the operational lesson printed: package bid/offer ~3bp, and in Mar-2020 "large transaction costs meant we couldn't realistically take it off" at the max-P&L dislocation. Fly over outright steepener chosen for "smaller convexity risks."

### JPM EUR fly machinery (the methodology imports)
- **"RV on the ultra-long end" (11-Feb-2019):** RV opportunity index = 10d MA of Σ squared 6M fly z-scores; 5Yx5Y/15Yx5Y/30Yx5Y 50:50 fly vs PCA-weighted (15Yx5Y − 0.133·5Yx5Y − 0.778·30Yx5Y, level/curve-neutral by construction, 3M carry −1bp); cross-fly: 5Y-fwd fly = 1.40·(10Y-fwd fly) − 53.59 (R² 72%) → 100:140 fly-vs-fly RV.
- **"Pay belly of 1Yx1Y/5Yx5Y/10Yx10Y" (23-Jan-2020):** full ticket (€100mm 5Yx5Y vs €251.8mm 1Yx1Y + €26.2mm 10Yx10Y @ 11.6bp, carry −2bp/3M) with three fair values: quadratic-in-level (fly = 33.23x² + 10.56x + 15.44, R² 99%), cross-fly (0.87x + 23.95, R² 55%), level+curve-neutral 6M regressions (R² 78%/91%, se 2.9/1.6bp).
- **The beta-stability framework (07-Apr-2021) — the systematic recipe:** universe of 50:50 level/curve-neutral flies (spot + 1Y/2Y/5Y-fwd + 5Y-gap forward + money-market gap families); rolling 6M two-factor regression on body level + wing curve; **enter R² ≥ 60% & |z| ≥ 1.5 & |residual| ≥ 4bp** (best of 12 combos: 1.3bp/trade, 52% hit, 1,188 trades 2001–21); exit at first of residual zero-cross (ex-ante betas), +2SD stop, 1M horizon (Fourier: dominant reversion <1M); **risk gate: skip entries when √(Zb²+Zw²) > 3** (z-scores of the 3M vol of the body/wing betas — "when the betas are moving you are trading the estimator") — improved critical-period P&L ~+25%. Failure regimes named: cycle turns (2Q19 worst: 3–29% success).
- **Citi swap-fly RV appendix conventions (six dated vintages 2018–19 for tie-outs):** equal-weight −0.5/1/−0.5 and PCA (3rd-PC, 5y window) tables with 1m/3m/6m z and 3m carry+roll; ED monitor quotes pack flies both 1:2:1 and PCA.

### ARBS verdicts (constraints)
Fly-vs-CA and fly-vs-vol pairings dead (II.2); spot-fly mean reversion is real but edge +0.75bp/trade vs 1.5–2bp round trip; 5s10s30s is the worst spot fly on risk-adjusted carry (rac −0.39) BUT the only named structure positive on reversion-adjusted carry at 3–6m (z −1.00 ⇒ +1.6bp net) — **carry and reversion must be read together (corr +0.61)**. The 2010-style "convexity cost" line and the JPM beta-stability gate are the two imports that survive our evidence.

## II.4 UST futures basis — the delivery option as the tradable vol

### The object
- `gross basis = P_bond − CF·P_fut` (32nds); `net basis (BNOC) = forward bond price − CF·P_fut` = **the market price of the short's delivery options**; `gross = net + carry`; IRR = the term repo you earn after giving away the options, so **IRR < term repo always in theory, and the gap IS the option premium** (monotonicity proof: Fut < FWD_i(R_i)/CF_i ∀i). CTD = highest IRR / least-negative gap.
- **The basis-as-option map (CME):** yields < 6% → buy CTD basis = buy a PUT (CTD is the short-duration bond; selloff switches to long-duration); yields ≈ 6% → **straddle**; yields > 6% → call. No strike — think **crossover yields** (the levels where an alternate bond becomes CTD); vol drives the probability of crossover. Long basis floored at 0 (in the delivery month), unbounded upside — "reminiscent of a long option."
- **The four options** (Salomon/Burghardt taxonomy): quality/switch, timing, **afternoon wildcard** (invoice frozen at the 2/3pm settle, notice hours later while cash trades; monetized on the `1−1/CF` tail — a low-CF phenomenon), end-of-month (futures stop 7 bd before month-end; CTD can shift against a frozen invoice). **Which dominates is regime-conditional (dealer evidence + our audit):** near 6% yields the switch is live (ZB Sep26 CTD prob only 32–41%, 7 deliverables >1%); far below 6% the switch is "essentially valueless" and **the wildcard is the majority of net basis** (JPM Dec-2019); positive carry suppresses the wildcard (waiting earns carry), negative carry inflates it. UXY = wildcard-only; TY = switch + wildcard.
- Timing rule: carry positive ⇒ deliver last day (quoted IRRs to last delivery); carry negative ⇒ deliver early; a curve inversion mid-trade induces early delivery.

### Citi "US Rates Weekly: Summer lull" (17-Jul-2015) — the basis-vs-swaption comparison, executed
- USZ5 CTD migrated Feb36 → May37 in the selloff (higher coupon wins when durations converge); scenario analysis: parallel shifts on the forward yield at last delivery (31-Dec-2015), 6m realized vol for the probability distribution → CTD probability map: −30bp puts Feb36 back as CTD.
- **The trade: long $100mm May37 basis (vs 911 USZ5) at 4.2 ticks = $130k. Gamma $420/bp². The same gamma via 1m25y swaption costs $187k — the basis is the same option at 0.7× the price.** Matched-expiry scenario table (vs $100mm 5.5m25y ATMF receiver): ±40bp risk/reward 1.56 (basis) vs 1.3 (swaption). "On multiple metrics, the long May37 basis looks like a cheaper option to position for a rally."
- Same issue's vol section: calendar tenor selection by a **mean-reversion metric** — |forward-adjusted 1m move| / stdev of levels within the month; 3m/1m vol ratio vs this metric (fit 0.61x + 0.62, R² 0.70) says 10y tenors are the cheapest calendars (30y more mean-reverting but same ratio; short tails' high ratios justified). Un-hedged 1m10y straddle breakeven 20.4bp vs 27bp average seasonal Jul-Aug move — "seasonality is not a reason to short un-hedged vol."

### BofA "US Rates Alpha: Buy futures basis = cheap options" (10-Apr-2025, Ralph Axel)
- TY and UXY nets **0 to −0.5 ticks flat across first-to-last delivery** ⇒ owning the basis = the whole delivery month of switch/wildcard optionality **at flat-to-negative premium with flat carry** (coupons now above repo ⇒ the effective option window extends the full month, unlike prior cycles where negative carry compressed it to the front).
- Fair value: options "worth more than 0 ticks, probably ~1 tick for TYM5" (their model: 1.5 ticks under parallel + twist, may overstate the switch). **Trade: buy T 4.375 01/31/32 vs CF-weighted TYM5 at gross −1 tick / net 0; target +1 tick, base case 0, stop −4.** Nets were cheaper at the April-2 tariff-shock liquidation — "hard assets cheapen vs derivative benchmarks when cash is demanded" (the recurring basis-vs-swaps state variable).
- **Read with our verdict:** the trade is a long-vol expression at zero rent — exactly the σ_BE ≈ 0 corner of the ledger; scale check (BofA Apr-2025): the whole option ≈ 1 tick fair, entered 0 to −0.5, target +1, stop −4.

### JPM basis research series (the mechanics + distortion layer)
- **"Special delivery" (04-Dec-2019) — the accounting identity that makes the basis a measurable option:**
  `implied repo = CTD term repo − BNoC/(CTD dirty) × 360/n` — implied repo and net basis are **the same information**, but implied repo is annualized over a shrinking uncertain n and blows up into the roll (WN printed recurring 50–100bp implied-vs-term repo gaps each quarter "from just a few ticks of option value"; WNH0 CF 0.6141, wildcard ~3 ticks of WN net basis, 0.5–1.5 ticks elsewhere).
  **Option-adjusted versions:** `BNoC = option value + OA BNoC`; `OA implied repo = implied repo + option value/dirty × 360/n`; fair-value test: OA implied repo ≟ CTD term repo. **Use OA BNoC as the rich/cheap; raw metrics manufacture signals at the roll.** In the low-yield regime the switch is "essentially valueless" and the **wildcard comprises the majority of net basis** in UXY/WN.
- **"Good things come to those who wait" (18-May-2018) — the wildcard priced:** exercise threshold on the last live day `x₁ = GB(1day)/(1−CF)`; backward induction `E_n = (1−C)·[σ²·p(x_n) + (x_n/2)(1+erf(x_n/σ√2))]` with post-close σ **1–1.5bp/2hr, 2bp on FOMC days**. Verdicts: FVM8 (low CF) optimally delivered LATE even at gross basis down to **−3.5 ticks** (option ~0.5–1 tick > the bleed); TUM8 (CF≈1) delivered early (breakeven −0.75 ticks). **Rule: CF < 0.9 → wait for the wildcard; CF ≈ 0.95 → deliver ASAP.** The negative-basis wildcard is the pure form of "pay theta to own after-hours gamma."
- **"Why we should all care about Treasury futures basis" (12-Mar-2020):** the COVID unwind — levered gross shorts up to ~$600–650bn concentrated in TU/US/WN at ~20× leverage; "near-arbitrage terminal payoffs do not ensure low MTM volatility"; **implied repo becomes the system barometer** (TYM0 implied repo swung 0–3% intraday 3/11/20; unlevered front basis out-yielded 3M CP — the real-money entry signal); the Fed can fix cash repo but not the futures leg; channel into FRA/OIS and FX basis (trade: stay received EUR/USD 2Yx1Y xccy basis).
- **"The new and improved Treasury par curve model" (16-Jul-2018):** the cash-side yardstick — cubic-spline DF (9 params, 6 knots), duration-weighted yield-space objective, GC-repo-anchored short end, exclusions: OTRs/olds/double-olds, **repo specials ≥25bp through GC**, <1y, optionable; RMSE ~0.5–2.5bp. Rich/cheap of the CTD is measured against this; delivery-option distortion shows up as residual and must be stripped with the OA machinery, not traded as curve signal.
- **CFTC MRAC report (Dec-2024):** the official mechanics — 5-step trade, overnight-repo rolled daily, ~20× leverage, ~$317bn of basis-held Treasuries, zero-haircut NCCBR financing; "the delivery premium is driven by interest-rate volatility and the timing of the delivery window… and will decay to zero as the contract approaches maturity" — **the official sector describing the basis as a vol position with theta**. AM longs mirror HF shorts near 1:1. March-2020 unwind estimates $35–173bn.
- **Fed FEDS 2025-049 (liquidity study):** effective bid/ask (duration-normalized, vs an ML fair curve) — median D2C execution **0.37bp vs 0.68bp indicated** (you beat the screen), but **>$50mm clips: 95th-pctile 12.41bp vs 4.15 indicated**, worse when OTR liquidity degrades; **CTD status introduces NO bias in indicated spreads**; large trades show selective liquidity-taking. This is the execution-tail model a basis book should carry.
- **CS "New Ultra Long Contract" (28-Sep-2009):** the basket-breadth pricing of the quality option — ULH0 (9 deliverables) option ≈ **2.5 ticks vs ~10 ticks for USH0 (22 deliverables)**; UB convexity 442 vs US 112 (DV01 varies ±24% per ±100bp vs ±6–12%) — **fewer deliverables = less switch option = more convexity per contract**; trade: buy the belly of 11/21-2/25-11/27 (regression-weighted) into basket-anticipation cheapening; 30y spread floor thesis at the launch.
- **Citi "The long end basket case" (04-Feb-2015):** the basket-event case study — no long issuance 2001–06 + CME excluding the low-float 5.375% 2/31 ⇒ CTD jumps 6.25% May-30 (USH5, DV01 $166) → 4.5% Feb-36 (USM5, $252; 34.1% fewer contracts per DV01); the exiting 2029–31 sector cheapened **idiosyncratically ~12bp on ASW (3.9σ vs the 10s/30s ASW regression, R² 0.65)**; trade: buy May-30 sector vs 10y & 30y 1:2:1; note invoice spread sign is opposite to cash ASW; corr(Δinvoice spread, ΔOI) = 34% (AM basket migration). **Basket-definition events are a repricing channel entirely outside the daily option accounting** (same class as the TWE basket change 2022 and the ZN <8y grade vintage 2023).

### Burghardt & Belton, *The Treasury Bond Basis* (3rd ed., 2005) — the canonical framework
- **Identities:** `B = P − F·C` (32nds, $31.25/tick/contract); `basis = carry + BNOC`; **`BNOC = the market price of the delivery options`**; `IRR < term repo` always, gap = option cost; OAB = actual basis − (carry + theoretical option value); **"the basis is rich if OAB > 0; and if the basis is rich, futures are cheap."** The CTD's options are ATM (BNOC = pure option value); every other issue's are ITM (BNOC = option + moneyness).
- **CTD rules:** yields < 6% → lowest duration is CTD; > 6% → highest; equal duration → highest yield. Crossover yields are the strikes; **high-duration basis = call, low-duration = put, middle = straddle** — with the empirically vital wrinkle that **yield betas (curve flattens as yields rise) move the crossover WITH the market, "as if the strike were raised"** — the mechanism that killed basis gamma in 1991–93 (spread directionality +3bp per 10bp rally kept the CTD entrenched from 8.53% down to 7.41%) and that our own regime work should watch for.
- **The worked straddle numbers (Ch.2, Apr-2001):** buy the CTD basis at BNOC 4.53/32: unchanged yields → lose ~3; −60bp → +7; +60bp → +19.5. "The seller of the basis has sold an option on interest-rate volatility." The scenario method: shock OTR yield ±60bp with yield-beta-adjusted spreads, find scenario CTD, futures = (CTD − carry − EOM)/CF, read every BNOC; fair BNOC = probability-weighted E[BNOC at expiry].
- **The options, quantified:** switch ≫ EOM ≫ timing ("usually nothing"). EOM: after the last trade day the hedge flips from CF-weighted to **1:1** and the criterion flips from duration to **BPV** — "a change in yields that would make a bond cheap to deliver before expiration often makes it expensive after" — a re-exercisable strangle whose premium = the CTD's BNOC at the last trading day. Wildcard rule: play when `(C−1)·(C·F − P) > B`; the 1/(C−1) tail leverage worked example: basis 6/32 needs a 25.4/32 after-hours fall at CF 1.3093.
- **Hedging (Ch.5):** futures DV01 = CTD fwd DV01/CF **only between crossovers** — near one, the rule "can produce enormous changes in hedge ratios from 1bp"; option-adjusted DV01 from repricing the theoretical futures on a yield grid (10y contract: rule-of-thumb 60.76 vs OA 66.13 — **10% overhedge**); two separate risks: spot-yield DV01 (×(1+R·n/360)) and **repo/stub DV01 (opposite sign, ~$2.5–2.9/bp per contract, uncorrelated with yields — hedge with FF/SOFR futures)**; yield-beta hedges (1998: standard hedge 12.8% too big); the four competing "correct" ratios (min-variance/yield-beta/yield-delta/DV01) optimize different objectives.
- **Ch.7 — VOLATILITY ARBITRAGE (the direct ancestor of a basis-vs-vol program):** two arenas price long-dated yield vol — real options on futures and the embedded options in the basis. Input the **options-market implied vol** (translated σ_y = σ_p/(y·ModDur)) into the delivery-option model → OAB per issue → **OAB < 0 ⇒ buy the basis / sell the matched strip of real options; > 0 ⇒ reverse.** Record: 1990 client recs avg +6.9 ticks/5 trades; prop 1990–92 avg +3.3 ticks net; simulation 1989–90, |OAB| > 3 trigger: **297 trades, avg +4.9 ticks, σ 8.6 — vs unhedged basis legs avg +6.8, σ 13.4** (the option leg is variance reduction; the positive unhedged mean says the options market forecast vol better than the basis market). Cautions that transfer verbatim to our program: the basis also carries **spread and carry/special risks options don't**; profiles never match exactly; **options on futures expire ~1 month before the futures — the basis leg carries MORE vega than the real options** (the horizon mismatch).
- **Regime history (Ch.8, the base-rate prior):** delivery-option value cycles between ~0 (one entrenched CTD: 1995–99 = "a forward on one bond") and 8–12+/32 (6% factor change 2000: 22 CTDs in one quarter; buyback whipsaw). The 1986 9-1/4% squeeze: basis +6 points, spread −25→+100bp, repo to ~0% — the unbounded-loss tail of short-basis. Scarcity pricing: negative CTD BNOC = P(fail)×(2nd-CTD BNOC gap) — fail probability is priced, not free money.
- **Ch.10 — the harvest expression for real money:** the **synthetic note** (sell CTD, invest at term repo, buy OA-DV01-weighted futures): 19 of 21 quarters outperformed, avg **+61bp/yr** (futures chronically rich 2000–02 ≈ 2/32) — the mirror image of the levered basis trade, and the cleanest "sell the rich wrapper" implementation for an unlevered book.

### The practitioner toolset (RiskVal/Salomon/CME) — what a desk implementation looks like
- **Switch grid:** parallel ±bp × twist grid of the basket (shortest fixed, longest bumped, interpolate), each cell re-solving the CTD; delivery probabilities via PCA-factor simulation to last delivery, **variance scaled to the ATM listed-option vol (else swaption vol)** — i.e. the delivery-option model is priced off the same vol surface you're comparing it to. `Dlv Scen bp/Std` = distance-to-switch in bp and σ — **the moneyness of the embedded option, printed**.
- **Scenario futures price:** default = min converted forward at 0 net basis; refinement subtracts the market-implied option value (current 0-NB price − current future).
- **Option-adjusted net basis:** `OANB = NB − (selected option values)·CF` — **the residual the RV signal should trade** (worked: switch 2⅝ + EOM 9 = 11⅝ ticks total on the example bond). Sign convention we verified: `OABNOC ≈ (Term Repo − OA Implied Repo) × P_dirty × d/360 × 32`.
- **Wildcard pricing:** backward induction over delivery days, one-day reprice windows (6h of a 15h day), **vol = listed ATM option IV, tripled on FOMC dates**, exercise = ΔB·(1−1/q) vs remaining option value + carry.
- **Calendar roll fair value:** assume a smooth forward ASW-Z curve — front CTD carried to back delivery at forward repo; `R/C ASW Z = spot spread-of-z-spreads − at-d2 spread`; **roll rich (R/C > 0) ⇒ sell front/buy back**. The roll is where basis P&L concentrates; CF construction (RTM rounded down to quarter-years) makes convergence lumpy.
- **Roll-adjusted history:** stitched generic series jump at every auction/roll; adjust by decaying the WI roll across the prior cycle or the z-scores inherit phantom moves (ours: futures series roll on the FIRST POSITION DAY — IMM-rule assumptions were 25% wrong).
- **Hedging:** CF-weighting locks the cash-and-carry (never rebalance, but buy/sell the tail into delivery); DV01-weighting tracks MTM but needs rebalancing; futures DV01 = fwd DV01(CTD)/CF **only between cusps** — through a cusp the contract's DV01 gaps (Salomon: $101→$82/bp at the −50bp cusp) and its convexity "can be zero or even negative." **This IS the delivery-option gamma, and it belongs in the ledger as such.**
- Funding line: IRR < term repo persists because the trade consumes balance sheet (Basel LR: ≥7.5–15 cents/3m of net basis just to clear a 10% ROCE hurdle at 3–6% leverage ratios; 2–3 ticks ≈ 0.33–0.66% return on capital) and the resource is withdrawn at year-end (March basis structurally cheap). Funding enhancement: lock IRR−OIS with a pay-fixed OIS overlay and run the OIS-vs-repo basis instead of terming repo.

### ARBS verdicts (constraints)
Basis-vs-vol V1 (option-adjusted basis z) DEAD twice — original data corrupt (UB was pricing an FX future; ZN basket admitted non-deliverables), and on repaired data still below its own null (best 0.320 vs 0.503), the delivery-option model adding only 0.035 Sharpe over a raw net-basis fade; the honest name was "fade the net basis." The one carry-forward is a LEVEL: ZN's grid median moved −0.14 → +0.16 with 72% of cells positive. V2 (exchange vs OTC vol) DEAD (1,296 cells, best 0.97 vs null 2.73; the 1M "edge" was the vol surface extrapolating below its shortest node — the support-gate lesson). Two-bond Bachelier switch models capture ~35% of a diffuse basket's option (ZB spans 33 months of maturities — one switch is not the basket). **Surviving architecture: split σ_basis − σ_exchange − σ_swaption into V1 + V2 legs; V2 is 80% built in-house (737 days of TU–UL vs swaption vol, expiry- and tail-matched); the JPM daily "Volat Implied by the Basis" column vs "Opt. IVol" is the vendor's version of the same wedge (Dec26 ZB printed 5.19 vs 9.69 — only wedge worth money at the time).**

## II.5 The option venues themselves — Citi's Vol Lab toolkit (the RV instrument panel)

Each weekly Vol Lab runs the same ~15 modules. As a framework this is the most complete published example of a vol-RV instrument panel; every module is a candidate screen for the linear trader choosing WHERE to express:

1. **ATM grid + z-scores** (levels, 1w/1m changes).
2. **Macro-vol fair value:** regress each ATM point on 3 PCs of the swap + TIPS-breakeven curves; calibrate pre-2008 + 2017+ (the model "is broken with near-zero FedFunds"); residual = rich/cheap to RATES. (3m10y ≈72 fair vs 70 market, May-2017.)
3. **PCA of the vol surface** (3 PCs, 2y window): rich/cheap WITHIN vol, relative only.
4. **Implied vs realized:** 1m/3m realized, close-to-close AND intraday (30-min, 7am–4pm); the ratio by tail/expiry with z-scores.
5. **Realized-by-time-of-day:** hedging at noon vs 3pm changes realized vol materially (2018: optimal hedge time drifted to 12–1pm; 2023: morning hedging = higher realized).
6. **Expiry & tail switches:** vol ratios (6m10y/1y10y etc.) z-scored.
7. **Forward vol:** triangular approximation from spot vols (6m realized correlations as implied proxy); the **efficient frontier of forward-vol trades** — all gamma-neutral calendars/triangles ranked by ex-ante Sharpe (vol-adjusted roll) vs 1y z.
8. **Vol carry heatmaps:** 6m fixed-strike straddle carry by point.
9. **Skew:** 25bp-out payer/receiver/RR z-scores; **implied vs realized skew via an empirical SABR calibrated to the realized dynamics of ATM vol and rates** (2y backbone window, 3m corr/volvol window) — "realized skew" = the model value of OTM options under realized dynamics; spread-to-model z-scores (3m10y RR +2.9σ Jun-2023). *This is the cleanest published recipe for pricing skew against delivered behavior.*
10. **Skew-as-positioning:** 3m Δ(3m10y 25-out RR) percentile → next-1m Δ10y (Jan-2006–Nov-2016: <25th pctile ⇒ −11.5bp avg; >75th ⇒ +8.8bp, 69% up) — flat skew flags crowded shorts.
11. **Board vs swaption:** listed UST futures options ATM vs **CTD-matched swaptions** (strike = board strike yield + invoice spread; futures/swap realized-vol ratio as the fair anchor) — the wedge our V2 formalized. Plus full strike-grid comparisons (board puts vs payers, calls vs receivers).
12. **Conditional structures at zero cost:** costless strike spreads on curves/flies (bear/bull steepeners, payer/receiver flies) with implied-vs-realized betas and pickup tables — the standing translation of a vol view into a linear-conditional view.
13. **Midcurve vs vanilla:** regress midcurve vols on the two adjacent vanillas (3y window), residual z.
14. **CMS curve options:** implied correlation (5s30s implied corr at multi-year lows on curve-cap demand), implied/realized curve-vol ratios — **curve vol as its own venue** (implied curve vol rich when correlation is bid).
15. **Callable/Formosa supply monitor:** gross/net issuance, redemptions, **vega supply in $mn** (the structural vol-supply flow; 30nc1 vs 30nc6 bp-vega $145k vs $270k per $100mm — the FSC lockout rule change = +$31mn/yr vega), plus the SOFR-discounting repricing of the dealer hedge stock (−$100mn vega repricing estimate, Mar-2019).
16. **The CA screen** (II.2) — the STIR wrapper, in the same book.

### Named Vol Lab trades in the corpus (beyond CA/flatteners)
- Gamma: sell 1m10y/3m10y straddles delta-hedged (1997–2017 backtest: 1m10y avg 0.64bp/day Sharpe 0.48 daily-hedged; **0.84 with a 25%-delta threshold**, monthly hit 65%; unhedged 0.43; with 0.3bp costs daily hedging optimal, at 0.5bp a 3–7% threshold) — the short-gamma benchmark every linear wrapper must beat.
- Vega tenor flies: sell 3y2y/buy 3y10y/sell 3y30y vega-neutral (fair value = regression of the vol fly on curve level+slope ex-ZLB; +$240k take-in, carry +0.75nv/1y).
- Vol-cycle timing: corr(3m/1y-fwd-3m OIS slope, next-3m short-gamma return) ≈ +35%; May seasonality (gamma outperformed 4 of 5 Mays); Sep seasonal ~−5abp in 3Mx10Y.
- Curve caps: 1y 2s10s caps vs 6m 5s30s caps calendar (fwd vol = √(2·(1y)² − (6m)²)); 3y 10s30s conditional bear steepeners; 6m 5s30s/2y 2s30s cap switch.
- Left-side RV: 1y5y/1y30y ratio on the realized curve-to-rate beta (y = −0.61x + 0.96, R² 0.62); 5y2y vol on 5y2y rate (24.28x + 24.73, R² 0.91) ⇒ 5.7nv rich call.
- USD-vs-EUR and USD-vs-JPY straddle switches; 10y10y USD vs EUR (Mar-2020).

### What the linear trader takes from II.5
The Vol Lab IS the pricing source for half the ledger: cap/floor vols price the CA model; 1Yx30Y ATMF prices the curve's gamma; board-vs-swaption prices the basis triangle's third leg; the empirical-SABR realized skew prices conditional structures. **A convexity-RV desk needs a subscription to (or a rebuild of) exactly these panels — the framework in Part IV specifies the minimum rebuild.**

## II.6 The Bassman universe (Convexity Maven / Commentary / RateLab / Musings) — the dealer-structurer's convexity

Bassman's 30+ notes are the corpus's connective tissue: every wrapper above appears, priced through dealer structures. The recurring toolkit:

### The three laws (his versions of Part I)
1. **Curve ↔ vol law:** the spot-forward gap and implied vol are two prices of the same risk. When they diverge, one is "the wrong price" — 2014: curve +1SD steep while 1y10y vol −1.67SD ⇒ **the Three-to-One Rule**: buy the 1y2y receiver when 1y roll-down ≥ ~2.75–3× the premium ("a 3-to-1 payoff for a 2-to-1 risk"; 5th occurrence in 20 years). This is σ_BE/σ_impl in retail clothing — the same ratio the ledger ranks.
2. **Forwards are breakevens, not forecasts** — and under no-free-lunch the forward IS fair value, so "active management is the process of selecting assets where one thinks the forward price will not be realized"; the big money bets against forwards contorted by **regulation, accounting, or fear** (2008 EUR 30y-10y-forward < JGB; post-taper FVA surface 15% under spot; insurance-driven 10y equity vol).
3. **Carry is theta, priced in dollars:** the DV01-weighted 2s10s steepener "needs 58bp of steepening in a year to break even… a $100mm ticket costs ~$390,000 per month to hold." Every negative-carry position is a decaying option on a view; prefer structures that pay while waiting.

### The trades (dated, with terms)
- **"Your Ace in the Hole" (Jul-2014):** buy 1y2y receiver @ 56bp, K 1.45%, vs 82bp of roll-down — 2.88× payoff; "a fine replacement for long greens."
- **"For Propeller Heads Only" (Jun-2019):** 6m 2y payer spread (ATM 1.696% vs +50 2.196%) **contingent on SPX −5%** — 36c → **8c (−78%)** by selling the stock/bond correlation; 3.75× payout if rates unchanged and SPX −5%. "A near-the-money option at the price of a tail hedge."
- **"How High is High?" (Sep-2013):** the three bear structures — (1) **calendar midcurve payer spread**: sell 2y→(8y-20y) midcurve payer K 4.75% @ ~92nv vs buy 10y→20y payer same strike @ ~71nv, pay 400bp, +160bp first-year roll = synthetic forward vol in the mid-60s; (2) 5y5y payer ladder 4.85/5.60/6.90 zero-cost; (3) liability-manager collar: buy 5y10y receiver 3.50% / sell payer 6.25% zero-cost — "steep curve, high vol, elevated payer skew: all three conditions available."
- **"Skewered by Skew" (Apr-2013):** skew taxonomy (risk preference, kurtosis, speed, location, flows) + three zero-cost skew trades: the 5y5y payer ladder (3.65/4.50/5.50, flat delta/gamma, positive carry, thesis = the MBS vortex re-coupons and the 18nv skew ladder must compress — "profits booked as vega when the skew inverts"); conditional bear flattener at a 90% 5y/10y vol ratio (pre-ZIRP average 105%); the 5y SPX 1000/2000 risk reversal (paying 25% skew premium for the limited-loss side is backwards).
- **"Volatility Mousetrap" (Sep-2012):** the FVA as the only clean vega-as-asset-class (no delta/gamma/theta/skew until the look date, "you own the skew for free"); calendars can be right on vol and lose money (the Kumquat example); buy 3m10y straddles 2m forward at +8% over spot into the election; 5y vol swap on 1y20y at 16% under spot.
- **"Forwards are NOT a Prediction" (Aug-2013):** buy 8y-into-20y straddle **2y forward via FVA at 1650bp vs spot 1925bp** — the 2y20y implied at 100% of realized vs 10y20y at 81%, with the 2y20y realizing 7% LESS but implied 31% MORE — the maturity-mismatch dislocation.
- **MBS series (2012–2026):** MBS = long 10y UST − short ~3y call struck 100 (contract) / behaviorally ~103–105; the spread decomposes into option cost + curve/forward moneyness + OAS — **the curve dominates vol** (Nov-2022: 175bp = 75 vol + 40 inversion + 60 OAS; "the greatest factor influencing mortgage rates is the inversion"); **"a high OAS when IVol is low only means you are selling IVol less cheaply"** — the OAS-vs-vol gate; the **Convexity Vortex** = strike concentration → discontinuous hedging demand ("own options struck near the Vortex, sell options further away — period"); 2026 re-awakening: index convexity +0.28 → −1.06, coupon ≥5% share 13% → 34%, MOVE at post-hike lows = "the wrong price."
- **"The Big O" (Aug-2023):** the when/if/how triad (duration/credit/convexity) as the allocation screen; sell the rich vector — near-par MBS as a bond covered-call at crisis vol ("do NOT buy MBS-index ETFs at avg price 85 — that's not a covered call; I like $97"); the MOVE 80/120 band rule and its honest failure mode ("at 80 it seemed crazy to buy; at 120 traders were under their desks").
- **"Leverage is NOT a four-letter word" (Jan-2023):** convexity = the *relative* (unbalanced) payoff profile; leverage = *absolute* amplification; the **8:1 package** (levered 7y futures strategy + long 20y-forward puts) = flat carry, flat duration, **long convexity in a parallel shift** — a retail-format version of the desk's convexity book.
- **"Wall Street Babylon" (Nov-2011):** vol "language" — normal vs lognormal is a regime choice (FASB-122/1995 turned bond vol normal); the zero-boundary "squish"; **implied-vs-realized is the clean tiebreaker: "implied vol is the rent paid to own market risk."**

### The RateLab / Musings layer (2006–2013, the desk-era mechanics)
- **"The Positive Carry Hedge" (Oct-2008; reprise Dec-2010) — the corpus's cleanest anomaly trade:** buy the **10y-expiry payer on the 10y tail** (K 7.25% @ 139bp in 2008; K 6.00% @ 433bp in 2010). Because inversion-note hedging inverted the long FORWARDS and Trust-Preferred supply inverted the VOL surface (1y10y 141nv vs 10y10y 83nv), the constant-OTM option price RISES with expiry — **a long option with negative time decay: negative duration + positive convexity + positive carry (+6.5bp/y; +26bp over 3y in the reprise)**. The 2008 vintage more than doubled (139 → ~475bp) with spot LOWER. The generalizable scan: walk the constant-moneyness option price along the expiry axis; wherever it rises with expiry, the surface+curve are handing out convexity with positive rent.
- **"Paying Nickels for Dimes" (Jan-2010):** the front-end 3:1 — buy the 1y1y ATM receiver at 47bp vs 132bp of roll-down, unhedged: "long convexity with positive carry, a truly anomalous yet valuable trading position." Coin-flip Fed = 2:1 risk paid 3:1.
- **"No Bad Bonds, Just Bad Prices" (Oct-2009):** the payer skew ladder (5y10y 6.25/7.75/9.50 zero-cost, delta≈0, gamma short only 2mm 1y10y-equivalents, +$400k/y carry) — sells CMS-cap-driven deep-OTM skew "marked into the land of the ridiculous" (9.50% strike @ 181nv vs a 1985–90 realized regime that rarely exceeded 140nv) without naked gamma; loss needs +400bp inside a year with no skew rotation. The structural cause: **CMS caps pay fixed $/bp so the dealer is short a string of strikes to +20%** — skew supply/demand is flow, not information.
- **"Yield Curve Options" (Dec-2006):** `spread vol = √(σ_A² + σ_B² − 2ρσ_Aσ_B)` — **curve options are the most levered vol purchase** (short correlation + long two vols); buy 2s10s CMS curve straddles/caps when realized correlation is at its ceiling (~98%+) — correlation can only fall. (The direct wrapper for "curve vol" that Citi's CMS module prices; our CMS gap in VI.)
- **"Another Fine Mess" (Jun-2008):** the exotics lesson — €13–20bn of EUR 30-2 daily-accrual inversion notes crossing strike forced every dealer into the same flattener + short-tail vol hedge (per 100mm note: receive 450mm 10y/pay 150mm 30y, sell 400mm 4y2y vs buy 75mm 4y30y straddles); a 9σ one-day 2s30s move. **Digitals flip all Greeks at strike; strike-concentration maps (the Vortex, Formosa B/E switches, CMS caps, mortgage stack) belong on the conditioning dashboard.**
- **"VAR: Rearview Mirror" (Oct-2009):** VAR limits are procyclical vol-supply — trailing windows rolling off Lehman would mechanically expand risk budgets and release vol sellers; **implied vol can be a risk-capacity phenomenon that decays on the data window, not on news** (a timing input for vol-selling entries).
- **"Largest Volatility Sale Ever" (Mar-2010):** the flow equivalence — **$100mm of new 30y MBS ≈ homeowners buying $50mm 3y10y straddles of vega; the Fed's $1.25T ≈ selling $625bn straddles** (~$40mn/day of theta) — net MBS issuance leads implied vol; USD/EUR vol ratio is the MBS loop (implied 1.58 vs realized 1.55).
- **"Implied Volatility: Fear" (Oct-2008) + "Babylon":** the MOVE's mechanics (constant 1m ATM OTR blended normal vol; band 80–125 ≈ 5–8bp/day; at 80 it "explodes, not rebounds"), the conversion ladder (normal = yield vol × yield; daily = annual/15.9), and the five reasons raw CBOT option IV history misleads (rolling expiries, basket duration, price-vol storage, notional-coupon change, CTD switches).
- **"Professional Javelin Catching" (Feb-2007):** the vega-floor call — implied/actual ratio fair value **107%** ("risk-adjusted fair value compensating the limited-gain/unlimited-loss nature of short convexity"); belly vol = 2y–5y expiries on 5y–10y tails (the MBS vega bucket); buy 3y10y/5y10y straddles outright, or vs gamma-weighted short 3m-6m (calendars) when the 3y10y−3m10y spread compresses to 7nv.
- **"The FVA" (Aug-2013, with full replication math):** FVA = forward straddle struck ATMF at the look date — pure vega until struck; replication: long 160k/nv 18m10y vanilla vs short 60k/nv 6m1y10y midcurve per 100k/nv FVA (variance additivity `(T₂−T₁)σ²_FVA = (T₂−T₀)σ²_van − (T₁−T₀)σ²_MC`; midcurve via the DV01-weighted spread-vol formula); the worked 6m1y10y: **spot 100nv purchasable 6m forward at 95nv**. The forward-vol discount/premium is its own wedge on the board (Citi's fwd-vol frontier prices the same object with calendars).

### What the framework takes from Bassman
The 3:1 roll-to-premium rule and "carry is theta in dollars" are ledger lines; the constant-moneyness-price-vs-expiry scan finds negative-theta options; the OAS-needs-a-vol-gate point generalizes to every spread instrument (a wide spread is only cheap if the embedded option is rich); spread-vol/correlation is the curve-vol wrapper; strike-concentration maps and VAR-window mechanics are conditioning inputs; FVAs are the clean vega instrument; the flow equivalences (MBS issuance = straddle flow, QE = vol sale) are the supply side of the vol ledger. And the maxims are risk policy: **"sizing is more important than entry level," "markets do not go from cheap to fair," "short convexity is found lurking near the scene of the crime."**

## II.7 Nordea (+ Astor Ridge) — the EUR carry-and-convexity screener culture

### The Nordea methodology (two eras, one convention)
- **Carry vs roll, resolved (their methodology note + the QSE dissection + their own trade cards):** carry = the horizon's net fixed-vs-floating accrual = forward − spot in running bp (upfront = (spot − fixing)·τ·df(h); running = upfront/DV01 of the residual forward swap — the note's printed formula omits the accrual τ, a 2× error if transcribed literally); roll-down = repricing the aged swap on an UNCHANGED spot curve. Both static-curve; under realized forwards the sum is zero. **Empirical confirmation on their own cards: every forward-starting structure prints carry = 0.0 with 100% in roll; the one spot structure (2s5s) splits 3.2 carry + 3.5 roll.**
- **The 2019 monitor (Vainikainen):** per curve point — 1y carry&roll (a) + **value of convexity (b)** = conv-adjusted carry, ÷ 36m realized vol = (c), plus level z (d), **J-score = (c)+(d)**, and **empirical in-the-money probabilities of the 1y-aged point vs 1/3/5/10y history**. The May-2019 grid: raw C&R peaks at 4y1y–5y2y (~21bp/y), goes negative past 12y, and **only the convexity add-on keeps the long end positive** — the quantitative basis of "pay the belly of 10/20/30y."
- **The convexity grid (Aug-2025, receiving, bp):** spot 1y 0.3 → spot 30y 6.7; but 30y-forward 1y = **13.1** — **the forward-start dimension dominates the tenor dimension** (a 30y-fwd 1y carries 2× the convexity of a spot 30y). This is the cleanest published table of "where convexity lives on the surface" and matches Attack68's per-PV01 ladder.
- **The vol ↔ curvature bridge:** the residual of 1y10y normal vol after regressing on the outright + curve PCA factors ≈ **the curvature factor itself** — Nordea's stated link between the vol surface and fly richness. Their drivers-of-change decomposition makes it operational: the popular R 5s10s30s "steepener-beta" fly earned +3bp from 10s30s and **+15bp from the curvature drop** — the fly was a short-vol trade wearing a curve label. (Factor-level confirmation of our fly finding, from the other direction: curvature co-moves with the vol residual as a FACTOR; an individual fly's incremental vega is still ~0.)
- **The 2024/25 screeners:** dashboard = rate | 50d range | carry+roll (annualized from the natural fixing horizon) | **convexity-adjusted (c+r)/vol** | 50d z | **PCA mispricing** (structure regressed on 3 factors, insignificant loadings dropped, misprice = par − fitted); cards add 252d correlations to 10y / 2y1y / 2s10s / 10s30s / 5s10s30s — **the correlation row is the factor-hygiene line our sizing framework demands.**

### The Nordea trades (with terms)
- **The "brain-dead trade" (Jan-2020):** *"systematically take advantage of the top of the forward curve, almost regardless of market conditions — receive 10y5y, pay 15y5y."* 1y rolls of 1y forwards peak ≈ +13.5bp at 6–7y forward start, cross zero ~15y, trough ~−5bp at 20y+ — **the EUR twin of our own finding that same-tenor forward curves are the harvest family (+6.63bp/y mean CR, 78% positive).** Evaluated on the 1y-aged structure (4y5y/14y5y) — same static-curve convention.
- Receive belly 1y2y/3y2y/5y2y 6s @ −8 (17-Jan-2024): carry/12m **79.2bp**, carry/vol 1.70, PCA ~25bp below; tgt −25+roll, stop +5 — "the ECB will cut, which takes away some but not all of the roll."
- Rec 20y5y/25y5y 6s @ −20 → re-entered @ −9 (12-Aug-2025) tgt −15 stop −7, 12m roll 3.4 — **explicitly the positive-convexity hedge for the steepener book** (corr +0.62 to 10s30s).
- Pay 5y7y/12y8y/20y10y 6s @ 45.5 (7-May-2025) tgt 60 stop 35, 1y roll 18 — the short-curvature/short-vol carry fly (corr +0.34 10s30s, −0.44 5s10s30s); paired vs Pay 9y3y/12y8y/25y5y (opposite correlation signs) — **carry flies sorted by their vol/curvature beta, the pairing discipline our framework adopts.**
- Rec 2y1y €STR @ 2.135% (30-Jul-2025) tgt 1.90 stop 2.25, 1y roll 30bp — "the ECB's medium term… the market-implied neutral rate"; later checked by crowding (high corr to 10s30s = a backdoor steepener) → rotate to **R 2s5s @ 24 (26-Sep-2025) tgt 19 stop 30, 12m C+R 6.6** with near-zero 10s30s correlation — **diversification against the consensus book, chosen off the correlation row.**
- Pay 3s6s tenor basis 5y5y (Mar-2020, "irrational": 6m fixing priced below 3m at long horizons); Euribor/€STR basis = universal tightener on the 2024 dashboard (swapped issuance).

### Astor Ridge Trade Radar (6-Mar-2022) — the contrast case
Bond-RV radar, not a carry screener: Bloomberg stdev/percentile stats on regression-weighted pairs (€STR 10y5y−15y5y at **5.36σ/99.65th pctile** — "stops in 10s vs 5s and 30s are causing this to be the best idiosyncratic fwd steepener"); an **anomaly-vs-fitted yield curve with a bond-age cap (≤2y) and coupon buckets**; deliberately tilted fly weights (10s15s20s with an imposed 5% steepener bias: +2.00/−0.90/−1.10); BTP basis trades into supply; **"10y invoice spreads have roll but not carry at the highs"** — the C&R split used as a veto; realized-vol regime checks before sizing (a candidate pair's daily vol doubling in a week = stand down). The lesson for the framework: **a dislocation radar needs a flow/stop-out story per signal, not just a percentile.**

---

# PART III — THE FRAMEWORKS COMPARED (how each shop defines "fair convexity")

| Shop / document | Fair-value engine | The comparison axis | The traded signal | What survives our evidence |
|---|---|---|---|---|
| **JPM long-end** (2017/2018) | Expected payoff of the aged package under the swaption-implied terminal distribution; equivalently curve-implied (breakeven) vol | curve-implied vol vs 1Yx30Y ATMF, bp/day; E(R) = carry + slide + ½σ²Γ | Sign of expected payoff → flattener vs straddle-funded reverse | The measure, yes; the signal is **degenerate on the long end** (curve cheaper than swaptions on 97%+ of days) — it's a permanently-on flattener, so treat as a *structural allocation*, not a timing rule; 5s/30s is the only two-sided pair and it's a slope trade |
| **Citi CA screen** (2016–23) | One-factor Ho-Lee on cap/floor vols; `CA = ½σ²·mean(T1²)·1e4` | CA-implied vol vs 3m realized pack vol; VsModel z | Sell CA at 2σ+ VsModel with roll and I/R support; hedge with fitted fly/strip proxies | The screen and identities reproduce to ~1bp; the mechanism (positioning) is real on Blues; the **trade fails our nulls at our costs**; the roll-jump theta must be decomposed |
| **Citi flatteners** (2019–23) | Daily breakeven from carry + repriced convexity | BE/RV ratio with two-sided thresholds (≤0.8 long gamma; ≥1.17 short) | Delta-hedged forward flatteners / steepeners, resize per 15–30bp | Engine mechanics reproduce (our strat3: convexity-dominated by factor attribution, 86–124% of P&L); ex-direction economics are thin but positive on the one positive-carry pair; **the resize mechanic is the correct gamma harvest** |
| **JPM EUR flies** (2019–21) | Rolling 6M two-factor (level+curve) regressions per fly | Residual z + R² + absolute residual | Enter 60%/1.5z/4bp, exit zero-cross/2SD/1M, beta-stability gate ≤3 | The **gating discipline** (R² floor, beta-stability, 1M horizon) is the best-tested entry machinery in the corpus; regime failures are named and match our regime findings |
| **Citi 2010 fly** | Regime-probability-weighted historical means + explicit convexity cost at assumed vol | Mispricing − convexity rent | Receive/pay belly with target = net of rent | The **rent-accounting line** ("28bp mispricing − 8bp convexity cost") is the correct fly P&L decomposition; regime conditioning is honest |
| **Burghardt/CME/Salomon basis** | Net basis = delivery option value; IRR − term repo = option premium | Option-adjusted BNoC vs 0; basis-implied vol vs option/swaption vol | Buy cheap options (nets ≈ 0), sell rich basis; wildcard timing rules | The taxonomy and OA identities are the framework; our V1 says the OA *model* adds ~nothing over the raw net-basis z at our data quality — **the option-adjustment matters most at the roll and in low-CF contracts** |
| **BofA basis** (2025) | Model ~1–1.5 ticks fair for TY delivery options | Net basis vs 0 (free-option detector) | Buy nets at ≤0, target +1 tick, stop −4 | Consistent with our "premium real but priced to cost" finding — the entry exists; the exit pays the spread |
| **RiskVal** | Full delivery-option engine (switch grid via PCA-scaled scenarios + wildcard induction + EOM), vol from listed ATM options | Option-adjusted net basis; R/C ASW-Z for the roll | Scenario CTD maps; calendar-roll rich/cheap | The practitioner implementation target: **distance-to-switch in σ is the moneyness of the basis option** — the number to put on the ledger |
| **Huggins-Schaller / Henrard / Rosen** | Gaussian-HJM financing bias exactly; SR3 has no payout convexity | Model CA vs market CA | (reference, not trades) | The model leg; front-quarter decay and matched-swap conventions are load-bearing |
| **PM (chat)** | PCA-weighted curve+fly package as synthetic vega | "long vega short gamma without a swaption" | 10y10y/20y10y + 1y 2s7s30s 5:1; 25bp resizes | Correct FORM (breakeven 4× realized vs the straddle alternative); timing fails mean-reversion at entry percentile; the fly leg's vega is a co-trend, not a hedge |

**Convergences across shops (the consensus core):**
1. Convexity value = ½σ²×(structure's T²-loading) everywhere — Ho-Lee CA, JPM's E(R) term, gilt fit 0.49σ², wildcard σ²-scaling. **Every wrapper's fair value is a variance claim.**
2. Everyone prices the wrapper against an option-market vol, then trades the *wedge* — never the level alone.
3. Everyone's entry is a 2σ-style dislocation **with a carry/roll support condition** (Citi roll + I/R; JPM carry-optimized pick; BofA flat-carry entry).
4. Everyone warns the same three ways: regressions break at regime change (ZLB annotations, beta-stability), costs eat multi-leg structures, and positioning can "engulf" model fair value.

---

# PART IV — THE UNIFIED GAMMA/THETA LEDGER, OPERATIONALIZED

## IV.1 The measurement recipes, per wrapper (all bp/day, all repriced not differentiated)

**W1 — Long-end forward curve (10y10y/15y10y, 15y5y/20y10y, 20Y/40Yx10Y, 30s/50s):**
- Γ$: reprice the DV01-neutral package on ±10/25/50/100bp parallel shifts of the forward curve (fit a quadratic through the profile); carry enters as the profile's level (`carry_ccy`), never via curve translate (which silently cancels on DV01-neutral packages).
- θ$: 1y carry+roll by repriced ageing (aged package on the rolled curve); split carry vs roll; forward-starting ⇒ carry ≈ 0, all roll.
- σ_BE = √(2|θ_daily|/Γ); compare to 1y realized vol of the LONGER forward rate (Citi convention) and to the co-expiry swaption ATMF (1Yx30Y for 1y horizon).
- vega$ (for cross-hedges): ∂V/∂σ ≈ σ·(T²-loading) — but empirically the tight pairs carry near-zero incremental vega (partial R² ≈ 0): **treat the curve package's "vega" as valuation-level exposure, not a hedgeable Greek**.
- Harvest mechanics: resize the longer leg to DV01-neutral at 15–30bp moves in the longer rate (25bp canonical; threshold-insensitive 15–30); each resize books ½Γ·(threshold)².
- Costs: 0.75–1bp entry, 0.3–0.4bp per resize/roll, one-way.

**W2 — SR3 CA (packs/bundles/outrights vs matched IMM Q/Q CME swap):**
- The mark: CA = pack rate − matched forward swap (identity-checked row by row); model = Ho-Lee on cap/floor (or listed SR3) vols; CA-implied vol by inversion; **quality gates before anything: strip depth, settle-vs-curve ≤ 2bp, EWMA-deviation diagnostic, magnitude (not sign) gate on Whites**.
- Γ$: the matched swap's DV01 drift per bp (the declining hedge ladder − flat 779-lot count); θ$: the deterministic components — front-quarter decay + the T1-slide (dCA/dt = −σ²·mean(T1)/1e4) + package carry (quote per 3m, Citi style).
- σ_BE: from short-CA rent vs Γ; σ_impl from the model inversion; σ_rlzd = 3m realized pack vol ex-roll-dates.
- Roll handling: blackout = union of both IMM clocks; roll_splice for any level series; t+1 fills.
- Costs: 0.25bp pack/bundle tick; 0.5bp 2y IMM swap b/o; realized hedged-CA round trip ~0.07bp (Citi 2017, at dealer access).

**W3 — Flies (spot + forward, −0.5/1/−0.5 quoted):**
- Role in the ledger: **priced-curvature venue** — carry/roll harvest and dislocation fade, NOT vol hedge.
- Γ$: reprice the fly on parallel shifts (small; the fly's real exposure is reshaping) + report the **convexity-cost line** at an assumed realized vol (Citi-2010 style: fly plan = expected reversion − convexity rent).
- θ$: 3m carry+roll (equal-weight and PCA-weighted versions); reversion drag; degeneracy gate (legs between same curve nodes realize <0.25bp/day and fake the rankings).
- Entry machinery: JPM 6M two-factor residual z with R² floor and beta-stability gate.
- Costs: ~3bp package b/o long-end forward flies (stress: untradeable); 1.5–2bp listed SR3 flies.

**W4 — UST futures basis:**
- The mark: **OA BNoC** = NB − (switch + wildcard + EOM at listed-option vol); distance-to-switch in bp and σ (the moneyness); IRR vs CTD term repo as the annualized mirror (avoid into the roll).
- Γ$: from the delivery-option model (reprice the basket over the switch grid; the DV01 gap across cusps is the gamma); the wildcard's gamma is the after-hours tail (1−CF)·notional per bp of post-close move.
- θ$: gross-basis daily drop = CTD carry; wildcard theta = the day's carry surrendered by waiting; option decay to zero into expiry.
- σ_impl: the vol that reprices net basis through the delivery model; compare against (a) the CTD-matched futures-option vol (board), (b) the expiry/tail-matched swaption — the **basis triangle**; the JPM package prints the first leg daily ("Volat Implied by the Basis" vs "Opt. IVol").
- Costs: CTD execution median 0.37bp inside the screen but 95th-pctile 12.4bp on >$50mm; futures 1/4-tick; the funding line (term repo attainability, balance-sheet rent, year-end withdrawal).

**W5 — Options (the explicit venues):**
- The panel of II.5; minimum rebuild for the ledger: ATMF grids (swaption cube store), listed SR3/UST option vols (qs_timeseries route, real contracts not CM interpolations), implied/realized with intraday variant, 25d skew z, board-vs-CTD-matched-swaption table.
- Everything quoted normal bp/yr internally ÷√252 to bp/day at the ledger boundary, with the 0.5–40bp/day plausibility guard.

## IV.2 The cross-venue screens (what the desk actually looks at each morning)

1. **The breakeven board:** every wrapper's σ_BE/σ_rlzd and σ_impl/σ_rlzd, one table, bp/day. Two-sided thresholds per the published franchises (0.8 / 1.17–1.38 for curve; 2σ VsModel + I/R ≥ 1.5 for CA; OA-BNoC ≤ 0 for basis longs).
2. **The wedge matrix:** pairwise implied-vol spreads between wrappers of the SAME underlying risk — curve vs swaption (long end), CA vs cap/floor (STIR), basis vs board vs swaption (CTD point), listed vs OTC (SFR vs swaption at matched sector). Fade 2σ wedges ONLY where the two legs' change-correlation is demonstrated at the trade horizon (our w3 lesson: STIR vs long-end curve-implied vol change-corr ≤ 0.11 — not a pair).
3. **The rent ranking:** risk-adjusted carry rac = carry/(vol·√252) net of reversion drag, curve+fly universe (1,075 structures in-house); forward-tenor curves are the harvest family (+6.63bp/y mean CR, 78% positive), forward flies are the paying family.
4. **The conditioning dashboard:** CFTC TFF net %OI (3-day lag), CA−model as the daily positioning proxy, CME-LCH basis level, skew percentile, callable/Formosa vega supply calendar, convexity-hedger thresholds (the JPM maps), OI/roll calendar (First Position Day, CTD switch distances).
5. **The event/structural registry:** discounting/CCP breaks, basket-definition events, IMM-FOMC collisions (22/33), year-turn Decembers, auction/WI rolls.

## IV.3 Sizing and hedging rules (the ones the evidence supports)

1. **Size gamma legs off the once-evaluated identity** ν = σ·(T²-loading) — never off a time-integral of a frozen ATM gamma profile (2× too big) and never off a lattice/model sensitivity without the realized-vs-predicted regression through the origin (5.7× episode).
2. **Variance, not vol:** P&L is linear in (σ_r² − σ_i²); a vol-linear hedge ratio set at one σ is a tangent (the 10c/30c wedge). Restate hedges as σ moves.
3. **Hedge ratios at the holding horizon** (β climbs 0.61→1.22 from 1d→15d on tick-quantised marks); prefer flat 1:1 when the horizon-fitted ratio is near 1.
4. **Factor hygiene:** DV01-neutrality leaves humped-PC1 leakage — PC1-hedge the tight forward pairs (`pca_rv.curve_weights(neutralize=("PC1",))`); never book wide-tenor pairs (5s30s-type) as convexity; walk-forward-vs-full-sample PCA gap = trading the estimator.
5. **Rehedge frequency is part of sizing:** half the move locks a quarter of the P&L; more frequent rehedging needs a larger total path per unit cost. 25bp threshold is the published optimum at 0.3bp swap costs; recompute if costs differ.
6. **Fixed vs floating hedge vol:** fixed-vol delta hedging makes terminal P&L a function of the spot path only (kills the vega×dσ term) at the cost of off-market marks; floating takes vega MTM + vanna and adds IV-path dependence. Expected P&L is invariant — it's a variance-of-outcome choice; decide per book and state it.
7. **Gamma-neutral ≠ stays gamma-neutral** (Bergomi skew-arb warning): third derivatives re-load the neutralized order under stress; and 0.2 vol points of bid/offer per leg wiped that strategy's P&L — cost the rebalances, not just the entry.

## IV.4 Statistical acceptance (before any of this trades)

Pre-registered grids with cell counts declared; deflated Sharpe at n_eff on both clocks; matched-rarity placebos for boundary/threshold signals; lag placebos (+20bd must kill a timing signal); engine certification of panel P&L (≥0.99 daily-change corr or the panel number is not quotable); negative controls that must fail (annual-frequency matched swap must re-introduce ~4bp; Hull T1T2 must NOT match Citi tables; reversed roll column must break the identity); cost curves 0×/0.5×/1×/2× with per-leg break-evens. **A negative result is a result** — the corpus's banks never publish their dead grids; we have ours and they are the moat.

---

# PART V — THE MASTER TRADE TABLE (every published ticket with terms)

| # | Date | Shop | Trade | Entry | Exit / target / stop | Result |
|---|---|---|---|---|---|---|
| 1 | 20-Dec-2010 | Citi | Receive belly 1y-fwd 5s10s30s ($180/200/50mm) | 48bp fly (98th pctile; fair 19) | tgt 20bp, stop 10bp | — |
| 1b | Dec-2006 | Bassman/ML | 2s10s CMS curve straddles/caps (1y/2y/5y) | straddles 30/38/48bp; caps 15/19/24bp | multi-year | — |
| 1c | Feb-2007 | Bassman/ML | Buy 3y10y/5y10y vega (outright, vs short gamma, or 6m fwd) | 73.0/72.7nv (all-time lows; I/A at 107% fair) | ≥6m hold | — |
| 1d | 31-Oct-2008 | Bassman/ML | **Positive Carry Hedge**: buy 10y-expiry payer 10y tail K 7.25% | 139bp; rolls UP to 171 over 5y (+6.5bp/y) | 2–3y macro horizon | 2009 mark ~475bp (>2×) |
| 1e | Oct-2009 | Bassman/ML | 5y10y payer skew ladder 6.25/7.75/9.50 | zero cost; +$400k/y carry; short 30mm vega | skew rotation | — |
| 1f | Jan-2010 | Bassman/ML | Buy 1y1y ATM receiver UNHEDGED | 47bp vs 132bp rolldown (2.8:1) | 1y expiry | — |
| 1g | Dec-2010 | Bassman/BofA | Positive Carry Hedge reprise: 10y-expiry payer K 6.00% | 433bp; +26bp carry over 3y | 2–3y | — |
| 2 | Sep-2012 | Bassman/CS | Buy 3m10y straddle 2m fwd (FVA) | ~320bp (+8% over spot) | into election look date | — |
| 3 | Aug-2013 | Bassman/CS | Buy 8y20y straddle 2y fwd (FVA) | 1650bp vs spot 1925 | vega trade | — |
| 4 | Sep-2013 | Bassman/CS | Calendar midcurve payer spread (2y→8y-20y vs 10y→20y, K 4.75%) | pay 400bp | +160bp yr-1 roll | — |
| 5 | Apr-2013 | Bassman/CS | 5y5y payer skew ladder 3.65/4.50/5.50 | zero cost, +carry | exit on skew compression | — |
| 6 | Jul-2014 | Bassman | Buy 1y2y receiver K 1.45% | 56bp vs 82bp rolldown (2.88×) | hold 1y | — |
| 7 | 4-Feb-2015 | Citi | Buy May-30 sector vs 10y & 30y (1:2:1) | 3.9σ cheap on ASW | normalization | — |
| 8 | 17-Jul-2015 | Citi | Long $100mm May37 basis vs 911 USZ5 | 4.2 ticks ($130k; swaption equiv $187k) | rally play | — |
| 9 | 12-Dec-2016+ | Citi | Sell Golds CA (screen) | 3bp/1σ rich | — | — |
| 10 | 9-Feb-2017 | Citi | Sell $200k DV01 Blues CA + pay belly 2s5s10s fly | 8.8bp / fly −18.2bp | $600k / −$350k | closed 6-Jun @ 6.6bp: **+$500k net** |
| 11 | 3-May-2017 | JPM | Buy H9/M9 EDs vs pay CME FRAs (CA + CCP basis) | CAs ~L+300 implied funding | pull-to-expiry ~2y | — |
| 12 | 15-May/6-Jun-2017 | Citi | Sell $300k DV01 Greens CA + ED5/ED9 steepener (−1/1.18) | 4.3–4.5bp | $450k / −$225k | closed 8-Aug @ 2.65bp: **+$475.5k net**; hedge off 13-Jul +$70.5k |
| 13 | 5-Jan-2018 | Citi | Sell $100k DV01 Blues CA + ED6/ED16 (0.74/−1) | 6.5bp; carry +$140k/3m | — | — |
| 14 | Mar-2018 | Citi | Sell 3Mx10Y vs buy 2Yx10Y straddles, delta-hedged | ratio rich on supply model | — | — |
| 15 | 18-Apr-2018 | Citi | Sell Blues CA outright | 7.2bp mid, 2σ | — | — |
| 16 | May-2018 | JPM | Deliver FVM8 late / TUM8 early (wildcard rules) | option 0.5–1 tick vs bleed | breakevens −3.5 / −0.75 ticks | — |
| 17 | Aug-2018 | JPM | Sell 30Y MM spreads vs 50% 10s/30s flattener | 4.54bp | — | closed 9/14/18 +1.0bp |
| 18 | Jan-2019 | Citi | Vega tenor fly: sell 3y2y / buy 3y10y / sell 3y30y | +$240k take-in; +0.75nv/1y carry | — | — |
| 19 | 9-May-2019 | Citi | **15y5y/20y10y delta-hedged flattener $50k DV01** | −11.8bp; BE/RV 0.42 | resize per 20bp; exit at BE/RV 0.8 | closed 5-Dec-2019 @ −12.5bp: **+$155k net** (+$187k gross) |
| 20 | May-2019 | JPM | Sell current 5s vs OIS (bank-convexity thesis) | 23.3bp matched | — | — |
| 21 | Aug-2019 | JPM | Pay 15Yx5Y vs receive 35Yx5Y (carry-optimized flattener) | −35.7bp | — | closed 1/10/20: **+7.9bp** |
| 22 | Aug-2019 | JPM | Conditional 10s/20s/30s payer-fly widener (25d 6M) | premium-neutral | selloff play | — |
| 23 | Sep-2019 | Citi | 1y 2s10s vs 6m 5s10s straddle switch (β 1.7) | 34 vs 21.5nv | watch list | — |
| 24 | Jan-2020 | Citi | **GBP 15y10y/25y10y delta-hedged flattener $50k DV01** | −11.2bp, carry +0.5bp/y ("free convexity") | resize per 25bp | closed 26-Mar-2020: **+£445k** (115 curve + 330 convexity) |
| 25 | Jan-2020 | JPM | Receive TYH0 invoice spreads | −5.95bp (3–5bp too wide) | — | — |
| 26 | Feb-2020 | JPM | Receive 30Yx10Y vs pay 10Yx10Y (Formosa supply) | −39bp | — | +3.0bp at print |
| 27 | Feb-2020 | Citi | Receive 20y10y vs 10y10y & 30y10y 1x2x1 | 16bp (efficient frontier) | — | closed 15-Jun-2020 @ 10bp: **+$360k** (3bp pkg b/o) |
| 28 | Mar-2020 | JPM | Long front TY basis unlevered (implied repo > CP) | crisis dislocation | to delivery | — |
| 29 | 11-Jun-2021 | Citi | Sell $100k DV01 Blues CA (EDM4-H5) | 7.9bp; carry +1.2bp/3m | tgt 4bp / stop 3bp | 5.9bp within 10 days |
| 30 | Mar-2022 | Citi | Receive EUR 5s10s30s 3m-fwd fly | 41bp | tgt 20, stop 50 | — |
| 31 | Nov-2022 | Bassman | Long near-par MBS vs UST/IG (+mREITs, + payer hedge) | 175bp spread (75 vol + 40 curve + 60 OAS) | steepening play | — |
| 32 | Jan-2023 | Bassman | 8:1 futures strategy + rate-hedge package | 7y vs fwd-20y −32bp | flat carry, long convexity | — |
| 33 | 17-Feb-2023 | Citi | Sell $100k DV01 Blues CA (SFRH6-Z6 vs $1.17bn CME) | 12.7bp; carry +1.5bp/3m | tgt 4bp / stop 2.5bp | — |
| 34 | Feb-2023 | Citi | SOFR micro-flatteners 6th/7th contract; post-pause 8th–10th steepen | Fig-12 cycle table | pause timing | — |
| 35 | 12-Jun-2023 | Citi | Long-dated fwd steepeners (10y10y/15y15s, 10y10y/20y5y) | BE/RV 1.17 / 1.38 | after FOMC | — |
| 36 | Jan-2024 | Bassman | Near-par MBS as the paid-to-wait steepener | FN 5.5 @ 99.65, +143bp | curve rotation | — |
| 37 | 10-Apr-2025 | BofA | Buy T 4.375 1/32 basis vs TYM5 (CF-weighted) | net 0 ticks (fair ~1) | tgt +1 / stop −4 | — |
| 38 | May-2026 | Bassman | Own rate vol vs re-convexifying MBS stack | MOVE at post-hike lows | multi-strike at prepay inflections | — |
| 39 | Jan-2026 | PM chat | 10y10y/20y10y flattener + 1y 2s7s30s 5:1, 25bp resizes | "strikeless vol" | resize = exit | (our verdict: form yes, timing no) |
| 40 | Jan-2020 | Nordea | "Brain-dead": rec 10y5y / pay 15y5y (top of fwd curve) | rolls peak +13.5bp/y at 6–7y fwd | systematic | — |
| 41 | 17-Jan-2024 | Nordea | Receive belly 1y2y/3y2y/5y2y 6s | −8bp; carry 79.2bp/12m, c/vol 1.70 | tgt −25+roll / stop +5 | — |
| 42 | 7-May-2025 | Nordea | Pay 5y7y/12y8y/20y10y 6s (short-curvature carry fly) | 45.5bp; 1y roll 18bp | tgt 60 / stop 35 | performing (Aug-25) |
| 43 | 12-Aug-2025 | Nordea | Rec 20y5y/25y5y 6s (convexity hedge for steepeners) | −9bp; 12m roll 3.4bp | tgt −15 / stop −7 | −13.2 by Sep-25 ("doing its job") |
| 44 | 26-Sep-2025 | Nordea | Receive 2s5s 6s (anti-consensus, near-zero 10s30s corr) | 24bp; 12m C+R 6.6bp | tgt 19 / stop 30 | — |
| 45 | 6-Mar-2022 | Astor Ridge | €STR 10s15s20s rec-belly (5% steepener tilt) + BTP Jul-28 vs IKM2 basis | fly 17.8bp; fwd spread 5.36σ | flow/supply driven | — |

*(Plus the standing screens: Citi CA table 2016–2023 vintages; Citi/JPM fly RV appendices; JPM futures-roll positioning regressions (FV R² 0.64, WN R² 0.83); B&B synthetic-note program +61bp/yr 19/21 quarters; B&B OAB vol-arb 297-trade sim +4.9 ticks avg.)*

---

# PART VI — WHAT TO BUILD (wiring the ledger into ARBS)

**Already built and verified in-house (reuse, don't rebuild):** the CA kernel (`RVUtils/ConvexityRV`: holee, payoff_profile, matched_forward_swap_rate, ca_diagnostics, rac_signal, gv_* modules); SwaptionCubeStore (7y USD ATMF); STIRFutureQuery/MDP with settle warms + intraday depth-20; USTFutureBasis stack (basket/CF/gross basis/IRR; wildcard model in `RVUtils/BasisVsVol/wildcard.py`; V2's exchange-vs-OTC vol tables); CurveFlyScreener (1,075 structures, rac_net); FlyVsVol; the QDB engine + trade_dashboard; JPM package parser (1,716 days of vendor vol/basis/CTD panels — the independent grader).

**The gap list (ranked by what the corpus says matters):**
1. **The breakeven board** (IV.2.1) — one daily table, all wrappers, bp/day. Most parts exist; the join does not.
2. **Option-adjusted basis line** — switch (two-bond Bachelier exists; extend toward basket) + wildcard (exists) + EOM (missing; RiskVal spec above) + **term repo** (the missing input — gap #1 from the audit; JPM package's per-issue repo is the stopgap).
3. **Board-vs-swaption panel** refresh (the stale ingest) + the JPM-package "Volat Implied by the Basis" column as the third leg.
4. **CMS curve-vol / implied-correlation** feed (curve caps are the direct long-vol-on-slope wrapper; nothing in-house prices them).
5. **Conditioning dashboard** (CFTC TFF lag-3, CA−model, CCP basis, skew pctile, Formosa calendar — all sources identified in-house).
6. **The two-book structure** (harvest + dislocation) with the IV.3 sizing rules and IV.4 acceptance gates as code, not culture.

# APPENDIX — COVERAGE LEDGER

Every file in the six directories maps to one of: the four flagships (read directly, full), the corpus1/2/3 digests (`docs/convexityrv/research/*`, 88/88 unique docs verified covered by md5 + title match), the seven extraction agents of this exercise (Bassman ×25, RateLab/Musings/FVA/QSE ×17, basis research ×8, Burghardt-Belton, practitioner refs ×16, basis QSE ×15, Nordea ×10), or duplicate copies of the above ("(1)" files, print duplicates: print(4)=(12)=(16), print(5)=(7)=(15)=(18), print(6)=(14), Rates_Vol_Lab fwd-steepener (1)). Five QSE hedging threads (fixed/floating IV ×2, Bergomi skew, continuous delta hedge, delta-hedge value) were double-extracted — corpus3 agent1 AND this exercise's agent B — and the two extractions are consistent. Identified but intentionally summarized rather than fully extracted: the three reference books (Huggins-Schaller, Aikin, Burghardt-Belton — framework chapters extracted, narrative chapters skimmed), the Barclays Abate money-market primer (no convexity content), and pure-boilerplate disclosure pages.
