# SERFF Fair-Value Model (ZQ vs SR3) — Design Spec

**Date:** 2026-07-02
**Status:** Built autonomously on branch `claude/focused-bun-faf561` per session mandate ("Work Autonomously"); this spec doubles as the plan the ground rules asked to confirm — review before merge.
**Scope:** Re-implement the standalone `serff_model.py` prototype (three-layer SOFR−FF fair-value model) inside ARBS conventions, restructured around a dated, source-tagged **residual ledger** (per the amendment), plus a walk-forward backtest of the ZQ-vs-SR3 futures spread with P&L attribution by source.

---

## 1. Goal

At any decision date, decompose SR3 − ZQ (rate space) into:

```
SR3 − ZQ = [realized-to-date fixings]           (booked, never modeled)
         + [forward remainder]                   (each day tagged policy / basis / turn)
         + [view remainder]                      (model expected − market implied, per source)
```

- **Layer 0 (mechanical):** policy path from meeting-dated ZQ/SR1 strip forwards; exact compounding (ε ≈ r²T/2 emerges from exact math, not an add-on).
- **Layer 1 (level):** daily SOFR−EFFR on non-turn days ~ regime intercepts + regime slopes on ln(liq/GDP) + TGA/GDP + mid-month dummy, HAC(20).
- **Layer 2 (turn):** hurdle on month-ends — logit P(spike > 5bp over local base) on ln(liq/GDP) + QE dummy; QuantReg (q50, q90) for magnitude.
- **Aggregator:** per-decision-date **residual ledger** (dated daily path), not a scalar fair value.
- **Backtest:** walk-forward, publication-lag aligned, DV01-correct 5 SR3 : 3 ZQ structures, exchange-settle reconciliation, P&L attributed basis / turn / policy-leakage.

## 2. Scope & Non-Goals

**In scope:** data fetchers (H.4.1, GDP) + panel builder; contract mechanics; three layers; ledger aggregator; futures EOD backfill (ZQ, SR3; SR1 best-effort purity check); backtest runner + attribution + reporting; tests incl. prototype validation anchors; one diagnostic notebook.

**Non-goals (surfaced, not silently fixed):**
- T-bill supply factor (Citi Δ-betas +0.27bp/$100bn bills, −0.67bp/$100bn reserves available as priors; `fiscaldata.py` in `MDP/FixedRateBonds/reference_data_cache` is the pattern for the extension).
- Real-time data vintages: DBnomics serves final revised H.4.1/GDP values. We align to **publication timestamps** (release-lag rule) but cannot recover as-published values. H.4.1 is essentially unrevised; GDP revisions are a genuine (small) look-ahead in liq/GDP denominators. Documented limitation.
- Post-2025 endogeneity (Fed reacts to the spread → slopes biased to zero, right tail censored): reported, not corrected. Regime-date sensitivity is reported as a diagnostic.

## 3. Repo mapping (inventory → decisions)

| Model component | Repo pattern followed | Location |
|---|---|---|
| SOFR/EFFR fixings | existing `fixings_cache._fetch_fixings` (NY Fed API, 8am-ET publication logic) | reuse `MDP/IRSwaps/fixings_cache` |
| Reserves / ON RRP / TGA (H.4.1) | `FixingsFetcher`-style keyless fetcher + dated-dir CSV cache | **new** `MDP/USMoneyMarkets/dbnomics_fetcher.py`, `h41.py` |
| Nominal GDP (BEA via DBnomics) | same | **new** `MDP/USMoneyMarkets/bea_gdp.py` |
| Panel builder (features, regimes, turn windows, publication alignment) | `build_basis_panel`-style cached builder | **new** `BT/serff/data.py` |
| Futures settlement history (ZQ/SR3/SR1) | `STIRFutureMDP` symbol layer + `BarchartFetcher.barchart_timeseries_api(interval=None)`; parquet cache like `BT/signals/_ustf_basis_cache` | **new** `BT/serff/futures_data.py` |
| FOMC effective dates | `Query/IRSwaps/_CENTRAL_BANK_DATES` (USD-FEDFUNDS), effective = decision + 1 day | consumed in `BT/serff/mechanics.py` |
| Contract mechanics (windows, settlement, backout) | pure functions + dataclasses (BT/misc.py QL calendar helpers style) | **new** `BT/serff/mechanics.py` |
| Three layers | statsmodels (formula OLS/HAC, Logit, QuantReg) — mirrors prototype exactly | **new** `BT/serff/layers.py` |
| Residual ledger | dataclasses + DataFrame emission | **new** `BT/serff/ledger.py` |
| Walk-forward | `pca_momentum` precedent (refit cadence + train-window config) | **new** `BT/serff/walkforward.py` |
| Backtest | **panel-driven runner** (existing convention: `sfr_cal_spread_rv`, `vectorized_backtest`) with explicit contracts, multipliers, tick costs, rolls | **new** `BT/serff/backtest.py` |
| Config | `@dataclass` configs (`RegressionRVConfig` precedent); every calibration parameter surfaced | **new** `BT/serff/config.py` |
| Tests | pytest markers, fixture parquet + `pytest.approx` tolerance bands | **new** `tests/serff/` |
| Package shape | `BT/flow_alpha/` subpackage precedent | **new** `BT/serff/` |

### Surfaced conflict — engine choice (per amendment instruction)

`QueryDrivenBacktest` (the "full" engine) resolves STIR futures pricers per timestamp via MDP; those pricers hang off swap-curve snapshots (`BARCHART_STIRF-RL`) whose history does not reliably extend to 2018, and the residual ledger needs marks at **actual exchange settles**, not curve-implied prices. The repo's second sanctioned convention — panel-driven runners marking at cached EOD settles (`sfr_cal_spread_rv`, `vectorized_backtest`, `risk_premia_pairs`) — marks exactly at settles and is what this build uses. For futures (linear payoff, daily variation margin) panel marks × contract multipliers are exact, not approximate.
**Option B (not built):** a `SERFFLedgerQuery` + `PositionHandler` wrapping the same panel, so positions flow through `QueryDrivenBacktest`/tearsheet. Additive later; the position ledger produced here carries the per-leg detail a handler would need.

## 4. Data contract

**Panel (daily, index = SOFR publication days, one row per fixing date):**
`sofr, effr, spread_bp, res, rrp, tga, gdp, liq_gdp, tga_gdp, ln_liq, is_me, is_qe, is_ye, turn_window, is_mid, regime, local_base, spike, published_at` (per-input publication timestamps in `published` alignment mode).

- **Alignment modes:** `contemporaneous` (prototype parity — weekly series ffilled on reference date) and `published` (each input usable only after its publication timestamp: fixings T+1 08:00 ET; H.4.1 Thursday 16:30 ET for prior Wednesday; GDP quarter-end + `gdp_publication_lag_days` (default 30)). The backtest uses `published`; validation anchors use `contemporaneous` to reproduce the prototype.
- **Futures panel:** per contract symbol → DataFrame(date → settle price [, volume, OI]); plus contract metadata (window start/end, multiplier, tick).

**Residual ledger (per decision date, per structure):** long DataFrame
`(leg, date) → [fixing_realized, expected_rate, market_implied_rate, source ∈ {realized, policy, basis, turn}, expected_sofr_ff, market_implied_sofr_ff, residual_bp]`
plus contract-level rollup: accrued block, forward block by source, total residual by source, in bp and $ per structure.

## 5. Module layout

```
MDP/USMoneyMarkets/
    __init__.py
    dbnomics_fetcher.py      # thin keyless DBnomics v22 client + dated-dir CSV cache
    h41.py                   # RESH4R_N.WW, RESPPLLRD_N.WW, RESPPLLDT_N.WW (+ publication stamps)
    bea_gdp.py               # BEA NIPA-T10105 A191RC-Q nominal GDP SAAR (+ publication stamps)
BT/serff/
    __init__.py
    config.py                # SerffDataConfig / SerffModelConfig / SerffTradeConfig / SerffBacktestConfig
    mechanics.py             # windows, day-weights, settlement math, FOMC weights, market-implied backout
    data.py                  # panel builder (both alignment modes) + parquet cache
    futures_data.py          # ZQ/SR3/SR1 EOD backfill via Barchart, parquet cache, settle reconciliation
    layers.py                # Layer0/1/2 estimation + prediction
    ledger.py                # residual ledger aggregator
    walkforward.py           # point-in-time refits, coefficient history
    backtest.py              # structures, rolls, costs, marks, attribution, reporting
tests/serff/
    conftest.py              # panel fixture loader
    fixtures/serff_panel.parquet
    test_mechanics.py  test_layers_anchors.py  test_ledger.py  test_backtest.py  test_data_live.py (network)
notebooks/backtests/serff_fair_value.ipynb
```

## 6. Key specifications

### 6.1 Mechanics (`mechanics.py`)
- Calendar: QuantLib `UnitedStates(SOFR)` (repo convention via `BT/misc.py` helpers).
- `zq_month_days(year, month)` → per-calendar-day weights with weekend/holiday carry (Friday counts 3×): weight of business day d = # calendar days until next business day.
- `sr3_window(contract)` → [3rd Wed of contract month, 3rd Wed +3 months), D = calendar days; per-business-day d_i = calendar days to next business day.
- `zq_settle(fixings)` = 100 − mean over calendar days (carried EFFR); `sr3_settle(fixings)` = 100 − 360/D·(Π(1+r_i·d_i/360)−1)·100. Rate/price space kept explicit: all internal math in **rate space**, converted at the futures boundary (`price = 100 − rate`).
- `fomc_weights(window, meeting_dates)`: effective date = decision + 1 BD; weight = accrual days ≥ eff. date in window / window days. (Checks: move eff. 2026-07-30 → 2/31 of ZQ N6, 48/91 of SR3 M6; eff. 2026-09-17 → 0 in M6.)
- `implied_remainder(price, realized_fixings, window)`: solve the flat remaining rate consistent with the settle convention (exact for ZQ arithmetic; Newton/closed-form for SR3 compounding). With an expected-EFFR shape supplied (from Layer 0), solves for the flat **spread over the shaped EFFR path** instead — the market-implied SOFR−FF over remaining days.
- Constants: ZQ/SR1 $41.67/bp, SR3 $25/bp; ticks 0.0025 front / 0.005 back (both roots), config-overridable.

### 6.2 Layers (`layers.py`) — prototype-faithful
- Layer 1: `smf.ols("spread ~ C(regime) + C(regime):ln_liq + tga_gdp + is_mid")` on non-turn rows, `cov_type="HAC", maxlags=hac_lags(20)`. Per-regime simple fits reported (pooled R² explicitly de-emphasized).
- Layer 2: spike = month-end spread − `local_base` (trailing `local_base_window=15` non-turn median, `min_periods=5`, shifted 1); hit = spike > `spike_threshold_bp=5`; `sm.Logit(hit ~ const + ln_liq + is_qe)` (GLM-Binomial fallback, as prototype); `smf.quantreg` at `quantiles=(0.50, 0.90)`.
- Layer 0: `policy_path(window, strip)` — meeting-dated moves from ZQ (fallback SR1) strip prices vs realized-EFFR base, converted to per-day expected EFFR via effective-date step function. Never regressed.
- Regime boundaries (config, defaults = prototype): 2020-03-01, 2021-04-01, 2023-10-01, 2024-12-19. Turn window = last 2 BD + first 1 BD (config). Mid-month = calendar days {14,15,16,17} (config).

### 6.3 Ledger (`ledger.py`)
Per decision date t and structure (SR3 contract + covering ZQ strip):
1. **Accrued:** fixings with publication ≤ t booked per leg (boundary = last published fixing).
2. **Forward expected:** per remaining day, expected EFFR (Layer 0) + expected spread: baseline (Layer 1, regime/covariates as of t) on ordinary days; + turn add-on on turn dates (P(hit) × max(q50,0) spread over `effective_spike_days=2`, in **daily** space so compounding weights it correctly).
3. **Market-implied:** per-leg implied flat remainder over the same days via `implied_remainder` (given realized block + Layer-0 EFFR shape).
4. **Residual per day per source** = expected − implied; contract-level rollup by source in bp and $.
Policy days are those within `policy_attribution_window_bd` of an effective date… **no** — tagging is by *content*: policy component = Layer-0 path contribution (worn, reported, not edge); basis = Layer-1 baseline vs implied on non-turn days; turn = Layer-2 add-on vs implied on turn dates.

### 6.4 Walk-forward (`walkforward.py`)
- Refit cadence: `refit_frequency="ME"` (month-end, config), expanding window from panel start; `min_train_days=750`, `min_turn_events=24` before Layer 2 activates.
- Every fit consumes only rows with `published_at ≤ decision_ts` (decision timestamp = 16:00 ET on decision date; H.4.1 released 16:30 ET is available the **next** day, parameterized via `h41_available_next_day=True`).
- Emits coefficient history for the regime-sensitivity and per-regime diagnostics.

### 6.5 Backtest (`backtest.py`)
- **Structure** (explicit, per theory section): the aggregate-DV01-neutral **strip basis** — 5 SR3 per {3 ZQ across the covering months, month-by-month 5:1 with stub months weighted (window days in month)/(days in month), rounded to integer contracts at `unit_scale`}. Rationale: isolates 3-month basis (turn + level) while the ZQ strip wears the policy path; a naive 1:1 (rejected) leaves $16.67/bp net direction and ~half-weighted FOMC exposure.
- **Signal:** contract-level turn+basis residual (policy residual excluded from the signal by construction); enter when |residual| ≥ `entry_threshold_bp` (default 1.5bp), direction = sign; exit when |residual| ≤ `exit_threshold_bp` (default 0.5bp) or at roll. Sized `max_units` (default 1).
- **Rolls:** front SR3 structure defined as nearest quarterly whose reference window end > decision date + `min_days_to_window_end` (default 10 BD); mandatory unwind then (positions never ride into the terminal fixing-dominated stub); ZQ hedge legs refreshed if strip membership changes (stub weights drift with the calendar, re-trued at `hedge_rebalance="ME"`).
- **P&L:** daily marks Δsettle × contracts × multiplier per leg; final settlement = exchange settle, with recomputed-from-fixings reconciliation gate (`settle_recon_tolerance_bp`, default 0.35bp; failures reported, not masked).
- **Costs:** `cost_ticks_per_leg_per_side=0.5` × tick value × contracts, both entry and exit, front/back tick schedule.
- **Attribution:** daily structure P&L decomposed exactly via the market-implied ledger identity — Δ(implied accrued) = realized-fixing carry, Δ(implied policy component) = policy leakage, Δ(implied basis/turn components) = basis / turn P&L; sums to total mark P&L by construction (small residual bucket for cross-terms/rounding reported).
- **Reports:** per-regime table, turn-event hit rate vs modeled P (calibration + Wilson CIs), realized turn P&L vs ex-ante modeled turn premium, bootstrap CIs (block bootstrap over months) honoring the ~99-month-end sample.

### 6.6 Validation anchors (regression tests, fixture panel = prototype sample 2018-04-02 → 2026-06-30, contemporaneous mode)
- Regime slope ln(liq/GDP): r2 (2021-04→2023-09) ≈ −0.35 (|b| < 2 band, sign + magnitude order); r4 (post-2024-12-19) ≈ −17 (band ±5).
- Logit z: ln_liq ≈ −4.7 (±1.0), is_qe ≈ +2.1 (±0.8).
- Current-state (panel end): P(ME spike) ≈ 46% (±8pp), P(QE spike) ≈ 74% (±8pp).
- 2026-06-30 print: spike ≈ +6bp vs q50 ≈ +7.2bp (±1.5bp) — sanity check, not proof.
- Bands deliberately loose ("roughly" per requirements); exact prototype numerics asserted tighter once the live panel is captured into the fixture.

## 7. Dependencies
No new packages: statsmodels 0.14.5 (OLS/HAC, Logit, QuantReg), pandas, numpy, QuantLib, pyarrow, requests — all pinned already. DBnomics accessed with plain `requests` (prototype-style), no `dbnomics` package.

## 8. Known risks / open items
- **Barchart expired-contract coverage** back to 2018 for ZQ/SQ/SL is assumed (UST futures basis backfill precedent). If the live backfill shows truncated history, the backtest window shrinks and this is reported — per ground rules, substituting a proxy is out of bounds without sign-off.
- GDP vintages (see Non-goals). Regime dating subjectivity handled via config + sensitivity report.
- Turn risk premium: backtest characterizes (ex-ante premium vs realized turn P&L); no assumption either way.
