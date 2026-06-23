# RVUtils Relative-Value Toolkit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (or executing-plans). Steps use checkbox (`- [ ]`) syntax. Spec: `docs/superpowers/specs/2026-06-22-rv-toolkit-design.md`.

**Goal:** Add a comprehensive, data-agnostic relative-value analytics toolkit to `RVUtils` (new builder modules + extensions to `plt_timeseries.py`/`regression.py`), then 4 USD-rates showcase notebooks.

**Architecture:** Each new module is a **closure-factory builder** (`make_*_builder(...)` returns a tuple of inner functions over a shared `state` dict) mirroring `make_secondary_axis_plot` / `make_linear_regression_builder`. Pure math/stats on pandas DataFrames; no pricing, no data infra. Reuse `mean_reversion.py` (OU) and extend `df_based_pca_risk_model.CurvePCAModel`.

**Tech Stack:** numpy, pandas, scipy (`optimize.least_squares`, `interpolate`, `odr`, `stats`), statsmodels (`OLS`, `adfuller`, `tsa.vector_ar.vecm.coint_johansen`), sklearn (optional `LedoitWolf`). matplotlib + plotly for the indicator extensions.

## Global Constraints
- Python/pytest run **only** under `conda run -n stir` (e.g. `conda run -n stir python -m pytest tests/test_rv_pca.py -v`).
- Data-agnostic: functions take pandas objects; never read files / network / price instruments.
- Builder pattern: factory returns a **tuple of closures** sharing a `state` dict; expose helpers as attributes where useful.
- Units: rates %, spreads/curves/flies bp. Sign: residual>0 ⇒ cheap; carry/roll>0 ⇒ receiver-friendly; fly = `2·belly − w_s·short − w_l·long`.
- Look-ahead safe: rolling/expanding only; expose `window`, `min_obs`, `step`.
- No new third-party deps. New code lives in `RVUtils/`; tests in `tests/`; notebooks in `notebooks/rv/`.
- TDD: failing test → minimal impl → pass → commit. Commit per task on branch `feat/rv-toolkit`.

## Builder-pattern contract (every new module follows this)
```python
def make_<x>_builder(df: pd.DataFrame, *, <config>) -> tuple:
    # validate inputs; coerce datetime index; build `state = {...}`
    def fit(...): ...
    def <verb>(...): ...
    # expose helpers: fit.state = state
    return (fit, <verb>, ..., get_data)
```
Stateless pure helpers (e.g. `roll_down`, `engle_granger`) may also be module-level functions; the builder composes them.

## File structure
- Create: `RVUtils/pca_rv.py`, `RVUtils/curve_fit_rv.py`, `RVUtils/carry_roll.py`, `RVUtils/cointegration.py`, `RVUtils/signal_backtest.py`, `RVUtils/screener_rv.py`
- Modify: `RVUtils/mean_reversion.py`, `RVUtils/df_based_pca_risk_model.py`, `RVUtils/plt_timeseries.py`, `RVUtils/regression.py`
- Tests: `tests/test_rv_mean_reversion.py`, `tests/test_rv_pca.py`, `tests/test_rv_curve_fit.py`, `tests/test_rv_carry_roll.py`, `tests/test_rv_cointegration.py`, `tests/test_rv_signal_backtest.py`, `tests/test_rv_screener.py`, `tests/test_rv_regression_ext.py`
- Notebooks: `notebooks/rv/rv_pca_curve_fly.ipynb`, `rv_statistical_regression_cointegration.ipynb`, `rv_carry_roll_screener.ipynb`, `rv_fitted_curve_and_backtest.ipynb`

---

## Phase 0 — branch
- [ ] `git checkout -b feat/rv-toolkit`

## Task 1 — `mean_reversion.py` extensions (foundation)
**Files:** Modify `RVUtils/mean_reversion.py`; Test `tests/test_rv_mean_reversion.py`
**Produces:**
- `calibrate_ou(series, dt=1.0, demean=False) -> dict{mu,kappa,sigma,phi,intercept,half_life}` — AR(1): regress `x_t` on `x_{t-1}` → `phi`; `kappa=-ln(phi)/dt`; `mu=intercept/(1-phi)`; `half_life=ln2/kappa`; `sigma=sqrt(var(resid)*2kappa/(1-phi^2))`. (Lift from `regression._ou_calibrate`.)
- `ou_conditional(x0, params, horizon) -> {mean,var,std}`: `mean=mu+(x0-mu)e^{-kappa*h}`, `var=sigma^2/(2kappa)*(1-e^{-2kappa*h})`.
- `ou_ex_ante_sharpe(x0, params, horizon, annualize=True, periods=252)`: `(mean-x0)/std`, ×`sqrt(periods/horizon)` if annualize.
- `first_passage_time(x0, target, params, sims=2000, steps=252) -> float` (MC; generalize existing inner MC).
**Tests:** simulate an OU path with known (kappa=0.05→half_life≈13.86, mu=0, sigma); assert `calibrate_ou` recovers half_life within 25%; `ou_conditional` mean decays toward mu; ex-ante Sharpe is finite & sign matches (x0<mu ⇒ positive expected move).
- [ ] failing test → run (fail) → implement → run (pass) → `git commit -m "feat(rv): OU calibration, conditional, ex-ante Sharpe, FPT"`

## Task 2 — `df_based_pca_risk_model.py` helpers (foundation)
**Files:** Modify `RVUtils/df_based_pca_risk_model.py`; Test folded into `tests/test_rv_pca.py`
**Produces (extend `fit_curve_pca_from_timeseries` + `CurvePCAModel`):**
- add `matrix="cov"|"corr"` and `n_factors` to the fit; **pin eigenvector signs** (make the largest-abs loading positive per PC).
- `CurvePCAModel.reconstruct(x, k=None)` → `mu + A_k A_kᵀ (x-mu)`.
- `CurvePCAModel.residual(x, k=None)` → `x - reconstruct(x,k)`.
- `CurvePCAModel.explained_variance()` → eigenvalues/sum.
**Tests:** construct a 3-tenor panel from known loadings; assert recovered loadings (up to sign) and that variance explained sums to 1; `reconstruct` with k=full ≈ identity.
- [ ] TDD cycle → `git commit -m "feat(rv): PCA engine sign-pinning, reconstruct/residual, corr option"`

## Task 3 — `pca_rv.py` (PCA relative value)  *(build inline — exemplar module)*
**Files:** Create `RVUtils/pca_rv.py`; Test `tests/test_rv_pca.py`
**Produces:** `make_pca_rv_builder(df, *, tenors=None, on="levels", matrix="cov", n_factors=3, window=None, sort_by_tenor=True, fixed_loadings_date=None)` → `(fit, fair_value, residual, fly_weights, curve_weights, directionality, risk_buckets, factor_corr_check, get_model)`.
**Formulas:**
- fit: eigh of cov/corr of levels or changes; cumulative reconstruction if `on="changes"`.
- `fly_weights(short, body, long, neutralize=("PC1","PC2"))`: solve `[[e1s,e1l],[e2s,e2l]]·[ws,wl]ᵀ = [-e1b,-e2b]ᵀ`, belly=1. Guard `cond(M)`; warn if PC1≈[-1,0,1].
- `curve_weights(short,long,neutralize=("PC1",))`: `w_s = e1_s/e1_l`.
- `directionality(structure, drivers=("PC1","PC2"), method)`: betas via OLS of structure on PC scores (or level/slope cols); minvar `b*=Σ⁻¹Aᵀ(AΣ⁻¹Aᵀ)⁻¹c`.
- `risk_buckets(dv01_ladder)`: `f = Vᵀ r`.
- `factor_corr_check(weights, window)`: rolling OLS of synthetic trade pnl on PC1 score → β series; flag |β|>tol.
**Tests:** planted-cov panel → `fly_weights` gives `|e1ᵀw|<1e-9` and `|e2ᵀw|<1e-9`; `residual().zscore()` finite; `risk_buckets` of a unit-5y ladder returns PC1≈loading.
- [ ] TDD cycle → `git commit -m "feat(rv): pca_rv builder (fair-value, residual, factor-neutral weights, directionality, risk buckets)"`

## Task 4 — `carry_roll.py`  *(delegable)*
**Files:** Create `RVUtils/carry_roll.py`; Test `tests/test_rv_carry_roll.py`
**Produces (module-level fns + `make_carry_roll_builder`):**
- `roll_down(curve_row, tenor, horizon, interp="cubic") -> bp`: `y(tenor) - y(tenor-horizon)` via interpolation over a tenor→yield Series.
- `forward_rate(curve_row, start, tenor)`: par/zero forward `( (1+s_{S+T})^{S+T}/(1+s_S)^S )^{1/T} - 1` (document approximation).
- `carry(curve_row, tenor, horizon, repo=None)`: forward-decomposition `fwd_yield(tenor-horizon@horizon) - spot_yield(tenor)`; coupon−repo variant if `repo` given.
- `curve_carry_roll(curve_row, t_short, t_long, horizon)` = leg roll difference.
- `fly_carry_roll(curve_row, legs, weights, horizon)` = Σ wᵢ·roll(legᵢ).
- `breakeven(cr, dv01)`, `carry_to_vol(cr, vol)`.
- builder takes a curve-snapshot timeseries DF (cols=tenors yrs) → `(carry, roll, total, breakeven, carry_to_vol_ts)` series over dates.
**Tests:** on a **linear** curve `y(t)=a+b·t`, `roll_down(t,h)=b·h` exactly; `curve_carry_roll`=0 for parallel; `carry_to_vol` = cr/vol.
- [ ] TDD cycle → `git commit -m "feat(rv): carry_roll (roll-down, forward, carry, curve/fly, breakeven, carry-to-vol)"`

## Task 5 — `curve_fit_rv.py`  *(delegable)*
**Files:** Create `RVUtils/curve_fit_rv.py`; Test `tests/test_rv_curve_fit.py`
**Produces:** `make_curve_fit_builder(data, *, x="maturity", y="yield", form="nss", loss="ols", weights=None)` → `(fit, residual, rank, rmse, otr_spread, get_data)`.
**Formulas:**
- NS yield: `y(τ)=β0+β1·(1-e^{-τ/λ})/(τ/λ)+β2·((1-e^{-τ/λ})/(τ/λ)-e^{-τ/λ})`.
- NSS adds `+β3·((1-e^{-τ/λ2})/(τ/λ2)-e^{-τ/λ2})`. Fit via `scipy.optimize.least_squares` (Huber loss for `loss="lad"`).
- `spline`: penalized cubic smoothing (`scipy.interpolate.UnivariateSpline`, smoothing s by GCV-ish heuristic).
- `linear`: `y ~ a + b·duration` (TFP line).
- `residual = y - fitted` (bp), `.zscore(window)` per bond across dates; `rmse=sqrt(mean(resid²))`.
**Tests:** generate yields from planted NSS params → `fit` recovers fitted within 1e-3 and residual≈0; a bond bumped +5bp shows residual≈+5 (cheap) and top rank.
- [ ] TDD cycle → `git commit -m "feat(rv): curve_fit_rv (NS/NSS/spline/linear cross-sectional rich-cheap)"`

## Task 6 — `cointegration.py`  *(delegable)*
**Files:** Create `RVUtils/cointegration.py`; Test `tests/test_rv_cointegration.py`
**Produces:**
- `engle_granger(y, x, hedge="ols"|"tls", trend="c") -> {beta,alpha,spread,adf_stat,pvalue,half_life}` (resid ADF via statsmodels; half_life via `mean_reversion.calibrate_ou`).
- `johansen(df, det_order=0, k_ar_diff=1) -> {trace_stat,eigen_stat,crit_trace,coint_vector,rank}` (`coint_johansen`).
- `spread(y,x,beta)`, `zscore(spread,window)`, `bands(spread,k,window)`.
- optional `kalman_hedge_ratio(y,x)`.
**Tests:** build `y=2x+stationary_noise` with x a random walk → `engle_granger` rejects unit root (pvalue<0.05), beta≈2, half_life finite; independent random walks → pvalue>0.1; Johansen finds rank≥1 for the cointegrated pair.
- [ ] TDD cycle → `git commit -m "feat(rv): cointegration (Engle-Granger, Johansen, spread z-bands, half-life)"`

## Task 7 — `signal_backtest.py`  *(delegable)*
**Files:** Create `RVUtils/signal_backtest.py`; Test `tests/test_rv_signal_backtest.py`
**Produces:** `make_signal_backtest_builder(signal, *, ret=None, ...)` → `(forecast, zscore_signal, position, pnl, stats, ex_ante_sharpe, first_passage, regime_gate, get_data)`.
**Formulas:**
- `forecast(scale=10, cap=20)`: `clip(scale*signal/avg|signal|, -cap, cap)` (Carver).
- `zscore_signal(window, entry, exit, stop)`: position state machine on rolling z.
- `position(method, target_vol, vol_window=36, idm=1.0)`: vol_target `σ_target/σ_realized·forecast/10·idm` (cap idm 2.5); inverse_vol; binary.
- `pnl(cost_bps)`: `position.shift(1)·ret - turnover·cost`; `stats()`: Sharpe `mean/std·√252`, t_stat, hit_rate, max_dd, turnover, avg_hold, sharpe_net.
**Tests:** synthetic mean-reverting spread → zscore strategy has positive Sharpe; `forecast` respects cap; `stats` keys present and max_dd≤0; cost reduces sharpe_net.
- [ ] TDD cycle → `git commit -m "feat(rv): signal_backtest (forecast/zscore signals, sizing, Sharpe/maxDD/turnover, OU ex-ante)"`

## Task 8 — `screener_rv.py`  *(inline; depends on 1,4)*
**Files:** Create `RVUtils/screener_rv.py`; Test `tests/test_rv_screener.py`
**Produces:** `make_rv_screener(structures_df, *, zscore_window=65, vol_window=20, percentile_window=65, halflife_window=120, weights=None, carry_df=None)` → `(build, rank, to_dataframe, rv_dislocation_index, get_data)`. Per-column: level, chg, z, percentile, vol, carry/roll (if carry_df), carry-to-vol, half-life, composite, direction, actionable. `rv_dislocation_index()` = `10D-MA(Σ z₆ₘ²)`.
**Tests:** 3 synthetic structures → `to_dataframe` shape/columns; most-extreme-z ranks first; dislocation index spikes when a structure jumps.
- [ ] TDD cycle → `git commit -m "feat(rv): screener_rv (composite cross-structure rank + dislocation index)"`

## Task 9 — `plt_timeseries.py` extensions  *(inline; shared file)*
**Files:** Modify `RVUtils/plt_timeseries.py`; Test `tests/test_rv_regression_ext.py` (shared) or smoke in `tests/test_rv_plt_ext.py`
**Produces:** new indicator kinds in the `indicators` dispatch: `percentile` (rolling rank), `zbands` (mean±entry/exit σ overlay), `fair_value`/`residual` (overlay supplied series). No changes to existing kinds. Add helper `_percentile(s,w)`. Keep matplotlib+plotly parity.
**Tests:** call `plot(series, indicators=[{"kind":"percentile","window":60,"hide":True}])` builds without error; `_percentile` matches `Series.rolling().rank(pct)`.
- [ ] TDD cycle → `git commit -m "feat(rv): plt_timeseries percentile/zbands/fair_value indicators"`

## Task 10 — `regression.py` extensions  *(inline; shared file)*
**Files:** Modify `RVUtils/regression.py`; Test `tests/test_rv_regression_ext.py`
**Produces (added to the builder return when `window` set, + module fns):**
- `rolling_beta_stability(window_beta=126, window_vol=63, window_z=126) -> DataFrame{TLI, z_per_beta...}`: `TLI=sqrt(Σ_i Z(rolling_std(beta_i))²)`.
- `residual_diagnostics() -> {half_life, adf_pvalue}` on fitted residual.
- module fn `level_curve_neutral_fly(fly, level, slope, window) -> {residual, zscore, betas}`.
**Tests:** stable-beta series → low TLI; regime-break series → TLI spike ≥3; `level_curve_neutral_fly` residual has ~0 corr with level & slope.
- [ ] TDD cycle → `git commit -m "feat(rv): regression beta-stability TLI, residual diagnostics, neutral-fly"`

## Task 11 — Full test sweep
- [ ] `conda run -n stir python -m pytest tests/test_rv_*.py -q` → all pass. Fix failures. Commit any fixes.

## Task 12 — Notebooks (`notebooks/rv/`)  *(inline; execute end-to-end under stir)*
Mirror data plumbing from `notebooks/timeseries/eod_linear_rates.ipynb` (`TimeseriesBuilder`, `UnifiedQuery`, `IRSwapsTB`/`FixedRateBondsTB`, `sys.path.append("../../")`). Date window ≈ 2025-06-01 → 2026-06-17.
- [ ] **N1 `rv_pca_curve_fly.ipynb`**: load SOFR 2/5/10/30 + UST CT2/5/10/30; build 2s5s10s & 5s10s30s; `make_pca_rv_builder` → fair-value, residual z (plotted via `make_secondary_axis_plot`), factor-neutral weights, directionality, risk buckets.
- [ ] **N2 `rv_statistical_regression_cointegration.ipynb`**: regression fair-value (10y20y vs CT10/CT30) + `rolling_beta_stability` TLI + residual OU bands; `cointegration.engle_granger`/`johansen` on a swap-vs-UST pair; z entry/exit + first-passage.
- [ ] **N3 `rv_carry_roll_screener.ipynb`**: build a SOFR curve-snapshot panel; `carry_roll` for curves/flies; `make_rv_screener` composite rank + dislocation index; ING PC1-residual-vs-carry/roll scatter.
- [ ] **N4 `rv_fitted_curve_and_backtest.ipynb`**: UST cross-section (CT2..CT30) → `make_curve_fit_builder` NSS/spline rich/cheap + OTR/old-bond; then `make_signal_backtest_builder` on a fly residual → Sharpe/maxDD/turnover.
- [ ] Execute each: `conda run -n stir jupyter nbconvert --to notebook --execute --inplace notebooks/rv/<nb>.ipynb` (allow long timeout). Fix runtime errors. Commit notebooks.

## Task 13 — Final verification & report
- [ ] Re-run full pytest sweep; confirm 4 notebooks executed with outputs.
- [ ] Summarize results to user (modules, tests passing, notebook headline findings). Offer to push/PR.

---

## Self-review (vs spec)
- Spec §6.1–6.9 → Tasks 1,2,3,5,4,6,7,8,9,10 (all modules covered). ✓
- Notebooks §8 → Task 12 (4 notebooks). ✓
- Testing §9 → per-task synthetic tests + Task 11 sweep + Task 12 execution. ✓
- Non-goals §2 (no pricing/infra) honored: carry needs supplied forwards/repo; curve_fit yield-space only; basis/swap-spread via generic spread/regression (no dedicated pricing module). ✓
- Deps §7: scipy/statsmodels/sklearn only. ✓
- Build order §10 matches Tasks 1→12. ✓
