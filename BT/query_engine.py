from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Iterable, List, Optional

import tqdm

from BT.data_handler import TimeGrid
from BT.execution_engine import ExecutionEngine
from BT.query_order import QueryOrder, UnwindOrder
from BT.query_portfolio import QueryPortfolio, ResolvedQueryPosition
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger
from MDP.MarketDataProvider import MarketDataProvider
from Query.Base._GenericPricer import _GenericPricer
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_for_request, resolve_query
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureValue import USTFutureValue

RiskFn = Callable[[QueryPortfolio, Callable[[BaseQuery], Any]], Dict[str, float]]


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

        # Optionally refresh hydration (no mutation; just use the hydrated view for valuation)
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


class SwapPositionHandler(PositionHandler):
    """
    IR swaps: store entry NPV and mark PnL as (NPV - entry_NPV).

    Assumes resolve_query() handles:
      - tenor parsing for curve/fly etc
      - structure_kwargs hydration
      - other canonicalization
    """

    name = "swap"

    @staticmethod
    def _refresh_mms_market_request(q: BaseQuery, now: datetime.datetime) -> BaseQuery:
        if not isinstance(q, IRSwapQuery):
            return q
        if not q.is_mms:
            return q
        if q.tenor is not None:
            return q
        mr = dict(q.market_request or {})
        ts = now.date() if isinstance(now, datetime.datetime) else now
        if mr.get(q.mdp_time_key) == ts:
            return q
        return replace(q, market_request={**mr, q.mdp_time_key: ts})

    def supports(self, query: BaseQuery) -> bool:  # type: ignore[override]
        return isinstance(query, IRSwapQuery)

    def build_position(
        self,
        order: QueryOrder,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> ResolvedQueryPosition:
        q0: IRSwapQuery = order.query  # type: ignore[assignment]
        q0 = self._refresh_mms_market_request(q0, now)
        pr = pricer_provider(q0)

        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        if isinstance(q, IRSwapQuery) and getattr(q, "value", None) != IRSwapValue.NPV:
            q = replace(q, value=IRSwapValue.NPV)

        package, weights = q.resolve_package(pricer_or_curve=pr)
        resolved_package = self._resolved_pricables(pr, package, weights)

        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=weights)
        entry_npv = float(vmap.apply(value=q.default_mtm_value_id()))

        meta = {**(order.meta or {}), "handler": self.name, "entry_npv": entry_npv}
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
        q0 = self._refresh_mms_market_request(position.source_query, now)
        pr = pricer_provider(q0)
        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)

        if isinstance(q, IRSwapQuery) and getattr(q, "value", None) != IRSwapValue.NPV:
            q = replace(q, value=IRSwapValue.NPV)

        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)

        current_npv = float(vmap.apply(value=q.default_mtm_value_id()))
        entry_npv = float((position.meta or {}).get("entry_npv", 0.0))
        return float(current_npv - entry_npv)


class FinancedFixedRateBondHandler(PositionHandler):
    """FixedRateBond positions: NPV PnL vs entry, plus optional financing and coupon/cashflow realization."""

    name = "financed_frb"

    def supports(self, query: BaseQuery) -> bool:  # type: ignore[override]
        return isinstance(query, FixedRateBondQuery)

    # --- minimal helpers retained (until FixedRateBondQuery.resolve_query fully owns it) ---
    @staticmethod
    def _is_constant_maturity(txt: str) -> bool:
        import re

        return bool(re.search(r"(?i)\bCT\d+\b", txt or ""))

    def _financing_pnl(self, position: ResolvedQueryPosition, now: datetime.datetime) -> float:
        repo_rate = position.meta.get("financing_rate")
        financing_notional = position.meta.get("financing_notional")
        if repo_rate is None or financing_notional is None:
            return 0.0

        elapsed_days = (now - position.opened).days + (now - position.opened).seconds / 86400.0
        year_frac = elapsed_days / 360.0

        direction = 1.0 if sum(position.weights) >= 0 else -1.0
        return -direction * float(financing_notional) * float(repo_rate) * year_frac

    def _pending_cashflows(
        self,
        pos: ResolvedQueryPosition,
        *,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
        pricer_provider: Callable[[BaseQuery], Any],
        backtest: "QueryDrivenBacktest",
    ) -> float:
        if window_end <= window_start:
            return 0.0

        pr = pricer_provider(pos.source_query)
        pr_any = next(iter((pr or {}).values()), None) if isinstance(pr, Mapping) else pr
        if pr_any is None or not hasattr(pr_any, "cashflows_between"):
            return 0.0

        cf_total = 0.0
        for frb in pos.package or []:
            cf_total += float(
                pr_any.cashflows_between(
                    frb,
                    start=window_start,
                    end=window_end,
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
        last = meta.get("last_cashflow_ts", pos.opened)
        last_dt = backtest._as_dt(last)

        end_dt = backtest._frb_cashflow_window_end_for_mtm(now)
        cf = self._pending_cashflows(
            pos,
            window_start=last_dt,
            window_end=end_dt,
            pricer_provider=pricer_provider,
            backtest=backtest,
        )

        if cf:
            meta["cashflows_realized"] = float(meta.get("cashflows_realized", 0.0) + cf)
        meta["last_cashflow_ts"] = end_dt
        return replace(pos, meta=meta), float(cf)

    def build_position(
        self,
        order: QueryOrder,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> ResolvedQueryPosition:
        q0: FixedRateBondQuery = order.query  # type: ignore[assignment]
        pr = pricer_provider(q0)
        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        if isinstance(q, FixedRateBondQuery) and getattr(q, "value", None) != FixedRateBondValue.NPV:
            q = replace(q, value=FixedRateBondValue.NPV)

        package, weights = q.resolve_package(pricer_or_curve=pr)
        resolved_package = self._resolved_pricables(pr, package, weights)

        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=weights)
        entry_npv = float(vmap.apply(value=q.default_mtm_value_id()))

        meta = {**(order.meta or {}), "handler": self.name}
        meta.setdefault("entry_npv", float(entry_npv))
        meta.setdefault("last_cashflow_ts", now)
        meta.setdefault("cashflows_realized", 0.0)
        meta.setdefault("financing_notional", meta.get("financing_notional", abs(sum(weights))))

        cusip_txt = str(getattr(order.query, "cusip", "") or "")
        if self._is_constant_maturity(cusip_txt):
            resolved_cusip = getattr(q, "cusip", None)
            meta.setdefault("resolved_cusips", resolved_cusip)
            meta.setdefault("rolls", [])

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
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)

        current_npv = float(vmap.apply(value=q.default_mtm_value_id()))
        entry_npv = float((position.meta or {}).get("entry_npv", 0.0))
        base = float(current_npv - entry_npv)
        return base + self._financing_pnl(position, now)

    def on_mark(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
        auto_roll: Optional[bool] = False,
    ) -> tuple[ResolvedQueryPosition, float, List[Trigger]]:
        pos1, cf_realized = self._apply_cashflows(position, pricer_provider=pricer_provider, now=now, backtest=backtest)
        return pos1, float(cf_realized), []

    def on_unwind(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> tuple[float, List[Trigger]]:
        meta = dict(position.meta or {})
        last = meta.get("last_cashflow_ts", position.opened)
        last_dt = backtest._as_dt(last)

        cf = self._pending_cashflows(
            position,
            window_start=last_dt,
            window_end=backtest._frb_cashflow_window_end_for_unwind(now),
            pricer_provider=pricer_provider,
            backtest=backtest,
        )
        mtm = self.value_position(position, pricer_provider, now, backtest)
        return float(cf + mtm), []


class STIRFutureHandler(PositionHandler):
    """STIR futures: PnL($) = (ΔPrice / 0.01) * PV01_quote($/bp)."""

    name = "stir_future"

    def supports(self, query: BaseQuery) -> bool:  # type: ignore[override]
        return isinstance(query, STIRFutureQuery)

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
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=weights)
        entry_price = float(vmap.apply(value=q.default_mtm_value_id()))

        meta = {**(order.meta or {}), "handler": self.name, "entry_price": entry_price}
        return ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=now,
            source_query=q,
            meta=meta,
        )

    def _pv01_quote(self, position: ResolvedQueryPosition, pr: Any, q: BaseQuery) -> float:
        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)
        return float(vmap.apply(value=STIRFutureValue.PV01))

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
        entry_price = float((position.meta or {}).get("entry_price", 0.0))
        pr = pricer_provider(position.source_query)
        q = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)

        current_price = self._price(position, pr, q)
        dprice = float(current_price - entry_price)  # price points
        pv01_quote = self._pv01_quote(position, pr, q)

        return float((dprice / 0.01) * pv01_quote)


class USTFutureHandler(PositionHandler):
    """UST futures: PnL($) = ticks * tick_value * contracts (per leg)."""

    name = "ust_future"

    _TICK_SPECS = {
        "TU": (1.0 / 256.0, 7.8125),
        "Z3N": (1.0 / 256.0, 7.8125),
        "FV": (1.0 / 128.0, 7.8125),
        "TY": (1.0 / 64.0, 15.625),
        "UXY": (1.0 / 64.0, 15.625),
        "US": (1.0 / 32.0, 31.25),
        "WN": (1.0 / 32.0, 31.25),
        "TWE": (1.0 / 32.0, 31.25),
    }

    _BARCHART_TO_INTERNAL = {
        "ZT": "TU",
        "ZF": "FV",
        "ZN": "TY",
        "ZB": "US",
        "UB": "WN",
        "TN": "UXY",
    }

    def supports(self, query: BaseQuery) -> bool:  # type: ignore[override]
        return isinstance(query, USTFutureQuery)

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
        return cls._BARCHART_TO_INTERNAL.get(root, root)

    @classmethod
    def _tick_spec(cls, symbol: Optional[str]) -> Optional[tuple[float, float]]:
        root = cls._root_from_symbol(symbol)
        return cls._TICK_SPECS.get(root)

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
        print('1')
        pr = pricer_provider(q0)
        print('2')

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
            # if not tick_spec:
            #     dprice = float(current_price - entry_price)
            #     pv01_quote = self._pv01_quote(position, pr, q)
            #     return float((dprice / 0.01) * pv01_quote)
            tick_size, tick_value = tick_spec
            contracts = self._contracts_for_leg(leg)
            dprice = float(current_price - entry_price)
            pnl += float((dprice / tick_size) * tick_value * contracts * weight)

        return float(pnl)


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
    position_handlers: List[PositionHandler] = field(
        default_factory=lambda: [
            FinancedFixedRateBondHandler(),
            STIRFutureHandler(),
            USTFutureHandler(),
            SwapPositionHandler(),
            PositionHandler(),  # fallback
        ]
    )
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
        seed_req = q.build_mdp_request(now)
        pr = self._pricer_for_request(seed_req, mdp)

        q_req = resolve_for_request(q, timestamp=now, pricer_or_curve=pr)
        req = q_req.build_mdp_request(now)
        if req == seed_req:
            return pr
        return self._pricer_for_request(req, mdp)

    def _handler_for_query(self, query: BaseQuery) -> PositionHandler:
        handler_name = None
        if hasattr(self.strategy, "mtm_handler_name_for_query"):
            handler_name = self.strategy.mtm_handler_name_for_query(query)
        if handler_name:
            for h in self.position_handlers:
                if h.name == handler_name:
                    return h
        for h in self.position_handlers:
            if h.supports(query):
                return h
        raise RuntimeError(f"No position handler for query type: {type(query).__name__}")

    def _handler_for_position(self, pos: ResolvedQueryPosition) -> PositionHandler:
        for h in self.position_handlers:
            if h.handles(pos):
                return h
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
        return self._cache.get(("next_grid_map",), {}).get(now, now)

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