"""Probe 5: is the EXISTING Fed notebook actually intraday, or silently EOD?

BaseQuery.build_mdp_request injects ``now.date()`` unless market_request carries
the literal "now" sentinel. If that is what happens for IRSwapQuery(value=NPV),
then an entry and an exit on the SAME calendar day price off the SAME daily curve
and every trade's P&L is identically zero.

The notebook reports $27m of P&L, so one of those two statements is false.
This settles which, by running the notebook's exact query shape both ways.
"""

from __future__ import annotations

import sys
import datetime

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")

import pandas as pd
import pytz

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, FlowSignalTriggerRequirements

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapValue import IRSwapValue

NY = pytz.timezone("America/New_York")
CURVE = "USD-SOFR-1D-Q12STIRT"
TENOR = "IMM_3xIMM_4"
BPV = 100_000

ENTRY = NY.localize(datetime.datetime(2025, 11, 20, 10, 0))
EXIT = NY.localize(datetime.datetime(2025, 11, 20, 14, 0))


def run(mdp, label: str, market_request: dict | None) -> float:
    kw = dict(
        curve=CURVE, tenor=TENOR, value=IRSwapValue.NPV,
        structure_kwargs={"bpv": BPV}, tags=("t",), meta={},
    )
    if market_request is not None:
        kw["market_request"] = market_request
    q = IRSwapQuery(**kw)

    print(f"  [{label}] build_mdp_request(entry) = {q.build_mdp_request(ENTRY)}")
    print(f"  [{label}] build_mdp_request(exit ) = {q.build_mdp_request(EXIT)}")

    exit_trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(signal_fn=lambda s, bt: s == EXIT),
        actions=[UnwindPositionsAction(match_all=True, fee=0.0)],
    )
    entry_trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(signal_fn=lambda s, bt: s == ENTRY),
        actions=[AddQueryAction(query=q)],
    )
    strat = QueryStrategy(name=label, triggers=[exit_trig, entry_trig])
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid([ENTRY, EXIT]), mdp=mdp, strategy=strat, show_progress=False
    )
    bt.run()
    cl = pd.DataFrame(bt.portfolio.closed_positions_log)
    if cl.empty:
        print(f"  [{label}] NO CLOSED TRADES\n")
        return float("nan")
    pnl = float(cl["realized_pnl"].sum())
    print(f"  [{label}] realized_pnl = {pnl:,.2f}\n")
    return pnl


def main() -> None:
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    print("=" * 100)
    print(f"IRSwapQuery {TENOR} on {CURVE}, same-day {ENTRY:%H:%M} -> {EXIT:%H:%M}")
    print("=" * 100)
    a = run(mdp, "notebook-as-is (no market_request)", None)
    b = run(mdp, 'with market_request={"timestamp": "now"}', {"timestamp": "now"})
    print("=" * 100)
    print(f"  as-is  P&L = {a:,.2f}")
    print(f"  'now'  P&L = {b:,.2f}")
    if a == a and abs(a) < 1e-9:
        print("  => VERDICT: the notebook's query is EOD-degenerate (zero intraday move).")
    else:
        print("  => VERDICT: the as-is query DOES see an intraday move.")
    print("=" * 100)


if __name__ == "__main__":
    main()
