"""Analytic round-trips for the implied-distribution extractors.

Feed option prices generated from a *known* density and check what comes back. These are
the checks that were missing: the package had no forward tie-out, no mass-conservation
assertion on the binned probabilities, and no test that recovered moments resemble the
moments that went in.
"""

import datetime

import numpy as np
import pytest
from scipy.stats import norm

from RVUtils.ImpliedDistribution._bachelier import bachelier_call_prices_vectorized
from RVUtils.ImpliedDistribution._bkm import extract_bkm_moments
from RVUtils.ImpliedDistribution._breeden_litzenberger import extract_rnd_breeden_litzenberger
from RVUtils.ImpliedDistribution._data_prep import build_ghost_wings
from RVUtils.ImpliedDistribution._gaussian_mixture import (
    _mixture_call_prices,
    extract_gaussian_mixture,
)
from RVUtils.ImpliedDistribution._types import RNDInput, ScenarioDefinition


def _bachelier_input(
    *,
    forward: float = 96.00,
    sigma: float = 0.40,
    tte: float = 0.25,
    df: float = 1.0,
    lo: float = 93.5,
    hi: float = 98.5,
    step: float = 0.125,
) -> RNDInput:
    """Exact Bachelier premiums, i.e. an exactly-normal RND with terminal
    std ``sigma * sqrt(tte)`` in price points."""
    strikes = np.arange(lo, hi + 1e-9, step)
    premiums = bachelier_call_prices_vectorized(
        strikes, forward, np.full_like(strikes, sigma), tte, df
    )
    return RNDInput(
        symbol="TEST",
        as_of=datetime.date(2026, 1, 2),
        forward_price=forward,
        forward_rate=100.0 - forward,
        time_to_expiry=tte,
        expiry_date=datetime.date(2026, 4, 2),
        discount_factor=df,
        strikes_price=strikes,
        call_premiums=premiums,
        strike_source="analytic_bachelier",
    )


# ----------------------------------------------------------------------------------
# binned probabilities must be a probability vector
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("bin_width_bps", [5.0, 12.5, 25.0, 50.0])
@pytest.mark.parametrize("grid_points", [500, 2000])
def test_bin_probabilities_sum_to_one(bin_width_bps, grid_points):
    """Bins were integrated over only the grid nodes strictly inside each bin, dropping
    both partial end intervals, so the vector summed to 1 - dx/bin_width."""
    bl = extract_rnd_breeden_litzenberger(
        _bachelier_input(), bin_width_bps=bin_width_bps, grid_points=grid_points
    )
    assert float(np.sum(bl.bin_probabilities)) == pytest.approx(1.0, abs=1e-9)
    assert np.all(bl.bin_probabilities >= -1e-12)


@pytest.mark.parametrize("forward", [95.87, 96.00, 96.07, 96.13])
def test_bin_edges_cover_the_whole_grid(forward):
    """The descending edge loop stopped at the first edge >= rate_grid[0], so up to a
    full bin width of left-tail mass was never binned at all. That loss was one-sided."""
    bl = extract_rnd_breeden_litzenberger(_bachelier_input(forward=forward))
    assert bl.bin_edges_rate[0] <= bl.strike_grid_rate[0] + 1e-12
    assert bl.bin_edges_rate[-1] >= bl.strike_grid_rate[-1] - 1e-12
    assert float(np.sum(bl.bin_probabilities)) == pytest.approx(1.0, abs=1e-9)


def test_narrow_bins_do_not_report_zero():
    """`trapezoid` of a single-element array is 0.0, so any bin holding one grid node
    reported exactly zero probability."""
    bl = extract_rnd_breeden_litzenberger(
        _bachelier_input(), bin_width_bps=25.0, grid_points=40
    )
    assert float(np.sum(bl.bin_probabilities)) == pytest.approx(1.0, abs=1e-9)
    # the two bins either side of the forward must carry mass
    fwd_rate = bl.input.forward_rate
    near = [
        p
        for p, lo, hi in zip(bl.bin_probabilities, bl.bin_edges_rate[:-1], bl.bin_edges_rate[1:])
        if lo - 0.25 <= fwd_rate <= hi + 0.25
    ]
    assert near and max(near) > 0.0


# ----------------------------------------------------------------------------------
# martingale tie-out and fit diagnostics
# ----------------------------------------------------------------------------------


def test_forward_residual_is_reported():
    """Under Q the SR3 future is a martingale, so E[100 - P_T] must equal 100 - F.
    Nothing used to check it."""
    bl = extract_rnd_breeden_litzenberger(_bachelier_input())
    assert np.isfinite(bl.forward_residual_bp)
    assert bl.forward_residual_bp == pytest.approx(
        (bl.mean_rate - bl.input.forward_rate) * 100.0, abs=1e-9
    )


def test_large_forward_residual_raises_a_warning():
    bl = extract_rnd_breeden_litzenberger(_bachelier_input(), smoothing_param=1e-2)
    if abs(bl.forward_residual_bp) > 2.0:
        assert any("martingale tie-out" in w for w in bl.warnings), bl.warnings


def test_pre_normalization_mass_is_preserved():
    """It was computed and then divided away, which left a downstream guard in
    STIRAsymmetricScreener/_rnd.py measuring a constant 1.0."""
    bl = extract_rnd_breeden_litzenberger(_bachelier_input())
    assert np.isfinite(bl.pre_normalization_mass)
    assert bl.pre_normalization_mass > 0.0
    # the returned density is separately normalised
    assert float(np.trapezoid(bl.rnd_density, bl.strike_grid_rate)) == pytest.approx(1.0, abs=1e-6)


def test_ghost_mass_fraction_is_reported():
    bl = extract_rnd_breeden_litzenberger(_bachelier_input())
    assert 0.0 <= bl.ghost_mass_fraction < 1.0


def test_shape_violations_are_reported():
    """A fitted call curve must be non-increasing in K and no steeper than -DF."""
    bl = extract_rnd_breeden_litzenberger(_bachelier_input(), smoothing_param=1e-2)
    assert any("non-monotone" in w or "delta bound" in w for w in bl.warnings), bl.warnings


# ----------------------------------------------------------------------------------
# the estimator itself is unbiased; `smoothing_param` is the tuning knob
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("sigma,tte", [(0.30, 0.25), (0.60, 0.50), (0.90, 1.00)])
def test_bl_recovers_a_known_normal_density_when_smoothing_is_tight(sigma, tte):
    """With noiseless input the correct residual budget is ~0 and the extractor is then
    essentially exact. Real settlement data is quantised on a 0.0025 tick (CME Rulebook
    460A01.C), which is why the shipped default is a half-tick budget rather than 0 -
    but the machinery must be unbiased before smoothing is applied."""
    # Span +/-5 terminal sd so the assertion measures estimator bias rather than support
    # truncation: a ladder that stops at +/-2.8 sd genuinely omits mass, and the recovered
    # mean legitimately misses the forward by ~1bp as a result. Coverage adequacy is
    # reported separately via ghost_mass_fraction.
    true_sd = sigma * np.sqrt(tte)
    half_span = np.ceil(5.0 * true_sd / 0.125) * 0.125
    inp = _bachelier_input(
        sigma=sigma, tte=tte, lo=96.0 - half_span, hi=96.0 + half_span
    )
    bl = extract_rnd_breeden_litzenberger(inp, smoothing_param=1e-10)

    assert bl.mean_rate == pytest.approx(inp.forward_rate, abs=0.002)
    assert bl.std_rate == pytest.approx(true_sd, rel=0.02)
    assert abs(bl.skewness) < 0.15
    assert bl.kurtosis == pytest.approx(3.0, abs=0.5)

    lo = 100.0 - inp.strikes_price[-1]
    hi = 100.0 - inp.strikes_price[0]
    mask = (bl.strike_grid_rate >= lo) & (bl.strike_grid_rate <= hi)
    grid = bl.strike_grid_rate[mask]
    l1 = float(
        np.trapezoid(np.abs(bl.rnd_density[mask] - norm.pdf(grid, inp.forward_rate, true_sd)), grid)
    )
    assert l1 < 0.05, f"L1 density error {l1:.4f}"


# ----------------------------------------------------------------------------------
# percentiles
# ----------------------------------------------------------------------------------


def test_percentile_is_monotone_and_anchored():
    """The zero-clip leaves flat CDF stretches; interpolating over tied abscissae is
    undefined and used to put percentile(0) well inside the support."""
    bl = extract_rnd_breeden_litzenberger(_bachelier_input())
    assert bl.percentile(0) == pytest.approx(float(bl.strike_grid_rate[0]), abs=1e-9)
    values = [bl.percentile(p) for p in range(0, 101)]
    assert all(b >= a - 1e-12 for a, b in zip(values, values[1:]))


# ----------------------------------------------------------------------------------
# ghost wings
# ----------------------------------------------------------------------------------


def test_cabinet_pinned_wing_keeps_the_linear_ghost_branch():
    """Real SFR wings sit at the 0.0025 settlement tick, giving a terminal slope of ~0
    that never crosses zero. Those inputs must be untouched."""
    strikes = np.array([96.0, 96.5, 97.0])
    premiums = np.array([0.30, 0.0025, 0.0025])
    ext_k, ext_p, warns = build_ghost_wings(strikes, premiums, n_ghost=10, extension_bps=5.0)
    assert warns == []
    assert np.allclose(ext_p[-10:], 0.0025)


def test_crossing_wing_avoids_the_zero_weld():
    """A ramp clamped at zero welds a slope discontinuity into C(K); d2C/dK2 of that
    corner is a near-delta, i.e. fabricated probability parked at the ghost boundary."""
    strikes = np.array([96.0, 96.5, 97.0])
    premiums = np.array([0.30, 0.10, 0.02])
    ext_k, ext_p, warns = build_ghost_wings(strikes, premiums, n_ghost=10, extension_bps=5.0)
    wing = ext_p[-10:]
    assert any("cross zero" in w for w in warns), warns
    assert np.all(wing > 0.0), wing
    assert np.all(np.diff(wing) < 0.0), "wing must decay monotonically"
    # C1 join: first ghost slope matches the observed terminal slope
    observed_slope = (premiums[-1] - premiums[-2]) / (strikes[-1] - strikes[-2])
    first_slope = (wing[0] - premiums[-1]) / (ext_k[len(ext_k) - 10] - strikes[-1])
    assert first_slope == pytest.approx(observed_slope, rel=0.2)


def test_rising_terminal_slope_is_refused():
    strikes = np.array([96.0, 96.5, 97.0])
    premiums = np.array([0.30, 0.02, 0.05])  # crossed / stale quote
    _, ext_p, warns = build_ghost_wings(strikes, premiums, n_ghost=5, extension_bps=5.0)
    assert any("positive" in w for w in warns), warns
    assert np.allclose(ext_p[-5:], 0.05)


# ----------------------------------------------------------------------------------
# BKM discounting
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("df", [1.0, 0.98, 0.90])
def test_bkm_variance_is_invariant_to_the_discount_factor(df):
    """BKM/Carr-Madan spanning needs UNDISCOUNTED option values. CME SR3 options are
    premium-paid-up-front, so quoted premiums carry a df that must be divided out;
    otherwise variance scaled with df and kurtosis with 1/df."""
    sigma, tte = 0.60, 0.50
    bkm = extract_bkm_moments(_bachelier_input(sigma=sigma, tte=tte, df=df))
    true_var = (sigma * np.sqrt(tte)) ** 2
    assert bkm.variance_rate == pytest.approx(true_var, rel=0.05)


def test_bkm_gaussian_input_has_no_excess_kurtosis():
    bkm = extract_bkm_moments(_bachelier_input(sigma=0.60, tte=0.50, df=0.98))
    assert bkm.excess_kurtosis_rate == pytest.approx(0.0, abs=0.30)
    assert bkm.skewness_rate == pytest.approx(0.0, abs=0.15)


def test_bkm_tail_fraction_aliases_agree_with_rate_space_skew():
    """left_/right_ are PRICE-space wings; the hawkish_/dovish_ aliases name them in
    rate space so they cannot be read against skewness_rate by mistake."""
    bkm = extract_bkm_moments(_bachelier_input())
    assert bkm.hawkish_tail_variance_frac == bkm.left_tail_variance_frac
    assert bkm.dovish_tail_variance_frac == bkm.right_tail_variance_frac
    assert bkm.hawkish_tail_variance_frac + bkm.dovish_tail_variance_frac == pytest.approx(1.0)


# ----------------------------------------------------------------------------------
# Gaussian mixture std convention
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("tte", [0.25, 2.00])
def test_gm_pricing_kernel_treats_std_as_terminal(tte):
    """The kernel multiplied the scenario std by sqrt(T) while the density export did
    not, so the exported mixture was wider than the calibrated one by 1/sqrt(T) -
    exact only at T=1."""
    terminal_std = 0.20
    strikes = np.array([96.0])
    got = _mixture_call_prices(
        strikes, tte, 1.0, np.array([4.0]), np.array([terminal_std]), np.array([1.0])
    )
    expected = bachelier_call_prices_vectorized(
        strikes, 96.0, np.array([terminal_std]), 1.0, 1.0
    )
    assert got == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("tte", [0.25, 2.00])
def test_gm_composite_density_matches_its_own_calibration(tte):
    scenarios = [
        ScenarioDefinition(label="cut", mean_rate=3.50),
        ScenarioDefinition(label="hold", mean_rate=3.75),
        ScenarioDefinition(label="hike", mean_rate=4.00),
    ]
    true_w = np.array([0.30, 0.50, 0.20])
    true_sd = 0.10
    strikes = np.arange(95.0, 97.0001, 0.125)
    means = np.array([s.mean_rate for s in scenarios])
    market = _mixture_call_prices(
        strikes, tte, 1.0, means, np.full(3, true_sd), true_w
    )
    inp = RNDInput(
        symbol="TEST",
        as_of=datetime.date(2026, 1, 2),
        forward_price=100.0 - float(np.dot(true_w, means)),
        forward_rate=float(np.dot(true_w, means)),
        time_to_expiry=tte,
        expiry_date=datetime.date(2026, 4, 2),
        discount_factor=1.0,
        strikes_price=strikes,
        call_premiums=market,
        strike_source="analytic_mixture",
    )
    gm = extract_gaussian_mixture(inp, scenarios, optimize_stds=True)

    mean = float(np.trapezoid(gm.strike_grid_rate * gm.composite_density, gm.strike_grid_rate))
    var = float(
        np.trapezoid(
            (gm.strike_grid_rate - mean) ** 2 * gm.composite_density, gm.strike_grid_rate
        )
    )
    true_mean = float(np.dot(true_w, means))
    true_var = float(np.dot(true_w, true_sd**2 + (means - true_mean) ** 2))
    assert mean == pytest.approx(true_mean, abs=0.01)
    assert np.sqrt(var) == pytest.approx(np.sqrt(true_var), rel=0.05)
