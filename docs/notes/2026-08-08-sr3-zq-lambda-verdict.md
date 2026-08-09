# Verdict: the SR3 copula-coordinate (λ) butterfly

One page. The bar below is quoted from
`docs/plans/2026-08-08-sr3-zq-lambda-preregistration.md`, committed at `912cf490` — before
any backtest ran.

## The call

**At the pre-registered gates: NO SIGNAL — a data-sufficiency result.**
**At relaxed gates, where it does trade: DEAD, and worse than noise.**

Two runs, and they say different things, so both are reported.

### Run 1 — pre-registered gates

The strategy never traded, for a reason that has nothing to do with whether λ predicts
anything.

```
signal availability: 93 rows, 10 admissible, 0 with a z-score, 0 beyond |z| >= 1.0
NO Z-SCORE ANYWHERE. The trailing window needs 30 admissible observations and the
largest contract supplies 10.
```

That is the honest headline and it is deliberately **not** written as DEAD. "The signal fired
and lost money" and "the signal never fired because the density could not be fitted well
enough often enough" are different findings, and reporting the second as the first would claim
evidence that was never gathered.

## Against the pre-registered bar

| # | Criterion | Threshold | Result |
|---|---|---|---|
| 1 | Trade count | ≥ 25 | **0** |
| 2 | Net bp/trade, half tick | > 0 | n/a |
| 3 | Net bp/trade, full tick | > 0 | n/a |
| 4 | Deflated Sharpe probability | > 0.5 | n/a |
| 5 | Median per-trade net | ≥ 0 | n/a |
| 6 | Independent meeting cycles | ≥ 6 | **0** |

Criteria 2–5 are not merely failed, they are **unmeasured**, and the difference matters.

### Run 2 — exploratory, gates relaxed until it trades

Labelled EXPLORATORY by the runner and barred from an ALIVE verdict by construction
(`--z-window 8 --z-min-obs 4 --max-fwd-resid-bp 3.0 --max-atom-spread 1.5`). This exists to
answer the one question run 1 cannot: **when the signal does fire, does it point the right
way?**

```
signal availability: 93 rows, 44 admissible, 40 with a z-score, 19 beyond |z| >= 1.0
trades 7   round trip cost 1.00bp (half tick) / 2.00bp (full tick)
gross bp/trade   mean -0.214   median -0.250   sd 0.585
net   bp/trade   mean -1.214   median -1.250
daily $ P&L: ann Sharpe -3.92   NW t -2.40
break-even cost multiple: 0.00x the half-tick round trip
```

**It does not.** The edge is negative *gross*, before a single basis point of cost — so this is
not the usual "real edge, eaten by costs" outcome that most SR3 RV programmes in this repo have
produced. There is nothing for costs to eat.

Kill criterion 2 (shuffle placebo) fails outright and is the most informative line in the whole
study:

```
shuffled gross bp/trade: mean +0.188  p90 +0.374  max +0.594   LIVE -0.214
live beats 10% of shuffles   (FAIL)
```

Randomly permuting λ across dates — same trade calendar, same costs, same fit quality, no
information — produces a *better* result than the real λ, 90% of the time. And the confound
regression finds no relationship to lean on either: per-trade net on `lambda_z` gives
β = +0.056, t = +0.51.

**Sample honesty: 7 trades, 5 meeting cycles, one contract.** That is far too small to
*conclude* the sign is negative. What it rules out is the opposite claim: on the only sample
where this signal has been made to trade at all, there is no evidence in its favour and the
point estimate is on the wrong side of zero and of the noise distribution.

## Why it did not trade: the fit gate, not the idea

Of 93 sessions on SFRZ26 (2026-03-26 → 2026-08-07):

| stage | sessions | note |
|---|---|---|
| extracted | 93 | 0 SABR model densities — the Part A fix holds |
| λ computable | 65 | the rest fail the ≥2 unit-weight-meeting structure |
| clears the fit gate | 19 (29%) | \|fwd resid\| < 1bp, pre-norm ≤ 1.02, ghost ≤ 5% |
| **also cross-strike coherent** | **10 (11%)** | atom spread ≤ 0.60 |
| enough to standardise | 0 | needs 30 in a trailing window |

**The binding constraint on this programme is the quality of the vol-space Breeden-Litzenberger
fit on an SR3 chain, not the economics of the copula.** Roughly one session in nine produces a
density that is both well-fitted and internally coherent enough to read a coupling off. That is
the number to attack if this is taken further.

## What was established anyway, and it is not nothing

Three results survive independently of the backtest, because they are measurements rather than
P&L (details and reproduction in the measurement note):

1. **The variance route is dead, and more decisively than predicted.** Not just a ±0.65-per-10bp/yr
   error bar — the observed RND variance exceeds the comonotone bound on **100%** of admissible
   sessions *at zero assumed non-meeting variance*. Bringing λ_var on scale needs ~66bp/yr of
   non-meeting vol against a total ATM vol of ~70. λ is a shape statistic or it is nothing.
2. **λ_wing = 0.54 was not a cherry-picked session.** It sits at the 37th percentile of the
   admissible sample. But λ_wing never goes near the independent null either — minimum +0.32 over
   19 sessions — so the market prices materially comonotone Fed behaviour essentially always.
   A trade that waits for λ to reach 0 will wait forever; the tradeable object is deviation from
   ~0.6, which is what the z-score encodes.
3. **The 50bp kill test passes, for the reason the design anticipated.** Allowing 50bp outcomes
   moves λ down by 0.14 at a 25% size mix — comparable to its entire cross-session standard
   deviation of 0.140 — so the *level* is contaminated. But rank ordering survives at corr 0.993.
   Entry was pre-registered on the standardised z rather than the level precisely so that this
   contamination would be survivable, and it is.

## Standing, un-run

- **Q3, the strongest claim in the original thesis** — that the modes stay pinned while the
  forward translates — is still unanswered. SFRZ26 alone supplies 7 bimodal admissible sessions
  against a floor of 10. The regression is implemented and includes the control the original
  framing omitted: the atom pins are ZQ-anchored, so a flat mode-vs-forward β proves nothing
  unless the pins themselves move with the forward. The multi-contract panel needed for it is
  still building.
- **Term structure of λ** across contracts on the same date: implemented, needs the same panel.
- **Dispersion** (SR3 straddle vs a vega-matched ZQ/SR1 straddle basket): not attempted. The
  binding constraint is known and structural — `covering_zq_months(SR3Z26)` = ZQZ26 at 0.516,
  ZQF27 and ZQG27 at 1.0, ZQH27 at 0.516 — so the IMM-vs-calendar stub is carried, and the
  constituent option leg is thin.

## Recommendation

**MONITOR — and after run 2, more weakly than the pre-registration expected.** The prior said
this would most likely land as a position-sizing and framing tool rather than standalone alpha.
It has landed lower than that: on the one sample where the strategy could be made to trade, the
gross edge is negative and a shuffled λ beats the real one nine times in ten. That is not proof
of a negative edge at n=7, but it is the absence of any positive one.

What survives is the measurement, not the trade. λ makes a
bimodal-Fed thesis falsifiable on a continuous scale, which it was not before: a discretionary
view that "the Fed either goes or it doesn't" is now a number with bounds attached and a
disagreement diagnostic when the surface stops being self-consistent. That is worth having on
the daily screen (`TradeFlagKind.LAMBDA_DEPENDENCE`), together with the free HARD-tier check
(`LAMBDA_ARBITRAGE`) for the rare session where the RND variance leaves the interval entirely.

What it is **not**, on this evidence, is a standalone systematic strategy — and the reason is
prosaic and fixable in principle: the density is only cleanly measurable about one session in
nine. Fix the fit yield and the question becomes answerable. Until then, the lockout stands
unburned: no capital has been committed and no claim has been made that the data supports.
