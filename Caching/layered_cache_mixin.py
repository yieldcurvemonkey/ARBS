"""LayeredCacheMixin: DiskCacheMixin + Supabase L2 KV store.

Drop-in replacement for DiskCacheMixin. Wraps each opened cache with
a LayeredDictProxy that adds L2 Supabase fallback with TTL-based freshness.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import queue
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


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using default=%s", name, raw, default)
        return default


_DEFAULT_L2_WRITE_WORKERS = _env_positive_int("ARBS_SUPABASE_WRITE_WORKERS", 1)
_DEFAULT_L2_WRITE_QUEUE_SIZE = _env_positive_int("ARBS_SUPABASE_WRITE_QUEUE_SIZE", 512)


class LayeredDictProxy(MutableMapping):
    """Wraps L1 diskcache with L2 Supabase KV fallback."""

    _L2_WRITE_WORKER_COUNT: ClassVar[int] = _DEFAULT_L2_WRITE_WORKERS
    _L2_WRITE_QUEUE_MAXSIZE: ClassVar[int] = _DEFAULT_L2_WRITE_QUEUE_SIZE
    _L2_WRITE_QUEUE: ClassVar[queue.Queue[tuple[str, str, str, Any]] | None] = None
    _L2_WRITE_WORKERS_STARTED: ClassVar[bool] = False
    _L2_WRITE_LOCK: ClassVar[threading.Lock] = threading.Lock()

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
            return False  # Existing L1 value loaded from disk is treated as fresh
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
        if key in self._l1:
            return True

        if not self._l2_read:
            return False

        cache_key = self._hash_key(key)
        row = self._l2_get(cache_key)
        if row is None:
            return False

        value = self._deserialize(row.payload, row.serializer)
        self._l1[key] = value
        self._timestamps[cache_key] = time.time()
        return True

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

    @classmethod
    def _ensure_l2_write_workers(cls) -> queue.Queue[tuple[str, str, str, Any]]:
        work_queue = cls._L2_WRITE_QUEUE
        if work_queue is not None and cls._L2_WRITE_WORKERS_STARTED:
            return work_queue

        with cls._L2_WRITE_LOCK:
            work_queue = cls._L2_WRITE_QUEUE
            if work_queue is None:
                work_queue = queue.Queue(maxsize=cls._L2_WRITE_QUEUE_MAXSIZE)
                cls._L2_WRITE_QUEUE = work_queue

            if not cls._L2_WRITE_WORKERS_STARTED:
                # Keep background writes below the SQLAlchemy pool size so cache bursts
                # cannot starve foreground reads or calibrations.
                for idx in range(cls._L2_WRITE_WORKER_COUNT):
                    worker = threading.Thread(
                        target=cls._l2_write_worker,
                        args=(work_queue,),
                        name=f"layered-cache-l2-{idx}",
                        daemon=True,
                    )
                    worker.start()
                cls._L2_WRITE_WORKERS_STARTED = True

            return work_queue

    @classmethod
    def _l2_write_worker(cls, work_queue: queue.Queue[tuple[str, str, str, Any]]) -> None:
        while True:
            ns, cache_key, key_repr, value = work_queue.get()
            try:
                from Caching.supabase_schema import ensure_schema
                from Caching.supabase_engine import get_engine
                from sqlalchemy import text

                if not ensure_schema():
                    continue
                engine = get_engine()
                if engine is None:
                    continue
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
                            "ns": ns,
                            "key": cache_key,
                            "repr": key_repr,
                            "payload": payload,
                            "serializer": _DEFAULT_SERIALIZER,
                        },
                    )
            except Exception:
                logger.warning("L2 set failed for %s/%s", ns, cache_key[:12], exc_info=True)
            finally:
                work_queue.task_done()

    def _l2_set_async(self, cache_key: str, key: Any, value: Any) -> None:
        """Queue best-effort L2 UPSERTs onto a bounded shared worker pool."""
        work_queue = type(self)._ensure_l2_write_workers()
        try:
            work_queue.put_nowait((self._ns, cache_key, repr(key)[:500], value))
        except queue.Full:
            logger.warning("L2 write queue full; dropping write for %s/%s", self._ns, cache_key[:12])

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
