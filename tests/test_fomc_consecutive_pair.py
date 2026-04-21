"""Tests for consecutive_meeting_pair helper.

Verifies that a pair of dates is classified as consecutive FOMC meetings
iff the dates exactly match adjacent rows in the schedule (sorted by
effective_date).
"""
import pandas as pd
import pytest

from SDRUtils.analytics.fomc import (
    consecutive_meeting_pair,
    load_fomc_schedule,
)


@pytest.fixture
def schedule():
    sched = load_fomc_schedule()
    if sched.empty:
        pytest.skip("FOMC schedule unavailable in this env")
    return sched


def test_adjacent_meetings_are_consecutive(schedule):
    row0 = schedule.iloc[0]
    row1 = schedule.iloc[1]
    assert consecutive_meeting_pair(
        row0["effective_date"], row1["effective_date"], schedule
    ) is True


def test_skip_one_meeting_not_consecutive(schedule):
    row0 = schedule.iloc[0]
    row2 = schedule.iloc[2]
    assert consecutive_meeting_pair(
        row0["effective_date"], row2["effective_date"], schedule
    ) is False


def test_non_fomc_eff_returns_false(schedule):
    fake_eff = pd.Timestamp("2026-01-01")
    fake_mat = pd.Timestamp("2026-03-18")
    assert consecutive_meeting_pair(fake_eff, fake_mat, schedule) is False


def test_mat_equals_this_maturity_also_counts(schedule):
    """Effective-to-effective is the primary signal, but SDR may report
    maturity as row i's ``maturity_date`` (which equals row i+1's
    ``effective_date`` since meetings tile). Both should resolve to
    consecutive=True."""
    row0 = schedule.iloc[0]
    assert consecutive_meeting_pair(
        row0["effective_date"], row0["maturity_date"], schedule
    ) is True


def test_reversed_order_returns_false(schedule):
    row0 = schedule.iloc[0]
    row1 = schedule.iloc[1]
    assert consecutive_meeting_pair(
        row1["effective_date"], row0["effective_date"], schedule
    ) is False
