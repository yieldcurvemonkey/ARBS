"""Qualify the h=21 unconditional pond: how much does it move with the block phase?"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib

import numpy as np
import pandas as pd

OUT = pathlib.Path(__file__).resolve().parents[1] / "notebooks" / "data" / "citivelo_rv"
SPREADS = ["10-30", "2-10", "2-30", "5-10", "5-30"]
LO, HI = pd.Timestamp("2023-12-01"), pd.Timestamp("2026-07-21")

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
win = par[(par.index >= LO) & (par.index <= HI)].sort_index()
gate = pd.read_parquet(OUT / "f7_gate.parquet")
ga = gate[gate["book"] == "all"].set_index(["signature", "h"])

print(f"{'sig':>7} {'committed':>10} {'uncond_med':>11} {'off_min':>8} {'off_max':>8} "
      f"{'pond_cmt':>9} {'pond_min':>9} {'pond_max':>9} {'infl':>6}")
for sig in SPREADS:
    a, b = (int(v) for v in sig.split("-"))
    x = ((win[f"{b}Y"] - win[f"{a}Y"]) * 100.0).dropna().to_numpy()
    h = 21
    meds = []
    for o in range(h):
        i = np.arange(o, len(x) - h, h)
        meds.append(float(np.median(np.abs(x[i + h] - x[i]))))
    meds = np.array(meds)
    c = float(ga.loc[(sig, h), "abs_move_med"])
    print(f"{sig:>7} {c:10.3f} {np.median(meds):11.3f} {meds.min():8.3f} {meds.max():8.3f} "
          f"{c / 1.8:9.2f} {meds.min() / 1.8:9.2f} {meds.max() / 1.8:9.2f} "
          f"{c / np.median(meds):6.3f}")

print("\n--- pond/boat under BOTH committed cost lines, h=21, book=all ---")
sub = gate[(gate["book"] == "all") & (gate["h"] == 21)]
out = sub[["signature", "n_legs", "abs_move_med", "rt_cm2", "rt_costmodel"]].copy()
out["pond_cm2"] = (out["abs_move_med"] / out["rt_cm2"]).round(2)
out["pond_costmodel"] = (out["abs_move_med"] / out["rt_costmodel"]).round(2)
print(out.to_string(index=False))
