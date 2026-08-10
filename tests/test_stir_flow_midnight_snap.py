r"""Exact midnight ET is a value that means something else downstream.

The chain, all of it production code:

1. ``stir_flow.pricing.snap_timestamp`` floors a print to the minute and
   subtracts one, so a print in the **00:01 ET** minute becomes exactly
   00:00:00 ET. ``book.snap_mtm`` floors without the decrement, so a print in
   the **00:00 ET** minute does the same.
2. ``CITIVELO_EXCEL.timestamps.resolve_request`` reads a datetime at exactly
   00:00:00 as **end of day** - on purpose, because ``pd.Timestamp("2026-08-06")``
   is how people spell "that day".
3. ``IRSwapsMDP._build_citivelo_excel_curve`` therefore routes it to
   ``_load_citivelo_excel_curve_store_point``, which serves the **last row of
   that day's EOD partition** - the close, roughly sixteen hours AFTER the print.

For dealer direction that is not staleness, it is **lookahead**: the close of
day D contains the trade being classified, so the inference is circular in
exactly the way the rest of this work exists to prevent. 256 SOFR legs and 3 Fed
Funds legs on the ``_v3`` tape land on it, silently.

Note which end is fixed. ``resolve_request``'s rule is correct for the API it
belongs to and is left alone; what changes is that the two *snapshot rules* stop
emitting a value that means end-of-day when they mean an instant, using the
escape hatch that ``resolve_request`` documents.
"""

from __future__ import annotations

import datetime
import zoneinfo

import pandas as pd
import pytest
import pytz

from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import resolve_request
from SDRUtils.stir_flow import book, pricing

NY = pytz.timezone("America/New_York")
ET = zoneinfo.ZoneInfo("America/New_York")


# --------------------------------------------------------------------------- #
#            the bug, reproduced against the rules as they shipped            #
# --------------------------------------------------------------------------- #


def test_the_shipped_snap_rule_lands_on_exact_midnight():
    """Written out longhand so it keeps demonstrating the defect after the fix."""
    printed = pd.Timestamp("2026-06-10 00:01:30", tz=ET)
    et = printed.tz_convert(NY).replace(second=0, microsecond=0) - pd.Timedelta(minutes=1)
    shipped = NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))
    assert (shipped.hour, shipped.minute, shipped.second) == (0, 0, 0)


def test_resolve_request_reads_exact_midnight_as_end_of_day():
    """The other half of the collision, also as shipped."""
    midnight = NY.localize(datetime.datetime(2026, 6, 10, 0, 0))
    mode = resolve_request(midnight)
    assert mode.mode == "eod"
    assert mode.eod_date == datetime.date(2026, 6, 10)


def test_the_two_together_would_ask_for_the_close_of_the_trade_s_own_day():
    """The composition is the bug: a 00:01 print asking for that day's close."""
    printed = pd.Timestamp("2026-06-10 00:01:30", tz=ET)
    et = printed.tz_convert(NY).replace(second=0, microsecond=0) - pd.Timedelta(minutes=1)
    shipped = NY.localize(datetime.datetime(et.year, et.month, et.day, et.hour, et.minute))
    mode = resolve_request(shipped)
    assert mode.mode == "eod" and mode.eod_date == printed.date(), (
        "the request resolves to the close of the very day the trade printed on"
    )


# --------------------------------------------------------------------------- #
#                            the fix, at the producers                        #
# --------------------------------------------------------------------------- #


def test_snap_timestamp_no_longer_emits_midnight_for_an_00_01_print():
    snap = pricing.snap_timestamp(pd.Timestamp("2026-06-10 00:01:30", tz=ET), None)
    assert (snap.hour, snap.minute) == (0, 0)
    assert snap.second == 1, "nudged by exactly one second, per resolve_request's own advice"
    assert resolve_request(snap).mode == "intraday"


def test_snap_mtm_no_longer_emits_midnight_for_an_00_00_mark():
    """``snap_mtm`` floors without the minus-one, so it collides one minute earlier."""
    mts = book.snap_mtm(pd.Timestamp("2026-06-10 00:00:30", tz=ET))
    assert (mts.hour, mts.minute, mts.second) == (0, 0, 1)
    assert resolve_request(mts).mode == "intraday"


@pytest.mark.parametrize(
    "printed,expected",
    [
        ("2026-06-10 00:01:00", (0, 0, 1)),    # first second of the colliding minute
        ("2026-06-10 00:01:59", (0, 0, 1)),    # last second of it
        ("2026-06-10 00:02:00", (0, 1, 0)),    # one minute later: untouched
        ("2026-06-10 00:00:30", (23, 59, 0)),  # decrements into the previous day
        ("2026-06-10 12:34:56", (12, 33, 0)),  # the ordinary case
    ],
)
def test_only_the_colliding_minute_moves(printed, expected):
    snap = pricing.snap_timestamp(pd.Timestamp(printed, tz=ET), None)
    assert (snap.hour, snap.minute, snap.second) == expected


def test_the_00_00_print_decrements_into_the_previous_day_not_midnight():
    """Worth pinning: the minus-one already saves the 00:00 minute for snap_timestamp."""
    snap = pricing.snap_timestamp(pd.Timestamp("2026-06-10 00:00:30", tz=ET), None)
    assert snap.date() == datetime.date(2026, 6, 9)
    assert resolve_request(snap).mode == "intraday"


def test_every_other_minute_of_the_day_is_returned_untouched():
    """The nudge must be surgical: it changes cache keys and stored curve_timestamps.

    ``backfill_stir_direction`` persists this value as ``curve_timestamp``, so a
    rule that shifted every request by a second would rewrite the meaning of
    every stored row to fix 256 of them.
    """
    base = pd.Timestamp("2026-06-10 00:00", tz=ET)
    moved = []
    for m in range(1, 24 * 60):
        printed = base + pd.Timedelta(minutes=m) + pd.Timedelta(seconds=30)
        snap = pricing.snap_timestamp(printed, None)
        if snap.second != 0:
            moved.append(printed)
    assert len(moved) == 1, f"exactly one minute of the day should move, got {len(moved)}"
    assert moved[0].hour == 0 and moved[0].minute == 1


# --------------------------------------------------------------------------- #
#                         as_intraday_instant on its own                      #
# --------------------------------------------------------------------------- #


def test_a_bare_date_is_left_alone_because_it_unambiguously_means_eod():
    day = datetime.date(2026, 6, 10)
    assert pricing.as_intraday_instant(day) is day
    assert pricing.is_ambiguous_midnight(day) is False


def test_a_midnight_pandas_timestamp_is_ambiguous_but_a_date_is_not():
    assert pricing.is_ambiguous_midnight(pd.Timestamp("2026-06-10")) is True
    assert pricing.is_ambiguous_midnight(pd.Timestamp("2026-06-10 00:00:01")) is False
    assert pricing.is_ambiguous_midnight(datetime.date(2026, 6, 10)) is False
    assert pricing.is_ambiguous_midnight(None) is False
    assert pricing.is_ambiguous_midnight(pd.NaT) is False
    assert pricing.is_ambiguous_midnight("live") is False


def test_the_nudge_is_idempotent():
    once = pricing.as_intraday_instant(NY.localize(datetime.datetime(2026, 6, 10)))
    assert pricing.as_intraday_instant(once) == once


# --------------------------------------------------------------------------- #
#                       the tripwire at the chokepoint                        #
# --------------------------------------------------------------------------- #


def test_curve_pricer_refuses_a_bare_midnight_datetime():
    """Unreachable if the producers are right - which is the point of having it.

    The next snapshot rule someone writes will not know about the collision.
    """
    class _MDP:
        def _get_curve(self, curve_name, timestamp):
            raise AssertionError("must not reach the source with an ambiguous midnight")

    p = pricing.CurvePricer(mdp=_MDP())
    with pytest.raises(ValueError, match="exactly midnight"):
        p.handle("USD-SOFR-1D", NY.localize(datetime.datetime(2026, 6, 10, 0, 0)))


def test_curve_pricer_still_accepts_a_date_and_a_nudged_instant():
    seen = []

    class _MDP:
        def _get_curve(self, curve_name, timestamp):
            seen.append(timestamp)
            return object()

    p = pricing.CurvePricer(mdp=_MDP())
    p.handle("USD-SOFR-1D", datetime.date(2026, 6, 10))
    p.handle("USD-SOFR-1D", NY.localize(datetime.datetime(2026, 6, 10, 0, 0, 1)))
    assert len(seen) == 2


# --------------------------------------------------------------------------- #
#              end to end, through the dispatch the refactor uses             #
# --------------------------------------------------------------------------- #


def test_a_00_01_print_reaches_the_MINUTE_store_not_the_eod_store(monkeypatch):
    """The whole chain, on the source the direction work is moving to.

    print -> snap_timestamp -> _build_citivelo_excel_curve. Before the fix this
    landed in the EOD branch and was answered with the close of the trade's own
    day; the assertion here is simply which loader runs.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    routed = []
    monkeypatch.setattr(
        IRSwapsMDP, "_load_citivelo_excel_minute_store_point",
        lambda self, **kw: routed.append(("minute", kw["timestamp"])) or "MINUTE",
    )
    monkeypatch.setattr(
        IRSwapsMDP, "_load_citivelo_excel_curve_store_point",
        lambda self, **kw: routed.append(("eod", kw["trading_date"])) or "EOD",
    )

    printed = pd.Timestamp("2026-06-10 00:01:30", tz=ET)
    snap = pricing.snap_timestamp(printed, None)

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    got = mdp._build_citivelo_excel_curve(curve_name="USD-SOFR-1D", timestamp=snap, kwargs={})

    assert got == "MINUTE", f"routed to {routed}"
    assert [r[0] for r in routed] == ["minute"]
    # and the instant handed to the loader still predates the print
    assert pd.Timestamp(routed[0][1]) < printed


def test_the_same_print_under_a_strict_policy_is_refused_rather_than_closed(monkeypatch):
    """Belt and braces: even if a producer regressed, strict must not serve a close."""
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss, SnapshotPolicy
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    monkeypatch.setattr(
        IRSwapsMDP, "_load_citivelo_excel_curve_store_point",
        lambda self, **kw: pytest.fail("a strict request reached the end-of-day store"),
    )
    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    midnight = NY.localize(datetime.datetime(2026, 6, 10, 0, 0))
    with pytest.raises(SnapshotMiss, match="END OF DAY"):
        mdp._build_citivelo_excel_curve(
            curve_name="USD-SOFR-1D", timestamp=midnight,
            kwargs={"snapshot_policy": SnapshotPolicy.strict(minutes=1)},
        )
