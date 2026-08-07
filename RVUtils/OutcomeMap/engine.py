"""The trade loop: fixed-leg cell packages, lag-1 entries, a linear hedge leg.

One open package per symbol. Legs are frozen on the signal day (the signal
column carries them), marks are LISTED premiums, and the exit signal is the same
package's richness recomputed daily against the lattice — so "convergence" means
the package we actually hold converged, not that an idealised one did.

The linear leg is optional and its bill is tracked separately from the option
leg's at every step, because the question this study exists to answer is
precisely whether that bill is worth paying.
"""
from __future__ import annotations

import dataclasses
import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.OutcomeMap.hedge import (
    linear_leg_cost_bp, option_leg_cost_bp, zq_basket_contracts)
from RVUtils.OutcomeMap.structures import package_contracts

__all__ = ["HedgeContext", "OutcomeTrade", "run_outcome_backtest"]

Leg = Tuple[str, float, float]


@dataclasses.dataclass
class HedgeContext:
    """Everything the linear leg needs for one open package.

    ``ratios(outcomes)`` returns ``h`` (bp of package per bp of each meeting's
    jump) with resolved meetings pinned; ``effectives`` and ``supports`` line the
    vector up with the jump marks and let a resolution be read off the last jump.
    """

    effectives: Tuple[datetime.date, ...]
    supports: Tuple[Tuple[int, int], ...]
    ratios: Callable[[Dict[int, int]], np.ndarray]


@dataclasses.dataclass
class OutcomeTrade:
    symbol: str
    expression: str
    entry: pd.Timestamp
    exit: pd.Timestamp
    side: int                      # +1 = hold the package as constructed
    n_contracts: float
    entry_mark_bp: float
    exit_mark_bp: float
    entry_signal_bp: float         # |package richness| at entry
    exit_signal_bp: float
    opt_gross_bp: float
    hedge_bp: float
    opt_cost_bp: float
    lin_cost_bp: float
    lin_contracts: float
    n_rebalances: int
    exit_reason: str
    daily: pd.Series
    meta: dict

    @property
    def gross_bp(self) -> float:
        return self.opt_gross_bp + self.hedge_bp

    @property
    def cost_bp(self) -> float:
        return self.opt_cost_bp + self.lin_cost_bp

    @property
    def net_bp(self) -> float:
        return self.gross_bp - self.cost_bp

    def net_at(self, mult: float) -> float:
        return self.gross_bp - mult * self.cost_bp


def _resolve_outcome(last_jump: float, support: Tuple[int, int]) -> int:
    a, b = support
    return a if abs(last_jump - a * 25.0) <= abs(last_jump - b * 25.0) else b


def run_outcome_backtest(
    entries: pd.DataFrame,
    mark_fn: Callable[[pd.Timestamp, object], float],
    signal_fn: Callable[[pd.Timestamp, object], float],
    all_dates: pd.DatetimeIndex,
    *,
    direction: str = "fade",
    lag: int = 1,
    threshold_bp: float = 0.0,
    exit_rule: str = "converge",
    exit_frac: float = 0.5,
    max_hold: int = 15,
    dte_floor: int = 3,
    linear_leg: str = "none",
    hedge_ctx_fn: Optional[Callable[[pd.Timestamp, str, Sequence[Leg]],
                                    Optional[HedgeContext]]] = None,
    jump_fn: Optional[Callable[[pd.Timestamp, datetime.date], float]] = None,
    cost_mult: float = 1.0,
    contracts_fn: Optional[Callable[[object], float]] = None,
    expiry_fn: Optional[Callable[[str], datetime.date]] = None,
    decision_after_fn: Optional[Callable[[pd.Timestamp], pd.Timestamp]] = None,
) -> List[OutcomeTrade]:
    """Run one config over a signal frame.

    ``entries`` columns: ``as_of``, ``symbol``, ``legs``, ``strength_bp``, and
    any meta (the contract count is derived from the legs). ``exit_rule`` is
    ``converge`` (half the entry signal), ``hold`` (``max_hold`` sessions) or
    ``decision`` (the session after the next FOMC decision, via
    ``decision_after_fn``).

    ``signal_fn(as_of, row) -> float`` must return the SAME object the entry
    rule selected on — for an odd-component expression that is the package's
    richness with the standing premium projected out, not its raw richness.
    Exiting on a different signal from the one you entered on is how a
    convergence trade silently becomes a dispersion trade.
    """
    if entries.empty:
        return []
    sig = entries.copy()
    sig["as_of"] = pd.to_datetime(sig["as_of"])
    sig = sig.sort_values("as_of")
    side_base = 1 if direction == "fade" else -1

    trades: List[OutcomeTrade] = []
    open_until: Dict[str, pd.Timestamp] = {}

    for _, row in sig.iterrows():
        sym = str(row["symbol"])
        d_sig = pd.Timestamp(row["as_of"])
        if sym in open_until and d_sig <= open_until[sym]:
            continue
        if float(row["strength_bp"]) < threshold_bp:
            continue
        later = all_dates[all_dates > d_sig]
        if len(later) < lag:
            continue
        d_entry = later[lag - 1]
        legs = list(row["legs"])
        m0 = mark_fn(d_entry, row)
        sig0 = signal_fn(d_entry, row)
        if not (np.isfinite(m0) and np.isfinite(sig0)):
            continue
        if abs(sig0) < 1e-9:                 # negative by construction:
            continue                         # long the cheap cell, short the rich

        side = side_base
        # the contract bill is a property of the LEGS (netted), never of a
        # caller-supplied column: a multi-cell book telescopes, and costing the
        # un-netted legs would overstate every map expression's bill. A
        # package spanning two expiries nets PER EXPIRY, which only the caller
        # knows how to do — hence contracts_fn, still computed from legs.
        n_con = (package_contracts(legs) if contracts_fn is None
                 else float(contracts_fn(row)))

        # --- hedge context -------------------------------------------------
        ctx = None
        if linear_leg != "none" and hedge_ctx_fn is not None:
            ctx = hedge_ctx_fn(d_entry, sym, legs)
        outcomes: Dict[int, int] = {}
        h = ctx.ratios(outcomes) if ctx is not None else np.zeros(0)
        lin_con = zq_basket_contracts(h) if ctx is not None else 0.0
        lin_con0 = lin_con
        prev_jump: Dict[datetime.date, float] = {}
        if ctx is not None and jump_fn is not None:
            for eff in ctx.effectives:
                v = jump_fn(d_entry, eff)
                if np.isfinite(v):
                    prev_jump[eff] = float(v)

        # --- schedule ------------------------------------------------------
        hard = later[min(lag - 1 + max_hold, len(later) - 1)]
        if expiry_fn is not None:
            xp = pd.Timestamp(expiry_fn(sym)) - pd.Timedelta(days=dte_floor)
            hard = min(hard, xp)
        if exit_rule == "decision" and decision_after_fn is not None:
            dec = decision_after_fn(d_entry)
            if dec is not None:
                nxt = all_dates[all_dates > pd.Timestamp(dec)]
                if len(nxt):
                    hard = min(hard, nxt[0])

        opt_half = option_leg_cost_bp(n_con, 1, mult=cost_mult)
        lin_half = (linear_leg_cost_bp(lin_con, 1, mult=cost_mult)
                    if ctx is not None else 0.0)

        daily: Dict[pd.Timestamp, float] = {d_entry: -(opt_half + lin_half)}
        prev_mark = m0
        hedge_pnl = 0.0
        n_reb = 0
        reb_cost = 0.0
        exit_reason, d_exit, last_sig = "eod", d_entry, sig0

        for dt in all_dates[all_dates > d_entry]:
            step = 0.0
            # meetings that have resolved re-ratio the basket (and cost a side)
            if ctx is not None:
                for j, eff in enumerate(ctx.effectives):
                    if j in outcomes or eff > dt.date():
                        continue
                    outcomes[j] = _resolve_outcome(
                        prev_jump.get(eff, 0.0), ctx.supports[j])
                    h = ctx.ratios(outcomes)
                    lin_con = zq_basket_contracts(h)
                    n_reb += 1
                    c_reb = linear_leg_cost_bp(lin_con, 1, mult=cost_mult)
                    reb_cost += c_reb
                    step -= c_reb
                if jump_fn is not None:
                    for j, eff in enumerate(ctx.effectives):
                        if j in outcomes:
                            continue
                        jn = jump_fn(dt, eff)
                        if not np.isfinite(jn):
                            continue
                        jo = prev_jump.get(eff)
                        if jo is not None and j < len(h):
                            d_hedge = -side * float(h[j]) * (float(jn) - jo)
                            hedge_pnl += d_hedge
                            step += d_hedge
                        prev_jump[eff] = float(jn)

            mk = mark_fn(dt, row)
            if np.isfinite(mk):
                step += side * (mk - prev_mark)
                prev_mark = float(mk)
                sv = signal_fn(dt, row)
                if np.isfinite(sv):
                    last_sig = float(sv)
            daily[dt] = daily.get(dt, 0.0) + step
            d_exit = dt

            if exit_rule == "converge" and abs(last_sig) <= exit_frac * abs(sig0):
                exit_reason = "converged"
                break
            if dt >= hard:
                exit_reason = ("decision" if exit_rule == "decision"
                               else "time_stop")
                break

        # unwind the basket at its CURRENT size: meetings that resolved were
        # already re-ratioed (and charged) mid-trade, so charging the entry
        # size again at exit would double-count them
        lin_exit_half = (linear_leg_cost_bp(lin_con, 1, mult=cost_mult)
                         if ctx is not None else 0.0)
        daily[d_exit] = daily.get(d_exit, 0.0) - (opt_half + lin_exit_half)
        dser = pd.Series(daily).sort_index()
        opt_gross = side * (prev_mark - m0)
        opt_cost = 2.0 * opt_half
        lin_cost = lin_half + lin_exit_half + reb_cost
        trades.append(OutcomeTrade(
            symbol=sym, expression=str(row.get("expression", "")),
            entry=d_entry, exit=pd.Timestamp(d_exit), side=side,
            n_contracts=n_con, entry_mark_bp=float(m0),
            exit_mark_bp=float(prev_mark), entry_signal_bp=float(sig0),
            exit_signal_bp=float(last_sig), opt_gross_bp=float(opt_gross),
            hedge_bp=float(hedge_pnl), opt_cost_bp=float(opt_cost),
            lin_cost_bp=float(lin_cost), lin_contracts=float(lin_con0),
            n_rebalances=int(n_reb), exit_reason=exit_reason, daily=dser,
            meta={k: row[k] for k in row.index
                  if k not in ("as_of", "symbol", "legs")},
        ))
        open_until[sym] = pd.Timestamp(d_exit)
    return trades
