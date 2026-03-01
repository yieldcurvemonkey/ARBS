"""IR Swap position handler: PnL = current_NPV - entry_NPV."""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import Any, Callable, List, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class SwapPositionHandler(PositionHandler):
    """
    IR swaps: store entry NPV and mark PnL as (NPV - entry_NPV).

    Assumes resolve_query() handles:
      - tenor parsing for curve/fly etc
      - structure_kwargs hydration
      - other canonicalization
    """

    name = "swap"

    @staticmethod
    def _refresh_mms_market_request(q: BaseQuery, now: datetime.datetime) -> BaseQuery:
        if q.product != "IRS":
            return q
        if not getattr(q, "is_mms", False):
            return q
        if getattr(q, "tenor", None) is not None:
            return q
        mr = dict(q.market_request or {})
        ts = now.date() if isinstance(now, datetime.datetime) else now
        if mr.get(q.mdp_time_key) == ts:
            return q
        return replace(q, market_request={**mr, q.mdp_time_key: ts})

    def supports(self, query: BaseQuery) -> bool:
        return query.product == "IRS"

    def _ensure_npv_value(self, q: BaseQuery) -> BaseQuery:
        from Query.IRSwaps.IRSwapValue import IRSwapValue
        if q.product == "IRS" and getattr(q, "value", None) != IRSwapValue.NPV:
            return replace(q, value=IRSwapValue.NPV)
        return q

    def build_position(
        self,
        order: QueryOrder,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> ResolvedQueryPosition:
        q0 = order.query
        q0 = self._refresh_mms_market_request(q0, now)
        pr = pricer_provider(q0)

        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        q = self._ensure_npv_value(q)

        package, weights = q.resolve_package(pricer_or_curve=pr)
        resolved_package = self._resolved_pricables(pr, package, weights)

        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=weights)
        entry_npv = float(vmap.apply(value=q.default_mtm_value_id()))

        meta = {**(order.meta or {}), "handler": self.name, "entry_npv": entry_npv}
        return ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=q,
            meta=meta,
        )

    def value_position(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> float:
        q0 = self._refresh_mms_market_request(position.source_query, now)
        pr = pricer_provider(q0)
        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        q = self._ensure_npv_value(q)

        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)

        current_npv = float(vmap.apply(value=q.default_mtm_value_id()))
        entry_npv = float((position.meta or {}).get("entry_npv", 0.0))
        return float(current_npv - entry_npv)
