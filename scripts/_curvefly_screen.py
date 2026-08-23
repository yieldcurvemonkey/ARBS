"""Full screen: 1,075 curves and flies, spot and forward, on risk-adjusted carry-roll."""
from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
pd.set_option("display.width", 210)
pd.set_option("display.max_rows", 400)

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402
from RVUtils.CurveFlyScreener import (  # noqa: E402
    add_risk_adjustment, compose_levels, full_universe, screen, structure_rate_bp,
)

ASOF = datetime.datetime(2026, 8, 21, 17, 0)
LH = REPO / "docs" / "curvefly" / "leg_history.parquet"

mdp = IRSwapsMDP(source="citivelo_excel_rl")
pricer = mdp.get_data({"curve_name": "USD-SOFR-1D", "timestamp": ASOF})
uni = full_universe()
print(f"universe {len(uni)} structures")

t0 = time.time()
df = screen(pricer, uni, horizon_y=1.0)
print(f"priced in {time.time()-t0:.1f}s")
df = df[df.error == ""].drop(columns=["error", "rlzd_vol_bp", "zs_1y", "rac"])

lh = pd.read_parquet(LH)
levels = compose_levels(lh, uni)
print(f"composed {levels.shape[1]} level histories over {len(levels)} dates")

# ---- GATE: compose-vs-price. A level built from the leg warm must match the
# level priced off today's curve, up to the vintage gap between the two sources.
last = levels.ffill().iloc[-1]
chk = []
for s in uni[:400:7]:
    if s.label in last.index:
        chk.append((s.label, structure_rate_bp(pricer, s), float(last[s.label])))
g = pd.DataFrame(chk, columns=["label", "priced", "composed"])
g["diff"] = g.priced - g.composed
print(f"\n=== GATE compose-vs-price on {len(g)} structures ===")
print(f"  mean |diff| {g['diff'].abs().mean():.2f}bp | max {g['diff'].abs().max():.2f}bp")
if g["diff"].abs().max() > 3.0:
    print("  WARNING: the TSB history and the live pricer are on different vintages.")
    print("  z-scores are computed WITHIN the composed history so they stay internally")
    print("  consistent; only the carry column comes from the pricer.")
print(g.reindex(g["diff"].abs().sort_values(ascending=False).index).head(4).round(2).to_string(index=False))

df = add_risk_adjustment(df, levels)
df.to_csv(REPO / "docs" / "curvefly" / "screen_full_2026-08-21.csv", index=False)

named = ["10y10y/20y10y", "15y5y/20y5y", "20y5y/25y5y", "5s10s30s", "2s7s20s",
         "5s30s", "2s10s", "10y10y/15y10y", "5y10y/10y10y"]
print("\n=== the structures the desk names ===")
print(df[df.label.isin(named)][["label", "kind", "level_bp", "cr_bp",
                                "rlzd_vol_bp", "zs", "rac", "n_obs"]]
      .round(2).to_string(index=False))

ok = df[df.rac.notna()]
print(f"\n{len(ok)} of {len(df)} structures have a usable rac "
      f"(>=100 obs of composed history)")
for kind in ["curve_spot", "curve_fwd_start", "curve_fwd_tenor", "fly_spot", "fly_fwd"]:
    sub = ok[ok.kind == kind].sort_values("rac", ascending=False)
    if sub.empty:
        continue
    print(f"\n=== {kind}: top 5 by rac (carry per unit of realised vol) ===")
    print(sub.head(5)[["label", "level_bp", "cr_bp", "rlzd_vol_bp", "zs", "rac"]]
          .round(2).to_string(index=False))
    print(f"    bottom 3: " + " | ".join(
        f"{r.label} {r.rac:+.2f}" for _, r in sub.tail(3).iterrows()))

print("\n=== summary by kind ===")
print(ok.groupby("kind").agg(n=("rac", "size"), mean_cr=("cr_bp", "mean"),
                             pct_cr_pos=("cr_bp", lambda x: (x > 0).mean()),
                             mean_rac=("rac", "mean"),
                             mean_vol=("rlzd_vol_bp", "mean")).round(3).to_string())
