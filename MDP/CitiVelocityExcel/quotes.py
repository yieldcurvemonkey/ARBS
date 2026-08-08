r"""Cached-then-live tag reader: the seam between the COM bridge and everything else.

Every analytics layer in this package takes plain pandas objects, so this is the
only place that knows how a tag becomes a series. That is deliberate: the curve,
cube and bond builders are then testable with no Excel, no cache and no network.

Two properties matter for how the rest of the package is shaped:

* **A fully-cached read never touches Excel.** The client is constructed lazily,
  on the first request that actually needs live data. A notebook re-running a
  backtest over a warm cache neither opens a workbook nor requires the user to be
  signed in.
* **Tags are batched across the whole request.** A 44-tenor par grid, a
  7x5 vol slice and a bond yield asked for in one call go out as few ``CVTSHIST``
  calls as the chunk size allows, not one call per tag.
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence

import pandas as pd

from MDP.CitiVelocityExcel.block_parser import MetadataRow
from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.frequencies import DateLike, normalise_frequency, normalise_price_point

__all__ = ["CitiVeloQuotes", "snapshot_from_frame"]

_logger = logging.getLogger(__name__)


def snapshot_from_frame(
    frame: pd.DataFrame,
    when: Optional[DateLike] = None,
    *,
    method: str = "asof",
) -> pd.Series:
    """One row of a time-indexed frame, resolved by ``nearest`` | ``asof`` | ``exact``.

    The default is ``asof`` (backward-only), matching every other intraday source
    in this repo. ``nearest`` is direction-unbounded: on the sibling ``citivelo``
    source it was measured answering a 00:05-00:55 ET request with a snapshot up
    to 55 minutes in the FUTURE, because the feed's first row of the day is 01:00 ET.

    Raises
    ------
    ValueError
        When the frame is empty, or ``method='exact'`` and there is no such row.
    """
    if frame is None or frame.empty:
        raise ValueError("snapshot_from_frame: the frame is empty.")
    idx = frame.index
    if when is None:
        return frame.iloc[-1]
    target = pd.Timestamp(when)
    if method == "exact":
        if target not in idx:
            raise ValueError(f"No row at exactly {target}; use method='asof' or 'nearest'.")
        return frame.loc[target]
    if method == "asof":
        prior = idx[idx <= target]
        if len(prior) == 0:
            raise ValueError(
                f"No row at or before {target} (earliest is {idx.min()}). "
                "Widen the window, or use method='nearest' knowingly."
            )
        return frame.loc[prior.max()]
    if method == "nearest":
        pos = int((idx.to_series() - target).abs().values.argmin())
        return frame.iloc[pos]
    raise ValueError(f"Unknown method {method!r}; use nearest | asof | exact.")


class CitiVeloQuotes:
    """Reads Velocity tags through the cache, hitting Excel only for what is missing.

    >>> quotes = CitiVeloQuotes()                                    # doctest: +SKIP
    >>> frame = quotes.frame(tags.ois_par_grid("USD_SOFR"), "DAILY",  # doctest: +SKIP
    ...                      start=date(2024, 1, 1))
    >>> quotes.close()                                               # doctest: +SKIP

    Parameters
    ----------
    client
        A live :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient`.
        Left ``None``, one is connected lazily the first time live data is needed.
    cache
        A :class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache`. Pass
        ``cache=False`` to bypass the cache entirely.
    offline
        Refuse to connect to Excel. Requests are served from the cache and
        anything missing is simply absent - useful in tests and on a machine with
        no add-in.
    """

    def __init__(
        self,
        *,
        client: Optional[CitiVelocityExcelClient] = None,
        cache: Optional[CitiVeloTagCache] | bool = None,
        catalog: Optional[CitiVeloCatalog] = None,
        offline: bool = False,
        max_staleness: Optional[datetime.timedelta] = None,
        client_kwargs: Optional[Mapping[str, Any]] = None,
    ):
        self._client = client
        self._owns_client = client is None
        self._cache = None if cache is False else (cache or CitiVeloTagCache())
        self._catalog = catalog or CitiVeloCatalog.default()
        self._offline = bool(offline)
        self._max_staleness = max_staleness
        self._client_kwargs = dict(client_kwargs or {})
        self._lock = threading.RLock()

    # -- lifecycle ------------------------------------------------------

    @property
    def catalog(self) -> CitiVeloCatalog:
        return self._catalog

    @property
    def cache(self) -> Optional[CitiVeloTagCache]:
        return self._cache

    @property
    def offline(self) -> bool:
        """Whether this reader refuses to connect to Excel.

        Public because a caller that was handed a reader has to be able to ask:
        ``offline`` also selects the TRANSPORT in the bond fetcher (a clamped
        cache read versus the windowed chunker, which needs a live client), and a
        component that guessed wrong called ``client()`` inside what its caller
        believed was an offline path.
        """
        return self._offline

    def client(self) -> CitiVelocityExcelClient:
        """The live client, connecting on first use.

        Raises
        ------
        CitiVelocityError
            When ``offline=True``. The message names the cache root, because the
            usual cause is a cold cache rather than a missing add-in.
        """
        if self._offline:
            root = self._cache.base_dir if self._cache is not None else "(no cache)"
            raise CitiVelocityError(
                f"CitiVeloQuotes is offline and the request is not fully cached (cache root: {root}). "
                "Pass offline=False with a signed-in Excel, or narrow the request to cached tags."
            )
        with self._lock:
            if self._client is None:
                self._client = CitiVelocityExcelClient.connect(**self._client_kwargs)
                self._owns_client = True
            return self._client

    def close(self) -> None:
        with self._lock:
            if self._client is not None and self._owns_client:
                self._client.close()
            self._client = None

    def __enter__(self) -> "CitiVeloQuotes":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- reads ----------------------------------------------------------

    def _fetcher(self, *, period: Optional[str], failures: Optional[MutableMapping[str, str]] = None):
        def fetch(tags, freq, start, end, price_point):
            client = self.client()
            got = client.fetch_timeseries(
                list(tags),
                freq,
                period=period if (start is None and end is None) else None,
                start=start,
                end=end,
                price_point=price_point,
            )
            if failures is not None:
                # Scoped to the call that just happened, not to the client's
                # lifetime: last_failures() is per fetch_timeseries, and reading it
                # outside this closure would attribute a previous request's
                # rejected tag to a fully-cached read that never went to the wire.
                failures.update(client.last_failures())
            return got

        return fetch

    def series(
        self,
        tags: Sequence[str],
        freq: str = "DAILY",
        *,
        start: Optional[DateLike] = None,
        end: Optional[DateLike] = None,
        period: Optional[str] = None,
        price_point: str = "CLOSE",
        force_refresh: bool = False,
        failures: Optional[MutableMapping[str, str]] = None,
        max_staleness: Optional[datetime.timedelta] = None,
    ) -> Dict[str, pd.Series]:
        """One ascending series per tag that returned data.

        Tags that failed are ABSENT rather than NaN-filled, and the reason is on
        the client's :meth:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient.last_failures`.

        Pass ``failures`` - any mutable mapping - to have those reasons handed back
        for THIS call, keyed by tag. Nothing is written to it when the request was
        served entirely from the cache, because no fetch happened and the client's
        record belongs to some earlier one. Note that the reason ``"empty"`` means
        the column came back with no rows in the window: the add-in distinguishes
        "no such tag" from "no rows here" and so does this.

        ``max_staleness`` overrides the reader's own setting for THIS call. It
        exists because the gate belongs to the DATA, not to whoever happens to own
        the reader: an overnight fixing is worth re-requesting twice a day at most,
        and a caller handed someone else's ``CitiVeloQuotes`` (the swaption cube
        provider hands its own to the fixings resolver) would otherwise inherit
        ``None`` and re-request an unbounded tail on every single call.
        """
        freq_token = normalise_frequency(freq)
        point_token = normalise_price_point(price_point)
        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        if not wanted:
            return {}

        if self._cache is None:
            client = self.client()
            got = dict(
                client.fetch_timeseries(
                    wanted,
                    freq_token,
                    period=period,
                    start=start,
                    end=end,
                    price_point=point_token,
                )
            )
            if failures is not None:
                failures.update(client.last_failures())
            return got

        fetcher = None if self._offline else self._fetcher(period=period, failures=failures)
        return self._cache.get(
            wanted,
            freq_token,
            start=start,
            end=end,
            price_point=point_token,
            fetcher=fetcher,
            force_refresh=force_refresh,
            max_staleness=self._max_staleness if max_staleness is None else max_staleness,
        )

    def frame(
        self,
        tags: Sequence[str],
        freq: str = "DAILY",
        **kwargs: Any,
    ) -> pd.DataFrame:
        """:meth:`series` as one wide, time-indexed frame, columns in tag order.

        Takes the same keywords, including ``failures``: a tag that failed is
        simply an absent COLUMN here, which is indistinguishable from a tag that
        returned no rows unless the reasons are asked for.
        """
        series = self.series(tags, freq, **kwargs)
        if not series:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
        ordered = [t for t in dict.fromkeys(tags) if t in series]
        frame = pd.concat({t: series[t] for t in ordered}, axis=1)
        frame = frame[ordered]
        frame.index.name = "Date"
        return frame.sort_index()

    def snapshot(
        self,
        tags: Sequence[str],
        when: Optional[DateLike] = None,
        freq: str = "DAILY",
        *,
        method: str = "asof",
        lookback: Optional[datetime.timedelta] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """``{tag: value}`` at one instant, resolved by ``method``.

        ``lookback`` bounds how far back the window is fetched; the default of 30
        days for daily data and 5 days for intraday keeps a point request from
        pulling a full history on a cold cache.
        """
        freq_token = normalise_frequency(freq)
        if lookback is None:
            lookback = datetime.timedelta(days=5 if freq_token in {"MI01", "MI10", "HOURLY"} else 30)
        end = None if when is None else pd.Timestamp(when)
        start = None if end is None else end - lookback
        frame = self.frame(tags, freq_token, start=start, end=end, **kwargs)
        if frame.empty:
            return {}
        row = snapshot_from_frame(frame, when, method=method)
        return {str(k): float(v) for k, v in row.items() if pd.notna(v)}

    # -- pass-throughs --------------------------------------------------

    def metadata(self, tags: Sequence[str]) -> Dict[str, MetadataRow]:
        """``CVMETADATA`` per tag: description and history bounds.

        The history start is written into the cache sidecar, which is what lets a
        "full history" request know it already holds everything.
        """
        rows = self.client().metadata(list(tags))
        if self._cache is not None:
            for tag, row in rows.items():
                if row.history_start is not None:
                    for freq in ("DAILY", "MI01"):
                        self._cache.set_history_start(tag, freq, row.history_start)
        return rows

    def latest(self, tags: Sequence[str]) -> Dict[str, Any]:
        return self.client().latest(list(tags))

    def validate(self, tags: Sequence[str], **kwargs: Any) -> Dict[str, str]:
        """Validate through ``CVTSHIST`` with known-good controls in front."""
        return self.client().validate_with_controls(list(tags), **kwargs)

    def curve_bond(self, curve_tag: str) -> pd.DataFrame:
        return self.client().curve_bond(curve_tag)

    def curve(self, curve_tag: str) -> pd.DataFrame:
        return self.client().curve(curve_tag)
