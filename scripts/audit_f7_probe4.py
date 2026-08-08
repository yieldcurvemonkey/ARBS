"""AUDIT probe 4: independent mark. Traded Part 43 package rates (DECIMAL, x10000 -> bp)
vs the Citi banked par grid the gate marks on.

If the traded structure dislocates several bp while the grid structure barely moves, the
grid is smoothing away the pond and the fly death is a mark artifact. If the two track,
the grid is a faithful mark and the small fly pond is real.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import importlib.util
import pathlib

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
spec = importlib.util.spec_from_file_location("g", _REPO / "scripts" / "s3_f7_gate.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
pd.set_option("display.width", 300)

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg["file_date"])))

print("scale check: one 5-10-30 package, legs in DECIMAL -> bp")
s0 = pkg[pkg.signature == "5-10-30"].iloc[0]
r0 = [float(v) for v in s0["rates"].split(",")]
print(f"  {s0['file_date'].date()} legs {r0} -> as %: {[round(v*100,4) for v in r0]}")
print(f"  grid same day 5Y/10Y/30Y: "
      f"{[round(par.loc[s0['file_date'], f'{k}Y'], 4) for k in (5, 10, 30)]}\n")

for sig in ["5-10-30", "2-5-10", "5-7-10", "10-15-30", "10-20-30", "10-30", "5-10"]:
    t = [int(v) for v in sig.split("-")]
    w = g.weights(sig)
    sub = pkg[pkg["signature"] == sig].copy()
    R = sub["rates"].str.split(",", expand=True).apply(pd.to_numeric, errors="coerce")
    if R.shape[1] != len(t):
        print(f"{sig}: bad rate cols"); continue
    sub["traded_bp"] = (sum(w[t[j]] * R[j] for j in range(len(t))) * 10000.0).to_numpy()
    grid = g.structure_series(par, sig)
    sub["grid_bp"] = grid.reindex(sub["file_date"]).to_numpy()
    sub = sub.dropna(subset=["traded_bp", "grid_bp"])
    dev = sub["traded_bp"] - sub["grid_bp"]

    day = sub.groupby("file_date").agg(traded=("traded_bp", "median"),
                                       sd=("traded_bp", "std"), n=("traded_bp", "size"))
    day["grid"] = grid.reindex(day.index).to_numpy()
    day = day[day["n"] >= 5].dropna()
    gd = grid.reindex(common).dropna()
    corr = day[["traded", "grid"]].diff().dropna().corr().iloc[0, 1]
    print(f"{sig:<9} n={len(sub):6d} days>=5pk {len(day):4d}")
    print(f"   traded-vs-grid dev  : med {dev.median():+7.2f}bp  IQR "
          f"{dev.quantile(.25):+.2f}..{dev.quantile(.75):+.2f}  sd {dev.std():.2f}")
    print(f"   DAILY MOVE  med|d|  : traded {day['traded'].diff().abs().median():6.3f}bp   "
          f"grid {gd.diff().abs().median():6.3f}bp   ratio "
          f"{day['traded'].diff().abs().median() / gd.diff().abs().median():.2f}x   "
          f"corr(d_traded, d_grid) = {corr:+.3f}")
    print(f"   within-day sd of traded structure: med {day['sd'].median():.3f}bp "
          f"(execution noise around the day's level)")
