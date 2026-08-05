"""Fetch a Citi Velocity OIS par grid and cut snapshots out of it.

``RATES.OIS.<index>.PAR.<tenor>`` is 44 tags per curve, and the add-in serves all
44 in one ``CVTSHIST`` call, so a par grid costs one round trip - which is why
:func:`fetch_par_grid` asks for the whole axis rather than looping tenors.

The one thing worth being careful about here is :func:`par_grid_snapshot`'s
``method``. It defaults to ``"asof"``, not ``"nearest"``: ``nearest`` is
direction-unbounded, and in this repo it was measured answering a 00:05 request
with a snapshot **55 minutes in the future**. A curve built from a future
snapshot is not wrong in any way a test notices - it is wrong in a way a
backtest notices, much later, as an implausibly good result.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.catalog import sort_tenors
from MDP.CitiVelocityExcel.curves.conventions import conventions_for
from MDP.CitiVelocityExcel.frequencies import normalise_frequency, normalise_price_point
from MDP.CitiVelocityExcel.tags import ois_par_grid

__all__ = [
    "SNAPSHOT_METHODS",
    "fetch_par_grid",
    "par_grid_snapshot",
    "tenor_columns_from_tags",
]

_logger = logging.getLogger(__name__)

DateLike = Union[datetime.date, datetime.datetime, pd.Timestamp, str]

#: Accepted values of :func:`par_grid_snapshot`'s ``method``. ``asof`` is the
#: default and the only one that cannot look forward in time.
SNAPSHOT_METHODS = ("nearest", "asof", "exact")


# ------------------------------------------------------------------ #
#                                tags                                #
# ------------------------------------------------------------------ #


def tenor_columns_from_tags(tags: Iterable[str]) -> List[str]:
    """The tenor tokens behind a set of ``...PAR.<tenor>`` tags, in tenor order.

    Parameters
    ----------
    tags
        Velocity tags, or bare tenor tokens (the last dotted segment is taken).

    Returns
    -------
    list[str]
        De-duplicated tenor tokens sorted by maturity, not lexically - ``"2W"``
        before ``"1M"``, ``"9Y"`` before ``"10Y"``.
    """
    seen: List[str] = []
    for tag in tags:
        token = str(tag).strip().split(".")[-1].upper()
        if token and token not in seen:
            seen.append(token)
    return sort_tenors(seen)


# ------------------------------------------------------------------ #
#                              fetching                              #
# ------------------------------------------------------------------ #


def fetch_par_grid(
    *,
    client: Any,
    citi_index: str,
    freq: str = "DAILY",
    period: Optional[str] = None,
    start: Optional[DateLike] = None,
    end: Optional[DateLike] = None,
    tenors: Optional[Sequence[str]] = None,
    cache: Optional[CitiVeloTagCache] = None,
    price_point: str = "CLOSE",
) -> pd.DataFrame:
    """One OIS curve's whole par grid as a time-indexed frame of percent rates.

    Parameters
    ----------
    client
        A :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient` (or
        the hermetic fake). May be ``None`` **only** when ``cache`` is supplied,
        in which case whatever is already on disk is served and nothing is
        fetched.
    citi_index
        Velocity OIS index token, e.g. ``"EUR_EUROSTR"``.
    freq
        ``CVTSHIST`` frequency: ``MI01 MI10 HOURLY DAILY WEEKLY MONTHLY``.
    period
        Relative window such as ``"5Y"``. Mutually exclusive with ``cache``: the
        cache reasons about absolute spans and cannot tell whether a relative
        window it already holds is still the same window.
    start, end
        Absolute bounds.
    tenors
        Restrict the axis. Defaults to the catalog's full 44-tenor axis.
    cache
        A :class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache`. When given,
        only the missing spans are fetched and the result is persisted.
    price_point
        ``CLOSE`` (default), ``OPEN``, ``HIGH``, ``LOW`` ...

    Returns
    -------
    pandas.DataFrame
        Index ``timestamp`` (ascending), columns the tenor tokens in maturity
        order, values **par rates in percent**. Tenors the add-in refused are
        absent from the columns and are logged, because ``CVTSHIST`` degrades
        per column and losing one tenor should not lose the grid.

    Raises
    ------
    ValueError
        ``client`` is ``None`` with no ``cache``; ``period`` combined with
        ``cache``; or the request returned nothing at all.
    """
    conv = conventions_for(citi_index)
    freq_token = normalise_frequency(freq)
    point_token = normalise_price_point(price_point)
    tags = ois_par_grid(conv.citi_index, tenors=tenors)

    if client is None and cache is None:
        raise ValueError(
            "fetch_par_grid: pass a client, a cache, or both. With neither there is nothing "
            "to read from."
        )
    if period is not None and cache is not None:
        raise ValueError(
            "fetch_par_grid: period= and cache= are mutually exclusive. The cache keys coverage "
            "on absolute timestamps and cannot tell whether a stored relative window still means "
            f"the same thing; pass start=/end= instead of period={period!r}."
        )

    if cache is None:
        series = client.fetch_timeseries(
            tags,
            freq_token,
            period=period,
            start=start,
            end=end,
            price_point=point_token,
        )
        failures = client.last_failures() if hasattr(client, "last_failures") else {}
    else:
        fetcher = None
        if client is not None:

            def fetcher(  # noqa: E306 - defined only when a client exists
                span_tags: Sequence[str],
                span_freq: str,
                span_start: Optional[datetime.datetime],
                span_end: Optional[datetime.datetime],
                span_point: str,
            ) -> Mapping[str, pd.Series]:
                return client.fetch_timeseries(
                    span_tags,
                    span_freq,
                    start=span_start,
                    end=span_end,
                    price_point=span_point,
                )

        series = cache.get(
            tags,
            freq_token,
            start=start,
            end=end,
            price_point=point_token,
            fetcher=fetcher,
        )
        failures = client.last_failures() if hasattr(client, "last_failures") else {}

    missing = [t for t in tags if t not in series]
    if missing:
        _logger.warning(
            "fetch_par_grid(%s): %d of %d tenor(s) returned no data (%s). CVTSHIST degrades per "
            "column, so the rest of the grid is intact.",
            conv.citi_index,
            len(missing),
            len(tags),
            ", ".join(f"{t.split('.')[-1]}={failures.get(t, 'no data')}" for t in missing[:10]),
        )
    if not series:
        raise ValueError(
            f"fetch_par_grid({conv.citi_index}): every one of the {len(tags)} PAR tags came back "
            "empty. Check the index token, the window, and that the add-in is signed in - an "
            "empty grid is never returned as a frame."
        )

    frame = pd.concat(series, axis=1).sort_index()
    frame.columns = [str(c).split(".")[-1].upper() for c in frame.columns]
    frame = frame[tenor_columns_from_tags(frame.columns)]
    frame.index.name = "timestamp"
    return frame.astype(float)


# ------------------------------------------------------------------ #
#                             snapshotting                           #
# ------------------------------------------------------------------ #


def par_grid_snapshot(
    frame: pd.DataFrame,
    when: Optional[DateLike] = None,
    *,
    method: str = "asof",
) -> pd.Series:
    """One row of a par grid, as ``{tenor: percent}`` ready for a curve builder.

    Parameters
    ----------
    frame
        The output of :func:`fetch_par_grid`.
    when
        The timestamp wanted. ``None`` takes the last row in the frame.
    method
        ``"asof"`` (default) takes the last row at or before ``when``.
        ``"exact"`` requires the timestamp to be present.
        ``"nearest"`` takes the closest row **in either direction** - it can and
        does return a row from the future. It was measured in this repo
        answering a 00:05 request with a snapshot 55 minutes ahead of it, which
        is why it is not the default and why it logs a warning whenever the row
        it picks is later than ``when``.

    Returns
    -------
    pandas.Series
        Indexed by tenor, values in percent, ``NaN`` entries dropped, and
        ``.name`` set to the timestamp actually used - so the caller can pass it
        straight to ``build_rl_ois_curve(par_rates=snap, ref_date=snap.name)``
        and know which row it got.

    Raises
    ------
    ValueError
        Empty frame, unknown ``method``, or no row satisfying the request.
    """
    token = str(method).strip().lower()
    if token not in SNAPSHOT_METHODS:
        raise ValueError(
            f"par_grid_snapshot: unknown method {method!r}. One of {', '.join(SNAPSHOT_METHODS)}."
        )
    if frame is None or frame.empty:
        raise ValueError("par_grid_snapshot: the frame is empty; there is no snapshot to take.")

    index = pd.DatetimeIndex(frame.index)
    if when is None:
        stamp = index[-1]
    else:
        target = pd.Timestamp(when)
        if index.tz is not None and target.tz is None:
            target = target.tz_localize(index.tz)
        elif index.tz is None and target.tz is not None:
            target = target.tz_convert(None).tz_localize(None)

        if token == "exact":
            if target not in index:
                raise ValueError(
                    f"par_grid_snapshot: no row at exactly {target}. The frame spans "
                    f"{index[0]} to {index[-1]}; pass method='asof' to take the last row at or "
                    "before it."
                )
            stamp = target
        elif token == "asof":
            eligible = index[index <= target]
            if len(eligible) == 0:
                raise ValueError(
                    f"par_grid_snapshot: no row at or before {target}; the frame starts at "
                    f"{index[0]}. Widen the fetch window rather than switching to 'nearest', "
                    "which would answer with a row from the future."
                )
            stamp = eligible[-1]
        else:  # nearest
            stamp = index[int(np.abs((index - target).to_numpy()).argmin())]
            if stamp > target:
                _logger.warning(
                    "par_grid_snapshot: method='nearest' picked %s, which is AFTER the requested "
                    "%s. That is look-ahead; use method='asof' unless you mean it.",
                    stamp,
                    target,
                )

    row = frame.loc[stamp]
    if isinstance(row, pd.DataFrame):  # duplicated timestamp in the frame
        row = row.iloc[-1]
    out = row.dropna().astype(float)
    out.name = stamp
    return out
