from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional

import tqdm

import Query.FixedRateBonds.adapter  # noqa: F401
import Query.IRSwaps.adapter  # noqa: F401
from BT.data_handler import TimeGrid
from BT.execution_engine import ExecutionEngine
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_portfolio import QueryPortfolio, ResolvedQueryPosition
from BT.query_strategy import QueryStrategy
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base.BaseQuery import BaseQuery
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapValue
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery, FixedRateBondValue
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure

RiskFn = Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]


@dataclass
class QueryDrivenBacktest:
    time_grid: TimeGrid
    mdp: MarketDataProvider
    strategy: QueryStrategy

    exec_engine: ExecutionEngine = field(default_factory=ExecutionEngine)
    risk_fn: RiskFn = lambda p, g: {}

    portfolio: QueryPortfolio = field(default_factory=QueryPortfolio)
    _cache: Dict[Any, Any] = field(default_factory=dict)

    mtm_history: Dict[datetime.datetime, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    realized_pnl_history: Dict[datetime.datetime, float] = field(default_factory=dict)

    _now: Optional[datetime.datetime] = None  # current clock

    show_progress: bool = True
    progress_desc: str = "BACKTESTING..."

    # ---------------------------------------
    # Market data / pricer resolution (cached)
    # ---------------------------------------
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

        if FixedRateBondQuery is not None and isinstance(q, FixedRateBondQuery):
            if "cusips" not in req:
                parts = self._frb_split_components(str(getattr(q, "cusip", "") or ""))
                if not parts:
                    raise ValueError("FixedRateBondQuery requires cusip/cusips to build MDP request.")
                req = dict(req)
                req["cusips"] = parts

        return self._pricer_for_request(req)

    # -------------------------
    # IRSwaps shorthand support
    # -------------------------
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

        # Force swap MTM to NPV
        return replace(q, value=IRSwapValue.NPV, structure=structure, structure_kwargs=skw)

    def _effective_query_for_trade(
        self,
        q: BaseQuery,
        *,
        pricer_or_curve: Any,
        now: datetime.datetime,
    ) -> BaseQuery:
        orig_mr = dict(getattr(q, "market_request", None) or {})
        keep_time_key = q.mdp_time_key in orig_mr

        q_eff = self._normalize_query_for_resolution(q)

        q_tmp = replace(q_eff, market_request=q_eff.build_mdp_request(now))

        edited = q_tmp._edited(pricer_or_curve)
        if edited is not None:
            q_tmp = edited

        if not keep_time_key:
            mr = dict(getattr(q_tmp, "market_request", None) or {})
            mr.pop(q_tmp.mdp_time_key, None)
            q_tmp = replace(q_tmp, market_request=mr)

        return q_tmp

    # ----------------------------
    # FixedRateBonds shorthand/roll
    # ----------------------------
    def _frb_split_components(self, txt: str) -> List[str]:
        s = (txt or "").strip()
        if "x" in s:
            return [p for p in s.split("x") if p]
        if "/" in s:
            return [p for p in s.split("/") if p]
        return [s] if s else []

    def _frb_is_constant_maturity(self, txt: str) -> bool:
        return bool(re.search(r"(?i)\bCT\d+\b", txt or ""))

    def _frb_normalize_query_for_resolution(self, q: BaseQuery) -> BaseQuery:
        if FixedRateBondQuery is None or not isinstance(q, FixedRateBondQuery):
            return q

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

        # Force FRB MTM to NPV
        return replace(q, value=FixedRateBondValue.NPV, structure=structure, structure_kwargs=skw)

    def _frb_resolved_cusips_from_pricers(self, pricer_map: Dict[str, Any]) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {}
        for original, pr in (pricer_map or {}).items():
            meta = getattr(pr, "_meta_data", None) or {}
            out[str(original)] = meta.get("cusip")
        return out

    def _frb_effective_query_for_trade(
        self,
        q: BaseQuery,
        *,
        pricer_or_curve: Any,
        now: datetime.datetime,
    ) -> BaseQuery:
        orig_mr = dict(getattr(q, "market_request", None) or {})
        keep_time_key = q.mdp_time_key in orig_mr

        q_eff = self._frb_normalize_query_for_resolution(q)

        q_tmp = replace(q_eff, value=FixedRateBondValue.NPV, market_request=q_eff.build_mdp_request(now))

        edited = q_tmp._edited(pricer_or_curve)
        if edited is not None:
            q_tmp = edited

        if not keep_time_key:
            mr = dict(getattr(q_tmp, "market_request", None) or {})
            mr.pop(q_tmp.mdp_time_key, None)
            q_tmp = replace(q_tmp, value=FixedRateBondValue.NPV, market_request=mr)

        return q_tmp

    def _frb_npv(self, q: BaseQuery, *, package, weights, pricer_map) -> float:
        vmap = q.build_value_map(
            pricer_or_curve=pricer_map,
            package=package,
            risk_weights=weights,
        )
        value_id = q.default_mtm_value_id()
        return float(vmap.apply(value=value_id))

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

    # ----------------------------
    # FRB coupon/redemption events
    # ----------------------------
    def _frb_cashflow_window_end_for_mtm(self, now: datetime.datetime) -> datetime.datetime:
        # shift attribution 1 time-grid step earlier by looking ahead one step
        return self._next_grid_time(now)

    def _frb_cashflow_window_end_for_unwind(self, now: datetime.datetime) -> datetime.datetime:
        # do NOT look ahead when closing; don’t pre-book future cashflows on unwind
        return now

    def _frb_pending_cashflows(
        self,
        pos: ResolvedQueryPosition,
        *,
        now: datetime.datetime,
        window_end: datetime.datetime,
    ) -> float:
        """
        Sum realized cashflows (coupons + redemption) with payment dates in:
            (last_cashflow_ts, window_end]
        where last_cashflow_ts is stored in pos.meta.

        For MTM attribution one step early, pass window_end = next(now).
        For unwind (no pre-book), pass window_end = now.
        """
        if FixedRateBondQuery is None or not isinstance(pos.source_query, FixedRateBondQuery):
            return 0.0

        meta = dict(pos.meta or {})
        last = meta.get("last_cashflow_ts", pos.opened)
        last_dt = self._as_dt(last)
        end_dt = self._as_dt(window_end)

        if end_dt <= last_dt:
            return 0.0

        pricer_map = self._pricer_for_query(pos.source_query, now)
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

    def _frb_apply_cashflows(self, pos: ResolvedQueryPosition, now: datetime.datetime) -> ResolvedQueryPosition:
        """
        Book FRB cashflows into realized_pnl and advance pos.meta['last_cashflow_ts'].

        Cashflows are applied 1 time-grid step earlier in the MTM series by using window_end = next(now).
        """
        if FixedRateBondQuery is None or not isinstance(pos.source_query, FixedRateBondQuery):
            return pos

        meta = dict(pos.meta or {})
        meta.setdefault("last_cashflow_ts", pos.opened)
        meta.setdefault("cashflows_realized", 0.0)

        end_eff = self._frb_cashflow_window_end_for_mtm(now)
        cf = self._frb_pending_cashflows(replace(pos, meta=meta), now=now, window_end=end_eff)

        if cf:
            self.realized_pnl += float(cf)
            self.realized_pnl_history[now] = self.realized_pnl
            meta["cashflows_realized"] = float(meta.get("cashflows_realized", 0.0) + cf)

        meta["last_cashflow_ts"] = end_eff
        return replace(pos, meta=meta)

    # ----------------------------
    # CT roll handling (unchanged)
    # ----------------------------
    def _frb_maybe_roll_position(self, pos: ResolvedQueryPosition, now: datetime.datetime) -> ResolvedQueryPosition:
        """
        For CT* aliases:
        - detect when alias -> CUSIP mapping changes
        - BOOK pnl on the old CUSIP into realized_pnl (to keep cumulative series continuous)
        - reset entry_npv to the NPV of the new CUSIP at the roll timestamp
        """
        if FixedRateBondQuery is None or not isinstance(pos.source_query, FixedRateBondQuery):
            return pos

        q0 = pos.source_query
        cusip_txt = str(getattr(q0, "cusip", "") or "")
        if not self._frb_is_constant_maturity(cusip_txt):
            return pos

        meta2 = dict(pos.meta or {})
        entry_npv = float(meta2.get("entry_npv", 0.0))
        resolved_prev = meta2.get("resolved_cusips")

        pricer_map_prev = self._pricer_for_query(q0, now)
        try:
            resolved_now = self._frb_resolved_cusips_from_pricers(pricer_map_prev)
        except Exception:
            resolved_now = None

        if resolved_prev is None and resolved_now is not None:
            meta2["resolved_cusips"] = resolved_now
            meta2.setdefault("rolls", [])
            return replace(pos, meta=meta2)

        npv_prev = self._frb_npv(
            q0,
            package=pos.package,
            weights=pos.weights,
            pricer_map=pricer_map_prev,
        )

        did_roll = (resolved_now is not None) and (resolved_prev is not None) and (resolved_now != resolved_prev)
        if not did_roll:
            if resolved_now is not None:
                meta2["resolved_cusips"] = resolved_now
            return replace(pos, meta=meta2)

        pnl_to_date = float(npv_prev - entry_npv)
        self.realized_pnl += pnl_to_date
        self.realized_pnl_history[now] = self.realized_pnl

        rolls = list(meta2.get("rolls", []))
        rolls.append({"ts": now, "prev": resolved_prev, "new": resolved_now})
        meta2["rolls"] = rolls
        meta2["resolved_cusips"] = resolved_now

        q_eff = self._frb_normalize_query_for_resolution(q0)
        pricer_map_new = self._pricer_for_query(q_eff, now)
        pkg_new, w_new = q_eff.resolve_package(pricer_or_curve=pricer_map_new)

        npv_new = self._frb_npv(q_eff, package=pkg_new, weights=w_new, pricer_map=pricer_map_new)
        meta2["entry_npv"] = float(npv_new)

        return replace(pos, package=pkg_new, weights=w_new, meta=meta2, source_query=q_eff)

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

        # FRB contributes *PnL* (current_npv - entry_npv); cashflows are booked into realized_pnl
        if FixedRateBondQuery is not None and isinstance(pos.source_query, FixedRateBondQuery):
            current_npv = self._frb_npv(
                pos.source_query,
                package=pos.package,
                weights=pos.weights,
                pricer_map=pricer_or_curve,
            )
            entry_npv = float((pos.meta or {}).get("entry_npv", 0.0))
            return float(current_npv - entry_npv)

        # Swaps: contribute PV directly
        if isinstance(pricer_or_curve, dict):
            resolved_package = pos.package
        else:
            resolved_package = [pricer_or_curve.resolve_pricable(p, rw) for p, rw in list(zip(pos.package, pos.weights))]

        vmap = pos.source_query.build_value_map(
            pricer_or_curve=pricer_or_curve,
            package=resolved_package,
            risk_weights=pos.weights,
        )
        value_id = pos.source_query.default_mtm_value_id()
        return float(vmap.apply(value=value_id))

    # -------- unwinds (realize P&L) --------
    def _handle_unwind(self, order: UnwindOrder, now: datetime.datetime) -> None:
        to_close = self.portfolio.pop_matching(order.selector)
        if not to_close:
            self.realized_pnl_history[now] = self.realized_pnl
            return

        pnl = 0.0
        for pos in to_close:
            # Unwind should NOT pre-book future cashflows. Use window_end=now.
            pnl += float(
                self._frb_pending_cashflows(
                    pos,
                    now=now,
                    window_end=self._frb_cashflow_window_end_for_unwind(now),
                )
            )
            pnl += self._position_value(pos, now)

        fee = float((order.meta or {}).get("fee", 0.0))
        self.realized_pnl += pnl - fee
        self.realized_pnl_history[now] = self.realized_pnl

    # -------- P&L / MTM --------
    def mark_to_market(self, now: datetime.datetime) -> float:
        total = float(self.realized_pnl)

        new_positions: List[ResolvedQueryPosition] = []
        for p in self.portfolio.iter_positions():
            # 1) book cashflows (attributed 1 grid-step early)
            p1 = self._frb_apply_cashflows(p, now)
            # 2) then handle CT rolls
            p2 = self._frb_maybe_roll_position(p1, now)
            new_positions.append(p2)
            total += self._position_value(p2, now)

        self.portfolio.positions = new_positions
        self.mtm_history[now] = total
        return total

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

            new_orders: list[QueryOrder] = self.strategy.evaluate(now, self)

            add_orders = [o for o in new_orders if isinstance(o, QueryOrder)]
            unwind_orders = [o for o in new_orders if isinstance(o, UnwindOrder)]

            fills = self.exec_engine.execute(add_orders)
            self.portfolio.orders_log.extend(add_orders)
            self.portfolio.trades_log.extend(fills)

            for o in fills:
                q0 = o.query
                pricer_or_curve = self._pricer_for_query(q0, now)

                if FixedRateBondQuery is not None and isinstance(q0, FixedRateBondQuery):
                    q = self._frb_effective_query_for_trade(q0, pricer_or_curve=pricer_or_curve, now=now)
                    package, weights = q.resolve_package(pricer_or_curve=pricer_or_curve)
                    meta2 = dict(o.meta or {})

                    # store entry_npv so FRB MTM is (npv - entry_npv)
                    entry_npv = self._frb_npv(q, package=package, weights=weights, pricer_map=pricer_or_curve)
                    meta2.setdefault("entry_npv", float(entry_npv))

                    # cashflow tracking
                    meta2.setdefault("last_cashflow_ts", now)
                    meta2.setdefault("cashflows_realized", 0.0)

                    cusip_txt = str(getattr(q0, "cusip", "") or "")
                    if self._frb_is_constant_maturity(cusip_txt):
                        resolved_now = self._frb_resolved_cusips_from_pricers(pricer_or_curve)
                        meta2.setdefault("resolved_cusips", resolved_now)
                        meta2.setdefault("rolls", [])

                else:
                    q = self._effective_query_for_trade(q0, pricer_or_curve=pricer_or_curve, now=now)
                    package, weights = q.resolve_package(pricer_or_curve=pricer_or_curve)
                    meta2 = dict(o.meta or {})

                self.portfolio.add(
                    ResolvedQueryPosition(
                        package=package,
                        weights=weights,
                        opened=now,
                        source_query=q,
                        meta=meta2,
                    )
                )

            for u in unwind_orders:
                self._handle_unwind(u, now)

            self.mark_to_market(now)
