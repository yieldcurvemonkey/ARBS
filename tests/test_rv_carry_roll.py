"""Tests for RVUtils.carry_roll — written FIRST (TDD, RED phase).

Run with:
    conda run -n stir python -m pytest tests/test_rv_carry_roll.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENORS = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0]
A = 1.0   # intercept (%)
B = 0.20  # slope per year (%)


def _linear_curve(a=A, b=B, tenors=TENORS) -> pd.Series:
    """y(t) = a + b*t — a perfectly linear yield curve in percent."""
    return pd.Series({t: a + b * t for t in tenors})


def _linear_curve_ts(n_dates=5, a=A, b=B, tenors=TENORS) -> pd.DataFrame:
    """Wide DataFrame with DatetimeIndex and float-tenor columns."""
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")
    row = {t: a + b * t for t in tenors}
    return pd.DataFrame([row] * n_dates, index=dates, columns=tenors)


# ---------------------------------------------------------------------------
# Imports (will fail until carry_roll.py exists — that's the RED phase)
# ---------------------------------------------------------------------------

from RVUtils.carry_roll import (
    roll_down,
    forward_rate,
    carry,
    curve_carry_roll,
    fly_carry_roll,
    breakeven,
    carry_to_vol,
    make_carry_roll_builder,
)


# ===========================================================================
# roll_down
# ===========================================================================

class TestRollDown:
    """roll_down(curve_row, tenor, horizon) = y(tenor) - y(tenor - horizon)."""

    def test_linear_curve_roll_1y_linear_interp(self):
        """On a linear curve roll_down = b * horizon exactly for linear interp."""
        curve = _linear_curve()
        result = roll_down(curve, tenor=10.0, horizon=1.0, interp="linear")
        assert result == pytest.approx(B * 1.0, abs=1e-10)

    def test_linear_curve_roll_quarter_linear_interp(self):
        curve = _linear_curve()
        result = roll_down(curve, tenor=10.0, horizon=0.25, interp="linear")
        assert result == pytest.approx(B * 0.25, abs=1e-10)

    def test_linear_curve_roll_1y_cubic_interp(self):
        """CubicSpline on a linear curve should also give b * horizon within 1e-6."""
        curve = _linear_curve()
        result = roll_down(curve, tenor=10.0, horizon=1.0, interp="cubic")
        assert result == pytest.approx(B * 1.0, abs=1e-6)

    def test_linear_curve_roll_quarter_cubic_interp(self):
        curve = _linear_curve()
        result = roll_down(curve, tenor=10.0, horizon=0.25, interp="cubic")
        assert result == pytest.approx(B * 0.25, abs=1e-6)

    def test_roll_zero_horizon(self):
        """Zero horizon => no roll."""
        curve = _linear_curve()
        assert roll_down(curve, tenor=5.0, horizon=0.0, interp="linear") == pytest.approx(0.0)

    def test_roll_short_end(self):
        """Roll on the short end of a linear curve."""
        curve = _linear_curve()
        result = roll_down(curve, tenor=2.0, horizon=1.0, interp="linear")
        assert result == pytest.approx(B * 1.0, abs=1e-10)

    def test_roll_inverted_curve_negative(self):
        """On an inverted (negative slope) curve, roll-down is negative."""
        curve = _linear_curve(a=5.0, b=-0.1)
        result = roll_down(curve, tenor=10.0, horizon=1.0, interp="linear")
        assert result == pytest.approx(-0.1 * 1.0, abs=1e-10)

    def test_cubic_falls_back_on_sparse_curve(self):
        """With <4 points, cubic falls back to numpy.interp (piecewise linear)."""
        sparse = pd.Series({1.0: 2.0, 5.0: 3.0, 10.0: 4.0})  # 3 points
        result = roll_down(sparse, tenor=5.0, horizon=1.0, interp="cubic")
        # numpy.interp is piecewise linear by segment:
        #   segment 1→5: slope = (3-2)/(5-1) = 0.25/yr
        #   segment 5→10: slope = (4-3)/(10-5) = 0.20/yr
        # y(5) = 3.0 (knot);  y(4) is in segment 1→5: 2.0 + 0.25*(4-1) = 2.75
        y5 = float(np.interp(5.0, [1.0, 5.0, 10.0], [2.0, 3.0, 4.0]))
        y4 = float(np.interp(4.0, [1.0, 5.0, 10.0], [2.0, 3.0, 4.0]))
        expected = y5 - y4
        assert result == pytest.approx(expected, abs=1e-8)


# ===========================================================================
# forward_rate
# ===========================================================================

class TestForwardRate:
    """forward_rate(curve_row, start, tenor, compounding, pct) via compounding identity."""

    def test_basic_forward_rate_pct(self):
        """Forward rate from a known flat curve: f == spot rate on flat curve."""
        # Flat curve at 4% — forward must also be 4%
        tenors = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]
        flat = pd.Series({t: 4.0 for t in tenors})
        result = forward_rate(flat, start=2.0, tenor=3.0, pct=True)
        assert result == pytest.approx(4.0, abs=1e-6)

    def test_forward_rate_steepening_curve(self):
        """On a linear upward curve, f(start,tenor) > spot(start+tenor) is not guaranteed
        but can be tested mathematically: f*(start,tenor) = (1+s_{start+tenor})^{start+tenor}
        / (1+s_start)^{start} raised to 1/tenor - 1.  Check consistency numerically."""
        curve = _linear_curve()
        # Spot 2y, 3y; forward 1y starting in 2y
        s2 = curve[2.0] / 100.0
        s3 = curve[3.0] / 100.0
        expected_decimal = ((1 + s3) ** 3.0 / (1 + s2) ** 2.0) ** (1.0 / 1.0) - 1
        expected_pct = expected_decimal * 100.0
        result = forward_rate(curve, start=2.0, tenor=1.0, pct=True)
        assert result == pytest.approx(expected_pct, abs=1e-8)

    def test_forward_rate_pct_false(self):
        """pct=False: inputs and output both in decimal."""
        tenors = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]
        flat_decimal = pd.Series({t: 0.04 for t in tenors})
        result = forward_rate(flat_decimal, start=2.0, tenor=3.0, pct=False)
        assert result == pytest.approx(0.04, abs=1e-6)


# ===========================================================================
# carry
# ===========================================================================

class TestCarry:
    """carry = forward_rate(start=horizon, tenor=t-horizon) - spot(t)."""

    def test_flat_curve_carry_is_zero(self):
        """On a flat curve, forward rate = spot rate, so carry = 0."""
        tenors = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0]
        flat = pd.Series({t: 3.0 for t in tenors})
        result = carry(flat, tenor=10.0, horizon=0.25, pct=True)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_carry_linear_curve(self):
        """On a linear curve, carry should equal the forward premium formula."""
        curve = _linear_curve()
        h = 0.25
        t = 10.0
        # Manually compute: forward_rate(start=h, tenor=t-h) - spot(t)
        s_th = (A + B * t) / 100.0
        s_h = (A + B * h) / 100.0
        s_t = A + B * t  # percent
        fwd_decimal = ((1 + s_th) ** t / (1 + s_h) ** h) ** (1 / (t - h)) - 1
        expected = fwd_decimal * 100.0 - s_t
        result = carry(curve, tenor=t, horizon=h, pct=True)
        assert result == pytest.approx(expected, abs=1e-8)


# ===========================================================================
# curve_carry_roll
# ===========================================================================

class TestCurveCarryRoll:
    """curve_carry_roll(curve_row, t_short, t_long, horizon) -> {carry, roll, total}."""

    def test_roll_zero_on_linear_curve(self):
        """roll(long) - roll(short) = b*h - b*h = 0 on a linear curve."""
        curve = _linear_curve()
        result = curve_carry_roll(curve, t_short=2.0, t_long=10.0, horizon=0.25)
        assert result["roll"] == pytest.approx(0.0, abs=1e-6)

    def test_total_is_carry_plus_roll(self):
        """total = carry + roll always."""
        curve = _linear_curve()
        result = curve_carry_roll(curve, t_short=2.0, t_long=10.0, horizon=0.25)
        assert result["total"] == pytest.approx(result["carry"] + result["roll"], abs=1e-12)

    def test_output_keys(self):
        """Result dict must have keys carry, roll, total."""
        curve = _linear_curve()
        result = curve_carry_roll(curve, t_short=2.0, t_long=10.0, horizon=0.25)
        assert set(result.keys()) == {"carry", "roll", "total"}


# ===========================================================================
# fly_carry_roll
# ===========================================================================

class TestFlyCarryRoll:
    """fly_carry_roll(curve_row, legs, weights, horizon) -> {carry, roll, total}."""

    def test_standard_fly_weights(self):
        """[-1, 2, -1] butterfly weights sum to 0."""
        weights = [-1.0, 2.0, -1.0]
        assert sum(weights) == pytest.approx(0.0)

    def test_roll_zero_on_linear_curve_butterfly(self):
        """On a linear curve, butterfly roll = -b*h + 2*b*h - b*h = 0."""
        curve = _linear_curve()
        result = fly_carry_roll(
            curve, legs=[2.0, 5.0, 10.0], weights=[-1.0, 2.0, -1.0], horizon=0.25
        )
        assert result["roll"] == pytest.approx(0.0, abs=1e-6)

    def test_total_is_carry_plus_roll_fly(self):
        curve = _linear_curve()
        result = fly_carry_roll(
            curve, legs=[2.0, 5.0, 10.0], weights=[-1.0, 2.0, -1.0], horizon=0.25
        )
        assert result["total"] == pytest.approx(result["carry"] + result["roll"], abs=1e-12)

    def test_output_keys_fly(self):
        curve = _linear_curve()
        result = fly_carry_roll(
            curve, legs=[2.0, 5.0, 10.0], weights=[-1.0, 2.0, -1.0], horizon=0.25
        )
        assert set(result.keys()) == {"carry", "roll", "total"}

    def test_single_leg_fly_matches_roll_down(self):
        """fly with one leg, weight=1 must equal roll_down for that leg."""
        curve = _linear_curve()
        rd = roll_down(curve, tenor=10.0, horizon=0.25)
        result = fly_carry_roll(curve, legs=[10.0], weights=[1.0], horizon=0.25)
        assert result["roll"] == pytest.approx(rd, abs=1e-10)


# ===========================================================================
# breakeven / carry_to_vol
# ===========================================================================

class TestScalarHelpers:
    def test_breakeven(self):
        assert breakeven(9.0, 0.9) == pytest.approx(10.0)

    def test_breakeven_zero_dv01_raises(self):
        with pytest.raises((ZeroDivisionError, ValueError)):
            breakeven(5.0, 0.0)

    def test_carry_to_vol(self):
        assert carry_to_vol(10.0, 5.0) == pytest.approx(2.0)

    def test_carry_to_vol_zero_vol_raises(self):
        with pytest.raises((ZeroDivisionError, ValueError)):
            carry_to_vol(5.0, 0.0)


# ===========================================================================
# make_carry_roll_builder
# ===========================================================================

class TestMakeCarryRollBuilder:
    """Builder returns a tuple of closures; roll_ts etc. produce Series indexed by date."""

    def _build(self, n_dates=8):
        curve_ts = _linear_curve_ts(n_dates=n_dates)
        return make_carry_roll_builder(curve_ts, horizon=0.25, interp="linear", pct=True), curve_ts

    def test_builder_returns_tuple_of_six(self):
        (tup, _) = self._build()
        assert len(tup) == 6

    def test_roll_ts_outright_length(self):
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=8)
        series = roll_ts(("outright", 10.0))
        assert isinstance(series, pd.Series)
        assert len(series) == 8

    def test_carry_ts_outright_length(self):
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=8)
        series = carry_ts(("outright", 10.0))
        assert isinstance(series, pd.Series)
        assert len(series) == 8

    def test_total_ts_curve_structure_length(self):
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=8)
        series = total_ts(("curve", 2.0, 10.0))
        assert isinstance(series, pd.Series)
        assert len(series) == 8

    def test_roll_ts_fly_structure_length(self):
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=8)
        series = roll_ts(("fly", [2.0, 5.0, 10.0], [-1.0, 2.0, -1.0]))
        assert isinstance(series, pd.Series)
        assert len(series) == 8

    def test_total_ts_linear_curve_roll_zero(self):
        """On a constant linear curve_ts, curve roll component should be ~0 every date."""
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=5)
        # Access roll via roll_ts for curve structure
        r_series = roll_ts(("curve", 2.0, 10.0))
        assert (r_series.abs() < 1e-6).all()

    def test_breakeven_ts_scalar_dv01(self):
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=5)
        series = breakeven_ts(("outright", 10.0), dv01=0.09)
        assert isinstance(series, pd.Series)
        assert len(series) == 5

    def test_carry_to_vol_ts(self):
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=10)
        series = carry_to_vol_ts(("outright", 10.0), vol_window=5)
        assert isinstance(series, pd.Series)
        # some NaNs from rolling vol warm-up are expected
        assert len(series) == 10

    def test_get_data_returns_original(self):
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), curve_ts = self._build(n_dates=5)
        pd.testing.assert_frame_equal(get_data(), curve_ts)

    def test_first_closure_has_state(self):
        """roll_ts (first closure) should expose .state like pca_rv's fit does."""
        (roll_ts, carry_ts, total_ts, breakeven_ts, carry_to_vol_ts, get_data), _ = self._build()
        assert hasattr(roll_ts, "state")
        assert "curve_ts" in roll_ts.state
