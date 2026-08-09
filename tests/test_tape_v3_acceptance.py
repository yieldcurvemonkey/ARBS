"""Tests for scripts/tape_v3_acceptance.py criterion 1 (day-set parity).

No database connection is ever made: `evaluate_day_parity` is a pure
function over two `set[date]` inputs, extracted specifically so this
criterion is testable without mocking SQLAlchemy/psycopg2.
"""
from __future__ import annotations

from datetime import date

from scripts.tape_v3_acceptance import EXEMPT_MISSING_DAYS, evaluate_day_parity


def test_exempt_missing_days_is_exactly_the_two_documented_dates():
    """Guards against silent generalisation: if a future edit widens this
    to a computed rule (e.g. "any holiday" or "any day with a low v2
    count"), this test breaks and forces the author to look at it."""
    assert EXEMPT_MISSING_DAYS == frozenset({
        date(2026, 7, 3),
        date(2024, 10, 14),
    })


def test_missing_day_outside_exemption_set_still_fails():
    v2_days = {date(2026, 8, 5), date(2026, 8, 6), date(2026, 8, 7)}
    v3_days = {date(2026, 8, 5), date(2026, 8, 7)}  # 2026-08-06 missing, NOT exempt

    report_lines, failures = evaluate_day_parity(v3_days, v2_days)

    assert any("missing from v3" in f and "2026-08-06" in f for f in failures)


def test_exempted_missing_day_does_not_fail_and_is_reported():
    v2_days = {date(2026, 8, 5), date(2026, 7, 3)}
    v3_days = {date(2026, 8, 5)}  # 2026-07-03 missing, but IS exempt

    report_lines, failures = evaluate_day_parity(v3_days, v2_days)

    assert failures == []
    assert any("2026-07-03" in line for line in report_lines)
    assert any("1 exempted" in line for line in report_lines)


def test_both_exempted_days_missing_together_reports_both_and_passes():
    v2_days = {date(2026, 8, 5), date(2026, 7, 3), date(2024, 10, 14)}
    v3_days = {date(2026, 8, 5)}

    report_lines, failures = evaluate_day_parity(v3_days, v2_days)

    assert failures == []
    assert any(
        "2 exempted" in line and "2026-07-03" in line and "2024-10-14" in line
        for line in report_lines
    )


def test_non_exempt_missing_day_fails_even_when_an_exempt_day_is_also_missing():
    """Requirement 5: a real gap must still fail the criterion even when it
    is reported alongside a legitimately-exempted one -- the exemption must
    not mask other failures."""
    v2_days = {date(2026, 8, 6), date(2026, 7, 3)}
    v3_days = set()  # both 2026-08-06 (not exempt) and 2026-07-03 (exempt) missing

    report_lines, failures = evaluate_day_parity(v3_days, v2_days)

    assert any("missing from v3" in f and "2026-08-06" in f for f in failures)
    assert any("2026-07-03" in line for line in report_lines)


def test_exempted_day_unexpectedly_present_in_v3_fails_loudly():
    """Requirement 4: if an exempted day HAS rows in v3, the premise behind
    the exemption changed and that must fail the run, not pass silently."""
    v2_days = {date(2026, 7, 3)}
    v3_days = {date(2026, 7, 3)}  # premise changed: v3 now has this day

    report_lines, failures = evaluate_day_parity(v3_days, v2_days)

    assert any(
        "now present in v3" in f and "2026-07-03" in f and "EXEMPT_MISSING_DAYS" in f
        for f in failures
    )


def test_clean_day_parity_reports_zero_missing_zero_exempted():
    v2_days = {date(2026, 8, 5), date(2026, 8, 6)}
    v3_days = {date(2026, 8, 5), date(2026, 8, 6)}

    report_lines, failures = evaluate_day_parity(v3_days, v2_days)

    assert failures == []
    assert any("0 day(s) missing, 0 exempted" in line for line in report_lines)
