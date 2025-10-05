from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import tqdm

import Query.IRSwaps.adapter  # noqa: F401

from BT.data_handler import TimeGrid
from BT.execution_engine import ExecutionEngine
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_portfolio import QueryPortfolio, ResolvedQueryPosition
from BT.query_strategy import QueryStrategy
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery

# Optional risk function: receives portfolio + a pricer getter for current time
RiskFn = Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]


@dataclass
class QueryDrivenBacktest:
    time_grid: TimeGrid
    mdp: MarketDataProvider
    strategy: QueryStrategy

    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, g: {}

    portfolio: QueryPortfolio = field(default_factory=QueryPortfolio)
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
        pricer_or_curve = self._pricer_for_query(pos.source_query, now)

        # rebuild package here, need to be product and backend agnostic

        vmap = pos.source_query.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=pos.package,
            risk_weights=pos.weights,
        )

        value_id = pos.source_query.default_mtm_value_id()
        return float(vmap.apply(value=value_id))

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
                q = o.query
                pricer_or_curve = self._pricer_for_query(q, now)
                package, weights = q.resolve_package(pricer_or_curve=pricer_or_curve)
                self.portfolio.add(
                    ResolvedQueryPosition(
                        package=package,
                        weights=weights,
                        opened=now,
                        source_query=q,
                        meta=o.meta or {},
                    )
                )

            # 2b) process unwinds (realize P&L and remove positions)
            for u in unwind_orders:
                self._handle_unwind(u, now)

            # 3) MTM (includes realized so far)
            self.mark_to_market(now)
