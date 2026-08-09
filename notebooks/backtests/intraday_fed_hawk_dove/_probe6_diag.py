"""Probe 6: where does the IRSwap P&L come from when entry and exit share a curve?

If a ZERO-holding-period trade (exit instant == entry instant) still books P&L,
the number is an artifact of the mark, not a market move.
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


def run(mdp, entry, exit_, mr) -> float:
    kw = dict(curve=CURVE, tenor=TENOR, value=IRSwapValue.NPV,
              structure_kwargs={"bpv": BPV}, tags=("t",), meta={})
    if mr is not None:
        kw["market_request"] = mr
    q = IRSwapQuery(**kw)
    trigs = [
        Trigger(trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda s, bt, _x=exit_: s == _x and len(bt.portfolio.positions) > 0),
            actions=[UnwindPositionsAction(match_all=True, fee=0.0)]),
        Trigger(trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda s, bt, _e=entry: s == _e and len(bt.portfolio.positions) == 0),
            actions=[AddQueryAction(query=q)]),
    ]
    ts = sorted({entry, exit_})
    bt = QueryDrivenBacktest(time_grid=TimeGrid(ts), mdp=mdp,
                            strategy=QueryStrategy(name="d", triggers=trigs),
                            show_progress=False)
    bt.run()
    cl = pd.DataFrame(bt.portfolio.closed_positions_log)
    return float(cl["realized_pnl"].sum()) if not cl.empty else float("nan")


def par_rate_at(mdp, ts):
    """Par rate of the same IMM structure straight off the MDP curve."""
    from Query.Base.query_resolution import resolve_query
    q = IRSwapQuery(curve=CURVE, tenor=TENOR, value=IRSwapValue.RATE,
                    structure_kwargs={"bpv": BPV}, tags=("t",),
                    market_request={"timestamp": "now"})
    req = q.build_mdp_request(ts)
    req["product"] = q.product
    pr = mdp.get_pricer(req)
    q2 = resolve_query(q, timestamp=ts, pricer_or_curve=pr)
    pkg, w = q2.resolve_package(pricer_or_curve=pr)
    vmap = q2.build_value_map(pricer_or_curve=pr, package=pkg, risk_weights=w)
    ref = getattr(pr, "reference_date", None)
    ref = ref() if callable(ref) else ref
    return float(vmap.apply(value=IRSwapValue.RATE)), ref


def main() -> None:
    mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
    d = datetime.date(2025, 11, 20)
    t10 = NY.localize(datetime.datetime(d.year, d.month, d.day, 10, 0))
    t14 = NY.localize(datetime.datetime(d.year, d.month, d.day, 14, 0))
    t_prev = NY.localize(datetime.datetime(2025, 11, 19, 14, 0))

    print("=" * 100)
    print("A. ZERO-HOLDING trade (entry instant == exit instant)")
    print("=" * 100)
    for label, mr in [("as-is", None), ("now", {"timestamp": "now"})]:
        pnl = run(mdp, t10, t10, mr)
        print(f"  {label:6s} entry==exit@10:00  P&L = {pnl:,.2f}"
              f"   {'<-- ARTIFACT (should be 0)' if pnl == pnl and abs(pnl) > 1 else ''}")

    print()
    print("=" * 100)
    print("B. SAME-DAY 10:00 -> 14:00")
    print("=" * 100)
    for label, mr in [("as-is", None), ("now", {"timestamp": "now"})]:
        print(f"  {label:6s} P&L = {run(mdp, t10, t14, mr):,.2f}")

    print()
    print("=" * 100)
    print("C. OVERNIGHT 11-19 14:00 -> 11-20 14:00 (dates genuinely differ)")
    print("=" * 100)
    for label, mr in [("as-is", None), ("now", {"timestamp": "now"})]:
        print(f"  {label:6s} P&L = {run(mdp, t_prev, t14, mr):,.2f}")

    print()
    print("=" * 100)
    print("D. PAR RATE off the curve at each instant (does the curve move intraday?)")
    print("=" * 100)
    for ts in (t10, t14, t_prev):
        try:
            r, ref = par_rate_at(mdp, ts)
            print(f"  {ts:%Y-%m-%d %H:%M}  par_rate = {r:.6f}   curve_ref_date = {ref}")
        except Exception as e:  # noqa: BLE001
            print(f"  {ts:%Y-%m-%d %H:%M}  ERROR {type(e).__name__}: {str(e)[:120]}")
    print("=" * 100)


if __name__ == "__main__":
    main()
