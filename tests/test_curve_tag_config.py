"""Tests for Caching.curve_tag_config — priority snapshot tagging."""

import datetime

import pytest


class TestGetTags:
    """get_tags() returns appropriate tags for a snapshot."""

    def test_open_tag_at_session_minute_zero(self):
        from Caching.curve_tag_config import get_tags

        tags = get_tags(
            session_minute=0,
            trading_date=datetime.date(2025, 3, 10),
            is_last_of_day=False,
            event_calendar={},
        )
        assert "OPEN" in tags

    def test_eod_tag_when_last_of_day(self):
        from Caching.curve_tag_config import get_tags

        tags = get_tags(
            session_minute=540,
            trading_date=datetime.date(2025, 3, 10),
            is_last_of_day=True,
            event_calendar={},
        )
        assert "EOD" in tags

    def test_fomc_tag_from_event_calendar(self):
        from Caching.curve_tag_config import get_tags

        cal = {
            datetime.date(2025, 3, 19): {
                "tag": "FOMC_RATE_DECISION",
                "session_minute": 480,
            },
        }
        tags = get_tags(
            session_minute=480,
            trading_date=datetime.date(2025, 3, 19),
            is_last_of_day=False,
            event_calendar=cal,
        )
        assert "FOMC_RATE_DECISION" in tags

    def test_no_event_tag_when_wrong_minute(self):
        from Caching.curve_tag_config import get_tags

        cal = {
            datetime.date(2025, 3, 19): {
                "tag": "FOMC_RATE_DECISION",
                "session_minute": 480,
            },
        }
        tags = get_tags(
            session_minute=100,
            trading_date=datetime.date(2025, 3, 19),
            is_last_of_day=False,
            event_calendar=cal,
        )
        assert "FOMC_RATE_DECISION" not in tags

    def test_no_tags_for_regular_minute(self):
        from Caching.curve_tag_config import get_tags

        tags = get_tags(
            session_minute=300,
            trading_date=datetime.date(2025, 3, 10),
            is_last_of_day=False,
            event_calendar={},
        )
        assert tags == []


class TestLoadEventCalendar:
    """load_event_calendar() reads YAML and returns date->event dict."""

    def test_loads_yaml(self, tmp_path):
        from Caching.curve_tag_config import load_event_calendar

        yaml_content = """
2025-03-19:
  tag: FOMC_RATE_DECISION
  session_minute: 480
2025-04-10:
  tag: CPI_PRINT
  session_minute: 90
"""
        cal_file = tmp_path / "events.yaml"
        cal_file.write_text(yaml_content)
        cal = load_event_calendar(cal_file)
        assert datetime.date(2025, 3, 19) in cal
        assert cal[datetime.date(2025, 3, 19)]["tag"] == "FOMC_RATE_DECISION"

    def test_returns_empty_for_missing_file(self, tmp_path):
        from Caching.curve_tag_config import load_event_calendar

        cal = load_event_calendar(tmp_path / "nonexistent.yaml")
        assert cal == {}
