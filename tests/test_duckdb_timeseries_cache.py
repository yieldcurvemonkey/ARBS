"""Tests for DuckDBTimeseriesCache — local persistent timeseries store."""

import datetime
import tempfile
from pathlib import Path

import pytest

from Caching.duckdb_timeseries_cache import DuckDBTimeseriesCache


@pytest.fixture
def cache(tmp_path):
    db_path = tmp_path / "test_ts.duckdb"
    c = DuckDBTimeseriesCache(db_path=str(db_path))
    yield c
    c.close()


class TestDuckDBTimeseriesCache:
    def test_upsert_and_read_single_row(self, cache):
        cache.upsert_rows(
            "IRS::TEST::5Y",
            [
                (datetime.date(2026, 1, 6), "USD-SOFR-1D 5Y RATE", 4.25),
            ],
        )
        rows = cache.read_rows(
            "IRS::TEST::5Y",
            start=datetime.date(2026, 1, 6),
            end=datetime.date(2026, 1, 6),
        )
        assert len(rows) == 1
        assert rows[0] == (datetime.date(2026, 1, 6), "USD-SOFR-1D 5Y RATE", 4.25)

    def test_read_cross_date_panel(self, cache):
        dates = [datetime.date(2026, 1, d) for d in range(6, 11)]
        cache.upsert_rows(
            "IRS::TEST::5Y",
            [(d, "5Y RATE", 4.0 + i * 0.01) for i, d in enumerate(dates)],
        )
        rows = cache.read_rows(
            "IRS::TEST::5Y",
            start=datetime.date(2026, 1, 6),
            end=datetime.date(2026, 1, 10),
        )
        assert len(rows) == 5
        assert rows[0][0] == datetime.date(2026, 1, 6)
        assert rows[-1][0] == datetime.date(2026, 1, 10)

    def test_upsert_overwrites_existing(self, cache):
        d = datetime.date(2026, 1, 6)
        cache.upsert_rows("SYM", [(d, "col", 1.0)])
        cache.upsert_rows("SYM", [(d, "col", 2.0)])
        rows = cache.read_rows("SYM", start=d, end=d)
        assert len(rows) == 1
        assert rows[0][2] == 2.0

    def test_read_empty_returns_empty(self, cache):
        rows = cache.read_rows(
            "NONEXISTENT",
            start=datetime.date(2026, 1, 1),
            end=datetime.date(2026, 12, 31),
        )
        assert rows == []

    def test_symbols_with_special_chars(self, cache):
        sym = "IRS::BARCHART_STIRF-RL::USD-SOFR-1D::a1b2c3"
        d = datetime.date(2026, 3, 10)
        cache.upsert_rows(sym, [(d, "rate", 3.5)])
        rows = cache.read_rows(sym, start=d, end=d)
        assert len(rows) == 1
        assert rows[0][2] == 3.5

    def test_watermark_tracking(self, cache):
        sym = "IRS::TEST::5Y"
        assert cache.get_watermark(sym) is None
        cache.set_watermark(sym, datetime.datetime(2026, 3, 19, 12, 0, 0))
        wm = cache.get_watermark(sym)
        assert wm == datetime.datetime(2026, 3, 19, 12, 0, 0)

    def test_has_symbol(self, cache):
        assert not cache.has_symbol("IRS::TEST::5Y")
        cache.upsert_rows("IRS::TEST::5Y", [(datetime.date(2026, 1, 6), "c", 1.0)])
        assert cache.has_symbol("IRS::TEST::5Y")

    def test_bulk_upsert_many_rows(self, cache):
        """Performance-relevant: 500 rows should complete quickly."""
        import time

        sym = "IRS::BULK"
        base = datetime.date(2024, 1, 1)
        rows = [
            (base + datetime.timedelta(days=i), "rate", float(i))
            for i in range(500)
        ]
        t0 = time.perf_counter()
        cache.upsert_rows(sym, rows)
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"Bulk upsert took {elapsed:.2f}s, expected <2s"

        result = cache.read_rows(sym, start=base, end=base + datetime.timedelta(days=499))
        assert len(result) == 500

    def test_upsert_many_rows_supports_multiple_symbols(self, cache):
        d1 = datetime.date(2026, 1, 6)
        d2 = datetime.date(2026, 1, 7)

        count = cache.upsert_many_rows(
            {
                "IRS::SYM1": [(d1, "rate", 4.25)],
                "IRS::SYM2": [(d2, "rate", 4.30)],
            }
        )

        assert count == 2
        assert cache.read_rows("IRS::SYM1", start=d1, end=d1) == [(d1, "rate", 4.25)]
        assert cache.read_rows("IRS::SYM2", start=d2, end=d2) == [(d2, "rate", 4.30)]

    def test_available_dates_returns_dates_with_data(self, cache):
        dates = [datetime.date(2026, 1, d) for d in (6, 7, 8, 9, 10)]
        cache.upsert_rows(
            "IRS::TEST::1M",
            [(d, "1M RATE", 4.0 + i * 0.01) for i, d in enumerate(dates)],
        )
        result = cache.available_dates(
            "IRS::TEST::1M",
            start=datetime.date(2026, 1, 1),
            end=datetime.date(2026, 1, 31),
        )
        assert result == set(dates)

    def test_available_dates_empty_when_no_data(self, cache):
        result = cache.available_dates(
            "IRS::TEST::MISSING",
            start=datetime.date(2026, 1, 1),
            end=datetime.date(2026, 1, 31),
        )
        assert result == set()

    def test_available_dates_filters_by_range(self, cache):
        all_dates = [datetime.date(2026, 1, d) for d in (6, 7, 8, 9, 10)]
        cache.upsert_rows(
            "IRS::TEST::1M",
            [(d, "1M RATE", 4.0) for d in all_dates],
        )
        result = cache.available_dates(
            "IRS::TEST::1M",
            start=datetime.date(2026, 1, 8),
            end=datetime.date(2026, 1, 9),
        )
        assert result == {datetime.date(2026, 1, 8), datetime.date(2026, 1, 9)}

    def test_persistence_across_reopen(self, tmp_path):
        db_path = str(tmp_path / "persist.duckdb")
        c1 = DuckDBTimeseriesCache(db_path=db_path)
        c1.upsert_rows("SYM", [(datetime.date(2026, 1, 6), "col", 42.0)])
        c1.close()

        c2 = DuckDBTimeseriesCache(db_path=db_path)
        rows = c2.read_rows("SYM", start=datetime.date(2026, 1, 6), end=datetime.date(2026, 1, 6))
        c2.close()
        assert len(rows) == 1
        assert rows[0][2] == 42.0
