"""Fixed-rate bond position handler: NPV PnL + financing + cashflows."""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from dataclasses import replace
from numbers import Real
from typing import Any, Callable, List, Optional, TYPE_CHECKING

import pandas as pd

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
    _ROLE_NAMES = {
        1: ("outright",),
        2: ("front", "back"),
        3: ("front", "belly", "back"),
    }

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

    @staticmethod
    def _as_date(value: Any) -> datetime.date:
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        if isinstance(value, pd.Timestamp):
            return value.date()
        return pd.Timestamp(value).date()

    @staticmethod
    def _as_datetime(value: Any) -> datetime.datetime:
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            return datetime.datetime.combine(value, datetime.time())
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        return pd.Timestamp(value).to_pydatetime()

    @staticmethod
    def _is_number(value: Any) -> bool:
        return isinstance(value, Real) and not isinstance(value, bool)

    def _financing_config(self, q: BaseQuery) -> Optional[dict[str, Any]]:
        raw = dict(((getattr(q, "meta", {}) or {}).get("financing") or {}))
        if not raw:
            return None

        mode = str(raw.get("mode") or "").strip()
        if not mode:
            return None
        if mode != "gc_plus_specialness":
            raise ValueError(f"Unsupported FRB financing mode: {mode!r}")

        if "gc_rate" not in raw:
            raise ValueError("FRB financing mode 'gc_plus_specialness' requires 'gc_rate'")

        day_count = str(raw.get("day_count", "ACT/360")).upper()
        if day_count != "ACT/360":
            raise ValueError(f"Unsupported FRB financing day_count: {day_count!r}")

        haircut = float(raw.get("haircut", 0.0))
        if haircut < 0.0 or haircut >= 1.0:
            raise ValueError(f"FRB financing haircut must be in [0, 1), got {haircut!r}")

        return {
            "mode": mode,
            "gc_rate": raw["gc_rate"],
            "leg_specialness_bps": dict(raw.get("leg_specialness_bps") or {}),
            "day_count": day_count,
            "haircut": haircut,
        }

    def _resolve_time_value(self, value: Any, *, as_of: datetime.date, label: str) -> float:
        if self._is_number(value):
            return float(value)

        if isinstance(value, pd.Series):
            if value.empty:
                raise ValueError(f"{label} series is empty")
            series = value.dropna()
            if series.empty:
                raise ValueError(f"{label} series contains only NaN values")
            by_date = {self._as_date(idx): float(val) for idx, val in series.items()}
            eligible = [d for d in by_date if d <= as_of]
            if not eligible:
                raise KeyError(f"No {label} value available on or before {as_of.isoformat()}")
            return by_date[max(eligible)]

        if isinstance(value, Mapping):
            if not value:
                raise ValueError(f"{label} mapping is empty")
            by_date = {self._as_date(idx): float(val) for idx, val in value.items()}
            eligible = [d for d in by_date if d <= as_of]
            if not eligible:
                raise KeyError(f"No {label} value available on or before {as_of.isoformat()}")
            return by_date[max(eligible)]

        raise TypeError(f"Unsupported {label} type: {type(value)!r}")

    @staticmethod
    def _normalize_rate_decimal(rate: float) -> float:
        rate = float(rate)
        if abs(rate) >= 1.0:
            rate /= 100.0
        return float(rate)

    def _repo_rate_for_leg(self, config: dict[str, Any], *, role: str, as_of: datetime.date) -> float:
        gc_rate = self._resolve_time_value(config["gc_rate"], as_of=as_of, label="gc_rate")

        raw_specials = dict(config.get("leg_specialness_bps") or {})
        leg_special = raw_specials.get(role, raw_specials.get(str(role), 0.0))
        if leg_special is None:
            leg_special = 0.0
        special_bps = self._resolve_time_value(leg_special, as_of=as_of, label=f"leg_specialness_bps[{role}]")
        return self._normalize_rate_decimal(gc_rate) - (float(special_bps) / 10_000.0)

    @staticmethod
    def _year_frac(start: datetime.datetime, end: datetime.datetime, *, day_count: str) -> float:
        if end <= start:
            return 0.0
        if day_count != "ACT/360":
            raise ValueError(f"Unsupported FRB financing day_count: {day_count!r}")
        elapsed_days = (end - start).total_seconds() / 86400.0
        return float(elapsed_days / 360.0)

    def _role_name(self, package_size: int, idx: int) -> str:
        names = self._ROLE_NAMES.get(package_size)
        if names is None or idx >= len(names):
            return f"leg_{idx}"
        return names[idx]

    @staticmethod
    def _leg_direction(leg: Any) -> float:
        notional = float(getattr(leg, "notional", 0.0) or 0.0)
        return 1.0 if notional >= 0.0 else -1.0

    def _pricer_for_leg(self, pricers: Any, leg: Any) -> Any:
        if not isinstance(pricers, Mapping):
            return pricers

        leg_key = str(getattr(leg, "cusip", "") or "")
        direct = pricers.get(leg_key)
        if direct is not None:
            return direct

        for key, candidate in pricers.items():
            try:
                meta = candidate.meta() or {}
            except Exception:
                meta = {}
            if str(meta.get("cusip") or key) == leg_key:
                return candidate

        raise KeyError(f"Missing FRB pricer for leg cusip={leg_key!r}. available={list(pricers.keys())}")

    def _leg_market_value(self, *, pricers: Any, leg: Any) -> float:
        pricer = self._pricer_for_leg(pricers, leg)
        notional = abs(float(getattr(leg, "notional", 0.0) or 0.0))
        if notional == 0.0:
            return 0.0

        try:
            return abs(float(pricer.npv(notional=notional)))
        except Exception:
            pass

        try:
            return abs(float(pricer.dirty_price(notional=notional)))
        except Exception:
            pass

        return abs(float(pricer.clean_price())) * notional / 100.0

    def _leg_market_value_for_time(
        self,
        position: ResolvedQueryPosition,
        *,
        leg_idx: int,
        as_of: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> float:
        pricers = backtest._pricer_for_query(position.source_query, as_of)
        leg = (position.package or [])[leg_idx]
        return self._leg_market_value(pricers=pricers, leg=leg)

    def _initial_financing_legs(
        self,
        *,
        package: list[Any],
        pricers: Any,
        as_of: datetime.datetime,
    ) -> list[dict[str, Any]]:
        legs: list[dict[str, Any]] = []
        for idx, leg in enumerate(package or []):
            legs.append(
                {
                    "role": self._role_name(len(package or []), idx),
                    "cusip": str(getattr(leg, "cusip", "") or ""),
                    "direction": self._leg_direction(leg),
                    "market_value": self._leg_market_value(pricers=pricers, leg=leg),
                    "last_financing_ts": as_of,
                }
            )
        return legs

    def _ensure_component_state(self, backtest: "QueryDrivenBacktest") -> tuple[dict[str, Any], dict[str, Any]]:
        histories = getattr(backtest, "frb_component_histories", None)
        if histories is None:
            histories = {
                "bond_realized": {},
                "financing_realized": {},
                "bond_open_mtm": {},
                "bond_total": {},
                "financing_total": {},
                "net_total": {},
            }
            setattr(backtest, "frb_component_histories", histories)

        state = getattr(backtest, "_frb_component_state", None)
        if state is None:
            state = {"bond_realized_total": 0.0, "financing_realized_total": 0.0}
            setattr(backtest, "_frb_component_state", state)

        return histories, state

    def _refresh_component_totals(self, backtest: "QueryDrivenBacktest", now: datetime.datetime) -> None:
        histories, state = self._ensure_component_state(backtest)
        bond_open = float(histories["bond_open_mtm"].get(now, 0.0))
        bond_total = float(state["bond_realized_total"] + bond_open)
        financing_total = float(state["financing_realized_total"])
        histories["bond_total"][now] = bond_total
        histories["financing_total"][now] = financing_total
        histories["net_total"][now] = float(bond_total + financing_total)

    def _record_bond_realized(self, backtest: "QueryDrivenBacktest", now: datetime.datetime, delta: float) -> None:
        histories, state = self._ensure_component_state(backtest)
        state["bond_realized_total"] = float(state["bond_realized_total"] + delta)
        histories["bond_realized"][now] = float(state["bond_realized_total"])
        self._refresh_component_totals(backtest, now)

    def _record_financing_realized(self, backtest: "QueryDrivenBacktest", now: datetime.datetime, delta: float) -> None:
        histories, state = self._ensure_component_state(backtest)
        state["financing_realized_total"] = float(state["financing_realized_total"] + delta)
        histories["financing_realized"][now] = float(state["financing_realized_total"])
        self._refresh_component_totals(backtest, now)

    def _record_open_bond_mtm(self, backtest: "QueryDrivenBacktest", now: datetime.datetime, delta: float) -> None:
        histories, _ = self._ensure_component_state(backtest)
        histories["bond_open_mtm"][now] = float(histories["bond_open_mtm"].get(now, 0.0) + delta)
        self._refresh_component_totals(backtest, now)

    def _financing_delta(
        self,
        position: ResolvedQueryPosition,
        *,
        window_end: datetime.datetime,
        backtest: "QueryDrivenBacktest",
        refresh_ledger: bool,
    ) -> tuple[list[dict[str, Any]], float]:
        config = self._financing_config(position.source_query)
        if config is None:
            return list((position.meta or {}).get("financing_legs", []) or []), 0.0

        legs = [dict(leg) for leg in ((position.meta or {}).get("financing_legs", []) or [])]
        if not legs:
            return [], 0.0

        total = 0.0
        for idx, leg in enumerate(legs):
            last_dt = backtest._as_dt(leg.get("last_financing_ts", position.opened))
            if window_end > last_dt:
                repo_rate = self._repo_rate_for_leg(config, role=str(leg.get("role", f"leg_{idx}")), as_of=self._as_date(last_dt))
                financed_value = abs(float(leg.get("market_value", 0.0) or 0.0)) * (1.0 - float(config.get("haircut", 0.0)))
                year_frac = self._year_frac(last_dt, window_end, day_count=str(config["day_count"]))
                direction = float(leg.get("direction", 0.0) or 0.0)
                sign = -1.0 if direction >= 0.0 else 1.0
                total += sign * financed_value * float(repo_rate) * year_frac

            if refresh_ledger:
                leg["last_financing_ts"] = window_end
                leg["market_value"] = self._leg_market_value_for_time(position, leg_idx=idx, as_of=window_end, backtest=backtest)

        return legs, float(total)

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

        if self._financing_config(q) is not None:
            meta["financing_legs"] = self._initial_financing_legs(
                package=package,
                pricers=pr,
                as_of=now,
            )

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
        self._record_open_bond_mtm(backtest, now, base)
        return base

    def on_mark(
        self,
        position: ResolvedQueryPosition,
        pricer_provider: Callable[[BaseQuery], Any],
        now: datetime.datetime,
        backtest: "QueryDrivenBacktest",
        auto_roll: Optional[bool] = False,
    ) -> tuple[ResolvedQueryPosition, float, List[Trigger]]:
        pos1, cf_realized = self._apply_cashflows(position, pricer_provider=pricer_provider, now=now, backtest=backtest)
        financing_window_end = backtest._cashflow_window_end_for_mtm(now)
        financing_legs, financing_realized = self._financing_delta(
            pos1,
            window_end=financing_window_end,
            backtest=backtest,
            refresh_ledger=True,
        )

        meta = dict(pos1.meta or {})
        if financing_legs:
            meta["financing_legs"] = financing_legs
        pos2 = replace(pos1, meta=meta)

        if cf_realized:
            self._record_bond_realized(backtest, now, float(cf_realized))
        if financing_realized:
            self._record_financing_realized(backtest, now, float(financing_realized))
        return pos2, float(cf_realized + financing_realized), []

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
        _, financing_realized = self._financing_delta(
            position,
            window_end=backtest._cashflow_window_end_for_unwind(now),
            backtest=backtest,
            refresh_ledger=False,
        )

        pr = pricer_provider(position.source_query)
        q = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)
        resolved_package = self._resolved_pricables(pr, position.package, position.weights)
        vmap = q.build_value_map(pricer_or_curve=pr, package=resolved_package, risk_weights=position.weights)
        current_npv = float(vmap.apply(value=q.default_mtm_value_id()))
        entry_npv = float((position.meta or {}).get("entry_npv", 0.0))
        gross_mtm = float(current_npv - entry_npv)

        bond_delta = float(cf + gross_mtm)
        if bond_delta:
            self._record_bond_realized(backtest, now, bond_delta)
        if financing_realized:
            self._record_financing_realized(backtest, now, float(financing_realized))
        return float(bond_delta + financing_realized), []

    def projected_holding_cost_ccy(
        self,
        position: ResolvedQueryPosition,
        now: datetime.datetime,
        horizon_end: datetime.datetime,
        backtest: "QueryDrivenBacktest",
    ) -> float:
        _, financing_realized = self._financing_delta(
            position,
            window_end=backtest._as_dt(horizon_end),
            backtest=backtest,
            refresh_ledger=False,
        )
        return float(-financing_realized)
