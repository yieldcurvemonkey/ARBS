"""Integration test: full CORE cycle with DuckDB fast path.

Tests the complete flow: write -> push to L2 rows -> sync to DuckDB -> fast read.
Uses mocked Postgres to avoid needing a real database.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from Caching.computed_timeseries_store import ComputedTimeseriesStore


@pytest.fixture
def store_pair(tmp_path):
    """Simulate producer and consumer on different machines."""
    producer = ComputedTimeseriesStore(
        base_dir=str(tmp_path / "producer_ts"),
        use_duckdb=True,
        duckdb_path=str(tmp_path / "producer.duckdb"),
    )
    consumer = ComputedTimeseriesStore(
        base_dir=str(tmp_path / "consumer_ts"),
        use_duckdb=True,
        duckdb_path=str(tmp_path / "consumer.duckdb"),
    )
    return producer, consumer


class TestCORECycleWithDuckDB:
    @patch("Caching.computed_timeseries_store._get_computed_ts_sync", return_value=None)
    def test_write_then_read_same_machine(self, mock_sync, tmp_path):
        """DuckDB fast path: write and read on same machine."""
        store = ComputedTimeseriesStore(
            base_dir=str(tmp_path / "ts"),
            use_duckdb=True,
            duckdb_path=str(tmp_path / "local.duckdb"),
        )
        dates = [datetime.date(2026, 1, d) for d in range(6, 13)]
        rows = [(d, "5Y RATE", 4.0 + i * 0.01) for i, d in enumerate(dates)]
        store.append_rows(symbol="IRS::SOFR::5Y", rows=rows)

        result = store.read_rows(
            symbol="IRS::SOFR::5Y",
            reference_points=dates,
            intraday=False,
        )
        assert len(result) == 7
        assert all(r[1] == "5Y RATE" for r in result)

    def test_sync_from_postgres_to_consumer_duckdb(self, store_pair, tmp_path):
        """Simulate CORE: producer writes, consumer syncs via mocked Postgres."""
        producer, consumer = store_pair

        # Producer writes data (mock sync to avoid background thread issues)
        dates = [datetime.date(2026, 1, d) for d in range(6, 11)]
        rows = [(d, "5Y RATE", 4.0 + i * 0.01) for i, d in enumerate(dates)]
        with patch("Caching.computed_timeseries_store._get_computed_ts_sync", return_value=None):
            producer.append_rows(symbol="IRS::SOFR::5Y", rows=rows)

        # Simulate what Postgres would return
        postgres_rows = [
            (d, "5Y RATE", 4.0 + i * 0.01, datetime.datetime(2026, 1, d.day, 12, 0, 0))
            for i, d in enumerate(dates)
        ]

        mock_sync = MagicMock()
        mock_sync.pull_rows = MagicMock(return_value=postgres_rows)
        mock_sync.push_rows = MagicMock(return_value=True)
        mock_sync.push_day = MagicMock(return_value=True)
        mock_sync.prefetch_range = MagicMock(return_value=[])

        with patch("Caching.computed_timeseries_store._get_computed_ts_sync", return_value=mock_sync):
            # Consumer reads — should trigger sync from Postgres to local DuckDB
            result = consumer.read_rows(
                symbol="IRS::SOFR::5Y",
                reference_points=dates,
                intraday=False,
            )

        assert len(result) == 5

    @patch("Caching.computed_timeseries_store._get_computed_ts_sync", return_value=None)
    def test_read_performance_from_duckdb(self, mock_sync, tmp_path):
        """Verify fast reads from local DuckDB."""
        import time

        store = ComputedTimeseriesStore(
            base_dir=str(tmp_path / "ts"),
            use_duckdb=True,
            duckdb_path=str(tmp_path / "perf.duckdb"),
        )

        # Write 250 days of data
        base_date = datetime.date(2025, 1, 1)
        dates = [base_date + datetime.timedelta(days=i) for i in range(250)]
        rows = [(d, "5Y RATE", 4.0 + i * 0.001) for i, d in enumerate(dates)]
        store.append_rows(symbol="IRS::PERF", rows=rows)

        # Time a 60-day panel read
        read_dates = dates[100:160]
        t0 = time.perf_counter()
        for _ in range(10):
            result = store.read_rows(
                symbol="IRS::PERF",
                reference_points=read_dates,
                intraday=False,
            )
        elapsed = (time.perf_counter() - t0) / 10

        assert len(result) == 60
        assert elapsed < 0.05, f"DuckDB read took {elapsed*1000:.1f}ms, expected <50ms"
