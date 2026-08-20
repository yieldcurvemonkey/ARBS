"""The ETF-rebalance butterfly book on QueryDrivenBacktest -- the marks layer.

What this adds over the vectorised engine
------------------------------------------
``RVUtils/ETFRebalance/engine.py`` marks a package as ``-dR`` where ``R`` is a weighted
sum of yields, plus an explicit yield-space carry term. That is fast, transparent, and
it is a model. The QDB marks the same positions at the pricer's **dirty NPV** and books
coupon cash through ``on_mark``, so it reprices the actual instruments with the actual
cashflow schedules. The two decompose the same total differently, and where they agree
the fast engine's approximations are ratified; where they disagree the difference is a
number to be explained, not averaged.

Three legs as three OUTRIGHTS, not one FLY
-------------------------------------------
The obvious construction is a single ``FixedRateBondQuery`` with
``structure=FLY``. It is a trap. ``FixedRateBondStructure._build_fly`` re-signs the whole
package from ``sign(bpv)``:

    risk_weights[1] = np.copysign(risk_weights[1], bpv)
    risk_weights[i] = np.copysign(risk_weights[i], -risk_weights[1])

so an unsigned ``bpv`` forces the belly LONG on every trade and discards the direction
the signal chose. Measured on a prior book: **15 of 35 flies entered backwards**, and the
exit rule then judged them against the opposite of the weights that opened them.

Three separate outright queries carrying **signed** ``bpv`` and a shared tag express the
identical position with no re-signing anywhere, which is how the olds-vs-currents study
ended up doing it too. A leg's ``bpv`` is ``side * w_leg``, so a belly at ``bpv = 1.0``
means one dollar per basis point and the book's P&L in dollars IS the package P&L in
basis points per unit of belly DV01 -- the same unit the vectorised engine and the cost
model both quote.

Read ``mtm_history``, never the closed log
-------------------------------------------
The engine marks bond packages at dirty NPV, so ``closed_positions_log["realized_pnl"]``
is *(exit dirty NPV - entry dirty NPV)* and contains coupon **accrual**, while the
matching coupon **cash** is booked on a different path (``on_mark`` ->
``backtest.realized_pnl``) and reaches no closed-log row. They are mirror images. Netting
them on a prior book turned +$7,917,373 (t = +1.473) into -$368,673 (t = -0.201), with
five trades spanning coupon dates accounting for 105% of the headline.
``mtm_history`` already contains both, so it is the only correct equity curve here.

The fee is charged once, in full, at the unwind
------------------------------------------------
``BT/query_engine.py:246`` reads ``order.meta["fee"]`` from the ``UnwindOrder``; entry
actions carry none. There is exactly one hook, so it takes the whole round trip.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


@dataclass
class _PackageBook:
    """Entry and exit schedules, keyed by date, for a set of butterfly packages."""

    entries: Dict[datetime.date, List[Dict[str, Any]]] = field(default_factory=dict)
    exits: Dict[datetime.date, List[Dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def from_trades(cls, closed: pd.DataFrame, legs: pd.DataFrame) -> "_PackageBook":
        """Rebuild the package schedule from the vectorised engine's own output.

        Taking the trades from the fast engine rather than re-selecting is deliberate:
        the two layers must price the *same* book, or a disagreement between them is
        just two different books and says nothing about either.
        """
        by_trade = {tid: g for tid, g in legs.groupby("trade_id")}
        book = cls()
        for r in closed.itertuples():
            lg = by_trade.get(r.trade_id)
            if lg is None:
                continue
            pkg = {
                "trade_id": int(r.trade_id),
                "tag": f"etfrv{int(r.trade_id)}",
                "side": float(r.side),
                "entry": pd.Timestamp(r.opened_at),
                "exit": pd.Timestamp(r.closed_at),
                "cost_bp": float(r.cost_bp),
                "legs": [{"cusip": str(x.cusip), "w": float(x.w), "role": str(x.role)}
                         for x in lg.itertuples()],
            }
            book.entries.setdefault(pkg["entry"].date(), []).append(pkg)
            book.exits.setdefault(pkg["exit"].date(), []).append(pkg)
        return book


class ETFRebalanceAction:
    """Submit signed outright legs on entry dates; unwind with the full fee on exits."""

    risk = None

    def __init__(self, book: _PackageBook, *, charge_fee: bool = True):
        from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
        from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

        self._Q, self._V = FixedRateBondQuery, FixedRateBondValue
        self.book = book
        self.charge_fee = charge_fee

    def __call__(self, *, now, backtest, info) -> List[Any]:
        from BT.query_order import QueryOrder, UnwindOrder

        d = now.date()
        orders: List[Any] = []

        for pkg in self.book.entries.get(d, ()):
            for leg in pkg["legs"]:
                # SIGNED bpv. The belly carries side * 1.0, so one dollar per basis point
                # of belly risk, and the book's dollar P&L is the package's bp P&L.
                bpv = float(pkg["side"]) * float(leg["w"])
                if bpv == 0.0:
                    continue
                q = self._Q(cusip=leg["cusip"], value=self._V.NPV,
                            structure_kwargs={"bpv": bpv}, tags=(pkg["tag"],))
                orders.append(QueryOrder(timestamp=now, query=q,
                                         meta={"action": "add_query", "tags": [pkg["tag"]],
                                               "trade_id": pkg["trade_id"],
                                               "role": leg["role"]}))

        for pkg in self.book.exits.get(d, ()):
            tag = pkg["tag"]

            def pred(p, _t=tag):
                tags = set(p.meta.get("tags", []))
                tags.update(getattr(p.source_query, "tags", ()) or ())
                return _t in tags

            orders.append(UnwindOrder(
                timestamp=now, selector=pred,
                meta={"action": "unwind", "trade_id": pkg["trade_id"],
                      "fee": float(pkg["cost_bp"]) if self.charge_fee else 0.0},
            ))
        return orders


def run_qdb(
    closed: pd.DataFrame,
    legs: pd.DataFrame,
    *,
    dates: Sequence[pd.Timestamp],
    source: str = "USTS_FEDINVEST_WSJ_LIVE-QL",
    charge_fee: bool = True,
    show_progress: bool = True,
    name: str = "etf_rebalance",
) -> Dict[str, Any]:
    """Run the book through ``QueryDrivenBacktest`` and return its daily equity curve.

    ``dates`` must be the marking grid -- the dates on which every leg of every open
    package has a genuine gated price. Handing the engine a date where one leg does not
    price is how a prior book unwound into a 50bp-rich mark that sat inside a 100bp gate
    and booked +15.3bp on a 22-trade result.
    """
    from BT.data_handler import TimeGrid
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import FlowSignalTriggerRequirements, Trigger
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP

    book = _PackageBook.from_trades(closed, legs)
    action = ETFRebalanceAction(book, charge_fee=charge_fee)
    fire = set(book.entries) | set(book.exits)

    trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda now, bt: now.date() in fire),
        actions=[action],
    )
    mdp = FixedRateBondsMDP(source=source)
    strat = QueryStrategy(name=name, triggers=[trig], default_mdp=mdp)

    grid = [datetime.datetime.combine(pd.Timestamp(d).date(), datetime.time())
            for d in sorted(pd.DatetimeIndex(dates).unique())]
    bt = QueryDrivenBacktest(time_grid=TimeGrid(grid), strategy=strat, mdp=mdp,
                             show_progress=show_progress,
                             progress_desc=f"QDB {name}")
    bt.run()

    eq = pd.Series({pd.Timestamp(k): float(v) for k, v in bt.mtm_history.items()}).sort_index()
    holes = len(grid) - len(eq)
    eq = eq.reindex(pd.DatetimeIndex(sorted(pd.Timestamp(g) for g in grid))).ffill().fillna(0.0)

    daily = pd.DataFrame({"date": eq.index, "mtm_bp": eq.to_numpy(float)})
    daily["pnl_bp"] = daily["mtm_bp"].diff().fillna(daily["mtm_bp"])

    comp = getattr(bt, "frb_component_histories", None)
    components = {}
    if comp:
        for k, v in comp.items():
            if v:
                components[k] = pd.Series(
                    {pd.Timestamp(t): float(x) for t, x in v.items()}).sort_index()

    return {
        "backtest": bt,
        "daily": daily,
        "equity": eq,
        "holes": holes,
        "n_packages": len(book.entries and closed),
        "components": components,
        "closed_log": pd.DataFrame(bt.portfolio.closed_positions_log),
    }


def fast_daily_for(segments: pd.DataFrame, trade_ids, dates) -> pd.DataFrame:
    """The fast engine's daily curve for a SUBSET of its own trades.

    Without this the only fast curve available is the whole book's, and comparing 1,400
    packages against the 10 the QDB actually priced measures the difference between two
    books rather than between two ways of marking one. Costs are excluded on both sides:
    they are a single deterministic charge and would only add a constant.
    """
    d = pd.DatetimeIndex(sorted(pd.DatetimeIndex(dates).unique()))
    if segments is None or segments.empty:
        return pd.DataFrame({"date": d, "mtm_bp": 0.0})
    s = segments[segments["trade_id"].isin(set(trade_ids))]
    step = s.groupby("date")["pnl_bp"].sum().reindex(d).fillna(0.0)
    return pd.DataFrame({"date": d, "mtm_bp": step.cumsum().to_numpy(float)})


def tie_out(fast_daily: pd.DataFrame, qdb_daily: pd.DataFrame) -> pd.DataFrame:
    """Compare the two equity curves day by day, and say where they part company.

    They are not required to be identical and it would be suspicious if they were: the
    fast engine measures price P&L as ``-dR`` in yield space plus an explicit
    ``(y - r)/D`` carry term, while the QDB reprices dirty NPV and books coupon cash.
    What IS required is that they agree in level and shape, that the gap has no trend,
    and that its size is of the order of the carry term rather than of the P&L.
    """
    a = fast_daily.set_index("date")["mtm_bp"].rename("fast_bp")
    b = qdb_daily.set_index("date")["mtm_bp"].rename("qdb_bp")
    j = pd.concat([a, b], axis=1).dropna()
    j["gap_bp"] = j["qdb_bp"] - j["fast_bp"]
    j["fast_d"] = j["fast_bp"].diff()
    j["qdb_d"] = j["qdb_bp"].diff()
    return j


def tie_out_report(j: pd.DataFrame) -> Dict[str, Any]:
    d = j.dropna(subset=["fast_d", "qdb_d"])
    corr = float(d["fast_d"].corr(d["qdb_d"])) if len(d) > 3 else np.nan
    return {
        "days": int(len(j)),
        "fast_end_bp": float(j["fast_bp"].iloc[-1]),
        "qdb_end_bp": float(j["qdb_bp"].iloc[-1]),
        "end_gap_bp": float(j["gap_bp"].iloc[-1]),
        "max_abs_gap_bp": float(j["gap_bp"].abs().max()),
        "daily_change_corr": corr,
        "gap_trend_bp_per_yr": float(
            np.polyfit(np.arange(len(j)), j["gap_bp"].to_numpy(float), 1)[0] * 252)
        if len(j) > 10 else np.nan,
    }
