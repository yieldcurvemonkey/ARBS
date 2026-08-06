r"""The ``citivelo_excel`` MDP source: arbitrary Velocity series, cached then live.

This is the *timeseries* face of Citi Velocity - hand it tags, get frames back. It
is deliberately distinct from the existing ``citivelo`` source in
``MDP/IRSwaps/IRSwapsMDP.py``: that one builds a rateslib USD-SOFR curve from a
hand-saved 365 MB workbook, is pinned by 930 warmed CurveStore partitions and by
the dealer-ladder study, and is not changed by anything in this package.

Request schema
--------------
``get_data`` and ``bulk_get_data`` take one dict::

    {
      "tags":        ["RATES.OIS.USD_SOFR.PAR.10Y", ...],   # or "tag": "..."
      "freq":        "DAILY",                                # default DAILY
      "start":       date | datetime | None,
      "end":         date | datetime | None,
      "period":      "5Y" | None,                            # relative window
      "price_point": "CLOSE",
      "timestamp":   date | datetime | "live" | None,        # single-point form
      "method":      "asof",                                 # for the single-point form
      "force_refresh": False,
    }

``timestamp`` selects the single-point form and returns ``{tag: value}``;
otherwise a wide frame is returned. ``bulk_get_data`` takes ``timestamps`` (plural)
and returns ``{timestamp: {tag: value}}``, which is the shape
``TB.BaseTimeseriesTB._bulk_fetch`` expects.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import pandas as pd

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache
from MDP.CitiVelocityExcel.frequencies import DateLike, normalise_frequency, normalise_price_point
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes, snapshot_from_frame

__all__ = ["CitiVelocityExcelSource", "SOURCE_NAME"]

_logger = logging.getLogger(__name__)

#: The MDP source string. Registered under a NEW name so the existing
#: ``CITIVELO`` / ``CITI_VELO`` / ``CITIVELOCITY`` aliases keep their current
#: semantics - the dealer-ladder study and 930 warmed partitions depend on them.
SOURCE_NAME = "citivelo_excel"


class CitiVelocityExcelSource:
    """Fetch arbitrary Citi Velocity series through the repo's MDP dispatch shape.

    >>> src = CitiVelocityExcelSource()                              # doctest: +SKIP
    >>> frame = src.get_data({"tags": tags.ois_par_grid("USD_SOFR"), # doctest: +SKIP
    ...                       "freq": "DAILY", "period": "1Y"})
    """

    source = SOURCE_NAME

    def __init__(
        self,
        *,
        quotes: Optional[CitiVeloQuotes] = None,
        cache: Optional[CitiVeloTagCache] = None,
        offline: bool = False,
        **client_kwargs: Any,
    ):
        self._quotes = quotes or CitiVeloQuotes(
            cache=cache, offline=offline, client_kwargs=client_kwargs or None
        )

    # -- helpers --------------------------------------------------------

    @property
    def quotes(self) -> CitiVeloQuotes:
        return self._quotes

    def close(self) -> None:
        self._quotes.close()

    @staticmethod
    def _tags(request: Mapping[str, Any]) -> List[str]:
        raw = request.get("tags")
        if raw is None:
            raw = request.get("tag")
        if raw is None:
            raise ValueError(
                "CitiVelocityExcelSource request must contain 'tags' (a sequence) or 'tag' (one string)."
            )
        if isinstance(raw, str):
            raw = [raw]
        out = [str(t).strip() for t in raw if str(t).strip()]
        if not out:
            raise ValueError("CitiVelocityExcelSource request contained no usable tags.")
        return out

    @staticmethod
    def _window(request: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "start": request.get("start"),
            "end": request.get("end"),
            "period": request.get("period"),
            "price_point": normalise_price_point(request.get("price_point", "CLOSE")),
            "force_refresh": bool(request.get("force_refresh", False)),
        }

    # -- the MDP surface ------------------------------------------------

    def get_data(self, request: Mapping[str, Any]) -> Union[pd.DataFrame, Dict[str, float]]:
        """A frame over the requested window, or ``{tag: value}`` at one instant."""
        req = dict(request)
        tags = self._tags(req)
        freq = normalise_frequency(req.get("freq", "DAILY"))
        window = self._window(req)
        timestamp = req.get("timestamp")

        if timestamp is None:
            return self._quotes.frame(tags, freq, **window)

        if isinstance(timestamp, str) and timestamp.lower() == "live":
            frame = self._quotes.frame(tags, freq, **window)
            if frame.empty:
                return {}
            row = frame.iloc[-1]
            return {str(k): float(v) for k, v in row.items() if pd.notna(v)}

        method = str(req.get("method", "asof"))
        return self._quotes.snapshot(
            tags,
            timestamp,
            freq,
            method=method,
            price_point=window["price_point"],
            force_refresh=window["force_refresh"],
        )

    def get_pricer(self, request: Mapping[str, Any]) -> Union[pd.DataFrame, Dict[str, float]]:
        """Alias for :meth:`get_data`, for callers that speak the MDP protocol."""
        return self.get_data(request)

    def bulk_get_data(
        self, request: Mapping[str, Any]
    ) -> Dict[Union[datetime.date, datetime.datetime, str], Dict[str, float]]:
        """``{timestamp: {tag: value}}`` for many timestamps in ONE fetch.

        The whole window is pulled once and then sliced per timestamp, so N
        reference points cost one ``CVTSHIST`` per tag chunk rather than N. Points
        with no row at or before them are ABSENT from the result rather than
        present-and-empty, matching ``IRSwapsMDP.bulk_get_data``.
        """
        req = dict(request)
        tags = self._tags(req)
        freq = normalise_frequency(req.get("freq", "DAILY"))
        stamps: Sequence[Any] = req.get("timestamps") or []
        if not stamps:
            raise ValueError("CitiVelocityExcelSource.bulk_get_data requires 'timestamps'.")
        method = str(req.get("method", "asof"))
        window = self._window(req)

        concrete = [s for s in stamps if not (isinstance(s, str) and s.lower() == "live")]
        if window["start"] is None and concrete:
            window["start"] = min(pd.Timestamp(s) for s in concrete)
        if window["end"] is None and concrete and not any(
            isinstance(s, str) and s.lower() == "live" for s in stamps
        ):
            window["end"] = max(pd.Timestamp(s) for s in concrete)

        frame = self._quotes.frame(tags, freq, **window)
        out: Dict[Any, Dict[str, float]] = {}
        if frame.empty:
            return out

        for stamp in stamps:
            try:
                if isinstance(stamp, str) and stamp.lower() == "live":
                    row = frame.iloc[-1]
                else:
                    row = snapshot_from_frame(frame, stamp, method=method)
            except ValueError:
                continue
            values = {str(k): float(v) for k, v in row.items() if pd.notna(v)}
            if values:
                out[stamp] = values
        return out

    # -- convenience ----------------------------------------------------

    def validate(self, tags: Sequence[str], **kwargs: Any) -> Dict[str, str]:
        return self._quotes.validate(list(tags), **kwargs)

    def metadata(self, tags: Sequence[str]) -> Dict[str, Any]:
        return self._quotes.metadata(list(tags))
