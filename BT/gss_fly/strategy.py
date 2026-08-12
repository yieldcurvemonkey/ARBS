"""QueryDrivenBacktest wiring for the GSS butterfly book.

The book is genuinely stateful — whether a fly is entered today depends on whether it is already
held, on how its |z| moved since yesterday, and on how far its vol-scaled signal has decayed — so
this is built on :class:`~BT.triggers.FlowSignalTriggerRequirements` rather than a precomputed
table of dated triggers. One trigger evaluates the whole book each grid step and emits both the
entries and the exits for that step.

Financing is **not** re-implemented here. ARBS's :class:`FinancedFixedRateBondHandler` already
prices repo per leg from a GC curve plus per-leg specialness on ACT/360, so the repo hurdle GSS
approximated with a flat ``-(r/360)·days`` is handed to the engine instead, through
``query.meta["financing"]``.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from BT.event import TriggerInfo
from BT.gss_fly.config import GSSConfig
from BT.gss_fly.costs import RepoCurve, fly_tcost_bp
from BT.gss_fly.data import CurvePanel, apply_universe_filter
from BT.gss_fly.flies import FlyState, build_fly_state, scan_flies
from BT.query_order import QueryOrder, UnwindOrder
from BT.triggers import FlowSignalTriggerRequirements, Trigger
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondStructure import FixedRateBondStructure
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

logger = logging.getLogger(__name__)

__all__ = ["GSSSignalEngine", "GSSEntryAction", "GSSExitAction", "build_gss_trigger", "OpenFly"]


@dataclass
class OpenFly:
    tag: str
    fly_id: str
    legs: List[str]
    weights: List[float]
    entered: pd.Timestamp
    entry_z: float
    entry_zsig_bp: float
    entry_fly_yield_bp: float
    rt_cost_bp: float
    ttms: List[float]


class GSSSignalEngine:
    """One evaluation of the whole book per grid step.

    Returns ``(fired, {"entries": [...], "exits": [...]})``. ``entries`` carry everything the
    order factory needs; ``exits`` carry a tag and the exit-side cost.
    """

    def __init__(
        self,
        panel: CurvePanel,
        signal_frame: pd.DataFrame,
        cfg: Optional[GSSConfig] = None,
        *,
        repo_curve: Optional[RepoCurve] = None,
        repo_tenor: str = "ON",
    ):
        self.panel = panel
        self.signal = signal_frame
        self.cfg = cfg or GSSConfig()
        self.repo_curve = repo_curve
        self.repo_tenor = repo_tenor

        self.open: Dict[str, OpenFly] = {}
        self.closed_at: Dict[str, pd.Timestamp] = {}
        self.log: List[dict] = []
        self._seq = 0

    # -- helpers ----------------------------------------------------------
    def _gc_rate_series(self) -> Optional[pd.Series]:
        if self.repo_curve is None:
            return None
        col = self.repo_tenor.upper()
        if col not in self.repo_curve.frame.columns:
            return None
        return self.repo_curve.frame[col].dropna()

    def _cooldown_ok(self, fly_id: str, now: pd.Timestamp) -> bool:
        last = self.closed_at.get(fly_id)
        if last is None:
            return True
        return (now - last).days >= self.cfg.backtest.reentry_cooldown_days

    def _eligible_curve(self, now: pd.Timestamp) -> pd.DataFrame:
        curve = self.panel.curve_on(now)
        if curve.empty:
            return curve
        curve = curve.rename(columns={"s2c": "_s2c"})
        if now in self.signal.index:
            curve["signal"] = self.signal.loc[now].reindex(curve.index)
        else:
            curve["signal"] = np.nan
        return apply_universe_filter(curve, self.cfg.universe)

    # -- the per-step evaluation ------------------------------------------
    def __call__(self, state, backtest=None):
        now = pd.Timestamp(state)
        bt = self.cfg.backtest
        entries: List[dict] = []
        exits: List[dict] = []

        # 1. exits first, so a freed slot can be refilled on the same step.
        for tag, pos in list(self.open.items()):
            st = build_fly_state(
                pos.fly_id,
                pos.legs,
                pos.weights,
                s2c_panel=self.panel.s2c,
                yield_panel=self.panel.ytm,
                ttms=pos.ttms,
                asof=now,
                cfg=self.cfg.fly,
                sign_by_z=False,  # the held position keeps the weights it was entered with
            )
            if st is None:
                continue
            decayed = st.zsig_bp <= self.cfg.costs.repo_penalty_bp
            rolled_over = (abs(st.z) < bt.exit_abs_z) and (np.isfinite(st.d_abs_z) and st.d_abs_z > 0)
            if decayed or rolled_over:
                exits.append(
                    {
                        "tag": tag,
                        "fly_id": pos.fly_id,
                        "reason": "zsig_below_repo" if decayed else "z_rollover",
                        "fee_bp": pos.rt_cost_bp / 2.0,
                        "zsig_bp": st.zsig_bp,
                        "z": st.z,
                    }
                )
                self.closed_at[pos.fly_id] = now
                self.log.append(
                    {
                        "date": now,
                        "event": "EXIT",
                        "tag": tag,
                        "fly_id": pos.fly_id,
                        "reason": exits[-1]["reason"],
                        "z": st.z,
                        "zsig_bp": st.zsig_bp,
                        "held_days": (now - pos.entered).days,
                    }
                )
                del self.open[tag]

        # 2. entries, ranked by the vol-scaled signal.
        slots = bt.max_concurrent - len(self.open)
        if slots > 0:
            curve = self._eligible_curve(now)
            if not curve.empty and curve["signal"].notna().any():
                held_ids = {p.fly_id for p in self.open.values()}
                held_legs = {leg for p in self.open.values() for leg in p.legs}
                candidates = scan_flies(
                    curve,
                    s2c_panel=self.panel.s2c,
                    yield_panel=self.panel.ytm,
                    asof=now,
                    cfg=self.cfg.fly,
                )
                gated = [
                    st
                    for st in candidates
                    if st.zsig_bp > bt.entry_zsig_bp
                    and (not bt.require_turning_point or (np.isfinite(st.d_abs_z) and st.d_abs_z < 0))
                    and st.fly_id not in held_ids
                    and self._cooldown_ok(st.fly_id, now)
                    and not (set(st.legs) & held_legs)  # no bond in two live flies at once
                ]
                gated.sort(key=lambda s: s.zsig_bp, reverse=True)

                for st in gated:
                    if slots <= 0:
                        break
                    # Re-check the overlap here, not only in the filter above: `gated` is built
                    # in one pass, so two candidates in the SAME batch can share a leg even though
                    # neither overlaps anything already held. Taking both would double the real
                    # position in that bond while the book records two independent flies.
                    if set(st.legs) & held_legs:
                        continue
                    slots -= 1
                    self._seq += 1
                    tag = f"gss{self._seq:05d}"
                    rt = 2.0 * fly_tcost_bp(st.ttms, st.weights, self.cfg.costs)
                    entries.append({"tag": tag, "state": st, "rt_cost_bp": rt})
                    self.open[tag] = OpenFly(
                        tag=tag,
                        fly_id=st.fly_id,
                        legs=list(st.legs),
                        weights=list(st.weights),
                        entered=now,
                        entry_z=st.z,
                        entry_zsig_bp=st.zsig_bp,
                        entry_fly_yield_bp=st.fly_yield_bp,
                        rt_cost_bp=rt,
                        ttms=list(st.ttms),
                    )
                    held_legs.update(st.legs)
                    self.log.append(
                        {
                            "date": now,
                            "event": "ENTER",
                            "tag": tag,
                            "fly_id": st.fly_id,
                            "z": st.z,
                            "zsig_bp": st.zsig_bp,
                            "std_bp": st.std_bp,
                            "d_abs_z": st.d_abs_z,
                            "rt_cost_bp": rt,
                            "weights": list(st.weights),
                            "ttms": list(st.ttms),
                        }
                    )

        fired = bool(entries or exits)
        return TriggerInfo(fired, {"entries": entries, "exits": exits, "engine": self})


@dataclass
class GSSEntryAction:
    """Build one ``FixedRateBondQuery`` FLY per entry the engine emitted."""

    cfg: GSSConfig
    gc_rate: Any = None
    leg_specialness_bps: Dict[str, float] = field(default_factory=dict)
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        orders: List[QueryOrder] = []
        for e in (info or {}).get("entries", []):
            st: FlyState = e["state"]
            meta: Dict[str, Any] = {"action": "gss_enter", "tags": [e["tag"]], "fly_id": st.fly_id}
            q_meta: Dict[str, Any] = {}
            if self.gc_rate is not None:
                q_meta["financing"] = {
                    "mode": "gc_plus_specialness",
                    "gc_rate": self.gc_rate,
                    "leg_specialness_bps": dict(self.leg_specialness_bps),
                    "day_count": "ACT/360",
                    "haircut": 0.0,
                }
            q = FixedRateBondQuery(
                structure=FixedRateBondStructure.FLY,
                value=FixedRateBondValue.NPV,
                cusip="/".join(st.legs),
                structure_kwargs={
                    "risk_weights": list(st.weights),
                    "bpv": self.cfg.backtest.belly_bpv,
                },
                tags=(e["tag"],),
                meta=q_meta,
            )
            orders.append(QueryOrder(timestamp=now, query=q, meta=meta))
        return orders


@dataclass
class GSSExitAction:
    """Emit an ``UnwindOrder`` per exit, carrying the exit-side cost as the engine's only fee hook."""

    cfg: GSSConfig
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        orders: List[UnwindOrder] = []
        for x in (info or {}).get("exits", []):
            tag = x["tag"]

            def _pred(pos, _tag=tag):
                tags = set(pos.meta.get("tags", []) or [])
                tags.update(getattr(pos.source_query, "tags", ()) or ())
                return _tag in tags

            fee = float(x.get("fee_bp", 0.0)) * self.cfg.backtest.belly_bpv
            orders.append(
                UnwindOrder(
                    timestamp=now,
                    selector=_pred,
                    meta={"action": "gss_exit", "fee": fee, "reason": x.get("reason"), "tag": tag},
                )
            )
        return orders


def build_gss_trigger(
    engine: GSSSignalEngine,
    *,
    gc_rate: Any = None,
    leg_specialness_bps: Optional[Dict[str, float]] = None,
) -> Trigger:
    """One trigger, two actions: everything the book does on a step."""
    return Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(signal_fn=engine),
        actions=[
            GSSEntryAction(cfg=engine.cfg, gc_rate=gc_rate, leg_specialness_bps=leg_specialness_bps or {}),
            GSSExitAction(cfg=engine.cfg),
        ],
    )
