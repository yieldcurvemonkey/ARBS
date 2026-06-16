"""Position handler for Treasury-futures basis positions.

PnL of a long-basis position (buy CTD cash, sell CF-weighted futures, direction=+1):

    daily_pnl =  cash_leg_MTM      direction * (QL dirty NPV_t - NPV_entry)         [open]
              +  futures_leg_VM     -direction * (F_t - F_entry)/tick * tickval * n  [open]
              +  coupon_realized    direction * coupons in (last, now]               [realized]
              -  repo_financing     direction>=0 -> pay GC-specialness, ACT/360      [realized]

Short basis (direction=-1) flips every sign. The futures leg + CTD selection come from
the future's deliverable basket; the cash leg (the specific bond we bought, which can
later drop out of the basket) is priced independently with QuantLib via the FedInvest
bond MDP so it is always available.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from Query.Base.query_resolution import resolve_query
from Query.FixedRateBonds.carry_roll import load_us_treasury_gc_fixing_pct
from Query.USTFutureBasis.backends.rateslib.RLUSTFutureBasisPricer import RLUSTFutureBasisPricer
from definitions.USTFutures import UST_FUTURE_BARCHART_TO_INTERNAL, UST_FUTURE_TICK_SPECS

if TYPE_CHECKING:
    from BT.query_engine import QueryDrivenBacktest


# ----------------------------------------------------------------------------
# Pure PnL helpers (unit-tested in isolation)
# ----------------------------------------------------------------------------
def compute_financing_delta(*, dirty_value: float, repo_pct: float, specialness_bps: float, days: float, haircut: float, direction: int) -> float:
    """Repo financing accrual ($) over `days`, ACT/360.

    repo used = repo_pct - specialness_bps/100 (percent). Long the bond (direction>=0)
    pays repo (negative); short the bond earns reverse repo (positive).
    """
    repo_dec = (float(repo_pct) - float(specialness_bps) / 100.0) / 100.0
    financed = abs(float(dirty_value)) * (1.0 - float(haircut))
    sign = -1.0 if direction >= 0 else 1.0
    return sign * financed * repo_dec * (float(days) / 360.0)


def compute_futures_leg_pnl(*, f_now: float, f_entry: float, tick_size: float, tick_value: float, n_contracts: int, direction: int) -> float:
    """Futures variation-margin PnL ($). Long basis (direction>=0) is SHORT futures."""
    fut_sign = -1.0 if direction >= 0 else 1.0
    return fut_sign * ((float(f_now) - float(f_entry)) / float(tick_size)) * float(tick_value) * int(n_contracts)


def compute_cash_leg_pnl(*, npv_now: float, npv_entry: float, direction: int) -> float:
    """Cash bond mark-to-market ($). Long basis (direction>=0) is LONG the bond."""
    sign = 1.0 if direction >= 0 else -1.0
    return sign * (float(npv_now) - float(npv_entry))


def root_from_symbol(symbol: Optional[str]) -> str:
    if not symbol:
        return ""
    sym = symbol.strip().upper().replace("/", "")
    if sym.startswith("Z3N"):
        return "Z3N"
    if sym.startswith("TWE"):
        return "TWE"
    m = re.match(r"^([A-Z]{1,3})([FGHJKMNQUVXZ]\d{1,2})$", sym)
    root = m.group(1) if m else sym
    return UST_FUTURE_BARCHART_TO_INTERNAL.get(root, root)


# ----------------------------------------------------------------------------
# Cash-leg pricing via the FedInvest QuantLib bond MDP (cached, by cusip+date)
# ----------------------------------------------------------------------------
_QL_BOND_MDP: Any = None
_QL_BOND_CACHE: Dict[Tuple[str, datetime.date], Any] = {}


def _ql_bond_mdp() -> Any:
    global _QL_BOND_MDP
    if _QL_BOND_MDP is None:
        from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

        _QL_BOND_MDP = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    return _QL_BOND_MDP


_QL_LAST_GOOD: Dict[str, Any] = {}


def _ql_bond(cusip: str, ref_date: datetime.date) -> Any:
    key = (str(cusip), ref_date)
    if key in _QL_BOND_CACHE:
        return _QL_BOND_CACHE[key]
    pr = None
    try:
        out = _ql_bond_mdp().get_data({"cusips": [str(cusip)], "timestamp": ref_date})
        pr = out.get(str(cusip)) if isinstance(out, dict) else None
    except Exception:
        pr = None
    if pr is not None:
        _QL_LAST_GOOD[str(cusip)] = pr
    else:
        # Carry last good price forward for genuine FedInvest gaps (holidays, late
        # publishes). WI bonds (not yet issued) should no longer reach here after the
        # issued-only CTD filter in RLUSTFutureBasisPricer.
        pr = _QL_LAST_GOOD.get(str(cusip))
    _QL_BOND_CACHE[key] = pr
    return pr


def cash_npv_and_coupons(cusip: str, bond_notional: float, ref_date: datetime.date, *, cf_start=None, cf_end=None) -> Tuple[float, float]:
    """Dollar dirty NPV of the held bond at ref_date, and coupons paid in (cf_start, cf_end]."""
    ql = _ql_bond(cusip, ref_date)
    if ql is None:
        raise ValueError(f"no QL bond pricer for {cusip} @ {ref_date}")
    npv = float(ql.npv(notional=float(bond_notional)))
    coupons = 0.0
    if cf_start is not None and cf_end is not None:
        frb = ql.build_fixed_rate_bond(
            issue_date=ql.issue_date(), maturity_date=ql.maturity_date(), coupon=ql.coupon(), notional=float(bond_notional)
        )
        coupons = float(ql.cashflows_between(frb, cf_start, cf_end, include_coupons=True, include_redemption=True, include_end=True))
    return npv, coupons


# ----------------------------------------------------------------------------
# Handler
# ----------------------------------------------------------------------------
class USTFutureBasisHandler(PositionHandler):
    name = "ust_future_basis"

    def supports(self, query: BaseQuery) -> bool:
        return getattr(query, "product", None) == "USTFUTUREBASIS"

    # ---- config / helpers ----
    @staticmethod
    def _as_date(dt: Any) -> datetime.date:
        if isinstance(dt, datetime.datetime):
            return dt.date()
        return dt

    def _financing_cfg(self, q: BaseQuery) -> dict:
        cfg = dict((getattr(q, "meta", {}) or {}).get("financing", {}) or {})
        return {
            "specialness_bps": float(cfg.get("specialness_bps", 0.0)),
            "haircut": float(cfg.get("haircut", 0.0)),
            "fixed_repo_pct": cfg.get("fixed_repo_pct", None),
        }

    def _repo_pct(self, cfg: dict, as_of_date: datetime.date, leg_repo: Optional[float]) -> float:
        if cfg.get("fixed_repo_pct") is not None:
            return float(cfg["fixed_repo_pct"])
        if leg_repo is not None:
            return float(leg_repo)
        gc = load_us_treasury_gc_fixing_pct(as_of_date)
        return float(gc) if gc is not None else 0.0

    @staticmethod
    def _basis_pricer(pr: Any, symbol: str) -> RLUSTFutureBasisPricer:
        """Wrap the raw MDP future pricer into a basis pricer (for future_price / CTD / CF)."""
        if isinstance(pr, dict):
            raw = pr.get(symbol) or next(iter(pr.values()))
        else:
            raw = pr
        if isinstance(raw, RLUSTFutureBasisPricer):
            return raw
        return RLUSTFutureBasisPricer(raw)

    # ---- component ledger (for PnL decomposition) ----
    def _components(self, backtest: "QueryDrivenBacktest") -> dict:
        comp = getattr(backtest, "ustf_basis_components", None)
        if comp is None:
            comp = {"financing_total": 0.0, "coupons_total": 0.0, "financing": {}, "coupons": {}}
            setattr(backtest, "ustf_basis_components", comp)
        return comp

    def _record_realized(self, backtest: "QueryDrivenBacktest", now: datetime.datetime, *, financing: float = 0.0, coupons: float = 0.0) -> None:
        comp = self._components(backtest)
        comp["financing_total"] += float(financing)
        comp["coupons_total"] += float(coupons)
        comp["financing"][now] = comp["financing_total"]
        comp["coupons"][now] = comp["coupons_total"]

    # ---- lifecycle ----
    def build_position(self, order: QueryOrder, pricer_provider: Callable[[BaseQuery], Any], now: datetime.datetime, backtest: "QueryDrivenBacktest") -> ResolvedQueryPosition:
        q0 = order.query
        pr = pricer_provider(q0)
        q = resolve_query(q0, timestamp=now, pricer_or_curve=pr)
        package, weights = q.resolve_package(pricer_or_curve=pr)
        leg = package[0]

        symbol = leg.future_symbol()
        bp = self._basis_pricer(pr, symbol)
        cusip = leg.bond_cusip()
        bond_notional = float(leg.bond_notional())
        contracts = int(leg.contracts())
        direction = int(leg.direction())

        f_entry = float(bp.future_price())
        npv_entry, _ = cash_npv_and_coupons(cusip, bond_notional, self._as_date(now))

        root = root_from_symbol(symbol)
        tick = UST_FUTURE_TICK_SPECS.get(root)
        if tick is None:
            raise ValueError(f"No tick spec for root {root!r} (symbol {symbol!r})")

        meta = {
            **(order.meta or {}),
            "handler": self.name,
            "symbol": symbol,
            "root": root,
            "cusip": cusip,
            "bond_notional": bond_notional,
            "contracts": contracts,
            "direction": direction,
            "f_entry": f_entry,
            "npv_entry": npv_entry,
            "tick_size": float(tick[0]),
            "tick_value": float(tick[1]),
            "leg_repo_pct": leg.repo_rate(),
            "last_financing_ts": now,
            "last_dirty_value": npv_entry,
            "last_cashflow_ts": now,
        }
        return ResolvedQueryPosition(package=package, weights=weights, opened=now, source_query=q, meta=meta)

    def value_position(self, position: ResolvedQueryPosition, pricer_provider: Callable[[BaseQuery], Any], now: datetime.datetime, backtest: "QueryDrivenBacktest") -> float:
        m = position.meta or {}
        pr = pricer_provider(position.source_query)
        bp = self._basis_pricer(pr, m["symbol"])

        f_now = float(bp.future_price())
        fut = compute_futures_leg_pnl(
            f_now=f_now,
            f_entry=m["f_entry"],
            tick_size=m["tick_size"],
            tick_value=m["tick_value"],
            n_contracts=m["contracts"],
            direction=m["direction"],
        )
        npv_now, _ = cash_npv_and_coupons(m["cusip"], m["bond_notional"], self._as_date(now))
        cash = compute_cash_leg_pnl(npv_now=npv_now, npv_entry=m["npv_entry"], direction=m["direction"])
        return float(fut + cash)

    def on_mark(self, position: ResolvedQueryPosition, pricer_provider: Callable[[BaseQuery], Any], now: datetime.datetime, backtest: "QueryDrivenBacktest", auto_roll: Optional[bool] = False):
        m = dict(position.meta or {})
        last_fin = backtest._as_dt(m["last_financing_ts"])
        if now <= last_fin:
            return position, 0.0, []

        cfg = self._financing_cfg(position.source_query)
        direction = int(m["direction"])

        days = (now - last_fin).total_seconds() / 86400.0
        repo_pct = self._repo_pct(cfg, self._as_date(last_fin), m.get("leg_repo_pct"))
        financing = compute_financing_delta(
            dirty_value=m["last_dirty_value"],
            repo_pct=repo_pct,
            specialness_bps=cfg["specialness_bps"],
            days=days,
            haircut=cfg["haircut"],
            direction=direction,
        )

        last_cf = backtest._as_dt(m["last_cashflow_ts"])
        cf_end = backtest._cashflow_window_end_for_mtm(now)
        npv_now, coupons_gross = cash_npv_and_coupons(m["cusip"], m["bond_notional"], self._as_date(now), cf_start=last_cf, cf_end=cf_end)
        coupons = (1.0 if direction >= 0 else -1.0) * coupons_gross

        m["last_financing_ts"] = now
        m["last_dirty_value"] = npv_now
        m["last_cashflow_ts"] = cf_end

        self._record_realized(backtest, now, financing=financing, coupons=coupons)
        return replace(position, meta=m), float(financing + coupons), []

    def on_unwind(self, position: ResolvedQueryPosition, pricer_provider: Callable[[BaseQuery], Any], now: datetime.datetime, backtest: "QueryDrivenBacktest"):
        open_mtm = self.value_position(position, pricer_provider, now, backtest)

        m = dict(position.meta or {})
        cfg = self._financing_cfg(position.source_query)
        direction = int(m["direction"])

        realized = 0.0
        last_fin = backtest._as_dt(m["last_financing_ts"])
        financing = 0.0
        if now > last_fin:
            days = (now - last_fin).total_seconds() / 86400.0
            repo_pct = self._repo_pct(cfg, self._as_date(last_fin), m.get("leg_repo_pct"))
            financing = compute_financing_delta(
                dirty_value=m["last_dirty_value"],
                repo_pct=repo_pct,
                specialness_bps=cfg["specialness_bps"],
                days=days,
                haircut=cfg["haircut"],
                direction=direction,
            )
            realized += financing

        last_cf = backtest._as_dt(m["last_cashflow_ts"])
        cf_end = backtest._cashflow_window_end_for_unwind(now)
        _, coupons_gross = cash_npv_and_coupons(m["cusip"], m["bond_notional"], self._as_date(now), cf_start=last_cf, cf_end=cf_end)
        coupons = (1.0 if direction >= 0 else -1.0) * coupons_gross
        realized += coupons

        self._record_realized(backtest, now, financing=financing, coupons=coupons)
        return float(open_mtm + realized), []
