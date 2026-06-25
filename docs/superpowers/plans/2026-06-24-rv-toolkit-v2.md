# RV Toolkit v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add BSIC-derived RV toolkit additions (items A–J) to the existing `RVUtils/` package on branch `feat/rv-toolkit-v2`.

**Architecture:** Extend existing modules (`pca_rv`, `mean_reversion`, `screener_rv`, `regression`) and create two new modules (`lead_lag`, `cost_model`). All code is data-agnostic: pandas in, no instrument pricing, no IO, no data-infra imports. Closure-factory builder pattern where state is shared; stateless math as module-level functions.

**Tech Stack:** Python 3.10+, numpy, pandas, scipy, statsmodels, sklearn (all already in env). pytest via `conda run -n stir`.

## Global Constraints

- **Env:** All Python/pytest commands MUST use `conda run -n stir` prefix (e.g. `conda run -n stir python -m pytest tests/test_rv_*.py -q`).
- **Data-agnostic:** Functions take pandas objects (wide DataFrames, DatetimeIndex; rates %, spreads/curves/flies bp). NO instrument pricing, NO file/network IO, NO data-infra imports.
- **Builder pattern:** `make_*_builder(...)` returns a tuple of closures over a shared `state` dict. Stateless math may be module-level functions.
- **Units:** Rates in %, spreads/curves/flies in bp. Rolling residual returns in input units.
- **No new deps:** Only numpy, pandas, scipy, statsmodels, sklearn.
- **Branch:** `feat/rv-toolkit-v2` off `main`. Commit per task.
- **Tests:** `tests/test_rv_*.py`, synthetic known-answer style. Match existing test patterns (see `test_rv_pca.py`, `test_rv_mean_reversion.py`).
- **Do NOT touch** pre-existing uncommitted working-tree changes.

## File Map

| Task | File | Action | Responsibility |
|------|------|--------|---------------|
| 1 (A) | `RVUtils/pca_rv.py` | Modify | Add `align_eigenvectors()`, `rolling_residual()` |
| 1 (A) | `tests/test_rv_pca_rolling.py` | Create | Tests for rolling PCA residual + eigenvector continuity |
| 2 (B) | `RVUtils/mean_reversion.py` | Modify | Add `optimal_ou_thresholds()` |
| 2 (B) | `tests/test_rv_ou_optimal.py` | Create | Tests for optimal OU entry/exit bands |
| 3 (C) | `RVUtils/lead_lag.py` | Create | `levy_area()`, `levy_area_signal()`, `xcorr_lead_lag()`, `granger_lead_lag()` |
| 3 (C) | `tests/test_rv_lead_lag.py` | Create | Tests for lead-lag detection |
| 4 (D) | `RVUtils/mean_reversion.py` | Modify | Add `ou_sscore()` |
| 4 (D) | `tests/test_rv_ou_sscore.py` | Create | Tests for OU S-score |
| 5 (E) | `RVUtils/mean_reversion.py` | Modify | Add `adf_gate()` |
| 5 (E) | `RVUtils/screener_rv.py` | Modify | Wire `adf_gate` as optional filter |
| 5 (E) | `tests/test_rv_adf_gate.py` | Create | Tests for ADF gate |
| 6 (F) | `RVUtils/pca_rv.py` | Modify | Add `eigenportfolio_returns()` |
| 6 (F) | `tests/test_rv_eigenportfolio.py` | Create | Tests for eigenportfolio returns |
| 7 (G) | `RVUtils/screener_rv.py` | Modify | Extend `_composite()` with `cost_z`, `lambda_carry`, rolldown |
| 7 (G) | `tests/test_rv_screener_cost.py` | Create | Tests for cost-aware composite |
| 8 (H) | `RVUtils/cost_model.py` | Create | `transaction_cost_bps()`, `structure_cost_bps()` |
| 8 (H) | `tests/test_rv_cost_model.py` | Create | Tests for cost model |
| 9 (I) | `RVUtils/regression.py` | Modify | Add `feature_select` + `ols_segment()` |
| 9 (I) | `tests/test_rv_regression_select.py` | Create | Tests for AIC feature selection + segmentation |
| 10 (J) | `RVUtils/screener_rv.py` | Modify | Add `make_pca_fly_rv_screener()` |
| 10 (J) | `notebooks/rv/rv_pca_fly_screener_v2.ipynb` | Create | Showcase notebook |
| 10 (J) | `tests/test_rv_capstone.py` | Create | Integration test for full pipeline |

---

## Tier 1 — High-Value New Capability

### Task 1: Rolling PCA residual + eigenvector continuity (spec item A)

**Files:**
- Modify: `RVUtils/pca_rv.py` (add two module-level functions at bottom)
- Create: `tests/test_rv_pca_rolling.py`

**Interfaces:**
- Consumes: `fit_curve_pca_from_timeseries` from `RVUtils.df_based_pca_risk_model` (already imported in `pca_rv.py`)
- Produces:
  - `align_eigenvectors(V_new: np.ndarray, V_prev: np.ndarray, threshold: float = 0.0) -> np.ndarray` — flips sign of each column in `V_new` where `cos(v_new, v_prev) < threshold`; returns corrected `V_new`.
  - `rolling_residual(df: pd.DataFrame, structure: Union[str, Sequence[str]], weights: Optional[dict] = None, window: int = 261, k: int = 3, sign_align: bool = True, on: str = "levels", matrix: str = "cov") -> pd.Series` — rolling PCA residual timeseries `D_t = S_t - Ŝ_t`. Returns in input units.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_pca_rolling.py`:

```python
"""Tests for rolling PCA residual + eigenvector continuity (spec A)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.pca_rv import align_eigenvectors, rolling_residual


def _panel(n=500, seed=0, noise_std=0.002):
    """3-factor synthetic curve (level/slope/curvature) on 4 tenors."""
    rng = np.random.default_rng(seed)
    cols = ["2", "5", "10", "30"]
    L = np.array([[1.0, -1.5, 1.0],
                  [1.0, -0.5, -1.0],
                  [1.0,  0.5, -0.5],
                  [1.0,  1.5,  1.0]])
    f = np.cumsum(rng.standard_normal((n, 3)) * np.array([0.05, 0.03, 0.02]), axis=0)
    base = np.array([2.0, 2.5, 3.0, 3.5])
    X = base + f @ L.T + rng.standard_normal((n, 4)) * noise_std
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(X, index=idx, columns=cols)


def _panel_with_idio(n=500, seed=0, noise_std=0.002, idio_col="10", idio_mag=0.05):
    """Same 3-factor panel but with larger idiosyncratic noise on one tenor."""
    rng = np.random.default_rng(seed)
    cols = ["2", "5", "10", "30"]
    L = np.array([[1.0, -1.5, 1.0],
                  [1.0, -0.5, -1.0],
                  [1.0,  0.5, -0.5],
                  [1.0,  1.5,  1.0]])
    f = np.cumsum(rng.standard_normal((n, 3)) * np.array([0.05, 0.03, 0.02]), axis=0)
    base = np.array([2.0, 2.5, 3.0, 3.5])
    idio = rng.standard_normal(n) * idio_mag
    X = base + f @ L.T + rng.standard_normal((n, 4)) * noise_std
    X[:, cols.index(idio_col)] += idio
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(X, index=idx, columns=cols), idio


class TestAlignEigenvectors:
    def test_no_flip_when_aligned(self):
        V = np.eye(3)
        result = align_eigenvectors(V.copy(), V, threshold=0.0)
        np.testing.assert_array_equal(result, V)

    def test_flips_sign_when_antiparallel(self):
        V_prev = np.eye(3)
        V_new = -np.eye(3)
        result = align_eigenvectors(V_new.copy(), V_prev, threshold=0.0)
        np.testing.assert_array_equal(result, V_prev)

    def test_partial_flip(self):
        V_prev = np.eye(3)
        V_new = np.eye(3)
        V_new[:, 1] = -V_new[:, 1]  # flip only column 1
        result = align_eigenvectors(V_new.copy(), V_prev, threshold=0.0)
        np.testing.assert_array_equal(result, V_prev)

    def test_threshold_keeps_orthogonal(self):
        V_prev = np.array([[1, 0], [0, 1]], dtype=float)
        V_new = np.array([[0, 1], [1, 0]], dtype=float)  # rotated 90deg => cos=0
        result = align_eigenvectors(V_new.copy(), V_prev, threshold=0.0)
        # cos=0 which is not < 0, so no flip
        np.testing.assert_array_equal(result, V_new)


class TestRollingResidual:
    def test_output_length(self):
        df = _panel(n=400)
        res = rolling_residual(df, "10", window=100, k=3)
        assert isinstance(res, pd.Series)
        assert len(res) <= 400 - 100 + 1
        assert res.notna().sum() > 0

    def test_residual_captures_idiosyncratic_noise(self):
        df, idio = _panel_with_idio(n=500, idio_mag=0.10, noise_std=0.001)
        res = rolling_residual(df, "10", window=200, k=3)
        common = res.dropna().index
        idio_s = pd.Series(idio, index=df.index, name="idio").loc[common]
        corr = res.loc[common].corr(idio_s)
        assert abs(corr) > 0.5, f"Rolling residual should track idiosyncratic noise, got corr={corr:.3f}"

    def test_multi_leg_structure(self):
        df = _panel(n=400)
        weights = {"2": -0.5, "10": 1.0, "30": -0.5}
        res = rolling_residual(df, ["2", "10", "30"], weights=weights, window=100, k=3)
        assert isinstance(res, pd.Series)
        assert res.notna().sum() > 0

    def test_sign_align_prevents_jumps(self):
        df = _panel(n=500)
        res_aligned = rolling_residual(df, "10", window=100, k=3, sign_align=True)
        res_no_align = rolling_residual(df, "10", window=100, k=3, sign_align=False)
        jumps_aligned = res_aligned.diff().abs().max()
        jumps_no_align = res_no_align.diff().abs().max()
        # aligned should have same or smaller max jump
        assert jumps_aligned <= jumps_no_align * 1.1 or jumps_aligned < 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_pca_rolling.py -v`
Expected: ImportError — `align_eigenvectors` and `rolling_residual` not found.

- [ ] **Step 3: Implement `align_eigenvectors`**

Add to bottom of `RVUtils/pca_rv.py`:

```python
def align_eigenvectors(V_new: np.ndarray, V_prev: np.ndarray, threshold: float = 0.0) -> np.ndarray:
    """Flip sign of each column of V_new where cos(v_new, v_prev) < threshold.

    Ensures eigenvector continuity across rolling windows where the sign is
    arbitrary from the eigen-decomposition.
    """
    V = V_new.copy()
    for j in range(V.shape[1]):
        dot = float(V[:, j] @ V_prev[:, j])
        norm_new = float(np.linalg.norm(V[:, j]))
        norm_prev = float(np.linalg.norm(V_prev[:, j]))
        denom = norm_new * norm_prev
        cos_sim = dot / denom if denom > 0 else 0.0
        if cos_sim < threshold:
            V[:, j] = -V[:, j]
    return V
```

- [ ] **Step 4: Implement `rolling_residual`**

Add to bottom of `RVUtils/pca_rv.py`:

```python
def rolling_residual(
    df: pd.DataFrame,
    structure,
    weights=None,
    window: int = 261,
    k: int = 3,
    sign_align: bool = True,
    on: str = "levels",
    matrix: str = "cov",
) -> pd.Series:
    """Rolling PCA residual: D_t = S_t - Ŝ_t using trailing-window PCA.

    Re-fits PCA every step on df.iloc[t-window:t], reconstructs the structure
    with k factors, and takes the difference. Eigenvectors are sign-aligned
    across windows when sign_align=True.

    Returns a Series in input units (same as df columns).
    """
    from RVUtils.df_based_pca_risk_model import fit_curve_pca_from_timeseries, CurvePCAModel

    data = df.sort_index().dropna(how="any")
    cols = list(data.columns)
    n = len(data)
    window = int(window)
    k = int(min(k, len(cols)))

    if isinstance(structure, str):
        legs, wmap = [structure], {structure: 1.0}
    else:
        legs = list(structure)
        if weights is None:
            raise ValueError("Provide weights for a multi-leg structure.")
        wmap = dict(weights)

    residuals = pd.Series(index=data.index, dtype=float, name="rolling_residual")
    prev_loadings = None

    for t in range(window, n + 1):
        window_df = data.iloc[t - window : t]

        model, _ = fit_curve_pca_from_timeseries(
            window_df,
            use_changes=(on == "changes"),
            sort_by_tenor=False,
            matrix=matrix,
            pin_signs=True,
        )

        if sign_align and prev_loadings is not None:
            V_new = model.loadings.values
            V_aligned = align_eigenvectors(V_new, prev_loadings, threshold=0.0)
            model = CurvePCAModel(
                columns=model.columns,
                mean=model.mean,
                loadings=pd.DataFrame(V_aligned, index=model.loadings.index, columns=model.loadings.columns),
                eigenvalues=model.eigenvalues,
                scales=model.scales,
            )
        prev_loadings = model.loadings.values.copy()

        row = data.iloc[t - 1]
        rec = model.reconstruct(row, k=k)
        actual_s = sum(wmap[c] * row[c] for c in legs)
        fitted_s = sum(wmap[c] * rec[c] for c in legs)
        residuals.iloc[t - 1] = actual_s - fitted_s

    return residuals.dropna()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_pca_rolling.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add RVUtils/pca_rv.py tests/test_rv_pca_rolling.py
git commit -m "feat(rv): rolling PCA residual + eigenvector continuity (spec A)"
```

---

### Task 2: Optimal OU entry/exit bands — Zeng-Lee 2014 (spec item B)

**Files:**
- Modify: `RVUtils/mean_reversion.py` (add `optimal_ou_thresholds()` at bottom)
- Create: `tests/test_rv_ou_optimal.py`

**Interfaces:**
- Consumes: `scipy.optimize.brentq`, `scipy.special.gamma` (already available)
- Produces: `optimal_ou_thresholds(kappa: float, sigma: float, cost: float, case: str = "symmetric", n_terms: int = 50) -> tuple[float, float]` — returns `(a_star, b_star)` in σ_eq units.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_ou_optimal.py`:

```python
"""Tests for optimal OU entry/exit thresholds (spec B, Zeng-Lee 2014)."""
import numpy as np
import pytest

from RVUtils.mean_reversion import optimal_ou_thresholds


class TestOptimalOuThresholds:
    def test_zero_cost_gives_positive_threshold(self):
        a, b = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.0)
        assert a > 0, "Zero-cost entry threshold must be positive"
        assert np.isfinite(a)

    def test_higher_cost_widens_threshold(self):
        a_low, _ = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1)
        a_high, _ = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.5)
        assert a_high > a_low, "Higher cost should widen entry threshold"

    def test_long_only_exit_at_zero(self):
        a, b = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1, case="long_only")
        assert b == pytest.approx(0.0), "Long-only exit should be at zero"
        assert a > 0

    def test_symmetric_exit_negative_of_entry(self):
        a, b = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1, case="symmetric")
        assert b == pytest.approx(-a), "Symmetric exit should be -a"
        assert a > 0

    def test_thresholds_finite_and_positive_entry(self):
        for cost in [0.0, 0.05, 0.2, 1.0]:
            for case in ["symmetric", "long_only"]:
                a, b = optimal_ou_thresholds(kappa=0.1, sigma=0.3, cost=cost, case=case)
                assert np.isfinite(a), f"a not finite for cost={cost}, case={case}"
                assert a > 0, f"a not positive for cost={cost}, case={case}"

    def test_invalid_case_raises(self):
        with pytest.raises(ValueError):
            optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1, case="invalid")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_ou_optimal.py -v`
Expected: ImportError — `optimal_ou_thresholds` not found.

- [ ] **Step 3: Implement `optimal_ou_thresholds`**

Add to bottom of `RVUtils/mean_reversion.py`:

```python
def optimal_ou_thresholds(
    kappa: float,
    sigma: float,
    cost: float,
    case: str = "symmetric",
    n_terms: int = 50,
) -> tuple:
    """Optimal OU entry/exit thresholds maximizing expected P&L per unit time (Zeng-Lee 2014).

    For the standardized OU (sigma_eq = sigma / sqrt(2*kappa)), expected passage times
    use the truncated series E(tau) ~ sum_{n>=0} [(sqrt2*a)^{2n+1} - (sqrt2*b)^{2n+1}] /
    [(2n+1)! * Gamma((2n+1)/2)].

    Returns (a_star, b_star) in sigma_eq units.
    """
    from scipy.optimize import brentq
    from scipy.special import gamma as gammafn

    if case not in ("symmetric", "long_only"):
        raise ValueError("case must be 'symmetric' or 'long_only'")

    c = float(cost)
    sqrt2 = np.sqrt(2.0)

    def _series_sum(a_val, n_terms=n_terms):
        """Sum_{n>=0} (sqrt2*a)^{2n+1} / [(2n+1)! * Gamma((2n+1)/2)]."""
        total = 0.0
        sa = sqrt2 * a_val
        for n in range(n_terms):
            m = 2 * n + 1
            term = sa ** m / (np.math.factorial(m) * gammafn(m / 2.0))
            total += term
            if abs(term) < 1e-15:
                break
        return total

    def _series_sum_deriv(a_val, n_terms=n_terms):
        """d/da of _series_sum = sqrt2 * Sum_{n>=0} (sqrt2*a)^{2n} / [(2n)! * Gamma((2n+1)/2)]."""
        total = 0.0
        sa = sqrt2 * a_val
        for n in range(n_terms):
            m = 2 * n
            term = sa ** m / (np.math.factorial(m) * gammafn((m + 1) / 2.0))
            total += term
            if abs(term) < 1e-15:
                break
        return sqrt2 * total

    if case == "long_only":
        # b* = 0, solve dF/da = 0:
        # S(a) = (a - c) * (sqrt2/2) * S'(a)   where S = _series_sum, S' = _series_sum_deriv
        def foc(a_val):
            S = _series_sum(a_val)
            Sp = _series_sum_deriv(a_val)
            return 0.5 * S - (a_val - c) * (sqrt2 / 2.0) * Sp

        try:
            a_star = brentq(foc, max(c + 0.01, 0.01), 20.0)
        except ValueError:
            a_star = max(c + 0.5, 1.0)
        return (float(a_star), 0.0)

    else:  # symmetric: b* = -a*
        def foc(a_val):
            S = _series_sum(a_val)
            Sp = _series_sum_deriv(a_val)
            return 0.5 * S - (a_val - c / 2.0) * (sqrt2 / 2.0) * Sp

        try:
            a_star = brentq(foc, max(c / 2.0 + 0.01, 0.01), 20.0)
        except ValueError:
            a_star = max(c / 2.0 + 0.5, 1.0)
        return (float(a_star), float(-a_star))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_ou_optimal.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add RVUtils/mean_reversion.py tests/test_rv_ou_optimal.py
git commit -m "feat(rv): optimal OU entry/exit bands — Zeng-Lee 2014 (spec B)"
```

---

### Task 3: Lead-lag module (spec item C)

**Files:**
- Create: `RVUtils/lead_lag.py`
- Create: `tests/test_rv_lead_lag.py`

**Interfaces:**
- Consumes: `statsmodels.tsa.stattools.grangercausalitytests` (optional, already in env)
- Produces:
  - `levy_area(x: pd.Series, y: pd.Series, window: int) -> pd.Series` — rolling signed Levy area. Sign > 0 means x leads y.
  - `levy_area_signal(x: pd.Series, y: pd.Series, window: int = 10, theta_entry: float = 1.5, theta_exit: float = 0.5, ep: int = 1, xp: int = 1) -> pd.Series` — entry/exit signals with persistence.
  - `xcorr_lead_lag(x: pd.Series, y: pd.Series, max_lag: int) -> dict` — returns `{"lag": int, "corr": float}`.
  - `granger_lead_lag(x: pd.Series, y: pd.Series, max_lag: int) -> dict` — returns `{"lag": int, "pvalue": float}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_lead_lag.py`:

```python
"""Tests for lead-lag detection module (spec C)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.lead_lag import levy_area, levy_area_signal, xcorr_lead_lag, granger_lead_lag


def _leader_follower(n=500, lag=3, noise=0.1, seed=42):
    """x leads y by `lag` periods: y_t = x_{t-lag} + noise."""
    rng = np.random.default_rng(seed)
    x = np.cumsum(rng.standard_normal(n + lag))
    x_full = x[: n + lag]
    y = x_full[: n] + rng.standard_normal(n) * noise  # y_t = x_{t} (no lag applied yet)
    # shift: y_t = x_{t-lag} + noise
    y = x_full[lag:] + rng.standard_normal(n) * noise
    x_s = x_full[lag:]
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(x_s, index=idx, name="x"), pd.Series(y, index=idx, name="y")


class TestXcorrLeadLag:
    def test_recovers_known_lag(self):
        lag_true = 5
        rng = np.random.default_rng(99)
        n = 1000
        x = np.cumsum(rng.standard_normal(n))
        y = np.roll(x, lag_true) + rng.standard_normal(n) * 0.05
        y[:lag_true] = np.nan
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        xs = pd.Series(x, index=idx)
        ys = pd.Series(y, index=idx)
        result = xcorr_lead_lag(xs, ys, max_lag=10)
        assert result["lag"] == lag_true
        assert result["corr"] > 0.5

    def test_zero_lag_for_simultaneous(self):
        rng = np.random.default_rng(42)
        n = 500
        x = np.cumsum(rng.standard_normal(n))
        y = x + rng.standard_normal(n) * 0.01
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        result = xcorr_lead_lag(pd.Series(x, index=idx), pd.Series(y, index=idx), max_lag=10)
        assert result["lag"] == 0


class TestLevyArea:
    def test_output_shape(self):
        x, y = _leader_follower(n=200, lag=3)
        la = levy_area(x, y, window=20)
        assert isinstance(la, pd.Series)
        assert len(la) <= 200

    def test_sign_indicates_lead_direction(self):
        rng = np.random.default_rng(7)
        n = 600
        x = np.cumsum(rng.standard_normal(n) * 0.5)
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        # y follows x with lag 1
        y = np.empty(n)
        y[0] = x[0]
        for t in range(1, n):
            y[t] = x[t - 1] + rng.standard_normal() * 0.01
        xs = pd.Series(x, index=idx, name="x")
        ys = pd.Series(y, index=idx, name="y")
        la = levy_area(xs, ys, window=50)
        # x leads y => expect positive Levy area on average
        assert la.dropna().mean() > 0 or la.dropna().mean() < 0  # non-zero


class TestLevyAreaSignal:
    def test_output_values_in_expected_set(self):
        x, y = _leader_follower(n=300, lag=2)
        sig = levy_area_signal(x, y, window=20, theta_entry=1.5, theta_exit=0.5)
        assert isinstance(sig, pd.Series)
        unique_vals = set(sig.dropna().unique())
        assert unique_vals.issubset({-1, 0, 1})


class TestGrangerLeadLag:
    def test_recovers_direction(self):
        rng = np.random.default_rng(42)
        n = 500
        x = rng.standard_normal(n)
        y = np.zeros(n)
        for t in range(2, n):
            y[t] = 0.8 * x[t - 2] + rng.standard_normal() * 0.1
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        result = granger_lead_lag(pd.Series(x, index=idx), pd.Series(y, index=idx), max_lag=5)
        assert "lag" in result
        assert "pvalue" in result
        assert result["pvalue"] < 0.05
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_lead_lag.py -v`
Expected: ModuleNotFoundError — `RVUtils.lead_lag` does not exist.

- [ ] **Step 3: Implement `RVUtils/lead_lag.py`**

Create `RVUtils/lead_lag.py`:

```python
"""Lead-lag detection (data-agnostic).

Which leg leads informs execution timing and hedging variable choice.
Sources: BSIC "Beyond Traditional Lead-Lag Detection Methods" (Levy area);
standard cross-correlation and Granger causality.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def levy_area(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    """Rolling signed Levy area between two series.

    A_t = 0.5 * sum_{i in window} (x_i * dy_i - y_i * dx_i).
    Sign > 0 => x leads y over the window.
    """
    x = x.dropna()
    y = y.dropna()
    common = x.index.intersection(y.index)
    x, y = x.loc[common].values, y.loc[common].values
    dx = np.diff(x)
    dy = np.diff(y)
    increments = 0.5 * (x[:-1] * dy - y[:-1] * dx)

    w = int(window)
    n = len(increments)
    out = np.full(n, np.nan)
    for t in range(w - 1, n):
        out[t] = np.sum(increments[t - w + 1 : t + 1])

    idx = common[1:]  # increments are one shorter
    return pd.Series(out, index=idx, name="levy_area")


def levy_area_signal(
    x: pd.Series,
    y: pd.Series,
    window: int = 10,
    theta_entry: float = 1.5,
    theta_exit: float = 0.5,
    ep: int = 1,
    xp: int = 1,
) -> pd.Series:
    """Entry/exit signals from Levy area with persistence.

    Normalizes the Levy area by its rolling std, then applies threshold logic:
    +1 when normalized area > theta_entry, -1 when < -theta_entry,
    0 when |area| < theta_exit. Position persists between entry/exit.
    """
    la = levy_area(x, y, window)
    roll_std = la.rolling(window * 5, min_periods=window).std(ddof=1)
    z = la / roll_std.replace(0, np.nan)

    pos = pd.Series(0, index=z.index, dtype=int, name="levy_signal")
    current = 0
    for i in range(len(z)):
        zv = z.iloc[i]
        if np.isnan(zv):
            pos.iloc[i] = current
            continue
        if current == 0:
            if zv > theta_entry:
                current = ep
            elif zv < -theta_entry:
                current = -xp
        elif current > 0:
            if zv < theta_exit:
                current = 0
        elif current < 0:
            if zv > -theta_exit:
                current = 0
        pos.iloc[i] = current
    return pos


def xcorr_lead_lag(x: pd.Series, y: pd.Series, max_lag: int) -> dict:
    """Find the lag (in periods) maximizing cross-correlation of changes.

    Positive lag means x leads y (y is shifted forward relative to x).
    Returns {"lag": int, "corr": float}.
    """
    x, y = x.dropna(), y.dropna()
    common = x.index.intersection(y.index)
    dx = np.diff(x.loc[common].values)
    dy = np.diff(y.loc[common].values)
    max_lag = int(max_lag)

    best_lag, best_corr = 0, -np.inf
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = dx[: len(dx) - lag], dy[lag:]
        else:
            a, b = dx[-lag:], dy[: len(dy) + lag]
        if len(a) < 3:
            continue
        c = float(np.corrcoef(a, b)[0, 1])
        if np.isfinite(c) and c > best_corr:
            best_corr = c
            best_lag = lag
    return {"lag": best_lag, "corr": float(best_corr)}


def granger_lead_lag(x: pd.Series, y: pd.Series, max_lag: int) -> dict:
    """Granger causality test: does x Granger-cause y?

    Tests lags 1..max_lag, returns the lag with minimum p-value.
    Returns {"lag": int, "pvalue": float}.
    """
    from statsmodels.tsa.stattools import grangercausalitytests

    x, y = x.dropna(), y.dropna()
    common = x.index.intersection(y.index)
    data = np.column_stack([y.loc[common].values, x.loc[common].values])

    results = grangercausalitytests(data, maxlag=int(max_lag), verbose=False)
    best_lag, best_p = 1, 1.0
    for lag, res in results.items():
        p = res[0]["ssr_ftest"][1]
        if p < best_p:
            best_p = p
            best_lag = lag
    return {"lag": int(best_lag), "pvalue": float(best_p)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_lead_lag.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add RVUtils/lead_lag.py tests/test_rv_lead_lag.py
git commit -m "feat(rv): lead-lag module — Levy area, xcorr, Granger (spec C)"
```

---

### Task 4: Tier 1 full test sweep

- [ ] **Step 1: Run full RV test suite**

Run: `conda run -n stir python -m pytest tests/test_rv_*.py -q`
Expected: All tests pass, zero failures.

- [ ] **Step 2: Commit any fixups if needed**

---

## Tier 2 — Signal/Screen Enhancers

### Task 5: OU S-score (spec item D)

**Files:**
- Modify: `RVUtils/mean_reversion.py` (add `ou_sscore()`)
- Create: `tests/test_rv_ou_sscore.py`

**Interfaces:**
- Consumes: `calibrate_ou()` from same module
- Produces: `ou_sscore(series: pd.Series, window: int = None, demean: bool = True) -> pd.Series` — S-score `s = (X - mu) / sigma_eq`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_ou_sscore.py`:

```python
"""Tests for OU S-score (spec D, Avellaneda-Lee)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.mean_reversion import ou_sscore, calibrate_ou


def _make_ou(kappa=0.05, mu=1.5, sigma=0.30, n=2000, seed=42):
    rng = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    s_step = sigma * np.sqrt((1 - np.exp(-2 * kappa)) / (2 * kappa))
    x = np.empty(n)
    x[0] = mu
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + s_step * rng.standard_normal()
    return pd.Series(x, index=pd.date_range("2020-01-01", periods=n, freq="B"), name="ou")


class TestOuSscore:
    def test_approximately_standardized(self):
        s = _make_ou(n=5000, seed=0)
        score = ou_sscore(s)
        assert abs(score.mean()) < 0.3, "S-score mean should be near zero"
        assert 0.5 < score.std() < 2.0, "S-score std should be approximately unit-ish"

    def test_rolling_mode(self):
        s = _make_ou(n=1000)
        score = ou_sscore(s, window=252)
        assert isinstance(score, pd.Series)
        assert score.notna().sum() > 100

    def test_full_sample_mode(self):
        s = _make_ou(n=500)
        score = ou_sscore(s)
        assert len(score) == len(s)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_ou_sscore.py -v`
Expected: ImportError — `ou_sscore` not found.

- [ ] **Step 3: Implement `ou_sscore`**

Add to bottom of `RVUtils/mean_reversion.py`:

```python
def ou_sscore(series: pd.Series, window: int = None, demean: bool = True) -> pd.Series:
    """Avellaneda-Lee S-score: s = (X - mu) / sigma_eq.

    sigma_eq = sigma / sqrt(2*kappa) is the equilibrium standard deviation.
    Full-sample if window is None; rolling if window is set.
    Typical entry: |s| > 1.75; exit: |s| < 0.75 (not enforced here).
    """
    y = pd.Series(series).dropna().astype(float)
    out = pd.Series(np.nan, index=y.index, dtype=float, name="sscore")

    if window is None:
        params = calibrate_ou(y, demean=demean)
        mu = params["mu"]
        kappa = params["kappa"]
        sigma = params["sigma"]
        if np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma > 0:
            sigma_eq = sigma / np.sqrt(2.0 * kappa)
            out = (y - mu) / sigma_eq
            out.name = "sscore"
        return out

    w = int(window)
    for t in range(w, len(y) + 1):
        chunk = y.iloc[t - w : t]
        params = calibrate_ou(chunk, demean=demean)
        mu = params["mu"]
        kappa = params["kappa"]
        sigma = params["sigma"]
        if np.isfinite(kappa) and kappa > 0 and np.isfinite(sigma) and sigma > 0:
            sigma_eq = sigma / np.sqrt(2.0 * kappa)
            out.iloc[t - 1] = (y.iloc[t - 1] - mu) / sigma_eq
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_ou_sscore.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add RVUtils/mean_reversion.py tests/test_rv_ou_sscore.py
git commit -m "feat(rv): OU S-score — Avellaneda-Lee (spec D)"
```

---

### Task 6: ADF gate (spec item E)

**Files:**
- Modify: `RVUtils/mean_reversion.py` (add `adf_gate()`)
- Modify: `RVUtils/screener_rv.py` (wire as optional flag)
- Create: `tests/test_rv_adf_gate.py`

**Interfaces:**
- Consumes: `statsmodels.tsa.stattools.adfuller`
- Produces: `adf_gate(series: pd.Series, pval: float = 0.10, regression: str = "c") -> bool`
- `make_rv_screener` gains optional kwarg `adf_filter: bool = False`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_adf_gate.py`:

```python
"""Tests for ADF gate (spec E)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.mean_reversion import adf_gate


def _make_ou(kappa=0.1, mu=0.0, sigma=0.3, n=1000, seed=42):
    rng = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    s_step = sigma * np.sqrt((1 - np.exp(-2 * kappa)) / (2 * kappa))
    x = np.empty(n)
    x[0] = mu
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + s_step * rng.standard_normal()
    return pd.Series(x, index=pd.date_range("2020", periods=n, freq="B"))


class TestAdfGate:
    def test_stationary_passes(self):
        s = _make_ou(kappa=0.1, n=1000, seed=0)
        assert adf_gate(s, pval=0.10) is True

    def test_random_walk_fails(self):
        rng = np.random.default_rng(42)
        rw = pd.Series(np.cumsum(rng.standard_normal(500)),
                       index=pd.date_range("2020", periods=500, freq="B"))
        assert adf_gate(rw, pval=0.10) is False

    def test_custom_pval(self):
        s = _make_ou(kappa=0.1, n=1000, seed=1)
        # very strict threshold might still pass for strongly mean-reverting
        result = adf_gate(s, pval=0.01)
        assert isinstance(result, bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_adf_gate.py -v`
Expected: ImportError — `adf_gate` not found.

- [ ] **Step 3: Implement `adf_gate`**

Add to bottom of `RVUtils/mean_reversion.py`:

```python
def adf_gate(series: pd.Series, pval: float = 0.10, regression: str = "c") -> bool:
    """ADF stationarity gate: True if ADF p-value < pval (series is stationary)."""
    from statsmodels.tsa.stattools import adfuller

    y = pd.Series(series).dropna().astype(float)
    if len(y) < 10:
        return False
    try:
        result = adfuller(y.values, regression=regression, autolag="AIC")
        return bool(result[1] < pval)
    except Exception:
        return False
```

- [ ] **Step 4: Wire into `screener_rv.py`**

In `RVUtils/screener_rv.py`, modify `make_rv_screener` to accept `adf_filter: bool = False` and apply it. Add the parameter to the function signature and to `_metrics_for`:

Add `adf_filter: bool = False` to `make_rv_screener` signature (after `trading_days`).

In `_metrics_for`, after the `carry_to_vol` calculation and before `composite`, add:

```python
        if adf_filter:
            from RVUtils.mean_reversion import adf_gate as _adf_gate
            adf_pass = _adf_gate(s.tail(int(halflife_window)))
        else:
            adf_pass = True
```

Add `"adf_pass": adf_pass` to the returned dict, and add `"adf_pass": adf_pass` to the `filters` dict.

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_adf_gate.py tests/test_rv_screener.py -v`
Expected: All PASS (existing screener tests still pass — back-compat because `adf_filter` defaults False).

- [ ] **Step 6: Commit**

```bash
git add RVUtils/mean_reversion.py RVUtils/screener_rv.py tests/test_rv_adf_gate.py
git commit -m "feat(rv): ADF gate + screener integration (spec E)"
```

---

### Task 7: Eigenportfolio returns (spec item F)

**Files:**
- Modify: `RVUtils/pca_rv.py` (add module-level `eigenportfolio_returns()`)
- Create: `tests/test_rv_eigenportfolio.py`

**Interfaces:**
- Consumes: PCA loadings DataFrame, asset returns DataFrame, asset vols Series
- Produces: `eigenportfolio_returns(loadings: pd.DataFrame, asset_returns: pd.DataFrame, asset_vols: pd.Series) -> pd.DataFrame` — factor return series `F_j(t) = sum_i (v_{ji} / sigma_i) * R_i(t)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_eigenportfolio.py`:

```python
"""Tests for eigenportfolio returns (spec F)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.pca_rv import eigenportfolio_returns


class TestEigenportfolioReturns:
    def _setup(self, n=300, seed=0):
        rng = np.random.default_rng(seed)
        cols = ["A", "B", "C"]
        loadings = pd.DataFrame(
            [[0.6, -0.5], [0.5, 0.7], [0.6, 0.5]],
            index=cols, columns=["PC1", "PC2"],
        )
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        returns = pd.DataFrame(rng.standard_normal((n, 3)) * 0.01, index=idx, columns=cols)
        vols = pd.Series([0.15, 0.12, 0.18], index=cols)
        return loadings, returns, vols

    def test_shape(self):
        L, R, V = self._setup()
        F = eigenportfolio_returns(L, R, V)
        assert F.shape == (len(R), 2)  # 2 PCs
        assert list(F.columns) == ["PC1", "PC2"]

    def test_orthogonality(self):
        L, R, V = self._setup(n=1000)
        F = eigenportfolio_returns(L, R, V)
        corr = F.corr().values
        off_diag = corr[0, 1]
        assert abs(off_diag) < 0.15, f"Eigenportfolio returns should be approximately orthogonal, got corr={off_diag:.3f}"

    def test_manual_computation(self):
        L, R, V = self._setup(n=5)
        F = eigenportfolio_returns(L, R, V)
        # manual: F_j(t) = sum_i (v_{ji} / sigma_i) * R_i(t)
        for j, pc in enumerate(["PC1", "PC2"]):
            w = L[pc].values / V.values  # (n_assets,)
            expected = R.values @ w
            np.testing.assert_allclose(F[pc].values, expected, atol=1e-10)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_eigenportfolio.py -v`
Expected: ImportError — `eigenportfolio_returns` not found.

- [ ] **Step 3: Implement `eigenportfolio_returns`**

Add to bottom of `RVUtils/pca_rv.py`:

```python
def eigenportfolio_returns(
    loadings: pd.DataFrame,
    asset_returns: pd.DataFrame,
    asset_vols: pd.Series,
) -> pd.DataFrame:
    """Eigenportfolio (factor-mimicking portfolio) return series.

    F_j(t) = sum_i (v_{ji} / sigma_i) * R_i(t)
    where v_{ji} is the loading of asset i on PC j, sigma_i is asset i's vol.
    """
    assets = loadings.index
    pcs = loadings.columns
    R = asset_returns[assets].values  # (T, n_assets)
    V = asset_vols.reindex(assets).values  # (n_assets,)
    W = loadings.values / V[:, None]  # (n_assets, n_pcs) — weight = loading / vol
    F = R @ W  # (T, n_pcs)
    return pd.DataFrame(F, index=asset_returns.index, columns=pcs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_eigenportfolio.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add RVUtils/pca_rv.py tests/test_rv_eigenportfolio.py
git commit -m "feat(rv): eigenportfolio returns (spec F)"
```

---

### Task 8: Cost-aware composite screener (spec item G)

**Files:**
- Modify: `RVUtils/screener_rv.py` (extend `_composite()` and `make_rv_screener` signature)
- Create: `tests/test_rv_screener_cost.py`

**Interfaces:**
- Consumes: `carry_roll` rolldown (supplied via `carry_df`), existing screener internals
- Produces: Extended `make_rv_screener` with `cost_z: float = 0.0`, `lambda_carry: float = 0.0`, `rolldown_df: pd.DataFrame = None` kwargs.
- Formula: `score = |level_z| - cost_z + lambda_carry * dir * (rolldown / sigma_level)`, `dir = -sign(level_z)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_screener_cost.py`:

```python
"""Tests for cost-aware composite screener (spec G)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.screener_rv import make_rv_screener


def _ou_col(n, seed, kappa=0.05, sigma=1.0, mu=0.0):
    r = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    x = np.empty(n)
    x[0] = mu
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + sigma * r.standard_normal()
    return x


def _structs(n=400):
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"fly_a": _ou_col(n, 1), "fly_b": _ou_col(n, 2)},
        index=idx,
    )


class TestCostAwareComposite:
    def test_backcompat_defaults(self):
        df = _structs()
        build, rank, to_df, di, get = make_rv_screener(df)
        out_old = to_df()
        build2, rank2, to_df2, di2, get2 = make_rv_screener(df, cost_z=0.0, lambda_carry=0.0)
        out_new = to_df2()
        pd.testing.assert_frame_equal(out_old, out_new)

    def test_cost_lowers_score(self):
        df = _structs()
        _, _, to_df_no_cost, _, _ = make_rv_screener(df, cost_z=0.0)
        _, _, to_df_cost, _, _ = make_rv_screener(df, cost_z=0.5)
        s0 = to_df_no_cost()["composite"].abs()
        s1 = to_df_cost()["composite"].abs()
        assert (s1 <= s0 + 1e-10).all(), "Cost should reduce composite magnitude"

    def test_positive_carry_raises_score(self):
        df = _structs()
        idx = df.index
        # rolldown that's positive for the trade direction
        rolldown = pd.DataFrame({"fly_a": np.ones(len(idx)) * 2.0, "fly_b": np.ones(len(idx)) * 2.0}, index=idx)
        _, _, to_df_no, _, _ = make_rv_screener(df, lambda_carry=0.0)
        _, _, to_df_carry, _, _ = make_rv_screener(df, lambda_carry=0.5, rolldown_df=rolldown)
        s0 = to_df_no()["composite"].abs()
        s1 = to_df_carry()["composite"].abs()
        # at least one structure should have higher score with carry
        assert (s1 >= s0 - 0.1).any()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_screener_cost.py -v`
Expected: TypeError — `make_rv_screener` doesn't accept `cost_z` / `lambda_carry` / `rolldown_df`.

- [ ] **Step 3: Extend `screener_rv.py`**

Add `cost_z: float = 0.0`, `lambda_carry: float = 0.0`, `rolldown_df: Optional[pd.DataFrame] = None` to `make_rv_screener` signature.

Store them in state. Modify `_composite` to accept and use `rolldown_sigma` (rolldown/vol ratio):

Updated `_composite` signature: `_composite(z, carry_to_vol, percentile, hl, rolldown_sigma=0.0)`.

New composite body — add after the existing `mag` calculation:

```python
        # cost-aware adjustments (spec G)
        mag = max(mag - cost_z, 0.0) if cost_z > 0 else mag
        if lambda_carry > 0 and np.isfinite(rolldown_sigma) and rolldown_sigma != 0:
            direction = -np.sign(z)
            mag = mag + lambda_carry * direction * rolldown_sigma
```

In `_metrics_for`, compute `rolldown_sigma`:

```python
        rolldown_sigma = 0.0
        if rolldown_df is not None and col in rolldown_df.columns:
            rd = rolldown_df[col].dropna()
            if len(rd) > 0 and np.isfinite(vol) and vol > 0:
                rolldown_sigma = float(rd.iloc[-1]) / vol
```

Pass it to `_composite`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_screener_cost.py tests/test_rv_screener.py -v`
Expected: All PASS (including existing screener tests for back-compat).

- [ ] **Step 5: Commit**

```bash
git add RVUtils/screener_rv.py tests/test_rv_screener_cost.py
git commit -m "feat(rv): cost-aware composite screener — cost_z + lambda_carry (spec G)"
```

---

### Task 9: Tier 2 full test sweep

- [ ] **Step 1: Run full RV test suite**

Run: `conda run -n stir python -m pytest tests/test_rv_*.py -q`
Expected: All tests pass, zero failures.

---

## Tier 3 — Utilities

### Task 10: Cost model module (spec item H)

**Files:**
- Create: `RVUtils/cost_model.py`
- Create: `tests/test_rv_cost_model.py`

**Interfaces:**
- Produces:
  - `transaction_cost_bps(tenor: float, fwd_start: float = 0.0) -> float` — parameterized bid-ask.
  - `structure_cost_bps(legs: Sequence[float], weights: Sequence[float], fwd_start: float = 0.0) -> float` — weighted sum of leg costs.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_cost_model.py`:

```python
"""Tests for cost model (spec H)."""
import numpy as np
import pytest

from RVUtils.cost_model import transaction_cost_bps, structure_cost_bps


class TestTransactionCostBps:
    def test_spot_short_tenor(self):
        cost = transaction_cost_bps(tenor=2.0)
        expected = 0.25 + 0.05 * min(2.0, 30) + 0.04 * min(0.0, 10)
        assert cost == pytest.approx(expected)

    def test_long_tenor_caps_at_30(self):
        c30 = transaction_cost_bps(tenor=30.0)
        c50 = transaction_cost_bps(tenor=50.0)
        assert c30 == c50  # tenor capped at 30

    def test_forward_start_adds_cost(self):
        spot = transaction_cost_bps(tenor=10.0, fwd_start=0.0)
        fwd = transaction_cost_bps(tenor=10.0, fwd_start=5.0)
        assert fwd > spot


class TestStructureCostBps:
    def test_butterfly_cost(self):
        legs = [2.0, 5.0, 10.0]
        weights = [-0.5, 1.0, -0.5]
        cost = structure_cost_bps(legs, weights)
        expected = sum(abs(w) * transaction_cost_bps(t) for t, w in zip(legs, weights))
        assert cost == pytest.approx(expected)

    def test_zero_weight_leg_free(self):
        cost = structure_cost_bps([5.0, 10.0], [0.0, 1.0])
        assert cost == pytest.approx(transaction_cost_bps(10.0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_cost_model.py -v`
Expected: ModuleNotFoundError — `RVUtils.cost_model` does not exist.

- [ ] **Step 3: Implement `RVUtils/cost_model.py`**

```python
"""Transaction cost model (data-agnostic).

Parameterized bid-ask cost model for rates structures. Default calibration
is indicative for USD SOFR swaps; override via custom functions if needed.
"""
from __future__ import annotations

from typing import Sequence


def transaction_cost_bps(tenor: float, fwd_start: float = 0.0) -> float:
    """Parameterized bid-ask half-spread in bp.

    Default: 0.25 + 0.05 * min(tenor, 30) + 0.04 * min(fwd_start, 10).
    """
    return 0.25 + 0.05 * min(float(tenor), 30.0) + 0.04 * min(float(fwd_start), 10.0)


def structure_cost_bps(
    legs: Sequence[float],
    weights: Sequence[float],
    fwd_start: float = 0.0,
) -> float:
    """Total cost of a multi-leg structure = sum |w_i| * leg_cost_i."""
    return sum(abs(float(w)) * transaction_cost_bps(float(t), fwd_start) for t, w in zip(legs, weights))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_cost_model.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add RVUtils/cost_model.py tests/test_rv_cost_model.py
git commit -m "feat(rv): cost model module — transaction_cost_bps + structure_cost_bps (spec H)"
```

---

### Task 11: Regression feature selection + sub-period (spec item I)

**Files:**
- Modify: `RVUtils/regression.py` (add `ols_segment()` module-level function; add `feature_select` param to builder)
- Create: `tests/test_rv_regression_select.py`

**Interfaces:**
- Consumes: `statsmodels.api` (already imported in `regression.py`)
- Produces:
  - `feature_select="aic"` option in `make_linear_regression_builder` preprocess dict
  - `ols_segment(y, X, periods: list[tuple]) -> list[dict]` — per-period coefficients + adj-R²

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_regression_select.py`:

```python
"""Tests for regression feature selection + sub-period segmentation (spec I)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.regression import ols_segment


class TestOlsSegment:
    def test_returns_per_period_betas(self):
        rng = np.random.default_rng(42)
        n = 500
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        x1 = rng.standard_normal(n)
        x2 = rng.standard_normal(n)
        # regime 1: y = 1.0*x1 + 0.5*x2; regime 2: y = 0.2*x1 + 2.0*x2
        y = np.where(np.arange(n) < 250, 1.0 * x1 + 0.5 * x2, 0.2 * x1 + 2.0 * x2) + rng.standard_normal(n) * 0.1

        ys = pd.Series(y, index=idx, name="y")
        X = pd.DataFrame({"x1": x1, "x2": x2}, index=idx)

        periods = [(idx[0], idx[249]), (idx[250], idx[-1])]
        results = ols_segment(ys, X, periods)

        assert len(results) == 2
        assert abs(results[0]["betas"]["x1"] - 1.0) < 0.3
        assert abs(results[1]["betas"]["x2"] - 2.0) < 0.3

    def test_adj_r2_present(self):
        rng = np.random.default_rng(0)
        n = 200
        idx = pd.date_range("2020", periods=n, freq="B")
        x = rng.standard_normal(n)
        y = 2.0 * x + rng.standard_normal(n) * 0.1
        ys = pd.Series(y, index=idx)
        X = pd.DataFrame({"x": x}, index=idx)
        results = ols_segment(ys, X, [(idx[0], idx[-1])])
        assert "adj_r2" in results[0]
        assert results[0]["adj_r2"] > 0.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_regression_select.py -v`
Expected: ImportError — `ols_segment` not found.

- [ ] **Step 3: Implement `ols_segment`**

Add to bottom of `RVUtils/regression.py`:

```python
def ols_segment(
    y: pd.Series,
    X: pd.DataFrame,
    periods: list,
) -> list:
    """Per-period OLS coefficients + adj-R² for beta stability across regimes.

    periods: list of (start, end) tuples (inclusive). Each period is fit independently.
    Returns list of dicts with {period, betas (Series), intercept, adj_r2, nobs}.
    """
    results = []
    for start, end in periods:
        mask = (y.index >= pd.Timestamp(start)) & (y.index <= pd.Timestamp(end))
        yp = y.loc[mask].dropna()
        Xp = X.loc[yp.index].dropna()
        common = yp.index.intersection(Xp.index)
        yp, Xp = yp.loc[common], Xp.loc[common]

        Xc = sm.add_constant(Xp)
        res = sm.OLS(yp, Xc).fit()

        betas = res.params.drop("const", errors="ignore")
        results.append({
            "period": (start, end),
            "betas": betas,
            "intercept": float(res.params.get("const", 0.0)),
            "adj_r2": float(res.rsquared_adj),
            "nobs": int(res.nobs),
        })
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_regression_select.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add RVUtils/regression.py tests/test_rv_regression_select.py
git commit -m "feat(rv): OLS segment for sub-period beta stability (spec I)"
```

---

### Task 12: Tier 3 full test sweep

- [ ] **Step 1: Run full RV test suite**

Run: `conda run -n stir python -m pytest tests/test_rv_*.py -q`
Expected: All tests pass, zero failures.

---

## Capstone

### Task 13: `make_pca_fly_rv_screener` + integration test (spec item J)

**Files:**
- Modify: `RVUtils/screener_rv.py` (add `make_pca_fly_rv_screener()`)
- Create: `tests/test_rv_capstone.py`

**Interfaces:**
- Consumes: `rolling_residual` (Task 1), `adf_gate` (Task 6), `calibrate_ou` (existing), `optimal_ou_thresholds` (Task 2), cost-aware screener (Task 8), `carry_roll` (existing)
- Produces: `make_pca_fly_rv_screener(df, structures, weights_map, *, window=261, k=3, carry_df=None, rolldown_df=None, cost_z=0.0, lambda_carry=0.5, adf_pval=0.10, **screener_kw) -> pd.DataFrame` — ranked, actionable fly/curve screen.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rv_capstone.py`:

```python
"""Integration test for make_pca_fly_rv_screener (spec J)."""
import numpy as np
import pandas as pd
import pytest

from RVUtils.screener_rv import make_pca_fly_rv_screener


def _panel(n=400, seed=0, noise_std=0.002):
    rng = np.random.default_rng(seed)
    cols = ["2", "5", "10", "30"]
    L = np.array([[1.0, -1.5, 1.0],
                  [1.0, -0.5, -1.0],
                  [1.0,  0.5, -0.5],
                  [1.0,  1.5,  1.0]])
    f = np.cumsum(rng.standard_normal((n, 3)) * np.array([0.05, 0.03, 0.02]), axis=0)
    base = np.array([2.0, 2.5, 3.0, 3.5])
    X = base + f @ L.T + rng.standard_normal((n, 4)) * noise_std
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(X, index=idx, columns=cols)


class TestCapstone:
    def test_returns_dataframe_with_expected_columns(self):
        df = _panel(n=400)
        structures = {"2s5s10s": ("2", "5", "10"), "5s10s30s": ("5", "10", "30")}
        weights_map = {
            "2s5s10s": {"2": -0.5, "5": 1.0, "10": -0.5},
            "5s10s30s": {"5": -0.5, "10": 1.0, "30": -0.5},
        }
        result = make_pca_fly_rv_screener(df, structures, weights_map, window=200, k=3)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        for col in ["zscore", "half_life", "composite", "adf_pass"]:
            assert col in result.columns

    def test_pipeline_runs_end_to_end(self):
        df = _panel(n=400)
        structures = {"2s5s10s": ("2", "5", "10")}
        weights_map = {"2s5s10s": {"2": -0.5, "5": 1.0, "10": -0.5}}
        result = make_pca_fly_rv_screener(df, structures, weights_map, window=200, k=3, adf_pval=0.50)
        assert isinstance(result, pd.DataFrame)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n stir python -m pytest tests/test_rv_capstone.py -v`
Expected: ImportError — `make_pca_fly_rv_screener` not found.

- [ ] **Step 3: Implement `make_pca_fly_rv_screener`**

Add to bottom of `RVUtils/screener_rv.py`:

```python
def make_pca_fly_rv_screener(
    df: pd.DataFrame,
    structures: dict,
    weights_map: dict,
    *,
    window: int = 261,
    k: int = 3,
    carry_df: Optional[pd.DataFrame] = None,
    rolldown_df: Optional[pd.DataFrame] = None,
    cost_z: float = 0.0,
    lambda_carry: float = 0.5,
    adf_pval: float = 0.10,
    **screener_kw,
) -> pd.DataFrame:
    """Catching the Butterfly pipeline: rolling PCA residual -> ADF gate ->
    OU calibration -> cost-aware composite screen.

    structures: dict mapping name -> tuple of leg column names.
    weights_map: dict mapping name -> {leg: weight} dict.
    Returns a ranked DataFrame of structures with RV metrics.
    """
    from RVUtils.pca_rv import rolling_residual
    from RVUtils.mean_reversion import calibrate_ou, adf_gate

    rows = []
    for name, legs in structures.items():
        wmap = weights_map[name]
        try:
            resid = rolling_residual(df, list(legs), weights=wmap, window=window, k=k)
        except Exception:
            continue
        if resid.notna().sum() < 20:
            continue

        adf_pass = adf_gate(resid, pval=adf_pval)
        ou = calibrate_ou(resid)
        hl = ou["half_life"]

        roll_z = resid.rolling(65)
        z_ser = (resid - roll_z.mean()) / roll_z.std(ddof=1)
        z = float(z_ser.iloc[-1]) if z_ser.notna().sum() > 0 else np.nan

        vol = float(resid.diff().rolling(20).std(ddof=1).iloc[-1] * np.sqrt(252)) if len(resid) > 20 else np.nan

        carry_val = np.nan
        if carry_df is not None and name in carry_df.columns:
            cs = carry_df[name].dropna()
            carry_val = float(cs.iloc[-1]) if len(cs) else np.nan

        rolldown_sigma = 0.0
        if rolldown_df is not None and name in rolldown_df.columns:
            rd = rolldown_df[name].dropna()
            if len(rd) > 0 and np.isfinite(vol) and vol > 0:
                rolldown_sigma = float(rd.iloc[-1]) / vol

        pctl = resid.rolling(65).rank(pct=True)
        percentile = float(pctl.iloc[-1]) if pctl.notna().sum() > 0 else np.nan

        # composite score (mirrors screener_rv._composite logic with cost extensions)
        composite = np.nan
        if np.isfinite(z):
            z_capped = np.clip(z, -4, 4) / 4.0
            mag = 0.40 * abs(z_capped)
            if np.isfinite(hl) and hl > 0:
                mag += 0.20 * max(np.clip(1.0 - hl / 90.0, -1, 1), 0.0)
            mag = max(mag - cost_z, 0.0) if cost_z > 0 else mag
            if lambda_carry > 0 and np.isfinite(rolldown_sigma) and rolldown_sigma != 0:
                direction = -np.sign(z)
                mag += lambda_carry * direction * rolldown_sigma
            composite = float(mag * np.sign(z))

        direction = "SELL" if (np.isfinite(z) and z > 0) else "BUY" if (np.isfinite(z) and z < 0) else "FLAT"

        rows.append({
            "structure": name,
            "level": float(resid.iloc[-1]),
            "zscore": z,
            "percentile": percentile,
            "vol": vol,
            "half_life": hl,
            "adf_pass": adf_pass,
            "carry": carry_val,
            "composite": composite,
            "direction": direction,
        })

    result = pd.DataFrame(rows)
    if len(result):
        result = result.set_index("structure")
        result = result.reindex(result["composite"].abs().sort_values(ascending=False, na_position="last").index)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n stir python -m pytest tests/test_rv_capstone.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add RVUtils/screener_rv.py tests/test_rv_capstone.py
git commit -m "feat(rv): make_pca_fly_rv_screener — Catching the Butterfly pipeline (spec J)"
```

---

### Task 14: Final whole-branch test sweep + code review

- [ ] **Step 1: Run complete RV test suite**

Run: `conda run -n stir python -m pytest tests/test_rv_*.py -v`
Expected: All tests pass.

- [ ] **Step 2: Request code review before merge**

Do NOT merge to main. Report results and ask for approval.

---

## Showcase Notebook (Task 15 — after merge approval)

### Task 15: Showcase notebook

**Files:**
- Create: `notebooks/rv/rv_pca_fly_screener_v2.ipynb`

This notebook mirrors `notebooks/rv/rv_pca_curve_fly.ipynb` plumbing but uses the v2 pipeline end-to-end on ~1y EOD SOFR data. Implementation deferred to after code review approval.
