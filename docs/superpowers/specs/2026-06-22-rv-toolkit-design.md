# RVUtils Relative-Value Analytics Toolkit — Design Spec

**Date:** 2026-06-22
**Status:** Awaiting user review
**Scope:** Enhance `RVUtils` (centered on `plt_timeseries.py` and `regression.py`) into a comprehensive, **data-agnostic** relative-value (RV) analytics toolkit, grounded in 13 practitioner/academic RV sources (see Appendix). Then showcase it with 4 USD-rates notebooks on ~1y of real EOD data.

---

## 1. Goal

Provide the mathematics/statistics/pandas-wrangling behind real-life rates RV trades as reusable **builder** utilities. The toolkit must:

- Operate purely on **pandas DataFrames** (wide, `DatetimeIndex`, descriptive string columns; rates in %, curves/flies/spreads in bp) and cross-sectional snapshots (one date, many bonds: maturity + yield).
- Contain **only** math/stats/dataframe logic — **no instrument pricing, no data infrastructure, no execution**.
- Follow the existing **closure-factory builder pattern**: a config function returns a tuple of inner functions sharing a `state` dict (as in `make_secondary_axis_plot` / `make_linear_regression_builder`).
- Be **self-contained** within RVUtils (reuse `mean_reversion.py`, extend `df_based_pca_risk_model.CurvePCAModel`; **no dependency on `BT.signals`**).

## 2. Scope & Non-Goals

**In scope (new builders + extensions):** PCA RV (fair-value/residual/factor-neutral weights/directionality/risk-buckets), cross-sectional fitted-curve rich/cheap (NS/NSS/spline/linear-in-duration), carry & roll-down (outright/curve/fly, breakeven, carry-to-vol), cointegration/mean-reversion pairs (Engle-Granger/Johansen/OU/half-life), signal→backtest scaffolding (forecast scaling, vol-targeting, Sharpe/hit/maxDD/turnover/costs, regime gating), cross-structure screener/composite rank, and new plot indicators + regression diagnostics.

**Non-goals (explicitly excluded):**
- Instrument pricing: no DV01/duration computation from scratch, no bond/swap/future pricing, no conversion factors / CTD / delivery-option valuation. Where a method needs these (gross/net basis, implied repo, par-curve-from-cashflows), the toolkit consumes a **precomputed** series and only layers statistics on top.
- Data sourcing / caching / vendor adapters (these live in `MDP`/`TB`/`Query`; notebooks use them, the toolkit does not).
- Portfolio MVO / asset-allocation optimization (out of RV scope).
- Live trading / order management.

## 3. Design principles & conventions

- **Builder pattern:** `make_*_builder(...)` returns a tuple of closures over a shared `state` dict; expose helpers as attributes where useful (mirrors `plot.state`, `plot.apply_pipeline`).
- **Inputs:** every public function takes pandas objects; never reads files or hits a network.
- **Units:** rates in %, spreads/curves/flies in bp; functions document and preserve units; bp helpers reuse `plt_timeseries._guess_bp_scale` logic where relevant.
- **Sign conventions:** residual `> 0 ⇒ cheap` (actual > fair); carry/roll positive ⇒ receiver/long-friendly; fly = `2·belly − wing₁ − wing₂` (high ⇒ belly cheap). Documented per function.
- **Look-ahead safety:** all rolling/expanding stats use only past data; rolling estimators expose `window`, `min_obs`, `step`.
- **Reuse:** OU via `mean_reversion.simulate_mean_reversion_ou` + `regression._ou_calibrate`; PCA via extended `CurvePCAModel`; hedge ratios via `arbl_hedge_ratios` and `regression` TLS.

## 4. Data contract

- **Timeseries panel:** wide DF, `DatetimeIndex`, one column per instrument/structure (e.g. `"USD-SOFR-1D 10y OUTRIGHT RATE"`, `"CT10/CT30 CURVE YTM"`).
- **Curve snapshot timeseries (for carry/roll & PCA):** wide DF whose columns are **tenors** (years, float) or parseable tenor labels; rows = dates. A tenor parser (reuse/extend `df_based_pca_risk_model._tenor_to_years`) maps labels→years.
- **Cross-section (for fitted-curve RV):** either a single-date `Series` (index = maturity in years, values = yield) or a (dates × bonds) DF plus a `maturities` mapping and optional `durations`/`dv01` for weighting.

## 5. Module layout

New modules (each a builder, same pattern):
- `RVUtils/pca_rv.py`
- `RVUtils/curve_fit_rv.py`
- `RVUtils/carry_roll.py`
- `RVUtils/cointegration.py`
- `RVUtils/signal_backtest.py`
- `RVUtils/screener_rv.py`

Extended existing modules:
- `RVUtils/mean_reversion.py` (add OU calibration export + ex-ante Sharpe + first-passage helper)
- `RVUtils/plt_timeseries.py` (new indicator kinds)
- `RVUtils/regression.py` (beta-stability TLI + residual diagnostics + level/curve-neutral fly helper)
- `RVUtils/df_based_pca_risk_model.py` (add level/corr options + residual/reconstruction helpers used by `pca_rv`)

## 6. Module specifications

### 6.1 `mean_reversion.py` (extend)
Keep `simulate_mean_reversion_ou`. Add:
- `calibrate_ou(series, dt=1.0, demean=False) -> dict{mu,kappa,sigma,phi,half_life}` (lift `regression._ou_calibrate` to module-level so all modules share one implementation).
- `ou_conditional(x0, params, horizon) -> dict{mean, var, std}` using `E[x_{t+τ}]=μ+(x0−μ)e^{−κτ}`, `Var=σ²/(2κ)(1−e^{−2κτ})`.
- `ou_ex_ante_sharpe(x0, params, horizon, annualize=True)` = expected reversion move / conditional std (Huggins–Schaller; note SR declines with horizon).
- `first_passage_time(x0, target, params, sims, steps)` (generalize the MC inside `simulate_mean_reversion_ou`).
*Sources: RV-Analysis Ch.2; Risk-Premia; existing code.*

### 6.2 `pca_rv.py` (new) — PCA relative value
`make_pca_rv_builder(df, *, tenors=None, on="levels"|"changes", matrix="cov"|"corr", n_factors=3, window=None, sort_by_tenor=True, fixed_loadings_date=None)` → returns:
- `fit()` — eigen-decompose covariance/correlation of levels or changes (`np.linalg.eigh`); **pin eigenvector signs** (belly/largest-loading positive); store loadings, eigenvalues, explained-variance. Reuses/extends `CurvePCAModel`.
- `fair_value(cols=None, k=None)` — reconstruction `x̂ = μ + A_k A_kᵀ(x−μ)`; if `on="changes"`, rebuild **levels by cumulative reconstruction** `ŷ(t)=y(0)+Σ ŷΔ`. Returns fitted DF.
- `residual(col_or_legs, weights=None, k=None)` — `actual − fitted` rich/cheap series (resid>0⇒cheap); chainable `.zscore(window)`, `.percentile(window)`.
- `fly_weights(short, body, long, neutralize=("PC1","PC2"))` — solve the 2×2 system
  `[[e1_s,e1_l],[e2_s,e2_l]]·[w_s,w_l]ᵀ = [−e1_b,−e2_b]ᵀ`, belly=1; **condition-number guard** (warn on near-degenerate PC1≈[−1,0,1]).
- `curve_weights(short, long, neutralize=("PC1",))` — `w = e1_s/e1_l`.
- `directionality(structure, drivers=("PC1","PC2"), method="pca"|"minvar"|"regression")` — betas of a structure to level/slope and the directionally-neutral residual; minvar via `b*=Σ⁻¹Aᵀ(AΣ⁻¹Aᵀ)⁻¹c`.
- `risk_buckets(dv01_ladder)` — PC exposures `f = Vᵀ r`; `reconstruct_ladder(f)`.
- `factor_corr_check(weights, window)` — rolling regression of trade P&L on PC1; flag if `|β|` not →0 (pre-trade gate; raised hit-rate 82→90% in Huggins–Schaller).
- `get_model()`.
*Sources: SSB Principles of PCA; CS PCA Unleashed; Tudor invariant metrics; RV-Analysis Ch.3; quant.SE PCA notes; BofA 2s4s7s; ING/JPM cross-market.*

### 6.3 `curve_fit_rv.py` (new) — cross-sectional fitted-curve rich/cheap
`make_curve_fit_builder(data, *, x="maturity", y="yield", form="nss"|"ns"|"spline"|"linear", loss="ols"|"lad", weights=None)` where `data` is a snapshot Series (maturity→yield) or dates×bonds DF + maturities.
- `fit(date=None)` — NS/NSS via `scipy.optimize.least_squares` (forward+yield closed forms); `spline` via penalized cubic smoothing (`scipy.interpolate`/GCV); `linear` = yield~duration (the Dallas-Fed term-funding-premium line); optional `1/(D·P)` or BPV weights; `loss="lad"` for robustness.
- `residual()` — `yield − fitted` (bp), resid>0⇒cheap; `.zscore(window)` per bond across history.
- `rank(date)` — cross-sectional rich/cheap ranking.
- `rmse()` — fit dispersion (liquidity/dislocation proxy).
- `otr_spread(new, old)` — on-the-run/old-bond spread helper.
*Sources: BofA UST RV primer (NS/NSS/LOESS); JPM par curve (knots, WLS yield-error); Krishnamurthy (OTR/specialness); RV-Analysis Ch.8; Astor Ridge curve-fitting.*
*Note: par-curve-from-cashflows (discount-factor spline) needs cashflows ⇒ out of scope; yield-space NS/NSS/spline/linear are fully data-agnostic and cover the notebooks (CT-yield cross-sections).*

### 6.4 `carry_roll.py` (new) — carry & roll-down
Curve-snapshot input (columns = tenors in years). Functions + `make_carry_roll_builder`:
- `roll_down(curve, tenor, horizon)` = `interp(curve,tenor) − interp(curve,tenor−horizon)` (eq. 2a; cubic/linear interp).
- `forward_rate(curve, start, tenor)` from par/zero (eq. for `NxnY`).
- `carry(curve_or_fwd, tenor, horizon)` via forward decomposition `fwd_yield(T−H) − spot_yield(T)`; or coupon−repo form when a repo series is supplied.
- `curve_carry_roll(curve, t_short, t_long, horizon)` = leg difference (DV01-neutral ⇒ subtract directly).
- `fly_carry_roll(curve, legs, weights, horizon)` = weighted sum of leg roll/carry.
- `breakeven(cr, dv01)` = `cr/dv01`; `carry_to_vol(cr, vol)` = `cr/σ` (annualized).
*Sources: Nordea carry/roll; swapsball ASW carry/roll; Ardea; RV-Analysis; ING (3M fly carry+roll).*
*Note: roll-down needs only the spot curve; carry needs forwards or repo (documented).*

### 6.5 `cointegration.py` (new) — mean-reversion pairs
- `engle_granger(y, x, hedge="ols"|"tls", trend="c") -> {beta, alpha, spread, adf_stat, pvalue, half_life}` (residual ADF via `statsmodels.adfuller`; reuse `arbl_hedge_ratios`).
- `johansen(df, det_order=0, k_ar_diff=1) -> {trace_stat, eigen_stat, crit, coint_vector, rank}` (`statsmodels.tsa.vector_ar.vecm.coint_johansen`).
- `spread(y, x, beta)`, `zscore(spread, window)`, `bands(spread, k)` (`μ±k·σ_OU`).
- `kalman_hedge_ratio(y, x)` — optional dynamic β (state-space).
*Sources: Risk-Premia by Pairs; RV-Analysis Ch.2/4; regression agent.*

### 6.6 `signal_backtest.py` (new) — signal → position → performance
`make_signal_backtest_builder(signal, *, ret=None, ...)`:
- Signal: `zscore_signal(window, entry, exit, stop)` and Carver `forecast(scale=10, cap=20)`; `combine(forecasts, weights, fdm_cap=2.5)` (FDM = `1/√(wᵀΣ_corr w)`).
- Sizing: `position(method="vol_target"|"inverse_vol"|"binary", target_vol, vol_window=36, idm_cap=2.5)`; vol-managed `σ_target/σ_realized` (incl. downside-vol variant).
- P&L: `pnl(cost_bps=...)`; cost speed-limit `max_turnover = 0.13/cost_SR`.
- Stats: `stats() -> {sharpe, t_stat, hit_rate, max_dd, turnover, avg_hold, sharpe_net}`; `ex_ante_sharpe()` (OU) and `first_passage()` (reuse `mean_reversion`).
- `regime_gate(regime_series, allowed)` — Tuckman macro gating (trade only the residual the regime doesn't explain).
*Sources: Carver Systematic Trading; JPM systematic/Sweating-the-small-stuff; Risk-Premia (VMP/dVMP); Tuckman Macro-Awareness; RV-Analysis Ch.2/9.*

### 6.7 `screener_rv.py` (new) — cross-structure ranking
`make_rv_screener(structures_df, *, zscore_window=65, vol_window=20, percentile_window=65, halflife_window=120, weights={...}, carry_df=None)`:
- Per structure column: level, 1d chg, z-score, percentile, realized vol, carry/roll (if `carry_df`), **carry-to-vol (risk-adjusted roll)**, OU half-life, composite score, direction, actionable filter.
- `rank(n)`, `to_dataframe()`, `rv_dislocation_index()` = `10D-MA(Σ_i z₆ₘ(fly_i)²)` across a fly universe.
- Data-agnostic generalization of `STIRRVScreener.compute_composite_score` to arbitrary structures.
*Sources: Astor Ridge process; SC RV-tool ranking; ING RV Dislocation Index; existing `STIRRVScreener`.*

### 6.8 `plt_timeseries.py` (extend) — new indicator kinds
Add to the `indicators=[{kind:...}]` dispatch (consistent with existing `hide`/`style`/legend handling):
- `percentile` (rolling percentile rank), `zbands` (mean ± entry/exit σ overlay), `carry_to_vol` (hidden annotation), `fair_value`/`residual` (overlay a supplied fitted/residual series). No breaking changes to existing kinds.

### 6.9 `regression.py` (extend)
- `rolling_beta_stability(window_beta, window_vol, window_z) -> {TLI, components}` where `TLI=√(Σ_i Z(σ_βi)²)`, gate at TLI≥3.
- `residual_diagnostics()` → half-life + ADF p-value on the fitted residual (OU bands already present).
- `level_curve_neutral_fly(fly, level, slope, window)` — regression-based directionally-neutral fly residual + z (companion to `pca_rv.directionality`).
*Sources: swapsball regression note; JPM EUR beta-stability TLI; Tuckman.*

## 7. Dependencies
All already present in the `stir` env (no new third-party deps): `numpy`, `pandas`, `scipy` (`optimize.least_squares`, `interpolate`, `odr`, `stats`), `statsmodels` (`OLS`, `adfuller`, `tsa.vector_ar.vecm.coint_johansen`), `sklearn` (optional: `LedoitWolf`, `LinearRegression`). Plotly/matplotlib for plotting (already used). Vendored `arbitragelab`/`mlfinlab` are **not** required (kept optional).

## 8. Notebooks (4) — USD rates, ~1y EOD, env `stir`
Mirror `notebooks/timeseries/eod_linear_rates.ipynb` data plumbing (`TimeseriesBuilder` + `UnifiedQuery` + `IRSwapsTB`/`FixedRateBondsTB`); ~2025-06 → 2026-06-17. Proposed files under `notebooks/rv/`:
1. **`rv_pca_curve_fly.ipynb`** — PCA fair-value/residual z, factor-neutral weights, directionality, risk-buckets on SOFR & UST flies (2s5s10s, 5s10s30s) + ranked screen.
2. **`rv_statistical_regression_cointegration.ipynb`** — fair-value vs drivers, rolling beta + **TLI** gate, residual OU bands, Engle-Granger/Johansen pair (e.g. CT10/CT30 vs SOFR 10s30s), half-life, z entry/exit, first-passage.
3. **`rv_carry_roll_screener.ipynb`** — curve/fly carry & roll-down, carry-to-vol, composite screener + RV dislocation index; ING-style PC1-residual-vs-carry/roll "double-alpha" scatter.
4. **`rv_fitted_curve_and_backtest.ipynb`** — NSS/spline UST cross-sectional rich/cheap + OTR/old-bond; then a z→vol-targeted→Sharpe/maxDD/turnover/cost backtest of a fly residual signal.

## 9. Testing & verification
- `pytest` under `conda run -n stir`; new `tests/test_rv_*.py`.
- Unit tests on **synthetic** data with known answers: PCA on a constructed covariance recovers planted loadings/variance; NSS fit recovers planted parameters; OU calibration recovers planted κ/half-life; cointegration detects a constructed cointegrated pair and rejects an independent one; carry/roll on a linear curve equals the analytic slope×horizon; fly weights zero out PC1/PC2 exposure (verify `eᵀw≈0`).
- Notebooks must **execute end-to-end** (papermill/nbconvert) against real cached data and render the headline plots.

## 10. Build sequence
1. `mean_reversion.py` extensions → 2. `df_based_pca_risk_model.py` helpers → 3. `pca_rv.py` → 4. `carry_roll.py` → 5. `curve_fit_rv.py` → 6. `cointegration.py` → 7. `signal_backtest.py` → 8. `screener_rv.py` → 9. `plt_timeseries.py` + `regression.py` extensions → 10. tests → 11. notebooks. Each module ships with its tests before the next.

## 11. Risks & mitigations
- **PCA weight instability / eigenvector sign flips:** pin signs; condition-number guard; offer `fixed_loadings_date` for backtests; default 3-leg PCA on the selected legs (not full curve) for fly weights.
- **Levels vs changes correctness:** explicit `on=` switch; changes→levels via cumulative reconstruction with drift caveat.
- **Look-ahead bias:** rolling-only estimators; tests assert no future leakage.
- **Curve interpolation for roll-down:** configurable interp; require sorted tenor grid.
- **Scope creep into pricing:** functions consume precomputed DV01/basis series; never price.

## Appendix — formula sources (13 documents ingested via markitdown)
RV frameworks: Ardea Swap/Bond/Rates primers; Standard Chartered "RV Tool for Swaps". PCA: SSB *Principles of Principal Components*, CS *PCA Unleashed*, Tudor *Invariant Risk Metrics*, BofA *Long 4s on 2s4s7s*, quant.SE PCA-hedge/neutral-fly/risk-bucketing/directionality notes. Carry/roll: Nordea *Carry & Roll*, swapsball ASW carry/roll. Regression/beta-stability: swapsball *Regression friend-or-foe*, JPM EUR beta-stability, JPM EUR fly note, swapsball seasonality. Systematic: JPM *Sweating the Small Stuff*, JPM *Systematic rule-based*, Carver *Systematic Trading*, Tuckman *Macro-Awareness in RV*. Basis: Burghardt *Treasury Bond Basis*, BofA *Futures basis = cheap options*, CFTC cash-futures basis, JPM *Special Delivery*. Swap spreads: USD 5s30s flattener, JPM *TFP & SOFR swap spreads*, Dallas Fed WP 2613, ICMA repo-swap, Clarus *Voyeur's Delight*. Bond/fitted-curve: Krishnamurthy *bond old-bond spread*, BofA UST RV primer, JPM par curve, JPM UST daily, BofA Rates-Watch-PCA. Books: Huggins & Schaller *Fixed Income RV Analysis 2e*, *Risk Premia by Pairs*. Trade tickets: Astor Ridge trade radars (18 notes), JPM EUR ultra-long fly, JPM JPY 2s5s10s, ING *Deconstructing the EUR curve* + RV trade ideas.
