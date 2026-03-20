"""Tests for ComputedTimeseriesStore with DuckDB fast path."""

import datetime
import time
from unittest.mock import MagicMock, patch

import pytest

from Caching.computed_timeseries_store import ComputedTimeseriesStore


@pytest.fixture
def store(tmp_path):
    return ComputedTimeseriesStore(
        base_dir=str(tmp_path / "ts"),
        use_duckdb=True,
        duckdb_path=str(tmp_path / "test.duckdb"),
    )


@pytest.fixture
def store_no_duckdb(tmp_path):
    return ComputedTimeseriesStore(
        base_dir=str(tmp_path / "ts"),
        use_duckdb=False,
    )


class TestDuckDBFastPath:
    def test_append_and_read_via_duckdb(self, store):
        dates = [datetime.date(2026, 1, d) for d in range(6, 11)]
        rows = [(d, "5Y RATE", 4.0 + i * 0.01) for i, d in enumerate(dates)]
        store.append_rows(symbol="IRS::TEST::5Y", rows=rows)

        result = store.read_rows(
            symbol="IRS::TEST::5Y",
            reference_points=dates,
            intraday=False,
        )
        assert len(result) == 5
        # Verify values round-trip correctly
        assert result[0][2] == 4.0
        assert result[4][2] == 4.04

    def test_read_returns_empty_for_unknown_symbol(self, store):
        result = store.read_rows(
            symbol="UNKNOWN",
            reference_points=[datetime.date(2026, 1, 6)],
            intraday=False,
        )
        assert result == []

    def test_duckdb_disabled_falls_back_to_parquet(self, store_no_duckdb):
        """When use_duckdb=False, should use existing Parquet path."""
        assert not hasattr(store_no_duckdb, "_duckdb_cache") or store_no_duckdb._duckdb_cache is None

    @patch("Caching.computed_timeseries_store._get_computed_ts_sync", return_value=None)
    def test_append_writes_to_both_parquet_and_duckdb(self, mock_sync, store, tmp_path):
        d = datetime.date(2026, 3, 10)
        store.append_rows(symbol="IRS::TEST", rows=[(d, "rate", 4.5)])

        # Verify DuckDB has the data
        duckdb_rows = store._duckdb_cache.read_rows("IRS::TEST", start=d, end=d)
        assert len(duckdb_rows) == 1

        # Verify Parquet path also has the data (existing behavior)
        from Caching.timeseries_cache import read_timeseries
        df = read_timeseries(None, "IRS::TEST", start=d, end=d, base_dir=str(tmp_path / "ts"))
        assert not df.empty

    def test_skip_current_eod(self, store):
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        store.append_rows(
            symbol="SYM",
            rows=[
                (yesterday, "col", 1.0),
                (today, "col", 2.0),
            ],
        )
        result = store.read_rows(
            symbol="SYM",
            reference_points=[yesterday, today],
            intraday=False,
            skip_current_eod=True,
        )
        # Should skip today
        assert len(result) == 1
        assert result[0][0] == yesterday

    def test_append_many_rows_writes_multiple_symbols(self, store, tmp_path):
        d1 = datetime.date(2026, 3, 10)
        d2 = datetime.date(2026, 3, 11)

        store.append_many_rows(
            rows_by_symbol={
                "IRS::TEST1": [(d1, "rate", 4.5)],
                "IRS::TEST2": [(d2, "rate", 4.6)],
            }
        )

        assert store._duckdb_cache.read_rows("IRS::TEST1", start=d1, end=d1) == [(d1, "rate", 4.5)]
        assert store._duckdb_cache.read_rows("IRS::TEST2", start=d2, end=d2) == [(d2, "rate", 4.6)]

        from Caching.timeseries_cache import read_timeseries

        df1 = read_timeseries(None, "IRS::TEST1", start=d1, end=d1, base_dir=str(tmp_path / "ts"))
        df2 = read_timeseries(None, "IRS::TEST2", start=d2, end=d2, base_dir=str(tmp_path / "ts"))
        assert not df1.empty
        assert not df2.empty


class TestRowLevelL2Push:
    @patch("Caching.computed_timeseries_store._get_computed_ts_sync")
    def test_append_rows_pushes_to_row_table(self, mock_get_sync, store):
        mock_sync = MagicMock()
        mock_sync.push_rows = MagicMock(return_value=True)
        mock_sync.push_day = MagicMock(return_value=True)
        mock_get_sync.return_value = mock_sync

        d = datetime.date(2026, 3, 10)
        store.append_rows(symbol="IRS::TEST", rows=[(d, "rate", 4.5)])

        # Give the background thread time to execute
        time.sleep(0.5)

        # Verify push_rows was called
        mock_sync.push_rows.assert_called_once()
        call_args = mock_sync.push_rows.call_args
        assert call_args[0][0] == "IRS::TEST"  # symbol
        assert len(call_args[0][1]) == 1  # one row
