"""Integration tests for CORE distributed cache — end-to-end flow."""

import datetime
import io
from unittest.mock import MagicMock, patch

import pyarrow.parquet as pq
import pytest


class TestCOREEndToEnd:
    """Full flow: write locally, push to 'Supabase', pull from 'Supabase', verify."""

    def test_write_push_pull_roundtrip(self, tmp_path):
        from Caching.curve_store import CurveStore, CurveSnapshot
        from Caching.supabase_curve_sync import SupabaseCurveSync

        # Two separate CurveStores simulating producer and consumer
        producer_dir = tmp_path / "producer"
        consumer_dir = tmp_path / "consumer"

        producer_store = CurveStore(base_dir=producer_dir)
        consumer_store = CurveStore(base_dir=consumer_dir)

        # Shared in-memory "Supabase" — dict keyed by (curve_name, date)
        blob_store: dict = {}

        class FakeEngine:
            """In-memory mock of Supabase for testing."""

            def begin(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, stmt, params=None):
                sql = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
                if "curve_intraday_blocks" in sql and "INSERT INTO" in sql:
                    key = (params["curve_name"], params["trading_date"])
                    blob_store[key] = params
                    return MagicMock()
                elif "curve_intraday_blocks" in sql and "SELECT" in sql:
                    key = (params["curve_name"], params["trading_date"])
                    if key in blob_store:
                        row = MagicMock()
                        row.payload = blob_store[key]["payload"]
                        row.sha256 = blob_store[key]["sha256"]
                        row.data_format = "parquet_zstd"
                        result = MagicMock()
                        result.fetchone.return_value = row
                        return result
                    result = MagicMock()
                    result.fetchone.return_value = None
                    return result
                elif "curve_snapshots" in sql and "INSERT INTO" in sql:
                    return MagicMock()
                return MagicMock()

        fake_engine = FakeEngine()

        # Producer writes locally
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 6, 15, 20, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 6, 15, 15, 0),
            trading_date=datetime.date(2025, 6, 15),
            session_minute=540,
            curve_name="USD-SOFR-1D",
            cfg_hash="integ_test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 6, 16), datetime.date(2025, 12, 15)],
            discount_factors=[0.99987, 0.97523],
        )
        with patch("Caching.curve_store._get_curve_sync", return_value=None):
            producer_store.write_day("USD-SOFR-1D", datetime.date(2025, 6, 15), [snap])

        # Producer pushes to "Supabase"
        producer_sync = SupabaseCurveSync(base_dir=producer_dir, engine=fake_engine)
        producer_sync.push_day("USD-SOFR-1D", datetime.date(2025, 6, 15))

        assert ("USD-SOFR-1D", datetime.date(2025, 6, 15)) in blob_store

        # Consumer pulls from "Supabase"
        consumer_sync = SupabaseCurveSync(base_dir=consumer_dir, engine=fake_engine)
        result = consumer_sync.pull_day("USD-SOFR-1D", datetime.date(2025, 6, 15))
        assert result is True

        # Consumer reads locally (should now have data)
        df = consumer_store.read_raw_day("USD-SOFR-1D", datetime.date(2025, 6, 15))
        assert len(df) == 1
        assert df.iloc[0]["curve_name"] == "USD-SOFR-1D"
        assert len(df.iloc[0]["discount_factors"]) == 2
        assert abs(df.iloc[0]["discount_factors"][0] - 0.99987) < 1e-10


class TestGracefulDegradation:
    """System operates normally when the Supabase layer is explicitly disabled."""

    def test_curvestore_works_without_supabase(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.curve_store import CurveStore, CurveSnapshot

        store = CurveStore(base_dir=tmp_path)
        snap = CurveSnapshot(
            timestamp_utc=datetime.datetime(2025, 1, 10, 20, 0, tzinfo=datetime.timezone.utc),
            timestamp_local=datetime.datetime(2025, 1, 10, 14, 0),
            trading_date=datetime.date(2025, 1, 10),
            session_minute=420,
            curve_name="TEST-CURVE",
            cfg_hash="test",
            reference_key="ref",
            interpolation="log_linear",
            node_dates=[datetime.date(2025, 1, 11)],
            discount_factors=[0.999],
        )

        with patch("Caching.curve_store._get_curve_sync", return_value=None):
            result = store.write_day("TEST-CURVE", datetime.date(2025, 1, 10), [snap])
            assert result is not None

            df = store.read_raw_day("TEST-CURVE", datetime.date(2025, 1, 10))
            assert len(df) == 1

    def test_layered_cache_works_without_supabase(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredCacheMixin

        class TestMDP(LayeredCacheMixin):
            pass

        mdp = TestMDP()
        mdp.open_cache(cache_attr="test_cache", path=str(tmp_path / "test"))
        mdp.test_cache["key"] = "value"
        assert mdp.test_cache["key"] == "value"
