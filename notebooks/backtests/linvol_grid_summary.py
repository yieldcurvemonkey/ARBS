# %% [markdown]
# # Linear-vs-vol backtest grid — summary and answer
#
# The question was: of every way to trade the measured gap between the
# FF/ZQ lattice and the SR3 option surface, which strategy family and
# config is best — and is anything ALIVE? Everything below is read from the
# league and verdicts computed in `linvol_grid_league` /
# `linvol_grid_autopsy`; nothing is asserted that a cell above this line
# did not produce.

# %%
import sys
from pathlib import Path

import pandas as pd

sys.path.append("../../")
DATA = Path("../data/linvol_grid")
league = pd.read_parquet(DATA / "league.parquet")
verdicts = pd.read_csv(DATA / "verdicts.csv")
real = league[league["family"].isin(["A", "B", "C", "E"])]
live = real[real["n_trades"] > 0]

print("=== verdicts (per-family best, house taxonomy) ===")
print(verdicts.to_string(index=False))

# %%
w = live.sort_values("net_1x_bp").iloc[-1]
n_cfg = len(real)
n_live = len(live)
frac_pos_1x = (live["net_1x_bp"] > 0).mean()
frac_pos_2x = (live["net_2x_bp"] > 0).mean()
print(f"grid: {n_cfg} real configs, {n_live} produced trades, "
      f"{frac_pos_1x:.0%} positive at 1x costs, {frac_pos_2x:.0%} at 2x")
print(f"\noverall winner: family {w['family']} | {w['boundary']} | "
      f"dte {w['dte']} | thr {w['thr']} | {w['direction']} | "
      f"gated={w['gated']}")
print(f"  {int(w['n_trades'])} trades, gross {w['total_gross_bp']:+.1f}bp, "
      f"net {w['net_1x_bp']:+.1f} @1x / {w['net_2x_bp']:+.1f} @2x, "
      f"t={w['t_stat']:.2f}")

fam_verdict = verdicts.set_index("family")["verdict"].to_dict()
alive = [f for f, v in fam_verdict.items() if v == "ALIVE"]
print(f"\nfamilies ALIVE: {alive if alive else 'NONE'}")

# %%
print("What the grid establishes, in one place:")
for fam in ("A", "B", "C", "E"):
    g = real[real["family"] == fam]
    gl = g[g["n_trades"] > 0]
    if len(gl):
        print(f"  {fam}: {len(g)} configs, best {gl['net_1x_bp'].max():+.1f}"
              f"bp @1x, median {gl['net_1x_bp'].median():+.1f}bp, "
              f"verdict {fam_verdict.get(fam, 'n/a')}")
    else:
        print(f"  {fam}: {len(g)} configs, no trades")
print("\nPlacebo summary (family A coordinates):")
for tag in ("P1_gauss", "P2_calendar"):
    p = league[league["family"] == tag]
    pl = p[p["n_trades"] > 0]
    print(f"  {tag}: best {pl['net_1x_bp'].max():+.1f}bp, "
          f"median {pl['net_1x_bp'].median():+.1f}bp"
          if len(pl) else f"  {tag}: no trades")
