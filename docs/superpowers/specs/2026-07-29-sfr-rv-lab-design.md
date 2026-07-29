# SR3 Futures-vs-Options RV Lab — Design

**Date:** 2026-07-29
**Status:** In progress
**Branch:** `feat/sfr-rv-lab`
**Predecessor:** `docs/superpowers/specs/2026-07-28-fly-vs-vol-rv-framework-design.md` (ground truth
on what is already known), `notebooks/backtests/curve_vs_vol_basis_backtest.py` (prior verdicts).

## Problem

Enumerate, implement and honestly backtest many distinct relative-value frameworks between
listed 3M SOFR (SR3) quarterly futures and their listed options, over ~1–2 years of daily
history, and rank them in one league table with P&L in bp AND dollars.

## What is NOT RV (the constraint that killed three prior backtests)

Put-call parity plus the conversion/reversal arb pin each surface's risk-neutral **mean** to
its own futures settle. Therefore any "options-implied fair value of a futures structure"
is identically the traded structure; apparent gaps are spline-fit error with sub-1-day
half-lives. Real RV lives in exactly four places, and every framework below is classified
into one of them:

| Class | What varies | Frameworks |
|---|---|---|
| **A. Within-contract shape** | skew / smile composition at one expiry | skew basis, wing convexity, vol fly, tail rent |
| **B. Cross-contract coupling** | the joint law across expiries | same-strike digital calendars, mid-curve forward vol, conditional curve |
| **C. Vol vs realized** | implied vs delivered on the same contract | gamma/theta, vol carry, vol momentum |
| **D. Event speed** | which market reprices first | FOMC lead-lag, meeting-lattice composition |

## Non-negotiable honesty rules

1. **Listed marks only.** Signals and P&L are computed on settle premiums from
   `quotes.parquet` at strikes **fixed on the execution date**. BL/SABR model values are a
   comparison column, never a P&L mark. (Prior measurement: model-mark P&L correlates
   −0.13..−0.51 with executable P&L.)
2. **Lag-1 execution.** Fills at the bar after the signal bar. Lag-0 is reported only as an
   ablation (it inflated prior gross P&L by 56–72%).
3. **Costs.** Per-leg one-way 0.5bp per option leg, 0.25bp per futures leg; headline
   scenarios are flat round-trip 0.0 (maker), 1.5, 2.5bp. Every table shows gross and net.
4. **Quality gates at entry.** Both legs `|forward_residual_bp| ≤ 2.5` and
   `pre_normalization_mass ≤ 1.02`. Far-dated contracts show 8–32bp residuals; their
   z-scores are stale-surface artifacts.
5. **Grid discipline.** For every sweep report the DISTRIBUTION (median config, % net
   positive), the deflated Sharpe of the best config (`BT/signals/deflated_sharpe.py`),
   and one-param-at-a-time neighbourhood stability. The top row is never the verdict.
6. **Sign test both directions.** Mean-reversion AND momentum, per framework (house rule
   from `kink_fade`).
7. **Put-call parity hygiene.** Per (date, symbol, strike) with both rights present,
   `resid = C − P − (F − K)`. Strikes whose |resid| exceeds a threshold are model marks,
   not prices; they are flagged in the panel and gated out of wing-based signals.

## Dollars

SR3 futures and options: 1bp of price = **$25 per contract**. Panel P&L is in bp of package
premium per 1 contract per leg; the league table states **100 contracts per leg**, so
`$ = bp × 25 × 100 = bp × $2,500`. Delta-hedge legs are sized in futures contracts by the
listed `delta_abs` (signed +delta for calls, −delta for puts in price space).

## Data

`notebooks/rv/build_sfr_rv_panels.py` walks a **rolling live strip**
(`resolve_strip_symbols("2y", as_of=d)` per date, so contracts appear exactly while listed;
dates after `sofr_option_last_trade_date` are dropped — the expired-chain guard is correct
behaviour) over 2024-07-01 → 2026-07-28 and writes, checkpointed per symbol:

- `quotes.parquet` — as_of, symbol, right, strike_price, strike_rate, premium_bp, iv_bp,
  delta_abs, atm_offset_bps, oi, volume. **The only object P&L is marked on.**
- `contracts.parquet` — forward rate/price, expiry, tte, SABR params, BL moments and
  diagnostics (mean/median/mode/std/skew, fwd_resid_bp, pre_norm_mass, ghost_frac).
- `cdf.parquet` — BL CDF resampled on a fixed 0–8% / 2.5bp rate grid (float32), so every
  coupling and tail metric is recomputable without refetching.

Histories are stitched two ways: by **contract label** and by **constant-maturity slot**
(SFR1..SFR8, roll-adjusted).

Mid-curve panels (`midcurve_quotes.parquet`) use the same builder with the mid-curve roots.
The repo already maps `0Q→MMA, 2Q→MMB, 3Q→MMC, 4Q→MMD, 5Q→MME` in
`MDP/STIRFutures/_sofr_option_contracts.py::_BBG_TO_BARCHART`, with `_UNDERLYING_RULES`
giving the +1/+2/+3/+4/+5-year underlying offsets, and quarterly mid-curve roots are already
inside `_PRE_IMM_FRIDAY_OPTION_ROOTS`, so `sofr_option_last_trade_date` returns real dates
for them (only *weekly* mid-curves — `S01..S35` — return `None`). The mid-curve work is
therefore a data/backtest exercise, not a symbol-resolution fix; anything that does turn out
to be broken is fixed with a no-network fixture test.

## Engine — `RVUtils/SFRRVLab/`

Data-agnostic, synthetic-testable, extends rather than replaces `RVUtils/FlyVsVol`.

- `structures.py` — `Leg(kind, symbol, right, strike_price, weight)` and `Structure`
  (tuple of legs + label). `mark_structure(marks, structure, dates)` returns the package
  premium in bp per date, forward-filling a leg's last print and never silently dropping a
  leg. Futures legs mark at `price_bp = (100 − forward_rate) × 100`.
- `panels.py` — panel loading, ATM interpolation, listed-strike selection at a target rate
  offset or target delta, parity-residual computation, roll-adjusted constant-maturity
  slots, realized-vol estimators.
- `engine.py` — one generic backtest: signal frame (key, as_of, signal, gate) + a
  structure-builder callback → trades, daily bp P&L, daily $ P&L, metrics. Supports
  `direction ∈ {fade, momentum}`, exits `{z0, half, tN, stop}`, lag, per-leg or flat costs.
- `stats.py` — grid distribution block, DSR wrapper, Newey-West t, non-overlapping Sharpe,
  neighbourhood stability, and the marks×lag honesty panel.

## Framework catalog

Each gets an executed notebook, a grid, a sign test, and one league-table row per
(framework, best-honest-config) and (framework, median-config).

1. **Skew basis (RR-spread pairs)** — class A/B. Extends prior work: weekly rebalance,
   FOMC event-window entries, maker-cost scenario, 2-leg variants, cross-sectional LS.
2. **Same-strike calendar digitals** — class B. Tight listed call spreads at the same rate
   strike across adjacent expiries vs the comonotone and FedWatch-null term structures of
   `P(≥K)`. The most promising untested framework.
3. **Vol vs realized (gamma/theta)** — class C. Delta-hedged straddle P&L with daily
   rehedge on futures settle; IV−RV signals; always-short baseline; vol-return momentum;
   cross-sectional vol carry; delta-rebalance-threshold sweep.
4. **Wing convexity harvest** — class A. Short OTM wings vs fly/steepener hedge with
   disaster buyback; premium-native wing z; tail-probability vs realized frequency.
5. **Meeting lattice** — class D. FedWatch-null vs listed digital prices at lattice-mapped
   strikes, day-weighted (never naive 25bp mapping); traded as verticals.
6. **Fly vs straddle** — class A/C. Fly level z vs belly straddle premium z; plus the
   vol-butterfly (smile curvature) and skew term structure.
7. **FOMC event studies as trades** — class D. Which market repriced first in ±5d windows;
   any systematic lead-lag becomes a rule and is backtested.
8. **Momentum variants** — the sign test, run inside every notebook above.
9. **Mid-curve frameworks** — class B, the only listed instruments spanning the coupling
   dimension: forward vol (mid-curve vs quarterly on the same underlying), executable
   same-strike digital calendars, conditional curve (co-terminal, premium-neutral),
   skew term structure, meeting-resolution differences.

## Verdict taxonomy

`DEAD` (no edge gross, or edge < maker cost), `MARGINAL-maker-only` (net positive at 0–0.5bp
round trip, negative at 1.5bp+), `ALIVE` (net positive at 2.5bp with DSR > 0.5 and stable
neighbourhood). The league table is sorted honestly and reports both the best-honest and the
median config so selection bias is visible.

## Testing

Fast, synthetic, no network (`-m "not slow and not network and not db"`): closed-form or
hand-computable fixtures for structure marking, parity residuals, cost accounting, lag
accounting, direction sign, digital-from-vertical pricing, realized-vol estimators, and the
grid-distribution/DSR plumbing.
