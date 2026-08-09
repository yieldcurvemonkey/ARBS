"""Probe 4: which direction encoding gives the CORRECT sign for a SHORT future?

Convention we must reproduce:
    HAWK -> pay fixed  -> SELL the future -> profits when price FALLS (rates rise)
    DOVE -> recv fixed -> BUY  the future -> profits when price RISES (rates fall)

Independent expectation is computed from the raw minute bars, NOT from the engine,
so a sign bug in the engine cannot hide inside the check.

Two candidate encodings are compared:
    (A) structure_kwargs={"bpv": -BPV}                 (negative bpv -> negative contracts)
    (B) structure_kwargs={"bpv": +BPV, "risk_weights": [-1.0]}
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

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure

NY = pytz.timezone("America/New_York")
BPV = 100_000.0

SYMBOL = "SR3Z25"
ENTRY = NY.localize(datetime.datetime(2025, 11, 20, 10, 0))
EXIT = NY.localize(datetime.datetime(2025, 11, 20, 14, 0))


def raw_prices(mdp: STIRFutureMDP) -> tuple[float, float]:
    """Entry/exit price straight from the MDP pricers - the ground truth."""
    out = []
    for ts in (ENTRY, EXIT):
        res = mdp.get_data({"symbols": [SYMBOL], "timestamp": ts})
        flat = []
        for _k, v in (res or {}).items():
            flat.extend(v if isinstance(v, list) else [v])
        out.append(float(flat[0].price()))
    return out[0], out[1]


def run_one(mdp, label: str, skw: dict) -> float:
    q = STIRFutureQuery(
        structure=STIRFutureStructure.OUTRIGHT,
        value=STIRFutureValue.PRICE,
        symbol=SYMBOL,
        structure_kwargs=dict(skw),
        tags=("t",),
        meta={"label": label},
        market_request={"timestamp": "now"},
    )
    exit_set = {EXIT}
    exit_trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda s, bt, _e=exit_set: s in _e
        ),
        actions=[UnwindPositionsAction(match_all=True, fee=0.0)],
    )
    entry_trig = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=lambda s, bt: s == ENTRY
        ),
        actions=[AddQueryAction(query=q)],
    )
    strat = QueryStrategy(name=label, triggers=[exit_trig, entry_trig])
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid([ENTRY, EXIT]), mdp=mdp, strategy=strat, show_progress=False
    )
    bt.run()
    cl = pd.DataFrame(bt.portfolio.closed_positions_log)
    if cl.empty:
        print(f"  {label:44s} -> NO CLOSED TRADES")
        return float("nan")
    pnl = float(cl["realized_pnl"].sum())
    print(f"  {label:44s} -> realized_pnl = {pnl:>16,.2f}")
    return pnl


def main() -> None:
    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")

    p0, p1 = raw_prices(mdp)
    dprice = p1 - p0
    d_bp = dprice / 0.01
    print("=" * 100)
    print(f"GROUND TRUTH  {SYMBOL}   {ENTRY:%Y-%m-%d %H:%M} -> {EXIT:%H:%M}")
    print(f"  entry price = {p0:.4f}")
    print(f"  exit  price = {p1:.4f}")
    print(f"  d(price)    = {dprice:+.4f} points  =>  rate moved {-d_bp:+.2f} bp")
    print()
    exp_long = d_bp * BPV
    exp_short = -d_bp * BPV
    print(f"  EXPECTED  LONG  (dove, buy)  P&L = {exp_long:+,.2f}")
    print(f"  EXPECTED  SHORT (hawk, sell) P&L = {exp_short:+,.2f}")
    print("=" * 100)

    print("\nENCODINGS")
    got = {}
    got["A_long  bpv=+BPV"] = run_one(mdp, "A_long   bpv=+BPV", {"bpv": +BPV})
    got["A_short bpv=-BPV"] = run_one(mdp, "A_short  bpv=-BPV", {"bpv": -BPV})
    got["B_long  bpv=+BPV rw=[+1]"] = run_one(
        mdp, "B_long   bpv=+BPV risk_weights=[+1.0]", {"bpv": BPV, "risk_weights": [1.0]}
    )
    got["B_short bpv=+BPV rw=[-1]"] = run_one(
        mdp, "B_short  bpv=+BPV risk_weights=[-1.0]", {"bpv": BPV, "risk_weights": [-1.0]}
    )

    print("\n" + "=" * 100)
    print("VERDICT (tolerance 1% of |expected|)")
    tol = max(abs(exp_long) * 0.01, 1.0)
    for k, v in got.items():
        target = exp_long if "long" in k else exp_short
        ok = abs(v - target) <= tol if v == v else False
        print(f"  {k:34s} got={v:>16,.2f}  want={target:>16,.2f}  {'OK' if ok else '** WRONG **'}")
    print("=" * 100)


if __name__ == "__main__":
    main()
