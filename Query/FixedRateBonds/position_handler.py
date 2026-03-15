"""Fixed-rate bond position handler: NPV PnL + financing + cashflows."""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable, List, Optional, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


class FinancedFixedRateBondHandler(PositionHandler):
    """FixedRateBond positions: NPV PnL vs entry, plus optional financing and coupon/cashflow realization."""

    name = "financed_frb"

    def supports(self, query: BaseQuery) -> bool:
        return query.product == "FRB"

    @staticmethod
    def _is_constant_maturity(txt: str) -> bool:
        return bool(re.search(r"(?i)\bCT\d+\b", txt or ""))

    def _ensure_npv_value(self, q: BaseQuery) -> BaseQuery:
        from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue
        if q.product == "FRB" and getattr(q, "value", None) != FixedRateBondValue.NPV:
            return replace(q, value=FixedRateBondValue.NPV)
        return q

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
            instrument = getattr(frb, "instrument", frb)
            cf_total += float(
                pr_any.cashflows_between(
                    instrument,
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

        end_dt = backtest._cashflow_window_end_for_mtm(now)
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
        q0 = order.query
        pr = pricer_provider(q0)
        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        q = self._ensure_npv_value(q)

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
            window_end=backtest._cashflow_window_end_for_unwind(now),
            pricer_provider=pricer_provider,
            backtest=backtest,
        )
        mtm = self.value_position(position, pricer_provider, now, backtest)
        return float(cf + mtm), []
