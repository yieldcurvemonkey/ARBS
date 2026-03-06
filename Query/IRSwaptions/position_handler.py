from __future__ import annotations

import datetime
from dataclasses import replace
from typing import Any, Callable, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query
from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class IRSwaptionPositionHandler(PositionHandler):
    name = "ir_swaption"

    def supports(self, query: BaseQuery) -> bool:
        return query.product in {"IRSWAPTION", "IRSWAPTIONS"}

    @staticmethod
    def _ensure_spot_npv(q: BaseQuery) -> BaseQuery:
        if q.product in {"IRSWAPTION", "IRSWAPTIONS"} and getattr(q, "value", None) != IRSwaptionValue.SPOT_NPV:
            return replace(q, value=IRSwaptionValue.SPOT_NPV)
        return q

    def build_position(
        self,
        order: QueryOrder,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> ResolvedQueryPosition:
        q0 = order.query
        pr = pricer_provider(q0)
        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        q = self._ensure_spot_npv(q)

        package, weights = q.resolve_package(pricer_or_curve=pr)
        vmap = q.build_value_map(pricer_or_curve=pr, package=package, risk_weights=weights)
        entry_spot_npv = float(vmap.apply(value=IRSwaptionValue.SPOT_NPV))

        meta = {**(order.meta or {}), "handler": self.name, "entry_spot_npv": entry_spot_npv}
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
        q0 = position.source_query
        pr = pricer_provider(q0)
        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        q = self._ensure_spot_npv(q)

        vmap = q.build_value_map(pricer_or_curve=pr, package=position.package, risk_weights=position.weights)
        current_spot_npv = float(vmap.apply(value=IRSwaptionValue.SPOT_NPV))
        entry_spot_npv = float((position.meta or {}).get("entry_spot_npv", 0.0))
        return float(current_spot_npv - entry_spot_npv)

