# ABOUTME: Generic backtest engine coordinating strategy, execution, and portfolio management
# ABOUTME: Iterates through time grid, executes strategy triggers/actions, tracks P&L and risk
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from BT.data_handler import TimeGrid
from BT.execution_engine import ExecutionEngine
from BT.strategy import Strategy
from BT.order import Order
from BT.portfolio import Portfolio
from Query.Base._GenericPricer import _GenericPricer
from Query.Base._GenericPricable import _GenericPricable
from MDP.MarketDataProvider import MarketDataProvider

RiskFn = Callable[[Portfolio, _GenericPricer], Dict[str, float]]
RequestBuilder = Callable[[dt.datetime], Dict[str, Any]]

@dataclass
class EventDrivenBacktest:
    time_grid: TimeGrid
    # Either provide a fixed pricer, or resolve via MDP on each timestep:
    pricer: Optional[_GenericPricer] = None
    mdp: Optional[MarketDataProvider] = None
    mdp_request_builder: Optional[RequestBuilder] = None

    strategy: Strategy = None
    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, r: {}

    portfolio: Portfolio = field(default_factory=Portfolio)
    cache: Dict[str, Any] = field(default_factory=dict)
    mtm_history: Dict[dt.datetime, float] = field(default_factory=dict)

    # ---------- helpers ----------
    def _current_pricer(self) -> _GenericPricer:
        cp = self.cache.get("pricer")
        if cp is None:
            raise RuntimeError("Pricer not set yet")
        return cp

    def _resolve_pricer_for(self, now: dt.datetime) -> _GenericPricer:
        if self.mdp is not None:
            if self.mdp_request_builder is None:
                raise RuntimeError("mdp_request_builder must be provided when mdp is set")
            req = dict(self.mdp_request_builder(now))
            sig = repr(sorted(req.items()))
            if self.cache.get("pricer_sig") != sig:
                self.cache["pricer"] = self.mdp.get_pricer(req)
                self.cache["pricer_sig"] = sig
        elif self.pricer is not None:
            self.cache["pricer"] = self.pricer
        else:
            raise RuntimeError("Provide either `pricer` or `mdp+mdp_request_builder`.")
        return self.cache["pricer"]

    def get_strategy_risk(self, name: str) -> float:
        risks = self.risk_fn(self.portfolio, self._current_pricer())
        return float(risks.get(name, 0.0))

    def trade_count_since(self, start: dt.datetime, end: dt.datetime) -> int:
        return self.portfolio.trade_count_between(start, end)

    def window(self, fetch_fn, now: dt.datetime, lookback: int):
        states = [t for t in self.time_grid if t <= now]
        return [fetch_fn(t) for t in states[-lookback:]]

    def mark_to_market(self, now: dt.datetime) -> float:
        pricer = self._current_pricer()
        total = 0.0
        for instr in self.portfolio.iter_instruments():
            try:
                total += float(pricer.npv(instr))
            except Exception:
                continue
        self.mtm_history[now] = total
        return total

    # ---------- main loop ----------
    def run(self) -> None:
        for now in self.time_grid:
            self._resolve_pricer_for(now)

            new_orders = self.strategy.evaluate(now, self)
            if not new_orders:
                self.mark_to_market(now)
                continue

            fills = self.exec_engine.execute(new_orders)

            self.portfolio.orders_log.extend(new_orders)
            self.portfolio.trades_log.extend(fills)
            for o in fills:
                self.portfolio.add(o.instrument, opened=now, meta=o.meta or {})

            self.mark_to_market(now)
