r"""Hermetic tests for the Citi Velocity cross-currency basis layer.

No Excel, no network, no market data. The fetch path runs against
:class:`MDP.CitiVelocityExcel.testing.FakeExcelApp`; everything numeric runs on a
synthetic EUR/USD market invented in this file - two upward-sloping par OIS grids
and a plausible basis strip. Nothing here says anything about Citi's numbers, and
in particular neither the sign nor the leg convention of Velocity's
``BASIS_SPREAD`` has been checked against a live quote. What it does check is
that two independently written implementations of the same swap - rateslib's
``XCS`` and a QuantLib swap assembled from ``OvernightLeg`` + ``SimpleCashFlow``
because QuantLib 1.41 has no cross-currency instrument - agree, and that each
reprices its own calibrating quotes.

Two kinds of pairing keep the numbers above from being self-congratulation:

MUTATION CHECKS
    ``test_payment_lag_mutation_moves_the_fair_basis`` reprices the QuantLib leg
    with its payment lag forced from 2 to 0 and asserts the fair basis moves by
    0.06-0.08 bp - roughly 6,000x the cross-library residual the agreement test
    tolerates. Without that, "the two libraries agree to 1e-5 bp" would be
    equally consistent with both of them being insensitive to the schedule.
    ``test_iso_reduction_is_what_hid_the_ibor_leg`` shows why the IBOR guard sits
    where it does by demonstrating that the same guard one line later cannot
    fire.

CONTROLS
    The reprice tests are paired with ``*_have_teeth`` variants that shift the
    quoted strip by 5 bp and reprice off the SAME solved curve, asserting the
    errors move to -5 bp. A reprice function that returned zeros, or that read
    the model instead of the quote, would pass the tolerance test and fail this.

Measured on this fixture, for the record: rateslib repricing 4.4e-08 bp,
QuantLib 2.0e-12 bp, cross-library (like for like) 1.1e-05 bp, MTM effect
0.0007 bp at 1Y rising to 0.0264 bp at 30Y.
"""

from __future__ import annotations

import datetime
import math
import warnings
from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd
import pytest
import QuantLib as ql
import rateslib as rl

from MDP.CitiVelocityExcel import tags as cv_tags
from MDP.CitiVelocityExcel.catalog import sort_tenors
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import CatalogError, UnknownTagError
from MDP.CitiVelocityExcel.testing import FakeExcelApp, FakeVelocityData
from MDP.CitiVelocityExcel.xccy.basis_data import (
    XCCY_TENORS,
    XccyBasisCurve,
    assert_ois_pair,
    basis_from_quotes,
    conventions_for_currency,
    default_spread_ccy,
    fetch_xccy_basis,
    iso_currency,
    ois_index_for_currency,
)
from MDP.CitiVelocityExcel.xccy.ql_xccy import (
    bootstrap_ql_xccy_discount_curve,
    build_ql_xccy_swap,
    ql_curve_from_rl,
    ql_xccy_reprice_errors_bp,
)
from MDP.CitiVelocityExcel.xccy.rl_xccy import (
    RL_XCS_SPECS,
    build_rl_xcs,
    rl_xccy_reprice_errors_bp,
    rl_xcs_kwargs,
    solve_rl_collateral_curve,
)

REF_DATE = datetime.datetime(2026, 8, 5)
FX_EURUSD = 1.08  # USD per EUR
NOTIONAL = 100_000_000.0

#: Calibration axis. Deliberately shorter than :data:`XCCY_TENORS`: the sub-1Y
#: points roll inside the first coupon period and are not what shapes the curve.
AXIS = ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y")

#: A plausible EUR/USD basis strip, in bp on the EUR leg. Invented.
BASIS_BP: Dict[str, float] = {
    "1Y": -8.0, "2Y": -11.0, "3Y": -13.5, "5Y": -16.0, "7Y": -17.5,
    "10Y": -19.0, "15Y": -21.0, "20Y": -23.0, "30Y": -26.5,
}
#: Upward-sloping synthetic par OIS, in percent.
USD_PAR = {"1Y": 3.90, "2Y": 3.80, "3Y": 3.78, "5Y": 3.85, "7Y": 3.95,
           "10Y": 4.05, "15Y": 4.20, "20Y": 4.25, "30Y": 4.20}
EUR_PAR = {"1Y": 2.05, "2Y": 2.00, "3Y": 2.02, "5Y": 2.15, "7Y": 2.28,
           "10Y": 2.42, "15Y": 2.58, "20Y": 2.62, "30Y": 2.55}

REPORT_TENORS = ("1Y", "5Y", "10Y", "30Y")

# -- stated tolerances, each an order of magnitude above what was measured ----

#: rateslib repricing its own calibrating quotes. Measured 4.4e-08 bp.
RL_REPRICE_TOL_BP = 1e-6
#: The QuantLib sequential bootstrap repricing its pillars. Measured 2.0e-12 bp.
QL_REPRICE_TOL_BP = 1e-9
#: QuantLib vs rateslib on the SAME collateral curve, both constant-notional.
#: This is pure construction difference - schedules, day counts, roll dates -
#: and nothing else. Measured 1.1e-05 bp.
CROSS_LIBRARY_TOL_BP = 1e-3
#: How far the payment-lag mutation must move the fair basis to prove the
#: cross-library agreement is evidence. Measured 0.061-0.081 bp.
MUTATION_FLOOR_BP = 0.05
#: The shifted-strip control. Reprice errors must move to exactly this.
CONTROL_SHIFT_BP = 5.0


# ------------------------------------------------------------------ #
#                              fixtures                              #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class _Market:
    """Everything the numeric tests share, built once per module.

    Building it twice would double the module's runtime for no extra coverage:
    two rateslib solves, one collateral-curve solve, three daily-sampled
    QuantLib curves and a nine-pillar Brent bootstrap.
    """

    basis: XccyBasisCurve
    eur_curve: Any
    usd_curve: Any
    eur_solver: Any
    usd_solver: Any
    rl_curves: Any            # RLXccyCurves, calibrated with mtm=True
    ql_handle: Any            # the bootstrapped EUR-under-USD discount curve
    ql_diagnostics: pd.DataFrame
    estr: Any
    sofr: Any
    h_eur: Any
    h_usd: Any
    h_coll: Any               # the rateslib-solved collateral curve, as QuantLib
    joint: Any
    d0: Any


def _build_ois_curve(*, citi_index: str, par: Dict[str, float], curve_id: str):
    """Solve one domestic OIS curve from a synthetic par grid."""
    conv = conventions_for_currency(citi_index.split("_")[0], ois_index=citi_index)
    cal = conv.rl_calendar_object()
    nodes = {REF_DATE: 1.0}
    for tenor in par:
        nodes[rl.add_tenor(REF_DATE, tenor, "MF", cal)] = 1.0
    curve = rl.Curve(
        nodes=nodes, id=curve_id, convention=conv.convention, calendar=cal,
        currency=conv.currency.lower(), modifier="MF",
    )
    solver = rl.Solver(
        curves=[curve],
        instruments=[rl.IRS(REF_DATE, t, spec=conv.rl_spec, curves=curve) for t in par],
        s=list(par.values()),
        instrument_labels=list(par),
        id=curve_id,
    )
    assert str(solver.result.get("status", "")).upper() == "SUCCESS"
    return curve, solver


@pytest.fixture(scope="module")
def market() -> _Market:
    """The synthetic EUR/USD market, solved both ways.

    ``ql.Settings.instance().evaluationDate`` is process-global state that the
    QuantLib builders set and never restore, so it is saved and put back here -
    otherwise this module would silently move the evaluation date under every
    QuantLib test that runs after it in the same session.
    """
    saved_eval_date = ql.Settings.instance().evaluationDate
    try:
        eur_curve, eur_solver = _build_ois_curve(
            citi_index="EUR_EUROSTR", par=EUR_PAR, curve_id="eureur"
        )
        usd_curve, usd_solver = _build_ois_curve(
            citi_index="USD_SOFR", par=USD_PAR, curve_id="usdusd"
        )
        basis = basis_from_quotes(
            quotes={t: BASIS_BP[t] for t in AXIS},
            ccy1="EUR", ccy2="USD", as_of=REF_DATE.date(),
        )
        rl_curves = solve_rl_collateral_curve(
            basis=basis, domestic_curve=eur_curve, foreign_curve=usd_curve,
            fx_rate=FX_EURUSD, ref_date=REF_DATE,
            pre_solvers=[eur_solver, usd_solver], notional=NOTIONAL, mtm=True,
        )

        ql.Settings.instance().evaluationDate = ql.Date(
            REF_DATE.day, REF_DATE.month, REF_DATE.year
        )
        tgt = ql.TARGET()
        nyc = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        joint = ql.JointCalendar(tgt, nyc)
        h_eur = ql.YieldTermStructureHandle(
            ql_curve_from_rl(eur_curve, ref_date=REF_DATE, calendar=tgt)
        )
        h_usd = ql.YieldTermStructureHandle(
            ql_curve_from_rl(usd_curve, ref_date=REF_DATE, calendar=nyc)
        )
        h_coll = ql.YieldTermStructureHandle(
            ql_curve_from_rl(rl_curves.collateral_curve, ref_date=REF_DATE, calendar=tgt)
        )
        estr = ql.Estr(h_eur)
        sofr = ql.Sofr(h_usd)

        ql_handle, ql_diagnostics = bootstrap_ql_xccy_discount_curve(
            basis=basis, base_index=estr, quote_index=sofr,
            base_discount=h_eur, quote_discount=h_usd, fx_spot=FX_EURUSD,
            ref_date=REF_DATE.date(), notional=NOTIONAL, calendar=joint,
            return_diagnostics=True,
        )
        yield _Market(
            basis=basis, eur_curve=eur_curve, usd_curve=usd_curve,
            eur_solver=eur_solver, usd_solver=usd_solver, rl_curves=rl_curves,
            ql_handle=ql_handle, ql_diagnostics=ql_diagnostics,
            estr=estr, sofr=sofr, h_eur=h_eur, h_usd=h_usd, h_coll=h_coll,
            joint=joint, d0=ql.Date(REF_DATE.day, REF_DATE.month, REF_DATE.year),
        )
    finally:
        ql.Settings.instance().evaluationDate = saved_eval_date


@pytest.fixture(scope="module")
def fair_basis(market: _Market) -> pd.DataFrame:
    """``quote | rl_mtm | rl_nomtm | ql`` in bp at :data:`REPORT_TENORS`.

    ``ql`` is constant-notional because the QuantLib side does not model the MTM
    notional reset (building an FX-forward-dependent notional schedule by hand is
    a large surface for silent error). So the LIKE-FOR-LIKE column against it is
    ``rl_nomtm``, and ``rl_mtm - rl_nomtm`` is the convention's own worth. All
    four columns are priced off the SAME rateslib-solved collateral curve, so
    ``ql - rl_nomtm`` is construction difference and nothing else.
    """
    eff = market.joint.advance(market.d0, 2, ql.Days)
    rows = []
    for tenor in REPORT_TENORS:
        quote = market.basis.at(tenor)
        priced = {}
        for label, mtm in (("rl_mtm", True), ("rl_nomtm", False)):
            priced[label] = float(
                build_rl_xcs(
                    basis=market.basis, tenor=tenor,
                    domestic_curve=market.eur_curve, foreign_curve=market.usd_curve,
                    fx_forwards=market.rl_curves.fx_forwards,
                    collateral_curve=market.rl_curves.collateral_curve,
                    notional=NOTIONAL, mtm=mtm, float_spread=0.0,
                ).rate(solver=market.rl_curves.solver)
            )
        priced["ql"] = build_ql_xccy_swap(
            notional=NOTIONAL, fx_spot=FX_EURUSD, start=eff,
            maturity=eff + ql.Period(tenor),  # unadjusted; the schedule adjusts it
            base_index=market.estr, quote_index=market.sofr,
            base_discount=market.h_coll, quote_discount=market.h_usd,
            spread_bp=quote, base_ccy="EUR", quote_ccy="USD", spread_ccy="EUR",
            calendar=market.joint,
        ).fair_basis_spread
        rows.append({"tenor": tenor, "quote": quote, **priced})
    return pd.DataFrame(rows).set_index("tenor")


def _shifted(basis: XccyBasisCurve, bp: float) -> XccyBasisCurve:
    """The same strip with every quote moved by ``bp``, for the reprice controls."""
    return basis_from_quotes(
        quotes={t: basis.at(t) + bp for t in basis.tenors()},
        ccy1=basis.base_ccy, ccy2=basis.quote_ccy, as_of=basis.as_of,
    )


# ------------------------------------------------------------------ #
#              the strip: ordering, units, and validate()            #
# ------------------------------------------------------------------ #


def test_tenors_are_ordered_by_maturity_not_lexically():
    """``18M`` sits between ``1Y`` and ``2Y``, which no string sort will do.

    The axis is a mixed-unit token vocabulary, so a lexical sort puts ``10Y``
    first and ``9M`` last - i.e. it reverses the front of the curve. Anything
    that interpolates or bootstraps off ``spreads.index`` in order would then be
    marching backwards through time.
    """
    scrambled = {"2Y": -11.0, "10Y": -19.0, "18M": -9.5, "9M": -7.0, "1Y": -8.0}
    curve = basis_from_quotes(quotes=scrambled, ccy1="EUR", ccy2="USD")

    assert curve.tenors() == ["9M", "1Y", "18M", "2Y", "10Y"]
    assert list(curve.spreads.index) == ["9M", "1Y", "18M", "2Y", "10Y"]
    assert sorted(scrambled) == ["10Y", "18M", "1Y", "2Y", "9M"]  # the naive order
    assert curve.years().is_monotonic_increasing
    assert list(curve.to_frame().index) == curve.tenors()


def test_a_missing_tenor_names_what_is_present():
    curve = basis_from_quotes(quotes={"1Y": -8.0, "5Y": -16.0}, ccy1="EUR", ccy2="USD")
    with pytest.raises(CatalogError) as excinfo:
        curve.at("7Y")
    assert "1Y, 5Y" in str(excinfo.value)


def test_the_strip_is_in_basis_points():
    """``-19.0`` means -19 bp, not -1900% and not -0.0019.

    Three independent statements of the same contract: the quote comes back
    verbatim; ``scale=1e4`` is what a decimal source needs to reach the same
    strip; and a strip 1,000x too large is refused with the knob that fixes it.
    The load-bearing consequence is elsewhere - ``build_rl_xcs`` hands
    ``basis.at(tenor)`` straight to rateslib's ``float_spread``, which is in bp,
    so the repricing tests below would fail by a factor of 1e4 if this changed.
    """
    bp = basis_from_quotes(quotes={"1Y": -8.0, "10Y": -19.0}, ccy1="EUR", ccy2="USD")
    assert bp.at("10Y") == pytest.approx(-19.0)
    assert bp.spreads.name.endswith("_basis_bp")

    from_decimals = basis_from_quotes(
        quotes={"1Y": -8.0e-4, "10Y": -19.0e-4}, ccy1="EUR", ccy2="USD", scale=1e4
    )
    assert from_decimals.at("10Y") == pytest.approx(bp.at("10Y"))

    flipped = basis_from_quotes(
        quotes={"1Y": -8.0, "10Y": -19.0}, ccy1="EUR", ccy2="USD", sign=-1
    )
    assert flipped.at("10Y") == pytest.approx(+19.0)

    with pytest.raises(ValueError) as excinfo:
        basis_from_quotes(quotes={"1Y": -8000.0, "10Y": -19000.0}, ccy1="EUR", ccy2="USD")
    message = str(excinfo.value)
    assert "not a basis spread in basis points" in message
    assert "scale=1e4" in message


def test_validate_refuses_an_empty_strip():
    """"Nothing came back" must never be returned as a curve.

    The repo has a recorded incident where a transiently failing curve build
    published an all-NULL risk column as "success", so the empty case raises with
    the pair and the likely cause named rather than yielding a length-zero
    object that reads as a quiet market.
    """
    with pytest.raises(ValueError, match="at least one tenor"):
        basis_from_quotes(quotes={}, ccy1="EUR", ccy2="USD")

    empty = XccyBasisCurve(
        pair="EUR/USD", base_ccy="EUR", quote_ccy="USD", forward="SPOT",
        leg="SPREAD_LEG", spreads=pd.Series(dtype="float64"), as_of=None,
        requested_tenors=tuple(AXIS),
    )
    with pytest.raises(ValueError) as excinfo:
        empty.validate()
    assert "EMPTY" in str(excinfo.value)
    assert f"{len(AXIS)} requested" in str(excinfo.value)


def test_validate_refuses_a_ragged_strip():
    """A strip short of what was asked for is a defect, not a shorter curve.

    Calibrating on whatever turned up would silently change the curve's shape
    between runs, so the missing tenors are named and the caller is told to
    narrow ``tenors=`` deliberately if that is what they meant.
    """
    ragged = basis_from_quotes(
        quotes={"1Y": -8.0, "5Y": -16.0}, ccy1="EUR", ccy2="USD",
        requested_tenors=["1Y", "2Y", "5Y"], validate=False,
    )
    assert len(ragged) == 2  # it was built, just not blessed
    with pytest.raises(ValueError) as excinfo:
        ragged.validate()
    message = str(excinfo.value)
    assert "RAGGED" in message
    assert "1 of 3 requested tenors" in message
    assert "2Y" in message


def test_validate_refuses_a_non_finite_point():
    with pytest.raises(ValueError, match="non-finite basis at 5Y"):
        basis_from_quotes(quotes={"1Y": -8.0, "5Y": float("nan")}, ccy1="EUR", ccy2="USD")


# ------------------------------------------------------------------ #
#                       the fetch, on the fake                       #
# ------------------------------------------------------------------ #


def test_fetch_batches_every_tenor_into_one_cvtshist_call():
    """Nine tenors, one ``CVTSHIST``.

    Each ``CVTSHIST`` is a round trip through the add-in's async queue, so a
    per-tenor loop turns one ~seconds-long call into nine and multiplies the
    surface for the overlap crash by the same factor.
    """
    index = pd.bdate_range(end=pd.Timestamp("2026-08-05"), periods=40)
    grid = cv_tags.xccy_basis_grid("EUR", "USD", tenors=list(AXIS))
    served = {
        tag: pd.Series(
            [BASIS_BP[tenor] + 0.05 * math.sin(i / 3.0) for i in range(len(index))],
            index=index, dtype="float64",
        )
        for tenor, tag in grid.items()
    }
    app = FakeExcelApp(FakeVelocityData(series=served), pending_reads=1)
    client = CitiVelocityExcelClient(app=app, drain_seconds=0.0)
    try:
        basis = fetch_xccy_basis(
            client=client, ccy1="EUR", ccy2="USD", tenors=list(AXIS),
            as_of=datetime.date(2026, 8, 5),
        )
    finally:
        client.close()

    assert len(app.formulas_for("CVTSHIST")) == 1, "one call per tenor, not one call"
    assert basis.tenors() == sort_tenors(list(AXIS))
    assert basis.spread_ccy == "EUR"  # the non-USD leg carries the basis
    assert basis.observed["5Y"] == datetime.date(2026, 8, 5)
    assert basis.tags["5Y"] == grid["5Y"]
    assert basis.at("5Y") == pytest.approx(served[grid["5Y"]].iloc[-1])


def test_the_default_tenor_axis_is_a_constant_because_the_catalog_is_empty():
    """``catalog.options()`` cannot supply this family's tenor axis.

    The Function Builder walk was depth-capped at ``<ccy1>.<ccy2>.<fwd>``, so the
    level below it returns ``[]`` and a grid built from the catalog would be
    empty - which is why :data:`XCCY_TENORS` exists and why ``tenors=None`` means
    something.
    """
    from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog

    catalog = CitiVeloCatalog.default()
    assert catalog.options("RATES.XCCY_OIS_SWAP.EUR.USD.SPOT") == []
    assert len(XCCY_TENORS) == 21
    assert sort_tenors(list(XCCY_TENORS)) == list(XCCY_TENORS)


# ------------------------------------------------------------------ #
#                    each library reprices its own                   #
# ------------------------------------------------------------------ #


def test_rateslib_collateral_curve_reprices_every_quote(market: _Market):
    """The solved EUR-under-USD-collateral curve returns its own inputs.

    Measured worst error 4.4e-08 bp against a stated tolerance of 1e-06 bp, which
    is two orders inside the 0.25 bp tick a cross-currency basis trades on.
    ``solve_rl_collateral_curve`` already refuses to return a curve missing a
    quote by more than 1e-04 bp, so this asserts a strictly tighter bound than
    production enforces, on the axis production calibrated.
    """
    errors = rl_xccy_reprice_errors_bp(market.rl_curves, market.basis)
    assert list(errors.index) == market.basis.tenors()
    worst = float(errors.abs().max())
    assert worst < RL_REPRICE_TOL_BP, f"worst rateslib reprice error {worst:.3e} bp"
    assert market.rl_curves.discount_ccy == "EUR"
    assert market.rl_curves.collateral_ccy == "USD"
    assert market.rl_curves.curve_id == "eurusd"


def test_rateslib_reprice_errors_have_teeth(market: _Market):
    """CONTROL for the test above, on an input whose answer is known.

    Reprice a strip shifted by +5 bp off the UNCHANGED curve. Every error must
    become -5 bp, because the model rate did not move and the quote did. A
    reprice function that returned zeros, or that compared the model against
    itself, passes the tolerance test above and fails here.
    """
    errors = rl_xccy_reprice_errors_bp(market.rl_curves, _shifted(market.basis, CONTROL_SHIFT_BP))
    assert len(errors) == len(AXIS)
    for tenor, err in errors.items():
        assert err == pytest.approx(-CONTROL_SHIFT_BP, abs=1e-5), tenor


def test_quantlib_bootstrap_reprices_every_quote(market: _Market):
    """The hand-rolled sequential bootstrap is exact by construction, and is checked anyway.

    QuantLib 1.41 has no cross-currency rate helper, so each pillar is a
    one-dimensional Brent solve with the earlier pillars frozen - which makes an
    exact fit structural rather than fortunate. Measured worst error 2.0e-12 bp
    against a stated tolerance of 1e-09 bp. The pillar sits at the LAST PAYMENT
    date rather than at maturity, so the payment-lagged final coupon is never
    extrapolated during the solve.
    """
    errors = ql_xccy_reprice_errors_bp(
        basis=market.basis, handle=market.ql_handle,
        base_index=market.estr, quote_index=market.sofr,
        base_discount=market.h_eur, quote_discount=market.h_usd,
        fx_spot=FX_EURUSD, ref_date=REF_DATE.date(), notional=NOTIONAL,
        calendar=market.joint,
    )
    worst = float(errors.abs().max())
    assert worst < QL_REPRICE_TOL_BP, f"worst QuantLib reprice error {worst:.3e} bp"

    frame = market.ql_diagnostics
    assert list(frame.index) == market.basis.tenors()
    assert frame["pillar"].is_monotonic_increasing
    # Every pillar is strictly past its own maturity, i.e. at the last PAYMENT.
    eff = market.joint.advance(market.d0, 2, ql.Days)
    for tenor, row in frame.iterrows():
        maturity = market.joint.adjust(eff + ql.Period(tenor), ql.ModifiedFollowing)
        assert row["pillar"] > datetime.date(
            maturity.year(), maturity.month(), maturity.dayOfMonth()
        ), tenor


def test_quantlib_reprice_errors_have_teeth(market: _Market):
    """CONTROL for the QuantLib bootstrap, same construction as the rateslib one."""
    errors = ql_xccy_reprice_errors_bp(
        basis=_shifted(market.basis, CONTROL_SHIFT_BP), handle=market.ql_handle,
        base_index=market.estr, quote_index=market.sofr,
        base_discount=market.h_eur, quote_discount=market.h_usd,
        fx_spot=FX_EURUSD, ref_date=REF_DATE.date(), notional=NOTIONAL,
        calendar=market.joint,
    )
    for tenor, err in errors.items():
        assert err == pytest.approx(-CONTROL_SHIFT_BP, abs=1e-5), tenor


# ------------------------------------------------------------------ #
#                    the two libraries, like for like                #
# ------------------------------------------------------------------ #


def test_the_two_libraries_agree_on_the_fair_basis(market: _Market, fair_basis: pd.DataFrame):
    """rateslib and QuantLib price the same swap to 1.1e-05 bp, LIKE FOR LIKE.

    Like for like means three things, all of which have to be said or the number
    is not interpretable: both sides discount off the SAME rateslib-solved
    collateral curve (so this is not a second calibration); both are
    CONSTANT-NOTIONAL (``mtm=False`` on the rateslib side, because the QuantLib
    swap does not model the notional reset); and both take the spread on the EUR
    leg. What is left is construction difference - schedule generation, day
    counts, roll and payment dates - and it is 1.1e-05 bp against a stated
    tolerance of 1e-03 bp.

    On its own this number proves nothing; see the payment-lag mutation next.
    """
    gaps = (fair_basis["ql"] - fair_basis["rl_nomtm"]).abs()
    worst = float(gaps.max())
    assert worst < CROSS_LIBRARY_TOL_BP, f"worst |ql - rl_nomtm| = {worst:.3e} bp"

    # And the MTM-calibrated instrument returns its own quote, as it must.
    for tenor in REPORT_TENORS:
        assert fair_basis.loc[tenor, "rl_mtm"] == pytest.approx(
            fair_basis.loc[tenor, "quote"], abs=RL_REPRICE_TOL_BP
        )


def test_payment_lag_mutation_moves_the_fair_basis(market: _Market, fair_basis: pd.DataFrame):
    """MUTATION CHECK for the cross-library agreement.

    Two implementations agreeing to 1e-05 bp is equally consistent with both of
    them being blind to the schedule. So rebuild the QuantLib leg with its coupon
    payment lag forced from the market-standard 2 business days to 0 - a
    deliberately wrong but entirely plausible construction - and require that the
    fair basis move.

    It moves by +0.081 bp at 1Y falling to +0.061 bp at 30Y: roughly 6,000x the
    residual the agreement test tolerates. The agreement is therefore a statement
    about the construction, not an artefact of both sides ignoring it.
    """
    eff = market.joint.advance(market.d0, 2, ql.Days)
    moves = {}
    for tenor in REPORT_TENORS:
        broken = build_ql_xccy_swap(
            notional=NOTIONAL, fx_spot=FX_EURUSD, start=eff,
            maturity=eff + ql.Period(tenor),
            base_index=market.estr, quote_index=market.sofr,
            base_discount=market.h_coll, quote_discount=market.h_usd,
            spread_bp=market.basis.at(tenor), base_ccy="EUR", quote_ccy="USD",
            spread_ccy="EUR", calendar=market.joint,
            payment_lag=0,  # the mutation
        ).fair_basis_spread
        moves[tenor] = broken - float(fair_basis.loc[tenor, "ql"])

    assert all(v > 0.0 for v in moves.values()), moves
    smallest = min(abs(v) for v in moves.values())
    assert smallest > MUTATION_FLOOR_BP, f"payment-lag mutation only moved {moves}"
    assert max(abs(v) for v in moves.values()) < 0.10, moves

    residual = float((fair_basis["ql"] - fair_basis["rl_nomtm"]).abs().max())
    assert smallest > 1000.0 * residual, (
        f"the mutation ({smallest:.4f} bp) is not decisively larger than the "
        f"cross-library residual ({residual:.3e} bp)"
    )


def test_the_mtm_notional_reset_is_worth_something(fair_basis: pd.DataFrame):
    """``mtm=True`` and ``mtm=False`` are different trades, and the gap is the QuantLib gap.

    A traded cross-currency basis swap resets the collateral-currency leg's
    notional against the FX forward every period. rateslib models it; the
    QuantLib side deliberately does not, because hand-building an
    FX-forward-dependent notional schedule with its compensating flows is a large
    surface for silent error.

    Measured, in bp of fair basis::

        tenor   rl_mtm    rl_nomtm   mtm effect
        1Y     -8.0000    -7.9993      -0.0007
        5Y    -16.0000   -15.9952      -0.0048
        10Y   -19.0000   -18.9904      -0.0096
        30Y   -26.5000   -26.4736      -0.0264

    Small, monotone in tenor, and 2,400x the cross-library construction residual
    at 30Y - so it is a convention difference, not noise. The second assertion is
    the point: ``ql - rl_mtm`` is the MTM effect and nothing else, which is what
    licenses reading the QuantLib number as a cross-check on the rateslib one.
    """
    effect = fair_basis["rl_mtm"] - fair_basis["rl_nomtm"]
    assert (effect < 0.0).all(), effect.to_dict()
    assert effect.abs().is_monotonic_increasing  # REPORT_TENORS is tenor-ordered
    assert abs(effect.loc["30Y"]) == pytest.approx(0.0264, abs=5e-3)
    assert abs(effect.loc["1Y"]) < 0.002

    unexplained = (fair_basis["ql"] - fair_basis["rl_mtm"]) + effect
    assert float(unexplained.abs().max()) < CROSS_LIBRARY_TOL_BP, (
        "the QuantLib-vs-rateslib gap is NOT explained by the MTM convention: "
        f"{unexplained.to_dict()}"
    )


# ------------------------------------------------------------------ #
#                    IBOR-indexed legs are refused                   #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("token", ["AUD_BBSW", "NZD_BKBM"])
def test_ibor_legs_are_refused_with_an_actionable_message(token: str):
    """``AUD_BBSW`` and ``NZD_BKBM`` are 3M IBOR legs, not RFR-OIS legs.

    Actionable means the message says what to use instead - the RFR pair - rather
    than only that something is unsupported. Both builders in this package
    construct compounded RFR legs on both sides, so pricing a term-fixing leg
    through them would be wrong in a way no assertion downstream would catch.
    """
    for call in (ois_index_for_currency, conventions_for_currency):
        with pytest.raises(UnknownTagError) as excinfo:
            call(token)
        message = str(excinfo.value)
        assert "IBOR" in message
        assert "OIS" in message
        assert iso_currency(token) in message  # "use the RFR pair (AUD) instead"

    with pytest.raises(UnknownTagError):
        rl_xcs_kwargs(spread_ccy=token, other_ccy="USD")
    with pytest.raises(UnknownTagError):
        assert_ois_pair(token, "USD")

    # The RFR sibling of the same currency is fine.
    assert ois_index_for_currency(iso_currency(token)).startswith(iso_currency(token))


@pytest.mark.parametrize("token", ["AUD_BBSW", "NZD_BKBM"])
def test_an_ibor_strip_never_reaches_a_curve_builder(market: _Market, token: str):
    """REGRESSION. Both builders used to price an IBOR-tokened strip as RFR-OIS.

    The strip carries Citi's raw tokens, but every consumer reduced them with
    ``iso_currency`` on the way in, and ``AUD_BBSW`` reduces to ``AUD`` - which
    has an RFR cross-currency spec. So ``solve_rl_collateral_curve`` found
    ``audusd_xcs``, short-circuited before any convention lookup, and solved a
    curve off an AONIA-indexed schedule for a BBSW-indexed quote without a word.
    The QuantLib bootstrap had the same hole from the other side: it policed the
    indices it was HANDED but never the strip's own tokens, so an ``ql.Aonia``
    passed its check while still mispricing the leg.

    The strip below is deliberately nonsense (EUR/USD quotes relabelled), because
    the guard has to fire before anything numeric happens.
    """
    strip = basis_from_quotes(
        quotes={t: BASIS_BP[t] for t in AXIS}, ccy1=token, ccy2="USD",
        as_of=REF_DATE.date(),
    )
    assert strip.base_ccy == token  # the strip itself may carry it: it is data

    with pytest.raises(UnknownTagError):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            solve_rl_collateral_curve(
                basis=strip, domestic_curve=market.eur_curve,
                foreign_curve=market.usd_curve, fx_rate=FX_EURUSD,
                ref_date=REF_DATE, notional=NOTIONAL, mtm=True,
            )

    with pytest.raises(UnknownTagError):
        build_rl_xcs(
            basis=strip, tenor="5Y", domestic_curve=market.eur_curve,
            foreign_curve=market.usd_curve,
            fx_forwards=market.rl_curves.fx_forwards, notional=NOTIONAL,
        )

    with pytest.raises(UnknownTagError):
        bootstrap_ql_xccy_discount_curve(
            basis=strip, base_index=market.estr, quote_index=market.sofr,
            base_discount=market.h_eur, quote_discount=market.h_usd,
            fx_spot=FX_EURUSD, ref_date=REF_DATE.date(), notional=NOTIONAL,
            calendar=market.joint,
        )


def test_iso_reduction_is_what_hid_the_ibor_leg():
    """MUTATION CHECK for where the guard sits, not just that it exists.

    A guard placed one line later - after ``iso_currency`` - cannot fire, because
    by then ``AUD_BBSW`` and ``AUD`` are the same string and ``AUD`` is a
    perfectly good RFR leg. This test runs the naive placement and asserts it
    lets the IBOR token straight through, so moving the real guard down would
    fail a test rather than silently restoring the bug.
    """
    assert iso_currency("AUD_BBSW") == "AUD"
    assert iso_currency("NZD_BKBM") == "NZD"
    assert ("AUD", "USD") in RL_XCS_SPECS  # the spec the short-circuit found

    def _naive_guard(token: str) -> None:
        """The guard as it would be if it ran after the ISO reduction."""
        ois_index_for_currency(iso_currency(token))

    _naive_guard("AUD_BBSW")  # no exception: the distinction is already gone
    _naive_guard("NZD_BKBM")
    with pytest.raises(UnknownTagError):
        ois_index_for_currency("AUD_BBSW")  # the real guard, on the raw token

    # The reduction is also why the spread currency cannot carry the flag: it is
    # ISO by construction.
    assert default_spread_ccy("AUD_BBSW", "USD") == "AUD"


def test_quantlib_refuses_an_ibor_index_object(market: _Market):
    """The other half of the QuantLib guard: the index it is handed.

    ``ql.OvernightLeg`` compounds a daily fixing. Handing it a ``Euribor3M``
    would build a term-fixing leg as though it compounded, which is why the type
    is checked rather than duck-typed.
    """
    eff = market.joint.advance(market.d0, 2, ql.Days)
    with pytest.raises(ValueError) as excinfo:
        build_ql_xccy_swap(
            notional=NOTIONAL, fx_spot=FX_EURUSD, start=eff,
            maturity=eff + ql.Period("5Y"),
            base_index=ql.Euribor3M(market.h_eur), quote_index=market.sofr,
            base_discount=market.h_coll, quote_discount=market.h_usd,
            spread_bp=-16.0, base_ccy="EUR", quote_ccy="USD", spread_ccy="EUR",
            calendar=market.joint,
        )
    message = str(excinfo.value)
    assert "OvernightIndex" in message
    assert "Euribor3M" in message
