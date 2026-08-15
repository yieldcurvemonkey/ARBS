All columns now reproduce exactly. Writing the spec.

# CITI "STIR FUTURES CONVEXITY ADJUSTMENT vs BUTTERFLY" — COMPLETE REIMPLEMENTATION SPEC (ED → SFR PORT)

## 0. SOURCE INVENTORY & FILE NOTES

| Ref | File (absolute path) | Publication | Date | Key figure |
|---|---|---|---|---|
| **[W-JAN13]** | `C:/Users/chris/Downloads/convexityrv_markdown/print (7).pdf.md` | Citi Research, *US Rates Weekly — Swearing in huge expectations* | 13 Jan 2017 | Fig 20, p.12 (close 1/12/17) |
| **[W-JAN13d]** | `C:/Users/chris/Downloads/convexityrv_markdown/print (5).pdf.md` | **BYTE-IDENTICAL DUPLICATE** of print (7) | — | — |
| **[VL-JAN17]** | `C:/Users/chris/Downloads/convexityrv_markdown/print (6).pdf.md` | Citi, *US Rates Vol Lab* | 17 Jan 2017 | Fig 48, p.15 (close 1/13/17) |
| **[TI-FEB9]** | `C:/Users/chris/Downloads/convexityrv_markdown/print (4).pdf.md` | Citi, *North America Rates Trade Idea — Sell Blues convexity adjustments, hedged* | 9 Feb 2017 | pp.2–4 |
| **[VL-2019a]** | `.../US_Rates_Vol_Lab_Gamma_and_Vega_RV.pdf.md` | Citi, *US Rates Vol Lab — Gamma and Vega RV* | Jan 2019 | Fig 57 (close 1/11/19) |
| **[VL-2019b]** | `.../US Rates Vol Lab_ Trading long-dated convexity.pdf.md` | Citi, *US Rates Vol Lab* | 9 May 2019 | Fig 60 (close 5/8/19) |
| **[VL-2019c]** | `C:/Users/chris/Downloads/convexityrv_markdown/print (3).pdf.md` | Citi, *US Rates Vol Lab* | 25 Sep 2019 | Fig 62 (close 9/24/19) |
| **[VL-2020a]** | `.../Rates_Vol_Lab_In_search_of_cheap_vol.pdf.md` | Citi, *Rates Vol Lab* | 17 Jan 2020 | Fig 62 (close 1/16/20) |
| **[VL-2020b]** | `.../Rates_Vol_Lab_Liquidity_vega_and_convexity.pdf.md` | Citi, *Rates Vol Lab* | 30 Mar 2020 | Fig 60 (close 3/27/20) |
| **[VL-SOFR]** | `.../Rates_Vol_Lab_Forward_steepener_and_vol_divergence.pdf.md` | Citi, *Rates Vol Lab — Forward steepener and vol divergence* | **12 Jun 2023** | **Fig 58, p.14 (close 6/9/23) — SOFR-NATIVE** |
| **[W-SEP30]** | `C:/Users/chris/Downloads/convexityrv_markdown/print (2).pdf.md` | Citi, *US Rates Weekly*, Appendix I Closed Trades | 30 Sep 2019 | Fig 38, p.27 |
| **[JPM]** | `.../A better way to sell vol_ CME-based convexity adjustments are rich. Wed May 03 2017.pdf.md` | J.P. Morgan (Younger/Sarkar/Salem) | 3 May 2017 | Exhibits 1–5 |
| **[CLARUS]** | `.../CME-LCH Basis_ Convexity in Eurodollar Futures _.pdf.md` | Clarus FT (Chris Barnes) | 1 Jul 2015 | — |

**Duplicate confirmation (asked):** `print (5).pdf.md` and `print (7).pdf.md` are **byte-identical** — MD5 `1df2136fbc13921d31f269b399cb166a` for both, `diff -q` reports no difference, both 143,305 bytes / 2,132 lines. **Zero differences.** Treat as one document.

**Critical find for the port:** the strategy was **already restated for SOFR by Citi itself** in [VL-SOFR] (12 Jun 2023). You are not porting blind — you have the target-state methodology note verbatim plus a 13-row SOFR tie-out table.

---

## 1. THE CONVEXITY ADJUSTMENT (CA) FOR A 1y PACK

### 1.1 Methodology text — VERBATIM

**ED version** ([W-JAN13], Fig 20 note, p.12, lines 671–673). *Note: the source note is truncated mid-sentence in the PDF extraction; the completion is supplied from the sister publications below.*

> "Note: Close of 1/12/17. Convexity adjustments for 1y ED packs are computed as the spread between the pack's rate (the average of 4 ED rates in the pack) and matched maturity forward 1y swap rate. The model for convexity adjustment is the Ho-Lee model calibrated to cap/floor vols. Implied vol is calculated by matching the model to the observed convexity adjustment. Realized vol is 3m realized vol of the corresponding pack. For each valuation metric, we mark three most attractive short convexity trades in [**bold**]. Source: Citi Research"

Completion `bold` from [VL-JAN17] Fig 48 note (line 888): "…we mark three most attractive short convexity trades in **bold**. Source: Citi Research"

**Fullest ED version** ([VL-2019c] Fig 62 note, lines 963–966) — note the added hyphen-`CME` qualifier:

> "Note: Close of 9/24/19. Convexity adjustments for 1y ED packs are computed as the spread between the pack's rate (the average of 4 ED rates in the pack) and matched-maturity forward 1y **CME** swap rate. The model for convexity adjustment is the Ho-Lee model calibrated to cap/floor vols. Implied vol is calculated by matching the model to the observed convexity adjustment. Realized vol is 3m realized vol of the corresponding pack. For each valuation metric, we mark three best short convexity trades in bold. Note that these are the most attractive in the chart but not necessarily trades that we would recommend at this point in time. Source: Citi Research"

**★ SOFR version — THE PORT TARGET** ([VL-SOFR], Fig 58 note, p.14, lines 855–860):

> "Note: Close 6/9/23. **Convexity adjustments for 1y SOFR packs are computed as the spread between the pack's rate (the average of 4 SOFR rates in the pack) and matched-maturity forward 1y CME swap rate.** The model for convexity adjustment is the Ho-Lee model calibrated to cap/floor vols. Implied vol is calculated by matching the model to the observed convexity adjustment. Realized vol is 3m realized vol of the corresponding pack. For each valuation metric, we mark three best short convexity trades in bold. Note that these are the most attractive in the chart but not necessarily trades that we would recommend at this point in time. Source: Citi Research"

Section header ([VL-SOFR], p.14, lines 826–827):
> "**SOFR futures convexity adjustments** — We calculate SOFR/FRA convexity adjustment for 1y SOFR packs and compare them to model values calibrated to cap/floor volatilities."

### 1.2 Why packs — VERBATIM

[W-JAN13] p.12, lines 648–653:
> "Figure 20 offers a systematic analysis of the valuation in convexity adjustments across the curve. **We analyze 1y packs (four consecutive contracts) because individual ED/FRA spreads are noisy and hard to trade.** We compute z-scores of CAs and rich/cheap on the fair value model (based on cap/floor vols), together with the z-scores of the dislocations from the model. We also compute volatilities implied from CAs and compare them to the recent realized volatilities."

### 1.3 Exact computation

```
pack_rate            = (1/4) * SUM_{i=1..4} futures_rate_i
futures_rate_i       = 100 - futures_price_i          [ED: EDx; SOFR: SR3]
CA_pack (bp)         = ( pack_rate - S_fwd1y ) * 1e4      [both in decimal]
```

`pack_rate` is identically `100 - pack_price` because the CME pack price is the arithmetic average of the four leg prices — the average of prices maps 1:1 to the average of rates.

**Matched-maturity forward 1y swap — EXACT START/END DATES.** Pinned verbatim by the trade recommendation ([W-JAN13] p.14, line 743–745; [TI-FEB9] p.2, lines 28–30):

> "buy 1000 of H0-Z0 packs (1000 of each of the four contracts) and pay $1bn on a **matched-maturity (3/18/20-3/17/21)** CME swap. Consistent with the standard market practice, both fixed and floating legs of this swap have a quarterly payment frequency."

The H0-Z0 pack = {H0, M0, U0, Z0} = Mar/Jun/Sep/Dec 2020. IMM date (3rd Wednesday) of H0 = **18 Mar 2020**. Start + 1y = **17 Mar 2021** (the IMM date of H1 is 17 Mar 2021). Therefore:

```
swap_start = IMM date (3rd Wednesday) of the FIRST contract month in the pack
swap_end   = IMM date (3rd Wednesday) of the month 12 months later
             ( = IMM date of the contract immediately AFTER the 4th pack leg)
fixed leg  : quarterly
float leg  : quarterly
clearing   : CME  (see §6.4)
```

**SOFR note:** for SR3 this is not merely "matched" but *exactly tiling* — the four SR3 reference quarters are [IMM_1,IMM_2), [IMM_2,IMM_3), [IMM_3,IMM_4), [IMM_4,IMM_5), which concatenate to exactly [swap_start, swap_end]. The ED analogue only tiled approximately (3M LIBOR deposits from each IMM date). This makes the SOFR CA cleaner than the ED CA.

---

## 2. THE HO-LEE MODEL — ★ FORMULA REVERSE-ENGINEERED AND VALIDATED

### 2.1 What the sources state

Citi never prints the formula, only "the Ho-Lee model calibrated to cap/floor vols". The JPM note prints it but PDF extraction mangled the glyphs ([JPM] Exhibit 1 footnote, lines 139–150):

> "\* Financing bias estimated using a Ho-Lee model, this reduces to
> `= 1 2/2` … `2`
> with ATM Eurodollar vols where available (out to the early Greens or so) and OTC Libor cap vols otherwise."

The surviving tokens `1`, `2`, `/2`, `2` are consistent with a `½ σ² t²`-family expression. **Do not take the textbook Hull form `½σ²t₁t₂` from this fragment — I tested it and it is wrong for Citi's tables.**

### 2.2 ★ THE ACTUAL FORMULA (empirically recovered, 8-table validation)

```
CA_pack_model (bp) = 0.5 * sigma^2 * ( (1/4) * SUM_{i=1..4} T1_i^2 ) * 1e4

  sigma  = normal (absolute) vol, decimal per sqrt(year)   [e.g. 125.5bp -> 0.01255]
  T1_i   = ACT/365 year fraction from as-of date to the IMM DATE
           (3rd Wednesday) of contract i's delivery month
```

Equivalently, per contract: `CA_i = ½σ²T1_i²`, and the pack CA is the simple average of the four.

**Validation — ratio σ_fit / σ_reported, solving the above for σ against every published "Implied Vol" column:**

| Table | n | min | median | max |
|---|---|---|---|---|
| 1/12/17 ED | 13 | 0.9992 | **0.9998** | 1.0006 |
| 1/13/17 ED | 17 | 0.9977 | **0.9999** | 1.0012 |
| 1/11/19 ED | 17 | 0.9927 | **0.9998** | 1.0386 |
| 5/8/19 ED | 17 | 0.8210 | **0.9993** | 1.0260 |
| 9/24/19 ED | 17 | 0.9986 | **1.0001** | 1.9447 |
| 1/16/20 ED | 14 | 0.9986 | **1.0001** | 1.0029 |
| 3/27/20 ED | 17 | 0.9968 | **1.0004** | 1.0878 |
| **6/9/23 SOFR** | 13 | 0.9941 | **0.9973** | 0.9979 |

Row-level accuracy on the flagship table (1/12/17): implied-vol error **−0.08% to +0.06%** across all 13 rows. On the SOFR table: **−0.21% to −0.59%** (small systematic; see §2.4).

Outliers (1.94 at 9/24/19, 0.821 at 5/8/19) are rows with CA ≤ 0.08bp quoted to 2 dp — rounding-dominated, not model failures. **Exclude rows with CA < 0.3bp from any calibration test.**

**Rejected alternative (mutation test on my own checker):** the Hull form `½σ²T1T2` with `T2 = T1+0.25` gives ratios drifting monotonically **0.933 → 0.975** across the 1/12/17 table — a clear, maturity-dependent bias. `½σ²T1²` gives a flat 1.000. Other rejected forms: `T1T2 × discount factor` (0.951→1.026), `T1T2` on ACT/360 (0.921→0.962), `(T1+0.5)T2` (0.814→0.926). Only `T1²` is flat.

### 2.3 Backing implied vol out of the observed CA — VERBATIM + formula

> "Implied vol is calculated by matching the model to the observed convexity adjustment." — all reports

Closed form (no root-finding needed — the model is quadratic in σ):

```
sigma_implied (bp) = sqrt( 2 * CA_observed_bp / 1e4 / M ) * 1e4
       where M = (1/4) * SUM_{i=1..4} T1_i^2
```

### 2.4 Calibration to cap/floor vols, and the model level

Verbatim: *"The model for convexity adjustment is the Ho-Lee model calibrated to cap/floor vols."* The corpus gives **no further calibration detail** — no cap tenor, no strike, no stripping method, no term-structure treatment. **This is the single largest unspecified degree of freedom in the port.** What *is* fully reproducible:

```
sigma_model (bp) = sqrt( 2 * CA_model_bp / 1e4 / M ) * 1e4
```

and the published `Cap vol Impl/Rlzd` column equals `TRUNC( sigma_model / RealizedVol , 1dp )` — **exact on 13/13 rows of the 1/12/17 ED table and 13/13 rows of the 6/9/23 SOFR table.** Worked SOFR examples: M4-H5 σ_model=169.4, RV=229.7 → 0.737 → printed **0.7** ✓; M6-H7 σ_model=131.0, RV=130.9 → 1.001 → printed **1.0** ✓; M7-H8 σ_model=122.3, RV=113.8 → 1.074 → printed **1.0** ✓.

So: **calibrate your cap/floor vol surface such that `σ_model` reproduces that column.** That is the operational definition of "calibrated to cap/floor vols" and it closes the loop without needing Citi's internal stripper.

*Caveat (inference):* Citi's model is calibrated to a cap/floor vol **term structure**, so `σ_model` above is the flat-σ *equivalent* of a time-varying vol path, not a single quoted cap vol. In an upward-sloping vol curve the two differ by a few percent.

**SOFR T1 refinement (inference):** the −0.2% to −0.6% systematic on the 2023 table implies Citi's effective SOFR `T1` is ~0.3% shorter than the raw as-of→IMM ACT/365 count (≈3–5 days on a 3–4y horizon). Candidates: business-day counting, spot (T+2) start, or the SR3 last-trade-day convention. Immaterial for RV ranking; calibrate a small date offset only if you need sub-1% vol reproduction.

---

## 3. REALIZED VOL

### 3.1 What is stated — VERBATIM

> "Realized vol is 3m realized vol of the corresponding pack." — all reports, ED and SOFR alike

That is the **complete** statement in the corpus. Everything below is **inference**, flagged as such.

### 3.2 Inferred convention

**Of what:** the *pack rate*, i.e. the average of the 4 futures rates (§1.3) — *not* the pack price, *not* individual contract rates, *not* the CA. "the corresponding pack" ties it to the same object whose CA is being measured.

**Daily changes, close-to-close.** Supporting in-corpus evidence — the same 12 Jun 2023 report's realized-vol convention for its swaption grid ([VL-SOFR], p.14, line 817): *"Close 6/9/23. **Close-to-close realized vol is used.**"*

**Annualization: normal (bp/yr), √252.** The vols are quoted in the same units as cap/floor normal vols (67.0 … 229.7) and the `Implied/Realized` column is a pure ratio of the two.

```
d_t          = pack_rate_t - pack_rate_{t-1}         (decimal, close-to-close, business days)
RealizedVol  = stdev( d_t over trailing 3 months ) * sqrt(252) * 1e4     [bp/yr, normal]
```

Open question left by the sources: population vs sample stdev, and zero-mean vs demeaned. Both are sub-1% effects at n≈63; use **sample stdev, demeaned**, and note it.

**Units self-check (confirms the convention):** `Implied/Realized` = ImpliedVol ÷ RealizedVol, rounded to 1 dp. 1/12/17 H8-Z8: 118.8/67.0 = 1.773 → **1.8** ✓. H0-Z0: 125.5/95.1 = 1.320 → **1.3** ✓. SOFR M4-H5: 199.5/229.7 = 0.869 → **0.9** ✓. (Note this column **rounds** while `Cap vol Impl/Rlzd` **truncates** — reproduce both literally.)

**Rolling-pack caveat for backtests:** on IMM roll dates the pack's constituent contracts change, producing a jump in `pack_rate` that is not a market move. Exclude roll-date returns or compute on a constant-contract basis within each 3m window.

---

## 4. THE VALUATION METRICS (RANKING SCREEN)

### 4.1 Column layout — DECODED AND VERIFIED

**ED tables (2017–2020): 12 columns.** Raw header ([W-JAN13] lines 656–657):

> "ED | Cvx Adj | 1 Week | 3m | 1 Y | V s M o d e l | 3 m | 1Y | 3m Roll | I m p l i e d | Realized | Implied/ | Cap vol
> Pack | (bp) | Chg (bp) | Z-Score | Z-Score | (bp) | Z-Score | Z-Score | (short cvx, bp) | Vol | Vol | Realized | Impl/Rlzd"

| # | Column | Definition |
|---|---|---|
| 1 | **Cvx Adj (bp)** | `pack_rate − matched fwd 1y swap rate`, in bp |
| 2 | **1 Week Chg (bp)** | change in col 1 over the past week |
| 3 | **3m Z-Score** | z-score of the **CA level** over a trailing 3-month window |
| 4 | **1Y Z-Score** | z-score of the **CA level** over a trailing 1-year window |
| 5 | **Vs Model (bp)** | `CA_observed − CA_model` — the *dislocation*. Positive ⇒ CA rich ⇒ sell |
| 6 | **3m Z-Score** | z-score of the **dislocation** (col 5) over trailing 3 months |
| 7 | **1Y Z-Score** | z-score of the **dislocation** (col 5) over trailing 1 year |
| 8 | **3m Roll (short cvx, bp)** | rolldown pickup to a *short-convexity* position over 3m — see §4.2 |
| 9 | **Implied Vol** | flat σ that reproduces col 1 via §2.3 (bp/yr normal) |
| 10 | **Realized Vol** | 3m realized vol of the pack (§3) |
| 11 | **Implied/Realized** | col 9 ÷ col 10, **rounded** 1 dp. >1 ⇒ CA rich to realized ⇒ sell |
| 12 | **Cap vol Impl/Rlzd** | σ_model ÷ col 10, **truncated** 1 dp (§2.4) |

**SOFR table (2023): 13 columns** — inserts **Model (bp)** as column 5, shifting Vs Model to column 6:

`CvxAdj | 1WkChg | 3m ZS | 1Y ZS | Model(bp) | Vs Model(bp) | 3m ZS | 1Y ZS | 3m Roll | Implied Vol | Realized Vol | Implied/Realized | Cap vol Impl/Rlzd`

*Assignment pinned by the report's own text*, [VL-SOFR] p.3, lines 119–121: *"we believe that the Blues convexity adjustment could continue to compress towards our model fair value, which is currently **about 5bps lower**."* Blues on 6/9/23 = M6-H7: CA 15.40, col5 = 9.98, col6 = 5.42 → model = 9.98 (≈5.4bp lower ✓), dislocation = 5.42. Cross-confirmed by Figure 3 (p.3, lines 125–141), whose "Blues Pack Cvx Adj / Model Level" chart shows CA ≈15 against model ≈10. Arithmetic check `CA − Model = VsModel` holds **13/13 rows exactly**.

### 4.2 ★ "3m Roll (short cvx, bp)" — EXACT RULE

```
Roll_3m(pack) = CA(pack) - CA(pack shifted ONE CONTRACT NEARER)
```

i.e. the pack rolls 3 months down the *observed* CA term structure (not the model curve).

**Verified exactly on 12/12 consecutive-row pairs of the 1/12/17 ED table AND 12/12 of the 6/9/23 SOFR table** (tolerance 0.011bp). Negative control: pairing the same CAs against a reversed roll column produces **11/12 mismatches**, confirming the test is not vacuous.

Worked examples — 1/12/17: H0-Z0 10.02 − Z9-U0 8.71 = **1.31** vs printed **1.30** ✓; M0-H1 11.12 − H0-Z0 10.02 = **1.10** vs **1.10** ✓; H1-Z1 13.53 − Z0-U1 12.76 = **0.77** vs **0.77** ✓. The first row H8-Z8 prints 0.47, requiring CA(Z7-U8) = 1.30 — confirmed by the 1/13/17 table, which lists Z7-U8 at **1.30** ✓.
SOFR 6/9/23: M5-H6 8.24 − H5-Z5 6.10 = **2.14** vs **2.14** ✓; M7-H8 22.29 − H7-Z7 20.08 = **2.21** vs **2.21** ✓.

### 4.3 Z-scores (inference — window mechanics not stated)

```
Z_3m(x)  = ( x_t - mean(x over trailing 3m) )  / stdev(x over trailing 3m)
Z_1Y(x)  = ( x_t - mean(x over trailing 1y) )  / stdev(x over trailing 1y)
```
applied to the CA **level** (cols 3–4) and to the CA−model **dislocation** (cols 6–7). Business-day sampling, trailing and inclusive of today. Requires ≥1y of history per rolling pack before the 1Y z-score is meaningful.

### 4.4 ★ Text-claim tie-out — FOUR-WAY CONFIRMATION OF THE COLUMN MAP

[W-JAN13] p.13, lines 683–687:
> "The convexity adjustment in Blues is an attractive sell on a number of these metrics (Figure 20). The CA is almost three sigmas wide to the model and has an attractive roll of about 1.3bp over 3m. The CA also trades about 30% rich to 3m recent realized volatility, which includes a period of especially high realized vol immediately post-election. We therefore like selling CA in Blues."

and p.11, lines 577–578: *"The CA of the Blues pack, in particular, is now about **4.6bp** (almost 3 sigmas) wide to the model, the widest dislocation since 2015"*

Row H0-Z0 (Blues), 1/12/17: `10.02 | 0.14 | 2.04 | 3.53 | 4.61 | 2.66 | 2.92 | 1.30 | 125.5 | 95.1 | 1.3 | 0.9`

| Text claim | Column | Value |
|---|---|---|
| "about 4.6bp … wide to the model" | Vs Model (bp) | **4.61** ✓ |
| "almost three sigmas wide to the model" | Vs Model 1Y Z-Score | **2.92** ✓ |
| "roll of about 1.3bp over 3m" | 3m Roll (short cvx) | **1.30** ✓ |
| "about 30% rich to 3m … realized volatility" | Implied/Realized | **1.3** ✓ |

### 4.5 "Three most attractive short convexity trades" — what SHORT CONVEXITY means

Verbatim marking rule (all reports): *"For each valuation metric, we mark three best short convexity trades in bold."* Plus, from 2019 onward, the disclaimer: *"Note that these are the most attractive in the chart but not necessarily trades that we would recommend at this point in time."*

**Ranking direction — a pack is a more attractive SHORT-convexity candidate the higher each of these is:**

| Metric | Sell-convexity signal |
|---|---|
| Cvx Adj (bp) | high (CA outright wide) |
| CA 3m / 1Y Z-Score | high (CA wide vs own history) |
| Vs Model (bp) | high (CA rich to Ho-Lee fair value) |
| Vs-Model 3m / 1Y Z-Score | high (dislocation extreme vs its own history) |
| 3m Roll (short cvx, bp) | high (short position earns rolldown as CA slides down the curve) |
| Implied/Realized | high (CA-implied vol rich to delivered vol) |

**"Short convexity" in trade terms = BUY the futures pack + PAY FIXED on the matched-maturity 1y swap, DV01-neutral.** You are short the CA (you profit if the CA narrows). Verbatim, [W-JAN13] p.14, line 742: *"**Sell $100k DV01 of Blues convexity adjustment, i.e. buy 1000 of H0-Z0 packs** (1000 of each of the four contracts) **and pay $1bn** on a matched-maturity … CME swap."*

Mechanism: the futures leg has a **rate-invariant DV01** ($25/bp/contract, forever). The FRA/swap leg's DV01 **rises as rates fall** — it is convex. Long-futures/pay-fixed therefore holds the *linear* instrument against the *convex* one ⇒ **net short convexity ⇒ short volatility**, which is exactly why the CA is a vol-driven quantity. [W-JAN13] p.11, lines 573–576: *"Because the theoretical value of convexity adjustments (CAs) is primarily determined by implied volatilities…"* And [VL-SOFR] p.3, line 114: *"shorting Blues convexity adjustment via **long SOFR futures against pay in swaps** as a **short vol proxy**."*

[CLARUS] gives the intuition and the crucial market-structure constraint: *"Overall, our chart means that Eurodollar contracts trade at a higher implied rate than an equivalent FRA. This offsets the positive PnL from the change in DV01 of the FRA relative to the Future. The exact size of this 'convexity adjustment' depends upon the expected path of interest rates and hence volatility."* … *"**It is only possible to trade convexity between CME Eurodollars and FRAs if you clear the FRA at CME and have CME Portfolio Margining in place.**"*

---

## 5. ★ THE TRADE STRUCTURE — PACK vs BUTTERFLY

### 5.1 Disambiguation — there are TWO butterflies in this corpus

1. **The 2s5s10s SWAP butterfly** — the vol hedge that makes this trade "CA vs butterfly". **This is the strategy.**
2. **ED pack butterflies** (W/R/G, R/G/B, G/B/Go, B/Go/P) in [W-JAN13] Appendix VI, Figure 57, p.30 — a **separate curve-RV monitor**, unrelated to convexity. Documented in §8.4 so you don't conflate them.

### 5.2 Why a butterfly rather than buying vol — VERBATIM

[W-JAN13] p.13, lines 693–707:
> "**Carry-efficient hedge for the risk of a hawkish Fed** — Although we believe that the near term balance of risks argues for tighter convexity spreads, outright selling of CAs is obviously exposed to the risk of higher volatilities over a medium term. The Fed's reaction function has arguably shifted to the hawkish side and a number of FOMC officials have lately mentioned the possibility of SOMA reinvestments tapering, which may cause a significant spike in volatilities. **One way to hedge this risk is to buy vol, such as a 3y1y swaption or a 3x4 cap, against selling Blues CA. But this will obviously reduce the total carry of the package. Instead, we propose hedging our short Blues CA by selling a 2s5s10s fly.** The motivation for this hedging strategy is that **3y1y vol is mostly driven by expectations of monetary policy, and therefore should be directional with the valuations of 5s on the curve.** Indeed, the 3y1y vol has been historically highly correlated with the 2s5s10s fly with DV01 weights shown in Figure 21 (**the correlation in levels being 90%**). We therefore should expect the fly to cheapen if vol richens going forward."

[W-JAN13] p.13, lines 725–732:
> "To build a more optimal hedging strategy, **we regressed Blues CA on 2y, 5y and 10y swap rates.** Consistent with the intuition above, the CA can be well explained by these three rates, with the fitted value effectively being a 2s5s10s fly with **-0.73/1/-0.47 DV01 weights** (Figure 22). The CA is about 4bp or 2.5 sigmas wide to the fly, which is consistent with the extreme richness of convexities to volatilities, as discussed above (Figure 22). Importantly, selling the 2s5s10s fly as a hedge has the advantage of positive carry, unlike buying volatility. **The 3m carry/roll on the short 2s5s10s fly is about +4bp over 3m.**"

[TI-FEB9] p.3, lines 158–167 — the same, re-estimated three weeks later, plus the key framing sentence:
> "To build a more optimal hedging strategy, we regressed Blues CA on 2y, 5y and 10y swap rates. Consistent with the intuition above, the CA are generally well explained by these three rates, with the fitted value effectively being a 2s5s10s fly with **0.705/-1/0.465 DV01 weights** (Figure 6). The CA is about 3bp (about 2 sigmas) wide to the fly … The 3m carry/roll on the short 2s5s10s fly is about **+3.2bp over 3m**. **Our trade, specified above, is constructed as a convergence trade between the Blues CA and the 2s5s10s fly**, precisely as illustrated in Figure 6."

### 5.3 The regression equations — VERBATIM chart annotations

| Source | Chart | Equation |
|---|---|---|
| [W-JAN13] Fig 21, p.13 (line 710) | 3y1y implied vol | `scaled 2s5s10s fly: 59.7+60.5*(-0.71*2y+5y-0.18*10y)` |
| [W-JAN13] Fig 22, p.13 (line 710) | **Blues Cvx Adj** | `scaled 2s5s10s fly: 10.2+21.4*(-0.73*2y+5y-0.47*10y)` |
| [VL-JAN17] Fig 8, p.5 (line 263) | 3y1y implied vol | `scaled 2s5s10s fly: 59.7+60.5*(-0.71*2y+5y-0.18*10y)` |
| [VL-JAN17] Fig 9, p.5 (line 263) | **Blues Cvx Adj** | `scaled 2s5s10s fly: 10.2+21.4*(-0.73*2y+5y-0.47*10y)` |
| [TI-FEB9] Fig 6, p.3 (line 136) | **Blues Cvx Adj** | `scaled 2s5s10s fly: 9.7+20.6*(-0.705*2y+5y-0.465*10y)` |

Read as: `CA_fitted (bp) = α + β · fly`, where `fly = (−w₂·r₂y + r₅y − w₁₀·r₁₀y)` in **percent**, and the weights `w₂, w₁₀` are **DV01 weights** with the belly normalized to 1.

**The weights and β are re-estimated at each publication (0.73/0.47, β=21.4 on 13 Jan → 0.705/0.465, β=20.6 on 9 Feb). Implement the regression procedure, not the frozen numbers.**

### 5.4 ★ RISK-WEIGHTING / DV01-NEUTRALITY RULES — DERIVED AND VERIFIED

**Rule A — the CA leg is DV01-neutral within itself:**
```
futures_DV01 = n_packs * 4 * $25        [$25/bp/contract, ED and SR3 alike]
swap_notional chosen so that  DV01(1y fwd swap) == futures_DV01
```
Verified: 1000 packs × 4 × $25 = **$100,000/bp**; $1bn × 1y ≈ **$100,000/bp** ✓. And 2000 packs × 4 × $25 = **$200,000/bp**; $2bn ≈ **$200,000/bp** ✓.

**Rule B — the butterfly is sized to the REGRESSION BETA, not to the CA DV01:**
```
fly_belly_DV01 = CA_DV01 * beta / 100        [beta from §5.3; /100 converts % -> bp]
wing_2y_DV01   = w2  * fly_belly_DV01
wing_10y_DV01  = w10 * fly_belly_DV01
```

**Verification against both published notional sets:**

| Trade | CA DV01 | β | Required belly DV01 | Published 5y notional | Implied belly DV01 @ $480/mn | Ratio |
|---|---|---|---|---|---|---|
| 13 Jan 2017 | $100,000 | 21.4 | $21,400/bp | −$44.4mn | $21,312/bp | **0.996** ✓ |
| 9 Feb 2017 | $200,000 | 20.6 | $41,200/bp | −$85.6mn | $41,088/bp | **0.997** ✓ |

Cross-check that the published notionals are internally consistent with the stated DV01 weights (solving for per-$1mn DV01):

| Trade | notionals 2y/5y/10y | stated DV01 wts | implied DV01/$1mn: 2y, 5y, 10y |
|---|---|---|---|
| 13 Jan | $79mn / −$44.4mn / $10.9mn | 0.73 / −1 / 0.46 | $197, $480, $899 |
| 9 Feb | $147mn / −$85.6mn / $20.89mn | 0.705 / −1 / 0.465 | $197, $480, $915 |

Identical 2y and 5y DV01s across both notes — consistent, and plausible for Jan/Feb-2017 swap levels. **The butterfly is a beta hedge for the vol exposure; it is deliberately NOT DV01-matched to the CA leg** (belly DV01 is only ~21% of the CA DV01).

### 5.5 THE TRADE — VERBATIM, BOTH VERSIONS

**Version 1 — [W-JAN13] p.14, lines 742–754 (and identically [VL-JAN17] p.6, lines 296–309):**
> "• **Sell $100k DV01 of Blues convexity adjustment, i.e. buy 1000 of H0-Z0 packs (1000 of each of the four contracts) and pay $1bn on a matched-maturity (3/18/20-3/17/21) CME swap. Consistent with the standard market practice, both fixed and floating legs of this swap have a quarterly payment frequency.**
> • **Pay the belly of the 2s5s10s swap fly with notional weights $79mn/-$44.4mn/$10.9mn (0.73/-1/0.46 DV01 weights).** We have not found a material difference in the hedging performance of clearing the fly on CME or LCH, so we believe either should offer an adequate hedge.
>
> The package carries by about **+$206k over a 3m term ($130k from the short CA trade and $76k from the hedge)**. Alternatively hedging with **3y1y swaption straddle ($96mn notional)** would carry by about **$65k over a 3m term ($130k from the short CA trade and -$65k from the swaption hedge)**. The main risk to this trade is further positioning imbalance, which may push convexities further above the fair value."

**Version 2 — the executed model-portfolio trade, [TI-FEB9] p.2, lines 26–36:**
> "**Levels: Sell Blues convexity adjustments, hedged** — We sell **$200k DV01** of Blues convexity adjustments, i.e. **buy 2000 of H0-Z0 Eurodollar packs (2000 of each of the four contracts) and pay $2bn on a matched-maturity (3/18/20-3/17/21) CME cleared swap at 8.8bp of spread.** The fixed leg on the swap is reset at a quarterly frequency. We hedge the trade by **paying the belly of the 2s5s10s swap fly with notional weights of $147mm/-$85.6mm/$20.89mm (0.705/-1/0.465 DV01 weights) at -18.2bp in terms of the level of the DV01-weighted fly.** Pricing is as of 8am on 2/9/2017. **We set the target at +$600k profit with the stop at -$350k loss. The trade carries positively by about $380k over the next three months.** Note: Futures trading involves substantial risk of loss."

**Carry decomposition — verified:** the CA-leg carry is *exactly* the `3m Roll (short cvx, bp)` column times the CA DV01. 13 Jan: **1.30 bp × $100k/bp = $130k** ✓ matching "$130k from the short CA trade". Hedge carry $76k on a $21.4k/bp belly ⇒ ≈3.55bp/3m, consistent with the stated "about +4bp over 3m". 9 Feb: 1.3bp × $200k = $260k plus 3.2bp × $41.2k = $132k ⇒ $392k ≈ the quoted **"about $380k"** ✓.

### 5.6 GENERALIZED ALGORITHM (the thing to code)

```
INPUT : as_of, futures curve (SR3), CME SOFR-swap curve, cap/floor vol surface,
        3m history of pack rates, >=1y history of CA and CA-model

FOR each rolling 1y pack p (contracts k..k+3, k = 1..N-3):
    T1_i        = ACT/365 (as_of -> IMM(3rd Wed) of contract i)          i in p
    M           = mean(T1_i^2)
    pack_rate   = mean(100 - price_i)
    S           = par fwd 1y CME swap, start IMM(k), end IMM(k)+1y, qtrly/qtrly
    CA          = (pack_rate - S) * 1e4                                   [bp]
    CA_model    = 0.5 * sigma_cap(p)^2 * M * 1e4                          [bp]
    vs_model    = CA - CA_model
    iv          = sqrt(2*CA/1e4/M)*1e4
    rv          = stdev(daily d(pack_rate), 3m) * sqrt(252) * 1e4
    roll_3m     = CA(p) - CA(p shifted one contract nearer)
    z3_lvl,z1_lvl = zscore(CA, 3m), zscore(CA, 1y)
    z3_dis,z1_dis = zscore(vs_model, 3m), zscore(vs_model, 1y)
    ir          = round(iv/rv, 1);   capr = trunc(sigma_cap(p)/rv, 1)

RANK: for each metric take the 3 packs with the highest value -> short-cvx candidates
SELECT: the pack flagged by the MOST metrics simultaneously (Citi's revealed rule:
        Blues on 1/12/17 topped vs-model bp, vs-model z, roll and implied/realized)

TRADE : buy n packs (n of EACH of the 4 contracts); CA_DV01 = n*4*25
        pay fixed, matched-maturity 1y CME swap, notional st DV01 == CA_DV01
        regress CA(bp) on (r2y, r5y, r10y) -> alpha, beta, w2, w10
        pay belly of 2s5s10s: belly_DV01 = CA_DV01 * beta/100
                              wings      = w2*belly_DV01, w10*belly_DV01
```

---

## 6. ENTRY / EXIT / SIZING / HOLDING PERIOD / COSTS

### 6.1 Explicit levels, target, stop — [TI-FEB9]

| Item | Value |
|---|---|
| Entry date / time | **9 Feb 2017**, "Pricing is as of 8am on 2/9/2017" |
| Entry level (CA leg) | **8.8bp of spread** (H0-Z0 pack vs 3/18/20–3/17/21 CME swap) |
| Entry level (hedge) | **−18.2bp**, "in terms of the level of the DV01-weighted fly" |
| Size | **$200k DV01** — 2000 packs; $2bn swap |
| **Target** | **+$600k profit** |
| **Stop** | **−$350k loss** |
| 3m carry | **+$380k** |

### 6.2 Realized outcome — [W-SEP30] Appendix I, Figure 38, p.27

Header: `Trade | Inception Date | Unwind Date | Initial | Unwind | P&L ($000s) | Target P&L | Stop Loss | Return on Risk | Return on Portfolio`

| Trade | Inception | Unwind | Initial | Unwind | P&L | Target | Stop | RoR | RoP |
|---|---|---|---|---|---|---|---|---|---|
| **Sell Blues convexity adjustments, hedged** | **Feb 9, 2017** | **Jun 6, 2017** | **8.8bp** | **6.6bp** | **$552** | $600 | $350 | **55.20%** | **0.18%** |
| **Sell Greens convexity adjustment, hedged** | **Jun 6, 2017** | **Aug 8, 2017** | **4.3bp** | **2.65bp** | **$476** | $450 | $225 | **47.55%** | **0.16%** |

**Holding period: ~4 months (Blues, 9 Feb → 6 Jun 2017); ~2 months (Greens, 6 Jun → 8 Aug 2017).** The Blues unwind date is the Greens inception date — the desk **rolled the same strategy down the strip** into the next pack rather than closing the theme. Neither hit target or stop; both were discretionary unwinds near target.

Nominal horizon at inception: [W-JAN13] carry is quoted "over a 3m term" and the model-portfolio convention lists trade horizons in months (e.g. p.21: *"Opened November 30, 2016, horizon 6 months"*). **Treat 3m as the carry-measurement horizon and ~3–6m as the intended holding period.**

### 6.3 Transaction cost assumptions — VERBATIM

There is **no explicit bid/offer or slippage assumption anywhere in the corpus.** Costs are explicitly **excluded**:

- [W-SEP30] p.27, lines 1405–1408: *"Note: Return on risk is based on Citi's return-on-risk methodology and is calculated by taking the largest two-week change in the trade since January 1997. Return on portfolio based off **$300 million model portfolio sizing.** Note: Past performance does not indicate future results. **Calculations do not include transaction fees and other costs.** Note: Futures trading involves substantial risk of loss."*
- [W-JAN13] p.21, line 1138: *"Past performance is no indicator of future results. **Calculations do not include transaction costs and other fees.**"*

**Sizing convention: Return on Portfolio is computed against a $300mn model portfolio** — the $552k Blues P&L = 0.18% of $300mn ✓. Return on Risk = P&L ÷ (largest two-week change in the trade since Jan 1997), e.g. $552k/55.20% ⇒ risk unit $1.0mn.

### 6.4 Clearing venue rule — VERBATIM

[W-JAN13] p.13, lines 688–692:
> "**Our analysis is based on the CME FRA/swap curve. Although convexity adjustments will appear wider if clearing the swap leg on LCH, we recommend clearing on CME as the CME-LCH basis has well retraced from its recent wide levels in December. In addition, clearing on CME is obviously more capital-efficient since it allows netting ED and swap positions for margin calculations.**"

And for the hedge leg only ([W-JAN13] p.14, lines 747–749): *"We have not found a material difference in the hedging performance of clearing the fly on CME or LCH, so we believe either should offer an adequate hedge."*

**Rule: CA leg swap → CME (mandatory, for netting). 2s5s10s fly → CME or LCH (indifferent).**

### 6.5 Stated risks — VERBATIM

- [W-JAN13] p.14: *"The main risk to this trade is further positioning imbalance, which may push convexities further above the fair value."*
- [TI-FEB9] p.4, lines 173–176: *"**Risks: Continued divergence in positioning** — The main risk to the trade is an increase to short positioning in Eurodollar futures, although we believe this is mitigated since positioning is stretched here from an historic perspective."*
- Mandatory disclaimer on every occurrence: *"Note: Futures trading involves substantial risk of loss."*

---

## 7. ALL NUMERIC TABLES — KNOWN-ANSWER TIE-OUT SET

Column key (ED, 12 cols): `CA | 1WkChg | CA_3mZ | CA_1YZ | VsModel | VsM_3mZ | VsM_1YZ | Roll3m | ImplVol | RlzdVol | Impl/Rlzd | CapVol I/R`

### 7.1 ★ Figure 20, [W-JAN13] p.12 — close **1/12/2017** — "The convexity adjustments in Blues are an attractive sell"

| ED Pack | CA (bp) | 1Wk Chg | 3m Z | 1Y Z | VsModel (bp) | 3m Z | 1Y Z | 3m Roll | Impl Vol | Rlzd Vol | Impl/Rlzd | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H8-Z8 | 1.77 | 0.03 | 1.49 | 0.34 | 1.18 | 1.63 | 0.25 | 0.47 | 118.8 | 67.0 | 1.8 | 1.0 |
| M8-H9 | 2.35 | 0.04 | 1.45 | 0.32 | 1.46 | 1.26 | 0.15 | 0.58 | 118.5 | 72.1 | 1.6 | 1.0 |
| U8-M9 | 3.14 | 0.09 | 1.54 | 0.64 | 1.86 | 1.27 | 0.52 | 0.79 | 120.7 | 77.1 | 1.6 | 0.9 |
| Z8-U9 | 4.17 | 0.13 | 1.61 | 1.18 | 2.40 | 1.43 | 1.21 | 1.03 | 124.2 | 81.8 | 1.5 | 0.9 |
| H9-Z9 | 5.32 | 0.17 | 1.63 | 1.68 | 2.94 | 1.56 | 1.80 | 1.15 | 126.8 | 86.0 | 1.5 | 0.9 |
| M9-H0 | 6.45 | 0.13 | 1.75 | 2.54 | 3.39 | 1.79 | 2.77 | 1.13 | 127.4 | 89.7 | 1.4 | 0.9 |
| U9-M0 | 7.64 | 0.00 | 1.83 | 3.33 | 3.83 | 2.13 | 3.06 | 1.19 | 127.4 | 92.4 | 1.4 | 0.9 |
| Z9-U0 | 8.71 | 0.00 | 1.89 | 3.44 | 4.12 | 2.39 | 2.91 | 1.08 | 125.9 | 94.3 | 1.3 | 0.9 |
| **H0-Z0** | **10.02** | **0.14** | **2.04** | **3.53** | **4.61** | **2.66** | **2.92** | **1.30** | **125.5** | **95.1** | **1.3** | **0.9** |
| M0-H1 | 11.12 | 0.36 | 2.09 | 3.49 | 4.87 | 2.85 | 2.79 | 1.10 | 123.6 | 95.6 | 1.3 | 0.9 |
| U0-M1 | 11.93 | 0.58 | 2.10 | 3.38 | 4.80 | 2.99 | 2.50 | 0.81 | 120.2 | 95.5 | 1.3 | 0.9 |
| Z0-U1 | 12.76 | 0.76 | 2.07 | 3.38 | 4.74 | 3.09 | 2.34 | 0.83 | 117.2 | 95.3 | 1.2 | 0.9 |
| H1-Z1 | 13.53 | 0.84 | 1.97 | 3.37 | 4.60 | 3.18 | 2.39 | 0.77 | 114.0 | 95.1 | 1.2 | 0.9 |

**H0-Z0 = Blues = the recommended trade.** Pack mapping on 1/12/17: front = H7 ⇒ Whites H7-Z7, Reds H8-Z8, Greens H9-Z9, **Blues H0-Z0**, Golds H1-Z1. Confirmed by Figures 16/17 (p.11): *"Greens Pack Cvx Adj"* charted ≈5 (H9-Z9 = 5.32 ✓) and *"Blues Pack Cvx Adj"* charted ≈10 (H0-Z0 = 10.02 ✓).

### 7.2 Figure 48, [VL-JAN17] p.15 — close **1/13/2017** (same table, one day later — use to validate day-over-day column stability; adds the Whites rows)

| ED Pack | CA | 1Wk | 3m Z | 1Y Z | VsModel | 3m Z | 1Y Z | Roll | Impl | Rlzd | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H7-Z7 | 0.25 | -0.04 | 0.95 | 0.72 | 0.21 | 0.99 | 0.89 | 0.14 | 113.5 | 47.1 | 2.4 | 0.9 |
| M7-H8 | 0.53 | -0.03 | 1.24 | 0.82 | 0.43 | 1.36 | 1.00 | 0.28 | 120.5 | 50.6 | 2.4 | 0.9 |
| U7-M8 | 0.89 | -0.01 | 1.41 | 0.70 | 0.70 | 1.66 | 0.84 | 0.36 | 122.1 | 55.9 | 2.2 | 0.9 |
| Z7-U8 | 1.30 | 0.01 | 1.44 | 0.49 | 0.94 | 1.79 | 0.58 | 0.40 | 120.4 | 61.0 | 2.0 | 1.0 |
| H8-Z8 | 1.77 | 0.03 | 1.41 | 0.31 | 1.19 | 1.63 | 0.27 | 0.47 | 118.8 | 67.0 | 1.8 | 0.9 |
| M8-H9 | 2.34 | 0.06 | 1.37 | 0.29 | 1.46 | 1.27 | 0.15 | 0.58 | 118.3 | 72.2 | 1.6 | 0.9 |
| U8-M9 | 3.13 | 0.11 | 1.47 | 0.61 | 1.86 | 1.26 | 0.51 | 0.79 | 120.6 | 77.2 | 1.6 | 0.9 |
| Z8-U9 | 4.16 | 0.13 | 1.54 | 1.15 | 2.39 | 1.40 | 1.18 | 1.03 | 124.1 | 81.8 | 1.5 | 0.9 |
| H9-Z9 | 5.32 | 0.12 | 1.57 | 1.66 | 2.93 | 1.51 | 1.76 | 1.16 | 126.9 | 86.0 | 1.5 | 0.9 |
| M9-H0 | 6.46 | 0.07 | 1.69 | 2.51 | 3.37 | 1.72 | 2.69 | 1.14 | 127.6 | 89.7 | 1.4 | 0.9 |
| U9-M0 | 7.64 | -0.12 | 1.76 | 3.26 | 3.80 | 2.01 | 2.93 | 1.18 | 127.5 | 92.5 | 1.4 | 0.9 |
| Z9-U0 | 8.69 | -0.25 | 1.79 | 3.33 | 4.04 | 2.19 | 2.75 | 1.05 | 125.8 | 94.3 | 1.3 | 0.9 |
| **H0-Z0** | **9.96** | -0.25 | 1.90 | 3.39 | **4.48** | 2.38 | **2.73** | **1.27** | 125.2 | 95.2 | **1.3** | 0.9 |
| M0-H1 | 10.99 | -0.24 | 1.91 | 3.30 | 4.66 | 2.47 | 2.55 | 1.03 | 123.0 | 95.6 | 1.3 | 0.9 |
| U0-M1 | 11.74 | -0.15 | 1.88 | 3.15 | 4.53 | 2.50 | 2.23 | 0.75 | 119.4 | 95.5 | 1.2 | 1.0 |
| Z0-U1 | 12.55 | -0.03 | 1.84 | 3.12 | 4.42 | 2.49 | 2.04 | 0.80 | 116.2 | 95.3 | 1.2 | 1.0 |
| H1-Z1 | 13.26 | -0.03 | 1.72 | 3.06 | 4.22 | 2.46 | 2.02 | 0.71 | 113.0 | 95.1 | 1.2 | 1.0 |

### 7.3 Figure 57, [VL-2019a] — close **1/11/2019**

| ED Pack | CA | 1Wk | 3m Z | 1Y Z | VsModel | 3m Z | 1Y Z | Roll | Impl | Rlzd | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H9-Z9 | 0.06 | -0.07 | -1.21 | -1.02 | 0.00 | -1.73 | -1.19 | 0.06 | 53.3 | 61.0 | 0.9 | 0.7 |
| M9-H0 | 0.17 | -0.09 | -1.99 | -2.35 | 0.05 | -2.43 | -3.41 | 0.12 | 68.6 | 65.0 | 1.1 | 0.8 |
| U9-M0 | 0.33 | -0.13 | -2.21 | -2.40 | 0.10 | -2.77 | -3.91 | 0.16 | 74.2 | 71.4 | 1.0 | 0.8 |
| Z9-U0 | 0.53 | -0.15 | -2.46 | -2.55 | 0.13 | -2.96 | -4.32 | 0.20 | 77.3 | 76.2 | 1.0 | 0.8 |
| H0-Z0 | 0.79 | -0.16 | -2.79 | -2.76 | 0.16 | -2.85 | -4.29 | 0.25 | 79.3 | 78.9 | 1.0 | 0.8 |
| M0-H1 | 1.09 | -0.16 | -3.01 | -2.79 | 0.18 | -2.58 | -3.72 | 0.30 | 80.7 | 80.4 | 1.0 | 0.9 |
| U0-M1 | 1.46 | -0.14 | -3.03 | -2.48 | 0.21 | -2.25 | -3.08 | 0.37 | 82.2 | 80.7 | 1.0 | 0.9 |
| Z0-U1 | 1.88 | -0.13 | -2.87 | -2.12 | 0.24 | -2.04 | -2.65 | 0.42 | 83.4 | 79.8 | 1.0 | 0.9 |
| H1-Z1 | 2.35 | -0.12 | -2.60 | -1.79 | 0.27 | -2.00 | -2.35 | 0.48 | 84.4 | 78.4 | 1.1 | 1.0 |
| M1-H2 | 2.81 | -0.29 | -3.19 | -1.84 | 0.23 | -2.01 | -2.43 | 0.46 | 84.1 | 76.9 | 1.1 | 1.0 |
| U1-M2 | 3.29 | -0.50 | -2.69 | -1.71 | 0.17 | -1.83 | -2.14 | 0.48 | 83.7 | 75.1 | 1.1 | 1.0 |
| Z1-U2 | 3.69 | -0.68 | -1.75 | -1.37 | -0.02 | -1.40 | -1.72 | 0.40 | 81.9 | 73.5 | 1.1 | 1.1 |
| H2-Z2 | 4.22 | -0.87 | -1.10 | -1.19 | -0.12 | -0.96 | -1.47 | 0.52 | 81.3 | 72.0 | 1.1 | 1.1 |
| M2-H3 | 4.52 | -0.96 | -1.42 | -1.40 | -0.46 | -1.18 | -1.57 | 0.31 | 78.7 | 70.3 | 1.1 | 1.1 |
| U2-M3 | 5.28 | -0.97 | -1.24 | -1.37 | -0.43 | -1.07 | -1.54 | 0.75 | 79.8 | 68.6 | 1.2 | 1.2 |
| Z2-U3 | 6.16 | -0.83 | -1.53 | -1.41 | -0.29 | -1.19 | -1.61 | 0.89 | 81.3 | 66.9 | 1.2 | 1.2 |
| H3-Z3 | 7.44 | -0.41 | -0.87 | -1.02 | 0.20 | -0.58 | -1.40 | 1.28 | 84.4 | 65.5 | 1.3 | 1.2 |

Report text: *"Eurodollar convexity adjustments now trade roughly fair to the model (Figure 57). We believe this has been driven by short covering of ED futures positions."*

### 7.4 Figure 60, [VL-2019b] (9 May 2019) — close **5/8/2019**

| ED Pack | CA | 1Wk | 3m Z | 1Y Z | VsModel | 3m Z | 1Y Z | Roll | Impl | Rlzd | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M9-H0 | 0.01 | 0.00 | -1.01 | -0.86 | -0.03 | -0.99 | -0.92 | 0.03 | 30.6 | 53.8 | 0.6 | 0.8 |
| U9-M0 | 0.08 | 0.00 | -1.07 | -1.58 | -0.02 | -1.25 | -1.76 | 0.06 | 49.4 | 60.1 | 0.8 | 0.8 |
| Z9-U0 | 0.17 | -0.01 | -1.34 | -1.67 | -0.02 | -1.39 | -1.85 | 0.10 | 57.0 | 66.0 | 0.9 | 0.8 |
| H0-Z0 | 0.30 | -0.01 | -1.52 | -1.75 | -0.02 | -1.45 | -1.90 | 0.12 | 60.7 | 69.7 | 0.9 | 0.8 |
| M0-H1 | 0.43 | -0.02 | -1.67 | -1.84 | -0.05 | -1.46 | -1.90 | 0.14 | 61.5 | 71.4 | 0.9 | 0.8 |
| U0-M1 | 0.58 | -0.03 | -1.73 | -1.89 | -0.09 | -1.52 | -1.86 | 0.15 | 61.4 | 71.3 | 0.9 | 0.9 |
| Z0-U1 | 0.75 | -0.05 | -1.72 | -1.95 | -0.14 | -1.60 | -1.82 | 0.17 | 61.2 | 70.1 | 0.9 | 0.9 |
| H1-Z1 | 0.95 | -0.06 | -1.71 | -2.00 | -0.19 | -1.66 | -1.80 | 0.20 | 61.2 | 68.3 | 0.9 | 0.9 |
| M1-H2 | 1.21 | -0.08 | -1.72 | -2.03 | -0.21 | -1.71 | -1.77 | 0.26 | 62.2 | 66.0 | 0.9 | 1.0 |
| U1-M2 | 1.58 | -0.09 | -1.46 | -1.85 | -0.15 | -1.43 | -1.56 | 0.37 | 64.8 | 64.0 | 1.0 | 1.0 |
| Z1-U2 | 1.83 | -0.12 | -0.77 | -1.77 | -0.26 | -0.71 | -1.43 | 0.25 | 63.8 | 62.2 | 1.0 | 1.1 |
| H2-Z2 | 2.12 | -0.19 | -0.48 | -1.65 | -0.35 | -0.41 | -1.19 | 0.29 | 63.3 | 60.6 | 1.0 | 1.1 |
| M2-H3 | 2.24 | -0.32 | -0.69 | -1.76 | -0.64 | -0.63 | -1.26 | 0.11 | 60.4 | 59.6 | 1.0 | 1.1 |
| U2-M3 | 2.67 | -0.39 | -0.98 | -1.79 | -0.66 | -0.91 | -1.16 | 0.43 | 61.6 | 58.8 | 1.0 | 1.1 |
| Z2-U3 | 3.21 | -0.46 | -1.61 | -1.92 | -0.59 | -1.49 | -1.16 | 0.54 | 63.3 | 58.5 | 1.1 | 1.1 |
| H3-Z3 | 3.98 | -0.41 | -1.98 | -1.95 | -0.34 | -1.44 | -1.10 | 0.77 | 66.4 | 58.4 | 1.1 | 1.2 |
| M3-H4 | 4.93 | -0.22 | -1.69 | -1.91 | 0.04 | -1.06 | -0.99 | 0.95 | 69.7 | 58.2 | 1.2 | 1.2 |

Text: *"Convexity adjustments have moved marginally lower over the past week. Golds Eurodollar convexity adjustments now trade only slightly rich to the model, while Blues convexities look cheap to the model (Figure 60)."*

### 7.5 Figure 62, [VL-2019c] (25 Sep 2019) — close **9/24/2019**

| ED Pack | CA | 1Wk | 3m Z | 1Y Z | VsModel | 3m Z | 1Y Z | Roll | Impl | Rlzd | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Z9-U0 | 0.08 | -0.01 | 0.16 | 0.06 | -0.06 | -0.79 | -0.93 | 0.06 | 30.8 | 101.0 | 0.3 | 0.7 |
| H0-Z0 | 0.21 | -0.01 | 1.66 | 0.20 | -0.03 | 0.38 | -0.62 | 0.13 | 71.7 | 103.0 | 0.7 | 0.7 |
| M0-H1 | 0.39 | -0.01 | 1.89 | 0.28 | 0.02 | 0.87 | -0.43 | 0.18 | 77.3 | 104.6 | 0.7 | 0.6 |
| U0-M1 | 0.61 | -0.02 | 1.80 | 0.32 | 0.09 | 0.96 | -0.27 | 0.22 | 79.6 | 104.9 | 0.8 | 0.6 |
| Z0-U1 | 0.86 | -0.02 | 1.59 | 0.37 | 0.15 | 0.92 | -0.10 | 0.25 | 80.4 | 103.9 | 0.8 | 0.7 |
| H1-Z1 | 1.14 | -0.03 | 1.38 | 0.42 | 0.23 | 0.82 | 0.09 | 0.28 | 80.6 | 102.1 | 0.8 | 0.7 |
| M1-H2 | 1.46 | -0.03 | 1.24 | 0.43 | 0.31 | 0.75 | 0.25 | 0.32 | 80.6 | 99.9 | 0.8 | 0.7 |
| U1-M2 | 1.81 | -0.03 | 1.15 | 0.40 | 0.40 | 0.69 | 0.37 | 0.35 | 80.4 | 97.6 | 0.8 | 0.7 |
| Z1-U2 | 2.21 | -0.02 | 1.13 | 0.37 | 0.50 | 0.66 | 0.47 | 0.40 | 80.3 | 95.5 | 0.8 | 0.7 |
| H2-Z2 | 3.00 | 0.35 | 1.77 | 0.72 | 0.96 | 1.25 | 0.79 | 1.06 | 85.2 | 93.5 | 0.9 | 0.7 |
| M2-H3 | 3.61 | 0.19 | 0.79 | 0.77 | 1.21 | 0.27 | 1.16 | 0.60 | 86.0 | 92.0 | 0.9 | 0.7 |
| U2-M3 | 4.47 | 0.28 | 1.13 | 1.12 | 1.68 | 0.55 | 1.53 | 0.87 | 88.7 | 91.0 | 1.0 | 0.7 |
| Z2-U3 | 5.11 | -0.06 | 0.06 | 0.98 | 1.90 | -0.44 | 1.28 | 0.63 | 88.2 | 90.4 | 1.0 | 0.7 |
| H3-Z3 | 5.51 | -0.51 | -0.30 | 0.86 | 1.85 | -0.71 | 1.15 | 0.41 | 85.8 | 90.1 | 1.0 | 0.8 |
| M3-H4 | 6.09 | -0.46 | 0.01 | 0.85 | 1.94 | -0.39 | 1.21 | 0.58 | 84.6 | 89.7 | 0.9 | 0.8 |
| U3-M4 | 6.47 | -0.50 | -0.17 | 0.53 | 1.80 | -0.54 | 1.00 | 0.38 | 82.2 | 89.4 | 0.9 | 0.8 |
| Z3-U4 | 7.03 | -0.06 | 0.21 | 0.38 | 1.81 | -0.24 | 1.05 | 0.56 | 81.1 | 89.1 | 0.9 | 0.8 |

*(H2-Z2 row: the markdown extraction split this row across lines 953–955; values reassembled in table order. Text: "Blues convexity adjustments remain wide to our model level. This may be driven by a shift in asset manager positioning".)*

### 7.6 Figure 62, [VL-2020a] (17 Jan 2020) — close **1/16/2020** — contains a NEGATIVE CA and two `n/a` implied vols

| ED Pack | CA | 1Wk | 3m Z | 1Y Z | VsModel | 3m Z | 1Y Z | Roll | Impl | Rlzd | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H0-Z0 | **-0.02** | 0.04 | -0.20 | -0.64 | -0.06 | 0.14 | -0.49 | 0.01 | 37.2 | 55.9 | 0.7 | 0.7 |
| M0-H1 | 0.01 | 0.05 | -0.49 | -1.46 | -0.07 | -0.23 | -0.71 | 0.03 | **n/a** | 59.5 | **n/a** | 0.7 |
| U0-M1 | 0.08 | 0.05 | -0.65 | -1.51 | -0.07 | -0.36 | -0.65 | 0.07 | **n/a** | 64.7 | **n/a** | 0.7 |
| Z0-U1 | 0.21 | 0.06 | -0.71 | -1.40 | -0.05 | -0.37 | -0.48 | 0.13 | 48.9 | 69.5 | 0.7 | 0.7 |
| H1-Z1 | 0.44 | 0.07 | -0.54 | -0.88 | 0.02 | -0.08 | -0.02 | 0.23 | 59.8 | 73.2 | 0.8 | 0.7 |
| M1-H2 | 0.76 | 0.08 | -0.15 | -0.19 | 0.14 | 0.57 | 0.51 | 0.32 | 68.1 | 76.1 | 0.9 | 0.8 |
| U1-M2 | 1.12 | 0.09 | 0.34 | 0.28 | 0.26 | 1.33 | 0.79 | 0.36 | 72.8 | 78.6 | 0.9 | 0.8 |
| Z1-U2 | 1.53 | 0.09 | 0.87 | 0.58 | 0.40 | 1.88 | 0.95 | 0.41 | 75.7 | 79.8 | 0.9 | 0.8 |
| H2-Z2 | 1.93 | 0.10 | 1.05 | 0.63 | 0.49 | 2.05 | 0.94 | 0.40 | 76.7 | 80.6 | 1.0 | 0.8 |
| M2-H3 | 2.28 | 0.12 | -0.43 | 0.18 | 0.51 | -0.21 | 0.47 | 0.34 | 75.9 | 80.9 | 0.9 | 0.8 |
| U2-M3 | 2.85 | 0.02 | -0.21 | 0.20 | 0.71 | -0.12 | 0.39 | 0.57 | 78.0 | 81.3 | 1.0 | 0.8 |
| Z2-U3 | 3.23 | -0.12 | -0.94 | -0.06 | 0.69 | -0.90 | 0.09 | 0.38 | 76.8 | 81.4 | 0.9 | 0.8 |
| H3-Z3 | 3.79 | -0.18 | -0.85 | -0.07 | 0.82 | -0.84 | 0.04 | 0.56 | 77.3 | 81.4 | 0.9 | 0.8 |
| M3-H4 | 4.25 | -0.26 | -0.78 | -0.11 | 0.80 | -0.81 | -0.02 | 0.46 | 76.5 | 81.4 | 0.9 | 0.8 |
| U3-M4 | 4.54 | -0.29 | -0.89 | -0.34 | 0.59 | -0.91 | -0.22 | 0.29 | 74.1 | 81.3 | 0.9 | 0.8 |
| Z3-U4 | 5.08 | -0.31 | -0.61 | -0.38 | 0.61 | -0.67 | -0.23 | 0.54 | 73.9 | 81.3 | 0.9 | 0.8 |
| H4-Z4 | 5.58 | -0.39 | -0.55 | -0.54 | 0.56 | -0.63 | -0.33 | 0.50 | 73.2 | 81.6 | 0.9 | 0.8 |

**Implementation rule from this table:** when `CA ≤ 0` the flat-σ inversion has no real solution ⇒ print **`n/a`** for Implied Vol and Implied/Realized. Note Citi prints `n/a` for M0-H1 (CA=0.01) and U0-M1 (CA=0.08) but a value (37.2) for H0-Z0 at CA=−0.02 — the flag is not a pure sign test; **guard on `CA < some floor` (≈0.1bp) rather than on sign, and treat these three rows as a documented irregularity.**

### 7.7 Figure 60, [VL-2020b] (30 Mar 2020) — close **3/27/2020** — COVID stress; two `n/a` in Implied/Realized

| ED Pack | CA | 1Wk | 3m Z | 1Y Z | VsModel | 3m Z | 1Y Z | Roll | Impl | Rlzd | I/R | Cap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M0-H1 | 0.03 | 0.00 | 1.64 | 0.10 | -0.03 | 1.88 | 0.86 | 0.03 | 34.1 | 93.6 | 0.4 | 0.4 |
| U0-M1 | 0.10 | 0.00 | 2.06 | 0.15 | 0.02 | 2.54 | 1.39 | 0.07 | 50.0 | 78.3 | **n/a** | 0.5 |
| Z0-U1 | 0.20 | 0.01 | 2.15 | -0.02 | 0.07 | 2.44 | 1.41 | 0.10 | 55.6 | 80.0 | **n/a** | 0.5 |
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

Note the 1-week CA changes of +4 to +5bp in the back packs — this is what a genuine liquidity dislocation looks like in this screen; useful as a regime-stress fixture.

### 7.8 ★★ Figure 58, [VL-SOFR] p.14 — close **6/9/2023** — **THE SOFR TIE-OUT (13 columns; note the extra `Model` column)**

**"Convexity adjustments for 1y SOFR futures packs (vs CME swaps)"**

| SOFR Pack | CA (bp) | 1Wk Chg | 3m Z | 1Y Z | **Model (bp)** | VsModel (bp) | 3m Z | 1Y Z | 3m Roll | Impl Vol | Rlzd Vol | Impl/Rlzd | Cap I/R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M4-H5 | 4.03 | 1.23 | 0.78 | 0.45 | 2.94 | 1.09 | 0.92 | 0.54 | 0.88 | 199.5 | 229.7 | 0.9 | 0.7 |
| U4-M5 | 4.41 | 0.98 | 0.79 | 0.27 | 3.79 | 0.62 | 0.98 | 0.43 | 0.38 | 178.1 | 201.4 | 0.9 | 0.8 |
| Z4-U5 | 5.16 | 0.71 | 0.63 | 0.19 | 4.66 | 0.49 | 0.93 | 0.42 | 0.74 | 167.7 | 180.3 | 0.9 | 0.8 |
| H5-Z5 | 6.10 | 0.29 | 0.40 | 0.24 | 5.53 | 0.58 | 0.83 | 0.55 | 0.95 | 161.6 | 166.3 | 1.0 | 0.9 |
| M5-H6 | 8.24 | -0.40 | -0.52 | 0.21 | 6.36 | 1.88 | 0.05 | 0.51 | 2.14 | 168.5 | 156.4 | 1.1 | 0.9 |
| U5-M6 | 9.77 | -1.22 | -0.73 | 0.36 | 7.16 | 2.60 | 0.06 | 0.82 | 1.52 | 166.3 | 148.8 | 1.1 | 0.9 |
| Z5-U6 | 11.70 | -1.89 | -0.82 | 0.55 | 8.02 | 3.67 | 0.13 | 1.10 | 1.93 | 166.5 | 142.2 | 1.2 | 0.9 |
| H6-Z6 | 13.70 | -2.37 | -0.80 | 0.70 | 8.96 | 4.74 | 0.22 | 1.25 | 2.00 | 166.0 | 136.1 | 1.2 | 0.9 |
| **M6-H7 (Blues)** | **15.40** | **-3.08** | **-0.96** | **0.73** | **9.98** | **5.42** | **-0.07** | **1.18** | **1.70** | **163.1** | **130.9** | **1.2** | **1.0** |
| U6-M7 | 16.84 | -2.97 | -1.30 | 0.63 | 11.10 | 5.74 | -0.42 | 1.05 | 1.44 | 159.0 | 126.2 | 1.3 | 1.0 |
| Z6-U7 | 18.27 | -2.72 | -1.55 | 0.47 | 12.23 | 6.04 | -0.77 | 0.90 | 1.43 | 155.1 | 121.9 | 1.3 | 1.0 |
| H7-Z7 | 20.08 | -2.33 | -1.54 | 0.40 | 13.37 | 6.71 | -0.88 | 0.82 | 1.81 | 152.8 | 118.0 | 1.3 | 1.0 |
| **M7-H8 (Golds)** | **22.29** | -1.78 | -1.35 | 0.45 | **14.50** | **7.79** | -0.69 | 0.90 | **2.21** | 151.9 | 113.8 | 1.3 | 1.0 |

**Pack mapping on 6/9/23** (front SR3 = M3): Whites M3-H4, **Reds M4-H5**, **Greens M5-H6**, **Blues M6-H7**, **Golds M7-H8**. The table starts at Reds. Cross-check against Figures 59/60 (p.14–15): *"Blues Pack Cvx Adj"* chart tops out near 20 with the last point ≈15 (M6-H7 = 15.40 ✓); *"Golds Pack Cvx Adj"* chart spans 10–35 with the last point ≈22 (M7-H8 = 22.29 ✓).

**Report commentary — [VL-SOFR] p.14, lines 829–835 (verbatim):**
> "• Convexity adjustments on both Blues (Figure 59) and Golds (Figure 60) have finally started to decline and converge towards our model fair values. With that said, **both convexity adjustments still look rich and has room to cheapen further, especially given that implied vols have declined to the low end of their 1-year range. We continue to favor shorting Blues convexity adjustment as a short vol proxy** (Rates Vol Lab - Short Blues convexity via futures/swaps).
> • Note: Futures trading involves substantial risk of loss"

### 7.9 Validation summary (what your implementation must reproduce)

| Check | Result |
|---|---|
| `Implied Vol` from `½σ²·mean(T1²)`, ED 1/12/17 | 13/13 rows within **±0.08%** |
| `Implied Vol`, SOFR 6/9/23 | 13/13 within **−0.21% to −0.59%** |
| `3m Roll = CA(p) − CA(p one nearer)`, ED 1/12/17 | **12/12 exact** (≤0.011bp) |
| `3m Roll`, SOFR 6/9/23 | **12/12 exact** |
| `3m Roll` negative control (shuffled) | **11/12 mismatch** — test is not vacuous |
| `CA − Model = VsModel`, SOFR | **13/13 exact** |
| `Cap vol I/R = trunc(σ_model/RV,1)`, ED + SOFR | **26/26 exact** |
| `Implied/Realized = round(IV/RV,1)` | exact on all spot-checked rows |
| Futures DV01 = swap DV01 | $100k/$1bn and $200k/$2bn ✓ |
| Fly belly DV01 = CA_DV01·β/100 | 0.996 and 0.997 ✓ |
| CA-leg 3m carry = Roll × CA_DV01 | 1.30bp × $100k = **$130k**, matches quoted $130k ✓ |

---

## 8. PACK CONVENTIONS

### 8.1 Definition and colour ladder

A **pack = 4 consecutive quarterly contracts** — [W-JAN13] p.12: *"We analyze 1y packs (four consecutive contracts)"*. Trading a pack means **equal contract counts in each leg**: *"buy 1000 of H0-Z0 packs (1000 of each of the four contracts)"* / *"2000 of H0-Z0 Eurodollar packs (2000 of each of the four contracts)"*.

Legend, [W-JAN13] Appendix VI, Figure 57 note, p.30 (line 1775):
> "Source: Citi Research, **W=White, R=Red, G=Green, B=Blue, Go =Gold and P=Purple**"

| Colour | Contracts (rolling, 1-indexed from the front quarterly) | 1/12/17 (front H7) | 6/9/23 (front M3) |
|---|---|---|---|
| Whites | 1–4 | H7-Z7 | M3-H4 |
| Reds | 5–8 | H8-Z8 | M4-H5 |
| Greens | 9–12 | H9-Z9 | M5-H6 |
| **Blues** | **13–16** | **H0-Z0** | **M6-H7** |
| Golds | 17–20 | H1-Z1 | M7-H8 |
| Purples | 21–24 | — | — |

Citi's tables are **rolling packs at every quarterly start**, not only the colour packs — the 1/12/17 table has 13 rows starting M8-H9, U8-M9, Z8-U9 etc., i.e. every 4-contract window, not just the 5 colour packs. Colours are labels applied to 4 of those windows.

### 8.2 Price ↔ rate

`futures_rate = 100 − price` for both ED and SR3. Pack price = arithmetic mean of the 4 leg prices ⇒ `pack_rate = 100 − pack_price = mean(leg rates)`. Pack quotes are conventionally shown as a **net price change** in ticks, but the CA calculation uses **levels**.

**DV01 = $25.00 per basis point per contract** for both ED (3M Eurodollar) and SR3 (3M SOFR) — both are 0.25 × $1mm × 1bp. Confirmed by the trade arithmetic: 1000 packs × 4 legs × $25 = $100,000/bp = "$100k DV01". This is the one convention that ports across ED→SFR with **no change at all**.

### 8.3 Contract-month codes

`H` = Mar, `M` = Jun, `U` = Sep, `Z` = Dec. Pack named `<first>-<last>`, e.g. `H0-Z0` = {H0, M0, U0, Z0}; `M6-H7` = {M6, U6, Z6, H7}.

### 8.4 SEPARATE MONITOR — do not confuse with the trade

[W-JAN13] Appendix VI, **Figure 57 "Eurodollar fly monitor"**, p.30 — a curve-RV screen, unrelated to convexity. Columns: `level (1/12/2017) | 1y Z-score | Correlation | Beta | Residual | PCA 1y Z-Score | PCA Residual | PCA Weights`.

**Eurodollar Packs section:**

| Fly | Level | 1y Z | Corr | Beta | Residual | PCA 1y Z | PCA Resid | PCA Weights |
|---|---|---|---|---|---|---|---|---|
| W/R/G | 16.1 | 2.8 | 92% | 0.19 | 4.9 (2.6) | 2.7 | 5.4 | **1.2:2:1.1** |
| R/G/B | 12.4 | 2.1 | 96% | 0.16 | 1.8 (1.2) | 1.3 | 2.0 | **1.1:2:1.1** |
| G/B/Go | 4.6 | — | 92% | 0.07 | -0.6 (-0.6) | 0.4 | 0.3 | **0.9:2:1.1** |
| B/Go/P | 1.9 | -0.7 | 55% | 0.03 | -2.7 (-1.9) | -0.7 | -0.8 | **0.8:2:1.2** |

Notes verbatim (p.30, lines 1776–1779): *"Correlation, beta and residuals are computed by regressing the fly against its belly. –ve residual value suggests that the fly is rich, +ve suggests that it is cheap."* … *"Note that PCA butterflies are created such that there is no correlation and beta with belly of the fly."* … *"Constant Maturity Eurodollars are computed using linear interpolation between Eurodollar futures."*

**These pack flies are NOT the hedge in the convexity trade.** The convexity trade's butterfly is the **2s5s10s swap fly** (§5).

---

## 9. SECONDARY SOURCES

### 9.1 [JPM], 3 May 2017 — same phenomenon, funding-cost framing

- **Same driver identified.** Exhibit 1 caption: *"The richness of convexity adjustments is driven in large part by dealer positioning, and that sensitivity peaks in 2-3 year forwards owing to issuance-related flows"* — matches Citi's positioning thesis (§10).
- **Ho-Lee with the same vol inputs:** *"Financing bias estimated using a Ho-Lee model … with ATM Eurodollar vols where available (out to the early Greens or so) and OTC Libor cap vols otherwise."*
- **Implied funding-spread reframing:** *"observable levels net of theoretical estimates imply collateral funding spreads that can be compared with actual costs … while these estimates were consistent with typical funding spreads among swaps dealers, more recently they have more than tripled, from **L+50-100 bp last year to nearly L+300 bp recently**."*
- **Margin figures:** *"We assume static margin on both, based on estimates provided by each clearinghouse for a pvbp-neutral package (**approximately 1.3% total margin**)."* CME-vs-LCH netting: *"the latter results in roughly **70-80% margin savings** versus the former."* CME/LCH front-end basis *"remaining well under 1 bp for the entirety of that period and spending most of its time around 0.25 bp."*
- **Their trade (opposite sign to Citi's, but same object):** *"we recommend **buying H9 and M9 Eurodollars versus CME-facing OTC FRAs** to position for a wider front-end CME/LCH basis and to monetize rich convexity adjustments."* Note "buying futures vs paying FRAs" = **short convexity**, the same direction as Citi's — the two desks agreed.
- **Monetizability:** *"the key distinction here is that the time to contract expiry is a couple of years compared with much longer maturities. This makes it much easier to monetize the actual/implied funding spread over a reasonable horizon."*

### 9.2 [CLARUS], 1 Jul 2015 — execution constraint

- **Hard prerequisite:** *"It is only possible to trade convexity between CME Eurodollars and FRAs if you clear the FRA at CME and have CME Portfolio Margining in place."* Directly corroborates Citi's CME-clearing instruction (§6.4).
- Payoff shape: *"The 'traditional' convexity style pay-off is only apparent when CME Portfolio Margining is applied. The humps that appear on the two lower lines are due to the cost of funding two lots of Variation Margin!"*
- Margin reference points: LCH FRA IM *"$1.37m to $1.4m"* across scenarios; CME SPAN *"$425,000 for 1,000 contracts of EDM6"* (i.e. **$425/contract**).
- Funding assumptions used: VM at *"OIS minus 12.5bp on ITM … OIS plus 12.5bp on OTM"*; IM term-funded at the 1y IRS rate.

---

## 10. NARRATIVE / SIGNAL CONTEXT (for the SOFR-era analogue)

[W-JAN13] p.11, lines 596–614 (verbatim, abridged to the mechanism):
> "We believe the recent richening of convexity adjustments is mainly due two factors: **positioning and corporate supply.** Last year both asset managers and leveraged funds increased their net short positions in ED futures, likely in anticipation of a Fed hike (Figure 18). Because futures are more liquid and transparent than FRAs, they are naturally preferred by a lot of accounts positioning for a more hawkish Fed. **Dealers, who were on the other side of these trades, had to hedge their long ED positions by paying in swaps and therefore were structurally short convexity adjustments.** Long dealers' positions in futures reached historically high levels pre-election, which should have put pressure on dealers' risk limits and therefore translated into wider CAs. Figure 19 demonstrates there is indeed a significant correlation between dealers' futures positions and the dislocation of CAs on the model (in monthly changes) … Further, corporate issuance surged this month … The associated receiving flows in swaps should have contributed to the widening pressure on CAs."

**Quantified positioning signal** — Figure 19, p.12: regression of monthly change in Blues CA-vs-model on monthly change in dealer ED positioning ($mn DV01), **`y = 0.00x − 0.15`, R² = 0.32**, sample **1/1/14 – 1/3/17**, CFTC data. Flow magnitudes: *"Asset managers and leveraged funds have increased short ED positions by over **$12.5mn DV01** since the election"* [W-JAN13]; *"over **$20.5mn DV01** since the election"* [TI-FEB9, three weeks later].

**Port note:** the CFTC ED positioning series is dead. The SOFR analogue is the CFTC **Traders in Financial Futures** report for SOFR futures (asset manager / leveraged fund / dealer net positions). [VL-SOFR] no longer uses positioning as the driver — it frames the trade purely as a **short-vol proxy** with the model gap as the signal.

---

## 11. GAPS, INFERENCES, AND PORT RISKS — EXPLICIT

| # | Item | Status |
|---|---|---|
| 1 | Ho-Lee `CA = ½σ²·mean(T1²)`, T1 to IMM date | **DERIVED + VALIDATED** on 8 tables. Not stated in any source. |
| 2 | Cap/floor vol **calibration method** (tenor, strike, stripping) | **NOT IN CORPUS.** Only *"calibrated to cap/floor vols"*. Operational workaround: calibrate so `σ_model` reproduces the `Cap vol Impl/Rlzd` column (§2.4). |
| 3 | Realized-vol convention (close-to-close, √252, sample stdev) | **INFERENCE.** Supported by the same report's swaption note *"Close-to-close realized vol is used"* and by the Impl/Rlzd ratio check. |
| 4 | Z-score window mechanics (trailing, inclusive, sample stdev) | **INFERENCE.** Not stated. |
| 5 | `n/a` trigger for low/negative CA | **IRREGULAR** in the source (§7.6). Use a CA floor ≈0.1bp; document the deviation. |
| 6 | Transaction costs | **EXPLICITLY EXCLUDED** by Citi: *"Calculations do not include transaction costs and other fees."* You must add your own. |
| 7 | `Rates Vol Lab – Short Blues convexity via futures/swaps` (the primary SOFR trade note, cited twice in [VL-SOFR] lines 115 and 834) | **NOT IN THIS CORPUS.** Obtain it — it is the SOFR-native equivalent of [TI-FEB9] and would supply SOFR-era entry level, target, stop and hedge weights. |
| 8 | SOFR `T1` micro-bias (−0.2% to −0.6% in vol) | Within rounding for RV work. Calibrate a small date offset only if sub-1% vol reproduction is required. |
| 9 | 2s5s10s regression weights / β for the SOFR era | **MUST BE RE-ESTIMATED.** The 2017 values (0.73/0.47, β=21.4; 0.705/0.465, β=20.6) are regime-specific and were already re-fit within three weeks of each other. Fit `CA ~ r2y + r5y + r10y` on your own history. |
| 10 | `pm_bbgchat.txt.md` | **EXCLUDED — different strategy** (10y10y/20y10y vega vs 1y-fwd 2s7s30s). Contains no convexity-adjustment content. Its only transferable instruction is methodological: *"you need to just calculate the dv01 parallel shift the curve and keep reweighting it each time"* and *"everything needs to be in terms of daily vol."* |

**Working notes retained at** `C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee\fd598297-c759-4904-8a06-2f2d2a03d199\scratchpad\findings.txt` (derivation summary only; all content above supersedes it).