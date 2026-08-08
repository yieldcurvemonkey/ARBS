r"""A process-wide cache of prepared CurveStore day windows.

Why this exists
---------------
A minute-resolution request re-read the SAME parquet partition once per
observation. Measured 2026-08-08, one warmed USD session (841 minutes of
``USD-SOFR-1D-CITIVELOEXCELMIN``, a 1,316 x 13 frame):

===========================  =============  ==================================
stage                        ms/observation what it was doing
===========================  =============  ==================================
``read_raw_day`` x2-3            17.392      re-reading one 537 KB file, 841x
``pd.to_datetime``                1.981      re-parsing the same stamp column
``pd.concat``                     1.080      re-joining the same two frames
``has_day`` x3                    0.964      re-stat-ing the same directories
===========================  =============  ==================================

That is 21.4 of the 30.4 ms a warmed minute point cost - **70%** - and every
millisecond of it was recomputing a value that had not changed.

What is cached, and what is not
-------------------------------
The unit is a **window**, not a day: the minute loader looks at the requested
local date and its two neighbours, because a session running to 19:59 local
straddles the UTC date boundary and the minute asked for can sit under either
partition. Caching the window (rather than three separate days) also removes the
``concat`` and the ``to_datetime``, which the caller would otherwise redo.

The frame is handed out **shared, not copied**. Callers here only read it and
then take ``.iloc[[i]]`` (which copies), so a copy per request would reintroduce
most of the cost it saves. Anything that intends to mutate must copy first.

Staleness
---------
Every hit re-validates against the partitions' file names, sizes and
modification times (~0.06 ms for three directories, vs 17 ms to re-read). A day
that is re-warmed mid-process - which the intraday warmer does, appending
minutes as they publish - therefore invalidates itself. A cache that trusted its
first read would serve a truncated session for the rest of the run, and would do
it silently.

Absence is cached the same way: a partition with no parquet file yields a
signature of ``None``, which is a legitimate cached value and is re-checked on
the same terms. That is what preserves ``has_day``'s contract - a cold day still
returns nothing and the caller still falls through to the live build.
"""

from __future__ import annotations

import datetime
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple

import pandas as pd

__all__ = [
    "DayWindow",
    "day_window",
    "single_day",
    "reset_day_cache",
    "day_cache_stats",
]

#: Windows retained. Measured 2026-08-08, one warmed minute session
#: (``USD-SOFR-1D-CITIVELOEXCELMIN``, 2026-07-22) is 1,226 rows of 45-node
#: curves and pickles to 0.67 MB, so a three-day window is ~2 MB. Eight windows
#: plus twenty-four day frames is therefore ~32 MB - enough for a backfill that
#: walks days in order and a dashboard that revisits a few, and small enough that
#: nobody has to think about it.
_MAX_ENTRIES = 8

#: Individual day frames retained under the windows. Larger than _MAX_ENTRIES
#: because each window holds up to three of them and adjacent windows overlap.
_MAX_DAY_FRAMES = 24

_LOCK = threading.RLock()
_CACHE: "OrderedDict[Tuple[str, str, Tuple[datetime.date, ...]], DayWindow]" = OrderedDict()
_DAY_FRAMES: "OrderedDict[Tuple[str, str, datetime.date], Tuple[Any, Any]]" = OrderedDict()
_STATS = {"hits": 0, "misses": 0, "revalidations": 0}


@dataclass(frozen=True)
class DayWindow:
    """One or more consecutive store days, joined and stamp-parsed once.

    ``frame`` is the concatenation of the days that exist, in the order the
    caller asked for them. ``stamps`` is ``pd.to_datetime(frame["timestamp_utc"],
    utc=True)`` for that same frame - kept beside it rather than recomputed,
    because parsing 1,316 stamps cost 2.0 ms per observation.
    """

    frame: pd.DataFrame
    stamps: pd.Series
    signature: Tuple[Any, ...]

    @property
    def empty(self) -> bool:
        return self.frame is None or self.frame.empty


def _partition_signature(store: Any, asset: str, day: datetime.date) -> Optional[Tuple[Any, ...]]:
    """``(name, size, mtime_ns)`` per parquet file, or ``None`` for a cold day.

    ``None`` deliberately matches ``has_day() is False``: a directory that does
    not exist and one that exists but holds no parquet are the same thing to the
    reader, and both must keep falling through to the live build.
    """
    try:
        part_dir = store.raw_partition_dir(asset, day)
    except AttributeError:  # a store predating raw_partition_dir
        return _LEGACY if store.has_day(asset, day) else None
    try:
        entries = [
            (e.name, e.stat().st_size, e.stat().st_mtime_ns)
            for e in os.scandir(part_dir)
            if e.name.endswith(".parquet")
        ]
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return None
    if not entries:
        return None
    return tuple(sorted(entries))


#: Signature used when the store cannot expose its partition directory. It is a
#: constant, so such a store gets a cache that never revalidates - correct only
#: because that store is also not the one this repo writes to mid-process.
_LEGACY: Tuple[Any, ...] = ("legacy-store",)


def _window_signature(
    store: Any, asset: str, days: Sequence[datetime.date]
) -> Tuple[Optional[Tuple[Any, ...]], ...]:
    return tuple(_partition_signature(store, asset, d) for d in days)


def _read_day(store: Any, asset: str, day: datetime.date, signature) -> Optional[pd.DataFrame]:
    """One day's frame, shared between overlapping windows.

    A second level under the window cache, because consecutive sessions overlap:
    a backfill walking day D then D+1 asks for windows (D, D-1, D+1) and
    (D+1, D, D+2), which have two days in common. Without this the same
    partition is read three times across a multi-day run instead of once.
    """
    key = (str(getattr(store, "base_dir", "")), asset, day)
    with _LOCK:
        hit = _DAY_FRAMES.get(key)
        if hit is not None and hit[0] == signature:
            _DAY_FRAMES.move_to_end(key)
            return hit[1]

    raw = store.read_raw_day(asset, day)

    with _LOCK:
        _DAY_FRAMES[key] = (signature, raw)
        _DAY_FRAMES.move_to_end(key)
        while len(_DAY_FRAMES) > _MAX_DAY_FRAMES:
            _DAY_FRAMES.popitem(last=False)
    return raw


def _build(store: Any, asset: str, days: Sequence[datetime.date], signature) -> DayWindow:
    frames = []
    for day, sig in zip(days, signature):
        if sig is None:
            continue
        raw = _read_day(store, asset, day, sig)
        if raw is not None and not getattr(raw, "empty", True):
            frames.append(raw)

    if not frames:
        empty = pd.DataFrame()
        return DayWindow(frame=empty, stamps=pd.Series(dtype="datetime64[ns, UTC]"),
                         signature=signature)

    frame = pd.concat(frames) if len(frames) > 1 else frames[0]
    stamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    return DayWindow(frame=frame, stamps=stamps, signature=signature)


def day_window(store: Any, asset: str, days: Sequence[datetime.date]) -> DayWindow:
    """The joined, stamp-parsed frame for ``days``, cached and revalidated.

    ``days`` is ordered and its order is preserved in the result, because the
    caller's nearest-snapshot search breaks ties positionally: reordering the
    window would silently change which of two equidistant snapshots is served.
    """
    days = tuple(days)
    key = (str(getattr(store, "base_dir", "")), asset, days)
    signature = _window_signature(store, asset, days)

    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            if hit.signature == signature:
                _CACHE.move_to_end(key)
                _STATS["hits"] += 1
                return hit
            # The partition changed under us (the intraday warmer appends
            # minutes as they publish). Counted separately from a cold miss so a
            # test can tell "never cached" from "cached and correctly dropped".
            _STATS["revalidations"] += 1
        else:
            _STATS["misses"] += 1

    # Built OUTSIDE the lock: reading a cold partition is I/O, and holding the
    # lock across it would serialise every other asset's lookups behind it.
    window = _build(store, asset, days, signature)

    with _LOCK:
        _CACHE[key] = window
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return window


def single_day(store: Any, asset: str, day: datetime.date) -> DayWindow:
    """One day. Shares the window cache, so an EOD and a minute read agree."""
    return day_window(store, asset, (day,))


def reset_day_cache() -> None:
    """Drop every cached window. For tests and for a long-lived daemon."""
    with _LOCK:
        _CACHE.clear()
        _DAY_FRAMES.clear()
        for k in _STATS:
            _STATS[k] = 0


def day_cache_stats() -> dict:
    """Hit/miss/revalidation counters.

    Exposed so a test can assert the number of *reads*, not the wall clock: a
    cache that looks fast because the filesystem is warm is indistinguishable
    from one that works, and this repo has been caught by exactly that.
    """
    with _LOCK:
        return dict(_STATS)
