r"""The primary book re-run through ``QueryDrivenBacktest`` and ``STIRFutureMDP``.

The grid is a vectorised search device: it prices a trade as
``side * (exit_settle - entry_settle) / 0.01`` from a settle panel. That is fast
enough to run 2,048 cells four hundred times, and it is also a second
implementation of the P&L -- which is exactly the kind of thing that is quietly
wrong. So the headline cells are re-run through the shipped engine: positions
are ``STIRFutureQuery`` OUTRIGHT legs opened by ``AddQueryAction``, marked by the
shipped ``STIRFutureHandler``, and unwound by ``UnwindPositionsAction``, with
every price served by ``STIRFutureMDP``'s own disk cache.

Two properties are enforced rather than hoped for.

**No network.** ``disarm`` replaces every fetch path with a raise, so a cache
miss is a loud failure instead of a silent refetch -- and "this used no network"
becomes something the run proves.

**The sign is checked against a known answer.** ``STIRFutureQuery`` has a
documented trap: a NEGATIVE contract count flips the risk weight while the leg
keeps its negative count, the handler multiplies by both, and the signs cancel
so a "short" books a long. The pattern used here is positive ``contracts`` with
the direction in ``risk_weights``, and :func:`gate_direction` proves it by
running the same trade both ways and requiring the two P&Ls to be equal and
opposite.
"""
from __future__ import annotations

import datetime
import pathlib
import sys
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (str(HERE), str(REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SOURCE = "BARCHART_STIRF-RL"

#: The most recent engine run, for a tearsheet. See ``replay`` for why it is
#: not attached to the returned frame.
LAST_BACKTEST: Dict[str, Any] = {}

#: One SR3 contract is $25 per basis point of rate.
USD_PER_BP = 25.0


class NetworkForbidden(RuntimeError):
    """The MDP asked for a price its cache does not hold."""


def disarm(mdp: Any) -> Any:
    def _forbidden(*_a, **_k):
        raise NetworkForbidden(
            "the MDP cache does not cover this request. Warm it from the settle "
            "panel with warm_from_panel() before running.")

    for attr in ("_fetch_barchart_timeseries", "_fetch_webull_intraday",
                 "_fetch_tos_live_quotes"):
        if hasattr(mdp, attr):
            setattr(mdp, attr, _forbidden)
    return mdp


def open_mdp(*, armed: bool = False) -> Any:
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    mdp = STIRFutureMDP(source=SOURCE)
    mdp._ensure_pricer_cache()
    return mdp if armed else disarm(mdp)


def warm_from_panel(mdp: Any, panel: pd.DataFrame, symbols: Sequence[str],
                    dates: Sequence[datetime.date]) -> int:
    """Seed the MDP's own disk cache from the settle panel.

    Delegates to ``BT.serff.engine_backtest.warm_mdp_cache``, which owns the
    exact key contract the MDP probes for a date-typed request
    (``{iso(_as_datetime(date))}-{SYMBOL}-{SOURCE}``, i.e. NY 17:00). Writing
    that key by hand here would be a second copy of a convention that already
    exists, and the copy is what goes stale.
    """
    from BT.serff.engine_backtest import warm_mdp_cache

    n = warm_mdp_cache(mdp, panel, list(symbols), list(dates))
    if hasattr(mdp, "_flush_pending_cache_writes"):
        # NOT the background flush: a process that exits straight after warming
        # would race the writer thread and lose the batch
        mdp._flush_pending_cache_writes(background=False)
    return int(n)


def _query(symbol: str, side: float, tag: str, contracts: int = 1):
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
    from Query.STIRFutures.STIRFutureValue import STIRFutureValue

    if contracts <= 0:
        raise ValueError(
            "contracts must be POSITIVE -- a negative count flips the risk weight "
            "AND keeps the negative leg, and the handler multiplies by both, so "
            "the signs cancel and the short books a long")
    return STIRFutureQuery(
        structure=STIRFutureStructure.OUTRIGHT,
        value=STIRFutureValue.PRICE,
        symbol=symbol,
        structure_kwargs={"symbol": symbol, "contracts": int(contracts),
                          "risk_weights": [float(side)]},
        tags=(tag,),
        meta={"symbol": symbol, "side": float(side), "contracts": int(contracts),
              "tag": tag},
    )


def replay(book: pd.DataFrame, panel: pd.DataFrame, *, mdp: Any = None,
           show_progress: bool = False) -> pd.DataFrame:
    """Run an analytic book through the engine and return its per-trade P&L.

    ``book`` is the frame :func:`fed_detachment_data.price_book` produces: one
    row per trade with ``entry_date``, ``exit_date``, ``side`` and ``symbols``.
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements

    if book.empty:
        return pd.DataFrame()
    mdp = mdp or open_mdp()

    symbols = sorted({s for row in book["symbols"] for s in str(row).split("/")})
    dates = sorted({pd.Timestamp(d).date()
                    for col in ("entry_date", "exit_date") for d in book[col]})
    warmed = warm_from_panel(mdp, panel, symbols, dates)

    triggers: List[Any] = []
    for i, r in book.reset_index(drop=True).iterrows():
        tag = f"det-{i}-{r['symbols']}"
        for sym in str(r["symbols"]).split("/"):
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[pd.Timestamp(r["entry_date"]).date()]),
                actions=[AddQueryAction(query=_query(sym, float(r["side"]), tag),
                                        meta={"tags": [tag], "trade": int(i)})]))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[pd.Timestamp(r["exit_date"]).date()]),
            actions=[UnwindPositionsAction(match_tag=tag, fee=0.0)]))

    grid = TimeGrid([datetime.datetime(d.year, d.month, d.day, 16, 0) for d in dates])
    bt = QueryDrivenBacktest(
        time_grid=grid, mdp=mdp,
        strategy=QueryStrategy(name="fed-detachment-replay", triggers=triggers),
        show_progress=show_progress)
    bt.run()

    closed = pd.DataFrame(bt.portfolio.closed_positions_log)
    if closed.empty:
        return closed
    closed["tag"] = closed["source_query"].apply(lambda q: next(iter(q.tags), None))
    closed["symbol"] = closed["source_query"].apply(lambda q: (q.meta or {}).get("symbol"))
    closed["side"] = closed["source_query"].apply(lambda q: (q.meta or {}).get("side"))
    closed["trade"] = closed["tag"].str.split("-").str[1].astype(int)
    closed["engine_pnl_bp"] = closed["gross_realized_pnl"] / USD_PER_BP
    closed.attrs["warmed"] = int(warmed)
    # deliberately NOT stored on ``closed.attrs``: pandas deep-copies attrs on
    # every column access, and the engine holds an RLock, so stashing it there
    # turns an ordinary ``df["col"]`` into "cannot pickle '_thread.RLock'"
    LAST_BACKTEST["bt"] = bt
    return closed


def tie_out(book: pd.DataFrame, replayed: pd.DataFrame,
            *, tol_bp: float = 1e-6) -> pd.DataFrame:
    """Per-trade engine-vs-panel difference, in basis points."""
    if replayed.empty:
        return pd.DataFrame()
    eng = replayed.groupby("trade")["engine_pnl_bp"].sum()
    b = book.reset_index(drop=True)
    out = pd.DataFrame({
        "entry_date": b["entry_date"], "exit_date": b["exit_date"],
        "symbols": b["symbols"], "side": b["side"],
        "panel_pnl_bp": b["pnl_bp_gross"],
        "engine_pnl_bp": [eng.get(i, np.nan) for i in range(len(b))],
    })
    out["diff_bp"] = out["engine_pnl_bp"] - out["panel_pnl_bp"]
    out.attrs["max_abs_diff"] = float(np.nanmax(np.abs(out["diff_bp"]))) if len(out) else 0.0
    out.attrs["tol_bp"] = tol_bp
    return out


def gate_engine_tie_out(tie: pd.DataFrame, *, tol_bp: float = 0.01) -> Dict[str, float]:
    """G-E1 -- the engine and the panel must price the same book identically."""
    assert not tie.empty, "G-E1 FAILED: the engine closed no positions at all"
    n_missing = int(tie["engine_pnl_bp"].isna().sum())
    assert n_missing == 0, (
        f"G-E1 FAILED: the engine did not close {n_missing} of {len(tie)} trades")
    worst = float(np.nanmax(np.abs(tie["diff_bp"])))
    assert worst < tol_bp, (
        f"G-E1 FAILED: worst engine-vs-panel difference {worst:.4f}bp exceeds "
        f"{tol_bp}bp -- the two price the same trade differently")
    return {"trades": int(len(tie)), "worst_abs_diff_bp": worst, "tol_bp": tol_bp}


def gate_direction(panel: pd.DataFrame, symbol: str, entry: pd.Timestamp,
                   exit_: pd.Timestamp, *, mdp: Any = None) -> Dict[str, float]:
    """G-E2 -- the same trade long and short must be equal and opposite.

    The known-answer check for ``STIRFutureQuery``'s documented sign trap. It
    also pins the SIGN itself: a long future must make money when the price
    RISES, which is the convention every P&L in this study is quoted in.
    """
    book = pd.DataFrame([
        {"entry_date": entry, "exit_date": exit_, "symbols": symbol, "side": 1.0,
         "pnl_bp_gross": np.nan},
        {"entry_date": entry, "exit_date": exit_, "symbols": symbol, "side": -1.0,
         "pnl_bp_gross": np.nan},
    ])
    rep = replay(book, panel, mdp=mdp)
    eng = rep.groupby("trade")["engine_pnl_bp"].sum()
    lng, srt = float(eng.get(0, np.nan)), float(eng.get(1, np.nan))
    dpx = float(panel.at[pd.Timestamp(exit_), symbol] - panel.at[pd.Timestamp(entry), symbol])
    expect = dpx / 0.01
    assert abs(lng + srt) < 1e-6, (
        f"G-E2 FAILED: long {lng:.6f}bp and short {srt:.6f}bp are not equal and "
        f"opposite -- the direction is being cancelled, see the negative-contracts trap")
    assert abs(lng - expect) < 1e-6, (
        f"G-E2 FAILED: the engine's LONG P&L is {lng:.6f}bp where the settle move "
        f"implies {expect:.6f}bp -- a long future must gain when the price rises")
    return {"long_bp": lng, "short_bp": srt, "settle_move_bp": expect}
