from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, Callable, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query
from Query.STIRCapFloors.STIRCapFloorValue import STIRCapFloorValue
from Query.STIRFutureOptions._risk import SOFR_OPTION_POINT_VALUE, option_quantity, resolve_pricer_for_leg

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class STIRCapFloorPositionHandler(PositionHandler):
    name = "stir_capfloor"

    def supports(self, query: BaseQuery) -> bool:
        return query.product in {"STIRCAPFLOOR", "STIRCAPFLOORS"}

    @staticmethod
    def _contracts_for_leg(leg: Any) -> float:
        return abs(float(option_quantity(leg)))

    @staticmethod
    def _leg_prices(pr: Any, package: list[Any]) -> list[float]:
        pricers = pr.pricers if hasattr(pr, "pricers") else pr
        if isinstance(pricers, Mapping):
            return [float(resolve_pricer_for_leg(pricers, leg, index=idx).price()) for idx, leg in enumerate(package)]
        return [float(pr.price(pk)) for pk in package]

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
        entry_leg_prices = self._leg_prices(pr, package)
        vmap = q.build_value_map(pricer_or_curve=pr, package=package, risk_weights=weights)
        breakdown = vmap.apply(STIRCapFloorValue.BREAKDOWN)
        meta = {
            **(order.meta or {}),
            "handler": self.name,
            "entry_leg_prices": entry_leg_prices,
            "entry_breakdown": breakdown,
        }
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
        entry_leg_prices = (position.meta or {}).get("entry_leg_prices") or []
        pr = pricer_provider(position.source_query)
        q = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)
        package = q.resolve_package(pricer_or_curve=pr)[0]
        current_leg_prices = self._leg_prices(pr, package)
        weights = position.weights or [1.0] * len(current_leg_prices)

        pnl = 0.0
        for entry_p, current_p, weight, leg in zip(entry_leg_prices, current_leg_prices, weights, package):
            contracts = self._contracts_for_leg(leg)
            pnl += float(current_p - entry_p) * SOFR_OPTION_POINT_VALUE * contracts * float(weight)
        return float(pnl)
