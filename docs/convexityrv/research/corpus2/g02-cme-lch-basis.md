# Corpus 2 / Group 02 — CME-LCH (CCP) Basis: level, term structure, drivers, hedging, margin economics

Source directory: `C:/Users/chris/Downloads/convexityrv_markdown`. All 14 assigned documents read in full.
Filename hazard: the file "Pricing and Arbitraging the CME_LCH Basis - Clarus Financial Technology.pdf.md" contains **U+00A0 non-breaking spaces** after "Pricing" and after "Arbitraging" in its name — plain-path Read fails; use a glob (`Pricing*Arbitrag*.md`) or copy it first.

Relevance to the SFR-CA-vs-fly project: the matched-maturity swap leg of the convexity adjustment has a **venue dimension**. A CA measured against an LCH-cleared SOFR swap differs from one measured against a CME-cleared swap by the CCP basis (history: <0.1 bp in 2014 → up to 2.0–3.4 bp and volatile 2015–2017 → ~0.85 bp and stable, with a sign flip below zero in 2024). Any CME-LCH-basis-conditioned CA variation should treat the basis as (a) a level shift in the CA depending on which curve the matched swap is built from, (b) a slow structural series driven by margin/funding costs and payer-receiver imbalance, not a fast mean-reverter, and (c) tradeable only above a ~3.9–4 bp threshold (two independent sources below).

---

## 1. LCH-CME Switch Trades and Margin Management — Clarus Financial Technology (blog), Amir Khwaja, June 30, 2014

File: `LCH-CME Switch Trades and Margin Management - Clarus Financial Technology.pdf.md`

Earliest doc in the group; the basis pre-2015 regime.

**Trade structure — CCP switch trade (definitional):** pay fixed at CME + receive fixed at LCH (or vice versa) in the same tenor and size, simultaneously; leaves total interest-rate DV01 unchanged, reduces IM at both CCPs. Brokerage paid on one side only.

**Worked example (hypothetical dealer book):**
- CME house IM $103m, LCH house IM $202m (total $305m).
- LCH IM driven by six largest HVaR loss scenarios; worst = historical date 13-Nov-2008, loss $204m, of which 10Y contributes $127m (10Y DV01 +$1,700,000 [note: text prints "1,700,00", clearly $1.7m/bp]; scenario 10Y rate −63 bp).
- CME 10Y contributes $25m loss, 10Y DV01 −$624,000.
- Switch: $285m notional 10Y, DV01 $250,000. Pay fixed CME (+250k) → CME 10Y DV01 −624k → −374k; receive fixed LCH (−250k) → LCH 10Y +1,700k → +1,450k; overall 10Y DV01 unchanged at +1,076,000.
- IM impact: LCH −$38m, CME −$10m, total −$48m = **16% of $305m**. Could do a further $425m notional (374k DV01) of 10Y switches.

**Market-size tie-outs (mid-2014):** standard 10Y USD IRS size $50m; block size $170m; $6–10bn gross 10Y per day (SDRView). Week of 16–20 Jun 2014: $2.5bn of 18M and $3bn of 5Y switch volume; Javelin reported $5bn 18M on 18-Jun (double-counted components), GFI reported $3.28bn LCH + $3bn CME 5Y on 19-Jun. CME USD cleared OI ~$10trn.

**Basis level as-of mid-2014:** "There can be a small basis spread (<0.1 bps) between CME and LCH rates."

No signal/entry/exit rules; no regression.

## 2. CME-LCH Basis Spread — Clarus Financial Technology, Amir Khwaja, May 20, 2015

File: `CME-LCH Basis Spread - Clarus Financial Technology.pdf.md`

The basis blow-out event doc.

**Level history:** basis "small enough (0.15 bps) to be inconsequential" historically; in May 2015 rose to a **term structure with values up to 2 bp**, vs a typical bid-offer of 0.25 bp. Convention: CME pay-fixed rates are HIGHER than LCH (pay fix up to 2 bp lower at LCH; receive fix up to 2 bp higher at CME) — i.e. positive CME-LCH basis = pay fixed at LCH, receive fixed at CME.

**30Y quote tie-out (ICAP indicative, Reuters page 19981, ~19-May-2015, assumed 0.25 bp bid-offer both venues):**
| Action | LCH | CME |
|---|---|---|
| Receive fixed 30Y | 2.74584 | 2.76484 |
| Pay fixed 30Y | 2.74834 | 2.76734 |

CME−LCH 30Y basis = 1.9 bp mid. Standard 30Y size $25m; the 1.9 bp difference = **$95,000** of value. Switch done through the market (pay CME 2.76734 / rec LCH 2.74584) loses basis + bid-offer = **2.15 bp ≈ $100k on $25m, $1m on $250m**.

**Mechanism (verbatim chain, the canonical positioning story):** CME cleared volume driven by fixed-income asset managers who swap fixed bond coupons to floating → clients pay fixed → dealer receives fixed at CME → dealer's D2D hedge cannot be found at CME (all dealers same way) → dealer pays fixed at LCH → dealer carries gross margin at two CCPs instead of zero ("difference between zero and two times gross margin"; for the $25m 30Y: zero vs **$5.5m of margin**). Funding + capital cost of that margin estimated **0.50–1.5 bp** — "which is the reason for the CME-LCH Basis."

**Fair-value upper bound (cited):** JP Morgan US Fixed Income Strategy, May 1, 2015: upper bound on the basis from the client cross-margin benefit of futures-vs-swaps at CME = **1.5 bp maximum**.

**Basis risk realization:** widening 0.15 → up to 1.9 bp caused dealer losses "up to as much as a $20 million loss at each dealer" (Risk, 15-May-2015). CME Advisory Chadv15-131 (13-May-2015): within 30 days CME-specific swap observations incorporated into CME end-of-day curves (creating the two-curve regime).

**Switch volumes 30-Apr–15-May-2015 (single-counted):** Tradition >$10bn (30-Apr $7bn incl. three $1.5bn+ 5Y trades vs standard size $70m; 13-May $1.8bn; 15-May $1.9bn); ICAP ~$10bn (5-May $2.7bn, 8-May $2.3bn); total >$20bn in 12 business days. Tulletts lumpy incl. $1.9bn on 12-May; GFI $150m 7Y on 13-May; BGC $500m CME 14-Apr-2015.

## 3. Hedging the CME-LCH Basis — Clarus Financial Technology, Amir Khwaja, May 26, 2015

File: `Hedging the CME-LCH Basis - Clarus Financial Technology.pdf.md`

**Book setup:** net receiver at CME / net payer at LCH across 11 tenors (e.g. 2Y $2.6bn each side). Rate-hedged: +1 bp → CME −$5.8m, LCH +$5.8m, net −$20k/bp. IM: CME $218m + LCH $262m = **$480m gross** (vs "$5–10m" if all at one CCP).

**Basis P&L tie-out:** CME 5Y 01 = −$1m; 5Y CME-LCH basis moved +1.2 bp → −$1.2m on that tenor [text says "lost $1m on this move"]; summing all tenors, the 0.15→1.9 bp widening = **$7.5m portfolio loss**.

**Hedge trade:** $1bn 5Y CCP switch at mid (hedger pays fixed at CME / receives fixed at LCH, offsetting the rec-CME/pay-LCH book; LCH-side 01 −$450k): reduces LCH 5Y 01 from +$1.145m [implied] to +$695k and CME to −$560k — basis risk nearly halved (further +1 bp widening now costs $560k not $1m).
- Cost: executed at prevailing basis — receiving 1.65642 / paying 1.66842 = paying away **1.2 bp = $600k** over the life.
- Benefit: IM falls $17m at LCH + $17m at CME = **$34m**. Funding-cost saving at 50 bp overnight rate: $472/day; PV over 5y with IM decay ≈ 460 $/mm-DV01 × 34 × 50 bp × 0.5 = **$391k ≈ $400k**. Default-fund saving: DF ≈ 8% of IM, at 10% equity capital rate ≈ **$270k**. Total **≈$670k saving vs $600k paid** — trade worth doing; and once CME re-marks its curves (Chadv15-131), the −$600k MTM goes to ~zero if basis stays 1.2 bp.

## 4. CME-LCH Basis – What does the Term Structure tell us? — Clarus Financial Technology, Chris Barnes, May 26, 2015

File: `CME-LCH Basis - What does the Term Structure tell us_ - Clarus Financial Technology.pdf.md`

**Term-structure tie-outs (TradX prices, 26-May-2015, single-curve Excel forward model):**
- Spot 5Y basis "only" **+1.85 bp**; **5y5y forward +2.9 bp** → upward-sloping forward basis curve; the market does NOT expect reversion to zero at any maturity (contrast with Libor-OIS 2008/09 where long-dated basis was narrower on normalization expectations).
- First hump of the curve at **4 years** — the tenor with the largest 1-week widening (+0.75 bp) — read as the average maturity of the paying pressure.
- Belly (~10y) cheap vs wings → highest switch volumes there (offers easier to find).
- Max roll-down of the 1-year forwards: **1.1 bp/yr** — "unlikely to be enough to attract hedge funds."
- Volume mix: 21% of TradX 7yr and 15% of 10yr total USD swap volume was CME-LCH basis-related (30-Apr–15-May window); 30y decent volumes. Non-benchmark tenors (6y, 12y, 25y) removed from curve build as noise.
- Basis widened over the week following doc #2.

Speculative drivers listed: intrinsic cost of dual-CCP IM rising with rates (correlation of outright rates with CCP basis); possible convexity of the basis vs swap spreads at zero strike.

## 5. Pricing and Arbitraging the CME/LCH Basis — Clarus Financial Technology, Tod Skarecky, June 22, 2015

File: `Pricing␣and Arbitraging␣the CME_LCH Basis - Clarus Financial Technology.pdf.md` (␣ = U+00A0)

The retail-arb cost-stack doc — the group's transaction-cost benchmark.

**Setup:** ICAP SEF indicative mid 17-Jun-2015: **5Y switch = 1.25 bp**. Receive CME / pay LCH $100m 5Y → $12,500/yr = $62,500 gross over 5y; MTM zero at inception because each leg is revalued on its own CCP curve; floating legs (same 3M Libor) always offset; basis moves generate VM.

**Cost stack (best-case assumptions):**
- Execution: ~$10/side on BBG SEF (ignoring terminal costs); basis market only exists on IDBs, else leg into it and pay spread twice.
- DCO fees: booking ~$4/mm ("standard") or $25 flat ("active"); maintenance $2–3/mm/yr standard, or %-of-IM active. Pay-as-you-go (plan A) wins.
- FCM fees: booking ~$1,000/ticket; **maintenance 10–100 bp on IM p.a.** (one FCM raised it BY 75 bp per Risk); monthly minimums in the tens of thousands (assumed away).
- IM: day-1 **≈$3.9m** on the $100m 5Y pair, tapering over 5y (CHARM forward IM profile); funded in 1y increments off a steep forward curve. Client IM = house IM +10%. IM add-ons scale super-linearly with size.
- After fees: $62,480 → ~$45,000 → negative once IM funding included.

**Breakeven (the number):** with all parameters, personal breakeven **5Y basis = 3.932 bp** — below that the switch "arb" loses money for an unaxed account. Each firm has its own two-sided breakeven set by its existing portfolio ("natural axe"); the dominant term is the forecast IM profile. Not a true arb even then (funding/fee components not lockable).

## 6. CME-LCH Basis For Dummies — Clarus Financial Technology, Tod Skarecky, June 28, 2017

File: `CME-LCH Basis For Dummies - Clarus Financial Technology.pdf.md`

The MVA decomposition of the quoted basis — the closest thing in the group to a published fair-value model of the CCP basis.

**Setup:** stylized dealer: fixed-rate payer at LCH, receiver at CME (18 Clarus articles on the basis since 2014). IM: CME $1.2bn, LCH ~$5bn. Client pays fixed $100m 30Y at CME; dealer hedges by paying fixed at LCH; both IMs increase (a trade can increase account IM by MORE than its standalone IM — liquidity add-ons on large positions).

**MVA arithmetic (tie-out):**
- Incremental IM today ≈ **$10m** (CME side), tapering over 30y (forward IM profile: Base, 1Y, ... rows: Account / New / Change / Margin columns).
- Funding spread assumed **20 bp over Fed Funds** (CCPs pay ~FF on cash collateral).
- Lifetime funding cost of the incremental margin = **$726,545**.
- Trade DV01 = **$225,000** ($100m 30Y).
- Converted: CME swap ≈ **+1.3 bp**, LCH swap ≈ **+2.1 bp**, total **3.4 bp** = the contemporaneous Tradition 30Y switch quote (screenshot dated ~Jun-2017). So the mid-2017 30Y basis ≈ 3.4 bp and is fully explained as two-sided MVA.
- Caveat verbatim in spirit: every bank's portfolio and funding differ → each has an "axe"; and "the basis market is a market unto itself, complete with speculation and panic, so it can move regardless of these costs."

## 7. CME-LCH Basis: Convexity in Eurodollar Futures — Clarus Financial Technology, Chris Barnes, July 1, 2015

File: `CME-LCH Basis_ Convexity in Eurodollar Futures - Clarus Financial Technology.pdf.md`

The doc most directly on futures-convexity mechanics; ED-era but the margin logic carries to SR3.

**Futures-vs-swaps liquidity crossover:** comparing ED ADV vs SEF swap DV01 by tenor (3-day avg 24/25/26-Jun-2015): swaps **up to and including 3y** are better priced off the Eurodollar strip than off a pure IRS curve.

**Convexity first principles (borrowing Stephen Aikin, stirfutures.co.uk):** short ED future + long equivalent FRA has convex net PnL (the "smiley face") — positive PnL wherever rates go IF traded at equal price and zero funding cost; therefore **ED futures trade at a higher implied rate than the equivalent FRA**, the difference being the convexity adjustment, whose size "depends upon the expected path of interest rates and hence volatility." Pre-clearing, uncleared FRAs made the trade sweeter (futures margin reinvested at higher rates with no offset on the uncollateralized FRA) — high-vol environments are when CAs become highly significant.

**Margin numbers (CHARM, tie-outs):**
- LCH IM on the example FRA: rises from **$1.37m to $1.4m** as rates fall; below **$1.355m** at higher rates; IM itself slightly convex (revaluation effect).
- CME SPAN on **1,000 lots of EDM6 = $425,000**.
- Funding assumptions: VM funded at a 25 bp spread (receive OIS −12.5 bp on ITM, pay OIS +12.5 bp on OTM); IM term-funded at the 1y IRS rate, then **0.50%**.

**Key structural result:** applying those funding costs to the future-vs-cleared-FRA package, the traditional convex payoff **survives only when the FRA is cleared at CME with CME portfolio margining**; FRA at LCH (or CME without PM) shows humped payoffs from funding two lots of VM, and payoff depends on outright rate level (term IM vs overnight VM funding). Implication: convexity between CME futures and OTC is only cleanly tradeable inside CME's cross-margin pool, which impedes moving 2y-3y ED liquidity into LCH swaps and may explain the 4y hump in the basis term structure (doc #4).

**Flow evidence:** biggest-ever CME USD FRA week (late Jun-2015), not an IMM roll; ~**$40bn of EDM6-dated IMM FRAs traded at CME in one day** at a variety of strikes, alongside a jump in Jun-16 ED OI — read as convexity plays (long CME FRA vs short ED under portfolio margining).

## 8. CME-LCH Basis: Convexity in Eurodollar Futures | (print capture) — duplicate

File: `CME-LCH Basis_ Convexity in Eurodollar Futures _.pdf.md` — exact duplicate of doc #7 (browser print capture dated 10/10/25); no additional content.

## 9. CME vs. LCH: Take Two — FIA MarketVoice, Nicola Tavendale, December 21, 2017

File: `CME vs. LCH_ Take Two _ FIA.pdf.md`

Largely irrelevant (FX/NDF clearing competition, not rates). Reusable crumbs: the buyside-clears-CME / dealers-clear-LCH pattern is cited as the precedent from IRS clearing; CME estimated margin offsets between NDFs and non-deliverable IRS (BRL, KRW) "as high as 51%"; LCH ForexClear Q3-2017 NDF notional $1.5trn (+400% y/y); UMR phase-in thresholds $3trn → $2.25trn → all by Sept-2020. No basis levels, no trade structures relevant to the CA project.

## 10. FMX Futures Says Margin Savings with LCH will Exceed CME — Markets Media, Shanny Basar, July 30, 2024

File: `FMX Futures Says Margin Savings with LCH will Exceed CME - Markets Media.pdf.md`

The venue-competition doc for SOFR futures — a candidate structural-break driver for the CA and the CCP basis from Sept-2024.

**Tie-outs (Q2-2024, BGC/CME earnings calls):**
- FMX Futures launch: **SOFR futures September 2024**; UST futures early 2025 (full CFTC approval). Clearing at LCH.
- LCH: fully approved CFTC DCO; **~98% market share in USD swap clearing; $53.3trn cleared in Q2-2024; holds $225bn of IRS margin** available for cross-margin vs futures; CME holds **~$37bn**. Lutnick: LCH has "at least 6.5×" CME's USD collateral.
- CME (Duffy): "margin savings of nearly $20bn per day" via offsets within its rates futures/options franchise.
- BGC claim: SOFR futures are "near perfect" offsets for IRS → cross-margin efficiencies vs the larger LCH pool "many multiples of CME" over time.
- FMX UST cash platform: record $47bn ADV Q2-24, 30% market share (vs 23% y/y). ~50 FCMs to onboard; 3-year competition roadmap.

## 11. SOFR Discounting Transition Process For Cleared Swaps (MRAC Appendix B) — CME Group, Steven Dayon & Dhiraj Bawadhankar, June 2, 2020 (filed to CFTC MRAC July 21, 2020)

File: `MRAC_AppendixB072120.pdf.md`

Two payloads relevant to the project.

**(a) CME's transition-curve construction = a matched-swap convention datapoint:** SOFR curve for the cash-compensation calc built as:
| Tenor | Instrument |
|---|---|
| 1M | CME Monthly SOFR futures (SR1) |
| 3M–2Y | CME quarterly SOFR futures (SR3) [slide labels them "Monthly"; ticker SR3 is the quarterly] |
| 3,4,5,7,10,12,15,20,25,30,40,50Y | Fed Funds–SOFR basis swaps |

"**Convexity adjustment is applied to SOFR futures to better reflect the differential of interest rate risk between OTC and exchange traded instruments.**" Quotes at 3:00 pm ET; forward rates held constant through the transition. I.e. CME itself strips SR1/SR3 with a CA out to 2Y when building its OTC curve.

**(b) Structural break for any backtest spanning Oct-2020:** USD cleared-swap discounting/PA switched EFFR → SOFR at COB **Friday October 16, 2020** (all CME USD IRS, OIS, FRA, basis, ZCS, swaptions). Cash adjustment at trade level (report fields NPV_NEW_DISC / NPV_PRIOR_DISC / OFFSET_ADJ_AMT; sample 2,266.34 vs 2,244.28, adj −22.06). CME booked **mandatory EFFR/SOFR basis swaps** to restore discounting-risk profiles: tenors 2/5/10/15/20/30Y, USD-SOFR-COMPOUND vs USD-Federal Funds-H.15-OIS-COMPOUND, start 10/21/2020, 3M pay freq both legs, ACT/360, spread on SOFR leg, $0 NPV, no IM/VM on transition date. Optional unwind auction Monday Oct 19, 9–10am ET, single auction all six tenors, winner-takes-all (small) or Dutch (large; vertical slices, last-clearing-size pricing). Worked Dutch example: net DV01 $2m, gross $5m, realized bid/ask 0.4 bp vs market 1.0 bp = 60% savings ($5m gross cost $2m vs $5m individually); cost allocated pro-rata on gross DV01 (10/20/30/40% shares). LCH ran the equivalent transition the same weekend (not in this doc) — so both discounting regimes and the EFFR/SOFR basis market changed at once.

## 12. The Portfolio Margining Imperative for Interest-Rate Derivatives — Coalition Greenwich (Stephen Bruel), Q4 2024 (research conducted Q3 2024)

File: `Portfolio-Margining-Imperative-Interest-Rate-Derivatives-24-2040.pdf.md`

The quantified cross-margin doc (LCH-supplied scenarios).

**Headline:** clearing USD swaps + rate futures in one CCP → potential margin savings up to **~80%** (USD), up to 50% on 13 other currencies.

**LCH scenario table (futures packages sized DV01-neutral vs $100m swap notional; "maximum achievable" hypotheticals; USD millions):**
| Scenario | Swaps+Futures IM | Portfolio-margined IM | Saving |
|---|---|---|---|
| 2Y receive fixed vs SOFR futures | $1,558 | $349 | 78% |
| 2Y pay fixed vs SOFR futures | $2,018 | $448 | 78% |
| 5Y receive vs SOFR futures | $3,753 | $870 | 77% |
| 5Y pay vs SOFR futures | $3,841 | $932 | 76% |
| 10Y receive vs UST futures | $6,630 | $2,646 | 60% |
| 10Y pay vs UST futures | $6,623 | $2,923 | 56% |
| 30Y receive vs UST futures | $12,924 | $6,496 | 50% |
| 30Y pay vs UST futures | $14,494 | $7,186 | 50% |

[Note: these IM figures are far larger than $100m-notional IM; they read as scaled/aggregate illustrations — use the RATIOS, not the levels.]

**Cross-currency offsets vs US rate futures (LCH figures):** EUR 41%, GBP 46%, CAD 50%, AUD 50%; LatAm not in scope at LCH; CME LatAm-swaps-vs-UST-futures 4–8%.

**Market-structure tie-outs:** IRD posted margin $331.8bn end-2023, +108% since 2017 (ISDA). LCH SwapClear swaps IM ~$227bn vs CME $37.5bn (Q1-2024 IOSCO disclosures); LCH netting already saves $102bn vs no-netting. 2023 SwapClear volume $1,319trn across 27 ccys, $502trn USD ≈ 98% of USD IRS clearing. UST futures ADV >80% of cash in most quarters; futures+SOFR futures traded 6× cash in 2023 (quarterly futures-to-cash ratios: 305%–792%, peak Q1-2023 792%). 88% of bank respondents: capital efficiency "very important" in CCP choice. **BofA research: margin = 76.7% of the cost of trading 10Y UST futures.** FMX partners: 10 largest banks/market-makers, 7 of the 8 largest FCMs.

**Mechanics:** LCH runs a daily automated process moving futures risk into the SwapClear pool where jointly margining is more efficient; included contracts enter the SwapClear VaR calc; no new bookings by members; model (not parameters) is volatility-invariant → more predictable calls. Pre-trade what-if via LCH Rates Margin Calculator / CME Margin Calculator.

## 13. Back to the basi(c)s – what is the CCP basis, why does it matter and is it here to stay? — SUERF Policy Brief No 940, Boudiaf, Kretschmann & Scheicher (ECB), July 2024

File: `SUERF-Policy-Brief-940_Boudiaf-Scheicher.pdf.md`

The academic driver-taxonomy doc.

**Definition/sign convention:** basis = fixed-rate difference for otherwise-identical IRS at two CCPs; positive Eurex-LCH (or CME-LCH) basis = pay-fixed costs more at Eurex/CME = oversupply of fixed payers there.

**Cross-CCP stylized facts (10y tenor, weekly averages, Bloomberg):** Eurex-LCH and CME-LCH historically positive, but **CME-LCH "recently dropped below zero"** (2024); JSCC-LCH negative for most of the period, turned positive early 2024. Persistence in one direction ⇒ partly structural.

**Driver taxonomy — sign** set by directional client imbalance (payer vs receiver oversupply within a CCP) + monetary-policy-driven repositioning; **size** set by the cost of collateralizing two directional portfolios: (1) margin models (netting, anti-procyclicality), (2) cross-margining practices, (3) collateral eligibility/haircuts, (4) funding costs / rate environment / HQLA availability, (5) balance-sheet capacity (capitalizing non-netted exposures + two default funds). Tenor-dependent.

**CME-specific driver (footnote, Benos et al. 2021/2022 "The Cost of Clearing Fragmentation"):** CME-LCH basis partly explained by local US banks hedging fixed-rate mortgage portfolios → pay-fixed preference at CME. Benos et al. estimate gains from exploiting the differential at **USD 80 million daily**.

**Arbitrage threshold:** "anecdotal evidence that a basis of at least **4 basis points** is required for an arbitrage transaction to be economical" (risk.net, JSCC-LCH context) — corroborates Clarus's computed 3.932 bp 5Y breakeven (doc #5). Below the threshold the basis is structural; low funding costs lower the threshold.

**Event history (Eurex-LCH):** 2017 Eurex profit-share incentive programme → basis to ~0 through 2018–19; brief negative at peak Brexit uncertainty end-2019; Covid spike Mar-2020 then calm; rose with inflation mid-2021 and further through the 2022 tightening without reverting. JSCC-LCH: pre-2018 sizeable negative (domestic banks receiving); 2018 hedge-fund onboarding arbitraged it down; spikes on BoJ tightening (2018, payers at LCH) and easing expectations (2019, 2024, receivers at LCH), each short-lived. EMIR 3 active-account requirement may shift the Eurex-LCH balance either way.

## 14. Fixed-income cross-margin opportunities: A driver of change — Crisil Coalition Greenwich (Stephen Bruel), Q3 2025 (interviews Feb–May 2025, 38 US participants)

File: `fixed-income-cross-margin-opportunities-driver-change.pdf.md`

The current-regime doc.

**CCP basis now:** the CME-LCH basis "has narrowed and become less volatile." Through the Feb–May 2025 tariff episode (Liberation Day, Apr-2025), **7Y invoice spreads moved >15 bp while the CCP basis stayed relatively flat** — a correlation breakdown between the basis and market vol vs a few years ago. Chart terminal marks (14-May-2025-ish): **7Y invoice spread −43.375 bp; CCP basis 0.85 bp** (axes: invoice spread −60..−30, basis −10..+10). Inference in the doc: cross-margin savings now more than offset the basis cost.

**Survey tie-outs:** 94% believe margin savings realizable between USD IRS and USD futures (n=18); 93% willing to clear packages at an additional CCP if offsets exceed the basis (n=14); 94% say offset availability influences where they clear (n=18); 70% (separate study) rank cross-margining the top attribute of a UST/repo clearinghouse. Margin ranked a bigger cost factor for swaps than futures (MPOR: uncleared > cleared swaps > futures); liquidity ranked most impactful for both.

**CME portfolio-margining savings (CME data, average daily, $bn):** 2016 2.5 → 2017 2.2 → 2018 2.2 → 2019 4.5 → 2020 5.2 → 2021 5.6 → 2022 6.9 → 2023 7.3 → 2024 7.7 → **H1-2025 8.2** (record, ~+12% vs 2024; ~90% of savings from USD swaps vs USD rate futures/options). Landscape: CME–FICC cross-margin (cash+derivs), planned CME Securities Clearing (CMESC); LCH–FMX cross-margin of cleared swaps vs FMX Treasury futures.

---

## Synthesis for the CA-vs-fly backtests

1. **Which swap curve defines the CA.** The matched-maturity forward swap has a venue. Regime history of the USD CCP basis: <0.1 bp (2014) → 0.15 bp pre-May-2015 → up to 2 bp (May-2015 blow-out; 30Y quotes above) → ~3.4 bp 30Y mid-2017 → narrow/stable ~0.85 bp with a 2024 sign flip (SUERF) and vol-insensitivity through Apr-2025 (Greenwich). Any CME-LCH-conditioned CA variation must specify which CCP curve the swap leg is stripped from; the basis contributes a slowly-varying, tenor-dependent bias to measured CA.
2. **Convexity-monetization plumbing.** Clarus doc #7: the futures-vs-OTC convexity package's smiley payoff survives funding costs only inside a single margin pool (CME futures + CME-cleared OTC with portfolio margining, historically). FMX/LCH (SOFR futures Sept-2024, UST futures 2025) creates for the first time a SOFR-futures-vs-LCH-swap-pool margining channel (78% offsets at 2Y-5Y per doc #12) — a candidate structural driver of both the CCP basis and the level/vol of the SOFR CA from late 2024 onward.
3. **Cost floor.** Two independent numbers for the round-trip economics of trading the CCP basis itself: Clarus computed 5Y breakeven **3.932 bp**; SUERF anecdotal threshold **≥4 bp**. Below that, the basis is structural carry, not a trade — relevant if a CA-vs-fly variation contemplates legging across CCPs.
4. **Fair-value model of the basis** = two-sided MVA: incremental forward-IM profile × funding spread ÷ DV01, per venue side (worked 30Y example: $10m IM, 20 bp spread, $726,545 lifetime cost, $225k DV01 → 1.3 + 2.1 = 3.4 bp). Upper bound from the client cross-margin benefit: 1.5 bp (JPM, May-2015). Drivers taxonomy (SUERF): imbalance sets sign; margin models, cross-margining, collateral, funding, balance sheet set size.
5. **Basis term structure exists and was steep** (spot 5Y +1.85 vs 5y5y +2.9 bp, May-2015; 4y hump; 1.1 bp/yr max rolldown) — if a dealer basis-curve series can be sourced, it is a conditioning variable, but its rolldown was never enough to attract spec capital.
6. **Backtest breaks:** 13-May-2015 (CME curves re-marked to CME observations, Chadv15-131); 16/19-Oct-2020 (EFFR→SOFR discounting + mandatory basis-swap booking + auction); Sept-2024 (FMX SOFR futures at LCH). CME's own transition curve applied a CA to SR1/SR3 out to 2Y with FF-SOFR basis swaps beyond — a precedent for the matched-swap convention.
