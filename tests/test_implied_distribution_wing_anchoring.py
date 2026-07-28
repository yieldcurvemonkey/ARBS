"""Wing handling: anchored ghost points, and the vol-space fit alternative.

JPM Appendix A says the ghost points exist so that "the fitted RND will approach zero
outside of the strike range spanned by the data, avoiding unphysical behavior in the
wings". Fitting them with the same weight as the quotes does not deliver that - the
smoothing spline drifts off the linear ramp and bends the wings back up, putting real
probability mass in bins where no option was ever observed.
"""

import datetime

import numpy as np
import pytest

from RVUtils.ImpliedDistribution._bachelier import (
    bachelier_call_prices_vectorized,
    bachelier_implied_vol,
    bachelier_vega,
)
from RVUtils.ImpliedDistribution._breeden_litzenberger import (
    extract_rnd_breeden_litzenberger,
)
from RVUtils.ImpliedDistribution._types import RNDInput


def _input(strikes, forward=96.0, sigma=0.40, tte=0.25, df=1.0, premiums=None):
    strikes = np.asarray(strikes, dtype=float)
    if premiums is None:
        premiums = bachelier_call_prices_vectorized(
            strikes, forward, np.full_like(strikes, sigma), tte, df
        )
    return RNDInput(
        symbol="TEST", as_of=datetime.date(2026, 1, 2), forward_price=forward,
        forward_rate=100.0 - forward, time_to_expiry=tte,
        expiry_date=datetime.date(2026, 4, 2), discount_factor=df,
        strikes_price=strikes, call_premiums=np.asarray(premiums, dtype=float),
        strike_source="analytic",
    )


def _outside_mass(result, strikes):
    """Probability sitting in bins wholly outside the observed strike range."""
    rates = np.sort(100.0 - np.asarray(strikes, dtype=float))
    lo, hi = rates.min(), rates.max()
    return sum(
        p for p, a, b in zip(result.bin_probabilities, result.bin_edges_rate[:-1],
                             result.bin_edges_rate[1:])
        if b <= lo or a >= hi
    )


# A deliberately sparse, delta-like ladder: a dense cluster near the money and two
# isolated points per wing, which is what delta-addressed smiles produce.
SPARSE = np.array([93.5, 94.5, 95.5, 95.75, 95.875, 96.0, 96.125, 96.25, 96.5, 97.5, 98.5])


def test_anchoring_removes_mass_from_the_ghost_region():
    inp = _input(SPARSE)
    loose = extract_rnd_breeden_litzenberger(inp)
    anchored = extract_rnd_breeden_litzenberger(inp, anchor_wings=True)
    assert _outside_mass(anchored, SPARSE) < _outside_mass(loose, SPARSE)
    assert _outside_mass(anchored, SPARSE) < 0.01, (
        f"{_outside_mass(anchored, SPARSE):.4f} of mass still outside the observed strikes"
    )


def test_anchoring_is_off_by_default():
    """The shipped default stays the literal Appendix A recipe."""
    inp = _input(SPARSE)
    a = extract_rnd_breeden_litzenberger(inp)
    b = extract_rnd_breeden_litzenberger(inp, anchor_wings=False)
    assert np.array_equal(a.rnd_density, b.rnd_density)
    assert a.mean_rate == b.mean_rate


def test_anchoring_preserves_genuine_structure():
    """Smoothing the wings must not flatten a real bimodal density."""
    strikes = np.arange(94.0, 98.0001, 0.125)
    # two-component mixture: modes 50bp apart, as a two-more-cuts market prices
    p1 = bachelier_call_prices_vectorized(strikes, 96.4, np.full_like(strikes, 0.18), 0.25, 1.0)
    p2 = bachelier_call_prices_vectorized(strikes, 95.9, np.full_like(strikes, 0.18), 0.25, 1.0)
    premiums = 0.45 * p1 + 0.55 * p2
    fwd = 0.45 * 96.4 + 0.55 * 95.9
    inp = _input(strikes, forward=fwd, premiums=premiums)

    def modes(r):
        d = r.rnd_density
        return int(np.sum((d[1:-1] > d[:-2]) & (d[1:-1] > d[2:]) & (d[1:-1] > 0.05 * d.max())))

    assert modes(extract_rnd_breeden_litzenberger(inp, anchor_wings=True)) == 2


def test_anchor_weight_zero_is_a_no_op():
    inp = _input(SPARSE)
    a = extract_rnd_breeden_litzenberger(inp)
    b = extract_rnd_breeden_litzenberger(inp, anchor_wings=True, ghost_anchor_weight=0.0)
    assert np.array_equal(a.rnd_density, b.rnd_density)


def test_ghost_mass_warning_fires_below_five_percent():
    """The threshold used to be 5%, so a case with 4% fabricated mass stayed silent."""
    inp = _input(SPARSE)
    r = extract_rnd_breeden_litzenberger(inp)
    if r.ghost_mass_fraction > 0.02:
        assert any("outside the observed" in w for w in r.warnings), r.warnings


# ----------------------------------------------------------------------------------
# vol-space fit
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("sigma,tte", [(0.30, 0.25), (0.60, 0.50), (0.90, 1.00)])
def test_vol_space_recovers_a_known_normal_density(sigma, tte):
    true_sd = sigma * np.sqrt(tte)
    half = np.ceil(5.0 * true_sd / 0.125) * 0.125
    strikes = np.arange(96.0 - half, 96.0 + half + 1e-9, 0.125)
    inp = _input(strikes, sigma=sigma, tte=tte)
    r = extract_rnd_breeden_litzenberger(inp, fit_space="vol")
    assert r.mean_rate == pytest.approx(4.0, abs=0.01)
    assert r.std_rate == pytest.approx(true_sd, rel=0.05)
    assert r.kurtosis == pytest.approx(3.0, abs=0.5)
    assert float(np.sum(r.bin_probabilities)) == pytest.approx(1.0, abs=1e-9)


def test_vol_space_rejects_unknown_fit_space():
    with pytest.raises(ValueError, match="fit_space must be"):
        extract_rnd_breeden_litzenberger(_input(SPARSE), fit_space="delta")


def test_vol_space_needs_enough_invertible_quotes():
    with pytest.raises(ValueError, match="invertible quotes"):
        extract_rnd_breeden_litzenberger(
            _input(np.array([95.5, 96.0, 96.5])), fit_space="vol"
        )


# ----------------------------------------------------------------------------------
# Bachelier vol inversion
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize("sigma", [0.20, 0.60, 1.50])
@pytest.mark.parametrize("n_sd", [-3.0, -1.0, 0.0, 1.0, 3.0])
def test_implied_vol_round_trips(sigma, n_sd):
    F, T, DF = 96.0, 0.4, 0.99
    K = F + n_sd * sigma * np.sqrt(T)
    px = bachelier_call_prices_vectorized(np.array([K]), F, np.array([sigma]), T, DF)[0]
    assert bachelier_implied_vol(px, K, F, T, DF) == pytest.approx(sigma, abs=1e-8)


def test_implied_vol_returns_nan_below_intrinsic():
    """A wing pinned at the settlement tick often sits at or below intrinsic; that must
    not be coerced into a fabricated vol."""
    F, T, DF = 96.0, 0.4, 0.99
    assert np.isnan(bachelier_implied_vol(DF * (F - 94.0) - 1e-9, 94.0, F, T, DF))
    assert np.isnan(bachelier_implied_vol(0.0, 96.0, F, T, DF))
    assert np.isnan(bachelier_implied_vol(-1.0, 96.0, F, T, DF))


def test_vega_collapses_in_the_wings():
    """The reason wing vols are unreliable and must be downweighted."""
    F, T = 96.0, 0.4
    strikes = np.array([96.0, 97.0, 98.0])
    vega = bachelier_vega(strikes, F, np.full(3, 0.4), T, 1.0)
    assert vega[0] > vega[1] > vega[2]
    assert vega[2] < 0.05 * vega[0]
