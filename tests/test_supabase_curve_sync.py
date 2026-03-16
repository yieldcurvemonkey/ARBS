"""Tests for Caching.supabase_curve_sync — push/pull CurveStore to Supabase."""

import datetime
import io
from unittest.mock import MagicMock, patch, call

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def _make_test_parquet_bytes() -> bytes:
    """Create minimal Parquet bytes matching CurveStore._RAW_SCHEMA."""
    table = pa.table(
        {
            "timestamp_utc": pa.array(
                [datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)],
                type=pa.timestamp("us", tz="UTC"),
            ),
            "timestamp_local": pa.array(
                [datetime.datetime(2025, 1, 15, 15, 0)],
                type=pa.timestamp("us"),
            ),
            "trading_date": pa.array([datetime.date(2025, 1, 15)], type=pa.date32()),
            "session_minute": pa.array([540], type=pa.int16()),
            "curve_name": pa.array(["USD-SOFR-1D"]).dictionary_encode(),
            "cfg_hash": pa.array(["abc123"]).dictionary_encode(),
            "reference_key": pa.array(["ref"]).dictionary_encode(),
            "interpolation": pa.array(["log_linear"]).dictionary_encode(),
            "source_variant": pa.array(["ERIS"]).dictionary_encode(),
            "node_dates": pa.array(
                [[datetime.date(2025, 1, 16), datetime.date(2025, 7, 15)]],
                type=pa.list_(pa.date32()),
            ),
            "discount_factors": pa.array(
                [[0.999, 0.985]], type=pa.list_(pa.float64())
            ),
        }
    )
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


class TestPushDay:
    """push_day() reads local Parquet and UPSERTs to curve_intraday_blocks."""

    def test_push_day_reads_file_and_upserts(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        # Write a test Parquet file to tmp_path
        parquet_bytes = _make_test_parquet_bytes()
        part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / "date=2025-01-15"
        part_dir.mkdir(parents=True)
        pq_file = part_dir / "abc123.parquet"
        pq_file.write_bytes(parquet_bytes)

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.push_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is True
        mock_conn.execute.assert_called()

    def test_push_day_returns_false_when_no_local_data(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        mock_engine = MagicMock()
        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.push_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is False

    def test_push_day_noop_when_no_engine(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=None)
        result = sync.push_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is False


class TestPullDay:
    """pull_day() fetches blob from Supabase and writes local Parquet."""

    def test_pull_day_writes_local_file(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        parquet_bytes = _make_test_parquet_bytes()

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        # Simulate a row returned from SELECT
        mock_row = MagicMock()
        mock_row.payload = parquet_bytes
        mock_row.sha256 = "fakehash"
        mock_row.data_format = "parquet_zstd"
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.pull_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is True
        # Verify local file was created
        part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / "date=2025-01-15"
        assert part_dir.exists()
        pq_files = list(part_dir.glob("*.parquet"))
        assert len(pq_files) == 1

    def test_pull_day_returns_false_when_not_in_supabase(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        result = sync.pull_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert result is False


class TestPrefetchRange:
    """prefetch_range() downloads only missing days."""

    def test_skips_already_cached_days(self, tmp_path):
        from Caching.supabase_curve_sync import SupabaseCurveSync

        # Create a local file for 2025-01-15
        part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / "date=2025-01-15"
        part_dir.mkdir(parents=True)
        (part_dir / "existing.parquet").write_bytes(_make_test_parquet_bytes())

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        # Return only 2025-01-16 from Supabase (15 is already local)
        mock_row = MagicMock()
        mock_row.trading_date = datetime.date(2025, 1, 16)
        mock_row.payload = _make_test_parquet_bytes()
        mock_row.sha256 = "hash16"
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]

        sync = SupabaseCurveSync(base_dir=tmp_path, engine=mock_engine)
        fetched = sync.prefetch_range(
            "USD-SOFR-1D",
            start=datetime.date(2025, 1, 15),
            end=datetime.date(2025, 1, 16),
        )

        assert datetime.date(2025, 1, 16) in fetched
        assert datetime.date(2025, 1, 15) not in fetched
