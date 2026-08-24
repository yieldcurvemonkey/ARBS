"""Tests for the vol butterfly grid + mode-vs-forward tracker."""
import datetime

import numpy as np
import pytest

from RVUtils.StripPeak.vol_backtest import (
    build_butterfly_grid,
    mode_series,
    mode_vs_forward,
    sr3_to_sfr_symbol,
)


@pytest.mark.network
def test_build_butterfly_grid_known_date():
    """Build the grid for SFRU26 on 2026-08-21 and verify against JWS's grid.

    Reference value note: the task-5 brief's skeleton test asserted a modal body
    of 96.1250 (3.875%). A clean-room rebuild here computes the argmax at body
    96.2500 (3.75%, gap -5bp vs the 96.20 forward) -- exactly one 6.25bp grid step
    away from the brief's value. Given that verified 96.2500 mode, the brief's own
    assertion fails deterministically at its own boundary: |96.25 - 96.125| ==
    0.125 exactly, and the brief's assert used strict '<' against a tolerance of
    0.0625*2 == 0.125, so 0.125 < 0.125 is False. Recentering the assertion on
    96.250 (below) keeps the same tolerance width and still discriminates --
    96.125 fails it by the same strict-'<' symmetry from the other side.

    This is independently corroborated by memory note
    reference_sofr_butterfly_grid.md, written from prior work that explicitly
    gated a rebuild against JWS's printed column ("8/8 bodies matched") and
    recorded: "SFRU26 peaks at body 96.2500 (3.75%) against a future at 96.2000 --
    mode 5bp below the forward in rate" -- matching this run's output exactly,
    including the sum(imp_prob) == 2.00 fingerprint for U6 specifically (the note
    lists 2.00/1.98/1.96/1.94 across U6/Z6/H7/M7). Treated as a plan-bug transcription
    slip in the brief (96.125 vs 96.250), same category as task-1's Saturday-date
    fix -- ratified in task-5-report.md's Ruling section rather than silently
    matched to the brief's number.
    """
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    grid = build_butterfly_grid(mdp, "SFRU26", datetime.date(2026, 8, 21))

    assert len(grid) > 10
    assert "body_price" in grid.columns
    assert "body_yield" in grid.columns
    assert "fly_settle" in grid.columns
    assert "imp_prob" in grid.columns

    # Known-answer check on the grid mechanics themselves: adjacent bodies'
    # triangular kernels overlap ~2x on a 6.25bp-body / 12.5bp-wing grid, so the
    # imp_prob column should sum to ~2.0 (measured 2.00 for U6 on this date in
    # prior gated work). A collapsed sum well below 2.0 is the specific failure
    # mode a broken/missing put-call-parity fill produces (see
    # reference_sofr_butterfly_grid.md) -- half the grid (the ITM-call bodies)
    # would silently drop out.
    assert 1.8 < grid["imp_prob"].sum() < 2.2

    mode_row = grid.loc[grid["imp_prob"].idxmax()]
    assert abs(mode_row["body_price"] - 96.25) < 0.0625 * 2  # within 2 ticks


@pytest.mark.network
def test_mode_vs_forward_known_date():
    """mode_vs_forward on the same grid: mode should sit ~5bp below the forward."""
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    grid = build_butterfly_grid(mdp, "SFRU26", datetime.date(2026, 8, 21))
    future_price = grid.attrs["future_price"]

    result = mode_vs_forward(grid, future_price)
    assert set(result.keys()) == {"mode_yield", "forward_yield", "gap_bp", "mode_imp_prob"}
    assert abs(result["mode_yield"] - 3.75) < 0.02
    assert abs(result["forward_yield"] - 3.80) < 0.02
    assert abs(result["gap_bp"] - (-5.0)) < 2.0


@pytest.mark.network
def test_mode_series_current_peak_contract():
    """Snapshot deliverable (Task 5 part d): mode-vs-forward gap for SFRU27, the
    strip's current peak contract (confirmed via identify_peak on a fresh
    2026-08-17..21 strip pull -- SR3U27 is peak on 08-20 and 08-21, SR3M27 on the
    three days before), over the three most recent settle dates at the time this
    was written. NOT a P&L backtest -- see module docstring / task-5-report.md's
    scoping ruling for why the full historical version needs rolling contracts
    that don't exist yet.

    All three `as_of` dates are fixed historical settles (not "today"), so this
    should keep returning data indefinitely via Barchart's EOD archive, same as
    the other fixed-date tests in this module and in test_strip_peak_builder.py --
    it is not expected to go stale when SFRU27 itself expires in 2027.
    """
    from MDP.STIRFutures.STIRFutureOptionMDP import STIRFutureOptionMDP

    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")
    symbol = sr3_to_sfr_symbol("SR3U27")
    assert symbol == "SFRU27"

    dates = [datetime.date(2026, 8, 19), datetime.date(2026, 8, 20), datetime.date(2026, 8, 21)]
    series = mode_series(mdp, symbol, dates)

    # No silent date drop-outs for this known-good window.
    assert len(series) == len(dates)
    assert list(series["as_of"]) == dates
    assert (series["symbol"] == symbol).all()

    # Sanity range only (not pinned to exact levels) -- SR3 rates across the whole
    # strip have sat in a 3-6% band throughout this study (see test_strip_peak_
    # builder.py's (2, 8) sanity band and task-4-report.md's strip printout).
    assert (series["mode_yield"] > 2.0).all() and (series["mode_yield"] < 8.0).all()
    assert (series["forward_yield"] > 2.0).all() and (series["forward_yield"] < 8.0).all()
    assert series["gap_bp"].apply(lambda x: np.isfinite(x)).all()
    assert (series["mode_imp_prob"] > 0).all()

    # 13 months out, the listed chain is measurably sparser than the front
    # contract's (SFRU26 summed to ~2.0 in the tests above): fewer strikes carry
    # real (non-floor-tick) market prices, so fewer bodies both exist and overlap.
    # Document the floor rather than assert a tight band -- this is a data-density
    # observation, not a mechanic being tested.
    assert (series["n_bodies"] > 10).all()
