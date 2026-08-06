# tests/test_strikeless_vol_breakeven.py
import math

import pandas as pd
import pytest
import rateslib as rl

from RVUtils.StrikelessVol.greeks import (
    analytic_leg_gamma,
    breakeven_bp_day,
    build_package,
    compute_greeks,
    daily_roll_usd,
    greeks_panel,
    package_dv01,
    package_gamma,
    package_npv,
)
from RVUtils.StrikelessVol.universe import ForwardLeg, ForwardPair
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
from utils.rl_compat import leg_cashflows, rate_fixings_kwargs

REF = rl.dt(2026, 8, 3)
PAIR = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))

# Every fixture here is act360 -- the DayCounter ``rl_curve_definitions_map``
# gives USD-OIS, and the convention the ``usd_irs`` legs these curves price
# already carried. They were act365f until rateslib 2.7.1, which refuses to
# forecast an act360 RFR index off an act365f curve at all.
#
# WHY EVERY MEASURED NUMBER BELOW MOVED. TWO factors changed, not one, and
# which of them cancels where is the whole content of this note.
#
#   d  the curve's own 1-day DCF. ``rl.Curve.shift`` applies its bp at time
#      exponent ``days * d`` (see ``greeks.daily_dcf``), so an act360 curve
#      moves 365/360 further per nominal bp -- measured straight off discount
#      factors, log-DF ratio 1.01388889 against 365/360 = 1.01388889.
#   A  a uniform multiplier on the whole swap PV, present ONLY on the old
#      mismatched fixture: the float leg was forecast off the act365f curve
#      and then multiplied by the act360 leg accrual, so PV carried
#      ``A = tau_leg/tau_curve = 365/360`` (measured 1.013889 on both legs).
#      A = 1 once the conventions match.
#
# Every package here is normalised to $100k of REPRICED DV01, and that unit
# DV01 goes as ``A * d``. So
#
#     N = 1e5 / (A*d*...)     A*d is 1/360 in BOTH worlds  ->  N INVARIANT
#     roll, breakeven ~ N*A   ~ 1/d   ->  x 360/365 = 0.986301
#     gamma           ~ N*A*d^2 ~ d   ->  x 365/360 = 1.013889
#     pv01            ~ N              ->  UNCHANGED
#
# The earlier version of this note said "the notional absorbs it, N scales by
# 360/365". That gets roll and gamma right for the wrong reason and predicts a
# pv01 move that does not happen. Measured: notional 172,988,501.32 (act365f)
# vs 172,988,495.98 (act360), ratio 1.00000003. See
# ``test_strikeless_vol_greeks.py::test_leg_is_sized_to_the_requested_dv01``.
#
# The arithmetic every re-measured number obeys, against the old fixture
# RECONSTRUCTED under rateslib 2.7.1 (not merely against values recorded under
# an older rateslib -- see ``test_strikeless_vol_greeks_control.py`` for how,
# and note the reconstruction reproduces all six recorded numbers, so these
# ratios carry no upgrade drift):
#
#   realistic roll   -1102.3859 -> -1087.2845   ratio 0.9862993
#   flat roll           -24.7614 ->   -24.4222  ratio 0.9862994
#   flat breakeven        0.497297 ->  0.490476 ratio 0.9862831
#   realistic gamma     201.1952 ->  203.9967   ratio 1.0139239
#   flat gamma          200.2507 ->  203.0391   ratio 1.0139245
#   realistic spread     -58.1035 ->  -57.3075  ratio 0.9863007
#
# -- every one of them 360/365 or 365/360 to 6 s.f. Each number is
# additionally confirmed by a route that does not go through this module --
# named in the docstring that quotes it.


def _flat_curve(ref=REF):
    """Flat 4%: the true-zero-roll sanity baseline."""
    nodes = {ref: 1.0}
    for y in range(1, 41):
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / (1.04 ** y)
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id="c")
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
    transition; see ``_realistic_curve``). On act360 those five readings are
    -667, +9426, +9255, +800, +7836 (they were -676, +9557, +9384, +811,
    +7945 on act365f -- a uniform ~1.4% shift, the convention's whole effect;
    the instability is unchanged and is the point). A curve this shaped is not
    something the module's roll story can be trusted on, which is the whole
    point of keeping it here as the labelled stress case rather than as
    the source of any headline number.
    """
    nodes = {ref: 1.0}
    for y in range(1, 41):
        r = 0.04 + slope * max(0.0, y - 10) / 100.0
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / ((1.0 + r) ** y)
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id="c")
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
    fixture gives **-57.31bp** on act360 (it gave -58.10bp on act365f).
    Rates stay positive everywhere out to y=40 (minimum ~3.33%), unlike the
    stress fixture.

    The move from -58.10 to -57.31 is **arithmetic, not corroboration**: it is
    the 360/365 multiplier this file's block comment derives, applied to a
    number that was already there (-58.1035 x 0.9863007 = -57.3075). It lands
    nearer the desk print than the old value did, and that is a coincidence of
    which direction the multiplier pointed -- nothing about the act360 fixture
    is better calibrated than the act365f one was. An earlier version of this
    docstring presented the closer agreement as confirmation; it is not, and
    the honest reading is that ``a`` has simply never been re-fitted.

    What IS an independent check on the level is reading the par forward rate
    off the curve's own nodes, ``(D(T0) - D(TN)) / sum_i tau_i D(Ti)``, which
    gives -57.34bp against the pricer's -57.31bp -- agreement to 0.03bp
    between two routes, which says the pricer is reading the fixture right.
    It says nothing about whether the fixture matches the market.

    The smoothness is not cosmetic. The same slope magnitude on the KINKED
    (``_stress_curve``-style, non-smooth) shape was tried first and was
    STILL unstable panel-to-panel (roll flipped sign, swinging roughly
    -36 to +895 across 5 business days) even with realistic rates and the
    Item-1 calendar-day horizon fix already applied -- extremity of slope was
    not the destabilising factor, the first-derivative discontinuity at y=10
    (exactly the short leg's own effective date) was. Removing it (this
    function) gives a roll that is stable in sign and within ~34% of itself
    across 10 business days (measured on act360: 33.6%) -- see
    ``test_realistic_fixture_roll_is_stable_across_consecutive_dates``.
    """
    nodes = {ref: 1.0}
    for y in range(1, 41):
        excess = max(0.0, y - 10)
        r = 0.04 - a * excess * excess
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / ((1.0 + r) ** y)
    handle = rl.Curve(nodes=nodes, convention="act360", calendar="nyc", id="c")
    return RLIRSwapCurve(
        rl_curve_id="USD-OIS",
        rl_curve_handle=handle,
        fixings=rl.NoInput(0),
        meta_data={"reference_curve_name": "USD-OIS"},
    )


def _roll_by_annuity_identity(curve, pkg, next_date) -> float:
    """The package's roll, by a route that touches none of ``greeks``' arithmetic.

    A swap struck at ``k`` on the base curve has PV ``N*(fair_new - k)*A_new``
    on ANY other curve, by the definition of the fair rate. Each leg here is
    struck at par on the base curve, so the package's roll is just that
    expression summed over the two legs, evaluated on the ROLLED curve --
    ``fair`` from ``rl.IRS.rate()``, the annuity from the rolled curve's own
    discount factors. No ``npv()``, no ``shift()``, no ``daily_roll_usd``.
    """
    handle = curve.handle()
    rolled = handle.roll(next_date)

    def pv_on(disc):
        total = 0.0
        for swap in (pkg.short, pkg.long):
            cf = leg_cashflows(swap.leg1, handle)
            eff = pd.Timestamp(cf["Acc Start"].min()).to_pydatetime()
            mat = pd.Timestamp(cf["Acc End"].max()).to_pydatetime()
            notional = float(curve.notional(swap))
            struck_pct = float(swap.fixed_rate)  # rateslib unit: percent
            twin = rl.IRS(effective=eff, termination=mat, spec="usd_irs",
                          curves=disc, notional=notional,
                          **rate_fixings_kwargs(rl.NoInput(0)))
            fair_pct = float(twin.rate(curves=disc).real)
            annuity = sum(
                float(r["DCF"]) * float(disc[pd.Timestamp(r["Payment"]).to_pydatetime()])
                for _, r in cf.iterrows()
            )
            total += notional * (fair_pct - struck_pct) / 100.0 * annuity
        return total

    return pv_on(rolled) - pv_on(handle)


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
    # fixture's roll()-based daily_roll_usd measures -1087.28 on act360);
    # 1e-3 is generous headroom above the ~5e-8 noise floor actually observed
    # while still being far below any economically plausible carry number.
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
    fund the day's convexity gain (Gamma ~204 $/bp^2 on this fixture ->
    breakeven in the low single-digit bp/day range, not micro-bp).

    Both numbers confirmed off the pricing path. Gamma: ``analytic_leg_gamma``
    -- the closed-form second derivative of the single-curve replication, the
    Task 8 control -- gives 203.80 against the repriced 204.00, 0.095% apart
    (the control's own agreement band is 2%, and Task 13's measured net
    convexity anchor is ~200 $/bp^2). Roll: for a leg struck at ``k`` on the
    base curve, its PV on the rolled curve is exactly
    ``N * (fair_rolled - k) * A_rolled``; summing that over the two legs, with
    ``fair`` from ``IRS.rate()`` and the annuity ``A`` from the rolled curve's
    own discount factors -- no ``npv()``, none of this module's arithmetic --
    reproduces -1087.2845 to printed precision on all three fixtures.
    """
    curve = _realistic_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    next_date = curve.reference_date() + pd.Timedelta(days=1)
    roll = daily_roll_usd(curve, pkg, next_date=next_date)
    assert roll < -500.0  # measured -1087.2845 (act365f gave -1102.3859)

    # The annuity identity, computed here rather than quoted: this PINS the
    # roll without hard-coding it, so it is a derivation check and not a
    # baseline. A re-baselined literal would agree with whatever the code
    # emits; this disagrees unless the two routes really coincide.
    assert roll == pytest.approx(_roll_by_annuity_identity(curve, pkg, next_date),
                                 rel=1e-9)

    # ...and gamma against the Task 8 closed form, on the fixture the headline
    # number is quoted from (the control file checks the flat and GBP ones).
    gamma = package_gamma(curve, pkg, h_bp=25.0)
    analytic = (analytic_leg_gamma(curve, pkg.short)
                + analytic_leg_gamma(curve, pkg.long))
    assert gamma == pytest.approx(analytic, rel=0.02)
    assert abs(gamma - analytic) / abs(analytic) < 0.005  # measured 0.00095


def test_the_realistic_fixture_is_still_the_calibrated_one():
    """``a`` must stay load-bearing, or the fixture drifts off its own premise.

    ``_realistic_curve``'s whole claim is that ``a=7.4e-6`` reproduces the real
    USD 10y10y/20y10y level (-57.34bp on 2026-08-03, Task 4's measured desk
    print, which this fixture is anchored to). Nothing asserted that. A review
    mutation moving ``a`` to 7.6e-6 SURVIVED the entire suite for exactly that
    reason -- every other assertion here is a sign, an inequality with orders
    of headroom, or a ratio the fixture scale cancels out of.

    Band chosen from the measured sensitivity, not tuned to pass: the fixture
    lands 0.03bp from the desk print, and ``a`` moves the spread about
    7.8bp per 1e-6, so 7.5e-6 gives -58.08 (0.74bp out) and 7.6e-6 gives
    -58.86 (1.52bp out). A 0.5bp band is ~17x the achieved residual and still
    catches both.

    This pins the CALIBRATION against an external datum -- it is not a
    re-baseline, because the target is the desk print rather than whatever the
    code emits.
    """
    desk_bp = -57.34
    g = compute_greeks(_realistic_curve(), PAIR)
    assert g.spread_bp == pytest.approx(desk_bp, abs=0.5)  # measured -57.3075


def test_flat_curve_roll_is_near_zero():
    """The sanity check that ``roll`` is measuring curve SHAPE, not something
    else: with no inversion there is nothing to bleed, so roll should be tiny
    relative to the materially-negative inverted case above (~44x smaller;
    measured 1087.28 / 24.42 = 44.5x, and it was 44.5x on act365f too -- the
    convention shifts both by the same 1.4% and cancels out of the ratio).
    """
    curve = _flat_curve()
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    next_date = curve.reference_date() + pd.Timedelta(days=1)
    roll = daily_roll_usd(curve, pkg, next_date=next_date)
    # measured -24.4222 (act365f gave -24.76); confirmed to printed precision
    # by the annuity identity described in the test above.
    assert abs(roll) < 100.0


def test_flat_curve_breakeven_is_small():
    """The true answer on a flat curve is a breakeven of 0 (nothing to fund).
    ``daily_roll_usd`` is not exactly 0 on this fixture (-$24.42, see above --
    a residual of the same repriced-DV01-vs-fair-rate-sensitivity kind Task 8
    already documents), so the breakeven it implies is not exactly 0 either.
    This pins it as small, not as an unexplained nonzero number.

    0.490 is DERIVED, not observed: ``breakeven_bp_day`` is
    ``sqrt(2|roll| / gamma)`` and ``sqrt(2 * 24.4222 / 203.0391) = 0.490476``
    exactly reproduces it from two numbers each confirmed independently above.
    """
    curve = _flat_curve()
    g = compute_greeks(curve, PAIR)
    assert 0.0 < g.breakeven_by_h[25.0] < 1.0  # measured 0.490 (act365f: 0.497)


def test_realistic_fixture_roll_is_stable_across_consecutive_dates():
    """Item 3: prove stability rather than assume it, and let the answer be
    the answer. Ten consecutive BUSINESS days (skipping the weekend), each
    a freshly-built curve anchored to that day with the SAME economic shape
    (``a`` unchanged) -- an "economically static" market by construction:
    spread moves <0.1%, Gamma <0.2%.

    On this realistic fixture the roll is stable: negative on every day,
    and the largest magnitude is within ~34% of the smallest (measured
    range -1452.19 to -1087.28 on act360, ratio 1.336; act365f gave
    -1472.36 to -1102.39, ratio 1.336 -- the SAME ratio, because the
    convention scales every day by the same 1.4% and cancels. That
    invariance is the confirmation: the assertion is on a ratio, and the
    ratio did not move at all. The assertion below uses a 2x band for
    headroom.) Per the brief: if this had NOT held, the fixture would not
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
    (short leg: aging +0.0099 vs -roll_bps_running +0.0123; long leg:
    +0.0207 vs +0.0066 -- once ``roll_bps_running`` is negated to the same
    orientation, both legs agree). That per-leg "agreement" (or the
    previous version's "disagreement") is guaranteed by algebra, not
    independent corroboration of anything -- it holds regardless of whether
    the two mechanics actually measure the same economics.

    **Those four per-leg numbers used to be the wrong fixture's, and that was
    not caused by the act360 move.** They were previously quoted as
    "+0.2816 / +0.5153 / +0.2884 / +0.2495". Measured on ``_stress_curve``
    (act360) they are +0.2778 / +0.5082 / +0.2845 / +0.2461 -- the same
    numbers up to the 1.4% the convention is worth -- while this test's body
    runs on ``_realistic_curve``, which gives the values now quoted, ~28x
    smaller. ``c0aa20fc`` switched the body from the kinked curve to the
    realistic one and carried the old fixture's readings into the new
    docstring. Nothing failed, because the assertion is a sign check that
    holds on both. Re-measured here on the fixture the test actually runs.

    **The only apples-to-apples comparison is at the package level**, and
    even that is not a stable finding here. Correcting the combination
    formula for the same subtraction-order issue (package repo measure =
    ``short_cr - long_cr``, not the original ``long_cr - short_cr``) makes
    the two agree in sign on 2026-08-03 (roll_bp_equiv -0.0109 vs corrected
    repo -0.0057, same sign, ~1.9x apart in magnitude -- the kind of
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


class _UnpriceableCurve:
    """A curve that raises wherever ``compute_greeks`` first touches it."""

    def __init__(self, message="synthetic pricing failure"):
        self._message = message

    def __getattr__(self, name):
        def _raise(*_args, **_kwargs):
            raise ValueError(self._message)
        return _raise


def test_greeks_panel_records_what_it_dropped_instead_of_silently_losing_it():
    """One bad date must not lose the panel, but it must not vanish either.

    The swallow is deliberate -- a provider gap on one day should not cost the
    other nine -- so what closes the hole is the record, not a refusal.
    """
    curve_map = {
        pd.Timestamp("2026-08-03"): _realistic_curve(),
        pd.Timestamp("2026-08-04"): _UnpriceableCurve("no curve for this date"),
        pd.Timestamp("2026-08-05"): _realistic_curve(ref=rl.dt(2026, 8, 5)),
    }
    panel = greeks_panel(curve_map, PAIR)

    assert len(panel) == 2
    assert panel.attrs["dates_in"] == 3
    assert panel.attrs["n_dropped"] == 1
    assert list(panel.attrs["dropped"]) == [pd.Timestamp("2026-08-04")]
    # the reason survives, not just the fact
    assert "no curve for this date" in panel.attrs["dropped"][pd.Timestamp("2026-08-04")]


def test_greeks_panel_raises_when_no_date_prices_at_all():
    """The failure mode this exists for, reproduced deliberately.

    When rateslib 2.7.1 began refusing this module's fixtures, EVERY date
    failed, ``rows`` came back empty and the caller saw
    ``KeyError: "None of ['date'] are in the columns"`` from ``set_index`` --
    a missing-column message for a convention conflict nine frames down. A
    systematic failure must say so, and must carry the real exception.
    """
    curve_map = {
        pd.Timestamp("2026-08-03"): _UnpriceableCurve("convention conflict"),
        pd.Timestamp("2026-08-04"): _UnpriceableCurve("convention conflict"),
    }
    with pytest.raises(ValueError, match="priced 0 of 2 dates") as excinfo:
        greeks_panel(curve_map, PAIR)
    # the original cause is attached, not discarded
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert "convention conflict" in str(excinfo.value.__cause__)
    # ...and it is emphatically not the old KeyError about a 'date' column
    assert not isinstance(excinfo.value, KeyError)


def test_greeks_panel_is_empty_not_raising_when_there_were_no_candidates():
    """No dates offered is not a systematic failure -- there was nothing to fail.

    Guards the refusal against firing on an empty or all-``None`` curve map,
    which is a caller passing nothing rather than a pipeline breaking.
    """
    assert len(greeks_panel({}, PAIR)) == 0
    assert len(greeks_panel({pd.Timestamp("2026-08-03"): None}, PAIR)) == 0


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


@pytest.mark.network
@pytest.mark.slow
def test_real_usd_curve_daily_roll_is_stable_and_negative():
    """Item 4: settle it on real data. Nothing before this test ran on a
    real curve -- everything else in this module is a synthetic fixture.

    USD 10y10y/20y10y, real GSQUANT-RL ``USD-OIS`` curves,
    2026-07-20..2026-08-03 (business days only; the provider drops
    weekends/holidays and this test does not force them). Measured (this
    exact pull, reproducible -- these are historical dates):

    - ``spread_bp`` ranges -54.9 to -60.4bp (2026-07-31: -60.4bp,
      2026-08-03: -57.3bp -- matches the desk levels
      ``test_real_usd_panel_matches_desk_levels`` independently pins).
    - ``daily_roll_usd`` ranges -$2,448.05 to -$2,335.71 across all 11
      business days: negative on EVERY day, std/mean = 1.5%.
    - ``breakeven_h25`` ranges 4.78 to 4.90 bp/day, essentially flat.

    **The answer to Item 4's question is: yes, stable, on this pull.** The
    real curve does not have the synthetic stress fixture's artificial kink,
    and behaves like the smooth realistic fixture the correction round built
    to match it (both show a materially negative, day-stable roll) rather
    than like the pathological one. This is one ~2-week pull, not a
    multi-year backtest -- it demonstrates the metric is usable, not that it
    is profitable or stable over all regimes; that is Tasks 10-13's question
    to answer, not this test's.
    """
    import datetime as dt

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    dates = [dt.date(2026, 7, d) for d in range(20, 32)] + [dt.date(2026, 8, d) for d in range(1, 4)]
    mdp = IRSwapsMDP(source="GSQUANT-RL")
    raw_curve_map = mdp.bulk_get_data({"curve_name": "USD-OIS", "timestamps": dates})
    curve_map = {
        pd.Timestamp(ts): curve
        for ts, curve in raw_curve_map.items()
        if curve is not None and ts != "live"
    }
    # A systemic provider failure should fail loudly, not silently pass on
    # whatever scraps came back -- more than half the ~10 business days
    # expected out of ~14 calendar days must have produced a curve.
    assert len(curve_map) >= 5

    panel = greeks_panel(curve_map, PAIR)
    assert len(panel) >= 5

    assert -70.0 < panel["spread_bp"].mean() < -40.0  # in the real desk range

    roll = panel["daily_roll_usd"]
    assert (roll < 0.0).all()  # the real desk flattener bleeds, every day sampled
    assert roll.abs().max() / roll.abs().min() < 2.0  # stable, not the stress fixture's chaos

    be25 = panel["breakeven_h25"]
    assert (be25 > 0.0).all()
    assert 2.0 < be25.mean() < 10.0
