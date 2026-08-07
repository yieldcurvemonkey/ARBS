r"""Citi Velocity through the repo's own swaption product, in both engines.

``source='CITIVELO-QL'`` and ``source='CITIVELO-RL'`` build an
``IRSwaptionMarketContext`` that the existing, unmodified ``Query/IRSwaptions``
layer prices - thirteen structures, twenty value metrics, the ``"ATMF+25"`` strike
grammar - over Citi's ATM surface **and every OTM offset**.

Everything is driven off the recorded live snapshot and a curve stripped from its
own par grid, so there is no network, no Excel and no database. The curve
wrappers are the repo's real ``QLIRSwapCurve`` / ``RLIRSwapCurve``; only the
market data is local.

The end-to-end assertion is the same one
``MDP/CitiVelocityExcel/vol/spot_check.py`` makes, taken through one more layer:
ask the Query stack for ``NVOL`` at ``ATMF``, ``ATMF+25``, ``ATMF-50``,
``ATMF+100`` and ``ATMF-200``, and check it comes back as Citi's quote for that
offset. Nothing in that path reads the interpolator directly - the strike is
resolved from the curve's forward, the swaption is built and priced, and the
volatility is inverted back out of the premium.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

rl = pytest.importorskip("rateslib")
import QuantLib as ql  # noqa: E402

from MDP.CitiVelocityExcel.curves import build_ql_ois_curve, build_rl_ois_curve  # noqa: E402
from MDP.CitiVelocityExcel.vol.live_snapshot import load_snapshot  # noqa: E402
from MDP.CitiVelocityExcel.vol.rl_native_cube import RATESLIB_NATIVE_AVAILABLE  # noqa: E402
from MDP.IRSwaptions.CITIVELO.provider import clear_citivelo_cube_cache  # noqa: E402
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP  # noqa: E402
from Query.Base.query_resolution import resolve_query  # noqa: E402
from Query.IRSwaps.backends.quantlib.QLIRSwapCurve import QLIRSwapCurve  # noqa: E402
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve  # noqa: E402
from Query.IRSwaptions import IRSwaptionQuery, IRSwaptionStructure, IRSwaptionValue  # noqa: E402

pytestmark = pytest.mark.skipif(
    not RATESLIB_NATIVE_AVAILABLE,
    reason="needs rateslib >= 2.7.0 for IRSplineCube / IRSCall",
)

CURVE = "USD-SOFR-1D"
EXPIRIES = ("1Y", "10Y")
TENORS = ("10Y", "30Y")
OFFSETS = (-200.0, -50.0, 0.0, 25.0, 100.0)

#: ``(offset, strike spec, structure)``. A signed offset picks the out-of-the-money
#: side, which is also what ``_infer_outright_structure`` does with the spec.
STRIKE_CASES = (
    (0.0, "ATMF", IRSwaptionStructure.PAYER),
    (25.0, "ATMF+25", IRSwaptionStructure.PAYER),
    (-50.0, "ATMF-50", IRSwaptionStructure.RECEIVER),
    (100.0, "ATMF+100", IRSwaptionStructure.PAYER),
    (-200.0, "ATMF-200", IRSwaptionStructure.RECEIVER),
)


class _QLCurve(QLIRSwapCurve):
    """``build_ql_ois_curve`` returns an evaluation-date-independent discount curve.

    It is built without a calendar on purpose (that is what makes it independent),
    and ``QLIRSwapCurve.calendar()`` delegates to ``handle().calendar()``. The
    production ERIS curve carries one; this supplies it so date rolling works.
    """

    def calendar(self) -> ql.Calendar:
        return ql.UnitedStates(ql.UnitedStates.GovernmentBond)


@pytest.fixture(scope="module")
def snapshot():
    return load_snapshot()


@pytest.fixture(scope="module")
def cube(snapshot):
    return snapshot.cube(expiries=EXPIRIES, tenors=TENORS, offsets_bp=OFFSETS)


@pytest.fixture(scope="module")
def ql_curve(snapshot):
    built = build_ql_ois_curve(
        par_rates=snapshot.par_rates, ref_date=snapshot.as_of, citi_index=snapshot.citi_index
    )
    return _QLCurve(
        ql_curve_id=CURVE,
        ql_curve_handle=built.handle,
        ql_curve_index=ql.Sofr(built.handle),
        meta_data={"timestamp": snapshot.as_of},
    )


@pytest.fixture(scope="module")
def rl_curve(snapshot):
    built = build_rl_ois_curve(
        par_rates=snapshot.par_rates, ref_date=snapshot.as_of, citi_index=snapshot.citi_index
    )
    # The production curve carries published SOFR fixings. Every swaption here is
    # forward starting so none is ever consumed, but rateslib validates the series
    # when it builds the float leg and an empty one indexes out of bounds.
    index = pd.bdate_range(end=pd.Timestamp(snapshot.as_of) - pd.Timedelta(days=1), periods=400)
    return RLIRSwapCurve(
        rl_curve_id=CURVE,
        rl_curve_handle=built.rl_pricing_curve,
        fixings=pd.Series(4.30, index=index, dtype=float),
        meta_data={"timestamp": snapshot.as_of, "reference_curve_name": CURVE},
    )


def _context(source, curve_obj, cube, snapshot, **extra):
    clear_citivelo_cube_cache()
    mdp = IRSwaptionMDP(source=source)
    mdp._fetch_curve_map = lambda **kw: {snapshot.as_of: curve_obj}  # noqa: ARG005
    request = {
        "curve_name": CURVE,
        "timestamp": snapshot.as_of,
        "cube": cube,
        "citi_index": snapshot.citi_index,
        "ignore_cache": True,
    }
    request.update(extra)
    return mdp.get_pricer(request)


@pytest.fixture(scope="module")
def ql_context(ql_curve, cube, snapshot):
    return _context("CITIVELO-QL", ql_curve, cube, snapshot)


@pytest.fixture(scope="module")
def rl_context(rl_curve, cube, snapshot):
    return _context("CITIVELO-RL", rl_curve, cube, snapshot)


def _nvol(context, spec, structure, value=IRSwaptionValue.NVOL, expiry="1Y", tail="10Y"):
    query = IRSwaptionQuery(
        curve=CURVE,
        shorthand=f"{expiry}x{tail}",
        strike=spec,
        structure=structure,
        value=value,
        structure_kwargs={"notional": 1e8},
    )
    resolved = resolve_query(query, timestamp=context.as_of_date, pricer_or_curve=context)
    package, weights = resolved.resolve_package(pricer_or_curve=context)
    vmap = resolved.build_value_map(
        pricer_or_curve=context, package=package, risk_weights=weights
    )
    return float(vmap.apply(value))


# ------------------------------------------------------------------ #
#                          the context itself                        #
# ------------------------------------------------------------------ #


def test_citivelo_ql_builds_a_quantlib_context(ql_context):
    assert ql_context.provider == "CITIVELO"
    assert ql_context.engine == "QL"
    assert ql_context.source == "CITIVELO-QL"
    assert isinstance(ql_context.vol_handle, ql.SwaptionVolatilityStructureHandle)
    assert isinstance(ql_context.pricing_engine, ql.PricingEngine)
    assert "citivelo_cube" in ql_context.metadata
    # NOT 'vol_cube': that key routes leg_cube_vol into volatility_at_point(),
    # which would have to rebuild an option date out of an option time.
    assert "vol_cube" not in ql_context.metadata


def test_citivelo_rl_builds_a_rateslib_context(rl_context):
    from MDP.IRSwaptions.CITIVELO.rl_engine import RLSwaptionEngine
    from MDP.CitiVelocityExcel.vol.swaption_cube import CitiVeloSwaptionCube

    assert rl_context.provider == "CITIVELO"
    assert rl_context.engine == "RL"
    assert isinstance(rl_context.vol_handle, CitiVeloSwaptionCube)
    assert isinstance(rl_context.pricing_engine, RLSwaptionEngine)
    assert rl_context.vol_handle.is_rateslib
    # The cube still carries a QuantLib surface, mirrored off the rateslib curve's
    # own nodes, because that is what answers the ql-shaped volatility() call
    # Query/IRSwaptions makes.
    assert "ql" in rl_context.vol_handle.backends_available


# ------------------------------------------------------------------ #
#              the end-to-end check, ATM and every offset            #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("offset,spec,structure", STRIKE_CASES)
def test_ql_engine_recovers_citis_quote_at_every_offset(
    ql_context, cube, offset, spec, structure
):
    """Priced as a ``ql.Swaption``, inverted by QuantLib, compared with the quote.

    The residual is the gap between QuantLib's ``atmStrike`` anchor and the
    forward of the swap the Query layer built, times the local smile slope. It is
    a hundredth of a basis point; 0.05 bp is loose enough not to be brittle and
    tight enough that a wrong anchor could not hide in it.
    """
    assert _nvol(ql_context, spec, structure) == pytest.approx(
        cube.vol("1Y", "10Y", offset), abs=0.05
    )


@pytest.mark.parametrize("offset,spec,structure", STRIKE_CASES)
def test_rl_engine_recovers_citis_quote_at_every_offset(
    rl_context, cube, offset, spec, structure
):
    assert _nvol(rl_context, spec, structure) == pytest.approx(
        cube.vol("1Y", "10Y", offset), abs=0.05
    )


@pytest.mark.parametrize("offset,spec,structure", STRIKE_CASES)
def test_the_two_engines_agree_on_the_premium(
    ql_context, rl_context, offset, spec, structure
):
    """Different libraries, different instruments, same number.

    ``rl.IRSCall`` priced off ``rl.IRS`` against ``ql.Swaption`` priced off
    ``ql.MakeOIS`` and ``ql.BachelierSwaptionEngine``. They are handed curves
    bootstrapped independently from the same par grid, so a few parts in 1e4 is
    the curve difference; anything larger would be a schedule difference.
    """
    left = _nvol(ql_context, spec, structure, value=IRSwaptionValue.SPOT_NPV)
    right = _nvol(rl_context, spec, structure, value=IRSwaptionValue.SPOT_NPV)
    assert left == pytest.approx(right, rel=1e-3)


@pytest.mark.parametrize("expiry", EXPIRIES)
@pytest.mark.parametrize("tail", TENORS)
def test_every_grid_point_resolves_on_both_engines(ql_context, rl_context, cube, expiry, tail):
    """The corners too, not just 1Yx10Y.

    The rateslib engine is handed a leg with explicit DATES and has to turn them
    back into cube coordinates; it does that in whole months, so 10Y x 30Y becomes
    ``120M x 360M``. If that conversion ever stopped landing on the node, the
    volatility would come back interpolated instead of exact and only a corner
    would show it.
    """
    quoted = cube.vol(expiry, tail, 0.0)
    for context in (ql_context, rl_context):
        got = _nvol(context, "ATMF", IRSwaptionStructure.PAYER, expiry=expiry, tail=tail)
        assert got == pytest.approx(quoted, abs=0.05), f"{expiry}x{tail} on {context.source}"


def test_vega_agrees_between_the_engines(ql_context, rl_context):
    left = _nvol(ql_context, "ATMF", IRSwaptionStructure.PAYER, value=IRSwaptionValue.VEGA_01)
    right = _nvol(rl_context, "ATMF", IRSwaptionStructure.PAYER, value=IRSwaptionValue.VEGA_01)
    assert left > 0
    assert left == pytest.approx(right, rel=1e-3)


def test_a_structure_prices_through_both_engines(ql_context, rl_context, cube):
    """A straddle, to prove this is the whole product and not one code path."""
    for context in (ql_context, rl_context):
        value = _nvol(context, "ATMF", IRSwaptionStructure.STRADDLE, value=IRSwaptionValue.SPOT_NPV)
        assert value > 0


# ------------------------------------------------------------------ #
#                              the guards                            #
# ------------------------------------------------------------------ #


def test_ignore_cache_does_not_bypass_the_curve_cache(rl_curve, cube, snapshot, caplog):
    """A swaption cache flag must not become a COM fetch against the user's Excel.

    ``ignore_cache`` on a swaption request means "rebuild the context". It used to
    be forwarded verbatim into the curve request, where it means "do not serve a
    warmed curve artefact" - and for ``citivelo_excel*`` the CurveStore fast path
    is gated on exactly that flag, so bypassing it drops through to the
    cached-then-LIVE quotes layer and, on a cold tag cache, drives the signed-in
    Excel add-in.

    The two are separate knobs now: ``ignore_cache`` rebuilds the context off the
    warmed curve, and ``curve_ignore_cache`` is the explicit way to refresh the
    curve - which warns when that refresh can go outside the process.
    """
    import logging

    seen: list[bool] = []
    mdp = IRSwaptionMDP(source="CITIVELO-RL", curve_source="citivelo_excel_rl")

    def _capture(*, curve_name, dates, ignore_cache):  # noqa: ARG001
        seen.append(bool(ignore_cache))
        return {snapshot.as_of: rl_curve}

    mdp._fetch_curve_map = _capture
    request = {
        "curve_name": CURVE,
        "timestamp": snapshot.as_of,
        "cube": cube,
        "citi_index": snapshot.citi_index,
    }

    mdp.get_pricer({**request, "ignore_cache": True})
    assert seen == [False], "ignore_cache must not reach the curve request"

    seen.clear()
    with caplog.at_level(logging.WARNING, logger="MDP.IRSwaptions.IRSwaptionMDP"):
        mdp.get_pricer({**request, "ignore_cache": True, "curve_ignore_cache": True})
    assert seen == [True], "curve_ignore_cache is the knob that does reach it"

    # And it is loud about what it is about to do, because the caller cannot see
    # the CurveStore gate from here.
    real = IRSwaptionMDP(source="CITIVELO-RL", curve_source="citivelo_excel_rl")
    with caplog.at_level(logging.WARNING, logger="MDP.IRSwaptions.IRSwaptionMDP"):
        caplog.clear()
        try:
            real._fetch_curve_map(curve_name=CURVE, dates=[snapshot.as_of], ignore_cache=True)
        except Exception:
            pass
    assert any("Excel" in r.message or "Excel" in r.getMessage() for r in caplog.records)


def test_force_refresh_still_refreshes_the_curve(rl_curve, cube, snapshot):
    """``force_refresh=True`` is the explicit "refresh everything" switch."""
    seen: list[bool] = []
    mdp = IRSwaptionMDP(
        source="CITIVELO-RL", curve_source="citivelo_excel_rl", force_refresh=True
    )
    mdp._fetch_curve_map = lambda *, curve_name, dates, ignore_cache: (  # noqa: ARG005
        seen.append(bool(ignore_cache)) or {snapshot.as_of: rl_curve}
    )
    mdp.get_pricer(
        {
            "curve_name": CURVE,
            "timestamp": snapshot.as_of,
            "cube": cube,
            "citi_index": snapshot.citi_index,
        }
    )
    assert seen == [True]


def test_the_cube_accepts_an_RLIRSwapCurve_wrapper_directly(rl_curve, cube, snapshot):
    """``IRSwapsMDP`` hands back the wrapper, so the cube has to take the wrapper.

    ``IRSwapsMDP(source="citivelo_excel_rl")`` - Citi's own warmed SOFR curve -
    returns an ``RLIRSwapCurve``, which is the obvious thing to pass here. It
    exposes the ``rateslib.Curve`` through a ``handle()`` METHOD and satisfies
    none of the duck tests ``_resolve_curves`` makes, so it used to raise a
    TypeError listing three accepted shapes and not the one just passed - while
    this class's own docstring said it was accepted.
    """
    from MDP.CitiVelocityExcel.vol.swaption_cube import (
        build_citivelo_swaption_cube,
        unwrap_rl_curve,
    )

    wrapped = build_citivelo_swaption_cube(
        cube=cube, rl_curve=rl_curve, citi_index=snapshot.citi_index
    )
    bare = build_citivelo_swaption_cube(
        cube=cube, rl_curve=rl_curve.handle(), citi_index=snapshot.citi_index
    )
    assert wrapped.backend == bare.backend
    for expiry in EXPIRIES:
        for tenor in TENORS:
            assert wrapped.forward(expiry, tenor) == pytest.approx(
                bare.forward(expiry, tenor), rel=0, abs=0
            )

    # A QuantLib wrapper's handle() is a QuantLib object and must NOT be routed
    # down the rateslib branch; unwrap_rl_curve leaves it alone.
    assert unwrap_rl_curve(rl_curve) is rl_curve.handle()
    assert unwrap_rl_curve(None) is None


def test_a_rateslib_curve_is_refused_by_the_quantlib_engine(rl_curve, cube, snapshot):
    """The old ``hasattr`` gate passed this and then failed inside SWIG.

    ``RLIRSwapCurve`` defines both ``handle()`` and ``index()``, so the check the
    MDP used to make could not tell the backends apart; what came back was an
    ``rl.Curve`` where a ``ql.YieldTermStructureHandle`` was expected.
    """
    with pytest.raises(TypeError, match="engine='QL' needs a QuantLib curve"):
        _context("CITIVELO-QL", rl_curve, cube, snapshot)


def test_a_quantlib_curve_is_refused_by_the_rateslib_engine(ql_curve, cube, snapshot):
    """There is no lossless QuantLib -> rateslib mirror, so this raises."""
    with pytest.raises(TypeError, match="engine='RL' needs a rateslib curve"):
        _context("CITIVELO-RL", ql_curve, cube, snapshot)


def test_premium_overrides_are_refused_on_the_rateslib_engine(rl_context):
    """Declared, not silently approximated.

    The QuantLib path inverts a supplied premium through
    ``ql.Swaption.impliedVolatility``; matching that here would need a second
    inverter and would quietly price off a different model.
    """
    query = IRSwaptionQuery(
        curve=CURVE,
        shorthand="1Yx10Y",
        strike="ATMF",
        structure=IRSwaptionStructure.PAYER,
        value=IRSwaptionValue.NVOL,
        structure_kwargs={"notional": 1e8, "premium": 500_000.0},
    )
    resolved = resolve_query(query, timestamp=rl_context.as_of_date, pricer_or_curve=rl_context)
    with pytest.raises(NotImplementedError, match="premium_override is not supported"):
        package, weights = resolved.resolve_package(pricer_or_curve=rl_context)
        vmap = resolved.build_value_map(
            pricer_or_curve=rl_context, package=package, risk_weights=weights
        )
        vmap.apply(IRSwaptionValue.NVOL)


def test_only_opted_in_providers_are_handed_the_new_keywords():
    """``curves=`` and ``engine=`` must not reach a provider that did not ask.

    ``MONKEYCUBE``'s provider forwards ``**kwargs`` straight into
    ``get_sabr_vol_surfaces``, where an unexpected keyword is a ``TypeError`` and
    the whole batch would be swallowed by the fallback loop and come back empty.
    """
    from MDP.IRSwaptions.IRSwaptionMDP import _citivelo_vol_provider

    mdp = IRSwaptionMDP(source="GSQUANT-QL")
    assert getattr(_citivelo_vol_provider, "wants_curves", False) is True
    assert getattr(_citivelo_vol_provider, "wants_engine", False) is True
    for name in ("GSQUANT", "MONKEYCUBE", "GSQUANT_MC_ENHANCED"):
        provider = mdp.VOL_PROVIDERS[name]
        assert getattr(provider, "wants_curves", False) is False
        assert getattr(provider, "wants_engine", False) is False


def test_both_engines_are_registered_beside_the_existing_providers():
    mdp = IRSwaptionMDP(source="GSQUANT-QL")
    assert set(mdp.ENGINE_FACTORIES) >= {"QL", "RL"}
    assert set(mdp.VOL_PROVIDERS) >= {
        "GSQUANT",
        "MONKEYCUBE",
        "GSQUANT_MC_ENHANCED",
        "CITIVELO",
    }
    # The default is still the one every production call site pins.
    assert mdp.source.upper().startswith("GSQUANT")


@pytest.mark.network
@pytest.mark.parametrize(
    "source,curve_source",
    [
        ("CITIVELO-QL", "ERIS_EOD_LIVE-QL_BASIC"),
        ("CITIVELO-RL", "ERIS_EOD_LIVE-RL_BASIC"),
    ],
)
def test_both_engines_run_on_a_real_curve_source(snapshot, cube, source, curve_source):
    """The production path: a curve from IRSwapsMDP, not one built in the fixture.

    Everything else in this file injects the curve so it stays hermetic, which
    leaves the ``IRSwapsMDP`` fetch itself untested. Marked ``network`` because
    ERIS EOD curves are not local; run with
    ``pytest -m network tests/test_citivelo_swaption_provider.py``.

    Measured 2026-08-06: ``CITIVELO-QL`` on the ERIS QuantLib curve returns
    82.1183 / 96.5198 / 98.7044 bp against Citi's 82.1221 / 96.5305 / 98.6960 at
    ATMF, +100 and -200 - the residual is that the vol is Citi's and the curve is
    not, so the strike axis is anchored a fraction of a basis point elsewhere.
    ``CITIVELO-RL`` on the ERIS rateslib curve is exact, because its engine reads
    the smile by offset.

    ``curve_source="CITIVELO"`` - Citi's OWN curve - is deliberately not here: the
    CurveStore asset ``USD-SOFR-1D-CITIVELO`` has no 2026-08-06 partition warmed,
    so it would fail for want of data rather than for want of code.
    """
    clear_citivelo_cube_cache()
    mdp = IRSwaptionMDP(source=source, curve_source=curve_source)
    context = mdp.get_pricer(
        {
            "curve_name": CURVE,
            "timestamp": snapshot.as_of,
            "cube": cube,
            "citi_index": snapshot.citi_index,
            "ignore_cache": True,
        }
    )
    assert context.provider == "CITIVELO"
    for offset, spec, structure in STRIKE_CASES:
        assert _nvol(context, spec, structure) == pytest.approx(
            cube.vol("1Y", "10Y", offset), abs=0.05
        )


def test_a_snapshot_dated_elsewhere_is_refused(ql_curve, cube, snapshot):
    """A cube carried to another date is a wrong number that looks right."""
    from MDP.CitiVelocityExcel.errors import CitiVelocityError

    clear_citivelo_cube_cache()
    mdp = IRSwaptionMDP(source="CITIVELO-QL")
    other = snapshot.as_of + dt.timedelta(days=1)
    mdp._fetch_curve_map = lambda **kw: {other: ql_curve}  # noqa: ARG005
    with pytest.raises((CitiVelocityError, KeyError)):
        mdp.get_pricer(
            {
                "curve_name": CURVE,
                "timestamp": other,
                "snapshot": snapshot.path.name,
                "citi_index": snapshot.citi_index,
                "ignore_cache": True,
            }
        )
