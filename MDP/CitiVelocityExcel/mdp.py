r"""``CitiVelocityMDP`` - the market-data provider the Query and TB layers talk to.

Follows the repo's MDP contract: ``get_pricer(request)`` returns a pricer, and
``bulk_get_data(request)`` returns ``{timestamp: pricer}`` for many timestamps in
one fetch. The pricer is a :class:`~MDP.CitiVelocityExcel.pricer.CitiVeloPricer` -
a snapshot of Citi quotes that builds rateslib and QuantLib objects on demand.

Request schema
--------------
::

    {
      "timestamp":   date | datetime | "live",   # required
      "citi_index":  "USD_SOFR",                 # default curve for rate legs
      "currency":    "USD",                      # default currency for vol legs
      "freq":        "DAILY",
      "price_point": "CLOSE",
      "method":      "asof",
      "tags":        (...),                      # optional prefetch hints
    }

Bulk is where this source earns its keep. ``BaseTimeseriesTB`` prices every query
at every timestep through ``get_pricer``, which for Velocity would be pathological
- most queries *are* already a tag. :meth:`bulk_get_data` pulls the whole window
once and hands each timestep a pricer that shares the fetched frame, so N
reference points cost one ``CVTSHIST`` per tag chunk rather than N.
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

import pandas as pd

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.frequencies import normalise_frequency, normalise_price_point
from MDP.CitiVelocityExcel.pricer import CitiVeloPricer
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes, snapshot_from_frame
from MDP.CitiVelocityExcel.source import SOURCE_NAME
from MDP.MarketDataProvider import MarketDataProvider

__all__ = ["CitiVelocityMDP"]

_logger = logging.getLogger(__name__)


class CitiVelocityMDP(MarketDataProvider):
    """Market-data provider over the Citi Velocity Excel add-in.

    >>> mdp = CitiVelocityMDP()                                          # doctest: +SKIP
    >>> pricer = mdp.get_pricer({"timestamp": date(2026, 8, 4),          # doctest: +SKIP
    ...                          "citi_index": "USD_SOFR"})
    >>> pricer.quote("RATES.OIS.USD_SOFR.PAR.10Y")                       # doctest: +SKIP

    Parameters
    ----------
    source
        Kept for the base class's signature; the only meaningful value is
        ``citivelo_excel``. Registered under a NEW name so the existing
        ``CITIVELO``/``CITI_VELO``/``CITIVELOCITY`` aliases in ``IRSwapsMDP``
        keep their current semantics - the dealer-ladder study and 930 warmed
        CurveStore partitions depend on them.
    offline
        Never connect to Excel; serve only what the parquet cache holds. This is
        what makes a warm-cache backtest runnable without a signed-in add-in.
    """

    def __init__(
        self,
        source: str = SOURCE_NAME,
        *,
        quotes: Optional[CitiVeloQuotes] = None,
        cache: Optional[CitiVeloTagCache] = None,
        catalog: Optional[CitiVeloCatalog] = None,
        offline: bool = False,
        direct: bool = False,
        **kwargs: Any,
    ):
        super().__init__(source, **kwargs)
        self.catalog = catalog or CitiVeloCatalog.default()
        self._quotes = quotes or CitiVeloQuotes(cache=cache, catalog=self.catalog, offline=offline)
        self._direct = bool(direct)
        if self._direct and not self._quotes.is_direct:
            # A guard, not a nicety. `direct=True` is what makes every pricer
            # this provider hands out claim to be live; if the reader underneath
            # still has a tag cache, that claim is false and the caller has no
            # way to tell. Refuse rather than let the two disagree.
            raise CitiVelocityError(
                "CitiVelocityMDP(direct=True) requires a direct reader underneath. "
                "Build it with CitiVelocityMDP.direct_mdp() (or pass "
                "quotes=<existing>.direct_reader()) rather than constructing one with a "
                "cache-backed CitiVeloQuotes - otherwise a 'direct' pricer would serve "
                "cached values."
            )
        self._lock = threading.RLock()

    # -- lifecycle ------------------------------------------------------

    @property
    def quotes(self) -> CitiVeloQuotes:
        return self._quotes

    @property
    def direct(self) -> bool:
        """Whether every pricer from this provider reads straight from the add-in."""
        return self._direct

    def direct_mdp(self) -> "CitiVelocityMDP":
        """A sibling provider that bypasses the tag cache in both directions.

        Reads go to the add-in; nothing is written anywhere. The COM client is
        borrowed from this provider's reader, so no second Excel session is
        opened and closing the sibling does not close the shared client.

        >>> live = CitiVelocityMDP().direct_mdp()                    # doctest: +SKIP
        >>> live.get_pricer({"timestamp": "live"}).quote("RATES.OIS.USD_SOFR.PAR.10Y")
        """
        return CitiVelocityMDP(
            self.source,
            quotes=self._quotes.direct_reader(),
            catalog=self.catalog,
            direct=True,
        )

    def close(self) -> None:
        self._quotes.close()

    def __enter__(self) -> "CitiVelocityMDP":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- the MDP contract -----------------------------------------------

    def get_pricer(self, request: Mapping[str, Any]) -> CitiVeloPricer:
        """One snapshot at ``request['timestamp']``.

        Raises
        ------
        ValueError
            When ``timestamp`` is absent. There is no implicit "now": a Velocity
            snapshot with an unstated instant is the kind of ambiguity that
            silently prices a backtest against today's market.
        """
        req = dict(request)
        if "timestamp" not in req:
            raise ValueError(
                "CitiVelocityMDP request must contain 'timestamp' "
                "(a date, a datetime, or the literal 'live')."
            )
        timestamp = req.pop("timestamp")
        as_of = None if (isinstance(timestamp, str) and timestamp.lower() == "live") else timestamp

        return CitiVeloPricer(
            quotes=self._quotes,
            as_of=as_of,
            freq=normalise_frequency(req.get("freq", "DAILY")),
            price_point=normalise_price_point(req.get("price_point", "CLOSE")),
            method=str(req.get("method", "asof")),
            citi_index=req.get("citi_index") or req.get("curve_name"),
            currency=req.get("currency"),
            catalog=self.catalog,
            prefetch=tuple(req.get("tags") or ()),
            lookback=req.get("lookback"),
            direct=self._direct,
            preloaded=req.get("preloaded"),
        )

    def get_data(self, request: Mapping[str, Any]) -> CitiVeloPricer:
        """Deprecated alias, kept because parts of the repo still call it.

        Note this delegates to :meth:`get_pricer`, the opposite direction from
        ``IRSwapsMDP`` - which overrides ``get_data`` and has ``get_pricer`` call
        it. Both shapes exist in the repo; mixing them recurses forever, so this
        one is stated explicitly.
        """
        return self.get_pricer(request)

    def bulk_get_data(
        self, request: Mapping[str, Any]
    ) -> Dict[Union[datetime.date, datetime.datetime, str], CitiVeloPricer]:
        """``{timestamp: pricer}`` for many timestamps, with ONE window fetch.

        The prefetch hints in ``request['tags']`` are pulled across the whole
        span before any pricer is built, so every snapshot is served from the
        same warm cache. Timestamps with no row at or before them are ABSENT
        from the result rather than mapped to an empty pricer, matching
        ``IRSwapsMDP.bulk_get_data``.
        """
        req = dict(request)
        stamps: Sequence[Any] = req.pop("timestamps", None) or []
        if not stamps:
            raise ValueError("CitiVelocityMDP.bulk_get_data requires 'timestamps'.")

        freq = normalise_frequency(req.get("freq", "DAILY"))
        price_point = normalise_price_point(req.get("price_point", "CLOSE"))
        tags = tuple(req.get("tags") or ())

        concrete = [s for s in stamps if not (isinstance(s, str) and s.lower() == "live")]
        window: Optional[pd.DataFrame] = None
        if tags:
            start = min(pd.Timestamp(s) for s in concrete) if concrete else None
            end = max(pd.Timestamp(s) for s in concrete) if concrete else None
            if start is not None:
                start = start - _warm_lookback(freq)
            has_live = len(concrete) != len(stamps)
            if self._direct:
                # A direct reader has NO cache, so the sweep cannot work the way
                # it does below - "fetch the window and let each pricer find it
                # warm" has nowhere to leave the rows, and every timestep would
                # then go to the wire on its own: N CVTSHIST under the Excel lock
                # plus one discarded full-window fetch. So under direct the sweep
                # DELIVERS: one window read here, and each timestep is handed the
                # asof slice of it that it would otherwise have fetched.
                window = self._quotes.frame(
                    list(tags),
                    freq,
                    start=start,
                    end=None if has_live else end,
                    price_point=price_point,
                )
            else:
                self._quotes.series(
                    list(tags),
                    freq,
                    start=start,
                    end=None if has_live else end,
                    price_point=price_point,
                )

        method = str(req.get("method", "asof"))
        out: Dict[Any, CitiVeloPricer] = {}
        for stamp in stamps:
            sub = dict(req)
            sub["timestamp"] = stamp
            if self._direct and window is not None:
                # Same resolution rule the per-timestep pricer would have used,
                # so the delivered values are identical to the ones it would have
                # fetched - only fetched once.
                sub["tags"] = ()
                sub["preloaded"] = _asof_row(window, stamp, method=method)
            try:
                out[stamp] = self.get_pricer(sub)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("CitiVelocityMDP.bulk_get_data: %s failed (%s)", stamp, exc)
        return out

    # -- convenience ----------------------------------------------------

    def validate(self, tags: Sequence[str], **kwargs: Any) -> Dict[str, str]:
        """Validate tags through ``CVTSHIST`` with known-good controls in front."""
        return self._quotes.validate(list(tags), **kwargs)

    def metadata(self, tags: Sequence[str]) -> Dict[str, Any]:
        return self._quotes.metadata(list(tags))


def _asof_row(window: pd.DataFrame, stamp: Any, *, method: str) -> Dict[str, float]:
    """``{tag: value}`` for one instant out of an already-fetched window.

    Returns an EMPTY mapping when the window has no row for that instant rather
    than carrying a neighbouring one in: the pricer then asks for what it needs
    itself and, under a direct read, raises naming the tag. A silently carried
    value is the failure this whole path exists to avoid.
    """
    if window is None or window.empty:
        return {}
    when = None if (isinstance(stamp, str) and stamp.lower() == "live") else stamp
    try:
        row = snapshot_from_frame(window, when, method=method)
    except ValueError:
        return {}
    return {str(k): float(v) for k, v in row.items() if pd.notna(v)}


def _warm_lookback(freq: str) -> pd.Timedelta:
    """How far before the first reference point to warm, so ``asof`` can resolve.

    Without a lookback the first timestep of a window that starts on a Monday
    holiday has nothing at or before it, and the whole first row goes missing.
    """
    return pd.Timedelta(days=7 if freq in {"MI01", "MI10", "HOURLY"} else 45)
