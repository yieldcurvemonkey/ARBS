"""
Tests for LayeredCacheMixin and supporting components.

Covers:
- LayeredMapping read-through / write-through / delete / contains
- LayeredCacheMixin as drop-in replacement for DiskCacheMixin
- L2 disabled fallback (pure DiskCacheMixin behavior)
- Codec wrapping with layered backend
- Force-refresh clears both layers
- Namespace derivation from cache path
- PostgresCacheBackend MutableMapping contract (requires live Postgres)
"""

import json
import os
import threading
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from Caching.DiskCacheMixin import DiskCacheMixin
from Caching.LayeredMapping import LayeredMapping
from Caching.LayeredCacheMixin import LayeredCacheMixin, _namespace_from_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DictBackend(dict):
    """dict subclass that satisfies MutableMapping for testing L2."""
    pass


class LayeredTester(LayeredCacheMixin):
    """Minimal subclass for testing the mixin."""
    pass


@pytest.fixture(autouse=True)
def _clean_registry():
    saved_root = DiskCacheMixin.CACHE_ROOT
    DiskCacheMixin._CACHE_REGISTRY.clear()
    yield
    DiskCacheMixin._CACHE_REGISTRY.clear()
    DiskCacheMixin.CACHE_ROOT = saved_root


@pytest.fixture
def cache_dir(tmp_path):
    return str(tmp_path / "test_cache")


# ---------------------------------------------------------------------------
# LayeredMapping unit tests (no Postgres needed)
# ---------------------------------------------------------------------------


class TestLayeredMapping:
    def test_l1_hit(self):
        l1, l2 = DictBackend({"k": "v"}), DictBackend()
        lm = LayeredMapping(l1, l2)
        assert lm["k"] == "v"

    def test_l2_read_through_on_l1_miss(self):
        l1, l2 = DictBackend(), DictBackend({"k": "from_l2"})
        lm = LayeredMapping(l1, l2)
        assert lm["k"] == "from_l2"
        # Should backfill L1
        assert l1["k"] == "from_l2"

    def test_miss_both_layers_raises(self):
        l1, l2 = DictBackend(), DictBackend()
        lm = LayeredMapping(l1, l2)
        with pytest.raises(KeyError):
            lm["missing"]

    def test_write_through(self):
        l1, l2 = DictBackend(), DictBackend()
        lm = LayeredMapping(l1, l2)
        lm["k"] = "val"
        assert l1["k"] == "val"
        assert l2["k"] == "val"

    def test_write_l2_disabled(self):
        l1, l2 = DictBackend(), DictBackend()
        lm = LayeredMapping(l1, l2, l2_write=False)
        lm["k"] = "val"
        assert l1["k"] == "val"
        assert "k" not in l2

    def test_read_l2_disabled(self):
        l1, l2 = DictBackend(), DictBackend({"k": "hidden"})
        lm = LayeredMapping(l1, l2, l2_read=False)
        with pytest.raises(KeyError):
            lm["k"]

    def test_delete_both(self):
        l1, l2 = DictBackend({"k": "v"}), DictBackend({"k": "v"})
        lm = LayeredMapping(l1, l2)
        del lm["k"]
        assert "k" not in l1
        assert "k" not in l2

    def test_delete_missing_raises(self):
        l1, l2 = DictBackend(), DictBackend()
        lm = LayeredMapping(l1, l2)
        with pytest.raises(KeyError):
            del lm["nope"]

    def test_contains_checks_l2(self):
        l1, l2 = DictBackend(), DictBackend({"k": "v"})
        lm = LayeredMapping(l1, l2)
        assert "k" in lm
        assert "missing" not in lm

    def test_contains_l2_disabled(self):
        l1, l2 = DictBackend(), DictBackend({"k": "v"})
        lm = LayeredMapping(l1, l2, l2_read=False)
        assert "k" not in lm

    def test_iter_returns_l1_keys(self):
        l1 = DictBackend({"a": 1, "b": 2})
        l2 = DictBackend({"c": 3})
        lm = LayeredMapping(l1, l2)
        assert sorted(lm) == ["a", "b"]

    def test_len_returns_l1_length(self):
        l1 = DictBackend({"a": 1})
        l2 = DictBackend({"a": 1, "b": 2, "c": 3})
        lm = LayeredMapping(l1, l2)
        assert len(lm) == 1

    def test_clear_both(self):
        l1 = DictBackend({"a": 1})
        l2 = DictBackend({"a": 1, "b": 2})
        lm = LayeredMapping(l1, l2)
        lm.clear()
        assert len(l1) == 0
        assert len(l2) == 0

    def test_get_with_default(self):
        l1, l2 = DictBackend(), DictBackend()
        lm = LayeredMapping(l1, l2)
        assert lm.get("missing", "default") == "default"

    def test_get_from_l2(self):
        l1, l2 = DictBackend(), DictBackend({"k": 42})
        lm = LayeredMapping(l1, l2)
        assert lm.get("k") == 42

    def test_l2_write_error_does_not_block_l1(self):
        l1 = DictBackend()
        l2 = MagicMock()
        l2.__setitem__ = MagicMock(side_effect=ConnectionError("db down"))
        lm = LayeredMapping(l1, l2)
        lm["k"] = "val"
        assert l1["k"] == "val"

    def test_l2_read_error_raises_keyerror(self):
        l1 = DictBackend()
        l2 = MagicMock()
        l2.__getitem__ = MagicMock(side_effect=ConnectionError("db down"))
        lm = LayeredMapping(l1, l2)
        with pytest.raises(KeyError):
            lm["k"]

    def test_layer_properties(self):
        l1, l2 = DictBackend(), DictBackend()
        lm = LayeredMapping(l1, l2)
        assert lm.l1 is l1
        assert lm.l2 is l2


# ---------------------------------------------------------------------------
# Namespace derivation
# ---------------------------------------------------------------------------


class TestNamespaceDerivation:
    def test_simple_stem(self):
        assert _namespace_from_path("/foo/bar/my_cache") == "my_cache"

    def test_sanitizes_special_chars(self):
        assert _namespace_from_path("/foo/cache name:v2") == "cache_name_v2"

    def test_preserves_dots_and_dashes(self):
        assert _namespace_from_path("/foo/cache-stem.v1") == "cache-stem.v1"


# ---------------------------------------------------------------------------
# LayeredCacheMixin with L2 disabled (pure DiskCacheMixin behavior)
# ---------------------------------------------------------------------------


class TestL2Disabled:
    def test_behaves_like_diskcache_mixin(self, cache_dir):
        obj = LayeredTester()
        obj.L2_ENABLED = False
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["k"] = "v"
        assert obj.c["k"] == "v"
        obj.close_cache()
        assert not hasattr(obj, "c")

    def test_codec_wrapping_works(self, cache_dir):
        obj = LayeredTester()
        obj.L2_ENABLED = False
        obj.open_cache(
            cache_attr="jc", path=cache_dir, encode=json.dumps, decode=json.loads
        )
        obj.jc["data"] = {"a": 1}
        assert obj.jc["data"] == {"a": 1}

    def test_force_refresh_clears(self, cache_dir):
        obj = LayeredTester()
        obj.L2_ENABLED = False
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["k"] = "old"
        obj.close_cache()

        obj.open_cache(cache_attr="c", path=cache_dir, force=True)
        assert "k" not in obj.c


# ---------------------------------------------------------------------------
# LayeredCacheMixin with mocked L2
# ---------------------------------------------------------------------------


class _FakePgBackend(MutableMapping):
    """Dict-backed fake that replaces PostgresCacheBackend in tests."""

    _stores: dict[str, dict] = {}

    def __init__(self, namespace: str, engine=None):
        self._ns = namespace
        if namespace not in _FakePgBackend._stores:
            _FakePgBackend._stores[namespace] = {}

    def _s(self):
        return _FakePgBackend._stores[self._ns]

    def __getitem__(self, k):
        return self._s()[k]

    def __setitem__(self, k, v):
        self._s()[k] = v

    def __delitem__(self, k):
        del self._s()[k]

    def __contains__(self, k):
        return k in self._s()

    def __iter__(self):
        return iter(self._s())

    def __len__(self):
        return len(self._s())

    def clear(self):
        self._s().clear()

    def get(self, k, default=None):
        return self._s().get(k, default)


class TestLayeredCacheMixinMockedL2:
    @pytest.fixture(autouse=True)
    def _mock_pg(self):
        """Replace PostgresCacheBackend with _FakePgBackend for testing."""
        _FakePgBackend._stores.clear()

        with patch("Caching.LayeredCacheMixin.PostgresCacheBackend", _FakePgBackend):
            yield

        _FakePgBackend._stores.clear()

    def test_open_creates_layered_mapping(self, cache_dir):
        obj = LayeredTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        assert hasattr(obj, "c")
        # The underlying should be a LayeredMapping (not wrapped by codec)
        mapping = getattr(obj, "c")
        assert isinstance(mapping, LayeredMapping)

    def test_write_propagates_to_l2(self, cache_dir):
        obj = LayeredTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["k"] = "val"
        ns = _namespace_from_path(cache_dir)
        assert _FakePgBackend._stores[ns]["k"] == "val"

    def test_l2_read_through(self, cache_dir):
        ns = _namespace_from_path(cache_dir)
        _FakePgBackend._stores[ns] = {"remote_key": "remote_val"}
        obj = LayeredTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        assert obj.c["remote_key"] == "remote_val"

    def test_codec_with_layered(self, cache_dir):
        obj = LayeredTester()
        obj.open_cache(
            cache_attr="jc", path=cache_dir, encode=json.dumps, decode=json.loads
        )
        obj.jc["data"] = {"a": 1}
        assert obj.jc["data"] == {"a": 1}

    def test_close_clears_l2_backends(self, cache_dir):
        obj = LayeredTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        assert len(obj._l2_backends) == 1
        obj.close_cache()
        assert len(obj._l2_backends) == 0

    def test_idempotent_open(self, cache_dir):
        obj = LayeredTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["k"] = 42
        obj.open_cache(cache_attr="c", path=cache_dir)
        assert obj.c["k"] == 42

    def test_multiple_caches(self, tmp_path):
        d1 = str(tmp_path / "prices")
        d2 = str(tmp_path / "curves")
        obj = LayeredTester()
        obj.open_cache(cache_attr="prices", path=d1)
        obj.open_cache(cache_attr="curves", path=d2)
        obj.prices["AAPL"] = 150.0
        obj.curves["USD-SOFR"] = [0.04, 0.041]
        assert obj.prices["AAPL"] == 150.0
        assert obj.curves["USD-SOFR"] == [0.04, 0.041]
        assert "AAPL" not in obj.curves

    def test_backward_compat_aliases(self, cache_dir):
        obj = LayeredTester()
        obj.zodb_open_cache(cache_attr="c", path=cache_dir)
        assert hasattr(obj, "c")
        obj.zodb_commit()
        obj.close_zodb()
        assert not hasattr(obj, "c")

    def test_diagnostics(self, cache_dir):
        obj = LayeredTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["a"] = 1
        diag = DiskCacheMixin.diagnostics()
        assert cache_dir in diag

    def test_thread_safety(self, cache_dir):
        results = []
        errors = []

        def worker(idx):
            try:
                obj = LayeredTester()
                obj.open_cache(cache_attr=f"c_{idx}", path=cache_dir)
                c = getattr(obj, f"c_{idx}")
                c[f"key_{idx}"] = idx
                results.append(idx)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10


# ---------------------------------------------------------------------------
# PostgresCacheBackend integration tests (skipped without live Postgres)
# ---------------------------------------------------------------------------


def _pg_available() -> bool:
    try:
        from Caching.pg_backend import get_engine, ensure_schema

        engine = get_engine()
        ensure_schema(engine)
        with engine.begin() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_available(), reason="No Postgres connection available")
class TestPostgresCacheBackendIntegration:
    @pytest.fixture
    def backend(self):
        from Caching.pg_backend import PostgresCacheBackend

        ns = f"_test_{os.getpid()}"
        b = PostgresCacheBackend(namespace=ns)
        b.clear()
        yield b
        b.clear()

    def test_set_get(self, backend):
        backend["k"] = {"a": 1, "b": [2, 3]}
        assert backend["k"] == {"a": 1, "b": [2, 3]}

    def test_missing_key_raises(self, backend):
        with pytest.raises(KeyError):
            backend["nonexistent"]

    def test_delete(self, backend):
        backend["k"] = "v"
        del backend["k"]
        assert "k" not in backend

    def test_contains(self, backend):
        backend["present"] = True
        assert "present" in backend
        assert "absent" not in backend

    def test_len(self, backend):
        backend["a"] = 1
        backend["b"] = 2
        assert len(backend) == 2

    def test_iter(self, backend):
        backend["x"] = 1
        backend["y"] = 2
        assert sorted(backend) == ["x", "y"]

    def test_clear(self, backend):
        backend["a"] = 1
        backend["b"] = 2
        backend.clear()
        assert len(backend) == 0

    def test_bulk_put(self, backend):
        items = [(f"key_{i}", {"val": i}) for i in range(100)]
        n = backend.bulk_put(items)
        assert n == 100
        assert len(backend) == 100
        assert backend["key_50"]["val"] == 50

    def test_upsert_overwrites(self, backend):
        backend["k"] = "old"
        backend["k"] = "new"
        assert backend["k"] == "new"

    def test_stats(self, backend):
        backend["k"] = "v"
        s = backend.stats()
        assert s["count"] == 1
        assert s["total_bytes"] > 0

    def test_stores_complex_objects(self, backend):
        import numpy as np
        import pandas as pd

        df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
        backend["df"] = df
        result = backend["df"]
        pd.testing.assert_frame_equal(result, df)

        arr = np.array([1.0, 2.0, 3.0])
        backend["arr"] = arr
        np.testing.assert_array_equal(backend["arr"], arr)
