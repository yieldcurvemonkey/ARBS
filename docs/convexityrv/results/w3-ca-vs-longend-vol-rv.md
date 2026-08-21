# W3 — STIR convexity against long-end curve convexity, as vol RV: **DEAD at the diagnostic**

Measured 2026-08-21, worktree `ARBS-cvx2`, 2021-01-01 → 2026-08-20.

Both legs are *curve-implied volatility* on the same ruler, sourced from two
markets that never have to agree:

* **STIR** — a SOFR pack's convexity adjustment is a variance quantity
  (`CA = ½·σ²·mean(T1²)`), so inverting the observed adjustment gives a normal
  vol with **no fitted parameter in it**.
* **The long end** — a DV01-neutral ultra-long forward flattener's *daily
  breakeven*: the move that makes its convexity gain offset its negative carry.

Neither is an option price. That is the appeal: two independent readings of what
convexity costs, one at the very front and one at the very back.

**The premise fails before any backtest.**

---

## 1. The two legs do not move together

16 (colour, pair) combinations, 2021-2026. Correlation of **daily changes** —
the number that matters, because two trending series correlate in levels for
reasons that are not tradable:

| | max \|corr of changes\| |
|---|---:|
| across all 16 combinations | **0.112** |

Most sit between 0.00 and 0.08, and several are negative. The strongest is Golds
against `15Yx5Y/20Yx10Y` at −0.112 on n = 691.

Level correlations are mostly *negative* (−0.08 to −0.63) — when front-end
convexity is expensive, long-end convexity tends to be cheap — which is
economically interesting and not tradable on its own.

## 2. The spread does not revert

A z-score entry **assumes** the spread is stationary. Augmented Dickey-Fuller on
each spread:

* **14 of 16 fail to reject a unit root at 5 %.**
* The two that do reject — Reds against `15Yx5Y/20Yx10Y` (p = 0.0003) and Reds
  against `20Yx5Y/25Yx5Y` (p = 0.0015) — have half-lives of **1.22 and 1.62
  days**.

So either the spread is a random walk, in which case a z-score signal is fitting
the sampling distribution of a unit root, or it reverts far too fast to pay a
0.5 bp round trip. Neither is a strategy.

The checker is graded against both known answers before it is believed: two
independent random walks must **not** reject, and an Ornstein-Uhlenbeck spread
must. Without both, "14 of 16 fail to reject" would mean nothing.

## 3. A unit error, caught by the levels rather than the correlation

`holee.implied_vol_from_ca_bp` returns bp per **year** — its docstring says so.
`be_daily_analytic` is Citi's daily breakeven, in bp per **day**. The first run of
this module spread them as they came:

| | first run | after the fix |
|---|---:|---:|
| STIR leg mean | 100 – 135 | **6.3 – 8.5** |
| long-end leg mean | 2.5 – 4.0 | 2.3 – 4.0 |
| "spread" mean | ~100 | 3.2 – 4.5 |

A factor of `sqrt(252) ≈ 15.9`, entirely inside one column name.

**Correlation is scale-invariant, so the link diagnostics were untouched by it**
— the change-correlation table would have been reported exactly as it stands, and
the conclusion would have been right for the wrong reason. Every level, spread
and z-score was wrong.

Both legs now leave the module in bp/day, and a guard rejects any STIR series
whose median falls outside 0.5–40 bp/day, because a wrong-unit series stays
plausible in isolation and only the *spread* goes wrong — the hardest place to
notice it. This package has the same trap on record twice already (`delta_abs` in
percent; `ABPV/ATM` differing by asset class).

## 4. Why no QueryDrivenBacktest certification was spent

The house pattern is to simulate a grid on panels and certify the top cells
through the engine. Here the *premise* is rejected at the diagnostic stage, so an
engine certification would price, to 1e-13 agreement, a strategy whose
stationarity assumption the data refuses. The notebook quantifies the rule with a
bounded panel simulation and says plainly that the engine run was not spent and
why.

That is the point of running diagnostics first: so a backtest is not spent on two
random walks.

## 5. What is worth keeping

The **screen** is still useful even though the trade is not. Where front-end and
long-end curve-implied vol currently sit relative to each other is a market read,
and the module produces it. `notebooks/backtests/convexity_rv/w3_vol_rv_screener`
carries it with the ADF p-value and half-life displayed alongside the z-score, so
a reader can see immediately that the z-score is not a trading signal.
