# Strikeless Vol — the Ultra-Long Forward Slope as a Long-Dated Vol Instrument

**Date:** 2026-08-04
**Branch:** `feat/strikeless-vol` (worktree `../ARBS-sv`)
**Question:** the DV01-neutral ultra-long forward flattener is a delta-hedged
straddle built from linear instruments. Is the embedded vol systematically
mispriced, is the mispricing *conditional and two-sided*, and does a rulebook
that switches sign on valuation + drift survive costs, multiple testing and
cross-market extension?

## The mechanism (what the system is actually trading)

Beyond the ~10y forward point, expectations differences between forward dates
wash out; the slope between distant forwards is convexity differential plus
slow term-premium/flow technicals. Convexity per unit DV01 rises with maturity,
so a DV01-neutral flattener (receive the longer forward, pay the shorter) is
structurally positively convex and the market charges for it by inverting the
ultra-long forward curve. The spread level is therefore a **price of long-dated
vol**; the Greeks map one-to-one onto a delta-hedged straddle (delta = residual
DV01 drift, gamma = net convexity harvested by resizing, theta = roll, vega =
spread MTM).

**The rebalancing rule is the option replication.** Unhedged this is a curve
position with a story. Both signs rebalance: a steepener runs the short-straddle
ledger (carry collected vs convexity paid).

## Measured data facts (probed 2026-08-04, not assumed)

| Fact | Source | Consequence |
|---|---|---|
| GS Marquee auth works; `IR_SWAPTION_VOLS_V1_STANDARD` carries **240 assets across USD/EUR/GBP/JPY/AUD** | `ds.get_coverage()` | cross-market vol is available; `definitions/IRSwaptions.ASSET_IDS_MAP` is USD-only today and must be extended by parsing coverage names (`"Swaption EUR-6m Payer 5y 5y ATM Physically Settled"`) |
| USD 2y10y normal vol history **starts 2017-01-03**, 2409 daily obs → 2026-08-03 | GS dataset | **no vol regression before 2017.** The Citi 2010–19 *regression* cannot be reproduced; the 2010–19 *P&L* control can (curves only) |
| Today's USD 2y10y `impliedNormalVolatility` = 5.329 daily-bp; × √252 = **84.6 annual normals** | GS dataset | identical to the figure in the research brief — same series, so the brief's betas are directly comparable |
| GS `USD-OIS` rateslib curve cached back to **2010-10-11** (daily) | `data/ts` asset `IRS__GSQUANT-RL__USD-OIS__*` | long-history curve spine for the static-long control |
| `USD-OIS` knot set stops at **30Y**, extrapolation +20y | `MDP/IRSwaps/GSQUANT/rl_basic/build.py` | 10y10y ✅ 15y5y ✅ 20y10y ✅ — **25y10y needs the 35y point, which today is extrapolated, i.e. fitted air.** Must add a 40Y knot or drop the pair |
| `EUR-ESTR` and `JPY-TONAR` builders exist but nothing is cached; **no GBP-SONIA builder** | same file | EUR/JPY = backfill cost only; GBP = new curve definition (stretch) |
| `BT/signals/tfp_swap_spread.py` already implements the Dallas Fed / JPM cross-sectional regression (ASW vs modified duration, intercept discarded) | repo | **UMEP is reuse, not a build** — but it is USD-only (needs a UST curve) |
| ERIS `USD-SOFR-1D` panel starts 2022; Barchart intraday from 2021 | `data/ts` | cross-validation window for the OIS-built series, not a primary spine |

## Conventions (load-bearing — pinned in one module, asserted in tests)

- `ASW = UST yield − matched swap rate` (**tool convention**; desk convention is
  its negative). 30y ≈ +74.6bp on 2026-08-03.
- `curve = longer forward − shorter forward` (e.g. `20y10y − 10y10y`);
  **negative = inverted**. Flattener = receive longer, pay shorter, and is the
  long-convexity side.
- All vol in **bp/day** internally; annual normals only at display boundaries,
  always with the conversion (`× √252`) written at the call site.
- Every vol carries a label stating *what it is computed on*: which forward,
  which tail, which window, which measure (realized / implied / breakeven).
  A `VolQuote` dataclass carries the label; unlabeled floats do not cross a
  module boundary.
- Under tool convention: **drag hypothesis ⇒ negative coefficient** of the slope
  on ASW/UMEP; **common-factor hypothesis ⇒ positive**.

## Architecture

New package `RVUtils/StrikelessVol/`. Data lands in
`notebooks/data/strikeless_vol/*.parquet` (the `meeting_prob` convention).

```
RVUtils/StrikelessVol/
  conventions.py   sign constants, VolQuote, unit conversions, assertions
  universe.py      ForwardPair(market, short_fwd, short_tail, long_fwd, long_tail)
                   + the pair registry and its curve-node requirements
  panels.py        forward par-rate panels, vol panels, UMEP panel; caching
  greeks.py        DV01 / Γ_net / carry / breakeven — ALL from repriced curves
  vol_metrics.py   realized vol, implied lookup, BE/realized, BE/implied
  replication.py   path-wise rebalancing simulator, four ledgers, aging, roll
  factors.py       changes/levels regressions, frequency ladder, residual z, drift
  strategy.py      the two-sided conditional rule (sign + size)
  backtest.py      static-long control, conditional book, cross-market portfolio
  costs.py         clip-size-aware schedule (wraps RVUtils/cost_model where it fits)
  report.py        league tables, ledger attribution, distribution diagnostics
BT/signals/strikeless_vol.py   daily runner: today's state per pair
tests/test_strikeless_vol_*.py
notebooks/rv/strikeless_vol_research.ipynb
notebooks/backtests/strikeless_vol/strikeless_vol_backtest.ipynb
```

Module rule: `greeks.py` never imports `strategy.py`; `panels.py` knows nothing
about pairs beyond the tenor strings it is asked for; `replication.py` takes a
callable that returns greeks for a date and is testable against a synthetic
curve path with no data access.

## The greeks contract (rigor standard 1 — repricing only)

For each date `d` and pair `p`, from the rateslib curve built for `d`:

- **Leg pricing** — both legs priced as forward-starting par swaps off the same
  curve object. No analytic forward-rate shortcuts.
- **DV01** — ±1bp parallel bump, reprice, central difference, per leg and for
  the package. Per-leg (bucketed) bumps also stored — they are the ladder used
  to solve the DV01-neutral ratio and, later, the PCA-hedged variant.
- **Γ_net** — second difference of package PV under ±h parallel reprices,
  `Γ(h) = (PV(+h) + PV(−h) − 2·PV(0)) / h²`, computed at **h ∈ {10, 25, 50} bp**.
  The h-dependence is reported, not averaged away: if Γ decays materially with
  move size, that is a finding about the instrument, and the breakeven inherits
  it.
- **Carry / roll (theta)** — PV change from advancing the valuation date one
  business day on the *unchanged* curve, plus accrual. Daily roll $ per $100k
  package DV01.
- **Breakeven** — `BE(h) = sqrt(2·|daily roll $| / Γ_net(h))` in bp/day,
  reported per `h`. The headline uses `h = 25bp` (the rebalance trigger prior);
  the `h`-spread is published beside it.
- **Vega translation** — `vega$ ≈ |β| · spread DV01` where `β` is the *rolling*
  changes-regression beta of the pair, never a global constant.

**Verification before any BE is believed** (the toy-model trap): for a single
vanilla swap, the repriced Γ must match the analytic annuity-weighted convexity
to within a stated tolerance, and the repriced DV01 must match the analytic
annuity. Both are unit tests with a hardcoded expected value computed from an
independent path. A checking tool that is itself wrong reports success — so the
test is also mutated (perturb the curve builder, confirm the test fails).

## The four ledgers (rigor standard 4)

Per day, per position:

1. **carry/roll** — theta as defined above.
2. **rebalance harvest** — the P&L of the *incremental* legs added at each
   resize, marked from the rate at which that increment was traded. Formally:
   at resize `k` the longer leg's notional changes by `Δn_k` at rate `r_k`; the
   harvest ledger is `Σ_k Δn_k · (r_t − r_k) · DV01_unit`, i.e. it holds the
   whole history of increments at their own strikes. It is not "total P&L minus
   the other three".
3. **spread MTM (vega)** — package PV change from curve moves on the notionals
   held at the start of each day, excluding the increments above.
4. **costs** — initiation, each hedge, each roll.

**Reconciliation is a hard test.** The four ledgers do not sum to total P&L by
identity — theta, the base-notional MTM and the increment MTM leave second-order
cross terms (a curve move changes the DV01 of the increments within the same
day). So the decomposition carries an explicit fifth bucket, **cross/residual**,
computed as the plug. The test is not that the plug is zero; it is that the plug
is *small and stationary*: `|cross| < 1%` of `|total|` per path and no trend in
its cumulative sum. A growing plug means the attribution is wrong, and a plug
quietly absorbing the harvest is exactly how H10 would be faked. The published output includes the
**harvest : |MTM| ratio** per pair — H10's claim is that harvest is
near-uniformly positive while total P&L is MTM-dominated. The brief's toy
suggested ~150:1; that number is to be measured, not carried.

## Replication rule (rigor standard 2 — path-wise)

DV01-neutral at inception. Resize the **longer** leg back to neutral when the
longer forward rate has moved ≥ trigger since the last resize.
Grid: trigger ∈ {10, 15, 20, 25, 30, 40} bp (H7's plateau claim spans 15–30).
Hedge instrument ∈ {adjust the off-market longer leg, ATM spot-starting swap} —
the brief flags both as open; both are implemented and compared.
Annual roll back to constant-maturity forwards, cost charged.

**Aging is explicit and never mixed with the constant-maturity panel.** The
signal panel is constant-maturity (10y10y every day); the position ages
(today's 10y10y is 9y10y in one year) and its greeks are repriced on the aged
definition. Mixing the two is the vintage trap that has cost this repo a full
re-classification before; a test asserts the position's tenor at t equals its
inception tenor minus elapsed time.

## Universe

| Market | Pairs | Notes |
|---|---|---|
| USD | 10y10y/20y10y, 15y5y/20y10y, 5y10y/15y10y, 10y10y/25y10y* | *only if the 40Y knot lands; otherwise dropped and said so |
| EUR | 10y10y/20y10y, 15y5y/20y10y | Wtp calendar as a drift covariate |
| JPY | 10y10y/20y10y, 15y5y/20y10y | post-lifer-exit "back-book" configuration |
| GBP | 15y10y/25y10y | **stretch** — needs a new `GBP-SONIA` curve definition *and* the 35y point (same knot dependency as USD 25y10y); dropped without ceremony if either fails |

Node-set coverage per market is a P0 measurement, not an assumption: `EUR-ESTR`
lists a 50y instrument, `JPY-TONAR` and `GBP-SONIA` are unverified. A pair whose
longest point is extrapolated is excluded from that market's universe and the
exclusion is published in the findings.

Constructions compared (H9): pure two-leg flattener; the same package hedged
with a received 1y-fwd 2-7-30 fly at PCA-solved weights (uses the existing
`RVUtils/rl_swap_risk_ladder_utils.solve_best_n_leg_hedge_pca`); and the
same-sector 15y5y/20y10y pair that needs no fly leg. Metric: carry-per-vega
after costs, and uncompensated factor risk measured as residual PCA exposure.

## Hypotheses → tests

| # | Claim | Test | Falsified if |
|---|---|---|---|
| H1 | vol is the only significant **daily** factor; UMEP acts weekly/monthly | changes regressions at 1d/5d/21d, HAC errors, DW reported | UMEP significant daily, or never significant at any frequency |
| H2 | drag vs common-factor resolves on the UMEP sign | UMEP as regressor (not 30y ASW); repeat on **Treasury-built forwards** where drag should vanish | sign unstable across sub-samples, or Treasury-built forwards show the same coefficient |
| H3 | vol beta scales ~linearly with the vol level (σ² mechanism) | rolling betas vs contemporaneous vol level; regression of β on σ | β flat in σ, or slope of the wrong sign |
| H4 | the vol-orthogonal residual drift is persistent in 2025–26 and partly forecastable | drift persistence (AR, variance ratio); predictive regressions on flow proxies (Wtp calendar windows, UMEP trend, dealer inventory) | drift indistinguishable from zero-mean noise out of sample |
| H5 | conditional two-sided rule beats static long on **distribution and drawdown** | both books, same costs; compare skew, tail, max DD, not just Sharpe | conditional book's distribution is not better despite similar Sharpe |
| H6 | levels residual mean-reverts ~1 week and is tradeable at \|z\| ≥ 1.5–2 | AR(1) half-life; event study of z-entries; net-of-cost expectancy | expected reversion < round-trip cost at every threshold |
| H7 | 15–30bp trigger plateau replicates OOS and cross-market | trigger grid × market × sub-sample | Sharpe monotone in trigger, or the plateau is sample-specific |
| H8 | cross-market signs currently differ and the book has better skew | per-market signal state; combined vs best-single distribution | signs agree everywhere, or the combination adds no distributional benefit |
| H9 | fly-hedged improves carry-per-vega without dominant factor risk; 15y5y/20y10y dominates 10y10y/20y10y after costs | three constructions, same engine and cost schedule | fly hedge's added cost and factor risk exceed the carry gain |
| H10 | harvest ledger near-uniformly positive, total P&L MTM-dominated | ledger decomposition per path | harvest sign flips materially, or MTM does not dominate |

## Controls, placebos, confounds

- **Positive control (required)**: a faithful static-long Citi-style backtest
  must land near the published stats — Sharpes ~0.05–0.35 by pair, daily P&L
  skew ≈ 0 (vs ≈ −3 for a short 1m10y straddle), monthly P&L correlation to
  Δ1y10y vol ≈ +26%. Recovering the long-vol **distributional signature** is
  the control, not the Sharpe point estimate. Failure here halts everything
  downstream — it means the greeks or the ledgers are wrong.
- **Analytic control**: repriced DV01/Γ vs closed form on a vanilla swap.
- **Regime re-basing check**: fit 2017–19, predict 2026; the brief's claim is a
  ~35bp intercept shift invisible to within-sample regression. Reproduce the
  gap and attribute it.
- **Placebo the mechanism**: run the identical rulebook on pairs where the
  convexity story should NOT hold (short-dated forward slopes, e.g. 1y5y/2y5y),
  and on shuffled vol series. A signal that survives the placebo is a
  calendar/curve artifact, not convexity.
- **Confound-check the winner**: whatever config wins, test it against
  duration-only, PC1-only and pure-carry alternatives before believing the vol
  story. The prior lesson stands — every defect found post-hoc in this repo's
  research has flattered the hypothesis.

## Honesty rules (binding)

- Lag-1 on the session calendar; no same-day information in any signal.
- Costs charged at Citi priors and stressed: initiate 0.75–1.0bp, hedge/roll
  0.3–0.4bp one-way per $100k DV01, at multipliers {0, 1, 2}; Sharpe reported
  as a function of clip size (capacity is a first-order constraint, and the
  conclusion is stated in clips, not in ratios).
- Sizing off total spread daily vol (≈1.65bp/day measured, re-estimated per
  pair and per regime), **never** off the rebalancing harvest.
- Every config family reports n, hit, gross, net@1x, net@2x, t, Sharpe, and
  **deflated Sharpe with the full trial count across all families**
  (`BT/signals/deflated_sharpe.py`).
- Chronological-half stability and winner-neighborhood stability for anything
  claimed ALIVE; verdict taxonomy per `RVUtils/SFRRVLab`.
- Levels regressions are labelled RV anchors and never used for inference
  (DW ≈ 0.2 in the brief's sample); inference runs on changes with HAC errors.
- The short-convexity side carries hard gates (implied spike, residual-z
  blowout, crowding proxy) and its tail is reported separately — a crowded
  carry steepener unwinds as a flattening squeeze.

## The rule (two-sided, conditional)

- **Signal 1 — valuation (slow)**: `BE/realized` and `BE/implied` per pair.
  Well below 1 → flattener; well above 1 → steepener; near 1 → flat. Bands
  estimated from the ratio's own distribution per pair, not hardcoded.
- **Signal 2 — drift (slow)**: rolling mean of the vol-orthogonal changes
  residual. Significantly positive drift overrides mildly cheap valuation.
- **Signal 3 — RV overlay (fast)**: z of the two-factor levels residual with
  **AR-adjusted bands** (not OLS SE). Entry |z| ≥ 1.5–2, exit at 0 — as a prior
  to be re-estimated per pair.
- Blend: sign from 1 gated by 2, size scaled by 3, risk-parity across pairs and
  markets on spread daily vol, per-market and book-level caps.

## Deliverables and phasing (one spec, staged execution)

- **P0 data** — extend `ASSET_IDS_MAP` to EUR/GBP/JPY from coverage; add 40Y
  (and 50Y if it resolves) knots to `USD-OIS`/`EUR-ESTR`/`JPY-TONAR`; backfill
  EUR/JPY curves; build and cache forward/vol/UMEP panels; measure and publish
  actual coverage per market. Cross-validate OIS-built vs SOFR-built USD
  forwards on 2022+ and report the divergence before choosing the spine.
- **P1 greeks** — `greeks.py` + analytic control tests + BE panel.
- **P2 replication + control** — `replication.py`, four ledgers, reconciliation
  test, **the Citi static-long positive control**. Gate: no downstream work
  until the distributional signature is recovered.
- **P3 factors** — `factors.py`, H1–H4, H6 diagnostics; reproduce the brief's
  2026 numbers from raw data as validation (β ≈ −0.78/R² ≈ 0.34 changes;
  two-factor levels R² ≈ 0.455) before extending the sample.
- **P4 strategy + backtest** — H5, H7, H9, H10; league tables with DSR.
- **P5 cross-market** — EUR/JPY (+GBP if it lands), H8.
- **P6 runner + findings** — `BT/signals/strikeless_vol.py` daily state per
  pair; `docs/superpowers/specs/2026-08-04-strikeless-vol-findings.md`.

Tests run under `conda run -n stir`; fast gate is
`python -m pytest tests -m "not slow and not network and not db"`. GS pulls are
`network`-marked; panel builds are `slow`-marked.

## Known limits, stated up front

- Swaption vol starts 2017-01-03. Any claim about the 2010–19 regime rests on
  curves alone.
- UMEP is USD-only (it needs a UST curve); EUR/JPY/GBP signals run on
  valuation + drift, and the two-factor levels residual is a USD-only overlay.
- The 35y forward point does not exist in the current node set. Either the 40Y
  knot lands or 25y10y is dropped — it is not to be fitted from extrapolation.
- Max GS swaption expiry is 10y, so a 20y-expiry vol (the mechanically exact
  regressor for the long leg of a 20y10y position) is unavailable; 10y10y is
  the closest and the approximation is reported.
- Backtest realism ends at mid-market plus a cost schedule; there is no order
  book for 30y forward swaps and capacity is asserted from clip sensitivity,
  not measured.

## Out of scope

Dashboard surfacing, scheduled/cron production, Supabase persistence of signal
history, swaption-based expression of the same view (the strike-ful switch is
priced as a comparison, not traded), and any non-USD ASW/UMEP construction.
