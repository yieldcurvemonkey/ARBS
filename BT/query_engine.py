from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import tqdm

import Query.IRSwaps.adapter  # noqa: F401
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from BT.data_handler import TimeGrid
from BT.execution_engine import ExecutionEngine
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_portfolio import QueryPortfolio, ResolvedQueryPosition
from BT.query_strategy import QueryStrategy
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricer import _GenericPricer
from Query.Base.BaseQuery import BaseQuery

# Optional risk function: receives portfolio + a pricer getter for current time
RiskFn = Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]


class PositionHandler:
    """Responsible for building and valuing positions for a given query type."""

    name: str = "generic"

    def supports(self, query: BaseQuery) -> bool:
        return True

    def handles(self, position: ResolvedQueryPosition) -> bool:
        return position.meta.get("handler") == self.name

    def build_position(
        self,
        order: QueryOrder,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
    ) -> ResolvedQueryPosition:
        query = order.query
        pricer_or_curve = pricer_provider(query)
        package, weights = query.resolve_package(pricer_or_curve=pricer_or_curve)
        meta = {**(order.meta or {}), "handler": self.name}
        return ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=query,
            meta=meta,
        )

    def value_position(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
    ) -> float:
        pricer_or_curve: _GenericPricer = pricer_provider(position.source_query)
        resolved_package = [
            pricer_or_curve.resolve_pricable(p, rw)
            for p, rw in list(zip(position.package, position.weights))
        ]

        vmap = position.source_query.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=resolved_package,
            risk_weights=position.weights,
        )

        value_id = position.source_query.default_mtm_value_id()
        return float(vmap.apply(value=value_id))


class FinancedFixedRateBondHandler(PositionHandler):
    """Handles FixedRateBond positions with repo/reverse repo financing."""

    name = "financed_frb"

    def supports(self, query: BaseQuery) -> bool:  # type: ignore[override]
        return isinstance(query, FixedRateBondQuery)

    def _financing_pnl(self, position: ResolvedQueryPosition, now: datetime.datetime) -> float:
        repo_rate = position.meta.get("financing_rate")
        financing_notional = position.meta.get("financing_notional")
        if repo_rate is None or financing_notional is None:
            return 0.0

        elapsed_days = (now - position.opened).days + (now - position.opened).seconds / 86400
        year_frac = elapsed_days / 360.0

        # Long positions pay repo (negative carry), shorts receive (positive carry)
        direction = 1.0 if sum(position.weights) >= 0 else -1.0
        return -direction * float(financing_notional) * float(repo_rate) * year_frac

    def value_position(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
    ) -> float:
        base_value = super().value_position(position, pricer_provider, now)
        return base_value + self._financing_pnl(position, now)


@dataclass
class QueryDrivenBacktest:
    time_grid: TimeGrid
    mdp: MarketDataProvider
    strategy: QueryStrategy

    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, g: {}

    portfolio: QueryPortfolio = field(default_factory=QueryPortfolio)
    position_handlers: List[PositionHandler] = field(
        default_factory=lambda: [FinancedFixedRateBondHandler(), PositionHandler()]
    )
    _cache: Dict[str, Any] = field(default_factory=dict)

    mtm_history: Dict[datetime.datetime, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    realized_pnl_history: Dict[datetime.datetime, float] = field(default_factory=dict)

    _now: Optional[datetime.datetime] = None  # current clock

    show_progress: bool = True
    progress_desc: str = "BACKTESTING..."

    # -------- pricer resolution (cached per request signature) --------
    def _pricer_for_request(self, req: Dict[str, Any]) -> Any:
        sig = repr(sorted(req.items()))
        hit = self._cache.get(("pricer", sig))
        if hit is not None:
            return hit
        pricer = self.mdp.get_pricer(req)
        self._cache[("pricer", sig)] = pricer
        return pricer

    def _pricer_for_query(self, q: BaseQuery, now: datetime.datetime) -> Any:
        req = q.build_mdp_request(now)
        return self._pricer_for_request(req)

    def _handler_for_query(self, query: BaseQuery) -> PositionHandler:
        for handler in self.position_handlers:
            if handler.supports(query):
                return handler
        return self.position_handlers[-1]

    def _handler_for_position(self, pos: ResolvedQueryPosition) -> PositionHandler:
        for handler in self.position_handlers:
            if handler.handles(pos):
                return handler
        return self._handler_for_query(pos.source_query)

    # -------- risk API used by triggers --------
    def get_strategy_risk(self, name: str) -> float:
        now = self._now

        def getter(query: BaseQuery) -> Any:
            return self._pricer_for_query(query, now)

        risks = self.risk_fn(self.portfolio, getter)
        return float(risks.get(name, 0.0))

    def trade_count_since(self, start: datetime.datetime, end: datetime.datetime) -> int:
        return self.portfolio.trade_count_between(start, end)

    def window(self, fetch_fn, now: datetime.datetime, lookback: int):
        states = [t for t in self.time_grid if t <= now]
        return [fetch_fn(t) for t in states[-lookback:]]

    # -------- P&L / MTM --------
    def _position_value(self, pos: ResolvedQueryPosition, now: datetime.datetime) -> float:
        handler = self._handler_for_position(pos)
        return handler.value_position(pos, lambda q: self._pricer_for_query(q, now), now)

    # -------- unwinds (realize P&L) --------
    def _handle_unwind(self, order: UnwindOrder, now: datetime.datetime) -> None:
        to_close = self.portfolio.pop_matching(order.selector)
        if not to_close:
            # carry forward realized so far
            self.realized_pnl_history[now] = self.realized_pnl
            return

        pnl = 0.0
        for pos in to_close:
            pnl += self._position_value(pos, now)

        fee = float((order.meta or {}).get("fee", 0.0))
        self.realized_pnl += pnl - fee
        self.realized_pnl_history[now] = self.realized_pnl

    # -------- P&L / MTM --------
    def mark_to_market(self, now: datetime.datetime) -> float:
        # total = realized + current open marks
        total = float(self.realized_pnl)
        for p in self.portfolio.iter_positions():
            total += self._position_value(p, now)
        self.mtm_history[now] = total
        return total

    # -------- main loop --------
    def run(self) -> None:
        # Materialize time grid to allow tqdm length/estimation
        states = list(self.time_grid)

        for now in tqdm.tqdm(
            states,
            disable=not self.show_progress,
            desc=self.progress_desc,
            total=len(states),
            unit="step",
        ):
            self._now = now

            # 1) Evaluate strategy -> QueryOrders
            new_orders: list[QueryOrder] = self.strategy.evaluate(now, self)

            # split: adds vs unwinds
            add_orders = [o for o in new_orders if isinstance(o, QueryOrder)]
            unwind_orders = [o for o in new_orders if isinstance(o, UnwindOrder)]

            # 2a) add new queries (freeze package at trade time, as before)
            fills = self.exec_engine.execute(add_orders)
            self.portfolio.orders_log.extend(add_orders)
            self.portfolio.trades_log.extend(fills)
            for o in fills:
                handler = self._handler_for_query(o.query)
                pos = handler.build_position(o, lambda q: self._pricer_for_query(q, now), now)
                self.portfolio.add(pos)

            # 2b) process unwinds (realize P&L and remove positions)
            for u in unwind_orders:
                self._handle_unwind(u, now)

            # 3) MTM (includes realized so far)
            self.mark_to_market(now)
