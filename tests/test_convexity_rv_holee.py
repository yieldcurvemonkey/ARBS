"""Known-answer tests for the Ho-Lee convexity adjustment and its inversion.

The planted answer is Hull's worked example (*Options, Futures and Other
Derivatives*, the Eurodollar futures convexity-adjustment section): with
sigma = 1.2% (120bp/yr), a contract expiring in 8 years on a 3M rate
(T1 = 8, T2 = 8.25) carries an adjustment of

    0.5 * 0.012^2 * 8 * 8.25 = 0.004752  =  0.4752%  =  47.52bp

which the textbook quotes as 0.475%. A checking tool that is itself wrong
reports success and hides the thing it was built to find, so the inversion is
tested against the same planted number rather than only round-tripped.
"""

import numpy as np
import pytest

from RVUtils.ConvexityRV.holee import (
    ACCRUAL_3M,
    ho_lee_ca,
    ho_lee_ca_bp,
    implied_vol_from_ca,
    implied_vol_from_ca_bp,
    pack_ca_bp,
    pack_time_weight,
)


def test_hull_worked_example_decimal():
    """Hull: sigma=1.2%, T1=8, T2=8.25 -> CA = 0.475%."""
    ca = ho_lee_ca(sigma=0.012, t1=8.0, t2=8.25)
    assert ca == pytest.approx(0.004752, abs=1e-9)
    assert ca * 100 == pytest.approx(0.4752, abs=1e-6)  # in percent, as Hull quotes


def test_hull_worked_example_bp():
    """Same number through the bp-unit boundary -- catches 1e4 slips."""
    assert ho_lee_ca_bp(sigma_bp=120.0, t1=8.0, t2=8.25) == pytest.approx(47.52, abs=1e-6)


def test_inversion_recovers_hull_vol():
    """Inverting the planted adjustment must give the planted vol back."""
    # A degenerate one-contract "pack" reduces to the single-contract formula.
    t1s = [8.0]
    assert pack_time_weight(t1s) == pytest.approx(8.0 * 8.25)
    sigma = implied_vol_from_ca(ca=0.004752, t1s=t1s)
    assert sigma == pytest.approx(0.012, rel=1e-9)
    assert implied_vol_from_ca_bp(ca_bp=47.52, t1s=t1s) == pytest.approx(120.0, rel=1e-9)


def test_pack_average_matches_mean_of_contract_adjustments():
    """A pack's model CA is the mean of its four contract CAs, by construction."""
    sigma_bp = 90.0
    t1s = [2.00, 2.25, 2.50, 2.75]
    by_contract = np.mean([ho_lee_ca_bp(sigma_bp, t, t + ACCRUAL_3M) for t in t1s])
    assert pack_ca_bp(sigma_bp, t1s) == pytest.approx(by_contract, rel=1e-12)


def test_pack_roundtrip_is_exact():
    sigma_bp = 75.0
    t1s = [1.0, 1.25, 1.5, 1.75]
    ca_bp = pack_ca_bp(sigma_bp, t1s)
    assert implied_vol_from_ca_bp(ca_bp, t1s) == pytest.approx(sigma_bp, rel=1e-10)


def test_adjustment_grows_with_expiry_and_vol():
    """Monotonicity: CA rises in both sigma and time. A sign/ordering regression
    in the inversion would show up here before it reaches a backtest."""
    assert ho_lee_ca_bp(100.0, 5.0, 5.25) > ho_lee_ca_bp(100.0, 2.0, 2.25)
    assert ho_lee_ca_bp(120.0, 5.0, 5.25) > ho_lee_ca_bp(100.0, 5.0, 5.25)


@pytest.mark.parametrize("bad_ca", [0.0, -1e-6, float("nan")])
def test_non_positive_ca_is_not_invertible(bad_ca):
    """A negative observed adjustment has no Ho-Lee vol -- must be NaN, not a
    complex number and not a silent zero."""
    assert np.isnan(implied_vol_from_ca(bad_ca, [2.0, 2.25, 2.5, 2.75]))


def test_empty_pack_is_nan():
    assert np.isnan(pack_time_weight([]))
