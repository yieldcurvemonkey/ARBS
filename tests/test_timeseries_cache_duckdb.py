"""
Tests for timeseries_cache.py — DuckDB-backed Hive-partitioned Parquet I/O.

Covers:
- append_timeseries: writing DataFrames to partitioned Parquet
- read_timeseries: reading back via DuckDB read_parquet with hive partitioning
- Date-range filtering (start/end pruning)
- Column projection
- Multi-day DataFrames partitioned by date
- Content-addressed (SHA256) deduplication
- Non-DatetimeIndex with as_of_date
- Empty / missing symbol handling
- Symbol sanitization
- Datetime precision trimming (start/end as datetime objects)
- WriteOptions configuration
- Round-trip data fidelity
"""

import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Caching.timeseries_cache import (
    WriteOptions,
    append_timeseries,
    append_timeseries_many,
    read_timeseries,
    _sanitize_symbol,
    _to_datestr,
    _df_to_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ts_dir(tmp_path):
    """Fresh temporary directory for timeseries Parquet storage."""
    return tmp_path / "ts_data"


@pytest.fixture
def opts(ts_dir):
    """Default WriteOptions pointing at the temp directory."""
    return WriteOptions(base_dir=str(ts_dir))


def _make_df(dates, columns=None, freq="h", periods_per_day=24):
    """Build a simple DatetimeIndex DataFrame spanning the given dates."""
    if columns is None:
        columns = {"bid": 100.0, "ask": 100.5, "mid": 100.25}
    frames = []
    for d in dates:
        idx = pd.date_range(
            start=datetime(d.year, d.month, d.day, 0, 0),
            periods=periods_per_day,
            freq=freq,
        )
        data = {col: val + np.random.randn(len(idx)) * 0.01 for col, val in columns.items()}
        frames.append(pd.DataFrame(data, index=idx))
    return pd.concat(frames)


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_sanitize_symbol_basic(self):
        assert _sanitize_symbol("AAPL") == "AAPL"
        assert _sanitize_symbol("USD/JPY") == "USD_JPY"
        assert _sanitize_symbol("T 2.5 05/15/2030") == "T_2.5_05_15_2030"

    def test_sanitize_symbol_special_chars(self):
        assert _sanitize_symbol("A&B@C#D") == "A_B_C_D"
        assert _sanitize_symbol("plain-text_ok.1") == "plain-text_ok.1"

    def test_to_datestr_date(self):
        assert _to_datestr(date(2025, 3, 15)) == "2025-03-15"

    def test_to_datestr_datetime(self):
        assert _to_datestr(datetime(2025, 3, 15, 10, 30)) == "2025-03-15"

    def test_df_to_table_adds_index_ts(self):
        idx = pd.date_range("2025-01-01", periods=3, freq="h")
        df = pd.DataFrame({"price": [1.0, 2.0, 3.0]}, index=idx)
        table = _df_to_table(df)
        assert "_index_ts" in table.column_names
        assert "price" in table.column_names


# ---------------------------------------------------------------------------
# append_timeseries
# ---------------------------------------------------------------------------

class TestAppendTimeseries:
    def test_basic_write(self, opts):
        df = _make_df([date(2025, 1, 6)], periods_per_day=5)
        metas = append_timeseries(None, "TEST_SYM", df, opts=opts)
        assert len(metas) == 1
        meta = metas[0]
        assert meta["rows"] == 5
        assert meta["sha256"]
        assert Path(meta["path"]).exists()

    def test_multi_day_partitioning(self, opts):
        dates = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)]
        df = _make_df(dates, periods_per_day=4)
        metas = append_timeseries(None, "MULTI", df, opts=opts)
        assert len(metas) == 3
        for m in metas:
            assert m["rows"] == 4

    def test_content_dedup(self, opts):
        df = pd.DataFrame(
            {"val": [1.0, 2.0, 3.0]},
            index=pd.date_range("2025-01-06", periods=3, freq="h"),
        )
        m1 = append_timeseries(None, "DEDUP", df, opts=opts)
        m2 = append_timeseries(None, "DEDUP", df, opts=opts)
        assert m1[0]["sha256"] == m2[0]["sha256"]
        # Same file, no duplicate
        assert m1[0]["path"] == m2[0]["path"]

    def test_empty_df_returns_empty(self, opts):
        assert append_timeseries(None, "EMPTY", pd.DataFrame(), opts=opts) == []

    def test_none_df_returns_empty(self, opts):
        assert append_timeseries(None, "NONE", None, opts=opts) == []

    def test_non_datetime_index_requires_as_of_date(self, opts):
        df = pd.DataFrame({"val": [1, 2, 3]}, index=[0, 1, 2])
        with pytest.raises(ValueError, match="as_of_date"):
            append_timeseries(None, "NODT", df, opts=opts)

    def test_non_datetime_index_with_as_of_date(self, opts):
        df = pd.DataFrame({"val": [10, 20]}, index=[0, 1])
        metas = append_timeseries(None, "NODT", df, as_of_date=date(2025, 2, 1), opts=opts)
        assert len(metas) == 1
        assert metas[0]["rows"] == 2

    def test_root_param_ignored(self, opts):
        df = _make_df([date(2025, 1, 6)], periods_per_day=2)
        # Pass arbitrary root; should be silently ignored
        metas = append_timeseries("not_a_real_root", "IGN", df, opts=opts)
        assert len(metas) == 1

    def test_hive_directory_structure(self, opts, ts_dir):
        df = _make_df([date(2025, 3, 10)], periods_per_day=2)
        append_timeseries(None, "HIVE_SYM", df, opts=opts)
        expected_dir = ts_dir / "asset=HIVE_SYM" / "date=2025-03-10"
        assert expected_dir.exists()
        parquet_files = list(expected_dir.glob("*.parquet"))
        assert len(parquet_files) == 1

    def test_symbol_sanitized_in_path(self, opts, ts_dir):
        df = _make_df([date(2025, 1, 6)], periods_per_day=2)
        append_timeseries(None, "US/T 2.5%", df, opts=opts)
        dirs = list(ts_dir.glob("asset=*"))
        assert len(dirs) == 1
        assert "US_T_2.5_" in dirs[0].name

    def test_bulk_multi_symbol_write(self, opts, ts_dir):
        df1 = _make_df([date(2025, 1, 6)], columns={"v": 1.0}, periods_per_day=2)
        df2 = _make_df([date(2025, 1, 7)], columns={"v": 2.0}, periods_per_day=2)

        metas = append_timeseries_many(
            None,
            [
                ("SYM1", df1, None),
                ("SYM2", df2, None),
            ],
            opts=opts,
        )

        assert set(metas.keys()) == {"SYM1", "SYM2"}
        assert len(metas["SYM1"]) == 1
        assert len(metas["SYM2"]) == 1
        assert read_timeseries(None, "SYM1", base_dir=str(ts_dir)).shape[0] == 2
        assert read_timeseries(None, "SYM2", base_dir=str(ts_dir)).shape[0] == 2


# ---------------------------------------------------------------------------
# read_timeseries
# ---------------------------------------------------------------------------

class TestReadTimeseries:
    def test_roundtrip(self, opts, ts_dir):
        df = _make_df([date(2025, 1, 6)], columns={"price": 100.0}, periods_per_day=5)
        append_timeseries(None, "RT", df, opts=opts)
        result = read_timeseries(None, "RT", base_dir=str(ts_dir))
        assert len(result) == 5
        assert "price" in result.columns
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_values_preserved(self, opts, ts_dir):
        idx = pd.date_range("2025-01-06", periods=3, freq="h")
        df = pd.DataFrame({"exact": [1.5, 2.5, 3.5]}, index=idx)
        append_timeseries(None, "VALS", df, opts=opts)
        result = read_timeseries(None, "VALS", base_dir=str(ts_dir))
        np.testing.assert_array_almost_equal(result["exact"].values, [1.5, 2.5, 3.5])

    def test_multi_day_read(self, opts, ts_dir):
        dates = [date(2025, 1, 6), date(2025, 1, 7)]
        df = _make_df(dates, columns={"v": 1.0}, periods_per_day=3)
        append_timeseries(None, "MD", df, opts=opts)
        result = read_timeseries(None, "MD", base_dir=str(ts_dir))
        assert len(result) == 6

    def test_date_range_start_filter(self, opts, ts_dir):
        dates = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)]
        df = _make_df(dates, columns={"v": 1.0}, periods_per_day=2)
        append_timeseries(None, "SF", df, opts=opts)
        result = read_timeseries(None, "SF", start=date(2025, 1, 7), base_dir=str(ts_dir))
        # Only Jan 7 and Jan 8
        assert all(d.date() >= date(2025, 1, 7) for d in result.index)

    def test_date_range_end_filter(self, opts, ts_dir):
        dates = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)]
        df = _make_df(dates, columns={"v": 1.0}, periods_per_day=2)
        append_timeseries(None, "EF", df, opts=opts)
        result = read_timeseries(None, "EF", end=date(2025, 1, 7), base_dir=str(ts_dir))
        assert all(d.date() <= date(2025, 1, 7) for d in result.index)

    def test_date_range_both(self, opts, ts_dir):
        dates = [date(2025, 1, d) for d in range(6, 11)]
        df = _make_df(dates, columns={"v": 1.0}, periods_per_day=2)
        append_timeseries(None, "BF", df, opts=opts)
        result = read_timeseries(
            None, "BF",
            start=date(2025, 1, 7),
            end=date(2025, 1, 9),
            base_dir=str(ts_dir),
        )
        result_dates = set(d.date() for d in result.index)
        assert result_dates <= {date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9)}

    def test_column_projection(self, opts, ts_dir):
        df = _make_df([date(2025, 1, 6)], columns={"bid": 99.0, "ask": 101.0, "mid": 100.0}, periods_per_day=3)
        append_timeseries(None, "PROJ", df, opts=opts)
        result = read_timeseries(None, "PROJ", columns=["bid", "ask"], base_dir=str(ts_dir))
        assert "bid" in result.columns
        assert "ask" in result.columns
        assert "mid" not in result.columns

    def test_missing_symbol_returns_empty(self, ts_dir):
        result = read_timeseries(None, "DOESNOTEXIST", base_dir=str(ts_dir))
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_datetime_start_precision(self, opts, ts_dir):
        idx = pd.date_range("2025-01-06 08:00", periods=6, freq="h")
        df = pd.DataFrame({"v": range(6)}, index=idx)
        append_timeseries(None, "DTP", df, opts=opts)
        result = read_timeseries(
            None, "DTP",
            start=datetime(2025, 1, 6, 10, 0),
            base_dir=str(ts_dir),
        )
        assert all(d >= pd.Timestamp("2025-01-06 10:00") for d in result.index)

    def test_datetime_end_precision(self, opts, ts_dir):
        idx = pd.date_range("2025-01-06 08:00", periods=6, freq="h")
        df = pd.DataFrame({"v": range(6)}, index=idx)
        append_timeseries(None, "DTE", df, opts=opts)
        result = read_timeseries(
            None, "DTE",
            end=datetime(2025, 1, 6, 10, 0),
            base_dir=str(ts_dir),
        )
        assert all(d <= pd.Timestamp("2025-01-06 10:00") for d in result.index)

    def test_sorted_output(self, opts, ts_dir):
        idx = pd.date_range("2025-01-06", periods=10, freq="h")
        df = pd.DataFrame({"v": range(10)}, index=idx)
        # Shuffle input
        df = df.sample(frac=1)
        append_timeseries(None, "SORT", df, opts=opts)
        result = read_timeseries(None, "SORT", base_dir=str(ts_dir))
        assert result.index.is_monotonic_increasing

    def test_no_date_column_in_output(self, opts, ts_dir):
        df = _make_df([date(2025, 1, 6)], columns={"price": 50.0}, periods_per_day=3)
        append_timeseries(None, "NOCOL", df, opts=opts)
        result = read_timeseries(None, "NOCOL", base_dir=str(ts_dir))
        assert "date" not in result.columns
        assert "_index_ts" not in result.columns

    def test_root_param_ignored_on_read(self, opts, ts_dir):
        df = _make_df([date(2025, 1, 6)], columns={"v": 1.0}, periods_per_day=2)
        append_timeseries(None, "RPI", df, opts=opts)
        result = read_timeseries("ignored_root", "RPI", base_dir=str(ts_dir))
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Multiple appends (append semantics)
# ---------------------------------------------------------------------------

class TestAppendSemantics:
    def test_append_new_data_to_same_symbol(self, opts, ts_dir):
        df1 = _make_df([date(2025, 1, 6)], columns={"v": 1.0}, periods_per_day=3)
        df2 = _make_df([date(2025, 1, 7)], columns={"v": 2.0}, periods_per_day=3)
        append_timeseries(None, "APP", df1, opts=opts)
        append_timeseries(None, "APP", df2, opts=opts)
        result = read_timeseries(None, "APP", base_dir=str(ts_dir))
        assert len(result) == 6
        result_dates = set(d.date() for d in result.index)
        assert date(2025, 1, 6) in result_dates
        assert date(2025, 1, 7) in result_dates

    def test_append_same_day_compacts_to_latest_single_file(self, opts, ts_dir):
        idx = pd.date_range("2025-01-06", periods=3, freq="h")
        df1 = pd.DataFrame({"v": [1.0, 2.0, 3.0]}, index=idx)
        df2 = pd.DataFrame({"v": [4.0, 5.0, 6.0]}, index=idx)
        append_timeseries(None, "SAMEDAY", df1, opts=opts)
        append_timeseries(None, "SAMEDAY", df2, opts=opts)
        part_dir = ts_dir / "asset=SAMEDAY" / "date=2025-01-06"
        parquet_files = list(part_dir.glob("*.parquet"))
        assert len(parquet_files) == 1
        result = read_timeseries(None, "SAMEDAY", base_dir=str(ts_dir))
        assert list(result["v"]) == [4.0, 5.0, 6.0]

    def test_append_same_day_partial_overlap_prefers_latest_values(self, opts, ts_dir):
        idx = pd.date_range("2025-01-06 00:00", periods=20, freq="min")
        df1 = pd.DataFrame({"v": [1.0] * len(idx)}, index=idx)
        df2 = pd.DataFrame({"v": [2.0] * len(idx[::2])}, index=idx[::2])
        append_timeseries(None, "PARTIAL", df1, opts=opts)
        append_timeseries(None, "PARTIAL", df2, opts=opts)

        result = read_timeseries(None, "PARTIAL", base_dir=str(ts_dir))
        assert (result.loc[idx[::2], "v"] == 2.0).all()
        assert (result.loc[idx[1::2], "v"] == 1.0).all()


# ---------------------------------------------------------------------------
# WriteOptions
# ---------------------------------------------------------------------------

class TestWriteOptions:
    def test_custom_base_dir(self, tmp_path):
        custom_dir = tmp_path / "custom"
        wopts = WriteOptions(base_dir=str(custom_dir))
        df = _make_df([date(2025, 1, 6)], periods_per_day=2)
        append_timeseries(None, "CUSTOM", df, opts=wopts)
        assert (custom_dir / "asset=CUSTOM").exists()

    def test_default_opts_used(self, tmp_path):
        # When opts is None, default base_dir is ./data/ts
        df = _make_df([date(2025, 1, 6)], periods_per_day=2)
        metas = append_timeseries(None, "DEFAULT", df)
        # Cleanup: remove the default directory
        for m in metas:
            try:
                os.remove(m["path"])
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Large-ish data round-trip
# ---------------------------------------------------------------------------

class TestLargeDataRoundtrip:
    def test_1000_rows_fidelity(self, opts, ts_dir):
        idx = pd.date_range("2025-01-06", periods=1000, freq="min")
        np.random.seed(42)
        df = pd.DataFrame({
            "price": np.random.randn(1000) * 10 + 100,
            "volume": np.random.randint(0, 10000, 1000),
        }, index=idx)
        append_timeseries(None, "BIG", df, opts=opts)
        result = read_timeseries(None, "BIG", base_dir=str(ts_dir))
        assert len(result) == 1000
        np.testing.assert_array_almost_equal(
            result["price"].values, df.sort_index()["price"].values, decimal=5
        )
