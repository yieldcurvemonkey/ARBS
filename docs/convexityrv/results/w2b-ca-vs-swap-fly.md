# W2b — SOFR pack convexity against a swap fly, 2021–2026: **DEAD**

Measured 2026-08-21, worktree `ARBS-cvx2`. 1,406 trading days, 45 epochs,
`rank_start=2, n_packs=16, n_contracts=20` so Blues (rank 13) and Golds (17) are
inside the fitted range for the first time.

**Verdict: the gross Sharpe is 0.130 against an expected maximum of 0.177 under
the null at six trials.** It fails before costs are considered, and costs then
remove 90 % of the gross anyway.

---

## 1. The arms

| arm | terminal | ann Sharpe | max drawdown |
|---|---:|---:|---:|
| unhedged, zero cost | +$2,483,251 | **0.130** | −$2,620,061 |
| hedged, zero cost | +$2,395,284 | 0.125 | −$2,659,882 |
| unhedged, 0.5 bp | +$233,251 | 0.012 | −$2,870,061 |
| hedged, 0.5 bp | +$145,284 | 0.008 | −$2,909,882 |
| unhedged, 1.0 bp | −$2,016,749 | −0.105 | −$3,607,512 |

## 2. Why it is dead

45 epochs with a mean hold of 26 business days over 5.62 years is about **54
independent observations**.

`expected_max_sharpe_under_null(N, n_obs=k)` defaults its standard error to
`1/sqrt(k)`, which is the SE of a **per-observation** Sharpe. The Sharpes
quoted here are **annualised**, and an annualised Sharpe has null SE
`1/sqrt(span_years)`. Those are different clocks, and with holds this long the
annualised one is the **larger** number — so quoting only the per-hold null
understates the bar the search has to clear. Both are therefore reported, and
the notebook asserts against both:

| trials | E[max SR \| null], per-hold (SE 0.136) | E[max SR \| null], annualised (SE 0.422) |
|---:|---:|---:|
| 6 | **0.177** | **0.548** |
| 12 | 0.227 | 0.702 |
| 24 | 0.270 | 0.835 |
| 48 | 0.308 | 0.953 |
| 1,569 | 0.461 | 1.426 |

The best gross Sharpe in the table is **0.130**. It clears neither null at any
trial count, and this work explored more than six configurations before
arriving here. The verdict does not rest on which clock is used, which is the
only condition under which reporting one of them would have been acceptable.

## 3. The hedge does not help — again

The 2s5s10s fly hedge is **worse than no hedge at every cost level**: 0.125
against 0.130 gross, and $145 K against $233 K net. That reproduces block 1's
finding on a different window and a much better panel — there, hedging moved the
Sharpe 0.191 → 0.070 and the hedge leg itself lost $606 K.

The factor attribution already said why: the tight forward pairs' dominant
unwanted exposure is **level (PC1)**, not slope, and a 2s5s10s fly is a curvature
instrument. `factor_neutral_sizing.py::curve_weights(..., neutralize=("PC1",))`
computes the hedge that would actually be pointed at the exposure; the fly is
not it.

## 4. The repaired data made the result *worse*, and that is the interesting part

W1 took Blues from 49 usable dates in 2023 to 229, and Golds from 0 in 2026 to
159. The strategy then got **worse**, not better.

That is not a contradiction — it is what a coverage repair is supposed to do to a
result that was previously measured on an accidental sample. Block 1 quoted this
book at an annualised Sharpe of 0.470 unhedged over 2020-08 → 2024-05, on a panel
whose deep end was mostly missing and whose window was chosen by where the data
happened to exist. On a complete panel over a fixed 2021-2026 window it is 0.130.

**A strategy whose Sharpe falls by two thirds when you give it the data it was
missing was never measuring what it appeared to measure.** That is the single
most useful thing W1 bought.

## 5. What *did* reproduce: the positioning mechanism

Citi's economic claim survives even though the trade does not.

> *"Dealers, who are on the other side of the shorts established by hedge funds
> and asset managers, have ended up with significant long ED positions. Convexity
> adjustments have therefore widened to compensate dealers for this concentration
> risk."*

The published regression — *Sell Eurodollar convexity in Blues*, Fig 4, monthly
2013-01 → 2017-12, `d(Blues CA − model)` on `d(dealer positioning)`, slope
`2e−06`, R² `0.2724` — reproduces on SOFR 2021-2026, 67 monthly changes, HAC
t-stats:

| colour | slope (bp/contract) | t | p | R² |
|---|---:|---:|---:|---:|
| Reds | −8.336e−07 | −1.66 | 0.097 | 0.030 |
| Greens | −9.319e−08 | −0.23 | 0.815 | 0.001 |
| **Blues** | **+5.280e−07** | **+2.59** | **0.010** | **0.124** |
| Golds | −6.435e−08 | −0.29 | 0.770 | 0.002 |

Blues — the colour the published figure is *about* — agrees in sign, is within a
factor of four on slope, and is significant. The other three are indistinguishable
from zero. A published relationship holding on a different decade, a different
index, and specifically on the colour it was published for is about as much as a
reproduction of this kind can offer.

**It reproduces and the trade still loses.** The mechanism being real does not
make the spread tradable after costs, and the two questions are separate.

### The version of this that gave the opposite answer

`vs_model` is keyed by **pack label** (`M4-H5`, `U4-M5`, …) and a label lives only
until the strip rolls past it. The first implementation took the lowest-ranked
label's column, which collapsed Blues from 2,000 dates to **239 inside one
calendar year**, and then reported a monthly regression on **eleven** points at
slope −8.21e−06, t = −3.80, R² = 0.359 — opposite sign, apparently significant,
entirely an artifact. A colour is a **rank** stitched across labels.

## 6. Current positioning, for the screener

Measured on SOFR-3M, 2020-01 → 2026-05: dealer net correlates **−0.9547** in
levels against (leveraged money + asset managers). Dealers are currently long
**1,719,008** contracts — the maximum of the sample — while leveraged money sits
at its minimum, **−1,530,754**. On Citi's thesis that is the configuration that
widens the adjustment, and it is the screener's most important single reading.

## 7. The Citi tie-out, and the discrepancy it was hiding

`w2b_ca_screener` grades our CA against the 13 published rows of Citi's Figure 58
for 2023-06-09. It used to do so with `assert pearson > 0.90`, which graded
**nothing**: Citi's published CA is almost linear in pack rank — rank alone
explains 99.4 % of its variance — so a correlation against it is very nearly a
statement about the ordering, and every affine transform of our column preserves
the ordering exactly. Measured, the correlation is **0.966 under all four** of:

| mutation | pearson | median \|err\| | slope | intercept | old check | new check |
|---|---:|---:|---:|---:|---|---|
| ×2 (double-counting a leg) | 0.966 | 11.28 bp | 1.700 | +3.53 | **passes** | fails |
| ×100 (percent read as bp) | 0.966 | 950.92 bp | 84.98 | +176.42 | **passes** | fails |
| +10 bp (a level offset) | 0.966 | 9.34 bp | 0.850 | +11.76 | **passes** | fails |
| ÷√252 (bp/yr read as bp/day) | 0.966 | 11.09 bp | 0.054 | +0.11 | **passes** | fails |

The replacement grades in bp on a level — median and max absolute error, mean
error, and the slope and intercept of ours regressed on theirs — and section 2.2
of the notebook re-runs those four mutations to demonstrate that it can fail.

Real figures: **13/13 rows, median error 0.99 bp, worst 3.06 bp, mean −0.04 bp.**

**And the slope is 0.850, not 1.0.** That is a finding the correlation could
never have surfaced. Our CA curve is about **15 % flatter across rank** than
Citi's, sitting on a **+1.76 bp pedestal**: front packs (rank ≤ 8) run **+2.04 bp
rich** to them, deep packs (rank ≥ 13) **−0.54 bp cheap**. Citi price off a cap
surface; we invert the futures-versus-swap identity. A difference in the term
structure of vol lands exactly there. It is a level disagreement of about a
basis point at the ends — not a units error and not a sign error — and it is now
on the record instead of averaged into a correlation.

## 8. Data provenance, stated because two things share one name

* **Dealer positioning** — CFTC TFF, weekly, lagged **3 business days** to
  publication (the report measures Tuesday, publishes Friday 15:30 ET, and the
  raw file carries no release stamp).
* **Open interest** — CFTC `Open_Interest_All`, **whole strip**, weekly, no
  per-contract dimension. Per-contract SR3 open interest on this machine is
  *survivorship-shaped*: coverage splits at the live/expired line (SR3M26 0.008,
  SR3U26 0.980), so front ranks before ~2025 have none.
* **Whites is absent by design**, not for want of data: `Strat2Config` enforces
  `rank_start >= 2` because the 3m roll column differences against a nearer pack.
