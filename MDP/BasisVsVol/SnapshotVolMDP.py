"""Offline MarketDataProvider serving the stored vol surfaces to the backtest engine.

The point of a snapshot-backed MDP is that a historical backtest must never reach a vendor. Every
mark comes from the parquet mirror of ``arbs_ustf_vol_snapshots_v2`` /
``arbs_swaption_vol_snapshots_v2``, so a run is reproducible, offline, and cannot silently serve
"today" for a 2023 date.

``get_pricer(request)`` returns a :class:`PairSnapshot` for one date -- the two ``DailySurface``
objects the position handler needs. It returns ``None`` when the date is absent rather than the
nearest available snapshot: a minute store that answers a request for today with yesterday's data
in 2ms is exactly the failure this avoids.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from MDP.MarketDataProvider import MarketDataProvider
from RVUtils.BasisVsVol.surfaces import DailySurface, SurfaceBook
from RVUtils.BasisVsVol.voldata import PRODUCT_TAIL, VolData

__all__ = ["PairSnapshot", "SnapshotVolMDP"]


@dataclass(frozen=True)
class PairSnapshot:
    date: pd.Timestamp
    product: str
    tail: str
    ustf: DailySurface
    swpt: DailySurface

    @property
    def fv01(self) -> float:
        return float(self.ustf.meta.get("fv01", float("nan")))

    @property
    def underlying_contract(self) -> str:
        return str(self.ustf.meta.get("underlying_contract", ""))


class SnapshotVolMDP(MarketDataProvider):
    """Serves :class:`PairSnapshot` keyed on (product, tail, timestamp)."""

    def __init__(self, vd: VolData, book: SurfaceBook | None = None):
        self.vd = vd
        self.book = book or SurfaceBook(vd)

    @staticmethod
    def _as_ts(v) -> pd.Timestamp | None:
        if v is None or isinstance(v, str):
            return None
        if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
            return pd.Timestamp(v).normalize()
        return None

    def get_pricer(self, request: dict):
        product = request.get("product")
        tail = request.get("tail") or PRODUCT_TAIL.get(product)
        ts = self._as_ts(request.get("timestamp"))
        if product is None or tail is None or ts is None:
            return None
        u = self.book.ustf(product).get(ts)
        s = self.book.swpt(tail).get(ts)
        if u is None or s is None:
            return None  # absence, never the nearest neighbour
        return PairSnapshot(date=ts, product=product, tail=tail, ustf=u, swpt=s)
