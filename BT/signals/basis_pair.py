"""QueryDrivenBacktest runner for the V1 basis position.

Same pattern as ``BT/signals/basis_vs_vol.py``: the trade calendar comes from
:func:`RVUtils.BasisVsVol.v1.run_v1` and is materialised as ``DateTrigger`` pairs, so both engines
trade an identical schedule and any P&L difference is a pricing difference. Costs are charged as a
round trip at unwind because the framework has no entry-side fee hook.
"""

from __future__ import annotations

import pandas as pd

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
import Query.BasisPair.BasisPairQuery  # noqa: F401  (registers the product + handler)

__all__ = ["run_v1_qdb", "qdb_equity"]


def qdb_equity(bt) -> pd.Series:
    if not bt.mtm_history:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(k): float(v) for k, v in bt.mtm_history.items()}).sort_index()


def run_v1_qdb(panel: pd.DataFrame, cfg, show_progress: bool = False):
    """Run the V1 schedule through QueryDrivenBacktest. Returns ``(backtest, reference_result)``."""
    from Query.BasisPair.BasisPairQuery import BasisPairQuery, BasisPanelMDP
    from RVUtils.BasisVsVol.v1 import run_v1

    ref = run_v1(panel, cfg)
    if ref.trades.empty:
        raise ValueError("no trades from the reference engine; nothing to materialise")

    p = ref.panel
    grid = [pd.Timestamp(d).to_pydatetime() for d in p["date"]]
    triggers = []
    for i, t in enumerate(ref.trades.itertuples(index=False)):
        tag = f"bp{i:04d}"
        q = BasisPairQuery(root=cfg.root, side=int(t.side), face_mm=cfg.face_mm,
                           cost_32nds=cfg.cost_32nds, cost_mult=cfg.cost_mult,
                           max_gap_days=cfg.max_gap_days, tags=(tag,), name=tag)
        fee = cfg.cost_mult * cfg.cost_32nds * cfg.face_mm * 312.50
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[pd.Timestamp(t.entry_date).date()]),
                                    actions=[AddQueryAction(query=q, meta={"tags": [tag]})]))
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[pd.Timestamp(t.exit_date).date()]),
                                    actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(grid), mdp=BasisPanelMDP(p),
        strategy=QueryStrategy(name=f"v1/{cfg.root}", triggers=triggers),
        show_progress=show_progress,
    )
    bt.run()
    if len(bt.mtm_history) != len(grid):
        raise RuntimeError(f"QDB dropped {len(grid) - len(bt.mtm_history)} of {len(grid)} steps -- "
                           "a pricer raised inside run(); do not trust this equity curve")
    return bt, ref
