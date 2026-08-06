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
    """Flat 4%, act360 -- the convention USD-OIS actually carries.

    ``rl_curve_definitions_map`` gives ``USD-OIS`` DayCounter act360 and
    ReferenceRate ``usd_irs``, whose legs are act360 too, so curve and index
    agree. The fixture was act365f until rateslib 2.7.1, which refuses to
    forecast an act360 RFR index off an act365f curve outright
    (``ValueError: A `rate_curve` and `rate_index` have been supplied with
    conflicting parameters``) -- see
    ``tests/test_strikeless_vol_greeks_control.py`` for that refusal pinned,
    and for the act365f case kept alive on a market (GBP) that really is
    act365f on both sides. Nothing asserted in this file names a number the
    convention moves: every assertion here is a sign, a structural identity,
    or the $100k sizing target that is an INPUT.
    """
    nodes = {REF: 1.0}
    nodes.update({rl.dt(2026 + y, 8, 3): 1.0 / (1.04 ** y) for y in range(1, 41)})
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id="flat4")
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
    """Sized in the spec's DV01 measure -- bump-and-reprice, +/-1bp central
    difference -- not the analytic annuity (``curve.pv01``). The two agree
    to within ~4% even on this flat fixture (``curve.pv01`` gives $96,160.97,
    not $100,000, for this same leg; $-96,162.29 for the 20y10y -- see
    ``tests/test_strikeless_vol_breakeven.py``'s inverted-curve residual for
    where that gap becomes 11%+ and the reason sizing moved off ``pv01``).

    Those two figures are Task 9's own ("$96,161/-$96,162 on the flat
    fixture") and they are unchanged by this file's act365f -> act360 fixture
    move -- because they were **always act360 numbers**. ``rl.Curve.shift``
    moves an act360 curve ``365/360`` further per nominal bp than an act365f
    one (measured directly on discount factors: log-DF ratio 1.01388889 vs
    365/360 = 1.01388889), so a leg sized to $100k of repriced DV01 carries a
    ``360/365`` smaller notional there, and its ``pv01`` scales with it. On
    the act365f fixture this docstring used to sit on, the same leg gives
    $97,496.54. The number was quoted from the act360 control fixture; the
    fixture change made it true of the fixture it is written on.

    **This is circular, not an independent check**: it recomputes the exact
    same +/-1bp central difference ``build_leg``/``_reprice_dv01`` sizes off,
    on the same curve and the same ``h_bp``, so it can only fail if NPV is
    non-linear in notional (it is not -- NPV is a linear function of
    notional for a fixed-rate/float swap under a given curve, by
    construction). There is currently no independent closed-form control for
    this first-derivative sizing specifically. What IS independent:
    ``test_control_bites_when_the_bump_unit_is_wrong`` /
    ``test_bp_read_as_a_decimal_cannot_even_be_repriced``
    (``test_strikeless_vol_greeks_control.py``) sabotage the underlying
    ``rl.Curve.shift`` primitive that ``_reprice_dv01`` and ``package_gamma``
    both depend on, and confirm a unit/sign bug in THAT primitive is caught
    -- but that control validates the SECOND derivative (Gamma) against a
    closed form using whatever notional the leg already has; it does not
    independently re-derive that the notional itself is correct. This test
    is kept as a smoke test (a gross regression -- e.g. someone deleting the
    scaling entirely -- would still fail it) with that limitation stated
    plainly rather than left circular and unlabelled.
    """
    leg = build_leg(curve, ForwardLeg("10Y", "10Y"), dv01_usd=100_000.0, direction=+1)
    handle = curve.handle()
    up = leg.npv(curves=handle.shift(1.0)).real
    dn = leg.npv(curves=handle.shift(-1.0)).real
    reprice_dv01 = (up - dn) / 2.0
    assert abs(reprice_dv01) == pytest.approx(100_000.0, rel=1e-6)


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
