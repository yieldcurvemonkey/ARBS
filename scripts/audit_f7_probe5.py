"""AUDIT probe 5:
  F1  is the committed self-test BLIND to a fade-sign inversion? (mutate, expect failure)
  F2  pond on the INDEPENDENT mark (daily-median traded package structure from Part 43)
  F3  do the universe-excluded signatures hide a survivor?
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

print("=== F1 SIGN MUTANT vs the committed self-test ===")
orig = g.episodes


def episodes_signflip(x, z, enter_ok, h, lag=1):
    idx, n = x.index, len(x)
    xv, zv = x.to_numpy(), z.to_numpy()
    ok = enter_ok.reindex(idx).fillna(False).to_numpy()
    rows, busy = [], -1
    for i in range(g.Z_WIN, n - lag - h):
        if i <= busy or not ok[i]:
            continue
        side = +np.sign(zv[i])                       # <-- MUTANT: momentum, not fade
        if side == 0:
            continue
        e, xo = xv[i + lag], xv[i + lag + h]
        rows.append({"signal_date": idx[i], "entry_date": idx[i + lag],
                     "exit_date": idx[i + lag + h], "z": zv[i], "side": side,
                     "gross_bp": float(side * (xo - e)), "abs_move_bp": float(abs(xo - e))})
        busy = i + lag + h
    return pd.DataFrame(rows)


g.episodes = episodes_signflip
try:
    g.selftest()
    print("  !!! SELF-TEST PASSED WITH THE SIGN INVERTED -- the test is BLIND to it.")
except SystemExit as exc:
    print(f"  self-test correctly FAILED under a sign flip: {exc}")
finally:
    g.episodes = orig

# a second mutant: shock threshold that never fires
print("\n=== F1b threshold-never-fires check (does the gate notice an empty shock book?) ===")
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
    P[sig] = dict(x=x, z=z, flow=flow, shock=g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q),
                  persistent=(z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1)))
                  & (z.shift(1).abs() >= g.Z_ENTRY), rt=g.round_trips(sig))
for sig in uni:
    sh, fl = P[sig]["shock"], P[sig]["flow"]
    elig = g.shock_flags(fl, g.FLOW_WIN, g.SHOCK_Q).notna().sum()
    thr = fl.shift(1).rolling(60, min_periods=60).quantile(0.90)
    print(f"  {sig:<9} shock {int(sh.sum()):3d}/{int(thr.notna().sum())} eligible "
          f"({sh.sum()/max(1,thr.notna().sum()):5.1%})  flow>0 on "
          f"{(fl>0).mean():.1%} of days  thr med {thr.median():5.1f}  "
          f"flow p90 (whole sample) {fl.quantile(0.9):5.1f}")

print("\n=== F2 POND ON THE INDEPENDENT MARK (Part 43 daily-median traded structure) ===")
print("    (restricted to date pairs exactly h business days apart, both days present)")
for sig in uni:
    t = [int(v) for v in sig.split("-")]
    w = g.weights(sig)
    sub = pkg[pkg["signature"] == sig].copy()
    R = sub["rates"].str.split(",", expand=True).apply(pd.to_numeric, errors="coerce")
    sub["traded_bp"] = (sum(w[t[j]] * R[j] for j in range(len(t))) * 10000.0).to_numpy()
    sub = sub.dropna(subset=["traded_bp"])
    day = sub.groupby("file_date")["traded_bp"].agg(["median", "size"])
    day = day[day["size"] >= 5]["median"]
    bd = pd.DatetimeIndex(common)
    pos = {d: i for i, d in enumerate(bd)}
    rt = P[sig]["rt"]["rt_cm2"]
    line = [f"{sig:<9} rt {rt:.1f}bp  days {len(day):4d} |"]
    for h in g.HORIZONS:
        mv, mvg = [], []
        gr = P[sig]["x"]
        for d, v in day.items():
            i = pos.get(d)
            if i is None or i + h >= len(bd):
                continue
            d2 = bd[i + h]
            if d2 in day.index:
                mv.append(abs(day[d2] - v))
                mvg.append(abs(gr.get(d2, np.nan) - gr.get(d, np.nan)))
        if len(mv) >= 20:
            m, mg = float(np.nanmedian(mv)), float(np.nanmedian(mvg))
            line.append(f" h{h}: tape {m:6.3f}bp ({m/rt:4.2f}x) grid {mg:6.3f} ({mg/rt:4.2f}x) n{len(mv):4d}")
        else:
            line.append(f" h{h}: n<20")
    print("".join(line))

print("\n=== F3 UNIVERSE-EXCLUDED SIGNATURES: would any have survived? ===")
cap = pd.read_parquet(OUT / "f7_capacity.parquet")
print(cap.head(3).to_string(index=False))
extra = ["10-15-20", "15-20-30", "7-10-15", "2-5-30", "2-5", "5-7", "7-10", "7-30"]
for sig in extra:
    try:
        x = g.structure_series(par, sig).reindex(common).dropna()
    except KeyError:
        print(f"  {sig}: leg not on the grid"); continue
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    sh = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
    per = (z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
        & (z.shift(1).abs() >= g.Z_ENTRY)
    rt = g.round_trips(sig)["rt_cm2"]
    out = []
    for h in g.HORIZONS:
        mv = (x.shift(-h) - x).dropna().abs().median()
        a = g.episodes(x, z, per & sh, h)
        b = g.episodes(x, z, per & ~sh, h)
        inc = (a["gross_bp"].median() - b["gross_bp"].median()) if len(a) and len(b) else np.nan
        out.append(f"h{h}: pond {mv/rt:4.2f}x  shock_gross "
                   f"{a['gross_bp'].median() if len(a) else np.nan:+6.2f}  incr {inc:+6.2f}")
    print(f"  {sig:<9} rt {rt:.1f}  flow {int(flow.sum()):6d}  " + " | ".join(out))
