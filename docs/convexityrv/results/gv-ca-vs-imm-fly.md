# GV — SOFR convexity adjustment vs an IMM-dated swap butterfly: **DEAD**

Block 4 of the convexity RV programme, measured 2026-08-24 in
`C:/Users/chris/clee/ARBS-cvx4` on branch `feat/convexity-rv4`. Every number
below was measured on this machine. The search space was frozen in
`docs/convexityrv/gv-preregistration.md` **before any scoring**, with six dated
amendments.

**This is the third pass over the same convexity-adjustment panel** (block 1
`strat2`, block 3 `cavf`/PR #492, now `gv`). The cumulative-search caveat is on
the record and travels with every number here.

---

## The brief, and the verdict

> *"we need to flush out 3m sofr futures convexity adjustment vs swap butterfly
> (butterflies should be imm dated forewards …) (need to take care handling the
> imm roll in the backtest ideally we dont have a position on during the roll/we
> are flat). i know that a significant tradable edge is here. we can think of
> swap butterflies as vol proxies in linear space. convexity adjustments is pure
> gamma. we are essentially trading gamma vs vega here."*
>
> *"i believe the pervious backtest results look bad bc of sizing issues"*

**The sizing objection is correct.** The previous grid's hedge leg was 2.0–7.7×
too small to be a volatility hedge — median 3.8×. That is a real defect and it
is measured below.

**Fixing it does not rescue the trade, for a reason that is itself the finding.**
The vega-matched hedge is *undefined* on 72–100% of days, because a swap
butterfly is not a volatility proxy in the sense a hedge ratio needs: after
controlling for level and slope, **0 of 11 declared legs clear a partial-R²
gate of 0.05** against ATMF normal vol. The tractable rule of the same size
(risk parity) makes the book worse, and **no hedge at all beats every hedge**.

**And the mechanism is real** — the raw level relation the brief's regressions
found is strong (R² up to 0.88), correctly signed, and matches the desk's own
framing of a long-end flattener as long vega. It is a co-trend between two
prices of the same volatility, not an incremental response, and it does not
survive a hedge ratio, a roll-flat window, an engine, or a null bar.

---

## 1. The data, and its tie-out

| panel | size | grade |
|---|---|---|
| CA via `IRSwapsTB.sfr_cvx_adj` (Q/Q matched swap) | 1,409 dates × 31 labels, 2021-01-04..2026-08-21 | carried forward from block 3 and **re-priced**: 18 random (date × colour) cells, **max \|fresh − panel\| = 0.00000000 bp** |
| IMM leg panel, 118 queries | 1,416 dates × 118 columns | density **0.9993–1.0000** for 2021-2025, 0.9644 on the 2026 tail; 36 min to build |
| CFTC TFF positioning | to 2026-08-18, release-lagged 3 bd | reused unchanged from block 3 |
| CME–LCH CCP basis | 1,414 dates × 11 tenors, offline cache, lagged 1 bd | fetched explicitly, not via a fallback that returns nothing silently |

The leg panel carries `IMM_k × {1,2,3,5,7,10,20,30}y` for k ∈ {1,2,4,5,8,9,12,
13,16,17,20}, spot par legs, eight long-end forwards, ten ATMF straddle normal
vols, and — as tie-outs — the two fly and two curve columns the brief printed.

**The brief's own regression reproduces to four decimals** on this panel:
BLUES CA on `IMM_1x2y/IMM_1x5y/IMM_1x10y FLY RATE`, n = 161, const **+7.6893**,
β **+0.1461**, R² **0.394**. Same object, same numbers.

**Two quoted conventions are pinned to zero**, because a factor of two here is
a silent halving of exactly the leg this block re-sizes:

* `FLY RATE = (2·belly − front − back) × 100`, max \|diff\| **0.0**;
* `CURVE RATE = (back − front) × 100`, max \|diff\| **0.0**.

A fly quoted that way is a belly of **2×** and wings of **1×** the
quoted-combination DV01, so it is charged **4×**, not 1×.

---

## 2. THE SIZING ANSWER

Scaling a whole book cannot change its Sharpe, so the objection can only be
about the *relative* size of the two legs. Median |β| over all 21
(structure × leg) pairs, at $100k CA DV01:

| rule | median \|β\| | hedge DV01 | gate pass |
|---|---:|---:|---:|
| `beta_lvl` — the brief's own levels regression, block 3 family B | 0.105 | **$10,480** | — |
| `beta_chg` — block 3 family A, daily changes | 0.115 | $11,510 | — |
| `vol_ratio` — risk parity, sign from the daily changes | 0.308 | $30,790 | — |
| **`vega_match`** — `(∂CA/∂σ)/(∂leg/∂σ)`, both at the same benchmark vol | **0.324** | **$32,390** | **0.000–0.277** |

**The vega-matched hedge is 2.0–7.7× the incumbent, median 3.8×.** The
objection is right.

But `vega_match` gates on `|t| ≥ 2` **and** the partial R² of the vol term
`≥ 0.05` after level/slope controls, and that gate refuses **91.8% of days at
the median cell**. Five of the six `vega_match` headline cells produce **zero
episodes**. The fix cannot be evaluated on its own terms — which is not an
implementation problem, it is section 3 arriving from the other direction.

Two more sizing defects, both measured before the freeze:

* **The level β and the change β have opposite signs on 37 of 70 pairs**, and
  the level-β hedge *increases* daily variance on **46 of 70**. Since
  `var(ΔCA − βΔleg) = var(ΔCA) − 2β·cov + β²var(Δleg)` and `cov < 0`, a
  positive β adds variance. Block 3's family B was hedging with the wrong sign.
* **The CA mark is noise-dominated**, so a rolling daily-change β carries `2ν`
  of irreducible residual variance and is close to random. AC1 of the daily
  change, full sample: WHITES **−0.540**, REDS **−0.517**, GREENS −0.228,
  BLUES −0.392, GOLDS −0.395, against a pure-noise bound of −0.5.

### And when the hedge IS correctly sized, the book gets worse

298 declared cells, $100k CA DV01, t+1 fills, roll blackout on, zero cost:

| sizing rule | cells | median gross | median net @1× | median gross Sharpe | max | median hedge DV01 |
|---|---:|---:|---:|---:|---:|---:|
| **`none` (no hedge)** | 42 | **+$1,006,769** | **+$106,769** | **0.571** | 0.662 | $0 |
| `beta_chg` | 42 | +$800,707 | −$449,527 | 0.336 | 0.851 | $13,215 |
| `beta_lvl` | 42 | +$731,422 | −$410,337 | 0.251 | 0.758 | $9,867 |
| `vol_ratio` | 42 | +$376,209 | −$1,295,606 | 0.203 | 0.576 | $37,116 |
| `unit` (β = 1) | 42 | +$705,579 | −$2,491,868 | 0.107 | 0.563 | $100,000 |
| `vega_match` | 42 | $0 | $0 | 0.015 | 0.144 | (gated out) |

**No hedge (0.571) beats the incumbent hedge (0.251) beats the correctly-sized
hedge (0.203), monotonically in hedge size.** `none` is also the only family
still positive at 1× its own costs. This is the answer to the sizing objection
in one line: the sizing was wrong, and correcting it makes things worse, because
the leg being sized carries no information about the thing it is hedging.

---

## 3. Is a swap butterfly a volatility proxy at all?

The brief's premise, and it is testable. `vega_match` divides by `∂leg/∂σ`, so a
noise-sized slope there is an *unbounded* hedge.

The regression is `Δleg = a + b_v·Δσ + b_L·Δlevel + b_S·Δslope + ε`, because the
CA's vega `σ·w/1e4` is a pure volatility derivative by construction and a fly
that loads on level and not on vol is a duration bet wearing a vol costume.

| leg | raw level β | raw level R² | controlled β | t | **partial R²** | gate |
|---|---:|---:|---:|---:|---:|---|
| `immF_2s5s10s` | −0.662 | 0.350 | +0.284 | +7.29 | 0.037 | ✗ |
| `imm2_2s5s10s` | −0.601 | 0.417 | +0.209 | +6.06 | 0.026 | ✗ |
| `immM_2s5s10s` @ GREENS | −0.198 | 0.357 | −0.029 | −2.37 | 0.004 | ✗ |
| `immM_2s5s10s` @ BLUES | −0.172 | 0.320 | −0.024 | −1.45 | 0.002 | ✗ |
| `immM_2s5s10s` @ GOLDS | −0.150 | 0.300 | −0.001 | −0.03 | 0.000 | ✗ |
| `immM_1s2s3s` @ GREENS | −0.097 | **0.565** | −0.020 | −2.41 | 0.004 | ✗ |
| **`le_10y10y_20y10y`** | **−1.131** | **0.814** | −0.122 | −5.40 | 0.020 | ✗ |
| **`le_10y10y_15y10y`** | **−0.604** | **0.882** | −0.061 | −4.76 | 0.016 | ✗ |
| `spot_2s5s10s` | −0.679 | 0.308 | +0.305 | +8.06 | 0.044 | ✗ |

**0 of 11 clear the gate at full sample; median rolling gate-pass 0.127.**

Read the two halves together. The raw level relation is **real, strong and
correctly signed** — `10y10y/20y10y` on 10Yx10Y ATMF nvol has R² **0.814** with
a **negative** β, i.e. a flatter long end is higher vol, which is precisely the
desk framing in the corpus ("10y10y/20y10y curve flattener … leaves you long
vega short gamma without having to trade a swaption"). But once the level and
slope channels are removed, the incremental vol response is 0.0–4.4% of the
variance. Two series that trend together over one hiking cycle are not a hedge
pair.

The `immM` legs are the worst of all: rolling vol β median **−0.005 to +0.017**
with sd 0.06–0.09. The matched-expiry IMM flies have **no measurable vega**.

### 3b. The brief's own two regressions, reproduced — and then extended

Both printed fits reproduce **exactly** on this panel:

| regressor | window | n | const | β | R² | DW |
|---|---|---:|---:|---:|---:|---:|
| `IMM_1x2y/IMM_1x5y/IMM_1x10y` fly | brief's | 161 | **+7.6893** | **+0.1461** | **0.3937** | 1.146 |
| `10y10y/20y10y` curve | brief's | 410 | **−0.3514** | **−0.0993** | **0.5047** | 0.764 |

Now run each one on the *other* two windows:

| regressor | n = 161 | n = 410 | n = 1,409 (full) |
|---|---|---|---|
| IMM_1 2s5s10s fly | β **+0.1461**, R² **0.394** | β +0.0150, R² **0.009** | β **−0.0841**, R² 0.223 |
| 10y10y/20y10y curve | β −0.0570, R² **0.064** | β **−0.0993**, R² **0.505** | β −0.0790, R² 0.247 |

**Each regression is strong only on the window it was run on.** The fly's R²
falls from 0.394 to **0.009** when the window is widened from 161 to 410 days,
and its β **flips sign** on the full sample. The curve's R² is 0.064 on 161 days
and 0.505 on 410.

Rolling 410-bd windows across the whole sample, all 21 (structure × leg) pairs:
R² ranges **0.000 to 0.807**, the β's range is **0.395 at the median pair
against a median |β| of 0.110 — a span 3.6× the level itself — and the sign
flips within the sample on 20 of 21 pairs**. A hedge ratio that changes sign
inside its own sample is not a hedge ratio.

The Durbin–Watson statistics are the tell that was already on the brief's own
printouts: **0.764 and 1.146**, and 0.097–0.112 on the full sample. Residuals
that autocorrelated are the textbook spurious-regression signature.

And the decisive test, because it removes the obvious objection that daily CA
marks are too noisy to see a relationship: **resample to weekly and the level R²
survives while the change R² does not.**

| structure | leg | weekly level β | level R² | level DW | weekly **change** β | **change R²** |
|---|---|---:|---:|---:|---:|---:|
| GREENS | `le_10y10y_15y10y` | −0.105 | 0.375 | 0.166 | +0.006 | **0.0003** |
| BLUES | `le_10y10y_15y10y` | −0.205 | 0.416 | 0.297 | +0.046 | **0.0035** |
| BLUES | `le_10y10y_20y10y` | −0.080 | 0.243 | 0.223 | +0.039 | **0.0085** |
| GOLDS | `le_10y10y_15y10y` | −0.364 | **0.579** | 0.346 | +0.175 | **0.0315** |
| GOLDS | `le_10y10y_20y10y` | −0.149 | 0.370 | 0.217 | +0.112 | **0.0428** |

If the level relation were a pricing relationship, cleaning the noise out by
sampling weekly would make the *change* relation appear. It does not: weekly
change R² is **0.0003–0.089** against level R² of 0.05–0.58, and the change β is
**positive** where the level β is negative. The two series drift together; they
do not move together.

---

## 4. The roll — and the finding that the roll jump IS the theta

**The two roll clocks are one business day apart.**
`IRSwapsTB._cvx_front_imm_code` advances the SR3 rank map **on** the IMM date;
`Query.Base.imm_resolution.resolve_imm_token("IMM_1", d)` searches from
`d + 1 day` and advances the business day **before**. Over 1,409 dates each
produces exactly 22 roll dates and **none coincide**. A blackout on either
clock alone leaves the other jumping unhedged, so the blackout is the union:
IMM−3 bd through IMM+1 bd, **132 of 1,409 dates (9.37%)**, leaving 23 tradeable
segments of median 56 bd.

The jump it removes is large and signed:

| pack | mean ΔCA on roll | t | \|ΔCA\| on roll ÷ off |
|---|---:|---:|---:|
| GREENS | **+0.741 bp** | +2.44 | 5.63 |
| BLUES | **+0.946 bp** | +2.70 | 1.80 |
| GOLDS | **+1.223 bp** | +2.46 | 1.89 |

A long-CA book held through every roll books **+$1.63M / +$2.08M / +$2.69M** of
pure label-switching at $100k DV01.

### The identity

`w = mean_i(T1_i²)` and every `T1_i` shortens with the calendar, so
`dw/dt = −2·mean_i(T1_i)` and

```
dCA_bp/dt  =  −σ_bp² · mean(T1) / 1e4       bp per year
```

Measured: **−0.237 / −0.308 / −0.367 bp per month** for GREENS / BLUES / GOLDS.
One quarter of that decay against the measured roll jump:

| pack | quarter of theta | measured roll jump | ratio |
|---|---:|---:|---:|
| GREENS | −0.710 bp | +0.741 bp | **1.045** |
| BLUES | −0.924 bp | +0.946 bp | **1.024** |
| GOLDS | −1.100 bp | +1.223 bp | **1.111** |

**They are the same quantity.** The constant-rank CA series looks stationary
only because the roll reset pays back the decay. Confirmed a third way by the
causal forward roll-splice — the level path of a position nobody rolls — which
drifts **−14.9 / −16.5 / −21.2 bp** over the sample against a predicted theta of
**−16.0 / −20.8 / −24.8 bp**.

Two consequences:

1. **A roll blackout leaves the decay one-sided.** A two-sided book acquires a
   systematic short-CA **carry**, ≈ +1.2 bp per quarter held short. That is
   Citi's own published trade, and it is carry, not alpha. Every headline number
   here is decomposed into analytic carry and residual.
2. **`WHITES` (ratio 4.31), `REDS` (−0.73), `SFR12` (−0.47), `SFR16` (−4.23) and
   `SFR20` (−5.18) fail the identity**, which is an independent read on which
   marks are trustworthy. It agrees with everything else about them.

---

## 5. The grid — 298 declared cells

2,591 episodes. **67.1% exit at `segment_end`** rather than on the signal: the
roll blackout, not the rule, is closing two thirds of the positions.

### The headline 12 — the brief's trade at the incumbent sizing and at the fix

| structure | leg | sizing | n_ep | hedge DV01 | gate refusal | gross | ann SR | net @1× |
|---|---|---|---:|---:|---:|---:|---:|---:|
| GREENS | `immF_2s5s10s` | `beta_lvl` | 10 | $3,721 | 8.9% | +$816,067 | 0.646 | −$8,361 |
| GREENS | `immF_2s5s10s` | `vega_match` | **0** | — | **82.8%** | $0 | — | $0 |
| GREENS | `immM_2s5s10s` | `beta_lvl` | 10 | $6,945 | 8.9% | +$274,377 | 0.268 | −$614,515 |
| GREENS | `immM_2s5s10s` | `vega_match` | **0** | — | **86.9%** | $0 | — | $0 |
| BLUES | `immF_2s5s10s` | `beta_lvl` | 8 | $4,477 | 8.9% | +$528,861 | 0.147 | −$142,775 |
| BLUES | `immF_2s5s10s` | `vega_match` | **1** | $17,200 | **84.1%** | +$181,847 | — | +$72,448 |
| BLUES | `immM_2s5s10s` | `beta_lvl` | 12 | $22,466 | 8.9% | +$780,043 | 0.199 | −$659,139 |
| BLUES | `immM_2s5s10s` | `vega_match` | **0** | — | **100%** | $0 | — | $0 |
| GOLDS | `immF_2s5s10s` | `beta_lvl` | 7 | $10,562 | 8.9% | +$1,550,878 | 0.346 | +$878,008 |
| GOLDS | `immF_2s5s10s` | `vega_match` | **0** | — | **95.2%** | $0 | — | $0 |
| GOLDS | `immM_2s5s10s` | `beta_lvl` | 10 | $48,025 | 8.9% | +$1,163,304 | 0.255 | −$547,198 |
| GOLDS | `immM_2s5s10s` | `vega_match` | **0** | — | **100%** | $0 | — | $0 |

Six of six `beta_lvl` cells are positive gross; **five of six go negative at 1×
their own costs**, and the best gross Sharpe among them (0.646) sits below the
**12-trial** annualised null bar of **0.702**.

### Null bars, on the honest clock

`n_eff = min(n_episodes, span × 252 / mean_hold)` — the span clock assumes an
always-invested book, and a blackout book with 9 episodes over 5.6 years has
made 9 bets, not 48. Median honest `n_eff` = **11.0** (span-clock median 48.5).

| | trials | E[max SR \| null], per-hold | annualised |
|---|---:|---:|---:|
| headline | 12 | 0.5020 | **0.7019** |
| full grid | 298 | 0.8724 | **1.2198** |
| grid + A5 | 304 | 0.8737 | **1.2225** |

**The best PRIMARY cell in the whole grid is 0.851 against an annualised bar of
1.220.** Nothing in the primary universe clears, at any cost level, before the
adversarial pass begins.

Exactly one cell of 298 clears: `S|SFR12|immM_2s5s10s|beta_lvl|const_dv01` at
**1.806**, on a *secondary* structure whose marks were flagged in advance. It is
adjudicated in §7.

---

## 6. The adversarial pass

**Always-short control** (same structure, leg and β, held through every
segment, signal off): 2 of the top 8 cells are *entirely* explained by the
static short position, and 2 more are majority-static.

**β = 0 control**: the fly adds Sharpe on **2 of the top 8** and *removes* it on
3. `S|SFR16|immF_2s5s10s` scores **0.715 with the fly and 0.926 without it**.

**Placebo ladder** — a timing signal must decay as the lag grows. At 9 episodes
the per-rung standard error is ~0.4, so read this as *does it fall below the
noise floor*, not rung by rung:

| cell | 0 bd | 10 | 20 | 40 | 60 |
|---|---:|---:|---:|---:|---:|
| `SFR12 × immM_2s5s10s` | 1.806 | 1.098 | 1.217 | 0.696 | **0.989** |
| `SFR16 × immM_2s5s10s` | 0.864 | 0.598 | 0.609 | 0.716 | **0.613** |
| `GREENS × le_10y10y_15y10y` | 0.851 | 0.263 | 0.368 | −0.022 | **−0.247** |

The ladder separates the two families cleanly. **The long-end curve cell dies;
the deferred-outright cells do not.** A rule whose P&L survives a 60-business-day
stale signal is a slow level effect wearing a timing rule.

**Residual half-life** of the traded spread, against a tradeable segment of a
median **56 business days**:

| cell | daily AR(1) | daily half-life | weekly half-life |
|---|---:|---:|---:|
| `SFR12 × immM_2s5s10s` | 0.922 | 8.5 d | 1.8 w |
| `SFR16 × immM_2s5s10s` | 0.949 | 13.3 d | 3.1 w |
| `GREENS × le_10y10y_15y10y` | **0.993** | **99.1 d** | 23.6 w |
| `GREENS × spot_2s5s10s` | 0.990 | **68.3 d** | 16.4 w |

**This is the structural finding of the block.** The long-end residual — the one
the brief's R² = 0.505 regression is about — reverts in 68–99 business days, and
the roll-flat window is 56. It *cannot converge inside one*, which is exactly
what the 67% `segment_end` exit share was saying.

---

## 7. Engine certification — and SFR12 is a mark, not a trade

`noise_fit` detects **i.i.d. (MA(1))** error only. SFR12's AC1 of −0.056
therefore means "no i.i.d. noise", **not** "clean marks" — and it is
structurally blind to a *multi-day dislocation*, which is what a deferred single
contract does around meeting repricings.

| structure | frac negative CA | frac implausible vol | **frac ok** | sd of dev from 10d EWMA | AC1(dev) | AC5(dev) | frac \|dev\| > 2bp |
|---|---:|---:|---:|---:|---:|---:|---:|
| **SFR12** | 8.7% | 3.1% | **0.882** | **4.05 bp** | **+0.863** | +0.446 | **38.3%** |
| SFR16 | 2.2% | 1.1% | 0.967 | 2.97 bp | +0.823 | +0.473 | 26.5% |
| GREENS | 0.8% | 0.7% | 0.985 | **0.56 bp** | +0.803 | +0.472 | **1.1%** |
| BLUES | 0.6% | 0.4% | 0.990 | 1.15 bp | +0.626 | +0.374 | 6.3% |
| GOLDS | 0.6% | 0.2% | 0.992 | 1.57 bp | +0.677 | +0.448 | 13.6% |

On **its own nine entry/exit dates**, SFR12's `frac_ok` is **0.667** — a third
of the dates it trades on are flagged. Both other finalists score **1.000**. An
8.5-day residual half-life is what a 4 bp multi-day dislocation snapping back
looks like.

### The engine

`QueryDrivenBacktest`, real SR3 contracts, a dated matched swap and an
IMM-pinned hedge leg, marked independently of the panel:

| finalist | episodes | engine terminal | panel terminal | gap | **daily-change corr** | engine SR | panel SR |
|---|---:|---:|---:|---:|---:|---:|---:|
| `SFR12 × immM_2s5s10s` | 9 | $6,605,723 | $6,378,629 | +3.6% | **+0.527** | **1.409** | 2.141 |
| `GREENS × le_10y10y_15y10y` | 9 | $683,336 | $781,413 | −12.6% | **+0.126** | **0.151** | 0.867 |
| `GOLDS × imm2_2s5s10s` | 6 | $1,000,459 | $1,514,308 | −33.9% | **+0.389** | **0.131** | 0.414 |

**The pre-registered bar is a daily-change correlation ≥ 0.99. None of the three
reaches it, and every one comes back lower on the engine.** The par-rate panel
prices rate *changes*; the engine prices struck instruments that age, and the
omitted term is carry. **The engine numbers are the numbers.** Two of the three
finalists are worth 0.13–0.15 on real instruments.

### The loose thread, closed

The declared shared-sign-flip null gave a family-wise **p = 0.0225** to
`A|GOLDS|imm2_2s5s10s|beta_lvl|inv_vol` (per-observation Sharpe 2.009). It was
not in the Sharpe-ranked top 8, so it was run through the full battery
separately: always-short/long ≈ ±$113k (not direction), placebo decays
0.398 → 0.263 → 0.089 (behaves like a signal), **n = 6 episodes**, engine
Sharpe **0.131**. It is a six-observation statistic that does not survive real
instruments.

---

## 8. A5 — the dated, hold-through-the-roll package

"Flat across the roll" was only ever a proxy for *do not book a
contract-switching jump as P&L*. A **dated** package — fixed SR3 contracts, a
fixed matched swap, an IMM-pinned fly, all resolved at entry — has no label to
switch, so it can be held straight through a roll and the 68–99 day half-life
has room to converge. Declared as amendment A5 before scoring (6 cells, trials
298 → 304). Signal on the causal forward-adjusted roll splice; **P&L on the
engine only**, because a constant-rank panel cannot represent a dated hold.

| structure | leg | episodes | crossing a roll | **engine net** | **engine SR** | spliced-panel SR |
|---|---|---:|---:|---:|---:|---:|
| GREENS | `immM_2s5s10s` | 7 | 4 | +$12,718 | +0.001 | −0.428 |
| GREENS | `le_10y10y_15y10y` | 5 | 3 | −$862,112 | −0.088 | −1.096 |
| BLUES | `immM_2s5s10s` | 7 | 6 | +$948,584 | +0.103 | −0.151 |
| BLUES | `le_10y10y_15y10y` | 6 | 4 | −$206,390 | −0.029 | −0.222 |
| GOLDS | `immM_2s5s10s` | 6 | 4 | +$1,969,621 | **+0.184** | −0.079 |
| GOLDS | `le_10y10y_15y10y` | 4 | 2 | −$1,537,708 | −0.207 | −0.445 |

**Best engine Sharpe 0.184 against a 304-trial annualised bar of 1.2225. Median
−0.014. Three of six positive.** The version of the brief's structure that
removes the roll constraint entirely is dead too.

---

## 9. Overlays C and D — positioning and the CME–LCH basis

Both verticals the brief names were measured rather than left silent.

**The overlays keep 0–1 of 6–9 episodes on every finalist.** An overlay that
keeps one episode cannot be distinguished from noise, and that — not the sign of
its P&L — is the reportable fact.

Citi's monthly positioning regression does **not** reproduce on the raw CA level
here (R² 0.000–0.034, |t| 0.06–1.51, and the level slope is negative for all
four structures against Citi's published positive). **This is a weaker test than
block 3's**, which regressed the model *residual* (`CA − model`) — Citi's own
LHS — and did reproduce, in BLUES only, at slope +5.28e−07, t = +2.59, R² 0.124.
The mechanism claim stands where block 3 left it; this block adds only that the
raw level does not carry it.

Data provenance, stated because two things share one name: dealer positioning is
CFTC TFF weekly, lagged 3 business days to publication; open interest is the
**whole-strip** aggregate, not per contract; the CCP basis is LCH minus CME, USD
SOFR, lagged 1 business day.

---

## 10. What this block establishes, beyond the verdict

1. **The sizing before/after table** (§2) — the direct answer to the objection,
   and the reason the fix is undefined.
2. **The mark-noise decomposition per structure** (§2), which says which
   structures are tradable at daily frequency at all, and the Kalman-derived
   denoising half-life that follows from it.
3. **The two roll clocks** (§4) and the union blackout they require.
4. **The theta identity** (§4), confirmed three independent ways. It reframes
   every CA mean-reversion result in the package: a constant-rank series is
   stationary because the roll pays back the decay, and any book that is flat
   across the roll is running a one-sided carry.
5. **The half-life-versus-window constraint** (§6) — the structural reason this
   family of trades cannot work in a roll-flat implementation.
6. **The multi-day dislocation diagnostic** (§7), which catches what an
   MA(1) noise model cannot, and which is the reason the grid's only bar-clearer
   is not a trade.
7. **The engine-vs-panel gap** (§7): a par-rate panel systematically overstates
   these books, by 1.5–6× in Sharpe. That caveat belongs on every panel-only
   number this package has published.

## 11. Reproduction

```
python notebooks/backtests/convexity_rv/_p2_build_panel.py        # ~36 min
python notebooks/backtests/convexity_rv/_p2_probe_roll_alignment.py
python notebooks/backtests/convexity_rv/_p2_measure_premise.py    # ~3 min
python notebooks/backtests/convexity_rv/_p2_run_grid.py           # ~2 min
python notebooks/backtests/convexity_rv/_p2_adversarial.py        # ~4 min
python notebooks/backtests/convexity_rv/_p2_certify.py            # ~2 min
python notebooks/backtests/convexity_rv/_p2_a5_dated.py           # ~4 min
python notebooks/backtests/convexity_rv/_p2_overlays.py           # ~1 min
python notebooks/backtests/_py2nb.py gv_ca_vs_imm_fly.py
jupyter nbconvert --to notebook --execute --inplace gv_ca_vs_imm_fly.ipynb
python notebooks/backtests/_verify_nb.py gv_ca_vs_imm_fly.ipynb
```

The CA panel is carried forward from block 3's `_cavf_backfill_ca.py` and
re-priced rather than assumed. Both panels are gitignored and regenerable.

Suites: `tests/test_convexity_rv_gv_{universe,sizing,signals,grid,engine}.py`.
Mutation harness `_p2_mutate_gv.py` plants 22 defects one at a time — **22
KILLED, anchors matched 22/22, restored tree re-runs green**. One mutant
(`vega-uses-uncontrolled-fit`) SURVIVED the first run and is now covered by a
test that asserts the *rule*, not just the primitive.

Notebook: `notebooks/backtests/convexity_rv/gv_ca_vs_imm_fly.ipynb` —
28 code cells, **0 unrun, 0 errors**.
