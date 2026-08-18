"""QueryDrivenBacktest runner for the exchange-vs-OTC vol pair.

The trade calendar is taken from :func:`RVUtils.BasisVsVol.strategy.run_strategy` and materialised
as ``DateTrigger`` pairs -- the "precompute-and-materialise" idiom already used by
``BT/signals/ustf_basis.py``. Doing it this way is deliberate: both engines then trade an
identical schedule, so any difference in the equity curve is a difference in *pricing*, not in
*selection*. That makes the two implementations a genuine cross-check of each other rather than
two views of the same code.

Costs: the framework has no entry-side fee hook, so the full round trip is charged at unwind
(the same convention as ``ustf_basis.py``). Fees are split across matched positions by the engine,
so one tag must match exactly one position.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

import numpy as np
import pandas as pd

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.BasisVsVol.SnapshotVolMDP import SnapshotVolMDP
from Query.BasisVsVol.BasisVsVolQuery import BasisVsVolQuery
from RVUtils.BasisVsVol.strategy import StrategyConfig, run_strategy
from RVUtils.BasisVsVol.surfaces import SurfaceBook
from RVUtils.BasisVsVol.voldata import PRODUCT_TAIL, VolData

__all__ = ["run_bvv_qdb_backtest", "qdb_equity_series"]


def qdb_equity_series(bt: QueryDrivenBacktest) -> pd.Series:
    """``mtm_history`` as a sorted Series. It is cumulative equity, not a daily P&L."""
    if not bt.mtm_history:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(k): float(v) for k, v in bt.mtm_history.items()})
    return s.sort_index()


def run_bvv_qdb_backtest(vd: VolData, cfg: StrategyConfig, book: SurfaceBook | None = None,
                         show_progress: bool = False):
    """Run the pair through QueryDrivenBacktest. Returns ``(backtest, reference_result)``."""
    book = book or SurfaceBook(vd)
    ref = run_strategy(vd, cfg, book)
    if ref.trades.empty:
        raise ValueError("no trades from the reference strategy; nothing to materialise")

    tail = cfg.resolved_tail()
    dates = [pd.Timestamp(d) for d in ref.signal.index]
    grid = [d.to_pydatetime() for d in dates]

    triggers = []
    for i, t in enumerate(ref.trades.itertuples(index=False)):
        tag = f"bvv{i:04d}"
        q = BasisVsVolQuery(
            ustf_product=cfg.product, tail=tail, expiry_label=cfg.expiry_label,
            offset_bps=cfg.offset_bps, side=int(t.side),
            target_vega_usd=cfg.target_vega_usd, rehedge_days=cfg.rehedge_days,
            hedge_cost_bp=cfg.hedge_cost_bp, cost_mult=cfg.cost_mult,
            max_gap_days=cfg.max_gap_days,
            tags=(tag,), name=tag,
        )
        # Round trip charged at unwind: the engine exposes no entry-side fee hook.
        fee = cfg.cost_mult * cfg.target_vega_usd * (cfg.ustf_cost_vol_bp + cfg.swpt_cost_vol_bp) * 2.0
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[pd.Timestamp(t.entry_date).date()]),
                                    actions=[AddQueryAction(query=q, meta={"tags": [tag]})]))
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[pd.Timestamp(t.exit_date).date()]),
                                    actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))

    mdp = SnapshotVolMDP(vd, book)
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(grid),
        mdp=mdp,
        strategy=QueryStrategy(name=f"bvv/{cfg.product}/{cfg.expiry_label}", triggers=triggers),
        show_progress=show_progress,
    )
    bt.run()

    # run() swallows per-step exceptions and prints them; a short history is the only signal that
    # a day was dropped, and a partial run otherwise looks like a flat book.
    n_expected, n_got = len(grid), len(bt.mtm_history)
    if n_got != n_expected:
        raise RuntimeError(f"QDB dropped {n_expected - n_got} of {n_expected} steps -- "
                           f"a pricer raised inside run(); do not trust this equity curve")
    return bt, ref
