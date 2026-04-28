# SOFR Convex Linear Structure Screener — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Build a screener at `RVUtils/SFRConvexScreener/` that ranks 3M SOFR futures calendar spreads and butterflies by the asymmetry of their option-implied payoff distributions, plus comprehensively fix bugs in `RVUtils/ImpliedDistribution/` that the screener depends on.

**Architecture:** Mirror the conventions of `BT/signals/sfr_cal_spread_rv.py`: dataclass config, fail-soft per-structure with `logger.warning`, frozen dataclass result containers with `to_dataframe()`/`to_dict()`. Reuse existing `JointDistributionSnapshot.linear_combination_distribution(weights)` for the common-state joint payoff PDF; add a parallel Gaussian-copula path that samples from BL marginals using a 60-day historical correlation matrix. Output two ranked tables (composite score, asymmetry-only) per Section 4 of the design doc, written to disk as CSV+JSON; rendering happens in a notebook frontend at `notebooks/rv/run_sfr_convex_screener.ipynb`.

**Tech Stack:** Python 3, numpy, scipy, pandas, matplotlib, rateslib (transitively), existing ARBS infra (`RVUtils/ImpliedDistribution`, `MDP/STIRFutures`, `MDP/IRSwaps`, `MDP/STIRConvexityAdjustment`, `Caching/DiskCacheMixin`). Tests with pytest. All Python invoked via `conda run -n stir`.

**Key reuse (no re-implementation):**
- `IRSwapsMDP(source="BARCHART_STIRF-RL")` for the OIS curve
- `STIRFutureMDP` for SR3 prices/OI/volume + bulk historical
- `STIRFutureOptionMDP.fetch_sabr_smile` for option chain → SABR smile
- `SFRImpliedDistribution.extract` for BL + GM per-contract distributions
- Joint-strip calibration: existing `JointDistributionSnapshot` (FOMC-path common-state model) reachable via the strip-fitting entry points already in `implied_distribution.py`
- Linear structure P&L helpers from `BT/signals/sfr_cal_spread_rv.py`: `compute_spread_curve`, `compute_fly_curve`, `compute_zscore`, `compute_realized_vol`, `compute_risk_adj_roll`
- `IRSwapValue.CVX_ADJ_EMPIRICAL` via `STIRConvexityAdjustmentMDP` for futures-vs-OIS convexity
- `Caching/DiskCacheMixin` if any new cache layer is required

**Conventions to follow:**
- `@dataclass` (mutable) for configs; `@dataclass(frozen=True)` for results
- `logger = logging.getLogger(__name__)`; `logger.warning(...)` for per-structure fail-soft
- `datetime.date` for calendar dates; `pytz.timezone("America/New_York").localize(datetime.combine(d, time(18,0)))` for EOD timestamps
- Type hints via `typing` module (`Optional[X]`, `Dict[str, Y]`)
- `_safe_float()` pattern + `np.nan` for per-row failures
- Tests live flat in `tests/`; no mocking of MDP layer; pure-function unit tests with synthetic inputs
- All commands run via `conda run -n stir <cmd>`
- Frequent commits — one per task by default

**Out of scope (Phase 2+ per design doc):**
- HTML dashboard rendering (notebook handles display)
- Empirical historical copula (use Gaussian copula in Phase 1)
- Risk-weighted flies (1:-2:1 only in Phase 1)
- Backtester
- Condors / cross-color flies

---

## Phase 0: Comprehensive bug fixes in `RVUtils/ImpliedDistribution`

Reason: the screener will use percentiles, warnings, and joint snapshots from this module. All six identified issues must be fixed first so the screener inherits correct, observable behavior. Each task is bite-sized and TDD-disciplined.

### Task 0.1: Add `warnings: Tuple[str, ...]` field to result dataclasses

**Files:**
- Modify: `RVUtils/ImpliedDistribution/_types.py:33-59` (`BreedenLitzenbergerResult`)
- Modify: `RVUtils/ImpliedDistribution/_types.py:71-91` (`GaussianMixtureResult`)
- Modify: `RVUtils/ImpliedDistribution/_types.py:94-101` (`ImpliedDistributionSnapshot`)
- Test: `tests/test_implied_distribution_warnings.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_implied_distribution_warnings.py
import datetime
import numpy as np
import pytest

from RVUtils.ImpliedDistribution import (
    BreedenLitzenbergerResult,
    GaussianMixtureResult,
    ImpliedDistributionSnapshot,
    RNDInput,
)


def _trivial_rnd_input() -> RNDInput:
    return RNDInput(
        symbol="SFRZ26",
        as_of=datetime.date(2026, 4, 28),
        forward_price=96.5,
        forward_rate=3.5,
        time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14),
        discount_factor=1.0,
        strikes_price=np.array([96.0, 96.5, 97.0]),
        call_premiums=np.array([0.6, 0.3, 0.1]),
        strike_source="test",
    )


class TestWarningsField:
    def test_bl_result_has_warnings_tuple_default_empty(self):
        result = BreedenLitzenbergerResult(
            input=_trivial_rnd_input(),
            strike_grid_rate=np.array([3.0, 3.5, 4.0]),
            rnd_density=np.array([0.2, 0.6, 0.2]),
            rnd_cumulative=np.array([0.2, 0.8, 1.0]),
            bin_edges_rate=np.array([3.0, 3.5, 4.0]),
            bin_probabilities=np.array([0.5, 0.5]),
            bin_labels=["3.25", "3.75"],
            mean_rate=3.5,
            std_rate=0.3,
            skewness=0.0,
            kurtosis=3.0,
            smoothing_param=1e-4,
            n_ghost_points=10,
            spline_residual=0.0,
        )
        assert result.warnings == ()

    def test_bl_result_warnings_field_accepts_tuple(self):
        result = BreedenLitzenbergerResult(
            input=_trivial_rnd_input(),
            strike_grid_rate=np.array([3.0]),
            rnd_density=np.array([1.0]),
            rnd_cumulative=np.array([1.0]),
            bin_edges_rate=np.array([3.0, 3.5]),
            bin_probabilities=np.array([1.0]),
            bin_labels=["3.25"],
            mean_rate=3.0,
            std_rate=0.0,
            skewness=0.0,
            kurtosis=3.0,
            smoothing_param=1e-4,
            n_ghost_points=10,
            spline_residual=0.0,
            warnings=("clipped 1.5% of mass below 0% rate floor",),
        )
        assert result.warnings == ("clipped 1.5% of mass below 0% rate floor",)

    def test_gm_result_has_warnings_tuple_default_empty(self):
        result = GaussianMixtureResult(
            input=_trivial_rnd_input(),
            scenarios=(),
            weights=np.array([]),
            fitted_std_rates=np.array([]),
            strike_grid_rate=np.array([3.0]),
            composite_density=np.array([1.0]),
            composite_cdf=np.array([1.0]),
            rmse_price=0.0,
            max_abs_error_price=0.0,
            optimization_success=True,
            component_densities=np.zeros((0, 1)),
        )
        assert result.warnings == ()

    def test_snapshot_aggregates_child_warnings(self):
        bl = BreedenLitzenbergerResult(
            input=_trivial_rnd_input(),
            strike_grid_rate=np.array([3.0]),
            rnd_density=np.array([1.0]),
            rnd_cumulative=np.array([1.0]),
            bin_edges_rate=np.array([3.0, 3.5]),
            bin_probabilities=np.array([1.0]),
            bin_labels=["3.25"],
            mean_rate=3.0,
            std_rate=0.0,
            skewness=0.0,
            kurtosis=3.0,
            smoothing_param=1e-4,
            n_ghost_points=10,
            spline_residual=0.0,
            warnings=("bl warning",),
        )
        snap = ImpliedDistributionSnapshot(
            symbol="SFRZ26",
            as_of=datetime.date(2026, 4, 28),
            bl_result=bl,
            gm_result=None,
        )
        assert snap.all_warnings() == ("bl::bl warning",)
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_implied_distribution_warnings.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'warnings'`

**Step 3: Implement minimal change**

Add `warnings: Tuple[str, ...] = ()` field to `BreedenLitzenbergerResult` and `GaussianMixtureResult`. Add `all_warnings()` method to `ImpliedDistributionSnapshot` that returns a tuple of `f"{prefix}::{w}"` for each child warning. Use `field(default_factory=tuple)` if needed; tuples work as default literal `()` in `@dataclass(frozen=True)`.

```python
# In BreedenLitzenbergerResult:
warnings: Tuple[str, ...] = ()

# In GaussianMixtureResult:
warnings: Tuple[str, ...] = ()

# In ImpliedDistributionSnapshot:
def all_warnings(self) -> Tuple[str, ...]:
    out: List[str] = []
    if self.bl_result is not None:
        out.extend(f"bl::{w}" for w in self.bl_result.warnings)
    if self.gm_result is not None:
        out.extend(f"gm::{w}" for w in self.gm_result.warnings)
    return tuple(out)
```

**Step 4: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_implied_distribution_warnings.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_implied_distribution_warnings.py RVUtils/ImpliedDistribution/_types.py
git commit -m "feat(implied-dist): add warnings field to result dataclasses"
```

---

### Task 0.2: Fix `BreedenLitzenbergerResult.percentile()` to interpolate

**Files:**
- Modify: `RVUtils/ImpliedDistribution/_types.py:55-59`
- Test: `tests/test_implied_distribution_percentile.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_implied_distribution_percentile.py
import datetime
import numpy as np

from RVUtils.ImpliedDistribution import BreedenLitzenbergerResult, RNDInput


def _result_with_uniform_density() -> BreedenLitzenbergerResult:
    """Uniform [3.0, 4.0]: CDF(x) = (x - 3.0). 50th pct = 3.5 exactly."""
    grid = np.linspace(3.0, 4.0, 1001)
    density = np.ones_like(grid)
    cdf = (grid - 3.0)
    return BreedenLitzenbergerResult(
        input=RNDInput(
            symbol="X", as_of=datetime.date(2026, 4, 28),
            forward_price=96.5, forward_rate=3.5, time_to_expiry=0.5,
            expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
            strikes_price=np.array([96.0]), call_premiums=np.array([0.5]),
            strike_source="test",
        ),
        strike_grid_rate=grid,
        rnd_density=density,
        rnd_cumulative=cdf,
        bin_edges_rate=np.array([3.0, 4.0]),
        bin_probabilities=np.array([1.0]),
        bin_labels=["3.5"],
        mean_rate=3.5, std_rate=1/np.sqrt(12),
        skewness=0.0, kurtosis=1.8,
        smoothing_param=1e-4, n_ghost_points=10, spline_residual=0.0,
    )


def test_percentile_50_returns_exact_median():
    r = _result_with_uniform_density()
    assert abs(r.percentile(50.0) - 3.5) < 1e-3


def test_percentile_25_and_75_interpolate_correctly():
    r = _result_with_uniform_density()
    assert abs(r.percentile(25.0) - 3.25) < 1e-3
    assert abs(r.percentile(75.0) - 3.75) < 1e-3


def test_percentile_extreme_values_clamped():
    r = _result_with_uniform_density()
    # 0.0 and 100.0 should return grid endpoints, not crash
    assert r.percentile(0.0) == r.strike_grid_rate[0]
    assert r.percentile(100.0) == r.strike_grid_rate[-1]
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_implied_distribution_percentile.py -v`
Expected: FAIL — current `searchsorted` returns staircase values, off by `~1/1001` on a 1001-point grid (tolerance is 1e-3 so it may *just* pass for p=25/50/75). Confirm by inspecting output: if it currently passes accidentally, tighten tolerance to 1e-6 to force interpolation requirement.

**Step 3: Implement minimal change**

```python
def percentile(self, p: float) -> float:
    """Return the rate at the p-th percentile (0-100), linearly interpolated."""
    return float(np.interp(p / 100.0, self.rnd_cumulative, self.strike_grid_rate))
```

**Step 4: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_implied_distribution_percentile.py -v`
Expected: PASS, with errors << 1e-3 even at tight tolerances.

**Step 5: Commit**

```bash
git add tests/test_implied_distribution_percentile.py RVUtils/ImpliedDistribution/_types.py
git commit -m "fix(implied-dist): interpolate BL percentile via np.interp"
```

---

### Task 0.3: Surface negative-density clipping as a warning

**Files:**
- Modify: `RVUtils/ImpliedDistribution/_breeden_litzenberger.py:79-89`
- Test: `tests/test_implied_distribution_clipping_warning.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_implied_distribution_clipping_warning.py
import datetime
import numpy as np

from RVUtils.ImpliedDistribution import RNDInput
from RVUtils.ImpliedDistribution._breeden_litzenberger import extract_rnd_breeden_litzenberger


def _ill_conditioned_input_with_concave_calls() -> RNDInput:
    """Calls that violate convexity → spline 2nd derivative goes negative."""
    strikes = np.linspace(95.0, 98.0, 7)
    # Concave premium curve violates no-arbitrage; spline d²C/dK² < 0 in interior.
    premiums = np.array([0.1, 0.2, 0.5, 1.5, 0.5, 0.2, 0.1])
    return RNDInput(
        symbol="SYNTH", as_of=datetime.date(2026, 4, 28),
        forward_price=96.5, forward_rate=3.5, time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
        strikes_price=strikes, call_premiums=premiums,
        strike_source="test_concave",
    )


def test_extract_emits_warning_when_negative_density_clipped():
    result = extract_rnd_breeden_litzenberger(_ill_conditioned_input_with_concave_calls())
    # The negative-density mass *fraction* clipped before normalization should
    # be reported as a warning when nontrivial.
    matching = [w for w in result.warnings if "negative density" in w.lower()]
    assert len(matching) >= 1, f"expected negative-density warning, got: {result.warnings}"


def test_extract_no_warning_for_well_conditioned_input():
    # Smooth convex calls
    strikes = np.linspace(95.0, 98.0, 13)
    fwd = 96.5
    sigma = 0.5
    # Bachelier-like prices (closed-form not needed; smooth convex parabola will do)
    premiums = np.maximum(fwd - strikes, 0.0) + 0.5 * sigma * np.exp(-((strikes - fwd) ** 2) / (2 * sigma ** 2))
    rnd_input = RNDInput(
        symbol="SYNTH", as_of=datetime.date(2026, 4, 28),
        forward_price=fwd, forward_rate=100 - fwd, time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
        strikes_price=strikes, call_premiums=premiums,
        strike_source="test_smooth",
    )
    result = extract_rnd_breeden_litzenberger(rnd_input)
    matching = [w for w in result.warnings if "negative density" in w.lower()]
    assert len(matching) == 0, f"unexpected warning: {result.warnings}"
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_implied_distribution_clipping_warning.py -v`
Expected: FAIL — current code clips silently, no warning produced.

**Step 3: Implement minimal change**

Modify `extract_rnd_breeden_litzenberger`:

```python
warnings: List[str] = []

# 4. 2nd derivative → RND in price space
d2c_dk2 = spline(strike_grid, nu=2)
rnd_price = d2c_dk2 / df

# Detect & clip negative density
neg_mask = rnd_price < 0.0
if neg_mask.any():
    neg_mass = float(trapezoid(np.abs(np.minimum(rnd_price, 0.0)), strike_grid))
    pos_mass = float(trapezoid(np.maximum(rnd_price, 0.0), strike_grid))
    if pos_mass > 0:
        frac = neg_mass / (neg_mass + pos_mass)
        if frac > 1e-4:  # ignore numerical noise below 0.01%
            warnings.append(
                f"negative density mass clipped ({frac * 100:.2f}% of total)"
            )
rnd_price = np.maximum(rnd_price, 0.0)
```

Pass `warnings=tuple(warnings)` to the `BreedenLitzenbergerResult(...)` constructor at the end.

**Step 4: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_implied_distribution_clipping_warning.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_implied_distribution_clipping_warning.py RVUtils/ImpliedDistribution/_breeden_litzenberger.py
git commit -m "fix(implied-dist): emit warning when BL clips negative density"
```

---

### Task 0.4: Surface rate-floor truncation as a warning + diagnostic

**Files:**
- Modify: `RVUtils/ImpliedDistribution/_breeden_litzenberger.py:96-104`
- Test: extend `tests/test_implied_distribution_clipping_warning.py`

**Step 1: Write the failing test**

```python
# Append to tests/test_implied_distribution_clipping_warning.py

import math
def test_rate_floor_truncation_produces_warning():
    # Forward near 0% with wide vol → density tail extends below 0%
    strikes = np.linspace(99.0, 101.0, 21)  # rates: -1% to 1%
    fwd_rate = 0.10  # 10 bp
    fwd_price = 100 - fwd_rate
    # Wide bell-shaped premium curve so tail leaks below price=100 (rate<0)
    sigma = 1.0
    premiums = np.maximum(fwd_price - strikes, 0.0) + sigma * np.exp(-((strikes - fwd_price) ** 2) / 2.0)
    rnd_input = RNDInput(
        symbol="LOWRATE", as_of=datetime.date(2026, 4, 28),
        forward_price=fwd_price, forward_rate=fwd_rate, time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
        strikes_price=strikes, call_premiums=premiums,
        strike_source="test_lowrate",
    )
    result = extract_rnd_breeden_litzenberger(rnd_input, rate_floor=0.0)
    matching = [w for w in result.warnings if "floor" in w.lower()]
    assert len(matching) >= 1, f"expected rate-floor warning, got: {result.warnings}"
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_implied_distribution_clipping_warning.py::test_rate_floor_truncation_produces_warning -v`
Expected: FAIL — silent truncation today.

**Step 3: Implement minimal change**

In the rate-floor block, capture pre-truncation total mass and post-truncation mass, compute fraction discarded, emit warning if > 1e-4.

```python
# 6b. Truncate at rate floor
if rate_floor is not None:
    floor_mask = rate_grid >= rate_floor
    pre_mass = float(trapezoid(rnd_rate, rate_grid))
    rate_grid = rate_grid[floor_mask]
    rnd_rate = rnd_rate[floor_mask]
    post_mass = float(trapezoid(rnd_rate, rate_grid)) if len(rate_grid) > 1 else 0.0
    if pre_mass > 1e-10:
        truncated_frac = max(0.0, (pre_mass - post_mass) / pre_mass)
        if truncated_frac > 1e-4:
            warnings.append(
                f"rate floor at {rate_floor:.2%} truncated {truncated_frac * 100:.2f}% of mass"
            )
    if post_mass > 1e-10:
        rnd_rate = rnd_rate / post_mass
```

**Step 4: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_implied_distribution_clipping_warning.py -v`
Expected: PASS (all four tests in that file now pass).

**Step 5: Commit**

```bash
git add tests/test_implied_distribution_clipping_warning.py RVUtils/ImpliedDistribution/_breeden_litzenberger.py
git commit -m "fix(implied-dist): warn when rate floor truncates BL mass"
```

---

### Task 0.5: Surface Gaussian mixture optimizer non-convergence as a warning

**Files:**
- Modify: `RVUtils/ImpliedDistribution/_gaussian_mixture.py` — `extract_gaussian_mixture` function
- Test: `tests/test_implied_distribution_gm_warnings.py` (new)

**Step 1: Read the source first**

Run `Read` on `RVUtils/ImpliedDistribution/_gaussian_mixture.py` to confirm the function signature and where `result = scipy.optimize.minimize(...)` is invoked. Identify the exact line where `GaussianMixtureResult(...)` is constructed.

**Step 2: Write the failing test**

```python
# tests/test_implied_distribution_gm_warnings.py
import datetime
import numpy as np
from unittest.mock import patch

import scipy.optimize

from RVUtils.ImpliedDistribution import RNDInput, FedScenarioConfig
from RVUtils.ImpliedDistribution._gaussian_mixture import extract_gaussian_mixture


def _input() -> RNDInput:
    strikes = np.linspace(95.0, 98.0, 13)
    fwd = 96.5
    premiums = np.maximum(fwd - strikes, 0.0) + 0.3 * np.exp(-((strikes - fwd) ** 2) / 0.5)
    return RNDInput(
        symbol="SFRZ26", as_of=datetime.date(2026, 4, 28),
        forward_price=fwd, forward_rate=100 - fwd, time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
        strikes_price=strikes, call_premiums=premiums, strike_source="test",
    )


def test_gm_non_convergence_emits_warning():
    cfg = FedScenarioConfig.default_sofr_scenarios(current_rate=3.5)
    real_minimize = scipy.optimize.minimize

    def fake_minimize(*args, **kwargs):
        # Run the real optimizer once, then mark success=False on result
        result = real_minimize(*args, **kwargs)
        result.success = False
        result.message = "test forced failure"
        return result

    with patch("scipy.optimize.minimize", side_effect=fake_minimize):
        gm = extract_gaussian_mixture(_input(), config=cfg)

    assert any("converge" in w.lower() or "fail" in w.lower() for w in gm.warnings), \
        f"expected non-convergence warning, got: {gm.warnings}"


def test_gm_success_no_warning():
    cfg = FedScenarioConfig.default_sofr_scenarios(current_rate=3.5)
    gm = extract_gaussian_mixture(_input(), config=cfg)
    if gm.optimization_success:
        non_conv = [w for w in gm.warnings if "converge" in w.lower()]
        assert len(non_conv) == 0
```

**Step 3: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_implied_distribution_gm_warnings.py -v`
Expected: FAIL.

**Step 4: Implement minimal change**

In `_gaussian_mixture.py`, build a `warnings: List[str]` list before the `GaussianMixtureResult(...)` construction. After the optimizer call:

```python
warnings: List[str] = []
if not result.success:
    warnings.append(
        f"GM optimizer failed to converge: {result.message}"
    )
```

Also add a check: if `rmse_price > some_threshold` (say 0.001 in price units = 1bp normal vol equivalent at the median strike), emit a "fit quality" warning. Use a config-able threshold default `gm_rmse_warn_threshold=1e-3`.

Pass `warnings=tuple(warnings)` to `GaussianMixtureResult(...)`.

**Step 5: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_implied_distribution_gm_warnings.py -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add tests/test_implied_distribution_gm_warnings.py RVUtils/ImpliedDistribution/_gaussian_mixture.py
git commit -m "fix(implied-dist): warn when Gaussian-mixture optimizer fails"
```

---

### Task 0.6: Document American-exercise limitation + run regression tests

**Files:**
- Modify: `RVUtils/ImpliedDistribution/implied_distribution.py` — class docstring of `SFRImpliedDistribution`
- Modify: `RVUtils/ImpliedDistribution/__init__.py` — module docstring (add caveat note)

**Step 1: Add docstring caveat**

Read `RVUtils/ImpliedDistribution/implied_distribution.py`. Add a caveat block to the `SFRImpliedDistribution` class docstring:

```
Caveats and known limitations
-----------------------------
* Bachelier European pricing only. SR3 options are American on the future,
  but for short-dated instruments the early-exercise premium is small and
  ignored here. Avoid relying on this module for options with less than ~10
  business days to expiry.
* Wing extrapolation uses calibrated SABR plus linear "ghost" anchor points.
  This is *not* SVI or rational interpolation. Tails are sensitive to the
  SABR β/ρ/ν parameters; check ``BreedenLitzenbergerResult.warnings`` for
  truncation or clipping flags before relying on extreme percentiles.
* The default ``rate_floor=0.0`` truncates SOFR density below zero. Mass lost
  to truncation is reported in ``BreedenLitzenbergerResult.warnings``; the
  reported ``mean_rate``/``std_rate`` are computed on the truncated domain.
```

**Step 2: Run the full BL/GM regression suite**

```bash
conda run -n stir pytest tests/test_implied_distribution_warnings.py tests/test_implied_distribution_percentile.py tests/test_implied_distribution_clipping_warning.py tests/test_implied_distribution_gm_warnings.py -v
```

Expected: ALL PASS.

**Step 3: Commit**

```bash
git add RVUtils/ImpliedDistribution/implied_distribution.py RVUtils/ImpliedDistribution/__init__.py
git commit -m "docs(implied-dist): document American-exercise + wing extrapolation caveats"
```

---

## Phase 1: Screener package scaffolding

### Task 1.1: Create package skeleton + types

**Files:**
- Create: `RVUtils/SFRConvexScreener/__init__.py`
- Create: `RVUtils/SFRConvexScreener/_types.py`
- Test: `tests/test_sfr_convex_screener_types.py` (new)

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_types.py
import datetime
import pytest

from RVUtils.SFRConvexScreener import (
    Leg,
    StructureDef,
    StructureType,
    JointMethod,
    SFRConvexScreenerConfig,
)


def test_leg_is_frozen():
    leg = Leg(contract="SFRZ26", weight=1.0, price=96.5, dv01=25.0)
    with pytest.raises(Exception):
        leg.weight = 2.0  # frozen dataclass should reject


def test_structure_type_enum_values():
    assert StructureType.CALENDAR.value == "calendar"
    assert StructureType.BUTTERFLY.value == "butterfly"


def test_joint_method_enum_values():
    assert JointMethod.COMMON_STATE.value == "common_state"
    assert JointMethod.HISTORICAL_GAUSSIAN_COPULA.value == "historical_gaussian_copula"


def test_config_defaults():
    cfg = SFRConvexScreenerConfig()
    assert cfg.universe_size == 12  # whites + reds + greens
    assert cfg.calendar_gaps == (1, 2, 4)
    assert cfg.fly_gaps == (1, 2, 4)
    assert cfg.correlation_window == 60
    assert cfg.n_simulations == 100_000
    assert JointMethod.COMMON_STATE in cfg.joint_methods
    assert JointMethod.HISTORICAL_GAUSSIAN_COPULA in cfg.joint_methods
    assert cfg.score_weights == (0.4, 0.2, 0.3, 0.1)


def test_structure_def_id_canonical():
    sd = StructureDef(
        structure_id="SFRZ26_SFRH27_FLY_1_-2_1",
        structure_type=StructureType.BUTTERFLY,
        legs=(
            Leg(contract="SFRZ26", weight=1, price=96.5, dv01=25),
            Leg(contract="SFRH27", weight=-2, price=96.6, dv01=25),
            Leg(contract="SFRM27", weight=1, price=96.7, dv01=25),
        ),
    )
    assert sd.structure_type is StructureType.BUTTERFLY
    assert len(sd.legs) == 3
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_types.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement minimal types**

```python
# RVUtils/SFRConvexScreener/_types.py
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


class StructureType(Enum):
    CALENDAR = "calendar"
    BUTTERFLY = "butterfly"


class JointMethod(Enum):
    COMMON_STATE = "common_state"           # existing JointDistributionSnapshot
    HISTORICAL_GAUSSIAN_COPULA = "historical_gaussian_copula"
    PERFECT_CORRELATION = "perfect_correlation"  # design-doc Phase 1 sanity baseline


@dataclass(frozen=True)
class Leg:
    contract: str
    weight: float
    price: float
    dv01: float = 25.0


@dataclass(frozen=True)
class StructureDef:
    structure_id: str
    structure_type: StructureType
    legs: Tuple[Leg, ...]


@dataclass
class SFRConvexScreenerConfig:
    # Universe
    universe_size: int = 12       # whites(4) + reds(4) + greens(4)
    calendar_gaps: Tuple[int, ...] = (1, 2, 4)
    fly_gaps: Tuple[int, ...] = (1, 2, 4)

    # Curve / data sources
    curve_source: str = "BARCHART_STIRF-RL"
    curve_name: str = "USD-SOFR-1D-Q12STIRT"
    options_source: str = "BARCHART_STIRFO-QL"

    # Joint distribution
    joint_methods: Tuple[JointMethod, ...] = (
        JointMethod.COMMON_STATE,
        JointMethod.HISTORICAL_GAUSSIAN_COPULA,
        JointMethod.PERFECT_CORRELATION,
    )
    primary_joint_method: JointMethod = JointMethod.COMMON_STATE
    correlation_window: int = 60
    n_simulations: int = 100_000

    # Carry / horizon
    horizon_days: int = 63   # ~3M
    historical_lookback_years: int = 5

    # Filters
    min_open_interest_per_leg: int = 5_000
    min_avg_daily_volume_per_leg: int = 1_000
    max_bid_ask_bp: float = 0.5
    min_carry_adjusted_ev_bp: float = 0.5

    # Scoring weights: (asymmetry, p_profit, ev+carry, tail_ratio)
    score_weights: Tuple[float, float, float, float] = (0.4, 0.2, 0.3, 0.1)

    # Output
    output_root: str = "data/screener_results/sfr_convex_screener"

    # Seed for reproducibility of copula sampling
    random_seed: int = 17
```

```python
# RVUtils/SFRConvexScreener/__init__.py
from RVUtils.SFRConvexScreener._types import (
    JointMethod,
    Leg,
    SFRConvexScreenerConfig,
    StructureDef,
    StructureType,
)

__all__ = [
    "JointMethod",
    "Leg",
    "SFRConvexScreenerConfig",
    "StructureDef",
    "StructureType",
]
```

**Step 4: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_types.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/__init__.py RVUtils/SFRConvexScreener/_types.py tests/test_sfr_convex_screener_types.py
git commit -m "feat(sfr-screener): scaffold types and config"
```

---

### Task 1.2: Universe enumeration

**Files:**
- Create: `RVUtils/SFRConvexScreener/_universe.py`
- Modify: `RVUtils/SFRConvexScreener/__init__.py`
- Test: `tests/test_sfr_convex_screener_universe.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_universe.py
from RVUtils.SFRConvexScreener import (
    JointMethod,
    SFRConvexScreenerConfig,
    StructureType,
)
from RVUtils.SFRConvexScreener._universe import (
    enumerate_calendars,
    enumerate_butterflies,
    enumerate_structures,
)


SYMBOLS = ["SFRM26", "SFRU26", "SFRZ26", "SFRH27"]  # 4 contracts ordered by expiry


def test_calendars_with_gap_1_produces_three_pairs():
    cals = enumerate_calendars(SYMBOLS, gap=1)
    assert len(cals) == 3
    ids = [s.structure_id for s in cals]
    assert "SFRM26_SFRU26_CAL_1" in ids
    assert "SFRZ26_SFRH27_CAL_1" in ids


def test_calendar_legs_have_pm_one_weights():
    cals = enumerate_calendars(SYMBOLS, gap=1)
    for s in cals:
        weights = [leg.weight for leg in s.legs]
        assert weights == [1.0, -1.0]


def test_calendars_skip_when_gap_too_large():
    cals = enumerate_calendars(SYMBOLS, gap=4)
    assert cals == []


def test_butterflies_with_gap_1_produces_two():
    flies = enumerate_butterflies(SYMBOLS, gap=1)
    assert len(flies) == 2
    weights_set = [tuple(leg.weight for leg in f.legs) for f in flies]
    assert (1.0, -2.0, 1.0) in weights_set


def test_butterfly_id_format():
    flies = enumerate_butterflies(SYMBOLS, gap=1)
    assert all("FLY_1_-2_1" in f.structure_id for f in flies)


def test_enumerate_structures_uses_config_gaps():
    cfg = SFRConvexScreenerConfig(calendar_gaps=(1,), fly_gaps=(1,))
    structures = enumerate_structures(SYMBOLS, cfg)
    n_cals = sum(1 for s in structures if s.structure_type is StructureType.CALENDAR)
    n_flies = sum(1 for s in structures if s.structure_type is StructureType.BUTTERFLY)
    assert n_cals == 3
    assert n_flies == 2
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_universe.py -v`
Expected: FAIL.

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_universe.py
from __future__ import annotations

from typing import List, Sequence, Tuple

from RVUtils.SFRConvexScreener._types import (
    Leg,
    SFRConvexScreenerConfig,
    StructureDef,
    StructureType,
)


def _make_leg(contract: str, weight: float) -> Leg:
    # price/dv01 filled in later from market data
    return Leg(contract=contract, weight=float(weight), price=float("nan"), dv01=25.0)


def enumerate_calendars(symbols: Sequence[str], gap: int) -> List[StructureDef]:
    out: List[StructureDef] = []
    n = len(symbols)
    for i in range(n - gap):
        front, back = symbols[i], symbols[i + gap]
        out.append(
            StructureDef(
                structure_id=f"{front}_{back}_CAL_{gap}",
                structure_type=StructureType.CALENDAR,
                legs=(_make_leg(front, 1.0), _make_leg(back, -1.0)),
            )
        )
    return out


def enumerate_butterflies(symbols: Sequence[str], gap: int) -> List[StructureDef]:
    out: List[StructureDef] = []
    n = len(symbols)
    for i in range(n - 2 * gap):
        a, b, c = symbols[i], symbols[i + gap], symbols[i + 2 * gap]
        out.append(
            StructureDef(
                structure_id=f"{a}_{b}_{c}_FLY_1_-2_1",
                structure_type=StructureType.BUTTERFLY,
                legs=(_make_leg(a, 1.0), _make_leg(b, -2.0), _make_leg(c, 1.0)),
            )
        )
    return out


def enumerate_structures(
    symbols: Sequence[str], config: SFRConvexScreenerConfig
) -> List[StructureDef]:
    out: List[StructureDef] = []
    for g in config.calendar_gaps:
        out.extend(enumerate_calendars(symbols, g))
    for g in config.fly_gaps:
        out.extend(enumerate_butterflies(symbols, g))
    return out
```

Update `__init__.py` to re-export the three functions.

**Step 4: Run test to verify it passes**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_universe.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_universe.py RVUtils/SFRConvexScreener/__init__.py tests/test_sfr_convex_screener_universe.py
git commit -m "feat(sfr-screener): enumerate calendar + butterfly universe"
```

---

### Task 1.3: Market data loader (thin wrapper around existing MDP)

**Files:**
- Create: `RVUtils/SFRConvexScreener/_market_data.py`
- Modify: `RVUtils/SFRConvexScreener/__init__.py`
- Test: `tests/test_sfr_convex_screener_market_data.py` — *integration smoke test* gated by `pytest.mark.integration` to avoid hammering Barchart in CI.

**Step 1: Write the failing test (integration-marked)**

```python
# tests/test_sfr_convex_screener_market_data.py
import datetime
import pytest

from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig
from RVUtils.SFRConvexScreener._market_data import (
    SFRMarketData,
    load_market_data,
    resolve_universe_symbols,
)


@pytest.mark.integration
def test_load_market_data_smoke():
    cfg = SFRConvexScreenerConfig()
    md = load_market_data(cfg, as_of=datetime.date(2026, 4, 28))
    assert isinstance(md, SFRMarketData)
    assert len(md.symbols) == cfg.universe_size
    assert md.curve_handle is not None
    assert not md.futures_df.empty
    assert "price" in md.futures_df.columns
    assert "open_interest" in md.futures_df.columns
    assert md.price_panel.shape[0] >= cfg.correlation_window // 2  # at least half the window populated


@pytest.mark.integration
def test_resolve_universe_symbols_returns_12_sr3():
    cfg = SFRConvexScreenerConfig()
    syms = resolve_universe_symbols(cfg, as_of=datetime.date(2026, 4, 28))
    assert len(syms) == 12
    for s in syms:
        assert s.startswith("SFR")  # canonical name
```

**Step 2: Run test to verify it fails**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_market_data.py -v -m integration`
Expected: FAIL — module not implemented.

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_market_data.py
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import _next_contracts, _imm_cutoff

from RVUtils.SFRConvexScreener._types import SFRConvexScreenerConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SFRMarketData:
    as_of: datetime.date
    symbols: Tuple[str, ...]                  # SFR* canonical names
    sr3_symbols: Tuple[str, ...]              # SR3* canonical (used internally)
    curve_handle: Any
    futures_df: pd.DataFrame                  # index=SFR symbol, cols: price, rate, open_interest, volume, effective, maturity
    price_panel: pd.DataFrame                 # index=date, cols=SFR symbols (60d history)
    smiles: Dict[str, Any]                    # SFR symbol → STIRFutureOptionSABRSmile
    warnings: Tuple[str, ...] = ()


def _sr3_to_sfr(sym: str) -> str:
    # SR3Z26 → SFRZ26
    return sym.replace("SR3", "SFR", 1)


def _sfr_to_sr3(sym: str) -> str:
    return sym.replace("SFR", "SR3", 1)


def resolve_universe_symbols(
    config: SFRConvexScreenerConfig, *, as_of: datetime.date
) -> Tuple[str, ...]:
    sr3_syms = _next_contracts(
        as_of, prefix="SR3", count=config.universe_size,
        valid_months=[3, 6, 9, 12], cutoff_fn=_imm_cutoff,
    )
    return tuple(_sr3_to_sfr(s) for s in sr3_syms)


def load_market_data(
    config: SFRConvexScreenerConfig, *, as_of: datetime.date
) -> SFRMarketData:
    sfr_symbols = resolve_universe_symbols(config, as_of=as_of)
    sr3_symbols = tuple(_sfr_to_sr3(s) for s in sfr_symbols)
    warnings: List[str] = []

    # 1. Curve
    curve_mdp = IRSwapsMDP(source=config.curve_source)
    curve_handle = curve_mdp.get_pricer(
        request={"curve_name": config.curve_name, "timestamp": as_of}
    )

    # 2. Futures snapshot (price + OI)
    fut_mdp = STIRFutureMDP(source=config.curve_source)
    snap = fut_mdp.get_data({"symbols": list(sr3_symbols), "timestamp": as_of})
    rows: List[Dict[str, Any]] = []
    for sr3, sfr in zip(sr3_symbols, sfr_symbols):
        pricers = snap.get(sr3) or []
        if not pricers:
            warnings.append(f"missing futures snapshot for {sr3}")
            continue
        p = pricers[0]
        rows.append({
            "symbol": sfr,
            "price": float(p._price),
            "rate": float(p._rate),
            "open_interest": p._meta_data.get("openinterest"),
            "volume": p._meta_data.get("volume"),
            "effective": p._effective_date,
            "maturity": p._maturity_date,
        })
    futures_df = pd.DataFrame(rows).set_index("symbol")

    # 3. Historical 60-day price panel
    bdate_range = pd.bdate_range(end=as_of, periods=config.correlation_window).date.tolist()
    bulk = fut_mdp.get_bulk_data({
        "symbols": list(sr3_symbols),
        "timestamps": bdate_range,
        "max_workers": 8,
    })
    rows_panel: Dict[datetime.date, Dict[str, float]] = {}
    for d, by_sym in (bulk or {}).items():
        rows_panel[d] = {}
        for sr3, sfr in zip(sr3_symbols, sfr_symbols):
            pricers = (by_sym or {}).get(sr3) or []
            if pricers:
                rows_panel[d][sfr] = float(pricers[0]._price)
    price_panel = pd.DataFrame(rows_panel).T.sort_index()

    # 4. SABR smiles per contract
    opt_mdp = STIRFutureOptionMDP(source=config.options_source)
    smiles: Dict[str, Any] = {}
    for sfr in sfr_symbols:
        try:
            smile = opt_mdp.fetch_sabr_smile({
                "symbol": sfr, "as_of": as_of, "strike_offsets_bps": "listed",
            })
            smiles[sfr] = smile
        except Exception as e:  # noqa: BLE001
            logger.warning("SABR smile fetch failed for %s: %s", sfr, e)
            warnings.append(f"smile fetch failed for {sfr}: {e}")

    return SFRMarketData(
        as_of=as_of,
        symbols=sfr_symbols,
        sr3_symbols=sr3_symbols,
        curve_handle=curve_handle,
        futures_df=futures_df,
        price_panel=price_panel,
        smiles=smiles,
        warnings=tuple(warnings),
    )
```

Add `pytest.ini` registration of the `integration` marker if not already present.

**Step 4: Verify the integration test passes**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_market_data.py -v -m integration`
Expected: PASS (requires live data access). If running offline, document that the integration tests are skipped and verify import-only:
`conda run -n stir python -c "from RVUtils.SFRConvexScreener._market_data import load_market_data; print('ok')"`

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_market_data.py RVUtils/SFRConvexScreener/__init__.py tests/test_sfr_convex_screener_market_data.py
git commit -m "feat(sfr-screener): market data loader using existing MDP infra"
```

---

## Phase 2: Distribution and metrics

### Task 2.1: Per-contract BL extraction wrapper

**Files:**
- Create: `RVUtils/SFRConvexScreener/_distributions.py`
- Test: `tests/test_sfr_convex_screener_distributions.py`

**Step 1: Write the failing test**

Use a tiny synthetic smile (build a `STIRFutureOptionSABRSmile`-shaped object via `MagicMock` with the attributes `SFRImpliedDistribution.extract` reads).

```python
# tests/test_sfr_convex_screener_distributions.py
import datetime
import numpy as np
import pytest

from RVUtils.ImpliedDistribution import RNDInput, BreedenLitzenbergerResult
from RVUtils.SFRConvexScreener._distributions import (
    extract_bl_marginals,
    PerContractDistribution,
)


def _bl_with_uniform(symbol: str, mean: float = 3.5) -> BreedenLitzenbergerResult:
    grid = np.linspace(mean - 1.0, mean + 1.0, 1001)
    density = np.ones_like(grid) / 2.0
    cdf = np.linspace(0.0, 1.0, 1001)
    return BreedenLitzenbergerResult(
        input=RNDInput(
            symbol=symbol, as_of=datetime.date(2026, 4, 28),
            forward_price=100 - mean, forward_rate=mean, time_to_expiry=0.5,
            expiry_date=datetime.date(2026, 12, 14), discount_factor=1.0,
            strikes_price=np.array([95.0]), call_premiums=np.array([0.5]),
            strike_source="test",
        ),
        strike_grid_rate=grid,
        rnd_density=density,
        rnd_cumulative=cdf,
        bin_edges_rate=np.array([mean - 0.5, mean + 0.5]),
        bin_probabilities=np.array([1.0]),
        bin_labels=[f"{mean:.2f}"],
        mean_rate=mean,
        std_rate=1 / np.sqrt(3),
        skewness=0.0, kurtosis=1.8,
        smoothing_param=1e-4, n_ghost_points=10, spline_residual=0.0,
    )


def test_per_contract_distribution_holds_grid_and_density():
    bl = _bl_with_uniform("SFRZ26", 3.5)
    d = PerContractDistribution(symbol="SFRZ26", bl=bl)
    grid, density = d.rate_grid, d.density
    assert len(grid) == 1001
    assert np.isclose(density.sum() * (grid[1] - grid[0]), 1.0, atol=1e-3)


def test_extract_bl_marginals_skips_failures(monkeypatch):
    """If SFRImpliedDistribution.extract raises, log warning and continue."""
    bl_z = _bl_with_uniform("SFRZ26", 3.5)
    bl_h = _bl_with_uniform("SFRH27", 3.6)
    fake_smiles = {"SFRZ26": object(), "SFRH27": object(), "SFRM27": object()}

    class _FakeID:
        def extract(self, smile):
            # Use object identity to decide return
            if smile is fake_smiles["SFRM27"]:
                raise RuntimeError("induced failure")
            from RVUtils.ImpliedDistribution import ImpliedDistributionSnapshot
            sym = "SFRZ26" if smile is fake_smiles["SFRZ26"] else "SFRH27"
            bl = bl_z if sym == "SFRZ26" else bl_h
            return ImpliedDistributionSnapshot(
                symbol=sym, as_of=datetime.date(2026, 4, 28),
                bl_result=bl, gm_result=None,
            )

    out = extract_bl_marginals(fake_smiles, dist_extractor=_FakeID())
    assert "SFRZ26" in out and "SFRH27" in out
    assert "SFRM27" not in out
```

**Step 2: Run test (expect FAIL)**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_distributions.py -v`
Expected: FAIL.

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_distributions.py
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from RVUtils.ImpliedDistribution import (
    BreedenLitzenbergerResult,
    FedScenarioConfig,
    ImpliedDistributionSnapshot,
    JointDistributionSnapshot,
    SFRImpliedDistribution,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PerContractDistribution:
    symbol: str
    bl: BreedenLitzenbergerResult

    @property
    def rate_grid(self) -> np.ndarray:
        return self.bl.strike_grid_rate

    @property
    def density(self) -> np.ndarray:
        return self.bl.rnd_density


def extract_bl_marginals(
    smiles: Mapping[str, Any],
    *,
    dist_extractor: Optional[Any] = None,
    scenario_config: Optional[FedScenarioConfig] = None,
) -> Dict[str, PerContractDistribution]:
    """Run BL extraction on each smile. Fail-soft per contract."""
    if dist_extractor is None:
        scenarios = scenario_config or FedScenarioConfig.default_sofr_scenarios()
        dist_extractor = SFRImpliedDistribution(scenario_config=scenarios)

    out: Dict[str, PerContractDistribution] = {}
    for symbol, smile in smiles.items():
        try:
            snap: ImpliedDistributionSnapshot = dist_extractor.extract(smile)
        except Exception as exc:  # noqa: BLE001
            logger.warning("BL extraction failed for %s: %s", symbol, exc)
            continue
        if snap.bl_result is None:
            logger.warning("no BL result for %s", symbol)
            continue
        out[symbol] = PerContractDistribution(symbol=symbol, bl=snap.bl_result)
    return out
```

**Step 4: Run test (PASS)**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_distributions.py -v`

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_distributions.py tests/test_sfr_convex_screener_distributions.py
git commit -m "feat(sfr-screener): per-contract BL marginal wrapper"
```

---

### Task 2.2: Joint payoff PDF — common-state path

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_distributions.py` (add joint helpers)
- Test: extend `tests/test_sfr_convex_screener_distributions.py`

**Step 1: Write the failing test**

```python
def test_payoff_pdf_common_state_returns_array_with_finite_support():
    """Build a tiny JointDistributionSnapshot stub and verify linear-combination
    distribution dispatch."""
    # Use a real JointDistributionSnapshot if you can construct one cheaply with
    # 2 symbols × 3 states; otherwise mock the linear_combination_distribution.
    from unittest.mock import MagicMock
    from RVUtils.ImpliedDistribution import AnnotatedResult, ViewMetadata
    from RVUtils.SFRConvexScreener._distributions import (
        payoff_pdf_common_state,
    )
    from RVUtils.SFRConvexScreener import Leg

    fake_outcomes = np.array([-5.0, 0.0, 7.0])
    fake_probs = np.array([0.3, 0.4, 0.3])
    snap = MagicMock(spec=["linear_combination_distribution"])
    snap.linear_combination_distribution.return_value = AnnotatedResult(
        data=pd.DataFrame({"value": fake_outcomes, "probability": fake_probs}),
        metadata=ViewMetadata(support="exact"),
    )

    legs = (
        Leg(contract="SFRZ26", weight=1, price=96.5, dv01=25),
        Leg(contract="SFRH27", weight=-2, price=96.6, dv01=25),
        Leg(contract="SFRM27", weight=1, price=96.7, dv01=25),
    )
    outcomes_bp, probs = payoff_pdf_common_state(legs, joint=snap)

    snap.linear_combination_distribution.assert_called_once()
    call_kwargs = snap.linear_combination_distribution.call_args.kwargs or snap.linear_combination_distribution.call_args[1]
    weights = (snap.linear_combination_distribution.call_args.args[0]
               if snap.linear_combination_distribution.call_args.args
               else call_kwargs["weights"])
    assert weights == {"SFRZ26": 1, "SFRH27": -2, "SFRM27": 1}
    np.testing.assert_allclose(probs.sum(), 1.0, atol=1e-9)
    np.testing.assert_allclose(outcomes_bp, fake_outcomes * 100.0)  # convert % to bp
```

**Step 2: Run test**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_distributions.py::test_payoff_pdf_common_state_returns_array_with_finite_support -v`
Expected: FAIL.

**Step 3: Implement**

```python
# Append to RVUtils/SFRConvexScreener/_distributions.py
from typing import Iterable, Sequence
from RVUtils.SFRConvexScreener._types import Leg


def payoff_pdf_common_state(
    legs: Sequence[Leg],
    *,
    joint: JointDistributionSnapshot,
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute the structure payoff PDF using the existing common-state joint.

    Returns
    -------
    outcomes_bp : np.ndarray
        Linear-combination outcomes converted to basis points.
    probs : np.ndarray
        Discrete probabilities summing to 1.
    """
    weights = {leg.contract: float(leg.weight) for leg in legs}
    annotated = joint.linear_combination_distribution(weights)
    df: pd.DataFrame = annotated.data
    outcomes_pct = df["value"].to_numpy()
    probs = df["probability"].to_numpy()
    # Rates from BL/joint are in percent; convert to bp
    outcomes_bp = outcomes_pct * 100.0
    return outcomes_bp, probs
```

**Step 4: Run test**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_distributions.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_distributions.py tests/test_sfr_convex_screener_distributions.py
git commit -m "feat(sfr-screener): common-state structure payoff PDF"
```

---

### Task 2.3: Joint payoff PDF — historical Gaussian copula path

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_distributions.py`
- Test: extend `tests/test_sfr_convex_screener_distributions.py`

**Step 1: Write the failing test**

```python
def test_payoff_pdf_gaussian_copula_recovers_expected_mean_for_independent_uniform():
    """Independent uniform marginals: 1*X1 - 1*X2 has mean 0, std sqrt(2)/sqrt(3)*range."""
    from RVUtils.SFRConvexScreener._distributions import (
        payoff_pdf_historical_gaussian_copula,
    )
    rng = np.random.default_rng(seed=42)
    grid = np.linspace(-1.0, 1.0, 1001)
    density = np.full_like(grid, 0.5)
    cdf = np.linspace(0.0, 1.0, 1001)
    bl_a = _bl_with_uniform("SFRZ26", 0.0)  # uniform [-1,+1] approx via existing helper
    bl_a = BreedenLitzenbergerResult(
        input=bl_a.input, strike_grid_rate=grid, rnd_density=density, rnd_cumulative=cdf,
        bin_edges_rate=bl_a.bin_edges_rate, bin_probabilities=bl_a.bin_probabilities,
        bin_labels=bl_a.bin_labels, mean_rate=0.0, std_rate=1/np.sqrt(3),
        skewness=0.0, kurtosis=1.8, smoothing_param=1e-4,
        n_ghost_points=10, spline_residual=0.0,
    )
    bl_b = _bl_with_uniform("SFRH27", 0.0)
    bl_b = BreedenLitzenbergerResult(
        input=bl_b.input, strike_grid_rate=grid, rnd_density=density, rnd_cumulative=cdf,
        bin_edges_rate=bl_b.bin_edges_rate, bin_probabilities=bl_b.bin_probabilities,
        bin_labels=bl_b.bin_labels, mean_rate=0.0, std_rate=1/np.sqrt(3),
        skewness=0.0, kurtosis=1.8, smoothing_param=1e-4,
        n_ghost_points=10, spline_residual=0.0,
    )
    marginals = {
        "SFRZ26": PerContractDistribution(symbol="SFRZ26", bl=bl_a),
        "SFRH27": PerContractDistribution(symbol="SFRH27", bl=bl_b),
    }
    legs = (
        Leg(contract="SFRZ26", weight=1, price=99.0, dv01=25),
        Leg(contract="SFRH27", weight=-1, price=99.0, dv01=25),
    )
    corr = pd.DataFrame(np.eye(2), index=["SFRZ26", "SFRH27"], columns=["SFRZ26", "SFRH27"])
    samples_bp = payoff_pdf_historical_gaussian_copula(
        legs, marginals=marginals, corr_matrix=corr, n_sim=20_000, rng=rng,
    )
    assert abs(samples_bp.mean()) < 5.0  # mean near 0 (in bp)
    # std of (X1 - X2), each U(-1,1)% → 1/sqrt(3)% each → std difference = sqrt(2/3)% = ~81.6 bp
    assert 70.0 < samples_bp.std() < 95.0
```

**Step 2: Run test**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_distributions.py::test_payoff_pdf_gaussian_copula_recovers_expected_mean_for_independent_uniform -v`
Expected: FAIL.

**Step 3: Implement**

```python
# Append to RVUtils/SFRConvexScreener/_distributions.py
from scipy.stats import norm


def _inverse_marginal_cdf(bl: BreedenLitzenbergerResult, u: np.ndarray) -> np.ndarray:
    """Vectorized inverse-CDF lookup on the BL grid."""
    return np.interp(u, bl.rnd_cumulative, bl.strike_grid_rate)


def payoff_pdf_historical_gaussian_copula(
    legs: Sequence[Leg],
    *,
    marginals: Mapping[str, PerContractDistribution],
    corr_matrix: pd.DataFrame,
    n_sim: int = 100_000,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """Sample structure payoffs in basis points using a Gaussian copula on
    historical correlations and BL marginals.

    Returns
    -------
    samples_bp : np.ndarray of shape (n_sim,)
    """
    rng = rng or np.random.default_rng()
    contracts = [leg.contract for leg in legs]
    weights = np.array([leg.weight for leg in legs])

    # Align correlation matrix to leg order
    sub = corr_matrix.reindex(index=contracts, columns=contracts).to_numpy()
    if not np.all(np.isfinite(sub)):
        # Fall back to identity if any pair is missing
        sub = np.eye(len(contracts))
    # Symmetric PSD safety: nudge eigenvalues
    sub = (sub + sub.T) / 2.0
    eig, vec = np.linalg.eigh(sub)
    eig = np.clip(eig, 1e-8, None)
    L = vec @ np.diag(np.sqrt(eig))

    z = rng.standard_normal(size=(n_sim, len(contracts))) @ L.T
    u = norm.cdf(z)
    rates_pct = np.empty_like(u)
    for i, contract in enumerate(contracts):
        rates_pct[:, i] = _inverse_marginal_cdf(marginals[contract].bl, u[:, i])

    # Linear combination in % rate space, convert to bp
    payoff_pct = rates_pct @ weights
    # Subtract current structure level so the distribution is P&L-relative
    current_pct = np.array([marginals[c].bl.input.forward_rate for c in contracts]) @ weights
    return (payoff_pct - current_pct) * 100.0
```

**Step 4: Run test**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_distributions.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_distributions.py tests/test_sfr_convex_screener_distributions.py
git commit -m "feat(sfr-screener): Gaussian-copula payoff sampler"
```

---

### Task 2.4: Perfect-correlation (Phase-1 sanity) payoff helper

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_distributions.py`
- Test: extend `tests/test_sfr_convex_screener_distributions.py`

**Step 1: Write the failing test**

```python
def test_payoff_pdf_perfect_correlation_uses_front_marginal_only():
    """All legs move with the same shift — payoff = sum(weights) * shift."""
    from RVUtils.SFRConvexScreener._distributions import payoff_pdf_perfect_correlation
    bl = _bl_with_uniform("SFRZ26", 3.5)
    marginals = {
        "SFRZ26": PerContractDistribution(symbol="SFRZ26", bl=bl),
        "SFRH27": PerContractDistribution(symbol="SFRH27", bl=bl),
        "SFRM27": PerContractDistribution(symbol="SFRM27", bl=bl),
    }
    legs = (
        Leg(contract="SFRZ26", weight=1, price=96.5, dv01=25),
        Leg(contract="SFRH27", weight=-2, price=96.5, dv01=25),
        Leg(contract="SFRM27", weight=1, price=96.5, dv01=25),
    )
    outcomes_bp, probs = payoff_pdf_perfect_correlation(legs, marginals=marginals)
    # Sum of weights = 0 → fly P&L = 0 at every shift → outcomes all 0
    np.testing.assert_allclose(outcomes_bp, np.zeros_like(outcomes_bp), atol=1e-6)
    np.testing.assert_allclose(probs.sum(), 1.0, atol=1e-6)
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
def payoff_pdf_perfect_correlation(
    legs: Sequence[Leg],
    *,
    marginals: Mapping[str, PerContractDistribution],
) -> Tuple[np.ndarray, np.ndarray]:
    """Phase-1 baseline: assume all legs move by the same shift, weight by the
    front contract's marginal."""
    front_bl = marginals[legs[0].contract].bl
    shifts_pct = front_bl.strike_grid_rate - front_bl.input.forward_rate
    # Weighted sum of (forward + shift) - sum(weights * forward) = shift * sum(weights)
    sum_weights = sum(leg.weight for leg in legs)
    payoff_bp = shifts_pct * sum_weights * 100.0

    density = front_bl.rnd_density.copy()
    dx = np.diff(front_bl.strike_grid_rate)
    probs = np.zeros_like(density)
    if len(dx) > 0:
        probs[:-1] = 0.5 * (density[:-1] + density[1:]) * dx
        probs[-1] = probs[-2] if len(probs) > 1 else 1.0
    total = probs.sum()
    if total > 0:
        probs = probs / total
    return payoff_bp, probs
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_distributions.py tests/test_sfr_convex_screener_distributions.py
git commit -m "feat(sfr-screener): perfect-correlation Phase-1 baseline"
```

---

### Task 2.5: Payoff metrics

**Files:**
- Create: `RVUtils/SFRConvexScreener/_metrics.py`
- Test: `tests/test_sfr_convex_screener_metrics.py`

**Step 1: Write the failing test** (full set of metrics required by Section 3.3)

```python
# tests/test_sfr_convex_screener_metrics.py
import numpy as np
import pytest

from RVUtils.SFRConvexScreener._metrics import (
    PayoffMetrics,
    metrics_from_samples,
    metrics_from_pdf,
)


def test_metrics_from_samples_symmetric_normal_has_unit_asymmetry():
    rng = np.random.default_rng(0)
    samples = rng.standard_normal(50_000) * 10.0  # std 10 bp, mean 0
    m = metrics_from_samples(samples)
    assert abs(m.mean_bp) < 0.5
    assert 9 < m.std_bp < 11
    assert abs(m.skew) < 0.05
    assert 0.95 < m.asymmetry_ratio < 1.05
    assert 0.95 < m.tail_ratio < 1.10
    assert abs(m.p_profit - 0.5) < 0.01


def test_metrics_from_samples_skewed_has_asymmetry_above_one():
    rng = np.random.default_rng(0)
    # Right-skewed: exponential - 1
    samples = (rng.exponential(scale=10.0, size=50_000) - 10.0)
    m = metrics_from_samples(samples)
    assert m.asymmetry_ratio > 1.5


def test_metrics_percentile_fields():
    rng = np.random.default_rng(0)
    samples = rng.standard_normal(100_000) * 10.0
    m = metrics_from_samples(samples)
    # 5/95 of N(0, 10): roughly ±16.45
    assert -18 < m.percentiles_bp["p5"] < -14
    assert 14 < m.percentiles_bp["p95"] < 18


def test_metrics_from_pdf_matches_sampled_metrics_uniform():
    grid = np.linspace(-50.0, 50.0, 2001)
    density = np.ones_like(grid) / 100.0  # uniform [-50, 50] in bp
    probs = np.full_like(grid, 1.0 / len(grid))
    m_pdf = metrics_from_pdf(grid, probs)
    rng = np.random.default_rng(0)
    samples = rng.uniform(-50, 50, size=200_000)
    m_samp = metrics_from_samples(samples)
    assert abs(m_pdf.mean_bp - m_samp.mean_bp) < 1.0
    assert abs(m_pdf.std_bp - m_samp.std_bp) < 1.0
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_metrics.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


@dataclass(frozen=True)
class PayoffMetrics:
    mean_bp: float
    std_bp: float
    skew: float
    excess_kurtosis: float
    p_profit: float
    ev_given_profit_bp: float
    ev_given_loss_bp: float
    asymmetry_ratio: float
    percentiles_bp: Dict[str, float]
    tail_ratio: float

    def to_dict(self) -> Dict[str, float]:
        d = {
            "mean_bp": self.mean_bp,
            "std_bp": self.std_bp,
            "skew": self.skew,
            "excess_kurt": self.excess_kurtosis,
            "p_profit": self.p_profit,
            "ev_given_profit_bp": self.ev_given_profit_bp,
            "ev_given_loss_bp": self.ev_given_loss_bp,
            "asymmetry_ratio": self.asymmetry_ratio,
            "tail_ratio": self.tail_ratio,
        }
        d.update({f"pct_{k}": v for k, v in self.percentiles_bp.items()})
        return d


def _percentiles(samples: np.ndarray) -> Dict[str, float]:
    pcts = np.percentile(samples, [5, 25, 50, 75, 95])
    return {"p5": float(pcts[0]), "p25": float(pcts[1]), "p50": float(pcts[2]),
            "p75": float(pcts[3]), "p95": float(pcts[4])}


def _asymmetry_ratio(samples: np.ndarray) -> Tuple[float, float, float, float]:
    pos = samples[samples > 0]
    neg = samples[samples < 0]
    p_profit = len(pos) / len(samples)
    ev_pos = float(pos.mean()) if pos.size else 0.0
    ev_neg = float(neg.mean()) if neg.size else 0.0
    upper = ev_pos * (len(pos) / len(samples))
    lower = abs(ev_neg * (len(neg) / len(samples)))
    asym = upper / lower if lower > 0 else float("inf")
    return p_profit, ev_pos, ev_neg, asym


def metrics_from_samples(samples: np.ndarray) -> PayoffMetrics:
    samples = np.asarray(samples, dtype=float)
    mean = float(samples.mean())
    std = float(samples.std(ddof=1))
    if std > 0:
        z = (samples - mean) / std
        skew = float((z ** 3).mean())
        excess_kurt = float((z ** 4).mean()) - 3.0
    else:
        skew = 0.0
        excess_kurt = 0.0

    p_profit, ev_pos, ev_neg, asym = _asymmetry_ratio(samples)
    pcts = _percentiles(samples)
    tail = abs(pcts["p95"]) / abs(pcts["p5"]) if pcts["p5"] != 0 else float("inf")
    return PayoffMetrics(
        mean_bp=mean, std_bp=std, skew=skew, excess_kurtosis=excess_kurt,
        p_profit=p_profit, ev_given_profit_bp=ev_pos, ev_given_loss_bp=ev_neg,
        asymmetry_ratio=asym, percentiles_bp=pcts, tail_ratio=tail,
    )


def metrics_from_pdf(outcomes_bp: np.ndarray, probs: np.ndarray) -> PayoffMetrics:
    """Compute the same metrics from a discrete PDF (no Monte Carlo)."""
    outcomes_bp = np.asarray(outcomes_bp, dtype=float)
    probs = np.asarray(probs, dtype=float)
    probs = probs / probs.sum()
    mean = float((outcomes_bp * probs).sum())
    var = float(((outcomes_bp - mean) ** 2 * probs).sum())
    std = float(np.sqrt(max(var, 0.0)))
    if std > 0:
        skew = float(((outcomes_bp - mean) ** 3 * probs).sum() / (std ** 3))
        excess_kurt = float(((outcomes_bp - mean) ** 4 * probs).sum() / (std ** 4)) - 3.0
    else:
        skew = 0.0
        excess_kurt = 0.0
    p_profit = float(probs[outcomes_bp > 0].sum())
    ev_pos = float((outcomes_bp[outcomes_bp > 0] * probs[outcomes_bp > 0]).sum() /
                   max(probs[outcomes_bp > 0].sum(), 1e-12))
    ev_neg = float((outcomes_bp[outcomes_bp < 0] * probs[outcomes_bp < 0]).sum() /
                   max(probs[outcomes_bp < 0].sum(), 1e-12))
    upper = ev_pos * p_profit
    lower = abs(ev_neg * (1.0 - p_profit))
    asym = upper / lower if lower > 0 else float("inf")
    cdf = np.cumsum(probs)
    pct_levels = [0.05, 0.25, 0.50, 0.75, 0.95]
    pct_vals = [float(np.interp(p, cdf, outcomes_bp)) for p in pct_levels]
    pcts = dict(zip(["p5", "p25", "p50", "p75", "p95"], pct_vals))
    tail = abs(pcts["p95"]) / abs(pcts["p5"]) if pcts["p5"] != 0 else float("inf")
    return PayoffMetrics(
        mean_bp=mean, std_bp=std, skew=skew, excess_kurtosis=excess_kurt,
        p_profit=p_profit, ev_given_profit_bp=ev_pos, ev_given_loss_bp=ev_neg,
        asymmetry_ratio=asym, percentiles_bp=pcts, tail_ratio=tail,
    )
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_metrics.py tests/test_sfr_convex_screener_metrics.py
git commit -m "feat(sfr-screener): payoff distribution metrics"
```

---

### Task 2.6: IV/RV diagnostics

**Files:**
- Create: `RVUtils/SFRConvexScreener/_ivrv.py`
- Test: `tests/test_sfr_convex_screener_ivrv.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_ivrv.py
import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener._ivrv import (
    IVRVDiagnostic,
    realized_vol_bp,
    iv_rv_diagnostic,
)


def test_realized_vol_bp_matches_simple_std():
    rng = np.random.default_rng(0)
    # Daily moves of std 1 bp → annualized = sqrt(252) bp ≈ 15.87
    daily_changes_bp = rng.standard_normal(63)  # 1 bp std
    rv = realized_vol_bp(pd.Series(daily_changes_bp))
    assert 14.0 < rv < 18.0


def test_iv_rv_diagnostic_returns_ratio():
    iv_bp = 80.0
    rv_bp = 65.0
    diag = iv_rv_diagnostic("SFRZ26", iv_bp=iv_bp, rv_bp=rv_bp)
    assert diag.contract == "SFRZ26"
    assert abs(diag.iv_rv_ratio - (iv_bp / rv_bp)) < 1e-9
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_ivrv.py
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IVRVDiagnostic:
    contract: str
    iv_bp: float
    rv_bp: float
    iv_rv_ratio: float


def realized_vol_bp(daily_rate_changes_bp: pd.Series, *, periods_per_year: int = 252) -> float:
    """Annualize a series of daily *rate* changes (bp) into bp/yr realized vol."""
    s = daily_rate_changes_bp.dropna()
    if len(s) < 2:
        return float("nan")
    return float(s.std(ddof=1) * np.sqrt(periods_per_year))


def iv_rv_diagnostic(contract: str, *, iv_bp: float, rv_bp: float) -> IVRVDiagnostic:
    ratio = iv_bp / rv_bp if rv_bp > 0 else float("inf")
    return IVRVDiagnostic(contract=contract, iv_bp=iv_bp, rv_bp=rv_bp, iv_rv_ratio=ratio)
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_ivrv.py tests/test_sfr_convex_screener_ivrv.py
git commit -m "feat(sfr-screener): IV/RV diagnostics helper"
```

---

### Task 2.7: Historical realized payoff distribution (5y comparison)

**Files:**
- Create: `RVUtils/SFRConvexScreener/_historical.py`
- Test: `tests/test_sfr_convex_screener_historical.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_historical.py
import datetime
import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener import Leg
from RVUtils.SFRConvexScreener._historical import (
    rolling_structure_payoffs_bp,
    historical_asymmetry_summary,
)


def test_rolling_structure_payoffs_simple_pair():
    dates = pd.bdate_range("2025-01-01", periods=200)
    df = pd.DataFrame({
        "SFRZ26": np.linspace(96.0, 96.5, 200),  # ↑ 50 bp linearly
        "SFRH27": np.linspace(96.5, 96.0, 200),  # ↓ 50 bp linearly
    }, index=dates)
    legs = (Leg("SFRZ26", 1, 96.0, 25), Leg("SFRH27", -1, 96.0, 25))
    series = rolling_structure_payoffs_bp(df, legs=legs, horizon_days=63)
    assert isinstance(series, pd.Series)
    # Net move over 63 days: front +(63/200*50) - (-(63/200*50)) ≈ 31.5 bp
    assert 25 < series.dropna().mean() < 40
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_historical.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener._types import Leg


@dataclass(frozen=True)
class HistoricalAsymmetry:
    median_asymmetry: float
    p95_asymmetry: float
    n_observations: int
    current_rn_percentile: float


def rolling_structure_payoffs_bp(
    price_panel: pd.DataFrame,
    *,
    legs: Sequence[Leg],
    horizon_days: int = 63,
) -> pd.Series:
    """For each date in price_panel, compute the structure P&L (in bp) over the
    next ``horizon_days`` business days."""
    contracts = [leg.contract for leg in legs]
    weights = np.array([leg.weight for leg in legs])
    sub = price_panel[contracts].dropna(how="any")
    # Convert price → rate (rate = 100 - price)
    rate_panel = 100.0 - sub
    # Forward-shift to compute horizon return
    horizon_rate_change = rate_panel.shift(-horizon_days) - rate_panel
    payoff_pct = horizon_rate_change.to_numpy() @ weights
    series = pd.Series(payoff_pct * 100.0, index=sub.index, name="payoff_bp")
    return series


def historical_asymmetry_summary(
    samples_bp: pd.Series, *, current_rn_asymmetry: float,
) -> HistoricalAsymmetry:
    s = samples_bp.dropna()
    if len(s) < 5:
        return HistoricalAsymmetry(
            median_asymmetry=float("nan"), p95_asymmetry=float("nan"),
            n_observations=len(s), current_rn_percentile=float("nan"),
        )
    # Compute *empirical* asymmetry on a rolling basis would require many windows;
    # for v1, summarize the realized payoff distribution directly: report the
    # ratio of upper-half partial expectation to lower-half magnitude using all data.
    pos = s[s > 0]
    neg = s[s < 0]
    realized_asym = (
        (pos.mean() * len(pos) / len(s)) /
        max(abs(neg.mean() * len(neg) / len(s)), 1e-12)
    ) if len(neg) else float("inf")
    pct = float((s.rank().iloc[-1] / len(s))) if len(s) else float("nan")
    return HistoricalAsymmetry(
        median_asymmetry=float(realized_asym),
        p95_asymmetry=float(realized_asym),  # placeholder until rolling impl in Phase 2
        n_observations=len(s),
        current_rn_percentile=pct,
    )
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_historical.py tests/test_sfr_convex_screener_historical.py
git commit -m "feat(sfr-screener): historical realized payoff helper"
```

---

### Task 2.8: Carry / roll-down for a structure

**Files:**
- Create: `RVUtils/SFRConvexScreener/_carry.py`
- Test: `tests/test_sfr_convex_screener_carry.py` (unit test the *math*; integration test with curve goes later)

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_carry.py
import numpy as np

from RVUtils.SFRConvexScreener import Leg
from RVUtils.SFRConvexScreener._carry import structure_pnl_from_rates_bp


def test_fly_pnl_zero_when_curve_unchanged():
    legs = (Leg("A", 1, 96.5, 25), Leg("B", -2, 96.6, 25), Leg("C", 1, 96.7, 25))
    rates_now = {"A": 3.5, "B": 3.4, "C": 3.3}
    rates_then = dict(rates_now)
    assert abs(structure_pnl_from_rates_bp(legs, rates_now=rates_now, rates_then=rates_then)) < 1e-9


def test_fly_pnl_positive_when_belly_richens():
    """Fly = front + back - 2*belly. If belly drops 5 bp, fly P&L = +10 bp."""
    legs = (Leg("A", 1, 96.5, 25), Leg("B", -2, 96.6, 25), Leg("C", 1, 96.7, 25))
    rates_now = {"A": 3.5, "B": 3.4, "C": 3.3}
    rates_then = {"A": 3.5, "B": 3.35, "C": 3.3}  # belly down 5 bp
    pnl_bp = structure_pnl_from_rates_bp(legs, rates_now=rates_now, rates_then=rates_then)
    assert abs(pnl_bp - 10.0) < 1e-6
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_carry.py
from __future__ import annotations

from typing import Mapping, Sequence

from RVUtils.SFRConvexScreener._types import Leg


def structure_pnl_from_rates_bp(
    legs: Sequence[Leg],
    *,
    rates_now: Mapping[str, float],
    rates_then: Mapping[str, float],
) -> float:
    """P&L (bp) of the structure given two rate snapshots (% units).

    Convention: structure rate = sum(weight * rate). P&L for a *received*
    structure is (rate_now - rate_then), in bp.
    """
    rate_now = sum(leg.weight * rates_now[leg.contract] for leg in legs)
    rate_then = sum(leg.weight * rates_then[leg.contract] for leg in legs)
    return (rate_now - rate_then) * 100.0
```

For the curve-aware roll-down (3M roll-down assuming curve shape unchanged), we'll use the existing `IRSwapValue.ROLL_BPS_RUNNING` via `IRSwapQuery` — wired into `_market_data.py` in Phase 4.

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_carry.py tests/test_sfr_convex_screener_carry.py
git commit -m "feat(sfr-screener): structure P&L from rate snapshots"
```

---

## Phase 3: Scoring, filtering, ranking

### Task 3.1: Cross-sectional z-score normalization + composite score

**Files:**
- Create: `RVUtils/SFRConvexScreener/_scoring.py`
- Test: `tests/test_sfr_convex_screener_scoring.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_scoring.py
import numpy as np
import pandas as pd

from RVUtils.SFRConvexScreener._scoring import zscore, composite_score_series


def test_zscore_zero_mean_unit_std():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = zscore(s)
    assert abs(z.mean()) < 1e-9
    assert abs(z.std(ddof=0) - 1.0) < 1e-9


def test_zscore_handles_zero_variance():
    s = pd.Series([3.0, 3.0, 3.0])
    z = zscore(s)
    assert (z == 0.0).all()


def test_composite_score_weighted_sum():
    df = pd.DataFrame({
        "asymmetry": [1.0, 2.0, 3.0],
        "p_profit": [0.5, 0.6, 0.7],
        "ev_carry": [0.1, 0.2, 0.3],
        "tail_ratio": [1.0, 1.5, 2.0],
    })
    weights = (0.4, 0.2, 0.3, 0.1)
    score = composite_score_series(df, weights=weights, columns=("asymmetry", "p_profit", "ev_carry", "tail_ratio"))
    # Largest in every dimension → top score
    assert score.idxmax() == 2
    assert score.idxmin() == 0
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_scoring.py
from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np
import pandas as pd


def zscore(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    sd = s.std(ddof=0)
    if not np.isfinite(sd) or sd <= 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / sd


def composite_score_series(
    df: pd.DataFrame,
    *,
    weights: Sequence[float],
    columns: Sequence[str],
) -> pd.Series:
    if len(weights) != len(columns):
        raise ValueError("weights and columns must have same length")
    z_df = pd.concat([zscore(df[c]) for c in columns], axis=1)
    z_df.columns = list(columns)
    return z_df.mul(list(weights), axis=1).sum(axis=1)
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_scoring.py tests/test_sfr_convex_screener_scoring.py
git commit -m "feat(sfr-screener): cross-sectional z-score and composite score"
```

---

### Task 3.2: Filter pipeline

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_scoring.py` (add filter)
- Test: extend `tests/test_sfr_convex_screener_scoring.py`

**Step 1: Write the failing test**

```python
def test_filter_excludes_below_oi_threshold():
    from RVUtils.SFRConvexScreener._scoring import apply_liquidity_filters
    df = pd.DataFrame({
        "structure_id": ["A_B_CAL_1", "C_D_CAL_1"],
        "min_leg_oi": [10_000, 1_000],          # second below 5_000 default
        "min_leg_volume": [5_000, 500],
        "max_leg_bid_ask_bp": [0.2, 0.6],
        "carry_adjusted_ev_bp": [1.0, -2.0],    # second below 0.5 default
    })
    out = apply_liquidity_filters(df,
        min_open_interest_per_leg=5_000,
        min_avg_daily_volume_per_leg=1_000,
        max_bid_ask_bp=0.5,
        min_carry_adjusted_ev_bp=0.5,
    )
    assert list(out["structure_id"]) == ["A_B_CAL_1"]
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
def apply_liquidity_filters(
    df: pd.DataFrame,
    *,
    min_open_interest_per_leg: int,
    min_avg_daily_volume_per_leg: int,
    max_bid_ask_bp: float,
    min_carry_adjusted_ev_bp: float,
) -> pd.DataFrame:
    """Drop rows that fail any of the configured liquidity / EV filters.
    Expects columns: min_leg_oi, min_leg_volume, max_leg_bid_ask_bp, carry_adjusted_ev_bp.
    Missing columns are treated as pass-through (do not exclude on missing data)."""
    mask = pd.Series(True, index=df.index)
    if "min_leg_oi" in df.columns:
        mask &= df["min_leg_oi"].fillna(np.inf) >= min_open_interest_per_leg
    if "min_leg_volume" in df.columns:
        mask &= df["min_leg_volume"].fillna(np.inf) >= min_avg_daily_volume_per_leg
    if "max_leg_bid_ask_bp" in df.columns:
        mask &= df["max_leg_bid_ask_bp"].fillna(-np.inf) <= max_bid_ask_bp
    if "carry_adjusted_ev_bp" in df.columns:
        mask &= df["carry_adjusted_ev_bp"].fillna(-np.inf) >= min_carry_adjusted_ev_bp
    return df.loc[mask].copy()
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_scoring.py tests/test_sfr_convex_screener_scoring.py
git commit -m "feat(sfr-screener): liquidity and EV filter pipeline"
```

---

## Phase 4: Top-level orchestrator + I/O

### Task 4.1: Result containers (`StructureResult`, `SFRConvexScreenerSnapshot`)

**Files:**
- Modify: `RVUtils/SFRConvexScreener/_types.py`
- Test: `tests/test_sfr_convex_screener_results.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_results.py
import datetime
from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics


def _trivial_metrics() -> PayoffMetrics:
    return PayoffMetrics(
        mean_bp=1.0, std_bp=5.0, skew=0.5, excess_kurtosis=1.0,
        p_profit=0.55, ev_given_profit_bp=4.0, ev_given_loss_bp=-3.0,
        asymmetry_ratio=1.5, percentiles_bp={"p5": -8, "p25": -2, "p50": 1, "p75": 5, "p95": 11},
        tail_ratio=1.4,
    )


def test_structure_result_to_dict_roundtrip():
    sd = StructureDef(
        structure_id="A_B_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("A", 1, 96.5, 25), Leg("B", -1, 96.6, 25)),
    )
    r = StructureResult(
        structure_def=sd,
        metrics_by_method={"common_state": _trivial_metrics()},
        primary_method="common_state",
        carry_3m_bp=1.0,
        rolldown_3m_bp=0.5,
        iv_rv_diagnostics=(),
        historical=None,
        warnings=("liquidity flag",),
        composite_score=0.7,
        rank=3,
    )
    d = r.to_dict()
    assert d["structure_id"] == "A_B_CAL_1"
    assert d["composite_score"] == 0.7
    assert "common_state" in d["metrics_by_method"]


def test_snapshot_to_dataframe():
    sd = StructureDef(
        structure_id="A_B_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("A", 1, 96.5, 25), Leg("B", -1, 96.6, 25)),
    )
    r = StructureResult(
        structure_def=sd,
        metrics_by_method={"common_state": _trivial_metrics()},
        primary_method="common_state",
        carry_3m_bp=1.0, rolldown_3m_bp=0.5,
        iv_rv_diagnostics=(), historical=None, warnings=(),
        composite_score=0.7, rank=1,
    )
    snap = SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28),
        results=(r,),
        config_summary={"universe_size": 12},
    )
    df = snap.to_dataframe()
    assert df.shape[0] == 1
    assert "structure_id" in df.columns
    assert "asymmetry_ratio" in df.columns
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# Append to RVUtils/SFRConvexScreener/_types.py
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics  # at top
from RVUtils.SFRConvexScreener._ivrv import IVRVDiagnostic
from RVUtils.SFRConvexScreener._historical import HistoricalAsymmetry


@dataclass(frozen=True)
class StructureResult:
    structure_def: StructureDef
    metrics_by_method: Dict[str, PayoffMetrics]
    primary_method: str
    carry_3m_bp: float
    rolldown_3m_bp: float
    iv_rv_diagnostics: Tuple[IVRVDiagnostic, ...]
    historical: Optional[HistoricalAsymmetry]
    warnings: Tuple[str, ...]
    composite_score: float
    rank: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structure_id": self.structure_def.structure_id,
            "structure_type": self.structure_def.structure_type.value,
            "legs": [
                {"contract": l.contract, "weight": l.weight, "price": l.price, "dv01": l.dv01}
                for l in self.structure_def.legs
            ],
            "carry_3m_bp": self.carry_3m_bp,
            "rolldown_3m_bp": self.rolldown_3m_bp,
            "metrics_by_method": {
                name: m.to_dict() for name, m in self.metrics_by_method.items()
            },
            "primary_method": self.primary_method,
            "iv_rv_diagnostics": [
                {"contract": d.contract, "iv_bp": d.iv_bp,
                 "rv_bp": d.rv_bp, "iv_rv_ratio": d.iv_rv_ratio}
                for d in self.iv_rv_diagnostics
            ],
            "historical": (
                None if self.historical is None
                else {
                    "median_asymmetry": self.historical.median_asymmetry,
                    "p95_asymmetry": self.historical.p95_asymmetry,
                    "n_observations": self.historical.n_observations,
                    "current_rn_percentile": self.historical.current_rn_percentile,
                }
            ),
            "warnings": list(self.warnings),
            "composite_score": self.composite_score,
            "rank": self.rank,
        }


@dataclass(frozen=True)
class SFRConvexScreenerSnapshot:
    as_of: datetime.date
    results: Tuple[StructureResult, ...]
    config_summary: Dict[str, Any]
    run_warnings: Tuple[str, ...] = ()

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for r in self.results:
            primary = r.metrics_by_method.get(r.primary_method)
            row = {
                "structure_id": r.structure_def.structure_id,
                "type": r.structure_def.structure_type.value,
                "rank": r.rank,
                "composite_score": r.composite_score,
                "carry_3m_bp": r.carry_3m_bp,
                "rolldown_3m_bp": r.rolldown_3m_bp,
                "primary_method": r.primary_method,
            }
            if primary is not None:
                row.update(primary.to_dict())
            rows.append(row)
        return pd.DataFrame(rows)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "config": self.config_summary,
            "run_warnings": list(self.run_warnings),
            "results": [r.to_dict() for r in self.results],
        }
```

Re-export from `__init__.py`.

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_types.py RVUtils/SFRConvexScreener/__init__.py tests/test_sfr_convex_screener_results.py
git commit -m "feat(sfr-screener): result containers"
```

---

### Task 4.2: Top-level orchestrator (`build_snapshot`)

**Files:**
- Create: `RVUtils/SFRConvexScreener/screener.py`
- Modify: `RVUtils/SFRConvexScreener/__init__.py`
- Test: `tests/test_sfr_convex_screener_orchestrator.py` (integration-marked)

**Step 1: Write the failing test (integration-marked smoke test)**

```python
# tests/test_sfr_convex_screener_orchestrator.py
import datetime
import pytest

from RVUtils.SFRConvexScreener import SFRConvexScreenerConfig, build_snapshot


@pytest.mark.integration
def test_build_snapshot_smoke():
    cfg = SFRConvexScreenerConfig(universe_size=4, calendar_gaps=(1,), fly_gaps=(1,))
    snap = build_snapshot(cfg, as_of=datetime.date(2026, 4, 28))
    assert snap.as_of == datetime.date(2026, 4, 28)
    assert len(snap.results) > 0
    df = snap.to_dataframe()
    assert "asymmetry_ratio" in df.columns
    assert df["composite_score"].notna().all()
```

**Step 2: Run test (FAIL)**

**Step 3: Implement (sketch — flesh out in implementation)**

```python
# RVUtils/SFRConvexScreener/screener.py
from __future__ import annotations

import datetime
import logging
from dataclasses import asdict
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.ImpliedDistribution import (
    FedScenarioConfig,
    JointDistributionSnapshot,
    SFRImpliedDistribution,
)
from RVUtils.SFRConvexScreener._types import (
    JointMethod,
    Leg,
    SFRConvexScreenerConfig,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
)
from RVUtils.SFRConvexScreener._universe import enumerate_structures
from RVUtils.SFRConvexScreener._market_data import load_market_data
from RVUtils.SFRConvexScreener._distributions import (
    extract_bl_marginals,
    payoff_pdf_common_state,
    payoff_pdf_historical_gaussian_copula,
    payoff_pdf_perfect_correlation,
)
from RVUtils.SFRConvexScreener._metrics import (
    PayoffMetrics,
    metrics_from_pdf,
    metrics_from_samples,
)
from RVUtils.SFRConvexScreener._ivrv import realized_vol_bp, iv_rv_diagnostic
from RVUtils.SFRConvexScreener._historical import (
    rolling_structure_payoffs_bp,
    historical_asymmetry_summary,
)
from RVUtils.SFRConvexScreener._carry import structure_pnl_from_rates_bp
from RVUtils.SFRConvexScreener._scoring import (
    apply_liquidity_filters,
    composite_score_series,
)

logger = logging.getLogger(__name__)


def _historical_correlation_matrix(
    price_panel: pd.DataFrame, *, window: int
) -> pd.DataFrame:
    rate_panel = 100.0 - price_panel
    daily_changes = rate_panel.diff().dropna(how="any").tail(window)
    if len(daily_changes) < 5:
        # Insufficient history → identity
        return pd.DataFrame(
            np.eye(price_panel.shape[1]),
            index=price_panel.columns, columns=price_panel.columns,
        )
    return daily_changes.corr()


def _calibrate_joint(
    smiles: Dict[str, object], *, as_of: datetime.date,
) -> Optional[JointDistributionSnapshot]:
    """Use the existing strip-fitting entry point. If unsupported by the current
    public API, return None and downstream code falls back to copula-only."""
    try:
        from RVUtils.ImpliedDistribution.implied_distribution import (
            SFRImpliedDistribution,
        )
        # The public API for joint calibration is `SFRImpliedDistribution.fit_joint(smiles)` —
        # confirm the actual entry point name during implementation; if it differs,
        # update the call accordingly.
        scenarios = FedScenarioConfig.default_sofr_scenarios()
        dist = SFRImpliedDistribution(scenario_config=scenarios)
        # If a `fit_joint` or `fit_strip` method exists, use it; otherwise wire
        # through `_joint_calibration.calibrate_joint_distribution` directly.
        return dist.fit_joint(smiles, as_of=as_of)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Joint calibration failed; falling back to copula only: %s", exc)
        return None


def build_snapshot(
    config: SFRConvexScreenerConfig, *, as_of: datetime.date,
) -> SFRConvexScreenerSnapshot:
    md = load_market_data(config, as_of=as_of)
    structures = enumerate_structures(md.symbols, config)
    if not structures:
        return SFRConvexScreenerSnapshot(
            as_of=as_of, results=(), config_summary=_config_summary(config),
            run_warnings=("no structures enumerated",),
        )

    # 1. BL marginals
    marginals = extract_bl_marginals(md.smiles)

    # 2. Joint snapshot (common-state) — best-effort
    joint_snapshot = (
        _calibrate_joint(md.smiles, as_of=as_of)
        if JointMethod.COMMON_STATE in config.joint_methods else None
    )

    # 3. Historical correlation
    corr = _historical_correlation_matrix(md.price_panel, window=config.correlation_window)
    rng = np.random.default_rng(config.random_seed)

    # 4. Per-structure analytics
    rows: List[Dict] = []
    results_intermediate: List[Dict] = []
    for s in structures:
        # Skip structures touching contracts with missing marginals
        if any(leg.contract not in marginals for leg in s.legs):
            logger.warning("skipping %s — missing marginal", s.structure_id)
            continue

        metrics_by_method: Dict[str, PayoffMetrics] = {}

        if JointMethod.COMMON_STATE in config.joint_methods and joint_snapshot is not None:
            try:
                outcomes_bp, probs = payoff_pdf_common_state(s.legs, joint=joint_snapshot)
                metrics_by_method["common_state"] = metrics_from_pdf(outcomes_bp, probs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("common-state PDF failed for %s: %s", s.structure_id, exc)

        if JointMethod.HISTORICAL_GAUSSIAN_COPULA in config.joint_methods:
            try:
                samples = payoff_pdf_historical_gaussian_copula(
                    s.legs, marginals=marginals, corr_matrix=corr,
                    n_sim=config.n_simulations, rng=rng,
                )
                metrics_by_method["historical_gaussian_copula"] = metrics_from_samples(samples)
            except Exception as exc:  # noqa: BLE001
                logger.warning("copula PDF failed for %s: %s", s.structure_id, exc)

        if JointMethod.PERFECT_CORRELATION in config.joint_methods:
            try:
                outcomes_bp, probs = payoff_pdf_perfect_correlation(s.legs, marginals=marginals)
                metrics_by_method["perfect_correlation"] = metrics_from_pdf(outcomes_bp, probs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("perfect-corr PDF failed for %s: %s", s.structure_id, exc)

        if not metrics_by_method:
            logger.warning("no metrics produced for %s — skipping", s.structure_id)
            continue

        primary_method = config.primary_joint_method.value
        if primary_method not in metrics_by_method:
            primary_method = next(iter(metrics_by_method))

        # Carry / roll: use ROLL_BPS_RUNNING per-leg via existing IRSwapQuery helpers.
        # For the first cut, set both to NaN and wire in Phase 4 follow-up.
        carry_bp = float("nan")
        rolldown_bp = float("nan")

        # IV/RV
        ivrv: List = []
        for leg in s.legs:
            bl = marginals[leg.contract].bl
            iv_bp = bl.std_rate * 100.0 / np.sqrt(max(bl.input.time_to_expiry, 1e-6))  # rough conversion
            rv_series = (100.0 - md.price_panel[leg.contract]).diff() * 100.0
            rv_bp = realized_vol_bp(rv_series.tail(21))
            ivrv.append(iv_rv_diagnostic(leg.contract, iv_bp=iv_bp, rv_bp=rv_bp))

        # Historical realized payoff
        try:
            payoff_series = rolling_structure_payoffs_bp(
                md.price_panel, legs=s.legs, horizon_days=config.horizon_days,
            )
            hist = historical_asymmetry_summary(
                payoff_series,
                current_rn_asymmetry=metrics_by_method[primary_method].asymmetry_ratio,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("historical comp failed for %s: %s", s.structure_id, exc)
            hist = None

        results_intermediate.append({
            "structure_def": s,
            "metrics_by_method": metrics_by_method,
            "primary_method": primary_method,
            "carry_3m_bp": carry_bp,
            "rolldown_3m_bp": rolldown_bp,
            "iv_rv_diagnostics": tuple(ivrv),
            "historical": hist,
            "warnings": tuple(),
        })

    # 5. Composite score (cross-sectional z over primary metrics)
    score_df = pd.DataFrame([
        {
            "structure_id": r["structure_def"].structure_id,
            "asymmetry": r["metrics_by_method"][r["primary_method"]].asymmetry_ratio,
            "p_profit": r["metrics_by_method"][r["primary_method"]].p_profit,
            "ev_carry": (r["metrics_by_method"][r["primary_method"]].mean_bp
                         + (r["carry_3m_bp"] if np.isfinite(r["carry_3m_bp"]) else 0.0)),
            "tail_ratio": r["metrics_by_method"][r["primary_method"]].tail_ratio,
        }
        for r in results_intermediate
    ])
    if not score_df.empty:
        scores = composite_score_series(
            score_df, weights=config.score_weights,
            columns=("asymmetry", "p_profit", "ev_carry", "tail_ratio"),
        )
        score_df["composite_score"] = scores.values
        score_df = score_df.sort_values("composite_score", ascending=False)
        score_df["rank"] = np.arange(1, len(score_df) + 1)
        rank_lookup = dict(zip(score_df["structure_id"], score_df["rank"]))
        score_lookup = dict(zip(score_df["structure_id"], score_df["composite_score"]))
    else:
        rank_lookup, score_lookup = {}, {}

    final = []
    for r in results_intermediate:
        sid = r["structure_def"].structure_id
        final.append(StructureResult(
            structure_def=r["structure_def"],
            metrics_by_method=r["metrics_by_method"],
            primary_method=r["primary_method"],
            carry_3m_bp=r["carry_3m_bp"],
            rolldown_3m_bp=r["rolldown_3m_bp"],
            iv_rv_diagnostics=r["iv_rv_diagnostics"],
            historical=r["historical"],
            warnings=r["warnings"],
            composite_score=float(score_lookup.get(sid, float("nan"))),
            rank=int(rank_lookup.get(sid, 0)),
        ))
    final.sort(key=lambda r: r.rank if r.rank > 0 else 1_000_000)

    return SFRConvexScreenerSnapshot(
        as_of=as_of,
        results=tuple(final),
        config_summary=_config_summary(config),
        run_warnings=md.warnings,
    )


def _config_summary(config: SFRConvexScreenerConfig) -> Dict:
    return {
        "universe_size": config.universe_size,
        "calendar_gaps": list(config.calendar_gaps),
        "fly_gaps": list(config.fly_gaps),
        "joint_methods": [m.value for m in config.joint_methods],
        "primary_joint_method": config.primary_joint_method.value,
        "correlation_window": config.correlation_window,
        "n_simulations": config.n_simulations,
        "horizon_days": config.horizon_days,
        "score_weights": list(config.score_weights),
    }
```

Re-export `build_snapshot` from `__init__.py`.

**Step 4: Run test**

Run: `conda run -n stir pytest tests/test_sfr_convex_screener_orchestrator.py -v -m integration`

If integration test passes (live data available), commit. Otherwise mark as known-blocked and proceed; the function should still import without error.

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/screener.py RVUtils/SFRConvexScreener/__init__.py tests/test_sfr_convex_screener_orchestrator.py
git commit -m "feat(sfr-screener): top-level build_snapshot orchestrator"
```

---

### Task 4.3: CSV + JSON export

**Files:**
- Create: `RVUtils/SFRConvexScreener/_export.py`
- Modify: `RVUtils/SFRConvexScreener/__init__.py`
- Test: `tests/test_sfr_convex_screener_export.py`

**Step 1: Write the failing test**

```python
# tests/test_sfr_convex_screener_export.py
import datetime
import json
from pathlib import Path

import pandas as pd
import pytest

from RVUtils.SFRConvexScreener import (
    Leg,
    SFRConvexScreenerSnapshot,
    StructureDef,
    StructureResult,
    StructureType,
)
from RVUtils.SFRConvexScreener._export import write_snapshot
from RVUtils.SFRConvexScreener._metrics import PayoffMetrics


def _trivial_snapshot() -> SFRConvexScreenerSnapshot:
    sd = StructureDef(
        structure_id="A_B_CAL_1",
        structure_type=StructureType.CALENDAR,
        legs=(Leg("A", 1, 96.5, 25), Leg("B", -1, 96.6, 25)),
    )
    metrics = PayoffMetrics(
        mean_bp=1.0, std_bp=5.0, skew=0.5, excess_kurtosis=1.0,
        p_profit=0.55, ev_given_profit_bp=4.0, ev_given_loss_bp=-3.0,
        asymmetry_ratio=1.5, percentiles_bp={"p5": -8, "p25": -2, "p50": 1, "p75": 5, "p95": 11},
        tail_ratio=1.4,
    )
    r = StructureResult(
        structure_def=sd, metrics_by_method={"common_state": metrics},
        primary_method="common_state", carry_3m_bp=1.0, rolldown_3m_bp=0.5,
        iv_rv_diagnostics=(), historical=None, warnings=(), composite_score=0.7, rank=1,
    )
    return SFRConvexScreenerSnapshot(
        as_of=datetime.date(2026, 4, 28), results=(r,),
        config_summary={"universe_size": 4},
    )


def test_write_snapshot_emits_csv_and_json(tmp_path: Path):
    snap = _trivial_snapshot()
    paths = write_snapshot(snap, root_dir=tmp_path)
    assert paths["csv"].exists()
    assert paths["json"].exists()

    df = pd.read_csv(paths["csv"])
    assert "structure_id" in df.columns
    payload = json.loads(paths["json"].read_text())
    assert payload["as_of"] == "2026-04-28"
    assert payload["results"][0]["structure_id"] == "A_B_CAL_1"
```

**Step 2: Run test (FAIL)**

**Step 3: Implement**

```python
# RVUtils/SFRConvexScreener/_export.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Union

from RVUtils.SFRConvexScreener._types import SFRConvexScreenerSnapshot

logger = logging.getLogger(__name__)


def write_snapshot(
    snapshot: SFRConvexScreenerSnapshot, *, root_dir: Union[str, Path],
) -> Dict[str, Path]:
    root = Path(root_dir) / snapshot.as_of.isoformat()
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / "screener_results.csv"
    json_path = root / "screener_results.json"

    df = snapshot.to_dataframe()
    df.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(snapshot.to_dict(), indent=2, default=str))
    logger.info("snapshot written to %s", root)
    return {"csv": csv_path, "json": json_path}
```

**Step 4: Run test (PASS)**

**Step 5: Commit**

```bash
git add RVUtils/SFRConvexScreener/_export.py RVUtils/SFRConvexScreener/__init__.py tests/test_sfr_convex_screener_export.py
git commit -m "feat(sfr-screener): CSV + JSON export"
```

---

### Task 4.4: Notebook frontend

**Files:**
- Create: `notebooks/rv/run_sfr_convex_screener.ipynb`

**Step 1: Author the notebook**

The notebook is the screener's user interface. It should be self-explanatory and follow the structure of [notebooks/rv/run_sfr_rv_screener.py](notebooks/rv/run_sfr_rv_screener.py) (which is a script, but the cell layout will be obvious from imports). Cells:

1. **Setup**: imports, `sys.path.append("../../")`, NYC tz, `as_of = datetime.date.today()` overrideable.
2. **Config**:
   ```python
   config = SFRConvexScreenerConfig(
       universe_size=12,
       calendar_gaps=(1, 2, 4),
       fly_gaps=(1, 2, 4),
       primary_joint_method=JointMethod.COMMON_STATE,
   )
   ```
3. **Build snapshot**: `snap = build_snapshot(config, as_of=as_of)`.
4. **Top-20 by composite score**:
   ```python
   df = snap.to_dataframe().sort_values("composite_score", ascending=False).head(20)
   df.style.format({"composite_score": "{:.2f}", "asymmetry_ratio": "{:.2f}", ...})
   ```
5. **Top-10 by asymmetry only**: `snap.to_dataframe().sort_values("asymmetry_ratio", ascending=False).head(10)`.
6. **Plot top-5 payoff PDFs**: iterate top-5 results, for each call `payoff_pdf_common_state(...)` and matplotlib bar/line plot. Reuse `plot_linear_combination_distribution` from `RVUtils/ImpliedDistribution/_joint_plotting.py` where applicable.
7. **Plot historical realized payoff comparison** for top-5: side-by-side histogram of RN-implied vs. realized 3M payoffs.
8. **IV/RV heatmap** across the strip: pivot `snap.results[*].iv_rv_diagnostics` into a wide DataFrame and `seaborn.heatmap` (or matplotlib `imshow`).
9. **Persist**: `write_snapshot(snap, root_dir=Path(config.output_root))`.
10. **Caveats markdown cell** at the bottom:
    > Risk-neutral ≠ real-world. Reported asymmetry ratios reflect the option-implied measure; real-world distributions differ by the price of risk. Joint dependence is the largest single source of model error — review both `common_state` and `historical_gaussian_copula` columns when evaluating any structure.

Test the notebook by executing it end-to-end:
```bash
conda run -n stir jupyter nbconvert --to notebook --execute notebooks/rv/run_sfr_convex_screener.ipynb --output run_sfr_convex_screener.ipynb
```

**Step 2: Commit**

```bash
git add notebooks/rv/run_sfr_convex_screener.ipynb
git commit -m "feat(sfr-screener): notebook frontend"
```

---

## Phase 5: Carry / roll-down via curve (follow-up)

### Task 5.1: Wire `IRSwapValue.ROLL_BPS_RUNNING` into the orchestrator

Replace the `carry_bp = float("nan")` placeholders in `screener.py` with real per-leg roll-down extracted from the curve handle, summed using leg weights. Pattern from `notebooks/pricers/sfr.ipynb`:

```python
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

def _structure_carry_bp(legs, *, curve_handle, curve_name, horizon: str = "3m") -> tuple[float, float]:
    carry_bp = 0.0
    roll_bp = 0.0
    for leg in legs:
        # SFRZ26 → IMM_Z2026xIMM_H2027 absolute-maturity tenor
        tenor = _sfr_to_imm_tenor(leg.contract)
        q = IRSwapQuery(curve=curve_name, tenor=tenor).resolve_query(
            "live", pricer_or_curve=curve_handle,
        )
        pkg, rws = q.resolve_package(pricer_or_curve=curve_handle)
        vmap = q.build_value_map(pricer_or_curve=curve_handle, package=pkg, risk_weights=rws)
        carry_bp += leg.weight * vmap.apply(value=IRSwapValue.RATE).real * 100.0
        roll_bp += leg.weight * vmap.apply(
            value=IRSwapValue.ROLL_BPS_RUNNING, horizon=horizon,
        ).real
    return carry_bp, roll_bp
```

Add unit test for `_sfr_to_imm_tenor` (pure string transform) — TDD'able offline. The full carry computation is integration-only.

**Steps:**
- Step 1: Write `_sfr_to_imm_tenor` + unit test (e.g. `SFRZ26 → "IMM_Z2026xIMM_H2027"`).
- Step 2: Wire into `build_snapshot`.
- Step 3: Add integration test.
- Step 4: Commit.

```bash
git commit -m "feat(sfr-screener): wire 3m roll-down via IRSwapQuery"
```

---

## Phase 6: End-to-end verification

### Task 6.1: Full unit suite

```bash
conda run -n stir pytest tests/test_implied_distribution_*.py tests/test_sfr_convex_screener_*.py -v
```

Expected: all unit tests PASS. Integration tests skipped without live data.

### Task 6.2: Full integration smoke

```bash
conda run -n stir pytest tests/test_sfr_convex_screener_*.py -v -m integration
```

Expected: PASS with live BARCHART access; review notebook output manually.

### Task 6.3: Notebook execution

```bash
conda run -n stir jupyter nbconvert --to notebook --execute notebooks/rv/run_sfr_convex_screener.ipynb --output _executed.ipynb
```

Visually inspect: top-20 table populated, top-5 payoff PDFs render, historical comparison plot makes sense, IV/RV heatmap covers all 12 contracts.

### Task 6.4: Final commit

```bash
git add -A
git status   # verify nothing unexpected
git commit -m "chore(sfr-screener): final verification + notebook re-run"
```

---

## File map (final state)

```
RVUtils/
├── ImpliedDistribution/
│   ├── _types.py                     (modified: warnings field, percentile fix)
│   ├── _breeden_litzenberger.py      (modified: clipping + truncation warnings)
│   ├── _gaussian_mixture.py          (modified: non-convergence warning)
│   ├── implied_distribution.py       (modified: caveat docstring)
│   └── ...                           (rest unchanged)
└── SFRConvexScreener/
    ├── __init__.py                   (new)
    ├── _types.py                     (new — config, dataclasses)
    ├── _universe.py                  (new — enumerate cal/fly)
    ├── _market_data.py               (new — MDP wrapper)
    ├── _distributions.py             (new — common-state + copula payoff PDFs)
    ├── _metrics.py                   (new — payoff metrics)
    ├── _ivrv.py                      (new — IV/RV diagnostics)
    ├── _historical.py                (new — 5y realized comparison)
    ├── _carry.py                     (new — structure P&L from rates)
    ├── _scoring.py                   (new — z-score, composite, filters)
    ├── _export.py                    (new — CSV/JSON writer)
    └── screener.py                   (new — top-level build_snapshot)

notebooks/
└── rv/
    └── run_sfr_convex_screener.ipynb (new — frontend)

tests/
├── test_implied_distribution_warnings.py
├── test_implied_distribution_percentile.py
├── test_implied_distribution_clipping_warning.py
├── test_implied_distribution_gm_warnings.py
├── test_sfr_convex_screener_types.py
├── test_sfr_convex_screener_universe.py
├── test_sfr_convex_screener_market_data.py
├── test_sfr_convex_screener_distributions.py
├── test_sfr_convex_screener_metrics.py
├── test_sfr_convex_screener_ivrv.py
├── test_sfr_convex_screener_historical.py
├── test_sfr_convex_screener_carry.py
├── test_sfr_convex_screener_scoring.py
├── test_sfr_convex_screener_results.py
├── test_sfr_convex_screener_export.py
└── test_sfr_convex_screener_orchestrator.py

docs/plans/
└── 2026-04-28-sfr-convex-screener.md (this file)
```

---

## Notes for the executing engineer

- **Run all Python through `conda run -n stir`.** Tests, notebook execution, ad-hoc REPL — all of it.
- **Do not bypass pre-commit hooks.** Investigate failures.
- **Commit per task.** Do not batch.
- **If `JointDistributionSnapshot` calibration entry point name differs** from `SFRImpliedDistribution.fit_joint`, check `RVUtils/ImpliedDistribution/_joint_calibration.py` for the actual public function and wire that in. Update `_calibrate_joint` accordingly.
- **Notebook caveat cell is mandatory** — it surfaces the design doc's RN-vs-RW disclaimer to whoever reads the output.
- **If integration tests fail due to no live data**, mark them skipped via `pytest.mark.integration` and proceed — the unit suite is the gate for correctness.
- **Reference skills as needed:** `superpowers:test-driven-development`, `superpowers:verification-before-completion`, `superpowers:systematic-debugging`.
