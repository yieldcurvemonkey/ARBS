"""Score every labelling scheme on the same machinery, causal and not.

The researched / blended schemes cannot be run through the deflated grid because
they are not point-in-time: the stance table was written in 2026 about trades from
2023-2026. They still deserve a NUMBER, because "how much would perfect knowledge
of who is a hawk have been worth" is the natural upper bound on this whole idea.

Uses the closed-form P&L (validated against the engine to the tick on the baseline
book), so this is seconds rather than another set of backtests.
"""

from __future__ import annotations

import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

import global_hawk_dove_common as G
from global_hawk_dove_run import CACHE, BANKS

SCHEMES = [
    ("peer", "events.pkl", True),
    ("percentile", "events_percentile.pkl", True),
    ("absolute", "events_absolute.pkl", True),
    ("researched", "events_researched.pkl", False),
    ("blended", "events_blended.pkl", False),
]


def score(path: Path):
    if not path.exists():
        return None
    with open(path, "rb") as f:
        ev = pickle.load(f)
    frames = []
    for b in BANKS:
        evs = (ev.get(b) or {}).get("events") or []
        if not evs:
            continue
        f_ = G.fast_backtest(evs)
        if not f_.empty:
            frames.append(f_)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True).sort_values("opened_at")


def main() -> None:
    rows = []
    per_leg = {}
    for name, fname, causal in SCHEMES:
        pooled = score(CACHE / fname)
        if pooled is None:
            print(f"  {name:12s} (no event set - skipped)")
            continue
        s = G.summarize(pooled)
        real = pooled[pooled.timestamp_source == "forexfactory"]
        s_real = G.summarize(real) if len(real) > 20 else {}
        rows.append({
            "scheme": name, "causal": causal, "trades": s["trades"],
            "total_bp": s["total"], "avg_bp": s["avg"], "hit": s["hit_rate"],
            "sharpe": s["sharpe"], "t_stat": s["t_stat"],
            "hawk_share": float((pooled["bucket"] > 0).mean()),
            "real_ts_trades": s_real.get("trades", 0),
            "real_ts_avg_bp": s_real.get("avg", float("nan")),
            "real_ts_sharpe": s_real.get("sharpe", float("nan")),
        })
        per_leg[name] = (pooled.groupby("bank")
                         .agg(n=("pnl_bp", "size"), total_bp=("pnl_bp", "sum"),
                              avg_bp=("pnl_bp", "mean")).round(4))

    df = pd.DataFrame(rows).set_index("scheme")
    print("=" * 100)
    print("LABELLING SCHEMES, scored on identical machinery")
    print("=" * 100)
    print(df.round(4).to_string())

    print()
    print("CAUSAL = a desk could have run it at the time.")
    print("The researched and blended schemes are NOT causal: the stance table was")
    print("written in 2026 from sources that postdate these trades, and its period")
    print("boundaries are its largest free parameter. An adversarial audit measured an")
    print("oracle version of the same table at t=5.8 (one period per speaker) and")
    print("t=10.5 (speaker x year), while making its estimation window causal collapsed")
    print("it to t=0.9. Read their numbers as an UPPER BOUND on what perfect knowledge")
    print("of who was a hawk would have been worth - not as a tradeable result.")

    for name, tbl in per_leg.items():
        print(f"\n--- {name} by leg ---")
        print(tbl.to_string())


if __name__ == "__main__":
    main()
