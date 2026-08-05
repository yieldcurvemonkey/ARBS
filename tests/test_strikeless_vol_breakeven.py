# tests/test_strikeless_vol_breakeven.py
import math

import pandas as pd
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.greeks import (
    breakeven_bp_day,
    build_package,
    compute_greeks,
    daily_roll_usd,
    greeks_panel,
    package_dv01,
    package_npv,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

REF = rl.dt(2026, 8, 3)
PAIR = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))


def _flat_curve(ref=REF):
    """Flat 4%: the true-zero-roll sanity baseline."""
    nodes = {ref: 1.0}
    for y in range(1, 41):
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / (1.04 ** y)
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="c")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        # rateslib 2.1.1 raises IndexError inside _set_fixings on an empty
        # pd.Series and fails later at .npv() with fixings=None; only the
        # NoInput sentinel works. See tests/test_strikeless_vol_greeks.py.
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


def _stress_curve(ref=REF, slope=-0.5):
    """PATHOLOGICAL stress fixture -- NOT a curve that could exist.

    Flat 4% out to y=10, then a LINEAR ramp with a first-derivative KINK
    exactly at y=10 (which is also the short leg's own effective date).
    ``slope=-0.5`` takes rates from +4% at 10y to -11% at 40y, with discount
    factors above 100 and implied instantaneous forwards to -31%.

    Kept only for two things a realistic fixture cannot demonstrate: (1) the
    ``translate`` finding (a mathematical identity, true on any par-struck
    curve, so the extremity doesn't matter there), and (2) as a documented
    negative example -- see ``test_stress_fixture_roll_is_unstable``. A round
    of independent review found that ``daily_roll_usd`` computed on THIS
    fixture, panelled across consecutive economically-static calendar dates,
    is wildly unstable (roll -676, +9557, +9384, +811, +7945 across 5
    business days on a spread that itself moves <0.1%) and even flips sign.
    Root cause (investigated, not just observed): shortening the horizon to
    exactly 1 calendar day (see the realistic fixture and Item 1 of the
    correction round) does not fix it -- what fixes it is removing the
    first-derivative kink at y=10 (replacing it with a smooth, C1-continuous
    transition; see ``_realistic_curve``). A curve this shaped is not
    something the module's roll story can be trusted on, which is the whole
    point of keeping it here as the labelled stress case rather than as
    the source of any headline number.
    """
    nodes = {ref: 1.0}
    for y in range(1, 41):
        r = 0.04 + slope * max(0.0, y - 10) / 100.0
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / ((1.0 + r) ** y)
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="c")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


def _realistic_curve(ref=REF, a=7.4e-6):
    """The headline fixture: flat 4% out to y=10, then a SMOOTH (C1-continuous
    at y=10 -- no kink) quadratic inversion beyond, ``r(y) = 0.04 - a*(y-10)^2``
    for y>10. Calibrated (``a=7.4e-6``) to the real USD 10y10y/20y10y level:
    desk print was -60.4bp on 2026-07-31 and -57.3bp on 2026-08-03; this
    fixture gives -58.10bp. Rates stay positive everywhere out to y=40
    (minimum ~3.33%), unlike the stress fixture.

    The smoothness is not cosmetic. The same slope magnitude on the KINKED
    (``_stress_curve``-style, non-smooth) shape was tried first and was
    STILL unstable panel-to-panel (roll flipped sign, swinging roughly
    -36 to +895 across 5 business days) even with realistic rates and the
    Item-1 calendar-day horizon fix already applied -- extremity of slope was
    not the destabilising factor, the first-derivative discontinuity at y=10
    (exactly the short leg's own effective date) was. Removing it (this
    function) gives a roll that is stable in sign and within ~34% of itself
    across 10 business days -- see
    ``test_realistic_fixture_roll_is_stable_across_consecutive_dates``.
    """
    nodes = {ref: 1.0}
    for y in range(1, 41):
        excess = max(0.0, y - 10)
        r = 0.04 - a * excess * excess
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / ((1.0 + r) ** y)
    handle = rl.Curve(nodes=nodes, convention="act365f", calendar="nyc", id="c")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


def test_breakeven_formula():
    # 2 * |roll| / gamma, square-rooted
    assert breakeven_bp_day(-800.0, 100.0) == pytest.approx(math.sqrt(16.0))


def test_breakeven_is_nan_when_convexity_is_non_positive():
    assert math.isnan(breakeven_bp_day(-800.0, 0.0))
    assert math.isnan(breakeven_bp_day(-800.0, -5.0))


def test_daily_roll_is_a_shape_preserving_curve_roll_not_a_maturity_shortening():
    """``daily_roll_usd`` holds the package's own dates fixed and slides the
    curve's *shape* forward (``rl.Curve.roll``) -- not a reprice against a
    curve whose OWN maturity/final node has been shortened, which would pick
    up a duration/convexity distortion unrelated to genuine roll-down.
    """
    curve = _realistic_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    next_date = curve.reference_date() + pd.Timedelta(days=1)
    roll = daily_roll_usd(curve, pkg, next_date=next_date)
    assert roll != 0.0
    assert abs(roll) < 100_000.0  # one day of carry cannot be a bp of DV01


def test_translate_yields_no_carry_for_a_par_struck_forward_package():
    """Pins the finding that changed the mechanic: ``rl.Curve.translate`` is
    the wrong primitive for this module's roll-down, kept as a permanent
    record rather than deleted now that ``daily_roll_usd`` no longer calls it.

    ``rl.curves.curves.TranslatedCurve.__getitem__`` returns
    ``self.obj[date] / self.obj[self.nodes.initial]`` -- a pure per-date
    rescale by one constant. NPV is linear (homogeneous degree 1) in the
    discount factors it queries, so a package whose legs are struck exactly
    at par (NPV == 0.0 on the original curve, confirmed below) reprices to
    0.0 again under ANY translate horizon, for ANY curve shape, as long as
    the new valuation date stays before the package's first cashflow --
    confirmed empirically from 1 day out to 9 years (both legs start
    10-20y forward), and true regardless of whether the curve is realistic
    or pathological, since the argument never touches curve shape. Uses the
    realistic fixture here precisely to demonstrate that: this isn't a
    quirk of the stress curve.
    """
    curve = _realistic_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    # Struck exactly at par, up to the same float noise floor (~1e-8) this
    # whole test is about -- the quadratic fixture's NPV isn't bit-exact 0.0
    # the way the piecewise-linear fixtures are, but it's the same order of
    # magnitude noise, not a real residual.
    assert package_npv(curve.handle(), pkg) == pytest.approx(0.0, abs=1e-6)

    next_date = curve.reference_date() + pd.Timedelta(days=1)
    translated = curve.handle().translate(next_date)
    roll_via_translate = package_npv(translated, pkg) - package_npv(curve.handle(), pkg)
    # A real one-day bleed on a $100k/bp package is materially larger (this
    # fixture's roll()-based daily_roll_usd measures -1102.39); 1e-3 is
    # generous headroom above the ~1e-7 noise floor actually observed while
    # still being far below any economically plausible carry number.
    assert abs(roll_via_translate) < 1e-3


def test_horizon_defaults_to_exactly_one_calendar_day():
    """``compute_greeks``'s default horizon must not vary with the calendar.

    The original default (``calendar_advance(ref, "1b")``, one BUSINESS day)
    spans 1 calendar day midweek but 3 over a weekend and 4 over a
    holiday-adjacent Friday -- while ``breakeven_by_h`` is labelled and
    consumed as bp/day. A real panel showed every Friday row inflated by
    ~sqrt(3) purely from the horizon, nothing economic. ``rl.Curve.roll``
    slides the curve's shape forward in time; a weekend is not a market
    convention it needs to respect, so the fix is to roll by exactly one
    calendar day regardless of what day of the week ``today`` is.
    """
    friday = rl.dt(2026, 8, 7)
    curve = _realistic_curve(ref=friday)
    g_default = compute_greeks(curve, PAIR)
    g_explicit_1d = compute_greeks(curve, PAIR, next_date=friday + pd.Timedelta(days=1))
    g_explicit_3d_1b = compute_greeks(curve, PAIR, next_date=friday + pd.Timedelta(days=3))

    assert g_default.daily_roll_usd == pytest.approx(g_explicit_1d.daily_roll_usd)
    # The default must NOT match the old "1b" business-day-advance behaviour
    # (which on a Friday would have landed on the following Monday, 3
    # calendar days later) -- confirms the fix actually changed the default,
    # not just that it still happens to agree by coincidence.
    assert g_default.daily_roll_usd != pytest.approx(g_explicit_3d_1b.daily_roll_usd)


def test_realistic_curve_flattener_bleeds():
    """The headline sign check, on a curve that could exist."""
    curve = _realistic_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    next_date = curve.reference_date() + pd.Timedelta(days=1)
    assert daily_roll_usd(curve, pkg, next_date=next_date) < 0.0


def test_realistic_curve_roll_is_materially_negative_not_merely_negative():
    """A real bleed, not a rounding artifact: of a size that could plausibly
    fund the day's convexity gain (Gamma ~201 $/bp^2 on this fixture ->
    breakeven in the low single-digit bp/day range, not micro-bp).
    """
    curve = _realistic_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    next_date = curve.reference_date() + pd.Timedelta(days=1)
    roll = daily_roll_usd(curve, pkg, next_date=next_date)
    assert roll < -500.0  # measured -1102.39; generous headroom below that


def test_flat_curve_roll_is_near_zero():
    """The sanity check that ``roll`` is measuring curve SHAPE, not something
    else: with no inversion there is nothing to bleed, so roll should be tiny
    relative to the materially-negative inverted case above (~44x smaller).
    """
    curve = _flat_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    next_date = curve.reference_date() + pd.Timedelta(days=1)
    roll = daily_roll_usd(curve, pkg, next_date=next_date)
    assert abs(roll) < 100.0  # measured -24.76


def test_flat_curve_breakeven_is_small():
    """The true answer on a flat curve is a breakeven of 0 (nothing to fund).
    ``daily_roll_usd`` is not exactly 0 on this fixture (-$24.76, see above --
    a residual of the same repriced-DV01-vs-fair-rate-sensitivity kind Task 8
    already documents), so the breakeven it implies is not exactly 0 either.
    This pins it as small, not as an unexplained nonzero number.
    """
    curve = _flat_curve()
    g = compute_greeks(curve, PAIR)
    assert 0.0 < g.breakeven_by_h[25.0] < 1.0  # measured 0.497


def test_realistic_fixture_roll_is_stable_across_consecutive_dates():
    """Item 3: prove stability rather than assume it, and let the answer be
    the answer. Ten consecutive BUSINESS days (skipping the weekend), each
    a freshly-built curve anchored to that day with the SAME economic shape
    (``a`` unchanged) -- an "economically static" market by construction:
    spread moves <0.1%, Gamma <0.2%.

    On this realistic fixture the roll is stable: negative on every day,
    and the largest magnitude is within ~34% of the smallest (measured
    range -1472.36 to -1102.39; the assertion below uses a 2x band for
    headroom). Per the brief: if this had NOT held, the fixture would not
    have been tuned until it did -- it would have been reported as a finding
    that the package roll cannot be measured this way. It holds here.
    """
    dates = [rl.dt(2026, 8, d) for d in (3, 4, 5, 6, 7, 10, 11, 12, 13, 14)]
    curve_map = {pd.Timestamp(d): _realistic_curve(ref=d) for d in dates}
    panel = greeks_panel(curve_map, PAIR)

    assert len(panel) == len(dates)
    assert panel["spread_bp"].std() / panel["spread_bp"].abs().mean() < 0.01  # <1%: static
    assert panel["gamma_h25"].std() / panel["gamma_h25"].mean() < 0.01  # <1%: static

    roll = panel["daily_roll_usd"]
    assert (roll < 0.0).all()
    assert roll.abs().max() / roll.abs().min() < 2.0


def test_stress_fixture_roll_is_unstable_do_not_trust_a_single_reading():
    """The negative-space companion to the stability test above: documents,
    rather than hides, that the pathological fixture's roll does NOT share
    this stability -- which is exactly why it must not be used for headline
    numbers, and why ``test_realistic_curve_flattener_bleeds`` above uses the
    realistic fixture instead of this one.
    """
    dates = [rl.dt(2026, 8, d) for d in (3, 4, 5, 6, 7, 10, 11, 12, 13, 14)]
    curve_map = {pd.Timestamp(d): _stress_curve(ref=d) for d in dates}
    panel = greeks_panel(curve_map, PAIR)

    roll = panel["daily_roll_usd"]
    assert not ((roll < 0.0).all() or (roll > 0.0).all())  # sign is not stable
    assert roll.abs().max() / roll.abs().min() > 5.0  # and neither is magnitude


def test_repo_bps_running_cross_check():
    """Cross-check against ``RLIRSwapCurve.carry_and_roll_bps_running``,
    reported as an investigated finding rather than a clean pass/fail gate.

    **The per-leg "sign flip" this test originally asserted was spurious.**
    ``roll_bps_running(swap, horizon)`` is defined as
    ``fair(orig) - fair(shortened)`` -- i.e. exactly
    ``-(fair(shortened) - fair(orig))``. Comparing it directly (unnegated)
    against this module's "aging" bp-equivalent (``leg_roll_usd / leg_dv01``,
    itself unrelated in sign convention to a shortening-based diff) produces
    a sign flip PER LEG purely from that subtraction-order mismatch, whenever
    both mechanics move the fair rate the same way -- which they do here
    (e.g. short leg: aging +0.2816 vs -roll_bps_running +0.5153; long leg:
    +0.2884 vs +0.2495 -- once ``roll_bps_running`` is negated to the same
    orientation, both legs agree). That per-leg "agreement" (or the
    previous version's "disagreement") is guaranteed by algebra, not
    independent corroboration of anything -- it holds regardless of whether
    the two mechanics actually measure the same economics.

    **The only apples-to-apples comparison is at the package level**, and
    even that is not a stable finding here. Correcting the combination
    formula for the same subtraction-order issue (package repo measure =
    ``short_cr - long_cr``, not the original ``long_cr - short_cr``) makes
    the two agree in sign on 2026-08-03 (roll_bp_equiv -0.0110 vs corrected
    repo -0.0058, same sign, ~1.9x apart in magnitude -- the kind of
    "genuine divergence in magnitude" a clean finding would look like).
    **But it does not hold on other dates**: checked on 2026-08-04, 08-06 and
    on the flat fixture, the corrected package-level comparison's sign
    flips back and forth relative to ``daily_roll_usd``'s. The most likely
    explanation (not yet confirmed): ``roll_bps_running`` shortens the
    maturity via ``calendar_advance(..., "-1b")`` -- a BUSINESS-day tenor,
    internal to ``RLIRSwapCurve`` and outside this module's ownership --
    which may carry the same weekday-dependent horizon instability Item 1
    fixed in ``daily_roll_usd`` itself, uncorrected here. This is reported,
    not resolved: the repo's ``carry_and_roll_bps_running`` should not
    currently be treated as an independent oracle for ``daily_roll_usd``,
    in either direction.
    """
    curve = _realistic_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    next_date = curve.reference_date() + pd.Timedelta(days=1)

    roll_usd = daily_roll_usd(curve, pkg, next_date=next_date)
    pkg_dv01_target = 100_000.0
    roll_bp_equiv = roll_usd / pkg_dv01_target

    short_cr = curve.carry_and_roll_bps_running(pkg.short, "1b")
    long_cr = curve.carry_and_roll_bps_running(pkg.long, "1b")
    repo_bp_running = short_cr - long_cr  # corrected combination, see docstring

    # What IS robust (an algebraic identity, not a fixture-dependent
    # finding): per leg, the "aging" bp-equivalent and the NEGATED
    # roll_bps_running always share sign here -- this is the mechanism
    # behind the spurious "corroboration" the original version of this test
    # mistook for evidence.
    handle = curve.handle()
    for swap, dv01_sign in ((pkg.short, +1.0), (pkg.long, -1.0)):
        base = swap.npv(curves=handle).real
        rolled = swap.npv(curves=handle.roll(next_date)).real
        leg_roll_usd = rolled - base
        leg_bp_equiv = leg_roll_usd / (dv01_sign * pkg_dv01_target)
        leg_rr = curve.roll_bps_running(swap, "1b")
        assert (leg_bp_equiv > 0.0) == (-leg_rr > 0.0)

    # The package-level comparison is reported (see docstring) rather than
    # asserted to agree -- it does not, robustly, across dates. What IS
    # asserted: both numbers are finite and nonzero, so the comparison in
    # the docstring is reproducible, not vacuous.
    assert roll_bp_equiv != 0.0
    assert repo_bp_running != 0.0


def test_compute_greeks_returns_a_full_labelled_record():
    curve = _realistic_curve()
    next_date = curve.reference_date() + pd.Timedelta(days=1)
    g = compute_greeks(curve, PAIR, next_date=next_date)
    assert g.pair_name == "USD 10Y10Y/20Y10Y"
    assert g.spread_bp < 0.0  # inverted
    assert set(g.gamma_by_h) == {10.0, 25.0, 50.0}
    assert set(g.breakeven_by_h) == {10.0, 25.0, 50.0}
    assert g.breakeven_by_h[25.0] > 0.0
    # Sizing each leg on its own repriced DV01 (central difference, matching
    # the measure package_dv01 checks) rather than the analytic annuity
    # (curve.pv01) makes the package neutral in the measure that matters by
    # construction: measured residual is 0.0 (float-exact) on this fixture.
    assert abs(g.package_dv01) == pytest.approx(0.0, abs=10.0)


def test_greeks_panel_is_one_row_per_date():
    curve_map = {
        pd.Timestamp("2026-08-03"): _realistic_curve(),
        pd.Timestamp("2026-08-04"): _realistic_curve(ref=rl.dt(2026, 8, 4)),
    }
    panel = greeks_panel(curve_map, PAIR)
    assert len(panel) == 2
    assert "breakeven_h25" in panel.columns
    assert "gamma_h25" in panel.columns
    assert "daily_roll_usd" in panel.columns
