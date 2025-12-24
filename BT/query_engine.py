from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, List, Optional
from collections.abc import Mapping

import tqdm

import Query.IRSwaps.adapter  # noqa: F401
import Query.STIRFutures.adapter  # noqa: F401
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapValue
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from BT.data_handler import TimeGrid
from BT.execution_engine import ExecutionEngine
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_portfolio import QueryPortfolio, ResolvedQueryPosition
from BT.query_strategy import QueryStrategy
from BT.triggers import (
    Trigger,
    ConstantMaturityRollTrigger,
    ConstantMaturityRollTriggerRequirements,
)
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricer import _GenericPricer
from Query.Base.BaseQuery import BaseQuery

# Optional risk function: receives portfolio + a pricer getter for current time
RiskFn = Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]


class PositionHandler:
    """Responsible for building, updating, and valuing positions for a given query type."""

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
        backtest: "QueryDrivenBacktest",
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
        backtest: "QueryDrivenBacktest",
    ) -> float:
        pricer_or_curve: _GenericPricer | Dict[str, _GenericPricer] = pricer_provider(position.source_query)

        if isinstance(pricer_or_curve, Mapping):
            resolved_package = position.package
        else:
            resolved_package = [pricer_or_curve.resolve_pricable(p, rw) for p, rw in list(zip(position.package, position.weights))]

        vmap = position.source_query.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=resolved_package,
            risk_weights=position.weights,
        )

        value_id = position.source_query.default_mtm_value_id()
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


class FinancedFixedRateBondHandler(PositionHandler):
    """Handles FixedRateBond positions with repo/reverse repo financing and rolls."""

    name = "financed_frb"

    def supports(self, query: BaseQuery) -> bool:  # type: ignore[override]
        return isinstance(query, FixedRateBondQuery)

    # ----- helpers -----
    def _split_components(self, txt: str) -> List[str]:
        s = (txt or "").strip()
        if "x" in s:
            return [p for p in s.split("x") if p]
        if "/" in s:
            return [p for p in s.split("/") if p]
        return [s] if s else []

    def _is_constant_maturity(self, txt: str) -> bool:
        return bool(re.search(r"(?i)\bCT\d+\b", txt or ""))

    def _normalize_query_for_resolution(self, q: FixedRateBondQuery) -> FixedRateBondQuery:
        cusip_txt = str(getattr(q, "cusip", "") or "").strip()

        structure = getattr(q, "structure", None)
        if ("x" in cusip_txt) or ("/" in cusip_txt):
            if cusip_txt.count("x") == 1 or cusip_txt.count("/") == 1:
                structure = FixedRateBondStructure.CURVE
            elif cusip_txt.count("x") == 2 or cusip_txt.count("/") == 2:
                structure = FixedRateBondStructure.FLY

        skw = dict(getattr(q, "structure_kwargs", None) or {})
        skw.setdefault("cusip", cusip_txt)

        if structure == FixedRateBondStructure.OUTRIGHT:
            if all(skw.get(k) is None for k in ("notional", "bpv")):
                skw["bpv"] = 1.0
        else:
            if all(skw.get(k) is None for k in ("front_notional", "belly_notional", "back_notional", "bpv")):
                skw["bpv"] = 1.0

        return replace(q, value=FixedRateBondValue.NPV, structure=structure, structure_kwargs=skw)

    def _resolved_cusips_from_pricers(self, pricer_map: Dict[str, Any]) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        for original, pr in (pricer_map or {}).items():
            meta = getattr(pr, "_meta_data", None) or {}
            out[str(original)] = meta.get("cusip")
        return out

    def _npv(self, q: FixedRateBondQuery, *, package, weights, pricer_map) -> float:
        vmap = q.build_value_map(
            pricer_or_curve=pricer_map,
            package=package,
            risk_weights=weights,
        )
        value_id = q.default_mtm_value_id()
        return float(vmap.apply(value=value_id))

    def _financing_pnl(self, position: ResolvedQueryPosition, now: datetime.datetime) -> float:
        repo_rate = position.meta.get("financing_rate")
        financing_notional = position.meta.get("financing_notional")
        if repo_rate is None or financing_notional is None:
            return 0.0

        elapsed_days = (now - position.opened).days + (now - position.opened).seconds / 86400
        year_frac = elapsed_days / 360.0

        direction = 1.0 if sum(position.weights) >= 0 else -1.0
        return -direction * float(financing_notional) * float(repo_rate) * year_frac

    def _pending_cashflows(
        self,
        pos: ResolvedQueryPosition,
        *,
        now: datetime.datetime,
        window_end: datetime.datetime,
        pricer_provider: Callable[[BaseQuery], Any],
        backtest: "QueryDrivenBacktest",
    ) -> float:
        meta = dict(pos.meta or {})
        last = meta.get("last_cashflow_ts", pos.opened)
        last_dt = backtest._as_dt(last)
        end_dt = backtest._as_dt(window_end)

        if end_dt <= last_dt:
            return 0.0

        pricer_map = pricer_provider(pos.source_query)
        pr_any = next(iter((pricer_map or {}).values()), None)
        if pr_any is None or not hasattr(pr_any, "cashflows_between"):
            return 0.0

        cf_total = 0.0
        for frb in pos.package or []:
            cf_total += float(
                pr_any.cashflows_between(
                    frb,
                    start=last_dt,
                    end=end_dt,
                    include_coupons=True,
                    include_redemption=True,
                    include_end=True,
                )
            )
        return float(cf_total)

    def _apply_cashflows(
        self,
        pos: ResolvedQueryPosition,
        *,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> tuple[ResolvedQueryPosition, float]:
        meta = dict(pos.meta or {})
        meta.setdefault("last_cashflow_ts", pos.opened)
        meta.setdefault("cashflows_realized", 0.0)

        end_eff = backtest._frb_cashflow_window_end_for_mtm(now)
        cf = self._pending_cashflows(pos, now=now, window_end=end_eff, pricer_provider=pricer_provider, backtest=backtest)

        if cf:
            meta["cashflows_realized"] = float(meta.get("cashflows_realized", 0.0) + cf)
        meta["last_cashflow_ts"] = end_eff
        return replace(pos, meta=meta), float(cf)

    def _maybe_roll_position(
        self,
        pos: ResolvedQueryPosition,
        *,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
        auto_roll: Optional[bool] = False,
    ) -> tuple[ResolvedQueryPosition, float, List[Trigger]]:
        if not pos.meta.get("auto_roll", False):
            return pos, 0.0, []

        q0 = pos.source_query
        cusip_txt = str(getattr(q0, "cusip", "") or "")
        if not self._is_constant_maturity(cusip_txt):
            return pos, 0.0, []

        meta2 = dict(pos.meta or {})
        entry_npv = float(meta2.get("entry_npv", 0.0))
        resolved_prev = meta2.get("resolved_cusips")

        pricer_map_prev = pricer_provider(q0)
        try:
            resolved_now = self._resolved_cusips_from_pricers(pricer_map_prev)
        except Exception:
            resolved_now = None

        if resolved_prev is None and resolved_now is not None:
            meta2["resolved_cusips"] = resolved_now
            meta2.setdefault("rolls", [])
            return replace(pos, meta=meta2), 0.0, []

        npv_prev = self._npv(q0, package=pos.package, weights=pos.weights, pricer_map=pricer_map_prev)

        did_roll = (resolved_now is not None) and (resolved_prev is not None) and (resolved_now != resolved_prev)
        if not did_roll:
            if resolved_now is not None:
                meta2["resolved_cusips"] = resolved_now
            return replace(pos, meta=meta2), 0.0, []

        pnl_to_date = float(npv_prev - entry_npv)

        rolls = list(meta2.get("rolls", []))
        rolls.append({"ts": now, "prev": resolved_prev, "new": resolved_now})
        meta2["rolls"] = rolls
        meta2["resolved_cusips"] = resolved_now

        q_eff = self._normalize_query_for_resolution(q0)
        pricer_map_new = pricer_provider(q_eff)
        pkg_new, w_new = q_eff.resolve_package(pricer_or_curve=pricer_map_new)

        npv_new = self._npv(q_eff, package=pkg_new, weights=w_new, pricer_map=pricer_map_new)
        meta2["entry_npv"] = float(npv_new)

        trigger = ConstantMaturityRollTrigger(ConstantMaturityRollTriggerRequirements(timestamp=now, previous=resolved_prev, new=resolved_now))

        return (
            replace(pos, package=pkg_new, weights=w_new, meta=meta2, source_query=q_eff),
            pnl_to_date,
            [trigger],
        )

    # ----- PositionHandler overrides -----
    def build_position(
        self,
        order: QueryOrder,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> ResolvedQueryPosition:
        q0 = order.query
        pricer_or_curve = pricer_provider(q0)
        q = self._normalize_query_for_resolution(q0)

        pricer_or_curve = pricer_provider(q)
        package, weights = q.resolve_package(pricer_or_curve=pricer_or_curve)
        meta2 = {**(order.meta or {}), "handler": self.name}

        entry_npv = self._npv(q, package=package, weights=weights, pricer_map=pricer_or_curve)
        meta2.setdefault("entry_npv", float(entry_npv))

        meta2.setdefault("last_cashflow_ts", now)
        meta2.setdefault("cashflows_realized", 0.0)

        cusip_txt = str(getattr(q0, "cusip", "") or "")
        if self._is_constant_maturity(cusip_txt):
            resolved_now = self._resolved_cusips_from_pricers(pricer_or_curve)
            meta2.setdefault("resolved_cusips", resolved_now)
            meta2.setdefault("rolls", [])

        meta2.setdefault("financing_notional", meta2.get("financing_notional", abs(sum(weights))))

        return ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=q,
            meta=meta2,
        )

    def value_position(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> float:
        pricer_map = pricer_provider(position.source_query)
        current_npv = self._npv(
            position.source_query,
            package=position.package,
            weights=position.weights,
            pricer_map=pricer_map,
        )
        entry_npv = float((position.meta or {}).get("entry_npv", 0.0))
        base_value = float(current_npv - entry_npv)
        return base_value + self._financing_pnl(position, now)

    def on_mark(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
        auto_roll: Optional[bool] = False,
    ) -> tuple[ResolvedQueryPosition, float, List[Trigger]]:
        pos1, cf_realized = self._apply_cashflows(position, pricer_provider=pricer_provider, now=now, backtest=backtest)
        pos2, roll_realized, triggers = self._maybe_roll_position(pos1, pricer_provider=pricer_provider, now=now, backtest=backtest, auto_roll=auto_roll)
        return pos2, float(cf_realized + roll_realized), triggers

    def on_unwind(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> tuple[float, List[Trigger]]:
        cf = self._pending_cashflows(
            position,
            now=now,
            window_end=backtest._frb_cashflow_window_end_for_unwind(now),
            pricer_provider=pricer_provider,
            backtest=backtest,
        )
        mtm = self.value_position(position, pricer_provider, now, backtest)
        return float(cf + mtm), []


class STIRFutureHandler(PositionHandler):
    """Handles STIR future positions using change in price."""

    name = "stir_future"

    def supports(self, query: BaseQuery) -> bool:  # type: ignore[override]
        return isinstance(query, STIRFutureQuery)

    def _mtm_value(self, position: ResolvedQueryPosition, pricer_provider: Callable[[BaseQuery], Any]) -> float:
        pricer_or_curve: _GenericPricer | Dict[str, _GenericPricer] = pricer_provider(position.source_query)

        if isinstance(pricer_or_curve, Mapping):
            resolved_package = position.package
        else:
            resolved_package = [pricer_or_curve.resolve_pricable(p, rw) for p, rw in list(zip(position.package, position.weights))]

        vmap = position.source_query.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=resolved_package,
            risk_weights=position.weights,
        )
        value_id = position.source_query.default_mtm_value_id()
        return float(vmap.apply(value=value_id))

    def build_position(
        self,
        order: QueryOrder,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> ResolvedQueryPosition:
        query = order.query
        pricer_or_curve = pricer_provider(query)
        package, weights = query.resolve_package(pricer_or_curve=pricer_or_curve)

        meta = {**(order.meta or {}), "handler": self.name}
        position = ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=query,
            meta=meta,
        )
        entry_price = self._mtm_value(position, pricer_provider)
        meta["entry_price"] = float(entry_price)
        return replace(position, meta=meta)

    def value_position(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> float:
        entry_price = float((position.meta or {}).get("entry_price", 0.0))
        return self._mtm_value(position, pricer_provider) - entry_price


@dataclass
class QueryDrivenBacktest:
    time_grid: TimeGrid
    mdp: MarketDataProvider
    strategy: QueryStrategy

    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, g: {}

    portfolio: QueryPortfolio = field(default_factory=QueryPortfolio)
    position_handlers: List[PositionHandler] = field(default_factory=lambda: [FinancedFixedRateBondHandler(), STIRFutureHandler(), PositionHandler()])
    dynamic_triggers: List[Trigger] = field(default_factory=list)
    _cache: Dict[Any, Any] = field(default_factory=dict)

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

    def _frb_split_components(self, txt: str) -> List[str]:
        s = (txt or "").strip()
        if "x" in s:
            return [p for p in s.split("x") if p]
        if "/" in s:
            return [p for p in s.split("/") if p]
        return [s] if s else []

    def _normalize_query_for_resolution(self, q: BaseQuery) -> BaseQuery:
        if not isinstance(q, IRSwapQuery):
            return q

        tenor = getattr(q, "tenor", None)
        if not isinstance(tenor, str) or not tenor.strip():
            return q

        def _norm(s: str) -> str:
            s = s.strip().replace(" ", "").upper()
            s = s.replace("X", "x")
            m = re.match(r"^(\d+[DWMY])(\d+[DWMY])$", s)
            if m:
                return f"{m.group(1)}x{m.group(2)}"
            return s

        txt = _norm(tenor)
        parts = [p for p in txt.split("/") if p]
        slash_count = max(0, len(parts) - 1)

        skw = dict(getattr(q, "structure_kwargs", None) or {})
        skw["tenor"] = txt
        structure = getattr(q, "structure", None)

        if slash_count == 1:
            structure = IRSwapStructure.CURVE
            skw.setdefault("front_tenor", _norm(parts[0]))
            skw.setdefault("back_tenor", _norm(parts[1]))
            if all(skw.get(k) is None for k in ("front_notional", "back_notional", "bpv")):
                skw["bpv"] = 1.0

        elif slash_count == 2:
            structure = IRSwapStructure.FLY
            skw.setdefault("front_tenor", _norm(parts[0]))
            skw.setdefault("belly_tenor", _norm(parts[1]))
            skw.setdefault("back_tenor", _norm(parts[2]))
            if all(skw.get(k) is None for k in ("front_notional", "belly_notional", "back_notional", "bpv")):
                skw["bpv"] = 1.0

        else:
            if all(skw.get(k) is None for k in ("notional", "bpv")):
                skw["bpv"] = 1.0

        return replace(q, value=IRSwapValue.NPV, structure=structure, structure_kwargs=skw)

    def _pricer_for_query(self, q: BaseQuery, now: datetime.datetime) -> Any:
        q_norm = self._normalize_query_for_resolution(q)
        req = q_norm.build_mdp_request(now)

        if FixedRateBondQuery is not None and isinstance(q_norm, FixedRateBondQuery):
            if "cusips" not in req:
                parts = self._frb_split_components(str(getattr(q_norm, "cusip", "") or ""))
                if parts:
                    req = dict(req)
                    req["cusips"] = parts

        return self._pricer_for_request(req)

    def _handler_for_query(self, query: BaseQuery) -> PositionHandler:
        for handler in self.position_handlers:
            if handler.supports(query):
                return handler

        raise Exception("position handler not implemented!")

    def _handler_for_position(self, pos: ResolvedQueryPosition) -> PositionHandler:
        for handler in self.position_handlers:
            if handler.handles(pos):
                return handler
        return self._handler_for_query(pos.source_query)

    def inject_triggers(self, triggers: Iterable[Trigger]) -> None:
        self.dynamic_triggers.extend(list(triggers))

    # ----------------------------
    # Time-grid helpers (cashflows)
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
        m = self._cache.get(("next_grid_map",), {})
        return m.get(now, now)

    def _as_dt(self, x: Any) -> datetime.datetime:
        if isinstance(x, datetime.datetime):
            return x
        if isinstance(x, datetime.date):
            return datetime.datetime(x.year, x.month, x.day)
        raise TypeError(f"Expected date/datetime, got {type(x)}")

    def _frb_cashflow_window_end_for_mtm(self, now: datetime.datetime) -> datetime.datetime:
        return self._next_grid_time(now)

    def _frb_cashflow_window_end_for_unwind(self, now: datetime.datetime) -> datetime.datetime:
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

    # -------- P&L / MTM --------
    def _position_value(self, pos: ResolvedQueryPosition, now: datetime.datetime) -> float:
        handler = self._handler_for_position(pos)
        return handler.value_position(pos, lambda q: self._pricer_for_query(q, now), now, self)

    # -------- unwinds (realize P&L) --------
    def _handle_unwind(self, order: UnwindOrder, now: datetime.datetime) -> None:
        to_close = self.portfolio.pop_matching(order.selector)
        if not to_close:
            self.realized_pnl_history[now] = self.realized_pnl
            return

        pnl = 0.0
        for pos in to_close:
            handler = self._handler_for_position(pos)
            realized, triggers = handler.on_unwind(pos, lambda q: self._pricer_for_query(q, now), now, self)
            pnl += float(realized)
            if triggers:
                self.inject_triggers(triggers)

        fee = float((order.meta or {}).get("fee", 0.0))
        self.realized_pnl += pnl - fee
        self.realized_pnl_history[now] = self.realized_pnl

    # -------- P&L / MTM --------
    def mark_to_market(self, now: datetime.datetime) -> float:
        total = float(self.realized_pnl)

        new_positions: List[ResolvedQueryPosition] = []
        for p in self.portfolio.iter_positions():
            handler = self._handler_for_position(p)
            p1, realized_delta, triggers = handler.on_mark(p, lambda q: self._pricer_for_query(q, now), now, self, auto_roll=p.meta.get("auto_roll", False))

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
        trigger_pool = list(self.strategy.triggers) + list(self.dynamic_triggers)
        self.dynamic_triggers = []
        orders: List[QueryOrder] = []
        for trig in trigger_pool:
            info = trig.has_triggered(now, self)
            if info:
                for action in trig.actions:
                    if hasattr(action, "__call__"):
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
            self._now = now

            new_orders: list[QueryOrder] = self._evaluate_triggers(now)

            add_orders = [o for o in new_orders if isinstance(o, QueryOrder)]
            unwind_orders = [o for o in new_orders if isinstance(o, UnwindOrder)]

            fills = self.exec_engine.execute(add_orders)
            self.portfolio.orders_log.extend(add_orders)
            self.portfolio.trades_log.extend(fills)
            for o in fills:
                handler = self._handler_for_query(o.query)
                pos = handler.build_position(o, lambda q: self._pricer_for_query(q, now), now, self)
                self.portfolio.add(pos)

            for u in unwind_orders:
                self._handle_unwind(u, now)

            self.mark_to_market(now)
