"""Tests for CurveStore L2 Supabase integration."""

import datetime
from unittest.mock import MagicMock, patch

import pytest


class TestWriteDayL2:
    """write_day() triggers background L2 push when Supabase is enabled."""

    def test_write_day_uses_store_base_dir_for_sync(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot

        store_base_dir = tmp_path / "custom_store"
        store = CurveStore(base_dir=store_base_dir)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
            trading_date=datetime.date(2025, 1, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 16)],
            discount_factors=[0.999],
        )

        mock_sync = MagicMock()
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync) as get_sync:
            store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])

        assert get_sync.call_args.args[0] == store_base_dir

    def test_write_day_calls_push_in_background(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
            trading_date=datetime.date(2025, 1, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 16), datetime.date(2025, 7, 15)],
            discount_factors=[0.999, 0.985],
        )

        mock_sync = MagicMock()
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            result = store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])

        assert result is not None  # local write succeeded
        # Background push was scheduled — wait briefly for thread to run
        import time
        time.sleep(0.2)
        mock_sync.push_day.assert_called_once_with("USD-SOFR-1D", datetime.date(2025, 1, 15))

    def test_write_day_succeeds_even_if_push_fails(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
            trading_date=datetime.date(2025, 1, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 16)],
            discount_factors=[0.999],
        )

        mock_sync = MagicMock()
        mock_sync.push_day.side_effect = Exception("Supabase down")
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            result = store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])

        # Local write still succeeded
        assert result is not None


class TestReadRawDayL2:
    """read_raw_day() falls back to L2 when local data is missing."""

    def test_read_uses_store_base_dir_for_sync(self, tmp_path):
        from Caching.curve_store import CurveStore

        store_base_dir = tmp_path / "custom_store"
        store = CurveStore(base_dir=store_base_dir)
        mock_sync = MagicMock()
        mock_sync.pull_day.return_value = False

        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync) as get_sync:
            store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert get_sync.call_args.args[0] == store_base_dir

    def test_read_falls_back_to_supabase(self, tmp_path):
        from Caching.curve_store import CurveStore

        store = CurveStore(base_dir=tmp_path)

        mock_sync = MagicMock()
        # Simulate pull_day writing a local file
        def fake_pull(curve_name, trading_date):
            from tests.test_supabase_curve_sync import _make_test_parquet_bytes
            part_dir = tmp_path / "raw" / f"asset={curve_name}" / f"date={trading_date.isoformat()}"
            part_dir.mkdir(parents=True, exist_ok=True)
            (part_dir / "pulled.parquet").write_bytes(_make_test_parquet_bytes())
            return True

        mock_sync.pull_day.side_effect = fake_pull
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert len(df) == 1
        mock_sync.pull_day.assert_called_once()

    def test_read_returns_empty_when_both_miss(self, tmp_path):
        from Caching.curve_store import CurveStore

        store = CurveStore(base_dir=tmp_path)
        mock_sync = MagicMock()
        mock_sync.pull_day.return_value = False  # Supabase also doesn't have it

        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert len(df) == 0

    def test_read_uses_local_when_available(self, tmp_path):
        """L1 hit should NOT trigger L2 pull."""
        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
            trading_date=datetime.date(2025, 1, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 16)],
            discount_factors=[0.999],
        )
        with patch("Caching.curve_store._get_curve_sync", return_value=None):
            store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])

        mock_sync = MagicMock()
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 1, 15))

        assert len(df) == 1
        mock_sync.pull_day.assert_not_called()
