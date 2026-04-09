# CCP Basis Fair Value Model Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a hybrid multi-factor regression + PCA fair value model for the CME-LCH clearing house basis across the USD swaps curve.

**Architecture:** Per-tenor regression of CCP basis against swap curve PCA scores (PC1=level, PC2=slope, PC3=curvature), FRED-sourced macro factors (funding costs, credit spreads, repo rates), realized rate volatility, and calendar dummies. OU mean-reversion on residuals produces trade signals.

**Tech Stack:** Existing MDP infrastructure (IRClearingHouseBasisSwapsMDP, FredFetcher), RVUtils (PCA, regression, mean_reversion, plotting), statsmodels, numpy, pandas.

---

### Task 1: Create RVUtils/ccp_basis_fair_value.py — Core Model

**Files:**
- Create: `RVUtils/ccp_basis_fair_value.py`

**Step 1: Write the module**

Full implementation of:
- `CCPBasisFairValueResult` dataclass — holds per-tenor regression output
- `CCPBasisFairValueModel` class:
  - `fetch_data()` — fetches CCP basis (all tenors), FRED series (SOFR, EFFR, BGCR, BBB OAS)
  - `build_factors()` — PCA of swap curve, funding/credit spreads, realized vol, calendar dummies
  - `fit(tenor)` — per-tenor OLS regression via `make_linear_regression_builder()`
  - `fit_all()` — iterates tenors
  - `plot_fair_value(result)` — actual vs FV with residual on right axis
  - `plot_residual_zscore(result)` — z-score with ±2σ bands
  - `plot_factor_attribution(result)` — stacked area of factor contributions
  - `summary()` — cross-tenor DataFrame (R², current residual, z-score, OU half-life)

**Factor set:**
1. Swap curve PC1/PC2/PC3 (from `fit_curve_pca_from_timeseries`)
2. SOFR-EFFR spread (funding cost)
3. BGCR-EFFR spread (repo-OIS)
4. BBB Corporate OAS (BAMLC0A4CBBB — dealer credit proxy)
5. Realized rate vol (20d rolling std of daily rate changes)
6. Rate level at tenor
7. Quarter-end dummy (last 5 biz days of Mar/Jun/Sep/Dec)
8. Year-end dummy (last 5 biz days of Dec)

**Step 2: Verify imports resolve**

Run: `cd /path/to/repo && python -c "from RVUtils.ccp_basis_fair_value import CCPBasisFairValueModel; print('OK')"`

**Step 3: Commit**

---

### Task 2: Create notebooks/rv/ccp_basis_rv.ipynb — Entry Point Notebook

**Files:**
- Create: `notebooks/rv/ccp_basis_rv.ipynb`

**Step 1: Write the notebook**

Cells:
1. Standard imports (autoreload, matplotlib, plotly, pandas, numpy, sys.path)
2. Instantiate model: `CCPBasisFairValueModel(tenors=["5Y","10Y","30Y"], start_date, end_date)`
3. `model.fetch_data()` — show raw data shape
4. `model.build_factors()` — show factor matrix, PCA variance explained
5. `results = model.fit_all()` — fit all tenors
6. Per-tenor fair value plots
7. Per-tenor residual z-score plots
8. Cross-tenor summary table
9. Factor attribution for 30Y (most liquid/interesting)
10. Regression coefficient comparison across tenors

**Step 2: Commit**

---

### Task 3: Verify end-to-end

**Step 1:** Run notebook cells to verify data fetching and model fitting work
**Step 2:** Fix any import/API issues
**Step 3:** Final commit
