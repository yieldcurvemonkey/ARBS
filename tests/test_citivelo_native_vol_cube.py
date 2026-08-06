r"""The rateslib-native IR vol cube: conventions, guards, and backend agreement.

The thing these tests exist to pin is the **strike axis convention**.
``rl.IRSplineCube(strikes=...)`` takes signed BASIS POINTS from the ATM forward.
An earlier revision of this repo passed percent, which builds without error,
round-trips the ATM node exactly, and misprices every off-ATM strike by up to a
factor of five - the exact failure shape that a green test suite would not have
caught. So the guard is mutation-tested here, not merely exercised: three
deliberately wrong cubes must raise, and the correct one must not.

The second thing is that the two backends agree. They share nothing but the
input data and the curve: the hand-built cube interpolates with ``PPSplineF64``
and prices through QuantLib's Bachelier, the native one interpolates inside
rateslib and prices through ``rl.IRSCall``. Agreement to ~1e-15 relative is
therefore evidence about both.
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd
import pytest

rl = pytest.importorskip("rateslib")

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.vol.cube_data import SwaptionCubeData, cube_from_quotes, cube_tags
from MDP.CitiVelocityExcel.vol.rl_cube import CitiVeloNormalVolCube, build_rl_vol_cube
from MDP.CitiVelocityExcel.vol.rl_native_cube import (
    RATESLIB_NATIVE_AVAILABLE,
    NativeCubeUnverifiedError,
    NativeSwaptionCube,
    assert_native_cube_round_trips,
    build_rl_native_cube,
    build_rl_native_swaption_cube,
    compare_backends,
    irs_series_for,
    native_spline_order,
)

pytestmark = pytest.mark.skipif(
    not RATESLIB_NATIVE_AVAILABLE,
    reason="needs rateslib >= 2.7.0 for IRSplineCube / IRSCall",
)

AS_OF = datetime.date(2026, 8, 5)
EVAL = datetime.datetime(2026, 8, 5)
CURRENCY = "USD"
EXPIRIES = ("1Y", "2Y", "5Y", "10Y")
TENORS = ("2Y", "5Y", "10Y", "30Y")
OFFSETS = (-100.0, -50.0, -25.0, 25.0, 50.0, 100.0)
NOTIONAL = 1e8

_YEARS = {"M": 1.0 / 12.0, "Y": 1.0}


def _yrs(token: str) -> float:
    return float(token[:-1]) * _YEARS[token[-1]]


def _atm_bp(expiry: str, tenor: str) -> float:
    te, ts = _yrs(expiry), _yrs(tenor)
    return 55.0 + 60.0 * math.exp(-ts / 8.0) + 20.0 * math.exp(-te / 2.0) - 3.0 * math.log1p(te)


def _spread_bp(expiry: str, tenor: str, offset: float) -> float:
    te, ts = _yrs(expiry), _yrs(tenor)
    u = offset / 100.0
    return (6.0 + 4.0 * math.exp(-te)) * u * u - (3.0 + 2.0 * math.exp(-ts / 10.0)) * u


@pytest.fixture(scope="module")
def cube() -> SwaptionCubeData:
    tag_map = cube_tags(
        currency=CURRENCY,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets_bp=OFFSETS,
        measure="NORMAL",
        skew_measure="NORMALABSOLUTE",
    )
    quotes = {}
    for tag, (kind, expiry, tenor, offset) in tag_map.items():
        base = _atm_bp(expiry, tenor)
        quotes[tag] = base if kind == "ATM" else base + _spread_bp(expiry, tenor, offset)
    return cube_from_quotes(
        quotes=quotes,
        currency=CURRENCY,
        as_of=AS_OF,
        expiries=EXPIRIES,
        tenors=TENORS,
        offsets_bp=OFFSETS,
        served_unit="bp",
        source="pytest/synthetic",
    )


@pytest.fixture(scope="module")
def rl_curve():
    nodes = {EVAL: 1.0}
    for t in (0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 45):
        zero = 0.030 + 0.012 * (1.0 - math.exp(-t / 4.0))
        nodes[EVAL + datetime.timedelta(days=int(round(t * 365)))] = math.exp(-zero * t)
    return rl.Curve(
        nodes, interpolation="log_linear", calendar="nyc", convention="act360", id="test_sofr"
    )


@pytest.fixture(scope="module")
def native(cube, rl_curve) -> NativeSwaptionCube:
    return build_rl_native_swaption_cube(cube=cube, rl_curve=rl_curve, notional=NOTIONAL)


def _params(cube: SwaptionCubeData) -> np.ndarray:
    return np.array(
        [
            [[float(cube.vol(e, t, o)) for o in cube.offsets()] for t in cube.tenors()]
            for e in cube.expiries()
        ],
        dtype=float,
    )


# ------------------------------------------------------------------ #
#                       the strike convention                        #
# ------------------------------------------------------------------ #


def test_strike_axis_is_signed_basis_points_from_the_forward(cube):
    """The whole point of this module. Nodes are keyed on the bp offset itself."""
    native = build_rl_native_cube(cube=cube, verify=True)
    smile = native.get_smile("2Y", "10Y")

    assert sorted(float(k) for k in smile.nodes.nodes) == sorted(cube.offsets())
    for offset in cube.offsets():
        assert float(smile.nodes.nodes[float(offset)]) == pytest.approx(
            cube.vol("2Y", "10Y", offset), abs=1e-12
        )


def test_strike_axis_is_forward_invariant(cube):
    """``get_from_strike(f + off/100, f=f)`` gives the same vol for any ``f``.

    This is what lets :func:`assert_native_cube_round_trips` check nodes without
    a curve, and it is only true because the axis is bp-relative rather than
    absolute.
    """
    native = build_rl_native_cube(cube=cube, verify=False)
    smile = native.get_smile("2Y", "10Y")

    baseline = [
        float(smile.get_from_strike(3.0 + o / 100.0, f=3.0).vol) for o in cube.offsets()
    ]
    for forward in (0.25, 4.2, 9.9, -1.0):
        got = [float(smile.get_from_strike(forward + o / 100.0, f=forward).vol) for o in cube.offsets()]
        assert got == baseline


def test_parameters_are_basis_points_of_normal_vol(cube, native, rl_curve):
    """rateslib holds the vol in percent internally; the input is in bp.

    ``analytic_greeks()['__vol']`` is the pricing input alongside ``__forward``,
    both in percent, so the cube's bp parameter must appear there divided by 100.
    If ``parameters`` were themselves percent, this would be 100x out and every
    premium with it.
    """
    quoted_bp = cube.vol("2Y", "10Y", 0.0)
    greeks = native.greeks("2Y", "10Y", "atm")

    assert float(greeks["__vol"]) == pytest.approx(quoted_bp / 100.0, rel=1e-12)
    assert native.normal_vol("2Y", "10Y", offset_bp=0.0) == pytest.approx(quoted_bp, abs=1e-10)


def test_named_spec_is_preferred_over_a_hand_built_series():
    """USD has ``usd_irs``; using it means the cube's underlying cannot drift.

    A hand-rolled ``IRSSeries`` reproduces every field except ``payment_lag``,
    which the spec sets to T+2 and which moves the premium's discount factor.
    """
    assert irs_series_for("USD_SOFR") == "usd_irs"


# ------------------------------------------------------------------ #
#                     the guard, mutation-tested                     #
# ------------------------------------------------------------------ #


def test_guard_catches_a_percent_strike_axis(cube):
    """The original bug: strikes passed as percent moneyness.

    It builds, the ATM node is exact, and the wings are wrong by thousands of bp.
    """
    bad = rl.IRSplineCube(
        expiries=list(cube.expiries()),
        tenors=list(cube.tenors()),
        strikes=[o / 100.0 for o in cube.offsets()],
        eval_date=EVAL,
        irs_series="usd_irs",
        parameters=_params(cube),
        pricing_model="normal_vol",
        k=4,
        id="BAD-PERCENT",
    )
    # The trap that made this hard to spot: ATM alone looks perfect.
    atm = float(bad.get_smile("2Y", "10Y").get_from_strike(3.0, f=3.0).vol)
    assert atm == pytest.approx(cube.vol("2Y", "10Y", 0.0), abs=1e-9)

    with pytest.raises(NativeCubeUnverifiedError, match="did not reproduce its own input nodes"):
        assert_native_cube_round_trips(bad, cube)


def test_guard_catches_a_transposed_parameter_block(cube):
    """Swapping two tenor slices leaves the shape valid and the cube wrong."""
    params = _params(cube)
    swapped = params.copy()
    swapped[:, 0, :], swapped[:, 1, :] = params[:, 1, :], params[:, 0, :]
    bad = rl.IRSplineCube(
        expiries=list(cube.expiries()),
        tenors=list(cube.tenors()),
        strikes=[float(o) for o in cube.offsets()],
        eval_date=EVAL,
        irs_series="usd_irs",
        parameters=swapped,
        pricing_model="normal_vol",
        k=4,
        id="BAD-TRANSPOSED",
    )
    with pytest.raises(NativeCubeUnverifiedError):
        assert_native_cube_round_trips(bad, cube)


def test_guard_catches_a_single_hundredth_of_a_basis_point(cube):
    """Tolerance probe: the guard is tight, not decorative."""
    params = _params(cube)
    params[1, 1, 3] += 0.01
    bad = rl.IRSplineCube(
        expiries=list(cube.expiries()),
        tenors=list(cube.tenors()),
        strikes=[float(o) for o in cube.offsets()],
        eval_date=EVAL,
        irs_series="usd_irs",
        parameters=params,
        pricing_model="normal_vol",
        k=4,
        id="BAD-NUDGED",
    )
    with pytest.raises(NativeCubeUnverifiedError, match=r"worst error 0\.01"):
        assert_native_cube_round_trips(bad, cube)


def test_the_correct_cube_passes_the_same_guard(cube):
    """The control for the three mutations above."""
    native = build_rl_native_cube(cube=cube, verify=False)
    assert assert_native_cube_round_trips(native, cube) < 1e-9


def test_round_trip_with_real_forwards_agrees_with_the_forward_free_check(cube, rl_curve, native):
    """Passing real forwards exercises the query path pricing uses."""
    forwards = {
        (e, t): native.forward(e, t) * 100.0 for e in cube.expiries() for t in cube.tenors()
    }
    assert assert_native_cube_round_trips(native.native, cube, forwards) < 1e-9


def test_nan_nodes_are_caught_by_the_cube_s_own_validation(cube):
    """``validate()`` runs first, so a hole never reaches IRSplineCube."""
    from MDP.CitiVelocityExcel.vol.cube_data import RaggedCubeError

    holed = SwaptionCubeData(
        as_of=cube.as_of,
        currency=cube.currency,
        measure=cube.measure,
        atm=cube.atm.copy(),
        skew={k: v.copy() for k, v in cube.skew.items()},
        source="pytest/holed",
    )
    holed.atm.iloc[1, 1] = float("nan")
    with pytest.raises(RaggedCubeError, match="NaN"):
        build_rl_native_cube(cube=holed)


def test_infinite_nodes_are_refused_by_the_native_builder(cube):
    """The gap ``validate()`` leaves: ``isna()`` is False for an infinity.

    IRSplineCube builds happily from one and every premium that touches it comes
    back NaN with no exception raised anywhere.
    """
    poisoned = SwaptionCubeData(
        as_of=cube.as_of,
        currency=cube.currency,
        measure=cube.measure,
        atm=cube.atm.copy(),
        skew={k: v.copy() for k, v in cube.skew.items()},
        source="pytest/poisoned",
    )
    poisoned.atm.iloc[1, 1] = float("inf")
    assert not poisoned.atm.isna().to_numpy().any()  # validate() would let this through

    with pytest.raises(ValueError, match="not finite"):
        build_rl_native_cube(cube=poisoned)


# ------------------------------------------------------------------ #
#                        backend agreement                           #
# ------------------------------------------------------------------ #


def test_both_backends_agree_on_vol_forward_price_and_vega(cube, rl_curve):
    """The reconciliation the native backend is gated on.

    Different interpolators, different Bachelier implementations, different
    annuity derivations - the same numbers.
    """
    frame = compare_backends(
        cube=cube,
        rl_curve=rl_curve,
        notional=NOTIONAL,
        expiries=["1Y", "2Y", "5Y"],
        tenors=["2Y", "10Y", "30Y"],
    )
    assert len(frame) == 3 * 3 * len(cube.offsets())

    assert frame["citi_vol_err_bp"].abs().max() < 1e-9
    assert frame["vol_diff_bp"].abs().max() < 1e-9
    assert frame["forward_diff_bp"].abs().max() < 1e-6
    assert frame["price_rel"].max() < 1e-9
    # The native vega is a +/-0.5bp central difference of its own price, so it
    # carries an O(h^2) truncation the hand-built analytic one does not. 1e-5 at
    # the wings, exact at the money.
    assert (frame["vega_diff"].abs() / frame["hand_vega"].abs()).max() < 1e-4


def test_the_comparison_would_show_a_disagreement_if_there_were_one(cube, rl_curve):
    """Verify the check, not just the result: perturb one backend's input.

    A comparison that cannot fail proves nothing about the one that passed.
    """
    shifted = SwaptionCubeData(
        as_of=cube.as_of,
        currency=cube.currency,
        measure=cube.measure,
        atm=cube.atm + 1.0,
        skew={k: v.copy() for k, v in cube.skew.items()},
        source="pytest/shifted",
    )
    hand = build_rl_vol_cube(cube=cube, rl_curve=rl_curve, notional=NOTIONAL)
    native = build_rl_native_swaption_cube(cube=shifted, rl_curve=rl_curve, notional=NOTIONAL)

    strike = hand.forward("2Y", "10Y")
    assert native.normal_vol("2Y", "10Y", offset_bp=0.0) - hand.normal_vol(
        "2Y", "10Y", offset_bp=0.0
    ) == pytest.approx(1.0, abs=1e-9)
    assert abs(native.price("2Y", "10Y", strike) / hand.price("2Y", "10Y", strike) - 1.0) > 1e-3


def test_backend_selector_returns_the_right_class(cube, rl_curve):
    assert isinstance(build_rl_vol_cube(cube=cube, rl_curve=rl_curve), CitiVeloNormalVolCube)
    assert isinstance(
        build_rl_vol_cube(cube=cube, rl_curve=rl_curve, backend="native"), NativeSwaptionCube
    )
    assert isinstance(
        build_rl_vol_cube(cube=cube, rl_curve=rl_curve, backend="auto"), NativeSwaptionCube
    )
    with pytest.raises(ValueError, match="backend must be"):
        build_rl_vol_cube(cube=cube, rl_curve=rl_curve, backend="quantlib")


# ------------------------------------------------------------------ #
#                     premium, PV and the greeks                     #
# ------------------------------------------------------------------ #


def test_price_is_the_premium_discounted_from_its_payment_date(native, rl_curve):
    """Three quantities that are easy to confuse. See the module docstring."""
    strike = native.forward("2Y", "10Y")
    premium = native.premium("2Y", "10Y", strike)
    pv = native.price("2Y", "10Y", strike)

    assert 0.0 < pv < premium
    discount = pv / premium
    # Premium pays two business days after a 2Y expiry, so the factor is the
    # curve's own ~2Y discount, not 1.0 and not the 12Y one.
    assert 0.85 < discount < 0.95


def test_an_unpriced_option_has_zero_npv_by_construction(native, rl_curve):
    """Not a bug and not a worthless option: rateslib struck it at mid.

    This is the trap that makes ``npv()`` look broken. ``price()`` passes
    ``premium=0.0`` for exactly this reason.
    """
    unpriced = native.swaption("2Y", "10Y", "atm")
    assert float(unpriced.npv(curves=native._curves(), vol=native.native)) == pytest.approx(0.0, abs=1e-6)

    zero_premium = native.swaption("2Y", "10Y", "atm", premium=0.0)
    assert float(zero_premium.npv(curves=native._curves(), vol=native.native)) > 1e6


def test_vega_is_the_pv_change_per_basis_point_of_normal_vol(cube, rl_curve, native):
    """Measured against an independent one-sided bump, not asserted from the docs."""
    bumped_data = SwaptionCubeData(
        as_of=cube.as_of,
        currency=cube.currency,
        measure=cube.measure,
        atm=cube.atm + 1.0,
        skew={k: v + 1.0 for k, v in cube.skew.items()},
        source="pytest/bumped",
    )
    bumped = build_rl_native_swaption_cube(cube=bumped_data, rl_curve=rl_curve, notional=NOTIONAL)

    strike = native.forward("2Y", "10Y")
    finite_difference = bumped.price("2Y", "10Y", strike) - native.price("2Y", "10Y", strike)
    assert native.vega("2Y", "10Y", strike) == pytest.approx(finite_difference, rel=2e-3)


def test_analytic_and_price_derived_vega_agree_when_the_dates_line_up(native):
    """With ``as_of`` on the curve's first node, rateslib's analytic vega is exact."""
    assert native.eval_date_gap_days == 0
    for offset in (-100.0, -25.0, 0.0, 25.0, 100.0):
        strike = native.forward("1Y", "10Y") + offset / 1e4
        assert native.vega("1Y", "10Y", strike) == pytest.approx(
            native.vega("1Y", "10Y", strike, analytic=True), rel=5e-5
        )


def _curve_from(reference: datetime.datetime):
    nodes = {reference: 1.0}
    for t in (0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30, 45):
        zero = 0.030 + 0.012 * (1.0 - math.exp(-t / 4.0))
        nodes[reference + datetime.timedelta(days=int(round(t * 365)))] = math.exp(-zero * t)
    return rl.Curve(
        nodes, interpolation="log_linear", calendar="nyc", convention="act360", id="shifted_sofr"
    )


def test_analytic_vega_is_wrong_when_the_curve_starts_after_the_cube(cube, caplog):
    """A rateslib 2.7.1 defect, found on live Citi data and pinned here.

    rateslib measures the option's time to expiry from the CURVE's first node
    while the premium uses the cube's ``eval_date``. The premium stays right; the
    analytic vega comes back low by sqrt(T'/T)*phi(d')/phi(d), which for one day
    on a 1Y expiry is 0.137% at the money.

    If a later rateslib fixes this, THIS TEST FAILS - which is the point. It is a
    detector, not an endorsement.
    """
    with caplog.at_level("WARNING"):
        shifted = build_rl_native_swaption_cube(
            cube=cube,
            rl_curve=_curve_from(EVAL + datetime.timedelta(days=1)),
            notional=NOTIONAL,
        )
    assert shifted.eval_date_gap_days == 1
    assert "times the option from the CURVE" in caplog.text

    strike = shifted.forward("1Y", "10Y")
    analytic = shifted.vega("1Y", "10Y", strike, analytic=True)
    from_price = shifted.vega("1Y", "10Y", strike)

    expected = math.sqrt(364.0 / 365.0)  # sqrt(T'/T) at the money
    assert analytic / from_price == pytest.approx(expected, rel=1e-4)
    assert analytic < from_price


def test_price_derived_vega_survives_the_date_mismatch(cube):
    """The defence: ``vega()`` differentiates the price, so the gap cannot bite."""
    shifted_curve = _curve_from(EVAL + datetime.timedelta(days=1))
    hand = CitiVeloNormalVolCube(cube=cube, rl_curve=shifted_curve, notional=NOTIONAL)
    shifted = build_rl_native_swaption_cube(cube=cube, rl_curve=shifted_curve, notional=NOTIONAL)
    for offset in (-100.0, 0.0, 100.0):
        strike = hand.forward("1Y", "10Y") + offset / 1e4
        assert shifted.vega("1Y", "10Y", strike) == pytest.approx(
            hand.vega("1Y", "10Y", strike), rel=1e-4
        )


def test_annuity_and_tte_survive_the_date_mismatch(cube):
    """The other place ``__sqrt_t`` would have leaked the curve-timing error in.

    ``_point`` computes the time to expiry itself and checks the resulting
    (annuity, tte) reprices a 25bp strike, so a mismatch cannot reach
    :meth:`annuity`, :meth:`to_frame` or :meth:`implied_normal_vol`.
    """
    aligned = build_rl_native_swaption_cube(
        cube=cube, rl_curve=_curve_from(EVAL), notional=NOTIONAL
    )
    shifted = build_rl_native_swaption_cube(
        cube=cube, rl_curve=_curve_from(EVAL + datetime.timedelta(days=1)), notional=NOTIONAL
    )
    hand = CitiVeloNormalVolCube(
        cube=cube, rl_curve=_curve_from(EVAL + datetime.timedelta(days=1)), notional=NOTIONAL
    )
    # rateslib reports sqrt_t off the curve; we must NOT be using it.
    reported = float(shifted.greeks("1Y", "10Y", "atm")["__sqrt_t"]) ** 2
    assert reported == pytest.approx(364.0 / 365.0, rel=1e-9)
    assert shifted.time_to_expiry("1Y") == pytest.approx(1.0, abs=1e-12)
    assert aligned.time_to_expiry("1Y") == pytest.approx(1.0, abs=1e-12)
    assert shifted.annuity("1Y", "10Y") == pytest.approx(hand.annuity("1Y", "10Y"), rel=1e-6)


def test_the_annuity_reprice_check_actually_fires(cube, monkeypatch):
    """Verify the check, not just the result.

    Shift the option's expiry date by a day so ``tte`` is 364/365 of the truth.
    The at-the-money premium still reprices (the annuity absorbs it) - it is the
    25bp probe that catches it, which is exactly why the probe is there.
    """
    # The control FIRST: monkeypatch below is class-level, so it would apply to
    # this object too if the call came after it.
    control = build_rl_native_swaption_cube(
        cube=cube, rl_curve=_curve_from(EVAL), notional=NOTIONAL
    )
    assert control.annuity("1Y", "10Y") > 0.0

    real = NativeSwaptionCube.expiry_date

    def one_day_early(self, expiry):
        return real(self, expiry) - datetime.timedelta(days=1)

    monkeypatch.setattr(NativeSwaptionCube, "expiry_date", one_day_early)
    broken = build_rl_native_swaption_cube(
        cube=cube, rl_curve=_curve_from(EVAL), notional=NOTIONAL
    )
    with pytest.raises(CitiVelocityError, match="does not reprice a 25bp strike"):
        broken.annuity("1Y", "10Y")


def test_no_warning_when_the_dates_do_line_up(cube, caplog):
    """The control for the warning above - it must not cry wolf."""
    with caplog.at_level("WARNING"):
        build_rl_native_swaption_cube(cube=cube, rl_curve=_curve_from(EVAL), notional=NOTIONAL)
    assert "times the option from the CURVE" not in caplog.text


def test_greeks_carry_the_full_analytic_set(native):
    greeks = native.greeks("2Y", "10Y", "atm")
    for key in ("delta", "gamma", "vega", "vanna", "vomma", "delta_usd", "vega_usd"):
        assert key in greeks
    # A Bachelier ATM call has delta exactly one half.
    assert float(greeks["delta"]) == pytest.approx(0.5, abs=1e-9)


def test_payer_and_receiver_satisfy_put_call_parity(native):
    """A payer minus a receiver at the forward is worth nothing."""
    forward = native.forward("2Y", "10Y")
    payer = native.price("2Y", "10Y", forward, right="payer")
    receiver = native.price("2Y", "10Y", forward, right="receiver")
    assert payer == pytest.approx(receiver, rel=1e-9)

    off = forward + 25e-4
    spread = native.price("2Y", "10Y", off, "payer") - native.price("2Y", "10Y", off, "receiver")
    annuity = native.annuity("2Y", "10Y")
    assert spread == pytest.approx(NOTIONAL * annuity * (forward - off), rel=1e-6)


def test_implied_normal_vol_inverts_price(native):
    strike = native.forward("2Y", "10Y") + 50e-4
    premium = native.price("2Y", "10Y", strike)
    recovered = native.implied_normal_vol("2Y", "10Y", strike, premium)
    assert recovered == pytest.approx(native.normal_vol("2Y", "10Y", strike=strike), rel=1e-6)


# ------------------------------------------------------------------ #
#                          interpolation                             #
# ------------------------------------------------------------------ #


def test_spline_order_downgrades_only_when_the_axis_is_too_short():
    assert native_spline_order(7) == 4
    assert native_spline_order(4) == 4
    assert native_spline_order(3) == 2
    assert native_spline_order(3, 4) == 4  # explicit is honoured, never downgraded
    assert native_spline_order(7, 2) == 2
    with pytest.raises(ValueError, match="no order 3"):
        native_spline_order(7, 3)


def test_the_cube_reports_the_interpolation_it_actually_used(native):
    """rateslib's expiry/tenor interpolation is bilinear and not configurable."""
    assert native.interpolation_used == {
        "expiry": "bilinear",
        "tenor": "bilinear",
        "offset": "spline",
    }


def test_off_grid_expiries_interpolate_between_neighbours(native, cube):
    """A 3Y expiry sits between the 2Y and 5Y rows and must land between them."""
    low = native.normal_vol("2Y", "10Y", offset_bp=0.0)
    high = native.normal_vol("5Y", "10Y", offset_bp=0.0)
    mid = native.normal_vol("3Y", "10Y", offset_bp=0.0)
    assert min(low, high) <= mid <= max(low, high)
    assert mid not in (low, high)


def test_outside_the_grid_holds_flat(native):
    """IRSplineCube's documented behaviour, pinned so a change is visible."""
    assert native.normal_vol("40Y", "30Y", offset_bp=0.0) == pytest.approx(
        native.normal_vol("10Y", "30Y", offset_bp=0.0), abs=1e-9
    )


def test_to_frame_covers_every_node(native, cube):
    frame = native.to_frame()
    assert len(frame) == len(cube.expiries()) * len(cube.tenors()) * len(cube.offsets())
    assert frame["vol_bp"].notna().all()
    assert (frame["annuity"] > 0).all()
    merged = frame.set_index(["expiry", "tenor", "offset_bp"])["vol_bp"]
    assert merged.loc[("2Y", "10Y", 25.0)] == pytest.approx(cube.vol("2Y", "10Y", 25.0))
