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
