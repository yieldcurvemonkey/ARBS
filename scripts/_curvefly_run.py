"""Run the curve-fly screen on one curve date."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 400)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from RVUtils.CurveFlyScreener import (  # noqa: E402
    Leg, Structure, forward_flies, screen, spot_flies,
)

ASOF = datetime.datetime(2026, 8, 21, 17, 0)
mdp = IRSwapsMDP(source="citivelo_excel_rl")
pricer = mdp.get_data({"curve_name": "USD-SOFR-1D", "timestamp": ASOF})

uni = spot_flies() + forward_flies(starts=(1, 2, 3, 5, 10),
                                   tenors=(2, 3, 5, 7, 10, 15, 20, 30))
# the two structures the desk actually talks about, as named pairs
uni += [
    Structure("10y10y/20y10y", (Leg(10, 10), Leg(20, 10)), (-1.0, 1.0), "curve"),
    Structure("15y5y/20y5y", (Leg(15, 5), Leg(20, 5)), (-1.0, 1.0), "curve"),
    Structure("20y5y/25y5y", (Leg(20, 5), Leg(25, 5)), (-1.0, 1.0), "curve"),
    Structure("5s30s", (Leg(0, 5), Leg(0, 30)), (-1.0, 1.0), "curve"),
    Structure("2s10s", (Leg(0, 2), Leg(0, 10)), (-1.0, 1.0), "curve"),
]
print(f"universe: {len(uni)} structures")

df = screen(pricer, uni, horizon_y=1.0)
df = df[df.error == ""].drop(columns=["error", "rlzd_vol_bp", "zs_1y", "rac"])
out = REPO / "docs" / "curvefly" / "screen_2026-08-21.csv"
df.to_csv(out, index=False)
print(f"wrote {out}  ({len(df)} rows)\n")

print("=== the structures the desk names ===")
named = ["10y10y/20y10y", "15y5y/20y5y", "20y5y/25y5y", "5s30s", "2s10s",
         "5s10s30s", "2s7s20s"]
print(df[df.label.isin(named)].round(2).to_string(index=False))

for kind, tag in [("fly", "FLIES")]:
    sub = df[df.kind == kind].sort_values("cr_bp", ascending=False)
    print(f"\n=== {tag}: best 12 by 1y carry-and-roll (bp of structure) ===")
    print(sub.head(12).round(2).to_string(index=False))
    print(f"\n=== {tag}: worst 8 ===")
    print(sub.tail(8).round(2).to_string(index=False))

spot = df[(df.kind == "fly") & (~df.label.str.contains("\\("))]
fwd = df[(df.kind == "fly") & (df.label.str.contains("\\("))]
print(f"\nspot flies    n={len(spot):>3}  mean CR {spot.cr_bp.mean():+.2f}bp  "
      f"positive on {(spot.cr_bp > 0).mean():.0%}")
print(f"forward flies n={len(fwd):>3}  mean CR {fwd.cr_bp.mean():+.2f}bp  "
      f"positive on {(fwd.cr_bp > 0).mean():.0%}")
