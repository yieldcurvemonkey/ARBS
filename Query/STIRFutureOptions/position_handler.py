"""STIR future options position handler.

PnL Economics per CME Rulebook Chapter 460A, Rule 460A01.C:
  Options are quoted in IMM Index points.
  Each 0.01 IMM Index point = $25 per option contract.
  Therefore 1.0 IMM Index point = $2,500 per option contract.

  PnL($) = Σ_legs (current_price_i - entry_price_i) × POINT_VALUE × contracts_i × weight_i
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, Callable, List, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query
from Query.STIRFutureOptions._risk import SOFR_OPTION_POINT_VALUE, option_quantity, resolve_pricer_for_leg

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class STIRFutureOptionHandler(PositionHandler):
    """
    STIR future options on Three-Month SOFR Futures (CME Chapter 460A).

    Prices from the pricer/value map are in raw IMM Index points.
    Per Rule 460A01.C the dollar multiplier is $2,500 per full IMM point
    per contract ($25 per 0.01 point, i.e. per basis point).

    PnL is computed per leg:
      PnL($) = (current_price - entry_price) × $2,500 × contracts × weight

    For multi-leg structures (verticals, straddles) each leg is tracked
    independently so differing contract counts are handled correctly.
    """

    name = "stir_future_option"

    def supports(self, query: BaseQuery) -> bool:
        return query.product == "STIRFUTUREOPTION"

    @staticmethod
    def _contracts_for_leg(leg: Any) -> float:
        """Extract contract count from a pricable instrument."""
        return abs(float(option_quantity(leg)))

    @staticmethod
    def _leg_prices(pr: Any, package: list[Any]) -> list[float]:
        """Get raw option price in IMM Index points per leg."""
        if isinstance(pr, Mapping):
            out: list[float] = []
            for idx, leg in enumerate(package):
                out.append(float(resolve_pricer_for_leg(pr, leg, index=idx).price()))
            return out
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

        # Per-leg entry prices in IMM Index points
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
            # Fallback: use risk-weighted value map price (per-contract)
            resolved_package = self._resolved_pricables(pr, position.package, position.weights)
            vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)
            current_price = float(vmap.apply(value=q.default_mtm_value_id()))
            entry_price = float((position.meta or {}).get("entry_price", 0.0))
            return (current_price - entry_price) * SOFR_OPTION_POINT_VALUE

        # Per-leg PnL: (Δprice) × $2,500 × contracts × weight
        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        current_leg_prices = self._leg_prices(pr, resolved_package)
        weights = position.weights or [1.0] * len(current_leg_prices)

        pnl = 0.0
        for entry_p, current_p, weight, leg in zip(
            entry_leg_prices, current_leg_prices, weights, resolved_package
        ):
            contracts = self._contracts_for_leg(leg)
            dprice = float(current_p - entry_p)
            pnl += dprice * SOFR_OPTION_POINT_VALUE * contracts * weight

        return float(pnl)
