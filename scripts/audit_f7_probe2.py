"""AUDIT probe 2 for F7: does the episode constructor / pond estimator manufacture the death?

  C1  non-overlap discard: how many eligible entries dropped, are the dropped ones different
  C2  rerun pond + increment with busy_until DISABLED (all eligible entries kept)
  C3  pond measured unconditionally over EVERY overlapping window (not just entry days)
  C4  the momentum mirror (never reported by the gate)
  C5  cost sensitivity: what half-spread would each structure need to clear the pond
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
pd.set_option("display.max_columns", 60)


def episodes_free(x, z, ok, h, lag=1, overlap=True):
    """Same as g.episodes but with the non-overlap lock optionally removed."""
    idx = x.index
    n = len(idx)
    xv, zv = x.to_numpy(), z.to_numpy()
    okv = ok.reindex(idx).fillna(False).to_numpy()
    rows, busy = [], -1
    for i in range(g.Z_WIN, n - lag - h):
        if not okv[i]:
            continue
        blocked = (not overlap) and i <= busy
        side = -np.sign(zv[i])
        if side == 0:
            continue
        e, xo = xv[i + lag], xv[i + lag + h]
        rows.append({"i": i, "signal_date": idx[i], "z": zv[i], "side": side,
                     "gross_bp": float(side * (xo - e)), "abs_move_bp": float(abs(xo - e)),
                     "blocked": bool(blocked)})
        if not blocked:
            busy = i + lag + h
    return pd.DataFrame(rows)


par = pd.read_parquet(OUT / "par_grid_USD_SOFR.parquet")
par.index = pd.to_datetime(par.index)
pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
uni = json.loads((OUT / "f7_universe.json").read_text())["universe"]
dg_all = pd.read_parquet(OUT / "f7_extract_diag.parquet")
fd = pd.to_datetime(dg_all["file_date"])
common = par.index.intersection(pd.DatetimeIndex(fd))

P = {}
for sig in uni:
    x = g.structure_series(par, sig).reindex(common).dropna()
    flow = (pkg[pkg["signature"] == sig].groupby("file_date").size()
            .reindex(x.index, fill_value=0).astype(float))
    z = g.zscore(x, g.Z_WIN)
    shock = g.shock_flags(flow, g.FLOW_WIN, g.SHOCK_Q)
    persistent = (z.abs() >= g.Z_ENTRY) & (np.sign(z) == np.sign(z.shift(1))) \
        & (z.shift(1).abs() >= g.Z_ENTRY)
    P[sig] = dict(x=x, z=z, persistent=persistent, shock=shock, rt=g.round_trips(sig))

print("=== C1/C2 NON-OVERLAP DISCARD, book 'all' ===")
r = []
for sig in uni:
    for h in g.HORIZONS:
        f = episodes_free(P[sig]["x"], P[sig]["z"], P[sig]["persistent"], h)
        kept, drop = f[~f["blocked"]], f[f["blocked"]]
        r.append({
            "sig": sig, "h": h, "eligible": len(f), "kept": len(kept), "dropped": len(drop),
            "absz_kept": kept["z"].abs().median(), "absz_drop": drop["z"].abs().median(),
            "gross_kept": kept["gross_bp"].median(), "gross_drop": drop["gross_bp"].median(),
            "gross_all": f["gross_bp"].median(),
            "amove_kept": kept["abs_move_bp"].median(), "amove_all": f["abs_move_bp"].median(),
            "rt": P[sig]["rt"]["rt_cm2"],
        })
d = pd.DataFrame(r)
d["pond_kept"] = (d["amove_kept"] / d["rt"]).round(2)
d["pond_allelig"] = (d["amove_all"] / d["rt"]).round(2)
print(d.round(3).to_string(index=False))

print("\n=== C3 POND measured UNCONDITIONALLY over every overlapping window ===")
r = []
for sig in uni:
    x = P[sig]["x"]
    rt = P[sig]["rt"]["rt_cm2"]
    rtc = P[sig]["rt"]["rt_costmodel"]
    for h in g.HORIZONS:
        mv = (x.shift(-h) - x).dropna().abs()
        # also the "oracle within window": max favourable excursion, a strictly bigger pond
        arr = x.to_numpy()
        mfe = np.array([np.nanmax(np.abs(arr[i + 1:i + 1 + h] - arr[i]))
                        for i in range(len(arr) - h - 1)])
        r.append({"sig": sig, "h": h, "n": len(mv),
                  "uncond_absmove_med": mv.median(), "p75": mv.quantile(0.75),
                  "p90": mv.quantile(0.90), "mfe_med": float(np.median(mfe)),
                  "rt_cm2": rt, "pond_uncond": round(mv.median() / rt, 2),
                  "pond_mfe": round(float(np.median(mfe)) / rt, 2),
                  "pond_p90": round(mv.quantile(0.90) / rt, 2),
                  "pond_uncond_costmodel": round(mv.median() / rtc, 2)})
print(pd.DataFrame(r).round(3).to_string(index=False))

print("\n=== C4 MOMENTUM MIRROR (gate never reports it; = -gross) ===")
for h in g.HORIZONS:
    line = []
    for sig in uni:
        f = episodes_free(P[sig]["x"], P[sig]["z"], P[sig]["persistent"], h)
        k = f[~f["blocked"]]
        line.append(f"{sig}:{-k['gross_bp'].median():+.2f}/{P[sig]['rt']['rt_cm2']:.1f}")
    print(f"  h={h:>2}  " + "  ".join(line))

print("\n=== C5 HALF-SPREAD each structure would need to clear pond at 1x (h=21) ===")
for sig in uni:
    x = P[sig]["x"]
    mv = (x.shift(-21) - x).dropna().abs().median()
    sw = P[sig]["rt"]["sum_abs_w"]
    print(f"  {sig:<9} uncond |21bd move| med {mv:6.3f}bp  sum|w| {sw:.0f}  "
          f"needs hs <= {mv / (2 * sw):5.3f}bp/leg   (CM-2 charges 0.450; "
          f"CM-2 measured band 0.315-0.528)")

print("\n=== C2b INCREMENT with the non-overlap lock REMOVED ===")
for h in g.HORIZONS:
    incs, incs_lock = [], []
    for sig in uni:
        a = episodes_free(P[sig]["x"], P[sig]["z"], P[sig]["persistent"] & P[sig]["shock"], h)
        b = episodes_free(P[sig]["x"], P[sig]["z"], P[sig]["persistent"] & ~P[sig]["shock"], h)
        incs.append(a["gross_bp"].median() - b["gross_bp"].median())
        ak = g.episodes(P[sig]["x"], P[sig]["z"], P[sig]["persistent"] & P[sig]["shock"], h)
        bk = g.episodes(P[sig]["x"], P[sig]["z"], P[sig]["persistent"] & ~P[sig]["shock"], h)
        incs_lock.append(ak["gross_bp"].median() - bk["gross_bp"].median())
    print(f"  h={h:>2}  median incr NO-LOCK {np.median(incs):+.3f}bp  "
          f"(gate, WITH lock {np.median(incs_lock):+.3f}bp)   "
          f"positive: {int(np.sum(np.array(incs) > 0))}/10 vs "
          f"{int(np.sum(np.array(incs_lock) > 0))}/10")
