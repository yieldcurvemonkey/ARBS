"""A date the source will never serve must not be asked for, and must never stall a warm.

Both of these cost a real warm. `pd.bdate_range` returns weekdays, which includes market holidays;
the source serves no data on a holiday and its fetcher *hangs* rather than refusing, so one Labor
Day inside the requested range stalled two separate builds at 3% CPU. And because a chunked warm
calls the builder on growing prefixes, that dead date was re-attempted on every single chunk.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pytest

import BT.gss_fly.data as data_mod
from BT.gss_fly.data import build_curve_panel, ust_business_days
from tests.gss_fly.test_panel_cache import _FakeMDP


@pytest.fixture(autouse=True)
def _clear_failed_days():
    data_mod._FAILED_DAYS.clear()
    yield
    data_mod._FAILED_DAYS.clear()


def test_labor_day_is_a_weekday_but_not_a_trading_day():
    """The exact date that stalled the warm."""
    labor_day = datetime.date(2024, 9, 2)
    assert labor_day.weekday() < 5                                   # bdate_range would include it
    assert labor_day in {d.date() for d in pd.bdate_range("2024-09-01", "2024-09-06")}
    assert labor_day not in ust_business_days("2024-09-01", "2024-09-06")


def test_the_usual_suspects_are_excluded():
    days = set(ust_business_days("2024-01-01", "2024-12-31"))
    for holiday in (
        datetime.date(2024, 1, 1),    # New Year
        datetime.date(2024, 7, 4),    # Independence Day
        datetime.date(2024, 9, 2),    # Labor Day
        datetime.date(2024, 11, 28),  # Thanksgiving
        datetime.date(2024, 12, 25),  # Christmas
    ):
        assert holiday not in days, holiday
    # ...and a plain Tuesday is kept
    assert datetime.date(2024, 3, 12) in days


def test_ust_business_days_is_a_strict_subset_of_bdate_range():
    cal = set(ust_business_days("2024-01-01", "2024-12-31"))
    bd = {d.date() for d in pd.bdate_range("2024-01-01", "2024-12-31")}
    assert cal < bd
    assert len(bd) - len(cal) >= 9  # the UST calendar drops roughly ten sessions a year


def test_a_dead_date_is_attempted_a_bounded_number_of_times_not_once_per_chunk(tmp_path):
    """The chunked-warm pathology, in miniature.

    Days 0-3 resolve; day 4 never will. A chunked warm walks prefixes 3, 4, 5, 6 — without the
    guard the dead date is attempted on every prefix that contains it.

    The bound is `_MAX_DAY_ATTEMPTS`, not one. An absolute one-strike guard also blocks a
    TRANSIENT failure from ever being retried in the same process, which defeats the resume it
    was written to protect — that is a real bug this test used to enforce.
    """
    dates = [d.date() for d in pd.bdate_range("2025-03-03", periods=6)]
    mdp = _FakeMDP(dates, fail_from=4)
    cache = tmp_path / "panel"
    for end in (3, 4, 5, 6):
        build_curve_panel(dates[:end], mdp, cache_path=cache, show_progress=False,
                          consolidate="never", local_reference=False)

    dead = dates[4]
    n = mdp.spline_calls.count(dead)
    assert n <= data_mod._MAX_DAY_ATTEMPTS, f"unbounded retry: {n} attempts"
    assert n < 3, f"the dead date rode 3 chunks; the guard did not bind ({n})"
