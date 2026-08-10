r"""How much of a session the minute store actually holds.

"The day is present in the store" is not "one-minute data is available for that
day", and the gap between those two statements is where minute-resolution
research quietly stops being minute-resolution. Measured on the local store on
2026-08-09, ``USD-SOFR-1D-CITIVELOEXCELMIN`` held 1,233 days - of which 729 carry
at least 1,000 snapshots and 292 carry fewer than 200. On an 18-snapshot day
"the curve at t-1min" is not a request the data can answer, and until this module
existed the caller had no way to find that out short of reading the whole
partition (a 537 KB frame of 45-node curves, ~21 ms) for a number that is in the
file footer.

Two things are needed to answer "is this day dense enough", and a count alone is
only one of them: 240 snapshots evenly spread across a session and 240 that stop
at 11:58 ET are the same count and completely different answers. So the gap
profile and the session bounds are reported beside the count, and
:meth:`DayDensity.covers` asks the question a caller actually has - "was the feed
publishing at the minute I care about" - rather than the proxy.

Cost
----
``n_snapshots`` comes from the parquet **footer** (``metadata.num_rows``), which
reads kilobytes rather than the file. The gap profile needs one column of
timestamps - still far less than the curve payload, and cached per partition with
the same modification-time revalidation ``day_cache`` uses, because the intraday
warmer appends to today's partition while a long run is reading it.
"""
from __future__ import annotations

import dataclasses
import datetime
import os
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from MDP.IRSwaps.CITIVELO_EXCEL.day_cache import _partition_signature

__all__ = [
    "DayDensity",
    "day_density",
    "reset_density_cache",
    "DEFAULT_MIN_SNAPSHOTS",
    "DEFAULT_MAX_GAP",
]

#: A session with at least this many snapshots is treated as minute-resolution.
#: A full Citi session runs roughly 01:00-16:00 ET, so ~900 minutes; 800 leaves
#: room for a short Friday or an early stop without admitting the ten-minute era
#: (a ten-minute day tops out near 90).
DEFAULT_MIN_SNAPSHOTS = 800

#: And no gap inside it longer than this. The count alone cannot distinguish a
#: dense morning followed by a dead afternoon from an evenly covered day.
DEFAULT_MAX_GAP = datetime.timedelta(minutes=5)

_LOCK = threading.RLock()
_CACHE: "OrderedDict[Tuple[str, str, datetime.date], Tuple[Any, DayDensity]]" = OrderedDict()
_MAX_ENTRIES = 512


@dataclasses.dataclass(frozen=True)
class DayDensity:
    """What one stored session contains.

    ``first_utc``/``last_utc``/``max_gap_s`` are ``None`` when the density was
    taken with ``with_gaps=False``, which reads only the parquet footers. That is
    an absence of measurement, not a measurement of absence - ``is_dense`` says
    so by refusing to certify a day whose gap profile it has not seen.
    """

    asset: str
    local_date: datetime.date
    n_snapshots: int
    first_utc: Optional[pd.Timestamp] = None
    last_utc: Optional[pd.Timestamp] = None
    median_gap_s: Optional[float] = None
    max_gap_s: Optional[float] = None
    n_duplicate_stamps: Optional[int] = None

    @property
    def present(self) -> bool:
        return self.n_snapshots > 0

    def is_dense(
        self,
        *,
        min_snapshots: int = DEFAULT_MIN_SNAPSHOTS,
        max_gap: Optional[datetime.timedelta] = DEFAULT_MAX_GAP,
    ) -> bool:
        """Is minute-resolution work meaningful on this day?

        Returns ``False`` rather than raising when the gap profile was never
        measured and a gap bound was asked for. A helper that answered "dense"
        from a count it could not corroborate would be the same class of bug as
        the read path this module was written to support.
        """
        if self.n_snapshots < int(min_snapshots):
            return False
        if max_gap is None:
            return True
        if self.max_gap_s is None:
            return False
        return self.max_gap_s <= max_gap.total_seconds()

    def covers(self, instant: Any, *, tolerance: datetime.timedelta = DEFAULT_MAX_GAP) -> bool:
        """Was the feed publishing within ``tolerance`` before ``instant``?

        The honest form of the question. A day can be dense from 01:00 to 11:58
        and hold nothing at all for a 15:30 request, and no aggregate statistic
        about the day tells the 15:30 caller that.
        """
        if not self.present or self.first_utc is None or self.last_utc is None:
            return False
        ts = pd.Timestamp(instant)
        if ts.tzinfo is None:
            raise ValueError("covers() needs a tz-aware instant; a naive one has no meaning here")
        ts = ts.tz_convert("UTC")
        if ts < self.first_utc:
            return False
        return (ts - self.last_utc) <= tolerance if ts > self.last_utc else True


def _partition_files(store: Any, asset: str, day: datetime.date) -> List[str]:
    try:
        part_dir = store.raw_partition_dir(asset, day)
    except AttributeError:
        return []
    try:
        return [e.path for e in os.scandir(part_dir) if e.name.endswith(".parquet")]
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []


def _measure(store: Any, asset: str, day: datetime.date, with_gaps: bool) -> DayDensity:
    import pyarrow.parquet as pq

    files = _partition_files(store, asset, day)
    if not files:
        return DayDensity(asset=asset, local_date=day, n_snapshots=0)

    if not with_gaps:
        total = 0
        for path in files:
            total += pq.ParquetFile(path).metadata.num_rows
        return DayDensity(asset=asset, local_date=day, n_snapshots=int(total))

    chunks = []
    for path in files:
        table = pq.read_table(path, columns=["timestamp_utc"])
        chunks.append(table.column("timestamp_utc").to_pandas().to_numpy())
    stamps = pd.to_datetime(pd.Series(np.concatenate(chunks)), utc=True).sort_values()
    gaps = stamps.diff().dropna().dt.total_seconds()
    return DayDensity(
        asset=asset,
        local_date=day,
        n_snapshots=int(len(stamps)),
        first_utc=pd.Timestamp(stamps.iloc[0]),
        last_utc=pd.Timestamp(stamps.iloc[-1]),
        median_gap_s=float(gaps.median()) if len(gaps) else None,
        max_gap_s=float(gaps.max()) if len(gaps) else None,
        n_duplicate_stamps=int(len(stamps) - stamps.nunique()),
    )


def day_density(
    store: Any,
    asset: str,
    day: datetime.date,
    *,
    with_gaps: bool = True,
) -> DayDensity:
    """Density of one stored session, cached and revalidated against the files.

    Shares ``day_cache``'s partition signature - file names, sizes and
    modification times - so a partition the intraday warmer has appended to
    since the last look is re-measured rather than served from the cache. A
    cached density that trusted its first read would report a truncated session
    for the rest of a long run, and would do it silently.
    """
    key = (str(getattr(store, "base_dir", "")), asset, day)
    signature = (_partition_signature(store, asset, day), bool(with_gaps))
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == signature:
            _CACHE.move_to_end(key)
            return hit[1]

    result = _measure(store, asset, day, with_gaps)

    with _LOCK:
        _CACHE[key] = (signature, result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)
    return result


def reset_density_cache() -> None:
    with _LOCK:
        _CACHE.clear()
