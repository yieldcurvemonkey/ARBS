"""Tests for the recurring SR3 EOD settle warm.

Three things are worth pinning, and they are the three that were actually wrong
or nearly wrong while building it:

* the strip is *consecutive quarterlies* at the requested depth (a warm that
  fetches the wrong symbols writes keys nobody reads);
* ``_depth_by_date`` must force ``min_instruments=1``, because
  ``strip_depth_by_date``'s default of 12 *omits* shallower dates entirely --
  leaving it at the default makes the warm blind to precisely the dates it
  exists to fill; and
* the job must FAIL when it fetched dates but measured depth did not move.
  "Keys written" is not evidence of recovery: the panel matches a specific
  ``{iso_timestamp}-{TICKER}-{SOURCE}`` shape, and a fetch writing any other
  shape would otherwise report a cheerful success while recovering nothing.
"""

from __future__ import annotations

import datetime as dt

import pytest

from scripts import warm_sr3_settles as W


def test_strip_symbols_are_consecutive_quarterlies_at_requested_depth():
    syms = W._strip_symbols(dt.date(2026, 8, 18), 20)
    assert len(syms) == 20
    assert len(set(syms)) == 20, "a repeated symbol means the ladder stalled"
    assert all(s.startswith("SR3") for s in syms)
    # H/M/U/Z only -- the quarterly cycle, never a serial month.
    assert all(s[3] in "HMUZ" for s in syms), syms

    # Consecutive: each step advances exactly one quarter, including across the
    # year boundary (Z -> H), which is where an off-by-one ladder breaks first.
    order = {"H": 0, "M": 1, "U": 2, "Z": 3}
    idx = [order[s[3]] + 4 * int(s[4:]) for s in syms]
    assert idx == list(range(idx[0], idx[0] + 20)), idx


def test_depth_by_date_sees_dates_below_the_q20_min_instruments_default():
    """The regression guard: default ``min_instruments=12`` hides shallow dates."""
    from RVUtils.ConvexityRV.strat2_q20 import Q20Config, strip_depth_by_date

    start, end = dt.date(2026, 7, 1), dt.date(2026, 8, 18)
    permissive = W._depth_by_date(20, start, end)
    default = strip_depth_by_date(
        Q20Config(max_instruments=20, start=start, end=end))

    shallow = {d: n for d, n in permissive.items() if 0 < n < 12}
    assert shallow, "expected some dates below depth 12 in this window"
    # Every shallow date is invisible to the default config -- which is exactly
    # why the warm must not use it.
    assert not (set(shallow) & set(default))


def test_job_raises_when_fetches_did_not_move_measured_depth(monkeypatch):
    monkeypatch.setattr(W, "run_warm", lambda *a, **k: {
        "dates_considered": 5, "already_deep": 0, "attempted": 5,
        "warmed": 5, "failed": 0, "depth_gained": 0, "reached_target": 0,
        "capped": False, "failures": [],
    })
    with pytest.raises(RuntimeError, match="depth did not increase"):
        W.warm_sr3_eod_settles(dt.date(2026, 8, 17), dt.date(2026, 8, 18))


def test_job_reports_success_when_depth_actually_moved(monkeypatch):
    monkeypatch.setattr(W, "run_warm", lambda *a, **k: {
        "dates_considered": 5, "already_deep": 1, "attempted": 4,
        "warmed": 4, "failed": 0, "depth_gained": 4, "reached_target": 4,
        "capped": False, "failures": [],
    })
    msg = W.warm_sr3_eod_settles(dt.date(2026, 8, 17), dt.date(2026, 8, 18))
    assert "4 warmed" in msg and "1 already deep" in msg


def test_no_business_days_is_a_noop_not_a_failure(monkeypatch):
    monkeypatch.setattr(W, "run_warm", lambda *a, **k: {
        "dates_considered": 0, "warmed": 0, "skipped": 0, "failed": 0})
    assert W.warm_sr3_eod_settles(dt.date(2026, 8, 15), dt.date(2026, 8, 16)) is None


def test_registered_in_the_daily_warmer_and_ordering_still_holds():
    from scripts.daily_cache_warmer import WARM_JOBS
    from utils.warm_jobs import assert_ordered, assert_unique_providers

    names = [j.name for j in WARM_JOBS]
    assert "SR3 EOD settles (depth 20)" in names
    assert_ordered(WARM_JOBS)
    assert_unique_providers(WARM_JOBS)
