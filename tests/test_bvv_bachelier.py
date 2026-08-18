"""Unit tests for the Bachelier primitives used by the basis-vs-vol framework.

Each test is checked against a value known independently of the implementation (a closed form,
put-call parity, or a finite difference) rather than against the function under test.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from RVUtils.BasisVsVol.bachelier import (
    SQRT_2PI,
    contracts_for_vega,
    implied_normal_vol,
    normal_atm_price,
    normal_delta,
    normal_gamma,
    normal_price,
    normal_theta,
    normal_vega,
    vega_per_contract_usd,
)

# A realistic long-end point: 20y forward at 400bp, 100bp normal vol, 3 months.
F0, SIG0, T0 = 400.0, 100.0, 0.25


def test_atm_price_matches_closed_form():
    got = float(normal_price(F0, F0, SIG0, T0, w=1))
    want = SIG0 * math.sqrt(T0) / SQRT_2PI
    assert got == pytest.approx(want, rel=1e-12)
    assert float(normal_atm_price(SIG0, T0)) == pytest.approx(want, rel=1e-12)
    # sanity on magnitude: 100bp vol, 3m -> ~19.9bp of premium
    assert 19.0 < got < 21.0


def test_call_put_symmetry_at_the_money():
    c = float(normal_price(F0, F0, SIG0, T0, w=1))
    p = float(normal_price(F0, F0, SIG0, T0, w=-1))
    assert c == pytest.approx(p, rel=1e-12)


@pytest.mark.parametrize("K", [340.0, 380.0, 400.0, 425.0, 470.0])
def test_put_call_parity(K):
    c = float(normal_price(F0, K, SIG0, T0, w=1))
    p = float(normal_price(F0, K, SIG0, T0, w=-1))
    assert c - p == pytest.approx(F0 - K, abs=1e-10)


@pytest.mark.parametrize("K", [330.0, 375.0, 400.0, 430.0, 480.0])
@pytest.mark.parametrize("w", [1, -1])
def test_implied_vol_round_trip(K, w):
    px = float(normal_price(F0, K, SIG0, T0, w))
    back = implied_normal_vol(px, F0, K, T0, w)
    assert back == pytest.approx(SIG0, rel=1e-8)


def test_implied_vol_round_trip_extreme_moneyness_and_tenor():
    """Round-trip wherever the premium carries resolvable time value; nan where it does not."""
    checked_live, checked_dead = 0, 0
    for K in (250.0, 600.0):
        for T in (0.02, 1.0, 5.0):
            for sig in (25.0, 150.0):
                px = float(normal_price(F0, K, sig, T, w=1))
                tv = px - max(F0 - K, 0.0)
                back = implied_normal_vol(px, F0, K, T, w=1)
                if tv < 1e-10:
                    # unidentifiable by construction: the time value has underflowed
                    assert math.isnan(back), (K, T, sig, tv)
                    checked_dead += 1
                elif tv > 1e-4:
                    # resolvable time value: the inversion must recover the input vol
                    assert back == pytest.approx(sig, rel=1e-6), (K, T, sig, tv)
                    checked_live += 1
    # guard against the test silently degenerating into "everything is nan"
    assert checked_live >= 5, checked_live
    assert checked_dead >= 3, checked_dead


def test_implied_vol_rejects_sub_intrinsic():
    intrinsic = F0 - 350.0
    assert math.isnan(implied_normal_vol(intrinsic - 1.0, F0, 350.0, T0, w=1))


def test_implied_vol_returns_nan_not_zero_when_unidentified():
    """A vanishing time value must not be served as a 0.0 vol."""
    px = float(normal_price(F0, 900.0, 20.0, 0.02, w=1))  # underflows to exactly 0.0, deep OTM
    assert px == 0.0
    assert math.isnan(implied_normal_vol(px, F0, 900.0, 0.02, w=1))
    # deep ITM at exactly intrinsic is equally unidentified -- many small vols give this price
    assert math.isnan(implied_normal_vol(50.0, F0, 350.0, T0, w=1))
    # at the money, price = sigma*sqrt(T/2pi) is strictly increasing from zero, so zero IS the answer
    assert implied_normal_vol(0.0, F0, F0, T0, w=1) == 0.0


def test_atm_greeks_closed_forms():
    assert float(normal_delta(F0, F0, SIG0, T0, w=1)) == pytest.approx(0.5, rel=1e-12)
    assert float(normal_delta(F0, F0, SIG0, T0, w=-1)) == pytest.approx(-0.5, rel=1e-12)
    assert float(normal_gamma(F0, F0, SIG0, T0)) == pytest.approx(
        1.0 / (SIG0 * math.sqrt(2 * math.pi * T0)), rel=1e-12
    )
    assert float(normal_vega(F0, F0, SIG0, T0)) == pytest.approx(math.sqrt(T0) / SQRT_2PI, rel=1e-12)
    assert float(normal_theta(F0, F0, SIG0, T0)) == pytest.approx(
        SIG0 / (2.0 * math.sqrt(2 * math.pi * T0)), rel=1e-12
    )


@pytest.mark.parametrize("K", [370.0, 400.0, 435.0])
@pytest.mark.parametrize("w", [1, -1])
def test_greeks_match_finite_differences(K, w):
    h = 1e-4
    d_fd = (float(normal_price(F0 + h, K, SIG0, T0, w)) - float(normal_price(F0 - h, K, SIG0, T0, w))) / (2 * h)
    assert float(normal_delta(F0, K, SIG0, T0, w)) == pytest.approx(d_fd, abs=1e-7)

    # gamma needs a much larger bump: with h=1e-4 the second difference of an O(30) price loses
    # ~10 significant figures to cancellation. h=0.05bp keeps roundoff ~1e-11 and truncation ~4e-10.
    hg = 0.05
    g_fd = (
        float(normal_price(F0 + hg, K, SIG0, T0, w))
        - 2 * float(normal_price(F0, K, SIG0, T0, w))
        + float(normal_price(F0 - hg, K, SIG0, T0, w))
    ) / (hg * hg)
    assert float(normal_gamma(F0, K, SIG0, T0)) == pytest.approx(g_fd, rel=1e-6)

    hv = 1e-5
    v_fd = (float(normal_price(F0, K, SIG0 + hv, T0, w)) - float(normal_price(F0, K, SIG0 - hv, T0, w))) / (2 * hv)
    assert float(normal_vega(F0, K, SIG0, T0)) == pytest.approx(v_fd, rel=1e-6)

    ht = 1e-7
    t_fd = (float(normal_price(F0, K, SIG0, T0 + ht, w)) - float(normal_price(F0, K, SIG0, T0 - ht, w))) / (2 * ht)
    assert float(normal_theta(F0, K, SIG0, T0)) == pytest.approx(t_fd, rel=1e-3)


def test_gamma_theta_relation():
    """Bachelier PDE with zero rates: theta = 0.5 * sigma^2 * gamma (per year)."""
    for K in (360.0, 400.0, 440.0):
        g = float(normal_gamma(F0, K, SIG0, T0))
        th = float(normal_theta(F0, K, SIG0, T0))
        assert th == pytest.approx(0.5 * SIG0**2 * g, rel=1e-12)


def test_price_monotone_in_vol_and_expiry():
    sigs = np.array([10.0, 50.0, 100.0, 200.0])
    px = normal_price(F0, 420.0, sigs, T0, w=1)
    assert np.all(np.diff(px) > 0)
    ts = np.array([0.05, 0.25, 0.5, 1.0])
    px = normal_price(F0, 420.0, SIG0, ts, w=1)
    assert np.all(np.diff(px) > 0)


def test_zero_vol_is_intrinsic():
    assert float(normal_price(F0, 380.0, 0.0, T0, w=1)) == pytest.approx(20.0, abs=1e-9)
    assert float(normal_price(F0, 420.0, 0.0, T0, w=1)) == pytest.approx(0.0, abs=1e-9)


def test_vega_per_contract_usd_hand_calc():
    """ZB-like: fv01 = 0.1458 price points per bp, 3m expiry, $1,000 per point.

    ATM premium in points = sigma_bp * fv01 * sqrt(T/2pi); per 1bp of vol and per contract that
    is 0.1458 * sqrt(0.25)/sqrt(2pi) * 1000 = $29.08.
    """
    got = vega_per_contract_usd(0.145781, 0.25)
    want = 0.145781 * math.sqrt(0.25) / SQRT_2PI * 1000.0
    assert got == pytest.approx(want, rel=1e-12)
    assert got == pytest.approx(29.08, abs=0.05)

    n = contracts_for_vega(100_000.0, 0.145781, 0.25)
    assert n == pytest.approx(100_000.0 / want, rel=1e-12)
    assert 3300 < n < 3500


def test_vega_scales_with_sqrt_time():
    a = vega_per_contract_usd(0.145781, 0.25)
    b = vega_per_contract_usd(0.145781, 1.0)
    assert b / a == pytest.approx(2.0, rel=1e-12)
