# Corpus 2 / Group 06 — SSRN academic papers on futures convexity adjustment and multi-curve construction

Source directory: `C:/Users/chris/Downloads/convexityrv_markdown`
Files covered (3, all read in full):

| File | Paper | Date | Direct relevance to CA-vs-fly RV |
|---|---|---|---|
| `ssrn_id3134346_code352726.pdf.md` | Henrard, *Overnight Futures: Convexity Adjustment* (OpenGamma) | Feb/Mar 2018 | **HIGH** — the canonical closed-form CA for a 3M compounded-overnight future (i.e. SR3). Defines the CA we are trading. |
| `ssrn_id3350745_code3383538.pdf.md` | Rosen, *Averaged Overnight Rate Futures: Convexity Adjustment* (FINCAD) | 1 Mar 2019 | **MEDIUM-HIGH** — CA for SOFR **1M** / Fed Funds (arithmetic average) and the size relation to the SR3 (compounded) CA. Gives magnitude scales. |
| `ssrn-2219548.pdf.md` | Ametrano & Bianchetti, *Everything You Always Wanted to Know About Multiple Interest Rate Curve Bootstrapping But Were Afraid To Ask* | v1 4 Feb 2013, this version 2 Apr 2013 | **MEDIUM** — where the CA sits in a bootstrap (futures rate = FRA rate + CA), matched-swap/discounting conventions, a fully worked HW futures-CA table with a verifiable arithmetic tie-out chain. |

**None of the three contains anything on:** dealer positioning (CFTC TFF) vs CA, CME–LCH clearing basis, pack/bundle/butterfly construction in futures space, or any fly-vs-CA regression. That material must come from the sell-side/Clarus documents in the other corpus groups. These three supply the **model leg** (fair-value CA) and the **convention leg** (what "matched-maturity forward swap rate" must mean) only.

### Decoding note (important for reproducibility)

`ssrn_id3134346_code352726.pdf.md` is **not readable as delivered**: the PDF→markdown conversion emitted raw font CIDs (`(cid:24)(cid:25)…`) because the embedded subset has no ToUnicode map. I reconstructed the glyph map empirically (validated against known words: "Abstract", "Contents", "Introduction", "convexity adjustment", "New York", "LIBOR–OIS", "G2++") and decoded the whole file. Map: `A–W = 1–23`; `a,b,c = 24,25,26`; `e–z = 27–48` (**`d` is not in that block — it is 80**); digits `0–9 = 49–58`; `: ; . , ( ) = 59,60,61,62,63,64`; `- = 68`; `Y = 74`; `’ = 79`; `– = 104`; `+ = 112`; `B = 217`; `% = 134`; `fi = 688`, `ff = 690`. Word spaces are lost (text reads run-together), and the *heading* font is a different subset in which `79` renders `d` (hence "Intro’uction" in body-font decoding of headings). The author e-mail line decodes to garbage and is not quoted here.
Decoded copy: `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/c8967402-eab9-408f-a7ff-5e479504934d/scratchpad/henrard_decoded.md` (decoder script `decode_cid.py` in the same directory) — **that path is session-temporary and will disappear**; the glyph map above is reproduced in full precisely so this file stays self-sufficient and the decode is reproducible from the original markdown. All Henrard quotes below come from that decode.

---

## 1. Henrard (2018) — *Overnight Futures: Convexity Adjustment*

**Exact identification.** Title: "OVERNIGHT FUTURES: CONVEXITY ADJUSTMENT". Publisher: **OpenGamma Quantitative Research**, February 2018. Author: **Marc Henrard**. SSRN abstract 3134346. Footnote 0: "**First version: 22 February 2018; this version: 5 March 2018.**" Section list: 1 Introduction, 2 Instrument description, 3 Gaussian HJM, 4 Pricing of futures, 5 Numerical example.

**Abstract (verbatim, spaces restored):** "In this note we describe the pricing, including the convexity adjustment, of the a new overnight benchmark based futures in the collateral framework using a Gaussian HJM-like model. The note also describes in details the cash-flows of the instrument. The adjustment obtained is relatively similar to the one obtained for LIBOR futures when the stochastic nature of the LIBOR–OIS spread is ignored. Some extra small adjustment need to be added to take into account that the futures settles only at the end of the accrual period while the LIBOR futures settle on fixing at the start of the underlying deposit period."

### 1.1 Instrument facts (these are the contract conventions our backtest must honour)

- Two contracts announced days apart: **CurveGlobal "Three month SONIA futures"** (launch planned **Q2 2018**) and **CME "CME Three-Month SOFR Futures"** (launch planned **7 May 2018**). CME simultaneously planned a **One-Month SOFR Future with a different term sheet**; Henrard covers only the 3-month contract (footnote 1).
- SOFR published by FRBNY in cooperation with the U.S. Office of Financial Research; **rate publication expected to start 3 April 2018** — i.e. the benchmark had existed for **one month** when the future started trading.
- SONIA: reformed benchmark **effective 23 April 2018**, volume-weighted trimmed mean of overnight unsecured transactions, **published 9am on the business day following the day the rate relates to** (so the ON rate for [start,end] is published on the *end* date, not the start date).
- **Dates.** Start accrual date `T_s` (also defines the contract month) and end accrual date `T_e`; `T_e` is also the last trading date and the date the **EDSP** is computed. **Both dates align with the quarterly IMM dates.** Worked example: *"the December 2018 contract will have a start accrual date on Wednesday 19 December 2018 and an end accrual date of Wednesday 20 March 2019."*
- **GBP:** trading stops **08:30 on the end accrual date**, i.e. 30 min before the last fixing is published; day count **ACT/365F**; **25 quarterly contracts** listed (24 not started + 1 accruing).
- **USD:** trading stops at the **close of CME Globex on the business day preceding the end accrual date**; day count **ACT/360**; **20 quarterly contracts** listed.
- Settlement rate definition (Henrard's disambiguation of "compounded daily SOFR interest during contract Reference Quarter"): with business days `T_s = t_0 < t_1 < … < t_n = T_e`, accrual factors `δ_i` for `[t_{i−1},t_i]`, `δ` for the whole period, `Σ δ_i = δ`:

  **(Eq. 1)  `1 + δ·r = Π_{i=1..n} (1 + δ_i·r_i)`**

  and the **EDSP** at `T_e` is **(Eq. 2) `P(t_e) = 1 − r`** (term sheet says "100 minus this rate"). Note "even if all the rates `r_i` are equal, the settlement rate `r` will not be equal to the same rate" — settlement uses a *simple* rate while accrual *compounds*.
- **Two structural warnings that bite any SR3-vs-swap RV measurement:**
  1. *"the ON futures relevant dates are from one quarterly IMM date to the next while the LIBOR futures relevant dates are from one IMM date to that date plus three months. The two products are related to different benchmarks but also to different dates; one has to be very careful when analysing the implied spread as it originates in the difference of benchmark but also in the difference of reference period."*
  2. *"in the USD case, the OIS usually settle not on the end accrual but two days later. This introduce a further difference between the ON futures and the OTC market on the same underlying."* (futures settle at `T_e`, matched OIS pays `T_e + 2`).

### 1.2 Model and closed form

Collateral framework of Henrard (2014, ch. 8) — collateral (pseudo-)discount curve `P^c(t,u)`, collateral cash account `N^c_t = exp(∫_0^t c_s ds)`. Dynamics: `P^c(t,u)/N^c_t = (P^c(s,u)/N^c_s)·exp(−∫ν(τ,u)dW^X_τ − ½∫ν²(τ,u)dτ)`. Ratio dynamics introduce

- `α²(s,t,u,v) = ∫_s^t (ν(τ,u) − ν(τ,v))² dτ`
- **`γ(s,t,u,v) = exp[ ∫_s^t ν(τ,v)·(ν(τ,v) − ν(τ,u)) dτ ]`**
- Hull-White one factor: **`ν(s,t) = (η(s)/a)·(1 − exp(−a(t−s)))`**

The framework is a **generic Gaussian HJM that generalises Hull-White and G2++**; the Brownian motion may be of any dimension — "in all cases they are explicit constants."

**Theorem 1 (valuation before the reference period, `0 < T_s`):**

```
P(0) = 1 − (1/δ) · [ (P^c(0,T_s)/P^c(0,T_e)) · Π_{i=1..n} γ(t_{i−2}, t_{i−1}, t_{i−1}, t_n) − 1 ]        (Eq. 3)
```
with the convention `t_{−1} = 0`. Written with the forward rate `F^c(t,u,v) = (1/δ)(P^c(t,u)/P^c(t,v) − 1)`:

```
P(0) = 1 − [ F^c(0,T_s,T_e) + (1/δ)·(P^c(0,T_s)/P^c(0,T_e))·( Π_{i=1..n} γ(t_{i−2},t_{i−1},t_{i−1},t_n) − 1 ) ]
```
and **"the last term can be described as the convexity adjustment."**

**Where the adjustment lives:** *"Most of the adjustment is coming from the period between the valuation date 0 and the start date `T_s` on full period `[T_s,T_e]` which is the first term of the product. The first term is `γ(0,T_s,T_s,T_e)`. The other terms include adjustments for very small time interval (one day) and on shorter and shorter periods."*

**Theorem 2 (valuation inside the reference period, `0 = t_k`, first k days already fixed):**

```
P(0) = 1 − (1/δ) · [ Π_{i=1..k}(1 + δ_i r_i) · (P^c(0,t_k)/P^c(0,t_n)) · Π_{i=k+1..n} γ(t_{i−2},t_{i−1},t_{i−1},t_n) − 1 ]   (Eq. 4)
```
*"In case some part of the futures as already fixed, there is no convexity anymore for that part."* — the CA on a front/accruing contract decays deterministically through the quarter.

Comparison anchor: Theorem 1 *"can be compared to (Henrard, 2014, Theorem 2.3) which describes the price of Ibor futures in case of deterministic spread between Ibor and OIS."*

### 1.3 Published numbers (tie-outs)

Section 5, numerical example:

| Quantity | Value | Provenance |
|---|---|---|
| Curve | "a realistic GBP OIS curve as **end of December 2017**" | text |
| Model | Hull-White **one factor, constant volatility** | text |
| **Mean reversion `a`** | **3.00%** | text (printed) |
| **Volatility `η`** | **65 bps** ("a realistic figure for the GBP market") | text (printed) |
| Per-day in-accrual-period adjustment terms | **"around 0.01 bps for all contracts"** | text (printed) |
| First term vs full adjustment | *"the first term of the adjustment product is almost the full adjustment"* | text (printed) |
| Figure 1 CA term structure | y-axis ticks 0,1,…,8 bp; x-axis Jan-18 → Jan-25; two series ("Adjustment first term", "Full adjustment") | **chart read** — CA rises monotonically with contract date to roughly **7 bp at ≈7y** (Jan-25 contract). Exact per-contract values are not printed. |

Caption verbatim: *"Figure 1: Realistic estimate of convexity adjustment in the for GBP SONIA futures. Market data as of end of December 2017."*

**References cited:** Fujii-Shimada-Takahashi (2011), Fujii-Takahashi (2013), Henrard (2014) *Interest Rate Modelling in the Multi-curve Framework*, Pallavicini-Brigo (2013), OpenGamma Quantitative Research (2012) *Overnight Indexed Swaps in multi-curves framework*, Working Group on Sterling RFR (2017).

**Absent:** no fly, no pack/bundle, no positioning, no CME-LCH, no transaction costs, no trade rules. Purely a pricing note.

---

## 2. Rosen (2019) — *Averaged Overnight Rate Futures: Convexity Adjustment*

**Exact identification.** Title: "Averaged Overnight Rate Futures: Convexity Adjustment". Author: **Jonathan Rosen**, Quantitative Research, **FINCAD** (j.rosen@fincad.com). Dated **March 1, 2019**. SSRN abstract 3350745. 5 pages.

**Abstract (verbatim):** "The convexity adjustment for averaged overnight rate futures, like SOFR 1m futures, is derived including the case where trading occurs during the reference period. These results are more general than previous work that relied solely on the HJM framework, and the results herein can easily incorporate and reuse previous derivations. Numerical results demonstrate that the averaged overnight rate futures convexity adjustment is close to the convexity adjustment for compounded overnight rate futures, which is due to the close proximity of daily compounding to the continuous compounding limit."

### 2.1 Contract taxonomy (useful vocabulary for the codebase)

- **AONF** = averaged overnight rate futures (**Fed Funds futures, SOFR 1M**) — monthly reference period **beginning on the start of the contract month**, **7 consecutive months** available for spot trading.
- **CONF** = compounded overnight rate futures (**SOFR 3M**) — **quarterly reference period**, **20 consecutive quarters**, *"the reference period beginning on the third Wednesday IMM date of the contract month."*
- SOFR 1M futures emerged **May 2018**, "an important milestone".
- Both AONF and CONF can be **traded during the reference period** (unlike Eurodollar, whose LIBOR fixes at the start).

### 2.2 Derivation (verbatim structure)

- Arithmetic average rate **(Eq. 1):** `F_avg(t,T_0,T_n) = Σ_k δ_k r_k / Σ_k δ_k = (1/δ)·Σ_{k=1..n} [ P(t,T_{k−1})/P(t,T_k) − 1 ]`, with `P(t,T)` the price of a zero-coupon bond **funded at the overnight rate**, `δ = T_n − T_0`.
- Eurodollar-style CA **(Eq. 2):** `C_ED(T_0,T_n) = E^Q[ (1/δ)(P(T_0,T_0)/P(T_0,T_n) − 1) | F_0 ] − (1/δ)(P(0,T_0)/P(0,T_n) − 1)`.
- **Exact decomposition (Eq. 3):** *"As this is linear in the summation of Eq. (1) we have the immediate result that"*

  **`C_avg(T_0,T_n) = Σ_{k=1..n} (δ_k/δ) · C_ED(T_{k−1}, T_k)`**

  i.e. the averaged-ON CA is the **daily-weighted average of one-day Eurodollar CAs** over the reference period.
- **(Eq. 4/5):** `F_avg ≈ (1/δ)·log Π(1+δ_k r_k) = (1/δ)·Σ log[P(t,T_{k−1})/P(t,T_k)] = F_cont` — the continuously compounded forward is a good proxy for the arithmetic average.
- **Main result (Eq. 6):**

  **`C_avg(T_0,T_n) = Σ (δ_k/δ) C_ED(T_{k−1},T_k) ≈ Σ (δ_k/δ) C_cont(T_{k−1},T_k) = C_cont(T_0,T_n) ≈ C_cmpd(T_0,T_n)`**

  *"This result … is straightforward, but also more general than the HJM interest rate model framework which was required in the majority of previous work on futures convexity adjustments."*
- **In-period trading:** *"Before the reference period where 0 < T_0, the summation in Eq. (6) covers the entire reference period. As time advances and trading begins to occur during the reference period, then throughout we set T_0 = 0, and subsequently a term will be dropped from the summation on a daily basis as overnight rate fixings become available, which will lead to the trend of a diminishing convexity adjustment as trading moves through the reference period."* (Same qualitative result as Henrard's Theorem 2.)

### 2.3 Published numbers (tie-outs)

Model: **Vasicek, using the model specified in [5] (= Henrard 2018), volatility 65 bps, mean reversion 3%** — i.e. **the same parameter pair as Henrard**, deliberately reused so the two papers' figures are comparable. Valuation date **March 1, 2019**.

| Figure | Contract set | Printed / axis values |
|---|---|---|
| Fig 1a | SOFR **1M** futures CA, final day of reference month **03/19 → 10/19** | y-axis 0 → **0.07 bp** (ticks 0.01 … 0.07). Two series: "Daily Compounded O/N Rate" and "Average O/N Rate" (**chart read** — no table printed) |
| Fig 1b | compounded − averaged difference, SOFR 1M | y-axis 0 → **0.01 bp**; text: *"at realistic volatility and mean reversion levels the difference is **less than 0.01 basis points** for the entire range of SOFR 1m futures contracts which are traded"* (printed) |
| Fig 1c | SOFR **3M** futures CA, final day of reference quarter **03/19 → 02/24** | y-axis 0 → **4.5 bp** (ticks 0.5 … 4.5) — **chart read**: CA ≈ 4–4.5 bp at the ~5-year contract |
| Fig 1d | compounded − averaged difference, SOFR 3M | y-axis 0 → **0.35 bp**; text: *"the largest discrepancy between the two only reaching **about a third of a basis point**"* (printed) |

Text: *"Under the Vasicek model the compounded convexity adjustment is larger than in the case of averaging"*; SOFR 3M contracts *"extend much further in maturity, and at the long-end experience a larger convexity adjustment than for any SOFR 1m futures contracts."*

**References:** [1] Hunt & Kennedy (2004); [2] Andersen & Piterbarg (2010); [3] **Kirikos & Novak, "Convexity conundrums", Risk, March 1997, 60–61**; [4] **Fenger, "Convexity adjustment for FRAs and futures with multicurves", SSRN 2015**; [5] **Henrard, "Overnight futures: Convexity adjustment", SSRN 2018** (= doc 1 above); [6] **Mercurio, "A simple multi-curve model for pricing SOFR futures and other derivatives", SSRN 2018**; [7] **Takada, "Valuation of arithmetic average of Fed Funds rates and construction of the US dollar swap yield curve", SSRN 2011**.

**Absent:** no flies, packs/bundles, positioning, clearing basis, trade rules, or costs.

---

## 3. Ametrano & Bianchetti (2013) — multi-curve bootstrapping

**Exact identification.** Title: "Everything You Always Wanted to Know About Multiple Interest Rate Curve Bootstrapping But Were Afraid To Ask". Authors: **Ferdinando M. Ametrano** (Financial Engineering, Banca IMI, Milan) and **Marco Bianchetti** (Market Risk Management, Banca Intesa Sanpaolo, Milan; corresponding author). **First version 4 February 2013; this version 2 April 2013.** SSRN abstract 2219548. 82 pages. JEL E43, G12, G13. Also appears as a chapter in *Interest Rate Modelling After the Financial Crisis*, eds. Bianchetti & Morini, Risk Books, 2013. Implementation open-sourced in **QuantLib** (revision 18431, R01020x-branch), exposed via QuantLibAddin/QuantLibXL.

This is a curve-construction paper, not a trading paper. Its value to us is (a) the exact place the futures CA enters a bootstrap, (b) matched-swap/discount conventions, (c) a **fully self-consistent worked numeric example** we can use as a known-answer test of any HW convexity code and of a futures-strip bootstrap.

### 3.1 Futures pricing and the convexity adjustment (§4.3.3 and App. C.2)

- Futures payoff at payment date `T_{i−1}` (payer of floating): **(Eq. 52) `Futures(T_{i−1};T) = N[1 − L_x(T_{i−1},T_i)]`**. The authors call this "mixing apples and oranges" — it is *"merely a rule to compute the margin."*
- **(Eq. 53) `Futures(t;T) = N[1 − R^Fut_x(t;T)]`**, **(Eq. 54) `R^Fut_x(t;T) = F_{x,i}(t) + C^Fut_x(t;T_{i−1})`** — the futures rate is the FRA rate plus a convexity adjustment.
- App. C.2: **(Eq. 131–133)** since futures are margined, the stochastic discount factor is `D_c(t;t) = 1`, so `R^Fut_x(t;T) := E^{Q_f}_t[L_x(T_{i−1},T_i)] = E^{Q_f}_t[F_{x,i}(T_{i−1})]`, and since `F_{x,i}` is **not** a martingale under the risk-neutral funding measure, **(Eq. 134)** `R^Fut = F_{x,i}(t) + C^Fut_x(t;T_{i−1})`.
- Economic mechanism, verbatim: *"Convexity adjustment arises because of the daily marking to market and margination mechanism of Futures. An investor long a Futures contract will have a loss when the Futures price increases (and the Futures rate decreases) but she will finance such loss at lower rate. Viceversa, when the Futures price decreases, the profit will be reinvested at higher rate. This means that the volatility of the FRA rates and their correlation to the spot rates have to be accounted for…"*
- **Model menu cited:** Hull-White [44 = Kirikos & Novak, Risk 10(3):60–61, March 1997]; Libor Market Model [43 = Jäckel & Kawai, "The future is convex", Wilmott, Feb 2005] and [18 = Brigo & Mercurio]; two-factor Gaussian short rate [18]; stochastic volatility [45 = Piterbarg & Renedo, JCF 9(3), 2006]; one-factor HJM [46 = **Henrard**, "Eurodollar futures and options: Convexity adjustment in HJM one-factor model", SSRN, March 2009]; most advanced [42 = **Mercurio**, "Libor Market Models with Stochastic Basis", SSRN, March 2010]. *"The most common practitioners' recipe is that of [44], based on a simple short rate 1 factor Hull & White model [47]. This approach has been used in fig. 7 to calculate the adjustments."*
- **Multi-curve LMM CA (App. C.2, verbatim structure):**

  `C^Fut_x(t;T_{i−1}) ≈ F_{x,i}(t)·[ exp( ∫_t^{T_{i−1}} μ_{x,i}(u) du ) − 1 ]`, with
  `dF_{x,i}/F_{x,i} = μ_{x,i} dt + σ_{x,i} dW^{Q_f^{T_i}}_x`,
  `μ_{x,i}(t) := σ_{x,i} · Σ_{j=1..i} [ σ_{c,j} ρ_{x,c,j,i} τ_{c,j} F_{c,j}(t) / (1 + τ_{c,j} F_{c,j}(t)) ]`, and
  `∫_t^{T_{i−1}} μ_{x,i}(u) du ≈ σ_{x,i} Σ_j [σ_{c,j} ρ_{x,c,j,i} τ_{c,j}F_{c,j}(t)/(1+τ_{c,j}F_{c,j}(t))] · τ(t,T_{j−1})`
  where `F_{c,j}(t) := E^{Q_f^{T_j}}_t[L_c(T_{j−1},T_j)] = (1/τ_{c,j})[P_c(t;T_{j−1})/P_c(t;T_j) − 1]` (**Eq. 135**).
- **Related result (market-FRA convexity, §4.3.2 / App. C.1):** the *market* FRA (settled at `T_{i−1}`, discounted by the fixing) carries its own convexity `C^{FRA}_{c,x}(t;T_{i−1}) = −σ_{x,i}·(σ_{x,i} − σ_{c,i}ρ_{c,x,i})·τ(t,T_{i−1})` under shifted-lognormal dynamics (**Eq. 130**), and **"For typical post credit crunch market situations, the actual size of the convexity adjustment results to be below 1 bp, even for very long maturities"** — so they discard it. Do **not** confuse this sub-1bp FRA-vs-standard-FRA convexity with the futures CA.

### 3.2 Futures contract conventions (EUR / Euribor3M IMM)

- Schedule `T_i = [T_i^F, T_i^e, T_i]` with `τ(T_i^F, T_i^e) =` settlement lag (2 business days) and `τ_L(T_i^e, T_i) = 3M`; schedule shared with the underlying FRA 3M.
- **IMM Futures fix and stop trading the third Monday of the expiry month and expire the following Wednesday.** *"such date grid is not regular: in general `T_i ≠ T^e_{i+1}`, so Futures' dates do not concatenate exactly."* (Contrast with SR3, where reference periods do concatenate IMM→IMM — see Henrard §1.1.)
- Lot size **EUR 1,000,000**; margin **(Eq. 55)** `Δ(t,t−1;T) = (N′/n)·[Futures(t;T) − Futures(t−1;T)]`, `n` = tenor in months (`n = 4` for quarterly futures — as printed; note this is inconsistent with "tenor in months" for a 3M contract and looks like a typo in the paper).
- Liquidity: *"The first front contract is one of the most liquid interest rate instruments, with longer expiry contracts having very good liquidity up to the **8th-12th contract**."* Serial futures also traded (quite liquid, especially when expiring before the front quarterly).
- Quotation **(Eq. 56)** `Futures(t;T) = 100 × [1 − R^Fut_x(t;T)]`.
- Bootstrap use: **(Eq. 57)** `F_{x,i}(t_0) = R^Fut_x(t_0;T_i) − C^Fut_x(t_0;T^e_i)` and **(Eq. 58)** `P_x(t_0,T_i) = P_x(t_0,T_{i−1}) / {1 + [R^Fut − C^Fut]·τ_L(T^e_i,T_i)}`.
- Rolling: futures have fixed, not rolling, expirations, so *"Futures used as bootstrapping instruments … generate rolling pillars that periodically jumps and overlap the fixed Depo Deposit and FRA pillars. Hence some **priority rule** must be used."* §5.3: on the first futures' fixing (Monday 17 Dec 2012 in the example) the strip is rolled — first contract dropped, a new one added at the back; *"the Futures rolling can be executed before the first Futures fixing date, in case of lowered market liquidity of the first Futures."*

### 3.3 Published numbers — the Hull-White CA table (primary tie-out)

**Table 1 — "Hull-White parameters values for Futures3M convexity adjustment as of 11 Dec. 2012":**

| HW parameter | Value |
|---|---|
| Mean reversion | **3%** |
| Volatility | **0.3526%** |

**Figure 7 — "EUR Futures on Euribor 3M … Source: Reuters page 0#FEI, as of 11 Dec. 2012. In column 5 are reported the corresponding convexity adjustments, calculated as discussed in the text."** (bid/ask/mid in %, CA in %, underlying Euribor3M):

| Instrument | Bid | Ask | Mid | **Convexity adj.** | Underlying start | Underlying end |
|---|---|---|---|---|---|---|
| FUT 3MZ2 | 99.8200 | 99.8250 | 99.8225 | **0.0000%** | Wed 19 Dec 2012 | Tue 19 Mar 2013 |
| FUT 3MF3 | 99.8450 | 99.8500 | 99.8475 | **0.0000%** | Wed 16 Jan 2013 | Tue 16 Apr 2013 |
| FUT 3MG3 | 99.8450 | 99.8650 | 99.8550 | **0.0001%** | Wed 20 Feb 2013 | Mon 20 May 2013 |
| FUT 3MH3 | 99.8700 | 99.8750 | 99.8725 | **0.0001%** | Wed 20 Mar 2013 | Thu 20 Jun 2013 |
| FUT 3MM3 | 99.8750 | 99.8800 | 99.8775 | **0.0003%** | Wed 19 Jun 2013 | Thu 19 Sep 2013 |
| FUT 3MU3 | 99.8700 | 99.8750 | 99.8725 | **0.0006%** | Wed 18 Sep 2013 | Wed 18 Dec 2013 |
| FUT 3MZ3 | 99.8400 | 99.8450 | 99.8425 | **0.0009%** | Wed 18 Dec 2013 | Tue 18 Mar 2014 |
| FUT 3MH4 | 99.8000 | 99.8050 | 99.8025 | **0.0013%** | Wed 19 Mar 2014 | Thu 19 Jun 2014 |
| FUT 3MM4 | 99.7400 | 99.7450 | 99.7425 | **0.0018%** | Wed 18 Jun 2014 | Thu 18 Sep 2014 |
| FUT 3MU4 | 99.6850 | 99.6900 | 99.6875 | **0.0024%** | Wed 17 Sep 2014 | Wed 17 Dec 2014 |
| FUT 3MZ4 | 99.6150 | 99.6200 | 99.6175 | **0.0030%** | Wed 17 Dec 2014 | Tue 17 Mar 2015 |
| FUT 3MH5 | 99.5550 | 99.5600 | 99.5575 | **0.0036%** | Wed 18 Mar 2015 | Thu 18 Jun 2015 |
| FUT 3MM5 | 99.4750 | 99.4800 | 99.4775 | **0.0044%** | Wed 17 Jun 2015 | Thu 17 Sep 2015 |
| FUT 3MU5 | 99.3800 | 99.3850 | 99.3825 | **0.0051%** | Wed 16 Sep 2015 | Wed 16 Dec 2015 |
| FUT 3MZ5 | 99.2750 | 99.2800 | 99.2775 | **0.0060%** | Wed 16 Dec 2015 | Wed 16 Mar 2016 |
| FUT 3MH6 | 99.1650 | 99.1700 | 99.1675 | **0.0069%** | Wed 16 Mar 2016 | Thu 16 Jun 2016 |
| FUT 3MM6 | 99.0350 | 99.0400 | 99.0375 | **0.0079%** | Wed 15 Jun 2016 | Thu 15 Sep 2016 |
| FUT 3MU6 | 98.9050 | 98.9150 | 98.9100 | **0.0090%** | Wed 21 Sep 2016 | Wed 21 Dec 2016 |
| FUT 3MZ6 | 98.7700 | 98.7850 | 98.7775 | **0.0100%** | Wed 21 Dec 2016 | Tue 21 Mar 2017 |
| FUT 3MH7 | 98.6500 | 98.6650 | 98.6575 | **0.0111%** | Wed 15 Mar 2017 | Thu 15 Jun 2017 |
| FUT 3MM7 | 98.5200 | 98.5450 | 98.5325 | **0.0124%** | Wed 21 Jun 2017 | Thu 21 Sep 2017 |
| FUT 3MU7 | 98.4000 | 98.4250 | 98.4125 | **0.0136%** | Wed 20 Sep 2017 | Wed 20 Dec 2017 |

So under HW(a=3%, σ=0.3526%) the EUR 3M CA runs **0.00 bp at the front to 1.36 bp at ~5y** (0.0136% = 1.36 bp). Compare: Henrard's GBP HW(3%, 65bp) gives ≈7 bp at 7y and Rosen's Vasicek(3%, 65bp) gives ≈4–4.5 bp at 5y — the 0.3526% vol used here is ~5.4× smaller than 65bp, which is why the numbers differ by roughly that factor. **When using these as tie-outs, always carry the (a, σ) pair with the number.**

**Verified arithmetic chain (I checked this myself — it is a genuine end-to-end known-answer test).** Figure 29 gives the futures leg of the Euribor3M bootstrap inputs, and each rate equals `(100 − mid)/100 − CA` from Figure 7:

| Bootstrap instrument | Fig-7 mid | implied futures rate | minus CA | **Fig-29 input rate** | start | end |
|---|---|---|---|---|---|---|
| EUR_YC3M_FUT3MZ2 | 99.8225 | 0.1775% | −0.0000% | **0.1775%** | Wed 19 Dec 2012 | Tue 19 Mar 2013 |
| EUR_YC3M_FUT3MH3 | 99.8725 | 0.1275% | −0.0001% | **0.1274%** | Wed 20 Mar 2013 | Thu 20 Jun 2013 |
| EUR_YC3M_FUT3MM3 | 99.8775 | 0.1225% | −0.0003% | **0.1222%** | Wed 19 Jun 2013 | Thu 19 Sep 2013 |
| EUR_YC3M_FUT3MU3 | 99.8725 | 0.1275% | −0.0006% | **0.1269%** | Wed 18 Sep 2013 | Wed 18 Dec 2013 |
| EUR_YC3M_FUT3MZ3 | 99.8425 | 0.1575% | −0.0009% | **0.1565%** | Wed 18 Dec 2013 | Tue 18 Mar 2014 |
| EUR_YC3M_FUT3MH4 | 99.8025 | 0.1975% | −0.0013% | **0.1961%** | Wed 19 Mar 2014 | Thu 19 Jun 2014 |
| EUR_YC3M_FUT3MM4 | 99.7425 | 0.2575% | −0.0018% | **0.2556%** | Wed 18 Jun 2014 | Thu 18 Sep 2014 |
| EUR_YC3M_FUT3MU4 | 99.6875 | 0.3125% | −0.0024% | **0.3101%** | Wed 17 Sep 2014 | Wed 17 Dec 2014 |

(Three rows differ by 0.0001% from naive subtraction — Z3, H4 and M4 — consistent with the CA column being rounded to 4 dp before printing. The other five are exact.) Note the strip used in the bootstrap is **8 quarterly contracts only (Z2, H3, M3, U3, Z3, H4, M4, U4)** — the serials F3/G3 and the front-month overlap with deposits are deliberately excluded to avoid overlaps.

### 3.4 Other published market data in the paper (11 Dec 2012 EUR, Reuters close ≈16:30 CET)

All usable as bootstrap fixture data; all mid = (bid+ask)/2 unless noted.

- **Fig. 4 — EUR Deposit strip (Reuters KLIEM), ask %:** ON 0.040, TN 0.040, SN 0.040, 1W 0.070, 2W 0.080, 3W 0.110, 1M 0.110, 2M 0.140, 3M 0.180, 4M 0.220, 5M 0.270, 6M 0.320, 7M 0.350, 8M 0.390, 9M 0.420, 10M 0.460, 11M 0.500, 12M 0.540. Conventions per row: settlement Today/Tomorrow/Spot, Following (<1M) vs Modified Following + end-of-month = True (≥1M), TARGET calendar, ACT/360 for the rate, ACT/365F for zero rates.
- **Fig. 6 — FRA strips (Reuters ICAPSHORT2):** Euribor3M FRA Tod3M 0.181 mid … 6x9 0.121; Euribor6M FRA Tod6M 0.316 … 18x24 0.409; FRA 12x24 (Euribor12M) 0.507; **IMM FRA** IMMF3/IMMG3/IMMH3/IMMJ3 mids quoted as prices 99.7110 / 99.7310 / 99.7410 / 99.7450.
- **Fig. 9 — EUR IRS vs Euribor6M (ICAPEURO), annual fixed 30/360 vs semi-annual float:** 1Y 0.286, 2Y 0.324, 3Y 0.424, 5Y 0.762, 10Y **1.584**, 20Y 2.187, 30Y 2.256, 60Y 2.463 (mids).
- **Fig. 10 — EUR IRS vs Euribor3M:** 1Y 0.141, 2Y 0.186, 3Y 0.285, 5Y 0.623, 10Y 1.459, 30Y 2.186, 50Y 2.367; plus **IMM-starting IRS** AB3EZ2 0.138, AB3EH3 0.134, AB3EM3 0.151, AB3EU3 0.183, AB3EZ3 0.183, AB3EH4 0.208, AB3EZ4 0.283.
- **Fig. 11 — EUR IRS vs Euribor1M:** 2M 0.106 … 12M 0.063.
- **Fig. 13 — EUR OIS on Eonia (ICAPSHORT1/ICAPEURO2):** 1W 0.070, 1M 0.074, 3M 0.047, 6M 0.018, **1Y 0.000**, 2Y 0.036, 5Y 0.456, 10Y 1.280, 30Y 2.038; **forward-starting OIS on ECB dates** EONECBFEB13 0.046, MAR13 0.016, **APR13 −0.007, MAY13 −0.013, JUN13 −0.014, JUL13 −0.016** (negative mids).
- **Fig. 15 — EUR basis swaps (ICAPEUROBASIS), spread in bp, quoted as two IRS with identical annual fixed legs:** 1M-vs-6M 1Y 22.20, 5Y 25.00, 10Y 23.70, 30Y 16.30; 3M-vs-6M 1Y 14.50, 5Y 13.95, 10Y 12.50, 30Y 7.00, 50Y 5.40; 6M-vs-12M 1Y 26.20, 5Y 15.10, 10Y 11.30, 30Y 6.60. Convention: *"the difference (in basis points) between the fixed rate of the higher frequency IRS and the fixed rate of the lower frequency IRS"*; **(Eq. 86)** `R^IRS_x = R^IRS_6M + Δ(t;T_x,T_6M,S)`.
- **Fig. 25/27/29/31/33** — the actual per-curve bootstrap instrument lists (Eonia, Euribor1M/3M/6M/12M) with rates and start/end dates, including synthetic deposits and synthetic FRA. Sample: Euribor6M curve uses 9 synthetic depos (SND 0.3565% … 5MD 0.3225%), 19 market FRA 6M (Tom6M 0.3120% … 18x24 0.4090%), then IRS 6M 3Y–60Y; the Euribor12M curve uses synthetic depos 1M 0.6537% / 3M 0.6187% / 6M 0.5772% / 9M 0.5563%, market 12MD 0.5400%, six FRA 12M (3x15 0.4974% … 18x30 0.6025%, only 12x24 = 0.5070% is a market quote), then IRS 12M implied from IRS 6M + IRBS.
- **Fig. 17/18 — synthetic instrument construction with the FRA-OIS basis polynomial (Eq. 89/90):** e.g. Fut 3MZ2 row: quote 0.1775%, OIS 0.0415%, FRA-OIS basis 0.1359%, α = 0.1148, β = 0.0002; FRA 1x7 row: 0.2930% / 0.0027% / 0.2903%, α = 0.3166, β = −0.0001. *"Since the β coefficients are very small, the constant FRA-OIS basis approximation is sufficient."*

### 3.5 Turn-of-year (relevant because IMM December contracts always straddle it)

- Historical Euribor1M fixing jumps (Fig. 23, source Reuters): **2007 turn of year +64 bp on 29 Nov 2007**; **2008 turn of year +22 bp on 27 Nov 2008**; **end-of-semester +9 bp on 29 May 2008**.
- *"the **December IMM Futures always include a jump**, as well as the October and November serial Futures; 2Y Swaps always include two jumps"*; the 12M deposit always includes a jump except 2 business days before year end (end-of-month rule).
- Bootstrapped jump sizes in the 11 Dec 2012 example: **ON curve +10.2 bp (2 Jan 2013) and +8.5 bp (2 Jan 2014)**; the **1M** curve shows the 2014 jump as **+1.8 bp (1 Dec 2013) / −1.6 bp (2 Jan 2014)** — *"size roughly equal to 1/20 of the ON jumps"*; the **3M** curve shows **+0.6 bp (1 Oct 2013) / −0.5 bp (2 Jan 2014)** — *"roughly equal to 1/3 of the 1M jump."*
- Four estimation methods listed for the jump coefficient (jump in the Futures 3M strip; in the FRA 6M strip; in the IRS 1M strip; in the brokers' Monday FRA strip), with the caveat that the futures method cannot see the *first* turn of year after the third Wednesday of September.
- Also: a single turn of year produces **one** discontinuity in zero/discount curves but **two** in the FRA-rate curve.

### 3.6 Conventions, discounting and hedging points relevant to a matched-swap CA definition

- Modern recipe: **OIS discounting**, one discount curve per funding/collateral regime; forwarding curves homogeneous in tenor; futures are exchange-margined so priced under the risk-neutral funding measure with unit discount factor; OTC instruments under CSA are priced with collateral discounting (Eq. 13/14: `Π(t) = P_c(t,T)·E^{Q_f^T}[Π(T)]`).
- **Telescoping fails in multi-curve:** *"the classical telescopic property of IRS rates … does not hold, even as an approximation, because in the modern multiple-curve world the discount rate and the FRA rate belongs to two different yield curves"* (Eq. 64/65). For **OIS** it does still collapse: **(Eq. 74/150)** OIS float leg = `N[P_c(t;T_0) − P_c(t;T_n)]`, `R^OIS = (P_c(T_0) − P_c(T_n))/A_c(t;S)`. This matters: a *SOFR* matched swap is an OIS, so the single-curve simplification is legitimate for the swap leg of the CA.
- Zero-rate convention **ACT/365F** (must be additive and monotone), FRA/Libor rate convention **ACT/360**, IRS fixed leg **30/360 bond basis**, calendar TARGET; reference date = spot (T+2) except ON/TN deposits which anchor the curve to today.
- **Interpolation:** linear on zero rates or on log-discounts is *"horrible"* for forwards (*"nasty oscillations up to tens of basis points"*); their preferred scheme is **Hyman monotonic cubic filter applied to spline interpolation of log-discounts**. Non-local interpolation ⇒ non-local (smeared) delta, requires iterative bootstrap, and slows sensitivity computation. Relevant to us: a fly built from an interpolated curve inherits interpolation artefacts of exactly this magnitude.
- **Delta/hedging formalism (§4.9):** `Δ^Π_{j,k} = ∂Π/∂R_{j,k}`, decomposed as `Δ_j = J_j·∇_j Π` with Jacobian `J_{j,k,α} = ∂z_{j,α}/∂R_{j,k}`; for exogenous (OIS-discounted) multi-curve bootstrap the Jacobian picks up the cross term **(Eq. 96)** `J_{j,k,α} = δ_{j,1}·∂z_{j,α}/∂R_{j,k} + (1−δ_{j,1})[∂z_{j,α}/∂R_{j,k} + ∂z_{j,α}/∂R_{1,k}]`. Hedge ratios **(Eq. 99)** `H_{j,h} = −Δ^Π_{j,h}(t;R^H) / δ^Π_{j,h}(t;R^H)` where `δ^Π_{j,h} = ∂π^H_{j,h}/∂R^H_{j,h}`, i.e. **hedge notional = portfolio DV01 at that pillar divided by the hedge instrument's own DV01 at that pillar** — the same construction we need for CA-vs-fly leg weights. Assumes static hedge ratios (`∂H/∂R ≈ 0`).
- **Curve QA (§4.11), four checks**, of which #4 is directly our validation route: *"instruments quoted on the market but not included in the bootstrapping should be repriced within their bid-ask window. A typical example are quotes of **long term Futures** and forward starting IRS."*
- Endogenous vs exogenous bootstrapping: the difference on FRA/IRS rates is *"small but non-negligible, ranging from zero to a couple of basis points"* (Fig. 22) — i.e. **using the wrong discount curve moves a fly by ~1–2 bp**, comparable to the whole CA at the front of the strip.
- Negative rates: bootstrapped ON FRA curve on 11 Dec 2012 goes negative in the 3M–12M window with a **minimum of −1.8 bp in the second week of Aug 2013**; discount factors non-monotone there. (Text says "up to −2 bps" in the Fig. 21 caption; the body says −1.8 bp.)
- Precision bar quoted for trading purposes: *"the fit quality is typically not good enough for trading purposes in liquid interest rate markets, where **0.25 basis points can make the difference**."*

### 3.7 Tenor-basis worked example (§4.3.2) and two anti-tie-outs

**Worked tenor-basis example (a real tie-out).** As of 11 Dec 2012: 1x4 FRA3M (14 Jan → 15 Apr 2013, `τ_L = 0.25278`) at **0.165%** and 4x7 FRA3M (15 Apr → 15 Jul 2013, `τ_L = 0.25278`) at **0.126%** compound (Eq. 49) to an implied 1x7 FRA6M (14 Jan → 15 Jul 2013, `τ_L = 0.50556`) of
`[(1+0.165%·0.25278)(1+0.126%·0.25278) − 1]/0.50556 = **0.146%**`,
versus the market 1x7 FRA6M at **0.293%** — **14.7 bp larger**. Verbatim: *"The 14.7 basis points are the price assigned by the market to the different liquidity/default risk implicit in the two investment strategies."* (I re-derived 0.146% from the Fig. 6 mids; it reproduces.)

**Anti-tie-out #1.** In that same passage the text prints the 4x7 FRA3M level as **"1.580%"**, which contradicts both Figure 6 (mid **0.126%**) and the paper's own arithmetic (1.580% cannot produce 0.146%). Stale/typo — use 0.126%.

**Anti-tie-out #2.** Line ~1867 of the markdown (§4.3.5 lead-in, the 9Y→10Y Euribor6M bootstrap illustration) uses **`R^IRS_6M(T_0;10Y) = 3.488%`**, which contradicts the paper's own Figure 9 (10Y Euribor6M mid **1.584%** as of 11 Dec 2012). This is a **stale number carried over from the authors' earlier (2009) paper** and is not consistent with the 2012 data set. Treat Eq. 69/70 as structurally correct but the 3.488% as fiction.

Both artefacts are the same failure mode: prose examples were not refreshed when the market data set was. **Only the tabulated figures (Figs. 4, 6, 7, 9–18, 25–34) and Table 1 should be used as fixtures.**

---

## 4. Synthesis for the SR3 CA-vs-swap-fly programme

**What this group gives us**

1. **A defensible fair-value CA model with an agreed parameterisation.** Henrard (Gaussian HJM / HW1F, Theorem 1 & 2) is the reference implementation for an SR3 CA; Rosen shows the averaged-rate (FF, SR1) CA is the daily-weighted sum of the same one-day Eurodollar CAs and is numerically ≈ the compounded CA. **Both papers use `a = 3%`, `σ = 65 bp`** — one of them explicitly borrowing from the other — so that pair is the natural default for a first-pass CA model, with Ametrano's `a = 3%`, `σ = 0.3526%` as the low-vol EUR-2012 anchor.
2. **Magnitude scale for the tradable object.** At HW/Vasicek(3%, 65bp): SR3 CA ≈ **0–0.5 bp in Whites**, **~1–2 bp in Reds**, **~4–4.5 bp by the 5-year contract** (Rosen Fig 1c), rising to **~7 bp at 7 years** in Henrard's GBP example. SR1/FF CA is **≤0.07 bp** across the traded 7-month strip — effectively zero. Implication: a Golds-vs-Blues CA structure carries several bp of model CA, whereas anything in Whites is CA-noise, and **CA-based RV is only meaningful from Reds outwards**.
3. **The exact matching rules for the swap leg.**
   - SR3 reference periods run **IMM→next IMM** and therefore *do* concatenate; ED/Euribor futures run **IMM→IMM+3M** and *do not* (Ametrano §4.3.3). A "matched-maturity forward swap" for an SR3 pack/bundle must span `T_s` of the first contract to `T_e` of the last, using the actual IMM dates, not 3M-tenor rolls.
   - The matched OIS **settles T+2 after end accrual** in USD while the future settles at `T_e` (Henrard). That is a small but real systematic wedge in any CA time series; it should be either modelled or absorbed into the "measured CA" definition consistently across the whole history.
   - The SR3 settlement rate is a **simple** rate equivalent to compounded ON investment (Eq. 1) — so the matched swap must be a compounded-SOFR OIS with the same compounding convention, ACT/360, not an average-rate leg.
   - Discount curve choice moves swap rates by **0–2 bp** (Ametrano Fig. 22) — of the same order as the CA in the front half of the strip. The CA time series must be built with one fixed, consistent (OIS-discounted, exogenous) curve convention, or the "CA" will be part discounting artefact.
4. **A front-contract decay effect that must be in the backtest.** Both papers derive that once a contract enters its reference quarter, the fixed portion carries **no** convexity, so CA decays deterministically to zero across the quarter (Henrard Thm 2; Rosen "a term will be dropped from the summation on a daily basis"). A CA-vs-fly spread on Whites therefore has a **mechanical, non-mean-reverting drift** component. Do not let a mean-reversion signal harvest it.
5. **Known-answer tests we can wire up immediately.**
   - HW(3%, 0.3526%) EUR CA table (§3.3, 22 contracts, 11 Dec 2012) — reprice the CA column.
   - The `futures rate − CA = bootstrap FRA rate` chain (§3.3, 8 contracts) — reprices to 0.0001% except for print rounding; verified by hand here.
   - Rosen's printed inequalities: SR1 avg-vs-compounded difference **< 0.01 bp**; SR3 avg-vs-compounded max difference **≈ 0.33 bp**. Any implementation whose average/compounded gap is materially larger at 3%/65bp is wrong.
   - Henrard's "daily in-period terms ≈ 0.01 bp each" and "first term γ(0,Ts,Ts,Te) ≈ full adjustment" — a cheap structural check on a CA implementation.
6. **Turn-of-year**: December IMM contracts always straddle a year end (Ametrano §4.8). Historically the ON jump has been **+64 bp (2007)**, **+22 bp (2008)**, **+10.2 / +8.5 bp (2013/2014 as priced in Dec-2012)**, damped to **~1/20** at 1M tenor and **~1/3 of that** at 3M tenor. Any Dec-contract CA or fly residual will show a seasonal that is a **funding/technical effect, not convexity** — flag and either model or exclude December belly positions.

**What this group does not give us (state plainly, do not extrapolate):** no dealer-positioning conditioning, no CFTC data, no CME–LCH basis level/term structure/hedging, no pack/bundle/butterfly weighting conventions in futures space, no fitted CA-vs-fly regression (no "Blues CA = a + b·fly" style equation, no R², no coefficients), no entry/exit/target/stop rules, and **no transaction costs of any kind** in any of the three papers.
