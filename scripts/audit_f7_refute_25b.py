"""AUDIT REFUTE addendum:
  A. the STRONGEST form of the claim -- treat the whole excluded set as if the
     enrichment filter had hidden it. What is its aggregate increment?
  B. the registered wrong-day placebo re-run on the 11-signature universe, so the
     verdict step itself (not just the headline median) is re-decided with 2-5 in.
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
pd.set_option("display.width", 320)

par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
dg = pd.read_parquet(OUT / "f7_extract_diag.parquet")
common = par.index.intersection(pd.DatetimeIndex(pd.to_datetime(dg["file_date"])))

UNI10 = json.loads((OUT / "f7_universe.json").read_text())["universe"]
EXCL = ["2-5", "5-7", "7-10", "7-30", "10-15-20", "15-20-30", "7-10-15", "2-5-30"]


def panel(sig):
    x = g.structure_series(par, sig).reindex(common).dropna()
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    return dict(x=x, z=z, shock=g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q),
                persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                & (z.shift(1).abs() >= g.Z_ENTRY),
                rt=g.round_trips(sig)["rt_cm2"])


PE = {s: panel(s) for s in EXCL}
P10 = {s: panel(s) for s in UNI10}

print("=== A. the excluded set taken AS A WHOLE (strongest form of the claim) ===")
for h in g.HORIZONS:
    inc_e, inc_r = [], []
    for s in EXCL:
        Q = PE[s]
        a = g.episodes(Q["x"], Q["z"], Q["persistent"] & Q["shock"], h)
        b = g.episodes(Q["x"], Q["z"], Q["persistent"] & ~Q["shock"], h)
        if len(a) and len(b):
            inc_e.append(a["gross_bp"].median() - b["gross_bp"].median())
    for s in UNI10:
        Q = P10[s]
        a = g.episodes(Q["x"], Q["z"], Q["persistent"] & Q["shock"], h)
        b = g.episodes(Q["x"], Q["z"], Q["persistent"] & ~Q["shock"], h)
        if len(a) and len(b):
            inc_r.append(a["gross_bp"].median() - b["gross_bp"].median())
    print(f"  h={h:>2}  EXCLUDED median incr {np.median(inc_e):+.3f}bp (n={len(inc_e)})   "
          f"REGISTERED median incr {np.median(inc_r):+.3f}bp (n={len(inc_r)})   "
          f"bar to clear = +1.8bp (spread) / +3.6bp (fly)")

print("\n=== B. registered wrong-day placebo, 11-signature universe, 200 draws ===")
P11 = dict(P10)
P11["2-5"] = PE["2-5"]
rng = np.random.default_rng(20260809)
for h in g.HORIZONS:
    real = float(np.median([
        (lambda a, b: a["gross_bp"].median() - b["gross_bp"].median())(
            g.episodes(Q["x"], Q["z"], Q["persistent"] & Q["shock"], h),
            g.episodes(Q["x"], Q["z"], Q["persistent"] & ~Q["shock"], h))
        for Q in P11.values()]))
    draws = []
    for _ in range(200):
        incs = []
        for sig, Q in P11.items():
            k = int(rng.integers(20, len(Q["x"]) - 20))
            sh = pd.Series(np.roll(Q["shock"].to_numpy(), k), index=Q["x"].index)
            a = g.episodes(Q["x"], Q["z"], Q["persistent"] & sh, h)
            b = g.episodes(Q["x"], Q["z"], Q["persistent"] & ~sh, h)
            if len(a) and len(b):
                incs.append(float(a["gross_bp"].median() - b["gross_bp"].median()))
        if incs:
            draws.append(float(np.median(incs)))
    d = np.array(draws)
    print(f"  h={h:>2}  real {real:+.3f}bp   null mean {d.mean():+.3f} sd {d.std(ddof=1):.3f}"
          f"  [p05 {np.percentile(d,5):+.3f}, p95 {np.percentile(d,95):+.3f}]  "
          f"p(null>=real) = {float((d>=real).mean()):.3f}")
