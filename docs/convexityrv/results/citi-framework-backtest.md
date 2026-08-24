# CITI — the published convexity trade, backtested in its own framework

**Verdict: DEAD — a small-sample gross edge on the trades it selects, killed by
its own execution costs, on a book too sparse to run. The most useful part of
the answer is WHY the rule almost never fires at all.**

Pre-registration: `docs/convexityrv/citi-framework-preregistration.md`, frozen
and committed **before any P&L was computed** (commit `b539df62`). Notebook:
`notebooks/backtests/convexity_rv/citi_framework_backtest.ipynb`, executed at
0 unrun / 0 errors. Block 5 of the convexity RV programme.

---

## The headline

| | |
|---|---|
| declared cells | **23** (16 primary, 2 secondary, 5 diagnostic), one headline |
| window | 2021-01-04 .. 2026-08-21, 1,409 CA dates |
| **tradeable** span | **4.682 y**, from 2021-12-15 |
| **the headline cell** | 2 episodes in 4.7 years, net **−$1,189,942** |
| **annualised clock** — cells clearing `E[max SR \| null]` = **0.9066** at 23 trials | **0 of 23 gross, 0 of 23 net** |
| **per-hold clock** — cells clearing their own `emax_perhold` at their own `n_eff` | **8 of 23 GROSS, 0 of 23 NET** |
| best NET annualised Sharpe on the panel | **+0.2020** (`S\|z1.0\|screen_best_all5\|citi_2017`) |
| best NET annualised Sharpe on the **engine** | **+0.1657** (same cell) |
| best per-hold Sharpe, gross / net | **+1.3346 / +0.6362** (`P\|z1.0\|screen_best\|fitted_refit`, 4 trades, bar 0.9808) |
| shared-sign-flip p on NET per-episode P&L, best of 23 | **0.161** |

**Read the two clocks together, because apart they say different things and
both are true.**

* On the **annualised** clock — the equity curve an investor would actually
  hold — nothing clears at any cost level, and it cannot: four trades in
  4.7 years is not a book.
* On the **per-hold** clock — the quality of the trades that were *taken* —
  eight cells clear their own bar **gross**, the best at 1.33 against 0.98.
  **Costs kill every one of them**: 0 of 23 clear net, and no cell's
  shared-sign-flip p on net per-episode P&L is below 0.16.

So the framework is not *nothing* on the trades it selects. It is a
small-sample gross edge that does not survive its own execution costs, on a
book too sparse to run — and the honest headline is the conjunction of those
three facts, not any one of them.

The pre-registration required both clocks (§6, §11); the grid runner initially
graded only the annualised one and the per-hold grading is amendment A1,
computed after the grid ran and before this verdict was written.

---

## 1. The rule as published does not trade

Citi's entry is a conjunction of five conditions. Each threshold in this
backtest is the note's own printed value. On USD SOFR, over 1,409 dates and the
three tradeable colour packs, **all five hold on 2 dates**.

| pack | wide_to_model | wide_to_fly | positive_roll | implied_rich | positioning | **all five** |
|---|---:|---:|---:|---:|---:|---:|
| GREENS | 0.0248 | 0.0199 | 0.9986 | 0.1923 | 0.3534 | **0.0007** |
| BLUES | 0.0234 | 0.0234 | 0.9986 | 0.2697 | 0.3534 | **0.0007** |
| GOLDS | 0.0284 | 0.0546 | 0.9986 | 0.2229 | 0.3534 | **0.0000** |

Nested, one condition at a time (days surviving):

| pack | wide_to_model | + wide_to_fly | + positive_roll | + implied_rich | + positioning |
|---|---:|---:|---:|---:|---:|
| GREENS | 35 | 6 | 6 | 2 | 1 |
| BLUES | 33 | 2 | 2 | 1 | 1 |
| GOLDS | 40 | 0 | 0 | 0 | 0 |

### Why: three of the note's five conditions are mutually antagonistic here

The pairwise **lift** — the observed joint pass rate divided by the rate under
independence — on BLUES:

| | wide_to_model | wide_to_fly | implied_rich | positioning |
|---|---:|---:|---:|---:|
| **wide_to_model** | — | **2.59** | **0.34** | **0.43** |
| **wide_to_fly** | 2.59 | — | 0.90 | 1.03 |
| **implied_rich** | 0.34 | 0.90 | — | 1.01 |
| **positioning** | 0.43 | 1.03 | 1.01 | — |

* `wide_to_model × implied_rich = 0.34`. A CA that is unusually wide to the
  Ho-Lee model tends to occur when **realised** vol has been high — so
  implied/realised is *low* at exactly the moment the model calls the
  adjustment rich. The note treats these as two readings of the same thing;
  they are two readings of different denominators.
* `wide_to_model × positioning_stretched = 0.43`. **The note's own causal chain
  does not reproduce on SOFR.** Its mechanism is: clients short futures →
  dealers long → dealers hedge by paying swaps → structurally short CA → wider
  CA. Measured here, `corr(BLUES CA-vs-model, dealer-net 1Y z) = −0.187`, and
  the widest dislocations sit in the *low* dealer-position bucket
  (mean CA-vs-model +3.64 bp at z ∈ (−1, 0] against +1.64 bp at z ∈ (0, +1]).
  The dealer-takes-the-other-side identity does hold
  (`corr(dealer, AM+leveraged) = −0.985`); it is the step *after* it — that the
  size of the dealer position moves the adjustment — that does not.
* `wide_to_model × wide_to_fly = 2.59`. Better than independence, but the two
  "wideness" measures pass 2.3% of days each and only **0.14%** jointly. The
  Ho-Lee model level and the fitted 2s5s10s fly are nearly orthogonal
  descriptions of the same adjustment.

**This is the block's most transferable finding.** A conjunction reads, in
prose, as one signal with several confirmations. Measured, it was three
signals that rarely agree, and it is the reason a published rule with two
tradeable days in five years is not a coding error.

---

## 2. The threshold ladder, and what happens when the rule can trade

A rule with two entry days cannot be graded, so the pre-registration declared
**two rungs** — the note's own 2.0σ and a widened 1.0σ — and printed the rungs
it does not walk. Days on which some primary structure passes all five:

| z on both wideness gates ↓ / impl-rlzd floor → | 1.3 (the note's) | 1.0 | dropped |
|---|---:|---:|---:|
| **2.0 (the note's)** | **2** | 2 | 2 |
| 1.5 *(not scored)* | 2 | 4 | 4 |
| **1.0** | **11** | 18 | 20 |
| 0.5 *(not scored)* | 30 | 59 | 84 |
| 0.0 *(not scored)* | 51 | 108 | 161 |

At 1.0σ the framework trades 4–5 times per cell (22–23 for the all-five-colour
secondary). Annualised clock:

| cell | n | gross SR | net SR (1×) | net SR (2×) | break-even bp | carry share |
|---|---:|---:|---:|---:|---:|---:|
| `P\|z1.0\|screen_best\|fitted_refit` | 4 | 0.2989 | 0.1226 | −0.0271 | 0.709 | 0.085 |
| `P\|z1.0\|screen_best\|fitted_frozen` | 4 | 0.2797 | 0.1178 | −0.0221 | 0.716 | 0.086 |
| `P\|z1.0\|screen_best\|citi_2017` | 5 | −0.1856 | −0.4622 | −0.6925 | −0.274 | −0.278 |
| `P\|z1.0\|screen_best\|unhedged` | 4 | 0.2079 | 0.1033 | 0.0034 | 0.763 | 0.332 |
| `S\|z1.0\|screen_best_all5\|citi_2017` | 22 | 0.4155 | 0.2020 | −0.0049 | 0.754 | 0.029 |

Every one of them is below **0.9066**, and every one except the unhedged cell
is negative at 2× costs.

### The per-hold clock — the same cells, graded on the trades they took

`mean / sd` over the **episodes**, against `E[max SR | null]` at 23 trials with
`σ = 1/sqrt(n_eff)` and `n_eff = min(n_episodes, span·252/mean_hold)`. Every
cell that clears its bar gross:

| cell | n | per-hold SR gross | per-hold SR net | bar | sign-flip p (gross) | sign-flip p (net) |
|---|---:|---:|---:|---:|---:|---:|
| `P\|z1.0\|screen_best\|fitted_refit` | 4 | **1.3346** | 0.6362 | 0.9808 | 0.062 | 0.191 |
| `P\|z1.0\|screen_best\|fitted_frozen` | 4 | **1.3212** | 0.6439 | 0.9808 | 0.065 | 0.190 |
| `D\|z1.0\|drop_positive_roll` | 4 | **1.3346** | 0.6362 | 0.9808 | 0.063 | 0.191 |
| `D\|z1.0\|drop_positioning_stretched` | 4 | **1.2183** | 0.2804 | 0.9808 | 0.064 | 0.378 |
| `P\|z1.0\|screen_best\|unhedged` | 4 | **1.0712** | 0.5448 | 0.9808 | 0.063 | 0.186 |
| `D\|z1.0\|drop_implied_rich` | 8 | **0.9240** | 0.3505 | 0.6935 | 0.012 | 0.199 |
| `D\|z1.0\|drop_wide_to_fly` | 7 | **0.7820** | 0.1510 | 0.7414 | 0.039 | 0.354 |
| `S\|z1.0\|screen_best_all5\|citi_2017` | 22 | **0.4429** | 0.2194 | 0.4182 | 0.023 | 0.161 |

**8 of 23 clear gross; 0 of 23 clear net.** The gap between the two Sharpe
columns is the declared cost model doing its job, and the gap between the two
p-columns says the same thing: gross, five cells sit under p = 0.07 on their
own sign-flip null (before any family adjustment for 23 trials); net, the best
p in the whole block is 0.161.

Two cautions the numbers demand. First, a per-hold Sharpe on **four**
observations has enormous estimation error — its own null sd is 0.5, which is
why the bar is 0.98. Second, three of the eight are drop-one *diagnostics*, and
`drop_positive_roll` is byte-identical to the headline construction because the
positive-roll condition passes on 99.9% of dates and so removes nothing. That
leaves the real content: the `screen_best` z=1.0 family, at four trades.

---

## 3. The headline trade, in detail

`P|z2.0|screen_best|fitted_refit` — screen-selected structure, fly-constrained
fit re-struck at each roll, five-way conjunction at the note's own thresholds,
+$600k / −$350k on $200k DV01, short only, held through rolls.

| structure | entry fill | exit fill | hold | β at entry | exit | z model | z fly | rich bp | impl/rlzd | gross |
|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| BLUES | 2023-03-16 | 2023-03-20 | 2 bd | −0.033 | **stop** | 3.91 | 2.67 | 10.37 | 1.40 | **−$880,773** |
| GREENS | 2026-08-10 | 2026-08-21 | 9 bd | +0.045 | end of sample | 2.37 | 2.09 | 0.94 | 1.37 | +$6,443 |

The first entry is the March-2023 regional-bank week. The Blues CA was 10.4 bp
rich to its own fitted fly and 3.9σ wide to the Ho-Lee model — **exactly the
setup the note describes, and by a wider margin than the note's own +4 bp / 2σ
entry** — and it widened further. The stop did its job and the trade lost
$880,773 in two business days. That is not an argument against the stop; it is
the observation that the one time in five years this rule found its own setup,
the setup was a liquidity event and the mean reversion was on the other side of
it.

---

## 4. Engine certification

Nine books re-priced through `QueryDrivenBacktest` on dated instruments — four
SR3 contracts, a matched-maturity quarterly/quarterly swap, and a spot 2s5s10s
fly at the fitted weights re-struck at each quarterly refit inside the hold —
with `assert_ran` on every one.

| cell | n | closed | panel gross | engine gross | ratio | panel SR net | **engine SR net** | daily corr |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `P\|z2.0\|screen_best\|fitted_refit` | 2 | 12 | −874,329 | −537,513 | 0.61 | −0.5177 | **−0.1701** | 0.880 |
| `P\|z2.0\|blues\|fitted_refit` | 1 | 6 | −880,773 | −931,144 | 1.06 | — | — | 0.926 |
| `P\|z1.0\|screen_best\|fitted_refit` | 4 | 25 | 1,322,847 | 1,300,079 | 0.98 | 0.1226 | **0.0681** | 0.811 |
| `P\|z1.0\|screen_best\|fitted_frozen` | 4 | 24 | 1,313,159 | 1,283,278 | 0.98 | 0.1178 | **0.0652** | 0.824 |
| `P\|z1.0\|screen_best\|citi_2017` | 5 | 30 | −653,422 | **+886,154** | **−1.36** | −0.4622 | **−0.0067** | 0.682 |
| `P\|z1.0\|screen_best\|unhedged` | 4 | 20 | 1,221,105 | 939,305 | 0.77 | 0.1033 | **0.0285** | 0.510 |
| `P\|z1.0\|blues\|fitted_refit` | 4 | 25 | 1,142,551 | 1,025,236 | 0.90 | 0.0871 | **0.0368** | 0.776 |
| `S\|z1.0\|screen_best_all5\|fitted_refit` | 23 | 143 | 5,034,542 | 4,397,958 | 0.87 | 0.0814 | **0.0406** | 0.816 |
| `S\|z1.0\|screen_best_all5\|citi_2017` | 22 | 138 | 7,012,312 | 6,907,091 | 0.98 | 0.2020 | **0.1657** | 0.802 |

**The engine is the quoted number and it is worse than the panel on eight of
nine books.** On one — `citi_2017` — the two disagree on the *sign* of the
gross P&L (ratio −1.36), which is the largest panel/engine divergence this
package has recorded and belongs beside the earlier finding that a par-rate
panel overstated three hedged Sharpes by 1.5–6×. The daily-change correlation
runs 0.51–0.93; it does not reach 0.99 and the design says why, because a
par-rate panel prices par-rate changes while the engine prices struck
instruments that age and the omitted term is carry.

---

## 5. The control battery

### Same-day fills — the mark-noise harvest

Every one of the six cells is worth **$1.88m to $17.76m MORE** filled at the
mark its own signal was computed from. That gap is the reason `exec_lag_bd = 1`
is the convention: the CA mark is a composite of a futures bar and a
separately-timed swap curve, and a rule that shorts a rich mark *at* that mark
banks a reversion nobody can trade.

### Placebo ladder — the edge that exists behaves like timing

| cell | lag 0 | 10 | 20 | 40 | 60 |
|---|---:|---:|---:|---:|---:|
| `P\|z1.0\|screen_best\|fitted_refit` | 0.2989 | 0.2389 | −0.1777 | −0.1645 | −0.3938 |
| `P\|z1.0\|blues\|fitted_refit` | 0.2516 | 0.2273 | −0.2148 | −0.1818 | −0.3792 |
| `P\|z1.0\|screen_best\|unhedged` | 0.2079 | 0.0746 | −0.0877 | −0.1635 | −0.2340 |
| `S\|z1.0\|screen_best_all5\|citi_2017` | 0.4155 | −0.2636 | −0.0261 | −0.0118 | 0.2764 |

Every cell that makes money unlagged is negative by 40 bd of lag. So the small
edge that is there is genuinely about *when* rather than a slow level effect —
it is just an order of magnitude below the bar.

### Always-short — what the trade IS when it works

The signal switched off, the same structures, the same hold length: the static
short earns **−$3,506 to +$149,112 per trade**, positive on **15 of 16**
(cell, structure) pairs. A short-convexity book collects the CA's theta whether
or not a signal fired. The signal's own per-trade contribution is positive on
4 of 6 cells, on four trades each — and negative on the headline, which is the
same statement as "the two trades it took lost money".

### β = 0 — the fly leg

| cell | Sharpe hedged | Sharpe β=0 | hedge adds |
|---|---:|---:|---:|
| `P\|z2.0\|screen_best\|fitted_refit` | −0.3859 | −0.3738 | −0.0121 |
| `P\|z1.0\|screen_best\|fitted_refit` | 0.2989 | 0.2079 | **+0.0911** |
| `P\|z1.0\|screen_best\|citi_2017` | −0.1856 | 0.2079 | **−0.3935** |
| `P\|z1.0\|blues\|fitted_refit` | 0.2516 | 0.1764 | **+0.0752** |
| `S\|z1.0\|screen_best_all5\|citi_2017` | 0.4155 | 0.4227 | −0.0072 |

The fly adds Sharpe on two of five and removes it on three. **Citi's own
published 0.705/−1/0.465 weights are the worst of them**, at −0.39 of Sharpe
against the same book with the hedge simply removed.

### The splice control

The raw constant-rank CA carries **+0.946 bp per roll** on BLUES (22 rolls) and
the spliced series carries exactly 0.0. Running the P&L on the raw series
instead costs the all-five-colour book $4.19m of gross — and it would be an
artifact, because a dated position has no label to switch.

### Sign-flip null

20,000 shared sign flips on the per-episode P&L (a row permutation leaves a
Sharpe unchanged):

| cell | n | t | p one-sided | p two-sided |
|---|---:|---:|---:|---:|
| `P\|z1.0\|screen_best\|fitted_refit` | 4 | 2.669 | 0.061 | 0.123 |
| `P\|z1.0\|screen_best\|unhedged` | 4 | 2.142 | 0.063 | 0.127 |
| `S\|z1.0\|screen_best_all5\|citi_2017` | 22 | 2.077 | **0.024** | 0.050 |

**The loose thread, recorded rather than promoted.** The all-five-colour
secondary cell reads p = 0.024 one-sided on a per-trade clock. It is 16 of 22
WHITES episodes on marks whose daily-change AC1 is −0.540 — at or past the
pure-noise bound — its per-episode P&L runs ±$2m on a $200k DV01 book (i.e.
±5–10 bp moves on a structure whose whole level is under 1 bp), and its Sharpe
is still under a quarter of the bar. It is exactly the adverse selection the
pre-registration named when it put WHITES and REDS outside the primary
universe, and it is in the record because a sub-5% p-value left unexamined is
the kind of loose thread this package keeps writing down.

### Convexity signature

The CA is exactly quadratic in σ, so "this is a convexity trade" has a number
attached: the fitted quadratic coefficient must equal `CA_DV01·w/2e4` USD per
(bp/yr)². The fitted coefficients run **9–51× the prediction with the wrong
sign half the time**. At 4–22 episodes this is a three-parameter regression on a
handful of points and cannot confirm or deny the claim. The honest reading is
that the book never got large enough to have a convexity signature to test.

### Sub-period and sensitivities

The z=1.0 books are positive in both halves of the sample (split 2023-10-26).
`max_hold_bd ∈ {63, 126, 189}` changes nothing — every episode exits on target
or at the end of the sample well inside 63 bd. `fit_window_bd = 252` flips the
book's sign (+0.0692 gross against +0.2989 at 504); `= 756` halves it.
Splicing the signal as well as the P&L drops the book from 4 episodes to 2.

---

## 6. What else was measured

### Citi's fair value is not stable enough to hedge with on this window

Fly-constrained 3-rate fit, refit at each of 21 CA rolls, 504 bd trailing
window:

| pack | refits | w2 median | w2 range | b median | **b sign flips** | w2 at a grid boundary | OOS resid sd |
|---|---:|---:|---:|---:|---:|---:|---:|
| GREENS | 21 | 0.31 | 0.90 | −8.95 | **4** | 11 / 21 | 2.350 bp |
| BLUES | 21 | 0.70 | 0.90 | +12.42 | **4** | 9 / 21 | 4.537 bp |
| GOLDS | 21 | 0.34 | 0.90 | +31.20 | **2** | 6 / 21 | 7.280 bp |

On the reproduction's narrower window (2022 start) BLUES has **one** sign flip
and a residual sd of 2.232 bp. Adding 2021 doubles both. The window was not
narrowed to make this look better; the instability is the result. A hedge ratio
whose *sign* changes inside its own sample cannot be hedged with, however well
it fits on average — the hedge would have to be turned upside down mid-trade,
and nothing in the fit says in advance which side of the flip it is on.

### The screen reproduces, and its roll column agrees three ways

`CA − Model − VsModel = 0` exactly (10 of 7,045 cells skipped for a missing vol
mark); `implied²·w/2e4 − CA = 7.1e-15` (997 skipped: a non-positive CA has no
real implied vol). The `3m Roll` column agrees with the term-structure form
`[CA(p) − CA(p one year nearer)]/4` at a ratio of 0.78–0.92 for
GREENS/BLUES/GOLDS, and with the **measured IMM-roll jump** at 1.045 / 1.024 /
1.111. Three independent estimates of the same quantity, and the two structures
that disagree (WHITES 4.31, REDS −0.73) are the noise-dominated ones.

### Maintaining the hedge changes almost nothing

`fitted_refit` against `fitted_frozen` at z = 1.0: gross $1,322,847 against
$1,313,159, net $589,525 against $595,614. The re-strikes cost more than they
earn, by a hair. The mid-2023 sign reversal of `b` — the finding that motivated
this comparison — does **not** destroy the book, because the book is barely
hedged: mean |β| runs 0.039–0.18 against Citi's printed 0.206.

### The carried panels were certified before anything was built on them

CA panel re-price: **max |diff| 0.00000000 bp** over 30 cells. Leg panel: every
one of 13 columns exact on **1,409 of 1,409 dates**.

**A data-layer finding worth carrying forward.** The first sample said the spot
2y/5y/10y were off by up to **1.21 bp**. They are not. The difference was the
*request shape*: the sample was pulled as one 940-day `IRSwapsTB` span, the
panel and the re-pull year-chunked. A single multi-year span request returns
different par rates for the same dates than the year-chunked request does. Every
panel build in this package is year-chunked; that is now a stated convention
rather than an accident, and it is a live hazard for any code that widens a
request to "save a round trip".

---

## 7. The bar, and the caveat

`E[max SR | null]` at the declared trial count, tradeable span 4.682 y:

| trials | per-hold | annualised |
|---|---:|---:|
| 2 | 0.2599 | 0.2402 |
| 16 (primary only) | 0.9002 | 0.8321 |
| **23 (declared)** | **0.9808** | **0.9066** |
| for reference, block 4 at 298 trials / 5.626 y | 1.1812 | 1.2199 |

The annualised bar is computed against the **tradeable** span, not the 5.626 y
panel span: a book that cannot open until its fair value and its z-scores exist
has not been running for the whole panel. The per-hold bar in the table above
is at `n_eff = 6`; each cell is graded at **its own** `n_eff`, which for the
four-trade cells is 4 and gives a bar of 0.9808.

**Which clock a number lives on is part of the number.** An annualised daily
Sharpe and a per-hold Sharpe are not two estimates of one quantity, and each has
its own null: `σ = 1/sqrt(span_years)` for the first, `1/sqrt(n_eff)` for the
second. Grading either against the other's bar is the "which column is the claim
true in" error, and it is why this block reports both and quotes neither alone.
On the annualised clock the best engine-certified book is +0.166 against 0.907;
on the per-hold clock the best *gross* book is +1.335 against 0.981 and the best
*net* book is +0.644 against the same 0.981.

**Standing caveat.** This is the fifth pass over the same CA panel (block 1
`strat2`, block 3 `cavf`/PR #492, block 4 `gv`/PR #496, the reproduction/PR
#499, now this). The 23-trial bar is the honest one for the cells scored here,
but the *structure* being tested was chosen after four prior searches over the
same data, and no single-rule null bar can undo that.

---

## 8. What this block adds to the programme

0. **The two clocks disagree and the disagreement is the result.** Eight of 23
   cells clear their own per-hold null bar **gross** and none clears it **net**;
   none clears the annualised bar at any cost level. The framework selects
   trades that are better than chance and cannot pay for them, on a book too
   sparse to run. A one-line verdict that quotes only one of those clocks is
   wrong whichever one it picks.
1. **Citi's published rule does not trade on SOFR**, and the reason is inside
   the rule rather than in the data: three of its five entry conditions are
   mutually antagonistic here, with the two that the note treats as saying the
   same thing passing 2.3% of days each and 0.14% jointly.
2. **The note's positioning mechanism does not reproduce.** Dealers do take the
   other side (corr −0.985), but the size of the dealer position goes with a
   *narrower* adjustment on SOFR (corr −0.187), not a wider one.
3. **The published hedge is the worst of the four schemes tested**, and it is
   worse than no hedge at all by 0.39 of Sharpe.
4. **A short-CA book is a carry trade before it is anything else.** The static
   short is profitable on 15 of 16 (cell, structure) pairs with the signal
   switched off, up to $149k per trade; the declared carry share of the 14
   cells with a positive gross runs 0.03–0.40 (median 0.11), the outlier being
   a cell whose whole gross is $15,748.
5. **The roll splice belongs in the P&L and not in the signal** — a distinction
   that was measured, not assumed, and that would have quietly killed the
   signal for the wrong reason (median 1Y z −1.15 to −1.31 instead of −0.20 to
   −0.53).
6. **A single multi-year `IRSwapsTB` span request does not return the same par
   rates as the year-chunked request.**

Block 4's verdict — CA-vs-fly is dead as a systematic strategy — stands. This
block adds the reason the *published* version of it does not rescue the idea.

---

## Artifacts

```
docs/convexityrv/citi-framework-preregistration.md      the frozen contract
docs/convexityrv/results/citi-framework-backtest.md     this file
RVUtils/ConvexityRV/citi_fv.py       the Figure-6 fair value, 3 fits, IMM refit
RVUtils/ConvexityRV/citi_screen.py   Figure 20 on every date, and its identities
RVUtils/ConvexityRV/citi_rule.py     the conjunction, the target/stop, the cells
RVUtils/ConvexityRV/citi_engine.py   fitted-weight flies, per-segment tags
tests/test_convexity_rv_citi_{fv,screen,rule,engine}.py
notebooks/backtests/convexity_rv/
  _p4_certify_inputs.py     re-price the carried panels          (~3 min)
  _p4_leg_vintage_diff.py   the request-shape finding            (~10 min)
  _p4_build_panel.py        p4_citi.parquet, 1,409 x 82          (~7 min)
  _p4_tieout_repro.py       citi_fv against the reproduction     (~1 min)
  _p4_preflight.py          everything measured before the freeze
  _p4_conjunction_probe.py  why the conjunction never fires
  _p4_run_grid.py           the 23 declared cells                (~16 s)
  _p4_engine.py             engine certification                 (~3 min)
  _p4_controls.py           the control battery
  _p4_mutate_citi.py        38-mutant harness
  citi_framework_backtest.py / .ipynb   executed, 0 unrun / 0 errors
```

Panels in `notebooks/data/convexity_rv/` are **gitignored and regenerable**.
