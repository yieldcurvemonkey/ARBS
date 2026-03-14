"""
LayeredCacheMixin — drop-in replacement for DiskCacheMixin with L1 (disk) + L2 (Postgres).

Usage
-----
Replace ``DiskCacheMixin`` in any class's MRO with ``LayeredCacheMixin``::

    # Before
    class MyMDP(MarketDataProvider, DiskCacheMixin): ...

    # After
    class MyMDP(MarketDataProvider, LayeredCacheMixin): ...

Everything else (open_cache, close_cache, zodb aliases, diagnostics) works
identically.  When ``L2_ENABLED`` is True (default), every open_cache call
creates a LayeredMapping(L1=FanoutCache, L2=PostgresCacheBackend).  When False,
the mixin degrades to pure DiskCacheMixin behavior.

The L2 namespace is derived from the cache path stem so that each logical
cache maps to a distinct partition in the Postgres table.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional, TypeVar

from Caching.CodecMapping import CodecMapping, DecodeFn, EncodeFn
from Caching.DiskCacheMixin import DiskCacheMixin
from Caching.LayeredMapping import LayeredMapping
from Caching.pg_backend import PostgresCacheBackend

logger = logging.getLogger(__name__)
T = TypeVar("T", bound="LayeredCacheMixin")

_NS_RX = re.compile(r"[^\w.\-]")


def _namespace_from_path(path: str) -> str:
    """Derive a Postgres-friendly namespace from a cache directory path."""
    stem = Path(path).name
    return _NS_RX.sub("_", stem)


class LayeredCacheMixin(DiskCacheMixin):
    """
    DiskCacheMixin + L2 Postgres backing store.

    Class-level toggles
    -------------------
    L2_ENABLED : bool
        Master switch.  When False, behaves identically to DiskCacheMixin.
    L2_READ : bool
        Read-through from L2 on L1 miss.
    L2_WRITE : bool
        Write-through to L2 on every set.
    L1_TTL_SECONDS : int | None
        Time-to-live for L1 (disk) entries in seconds.  After expiry the
        next read triggers an L2 fetch, bounding cross-node staleness.
        ``None`` (default) means no TTL — suitable for single-node or
        when data is immutable / append-only (e.g. historical EOD caches).
        Recommended starting point for mutable caches: 300 (5 min).
    """

    L2_ENABLED: bool = True
    L2_READ: bool = True
    L2_WRITE: bool = True
    L1_TTL_SECONDS: Optional[int] = None

    def __init__(self: T, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._l2_backends: dict[str, PostgresCacheBackend] = {}

    def open_cache(
        self: T,
        *,
        cache_attr: str,
        path: str,
        encode: EncodeFn | None = None,
        decode: DecodeFn | None = None,
        force: bool | None = None,
    ) -> None:
        if force is None:
            force = self._force_refresh

        # Handle force-refresh on reopening
        if force and cache_attr in self._dc_caches:
            old_dir = self._dc_caches.pop(cache_attr)
            if hasattr(self, cache_attr):
                delattr(self, cache_attr)
            if cache_attr in self._l2_backends:
                del self._l2_backends[cache_attr]

        # Idempotent: already open → skip
        if cache_attr in self._dc_caches:
            return

        # L1: local FanoutCache (reuses parent's registry/singleton logic)
        l1 = self._acquire_cache(path)

        if force:
            l1.clear()

        # L2: Postgres backend (if enabled)
        if self.L2_ENABLED:
            try:
                ns = _namespace_from_path(path)
                l2 = PostgresCacheBackend(namespace=ns)
                self._l2_backends[cache_attr] = l2

                if force:
                    try:
                        l2.clear()
                    except Exception:
                        logger.debug("L2 clear failed for ns=%s", ns, exc_info=True)

                mapping: Any = LayeredMapping(
                    l1,
                    l2,
                    l2_read=self.L2_READ,
                    l2_write=self.L2_WRITE,
                    l1_ttl_seconds=self.L1_TTL_SECONDS,
                )
            except Exception:
                logger.warning(
                    "L2 init failed for cache_attr=%s; falling back to L1 only",
                    cache_attr,
                    exc_info=True,
                )
                mapping = l1
        else:
            mapping = l1

        # Codec wrapping (same as DiskCacheMixin)
        if encode or decode:
            mapping = CodecMapping(mapping, encode, decode)
            self._codec_wrappers[cache_attr] = mapping

        setattr(self, cache_attr, mapping)
        self._dc_caches[cache_attr] = path

    def close_cache(self: T) -> None:
        super().close_cache()
        self._l2_backends.clear()

    @classmethod
    def l2_diagnostics(cls) -> dict[str, dict[str, Any]]:
        """Return L2 stats for all instances that have been opened (if accessible)."""
        # L2 diagnostics are per-instance; this is a convenience for manual debugging.
        return {}
