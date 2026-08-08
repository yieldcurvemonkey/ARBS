"""AUDIT probe 7: the fill-lag monotonicity criterion is registered (H-F7 (8)(a)) as a KILL.
Does it have any power at the n the shock book actually delivers?

Method: the gate's own scale-matched circular-shift null. For each draw, build the SAME
4-point lag profile the gate prints. Under a null with no immediacy premium the profile is
monotone by chance alone; measure that rate, and measure the per-lag noise sd against the
spread of the real profile.
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

P = {}
for sig in uni:
    x = g.structure_series(par, sig).reindex(common).dropna()
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    P[sig] = dict(x=x, z=z, shock=g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q),
                  persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                  & (z.shift(1).abs() >= g.Z_ENTRY))


def profile(shockmap, h):
    out = []
    for lag in g.LAGS:
        v = [g.episodes(P[s]["x"], P[s]["z"], P[s]["persistent"] & shockmap[s], h,
                        lag=lag)["gross_bp"].median() for s in uni]
        out.append(float(np.nanmedian(v)))
    return np.array(out)


def n_per_cell(h):
    return [int(np.median([len(g.episodes(P[s]["x"], P[s]["z"],
                                          P[s]["persistent"] & P[s]["shock"], h, lag=lag))
                           for s in uni])) for lag in g.LAGS]


real_map = {s: P[s]["shock"] for s in uni}
rng = np.random.default_rng(5)
print("lag profile: gate prints the median-across-signatures gross at t+1/2/3/5\n")
for h in g.HORIZONS:
    real = profile(real_map, h)
    mono = (np.all(np.diff(real) <= 0) or np.all(np.diff(real) >= 0))
    draws = []
    for _ in range(120):
        m = {}
        for s in uni:
            k = int(rng.integers(20, len(P[s]["x"]) - 20))
            m[s] = pd.Series(np.roll(P[s]["shock"].to_numpy(), k), index=P[s]["x"].index)
        draws.append(profile(m, h))
    D = np.array(draws)
    nmono = np.mean([(np.all(np.diff(d) <= 0) or np.all(np.diff(d) >= 0)) for d in D])
    print(f"h={h:>2}  real profile {np.round(real, 3)}  monotone={mono}   "
          f"median n/cell {n_per_cell(h)}")
    print(f"      null: per-lag sd {np.round(D.std(axis=0, ddof=1), 3)}  "
          f"spread of real profile (max-min) {real.max()-real.min():.3f}bp")
    print(f"      P(monotone | NULL, no immediacy premium) = {nmono:.2f}  "
          f"-> a non-monotone profile is the null's MODAL outcome, so the KILL "
          f"fires {1-nmono:.0%} of the time on pure noise\n")
