r"""Timeseries router for the LCH-vs-CME clearing-house basis.

Routes ``CHBASIS`` queries through the normal
``TimeseriesBuilder(...).get_timeseries(..., routers={"CHBASIS": tb})`` path.

**One fetch per instrument, not per date.** The MDP returns a whole panel for a
window, so the base class's date loop would re-read the same cache once per
business day. ``_bulk_fetch`` therefore issues one window-wide request per
distinct (ccy, index, tenor, house-a, house-b) and ``_price_one`` reads the row.

**No forward fill.** A date the CCP-basis cache does not carry comes back
missing rather than as the previous day's number. A stale basis that looks like
a fresh one is exactly the kind of thing that ends up sized against, and the
caller who wants a fill can say so explicitly.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from Query.Base.BaseQuery import BaseQuery
from Query.IRClearingHouseBasis.IRClearingHouseBasisQuery import (
    IRClearingHouseBasisQuery,
    value_column,
)
from TB.BaseTimeseriesTB import BaseTimeseriesTB

__all__ = ["IRClearingHouseBasisTB"]


class IRClearingHouseBasisTB(BaseTimeseriesTB):
    _DEFAULT_PRICING_MESSAGE = "PRICING CCP BASIS."

    # ------------------------------------------------------------------
    def _bulk_fetch(self, *, reference_points: Sequence[Any],
                    queries: Sequence[BaseQuery], n_jobs: Optional[int],
                    ignore_cache: Optional[bool]) -> Dict[str, Any]:
        _ = n_jobs, ignore_cache
        if not reference_points:
            return {"panels": {}, "failures": {}}
        days = [self._as_date(p) for p in reference_points]
        start, end = min(days), max(days)

        panels: Dict[tuple, pd.DataFrame] = {}
        failures: Dict[tuple, str] = {}
        for q in queries:
            if not isinstance(q, IRClearingHouseBasisQuery):
                continue
            key = q.instrument_key()
            if key in panels or key in failures:
                continue
            try:
                pricer = self.mdp.get_pricer(q.window_request(start, end))
                df = pricer.basis_data.copy()
                df.index = pd.to_datetime(df.index).normalize()
                panels[key] = df
            except Exception as exc:                            # noqa: BLE001
                # Recorded, not swallowed: a cold cache window is a real answer
                # and the caller should be able to see which instrument it was.
                failures[key] = f"{type(exc).__name__}: {exc}"
        self._last_failures = failures
        return {"panels": panels, "failures": failures}

    # ------------------------------------------------------------------
    def _price_one(self, q: BaseQuery, *, ref_point: Any, now: datetime.datetime,
                   bulk_data: Any, n_jobs: Optional[int],
                   ignore_cache: Optional[bool]
                   ) -> Optional[Tuple[BaseQuery, float]]:
        _ = now, n_jobs, ignore_cache
        if not isinstance(q, IRClearingHouseBasisQuery):
            return None
        panels = (bulk_data or {}).get("panels") or {}
        df = panels.get(q.instrument_key())
        if df is None or df.empty:
            return None
        col = value_column(q.value)
        if col not in df.columns:
            return None
        d = pd.Timestamp(self._as_date(ref_point))
        if d not in df.index:
            return None                       # missing, NOT forward filled
        val = df.at[d, col]
        if val is None or not np.isfinite(float(val)):
            return None
        return q, float(val)

    # ------------------------------------------------------------------
    @staticmethod
    def _as_date(ref_point: Any) -> datetime.date:
        ts = pd.Timestamp(ref_point)
        return ts.normalize().to_pydatetime().date()

    @property
    def failures(self) -> Dict[tuple, str]:
        """Per-instrument fetch failures from the last call, keyed by
        ``instrument_key()``. Empty is the normal case; a cold cache window
        lands here rather than silently producing an empty column."""
        return dict(getattr(self, "_last_failures", {}))
