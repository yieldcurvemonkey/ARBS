"""Fetch calibrated rateslib SOFR curves from a Citi Velocity intraday workbook.

Mirrors the interface style of
``MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/ErisFuturesFetcher.py``'s
``fetch_intraday_discount_curve`` — but the market data comes from the local
Citi Velocity ``CVTSHIST`` export instead of the Eris FTP, and the curve is
*solved* from par swap rates rather than read off published discount factors.

Typical use
-----------
>>> f = CitiVelocityIntradayFetcher()                      # defaults to db.xlsx
>>> rlc = f.build_curve()                                  # latest snapshot
>>> rlc = f.build_curve("2026-07-17 11:30")                # nearest snapshot
>>> curve, ts = f.fetch_intraday_discount_curve("2026-07-17 11:30")
>>> for ts, rlc in f.iter_curves("2026-07-17 09:00", "2026-07-17 16:00", freq="15min"):
...     ...
"""

from __future__ import annotations

import datetime
import os
from typing import Dict, Iterator, Optional, Tuple, Union

import pandas as pd
import rateslib as rl

from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import RLCurveBase
from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.citi_velocity_loader import CitiVelocityWorkbook
from MDP.IRSwaps.CITI_VELOCITY_INTRADAY.rl_usd_sofr_intraday_builder import (
    build_rl_usd_sofr_intraday_curve,
)

__all__ = ["CitiVelocityIntradayFetcher", "DEFAULT_DB_PATH"]

DateLike = Union[str, datetime.date, datetime.datetime, pd.Timestamp]

# Repo idiom: absolute default path overridable via env var.
DEFAULT_DB_PATH = os.environ.get(
    "CITI_VELOCITY_INTRADAY_DB",
    r"C:\Users\chris\clee\textbooks\sdr_dealer_direction\citi_usd_sofr_intraday_curve\db.xlsx",
)


class CitiVelocityIntradayFetcher:
    """Read a Citi Velocity intraday par workbook and hand back rateslib curves."""

    def __init__(
        self,
        workbook_path: str = DEFAULT_DB_PATH,
        *,
        curve_id: str = "USD-SOFR-1D",
        tz: Optional[str] = None,
        cache: bool = True,
        **build_kwargs,
    ):
        self.workbook_path = str(workbook_path)
        self.curve_id = curve_id
        self._wb = CitiVelocityWorkbook(self.workbook_path, tz=tz)
        self._build_kwargs = build_kwargs
        self._cache_enabled = cache
        self._curve_cache: Dict[Tuple, RLCurveBase] = {}

    # ------------------------------------------------------------------ #
    # metadata / raw data passthroughs
    # ------------------------------------------------------------------ #
    def populated_sheets(self):
        return self._wb.populated_sheets()

    def sheet_periods(self):
        return self._wb.sheet_periods()

    def timestamps(self) -> pd.DatetimeIndex:
        """All available intraday snapshot timestamps (ascending)."""
        return self._wb.timestamps()

    def frame(self) -> pd.DataFrame:
        """The full time-indexed par-rate frame across every populated sheet."""
        return self._wb.frame()

    def snapshot_par_rates(self, when: Optional[DateLike] = None, *, method: str = "nearest") -> pd.Series:
        """Par-rate curve (Series of tenor→percent) at/nearest ``when``."""
        return self._wb.snapshot(self._coerce(when), method=method)

    # ------------------------------------------------------------------ #
    # curve building
    # ------------------------------------------------------------------ #
    def build_curve(
        self,
        when: Optional[DateLike] = None,
        *,
        method: str = "nearest",
        curve_id: Optional[str] = None,
        **build_overrides,
    ) -> RLCurveBase:
        """Return a solved :class:`RLCurveBase` for the snapshot at/nearest ``when``.

        ``when=None`` uses the most recent snapshot.  ``method`` is
        ``nearest`` | ``asof`` | ``exact``.
        """
        series = self.snapshot_par_rates(when, method=method)
        ts = pd.Timestamp(series.name)
        cid = curve_id or self.curve_id
        kwargs = {**self._build_kwargs, **build_overrides}

        cache_key = (ts, cid, tuple(sorted(kwargs.items())))
        if self._cache_enabled and cache_key in self._curve_cache:
            return self._curve_cache[cache_key]

        rlc = build_rl_usd_sofr_intraday_curve(
            par_rates=series,
            ref_date=ts,
            curve_id=cid,
            timestamp=ts.to_pydatetime(),
            **kwargs,
        )
        if self._cache_enabled:
            self._curve_cache[cache_key] = rlc
        return rlc

    def latest(self, **build_overrides) -> RLCurveBase:
        return self.build_curve(None, **build_overrides)

    def fetch_intraday_discount_curve(
        self,
        snap: Optional[DateLike] = None,
        *,
        curve_id: Optional[str] = None,
        method: str = "nearest",
        return_df: bool = False,
        return_intraday_timestamp: bool = True,
        return_rl_curve_base: bool = False,
        **build_overrides,
    ) -> Union[
        rl.Curve,
        RLCurveBase,
        pd.Series,
        Tuple[rl.Curve, datetime.datetime],
        Tuple[RLCurveBase, datetime.datetime],
    ]:
        """Eris-style entry point.

        Parameters
        ----------
        snap
            Timestamp to fetch (``None`` → latest).
        return_df
            Return the raw par-rate Series for that snapshot instead of a curve.
        return_intraday_timestamp
            When ``True`` (default) return ``(curve, timestamp)``; else just the curve.
        return_rl_curve_base
            Return the full :class:`RLCurveBase` rather than the bare
            ``rl.Curve`` (the Eris fetcher returns the bare curve).
        """
        if return_df:
            return self.snapshot_par_rates(snap, method=method)

        rlc = self.build_curve(snap, method=method, curve_id=curve_id, **build_overrides)
        result = rlc if return_rl_curve_base else rlc.rl_pricing_curve
        if return_intraday_timestamp:
            ts = pd.Timestamp(rlc.timestamp).to_pydatetime()
            return result, ts
        return result

    def iter_curves(
        self,
        start: Optional[DateLike] = None,
        end: Optional[DateLike] = None,
        *,
        freq: Optional[str] = None,
        method: str = "nearest",
        curve_id: Optional[str] = None,
        **build_overrides,
    ) -> Iterator[Tuple[pd.Timestamp, RLCurveBase]]:
        """Iterate ``(timestamp, RLCurveBase)`` over an intraday window.

        With ``freq`` (e.g. ``"5min"``, ``"1H"``) a regular target grid between
        ``start`` and ``end`` is generated and each point snapped to the nearest
        available snapshot (duplicates collapsed).  Without ``freq`` every raw
        snapshot in ``[start, end]`` is yielded.
        """
        index = self.timestamps()
        if index.empty:
            return

        lo = index[0] if start is None else self._coerce_index_tz(start, index)
        hi = index[-1] if end is None else self._coerce_index_tz(end, index)

        if freq is None:
            targets = index[(index >= lo) & (index <= hi)]
        else:
            grid = pd.date_range(lo, hi, freq=freq)
            # map the fetcher's method vocabulary (nearest|asof|exact) onto the
            # pad/backfill/nearest set that pandas Index.get_indexer accepts.
            gi_method = {"asof": "ffill", "exact": "nearest", "nearest": "nearest"}.get(method, method)
            positions = index.get_indexer(grid, method=gi_method)
            positions = sorted({p for p in positions if p != -1})
            targets = index[positions]

        seen = set()
        for ts in targets:
            key = pd.Timestamp(ts)
            if key in seen:
                continue
            seen.add(key)
            yield key, self.build_curve(key, method="exact", curve_id=curve_id, **build_overrides)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _coerce(self, when: Optional[DateLike]) -> Optional[datetime.datetime]:
        if when is None:
            return None
        return pd.Timestamp(when).to_pydatetime()

    def _coerce_index_tz(self, when: DateLike, index: pd.DatetimeIndex) -> pd.Timestamp:
        key = pd.Timestamp(when)
        if key.tzinfo is None and index.tz is not None:
            key = key.tz_localize(index.tz)
        elif key.tzinfo is not None and index.tz is None:
            key = key.tz_localize(None)
        return key
