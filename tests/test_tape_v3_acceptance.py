"""Tests for scripts/tape_v3_acceptance.py criteria 1 and 2b.

No database connection is ever made: `evaluate_day_parity` and
`evaluate_marker_thresholds` are pure functions over plain Python data,
extracted specifically so these criteria are testable without mocking
SQLAlchemy/psycopg2.
"""
from __future__ import annotations

from datetime import date

from scripts.tape_v3_acceptance import (
    EXEMPT_MISSING_DAYS,
    THIN_DAY_LEG_THRESHOLD,
    evaluate_day_parity,
    evaluate_marker_thresholds,
)


def test_exempt_missing_days_is_exactly_the_one_documented_date():
    """Guards against silent generalisation: if a future edit widens this
    to a computed rule (e.g. "any holiday" or "any day with a low v2
    count"), this test breaks and forces the author to look at it.

    Also guards against silently re-adding 2024-10-14: its exemption was
    removed because the backfill ties it out 3-for-3 against v2, and the
    `start=D end=D` probe that originally justified it does not reproduce
    production's D+1-forward fetch window (see the comment above
    EXEMPT_MISSING_DAYS)."""
    assert EXEMPT_MISSING_DAYS == frozenset({
        date(2026, 7, 3),
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


def test_multiple_exempted_days_missing_together_reports_both_and_passes():
    """Exercises the plural-reporting branch with a synthetic exempt set
    (via the `exempt` parameter) rather than production dates, so this
    stays valid regardless of how many dates EXEMPT_MISSING_DAYS holds."""
    synthetic_exempt = frozenset({date(2026, 7, 3), date(2024, 10, 14)})
    v2_days = {date(2026, 8, 5), date(2026, 7, 3), date(2024, 10, 14)}
    v3_days = {date(2026, 8, 5)}

    report_lines, failures = evaluate_day_parity(v3_days, v2_days, exempt=synthetic_exempt)

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


# --- Criterion 2b: enrichment-marker thresholds, thin-day exemption -----
#
# 2024-10-14 has 3 legs, all standalone outrights (package_id
# 'OUTRIGHT-<trade_id>', ptp_group_id and package_transaction_price both
# NULL) -- PTP grouping requires a package transaction price, so 0% ptp
# fill is the correct answer, not a defect. It is the only day of 611
# with fewer than 50 legs; every day with >=50 legs has nonzero ptp fill.
# These tests call `evaluate_marker_thresholds` WITHOUT an explicit
# `thin_threshold` so they exercise the real default
# (`THIN_DAY_LEG_THRESHOLD`), not a value pinned in the test -- a
# regression that widens or narrows the constant must show up here.

def test_thin_day_leg_threshold_is_fifty():
    """Guards the specific value, mirroring the EXEMPT_MISSING_DAYS guard
    above: matches `_RISK_GUARD_MIN_LEGS` in ingest_usdswaps_tape.py, the
    codebase's existing "too thin to assert on" threshold."""
    assert THIN_DAY_LEG_THRESHOLD == 50


def test_thin_day_with_zero_ptp_passes_and_is_reported():
    """The motivating case: 2024-10-14, 3 legs, 0% ptp, 100% on the other
    three markers -- must NOT fail, but the exemption must be visible in
    the report, not silent."""
    rows = [
        {"as_of_date": "2024-10-14", "n": 3, "ptp": 0.0,
         "spec": 100.0, "evt": 100.0, "ust": 100.0},
    ]

    report_lines, failures = evaluate_marker_thresholds(rows)

    assert failures == []
    assert any(
        "1 thin day(s) (<50 legs) exempt" in line and "2024-10-14" in line
        for line in report_lines
    )
    assert any("0 day(s) below threshold" in line for line in report_lines)


def test_large_day_with_zero_ptp_still_fails():
    """A day at or above the thin-day threshold gets no exemption: zero
    ptp fill on a substantial day is still the real defect the rule
    exists to catch."""
    rows = [
        {"as_of_date": "2026-08-05", "n": 500, "ptp": 0.0,
         "spec": 100.0, "evt": 100.0, "ust": 100.0},
    ]

    report_lines, failures = evaluate_marker_thresholds(rows)

    assert any(
        "1 day(s) below marker thresholds" in f and "2026-08-05" in f
        for f in failures
    )
    assert any("0 thin day(s)" in line for line in report_lines)


def test_thin_day_still_fails_on_low_event_timestamp_fill():
    """The exemption is narrow: only the ptp clause is thinned. A thin
    day that also fails event_timestamp must still fail the criterion,
    not be swept up by the ptp exemption."""
    rows = [
        {"as_of_date": "2024-10-14", "n": 3, "ptp": 0.0,
         "spec": 100.0, "evt": 66.7, "ust": 100.0},
    ]

    report_lines, failures = evaluate_marker_thresholds(rows)

    assert any(
        "1 day(s) below marker thresholds" in f and "2024-10-14" in f
        for f in failures
    )
    assert any("0 thin day(s)" in line for line in report_lines)


def test_no_bad_days_reports_zero_and_zero():
    report_lines, failures = evaluate_marker_thresholds([])

    assert failures == []
    assert any(
        "0 day(s) below threshold, 0 thin day(s)" in line for line in report_lines
    )
