"""STIR futures position handler: PnL($) = (delta_price / 0.01) * PV01_quote."""

from __future__ import annotations

import datetime
from typing import Any, Callable, List, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class STIRFutureHandler(PositionHandler):
    """STIR futures: PnL($) = (ΔPrice / 0.01) * PV01_quote($/bp)."""

    name = "stir_future"

    def supports(self, query: BaseQuery) -> bool:
        return query.product == "STIRFUTURE"

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
        package, weights = q.resolve_package(pricer_or_curve=pr)

        resolved_package = self._resolved_pricables(pr, package, weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=weights)
        entry_price = float(vmap.apply(value=q.default_mtm_value_id()))

        meta = {**(order.meta or {}), "handler": self.name, "entry_price": entry_price}
        return ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=q,
            meta=meta,
        )

    def _pv01_quote(self, position: ResolvedQueryPosition, pr: Any, q: BaseQuery) -> float:
        from Query.STIRFutures.STIRFutureValue import STIRFutureValue

        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)
        return float(vmap.apply(value=STIRFutureValue.PV01))

    def _price(self, position: ResolvedQueryPosition, pr: Any, q: BaseQuery) -> float:
        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)
        return float(vmap.apply(value=q.default_mtm_value_id()))

    def value_position(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> float:
        entry_price = float((position.meta or {}).get("entry_price", 0.0))
        pr = pricer_provider(position.source_query)
        q = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)

        current_price = self._price(position, pr, q)
        dprice = float(current_price - entry_price)  # price points
        pv01_quote = self._pv01_quote(position, pr, q)

        return float((dprice / 0.01) * pv01_quote)
