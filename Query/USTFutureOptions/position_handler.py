"""UST future options position handler.

PnL per leg:
  (current_price - entry_price) * point_value * contracts * weight
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from typing import Any, Callable, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query
from definitions.USTFutureOptions import option_point_value_for_contract

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class USTFutureOptionHandler(PositionHandler):
    name = "ust_future_option"

    _CONTRACT_FROM_SYMBOL = re.compile(r"^(?P<contract>[^|]+)\|", re.IGNORECASE)

    def supports(self, query: BaseQuery) -> bool:
        return query.product == "USTFUTUREOPTION"

    @staticmethod
    def _contracts_for_leg(leg: Any) -> int:
        if hasattr(leg, "quantity"):
            q = leg.quantity
            val = q() if callable(q) else q
            return max(1, abs(int(val)))
        return 1

    @staticmethod
    def _leg_prices(pr: Any, package: list[Any]) -> list[float]:
        if isinstance(pr, Mapping):
            out: list[float] = []
            for p in pr.values():
                pricer_obj = p[0] if isinstance(p, list) and p else p
                if pricer_obj is None:
                    continue
                out.append(float(pricer_obj.price()))
            return out
        return [float(pr.price(pk)) for pk in package]

    @classmethod
    def _point_value_for_leg(cls, leg: Any) -> float:
        symbol = ""
        if hasattr(leg, "symbol"):
            sym_obj = leg.symbol
            symbol = sym_obj() if callable(sym_obj) else str(sym_obj)
        m = cls._CONTRACT_FROM_SYMBOL.match(str(symbol).strip().upper())
        if not m:
            return 1000.0
        contract = m.group("contract")
        return float(option_point_value_for_contract(contract))

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
        entry_leg_prices = self._leg_prices(pr, resolved_package)

        meta = {
            **(order.meta or {}),
            "handler": self.name,
            "entry_leg_prices": entry_leg_prices,
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
        entry_leg_prices = (position.meta or {}).get("entry_leg_prices")
        pr = pricer_provider(position.source_query)
        q = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)

        if not entry_leg_prices:
            resolved_package = self._resolved_pricables(pr, position.package, position.weights)
            vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)
            current_price = float(vmap.apply(value=q.default_mtm_value_id()))
            entry_price = float((position.meta or {}).get("entry_price", 0.0))
            # No reliable per-leg contract root in fallback mode; use 10Y/5Y/30Y multiplier default.
            return (current_price - entry_price) * 1000.0

        current_package, _ = q.resolve_package(pricer_or_curve=pr)
        resolved_package = self._resolved_pricables(pr, current_package, position.weights)
        current_leg_prices = self._leg_prices(pr, resolved_package)
        weights = position.weights or [1.0] * len(current_leg_prices)

        pnl = 0.0
        for entry_p, current_p, weight, leg in zip(
            entry_leg_prices, current_leg_prices, weights, resolved_package
        ):
            contracts = self._contracts_for_leg(leg)
            point_value = self._point_value_for_leg(leg)
            pnl += (float(current_p) - float(entry_p)) * point_value * contracts * float(weight)

        return float(pnl)
