"""Known-answer tests for strategy 1 -- the JPM curve-as-gamma framework.

Two tiers, deliberately separated so the fast gate stays fast:

* **Synthetic** (default marks, no I/O). Analytic planted answers for the
  breakeven classification, the uneven-grid convexity test, the straddle
  sizing, the cohort schedule and the direction algebra. These are the ones
  that catch a logic regression, and they run in milliseconds.

* **Live** (``@pytest.mark.slow``). The regression table the whole package is
  pinned to: the 2022-09-13 payoff profiles for three structures, reproduced
  to +/-0.5 bp, plus the carry ordering that is JPM's headline claim. These
  need the Citi Velocity curve store.

Verifying the checker itself: every synthetic assertion below has a planted
answer computed independently of the code under test (closed-form Bachelier,
closed-form quadratic breakeven, hand-written date arithmetic), and
``test_is_convex_rejects_a_concave_profile`` /
``test_is_convex_uneven_grid_is_not_a_plain_second_difference`` are the
mutation checks for the convexity test -- the second one FAILS if ``is_convex``
is rewritten as a naive ``np.diff(np.diff(payoff))``.
"""

from __future__ import annotations

import dataclasses
import datetime
import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import strat1_curve_gamma as s1

CURVE = "USD-SOFR-1D"
DV01 = 100_000.0

#: The pinned regression table: 2022-09-13, $100k package DV01, bpv<0 flattener,
#: payoff in bp of package DV01 across the 13-point shift grid, carry EXCLUDED
#: (pure convexity shape -- the ``carry_ccy=0`` profile).
REGRESSION_2022_09_13 = {
    "20Yx5Y/25Yx5Y": [60.0, 33.7, 16.5, 6.4, 1.3, 0.3, 0.0, 0.4, 1.2, 4.2, 8.2, 12.8, 17.5],
    "30Y/50Y": [137.9, 82.1, 44.7, 20.9, 6.9, 2.7, 0.0, -1.4, -1.8, -0.1, 3.9, 9.5, 15.9],
    "10Yx10Y/20Yx10Y": [104.9, 60.0, 29.9, 11.6, 2.3, 0.4, 0.0, 0.9, 2.9, 9.5, 18.7, 29.7, 41.7],
}

#: Package carry-and-roll over a 1-year horizon on 2022-09-13, bp of package
#: DV01, for the bpv<0 flattener. JPM's headline claim is the ORDERING of these.
CARRY_2022_09_13 = {
    "20Yx5Y/25Yx5Y": 0.0061,
    "5Y/30Y": -20.6697,
    "30Y/50Y": 0.3632,
    "10Yx10Y/20Yx10Y": -2.8401,
}

GRID = np.arange(-1000.0, 1000.01, 2.0)


# ------------------------------------------------------------------ config


def test_config_defaults_match_the_note():
    cfg = s1.Strat1Config()
    # "we use 1Yx30Y swaptions for a 1-year horizon"
    assert cfg.swaption_expiry == "1Y" and cfg.swaption_tenor == "30Y"
    assert cfg.horizon == "1Y" and cfg.horizon_years == 1.0
    # breakeven-vol is the default because the OTM smile only starts 2020-03-25
    assert cfg.signal_mode == "breakeven_vol"
    # Exhibit 3's axis
    assert min(cfg.shifts_bp) == -250.0 and max(cfg.shifts_bp) == 250.0
    assert 0.0 in cfg.shifts_bp
    # overlapping cohorts are never force-closed
    assert cfg.force_close_at_end is False
    # the pair JPM's Exhibit 5 reports side by side must both be present
    labels = [l for (l, _, _) in cfg.structures]
    assert "30Y/50Y" in labels and "20Yx5Y/25Yx5Y" in labels


def test_config_is_frozen_so_a_run_cannot_mutate_its_own_knobs():
    cfg = s1.Strat1Config()
    with pytest.raises(Exception):
        cfg.package_dv01 = 1.0  # type: ignore[misc]


# ------------------------------------------------- breakeven classification


def _quadratic(a: float, c: float) -> np.ndarray:
    """Planted answer: E[a x^2 + c] = a sigma^2 + c, root at sqrt(-c/a)."""
    return a * GRID**2 + c


def test_breakeven_root_matches_the_closed_form():
    a, c = 0.002, -30.0
    r = s1.breakeven_vol(GRID, _quadratic(a, c), horizon_years=1.0)
    assert r.status == "root"
    assert r.bp_per_year == pytest.approx(math.sqrt(-c / a), rel=1e-4)
    assert r.bp_per_day == pytest.approx(r.bp_per_year / math.sqrt(252.0), rel=1e-9)


def test_positive_carry_is_always_cheap_not_nan():
    """The branch JPM's '100% cheap curve gamma' column lives in.

    A convex profile that is already positive everywhere never needs vol to
    break even. ``breakeven_vol_bp_per_year`` returns NaN; collapsing that to
    'no signal' would delete exactly the days the note is about.
    """
    r = s1.breakeven_vol(GRID, _quadratic(0.002, +5.0), horizon_years=1.0)
    assert r.status == "always_cheap"
    assert r.bp_per_year == 0.0
    assert s1.signal_from_breakeven(r, atmf_bp_per_day=6.0) == 1.0


def test_never_cheap_is_distinguished_from_always_cheap():
    """A concave, everywhere-negative profile is rich at ANY vol -- the opposite
    state, and ``breakeven_vol_bp_per_year`` returns the same NaN for it."""
    payoff = -0.002 * GRID**2 - 5.0
    r = s1.breakeven_vol(GRID, payoff, horizon_years=1.0)
    assert r.status == "never_cheap"
    assert r.bp_per_year == math.inf
    assert s1.signal_from_breakeven(r, atmf_bp_per_day=6.0) == -1.0
    assert s1.signal_from_breakeven(r, atmf_bp_per_day=6.0, trade_when_rich=False) == 0.0


def test_breakeven_nan_payoff_is_undefined_and_gives_no_signal():
    payoff = _quadratic(0.002, -30.0).copy()
    payoff[3] = np.nan
    r = s1.breakeven_vol(GRID, payoff, horizon_years=1.0)
    assert r.status == "undefined"
    assert s1.signal_from_breakeven(r, atmf_bp_per_day=6.0) == 0.0


def test_missing_atmf_vol_gives_no_signal():
    r = s1.breakeven_vol(GRID, _quadratic(0.002, -30.0), horizon_years=1.0)
    assert r.status == "root"
    assert s1.signal_from_breakeven(r, atmf_bp_per_day=float("nan")) == 0.0


# ------------------------------------------------------------ signal algebra


def test_signal_from_breakeven_is_cheap_below_and_rich_above():
    r = s1.BreakevenResult(bp_per_year=100.0, bp_per_day=100.0 / math.sqrt(252.0), status="root")
    assert s1.signal_from_breakeven(r, atmf_bp_per_day=r.bp_per_day + 1.0) == 1.0
    assert s1.signal_from_breakeven(r, atmf_bp_per_day=r.bp_per_day - 1.0) == -1.0


def test_entry_threshold_creates_a_no_trade_band():
    r = s1.BreakevenResult(bp_per_year=100.0, bp_per_day=6.0, status="root")
    # 0.2 bp/day inside the band on either side -> flat
    assert s1.signal_from_breakeven(r, 6.1, threshold_bp_per_day=0.2) == 0.0
    assert s1.signal_from_breakeven(r, 5.9, threshold_bp_per_day=0.2) == 0.0
    assert s1.signal_from_breakeven(r, 6.5, threshold_bp_per_day=0.2) == 1.0
    assert s1.signal_from_breakeven(r, 5.5, threshold_bp_per_day=0.2) == -1.0


def test_signal_from_expected_payoff_sign_and_threshold():
    f = s1.signal_from_expected_payoff
    assert f(+1.0, package_dv01=DV01) == 1.0
    assert f(-1.0, package_dv01=DV01) == -1.0
    assert f(0.0, package_dv01=DV01) == 0.0
    assert f(float("nan"), package_dv01=DV01) == 0.0
    # threshold is in bp of package DV01
    assert f(0.5 * DV01, package_dv01=DV01, threshold_bp=1.0) == 0.0
    assert f(1.5 * DV01, package_dv01=DV01, threshold_bp=1.0) == 1.0


def test_vol_bp_per_day_conversion():
    assert s1.vol_bp_per_day(100.0, 252.0) == pytest.approx(100.0 / math.sqrt(252.0))
    assert np.isnan(s1.vol_bp_per_day(float("nan")))


# ---------------------------------------------------------------- convexity


def test_is_convex_accepts_a_quadratic_on_the_production_grid():
    shifts = np.asarray(s1.Strat1Config().shifts_bp)
    assert s1.is_convex(shifts, 0.002 * shifts**2)


def test_is_convex_rejects_a_concave_profile():
    """Mutation check: if ``is_convex`` always returned True this fails."""
    shifts = np.asarray(s1.Strat1Config().shifts_bp)
    assert not s1.is_convex(shifts, -0.002 * shifts**2)


def test_is_convex_uneven_grid_is_not_a_plain_second_difference():
    """Mutation check for the SPACING handling.

    The production grid steps 50 bp in the wings and 25 bp near the money. A
    real flattener profile is not a centred parabola -- it carries a linear term
    (residual delta plus the carry level's interaction with the grid), and for
    ``a*s^2 + b*s`` the LINEAR part alone contributes ``b * secondDiff(s)``,
    which is -25b at the point where the step size drops from 50 to 25. So a
    ``np.diff(np.diff(payoff)) >= 0`` implementation reports this
    everywhere-convex function as concave. This test pins the correct behaviour
    and fails if ``is_convex`` is rewritten the naive way.
    """
    shifts = np.asarray(s1.Strat1Config().shifts_bp)
    payoff = 0.002 * shifts**2 + 1.0 * shifts   # convex for all s, since a > 0
    assert s1.is_convex(shifts, payoff)
    naive = np.diff(np.diff(payoff))
    assert (naive < 0).any(), "grid is no longer uneven -- this test has stopped testing anything"


def test_is_convex_needs_finite_values():
    shifts = np.asarray(s1.Strat1Config().shifts_bp)
    payoff = 0.002 * shifts**2
    payoff[0] = np.nan
    assert not s1.is_convex(shifts, payoff)


# --------------------------------------------------------- straddle sizing


def test_atmf_straddle_premium_is_the_bachelier_closed_form():
    """A normal-model ATMF straddle is sqrt(2/pi)*sigma*sqrt(T) of rate."""
    assert s1.atmf_straddle_premium_bp(100.0, 1.0) == pytest.approx(79.7885, rel=1e-4)
    # doubling the horizon widens by sqrt(2)
    assert (s1.atmf_straddle_premium_bp(100.0, 2.0)
            / s1.atmf_straddle_premium_bp(100.0, 1.0)) == pytest.approx(math.sqrt(2.0))
    assert np.isnan(s1.atmf_straddle_premium_bp(float("nan")))
    assert np.isnan(s1.atmf_straddle_premium_bp(0.0))


def test_straddle_sized_to_fund_the_carry_intakes_exactly_the_carry():
    """The note: 'sized such that the initiate premium intake is equal to the
    carry over the same 1-year horizon'."""
    vol, carry_ccy = 98.3785, -2.84 * DV01   # 10Yx10Y/20Yx10Y on 2022-09-13
    dv01 = s1.straddle_dv01_for_carry(carry_ccy, vol, tte_years=1.0)
    intake = dv01 * s1.atmf_straddle_premium_bp(vol, 1.0)
    assert intake == pytest.approx(abs(carry_ccy), rel=1e-9)


def test_trade_straddle_true_refuses_loudly_instead_of_doing_nothing():
    """``build_backtest`` does not wire the straddle leg. Flipping the knob must
    RAISE, not return the identical flattener-only book."""
    cfg = dataclasses.replace(s1.Strat1Config(), trade_straddle=True)
    grid = _bdays("2021-01-01", "2021-06-30")
    sig = pd.Series(1.0, index=grid)
    with pytest.raises(NotImplementedError, match="trade_straddle"):
        s1.build_backtest(None, cfg, "20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y", sig, grid)


def test_zero_carry_means_a_zero_size_straddle():
    """Why the straddle leg defaults OFF: the forward structure's carry is
    +0.0061 bp, so the funding straddle is ~$5 of DV01 -- noise, not a leg."""
    dv01 = s1.straddle_dv01_for_carry(CARRY_2022_09_13["20Yx5Y/25Yx5Y"] * DV01, 98.3785, tte_years=1.0)
    assert dv01 < 10.0
    # the spot structure's is three orders of magnitude larger
    spot = s1.straddle_dv01_for_carry(CARRY_2022_09_13["5Y/30Y"] * DV01, 98.3785, tte_years=1.0)
    assert spot > 1000.0 * dv01


# ---------------------------------------------------------------- cohorts


def _bdays(a: str, b: str) -> pd.DatetimeIndex:
    return pd.bdate_range(a, b)


def test_cohort_dates_daily_weekly_monthly():
    days = _bdays("2021-01-01", "2021-03-31")   # 3 months of business days
    assert len(s1.cohort_dates(days, "daily")) == len(days)
    weekly = s1.cohort_dates(days, "weekly")
    monthly = s1.cohort_dates(days, "monthly")
    # one per ISO week and one per calendar month, first available day of each
    assert len(weekly) == len({(d.isocalendar()[0], d.isocalendar()[1]) for d in days})
    assert [str(d) for d in monthly] == ["2021-01-01", "2021-02-01", "2021-03-01"]
    assert set(monthly) <= set(weekly) <= set(d.date() for d in days)


def test_cohort_dates_takes_the_first_available_day_not_a_fixed_weekday():
    """A holiday must SHIFT the cohort, not delete it."""
    days = _bdays("2021-01-04", "2021-01-15").drop(pd.Timestamp("2021-01-11"))
    weekly = s1.cohort_dates(days, "weekly")
    assert weekly == [datetime.date(2021, 1, 4), datetime.date(2021, 1, 12)]


def test_cohort_dates_rejects_an_unknown_frequency():
    with pytest.raises(ValueError):
        s1.cohort_dates(_bdays("2021-01-01", "2021-01-31"), "fortnightly")


def test_cohort_schedule_exits_one_year_later_and_leaves_the_tail_live():
    grid = _bdays("2021-01-01", "2022-06-30")
    entries = [datetime.date(2021, 1, 1), datetime.date(2021, 6, 1), datetime.date(2022, 1, 3)]
    sched = s1.cohort_schedule(grid, entries, "1Y")
    assert sched[0] == (datetime.date(2021, 1, 1), datetime.date(2022, 1, 3))
    assert sched[1] == (datetime.date(2021, 6, 1), datetime.date(2022, 6, 1))
    # a cohort opened inside the last year has no exit on the grid: still LIVE
    assert sched[2][0] == datetime.date(2022, 1, 3) and sched[2][1] is None


def test_cohort_schedule_never_force_closes_the_tail():
    """The design decision, pinned: positions opened after (end - horizon) must
    come back with exit=None so they can be MARKED rather than closed at a
    partial horizon and mixed into the closed-trade statistics."""
    grid = _bdays("2019-01-01", "2026-08-14")
    entries = s1.cohort_dates(grid, "monthly")
    sched = s1.cohort_schedule(grid, entries, "1Y")
    live = [e for (e, x) in sched if x is None]
    assert live, "no live tail -- the overlapping-cohort case is not being exercised"
    assert min(live) > datetime.date(2025, 8, 1)
    assert all(x is not None for (e, x) in sched if e < datetime.date(2025, 8, 1))


# --------------------------------------------------- live, curve-store bound


@pytest.fixture(scope="module")
def live_pricer():
    pytest.importorskip("rateslib")
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    p = mdp.get_data({"curve_name": CURVE, "timestamp": datetime.date(2022, 9, 13)})
    if p is None:
        pytest.skip("Citi Velocity curve unavailable for 2022-09-13")
    return p


@pytest.mark.slow
@pytest.mark.parametrize("label,front,back", [
    ("20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y"),
    ("30Y/50Y", "30Y", "50Y"),
    ("10Yx10Y/20Yx10Y", "10Yx10Y", "20Yx10Y"),
])
def test_payoff_profile_regression_table(live_pricer, label, front, back):
    """Tie-out (a): the pinned 2022-09-13 convexity table, +/-0.5 bp.

    This is the tripwire on the whole measurement chain -- CURVE structure
    resolution, direction resolution, the shifted repricing kernel and the
    unit conversion. If any of them regresses, every downstream signal is wrong
    and nothing else in this module would notice.
    """
    cfg = s1.Strat1Config()
    prof = s1.structure_profile(live_pricer, label, front, back, cfg, direction=s1.FLATTENER)
    got = prof.convexity_bp
    exp = np.asarray(REGRESSION_2022_09_13[label], dtype=float)
    assert got.shape == exp.shape
    assert np.max(np.abs(got - exp)) < 0.5, f"{label}: got {np.round(got, 2)} want {exp}"


@pytest.mark.slow
@pytest.mark.parametrize("label,front,back", [
    ("20Yx5Y/25Yx5Y", "20Yx5Y", "25Yx5Y"),
    ("30Y/50Y", "30Y", "50Y"),
    ("10Yx10Y/20Yx10Y", "10Yx10Y", "20Yx10Y"),
    ("5Y/30Y", "5Y", "30Y"),
])
def test_flattener_convexity_shape_is_convex(live_pricer, label, front, back):
    """Tie-out (b): a DV01-neutral flattener must be LONG gamma.

        "duration-neutral flatteners with fixed hedge ratios will have positive
         P/L if the curve shifts in parallel in either direction. The resulting
         P/L diagram looks quite a bit like a straddle."
    """
    cfg = s1.Strat1Config()
    prof = s1.structure_profile(live_pricer, label, front, back, cfg, direction=s1.FLATTENER)
    assert s1.is_convex(prof.shifts_bp, prof.convexity_ccy), (
        f"{label} convexity profile is not convex: {np.round(prof.convexity_bp, 2)}")
    # and the mirror: the steepener is SHORT gamma
    st = s1.structure_profile(live_pricer, label, front, back, cfg, direction=s1.STEEPENER)
    assert not s1.is_convex(st.shifts_bp, st.convexity_ccy)
    assert np.allclose(st.convexity_ccy, -prof.convexity_ccy, rtol=1e-3, atol=1.0)


@pytest.mark.slow
def test_carry_ordering_forward_beats_spot(live_pricer):
    """Tie-out (d): JPM's headline claim, on the day it is pinned to.

        "forward curve flatteners (e.g., 25Yx5Y versus 20Yx5Y) are a more
         attractive and cheaper source of this exposure than 30s/50s and similar
         structures."

    Pinned to the 20Yx5Y/25Yx5Y vs 5Y/30Y pair, whose 2022-09-13 values are
    +0.0061 bp and -20.6697 bp. NOT to 30s/50s: on this particular date the
    long end was inverted enough that 30s/50s carried at +0.3632 bp, so the
    forward-beats-30s50s ordering is a full-sample question, not a one-day
    assertion, and it is answered in the notebook.
    """
    cfg = s1.Strat1Config()
    got = {}
    for label, front, back in cfg.structures:
        raw, w, _ = s1.resolve_package(
            live_pricer, front, back,
            package_dv01=cfg.package_dv01, direction=s1.FLATTENER, curve=cfg.curve)
        got[label] = s1.package_carry_roll_bp(live_pricer, raw, w, cfg.horizon)
    for label, want in CARRY_2022_09_13.items():
        assert got[label] == pytest.approx(want, abs=0.01), f"{label}: {got[label]}"
    assert got["20Yx5Y/25Yx5Y"] > got["5Y/30Y"] + 15.0
    assert got["20Yx5Y/25Yx5Y"] > got["10Yx10Y/20Yx10Y"]


@pytest.mark.slow
def test_resolve_package_is_dv01_neutral_and_direction_mirrors(live_pricer):
    """Tie-out (c) at module level: the sign convention, verified live.

    ``bpv < 0`` must pay the front leg and receive the back (a flattener), and
    flipping the sign must mirror both legs exactly. A direction-blind
    ``resolve_pricable`` would return the same all-payer package for both.
    """
    cfg = s1.Strat1Config()
    _, w_flat, flat = s1.resolve_package(
        live_pricer, "20Yx5Y", "25Yx5Y",
        package_dv01=cfg.package_dv01, direction=s1.FLATTENER, curve=cfg.curve)
    _, w_steep, steep = s1.resolve_package(
        live_pricer, "20Yx5Y", "25Yx5Y",
        package_dv01=cfg.package_dv01, direction=s1.STEEPENER, curve=cfg.curve)

    pv_flat = [live_pricer.pv01(s) for s in flat]
    pv_steep = [live_pricer.pv01(s) for s in steep]
    assert w_flat == [1.0, -1.0] and w_steep == [-1.0, 1.0]
    for a, b in zip(pv_flat, pv_steep):
        assert abs(a) == pytest.approx(cfg.package_dv01, rel=1e-6)
        assert a == pytest.approx(-b, rel=1e-6)
    assert sum(pv_flat) == pytest.approx(0.0, abs=1e-3 * cfg.package_dv01)
    # notionals must mirror too, not just pv01
    n_flat = [live_pricer.notional(s) for s in flat]
    n_steep = [live_pricer.notional(s) for s in steep]
    for a, b in zip(n_flat, n_steep):
        assert a == pytest.approx(-b, rel=1e-9)
