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
    assert (snap.second, snap.microsecond) == (0, 1), "nudged by one MICROSECOND, see the docstring"
    assert resolve_request(snap).mode == "intraday"


def test_snap_mtm_no_longer_emits_midnight_for_an_00_00_mark():
    """``snap_mtm`` floors without the minus-one, so it collides one minute earlier."""
    mts = book.snap_mtm(pd.Timestamp("2026-06-10 00:00:30", tz=ET))
    assert (mts.hour, mts.minute, mts.second, mts.microsecond) == (0, 0, 0, 1)
    assert resolve_request(mts).mode == "intraday"


@pytest.mark.parametrize(
    "printed,expected",
    [
        ("2026-06-10 00:01:00", (0, 0, 0, 1)),    # first second of the colliding minute
        ("2026-06-10 00:01:59", (0, 0, 0, 1)),    # last second of it
        ("2026-06-10 00:02:00", (0, 1, 0, 0)),    # one minute later: untouched
        ("2026-06-10 00:00:30", (23, 59, 0, 0)),  # decrements into the previous day
        ("2026-06-10 12:34:56", (12, 33, 0, 0)),  # the ordinary case
    ],
)
def test_only_the_colliding_minute_moves(printed, expected):
    snap = pricing.snap_timestamp(pd.Timestamp(printed, tz=ET), None)
    assert (snap.hour, snap.minute, snap.second, snap.microsecond) == expected


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
        if (snap.second, snap.microsecond) != (0, 0):
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


@pytest.mark.parametrize("value", ["live", None, pd.NaT, 42, datetime.date(2026, 6, 10)])
def test_as_intraday_instant_passes_through_anything_that_is_not_a_midnight_datetime(value):
    """It shares one definition of "ambiguous" with is_ambiguous_midnight.

    An earlier draft parsed the value itself and would have raised on "live" -
    which the curve APIs accept - so the two helpers now agree by construction
    rather than by both being edited together.
    """
    out = pricing.as_intraday_instant(value)
    assert out is value or out == value


def test_the_nudge_keeps_the_type_and_the_offset():
    naive = datetime.datetime(2026, 6, 10, 0, 0)
    assert pricing.as_intraday_instant(naive) == datetime.datetime(2026, 6, 10, 0, 0, 0, 1)

    aware = NY.localize(datetime.datetime(2026, 6, 10, 0, 0))
    out = pricing.as_intraday_instant(aware)
    assert isinstance(out, datetime.datetime)
    assert out.utcoffset() == aware.utcoffset(), "one second cannot cross a DST change"
    assert out.tzinfo is aware.tzinfo

    ts = pd.Timestamp("2026-06-10 00:00", tz=ET)
    assert isinstance(pricing.as_intraday_instant(ts), pd.Timestamp)


def test_the_nudge_does_not_change_which_snapshot_is_selected():
    """Invariant (B), arithmetically rather than by assertion.

    Citi's last row before the hole is 22:59 ET and its first after is 01:00 ET.
    From 00:00:00 those are 3,660 s back and 3,600 s forward; from 00:00:01 they
    are 3,661 and 3,599. Nearest picks the 01:00 row from both, as-of picks the
    22:59 row from both. Neither rule changes its answer - and note there is no
    exact tie at midnight to break, which was the thing worth checking.
    """
    import numpy as np

    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotPolicy, select_snapshot

    prev_close = pd.Timestamp("2026-06-09 22:59", tz=ET).tz_convert("UTC")
    next_open = pd.Timestamp("2026-06-10 01:00", tz=ET).tz_convert("UTC")
    stamps = np.array([prev_close.value, next_open.value], dtype=np.int64)

    for spelling in ("2026-06-10 00:00:00", "2026-06-10 00:00:01"):
        wanted = pd.Timestamp(spelling, tz=ET).tz_convert("UTC").value
        assert select_snapshot(stamps, wanted, SnapshotPolicy.legacy()).position == 1
        asof = SnapshotPolicy(method="asof", max_lag=datetime.timedelta(hours=3))
        assert select_snapshot(stamps, wanted, asof).position == 0


def test_a_pre_seeded_midnight_key_is_still_refused_by_handle():
    """The guard has to sit BEFORE the cache lookup, not only inside build.

    ``curve_warm.warm_pricer`` and ``_bulk_seed`` write straight into
    ``_handles``. A key seeded that way is returned without ``build`` ever
    running, so a guard living only in ``build`` would be bypassed by exactly
    the path most likely to carry a bad timestamp in bulk.
    """
    class _MDP:
        def _get_curve(self, curve_name, timestamp):
            raise AssertionError("should not be reached")

    p = pricing.CurvePricer(mdp=_MDP())
    midnight = NY.localize(datetime.datetime(2026, 6, 10, 0, 0))
    p._handles[("USD-SOFR-1D", midnight)] = "A CURVE FROM THE CLOSE"

    with pytest.raises(ValueError, match="exactly midnight"):
        p.handle("USD-SOFR-1D", midnight)


# --------------------------------------------------------------------------- #
#      the nudge must be invisible to the CURRENT production store lookup     #
# --------------------------------------------------------------------------- #


def test_the_nudge_does_not_change_the_barchart_curve_store_key():
    """The regression an earlier draft of this fix actually caused.

    ``BARCHART_STIRF-RL`` is ``config.CURVE_SOURCE`` - the source the classifier
    runs on today - and its CurveStore fast path matches by EXACT key equality.
    ``_curve_store_timestamp_key`` ends with ``value.replace(microsecond=0)``: it
    discards microseconds and **keeps seconds**. So a one-second nudge changed
    the key, missed a store whose rows are all stamped on whole minutes, and fell
    through to a live Barchart build - slower, network-bound, never written back,
    and free to calibrate a different curve than the stored one.

    A microsecond is zeroed by that key and tested by ``resolve_request``. This
    test is the reason it is a microsecond.
    """
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    midnight = NY.localize(datetime.datetime(2026, 1, 5, 0, 0))
    nudged = pricing.as_intraday_instant(midnight)

    assert nudged != midnight, "the value must still change, or resolve_request is unfixed"
    assert IRSwapsMDP._curve_store_timestamp_key(nudged) == \
        IRSwapsMDP._curve_store_timestamp_key(midnight), (
        "the barchart store key must be identical, or every 00:01 ET leg on the "
        "live source turns a Parquet read into a vendor build"
    )


def test_a_one_second_nudge_would_have_broken_that_key():
    """Pins the counterfactual, so the choice of unit cannot be casually widened."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    midnight = NY.localize(datetime.datetime(2026, 1, 5, 0, 0))
    one_second = midnight + datetime.timedelta(seconds=1)
    assert IRSwapsMDP._curve_store_timestamp_key(one_second) != \
        IRSwapsMDP._curve_store_timestamp_key(midnight)


def test_the_nudge_still_flips_resolve_request_to_intraday():
    """The other consumer, which tests microsecond - so a microsecond suffices."""
    midnight = NY.localize(datetime.datetime(2026, 6, 10, 0, 0))
    assert resolve_request(midnight).mode == "eod"
    assert resolve_request(pricing.as_intraday_instant(midnight)).mode == "intraday"


def _np_units():
    import numpy as np

    return [
        np.datetime64("2026-06-10T00:00:00").astype(f"datetime64[{u}]")
        for u in ("Y", "M", "W", "D", "h", "m", "s", "ms", "us", "ns")
    ]


@pytest.mark.parametrize(
    "value",
    ["2026-06-10", "2026-06-10 00:00:00", "2026-06-10T00:00:00-04:00"] + _np_units(),
    ids=str,
)
def test_every_admitted_type_is_actually_nudgeable(value):
    """The classifier's domain must not exceed the nudge's, in either direction.

    ``is_ambiguous_midnight`` admits datetimes, numpy datetime64 and strings,
    because it has to predict what ``resolve_request`` will do and that accepts
    all three. But raw ``+ timedelta`` is undefined for a str, resolution-
    dependent for datetime64, and a review found the three distinct outcomes:
    a str raised TypeError, a **day**-unit datetime64 silently returned an
    unchanged midnight - a no-op on exactly the input this exists to repair -
    and an **ns**-unit one raised TypeError from int arithmetic. Only the
    second-to-microsecond units happened to work.

    Every unit is swept because "I checked the ones I thought of" is how the
    day and nanosecond ends were missed the first time.
    """
    out = pricing.as_intraday_instant(value)
    assert isinstance(out, pd.Timestamp)
    assert out.microsecond == 1
    assert resolve_request(out).mode == "intraday"


def test_a_non_midnight_string_is_still_returned_byte_identical():
    """Invariant (A) has to survive the normalisation, not just the nudge."""
    value = "2026-06-10 09:30:00"
    assert pricing.as_intraday_instant(value) is value


def test_the_int_asymmetry_is_a_decision_not_an_accident():
    """``resolve_request(42)`` says eod; ``is_ambiguous_midnight(42)`` says no.

    Both are right for their own job. ``resolve_request`` parses whatever it is
    handed, so a bare int becomes 42 nanoseconds past the epoch and reads as
    midnight. This predicate deliberately declines to chase that: nudging ``42``
    to ``1970-01-01 00:00:00.000001`` and reporting success is a worse answer
    than letting a non-temporal input fail as the type error it is.

    Pinned so the asymmetry is a documented choice rather than something a later
    reader has to rediscover - a review found it by measurement, not by reading.
    """
    assert resolve_request(42).mode == "eod"
    assert pricing.is_ambiguous_midnight(42) is False
    assert pricing.as_intraday_instant(42) == 42
