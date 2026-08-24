# Group 11 — Carry/Roll Methodology References + Citi Velocity Sales Commentary

Corpus-2 extraction for the SOFR-futures-CA-vs-swap-fly backtest project. Five documents:
three Quantitative Finance Stack Exchange threads on IRS carry/roll-down methodology
(directly relevant to the **carry/rolldown-aware** CA-vs-fly variation), and two Citi
Velocity sales-commentary emails (EUR vol RV, low relevance — NOT the Citi CA fair-value
regression note referenced elsewhere in the project).

---

## 1. Carry Roll Calculation for Interest Rate Swaps in Nordea Note (Quant Finance SE)

- **Title:** "Carry Roll Calculation for Interest Rate Swaps in Nordea Note"
- **Publisher:** Quantitative Finance Stack Exchange
- **Dates:** asked Jun 16, 2024 (user nichel); top answer Jun 17, 2024, edited Jun 17, 2024 (user68819); second answer Jan 19 [2025?] (Big L). Viewed 702 times.
- **Underlying source discussed:** Nordea research note, https://corporate.nordea.com/api/research/attachment/2796

### Worked example (known-answer tie-out set)

Inputs from the Nordea note as quoted in the thread:

| Quantity | Value |
|---|---|
| 5Y spot swap rate | 1.023% |
| 6M Euribor | 0.319% |
| DV01 of 4.5Y swap in 6 months' time (6m fwd 4.5y) | 4.45 |
| P(0,6M) — 6M discount factor | 0.995 |
| 6m fwd 4.5y swap rate | 1.10% |

Accepted resolution (user68819), fixing the note's sloppy notation:

- **6M-horizon DV01 convention:** `dv01(6m) = 0.5 × df(6m)` — i.e. the accrual fraction (0.5 for 6 months) times the discount factor to the horizon. (Generalization confirmed in comments: 3M carry would use `dv01(3m) = 0.25 × df(3m)`. Big L's answer: the ÷2 is "the specific coverage for 6 months will average 2" — implicit in the note, sloppily.)
- **Carry upfront (bp):** `(5y swap − 6m Euribor) × dv01(6m)` = (1.023% − 0.319%) × 0.5 × 0.995 = **35 bp upfront**.
- **Carry running (bp), of the residual 6m4.5y swap:** divide upfront by the forward swap's DV01: 35 / 4.45 = **7.9 bp**.
- **Cross-check identity:** running carry = (6m fwd 4.5y swap − 5y spot swap) = 1.10% − 1.023% = **7.7–7.9 bp** — the horizon-forward-minus-spot formulation reproduces the funding-spread formulation.
- OP's original confusion: applying the note's formula 1a literally, `0.995 × (1.023% − 0.319%) / 4.45`, gives ≈16 bp not 7.9 bp — the missing factor is the 0.5 accrual (implicit ÷2). **Implementation warning:** the note's formula as printed is wrong/incomplete; the accrual fraction must be applied.
- Running-bp formula confirmed in comments: `carry_running = (5y swap − 6m Euribor) × dv01(6m) / dv01(6m4.5y)`.

Attack68's dissenting comment (Jun 17, 2024): P(0,6m) is "likely the 6m discount factor"; and philosophically "IRS do not have carry: if the curve evolves exactly as predicted a Swap will not gain or lose PnL" — the P&L merely splits between realized cash and residual NPV. Roll-down is a separate calculation assuming the *present* curve is maintained (static-curve assumption).

---

## 2. Carry calculation on an interest rate swap (Quant Finance SE)

- **Title:** "Carry calculation on an interest rate swap"
- **Publisher:** Quantitative Finance Stack Exchange
- **Dates:** asked Aug 26, 2017 (user29352); answers Aug 27, 2017 (dm63), Sep 3, 2017 (Attack68), Jun 18, 2018 (Lipton), Jan 5, 2020 (McCabe), Oct 12, 2021 (user35980). Viewed 29k times.

Question setup: pay-fixed 5Y USD IRS quarterly vs receive 3M Libor. **5y spot = 2%, 3m Libor = 1.3%.** Why is carry quoted as `forward rate − spot rate` (4.75y IRS starting in 3m, minus 5y spot) rather than the intuitive `spot − Libor` = 0.7%?

### dm63's equivalence proof (score 9) — load-bearing for any implementation

Decompose the 5y swap into 3m Libor + a 3m-forward 4.75y swap, DV01-weighted; ignoring discounting:

```
5yr swap rate = (0.25·3mLibor + 4.75·fwd) / 5
⟹ 0.25·(5yr − 3mLibor) = 4.75·(fwd − 5yr)
```

So **funding-spread carry and forward-minus-spot carry are the same number under different scalings**: forward−spot is carry **per unit DV01** (what Bloomberg shows); spot−Libor is carry **per unit notional**. With discounting, the 4.75 weight is replaced by the DV01 of the forward swap. Comment (Aug 29, 2017): "50k dv01 of 5yr swap has similar carry to 50k dv01 10yr swap, so 100mm 5yr and 50mm 10yr have similar carry."

### Attack68's answer (score 12, accepted-style)

Separates: (1) **costs-of-carry** = non-market holding costs (funding CCP margin, regulatory capital) — user-specific; (2) **roll-down** = expected PnL if the curve stays *the same as its current state* rather than evolving to forwards. A mid-market swap has zero expected PnL under forecast evolution: the 0.7% cash acquired over 3 months is exactly offset by a swap liability. The only repriceable part after the first fixing is the 3m-fwd 4.75y piece, so roll-down = (current 4.75Y swap − 3m fwd 4.75Y swap), delta-adjusted for that portion.

### Lipton's scenario-dependence answer (Jun 18, 2018)

Carry/roll depend on the assumed forward scenario (using zero-coupon-style compounding, pay-fixed 5y, funding at spot 5y):

| Scenario | Carry | Roll-down | Total |
|---|---|---|---|
| Tomorrow's spot curve = today's spot curve (static curve) | `Fwd4y5y − Spot5y` | `Spot5y − Spot4y` | `Fwd4y5y − Spot4y` |
| Tomorrow's spot curve = today's forwards (forwards realized) | `Spot1y − Spot5y` | `Spot5y − Fwd1y5y` | `Spot1y − Fwd1y5y` |

(Derivation uses `(1+Spot5y)^5 = (1+Fwd4y5y)(1+Spot4y)^4`.)

McCabe (Jan 5, 2020): the Libor leg is the "funding leg"; the swap is a collateralized bond financed in repo; for collateral cost, use SOFR-type repo rates, not Libor.

No tradeable tie-out numbers beyond the illustrative 2%/1.3% inputs.

---

## 3. Carry-roll-down assuming expectations of short-term rates are realized (Quant Finance SE)

- **Title:** "How does one calculate carry-roll-down theoretically assuming expectations of short-term rates are realised"
- **Publisher:** Quantitative Finance Stack Exchange
- **Dates:** asked Dec 15, 2020, edited Dec 15, 2020 (junior_pm); answers Dec 15, 2020 (Dimitri Vulis, edited Dec 16, 2020; Jan Stuller, edited Jun 3, 2023). Viewed 14k times.

Context: Tuckman's third carry-roll-down scenario ("expectations of short-term rates are realized") vs the standard two (forwards realized; yields unchanged). Tuckman quote: it is "much more difficult to implement… because an investor has to specify expectations of rates in the future and then describe how forward rates are formed relative to these expectations."

### Dimitri Vulis — the rolled-curve mechanics (P&L-explain framing)

- Static-curve implementation: rebuild the curve on T+0 from **T−1's quotes** (same 5y rate, maturity 1 day later); reprice. Change in accrued on both legs = **carry**; remaining passage-of-time change = **roll-down**.
- Rolled discount factors: `D(T+0, t) = D(T−1, t) / D(T−1, T+0)`.
- For P&L explain, this rolled-curve rolldown leaves **less unexplained P&L** than repricing on T+0 with T−1's curve unshifted (which double-counts realized forwards inside the IR-change bucket); alternative fix: viewless shift (forwards realized) + an IR-time cross-gamma term to cancel the double-count.

### Jan Stuller — sign conventions and bond carry (score 12)

- Pay-fixed 10y swap, upward-sloping curve: carry over first 6m = PV of `(c0 − r10)` — negative when curve is upward-sloping and you pay fixed. **Forward-starting swaps have zero carry** (no floating fixing at inception) — directly relevant to the project's forward-starting flies.
- Roll-down = revaluation as maturity shortens on a frozen curve: after 6m the 10y at r10 marks against r9.5 < r10 ⟹ negative roll for the payer.
- Summary conventions: carry = fixed rate − first floating coupon (annualized, quoted bp/day or bp/month); roll-down = fixed rate − next shorter liquid curve point.
- Bond carry per month, notional N, all rates annualized, bi-weekly funding/repo rolls: `C = N(−2·r_funding + y + 2·r_repo)` (accrual approximated at yield; Vulis comment: use the actual coupon, matters for far-from-par EM bonds).
- Key comment (Stuller, Dec 15, 2020): computing carry-roll-down under *realized risk-neutral expectations* is vacuous — if the pricing expectation is realized, cumulative carry+roll exactly equals the inception premium (zero for par swaps) — "not done in practice." Attack68 comment (Jan 22, 2021): prefers the single static-curve roll-down number; for swaps you can compute 1m/3m/6m roll straight off forward-rate differences on the curve, "and they are not always linear multiples of each other."

**Implication for the CA backtest's carry-aware variation:** use the static-curve (roll-down) convention off forward rates; treat forwards-realized as the null in which the strategy earns nothing.

---

## 4. Citi Velocity.pdf.md — EUR 1m10y gamma vs 1m5y/1m30y (LOW relevance)

- **Title (email subject):** "Eur (mattia latest on 1m10y vs 5y and 30y" — "The structural feature of the EUR gamma surface: 1m10y is persistently too cheap, especially vs 1m5y and 1m30y"
- **Publisher:** Citigroup Global Markets Limited — hedge-fund rates **sales commentary** (Jonny Brentnall relaying strategist "Mattia"), explicitly "NOT A PRODUCT OF CITI RESEARCH."
- **Date:** Jul 29, 2026, 7:57AM EDT.

Not about SOFR futures CA, swap flies, or CME-LCH basis. Content, for the record:

- Claim: EUR 1m10y gamma persistently cheap on the surface vs outlier-expensive 1m5y and 1m30y ("fifth time this year" flagged); attributed to price-insensitive selling from systematic/QIS indices.
- **Trade P&L tie-out:** long 1m10y vs short 1m5y and 1m30y gamma **1x2x1** (vol fly) "would have made almost **100 bpv over the past two years**" (cumulative P&L in vols, as of Jul 2026).
- Recommended simple expression: **buy 1m10y vs sell 1m5y, notional-neutral**. Alternative for 5s10s30s directionality (fly "relentlessly tightens in rallies and widens in sell-offs"): conditional flies, e.g. 1m 5s10s30s bear-widener.
- Charts/tables (expected returns, Sharpe, efficient frontier for EUR vols) referenced but not reproduced in the markdown.

Only tangentially useful to the project as an example of dealer framing of gamma-fly RV vs the 5s10s30s curve fly directionality claim.

## 5. Citi Velocity1.pdf.md — EUR 30s50s steepener vs 5y10y vol (LOW relevance)

- **Title (email subject):** "Eur (mattia) 30s50s steeps vs 5y10y vol"
- **Publisher:** Citigroup Global Markets Limited — sales commentary (Jonny Brentnall / "Mattia"), "NOT A PRODUCT OF CITI RESEARCH."
- **Date:** Jul 27, 2026, 7:00AM EDT.

Not about SOFR futures CA or CME-LCH basis. Content, for the record:

- **Curve tie-outs (as of ~Jul 27, 2026):** 30s50s slope — **EUR −28.8 bp** (flattest), **USD −26.6 bp**, **UK +16.8 bp**. EUR has by far the lowest implied vols yet the most inverted ultras ⟹ EUR ultras "too inverted versus all vols on the surface."
- **Trade:** pay EUR 30s50s in **100k** (bpv) vs buy **90mio notional 5y10y straddle** — later restated as "100k of curve vs 120k of 5y10y vol" (internal inconsistency between the two sizings; the 120k figure is the vol-leg bpv).
- Expiry-choice logic (value vs carry): 1y–2y expiries most distorted but punitive carry (implied/realized **>100%**); 7y–10y expiries less distorted, ~zero net carry (mild negative vol carry offset by positive 30s50s curve carry using the 10y10y point). 5y10y chosen "semi-arbitrarily" as the middle; long enough to avoid active delta-hedging.
- **Expected returns:** 5y10y vol leg ≈ **−2 bpv/yr**, partly offset by **+1 bp/yr** expected return on 30s50s.
- Cross-reference: similar 2024 recommendations in 10s30s discussing why curve has explicit and implicit exposure to volatility (the general "curve-vs-vol orthogonalization" framing — thematically adjacent to the project's fly-vs-CA idea but in EUR vol space).

---

## Cross-document synthesis for the carry/rolldown-aware CA-vs-fly variation

1. **Two equivalent carry quotes; pick one and scale correctly.** Funding-spread carry (fixed − first floating, per unit notional) ≡ forward-minus-spot carry (per unit DV01), linked by DV01 weights (dm63). For fly legs quoted in bp running, forward-minus-spot per unit DV01 is the natural convention and matches Bloomberg.
2. **Horizon carry formula with the accrual factor:** upfront bp = (spot swap − first fixing) × τ × df(horizon); running bp = upfront / DV01(forward residual swap) = (horizon-forward residual rate − spot rate). The Nordea note omits τ; a literal transcription is off by ~2× on 6M horizons (7.9bp vs 16bp in the worked example).
3. **Scenario discipline:** static-curve (Lipton row 1) is the practitioner roll-down; forwards-realized (row 2) is the zero-edge null (Stuller: realized pricing expectation ⟹ total carry+roll = 0 for par swaps). Compute roll for arbitrary horizons directly from forward-rate differences; they are not linear in horizon (Attack68).
4. **Forward-starting structures have zero carry** at inception (no fixed floating coupon) — the carry of a forward-starting fly is pure roll-down, which simplifies the carry-aware conditioning of forward flies vs futures packs (whose CA leg does accrue convexity P&L).
5. The two Citi Velocity emails are EUR vol sales notes, not the Citi Blues-CA regression source; their only reusable content is the curve-vs-vol orthogonalization framing and the tie-out levels recorded above.
