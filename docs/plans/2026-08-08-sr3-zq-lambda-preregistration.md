# Pre-registration: SR3 copula-coordinate (λ) butterfly

**Committed before the first backtest run.** Everything below is fixed in advance. If a
later commit changes any threshold, bar, or kill rule, that is a new hypothesis and the
result is exploratory, not confirmatory — and it must say so.

Prior: two previous SR3 RV programmes in this repo returned 0/47 and 0/360 alive. A third
(the outcome-map lattice trade) reached 0/360 with a wrong-calendar placebo that retained
88% of its edge. The base rate for "this one is different" is low, and the bar below is set
accordingly rather than to whatever this strategy happens to clear.

## 1. What is being traded, and why it is not an arbitrage

ZQ pins the marginal hike probability at each FOMC meeting. Marginals fix `E[K]` and say
nothing about `Var(K)`. Any payoff linear in `K` is copula-free — that is the future — so
there is **no copula-free arbitrage** between the ZQ strip and SR3 options. λ is an
unobservable the market must price, and Sklar's theorem makes the marginal and the copula
orthogonal: there is no exchange rate between them and no convergence to trade. Only two
tiers exist:

- **HARD.** `Var_RND` outside `[Var_min, Var_com]` is a genuine static arbitrage. Checked
  daily, free, expected to be rare. Reported, not backtested.
- **SOFT.** Inside the interval, λ versus a prior is a view trade. This is what is
  backtested below.

## 2. Signal definition (fixed)

- **λ = `lambda_wing`**, the absorbed-tail convention: observed atom probabilities from the
  BL CDF differenced at bucket edges `pin_k ± 12.5bp`, with mass outside the lattice assigned
  to the nearest end atom, then `(w_obs − w_ind) / (w_com − w_ind)`.
  Rationale for absorbed over strict: the move count cannot be below 0 or above `n`, so
  off-lattice mass is not a state; leaving it out compares a law summing to ~0.83 against
  bounds summing to 1.0.
- **Density config, non-negotiable:** `use_sabr_vols=False`, `raw_market_open_interest_min=None`,
  `raw_market_otm_only=True`, `allow_sabr_fallback=False`, `fit_space="vol"`. A SABR density is
  unimodal by construction and would confirm the null by construction.
- **Admissibility gate, applied before the signal is computed:** `|forward_residual_bp| < 1.0`,
  `pre_normalization_mass ≤ 1.02`, `ghost_mass_fraction ≤ 0.05`, `n_resolved ≥ 2`, every
  resolved meeting carrying day-weight exactly 1, and no mixed hike/cut set. A session failing
  any of these produces **no signal**, not a fallback signal.
- **Standardisation:** `z_t = (λ_t − mean(λ_{t−60..t−1})) / sd(λ_{t−60..t−1})`, trailing,
  strictly excluding `t`. Minimum 30 admissible observations in the window or no signal.
  Entry is on `z`, never on the raw level — the raw level is confounded with time to expiry
  and meeting count (see §5).

## 3. Trade, sizing, costs (fixed)

- **Structure:** SR3 option butterfly, all calls, strikes on the K-atom grid at the
  `FLY25` spacing (±0.25 price = ±25bp = exactly the atom spacing), centred on the middle
  atom of the measured lattice.
- **Direction:** `z ≤ −1.0` → **long the wings** (short the fly: weights `[-1, 2, -1]`),
  because a low λ means the market is pricing a fat middle and the wings are cheap.
  `z ≥ +1.0` → **long the fly**. `|z| < 1.0` → flat.
- **Size:** 1 fly lot = 4 option contracts. No scaling by conviction in v1.
- **Hold / exit:** to the scheduled roll (the existing `build_roll_schedule` rank-1 rule), or
  earlier if `z` crosses zero. Force-flatten on the final grid timestamp so no trade escapes
  the closed-position log.
- **Costs, headline:** `tcost_vol_bp = 0.125` per option contract per side — the half-tick —
  which is `2 × 4 × 0.125 = 1.0bp` of package premium round trip, i.e. $25 per lot.
  **Also reported at a full tick (`0.25` → 2.0bp round trip).** Net is the number that counts;
  gross is reported only to locate where any edge comes from.
- **Delta hedge:** off in v1. If enabled, the same-timestep unwind defect in
  `famb_fly_qdb.py` (adds are processed before unwinds, so the hedge is closed in the step it
  opens while its cost still accrues) must be fixed first, and the fix verified by asserting
  the hedged equity curve differs from the unhedged one.

## 4. Success bar (fixed)

**ALIVE** requires *all* of:

| # | Criterion | Threshold |
|---|-----------|-----------|
| 1 | Trade count | ≥ 25 closed round trips |
| 2 | Net P&L per trade, at the half-tick | > 0 bp of package |
| 3 | Net P&L per trade, at the full tick | > 0 bp of package |
| 4 | Deflated Sharpe probability | `dsr_prob > 0.5`, `n_trials` = the full configuration count actually run |
| 5 | Median per-trade net | ≥ 0 |
| 6 | Effective sample size | ≥ 6 independent meeting cycles, stated explicitly |

This is `RVUtils.SFRRVLab.stats.verdict(...)` plus criteria 3 and 6. Anything that clears 1–5
but not 6 is **MONITOR**, not ALIVE.

**MARGINAL** = clears 1, 2, 4, 5 but fails 3 (survives at the half-tick only).

**DEAD** = anything else.

## 5. What kills it (fixed, stated before seeing the result)

1. **Wrong-calendar placebo.** Re-run with the FOMC effective dates shifted by +45 days (a
   calendar with the same number of meetings and the same spacing statistics, but wrong).
   *If the placebo retains > 50% of the gross edge, the signal is cell geometry, not lattice
   probability, and the result is DEAD regardless of its Sharpe.* This exact failure has
   already happened once in this repo at 88% retention.
2. **Shuffle placebo.** Randomly permute the λ series across dates within each contract
   (20 seeds). If the true edge is not outside the 90th percentile of the shuffled
   distribution, DEAD.
3. **Time-to-expiry confound.** λ is mechanically related to dte (fewer meetings resolve as
   expiry approaches) and to meeting count. If a regression of per-trade net on `z` loses
   significance once dte and `n_resolved` are included, the signal is the calendar. DEAD.
4. **Fit-quality confound.** If the edge concentrates in sessions with the worst admissible
   `forward_residual_bp`, it is spline noise. DEAD.
5. **Cost sensitivity.** If the break-even cost multiple is below 1.0× the half-tick, DEAD —
   there is no room.
6. **50bp contamination.** λ is estimated under a binary 0/25 marginal. ZQ pins only the
   *mean* of each marginal, so once 50bp moves are live, marginal shape and copula are not
   separately identified and size uncertainty is booked as dependence — biasing λ **upward**.
   If λ's sign flips or its rank ordering across sessions changes materially when a three-point
   {0, 25, 50} marginal is allowed with a plausible size-mix, the signal is not measuring the
   copula. This is a **kill criterion, not a caveat.**

## 6. Effective sample size, stated in advance

Across a strip there are 8–12 overlapping λ observations sharing the *same* meetings.
Independent draws are resolved meeting cycles, not sessions: roughly **2–3 per contract**.
The backtest will report the number of distinct meeting cycles, and any Sharpe will be quoted
against that, not against the session count. Expect the DSR wall.

## 7. Expected outcome, stated up front

Most likely **MONITOR**: a position-sizing and framing tool for a discretionary Fed view,
not standalone alpha. The framework's real contribution is that it makes a bimodal-Fed thesis
falsifiable on a continuous scale. That is the honest expected result and it will be reported
as such if that is what comes out.
