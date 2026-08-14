## 1. pm_bbgchat.txt.md — FULL VERBATIM QUOTE

```
Peter Findley <pfindley@gmail.com>
Jan 21, 2026, 11:24 AM
to me

decent enough breakdown of how this works to link linear curve to vega backend

11:00:14 Any view $10y10y vs 20y10y
PETER FINDLEY
11:12:20 Not sure
11:12:31 There is good size trading in 10y20y and 20y10y vega right now from custys
11:12:49 Trying to get a signal from it ; for choice I like owning vega which means rcving 20y10y
11:13:20 10y10y 20y10y flatteners - that's like being short 20s on the curve, against that rcv 1y fwd 2-7-30;  soemthing tlike that
MARK DONLON
11:14:15 Just arrived in nyc office will take a look
PHILIPPE KATZ
11:14:20 Sorry delta
11:14:22 curve
11:14:26 Not swaptions
PETER FINDLEY
11:14:44 Yeah I agree .. 10y10y 20y10y curve flattener and rcv 1y 2-7-30 as a combo
11:14:50 In 5:1 weights
11:15:06 That position leaves you long vega short gamma without having to trade a swaption
PHILIPPE KATZ
11:15:21 Isn't 101 v 2010 super flat already
PETER FINDLEY
11:15:40 yes
PHILIPPE KATZ
11:15:44 Put steepened a bit
11:15:56 Wh did u get the weights from
PETER FINDLEY
11:16:29 Rough PCA weight
11:16:42 If you translate the gross buckets of 20s into a 2-7-30 trade
11:17:10 You can actually delta hedge 20y10y if it moves around
11:17:15 If it doesn't move you earn carry on 2-7-30
11:17:28 You *need* to implement the hedges, this means doing 5% delta hedges at the wings
PHILIPPE KATZ
11:17:42 We liekd the 1y 2s5s10s or variations
11:17:46 tehreof
11:17:50 Can look at the pCA
PETER FINDLEY
11:17:51 You just recalc the delta on the trades you do every 25 bp and then resize the notinoals back to be dv01 neutral
11:17:55 Everytime you will be 'taking profit'
11:18:16 That's how you delta hedge and treat 10y10y 20y10y as a vol trade - I think of it as strikeless vol
11:18:46 Depending on how you do the resize you can delta hedge it to 0 risk (always decrease) or keep it constant - so the delta hedging eventually is also an exit if you feel like it
11:19:33 Mechanical process. Do trade with client. Wait 2 months/25 bp, rerun their exact notinoals and strikes, calc the new notinoals required to be dv01 neutral, you will probably get some 2-10mm adjustment to one of the legs, and always at a gain relative to your initial K
11:20:44 In Japan right now those delta hedge trades are pretty valuable, you execute them almost everyday
11:21:20 1010 2010 in Japan is flattening, honestly, that's probably the better trade in the long run
11:21:44 1010 2010 in Japan at these levels you can back book and look back in 2027, 2028, 2029 and think 'wow, what were they thinking, im *still* making free gamma'
11:21:54 Its like when people sold 10y10y gbp vol at 2 norms a day
11:22:05 In 3 years.. That's still 7y10y.
11:22:37 You might be panicking now, but 10y10y 20y10y has absolutely nothing to do with fiscal policy over the span of multiple years and is completely a carry vega trade
11:23:28 I like looking at 15y5y 20y10y as the pure vega expression that has a bit less factor exposure than 1010 2010 (doesn't require 1y 2730); also, tldr, that was way too long. tldr

Strikeless Vol: The 20y10y Vega Trade

The core insight: 10y10y vs 20y10y curve flatteners replicate long vega, short gamma exposure without touching swaptions.

The Structure

Receive 20y10y against paying 10y10y (curve flattener) paired with receiving 1y forward 2-7-30 butterfly. Ratio: 5:1 by rough PCA weights.

Why it works: The flattener is synthetically short 20s. Translating those gross 20s buckets into a 2-7-30 trade gives you a delta hedge that earns carry when nothing happens.

The Mechanical Edge

Every 25bp move, recalculate DV01 on your trades. Resize notionals back to neutral. Each adjustment books profit versus initial entry - you're systematically harvesting convexity.

This creates two exit paths:

Always decrease notionals → position naturally winds down, delta hedging becomes your exit
Keep constant → maintain exposure, bank the hedge gains
In Japan right now, these delta hedge trades execute almost daily. That's real PnL, not theoretical.

The Long Game

10y10y vs 20y10y has nothing to do with fiscal policy over multi-year horizons. It's pure carry vega. At current Japan levels, you back-book this and in 2027-2029 you're still collecting free gamma - same dynamic as when desks sold 10y10y GBP vol at 2 norms/day. Three years later that's still 7y10y duration.

Cleaner Expression

15y5y vs 20y10y isolates the vega with less factor exposure. Doesn't require the 1y 2-7-30 hedge leg. Purer trade, fewer moving parts.

meta prompt
'verify make sure to use greeks correctly to determine sizes. no guesses, thats why we have rateslib. you need to just calculate the dv01 parallel shift the curve and keep reweighting it each time you need to verify the mechanic peter identified first , double check . it does not seem like you USED rates lib whats wrong with the skill. be critical both fix the process and in doing so fix the skill. how did you calculate your vol on WHAT and everything needs ot be in terms of daily vol'
```

**Practitioner intent (what the PM actually wants traded), decoded:**
- **Primary structure:** pay 10y10y / receive 20y10y forward-swap curve flattener (delta/cash curve, explicitly **NOT swaptions** — Katz corrects this at 11:14:20-26), paired with **receive 1y-forward 2s7s30s belly**, ratio **5:1** from rough PCA. Net position = long vega, short gamma, no swaption traded.
- **Mechanic to verify:** every 25bp parallel move, re-run the *original* notionals/strikes through the curve, recompute DV01, resize to DV01-neutral. The resize is always a gain vs initial entry K; typical adjustment 2-10mm on one leg. Hedge at the wings in 5% delta increments. Choose "always decrease" (self-liquidating, → 0 risk) or "hold constant" (bank hedge gains, keep exposure).
- **Cleaner alternative he prefers:** **15y5y/20y10y** — pure vega, less factor exposure, no 1y 2s7s30s hedge leg needed.
- **Cross-market:** same trade in JPY is the higher-conviction long-run version.
- **Meta prompt = the actual build spec:** use rateslib for real DV01s (no guessed weights), parallel-shift the curve, reweight at each step, verify Peter's mechanic first, and express **all vol in daily vol terms**.

---

## 2. print (N) file map

| File | Title | Bank / Product | Date | Topic | Relevance to convexity RV |
|---|---|---|---|---|---|
| `print.pdf.md` | **European Rates Weekly — "A narrative shift looms"** | Citi Research (Searle, Harju, Appeddu, Bansal, Gaveau, Dutta, Sawant) | 18 Mar 2022 | EUR/GBP weekly; € swaps section recommends **receive 3m-fwd 5s10s30s** to buy cheapened convexity as € 10s30s sits at 13y inversion lows | **High.** EUR analog of the belly-receive fly; introduces **vol-normalized roll-down** (roll-down per bpv of 3m10y ATMF vol) as the RV metric, and the gamma-vol ↔ fly beta regression. Trade spec: rec 5s10s30s 3mF @41bp, tgt 20, stop 50 |
| `print (1).pdf.md` | **US Rates Weekly — "Eat, pay, spend"** | Citi Research (Mathai, Bikbov, Kang, Williams, S. Li) | 27 Mar 2020 | COVID weekly; Vol section flags **delta-hedged 15y5y/20y10y USD flatteners as "a cheap convexity buy"** | **Highest.** This is literally the chat's "cleaner expression" (15y5y/20y10y). Contains the full cross-currency screen (USD/EUR/GBP) with curve level, 1y/3y/since-2000 z-scores, 1y carry, **daily breakeven**, 1y realized vol, and **BE/realized-vol ratio**. Also carries the live `Sell beta-adj. 10y10y/20y10y/30y10y butterfly` (open 16bp, mkt 20bp, P&L -53K) — the exact trade the Citi Alert later unwinds |
| `print (2).pdf.md` | **US Rates Weekly — "Fixing the plumbing"** | Citi Research (Mathai, Bikbov, Kang, Williams, S. Li) | 30 Sep 2019 | Repocalypse weekly; Vol section = **delta-hedged 15y10y/25y10y GBP flatteners as cheap convexity**, plus 1y 2s10s / 6m 5s10s straddle switch | **High.** Weekly-length version of print (3). Gives the **live USD trade state**: $50K DV01 15y5y/20y10y delta-hedged at each 20bp, opened 9 May 2019 @ -11.8bp, P&L +$59-70K purely from realized vol. Straddle switch sized $1bn 1y 2s10s vs $1.7bn 6m 5s10s |
| `print (3).pdf.md` | **US Rates Vol Lab — "Buying vol for less"** (CORRECTION issue) | Citi Research (Bikbov, Williams) | 25 Sep 2019 | Standalone vol-lab note behind print (2)'s vol section | **Highest (methodology).** The canonical write-up of *"delta-hedge a long-dated forward-swap flattener at every 20-25bp move"* as a systematic long-convexity strategy, plus the **daily-breakeven / realized-daily-vol** cheapness screen across USD, EUR, GBP, CAD, JPY. Also has the ED convexity-adjustment (Ho-Lee vs cap/floor) table and curve-vol PCA |
| `print (4).pdf.md` | **North America Rates Trade Idea — "Sell Blues convexity adjustments, hedged"** | Citi Research (Bikbov, Williams) | 9 Feb 2017 | Sell ED Blues-pack convexity adjustment, hedge with short 2s5s10s swap fly | **Medium.** Different convexity (futures CA, not curve convexity), but it is the cleanest worked example of **using a DV01-weighted fly as a regression-derived proxy hedge for a convexity/vol exposure** — directly analogous to using 2s7s30s as the delta hedge for 10y10y/20y10y |
| `print (5).pdf.md` | **US Rates Weekly — "Swearing in huge expectations"** | Citi Research (Mathai, Bikbov, Kang, Williams) | 13 Jan 2017 | §Swaps "Smart convexity sells" = long form of print (4); §Special Topic = the standalone `Flatter_skew…` PDF; §Vol = Formosa | **Medium.** Source of the 2s5s10s regression hedge weights and the ED CA valuation framework. Its Special Topic is byte-identical in content to `North_America_Rates_Focus_Flatter_skew…pdf.md` |
| `print (6).pdf.md` | **US Rates Vol Lab — "Buy long expiries"** | Citi Research (Bikbov, Williams) | 17 Jan 2017 | Formosa NC5 rule → buy delta-hedged 10y10y straddles; "Optimal convexity sells" (Blues CA + 2s5s10s); 3m 2s3s5s conditional receiver flies | **Medium-high.** Supplies the **vol-adjusted roll-down carry ladder for long expiries** (3y/5y/7y/10y × 10y/20y/30y tails) — the direct swaption benchmark against which the chat's "strikeless vol" flattener should be priced. 10y10y is the cheapest point by vol-adj. rolldown (0.38, 1y ZS -1.4, 3y ZS -2.02) |
| `print (7).pdf.md` | — | — | — | — | **Exact byte-for-byte duplicate of `print (5).pdf.md`** (md5 `1df2136fbc13921d31f269b399cb166a` for both). Ignore |

Duplication also runs across the named PDFs: `North_America_Rates_Focus_Flatter_skew…` = §Special Topic of print (5)/(7); `Alert…Taking profits on long end butterfly` closes the open position tracked in print (1).

---

## 3. Spec-level convexity content, per document

### print (3) — US Rates Vol Lab, 25 Sep 2019 — **the core methodology**
- **Claim:** convexity embedded in long-dated forward-swap flatteners (15y5y/20y10y, 15y10y/25y10y, 15y5y/25y10y) "is typically cheap for structural reasons", so **systematically delta-hedging the flattener at each 20-25bp move in rates has been historically profitable**. This is the identical mechanic Findley describes, published by Citi 6+ years earlier.
- **Live trade:** $50K DV01 USD 15y5y/20y10y flattener, delta-hedged at each **20bp** move. Profitable purely on realized vol even after the curve moved against the directional leg.
- **Cheapness screen — implement this:** for each candidate curve pair, compute
  - curve level (bp), 1y / 3y / since-2000 z-scores;
  - **1y carry (bp)** — note zero is coded as *positive* carry;
  - **daily breakeven (bp)** = "the move in rates that yields a convexity gain offsetting the negative daily roll";
  - **1y realized daily vol (bp)**;
  - **BE / realized-vol ratio — smaller = cheaper embedded convexity = more attractive.**
  This is the metric that answers the meta prompt's "everything needs to be in terms of daily vol": convexity gain per day vs daily roll cost, both benchmarked to daily realized vol.
- **Universe screened (15 pairs × 5 currencies):** 10y10y/{15y15y, 20y5y, 20y10y, 20y15y, 25y5y, 25y10y}, 15y5y/{20y5y, 20y10y, 20y15y, 25y5y, 25y10y}, 15y10y/{25y5y, 25y10y}, 20y5y/{25y5y, 25y10y}. USD, EUR, GBP, CAD, JPY.
- **USD reference numbers (24 Sep 2019):** 10y10y/20y10y curve -7.50bp, 1y ZS 2.16, 1y carry -3.83bp, daily BE 3.84bp, 1y realized vol 3.82bp, **BE/vol 1.01**. 15y5y/20y10y curve -10.24bp, carry -2.37bp, daily BE 3.55bp, realized 3.82bp, **BE/vol 0.93** — i.e. the chat's "cleaner expression" screened cheaper than the headline pair on the exact same day.
- **GBP reference:** 15y10y/25y10y curve -6.34bp at all-time-high steepness, **positive carry +0.58bp/yr**, daily BE 0.00 → **BE/vol 0.00** ⇒ "effectively a free long convexity buy." Structural driver: ALM/pension receiving richening the 20y sector.
- **Curve-vol RV:** 1y 2s10s / 6m 5s10s straddle switch as synthetic forward curve vol; 6m-fwd-6m 2s10s vol computed as `sqrt(2*vol(1y 2s10s)^2 - (beta*vol(6m 5s10s))^2)` with conservative beta 1.7. Curve-vol rich/cheap from **PCA on curve vols, 2 PCs, 3y of data** (relative value only, by design).

### print (1) — US Rates Weekly, 27 Mar 2020
- Same screen re-run in the COVID dislocation. **15y5y/20y10y USD** steepened to the top of its historical range on **variable-annuity receiving concentrated in the 20y sector** — "slightly positive carry and positive convexity… effectively a free convexity buy."
- **USD 26 Mar 2020 numbers:** 15y5y/20y10y curve -5.21bp, 1y ZS 4.21, 3y ZS 3.58, **1y carry +0.11bp**, **daily BE 0.00**, 1y realized vol 6.40bp, **BE/vol 0.00**. Compare 10y10y/20y10y: -6.86bp, carry -0.24bp, BE 0.98bp, realized 6.40bp, BE/vol 0.15.
- Explicit sequencing precedent for the delta-hedged flattener book: GBP 15y10y/25y10y entered 17 Jan 2020 @ -11.0, exited 26 Mar 2020 @ -19.0 for **+$542K on $500K target**; USD 15y5y/20y10y ran 8 May 2019 → 5 Dec 2019, -12 → -13, **+$155K**. Note the GBP winner made money while the *curve* moved 8bp — the P&L is hedge-harvest, not direction.
- Notes 10y bid/offer ~0.6bp, "which makes it costly to delta-hedge frequently" — a real constraint on the 25bp re-hedge cadence.
- Tracks the open `Sell beta-adjusted 10y10y/20y10y/30y10y butterfly`: opened 21 Feb 2020 @ **16bp**, marked 20bp, P&L **-$53K**, target $500K. Rationale: "using flies to fade the ultra-long flattening in the swaps curve looks attractive **due to the smaller convexity risks**"; risk = Formosa issuance flattening 30s40s.

### print (2) — US Rates Weekly, 30 Sep 2019
- Weekly restatement of print (3). Adds the P&L attribution: USD 15y5y/20y10y opened @ -11.8bp, marked -10.59bp (**curve moved against the trade**) yet **P&L +$59K** — clean empirical evidence that the 20bp delta-hedge harvest dominates the directional leg. Target/stop both $1,000K.
- Stated entry thesis: "current environment is favorable for initiating delta-hedged curve flatteners. Rates vol is likely to see a cyclical turn higher. Long-dated forward curves have steepened as a result of the recent decline in rates volatilities." Risk: VA hedging flows in risk-off.
- Straddle-switch sizing: buy **$1bn 1y 2s10s straddles vs $1.7bn 6m 5s10s straddles**, delta-hedged.

### print.pdf.md — European Rates Weekly, 18 Mar 2022
- **NEW TRADE: receive 5s10s30s 3m forward-starting swap @ 41bp mid, target 20bp, stop 50bp.** Risk: another bout of top-left vol richening.
- Framing that matters for a convexity engine: € 10s30s at its most inverted in 13y is *the* long-convexity price; "investors cautiously re-assessing the value of being long convexity as gamma vol corrects lower."
- **Vol-normalized roll-down metric:** 3m fwd/spot roll-down (annualized ×4) divided by 3m10y ATMF vol level. As of 17 Mar 2022: **0.3bp per bpv** to receive 10y, **0.4** to pay 5s30s, **0.1** to receive 5s10s30s — i.e. the fly was the *worst* on pure carry but chosen for asymmetry.
- **Gamma-vol → curve betas** (3m changes regressed on 1bpv change in 3m10y ATMF vol, post-GFC daily overlapping from 4 Jan 2010):
  - conditional on 2y **selloff**: € 5s10s30s `y = 0.82x + 1.25`, **R² 0.48** (the only economically meaningful relationship); € 10y `y = 0.45x + 26.76`, R² 0.05; € 5s30s `y = -0.35x - 6.87`, R² 0.06.
  - conditional on 2y **rally**: € 10y `y = -0.64x - 32.10`, R² 0.39.
  - Interpretation: the 5s10s30s fly is the highest-signal curve expression of gamma vol when the front end is cheapening, and its cheapening came from **flatter 10s30s, not steeper 5s10s**.

### print (4) — NA Rates Trade Idea, 9 Feb 2017 (full spec, no OCR loss)
- **Sell $200k DV01 of Blues convexity adjustment**: buy 2000 of H0-Z0 ED packs (2000 of each of four contracts) and pay $2bn on a matched-maturity (3/18/20-3/17/21) **CME-cleared** swap at **8.8bp of spread**, fixed leg quarterly.
- **Hedge: pay the belly of 2s5s10s** with notionals **$147mm / -$85.6mm / $20.89mm** = **0.705 / -1 / 0.465 DV01 weights**, at **-18.2bp** on the DV01-weighted fly.
- Target **+$600k**, stop **-$350k**; package carries **+$380k over 3m**. Blues CA ~4bp (≈2σ) wide to model, +1.3bp rolldown over 3m.
- Driver: dealers long ED futures vs asset-manager/leveraged-fund shorts ⇒ dealers structurally short CA ⇒ CA widens with dealer positioning.
- CME vs LCH: recommend CME clearing — CA appears wider on LCH but CME nets ED and swap margin.

### print (5)/(7) — US Rates Weekly, 13 Jan 2017, §"Smart convexity sells"
- Smaller sizing of the same trade one month earlier: **sell $100k DV01 Blues CA** (buy 1000 H0-Z0 packs, pay $1bn matched-maturity CME swap, quarterly/quarterly) + **pay 2s5s10s belly $79mn / -$44.4mn / $10.9mn (0.73 / -1 / 0.46 DV01)**.
- Carry **+$206k over 3m** ($130k from short CA, $76k from the fly hedge). Alternative hedge with a **3y1y straddle ($96mn notional)** carries only **+$65k** ($130k − $65k) — the explicit case for **using a DV01-weighted fly as a positive-carry substitute for a bought-vol hedge**, which is exactly the role of the 1y 2s7s30s leg in the PM's structure.
- **Hedge derivation (reusable recipe):** regress the convexity exposure on 2y/5y/10y swap rates; the fitted value *is* a fly. Blues CA → 2s5s10s with **-0.73/1/-0.47** DV01 weights, 4bp / 2.5σ wide. 3y1y implied vol vs scaled fly `59.7 + 60.5*(-0.71*2y + 5y - 0.18*10y)`; Blues CA vs scaled fly `10.2 + 21.4*(-0.73*2y + 5y - 0.47*10y)`; level correlation 90%. Short 2s5s10s carries **+4bp over 3m**.
- CA model = **Ho-Lee calibrated to cap/floor vols**; implied vol backed out by matching model to observed CA; compared against 3m realized vol of the pack.

### print (6) — US Rates Vol Lab, 17 Jan 2017
- **Long-expiry vol-adjusted roll-down table (13 Jan 2017)** — the swaption benchmark for "strikeless vol": vol (normals) / 1y rolldown (normals) / vol-adj rolldown / 1y ZS / 3y ZS. 3y10y 84.6/0.33/0.04/0.4/-0.3; 5y10y 83.3/0.69/0.10; 7y10y 79.1/2.09/0.36; **10y10y 72.7/2.10/0.38/-1.4/-2.02**; 3y20y 78.1/1.10/0.14; 5y20y 74.7/1.67/0.25; 7y20y 70.7/2.01/0.33; 10y20y 64.4/2.07/0.36/-1.6/-1.7; 3y30y 76.4/1.77/0.22; 5y30y 73.1/1.67/0.24; 7y30y 69.2/1.91/0.30; 10y30y 63.2/1.98/0.36/-1.4/-1.0. Vol-adj rolldown uses 3y vol-of-vol.
- Recommends **buying delta-hedged 10y10y straddles** (best vol-adj carry + most liquid long expiry). Same Blues CA / 2s5s10s spec as print (5), $100k DV01 version.
- Also: 2y30y vs 2y10y beta-weighted straddles for the Formosa NC5 tail switch; 3m 2s3s5s conditional receiver flies.

---

## 4. Named PDFs — convexity content

**`Alert…Taking profits on long end butterfly` (Citi, Mathai/Williams, 15 Jun 2020, 6pp)** — closes the trade opened in print (1). Structure: **receive 20y10y vs pay 10y10y and 30y10y**, i.e. receive the belly of the 10y10y/20y10y/30y10y fly, **1x2x1**, with a **beta adjustment making it slightly net long DV01**. Thesis: 30y swap point cheap vs 40y point; **"using butterflies to fade this was more attractive due to the smaller convexity risks compared to an outright long end steepener."** Selected by an **efficient-frontier screen of long-dated/ultra-long butterflies on 5y z-score vs 1y vol-adjusted carry**. Entry **16bp** (late Feb 2020), unwound at offer **10bp** (4pm 15 Jun 2020), **P&L +$360k**. Hit max P&L in the March dislocation but **transaction cost made it untakeable then**; normal bid/offer on the structure is **~3bp**. Directly relevant: it is the exact 10y10y/20y10y/30y10y fly neighbourhood the PM's flattener sits in, and it quantifies the liquidity constraint on any 25bp re-hedge loop in that sector.

**`North_America_Rates_Focus_Flatter_skew…` (Citi, Bikbov, 12 Jan 2017, 8pp)** — 3m changes in the **3m10y 25-out risk reversal**, bucketed into historical percentiles, predict the subsequent **1m** change in the 10y rate (monthly data Jan 2006-Nov 2016): steeper skew → higher rates, flatter skew → lower rates. Mechanism: core shorts hedged with low-strike options richen low strikes; flattening skew therefore signals a **build-up of core duration shorts** (corroborated by record short leveraged-money futures positioning). Convexity relevance is indirect — it is a **regime/positioning overlay** on when to be long vs short the convexity of the long end, not a sizing input.

**`US_Rates_Trade_Recommendation_Receive_Belly_of_1_Year_Forward_5s10s30s_Fly` (Citi/CIRA, Arora/Chen, 20 Dec 2010, 6pp)** — the template for **convexity cost as an explicit line item in trade selection**. Receive belly of **1y-fwd 5s10s30s**, target **20bp**, stop **10bp**. Explicit comparison: 1y-fwd 10s30s steepener has **+27bp/a carry but 11bp/a convexity cost** at **120bp/a realized vol**, and is rate-directional; the 5s10s30s fly has **-5bp/a carry but only 8bp/a convexity cost** and little rate directionality — the fly wins on convexity-adjusted margin. Target is derived as **28bp (fwd vs predicted) minus 8bp convexity cost = 20bp**. Full trade table with greeks: pay -$180.0mm 1y×5y @ 2.971% ATMF (delta 84,827; gamma -64); receive $200.0mm 1y×10y @ 3.908% ATMF (delta -171,139; gamma 206); pay -$50.0mm 1y×30y @ 4.344% ATMF (delta 86,510; gamma -230); **total delta 198, total gamma -88**. This is the closest published analogue of what the meta prompt asks rateslib to reproduce: DV01/gamma per leg, netted, with a convexity charge in bp/a computed from a realized-vol assumption.

**`interest rates — Why does the ultra long-end of a yield curve invert?` (Quantitative Finance StackExchange, Aug 2019)** — the first-principles justification for the whole book.
- dm63: with equal yields, the 40y has more convexity than the 30y; **long 40y / short 30y DV01-neutral makes money on every move** (longer in rallies, shorter in selloffs), so the market charges for it by pushing the 40y yield lower. Caveat: this fails for 10s30s because 10s move more than 30s, whereas 30s and 40s move roughly in parallel — **the direct argument for why the trade belongs in the 15y-30y forward sector, not 10s30s**.
- Zero-coupon proof: `P = e^(-yT)`, `dv01 = -T·e^(-yT)`, `convexity = T²·e^(-yT)` ⇒ **convexity per unit DV01 ∝ T**.
- **Convexity ladder per $1,000 PV01 IR swap — the numbers to reproduce in rateslib:** 10Y **$1.1**, 10Y10Y **$3.1**, 20Y10Y **$5.1**, 30Y10Y **$7.1**, 40Y10Y **$9.1**. At **50bp/a** uniform vol, expected 1y gamma P&L `0.5 · σ² · γ` = **[1.4, 3.9, 6.4, 8.9, 11.4] bp**. Note the ladder is roughly linear in forward start — so a 10y10y/20y10y DV01-neutral flattener is long ≈$2.0 of convexity per $1,000 PV01, worth ≈2.5bp/yr at 50bp vol. Use forward (non-overlapping) rates, not par rates, because a 20Y is >50% dependent on the 10Y.
- Structural driver of the inversion: **pension/insurance ALM-LDI receiving**, which is **pro-cyclical** (falling long rates force more hedging, and it unwinds violently in reverse) — the same VA/ALM flow print (1) and print (3) cite as the reason the embedded convexity is persistently cheap.

---

## 5. Convergent spec for the implementation

1. **Instrument set:** forward-starting swaps only — 10y10y, 15y5y, 20y10y, 15y10y, 25y10y, 30y10y — plus the 1y-fwd 2s7s30s (and 1y 2s5s10s as Katz's variant) hedge fly. No swaptions in the position.
2. **Weights:** DV01-neutral by construction, not guessed. Citi's published precedents derive fly weights by **regressing the target exposure on the constituent swap rates** (0.73/-1/0.46, 0.705/-1/0.465) or **beta-adjust to be slightly net long DV01** (the 1x2x1 10y10y/20y10y/30y10y fly). The PM's 5:1 is "rough PCA" and is exactly what the meta prompt says to replace with computed greeks.
3. **Hedge cadence:** 20-25bp parallel move (Citi used 20bp in USD, 20-25bp generally; Findley says 25bp / ~2 months). Re-price the original notionals and strikes on the shifted curve, recompute DV01, resize to neutral, book the difference.
4. **Cheapness metric, in daily-vol terms:** `daily breakeven (bp) / daily realized vol (bp)`, where daily breakeven is the rate move whose convexity gain offsets one day's negative roll. Ratio < ~0.5 = attractive; 0.00 (positive carry) = free convexity. Screen all 15 pairs × currency.
5. **Cost gates:** ~3bp bid/offer on a long-dated fly, ~0.6bp on 10y swaps — the March 2020 lesson is that a structure can be at max theoretical P&L and still be unexitable.
6. **Benchmark:** price the resulting strikeless-vol P&L against the vol-adjusted roll-down of the equivalent delta-hedged long-expiry straddle (10y10y is the reference point) to confirm the "long vega without a swaption" claim actually pays.