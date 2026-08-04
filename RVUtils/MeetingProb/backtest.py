"""Channel-1 backtest: listed SR3 boundary verticals hedged with the ZQ ladder.

The tradeable expression of a per-meeting probability gap:

* **SR3 leg**: the listed vertical bracketing the signal boundary, scaled to
  one probability unit (``100/width`` of premium bp per unit), marked from
  LISTED premiums only.
* **Hedge leg**: the FedWatch ladder's per-meeting jump estimates are linear
  combinations of ZQ monthly averages, so "h_m units of meeting m's jump" is a
  fixed-weight ZQ basket. Hedge P&L in probability-unit bp is
  ``-h_m * d(jump_m)`` summed over unresolved meetings, with ``h_m`` the tree's
  digital sensitivity per bp of jump.
* **Multilinearity**: the tree value is multilinear in the per-meeting P's and
  P is linear in the jump on a fixed support, so ``h`` is constant between
  meeting resolutions; the hedge is recomputed (and a rebalance charged) when a
  meeting resolves. Support migration (a jump crossing a 25bp characteristic)
  also technically re-ratios the hedge; it is NOT re-charged here, which
  understates costs by at most one ZQ rebalance per migration — stated rather
  than hidden.
* **Off-lattice risk stays**: a >25bp surprise or an intermeeting move breaks
  the replication. No cost scenario prices that tail; the trade log carries the
  realized outcome so the tail shows up as P&L, not as an assumption.

Inputs are plain frames so every path is testable on planted numbers.
"""
from __future__ import annotations

import dataclasses
import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.MeetingProb.atoms import ContractMeetings, atom_distribution
from RVUtils.MeetingProb.pricer import digital_prob

__all__ = ["hedge_ratios", "run_channel1_backtest", "package_cost_bp",
           "SR3_DV01", "ZQ_DV01"]

SR3_DV01 = 25.0
ZQ_DV01 = 41.67
SR3_HALF_TICK_BP = 0.125          # one way, bp of SR3 price
ZQ_HALF_TICK_BP = 0.25            # one way, bp of ZQ's own rate
ZQ_LEGS_PER_MEETING = 3           # bracketing-months basket


def hedge_ratios(
    cm: ContractMeetings,
    forward_rate: float,
    boundary_rate: float,
    smear_bp: float,
    *,
    q: Optional[np.ndarray] = None,
    outcomes: Optional[Dict[int, int]] = None,
    bump_bp: float = 1.0,
) -> np.ndarray:
    """d(tree digital P(rate >= boundary)) / d(jump_m), per bp of jump.

    Meetings already resolved (``outcomes``: index -> realized move count) are
    frozen at their outcome and carry zero ratio. The bump runs through the
    mantissa slope ``1/(25 * |support span|)``.
    """
    from RVUtils.MeetingProb.atoms import AtomEngine

    q_ref = np.array([r.q_zq for r in cm.resolved], dtype=float)
    q0 = q_ref.copy() if q is None else np.asarray(q, dtype=float).copy()
    fixed = outcomes or {}
    for i, n in fixed.items():
        a, b = cm.resolved[i].support
        q0[i] = 0.0 if n == a else 1.0

    # FRAME-FROZEN evaluation (q_ref = the entry-day reference): absolute atom
    # rates are constant, only probabilities move, so the digital is exactly
    # multilinear in q and the per-meeting linear hedge replicates on-lattice.
    engine = AtomEngine(cm)

    def value(qv: np.ndarray) -> float:
        rates, probs = engine.rates_probs(forward_rate, q=qv, q_ref=q_ref)
        return digital_prob(rates, probs, boundary_rate, smear_bp=smear_bp)

    out = np.zeros(len(q0))
    for i, r in enumerate(cm.resolved):
        if i in fixed:
            continue
        span = abs(r.support[1] - r.support[0]) * 25.0
        if span <= 0:
            continue
        dq = min(bump_bp / span, 0.49)
        hi, lo = q0.copy(), q0.copy()
        hi[i] = min(q0[i] + dq, 1.0)
        lo[i] = max(q0[i] - dq, 0.0)
        if hi[i] <= lo[i]:
            continue
        out[i] = (value(hi) - value(lo)) / ((hi[i] - lo[i]) * span)
    return out


def package_cost_bp(
    n_rebalances: int,
    zq_contracts_per_unit: float,
    *,
    vertical_width_bp: float,
    sr3_half_tick_bp: float = SR3_HALF_TICK_BP,
    zq_half_tick_bp: float = ZQ_HALF_TICK_BP,
) -> float:
    """Round trip in bp of one probability unit (a 100bp-notional digital).

    One unit trades ``100/width`` lots per SR3 leg, two legs, both ways:
    ``2 legs x (100/width) lots x half_tick x 2 sides``. ZQ legs pay in their
    own bp times the DV01 ratio, once per rebalance on the traded delta.
    """
    sr3_lots = 100.0 / max(vertical_width_bp, 1e-9)
    sr3 = 2.0 * sr3_lots * sr3_half_tick_bp * 2.0
    zq = (n_rebalances * zq_contracts_per_unit * zq_half_tick_bp
          * (ZQ_DV01 / SR3_DV01))
    return sr3 + zq


@dataclasses.dataclass
class Channel1Trade:
    symbol: str
    boundary_rate: float
    entry: pd.Timestamp
    exit: pd.Timestamp
    direction: int                 # +1 long the listed digital
    entry_gap: float
    gross_bp: float                # per probability unit, signed, incl. hedge
    hedge_bp: float
    cost_bp: float
    net_bp: float
    n_rebalances: int
    outcomes: Dict[str, int]
    exit_reason: str
    daily: pd.Series


def run_channel1_backtest(
    signals: pd.DataFrame,
    vert_marks: pd.DataFrame,
    jumps: pd.DataFrame,
    cm_lookup,
    fwd_lookup,
    *,
    entry_min_gap: float = 0.05,
    entry_min_t: float = 2.0,
    exit_frac: float = 0.25,
    lag: int = 1,
    direction: str = "fade",
    expiry_cutoff_days: int = 3,
) -> List[Channel1Trade]:
    """One open trade per contract; lag-1 entries; meeting-resolution hedging.

    Parameters
    ----------
    signals
        One row per (as_of, symbol): ``boundary_rate, width_bp, gap, gap_t,
        smear_bp, channel, gate``. The signal bar's boundary defines the trade.
    vert_marks
        Long frame (as_of, symbol, boundary_rate) -> ``unit_bp``: the listed
        vertical premium PER PROBABILITY UNIT on each date (NaN = no print).
    jumps
        Long frame (as_of, effective) -> ``jump_bp`` from the daily ladder.
    cm_lookup(date, symbol) -> ContractMeetings (as of the ENTRY date, fixed).
    fwd_lookup(date, symbol) -> forward rate at entry (hedge-ratio input).
    """
    sig = signals.copy()
    sig["as_of"] = pd.to_datetime(sig["as_of"])
    vm = vert_marks.copy()
    vm["as_of"] = pd.to_datetime(vm["as_of"])
    vm_idx = vm.set_index(["symbol", "boundary_rate", "as_of"])["unit_bp"] \
        .sort_index()
    jp = jumps.copy()
    jp["as_of"] = pd.to_datetime(jp["as_of"])
    jp_idx = jp.set_index(["as_of", "effective"])["jump_bp"].sort_index()
    all_dates = pd.DatetimeIndex(sorted(jp["as_of"].unique()))

    trades: List[Channel1Trade] = []
    for symbol, sub in sig.groupby("symbol"):
        sub = sub.sort_values("as_of").reset_index(drop=True)
        busy_until: Optional[pd.Timestamp] = None
        for _, row in sub.iterrows():
            d_sig = pd.Timestamp(row["as_of"])
            if busy_until is not None and d_sig <= busy_until:
                continue
            if not bool(row.get("gate", True)) or row.get("channel") != "channel1":
                continue
            gap = float(row["gap"])
            t = float(row.get("gap_t", np.nan))
            if abs(gap) < entry_min_gap or not np.isfinite(t) \
                    or abs(t) < entry_min_t:
                continue
            # lag on the GLOBAL trading calendar, not the signal frame's rows
            later = all_dates[all_dates > d_sig]
            if len(later) < max(lag, 1):
                continue
            d_entry = later[lag - 1] if lag >= 1 else d_sig
            cm = cm_lookup(d_entry.date(), symbol)
            if cm is None or cm.n_resolved == 0:
                continue
            key = (symbol, float(row["boundary_rate"]))
            try:
                marks = vm_idx.loc[key]
            except KeyError:
                continue
            marks = marks[marks.index >= d_entry].dropna()
            if marks.empty or marks.index[0] != d_entry:
                continue
            v0 = float(marks.iloc[0])
            side = -int(np.sign(gap)) if direction == "fade" else int(np.sign(gap))
            fwd0 = float(fwd_lookup(d_entry, symbol))
            smear = float(row["smear_bp"])
            boundary = float(row["boundary_rate"])

            h = hedge_ratios(cm, fwd0, boundary, smear)
            outcomes: Dict[int, int] = {}
            n_reb, hedge_pnl = 1, 0.0
            last_meeting = max(r.effective for r in cm.resolved)
            hard_exit = min(pd.Timestamp(last_meeting),
                            pd.Timestamp(cm.expiry)
                            - pd.Timedelta(days=expiry_cutoff_days))
            daily: Dict[pd.Timestamp, float] = {}
            prev_mark, prev_jumps = v0, {}
            for r in cm.resolved:
                try:
                    prev_jumps[r.effective] = float(jp_idx.loc[(d_entry,
                                                                r.effective)])
                except KeyError:
                    pass
            exit_reason, d_exit = "eod", d_entry
            span = all_dates[all_dates > d_entry]
            for dt in span:
                dd = dt.date()
                # resolve meetings whose effective date has passed
                for j, r in enumerate(cm.resolved):
                    if j not in outcomes and r.effective <= dd:
                        jlast = prev_jumps.get(r.effective, r.q_zq * 25.0)
                        a, b = r.support
                        outcomes[j] = a if abs(jlast - a * 25.0) <= \
                            abs(jlast - b * 25.0) else b
                        h = hedge_ratios(cm, fwd0, boundary, smear,
                                         outcomes=outcomes)
                        n_reb += 1
                # hedge P&L on unresolved meetings' jump changes
                dh = 0.0
                for j, r in enumerate(cm.resolved):
                    if j in outcomes:
                        continue
                    try:
                        jn = float(jp_idx.loc[(dt, r.effective)])
                    except KeyError:
                        continue
                    jo = prev_jumps.get(r.effective)
                    if jo is not None:
                        # h is probability per bp of jump; marks are unit_bp
                        # (probability x 100). The hedge REPLICATES the digital
                        # (long its tree exposure when short the listed one).
                        dh += -side * h[j] * (jn - jo) * 100.0
                    prev_jumps[r.effective] = jn
                hedge_pnl += dh
                # SR3 leg
                step = dh
                try:
                    v = float(vm_idx.loc[(symbol, boundary, dt)])
                except KeyError:
                    v = np.nan
                if np.isfinite(v):
                    step += side * (v - prev_mark)
                    prev_mark = v
                daily[dt] = daily.get(dt, 0.0) + step
                gross = side * (prev_mark - v0) + hedge_pnl
                if len(outcomes) == cm.n_resolved:
                    exit_reason, d_exit = "resolved", dt
                    break
                if dt >= hard_exit:
                    exit_reason, d_exit = "hard_exit", dt
                    break
                d_exit = dt
            else:
                gross = side * (prev_mark - v0) + hedge_pnl

            zq_contracts = (float(np.sum(np.abs(h))) * 25.0
                            * ZQ_LEGS_PER_MEETING * (SR3_DV01 / ZQ_DV01))
            cost = package_cost_bp(n_reb, zq_contracts,
                                   vertical_width_bp=float(row["width_bp"]))
            dser = pd.Series(daily).sort_index()
            if len(dser):
                dser.iloc[-1] -= cost
            trades.append(Channel1Trade(
                symbol=symbol, boundary_rate=boundary, entry=d_entry,
                exit=pd.Timestamp(d_exit), direction=side, entry_gap=gap,
                gross_bp=float(gross), hedge_bp=float(hedge_pnl),
                cost_bp=float(cost), net_bp=float(gross - cost),
                n_rebalances=int(n_reb),
                outcomes={cm.resolved[j].effective.isoformat(): n
                          for j, n in outcomes.items()},
                exit_reason=exit_reason, daily=dser,
            ))
            busy_until = pd.Timestamp(d_exit)
    return trades
