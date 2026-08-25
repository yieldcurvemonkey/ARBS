"""Tests for the SR3 flattener structuring analysis.

This module makes no backtest claim -- it prices structures and describes
distributions -- so the invariants that matter are the ones that would silently
make a DESCRIPTION wrong: the roll, the sign convention, and the cost.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
RV = REPO / "notebooks" / "rv"
for _p in (str(REPO), str(RV)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fed_detachment_prices as PX  # noqa: E402
import sfr_flattener_structuring as S  # noqa: E402


@pytest.fixture(scope="module")
def rates():
    r = S.rate_panel()
    if r.empty or r.shape[1] < 10:
        pytest.skip("SR3 settle cache is cold")
    return r


def test_a_two_leg_spread_costs_twice_an_outright():
    """`reference_sfr_fly_conventions`: the cost is per CONTRACT, not per leg of
    the quote. Quoting a spread at an outright's 0.50bp halves the hurdle, and on
    a structure whose entire prize is 4.5bp that is the difference between a
    22% haircut and an 11% one."""
    assert S.SPREAD_ROUND_TRIP_BP == pytest.approx(2 * S.OUTRIGHT_ROUND_TRIP_BP)
    assert S.SPREAD_ROUND_TRIP_BP == pytest.approx(1.00)


def test_a_positive_spread_means_tightening_is_priced(rates):
    """`spread(i, j) = rate(j) - rate(i)` with j the LATER contract, so positive
    is upward sloping. Getting this backwards would turn every flattener in the
    table into a steepener and invert the whole recommendation."""
    d = pd.Timestamp("2026-08-21")
    if d not in rates.index:
        pytest.skip("panel does not cover the reference date")
    front, back = PX.rank_symbol(d.date(), 1), PX.rank_symbol(d.date(), 3)
    s = S.spread_bp(rates, d, front, back)
    a, b = rates.at[d, front], rates.at[d, back]
    assert s == pytest.approx((b - a) * 100.0)
    assert (s > 0) == (b > a)


def test_the_flattener_pnl_is_MINUS_the_spread_change_net_of_cost(rates):
    """A flattener is SHORT the spread: it profits when the spread falls. A sign
    slip here would report every loss as a gain."""
    mv = S.horizon_moves(rates, 3, 5, horizon_bd=21, start="2024-01-01")
    assert len(mv) > 50
    want = -(mv["spread_end_bp"] - mv["spread_start_bp"]) - S.SPREAD_ROUND_TRIP_BP
    assert np.allclose(mv["flattener_pnl_bp"].to_numpy(float),
                       want.to_numpy(float))


def test_no_horizon_row_ever_differences_two_contracts(rates):
    """The roll discipline. A rank-differenced spread fabricates drift at every
    roll -- measured on this desk at +6.9bp per roll week for a single leg,
    more than twice what the book it was built for earned. Every row here must
    read the SAME two contracts at both ends, and a pair whose near leg expires
    inside the hold must be dropped, not rolled."""
    mv = S.horizon_moves(rates, 3, 5, horizon_bd=63, start="2021-01-04")
    assert len(mv) > 200
    worst = 0.0
    for r in mv.itertuples():
        # the recorded legs must be the ranks AS OF THE START, not the exit
        assert r.front == PX.rank_symbol(pd.Timestamp(r.date).date(), 3)
        assert r.back == PX.rank_symbol(pd.Timestamp(r.date).date(), 5)
        # ...and both marks must come from those same two contracts
        a = S.spread_bp(rates, pd.Timestamp(r.date), r.front, r.back)
        b = S.spread_bp(rates, pd.Timestamp(r.exit), r.front, r.back)
        worst = max(worst, abs(a - r.spread_start_bp), abs(b - r.spread_end_bp))
    assert worst < 1e-9
    assert mv.attrs["dropped_expiring"] >= 0


def test_a_pair_whose_leg_expires_inside_the_hold_is_dropped_and_counted(rates):
    """At a long enough horizon the near leg CAN expire. The guard is the only
    thing standing between that and a P&L computed across two contracts, so it
    has to actually fire -- if the count is zero this test proves nothing."""
    mv = S.horizon_moves(rates, 1, 3, horizon_bd=126, start="2021-01-04")
    assert mv.attrs["dropped_expiring"] > 0, (
        "the fixture must contain an expiring pair for this to test anything")


def test_conditional_on_level_actually_restricts_the_sample(rates):
    """A flattener entered at +40bp and one entered at +3bp are different trades.
    Pooling them describes neither, and the pooled mean is what a reader would
    otherwise take as 'what happens from here'."""
    mv = S.horizon_moves(rates, 3, 5, horizon_bd=63, start="2021-01-04")
    allc = S.horizon_summary(mv)
    cond = S.conditional_on_level(mv, 6.5)
    assert cond["n"] < allc["n"], "the band must exclude something"
    assert cond["n"] > 20
    assert "band" in cond
    sub = mv[(mv["spread_start_bp"] - 6.5).abs() <= 5.0]
    assert cond["n"] == len(sub)


def test_both_ways_requires_the_spread_to_fall_in_BOTH_halves(rates):
    """'Wins both ways' means beta_up < 0 AND beta_dn > 0 -- the spread falls
    whether the strip sells off or rallies. Reporting only the pooled beta would
    hide a structure that is directional in disguise, which is what every pair
    tested here turns out to be."""
    bw = S.both_ways(rates, 3, 5, horizon_bd=21, start="2021-01-04")
    assert bw["n"] > 100
    assert bw["flattens_when_level_rises"] == bool(bw["beta_up"] < 0)
    assert bw["flattens_when_level_falls"] == bool(bw["beta_dn"] > 0)
    assert bw["n_up"] + bw["n_dn"] <= bw["n"]


def test_the_twist_point_betas_are_ordered_and_peak_inside_the_strip(rates):
    """The level-sensitivity profile is what says which leg of a spread moves
    more, and therefore whether a given pair is a flattener at all. It must rise
    from the front and turn over inside the strip -- a monotone profile would
    mean no twist point exists and every calendar spread is directional."""
    tw = S.twist_point(rates, horizon_bd=21, max_rank=8, start="2021-01-04")
    b = tw["beta_to_level"].to_numpy(float)
    assert np.isfinite(b).all()
    assert b[0] < b[2], "the front must be less level-sensitive than the belly"
    assert int(np.nanargmax(b)) not in (0, len(b) - 1), (
        "the peak must be strictly inside the strip for a twist point to exist")
