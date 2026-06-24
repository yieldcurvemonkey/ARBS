# RVUtils v2 — RV Toolkit Additions (BSIC-derived)

**Date:** 2026-06-24
**Status:** Plan / spec for implementation (v1 toolkit already merged to `main`)
**Source research:** 6 BSIC (bsic.it) RV articles (URLs in Appendix), distilled and mapped against the existing toolkit.

## 0. Context for the implementer

`RVUtils/` already contains a **data-agnostic** relative-value toolkit (merged to `main`). Conventions to follow exactly:
- **Data-agnostic:** functions take pandas objects (wide DataFrames, DatetimeIndex; rates %, spreads/curves/flies bp). **No instrument pricing, no file/network IO, no data-infra imports.**
- **Builder pattern:** `make_*_builder(...)` returns a tuple of closures over a shared `state` dict (see `RVUtils/pca_rv.py`, `regression.py`, `plt_timeseries.py`). Stateless math may be module-level functions.
- **Env / tests:** Python + pytest **only** via `conda run -n stir`. Tests in `tests/test_rv_*.py`, synthetic known-answer style.
- Deps already present: numpy, pandas, scipy, statsmodels, sklearn. No new third-party deps.

**Existing modules (do NOT rebuild):** `regression` (OLS/WLS/GLS/TLS/PCR + rolling beta, beta-stability TLI, residual diagnostics, level/curve-neutral fly), `pca_rv` (PCA fair-value/residual, PC1/PC2-neutral fly & curve weights via 2×2 solve, directionality, risk-buckets, `matrix="cov"|"corr"`, `pin_signs`), `mean_reversion` (`calibrate_ou`, `ou_conditional`, `ou_ex_ante_sharpe`, `first_passage_time`, `simulate_mean_reversion_ou`), `carry_roll` (roll-down, forward_rate, carry, curve/fly carry+roll, breakeven, carry-to-vol), `curve_fit_rv` (NS/NSS/spline/linear cross-sectional rich-cheap), `cointegration` (Engle-Granger, Johansen, spread z-bands, half-life), `signal_backtest` (z/Carver-forecast signals, vol-target/inverse-vol sizing, Sharpe/hit/maxDD/turnover/cost, regime gate), `screener_rv` (composite rank + RV dislocation index), `seasonality_utils`, `df_based_pca_risk_model` (`CurvePCAModel`).

**Already covered (verified — flagged as "gaps" by readers but present):** correlation-matrix PCA (`matrix="corr"`), PC1/PC2-neutral fly 2×2 belly-fixed solve (`pca_rv.fly_weights`), AR(1) half-life (`calibrate_ou`), fixed-z entry/exit (`signal_backtest`), EG/Johansen + ADF usage (`cointegration`), carry/roll/carry-to-vol (`carry_roll`).

**Out of scope:** DeltaLag LSTM (not a data-agnostic stat method); forward-OIS par-rate construction from discount factors (data layer — `carry_roll.forward_rate` already derives forwards from a supplied curve).

---

## 1. Tier 1 — high-value new capability

### A. Rolling PCA fair-value / residual + eigenvector continuity  — `pca_rv`
The core RV signal in *Catching the Butterfly* and *PCA-residuals*: re-fit PCA on a rolling window and take the residual. `pca_rv` currently fits once (full-sample or `fixed_loadings_date`); add a rolling path.
- New: `rolling_residual(structure, weights=None, window=261, k=3, sign_align=True)` → residual timeseries `D_t = S_t − Ŝ_t` where `Ŝ_t` uses the trailing-window PCA reconstruction `r̂ = r̄ + Σ_{j≤k} y_j L_j`. Return in input units (×100 for bp at call site).
- New helper `align_eigenvectors(V_new, V_prev, threshold=0.0)`: for each PC column flip sign if `cos(v_new, v_prev) < threshold`; call inside the rolling loop so loadings/scores are continuous across windows (deterministic `pin_signs` is not enough for rolling).
- Acceptance: on a synthetic 3-factor panel, rolling residual ≈ planted idiosyncratic noise; with a sign-flip injected between windows, `align_eigenvectors` keeps the loading sign continuous (no spurious jumps in the residual).
- Params/defaults (BSIC): window 261 bdays, k=3 (>95% var), min leg spacing 1y.

### B. Optimal OU entry/exit bands (Zeng-Lee 2014) — `mean_reversion` (→ `signal_backtest`)
Replace fixed z=2/0.5/4 with cost-aware optimal thresholds maximizing expected P&L per unit time.
- New: `optimal_ou_thresholds(kappa, sigma, cost, case="symmetric"|"long_only", n_terms=50)` → `(a_star, b_star)` (in σ_eq units).
- Objective: `max_{a,b} (a − b − c) / (E[τ₁] + E[τ₂])`. For the standardized OU, expected passage times use the truncated series
  `E(τ) ∝ ½ Σ_{n≥0} [ (√2·a)^{2n+1} − (√2·b)^{2n+1} ] / [ (2n+1)! · Γ((2n+1)/2) ]`.
- Long-only: `b*=0` (∂f/∂b<0), solve `∂f/∂a=0`:
  `½ Σ (√2 a)^{2n+1}/[(2n+1)!Γ((2n+1)/2)] = (a−c)(√2/2) Σ (√2 a)^{2n}/[(2n)!Γ((2n+1)/2)]` via `scipy.optimize.brentq`.
- Symmetric: `b*=−a*`, same FOC with `(a − c/2)`.
- Acceptance: zero cost → wider-than-zero `a*`; higher `cost` ⇒ wider `a*`; thresholds finite/positive; plug into `signal_backtest.zscore_signal(entry=a*, exit=b*)`.

### C. `lead_lag.py` (new module)
Which leg leads → execution timing and choice of dependent variable for hedging.
- `levy_area(x, y, window)` → rolling signed Lévy area `A_t = ½ Σ (x_i Δy_i − y_i Δx_i)` over the window (discrete Itô sum: `0.5*np.sum(x[:-1]*np.diff(y) − y[:-1]*np.diff(x))`). Sign>0 ⇒ x leads y.
- `levy_area_signal(x, y, window=10, theta_entry=1.5, theta_exit=0.5, ep=1, xp=1)` → entry/exit signals with persistence.
- `xcorr_lead_lag(x, y, max_lag)` → lag (in periods) maximizing cross-correlation of changes, + the corr.
- Optional `granger_lead_lag(x, y, max_lag)` via `statsmodels.tsa.stattools.grangercausalitytests` (min p-value lag).
- Acceptance: construct `y_t = x_{t−k} + noise`; `xcorr_lead_lag` recovers lag k; `levy_area` sign matches the lead direction.

## 2. Tier 2 — low-effort signal/screen enhancers

### D. OU S-score — `mean_reversion`
- `ou_sscore(series, window=None, demean=True)` → `s = (X − μ)/σ_eq`, `σ_eq = σ/√(2κ)` from `calibrate_ou` (rolling if `window`). Avellaneda-Lee entry |s|>1.75 / exit |s|<0.75 (defaults documented, not enforced).
- Acceptance: on a planted OU path, `ou_sscore` is ~standardized (unit-ish stationary variance), mean ~0.

### E. ADF gate — `mean_reversion` (wired into `screener_rv`)
- `adf_gate(series, pval=0.10, regression="c")` → bool (True if ADF p < pval). `screener_rv` admits a structure only if gated True (optional flag).
- Acceptance: stationary OU → True; random walk → False.

### F. Eigenportfolio returns — `pca_rv`
- `eigenportfolio_returns(loadings, asset_returns, asset_vols)` → `F_j(t) = Σ_i (v_{ji}/σ_i) R_i(t)` (factor/eigenportfolio return series).
- Acceptance: shapes correct; F orthogonality ≈ holds on synthetic factor data.

### G. Cost-aware composite — `screener_rv`
- Extend `composite_score(...)` (and the screener) with `cost_z` deduction and `lambda_carry` (default 0.5): `score = |level_z| − cost_z + λ·dir·(rolldown/σ_level)`, `dir = −sign(level_z)`. Wire `carry_roll` rolldown in.
- Acceptance: positive carry in the trade direction raises score; cost lowers it; back-compat default `lambda_carry=0`, `cost_z=0` reproduces current ranking.

## 3. Tier 3 — utilities

### H. `cost_model.py` (new)
- `transaction_cost_bps(tenor, fwd_start=0.0)` parameterized bid-ask (default `0.25 + 0.05·min(tenor,30) + 0.04·min(fwd_start,10)`); `structure_cost_bps(legs, weights, fwd_start)` = Σ|w|·leg cost. Feeds `signal_backtest`/`screener_rv`.

### I. Regression feature selection / sub-period — `regression`
- `feature_select="aic"` (stepwise add/drop by AIC) in the builder preprocess; `ols_segment(periods=[(start,end),...])` → per-period coefficients + adj-R² for beta-stability across regimes (swap-spread macro-driver fair value).
- Acceptance: AIC selection drops an irrelevant planted regressor; segmentation returns per-period betas.

## 4. Capstone — integration

### J. `make_pca_fly_rv_screener(...)`
Wire the *Catching the Butterfly* pipeline end-to-end: rolling `pca_rv` residual (A) → `adf_gate` (E) → AR(1) half-life → cost-aware composite (G) with optimal OU bands (B) and `carry_roll` carry. Output a ranked, actionable fly/curve screen. Showcase notebook under `notebooks/rv/` on ~1y EOD SOFR data (mirror `notebooks/rv/rv_pca_curve_fly.ipynb` plumbing).

---

## 5. Build approach
- Branch `feat/rv-toolkit-v2` off `main`. TDD each item (RED→GREEN), synthetic known-answer tests, `conda run -n stir python -m pytest tests/test_rv_*.py -q`. Commit per item. Order: Tier 1 (A,B,C) → Tier 2 (D,E,F,G) → Tier 3 (H,I) → Capstone (J). Final whole-branch review; then merge to `main` on request.
- **Do not touch** the user's pre-existing uncommitted working-tree changes (unrelated MDP/notebooks/cache files).

## Appendix — sources
- https://bsic.it/a-primer-on-swap-spreads/ (swap-spread driver OLS; mostly covered)
- https://bsic.it/fixed-income-trading-unlocking-risk-reduction-with-ols-and-pca-hedging/ (OLS/PCA fly hedge; covered + eigenvector continuity gap)
- https://bsic.it/beyond-traditional-lead-lag-detection-methods/ (Lévy area; DeltaLag out-of-scope)
- https://bsic.it/optimization-methods-for-entry-and-exit-points-in-relative-value-trading/ (Zeng-Lee optimal OU bands)
- https://bsic.it/catching-the-butterfly-a-relative-value-approach-in-ois-curves/ (rolling PCA fly residual + ADF gate + cost-aware score)
- https://bsic.it/19167-2/ = "PCA: Using Mean-Reverting Residuals as Trading Signals" (Avellaneda-Lee S-score, eigenportfolios)
