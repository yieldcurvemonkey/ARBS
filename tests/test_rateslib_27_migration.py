r"""Regression tests for the rateslib 2.1.1 -> 2.7.1 upgrade.

These lock in the call shapes that CHANGED, so a future upgrade (or an accidental
downgrade) fails here rather than three layers away in a risk number. Every one
was found by running the repo's own objects under both versions, not by reading a
changelog.

The two behaviour changes worth knowing about, both verified below:

* **STIR futures BPV moved.** rateslib 2.7 changed the ``usd_stir``/``eur_stir``/
  ``gbp_stir`` fixed-leg convention from ``act360``/``act365f`` to ``actacticma``.
  The future's *rate* is unchanged, but ``analytic_delta`` went from ``-25.2778``
  to exactly ``-25.0`` - which is the exchange-defined $25/bp for a 3M SOFR
  contract, i.e. 2.7 corrected it. Anything sizing off STIR DV01 moves ~1.1%.
* **UK gilt stub flipped** from ``shortfront`` to ``longfront``, which changes the
  coupon schedule (and so any curve-based cashflow pricing) without moving a
  yield-based metric.

``scripts/rateslib_upgrade_baseline.py`` is the broader instrument: it dumps 918
numbers and diffs them across an upgrade. Max absolute change across the whole
migration was 2.6e-12.
"""

from __future__ import annotations

import datetime

import pytest
import rateslib as rl


def _version() -> tuple[int, ...]:
    return tuple(int(p) for p in rl.__version__.split(".")[:2])


pytestmark = pytest.mark.skipif(
    _version() < (2, 7), reason="these lock in rateslib >= 2.7 behaviour"
)

REF = datetime.datetime(2026, 8, 5)


@pytest.fixture(scope="module")
def curve() -> rl.Curve:
    nodes = {REF: 1.0}
    for years in (0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30, 45):
        nodes[REF + datetime.timedelta(days=int(365.25 * years))] = 1 / (1.042**years)
    return rl.Curve(nodes=nodes, id="c", convention="act360", calendar="nyc")


# ------------------------------------------------------------------ #
#                        the renamed arguments                       #
# ------------------------------------------------------------------ #


def test_instrument_kwargs_is_no_longer_a_flat_dict():
    """``.kwargs`` became a ``_KWArgs`` with ``.leg1`` / ``.leg2`` / ``.meta``.

    The old ``irs.kwargs["fixed_rate"]`` raises ``TypeError``, and - worse - the
    ``irs.__dict__.get("kwargs", {}).get("fixed_rate")`` form the repo used
    returned ``None`` silently, which only surfaced as ``float(None)``.
    """
    irs = rl.IRS(
        effective=REF, termination="10Y", spec="usd_irs", curves="c", fixed_rate=4.2,
        notional=1e6,
    )
    with pytest.raises(TypeError):
        _ = irs.kwargs["fixed_rate"]
    assert irs.kwargs.leg1["fixed_rate"] == pytest.approx(4.2)
    assert irs.kwargs.leg1["notional"] == pytest.approx(1e6)


def test_no_module_reaches_through_instance_dict_for_kwargs():
    """``obj.__dict__["kwargs"]`` must not come back anywhere in the repo.

    It was used in 18 places - including two production STIR/SDR curve builders -
    and every one of them breaks on 2.7, where ``kwargs`` is a property rather
    than an instance attribute. The ``.get("kwargs", {}).get(...)`` variant is the
    dangerous one: it returns ``None`` silently instead of raising, so the failure
    surfaces later as ``float(None)`` somewhere unrelated.

    Schedule fields moved too: ``effective``/``termination`` now live on
    ``leg1.schedule``, while ``fixed_rate``/``notional`` stay in ``kwargs.leg1``.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in rel or rel == "tests/test_rateslib_27_migration.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if '__dict__["kwargs"]' in text or '__dict__.get("kwargs"' in text:
            offenders.append(rel)
    assert not offenders, (
        "these reach into an instrument's __dict__ for kwargs, which 2.7 broke: "
        f"{offenders}"
    )


def test_schedule_dates_are_on_the_schedule_not_in_kwargs():
    """The replacement accessors, pinned."""
    irs = rl.IRS(effective=REF, termination="10Y", spec="usd_irs", curves="c", fixed_rate=4.2)
    assert irs.leg1.schedule.effective == REF
    assert irs.leg1.schedule.termination is not None
    assert irs.kwargs.leg1["fixed_rate"] == pytest.approx(4.2)
    assert "effective" not in irs.kwargs.leg1


def test_rate_fixings_were_renamed():
    """``leg2_fixings`` -> ``leg2_rate_fixings``.

    Note the error message's "did you mean ``leg2_fx_fixings``" is a TRAP -
    that is the MTM FX reset series, a different thing entirely.
    """
    import pandas as pd

    fixings = pd.Series([0.0433] * 10, index=pd.date_range(end="2026-08-05", periods=10))
    with pytest.raises(TypeError):
        rl.IRS(effective=REF, termination="5Y", spec="usd_irs", curves="c", leg2_fixings=fixings)
    irs = rl.IRS(
        effective=REF, termination="5Y", spec="usd_irs", curves="c", leg2_rate_fixings=fixings
    )
    assert irs is not None


def test_analytic_delta_takes_curves_not_curve(curve: rl.Curve):
    irs = rl.IRS(effective=REF, termination="10Y", spec="usd_irs", curves="c", fixed_rate=4.0)
    with pytest.raises(TypeError):
        irs.analytic_delta(curve=curve)
    assert float(irs.analytic_delta(curves=curve).real) != 0.0


def test_leg2_method_param_was_removed():
    with pytest.raises(TypeError):
        rl.IRS(
            effective=REF, termination="5Y", frequency="a", convention="act360",
            calendar=rl.get_calendar("nyc"), currency="usd", curves="c",
            leg2_fixing_method="rfr_payment_delay", leg2_method_param=0,
        )


def test_defaults_calendars_dict_was_removed():
    """``rl.defaults.calendars`` is gone; ``get_calendar`` is the way in."""
    assert not hasattr(rl.defaults, "calendars")
    assert rl.get_calendar("nyc") is not None


# ------------------------------------------------------------------ #
#                       the behaviour changes                        #
# ------------------------------------------------------------------ #


def test_stir_future_bpv_is_now_the_exchange_contract_value(curve: rl.Curve):
    """A 3M SOFR future's DV01 is exactly $25/bp, and 2.7 now returns that.

    ``usd_stir``'s fixed-leg convention became ``actacticma``, so the accrual is
    exactly 0.25 and ``analytic_delta`` is ``1,000,000 * 0.25 * 1e-4 = 25``.
    Under 2.1.1 the ``act360`` convention gave ``-25.2778``. The RATE is unchanged
    either way, so only a risk-side check catches this.
    """
    assert rl.defaults.spec["usd_stir"]["convention"] == "actacticma"

    start = rl.scheduling.get_imm(code="Z26")
    end = rl.scheduling.next_imm(start)
    fut = rl.STIRFuture(effective=start, termination=end, spec="usd_stir", curves="c")

    delta = float(fut.analytic_delta(curves=curve).real)
    assert delta == pytest.approx(-25.0, abs=1e-9)

    old = rl.STIRFuture(
        effective=start, termination=end, spec="usd_stir", convention="act360", curves="c"
    )
    old_delta = float(old.analytic_delta(curves=curve).real)
    assert abs(old_delta - delta) > 0.2, "the convention change must be visible in the BPV"

    # ... and the rate is identical, which is why a rate-only test misses it.
    assert float(fut.rate(curves=curve)) == pytest.approx(float(old.rate(curves=curve)), abs=1e-12)


def test_stir_future_analytic_delta_is_discount_invariant(curve: rl.Curve):
    """Justifies the unit curve ``RLSTIRFuturePricer`` now passes.

    2.7 made the curve argument mandatory, but a future carries no discounting -
    so a DF==1 curve reproduces the old no-argument value exactly rather than
    approximating it.
    """
    start = rl.scheduling.get_imm(code="Z26")
    end = rl.scheduling.next_imm(start)
    fut = rl.STIRFuture(effective=start, termination=end, spec="usd_stir", curves="c")

    unit = rl.Curve(
        {datetime.datetime(1990, 1, 1): 1.0, datetime.datetime(2090, 1, 1): 1.0},
        id="unit", convention="act360", calendar="nyc",
    )
    steep = rl.Curve(
        {datetime.datetime(1990, 1, 1): 1.0, datetime.datetime(2090, 1, 1): 0.2},
        id="steep", convention="act360", calendar="nyc",
    )
    a = float(fut.analytic_delta(curves=unit).real)
    b = float(fut.analytic_delta(curves=steep).real)
    c = float(fut.analytic_delta(curves=curve).real)
    assert a == pytest.approx(b, abs=1e-12) == pytest.approx(c, abs=1e-12)


def test_stir_pricer_pv01_still_works_and_is_the_contract_bpv():
    """The repo's own STIR pricer, which called ``analytic_delta()`` with no args."""
    from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import _unit_discount_curve

    assert _unit_discount_curve() is not None
    start = rl.scheduling.get_imm(code="Z26")
    end = rl.scheduling.next_imm(start)
    fut = rl.STIRFuture(effective=start, termination=end, spec="usd_stir", curves="c")
    bpv = -float(fut.analytic_delta(curves=_unit_discount_curve()).real)
    assert bpv == pytest.approx(25.0, abs=1e-9)


def test_uk_gilt_stub_convention_flipped():
    """``uk_gb`` went from ``shortfront`` to ``longfront``.

    This changes the SCHEDULE - a bond with a front stub gains or loses a coupon
    period - without moving a yield-computed metric, so only a schedule-shape
    check catches it.
    """
    assert rl.defaults.spec["uk_gb"]["stub"] == "longfront"

    def periods(stub: str) -> int:
        bond = rl.FixedRateBond(
            effective=datetime.datetime(2021, 3, 7),
            termination=datetime.datetime(2032, 6, 7),
            fixed_rate=4.25,
            spec="uk_gb",
            stub=stub,
        )
        return len(bond.leg1.schedule.aschedule) - 1

    assert periods("longfront") != periods("shortfront")


def test_ex_div_representation_changed_but_behaviour_did_not():
    """``ex_div`` became a signed business-day string (``1`` -> ``'-1b'``).

    Accrued interest is identical on both sides of the ex-dividend boundary, so
    this one is cosmetic - asserted so a future reader does not go hunting.
    """
    assert str(rl.defaults.spec["us_gb_tsy"]["ex_div"]) == "-1b"
    accrued = {}
    for ex_div in (1, "-1b"):
        bond = rl.FixedRateBond(
            effective=datetime.datetime(2021, 8, 15),
            termination=datetime.datetime(2031, 8, 15),
            fixed_rate=1.25,
            spec="us_gb_tsy",
            ex_div=ex_div,
        )
        accrued[str(ex_div)] = [
            float(bond.accrued(settlement=datetime.datetime.fromisoformat(d)))
            for d in ("2026-08-13", "2026-08-14", "2026-08-17")
        ]
    assert accrued["1"] == pytest.approx(accrued["-1b"])


# ------------------------------------------------------------------ #
#                    the IR vol cubes 2.7 unlocked                   #
# ------------------------------------------------------------------ #


def test_ir_vol_cubes_now_exist():
    """The reason for the upgrade. These do NOT exist in 2.1.1."""
    assert hasattr(rl, "IRSabrCube")
    assert hasattr(rl, "IRSplineCube")
    from MDP.CitiVelocityExcel.vol import RATESLIB_NATIVE_AVAILABLE

    assert RATESLIB_NATIVE_AVAILABLE is True


def test_native_cube_refuses_rather_than_serving_an_unverified_smile():
    """The native backend must not hand back a smile it cannot reproduce.

    ``rl.IRSplineCube`` builds from the Citi grid and its ATM node round-trips
    exactly, but the off-ATM nodes do not, and the strike axis is scale-invariant
    across bp / percent / decimal - so the cause is a parameterisation convention
    that has not been identified, not a unit error. Until it is, the builder
    raises. A cube that quietly returned 453 bp where 82 bp was fed in would pass
    every downstream assertion.
    """
    import math

    from MDP.CitiVelocityExcel.curves import build_rl_ois_curve
    from MDP.CitiVelocityExcel.vol import (
        NativeCubeUnverifiedError,
        build_rl_native_cube,
        build_rl_vol_cube,
    )
    from MDP.CitiVelocityExcel.vol.cube_data import cube_from_quotes, cube_tags

    expiries, tenors, offsets = ("1Y", "2Y"), ("2Y", "10Y"), (-25.0, 25.0)
    years = {"M": 1 / 12, "Y": 1.0}

    def yrs(token: str) -> float:
        return float(token[:-1]) * years[token[-1]]

    tag_map = cube_tags(currency="USD", expiries=expiries, tenors=tenors, offsets_bp=offsets)
    quotes = {}
    for tag, (kind, expiry, tenor, offset) in tag_map.items():
        base = 55 + 60 * math.exp(-yrs(tenor) / 8) + 20 * math.exp(-yrs(expiry) / 2)
        quotes[tag] = base if kind == "ATM" else base + 6 * (offset / 100) ** 2
    cube = cube_from_quotes(
        quotes=quotes, currency="USD", as_of=datetime.date(2026, 8, 5),
        expiries=expiries, tenors=tenors, offsets_bp=offsets, served_unit="bp",
    )
    par = {t: 3.6 + 0.9 * (1 - math.exp(-yrs(t) / 3)) for t in
           ("1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "30Y", "40Y")}
    rl_curve = build_rl_ois_curve(
        par_rates=par, ref_date=datetime.date(2026, 8, 5), citi_index="USD_SOFR"
    )
    hand = build_rl_vol_cube(cube=cube, rl_curve=rl_curve)
    forwards = {(e, t): hand.forward(e, t) for e in expiries for t in tenors}

    with pytest.raises(NativeCubeUnverifiedError, match="did not reproduce"):
        build_rl_native_cube(cube=cube, forwards=forwards, citi_index="USD_SOFR")

    # ... while the hand-built cube reproduces its nodes exactly.
    for expiry in expiries:
        for tenor in tenors:
            for offset in offsets:
                assert hand.normal_vol(expiry, tenor, offset_bp=offset) == pytest.approx(
                    cube.vol(expiry, tenor, offset), abs=1e-8
                )
