r"""Incremental parquet cache for Citi Velocity tag series.

Keyed ``(tag, freq, price_point)``, one parquet per key, under a
``reference_data_cache``-style dated-free tree::

    <base>/<FREQ>/<PRICE_POINT>/<sanitised-tag>.parquet
    <base>/<FREQ>/<PRICE_POINT>/<sanitised-tag>.meta.json

Reads serve what is cached and fetch only the missing head and/or tail; writes
merge, de-duplicate on timestamp (keep last) and sort ascending. Intraday and
daily are separate keys and are **never** mixed - a one-minute series and a daily
series of the same tag are different data, and collapsing them silently picks one
arbitrary minute per day.

The sidecar records ``history_start`` from ``CVMETADATA``, which is what lets the
cache know when it already holds everything the add-in has: without it, "give me
full history" would re-request the whole span on every call forever.

The cache root deliberately lives outside the repo. The one in-repo precedent
(``MDP/FixedRateBonds/reference_data_cache``) is not gitignored and produces
constant ``git status`` churn as its retention policy prunes dated directories;
16k bond tags would make that unbearable. Override with ``CITIVELO_EXCEL_CACHE_DIR``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import pathlib
import re
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from MDP.CitiVelocityExcel.frequencies import (
    DateLike,
    is_intraday,
    normalise_frequency,
    normalise_price_point,
)

__all__ = [
    "CitiVeloTagCache",
    "Coverage",
    "Fetcher",
    "default_cache_dir",
    "sanitise_tag",
]

_logger = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STEM = 120

#: ``fetcher(tags, freq, start, end, price_point) -> {tag: Series}``.
Fetcher = Callable[
    [Sequence[str], str, Optional[datetime.datetime], Optional[datetime.datetime], str],
    Mapping[str, pd.Series],
]


def default_cache_dir() -> pathlib.Path:
    """Resolve the cache root, mirroring the repo's cache-root ladder."""
    explicit = os.environ.get("CITIVELO_EXCEL_CACHE_DIR")
    if explicit:
        return pathlib.Path(explicit)
    arbs = os.environ.get("ARBS_CACHE_DIR")
    if arbs:
        return pathlib.Path(arbs) / "citivelo_excel"
    try:
        import platformdirs  # type: ignore

        return pathlib.Path(platformdirs.user_cache_dir(appname="ARBS")) / "citivelo_excel"
    except ImportError:
        pass
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return pathlib.Path(local) / "ARBS" / "Cache" / "citivelo_excel"
    return pathlib.Path.home() / ".cache" / "arbs" / "citivelo_excel"


def sanitise_tag(tag: str) -> str:
    """A filesystem-safe stem for a tag, stable and collision-resistant.

    Velocity tags are dot-separated ASCII, so the sanitiser almost never fires;
    the length cap exists because a seven-segment ``XCCY_OIS_SWAP`` tag under a
    deep cache root can approach Windows' 260-character path limit.
    """
    stem = _SAFE_RE.sub("_", str(tag).strip())
    if len(stem) <= _MAX_STEM:
        return stem
    digest = hashlib.sha1(str(tag).encode("utf-8")).hexdigest()[:12]
    return f"{stem[: _MAX_STEM - 13]}__{digest}"


@dataclass(frozen=True)
class Coverage:
    """What the cache holds for one key."""

    tag: str
    freq: str
    price_point: str
    first: Optional[pd.Timestamp]
    last: Optional[pd.Timestamp]
    n_rows: int
    history_start: Optional[pd.Timestamp]
    fetched_at: Optional[datetime.datetime]

    @property
    def complete_back(self) -> bool:
        """True when the cache reaches the tag's own start of history."""
        if self.history_start is None or self.first is None:
            return False
        return self.first <= self.history_start + pd.Timedelta(days=1)


class CitiVeloTagCache:
    """Serve cached rows, fetch only the missing span, merge and persist.

    >>> cache = CitiVeloTagCache(base_dir=tmp)                       # doctest: +SKIP
    >>> series = cache.get(                                          # doctest: +SKIP
    ...     ["RATES.OIS.USD_SOFR.PAR.10Y"], "DAILY",
    ...     start=date(2024, 1, 1), end=date(2024, 6, 30),
    ...     fetcher=client_fetcher,
    ... )
    """

    def __init__(self, base_dir: Optional[pathlib.Path] = None):
        self.base_dir = pathlib.Path(base_dir) if base_dir is not None else default_cache_dir()
        self._lock = threading.RLock()

    # -- paths ----------------------------------------------------------

    def _dir(self, freq: str, price_point: str) -> pathlib.Path:
        return self.base_dir / normalise_frequency(freq) / normalise_price_point(price_point)

    def path(self, tag: str, freq: str, price_point: str = "CLOSE") -> pathlib.Path:
        return self._dir(freq, price_point) / f"{sanitise_tag(tag)}.parquet"

    def meta_path(self, tag: str, freq: str, price_point: str = "CLOSE") -> pathlib.Path:
        return self._dir(freq, price_point) / f"{sanitise_tag(tag)}.meta.json"

    # -- read -----------------------------------------------------------

    #: How many parsed series to keep in memory. A bond needs about a dozen tags
    #: and a warm walks bonds one at a time, so even a small window hits almost
    #: always; the bound exists so a 900-bond run cannot grow without limit.
    _PARSE_MEMO_MAX = 256

    def read(self, tag: str, freq: str, price_point: str = "CLOSE") -> Optional[pd.Series]:
        """The whole cached series for one key, or ``None`` when absent.

        The parquet PARSE is memoised on ``(path, mtime, size)``
        -------------------------------------------------------
        Reading a whole tag file to answer one date is the shape of this cache -
        it stores series, not points - and it is fine until something asks per
        date. Profiled on a forty-date offline pricer loop, this path was **24%
        of runtime**: 400 reads of ten files, each re-parsing the parquet,
        de-duplicating and sorting.

        Keyed on the file's identity AND its stat, so a tag that is rewritten
        mid-process - which happens, ``get`` writes through here - produces a
        different key and is re-read. A memo keyed on the path alone would serve
        a stale series to the very run that had just extended it.

        The arrays are cached; the ``Series`` is rebuilt per call. Sharing one
        Series would let any caller's in-place edit reach every later reader,
        and pandas gives no cheap way to forbid that. Rebuilding costs
        microseconds against the milliseconds the parse costs.
        """
        path = self.path(tag, freq, price_point)
        try:
            st = path.stat()
        except OSError:
            return None
        key = (str(path), st.st_mtime_ns, st.st_size)
        memo = getattr(self, "_parse_memo", None)
        if memo is None:
            memo = {}
            self._parse_memo = memo  # type: ignore[attr-defined]
        hit = memo.get(key)
        if hit is None:
            try:
                table = pq.read_table(path)
            except Exception as exc:  # noqa: BLE001
                # A corrupt parquet must not look like a cache miss that silently
                # refetches forever - say so, then treat it as a miss once.
                _logger.warning("CitiVeloTagCache: unreadable cache file %s (%s); refetching.", path, exc)
                return None
            df = table.to_pandas()
            if df.empty or "timestamp" not in df.columns or "value" not in df.columns:
                return None
            idx = pd.DatetimeIndex(pd.to_datetime(df["timestamp"]), name="Date")
            s = pd.Series(df["value"].astype("float64").to_numpy(), index=idx, name=str(tag))
            s = s[~s.index.duplicated(keep="last")].sort_index()
            hit = (s.index, s.to_numpy())
            if len(memo) >= self._PARSE_MEMO_MAX:
                memo.pop(next(iter(memo)), None)
            memo[key] = hit
        index, values = hit
        # copy=True, and it is not optional. With copy=False the Series wraps the
        # cached array itself, so ``s.iloc[0] = x`` in any caller rewrites the memo
        # for every later reader - caught by
        # test_the_memo_does_not_hand_out_a_shared_mutable_series. The index is
        # shared deliberately: a DatetimeIndex is immutable, and it is the larger
        # of the two. Copying ~2,500 float64 is 20 KB against a parquet parse.
        return pd.Series(values, index=index, name=str(tag), copy=True)

    def coverage(self, tag: str, freq: str, price_point: str = "CLOSE") -> Optional[Coverage]:
        """What is cached for one key, including the tag's own history start."""
        s = self.read(tag, freq, price_point)
        meta = self._read_meta(tag, freq, price_point)
        if s is None and not meta:
            return None
        hist = meta.get("history_start")
        fetched = meta.get("fetched_at")
        return Coverage(
            tag=str(tag),
            freq=normalise_frequency(freq),
            price_point=normalise_price_point(price_point),
            first=(None if s is None or s.empty else s.index.min()),
            last=(None if s is None or s.empty else s.index.max()),
            n_rows=(0 if s is None else int(s.size)),
            history_start=(pd.Timestamp(hist) if hist else None),
            fetched_at=(datetime.datetime.fromisoformat(fetched) if fetched else None),
        )

    def _read_meta(self, tag: str, freq: str, price_point: str) -> Dict[str, object]:
        path = self.meta_path(tag, freq, price_point)
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    # -- write ----------------------------------------------------------

    @staticmethod
    def merge(existing: Optional[pd.Series], incoming: pd.Series) -> pd.Series:
        """Merge two series: union of timestamps, incoming wins on collision.

        Incoming wins because a re-fetch of an overlapping span is how a revised
        value reaches us; keeping the older one would pin a stale print forever.
        """
        incoming = incoming[~incoming.index.duplicated(keep="last")].sort_index()
        if existing is None or existing.empty:
            return incoming.astype("float64")
        combined = pd.concat([existing, incoming])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        return combined.astype("float64")

    def write(
        self,
        tag: str,
        freq: str,
        series: pd.Series,
        *,
        price_point: str = "CLOSE",
        history_start: Optional[DateLike] = None,
    ) -> pd.Series:
        """Merge ``series`` into the cache and return the merged result."""
        freq_token = normalise_frequency(freq)
        point_token = normalise_price_point(price_point)
        with self._lock:
            existing = self.read(tag, freq_token, point_token)
            merged = self.merge(existing, series)

            path = self.path(tag, freq_token, point_token)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Nanosecond resolution, not microsecond: pandas' default DatetimeIndex
            # is datetime64[ns], and writing microseconds makes a cache round trip
            # silently change the index dtype. Mixed-resolution indices compare
            # correctly but concatenate to object in some pandas paths, and a
            # dtype that depends on whether a value came from cache or from Excel
            # is exactly the kind of difference that shows up three layers away.
            table = pa.table(
                {
                    "timestamp": pa.array(
                        merged.index.to_numpy(dtype="datetime64[ns]"), type=pa.timestamp("ns")
                    ),
                    "value": pa.array(merged.to_numpy(), type=pa.float64()),
                }
            )
            tmp = path.with_suffix(".parquet.tmp")
            pq.write_table(table, tmp, compression="zstd")
            os.replace(tmp, path)

            meta = self._read_meta(tag, freq_token, point_token)
            meta["tag"] = str(tag)
            meta["freq"] = freq_token
            meta["price_point"] = point_token
            meta["intraday"] = is_intraday(freq_token)
            meta["fetched_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            meta["n_rows"] = int(merged.size)
            if not merged.empty:
                meta["first"] = merged.index.min().isoformat()
                meta["last"] = merged.index.max().isoformat()
            if history_start is not None:
                meta["history_start"] = pd.Timestamp(history_start).isoformat()
            meta_tmp = self.meta_path(tag, freq_token, point_token).with_suffix(".json.tmp")
            meta_tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
            os.replace(meta_tmp, self.meta_path(tag, freq_token, point_token))
        return merged

    def set_history_start(
        self, tag: str, freq: str, history_start: DateLike, *, price_point: str = "CLOSE"
    ) -> None:
        """Record the tag's own start of history, from ``CVMETADATA``."""
        freq_token = normalise_frequency(freq)
        point_token = normalise_price_point(price_point)
        with self._lock:
            meta = self._read_meta(tag, freq_token, point_token)
            meta["history_start"] = pd.Timestamp(history_start).isoformat()
            path = self.meta_path(tag, freq_token, point_token)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(meta, indent=1), encoding="utf-8")
            os.replace(tmp, path)

    # -- incremental fetch ----------------------------------------------

    def missing_spans(
        self,
        tag: str,
        freq: str,
        *,
        start: Optional[DateLike],
        end: Optional[DateLike],
        price_point: str = "CLOSE",
        max_staleness: Optional[datetime.timedelta] = None,
    ) -> List[Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]]:
        """Spans that are NOT cached for a request, as ``[(start, end), ...]``.

        ``start=None`` means "back to the beginning of history": that head is
        considered covered once the cache reaches the tag's recorded
        ``history_start``. ``end=None`` means "up to now": that tail is always
        re-requested unless ``max_staleness`` says the last fetch is recent enough.
        """
        cov = self.coverage(tag, freq, price_point)
        want_start = None if start is None else pd.Timestamp(start)
        want_end = None if end is None else pd.Timestamp(end)

        if cov is None or cov.first is None or cov.last is None or cov.n_rows == 0:
            return [(want_start, want_end)]

        spans: List[Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]] = []

        if want_start is None:
            if not cov.complete_back:
                spans.append((None, cov.first))
        elif want_start < cov.first:
            spans.append((want_start, cov.first))

        if want_end is None:
            fresh = (
                max_staleness is not None
                and cov.fetched_at is not None
                and datetime.datetime.now() - cov.fetched_at <= max_staleness
            )
            if not fresh:
                spans.append((cov.last, None))
        elif want_end > cov.last:
            spans.append((cov.last, want_end))

        return spans

    def get(
        self,
        tags: Sequence[str],
        freq: str = "DAILY",
        *,
        start: Optional[DateLike] = None,
        end: Optional[DateLike] = None,
        price_point: str = "CLOSE",
        fetcher: Optional[Fetcher] = None,
        force_refresh: bool = False,
        max_staleness: Optional[datetime.timedelta] = None,
        history_starts: Optional[Mapping[str, DateLike]] = None,
    ) -> Dict[str, pd.Series]:
        """Cached-then-live read for many tags.

        Tags whose missing spans coincide are fetched in ONE call, so a 44-tenor
        par grid with a cold cache costs one ``CVTSHIST`` rather than 44.
        """
        freq_token = normalise_frequency(freq)
        point_token = normalise_price_point(price_point)
        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        if not wanted:
            return {}

        if history_starts:
            for tag, hs in history_starts.items():
                if hs is not None:
                    self.set_history_start(tag, freq_token, hs, price_point=point_token)

        # Group tags by the span they still need, so one call serves many tags.
        by_span: Dict[Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]], List[str]] = {}
        for tag in wanted:
            if force_refresh:
                spans = [(None if start is None else pd.Timestamp(start), None if end is None else pd.Timestamp(end))]
            else:
                spans = self.missing_spans(
                    tag,
                    freq_token,
                    start=start,
                    end=end,
                    price_point=point_token,
                    max_staleness=max_staleness,
                )
            for span in spans:
                by_span.setdefault(span, []).append(tag)

        if by_span and fetcher is None:
            _logger.debug(
                "CitiVeloTagCache.get: %d span(s) are not cached and no fetcher was supplied; "
                "serving what is on disk.",
                len(by_span),
            )
        elif fetcher is not None:
            for (span_start, span_end), span_tags in by_span.items():
                fetched = fetcher(
                    span_tags,
                    freq_token,
                    None if span_start is None else span_start.to_pydatetime(),
                    None if span_end is None else span_end.to_pydatetime(),
                    point_token,
                )
                for tag, series in (fetched or {}).items():
                    if series is None or len(series) == 0:
                        continue
                    self.write(tag, freq_token, series, price_point=point_token)

        out: Dict[str, pd.Series] = {}
        for tag in wanted:
            s = self.read(tag, freq_token, point_token)
            if s is None or s.empty:
                continue
            if start is not None:
                s = s[s.index >= pd.Timestamp(start)]
            if end is not None:
                s = s[s.index <= pd.Timestamp(end)]
            if not s.empty:
                out[tag] = s
        return out

    # -- housekeeping ---------------------------------------------------

    def keys(self) -> List[Tuple[str, str, str]]:
        """Every ``(freq, price_point, stem)`` currently on disk."""
        out: List[Tuple[str, str, str]] = []
        if not self.base_dir.is_dir():
            return out
        for freq_dir in sorted(self.base_dir.iterdir()):
            if not freq_dir.is_dir():
                continue
            for point_dir in sorted(freq_dir.iterdir()):
                if not point_dir.is_dir():
                    continue
                for parquet in sorted(point_dir.glob("*.parquet")):
                    out.append((freq_dir.name, point_dir.name, parquet.stem))
        return out

    def size_bytes(self) -> int:
        if not self.base_dir.is_dir():
            return 0
        return sum(p.stat().st_size for p in self.base_dir.rglob("*.parquet"))
