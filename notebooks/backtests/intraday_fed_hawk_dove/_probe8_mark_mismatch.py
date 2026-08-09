"""Probe 8: why do 31/449 FED trades disagree with the gate's bar prices?

The gate records the last bar at-or-before entry/exit from a FULL-DAY minute fetch.
The engine asks the MDP for a price AT that timestamp, and the MDP fetches its own
window. If the two resolve to different bars, the reconciliation flips sign on
small moves. This identifies which bar each side used.
"""

from __future__ import annotations

import sys
import pickle
import datetime
from pathlib import Path

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

import global_hawk_dove_common as G
from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

CACHE = Path(__file__).parent / "_global_cache"


def mdp_price(mdp, symbol, ts):
    res = mdp.get_data({"symbols": [symbol], "timestamp": G._plain_dt(ts)})
    flat = []
    for _k, v in (res or {}).items():
        flat.extend(v if isinstance(v, list) else [v])
    return float(flat[0].price()) if flat else None


def main() -> None:
    with open(CACHE / "events.pkl", "rb") as f:
        events_by_bank = pickle.load(f)
    with open(CACHE / "closed.pkl", "rb") as f:
        closed_by_bank = pickle.load(f)

    mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
    cfg = G.CB_CONFIGS["FED"]
    fetcher = mdp._get_barchart_fetcher(required_concurrency=2)

    cl = closed_by_bank["FED"]
    evs = {e["tag"]: e for e in events_by_bank["FED"]["events"]}

    rows = []
    for _, r in cl.iterrows():
        tag = next(iter(r["source_query"].tags), None)
        ev = evs.get(tag)
        if ev is None or "entry_bar_px" not in ev:
            continue
        exp = ev["side"] * (ev["exit_bar_px"] - ev["entry_bar_px"]) / 0.01
        rows.append({"tag": tag, "ev": ev, "expected": exp, "actual": r["pnl_bp"]})

    bad = [x for x in rows
           if abs(x["ev"]["exit_bar_px"] - x["ev"]["entry_bar_px"]) > 1e-12
           and np.sign(x["expected"]) != np.sign(x["actual"])]
    print(f"FED trades reconciled: {len(rows)}   mismatching: {len(bad)}")

    print("\nInspecting the first 6 mismatches — which bar did each side use?\n")
    for x in bad[:6]:
        ev = x["ev"]
        day = ev["entry_ts"].date()
        bars = G._day_bars(fetcher, ev["symbol"], day, cfg.tz)
        e_px = mdp_price(mdp, ev["symbol"], ev["entry_ts"])
        x_px = mdp_price(mdp, ev["symbol"], ev["exit_ts"])

        def which(px):
            if px is None or bars.empty:
                return "n/a"
            hit = bars.index[(bars["Close"] - px).abs() < 1e-9]
            return f"{len(hit)} bar(s), first {hit.min():%H:%M}" if len(hit) else "NOT IN DAY BARS"

        print(f"  {x['tag']}  {ev['symbol']}  {day}  side={ev['side']:+.0f}")
        print(f"    entry {ev['entry_ts']:%H:%M}  gate_bar={ev['entry_bar']:%H:%M} "
              f"px={ev['entry_bar_px']}   MDP px={e_px}  -> {which(e_px)}")
        print(f"    exit  {ev['exit_ts']:%H:%M}  gate_bar={ev['exit_bar']:%H:%M} "
              f"px={ev['exit_bar_px']}   MDP px={x_px}  -> {which(x_px)}")
        print(f"    expected {x['expected']:+.2f}bp   actual {x['actual']:+.2f}bp")
        print(f"    day bars: {len(bars)}  {bars.index.min():%H:%M}..{bars.index.max():%H:%M}")
        print()

    # How big are the mismatches relative to the book?
    tot = sum(x["actual"] for x in rows)
    bad_tot = sum(x["actual"] for x in bad)
    print(f"FED total {tot:+.2f}bp | contribution of the {len(bad)} mismatching "
          f"trades {bad_tot:+.2f}bp ({100*bad_tot/tot:.1f}% of total)")


if __name__ == "__main__":
    main()
