"""Tests for Caching.layered_cache_mixin — L1 diskcache + L2 Supabase KV."""

import queue
from unittest.mock import MagicMock, patch

import pytest


class _TestConsumer:
    """Minimal consumer using LayeredCacheMixin, defined inside test to avoid import issues."""
    pass


def _make_consumer(tmp_path, l2_enabled=True, l2_read=True, l2_write=True, ttl=300):
    """Create a LayeredCacheMixin subclass instance with configurable toggles."""
    from Caching.layered_cache_mixin import LayeredCacheMixin

    class Consumer(LayeredCacheMixin):
        L2_ENABLED = l2_enabled
        L2_READ = l2_read
        L2_WRITE = l2_write
        L2_TTL_SECONDS = ttl

    c = Consumer()
    c.open_cache(cache_attr="my_cache", path=str(tmp_path / "test_cache"))
    return c


class TestLayeredCacheMixinInit:
    """LayeredCacheMixin extends DiskCacheMixin."""

    def test_is_subclass_of_diskcache_mixin(self):
        from Caching.layered_cache_mixin import LayeredCacheMixin
        from Caching.DiskCacheMixin import DiskCacheMixin
        assert issubclass(LayeredCacheMixin, DiskCacheMixin)

    def test_has_l2_class_vars(self):
        from Caching.layered_cache_mixin import LayeredCacheMixin
        assert hasattr(LayeredCacheMixin, "L2_ENABLED")
        assert hasattr(LayeredCacheMixin, "L2_READ")
        assert hasattr(LayeredCacheMixin, "L2_WRITE")
        assert hasattr(LayeredCacheMixin, "L2_TTL_SECONDS")


class TestOpenCacheWrapping:
    """open_cache() wraps L1 with LayeredDictProxy when L2 is enabled."""

    def test_wraps_cache_attr_when_l2_enabled(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy
        c = _make_consumer(tmp_path, l2_enabled=True)
        assert isinstance(c.my_cache, LayeredDictProxy)

    def test_namespace_uses_last_path_component(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True)
        assert c.my_cache._ns == "test_cache"

    def test_no_wrap_when_l2_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy
        c = _make_consumer(tmp_path, l2_enabled=False)
        assert not isinstance(c.my_cache, LayeredDictProxy)


class TestLayeredDictProxyL1Only:
    """LayeredDictProxy works as pure L1 when L2 is disabled for reads/writes."""

    def test_set_and_get_l1_only(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=False)
        c.my_cache["hello"] = "world"
        assert c.my_cache["hello"] == "world"

    def test_keyerror_on_miss(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARBS_SUPABASE_ENABLED", "0")
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=False)
        with pytest.raises(KeyError):
            _ = c.my_cache["nonexistent"]


class TestLayeredDictProxyL2Fallback:
    """LayeredDictProxy falls back to L2 on L1 miss."""

    def test_l2_fallback_on_miss(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_read=True)

        # Mock the L2 get to return a value
        mock_row = MagicMock()
        mock_row.payload = b'\x80\x05\x95\x0b\x00\x00\x00\x00\x00\x00\x00\x8c\x07from_l2\x94.'  # cloudpickle of "from_l2"
        mock_row.serializer = "cloudpickle"

        with patch.object(c.my_cache, "_l2_get", return_value=mock_row):
            with patch.object(c.my_cache, "_deserialize", return_value="from_l2"):
                val = c.my_cache["missing_key"]

        assert val == "from_l2"

    def test_contains_returns_true_and_hydrates_from_l2_on_local_miss(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_read=True)
        payload = {"result": "curve-json", "pricing_location": "NYC"}
        mock_row = MagicMock()
        mock_row.payload = b"unused"
        mock_row.serializer = "cloudpickle"

        with patch.object(c.my_cache, "_l2_get", return_value=mock_row) as mock_l2_get:
            with patch.object(c.my_cache, "_deserialize", return_value=payload) as mock_deserialize:
                assert "curve-key" in c.my_cache

        assert c.my_cache.raw["curve-key"] == payload
        mock_l2_get.assert_called_once()
        mock_deserialize.assert_called_once_with(mock_row.payload, mock_row.serializer)

    def test_contains_hydration_supports_fetch_then_get_access_pattern(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_read=True)
        payload = {"result": "curve-json", "pricing_location": "LDN"}
        mock_row = MagicMock()
        mock_row.payload = b"unused"
        mock_row.serializer = "cloudpickle"

        with patch.object(c.my_cache, "_l2_get", return_value=mock_row) as mock_l2_get:
            with patch.object(c.my_cache, "_deserialize", return_value=payload) as mock_deserialize:
                cached = None
                if "curve-key" in c.my_cache:
                    cached = c.my_cache["curve-key"]

        assert cached == payload
        assert c.my_cache.raw["curve-key"] == payload
        mock_l2_get.assert_called_once()
        mock_deserialize.assert_called_once_with(mock_row.payload, mock_row.serializer)

    def test_l2_write_on_set(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)

        with patch.object(c.my_cache, "_l2_set_async") as mock_l2_set:
            c.my_cache["key"] = "value"

        mock_l2_set.assert_called_once()

    def test_local_hit_without_session_timestamp_does_not_probe_l2(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_read=True)
        c.my_cache.raw["key"] = "value"

        with patch.object(c.my_cache, "_l2_get") as mock_l2_get:
            assert c.my_cache["key"] == "value"

        mock_l2_get.assert_not_called()

    def test_async_writer_starts_shared_workers_once(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)
        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITE_QUEUE", None)
        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITE_WORKERS_STARTED", False)
        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITE_WORKER_COUNT", 2)

        started_names = []

        class DummyThread:
            def __init__(self, *args, **kwargs):
                started_names.append(kwargs["name"])

            def start(self):
                return None

        with patch("Caching.layered_cache_mixin.threading.Thread", side_effect=DummyThread):
            c.my_cache._l2_set_async("cache-key-1", "key1", "value1")
            c.my_cache._l2_set_async("cache-key-2", "key2", "value2")

        assert started_names == ["layered-cache-l2-0", "layered-cache-l2-1"]
        assert LayeredDictProxy._L2_WRITE_QUEUE is not None
        assert LayeredDictProxy._L2_WRITE_QUEUE.qsize() == 2

        # Items are now pre-serialized 5-tuples
        item = LayeredDictProxy._L2_WRITE_QUEUE.get_nowait()
        assert len(item) == 5
        ns, cache_key, key_repr, payload_bytes, serializer = item
        assert isinstance(payload_bytes, bytes)
        assert serializer in ("cloudpickle", "pickle")

    def test_async_writer_drops_when_queue_is_full(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)

        class FullQueue:
            def full(self):
                return True

            def put_nowait(self, item):
                raise queue.Full

            def put(self, item, timeout=None):
                raise queue.Full

        with patch.object(type(c.my_cache), "_ensure_l2_write_workers", return_value=FullQueue()):
            with patch("Caching.layered_cache_mixin.logger.debug") as mock_debug:
                c.my_cache._l2_set_async("cache-key-1", "key1", "value1")

        mock_debug.assert_called_once()

    def test_serialization_happens_before_enqueue(self, tmp_path, monkeypatch):
        """Payload is pre-serialized to bytes before hitting the queue."""
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)
        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITE_QUEUE", None)
        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITE_WORKERS_STARTED", False)

        class DummyThread:
            def __init__(self, *args, **kwargs):
                pass
            def start(self):
                pass

        with patch("Caching.layered_cache_mixin.threading.Thread", side_effect=DummyThread):
            c.my_cache._l2_set_async("cache-key", "key", {"complex": [1, 2, 3]})

        item = LayeredDictProxy._L2_WRITE_QUEUE.get_nowait()
        ns, cache_key, key_repr, payload_bytes, serializer = item
        assert isinstance(payload_bytes, bytes)
        assert len(payload_bytes) > 0

    def test_backpressure_timeout_before_drop(self, tmp_path, monkeypatch):
        """With timeout > 0, put() is called with timeout instead of put_nowait()."""
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)

        put_calls = []

        class TrackingQueue:
            def full(self):
                return False

            def put(self, item, timeout=None):
                put_calls.append(("put", timeout))
            def put_nowait(self, item):
                put_calls.append(("put_nowait", None))

        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITE_TIMEOUT", 0.1)
        with patch.object(type(c.my_cache), "_ensure_l2_write_workers", return_value=TrackingQueue()):
            c.my_cache._l2_set_async("cache-key", "key", "value")

        assert len(put_calls) == 1
        assert put_calls[0][0] == "put"
        assert put_calls[0][1] == 0.1

    def test_zero_timeout_uses_put_nowait(self, tmp_path, monkeypatch):
        """With timeout == 0, put_nowait() is used for non-blocking behavior."""
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)

        put_calls = []

        class TrackingQueue:
            def full(self):
                return False

            def put(self, item, timeout=None):
                put_calls.append(("put", timeout))
            def put_nowait(self, item):
                put_calls.append(("put_nowait", None))

        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITE_TIMEOUT", 0.0)
        with patch.object(type(c.my_cache), "_ensure_l2_write_workers", return_value=TrackingQueue()):
            c.my_cache._l2_set_async("cache-key", "key", "value")

        assert len(put_calls) == 1
        assert put_calls[0][0] == "put_nowait"

    def test_stats_counters_increment(self, tmp_path, monkeypatch):
        """Write counters track successful enqueues and drops."""
        monkeypatch.delenv("ARBS_SUPABASE_ENABLED", raising=False)
        monkeypatch.delenv("ARBS_DATABASE_URL", raising=False)
        import importlib
        import Caching.supabase_engine as eng
        importlib.reload(eng)

        from Caching.layered_cache_mixin import LayeredDictProxy

        c = _make_consumer(tmp_path, l2_enabled=True, l2_write=True)

        # Reset counters
        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITES_OK", 0)
        monkeypatch.setattr(LayeredDictProxy, "_L2_WRITES_DROPPED", 0)

        # Successful enqueue
        ok_queue = queue.Queue(maxsize=10)
        with patch.object(type(c.my_cache), "_ensure_l2_write_workers", return_value=ok_queue):
            c.my_cache._l2_set_async("cache-key", "key", "value")
        assert LayeredDictProxy._L2_WRITES_OK == 1
        assert LayeredDictProxy._L2_WRITES_DROPPED == 0

        # Full queue -> dropped
        class FullQueue:
            def full(self):
                return True

            def put(self, item, timeout=None):
                raise queue.Full
            def put_nowait(self, item):
                raise queue.Full

        with patch.object(type(c.my_cache), "_ensure_l2_write_workers", return_value=FullQueue()):
            c.my_cache._l2_set_async("cache-key", "key", "value")
        assert LayeredDictProxy._L2_WRITES_OK == 1
        assert LayeredDictProxy._L2_WRITES_DROPPED == 1
