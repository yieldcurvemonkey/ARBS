# Swaption Annuity-Duration Correction — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the constant-annuity approximation in `SwaptionExtractor` with a first-order duration correction so that swaption repricing under forward-rate shifts accounts for annuity sensitivity to rates.

**Architecture:** Extend `MarketState` with two optional fields (`annuity_duration`, `swap_tenor_years`) that only `SwaptionExtractor` populates. Modify `UnderlyingShift.mutate()` to adjust `discount` (the annuity/scale) via a first-order Taylor correction when `annuity_duration` is present. Listed-option paths are unaffected (fields stay `None`). No new files — all changes are in existing `Simulation/` module files.

**Tech Stack:** Python 3.13, dataclasses, QuantLib (via existing `pricer.py`), pytest.

---

## Background: The Problem

`SwaptionExtractor.extract()` (in `Simulation/extractors.py:75-99`) computes:

```
scale = base_npv / bachelier_price(..., discount=1.0)
```

This `scale` is the annuity (PVBP × notional) at the **base** market state. It's stored in `MarketState.discount` and held constant across all scenario mutations. When `UnderlyingShift` moves the forward rate, the annuity should change because:

- Annuity = Σ(accrual_i × DF_i) — discount factors depend on rates
- A +100bp shift on a 5Y swap reduces annuity by ~2.5%
- For large scenario grids (±200bp), this introduces meaningful repricing error

**Correction formula (first-order Taylor):**

```
A(F₀ + ΔF) ≈ A₀ × (1 − D_A × ΔF)
```

Where `D_A` is the modified duration of the annuity stream (≈ swap_length / 2 for quarterly payments).

**Why first-order is sufficient:** For typical scenario ranges (±200bp), the duration approximation is accurate to < 1% of annuity. Second-order (convexity) can be added later if needed.

**What this does NOT change:** `BachelierExtractor` for listed STIR/UST options — those use a true discount factor that doesn't depend on forward price. Their `annuity_duration` will be `None`, so `UnderlyingShift` leaves their `discount` untouched.

---

### Task 1: Extend MarketState with Annuity Metadata

**Files:**
- Modify: `Simulation/scenarios.py:9-17`
- Test: `tests/test_simulation_scenarios.py`

**Step 1: Write the failing tests**

Add to `tests/test_simulation_scenarios.py`:

```python
class TestMarketStateAnnuityFields:
    def test_annuity_duration_defaults_to_none(self):
        s = MarketState(forward=0.04, vol_normal=0.01, discount=1e7, tte=1.0)
        assert s.annuity_duration is None
        assert s.swap_tenor_years is None

    def test_annuity_duration_round_trips(self):
        s = MarketState(
            forward=0.04, vol_normal=0.01, discount=1e7, tte=1.0,
            annuity_duration=2.5, swap_tenor_years=5.0,
        )
        assert s.annuity_duration == 2.5
        assert s.swap_tenor_years == 5.0

    def test_annuity_fields_frozen(self):
        s = MarketState(annuity_duration=2.5)
        with pytest.raises(AttributeError):
            s.annuity_duration = 3.0

    def test_replace_preserves_annuity_fields(self):
        from dataclasses import replace
        s = MarketState(forward=0.04, annuity_duration=2.5, swap_tenor_years=5.0)
        s2 = replace(s, forward=0.05)
        assert s2.annuity_duration == 2.5
        assert s2.swap_tenor_years == 5.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation_scenarios.py::TestMarketStateAnnuityFields -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'annuity_duration'`

**Step 3: Write minimal implementation**

In `Simulation/scenarios.py`, add two fields to `MarketState`:

```python
@dataclass(frozen=True)
class MarketState:
    """Flat market snapshot used for analytical repricing."""

    forward: Optional[float] = None
    vol_normal: Optional[float] = None
    discount: Optional[float] = None
    tte: Optional[float] = None
    eval_date: Optional[dt.date] = None
    # Swaption annuity metadata (populated by SwaptionExtractor only)
    annuity_duration: Optional[float] = None   # modified duration of annuity w.r.t. forward rate
    swap_tenor_years: Optional[float] = None   # underlying swap length (for time-decay approximation)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_scenarios.py -v`
Expected: ALL PASS (new tests + existing tests unchanged)

**Step 5: Commit**

```bash
git add Simulation/scenarios.py tests/test_simulation_scenarios.py
git commit -m "feat(simulation): add annuity_duration and swap_tenor_years to MarketState"
```

---

### Task 2: Adjust UnderlyingShift to Apply Duration Correction

**Files:**
- Modify: `Simulation/scenarios.py:30-38` (UnderlyingShift.mutate)
- Test: `tests/test_simulation_scenarios.py`

**Step 1: Write the failing tests**

Add to `tests/test_simulation_scenarios.py`:

```python
class TestUnderlyingShiftAnnuityCorrection:
    def test_no_correction_when_annuity_duration_is_none(self):
        """Listed options: annuity_duration=None → discount unchanged."""
        s = MarketState(forward=95.75, vol_normal=0.005, discount=0.998, tte=0.25)
        result = UnderlyingShift(shift=1.0).mutate(s)
        assert result.forward == pytest.approx(96.75)
        assert result.discount == pytest.approx(0.998)  # unchanged

    def test_correction_applied_when_annuity_duration_present(self):
        """Swaption: annuity_duration=2.5 → discount adjusted for 5Y swap."""
        annuity = 1_000_000.0
        s = MarketState(
            forward=0.04, vol_normal=0.01, discount=annuity,
            tte=1.0, annuity_duration=2.5, swap_tenor_years=5.0,
        )
        # Shift forward by +100bp (0.01)
        result = UnderlyingShift(shift=0.01).mutate(s)
        assert result.forward == pytest.approx(0.05)
        # A' ≈ A₀ × (1 - D × ΔF) = 1e6 × (1 - 2.5 × 0.01) = 975_000
        assert result.discount == pytest.approx(975_000.0)

    def test_correction_negative_shift(self):
        """Rates down → annuity increases."""
        annuity = 1_000_000.0
        s = MarketState(
            forward=0.04, vol_normal=0.01, discount=annuity,
            tte=1.0, annuity_duration=2.5, swap_tenor_years=5.0,
        )
        result = UnderlyingShift(shift=-0.01).mutate(s)
        assert result.forward == pytest.approx(0.03)
        # A' ≈ 1e6 × (1 - 2.5 × (-0.01)) = 1_025_000
        assert result.discount == pytest.approx(1_025_000.0)

    def test_zero_shift_no_correction(self):
        s = MarketState(
            forward=0.04, discount=1e6, annuity_duration=2.5,
        )
        result = UnderlyingShift(shift=0.0).mutate(s)
        assert result.discount == pytest.approx(1e6)

    def test_annuity_fields_preserved_through_mutation(self):
        s = MarketState(
            forward=0.04, vol_normal=0.01, discount=1e6,
            tte=1.0, annuity_duration=2.5, swap_tenor_years=5.0,
        )
        result = UnderlyingShift(shift=0.005).mutate(s)
        assert result.annuity_duration == 2.5
        assert result.swap_tenor_years == 5.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation_scenarios.py::TestUnderlyingShiftAnnuityCorrection -v`
Expected: FAIL — `test_correction_applied_when_annuity_duration_present` fails because discount is unchanged

**Step 3: Write minimal implementation**

Replace `UnderlyingShift.mutate` in `Simulation/scenarios.py`:

```python
@dataclass(frozen=True)
class UnderlyingShift(ScenarioAxis):
    """Shift forward price in absolute price points."""

    shift: float = 0.0

    def mutate(self, market_state: MarketState) -> MarketState:
        if market_state.forward is None or self.shift == 0.0:
            return market_state
        new_forward = float(market_state.forward) + float(self.shift)
        new_discount = market_state.discount
        if (
            market_state.annuity_duration is not None
            and new_discount is not None
        ):
            new_discount = float(new_discount) * (
                1.0 - float(market_state.annuity_duration) * float(self.shift)
            )
        return replace(market_state, forward=new_forward, discount=new_discount)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_scenarios.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add Simulation/scenarios.py tests/test_simulation_scenarios.py
git commit -m "feat(simulation): apply first-order annuity correction in UnderlyingShift"
```

---

### Task 3: Populate Annuity Metadata in SwaptionExtractor.extract()

**Files:**
- Modify: `Simulation/extractors.py:67-99` (SwaptionExtractor.extract)
- Test: `tests/test_simulation_extractors.py`

This task computes `annuity_duration` and `swap_tenor_years` at extraction time. We use the QuantLib swaption's `.annuity()` for the base value, and `leg_swap_length_years()` for the swap term. The duration approximation is:

```
annuity_duration ≈ swap_tenor_years / 2
```

This analytical estimate (mid-point of payment schedule) is accurate within ~10% for typical rate environments and avoids curve-level FD bumps.

**Step 1: Write the failing tests**

Add to `tests/test_simulation_extractors.py`:

```python
class TestSwaptionExtractorAnnuityMetadata:
    """Test that SwaptionExtractor populates annuity_duration and swap_tenor_years."""

    def test_extract_sets_annuity_duration(self):
        """Mock a pricer context with known annuity and swap length."""
        from unittest.mock import patch, MagicMock
        from Simulation.extractors import SwaptionExtractor
        from Simulation.scenarios import MarketState

        leg = SimpleNamespace(
            option_type="payer",
            strike=0.04,
            exercise_date=datetime.date(2027, 3, 16),
            underlying_effective_date=datetime.date(2027, 3, 18),
            underlying_maturity_date=datetime.date(2032, 3, 18),
            notional=10_000_000.0,
        )
        mock_context = MagicMock()
        mock_context.as_of_date = datetime.date(2026, 3, 16)

        with patch("Simulation.extractors.leg_forward_rate", return_value=0.04), \
             patch("Simulation.extractors.leg_model_vol", return_value=0.0060), \
             patch("Simulation.extractors.leg_tte_years", return_value=1.0), \
             patch("Simulation.extractors.leg_spot_npv", return_value=150_000.0), \
             patch("Simulation.extractors.leg_swap_length_years", return_value=5.0):

            extractor = SwaptionExtractor()
            state = extractor.extract(mock_context, leg)

            assert state.forward == pytest.approx(0.04)
            assert state.vol_normal == pytest.approx(0.0060)
            assert state.tte == pytest.approx(1.0)
            assert state.annuity_duration is not None
            assert state.annuity_duration == pytest.approx(2.5)  # 5.0 / 2
            assert state.swap_tenor_years == pytest.approx(5.0)

    def test_extract_annuity_duration_scales_with_tenor(self):
        """Longer swap → larger annuity_duration."""
        from unittest.mock import patch, MagicMock
        from Simulation.extractors import SwaptionExtractor

        leg = SimpleNamespace(option_type="payer", strike=0.04)
        mock_context = MagicMock()
        mock_context.as_of_date = datetime.date(2026, 3, 16)

        for tenor, expected_dur in [(2.0, 1.0), (5.0, 2.5), (10.0, 5.0), (30.0, 15.0)]:
            with patch("Simulation.extractors.leg_forward_rate", return_value=0.04), \
                 patch("Simulation.extractors.leg_model_vol", return_value=0.006), \
                 patch("Simulation.extractors.leg_tte_years", return_value=1.0), \
                 patch("Simulation.extractors.leg_spot_npv", return_value=100_000.0), \
                 patch("Simulation.extractors.leg_swap_length_years", return_value=tenor):

                state = SwaptionExtractor().extract(mock_context, leg)
                assert state.annuity_duration == pytest.approx(expected_dur), \
                    f"tenor={tenor}: expected duration={expected_dur}, got {state.annuity_duration}"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_simulation_extractors.py::TestSwaptionExtractorAnnuityMetadata -v`
Expected: FAIL — `state.annuity_duration is None` (not yet populated)

**Step 3: Write minimal implementation**

Modify `SwaptionExtractor.extract()` in `Simulation/extractors.py`.

First, add the import at the top of the file (alongside the existing imports from `Query.IRSwaptions.pricer`):

```python
from Query.IRSwaptions.pricer import (
    leg_forward_rate, leg_model_vol, leg_spot_npv, leg_swap_length_years, leg_tte_years,
)
```

Note: `leg_swap_length_years` is a new import. It already exists in `Query/IRSwaptions/pricer.py:91-95`.

Then modify `SwaptionExtractor.extract()`:

```python
def extract(self, pricer: Any, leg: Any) -> MarketState:
    forward = float(leg_forward_rate(pricer, leg))
    vol_normal = float(leg_model_vol(pricer, leg))
    tte = float(leg_tte_years(pricer, leg))
    base_npv = float(leg_spot_npv(pricer, leg))
    swap_tenor = float(leg_swap_length_years(pricer, leg))

    unit_price = float(
        bachelier_price(
            right=self._leg_right(leg),
            strike=float(leg.strike),
            forward=forward,
            vol_normal=vol_normal,
            tte=tte,
            discount=1.0,
        )
    )
    scale = base_npv / unit_price if abs(unit_price) > 1e-14 else 0.0

    return MarketState(
        forward=forward,
        vol_normal=vol_normal,
        discount=float(scale),
        tte=tte,
        eval_date=pricer.as_of_date,
        annuity_duration=swap_tenor / 2.0,
        swap_tenor_years=swap_tenor,
    )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_extractors.py -v`
Expected: ALL PASS (new tests + existing TestSwaptionExpiryPayoff still passes)

**Step 5: Commit**

```bash
git add Simulation/extractors.py tests/test_simulation_extractors.py
git commit -m "feat(simulation): populate annuity_duration in SwaptionExtractor.extract"
```

---

### Task 4: Verify BachelierExtractor Is Unaffected

**Files:**
- Test: `tests/test_simulation_extractors.py`
- Test: `tests/test_simulation_engine.py`

This task verifies that the new fields don't regress the listed-option path.

**Step 1: Run existing tests**

Run: `python -m pytest tests/test_simulation_extractors.py tests/test_simulation_engine.py tests/test_simulation_scenarios.py tests/test_simulation_grid.py -v`
Expected: ALL PASS

**Step 2: Add explicit guard test**

Add to `tests/test_simulation_extractors.py`:

```python
class TestBachelierExtractorUnaffected:
    def test_bachelier_extract_has_no_annuity_metadata(self):
        """BachelierExtractor should NOT set annuity_duration."""
        pricer = _make_pricer()
        leg = _make_leg(pricer)
        state = BachelierExtractor().extract(pricer, leg)
        assert state.annuity_duration is None
        assert state.swap_tenor_years is None

    def test_underlying_shift_leaves_discount_unchanged_for_listed(self):
        """For listed options, discount must not be adjusted."""
        from Simulation.scenarios import UnderlyingShift
        pricer = _make_pricer()
        leg = _make_leg(pricer)
        state = BachelierExtractor().extract(pricer, leg)
        original_discount = state.discount
        shifted = UnderlyingShift(shift=1.0).mutate(state)
        assert shifted.discount == pytest.approx(original_discount)
```

**Step 3: Run to verify they pass**

Run: `python -m pytest tests/test_simulation_extractors.py::TestBachelierExtractorUnaffected -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/test_simulation_extractors.py
git commit -m "test(simulation): verify BachelierExtractor unaffected by annuity fields"
```

---

### Task 5: Analytical Validation — Duration Correction vs Closed-Form Annuity

**Files:**
- Test: `tests/test_simulation_extractors.py`

This is the key validation. We compute the "true" annuity change using a closed-form flat-curve annuity formula, and verify the duration approximation tracks it.

Flat-curve annuity for quarterly payments:

```
A(r) = (1/r) × [1 − (1 + r/4)^{−4T}]    (approximate, using quarterly compounding)
```

**Step 1: Write the analytical validation test**

Add to `tests/test_simulation_extractors.py`:

```python
class TestAnnuityDurationAccuracy:
    """Validate first-order duration correction against closed-form annuity."""

    @staticmethod
    def _flat_curve_annuity(rate: float, swap_years: float, freq: int = 4) -> float:
        """Closed-form annuity for flat curve with fixed payment frequency."""
        if abs(rate) < 1e-12:
            return swap_years
        period_rate = rate / freq
        n_periods = int(swap_years * freq)
        return (1.0 / rate) * (1.0 - (1.0 + period_rate) ** (-n_periods))

    def test_5y_swap_100bp_shift(self):
        """For a 5Y swap, +100bp shift: duration approx error < 1% of annuity."""
        r0 = 0.04
        T = 5.0
        dr = 0.01  # +100bp

        A_base = self._flat_curve_annuity(r0, T)
        A_true = self._flat_curve_annuity(r0 + dr, T)

        # Duration approximation: D ≈ T/2
        D = T / 2.0
        A_approx = A_base * (1.0 - D * dr)

        # The approximation should be within 1% of annuity
        error_pct = abs(A_approx - A_true) / A_base * 100
        assert error_pct < 1.0, f"Duration approx error {error_pct:.2f}% exceeds 1% for 5Y +100bp"

    def test_10y_swap_200bp_shift(self):
        """For a 10Y swap, +200bp: still within 5% error."""
        r0 = 0.04
        T = 10.0
        dr = 0.02  # +200bp

        A_base = self._flat_curve_annuity(r0, T)
        A_true = self._flat_curve_annuity(r0 + dr, T)

        D = T / 2.0
        A_approx = A_base * (1.0 - D * dr)

        error_pct = abs(A_approx - A_true) / A_base * 100
        assert error_pct < 5.0, f"Duration approx error {error_pct:.2f}% exceeds 5% for 10Y +200bp"

    def test_always_better_than_constant(self):
        """Duration-corrected annuity is always closer to true than constant."""
        for T in [2, 5, 10, 30]:
            for dr in [-0.02, -0.01, -0.005, 0.005, 0.01, 0.02]:
                r0 = 0.04
                A_base = self._flat_curve_annuity(r0, T)
                A_true = self._flat_curve_annuity(r0 + dr, T)

                D = T / 2.0
                A_corrected = A_base * (1.0 - D * dr)

                err_constant = abs(A_base - A_true)
                err_corrected = abs(A_corrected - A_true)

                assert err_corrected <= err_constant, (
                    f"T={T}, dr={dr}: corrected error {err_corrected:.6f} > "
                    f"constant error {err_constant:.6f}"
                )
```

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_simulation_extractors.py::TestAnnuityDurationAccuracy -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/test_simulation_extractors.py
git commit -m "test(simulation): analytical validation of annuity duration correction"
```

---

### Task 6: End-to-End Swaption Repricing Correction Test

**Files:**
- Test: `tests/test_simulation_extractors.py`

Verify that when `SwaptionExtractor.reprice()` is called on a shifted `MarketState` (with duration-corrected discount), the result is closer to the true value than the old constant approach.

**Step 1: Write the end-to-end swaption repricing test**

```python
class TestSwaptionRepricingCorrection:
    """
    Construct a swaption MarketState with annuity metadata,
    shift it, reprice, and verify the correction improves accuracy.
    """

    @staticmethod
    def _flat_curve_annuity(rate: float, swap_years: float, freq: int = 4) -> float:
        if abs(rate) < 1e-12:
            return swap_years
        period_rate = rate / freq
        n_periods = int(swap_years * freq)
        return (1.0 / rate) * (1.0 - (1.0 + period_rate) ** (-n_periods))

    def test_payer_swaption_repricing_improvement(self):
        """
        A 1Yx5Y payer swaption at 4% strike.
        Shift forward by +100bp. Compare:
        - constant annuity repricing (old)
        - duration-corrected repricing (new)
        - true annuity repricing (benchmark)
        """
        from Simulation.extractors import SwaptionExtractor
        from Simulation.scenarios import MarketState, UnderlyingShift

        r0 = 0.04
        T_swap = 5.0
        tte = 1.0
        vol = 0.0060  # 60bps normal vol
        notional = 10_000_000.0

        A_base = self._flat_curve_annuity(r0, T_swap) * notional
        strike = r0

        # Build base state (as SwaptionExtractor would produce)
        base_state = MarketState(
            forward=r0,
            vol_normal=vol,
            discount=A_base,
            tte=tte,
            annuity_duration=T_swap / 2.0,
            swap_tenor_years=T_swap,
        )

        extractor = SwaptionExtractor()
        leg = SimpleNamespace(option_type="payer", strike=strike)

        # Base price sanity check
        base_price = extractor.reprice(base_state, leg)
        assert base_price > 0

        dr = 0.01  # +100bp shift

        # Old approach: constant annuity (no duration field)
        old_state = MarketState(
            forward=r0, vol_normal=vol, discount=A_base, tte=tte,
            annuity_duration=None,  # <-- no correction
        )
        old_shifted = UnderlyingShift(shift=dr).mutate(old_state)
        old_price = extractor.reprice(old_shifted, leg)

        # New approach: duration-corrected
        new_shifted = UnderlyingShift(shift=dr).mutate(base_state)
        new_price = extractor.reprice(new_shifted, leg)

        # True benchmark: use true annuity at shifted rate
        A_true = self._flat_curve_annuity(r0 + dr, T_swap) * notional
        true_state = MarketState(
            forward=r0 + dr, vol_normal=vol, discount=A_true, tte=tte,
        )
        true_price = extractor.reprice(true_state, leg)

        # New price should be closer to true price than old price
        err_old = abs(old_price - true_price)
        err_new = abs(new_price - true_price)
        assert err_new < err_old, (
            f"New error ({err_new:.2f}) should be < old error ({err_old:.2f})"
        )
        # And the improvement should be substantial
        improvement = 1.0 - err_new / err_old if err_old > 0 else 1.0
        assert improvement > 0.5, f"Expected >50% error reduction, got {improvement:.1%}"
```

**Step 2: Run to verify it passes**

Run: `python -m pytest tests/test_simulation_extractors.py::TestSwaptionRepricingCorrection -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add tests/test_simulation_extractors.py
git commit -m "test(simulation): end-to-end swaption repricing shows correction improvement"
```

---

### Task 7: Run Full Test Suite and Final Commit

**Step 1: Run all simulation tests**

Run: `python -m pytest tests/test_simulation_scenarios.py tests/test_simulation_grid.py tests/test_simulation_extractors.py tests/test_simulation_engine.py tests/test_simulation_integration.py -v`
Expected: ALL PASS

**Step 2: Verify no regressions in existing tests**

Run: `python -m pytest tests/ -x --timeout=60 -q`
Expected: No failures

**Step 3: Commit**

```bash
git add -A Simulation/ tests/test_simulation_*.py docs/plans/2026-03-16-swaption-annuity-correction.md
git commit -m "feat(simulation): first-order annuity duration correction for swaption scenarios

Extends MarketState with annuity_duration and swap_tenor_years fields.
SwaptionExtractor populates these from swap term (duration ≈ T/2).
UnderlyingShift applies first-order Taylor correction: A' ≈ A₀(1 - D×ΔF).
Listed-option paths are unaffected (fields remain None).

Analytical validation confirms <1% error for 5Y/100bp, <5% for 10Y/200bp,
and the correction is always closer to true annuity than constant."
```

---

## Summary of All Changes

| File | Change | Lines |
|------|--------|-------|
| `Simulation/scenarios.py` | Add `annuity_duration`, `swap_tenor_years` to `MarketState` | ~2 lines |
| `Simulation/scenarios.py` | Adjust `UnderlyingShift.mutate()` for duration correction | ~5 lines |
| `Simulation/extractors.py` | Import `leg_swap_length_years`; populate annuity fields in `SwaptionExtractor.extract()` | ~5 lines |
| `tests/test_simulation_scenarios.py` | New test classes: `TestMarketStateAnnuityFields`, `TestUnderlyingShiftAnnuityCorrection` | ~50 lines |
| `tests/test_simulation_extractors.py` | New test classes: `TestSwaptionExtractorAnnuityMetadata`, `TestBachelierExtractorUnaffected`, `TestAnnuityDurationAccuracy`, `TestSwaptionRepricingCorrection` | ~120 lines |

## Future Refinements (Not in Scope)

1. **Second-order (convexity) correction:** `A(ΔF) ≈ A₀(1 - D×ΔF + ½C×ΔF²)` with `C ≈ T²/3`. Useful for ±300bp+ scenarios.
2. **FD-computed annuity_duration:** Use `ql.ZeroSpreadedTermStructure` to bump the curve by 1bp, rebuild the swaption, compute `dA/dF` via FD. More accurate than `T/2` but requires curve access at extraction.
3. **Time-decay annuity adjustment:** Account for annuity carrying cost as time passes pre-expiry. The effect is small (< 0.5% per month for typical rates).
4. **Phase 3 curve-level repricing:** Full `SimulationMDP` wrapper that rebuilds the curve under each scenario (as noted in the design doc Section 8). This makes the duration approximation unnecessary but is much more expensive.
