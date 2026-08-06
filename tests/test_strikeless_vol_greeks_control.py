# tests/test_strikeless_vol_greeks_control.py
import pandas as pd
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.conventions import FLATTENER
from RVUtils.StrikelessVol.greeks import (
    analytic_leg_gamma,
    build_package,
    daily_dcf,
    gamma_by_h,
    package_dv01,
    package_gamma,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import (
    RATESLIB_CURVE_DEFINITIONS,
)
from utils.rl_compat import leg_cashflows, leg_npv, rate_fixings_kwargs

REF = rl.dt(2026, 8, 3)
PAIR = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))

#: The act365f market. ``rl_curve_definitions_map`` gives GBP-SONIA DayCounter
#: act365f and ReferenceRate ``gbp_irs``, whose legs are act365f too -- the only
#: shape in which an act365f curve exists in this repo, on either side. It is a
#: pair the study already trades: ``universe.GBP_PAIRS`` contains this exact
#: 10y10y/20y10y slope.
GBP_PAIR = ForwardPair("GBP", "GBP-SONIA", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))

#: Curve name -> (curve day count, calendar), read from the definitions map so
#: the fixture cannot drift out of agreement with the spec whose legs it prices.
_DEFS = {
    name: (RATESLIB_CURVE_DEFINITIONS[name]["DayCounter"],
           RATESLIB_CURVE_DEFINITIONS[name]["Calendar"])
    for name in ("USD-OIS", "GBP-SONIA")
}


def _curve(curve_name: str, convention: str | None = None):
    """Flat 4% on ``curve_name``'s own day count, unless ``convention`` overrides.

    The override exists for exactly one test -- the one that pins rateslib
    2.7.1's refusal of a curve/index convention mismatch -- and is never used
    to build a package that then gets measured.
    """
    day_count, calendar = _DEFS[curve_name]
    nodes = {REF: 1.0}
    nodes.update({rl.dt(2026 + y, 8, 3): 1.0 / (1.04 ** y) for y in range(1, 41)})
    handle = rl.Curve(
        nodes=nodes,
        convention=convention or day_count,
        calendar=calendar,
        id="flat4",
    )
    return RLIRSwapCurve(
        rl_curve_id=curve_name,
        rl_curve_handle=handle,
        # rateslib 2.1.1 crashes in _set_fixings on an empty pd.Series and
        # fails later at .npv() on None; only the NoInput sentinel works.
        # See tests/test_strikeless_vol_greeks.py for the full note. Legs
        # here are forward-starting 10-20y out and need no historical fixings.
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": curve_name},
    )


@pytest.fixture(scope="module")
def curve():
    """The act365f case, on a market that really is act365f on BOTH sides.

    This fixture used to be an act365f curve carrying USD ``usd_irs`` (act360)
    legs -- a deliberate mismatch, kept so the 365/360 float-leg scaling
    artefact it produced could be pinned rather than rediscovered as a bug.
    **rateslib 2.7.1 refuses that pairing outright** (see
    ``test_a_curve_index_convention_mismatch_is_now_refused_outright``), so the
    artefact is no longer constructible and the fixture has moved to GBP-SONIA,
    where act365f is the curve's convention AND ``gbp_irs``'s.

    Nothing that was asserted on the old fixture named a number: every
    assertion reached through it is a sign, a tolerance band, or a convention
    identity (``days * d == days / 365``), all of which hold for any act365f
    curve/leg pair. The act365f side of this file therefore still tests what
    it tested, on a pairing that can actually ship.
    """
    return _curve("GBP-SONIA")


@pytest.fixture(scope="module")
def act360_curve():
    """The convention the repo's USD SOFR curves actually use.

    ``rl_curve_definitions_map.py`` gives USD-SOFR-1D and USD-OIS DayCounter
    act360, and the ``usd_irs`` spec's legs are act360 too, so curve and legs
    agree here and the replication holds without a scaling artefact.
    """
    return _curve("USD-OIS")


@pytest.fixture(scope="module")
def pkg(curve):
    return build_package(curve, GBP_PAIR, package_dv01_usd=100_000.0, sign=FLATTENER)


@pytest.fixture(scope="module")
def act360_pkg(act360_curve):
    return build_package(act360_curve, PAIR, package_dv01_usd=100_000.0, sign=FLATTENER)


def _bumped(price, h=25.0):
    """Second difference of a one-argument repricer, in $/bp^2."""
    return (price(h) + price(-h) - 2.0 * price(0.0)) / (h * h)


def _leg_gamma_bumped(curve, swap, h=25.0):
    handle = curve.handle()
    return _bumped(
        lambda s: swap.npv(curves=handle.shift(s) if s else handle).real, h
    )


def _float_leg_gamma_bumped(curve, swap, h=25.0):
    handle = curve.handle()

    def price(s):
        c = handle.shift(s) if s else handle
        return leg_npv(swap.leg2, c).real

    return _bumped(price, h)


def _legacy_365_control(curve, swap):
    """The pre-fix control, with time hard-coded to days/365.

    Kept so the act360 miss can be measured rather than asserted from theory.
    """
    handle = curve.handle()
    ref = pd.Timestamp(curve.reference_date())
    n, k = float(curve.notional(swap)), float(curve.fixed_rate(swap))

    def t(x):
        return (pd.Timestamp(x) - ref).days / 365.0

    ann = sum(
        float(r["DCF"]) * t(r["Payment"]) ** 2
        * float(handle[pd.Timestamp(r["Payment"]).to_pydatetime()])
        for _, r in leg_cashflows(swap.leg1, handle).iterrows()
    )
    eff, mat = curve.effective_date(swap), curve.maturity_date(swap)
    return n * (
        t(eff) ** 2 * float(handle[eff]) - t(mat) ** 2 * float(handle[mat]) - k * ann
    ) * 1e-8


def _float_replication(curve, swap):
    """N * (t0^2 D(T0) - tN^2 D(TN)) * 1e-8 -- the float half of the control."""
    handle = curve.handle()
    ref = pd.Timestamp(curve.reference_date())
    d = daily_dcf(handle)
    eff, mat = curve.effective_date(swap), curve.maturity_date(swap)
    t0 = (pd.Timestamp(eff) - ref).days * d
    tn = (pd.Timestamp(mat) - ref).days * d
    n = float(curve.notional(swap))
    return n * (t0 * t0 * float(handle[eff]) - tn * tn * float(handle[mat])) * 1e-8


def _semiannual_par_swap(curve, notional=100_000_000.0):
    """A semiannual-schedule par OIS, so ``row["DCF"]`` is ~0.507 not ~1.0."""
    handle = curve.handle()
    kw = dict(
        effective=rl.dt(2036, 8, 3),
        termination=rl.dt(2046, 8, 3),
        spec="usd_irs",
        frequency="S",
        leg2_frequency="S",
        curves=handle,
        notional=notional,
        # `leg2_fixings` became `leg2_rate_fixings` in rateslib 2.7; resolved
        # once, by introspection, in utils.rl_compat rather than named here.
        **rate_fixings_kwargs(rl.NoInput(0)),
    )
    return rl.IRS(**kw, fixed_rate=rl.IRS(**kw).rate(curves=handle).real)


def test_package_dv01_is_neutral_at_inception(curve, pkg):
    """Neutrality is now imposed directly in the repriced measure this
    checks, so the residual is float noise, not a small but real number.

    Each leg is struck at its own fair rate, so each leg's PV is exactly zero
    at inception. ``build_leg`` originally sized each leg off ``curve.pv01``
    (the analytic annuity) while this test checks neutrality in the repriced
    (bump-and-reprice) measure -- those two measures disagree once the curve
    isn't flat (``dR_fair/dDelta`` under a parallel shift is not identical for
    a 10y10y and a 20y10y), which is what left the originally-observed $1.44
    residual on a $100k package here, and an 11.4%-of-target residual on an
    inverted fixture (see ``tests/test_strikeless_vol_breakeven.py``).
    ``build_leg`` now sizes off the same repriced measure
    (``greeks._reprice_dv01``) this test checks, so the two can no longer
    disagree: observed residual is 3.7e-09 dollars on this fixture (0.0
    float-exact on the act360 one), against a $100k package. The abs=10.0
    band is 9 orders of magnitude of headroom, kept because it is the size of
    residual that would matter economically, not the size float noise
    happens to be.
    """
    assert package_dv01(curve, pkg) == pytest.approx(0.0, abs=10.0)


def test_bumped_gamma_matches_the_analytic_replication_formula(curve, pkg):
    """The control: an independent closed form, not the bump code."""
    analytic = analytic_leg_gamma(curve, pkg.short) + analytic_leg_gamma(curve, pkg.long)
    bumped = package_gamma(curve, pkg, h_bp=25.0)
    assert analytic != 0.0
    assert bumped == pytest.approx(analytic, rel=0.02)


def test_each_leg_matches_the_control_on_its_own(curve, pkg):
    """The package sum agrees partly by cancellation, so check the legs too.

    The two legs' residuals point opposite ways (the short leg's bumped
    convexity is more negative than analytic, the long leg's more positive),
    so summing them flatters the agreement. Pinning each leg separately is
    what makes the package number evidence rather than coincidence.
    """
    handle = curve.handle()
    for swap in (pkg.short, pkg.long):
        base = swap.npv(curves=handle).real
        up = swap.npv(curves=handle.shift(25.0)).real
        dn = swap.npv(curves=handle.shift(-25.0)).real
        bumped = (up + dn - 2.0 * base) / (25.0 ** 2)
        assert bumped == pytest.approx(analytic_leg_gamma(curve, swap), rel=0.02)


def test_control_holds_on_the_production_act360_convention(act360_curve, act360_pkg):
    """The case that actually ships: curve act360, usd_irs legs act360.

    With curve and leg conventions agreeing there is no scaling artefact, and
    the control lands far inside its band: residual 0.078% against a 2%
    tolerance.

    **This docstring used to say "an order of magnitude closer than on the
    act365f fixture", and that comparison is gone.** It was true when the
    act365f fixture was the MISMATCHED one, whose float leg carried the
    365/360 artefact and pushed the control's residual to ~1%. Both fixtures
    are now matched, so both are artefact-free and the residuals are the same
    order: 0.078% here against 0.105% on the GBP act365f fixture. What the
    two cases still test between them is that the control holds on either day
    count, not that one of them is broken.
    """
    analytic = (
        analytic_leg_gamma(act360_curve, act360_pkg.short)
        + analytic_leg_gamma(act360_curve, act360_pkg.long)
    )
    bumped = package_gamma(act360_curve, act360_pkg, h_bp=25.0)
    assert bumped == pytest.approx(analytic, rel=0.02)
    # ...and it is not merely inside the band, it is far inside it
    assert abs(bumped - analytic) / abs(analytic) < 0.005


def test_hard_coding_365_would_miss_on_an_act360_curve(act360_curve, act360_pkg):
    """The test that proves the daily_dcf fix rather than restating it.

    ``rl.Curve.shift``'s time exponent is ``days * d`` with ``d`` the curve's
    own 1-day DCF, so on an act360 curve a control measuring ``days/365``
    understates ``t`` by 360/365. Gamma goes as ``t**2``, so it reads
    ``(360/365)**2`` low -- deterministic, and outside the 2% band.
    """
    bumped = package_gamma(act360_curve, act360_pkg, h_bp=25.0)
    legacy = (
        _legacy_365_control(act360_curve, act360_pkg.short)
        + _legacy_365_control(act360_curve, act360_pkg.long)
    )
    assert bumped != pytest.approx(legacy, rel=0.02)
    assert (bumped - legacy) / abs(legacy) == pytest.approx(
        (365.0 / 360.0) ** 2 - 1.0, abs=0.005
    )


def test_the_fix_is_exactly_neutral_on_an_act365f_curve(curve, pkg):
    """days*d IS days/365 under act365f, so an act365f fixture must not move.

    Neutrality where the conventions already agreed is the evidence that the
    daily_dcf change corrected a convention bug rather than retuning a number.
    The claim names no number, so it is independent of WHICH act365f market the
    fixture is -- it moved from a USD-on-act365f mismatch to GBP-SONIA when
    rateslib 2.7.1 outlawed the mismatch.

    **Where the neutrality is bit-exact, and where it is not.** The fix lives
    entirely in ``t``, and there it IS bit-exact: ``daily_dcf`` returns
    ``fl(1/365)`` to the last bit on an act365f curve, and ``days * fl(1/365)``
    equals ``fl(days / 365)`` exactly for every cashflow date either fixture
    produces (checked below, per date, not assumed -- across day counts
    3000..8000 the two disagree by 1 ulp about 4.9% of the time, so this is a
    property of these dates and it is asserted rather than trusted).

    The two whole formulas then agree to ~1 ulp rather than bit-for-bit,
    because they associate the same three factors differently:
    ``greeks.analytic_leg_gamma`` accumulates ``(tau * ti) * ti * D`` while the
    control below writes ``(tau * t**2) * D``. Float multiplication is not
    associative. The previous fixture happened to round identically for its own
    day counts and the assertion was written as ``==``; that was luck, not
    identity, and it is stated as the noise floor it is. The mutation this test
    exists to catch -- ``daily_dcf`` hard-coded to 1/360 -- moves the answer by
    ``(365/360)**2 - 1 = 2.8%``, ten orders of magnitude outside the band.
    """
    handle = curve.handle()
    ref = pd.Timestamp(curve.reference_date())
    d = daily_dcf(handle)
    assert d == 1.0 / 365.0  # bit-exact: this IS the whole of the fix

    for swap in (pkg.short, pkg.long):
        for date in leg_cashflows(swap.leg1, handle)["Payment"]:
            days = (pd.Timestamp(date) - ref).days
            assert days * d == days / 365.0  # bit-exact, per date
        assert analytic_leg_gamma(curve, swap) == pytest.approx(
            _legacy_365_control(curve, swap), rel=1e-12
        )


def test_daily_dcf_is_read_off_the_curve_convention(curve, act360_curve):
    assert daily_dcf(curve.handle()) == pytest.approx(1.0 / 365.0, rel=1e-12)
    assert daily_dcf(act360_curve.handle()) == pytest.approx(1.0 / 360.0, rel=1e-12)


def test_a_curve_index_convention_mismatch_is_now_refused_outright():
    """The successor to ``test_the_act365f_fixture_pays_365_over_360_...``.

    **That test's subject no longer exists.** It pinned a fixture artefact:
    rateslib compounded the RFR off the *curve* (act365f) and then multiplied
    by the *leg's* own accrual fraction (act360, from the ``usd_irs`` spec), so
    a mismatched pair scaled the float leg by tau_leg/tau_curve = 365/360
    relative to the ``D(T0) - D(TN)`` replication. It was pinned "so it does
    not get rediscovered as a bug".

    rateslib 2.7.1 refuses that pairing instead: forecasting an act360 RFR
    index off an act365f curve raises before any number is produced. What is
    pinned here is that refusal -- the statement that would catch the pairing
    coming back.

    **The old fixture is still MEASURABLE, and here is how.** An earlier
    version of this docstring said the artefact "can no longer be measured",
    and that was wrong in a way that cost something: believing it, the repair
    DERIVED an old-fixture number instead of measuring one, and derived it
    from a mechanism that was itself wrong (see
    ``test_strikeless_vol_greeks.py::test_leg_is_sized_to_the_requested_dv01``).
    The guard lives in one function,
    ``rateslib.data.fixings._maybe_get_rate_series_from_curve``: given a rate
    curve it either builds the index FROM the curve (when no index was
    supplied) or compares conventions and raises. Pre-2.7 always took the
    first path. Monkeypatching it to do so unconditionally reconstructs the
    old fixture exactly -- it reproduces all six numbers this branch recorded
    under rateslib 2.1.1 (flat roll -24.7614, flat gamma 200.2507, flat
    breakeven 0.497297, realistic roll -1102.3859, realistic gamma 201.1952,
    realistic spread -58.1035), so the reconstruction is validated against
    values it was not fitted to.

    Do that rather than re-derive, if a pre-repair number is ever in question.

    Production was never exposed to the artefact: the only act365f curves in
    this repo are CAD-CORRA, JPY-TONAR, JPY-TONA and GBP-SONIA, and each is
    paired with a spec whose own legs are act365f -- which the loop below
    checks against ``RATESLIB_CURVE_DEFINITIONS`` rather than asserting from
    memory, because the set is easy to misremember (EUR-ESTR is act360, not
    act365f).
    """
    mismatched = _curve("USD-OIS", convention="act365f")  # act365f curve, act360 usd_irs legs
    with pytest.raises(ValueError, match="conflicting parameters"):
        build_package(mismatched, PAIR, package_dv01_usd=100_000.0, sign=FLATTENER)

    # ...and no shipped curve is in that shape: every act365f curve definition
    # names a spec whose own legs are act365f.
    act365f_curves = [
        name for name, d in RATESLIB_CURVE_DEFINITIONS.items()
        if d["DayCounter"] == "act365f"
    ]
    assert act365f_curves, "expected at least one act365f curve definition"
    for name in act365f_curves:
        d = RATESLIB_CURVE_DEFINITIONS[name]
        nodes = {REF: 1.0, rl.dt(2036, 8, 3): 0.5}
        handle = rl.Curve(nodes=nodes, convention=d["DayCounter"],
                          calendar=d["Calendar"], id=name)
        # Constructing and RATING is what triggers the check; a spec whose legs
        # were act360 would raise here exactly as the USD case above does.
        swap = rl.IRS(effective=rl.dt(2027, 8, 3), termination=rl.dt(2032, 8, 3),
                      spec=d["ReferenceRate"], curves=handle, notional=1.0,
                      **rate_fixings_kwargs(rl.NoInput(0)))
        assert float(swap.rate(curves=handle).real) != 0.0, name


def test_the_matched_act365f_fixture_needs_no_365_over_360_correction(curve, pkg):
    """The positive half of the finding above, on the matched pairing.

    The old test's own conclusion was that dividing the 365/360 ratio out left
    the float leg agreeing "to ~0.05%, which is what the matched-convention
    curve gives directly". This asserts that directly: with curve and index
    both act365f, the bumped float-leg convexity IS the ``D(T0) - D(TN)``
    replication, with no scaling factor -- so any reappearance of a ratio
    would be a real defect in the mechanic rather than a fixture artefact.

    The band is 0.5%, generous against the 365/360 = 1.0139 the mismatch used
    to produce (28x outside it) and against exact 1.0.
    """
    for swap in (pkg.short, pkg.long):
        ratio = _float_leg_gamma_bumped(curve, swap) / _float_replication(curve, swap)
        assert ratio == pytest.approx(1.0, rel=0.005)


def test_the_tau_term_is_bound_by_a_semiannual_schedule(act360_curve):
    """The annual fixture cannot tell tau from 1.0, so check on a semiannual one.

    With DCF ~= 0.507 the accrual fraction carries real weight, and replacing it
    with 1.0 throws the control ~23% -- more than ten times the band. Without
    this an edit that dropped the tau weighting would pass the whole suite.
    """
    swap = _semiannual_par_swap(act360_curve)
    handle = act360_curve.handle()
    cf = leg_cashflows(swap.leg1, handle)
    assert float(cf["DCF"].mean()) == pytest.approx(0.507, abs=0.01)

    bumped = _leg_gamma_bumped(act360_curve, swap)
    assert bumped == pytest.approx(analytic_leg_gamma(act360_curve, swap), rel=0.02)

    ref = pd.Timestamp(act360_curve.reference_date())
    d = daily_dcf(handle)
    n, k = float(act360_curve.notional(swap)), float(act360_curve.fixed_rate(swap))
    eff, mat = act360_curve.effective_date(swap), act360_curve.maturity_date(swap)
    t0 = (pd.Timestamp(eff) - ref).days * d
    tn = (pd.Timestamp(mat) - ref).days * d
    ann_tau_is_one = sum(
        1.0 * ((pd.Timestamp(r["Payment"]) - ref).days * d) ** 2
        * float(handle[pd.Timestamp(r["Payment"]).to_pydatetime()])
        for _, r in cf.iterrows()
    )
    mutant = n * (
        t0 * t0 * float(handle[eff]) - tn * tn * float(handle[mat]) - k * ann_tau_is_one
    ) * 1e-8
    assert bumped != pytest.approx(mutant, rel=0.02)


def test_flattener_convexity_is_positive(curve, pkg):
    """Receiving the longer forward against the shorter is long convexity."""
    assert package_gamma(curve, pkg, h_bp=25.0) > 0.0


def test_gamma_is_reported_per_h_not_averaged(curve, pkg):
    g = gamma_by_h(curve, pkg, h_bps=(10.0, 25.0, 50.0))
    assert set(g) == {10.0, 25.0, 50.0}
    assert all(v > 0 for v in g.values())
    # h-dependence is a property of the instrument, so it must be visible.
    # Distinct values are the assertion: if the three ever collapsed to one
    # number, convexity would have been averaged across move size, which is
    # the thing this function exists to prevent.
    assert len(set(g.values())) == 3
    spread = (max(g.values()) - min(g.values())) / max(g.values())
    assert 0.0 < spread < 0.05  # small over 10-50bp, but not zero


def test_control_bites_when_the_bump_unit_is_wrong(curve, pkg, monkeypatch):
    """Mutation check: if h were passed as a decimal instead of bp, this fails.

    A checking tool that is itself wrong reports success. This asserts the
    control can tell the difference.

    Scaling ``shift``'s argument by 1e-4 is exactly "25bp handed to an API
    that wanted a decimal": the curve moves 0.0025bp while ``package_gamma``
    still divides by ``h_bp**2 = 625``, so the bumped number lands ~1e-8 of
    the truth. The analytic side never touches ``shift``, so it is unmoved
    and the 2% band rejects the mutant.
    """
    import RVUtils.StrikelessVol.greeks as g

    def _analytic():
        return analytic_leg_gamma(curve, pkg.short) + analytic_leg_gamma(curve, pkg.long)

    before = _analytic()
    assert before != 0.0

    real_shift = rl.Curve.shift
    monkeypatch.setattr(
        rl.Curve, "shift", lambda self, spread, **kw: real_shift(self, spread * 1e-4, **kw)
    )
    # The control's independence, proved by the suite rather than by reading:
    # sabotaging shift() must leave the analytic side bit-for-bit unmoved.
    assert _analytic() == before

    bumped = g.package_gamma(curve, pkg, h_bp=25.0)
    assert bumped != pytest.approx(before, rel=0.02)


def test_bp_read_as_a_decimal_cannot_even_be_repriced(curve, pkg, monkeypatch):
    """The same 1e4 unit error in the other direction.

    Scaling ``shift``'s argument *up* by 1e4 asks rateslib for a 250,000bp
    parallel bump, and it raises ``OverflowError`` while building the shifted
    curve (``rateslib/curves/curves.py:960``) rather than handing back a
    wrong number. Asserted explicitly so that direction of the mutation is
    on record as caught rather than silently skipped.
    """
    import RVUtils.StrikelessVol.greeks as g

    real_shift = rl.Curve.shift
    monkeypatch.setattr(
        rl.Curve, "shift", lambda self, spread, **kw: real_shift(self, spread * 1e4, **kw)
    )
    with pytest.raises(OverflowError):
        g.package_gamma(curve, pkg, h_bp=25.0)
