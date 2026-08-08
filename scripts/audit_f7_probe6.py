"""AUDIT probe 6: the two exclusion/entry rules that could be discarding the signal.
  G1  2-5: the only capacity-clearing signature the enrichment z>=3 arm removed. n and net.
  G2  does the 2-consecutive-close persistence filter enter AFTER the reversion?
  G3  per-signature placebo scale, so a single-signature number can be read.
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
spec.loader.exec_module(g)
pd.set_option("display.width", 300)

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg["file_date"])))


def panel(sig):
    x = g.structure_series(par, sig).reindex(common).dropna()
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    return dict(x=x, z=z, shock=g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q),
                persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                & (z.shift(1).abs() >= g.Z_ENTRY),
                first=(z.abs() >= g.Z_ENTRY) & (z.shift(1).abs() < g.Z_ENTRY),
                rt=g.round_trips(sig)["rt_cm2"])


print("=== G1  2-5 (excluded at enrichment z=+2.1, NOT depleted; capacity PASSED) ===")
P25 = panel("2-5")
for h in g.HORIZONS:
    a = g.episodes(P25["x"], P25["z"], P25["persistent"] & P25["shock"], h)
    b = g.episodes(P25["x"], P25["z"], P25["persistent"] & ~P25["shock"], h)
    print(f"  h={h:>2}  shock n={len(a):3d} gross_med {a['gross_bp'].median():+6.3f} "
          f"mean {a['gross_bp'].mean():+6.3f} hit {(a['gross_bp']>0).mean():.2f} "
          f"net@1x(med) {a['gross_bp'].median()-1.8:+6.3f} | noshock n={len(b):3d} "
          f"gross_med {b['gross_bp'].median():+6.3f} | incr "
          f"{a['gross_bp'].median()-b['gross_bp'].median():+6.3f}")
a = g.episodes(P25["x"], P25["z"], P25["persistent"] & P25["shock"], 21)
print("  h=21 shock episodes:")
print(a[["signal_date", "z", "side", "gross_bp"]].to_string(index=False))

print("\n=== G2  entry timing: 2-consecutive-close (registered) vs FIRST |z|>=1 close ===")
for h in [1, 5, 21]:
    pr, fr = [], []
    for sig in uni:
        P = panel(sig)
        a = g.episodes(P["x"], P["z"], P["persistent"] & P["shock"], h)
        b = g.episodes(P["x"], P["z"], P["persistent"] & ~P["shock"], h)
        pr.append(a["gross_bp"].median() - b["gross_bp"].median() if len(a) and len(b) else np.nan)
        a2 = g.episodes(P["x"], P["z"], P["first"] & P["shock"], h)
        b2 = g.episodes(P["x"], P["z"], P["first"] & ~P["shock"], h)
        fr.append(a2["gross_bp"].median() - b2["gross_bp"].median() if len(a2) and len(b2) else np.nan)
    print(f"  h={h:>2}  median incr: persistent {np.nanmedian(pr):+.3f}bp  "
          f"first-touch {np.nanmedian(fr):+.3f}bp   positive: "
          f"{int(np.nansum(np.array(pr) > 0))}/10 vs {int(np.nansum(np.array(fr) > 0))}/10")
# does the fade at |z|>=1 make money at all under first-touch entry?
print("\n  first-touch, book 'all', median gross vs rt:")
for h in [1, 5, 21]:
    line = []
    for sig in uni:
        P = panel(sig)
        t = g.episodes(P["x"], P["z"], P["first"], h)
        line.append(f"{sig}:{t['gross_bp'].median():+.2f}/{P['rt']:.1f}(n{len(t)})")
    print(f"    h={h:>2} " + " ".join(line))

print("\n=== G3  PER-SIGNATURE placebo scale at h=21 (circular-shift shock, 300 draws) ===")
rng = np.random.default_rng(11)
for sig in ["2-5-10", "2-5", "5-10-30"]:
    P = panel(sig)
    real_a = g.episodes(P["x"], P["z"], P["persistent"] & P["shock"], 21)
    real_b = g.episodes(P["x"], P["z"], P["persistent"] & ~P["shock"], 21)
    real = real_a["gross_bp"].median() - real_b["gross_bp"].median()
    d = []
    for _ in range(300):
        k = int(rng.integers(20, len(P["x"]) - 20))
        sh = pd.Series(np.roll(P["shock"].to_numpy(), k), index=P["x"].index)
        aa = g.episodes(P["x"], P["z"], P["persistent"] & sh, 21)
        bb = g.episodes(P["x"], P["z"], P["persistent"] & ~sh, 21)
        if len(aa) and len(bb):
            d.append(aa["gross_bp"].median() - bb["gross_bp"].median())
    d = np.array(d)
    print(f"  {sig:<9} real incr {real:+6.3f}bp   null mean {d.mean():+6.3f} sd {d.std(ddof=1):5.3f}"
          f"   p(null>=real) {float((d >= real).mean()):.3f}   "
          f"shock gross_med {real_a['gross_bp'].median():+6.3f} vs rt {P['rt']:.1f}")
