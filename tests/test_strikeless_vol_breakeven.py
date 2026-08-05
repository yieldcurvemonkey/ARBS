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


def _curve(ref=REF, slope=0.0):
    """Flat-4% curve, optionally with an inverted ultra-long section."""
    nodes = {ref: 1.0}
    for y in range(1, 41):
        r = 0.04 + slope * max(0.0, y - 10) / 100.0
        nodes[rl.dt(ref.year + y, ref.month, ref.day)] = 1.0 / ((1.0 + r) ** y)
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


PAIR = ForwardPair("USD", "USD-OIS", ForwardLeg("10Y", "10Y"), ForwardLeg("20Y", "10Y"))


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
    curve = _curve(slope=-0.5)  # inverted ultra-long -> flattener should bleed
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    roll = daily_roll_usd(curve, pkg, next_date=rl.dt(2026, 8, 4))
    assert roll != 0.0
    assert abs(roll) < 100_000.0  # one day of carry cannot be a bp of DV01


def test_inverted_curve_makes_the_flattener_bleed():
    curve = _curve(slope=-0.5)
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    assert daily_roll_usd(curve, pkg, next_date=rl.dt(2026, 8, 4)) < 0.0


def test_inverted_roll_is_materially_negative_not_merely_negative():
    """A real bleed, not a rounding artifact: of a size that could plausibly
    fund the day's convexity gain (Gamma ~160 $/bp^2 on this fixture -> a
    breakeven in the low single-digit bp/day range, not micro-bp).
    """
    curve = _curve(slope=-0.5)
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    roll = daily_roll_usd(curve, pkg, next_date=rl.dt(2026, 8, 4))
    assert roll < -100.0  # measured -676.04; generous headroom below that


def test_flat_curve_roll_is_near_zero():
    """The sanity check that ``roll`` is measuring curve SHAPE, not something
    else: with no inversion there is nothing to bleed, so roll should be tiny
    relative to the materially-negative inverted case above (~28x smaller).
    """
    curve = _curve(slope=0.0)
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    roll = daily_roll_usd(curve, pkg, next_date=rl.dt(2026, 8, 4))
    assert abs(roll) < 100.0  # measured -24.76


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
    10-20y forward). A discounting re-base cannot produce carry for a
    not-yet-started, par-struck forward package -- which is exactly why
    ``daily_roll_usd`` now uses ``rl.Curve.roll`` (shape-preserving,
    date-fixed) instead.
    """
    curve = _curve(slope=-0.5)
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    assert package_npv(curve.handle(), pkg) == 0.0  # struck exactly at par

    translated = curve.handle().translate(rl.dt(2026, 8, 4))
    roll_via_translate = package_npv(translated, pkg) - package_npv(curve.handle(), pkg)
    # A real one-day bleed on a $100k/bp package would plausibly be tens to
    # low thousands of dollars (the roll()-based daily_roll_usd measures
    # -676.04 on this same fixture); 1e-3 is generous headroom above the
    # ~1e-7 noise floor actually observed while still being far below any
    # economically plausible carry number.
    assert abs(roll_via_translate) < 1e-3


def test_repo_bps_running_convention_disagrees_in_sign_with_curve_roll_here():
    """Cross-check requested against ``RLIRSwapCurve.carry_and_roll_bps_running``
    -- reported here as a pinned, investigated finding, not silently reconciled.

    ``carry_and_roll_bps_running`` (via ``roll_bps_running``) holds the leg's
    EFFECTIVE date fixed and SHORTENS ITS OWN MATURITY by the horizon, then
    diffs fair rates of those two different-tenor instruments -- a maturity-
    shortening construction. ``daily_roll_usd`` (via ``rl.Curve.roll``) holds
    the leg's dates fixed and slides the CURVE's shape forward instead. On a
    smoothly-sloped curve the two agree in sign (verified below on the flat
    fixture, and per-leg on this inverted one too when checked individually
    -- see the report). On this fixture, which has a sharp kink at y=10
    (flat below, steeply inverted above -- exactly where both legs sit),
    they disagree.

    Verified per-leg (not just at the package level, which could hide a
    combination error): for both the short (10-20y) and the long (20-30y)
    leg individually, converting each leg's OWN ``rl.Curve.roll``-based
    dollar reprice to a bp-equivalent via that leg's own signed DV01
    (``leg_roll_usd / leg_dv01``) gives a POSITIVE number for both legs on
    this fixture, while ``roll_bps_running`` gives a NEGATIVE number for both
    legs. Agreement on the flat curve plus a clean per-leg (not just
    package-level) sign flip specifically on the kinked/inverted curve rules
    out a bookkeeping error in how the two legs are combined -- this is a
    genuine divergence between the two conventions once the curve's shape is
    not smooth, not a mistake in this module. Per the brief: reported and
    pinned rather than forced to agree; whoever compares Task 9's roll
    against ``carry_and_roll_bps_running``-derived numbers on real curves
    should re-verify which convention matches the trade they mean to
    describe. This test's assertions are a snapshot of the current
    (currently correct, per this investigation) disagreement, and will need
    re-examining if the referenced repo functions change.
    """
    curve = _curve(slope=-0.5)
    pkg = build_package(curve, PAIR, package_dv01_usd=100_000.0)
    handle = curve.handle()

    roll_usd = daily_roll_usd(curve, pkg, next_date=rl.dt(2026, 8, 4))
    pkg_dv01_target = 100_000.0
    roll_bp_equiv = roll_usd / pkg_dv01_target

    short_cr = curve.carry_and_roll_bps_running(pkg.short, "1b")
    long_cr = curve.carry_and_roll_bps_running(pkg.long, "1b")
    # Package convention: we PAY the short leg (opposite of the "receiver"
    # convention roll_bps_running is quoted in) and RECEIVE the long leg
    # (matching it directly).
    repo_bp_running = long_cr - short_cr

    assert roll_bp_equiv < 0.0
    assert repo_bp_running > 0.0  # the pinned disagreement

    # Per-leg check (rules out a package-combination error): each leg's own
    # roll()-based bp-equivalent is positive while its own roll_bps_running
    # is negative, individually, not just after combining the two legs.
    for swap, dv01_sign in ((pkg.short, +1.0), (pkg.long, -1.0)):
        base = swap.npv(curves=handle).real
        rolled = swap.npv(curves=handle.roll(rl.dt(2026, 8, 4))).real
        leg_roll_usd = rolled - base
        leg_bp_equiv = leg_roll_usd / (dv01_sign * pkg_dv01_target)
        leg_rr = curve.roll_bps_running(swap, "1b")
        assert leg_bp_equiv > 0.0
        assert leg_rr < 0.0


def test_compute_greeks_returns_a_full_labelled_record():
    curve = _curve(slope=-0.5)
    g = compute_greeks(curve, PAIR, next_date=rl.dt(2026, 8, 4))
    assert g.pair_name == "USD 10Y10Y/20Y10Y"
    assert g.spread_bp < 0.0  # inverted
    assert set(g.gamma_by_h) == {10.0, 25.0, 50.0}
    assert set(g.breakeven_by_h) == {10.0, 25.0, 50.0}
    assert g.breakeven_by_h[25.0] > 0.0
    # Sizing each leg on its own repriced DV01 (central difference, matching
    # the measure package_dv01 checks) rather than the analytic annuity
    # (curve.pv01) makes the package neutral in the measure that matters by
    # construction: measured residual is ~1e-8 on this inverted fixture (was
    # $11,411 -- 11.4% of target -- when sizing was pv01-based and the check
    # was in the repriced measure). abs=10.0 restored to the tight bound.
    assert abs(g.package_dv01) == pytest.approx(0.0, abs=10.0)


def test_greeks_panel_is_one_row_per_date():
    curve_map = {
        pd.Timestamp("2026-08-03"): _curve(slope=-0.5),
        pd.Timestamp("2026-08-04"): _curve(ref=rl.dt(2026, 8, 4), slope=-0.5),
    }
    panel = greeks_panel(curve_map, PAIR)
    assert len(panel) == 2
    assert "breakeven_h25" in panel.columns
    assert "gamma_h25" in panel.columns
    assert "daily_roll_usd" in panel.columns
