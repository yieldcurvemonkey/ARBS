"""Tests for lifecycle_v2 integration with existing lifecycle pipeline."""

import pandas as pd
import pytest
from datetime import date

from SDRUtils.core.lifecycle import (
    replay_lifecycle_full,
    build_lifecycle_summary_from_resolved,
)


def _make_messages(rows):
    return pd.DataFrame(rows)


class TestBuildLifecycleSummaryFromResolved:
    def test_newt_only_produces_summary(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-001")
        summary = build_lifecycle_summary_from_resolved(resolved)
        assert not summary.was_corrected
        assert not summary.arrived_in_later_file
        assert not summary.is_terminated

    def test_cross_day_corr_detected(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
            {
                "Dissemination Identifier": "200",
                "Original Dissemination Identifier": "100",
                "Action type": "CORR",
                "Event type": None,
                "Amendment indicator": None,
                "Event timestamp": "2026-03-10 04:00:55",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.0455",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-002")

        # With file_dates showing cross-day arrival
        file_dates = {
            "100": date(2026, 3, 9),
            "200": date(2026, 3, 10),
        }
        summary = build_lifecycle_summary_from_resolved(resolved, file_dates=file_dates)
        assert summary.was_corrected
        assert summary.arrived_in_later_file
        assert summary.economics_changed
        assert "Fixed rate-Leg 1" in summary.fields_changed

    def test_amendment_modi_detected(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 20:13:27",
                "Execution Timestamp": "2026-03-09 20:13:23",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
            {
                "Dissemination Identifier": "201",
                "Original Dissemination Identifier": "100",
                "Action type": "MODI",
                "Event type": "TRAD",
                "Amendment indicator": True,
                "Event timestamp": "2026-03-10 11:36:35",
                "Execution Timestamp": "2026-03-09 20:13:23",
                "Notional amount-Leg 1": "12,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-003")
        file_dates = {
            "100": date(2026, 3, 9),
            "201": date(2026, 3, 10),
        }
        summary = build_lifecycle_summary_from_resolved(resolved, file_dates=file_dates)
        assert summary.was_economically_modified
        assert summary.arrived_in_later_file
        assert "Notional amount-Leg 1" in summary.fields_changed

    def test_term_detected(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
            {
                "Dissemination Identifier": "300",
                "Original Dissemination Identifier": "100",
                "Action type": "TERM",
                "Event type": "ETRM",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 15:15:56",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-004")
        summary = build_lifecycle_summary_from_resolved(resolved)
        assert summary.is_terminated

    def test_no_file_dates_defaults_to_event_date(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-005")
        # Should not crash when no file_dates provided
        summary = build_lifecycle_summary_from_resolved(resolved)
        assert summary.original_execution_timestamp is not None
