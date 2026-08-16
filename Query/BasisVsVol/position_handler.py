"""PositionHandler for the paired vol structure.

Accounting choice: **all P&L is realized daily, none is carried as an unrealized mark.**
``value_position`` returns 0.0 and every day's delta-hedged P&L is returned from ``on_mark`` as a
realized delta. That is the correct shape for a delta-hedged book -- the hedge is rebalanced and
the increment banked each day -- and it sidesteps the framework's generic ``value_position``,
which marks an absolute value rather than value-minus-entry and would otherwise report the option
premium as profit on day one.

The engine unwinds *before* it marks within a step, so the exit day's P&L would be lost if it were
only computed in ``on_mark``. ``on_unwind`` therefore runs the same one-day computation and returns
it; the engine subtracts the fee separately.
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import Any, Callable, List

import numpy as np

from BT.position_handler import PositionHandler
from BT.query_order import QueryOrder
from BT.query_portfolio import ResolvedQueryPosition
from BT.triggers import Trigger
from Query.Base.BaseQuery import BaseQuery
from RVUtils.BasisVsVol.bachelier import normal_delta, normal_price, normal_vega

__all__ = ["BasisVsVolPositionHandler"]


def _leg(surf, K_bp: float, tte: float):
    F = surf.forward_bp
    sig = surf.vol(tte, K_bp - F)
    if not np.isfinite(sig) or sig <= 0 or tte <= 0:
        return np.nan, np.nan, np.nan, np.nan
    return (sig,
            float(normal_price(F, K_bp, sig, tte, w=1)),
            float(normal_delta(F, K_bp, sig, tte, w=1)),
            float(normal_vega(F, K_bp, sig, tte)))


class BasisVsVolPositionHandler(PositionHandler):
    name = "basis_vs_vol"

    def supports(self, query: BaseQuery) -> bool:
        return getattr(query, "product", None) == "BASISVSVOL"

    # ------------------------------------------------------------------ open
    def build_position(self, order: QueryOrder, pricer_provider, now, backtest) -> ResolvedQueryPosition:
        q = order.query
        snap = pricer_provider(q)
        if snap is None:
            raise ValueError(f"no snapshot for {q.ustf_product}/{q.tail} at {now}")

        tte0 = float(max(snap.ustf.min_node_tte, snap.swpt.min_node_tte))
        # open at the labelled slot's own maturity where it is on support
        node = min((n.tte for n in snap.ustf.nodes
                    if abs(n.tte - _label_years(q.expiry_label)) < 0.02), default=None)
        tte0 = float(node) if node else float(_label_years(q.expiry_label))

        K_u = snap.ustf.forward_bp + q.offset_bps
        K_s = snap.swpt.forward_bp + q.offset_bps
        vu, pu, du, gu = _leg(snap.ustf, K_u, tte0)
        vs, ps, ds, gs = _leg(snap.swpt, K_s, tte0)
        if not all(np.isfinite(x) for x in (pu, ps, gu, gs)) or gu <= 0 or gs <= 0:
            raise ValueError("pair not priceable at open")

        meta = {
            **(order.meta or {}), "handler": self.name,
            "K_u": K_u, "K_s": K_s, "tte0": tte0, "opened_on": _d(now),
            "dv01_u": q.target_vega_usd / gu, "dv01_s": q.target_vega_usd / gs,
            "prev_pu": pu, "prev_ps": ps, "prev_du": du, "prev_ds": ds,
            "prev_F_u": snap.ustf.forward_bp, "prev_F_s": snap.swpt.forward_bp,
            "contract": snap.underlying_contract, "side": int(q.side),
            "prev_mark": _d(now),
            "target_vega_usd": q.target_vega_usd, "cum_pnl": 0.0, "last_hedge": _d(now),
        }
        return ResolvedQueryPosition(package=[], weights=[], opened=now, source_query=q, meta=meta)

    # ------------------------------------------------------------------ mark
    def value_position(self, position, pricer_provider, now, backtest) -> float:
        return 0.0  # everything is realized daily; see module docstring

    def _step_pnl(self, position, pricer_provider, now):
        q = position.source_query
        m = position.meta
        snap = pricer_provider(q)
        if snap is None:
            return 0.0, m
        tte = m["tte0"] - (_d(now) - m["opened_on"]).days / 365.0
        if tte <= 0:
            return 0.0, m
        vu, pu, du, _ = _leg(snap.ustf, m["K_u"], tte)
        vs, ps, ds, _ = _leg(snap.swpt, m["K_s"], tte)
        if not (np.isfinite(pu) and np.isfinite(ps)):
            return 0.0, m
        if snap.underlying_contract != m["contract"]:
            return 0.0, m  # a roll is not a return; the runner closes the position here
        if (_d(now) - m["prev_mark"]).days > q.max_gap_days:
            # The futures-option leg has holes up to 80 days. A position cannot be hedged through
            # one, so the move across it is not P&L this book could have earned. Re-anchor the
            # marks and claim nothing -- the same rule the reference engine applies.
            return 0.0, {**m, "prev_pu": pu, "prev_ps": ps, "prev_du": du, "prev_ds": ds,
                         "prev_F_u": snap.ustf.forward_bp, "prev_F_s": snap.swpt.forward_bp,
                         "prev_mark": _d(now)}

        hedged = q.rehedge_days > 0
        dpu = (pu - m["prev_pu"]) - (m["prev_du"] * (snap.ustf.forward_bp - m["prev_F_u"]) if hedged else 0.0)
        dps = (ps - m["prev_ps"]) - (m["prev_ds"] * (snap.swpt.forward_bp - m["prev_F_s"]) if hedged else 0.0)
        gross = m["side"] * (m["dv01_s"] * dps - m["dv01_u"] * dpu)

        cost = 0.0
        if hedged and (_d(now) - m["last_hedge"]).days >= q.rehedge_days:
            cost = q.cost_mult * q.hedge_cost_bp * (
                abs(m["dv01_u"] * m["prev_du"]) + abs(m["dv01_s"] * m["prev_ds"])) / 100.0

        new = {**m, "prev_pu": pu, "prev_ps": ps, "prev_du": du, "prev_ds": ds,
               "prev_F_u": snap.ustf.forward_bp, "prev_F_s": snap.swpt.forward_bp,
               "prev_mark": _d(now), "cum_pnl": m["cum_pnl"] + gross - cost}
        if cost:
            new["last_hedge"] = _d(now)
        return gross - cost, new

    def on_mark(self, position, pricer_provider, now, backtest, auto_roll=False):
        pnl, new_meta = self._step_pnl(position, pricer_provider, now)
        return replace(position, meta=new_meta), float(pnl), []

    def on_unwind(self, position, pricer_provider, now, backtest):
        pnl, _ = self._step_pnl(position, pricer_provider, now)
        return float(pnl), []


def _d(x) -> datetime.date:
    return x.date() if isinstance(x, datetime.datetime) else x


def _label_years(label: str) -> float:
    return {"1M": 30 / 365, "2M": 60 / 365, "3M": 90 / 365, "6M": 180 / 365, "1Y": 1.0}.get(label, 0.25)
