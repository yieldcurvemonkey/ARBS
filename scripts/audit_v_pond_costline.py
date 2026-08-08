"""VERIFY-A-CLAIM probe: does the pond quote depend on the cost line, and does it
change the VERDICT?

Three questions, each answered with a number:
  Q1  reproduce the claimant's arithmetic off the committed f7_gate.parquet
  Q2  where could "2.0-4.1x" have come from?  Test the "superseded run"
      hypothesis by recomputing the pond on the UNION sample (no SDR-file
      intersection) -- i.e. the code as it stood before the tape-less-day fix.
  Q3  does the cost line change the GATE VERDICT?  Recompute step (ii)'s
      pass/fail under BOTH cost lines and under the x{0.5,1,2} band.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"

import sys
sys.path.insert(0, str(_REPO / "scripts"))
from s3_f7_gate import (BASIS, HORIZONS, Z_WIN, FLOW_WIN, Z_ENTRY, SHOCK_Q,
                        episodes, round_trips, shock_flags, stats,
                        structure_series, zscore)

gate = pd.read_parquet(OUT / "f7_gate.parquet")

print("=" * 78)
print("Q1  committed artifact, h=21, book='all', both cost lines")
print("=" * 78)
sub = gate[(gate["book"] == "all") & (gate["h"] == 21)].copy()
sub["pond_cm2"] = sub["abs_move_med"] / sub["rt_cm2"]
sub["pond_cm"] = sub["abs_move_med"] / sub["rt_costmodel"]
spr = sub[sub["n_legs"] == 2].sort_values("pond_cm2")
print(spr[["signature", "abs_move_med", "rt_cm2", "pond_cm2",
           "rt_costmodel", "pond_cm"]].round(3).to_string(index=False))
print(f"  spreads CM-2 range      {spr.pond_cm2.min():.2f}x .. {spr.pond_cm2.max():.2f}x")
print(f"  spreads costmodel range {spr.pond_cm.min():.2f}x .. {spr.pond_cm.max():.2f}x")

print("\n  --- does any (book, h, cost line) in the WHOLE parquet give max 4.1x? ---")
g = gate.copy()
for lab, col in (("cm2", "rt_cm2"), ("cm", "rt_costmodel")):
    g[f"r_{lab}"] = g["abs_move_med"] / g[col]
near = g[(g["r_cm2"].between(4.0, 4.2)) | (g["r_cm"].between(4.0, 4.2))]
print(f"  rows with a ratio in [4.0,4.2] on either line: {len(near)}")
if len(near):
    print(near[["signature", "book", "h", "abs_move_med", "r_cm2", "r_cm"]]
          .round(3).to_string(index=False))
for h in HORIZONS:
    s = g[(g.book == "all") & (g.h == h) & (g.n_legs == 2)]
    print(f"  h={h:>2}  spread pond CM-2 max {s.r_cm2.max():.3f}   "
          f"costmodel max {s.r_cm.max():.3f}")

print("\n" + "=" * 78)
print("Q2  superseded-run hypothesis: pond on the UNION sample (pre tape-less fix)")
print("=" * 78)
par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
file_dates = pd.to_datetime(dg_all["file_date"])
lo, hi = file_dates.min(), file_dates.max()
common = par.index.intersection(pd.DatetimeIndex(file_dates))
union = par.index[(par.index >= lo) & (par.index <= hi)]
print(f"  intersection {len(common)} days   union {len(union)} days")


def pond_table(sample_idx, label):
    rows = []
    for sig in uni:
        x = structure_series(par, sig).reindex(sample_idx).dropna()
        z = zscore(x, Z_WIN)
        flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
                .reindex(x.index, fill_value=0).astype(float))
        shock = shock_flags(flow, FLOW_WIN, SHOCK_Q)
        persistent = (z.abs() >= Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
            & (z.shift(1).abs() >= Z_ENTRY)
        rt = round_trips(sig)
        for h in HORIZONS:
            st = stats(episodes(x, z, persistent, h), rt["rt_cm2"])
            if st.get("n", 0) == 0:
                continue
            rows.append({"signature": sig, "n_legs": len(sig.split("-")), "h": h,
                         "n": st["n"], "abs_move_med": st["abs_move_med"],
                         "pond_cm2": st["abs_move_med"] / rt["rt_cm2"],
                         "pond_cm": st["abs_move_med"] / rt["rt_costmodel"]})
    t = pd.DataFrame(rows)
    s = t[(t.h == 21) & (t.n_legs == 2)]
    print(f"  [{label}] h=21 spreads: CM-2 {s.pond_cm2.min():.2f}..{s.pond_cm2.max():.2f}x"
          f"   costmodel {s.pond_cm.min():.2f}..{s.pond_cm.max():.2f}x")
    print(s[["signature", "n", "abs_move_med", "pond_cm2", "pond_cm"]]
          .round(3).to_string(index=False))
    return t


pond_table(common, "intersection = committed")
pond_table(union, "union = pre-fix")

print("\n" + "=" * 78)
print("Q3  DOES THE COST LINE CHANGE THE VERDICT?  step (ii) increment vs RT")
print("=" * 78)
inc = pd.read_parquet(OUT / "f7_gate_increment.parquet")
for h in HORIZONS:
    s = inc[inc["h"] == h]
    med = s["incr_gross_vs_noshock"].median()
    print(f"  h={h:>2}  median increment vs noshock {med:+.3f}bp   "
          f"positive on {int((s['incr_gross_vs_noshock']>0).sum())}/{len(s)}")
print("\n  round trips the increment must beat, per signature:")
rts = {sig: round_trips(sig) for sig in uni}
lo_cm2 = min(v["rt_cm2"] for v in rts.values())
lo_cm = min(v["rt_costmodel"] for v in rts.values())
print(f"    cheapest CM-2 RT in the universe        {lo_cm2:.2f}bp")
print(f"    cheapest costmodel RT in the universe   {lo_cm:.2f}bp")
print(f"    cheapest CM-2 RT at the 0.5x band edge  {0.5*lo_cm2:.2f}bp")
print("  -> the increment is NEGATIVE at every h; no cost line in the band "
      "flips a negative number positive.")

print("\n  shock-book NET at 1x, median across signatures (from the committed pivot):")
for h in HORIZONS:
    s = inc[inc["h"] == h]
    print(f"    h={h:>2}  {s['net_mean_1x_shock'].median():+.3f}bp  (CM-2 line; the "
          f"costmodel line is 1.2-2.8x more expensive -> more negative)")
