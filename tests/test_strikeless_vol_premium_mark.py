"""Premium-mark unit pins: round trip, parity, hand values, mutation."""
import math

import pytest

from RVUtils.StrikelessVol.premium_mark import (
    implied_from_straddle_usd,
    straddle_delta,
    straddle_premium_usd,
)


def test_atm_straddle_hand_value():
    # ATM Bachelier call = sigma*sqrt(T)*phi(0), phi(0) = 1/sqrt(2*pi);
    # straddle = 2x. sigma=100bp=0.01, T=1, annuity $80,000/bp:
    # $ = 2 * 0.01 * (1/sqrt(2pi)) * 80_000 * 1e4
    phi0 = 1.0 / math.sqrt(2.0 * math.pi)
    usd = straddle_premium_usd(forward=0.04, strike=0.04, vol_bp_annual=100.0,
                               tte_yrs=1.0, annuity_per_bp=80_000.0)
    assert usd == pytest.approx(2.0 * 0.01 * phi0 * 80_000.0 * 1e4, rel=1e-12)


def test_round_trip_inversion_atm_and_otm():
    for strike in (0.04, 0.0425, 0.036):
        usd = straddle_premium_usd(forward=0.04, strike=strike, vol_bp_annual=84.5,
                                   tte_yrs=1.0, annuity_per_bp=80_000.0)
        iv = implied_from_straddle_usd(premium_usd=usd, forward=0.04, strike=strike,
                                       tte_yrs=1.0, annuity_per_bp=80_000.0)
        assert iv == pytest.approx(84.5, abs=1e-6)


def test_delta_signs_and_atm_zero():
    assert straddle_delta(forward=0.04, strike=0.04, vol_bp_annual=80.0, tte_yrs=1.0) == 0.0
    # 50bp ITM at sigma=80bp/yr, T=1: d = 50/80 = 0.625 -> 2*Phi(0.625)-1 = 0.46803
    d = straddle_delta(forward=0.045, strike=0.04, vol_bp_annual=80.0, tte_yrs=1.0)
    assert d == pytest.approx(0.4680289419, abs=1e-8)
    # deep ITM at tiny vol: d = 50/10 = 5 -> delta ~ 1
    assert straddle_delta(forward=0.045, strike=0.04, vol_bp_annual=10.0, tte_yrs=1.0) > 0.999
    assert straddle_delta(forward=0.035, strike=0.04, vol_bp_annual=10.0, tte_yrs=1.0) < -0.999


def test_mutation_percent_as_decimal_is_caught():
    """Feeding vol as PERCENT (0.845) instead of annual bp (84.5) collapses the
    premium by ~100x — the repo's recorded 100x trap. The round trip makes it
    visible: inverted vol comes back ~100x smaller, never ~equal."""
    usd_bad = straddle_premium_usd(forward=0.04, strike=0.04, vol_bp_annual=0.845,
                                   tte_yrs=1.0, annuity_per_bp=80_000.0)
    iv = implied_from_straddle_usd(premium_usd=usd_bad, forward=0.04, strike=0.04,
                                   tte_yrs=1.0, annuity_per_bp=80_000.0)
    assert iv is not None and iv < 2.0  # nowhere near 84.5


def test_expired_or_zero_vol_is_intrinsic():
    usd = straddle_premium_usd(forward=0.045, strike=0.04, vol_bp_annual=80.0,
                               tte_yrs=0.0, annuity_per_bp=80_000.0)
    assert usd == pytest.approx(0.005 * 80_000.0 * 1e4, rel=1e-12)
