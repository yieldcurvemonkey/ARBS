"""
LayeredMapping — L1 (disk) + L2 (Postgres) read-through / write-through cache.

Implements MutableMapping so it can be used as a drop-in wherever FanoutCache
is used today.  On read miss from L1 the value is fetched from L2 and backfilled
into L1.  Writes go to both layers synchronously (write-through).

Distributed Invalidation
------------------------
In a multi-node deployment every node maintains its own L1 (diskcache).  If Node A
writes a new value, Node B's L1 still holds the stale copy and will never miss.
To bound staleness, ``l1_ttl_seconds`` sets a per-entry Time-To-Live on L1.
When diskcache expires the entry the next read becomes an L1 miss, triggers an
L2 fetch, and backfills a fresh copy with a new TTL.

For real-time invalidation, a future enhancement can layer Postgres
LISTEN/NOTIFY on top of this TTL floor (see pg_backend.py docstring).
"""
from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)


class LayeredMapping(MutableMapping):
    """
    Two-tier cache mapping.

    Parameters
    ----------
    l1 : MutableMapping
        Fast local cache (diskcache.FanoutCache).
    l2 : MutableMapping
        Remote backing store (PostgresCacheBackend).
    l2_read : bool
        Whether to read from L2 on L1 miss (default True).
    l2_write : bool
        Whether to write-through to L2 on set (default True).
    l1_ttl_seconds : int | None
        If set, L1 entries expire after this many seconds.  On expiry the
        next read triggers an L2 fetch and backfills L1 with a fresh TTL.
        Requires the L1 backend to support ``.set(key, value, expire=…)``
        (diskcache.FanoutCache does).  ``None`` means no TTL (infinite).
    """

    def __init__(
        self,
        l1: MutableMapping,
        l2: MutableMapping,
        *,
        l2_read: bool = True,
        l2_write: bool = True,
        l1_ttl_seconds: Optional[int] = None,
    ) -> None:
        self._l1 = l1
        self._l2 = l2
        self._l2_read = l2_read
        self._l2_write = l2_write
        self._l1_ttl = l1_ttl_seconds
        # Detect whether L1 supports .set(key, val, expire=…) (FanoutCache does)
        self._l1_has_set = callable(getattr(l1, "set", None))

    # -- internal: TTL-aware L1 write ---------------------------------------

    def _l1_put(self, key: str, value: Any) -> None:
        """Write to L1, applying TTL if configured."""
        if self._l1_ttl is not None and self._l1_has_set:
            self._l1.set(key, value, expire=self._l1_ttl)  # type: ignore[attr-defined]
        else:
            self._l1[key] = value

    # -- read ---------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        # Fast path: L1 hit (expired entries raise KeyError in FanoutCache)
        try:
            return self._l1[key]
        except KeyError:
            pass

        if not self._l2_read:
            raise KeyError(key)

        # L1 miss (or expired) → try L2
        try:
            value = self._l2[key]
        except KeyError:
            raise KeyError(key)
        except Exception:
            logger.debug("L2 read error for key=%s", key, exc_info=True)
            raise KeyError(key)

        # Backfill L1 with fresh TTL
        try:
            self._l1_put(key, value)
        except Exception:
            logger.debug("L1 backfill error for key=%s", key, exc_info=True)

        return value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    # -- write --------------------------------------------------------------

    def __setitem__(self, key: str, value: Any) -> None:
        self._l1_put(key, value)
        if self._l2_write:
            try:
                self._l2[key] = value
            except Exception:
                logger.warning("L2 write error for key=%s", key, exc_info=True)

    # -- delete -------------------------------------------------------------

    def __delitem__(self, key: str) -> None:
        l1_ok = False
        try:
            del self._l1[key]
            l1_ok = True
        except KeyError:
            pass

        l2_ok = False
        if self._l2_write:
            try:
                del self._l2[key]
                l2_ok = True
            except KeyError:
                pass
            except Exception:
                logger.debug("L2 delete error for key=%s", key, exc_info=True)

        if not l1_ok and not l2_ok:
            raise KeyError(key)

    # -- membership ---------------------------------------------------------

    def __contains__(self, key: object) -> bool:
        if key in self._l1:
            return True
        if self._l2_read:
            try:
                return key in self._l2
            except Exception:
                return False
        return False

    # -- iteration (union of L1 + L2 when l2_read is enabled) ---------------

    def __iter__(self) -> Iterator[str]:
        if not self._l2_read:
            return iter(self._l1)
        try:
            l2_keys = set(self._l2)
        except Exception:
            logger.debug("L2 iteration error; falling back to L1-only", exc_info=True)
            return iter(self._l1)
        # Union: all L1 keys + any L2-only keys not yet in L1.
        # L1 keys come first (fast/local), then L2 remainder.
        l1_keys = set(self._l1)
        return iter(list(l1_keys) + [k for k in l2_keys if k not in l1_keys])

    def __len__(self) -> int:
        if not self._l2_read:
            return len(self._l1)
        try:
            l2_keys = set(self._l2)
        except Exception:
            logger.debug("L2 len error; falling back to L1-only", exc_info=True)
            return len(self._l1)
        return len(set(self._l1) | l2_keys)

    def keys_l1_only(self) -> Iterator[str]:
        """Iterate L1 keys only — use when you explicitly want local-only."""
        return iter(self._l1)

    def len_l1_only(self) -> int:
        """L1 key count only — use when you explicitly want local-only."""
        return len(self._l1)

    # -- clear both layers --------------------------------------------------

    def clear(self) -> None:
        self._l1.clear()
        if self._l2_write:
            try:
                self._l2.clear()
            except Exception:
                logger.warning("L2 clear error", exc_info=True)

    # -- layer access (for diagnostics / migration) -------------------------

    @property
    def l1(self) -> MutableMapping:
        return self._l1

    @property
    def l2(self) -> MutableMapping:
        return self._l2
