# SFR Butterfly Mean-Reversion Lab — Findings

**Date:** 2026-07-29
**Branch:** `feat/sfr-fly-meanrev`
**Design:** `2026-07-29-sfr-fly-meanrev-design.md`
**Plan:** `../plans/2026-07-29-sfr-fly-meanrev.md`
**Executed notebooks:** `notebooks/backtests/sfr_fly_meanrev_*.ipynb`,
`notebooks/backtests/sfr_fly_rules_of_thumb.ipynb`
**League table:** `notebooks/data/sfr_fly_meanrev/league_table.csv` (+ `_sorted.csv`)
**Desk card:** `notebooks/data/sfr_fly_meanrev/rules_of_thumb.csv`

## Summary

Nine method families were implemented and backtested on daily SR3 settles across every 3m
and 6m butterfly on the front 16 quarterly contracts. Every framework is marked on **raw
futures settlement prices**, filled lag-1, charged 1.5bp round trip on the package, swept
over a grid, sign-tested in both directions, split by policy regime, decomposed against its
own linear shadows, and graded by the same `verdict` function as the SR3 options lab.

**Nothing is ALIVE.** But unlike the options lab, the reason is a single measurable number
rather than an absence of signal:

> **The butterflies mean-revert. The edge is real and statistically significant. It is
> worth about 0.4–0.9bp per trade, and the round trip costs 1.5bp.**

That reframes the result from "no alpha" to "an execution problem with a known size". The
gross edge is roughly **half** the taker cost, so the strategy needs about a 2× improvement
in fill quality — not a better signal — to break even. **38 of 48 league rows are positive
gross; 0 of 48 have a positive grid median.**

Three results carry more information than the league table itself:

* **The edge is a regime, not a strategy.** Summed across frameworks: **+476bp in the 2022-23
  hiking cycle, −905bp in the cutting cycle** (14/23 frameworks positive in the former,
  2/23 in the latter). Fly dispersion, not the signal, changed.
* **The fly loses to its own outright belly.** Running the identical signal on the belly beats
  the butterfly in **16 of 24** frameworks; the fly beats every linear shadow in **1 of 24**,
  and that one has a single trade.
* **~~The `1/-2/1` convention is the wrong weighting~~ — retracted in §5a.** The apparent tilt
  to ~0.43/0.58 was substantially +1.9% of outright rate exposure; forcing level-neutrality
  moves it to 0.463/0.537, *cuts* the stationary count 7/16 → 4/16 and *lengthens* the median
  half-life 20.6d → 30.3d. `1/-2/1` at 4 contracts is the cheapest level-neutral 3-leg package
  that exists, and with identical-DV01 futures no re-weighting can improve cost per sigma
  (measured invariance: 1.000). What does survive is unrelated to cointegration — larger
  integer coefficients resolve the spread more finely against the 0.5bp tick grid.

## Data

| | |
|---|---|
| Source | Barchart EOD per contract symbol (`SR3<MonYY>` → `SQ<MonYY>`), one full-history request per symbol |
| Raw span | **2018-05-04 → 2026-07-29** (8.24 years, 2,074 sessions, 55 contracts, 66,227 contract-days) |
| Marks | raw settlement prices; `rate_pct = 100 − settle` |
| Structures | 14 3m flies/day (slots `i, i+1, i+2`), 12 6m flies/day (slots `i, i+2, i+4`) |
| Keys | absolute contract triples (`U26-Z26-H27`), so no roll enters any series |

A complete 16-deep strip is formable on **every** session from 2018, because SR3 contracts
list ~5 years ahead. The binding constraint is liquidity, not the feed, and it is severe:

| | slots 1–8 | slots 9–16 |
|---|---|---|
| 2018–2020 | tradeable (0–2% zero-volume days from 2019) | **100% zero-volume days**, zero open interest |
| 2021 | tradeable | 50–63% zero-volume days on slots 13–16 |
| 2022 onward | tradeable | tradeable (0% zero-volume days on every slot) |

So the lab runs two windows and reports both, rather than picking one:

* **`liquid16`** — 2022-01-03 → 2026-07-29 (1,150 sessions). Every strip slot trades every
  session. This is the only honest full-cross-section window.
* **`front8`** — 2019-01-02 → 2026-07-29 (1,907 sessions), restricted to flies whose back
  leg is inside slot 8. This is the regime-rich window: it is the only one that contains
  ZIRP and the hiking cycle.

Nothing is believed on one window alone. Where they disagree it is reported.

## Structural results (measured, and independent of any strategy choice)

### 1. The flies do mean-revert — and the usual test threshold is wrong

Against a Monte-Carlo random-walk null of the same length (300 paths, 481 bars, the median
per-fly sample), the Hurst exponent's null is **not** centred tightly on 0.5:

| `max_lag` | null mean | null sd | 5th pct | 95th pct |
|---|---|---|---|---|
| 20 | 0.483 | 0.054 | **0.391** | 0.561 |
| 50 | 0.469 | 0.070 | 0.348 | 0.574 |
| 100 | 0.426 | 0.093 | 0.275 | 0.573 |

A wider `max_lag` uses more of the series and has a *fatter* null, so it is the worse
choice. At `max_lag=20` the one-sided 5% critical value is **H < 0.391**, not 0.5 — and
**15 of 22** flies clear it. The variance ratio agrees: VR(5) < 1 on **23/23** keys, and
significantly so (Lo-MacKinlay heteroskedasticity-robust z < −1.96) on **14/23**.

ADF disagrees — it rejects a unit root at 10% on only **3/23** keys. That is the expected
pattern, not a contradiction: ADF has low power against a slowly reverting alternative at
this sample size, while the variance ratio is built for exactly it. Reporting only ADF would
have concluded "not stationary, nothing here", and reporting only Hurst against a 0.5
threshold would have concluded "all 23 mean-revert". Both would be wrong.

### 2. The edge is real, and it is about a fifth of the cost

The clean statement, from the primary z-score fade on the 3m panel over 2022+:

| round trip charged | total bp | avg bp/trade | hit rate |
|---|---|---|---|
| 0.0 (maker) | **+105.5** | +0.75 | 47.5% |
| 0.5 | −98.5 | −0.33 | 31.3% |
| 1.0 | −247.0 | −0.83 | 20.9% |
| 1.5 (a per-*leg* charge) | −395.5 | −1.33 | 16.2% |
| **2.0 (per-CONTRACT — the correct figure)** | | | |
| 2.5 (taker) | −692.5 | −2.33 | 9.8% |

141 trades. The hit rate at zero cost is essentially a coin flip with a small positive
expectancy; the cost curve does the rest. Every framework in the lab has this shape — gross
positive, maker positive, taker negative — which is why the verdict distribution is almost
entirely `MARGINAL-maker-only` rather than `DEAD`.

**Cost correction.** The lab charges 0.25bp per **leg** one-way, i.e. 1.5bp round trip on a
3-leg fly. That is wrong for futures: cost is per **contract**, the belly is two contracts,
and you cross the spread on both. The correct round trip for a `1/-2/1` fly is
`4 contracts × 2 sides × 0.25bp = ` **2.0bp**, so every net figure in this document is ~25%
optimistic and the true numbers sit between the 1.5bp and 2.5bp rows. Re-run on the Q12
universe with per-contract costing, the plain fly makes **+29.75bp gross over 76 trades** and
**−122.25bp net at 2.0bp**.

That gives the sharpest statement of the problem. Break-even requires

```
half-spread per contract = gross bp per trade / (2 × contracts)
                         = 0.391 / 8 = 0.049 bp
```

against the 0.25bp half-tick a taker pays — so the program needs an effective half-spread of
**one fifth of a half-tick**, i.e. roughly **5× better execution on every contract, on both
entry and exit**. Not the ~2× a per-leg cost model implies. The break-even round trip is
**0.39bp** on a package whose taker round trip is 2.0bp.

### 2b. Why the equity curves look monotone, and why flipping the sign cannot fix it

The net equity curves slope down almost without interruption, which naturally invites the
question: if it loses that reliably, why not just trade the other way? Audited end to end in
`notebooks/rv/_audit_sign_conventions.py`.

**The curve is monotone because of cost, not signal.** For the same config, over 235 trades:

| | max | min | final | trades moving it up | new highs |
|---|---:|---:|---:|---:|---:|
| **gross** curve | +121.5 | −10.0 | +72.2 | 40.6% | 26 / 235 |
| **net** curve | −0.5 | −397.8 | −397.8 | 14.1% | 2 / 235 |

The gross curve wanders like a random walk with a slight upward drift. The net curve is that
same walk minus a fixed **2.0bp per trade**, which dominates it completely. A monotone net
curve on a wandering gross curve is a bleed, not an invertible signal.

**Flipping the sign flips the gross but not the cost.** `fade` and `momentum` open the same
trades on the same bars on opposite sides, so this is an identity, verified exactly:

```
gross_fade + gross_momentum = +0.000000        (same trades, opposite sides)
net_fade   + net_momentum   = −940.0 = −2 × total cost
```

| direction | trades | gross | cost | net |
|---|---:|---:|---:|---:|
| fade | 235 | **+72.25** | 470.0 | −397.75 |
| momentum | 235 | **−72.25** | 470.0 | −542.25 |

Picking the better side is already what the grid does, and the better side is still −398bp,
because `|gross| = 72bp` is a seventh of the `470bp` of cost. There is no sign to flip into.

**The oracle ceiling.** The strongest possible version of "get the direction right": an oracle
that knows the winning side on *every* trade in hindsight.

| round trip | perfect-hindsight side | actual rule |
|---|---:|---:|
| 0.0bp | +558.8bp | +72.2bp |
| 1.0bp | +323.8bp | −162.8bp |
| **2.0bp (per-contract)** | **+88.8bp** | −397.8bp |
| **2.5bp (taker)** | **−28.8bp** | −515.2bp |

The oracle captures **2.378bp per trade** against a **2.0bp** round trip, so **even perfect
direction-calling is barely profitable at 2.0bp and loses money at taker costs**. Its
break-even is a 2.378bp round trip = 0.297bp per contract per side.

That reframes the whole lab. The constraint is not the sign and not the signal quality — it is
that **the moves being captured (2.4bp on average) are barely larger than the cost of
capturing them (2.0bp)**. The actual rule harvests 0.31bp of that 2.378bp, i.e. **13% of what
is theoretically available**, and closing the entire remaining 87% would still only be worth
+0.38bp per trade at 2.0bp cost.

**Per-side attribution confirms there is no sign error.** Under `fade`, *both* sides are
gross-positive — short-spread +24.50bp over 103 trades, long-spread +47.75bp over 132. A
flipped sign somewhere in the stack would show up as one side being systematically
gross-negative; neither is.

### 3. The "typical level" of a fly is a regime statement, not a number

Median level in bp by constant-maturity slot and policy regime (3m flies, front-8 panel):

| slot | ZIRP | HIKING | PLATEAU | CUTTING |
|---|---:|---:|---:|---:|
| SFR123 | 0.0 | **+29.25** | +5.0 | **−2.5** |
| SFR234 | 0.0 | +13.75 | +0.5 | −5.5 |
| SFR345 | −0.5 | +7.50 | −3.0 | −6.0 |
| SFR456 | −1.0 | +1.00 | −5.0 | −3.5 |
| SFR567 | −0.5 | −3.50 | −6.5 | −2.5 |
| SFR678 | −1.0 | −6.50 | −7.0 | −2.0 |
| SFR789 | −0.5 | −5.00 | −4.5 | −1.5 |

`SFR123` swings **31.75bp** between the hiking and cutting cycles — more than twenty round
trips. The unconditional six-year median of +0.5bp is the average of incompatible states and
is not a fair value anyone should quote. The daily standard deviation moves with it: 1.13bp
in ZIRP, 3.73bp in the hiking cycle, 1.42bp in the cutting cycle for the same slot.

This is why the rules of thumb are stated per regime, and why a single mean-reversion
parameter set across the whole sample was never going to work: the OU fit's `mu` is a
six-year average, so a large part of the "reversion" it measures is the walk between
regimes.

**And the regime is the single biggest driver of P&L in the whole lab.** Summing each
framework's best config across all 23 that reported a regime split:

| regime | total net bp, all frameworks | frameworks net positive | trades |
|---|---:|---:|---:|
| ZIRP | −327.0 | 2 / 23 | 289 |
| **HIKING** | **+476.0** | **14 / 23** | 680 |
| PLATEAU | −364.8 | 7 / 23 | 486 |
| **CUTTING** | **−905.0** | **2 / 23** | 906 |

Fading SR3 flies **worked in the 2022-23 hiking cycle and lost more than it made everywhere
else**, worst of all in the cutting cycle. The mechanism is the same cost arithmetic as §2:
in the hiking cycle `SFR123`'s daily standard deviation was 3.73bp, so a 1.5bp round trip
was 0.4 sigma; in the cutting cycle it is 1.42bp, so the same round trip is 1.06 sigma. The
edge did not disappear — the moves shrank relative to the spread.

That also means the aggregate result is a **regime average masquerading as a strategy**, and
any live deployment of a single parameter set would have been long the 2022-23 environment
without knowing it.

### 4. The back of the strip is a tick lattice, and every estimator is fooled by it

SR3 settles on a 0.005 price grid outside its final four months (0.0025 inside) — **0.5bp of
rate**. A fly inherits that lattice. Measured on the 2022+ panel:

| slot | sd (bp) | sd in ticks | distinct values in 1,149 sessions | % days unchanged | % days within 1 tick | fitted half-life |
|---|---:|---:|---:|---:|---:|---:|
| SFR123 | 15.71 | 31.4 | 452 | 12.9% | 41.9% | 33.5d |
| SFR456 | 6.45 | 12.9 | 191 | 31.6% | 69.0% | 38.9d |
| SFR789 | 3.21 | 6.4 | 115 | 42.0% | 88.1% | 28.5d |
| SFR-11-12-13 | 1.07 | 2.1 | 52 | 46.0% | 93.8% | 5.9d |
| SFR-12-13-14 | 0.76 | 1.5 | 31 | 47.3% | 93.7% | 4.0d |
| SFR-13-14-15 | 0.71 | 1.4 | 36 | 48.0% | 95.9% | 3.6d |
| **SFR-14-15-16** | **0.52** | **1.0** | **22** | **51.0%** | **95.5%** | **1.8d** |

The fitted half-life falls monotonically from 33.5 to 1.8 days *exactly as* the
standard-deviation-per-tick falls from 31.4 to 1.0. `SFR-14-15-16` takes 22 distinct values
in four and a half years and is unchanged on half of all sessions. **Its 1.8-day half-life
and Hurst of 0.109 are discretisation, not reversion** — and one tick is 0.5bp against a
1.5bp round trip, so none of it is reachable.

Any screen that ranks flies by fitted half-life will therefore put the *least* tradeable
slots at the top. This also accounts for the TAR asymmetry result below being strongest
precisely where the lattice is tightest.

### 5a. RETRACTION — the fitted vector was buying direction, and re-weighting cannot pay for itself

**This supersedes §5b below, which was written before the weights were mapped back to whole
contracts.** §5b reported the fitted cointegrating vector as the strongest remaining lead.
Testing it properly (`notebooks/backtests/sfr_fly_meanrev_weights.ipynb`, Q12 universe,
slots ≤ 12) closes it for two independent reasons.

**First: the tilt was net outright rate exposure.** An unconstrained regression of the belly
on its two wings has no reason to make the loadings sum to 1, and any excess *is* direction —
the same direction the shadow test (§7) already showed makes money on its own. Measured on 16
keys:

| | front wing | back wing | loading sum | ADF p < 0.10 | median half-life |
|---|---:|---:|---:|---:|---:|
| plain fly | 0.500 | 0.500 | 1.000 | — | 42.0d |
| **unconstrained fit** | 0.448 | 0.572 | **1.019** | **7/16** | **20.6d** |
| **level-neutral fit** | 0.463 | 0.537 | 1.000 (forced) | **4/16** | **30.3d** |

The unconstrained fit carries **+1.9% of outright rate exposure per unit belly**, positive on
every key. Forcing level-neutrality — which is mandatory, or it is not a fly — moves the wings
back toward 0.5/0.5, **reduces** the stationary count from 7/16 to 4/16 and **lengthens** the
median half-life from 20.6d to 30.3d. The stationarity and the fast reversion in §5b were
substantially the leak. A *rolling* 252-day fit carries the same leak (mean loading sum 1.021,
sd 0.018) and wanders, so this is not an in-sample artifact that a causal fit removes.

**Second: with identical-DV01 futures, re-weighting cannot improve cost-to-signal.** Each SR3
contract is $25 per bp of its own rate, so for weights `w`:

```
DV01       = $25 per bp of the spread S = Σ wᵢrᵢ   -- INDEPENDENT of w
contracts  = Σ|wᵢ|
round trip = Σ|wᵢ| × 2 × 0.25bp = Σ|wᵢ| × 0.5 bp of S
```

For a level-neutral 3-leg package the wings sum to the belly, so `Σ|w| = 2 × belly` and the
cost in bp of the spread **is** the belly. The spread also scales with the belly, so
`cost / σ(spread)` is invariant to package scale and depends only on volatility *per unit
belly*. Any tilt that damps that volatility therefore raises the cost per sigma one-for-one:

| package | contracts | round trip | σ per belly-2 | median half-life | ADF p<0.10 | **round trip in σ_eq** |
|---|---:|---:|---:|---:|---:|---:|
| **`1/-2/1`** | **4** | **2.0bp** | 3.76 | 42.0d | 0/16 | **0.463** |
| `2/-5/3` | 10 | 5.0bp | 3.46 | 62.7d | 3/16 | 0.495 |
| `3/-7/4` | 14 | 7.0bp | 3.40 | 46.9d | 2/16 | 0.514 |
| `6/-13/7` | 26 | 13.0bp | 3.31 | — | — | 0.529 |

Tilting *does* damp the spread's volatility (3.76 → 3.31 per belly-2, ρ ≈ 0.88) — and the
cost per equilibrium sigma rises by exactly `1/ρ`. The product of the two ratios measures
**1.000**. There is no free lunch in re-weighting a package of identical-DV01 futures, and
`1/-2/1` at 4 contracts is the **cheapest level-neutral 3-leg package that exists**.

The backtests agree. Normalised to the same 100-contract position (valid because DV01 per bp
of spread is weight-independent), and with **every** grid having zero positive configs:

| package | gross $ | net $ | grid median |
|---|---:|---:|---:|
| `1/-2/1` | +$29.4k → | **−$76.4k** | negative |
| `3/-7/4` | | −$70.1k | negative |
| `6/-13/7` | +$29.4k | −$68.1k | negative |

An 11% improvement in a large negative number, from 6.5× the contracts, with 0/4 grids
positive. That is noise, not a lead.

**Integer expression.** The level-neutral tilt (0.463 front share) needs a belly of
**13 — 26 contracts** — to express to within 0.001. The practical menu is only ever three
packages (belly 2, 5, 7) and then nothing better until belly 41.

**But one thing does survive, and it is not what §5b claimed.** On an equal-contract basis the
tilted packages capture *more* gross per contract, and the break-even execution requirement
falls: `6/-13/7` needs **3.3×** better fills against the plain fly's **5.1×**. The mechanism is
resolution against the tick grid, not the cointegrating vector:

| package | contracts | spread tick | σ | **σ in grid steps** | distinct values | % days unchanged |
|---|---:|---:|---:|---:|---:|---:|
| `1/-2/1` | 4 | 0.5bp | 3.76 | **7.5** | 166 | 26.3% |
| `2/-5/3` | 10 | 0.5bp | 8.65 | 17.3 | 347 | 12.1% |
| `3/-7/4` | 14 | 0.5bp | 11.89 | 23.8 | 385 | 8.5% |
| `6/-13/7` | 26 | 0.5bp | 21.49 | **43.0** | 462 | 7.0% |
| *6× plain fly* | *24* | *3.0bp* | *22.57* | ***7.5*** | *166* | *26.3%* |
| *7× plain fly* | *28* | *3.5bp* | *26.34* | ***7.5*** | *166* | *26.3%* |

The two italic control rows are the point. **Every equal-wing package is an exact integer
multiple of `1/-2/1`**, so scaling raises the tick and the σ together, leaves σ/grid at exactly
7.5, and produces a *literally identical* z-score (verified: `max |z(fly) − z(6× fly)| ≈ 0`)
— the same trades, 6× the size. Tilting is the **only** way to obtain a spread that is resolved
finely against the 0.5bp settlement grid, because it raises the coefficients without changing
the base grid. The plain fly is unchanged on **26% of sessions**; `6/-13/7` on **7%**.

Given §4 — that a coarse grid corrupts every mean-reversion estimator, and that the whole back
of the strip is a lattice — that is a real and previously unnoticed effect. It is also
*orthogonal to cointegration*: the benefit comes from the size of the integer coefficients, not
from their ratio matching a fitted vector. So the residual lead is **"pick weights that resolve
finely against the tick grid"**, which is a different and cheaper question than
**"estimate the cointegrating vector"** — and it is still not enough to make anything tradeable
(0/4 grids positive, every package net negative).

### 5b. [SUPERSEDED by §5a] The fitted cointegrating vector looked better than `1/-2/1`

This is the most interesting near-miss in the lab, and the one place where a modelling
choice moved the result by a factor of three.

Regressing the belly on both wings over the full sample, the fitted weights **sum to 1.00
on every one of 23 keys** (range 0.997–1.035), which is a clean independent confirmation
that a butterfly is the right *shape*. But the split is systematically **back-weighted**,
not even:

| | front wing | back wing |
|---|---:|---:|
| butterfly convention | 0.500 | 0.500 |
| Engle-Granger, mean over 23 keys | **0.432** | **0.578** |
| Box-Tiao, mean over 23 keys | **0.439** | **0.576** |

Two independent methods agree on a ~15% tilt toward the back wing. And the tilt matters for
stationarity, which is the property the whole thesis rests on:

| | ADF p < 0.10 | median ADF p | median half-life |
|---|---:|---:|---:|
| asserted `1/-2/1` fly | **3 / 23** | 0.434 | **40.7d** |
| Box-Tiao fitted spread | **17 / 23** | **0.034** | **14.7d** |

So the traded butterfly is mostly **not** stationary, while the fitted combination of the
same three contracts mostly **is**, and reverts nearly three times faster. That is a real
finding about the convention, not a curve-fitting artifact — Engle-Granger and Johansen both
reproduce `(−1, +2, −1)` exactly on synthetic data, so the tilt is in the SR3 data.

It carries into the backtest, and by a large factor:

| signal | grid median | best config | % of configs positive |
|---|---:|---:|---:|
| asserted `1/-2/1`, z-scored | −556.8bp | −113.5bp | 0% |
| **fitted EG residual, z-scored** | **−188.0bp** | **−7.5bp** | 0% |

A **3× improvement in the grid median** and a best config within 7.5bp of break-even over
4.6 years — but still not positive, and still 0% of configs. The P&L is marked on the traded
butterfly throughout, because a non-integer vector is not what gets executed; trading the
fitted weights themselves needs per-leg contract counts and a different cost model, and is
the single most promising thing left untested.

The opposite test also matters: `SparseMeanReversionPortfolio.greedy_search` over the
**whole** 16-slot strip, free to pick any three contracts with any weights, selects slots
**(1, 2, 16)** with weights (1.25, −2.0, 1.86) — half-life **106 days**, ADF p = 0.379.
That is *worse* than the consecutive fly on both counts. So the answer is specifically "keep
adjacent contracts, tilt the wings", not "search freely".

### 6. Even the theoretically optimal cost-aware band earns single-digit bp per year

Bertram's optimal thresholds, fitted per constant-maturity slot on the raw bp series and
solved at the 1.5bp round trip, give the expected profit per unit time at the optimum — the
best any band on that fitted OU could do:

| slot | fitted half-life | optimal entry (bp) | expected hold | **expected return** |
|---|---:|---:|---:|---:|
| SFR123 | 33.5d | +7.4 | 23d | **+16.4 bp/year** |
| SFR234 | 52.7d | +1.2 | 54d | +7.1 bp/year |
| SFR456 | 38.9d | −3.3 | 67d | +5.8 bp/year |
| SFR789 | 28.5d | −6.3 | 233d | +4.7 bp/year |
| SFR-14-15-16 | 1.8d | −1.4 | 67d | +2.5 bp/year |

At 100 packages (400 contracts, $2,500/bp) the best slot's theoretical optimum is
**≈ $41k per year**, and the back of the strip ≈ $6k. Zeng's "reverse at the opposite band"
rule roughly doubles those figures by halving the cycle. These are model numbers, not
backtest numbers, and they are the ceiling: they assume the fitted `(mu, kappa, sigma)`
persist, which §3 says they do not.

The mismatch is also structural. The band the model wants is **narrow** (entry 0.53–2.06
equilibrium sigmas) and the hold it wants is **long** (23–349 days). Both sit outside the
grid a desk would sweep, and the notebook's "trade the model's own recommended band" cell
tests that recommendation directly rather than concluding from the sweep.

### 7. The fly's edge is partly its outright belly

`fly = (belly − front) + (belly − back)`, so every framework was re-run with the identical
signal on the outright belly and on each belly-versus-wing spread, each charged its own leg
count (0.5bp for the outright, 1.0bp for a 2-leg spread, 1.5bp for the fly).

The result is close to unanimous across all 24 frameworks:

* the fly beats **every** linear shadow in **1 of 24** frameworks — and that one is the
  1-trade Kalman hedge-ratio config the verdict already marks `DEAD (too few trades)`;
* the **outright belly alone** beats the fly in **16 of 24**.

On the primary z-score config the fly makes **−106.0bp** net while the **outright belly on
the same signal makes +389.5bp**, and `belly_vs_back` makes +7.5bp. Read plainly: a fly
z-score contains a directional rates signal, and the butterfly packaging spends three legs
of spread to express what one leg expresses better. This is the diagnostic that most changes
what one would build next — before adding any signal sophistication, the question is whether
the fly is the right instrument at all.

The sign test is a useful counterweight to that scepticism: **fade wins in 17 of 23
frameworks, momentum in 6**, so mean reversion is the right direction — it is the packaging
and the cost, not the thesis, that fail.

### 8. State filters remove trades without improving the trade

Sixteen gates on the identical base signal and config — Hurst bands, half-life bands, ADF
thresholds, realised-vol halves, FOMC proximity, curve level and slope. Change in **average
net bp per trade** versus the ungated rule:

| gate | bars open | trades | Δ avg net bp/trade |
|---|---:|---:|---:|
| curve flat/inverted | 20.6% | 170 | **+0.18** |
| front rates above median | 20.6% | 169 | +0.17 |
| realised vol top half | 19.9% | 186 | +0.04 |
| half-life 3–20d | 7.4% | 68 | −0.01 |
| ADF p < 0.05 | 9.6% | 113 | −0.05 |
| Hurst < 0.45 | 29.2% | 274 | −0.16 |
| within 5d before FOMC | 5.2% | 124 | −0.17 |

The best gate improves the average trade by **0.18bp** against a 1.5bp cost and a −1.23bp
starting point. Every gate cuts total losses, but only by cutting trade count — which is not
information. Notably the *mean-reversion* gates (Hurst, half-life, ADF) are among the
**worst**: conditioning on a fly looking statistically mean-reverting does not make fading
it more profitable, which is consistent with §4 (those statistics are measuring the lattice).

## The league table

48 rows across 24 framework variants (`notebooks/data/sfr_fly_meanrev/league_table_sorted.csv`).

| | |
|---|---:|
| **ALIVE** | **0** |
| SELECTION-ARTIFACT | 2 |
| MARGINAL-maker-only | 35 |
| DEAD | 8 |
| DEAD (too few trades) | 3 |
| rows net positive **gross** | **38 / 48** |
| rows net positive at maker (0.0bp) | **38 / 48** |
| rows net positive at taker (2.5bp) | 3 / 48 |
| rows with a positive **grid median** | **0 / 48** |
| median DSR probability | **0.0000** (threshold 0.5) |

That table is the whole thesis in one place. **79% of rows make money gross and 6% survive
taker costs** — and the three that do are the degenerate 0-trade and 1-trade configs the
verdict already flags. Not one row has a positive grid median, so every positive headline is
the best corner of a negative sweep, and no selected config beats the expected best-of-N
under the null.

The three least-dead rows, for the record:

| framework (best config) | n | gross bp | net @ taker | grid median | DSR p | verdict |
|---|---:|---:|---:|---:|---:|---|
| 2b. OU S-score (3m, front8, 2019+) | 47 | +129.8 | +12.3 | −53.9 | 0.04 | SELECTION-ARTIFACT |
| 2c. OU S-score (6m, liquid16) | 140 | +355.0 | +5.0 | −87.9 | 0.00 | SELECTION-ARTIFACT |
| 5b. Kalman dynamic hedge ratio | 1 | +16.5 | +14.0 | 0.0 | — | DEAD (too few trades) |

Dollars throughout assume **100 packages** = 400 contracts = **$2,500/bp**.

## The rules of thumb

`notebooks/backtests/sfr_fly_rules_of_thumb.ipynb` and
`notebooks/data/sfr_fly_meanrev/rules_of_thumb.csv`, as of 2026-07-29, on the 2022+ panel.
"Fade band" is the **causal** one: the smallest distance from a *trailing* 250-day median at
which the rule was net positive over at least 10 trades, charged 1.5bp per completed trade.

| slot | typical | IQR | 90% range | daily sd | half-life | now (z) | fade beyond | hit | n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **3m** | | | | | | | | | |
| SFR123 | +5.0 | 21.2 | −12 to +37 | 3.18 | 33.5d | +9.0 (+0.25) | — none pays — | | |
| SFR234 | +1.0 | 16.0 | −12 to +21 | 1.72 | 52.7d | +8.5 (+0.71) | **±2** | 52% | 33 |
| SFR345 | −2.5 | 11.5 | −10 to +18 | 1.53 | 42.2d | +6.0 (+1.01) | **±4** | 50% | 18 |
| SFR456 | −3.5 | 7.5 | −9 to +12 | 1.21 | 38.9d | +2.0 (+0.85) | — none pays — | | |
| SFR567 | −3.5 | 5.0 | −12 to +7 | 0.98 | 37.6d | −3.0 (+0.10) | ±4 | 40% | 10 |
| SFR678 … SFR-14-15-16 | −3.5 → −0.5 | 5.5 → 0.5 | | 0.64 → 0.42 | 47d → 1.8d | | — none pays — | | |
| **6m** | | | | | | | | | |
| SFR135 | +5.1 | 64.4 | −39 to +89 | 6.27 | 64.8d | +32.0 (+0.63) | **±6** | 62% | 37 |
| SFR246 | −8.0 | 44.5 | −35 to +61 | 4.82 | 58.3d | +22.5 (+0.98) | ±0.5 | 60% | 40 |
| SFR357 | −13.0 | 29.0 | −35 to +42 | 3.99 | 47.3d | +7.0 (+0.85) | ±20 | 56% | 16 |
| SFR468 | −13.5 | 19.0 | −43 to +27 | 2.84 | 55.3d | −6.0 (+0.40) | ±0.5 | 63% | 52 |
| SFR579 | −13.5 | 21.0 | −40 to +12 | 1.83 | 75.5d | −8.0 (+0.36) | ±8 | 36% | 14 |
| SFR-6-8-10 … SFR-12-14-16 | −10.5 → −1.5 | 13.5 → 3.0 | | 1.80 → 0.67 | 47d → 12d | | mostly none pays | | |

**10 of 26 slots have any causal fade band that pays.** Read the table with four caveats,
all of which are in the notebook:

1. **The 6m flies are the better instrument.** They carry 2.5–3× the dispersion of the 3m
   fly for the same three-leg cost, and they hold 4 of the 5 best rows. `SFR468` (63% over
   52 trades) and `SFR246` (60% over 40) are the strongest in the lab.
2. **The `±0.5bp` bands are grid-boundary solutions**, not thresholds. 0.5bp is the smallest
   band tried and it is where a fly with a 44bp IQR wants to sit — the rule is really "always
   be positioned against the trailing median", not "wait for a dislocation".
3. **"Typical" is unconditional and therefore misleading.** `SFR123` is +29bp in the hiking
   cycle and −2.5bp in the cutting cycle against a +5.0bp unconditional median. Use the
   per-regime columns.
4. **Below about `SFR789` the numbers are a tick lattice** (§4) — an IQR of 0.5–1.0bp against
   a 1.5bp round trip, so there is nothing to trade regardless of what the half-life says.

Note that size is not the whole story: `SFR123`, the largest and most liquid fly, has **no**
paying band, while `SFR234` and `SFR345` do. The front fly moves most but is also where the
policy-path repricing is most persistent, so it trends through the band rather than reverting
inside it.

## Bugs found and fixed

Each of these was found by a test or a cross-check, and each had produced a wrong number
first.

1. **`optimal_ou_thresholds` used the wrong first-passage series.** It put `Gamma(k/2)` in
   the **denominator**. Monte Carlo on the standardised OU `dz = −z dt + sqrt(2) dW`
   (40k paths, dt = 5e-4) measures `E[tau(−1 → +1)] = 3.042`; the corrected numerator form
   gives 2.995 and the shipped denominator form gives **1.366**. Every threshold it returned
   was solving the wrong optimisation.
2. **…and carried a spurious `sqrt(2)/2`** on the derivative term of the first-order
   condition (the spec's factor applies to the undifferentiated sum, not to `S'`).
3. **…and its zero-cost branch returned a fallback constant.** With `cost = 0` the FOC has
   no root because the objective is maximised as the band width goes to zero; `brentq`
   raised and the `except` returned `1.0` — which sits *above* the solved 0.017 at cost 0.01,
   breaking monotonicity in cost. Two existing tests passed only because of that constant.
4. **…and never used `kappa` or `sigma`** despite taking them: `(1.0, 1.0, 0.0)` and
   `(99.0, 42.0, 0.0)` returned identical thresholds. Bands in level units now come from
   `ou_band_levels`, which is where those parameters earn their place.
5. **`plt_timeseries._hurst_exponent` returned `2 × slope`** and measured **H = 1.035 on a
   pure random walk**. Confirmed independently: `arbitragelab`'s
   `get_hurst_exponent` is algebraically identical to the corrected form
   (its `sqrt(...)` and `× 2.0` cancel), and agrees bit-for-bit.
6. **The R/S Hurst estimator was applied to levels.** R/S is defined on increments; on
   levels it read **H = 0.99 on a random walk**.
7. **The variance ratio divided by `q` twice.** The Lo-MacKinlay denominator
   `m = q(n−q+1)(1−q/n)` already carries `q`, so `varq` is already per-period. A random walk
   read **VR = 0.197** instead of 1.0, and its z-statistic **−32.7** instead of ~0.
8. **The rolling AR(1) fit's `min_periods` counted bars, not pairs.** The first bar of a
   window has no predecessor, so a naive `rolling(w)` fit at bar `w−1` silently used `w−1`
   pairs and disagreed with `calibrate_ou` on the same slice.
9. **The cross-sectional `rank` signal was bounded by ±1** (`(pct − 0.5) × 2`), so in a grid
   shared with z-score entries every threshold above 1.0 produced **zero trades** and the
   whole method dropped out silently. Replaced with normal scores.
10. **A `None` grid value became `NaN`** in the sweep frame and reached `int()`.
11. **The constant-maturity label was assigned once per key.** A fly's CM slot rolls through
    its life, so one label per key tagged every key with the slot it was *born* at — which
    put 15 of 24 keys in `SFR-14-15-16`. Trades are now attributed by `(entry date, key)`,
    and a separate roll-adjusted CM panel exists for reporting.
12. **`notebooks/backtests/SFR_screeners/_curve_panel.py:93` scales `fixed_rate` as a
    decimal when it is a percent**, so its `bf_bps` and `*_rate` columns are **100× too
    large**. Not used by this lab; flagged because it is live prior art.

## Repo issues found, not fixed

1. **`USD-SOFR-1D-Q16STIRT` is degenerate on recent dates.** On 2026-07-27 its front six
   strip rates sit **22–36bp away from the SR3 settles it is calibrated to**, and slots 8–14
   return bit-identical rates (`4.038996478235703`). Its fly correlates **−0.377** with the
   settle fly, median ratio ≈ 0. `USD-SOFR-1D-Q12STIRT` reprices the same settles to 0.5bp
   on the same date and reproduces the settle fly exactly (ratio 1.000, corr 0.996). The Q12
   config sets `stirf_target_weight: 1e6` and the Q16 config does not
   (`MDP/IRSwaps/BARCHART_STIRF/rl.py:1048` vs `:1071`), which is the first place to look.
   On 2025-06-12 and 2023-06-14 Q16 tracks settles to ~1bp, so this is date-dependent.
   Reproduce with `notebooks/rv/_probe_curve_vs_settle.py`.
2. **The vendored `mlfinlab` is ~95% stubs that return `None` silently.** `get_sadf`,
   `get_chow_type_stat`, `frac_diff`, `frac_diff_ffd`, `trend_scanning_labels` and the whole
   `bet_sizing` module import fine, execute in 0.00s, and return `None` — the dangerous
   failure mode, since nothing raises. Only `filters` (`cusum_filter`, `z_score_filter`) and
   `datasets` are functional. `arch.unitroot` is already installed and covers what
   `structural_breaks` was meant to. `arbitragelab`, by contrast, is complete and unstubbed.
3. **`RVUtils/SFRKinkFadeScreener` and `RVUtils/STIRRVScreener` import their half-life from
   `BT.signals.sfr_kink_fade`**, so an `RVUtils` package depends on `BT` — inverted layering.
   Left alone to keep the blast radius small; the canonical `half_life` now exists in
   `RVUtils/mean_reversion.py` for them to move to.

## Toolkit refactor

The audit found **11 independent OU/half-life implementations**, 7 mutually incompatible
`adfuller` call conventions, 27 z-score sites, and both Hurst and the variance ratio trapped
as closures inside a plotting builder (therefore unreachable by any caller).

`RVUtils/mean_reversion.py` now holds the canonical core: `half_life`, `rolling_ar1`,
`rolling_half_life`, `rolling_zscore` (with an `exclude_current` ablation),
`hurst_exponent` (correct scaling, `std` and `rs` estimators), `rolling_hurst`,
`variance_ratio`, `variance_ratio_stat`, `ou_mle`, `expected_passage_time`,
`ou_band_levels`, `bertram_thresholds`, `kalman_local_level`, `kalman_hedge_ratio`,
`adf_pvalue`. `plt_timeseries._hurst_exponent` / `_ou_calibrate` and
`FlyVsVol.screener.series_half_life` now delegate to it, each with its existing sentinel
pinned under test.

`RVUtils/MeanRev/` is new: `panel.py` (strip slots, structure enumeration, CM tags,
liquidity, regimes), `engine.py` (the panel backtest with the honesty rules structural),
`signals.py` (the method families), `shadow.py` (the linear-shadow decomposition). It reuses
`RVUtils/SFRRVLab/stats.py` unchanged, so both labs are graded by identical code.

**Measured optimisation** (`notebooks/rv/_profile_meanrev.py`, 2,074 bars × 26 keys):

| hot path | naive | optimised | speedup |
|---|---:|---:|---:|
| rolling AR(1) / OU fit, window 120 | 5.664s | **0.091s** | **62×** |
| rolling cointegrating regression, window 252 | 0.006s | 0.003s | 1.6× (bit-identical to 1.9e-13) |
| the whole curve-fit notebook | did not finish in 40 min | **~3 min** | **>13×** |

The AR(1) one matters because `ou_sscore(window=...)` re-fits from scratch at every bar; the
rolling-cross-moment form is what makes an OU sweep across 26 keys practical.

The curve-fit notebook was the surprise. Profiling showed the cost was entirely Svensson:
55.4s per panel against 1.9s for Nelson-Siegel and 0.06s for a cubic, because
`least_squares` was re-seeded from a fixed guess on all 1,150 dates. Two fixes: **warm-start
each date from the previous date's parameters** (the strip barely moves overnight, so the
iteration count collapses), and **memoise the residual panel per `(form, panel)`** — the
diagnostic block, the grid and the raw-bp variant all want the same four panels, so it was
computing each about ten times over. Neither changes a single number in the output.

Tests: **85** synthetic, no-network tests in `tests/test_rv_meanrev_core.py` and
`tests/test_meanrev_engine.py`, plus the two rewritten in `tests/test_rv_ou_optimal.py`.

## What I would test next

1. **~~Trade the fitted vector~~ — CLOSED, see §5a.** Tested and retracted: the tilt was
   substantially a directional leak, and re-weighting a package of identical-DV01 futures
   cannot improve cost per sigma. What replaced it is narrower and more interesting:
   **choose integer weights that resolve finely against the 0.5bp tick grid.** `6/-13/7`
   is unchanged on 7% of sessions against the plain fly's 26%, and needs 3.3× better fills
   rather than 5.1×. That is worth one more pass — but on grid resolution, not cointegration,
   and it does not on its own make anything tradeable.
2. **Maker execution — now the only real lead.** The edge is +0.39bp per trade against a
   **2.0bp** per-contract taker round trip, and it is positive at zero cost with a 47.5% hit
   rate. Break-even needs an effective half-spread of **0.049bp per contract per side**, one
   fifth of a half-tick, on all four contracts and on both entry and exit. A
   queue-position / fill-probability study on SR3 leg quotes is the only thing that can move
   this, and it is now the whole question.
3. **Intraday.** The measured half-lives on the tradeable front slots are 28–53 days, which
   is far longer than any of the swept holds, while the back slots' short half-lives are
   lattice artifacts. Daily EOD may simply be the wrong frequency; the repo already has
   intraday SOFR curve infrastructure (`eris_live_intraday`, `citivelo`).
4. **The asymmetric fade.** TAR rejects symmetric adjustment on 8/14 slots, with rich flies
   reverting faster than cheap ones. On the front slots — where the lattice does not explain
   it — that is a directly implementable asymmetric rule and it was not tested here.
5. **Conditional-on-regime parameter sets.** §3 shows the fair level moves by more than
   twenty round trips between regimes. A rule that re-anchors `mu` on a regime classifier
   (rather than a trailing window) is the obvious next formulation, and the state-filter
   notebook's "fit and trade inside one regime at a time" cell is the starting point.
6. **Fix or avoid Q16STIRT.** Any future work wanting curve-implied SR3 forwards should use
   Q12STIRT until the Q16 calibration is repaired.
