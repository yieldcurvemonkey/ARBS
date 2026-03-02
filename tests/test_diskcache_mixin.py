"""
Tests for DiskCacheMixin — drop-in replacement for ZODBCacheMixin.

Covers:
- Initialization and default parameters
- open_cache / close_cache lifecycle
- Codec (encode/decode) wrapping via CodecMapping
- Force-refresh behavior (cache clearing)
- Backward-compat aliases (zodb_open_cache, zodb_commit, close_zodb)
- batched() context manager (no-op)
- Shared FanoutCache via _CACHE_REGISTRY (singleton per directory)
- default_cache_path slug sanitization
- diagnostics() class method
- Multiple caches on a single instance
- Thread safety of registry
- CACHE_ROOT override
"""

import json
import os
import threading
import tempfile
from pathlib import Path

import pytest

from Caching.DiskCacheMixin import DiskCacheMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class CacheTester(DiskCacheMixin):
    """Minimal subclass for testing the mixin."""
    pass


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the global cache registry before and after every test."""
    saved_root = DiskCacheMixin.CACHE_ROOT
    DiskCacheMixin._CACHE_REGISTRY.clear()
    yield
    DiskCacheMixin._CACHE_REGISTRY.clear()
    DiskCacheMixin.CACHE_ROOT = saved_root


@pytest.fixture
def cache_dir(tmp_path):
    """Return a fresh temporary directory for a single test's cache."""
    return str(tmp_path / "test_cache")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_defaults(self):
        obj = CacheTester()
        assert obj._use_btree is True
        assert obj._force_refresh is False
        assert obj._dc_caches == {}
        assert obj._codec_wrappers == {}

    def test_custom_flags(self):
        obj = CacheTester(use_btree=False, force_refresh=True)
        assert obj._use_btree is False
        assert obj._force_refresh is True

    def test_none_coerced_to_false(self):
        obj = CacheTester(use_btree=None, force_refresh=None)
        assert obj._use_btree is False
        assert obj._force_refresh is False


# ---------------------------------------------------------------------------
# open_cache / close_cache
# ---------------------------------------------------------------------------

class TestOpenCloseCache:
    def test_open_creates_attr(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="my_cache", path=cache_dir)
        assert hasattr(obj, "my_cache")
        assert "my_cache" in obj._dc_caches

    def test_cache_is_usable_as_dict(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["key1"] = "value1"
        assert obj.c["key1"] == "value1"
        assert len(obj.c) == 1

    def test_close_removes_attr(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.close_cache()
        assert not hasattr(obj, "c")
        assert obj._dc_caches == {}

    def test_idempotent_open(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["k"] = 42
        # Second open should be a no-op (data preserved)
        obj.open_cache(cache_attr="c", path=cache_dir)
        assert obj.c["k"] == 42

    def test_directory_created(self, cache_dir):
        obj = CacheTester()
        assert not Path(cache_dir).exists()
        obj.open_cache(cache_attr="c", path=cache_dir)
        assert Path(cache_dir).exists()


# ---------------------------------------------------------------------------
# Codec wrapping
# ---------------------------------------------------------------------------

class TestCodecMapping:
    def test_encode_decode_roundtrip(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(
            cache_attr="jcache",
            path=cache_dir,
            encode=json.dumps,
            decode=json.loads,
        )
        obj.jcache["data"] = {"a": 1, "b": [2, 3]}
        result = obj.jcache["data"]
        assert result == {"a": 1, "b": [2, 3]}

    def test_codec_wrapper_tracked(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="jcache", path=cache_dir, encode=str, decode=eval)
        assert "jcache" in obj._codec_wrappers

    def test_no_codec_no_wrapper(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="raw", path=cache_dir)
        assert "raw" not in obj._codec_wrappers

    def test_close_clears_codec_wrappers(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="jcache", path=cache_dir, encode=str, decode=eval)
        obj.close_cache()
        assert obj._codec_wrappers == {}


# ---------------------------------------------------------------------------
# Force-refresh
# ---------------------------------------------------------------------------

class TestForceRefresh:
    def test_force_clears_existing_data(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["k"] = "old"
        obj.close_cache()

        obj.open_cache(cache_attr="c", path=cache_dir, force=True)
        assert "k" not in obj.c

    def test_force_refresh_instance_flag(self, tmp_path):
        d = str(tmp_path / "fr")
        obj = CacheTester(force_refresh=True)
        obj.open_cache(cache_attr="c", path=d)
        obj.c["k"] = "val"
        obj.close_cache()
        # Re-open: force=None → uses instance flag (True)
        obj.open_cache(cache_attr="c", path=d)
        assert "k" not in obj.c

    def test_force_false_preserves_data(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["persist"] = 999
        obj.close_cache()

        obj.open_cache(cache_attr="c", path=cache_dir, force=False)
        assert obj.c["persist"] == 999


# ---------------------------------------------------------------------------
# Backward-compat aliases
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_zodb_open_cache_alias(self, cache_dir):
        obj = CacheTester()
        obj.zodb_open_cache(cache_attr="c", path=cache_dir)
        assert hasattr(obj, "c")

    def test_zodb_commit_is_noop(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["x"] = 1
        obj.zodb_commit()  # should not raise
        assert obj.c["x"] == 1

    def test_close_zodb_alias(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.close_zodb()
        assert not hasattr(obj, "c")


# ---------------------------------------------------------------------------
# batched() context manager
# ---------------------------------------------------------------------------

class TestBatched:
    def test_batched_is_noop_context_manager(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        with obj.batched():
            obj.c["inside"] = "batch"
        assert obj.c["inside"] == "batch"


# ---------------------------------------------------------------------------
# Registry / shared FanoutCache
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_same_directory_shares_cache(self, cache_dir):
        a = CacheTester()
        b = CacheTester()
        a.open_cache(cache_attr="ca", path=cache_dir)
        b.open_cache(cache_attr="cb", path=cache_dir)
        a.ca["shared"] = "yes"
        assert b.cb["shared"] == "yes"

    def test_different_directories_isolated(self, tmp_path):
        d1 = str(tmp_path / "d1")
        d2 = str(tmp_path / "d2")
        a = CacheTester()
        b = CacheTester()
        a.open_cache(cache_attr="c", path=d1)
        b.open_cache(cache_attr="c", path=d2)
        a.c["only_a"] = True
        assert "only_a" not in b.c


# ---------------------------------------------------------------------------
# diagnostics()
# ---------------------------------------------------------------------------

class TestDiagnostics:
    def test_empty_initially(self):
        assert DiskCacheMixin.diagnostics() == {}

    def test_reports_cache_sizes(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["a"] = 1
        obj.c["b"] = 2
        diag = DiskCacheMixin.diagnostics()
        assert cache_dir in diag
        assert diag[cache_dir] == 2


# ---------------------------------------------------------------------------
# default_cache_path & slug
# ---------------------------------------------------------------------------

class TestDefaultCachePath:
    def test_slug_sanitizes(self):
        assert DiskCacheMixin._slug("hello/world:test") == "hello_world_test"
        assert DiskCacheMixin._slug("safe_name.v2") == "safe_name.v2"
        assert DiskCacheMixin._slug("a b c") == "a_b_c"

    def test_default_cache_path_returns_string(self):
        p = DiskCacheMixin.default_cache_path("test_stem")
        assert isinstance(p, str)
        assert "test_stem" in p

    def test_cache_root_override(self, tmp_path):
        DiskCacheMixin.CACHE_ROOT = tmp_path / "custom_root"
        p = DiskCacheMixin.default_cache_path("mystem")
        assert "custom_root" in p
        assert "dump" in p
        assert "mystem" in p


# ---------------------------------------------------------------------------
# Multiple caches on one instance
# ---------------------------------------------------------------------------

class TestMultipleCaches:
    def test_two_caches_independent(self, tmp_path):
        d1 = str(tmp_path / "prices")
        d2 = str(tmp_path / "curves")
        obj = CacheTester()
        obj.open_cache(cache_attr="prices", path=d1)
        obj.open_cache(cache_attr="curves", path=d2)
        obj.prices["AAPL"] = 150.0
        obj.curves["USD-SOFR"] = [0.04, 0.041]
        assert obj.prices["AAPL"] == 150.0
        assert obj.curves["USD-SOFR"] == [0.04, 0.041]
        assert "AAPL" not in obj.curves
        assert "USD-SOFR" not in obj.prices

    def test_close_removes_all(self, tmp_path):
        d1 = str(tmp_path / "a")
        d2 = str(tmp_path / "b")
        obj = CacheTester()
        obj.open_cache(cache_attr="a", path=d1)
        obj.open_cache(cache_attr="b", path=d2)
        obj.close_cache()
        assert not hasattr(obj, "a")
        assert not hasattr(obj, "b")
        assert obj._dc_caches == {}


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_open_same_dir(self, cache_dir):
        results = []
        errors = []

        def worker(idx):
            try:
                obj = CacheTester()
                obj.open_cache(cache_attr=f"c_{idx}", path=cache_dir)
                obj_cache = getattr(obj, f"c_{idx}")
                obj_cache[f"key_{idx}"] = idx
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
# Data type persistence
# ---------------------------------------------------------------------------

class TestDataTypes:
    def test_stores_strings(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["s"] = "hello world"
        assert obj.c["s"] == "hello world"

    def test_stores_numbers(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["i"] = 42
        obj.c["f"] = 3.14
        assert obj.c["i"] == 42
        assert obj.c["f"] == pytest.approx(3.14)

    def test_stores_lists(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["lst"] = [1, 2, 3]
        assert obj.c["lst"] == [1, 2, 3]

    def test_stores_dicts(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["d"] = {"nested": {"a": 1}}
        assert obj.c["d"] == {"nested": {"a": 1}}

    def test_stores_none(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["n"] = None
        assert obj.c["n"] is None

    def test_stores_bytes(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["b"] = b"\x00\x01\x02"
        assert obj.c["b"] == b"\x00\x01\x02"

    def test_delete_key(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["x"] = 1
        del obj.c["x"]
        assert "x" not in obj.c

    def test_contains(self, cache_dir):
        obj = CacheTester()
        obj.open_cache(cache_attr="c", path=cache_dir)
        obj.c["present"] = True
        assert "present" in obj.c
        assert "absent" not in obj.c
