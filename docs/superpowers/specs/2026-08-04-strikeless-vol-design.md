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
| `USD-OIS` knot set stops at **30Y**, extrapolation +20y | `MDP/IRSwaps/GSQUANT/rl_basic/build.py` | 10y10y ✅ 15y5y ✅ 20y10y ✅; 25y10y needs a 35y point |
| **GS coverage sheet settles the knot question** (33,111 instruments, local file, no network): USD OIS **max 30y** (history 2010-01-04), USD SOFR max 30y (2018-04-27), **EUR ESTR to 50y** (2018-12/2019-08), JPY TONA max 30y (2010-01-04), **GBP OIS to 50y (2010-01-04)** | `MDP/IRSwaps/GSQUANT/COVERAGE/IR_SWAP_RATES_V1_STANDARD_COVERAGE.xlsx` | **USD 25y10y is dead — the 35y point does not exist at any provider tenor.** EUR and GBP support it; GBP is the *only* market with both 50y coverage and 2010 history |
| `EUR-ESTR` and `JPY-TONAR` builders exist but nothing is cached; no GBP builder, but the instruments are named `GBP Swap OIS 1y ATM 0b to Ny LCH Cleared` and cover 1–50y from 2010 | same file + coverage sheet | EUR/JPY = backfill cost only. GBP is no longer speculative: writing the curve definition is mechanical, mirroring EUR/JPY |
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

Set by measured provider coverage, not by preference:

| Market | Curve | Longest observed point | Sample | Pairs |
|---|---|---|---|---|
| USD | `USD-OIS` (spine), `USD-SOFR-1D` (cross-check) | 30y | 2010-01-04 (OIS), 2018-04-27 (SOFR) | 10y10y/20y10y, 15y5y/20y10y, 5y10y/15y10y |
| EUR | `EUR-ESTR` | 50y | ~2019 | 10y10y/20y10y, 15y5y/20y10y, 10y10y/25y10y |
| JPY | `JPY-TONAR` | 30y | 2010-01-04 | 10y10y/20y10y, 15y5y/20y10y |
| GBP | `GBP-OIS` (new definition) | 50y | 2010-01-04 | 15y10y/25y10y, 10y10y/20y10y |

**USD 10y10y/25y10y is excluded** — its 35y point is not published at any GS
tenor, so it cannot be observed and will not be extrapolated. GBP was scoped as
a stretch before the coverage sheet was read; it is now the only market with
both 50y coverage and 2010 history, so it carries the ultra-long pair the USD
curve cannot. A pair whose longest point is not an observed instrument is
excluded from that market's universe and the exclusion is published in the
findings.

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

- **Positive control — SUPERSEDED, and the reason is itself a finding.** This
  spec originally required the static-long backtest to recover the published
  distributional signature: Sharpe ~0.05–0.35, daily P&L skew ≈ 0 (vs ≈ −3 for
  a short 1m10y straddle), monthly P&L correlation to Δ1y10y vol ≈ +26%, with
  "the distribution, not the Sharpe" as the test. **Task 13 measured that none
  of those three criteria carries information about convexity.** A DV01-matched
  **zero-convexity twin** — a constant-maturity flattener with no aging, no
  gamma and zero harvest — clears all of them with *better* numbers than the
  real package (skew +0.288 vs +0.087, vol-corr +0.613 vs +0.635, Sharpe +0.228
  vs +0.046, the twin landing inside the published band the real book misses),
  and the short-convexity **steepener** passes the skew and Sharpe criteria too.
  The mechanism is exact: this instrument carries an unhedged first-order slope
  exposure holding ~95.6% of its daily variance, so its distribution is the
  slope's distribution, and `corr(−Δspread, Δvol)` reproduces the twin's vol
  correlation to four decimals. The twin is committed as a runnable null model.

  **Replacement control.** Convexity is evidenced by, in order of strength:
  the closed-form analytic Γ check; carry equal to the independently repriced
  daily roll date by date on real curves; harvest equal to an independent
  per-day replay carrying a shuffle counterexample; the DV01 traded per resize
  implied by the cost ledger matching Γ·h (measured $5,311 vs $5,102, 4%);
  harvest flipping sign exactly with the position and vanishing on instruments
  without convexity. Sharpe is actively misleading here: both placebo pairs
  out-Sharpe every real pair while running the opposite carry sign.

  **`resid_skew` / `mirror_split` — domain established by refutation, not by
  assumption.** The mirrored paired difference was tested on the placebos and
  failed: placebo-2's steepener printed a near-exact *reflection* rather than
  the same-signed misfit the cancellation argument needs, so differencing
  doubled the error (−0.830) instead of cancelling it. Decisively, the two
  placebo pairs carry **identical Γ to within 0.2%** (20.31 vs 20.34 $/bp²) and
  receive **opposite** `resid_skew` signs — at a tenth the study pair's
  convexity the sign carries no information. Pairing cancels contamination
  *common* to both books; it does nothing to position-odd noise. `mirror_split`
  is therefore a **confirmatory** statistic in the high-Γ, high-R² regime only
  (study pair: Γ ≈ 204 $/bp², R² ≈ 0.956, split +5.13), the **R² cut is what
  excludes the placebos**, and neither statistic may rank anything.
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

- **P0 data** — extend `ASSET_IDS_MAP` to EUR/GBP/JPY from the swaption
  coverage; extend `EUR-ESTR` knots to 35/40/50y (they exist); write the
  `GBP-OIS` curve definition (1–50y, 2010+); backfill EUR/JPY/GBP curves; build
  and cache forward/vol/UMEP panels. Cross-validate OIS-built vs SOFR-built USD
  forwards on the 2018-04-27+ overlap and report the divergence before fixing
  the spine. USD and JPY node sets stay at 30y — the instruments stop there.
- **P1 greeks** — `greeks.py` + analytic control tests + BE panel.
- **P2 replication + control** — `replication.py`, four ledgers, reconciliation
  test, **the Citi static-long positive control**. Gate — as run: the control
  executes, is directionally correct, and reproduces the published Sharpe
  *spread*; the distributional criteria were found **non-discriminating** (see
  the superseded positive-control section above) and were replaced by the
  mechanism evidence listed there. Downstream work proceeds on that evidence,
  not on the distributional signature.
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
- The 35y USD point does not exist at the provider. USD 25y10y is dropped, not
  extrapolated; the ultra-long pair lives in GBP and EUR instead.
- EUR's sample starts ~2019 (ESTR); pre-2019 EUR would need EURIBOR-discounted
  curves and is out of scope, so EUR contributes ~7 years, not 16.
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
