# SFR Butterfly Mean-Reversion Lab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stress-test mean reversion on SR3 butterflies across every 3m and 6m fly on the
front 16 quarterly contracts, and produce an honest league table plus per-constant-maturity-slot
rules of thumb.

**Architecture:** A data-agnostic panel engine (`RVUtils/MeanRev`) backtests a wide
`date × key` level panel against a wide signal panel, enforcing the honesty rules
structurally; signal families are pure `levels -> signal` functions; grading is shared
verbatim with the SR3 options lab (`RVUtils/SFRRVLab/stats.py`) so both labs are scored by
identical code. Marks are raw SR3 settles, never a fitted curve.

**Tech Stack:** Python 3.11 under `conda run -n stir`; numpy / pandas / scipy /
statsmodels; `arbitragelab` (installed editable at `RVUtils/arbitragelab`); Barchart EOD
via `MDP/STIRFutures/STIRFutureMDP.py`; notebooks built from `# %%` sources by
`notebooks/backtests/_py2nb.py`.

## Global Constraints

- Python and pytest run **only** via `conda run -n stir` from the repo root.
- Fast gate before every commit:
  `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.
- Fly sign convention is `2*belly - front - back` in bp, matching the Query layer's
  `FLY RATE`. `BT/signals/sfr_cal_spread_rv.py::compute_fly_curve` is the opposite sign and
  must not be imported.
- Costs: 0.25bp one-way per futures leg. Round trip 1.5bp on a 3-leg fly, 1.0bp on a
  2-leg spread, 0.5bp on an outright. Headline scenarios 0.0 / 1.5 / 2.5bp.
- Sizing: 1 package = 4 contracts = $25/bp. League table uses 100 packages = $2,500/bp.
- `RVUtils/` is a namespace package with no `__init__.py` at the top level; import as
  `from RVUtils.<mod> import ...` from the repo root.
- New toolkit code must be data-agnostic: pandas in, pandas out, no IO, no provider imports.
- Notebooks execute with CWD = `notebooks/backtests`; sources use
  `sys.path.append("../../")` and the negative Agg guard
  (`if "ipykernel" not in sys.modules: matplotlib.use("Agg")`).
- `conda run` buffers stdout: every long-running script prints with `flush=True` and writes
  a progress file.

---

### Task 1: SR3 contract panel

**Files:**
- Create: `notebooks/rv/build_sfr_fly_panel.py`
- Output: `notebooks/data/sfr_fly_meanrev/{parts/*.parquet, contracts.parquet, build_log.txt}`

**Interfaces:**
- Produces: `contracts.parquet` with columns
  `as_of, code, settle, rate_pct, volume, open_interest, imm_start, imm_end`.

- [ ] **Step 1: Probe the feed before building.** Confirm `fixed_rate` units, the fly sign
  against the Query layer, and how far the history goes. Do not skip: the equivalent file in
  `notebooks/backtests/SFR_screeners/_curve_panel.py:93` scales `fixed_rate` as if it were a
  decimal when it is a percent, so its `bf_bps` is 100x too large.
- [ ] **Step 2: One EOD history request per contract symbol.** `SR3<MonYY>` maps to Barchart
  `SQ<MonYY>` via `MDP.STIRFutures.STIRFutureMDP._to_barchart_symbol`. Use
  `bcf.barchart_timeseries_api(barchart_symbols=..., start_date=..., end_date=...,
  interval=None, one_df=True, merge_val_col=col)` once per value column
  (`Close`, `Volume`, `Open Interest`). ~56 symbols is ~3 requests each, not 56 x 2000.
- [ ] **Step 3: Checkpoint per symbol** to `parts/<SYM>.parquet` and skip existing on re-run.
- [ ] **Step 4: Merge** to `contracts.parquet` with `rate_pct = 100 - settle`.
- [ ] **Step 5: Audit coverage and liquidity** (`notebooks/rv/_audit_sfr_panel.py`): per
  year x strip slot, median open interest, share of zero-volume days, share of stale
  settles. This is what fixes the sample windows; do not choose them by taste.
- [ ] **Step 6: Commit.**

```bash
git add notebooks/rv/build_sfr_fly_panel.py notebooks/rv/_audit_sfr_panel.py
git commit -m "feat(rv): SR3 contract panel from raw settles, checkpointed per symbol"
```

---

### Task 2: Mean-reversion core in `RVUtils/mean_reversion.py`

**Files:**
- Modify: `RVUtils/mean_reversion.py`
- Modify: `RVUtils/plt_timeseries.py` (delegate `_hurst_exponent`, `_ou_calibrate`)
- Modify: `RVUtils/FlyVsVol/screener.py` (delegate `series_half_life`)
- Test: `tests/test_rv_meanrev_core.py`, `tests/test_rv_ou_optimal.py`

**Interfaces:**
- Produces: `half_life(series, *, dt=1.0) -> float`;
  `rolling_ar1(series, window, *, min_periods=None, dt=1.0) -> DataFrame[phi, intercept, mu,
  kappa, half_life, sigma, sigma_eq, n_obs]`;
  `rolling_half_life(series, window=120, ...) -> Series`;
  `rolling_zscore(series, window, *, min_periods=None, ddof=0, exclude_current=False) -> Series`;
  `hurst_exponent(series, *, max_lag=100, min_lag=2, method="std"|"rs") -> float`;
  `rolling_hurst(series, window=252, *, max_lag=20, method="std", step=1) -> Series`;
  `variance_ratio(series, k=5, *, on_changes=True) -> float`;
  `variance_ratio_stat(series, k=5, *, heteroskedastic=True) -> dict[vr, z, pvalue, n]`;
  `ou_mle(series, *, dt=1.0) -> dict`;
  `expected_passage_time(a, m, *, kappa=1.0, n_terms=None) -> float`;
  `ou_band_levels(params, cost, case="symmetric", n_terms=50) -> dict`;
  `bertram_thresholds(params, cost, ...) -> dict`;
  `kalman_local_level(series, *, q=1e-4, r=1.0, p0=None) -> DataFrame[prior, filtered,
  pred_var, innovation, z]`;
  `kalman_hedge_ratio(y, X, *, delta=1e-4, r=1e-3, add_constant=True) -> DataFrame`;
  `adf_pvalue(series, regression="c") -> float`.

- [ ] **Step 1: Write the failing test for the first-passage series.** The shipped
  `optimal_ou_thresholds` puts `Gamma(k/2)` in the DENOMINATOR. Settle it by Monte Carlo on
  the standardised OU `dz = -z dt + sqrt(2) dW` before writing any code.

```python
def test_expected_passage_time_matches_monte_carlo():
    assert expected_passage_time(-1.0, 1.0, kappa=1.0) == pytest.approx(2.995, abs=0.05)
    assert expected_passage_time(-2.0, 2.0, kappa=1.0) == pytest.approx(11.854, abs=0.15)
```

- [ ] **Step 2: Run it — expect FAIL** (`expected_passage_time` does not exist).
- [ ] **Step 3: Implement the passage series in log space** with `scipy.special.gammaln` and
  an adaptive term count. Terms peak near `k = 2*z**2` and only then decay, so a fixed
  50-term truncation under-sums beyond |z| ~ 3. Do **not** break the loop on a single
  negligible term: for a symmetric band every even term is exactly zero and an early break
  truncates the series at `k = 6`.
- [ ] **Step 4: Fix `optimal_ou_thresholds`.** FOC of `max_a (a - c_eff)/T(a)` is
  `T(a) - (a - c_eff) T'(a) = 0` with `c_eff = c` (long-only) or `c/2` (symmetric). At zero
  cost the objective is maximised as the band width goes to zero, so return `a* = 0.0`
  rather than the old fallback constant `1.0`, which sat above the solved value at cost 0.01
  and broke monotonicity.
- [ ] **Step 5: Update `tests/test_rv_ou_optimal.py`.** Two existing tests
  (`test_zero_cost_gives_positive_threshold`, `test_thresholds_finite_and_positive_entry`)
  pass only because of that fallback and must be rewritten to assert the corrected
  behaviour plus monotonicity in cost.
- [ ] **Step 6: Add the remaining estimators with known-answer tests.** Hurst must read
  ~0.5 on a random walk (the `plt_timeseries` version returned `2 * slope` and measured
  1.035); R/S operates on increments, not levels; the variance-ratio denominator
  `m = q(n-q+1)(1-q/n)` already carries `q`, so the ratio is `varq/var1`, not
  `varq/(q*var1)`.
- [ ] **Step 7: `rolling_ar1` must equal `calibrate_ou` on the same slice.** Use ddof=1 on
  the residuals to match, and gate `min_periods` on usable **pairs** — a naive `rolling(w)`
  fit at bar `w-1` silently uses `w-1` pairs.
- [ ] **Step 8: Delegate the duplicates** and pin each caller's sentinel under test
  (`FlyVsVol.series_half_life` returns `inf`, not NaN, for non-reverting).
- [ ] **Step 9: Run the full RV suite.**

```bash
conda run -n stir python -m pytest tests/ -k "rv_" -q -m "not slow and not network and not db"
```

- [ ] **Step 10: Commit.**

---

### Task 3: `RVUtils/MeanRev` package

**Files:**
- Create: `RVUtils/MeanRev/{__init__,panel,engine,signals,shadow}.py`
- Test: `tests/test_meanrev_engine.py`

**Interfaces:**
- Consumes: Task 2's estimators.
- Produces: `MRConfig`, `MRResult`, `run_backtest(config, *, levels, signal, gate=None)`,
  `run_continuous(...)`, `grid_search(param_grid, *, levels, signal, gate, base, signal_fn)`,
  `add_strip_slots`, `enumerate_structures`, `structure_liquidity`, `pivot_levels`,
  `regime_tag`, `cm_label`, `shadow_levels`, `shadow_table`, and the signal family functions.
  `MRResult` carries `config/trades/daily_bp/metrics`, matching
  `RVUtils.SFRRVLab.engine.LabResult` so `SFRRVLab.stats` consumes it unchanged.

- [ ] **Step 1: Write the execution-mechanics tests first.** Each encodes a rule that was a
  bug in the prior lab:

```python
def test_fixed_horizon_exit_is_not_lagged_twice():
    lv = frame([0, 0, 0, 10, 11, 12, 13, 14, 15, 16])
    sg = frame([0, 0, 3, 0, 0, 0, 0, 0, 0, 0])
    cfg = MRConfig(direction="momentum", entry_z=2.0, exit_style="t3", lag=1,
                   round_trip_cost_bp=0.0, max_hold=99)
    t = run_backtest(cfg, levels=lv, signal=sg).trades.iloc[0]
    assert t["entry"] == DATES[3] and t["exit"] == DATES[6] and t["days"] == 3
```

  plus: lag-1 entry, cost charged once in both the trade row and the daily series, gates
  blocking entry but never forcing an exit, `direction` sign, stop-loss, max-hold, and a
  look-ahead test that perturbs the tail of the panel and asserts early trades are unchanged.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement `engine.py`.** Per-key numpy loop. A deterministic exit
  (`time`, `max_hold`, `eod`, `stop_loss`) fills on the bar; a signal-driven exit costs a
  lag day.
- [ ] **Step 4: Implement `panel.py`.** `add_strip_slots` must drop contracts whose
  reference quarter has already started, so slot 1 is the front contract that is not yet
  accruing. `enumerate_structures` keys on the **absolute** contract triple and attaches
  CM slot / label / pack as reporting tags.
- [ ] **Step 5: Implement `signals.py`** — z-score, Bollinger, OU S-score, Kalman,
  cross-sectional, PCA residual (one eigendecomposition per date, sign-aligned), curve-fit
  residual, rolling-EG spread.
- [ ] **Step 6: Implement `shadow.py`.** Assert in a test that
  `fly == belly_vs_front + belly_vs_back` exactly, and that each instrument is charged its
  own leg count.
- [ ] **Step 7: Test interop** — `SFRRVLab.stats.grid_distribution/verdict/cost_curve`
  must consume an `MRResult` unmodified.
- [ ] **Step 8: Profile before optimising** (`notebooks/rv/_profile_meanrev.py`) and record
  the measured speedup in the docstring.
- [ ] **Step 9: Run tests, commit.**

---

### Task 4: Structure panels

**Files:**
- Create: `notebooks/rv/build_sfr_fly_structures.py`
- Output: `structures_3m.parquet`, `structures_6m.parquet`, `structures_6m_asym.parquet`,
  `slot_panel.parquet`, `panel_audit.txt`

- [ ] **Step 1: Build 3m (spacing 1) and 6m (spacing 2) panels** to slot 16.
- [ ] **Step 2: Attach min-across-legs liquidity, days-to-front-accrual, and regime.**
- [ ] **Step 3: Build the asymmetric `(i, i+2, i+3)` ablation** and report it without
  trading it — it is not a `1/-2/1` package.
- [ ] **Step 4: Verify the fly sign against the Query layer's `FLY RATE`** on real dates and
  fail loudly on a sign mismatch.
- [ ] **Step 5: Commit.**

---

### Task 5: Framework notebooks

**Files:**
- Create: `notebooks/backtests/sfr_fly_meanrev_common.py`
- Create: `notebooks/backtests/sfr_fly_meanrev_{zscore,ou,coint,pca,kalman,curvefit,
  xsection,regime,arblab,summary}.py`, `sfr_fly_rules_of_thumb.py`
- Create: `notebooks/backtests/run_sfr_fly_meanrev.py`

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces: `load_lab(structure, window)`, `run_family(...)`, `league_row(...)`,
  `regime_block(...)`, `shadow_block(...)`, `per_slot_table(...)`, and
  `league_table.csv` / `sign_tests.csv` / `regime_splits.csv` / `shadow_tests.csv` /
  `rules_of_thumb.csv`.

- [ ] **Step 1: Write `sfr_fly_meanrev_common.py`** mirroring `sfr_rv_lab_common.py` block
  for block. Note the CM label of a key **rolls**: assigning one label per key tags every
  key with the slot it was born at. Attribute trades by `(entry date, key)`.
- [ ] **Step 2: Fix the sample windows from the audit**, not from taste:
  `liquid16` = 2022+ all 16 slots, `front8` = 2019+ slots 1-8.
- [ ] **Step 3: One notebook per method family.** Each: config block, coverage, grid
  distribution before top rows, neighbourhood stability, sign test, header stats, 3-panel
  equity, trade log, exit comparison, cost curve, regime split, linear-shadow
  decomposition, median-config control, league rows.
- [ ] **Step 4: Validate each source as a plain script first** (`--as-scripts`) — far faster
  to iterate than nbconvert.
- [ ] **Step 5: Convert, execute, verify.**

```bash
conda run -n stir python notebooks/backtests/run_sfr_fly_meanrev.py --reset-league
```

- [ ] **Step 6: Confirm zero cell errors and zero unrun cells** via `_verify_nb.py`.
- [ ] **Step 7: Commit.**

---

### Task 6: Findings, tests, PR

- [ ] **Step 1: Write `docs/superpowers/specs/2026-07-29-sfr-fly-meanrev-findings.md`** —
  the league table, the structural results that hold regardless of strategy choice, the bug
  log, and what to test next.
- [ ] **Step 2: Run the fast gate.**

```bash
conda run -n stir python -m pytest tests -m "not slow and not network and not db"
```

- [ ] **Step 3: Commit and open the PR.**
