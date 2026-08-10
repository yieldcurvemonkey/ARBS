r"""The measured Citi USD publication schedule.

Every number here comes from the store, not from a convention: 815 stored days
of USD-SOFR-1D and 794 of USD-FEDFUNDS-1D, split by DST regime so that each
boundary's anchoring is established rather than assumed. The week runs on a UTC
clock (Sunday 21:00 open, Friday 22:00 close) and the day runs on a New York one
(01:00-22:59 ET), and the tests below pin both halves of that split - because a
model that got the anchoring backwards would agree with the data for most of the
year and disagree twice, in March and November.
"""

from __future__ import annotations

import datetime
import zoneinfo

import pandas as pd
import pytest

from MDP.IRSwaps.CITIVELO_EXCEL.citi_session import (
    CITI_USD_SESSION,
    UnknownSessionError,
    expected_minutes,
    is_truncated,
    publishes,
)

ET = zoneinfo.ZoneInfo("America/New_York")
CURVE = "USD-SOFR-1D"


def et(s):
    return pd.Timestamp(s, tz=ET)


def utc(s):
    return pd.Timestamp(s, tz="UTC")


# --------------------------------------------------------------------------- #
#                    the daily gap is anchored in NEW YORK                    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "day,label",
    [("2026-06-17", "EDT"), ("2026-01-14", "EST")],   # both a Wednesday
)
def test_the_day_runs_01_00_to_22_59_ET_in_both_dst_regimes(day, label):
    assert publishes(CURVE, et(f"{day} 01:00")) is True, label
    assert publishes(CURVE, et(f"{day} 22:59")) is True, label
    assert publishes(CURVE, et(f"{day} 00:59")) is False, label
    assert publishes(CURVE, et(f"{day} 23:00")) is False, label


def test_the_gap_moves_in_UTC_across_dst_which_is_the_whole_point():
    """Measured: first row 05:00 UTC in summer and 06:00 UTC in winter.

    A model anchored in UTC would put the gap at one fixed UTC hour and be wrong
    for half the year. This is the test that separates the two.
    """
    assert publishes(CURVE, utc("2026-06-17 05:00")) is True     # 01:00 EDT
    assert publishes(CURVE, utc("2026-06-17 04:59")) is False    # 00:59 EDT
    assert publishes(CURVE, utc("2026-01-14 06:00")) is True     # 01:00 EST
    assert publishes(CURVE, utc("2026-01-14 05:59")) is False    # 00:59 EST


@pytest.mark.parametrize("day", ["2026-03-08", "2026-11-01"])
def test_both_dst_transitions_fall_inside_the_weekend(day):
    """A property worth having, not just a case that must not crash.

    US DST transitions are always a Sunday, and this session is shut all Sunday
    morning - so the skipped hour (02:00-02:59 ET on spring forward) and the
    repeated one (01:00-01:59 ET on fall back) both land in the weekend. The
    ambiguous-timestamp problem that ``from_wire_naive`` has to resolve for the
    wire simply never reaches a published USD minute.
    """
    assert publishes(CURVE, et(f"{day} 00:30")) is False
    assert publishes(CURVE, et(f"{day} 10:00")) is False, "transition days are Sundays"
    # ...and the Sunday evening open and the Monday after are both normal.
    assert publishes(CURVE, utc(f"{day} 21:00")) is True
    monday = datetime.date.fromisoformat(day) + datetime.timedelta(days=1)
    assert publishes(CURVE, et(f"{monday} 10:00")) is True
    assert expected_minutes(CURVE, monday) == 1320


# --------------------------------------------------------------------------- #
#                     the week is anchored in UTC                             #
# --------------------------------------------------------------------------- #


def test_the_week_opens_sunday_21_00_utc_in_both_regimes():
    assert publishes(CURVE, utc("2026-06-14 21:00")) is True     # Sun, 17:00 EDT
    assert publishes(CURVE, utc("2026-06-14 20:59")) is False
    assert publishes(CURVE, utc("2026-01-11 21:00")) is True     # Sun, 16:00 EST
    assert publishes(CURVE, utc("2026-01-11 20:59")) is False


def test_the_week_closes_friday_22_00_utc_in_both_regimes():
    assert publishes(CURVE, utc("2026-06-19 21:59")) is True     # Fri, 17:59 EDT
    assert publishes(CURVE, utc("2026-06-19 22:00")) is False
    assert publishes(CURVE, utc("2026-01-16 21:59")) is True     # Fri, 16:59 EST
    assert publishes(CURVE, utc("2026-01-16 22:00")) is False


def test_friday_evening_and_saturday_are_the_weekend_not_a_gap_in_our_data():
    """The distinction the whole module exists for.

    A Friday 20:00 ET request looks exactly like a truncated day from the
    store's point of view - the stored day ends at 17:59 - and it is not. No
    fetch will ever produce it.
    """
    assert publishes(CURVE, et("2026-06-19 20:00")) is False
    assert publishes(CURVE, et("2026-06-20 10:00")) is False     # Saturday
    assert publishes(CURVE, et("2026-06-21 10:00")) is False     # Sunday morning
    assert publishes(CURVE, et("2026-06-21 17:00")) is True      # Sunday open, EDT


def test_a_naive_instant_is_refused():
    with pytest.raises(ValueError, match="tz-aware"):
        publishes(CURVE, pd.Timestamp("2026-06-17 10:00"))


# --------------------------------------------------------------------------- #
#                       per-date bounds and expected counts                   #
# --------------------------------------------------------------------------- #


def test_a_normal_weekday_has_1320_publishable_minutes():
    """01:00-22:59 inclusive = 22 h = 1,320 minutes.

    Which is exactly the row count of a full stored day: measured 1,320 on
    2024-07-02, 2025-01-01, 2026-06-17.
    """
    assert expected_minutes(CURVE, datetime.date(2026, 6, 17)) == 1320


def test_friday_is_shorter_and_by_a_dst_dependent_amount():
    """Friday stops at 21:59 UTC: 17:59 ET on daylight time, 16:59 on standard."""
    edt = expected_minutes(CURVE, datetime.date(2026, 6, 19))
    est = expected_minutes(CURVE, datetime.date(2026, 1, 16))
    assert edt == 17 * 60      # 01:00 -> 17:59 inclusive = 1,020 minutes
    assert est == 16 * 60      # 01:00 -> 16:59 inclusive =   960 minutes
    assert edt - est == 60, "the Friday close is UTC-anchored, so its ET length moves"


def test_saturday_has_none_and_sunday_only_the_evening():
    assert expected_minutes(CURVE, datetime.date(2026, 6, 20)) == 0
    # Sunday opens 21:00 UTC = 17:00 EDT, runs to 22:59 ET -> 6 hours.
    assert expected_minutes(CURVE, datetime.date(2026, 6, 21)) == 6 * 60


def test_us_holidays_publish_normally():
    """Measured on eighteen of them; the data has no holiday calendar.

    2025-12-25 held 1,318 rows running 01:00-22:59, indistinguishable from a
    control Wednesday. A model with a holiday carve-out would have called that
    day's 1,318 real minutes missing.
    """
    assert expected_minutes(CURVE, datetime.date(2025, 12, 25)) == 1320
    assert publishes(CURVE, et("2025-12-25 14:00")) is True


# --------------------------------------------------------------------------- #
#                    truncated day vs genuinely short day                     #
# --------------------------------------------------------------------------- #


def test_the_23_59_utc_ending_is_detected_as_truncation_in_both_regimes():
    """19:59 ET on EDT and 18:59 ET on EST are the same UTC instant.

    27 of 144 EDT Mon-Thu days and 27 of 140 EST ones end there - the same count
    on a UTC clock, which no market event produces.
    """
    assert is_truncated(CURVE, datetime.date(2026, 6, 17), utc("2026-06-17 23:59")) is True
    assert is_truncated(CURVE, datetime.date(2026, 1, 14), utc("2026-01-14 23:59")) is True


def test_a_full_weekday_is_not_truncated():
    assert is_truncated(CURVE, datetime.date(2026, 6, 17), et("2026-06-17 22:59")) is False


def test_fridays_early_close_is_not_truncation():
    """The failure mode in the other direction, and the more damaging one.

    A repair pass driven by a rule that flagged Friday would re-fetch 136 days a
    year that are already complete, and - worse - a completeness gate that
    treated 19:59 as a normal weekday close would mark the genuinely truncated
    days done and never repair them.
    """
    assert is_truncated(CURVE, datetime.date(2026, 6, 19), et("2026-06-19 17:59")) is False
    assert is_truncated(CURVE, datetime.date(2026, 1, 16), et("2026-01-16 16:59")) is False


def test_sundays_late_open_is_not_truncation():
    assert is_truncated(CURVE, datetime.date(2026, 6, 21), et("2026-06-21 22:59")) is False


def test_saturday_can_never_be_truncated():
    assert is_truncated(CURVE, datetime.date(2026, 6, 20), et("2026-06-20 12:00")) is False


# --------------------------------------------------------------------------- #
#                     the model refuses what it did not measure               #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("curve", ["GBP-SONIA-1D", "EUR-ESTR-1D", "JPY-TONAR-1D"])
def test_an_unmeasured_curve_raises_rather_than_inheriting_the_usd_anatomy(curve):
    """GBP runs 08:00-19:59 LONDON - 12 hours, not 22, and on a different clock.

    Silently answering for it with the USD model would report most of a GBP
    trading day as "Citi published nothing", which is both wrong and confident.
    """
    with pytest.raises(UnknownSessionError, match="No measured Citi session model"):
        publishes(curve, et("2026-06-17 10:00"))


def test_both_usd_curves_are_modelled():
    for curve in ("USD-SOFR-1D", "USD-FEDFUNDS-1D"):
        assert publishes(curve, et("2026-06-17 10:00")) is True


def test_bounds_walk_in_rather_than_assuming_a_fixed_wall_clock():
    """Sunday's first publishable minute is not a fixed ET time.

    It is 17:00 ET in summer and 16:00 ET in winter, because the weekly open is
    UTC-anchored. A bounds helper that returned a constant would be wrong for
    half the year.
    """
    summer = CITI_USD_SESSION.bounds_for_local_date(datetime.date(2026, 6, 21))
    winter = CITI_USD_SESSION.bounds_for_local_date(datetime.date(2026, 1, 11))
    assert summer[0].tz_convert(ET).hour == 17
    assert winter[0].tz_convert(ET).hour == 16
    assert summer[0].tz_convert("UTC").hour == winter[0].tz_convert("UTC").hour == 21
