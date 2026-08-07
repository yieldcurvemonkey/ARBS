"""Tests for utils.rl_compat -- the rateslib version-tolerance shims.

Two halves:

* against the **installed** rateslib, assert the shim agrees with the spelling
  that version actually accepts, and assert the *other* spelling really is
  rejected (otherwise the first assertion is vacuous and would pass on a
  rateslib that tolerated both);
* against **fakes** shaped like the other rateslib generation, assert the
  fallback branches are reachable -- the installed version can only ever
  exercise one branch.
"""

from __future__ import annotations

import inspect

import pytest

rl = pytest.importorskip("rateslib")

from utils.rl_compat import (  # noqa: E402
    RATE_FIXINGS_KWARG,
    analytic_delta,
    fixed_rate,
    fly,
    instrument_kwarg,
    leg_cashflows,
    leg_npv,
    rate_fixings_kwargs,
    stirf_analytic_delta,
    stirf_pv01,
)


@pytest.fixture(scope="module")
def curve():
    return rl.Curve(
        nodes={rl.dt(2025, 1, 2): 1.0, rl.dt(2026, 1, 2): 0.96, rl.dt(2027, 1, 2): 0.92},
        id="rl_compat_probe",
        convention="act360",
        calendar="nyc",
    )


@pytest.fixture(scope="module")
def irs(curve):
    return rl.IRS(
        effective=rl.dt(2025, 3, 3),
        termination="1y",
        spec="usd_irs",
        curves=curve,
        notional=1_000_000,
        fixed_rate=4.0,
    )


@pytest.fixture(scope="module")
def stirf(curve):
    return rl.STIRFuture(
        effective=rl.dt(2025, 3, 19),
        termination=rl.dt(2025, 6, 18),
        spec="usd_stir",
        curves=curve,
        price=96.0,
        contracts=3,
    )


# --------------------------------------------------------------------------
# fixings kwarg
# --------------------------------------------------------------------------


def test_rate_fixings_kwarg_is_one_the_installed_rateslib_accepts():
    for ctor in (rl.IRS.__init__, rl.STIRFuture.__init__):
        assert RATE_FIXINGS_KWARG in inspect.signature(ctor).parameters


def test_the_other_spelling_is_genuinely_rejected():
    """Guards against a vacuous test: prove exactly one spelling is live."""
    rejected = "leg2_fixings" if RATE_FIXINGS_KWARG == "leg2_rate_fixings" else "leg2_rate_fixings"
    params = inspect.signature(rl.IRS.__init__).parameters
    assert rejected not in params
    assert not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()), (
        "rl.IRS.__init__ grew **kwargs; a wrong fixings name would now be "
        "silently swallowed instead of raising, and this module's premise changes"
    )


def test_rate_fixings_kwargs_is_empty_for_no_fixings():
    assert rate_fixings_kwargs(None) == {}


def test_instrument_constructs_with_the_resolved_kwarg(curve):
    import pandas as pd

    fixings = pd.Series([4.31, 4.32], index=[rl.dt(2025, 3, 3), rl.dt(2025, 3, 4)])
    built = rl.STIRFuture(
        effective=rl.dt(2025, 3, 3),
        termination=rl.dt(2025, 4, 1),
        spec="usd_stir1",
        roll="som",
        curves=curve,
        price=96.0,
        **rate_fixings_kwargs(fixings),
    )
    assert isinstance(built, rl.STIRFuture)


# --------------------------------------------------------------------------
# fixings actually reach a partially fixed period
#
# Naming the kwarg correctly is not sufficient on rateslib 2.7: it accepts a
# Series and then discards it for any period that is only PART fixed (the front
# monthly SR1/ZQ contract on any day but the first of its month, and every
# seasoned swap). These tests measure the VALUES that arrive, not that the
# constructor returned an object.
# --------------------------------------------------------------------------


_ELAPSED = [rl.dt(2010, 8, 2), rl.dt(2010, 8, 3), rl.dt(2010, 8, 4)]

#: 1 Aug -> 1 Sep monthly contract; a curve starting 5 Aug leaves the first
#: three observation dates reachable only through published fixings.
_FRONT_MONTH = dict(
    effective=rl.dt(2010, 8, 1),
    termination=rl.dt(2010, 9, 1),
    spec="usd_stir1",
    roll="som",
    price=99.0,
)


@pytest.fixture(scope="module")
def straddling_curves():
    """Two curves with identical forwards, one starting mid-accrual.

    Both are two-node log-linear, so log(DF) is a straight line and re-basing
    the start leaves every forward rate in the overlap unchanged.
    """
    long_curve = rl.Curve(
        nodes={rl.dt(2010, 7, 1): 1.0, rl.dt(2012, 7, 1): 0.92},
        id="rl_compat_long",
        convention="act360",
        calendar="nyc",
        modifier="MF",
    )
    short_curve = rl.Curve(
        nodes={rl.dt(2010, 8, 5): 1.0, rl.dt(2012, 7, 1): 0.92 / float(long_curve[rl.dt(2010, 8, 5)])},
        id="rl_compat_short",
        convention="act360",
        calendar="nyc",
        modifier="MF",
    )
    return long_curve, short_curve


@pytest.fixture(scope="module")
def implied_elapsed_fixings(straddling_curves):
    """The overnight rates the long curve itself implies for the elapsed days."""
    import pandas as pd

    long_curve, _ = straddling_curves
    return pd.Series(
        [float(long_curve.rate(d, "1b")) for d in _ELAPSED],
        index=pd.DatetimeIndex(_ELAPSED),
    )


def test_fixings_reproduce_the_rate_of_a_curve_that_spans_the_accrual(
    straddling_curves, implied_elapsed_fixings
):
    """The shim must carry fixing VALUES, not merely be accepted.

    Priced on the short curve with exactly the fixings the long curve implies,
    the contract must return the long curve's own number.
    """
    long_curve, short_curve = straddling_curves

    reference = float(rl.STIRFuture(**_FRONT_MONTH, curves=long_curve).rate())
    via_shim = float(
        rl.STIRFuture(
            **_FRONT_MONTH,
            curves=short_curve,
            **rate_fixings_kwargs(implied_elapsed_fixings),
        ).rate()
    )

    assert reference == pytest.approx(4.1067662, abs=1e-6)
    assert via_shim == pytest.approx(reference, abs=1e-8)


def test_without_fixings_the_same_contract_cannot_price(straddling_curves):
    """Control: the elapsed days really are unreachable from the short curve.

    Without this the equivalence test above could pass on a curve that never
    needed fixings at all.
    """
    import math

    _, short_curve = straddling_curves
    assert math.isnan(float(rl.STIRFuture(**_FRONT_MONTH, curves=short_curve).rate()))


def test_a_wrong_fixing_moves_the_rate(straddling_curves, implied_elapsed_fixings):
    """Mutation check: fixings that reached the period must be able to change it."""
    _, short_curve = straddling_curves

    good = float(
        rl.STIRFuture(
            **_FRONT_MONTH, curves=short_curve, **rate_fixings_kwargs(implied_elapsed_fixings)
        ).rate()
    )
    bumped = implied_elapsed_fixings.copy()
    bumped.iloc[0] += 100.0
    moved = float(
        rl.STIRFuture(**_FRONT_MONTH, curves=short_curve, **rate_fixings_kwargs(bumped)).rate()
    )

    assert abs(moved - good) > 1e-6


def test_the_shim_is_not_a_no_op_on_this_rateslib(straddling_curves, implied_elapsed_fixings):
    """When the shim registers a name, prove the raw Series really does fail.

    Otherwise every assertion above would hold with the shim deleted.
    """
    import math

    from utils.rl_compat import FIXINGS_TRANSPORT

    _, short_curve = straddling_curves
    if FIXINGS_TRANSPORT() != "identifier":
        pytest.skip("this rateslib carries a Series through; nothing to bypass")

    raw = float(
        rl.STIRFuture(
            **_FRONT_MONTH,
            curves=short_curve,
            **{RATE_FIXINGS_KWARG: implied_elapsed_fixings},
        ).rate()
    )
    assert math.isnan(raw), (
        "passing the Series now works, so the identifier transport is no longer "
        "needed -- re-check utils.rl_compat._resolve_fixings_transport"
    )


def test_the_same_series_is_registered_once(implied_elapsed_fixings):
    from utils.rl_compat import FIXINGS_TRANSPORT

    if FIXINGS_TRANSPORT() != "identifier":
        pytest.skip("no registration on this rateslib")

    first = rate_fixings_kwargs(implied_elapsed_fixings)[RATE_FIXINGS_KWARG]
    second = rate_fixings_kwargs(implied_elapsed_fixings.copy())[RATE_FIXINGS_KWARG]
    assert isinstance(first, str) and first == second


def test_empty_fixings_are_dropped():
    import pandas as pd

    assert rate_fixings_kwargs(pd.Series(dtype=float)) == {}


# --------------------------------------------------------------------------
# fixed_rate -- 2.7 dropped the private ``_fixed_rate`` every SDR/STIR curve
# builder read off its calibrating instruments to build the Solver's s-vector
# --------------------------------------------------------------------------


def test_fixed_rate_returns_the_struck_rate(curve):
    irs = rl.IRS(
        effective=rl.dt(2025, 3, 3), termination="5y", spec="usd_irs", curves=curve, fixed_rate=4.25
    )
    assert fixed_rate(irs) == pytest.approx(4.25)


def test_fixed_rate_of_a_stir_future_is_100_minus_price(stirf):
    assert fixed_rate(stirf) == pytest.approx(100.0 - 96.0)


def test_fixed_rate_is_not_a_no_op_on_this_rateslib(stirf):
    """Guard the shim's premise: exactly one spelling is live."""
    from utils.rl_compat import _FIXED_RATE_ATTR

    dead = "_fixed_rate" if _FIXED_RATE_ATTR == "fixed_rate" else "fixed_rate"
    assert not hasattr(stirf, dead), (
        f"{dead!r} came back on rl.STIRFuture; re-check utils.rl_compat._FIXED_RATE_ATTR"
    )


# --------------------------------------------------------------------------
# fly -- 2.7 declares ``_rate_scalar`` on Spread but not on Fly, and
# ``Solver.__init__`` reads it off every instrument
# --------------------------------------------------------------------------


@pytest.fixture
def turn_flies(curve):
    """Three consecutive 1-day OIS and the fly across them, on a fresh curve."""

    def build(rate_scalar=None):
        c = rl.Curve(
            nodes={
                rl.dt(2025, 1, 2): 1.0,
                rl.dt(2025, 4, 2): 0.99,
                rl.dt(2025, 7, 2): 0.98,
                rl.dt(2025, 10, 2): 0.97,
            },
            id="rl_compat_fly",
            convention="act360",
            calendar="nyc",
        )
        legs = [
            rl.IRS(effective=d, termination="1d", spec="usd_irs_lt_2y", curves=c)
            for d in (rl.dt(2025, 4, 2), rl.dt(2025, 7, 2), rl.dt(2025, 10, 2))
        ]
        f = fly(*legs)
        if rate_scalar is not None:
            f._rate_scalar = rate_scalar
        return c, legs, f

    return build


def test_fly_is_accepted_by_a_solver(turn_flies):
    c, legs, f = turn_flies()
    solver = rl.Solver(
        curves=[c],
        instruments=legs + [f],
        s=[3.9, 4.0, 4.1, 0.0],
        weights=[1.0, 1.0, 1.0, 1e-8],
        id="rl_compat_fly_solver",
    )
    assert solver.result["status"] == "SUCCESS"


def test_raw_rl_fly_is_rejected_by_a_solver_on_this_rateslib(turn_flies):
    """Without this the test above would pass with the shim deleted."""
    from utils.rl_compat import _FLY_DECLARES_RATE_SCALAR

    if _FLY_DECLARES_RATE_SCALAR:
        pytest.skip("this rateslib declares Fly._rate_scalar; nothing to supply")

    c, legs, _ = turn_flies()
    with pytest.raises(AttributeError, match="_rate_scalar"):
        rl.Solver(
            curves=[c],
            instruments=legs + [rl.Fly(*legs)],
            s=[3.9, 4.0, 4.1, 0.0],
            id="rl_compat_fly_raw",
        )


def test_fly_rate_scalar_does_not_move_the_solved_curve(turn_flies):
    """The scalar drives Solver risk reporting, not calibration.

    Pins the claim ``utils.rl_compat.fly`` makes when it borrows Spread's value:
    if the choice could move a curve, borrowing would need more justification
    than a shared ``* 100`` in ``rate()``.
    """
    solved = {}
    for scalar in (100.0, 1.0):
        c, legs, f = turn_flies(rate_scalar=scalar)
        rl.Solver(
            curves=[c],
            instruments=legs + [f],
            s=[3.9, 4.0, 4.1, 0.0],
            weights=[1.0, 1.0, 1.0, 1e-8],
            id=f"rl_compat_fly_scalar_{scalar}",
        )
        solved[scalar] = [float(v) for v in c.nodes.nodes.values()]

    assert solved[100.0] == pytest.approx(solved[1.0], abs=1e-12)


def test_fly_rate_is_the_butterfly_of_its_legs(turn_flies):
    c, legs, f = turn_flies()
    rates = [float(leg.rate(curves=c).real) for leg in legs]
    assert float(f.rate(curves=c).real) == pytest.approx(
        (-rates[0] + 2 * rates[1] - rates[2]) * 100.0
    )


# --------------------------------------------------------------------------
# analytic_delta
# --------------------------------------------------------------------------


def test_analytic_delta_matches_direct_call(irs, curve):
    assert float(analytic_delta(irs, curve).real) == pytest.approx(
        float(irs.analytic_delta(curves=curve).real)
        if "curves" in inspect.signature(rl.IRS.analytic_delta).parameters
        else float(irs.analytic_delta(curve).real)
    )


def test_analytic_delta_without_a_curve_uses_the_instruments_own(stirf):
    assert float(analytic_delta(stirf).real) == pytest.approx(float(stirf.analytic_delta().real))


def test_analytic_delta_positional_fallback_branch():
    """The <=2.6 shape: no named ``curves``, curve arrives positionally."""

    class _Legacy:
        def analytic_delta(self, curve=None, **kwargs):
            return curve

    import utils.rl_compat as compat

    saved = compat._ANALYTIC_DELTA_TAKES_CURVES
    try:
        compat._ANALYTIC_DELTA_TAKES_CURVES = False
        assert compat.analytic_delta(_Legacy(), "SENTINEL") == "SENTINEL"
    finally:
        compat._ANALYTIC_DELTA_TAKES_CURVES = saved


# --------------------------------------------------------------------------
# instrument_kwarg
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# leg accessors (keyword-only from 2.7)
# --------------------------------------------------------------------------


def test_leg_cashflows_returns_the_frame_and_the_positional_form_is_rejected(irs, curve):
    """Both halves, so the first assertion cannot be vacuous."""
    frame = leg_cashflows(irs.leg1, curve)
    assert len(frame) > 0
    assert {"Payment", "DCF"} <= set(frame.columns)

    takes_positional = True
    try:
        irs.leg1.cashflows(curve)
    except TypeError:
        takes_positional = False
    # exactly one call shape is live on the installed rateslib; if BOTH worked
    # the shim would be untested rather than tested
    assert not takes_positional or "curve" in inspect.signature(
        rl.legs.FixedLeg.cashflows).parameters


def test_leg_npv_defaults_the_discount_curve_to_the_forecasting_one(irs, curve):
    """``leg.npv(c, c)`` was the pre-2.7 spelling; ``disc_curve=None`` means it."""
    implicit = complex(leg_npv(irs.leg1, curve)).real
    explicit = complex(leg_npv(irs.leg1, curve, disc_curve=curve)).real
    assert implicit == explicit
    assert implicit != 0.0


def test_leg_npv_actually_uses_the_discount_curve_it_is_given(irs, curve):
    """Otherwise the disc_curve argument could be ignored and nothing would say so."""
    other = rl.Curve(
        nodes={rl.dt(2025, 1, 2): 1.0, rl.dt(2027, 1, 2): 0.70},
        id="rl_compat_probe_disc", convention="act360", calendar="nyc",
    )
    assert complex(leg_npv(irs.leg1, curve, disc_curve=other)).real != pytest.approx(
        complex(leg_npv(irs.leg1, curve)).real
    )


def test_instrument_kwarg_reads_notional(irs):
    assert float(instrument_kwarg(irs, "notional")) == pytest.approx(1_000_000.0)


def test_instrument_kwarg_reads_contracts(stirf):
    assert int(instrument_kwarg(stirf, "contracts")) == 3


def test_instrument_kwarg_reads_schedule_derived_dates(irs):
    assert instrument_kwarg(irs, "effective") == rl.dt(2025, 3, 3)
    assert instrument_kwarg(irs, "termination") == rl.dt(2026, 3, 3)


def test_instrument_kwarg_reads_fixed_rate(irs):
    assert float(instrument_kwarg(irs, "fixed_rate")) == pytest.approx(4.0)


def test_instrument_kwarg_flat_dict_fallback():
    """The <=2.6 shape: a flat ``kwargs`` dict on ``__dict__``."""

    class _Legacy:
        def __init__(self):
            self.kwargs = {"notional": 5_000_000, "termination": "5y"}

    legacy = _Legacy()
    assert instrument_kwarg(legacy, "notional") == 5_000_000
    assert instrument_kwarg(legacy, "termination") == "5y"


def test_instrument_kwarg_default_and_raise():
    class _Empty:
        pass

    assert instrument_kwarg(_Empty(), "notional", default=None) is None
    with pytest.raises(KeyError):
        instrument_kwarg(_Empty(), "notional")


# --------------------------------------------------------------------------
# stirf_pv01
# --------------------------------------------------------------------------


def test_stirf_pv01_is_25_per_contract(stirf):
    # A SR3 contract is $25 per basis point; this future carries 3.
    assert stirf_pv01(stirf) == pytest.approx(75.0)


def test_stirf_analytic_delta_is_discount_independent():
    """The premise of the placeholder-curve fallback in ``stirf_analytic_delta``.

    A STIR future's analytic delta is the exchange tick value and carries no
    discounting. If a future rateslib ever made it discount-dependent, handing
    it an arbitrary placeholder curve would start returning wrong numbers -- so
    pin the invariant rather than trusting it.
    """
    flat = rl.Curve(
        nodes={rl.dt(2026, 1, 1): 1.0, rl.dt(2030, 1, 1): 1.0},
        id="dc_flat", convention="act360", calendar="nyc",
    )
    steep = rl.Curve(
        nodes={rl.dt(2026, 1, 1): 1.0, rl.dt(2027, 1, 1): 0.90, rl.dt(2030, 1, 1): 0.55},
        id="dc_steep", convention="act360", calendar="nyc",
    )

    def sr3(dc):
        return float(rl.STIRFuture(
            effective=rl.dt(2026, 6, 17), termination=rl.dt(2026, 9, 16),
            spec="usd_stir", curves=dc, price=96.0, contracts=1,
        ).analytic_delta().real)

    def zq(dc):
        return float(rl.STIRFuture(
            effective=rl.dt(2026, 7, 1), termination=rl.dt(2026, 8, 3),
            spec="usd_stir1", roll="som", curves=dc, price=96.1, contracts=1,
        ).analytic_delta().real)

    assert sr3(flat) == pytest.approx(sr3(steep))
    assert sr3(flat) == pytest.approx(-25.0)  # $25/bp, SR3
    assert zq(flat) == pytest.approx(zq(steep))
    assert zq(flat) == pytest.approx(-41.67, abs=0.01)  # $41.67/bp, ZQ


def test_stirf_analytic_delta_survives_an_unresolvable_curve_name(curve):
    """The production shape: a pricer holding only a curve id, with no Solver."""
    by_name = rl.STIRFuture(
        effective=rl.dt(2026, 6, 17), termination=rl.dt(2026, 9, 16),
        spec="usd_stir", curves="USD-SOFR-1D", price=96.0, contracts=2,
    )
    # Confirm the bare call really is the thing that breaks, so the shim is not
    # papering over nothing.
    with pytest.raises(ValueError, match="disc_curve"):
        by_name.analytic_delta()

    assert float(stirf_analytic_delta(by_name).real) == pytest.approx(-50.0)


def test_stirf_analytic_delta_does_not_swallow_other_errors():
    class _Boom:
        def analytic_delta(self, **kwargs):
            raise ValueError("schedule is degenerate")

    with pytest.raises(ValueError, match="degenerate"):
        stirf_analytic_delta(_Boom())


def test_stirf_pv01_prefers_a_legacy_pv01_property():
    class _Legacy:
        pv01 = -42.0

        def analytic_delta(self, **kwargs):  # pragma: no cover - must not be reached
            raise AssertionError("legacy .pv01 should have been used")

    assert stirf_pv01(_Legacy()) == pytest.approx(42.0)
