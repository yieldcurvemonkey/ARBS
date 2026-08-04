# tests/test_strikeless_vol_greeks.py
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.conventions import FLATTENER, STEEPENER
from RVUtils.StrikelessVol.greeks import build_leg, build_package, package_npv
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 8, 3)


@pytest.fixture(scope="module")
def curve():
    nodes = {REF: 1.0}
    nodes.update({rl.dt(2026 + y, 8, 3): 1.0 / (1.04 ** y) for y in range(1, 41)})
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="flat4")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        # rateslib 2.1.1's _FloatLegMixin._set_fixings crashes on an empty
        # pd.Series (unconditional ser.index[-1] on zero-length data; see
        # rateslib/legs/base.py:501). Python None construct()s but then
        # fails at .npv() time ("fixings should be of type scalar, None,
        # list or Series" -- misleading; only the NoInput sentinel actually
        # works, confirmed against a bare rl.IRS().npv()). All legs here
        # are forward-starting 10-20y out and need no historical fixings,
        # so rl.NoInput(0) is the correct value.
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


@pytest.fixture(scope="module")
def pair():
    return ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))


def test_payer_gains_when_rates_rise(curve):
    """Pins rateslib's notional sign convention. Everything downstream uses it."""
    payer = build_leg(curve, ForwardLeg("10Y", "10Y"), dv01_usd=100_000.0, direction=+1)
    base = payer.npv(curves=curve.handle()).real
    up = payer.npv(curves=curve.handle().shift(25)).real
    assert up > base


def test_leg_is_sized_to_the_requested_dv01(curve):
    leg = build_leg(curve, ForwardLeg("10Y", "10Y"), dv01_usd=100_000.0, direction=+1)
    assert abs(curve.pv01(leg)) == pytest.approx(100_000.0, rel=1e-6)


def test_flattener_receives_the_longer_leg_and_pays_the_shorter(curve, pair):
    pkg = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    # receiving the longer leg: its PV falls when rates rise
    up = pkg.long.npv(curves=curve.handle().shift(25)).real
    assert up < pkg.long.npv(curves=curve.handle()).real
    # paying the shorter leg: its PV rises when rates rise
    up_s = pkg.short.npv(curves=curve.handle().shift(25)).real
    assert up_s > pkg.short.npv(curves=curve.handle()).real


def test_package_is_dv01_neutral_at_inception(curve, pair):
    pkg = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    net = abs(pkg.short_dv01) - abs(pkg.long_dv01)
    assert net == pytest.approx(0.0, abs=1.0)  # $1 on a $100k DV01 package


def test_package_starts_at_zero_pv(curve, pair):
    pkg = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    assert package_npv(curve.handle(), pkg) == pytest.approx(0.0, abs=1.0)


def test_steepener_is_the_mirror_of_the_flattener(curve, pair):
    flat = build_package(curve, pair, package_dv01_usd=100_000.0, sign=FLATTENER)
    steep = build_package(curve, pair, package_dv01_usd=100_000.0, sign=STEEPENER)
    shifted = curve.handle().shift(25)
    assert package_npv(shifted, flat) == pytest.approx(
        -package_npv(shifted, steep), rel=1e-9
    )
