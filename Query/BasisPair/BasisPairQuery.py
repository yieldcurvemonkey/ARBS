"""QueryDrivenBacktest product for the V1 basis position (long/short CTD net basis).

One module holds the query, the (inert) adapter and the position handler, because the handler
overrides the whole pricing surface and splitting three ~30-line pieces across three files would
only obscure that.

**Why not `USTFutureBasisQuery`?** It is the repo's real basis instrument and it prices the cash
leg through QuantLib with coupons and financing -- but it rebuilds the deliverable basket on every
mark, at ~1.3s a day. Over 2,900 days that is an hour per backtest and a grid search is impossible.
This product marks off a precomputed panel instead, which is the same arithmetic (see below) at
microseconds a day, and the panel itself was built by that same basket machinery.

**Marking.** Long basis P&L per 100 face = d(P_cash) - CF*d(F) + coupon accrual - repo cost, which
is d(gross basis) + one day's carry = **d(net basis)**. Carry is already inside the net basis, so
the daily mark needs nothing else. All P&L is realized daily via ``on_mark``; ``value_position``
returns 0, so the equity curve is cumulative realized.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, replace
from typing import Any, List, Optional

import numpy as np
import pandas as pd

from BT.position_handler import PositionHandler, register_handler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.Base.product_adapter import ProductAdapter, register_product

PRODUCT = "BASISPAIR"
TICK_USD_PER_MM = 312.50


# --------------------------------------------------------------------------- MDP
@dataclass(frozen=True)
class PanelMark:
    date: pd.Timestamp
    root: str
    symbol: str
    nb32: float
    is_roll: bool


class BasisPanelMDP(MarketDataProvider):
    """Serves one day of the precomputed basis panel. Absence is absence, never a stale neighbour."""

    def __init__(self, panel: pd.DataFrame):
        p = panel.copy()
        p["date"] = pd.to_datetime(p["date"])
        self._by = {(r.root, pd.Timestamp(r.date).normalize()): r for r in p.itertuples(index=False)}

    def get_pricer(self, request: dict):
        root = request.get("root")
        ts = request.get("timestamp")
        if root is None or ts is None or isinstance(ts, str):
            return None
        r = self._by.get((root, pd.Timestamp(ts).normalize()))
        if r is None:
            return None
        return PanelMark(pd.Timestamp(r.date), r.root, r.symbol, float(r.ctd_bnoc32),
                         bool(getattr(r, "is_roll", False)))


# --------------------------------------------------------------------------- query
@dataclass(frozen=True)
class BasisPairQuery(BaseQuery):
    root: str = "ZB"
    side: int = 1                 # +1 = long basis (long CTD, short CF futures)
    face_mm: float = 100.0
    cost_32nds: float = 0.5
    cost_mult: float = 1.0
    max_gap_days: int = 5

    def __post_init__(self):
        object.__setattr__(self, "product", PRODUCT)
        object.__setattr__(self, "structure_id", "CTD_BASIS")
        req = dict(self.market_request or {})
        req.setdefault("root", self.root)
        object.__setattr__(self, "market_request", req)

    def return_query(self):
        return self

    def col_name(self, cube_name: Optional[str] = None) -> str:
        return f"BASIS|{self.root}|side{self.side:+d}|{self.face_mm:g}mm"

    def eval_expression(self, cube_name: Optional[str] = None) -> str:
        return self.col_name(cube_name)


# --------------------------------------------------------------------------- adapter
class _Inert:
    def apply(self, *a, **k):
        raise NotImplementedError("BASISPAIR is priced by its PositionHandler.")


class BasisPairAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve): return _Inert()

    def build_value_map(self, *, pricer_or_curve, package, risk_weights): return _Inert()

    def edit_query(self, *, q, pricer_or_curve): return q


# --------------------------------------------------------------------------- handler
class BasisPairHandler(PositionHandler):
    name = "basis_pair"

    def supports(self, query: BaseQuery) -> bool:
        return getattr(query, "product", None) == PRODUCT

    def build_position(self, order: QueryOrder, pricer_provider, now, backtest):
        q = order.query
        m = pricer_provider(q)
        if m is None:
            raise ValueError(f"no panel mark for {q.root} at {now}")
        meta = {**(order.meta or {}), "handler": self.name, "side": int(q.side),
                "prev_nb32": m.nb32, "symbol": m.symbol, "prev_mark": _d(now),
                "usd_per_32nd": q.face_mm * TICK_USD_PER_MM, "cum_pnl": 0.0}
        return ResolvedQueryPosition(package=[], weights=[], opened=now, source_query=q, meta=meta)

    def value_position(self, position, pricer_provider, now, backtest) -> float:
        return 0.0

    def _step(self, position, pricer_provider, now):
        q, m0 = position.source_query, position.meta
        mk = pricer_provider(q)
        if mk is None:
            return 0.0, m0
        stale = (_d(now) - m0["prev_mark"]).days > q.max_gap_days
        if stale or mk.symbol != m0["symbol"] or mk.is_roll:
            # re-anchor, claim nothing: neither a data hole nor a contract change is a return
            return 0.0, {**m0, "prev_nb32": mk.nb32, "symbol": mk.symbol, "prev_mark": _d(now)}
        pnl = m0["side"] * (mk.nb32 - m0["prev_nb32"]) * m0["usd_per_32nd"]
        return pnl, {**m0, "prev_nb32": mk.nb32, "prev_mark": _d(now),
                     "cum_pnl": m0["cum_pnl"] + pnl}

    def on_mark(self, position, pricer_provider, now, backtest, auto_roll=False):
        pnl, meta = self._step(position, pricer_provider, now)
        return replace(position, meta=meta), float(pnl), []

    def on_unwind(self, position, pricer_provider, now, backtest):
        pnl, _ = self._step(position, pricer_provider, now)
        return float(pnl), []


def _d(x):
    return x.date() if isinstance(x, datetime.datetime) else x


register_product(PRODUCT, BasisPairAdapter)
register_handler(PRODUCT, BasisPairHandler)
