"""
Base PositionHandler and handler registry.

Each product registers its handler via ``register_handler(product, cls)``
(typically in the product's ``adapter.py`` alongside ``register_product``).
The backtest engine discovers handlers through ``get_handler(product)``.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Type, TYPE_CHECKING

from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class PositionHandler:
    """Builds, updates, and values positions for a given query type."""

    name: str = "generic"

    def supports(self, query: BaseQuery) -> bool:
        return True

    def handles(self, position: ResolvedQueryPosition) -> bool:
        return position.meta.get("handler") == self.name

    @staticmethod
    def _resolved_pricables(pricer_or_curve: Any, package: list[Any], weights: list[float]) -> list[Any]:
        if isinstance(pricer_or_curve, Mapping):
            return package
        return [pricer_or_curve.resolve_pricable(p, rw) for p, rw in zip(package, weights)]

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

        meta = {**(order.meta or {}), "handler": self.name}
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
        pr = pricer_provider(position.source_query)

        q = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)

        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(
            pricer_or_curve=pr,
            package=resolved_package,
            risk_weights=position.weights,
        )
        value_id = q.default_mtm_value_id()
        return float(vmap.apply(value=value_id))

    def on_mark(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
        auto_roll: Optional[bool] = False,
    ) -> tuple[ResolvedQueryPosition, float, List[Trigger]]:
        return position, 0.0, []

    def on_unwind(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> tuple[float, List[Trigger]]:
        return self.value_position(position, pricer_provider, now, backtest), []


# --------------- Handler Registry ---------------

_HANDLERS: Dict[str, Type[PositionHandler]] = {}


def register_handler(product: str, handler_cls: Type[PositionHandler]) -> None:
    """Register a PositionHandler class for a product string (e.g. ``"IRS"``)."""
    if not (isinstance(handler_cls, type) and issubclass(handler_cls, PositionHandler)):
        raise TypeError(f"handler_cls must be a subclass of PositionHandler, got {handler_cls}")
    _HANDLERS[product] = handler_cls


def get_handler(product: str) -> PositionHandler:
    """Return an instance of the registered handler for *product*, or the generic fallback."""
    cls = _HANDLERS.get(product)
    if cls is None:
        return PositionHandler()
    return cls()


def get_handler_by_name(name: str) -> PositionHandler:
    """Return an instance of the handler whose ``name`` attribute matches *name*."""
    for cls in _HANDLERS.values():
        inst = cls()
        if inst.name == name:
            return inst
    return PositionHandler()


def registered_handlers() -> Dict[str, Type[PositionHandler]]:
    """Return a copy of the handler registry (for introspection / debugging)."""
    return dict(_HANDLERS)
