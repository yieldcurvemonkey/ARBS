"""QueryDrivenBacktest runner for the V3 basis-vs-swaption position.

Same pattern as ``BT/signals/basis_pair.py``: the trade calendar comes from
:func:`RVUtils.BasisVsVol.v3.run_v3` and is materialised as ``DateTrigger`` pairs, so both engines
trade an identical schedule and any P&L difference is a pricing difference rather than a signal
difference.

WHAT QDB PRICES, AND WHAT IT DOES NOT
-------------------------------------
The **basis leg** goes through the real product (``Query/BasisPair``), marked daily off the panel,
exactly as V1's does.

The **swaption leg** (arm B only) is booked as a cash adjustment at unwind rather than as a second
marked product. So for arm B, QDB and the reference engine agree on TOTALS and trade counts but the
swaption leg contributes nothing to the intra-trade QDB path. That is a real limitation and it is
stated rather than papered over: arm A and arm C are fully marked, arm B's daily QDB path is the
basis leg alone. Reported Sharpes come from the reference engine throughout, as they do for V1.
"""

from __future__ import annotations

import pandas as pd

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
import Query.BasisPair.BasisPairQuery  # noqa: F401  (registers the product + handler)

__all__ = ["run_v3_qdb", "qdb_equity"]


def qdb_equity(bt) -> pd.Series:
    if not bt.mtm_history:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(k): float(v) for k, v in bt.mtm_history.items()}).sort_index()


def run_v3_qdb(panel: pd.DataFrame, cfg, show_progress: bool = False):
    """Run the V3 schedule through QueryDrivenBacktest. Returns ``(backtest, reference_result)``."""
    from Query.BasisPair.BasisPairQuery import BasisPairQuery, BasisPanelMDP
    from RVUtils.BasisVsVol.v3 import TICK_USD_PER_MM, run_v3

    ref = run_v3(panel, cfg)
    if ref.trades.empty:
        raise ValueError("no trades from the reference engine; nothing to materialise")

    p = ref.panel
    grid = [pd.Timestamp(d).to_pydatetime() for d in p["date"]]
    triggers = []
    for i, t in enumerate(ref.trades.itertuples(index=False)):
        tag = f"v3{i:04d}"
        q = BasisPairQuery(root=cfg.root, side=1, face_mm=cfg.face_mm,
                           cost_32nds=cfg.cost_32nds, cost_mult=cfg.cost_mult,
                           max_gap_days=cfg.max_gap_days, tags=(tag,), name=tag)
        # The reference engine charges the basis fee at BOTH entry and exit; the framework has
        # no entry-side fee hook, so the whole ROUND TRIP is charged here. Getting this wrong
        # showed up as a constant 15 x 15,625 gap between the two engines.
        fee = 2.0 * cfg.cost_mult * cfg.cost_32nds * cfg.face_mm * TICK_USD_PER_MM
        # arm B: fold the swaption leg's realised P&L into the unwind as a cash adjustment, since
        # it is not a separately marked product here. Sign: a POSITIVE swaption contribution is a
        # negative fee.
        if cfg.arm == "B":
            # read the leg, do not infer it by subtraction: on a roll- or gap-closed trade the
            # engine deliberately skips the final day's move, so exit_nb - entry_nb overstates the
            # basis leg and the residual is not the swaption.
            fee -= float(t.pnl_swaption)
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[pd.Timestamp(t.entry_date).date()]),
                                    actions=[AddQueryAction(query=q, meta={"tags": [tag]})]))
        triggers.append(DateTrigger(DateTriggerRequirements(dates=[pd.Timestamp(t.exit_date).date()]),
                                    actions=[UnwindPositionsAction(match_tag=tag, fee=fee)]))

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(grid), mdp=BasisPanelMDP(p),
        strategy=QueryStrategy(name=f"v3/{cfg.root}/{cfg.arm}", triggers=triggers),
        show_progress=show_progress,
    )
    bt.run()
    return bt, ref
