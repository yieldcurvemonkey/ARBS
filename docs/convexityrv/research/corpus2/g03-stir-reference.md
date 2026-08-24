# Corpus 2, Group 03 — STIR reference documents

Reader: subagent g03. Source directory: `C:/Users/chris/Downloads/convexityrv_markdown`.
All five assigned files were read in full. Ranked by relevance to the CA-vs-fly backtest
program: the CME/Rogerson article is the only document in this group with dense,
directly-usable convexity numbers (a complete worked futures-strip-to-IMM-swap pricing +
DV01 hedge ladder + convexity P&L table + margin figures — an excellent known-answer
tie-out set for our matched-swap pricing code). The Barclays Abate primer is 224 slides of
money-market plumbing with zero futures-convexity content but useful institutional
background on SOFR construction, quarter-end dynamics, and CME-FICC cross-margining. The
three Aikin "Welcome to STIR futures" web captures are qualitative trading color from the
LIBOR era with a few conventions worth keeping.

---

## 1. Pricing and Hedging USD SOFR Interest Rate Swaps with SOFR Futures — CME Group

**File:** `Pricing and Hedging USD SOFR Interest Rate Swaps with SOFR Futures - CME Group.pdf.md`
**Title:** "Pricing and Hedging USD SOFR Interest Rate Swaps with SOFR Futures"
**Publisher / author / date:** CME Group, Mark Rogerson (head of CME STIR product team, Head of Interest Rates EMEA), 04 Jun 2025. ~20-minute-read article / whitepaper.

### 1.1 SR3 contract mechanics (conventions we must match)

- SR3 settles to **100 − compounded SOFR** over the contract reference period; reference
  period runs **from and including the 3rd Wednesday of the named month up to but not
  including the 3rd Wednesday 3 months later**. Example: H5 (Mar-2025) reference period
  Mar 19, 2025 → Jun 18, 2025 (exclusive).
- Final-settlement example: realized compounded SOFR 3.748% → settle 96.252.
- Price 100 − R where R = annualized implied compounded overnight rate. SFRH5 at 95.705 →
  3M compounded rate 4.295%; **decompounding under a constant-overnight-rate assumption
  gives an implied overnight SOFR ≈ 4.2725%** (daily compounding accounts for the
  4.2725% vs 4.295% gap). Good micro tie-out for a decompounding routine.
- **$25 per bp per contract**, fixed at all rate levels — the source of the convexity bias.
- Quarterly IMM contracts are contiguous (no gaps); serial contracts add front-end
  granularity, also covering 3-month windows.
- Each SR3 ≡ a single-period IRS over its reference period, both legs 3M, paid at period
  end.

### 1.2 Pack / bundle conventions

- Packs and bundles are **execution strategies, not distinct products**: single order over
  multiple consecutive futures.
- **Pack = 4 consecutive quarterly contracts (one year of curve)**; **bundle = integer
  multiples of 4 contracts spanning 2 to 5 years** (i.e., always starting from a defined
  point and covering 8/12/16/20 contracts).
- **Pack/bundle price = arithmetic average of constituent contract prices.**
- Minimum price increment for SOFR packs and bundles: **0.25bp** (0.0025).
- Worked number: 2-year bundle over the 8 contracts below has average price **96.675625**;
  plausible market 96.675 / 96.6775; buying the bundle at 96.6775 costs
  96.6775 − 96.675625 = 0.001875 = **0.1875bp** of the swap-side edge.

### 1.3 Worked example: pricing a 2y IMM swap from 8 SR3 futures (as-of April 2025, hypothetical)

Swap: 2-year Jun-25 IMM-dated USD OIS, quarterly payments both legs, act/360 both legs,
$100mn notional. Futures inputs (all 91-day periods):

| Contract | Start | End | Code | Price | Yield % | DF (period) | Cum DF |
|---|---|---|---|---|---|---|---|
| Jun-2025 | 18-Jun-25 | 17-Sep-25 | SFRM5 | 95.895 | 4.105 | 0.989730 | 0.989730 |
| Sep-2025 | 17-Sep-25 | 17-Dec-25 | SFRU5 | 96.290 | 3.710 | 0.990709 | 0.980535 |
| Dec-2025 | 17-Dec-25 | 18-Mar-26 | SFRZ5 | 96.605 | 3.395 | 0.991491 | 0.972191 |
| Mar-2026 | 18-Mar-26 | 17-Jun-26 | SFRH6 | 96.815 | 3.185 | 0.992013 | 0.964427 |
| Jun-2026 | 17-Jun-26 | 16-Sep-26 | SFRM6 | 96.940 | 3.060 | 0.992324 | 0.957024 |
| Sep-2026 | 16-Sep-26 | 16-Dec-26 | SFRU6 | 96.985 | 3.015 | 0.992436 | 0.949786 |
| Dec-2026 | 16-Dec-26 | 17-Mar-27 | SFRZ6 | 96.965 | 3.035 | 0.992387 | 0.942555 |
| Mar-2027 | 17-Mar-27 | 16-Jun-27 | SFRH7 | 96.910 | 3.090 | 0.992250 | 0.935249 |

Discounted floating cash flows per period (principal 1): 0.010270, 0.009196, 0.008343,
0.007765, 0.007403, 0.007239, 0.007231, 0.007305. Sums:

- Sum of discounted floating cash flows = **0.0647505**
- Sum of discounted daycount (Σ CDF_i × days_i) = **699.926**
- Sum of discounted floating cash flows × 360 = **23.310**
- Solved fixed coupon = **3.3304%** (fixed = 360 × Σ disc. float / Σ disc. daycount)

Interpretation stated in the article: buying one of each future in the strip ≡ receiving
fixed at 3.3304%; selling ≡ paying fixed at 3.3304%. Market-maker quote example: 0.5bp
bid/ask → 3.3275 / 3.3325; customer receives at 3.3275, MM hedges by buying futures at
table prices, locking **0.29bp** hypothetical profit (before hedge friction; using the
bundle at 96.6775 costs 0.1875bp of that, net ≈ **0.1bp**).

### 1.4 DV01 hedge ladder (single-contract bump method)

Method: bump one contract +0.01 (rate −1bp), reprice swap at ORIGINAL coupon, divide value
change by $25.

- Bump SFRM5 only (95.895→95.905): recomputed par coupon 3.3291%, swap value change for
  $100mn = **$2,501.88** → hedge **sell 100** SFRM5.
- Bump SFRU5 only (96.290→96.300): value change **$2,483.49** → hedge **99** contracts.
  Fewer than the front because discounting shrinks the swap's forward-bucket DV01 with
  maturity while the futures bp stays $25 — the stated root of the convexity bias.
- Full ladder (each contract bumped independently):

| Code | Hedge (contracts, short) |
|---|---|
| SFRM5 | 100 |
| SFRU5 | 99 |
| SFRZ5 | 99 |
| SFRH6 | 98 |
| SFRM6 | 97 |
| SFRU6 | 96 |
| SFRZ6 | 95 |
| SFRH7 | 95 |
| **Total** | **779** |

- All-contracts +0.01 bump: coupon 3.3204% (−1bp as expected), swap value change
  **$19,480.69** per $100mn; 779 × $25 = $19,475 — near-perfect hedge at ±1bp.

### 1.5 Convexity P&L table (the core CA tie-out)

Position: received fixed $100mn 2y Jun-25 IMM OIS at 3.3304% + short 779 SR3 across the 8
contracts; parallel move, futures P&L = 779 × bp × $25.

| Move | Swap ΔV ($100mn) | 779 futures | Net "hedged" P&L |
|---|---|---|---|
| −10bp | +$195,003 | −$194,750 | **+$253** |
| −25bp | +$488,326 | −$486,875 | **+$1,451** |
| −50bp | +$979,388 | −$973,750 | **+$5,638** |
| −100bp | +$1,969,792 | −$1,947,500 | **+$22,292** |
| +10bp | −$194,568 | +$194,750 | **+$182** |
| +25bp | −$485,606 | +$486,875 | **+$1,269** |
| +50bp | −$968,509 | +$973,750 | **+$5,241** |
| +100bp | −$1,926,274 | +$1,947,500 | **+$21,226** |

- Received-fixed-vs-short-futures profits on ANY parallel move → "long convexity";
  paid-fixed-vs-long-futures = "short convexity."
- DV01 drift: re-running the bump at +100bp vs +101bp gives swap DV01 **$19,480 →
  $19,921** and hedge **779 → 797** contracts. Linear approximation of the convexity gain:
  (797−779) × ½ × 100bp × $25 = **$22,500** ≈ the −100bp net P&L above. (The ½ is the
  average of the linearly-growing hedge mismatch over the move.)
- Rehedging framing: after −100bp realize ~$22,500, sell 18 more futures; a full retrace
  re-monetizes on the new ratio — explicitly identified as **delta-hedging an embedded
  option**, so "the magnitude of the difference between the fixed rate implied by futures
  prices and the equilibrium price for the swap is a function of volatility," and the
  swap-vs-futures rate difference "is essentially the cost of the premium for buying the
  embedded option in the convexity position." Directional sign stated: the receiver of
  fixed must receive **lower** than the futures-implied rate (pays for convexity). This is
  the article's entire CA fair-value model — no Ho-Lee/Hull-White closed form, no
  regression; CA ∝ volatility via gamma-rebalancing value.

### 1.6 Margin numbers (as published, per-contract performance bond, mid-2025)

| Code | Contracts | IM per contract | Total |
|---|---|---|---|
| SFRM5 | 100 | $425 | $42,500 |
| SFRU5 | 99 | $650 | $64,350 |
| SFRZ5 | 99 | $765 | $75,735 |
| SFRH6 | 98 | $825 | $80,850 |
| SFRM6 | 97 | $825 | $80,025 |
| SFRU6 | 96 | $825 | $79,200 |
| SFRZ6 | 95 | $800 | $76,000 |
| SFRH7 | 95 | $750 | $71,250 |
| **Total** | 779 | | **$569,910** |

- Swap-only IM (CME CORE): **$1,568,352** → futures hedge IM ≈ **36%** of the swap's.
  Driver: MPOR 1 day (futures) vs 5 days (IRS) under US regulation.
- **Portfolio margining** (swap + futures in the OTC waterfall): combined IM **$46,161**
  vs $2,138,262 separately — **~98% reduction**; residual IM is essentially the convexity
  risk. Conditions: both cleared at CME, same FCM, same beneficial ownership.
- Clients' portfolio-margining savings in rates: just over **$2bn (2018) → peak >$9bn
  (early 2025)**.

### 1.7 Use for our backtests

- The Section 1.3–1.5 numbers are a complete known-answer test for a matched-maturity
  IMM-swap pricer built off an SR3 strip: given the 8 prices, our code should reproduce
  coupon 3.3304%, DF ladder to 6 d.p., hedge ladder 100/99/99/98/97/96/95/95 (=779), and
  the ±10/25/50/100bp convexity P&L table to the dollar.
- Confirms conventions the CA measurement depends on: act/360 quarterly money-market both
  legs for IMM swaps priced from futures; arithmetic-average pack/bundle quoting; 0.25bp
  bundle tick; $25/bp; discounting done ON the futures-implied curve itself.
- Cost anchors: 0.5bp swap bid/ask (market-maker 2y IMM quote), 0.25bp bundle increment,
  0.1875bp bundle-execution give-up in the worked example.

---

## 2. ABATE STIR PRIMER 2025 — Barclays "US short interest rate primer"

**File:** `ABATE STIR PRIMER 2025 (1).pdf.md` (224 slides)
**Title:** "US short interest rate primer"
**Publisher / author / date:** Barclays FICC Research (BCI, US), Joseph Abate. Completed 31-Dec-24 13:43 GMT, released 02-Jan-25 12:00 GMT ("January 2025").

**Relevance verdict: background only.** Despite the filename, this is a *money-markets*
primer (Fed operating regime, balance sheet, discount window, deposits, FHLB, debt
ceiling, repo, clearing, bills, GSIB, CP/money funds, Basel III/SLR/LCR/NSFR). It contains
**nothing** on SOFR futures convexity adjustments, packs/bundles/flies, CA fair-value
models, dealer positioning vs CA, or the CME-LCH swap basis. Its value to the program is
institutional context for the SOFR fixing itself and for margin/clearing frictions.
Sections and the numbers worth keeping:

- **Fed rate corridor:** 25bp target band; RRP = floor, IORB currently set **15bp above
  RRP**; RRP counterparty cap $160bn; Fed gets uneasy when EFFR is within 5bp of the top
  of the band (spring-2018 episode; June 2021 +5bp RRP technical adjustment).
- **SOFR construction (slide 123):** SOFR = volume-weighted **median** across tri-party,
  GCF, and cleared bilateral repo; **bottom 20% of cleared-bilateral volume is trimmed**
  to strip specials. Fed funds typically trades ABOVE overnight SOFR; the FF−SOFR spread
  is sensitive to dealer balance-sheet pressure and positioning; SOFR can trade below the
  RRP floor when there is a deep market short base. Relevant to any ZQ-vs-SR3 leg of the
  program.
- **Quarter-end repo volatility (slide 122):** off-balance-sheet activity reported as the
  average of three month-ends → quarter-end balance-sheet pull-back pushes repo (and
  hence SOFR prints) higher; can take several days after quarter-end to normalize.
  Sept 30, 2024: SOFR as much as **15bp above the prior week's average** with the SRF
  hardly used ("operational frictions" cap commentary, Perli Nov 12 2024). This is the
  same seasonality our SR3 settlement windows straddle.
- **"Expanded SOFR" experiment (May 2024, slides 126-127):** adding several hundred $bn of
  uncleared bilateral trades makes the median ~**1bp higher** with an interquartile range
  ~2bp wider; cleared and uncleared medians within ~1bp. Bears on whether the June 2026
  repo clearing mandate shifts the SOFR fixing level.
- **Reserve ampleness:** Afonso et al. (NY Fed, Oct 2024) reserve-demand-elasticity model;
  ample zone **10–13% of bank assets ≈ $2.4–3.0trn**; RDE ≈ 0 as of late Nov 2024;
  2018-19 scarcity episode had FF 3–5bp above IORB before the Sep 2019 spike.
- **SRF:** $500bn program cap; min bid at top of the target band; 1:30pm auction, tri-party
  settle 3:30pm; two $20bn bids per dealer, Treasuries can fill agency/MBS shells →
  $120bn/day per-dealer Treasury capacity; not balance-sheet-neutral for arbing.
- **CME-FICC cross-margining (slide 141)** — the one clearing item directly relevant to a
  futures-vs-cleared-swap RV book: CME and FICC each margin the portfolio independently
  and **accept whichever model produces the most conservative net reduction**, pro-rating
  the percentage reduction across CME and FICC positions; CME converts FICC positions to
  DV01 equivalents, FICC converts Treasury futures to cash equivalents "with an
  appropriate basis" to simulate portfolio price history for VaR; CME has an optimizer
  that moves futures into the cross-margin portfolio.
- **Treasury clearing mandate dates:** cash trades Dec 31 2025; repo trades Jun 30 2026.
  FICC July-2024 estimate of incremental VaR margin: **$58bn** (ex add-ons, ex CCLF).
- **FICC repo rate tie-out:** Sep 30, 2024 — median (and modal) money-fund FICC repo rate
  **4.88%**, equal to that day's tri-party rate, both **8bp above the RRP rate**.
- **SIFMU deposits at the Fed:** ~$165bn, earning IORB (CME margin cash sits here).
- Misc series with dates usable as macro-covariate sanity checks: bank reserves >$3trn
  through 2024 (−$300bn in 2024); Fed assets $7.0trn end-Nov 2024 (62% TSY / 32% MBS);
  money funds ~$7trn aggregate; bills 22.4% long-term share discussion (TBAC Aug 2 2023);
  extraordinary-measures capacity ~$315bn; largest banks' FDIC assessment 5-8bp (the
  stated wedge that keeps domestic banks out of the FF-IORB arb, ≤8bp).
- LCR outflow assumptions table (insured deposits 3%, FHLB overnight advance 25%, FHLB fed
  funds 40%...), NSFR factor table, GSIB scoring revisions (quarterly averaging proposal,
  20bp score / 10bp surcharge bandwidth) — all context for year-end/quarter-end
  distortions in short rates.

No trade structures, no signals, no regressions with coefficients, no CA content.

---

## 3. Understanding open interest — Welcome to STIR futures (Aikin)

**File:** `Understanding open interest _ Welcome to STIR futures.pdf.md`
**Title/publisher/date:** "Understanding open interest", welcometostirfutures (Stephen
Aikin's companion site to *STIR Futures*, Harriman House), January 24, 2014.

One-page blog post. Defines OI (outstanding contracts not closed or delivered); per-contract
vs Market Open Interest; notes technical practitioners expect OI to rise as a trend
establishes and fall as it ends; shows Eurodollar and Euribor market OI vs continuous price
2002-2013 and concludes **"there does not seem to be an obvious link between increasing
open interest and price action."** No numbers, no trade structures. Only takeaway for us:
even the author of the standard STIR text found no OI→price signal at the market level —
mildly relevant as a prior against naive OI conditioning (our positioning work should stay
with CFTC TFF dealer nets, not raw OI).

---

## 4. Interest rate change probabilities — Welcome to STIR futures (Aikin)

**File:** `Interest rate change probabilities _ Welcome to STIR futures.pdf.md`
**Title/publisher/date:** "Interest rate change probabilities", welcometostirfutures
(Stephen Aikin), January 30, 2014.

Short post on backing out policy-change probabilities. Key content:

- STIR futures are the **wrong** instrument for policy-rate probabilities (LIBOR/EURIBOR
  fixings ≠ policy rates, "+ a ton of basis"); the right instrument is the **meeting-dated
  OIS** (one-period forward-starting OIS spanning consecutive MPC dates).
- Worked example (late Jan 2014, BOE): MPC meeting 8-May-2014 meeting-dated OIS =
  **0.499%** vs base rate 0.50%; probability of a +25bp hike on/before 8 May ≈ **0%**
  (the implied-probability formula figure itself was an image and did not survive the PDF
  conversion — it is the standard (OIS − base)/25bp construction); the same probability
  reaches **80% by the February 2015 meeting**, matching the then-consensus of a first
  hike early Q2 2015.
- Term-structure chart comparison: MPC-dated OIS vs consensus base-rate forecast vs Short
  Sterling implied forwards — the futures strip sits ABOVE the OIS strip purely because it
  is forward 3M LIBOR vs forward SONIA (basis), while the **gradients** agree; i.e., slope
  is comparable across products, level is not. Trader mapping: rates sooner/faster than
  priced → curve steepens → buy STIR calendar spreads; on-hold/slower → sell calendars.

Relevance: methodological footnote for the ZQ/SR3 meeting-probability comparisons already
in the repo (MeetingProb); confirms slope-not-level comparability across instruments with
different floating bases — the same principle that makes CA (a level spread) require a
matched-convention swap rather than any nearby strip.

---

## 5. Forum posts — Welcome to STIR futures (Aikin, 2006–2014)

**File:** `Forum posts _ Welcome to STIR futures.pdf.md`
**Title/publisher/date:** "Forum posts", welcometostirfutures (Stephen Aikin), Q&A archive
of a forum that ran 2006–2014 (site notes older posts have limited current relevance).

Qualitative LIBOR-era trading color; no regressions, no CA models. Items worth recording:

**Conventions / structures**
- **5-year STIR bundle = whites + reds + greens + blues + golds** (20 quarterly
  contracts) — matches our rank 1-20 color taxonomy.
- Forward-starting term TED construction: buy 5y T-note futures, sell 2y T-note futures in
  **equal notionals** (creates a 3y forward bond, repo a key driver), sell the STIR strip
  of **greens + blues + golds** (ranks 9-20).
- Euribor-vs-Schatz credit/swap spread: **bundles are the correct hedge** ("using bundles
  to trade the credit/swap spread between Schatz/bor is usually the best proxy"); a
  single-contract stack (e.g., ER4) adds curve risk; stacks in early/mid reds are highly
  correlated with the bundle, front month inappropriate. Observed market conventions for
  the stack version: quote **2×Euribor − Schatz** with a **4:5 Euribor:Schatz lot ratio**
  (taken from LCH Clearnet margin-offset ratios — i.e., a clearing-house hedge ratio, only
  approximately DV01-neutral); an alternative quoted ratio 25:18 Schatz:Bor appears
  regression-derived and the author flags regression ratios as sample-dependent and blind
  to curve-shape changes, recommending PCA of Euribor spreads vs Schatz/Bobl spreads.
- Bundle vs par swap mismatches (why matched-maturity CA needs care): the 2y swap is
  quoted **t+2 spot-starting** while the 2y bundle is **forward-starting at the first IMM
  date** → stub and maturity mismatches, plus counterparty/credit basis. Same point for
  Swapnote: 2y € Swapnote vs Euribor bundle spread is driven by **convexity and the
  incidence of cash flows**, not credit.
- CTD-maturity strip-length question: if the CTD matures 2 days after the 8th contract's
  expiry, 7 futures map cash flows better, but **DV01 neutrality dominates cash-flow
  mapping**, and using 8 keeps bundle executability (tighter price than legging 7).
- Short Sterling DV01 = **£12.5**; short gilt future DV01 ≈ £20 → gilt:sterling TED ratio
  ≈ 1.6.
- Implied pricing: LIFFE implied in/out across strip and calendar spreads but NOT
  butterflies or packs/bundles; **CME supports implied pricing into butterflies and
  condors** (from the strip, not from other spreads). Outright orders take precedence over
  implied-in prices.

**Numbers usable as loose period tie-outs (all LIBOR-era, mostly 2010-2014)**
- ED white 3M calendar spread initial margin ≈ **$160**; tick $25. VaR sizing example:
  U4Z4 ED spread stdev ≈ 1 tick ($25) over a mid-Jun→mid-Sep 3M sample; 99% 1-day loss
  2.33 ticks; risking $50k → ~850 spreads (50,000/(2.33×25)).
- **Back (deferred) red/green butterflies move very little — a yearly range of 2-3 ticks**
  (author's chart, ~2013). Fly traders look for a fly out of line vs adjacent flies (e.g.,
  trading 1.5s all week, closes 2.0 with adjacent flies unmoved → sell 2.0-2.5, buy
  adjacent flies on the bid). Fly trading described as bid/offer inventory business living
  on exchange ILP rebates — a cost-structure warning consistent with our measured
  1.5-2.0bp round-trip fly cost dominating small edges.
- Buy-and-hold 1y ED calendar "roll-down" strategy data (Moore Research, ~2010): white
  June vs red June spread in its final year, history to 1983: closed <0.13 in only 5 of 27
  years; lowest ≈ −0.7 ("an aberration"); typically closes just under 1.0; >2.0 five
  times. Example entry M8M9 at 0.13 vs M0M1 at 1.05; GE multiplier $2,500/point → gain
  $2,300/spread on 0.13→1.05; spread margins $100 (M8M9) and $400 (M0M1). Author caveats:
  assumes persistently positive curve; drawdowns when curve inverts; 2007+ patchy.
- Front-month roll effect: in a positive curve, the front fly/condor tends to sell off
  into the roll as positions migrate to the next month; magnitude scales with curve
  steepness; risk is flattening/inversion.
- Rate-probability question repeats the meeting-dated-OIS answer of doc 4 ("STIR futures
  reference LIBOR/EURIBOR ... + a ton of basis").
- 3M/12M calendars named the most liquid/representative structures on the ED complex;
  1-month ED calendars = 1 month of curve exposure, strictly less volatile, less liquid.

Relevance: conventions section feeds our pack/bundle/matched-swap construction; the fly
range and rebate-economics anecdotes reinforce the cost ceiling on fly mean-reversion; the
rest is period color.

---

## Cross-document synthesis for the CA-vs-fly program

1. **Known-answer suite:** Doc 1 provides the only end-to-end numeric chain in this group
   (8 futures prices → DFs → 3.3304% IMM coupon → 779-lot DV01 ladder → convexity P&L
   table → $46,161 portfolio-margined IM). Implement as a pytest tie-out for the
   futures-implied matched-swap leg of the CA calculation.
2. **CA model content in this group is minimal but directional:** CME states CA = value of
   the embedded option in received-fixed-vs-short-futures, monetized by rehedging, hence
   an increasing function of volatility; receiver must receive below the futures-implied
   rate. No closed form, no regression (the Citi-style Blues-CA-on-fly regression is not
   in this group).
3. **Convention traps confirmed:** arithmetic-average pack/bundle quoting (index points,
   0.25bp tick); bundle forward-start vs t+2 spot swap stub/maturity mismatch; DV01
   neutrality over cash-flow mapping; $25/bp fixed futures bp vs level-dependent swap bp.
4. **Positioning/OI:** Aikin found no market-level OI→price link (doc 3); nothing in this
   group on dealer-positioning-vs-CA — that thread must come from the CFTC/Clarus groups.
5. **SOFR fixing microstructure (doc 2)** — quarter-end repo spikes (Sep 30 2024: +15bp),
   SOFR-below-floor episodes under heavy short base, and the ~+1bp "expanded SOFR"
   estimate ahead of the Jun 30 2026 repo clearing mandate — are the settlement-rate-side
   risks to any SR3-settlement-window trade in the backtests.
