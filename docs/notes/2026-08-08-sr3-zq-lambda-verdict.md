# Verdict: the SR3 copula-coordinate (λ) butterfly

One page. The bar below is quoted from
`docs/plans/2026-08-08-sr3-zq-lambda-preregistration.md`, committed at `912cf490` — before
any backtest ran.

## The call

**At the pre-registered gates: NO SIGNAL — a data-sufficiency result.**
**At relaxed gates, where it does trade: DEAD. No gross edge; the net is the cost.**

Headline P&L, guarded multi-contract panel, 1-lot fly, 7 trades:
**gross −$19, net −$194 at the half tick, −$369 at a full tick.**

Two runs, and they say different things, so both are reported.

### Run 1 — pre-registered gates

The strategy never traded, for a reason that has nothing to do with whether λ predicts
anything.

```
NO Z-SCORE ANYWHERE. The trailing window needs 30 admissible observations and the
largest contract supplies 7. This is a DATA-SUFFICIENCY outcome, not evidence
about the edge.
```

(555 sessions across 5 contracts; 8 clear both the fit gate and the cross-strike gate, 7 of
them on one contract.)

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

Measured on the **guarded multi-contract panel** (555 sessions, 5 contracts). 1bp of package on
a 1-lot fly is $25.

```
signal availability: 555 rows, 48 admissible, 33 with a z-score, 12 beyond |z| >= 1.0
trades 7   round trip cost 1.00bp (half tick) / 2.00bp (full tick)
gross bp/trade   mean -0.107   median +0.500   sd 1.994
net   bp/trade   mean -1.107   median -0.500
net@fulltick     mean -2.107   median -1.500
daily $ P&L: n 302   ann Sharpe -1.37   NW t -2.31
DSR: sr -0.555   prob 0.006
break-even cost multiple: 0.00x the half-tick round trip
independent meeting cycles: 6
```

| | bp/trade | $/trade | total (7 trades) |
|---|---|---|---|
| Gross | −0.107 | −$2.68 | **−$19** |
| Net @ half tick | −1.107 | −$27.68 | **−$194** |
| Net @ full tick | −2.107 | −$52.68 | **−$369** |

**Answer: there is no gross edge, and the net is the cost.** The break-even cost multiple is
0.00× — nothing for costs to eat, which is *not* the "real edge eaten by costs" outcome most SR3
RV programmes in this repo have produced.

**Do not read the t-statistics as evidence.** The daily Sharpe of −1.37 and NW t of −2.31 are
mostly the cost: the full round trip is booked in a single step at each unwind, so the daily
series is 7 cost spikes on an otherwise gross curve. The statistic that matters is the gross
per-trade mean, and there

    t = −0.107 / (1.994 / √7) = **−0.14**

— indistinguishable from zero. (Same trap as the dealer-ladder study, where a t of −9.44\*\*\*
turned out to be the cost constant rather than evidence.) The confound regression agrees:
per-trade net on `lambda_z` gives β = −0.067, t = −0.25.

Note also that gross **median is +0.50bp** against a mean of −0.107: most trades are small
winners and a couple are large losers. At n = 7 that is a description of seven numbers, not a
distribution.

Criterion 6 (independent meeting cycles ≥ 6) **passes** on this panel — the one bar the study
clears.

### The placebo, and its provenance

The shuffle placebo was run on the **pre-guard SFRZ26 panel** (10 seeds), not on the guarded
one:

```
shuffled gross bp/trade: mean +0.188  p90 +0.374  max +0.594   LIVE -0.214
live beats 10% of shuffles   (FAIL, kill criterion 2)
```

Permuting λ across dates — same trade calendar, same costs, same fit quality, no information —
beats the real λ nine times in ten. It is stated separately and with its panel named because
moving it to the guarded panel costs ~4 hours of compute (each seed re-runs every contract
through the pricing engine), and the obvious shortcut — restricting to the two contracts that
fire under the *true* λ — would bias the null in the strategy's favour, since a permutation can
make the other three fire. A rigged placebo is worse than a dated one.

**Sample honesty: 7 trades, 6 meeting cycles, 2 contracts actually trading.** Far too small to
*conclude* the sign is negative. What it rules out is the opposite claim: on every sample where
this signal has been made to trade, there is no evidence in its favour, the point estimate sits
on the wrong side of zero, and the one placebo that has been run puts it below the noise.

## Why it did not trade: the fit gate, not the idea

Of 555 sessions across 5 contracts (SFRZ25 → SFRZ26, 2025-05 → 2026-08):

| stage | sessions | note |
|---|---|---|
| extracted | 555 | 0 SABR model densities — the Part A fix holds |
| λ applicable | 92 (17%) | ≥2 unit-weight meetings, one sign, lattice spans the density, interval wide enough |
| clears the fit gate | 28 (5.0%) | \|fwd resid\| < 1bp, pre-norm ≤ 1.02, ghost ≤ 5% |
| **also cross-strike coherent** | **8 (1.4%)** | atom spread ≤ 0.60 — 7 of them one contract |
| enough to standardise | 0 | largest contract supplies 7, needs 30 |

**One session in sixty-nine.** Not one in nine, which was the single-contract estimate.

**The binding constraint on this programme is measurability, not economics.** Three independent
filters compound: the copula framework only applies when the resolved meetings carry unit
day-weight, share a sign, and produce a lattice that actually spans the density (17% of
sessions); the vol-space Breeden-Litzenberger fit ties out to the martingale on 30% of those;
and the surface is cross-strike coherent on under a third of what is left. That is the number
to attack if this is taken further, and it is a data-and-fitting problem, not a thesis problem.

The gates are not arbitrary — see §5b of the measurement note. Three of the four applicability
guards were forced by an independent quantity refusing to behave: the calibrated SOFR-EFFR
basis, which came back at a mean of −39bp before them and reads +6.4bp ± 0.9 after.

## What was established anyway, and it is not nothing

Three results survive independently of the backtest, because they are measurements rather than
P&L (details and reproduction in the measurement note):

1. **The variance route is dead, and more decisively than predicted.** Not just a ±0.65-per-10bp/yr
   error bar — the observed RND variance exceeds the comonotone bound on **100%** of admissible
   sessions *at zero assumed non-meeting variance*. Bringing λ_var on scale needs ~66bp/yr of
   non-meeting vol against a total ATM vol of ~70. λ is a shape statistic or it is nothing.
2. **λ is regime-dependent, and that is the substantive finding.** In the 2025 cutting cycle
   (SFRZ25, 17 sessions) the market priced the meetings as nearly independent, mean λ **+0.15** —
   "they'll cut, timing uncertain". In the 2026 hiking cycle (SFRZ26) it prices them materially
   comonotone, mean **+0.55** — "do they go at all". Within a contract λ is stable (sd 0.06);
   across regimes it is a different animal. The published 0.54 sits at the 37th percentile of
   SFRZ26 alone and the **79th across four contracts**, so the original worry that it was the
   favourable end was right *on the pooled sample* — and a pooled prior would have been fitted
   to one half of the history.
3. **The 50bp kill test passes within a contract and FAILS across them.** Allowing 50bp outcomes
   moves λ down by ~0.14 at a 25% size mix, comparable to its entire cross-session standard
   deviation, so the *level* is contaminated. Rank ordering survives at corr 0.993 on one
   contract — but only **0.769** across four, below the pre-registered 0.90. Kill criterion 5.6
   is invoked. The single-contract test was reassuring and wrong: within one contract the
   marginals are similar enough that a size mix rescales everything almost uniformly; across
   contracts, where a pooled prior would actually be used, the same contamination reorders the
   sessions. **λ is comparable within a contract and a regime, not across them.**

## Standing, un-run

- **Q3, the strongest claim in the original thesis** — that the modes stay pinned while the
  forward translates — is still unanswered, and the reason is worth stating precisely rather
  than filing under "didn't get to it". Two causes, one of them mine: (i) the mode data was
  being *coupled to the copula gates* — `measure_lambda` returned early on a copula-applicability
  guard before computing the modes, discarding shape evidence for every session where only the
  *coupling* was unidentified. Fixed: the shape and fit-quality fields are now recorded on every
  session with a usable density, and the Q3 regression is gated on fit quality alone, since mode
  location needs no copula machinery. (ii) Even so, bimodality is rare once the fit gate applies
  — 5 of 28 on the current panel — so the n ≥ 10 floor is not yet cleared. The regression
  includes the control the original framing omitted: the atom pins are ZQ-anchored, so a flat
  mode-vs-forward β proves nothing unless the pins themselves move with the forward.
- **Term structure of λ** across contracts on the same date: implemented, but no adjacent
  contract pair yet has ≥ 5 overlapping admissible sessions — a direct consequence of the 1-in-69
  measurability rate.
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
