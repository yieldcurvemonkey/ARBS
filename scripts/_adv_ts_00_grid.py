"""Adversarial pass 0: re-derive the accounting and headline numbers from tsgrid_grid.csv."""
from __future__ import annotations
import pathlib
import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "backtests" / "etf_rebalance" / "_data"
g = pd.read_csv(DATA / "tsgrid_grid.csv")
print("rows", len(g))
print(g.dtypes)
print("\nsignal x kind counts:")
print(g.groupby(["signal", "kind"]).size())
print("\north counts by signal:")
print(g.groupby(["signal", "orth"]).size())
print("\nlag counts:", g.groupby("lag").size().to_dict())

HOLD = ["active_w", "active_rel", "bucket_active", "bucket_hist_z", "flow", "ownership", "not_held"]
CAL = ["deletion", "addition"]
CTRL = ["resid"]

real = g[g["kind"] == "real"]
plac = g[g["kind"] == "placebo"]
h = g[g["signal"].isin(HOLD)]
c = g[g["signal"].isin(CAL)]
ct = g[g["signal"].isin(CTRL)]
print("\ncell counts: real %d placebo %d holdings %d cal %d ctrl %d" % (len(real), len(plac), len(h), len(c), len(ct)))

for nm, d in [("holdings", h), ("calendar", c), ("control", ct), ("placebo", plac), ("ALL real", real)]:
    if not len(d):
        continue
    be = d["gross_bp"] / d["cost_measured"]
    print(f"\n{nm}: n={len(d)} max_gross={d['gross_bp'].max():.4f} max|t|={d['t_nw'].abs().max():.2f} "
          f"med|t|={d['t_nw'].abs().median():.2f} max_breakeven={be.max():.4f}x "
          f"p99|t|={d['t_nw'].abs().quantile(0.99):.2f}")

# net > 0 counts
print("\n--- net>0 at various multipliers (real only, all anchors) ---")
for a in ["measured", "flat", "sr1170"]:
    line = []
    for mult in [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0]:
        n = int((real["gross_bp"] - mult * real["cost_" + a] > 0).sum())
        line.append(f"{mult}:{n}")
    print(a, " ".join(line), " of", len(real))

# reconcile the two "best cell" claims
print("\n--- §5 claim: deletion orth mark15 entry15 hold1 exit15 ---")
q = g[(g.signal == "deletion") & (g.orth == True) & (g["mark"] == 15) & (g.entry == 15)
      & (g.hold == 1) & (g["exit"] == 15)]
print(q.to_string(index=False))
print("\n--- SUMMARY claim: deletion orth lag1 mark10 entry10 hold21 exit10 ---")
q2 = g[(g.signal == "deletion") & (g.orth == True) & (g.lag == 1) & (g["mark"] == 10)
       & (g.entry == 10) & (g.hold == 21) & (g["exit"] == 10)]
print(q2.to_string(index=False))

print("\n--- top 10 real by |t| ---")
r2 = real.reindex(real["t_nw"].abs().sort_values(ascending=False).index).head(12)
print(r2.to_string(index=False))
print("\n--- top 6 holdings by gross ---")
print(h.sort_values("gross_bp", ascending=False).head(6).to_string(index=False))
print("\n--- top 6 holdings by |t| ---")
print(h.reindex(h["t_nw"].abs().sort_values(ascending=False).index).head(6).to_string(index=False))
print("\n--- top 6 placebo by |t| ---")
print(plac.reindex(plac["t_nw"].abs().sort_values(ascending=False).index).head(6).to_string(index=False))

# cost distribution
print("\ncost_measured over cells: med %.4f mean %.4f p10 %.4f p90 %.4f" %
      (g.cost_measured.median(), g.cost_measured.mean(), g.cost_measured.quantile(.1), g.cost_measured.quantile(.9)))
print("gross/pf: max %.4f min %.4f" % (g.gross_over_pf.max(), g.gross_over_pf.min()))
