"""
LayeredMapping — L1 (disk) + L2 (Postgres) read-through / write-through cache.

Implements MutableMapping so it can be used as a drop-in wherever FanoutCache
is used today.  On read miss from L1 the value is fetched from L2 and backfilled
into L1.  Writes go to both layers synchronously (write-through).
"""
from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any, Iterator

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
    """

    def __init__(
        self,
        l1: MutableMapping,
        l2: MutableMapping,
        *,
        l2_read: bool = True,
        l2_write: bool = True,
    ) -> None:
        self._l1 = l1
        self._l2 = l2
        self._l2_read = l2_read
        self._l2_write = l2_write

    # -- read ---------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        # Fast path: L1 hit
        try:
            return self._l1[key]
        except KeyError:
            pass

        if not self._l2_read:
            raise KeyError(key)

        # L1 miss → try L2
        try:
            value = self._l2[key]
        except KeyError:
            raise KeyError(key)
        except Exception:
            logger.debug("L2 read error for key=%s", key, exc_info=True)
            raise KeyError(key)

        # Backfill L1
        try:
            self._l1[key] = value
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
        self._l1[key] = value
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

    # -- iteration (L1 only — iterating L2 would be expensive) --------------

    def __iter__(self) -> Iterator[str]:
        return iter(self._l1)

    def __len__(self) -> int:
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
