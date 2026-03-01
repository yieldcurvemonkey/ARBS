"""UST futures position handler: PnL($) = ticks * tick_value * contracts (per leg)."""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from typing import Any, Callable, List, Optional, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query
from definitions.USTFutures import (
    UST_FUTURE_TICK_SPECS,
    UST_FUTURE_BARCHART_TO_INTERNAL,
)

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class USTFutureHandler(PositionHandler):
    """UST futures: PnL($) = ticks * tick_value * contracts (per leg)."""

    name = "ust_future"

    def supports(self, query: BaseQuery) -> bool:
        return query.product == "USTFUTURE"

    @classmethod
    def _root_from_symbol(cls, symbol: Optional[str]) -> str:
        if not symbol:
            return ""
        sym = symbol.strip().upper().replace("/", "")
        if sym.startswith("Z3N"):
            return "Z3N"
        if sym.startswith("TWE"):
            return "TWE"
        match = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\\d{1,2})$", sym)
        root = match.group("root") if match else sym
        return UST_FUTURE_BARCHART_TO_INTERNAL.get(root, root)

    @classmethod
    def _tick_spec(cls, symbol: Optional[str]) -> Optional[tuple[float, float]]:
        root = cls._root_from_symbol(symbol)
        return UST_FUTURE_TICK_SPECS.get(root)

    @staticmethod
    def _contracts_for_leg(leg: Any) -> int:
        if hasattr(leg, "contracts") and callable(leg.contracts):
            return int(leg.contracts())
        return 1

    @staticmethod
    def _leg_prices(pr: Any, package: list[Any]) -> list[float]:
        if isinstance(pr, Mapping):
            return [float(p.price(pk)) for p, pk in zip(pr.values(), package)]
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

        resolved_package = self._resolved_pricables(pr, package, weights)
        entry_leg_prices = self._leg_prices(pr, resolved_package)

        meta = {**(order.meta or {}), "handler": self.name, "entry_leg_prices": entry_leg_prices}
        return ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=q,
            meta=meta,
        )

    def _pv01_quote(self, position: ResolvedQueryPosition, pr: Any, q: BaseQuery) -> float:
        from Query.USTFutures.USTFutureValue import USTFutureValue

        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)
        return float(vmap.apply(value=USTFutureValue.PV01))

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
        entry_leg_prices = (position.meta or {}).get("entry_leg_prices")
        pr = pricer_provider(position.source_query)
        q = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)

        if not entry_leg_prices:
            current_price = self._price(position, pr, q)
            entry_price = float((position.meta or {}).get("entry_price", current_price))
            dprice = float(current_price - entry_price)
            pv01_quote = self._pv01_quote(position, pr, q)
            return float((dprice / 0.01) * pv01_quote)

        current_package, _ = q.resolve_package(pricer_or_curve=pr)
        resolved_package = self._resolved_pricables(pr, current_package, position.weights)
        current_leg_prices = self._leg_prices(pr, resolved_package)
        weights = position.weights or [1.0] * len(current_leg_prices)

        pnl = 0.0
        if isinstance(pr, Mapping):
            leg_symbols = list(pr.keys())
        else:
            leg_symbols = [getattr(leg, "contract_code", lambda: None)() for leg in resolved_package]

        for idx, (entry_price, current_price, weight, leg) in enumerate(zip(entry_leg_prices, current_leg_prices, weights, resolved_package)):
            symbol = leg_symbols[idx] if idx < len(leg_symbols) else None
            tick_spec = self._tick_spec(symbol[:-3])
            assert tick_spec is not None, f"{symbol[:-3]} not valid symbol"
            tick_size, tick_value = tick_spec
            contracts = self._contracts_for_leg(leg)
            dprice = float(current_price - entry_price)
            pnl += float((dprice / tick_size) * tick_value * contracts * weight)

        return float(pnl)
