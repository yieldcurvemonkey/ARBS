"""Tests for the recurring SR3 EOD settle warm.

Three things are worth pinning, and they are the three that were actually wrong
or nearly wrong while building it:

* the strip is *consecutive quarterlies* at the requested depth (a warm that
  fetches the wrong symbols writes keys nobody reads);
* ``_depth_by_date`` must force its own floor of 1, because
  ``strip_depth_by_date`` *omits* any date below the configured floor --
  leaving it at the default makes the warm blind to precisely the dates it
  exists to fill. (That default was 12 when this was written, which was itself
  the cause of the sparse CA series; it is 4 since 2026-08-19. The guard is
  written against the mechanism so it survives the number changing.) And
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


def test_depth_by_date_sees_dates_a_floored_config_hides(tmp_path):
    """The regression guard: any depth floor hides the dates the warm exists for.

    Two things changed under this test and both are worth recording.

    It was originally written against ``strip_depth_by_date``'s default of
    ``min_instruments=12``. That default was **the** cause of the sparse CA
    series and was corrected to 4 on 2026-08-19 (see
    ``tests/test_convexity_rv_ca_coverage.py``), so the guard is now expressed
    against the mechanism rather than against one historical number: a config
    floored at ``f`` cannot see a date shallower than ``f``, whatever ``f`` is,
    and the warm must therefore keep forcing its own floor of 1.

    It also read the LIVE store and asserted that the window 2026-07..08 held
    shallow dates -- which stopped being true the moment
    ``scripts/warm_sr3_deferred.py`` filled that window to depth 20. A test whose
    fixture is deleted by the job it is testing is not a regression guard, so the
    mechanism is now pinned on a synthetic shard and the live store is only
    reported.
    """
    import sqlite3

    from RVUtils.ConvexityRV.packs import quarterly_imm_sequence
    from RVUtils.ConvexityRV.strat2_q20 import Q20Config, strip_depth_by_date
    from RVUtils.ConvexityRV.strat2_sofr_convexity import (
        futures_symbol, ny_utc_offset)

    day = dt.date(2026, 7, 8)
    keys = [f"{day.isoformat()}T17:00:00{ny_utc_offset(day)}-"
            f"{futures_symbol(y, m)}-BARCHART_STIRF-RL"
            for y, m in quarterly_imm_sequence(day, 6)]      # a 6-deep date
    shard = tmp_path / "000"
    shard.mkdir(parents=True)
    con = sqlite3.connect(shard / "cache.db")
    con.execute("CREATE TABLE Cache (rowid INTEGER PRIMARY KEY, key TEXT)")
    con.executemany("INSERT INTO Cache (key) VALUES (?)", [(k,) for k in keys])
    con.commit()
    con.close()

    cfg = Q20Config(max_instruments=20, start=day, end=day)
    assert strip_depth_by_date(cfg, cache_root=str(tmp_path),
                               min_depth=1) == {day: 6}, "the warm's lens"
    assert strip_depth_by_date(cfg, cache_root=str(tmp_path),
                               min_depth=12) == {}, "a floored config is blind to it"

    # And the shipped default is no longer a 12-deep floor, which is the fix.
    assert Q20Config().min_strip_depth == 4
    assert Q20Config().min_instruments == 4


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


# ---------------------------------------------------------------------------
# The helper the test above is NAMED for, but never called
# ---------------------------------------------------------------------------
def test_depth_by_date_forces_its_own_floor_through_to_the_scan(monkeypatch):
    """``W._depth_by_date`` must pass ``min_depth=1``, not merely set min_instruments.

    ``test_depth_by_date_sees_dates_a_floored_config_hides`` asserts on
    ``strip_depth_by_date`` directly and never touches ``W._depth_by_date``, so
    it passed for as long as the helper it is named for was blind. ``9df2875a``
    moved universe admission from ``min_instruments`` to ``min_strip_depth``
    (default 4) and the helper was not updated, so it stopped seeing every date
    below depth 4 -- the common case for a cold date, and exactly what a warm
    exists to find.
    """
    import RVUtils.ConvexityRV.strat2_q20 as Q

    seen = {}

    def _spy(cfg, **kwargs):
        seen.update(kwargs)
        seen["min_strip_depth"] = cfg.min_strip_depth
        return {}

    monkeypatch.setattr(Q, "strip_depth_by_date", _spy)
    W._depth_by_date(20, dt.date(2026, 7, 1), dt.date(2026, 7, 31))

    assert seen.get("min_depth") == 1, (
        "the warm's depth scan does not override the universe floor, so every "
        f"date below min_strip_depth={seen.get('min_strip_depth')} is invisible "
        "to it"
    )


def test_depth_by_date_reports_a_shallow_date(monkeypatch):
    """Behavioural version: a depth-2 date must survive the helper.

    The stub reproduces the real admission rule -- a date is dropped when its
    depth is below ``min_depth`` if given, else below ``cfg.min_strip_depth`` --
    so this fails whenever the helper stops overriding the floor.
    """
    import RVUtils.ConvexityRV.strat2_q20 as Q

    shallow, deep = dt.date(2026, 7, 8), dt.date(2026, 7, 9)
    truth = {shallow: 2, deep: 6}

    def _stub(cfg, **kwargs):
        floor = kwargs.get("min_depth")
        if floor is None:
            floor = cfg.min_strip_depth
        return {d: n for d, n in truth.items() if n >= floor}

    monkeypatch.setattr(Q, "strip_depth_by_date", _stub)
    got = W._depth_by_date(20, shallow, deep)

    assert shallow in got and got[shallow] == 2, (
        f"the depth-2 date is invisible to the warm: {got}. Its acceptance test "
        "would then read before[d]=0 and score a genuine 2->3 gain as no gain."
    )


# ---------------------------------------------------------------------------
# Never warm a session that has not settled
# ---------------------------------------------------------------------------
def test_session_has_settled_is_a_clock_test_not_a_calendar_test():
    """Yesterday always; today only after the settle; tomorrow never.

    A flat ``d >= today`` refusal -- which is what ``warm_sr3_deferred`` does --
    would make this nightly a no-op every night, since its whole job is the
    session that just closed. The hazard is fetching before the settle exists,
    so the test is on the clock.
    """
    noon = dt.datetime(2026, 7, 9, 12, 0)
    evening = dt.datetime(2026, 7, 9, 18, 15)
    today, yesterday = dt.date(2026, 7, 9), dt.date(2026, 7, 8)
    tomorrow = dt.date(2026, 7, 10)

    assert W._session_has_settled(yesterday, now_et=noon)
    assert not W._session_has_settled(today, now_et=noon), (
        "warming the live session files an intraday print under a 17:00 "
        "settlement alias")
    assert W._session_has_settled(today, now_et=evening), (
        "the 18:15 ET slot is after the ~15:00 ET SR3 settle; refusing here "
        "would make the nightly do nothing at all")
    assert not W._session_has_settled(tomorrow, now_et=evening)


def test_run_warm_refuses_an_unsettled_session(monkeypatch):
    """`run_warm` must not fetch a date whose session is still open."""
    today = dt.date.today()

    def _boom(*a, **k):
        raise AssertionError("run_warm fetched an unsettled session")

    monkeypatch.setattr(W, "warm_one_date", _boom)
    monkeypatch.setattr(W, "_business_days", lambda s, e: [today])
    monkeypatch.setattr(W, "_session_has_settled", lambda d, **k: False)
    monkeypatch.setattr(W, "_depth_by_date", lambda *a, **k: {})

    out = W.run_warm(today, today, depth=20)
    assert out["warmed"] == 0
    assert out.get("skipped_unsettled") == 1, out
