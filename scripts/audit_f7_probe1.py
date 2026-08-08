"""AUDIT probe 1 for F7: integrity, hand-recompute of gross_bp, walk-forward truncation.

Read-only. Writes nothing into the committed artifact set.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import importlib.util
import json
import pathlib

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"

spec = importlib.util.spec_from_file_location("g", _REPO / "scripts" / "s3_f7_gate.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)          # module has a __main__ guard, safe to import

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 60)

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
file_dates = pd.to_datetime(dg_all["file_date"])
lo, hi = file_dates.min(), file_dates.max()
common = par.index.intersection(pd.DatetimeIndex(file_dates))

print("=== A. INDEX INTEGRITY ===")
print(f"n files in diag        : {len(file_dates)}  unique {file_dates.nunique()}")
print(f"common monotonic       : {common.is_monotonic_increasing}")
print(f"common dupes           : {int(pd.Index(common).duplicated().sum())}  len {len(common)}")
print(f"file_dates dupes       : {int(file_dates.duplicated().sum())}")
print(f"file_dates on weekends : {int((file_dates.dt.dayofweek >= 5).sum())}")
gaps = pd.Series(common).diff().dt.days.dropna()
print(f"common day-gaps        : max {gaps.max():.0f}  #gap>3d {int((gaps > 3).sum())}  "
      f"#gap>7d {int((gaps > 7).sum())}")
# how much calendar time does a 21-ROW horizon really span?
cal21 = (pd.Series(common).shift(-21) - pd.Series(common)).dt.days.dropna()
print(f"calendar days spanned by h=21 rows: median {cal21.median():.0f} "
      f"(a clean 21bd span would be ~29-31)")

print("\n=== B. HAND-RECOMPUTE gross_bp FROM RAW PAR COLUMNS ===")
for sig, h in [("10-30", 21), ("5-10-30", 21), ("2-10", 5)]:
    x = g.structure_series(par, sig).reindex(common).dropna()
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    shock = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
    persistent = (z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
        & (z.shift(1).abs() >= g.Z_ENTRY)
    tr = g.episodes(x, z, persistent, h)
    print(f"\n--- {sig} h={h}  n={len(tr)}  gate gross_med={tr['gross_bp'].median():+.4f}")
    t = [int(v) for v in sig.split("-")]
    w = g.weights(sig)
    show = tr.head(3)
    for _, r in show.iterrows():
        ed, xd = r["entry_date"], r["exit_date"]
        legs_e = {k: par.loc[ed, f"{k}Y"] for k in t}
        legs_x = {k: par.loc[xd, f"{k}Y"] for k in t}
        s_e = sum(w[k] * legs_e[k] for k in t) * 100.0
        s_x = sum(w[k] * legs_x[k] for k in t) * 100.0
        # trailing mean at the SIGNAL date, computed from scratch off the same panel
        sd = r["signal_date"]
        hist = x.loc[:sd].iloc[-g.Z_WIN:]
        mu, sg = hist.mean(), hist.std(ddof=1)
        z_hand = (x.loc[sd] - mu) / sg
        side_hand = -np.sign(z_hand)
        gross_hand = side_hand * (s_x - s_e)
        print(f"  sig {sd.date()} entry {ed.date()} exit {xd.date()}")
        print(f"    legs@entry {legs_e}  -> struct {s_e:+.4f}bp")
        print(f"    legs@exit  {legs_x}  -> struct {s_x:+.4f}bp")
        print(f"    trailing60 mean {mu:+.4f} sd {sg:.4f}  z_hand {z_hand:+.4f} "
              f"(gate z {r['z']:+.4f})   side_hand {side_hand:+.0f} (gate {r['side']:+.0f})")
        print(f"    ABOVE mean by {x.loc[sd] - mu:+.4f}bp -> fading means betting it FALLS")
        print(f"    struct moved {s_x - s_e:+.4f}bp  gross_hand {gross_hand:+.4f} "
              f"(gate {r['gross_bp']:+.4f})  MATCH={abs(gross_hand - r['gross_bp']) < 1e-9}")

print("\n=== C. WALK-FORWARD TRUNCATION (z and shock use only data <= t) ===")
sig = "5-10-30"
x = g.structure_series(par, sig).reindex(common).dropna()
flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
        .reindex(x.index, fill_value=0).astype(float))
z_full = g.zscore(x, g.Z_WIN)
sh_full = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
bad_z = bad_s = 0
for cut in range(200, len(x), 37):
    t = x.index[cut]
    zt = g.zscore(x.iloc[:cut + 1], g.Z_WIN).iloc[-1]
    st = g.shock_flags(flow.iloc[:cut + 1], g.FLOW_WIN, g.SHOCK_Q).iloc[-1]
    if not (np.isnan(zt) and np.isnan(z_full.loc[t])) and abs(zt - z_full.loc[t]) > 1e-12:
        bad_z += 1
    if bool(st) != bool(sh_full.loc[t]):
        bad_s += 1
print(f"truncation mismatches: z {bad_z}, shock {bad_s} (0/0 == strictly causal)")

print("\n=== D. FLOW COUNT BY HAND ===")
for sig in ["5-10-30", "10-30"]:
    sub = pkg[pkg["signature"] == sig]
    d = sub["file_date"].value_counts().sort_index()
    day = d.index[len(d) // 2]
    hand = int((pkg["signature"].eq(sig) & pkg["file_date"].eq(day)).sum())
    x = g.structure_series(par, sig).reindex(common).dropna()
    fl = (sub.groupby("file_date").size().reindex(x.index, fill_value=0).astype(float))
    print(f"{sig} {day.date()}: hand {hand}  gate {fl.get(day, float('nan')):.0f}  "
          f"zero-flow days in sample {int((fl == 0).sum())}/{len(fl)}")
    thr = fl.shift(1).rolling(60, min_periods=60).quantile(0.90)
    fired = (fl >= thr) & thr.notna()
    ties = ((fl == thr) & thr.notna()).sum()
    print(f"    shock fired {int(fired.sum())}/{int(thr.notna().sum())} eligible "
          f"({fired.sum() / max(1, thr.notna().sum()):.1%}); ties at threshold {int(ties)}; "
          f"thr median {thr.median():.1f}")
