"""Tests for row-level push/pull in SupabaseComputedTimeseriesSync."""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from Caching.supabase_computed_timeseries_sync import SupabaseComputedTimeseriesSync


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    ctx = MagicMock()
    conn = MagicMock()
    engine.begin.return_value = ctx
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return engine, conn


@pytest.fixture
def sync(tmp_path, mock_engine):
    engine, _ = mock_engine
    return SupabaseComputedTimeseriesSync(base_dir=tmp_path, engine=engine)


class TestPushRows:
    @patch("Caching.supabase_schema.ensure_schema", return_value=True)
    def test_push_rows_executes_upsert(self, mock_schema, sync, mock_engine):
        _, conn = mock_engine
        rows = [
            (datetime.date(2026, 1, 6), "col1", 4.25),
            (datetime.date(2026, 1, 7), "col1", 4.30),
        ]
        result = sync.push_rows("IRS::TEST", rows)
        assert result is True
        assert conn.execute.call_count == 2  # one per row

    @patch("Caching.supabase_schema.ensure_schema", return_value=True)
    def test_push_rows_empty_returns_false(self, mock_schema, sync):
        assert sync.push_rows("IRS::TEST", []) is False

    def test_push_rows_no_engine_returns_false(self, tmp_path):
        sync = SupabaseComputedTimeseriesSync(base_dir=tmp_path, engine=None)
        assert sync.push_rows("IRS::TEST", [(datetime.date(2026, 1, 6), "c", 1.0)]) is False


class TestPullRows:
    @patch("Caching.supabase_schema.ensure_schema", return_value=True)
    def test_pull_rows_returns_fetched_data(self, mock_schema, sync, mock_engine):
        _, conn = mock_engine
        mock_row_1 = MagicMock()
        mock_row_1.trading_date = datetime.date(2026, 1, 6)
        mock_row_1.column_name = "rate"
        mock_row_1.value = 4.25
        mock_row_1.updated_at = datetime.datetime(2026, 1, 6, 12, 0, 0)
        mock_row_2 = MagicMock()
        mock_row_2.trading_date = datetime.date(2026, 1, 7)
        mock_row_2.column_name = "rate"
        mock_row_2.value = 4.30
        mock_row_2.updated_at = datetime.datetime(2026, 1, 7, 12, 0, 0)
        conn.execute.return_value.fetchall.return_value = [mock_row_1, mock_row_2]

        rows = sync.pull_rows(
            "IRS::TEST",
            start=datetime.date(2026, 1, 6),
            end=datetime.date(2026, 1, 7),
        )
        assert len(rows) == 2
        assert rows[0] == (datetime.date(2026, 1, 6), "rate", 4.25, datetime.datetime(2026, 1, 6, 12, 0, 0))
        assert rows[1] == (datetime.date(2026, 1, 7), "rate", 4.30, datetime.datetime(2026, 1, 7, 12, 0, 0))

    def test_pull_rows_no_engine_returns_empty(self, tmp_path):
        sync = SupabaseComputedTimeseriesSync(base_dir=tmp_path, engine=None)
        rows = sync.pull_rows("SYM", start=datetime.date(2026, 1, 1), end=datetime.date(2026, 12, 31))
        assert rows == []
