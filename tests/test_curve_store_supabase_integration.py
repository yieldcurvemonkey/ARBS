"""Tests for CurveStore L2 Supabase integration."""

import datetime
import threading
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
        assert store.wait_for_background_pushes(timeout=2.0) == 1
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

    def test_wait_for_background_pushes_joins_pending_threads(self, tmp_path):
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

        started = threading.Event()
        release = threading.Event()
        mock_sync = MagicMock()

        def _slow_push(curve_name, trading_date):
            started.set()
            assert release.wait(timeout=2.0)

        mock_sync.push_day.side_effect = _slow_push

        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            result = store.write_day("USD-SOFR-1D", datetime.date(2025, 1, 15), [snap])
            assert result is not None
            assert started.wait(timeout=1.0)
            release.set()
            waited = store.wait_for_background_pushes(timeout=2.0)

        assert waited == 1
        assert store.wait_for_background_pushes(timeout=0.0) == 0
        mock_sync.push_day.assert_called_once_with("USD-SOFR-1D", datetime.date(2025, 1, 15))

    def test_write_day_limits_background_push_concurrency(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path, bg_push_workers=2)
        active_lock = threading.Lock()
        release = threading.Event()
        two_started = threading.Event()
        third_started = threading.Event()
        active_pushes = 0
        max_active_pushes = 0

        def _make_snapshot(trading_date):
            return CurveSnapshot(
                timestamp_utc=datetime.datetime.combine(
                    trading_date,
                    datetime.time(21, 0, tzinfo=datetime.timezone.utc),
                ),
                timestamp_local=datetime.datetime(2025, 1, 15, 15, 0),
                trading_date=trading_date,
                session_minute=540,
                curve_name="USD-SOFR-1D",
                cfg_hash="test",
                reference_key="ref",
                interpolation="log_linear",
                node_dates=[trading_date + datetime.timedelta(days=1)],
                discount_factors=[0.999],
            )

        def _slow_push(curve_name, trading_date):
            nonlocal active_pushes, max_active_pushes
            with active_lock:
                active_pushes += 1
                max_active_pushes = max(max_active_pushes, active_pushes)
                if active_pushes >= 2:
                    two_started.set()
                if active_pushes >= 3:
                    third_started.set()
            assert release.wait(timeout=2.0)
            with active_lock:
                active_pushes -= 1

        mock_sync = MagicMock()
        mock_sync.push_day.side_effect = _slow_push

        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            for offset in range(4):
                trading_date = datetime.date(2025, 1, 15) + datetime.timedelta(days=offset)
                result = store.write_day("USD-SOFR-1D", trading_date, [_make_snapshot(trading_date)])
                assert result is not None

            assert two_started.wait(timeout=1.0)
            assert not third_started.wait(timeout=0.2)
            release.set()
            assert store.wait_for_background_pushes(timeout=2.0) == 4

        assert max_active_pushes == 2
        assert mock_sync.push_day.call_count == 4


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


class TestReadRawNodesL2:
    def test_read_raw_nodes_prefetches_from_supabase_when_local_missing(self, tmp_path):
        from Caching.curve_store import CurveStore
        from tests.test_supabase_curve_sync import _make_test_parquet_bytes

        store = CurveStore(base_dir=tmp_path)
        target_date = datetime.date(2025, 1, 15)
        target_ts = datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)

        def _prefetch(curve_name, start, end):
            assert curve_name == "USD-SOFR-1D"
            assert start == target_date
            assert end == target_date
            part_dir = tmp_path / "raw" / "asset=USD-SOFR-1D" / f"date={target_date.isoformat()}"
            part_dir.mkdir(parents=True, exist_ok=True)
            (part_dir / "prefetched.parquet").write_bytes(_make_test_parquet_bytes())
            return [target_date]

        mock_sync = MagicMock()
        mock_sync.prefetch_range.side_effect = _prefetch
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_raw_nodes(
                "USD-SOFR-1D",
                start=target_date,
                end=target_date,
                timestamps_utc=[target_ts],
            )

        assert len(df) == 1
        mock_sync.prefetch_range.assert_called_once_with("USD-SOFR-1D", target_date, target_date)


class TestAnalyticsL2:
    def test_write_analytics_day_calls_push_in_background(self, tmp_path):
        from Caching.curve_store import CurveStore

        store = CurveStore(base_dir=tmp_path)
        analytics_df = pytest.importorskip("pandas").DataFrame(
            {
                "timestamp_utc": [datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)],
                "trading_date": [datetime.date(2025, 1, 15)],
                "session_minute": [540],
                "par_rate_10Y": [4.25],
                "rate_10Y": [4.25],
            }
        )

        mock_sync = MagicMock()
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            result = store.write_analytics_day("USD-SOFR-1D", datetime.date(2025, 1, 15), analytics_df, overwrite=True)

        assert result is not None
        assert store.wait_for_background_pushes(timeout=2.0) == 1
        mock_sync.push_analytics_day.assert_called_once_with("USD-SOFR-1D", datetime.date(2025, 1, 15))

    def test_read_analytics_prefetches_from_supabase_when_local_missing(self, tmp_path):
        from Caching.curve_store import CurveStore

        store = CurveStore(base_dir=tmp_path)
        analytics_df = pytest.importorskip("pandas").DataFrame(
            {
                "timestamp_utc": [datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)],
                "trading_date": [datetime.date(2025, 1, 15)],
                "session_minute": [540],
                "par_rate_10Y": [4.25],
                "rate_10Y": [4.25],
            }
        )

        def _prefetch(curve_name, start, end):
            assert curve_name == "USD-SOFR-1D"
            assert start == datetime.date(2025, 1, 15)
            assert end == datetime.date(2025, 1, 15)
            store.write_analytics_day("USD-SOFR-1D", datetime.date(2025, 1, 15), analytics_df, overwrite=True)
            return [datetime.date(2025, 1, 15)]

        mock_sync = MagicMock()
        mock_sync.prefetch_analytics_range.side_effect = _prefetch
        with patch("Caching.curve_store._get_curve_sync", return_value=mock_sync):
            df = store.read_analytics(
                "USD-SOFR-1D",
                start=datetime.date(2025, 1, 15),
                end=datetime.date(2025, 1, 15),
                tenors=["10Y"],
                metrics=["par_rate", "rate"],
            )

        assert not df.empty
        assert float(df.iloc[0]["par_rate_10Y"]) == 4.25
        mock_sync.prefetch_analytics_range.assert_called_once()

    def test_read_analytics_supports_mixed_legacy_schema(self, tmp_path):
        from Caching.curve_store import CurveStore

        pd = pytest.importorskip("pandas")

        store = CurveStore(base_dir=tmp_path)
        legacy_df = pd.DataFrame(
            {
                "timestamp_utc": [datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)],
                "trading_date": [datetime.date(2025, 1, 15)],
                "par_rate_10Y": [4.25],
                "rate_10Y": [4.25],
            }
        )
        current_df = pd.DataFrame(
            {
                "timestamp_utc": [datetime.datetime(2025, 1, 16, 21, 0, tzinfo=datetime.timezone.utc)],
                "trading_date": [datetime.date(2025, 1, 16)],
                "session_minute": [540],
                "par_rate_10Y": [4.30],
                "rate_10Y": [4.30],
            }
        )

        with patch("Caching.curve_store._get_curve_sync", return_value=None):
            store.write_analytics_day("USD-SOFR-1D", datetime.date(2025, 1, 15), legacy_df, overwrite=True)
            store.write_analytics_day("USD-SOFR-1D", datetime.date(2025, 1, 16), current_df, overwrite=True)

        df = store.read_analytics(
            "USD-SOFR-1D",
            start=datetime.date(2025, 1, 15),
            end=datetime.date(2025, 1, 16),
            tenors=["10Y"],
            metrics=["par_rate", "rate"],
        )

        assert list(pd.to_datetime(df["trading_date"]).dt.date) == [
            datetime.date(2025, 1, 15),
            datetime.date(2025, 1, 16),
        ]
        assert list(df["par_rate_10Y"]) == [4.25, 4.30]
        assert list(df["rate_10Y"]) == [4.25, 4.30]
        assert list(df["session_minute"].astype("Int64")) == [540, 540]

    def test_read_analytics_tolerates_requested_columns_missing_from_all_files(self, tmp_path):
        from Caching.curve_store import CurveStore

        pd = pytest.importorskip("pandas")

        store = CurveStore(base_dir=tmp_path)
        analytics_df = pd.DataFrame(
            {
                "timestamp_utc": [datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)],
                "trading_date": [datetime.date(2025, 1, 15)],
                "session_minute": [540],
                "rate_1Y2Y": [4.25],
            }
        )

        with patch("Caching.curve_store._get_curve_sync", return_value=None):
            store.write_analytics_day("USD-SOFR-1D", datetime.date(2025, 1, 15), analytics_df, overwrite=True)

        df = store.read_analytics(
            "USD-SOFR-1D",
            start=datetime.date(2025, 1, 15),
            end=datetime.date(2025, 1, 15),
            tenors=["1Y2Y"],
            metrics=["par_rate", "rate"],
        )

        assert "rate_1Y2Y" in df.columns
        assert "par_rate_1Y2Y" not in df.columns
        assert float(df.iloc[0]["rate_1Y2Y"]) == 4.25

    def test_read_analytics_projected_reads_match_wide_reads_for_requested_columns(self, tmp_path):
        from Caching.curve_store import CurveStore

        pd = pytest.importorskip("pandas")

        store = CurveStore(base_dir=tmp_path)
        analytics_df = pd.DataFrame(
            {
                "timestamp_utc": [datetime.datetime(2025, 1, 15, 21, 0, tzinfo=datetime.timezone.utc)],
                "trading_date": [datetime.date(2025, 1, 15)],
                "session_minute": [540],
                "par_rate_10Y": [4.25],
                "rate_10Y": [4.25],
                "par_rate_1Y2Y": [4.05],
                "rate_1Y2Y": [4.05],
                "par_rate_30Y": [4.75],
                "rate_30Y": [4.75],
            }
        )

        with patch("Caching.curve_store._get_curve_sync", return_value=None):
            store.write_analytics_day("USD-SOFR-1D", datetime.date(2025, 1, 15), analytics_df, overwrite=True)

        projected = store.read_analytics(
            "USD-SOFR-1D",
            start=datetime.date(2025, 1, 15),
            end=datetime.date(2025, 1, 15),
            tenors=["10Y", "1Y2Y"],
            metrics=["par_rate", "rate"],
        ).reset_index(drop=True)
        wide = store.read_analytics(
            "USD-SOFR-1D",
            start=datetime.date(2025, 1, 15),
            end=datetime.date(2025, 1, 15),
        ).reset_index(drop=True)

        expected = wide.loc[
            :,
            [
                "timestamp_utc",
                "trading_date",
                "session_minute",
                "par_rate_10Y",
                "par_rate_1Y2Y",
                "rate_10Y",
                "rate_1Y2Y",
            ],
        ]
        pd.testing.assert_frame_equal(projected, expected)
