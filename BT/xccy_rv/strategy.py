"""QueryDrivenBacktest wiring for the cross-currency basis book.

The allocation is genuinely path-dependent — the target holding depends on yesterday's holding
through the transaction-cost term — so this is a :class:`~BT.triggers.FlowSignalTriggerRequirements`
evaluated on every grid step, not a precomputed trade list.

Two allocators, one problem. With a diagonal covariance and no constraints (the original's shipped
configuration) the mean-variance QP separates per asset and has an exact closed form: a no-trade
band around the previous holding,

    h* = (α ∓ c)/(λσ²)  outside the band,   h_prev inside it,     c = tcost_aversion · tcost

That is what :func:`no_trade_band` computes, and it is the *same optimum* the QP would return —
not an approximation — while also working for a single instrument, which the QP refuses. The
ported cvxopt optimizer is used instead when a full covariance or constraints are wanted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from BT.event import TriggerInfo
from BT.query_order import QueryOrder, UnwindOrder
from BT.triggers import FlowSignalTriggerRequirements, Trigger
from BT.xccy_rv.config import XccyConfig
from BT.xccy_rv.product import XccyBasisQuery, XccyBasisStructure, XccyBasisValue

logger = logging.getLogger(__name__)

__all__ = ["no_trade_band_step", "XccyAllocator", "XccyRebalanceAction", "XccyUnwindAction", "build_xccy_trigger"]


def no_trade_band_step(alpha: float, var: float, prev: float, lam: float, cost: float) -> float:
    """One period of ``max α·h − (λ/2)·var·h² − cost·|h − prev|``.

    Exact, not iterative: the objective is piecewise quadratic in one variable, so the optimum is
    the unconstrained solution shifted by the cost, or the previous holding if the gradient at
    ``prev`` is inside ``[-cost, +cost]``.
    """
    if not (np.isfinite(alpha) and np.isfinite(var)) or var <= 0:
        return prev
    grad = alpha - lam * var * prev
    if grad > cost:
        return (alpha - cost) / (lam * var)
    if grad < -cost:
        return (alpha + cost) / (lam * var)
    return prev


class XccyAllocator:
    """Per-step target holdings, and the orders needed to get there."""

    def __init__(self, alpha: pd.DataFrame, vol: pd.DataFrame, cfg: Optional[XccyConfig] = None,
                 carry: Optional[pd.DataFrame] = None):
        self.alpha = alpha
        self.vol = vol
        self.carry = carry
        self.cfg = cfg or XccyConfig()
        self.holdings: Dict[str, float] = {}
        self.open_tags: Dict[str, str] = {}
        self.log: List[dict] = []
        self._seq = 0
        self._step = 0

    def targets(self, now: pd.Timestamp) -> Dict[str, float]:
        o = self.cfg.optimizer
        cost = o.transaction_cost_aversion * o.transaction_costs
        out: Dict[str, float] = {}
        if now not in self.alpha.index:
            return dict(self.holdings)
        a_row, v_row = self.alpha.loc[now], self.vol.loc[now]
        for inst in self.alpha.columns:
            prev = self.holdings.get(inst, 0.0)
            out[inst] = no_trade_band_step(
                float(a_row.get(inst, np.nan)),
                float(v_row.get(inst, np.nan)) ** 2,
                prev,
                o.risk_aversion,
                cost,
            )
        return out

    def __call__(self, state, backtest=None):
        now = pd.Timestamp(state)
        self._step += 1
        if (self._step - 1) % max(1, self.cfg.backtest.rebalance_every) != 0:
            return TriggerInfo(False, {})

        tgt = self.targets(now)
        opens: List[dict] = []
        closes: List[dict] = []

        for inst, want in tgt.items():
            have = self.holdings.get(inst, 0.0)
            if not np.isfinite(want):
                continue
            scale = max(abs(want), abs(have), 1e-12)
            if abs(want - have) / scale < self.cfg.backtest.min_trade_fraction:
                continue

            if inst in self.open_tags:
                # The cost is on the TRADED INCREMENT, not on the position. A resize is expressed
                # here as unwind-and-reopen because the engine has no partial-resize primitive, so
                # charging |have| would bill the whole book on every rebalance -- which on this
                # panel came to $624m of fees against $47k of gross P&L before it was caught.
                closes.append(
                    {"tag": self.open_tags.pop(inst), "instrument": inst,
                     "from": have, "traded": abs(want - have)}
                )
            if abs(want) > 1e-12:
                self._seq += 1
                tag = f"xc{self._seq:05d}"
                self.open_tags[inst] = tag
                c_bp = 0.0
                if self.carry is not None and now in self.carry.index:
                    v = self.carry.loc[now].get(inst, np.nan)
                    c_bp = float(v) if np.isfinite(v) else 0.0
                opens.append({"tag": tag, "instrument": inst, "holding": want, "carry_bp": c_bp})
            self.holdings[inst] = want
            self.log.append(
                {"date": now, "instrument": inst, "from": have, "to": want,
                 "alpha": float(self.alpha.loc[now].get(inst, np.nan))}
            )

        return TriggerInfo(bool(opens or closes), {"opens": opens, "closes": closes})


@dataclass
class XccyRebalanceAction:
    cfg: XccyConfig
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        orders: List[QueryOrder] = []
        for o in (info or {}).get("opens", []):
            h = float(o["holding"])
            q = XccyBasisQuery(
                instrument=o["instrument"],
                structure=XccyBasisStructure.OUTRIGHT,
                value=XccyBasisValue.NPV,
                structure_kwargs={
                    "instrument": o["instrument"],
                    "dv01": abs(h) * self.cfg.backtest.dv01_per_unit,   # notional/1e4 -> $ per bp
                    "direction": float(np.sign(h)),
                    "carry_bp_per_year": float(o.get("carry_bp", 0.0)),
                },
                tags=(o["tag"],),
            )
            orders.append(
                QueryOrder(timestamp=now, query=q, meta={"action": "xccy_rebalance", "tags": [o["tag"]]})
            )
        return orders


@dataclass
class XccyUnwindAction:
    cfg: XccyConfig
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        orders: List[UnwindOrder] = []
        for c in (info or {}).get("closes", []):
            tag = c["tag"]

            def _pred(pos, _tag=tag):
                tags = set(pos.meta.get("tags", []) or [])
                tags.update(getattr(pos.source_query, "tags", ()) or ())
                return _tag in tags

            traded = c.get("traded")
            if traded is None:  # a genuine close-out trades the whole position
                traded = abs(float(c.get("from", 0.0)))
            # notional x cost-in-bp x 1e-4 == the panel's ``transaction_costs * turnover`` in
            # decimal-return space, scaled by the same notional. The two must agree or the engine
            # and the tie-out are charging different books.
            fee = (
                abs(float(traded))
                * self.cfg.backtest.notional_per_unit
                * self.cfg.backtest.round_trip_bp
                * 1e-4
            )
            orders.append(
                UnwindOrder(timestamp=now, selector=_pred, meta={"action": "xccy_unwind", "fee": fee, "tag": tag})
            )
        return orders


def build_xccy_trigger(allocator: XccyAllocator) -> Trigger:
    return Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(signal_fn=allocator),
        actions=[XccyRebalanceAction(cfg=allocator.cfg), XccyUnwindAction(cfg=allocator.cfg)],
    )
