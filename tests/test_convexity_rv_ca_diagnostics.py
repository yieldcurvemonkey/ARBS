"""Known-answer tests for the convexity-adjustment correctness diagnostics.

The module under test exists to catch mistakes in a number that is a *small
difference of two large numbers*, so a checking tool that is itself wrong is
the dominant failure mode -- it reports success and hides exactly what it was
built to find. Every test here therefore carries a **negative control**: an
input on which the check must FAIL. A test that only asserts the happy path
would still pass against a function that returned a constant.

The planted answers:

* Ho-Lee shape. Synthesise ``CA = 1/2 sigma^2 T1^2`` exactly, so the log-log
  slope MUST be 2.000000 and ``corr(CA, T1^2)`` MUST be 1. Then feed a linear
  and a cubic profile and require the slope to move to 1 and 3.
* The compounding gap. ``0.375 * r^2`` is a truncated expansion of the exact
  identity ``(1 + q/4)^4 = 1 + a``, so the predictor is checked against the
  exact number rather than against itself.
* Curve resolution. A grid whose second node is two years out must report zero
  nodes inside a 1y window and ``spans_window == 1``; a monthly grid must not.
  This is the check that the full-sample scan showed the zero-convexity control
  cannot make for itself.
* Annuity weighting. On a FLAT strip the term is identically zero; on a rising
  strip it is positive; on an inverted strip it is negative. Sign is the test,
  because sign is what makes the measured residual interpretable.

Pure functions only -- no market data, no network, so this runs in the fast
gate.
"""

import datetime

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.ca_diagnostics import (
    COMPOUNDING_GAP_SLOPE,
    MIN_T1_FOR_VOL_YEARS,
    PLAUSIBLE_VOL_BP,
    annuity_weight_residual_bp,
    compounding_gap_bp,
    control_power_bp,
    flag_quality,
    next_quarterly,
    regress_gap_on_rate_squared,
    shape_diagnostics,
    vol_sensitivity_bp_per_bp,
    window_resolution,
)
from RVUtils.ConvexityRV.holee import implied_vol_from_ca_bp, pack_time_weight


# ===========================================================================
# next_quarterly
# ===========================================================================
def test_next_quarterly_walks_the_imm_cycle_and_wraps_the_year():
    assert next_quarterly(2024, 3) == (2024, 6)
    assert next_quarterly(2024, 6) == (2024, 9)
    assert next_quarterly(2024, 9) == (2024, 12)
    assert next_quarterly(2024, 12) == (2025, 3)          # the wrap


# ===========================================================================
# 1. Ho-Lee shape -- planted answer with two negative controls
# ===========================================================================
def _profile(power: float, t1=np.arange(1.0, 5.01, 0.25)) -> pd.DataFrame:
    return pd.DataFrame({"t1_first": t1, "ca_bp": 3.0 * t1 ** power})


def test_shape_recovers_the_planted_exponent_exactly():
    sigma = 0.015
    t1 = np.arange(1.0, 5.01, 0.25)
    df = pd.DataFrame({"t1_first": t1, "ca_bp": 0.5 * sigma ** 2 * t1 ** 2 * 1e4})
    out = shape_diagnostics(df)
    assert out["loglog_slope"] == pytest.approx(2.0, abs=1e-9)
    assert out["corr_t1_squared"] == pytest.approx(1.0, abs=1e-12)
    assert out["n"] == len(t1)


@pytest.mark.parametrize("power", [1.0, 1.5, 3.0])
def test_shape_is_not_hardwired_to_two(power):
    """Negative control: a non-quadratic profile must NOT return slope 2."""
    out = shape_diagnostics(_profile(power))
    assert out["loglog_slope"] == pytest.approx(power, abs=1e-9)
    assert abs(out["loglog_slope"] - 2.0) > 0.4


def test_shape_drops_non_positive_and_degrades_to_nan_rather_than_raising():
    df = pd.DataFrame({"t1_first": [0.5, 1.0, 1.5, 2.0, 2.5],
                       "ca_bp": [-1.0, -2.0, -0.5, 3.0, 4.0]})
    out = shape_diagnostics(df)
    assert np.isnan(out["loglog_slope"])          # only 2 usable points
    assert out["n"] == 2
    # a day with no usable rows at all must still return, not raise
    empty = shape_diagnostics(pd.DataFrame({"t1_first": [], "ca_bp": []}))
    assert np.isnan(empty["loglog_slope"]) and empty["n"] == 0


# ===========================================================================
# 2. The annual/quarterly compounding gap
# ===========================================================================
@pytest.mark.parametrize("q", [0.005, 0.01, 0.02, 0.034, 0.05])
def test_compounding_gap_matches_the_exact_identity(q):
    """``(1 + q/4)^4 = 1 + a``; the predictor is the truncated expansion of it."""
    exact_bp = ((1.0 + q / 4.0) ** 4 - 1.0 - q) * 1e4
    approx_bp = compounding_gap_bp(q * 100.0)
    assert approx_bp == pytest.approx(exact_bp, rel=0.02, abs=0.01)
    assert approx_bp > 0                                   # annual always exceeds


def test_compounding_gap_hits_the_documented_levels():
    assert compounding_gap_bp(5.0) == pytest.approx(9.375, abs=1e-9)
    assert compounding_gap_bp(3.4) == pytest.approx(4.335, abs=1e-9)
    assert compounding_gap_bp(0.0) == 0.0
    assert COMPOUNDING_GAP_SLOPE == 0.375


def test_compounding_gap_is_vectorised():
    out = compounding_gap_bp(np.array([0.0, 3.4, 5.0]))
    assert isinstance(out, np.ndarray)
    assert out == pytest.approx([0.0, 4.335, 9.375], abs=1e-9)


def test_regression_recovers_the_slope_from_synthetic_gaps():
    rates = np.linspace(0.1, 5.5, 400)
    gaps = COMPOUNDING_GAP_SLOPE * rates ** 2
    out = regress_gap_on_rate_squared(gaps, rates)
    assert out["slope_no_intercept"] == pytest.approx(0.375, abs=1e-9)
    assert out["intercept"] == pytest.approx(0.0, abs=1e-9)
    assert out["r2"] == pytest.approx(1.0, abs=1e-12)
    # negative control: a gap that is LINEAR in the rate must not fit 0.375 well
    lin = regress_gap_on_rate_squared(2.0 * rates, rates)
    assert abs(lin["slope_no_intercept"] - 0.375) > 0.05
    assert lin["r2"] < 0.99
    # too few points -> NaNs, not an exception
    assert np.isnan(regress_gap_on_rate_squared([1.0], [1.0])["slope"])


# ===========================================================================
# 3. Curve resolution -- the blind spot of the zero-convexity control
# ===========================================================================
COARSE = [datetime.date(2019, 3, 15), datetime.date(2021, 3, 19),
          datetime.date(2022, 3, 21), datetime.date(2023, 3, 20)]
FINE = [datetime.date(2019, 3, 15) + datetime.timedelta(days=30 * k) for k in range(48)]
WINDOW = (datetime.date(2019, 6, 19), datetime.date(2020, 6, 17))


def test_coarse_grid_is_flagged_as_spanning_the_window():
    out = window_resolution(COARSE, *WINDOW)
    assert out["n_nodes_inside"] == 0
    assert out["spans_window"] == 1.0
    assert out["segment_days"] > 700
    assert out["n_nodes"] == len(COARSE)


def test_fine_grid_is_not_flagged():
    """Negative control -- without this the resolution test could be vacuous."""
    out = window_resolution(FINE, *WINDOW)
    assert out["n_nodes_inside"] >= 10
    assert out["spans_window"] == 0.0
    assert out["segment_days"] <= 31


def test_control_power_is_zero_on_a_flat_strip_and_positive_otherwise():
    assert control_power_bp([2.2866] * 4) == pytest.approx(0.0, abs=1e-12)
    assert control_power_bp([2.43, 2.405, 2.38, 2.34]) == pytest.approx(9.0, abs=1e-9)
    assert np.isnan(control_power_bp([]))
    assert np.isnan(control_power_bp([1.0, np.nan, 2.0, 3.0]))


# ===========================================================================
# 4. Annuity weighting -- the term the control legitimately returns
# ===========================================================================
def test_annuity_term_is_exactly_zero_on_a_flat_strip():
    """A flat strip has equal-weighted mean == annuity-weighted mean, always."""
    assert annuity_weight_residual_bp([3.0] * 4, 3.0) == pytest.approx(0.0, abs=1e-12)
    assert annuity_weight_residual_bp([3.0] * 4, 0.0) == pytest.approx(0.0, abs=1e-12)


def test_annuity_term_sign_follows_the_slope_of_the_strip():
    """Rising strip -> arithmetic mean above par -> positive. Inverted -> negative.

    This is the property that makes a measured negative residual through the
    inverted 2022-2023 SOFR strip evidence of correctness rather than of error.
    """
    rising = annuity_weight_residual_bp([3.0, 3.2, 3.4, 3.6], 3.3)
    inverted = annuity_weight_residual_bp([3.6, 3.4, 3.2, 3.0], 3.3)
    assert rising > 0
    assert inverted < 0
    assert rising == pytest.approx(-inverted, rel=1e-6)


def test_annuity_term_scales_with_rate_and_with_dispersion():
    small = annuity_weight_residual_bp([3.0, 3.1, 3.2, 3.3], 3.15)
    wide = annuity_weight_residual_bp([3.0, 3.4, 3.8, 4.2], 3.6)
    assert abs(wide) > abs(small)
    # at a zero rate every discount factor is 1, so the term vanishes
    assert annuity_weight_residual_bp([3.0, 3.2, 3.4, 3.6], 0.0) == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(annuity_weight_residual_bp([1.0, np.nan], 3.0))


def test_annuity_term_is_the_right_order_of_magnitude():
    """~0.2bp on a 50bp inverted strip at 4% -- the size measured in 2022-23."""
    got = annuity_weight_residual_bp([4.25, 4.10, 3.95, 3.75], 4.0)
    assert -0.6 < got < -0.05


# ===========================================================================
# 5. Vol-inversion conditioning
# ===========================================================================
def test_vol_sensitivity_equals_sigma_over_twice_ca():
    t1s = [1.0, 1.25, 1.5, 1.75]
    for ca in (0.5, 2.0, 10.0):
        sigma = implied_vol_from_ca_bp(ca, t1s)
        assert vol_sensitivity_bp_per_bp(ca, t1s) == pytest.approx(sigma / (2 * ca), rel=1e-12)


def test_vol_sensitivity_explodes_for_small_adjustments():
    """The whole reason near packs are unusable, stated as an inequality."""
    t1s_near = [0.12, 0.37, 0.62, 0.87]
    t1s_far = [2.1, 2.4, 2.6, 2.9]
    near = vol_sensitivity_bp_per_bp(0.28, t1s_near)     # measured rank-1 median CA
    far = vol_sensitivity_bp_per_bp(4.10, t1s_far)       # measured rank-10 median CA
    assert near > 8 * far
    assert not np.isfinite(vol_sensitivity_bp_per_bp(-1.0, t1s_far))
    assert not np.isfinite(vol_sensitivity_bp_per_bp(0.0, t1s_far))


def test_pack_time_weight_pseudo_t1_identity():
    """``pack_time_weight([sqrt(M)]) == M`` -- strat2 stores M, not the four T1s."""
    t1s = [1.0, 1.25, 1.5, 1.75]
    m = pack_time_weight(t1s)
    assert pack_time_weight([np.sqrt(m)]) == pytest.approx(m, rel=1e-14)


# ===========================================================================
# 6. flag_quality -- each flag must fire alone, and 'ok' must be their AND
# ===========================================================================
@pytest.fixture()
def flag_frame():
    return pd.DataFrame({
        "ca_bp": [5.0, -2.0, 5.0, 5.0, 5.0],
        "ca_synthetic_bp": [0.0, 0.0, 3.0, 0.0, 0.0],
        "implied_vol_bp": [160.0, np.nan, 160.0, 900.0, 160.0],
        "t1_first": [2.0, 2.0, 2.0, 2.0, 0.12],
    })


def test_each_flag_fires_on_its_own_row(flag_frame):
    out = flag_quality(flag_frame)
    assert list(out["flag_negative_ca"]) == [False, True, False, False, False]
    assert list(out["flag_convention"]) == [False, False, True, False, False]
    assert list(out["flag_implausible_vol"]) == [False, False, False, True, False]
    assert list(out["flag_vol_ill_conditioned"]) == [False, False, False, False, True]


def test_ok_is_the_conjunction_and_excludes_the_conditioning_flag(flag_frame):
    """``flag_vol_ill_conditioned`` is advisory: a short-dated pack with a good
    CA is still a good CA, it just cannot be inverted for a vol."""
    out = flag_quality(flag_frame)
    assert list(out["ok"]) == [True, False, False, False, True]


def test_flag_quality_does_not_mutate_its_input(flag_frame):
    before = flag_frame.copy(deep=True)
    flag_quality(flag_frame)
    pd.testing.assert_frame_equal(flag_frame, before)


def test_convention_threshold_is_honoured(flag_frame):
    """Negative control on the threshold itself: raise it and the flag clears."""
    assert bool(flag_quality(flag_frame, max_convention_bp=1.0)["flag_convention"].iloc[2])
    assert not bool(flag_quality(flag_frame, max_convention_bp=5.0)["flag_convention"].iloc[2])


def test_missing_optional_columns_default_to_not_flagged():
    out = flag_quality(pd.DataFrame({"ca_bp": [1.0, -1.0]}))
    assert list(out["flag_negative_ca"]) == [False, True]
    assert not out["flag_convention"].any()
    assert not out["flag_implausible_vol"].any()
    assert list(out["ok"]) == [True, False]


def test_module_constants_are_the_documented_ones():
    assert PLAUSIBLE_VOL_BP == (40.0, 350.0)
    assert MIN_T1_FOR_VOL_YEARS == 0.75
