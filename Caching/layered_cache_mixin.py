"""LayeredCacheMixin: DiskCacheMixin + Supabase L2 KV store.

Drop-in replacement for DiskCacheMixin. Wraps each opened cache with
a LayeredDictProxy that adds L2 Supabase fallback with TTL-based freshness.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import threading
import time
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any, ClassVar, Optional

from Caching.DiskCacheMixin import DiskCacheMixin

logger = logging.getLogger(__name__)

try:
    import cloudpickle as _pickle_impl

    _DEFAULT_SERIALIZER = "cloudpickle"
except ImportError:  # pragma: no cover - exercised implicitly in environments without cloudpickle
    _pickle_impl = pickle
    _DEFAULT_SERIALIZER = "pickle"


class LayeredDictProxy(MutableMapping):
    """Wraps L1 diskcache with L2 Supabase KV fallback."""

    def __init__(
        self,
        l1: MutableMapping,
        cache_ns: str,
        *,
        l2_read: bool = True,
        l2_write: bool = True,
        ttl_seconds: int = 300,
    ):
        self._l1 = l1
        self._ns = cache_ns
        self._l2_read = l2_read
        self._l2_write = l2_write
        self._ttl = ttl_seconds
        # Track write timestamps for TTL (in-memory, not persisted)
        self._timestamps: dict[str, float] = {}

    def _hash_key(self, key: Any) -> str:
        return hashlib.sha256(_pickle_impl.dumps(key)).hexdigest()

    def _is_stale(self, cache_key: str) -> bool:
        ts = self._timestamps.get(cache_key)
        if ts is None:
            return True  # No timestamp = treat as potentially stale
        return (time.time() - ts) > self._ttl

    def __getitem__(self, key: Any) -> Any:
        cache_key = self._hash_key(key)

        # L1 check
        try:
            value = self._l1[key]
            if not self._is_stale(cache_key):
                return value
            # Stale — try L2, fall back to stale L1 if L2 fails
            if self._l2_read:
                row = self._l2_get(cache_key)
                if row is not None:
                    fresh = self._deserialize(row.payload, row.serializer)
                    self._l1[key] = fresh
                    self._timestamps[cache_key] = time.time()
                    return fresh
            # L2 miss or disabled — return stale L1
            return value
        except KeyError:
            pass

        # L1 miss — try L2
        if self._l2_read:
            row = self._l2_get(cache_key)
            if row is not None:
                value = self._deserialize(row.payload, row.serializer)
                self._l1[key] = value
                self._timestamps[cache_key] = time.time()
                return value

        raise KeyError(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        cache_key = self._hash_key(key)

        # L1 write (always synchronous)
        self._l1[key] = value
        self._timestamps[cache_key] = time.time()

        # L2 write (background, best-effort)
        if self._l2_write:
            self._l2_set_async(cache_key, key, value)

    def __delitem__(self, key: Any) -> None:
        del self._l1[key]
        cache_key = self._hash_key(key)
        self._timestamps.pop(cache_key, None)

    def __iter__(self) -> Iterator:
        return iter(self._l1)

    def __len__(self) -> int:
        return len(self._l1)

    def __contains__(self, key: Any) -> bool:
        return key in self._l1

    def clear(self) -> None:
        self._l1.clear()
        self._timestamps.clear()

    @property
    def raw(self) -> MutableMapping:
        """Access underlying L1 cache directly."""
        return self._l1

    def _l2_get(self, cache_key: str) -> Optional[Any]:
        """Fetch from Supabase KV table. Returns row or None."""
        try:
            from Caching.supabase_schema import ensure_schema
            from Caching.supabase_engine import get_engine
            from sqlalchemy import text

            if not ensure_schema():
                return None
            engine = get_engine()
            if engine is None:
                return None
            with engine.begin() as conn:
                return conn.execute(
                    text("""
                        SELECT payload, serializer
                        FROM arbs_kv_cache_v1
                        WHERE cache_ns = :ns AND cache_key = :key
                    """),
                    {"ns": self._ns, "key": cache_key},
                ).fetchone()
        except Exception:
            logger.warning("L2 get failed for %s/%s", self._ns, cache_key[:12], exc_info=True)
            return None

    def _l2_set_async(self, cache_key: str, key: Any, value: Any) -> None:
        """Background UPSERT to Supabase KV table."""
        def _bg():
            try:
                from Caching.supabase_schema import ensure_schema
                from Caching.supabase_engine import get_engine
                from sqlalchemy import text

                if not ensure_schema():
                    return
                engine = get_engine()
                if engine is None:
                    return
                payload = _pickle_impl.dumps(value)
                with engine.begin() as conn:
                    conn.execute(
                        text("""
                            INSERT INTO arbs_kv_cache_v1
                                (cache_ns, cache_key, key_repr, payload, serializer, updated_at)
                            VALUES
                                (:ns, :key, :repr, :payload, :serializer, NOW())
                            ON CONFLICT (cache_ns, cache_key) DO UPDATE SET
                                payload = EXCLUDED.payload,
                                key_repr = EXCLUDED.key_repr,
                                updated_at = NOW()
                        """),
                        {
                            "ns": self._ns,
                            "key": cache_key,
                            "repr": repr(key)[:500],
                            "payload": payload,
                            "serializer": _DEFAULT_SERIALIZER,
                        },
                    )
            except Exception:
                logger.warning("L2 set failed for %s/%s", self._ns, cache_key[:12], exc_info=True)

        threading.Thread(target=_bg, daemon=True).start()

    def _deserialize(self, payload: bytes, serializer: str) -> Any:
        """Deserialize L2 payload."""
        if serializer == "cloudpickle":
            try:
                import cloudpickle

                return cloudpickle.loads(payload)
            except ImportError:
                return pickle.loads(payload)
        if serializer == "pickle":
            return pickle.loads(payload)
        raise ValueError(f"Unknown serializer: {serializer}")


class LayeredCacheMixin(DiskCacheMixin):
    """Drop-in replacement for DiskCacheMixin with L2 Supabase persistence.

    Class-level toggles allow per-MDP configuration:
        L2_ENABLED     — master toggle
        L2_READ        — enable L2 read fallback
        L2_WRITE       — enable L2 write-through
        L2_TTL_SECONDS — L1 freshness window (seconds)
    """

    L2_ENABLED: ClassVar[bool] = True
    L2_READ: ClassVar[bool] = True
    L2_WRITE: ClassVar[bool] = True
    L2_TTL_SECONDS: ClassVar[int] = 300

    def open_cache(self, *, cache_attr: str, path: str, **kwargs) -> None:
        """Open L1 cache, then wrap with LayeredDictProxy if L2 enabled."""
        super().open_cache(cache_attr=cache_attr, path=path, **kwargs)

        from Caching.supabase_engine import SUPABASE_ENABLED

        if SUPABASE_ENABLED and self.L2_ENABLED:
            l1 = getattr(self, cache_attr)
            cache_ns = Path(path).name
            proxy = LayeredDictProxy(
                l1,
                cache_ns,
                l2_read=self.L2_READ,
                l2_write=self.L2_WRITE,
                ttl_seconds=self.L2_TTL_SECONDS,
            )
            setattr(self, cache_attr, proxy)
