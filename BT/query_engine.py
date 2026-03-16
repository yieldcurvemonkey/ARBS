from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

import tqdm

from BT.data_handler import TimeGrid
from BT.execution_engine import ExecutionEngine
from BT.position_handler import PositionHandler, get_handler, get_handler_by_name
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_portfolio import QueryPortfolio, ResolvedQueryPosition
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_for_request, resolve_query

RiskFn = Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]


# -----------------------------
# Backtest
# -----------------------------
@dataclass
class QueryDrivenBacktest:
    time_grid: TimeGrid
    strategy: QueryStrategy
    mdp: Optional[MarketDataProvider] = None

    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, g: {}

    portfolio: QueryPortfolio = field(default_factory=QueryPortfolio)
    position_handlers: List[PositionHandler] = field(default_factory=list)
    dynamic_triggers: List[Trigger] = field(default_factory=list)
    _cache: Dict[Any, Any] = field(default_factory=dict)

    mtm_history: Dict[datetime.datetime, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    realized_pnl_history: Dict[datetime.datetime, float] = field(default_factory=dict)

    _now: Optional[datetime.datetime] = None

    show_progress: bool = True
    progress_desc: str = "BACKTESTING..."

    def __post_init__(self):
        if self.mdp is not None and self.strategy.default_mdp is None:
            self.strategy.default_mdp = self.mdp

    # -------- pricer resolution (cached per request signature) --------
    def _pricer_for_request(self, req: Dict[str, Any], mdp: MarketDataProvider) -> Any:
        sig = repr(sorted(req.items()))
        key = ("pricer", id(mdp), sig)
        if key in self._cache:
            return self._cache[key]
        pr = mdp.get_pricer(req)
        self._cache[key] = pr
        return pr

    @staticmethod
    def _enrich_request_product(req: Dict[str, Any], q: BaseQuery) -> Dict[str, Any]:
        enriched = dict(req)
        if "product" not in enriched and getattr(q, "product", None):
            enriched["product"] = q.product
        return enriched

    def _mdp_for_query(self, q: BaseQuery) -> MarketDataProvider:
        mdp = None
        if hasattr(self.strategy, "mdp_for_query"):
            mdp = self.strategy.mdp_for_query(q)
        if mdp is None:
            mdp = self.strategy.mdps
        if mdp is None:
            raise RuntimeError("No MarketDataProvider available for query.")
        return mdp

    def _pricer_for_query(self, q: BaseQuery, now: datetime.datetime) -> Any:
        mdp = self._mdp_for_query(q)
        seed_req = self._enrich_request_product(q.build_mdp_request(now), q)
        pr = self._pricer_for_request(seed_req, mdp)

        q_req = resolve_for_request(q, timestamp=now, pricer_or_curve=pr)
        req = self._enrich_request_product(q_req.build_mdp_request(now), q_req)
        if req == seed_req:
            return pr
        return self._pricer_for_request(req, mdp)

    def _handler_for_query(self, query: BaseQuery) -> PositionHandler:
        # 1. Strategy-level override via mtm_map
        handler_name = None
        if hasattr(self.strategy, "mtm_handler_name_for_query"):
            handler_name = self.strategy.mtm_handler_name_for_query(query)
        if handler_name:
            for h in self.position_handlers:
                if h.name == handler_name:
                    return h
            found = get_handler_by_name(handler_name)
            if found.name == handler_name:
                return found

        # 2. Explicit position_handlers list (backward compat)
        for h in self.position_handlers:
            if h.supports(query):
                return h

        # 3. Registry lookup by product string
        return get_handler(query.product)

    def _handler_for_position(self, pos: ResolvedQueryPosition) -> PositionHandler:
        handler_name = (pos.meta or {}).get("handler")
        if handler_name:
            for h in self.position_handlers:
                if h.handles(pos):
                    return h
            found = get_handler_by_name(handler_name)
            if found.name == handler_name:
                return found
        return self._handler_for_query(pos.source_query)

    def inject_triggers(self, triggers: Iterable[Trigger]) -> None:
        self.dynamic_triggers.extend(list(triggers))

    # ----------------------------
    # Time-grid helpers
    # ----------------------------
    def _ensure_time_grid_cache(self) -> List[datetime.datetime]:
        states = self._cache.get(("time_grid_states",))
        if states is None:
            states = list(self.time_grid)
            self._cache[("time_grid_states",)] = states
            self._cache[("next_grid_map",)] = {states[i]: states[i + 1] for i in range(len(states) - 1)}
        return states

    def _next_grid_time(self, now: datetime.datetime) -> datetime.datetime:
        self._ensure_time_grid_cache()
        return self._cache.get(("next_grid_map",), {}).get(now, now)

    def _as_dt(self, x: Any) -> datetime.datetime:
        if isinstance(x, datetime.datetime):
            return x
        if isinstance(x, datetime.date):
            return datetime.datetime(x.year, x.month, x.day)
        raise TypeError(f"Expected date/datetime, got {type(x)}")

    def _cashflow_window_end_for_mtm(self, now: datetime.datetime) -> datetime.datetime:
        return self._next_grid_time(now)

    def _cashflow_window_end_for_unwind(self, now: datetime.datetime) -> datetime.datetime:
        return now

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

    # -------- MTM --------
    def _position_value(self, pos: ResolvedQueryPosition, now: datetime.datetime) -> float:
        h = self._handler_for_position(pos)
        return h.value_position(pos, lambda q: self._pricer_for_query(q, now), now, self)

    # -------- unwinds (realize P&L) --------
    def _handle_unwind(self, order: UnwindOrder, now: datetime.datetime) -> None:
        to_close = self.portfolio.pop_matching(order.selector)
        if not to_close:
            self.realized_pnl_history[now] = self.realized_pnl
            return

        pnl = 0.0
        for pos in to_close:
            h = self._handler_for_position(pos)
            realized, triggers = h.on_unwind(pos, lambda q: self._pricer_for_query(q, now), now, self)
            pnl += float(realized)
            if triggers:
                self.inject_triggers(triggers)

        fee = float((order.meta or {}).get("fee", 0.0))
        self.realized_pnl += pnl - fee
        self.realized_pnl_history[now] = self.realized_pnl

    # -------- MTM --------
    def mark_to_market(self, now: datetime.datetime) -> float:
        total = float(self.realized_pnl)

        new_positions: List[ResolvedQueryPosition] = []
        for p in self.portfolio.iter_positions():
            h = self._handler_for_position(p)
            p1, realized_delta, triggers = h.on_mark(
                p,
                lambda q: self._pricer_for_query(q, now),
                now,
                self,
                auto_roll=p.meta.get("auto_roll", False),
            )

            if realized_delta:
                self.realized_pnl += float(realized_delta)
                self.realized_pnl_history[now] = self.realized_pnl

            if triggers:
                self.inject_triggers(triggers)

            new_positions.append(p1)
            total += self._position_value(p1, now)

        self.portfolio.positions = new_positions
        self.mtm_history[now] = total
        return total

    def _evaluate_triggers(self, now: datetime.datetime) -> List[QueryOrder]:
        pool = list(self.strategy.triggers) + list(self.dynamic_triggers)
        self.dynamic_triggers = []
        orders: List[QueryOrder] = []
        for trig in pool:
            info = trig.has_triggered(now, self)
            if info:
                for action in trig.actions:
                    if callable(action):
                        out = action(now=now, backtest=self, info=info.info)
                        if out:
                            orders.extend(out)
        return orders

    # -------- main loop --------
    def run(self) -> None:
        states = self._ensure_time_grid_cache()

        for now in tqdm.tqdm(
            states,
            disable=not self.show_progress,
            desc=self.progress_desc,
            total=len(states),
            unit="step",
        ):
            try:
                self._now = now

                new_orders = self._evaluate_triggers(now)
                add_orders = [o for o in new_orders if isinstance(o, QueryOrder)]
                unwind_orders = [o for o in new_orders if isinstance(o, UnwindOrder)]

                fills = self.exec_engine.execute(add_orders)
                self.portfolio.orders_log.extend(add_orders)
                self.portfolio.trades_log.extend(fills)

                for o in fills:
                    h = self._handler_for_query(o.query)
                    pos = h.build_position(o, lambda q: self._pricer_for_query(q, now), now, self)
                    self.portfolio.add(pos)

                for u in unwind_orders:
                    self._handle_unwind(u, now)

                self.mark_to_market(now)

            # TODO handle errors
            except Exception as e:
                print(e)
